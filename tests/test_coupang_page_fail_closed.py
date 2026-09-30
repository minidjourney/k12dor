"""An absent or malformed provider page is not a confirmed empty read."""

import pytest

from k12_commerce_mcp.clients.coupang import CoupangClient, CoupangProviderError


@pytest.mark.parametrize(
    "payload",
    [
        {"code": "ERROR", "data": []},
        {"data": None},
        {"data": [None]},
        {"data": [{"id": 1}, "malformed"]},
        {"data": [], "nextToken": []},
    ],
)
def test_shared_coupang_page_refuses_non_page_and_dropped_rows(payload):
    with pytest.raises(CoupangProviderError):
        CoupangClient._page(payload)


def test_shared_coupang_page_allows_explicit_complete_empty_page():
    result = CoupangClient._page({"code": "200", "data": [], "nextToken": None})
    assert result.rows == ()
    assert result.next_token is None


@pytest.mark.parametrize(
    "payload",
    [{"code": "ERROR", "data": []}, {"data": None}, {"data": [None]}],
)
def test_shared_coupang_data_rows_refuses_malformed_or_rejected_body(payload):
    with pytest.raises(CoupangProviderError):
        CoupangClient._data_rows(payload)
