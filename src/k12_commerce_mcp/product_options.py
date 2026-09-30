"""Pure projections that keep each provider option's fields together."""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from .adapters.base import AdapterInvalidResponseError
from .image_assets import IMAGE_ASSETS, ImageAssetError
from .models.common import Channel, Completeness, Money, ResultStatus, SourceEvidence
from .models.products import (
    ProductAttribute,
    ProductImageReference,
    ProductOption,
    ProductOptionImageGroup,
)
from .security import is_agent_safe_value


def option_id(value: object) -> str | None:
    if type(value) is int and 0 < value < 10**20:
        return str(value)
    if isinstance(value, str) and re.fullmatch(r"[0-9]{1,20}", value) and int(value) > 0:
        return value
    return None


def integer(value: object, *, negative: bool = False) -> int | None:
    if value is None:
        return None
    if type(value) is not int or not (-999_999_990 if negative else 0) <= value <= 999_999_990:
        raise AdapterInvalidResponseError("option number is invalid")
    return value


def money(value: object, *, negative: bool = False) -> Money | None:
    amount = integer(value, negative=negative)
    return Money(amount=Decimal(amount), currency="KRW") if amount is not None else None


def option_completeness(
    name: str | None,
    price: Money | None,
    quantity: int | None,
    images: tuple[str, ...],
    reasons: tuple[str, ...] = (),
) -> Completeness:
    missing = [
        key
        for key, value in (
            ("name", name),
            ("listing_price", price),
            ("quantity", quantity),
        )
        if value is None
    ]
    if not images:
        missing.append("image_urls")
    missing.append("master_sku")
    return Completeness(
        status=ResultStatus.INCOMPLETE,
        missing_fields=tuple(missing),
        reasons=tuple(dict.fromkeys(("master_sku_link_not_verified", *reasons))),
    )


def naver_option_image_groups(
    origin: dict[str, Any] | None,
    source: SourceEvidence,
) -> tuple[ProductOptionImageGroup, ...]:
    detail = origin.get("detailAttribute") if isinstance(origin, dict) else None
    info = detail.get("optionInfo") if isinstance(detail, dict) else None
    if not isinstance(info, dict):
        return ()
    groups = info.get("standardOptionGroups", [])
    if not isinstance(groups, list) or len(groups) > 4:
        raise AdapterInvalidResponseError("option image groups exceed shape or bound")
    result = []
    seen = set()
    total_images = 0
    for group in groups:
        if not isinstance(group, dict) or not isinstance(group.get("groupName"), str):
            raise AdapterInvalidResponseError("option image group is invalid")
        attributes = group.get("standardOptionAttributes", [])
        if not isinstance(attributes, list) or len(attributes) > 100:
            raise AdapterInvalidResponseError("option image attributes exceed shape or bound")
        for attribute in attributes:
            if not isinstance(attribute, dict):
                raise AdapterInvalidResponseError("option image attribute is invalid")
            aid, vid = (
                option_id(attribute.get("attributeId")),
                option_id(attribute.get("attributeValueId")),
            )
            name = attribute.get("attributeValueName")
            key = (group["groupName"], aid, vid)
            if (
                aid is None
                or vid is None
                or not isinstance(name, str)
                or not name.strip()
                or key in seen
            ):
                raise AdapterInvalidResponseError("option image attribute identity is invalid")
            seen.add(key)
            urls = attribute.get("imageUrls", [])
            if (
                not isinstance(urls, list)
                or len(urls) > 100
                or any(
                    not isinstance(u, str) or not u.startswith("https://") or len(u) > 2048
                    for u in urls
                )
            ):
                raise AdapterInvalidResponseError("option image locations are invalid")
            urls = tuple(dict.fromkeys(urls))
            total_images += len(urls)
            if total_images > 100 or len(seen) > 100:
                raise AdapterInvalidResponseError("option image count exceeds bound")
            visible, refs = [], []
            for url in urls:
                try:
                    ref = IMAGE_ASSETS.register(url)
                except ImageAssetError:
                    ref = None
                if is_agent_safe_value(url):
                    visible.append(url)
                elif ref is None:
                    raise AdapterInvalidResponseError("option image is not agent-safe")
                if ref is not None:
                    refs.append(ProductImageReference(asset_ref=ref, role="option"))
            result.append(
                ProductOptionImageGroup(
                    group_name=group["groupName"],
                    attribute_id=aid,
                    attribute_value_id=vid,
                    attribute_value_name=name,
                    image_urls=tuple(visible),
                    image_refs=tuple(refs),
                    source=source,
                )
            )
    return tuple(result)


def naver_options(
    origin: dict[str, Any] | None,
    product_id: str,
    source: SourceEvidence,
) -> tuple[ProductOption, ...]:
    if not isinstance(origin, dict):
        return ()
    detail = origin.get("detailAttribute")
    info = detail.get("optionInfo") if isinstance(detail, dict) else None
    if not isinstance(info, dict):
        return ()
    base_price = money(origin.get("salePrice"))
    result: list[ProductOption] = []
    seen: set[str] = set()
    active_kinds = [
        kind for kind in ("optionCombinations", "optionStandards", "optionSimple") if info.get(kind)
    ]
    if len(active_kinds) > 1:
        raise AdapterInvalidResponseError("mutually exclusive option types conflict")
    for kind in active_kinds:
        rows = info[kind]
        if not isinstance(rows, list) or len(rows) > 300:
            raise AdapterInvalidResponseError("option rows exceed shape or bound")
        groups = info.get("optionCombinationGroupNames")
        for row in rows:
            if not isinstance(row, dict):
                raise AdapterInvalidResponseError("option row is invalid")
            identifier = option_id(row.get("id"))
            if identifier is None or identifier in seen:
                raise AdapterInvalidResponseError("option identity is missing or duplicate")
            seen.add(identifier)
            attributes: list[ProductAttribute] = []
            values: list[str] = []
            if kind == "optionSimple":
                name = row.get("name")
                group = row.get("groupName")
                if isinstance(name, str) and name.strip():
                    values.append(name)
                    if isinstance(group, str) and group.strip():
                        attributes.append(ProductAttribute(name=group, value=name))
            else:
                for index in range(1, 5):
                    value = row.get(f"optionName{index}")
                    if isinstance(value, str) and value.strip():
                        values.append(value)
                        group = (
                            groups.get(f"optionGroupName{index}")
                            if isinstance(groups, dict)
                            else None
                        )
                        if isinstance(group, str) and group.strip():
                            attributes.append(ProductAttribute(name=group, value=value))
            name = " / ".join(values) or None
            observed_stock = integer(row.get("stockQuantity"))
            if observed_stock is not None and observed_stock > 99_999_999:
                raise AdapterInvalidResponseError("option quantity exceeds bound")
            quantity = (
                observed_stock
                if info.get("useStockManagement") is True and kind != "optionSimple"
                else None
            )
            component = (
                money(row.get("price"), negative=True) if kind == "optionCombinations" else None
            )
            # Do not turn Naver's provider option price into a final customer price.
            # Base sale price and option component are separate observed fields.
            price = base_price if kind != "optionCombinations" else None
            usable = row.get("usable")
            if usable is not None and type(usable) is not bool:
                raise AdapterInvalidResponseError("option usability is invalid")
            result.append(
                ProductOption(
                    channel=Channel.NAVER,
                    external_product_id=product_id,
                    external_option_id=identifier,
                    name=name,
                    attributes=tuple(attributes),
                    listing_price=price,
                    base_listing_price=base_price,
                    provider_option_price=component,
                    price_source=source
                    if price is not None or component is not None or base_price is not None
                    else None,
                    price_basis="provider_option_price_component"
                    if kind == "optionCombinations"
                    else "shared_product_sale_price"
                    if price is not None
                    else None,
                    quantity=quantity,
                    quantity_scope="listing_quantity" if quantity is not None else None,
                    quantity_source=source if quantity is not None else None,
                    image_urls=(),
                    usable=usable,
                    completeness=option_completeness(
                        name,
                        price,
                        quantity,
                        (),
                        (
                            "option_image_identifier_link_unavailable",
                            *(
                                ("provider_option_price_is_component",)
                                if kind == "optionCombinations"
                                else ()
                            ),
                        ),
                    ),
                    source=source,
                )
            )
    return tuple(result)
