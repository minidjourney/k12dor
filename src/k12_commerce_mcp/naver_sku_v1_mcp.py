"""Deprecated SKU v1: independent GET and absent-preserving catalog.

Local bounds (text 200, alliances 1000) are not provider maxima. Version 2
fields/readers and transport fallback are not used. Deprecation remains
explicit in the tool description; complete means this safe response only.
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timedelta
from typing import Any, Literal

from pydantic import StrictBool, StrictFloat, StrictInt, StrictStr
from pydantic.experimental.missing_sentinel import MISSING

from .models.common import CanonicalModel
from .security import assert_agent_safe_value

SKU_V1_PREFIX = "/v1/logistics/products/sellers/me/skus"
SKU_V1_ID = re.compile(r"[A-Za-z0-9]{1,20}")


class V1Alliance(CanonicalModel):
    allianceId: StrictStr
    allianceLinkedYmdt: StrictStr


class V1SkuCatalog(CanonicalModel):
    nsId: StrictStr
    registrationYmdt: StrictStr
    modificationYmdt: StrictStr
    nsBarcode: StrictStr | None | MISSING = MISSING
    nsName: StrictStr | None | MISSING = MISSING
    storageTemperature: Literal["DRY", "WET", "FROZEN"] | None | MISSING = MISSING
    shelfLifeManagement: StrictBool | None | MISSING = MISSING
    lotNoManagement: StrictBool | None | MISSING = MISSING
    pieceWidth: StrictInt | StrictFloat | None | MISSING = MISSING
    pieceLength: StrictInt | StrictFloat | None | MISSING = MISSING
    pieceHeight: StrictInt | StrictFloat | None | MISSING = MISSING
    pieceWeight: StrictInt | StrictFloat | None | MISSING = MISSING
    nsType: Literal["MAIN", "FREEBIE"] | None | MISSING = MISSING
    linkedAlliances: tuple[V1Alliance, ...] | MISSING = MISSING


class V1SkuRead(CanonicalModel):
    channel: Literal["naver"] = "naver"
    operation_id: Literal["get-ns-detail-1-nfa-product"] = "get-ns-detail-1-nfa-product"
    status: Literal["complete", "incomplete", "invalid_request", "unavailable"]
    reasons: tuple[str, ...] = ()
    item: V1SkuCatalog | None = None


def _result(status: str, reason: str | None = None, item: dict | None = None) -> V1SkuRead:
    return V1SkuRead.model_validate(
        {"status": status, "reasons": [reason] if reason else [], "item": item}
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


def _text(value: object) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= 200
        and value == value.strip()
        and all(ord(c) >= 32 and ord(c) != 127 for c in value)
        and "<" not in value
        and ">" not in value
    )


def _project(payload: object, ns_id: str) -> V1SkuRead:
    invalid = _result("incomplete", "invalid_provider_shape")
    if not isinstance(payload, dict) or payload.get("nsId") != ns_id:
        return invalid
    if not all(_kst(payload.get(key)) for key in ("registrationYmdt", "modificationYmdt")):
        return invalid
    for key in ("shelfLifeManagement", "lotNoManagement"):
        if payload.get(key) is not None and type(payload[key]) is not bool:
            return invalid
    for key in ("pieceWidth", "pieceLength", "pieceHeight", "pieceWeight"):
        value = payload.get(key)
        if value is not None:
            try:
                if type(value) not in (int, float) or not math.isfinite(value):
                    return invalid
            except OverflowError:
                return invalid
    barcode = payload.get("nsBarcode")
    if barcode is not None and (
        not isinstance(barcode, str)
        or re.fullmatch(r"[A-Za-z0-9 ._-]{1,100}", barcode) is None
        or barcode != barcode.strip()
    ):
        return invalid
    if payload.get("nsName") is not None and not _text(payload["nsName"]):
        return invalid
    item = {key: payload[key] for key in V1SkuCatalog.model_fields if key in payload}
    if "linkedAlliances" in item:
        entries = item["linkedAlliances"]
        if not isinstance(entries, list) or len(entries) > 1000:
            return invalid
        projected = []
        for row in entries:
            if not isinstance(row, dict) or not (
                _text(row.get("allianceId")) and _kst(row.get("allianceLinkedYmdt"))
            ):
                return invalid
            projected.append({key: row[key] for key in ("allianceId", "allianceLinkedYmdt")})
        item["linkedAlliances"] = projected
    try:
        result = _result("complete", item=item)
    except ValueError:
        return invalid
    try:
        assert_agent_safe_value(result)
    except ValueError:
        return _result("incomplete", "unsafe_provider_value")
    return result


async def read_sku_v1(client: Any | None, ns_id: object) -> V1SkuRead:
    if not isinstance(ns_id, str) or SKU_V1_ID.fullmatch(ns_id) is None:
        return _result("invalid_request", "invalid_request")
    if client is None:
        return _result("unavailable", "client_not_configured")
    try:
        payload = await client._request(
            "GET",
            f"{SKU_V1_PREFIX}/{ns_id}",
            query=None,
            access_token=await client._access_token(),
        )
    except Exception:
        return _result("unavailable", "provider_unavailable")
    return _project(payload, ns_id)
