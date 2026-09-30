"""Rocket Growth claim provenance: RG docs do not establish cancellation reads.

The prior matching experiment joined general-Coupang returnRequests to RG orders
by ID and asserted a synthetic positive. That join cannot establish provider
coverage; in particular a synthetic match is not a supported RG API. Keep the
provider path closed until an explicit RG contract and live proof exist.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from k12_commerce_mcp.adapters.base import AdapterInvalidRequestError
from k12_commerce_mcp.adapters.coupang import CoupangRocketGrowthAdapter
from k12_commerce_mcp.models import Channel, ImplementationStatus, ResultStatus
from k12_commerce_mcp.server import build_live_service


class NoProvider:
    async def list_rg_orders(self, **kwargs):
        raise AssertionError("RG order GET must not run for unsupported claim")

    async def list_return_requests(self, **kwargs):
        raise AssertionError("general Coupang claim GET must not run for RG")


def credential_file(tmp_path: Path) -> Path:
    path = tmp_path / "marketplace-readonly.env"
    path.write_text(
        "DOR_COUPANG_VENDOR_ID=vendor\n"
        "DOR_COUPANG_ACCESS_KEY=access\n"
        "DOR_COUPANG_SECRET_KEY=secret\n",
        encoding="utf-8",
    )
    path.chmod(0o600)
    return path


def test_rg_claim_capability_is_deferred_not_active(tmp_path: Path) -> None:
    adapter = CoupangRocketGrowthAdapter(NoProvider())
    assert "commerce_get_returns" not in adapter.capabilities
    service = build_live_service(credential_file(tmp_path))
    capability = next(
        item for item in service.get_capabilities(Channel.COUPANG_ROCKET_GROWTH).capabilities
        if item.tool_name == "commerce_get_returns"
    )
    assert capability.implementation_status is ImplementationStatus.DEFERRED


@pytest.mark.parametrize("kind", ["cancel", "return", "exchange", None])
async def test_rg_claim_path_refuses_before_provider_read(kind: str | None) -> None:
    adapter = CoupangRocketGrowthAdapter(NoProvider())
    with pytest.raises(AdapterInvalidRequestError, match="unproven"):
        await adapter.get_returns(page_size=10, kind=kind)


async def test_rg_claim_dispatch_never_reports_observed_empty(tmp_path: Path) -> None:
    service = build_live_service(credential_file(tmp_path))
    adapter = service.registry.get("coupang_rocket_growth")
    adapter.client = NoProvider()
    result = await service.get_returns(
        Channel.COUPANG_ROCKET_GROWTH, page_size=10, kind="cancel"
    )
    assert result.status is ResultStatus.UNSUPPORTED
    assert result.items == ()
    assert result.errors
