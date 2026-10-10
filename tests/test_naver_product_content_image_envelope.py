"""Naver content image envelope. String fixtures only. No HTML or image bodies.

Official origin-product schema, local ingest 2026-09-16:
docs_commerce-api_current_schemas_원상품-정보-구조체.html
https://apicenter.commerce.naver.com/docs/commerce-api/current/schemas/원상품-정보-구조체

images is a required object. representativeImage is a required object whose
url is a required string. optionalImages is an array of objects whose url is
a required string. Representative is required; additional images are optional.
This file does not encode the documented maximum of 9.

Existing list fixture: tests/test_naver_origin_content.py.
Existing unsafe-value rejection is the service gate in
tests/test_naver_live.py, not a new image filter.
"""

from datetime import UTC, datetime

import pytest

from k12_commerce_mcp.adapters.naver import NaverAdapter
from k12_commerce_mcp.models import Channel, ErrorCode, ResultStatus
from k12_commerce_mcp.registry import AdapterRegistry
from k12_commerce_mcp.service.application import CommerceService

PRODUCT_ID = "123"
REP = "https://example.invalid/representative.jpg"
OPT = "https://example.invalid/optional.jpg"
DESCRIPTION = "Synthetic description"


class _UnusedClient:
    def __getattr__(self, name: str):
        raise AssertionError(f"client.{name} must not be called")


def _row(images: object | None) -> dict[str, object]:
    origin: dict[str, object] = {
        "name": "Synthetic product",
        "detailContent": DESCRIPTION,
    }
    if images is not None:
        origin["images"] = images
    return {
        "channelProductNo": 123,
        "name": "Synthetic product",
        "originProduct": origin,
    }


def _adapter(images: object | None) -> NaverAdapter:
    adapter = NaverAdapter(
        _UnusedClient(),
        clock=lambda: datetime(2026, 9, 30, tzinfo=UTC),
    )
    row = _row(images)

    async def _read_product(
        self: NaverAdapter, external_product_id: str
    ) -> dict[str, object] | None:
        del self
        assert external_product_id == PRODUCT_ID
        return row

    adapter._read_product = _read_product.__get__(adapter)
    return adapter


@pytest.mark.asyncio
async def test_object_envelope_returns_representative_then_one_optional() -> None:
    adapter = _adapter(
        {
            "representativeImage": {"url": REP},
            "optionalImages": [{"url": OPT}],
        }
    )

    content = await adapter.get_product_content(PRODUCT_ID)

    assert content is not None
    assert content.channel is Channel.NAVER
    assert content.image_urls == (REP, OPT)
    assert content.description_text == DESCRIPTION
    assert content.completeness.status is ResultStatus.INCOMPLETE
    assert content.completeness.missing_fields == ("notices",)
    assert content.completeness.reasons == ("provider_content_fields_missing",)


@pytest.mark.asyncio
async def test_legacy_image_list_still_returns_https_urls() -> None:
    adapter = _adapter([{"url": REP}, {"url": OPT}])

    content = await adapter.get_product_content(PRODUCT_ID)

    assert content is not None
    assert content.image_urls == (REP, OPT)
    assert content.completeness.status is ResultStatus.INCOMPLETE
    assert "image_urls" not in content.completeness.missing_fields
    assert "notices" in content.completeness.missing_fields


@pytest.mark.asyncio
async def test_absent_image_info_stays_incomplete() -> None:
    adapter = _adapter(None)

    content = await adapter.get_product_content(PRODUCT_ID)

    assert content is not None
    assert content.image_urls == ()
    assert content.description_text == DESCRIPTION
    assert content.completeness.status is ResultStatus.INCOMPLETE
    assert content.completeness.missing_fields == ("notices", "image_urls")
    assert content.completeness.reasons == ("provider_content_fields_missing",)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("image_url", "forbidden"),
    [
        ("https://example.invalid/asset.jpg?token=synthetic-secret", "synthetic-secret"),
        ("https://example.invalid/pii@example.invalid/a.jpg", "pii@example.invalid"),
    ],
)
async def test_object_image_url_keeps_existing_service_rejection(
    image_url: str, forbidden: str
) -> None:
    adapter = _adapter({"representativeImage": {"url": image_url}})
    service = CommerceService(AdapterRegistry([adapter]))

    result = await service.get_product_content(Channel.NAVER, PRODUCT_ID)

    assert result.status is ResultStatus.UNAVAILABLE
    assert result.item is None
    assert result.errors[0].code is ErrorCode.INVALID_ADAPTER_RESPONSE
    assert forbidden not in result.model_dump_json()


# Synthetic only. The literal is deliberately rejected by the generic gate.
PHONE_ASSET = (
    "https://shop-phinf.pstatic.net/20260930_100/1700000000000abc_JPEG/"
    "asset_" + "010" + "0000" + "0000" + ".jpg"
)


@pytest.mark.parametrize("other_images", [[], [{"url": REP}]])
async def test_phone_like_public_asset_is_withheld_without_disabling_global_gate(other_images):
    from k12_commerce_mcp.security import PiiValueError, assert_agent_safe_value

    with pytest.raises(PiiValueError):
        assert_agent_safe_value(PHONE_ASSET)
    adapter = _adapter(
        {"representativeImage": {"url": PHONE_ASSET}, "optionalImages": other_images}
    )
    result = await CommerceService(AdapterRegistry([adapter])).get_product_content(
        Channel.NAVER, PRODUCT_ID
    )
    assert result.status is ResultStatus.INCOMPLETE
    assert result.item is not None
    assert result.item.image_urls == tuple(image["url"] for image in other_images)
    assert result.item.completeness.missing_fields == ("notices", "image_urls")
    assert result.reasons == (
        "provider_content_fields_missing",
        "unsafe_image_urls_withheld",
    )
    assert PHONE_ASSET not in result.model_dump_json()
    assert_agent_safe_value(result)


@pytest.mark.parametrize(
    "bad_url",
    [
        PHONE_ASSET + "?token=synthetic-credential",
        PHONE_ASSET.replace("asset_", "person@example.invalid_"),
        PHONE_ASSET.replace("shop-phinf.pstatic.net", "example.invalid"),
    ],
)
async def test_asset_withholding_does_not_bypass_secrets_email_or_unknown_host(bad_url):
    adapter = _adapter({"representativeImage": {"url": bad_url}, "optionalImages": [{"url": REP}]})
    result = await CommerceService(AdapterRegistry([adapter])).get_product_content(
        Channel.NAVER, PRODUCT_ID
    )
    assert result.status is ResultStatus.UNAVAILABLE
    assert result.item is None
    assert result.errors[0].code is ErrorCode.INVALID_ADAPTER_RESPONSE
    assert bad_url not in result.model_dump_json()
