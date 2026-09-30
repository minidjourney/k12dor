"""Field-local public certification labels; global PII/raw guards stay strict.

All values are synthetic. Square-bracket notation is supported only for the
certification name, never category titles or arbitrary provider content.
"""

import pytest
from test_naver_category_alphanumeric_get_mcp import (
    _assert_closed_failure,
    _call,
    _category,
    _cert,
)

from k12_commerce_mcp.security import PiiValueError, assert_agent_safe_value


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ("[KC]", "[KC인증]", "전기용품 [KC]", "[ID-01] 어린이제품"))
async def test_public_square_bracket_certification_label(name, monkeypatch):
    provider, result = await _call(
        "Ab12", _category("Ab12", certificationInfos=[_cert(name=name)]), monkeypatch
    )
    body = result.structured_content
    assert body["status"] == "complete"
    assert body["reasons"] == []
    assert body["item"]["certificationInfos"][0]["name"] == name
    assert provider.calls == [("GET", "/v1/categories/Ab12", None)]
    with pytest.raises(PiiValueError):
        assert_agent_safe_value(name)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name",
    (
        "{KC}",
        '{"buyer":"synthetic"}',
        '["KC"]',
        "['KC']",
        '[{"id":0}]',
        "[token=abcdef]",
        "[k=abcdef]",
        "foo:[KC]",
        "foo: [KC]",
        "[KC, HACCP]",
        "[KC] sample@example.com",
        "[KC] 010-0000-0000",
        "[KC] 서울시 강남구 테헤란로 1",
        "[KC] bearer abcdefghijk",
        "[KC] api_key=abcdef",
        "[KC] ?token=abcdef",
        "[KC] [broken",
        "[KC] nested [[ID]]",
    ),
)
async def test_certification_payload_stays_closed(name, monkeypatch):
    provider, result = await _call(
        "Ab12", _category("Ab12", certificationInfos=[_cert(name=name)]), monkeypatch
    )
    _assert_closed_failure(result, provider, name)
    assert result.structured_content["reasons"] == ["unsafe_provider_value"]


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ("name", "wholeCategoryName"))
async def test_label_exception_does_not_extend_to_category_titles(field, monkeypatch):
    provider, result = await _call("Ab12", _category("Ab12", **{field: "[KC]"}), monkeypatch)
    _assert_closed_failure(result, provider, "[KC]")
    assert result.structured_content["reasons"] == ["unsafe_provider_value"]
