"""DOR 작업대에서 고친 상세 본문이 네이버 등록 상세(detailContent)로 들어가는지
(CEO 2026-10-05). 네트워크 없음."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest

from k12_commerce_mcp.publishing.naver import (
    NaverCanonicalDraft,
    NaverDetailBlock,
    NaverProductPublisher,
    render_detail_html,
)


def _image(tmp: Path, name: str, body: bytes) -> dict[str, Any]:
    (tmp / name).write_bytes(body)
    return {
        "storage_ref": name,
        "mime_type": "image/png",
        "byte_size": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
    }


def _draft(tmp: Path, **extra: Any) -> NaverCanonicalDraft:
    main = _image(tmp, "main.png", b"main")
    return NaverCanonicalDraft(
        channel="naver",
        status_type="SALE",
        leaf_category_id="50000000",
        name="상품",
        detail_content="원래 설명",
        sale_price=1000,
        stock_quantity=3,
        delivery_info={},
        detail_attribute={},
        channel_product_name="상품",
        naver_shopping_registration=False,
        channel_product_display_status_type="ON",
        image_storage_ref=main["storage_ref"],
        image_mime_type="image/png",
        image_byte_size=main["byte_size"],
        image_sha256=main["sha256"],
        **extra,
    )


class Uploads:
    def __init__(self) -> None:
        self.batches: list[int] = []

    async def upload_product_images(self, images):  # type: ignore[no-untyped-def]
        self.batches.append(len(images))
        return tuple(f"https://shop-phinf.pstatic.net/{name}" for name, _, _ in images)


def test_html_escapes_text_and_uses_860px_layout() -> None:
    html = render_detail_html(
        [
            NaverDetailBlock(
                type="text", heading="이런 분께 추천", text="<script>x</script>\n둘째 줄"
            ),
            NaverDetailBlock(type="image", image_index=0),
        ],
        ["https://shop-phinf.pstatic.net/a.png"],
    )
    assert "max-width:860px" in html
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "<br>" in html
    assert html.index("이런 분께 추천") < html.index("https://shop-phinf.pstatic.net/a.png")


def test_blocks_must_reference_every_image_exactly(tmp_path: Path) -> None:
    img = _image(tmp_path, "d1.png", b"d1")
    with pytest.raises(ValueError):
        _draft(tmp_path, detail_blocks=[{"type": "image", "image_index": 1}], detail_images=[img])
    with pytest.raises(ValueError):
        _draft(tmp_path, detail_blocks=[{"type": "text", "text": "글"}], detail_images=[img])
    with pytest.raises(ValueError):
        _draft(tmp_path, detail_blocks=[{"type": "text"}])


def test_empty_detail_keeps_old_payload_and_digest_shape(tmp_path: Path) -> None:
    draft = _draft(tmp_path)
    dumped = draft.model_dump(mode="json")
    assert "detail_blocks" not in dumped and "detail_images" not in dumped


@pytest.mark.anyio
async def test_detail_images_upload_in_batches_of_ten_and_render_in_order(tmp_path: Path) -> None:
    images = [_image(tmp_path, f"d{i}.png", f"d{i}".encode()) for i in range(12)]
    blocks = [{"type": "text", "heading": "한눈에 보기", "text": "요약"}] + [
        {"type": "image", "image_index": i} for i in range(12)
    ]
    draft = _draft(tmp_path, detail_blocks=blocks, detail_images=images)
    client = Uploads()
    publisher = NaverProductPublisher(client=client, asset_root=tmp_path, approval_verifier=None)  # type: ignore[arg-type]
    content = await publisher._detail_content(draft)
    assert client.batches == [10, 2]
    assert content.index("한눈에 보기") < content.index("d0.png") < content.index("d11.png")


@pytest.mark.anyio
async def test_tampered_detail_image_is_rejected_before_upload(tmp_path: Path) -> None:
    img = _image(tmp_path, "d1.png", b"d1")
    draft = _draft(
        tmp_path, detail_blocks=[{"type": "image", "image_index": 0}], detail_images=[img]
    )
    (tmp_path / "d1.png").write_bytes(b"changed")
    client = Uploads()
    publisher = NaverProductPublisher(client=client, asset_root=tmp_path, approval_verifier=None)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        await publisher._detail_content(draft)
    assert client.batches == []


@pytest.mark.anyio
async def test_detail_images_split_so_each_upload_stays_under_nine_mb(tmp_path: Path) -> None:
    # CTO 2026-10-08 (19:16 네이버 HTTP 400): 할로윈 상세 사진 4장 합계 12.3MB 를 한 번에 보냈다.
    # 같은 크기(4.3·2.9·4.3·0.9MB)로 재현 — 합계 9MB 를 넘지 않게 나눠 보내고, 순서는 그대로다.
    sizes = [4_273_871, 2_859_172, 4_287_703, 885_017]
    images = [_image(tmp_path, f"h{i}.png", bytes([i]) * size) for i, size in enumerate(sizes)]
    blocks = [{"type": "image", "image_index": i} for i in range(4)]
    draft = _draft(tmp_path, detail_blocks=blocks, detail_images=images)
    client = Uploads()
    publisher = NaverProductPublisher(client=client, asset_root=tmp_path, approval_verifier=None)  # type: ignore[arg-type]
    content = await publisher._detail_content(draft)
    assert client.batches == [2, 2]
    assert (
        content.index("h0.png") < content.index("h1.png")
        < content.index("h2.png") < content.index("h3.png")
    )
