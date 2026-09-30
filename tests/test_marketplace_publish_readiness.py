"""Readiness contract for commerce_prepare_marketplace_product_drafts.

One canonical common product plus per-channel config objects produce
independent structured readiness per channel. The tool is READ-only: it
builds and validates draft candidates locally and never calls a provider
or a database. Unknown values stay unknown; nothing is zero-filled.

Common ``image_refs`` are K12-local opaque refs, never provider paths.
Coupang/Toss readiness therefore requires typed per-channel
``image_materializations`` bindings that resolve each local ref to an
explicit provider location; unmapped or ambiguous refs block readiness.
"""

from __future__ import annotations

import pytest
from mcp import Client
from pydantic import ValidationError

from k12_commerce_mcp.models import (
    CanonicalCommonProduct,
    CoupangChannelConfig,
    NaverChannelConfig,
    TossChannelConfig,
)
from k12_commerce_mcp.models.marketplace_publish import (
    CoupangImageMaterialization,
    TossImageMaterialization,
)
from k12_commerce_mcp.publishing import CoupangProductPublisher
from k12_commerce_mcp.server import build_server
from k12_commerce_mcp.service import MarketplaceReadinessService

COUPANG_IMAGE_MATERIALIZATIONS: tuple[dict[str, str], ...] = (
    {"image_ref": "img-z-1", "vendor_path": "vendor/k12/img-z-1.jpg"},
    {"image_ref": "img-z-2", "cdn_path": "cdn/k12/img-z-2.jpg"},
    {"image_ref": "img-a-1", "vendor_path": "vendor/k12/img-a-1.jpg"},
)

TOSS_IMAGE_MATERIALIZATIONS: tuple[dict[str, str], ...] = (
    {"image_ref": "img-rep-001", "url": "https://img.example.com/rep-001.png"},
    {"image_ref": "img-gallery-001", "url": "https://img.example.com/gallery-001.png"},
    {"image_ref": "img-gallery-002", "url": "https://img.example.com/gallery-002.png"},
    {"image_ref": "img-z-1", "url": "https://img.example.com/opt-z-1.png"},
    {"image_ref": "img-z-2", "url": "https://img.example.com/opt-z-2.png"},
    {"image_ref": "img-a-1", "url": "https://img.example.com/opt-a-1.png"},
)


def sparse_product() -> CanonicalCommonProduct:
    """The DOR-style payload that previously reached publish tools."""
    return CanonicalCommonProduct(
        title="할로윈 풍선 세트",
        representative_image_ref="img-rep-001",
    )


def complete_product() -> CanonicalCommonProduct:
    return CanonicalCommonProduct.model_validate(
        {
            "title": "할로윈 풍선 세트",
            "price": 12900,
            "description": "할로윈 파티용 풍선 12개 세트",
            "shipping_fee": 3000,
            "representative_image_ref": "img-rep-001",
            "gallery_image_refs": ["img-gallery-001", "img-gallery-002"],
            "options": [
                {
                    "option_ref": "opt-z",
                    "name": "레드",
                    "price": 12900,
                    "stock_quantity": 15,
                    "image_refs": ["img-z-1", "img-z-2"],
                },
                {
                    "option_ref": "opt-a",
                    "name": "블루",
                    "price": 13900,
                    "stock_quantity": 7,
                    "image_refs": ["img-a-1"],
                },
            ],
        }
    )


def coupang_config(**overrides: object) -> CoupangChannelConfig:
    base: dict[str, object] = {
        "channel": "coupang",
        "vendor_id": "A00012345",
        "sale_started_at": "2026-09-21T00:00:00",
        "sale_ended_at": "2026-12-31T23:59:59",
        "delivery_method": "SEQUENCIAL",
        "delivery_company_code": "CJGLS",
        "delivery_charge_type": "NOT_FREE",
        "free_ship_over_amount": 50000,
        "delivery_charge_on_return": 3000,
        "remote_area_deliverable": "Y",
        "union_delivery_type": "NOT_UNION_DELIVERY",
        "return_center_code": "RC-001",
        "return_charge_name": "반품센터",
        "company_contact_number": "0212345678",
        "return_zip_code": "12345",
        "return_address": "물류센터",
        "return_address_detail": "101동",
        "return_charge": 3000,
        "outbound_shipping_place_code": 123,
        "vendor_user_id": "vendor-user-1",
        "requested": True,
        "item_defaults": {
            "maximum_buy_count": 100,
            "maximum_buy_for_person": 0,
            "maximum_buy_for_person_period": 1,
            "outbound_shipping_time_day": 2,
            "unit_count": 1,
            "adult_only": "EVERYONE",
            "tax_type": "TAX",
            "parallel_imported": "NOT_PARALLEL_IMPORTED",
            "overseas_purchased": "NOT_OVERSEAS_PURCHASED",
            "pcc_needed": False,
            "attributes": [
                {"attribute_type_name": "색상", "attribute_value_name": "혼합"},
            ],
        },
        "image_materializations": list(COUPANG_IMAGE_MATERIALIZATIONS),
    }
    base.update(overrides)
    return CoupangChannelConfig.model_validate(base)


def naver_config(**overrides: object) -> NaverChannelConfig:
    base: dict[str, object] = {
        "channel": "naver",
        "leaf_category_id": "50000000",
        "delivery_info": {"deliveryType": "DELIVERY", "deliveryFee": 3000},
        "detail_attribute": {"taxType": "TAX"},
        "naver_shopping_registration": True,
        "channel_product_display_status_type": "ON",
        "image_storage_ref": "main.png",
        "image_mime_type": "image/png",
        "image_byte_size": 1024,
        "image_sha256": "a" * 64,
    }
    base.update(overrides)
    return NaverChannelConfig.model_validate(base)


def toss_config(**overrides: object) -> TossChannelConfig:
    base: dict[str, object] = {
        "channel": "toss",
        "category_id": 14835,
        "is_tax_free": False,
        "exposure": {"search_keywords": ["할로윈", "풍선"]},
        "delivery_policy": {
            "delivery_method": "NORMAL",
            "delivery_fee_type": "PAID",
            "delivery_fee": 3000,
            "minimum_purchase_price": 0,
            "is_jeju_and_islands_mountains_delivery": False,
        },
        "exchange_return_policy": {
            "refund_one_way_delivery_fee": 3000,
            "exchange_round_trip_delivery_fee": 6000,
            "application_method_description": "고객센터 접수",
            "application_term_description": "수령 후 7일 이내",
        },
        "notice": {
            "category_code": "GENERAL",
            "items": [{"id": 1, "content": "상품 고시"}],
        },
        "image_materializations": list(TOSS_IMAGE_MATERIALIZATIONS),
    }
    base.update(overrides)
    return TossChannelConfig.model_validate(base)


def test_sparse_product_returns_blockers_instead_of_throwing() -> None:
    service = MarketplaceReadinessService()

    result = service.evaluate(sparse_product(), (CoupangChannelConfig(channel="coupang"),))

    assert result.status == "complete"
    assert result.stage == "readiness"
    assert result.external_write_performed is False
    assert len(result.channels) == 1
    entry = result.channels[0]
    assert entry.channel == "coupang"
    assert entry.stage == "readiness"
    assert entry.ready is False
    assert entry.prepared_draft is None
    assert entry.external_execution_configured is False
    assert {"price", "description", "shipping_fee", "options"} <= set(entry.missing_common_fields)
    assert "vendor_id" in entry.missing_channel_fields
    assert "return_center_code" in entry.missing_channel_fields


def test_complete_product_produces_typed_coupang_draft() -> None:
    service = MarketplaceReadinessService()

    result = service.evaluate(complete_product(), (coupang_config(),))

    entry = result.channels[0]
    assert entry.ready is True
    assert entry.missing_common_fields == ()
    assert entry.missing_channel_fields == ()
    assert entry.invalid_fields == ()
    draft = entry.prepared_draft
    assert draft is not None
    assert draft.channel == "coupang"
    assert draft.seller_product_name == "할로윈 풍선 세트"


def test_coupang_images_map_to_items_by_option_ref_never_by_order() -> None:
    service = MarketplaceReadinessService()

    result = service.evaluate(complete_product(), (coupang_config(),))

    draft = result.channels[0].prepared_draft
    assert draft is not None
    by_ref = {item.option_ref: item for item in draft.items}
    assert set(by_ref) == {"opt-z", "opt-a"}
    assert by_ref["opt-z"].item_name == "레드"
    assert by_ref["opt-z"].image_refs == (
        "vendor/k12/img-z-1.jpg",
        "cdn/k12/img-z-2.jpg",
    )
    assert by_ref["opt-a"].item_name == "블루"
    assert by_ref["opt-a"].image_refs == ("vendor/k12/img-a-1.jpg",)


def test_coupang_without_image_materializations_is_never_ready() -> None:
    """Local opaque refs are never reused as Coupang vendor/cdn paths."""
    service = MarketplaceReadinessService()

    result = service.evaluate(
        complete_product(), (coupang_config(image_materializations=()),)
    )

    entry = result.channels[0]
    assert entry.ready is False
    assert entry.prepared_draft is None
    assert {
        "image_materializations[img-z-1]",
        "image_materializations[img-z-2]",
        "image_materializations[img-a-1]",
    } <= set(entry.missing_channel_fields)
    assert entry.missing_common_fields == ()
    assert entry.invalid_fields == ()


def test_coupang_partial_mapping_reports_each_unmapped_ref() -> None:
    service = MarketplaceReadinessService()
    config = coupang_config(
        image_materializations=[
            binding
            for binding in COUPANG_IMAGE_MATERIALIZATIONS
            if binding["image_ref"] != "img-a-1"
        ]
    )

    entry = service.evaluate(complete_product(), (config,)).channels[0]

    assert entry.ready is False
    assert entry.prepared_draft is None
    assert "image_materializations[img-a-1]" in entry.missing_channel_fields
    assert "image_materializations[img-z-1]" not in entry.missing_channel_fields
    # The common option.image_refs values exist; the channel binding is the gap.
    assert entry.missing_common_fields == ()


def test_coupang_duplicate_binding_is_ambiguous_and_invalid() -> None:
    service = MarketplaceReadinessService()
    config = coupang_config(
        image_materializations=[
            {"image_ref": "img-z-1", "vendor_path": "vendor/k12/one.jpg"},
            {"image_ref": "img-z-1", "cdn_path": "cdn/k12/two.jpg"},
            *COUPANG_IMAGE_MATERIALIZATIONS[1:],
        ]
    )

    entry = service.evaluate(complete_product(), (config,)).channels[0]

    assert entry.ready is False
    assert entry.prepared_draft is None
    assert "image_materializations[img-z-1]" in entry.invalid_fields
    assert "image_materializations[img-z-1]" not in entry.missing_channel_fields


def test_coupang_image_binding_requires_exactly_one_path() -> None:
    with pytest.raises(ValidationError):
        CoupangImageMaterialization.model_validate({"image_ref": "img-1"})
    with pytest.raises(ValidationError):
        CoupangImageMaterialization.model_validate(
            {"image_ref": "img-1", "vendor_path": "a/b.jpg", "cdn_path": "c/d.jpg"}
        )
    bound = CoupangImageMaterialization.model_validate(
        {"image_ref": "img-1", "cdn_path": "c/d.jpg"}
    )
    assert bound.vendor_path is None
    assert bound.cdn_path == "c/d.jpg"


def test_missing_channel_fields_are_reported_per_channel() -> None:
    service = MarketplaceReadinessService()

    result = service.evaluate(complete_product(), (CoupangChannelConfig(channel="coupang"),))

    entry = result.channels[0]
    assert entry.ready is False
    assert entry.missing_common_fields == ()
    assert "vendor_id" in entry.missing_channel_fields
    assert "sale_started_at" in entry.missing_channel_fields
    assert "return_center_code" in entry.missing_channel_fields
    assert "requested" in entry.missing_channel_fields
    assert entry.invalid_fields == ()
    assert entry.prepared_draft is None


def test_invalid_channel_values_are_reported_as_invalid_not_missing() -> None:
    service = MarketplaceReadinessService()

    result = service.evaluate(
        complete_product(),
        (coupang_config(sale_started_at="not-a-date"),),
    )

    entry = result.channels[0]
    assert entry.ready is False
    assert entry.prepared_draft is None
    assert any(field.startswith("sale_started_at") for field in entry.invalid_fields)
    assert "sale_started_at" not in entry.missing_channel_fields


def test_naver_and_toss_readiness_stay_independent() -> None:
    service = MarketplaceReadinessService()

    result = service.evaluate(
        complete_product(),
        (naver_config(), TossChannelConfig(channel="toss")),
    )

    by_channel = {entry.channel: entry for entry in result.channels}
    assert set(by_channel) == {"naver", "toss"}
    naver = by_channel["naver"]
    assert naver.ready is True
    assert naver.prepared_draft is not None
    assert naver.prepared_draft.channel == "naver"
    assert naver.prepared_draft.sale_price == 12900
    assert naver.prepared_draft.stock_quantity == 22
    toss = by_channel["toss"]
    assert toss.ready is False
    assert toss.prepared_draft is None
    assert "notice" in toss.missing_channel_fields


def test_complete_toss_config_preserves_option_refs_in_stocks() -> None:
    service = MarketplaceReadinessService()

    result = service.evaluate(complete_product(), (toss_config(),))

    entry = result.channels[0]
    assert entry.ready is True
    draft = entry.prepared_draft
    assert draft is not None
    assert draft.channel == "toss"
    by_ref = {stock.option_ref: stock for stock in draft.stocks}
    assert set(by_ref) == {"opt-z", "opt-a"}
    assert by_ref["opt-z"].is_main_price is True
    assert by_ref["opt-a"].is_main_price is False
    assert by_ref["opt-z"].image_refs == (
        "https://img.example.com/opt-z-1.png",
        "https://img.example.com/opt-z-2.png",
    )
    assert draft.image_refs == (
        "https://img.example.com/rep-001.png",
        "https://img.example.com/gallery-001.png",
        "https://img.example.com/gallery-002.png",
    )


def test_toss_unmapped_representative_ref_blocks_readiness() -> None:
    service = MarketplaceReadinessService()
    config = toss_config(
        image_materializations=[
            binding
            for binding in TOSS_IMAGE_MATERIALIZATIONS
            if binding["image_ref"] != "img-rep-001"
        ]
    )

    entry = service.evaluate(complete_product(), (config,)).channels[0]

    assert entry.ready is False
    assert entry.prepared_draft is None
    assert "image_materializations[img-rep-001]" in entry.missing_channel_fields
    assert "representative_image_ref" not in entry.missing_common_fields


def test_toss_unmapped_gallery_and_option_refs_block_readiness() -> None:
    service = MarketplaceReadinessService()
    config = toss_config(
        image_materializations=[
            binding
            for binding in TOSS_IMAGE_MATERIALIZATIONS
            if binding["image_ref"] not in {"img-gallery-002", "img-a-1"}
        ]
    )

    entry = service.evaluate(complete_product(), (config,)).channels[0]

    assert entry.ready is False
    assert {
        "image_materializations[img-gallery-002]",
        "image_materializations[img-a-1]",
    } <= set(entry.missing_channel_fields)


def test_toss_duplicate_binding_is_ambiguous_and_invalid() -> None:
    service = MarketplaceReadinessService()
    config = toss_config(
        image_materializations=[
            *TOSS_IMAGE_MATERIALIZATIONS,
            {"image_ref": "img-rep-001", "url": "https://img.example.com/other.png"},
        ]
    )

    entry = service.evaluate(complete_product(), (config,)).channels[0]

    assert entry.ready is False
    assert entry.prepared_draft is None
    assert "image_materializations[img-rep-001]" in entry.invalid_fields


def test_toss_image_binding_requires_public_https_url() -> None:
    with pytest.raises(ValidationError):
        TossImageMaterialization.model_validate(
            {"image_ref": "img-1", "url": "pa-img:local-1"}
        )
    with pytest.raises(ValidationError):
        TossImageMaterialization.model_validate(
            {"image_ref": "img-1", "url": "http://img.example.com/x.png"}
        )
    bound = TossImageMaterialization.model_validate(
        {"image_ref": "img-1", "url": "https://img.example.com/x.png"}
    )
    assert bound.url == "https://img.example.com/x.png"


def test_toss_bindings_never_reuse_coupang_paths() -> None:
    """Toss materializations are typed URLs; vendor/cdn paths cannot pass."""
    with pytest.raises(ValidationError):
        TossChannelConfig.model_validate(
            {
                "channel": "toss",
                "image_materializations": [
                    {"image_ref": "img-1", "vendor_path": "vendor/k12/x.jpg"}
                ],
            }
        )

    service = MarketplaceReadinessService()
    result = service.evaluate(complete_product(), (coupang_config(), toss_config()))

    by_channel = {entry.channel: entry for entry in result.channels}
    assert by_channel["coupang"].ready is True
    assert by_channel["toss"].ready is True
    toss_draft = by_channel["toss"].prepared_draft
    assert toss_draft is not None
    assert all(ref.startswith("https://") for ref in toss_draft.image_refs)
    for stock in toss_draft.stocks:
        assert all(ref.startswith("https://") for ref in stock.image_refs)


def test_naver_keeps_local_asset_upload_semantics() -> None:
    """Naver uploads approved local assets; it has no URL materialization field."""
    with pytest.raises(ValidationError):
        NaverChannelConfig.model_validate(
            {
                "channel": "naver",
                "image_materializations": [
                    {"image_ref": "img-1", "url": "https://img.example.com/x.png"}
                ],
            }
        )

    service = MarketplaceReadinessService()
    entry = service.evaluate(complete_product(), (naver_config(),)).channels[0]

    assert entry.ready is True
    assert entry.prepared_draft is not None
    assert entry.prepared_draft.image_storage_ref == "main.png"


def test_unknown_option_values_stay_unknown_and_block() -> None:
    product = CanonicalCommonProduct.model_validate(
        {
            "title": "옵션 미정 상품",
            "price": 5000,
            "description": "설명",
            "shipping_fee": 0,
            "representative_image_ref": "img-rep",
            "options": [{"option_ref": "opt-1", "name": "기본"}],
        }
    )
    service = MarketplaceReadinessService()

    result = service.evaluate(product, (toss_config(), coupang_config()))

    for entry in result.channels:
        assert entry.ready is False
        assert entry.prepared_draft is None
        assert "options[opt-1].price" in entry.missing_common_fields
        assert "options[opt-1].stock_quantity" in entry.missing_common_fields


def test_coupang_requires_explicit_option_images_but_naver_does_not() -> None:
    product = CanonicalCommonProduct.model_validate(
        {
            "title": "이미지 없는 옵션 상품",
            "price": 5000,
            "description": "설명",
            "shipping_fee": 0,
            "representative_image_ref": "img-rep",
            "options": [
                {
                    "option_ref": "opt-1",
                    "name": "기본",
                    "price": 5000,
                    "stock_quantity": 3,
                }
            ],
        }
    )
    service = MarketplaceReadinessService()

    result = service.evaluate(product, (coupang_config(), naver_config()))

    by_channel = {entry.channel: entry for entry in result.channels}
    coupang = by_channel["coupang"]
    assert coupang.ready is False
    assert "options[opt-1].image_refs" in coupang.missing_common_fields
    naver = by_channel["naver"]
    assert naver.ready is True
    assert "options[opt-1].image_refs" not in naver.missing_common_fields


def test_duplicate_option_refs_are_invalid_not_silently_merged() -> None:
    product = CanonicalCommonProduct.model_validate(
        {
            "title": "중복 옵션 상품",
            "price": 5000,
            "description": "설명",
            "shipping_fee": 0,
            "representative_image_ref": "img-rep",
            "options": [
                {
                    "option_ref": "opt-dup",
                    "name": "첫째",
                    "price": 5000,
                    "stock_quantity": 1,
                    "image_refs": ["img-1"],
                },
                {
                    "option_ref": "opt-dup",
                    "name": "둘째",
                    "price": 6000,
                    "stock_quantity": 2,
                    "image_refs": ["img-2"],
                },
            ],
        }
    )
    service = MarketplaceReadinessService()

    result = service.evaluate(product, (coupang_config(),))

    entry = result.channels[0]
    assert entry.ready is False
    assert entry.prepared_draft is None
    assert "options.option_ref" in entry.invalid_fields


def test_external_execution_configured_only_when_explicitly_injected() -> None:
    default = MarketplaceReadinessService().evaluate(complete_product(), (coupang_config(),))
    injected = MarketplaceReadinessService(external_execution={"coupang": True}).evaluate(
        complete_product(), (coupang_config(),)
    )

    assert default.channels[0].external_execution_configured is False
    assert injected.channels[0].external_execution_configured is True


async def test_tool_is_registered_read_only_and_fails_closed() -> None:
    async with Client(build_server()) as client:
        listed = await client.list_tools()
        result = await client.call_tool(
            "commerce_prepare_marketplace_product_drafts",
            {
                "product": {
                    "title": "할로윈 풍선 세트",
                    "representative_image_ref": "img-rep-001",
                },
                "channel_configs": [{"channel": "coupang"}],
            },
        )

    tool = next(
        item for item in listed.tools if item.name == "commerce_prepare_marketplace_product_drafts"
    )
    assert tool.annotations is not None
    assert tool.annotations.read_only_hint is True
    assert tool.annotations.destructive_hint is False
    assert result.is_error is False
    assert result.structured_content["stage"] == "readiness"
    assert result.structured_content["external_write_performed"] is False
    entry = result.structured_content["channels"][0]
    assert entry["channel"] == "coupang"
    assert entry["ready"] is False
    assert entry["prepared_draft"] is None
    assert entry["external_execution_configured"] is False
    assert "options" in entry["missing_common_fields"]


async def test_tool_reports_execution_configured_with_injected_publisher() -> None:
    publisher = CoupangProductPublisher(client=object(), approval_verifier=object())
    async with Client(build_server(coupang_publisher=publisher)) as client:
        result = await client.call_tool(
            "commerce_prepare_marketplace_product_drafts",
            {
                "product": complete_product().model_dump(mode="json"),
                "channel_configs": [coupang_config().model_dump(mode="json")],
            },
        )

    assert result.is_error is False
    entry = result.structured_content["channels"][0]
    assert entry["ready"] is True
    assert entry["external_execution_configured"] is True
