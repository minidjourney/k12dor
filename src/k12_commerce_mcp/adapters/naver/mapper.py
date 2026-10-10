"""Naver provider-to-canonical mapping helpers."""

from __future__ import annotations

import hashlib
import hmac
import re
from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal
from html import escape
from html.parser import HTMLParser
from typing import Any

from ...models import ClaimState, Money, ProductState
from ...models.products import ProductContentNotice
from ...security import UNSAFE_VALUE_PATTERNS, is_agent_safe_value
from ..base import AdapterInvalidResponseError


def _product_state(value: object) -> ProductState:
    text = str(value or "").upper()
    if any(part in text for part in ("ON_SALE", "SALE", "ACTIVE", "EXPOSURE")):
        return ProductState.ACTIVE
    if any(part in text for part in ("STOP", "CLOSE", "DELETE", "INACTIVE")):
        return ProductState.INACTIVE
    return ProductState.UNKNOWN

# Tag-looking text inside a raw-text blocked subtree (e.g. "<iframe><script>
# </iframe>") is a sanitizer-probing polyglot; the whole input stays withheld.
_BLOCKED_RAW_TAG = re.compile(
    r"(?is)<\s*/?\s*(?:script|style|iframe|object|embed|applet|template)\b"
)


class _PlainTextExtractor(HTMLParser):
    _BLOCKED_TAGS = frozenset({"iframe", "script", "style"})
    _SEPARATOR_TAGS = frozenset(
        {"br", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "p", "tr"}
    )

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._blocked_depth = 0
        self.parts: list[str] = []
        self.suspicious = False

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
        if self._blocked_depth:
            self.suspicious |= bool(_BLOCKED_RAW_TAG.search(data))
            return
        self.parts.append(data)

def _safe_detail_html(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    parser = _PlainTextExtractor()
    try:
        parser.feed(value)
        parser.close()
    except Exception:
        return None
    if parser.suspicious:
        return None
    cleaned = " ".join("".join(parser.parts).split())
    return cleaned[:100_000] or None


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

    def __init__(self, check_src: Callable[[str], str | None]) -> None:
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
        self._open(normalized, attrs)
        if normalized not in self._VOID:
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


def _detail_markup(
    value: object, *, check_src: Callable[[str], str | None]
) -> tuple[str | None, bool, bool]:
    """Sanitize one detail-HTML block; withheld/truncated flags stay honest."""
    if not isinstance(value, str) or not value.strip():
        return None, False, False
    if len(value) > 100_000:
        return None, True, False
    parser = _DetailMarkup(check_src)
    try:
        parser.feed(value)
        parser.close()
    except AdapterInvalidResponseError:
        raise
    except Exception:
        raise AdapterInvalidResponseError("detail content shape is invalid") from None
    if parser.suspicious:
        return None, True, parser.truncated
    html = "".join(parser.parts)
    return (html or None), parser.active_seen or parser.withheld, parser.truncated


class _DetailImgSrcs(HTMLParser):
    """Collect <img> src/data-src attributes outside blocked subtrees."""

    _SUBTREE_DROP = _DetailMarkup._SUBTREE_DROP

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocked = 0
        self.srcs: list[str] = []
        self.dropped = False
        self.suspicious = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized = tag.lower()
        if self.blocked:
            if normalized in self._SUBTREE_DROP:
                self.blocked += 1
            return
        if normalized in self._SUBTREE_DROP:
            self.blocked = 1
            return
        self._scan(normalized, attrs)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized = tag.lower()
        if self.blocked or normalized in self._SUBTREE_DROP:
            return
        self._scan(normalized, attrs)

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.lower()
        if self.blocked and normalized in self._SUBTREE_DROP:
            self.blocked -= 1

    def handle_data(self, data: str) -> None:
        if self.blocked and _BLOCKED_RAW_TAG.search(data):
            self.suspicious = True

    def _scan(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "img" or len(attrs) > 20:
            self.dropped |= tag == "img"
            return
        src: str | None = None
        for key, value in attrs:
            if not isinstance(key, str) or key.lower() not in {"src", "data-src"}:
                continue
            if isinstance(value, str) and len(value) <= 2048:
                if src is None:
                    src = value
            else:
                self.dropped = True
        if src is None:
            self.dropped = True
        elif src not in self.srcs:
            self.srcs.append(src)


def _detail_src_scan(
    value: object, check_src: Callable[[str], str | None]
) -> tuple[tuple[str, ...], bool]:
    """Kept detail-image urls plus a withheld flag, under the url policy."""
    if not isinstance(value, str) or not value.strip():
        return (), False
    if len(value) > 100_000:
        raise AdapterInvalidResponseError("detail content exceeds bound")
    parser = _DetailImgSrcs()
    try:
        parser.feed(value)
        parser.close()
    except AdapterInvalidResponseError:
        raise
    except Exception:
        raise AdapterInvalidResponseError("detail content shape is invalid") from None
    if parser.suspicious:
        return (), True
    urls: list[str] = []
    withheld = parser.dropped
    for src in parser.srcs:
        kept = check_src(src)
        if kept is None:
            withheld = True
        elif kept not in urls:
            urls.append(kept)
    if len(urls) > 100:
        raise AdapterInvalidResponseError("detail image count exceeds bound")
    return tuple(urls), withheld


def _redact_unsafe(text: str) -> str:
    cleaned = text
    for pattern in UNSAFE_VALUE_PATTERNS:
        cleaned = pattern.sub(" ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def _notice_safe_text(value: object, *, limit: int) -> tuple[str | None, bool]:
    """(text, withheld): redact unsafe spans, keep the plain remainder."""
    text = _notice_text(value, limit=limit)
    if text is None:
        return None, isinstance(value, (dict, list))
    if is_agent_safe_value(text):
        return text, False
    redacted = _redact_unsafe(text)
    if redacted and is_agent_safe_value(redacted):
        return redacted, True
    return None, True


def _notice_text(value: object, limit: int = 2_000) -> str | None:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if not isinstance(value, str) or not value.strip():
        return None
    text = re.sub(r"<[^>]*>", " ", value)
    text = re.sub(r"(?:https?:)?//[^\s\"'<>]+", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"&nbsp;", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"&amp;", "&", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit] or None


def _notice_items(
    containers: tuple[dict[str, Any], ...],
) -> tuple[tuple[ProductContentNotice, ...], bool]:
    """productInfoProvidedNotice values as {category, name, value|null}."""
    items: list[ProductContentNotice] = []
    withheld = False
    seen: set[ProductContentNotice] = set()
    for container in containers:
        if not isinstance(container, dict):
            continue
        detail = container.get("detailAttribute")
        notice = None
        if isinstance(detail, dict) and isinstance(
            detail.get("productInfoProvidedNotice"), dict
        ):
            notice = detail["productInfoProvidedNotice"]
        elif isinstance(container.get("productInfoProvidedNotice"), dict):
            notice = container["productInfoProvidedNotice"]
        if notice is None:
            continue
        if len(notice) > 200:
            raise AdapterInvalidResponseError("provided notice shape is invalid")
        category, flag = _notice_safe_text(
            notice.get("productInfoProvidedNoticeType"), limit=200
        )
        withheld |= flag
        for key, value in notice.items():
            if key == "productInfoProvidedNoticeType" or not isinstance(key, str):
                continue
            if isinstance(value, dict):
                if len(value) > 200:
                    raise AdapterInvalidResponseError("provided notice shape is invalid")
                group_category = category
                if group_category is None:
                    group_category, flag = _notice_safe_text(key, limit=200)
                    withheld |= flag
                fields = value.items()
            elif isinstance(value, list):
                withheld = True
                continue
            else:
                group_category = category
                fields = ((key, value),)
            for field_name, field_value in fields:
                name, flag = _notice_safe_text(field_name, limit=200)
                withheld |= flag
                if name is None:
                    withheld |= isinstance(field_name, str) and bool(field_name)
                    continue
                text, flag = _notice_safe_text(field_value, limit=2_000)
                withheld |= flag
                item = ProductContentNotice(
                    category=group_category, name=name, value=text
                )
                if item in seen:
                    continue
                seen.add(item)
                items.append(item)
                if len(items) > 500:
                    raise AdapterInvalidResponseError("notice items exceed bound")
    return tuple(items), withheld

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
