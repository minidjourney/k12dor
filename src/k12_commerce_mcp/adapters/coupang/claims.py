"""Coupang return, exchange, withdraw, and customer-inquiry reads."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from ...clients.coupang import CoupangPage
from ...models import (
    Channel,
    ClaimReturn,
    ClaimState,
    Completeness,
    Money,
    ResultStatus,
)
from ...models.claims import ClaimKind
from ..base import (
    AdapterFailure,
    AdapterInvalidCursorError,
    AdapterInvalidRequestError,
)
from ..mock import MockPage
from .mapper import (
    CURSOR_VERSION,
    KST,
    _aware_datetime,
    _claim_state,
    _decode_cursor,
    _digest,
    _encode_cursor,
    _first_value,
    _money,
    _nonnegative_integer,
    _project,
    _scalar_money,
)

_CLAIM_KINDS = ("return", "exchange", "withdraw", "cancel")
_CLAIM_ID_KEYS = {
    "return": ("receiptId", "claimId"),
    "exchange": ("exchangeId", "receiptId", "claimId"),
    "withdraw": ("returnWithdrawId", "withdrawId", "receiptId", "claimId"),
    "cancel": ("receiptId", "cancelId", "claimId"),
}
_CLAIM_STATUS_KEYS = {
    "return": ("receiptStatus", "status"),
    "exchange": ("exchangeStatus", "receiptStatus", "status"),
    "withdraw": ("withdrawStatus", "receiptStatus", "status"),
    "cancel": ("receiptStatus", "cancelStatus", "status"),
}
_CLAIM_ENDPOINTS = {
    "return": "coupang:returnRequests",
    "exchange": "coupang:exchangeRequests",
    "withdraw": "coupang:returnWithdrawRequests",
    "cancel": "coupang:returnRequests?cancelType=CANCEL",
}
_CLAIM_CANONICAL_KIND = {
    "return": ClaimKind.RETURN,
    "exchange": ClaimKind.EXCHANGE,
    "cancel": ClaimKind.CANCEL,
}
_CLAIM_REQUEST_AT_KEYS = (
    "createdAt",
    "requestedAt",
    "requestAt",
    "returnRequestedAt",
    "exchangeRequestedAt",
)
_CLAIM_COMPLETED_AT_KEYS = (
    "completeConfirmDate",
    "completedAt",
    "confirmDate",
    "completeDate",
)
_CLAIM_QUANTITY_KEYS = (
    "cancelCountSum",
    "exchangeCount",
    "requestQuantity",
    "quantity",
    "cancelCount",
    "returnCount",
)
_CLAIM_ITEM_LIST_KEYS = (
    "returnItems",
    "exchangeItems",
    "exchangeItemDtos",
    "cancelItems",
    "claimItems",
)
_CLAIM_ITEM_QUANTITY_KEYS = (
    "quantity",
    "salesQuantity",
    "exchangeCount",
    "cancelCount",
    "returnCount",
)
_REFUND_VALUE_KEYS = (
    "refundAmount",
    "refundPrice",
    "returnPrice",
    "repaymentAmount",
    "expectedRefundAmount",
)
_REFUND_CONTAINER_KEYS = ("refundInfo", "refund", "settlementInfo", "priceInfo")
_INQUIRY_ID_KEYS = ("inquiryId", "callCenterInquiryId", "onlineInquiryId", "id")
_INQUIRY_REQUESTED_AT_KEYS = ("inquiryAt", "createdAt", "requestedAt", "inquiryDate")


class CoupangClaimsMixin:
    def _claim_quantity(self, row: dict[str, Any]) -> int | None:
        for key in _CLAIM_QUANTITY_KEYS:
            quantity = _nonnegative_integer(row.get(key))
            if quantity:
                return quantity
        total = 0
        for key in _CLAIM_ITEM_LIST_KEYS:
            items = row.get(key)
            for item in items if isinstance(items, list) else []:
                if not isinstance(item, dict):
                    continue
                quantity = next(
                    (
                        value
                        for item_key in _CLAIM_ITEM_QUANTITY_KEYS
                        if (value := _nonnegative_integer(item.get(item_key)))
                    ),
                    None,
                )
                if quantity:
                    total += quantity
        return total or None

    def _claim_identity(self, kind: str, row: dict[str, Any]) -> Any:
        return _first_value(row, _CLAIM_ID_KEYS[kind])

    async def _claim_page(
        self,
        kind: str,
        *,
        date_from: date,
        date_to: date,
        page_size: int,
        token: str | None,
    ) -> CoupangPage:
        method_name = {
            "exchange": "list_exchange_requests",
            "withdraw": "list_return_withdraw_requests",
        }.get(kind, "list_return_requests")
        fetch = getattr(self.client, method_name, None)
        if fetch is None:
            return CoupangPage(rows=(), next_token=None)
        kwargs: dict[str, Any] = {
            "date_from": date_from,
            "date_to": date_to,
            "page_size": page_size,
            "next_token": token,
        }
        if kind == "cancel":
            kwargs["cancel_type"] = "CANCEL"
        return await fetch(**kwargs)

    def _refund_amount(self, detail: dict[str, Any]) -> Money | None:
        candidates: list[dict[str, Any]] = [detail]
        for key in _REFUND_CONTAINER_KEYS:
            nested = detail.get(key)
            if isinstance(nested, dict):
                candidates.append(nested)
        for candidate in candidates:
            for key in _REFUND_VALUE_KEYS:
                refund = _money(candidate.get(key))
                if refund is None:
                    refund = _scalar_money(candidate.get(key))
                if refund is not None:
                    return refund
        return None

    async def _map_claim(
        self,
        kind: str,
        row: dict[str, Any],
        *,
        observed_at: datetime,
    ) -> ClaimReturn | None:
        claim_id = self._claim_identity(kind, row)
        order_id = row.get("orderId")
        requested_at = _aware_datetime(_first_value(row, _CLAIM_REQUEST_AT_KEYS))
        quantity = self._claim_quantity(row)
        if claim_id is None or order_id is None or requested_at is None or quantity is None:
            return None
        state = _claim_state(_first_value(row, _CLAIM_STATUS_KEYS[kind]))
        completed_at = (
            _aware_datetime(_first_value(row, _CLAIM_COMPLETED_AT_KEYS))
            if state is ClaimState.COMPLETED
            else None
        )
        refund_amount = None
        detail_unavailable = False
        get_detail = getattr(self.client, "get_return_request", None)
        if kind in ("return", "cancel") and get_detail is not None:
            try:
                detail = await get_detail(str(claim_id))
            except AdapterFailure:
                detail = None
                detail_unavailable = True
            if detail:
                refund_amount = self._refund_amount(detail)
                if completed_at is None and state is ClaimState.COMPLETED:
                    completed_at = _aware_datetime(
                        _first_value(detail, _CLAIM_COMPLETED_AT_KEYS)
                    )
        missing_fields = [] if refund_amount is not None else ["refund_amount"]
        reasons = []
        if refund_amount is None:
            reasons.append("return_request_does_not_supply_refund_amount")
        if detail_unavailable:
            reasons.append("return_receipt_detail_unavailable")
        return ClaimReturn(
            channel=Channel(self.channel),
            claim_ref=_digest(
                self.client.credentials.secret_key,
                kind,
                self.client.credentials.vendor_id,
                claim_id,
            ),
            order_ref=_digest(
                self.client.credentials.secret_key,
                "order",
                self.client.credentials.vendor_id,
                order_id,
            ),
            state=state,
            kind=_CLAIM_CANONICAL_KIND.get(kind),
            quantity=quantity,
            requested_at=requested_at,
            completed_at=completed_at,
            refund_amount=refund_amount,
            completeness=Completeness(
                status=(
                    ResultStatus.COMPLETE
                    if refund_amount is not None and not detail_unavailable
                    else ResultStatus.INCOMPLETE
                ),
                missing_fields=tuple(missing_fields),
                reasons=tuple(reasons),
            ),
            source=self._source(
                observed_at,
                _CLAIM_ENDPOINTS[kind],
                "provider_return_request",
            ),
        )

    async def get_returns(
        self,
        *,
        page_size: int,
        cursor: str | None = None,
        kind: str | None = None,
    ) -> MockPage[ClaimReturn]:
        if type(page_size) is not int or not 1 <= page_size <= 100:
            raise ValueError("page_size must be between 1 and 100")
        kind_index = 0
        provider_token = None
        if kind is not None:
            try:
                kind_index = _CLAIM_KINDS.index(ClaimKind(kind).value)
            except ValueError:
                raise AdapterInvalidRequestError(
                    "unsupported claim kind filter"
                ) from None
        if cursor is not None:
            state = _decode_cursor(cursor)
            cursor_kind_index = state.get("kind_index")
            provider_token = state.get("provider_token")
            if (
                type(cursor_kind_index) is not int
                or not 0 <= cursor_kind_index < len(_CLAIM_KINDS)
                or (provider_token is not None and not isinstance(provider_token, str))
                or (kind is not None and cursor_kind_index != kind_index)
            ):
                raise AdapterInvalidCursorError("invalid coupang cursor")
            kind_index = cursor_kind_index
        observed_at = self._clock().astimezone(UTC)
        current_day = observed_at.astimezone(KST).date()
        claim_kind = _CLAIM_KINDS[kind_index]
        page = await self._claim_page(
            claim_kind,
            date_from=current_day - timedelta(days=1),
            date_to=current_day,
            page_size=min(page_size, 50),
            token=provider_token,
        )
        claims = []
        if page is not None:
            for row in page.rows:
                claim = await self._map_claim(
                    claim_kind, row, observed_at=observed_at
                )
                if claim is not None:
                    claims.append(claim)
        next_cursor = None
        if page is not None and page.next_token:
            next_cursor = _encode_cursor(
                {
                    "v": CURSOR_VERSION,
                    "kind_index": kind_index,
                    "provider_token": page.next_token,
                }
            )
        elif kind is None and kind_index + 1 < len(_CLAIM_KINDS):
            next_cursor = _encode_cursor(
                {
                    "v": CURSOR_VERSION,
                    "kind_index": kind_index + 1,
                    "provider_token": None,
                }
            )
        return MockPage(items=tuple(claims[:page_size]), next_cursor=next_cursor)

    def _inquiry_projection(
        self,
        kind: str,
        row: dict[str, Any],
    ) -> dict[str, Any]:
        """Digest-only inquiry view; inquiry text and customer fields never pass."""
        inquiry_id = _first_value(row, _INQUIRY_ID_KEYS)
        order_id = row.get("orderId")
        requested_at = _aware_datetime(_first_value(row, _INQUIRY_REQUESTED_AT_KEYS))
        projected = _project(row, ("answeredType", "inquiryStatus", "status"))
        projected["inquiry_kind"] = kind
        if inquiry_id is not None:
            projected["inquiry_ref"] = _digest(
                self.client.credentials.secret_key,
                "inquiry",
                self.client.credentials.vendor_id,
                kind,
                inquiry_id,
            )
        if order_id is not None:
            projected["order_ref"] = _digest(
                self.client.credentials.secret_key,
                "order",
                self.client.credentials.vendor_id,
                order_id,
            )
        if requested_at is not None:
            projected["requested_at"] = requested_at.isoformat()
        return projected

    async def _inquiry_page(
        self,
        kind: str,
        *,
        page_size: int,
        cursor: str | None,
        fetch: Any,
    ) -> MockPage[dict[str, Any]]:
        if type(page_size) is not int or not 1 <= page_size <= 100:
            raise ValueError("page_size must be between 1 and 100")
        page_number = 1
        if cursor is not None:
            if not cursor.isdigit() or int(cursor) < 1:
                raise AdapterInvalidCursorError("invalid coupang cursor")
            page_number = int(cursor)
        observed_at = self._clock().astimezone(UTC)
        current_day = observed_at.astimezone(KST).date()
        page = await fetch(
            date_from=current_day - timedelta(days=1),
            date_to=current_day,
            page_size=min(page_size, 50),
            page_number=page_number,
        )
        next_cursor = str(page_number + 1) if page.next_token else None
        return MockPage(
            items=tuple(self._inquiry_projection(kind, row) for row in page.rows),
            next_cursor=next_cursor,
        )

    async def read_call_center_inquiries(
        self,
        *,
        page_size: int,
        cursor: str | None = None,
    ) -> MockPage[dict[str, Any]]:
        fetch = getattr(self.client, "list_call_center_inquiries", None)
        if fetch is None:
            return MockPage(items=(), next_cursor=None)
        return await self._inquiry_page(
            "call_center",
            page_size=page_size,
            cursor=cursor,
            fetch=fetch,
        )

    async def read_online_inquiries(
        self,
        *,
        page_size: int,
        cursor: str | None = None,
    ) -> MockPage[dict[str, Any]]:
        fetch = getattr(self.client, "list_online_inquiries", None)
        if fetch is None:
            return MockPage(items=(), next_cursor=None)
        return await self._inquiry_page(
            "online",
            page_size=page_size,
            cursor=cursor,
            fetch=fetch,
        )

    async def read_call_center_inquiry(
        self,
        inquiry_id: str,
    ) -> dict[str, Any] | None:
        get_inquiry = getattr(self.client, "get_call_center_inquiry", None)
        if get_inquiry is None:
            return None
        row = await get_inquiry(inquiry_id)
        if row is None:
            return None
        return self._inquiry_projection("call_center", row)


class CoupangRocketGrowthClaimsMixin(CoupangClaimsMixin):
    """No RG cancellation source has been established by the RG-specific docs.

    Matching an RG order identifier against the general Coupang returnRequests
    list does not prove that list covers Rocket Growth claims. Never return a
    general claim as a verified RG cancellation or imply an empty RG day.
    """

    async def get_returns(
        self,
        *,
        page_size: int,
        cursor: str | None = None,
        kind: str | None = None,
    ) -> MockPage[ClaimReturn]:
        raise AdapterInvalidRequestError("rocket growth claims support unproven")
