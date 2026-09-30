"""Independent bounded Coupang general exchange and return-withdrawal GETs.

Never expose claim addresses, customer data, free text or raw provider errors.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any, Literal

from .models.common import CanonicalModel
from .security import assert_agent_safe_value

BASE = "/v2/providers/openapi/apis/api/v4/vendors"
EXCHANGE_STATUSES = frozenset({"RECEIPT", "PROGRESS", "SUCCESS", "REJECT", "CANCEL"})
DUTIES = frozenset({"COM", "CUS", "COU"})
MAX_ROWS = 100
_TOKEN = re.compile(r"[0-9A-Za-z_-]{1,100}\Z")
_DIGITS = re.compile(r"[0-9]{1,20}\Z")
_DATE_TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\Z")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")


class ExchangeItem(CanonicalModel):
    exchange_id: str
    exchange_status: Literal["RECEIPT", "PROGRESS", "SUCCESS", "REJECT", "CANCEL"]
    created_at: str


class WithdrawItem(CanonicalModel):
    cancel_id: str
    refund_delivery_duty: Literal["COM", "CUS", "COU"]
    created_at: str
    vendor_item_ids: tuple[str, ...]


class ExchangePage(CanonicalModel):
    channel: Literal["coupang_general"]
    status: Literal["complete", "incomplete", "invalid_request", "unavailable"]
    source_endpoint: Literal["coupang:exchangeRequests"]
    items: tuple[ExchangeItem, ...]
    next_token: str | None
    reasons: tuple[str, ...]


class WithdrawPage(CanonicalModel):
    channel: Literal["coupang_general"]
    status: Literal["complete", "incomplete", "invalid_request", "unavailable"]
    source_endpoint: Literal["coupang:returnWithdrawRequests"]
    items: tuple[WithdrawItem, ...]
    next_page_index: str | None
    reasons: tuple[str, ...]


def _closed(model: type[ExchangePage] | type[WithdrawPage], status: str, reason: str):
    field = "next_token" if model is ExchangePage else "next_page_index"
    return model.model_validate(
        {
            "channel": "coupang_general",
            "status": status,
            "source_endpoint": "coupang:exchangeRequests"
            if model is ExchangePage
            else "coupang:returnWithdrawRequests",
            "items": [],
            field: None,
            "reasons": [reason],
        }
    )


def _date_value(value: object, *, timestamp: bool) -> datetime | None:
    pattern = _DATE_TIME if timestamp else _DATE
    if not isinstance(value, str) or not pattern.fullmatch(value):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S" if timestamp else "%Y-%m-%d")
    except ValueError:
        return None


def _id(value: object) -> str | None:
    if type(value) is int and 0 < value < 10**20:
        return str(value)
    if isinstance(value, str) and _DIGITS.fullmatch(value) and int(value) > 0:
        return value
    return None


def _shape(payload: object) -> tuple[list, dict] | None:
    if (
        not isinstance(payload, dict)
        or type(payload.get("code")) is not int
        or payload["code"] != 200
    ):
        return None
    rows = payload.get("data")
    if not isinstance(rows, list) or len(rows) > MAX_ROWS:
        return None
    return rows, payload


def _project_exchange(payload: object) -> ExchangePage:
    parsed = _shape(payload)
    if parsed is None:
        return _closed(ExchangePage, "incomplete", "invalid_provider_shape")
    rows, envelope = parsed
    token = envelope.get("nextToken", "")
    if not isinstance(token, str) or (token and not _TOKEN.fullmatch(token)):
        return _closed(ExchangePage, "incomplete", "invalid_provider_shape")
    projected = []
    for row in rows:
        if not isinstance(row, dict):
            return _closed(ExchangePage, "incomplete", "invalid_provider_shape")
        identifier = _id(row.get("exchangeId"))
        status = row.get("exchangeStatus")
        when = row.get("createdAt")
        if (
            identifier is None
            or not isinstance(status, str)
            or status not in EXCHANGE_STATUSES
            or _date_value(when, timestamp=True) is None
        ):
            return _closed(ExchangePage, "incomplete", "invalid_provider_shape")
        projected.append({"exchange_id": identifier, "exchange_status": status, "created_at": when})
    page = ExchangePage.model_validate(
        {
            "channel": "coupang_general",
            "status": "complete",
            "source_endpoint": "coupang:exchangeRequests",
            "items": projected,
            "next_token": token or None,
            "reasons": [],
        }
    )
    try:
        assert_agent_safe_value(page)
    except ValueError:
        return _closed(ExchangePage, "incomplete", "unsafe_provider_value")
    return page


def _project_withdraw(payload: object) -> WithdrawPage:
    parsed = _shape(payload)
    if parsed is None:
        return _closed(WithdrawPage, "incomplete", "invalid_provider_shape")
    rows, envelope = parsed
    index = envelope.get("nextPageIndex", "")
    if not isinstance(index, str) or (index and (not _DIGITS.fullmatch(index) or int(index) < 1)):
        return _closed(WithdrawPage, "incomplete", "invalid_provider_shape")
    projected = []
    for row in rows:
        if not isinstance(row, dict):
            return _closed(WithdrawPage, "incomplete", "invalid_provider_shape")
        identifier = _id(row.get("cancelId"))
        duty = row.get("refundDeliveryDuty")
        when = row.get("createdAt")
        options = row.get("vendorItemIds")
        if (
            identifier is None
            or not isinstance(duty, str)
            or duty not in DUTIES
            or _date_value(when, timestamp=True) is None
            or not isinstance(options, list)
            or len(options) > MAX_ROWS
        ):
            return _closed(WithdrawPage, "incomplete", "invalid_provider_shape")
        safe_options = [_id(option) for option in options]
        if any(option is None for option in safe_options):
            return _closed(WithdrawPage, "incomplete", "invalid_provider_shape")
        projected.append(
            {
                "cancel_id": identifier,
                "refund_delivery_duty": duty,
                "created_at": when,
                "vendor_item_ids": safe_options,
            }
        )
    page = WithdrawPage.model_validate(
        {
            "channel": "coupang_general",
            "status": "complete",
            "source_endpoint": "coupang:returnWithdrawRequests",
            "items": projected,
            "next_page_index": index or None,
            "reasons": [],
        }
    )
    try:
        assert_agent_safe_value(page)
    except ValueError:
        return _closed(WithdrawPage, "incomplete", "unsafe_provider_value")
    return page


async def read_exchange_requests(
    client: Any | None,
    *,
    created_at_from: object,
    created_at_to: object,
    status: object = None,
    max_per_page: object = None,
    order_id: object = None,
    next_token: object = None,
) -> ExchangePage:
    start = _date_value(created_at_from, timestamp=True)
    end = _date_value(created_at_to, timestamp=True)
    if (
        start is None
        or end is None
        or not start <= end < start + timedelta(days=7)
        or (status is not None and (not isinstance(status, str) or status not in EXCHANGE_STATUSES))
        or (type(max_per_page) is not int and max_per_page is not None)
        or (max_per_page is not None and not 1 <= max_per_page <= 100)
        or (order_id is not None and _id(order_id) is None)
        or (
            next_token is not None
            and (not isinstance(next_token, str) or not _TOKEN.fullmatch(next_token))
        )
    ):
        return _closed(ExchangePage, "invalid_request", "invalid_request")
    if client is None:
        return _closed(ExchangePage, "unavailable", "client_not_configured")
    try:
        vendor = client.credentials.vendor_id
        if not re.fullmatch(r"A[0-9A-Za-z]{3,20}", vendor):
            return _closed(ExchangePage, "unavailable", "client_not_configured")
        query = [("createdAtFrom", created_at_from), ("createdAtTo", created_at_to)]
        for key, value in (
            ("status", status),
            ("orderId", order_id),
            ("nextToken", next_token),
            ("maxPerPage", max_per_page),
        ):
            if value is not None:
                query.append((key, str(value)))
        payload = await client._get(f"{BASE}/{vendor}/exchangeRequests", query)
    except Exception:
        return _closed(ExchangePage, "unavailable", "provider_unavailable")
    return _project_exchange(payload)


async def read_return_withdraw_requests(
    client: Any | None,
    *,
    date_from: object,
    date_to: object,
    page_index: object = 1,
    size_per_page: object = 10,
) -> WithdrawPage:
    start = _date_value(date_from, timestamp=False)
    end = _date_value(date_to, timestamp=False)
    if (
        start is None
        or end is None
        or not start <= end <= start + timedelta(days=6)
        or type(page_index) is not int
        or not 1 <= page_index <= 100_000
        or type(size_per_page) is not int
        or not 1 <= size_per_page <= 100
    ):
        return _closed(WithdrawPage, "invalid_request", "invalid_request")
    if client is None:
        return _closed(WithdrawPage, "unavailable", "client_not_configured")
    try:
        vendor = client.credentials.vendor_id
        if not re.fullmatch(r"A[0-9A-Za-z]{3,20}", vendor):
            return _closed(WithdrawPage, "unavailable", "client_not_configured")
        query = [
            ("dateFrom", date_from),
            ("dateTo", date_to),
            ("pageIndex", str(page_index)),
            ("sizePerPage", str(size_per_page)),
        ]
        payload = await client._get(f"{BASE}/{vendor}/returnWithdrawRequests", query)
    except Exception:
        return _closed(WithdrawPage, "unavailable", "provider_unavailable")
    return _project_withdraw(payload)
