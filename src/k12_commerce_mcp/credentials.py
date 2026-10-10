"""Strict read-only loader for the existing marketplace credential file."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path

from .clients.coupang import CoupangCredentials
from .clients.elevenst_seller import ElevenstCredentials
from .clients.naver import NaverCredentials
from .clients.toss import TossShoppingCredentials

DEFAULT_CREDENTIAL_FILE = Path.home() / ".config" / "dor" / "marketplace-readonly.env"
MAX_CREDENTIAL_FILE_BYTES = 16_384


class CredentialFileError(RuntimeError):
    """Raised when the local credential container violates its safety contract."""


@dataclass(frozen=True, repr=False)
class MarketplaceCredentials:
    coupang: CoupangCredentials | None = None
    naver: NaverCredentials | None = None
    toss: TossShoppingCredentials | None = None
    elevenst: ElevenstCredentials | None = None

    def __repr__(self) -> str:
        return (
            "MarketplaceCredentials("
            f"coupang_configured={self.coupang is not None}, "
            f"naver_configured={self.naver is not None}, "
            f"toss_configured={self.toss is not None}, "
            f"elevenst_configured={self.elevenst is not None})"
        )


def _parse_env(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key and key.replace("_", "A").isalnum():
            values[key] = value
    return values


def load_marketplace_credentials(
    path: Path = DEFAULT_CREDENTIAL_FILE,
) -> MarketplaceCredentials:
    """Read existing credentials without mutating, logging, or exporting them."""
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise CredentialFileError("credential file is unavailable") from exc
    if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise CredentialFileError("credential path must be a regular non-symlink file")
    if stat.S_IMODE(metadata.st_mode) != 0o600:
        raise CredentialFileError("credential file permissions must be 0600")
    if metadata.st_uid != os.getuid():
        raise CredentialFileError("credential file owner mismatch")
    if metadata.st_size > MAX_CREDENTIAL_FILE_BYTES:
        raise CredentialFileError("credential file exceeds size limit")
    try:
        values = _parse_env(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError) as exc:
        raise CredentialFileError("credential file cannot be read safely") from exc

    coupang_names = (
        "DOR_COUPANG_VENDOR_ID",
        "DOR_COUPANG_ACCESS_KEY",
        "DOR_COUPANG_SECRET_KEY",
    )
    coupang = None
    if all(values.get(name) for name in coupang_names):
        coupang = CoupangCredentials(*(values[name] for name in coupang_names))
    naver_names = (
        "DOR_NAVER_CLIENT_ID",
        "DOR_NAVER_CLIENT_SECRET",
    )
    naver = None
    if all(values.get(name) for name in naver_names):
        naver = NaverCredentials(*(values[name] for name in naver_names))
    toss_names = (
        "DOR_TOSS_SHOPPING_ACCESS_KEY",
        "DOR_TOSS_SHOPPING_SECRET_KEY",
    )
    toss = None
    if all(values.get(name) for name in toss_names):
        toss = TossShoppingCredentials(*(values[name] for name in toss_names))
    elevenst = None
    elevenst_key = values.get("DOR_11ST_API_KEY")
    if elevenst_key:
        try:
            elevenst = ElevenstCredentials(elevenst_key)
        except ValueError:
            # An out-of-shape key value is treated as not configured; the
            # rejected value is never raised, logged, or stored.
            elevenst = None
    return MarketplaceCredentials(
        coupang=coupang, naver=naver, toss=toss, elevenst=elevenst
    )
