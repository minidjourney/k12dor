"""Disabled simulations for Coupang general mutations.

The catalog is checked against the 20260916 capture. Regex effect labels are
not treated as proof that a call is safe or that a POST is a state change.
No provider call, payload, identifier, secret, or personal data is emitted.
"""

from __future__ import annotations

import importlib.util
import re
import socket
import sys
from pathlib import Path

import pytest

MODULE_PATH = (
    Path(__file__).parents[1]
    / "src"
    / "k12_commerce_mcp"
    / "simulations"
    / "coupang_general.py"
)
SNAPSHOT = Path(
    "/data/documents/second-brain/raw/documents/marketplace-api-docs-20260916/coupang"
)
DOC_ROOT = "raw/documents/marketplace-api-docs-20260916/coupang"
SCRIPT_PATH = (
    Path(__file__).parents[1] / "scripts" / "build_three_channel_api_manifest.py"
)
SENTINELS = (
    "PAYLOAD_MUST_NOT_ECHO",
    "person@example.invalid",
    "010-0000-0000",
    "VENDOR_TOKEN_MUST_NOT_ECHO",
)
REFUSAL = "disabled simulation refused"
PRIMARY = re.compile(
    r'<span class="badge method-([a-z]+)[^"]*"[^>]*>\s*([A-Z]+)\s*</span>\s*'
    r"<code[^>]*>(.*?)</code>\s*</div>\s*<h1[^>]*>(.*?)</h1>",
    re.S,
)
FRONT = re.compile(r"^---\n.*?\n---\n", re.S)

# Identity reviewed from each capture's detail, not from the regex effect label.
# operation_id, category, filename, effect phrase present in that detail.
EXPECTED = (
    ("product_create", "product", "ko_api_products_product-creation.html", "판매할 상품을 등록"),
    ("product_modify", "product", "ko_api_products_modify-product.html", "업체상품 정보를 수정"),
    (
        "product_partial_modify",
        "product",
        "ko_api_products_product-modification-approval-not-required.html",
        "빠르게 수정",
    ),
    ("product_delete", "product", "ko_api_products_delete-a-product.html", "등록된 상품을 삭제"),
    (
        "product_approval_request",
        "product",
        "ko_api_products_request-for-product-approval.html",
        "승인요청",
    ),
    (
        "item_price_change",
        "product",
        "ko_api_products_changing-price-of-each-item-of-a-product.html",
        "판매가격을 변경",
    ),
    (
        "item_quantity_change",
        "product",
        "ko_api_products_changing-quantity-of-each-product-item.html",
        "재고수량을 변경",
    ),
    (
        "item_original_price_change",
        "product",
        "ko_api_products_change-the-base-price-for-discount-rate-at-an-item-level.html",
        "할인율 기준가격을 변경",
    ),
    (
        "item_sales_resume",
        "product",
        "ko_api_products_resume-sales-of-each-item-of-a-product.html",
        "판매중으로 변경",
    ),
    (
        "item_sales_stop",
        "product",
        "ko_api_products_suspend-sale-of-each-item-of-a-product.html",
        "판매중지로 변경",
    ),
    (
        "auto_option_opt_in_item",
        "product",
        "ko_api_products_activate-auto-generated-option-option-product-unit.html",
        "개별 옵션상품마다 활성화",
    ),
    (
        "auto_option_opt_in_seller",
        "product",
        "ko_api_products_activate-auto-generated-option-total-product-unit.html",
        "전체 상품에 대해 활성화",
    ),
    (
        "auto_option_opt_out_item",
        "product",
        "ko_api_products_disable-auto-generated-option-option-product-unit.html",
        "개별 옵션상품마다 비활성화",
    ),
    (
        "auto_option_opt_out_seller",
        "product",
        "ko_api_products_disable-auto-generated-option-total-product-unit.html",
        "전체 상품에 대해 비활성화",
    ),
    (
        "outbound_place_create",
        "shipping",
        "ko_api_logistics_create-a-shipping-location.html",
        "출고지를 생성",
    ),
    (
        "outbound_place_update",
        "shipping",
        "ko_api_logistics_update-a-shipping-location.html",
        "출고지를 수정",
    ),
    (
        "return_place_create",
        "shipping",
        "ko_api_logistics_create-a-return-location.html",
        "반품지를 생성",
    ),
    (
        "return_place_update",
        "shipping",
        "ko_api_logistics_update-a-return-location.html",
        "반품지를 수정",
    ),
    (
        "invoice_upload",
        "shipping",
        "ko_api_shipments_uploading-waybills.html",
        "배송지시 상태로 변경",
    ),
    (
        "invoice_update",
        "shipping",
        "ko_api_shipments_updating-waybills.html",
        "운송장 내용을 변경",
    ),
    (
        "long_term_undelivery_complete",
        "shipping",
        "ko_api_shipments_process-orders-long-past-their-promised-"
        "delivery-date-as-delivery-completed.html",
        "배송완료로 상태",
    ),
    (
        "order_acknowledge",
        "order",
        "ko_api_shipments_changing-the-status-to-product-in-preparation.html",
        "상품준비중",
    ),
    ("order_cancel", "cancel", "ko_api_shipments_cancel-an-order.html", "상품을 취소"),
    (
        "already_shipped",
        "cancel",
        "ko_api_shipments_processing-already-released.html",
        "이미 판매자가 상품을 발송",
    ),
    (
        "stop_shipment",
        "cancel",
        "ko_api_shipments_processing-release-stop.html",
        "출고하지 않았을 때",
    ),
    (
        "exchange_receive_confirmation",
        "exchange",
        "ko_api_exchanges_check-the-receipt-of-exchange-requested-product.html",
        "입고 확인 상태로 변경",
    ),
    (
        "exchange_reject",
        "exchange",
        "ko_api_exchanges_reject-an-exchange-request.html",
        "교환 요청을 거부",
    ),
    (
        "exchange_invoice_upload",
        "exchange",
        "ko_api_exchanges_upload-a-waybill-for-exchange-product.html",
        "운송장을 입력",
    ),
    (
        "return_approval",
        "return",
        "ko_api_returns_approve-request-for-return.html",
        "환불 처리",
    ),
    (
        "return_receive_confirmation",
        "return",
        "ko_api_returns_return-product-receipt-confirmation.html",
        "반품접수",
    ),
    (
        "return_pickup_invoice",
        "return",
        "ko_api_returns_upload-a-pickup-waybill.html",
        "회수 송장",
    ),
    (
        "online_inquiry_reply",
        "inquiry",
        "ko_api_cs_answer-to-customer-product-inquiry.html",
        "답변할 수 있습니다",
    ),
    (
        "call_center_inquiry_reply",
        "inquiry",
        "ko_api_cs_answer-to-inquiries-via-coupang-contact-center.html",
        "문의에 대해 답변",
    ),
    (
        "call_center_inquiry_confirm",
        "inquiry",
        "ko_api_cs_coupang-contact-center-inquiry-check.html",
        "확인 처리",
    ),
    (
        "book_cashback_apply",
        "promotion",
        "ko_api_promotions_book-applying-cashback.html",
        "캐시백 룰을 적용",
    ),
    (
        "book_cashback_delete",
        "promotion",
        "ko_api_promotions_book-removing-product-cashback.html",
        "캐시백 룰을 중지",
    ),
    (
        "download_coupon_create",
        "promotion",
        "ko_api_promotions_downloadable-coupon-creation.html",
        "쿠폰을 생성",
    ),
    (
        "download_coupon_expire",
        "promotion",
        "ko_api_promotions_downloadable-coupon-expiring-download-coupon.html",
        "쿠폰을 파기",
    ),
    (
        "download_coupon_item_create",
        "promotion",
        "ko_api_promotions_downloadable-coupon-item-creation.html",
        "쿠폰을 적용",
    ),
    (
        "instant_coupon_create",
        "promotion",
        "ko_api_promotions_instant-discount-coupon-creation.html",
        "신규 쿠폰 생성",
    ),
    (
        "instant_coupon_expire",
        "promotion",
        "ko_api_promotions_instant-discount-coupon-expiration-disable.html",
        "쿠폰의 파기",
    ),
    (
        "instant_coupon_item_create",
        "promotion",
        "ko_api_promotions_instant-discount-coupon-item-addition.html",
        "개별 아이템에 적용",
    ),
)
REGEX_MISSED = (
    "ko_api_cs_answer-to-customer-product-inquiry.html",
    "ko_api_cs_answer-to-inquiries-via-coupang-contact-center.html",
    "ko_api_cs_coupang-contact-center-inquiry-check.html",
    "ko_api_promotions_book-applying-cashback.html",
    "ko_api_promotions_downloadable-coupon-expiring-download-coupon.html",
)
NOT_MUTATIONS = (
    "ko_api_categories_category-recommendation.html",
    "ko_api_brands_brand-search.html",
    "ko_api_returns_query-return-withdrawal-history-by-receiptid.html",
    "ko_api_brands_enrolled-brands-list.html",
    "ko_api_products_query-a-history-of-product-status-updates.html",
)


def _text(fragment: str) -> str:
    cleaned = re.sub(r"<[^>]+>", " ", fragment)
    return re.sub(r"\s+", "", cleaned)


def _capture(
    filename: str,
    *,
    require_path_methods: bool = True,
) -> tuple[str, str, tuple[str, ...], str]:
    html = FRONT.sub("", (SNAPSHOT / filename).read_text(encoding="utf-8"), count=1)
    main = html[html.find("<main") :] if "<main" in html else html
    match = PRIMARY.search(main)
    if match is None or match.group(2) == "ETC":
        pytest.fail(f"{filename} is not an operation capture")
    path = _text(match.group(3))
    path_at = main.find(">Path<")
    neighborhood = main[path_at : path_at + 500] if path_at != -1 else ""
    methods = tuple(
        dict.fromkeys(
            item[1]
            for item in re.findall(
                r'class="(get|post|put|patch|delete)"[^>]*>\s*'
                r"(GET|POST|PUT|PATCH|DELETE)\s*<",
                neighborhood,
            )
        )
    )
    if require_path_methods and not methods:
        pytest.fail(f"{filename} path methods missing")
    detail_at = main.find("zendesk-body")
    chunk = main[detail_at : detail_at + 2200] if detail_at != -1 else ""
    for stop in ("Request Parameters", "Body Parameter", "Example Endpoint"):
        stop_at = chunk.find(stop)
        if stop_at != -1:
            chunk = chunk[:stop_at]
    detail = re.sub(r"<[^>]+>", " ", chunk)
    detail = detail.replace("&gt;", ">").replace("&lt;", "<").replace("&amp;", "&")
    detail = re.sub(r"\s+", " ", detail)
    return match.group(2), path, methods, detail


def _load():
    if not MODULE_PATH.is_file():
        pytest.fail("coupang general simulation module is missing")
    spec = importlib.util.spec_from_file_location(
        "coupang_general_simulations",
        MODULE_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _manifest():
    spec = importlib.util.spec_from_file_location(
        "build_three_channel_api_manifest",
        SCRIPT_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.build_manifest(SNAPSHOT.parent)


@pytest.fixture(scope="module")
def simulations():
    return _load()


def test_document_confirmed_mutations_are_disabled_simulations(simulations) -> None:
    catalog = simulations.list_disabled_simulations()
    by_id = {item.operation_id: item for item in catalog}

    assert simulations.SNAPSHOT_ID == "20260916"
    assert len(catalog) == len(EXPECTED) == 42
    assert len(by_id) == 42
    assert {item.category for item in catalog} == {
        "product",
        "order",
        "shipping",
        "cancel",
        "exchange",
        "return",
        "inquiry",
        "promotion",
    }
    for operation_id, category, filename, phrase in EXPECTED:
        badge, path, methods, detail = _capture(filename)
        item = by_id[operation_id]
        if phrase not in detail:
            pytest.fail(f"{operation_id} document effect phrase missing")
        assert item.category == category
        assert item.channel == "coupang_general"
        assert item.method == badge
        assert item.method in item.documented_methods
        assert set(item.documented_methods) == set(methods)
        assert item.path_template == path
        assert item.path_template.startswith("/v2/")
        assert re.search(r"\d{6,}", item.path_template) is None
        assert item.document_ref == f"{DOC_ROOT}/{filename}"
        assert "rocket-growth" not in item.document_ref
        assert "rg_open_api" not in item.path_template
        assert item.status == "disabled_simulation"
        assert item.execution_enabled is False
        assert item.live_call is False
        assert item.approval == "none"
        assert item.external_calls == 0
        assert phrase in item.disabled_reason
        assert "외부 전송하지 않는다" in item.disabled_reason
        assert "effect_class" not in item.disabled_reason
        assert "@" not in item.disabled_reason
        if len(methods) > 1:
            assert "PATCH" in item.disabled_reason
            assert "PUT" in item.disabled_reason
            assert "배지만으로" in item.disabled_reason
        with pytest.raises(AttributeError):
            item.execution_enabled = True  # type: ignore[misc]


def test_regex_labels_do_not_define_the_mutation_set(simulations) -> None:
    catalog = simulations.list_disabled_simulations()
    keys = {(item.method, item.path_template) for item in catalog}
    general = [
        op
        for op in _manifest()["operations"]
        if op["channel"] == "coupang_general"
    ]
    by_key = {(str(op["method"]), str(op["path"])): op for op in general}

    assert len(general) == 90
    assert len(catalog) == 42
    missed = []
    for filename in REGEX_MISSED:
        badge, path, _, _ = _capture(filename)
        missed.append(by_key[(badge, path)]["effect_class"])
        assert (badge, path) in keys
    assert missed == ["post_effect_unknown"] * 5
    for item in catalog:
        effect = by_key[(item.method, item.path_template)]["effect_class"]
        filename = item.document_ref.rsplit("/", 1)[-1]
        if filename in REGEX_MISSED:
            assert effect == "post_effect_unknown"
        else:
            assert effect == "mutation"
    for filename in NOT_MUTATIONS:
        badge, path, _, _ = _capture(filename, require_path_methods=False)
        assert (badge, path) not in keys
        assert by_key[(badge, path)]["effect_class"] != "mutation"


def test_simulate_never_transmits_or_echoes_caller_input(
    simulations, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[str] = []

    def blocked(*_args: object, **_kwargs: object) -> None:
        opened.append("socket")
        raise AssertionError("socket opened")

    monkeypatch.setattr(socket, "socket", blocked)
    payload = {
        "note": SENTINELS[0],
        "contact": SENTINELS[1],
        "phone": SENTINELS[2],
        "token": SENTINELS[3],
    }
    before = dict(payload)

    class Spy:
        def __getattr__(self, name: str) -> object:
            raise AssertionError("transport touched")

    spy = Spy()
    for item in simulations.list_disabled_simulations():
        default = simulations.simulate(
            item.operation_id,
            payload=payload,
            transport=spy,
        )
        assert default.method == item.method
        assert default.transmitted is False
        assert default.external_calls == 0
        assert default.execution_enabled is False
        assert default.status == "disabled_simulation"
        assert default.disabled_reason == item.disabled_reason
        assert "payload" not in default.__dataclass_fields__
        blob = repr(default) + str(default)
        for secret in SENTINELS:
            assert secret not in blob
        for method in item.documented_methods:
            receipt = simulations.simulate(
                item.operation_id,
                method=method,
                payload=payload,
                transport=spy,
            )
            assert receipt.method == method
            assert receipt.transmitted is False
            assert receipt.path_template == item.path_template
            for secret in SENTINELS:
                assert secret not in repr(receipt)

    assert payload == before
    assert opened == []
    with pytest.raises(simulations.SimulationDisabled) as unknown:
        simulations.simulate(SENTINELS[0], method="POST", payload=payload, transport=spy)
    assert unknown.value.args == (REFUSAL,)
    assert SENTINELS[0] not in str(unknown.value)
    with pytest.raises(simulations.SimulationDisabled) as read_attempt:
        simulations.simulate("product_create", method="GET", payload=payload, transport=spy)
    assert read_attempt.value.args == (REFUSAL,)
    for secret in SENTINELS:
        assert secret not in str(read_attempt.value)


def test_module_has_no_provider_client_or_regex_classifier() -> None:
    if not MODULE_PATH.is_file():
        pytest.fail("coupang general simulation module is missing")
    source = MODULE_PATH.read_text(encoding="utf-8")
    for token in (
        "httpx",
        "urllib",
        "requests",
        "socket",
        "CoupangClient",
        "urlopen",
        "build_three_channel_api_manifest",
    ):
        assert token not in source
