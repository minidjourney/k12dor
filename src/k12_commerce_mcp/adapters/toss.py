"""Toss Shopping read adapter with de-identified, PII-free output."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from ..clients.toss import TossShoppingClient, TossShoppingProviderError
from ..currency_policy import POLICY_CONFIRMED_KRW_BASIS, currency_for_channel
from ..models import (
    Channel,
    ClaimReturn,
    ClaimState,
    Completeness,
    Fulfillment,
    Inventory,
    InventorySource,
    InventorySummary,
    MarketplaceCategory,
    MarketplaceCategoryRequirements,
    MarketplaceNoticeItem,
    MarketplaceRegistrationResource,
    Money,
    Order,
    OrderLine,
    OrderSummary,
    Product,
    ProductContent,
    ProductDetail,
    ProductState,
    ResultStatus,
    Settlement,
    SettlementBasis,
    SettlementSource,
    SourceEvidence,
    StockScope,
    TossRegistrationTemplate,
    TossRegistrationTemplateCandidate,
)
from ..models.claims import ClaimKind
from ..security import is_agent_safe_value
from .base import (
    AdapterInvalidCursorError,
    AdapterInvalidRequestError,
    AdapterInvalidResponseError,
    AdapterUnsupportedError,
)
from .registration import (
    MAX_CATEGORIES,
    MAX_NOTICE_CATEGORIES,
    MAX_NOTICES,
    MAX_RESOURCES,
    _bounded,
    group_descriptors,
    notice_category,
    notice_item,
    registration_resource,
)

KST = ZoneInfo("Asia/Seoul")
ACTIVE_ORDER_STATUSES = frozenset(
    {"PAID", "PREPARING_PRODUCT", "DELIVERING", "DELIVERED", "CONFIRMED_ORDER"}
)
KNOWN_NON_SALES_STATUSES = frozenset(
    {
        "BEFORE_PAYMENT",
        "CANCELED_PAYMENT",
        "CLAIM_REQUESTED_CANCEL",
        "CLAIM_REJECTED_CANCEL",
        "REQUESTED_EXCHANGE",
        "ONGOING_EXCHANGE",
        "COMPLETED_EXCHANGE",
        "CLAIM_REJECTED_EXCHANGE",
        "REQUESTED_RETURN",
        "ONGOING_RETURN",
        "COMPLETED_RETURN",
        "CLAIM_REJECTED_RETURN",
        "CLAIM_COLLECTING",
        "CLAIM_COLLECTED",
        "CLAIM_DELIVERING",
    }
)
ORDER_REF_PREFIX = "toss-store-order-hmac-v1:"
LINE_REF_PREFIX = "toss-store-line-hmac-v1:"
PRODUCT_ACTIVE_STATUSES = frozenset({"EXPOSURE", "ON_SALE", "SELLING"})
PRODUCT_INACTIVE_STATUSES = frozenset({"NO_EXPOSURE", "SUSPENDED", "STOP_SELLING"})
CLAIM_STATE_MAP = {
    "REQUESTED": ClaimState.REQUESTED,
    "ONGOING": ClaimState.REQUESTED,
    "COLLECTING": ClaimState.REQUESTED,
    "COLLECTED": ClaimState.REQUESTED,
    "DELIVERING": ClaimState.REQUESTED,
    "COMPLETED": ClaimState.COMPLETED,
    "REJECTED": ClaimState.REJECTED,
    "CANCELED": ClaimState.REJECTED,
    "WITHDRAWN": ClaimState.REJECTED,
}
CLAIM_KIND_MAP = {
    "CANCEL": ClaimKind.CANCEL,
    "RETURN": ClaimKind.RETURN,
    "EXCHANGE": ClaimKind.EXCHANGE,
}


@dataclass(frozen=True)
class TossOrderSummaryPage:
    items: tuple[Order, ...]
    next_cursor: str | None
    summary: OrderSummary


@dataclass(frozen=True)
class TossProductPage:
    items: tuple[Product, ...]
    next_cursor: str | None


@dataclass(frozen=True)
class TossInventoryPage:
    items: tuple[Inventory, ...]
    next_cursor: str | None
    summary: InventorySummary


@dataclass(frozen=True)
class TossClaimPage:
    items: tuple[ClaimReturn, ...]
    next_cursor: str | None


@dataclass(frozen=True)
class TossSettlementPage:
    items: tuple[Settlement, ...]
    next_cursor: str | None


def _aware_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=KST)
    return parsed


def _iso_date(value: object) -> date | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def _strict_int(value: object) -> int | None:
    if type(value) is int:
        return value
    if isinstance(value, str) and value.isdecimal():
        return int(value)
    return None


def _positive_int(value: object) -> int | None:
    parsed = _strict_int(value)
    return parsed if parsed is not None and parsed > 0 else None


def _nonnegative_int(value: object) -> int | None:
    parsed = _strict_int(value)
    return parsed if parsed is not None and parsed >= 0 else None


def _nonempty_text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


_REGISTRATION_DELIVERY_FIELDS = {
    "deliveryMethod": "delivery_method",
    "deliveryFeeType": "delivery_fee_type",
    "deliveryFee": "delivery_fee",
    "minimumPurchasePrice": "minimum_purchase_price",
    "isJejuAndIslandsMountainsDelivery": "is_jeju_and_islands_mountains_delivery",
    "deliveryDeadline": "delivery_deadline",
    "deliveryLocationId": "delivery_location_id",
    "jejuDeliveryFee": "jeju_delivery_fee",
    "islandsMountainsDeliveryFee": "islands_mountains_delivery_fee",
    "deliveryType": "delivery_type",
    "preparationDays": "preparation_days",
    "deliveryCompanyId": "delivery_company_id",
    "preferredDateType": "preferred_date_type",
    "preferredDateFromDays": "preferred_date_from_days",
    "preferredDateToDays": "preferred_date_to_days",
    "preferredDateFromDate": "preferred_date_from_date",
    "preferredDateToDate": "preferred_date_to_date",
    "deliveryBlockedRegionPolicyId": "delivery_blocked_region_policy_id",
}
_REGISTRATION_EXCHANGE_RETURN_FIELDS = {
    "exchangeRefundLocationId": "exchange_refund_location_id",
    "refundOneWayDeliveryFee": "refund_one_way_delivery_fee",
    "exchangeRoundTripDeliveryFee": "exchange_round_trip_delivery_fee",
    "applicationMethodDescription": "application_method_description",
    "applicationTermDescription": "application_term_description",
}


def _registration_template(row: dict[str, Any]) -> TossRegistrationTemplate | None:
    delivery = row.get("deliveryPolicy")
    exchange_return = row.get("exchangeReturnPolicy")
    if not isinstance(delivery, dict) or not isinstance(exchange_return, dict):
        return None
    projected = {
        "delivery_policy": {
            target: delivery[source]
            for source, target in _REGISTRATION_DELIVERY_FIELDS.items()
            if source in delivery
        },
        "exchange_return_policy": {
            target: exchange_return[source]
            for source, target in _REGISTRATION_EXCHANGE_RETURN_FIELDS.items()
            if source in exchange_return
        },
    }
    if not is_agent_safe_value(projected):
        return None
    try:
        return TossRegistrationTemplate.model_validate(projected)
    except (TypeError, ValueError):
        return None

def _registration_template_candidate(
    row: dict[str, Any],
) -> TossRegistrationTemplateCandidate | None:
    delivery = row.get("deliveryPolicy")
    exchange_return = row.get("exchangeReturnPolicy")
    if not isinstance(delivery, dict) or not isinstance(exchange_return, dict):
        return None
    projected = {
        "delivery_policy": {
            target: delivery[source]
            for source, target in _REGISTRATION_DELIVERY_FIELDS.items()
            if source in delivery
        },
        "exchange_return_policy": {
            target: exchange_return[source]
            for source, target in _REGISTRATION_EXCHANGE_RETURN_FIELDS.items()
            if source in exchange_return
        },
    }
    # Scan even the fields we will omit: a bad provider value must never be
    # smuggled into Agent-visible data or silently treated as a safe blank.
    if not is_agent_safe_value(projected):
        return None
    missing: list[str] = []
    deadline = projected["delivery_policy"].get("delivery_deadline")
    if deadline is not None and (
        not isinstance(deadline, str)
        or re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", deadline) is None
    ):
        projected["delivery_policy"]["delivery_deadline"] = None
        missing.append("delivery_policy.delivery_deadline")
    method = projected["exchange_return_policy"].get("application_method_description")
    if method is None or (isinstance(method, str) and not method.strip()):
        projected["exchange_return_policy"]["application_method_description"] = None
        missing.append("exchange_return_policy.application_method_description")
    if not missing:
        return None
    try:
        return TossRegistrationTemplateCandidate.model_validate(
            {**projected, "missing_fields": missing}
        )
    except (TypeError, ValueError):
        return None


def _product_state(value: object) -> ProductState:
    if not isinstance(value, str):
        return ProductState.UNKNOWN
    normalized = value.strip().upper()
    if normalized in PRODUCT_ACTIVE_STATUSES:
        return ProductState.ACTIVE
    if normalized in PRODUCT_INACTIVE_STATUSES:
        return ProductState.INACTIVE
    return ProductState.UNKNOWN


def _digest(secret: str, label: str, *parts: object) -> str:
    payload = json.dumps(parts, ensure_ascii=True, separators=(",", ":"))
    value = hmac.new(secret.encode(), f"{label}:{payload}".encode(), hashlib.sha256).hexdigest()
    return f"toss-store-{label}-hmac-v1:{value}"


class TossShoppingAdapter:
    """Read allowlisted Toss seller GETs into canonical, de-identified records."""

    channel = "toss_store"
    capabilities = frozenset(
        {
            "commerce_get_orders",
            "commerce_get_order_detail",
            "commerce_get_products",
            "commerce_get_product_detail",
            "commerce_get_inventory",
            "commerce_get_returns",
            "commerce_get_settlements",
            "commerce_get_marketplace_categories",
            "commerce_get_marketplace_category_requirements",
            "commerce_get_marketplace_registration_resources",
        }
    )

    def __init__(
        self,
        client: TossShoppingClient,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        max_pages: int = 1000,
    ) -> None:
        if type(max_pages) is not int or not 1 <= max_pages <= 1000:
            raise ValueError("max_pages must be between 1 and 1000")
        self.client = client
        self._clock = clock
        self._max_pages = max_pages
        self._order_ids: dict[str, int] = {}
        self._order_product_ids: dict[str, list[int]] = {}
        self._line_ids: dict[str, tuple[int, int]] = {}

    def _default_business_date(self) -> date:
        return self._clock().astimezone(KST).date() - timedelta(days=1)

    def _source(self, endpoint: str, basis: str) -> SourceEvidence:
        return SourceEvidence(
            endpoint_id=endpoint,
            method="GET",
            observed_at=self._clock().astimezone(UTC),
            data_basis=basis,
        )

    def _orders_source(self, observed_at: datetime) -> SourceEvidence:
        return SourceEvidence(
            endpoint_id="toss-shopping:orders/v2",
            method="GET",
            observed_at=observed_at,
            data_basis=(
                "provider_price_is_order_total_ordered_at_kst;"
                f"{POLICY_CONFIRMED_KRW_BASIS};not_settlement"
            ),
        )

    def _map_order_product(
        self,
        row: dict[str, Any],
        *,
        order_id: int,
        order_product_id: int,
        quantity: int,
        price: int,
        delivery_fee: int | None,
        ordered_at: datetime,
        currency: str,
        source: SourceEvidence,
        status_recognized: bool = True,
    ) -> Order:
        credentials = self.client.credentials
        product_id = row.get("productId")
        stock_id = row.get("stockId")
        amount = Money(amount=Decimal(price), currency=currency)
        shipping = (
            Money(amount=Decimal(delivery_fee), currency=currency)
            if delivery_fee is not None
            else None
        )
        missing_fields = [
            "paid_at",
            "customer_paid_amount",
            "recognized_revenue",
            "lines.unit_price",
            "lines.master_sku",
        ]
        if delivery_fee is None:
            missing_fields.append("customer_shipping_amount")
        if product_id is None:
            missing_fields.append("lines.external_product_id")
        if stock_id is None:
            missing_fields.append("lines.external_option_id")
        completeness_reasons = [
            "provider_did_not_supply_canonical_fields",
            "not_payment_confirmed_revenue",
        ]
        if not status_recognized:
            completeness_reasons.append("unrecognized_order_product_status")
        order_ref = _digest(
            credentials.secret_key,
            "order",
            credentials.access_key,
            order_id,
        )
        line_ref = _digest(
            credentials.secret_key,
            "line",
            credentials.access_key,
            order_id,
            order_product_id,
        )
        line = OrderLine(
            line_ref=line_ref,
            external_product_id=str(product_id) if product_id is not None else None,
            external_option_id=str(stock_id) if stock_id is not None else None,
            external_sku=None,
            product_name=_nonempty_text(row.get("productName")),
            option_name=_nonempty_text(row.get("optionName")),
            master_sku=None,
            quantity=quantity,
            unit_price=None,
            line_amount=amount,
        )
        order = Order(
            channel=Channel.TOSS_STORE,
            order_ref=order_ref,
            fulfillment=Fulfillment.SELLER_SHIPPED,
            ordered_at=ordered_at,
            paid_at=None,
            ordered_amount=amount,
            customer_paid_amount=None,
            customer_shipping_amount=shipping,
            recognized_revenue=None,
            lines=(line,),
            completeness=Completeness(
                status=ResultStatus.INCOMPLETE,
                missing_fields=tuple(missing_fields),
                reasons=tuple(completeness_reasons),
            ),
            source=source,
        )
        self._order_ids[order_ref] = order_id
        product_ids = self._order_product_ids.setdefault(order_ref, [])
        if order_product_id not in product_ids:
            product_ids.append(order_product_id)
        self._line_ids[line_ref] = (order_id, order_product_id)
        return order

    def _map_order_row(
        self,
        row: dict[str, Any],
        *,
        source: SourceEvidence,
        currency: str,
    ) -> Order | None:
        ordered_at = _aware_datetime(row.get("orderedAt"))
        order_id = _positive_int(row.get("orderId"))
        order_product_id = _positive_int(row.get("orderProductId"))
        quantity = _positive_int(row.get("quantity"))
        price = _nonnegative_int(row.get("price"))
        delivery_fee = _nonnegative_int(row.get("deliveryFee"))
        if (
            ordered_at is None
            or order_id is None
            or order_product_id is None
            or quantity is None
            or price is None
        ):
            return None
        return self._map_order_product(
            row,
            order_id=order_id,
            order_product_id=order_product_id,
            quantity=quantity,
            price=price,
            delivery_fee=delivery_fee,
            ordered_at=ordered_at,
            currency=currency,
            source=source,
        )

    async def get_orders(
        self,
        *,
        page_size: int,
        cursor: str | None = None,
        business_date: date | None = None,
    ) -> TossOrderSummaryPage:
        if type(page_size) is not int or not 1 <= page_size <= 100:
            raise ValueError("page_size must be between 1 and 100")
        if cursor is not None:
            raise AdapterInvalidCursorError("toss orders do not accept provider cursors")
        requested_date = business_date or self._default_business_date()
        observed_at = self._clock().astimezone(UTC)
        policy_currency = currency_for_channel(Channel.TOSS_STORE)
        if policy_currency is None:
            raise RuntimeError("toss store currency policy is not configured")
        source = self._orders_source(observed_at)
        provider_cursor: str | None = None
        seen_cursors: set[str] = set()
        seen_products: dict[int, tuple[int, int, int, int | None, str, str]] = {}
        order_ids: set[int] = set()
        items: list[Order] = []
        total_quantity = 0
        total_sales = 0
        reasons: list[str] = []
        page_count = 0

        while True:
            page = await self.client.list_orders(
                business_date=requested_date,
                page_size=min(page_size, 50),
                cursor=provider_cursor,
            )
            page_count += 1
            provider_page_size = min(page_size, 50)
            if len(page.rows) > provider_page_size:
                reasons.append("provider_page_overfull")
                break
            for row in page.rows:
                ordered_at = _aware_datetime(row.get("orderedAt"))
                if ordered_at is None:
                    reasons.append("invalid_order_row")
                    continue
                if ordered_at.astimezone(KST).date() != requested_date:
                    continue
                order_id = _positive_int(row.get("orderId"))
                order_product_id = _positive_int(row.get("orderProductId"))
                quantity = _positive_int(row.get("quantity"))
                price = _nonnegative_int(row.get("price"))
                delivery_fee = _nonnegative_int(row.get("deliveryFee"))
                if None in {order_id, order_product_id, quantity, price}:
                    reasons.append("invalid_order_row")
                    continue
                assert order_id is not None
                assert order_product_id is not None
                assert quantity is not None
                assert price is not None
                status = row.get("orderProductStatus")
                normalized = (
                    order_id,
                    quantity,
                    price,
                    delivery_fee,
                    status,
                    ordered_at.isoformat(),
                )
                previous = seen_products.get(order_product_id)
                if previous is not None:
                    if previous != normalized:
                        reasons.append("conflicting_order_product_duplicate")
                    else:
                        reasons.append("duplicate_order_product")
                    continue
                seen_products[order_product_id] = normalized
                if status in KNOWN_NON_SALES_STATUSES:
                    continue
                order_ids.add(order_id)
                total_quantity += quantity
                total_sales += price
                items.append(
                    self._map_order_product(
                        row,
                        order_id=order_id,
                        order_product_id=order_product_id,
                        quantity=quantity,
                        price=price,
                        delivery_fee=delivery_fee,
                        ordered_at=ordered_at,
                        currency=policy_currency,
                        source=source,
                        status_recognized=status in ACTIVE_ORDER_STATUSES,
                    )
                )
            next_cursor = page.next_cursor
            if next_cursor is None:
                break
            if page_count >= self._max_pages:
                reasons.append("pagination_limit_exceeded")
                break
            if next_cursor in seen_cursors:
                reasons.append("repeated_provider_cursor")
                break
            seen_cursors.add(next_cursor)
            provider_cursor = next_cursor

        complete_counts = not reasons
        summary_reasons = tuple(dict.fromkeys(reasons))
        return TossOrderSummaryPage(
            items=tuple(items),
            next_cursor=None,
            summary=OrderSummary(
                order_count=len(order_ids) if complete_counts else None,
                sales_quantity=total_quantity if complete_counts else None,
                order_sales=(
                    Money(amount=total_sales, currency=policy_currency)
                    if complete_counts
                    else None
                ),
                status=ResultStatus.COMPLETE if complete_counts else ResultStatus.INCOMPLETE,
                reasons=summary_reasons,
                source=source,
            ),
        )

    async def _order_detail_from_product(
        self, order_ref: str, currency: str
    ) -> Order | None:
        source = self._source(
            "toss-shopping:orders/products/{orderProductId}",
            "provider_order_product_detail",
        )
        for order_product_id in self._order_product_ids.get(order_ref, ()):
            try:
                row = await self.client.get_order_product(order_product_id)
            except TossShoppingProviderError:
                continue
            detail = self._map_order_row(row, source=source, currency=currency)
            if detail is not None and hmac.compare_digest(detail.order_ref, order_ref):
                return detail
        return None

    async def get_order_detail(self, order_ref: str) -> Order | None:
        policy_currency = currency_for_channel(Channel.TOSS_STORE)
        if policy_currency is None:
            raise RuntimeError("toss store currency policy is not configured")
        if order_ref.startswith(ORDER_REF_PREFIX):
            order_id = self._order_ids.get(order_ref)
            if order_id is None:
                return None
            source = self._source(
                "toss-shopping:orders/{orderId}",
                "provider_order_detail",
            )
            row: dict[str, Any] | None = None
            try:
                row = await self.client.get_order(order_id)
            except TossShoppingProviderError:
                row = None
            detail = (
                self._map_order_row(row, source=source, currency=policy_currency)
                if isinstance(row, dict)
                else None
            )
            if detail is not None and hmac.compare_digest(detail.order_ref, order_ref):
                return detail
            return await self._order_detail_from_product(order_ref, policy_currency)
        if order_ref.startswith(LINE_REF_PREFIX):
            ids = self._line_ids.get(order_ref)
            if ids is None:
                return None
            _order_id, order_product_id = ids
            source = self._source(
                "toss-shopping:orders/products/{orderProductId}",
                "provider_order_product_detail",
            )
            try:
                row = await self.client.get_order_product(order_product_id)
            except TossShoppingProviderError:
                return None
            detail = self._map_order_row(row, source=source, currency=policy_currency)
            if detail is None or not any(
                hmac.compare_digest(line.line_ref, order_ref) for line in detail.lines
            ):
                return None
            return detail
        raise AdapterUnsupportedError("unsupported toss shopping order ref")

    async def get_products(
        self, *, page_size: int, cursor: str | None = None
    ) -> TossProductPage:
        if type(page_size) is not int or not 1 <= page_size <= 100:
            raise ValueError("page_size must be between 1 and 100")
        policy_currency = currency_for_channel(Channel.TOSS_STORE)
        if policy_currency is None:
            raise RuntimeError("toss store currency policy is not configured")
        source = self._source(
            "toss-shopping:products/v2",
            f"provider_product_list;{POLICY_CONFIRMED_KRW_BASIS}",
        )
        page = await self.client.list_products(page_size=page_size, cursor=cursor)
        items: list[Product] = []
        for row in page.rows:
            product_id = _positive_int(row.get("id"))
            name = _nonempty_text(row.get("name"))
            # Some numeric seller IDs match the Agent PII scanner's phone
            # pattern. Exclude only that row; one unsafe ID must not make an
            # otherwise safe product-list page unavailable.
            if product_id is None or name is None or not is_agent_safe_value(str(product_id)):
                continue
            sale_price = _nonnegative_int(row.get("salePrice"))
            items.append(
                Product(
                    channel=Channel.TOSS_STORE,
                    external_product_id=str(product_id),
                    external_option_id=None,
                    master_sku=None,
                    name=name,
                    state=_product_state(
                        row.get("exposureStatus") or row.get("status")
                    ),
                    listing_price=(
                        Money(amount=Decimal(sale_price), currency=policy_currency)
                        if sale_price is not None
                        else None
                    ),
                    completeness=Completeness(
                        status=ResultStatus.INCOMPLETE,
                        missing_fields=("master_sku",),
                        reasons=("master_sku_link_not_verified",),
                    ),
                    source=source,
                )
            )
        return TossProductPage(items=tuple(items[:page_size]), next_cursor=page.next_cursor)

    async def get_product_detail(self, external_product_id: str) -> ProductDetail | None:
        if not external_product_id.isdigit():
            return None
        product_id = int(external_product_id)
        if product_id <= 0:
            return None
        endpoint = "toss-shopping:products/{productId}/v2"
        row: dict[str, Any] | None = None
        try:
            row = await self.client.get_product_v2(product_id)
        except TossShoppingProviderError:
            row = None
        if not isinstance(row, dict) or not row:
            endpoint = "toss-shopping:products/{productId}"
            try:
                row = await self.client.get_product(product_id)
            except TossShoppingProviderError:
                row = None
        option_ids: list[str] = []
        try:
            items_page = await self.client.list_product_items(product_id, page_size=100)
        except TossShoppingProviderError:
            # The product detail and its policy were read independently.
            # An optional item-list failure must not discard that observed
            # policy; missing option IDs remain explicitly incomplete below.
            items_page = None
        if items_page is not None:
            for item in items_page.rows:
                item_id = _positive_int(item.get("itemId"))
                if item_id is not None:
                    option_ids.append(str(item_id))
        if isinstance(row, dict):
            stocks = row.get("stocks")
            if isinstance(stocks, list):
                for stock in stocks:
                    if not isinstance(stock, dict):
                        continue
                    item_id = _positive_int(stock.get("itemId"))
                    if item_id is not None:
                        option_ids.append(str(item_id))
        if not isinstance(row, dict):
            return None
        name = _nonempty_text(row.get("name"))
        if name is None:
            return None
        exposure = row.get("exposure")
        model_name = (
            _nonempty_text(exposure.get("serialNumber"))
            if isinstance(exposure, dict)
            else None
        )
        missing = ["master_sku"]
        if not option_ids:
            missing.append("external_option_ids")
        registration_template = _registration_template(row)
        return ProductDetail(
            channel=Channel.TOSS_STORE,
            external_product_id=str(product_id),
            external_option_ids=tuple(dict.fromkeys(option_ids)),
            master_sku=None,
            name=name,
            state=_product_state(row.get("exposureStatus") or row.get("status")),
            brand_name=_nonempty_text(row.get("brandName")),
            category_name=_nonempty_text(row.get("categoryName")),
            model_name=model_name,
            attributes=(),
            registration_template=registration_template,
            registration_template_candidate=(
                _registration_template_candidate(row) if registration_template is None else None
            ),
            completeness=Completeness(
                status=ResultStatus.INCOMPLETE,
                missing_fields=tuple(missing),
                reasons=("master_sku_link_not_verified",),
            ),
            source=self._source(endpoint, "provider_product_detail"),
        )

    async def get_product_content(self, external_product_id: str) -> ProductContent | None:
        raise AdapterUnsupportedError("toss shopping product content is not enabled")

    async def get_inventory(
        self, *, page_size: int, cursor: str | None = None
    ) -> TossInventoryPage:
        if type(page_size) is not int or not 1 <= page_size <= 100:
            raise ValueError("page_size must be between 1 and 100")
        source = self._source(
            "toss-shopping:product-items/grouped-by-products",
            "provider_grouped_product_items",
        )
        observed_at = self._clock().astimezone(UTC)
        page = await self.client.list_grouped_product_items(
            page_size=page_size, cursor=cursor
        )
        items: list[Inventory] = []
        reasons: list[str] = []
        for group in page.rows:
            product_id = _positive_int(group.get("productId"))
            if product_id is None:
                reasons.append("invalid_product_group_row")
                continue
            if group.get("hasMoreItems") is True:
                reasons.append("product_items_truncated")
            product_items = group.get("productItems")
            if not isinstance(product_items, list):
                reasons.append("invalid_product_group_row")
                continue
            for row in product_items:
                if not isinstance(row, dict):
                    reasons.append("invalid_product_item_row")
                    continue
                item_id = _positive_int(row.get("itemId"))
                if item_id is None:
                    reasons.append("invalid_product_item_row")
                    continue
                quantity = _nonnegative_int(row.get("quantity"))
                if quantity is None:
                    reasons.append("product_item_quantity_missing")
                    continue
                items.append(
                    Inventory(
                        channel=Channel.TOSS_STORE,
                        external_product_id=str(product_id),
                        external_option_id=str(item_id),
                        master_sku=None,
                        quantity=quantity,
                        inventory_source=InventorySource.MARKETPLACE_LISTING,
                        stock_scope=StockScope.LISTING_QUANTITY,
                        fulfillment=Fulfillment.SELLER_SHIPPED,
                        observed_at=observed_at,
                        completeness=Completeness(
                            status=ResultStatus.INCOMPLETE,
                            missing_fields=("master_sku",),
                            reasons=("master_sku_link_not_verified",),
                        ),
                        source=source,
                    )
                )
        summary_reasons = tuple(dict.fromkeys(reasons))
        complete = not summary_reasons
        return TossInventoryPage(
            items=tuple(items[:page_size]),
            next_cursor=page.next_cursor,
            summary=InventorySummary(
                item_count=len(items) if complete else None,
                quantity_sum=(
                    sum(item.quantity for item in items) if complete else None
                ),
                status=(
                    ResultStatus.COMPLETE if complete else ResultStatus.INCOMPLETE
                ),
                reasons=summary_reasons,
                source=source,
            ),
        )

    async def get_returns(
        self,
        *,
        page_size: int,
        cursor: str | None = None,
        kind: str | None = None,
    ) -> TossClaimPage:
        if type(page_size) is not int or not 1 <= page_size <= 100:
            raise ValueError("page_size must be between 1 and 100")
        kind_filter = None
        if kind is not None:
            try:
                kind_filter = ClaimKind(kind)
            except ValueError:
                raise AdapterInvalidRequestError(
                    "unsupported claim kind filter"
                ) from None
        credentials = self.client.credentials
        source = self._source("toss-shopping:claims", "provider_claim_list")
        page = await self.client.list_claims(page_size=page_size, cursor=cursor)
        items: list[ClaimReturn] = []
        for row in page.rows:
            claim_id = _positive_int(row.get("id"))
            order = row.get("order") if isinstance(row.get("order"), dict) else {}
            product = row.get("product") if isinstance(row.get("product"), dict) else {}
            order_id = _positive_int(order.get("id"))
            order_product_id = _positive_int(order.get("orderProductId"))
            quantity = _positive_int(product.get("quantity"))
            requested_at = _aware_datetime(row.get("requestedDt"))
            if (
                claim_id is None
                or order_id is None
                or quantity is None
                or requested_at is None
            ):
                continue
            status = row.get("status")
            state = (
                CLAIM_STATE_MAP.get(status.strip().upper(), ClaimState.UNKNOWN)
                if isinstance(status, str)
                else ClaimState.UNKNOWN
            )
            claim_type = row.get("type")
            claim_kind = (
                CLAIM_KIND_MAP.get(claim_type.strip().upper())
                if isinstance(claim_type, str)
                else None
            )
            if kind_filter is not None and claim_kind is not kind_filter:
                continue
            missing = ["refund_amount"]
            completed_at = _aware_datetime(row.get("completedDt"))
            if completed_at is None:
                missing.append("completed_at")
            items.append(
                ClaimReturn(
                    channel=Channel.TOSS_STORE,
                    claim_ref=_digest(
                        credentials.secret_key,
                        "claim",
                        credentials.access_key,
                        claim_id,
                        order_id,
                        order_product_id,
                    ),
                    order_ref=_digest(
                        credentials.secret_key,
                        "order",
                        credentials.access_key,
                        order_id,
                    ),
                    state=state,
                    kind=claim_kind,
                    quantity=quantity,
                    requested_at=requested_at,
                    completed_at=completed_at,
                    refund_amount=None,
                    completeness=Completeness(
                        status=ResultStatus.INCOMPLETE,
                        missing_fields=tuple(missing),
                        reasons=("provider_did_not_supply_canonical_fields",),
                    ),
                    source=source,
                )
            )
        return TossClaimPage(items=tuple(items[:page_size]), next_cursor=page.next_cursor)

    async def get_settlements(
        self,
        *,
        page_size: int,
        cursor: str | None = None,
        date_condition: str = "PAYOUT_BASE_DATE",
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> TossSettlementPage:
        if type(page_size) is not int or not 1 <= page_size <= 100:
            raise ValueError("page_size must be between 1 and 100")
        policy_currency = currency_for_channel(Channel.TOSS_STORE)
        if policy_currency is None:
            raise RuntimeError("toss store currency policy is not configured")
        credentials = self.client.credentials
        day = self._default_business_date()
        range_from = date_from or day
        range_to = date_to or day
        source = self._source(
            "toss-shopping:settlement-steps",
            f"provider_settlement_steps;{POLICY_CONFIRMED_KRW_BASIS}",
        )
        page = await self.client.list_settlement_steps(
            date_condition=date_condition,
            date_from=range_from,
            date_to=range_to,
            page_size=page_size,
            cursor=cursor,
        )
        items: list[Settlement] = []
        for row in page.rows:
            order_id = _positive_int(row.get("orderId"))
            order_product_id = _positive_int(row.get("orderProductId"))
            step_type = _nonempty_text(row.get("stepType"))
            period = _iso_date(row.get("payoutBaseDate"))
            if order_id is None or order_product_id is None or period is None:
                continue
            gross = _nonnegative_int(row.get("orderProductPrice"))
            settled = row.get("settlementAmount")
            settled_amount = settled if type(settled) is int else None
            items.append(
                Settlement(
                    channel=Channel.TOSS_STORE,
                    settlement_ref=_digest(
                        credentials.secret_key,
                        "settle",
                        credentials.access_key,
                        order_id,
                        order_product_id,
                        step_type,
                    ),
                    settlement_source=SettlementSource.MARKETPLACE,
                    basis=SettlementBasis.ORDER_LINE,
                    period_start=period,
                    period_end=period,
                    settled_at=_aware_datetime(row.get("transactionTs")),
                    gross_sales=(
                        Money(amount=Decimal(gross), currency=policy_currency)
                        if gross is not None
                        else None
                    ),
                    service_fee=None,
                    settlement_amount=(
                        Money(amount=Decimal(settled_amount), currency=policy_currency)
                        if settled_amount is not None
                        else None
                    ),
                    completeness=Completeness(
                        status=ResultStatus.INCOMPLETE,
                        missing_fields=("service_fee",),
                        reasons=("provider_fee_split_not_canonical",),
                    ),
                    source=source,
                )
            )
        return TossSettlementPage(
            items=tuple(items[:page_size]), next_cursor=page.next_cursor
        )

    async def get_fees(
        self, *, page_size: int, cursor: str | None = None
    ) -> TossOrderSummaryPage:
        raise AdapterUnsupportedError("toss shopping fees are not enabled")

    @staticmethod
    def _category_id(value: str | None, label: str) -> int | None:
        if value is None:
            return None
        if not isinstance(value, str) or not value.isdigit() or int(value) <= 0:
            raise AdapterInvalidRequestError(f"invalid toss shopping {label}")
        return int(value)

    async def get_marketplace_categories(
        self, *, parent_category_id: str | None = None
    ) -> tuple[MarketplaceCategory, ...]:
        parent_id = self._category_id(parent_category_id, "parent category id")
        source = self._source(
            "toss-shopping:products/categories/children",
            "provider_category_children",
        )
        rows = _bounded(
            await self.client.list_category_children(parent_category_id=parent_id),
            MAX_CATEGORIES,
            "category children",
        )
        items: list[MarketplaceCategory] = []
        for row in rows:
            category_id = _positive_int(row.get("id"))
            name = _nonempty_text(row.get("name"))
            is_leaf = row.get("isLeaf")
            if category_id is None or name is None or type(is_leaf) is not bool:
                raise AdapterInvalidResponseError(
                    "toss shopping category row shape is invalid"
                )
            level = row.get("level")
            row_parent = _positive_int(row.get("parentId"))
            items.append(
                MarketplaceCategory(
                    channel=Channel.TOSS_STORE,
                    category_id=str(category_id),
                    parent_category_id=(
                        str(parent_id)
                        if parent_id is not None
                        else str(row_parent) if row_parent is not None else None
                    ),
                    name=name,
                    full_path=None,
                    level=(
                        level if type(level) is int and 2 <= level <= 6 else None
                    ),
                    is_leaf=is_leaf,
                    source=source,
                )
            )
        return tuple(items)

    async def get_marketplace_category_requirements(
        self, *, category_id: str, notice_category_code: str | None = None
    ) -> MarketplaceCategoryRequirements:
        parsed = self._category_id(category_id, "category id")
        assert parsed is not None
        source = self._source(
            "toss-shopping:category/{categoryId}/constraint-templates",
            "provider_constraint_templates",
        )
        templates = await self.client.get_category_constraint_templates(parsed)
        option_lists: list[Any] = []
        for key in ("categorySalesOptions", "categorySearchOptions"):
            rows = templates.get(key)
            if rows is None:
                continue
            if not isinstance(rows, list):
                raise AdapterInvalidResponseError(
                    "toss shopping constraint templates shape is invalid"
                )
            option_lists.extend(rows)
        if not any(
            key in templates
            for key in ("categorySalesOptions", "categorySearchOptions")
        ):
            raise AdapterInvalidResponseError(
                "toss shopping constraint templates shape is invalid"
            )
        code_rows = _bounded(
            await self.client.list_notice_category_codes(),
            MAX_NOTICE_CATEGORIES,
            "notice category codes",
        )
        notices: tuple[MarketplaceNoticeItem, ...] = ()
        if notice_category_code is not None:
            notice_rows = _bounded(
                await self.client.list_notices(category_code=notice_category_code),
                MAX_NOTICES,
                "notices",
            )
            notices = tuple(notice_item(row) for row in notice_rows)
        return MarketplaceCategoryRequirements(
            channel=Channel.TOSS_STORE,
            category_id=str(parsed),
            descriptors=group_descriptors(option_lists),
            notice_categories=tuple(notice_category(row) for row in code_rows),
            notices=notices,
            source=source,
        )

    async def get_marketplace_registration_resources(
        self,
    ) -> tuple[MarketplaceRegistrationResource, ...]:
        delivery_rows = _bounded(
            await self.client.list_delivery_locations_v2(),
            MAX_RESOURCES,
            "delivery locations",
        )
        refund_rows = _bounded(
            await self.client.list_exchange_refund_locations_v2(),
            MAX_RESOURCES,
            "exchange refund locations",
        )
        items: list[MarketplaceRegistrationResource] = []
        for rows, resource_type, endpoint in (
            (
                delivery_rows,
                "delivery_location",
                "toss-shopping:merchants/group-delivery/delivery-location/v2",
            ),
            (
                refund_rows,
                "exchange_refund_location",
                "toss-shopping:merchants/group-delivery/exchange-refund-location/v2",
            ),
        ):
            source = self._source(endpoint, f"provider_{resource_type}")
            for row in rows:
                items.append(
                    registration_resource(
                        row,
                        channel=Channel.TOSS_STORE,
                        resource_type=resource_type,
                        selector_keys=("locationType", "deliveryMethod", "type"),
                        source=source,
                    )
                )
        return tuple(items)
