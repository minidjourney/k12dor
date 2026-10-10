from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from k12_commerce_mcp.publishing.deferred_registration import (
    approved_artifact_digest,
)
from k12_commerce_mcp.publishing.elevenst import (
    REQUEST_CHARSET,
    ElevenstCanonicalDraft,
    build_product_xml,
)
from k12_commerce_mcp.publishing.naver import (
    MAX_OPTIONAL_IMAGES,
    NaverApprovalEvidence,
    NaverCanonicalDraft,
    NaverProductPublisher,
    NaverPublishStatus,
)


class FakeNaverWriteClient:
    """In-memory Naver write/readback stub; no HTTP ever leaves the test."""

    def __init__(self, *, optional_upload_mode: str = "ok") -> None:
        self.calls: list[tuple[str, Any]] = []
        self.optional_upload_mode = optional_upload_mode

    async def upload_product_images(
        self, images: tuple[tuple[str, str, bytes], ...]
    ) -> tuple[str, ...]:
        self.calls.append(("upload", images))
        upload_calls = sum(1 for name, _ in self.calls if name == "upload")
        if upload_calls > 1:
            if self.optional_upload_mode == "short":
                return tuple(
                    f"https://shop-phinf.pstatic.net/{name}"
                    for name, _, _ in images
                )[:-1]
            if self.optional_upload_mode == "bad_prefix":
                return tuple(
                    f"https://not-phinf.example.net/{name}" for name, _, _ in images
                )
        return tuple(
            f"https://shop-phinf.pstatic.net/{name}" for name, _, _ in images
        )

    async def create_product(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("create", payload))
        return {"originProductNo": 101, "smartstoreChannelProductNo": 202}

    async def get_origin_product(self, *, origin_product_no: int) -> dict[str, Any]:
        self.calls.append(("readback", origin_product_no))
        return {
            "originProduct": {
                "statusType": "SALE",
                "saleType": "NEW",
                "leafCategoryId": "50000000",
                "name": "검증 상품",
                "detailContent": "검증 설명",
                "images": {
                    "representativeImage": {
                        "url": "https://shop-phinf.pstatic.net/main.png"
                    },
                    "optionalImages": [],
                },
                "salePrice": 1000,
                "stockQuantity": 3,
                "deliveryInfo": {"deliveryType": "DELIVERY"},
                "detailAttribute": {"taxType": "TAX"},
            },
            "smartstoreChannelProduct": {
                "channelProductNo": 202,
                "channelProductName": "검증 상품",
                "naverShoppingRegistration": False,
                "channelProductDisplayStatusType": "ON",
            },
        }


class FakeApprovalVerifier:
    def verify(
        self, evidence: NaverApprovalEvidence, *, idempotency_key: str
    ) -> None:
        if idempotency_key != evidence.artifact_digest:
            raise ValueError("idempotency key does not match approved artifact")


def naver_draft_kwargs(asset: Path) -> dict[str, Any]:
    body = asset.read_bytes()
    return {
        "channel": "naver",
        "status_type": "SALE",
        "sale_type": "NEW",
        "leaf_category_id": "50000000",
        "name": "검증 상품",
        "detail_content": "검증 설명",
        "sale_price": 1000,
        "stock_quantity": 3,
        "delivery_info": {"deliveryType": "DELIVERY"},
        "detail_attribute": {"taxType": "TAX"},
        "channel_product_name": "검증 상품",
        "naver_shopping_registration": False,
        "channel_product_display_status_type": "ON",
        "image_storage_ref": asset.name,
        "image_mime_type": "image/png",
        "image_byte_size": len(body),
        "image_sha256": hashlib.sha256(body).hexdigest(),
    }


def optional_entry(index: int, sha256: str | None = None) -> dict[str, Any]:
    return {
        "storage_ref": f"opt{index}.png",
        "mime_type": "image/png",
        "byte_size": 3,
        "sha256": sha256 or f"{index + 1:064x}",
    }


def approval() -> NaverApprovalEvidence:
    base = datetime(2026, 9, 14, tzinfo=UTC)
    return NaverApprovalEvidence(
        external_publish_approval=True,
        external_publish_approved_at=base + timedelta(seconds=3),
        artifact_digest="a" * 64,
        attempt_id="attempt-1",
        project_id="project-1",
        batch_id="batch-1",
        version=1,
        effective_from=base,
    )


async def publish(
    tmp_path: Path, client: FakeNaverWriteClient, value: NaverCanonicalDraft
) -> Any:
    evidence = approval().model_copy(
        update={"artifact_digest": approved_artifact_digest(value, approval())}
    )
    return await NaverProductPublisher(
        client=client, asset_root=tmp_path, approval_verifier=FakeApprovalVerifier()
    ).publish(value, evidence, idempotency_key=evidence.artifact_digest)


def call_payloads(client: FakeNaverWriteClient, kind: str) -> list[Any]:
    return [payload for name, payload in client.calls if name == kind]


def write_optional_asset(tmp_path: Path, name: str, body: bytes) -> dict[str, Any]:
    (tmp_path / name).write_bytes(body)
    return {
        "storage_ref": name,
        "mime_type": "image/png",
        "byte_size": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
    }


def optional_draft(
    tmp_path: Path, entries: list[dict[str, Any]]
) -> NaverCanonicalDraft:
    asset = tmp_path / "main.png"
    if not asset.exists():
        asset.write_bytes(b"main-image")
    return NaverCanonicalDraft(
        **{**naver_draft_kwargs(asset), "optional_images": entries}
    )


async def test_default_off_serializes_old_shape_and_empty_payload(
    tmp_path: Path,
) -> None:
    asset = tmp_path / "main.png"
    asset.write_bytes(b"main-image")
    kwargs = naver_draft_kwargs(asset)
    plain = NaverCanonicalDraft(**kwargs)
    assert "optional_images" not in plain.model_dump(mode="json")
    explicit_empty = NaverCanonicalDraft(**{**kwargs, "optional_images": []})
    evidence = approval()
    assert approved_artifact_digest(plain, evidence) == approved_artifact_digest(
        explicit_empty, evidence
    )
    client = FakeNaverWriteClient()
    result = await publish(tmp_path, client, plain)
    assert result.status is NaverPublishStatus.PUBLISHED
    assert len(call_payloads(client, "upload")) == 1
    create = call_payloads(client, "create")[0]
    assert create["originProduct"]["images"]["optionalImages"] == []


async def test_two_optional_images_upload_once_and_reach_payload(
    tmp_path: Path,
) -> None:
    entries = [
        write_optional_asset(tmp_path, "opt0.png", b"optional-zero"),
        write_optional_asset(tmp_path, "opt1.png", b"optional-one!"),
    ]
    value = optional_draft(tmp_path, entries)
    client = FakeNaverWriteClient()
    result = await publish(tmp_path, client, value)
    assert result.status is NaverPublishStatus.PUBLISHED
    uploads = call_payloads(client, "upload")
    assert len(uploads) == 2
    assert len(uploads[0]) == 1
    assert [name for name, _, _ in uploads[1]] == ["opt0.png", "opt1.png"]
    create = call_payloads(client, "create")[0]
    assert create["originProduct"]["images"]["optionalImages"] == [
        {"url": "https://shop-phinf.pstatic.net/opt0.png"},
        {"url": "https://shop-phinf.pstatic.net/opt1.png"},
    ]


def test_optional_images_limit(tmp_path: Path) -> None:
    asset = tmp_path / "main.png"
    asset.write_bytes(b"main-image")
    kwargs = naver_draft_kwargs(asset)
    entries = [optional_entry(i) for i in range(MAX_OPTIONAL_IMAGES)]
    NaverCanonicalDraft(**{**kwargs, "optional_images": entries})
    with pytest.raises(ValidationError):
        NaverCanonicalDraft(
            **{
                **kwargs,
                "optional_images": [
                    *entries,
                    optional_entry(MAX_OPTIONAL_IMAGES),
                ],
            }
        )


def test_duplicate_optional_sha256_rejected(tmp_path: Path) -> None:
    asset = tmp_path / "main.png"
    asset.write_bytes(b"main-image")
    kwargs = naver_draft_kwargs(asset)
    duplicated = hashlib.sha256(b"same-bytes").hexdigest()
    with pytest.raises(ValidationError, match="optional images must be unique"):
        NaverCanonicalDraft(
            **{
                **kwargs,
                "optional_images": [
                    optional_entry(0, duplicated),
                    optional_entry(1, duplicated),
                ],
            }
        )


def test_optional_sha256_matching_representative_rejected(tmp_path: Path) -> None:
    asset = tmp_path / "main.png"
    asset.write_bytes(b"main-image")
    kwargs = naver_draft_kwargs(asset)
    with pytest.raises(
        ValidationError, match="repeats the representative image"
    ):
        NaverCanonicalDraft(
            **{
                **kwargs,
                "optional_images": [
                    optional_entry(0, kwargs["image_sha256"])
                ],
            }
        )


async def test_short_optional_upload_response_fails_before_create(
    tmp_path: Path,
) -> None:
    entries = [
        write_optional_asset(tmp_path, "opt0.png", b"optional-zero"),
        write_optional_asset(tmp_path, "opt1.png", b"optional-one!"),
    ]
    value = optional_draft(tmp_path, entries)
    client = FakeNaverWriteClient(optional_upload_mode="short")
    with pytest.raises(ValueError, match="optional image upload response"):
        await publish(tmp_path, client, value)
    assert call_payloads(client, "create") == []


async def test_bad_prefix_optional_upload_response_fails_before_create(
    tmp_path: Path,
) -> None:
    entries = [
        write_optional_asset(tmp_path, "opt0.png", b"optional-zero"),
        write_optional_asset(tmp_path, "opt1.png", b"optional-one!"),
    ]
    value = optional_draft(tmp_path, entries)
    client = FakeNaverWriteClient(optional_upload_mode="bad_prefix")
    with pytest.raises(ValueError, match="optional image upload response"):
        await publish(tmp_path, client, value)
    assert call_payloads(client, "create") == []


async def test_optional_file_evidence_mismatch_fails(tmp_path: Path) -> None:
    (tmp_path / "opt0.png").write_bytes(b"actual-bytes")
    declared = b"declared-bytes!"
    entries = [
        {
            "storage_ref": "opt0.png",
            "mime_type": "image/png",
            "byte_size": len(declared),
            "sha256": hashlib.sha256(declared).hexdigest(),
        }
    ]
    value = optional_draft(tmp_path, entries)
    client = FakeNaverWriteClient()
    with pytest.raises(ValueError, match="evidence"):
        await publish(tmp_path, client, value)
    assert call_payloads(client, "create") == []


def test_standard_option_groups_key_rejected(tmp_path: Path) -> None:
    asset = tmp_path / "main.png"
    asset.write_bytes(b"main-image")
    with pytest.raises(ValidationError, match="extra_forbidden"):
        NaverCanonicalDraft(
            **{**naver_draft_kwargs(asset), "standard_option_groups": []}
        )


def _st_image(index: int) -> str:
    return (
        "https://k12-server.example.ts.net/11st/"
        + f"{index:032x}"
        + ".jpg"
    )


def elevenst_draft(**overrides: Any) -> ElevenstCanonicalDraft:
    payload: dict[str, Any] = {
        "channel": "11st",
        "name": "11번가 리클라이너",
        "category_no": "134662",
        "sale_price": 18000,
        "stock_quantity": 99,
        "tax_code": "01",
        "minor_purchasable": True,
        "brand": "케이십이",
        "product_status": "01",
        "images": [_st_image(1)],
        "detail_html": "<p>상세설명</p>",
        "option_title": None,
        "options": None,
        "raw_material_type": "01",
        "origin_type": "01",
        "origin_region_code": "11",
        "origin_name": None,
        "beef_trace": "02",
        "cert_groups": [
            {
                "group_type": "01",
                "target_code": "01",
                "exemption_code": None,
                "certs": [{"type_code": "101", "key": "K-123"}],
            }
        ],
        "notice": {
            "type_code": "891",
            "items": [{"code": "1", "value": "소재: 가죽"}],
        },
        "delivery": {
            "area_code": "01",
            "method_code": "01",
            "courier_code": "00001",
            "send_close_template_no": "7",
            "fee_type": "02",
            "fee": 2500,
            "free_threshold": None,
            "pay_type": "01",
            "bundle": True,
            "jeju_fee": 3000,
            "island_fee": 3000,
            "outbound_addr_seq": "1",
            "inbound_addr_seq": "2",
            "return_fee": 3000,
            "exchange_fee": 6000,
        },
        "as_detail": "A/S 문의 02-000-0000",
        "return_exchange_detail": "수령 후 7일 이내 신청",
        "seller_product_code": "dor-" + "0" * 16,
    }
    payload.update(overrides)
    return ElevenstCanonicalDraft(**payload)


def test_elevenst_xml_carries_four_images_in_order() -> None:
    urls = [_st_image(i) for i in range(1, 5)]
    text = build_product_xml(elevenst_draft(images=urls)).decode(REQUEST_CHARSET)
    position = -1
    for index, url in enumerate(urls, start=1):
        marker = f"<prdImage{index:02d}>{url}</prdImage{index:02d}>"
        assert marker in text
        assert text.index(marker) > position
        position = text.index(marker)


def test_elevenst_five_images_rejected() -> None:
    with pytest.raises(ValidationError):
        elevenst_draft(images=[_st_image(i) for i in range(1, 6)])
