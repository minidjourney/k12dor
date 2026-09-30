"""Full local surface for the official nine Rocket Growth operations.

Snapshot: raw/documents/marketplace-api-docs-20260916/rocket-growth (ten HTML
files; the index lists exactly nine operations). This module never performs
a provider call by itself: reads use an injected transport, product reads on
the shared seller_api URI stay projection-only, and product create/modify
return a disabled synthetic contract with zero network calls. A shared
Coupang URI is never RG proof, and no general claim/cancellation path is an
RG operation.

Effect classes: every documented GET is a safe read on doc evidence (the
order-detail and inventory titles carry no read verb, but the doc bodies
document read-only GET semantics); the POST/PUT product writes are changes.
Nothing in this module is live evidence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from ...security import assert_agent_safe_value, safe_display_value
from .rg_category_pagination import (
    MAX_PAGE_SIZE,
    RgCategoryRequestError,
    RgCategoryTreePage,
    extract_category_nodes,
    paginate_rg_category_tree,
    validate_category_cursor,
)
from .rg_extended import (
    CATEGORY_META,
    DISPLAY_CATEGORIES,
    RG_VENDOR,
    SELLER_PRODUCTS,
    RgCategoryMeta,
    RgCategoryPage,
    RgDisabledMutation,
    RgExtendedReader,
    RgInventoryPage,
    RgOrderDetail,
    RgRequestError,
    RgTransport,
)

_EFFECT_CLASSES = frozenset({"safe_read", "change"})
_SURFACES = frozenset({"reader", "projection", "synthetic"})


@dataclass(frozen=True)
class RgFullOperation:
    """One closed official RG operation. surface picks the local handler."""

    operation_id: str
    method: str
    path_template: str
    rg_uri: bool
    effect_class: str
    surface: str
    source_file: str

    def __post_init__(self) -> None:
        if self.effect_class not in _EFFECT_CLASSES or self.surface not in _SURFACES:
            raise ValueError("invalid operation classification")


_PRODUCT_LIST_DOC = (
    "ko_api_rocket-growth_product-list-paging-query-rocket-growth-"
    "rocket-growthmarketplace-hybrid-products.html"
)
_PRODUCT_CREATE_DOC = (
    "ko_api_rocket-growth_product-creation-rocket-growth-"
    "rocket-growthmarketplace-hybrid-products.html"
)
_PRODUCT_MODIFY_DOC = (
    "ko_api_rocket-growth_modify-product-rocket-growth-"
    "rocket-growthmarketplace-hybrid-products.html"
)
_PRODUCT_DETAIL_DOC = (
    "ko_api_rocket-growth_query-product-rocket-growth-or-"
    "rocket-growthmarketplace-hybrid-products.html"
)
RG_FULL_OPERATIONS: tuple[RgFullOperation, ...] = (
    RgFullOperation(
        operation_id="rg_order_list",
        method="GET",
        path_template=f"{RG_VENDOR}/rg/orders",
        rg_uri=True,
        effect_class="safe_read",
        surface="reader",
        source_file="ko_api_rocket-growth_rg-order-apilist-query.html",
    ),
    RgFullOperation(
        operation_id="rg_order_detail",
        method="GET",
        path_template=f"{RG_VENDOR}/rg/order/{{orderId}}",
        rg_uri=True,
        effect_class="safe_read",
        surface="reader",
        source_file="ko_api_rocket-growth_api.html",
    ),
    RgFullOperation(
        operation_id="rg_inventory_summaries",
        method="GET",
        path_template=f"{RG_VENDOR}/rg/inventory/summaries",
        rg_uri=True,
        effect_class="safe_read",
        surface="reader",
        source_file="ko_api_rocket-growth_rg-inventory-api.html",
    ),
    RgFullOperation(
        operation_id="rg_product_list",
        method="GET",
        path_template=SELLER_PRODUCTS,
        rg_uri=False,
        effect_class="safe_read",
        surface="projection",
        source_file=_PRODUCT_LIST_DOC,
    ),
    RgFullOperation(
        operation_id="rg_product_create",
        method="POST",
        path_template=SELLER_PRODUCTS,
        rg_uri=False,
        effect_class="change",
        surface="synthetic",
        source_file=_PRODUCT_CREATE_DOC,
    ),
    RgFullOperation(
        operation_id="rg_product_modify",
        method="PUT",
        path_template=SELLER_PRODUCTS,
        rg_uri=False,
        effect_class="change",
        surface="synthetic",
        source_file=_PRODUCT_MODIFY_DOC,
    ),
    RgFullOperation(
        operation_id="rg_product_detail",
        method="GET",
        path_template=f"{SELLER_PRODUCTS}/{{sellerProductId}}",
        rg_uri=False,
        effect_class="safe_read",
        surface="projection",
        source_file=_PRODUCT_DETAIL_DOC,
    ),
    RgFullOperation(
        operation_id="rg_category_meta",
        method="GET",
        path_template=CATEGORY_META,
        rg_uri=False,
        effect_class="safe_read",
        surface="reader",
        source_file="ko_api_rocket-growth_category-metadata-query-39429124103449.html",
    ),
    RgFullOperation(
        operation_id="rg_category_list",
        method="GET",
        path_template=DISPLAY_CATEGORIES,
        rg_uri=False,
        effect_class="safe_read",
        surface="reader",
        source_file=(
            "ko_api_rocket-growth_how-to-get-category-list-for-rocket-growth-products.html"
        ),
    ),
)


def rg_full_operation(operation_id: str) -> RgFullOperation:
    """Return the closed catalog entry for an official RG operation id."""
    for item in RG_FULL_OPERATIONS:
        if item.operation_id == operation_id:
            return item
    raise RgRequestError("unknown rg operation")


_VENDOR_ID = re.compile(r"^A[0-9A-Za-z]{3,20}$")
_DIGITS = re.compile(r"^[0-9]{1,20}$")
_PAID_DATE = re.compile(r"^[0-9]{8}$")
_PAID_AT = re.compile(
    r"^(?:[0-9]{10,14}"
    r"|[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:Z|[+-][0-9]{2}:[0-9]{2})?)$"
)
_MONEY = re.compile(r"^[0-9]+(?:\.[0-9]{1,2})?$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")
_CREATED_AT = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_REGISTRATION_TYPE = re.compile(r"^[A-Z_]{1,32}$")
_LOCALES = frozenset({"en", "zh-CN", "kr"})
_PRODUCT_STATUSES = frozenset(
    {
        "IN_REVIEW",
        "SAVED",
        "APPROVING",
        "APPROVED",
        "PARTIAL_APPROVED",
        "DENIED",
        "DELETED",
    }
)
MAX_PAID_DATE_DAYS = 30
MAX_ORDER_PAGE_ROWS = 10_000
# The product list doc bounds maxPerPage at 100; a larger page is malformed.
MAX_PRODUCT_PAGE_ROWS = 100
MAX_PRODUCT_ITEMS = 1_000
_MAX_TOKEN = 512


def _vendor_id(value: object) -> str:
    if not isinstance(value, str) or _VENDOR_ID.fullmatch(value) is None:
        raise RgRequestError("invalid vendor id")
    return value


def _id_text(value: object) -> str | None:
    if type(value) is int and value >= 0:
        return str(value)
    if isinstance(value, str) and _DIGITS.fullmatch(value):
        return value
    return None


def _id_required(value: object, field: str) -> str:
    text = _id_text(value)
    if text is None:
        raise RgRequestError(f"invalid {field}")
    return text


def _id_optional(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _id_required(value, field)


def _safe_text(value: object, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise RgRequestError(f"invalid {field}")
    safe = safe_display_value(value)
    if safe is None:
        raise RgRequestError(f"invalid {field}")
    return safe


def _next_token(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or len(value) > _MAX_TOKEN
        or any(char in value for char in "/?#&=")
    ):
        raise RgRequestError("invalid next token")
    return value


def _paid_date(value: object, field: str) -> date:
    if not isinstance(value, str) or _PAID_DATE.fullmatch(value) is None:
        raise RgRequestError(f"invalid {field}")
    try:
        return date(int(value[:4]), int(value[4:6]), int(value[6:8]))
    except ValueError:
        raise RgRequestError(f"invalid {field}") from None


def _created_date(value: object) -> str:
    if not isinstance(value, str) or _CREATED_AT.fullmatch(value) is None:
        raise RgRequestError("invalid created at")
    try:
        date(int(value[:4]), int(value[5:7]), int(value[8:10]))
    except ValueError:
        raise RgRequestError("invalid created at") from None
    return value


@dataclass(frozen=True)
class RgOrderSummary:
    order_id: str
    paid_at: str | None
    lines: tuple[dict[str, object], ...]


@dataclass(frozen=True)
class RgOrderPage:
    items: tuple[RgOrderSummary, ...]
    next_token: str | None


@dataclass(frozen=True)
class RgProductListPage:
    items: tuple[dict[str, object], ...]
    next_token: str | None


@dataclass(frozen=True)
class RgProductDetail:
    seller_product_id: str
    seller_product_name: str | None
    display_product_name: str | None
    status_name: str | None
    display_category_code: str | None
    items: tuple[dict[str, object], ...]


def _price_text(item: dict[str, object]) -> str | None:
    """Doc table says salesPrice String; the captured sample uses unitSalesPrice."""
    for key in ("salesPrice", "unitSalesPrice"):
        value = item.get(key)
        if value is None:
            continue
        if type(value) is int and value >= 0:
            return str(value)
        if isinstance(value, str) and _MONEY.fullmatch(value):
            return value
        return None
    return None


def _project_order_line(item: object) -> dict[str, object]:
    if not isinstance(item, dict):
        raise RgRequestError("invalid order list shape")
    vendor_item_id = _id_text(item.get("vendorItemId"))
    quantity = item.get("salesQuantity")
    price = _price_text(item)
    currency = item.get("currency")
    name = _safe_text(item.get("productName"), "order line")
    if (
        vendor_item_id is None
        or type(quantity) is not int
        or quantity < 0
        or price is None
        or not isinstance(currency, str)
        or _CURRENCY.fullmatch(currency) is None
    ):
        raise RgRequestError("invalid order list shape")
    return {
        "vendor_item_id": vendor_item_id,
        "product_name": name,
        "sales_quantity": quantity,
        "sales_price": price,
        "currency": currency,
    }


def _project_order_row(row: object, vendor_id: str) -> RgOrderSummary:
    if not isinstance(row, dict) or row.get("vendorId") != vendor_id:
        raise RgRequestError("invalid order list shape")
    order_id = _id_text(row.get("orderId"))
    raw_items = row.get("orderItems")
    if order_id is None or not isinstance(raw_items, list):
        raise RgRequestError("invalid order list shape")
    paid_at = row.get("paidAt")
    if not isinstance(paid_at, str) or _PAID_AT.fullmatch(paid_at) is None:
        paid_at = None
    lines = tuple(_project_order_line(item) for item in raw_items)
    return RgOrderSummary(order_id=order_id, paid_at=paid_at, lines=lines)


def _project_order_list(payload: object, vendor_id: str) -> RgOrderPage:
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise RgRequestError("invalid order list shape")
    data = payload["data"]
    if len(data) > MAX_ORDER_PAGE_ROWS:
        raise RgRequestError("invalid order list shape")
    items = tuple(_project_order_row(row, vendor_id) for row in data)
    token = payload.get("nextToken")
    if token is not None and not isinstance(token, str):
        raise RgRequestError("invalid order list shape")
    result = RgOrderPage(items=items, next_token=token or None)
    assert_agent_safe_value(
        {
            "items": [
                {"order_id": row.order_id, "paid_at": row.paid_at, "lines": row.lines}
                for row in result.items
            ],
            "next_token": result.next_token,
        }
    )
    return result


def _project_product_item(item: object) -> dict[str, object]:
    if not isinstance(item, dict):
        raise RgRequestError("invalid product shape")
    projected: dict[str, object] = {
        "item_name": _safe_text(item.get("itemName"), "product item"),
        "rg_vendor_item_id": None,
        "rg_vendor_inventory_item_id": None,
        "mp_vendor_item_id": None,
    }
    rg_data = item.get("rocketGrowthItemData") or item.get("rocketGrowthItem")
    if rg_data is not None:
        if not isinstance(rg_data, dict):
            raise RgRequestError("invalid product shape")
        projected["rg_vendor_item_id"] = _id_optional(rg_data.get("vendorItemId"), "product item")
        projected["rg_vendor_inventory_item_id"] = _id_optional(
            rg_data.get("vendorInventoryItemId"), "product item"
        )
    mp_data = item.get("marketPlaceItemData") or item.get("marketPlaceItem")
    if mp_data is not None:
        if not isinstance(mp_data, dict):
            raise RgRequestError("invalid product shape")
        projected["mp_vendor_item_id"] = _id_optional(mp_data.get("vendorItemId"), "product item")
    return projected


def _project_product_items(raw: object) -> tuple[dict[str, object], ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list) or len(raw) > MAX_PRODUCT_ITEMS:
        raise RgRequestError("invalid product shape")
    return tuple(_project_product_item(item) for item in raw)


def _registration_type(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or _REGISTRATION_TYPE.fullmatch(value) is None:
        raise RgRequestError("invalid product shape")
    return value


def project_rg_product_list_page(payload: object) -> RgProductListPage:
    """Closed projection of the documented seller-products page. No transport."""
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise RgRequestError("invalid product list shape")
    data = payload["data"]
    if len(data) > MAX_PRODUCT_PAGE_ROWS:
        raise RgRequestError("invalid product list shape")
    items: list[dict[str, object]] = []
    for row in data:
        if not isinstance(row, dict):
            raise RgRequestError("invalid product list shape")
        items.append(
            {
                "seller_product_id": _id_required(row.get("sellerProductId"), "product list"),
                "seller_product_name": _safe_text(row.get("sellerProductName"), "product list"),
                "status_name": _safe_text(row.get("statusName"), "product list"),
                "display_category_code": _id_optional(
                    row.get("displayCategoryCode"), "product list"
                ),
                "registration_type": _registration_type(row.get("registrationType")),
                "items": _project_product_items(row.get("items")),
            }
        )
    token = payload.get("nextToken")
    if token is not None and not isinstance(token, str):
        raise RgRequestError("invalid product list shape")
    result = RgProductListPage(items=tuple(items), next_token=token or None)
    assert_agent_safe_value({"items": result.items, "next_token": result.next_token})
    return result


def project_rg_product_detail(payload: object) -> RgProductDetail:
    """Closed projection of the documented product detail payload. No transport."""
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
        raise RgRequestError("invalid product detail shape")
    row = payload["data"]
    result = RgProductDetail(
        seller_product_id=_id_required(row.get("sellerProductId"), "product detail"),
        seller_product_name=_safe_text(row.get("sellerProductName"), "product detail"),
        display_product_name=_safe_text(row.get("displayProductName"), "product detail"),
        status_name=_safe_text(row.get("statusName"), "product detail"),
        display_category_code=_id_optional(row.get("displayCategoryCode"), "product detail"),
        items=_project_product_items(row.get("items")),
    )
    assert_agent_safe_value(
        {
            "seller_product_id": result.seller_product_id,
            "seller_product_name": result.seller_product_name,
            "display_product_name": result.display_product_name,
            "status_name": result.status_name,
            "display_category_code": result.display_category_code,
            "items": result.items,
        }
    )
    return result


def build_rg_product_list_query(
    vendor_id: object,
    *,
    next_token: object = None,
    max_per_page: object = None,
    seller_product_id: object = None,
    seller_product_name: object = None,
    status: object = None,
    manufacture: object = None,
    created_at: object = None,
) -> tuple[tuple[str, str], ...]:
    """Closed query contract for the documented RG product list filter.

    Pure helper: it returns the parameter pairs and never sends them. The
    shared seller_api URI is not promoted to an RG call from this module.
    """
    query = [
        ("vendorId", _vendor_id(vendor_id)),
        ("businessTypes", "rocketGrowth"),
    ]
    if next_token is not None:
        query.append(("nextToken", _id_required(next_token, "next token")))
    if max_per_page is not None:
        if type(max_per_page) is not int or not 1 <= max_per_page <= 100:
            raise RgRequestError("invalid max per page")
        query.append(("maxPerPage", str(max_per_page)))
    if seller_product_id is not None:
        query.append(("sellerProductId", _id_required(seller_product_id, "seller product id")))
    if seller_product_name is not None:
        if (
            not isinstance(seller_product_name, str)
            or not 1 <= len(seller_product_name) <= 20
            or safe_display_value(seller_product_name) is None
        ):
            raise RgRequestError("invalid seller product name")
        query.append(("sellerProductName", seller_product_name))
    if status is not None:
        if status not in _PRODUCT_STATUSES:
            raise RgRequestError("invalid product status")
        query.append(("status", status))
    if manufacture is not None:
        if (
            not isinstance(manufacture, str)
            or not 1 <= len(manufacture) <= 100
            or safe_display_value(manufacture) is None
        ):
            raise RgRequestError("invalid manufacture")
        query.append(("manufacture", manufacture))
    if created_at is not None:
        query.append(("createdAt", _created_date(created_at)))
    return tuple(query)


class RgFullReader:
    """Local read surface for the official nine. Transport is injected."""

    def __init__(self, transport: RgTransport, vendor_id: str) -> None:
        self._transport = transport
        self._vendor_id = _vendor_id(vendor_id)
        self._reader = RgExtendedReader(transport, vendor_id)

    async def list_orders(
        self,
        *,
        paid_date_from: str,
        paid_date_to: str,
        next_token: str | None = None,
    ) -> RgOrderPage:
        """GET rg/orders. Dates are required yyyymmdd, span at most 30 days."""
        start = _paid_date(paid_date_from, "paid date from")
        end = _paid_date(paid_date_to, "paid date to")
        if end < start or (end - start).days > MAX_PAID_DATE_DAYS:
            raise RgRequestError("invalid paid date range")
        query = [
            ("paidDateFrom", paid_date_from),
            ("paidDateTo", paid_date_to),
        ]
        if next_token is not None:
            query.append(("nextToken", _next_token(next_token)))
        path = f"{RG_VENDOR.format(vendorId=self._vendor_id)}/rg/orders"
        payload = await self._transport.exchange(method="GET", path=path, query=tuple(query))
        return _project_order_list(payload, self._vendor_id)

    async def get_order(self, order_id: str) -> RgOrderDetail:
        return await self._reader.get_order(order_id)

    async def get_inventory_summaries(
        self,
        *,
        vendor_item_id: str | None = None,
        next_token: str | None = None,
    ) -> RgInventoryPage:
        return await self._reader.get_inventory_summaries(
            vendor_item_id=vendor_item_id, next_token=next_token
        )

    async def list_categories(
        self,
        *,
        registration_type: str,
        locale: str | None = None,
    ) -> RgCategoryPage:
        return await self._reader.list_categories(
            registration_type=registration_type, locale=locale
        )

    async def get_category_meta(self, display_category_code: str) -> RgCategoryMeta:
        return await self._reader.get_category_meta(display_category_code)

    async def get_category_tree_page(
        self,
        *,
        page_size: int,
        cursor: str | None = None,
        locale: str | None = None,
    ) -> RgCategoryTreePage:
        """GET display-categories with RFM, then bounded local pagination."""
        if type(page_size) is not int or not 1 <= page_size <= MAX_PAGE_SIZE:
            raise RgCategoryRequestError("invalid page_size")
        validate_category_cursor(cursor)
        query = [("registrationType", "RFM")]
        if locale is not None:
            if locale not in _LOCALES:
                raise RgRequestError("invalid category locale")
            query.append(("locale", locale))
        payload = await self._transport.exchange(
            method="GET", path=DISPLAY_CATEGORIES, query=tuple(query)
        )
        nodes = extract_category_nodes(payload)
        return paginate_rg_category_tree(nodes, page_size=page_size, cursor=cursor)

    def simulate_product_create(self, body: object) -> RgDisabledMutation:
        """Synthetic contract only. Never reaches the transport."""
        return self._reader.simulate_product_create(body)

    def simulate_product_modify(self, body: object) -> RgDisabledMutation:
        """Synthetic contract only. Never reaches the transport."""
        return self._reader.simulate_product_modify(body)
