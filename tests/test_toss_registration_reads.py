"""OPUS-4 워커 C — 토스 고시·배송지 읽기 도구 시험 (httpx.MockTransport, 실제 호출 없음)."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from mcp import Client

from k12_commerce_mcp.adapters.toss import (
    TossShoppingAdapter,
    normalize_delivery_cutoff,
    with_delivery_cutoff,
)
from k12_commerce_mcp.clients.toss import TossShoppingClient, TossShoppingCredentials
from k12_commerce_mcp.server import build_server
from k12_commerce_mcp.toss_registration_reads import (
    notice_categories,
    notice_items,
    project_notice_categories,
    registration_locations,
)

TOKEN = httpx.Response(
    200,
    json={
        "access_token": "synthetic-token",
        "expires_in": 3600,
        "scope": "toss-shopping-fep:write",
        "token_type": "Bearer",
    },
)
API = "/api/v3/shopping-fep"
POISON_ADDRESS = "서울특별시 강남구 테헤란로 123"
POISON_DETAIL = "토스타워 10층"
POISON_ZIP = "06234"
FAKE_PHONE = "02-000-0000"


def _ok(success: Any) -> httpx.Response:
    return httpx.Response(200, json={"resultType": "SUCCESS", "success": success})


CATEGORY_ROWS = {
    "items": [
        {
            "categoryCode": "FURNITURE",
            "firstCategoryName": "가구",
            "secondCategoryName": "가구(침대,쇼파,싱크대등)",
        },
        {
            "categoryCode": "ETC_GOODS",
            "firstCategoryName": "기타",
            "secondCategoryName": "기타 재화",
        },
        {"categoryCode": "bad code!", "firstCategoryName": "x"},
        {"categoryCode": "FURNITURE", "firstCategoryName": "중복"},
    ]
}
NOTICE_ROWS = {
    "items": [
        {"id": 29, "title": "2. 색상", "order": 2},
        {"id": 27, "title": "1. 제품 소재", "order": 1},
        {
            "id": 33,
            "title": "4. 제조자, 수입품의 경우 수입자를 함께 표기",
            "order": 4,
            "required": False,
        },
        {"id": "x", "title": "깨진 줄"},
    ]
}
DELIVERY_ROWS = {
    "items": [
        {
            "id": 1001,
            "name": "기본 배송 그룹",
            "isMain": True,
            "address": POISON_ADDRESS,
            "zipCode": POISON_ZIP,
        }
    ],
    "nextToken": "***=",
    "hasNext": True,
}
REFUND_ROWS = {
    "items": [
        {
            "id": 2001,
            "zipCode": POISON_ZIP,
            "address": POISON_ADDRESS,
            "detailAddress": POISON_DETAIL,
            "isMain": True,
            "phone": FAKE_PHONE,
        },
        {"id": 2002, "name": "두 번째 반품지", "isMain": False},
    ],
    "hasNext": False,
}


def _client(seen: list[httpx.Request], **overrides: httpx.Response) -> TossShoppingClient:
    routes = {
        f"{API}/notices/category-codes": _ok(CATEGORY_ROWS),
        f"{API}/notices": _ok(NOTICE_ROWS),
        f"{API}/merchants/group-delivery/delivery-location/v2": _ok(DELIVERY_ROWS),
        f"{API}/merchants/group-delivery/exchange-refund-location/v2": _ok(REFUND_ROWS),
        **overrides,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.host == "oauth2.cert.toss.im":
            return TOKEN
        response = routes.get(request.url.path)
        if response is None:
            raise AssertionError(f"unexpected request {request.method} {request.url.path}")
        return response

    return TossShoppingClient(
        TossShoppingCredentials("synthetic-access", "synthetic-secret"),
        transport=httpx.MockTransport(handler),
    )


async def test_notice_categories_project_code_and_names_only() -> None:
    seen: list[httpx.Request] = []
    result = await notice_categories(_client(seen))
    assert result.status == "incomplete"  # 깨진 줄·중복은 세고 건너뛴다
    assert result.skipped_rows == 2
    assert [item.model_dump() for item in result.items] == [
        {
            "category_code": "FURNITURE",
            "name": "가구 > 가구(침대,쇼파,싱크대등)",
            "first_category_name": "가구",
            "second_category_name": "가구(침대,쇼파,싱크대등)",
        },
        {
            "category_code": "ETC_GOODS",
            "name": "기타 > 기타 재화",
            "first_category_name": "기타",
            "second_category_name": "기타 재화",
        },
    ]
    assert [(r.method, r.url.path) for r in seen] == [
        ("POST", "/token"),
        ("GET", f"{API}/notices/category-codes"),
    ]


async def test_notice_items_sorted_by_order_and_required_basis_is_honest() -> None:
    seen: list[httpx.Request] = []
    result = await notice_items(_client(seen), "FURNITURE")
    assert result.status == "incomplete" and result.skipped_rows == 1
    assert [(i.notice_id, i.title, i.required, i.required_basis) for i in result.items] == [
        (27, "1. 제품 소재", True, "toss_doc_all_items_required"),
        (29, "2. 색상", True, "toss_doc_all_items_required"),
        (33, "4. 제조자, 수입품의 경우 수입자를 함께 표기", False, "provider"),
    ]
    assert all(item.default_hint is None for item in result.items)  # 응답에 없으면 지어내지 않는다
    assert seen[-1].url.params.get("categoryCode") == "FURNITURE"


async def test_notice_items_reject_bad_code_without_calling() -> None:
    seen: list[httpx.Request] = []
    result = await notice_items(_client(seen), "FURNITURE&x=1")
    assert result.status == "invalid_request"
    assert seen == []


async def test_locations_drop_address_zip_and_phone() -> None:
    seen: list[httpx.Request] = []
    result = await registration_locations(_client(seen))
    assert result.status == "complete"
    assert [loc.model_dump() for loc in result.delivery_locations] == [
        {"location_id": 1001, "name": "기본 배송 그룹", "is_main": True}
    ]
    assert [loc.model_dump() for loc in result.exchange_refund_locations] == [
        {"location_id": 2001, "name": None, "is_main": True},
        {"location_id": 2002, "name": "두 번째 반품지", "is_main": False},
    ]
    assert result.delivery_locations_has_more is True
    assert result.exchange_refund_locations_has_more is False
    dumped = result.model_dump_json()
    for poison in (POISON_ADDRESS, POISON_DETAIL, POISON_ZIP, FAKE_PHONE, "address", "zip"):
        assert poison not in dumped
    assert {r.method for r in seen if r.url.host != "oauth2.cert.toss.im"} == {"GET"}


async def test_locations_one_side_failing_is_incomplete_not_invented() -> None:
    seen: list[httpx.Request] = []
    client = _client(
        seen, **{f"{API}/merchants/group-delivery/exchange-refund-location/v2": httpx.Response(500)}
    )
    result = await registration_locations(client)
    assert result.status == "incomplete"
    assert result.exchange_refund_locations == ()
    assert "provider_read_unavailable" in result.reasons


async def test_unconfigured_and_auth_failure_are_unavailable() -> None:
    assert (await notice_categories(None)).reasons == ("not_configured",)
    seen: list[httpx.Request] = []
    client = _client(seen, **{f"{API}/notices/category-codes": httpx.Response(401)})
    result = await notice_categories(client)
    assert result.status == "unavailable" and result.reasons == ("authentication_failed",)


def test_category_projection_rejects_non_list() -> None:
    assert project_notice_categories({"items": []}).status == "unavailable"


async def test_mcp_tools_registered_read_only_and_capability_active() -> None:
    seen: list[httpx.Request] = []
    server = build_server(toss_registration_client=_client(seen))
    async with Client(server) as mcp:
        listed = {tool.name: tool for tool in (await mcp.list_tools()).tools}
        categories = await mcp.call_tool("commerce_get_toss_notice_categories", {})
        items = await mcp.call_tool(
            "commerce_get_toss_notice_items", {"category_code": "FURNITURE"}
        )
        locations = await mcp.call_tool("commerce_get_toss_registration_locations", {})
        caps = await mcp.call_tool("commerce_get_capabilities", {"channel": "toss_store"})
    for name in (
        "commerce_get_toss_notice_categories",
        "commerce_get_toss_notice_items",
        "commerce_get_toss_registration_locations",
    ):
        assert listed[name].annotations.read_only_hint is True
    assert categories.structured_content["items"][0]["category_code"] == "FURNITURE"
    assert [row["notice_id"] for row in items.structured_content["items"]] == [27, 29, 33]
    assert locations.structured_content["delivery_locations"][0]["location_id"] == 1001
    active = {
        row["tool_name"]
        for row in caps.structured_content["capabilities"]
        if row["implementation_status"] == "active"
    }
    assert {
        "commerce_get_toss_notice_categories",
        "commerce_get_toss_notice_items",
        "commerce_get_toss_registration_locations",
    } <= active


async def test_mcp_tools_unavailable_without_client() -> None:
    async with Client(build_server()) as mcp:
        result = await mcp.call_tool("commerce_get_toss_notice_categories", {})
        bad = await mcp.call_tool("commerce_get_toss_notice_items", {"category_code": "x y"})
    assert result.structured_content["status"] == "unavailable"
    assert bad.is_error is True  # 입력 모양이 틀리면 MCP 가 먼저 거절한다


# ---- 기존 토스 상품 상세: 등록 고시·면세·출고 마감 시각(deliveryCutoffTime) -----------------

PRODUCT = {
    "id": 301,
    "name": "관측 상품",
    "categoryName": "관측카테고리",
    "exposureStatus": "EXPOSURE",
    "isTaxFree": False,
    "stocks": [{"itemId": 77}],
    "deliveryPolicy": {
        "deliveryMethod": "NORMAL",
        "deliveryFeeType": "FREE",
        "deliveryFee": 0,
        "minimumPurchasePrice": 0,
        "isJejuAndIslandsMountainsDelivery": False,
        "deliveryType": "NORMAL",
        "deliveryCutoffTime": "14:00",
    },
    "exchangeReturnPolicy": {
        "exchangeRefundLocationId": 2001,
        "refundOneWayDeliveryFee": 3000,
        "exchangeRoundTripDeliveryFee": 6000,
        "applicationMethodDescription": "판매자 문의 후 신청",
        "applicationTermDescription": "수령 후 7일 이내",
    },
    "notice": {
        "categoryCode": "ETC_GOODS",
        "items": [
            {"id": 101, "title": "품명 및 모델명", "content": "가짜 상품"},
            {"id": 105, "title": "A/S 책임자와 전화번호", "content": f"가짜상사 {FAKE_PHONE}"},
            {"id": 106, "title": "제조국", "content": "중국"},
        ],
    },
}


def _adapter(product: dict[str, Any]) -> TossShoppingAdapter:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth2.cert.toss.im":
            return TOKEN
        if request.url.path.endswith("/products/301/v2"):
            return _ok(product)
        if request.url.path.endswith("/products/301/product-items"):
            return _ok({"items": [{"itemId": 77}], "nextCursor": None})
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    client = TossShoppingClient(
        TossShoppingCredentials("synthetic-access", "synthetic-secret"),
        transport=httpx.MockTransport(handler),
    )
    return TossShoppingAdapter(client, clock=lambda: datetime(2026, 10, 7, tzinfo=UTC))


async def test_detail_carries_registered_notice_and_withholds_unsafe_item() -> None:
    detail = await _adapter(deepcopy(PRODUCT)).get_product_detail("301")
    assert detail is not None
    assert detail.is_tax_free is False
    assert detail.notice is not None
    assert detail.notice.category_code == "ETC_GOODS"
    assert [(item.id, item.content) for item in detail.notice.items] == [
        (101, "가짜 상품"),
        (106, "중국"),
    ]
    assert detail.notice.withheld_item_ids == (
        105,
    )  # 전화번호가 든 칸은 복사하지 않고 번호만 알린다
    assert FAKE_PHONE not in detail.model_dump_json()


async def test_detail_uses_delivery_cutoff_time_when_deadline_absent() -> None:
    detail = await _adapter(deepcopy(PRODUCT)).get_product_detail("301")
    assert detail.registration_template is not None
    assert detail.registration_template.delivery_policy.delivery_deadline == "14:00"


async def test_detail_keeps_explicit_deadline_over_cutoff() -> None:
    product = deepcopy(PRODUCT)
    product["deliveryPolicy"]["deliveryDeadline"] = "16:30"
    detail = await _adapter(product).get_product_detail("301")
    assert detail.registration_template.delivery_policy.delivery_deadline == "16:30"


async def test_detail_without_notice_or_tax_flag_stays_none() -> None:
    product = deepcopy(PRODUCT)
    del product["notice"], product["isTaxFree"]
    detail = await _adapter(product).get_product_detail("301")
    assert detail.notice is None and detail.is_tax_free is None


# ---- F2: 예전 「N시」 형식 출고 마감 시각을 HH:mm 으로 읽기 ---------------------------------

READABLE_CUTOFFS = [
    ("16:30", "16:30"),
    ("9:30", "09:30"),
    ("15시", "15:00"),
    ("9시", "09:00"),
    ("15시 30분", "15:30"),
    ("15시30분", "15:30"),
    (" 17시 5분 ", "17:05"),
    ("0시", "00:00"),
    ("23시 59분", "23:59"),
]
UNREADABLE_CUTOFFS = ["24시", "25:00", "15시 60분", "12:5", "오후 3시", "15", "15:00:00", "１５시"]


@pytest.mark.parametrize(("raw", "expected"), READABLE_CUTOFFS)
def test_normalize_delivery_cutoff_accepts_old_and_clock_forms(raw: str, expected: str) -> None:
    assert normalize_delivery_cutoff(raw) == expected


@pytest.mark.parametrize("raw", [*UNREADABLE_CUTOFFS, "", "  ", None, 15, 15.0])
def test_normalize_delivery_cutoff_rejects_out_of_range_or_other_shapes(raw: object) -> None:
    assert normalize_delivery_cutoff(raw) is None


@pytest.mark.parametrize(("raw", "expected"), READABLE_CUTOFFS)
async def test_detail_reads_old_deadline_forms_as_hhmm(raw: str, expected: str) -> None:
    product = deepcopy(PRODUCT)
    # deliveryDeadline 이 원응답 deliveryCutoffTime(14:00)보다 앞선다
    product["deliveryPolicy"]["deliveryDeadline"] = raw
    detail = await _adapter(product).get_product_detail("301")
    assert detail.registration_template is not None
    assert detail.registration_template.delivery_policy.delivery_deadline == expected
    assert detail.registration_template_candidate is None


@pytest.mark.parametrize(("raw", "expected"), READABLE_CUTOFFS)
async def test_detail_reads_old_cutoff_forms_when_deadline_absent(raw: str, expected: str) -> None:
    product = deepcopy(PRODUCT)
    product["deliveryPolicy"]["deliveryCutoffTime"] = raw
    detail = await _adapter(product).get_product_detail("301")
    assert detail.registration_template is not None
    assert detail.registration_template.delivery_policy.delivery_deadline == expected


async def test_detail_blank_deadline_falls_back_to_cutoff() -> None:
    product = deepcopy(PRODUCT)
    product["deliveryPolicy"]["deliveryDeadline"] = "  "
    product["deliveryPolicy"]["deliveryCutoffTime"] = "13시"
    detail = await _adapter(product).get_product_detail("301")
    assert detail.registration_template is not None
    assert detail.registration_template.delivery_policy.delivery_deadline == "13:00"


@pytest.mark.parametrize("raw", UNREADABLE_CUTOFFS)
async def test_detail_unreadable_deadline_stays_blank_not_guessed(raw: str) -> None:
    product = deepcopy(PRODUCT)
    product["deliveryPolicy"]["deliveryDeadline"] = raw
    detail = await _adapter(product).get_product_detail("301")
    # 읽을 수 없는 마감 시각은 지금처럼 비우고 확인 필요로 넘긴다(다른 칸 14:00 으로 덮지 않음).
    assert detail.registration_template is None
    candidate = detail.registration_template_candidate
    assert candidate is not None
    assert "delivery_policy.delivery_deadline" in candidate.missing_fields
    assert candidate.delivery_policy.delivery_deadline is None


@pytest.mark.parametrize("raw", UNREADABLE_CUTOFFS)
async def test_detail_unreadable_cutoff_stays_blank_when_deadline_absent(raw: str) -> None:
    product = deepcopy(PRODUCT)
    product["deliveryPolicy"]["deliveryCutoffTime"] = raw
    detail = await _adapter(product).get_product_detail("301")
    template = detail.registration_template
    assert template is not None and template.delivery_policy.delivery_deadline is None


def test_with_delivery_cutoff_never_mutates_provider_row() -> None:
    row = deepcopy(PRODUCT)
    row["deliveryPolicy"]["deliveryDeadline"] = "15시 30분"
    before = deepcopy(row)
    patched, source = with_delivery_cutoff(row)
    assert row == before
    assert source == "deliveryDeadline"
    assert patched["deliveryPolicy"]["deliveryDeadline"] == "15:30"
    assert patched["deliveryPolicy"] is not row["deliveryPolicy"]

    cutoff_row = deepcopy(PRODUCT)
    cutoff_row["deliveryPolicy"]["deliveryCutoffTime"] = "9시"
    cutoff_before = deepcopy(cutoff_row)
    patched, source = with_delivery_cutoff(cutoff_row)
    assert cutoff_row == cutoff_before
    assert source == "deliveryCutoffTime"
    assert patched["deliveryPolicy"]["deliveryDeadline"] == "09:00"

    already = deepcopy(PRODUCT)
    already["deliveryPolicy"]["deliveryDeadline"] = "18:00"
    same, source = with_delivery_cutoff(already)
    assert same is already and source == "deliveryDeadline"

    unreadable = deepcopy(PRODUCT)
    unreadable["deliveryPolicy"]["deliveryDeadline"] = "25시"
    same, source = with_delivery_cutoff(unreadable)
    assert same is unreadable and source is None
