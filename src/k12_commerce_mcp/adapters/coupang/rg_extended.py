"""Independent Rocket Growth reads that the shared Coupang client does not expose.

Official index (2026-09-16 capture) lists nine operations. This module does not
import the live client and never performs a provider call by itself. Callers
inject a fake or later-approved transport. Product creation and modification
stay disabled. General Coupang return/exchange paths are not RG operations.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from ...security import assert_agent_safe_value, safe_display_value

RG_VENDOR = "/v2/providers/rg_open_api/apis/api/v1/vendors/{vendorId}"
SELLER_PRODUCTS = "/v2/providers/seller_api/apis/api/v1/marketplace/seller-products"
DISPLAY_CATEGORIES = (
    "/v2/providers/seller_api/apis/api/v1/marketplace/meta/display-categories"
)
CATEGORY_META = (
    "/v2/providers/seller_api/apis/api/v1/marketplace/meta"
    "/category-related-metas/display-category-codes/{displayCategoryCode}"
)


@dataclass(frozen=True)
class RgOperation:
    """One official RG operation identity. Shared URIs stay separate by method."""

    operation_id: str
    method: str
    path_template: str
    local_execution: str
    query_names: tuple[str, ...] = ()
    required_query: tuple[tuple[str, str], ...] = ()


OFFICIAL_RG_OPERATIONS: tuple[RgOperation, ...] = (
    RgOperation(
        operation_id="rg_order_list",
        method="GET",
        path_template=f"{RG_VENDOR}/rg/orders",
        local_execution="existing_client",
        query_names=("paidDateFrom", "paidDateTo", "nextToken"),
    ),
    RgOperation(
        operation_id="rg_order_detail",
        method="GET",
        path_template=f"{RG_VENDOR}/rg/order/{{orderId}}",
        local_execution="local_read",
    ),
    RgOperation(
        operation_id="rg_inventory_summaries",
        method="GET",
        path_template=f"{RG_VENDOR}/rg/inventory/summaries",
        local_execution="local_read",
        # Parameter table name. The intro text's vendorIdItemId is not sent.
        query_names=("vendorItemId", "nextToken"),
    ),
    RgOperation(
        operation_id="rg_product_list",
        method="GET",
        path_template=SELLER_PRODUCTS,
        local_execution="shared_uri_not_promoted",
        query_names=("vendorId", "nextToken", "maxPerPage", "businessTypes"),
        required_query=(("businessTypes", "rocketGrowth"),),
    ),
    RgOperation(
        operation_id="rg_product_create",
        method="POST",
        path_template=SELLER_PRODUCTS,
        local_execution="disabled_simulation",
    ),
    RgOperation(
        operation_id="rg_product_modify",
        method="PUT",
        path_template=SELLER_PRODUCTS,
        local_execution="disabled_simulation",
    ),
    RgOperation(
        operation_id="rg_product_detail",
        method="GET",
        path_template=f"{SELLER_PRODUCTS}/{{sellerProductId}}",
        local_execution="shared_uri_not_promoted",
    ),
    RgOperation(
        operation_id="rg_category_meta",
        method="GET",
        path_template=CATEGORY_META,
        local_execution="local_read",
    ),
    RgOperation(
        operation_id="rg_category_list",
        method="GET",
        path_template=DISPLAY_CATEGORIES,
        local_execution="local_read",
        query_names=("registrationType", "locale"),
        required_query=(("registrationType", "RFM"),),
    ),
)


def _path_matches(template: str, path: str) -> bool:
    template_parts = template.split("/")
    path_parts = path.split("/")
    if len(template_parts) != len(path_parts):
        return False
    for expected, actual in zip(template_parts, path_parts, strict=True):
        placeholder = expected.startswith("{") and expected.endswith("}")
        if placeholder:
            if not actual or actual in {".", ".."}:
                return False
            continue
        if expected != actual:
            return False
    return True


def classify_provider_path(method: str, path: str) -> RgPathVerdict:
    """Return an official RG identity only. General claim paths stay unsupported."""
    if not isinstance(method, str) or not isinstance(path, str):
        return RgPathVerdict(False, None, "not_official_rg_operation")
    for operation in OFFICIAL_RG_OPERATIONS:
        if operation.method != method or not _path_matches(operation.path_template, path):
            continue
        if "/rg_open_api/" not in operation.path_template:
            return RgPathVerdict(False, operation.operation_id, "shared_uri_not_rg_proof")
        return RgPathVerdict(True, operation.operation_id, "official_rg_operation")
    return RgPathVerdict(False, None, "not_official_rg_operation")


class RgRequestError(ValueError):
    """Closed local validation failure. Never includes a provider body."""


_VENDOR_ID = re.compile(r"^A[0-9A-Za-z]{3,20}$")
_DIGITS = re.compile(r"^[0-9]{1,20}$")
_PAID_AT = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{2}:\d{2})?$"
)
_MONEY = re.compile(r"^[0-9]+(?:\.[0-9]{1,2})?$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")
_LOCALES = frozenset({"en", "zh-CN", "kr"})
_CATEGORY_STATUS = frozenset({"ACTIVE", "READY", "DISABLED"})
_ATTRIBUTE_REQUIRED = frozenset({"MANDATORY", "OPTIONAL"})
_ATTRIBUTE_TYPES = frozenset({"STRING", "NUMBER", "DATE"})
_MAX_CATEGORY_NODES = 200


class RgTransport(Protocol):
    async def exchange(
        self,
        *,
        method: str,
        path: str,
        query: tuple[tuple[str, str], ...],
    ) -> object: ...


def _vendor_id(value: str) -> str:
    if not isinstance(value, str) or _VENDOR_ID.fullmatch(value) is None:
        raise RgRequestError("invalid vendor id")
    return value


def _digits(value: object, field: str) -> str:
    if not isinstance(value, str) or _DIGITS.fullmatch(value) is None:
        raise RgRequestError(f"invalid {field}")
    return value


def _id_text(value: object) -> str | None:
    if type(value) is int and value >= 0:
        return str(value)
    if isinstance(value, str) and _DIGITS.fullmatch(value):
        return value
    return None


@dataclass(frozen=True)
class RgOrderDetail:
    order_id: str
    paid_at: str | None
    lines: tuple[dict[str, object], ...]


@dataclass(frozen=True)
class RgInventoryPage:
    items: tuple[dict[str, object], ...]
    next_token: str | None


@dataclass(frozen=True)
class RgCategoryPage:
    categories: tuple[dict[str, object], ...]


@dataclass(frozen=True)
class RgCategoryMeta:
    display_category_code: str
    is_allow_single_item: bool
    rocket_growth_expiration_required: bool
    attributes: tuple[dict[str, str], ...]


@dataclass(frozen=True)
class RgDisabledMutation:
    method: str
    enabled: bool
    approval_missing: bool
    network_calls: int


@dataclass(frozen=True)
class RgPathVerdict:
    supported: bool
    operation_id: str | None
    reason: str


def _project_line(item: object) -> dict[str, object] | None:
    if not isinstance(item, dict):
        return None
    vendor_item_id = _id_text(item.get("vendorItemId"))
    quantity = item.get("salesQuantity")
    price = item.get("salesPrice")
    currency = item.get("currency")
    if (
        vendor_item_id is None
        or type(quantity) is not int
        or quantity < 0
        or not isinstance(price, str)
        or _MONEY.fullmatch(price) is None
        or not isinstance(currency, str)
        or _CURRENCY.fullmatch(currency) is None
    ):
        return None
    name = item.get("productName")
    product_name = safe_display_value(name) if isinstance(name, str) else None
    if isinstance(name, str) and product_name is None:
        return None
    return {
        "vendor_item_id": vendor_item_id,
        "product_name": product_name,
        "sales_quantity": quantity,
        "sales_price": price,
        "currency": currency,
    }


def _project_order(payload: object, order_id: str) -> RgOrderDetail:
    if not isinstance(payload, dict):
        raise RgRequestError("invalid order detail shape")
    data = payload.get("data")
    if isinstance(data, dict):
        rows = (data,)
    elif isinstance(data, list) and all(isinstance(row, dict) for row in data):
        rows = tuple(data)
    else:
        raise RgRequestError("invalid order detail shape")
    matched = [row for row in rows if _id_text(row.get("orderId")) == order_id]
    if len(matched) != 1:
        raise RgRequestError("invalid order detail shape")
    row = matched[0]
    paid_at = row.get("paidAt")
    if not isinstance(paid_at, str) or _PAID_AT.fullmatch(paid_at) is None:
        paid_at = None
    raw_items = row.get("orderItems")
    if not isinstance(raw_items, list):
        raise RgRequestError("invalid order detail shape")
    lines = []
    for item in raw_items:
        projected = _project_line(item)
        if projected is None:
            raise RgRequestError("invalid order detail shape")
        lines.append(projected)
    result = RgOrderDetail(order_id=order_id, paid_at=paid_at, lines=tuple(lines))
    assert_agent_safe_value(
        {"order_id": result.order_id, "paid_at": result.paid_at, "lines": result.lines}
    )
    return result


def _project_inventory(payload: object, vendor_item_id: str | None) -> RgInventoryPage:
    if not isinstance(payload, dict):
        raise RgRequestError("invalid inventory shape")
    data = payload.get("data")
    if not isinstance(data, list) or not all(isinstance(row, dict) for row in data):
        raise RgRequestError("invalid inventory shape")
    items: list[dict[str, object]] = []
    for row in data:
        item_id = _id_text(row.get("vendorItemId"))
        details = row.get("inventoryDetails")
        quantity = details.get("totalOrderableQuantity") if isinstance(details, dict) else None
        projected = None
        if item_id is not None and type(quantity) is int and quantity >= 0:
            projected = {"vendor_item_id": item_id, "orderable_quantity": quantity}
        if vendor_item_id is not None and item_id != vendor_item_id:
            continue
        if projected is None:
            raise RgRequestError("invalid inventory shape")
        items.append(projected)
    if vendor_item_id is not None:
        if len(items) != 1:
            raise RgRequestError("invalid inventory shape")
        token = None
    else:
        token = payload.get("nextToken")
        if token is not None and not isinstance(token, str):
            raise RgRequestError("invalid inventory shape")
        token = token or None
    result = RgInventoryPage(items=tuple(items), next_token=token)
    assert_agent_safe_value({"items": result.items, "next_token": result.next_token})
    return result


def _project_category(node: object, remaining: list[int]) -> dict[str, object] | None:
    if remaining[0] <= 0 or not isinstance(node, dict):
        return None
    code = _id_text(node.get("displayCategoryCode"))
    name = node.get("name")
    status = node.get("status")
    safe_name = safe_display_value(name)
    if code is None or safe_name is None or status not in _CATEGORY_STATUS:
        return None
    raw_children = node.get("child")
    if not isinstance(raw_children, list):
        return None
    remaining[0] -= 1
    children: list[dict[str, object]] = []
    for child in raw_children:
        projected = _project_category(child, remaining)
        if projected is None:
            return None
        children.append(projected)
    return {
        "display_category_code": code,
        "name": safe_name,
        "status": status,
        "child": tuple(children),
    }


def _project_categories(payload: object) -> RgCategoryPage:
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise RgRequestError("invalid category shape")
    remaining = [_MAX_CATEGORY_NODES]
    categories: list[dict[str, object]] = []
    for node in payload["data"]:
        projected = _project_category(node, remaining)
        if projected is None:
            raise RgRequestError("invalid category shape")
        categories.append(projected)
    result = RgCategoryPage(categories=tuple(categories))
    assert_agent_safe_value({"categories": result.categories})
    return result


def _project_category_meta(payload: object, category_code: str) -> RgCategoryMeta:
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise RgRequestError("invalid category meta shape")
    rows = payload["data"]
    if len(rows) != 1 or not isinstance(rows[0], dict):
        raise RgRequestError("invalid category meta shape")
    row = rows[0]
    single = row.get("isAllowSingleItem")
    expiration = row.get("isExpirationDateRequiredForRocketGrowth")
    raw_attributes = row.get("attributes")
    attributes_ok = isinstance(raw_attributes, list)
    if type(single) is not bool or type(expiration) is not bool or not attributes_ok:
        raise RgRequestError("invalid category meta shape")
    attributes: list[dict[str, str]] = []
    for item in raw_attributes:
        if not isinstance(item, dict):
            raise RgRequestError("invalid category meta shape")
        name = safe_display_value(item.get("attributeTypeName"))
        required = item.get("required")
        data_type = item.get("dataType")
        if (
            name is None
            or required not in _ATTRIBUTE_REQUIRED
            or data_type not in _ATTRIBUTE_TYPES
        ):
            raise RgRequestError("invalid category meta shape")
        attributes.append(
            {
                "attribute_type_name": name,
                "required": required,
                "data_type": data_type,
            }
        )
    result = RgCategoryMeta(
        display_category_code=category_code,
        is_allow_single_item=single,
        rocket_growth_expiration_required=expiration,
        attributes=tuple(attributes),
    )
    assert_agent_safe_value(
        {
            "display_category_code": result.display_category_code,
            "is_allow_single_item": result.is_allow_single_item,
            "rocket_growth_expiration_required": result.rocket_growth_expiration_required,
            "attributes": result.attributes,
        }
    )
    return result


class RgExtendedReader:
    def __init__(self, transport: RgTransport, vendor_id: str) -> None:
        self._transport = transport
        self._vendor_id = _vendor_id(vendor_id)

    async def get_order(self, order_id: str) -> RgOrderDetail:
        order = _digits(order_id, "order id")
        path = f"{RG_VENDOR.format(vendorId=self._vendor_id)}/rg/order/{order}"
        payload = await self._transport.exchange(method="GET", path=path, query=())
        return _project_order(payload, order)

    async def get_inventory_summaries(
        self,
        *,
        vendor_item_id: str | None = None,
        next_token: str | None = None,
    ) -> RgInventoryPage:
        query: list[tuple[str, str]] = []
        item_id = None
        if vendor_item_id is not None:
            item_id = _digits(vendor_item_id, "vendor item id")
            query.append(("vendorItemId", item_id))
        elif next_token is not None:
            if (
                not isinstance(next_token, str)
                or not next_token.strip()
                or next_token != next_token.strip()
                or len(next_token) > 512
                or any(char in next_token for char in "/?#&=")
            ):
                raise RgRequestError("invalid next token")
            query.append(("nextToken", next_token))
        path = f"{RG_VENDOR.format(vendorId=self._vendor_id)}/rg/inventory/summaries"
        payload = await self._transport.exchange(method="GET", path=path, query=tuple(query))
        return _project_inventory(payload, item_id)

    async def list_categories(
        self,
        *,
        registration_type: str,
        locale: str | None = None,
    ) -> RgCategoryPage:
        if registration_type != "RFM":
            raise RgRequestError("rocket growth categories require registrationType RFM")
        query = [("registrationType", "RFM")]
        if locale is not None:
            if locale not in _LOCALES:
                raise RgRequestError("invalid category locale")
            query.append(("locale", locale))
        payload = await self._transport.exchange(
            method="GET",
            path=DISPLAY_CATEGORIES,
            query=tuple(query),
        )
        return _project_categories(payload)

    async def get_category_meta(self, display_category_code: str) -> RgCategoryMeta:
        code = _digits(display_category_code, "display category code")
        path = CATEGORY_META.format(displayCategoryCode=code)
        payload = await self._transport.exchange(method="GET", path=path, query=())
        return _project_category_meta(payload, code)

    def _disabled_mutation(self, body: object, method: str) -> RgDisabledMutation:
        if not isinstance(body, dict) or body.get("vendorId") != self._vendor_id:
            raise RgRequestError("invalid disabled mutation body")
        name = body.get("sellerProductName")
        if not isinstance(name, str) or not name.strip() or len(name) > 100:
            raise RgRequestError("invalid disabled mutation body")
        if method == "PUT":
            _digits(body.get("sellerProductId"), "seller product id")
        return RgDisabledMutation(
            method=method,
            enabled=False,
            approval_missing=True,
            network_calls=0,
        )

    def simulate_product_create(self, body: object) -> RgDisabledMutation:
        return self._disabled_mutation(body, "POST")

    def simulate_product_modify(self, body: object) -> RgDisabledMutation:
        return self._disabled_mutation(body, "PUT")
