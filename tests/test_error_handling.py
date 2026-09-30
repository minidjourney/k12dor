import pytest
from mcp import Client

from k12_commerce_mcp.adapters.base import (
    AdapterAuthenticationError,
    AdapterFailure,
    AdapterRateLimitError,
    AdapterTimeoutError,
    AdapterUnsupportedError,
)
from k12_commerce_mcp.adapters.mock import MockAdapter, MockPage
from k12_commerce_mcp.adapters.naver import NaverAdapter
from k12_commerce_mcp.clients.naver import NaverCredentials, NaverRequestError
from k12_commerce_mcp.models import Channel
from k12_commerce_mcp.registry import AdapterRegistry
from k12_commerce_mcp.server import build_server
from k12_commerce_mcp.service import CommerceService
from k12_commerce_mcp.synthetic import build_synthetic_adapter


async def test_deferred_channel_returns_structured_unsupported_result() -> None:
    async with Client(build_server()) as client:
        result = await client.call_tool("commerce_get_orders", {"channel": "coupang"})

    assert result.is_error is False
    assert result.structured_content["status"] == "unsupported"
    assert result.structured_content["items"] == []
    assert result.structured_content["errors"][0]["code"] == "adapter_not_configured"


@pytest.mark.parametrize(
    ("tool_name", "arguments", "result_field"),
    [
        (
            "commerce_get_order_detail",
            {"channel": "coupang", "order_ref": "synthetic-order"},
            "item",
        ),
        ("commerce_get_products", {"channel": "coupang"}, "items"),
        ("commerce_get_inventory", {"channel": "coupang"}, "items"),
        ("commerce_get_returns", {"channel": "coupang"}, "items"),
        ("commerce_get_settlements", {"channel": "coupang"}, "items"),
    ],
)
async def test_all_deferred_data_tools_return_structured_unsupported(
    tool_name: str,
    arguments: dict[str, object],
    result_field: str,
) -> None:
    async with Client(build_server()) as client:
        result = await client.call_tool(tool_name, arguments)

    assert result.is_error is False
    assert result.structured_content["status"] == "unsupported"
    assert result.structured_content[result_field] in (None, [])
    assert result.structured_content["errors"][0]["code"] == "adapter_not_configured"


@pytest.mark.parametrize(
    ("failure", "code", "retryable"),
    [
        (AdapterAuthenticationError(), "authentication_failed", False),
        (AdapterTimeoutError(), "timeout", True),
        (AdapterRateLimitError(), "rate_limited", True),
    ],
)
async def test_adapter_failures_return_safe_structured_errors(
    failure: Exception,
    code: str,
    retryable: bool,
) -> None:
    service = CommerceService(
        AdapterRegistry([MockAdapter(failures={"get_orders": failure})])
    )
    async with Client(build_server(service)) as client:
        result = await client.call_tool("commerce_get_orders", {"channel": "mock"})

    assert result.is_error is False
    assert result.structured_content["status"] == "unavailable"
    assert result.structured_content["items"] == []
    assert result.structured_content["errors"] == [
        {
            "code": code,
            "message": code.replace("_", " "),
            "retryable": retryable,
            "provider_status": None,
            "source_endpoint": None,
        }
    ]
    assert "secret" not in str(result.structured_content).lower()


async def test_invalid_cursor_is_a_structured_safe_error() -> None:
    service = CommerceService(AdapterRegistry([MockAdapter()]))

    async with Client(build_server(service)) as client:
        result = await client.call_tool(
            "commerce_get_orders",
            {"channel": "mock", "cursor": "not-a-cursor"},
        )

    assert result.is_error is False
    assert result.structured_content["status"] == "unavailable"
    assert result.structured_content["errors"][0] == {
        "code": "invalid_cursor",
        "message": "invalid cursor",
        "retryable": False,
        "provider_status": None,
        "source_endpoint": None,
    }


async def test_naver_malformed_cursor_is_not_reported_as_internal_error() -> None:
    class FakeClient:
        credentials = NaverCredentials("client-id", "synthetic-secret")

        async def list_product_orders(self, **kwargs: object):
            raise NaverRequestError("invalid Naver cursor")

    service = CommerceService(AdapterRegistry([NaverAdapter(FakeClient())]))

    result = await service.get_orders(Channel.NAVER, page_size=1, cursor="malformed")

    assert result.status.value == "unavailable"
    assert result.errors[0].code.value == "invalid_cursor"


async def test_registered_deferred_operation_returns_unsupported_status() -> None:
    class DeferredAdapter(MockAdapter):
        async def get_products(
            self, *, page_size: int, cursor: str | None = None
        ) -> MockPage:
            raise AdapterUnsupportedError

    service = CommerceService(AdapterRegistry([DeferredAdapter()]))

    result = await service.get_products(Channel.MOCK, page_size=1)

    assert result.status.value == "unsupported"
    assert result.items == ()
    assert result.errors[0].code.value == "adapter_not_configured"


async def test_missing_order_detail_returns_structured_not_found() -> None:
    service = CommerceService(AdapterRegistry([MockAdapter()]))

    async with Client(build_server(service)) as client:
        result = await client.call_tool(
            "commerce_get_order_detail",
            {"channel": "mock", "order_ref": "missing-synthetic-order"},
        )

    assert result.is_error is False
    assert result.structured_content["status"] == "unavailable"
    assert result.structured_content["item"] is None
    assert result.structured_content["errors"][0] == {
        "code": "not_found",
        "message": "not found",
        "retryable": False,
        "provider_status": None,
        "source_endpoint": None,
    }


@pytest.mark.parametrize(
    ("operation", "tool_name", "arguments"),
    [
        ("get_orders", "commerce_get_orders", {"channel": "mock"}),
        (
            "get_order_detail",
            "commerce_get_order_detail",
            {"channel": "mock", "order_ref": "synthetic-order"},
        ),
        ("get_products", "commerce_get_products", {"channel": "mock"}),
        ("get_inventory", "commerce_get_inventory", {"channel": "mock"}),
        ("get_returns", "commerce_get_returns", {"channel": "mock"}),
        ("get_settlements", "commerce_get_settlements", {"channel": "mock"}),
    ],
)
async def test_all_adapter_methods_normalize_timeout(
    operation: str,
    tool_name: str,
    arguments: dict[str, object],
) -> None:
    service = CommerceService(
        AdapterRegistry([MockAdapter(failures={operation: AdapterTimeoutError()})])
    )
    async with Client(build_server(service)) as client:
        result = await client.call_tool(tool_name, arguments)

    assert result.is_error is False
    assert result.structured_content["status"] == "unavailable"
    assert result.structured_content["errors"][0]["code"] == "timeout"



async def test_unexpected_adapter_exception_is_sanitized_without_traceback() -> None:
    adapter = MockAdapter(
        failures={"get_orders": RuntimeError("synthetic-sensitive-marker")}
    )
    server = build_server(service=CommerceService(AdapterRegistry([adapter])))

    async with Client(server) as client:
        result = await client.call_tool(
            "commerce_get_orders",
            {"channel": "mock", "page_size": 10},
        )

    text = str(result.structured_content)
    assert result.is_error is False
    assert result.structured_content["errors"][0] == {
        "code": "internal_error",
        "message": "internal error",
        "retryable": False,
        "provider_status": None,
        "source_endpoint": None,
    }
    assert "synthetic-sensitive-marker" not in text
    assert "traceback" not in text.lower()


async def test_untyped_adapter_failure_is_sanitized_without_traceback() -> None:
    adapter = MockAdapter(
        failures={"get_orders": AdapterFailure("synthetic-provider-body-marker")}
    )
    server = build_server(service=CommerceService(AdapterRegistry([adapter])))

    async with Client(server) as client:
        result = await client.call_tool(
            "commerce_get_orders",
            {"channel": "mock", "page_size": 10},
        )

    text = str(result.structured_content)
    assert result.is_error is False
    assert result.structured_content["errors"][0]["code"] == "internal_error"
    assert "synthetic-provider-body-marker" not in text


class InvalidCursorAdapter(MockAdapter):
    async def get_orders(
        self, *, page_size: int, cursor: str | None = None
    ) -> MockPage:
        return MockPage(items=(), next_cursor="-1")


async def test_invalid_adapter_cursor_is_sanitized() -> None:
    server = build_server(
        service=CommerceService(AdapterRegistry([InvalidCursorAdapter()]))
    )

    async with Client(server) as client:
        result = await client.call_tool(
            "commerce_get_orders",
            {"channel": "mock", "page_size": 10},
        )

    assert result.is_error is False
    assert result.structured_content["status"] == "unavailable"
    assert result.structured_content["errors"][0]["code"] == "invalid_adapter_response"


class OverfullPageAdapter(MockAdapter):
    async def get_orders(
        self, *, page_size: int, cursor: str | None = None
    ) -> MockPage:
        seed = build_synthetic_adapter()
        page = await seed.get_orders(page_size=1)
        return MockPage(items=(page.items[0], page.items[0]), next_cursor=None)


@pytest.mark.parametrize("violation", ["cross_channel", "overfull"])
async def test_invalid_adapter_items_are_rejected(violation: str) -> None:
    if violation == "cross_channel":
        seed = build_synthetic_adapter()
        page = await seed.get_orders(page_size=1)
        wrong_channel = page.items[0].model_copy(update={"channel": Channel.COUPANG})
        adapter = MockAdapter(orders=(wrong_channel,))
    else:
        adapter = OverfullPageAdapter()
    server = build_server(service=CommerceService(AdapterRegistry([adapter])))

    async with Client(server) as client:
        result = await client.call_tool(
            "commerce_get_orders",
            {"channel": "mock", "page_size": 1},
        )

    assert result.is_error is False
    assert result.structured_content["errors"][0]["code"] == "invalid_adapter_response"


@pytest.mark.parametrize("page_size", [-1, 0, 101, True, 1.5, "1"])
async def test_direct_service_rejects_invalid_page_size(page_size: object) -> None:
    service = CommerceService(AdapterRegistry([build_synthetic_adapter()]))

    result = await service.get_orders(Channel.MOCK, page_size=page_size)

    assert result.status.value == "unavailable"
    assert result.errors[0].code.value == "invalid_request"


@pytest.mark.parametrize("page_size", [-1, 0, 101, True, 1.5, "1"])
async def test_mock_adapter_rejects_invalid_page_size(page_size: object) -> None:
    adapter = build_synthetic_adapter()

    with pytest.raises(ValueError, match="page_size"):
        await adapter.get_orders(page_size=page_size)
