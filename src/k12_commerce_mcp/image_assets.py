"""Bounded ephemeral image references. Source URLs remain in process memory only."""

from __future__ import annotations

import re
from collections import OrderedDict
from hashlib import sha256
from time import monotonic

from .security import UNSAFE_VALUE_PATTERNS

ALLOWED_ASSET_HOSTS = frozenset(
    {
        "shop-phinf.pstatic.net",
        "shopping-phinf.pstatic.net",
        "image.coupangcdn.com",
        "thumbnail6.coupangcdn.com",
        "thumbnail7.coupangcdn.com",
    }
)
_ASSET = re.compile(
    r"https://([a-z0-9.-]+)/((?:[A-Za-z0-9_./-]|%[0-9A-Fa-f]{2})+)(?:\?type=(?:w[1-9][0-9]{1,3}|f[1-9][0-9]{1,3}))?"
)
_REFERENCE = re.compile(r"commerce-asset-v1:[a-p]{64}")


class ImageAssetError(ValueError):
    """Sanitized asset denial; no source location or provider error details."""


def asset_host(url: str) -> str:
    match = _ASSET.fullmatch(url) if isinstance(url, str) and len(url) <= 2048 else None
    if match is None or match[1] not in ALLOWED_ASSET_HOSTS:
        raise ImageAssetError("image location is not eligible")
    try:
        path = (
            re.sub(r"%([0-9A-Fa-f]{2})", lambda m: chr(int(m[1], 16)), match[2])
            .encode("latin1")
            .decode("utf-8")
        )
    except UnicodeError:
        raise ImageAssetError("image location is not eligible") from None
    if (
        re.search(r"(?i)%(?:2f|5c|3f|3a|23|40|25)", match[2])
        or "//" in path
        or any(p in (".", "..") for p in path.split("/"))
        or any(not (c.isalpha() or c.isdecimal() or c in "_./- ") for c in path)
    ):
        raise ImageAssetError("image location is not eligible")
    hits = sorted(
        {i for i, p in enumerate(UNSAFE_VALUE_PATTERNS) if p.search(url) or p.search(path)}
    )
    # Phone-like asset paths are never emitted. They can be fetched by opaque
    # reference, but mixed secrets, email, addresses and arbitrary hosts cannot.
    if hits not in ([], [1]):
        raise ImageAssetError("image location is not eligible")
    return match[1]


class ImageAssetStore:
    def __init__(self, *, capacity: int = 2000, ttl: float = 3600, clock=monotonic):
        if not 1 <= capacity <= 2000 or not 0 < ttl <= 3600:
            raise ValueError("invalid image reference bounds")
        self.capacity, self.ttl, self.clock = capacity, ttl, clock
        self._entries: OrderedDict[str, tuple[float, str]] = OrderedDict()

    def _expire(self) -> None:
        now = self.clock()
        for key in [k for k, (deadline, _) in self._entries.items() if deadline <= now]:
            del self._entries[key]

    def register(self, url: str) -> str:
        asset_host(url)
        self._expire()
        # A one-way digest rendered in letters avoids accidental digit-pattern
        # hits without exempting any value from the existing security gate.
        digest = (
            sha256(url.encode("utf-8"))
            .hexdigest()
            .translate(str.maketrans("0123456789abcdef", "abcdefghijklmnop"))
        )
        reference = "commerce-asset-v1:" + digest
        self._entries[reference] = (self.clock() + self.ttl, url)
        self._entries.move_to_end(reference)
        while len(self._entries) > self.capacity:
            self._entries.popitem(last=False)
        return reference

    def resolve(self, reference: str) -> str:
        if not isinstance(reference, str) or _REFERENCE.fullmatch(reference) is None:
            raise ImageAssetError("image reference is invalid or expired")
        self._expire()
        entry = self._entries.get(reference)
        if entry is None:
            raise ImageAssetError("image reference is invalid or expired")
        return entry[1]


IMAGE_ASSETS = ImageAssetStore()
