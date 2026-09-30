"""Coupang provider-to-canonical mapping helpers."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

from ...models import ClaimState, Money, ProductState
from ..base import AdapterInvalidCursorError

KST = ZoneInfo("Asia/Seoul")
CURSOR_VERSION = 1

def _aware_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None

def _date_value(value: object) -> date | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None

def _decimal(value: object) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None

def _nonnegative_integer(value: object) -> int | None:
    parsed = _decimal(value)
    if parsed is None or parsed < 0 or parsed != parsed.to_integral_value():
        return None
    return int(parsed)

def _rg_paid_at(value: object) -> datetime | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, str)) and str(value).isdigit():
        try:
            return datetime.fromtimestamp(int(str(value)) / 1000, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
    return _aware_datetime(value)

def _money(value: object) -> Money | None:
    if not isinstance(value, dict):
        return None
    currency = value.get("currencyCode")
    units = _decimal(value.get("units"))
    nanos = _decimal(value.get("nanos"))
    if not isinstance(currency, str) or not currency.strip() or (units is None and nanos is None):
        return None
    amount = (units or Decimal(0)) + (nanos or Decimal(0)) / Decimal(1_000_000_000)
    try:
        return Money(amount=amount, currency=currency.strip())
    except ValueError:
        return None

def _scalar_money(value: object, currency: str = "KRW") -> Money | None:
    amount = _decimal(value)
    return Money(amount=amount, currency=currency) if amount is not None else None

def _product_state(value: object) -> ProductState:
    text = str(value or "").strip().lower()
    if text in {"승인완료", "판매중", "active", "approved"}:
        return ProductState.ACTIVE
    if text in {"판매중지", "승인반려", "inactive", "stopped", "rejected"}:
        return ProductState.INACTIVE
    return ProductState.UNKNOWN

def _claim_state(value: object) -> ClaimState:
    normalized = str(value or "").strip().upper()
    if normalized in {
        "RETURNS_COMPLETED",
        "VENDOR_WAREHOUSE_CONFIRM",
        "EXCHANGE_COMPLETED",
        "WITHDRAW_COMPLETED",
        "COMPLETED",
        "SUCCESS",
    }:
        return ClaimState.COMPLETED
    if normalized in {
        "RELEASE_STOP_UNCHECKED",
        "RETURNS_UNCHECKED",
        "REQUEST_COUPANG_CHECK",
        "EXCHANGE_REQUESTED",
        "RETURN_WITHDRAW_REQUESTED",
        "REQUESTED",
        "RECEIPT",
        "PROGRESS",
        "REGISTERED",
    }:
        return ClaimState.REQUESTED
    if normalized in {"REJECTED", "DENIED", "REFUSED", "EXCHANGE_REJECTED"}:
        return ClaimState.REJECTED
    return ClaimState.UNKNOWN

def _safe_text(value: object, *, limit: int = 12_000) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = re.sub(r"<[^>]*>", " ", value)
    text = re.sub(r"(?:https?:)?//[^\s\"'<>]+", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"&nbsp;", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"&amp;", "&", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit] or None

def _detail_text(row: dict[str, Any]) -> str | None:
    blocks: list[str] = []
    items = row.get("items") if isinstance(row.get("items"), list) else []
    for item in items:
        if not isinstance(item, dict):
            continue
        branches = [item]
        for key in ("marketplaceItemData", "marketPlaceItem", "marketplaceItem"):
            if isinstance(item.get(key), dict):
                branches.insert(0, item[key])
        for branch in branches:
            groups = branch.get("contents")
            for group in groups if isinstance(groups, list) else []:
                details = group.get("contentDetails") if isinstance(group, dict) else None
                if not isinstance(details, list):
                    details = [details] if details is not None else []
                for detail in details:
                    if (
                        isinstance(detail, dict)
                        and str(detail.get("detailType", "")).upper() == "TEXT"
                    ):
                        value = _safe_text(detail.get("content"))
                        if value:
                            blocks.append(value)
    return "\n\n".join(dict.fromkeys(blocks))[:12_000] or None

def _image_urls(row: dict[str, Any]) -> tuple[str, ...]:
    host_pattern = r"^https://(?:image|thumbnail6|thumbnail7)\.coupangcdn\.com/image/"
    values: list[str] = []
    items = row.get("items") if isinstance(row.get("items"), list) else []
    for item in items:
        if not isinstance(item, dict):
            continue
        branches = [item]
        for key in ("marketplaceItemData", "marketPlaceItem", "marketplaceItem"):
            if isinstance(item.get(key), dict):
                branches.insert(0, item[key])
        for branch in branches:
            images = branch.get("images")
            for image in images if isinstance(images, list) else []:
                if not isinstance(image, dict):
                    continue
                raw = image.get("cdnPath") or image.get("vendorPath")
                if not isinstance(raw, str) or not raw.strip() or ".." in raw:
                    continue
                url = (
                    raw
                    if raw.startswith("https://")
                    else f"https://image.coupangcdn.com/image/{raw}"
                )
                if re.match(host_pattern, url, flags=re.IGNORECASE):
                    values.append(url)
    return tuple(dict.fromkeys(values))[:100]

def _first_string(row: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _first_value(row: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = row.get(key)
        if value is not None:
            return value
    return None


def _project(row: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    """Whitelist scalar fields for non-canonical reads; never passes nested PII."""
    projected: dict[str, Any] = {}
    for key in fields:
        value = row.get(key)
        if isinstance(value, bool) or type(value) is int:
            projected[key] = value
        elif isinstance(value, str):
            safe = _safe_text(value, limit=500)
            if safe is not None:
                projected[key] = safe
    return projected


def _digest(secret: str, label: str, *parts: object) -> str:
    payload = json.dumps(parts, ensure_ascii=True, separators=(",", ":"))
    value = hmac.new(secret.encode(), f"{label}:{payload}".encode(), hashlib.sha256).hexdigest()
    return f"coupang-{label}-hmac-v1:{value}"

def _encode_cursor(state: dict[str, object]) -> str:
    raw = json.dumps(state, separators=(",", ":"), sort_keys=True).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")

def _decode_cursor(cursor: str) -> dict[str, object]:
    try:
        padding = "=" * (-len(cursor) % 4)
        value = json.loads(base64.urlsafe_b64decode(cursor + padding))
    except (ValueError, UnicodeError, json.JSONDecodeError) as exc:
        raise AdapterInvalidCursorError("invalid coupang cursor") from exc
    if not isinstance(value, dict) or value.get("v") != CURSOR_VERSION:
        raise AdapterInvalidCursorError("invalid coupang cursor")
    return value
