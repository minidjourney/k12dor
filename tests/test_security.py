import pytest
from mcp import Client
from pydantic import BaseModel

from k12_commerce_mcp.adapters.mock import MockAdapter
from k12_commerce_mcp.models import Order
from k12_commerce_mcp.registry import AdapterRegistry
from k12_commerce_mcp.security import (
    PiiSchemaError,
    PiiValueError,
    assert_agent_safe_schema,
    assert_agent_safe_value,
)
from k12_commerce_mcp.server import build_server
from k12_commerce_mcp.service import CommerceService
from k12_commerce_mcp.synthetic import build_synthetic_adapter


class UnsafeCustomerModel(BaseModel):
    customer_name: str



def test_order_schema_contains_no_forbidden_pii_fields() -> None:
    assert_agent_safe_schema(Order)


def test_schema_guard_rejects_pii_field_names() -> None:
    with pytest.raises(PiiSchemaError, match="customer_name"):
        assert_agent_safe_schema(UnsafeCustomerModel)


def test_server_startup_rejects_unsafe_output_model() -> None:
    with pytest.raises(PiiSchemaError, match="customer_name"):
        build_server(agent_visible_models=(UnsafeCustomerModel,))


@pytest.mark.parametrize(
    "unsafe",
    [
        "synthetic.person@example.invalid",
        "010-1234-5678",
        "02-1234-5678",
        "031-123-4567",
        "서울특별시 강남구 테헤란로 123",
        "서울 강남구 테헤란로 123",
        "서울시 강남구 테헤란로 123",
        "경기 성남시 분당구 판교역로 166",
        "강남구 테헤란로 123",
        "서울 강남구 테헤란로123",
        "Bearer synthetic-token-marker",
        '{"buyer":"synthetic"}',
        'prefix {"buyer":"synthetic"} suffix',
    ],
)
def test_runtime_value_gate_rejects_pii_secret_and_raw_json(unsafe: str) -> None:
    with pytest.raises(PiiValueError):
        assert_agent_safe_value({"safe_field": unsafe})


@pytest.mark.parametrize(
    "unsafe_key",
    ["raw_payload", "authorization", "access_token", "refresh_token", "cookie"],
)
def test_runtime_value_gate_rejects_sensitive_keys(unsafe_key: str) -> None:
    with pytest.raises(PiiValueError):
        assert_agent_safe_value({unsafe_key: "synthetic"})


async def test_mcp_rejects_unsafe_adapter_value_without_echoing_it() -> None:
    seed = build_synthetic_adapter()
    page = await seed.get_products(page_size=1)
    unsafe_product = page.items[0].model_copy(
        update={"name": "synthetic.person@example.invalid"}
    )
    service = CommerceService(
        AdapterRegistry([MockAdapter(products=(unsafe_product,))])
    )

    async with Client(build_server(service)) as client:
        result = await client.call_tool(
            "commerce_get_products",
            {"channel": "mock", "page_size": 1},
        )

    text = str(result.structured_content)
    assert result.is_error is False
    assert result.structured_content["errors"][0]["code"] == "invalid_adapter_response"
    assert "synthetic.person" not in text
