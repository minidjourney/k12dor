"""Local marketplace publish readiness evaluation.

This module builds per-channel draft candidates from one canonical common
product plus channel config objects and validates them against the canonical
draft models in ``k12_commerce_mcp.publishing``. It performs no provider
call, no database access, no filesystem read, and no external write. Missing
values stay missing; nothing is inferred from ordering or zero-filled.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any, TypeVar

from pydantic import ValidationError

from ..models import (
    CanonicalCommonProduct,
    CanonicalProductOption,
    CoupangChannelConfig,
    CoupangPreparedDraft,
    CoupangPreparedItem,
    MarketplaceChannelReadiness,
    MarketplaceReadinessResult,
    NaverChannelConfig,
    NaverPreparedDraft,
    TossChannelConfig,
    TossPreparedDraft,
    TossPreparedStock,
)
from ..models.marketplace_publish import (
    CoupangImageMaterialization,
    TossImageMaterialization,
)
from ..publishing import (
    CoupangCanonicalDraft,
    NaverCanonicalDraft,
    TossCanonicalDraft,
)
from ..security import PiiValueError, assert_agent_safe_value

# Draft top-level fields whose values are sourced from the common product.
# A "missing" error at one of these locations restates a common-level gap.
_TOP_LEVEL_COMMON_SOURCES: dict[str, dict[str, str]] = {
    "coupang": {
        "seller_product_name": "title",
        "delivery_charge": "shipping_fee",
        "items": "options",
    },
    "naver": {
        "name": "title",
        "channel_product_name": "title",
        "detail_content": "description",
        "sale_price": "price",
        "stock_quantity": "options[].stock_quantity",
    },
    "toss": {
        "name": "title",
        "stocks": "options",
        "images": "representative_image_ref",
    },
}

# Option-derived item/stock fields, keyed by the draft list field name.
_ITEM_COMMON_SOURCES: dict[str, tuple[str, dict[str, str]]] = {
    "coupang": (
        "items",
        {
            "item_name": "name",
            "original_price": "price",
            "sale_price": "price",
            "images": "image_refs",
            "contents": "description",
        },
    ),
    "toss": (
        "stocks",
        {
            "options": "name",
            "remaining_count": "stock_quantity",
            "is_sold_out": "stock_quantity",
            "origin_price": "price",
            "sale_price": "price",
            "management_code": "option_ref",
            "images": "image_refs",
        },
    ),
}

_NESTED_COMMON_SOURCES: dict[str, dict[tuple[str, ...], str]] = {
    "toss": {("exposure", "description"): "description"},
}

_MaterializationT = TypeVar(
    "_MaterializationT", CoupangImageMaterialization, TossImageMaterialization
)


def _image_binding_index(
    bindings: Sequence[_MaterializationT],
) -> tuple[dict[str, _MaterializationT], frozenset[str]]:
    """Index bindings by local ref; duplicated refs are ambiguous, not mapped."""
    index: dict[str, _MaterializationT] = {}
    ambiguous: set[str] = set()
    for binding in bindings:
        if binding.image_ref in index or binding.image_ref in ambiguous:
            ambiguous.add(binding.image_ref)
            index.pop(binding.image_ref, None)
        else:
            index[binding.image_ref] = binding
    return index, frozenset(ambiguous)


def _record_image_materialization_gaps(
    refs: Iterable[str],
    image_map: Mapping[str, Any],
    ambiguous: frozenset[str],
    missing_channel: list[str],
    invalid: list[str],
) -> None:
    """Report each referenced local ref that lacks a usable channel binding."""
    for ref in refs:
        if ref in ambiguous:
            invalid.append(f"image_materializations[{ref}]")
        elif ref not in image_map:
            missing_channel.append(f"image_materializations[{ref}]")


def _is_materialization_gap(
    channel: str,
    loc: tuple[Any, ...],
    option_refs: Sequence[str],
    image_blocked_option_refs: frozenset[str],
    product: CanonicalCommonProduct,
) -> bool:
    """True when a missing-image error only restates a reported binding gap.

    The gap itself is already reported as ``image_materializations[<ref>]``;
    echoing it again as a common-level image field would imply the local
    refs themselves are absent, which they are not.
    """
    if channel == "coupang":
        return (
            len(loc) == 3
            and loc[0] == "items"
            and isinstance(loc[1], int)
            and not isinstance(loc[1], bool)
            and loc[2] == "images"
            and loc[1] < len(option_refs)
            and option_refs[loc[1]] in image_blocked_option_refs
        )
    if channel == "toss":
        return loc == ("images",) and bool(product.representative_image_ref)
    return False


def _format_loc(loc: tuple[Any, ...], option_refs: Sequence[str]) -> str:
    if not loc:
        return ""
    parts: list[str] = []
    for part in loc:
        if isinstance(part, int) and not isinstance(part, bool):
            ref = option_refs[part] if part < len(option_refs) else str(part)
            parts[-1] = f"{parts[-1]}[{ref}]"
        else:
            parts.append(str(part))
    return ".".join(parts)


def _map_common_loc(channel: str, loc: tuple[Any, ...], option_refs: Sequence[str]) -> str | None:
    if not loc:
        return None
    nested = _NESTED_COMMON_SOURCES.get(channel, {})
    if loc in nested:
        return nested[loc]
    item_spec = _ITEM_COMMON_SOURCES.get(channel)
    if (
        item_spec is not None
        and loc[0] == item_spec[0]
        and len(loc) >= 3
        and isinstance(loc[1], int)
        and not isinstance(loc[1], bool)
    ):
        mapped = item_spec[1].get(str(loc[-1]))
        if mapped is None:
            return None
        ref = option_refs[loc[1]] if loc[1] < len(option_refs) else str(loc[1])
        return f"options[{ref}].{mapped}"
    if len(loc) == 1:
        return _TOP_LEVEL_COMMON_SOURCES.get(channel, {}).get(str(loc[0]))
    return None


def _missing_common_fields(
    product: CanonicalCommonProduct, *, require_option_images: bool
) -> list[str]:
    missing: list[str] = []
    if not product.title:
        missing.append("title")
    if product.price is None:
        missing.append("price")
    if not product.description:
        missing.append("description")
    if product.shipping_fee is None:
        missing.append("shipping_fee")
    if not product.representative_image_ref:
        missing.append("representative_image_ref")
    if not product.options:
        missing.append("options")
    for option in product.options:
        prefix = f"options[{option.option_ref}]"
        if not option.name:
            missing.append(f"{prefix}.name")
        if option.price is None:
            missing.append(f"{prefix}.price")
        if option.stock_quantity is None:
            missing.append(f"{prefix}.stock_quantity")
        if require_option_images and not option.image_refs:
            missing.append(f"{prefix}.image_refs")
    return missing


def _coupang_item(
    option: CanonicalProductOption,
    item_defaults: Mapping[str, Any] | None,
    description: str | None,
    image_map: Mapping[str, CoupangImageMaterialization],
) -> dict[str, Any]:
    item = dict(item_defaults or {})
    if option.name:
        item["item_name"] = option.name
    if option.price is not None:
        item["original_price"] = option.price
        item["sale_price"] = option.price
    item["external_vendor_sku"] = option.option_ref
    images: list[dict[str, Any]] = []
    for index, ref in enumerate(option.image_refs):
        binding = image_map.get(ref)
        if binding is None:
            continue
        image: dict[str, Any] = {
            "image_order": index,
            "image_type": "REPRESENTATION" if index == 0 else "DETAIL",
        }
        if binding.vendor_path is not None:
            image["vendor_path"] = binding.vendor_path
        else:
            image["cdn_path"] = binding.cdn_path
        images.append(image)
    if images:
        item["images"] = images
    if description:
        item["contents"] = [
            {
                "contents_type": "TEXT",
                "content_details": [{"content": description, "detail_type": "TEXT"}],
            }
        ]
    return item


def _coupang_payload(
    product: CanonicalCommonProduct,
    config: CoupangChannelConfig,
    image_map: Mapping[str, CoupangImageMaterialization],
) -> dict:
    payload = config.model_dump(mode="python", exclude_none=True)
    payload.pop("channel", None)
    payload.pop("image_materializations", None)
    item_defaults = payload.pop("item_defaults", None)
    if not payload.get("seller_product_name") and product.title:
        payload["seller_product_name"] = product.title
    if payload.get("delivery_charge") is None and product.shipping_fee is not None:
        payload["delivery_charge"] = product.shipping_fee
    if product.options:
        payload["items"] = [
            _coupang_item(option, item_defaults, product.description, image_map)
            for option in product.options
        ]
    payload["channel"] = "coupang"
    return payload


def _coupang_preview(draft: CoupangCanonicalDraft) -> CoupangPreparedDraft:
    items = []
    for item in draft.items:
        if not item.external_vendor_sku:
            raise ValueError("coupang item is missing its option_ref binding")
        image_refs = tuple(
            image.vendor_path or image.cdn_path or ""
            for image in sorted(item.images, key=lambda value: value.image_order)
        )
        items.append(
            CoupangPreparedItem(
                option_ref=item.external_vendor_sku,
                item_name=item.item_name,
                sale_price=item.sale_price,
                image_refs=image_refs,
            )
        )
    return CoupangPreparedDraft(
        seller_product_name=draft.seller_product_name,
        items=tuple(items),
    )


def _total_stock(product: CanonicalCommonProduct) -> int | None:
    if not product.options:
        return None
    if any(option.stock_quantity is None for option in product.options):
        return None
    return sum(option.stock_quantity or 0 for option in product.options)


def _naver_payload(product: CanonicalCommonProduct, config: NaverChannelConfig) -> dict:
    payload = config.model_dump(mode="python", exclude_none=True)
    payload.pop("channel", None)
    derived = {
        "status_type": "SALE",
        "name": product.title or None,
        "channel_product_name": product.title or None,
        "detail_content": product.description or None,
        "sale_price": product.price,
        "stock_quantity": _total_stock(product),
    }
    for key, value in derived.items():
        if payload.get(key) in (None, "") and value is not None:
            payload[key] = value
    payload["channel"] = "naver"
    return payload


def _naver_preview(draft: NaverCanonicalDraft) -> NaverPreparedDraft:
    return NaverPreparedDraft(
        name=draft.name,
        leaf_category_id=draft.leaf_category_id,
        sale_price=draft.sale_price,
        stock_quantity=draft.stock_quantity,
        image_storage_ref=draft.image_storage_ref,
    )


def _toss_stock(
    option: CanonicalProductOption,
    *,
    is_main: bool,
    image_map: Mapping[str, TossImageMaterialization],
) -> dict[str, Any]:
    stock: dict[str, Any] = {
        "is_hide": False,
        "is_main_price": is_main,
        "management_code": option.option_ref,
    }
    if option.name:
        stock["options"] = [{"group_name": "option", "value_name": option.name}]
    if option.price is not None:
        stock["origin_price"] = option.price
        stock["sale_price"] = option.price
    if option.stock_quantity is not None:
        stock["remaining_count"] = option.stock_quantity
        stock["is_sold_out"] = option.stock_quantity == 0
    images = [
        {"url": binding.url, "order": index}
        for index, ref in enumerate(option.image_refs)
        if (binding := image_map.get(ref)) is not None
    ]
    if images:
        stock["images"] = images
    return stock


def _toss_payload(
    product: CanonicalCommonProduct,
    config: TossChannelConfig,
    image_map: Mapping[str, TossImageMaterialization],
) -> dict:
    payload = config.model_dump(mode="python", exclude_none=True)
    payload.pop("channel", None)
    payload.pop("image_materializations", None)
    main_option_ref = payload.pop("main_option_ref", None)
    additional_images = payload.pop("additional_images", ())
    if not payload.get("name") and product.title:
        payload["name"] = product.title
    exposure = dict(payload.get("exposure") or {})
    if not exposure.get("description") and product.description:
        exposure["description"] = product.description
    if exposure:
        payload["exposure"] = exposure
    if product.options:
        main_ref = main_option_ref or product.options[0].option_ref
        payload["stocks"] = [
            _toss_stock(option, is_main=option.option_ref == main_ref, image_map=image_map)
            for option in product.options
        ]
    images: list[dict[str, Any]] = []
    representative = image_map.get(product.representative_image_ref or "")
    if representative is not None:
        images.append({"type": "THUMBNAIL", "url": representative.url, "order": 0})
    order = len(images)
    for ref in product.gallery_image_refs:
        binding = image_map.get(ref)
        if binding is None:
            continue
        images.append({"type": "DESCRIPTION", "url": binding.url, "order": order})
        order += 1
    if product.description:
        images.append({"type": "DESCRIPTION_HTML", "html": product.description, "order": order})
        order += 1
    for extra in additional_images:
        entry = dict(extra)
        entry.setdefault("order", order)
        images.append(entry)
        order += 1
    if images:
        payload["images"] = images
    payload["channel"] = "toss"
    return payload


def _toss_preview(draft: TossCanonicalDraft) -> TossPreparedDraft:
    stocks = []
    for stock in draft.stocks:
        if not stock.management_code:
            raise ValueError("toss stock is missing its option_ref binding")
        image_refs = tuple(
            image.url or "" for image in sorted(stock.images or (), key=lambda value: value.order)
        )
        stocks.append(
            TossPreparedStock(
                option_ref=stock.management_code,
                remaining_count=stock.remaining_count,
                sale_price=stock.sale_price,
                is_main_price=stock.is_main_price,
                image_refs=image_refs,
            )
        )
    image_refs = tuple(image.url for image in draft.images if image.url)
    return TossPreparedDraft(
        name=draft.name,
        category_id=draft.category_id,
        stocks=tuple(stocks),
        image_refs=image_refs,
    )


class MarketplaceReadinessService:
    """Evaluate publish readiness locally; owns no provider or DB handles."""

    def __init__(self, *, external_execution: Mapping[str, bool] | None = None) -> None:
        self._external_execution = dict(external_execution or {})

    def evaluate(
        self,
        product: CanonicalCommonProduct,
        channel_configs: Sequence[CoupangChannelConfig | NaverChannelConfig | TossChannelConfig],
    ) -> MarketplaceReadinessResult:
        entries = []
        seen: set[str] = set()
        for config in channel_configs:
            if config.channel in seen:
                continue
            seen.add(config.channel)
            entries.append(self._evaluate_channel(product, config))
        return MarketplaceReadinessResult(channels=tuple(entries))

    def _evaluate_channel(
        self,
        product: CanonicalCommonProduct,
        config: CoupangChannelConfig | NaverChannelConfig | TossChannelConfig,
    ) -> MarketplaceChannelReadiness:
        channel: str = config.channel
        option_refs = [option.option_ref for option in product.options]
        missing_channel: list[str] = []
        invalid: list[str] = []
        image_blocked_option_refs: frozenset[str] = frozenset()
        if isinstance(config, CoupangChannelConfig):
            image_map, ambiguous_refs = _image_binding_index(config.image_materializations)
            payload = _coupang_payload(product, config, image_map)
            draft_model: Any = CoupangCanonicalDraft
            preview_builder = _coupang_preview
            require_option_images = True
            _record_image_materialization_gaps(
                (ref for option in product.options for ref in option.image_refs),
                image_map,
                ambiguous_refs,
                missing_channel,
                invalid,
            )
            image_blocked_option_refs = frozenset(
                option.option_ref
                for option in product.options
                if option.image_refs
                and all(ref not in image_map for ref in option.image_refs)
            )
        elif isinstance(config, NaverChannelConfig):
            payload = _naver_payload(product, config)
            draft_model = NaverCanonicalDraft
            preview_builder = _naver_preview
            require_option_images = False
        else:
            image_map, ambiguous_refs = _image_binding_index(config.image_materializations)
            payload = _toss_payload(product, config, image_map)
            draft_model = TossCanonicalDraft
            preview_builder = _toss_preview
            require_option_images = False
            image_refs: list[str] = list(product.gallery_image_refs)
            if product.representative_image_ref:
                image_refs.insert(0, product.representative_image_ref)
            image_refs.extend(ref for option in product.options for ref in option.image_refs)
            _record_image_materialization_gaps(
                image_refs,
                image_map,
                ambiguous_refs,
                missing_channel,
                invalid,
            )

        missing_common = _missing_common_fields(
            product, require_option_images=require_option_images
        )
        if len(option_refs) != len(set(option_refs)):
            invalid.append("options.option_ref")

        prepared = None
        try:
            draft = draft_model.model_validate(payload)
            prepared = preview_builder(draft)
        except ValidationError as exc:
            errors = exc.errors()
            roots_with_nested = {error["loc"][0] for error in errors if len(error["loc"]) > 1}
            for error in errors:
                loc = tuple(error["loc"])
                if len(loc) == 1 and error["type"] != "missing" and loc[0] in roots_with_nested:
                    continue
                if error["type"] == "missing" and _is_materialization_gap(
                    channel, loc, option_refs, image_blocked_option_refs, product
                ):
                    continue
                if error["type"] == "missing":
                    mapped = _map_common_loc(channel, loc, option_refs)
                    if mapped is not None:
                        if mapped not in missing_common:
                            missing_common.append(mapped)
                    else:
                        missing_channel.append(_format_loc(loc, option_refs))
                else:
                    invalid.append(_format_loc(loc, option_refs) or str(error["msg"]))
        except (TypeError, ValueError):
            invalid.append("prepared_draft")

        ready = prepared is not None and not missing_common and not missing_channel and not invalid
        entry = MarketplaceChannelReadiness(
            channel=channel,
            ready=ready,
            missing_common_fields=tuple(dict.fromkeys(missing_common)),
            missing_channel_fields=tuple(dict.fromkeys(missing_channel)),
            invalid_fields=tuple(dict.fromkeys(invalid)),
            external_execution_configured=bool(self._external_execution.get(channel, False)),
            prepared_draft=prepared if ready else None,
        )
        try:
            assert_agent_safe_value(entry)
        except PiiValueError:
            entry = MarketplaceChannelReadiness(
                channel=channel,
                ready=False,
                missing_common_fields=entry.missing_common_fields,
                missing_channel_fields=entry.missing_channel_fields,
                invalid_fields=(*entry.invalid_fields, "agent_unsafe_output"),
                external_execution_configured=entry.external_execution_configured,
                prepared_draft=None,
            )
        return entry
