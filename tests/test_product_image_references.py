"""A source URL never bypasses the safety scan; opaque references are additive."""

import pytest
from test_naver_asset_withholding_boundaries import _allowed
from test_product_image_roles import naver, naver_row

from k12_commerce_mcp.models import Channel
from k12_commerce_mcp.registry import AdapterRegistry
from k12_commerce_mcp.security import assert_agent_safe_value
from k12_commerce_mcp.service import CommerceService


async def test_naver_body_images_have_safe_references_even_when_urls_are_withheld():
    url = _allowed("shop-phinf.pstatic.net")
    adapter = naver(naver_row(f'<img src="{url}"><img src="{url}">'))
    result = await CommerceService(AdapterRegistry([adapter])).get_product_content(
        Channel.NAVER, "123"
    )
    assert result.item is not None
    references = [r for r in result.item.image_refs if r.role == "detail"]
    assert len(references) == 1
    assert references[0].asset_ref.startswith("commerce-asset-v1:")
    assert url not in result.model_dump_json()
    assert_agent_safe_value(result)


async def test_standard_option_images_are_returned_with_official_attribute_identifiers():
    from test_product_image_roles import REP
    from test_product_option_linkage import naver_options

    row = naver_options(
        [{"id": 456, "optionName1": "Red", "stockQuantity": 4}], kind="optionStandards"
    )
    row["originProduct"]["detailAttribute"]["optionInfo"]["standardOptionGroups"] = [
        {
            "groupName": "COLOR",
            "standardOptionAttributes": [
                {
                    "attributeId": 11,
                    "attributeValueId": 22,
                    "attributeValueName": "Red",
                    "imageUrls": [REP],
                }
            ],
        }
    ]
    item = await naver(row).get_product_detail("123")
    groups = item.option_image_groups
    assert len(groups) == 1
    assert (groups[0].group_name, groups[0].attribute_id, groups[0].attribute_value_id) == (
        "COLOR",
        "11",
        "22",
    )
    assert groups[0].attribute_value_name == "Red"
    assert groups[0].image_urls == (REP,)
    assert len(groups[0].image_refs) == 1
    assert item.options[0].image_urls == ()  # Attribute ID is NOT the sale-option ID.
    assert_agent_safe_value(item)


@pytest.mark.parametrize("rg", [False, True])
async def test_coupang_body_phone_like_path_uses_opaque_reference(rg):
    from test_product_image_roles import coupang

    url = "https://image.coupangcdn.com/image/assets/asset_" + "010" + "0000" + "0000" + ".jpg"
    branch = {
        "vendorItemId": 456,
        "contents": [{"contentDetails": [{"detailType": "IMAGE", "content": url}]}],
    }
    data = {
        "sellerProductId": 123,
        "sellerProductName": "Product",
        "items": [{"rocketGrowthItemData": branch}] if rg else [branch],
    }
    item = await coupang(data, rg=rg).get_product_content("123")
    assert len(item.image_refs) == 1
    assert item.image_refs[0].role == "detail"
    assert item.image_refs[0].external_option_id == "456"
    assert url not in item.model_dump_json()
    assert_agent_safe_value(item)


async def test_naver_extracts_only_inert_image_references_from_active_html():
    from test_product_image_roles import BODY

    html = (
        f"<script>const text = '<img src=\"{BODY.replace('detail', 'hidden')}\">';</script>"
        f'<iframe><img src="{BODY.replace("detail", "frame")}"></iframe><img src="{BODY}">'
    )
    item = await naver(naver_row(html)).get_product_content("123")
    refs = [r for r in item.image_refs if r.role == "detail"]
    assert len(refs) == 1
    # Subtree-blocked markup never emits its images; the img outside the
    # blocked subtrees passed the url policy and is kept.
    assert [i.url for i in item.images if i.role == "detail"] == [BODY]
    assert "hidden" not in item.model_dump_json()
    assert "frame" not in item.model_dump_json()
    assert_agent_safe_value(item)


async def test_naver_percent_encoded_filename_can_be_read_by_reference():
    url = "https://shop-phinf.pstatic.net/assets/%ED%95%9C%EA%B8%80.jpg"
    item = await naver(naver_row(f'<script>void(0)</script><img src="{url}">')).get_product_content(
        "123"
    )
    assert len([r for r in item.image_refs if r.role == "detail"]) == 1


async def test_mcp_reads_image_bytes_using_only_an_observed_reference(monkeypatch):
    from mcp import Client
    from test_product_image_roles import BODY

    from k12_commerce_mcp.image_assets import IMAGE_ASSETS
    from k12_commerce_mcp.server import build_server

    seen = []

    async def read(url):
        seen.append(url)
        return b"\x89PNG\r\n\x1a\nfixture", "png"

    monkeypatch.setattr("k12_commerce_mcp.server.fetch_product_image", read, raising=False)
    reference = IMAGE_ASSETS.register(BODY)
    async with Client(build_server()) as client:
        response = await client.call_tool("commerce_get_product_image", {"asset_ref": reference})
    assert not response.is_error
    assert len(response.content) == 1
    assert response.content[0].type == "image"
    assert response.content[0].mime_type == "image/png"
    assert seen == [BODY]
