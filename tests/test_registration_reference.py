"""Marketplace registration reference reads: transport, mapping, safety.

All tests run on mock httpx transports or stub clients. No live network.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from mcp import Client

from k12_commerce_mcp.adapters.base import (
    AdapterInvalidRequestError,
    AdapterInvalidResponseError,
)
from k12_commerce_mcp.adapters.naver import NaverAdapter
from k12_commerce_mcp.adapters.toss import TossShoppingAdapter
from k12_commerce_mcp.clients.naver import (
    NaverClient,
    NaverCredentials,
    NaverPage,
    NaverProviderError,
)
from k12_commerce_mcp.clients.toss import (
    TossShoppingClient,
    TossShoppingCredentials,
    TossShoppingProviderError,
)
from k12_commerce_mcp.models import (
    Channel,
    MarketplaceCategoryRequirementResult,
    MarketplaceCategoryResult,
    MarketplaceRegistrationResourceResult,
    ResultStatus,
)
from k12_commerce_mcp.registry import AdapterRegistry
from k12_commerce_mcp.security import assert_agent_safe_schema
from k12_commerce_mcp.server import build_server
from k12_commerce_mcp.service import CommerceService

BCRYPT_SECRET = "$2b$10$abcdefghijklmnopqrstuu"
NAVER_TOKEN_RESPONSE = httpx.Response(
    200, json={"access_token": "synthetic-token", "expires_in": 3600}
)
TOSS_TOKEN_RESPONSE = httpx.Response(
    200,
    json={
        "access_token": "synthetic-token",
        "expires_in": 3600,
        "scope": "toss-shopping-fep:write",
        "token_type": "Bearer",
    },
)
TOSS_API_BASE = "https://shopping-fep.toss.im/api/v3/shopping-fep"


def FIXED_CLOCK() -> datetime:
    return datetime(2026, 9, 14, 1, 0, tzinfo=UTC)


def _naver_client(handler) -> NaverClient:
    return NaverClient(
        NaverCredentials("client-id", BCRYPT_SECRET),
        transport=httpx.MockTransport(handler),
        clock_ms=lambda: 1_789_315_200_000,
    )


def _toss_client(handler) -> TossShoppingClient:
    return TossShoppingClient(
        TossShoppingCredentials("synthetic-access", "synthetic-secret"),
        transport=httpx.MockTransport(handler),
    )


def _toss_success(payload: Any) -> httpx.Response:
    return httpx.Response(200, json={"resultType": "SUCCESS", "success": payload})


# ---------------------------------------------------------------------------
# Transport allowlists and request shapes
# ---------------------------------------------------------------------------


def test_naver_standard_options_path_is_read_allowlisted() -> None:
    NaverClient._validate_call("GET", "/v1/options/standard-options")
    with pytest.raises(ValueError, match="read-only allowlist"):
        NaverClient._validate_call("POST", "/v1/options/standard-options")
    with pytest.raises(ValueError, match="WRITE allowlist"):
        NaverClient._validate_call("GET", "/v1/options/standard-options", write=True)


async def test_naver_standard_options_hits_documented_get() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/external/v1/oauth2/token":
            return NAVER_TOKEN_RESPONSE
        return httpx.Response(
            200,
            json={"useStandardOption": True, "standardOptionCategoryGroups": []},
        )

    payload = await _naver_client(handler).get_standard_options(category_id=50000000)

    assert payload == {"useStandardOption": True, "standardOptionCategoryGroups": []}
    assert [(r.method, r.url.path) for r in seen] == [
        ("POST", "/external/v1/oauth2/token"),
        ("GET", "/external/v1/options/standard-options"),
    ]
    assert list(seen[1].url.params.multi_items()) == [("categoryId", "50000000")]


async def test_naver_standard_options_rejects_non_dict_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/external/v1/oauth2/token":
            return NAVER_TOKEN_RESPONSE
        return httpx.Response(200, json=["not", "a", "dict"])

    with pytest.raises(NaverProviderError, match="shape is invalid"):
        await _naver_client(handler).get_standard_options(category_id=50000000)


TOSS_REFERENCE_GETS = (
    f"{TOSS_API_BASE}/products/categories/children",
    f"{TOSS_API_BASE}/category/55/constraint-templates",
    f"{TOSS_API_BASE}/notices/category-codes",
    f"{TOSS_API_BASE}/notices",
    f"{TOSS_API_BASE}/merchants/group-delivery/delivery-location/v2",
    f"{TOSS_API_BASE}/merchants/group-delivery/exchange-refund-location/v2",
)


@pytest.mark.parametrize("url", TOSS_REFERENCE_GETS)
def test_toss_reference_gets_are_read_allowlisted(url: str) -> None:
    TossShoppingClient._validate_call("GET", url)


@pytest.mark.parametrize(
    ("method", "url"),
    [
        ("POST", f"{TOSS_API_BASE}/products/categories/children"),
        ("GET", f"{TOSS_API_BASE}/merchants/group-delivery/delivery-location"),
        ("GET", f"{TOSS_API_BASE}/merchants/group-delivery/exchange-refund-location"),
        ("GET", f"{TOSS_API_BASE}/category/not-a-number/constraint-templates"),
        ("GET", f"{TOSS_API_BASE}/merchants/holidays"),
        ("GET", f"{TOSS_API_BASE}/delivery-companies"),
    ],
)
def test_toss_reference_boundary_paths_stay_blocked(method: str, url: str) -> None:
    with pytest.raises(ValueError, match="read-only allowlist"):
        TossShoppingClient._validate_call(method, url)


async def test_toss_reference_methods_hit_only_documented_gets() -> None:
    seen: list[tuple[str, str, tuple[tuple[str, str], ...]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth2.cert.toss.im":
            return TOSS_TOKEN_RESPONSE
        seen.append(
            (
                request.method,
                request.url.path,
                tuple(request.url.params.multi_items()),
            )
        )
        path = request.url.path
        if path.endswith("/categories/children"):
            return _toss_success({"categories": []})
        if path.endswith("/constraint-templates"):
            return _toss_success({"categorySalesOptions": []})
        if path.endswith("/category-codes"):
            return _toss_success({"categoryCodes": []})
        if path.endswith("/notices"):
            return _toss_success({"notices": []})
        if path.endswith("/delivery-location/v2"):
            return _toss_success({"locations": []})
        if path.endswith("/exchange-refund-location/v2"):
            return _toss_success({"locations": []})
        return _toss_success({})

    client = _toss_client(handler)
    await client.list_category_children()
    await client.list_category_children(parent_category_id=55)
    await client.get_category_constraint_templates(55)
    await client.list_notice_category_codes()
    await client.list_notices(category_code="FURNITURE")
    await client.list_delivery_locations_v2()
    await client.list_exchange_refund_locations_v2()

    assert [(method, path) for method, path, _ in seen] == [
        ("GET", "/api/v3/shopping-fep/products/categories/children"),
        ("GET", "/api/v3/shopping-fep/products/categories/children"),
        ("GET", "/api/v3/shopping-fep/category/55/constraint-templates"),
        ("GET", "/api/v3/shopping-fep/notices/category-codes"),
        ("GET", "/api/v3/shopping-fep/notices"),
        ("GET", "/api/v3/shopping-fep/merchants/group-delivery/delivery-location/v2"),
        (
            "GET",
            "/api/v3/shopping-fep/merchants/group-delivery/exchange-refund-location/v2",
        ),
    ]
    assert seen[1][2] == (("id", "55"),)
    assert seen[4][2] == (("categoryCode", "FURNITURE"),)


async def test_toss_reference_rows_fail_closed_on_unknown_shapes() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth2.cert.toss.im":
            return TOSS_TOKEN_RESPONSE
        return _toss_success({"unexpected": "shape"})

    client = _toss_client(handler)
    for call in (
        client.list_category_children,
        client.list_notice_category_codes,
        client.list_delivery_locations_v2,
        client.list_exchange_refund_locations_v2,
    ):
        with pytest.raises(TossShoppingProviderError, match="shape is invalid"):
            await call()


async def test_toss_reference_accepts_success_row_lists() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth2.cert.toss.im":
            return TOSS_TOKEN_RESPONSE
        return _toss_success([{"id": 55, "name": "관측", "isLeaf": False}])

    rows = await _toss_client(handler).list_category_children()

    assert rows == ({"id": 55, "name": "관측", "isLeaf": False},)


# ---------------------------------------------------------------------------
# Naver adapter mapping
# ---------------------------------------------------------------------------


def _naver_category_rows() -> tuple[dict[str, Any], ...]:
    return (
        {
            "id": 50000000,
            "name": "패션의류",
            "wholeCategoryName": "패션의류",
            "last": False,
        },
        {
            "id": "50000001",
            "name": "여성의류",
            "wholeCategoryName": "패션의류>여성의류",
            "last": True,
        },
    )


async def test_naver_categories_map_strict_fields() -> None:
    class FakeClient:
        credentials = NaverCredentials("client-id", "synthetic-secret")

        async def list_categories(self) -> tuple[dict[str, Any], ...]:
            return _naver_category_rows()

    adapter = NaverAdapter(FakeClient(), clock=FIXED_CLOCK)
    items = await adapter.get_marketplace_categories()

    assert [item.category_id for item in items] == ["50000000", "50000001"]
    root, leaf = items
    assert root.channel is Channel.NAVER
    assert root.parent_category_id is None
    assert root.full_path == "패션의류"
    assert root.level == 1
    assert root.is_leaf is False
    assert leaf.full_path == "패션의류>여성의류"
    assert leaf.level == 2
    assert leaf.is_leaf is True
    assert leaf.source.method == "GET"


async def test_naver_complete_category_bound_accepts_current_catalog_size() -> None:
    class FakeClient:
        credentials = NaverCredentials("client-id", "synthetic-secret")

        async def list_categories(self) -> tuple[dict[str, Any], ...]:
            return tuple(
                {
                    "id": 50_000_000 + index,
                    "name": f"카테고리 {index}",
                    "last": True,
                    "wholeCategoryName": f"대분류>카테고리 {index}",
                }
                for index in range(5_820)
            )

    items = await NaverAdapter(FakeClient(), clock=FIXED_CLOCK).get_marketplace_categories()

    assert len(items) == 5_820


async def test_naver_categories_reject_malformed_parent_and_bad_rows() -> None:
    class FakeClient:
        credentials = NaverCredentials("client-id", "synthetic-secret")

        async def list_categories(self) -> tuple[dict[str, Any], ...]:
            return ({"id": 1, "name": "x", "last": "yes"},)

    adapter = NaverAdapter(FakeClient(), clock=FIXED_CLOCK)
    with pytest.raises(AdapterInvalidRequestError):
        await adapter.get_marketplace_categories(parent_category_id="1/../2")
    with pytest.raises(AdapterInvalidResponseError):
        await adapter.get_marketplace_categories()


async def test_naver_requirements_map_standard_option_descriptors() -> None:
    class FakeClient:
        credentials = NaverCredentials("client-id", "synthetic-secret")

        async def get_standard_options(self, *, category_id: int) -> dict[str, Any]:
            assert category_id == 50000000
            return {
                "useStandardOption": True,
                "standardOptionCategoryGroups": [
                    {
                        "groupName": "사이즈",
                        "standardOptionAttributes": [
                            {
                                "attributeName": "사이즈",
                                "required": True,
                                "attributeValues": [
                                    {"attributeValueName": "S"},
                                    {"attributeValueName": "M"},
                                ],
                                "attributeValueUnits": [{"unitName": "cm"}],
                                "useImage": True,
                            }
                        ],
                    }
                ],
                "rawEnvelopeNoise": "must not propagate",
            }

    adapter = NaverAdapter(FakeClient(), clock=FIXED_CLOCK)
    requirements = await adapter.get_marketplace_category_requirements(
        category_id="50000000"
    )

    assert requirements.channel is Channel.NAVER
    assert requirements.category_id == "50000000"
    assert requirements.notice_categories == ()
    assert requirements.notices == ()
    assert len(requirements.descriptors) == 1
    descriptor = requirements.descriptors[0]
    assert descriptor.key == "사이즈"
    assert descriptor.required is True
    assert descriptor.allowed_value_names == ("S", "M")
    assert descriptor.unit_names == ("cm",)
    assert descriptor.image_allowed is True
    assert "must not propagate" not in requirements.model_dump_json()


async def test_naver_requirements_fail_closed_on_malformed_payload() -> None:
    class FakeClient:
        credentials = NaverCredentials("client-id", "synthetic-secret")

        async def get_standard_options(self, *, category_id: int) -> dict[str, Any]:
            return {"unrelated": True}

    adapter = NaverAdapter(FakeClient(), clock=FIXED_CLOCK)
    with pytest.raises(AdapterInvalidResponseError):
        await adapter.get_marketplace_category_requirements(category_id="50000000")
    with pytest.raises(AdapterInvalidRequestError):
        await adapter.get_marketplace_category_requirements(
            category_id="50000000", notice_category_code="FURNITURE"
        )
    with pytest.raises(AdapterInvalidRequestError):
        await adapter.get_marketplace_category_requirements(category_id="abc")


async def test_naver_resources_map_bundle_groups_without_sensitive_fields() -> None:
    class FakeClient:
        credentials = NaverCredentials("client-id", "synthetic-secret")

        async def list_delivery_bundle_groups(self, **kwargs: Any) -> NaverPage:
            return NaverPage(
                rows=(
                    {
                        "id": 12,
                        "name": "기본 묶음",
                        "isDefault": True,
                        "deliveryType": "DIRECT",
                        "secretNote": "must not propagate",
                    },
                ),
                next_cursor=None,
            )

        async def list_seller_addressbooks(self, *, page: int = 1) -> NaverPage:
            assert page == 1
            return NaverPage(
                rows=(
                    {
                        "addressBookNo": 31,
                        "name": "기본 출고지",
                        "addressType": "RELEASE",
                    },
                    {
                        "addressBookNo": 32,
                        "name": "기본 반품지",
                        "addressType": "REFUND_OR_EXCHANGE",
                    },
                ),
                next_cursor=None,
            )

    adapter = NaverAdapter(FakeClient(), clock=FIXED_CLOCK)
    items = await adapter.get_marketplace_registration_resources()

    assert len(items) == 3
    item = items[0]
    assert item.channel is Channel.NAVER
    assert item.resource_id == "12"
    assert item.name == "기본 묶음"
    assert item.is_default is True
    assert item.resource_type == "delivery_bundle_group"
    assert item.selectors == {"deliveryType": "DIRECT"}
    assert "must not propagate" not in item.model_dump_json()
    assert items[1].resource_id.startswith("naver-addressbook-hmac-v1:")
    assert items[1].resource_id != items[2].resource_id
    assert items[1].resource_type == "delivery_location"
    assert items[1].name == "출고지 1"
    assert items[1].selectors == {"location_kind": "release"}
    assert items[2].resource_id.startswith("naver-addressbook-hmac-v1:")
    assert items[2].resource_type == "exchange_refund_location"
    assert items[2].name == "반품지 1"
    assert items[2].selectors == {"location_kind": "exchange_return"}


# ---------------------------------------------------------------------------
# Toss adapter mapping
# ---------------------------------------------------------------------------


def _toss_category_rows() -> tuple[dict[str, Any], ...]:
    return (
        {"id": 55, "name": "가구", "isLeaf": False},
        {"id": 56, "name": "침대", "isLeaf": True, "level": 3},
    )


async def test_toss_categories_map_children_rows() -> None:
    calls: list[int | None] = []

    class FakeClient:
        credentials = TossShoppingCredentials("synthetic-access", "synthetic-secret")

        async def list_category_children(
            self, *, parent_category_id: int | None = None
        ) -> tuple[dict[str, Any], ...]:
            calls.append(parent_category_id)
            return _toss_category_rows()

    adapter = TossShoppingAdapter(FakeClient(), clock=FIXED_CLOCK)
    items = await adapter.get_marketplace_categories(parent_category_id="44")

    assert calls == [44]
    first, second = items
    assert first.channel is Channel.TOSS_STORE
    assert first.category_id == "55"
    assert first.parent_category_id == "44"
    assert first.full_path is None
    assert first.level is None
    assert first.is_leaf is False
    assert second.level == 3
    assert second.is_leaf is True


async def test_toss_categories_reject_bad_ids_and_rows() -> None:
    class FakeClient:
        credentials = TossShoppingCredentials("synthetic-access", "synthetic-secret")

        async def list_category_children(
            self, *, parent_category_id: int | None = None
        ) -> tuple[dict[str, Any], ...]:
            return ({"id": 55, "name": "x"},)

    adapter = TossShoppingAdapter(FakeClient(), clock=FIXED_CLOCK)
    with pytest.raises(AdapterInvalidRequestError):
        await adapter.get_marketplace_categories(parent_category_id="abc")
    with pytest.raises(AdapterInvalidResponseError):
        await adapter.get_marketplace_categories()


async def test_toss_requirements_map_templates_notices_and_codes() -> None:
    calls: list[str] = []

    class FakeClient:
        credentials = TossShoppingCredentials("synthetic-access", "synthetic-secret")

        async def get_category_constraint_templates(
            self, category_id: int
        ) -> dict[str, Any]:
            calls.append(f"templates:{category_id}")
            return {
                "categorySalesOptions": [
                    {
                        "optionName": "색상",
                        "isRequired": True,
                        "values": [{"valueName": "검정"}, "흰색"],
                    }
                ],
                "categorySearchOptions": [
                    {"name": "소재", "required": False}
                ],
            }

        async def list_notice_category_codes(self) -> tuple[dict[str, Any], ...]:
            calls.append("codes")
            return ({"categoryCode": "FURNITURE", "name": "가구"},)

        async def list_notices(self, *, category_code: str) -> tuple[dict[str, Any], ...]:
            calls.append(f"notices:{category_code}")
            return (
                {
                    "id": 27,
                    "title": "소재/재질",
                    "required": True,
                    "content": "나무, 가죽",
                },
            )

    adapter = TossShoppingAdapter(FakeClient(), clock=FIXED_CLOCK)
    requirements = await adapter.get_marketplace_category_requirements(
        category_id="55", notice_category_code="FURNITURE"
    )

    assert calls == ["templates:55", "codes", "notices:FURNITURE"]
    assert requirements.category_id == "55"
    keys = [d.key for d in requirements.descriptors]
    assert keys == ["색상", "소재"]
    color = requirements.descriptors[0]
    assert color.required is True
    assert color.allowed_value_names == ("검정", "흰색")
    assert requirements.notice_categories[0].category_code == "FURNITURE"
    assert requirements.notice_categories[0].title == "가구"
    assert requirements.notices[0].notice_id == "27"
    assert requirements.notices[0].title == "소재/재질"
    assert requirements.notices[0].required is True
    assert "나무, 가죽" not in requirements.model_dump_json()


async def test_toss_requirements_fail_closed_on_malformed_templates() -> None:
    class FakeClient:
        credentials = TossShoppingCredentials("synthetic-access", "synthetic-secret")

        async def get_category_constraint_templates(
            self, category_id: int
        ) -> dict[str, Any]:
            return {"other": []}

    adapter = TossShoppingAdapter(FakeClient(), clock=FIXED_CLOCK)
    with pytest.raises(AdapterInvalidResponseError):
        await adapter.get_marketplace_category_requirements(category_id="55")
    with pytest.raises(AdapterInvalidRequestError):
        await adapter.get_marketplace_category_requirements(category_id="0")


async def test_toss_resources_project_only_safe_selector_fields() -> None:
    class FakeClient:
        credentials = TossShoppingCredentials("synthetic-access", "synthetic-secret")

        async def list_delivery_locations_v2(self) -> tuple[dict[str, Any], ...]:
            return (
                {
                    "id": 111,
                    "locationName": "기본 출고지",
                    "isDefault": True,
                    "address": "서울특별시 송파구 송파대로 570",
                    "addressDetail": "3층",
                    "zipCode": "05555",
                    "telNo": "02-1234-5678",
                    "recipientName": "노출금지",
                },
            )

        async def list_exchange_refund_locations_v2(self) -> tuple[dict[str, Any], ...]:
            return (
                {
                    "id": 222,
                    "name": "반품지",
                    "isDefault": False,
                },
            )

    adapter = TossShoppingAdapter(FakeClient(), clock=FIXED_CLOCK)
    items = await adapter.get_marketplace_registration_resources()

    assert [item.resource_id for item in items] == ["111", "222"]
    assert items[0].resource_type == "delivery_location"
    assert items[0].is_default is True
    assert items[1].resource_type == "exchange_refund_location"
    serialized = json.dumps(
        [item.model_dump(mode="json") for item in items], ensure_ascii=True
    )
    for fragment in (
        "서울특별시",
        "송파대로",
        "05555",
        "02-1234-5678",
        "노출금지",
        "3층",
    ):
        assert fragment not in serialized


# ---------------------------------------------------------------------------
# Service dispatch, envelopes, and Agent-safety
# ---------------------------------------------------------------------------


def _naver_service() -> CommerceService:
    class FakeClient:
        credentials = NaverCredentials("client-id", "synthetic-secret")

        async def list_categories(self) -> tuple[dict[str, Any], ...]:
            return _naver_category_rows()

        async def get_standard_options(self, *, category_id: int) -> dict[str, Any]:
            return {"useStandardOption": True, "standardOptionCategoryGroups": []}

        async def list_delivery_bundle_groups(self, **kwargs: Any) -> NaverPage:
            return NaverPage(
                rows=({"id": 12, "name": "기본 묶음", "isDefault": True},),
                next_cursor=None,
            )

        async def list_seller_addressbooks(self, *, page: int = 1) -> NaverPage:
            assert page == 1
            return NaverPage(rows=(), next_cursor=None)

    return CommerceService(AdapterRegistry([NaverAdapter(FakeClient(), clock=FIXED_CLOCK)]))


async def test_service_returns_structured_categories_requirements_and_resources() -> None:
    service = _naver_service()

    categories = await service.get_marketplace_categories(Channel.NAVER)
    requirements = await service.get_marketplace_category_requirements(
        Channel.NAVER, category_id="50000000"
    )
    resources = await service.get_marketplace_registration_resources(Channel.NAVER)

    assert categories.status is ResultStatus.COMPLETE
    assert len(categories.items) == 2
    assert requirements.status is ResultStatus.COMPLETE
    assert requirements.item is not None
    assert resources.status is ResultStatus.COMPLETE
    assert resources.items[0].resource_type == "delivery_bundle_group"


async def test_service_marks_unsupported_and_invalid_channels() -> None:
    from k12_commerce_mcp.adapters.mock import MockAdapter

    service = CommerceService(AdapterRegistry([MockAdapter()]))

    categories = await service.get_marketplace_categories(Channel.MOCK)
    requirements = await service.get_marketplace_category_requirements(
        Channel.MOCK, category_id="1"
    )
    resources = await service.get_marketplace_registration_resources(Channel.MOCK)

    for result in (categories, requirements, resources):
        assert result.status is ResultStatus.UNSUPPORTED
        assert result.errors[0].code.value == "adapter_not_configured"
    missing = CommerceService(AdapterRegistry())
    result = await missing.get_marketplace_categories(Channel.NAVER)
    assert result.status is ResultStatus.UNSUPPORTED


async def test_service_fails_closed_on_agent_unsafe_resource_label() -> None:
    class UnsafeClient:
        credentials = TossShoppingCredentials("synthetic-access", "synthetic-secret")

        async def list_delivery_locations_v2(self) -> tuple[dict[str, Any], ...]:
            return (
                {
                    "id": 1,
                    "locationName": "서울특별시 송파구 송파대로 570",
                },
            )

        async def list_exchange_refund_locations_v2(self) -> tuple[dict[str, Any], ...]:
            return ()

    service = CommerceService(
        AdapterRegistry([TossShoppingAdapter(UnsafeClient(), clock=FIXED_CLOCK)])
    )
    result = await service.get_marketplace_registration_resources(Channel.TOSS_STORE)

    assert result.status is ResultStatus.UNAVAILABLE
    assert result.errors[0].code.value == "invalid_adapter_response"
    assert result.items == ()
    assert "서울특별시" not in result.model_dump_json()


async def test_service_normalizes_adapter_failures_without_provider_text() -> None:
    class FailingClient:
        credentials = NaverCredentials("client-id", "synthetic-secret")

        async def list_categories(self) -> tuple[dict[str, Any], ...]:
            raise NaverProviderError("upstream body must not propagate")

    service = CommerceService(
        AdapterRegistry([NaverAdapter(FailingClient(), clock=FIXED_CLOCK)])
    )
    result = await service.get_marketplace_categories(Channel.NAVER)

    assert result.status is ResultStatus.UNAVAILABLE
    assert result.errors[0].code.value == "internal_error"
    assert "must not propagate" not in result.model_dump_json()


def test_registration_result_schemas_are_agent_safe() -> None:
    for model in (
        MarketplaceCategoryResult,
        MarketplaceCategoryRequirementResult,
        MarketplaceRegistrationResourceResult,
    ):
        assert_agent_safe_schema(model)


# ---------------------------------------------------------------------------
# Server tool registration
# ---------------------------------------------------------------------------


async def test_marketplace_reference_tools_are_registered_read_only() -> None:
    async with Client(build_server()) as client:
        listed = await client.list_tools()

    by_name = {tool.name: tool for tool in listed.tools}
    for name in (
        "commerce_get_marketplace_categories",
        "commerce_get_marketplace_category_requirements",
        "commerce_get_marketplace_registration_resources",
    ):
        tool = by_name[name]
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.destructive_hint is False
        channel_schema = tool.input_schema["properties"]["channel"]
        assert channel_schema.get("enum") == ["naver", "toss_store"]


async def test_marketplace_reference_tools_reject_other_channels() -> None:
    async with Client(build_server()) as client:
        for name, arguments in (
            ("commerce_get_marketplace_categories", {"channel": "coupang"}),
            (
                "commerce_get_marketplace_category_requirements",
                {"channel": "mock", "category_id": "1"},
            ),
            ("commerce_get_marketplace_registration_resources", {"channel": "elevenst"}),
        ):
            result = await client.call_tool(name, arguments)
            assert result.is_error is True


async def test_marketplace_reference_tools_end_to_end() -> None:
    service = _naver_service()

    async with Client(
        build_server(service, enforce_mock_scope=False)
    ) as client:
        categories = await client.call_tool(
            "commerce_get_marketplace_categories", {"channel": "naver"}
        )
        requirements = await client.call_tool(
            "commerce_get_marketplace_category_requirements",
            {"channel": "naver", "category_id": "50000000"},
        )
        resources = await client.call_tool(
            "commerce_get_marketplace_registration_resources", {"channel": "naver"}
        )

    assert categories.is_error is False
    assert categories.structured_content["status"] == "complete"
    assert categories.structured_content["items"][0]["category_id"] == "50000000"
    assert requirements.is_error is False
    assert requirements.structured_content["status"] == "complete"
    assert resources.is_error is False
    assert resources.structured_content["items"][0]["resource_id"] == "12"


async def test_capabilities_report_reference_reads_as_get() -> None:
    service = _naver_service()

    async with Client(
        build_server(service, enforce_mock_scope=False)
    ) as client:
        result = await client.call_tool(
            "commerce_get_capabilities", {"channel": "naver"}
        )

    rows = {
        row["tool_name"]: row
        for row in result.structured_content["capabilities"]
    }
    for name in (
        "commerce_get_marketplace_categories",
        "commerce_get_marketplace_category_requirements",
        "commerce_get_marketplace_registration_resources",
    ):
        assert rows[name]["implementation_status"] == "active"
        assert rows[name]["provider_method"] == "GET"
        assert rows[name]["permission"] == "read"
