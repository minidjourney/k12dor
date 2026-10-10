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


@pytest.mark.parametrize(
    "catalog",
    [
        {"external_option_ids": ["1712345678", "1012345678"]},
        {"external_option_id": "1612345678"},
        {"external_product_id": "1912345678"},
        {"external_option_ids": [1712345678]},
    ],
)
def test_runtime_value_gate_allows_phone_shaped_catalog_ids(catalog: dict) -> None:
    # 몰 상품·옵션 번호는 판매자 카탈로그 번호다.
    # 10자리가 휴대폰 모양이어도 상품 읽기를 막지 않는다.
    assert_agent_safe_value(catalog)


@pytest.mark.parametrize(
    "unsafe",
    [
        {"external_option_ids": ["010-1234-5678"]},
        {"external_option_ids": ["1712345678 synthetic.person@example.invalid"]},
        {"external_option_id": "+82 10 1234 5678"},
        {"name": "1712345678"},
        {"option_name": "1012345678"},
        {"external_option_ids": [["1712345678"]]},
    ],
)
def test_runtime_value_gate_catalog_exemption_is_exact(unsafe: dict) -> None:
    # 예외는 정해진 칸 이름 + 숫자만 1~20자일 때뿐 — 다른 칸·다른 모양은 그대로 막는다.
    with pytest.raises(PiiValueError):
        assert_agent_safe_value(unsafe)


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
