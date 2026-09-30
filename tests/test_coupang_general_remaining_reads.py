"""Coverage and injected dispatch for Coupang general reads still outside other modules.

No live provider call, credential, or shared client/server/permission edit.
Only GETs whose official contract, required input, and safe projection match an
existing client method are dispatched. Everything else is classified and blocked.
"""

from __future__ import annotations

import ast
import re
from datetime import date
from pathlib import Path

import pytest

from k12_commerce_mcp.adapters.coupang.general_extended import list_unconnected_reads
from k12_commerce_mcp.adapters.coupang.general_missing_reads import list_missing_reads
from k12_commerce_mcp.clients.coupang import ALLOWED_GET_PATH_TEMPLATES
from k12_commerce_mcp.security import assert_agent_safe_value

_SNAPSHOT = Path("/data/documents/second-brain/raw/documents/marketplace-api-docs-20260916/coupang")
_BADGE = re.compile(
    r'<span class="badge method-([a-z]+)[^"]*"[^>]*>\s*([A-Z]+)\s*</span>\s*'
    r"<code[^>]*>(.*?)</code>",
    re.S,
)
_DISPATCHABLE = frozenset(
    {
        "order_sheet_history",
        "order_sheet_by_shipment_box",
        "order_sheets_by_order",
        "return_request_by_receipt",
        "seller_product_partial",
    }
)
_BLOCKED = frozenset(
    {
        "exchange_requests",
        "return_withdraw_requests",
        "return_requests",
        "auto_category_agreed",
    }
)


def _norm(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "{}", path)


def _snapshot_operations() -> set[tuple[str, str, str]]:
    found: set[tuple[str, str, str]] = set()
    for page in _SNAPSHOT.glob("ko_api_*.html"):
        html = page.read_text(encoding="utf-8", errors="replace")
        main = html[html.find("<main") :] if "<main" in html else html
        match = _BADGE.search(main)
        if not match:
            continue
        method = match.group(2)
        path = re.sub(r"\s+", "", re.sub(r"<[^>]+>", "", match.group(3)))
        if method == "ETC" or not path.startswith("/"):
            continue
        found.add((method, path, page.name))
    return found


class _Client:
    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    async def get_order_sheet_history(self, shipment_box_id: str) -> object:
        self.calls.append(("get_order_sheet_history", (shipment_box_id,)))
        return self.payload

    async def get_order_sheet(self, shipment_box_id: str) -> object:
        self.calls.append(("get_order_sheet", (shipment_box_id,)))
        return self.payload

    async def list_order_sheets_by_order(self, order_id: str) -> object:
        self.calls.append(("list_order_sheets_by_order", (order_id,)))
        return self.payload

    async def get_return_request(self, receipt_id: str) -> object:
        self.calls.append(("get_return_request", (receipt_id,)))
        return self.payload

    async def get_seller_product_partial(self, seller_product_id: str) -> object:
        self.calls.append(("get_seller_product_partial", (seller_product_id,)))
        return self.payload

    async def list_exchange_requests(self, **kwargs: object) -> object:
        self.calls.append(("list_exchange_requests", (kwargs,)))
        return self.payload


class CoupangClient(_Client):
    """Name match for the live transport refusal. This is not the provider client."""


def _safe(result: object) -> dict[str, object]:
    payload = {
        "operation_id": result.operation_id,
        "items": result.items,
        "transport_connected": result.transport_connected,
        "live_call": result.live_call,
    }
    assert_agent_safe_value(payload)
    return payload


def test_coverage_classifies_every_official_operation_once() -> None:
    from k12_commerce_mcp.adapters.coupang.general_remaining_reads import (
        list_blocked_operations,
        list_dispatchable_reads,
        list_operation_coverage,
        list_unconnected_operations,
    )

    coverage = list_operation_coverage()
    assert len(coverage) == 90
    assert len({(item.method, item.path_template, item.source_doc) for item in coverage}) == 90
    counts: dict[str, int] = {}
    for item in coverage:
        counts[item.disposition] = counts.get(item.disposition, 0) + 1
        assert item.source_doc.endswith(".html")
        assert item.reason
        assert item.live_call is False
        assert item.transport_connected is False
    assert counts == {
        "connected_mcp": 9,
        "covered_extended": 17,
        "covered_missing_read": 10,
        "covered_disabled_query_post": 3,
        "covered_disabled_simulation": 42,
        "dispatchable": 5,
        "blocked": 4,
    }
    assert {item.operation_id for item in list_dispatchable_reads()} == _DISPATCHABLE
    assert {item.operation_id for item in list_blocked_operations()} == _BLOCKED
    assert len(list_unconnected_operations()) == 81
    assert all(item.disposition != "connected_mcp" for item in list_unconnected_operations())
    dispatchable = {item.operation_id: item for item in list_dispatchable_reads()}
    assert all(item.method == "GET" and item.execution_enabled for item in dispatchable.values())
    assert all(item.client_method for item in dispatchable.values())
    blocked = {item.operation_id: item for item in list_blocked_operations()}
    assert "createdAtFrom" in blocked["exchange_requests"].reason
    assert "7" in blocked["exchange_requests"].reason
    assert "dateFrom" in blocked["return_withdraw_requests"].reason
    assert "createdAtFrom" in blocked["return_withdraw_requests"].reason
    assert "searchType" in blocked["return_requests"].reason
    assert "get_effect_unknown" in blocked["auto_category_agreed"].reason
    extended_paths = {_norm(item.path_template) for item in list_unconnected_reads()}
    missing_paths = {_norm(item.path_template) for item in list_missing_reads()}
    allowed = {_norm(path) for path in ALLOWED_GET_PATH_TEMPLATES}
    for item in dispatchable.values():
        assert _norm(item.path_template) in allowed
        assert _norm(item.path_template) not in extended_paths
        assert _norm(item.path_template) not in missing_paths


def test_snapshot_pages_match_the_coverage_table() -> None:
    from k12_commerce_mcp.adapters.coupang.general_remaining_reads import list_operation_coverage

    if not _SNAPSHOT.is_dir():
        pytest.skip("snapshot directory missing")
    observed = _snapshot_operations()
    covered = {
        (item.method, item.path_template, item.source_doc.rsplit("/", 1)[-1])
        for item in list_operation_coverage()
    }
    assert covered == observed


_REFUSED = sorted(_BLOCKED | {"product_create", "ordersheets_by_day"})


@pytest.mark.parametrize("operation_id", _REFUSED)
async def test_non_dispatchable_operations_never_call_the_client(operation_id: str) -> None:
    from k12_commerce_mcp.adapters.coupang.general_remaining_reads import (
        BlockedReadError,
        CoupangGeneralRemainingReads,
        RemainingReadError,
    )

    client = _Client({"status": "ACCEPT"})
    facade = CoupangGeneralRemainingReads(client)
    with pytest.raises((BlockedReadError, RemainingReadError)):
        await facade.read(operation_id, shipment_box_id="1001", date_from=date(2026, 9, 1))
    assert client.calls == []


async def test_history_dispatch_projects_status_and_drops_unexpected_fields() -> None:
    from k12_commerce_mcp.adapters.coupang.general_remaining_reads import (
        CoupangGeneralRemainingReads,
    )

    client = _Client(
        (
            {
                "deliveryStatus": "DEPARTURE",
                "deliveryStatusDesc": "배송지시",
                "updatedAt": "2026-09-01T00:00:00",
                "shipmentBoxId": 1001,
            },
            {
                "deliveryStatus": "ACCEPT",
                "buyerName": "홍길동",
                "deliveryPhone": "010-1111-2222",
            },
        )
    )
    result = _safe(
        await CoupangGeneralRemainingReads(client).read(
            "order_sheet_history",
            shipment_box_id="1001",
        )
    )
    assert client.calls == [("get_order_sheet_history", ("1001",))]
    assert result["transport_connected"] is False
    assert result["live_call"] is False
    assert result["items"] == (
        {
            "deliveryStatus": "DEPARTURE",
            "deliveryStatusDesc": "배송지시",
            "updatedAt": "2026-09-01T00:00:00",
            "shipmentBoxId": 1001,
        },
        {"deliveryStatus": "ACCEPT"},
    )


async def test_order_sheet_dispatch_drops_receiver_and_customs_fields() -> None:
    from k12_commerce_mcp.adapters.coupang.general_remaining_reads import (
        CoupangGeneralRemainingReads,
    )

    payload = {
        "shipmentBoxId": 1001,
        "orderId": 2002,
        "orderedAt": "2026-09-01T01:02:03",
        "paidAt": "2026-09-01T01:03:04",
        "status": "ACCEPT",
        "splitShipping": False,
        "orderer": {"name": "홍길동", "email": "buyer@example.com", "safeNumber": "010-1234-5678"},
        "receiver": {
            "name": "김수신",
            "addr1": "서울시 강남구 테헤란로 1",
            "receiverNumber": "010-9999-8888",
        },
        "parcelPrintMessage": "문 앞에 두세요",
        "vendorId": "A00012345",
        "overseaShippingInfoDto": {
            "personalCustomsClearanceCode": "P123456789012",
            "orderersSsn": "900101-1234567",
        },
        "orderItems": [
            {
                "vendorItemId": 3003,
                "sellerProductId": 4004,
                "sellerProductName": "테스트상품",
                "shippingCount": 1,
                "salesPrice": {"currencyCode": "KRW", "units": 1000, "nanos": 0},
                "externalVendorSkuCode": "SKU-1",
                "etcInfoValue": "메모",
            }
        ],
    }
    client = _Client(payload)
    box = _safe(
        await CoupangGeneralRemainingReads(client).read(
            "order_sheet_by_shipment_box",
            shipment_box_id="1001",
        )
    )
    by_order = _safe(
        await CoupangGeneralRemainingReads(_Client((payload,))).read(
            "order_sheets_by_order",
            order_id="2002",
        )
    )
    expected = {
        "shipmentBoxId": 1001,
        "orderId": 2002,
        "orderedAt": "2026-09-01T01:02:03",
        "paidAt": "2026-09-01T01:03:04",
        "status": "ACCEPT",
        "splitShipping": False,
        "orderItems": (
            {
                "vendorItemId": 3003,
                "sellerProductId": 4004,
                "sellerProductName": "테스트상품",
                "shippingCount": 1,
                "salesPrice": {"currencyCode": "KRW", "units": 1000, "nanos": 0},
                "externalVendorSkuCode": "SKU-1",
            },
        ),
    }
    assert box["items"] == (expected,)
    assert by_order["items"] == (expected,)
    assert client.calls == [("get_order_sheet", ("1001",))]


async def test_partial_and_return_receipt_drop_contact_fields() -> None:
    from k12_commerce_mcp.adapters.coupang.general_remaining_reads import (
        CoupangGeneralRemainingReads,
    )

    partial_client = _Client(
        {
            "sellerProductId": 301,
            "deliveryChargeType": "FREE",
            "deliveryMethod": "SEQUENCIAL",
            "outboundShippingPlaceCode": 12,
            "returnCenterCode": "RC1",
            "pccNeeded": False,
            "remoteAreaDeliverable": "N",
            "unionDeliveryType": "UNION_DELIVERY",
            "companyContactNumber": "010-1234-5678",
            "returnAddress": "서울시 강남구 테헤란로 1",
            "returnAddressDetail": "101호",
            "returnChargeName": "담당자",
        }
    )
    partial = _safe(
        await CoupangGeneralRemainingReads(partial_client).read(
            "seller_product_partial",
            seller_product_id="301",
        )
    )
    receipt_client = _Client(
        {
            "receiptId": 363585,
            "orderId": 2002,
            "receiptType": "RETURN",
            "receiptStatus": "RETURNS_UNCHECKED",
            "createdAt": "2026-09-01T00:00:00",
            "faultByType": "CUSTOMER",
            "cancelCountSum": 1,
            "requesterName": "홍길동",
            "requesterPhoneNumber": "010-1234-5678",
            "requesterAddress": "서울시 강남구 테헤란로 1",
            "cancelReason": "고객 메모",
            "returnItems": [
                {
                    "vendorItemId": 9,
                    "sellerProductId": 8,
                    "cancelCount": 1,
                    "shipmentBoxId": 7,
                    "vendorItemName": "옵션",
                }
            ],
        }
    )
    receipt = _safe(
        await CoupangGeneralRemainingReads(receipt_client).read(
            "return_request_by_receipt",
            receipt_id="363585",
        )
    )
    assert partial["items"] == (
        {
            "sellerProductId": 301,
            "deliveryChargeType": "FREE",
            "deliveryMethod": "SEQUENCIAL",
            "outboundShippingPlaceCode": 12,
            "returnCenterCode": "RC1",
            "pccNeeded": False,
            "remoteAreaDeliverable": "N",
            "unionDeliveryType": "UNION_DELIVERY",
        },
    )
    assert receipt["items"] == (
        {
            "receiptId": 363585,
            "orderId": 2002,
            "receiptType": "RETURN",
            "receiptStatus": "RETURNS_UNCHECKED",
            "createdAt": "2026-09-01T00:00:00",
            "faultByType": "CUSTOMER",
            "cancelCountSum": 1,
            "returnItems": (
                {
                    "vendorItemId": 9,
                    "sellerProductId": 8,
                    "cancelCount": 1,
                    "shipmentBoxId": 7,
                    "vendorItemName": "옵션",
                },
            ),
        },
    )
    assert partial_client.calls == [("get_seller_product_partial", ("301",))]
    assert receipt_client.calls == [("get_return_request", ("363585",))]


async def test_invalid_input_and_live_client_are_refused_before_call() -> None:
    from k12_commerce_mcp.adapters.coupang.general_remaining_reads import (
        CoupangGeneralRemainingReads,
        RemainingReadError,
    )

    client = _Client(())
    facade = CoupangGeneralRemainingReads(client)
    with pytest.raises(RemainingReadError):
        await facade.read("order_sheet_history")
    with pytest.raises(RemainingReadError):
        await facade.read("order_sheet_history", shipment_box_id="010-1234-5678")
    with pytest.raises(RemainingReadError):
        await facade.read("order_sheet_history", shipment_box_id="1001", vendor_id="A1")
    live = CoupangClient(())
    with pytest.raises(RemainingReadError):
        await CoupangGeneralRemainingReads(live).read(
            "order_sheet_history",
            shipment_box_id="1001",
        )
    with pytest.raises(RemainingReadError):
        await CoupangGeneralRemainingReads(None).read(
            "order_sheet_history",
            shipment_box_id="1001",
        )
    assert client.calls == []
    assert live.calls == []


def test_module_does_not_import_live_transport() -> None:
    path = (
        Path(__file__).parents[1]
        / "src"
        / "k12_commerce_mcp"
        / "adapters"
        / "coupang"
        / "general_remaining_reads.py"
    )
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert not any(name.startswith("k12_commerce_mcp.clients") for name in imported)
    assert "httpx" not in imported
    assert "k12_commerce_mcp.server" not in imported
    text = path.read_text(encoding="utf-8")
    assert "CoupangGeneralAdapter" not in text
    assert "general_followup_read" not in text
