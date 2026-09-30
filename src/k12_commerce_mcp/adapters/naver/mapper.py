"""Naver provider-to-canonical mapping helpers."""

from __future__ import annotations

import hashlib
import hmac
import re
from datetime import date, datetime
from decimal import Decimal
from html.parser import HTMLParser

from ...models import ClaimState, Money, ProductState


def _product_state(value: object) -> ProductState:
    text = str(value or "").upper()
    if any(part in text for part in ("ON_SALE", "SALE", "ACTIVE", "EXPOSURE")):
        return ProductState.ACTIVE
    if any(part in text for part in ("STOP", "CLOSE", "DELETE", "INACTIVE")):
        return ProductState.INACTIVE
    return ProductState.UNKNOWN

class _PlainTextExtractor(HTMLParser):
    _BLOCKED_TAGS = frozenset({"iframe", "script", "style"})
    _SEPARATOR_TAGS = frozenset(
        {"br", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "p", "tr"}
    )

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._blocked_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        normalized = tag.lower()
        if normalized in self._BLOCKED_TAGS:
            self._blocked_depth += 1
        elif not self._blocked_depth and normalized in self._SEPARATOR_TAGS:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.lower()
        if normalized in self._BLOCKED_TAGS and self._blocked_depth:
            self._blocked_depth -= 1
        elif not self._blocked_depth and normalized in self._SEPARATOR_TAGS:
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if not self._blocked_depth:
            self.parts.append(data)

def _safe_detail_html(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    if re.search(r"(?i)<\s*(?:iframe|script|style)\b", value):
        return None
    parser = _PlainTextExtractor()
    try:
        parser.feed(value)
        parser.close()
    except Exception:
        return None
    cleaned = " ".join("".join(parser.parts).split())
    return cleaned[:100_000] or None

def _digest(secret: str, *parts: object) -> str:
    message = "\x1f".join(str(part) for part in parts)
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()

def _aware(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None

def _decimal(value: object) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = Decimal(str(value))
    except (ValueError, ArithmeticError):
        return None
    return result if result.is_finite() else None

def _money(value: object) -> Money | None:
    amount = _decimal(value)
    return Money(amount=amount, currency="KRW") if amount is not None else None

def _claim_state(value: object) -> ClaimState:
    text = str(value or "").upper()
    if any(part in text for part in ("DONE", "COMPLETED", "FINISHED")):
        return ClaimState.COMPLETED
    if any(part in text for part in ("REJECT", "WITHDRAW")):
        return ClaimState.REJECTED
    return ClaimState.REQUESTED if text else ClaimState.UNKNOWN


def _first_text(row: dict, keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value
        if isinstance(value, int) and not isinstance(value, bool):
            return str(value)
    return None


def _first_aware(row: dict, keys: tuple[str, ...]) -> datetime | None:
    for key in keys:
        value = _aware(row.get(key))
        if value is not None:
            return value
    return None


def _first_date(row: dict, keys: tuple[str, ...]) -> date | None:
    for key in keys:
        value = row.get(key)
        if isinstance(value, str):
            try:
                return date.fromisoformat(value[:10])
            except ValueError:
                continue
    return None


def _first_money(row: dict, keys: tuple[str, ...]) -> Money | None:
    for key in keys:
        if key in row:
            amount = _money(row.get(key))
            if amount is not None:
                return amount
    return None
