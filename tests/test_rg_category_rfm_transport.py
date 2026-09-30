"""RG category GET query must be RFM and never inherit marketplace filter."""
from datetime import UTC, datetime

import httpx
import pytest

from k12_commerce_mcp.clients.coupang import CoupangClient, CoupangCredentials, CoupangRequestError


@pytest.mark.asyncio
async def test_rocket_growth_category_list_uses_exact_rfm_filter() -> None:
    seen = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, tuple(request.url.params.multi_items())))
        return httpx.Response(200, json={"data": []})

    client = CoupangClient(
        CoupangCredentials(vendor_id="A0001", access_key="test", secret_key="test"),
        transport=httpx.MockTransport(respond),
        clock=lambda: datetime(2026, 9, 29, tzinfo=UTC),
    )
    rows = await client.list_display_categories(registration_type="RFM", locale="kr")
    assert rows == ()
    assert seen == [("GET", (("registrationType", "RFM"), ("locale", "kr")))]


@pytest.mark.asyncio
async def test_rfm_query_rejects_unverified_registration_values() -> None:
    def fail_if_sent(_: httpx.Request) -> httpx.Response:
        raise AssertionError("must not send")

    client = CoupangClient(
        CoupangCredentials(vendor_id="A0001", access_key="test", secret_key="test"),
        transport=httpx.MockTransport(fail_if_sent),
    )
    for value in ("CGF", "", "rfm", "RFM/../CGF"):
        with pytest.raises(CoupangRequestError):
            await client.list_display_categories(registration_type=value)
    with pytest.raises(CoupangRequestError):
        await client.list_display_categories(registration_type="RFM", keyword="phone")
