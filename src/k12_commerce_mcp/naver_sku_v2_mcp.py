"""SKU v2 GET: documented alphanumeric subset, closed catalog projection.

Local safety bounds: display text <=200, nested alliances <=1000. No claim
that these bounds restrict the provider's complete schema. Non-subset path
ids never dispatch; no unverified percent-encoding or v1 fallback.
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timedelta
from typing import Any, Literal

from pydantic import StrictBool, StrictFloat, StrictInt, StrictStr

from .models.common import CanonicalModel
from .security import assert_agent_safe_value, safe_display_value

SKU_PREFIX = "/v2/logistics/products/sellers/me/skus"
SKU_PATH = SKU_PREFIX + "/{ns_id}"
SKU_OP = "get-ns-detail-nfa-product"
SKU_ID = re.compile(r"[A-Za-z0-9]{1,20}")


class LinkedAlliance(CanonicalModel):
    allianceId: StrictStr
    allianceLinkedYmdt: StrictStr


class SkuCatalog(CanonicalModel):
    nsId: StrictStr
    nsBarcode: StrictStr | None = None
    nsName: StrictStr | None = None
    storageTemperature: Literal["DRY", "WET", "FROZEN"] | None = None
    shelfLifeManagement: StrictBool | None = None
    lotNoManagement: StrictBool | None = None
    pieceWidth: StrictInt | StrictFloat | None = None
    pieceLength: StrictInt | StrictFloat | None = None
    pieceHeight: StrictInt | StrictFloat | None = None
    pieceWeight: StrictInt | StrictFloat | None = None
    nsType: Literal["MAIN", "FREEBIE"] | None = None
    collectRequired: StrictBool | None = None
    defectiveInventoryTreatmentType: Literal["RETURN", "DISPOSAL"] | None = None
    refurbish: StrictBool | None = None
    inspectionType: Literal["GENERAL", "FASHION"] | None = None
    normalInventoryTreatmentType: Literal["RESELL", "RETURN", "DISPOSAL"] | None = None
    reconditionTreatmentType: Literal["NONE", "GENERAL", "BRAND"] | None = None
    linkedAlliances: tuple[LinkedAlliance, ...] = ()
    registrationYmdt: StrictStr
    modificationYmdt: StrictStr


class SkuRead(CanonicalModel):
    channel: Literal["naver"] = "naver"
    operation_id: Literal["get-ns-detail-nfa-product"] = SKU_OP
    status: Literal["complete", "incomplete", "invalid_request", "unavailable"]
    reasons: tuple[str, ...] = ()
    item: SkuCatalog | None = None


_ENUMS = {
    "storageTemperature": ("DRY", "WET", "FROZEN"),
    "nsType": ("MAIN", "FREEBIE"),
    "defectiveInventoryTreatmentType": ("RETURN", "DISPOSAL"),
    "inspectionType": ("GENERAL", "FASHION"),
    "normalInventoryTreatmentType": ("RESELL", "RETURN", "DISPOSAL"),
    "reconditionTreatmentType": ("NONE", "GENERAL", "BRAND"),
}
_BOOL_FIELDS = ("shelfLifeManagement", "lotNoManagement", "collectRequired", "refurbish")
_NUMBER_FIELDS = ("pieceWidth", "pieceLength", "pieceHeight", "pieceWeight")


def _result(status: str, reason: str | None = None, item: dict | None = None) -> SkuRead:
    return SkuRead.model_validate(
        {"status": status, "reasons": [reason] if reason else [], "item": item}
    )


def _text(value: object) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= 200
        and value == value.strip()
        and all(ord(c) >= 32 and ord(c) != 127 for c in value)
        and safe_display_value(value) is not None
    )


def _kst(value: object) -> bool:
    if not isinstance(value, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?\+09:00", value
    ):
        return False
    try:
        return datetime.fromisoformat(value).utcoffset() == timedelta(hours=9)
    except ValueError:
        return False


def _project(payload: object, ns_id: str) -> SkuRead:
    def invalid() -> SkuRead:
        return _result("incomplete", "invalid_provider_shape")

    if not isinstance(payload, dict) or payload.get("nsId") != ns_id:
        return invalid()
    if not all(_kst(payload.get(key)) for key in ("registrationYmdt", "modificationYmdt")):
        return invalid()
    for key, choices in _ENUMS.items():
        value = payload.get(key)
        if value is not None and (not isinstance(value, str) or value not in choices):
            return invalid()
    for key in _BOOL_FIELDS:
        if payload.get(key) is not None and type(payload[key]) is not bool:
            return invalid()
    for key in _NUMBER_FIELDS:
        value = payload.get(key)
        if value is not None and (type(value) not in (int, float) or not math.isfinite(value)):
            return invalid()
    barcode = payload.get("nsBarcode")
    if barcode is not None and (
        not isinstance(barcode, str)
        or re.fullmatch(r"[A-Za-z0-9 ._-]{1,100}", barcode) is None
        or barcode != barcode.strip()
    ):
        return invalid()
    if payload.get("nsName") is not None and not _text(payload["nsName"]):
        return invalid()
    alliances = payload.get("linkedAlliances")
    # Missing/non-array is incomplete, not silently interpreted as no alliances.
    if not isinstance(alliances, list) or len(alliances) > 1000:
        return invalid()
    projected = []
    for row in alliances:
        if not isinstance(row, dict) or not (
            _text(row.get("allianceId")) and _kst(row.get("allianceLinkedYmdt"))
        ):
            return invalid()
        projected.append({key: row[key] for key in ("allianceId", "allianceLinkedYmdt")})
    item = {key: payload.get(key) for key in SkuCatalog.model_fields if key != "linkedAlliances"}
    item["linkedAlliances"] = projected
    try:
        result = _result("complete", item=item)
        assert_agent_safe_value(result)
    except ValueError:
        return _result("incomplete", "unsafe_provider_value")
    return result


async def read_sku(client: Any | None, ns_id: object) -> SkuRead:
    if not isinstance(ns_id, str) or SKU_ID.fullmatch(ns_id) is None:
        return _result("invalid_request", "invalid_request")
    if client is None:
        return _result("unavailable", "client_not_configured")
    try:
        payload = await client._request(
            "GET",
            SKU_PATH.format(ns_id=ns_id),
            query=None,
            access_token=await client._access_token(),
        )
    except Exception:
        return _result("unavailable", "provider_unavailable")
    return _project(payload, ns_id)
