"""Naver marketplace registration reference reads."""

from __future__ import annotations

import hashlib
import hmac
from typing import Any

from ...models import (
    Channel,
    MarketplaceCategory,
    MarketplaceCategoryRequirements,
    MarketplaceRegistrationResource,
)
from ..base import AdapterInvalidRequestError, AdapterInvalidResponseError
from ..registration import (
    MAX_CATEGORIES,
    MAX_RESOURCES,
    _bounded,
    _text,
    group_descriptors,
    registration_resource,
)

_BUNDLE_GROUP_SELECTOR_KEYS = (
    "deliveryType",
    "chargeType",
    "deliveryMethodType",
    "useDelivery",
)
_RELEASE_ADDRESS_TYPES = frozenset({"RELEASE", "LOGISTICS_CENTER_RELEASE"})
_RETURN_ADDRESS_TYPES = frozenset(
    {"REFUND_OR_EXCHANGE", "LOGISTICS_CENTER_REFUND_OR_EXCHANGE"}
)


def _category_id(value: Any) -> str | None:
    if type(value) is int and value > 0:
        return str(value)
    if isinstance(value, str) and value.strip().isdigit() and int(value) > 0:
        return str(int(value))
    return None


def _addressbook_ref(secret: str, addressbook_id: str) -> str:
    digest = hmac.new(
        secret.encode(), f"naver-addressbook:{addressbook_id}".encode(), hashlib.sha256
    ).hexdigest()
    return f"naver-addressbook-hmac-v1:{digest}"


class NaverRegistrationMixin:
    async def get_marketplace_categories(
        self, *, parent_category_id: str | None = None
    ) -> tuple[MarketplaceCategory, ...]:
        parent = None
        if parent_category_id is not None:
            parent = _category_id(parent_category_id)
            if parent is None or parent != parent_category_id:
                raise AdapterInvalidRequestError("invalid naver parent category id")
            rows = _bounded(
                await self.client.list_sub_categories(category_id=int(parent)),
                MAX_CATEGORIES, "subcategory",
            )
            source = self._source(
                "naver:v1/categories/{categoryId}/sub-categories", "provider_subcategory_list"
            )
        else:
            source = self._source("naver:v1/categories", "provider_category_list")
            rows = _bounded(await self.client.list_categories(), MAX_CATEGORIES, "category")
        items: list[MarketplaceCategory] = []
        for row in rows:
            category_id = _category_id(row.get("id"))
            name = _text(row.get("name"))
            last = row.get("last")
            whole = _text(row.get("wholeCategoryName"), max_length=2000)
            if category_id is None or name is None or type(last) is not bool:
                raise AdapterInvalidResponseError("naver category row shape is invalid")
            level = (
                len([segment for segment in whole.split(">") if segment.strip()])
                if whole is not None
                else None
            )
            items.append(
                MarketplaceCategory(
                    channel=Channel.NAVER,
                    category_id=category_id,
                    parent_category_id=parent,
                    name=name,
                    full_path=whole,
                    level=level or None,
                    is_leaf=last,
                    source=source,
                )
            )
        return tuple(items)

    async def get_marketplace_category_requirements(
        self, *, category_id: str, notice_category_code: str | None = None
    ) -> MarketplaceCategoryRequirements:
        if notice_category_code is not None:
            raise AdapterInvalidRequestError(
                "naver has no notice category code contract"
            )
        parsed = _category_id(category_id)
        if parsed is None:
            raise AdapterInvalidRequestError("invalid naver category id")
        payload = await self.client.get_standard_options(category_id=int(parsed))
        container = payload
        data = payload.get("data")
        if isinstance(data, dict) and "standardOptionCategoryGroups" in data:
            container = data
        flag = container.get("useStandardOption")
        if flag is not None and type(flag) is not bool:
            raise AdapterInvalidResponseError(
                "naver standard options response shape is invalid"
            )
        groups = container.get("standardOptionCategoryGroups")
        if groups is None:
            if flag is not False:
                raise AdapterInvalidResponseError(
                    "naver standard options response shape is invalid"
                )
            groups = []
        return MarketplaceCategoryRequirements(
            channel=Channel.NAVER,
            category_id=parsed,
            descriptors=group_descriptors(groups),
            notice_categories=(),
            notices=(),
            source=self._source(
                "naver:v1/options/standard-options", "provider_standard_options"
            ),
        )

    async def get_marketplace_registration_resources(
        self,
    ) -> tuple[MarketplaceRegistrationResource, ...]:
        bundle_source = self._source(
            "naver:v1/product-delivery-info/bundle-groups",
            "provider_delivery_bundle_groups",
        )
        page = await self.client.list_delivery_bundle_groups(page_size=100)
        if page.next_cursor is not None:
            raise AdapterInvalidResponseError(
                "naver delivery bundle groups exceed one safe page"
            )
        rows = _bounded(page.rows, MAX_RESOURCES, "delivery bundle group")
        resources = [
            registration_resource(
                row,
                channel=Channel.NAVER,
                resource_type="delivery_bundle_group",
                selector_keys=_BUNDLE_GROUP_SELECTOR_KEYS,
                source=bundle_source,
            )
            for row in rows
        ]
        address_source = self._source(
            "naver:v1/seller/addressbooks-for-page",
            "provider_seller_addressbooks",
        )
        address_page = 1
        address_ordinals = {"delivery_location": 0, "exchange_refund_location": 0}
        while True:
            page_result = await self.client.list_seller_addressbooks(page=address_page)
            for row in _bounded(
                page_result.rows, MAX_RESOURCES, "seller addressbook"
            ):
                address_type = _text(row.get("addressType"))
                if address_type in _RELEASE_ADDRESS_TYPES:
                    resource_type = "delivery_location"
                elif address_type in _RETURN_ADDRESS_TYPES:
                    resource_type = "exchange_refund_location"
                else:
                    continue
                raw_address_id = _category_id(row.get("addressBookNo"))
                if raw_address_id is None:
                    raise AdapterInvalidResponseError(
                        "naver seller addressbook row shape is invalid"
                    )
                address_ordinals[resource_type] += 1
                ordinal = address_ordinals[resource_type]
                resources.append(
                    MarketplaceRegistrationResource(
                        channel=Channel.NAVER,
                        resource_id=_addressbook_ref(
                            self.client.credentials.client_secret, raw_address_id
                        ),
                        resource_type=resource_type,
                        name=(
                            f"출고지 {ordinal}"
                            if resource_type == "delivery_location"
                            else f"반품지 {ordinal}"
                        ),
                        is_default=False,
                        selectors={
                            "location_kind": (
                                "release"
                                if resource_type == "delivery_location"
                                else "exchange_return"
                            )
                        },
                        source=address_source,
                    )
                )
                if len(resources) > MAX_RESOURCES:
                    raise AdapterInvalidResponseError(
                        "naver registration resources exceed bound"
                    )
            if page_result.next_cursor is None:
                break
            if (
                not page_result.next_cursor.isdigit()
                or int(page_result.next_cursor) != address_page + 1
            ):
                raise AdapterInvalidResponseError(
                    "naver addressbook pagination is invalid"
                )
            address_page += 1
        return tuple(resources)
