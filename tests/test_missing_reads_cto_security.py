"""CTO safety gates for delegated synthetic-only missing read facades."""
import pytest

from k12_commerce_mcp.adapters.base import AdapterInvalidResponseError
from k12_commerce_mcp.adapters.coupang.general_missing_reads import (
    CoupangGeneralMissingReads,
    MissingReadError,
)
from k12_commerce_mcp.adapters.naver.missing_reads import NaverMissingReads


class GeneralFake:
    def __init__(self, payload):
        self.payload = payload
    async def __call__(self, operation_id, request):
        return self.payload


class NaverFake:
    synthetic = True
    def __init__(self, payload):
        self.payload = payload
    async def exchange(self, *, method, path):
        return 200, self.payload


@pytest.mark.asyncio
async def test_general_brand_page_rejects_more_than_bounded_rows():
    rows = [{"brandId": "KR-5", "brandName": "Safe"}] * 101
    reader = CoupangGeneralMissingReads(GeneralFake({"code": "SUCCESS", "data": rows}))
    with pytest.raises(MissingReadError, match="invalid result shape"):
        await reader.read("enrolled_brands")


@pytest.mark.asyncio
async def test_naver_nested_delivery_days_rejects_more_than_bounded_rows():
    days = [{"id": 1, "regionName": "서울", "usable": True}] * 101
    reader = NaverMissingReads(NaverFake({"id": 1, "hopeDeliveryGroupDays": days}))
    with pytest.raises(AdapterInvalidResponseError, match="invalid"):
        await reader.read_hope_delivery_group(group_id=1)


@pytest.mark.asyncio
async def test_naver_subscription_never_exposes_account_identifier_or_free_reason():
    reader = NaverMissingReads(
        NaverFake(
            {"accountUid": "merchantAccount42", "reason": "internal note", "status": "SUBSCRIBING"}
        )
    )
    result = await reader.read_solution_subscription(account_uid="merchantAccount42")
    assert result.account_uid is None
    assert result.reason is None
