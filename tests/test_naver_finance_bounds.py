"""Finance read request parameters must match the official read contracts."""

from datetime import date

import httpx
import pytest

from k12_commerce_mcp.clients.naver import NaverClient, NaverCredentials


async def test_finance_pagination_uses_total_pages_without_has_next():
    seen = []

    def handler(request):
        page = int(request.url.params["pageNumber"])
        seen.append(page)
        return httpx.Response(
            200,
            json={
                "elements": [{"commissionAmount": page}],
                "pagination": {"page": page, "size": 1, "totalPages": 2, "totalElements": 2},
            },
        )

    client = NaverClient(
        NaverCredentials("synthetic-client", "synthetic-secret"),
        transport=httpx.MockTransport(handler),
        clock_ms=lambda: 0,
    )
    client._token = "synthetic-token"
    client._token_expires_ms = 1000
    first = await client.list_commission_details(search_date=date(2026, 8, 31), page_size=1)
    assert first.next_cursor == "2"
    second = await client.list_commission_details(
        search_date=date(2026, 8, 31), page_size=1, cursor=first.next_cursor
    )
    assert second.next_cursor is None
    assert seen == [1, 2]


@pytest.mark.parametrize(
    "operation,expected",
    [
        ("list_daily_settlements", {"startDate": "2026-08-31", "endDate": "2026-08-31"}),
        (
            "list_settle_cases",
            {"searchDate": "2026-08-31", "periodType": "SETTLE_CASEBYCASE_SETTLE_BASIS_DATE"},
        ),
        (
            "list_commission_details",
            {"searchDate": "2026-08-31", "periodType": "SETTLE_CASEBYCASE_PAY_DATE"},
        ),
        ("list_vat_daily", {"startDate": "2026-08-31", "endDate": "2026-08-31"}),
        ("list_vat_cases", {"startDate": "2026-08-31", "endDate": "2026-08-31"}),
    ],
)
async def test_finance_contract_uses_documented_paging_fields(operation, expected):
    seen = []

    def handler(request):
        params = dict(request.url.params)
        seen.append(params)
        if params.get("pageNumber") != "1" or params.get("pageSize") != "2":
            return httpx.Response(400, json={})
        if any(params.get(key) != value for key, value in expected.items()):
            return httpx.Response(400, json={})
        return httpx.Response(200, json={"elements": [], "pagination": {"hasNext": False}})

    client = NaverClient(
        NaverCredentials("synthetic-client", "synthetic-secret"),
        transport=httpx.MockTransport(handler),
        clock_ms=lambda: 0,
    )
    client._token = "synthetic-token"
    client._token_expires_ms = 1000
    kwargs = {"page_size": 2}
    if operation == "list_commission_details":
        kwargs["search_date"] = date(2026, 8, 31)
    else:
        kwargs.update(start_date=date(2026, 8, 31), end_date=date(2026, 8, 31))
    result = await getattr(client, operation)(**kwargs)
    assert result.rows == ()
    assert len(seen) == 1
    assert "page" not in seen[0] and "size" not in seen[0]
