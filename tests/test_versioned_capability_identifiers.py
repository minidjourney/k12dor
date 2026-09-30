"""Version suffixes are valid identifiers, never URI or arbitrary text."""

import pytest
from pydantic import ValidationError

from k12_commerce_mcp.models.results import Capability


@pytest.mark.parametrize(
    "name", ("commerce_get_naver_sku_v1", "commerce_get_naver_sku", "commerce_get_orders")
)
def test_versioned_capability_identifier(name):
    result = Capability(tool_name=name, implementation_status="deferred")
    assert result.tool_name == name


@pytest.mark.parametrize(
    "name",
    (
        "commerce_",
        "commerce_1",
        "commerce_get-sku",
        "commerce_GET",
        "commerce_get/sku",
        "commerce_get?x=1",
        "other_get_sku",
        "commerce_get sku",
    ),
)
def test_capability_identifier_is_not_arbitrary_text(name):
    with pytest.raises(ValidationError):
        Capability(tool_name=name, implementation_status="deferred")
