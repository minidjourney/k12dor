"""Toss read-only registration-policy projection tests.

All external calls use httpx.MockTransport; no live API is used.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

import httpx

from k12_commerce_mcp.adapters.toss import TossShoppingAdapter
from k12_commerce_mcp.clients.toss import TossShoppingClient, TossShoppingCredentials

TOKEN_RESPONSE = httpx.Response(
    200,
    json={
        "access_token": "synthetic-token",
        "expires_in": 3600,
        "scope": "toss-shopping-fep:write",
        "token_type": "Bearer",
    },
)

PRODUCT = {
    "id": 301,
    "name": "관측 상품",
    "brandName": "관측브랜드",
    "categoryName": "관측카테고리",
    "exposureStatus": "EXPOSURE",
    "exposure": {"serialNumber": "MODEL-1"},
    "stocks": [{"itemId": 77}],
    "deliveryPolicy": {
        "deliveryMethod": "NORMAL",
        "deliveryFeeType": "CONDITIONALLY_FREE",
        "deliveryFee": 1500,
        "minimumPurchasePrice": 20000,
        "isJejuAndIslandsMountainsDelivery": True,
        "jejuDeliveryFee": 3000,
        "islandsMountainsDeliveryFee": 3000,
        "deliveryLocationId": 111,
        "deliveryType": "PARCEL",
        "deliveryDeadline": "18:00",
        "preparationDays": 2,
        "deliveryCompanyId": 7,
        "providerOnlyEnvelopeText": "must not propagate",
    },
    "exchangeReturnPolicy": {
        "exchangeRefundLocationId": 222,
        "refundOneWayDeliveryFee": 1500,
        "exchangeRoundTripDeliveryFee": 3000,
        "applicationMethodDescription": "고객센터 연락 후 교환/반품 신청",
        "applicationTermDescription": "상품 수령 후 7일 이내",
        "providerOnlyEnvelopeText": "must not propagate",
    },
    "providerOnlyEnvelopeText": "must not propagate",
}


def _adapter(product: dict[str, Any], *, items_unavailable: bool = False) -> TossShoppingAdapter:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth2.cert.toss.im":
            return TOKEN_RESPONSE
        if request.url.path.endswith("/products/301/v2"):
            return httpx.Response(
                200,
                json={"resultType": "SUCCESS", "success": product},
            )
        if request.url.path.endswith("/products/301/product-items"):
            if items_unavailable:
                return httpx.Response(503, json={"resultType": "FAIL"})
            return httpx.Response(
                200,
                json={
                    "resultType": "SUCCESS",
                    "success": {"items": [{"itemId": 77}], "nextCursor": None},
                },
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    client = TossShoppingClient(
        TossShoppingCredentials("synthetic-access", "synthetic-secret"),
        transport=httpx.MockTransport(handler),
    )
    return TossShoppingAdapter(
        client,
        clock=lambda: datetime(2026, 9, 14, 1, 0, tzinfo=UTC),
    )


async def test_toss_detail_projects_known_policy_fields_to_typed_template() -> None:
    detail = await _adapter(deepcopy(PRODUCT)).get_product_detail("301")

    assert detail is not None
    assert detail.name == "관측 상품"
    assert detail.registration_template is not None
    assert detail.registration_template.delivery_policy.delivery_method == "NORMAL"
    assert detail.registration_template.delivery_policy.delivery_fee == 1500
    assert detail.registration_template.delivery_policy.delivery_location_id == 111
    assert detail.registration_template.exchange_return_policy.exchange_refund_location_id == 222
    serialized = detail.registration_template.model_dump(mode="json")
    assert serialized["delivery_policy"]["minimum_purchase_price"] == 20000
    assert "providerOnlyEnvelopeText" not in str(serialized)
    assert "provider_only_envelope_text" not in str(serialized)


async def test_toss_detail_with_missing_required_policy_field_keeps_detail_without_guessing(
) -> None:
    product = deepcopy(PRODUCT)
    del product["deliveryPolicy"]["deliveryFee"]

    detail = await _adapter(product).get_product_detail("301")

    assert detail is not None
    assert detail.name == "관측 상품"
    assert detail.registration_template is None


async def test_toss_detail_rejects_pii_policy_text_without_dropping_detail() -> None:
    product = deepcopy(PRODUCT)
    product["exchangeReturnPolicy"]["applicationMethodDescription"] = (
        "문의: operator@example.com"
    )

    detail = await _adapter(product).get_product_detail("301")

    assert detail is not None
    assert detail.name == "관측 상품"
    assert detail.registration_template is None

async def test_toss_detail_keeps_product_policy_when_optional_item_read_fails() -> None:
    detail = await _adapter(deepcopy(PRODUCT), items_unavailable=True).get_product_detail("301")
    assert detail is not None
    assert detail.name == "관측 상품"
    assert detail.registration_template is not None
    assert detail.external_option_ids == ("77",)

async def test_toss_detail_exposes_only_typed_missing_fields_for_operator_review() -> None:
    product = deepcopy(PRODUCT)
    product["deliveryPolicy"]["deliveryDeadline"] = "invalid time"
    product["exchangeReturnPolicy"]["applicationMethodDescription"] = ""
    detail = await _adapter(product).get_product_detail("301")
    assert detail is not None
    assert detail.registration_template is None
    candidate = detail.registration_template_candidate
    assert candidate is not None
    assert set(candidate.missing_fields) == {
        "delivery_policy.delivery_deadline",
        "exchange_return_policy.application_method_description",
    }
    assert candidate.delivery_policy.delivery_deadline is None
    assert candidate.exchange_return_policy.application_method_description is None
    assert candidate.delivery_policy.delivery_fee == 1500
    assert "invalid time" not in str(candidate.model_dump(mode="json"))

async def test_toss_unsafe_policy_text_has_no_candidate() -> None:
    product = deepcopy(PRODUCT)
    product["exchangeReturnPolicy"]["applicationMethodDescription"] = "operator@example.com"
    detail = await _adapter(product).get_product_detail("301")
    assert detail is not None
    assert detail.registration_template_candidate is None
