"""Toss registration reads for DOR's 몰 등록 칸 자동 채움 (OPUS-4 워커 C) — GET only.

CEO 2026-10-07: 「내가 토스 정보고시를 어떻게 알아 그거 내가 하나하나 알려줘야해?」 —
고시 유형(카테고리 코드)과 항목 목록, 배송비 묶음 그룹·교환반품지 번호를 토스 API 에서 읽는다.

- commerce_get_toss_notice_categories
    GET /notices/category-codes
    → items[{category_code, name, first_category_name, second_category_name}]
- commerce_get_toss_notice_items(category_code)
    GET /notices?categoryCode=
    → items[{notice_id, title, order, required, required_basis, default_hint}]
- commerce_get_toss_registration_locations
    GET merchants/group-delivery/delivery-location/v2 · exchange-refund-location/v2
    → delivery_locations / exchange_refund_locations [{location_id, name, is_main}]

Boundaries: the only provider calls are the client's allowlisted GETs (plus its existing
OAuth token POST). Address text, zip codes, phone numbers and any non-whitelisted key are
never projected; unsafe display text is dropped (None), never truncated or guessed.
"""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .adapters.base import AdapterAuthenticationError, AdapterRateLimitError
from .clients.toss import TossShoppingRequestError
from .security import is_agent_safe_value

MAX_NOTICE_CATEGORIES = 500
MAX_NOTICE_ITEMS = 200
MAX_LOCATIONS = 1_000
_CATEGORY_CODE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_CTRL = re.compile(r"[\x00-\x1f\x7f]")

TossReadReason = Literal[
    "not_configured",
    "authentication_failed",
    "rate_limited",
    "invalid_request",
    "provider_read_unavailable",
    "invalid_provider_shape",
    "rows_skipped",
]
CategoryCode = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
DisplayText = Annotated[str, Field(min_length=1, max_length=300)]


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TossNoticeCategory(_Frozen):
    category_code: CategoryCode
    # 「1차 > 2차」 이름 (토스 응답에 이름 칸이 따로 없어서 두 이름을 잇는다).
    name: DisplayText | None = None
    first_category_name: DisplayText | None = None
    second_category_name: DisplayText | None = None


class TossNoticeCategoryList(_Frozen):
    status: Literal["complete", "incomplete", "unavailable"]
    items: tuple[TossNoticeCategory, ...] = Field(default=(), max_length=MAX_NOTICE_CATEGORIES)
    skipped_rows: int = Field(default=0, ge=0)
    reasons: tuple[TossReadReason, ...] = ()
    source: Literal["toss-shopping:notices/category-codes"] = "toss-shopping:notices/category-codes"


class TossNoticeItemDescriptor(_Frozen):
    notice_id: Annotated[int, Field(ge=0, le=2**63 - 1)]
    title: DisplayText | None = None
    order: Annotated[int, Field(ge=0, le=100_000)] | None = None
    # 토스 문서: 「고시항목이란 법적으로 고객에게 알려야 하는 필수 정보」 — 항목별 필수 칸이
    # 응답에 없으면 문서 기준으로 true 로 두고 그 근거를 required_basis 에 적는다.
    required: bool = True
    required_basis: Literal["provider", "toss_doc_all_items_required"] = (
        "toss_doc_all_items_required"
    )
    # 응답에 입력 예시(placeholder·guide 등)가 있을 때만 — 지어내지 않는다.
    default_hint: DisplayText | None = None


class TossNoticeItemList(_Frozen):
    status: Literal["complete", "incomplete", "unavailable", "invalid_request"]
    category_code: CategoryCode | None = None
    items: tuple[TossNoticeItemDescriptor, ...] = Field(default=(), max_length=MAX_NOTICE_ITEMS)
    skipped_rows: int = Field(default=0, ge=0)
    reasons: tuple[TossReadReason, ...] = ()
    source: Literal["toss-shopping:notices"] = "toss-shopping:notices"


class TossRegistrationLocation(_Frozen):
    location_id: Annotated[int, Field(ge=1, le=2**63 - 1)]
    name: DisplayText | None = None
    is_main: bool | None = None


class TossRegistrationLocations(_Frozen):
    status: Literal["complete", "incomplete", "unavailable"]
    delivery_locations: tuple[TossRegistrationLocation, ...] = Field(
        default=(), max_length=MAX_LOCATIONS
    )
    exchange_refund_locations: tuple[TossRegistrationLocation, ...] = Field(
        default=(), max_length=MAX_LOCATIONS
    )
    # 토스가 hasNext=true 를 돌려줬는지 — 다음 쪽 요청 이름은 문서에 없어 더 읽지 않는다.
    delivery_locations_has_more: bool = False
    exchange_refund_locations_has_more: bool = False
    skipped_rows: int = Field(default=0, ge=0)
    reasons: tuple[TossReadReason, ...] = ()


def _reason(exc: Exception) -> TossReadReason:
    if isinstance(exc, AdapterAuthenticationError):
        return "authentication_failed"
    if isinstance(exc, AdapterRateLimitError):
        return "rate_limited"
    if isinstance(exc, TossShoppingRequestError):
        return "invalid_request"
    return "provider_read_unavailable"


def _display(value: object, limit: int = 300) -> str | None:
    """Safe display text or None — never truncated, never control characters."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or len(text) > limit or _CTRL.search(text) or not is_agent_safe_value(text):
        return None
    return text


def _int_id(value: object, *, minimum: int) -> int | None:
    if type(value) is int and minimum <= value <= 2**63 - 1:
        return value
    if isinstance(value, str) and value.isascii() and value.isdigit():
        parsed = int(value)
        return parsed if minimum <= parsed <= 2**63 - 1 else None
    return None


def _first_bool(row: dict[str, Any], keys: tuple[str, ...]) -> bool | None:
    for key in keys:
        value = row.get(key)
        if type(value) is bool:
            return value
    return None


def project_notice_categories(rows: Any) -> TossNoticeCategoryList:
    if not isinstance(rows, (list, tuple)) or len(rows) > MAX_NOTICE_CATEGORIES:
        return TossNoticeCategoryList(status="unavailable", reasons=("invalid_provider_shape",))
    items: list[TossNoticeCategory] = []
    seen: set[str] = set()
    skipped = 0
    for row in rows:
        code = row.get("categoryCode") if isinstance(row, dict) else None
        if not isinstance(code, str) or not _CATEGORY_CODE.fullmatch(code) or code in seen:
            skipped += 1
            continue
        seen.add(code)
        first = _display(row.get("firstCategoryName"))
        second = _display(row.get("secondCategoryName"))
        joined = " > ".join(part for part in (first, second) if part)
        name = _display(row.get("name")) or _display(row.get("title")) or (joined or None)
        items.append(
            TossNoticeCategory(
                category_code=code,
                name=name if name is None or len(name) <= 300 else None,
                first_category_name=first,
                second_category_name=second,
            )
        )
    status = "complete" if not skipped else ("incomplete" if items else "unavailable")
    return TossNoticeCategoryList(
        status=status,
        items=tuple(items),
        skipped_rows=skipped,
        reasons=("rows_skipped",) if skipped else (),
    )


_HINT_KEYS = ("placeholder", "guide", "hint", "example", "inputGuide", "description")


def project_notice_items(category_code: str, rows: Any) -> TossNoticeItemList:
    if not isinstance(rows, (list, tuple)) or len(rows) > MAX_NOTICE_ITEMS:
        return TossNoticeItemList(
            status="unavailable", category_code=category_code, reasons=("invalid_provider_shape",)
        )
    items: list[TossNoticeItemDescriptor] = []
    seen: set[int] = set()
    skipped = 0
    for row in rows:
        notice_id = (
            _int_id(row.get("id", row.get("noticeId")), minimum=0)
            if isinstance(row, dict)
            else None
        )
        if notice_id is None or notice_id in seen:
            skipped += 1
            continue
        seen.add(notice_id)
        provider_required = _first_bool(row, ("required", "isRequired", "mandatory", "isMandatory"))
        order = row.get("order")
        hint = next(
            (text for key in _HINT_KEYS if (text := _display(row.get(key))) is not None), None
        )
        items.append(
            TossNoticeItemDescriptor(
                notice_id=notice_id,
                title=_display(
                    row.get("title") if row.get("title") is not None else row.get("name")
                ),
                order=order if type(order) is int and 0 <= order <= 100_000 else None,
                required=provider_required if provider_required is not None else True,
                required_basis="provider"
                if provider_required is not None
                else "toss_doc_all_items_required",
                default_hint=hint,
            )
        )
    items.sort(key=lambda item: (item.order is None, item.order or 0, item.notice_id))
    status = "complete" if not skipped else ("incomplete" if items else "unavailable")
    return TossNoticeItemList(
        status=status,
        category_code=category_code,
        items=tuple(items),
        skipped_rows=skipped,
        reasons=("rows_skipped",) if skipped else (),
    )


_LOCATION_NAME_KEYS = ("name", "locationName", "groupName", "alias", "title", "label")


def project_locations(rows: Any) -> tuple[tuple[TossRegistrationLocation, ...], int] | None:
    """Only id·name·isMain — address, zipCode, detailAddress and every other key are dropped."""
    if not isinstance(rows, (list, tuple)) or len(rows) > MAX_LOCATIONS:
        return None
    out: list[TossRegistrationLocation] = []
    seen: set[int] = set()
    skipped = 0
    for row in rows:
        location_id = _int_id(row.get("id"), minimum=1) if isinstance(row, dict) else None
        if location_id is None or location_id in seen:
            skipped += 1
            continue
        seen.add(location_id)
        name = next(
            (
                text
                for key in _LOCATION_NAME_KEYS
                if (text := _display(row.get(key), 100)) is not None
            ),
            None,
        )
        out.append(
            TossRegistrationLocation(
                location_id=location_id,
                name=name,
                is_main=_first_bool(row, ("isMain", "isDefault", "main")),
            )
        )
    return tuple(out), skipped


async def notice_categories(client: Any | None) -> TossNoticeCategoryList:
    if client is None:
        return TossNoticeCategoryList(status="unavailable", reasons=("not_configured",))
    try:
        rows = await client.list_notice_category_codes()
    except Exception as exc:  # never echo provider text
        return TossNoticeCategoryList(status="unavailable", reasons=(_reason(exc),))
    return project_notice_categories(rows)


async def notice_items(client: Any | None, category_code: str) -> TossNoticeItemList:
    if not isinstance(category_code, str) or not _CATEGORY_CODE.fullmatch(category_code):
        return TossNoticeItemList(status="invalid_request", reasons=("invalid_request",))
    if client is None:
        return TossNoticeItemList(
            status="unavailable", category_code=category_code, reasons=("not_configured",)
        )
    try:
        rows = await client.list_notices(category_code=category_code)
    except Exception as exc:
        return TossNoticeItemList(
            status="unavailable", category_code=category_code, reasons=(_reason(exc),)
        )
    return project_notice_items(category_code, rows)


async def registration_locations(client: Any | None) -> TossRegistrationLocations:
    if client is None:
        return TossRegistrationLocations(status="unavailable", reasons=("not_configured",))
    reasons: list[TossReadReason] = []
    results: dict[str, Any] = {}
    for key, reader in (
        ("delivery", client.read_delivery_locations_v2),
        ("exchange_refund", client.read_exchange_refund_locations_v2),
    ):
        try:
            results[key] = await reader()
        except Exception as exc:
            results[key] = None
            if (reason := _reason(exc)) not in reasons:
                reasons.append(reason)
    projected: dict[str, tuple[tuple[TossRegistrationLocation, ...], int] | None] = {}
    for key, page in results.items():
        projected[key] = project_locations(page.rows) if page is not None else None
        if page is not None and projected[key] is None and "invalid_provider_shape" not in reasons:
            reasons.append("invalid_provider_shape")
    delivery = projected.get("delivery")
    refund = projected.get("exchange_refund")
    skipped = sum(part[1] for part in (delivery, refund) if part is not None)
    if skipped and "rows_skipped" not in reasons:
        reasons.append("rows_skipped")
    if delivery is None and refund is None:
        status = "unavailable"
    elif delivery is None or refund is None or skipped:
        status = "incomplete"
    else:
        status = "complete"
    return TossRegistrationLocations(
        status=status,
        delivery_locations=delivery[0] if delivery else (),
        exchange_refund_locations=refund[0] if refund else (),
        delivery_locations_has_more=bool(results.get("delivery") and results["delivery"].has_more),
        exchange_refund_locations_has_more=bool(
            results.get("exchange_refund") and results["exchange_refund"].has_more
        ),
        skipped_rows=skipped,
        reasons=tuple(reasons),
    )
