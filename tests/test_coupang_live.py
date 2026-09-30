import re
from datetime import date, datetime
from pathlib import Path

import httpx
import pytest

from k12_commerce_mcp.adapters.base import AdapterAuthenticationError, AdapterRateLimitError
from k12_commerce_mcp.adapters.coupang import CoupangAdapter
from k12_commerce_mcp.clients.coupang import (
    CoupangClient,
    CoupangCredentials,
    CoupangPage,
    CoupangRequestError,
)
from k12_commerce_mcp.credentials import CredentialFileError, load_marketplace_credentials
from k12_commerce_mcp.models import Channel, ClaimState, Fulfillment, ResultStatus


def response(body: dict[str, object], status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=body)


def test_credential_loader_requires_private_regular_file_and_never_repr_exposes_values(
    tmp_path: Path,
) -> None:
    path = tmp_path / "marketplace-readonly.env"
    path.write_text(
        "DOR_COUPANG_VENDOR_ID=vendor-fixture\n"
        "DOR_COUPANG_ACCESS_KEY=access-fixture\n"
        "DOR_COUPANG_SECRET_KEY=secret-fixture\n",
        encoding="utf-8",
    )
    path.chmod(0o600)

    credentials = load_marketplace_credentials(path)

    assert credentials.coupang is not None
    assert credentials.coupang.vendor_id == "vendor-fixture"
    assert "access-fixture" not in repr(credentials)
    assert "secret-fixture" not in repr(credentials)

    path.chmod(0o644)
    with pytest.raises(CredentialFileError, match="permissions"):
        load_marketplace_credentials(path)


async def test_coupang_client_uses_only_get_signed_ordersheet_request() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return response({"code": 200, "data": [], "nextToken": None})

    client = CoupangClient(
        CoupangCredentials("vendor-fixture", "access-fixture", "secret-fixture"),
        transport=httpx.MockTransport(handler),
        clock=lambda: datetime.fromisoformat("2026-09-14T00:00:00+00:00"),
    )

    result = await client.list_order_sheets(
        business_date=date(2026, 9, 13),
        status="ACCEPT",
        page_size=50,
    )

    assert result.rows == ()
    assert len(seen) == 1
    request = seen[0]
    assert request.method == "GET"
    assert request.content == b""
    assert request.url.path.endswith("/vendors/vendor-fixture/ordersheets")
    assert request.url.params["createdAtFrom"] == "2026-09-13+09:00"
    assert request.url.params["createdAtTo"] == "2026-09-13+09:00"
    assert request.url.params["status"] == "ACCEPT"
    authorization = request.headers["Authorization"]
    assert authorization.startswith("CEA algorithm=HmacSHA256, access-key=access-fixture")
    assert "secret-fixture" not in authorization


@pytest.mark.parametrize(
    ("status", "error_type"),
    [
        (401, AdapterAuthenticationError),
        (403, AdapterAuthenticationError),
        (429, AdapterRateLimitError),
    ],
)
async def test_coupang_client_maps_http_errors_without_provider_body(
    status: int, error_type: type[Exception]
) -> None:
    transport = httpx.MockTransport(
        lambda request: response({"message": "secret provider body must not escape"}, status=status)
    )
    client = CoupangClient(
        CoupangCredentials("vendor", "access", "secret"),
        transport=transport,
    )

    with pytest.raises(error_type) as caught:
        await client.list_order_sheets(
            business_date=date(2026, 9, 13),
            status="ACCEPT",
            page_size=1,
        )

    assert "provider body" not in str(caught.value)
    assert "secret" not in str(caught.value)


async def test_coupang_adapter_maps_one_page_without_pii_or_raw_order_ids() -> None:
    calls: list[dict[str, object]] = []

    class FakeClient:
        credentials = CoupangCredentials("vendor", "access", "secret")

        async def list_order_sheets(self, **kwargs: object):
            calls.append(kwargs)
            return type(
                "Page",
                (),
                {
                    "rows": (
                        (
                            {
                                "orderId": 990000001,
                                "orderedAt": "2026-09-13T10:00:00+09:00",
                                "paidAt": "2026-09-13T10:00:00+09:00",
                                "status": "ACCEPT",
                                "shipmentType": "THIRD_PARTY",
                                "orderer": {"name": "홍길동", "safeNumber": "+82-10-0000-0000"},
                                "receiver": {"name": "홍길동", "addr1": "서울시 어딘가"},
                                "orderItems": [
                                    {
                                        "vendorItemId": 77770001,
                                        "shippingCount": 2,
                                        "salesPrice": {
                                            "currencyCode": "KRW",
                                            "units": 12000,
                                            "nanos": 0,
                                        },
                                        "orderPrice": {
                                            "currencyCode": "KRW",
                                            "units": 24000,
                                            "nanos": 0,
                                        },
                                        "discountPrice": {
                                            "currencyCode": "KRW",
                                            "units": 0,
                                            "nanos": 0,
                                        },
                                    }
                                ],
                            },
                        )
                        if kwargs.get("status") == "ACCEPT"
                        else ()
                    ),
                    "next_token": None,
                },
            )()

    adapter = CoupangAdapter(
        FakeClient(),
        clock=lambda: datetime.fromisoformat("2026-09-14T00:00:00+00:00"),
    )

    page = await adapter.get_orders(page_size=50, business_date=date(2026, 9, 13))

    assert calls[0]["status"] == "ACCEPT"
    assert page.next_cursor is None
    assert len(page.items) == 1
    order = page.items[0]
    assert order.channel is Channel.COUPANG
    assert order.fulfillment is Fulfillment.SELLER_SHIPPED
    assert re.fullmatch(r"coupang-order-hmac-v1:[0-9a-f]{64}", order.order_ref)
    assert "990000001" not in order.model_dump_json()
    assert "홍길동" not in order.model_dump_json()
    assert "서울시" not in order.model_dump_json()
    assert order.lines[0].external_option_id == "77770001"
    assert order.lines[0].quantity == 2
    assert str(order.lines[0].unit_price.amount) == "12000"
    assert str(order.ordered_amount.amount) == "24000"
    assert order.customer_paid_amount is None
    assert order.recognized_revenue is None
    assert order.completeness.status is ResultStatus.INCOMPLETE


async def test_coupang_adapter_maps_ordersheet_shipping_price_to_customer_shipping() -> None:
    def row(order_id: int, shipping_price: object) -> dict[str, object]:
        base: dict[str, object] = {
            "orderId": order_id,
            "orderedAt": "2026-09-13T10:00:00+09:00",
            "paidAt": "2026-09-13T10:00:00+09:00",
            "shipmentType": "THIRD_PARTY",
            "orderItems": [
                {
                    "vendorItemId": order_id + 1,
                    "shippingCount": 1,
                    "salesPrice": {
                        "currencyCode": "KRW",
                        "units": 10000,
                        "nanos": 0,
                    },
                    "orderPrice": {
                        "currencyCode": "KRW",
                        "units": 10000,
                        "nanos": 0,
                    },
                }
            ],
        }
        if shipping_price is not ...:
            base["shippingPrice"] = shipping_price
        return base

    class FakeClient:
        credentials = CoupangCredentials("vendor", "access", "secret")

        async def list_order_sheets(self, **kwargs: object):
            rows: tuple[dict[str, object], ...] = ()
            if kwargs.get("status") == "ACCEPT":
                rows = (
                    row(
                        990000011,
                        {"currencyCode": "KRW", "units": 2500, "nanos": 0},
                    ),
                    row(
                        990000012,
                        {"currencyCode": "KRW", "units": 0, "nanos": 0},
                    ),
                    row(990000013, ...),
                )
            return type("Page", (), {"rows": rows, "next_token": None})()

    adapter = CoupangAdapter(
        FakeClient(),
        clock=lambda: datetime.fromisoformat("2026-09-14T00:00:00+00:00"),
    )

    page = await adapter.get_orders(page_size=10, business_date=date(2026, 9, 13))

    shipped, free, absent = page.items
    assert shipped.customer_shipping_amount is not None
    assert str(shipped.customer_shipping_amount.amount) == "2500"
    assert shipped.customer_shipping_amount.currency == "KRW"
    assert str(shipped.ordered_amount.amount) == "10000"
    assert str(shipped.lines[0].line_amount.amount) == "10000"
    assert shipped.customer_paid_amount is None
    assert free.customer_shipping_amount is not None
    assert str(free.customer_shipping_amount.amount) == "0"
    assert absent.customer_shipping_amount is None


async def test_coupang_adapter_maps_line_listing_names_without_fabrication() -> None:
    def item(vendor_item_id: int, **extra: object) -> dict[str, object]:
        row: dict[str, object] = {
            "vendorItemId": vendor_item_id,
            "shippingCount": 1,
            "salesPrice": {"currencyCode": "KRW", "units": 1000, "nanos": 0},
            "orderPrice": {"currencyCode": "KRW", "units": 1000, "nanos": 0},
        }
        row.update(extra)
        return row

    class FakeClient:
        credentials = CoupangCredentials("vendor", "access", "secret")

        async def list_order_sheets(self, **kwargs: object):
            rows: tuple[dict[str, object], ...] = ()
            if kwargs.get("status") == "ACCEPT":
                rows = (
                    {
                        "orderId": 990000002,
                        "orderedAt": "2026-09-13T10:00:00+09:00",
                        "paidAt": "2026-09-13T10:00:00+09:00",
                        "shipmentType": "THIRD_PARTY",
                        "orderer": {"name": "홍길동"},
                        "orderItems": [
                            item(
                                1,
                                vendorItemName="관측 상품 블랙/L",
                                sellerProductName="관측 상품",
                            ),
                            item(2, vendorItemName="관측 단품"),
                            item(3, vendorItemName="   ", sellerProductName=" 관측 상품2 "),
                            item(4),
                            item(
                                5,
                                vendorItemName="같은 이름",
                                sellerProductName="같은 이름",
                            ),
                        ],
                    },
                )
            return type("Page", (), {"rows": rows, "next_token": None})()

    adapter = CoupangAdapter(
        FakeClient(),
        clock=lambda: datetime.fromisoformat("2026-09-14T00:00:00+00:00"),
    )

    page = await adapter.get_orders(page_size=50, business_date=date(2026, 9, 13))

    assert len(page.items) == 1
    lines = page.items[0].lines
    assert len(lines) == 5
    assert [(line.product_name, line.option_name) for line in lines] == [
        ("관측 상품", "관측 상품 블랙/L"),
        ("관측 단품", None),
        ("관측 상품2", None),
        (None, None),
        ("같은 이름", None),
    ]
    serialized = page.items[0].model_dump_json()
    assert "홍길동" not in serialized
    assert "990000002" not in serialized


async def test_coupang_adapter_withholds_ambiguous_discounted_order_amount() -> None:
    class FakeClient:
        credentials = CoupangCredentials("vendor", "access", "secret")

        async def list_order_sheets(self, **kwargs: object):
            return type(
                "Page",
                (),
                {
                    "rows": (
                        {
                            "orderId": 1,
                            "orderedAt": "2026-09-13T10:00:00+09:00",
                            "paidAt": "2026-09-13T10:00:00+09:00",
                            "shipmentType": "THIRD_PARTY",
                            "orderItems": [
                                {
                                    "vendorItemId": 2,
                                    "shippingCount": 1,
                                    "salesPrice": {
                                        "currencyCode": "KRW",
                                        "units": 1000,
                                        "nanos": 0,
                                    },
                                    "orderPrice": {
                                        "currencyCode": "KRW",
                                        "units": 1000,
                                        "nanos": 0,
                                    },
                                    "discountPrice": {
                                        "currencyCode": "KRW",
                                        "units": 100,
                                        "nanos": 0,
                                    },
                                }
                            ],
                        },
                    ),
                    "next_token": None,
                },
            )()

    page = await CoupangAdapter(FakeClient()).get_orders(
        page_size=1,
        business_date=date(2026, 9, 13),
    )

    assert page.items[0].ordered_amount is None
    assert "discount_price_relation_undocumented" in page.items[0].completeness.reasons


async def test_coupang_expanded_get_mappers_are_canonical_and_pii_free() -> None:
    class FakeClient:
        credentials = CoupangCredentials("vendor", "access", "secret")

        async def list_seller_products(self, **kwargs: object) -> CoupangPage:
            return CoupangPage(
                rows=(
                    {
                        "sellerProductId": 301,
                        "sellerProductName": "관측 상품",
                        "statusName": "승인완료",
                    },
                ),
                next_token=None,
            )

        async def get_seller_product(self, seller_product_id: str):
            return {
                "sellerProductId": int(seller_product_id),
                "sellerProductName": "관측 상품",
                "statusName": "승인완료",
                "brand": "브랜드",
                "productGroup": "상품군",
                "generalProductName": "모델",
                "returnAddress": "서울시 비공개 주소",
                "companyContactNumber": "02-000-0000",
                "items": [
                    {
                        "vendorItemId": 401,
                        "attributes": [
                            {"attributeTypeName": "색상", "attributeValueName": "검정"}
                        ],
                        "images": [
                            {
                                "cdnPath": (
                                    "https://image.coupangcdn.com/image/vendor_inventory/main.jpg"
                                )
                            }
                        ],
                        "contents": [
                            {
                                "contentDetails": [
                                    {"detailType": "TEXT", "content": "<p>공식 상세 설명</p>"}
                                ]
                            }
                        ],
                    }
                ],
            }

        async def list_rg_inventory(self, **kwargs: object) -> CoupangPage:
            return CoupangPage(
                rows=(
                    {
                        "vendorItemId": 401,
                        "inventoryDetails": {"totalOrderableQuantity": 7},
                    },
                ),
                next_token=None,
            )

        async def list_settlements(self, year_month: str):
            return (
                {
                    "revenueRecognitionDateFrom": f"{year_month}-01",
                    "revenueRecognitionDateTo": f"{year_month}-07",
                    "totalSale": 10000,
                    "serviceFee": 1080,
                    "settlementAmount": 8920,
                    "bankAccount": "must-not-escape",
                },
            )

        async def list_revenue_history(self, **kwargs: object) -> CoupangPage:
            return CoupangPage(
                rows=(
                    {
                        "recognitionDate": "2026-09-13",
                        "items": [
                            {
                                "vendorItemId": 401,
                                "saleAmount": 10000,
                                "serviceFee": 1080,
                                "serviceFeeRatio": 10.8,
                            }
                        ],
                    },
                ),
                next_token=None,
            )

    adapter = CoupangAdapter(
        FakeClient(),
        clock=lambda: datetime.fromisoformat("2026-09-14T00:00:00+00:00"),
    )

    products = await adapter.get_products(page_size=10)
    detail = await adapter.get_product_detail("301")
    content = await adapter.get_product_content("301")
    inventory = await adapter.get_inventory(page_size=10)
    settlements = await adapter.get_settlements(page_size=10)
    fees = await adapter.get_fees(page_size=10)

    assert products.items[0].external_product_id == "301"
    assert detail is not None and detail.external_option_ids == ("401",)
    assert detail.attributes[0].value == "검정"
    assert content is not None and content.description_text == "공식 상세 설명"
    assert content.image_urls[0].startswith("https://image.coupangcdn.com/image/")
    assert inventory.items[0].quantity == 7
    assert inventory.items[0].inventory_source.value == "marketplace_fulfillment"
    assert str(settlements.items[0].service_fee.amount) == "1080"
    assert fees.items[0].provider_reported is True
    assert fees.items[0].policy_derived is False
    serialized = " ".join(
        (
            detail.model_dump_json(),
            content.model_dump_json(),
            settlements.items[0].model_dump_json(),
        )
    )
    assert "서울시" not in serialized
    assert "02-000-0000" not in serialized
    assert "bankAccount" not in serialized


async def test_coupang_return_client_uses_get_only_and_bounded_timeframe() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["path"] = request.url.path
        captured["query"] = request.url.query.decode()
        return httpx.Response(200, json={"data": [], "nextToken": None})

    client = CoupangClient(
        CoupangCredentials("vendor", "access", "secret"),
        transport=httpx.MockTransport(handler),
        clock=lambda: datetime.fromisoformat("2026-09-14T00:00:00+00:00"),
    )
    await client.list_return_requests(
        date_from=date(2026, 9, 13),
        date_to=date(2026, 9, 14),
        page_size=1,
    )

    assert captured["method"] == "GET"
    assert captured["path"].endswith("/vendors/vendor/returnRequests")
    assert "cancelType=RETURN" in captured["query"]
    assert "maxPerPage=1" in captured["query"]


async def test_coupang_return_client_sends_requested_cancel_type() -> None:
    captured: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request.url.query.decode())
        return httpx.Response(200, json={"data": [], "nextToken": None})

    client = CoupangClient(
        CoupangCredentials("vendor", "access", "secret"),
        transport=httpx.MockTransport(handler),
        clock=lambda: datetime.fromisoformat("2026-09-14T00:00:00+00:00"),
    )
    await client.list_return_requests(
        date_from=date(2026, 9, 13),
        date_to=date(2026, 9, 14),
        page_size=1,
        cancel_type="CANCEL",
    )
    await client.list_return_requests(
        date_from=date(2026, 9, 13),
        date_to=date(2026, 9, 14),
        page_size=1,
    )

    assert len(captured) == 2
    assert "cancelType=CANCEL" in captured[0]
    assert "cancelType=RETURN" in captured[1]


async def test_coupang_return_client_rejects_unknown_cancel_type_before_transport() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"data": [], "nextToken": None})

    client = CoupangClient(
        CoupangCredentials("vendor", "access", "secret"),
        transport=httpx.MockTransport(handler),
        clock=lambda: datetime.fromisoformat("2026-09-14T00:00:00+00:00"),
    )
    with pytest.raises(CoupangRequestError):
        await client.list_return_requests(
            date_from=date(2026, 9, 13),
            date_to=date(2026, 9, 14),
            page_size=1,
            cancel_type="EXCHANGE",
        )
    assert seen == []


async def test_coupang_get_returns_sweeps_return_then_cancel_types() -> None:
    cancel_types: list[str] = []

    class FakeClient:
        credentials = CoupangCredentials("vendor", "access", "secret")

        async def list_return_requests(
            self, cancel_type: str = "RETURN", **kwargs: object
        ) -> CoupangPage:
            cancel_types.append(cancel_type)
            return CoupangPage(rows=(), next_token=None)

    adapter = CoupangAdapter(
        FakeClient(),
        clock=lambda: datetime.fromisoformat("2026-09-14T00:00:00+00:00"),
    )
    cursor = None
    for _ in range(4):
        page = await adapter.get_returns(page_size=10, cursor=cursor)
        assert page.items == ()
        cursor = page.next_cursor

    assert cursor is None
    assert cancel_types == ["RETURN", "CANCEL"]


async def test_coupang_return_mapper_drops_requester_and_delivery_pii() -> None:
    class FakeClient:
        credentials = CoupangCredentials("vendor", "access", "secret")

        async def list_return_requests(self, **kwargs: object) -> CoupangPage:
            return CoupangPage(
                rows=(
                    {
                        "receiptId": 501,
                        "orderId": 601,
                        "receiptStatus": "RETURNS_UNCHECKED",
                        "createdAt": "2026-09-13T10:00:00+09:00",
                        "cancelCountSum": 2,
                        "requesterName": "노출금지",
                        "requesterPhoneNumber": "010-1234-5678",
                        "requesterAddress": "서울특별시 송파구 송파대로 570",
                        "returnDeliveryDtos": [{"deliveryInvoiceNo": "노출금지"}],
                    },
                ),
                next_token=None,
            )

    adapter = CoupangAdapter(
        FakeClient(),
        clock=lambda: datetime.fromisoformat("2026-09-14T00:00:00+00:00"),
    )
    page = await adapter.get_returns(page_size=1)

    assert len(page.items) == 1
    assert page.items[0].state is ClaimState.REQUESTED
    assert page.items[0].quantity == 2
    serialized = page.items[0].model_dump_json()
    assert "노출금지" not in serialized
    assert "010-1234-5678" not in serialized
    assert "서울특별시" not in serialized
