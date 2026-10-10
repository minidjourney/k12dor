"""Coupang provider-to-canonical mapping helpers."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from html import escape
from html.parser import HTMLParser
from typing import Any
from zoneinfo import ZoneInfo

from ...models import ClaimState, Money, ProductState
from ...models.products import ProductContentNotice
from ...product_images import _withhold_coupang_phone_asset, coupang_image_url
from ...security import UNSAFE_VALUE_PATTERNS, is_agent_safe_value
from ..base import AdapterInvalidCursorError, AdapterInvalidResponseError

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

# Tag-looking text inside a raw-text blocked subtree (e.g. "<iframe><script>
# </iframe>") is a sanitizer-probing polyglot; the whole input stays withheld.
_BLOCKED_RAW_TAG = re.compile(
    r"(?is)<\s*/?\s*(?:script|style|iframe|object|embed|applet|template)\b"
)
_BLOCKED_SUBTREE = re.compile(
    r"(?is)<\s*(script|style|iframe|object|embed|applet|template)\b[^>]*>"
    r"(.*?)</\s*\1\s*>"
)


def _safe_text(value: object, *, limit: int = 12_000) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    suspicious = False

    def _drop(match: re.Match) -> str:
        nonlocal suspicious
        if _BLOCKED_RAW_TAG.search(match.group(2)):
            suspicious = True
        return " "

    text = _BLOCKED_SUBTREE.sub(_drop, value)
    if suspicious:
        return None
    text = re.sub(r"<[^>]*>", " ", text)
    text = re.sub(r"(?:https?:)?//[^\s\"'<>]+", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"&nbsp;", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"&amp;", "&", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit] or None


def _redact_unsafe(text: str) -> str:
    cleaned = text
    for pattern in UNSAFE_VALUE_PATTERNS:
        cleaned = pattern.sub(" ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def _notice_safe_text(value: object, *, limit: int) -> tuple[str | None, bool]:
    """(text, withheld): redact unsafe spans, keep the plain remainder."""
    text = _safe_text(value, limit=limit)
    if text is None:
        return None, isinstance(value, (dict, list))
    if is_agent_safe_value(text):
        return text, False
    redacted = _redact_unsafe(text)
    if redacted and is_agent_safe_value(redacted):
        return redacted, True
    return None, True


def _detail_text(row: dict[str, Any]) -> str | None:
    blocks: list[str] = []
    items = row.get("items") if isinstance(row.get("items"), list) else []
    for item in (row, *items):
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

class _DetailMarkup(HTMLParser):
    """Re-emit provider detail markup without active content or script attrs."""

    _SUBTREE_DROP = frozenset(
        {"script", "style", "iframe", "object", "embed", "applet", "template"}
    )
    _TAG_DROP = frozenset(
        {
            "base", "link", "meta", "form", "input", "button", "textarea",
            "select", "option", "source", "track", "video", "audio", "svg",
            "math", "canvas", "noscript", "portal", "fencedframe",
        }
    )
    _TEXT_ATTRS = frozenset({"alt", "title", "colspan", "rowspan"})
    _VOID = frozenset({"br", "hr", "img", "wbr", "col"})
    _LIMIT = 100_000

    def __init__(self, check_src) -> None:
        super().__init__(convert_charrefs=True)
        self.check_src = check_src
        self.parts: list[str] = []
        self.length = 0
        self.blocked = 0
        self.withheld = False
        self.truncated = False
        self.active_seen = False
        self.suspicious = False

    def _emit(self, text: str) -> None:
        if self.truncated:
            return
        if self.length + len(text) > self._LIMIT:
            self.truncated = True
            return
        self.parts.append(text)
        self.length += len(text)

    def _clean_attrs(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> tuple[list[tuple[str, str]], str | None]:
        clean: list[tuple[str, str]] = []
        src: str | None = None
        for key, value in attrs:
            if not isinstance(key, str):
                continue
            name = key.lower()
            if name.startswith("on") or name in {"style", "srcset"}:
                continue
            if tag == "img" and name in {"src", "data-src"}:
                if src is None and isinstance(value, str):
                    src = value
                continue
            if tag == "a" and name == "href":
                if (
                    isinstance(value, str)
                    and value.startswith("https://")
                    and len(value) <= 2048
                    and is_agent_safe_value(value)
                ):
                    clean.append(("href", value))
                continue
            if name in self._TEXT_ATTRS and isinstance(value, str) and value.strip():
                clean.append((name, value[:200]))
        return clean, src

    def _open(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        clean, src = self._clean_attrs(tag, attrs)
        if tag == "img":
            if src is None:
                self.withheld = True
                return
            url = self.check_src(src)
            if url is None:
                self.withheld = True
                return
            clean.append(("src", url))
        rendered = "".join(f' {name}="{escape(value, quote=True)}"' for name, value in clean)
        self._emit(f"<{tag}{rendered}>")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized = tag.lower()
        if self.blocked:
            if normalized in self._SUBTREE_DROP:
                self.blocked += 1
            return
        if normalized in self._SUBTREE_DROP:
            self.blocked = 1
            self.active_seen = True
            return
        if normalized in self._TAG_DROP:
            return
        self._open(normalized, attrs)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized = tag.lower()
        if normalized in self._SUBTREE_DROP:
            self.active_seen = True
            return
        if self.blocked or normalized in self._TAG_DROP:
            return
        if normalized == "img" or normalized in self._VOID:
            self._open(normalized, attrs)
            return
        self._open(normalized, attrs)
        self._emit(f"</{normalized}>")

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.lower()
        if self.blocked:
            if normalized in self._SUBTREE_DROP:
                self.blocked -= 1
            return
        if normalized in self._SUBTREE_DROP or normalized in self._TAG_DROP:
            return
        self._emit(f"</{normalized}>")

    def handle_data(self, data: str) -> None:
        if self.blocked:
            self.suspicious |= bool(_BLOCKED_RAW_TAG.search(data))
            return
        self._emit(escape(data, quote=False))


def _coupang_html_src(value: object) -> str | None:
    url = coupang_image_url(value)
    if url is None or _withhold_coupang_phone_asset(url):
        return None
    if not is_agent_safe_value(url):
        raise AdapterInvalidResponseError("detail image is not agent-safe")
    return url


def _detail_markup(value: object) -> tuple[str | None, bool, bool]:
    """Sanitize one detail-HTML block; withheld/truncated flags stay honest."""
    if not isinstance(value, str) or not value.strip():
        return None, False, False
    if len(value) > 100_000:
        return None, True, False
    parser = _DetailMarkup(_coupang_html_src)
    try:
        parser.feed(value)
        parser.close()
    except AdapterInvalidResponseError:
        raise
    except Exception:
        raise AdapterInvalidResponseError("detail content shape is invalid") from None
    if parser.active_seen or parser.suspicious:
        return None, True, parser.truncated
    html = "".join(parser.parts)
    return (html or None), parser.withheld, parser.truncated


def _detail_html(row: dict[str, Any]) -> tuple[str | None, bool, bool]:
    """Provider detail HTML from TEXT content blocks, sanitized per block."""
    blocks: list[str] = []
    withheld = False
    truncated = False
    items = row.get("items") if isinstance(row.get("items"), list) else []
    for item in (row, *items):
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
                        html, flag, cut = _detail_markup(detail.get("content"))
                        withheld |= flag
                        truncated |= cut
                        if html:
                            blocks.append(html)
    return "\n".join(dict.fromkeys(blocks)) or None, withheld, truncated


def _notice_items(
    containers: tuple[dict[str, Any], ...],
) -> tuple[tuple[ProductContentNotice, ...], bool]:
    """noticeCategories/notices entries as {category, name, value|null}; never invented."""
    items: list[ProductContentNotice] = []
    withheld = False
    seen: set[ProductContentNotice] = set()
    for container in containers:
        if not isinstance(container, dict):
            continue
        for key in ("noticeCategories", "notices"):
            categories = container.get(key)
            if categories is None:
                continue
            if not isinstance(categories, list) or len(categories) > 100:
                raise AdapterInvalidResponseError("notice categories are invalid")
            for category_row in categories:
                if not isinstance(category_row, dict):
                    raise AdapterInvalidResponseError("notice category row is invalid")
                category, flag = _notice_safe_text(
                    category_row.get("noticeCategoryName"), limit=200
                )
                withheld |= flag
                details = category_row.get("noticeCategoryDetails")
                if details is None and (
                    category_row.get("noticeCategoryDetailName") is not None
                    or category_row.get("content") is not None
                ):
                    details = [category_row]
                if details is None:
                    continue
                if not isinstance(details, list) or len(details) > 200:
                    raise AdapterInvalidResponseError(
                        "notice category details are invalid"
                    )
                for detail in details:
                    if not isinstance(detail, dict):
                        raise AdapterInvalidResponseError("notice detail row is invalid")
                    name, flag = _notice_safe_text(
                        detail.get("noticeCategoryDetailName"), limit=200
                    )
                    withheld |= flag
                    if name is None:
                        withheld |= detail.get("noticeCategoryDetailName") is not None
                        continue
                    value, flag = _notice_safe_text(detail.get("content"), limit=2_000)
                    withheld |= flag
                    item = ProductContentNotice(
                        category=category, name=name, value=value
                    )
                    if item in seen:
                        continue
                    seen.add(item)
                    items.append(item)
                    if len(items) > 500:
                        raise AdapterInvalidResponseError("notice items exceed bound")
    return tuple(items), withheld


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
