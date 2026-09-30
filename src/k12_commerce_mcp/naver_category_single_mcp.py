"""Single Naver category: safe local path subset and closed public projection.

The alphanumeric path cap of 200 and nested array cap of 1000 are LOCAL,
not provider format/size claims. Missing optional properties are omitted,
not materialized as null/false/empty values.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import StrictBool, StrictInt, StrictStr, model_serializer

from .models.common import CanonicalModel
from .security import assert_agent_safe_value

CATEGORY_ID = re.compile(r"[A-Za-z0-9]{1,200}")
CATEGORY_PREFIX = "/v1/categories"
CATEGORY_OP = "get-category-product"
Exceptional = Literal[
    "E_COUPON",
    "ADULT",
    "MARINE_PRODUCTS",
    "REVIEW_UNEXPOSE",
    "CHILD_CERTIFICATION",
    "ORIGINAREA_PRODUCTS",
    "GREEN_PRODUCTS",
    "KC_CERTIFICATION",
    "SAFE_CRITERION",
    "AFFILIATE",
    "TRADITIONAL_ALCOHOL",
    "ALCOHOL",
    "OPTION_PRICE",
    "BOOK_CHILD",
    "BOOK",
    "BOOK_EBOOK",
    "BOOK_AUDIO",
    "BOOK_MAGAZINE",
    "BOOK_USED",
    "BOOK_OVERSEAS",
    "BOOK_FREE",
    "PERFORMANCE",
    "FREE_RETURN_INSURANCE",
    "REGULAR_SUBSCRIPTION",
    "RENTAL_SUBSCRIPTION",
    "VINTAGE_CITY",
    "SEONE_AI_ASSISTANT_UNEXPOSE",
    "GROUP_PRODUCT_MAX",
    "DYNAMIC_PRICING_CONFIG",
    "MANUFACTURE_DEFINE_NO",
    "PREORDER_VALID_DATE",
    "UNIT_PRICE",
    "BUSINESSMALL_UNAVAILABLE",
    "CHEMICAL_CERTIFICATION",
]
Kind = Literal[
    "KC_CERTIFICATION",
    "CHILD_CERTIFICATION",
    "GREEN_PRODUCTS",
    "CHEMICAL_CERTIFICATION",
    "PARALLEL_IMPORT",
    "OVERSEAS",
    "ETC",
]
Mark = Literal[
    "KC",
    "ORGANIC_AGRICULTURAL_PROD",
    "ORGANIC_ANIMAL_PROD",
    "NON_PESTICIDE",
    "NON_ANTIBIOTIC",
    "LOW_PESTICIDE",
    "GAP",
    "AGRICULTURAL_TRACEABILITY",
    "PROCESSED_FOOD_KS",
    "TRADITIONAL_FOOD",
    "ORGANIC_PROCESSED_FOOD",
    "QUALITY_SEAFOOD",
    "ECO_SEAFOOD",
    "HACCP",
    "GMP",
    "SAFETY",
    "SIX_INDUSTRY",
    "ANIMAL_WELFARE",
    "FOOD_MASTER",
    "ECO_PROCESSED_FOOD",
    "ECO_ORGANIC_ANIMAL_PROD",
    "TRADITIONAL_SEAFOOD",
    "SOCIAL_ENTERPRISE",
    "VILLAGE_ENTERPRISE",
    "SPECIAL_SEAFOOD",
    "SEA_ORGANIC_PROCESSED_FOOD",
    "SEA_ORGANIC_PROD",
    "SEA_NON_ANTIBIOTIC",
    "SEA_NON_ACTIVE_TREATMENT",
    "ALCOHOL",
    "LIVING_CHEMISTRY_SAFETY",
    "ECO_FRIENDLY",
    "VEGAN",
    "VEGAN_STANDARD_CERT",
    "LOW_CARBON",
    "OVERSEAS_PETA",
    "OVERSEAS_V_LABEL",
    "OVERSEAS_VEGAN_SOCIETY",
    "OVERSEAS_EVE_VEGAN",
    "ECO_OVERSEAS_MSC",
    "ECO_OVERSEAS_USDA",
    "ECO_OVERSEAS_ECOCERT",
    "ECO_OVERSEAS_FSC",
    "ECO_OVERSEAS_FAIR_TRADE",
    "ECO_OVERSEAS_CARBON_TRUST",
]


class PresentFields(CanonicalModel):
    """Keep optional unbadged fields absent unless actually supplied."""

    @model_serializer(mode="wrap")
    def _present(self, handler):
        return {key: value for key, value in handler(self).items() if key in self.model_fields_set}


class Certification(PresentFields):
    id: StrictInt
    name: StrictStr
    kindTypes: tuple[Kind, ...]
    green: StrictBool
    certificationMarkType: Mark = "KC"
    companyName: StrictBool = False
    certificationDate: StrictBool = False
    kcParallelImportExemptionObject: StrictBool = False
    nonEssential: StrictBool = False


class CategoryDetail(PresentFields):
    wholeCategoryName: StrictStr
    id: StrictStr
    name: StrictStr
    last: StrictBool
    exceptionalCategories: tuple[Exceptional, ...] = ()
    certificationInfos: tuple[Certification, ...] = ()


class CategoryRead(CanonicalModel):
    channel: Literal["naver"] = "naver"
    operation_id: Literal["get-category-product"] = CATEGORY_OP
    status: Literal["complete", "incomplete", "unavailable", "invalid_request"]
    reasons: tuple[str, ...] = ()
    item: CategoryDetail | None = None


def _result(status: str, reason: str | None = None, item: dict | None = None) -> CategoryRead:
    return CategoryRead.model_validate(
        {"status": status, "reasons": [reason] if reason else [], "item": item}
    )


def _text(value: object) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= 200
        and value == value.strip()
        and all(ord(c) >= 32 and ord(c) != 127 for c in value)
    )


def _assert_category_safe(result: CategoryRead) -> None:
    """Check all original values; only public certification label syntax is local.

    The global raw/PII guard is unchanged. A tightly bounded, balanced bracket
    label in this one field is not a JSON array. Check its original text for
    unsafe content before scanning a bracket-free copy of the closed result.
    No returned value is rewritten and category titles get no exception.
    """
    scan = result.model_dump(mode="json")
    for cert in (scan.get("item") or {}).get("certificationInfos", []):
        name = cert["name"]
        if any(c in name for c in "[]{}\"'"):
            if re.fullmatch(r"[A-Za-z0-9가-힣 _\.()\[\]-]+", name) is None:
                raise ValueError("unsafe certification label")
            # Reject nested, unbalanced, padded, or payload-shaped labels.
            labels = re.findall(r"\[[A-Za-z_가-힣][A-Za-z0-9가-힣 _.-]{0,80}\]", name)
            if not labels or any(label[1:-1] != label[1:-1].strip() for label in labels):
                raise ValueError("unsafe certification label")
            remainder = name
            for label in labels:
                remainder = remainder.replace(label, "", 1)
            if "[" in remainder or "]" in remainder:
                raise ValueError("unsafe certification label")
            # Original PII/secret-shaped text still fails; only balanced label
            # brackets are removed for this field's raw-JSON scan.
            assert_agent_safe_value(name.replace("[", "").replace("]", ""))
            cert["name"] = name.replace("[", "").replace("]", "")
    assert_agent_safe_value(scan)


def _project(payload: object, category_id: str) -> CategoryRead:
    invalid = _result("incomplete", "invalid_provider_shape")
    if not isinstance(payload, dict) or not (
        payload.get("id") == category_id
        and all(_text(payload.get(key)) for key in ("wholeCategoryName", "name"))
        and type(payload.get("last")) is bool
    ):
        return invalid
    item = {key: payload[key] for key in ("wholeCategoryName", "id", "name", "last")}
    if "exceptionalCategories" in payload:
        entries = payload["exceptionalCategories"]
        if not isinstance(entries, list) or len(entries) > 1000:
            return invalid
        item["exceptionalCategories"] = entries
    if "certificationInfos" in payload:
        entries = payload["certificationInfos"]
        if not isinstance(entries, list) or len(entries) > 1000:
            return invalid
        certificates = []
        for entry in entries:
            if not isinstance(entry, dict) or not (
                type(entry.get("id")) is int
                and -(2**63) <= entry["id"] <= 2**63 - 1
                and _text(entry.get("name"))
                and type(entry.get("green")) is bool
                and isinstance(entry.get("kindTypes"), list)
                and len(entry["kindTypes"]) <= 1000
            ):
                return invalid
            certificates.append(
                {key: entry[key] for key in Certification.model_fields if key in entry}
            )
        item["certificationInfos"] = certificates
    try:
        result = _result("complete", item=item)
    except ValueError:
        return invalid
    try:
        _assert_category_safe(result)
    except ValueError:
        return _result("incomplete", "unsafe_provider_value")
    return result


async def read_category(client: Any | None, category_id: object) -> CategoryRead:
    if not isinstance(category_id, str) or CATEGORY_ID.fullmatch(category_id) is None:
        return _result("invalid_request", "invalid_request")
    if client is None:
        return _result("unavailable", "client_not_configured")
    try:
        payload = await client._request(
            "GET",
            f"{CATEGORY_PREFIX}/{category_id}",
            query=None,
            access_token=await client._access_token(),
        )
    except Exception:
        return _result("unavailable", "provider_unavailable")
    return _project(payload, category_id)
