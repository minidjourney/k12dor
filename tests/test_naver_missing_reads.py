"""Synthetic coverage for Naver GETs absent from the client allowlist.

No live network, no raw provider payload, no customer PII.
"""

from __future__ import annotations

import re
from datetime import datetime

import pytest

from k12_commerce_mcp.clients.naver import ALLOWED_CALLS, WRITE_ALLOWED_CALLS


def _clock() -> datetime:
    return datetime.fromisoformat("2026-09-29T00:00:00+00:00")


class SyntheticTransport:
    synthetic = True

    def __init__(self, status_code: int, body: object) -> None:
        self.status_code = status_code
        self.body = body
        self.calls: list[tuple[str, str]] = []

    async def exchange(self, *, method: str, path: str) -> tuple[int, object]:
        self.calls.append((method, path))
        return self.status_code, self.body


def _norm(path: str) -> str:
    path = re.sub(r"\{[^}]+\}", "{}", path)
    return re.sub(r":[A-Za-z0-9_]+", "{}", path)


def test_catalog_keeps_confirmed_missing_gets_off_the_client_allowlist() -> None:
    from k12_commerce_mcp.adapters.naver.missing_reads import missing_read_catalog

    catalog = missing_read_catalog()
    allowed = {(method, _norm(path)) for method, path in ALLOWED_CALLS | WRITE_ALLOWED_CALLS}
    assert catalog
    assert all(
        ((item.method, _norm(item.path)) in allowed) == item.on_client_allowlist for item in catalog
    )

    hope = next(item for item in catalog if item.operation == "hope_delivery_groups")
    assert hope.method == "GET"
    assert hope.path == "/v1/product-delivery-info/hope-delivery-groups"
    assert hope.category == "delivery"
    assert hope.projection == "projected"
    assert "get-hope-delivery-group-list-product.html" in hope.source_doc
    assert hope.on_client_allowlist is True

    disabled = next(item for item in catalog if item.operation == "sku_query_paged_list")
    assert disabled.method == "POST"
    assert disabled.path == "/v1/logistics/products/sellers/me/skus/query-paged-list"
    assert disabled.projection == "disabled_read_post"
    assert "get-ns-information-paged-list-nfa-product.html" in disabled.source_doc


async def test_hope_delivery_groups_project_schema_fields_and_drop_pii_values() -> None:
    transport = SyntheticTransport(
        200,
        [
            {
                "id": 12,
                "name": "오전 배송",
                "usable": True,
                "baseGroup": False,
                "hopeGroupStartTime": 9,
                "hopeGroupEndTime": 12,
                "regularHolidays": ["SUNDAY", "SECRETDAY"],
                "ladderTruckUseComment": "010-1234-5678",
                "productRemovalType": "COLLECT_SELLER",
                "customerName": "홍길동",
                "hopeDeliveryGroupDays": [
                    {
                        "id": 3,
                        "regionName": "서울시 강남구 테헤란로 1",
                        "usable": True,
                        "hopeStartDay": 1,
                        "hopeEndDay": 3,
                        "expectationDeliveryFee": 2500,
                        "address": "서울시 강남구 테헤란로 1",
                    }
                ],
            }
        ],
    )
    from k12_commerce_mcp.adapters.naver.missing_reads import NaverMissingReads

    page = await NaverMissingReads(transport, clock=_clock).read_hope_delivery_groups(page_size=1)

    assert transport.calls == [("GET", "/v1/product-delivery-info/hope-delivery-groups")]
    assert page.evidence.method == "GET"
    assert page.evidence.projection == "projected"
    assert page.evidence.operational_integration == "incomplete"
    assert page.kind == "page"
    assert len(page.items) == 1
    item = page.items[0]
    assert item.group_id == "12"
    assert item.name == "오전 배송"
    assert item.usable is True
    assert item.base_group is False
    assert item.regular_holidays == ("SUNDAY",)
    assert item.ladder_truck_use_comment is None
    assert item.product_removal_type == "COLLECT_SELLER"
    assert item.days[0].region_name is None
    assert item.days[0].expectation_delivery_fee == 2500
    dumped = page.model_dump_json()
    assert "010-1234-5678" not in dumped
    assert "홍길동" not in dumped
    assert "테헤란로" not in dumped
    assert "customerName" not in dumped
    assert "SECRETDAY" not in dumped


async def test_hope_delivery_group_uses_the_captured_path_and_rejects_an_over_max_fee() -> None:
    transport = SyntheticTransport(
        200,
        {
            "id": 9,
            "name": "기본",
            "usable": True,
            "baseGroup": True,
            "hopeDeliveryGroupDays": [
                {"id": 1, "regionName": "수도권", "usable": True, "expectationDeliveryFee": 100001}
            ],
        },
    )
    from k12_commerce_mcp.adapters.base import AdapterInvalidResponseError
    from k12_commerce_mcp.adapters.naver.missing_reads import NaverMissingReads

    with pytest.raises(AdapterInvalidResponseError) as caught:
        await NaverMissingReads(transport, clock=_clock).read_hope_delivery_group(group_id=9)

    assert transport.calls == [("GET", "/v1/product-delivery-info/hope-delivery-groups/9")]
    assert "100001" not in str(caught.value)
    assert "수도권" not in str(caught.value)


async def test_documented_404_is_not_a_page_and_does_not_echo_the_body() -> None:
    transport = SyntheticTransport(404, {"code": "NOT_FOUND", "message": "홍길동 010-1111-2222"})
    from k12_commerce_mcp.adapters.naver.missing_reads import (
        MissingReadStatusError,
        NaverMissingReads,
    )

    with pytest.raises(MissingReadStatusError) as caught:
        await NaverMissingReads(transport, clock=_clock).read_hope_delivery_groups(page_size=1)

    assert caught.value.status_code == 404
    assert caught.value.code == "not_found"
    text = str(caught.value)
    assert "홍길동" not in text
    assert "010-1111-2222" not in text
    assert "NOT_FOUND" not in text


async def test_http_200_error_code_is_not_a_page() -> None:
    transport = SyntheticTransport(200, {"code": "BAD_REQUEST", "message": "a@example.com"})
    from k12_commerce_mcp.adapters.naver.missing_reads import (
        MissingReadStatusError,
        NaverMissingReads,
    )

    with pytest.raises(MissingReadStatusError) as caught:
        await NaverMissingReads(transport, clock=_clock).read_hope_delivery_groups(page_size=1)

    assert caught.value.status_code == 200
    assert "a@example.com" not in str(caught.value)


async def test_return_companies_project_schema_and_reject_an_oversized_page() -> None:
    transport = SyntheticTransport(
        200,
        [
            {
                "id": 4,
                "name": "관측택배",
                "returnDeliveryCompanyPriorityType": "PRIMARY",
                "phone": "010-0000-0000",
            },
            {"id": 5, "name": "둘", "returnDeliveryCompanyPriorityType": "SECONDARY_1"},
        ],
    )
    from k12_commerce_mcp.adapters.base import AdapterInvalidRequestError
    from k12_commerce_mcp.adapters.naver.missing_reads import NaverMissingReads

    # The retired synthetic facade must not reimplement an operational MCP read.
    with pytest.raises(AdapterInvalidRequestError):
        await NaverMissingReads(transport, clock=_clock).read_return_delivery_companies(page_size=1)

    assert transport.calls == []


async def test_subscription_projects_closed_schema_and_drops_the_open_map() -> None:
    transport = SyntheticTransport(
        200,
        {
            "accountUid": "acc-1",
            "solutionId": "sol-1",
            "status": "SUBSCRIBING",
            "round": 2,
            "reason": "010-9999-0000",
            "plan": {
                "id": "plan-1",
                "grade": "PLUS",
                "name": "플러스",
                "additionalInfo": {"customerEmail": "a@example.com", "note": "숨김"},
            },
            "additionalInfo": {"token": "secret-value"},
            "reserve": {
                "type": "DOWNGRADE",
                "plan": {"id": "plan-0", "grade": "FREE", "name": "무료"},
            },
        },
    )
    from k12_commerce_mcp.adapters.naver.missing_reads import NaverMissingReads

    item = await NaverMissingReads(transport, clock=_clock).read_solution_subscription(
        account_uid="acc-1"
    )

    assert transport.calls == [("GET", "/v1/commerce-solutions/subscriptions/acc-1")]
    assert item.kind == "item"
    assert item.account_uid is None  # An external account identifier is input-only.
    assert item.solution_id == "sol-1"
    assert item.status == "SUBSCRIBING"
    assert item.round_no == 2
    assert item.reason is None
    assert item.plan_grade == "PLUS"
    assert item.plan_name == "플러스"
    assert item.reserve_type == "DOWNGRADE"
    dumped = item.model_dump_json()
    assert "a@example.com" not in dumped
    assert "secret-value" not in dumped
    assert "010-9999-0000" not in dumped
    assert "additionalInfo" not in dumped
    assert "customerEmail" not in dumped


async def test_withheld_reads_copy_no_values_and_disabled_reads_stay_unsent() -> None:
    transport = SyntheticTransport(
        200,
        {
            "accountName": "홍길동",
            "email": "a@example.com",
            "phone": "010-1111-2222",
            "address": "서울시 강남구 테헤란로 1",
        },
    )
    from k12_commerce_mcp.adapters.base import AdapterUnsupportedError
    from k12_commerce_mcp.adapters.naver.missing_reads import NaverMissingReads

    reader = NaverMissingReads(transport, clock=_clock)
    page = await reader.read_catalogued("seller_account", page_size=1)
    guide = await reader.read_catalogued("purchase_option_guides", page_size=1)

    assert transport.calls == [
        ("GET", "/v1/seller/account"),
        ("GET", "/v2/standard-purchase-option-guides"),
    ]
    assert page.evidence.projection == "pii_withheld"
    assert page.kind == "page"
    assert page.items == ()
    assert page.row_count == 1
    assert guide.evidence.projection == "fields_not_in_capture"
    assert guide.items == ()
    dumped = page.model_dump_json() + guide.model_dump_json()
    assert "홍길동" not in dumped
    assert "a@example.com" not in dumped
    assert "테헤란로" not in dumped
    assert "accountName" not in dumped

    disabled = SyntheticTransport(200, {"token": "secret-value"})
    blocked = NaverMissingReads(disabled, clock=_clock)
    with pytest.raises(AdapterUnsupportedError):
        await blocked.read_catalogued("seller_info_by_token")
    with pytest.raises(AdapterUnsupportedError):
        await blocked.read_catalogued("sku_query_paged_list")
    assert disabled.calls == []


async def test_address_read_requires_a_safe_path_token_and_copies_no_address() -> None:
    transport = SyntheticTransport(
        200,
        {"baseAddress": "서울시 강남구 테헤란로 1", "tel": "010-1111-2222", "name": "홍길동"},
    )
    from k12_commerce_mcp.adapters.base import AdapterInvalidRequestError
    from k12_commerce_mcp.adapters.naver.missing_reads import NaverMissingReads

    reader = NaverMissingReads(transport, clock=_clock)
    with pytest.raises(AdapterInvalidRequestError):
        await reader.read_catalogued("seller_address", page_size=1, path_token="010-1111-2222")
    page = await reader.read_catalogued("seller_address", page_size=1, path_token="12")
    assert transport.calls == [("GET", "/v1/seller/addressbooks/12")]
    assert page.evidence.projection == "pii_withheld"
    assert page.items == ()
    dumped = page.model_dump_json()
    assert "테헤란로" not in dumped
    assert "홍길동" not in dumped
    assert "010-1111-2222" not in dumped


async def test_undocumented_cursor_is_rejected_before_transport() -> None:
    transport = SyntheticTransport(200, [])
    from k12_commerce_mcp.adapters.base import AdapterInvalidRequestError
    from k12_commerce_mcp.adapters.naver.missing_reads import NaverMissingReads

    with pytest.raises(AdapterInvalidRequestError):
        await NaverMissingReads(transport, clock=_clock).read_hope_delivery_groups(
            page_size=1, cursor="2"
        )
    assert transport.calls == []


def test_real_client_is_refused_and_catalog_counts_match_the_capture() -> None:
    from k12_commerce_mcp.adapters.base import AdapterInvalidRequestError
    from k12_commerce_mcp.adapters.naver.missing_reads import (
        NaverMissingReads,
        missing_read_catalog,
    )
    from k12_commerce_mcp.clients.naver import NaverClient, NaverCredentials

    with pytest.raises(AdapterInvalidRequestError):
        NaverMissingReads(NaverClient(NaverCredentials("client-id", "client-secret")))

    catalog = missing_read_catalog()
    gets = [item for item in catalog if item.method == "GET"]
    posts = [item for item in catalog if item.method != "GET"]
    assert len(gets) == 23
    assert [(item.method, item.projection) for item in posts] == [("POST", "disabled_read_post")]
    assert {item.category for item in gets} >= {
        "delivery",
        "seller",
        "solution",
        "product_guide",
    }
    assert {item.operation for item in gets if item.projection == "projected"} == {
        "hope_delivery_groups",
        "hope_delivery_group",
        "solution_subscription",
    }
