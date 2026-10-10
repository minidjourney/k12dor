"""Fail-closed live publisher composition for the approved WRITE tools.

A channel publisher is composed only when its credentials are present AND its
local prerequisites are explicitly configured: the DOR approval database for
every channel, plus the Naver asset root for the Naver image resolver. Absent
or unusable prerequisites keep that channel unavailable; nothing is guessed
or defaulted, and READ composition is unaffected.
"""

from __future__ import annotations

import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .clients.coupang import CoupangClient
from .clients.elevenst_seller import ElevenstSellerClient
from .clients.naver import NaverClient
from .clients.toss import TossShoppingClient
from .credentials import MarketplaceCredentials
from .publishing import (
    CoupangProductPublisher,
    ElevenstProductPublisher,
    NaverProductPublisher,
    TossProductPublisher,
)
from .publishing.dor_approval import DorChannelApprovalVerifier

APPROVAL_DATABASE_KEY = "DOR_APPROVAL_DATABASE"
NAVER_ASSET_ROOT_KEY = "DOR_NAVER_ASSET_ROOT"


@dataclass(frozen=True)
class LivePublishPrerequisites:
    """Local write prerequisites; an unset piece keeps the channel unavailable."""

    dor_database: Path | None = None
    naver_asset_root: Path | None = None


@dataclass(frozen=True)
class LivePublishers:
    """Composed channel publishers; ``None`` means the channel stays unavailable."""

    coupang: CoupangProductPublisher | None = None
    naver: NaverProductPublisher | None = None
    toss: TossProductPublisher | None = None
    elevenst: ElevenstProductPublisher | None = None


class CoupangPublishClient:
    """Bind the publisher's write/readback protocol to the real CoupangClient.

    ``CoupangClient.get_seller_product`` returns the inner ``data`` object (or
    ``None``); the publisher protocol expects the documented ``code``/``data``
    envelope, so the readback is re-wrapped here without widening behavior.
    """

    def __init__(self, client: CoupangClient) -> None:
        self._client = client

    async def create_seller_product(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._client.create_seller_product(payload)

    async def get_seller_product(self, *, seller_product_id: int) -> dict[str, Any]:
        data = await self._client.get_seller_product(str(seller_product_id))
        if data is None:
            return {"code": "ERROR", "data": None}
        return {"code": "SUCCESS", "data": data}


class TossPublishClient:
    """Bind the publisher's write/readback protocol to TossShoppingClient.

    The documented readback is the v2 address — ``get_product_v2`` returns
    the inner ``success`` object there (the bare v1 GET answers 404 for
    products registered through POST /products/v2); the publisher protocol
    expects the documented ``resultType``/``success`` envelope, so the
    readback is re-wrapped here without widening behavior.
    """

    def __init__(self, client: TossShoppingClient) -> None:
        self._client = client

    async def register_product(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._client.register_product(payload)

    async def get_product(self, *, product_id: int) -> dict[str, Any]:
        success = await self._client.get_product_v2(product_id)
        return {"resultType": "SUCCESS", "success": success}


def _configured_path(text: str, key: str) -> Path | None:
    """Extract one absolute path for ``key``; anything else stays unset."""
    prefix = f"{key}="
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line.startswith(prefix):
            continue
        candidate = Path(line[len(prefix) :])
        return candidate if candidate.is_absolute() else None
    return None


def load_publish_prerequisites(credential_file: Path) -> LivePublishPrerequisites:
    """Read non-secret write prerequisites from the credential env file.

    Only the two explicit path keys are read; credential values are never
    materialized here. An absent, unreadable, or non-absolute value keeps the
    corresponding prerequisite unset so the channel fails closed.
    """
    try:
        metadata = credential_file.lstat()
    except OSError:
        return LivePublishPrerequisites()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        return LivePublishPrerequisites()
    try:
        text = credential_file.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return LivePublishPrerequisites()
    return LivePublishPrerequisites(
        dor_database=_configured_path(text, APPROVAL_DATABASE_KEY),
        naver_asset_root=_configured_path(text, NAVER_ASSET_ROOT_KEY),
    )


def _regular_file(path: Path | None) -> Path | None:
    if path is None:
        return None
    try:
        metadata = path.lstat()
    except OSError:
        return None
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        return None
    return path


def _directory(path: Path | None) -> Path | None:
    if path is None:
        return None
    try:
        metadata = path.lstat()
    except OSError:
        return None
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        return None
    return path


def build_live_publishers(
    credentials: MarketplaceCredentials,
    prerequisites: LivePublishPrerequisites,
) -> LivePublishers:
    """Compose channel publishers only where every prerequisite is satisfied.

    The DOR approval database is shared evidence: without it no channel gets
    a publisher. The Naver asset root is a Naver-only prerequisite; Coupang
    and Toss never require it.
    """
    dor_database = _regular_file(prerequisites.dor_database)
    coupang: CoupangProductPublisher | None = None
    naver: NaverProductPublisher | None = None
    toss: TossProductPublisher | None = None
    elevenst: ElevenstProductPublisher | None = None
    if dor_database is not None:
        if credentials.coupang is not None:
            coupang = CoupangProductPublisher(
                client=CoupangPublishClient(CoupangClient(credentials.coupang)),
                approval_verifier=DorChannelApprovalVerifier(
                    dor_database, channel="coupang"
                ),
            )
        naver_asset_root = _directory(prerequisites.naver_asset_root)
        if credentials.naver is not None and naver_asset_root is not None:
            naver = NaverProductPublisher(
                client=NaverClient(credentials.naver),
                asset_root=naver_asset_root,
                approval_verifier=DorChannelApprovalVerifier(
                    dor_database, channel="naver"
                ),
            )
        if credentials.toss is not None:
            toss = TossProductPublisher(
                client=TossPublishClient(TossShoppingClient(credentials.toss)),
                approval_verifier=DorChannelApprovalVerifier(
                    dor_database, channel="toss"
                ),
            )
        if credentials.elevenst is not None:
            # 11st: the seller client already speaks the publisher protocol
            # (register_product_xml / get_product); DOR's channel name is
            # "11st" in approval_records and the channel intent table.
            elevenst = ElevenstProductPublisher(
                client=ElevenstSellerClient(credentials.elevenst),
                approval_verifier=DorChannelApprovalVerifier(
                    dor_database, channel="11st"
                ),
            )
    return LivePublishers(coupang=coupang, naver=naver, toss=toss, elevenst=elevenst)
