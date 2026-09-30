"""Coupang product, detail, content, and catalog-metadata reads."""

from __future__ import annotations

from datetime import UTC, date
from typing import Any

from ...models import (
    Channel,
    Completeness,
    Product,
    ProductAttribute,
    ProductContent,
    ProductDetail,
    ResultStatus,
)
from ...models.products import ProductOption
from ...product_images import coupang_branches, coupang_image_refs, coupang_images
from ...product_options import money, option_completeness, option_id
from ..base import AdapterFailure, AdapterInvalidResponseError
from ..mock import MockPage
from .mapper import (
    _detail_text,
    _first_string,
    _product_state,
    _project,
)

_BRAND_NAME_KEYS = ("name", "brandName", "brand", "koreanName")


def _has_rocket_growth_item(row: dict[str, Any]) -> bool:
    """Do not label a marketplace-only or unclassifiable product as RG."""
    items = row.get("items")
    return isinstance(items, list) and any(
        isinstance(item, dict)
        and any(
            isinstance(item.get(key), dict)
            for key in ("rocketGrowthItemData", "rocketGrowthItem")
        )
        for item in items
    )

_CATEGORY_NAME_KEYS = (
    "name",
    "displayCategoryName",
    "categoryName",
    "wholeCategoryName",
)
_PRODUCT_LIST_KEYS = (
    "sellerProductId",
    "sellerProductName",
    "statusName",
    "displayCategoryCode",
    "brandId",
    "externalVendorSkuCode",
    "createdAt",
    "updatedAt",
)
_PRODUCT_HISTORY_KEYS = (
    "sellerProductId",
    "status",
    "statusName",
    "approvalStatus",
    "comment",
    "createdAt",
    "updatedAt",
    "modifiedAt",
)
_CATEGORY_KEYS = (
    "displayCategoryCode",
    "displayCategoryName",
    "name",
    "categoryName",
    "usable",
    "status",
)
_CATEGORY_STATUS_KEYS = ("displayCategoryCode", "status", "usable", "writable")
_CATEGORY_META_KEYS = (
    "displayCategoryCode",
    "metaType",
    "metaKey",
    "required",
    "dataType",
)
_BRAND_KEYS = ("brandId", "name", "brandName", "brand", "koreanName", "englishName")


class CoupangProductsMixin:
    async def get_products(
        self,
        *,
        page_size: int,
        cursor: str | None = None,
    ) -> MockPage[Product]:
        rocket_growth = self.channel == "coupang_rocket_growth"
        page = await self.client.list_seller_products(
            page_size=page_size,
            next_token=cursor,
            **({"rocket_growth": True} if rocket_growth else {}),
        )
        observed_at = self._clock().astimezone(UTC)
        products = []
        for row in page.rows:
            if rocket_growth and not _has_rocket_growth_item(row):
                raise AdapterInvalidResponseError("RG product scope cannot be verified")
            seller_product_id = row.get("sellerProductId")
            name = row.get("sellerProductName")
            if seller_product_id is None or not isinstance(name, str) or not name.strip():
                continue
            products.append(
                Product(
                    channel=Channel(self.channel),
                    external_product_id=str(seller_product_id),
                    external_option_id=None,
                    master_sku=None,
                    name=name,
                    state=_product_state(row.get("statusName")),
                    listing_price=None,
                    completeness=Completeness(
                        status=ResultStatus.INCOMPLETE,
                        missing_fields=("external_option_id", "master_sku", "listing_price"),
                        reasons=("seller_products_list_does_not_supply_option_price",),
                    ),
                    source=self._source(
                        observed_at,
                        (
                            "coupang:rg-seller-products"
                            if rocket_growth else "coupang:seller-products"
                        ),
                        "provider_listing_identity",
                    ),
                )
            )
        return MockPage(items=tuple(products), next_cursor=page.next_token)

    async def _read_product(self, external_product_id: str) -> dict[str, Any] | None:
        row = await self.client.get_seller_product(external_product_id)
        if self.channel == "coupang_rocket_growth":
            return row if row is not None and _has_rocket_growth_item(row) else None
        return row

    async def _enriched_brand_name(self, row: dict[str, Any]) -> str | None:
        brand = row.get("brand")
        if isinstance(brand, str) and brand.strip():
            return brand
        brand_id = row.get("brandId")
        if brand_id is None or not str(brand_id).isdigit():
            return None
        try:
            payload = await self.client.get_brand(str(brand_id))
        except AdapterFailure:
            return None
        return _first_string(payload, _BRAND_NAME_KEYS) if payload else None

    async def _enriched_category_name(self, row: dict[str, Any]) -> str | None:
        category = row.get("productGroup")
        if isinstance(category, str) and category.strip():
            return category
        code = row.get("displayCategoryCode")
        if code is None or not str(code).isdigit():
            return None
        try:
            payload = await self.client.get_display_category(str(code))
        except AdapterFailure:
            return None
        return _first_string(payload, _CATEGORY_NAME_KEYS) if payload else None

    async def _linked_options(
        self,
        row: dict[str, Any],
        product_id: str,
        *,
        include_inventory: bool = False,
    ) -> tuple[ProductOption, ...]:
        branches = coupang_branches(row, self.channel)
        images, _withheld = coupang_images(row, self.channel)
        result = []
        seen: set[str] = set()
        for branch in branches:
            identifier = option_id(branch.get("vendorItemId"))
            if identifier is None:
                if branch.get("vendorItemId") is not None:
                    raise AdapterInvalidResponseError("option identity is invalid")
                continue  # Unapproved item has no vendor item; never invent one.
            if identifier in seen:
                raise AdapterInvalidResponseError("duplicate option identity")
            seen.add(identifier)
            name = branch.get("itemName")
            name = name if isinstance(name, str) and name.strip() else None
            price = money(branch.get("salePrice"))
            price_data = branch.get("priceData")
            if price_data is not None and not isinstance(price_data, dict):
                raise AdapterInvalidResponseError("option price data is invalid")
            nested_price = (
                money(price_data.get("salePrice")) if isinstance(price_data, dict) else None
            )
            if price is not None and nested_price is not None and price != nested_price:
                raise AdapterInvalidResponseError("option price fields conflict")
            price = nested_price if nested_price is not None else price
            price_source = (
                self._source(
                    self._clock().astimezone(UTC),
                    "coupang:seller-product-detail",
                    "provider_option_sale_price",
                )
                if price is not None
                else None
            )
            option_images = tuple(
                dict.fromkeys(
                    image.url
                    for image in images
                    if image.external_option_id == identifier and image.role != "detail"
                )
            )
            attributes = []
            raw_attributes = branch.get("attributes", [])
            if not isinstance(raw_attributes, list) or len(raw_attributes) > 30:
                raise AdapterInvalidResponseError("option attributes are invalid")
            for attribute in raw_attributes:
                if not isinstance(attribute, dict):
                    raise AdapterInvalidResponseError("option attribute row is invalid")
                key, value = attribute.get("attributeTypeName"), attribute.get("attributeValueName")
                if isinstance(key, str) and isinstance(value, str) and key and value:
                    attributes.append(ProductAttribute(name=key, value=value))
            quantity = None
            quantity_source = None
            scope = None
            reasons: list[str] = []
            rg = self.channel == "coupang_rocket_growth"
            reader = getattr(
                self.client, "list_rg_inventory" if rg else "get_vendor_item_inventories", None
            )
            # Bound additional GET fanout; missing stock is explicit, never 0.
            if not include_inventory:
                reasons.append("option_stock_read_not_requested")
            elif reader is None or len(result) >= 100:
                reasons.append(
                    "option_stock_reader_unavailable"
                    if reader is None
                    else "option_stock_read_budget_exceeded"
                )
            else:
                try:
                    payload = (
                        await reader(next_token=None, vendor_item_id=identifier)
                        if rg
                        else await reader(identifier)
                    )
                except AdapterInvalidResponseError:
                    raise
                except AdapterFailure:
                    payload = None
                    reasons.append("option_stock_read_unavailable")
                if payload is not None:
                    if rg:
                        rows = payload.rows
                        if payload.next_token is not None or len(rows) > 1:
                            raise AdapterInvalidResponseError(
                                "RG option stock filter is incomplete"
                            )
                        stock = rows[0] if rows else None
                        if stock is not None and (
                            not isinstance(stock, dict)
                            or option_id(stock.get("vendorItemId")) != identifier
                        ):
                            raise AdapterInvalidResponseError("RG stock option mismatch")
                        detail = stock.get("inventoryDetails") if isinstance(stock, dict) else None
                        raw_quantity = (
                            detail.get("totalOrderableQuantity")
                            if isinstance(detail, dict)
                            else None
                        )
                    else:
                        if not isinstance(payload, dict):
                            raise AdapterInvalidResponseError("listing stock shape is invalid")
                        echo = payload.get("vendorItemId")
                        if echo is not None and option_id(echo) != identifier:
                            raise AdapterInvalidResponseError("listing stock option mismatch")
                        raw_quantity = payload.get("amountInStock")
                        inventory_price = money(payload.get("salePrice"))
                        if inventory_price is not None:
                            price = inventory_price
                            price_source = self._source(
                                self._clock().astimezone(UTC),
                                "coupang:vendor-item-inventories",
                                "provider_option_sale_price",
                            )
                    if raw_quantity is not None:
                        if type(raw_quantity) is not int or not 0 <= raw_quantity <= 99_999_999:
                            raise AdapterInvalidResponseError("option stock quantity is invalid")
                        quantity = raw_quantity
                        scope = "fulfillment_orderable" if rg else "listing_quantity"
                        quantity_source = self._source(
                            self._clock().astimezone(UTC),
                            "coupang:rg/inventory/summaries"
                            if rg
                            else "coupang:vendor-item-inventories",
                            "provider_fulfillment_orderable_quantity"
                            if rg
                            else "provider_listing_quantity",
                        )
            if quantity is None:
                reasons.append("option_quantity_not_observed")
            result.append(
                ProductOption(
                    channel=Channel(self.channel),
                    external_product_id=product_id,
                    external_option_id=identifier,
                    name=name,
                    attributes=tuple(attributes),
                    listing_price=price,
                    price_source=price_source,
                    price_basis="provider_item_sale_price" if price is not None else None,
                    quantity=quantity,
                    quantity_scope=scope,
                    quantity_source=quantity_source,
                    image_urls=option_images,
                    completeness=option_completeness(
                        name, price, quantity, option_images, tuple(reasons)
                    ),
                    source=self._source(
                        self._clock().astimezone(UTC),
                        "coupang:seller-product-detail",
                        "provider_option_fields",
                    ),
                )
            )
        return tuple(result)

    async def get_product_detail_with_option_inventory(
        self,
        external_product_id: str,
    ) -> ProductDetail | None:
        return await self.get_product_detail(external_product_id, include_option_inventory=True)

    async def get_product_detail(
        self,
        external_product_id: str,
        *,
        include_option_inventory: bool = False,
    ) -> ProductDetail | None:
        row = await self._read_product(external_product_id)
        if row is None or str(row.get("sellerProductId")) != external_product_id:
            return None
        observed_at = self._clock().astimezone(UTC)
        option_records = await self._linked_options(
            row,
            external_product_id,
            include_inventory=include_option_inventory,
        )
        option_ids = [option.external_option_id for option in option_records]
        attributes = [attribute for option in option_records for attribute in option.attributes]
        name = row.get("sellerProductName")
        if not isinstance(name, str) or not name.strip():
            return None
        brand_name = await self._enriched_brand_name(row)
        category = await self._enriched_category_name(row)
        model_name = row.get("generalProductName")
        missing = ["master_sku"]
        if not option_records:
            missing.append("options")
        if not option_ids:
            missing.append("external_option_ids")
        for field, value in (
            ("brand_name", brand_name),
            ("category_name", category),
            ("model_name", model_name),
        ):
            if not isinstance(value, str) or not value.strip():
                missing.append(field)
        return ProductDetail(
            channel=Channel(self.channel),
            external_product_id=external_product_id,
            external_option_ids=tuple(dict.fromkeys(option_ids)),
            options=option_records,
            master_sku=None,
            name=name,
            state=_product_state(row.get("statusName")),
            brand_name=brand_name,
            category_name=category if isinstance(category, str) else None,
            model_name=model_name if isinstance(model_name, str) else None,
            attributes=tuple(dict.fromkeys(attributes)),
            completeness=Completeness(
                status=ResultStatus.INCOMPLETE,
                missing_fields=tuple(missing),
                reasons=("master_sku_link_not_verified",),
            ),
            source=self._source(
                observed_at,
                "coupang:seller-product-detail",
                "provider_product_detail",
            ),
        )

    async def get_product_content(self, external_product_id: str) -> ProductContent | None:
        row = await self._read_product(external_product_id)
        if row is None or str(row.get("sellerProductId")) != external_product_id:
            return None
        title = row.get("sellerProductName")
        if not isinstance(title, str) or not title.strip():
            return None
        observed_at = self._clock().astimezone(UTC)
        scoped_row = {"items": list(coupang_branches(row, self.channel))}
        description = _detail_text(scoped_row)
        role_images, image_withheld = coupang_images(row, self.channel)
        images = tuple(dict.fromkeys(image.url for image in role_images if image.role != "detail"))
        missing = []
        if description is None:
            missing.append("description_text")
        if not images:
            missing.append("image_urls")
        if image_withheld:
            missing.append("images")
        status = ResultStatus.COMPLETE if not missing else ResultStatus.INCOMPLETE
        return ProductContent(
            channel=Channel(self.channel),
            external_product_id=external_product_id,
            title=title,
            description_text=description,
            image_urls=images,
            images=role_images,
            image_refs=coupang_image_refs(row, self.channel),
            completeness=Completeness(
                status=status,
                missing_fields=tuple(missing),
                reasons=("provider_content_fields_missing",) if missing else (),
            ),
            source=self._source(
                observed_at,
                "coupang:seller-product-detail",
                "provider_detail_content",
            ),
        )

    async def read_seller_product_histories(
        self,
        seller_product_id: str,
        *,
        page_size: int = 50,
        cursor: str | None = None,
    ) -> MockPage[dict[str, Any]]:
        page = await self.client.list_seller_product_histories(
            seller_product_id,
            page_size=page_size,
            next_token=cursor,
        )
        return MockPage(
            items=tuple(
                _project(row, _PRODUCT_HISTORY_KEYS) for row in page.rows
            ),
            next_cursor=page.next_token,
        )

    async def read_products_time_frame(
        self,
        *,
        date_from: date,
        date_to: date,
        page_size: int = 50,
        cursor: str | None = None,
    ) -> MockPage[dict[str, Any]]:
        page = await self.client.list_seller_products_time_frame(
            date_from=date_from,
            date_to=date_to,
            page_size=page_size,
            next_token=cursor,
        )
        return MockPage(
            items=tuple(_project(row, _PRODUCT_LIST_KEYS) for row in page.rows),
            next_cursor=page.next_token,
        )

    async def read_products_inflow_status(
        self,
        *,
        inflow_status: str = "ALL",
        page_size: int = 50,
        cursor: str | None = None,
    ) -> MockPage[dict[str, Any]]:
        page = await self.client.list_seller_products_inflow_status(
            inflow_status=inflow_status,
            page_size=page_size,
            next_token=cursor,
        )
        return MockPage(
            items=tuple(_project(row, _PRODUCT_LIST_KEYS) for row in page.rows),
            next_cursor=page.next_token,
        )

    async def read_product_by_external_sku(
        self,
        external_vendor_sku_code: str,
    ) -> dict[str, Any] | None:
        row = await self.client.get_seller_product_by_external_sku(
            external_vendor_sku_code
        )
        return _project(row, _PRODUCT_LIST_KEYS) if row is not None else None

    async def read_display_categories(
        self,
        *,
        keyword: str | None = None,
    ) -> tuple[dict[str, Any], ...]:
        rows = await self.client.list_display_categories(keyword=keyword)
        return tuple(_project(row, _CATEGORY_KEYS) for row in rows)

    async def read_display_category(
        self,
        display_category_code: str,
    ) -> dict[str, Any] | None:
        row = await self.client.get_display_category(display_category_code)
        return _project(row, _CATEGORY_KEYS) if row is not None else None

    async def read_display_category_status(
        self,
        display_category_code: str,
    ) -> dict[str, Any] | None:
        row = await self.client.get_display_category_status(display_category_code)
        return _project(row, _CATEGORY_STATUS_KEYS) if row is not None else None

    async def read_display_category_related_metas(
        self,
        display_category_code: str,
    ) -> dict[str, Any] | None:
        row = await self.client.get_display_category_related_metas(
            display_category_code
        )
        return _project(row, _CATEGORY_META_KEYS) if row is not None else None

    async def read_brand(self, brand_id: str) -> dict[str, Any] | None:
        row = await self.client.get_brand(brand_id)
        return _project(row, _BRAND_KEYS) if row is not None else None
