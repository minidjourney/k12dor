"""Naver order, detail-cache, and claim reads."""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from ...clients.naver import NaverProviderError, NaverRequestError
from ...models import (
    Channel,
    ClaimReturn,
    ClaimState,
    Completeness,
    Fulfillment,
    Money,
    Order,
    OrderLine,
    ResultStatus,
)
from ...models.claims import ClaimKind
from ..base import (
    AdapterAuthenticationError,
    AdapterFailure,
    AdapterInvalidCursorError,
    AdapterInvalidRequestError,
    AdapterInvalidResponseError,
)
from ..mock import MockPage
from .mapper import _aware, _claim_state, _digest, _first_aware, _first_text, _money

KST = ZoneInfo("Asia/Seoul")

_CLAIM_CHANGE_MARKERS = ("CANCEL", "RETURN", "EXCHANGE", "CLAIM")
_INQUIRY_ID_KEYS = (
    "inquiryId",
    "questionId",
    "commentId",
    "qnaId",
    "qnaNo",
    "inquiryNo",
    "id",
)
_INQUIRY_ORDER_KEYS = ("orderId", "orderNo")
_INQUIRY_REQUESTED_KEYS = (
    "createdDate",
    "createdAt",
    "createdDatetime",
    "registeredDate",
    "questionDate",
    "inquiryDate",
    "writeTime",
)
_INQUIRY_COMPLETED_KEYS = (
    "answeredDate",
    "answeredAt",
    "answerDate",
    "answeredDatetime",
)
_INQUIRY_STATUS_KEYS = ("status", "answerStatus", "inquiryStatus", "qnaStatus")


class NaverOrdersMixin:
    def _map_order(self, row: dict[str, Any], day: date) -> Order | None:
        content = row.get("content") if isinstance(row.get("content"), dict) else row
        order = content.get("order") if isinstance(content.get("order"), dict) else {}
        product = (
            content.get("productOrder")
            if isinstance(content.get("productOrder"), dict)
            else {}
        )
        order_id = order.get("orderId")
        product_order_id = product.get("productOrderId") or row.get("productOrderId")
        ordered_at = _aware(order.get("orderDate"))
        paid_at = _aware(order.get("paymentDate"))
        quantity = product.get("quantity")
        if (
            order_id is None
            or product_order_id is None
            or ordered_at is None
            or (paid_at is not None and paid_at.astimezone(KST).date() != day)
            or type(quantity) is not int
            or quantity <= 0
        ):
            return None
        unit_price = _money(product.get("unitPrice"))
        ordered_amount = _money(product.get("totalProductAmount"))
        customer_paid = _money(product.get("totalPaymentAmount"))
        customer_shipping = _money(product.get("deliveryFeeAmount"))
        if ordered_amount is None and unit_price is not None:
            ordered_amount = Money(
                amount=unit_price.amount * quantity,
                currency="KRW",
            )
        order_ref = _digest(
            self.client.credentials.client_secret,
            "order",
            self.client.credentials.client_id,
            order_id,
        )
        line_ref = _digest(
            self.client.credentials.client_secret,
            "line",
            self.client.credentials.client_id,
            order_id,
            product_order_id,
        )
        external_product_id = product.get("productId")
        # 공식 상품 주문 정보 구조체에는 optionCode 가 없고, 옵션 상품을 구분하는 값은
        # itemNo(옵션·추가 상품 등록 시 자동 생성된 아이템 번호)다. Supabase 연결 표의
        # naver_item_no 와 같은 값. optionCode 는 예전 이름 호환으로만 남긴다(CTO 2026-10-06).
        option_id = product.get("itemNo")
        if option_id in (None, ""):
            option_id = product.get("optionCode")
        product_name = product.get("productName")
        option_name = product.get("productOption")
        line = OrderLine(
            line_ref=line_ref,
            external_product_id=(
                str(external_product_id) if external_product_id is not None else None
            ),
            external_option_id=str(option_id) if option_id is not None else None,
            external_sku=None,
            product_name=(
                product_name.strip()
                if isinstance(product_name, str) and product_name.strip()
                else None
            ),
            option_name=(
                option_name.strip()
                if isinstance(option_name, str) and option_name.strip()
                else None
            ),
            master_sku=None,
            quantity=quantity,
            unit_price=unit_price,
            line_amount=ordered_amount,
        )
        missing = ["recognized_revenue", "lines.master_sku"]
        if paid_at is None:
            missing.append("paid_at")
        if unit_price is None:
            missing.append("lines.unit_price")
        if ordered_amount is None:
            missing.append("ordered_amount")
        if customer_paid is None:
            missing.append("customer_paid_amount")
        result = Order(
            channel=Channel.NAVER,
            order_ref=order_ref,
            fulfillment=Fulfillment.SELLER_SHIPPED,
            ordered_at=ordered_at,
            paid_at=paid_at,
            ordered_amount=ordered_amount,
            customer_paid_amount=customer_paid,
            customer_shipping_amount=customer_shipping,
            recognized_revenue=None,
            lines=(line,),
            completeness=Completeness(
                status=ResultStatus.INCOMPLETE,
                missing_fields=tuple(missing),
                reasons=(
                    "recognized_revenue_not_supplied_by_order_endpoint",
                    "master_sku_link_not_verified",
                    "currency_from_naver_domestic_seller_policy",
                ),
            ),
            source=self._source(
                "naver:pay-order/product-orders",
                "provider_order_original_payed_datetime",
            ),
        )
        self._orders[order_ref] = result
        return result

    async def get_orders(
        self,
        *,
        page_size: int,
        cursor: str | None = None,
        business_date: date | None = None,
    ) -> MockPage[Order]:
        day = business_date or self._day()
        page = await self.client.list_product_orders(
            business_date=day,
            page_size=min(page_size, 300),
            cursor=cursor,
        )
        items = []
        for row in page.rows:
            item = self._map_order(row, day)
            if item is None:
                continue
            product_order_id = self._product_order_id(row)
            if product_order_id is not None:
                self._order_product_ids[item.order_ref] = product_order_id
            items.append(item)
        return MockPage(items=tuple(items[:page_size]), next_cursor=page.next_cursor)

    @staticmethod
    def _product_order_id(row: dict[str, Any]) -> str | None:
        content = row.get("content") if isinstance(row.get("content"), dict) else row
        product = (
            content.get("productOrder")
            if isinstance(content.get("productOrder"), dict)
            else {}
        )
        value = product.get("productOrderId") or row.get("productOrderId")
        return value if isinstance(value, str) and value else None

    async def get_order_detail(self, order_ref: str) -> Order | None:
        cached = self._orders.get(order_ref)
        product_order_id = self._order_product_ids.get(order_ref)
        query = getattr(self.client, "query_product_orders", None)
        if cached is None or product_order_id is None or query is None:
            return cached
        day = (cached.paid_at or cached.ordered_at).astimezone(KST).date()
        for row in await query(product_order_ids=(product_order_id,)):
            refreshed = self._map_order(row, day)
            if refreshed is not None and refreshed.order_ref == order_ref:
                return refreshed
        return cached

    def _map_claim(
        self,
        row: dict[str, Any],
        *,
        endpoint: str,
        basis: str,
        method: str = "GET",
    ) -> ClaimReturn | None:
        content = row.get("content") if isinstance(row.get("content"), dict) else row
        order = content.get("order") if isinstance(content.get("order"), dict) else {}
        product = (
            content.get("productOrder")
            if isinstance(content.get("productOrder"), dict)
            else {}
        )
        block_key = next(
            (
                key
                for key in ("cancel", "return", "exchange")
                if isinstance(content.get(key), dict)
            ),
            None,
        )
        block = content[block_key] if block_key is not None else {}
        order_id = order.get("orderId")
        product_order_id = product.get("productOrderId") or row.get("productOrderId")
        requested_at = _aware(
            block.get("claimRequestDate")
            or block.get("cancelApprovalDate")
            or block.get("cancelCompletedDate")
        )
        quantity = block.get("requestQuantity") or product.get("quantity")
        if (
            order_id is None
            or product_order_id is None
            or requested_at is None
            or type(quantity) is not int
            or quantity <= 0
        ):
            return None
        return ClaimReturn(
            channel=Channel.NAVER,
            claim_ref=_digest(
                self.client.credentials.client_secret,
                "claim",
                self.client.credentials.client_id,
                order_id,
                product_order_id,
            ),
            order_ref=_digest(
                self.client.credentials.client_secret,
                "order",
                self.client.credentials.client_id,
                order_id,
            ),
            state=_claim_state(product.get("claimStatus") or block.get("claimStatus")),
            kind=ClaimKind(block_key) if block_key is not None else None,
            quantity=quantity,
            requested_at=requested_at,
            completed_at=None,
            refund_amount=None,
            completeness=Completeness(
                status=ResultStatus.INCOMPLETE,
                missing_fields=("refund_amount", "completed_at"),
                reasons=("verified_refund_amount_not_supplied",),
            ),
            source=self._source(endpoint, basis, method=method),
        )

    def _map_inquiry(
        self, raw: dict[str, Any], *, endpoint: str, basis: str
    ) -> ClaimReturn | None:
        inquiry_id = _first_text(raw, _INQUIRY_ID_KEYS)
        requested_at = _first_aware(raw, _INQUIRY_REQUESTED_KEYS)
        if inquiry_id is None or requested_at is None:
            return None
        order_id = _first_text(raw, _INQUIRY_ORDER_KEYS)
        completed_at = _first_aware(raw, _INQUIRY_COMPLETED_KEYS)
        answered_flag = raw.get("answered")
        if answered_flag is None:
            answered_flag = raw.get("isAnswered") or raw.get("answerYn")
        answered = completed_at is not None or str(answered_flag).strip().upper() in {
            "TRUE",
            "Y",
            "YES",
        }
        state = _claim_state(_first_text(raw, _INQUIRY_STATUS_KEYS))
        if answered:
            state = ClaimState.COMPLETED
        elif state is ClaimState.UNKNOWN:
            state = ClaimState.REQUESTED
        missing = ["refund_amount"]
        reasons = ["customer_inquiry_record", "inquiry_quantity_is_unit_count"]
        if order_id is None:
            missing.append("order_ref_link")
            reasons.append("inquiry_not_linked_to_order")
        if completed_at is None:
            missing.append("completed_at")
        return ClaimReturn(
            channel=Channel.NAVER,
            claim_ref=_digest(
                self.client.credentials.client_secret,
                "inquiry",
                self.client.credentials.client_id,
                inquiry_id,
            ),
            order_ref=_digest(
                self.client.credentials.client_secret,
                "order",
                self.client.credentials.client_id,
                order_id if order_id is not None else f"inquiry:{inquiry_id}",
            ),
            state=state,
            quantity=1,
            requested_at=requested_at,
            completed_at=completed_at,
            refund_amount=None,
            completeness=Completeness(
                status=ResultStatus.INCOMPLETE,
                missing_fields=tuple(missing),
                reasons=tuple(reasons),
            ),
            source=self._source(endpoint, basis),
        )

    @staticmethod
    def _subcall_failed(exc: Exception) -> bool:
        if isinstance(exc, (AdapterInvalidCursorError, AdapterAuthenticationError)):
            return False
        return isinstance(
            exc, (NaverProviderError, NaverRequestError, AdapterFailure)
        )

    def _degrade_claims(
        self, claims: list[ClaimReturn], degraded: list[str]
    ) -> list[ClaimReturn]:
        return [
            claim.model_copy(
                update={
                    "completeness": claim.completeness.model_copy(
                        update={
                            "status": ResultStatus.INCOMPLETE,
                            "reasons": tuple(
                                dict.fromkeys(
                                    (
                                        *claim.completeness.reasons,
                                        *(
                                            f"claim_subsource_unavailable:{endpoint}"
                                            for endpoint in degraded
                                        ),
                                    )
                                )
                            ),
                        }
                    )
                }
            )
            for claim in claims
        ]

    async def get_returns(
        self,
        *,
        page_size: int,
        cursor: str | None = None,
        kind: str | None = None,
    ) -> MockPage[ClaimReturn]:
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
        day = self._day()
        claims: list[ClaimReturn] = []
        seen: set[str] = set()
        degraded: list[str] = []
        failures: list[Exception] = []
        attempted = 0

        def note_failure(endpoint: str, exc: Exception) -> None:
            degraded.append(endpoint)
            failures.append(exc)

        page = None
        try:
            attempted += 1
            page = await self.client.list_product_orders(
                business_date=day,
                page_size=min(page_size, 300),
                cursor=cursor,
                range_type="CLAIM_REQUESTED_DATETIME",
            )
        except Exception as exc:
            if not self._subcall_failed(exc):
                raise
            note_failure("naver:pay-order/product-orders", exc)
        next_cursor = page.next_cursor if page is not None else None
        if page is not None:
            for row in page.rows:
                claim = self._map_claim(
                    row,
                    endpoint="naver:pay-order/product-orders",
                    basis="provider_claim_requested_datetime",
                )
                if claim is not None and claim.claim_ref not in seen:
                    seen.add(claim.claim_ref)
                    claims.append(claim)
        list_changed = getattr(self.client, "list_last_changed_statuses", None)
        query_orders = getattr(self.client, "query_product_orders", None)
        if list_changed is not None and query_orders is not None:
            changed = None
            try:
                attempted += 1
                changed = await list_changed(
                    changed_from=datetime.combine(day, time.min, tzinfo=KST),
                    page_size=min(page_size, 300),
                )
            except Exception as exc:
                if not self._subcall_failed(exc):
                    raise
                note_failure(
                    "naver:pay-order/product-orders/last-changed-statuses", exc
                )
            if changed is not None:
                changed_ids = []
                for raw in changed.rows:
                    marker = str(raw.get("lastChangeType") or "").upper()
                    product_order_id = raw.get("productOrderId")
                    if (
                        isinstance(product_order_id, str)
                        and product_order_id
                        and any(part in marker for part in _CLAIM_CHANGE_MARKERS)
                    ):
                        changed_ids.append(product_order_id)
                changed_ids = list(dict.fromkeys(changed_ids))[:100]
                if changed_ids:
                    rows: tuple[dict[str, Any], ...] = ()
                    try:
                        attempted += 1
                        rows = await query_orders(product_order_ids=changed_ids)
                    except Exception as exc:
                        if not self._subcall_failed(exc):
                            raise
                        note_failure("naver:pay-order/product-orders/query", exc)
                    for row in rows:
                        claim = self._map_claim(
                            row,
                            endpoint="naver:pay-order/product-orders/query",
                            basis="provider_claim_last_changed_query",
                            method="POST",
                        )
                        if claim is not None and claim.claim_ref not in seen:
                            seen.add(claim.claim_ref)
                            claims.append(claim)
        for method_name, endpoint, basis in (
            ("list_qnas", "naver:contents/qnas", "provider_customer_qna"),
            (
                "list_pay_user_inquiries",
                "naver:pay-user/inquiries",
                "provider_pay_user_inquiry",
            ),
        ):
            fetch = getattr(self.client, method_name, None)
            if fetch is None:
                continue
            inquiry_page = None
            try:
                attempted += 1
                inquiry_page = await fetch(page_size=min(page_size, 100))
            except Exception as exc:
                if not self._subcall_failed(exc):
                    raise
                note_failure(endpoint, exc)
            if inquiry_page is None:
                continue
            for raw in inquiry_page.rows:
                claim = self._map_inquiry(raw, endpoint=endpoint, basis=basis)
                if claim is not None and claim.claim_ref not in seen:
                    seen.add(claim.claim_ref)
                    claims.append(claim)
        if degraded and attempted == len(degraded):
            failure = failures[0]
            if isinstance(failure, AdapterFailure):
                raise failure
            raise AdapterInvalidResponseError(
                "naver claim sub-sources unavailable"
            ) from failure
        if degraded:
            claims = self._degrade_claims(claims, degraded)
        if kind_filter is not None:
            claims = [claim for claim in claims if claim.kind is kind_filter]
        if degraded and not claims:
            # No item exists to carry partial-source completeness. An empty
            # successful sub-source cannot prove a complete empty claim page.
            raise AdapterInvalidResponseError("naver empty claim page has unavailable sub-sources")
        return MockPage(items=tuple(claims[:page_size]), next_cursor=next_cursor)
