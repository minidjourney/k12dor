"""Partial provider failure must never become a complete empty claim page."""
from datetime import UTC, datetime

import pytest

from k12_commerce_mcp.adapters.base import AdapterInvalidRequestError
from k12_commerce_mcp.adapters.naver import NaverAdapter
from k12_commerce_mcp.clients.naver import NaverPage
from k12_commerce_mcp.models import Channel, ErrorCode, ResultStatus
from k12_commerce_mcp.registry import AdapterRegistry
from k12_commerce_mcp.service.application import CommerceService


class EmptyClaimSources:
    def __init__(self, failed_source: str | None):
        self.failed_source = failed_source
        self.calls: list[str] = []

    def response(self, source: str) -> NaverPage:
        self.calls.append(source)
        if self.failed_source == source:
            raise AdapterInvalidRequestError('synthetic sub-source request rejected')
        return NaverPage(rows=(), next_cursor=None)

    async def list_product_orders(self, **kwargs):
        return self.response('orders')

    async def list_last_changed_statuses(self, **kwargs):
        return self.response('changed')

    async def query_product_orders(self, **kwargs):
        raise AssertionError('No observed IDs: detail query must not run')

    async def list_qnas(self, **kwargs):
        return self.response('qnas')

    async def list_pay_user_inquiries(self, **kwargs):
        return self.response('inquiries')


def service(client: EmptyClaimSources) -> CommerceService:
    adapter = NaverAdapter(client, clock=lambda: datetime(2026, 9, 30, tzinfo=UTC))
    return CommerceService(AdapterRegistry([adapter]))


@pytest.mark.parametrize('failed_source', ['orders', 'changed', 'qnas', 'inquiries'])
@pytest.mark.parametrize('kind', [None, 'return'])
async def test_partial_failure_with_no_claims_is_unavailable(failed_source, kind):
    client = EmptyClaimSources(failed_source)
    result = await service(client).get_returns(Channel.NAVER, page_size=2, kind=kind)
    assert result.status is ResultStatus.UNAVAILABLE
    assert result.items == ()
    assert result.errors[0].code is ErrorCode.INVALID_ADAPTER_RESPONSE
    assert set(client.calls) == {'orders', 'changed', 'qnas', 'inquiries'}


async def test_all_healthy_empty_sources_remain_complete():
    client = EmptyClaimSources(None)
    result = await service(client).get_returns(Channel.NAVER, page_size=2)
    assert result.status is ResultStatus.COMPLETE
    assert result.items == ()
    assert result.errors == ()
