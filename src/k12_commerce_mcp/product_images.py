"""Pure, bounded image-role projections. No fetch, HTML output, or SKU inference."""

from __future__ import annotations

import re
from collections.abc import Iterable
from html.parser import HTMLParser
from typing import Any, TypeVar

from .adapters.base import AdapterInvalidResponseError
from .image_assets import IMAGE_ASSETS, ImageAssetError
from .models.products import ProductImage, ProductImageReference
from .security import UNSAFE_VALUE_PATTERNS


def _withhold_coupang_phone_asset(url: str) -> bool:
    # Withhold only a recognized public CDN asset with the phone pattern alone.
    # Secret/email/query/other-host cases retain whole-result safety rejection.
    return [i for i, pattern in enumerate(UNSAFE_VALUE_PATTERNS) if pattern.search(url)] == [
        1
    ] and re.fullmatch(
        r"https://(?:image|thumbnail6|thumbnail7)\.coupangcdn\.com/image/[A-Za-z0-9_./-]+",
        url,
    ) is not None


_BODY_URL = re.compile(
    r"https://(?:shop-phinf\.pstatic\.net|shopping-phinf\.pstatic\.net|"
    r"image\.coupangcdn\.com|thumbnail6\.coupangcdn\.com|thumbnail7\.coupangcdn\.com)/[^\s<>\\]+"
)


class _BodyImages(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.urls: list[str] = []
        self.withheld = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "img":
            return
        attributes = dict(attrs)
        url = attributes.get("src") or attributes.get("data-src")
        if not isinstance(url, str) or _BODY_URL.fullmatch(url) is None or len(url) > 2048:
            self.withheld = True
            return
        if url not in self.urls:
            self.urls.append(url)
        if len(self.urls) > 100:
            raise AdapterInvalidResponseError("detail image count exceeds bound")


def body_images(value: object) -> tuple[tuple[str, ...], bool]:
    if not isinstance(value, str) or not value.strip():
        return (), False
    if len(value) > 100_000:
        raise AdapterInvalidResponseError("detail content exceeds bound")
    if re.search(r"(?i)<\s*(?:iframe|script|style)\b", value):
        return (), True
    parser = _BodyImages()
    try:
        parser.feed(value)
        parser.close()
    except AdapterInvalidResponseError:
        raise
    except Exception:
        raise AdapterInvalidResponseError("detail content shape is invalid") from None
    return tuple(parser.urls), parser.withheld


class _InertReferenceImages(_BodyImages):
    """Ignore active element subtrees; never evaluate or return their content."""

    def __init__(self):
        super().__init__()
        self._blocked: list[str] = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in {"script", "style", "iframe", "object"}:
            self._blocked.append(tag)
            self.withheld = True
        elif not self._blocked:
            super().handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in self._blocked:
            del self._blocked[self._blocked.index(tag) :]


def body_reference_urls(value: object) -> tuple[str, ...]:
    if not isinstance(value, str) or not value.strip():
        return ()
    if len(value) > 100_000:
        raise AdapterInvalidResponseError("detail content exceeds bound")
    parser = _InertReferenceImages()
    try:
        parser.feed(value)
        parser.close()
    except AdapterInvalidResponseError:
        raise
    except Exception:
        raise AdapterInvalidResponseError("detail content shape is invalid") from None
    return tuple(parser.urls)


def unique_images(images: list[ProductImage]) -> tuple[ProductImage, ...]:
    values = tuple(dict.fromkeys(images))
    if len(values) > 100:
        raise AdapterInvalidResponseError("image role count exceeds bound")
    return values


_RoleItem = TypeVar("_RoleItem", ProductImage, ProductImageReference)

# Representative and per-option images outrank shared detail shots: providers
# repeat the same detail images under every option, so a positional cut would
# drop whole roles while a role-ranked cut only sheds repeated detail entries.
_ROLE_PRIORITY = {
    "representative": 0,
    "additional": 1,
    "option": 1,
    "unclassified": 2,
    "detail": 3,
}


def _bounded_by_role(
    items: tuple[_RoleItem, ...], limit: int
) -> tuple[tuple[_RoleItem, ...], bool]:
    if len(items) <= limit:
        return items, False
    chosen = sorted(range(len(items)), key=lambda i: (_ROLE_PRIORITY[items[i].role], i))[:limit]
    chosen.sort()
    return tuple(items[i] for i in chosen), True


def bounded_role_images(
    images: Iterable[ProductImage], limit: int = 100
) -> tuple[tuple[ProductImage, ...], bool]:
    return _bounded_by_role(tuple(dict.fromkeys(images)), limit)


def bounded_role_refs(
    refs: Iterable[ProductImageReference], limit: int = 100
) -> tuple[tuple[ProductImageReference, ...], bool]:
    return _bounded_by_role(tuple(dict.fromkeys(refs)), limit)


def coupang_branches(row: dict[str, Any], channel: str) -> tuple[dict[str, Any], ...]:
    raw = row.get("items")
    if raw is None:
        return ()
    if not isinstance(raw, list) or len(raw) > 300 or any(not isinstance(i, dict) for i in raw):
        raise AdapterInvalidResponseError("product option rows are invalid")
    result: list[dict[str, Any]] = []
    for item in raw:
        if channel == "coupang_rocket_growth":
            branches = [
                item[k]
                for k in ("rocketGrowthItemData", "rocketGrowthItem")
                if isinstance(item.get(k), dict)
            ]
        else:
            branches = [
                item[k]
                for k in ("marketplaceItemData", "marketPlaceItem", "marketplaceItem")
                if isinstance(item.get(k), dict)
            ]
            if not branches and not any(
                isinstance(item.get(k), dict) for k in ("rocketGrowthItemData", "rocketGrowthItem")
            ):
                branches = [item]
        # Shared parent fields are allowed only through this exact item's branch,
        # never from another item, list position, or the other channel's branch.
        for branch in branches:
            shared = dict(item)
            if branch is not item:
                for key in ("vendorItemId", "salePrice", "stockQuantity", "priceData"):
                    shared.pop(key, None)
            merged = {**shared, **branch}
            for key in (
                "rocketGrowthItemData",
                "rocketGrowthItem",
                "marketplaceItemData",
                "marketPlaceItem",
                "marketplaceItem",
            ):
                merged.pop(key, None)
            result.append(merged)
    return tuple(result)


def coupang_image_url(raw: object) -> str | None:
    if not isinstance(raw, str) or not raw or ".." in raw or raw.startswith(("http:", "//")):
        return None
    url = raw if raw.startswith("https://") else f"https://image.coupangcdn.com/image/{raw}"
    if (
        re.fullmatch(
            r"https://(?:image|thumbnail6|thumbnail7)\.coupangcdn\.com/image/[^\s<>\\]+", url
        )
        is None
        or len(url) > 2048
    ):
        return None
    return url


def _coupang_images(
    row: dict[str, Any], channel: str, *, for_references: bool = False
) -> tuple[tuple[ProductImage, ...], bool, bool]:
    result: list[ProductImage] = []
    withheld = False
    for branch in coupang_branches(row, channel):
        value = branch.get("vendorItemId")
        option_id = (
            str(value)
            if type(value) is int and value > 0
            else value
            if isinstance(value, str) and value.isascii() and value.isdigit() and int(value) > 0
            else None
        )
        images = branch.get("images", [])
        if not isinstance(images, list) or len(images) > 100:
            raise AdapterInvalidResponseError("product images shape is invalid")
        for image in images:
            if not isinstance(image, dict):
                raise AdapterInvalidResponseError("product image row is invalid")
            url = coupang_image_url(image.get("cdnPath") or image.get("vendorPath"))
            if url is None or (not for_references and _withhold_coupang_phone_asset(url)):
                withheld = True
                continue
            role = {"REPRESENTATION": "representative", "DETAIL": "additional"}.get(
                image.get("imageType"), "unclassified"
            )
            result.append(ProductImage(url=url, role=role, external_option_id=option_id))
        groups = branch.get("contents", [])
        if not isinstance(groups, list) or len(groups) > 100:
            raise AdapterInvalidResponseError("product contents shape is invalid")
        for group in groups:
            details = group.get("contentDetails") if isinstance(group, dict) else None
            if details is None:
                continue
            details = details if isinstance(details, list) else [details]
            if len(details) > 100:
                raise AdapterInvalidResponseError("content detail count exceeds bound")
            for detail in details:
                if not isinstance(detail, dict):
                    raise AdapterInvalidResponseError("content detail row is invalid")
                urls: tuple[str, ...] = ()
                if detail.get("detailType") == "IMAGE":
                    raw_url = detail.get("content")
                    url = coupang_image_url(raw_url)
                    if url is not None:
                        urls = (url,)
                    else:
                        withheld = True
                elif detail.get("detailType") == "TEXT":
                    urls, blocked = body_images(detail.get("content"))
                    if for_references:
                        urls = body_reference_urls(detail.get("content"))
                    withheld |= blocked
                for url in urls:
                    if not for_references and _withhold_coupang_phone_asset(url):
                        withheld = True
                    else:
                        result.append(
                            ProductImage(url=url, role="detail", external_option_id=option_id)
                        )
    bounded, truncated = bounded_role_images(result)
    return bounded, withheld, truncated


def coupang_images(row: dict[str, Any], channel: str) -> tuple[tuple[ProductImage, ...], bool]:
    images, withheld, _truncated = _coupang_images(row, channel)
    return images, withheld


def coupang_images_with_truncation(
    row: dict[str, Any], channel: str
) -> tuple[tuple[ProductImage, ...], bool, bool]:
    return _coupang_images(row, channel)


def coupang_image_refs(row: dict[str, Any], channel: str) -> tuple[ProductImageReference, ...]:
    source_images, _withheld, _truncated = _coupang_images(row, channel, for_references=True)
    refs = []
    for image in source_images:
        try:
            reference = IMAGE_ASSETS.register(image.url)
        except ImageAssetError:
            continue
        refs.append(
            ProductImageReference(
                asset_ref=reference, role=image.role, external_option_id=image.external_option_id
            )
        )
    bounded, _truncated = bounded_role_refs(refs)
    return bounded
