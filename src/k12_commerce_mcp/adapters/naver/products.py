"""Naver product detail and content reads."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from ...clients.naver import NaverProviderError, NaverRequestError
from ...currency_policy import POLICY_CONFIRMED_KRW_BASIS, currency_for_channel
from ...image_assets import IMAGE_ASSETS, ImageAssetError
from ...models import (
    Channel,
    Completeness,
    Money,
    NaverClaimDeliveryPolicy,
    NaverClaimDeliveryPolicyCandidate,
    NaverDeliveryFeeByArea,
    NaverDeliveryFeePolicy,
    NaverDeliveryFeePolicyCandidate,
    NaverDeliveryPolicyTemplate,
    NaverDeliveryPolicyTemplateCandidate,
    Product,
    ProductContent,
    ProductDetail,
    ResultStatus,
)
from ...models.products import ProductImage, ProductImageReference
from ...product_images import body_images, body_reference_urls, unique_images
from ...product_options import naver_option_image_groups, naver_options
from ...security import UNSAFE_VALUE_PATTERNS, is_agent_safe_value
from ..base import (
    AdapterInvalidCursorError,
    AdapterInvalidResponseError,
)
from .mapper import _first_text, _product_state, _safe_detail_html

_CATEGORY_ID_KEYS = ("leafCategoryId", "categoryId")
_CATEGORY_NAME_KEYS = ("name", "categoryName", "leafCategoryName")
_MODEL_ID_KEYS = ("modelId", "modelNo")
_MODEL_NAME_KEYS = ("name", "modelName")


def _positive_int(value: Any) -> int | None:
    if type(value) is int and value > 0:
        return value
    if isinstance(value, str) and value.isdigit() and int(value) > 0:
        return int(value)
    return None


def _numeric_id(row: dict[str, Any], keys: tuple[str, ...]) -> int | None:
    for key in keys:
        value = _positive_int(row.get(key))
        if value is not None:
            return value
    return None


@dataclass(frozen=True)
class NaverProductPage:
    items: tuple[Product, ...]
    next_cursor: str | None


def _echoed_channel_product_no(row: dict[str, Any]) -> str | None:
    candidates = [row.get("channelProductNo")]
    nested = row.get("smartstoreChannelProduct")
    if isinstance(nested, dict):
        candidates.append(nested.get("channelProductNo"))
    for value in candidates:
        parsed = _positive_int(value)
        if parsed is not None:
            return str(parsed)
    return None


def _withhold_phone_like_asset_url(value: str) -> bool:
    """Omit uncertain public asset paths, never exempt them from the PII gate.

    Secret/email and other hosts retain the existing whole-result rejection.
    This is a local output-withholding subset, not a provider URL contract.
    """
    if [i for i, pattern in enumerate(UNSAFE_VALUE_PATTERNS) if pattern.search(value)] != [1]:
        return False
    return re.fullmatch(
        r"https://(?:shop-phinf|shopping-phinf)\.pstatic\.net/[A-Za-z0-9_./-]+",
        value,
    ) is not None


class NaverProductsMixin:
    async def get_products(
        self, *, page_size: int, cursor: str | None = None
    ) -> NaverProductPage:
        if type(page_size) is not int or not 1 <= page_size <= 100:
            raise ValueError("page_size must be between 1 and 100")
        page, offset = _search_position(cursor)
        policy_currency = currency_for_channel(Channel.NAVER)
        if policy_currency is None:
            raise RuntimeError("naver currency policy is not configured")
        try:
            payload = await self.client.search_products(page=page, size=page_size)
        except NaverRequestError as exc:
            raise AdapterInvalidCursorError from exc
        if (
            not isinstance(payload, dict)
            or not isinstance(payload.get("contents"), list)
            or type(payload.get("last")) is not bool
            or payload.get("page") != page
            or payload.get("size") != page_size
        ):
            raise AdapterInvalidResponseError("naver product search response shape is invalid")
        source = self._source(
            "naver:v1/products/search",
            f"provider_product_list;{POLICY_CONFIRMED_KRW_BASIS}",
            method="POST",
        )
        items: list[Product] = []
        for content in payload["contents"]:
            if not isinstance(content, dict):
                continue
            channel_products = content.get("channelProducts")
            if not isinstance(channel_products, list):
                continue
            for row in channel_products:
                product = _channel_product(row, policy_currency, source)
                if product is not None:
                    items.append(product)
        if offset > len(items) or (offset and offset >= len(items)):
            raise AdapterInvalidResponseError(
                "naver product search cursor no longer matches the page"
            )
        window = items[offset : offset + page_size]
        next_offset = offset + len(window)
        if next_offset < len(items):
            next_cursor = f"{page}:{next_offset}"
        elif payload["last"] is False:
            next_cursor = str(page + 1)
        else:
            next_cursor = None
        return NaverProductPage(items=tuple(window), next_cursor=next_cursor)

    async def _read_product(self, external_product_id: str) -> dict[str, Any] | None:
        if not external_product_id.isdigit() or int(external_product_id) <= 0:
            return None
        row = await self.client.get_channel_product(
            channel_product_no=int(external_product_id)
        )
        if not isinstance(row, dict):
            return None
        echoed = _echoed_channel_product_no(row)
        if echoed is not None and echoed != external_product_id:
            return None
        if echoed is None and not isinstance(row.get("originProduct"), dict):
            return None
        return row

    async def _read_origin_root(self, row: dict[str, Any]) -> dict[str, Any] | None:
        embedded = row.get("originProduct")
        if isinstance(embedded, dict) and isinstance(embedded.get("deliveryInfo"), dict):
            return embedded
        get_origin = getattr(self.client, "get_origin_product", None)
        if get_origin is None:
            return None
        candidates = [row.get("originProductNo")]
        for key in ("originProduct", "smartstoreChannelProduct"):
            nested = row.get(key)
            if isinstance(nested, dict):
                candidates.append(nested.get("originProductNo"))
        origin_no = next(
            (value for value in map(_positive_int, candidates) if value is not None),
            None,
        )
        if origin_no is None:
            return None
        try:
            payload = await get_origin(origin_product_no=origin_no)
        except NaverProviderError:
            return None
        if not isinstance(payload, dict):
            return None
        origin = payload.get("originProduct")
        return origin if isinstance(origin, dict) else payload

    @staticmethod
    def _detail_attribute(origin_root: dict[str, Any] | None) -> dict[str, Any]:
        if not isinstance(origin_root, dict):
            return {}
        value = origin_root.get("detailAttribute")
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _search_info(
        origin_root: dict[str, Any] | None, detail_attribute: dict[str, Any]
    ) -> dict[str, Any]:
        for container in (detail_attribute, origin_root or {}):
            value = container.get("naverShoppingSearchInfo")
            if isinstance(value, dict):
                return value
        return {}

    async def _category_name(
        self, origin_root: dict[str, Any] | None, detail_attribute: dict[str, Any]
    ) -> str | None:
        get_category = getattr(self.client, "get_category", None)
        if get_category is None:
            return None
        containers = [detail_attribute]
        if isinstance(origin_root, dict):
            containers.append(origin_root)
        category_id = next(
            (
                value
                for value in (_numeric_id(row, _CATEGORY_ID_KEYS) for row in containers)
                if value is not None
            ),
            None,
        )
        if category_id is None:
            return None
        try:
            row = await get_category(category_id=category_id)
        except NaverProviderError:
            return None
        name = _first_text(row, _CATEGORY_NAME_KEYS)
        if name is not None:
            return name
        whole = row.get("wholeCategoryName")
        if isinstance(whole, str) and whole.strip():
            return whole.split(">")[-1].strip() or None
        return None

    async def _model_name(
        self, search_info: dict[str, Any], detail_attribute: dict[str, Any]
    ) -> str | None:
        name = _first_text(search_info, _MODEL_NAME_KEYS) or _first_text(
            detail_attribute, ("modelName",)
        )
        if name is not None:
            return name
        get_model = getattr(self.client, "get_product_model", None)
        if get_model is None:
            return None
        model_id = _numeric_id(search_info, _MODEL_ID_KEYS) or _numeric_id(
            detail_attribute, _MODEL_ID_KEYS
        )
        if model_id is None:
            return None
        try:
            row = await get_model(model_id=model_id)
        except NaverProviderError:
            return None
        return _first_text(row, _MODEL_NAME_KEYS)

    async def get_product_detail(self, external_product_id: str) -> ProductDetail | None:
        row = await self._read_product(external_product_id)
        if row is None:
            return None
        origin_root = await self._read_origin_root(row)
        if origin_root is None and isinstance(row.get("originProduct"), dict):
            origin_root = row["originProduct"]
        detail_attribute = self._detail_attribute(origin_root)
        search_info = self._search_info(origin_root, detail_attribute)
        name = row.get("name")
        if (not isinstance(name, str) or not name.strip()) and isinstance(
            origin_root, dict
        ):
            candidate = origin_root.get("name")
            name = candidate if isinstance(candidate, str) else name
        if not isinstance(name, str) or not name.strip():
            return None
        options = row.get("stocks")
        option_ids = (
            tuple(
                str(item.get("id"))
                for item in options
                if isinstance(item, dict) and item.get("id") is not None
            )
            if isinstance(options, list)
            else ()
        )
        option_records = naver_options(
            origin_root,
            external_product_id,
            self._source(
                "naver:v2/products/channel-products+origin-products", "provider_option_fields"
            ),
        )
        if option_records:
            option_ids = tuple(option.external_option_id for option in option_records)
        missing = ["master_sku"]
        if not option_records:
            missing.append("options")
        if not option_ids:
            missing.append("external_option_ids")
        brand = (
            _first_text(row, ("brandName",))
            or _first_text(search_info, ("brandName", "brandText"))
            or _first_text(detail_attribute, ("brandName", "manufacturerName"))
        )
        category = (
            _first_text(row, ("categoryName",))
            or _first_text(detail_attribute, ("categoryName",))
            or await self._category_name(origin_root, detail_attribute)
        )
        model_name = await self._model_name(search_info, detail_attribute)
        for field, value in (("brand_name", brand), ("category_name", category)):
            if not value:
                missing.append(field)
        endpoint = "naver:v2/products/channel-products"
        if origin_root is not None:
            endpoint = "naver:v2/products/channel-products+origin-products"
        template, candidate = _delivery_projection(origin_root)
        return ProductDetail(
            channel=Channel.NAVER,
            external_product_id=external_product_id,
            external_option_ids=tuple(dict.fromkeys(option_ids)),
            options=option_records,
            option_image_groups=naver_option_image_groups(
                origin_root,
                self._source(
                    "naver:v2/products/channel-products+origin-products",
                    "provider_standard_option_images",
                ),
            ),
            name=name,
            state=_product_state(row.get("exposureStatus") or row.get("status")),
            brand_name=brand,
            category_name=category,
            model_name=model_name,
            attributes=(),
            naver_delivery_template=template,
            naver_delivery_template_candidate=candidate,
            completeness=Completeness(
                status=ResultStatus.INCOMPLETE,
                missing_fields=tuple(missing),
                reasons=("master_sku_link_not_verified",),
            ),
            source=self._source(endpoint, "provider_product_detail"),
        )

    async def get_product_content(self, external_product_id: str) -> ProductContent | None:
        row = await self._read_product(external_product_id)
        if row is None:
            return None
        title = row.get("name")
        origin = row.get("originProduct")
        if (not isinstance(title, str) or not title.strip()) and isinstance(origin, dict):
            title = origin.get("name")
        if not isinstance(title, str) or not title.strip():
            return None
        description = _safe_detail_html(row.get("detailContent"))
        if description is None and isinstance(origin, dict):
            description = _safe_detail_html(origin.get("detailContent"))
        images = row.get("images")
        if not isinstance(images, (list, dict)) and isinstance(origin, dict):
            images = origin.get("images")
        if isinstance(images, dict):
            representative = images.get("representativeImage")
            optional = images.get("optionalImages")
            role_rows = (
                [(representative, "representative")] if isinstance(representative, dict) else []
            )
            if isinstance(optional, list):
                role_rows.extend((image, "additional") for image in optional)
            images = [image for image, _role in role_rows]
        else:
            role_rows = (
                [(image, "unclassified") for image in images] if isinstance(images, list) else []
            )
        for image, _role in role_rows:
            if (
                isinstance(image, dict)
                and isinstance(image.get("url"), str)
                and image["url"].startswith("https://")
                and not _withhold_phone_like_asset_url(image["url"])
                and not is_agent_safe_value(image["url"])
            ):
                raise AdapterInvalidResponseError("product image is not agent-safe")
        classified = [
            ProductImage(url=image["url"], role=role)
            for image, role in role_rows
            if isinstance(image, dict)
            and isinstance(image.get("url"), str)
            and image["url"].startswith("https://")
            and not _withhold_phone_like_asset_url(image["url"])
        ]
        html = row.get("detailContent")
        if not isinstance(html, str) and isinstance(origin, dict):
            html = origin.get("detailContent")
        detail_urls, detail_withheld = body_images(html)
        for url in detail_urls:
            if _withhold_phone_like_asset_url(url):
                detail_withheld = True
            else:
                classified.append(ProductImage(url=url, role="detail"))
        references = []
        reference_rows = [
            (image["url"], role)
            for image, role in role_rows
            if isinstance(image, dict) and isinstance(image.get("url"), str)
        ] + [(url, "detail") for url in body_reference_urls(html)]
        reference_rows = list(dict.fromkeys(reference_rows))
        if len(reference_rows) > 100:
            raise AdapterInvalidResponseError("image reference count exceeds bound")
        for url, role in reference_rows:
            try:
                reference = IMAGE_ASSETS.register(url)
            except ImageAssetError:
                continue  # Existing URL safety/withholding rules still apply.
            references.append(ProductImageReference(asset_ref=reference, role=role))
        image_refs = tuple(dict.fromkeys(references))
        classified_images = unique_images(classified)
        image_urls = (
            tuple(
                str(item.get("url"))
                for item in images
                if isinstance(item, dict)
                and isinstance(item.get("url"), str)
                and item["url"].startswith("https://")
            )
            if isinstance(images, list)
            else ()
        )
        visible_image_urls = tuple(
            url for url in image_urls if not _withhold_phone_like_asset_url(url)
        )
        withheld = len(visible_image_urls) != len(image_urls)
        image_urls = visible_image_urls
        missing = []
        reasons = []
        if description is None:
            missing.append("description_text")
            reasons.append("provider_content_fields_missing")
        if not image_urls or withheld:
            missing.append("image_urls")
            if not withheld and "provider_content_fields_missing" not in reasons:
                reasons.append("provider_content_fields_missing")
        if withheld:
            reasons.append("unsafe_image_urls_withheld")
        if detail_withheld:
            missing.append("detail_images")
            reasons.append("detail_image_urls_withheld")
        return ProductContent(
            channel=Channel.NAVER,
            external_product_id=external_product_id,
            title=title,
            description_text=description,
            image_urls=image_urls,
            images=classified_images,
            image_refs=image_refs,
            completeness=Completeness(
                status=ResultStatus.COMPLETE if not missing else ResultStatus.INCOMPLETE,
                missing_fields=tuple(missing),
                reasons=tuple(reasons),
            ),
            source=self._source("naver:v2/products/channel-products", "provider_product_content"),
        )



def _search_position(cursor: str | None) -> tuple[int, int]:
    if cursor is None:
        return 1, 0
    if not isinstance(cursor, str) or not cursor or cursor != cursor.strip():
        raise AdapterInvalidCursorError
    page_text, separator, offset_text = cursor.partition(":")
    if not page_text.isdigit() or page_text != str(int(page_text)):
        raise AdapterInvalidCursorError
    page = int(page_text)
    if not 1 <= page <= 10_000:
        raise AdapterInvalidCursorError
    if not separator:
        return page, 0
    if (
        not offset_text.isdigit()
        or offset_text != str(int(offset_text))
        or int(offset_text) < 1
    ):
        raise AdapterInvalidCursorError
    return page, int(offset_text)


def _channel_product(
    row: object, currency: str, source: Any
) -> Product | None:
    if not isinstance(row, dict):
        return None
    product_id = row.get("channelProductNo")
    if type(product_id) is not int or product_id <= 0:
        return None
    product_ref = str(product_id)
    name = row.get("name")
    if (
        not isinstance(name, str)
        or not name.strip()
        or not is_agent_safe_value(product_ref)
        or not is_agent_safe_value(name)
    ):
        return None
    sale_price = row.get("salePrice")
    listing_price = None
    if type(sale_price) is int and 0 <= sale_price <= 999_999_990:
        listing_price = Money(amount=Decimal(sale_price), currency=currency)
    return Product(
        channel=Channel.NAVER,
        external_product_id=product_ref,
        name=name.strip(),
        state=_product_state(row.get("statusType")),
        listing_price=listing_price,
        completeness=Completeness(
            status=ResultStatus.INCOMPLETE,
            missing_fields=("master_sku",),
            reasons=("master_sku_link_not_verified",),
        ),
        source=source,
    )


_DELIVERY_TYPES = {"DELIVERY", "DIRECT"}
_DELIVERY_ATTRIBUTES = {
    "NORMAL",
    "TODAY",
    "OPTION_TODAY",
    "HOPE",
    "TODAY_ARRIVAL",
    "DAWN_ARRIVAL",
    "ARRIVAL_GUARANTEE",
    "SELLER_GUARANTEE",
    "HOPE_SELLER_GUARANTEE",
    "QUICK",
    "PICKUP",
    "QUICK_PICKUP",
}
_FEE_TYPES = {
    "FREE",
    "CONDITIONAL_FREE",
    "PAID",
    "UNIT_QUANTITY_PAID",
    "RANGE_QUANTITY_PAID",
}
_PAY_TYPES = {"COLLECT", "PREPAID", "COLLECT_OR_PREPAID"}
_AREA_TYPES = {"AREA_2", "AREA_3"}
_COMPANY_CODE = re.compile(r"^[A-Z0-9_]{2,20}$")


def _has_unsafe_text(value: object) -> bool:
    if isinstance(value, str):
        return not is_agent_safe_value(value)
    if isinstance(value, dict):
        return any(_has_unsafe_text(child) for child in value.values())
    if isinstance(value, list):
        return any(_has_unsafe_text(child) for child in value)
    return False


def _bounded_int(value: object, maximum: int) -> int | None:
    if type(value) is int and 0 <= value <= maximum:
        return value
    return None


def _delivery_projection(
    origin_root: dict[str, Any] | None,
) -> tuple[NaverDeliveryPolicyTemplate | None, NaverDeliveryPolicyTemplateCandidate | None]:
    if not isinstance(origin_root, dict):
        return None, None
    info = origin_root.get("deliveryInfo")
    if not isinstance(info, dict) or _has_unsafe_text(info):
        return None, None
    missing: list[str] = []
    delivery_type = info.get("deliveryType")
    if delivery_type not in _DELIVERY_TYPES:
        delivery_type = None
        missing.append("delivery_type")
    attribute = info.get("deliveryAttributeType")
    if attribute not in _DELIVERY_ATTRIBUTES:
        attribute = None
        missing.append("delivery_attribute_type")
    company = info.get("deliveryCompany")
    company_code = (
        company if isinstance(company, str) and _COMPANY_CODE.fullmatch(company) else None
    )
    if delivery_type == "DELIVERY" and company_code is None:
        missing.append("delivery_company_code")
    fee = info.get("deliveryFee")
    fee_type = None
    base_fee = None
    conditional_amount = None
    pay_type = None
    area = None
    if not isinstance(fee, dict):
        missing.extend(["delivery_fee_type", "base_fee"])
    else:
        fee_type = fee.get("deliveryFeeType")
        if fee_type not in _FEE_TYPES:
            fee_type = None
            missing.append("delivery_fee_type")
        base_fee = _bounded_int(fee.get("baseFee"), 100_000)
        if base_fee is None:
            missing.append("base_fee")
        conditional_amount = _bounded_int(fee.get("freeConditionalAmount"), 999_999_990)
        if fee_type == "CONDITIONAL_FREE" and conditional_amount is None:
            missing.append("free_conditional_amount")
        if "deliveryFeePayType" in fee:
            pay_type = fee.get("deliveryFeePayType")
            if pay_type not in _PAY_TYPES:
                pay_type = None
                missing.append("delivery_fee_pay_type")
        area_row = fee.get("deliveryFeeByArea")
        if isinstance(area_row, dict):
            area_type = area_row.get("deliveryAreaType")
            area2 = _bounded_int(area_row.get("area2extraFee"), 200_000)
            area3 = _bounded_int(area_row.get("area3extraFee"), 200_000)
            if area_type not in _AREA_TYPES:
                missing.append("delivery_area_type")
            elif area_type == "AREA_2" and area2 is None:
                missing.append("area2_extra_fee")
            elif area_type == "AREA_3" and area3 is None:
                missing.append("area3_extra_fee")
            else:
                area = NaverDeliveryFeeByArea(
                    delivery_area_type=area_type,
                    area2_extra_fee=area2,
                    area3_extra_fee=area3,
                )
    claim = info.get("claimDeliveryInfo")
    return_fee = None
    exchange_fee = None
    if not isinstance(claim, dict):
        missing.extend(["return_delivery_fee", "exchange_delivery_fee"])
    else:
        return_fee = _bounded_int(claim.get("returnDeliveryFee"), 1_000_000)
        exchange_fee = _bounded_int(claim.get("exchangeDeliveryFee"), 1_000_000)
        if return_fee is None:
            missing.append("return_delivery_fee")
        if exchange_fee is None:
            missing.append("exchange_delivery_fee")
    if (
        not missing
        and delivery_type
        and attribute
        and fee_type is not None
        and base_fee is not None
    ):
        return (
            NaverDeliveryPolicyTemplate(
                delivery_type=delivery_type,
                delivery_attribute_type=attribute,
                delivery_company_code=company_code,
                delivery_fee=NaverDeliveryFeePolicy(
                    delivery_fee_type=fee_type,
                    base_fee=base_fee,
                    free_conditional_amount=conditional_amount,
                    delivery_fee_pay_type=pay_type,
                    delivery_fee_by_area=area,
                ),
                claim_delivery=NaverClaimDeliveryPolicy(
                    return_delivery_fee=return_fee,
                    exchange_delivery_fee=exchange_fee,
                ),
            ),
            None,
        )
    return (
        None,
        NaverDeliveryPolicyTemplateCandidate(
            delivery_type=delivery_type,
            delivery_attribute_type=attribute,
            delivery_company_code=company_code,
            delivery_fee=NaverDeliveryFeePolicyCandidate(
                delivery_fee_type=fee_type,
                base_fee=base_fee,
                free_conditional_amount=conditional_amount,
                delivery_fee_pay_type=pay_type,
                delivery_fee_by_area=area,
            ),
            claim_delivery=NaverClaimDeliveryPolicyCandidate(
                return_delivery_fee=return_fee,
                exchange_delivery_fee=exchange_fee,
            ),
            missing_fields=tuple(dict.fromkeys(missing)),
        ),
    )
