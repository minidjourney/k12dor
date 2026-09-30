"""Independent CTO review gates for junior-only facades; no provider calls."""
from __future__ import annotations

from datetime import date

import pytest

from k12_commerce_mcp.adapters.base import AdapterInvalidRequestError
from k12_commerce_mcp.adapters.coupang.general_extended import (
    CoupangGeneralExtendedFacade,
    ExtendedReadError,
)
from k12_commerce_mcp.adapters.naver.extended_reads import NaverExtendedReads
from k12_commerce_mcp.clients.naver import NaverPage
from k12_commerce_mcp.security import assert_agent_safe_value


class FakeNaver:
    def __init__(self) -> None:
        self.calls = 0

    async def list_vat_daily(self, **kwargs: object) -> NaverPage:
        self.calls += 1
        return NaverPage(
            rows=({"email@example.test": "private", "known": "value"},),
            next_cursor=None,
        )

    async def get_category(self, **kwargs: object) -> dict[str, object]:
        return {"id": 1, "name": "email@example.test", "last": True}


async def test_naver_vat_never_echoes_arbitrary_provider_key() -> None:
    facade = NaverExtendedReads(FakeNaver())
    result = await facade.read_vat_daily(
        start_date=date(2026, 9, 1), end_date=date(2026, 9, 1), page_size=1
    )
    assert_agent_safe_value(result)
    assert "email@example.test" not in result.model_dump_json()


async def test_naver_vat_rejects_bad_request_before_transport() -> None:
    fake = FakeNaver()
    facade = NaverExtendedReads(fake)
    with pytest.raises(AdapterInvalidRequestError):
        await facade.read_vat_daily(
            start_date=date(2026, 9, 2), end_date=date(2026, 9, 1), page_size=101
        )
    assert fake.calls == 0


async def test_naver_catalog_rejects_personal_data_in_allowlisted_name() -> None:
    with pytest.raises(Exception) as error:
        await NaverExtendedReads(FakeNaver()).read_category(category_id=1)
    assert "email@example.test" not in str(error.value)


class FakeGeneral:
    channel = "coupang_general"

    async def read_brand(self, brand_id: str) -> object:
        return object()


async def test_general_unknown_adapter_shape_is_not_reported_as_empty() -> None:
    with pytest.raises(ExtendedReadError):
        await CoupangGeneralExtendedFacade(FakeGeneral()).read("brand", brand_id="123")
