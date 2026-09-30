"""Historical synthetic tests for captured Coupang general read candidates.

Candidate metadata is the pre-integration snapshot, not a current transport
status. Enrolled brands has since gained an independent live MCP GET.
Query-shaped POSTs stay disabled unless a document explicitly denies mutation.
"""

from __future__ import annotations

import inspect
import re

import pytest

from k12_commerce_mcp.adapters.coupang.general_missing_reads import (
    CoupangGeneralMissingReads,
    DisabledQueryPostError,
    MissingReadError,
    list_disabled_query_posts,
    list_missing_reads,
    list_unconfirmed_exclusions,
)
from k12_commerce_mcp.clients.coupang import (
    ALLOWED_GET_PATH_TEMPLATES,
    ALLOWED_POST_PATH_TEMPLATES,
)
from k12_commerce_mcp.security import assert_agent_safe_value

_DOC = "raw/documents/marketplace-api-docs-20260916/coupang"
_DISABLE_REASON = "조회형 POST이나 문서가 상태 무변경을 명시하지 않음"


def _norm(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "{}", path)


class _Reader:
    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def __call__(self, operation_id: str, request: dict[str, object]) -> object:
        self.calls.append((operation_id, request))
        return self.payload


def _safe(result: object) -> dict[str, object]:
    payload = {
        "operation_id": result.operation_id,
        "items": result.items,
        "page": result.page,
        "transport_connected": result.transport_connected,
    }
    assert_agent_safe_value(payload)
    return payload


def test_captured_read_candidates_and_current_enrolled_brand_exception() -> None:
    reads = list_missing_reads()
    posts = list_disabled_query_posts()
    allowed = {_norm(path) for path in ALLOWED_GET_PATH_TEMPLATES}
    allowed_post = {_norm(path) for path in ALLOWED_POST_PATH_TEMPLATES}

    assert {item.operation_id for item in reads} == {
        "enrolled_brands",
        "budget_status",
        "instant_coupon_request_status",
        "instant_coupons_by_order",
        "instant_coupons_by_status",
        "instant_coupon_items_by_status",
        "instant_coupon_by_id",
        "instant_coupon_item_by_coupon_item_id",
        "instant_coupon_item_by_vendor_item_id",
        "cashback_rule",
    }
    assert {item.method for item in reads} == {"GET"}
    assert all(item.execution_enabled for item in reads)
    assert all(item.client_allowlisted is False for item in reads)
    assert all(item.transport_connected is False for item in reads)
    assert all(item.state_change_explicitly_denied is False for item in reads)
    assert all(item.query_evidence for item in reads)
    assert all("A000" not in item.path_template for item in reads)
    assert all("/rg/" not in item.path_template for item in reads)
    assert {
        _norm(item.path_template) for item in reads if item.operation_id != "enrolled_brands"
    }.isdisjoint(allowed)
    # The historic synthetic candidate now has a separately wired MCP GET.
    assert (
        _norm(next(item.path_template for item in reads if item.operation_id == "enrolled_brands"))
        in allowed
    )
    assert {_norm(item.path_template) for item in posts}.isdisjoint(allowed_post)

    enrolled = next(item for item in reads if item.operation_id == "enrolled_brands")
    assert enrolled.path_template == (
        "/v2/providers/seller_api/apis/api/v1/marketplace/brands/enrolled"
    )
    assert enrolled.source_doc == f"{_DOC}/ko_api_brands_enrolled-brands-list.html"
    assert "목록을 조회" in enrolled.query_evidence
    assert enrolled.category == "brand_list"

    budget = next(item for item in reads if item.operation_id == "budget_status")
    assert budget.path_template == ("/v2/providers/fms/apis/api/v1/vendors/{vendorId}/budgets")
    assert budget.source_doc.endswith("ko_api_promotions_common-run-a-query-on-budget-status.html")
    assert "예산을 조회" in budget.query_evidence
    assert any("Array" in note and "content" in note for note in budget.notes)

    coupons = [item for item in reads if item.category == "instant_discount_coupon"]
    assert len(coupons) == 7
    assert all("조회" in item.query_evidence or "확인" in item.query_evidence for item in coupons)
    by_id = next(item for item in reads if item.operation_id == "instant_coupon_by_id")
    assert by_id.path_template.endswith("/vendors/{vendorId}/coupon")
    assert not by_id.path_template.endswith("/coupons/{couponId}")


def test_query_posts_stay_disabled_when_no_change_is_not_explicit() -> None:
    posts = list_disabled_query_posts()

    assert {item.operation_id for item in posts} == {
        "brand_search",
        "category_predict",
        "return_withdraw_by_receipt",
    }
    assert all(item.method == "POST" for item in posts)
    assert all(item.execution_enabled is False for item in posts)
    assert all(item.state_change_explicitly_denied is False for item in posts)
    assert all(item.disable_reason == _DISABLE_REASON for item in posts)
    assert all(item.status == "disabled_unconfirmed_mutation" for item in posts)
    brand = next(item for item in posts if item.operation_id == "brand_search")
    assert brand.path_template.endswith("/marketplace/brands/search")
    assert brand.category == "brand_list"
    predict = next(item for item in posts if item.operation_id == "category_predict")
    assert predict.path_template == "/v2/providers/openapi/apis/api/v1/categorization/predict"
    withdraw = next(item for item in posts if item.operation_id == "return_withdraw_by_receipt")
    assert withdraw.path_template.endswith("/returnWithdrawList")


def test_courier_code_page_is_not_invented_as_an_endpoint() -> None:
    excluded = list_unconfirmed_exclusions()

    assert any(
        item.source_doc.endswith("ko_api_logistics_courier-code.html") and "경로" in item.reason
        for item in excluded
    )
    assert all("A000" not in item.reason for item in excluded)


def test_module_does_not_import_live_transport() -> None:
    source = inspect.getsource(CoupangGeneralMissingReads)
    module = inspect.getsource(
        __import__(
            "k12_commerce_mcp.adapters.coupang.general_missing_reads",
            fromlist=["general_missing_reads"],
        )
    )
    assert "httpx" not in module
    assert "clients.coupang" not in module
    assert "api-gateway.coupang.com" not in module
    assert "CoupangClient" not in source


async def test_enrolled_brands_projects_documented_fields_and_drops_leaks() -> None:
    reader = _Reader(
        {
            "code": "SUCCESS",
            "message": "email@example.test",
            "data": [
                {
                    "brandId": "KR-5",
                    "brandName": "NIKE",
                    "brandLogoUrl": "https://example.com/logo.png",
                    "buyerPhone": "010-1234-5678",
                    "vendorId": "A00012345",
                },
                {"brandId": "010-1234-5678", "brandName": "hidden@example.test"},
            ],
        }
    )
    result = await CoupangGeneralMissingReads(reader).read("enrolled_brands")

    payload = _safe(result)
    assert payload["transport_connected"] is False
    assert result.items == ({"brandId": "KR-5", "brandName": "NIKE"},)
    assert reader.calls == [("enrolled_brands", {"path": {}, "query": {}})]
    assert "email@example.test" not in str(payload)
    assert "010-1234-5678" not in str(payload)
    assert "vendorId" not in str(payload)
    assert "example.com" not in str(payload)


async def test_enrolled_brands_rejects_filters_and_wrong_shape_before_empty_success() -> None:
    reader = _Reader({"data": [{"brandId": "KR-5", "brandName": "NIKE"}]})
    facade = CoupangGeneralMissingReads(reader)

    with pytest.raises(MissingReadError) as bad_filter:
        await facade.read("enrolled_brands", brand_name="NIKE")
    assert reader.calls == []
    assert "NIKE" not in str(bad_filter.value)

    reader.payload = {"data": {"brandId": "KR-5"}}
    with pytest.raises(MissingReadError):
        await facade.read("enrolled_brands")
    assert reader.calls


async def test_budget_requires_month_and_rejects_bare_array_envelope() -> None:
    reader = _Reader(
        {
            "data": {
                "success": True,
                "content": [
                    {
                        "contractId": -1,
                        "targetMonth": "2017-08",
                        "vendorShareRatio": 100,
                        "totalBudgetAmount": 1000000,
                        "usedBudgetAmount": 50,
                        "vendorId": "A00012345",
                        "errorMessage": "secret",
                    }
                ],
                "pagination": None,
            }
        }
    )
    facade = CoupangGeneralMissingReads(reader)
    result = await facade.read("budget_status", contract_id=-1, target_month="2017-08")

    assert result.items == (
        {
            "contractId": -1,
            "targetMonth": "2017-08",
            "vendorShareRatio": 100,
            "totalBudgetAmount": 1000000,
            "usedBudgetAmount": 50,
        },
    )
    assert result.page is None
    assert reader.calls[0][1] == {
        "path": {},
        "query": {"contractId": -1, "targetMonth": "2017-08"},
    }
    assert "vendorId" not in result.items[0]
    _safe(result)

    reader.calls.clear()
    with pytest.raises(MissingReadError):
        await facade.read("budget_status", contract_id=True, target_month="2017-08")
    assert reader.calls == []

    reader.calls.clear()
    with pytest.raises(MissingReadError) as missing_month:
        await facade.read("budget_status", contract_id=2)
    assert reader.calls == []
    assert "current" not in str(missing_month.value).lower()

    reader.payload = {"data": [{"contractId": 2, "targetMonth": "2017-08"}]}
    with pytest.raises(MissingReadError):
        await facade.read("budget_status", target_month="2017-08")


async def test_budget_drops_unconfirmed_float_amount() -> None:
    reader = _Reader(
        {
            "data": {
                "success": True,
                "content": [
                    {
                        "contractId": 2,
                        "targetMonth": "2017-08",
                        "usedBudgetAmount": 50.0,
                    }
                ],
                "pagination": None,
            }
        }
    )
    result = await CoupangGeneralMissingReads(reader).read("budget_status", target_month="2017-08")

    assert "usedBudgetAmount" not in result.items[0]
    assert result.items[0]["contractId"] == 2


async def test_instant_coupon_pages_keep_distinct_indexes_and_type_query() -> None:
    reader = _Reader(
        {
            "data": {
                "success": True,
                "content": [
                    {
                        "couponId": 91,
                        "status": "APPLIED",
                        "type": "RATE",
                        "promotionName": "원피스 할인",
                        "wowExclusive": "false",
                        "buyerPhone": "010-9999-8888",
                    }
                ],
                "pagination": {
                    "currentPage": 1,
                    "countPerPage": 10,
                    "totalPages": 2,
                    "totalElements": 11,
                    "nextToken": "secret-token",
                },
            }
        }
    )
    facade = CoupangGeneralMissingReads(reader)
    listed = await facade.read(
        "instant_coupons_by_status",
        status="APPLIED",
        page=1,
        size=10,
        sort="desc",
    )

    assert listed.items == (
        {"couponId": 91, "status": "APPLIED", "type": "RATE", "promotionName": "원피스 할인"},
    )
    assert listed.page == {
        "currentPage": 1,
        "countPerPage": 10,
        "totalPages": 2,
        "totalElements": 11,
    }
    assert "false" not in str(listed.items)
    assert "010-9999-8888" not in str(_safe(listed))
    assert "secret-token" not in str(listed.page)
    assert reader.calls[-1][1]["query"] == {
        "status": "APPLIED",
        "page": 1,
        "size": 10,
        "sort": "desc",
    }
    assert "vendorId" not in reader.calls[-1][1]["path"]

    reader.calls.clear()
    with pytest.raises(MissingReadError) as bad_page:
        await facade.read("instant_coupons_by_status", status="APPLIED", page=0)
    assert reader.calls == []
    assert "@" not in str(bad_page.value)

    reader.payload = {
        "data": {
            "success": True,
            "content": [
                {
                    "couponItemId": 80984,
                    "couponId": 77,
                    "vendorItemId": 3223826213,
                    "status": "APPLIED",
                }
            ],
            "pagination": {
                "currentPage": 0,
                "countPerPage": 10,
                "totalPages": 1,
                "totalElements": 1,
            },
        }
    }
    items = await facade.read(
        "instant_coupon_items_by_status",
        coupon_id="77",
        status="APPLIED",
        page=0,
        size=10,
    )
    assert items.page["currentPage"] == 0
    assert reader.calls[-1][1] == {
        "path": {"couponId": "77"},
        "query": {"status": "APPLIED", "page": 0, "size": 10},
    }

    reader.calls.clear()
    with pytest.raises(MissingReadError):
        await facade.read(
            "instant_coupon_items_by_status",
            coupon_id="77",
            status="DETACHED",
            page=0,
        )
    assert reader.calls == []


async def test_item_lookups_do_not_let_caller_swap_type() -> None:
    reads = list_missing_reads()
    by_coupon_item = next(
        item for item in reads if item.operation_id == "instant_coupon_item_by_coupon_item_id"
    )
    by_vendor_item = next(
        item for item in reads if item.operation_id == "instant_coupon_item_by_vendor_item_id"
    )
    assert _norm(by_coupon_item.path_template) == _norm(by_vendor_item.path_template)
    assert by_coupon_item.path_template != by_vendor_item.path_template

    reader = _Reader(
        {
            "data": {
                "success": True,
                "content": {
                    "couponItemId": 80984,
                    "couponId": 77,
                    "vendorItemId": 3223826213,
                    "status": "APPLIED",
                    "startAt": "2017-08-04 01:00:00",
                    "endAt": "2017-09-01 00:00:00",
                    "reason": "내부 메모",
                },
                "pagination": None,
            }
        }
    )
    facade = CoupangGeneralMissingReads(reader)
    result = await facade.read(
        "instant_coupon_item_by_coupon_item_id",
        coupon_id="77",
        coupon_item_id="80984",
    )

    assert reader.calls[-1][1]["query"] == {"type": "couponItemId"}
    assert reader.calls[-1][1]["path"] == {"couponId": "77", "couponItemId": "80984"}
    assert "reason" not in result.items[0]
    assert result.items[0]["status"] == "APPLIED"

    reader.calls.clear()
    with pytest.raises(MissingReadError):
        await facade.read(
            "instant_coupon_item_by_coupon_item_id",
            coupon_id="77",
            coupon_item_id="80984",
            type="vendorItemId",
        )
    assert reader.calls == []

    await facade.read(
        "instant_coupon_item_by_vendor_item_id",
        coupon_id="76",
        vendor_item_id="3223826213",
    )
    assert reader.calls[-1][1]["query"] == {"type": "vendorItemId"}
    assert reader.calls[-1][1]["path"]["vendorItemId"] == "3223826213"


async def test_request_status_drops_free_text_reason() -> None:
    reader = _Reader(
        {
            "data": {
                "success": True,
                "content": {
                    "couponId": 778,
                    "requestedId": "4080133932843441",
                    "type": "COUPON_PUBLISH",
                    "status": "DONE",
                    "total": 1,
                    "succeeded": 1,
                    "failed": 0,
                    "failedVendorItems": [
                        {"vendorItemId": 32261389517, "reason": "email@example.test"}
                    ],
                },
                "pagination": None,
            }
        }
    )
    result = await CoupangGeneralMissingReads(reader).read(
        "instant_coupon_request_status", requested_id="649102321051192483"
    )

    assert result.items[0]["status"] == "DONE"
    assert result.items[0]["failedVendorItems"] == ({"vendorItemId": 32261389517},)
    assert "email@example.test" not in str(_safe(result))
    assert reader.calls[0][1]["path"] == {"requestedId": "649102321051192483"}


async def test_cashback_drops_vendor_id_from_documented_example() -> None:
    reader = _Reader(
        {
            "code": "200",
            "message": "OK",
            "data": {
                "vendorItemId": 3000000005,
                "vendorId": "A00012345",
                "valueType": "FIXED",
                "value": 1000,
                "ruleId": 1,
                "disabled": False,
                "maxAmount": "1000",
                "startAt": "2016-12-29 09:43:54",
                "endAt": "2017-01-01 09:43:54",
            },
        }
    )
    result = await CoupangGeneralMissingReads(reader).read(
        "cashback_rule", rule_id="1", vendor_item_id="3000000005"
    )

    assert "vendorId" not in result.items[0]
    assert "A00012345" not in str(_safe(result))
    assert "maxAmount" not in result.items[0]
    assert result.items[0]["valueType"] == "FIXED"
    assert result.items[0]["disabled"] is False
    assert reader.calls[0][1]["path"] == {}
    assert reader.calls[0][1]["query"] == {"ruleId": "1", "vendorItemId": "3000000005"}


async def test_disabled_query_post_never_calls_reader() -> None:
    reader = _Reader({"data": []})
    facade = CoupangGeneralMissingReads(reader)

    with pytest.raises(DisabledQueryPostError) as error:
        facade.refuse_query_post("brand_search")
    assert reader.calls == []
    assert "NIKE" not in str(error.value)

    with pytest.raises(DisabledQueryPostError):
        await facade.read("category_predict", product_name="코트")
    assert reader.calls == []
    assert "코트" not in str(error.value)

    with pytest.raises(DisabledQueryPostError):
        await facade.read("return_withdraw_by_receipt", cancel_ids=(1,))
    assert reader.calls == []


async def test_live_client_and_missing_reader_are_refused_before_call() -> None:
    class CoupangClient:
        async def __call__(self, operation_id: str, request: dict[str, object]) -> object:
            raise AssertionError("live client was called")

    with pytest.raises(MissingReadError):
        await CoupangGeneralMissingReads(CoupangClient()).read("enrolled_brands")

    with pytest.raises(MissingReadError):
        await CoupangGeneralMissingReads().read("enrolled_brands")


async def test_order_coupon_query_does_not_send_vendor_id() -> None:
    reader = _Reader(
        {
            "data": {
                "success": True,
                "content": [
                    {
                        "vendorItemId": 5500016112,
                        "couponId": 91,
                        "status": "PAUSED",
                        "promotionName": "서울특별시 강남구 테헤란로 1",
                    }
                ],
                "pagination": None,
            }
        }
    )
    result = await CoupangGeneralMissingReads(reader).read(
        "instant_coupons_by_order", order_id="8000000000294"
    )

    assert reader.calls[0][1]["path"] == {"orderId": "8000000000294"}
    assert "promotionName" not in result.items[0]
    assert "서울" not in str(_safe(result))
    assert result.items[0]["couponId"] == 91
