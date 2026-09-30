"""Fail-closed live publisher composition tests (mock transports only).

Every test builds the real publisher classes over the real client classes;
provider HTTP is intercepted by ``httpx.MockTransport`` and the DOR approval
database is a disposable sqlite fixture. Nothing here reaches a live provider,
a real credential, or a real DOR store.
"""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from mcp import Client

from k12_commerce_mcp import composition
from k12_commerce_mcp.clients.coupang import CoupangClient
from k12_commerce_mcp.clients.naver import NaverClient
from k12_commerce_mcp.clients.toss import TossShoppingClient
from k12_commerce_mcp.composition import (
    CoupangPublishClient,
    LivePublishPrerequisites,
    TossPublishClient,
    build_live_publishers,
    load_publish_prerequisites,
)
from k12_commerce_mcp.credentials import load_marketplace_credentials
from k12_commerce_mcp.permissions import APPROVED_TOOL_NAMES
from k12_commerce_mcp.publishing import (
    CoupangApprovalEvidence,
    CoupangCanonicalDraft,
    CoupangProductPublisher,
    NaverApprovalEvidence,
    NaverCanonicalDraft,
    NaverProductPublisher,
    TossApprovalEvidence,
    TossCanonicalDraft,
    TossProductPublisher,
)
from k12_commerce_mcp.publishing.coupang import (
    CoupangDraftAttribute,
    CoupangDraftContent,
    CoupangDraftContentDetail,
    CoupangDraftImage,
    CoupangDraftItem,
)
from k12_commerce_mcp.publishing.deferred_registration import approved_artifact_digest
from k12_commerce_mcp.publishing.dor_approval import DorChannelApprovalVerifier
from k12_commerce_mcp.publishing.toss import (
    TossDraftDeliveryPolicy,
    TossDraftExchangeReturnPolicy,
    TossDraftExposure,
    TossDraftImage,
    TossDraftNotice,
    TossDraftNoticeItem,
    TossDraftStock,
)
from k12_commerce_mcp.server import build_live_server

INTENT_TABLE = "product_automation_channel_publish_intents"
COUPANG_PRODUCT_ID = 427011919
NAVER_ORIGIN_NO = 101
NAVER_CHANNEL_NO = 202
TOSS_PRODUCT_ID = 555
NAVER_IMAGE_URL = "https://shop-phinf.pstatic.net/verified.jpg"


def _credential_file(
    tmp_path: Path,
    *,
    coupang: bool = True,
    naver: bool = True,
    toss: bool = True,
    extra_lines: tuple[str, ...] = (),
) -> Path:
    lines: list[str] = []
    if coupang:
        lines += [
            "DOR_COUPANG_VENDOR_ID=vendor-fixture",
            "DOR_COUPANG_ACCESS_KEY=access-fixture",
            "DOR_COUPANG_SECRET_KEY=secret-fixture",
        ]
    if naver:
        lines += [
            "DOR_NAVER_CLIENT_ID=naver-client-fixture",
            "DOR_NAVER_CLIENT_SECRET=$2b$10$abcdefghijklmnopqrstuu",
        ]
    if toss:
        lines += [
            "DOR_TOSS_SHOPPING_ACCESS_KEY=toss-access-fixture",
            "DOR_TOSS_SHOPPING_SECRET_KEY=toss-secret-fixture",
        ]
    lines += extra_lines
    path = tmp_path / "marketplace-readonly.env"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    path.chmod(0o600)
    return path


def _dor_db(tmp_path: Path) -> Path:
    path = tmp_path / "dor.sqlite"
    db = sqlite3.connect(path)
    db.executescript(
        f"""CREATE TABLE approval_records (
              product_id TEXT,batch_id TEXT,version INTEGER,effective_from TEXT,
              channel TEXT,approval_type TEXT,result TEXT,actor_role TEXT,
              recorded_at TEXT);
            CREATE TABLE {INTENT_TABLE} (
              project TEXT,batch TEXT,version INTEGER,effective_from TEXT,
              channel TEXT,attempt_id TEXT,artifact_digest TEXT,
              recorded_at TEXT,status TEXT);"""
    )
    db.commit()
    db.close()
    return path


def _seed_dor(
    db_path: Path, evidence: Any, channel: str, *, intent: bool = True
) -> None:
    effective = evidence.effective_from.isoformat().replace("+00:00", "Z")
    db = sqlite3.connect(db_path)
    db.execute(
        "INSERT INTO approval_records VALUES (?,?,?,?,?,?,?,?,?)",
        (
            evidence.project_id,
            evidence.batch_id,
            evidence.version,
            effective,
            channel,
            "external_publish",
            "approved",
            "CEO",
            evidence.external_publish_approved_at.isoformat().replace("+00:00", "Z"),
        ),
    )
    if intent:
        db.execute(
            f"INSERT INTO {INTENT_TABLE} VALUES (?,?,?,?,?,?,?,?,?)",
            (
                evidence.project_id,
                evidence.batch_id,
                evidence.version,
                effective,
                channel,
                evidence.attempt_id,
                evidence.artifact_digest,
                "2026-09-19T00:00:10Z",
                "intent_claimed",
            ),
        )
    db.commit()
    db.close()


def _asset_root(tmp_path: Path) -> Path:
    root = tmp_path / "assets"
    root.mkdir()
    (root / "main.png").write_bytes(b"verified-image")
    return root


def _evidence(model: type, draft: Any) -> Any:
    base = datetime(2026, 9, 19, tzinfo=UTC)
    value = model(
        external_publish_approval=True,
        external_publish_approved_at=base,
        artifact_digest="a" * 64,
        attempt_id="attempt-1",
        project_id="project-1",
        batch_id="batch-1",
        version=1,
        effective_from=base,
    )
    return value.model_copy(
        update={"artifact_digest": approved_artifact_digest(draft, value)}
    )


def _coupang_draft() -> CoupangCanonicalDraft:
    return CoupangCanonicalDraft(
        channel="coupang",
        seller_product_name="검증 상품",
        vendor_id="A00012345",
        sale_started_at="2026-09-19T00:00:00",
        sale_ended_at="2099-01-01T23:59:59",
        delivery_method="SEQUENCIAL",
        delivery_company_code="KDEXP",
        delivery_charge_type="FREE",
        delivery_charge=0,
        free_ship_over_amount=0,
        delivery_charge_on_return=2500,
        remote_area_deliverable="N",
        union_delivery_type="UNION_DELIVERY",
        return_center_code="1000274592",
        return_charge_name="반품지_1",
        company_contact_number="02-0000-0000",
        return_zip_code="00000",
        return_address="seller return site",
        return_address_detail="unit 1",
        return_charge=2500,
        outbound_shipping_place_code=74010,
        vendor_user_id="wing_loginId_1",
        requested=True,
        items=(
            CoupangDraftItem(
                item_name="검증 상품 옵션",
                original_price=20000,
                sale_price=18000,
                maximum_buy_count=100,
                maximum_buy_for_person=0,
                maximum_buy_for_person_period=1,
                outbound_shipping_time_day=1,
                unit_count=1,
                adult_only="EVERYONE",
                tax_type="TAX",
                parallel_imported="NOT_PARALLEL_IMPORTED",
                overseas_purchased="NOT_OVERSEAS_PURCHASED",
                pcc_needed=False,
                images=(
                    CoupangDraftImage(
                        image_order=0,
                        image_type="REPRESENTATION",
                        vendor_path="https://img.example.invalid/main.jpg",
                    ),
                ),
                attributes=(
                    CoupangDraftAttribute(
                        attribute_type_name="수량", attribute_value_name="1개"
                    ),
                ),
                contents=(
                    CoupangDraftContent(
                        contents_type="TEXT",
                        content_details=(
                            CoupangDraftContentDetail(content="상세", detail_type="TEXT"),
                        ),
                    ),
                ),
            ),
        ),
    )


def _naver_draft() -> NaverCanonicalDraft:
    body = b"verified-image"
    return NaverCanonicalDraft(
        channel="naver",
        status_type="SALE",
        sale_type="NEW",
        leaf_category_id="50000000",
        name="검증 상품",
        detail_content="검증 설명",
        sale_price=1000,
        stock_quantity=3,
        delivery_info={"deliveryType": "DELIVERY"},
        detail_attribute={"taxType": "TAX"},
        channel_product_name="검증 상품",
        naver_shopping_registration=False,
        channel_product_display_status_type="ON",
        image_storage_ref="main.png",
        image_mime_type="image/png",
        image_byte_size=len(body),
        image_sha256=hashlib.sha256(body).hexdigest(),
    )


def _toss_draft() -> TossCanonicalDraft:
    return TossCanonicalDraft(
        channel="toss",
        name="토스 리클라이너",
        category_id=14835,
        stocks=(
            TossDraftStock(
                remaining_count=99,
                is_hide=False,
                is_main_price=True,
                is_sold_out=False,
                origin_price=20000,
                sale_price=18000,
            ),
        ),
        images=(
            TossDraftImage(
                type="THUMBNAIL", url="https://img.example.invalid/t.jpg", order=0
            ),
            TossDraftImage(
                type="DESCRIPTION", url="https://img.example.invalid/d.jpg", order=1
            ),
        ),
        exposure=TossDraftExposure(
            search_keywords=("리클라이너",), description="토스 쇼핑의 리클라이너"
        ),
        is_tax_free=False,
        delivery_policy=TossDraftDeliveryPolicy(
            delivery_method="NORMAL",
            delivery_fee_type="CONDITIONALLY_FREE",
            delivery_fee=1500,
            minimum_purchase_price=20000,
            is_jeju_and_islands_mountains_delivery=True,
            jeju_delivery_fee=3000,
            islands_mountains_delivery_fee=3000,
        ),
        exchange_return_policy=TossDraftExchangeReturnPolicy(
            refund_one_way_delivery_fee=1500,
            exchange_round_trip_delivery_fee=3000,
            application_method_description="고객센터 연락 후 교환/반품 신청",
            application_term_description="상품 수령 후 7일 이내",
        ),
        notice=TossDraftNotice(
            category_code="FURNITURE",
            items=(TossDraftNoticeItem(id=27, content="나무, 가죽"),),
        ),
    )


def _coupang_transport(calls: list[tuple[str, str]]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.method == "POST":
            return httpx.Response(
                200, json={"code": "SUCCESS", "data": COUPANG_PRODUCT_ID}
            )
        return httpx.Response(
            200,
            json={
                "code": "SUCCESS",
                "data": {"sellerProductId": COUPANG_PRODUCT_ID},
            },
        )

    return httpx.MockTransport(handler)


def _naver_transport(
    calls: list[tuple[str, str]], draft: NaverCanonicalDraft
) -> httpx.MockTransport:
    readback = {
        "originProduct": {
            "statusType": "SALE",
            "saleType": "NEW",
            "leafCategoryId": draft.leaf_category_id,
            "name": draft.name,
            "detailContent": draft.detail_content,
            "images": {
                "representativeImage": {"url": NAVER_IMAGE_URL},
                "optionalImages": [],
            },
            "salePrice": draft.sale_price,
            "stockQuantity": draft.stock_quantity,
            "deliveryInfo": draft.delivery_info,
            "detailAttribute": draft.detail_attribute,
        },
        "smartstoreChannelProduct": {
            "channelProductNo": NAVER_CHANNEL_NO,
            "channelProductName": draft.channel_product_name,
            "naverShoppingRegistration": draft.naver_shopping_registration,
            "channelProductDisplayStatusType": draft.channel_product_display_status_type,
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        path = request.url.path
        if path.endswith("/v1/oauth2/token"):
            return httpx.Response(
                200, json={"access_token": "fixture-token", "expires_in": 3600}
            )
        if path.endswith("/v1/product-images/upload"):
            return httpx.Response(200, json={"images": [{"url": NAVER_IMAGE_URL}]})
        if request.method == "POST" and path.endswith("/v2/products"):
            return httpx.Response(
                200,
                json={
                    "originProductNo": NAVER_ORIGIN_NO,
                    "smartstoreChannelProductNo": NAVER_CHANNEL_NO,
                },
            )
        if "/v2/products/origin-products/" in path:
            return httpx.Response(200, json=readback)
        return httpx.Response(404, json={})

    return httpx.MockTransport(handler)


def _toss_transport(calls: list[tuple[str, str]]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.host == "oauth2.cert.toss.im":
            return httpx.Response(
                200,
                json={
                    "access_token": "fixture-token",
                    "expires_in": 3600,
                    "token_type": "Bearer",
                    "scope": "toss-shopping-fep:write",
                },
            )
        if request.method == "POST":
            return httpx.Response(
                200, json={"resultType": "SUCCESS", "success": {"id": TOSS_PRODUCT_ID}}
            )
        return httpx.Response(
            200,
            json={
                "resultType": "SUCCESS",
                "success": {"id": TOSS_PRODUCT_ID, "name": "토스 리클라이너"},
            },
        )

    return httpx.MockTransport(handler)


def _patch_clients(
    monkeypatch: pytest.MonkeyPatch,
    *,
    coupang_calls: list[tuple[str, str]],
    naver_calls: list[tuple[str, str]],
    toss_calls: list[tuple[str, str]],
    naver_draft: NaverCanonicalDraft,
) -> None:
    monkeypatch.setattr(
        composition,
        "CoupangClient",
        lambda credentials: CoupangClient(
            credentials, transport=_coupang_transport(coupang_calls)
        ),
    )
    monkeypatch.setattr(
        composition,
        "NaverClient",
        lambda credentials: NaverClient(
            credentials, transport=_naver_transport(naver_calls, naver_draft)
        ),
    )
    monkeypatch.setattr(
        composition,
        "TossShoppingClient",
        lambda credentials: TossShoppingClient(
            credentials, transport=_toss_transport(toss_calls)
        ),
    )


def _publish_prerequisites(tmp_path: Path) -> LivePublishPrerequisites:
    return LivePublishPrerequisites(
        dor_database=_dor_db(tmp_path), naver_asset_root=_asset_root(tmp_path)
    )


def test_publishers_compose_with_credentials_and_prerequisites(tmp_path: Path) -> None:
    credentials = load_marketplace_credentials(_credential_file(tmp_path))
    prerequisites = _publish_prerequisites(tmp_path)

    publishers = build_live_publishers(credentials, prerequisites)

    assert isinstance(publishers.coupang, CoupangProductPublisher)
    assert isinstance(publishers.naver, NaverProductPublisher)
    assert isinstance(publishers.toss, TossProductPublisher)
    assert isinstance(publishers.coupang._client, CoupangPublishClient)
    assert isinstance(publishers.coupang._client._client, CoupangClient)
    assert isinstance(publishers.naver._client, NaverClient)
    assert isinstance(publishers.toss._client, TossPublishClient)
    assert isinstance(publishers.toss._client._client, TossShoppingClient)
    for publisher, channel in (
        (publishers.coupang, "coupang"),
        (publishers.naver, "naver"),
        (publishers.toss, "toss"),
    ):
        verifier = publisher._approval_verifier
        assert isinstance(verifier, DorChannelApprovalVerifier)
        assert verifier._channel == channel
        assert verifier._database_path == prerequisites.dor_database
    assert publishers.naver._asset_root == prerequisites.naver_asset_root


def test_no_prerequisites_composes_no_publishers(tmp_path: Path) -> None:
    credentials = load_marketplace_credentials(_credential_file(tmp_path))

    publishers = build_live_publishers(credentials, LivePublishPrerequisites())

    assert publishers.coupang is None
    assert publishers.naver is None
    assert publishers.toss is None


@pytest.mark.parametrize("variant", ("absent", "missing_file", "directory", "symlink"))
def test_unusable_dor_database_keeps_every_channel_unavailable(
    tmp_path: Path, variant: str
) -> None:
    credentials = load_marketplace_credentials(_credential_file(tmp_path))
    assets = _asset_root(tmp_path)
    if variant == "absent":
        dor_database = None
    elif variant == "missing_file":
        dor_database = tmp_path / "absent.sqlite"
    elif variant == "directory":
        dor_database = tmp_path / "dbdir"
        dor_database.mkdir()
    else:
        real = _dor_db(tmp_path)
        dor_database = tmp_path / "linked.sqlite"
        dor_database.symlink_to(real)

    publishers = build_live_publishers(
        credentials,
        LivePublishPrerequisites(
            dor_database=dor_database, naver_asset_root=assets
        ),
    )

    assert publishers.coupang is None
    assert publishers.naver is None
    assert publishers.toss is None


@pytest.mark.parametrize("variant", ("absent", "regular_file", "symlink_dir", "missing"))
def test_naver_asset_root_scopes_only_naver_unavailable(
    tmp_path: Path, variant: str
) -> None:
    credentials = load_marketplace_credentials(_credential_file(tmp_path))
    dor_database = _dor_db(tmp_path)
    if variant == "absent":
        asset_root = None
    elif variant == "regular_file":
        asset_root = tmp_path / "not-a-dir"
        asset_root.write_bytes(b"x")
    elif variant == "symlink_dir":
        target = _asset_root(tmp_path)
        asset_root = tmp_path / "linked-assets"
        asset_root.symlink_to(target, target_is_directory=True)
    else:
        asset_root = tmp_path / "missing-assets"

    publishers = build_live_publishers(
        credentials,
        LivePublishPrerequisites(
            dor_database=dor_database, naver_asset_root=asset_root
        ),
    )

    assert publishers.naver is None
    assert isinstance(publishers.coupang, CoupangProductPublisher)
    assert isinstance(publishers.toss, TossProductPublisher)


def test_missing_credentials_keep_that_channel_unavailable(tmp_path: Path) -> None:
    credentials = load_marketplace_credentials(
        _credential_file(tmp_path, naver=False, toss=False)
    )

    publishers = build_live_publishers(credentials, _publish_prerequisites(tmp_path))

    assert isinstance(publishers.coupang, CoupangProductPublisher)
    assert publishers.naver is None
    assert publishers.toss is None


def test_load_publish_prerequisites_reads_only_explicit_config_keys(
    tmp_path: Path,
) -> None:
    dor_database = _dor_db(tmp_path)
    assets = _asset_root(tmp_path)
    cred_file = _credential_file(
        tmp_path,
        extra_lines=(
            f"DOR_APPROVAL_DATABASE={dor_database}",
            f"DOR_NAVER_ASSET_ROOT={assets}",
            "DOR_UNRELATED_KEY=ignored",
        ),
    )

    prerequisites = load_publish_prerequisites(cred_file)

    assert prerequisites.dor_database == dor_database
    assert prerequisites.naver_asset_root == assets


def test_load_publish_prerequisites_defaults_to_unavailable(tmp_path: Path) -> None:
    assert load_publish_prerequisites(_credential_file(tmp_path)) == (
        LivePublishPrerequisites()
    )
    assert load_publish_prerequisites(tmp_path / "absent.env") == LivePublishPrerequisites()


def test_load_publish_prerequisites_rejects_relative_paths(tmp_path: Path) -> None:
    cred_file = _credential_file(
        tmp_path,
        extra_lines=(
            "DOR_APPROVAL_DATABASE=relative/dor.sqlite",
            "DOR_NAVER_ASSET_ROOT=relative/assets",
        ),
    )

    assert load_publish_prerequisites(cred_file) == LivePublishPrerequisites()


async def test_live_server_keeps_read_tools_when_write_unconfigured(
    tmp_path: Path,
) -> None:
    server = build_live_server(_credential_file(tmp_path))
    async with Client(server) as client:
        listed = await client.list_tools()
        health = await client.call_tool("commerce_health_check")
        channels = await client.call_tool("commerce_list_channels")
        readiness = await client.call_tool(
            "commerce_prepare_marketplace_product_drafts",
            {
                "product": {},
                "channel_configs": [
                    {"channel": "coupang"},
                    {"channel": "naver"},
                    {"channel": "toss"},
                ],
            },
        )
        published = await client.call_tool(
            "commerce_publish_coupang_product",
            {
                "draft": _coupang_draft().model_dump(mode="json"),
                "approval": _evidence(
                    CoupangApprovalEvidence, _coupang_draft()
                ).model_dump(mode="json"),
                "idempotency_key": "a" * 64,
            },
        )

    assert len(listed.tools) == len(APPROVED_TOOL_NAMES)
    assert "commerce_prepare_detail_page_draft" in {tool.name for tool in listed.tools}
    assert health.is_error is False
    assert channels.is_error is False
    assert readiness.is_error is False
    flags = {
        row["channel"]: row["external_execution_configured"]
        for row in readiness.structured_content["channels"]
    }
    assert flags == {"coupang": False, "naver": False, "toss": False}
    assert published.is_error is True


async def test_live_server_reports_execution_only_for_composed_channels(
    tmp_path: Path,
) -> None:
    credentials_only_coupang = _credential_file(tmp_path, naver=False, toss=False)
    server = build_live_server(
        credentials_only_coupang,
        publish_prerequisites=_publish_prerequisites(tmp_path),
    )
    async with Client(server) as client:
        readiness = await client.call_tool(
            "commerce_prepare_marketplace_product_drafts",
            {
                "product": {},
                "channel_configs": [
                    {"channel": "coupang"},
                    {"channel": "naver"},
                    {"channel": "toss"},
                ],
            },
        )
    flags = {
        row["channel"]: row["external_execution_configured"]
        for row in readiness.structured_content["channels"]
    }
    assert flags == {"coupang": True, "naver": False, "toss": False}


async def test_live_publish_tools_execute_approved_drafts_end_to_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prerequisites = _publish_prerequisites(tmp_path)
    cred_file = _credential_file(
        tmp_path,
        extra_lines=(
            f"DOR_APPROVAL_DATABASE={prerequisites.dor_database}",
            f"DOR_NAVER_ASSET_ROOT={prerequisites.naver_asset_root}",
        ),
    )
    coupang_draft, naver_draft, toss_draft = (
        _coupang_draft(),
        _naver_draft(),
        _toss_draft(),
    )
    evidences = {
        "coupang": _evidence(CoupangApprovalEvidence, coupang_draft),
        "naver": _evidence(NaverApprovalEvidence, naver_draft),
        "toss": _evidence(TossApprovalEvidence, toss_draft),
    }
    assert prerequisites.dor_database is not None
    for channel, evidence in evidences.items():
        _seed_dor(prerequisites.dor_database, evidence, channel)
    calls: dict[str, list[tuple[str, str]]] = {
        "coupang": [],
        "naver": [],
        "toss": [],
    }
    _patch_clients(
        monkeypatch,
        coupang_calls=calls["coupang"],
        naver_calls=calls["naver"],
        toss_calls=calls["toss"],
        naver_draft=naver_draft,
    )

    async with Client(build_live_server(cred_file)) as client:
        results = {
            channel: await client.call_tool(
                f"commerce_publish_{channel}_product",
                {
                    "draft": draft.model_dump(mode="json"),
                    "approval": evidences[channel].model_dump(mode="json"),
                    "idempotency_key": evidences[channel].artifact_digest,
                },
            )
            for channel, draft in (
                ("coupang", coupang_draft),
                ("naver", naver_draft),
                ("toss", toss_draft),
            )
        }

    for channel, result in results.items():
        assert result.is_error is False, channel
        assert result.structured_content["status"] == "published", channel
        assert result.structured_content["receipt_verified"] is True, channel
    assert str(COUPANG_PRODUCT_ID) not in str(results["coupang"].structured_content)
    assert str(NAVER_ORIGIN_NO) not in str(results["naver"].structured_content)
    assert str(NAVER_CHANNEL_NO) not in str(results["naver"].structured_content)
    assert str(TOSS_PRODUCT_ID) not in str(results["toss"].structured_content)
    assert [method for method, _ in calls["coupang"]] == ["POST", "GET"]
    assert calls["coupang"][0][1].endswith("/marketplace/seller-products")
    assert calls["coupang"][1][1].endswith(f"/seller-products/{COUPANG_PRODUCT_ID}")
    assert [method for method, _ in calls["naver"]] == ["POST", "POST", "POST", "GET"]
    assert calls["naver"][1][1].endswith("/v1/product-images/upload")
    assert calls["naver"][2][1].endswith("/v2/products")
    assert calls["naver"][3][1].endswith(f"/origin-products/{NAVER_ORIGIN_NO}")
    assert [method for method, _ in calls["toss"]] == ["POST", "POST", "GET"]
    assert calls["toss"][1][1].endswith("/products/v2")
    assert calls["toss"][2][1].endswith(f"/products/{TOSS_PRODUCT_ID}")


async def test_publish_fails_closed_when_intent_row_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prerequisites = _publish_prerequisites(tmp_path)
    cred_file = _credential_file(tmp_path)
    draft = _toss_draft()
    evidence = _evidence(TossApprovalEvidence, draft)
    assert prerequisites.dor_database is not None
    _seed_dor(prerequisites.dor_database, evidence, "toss", intent=False)
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        composition,
        "TossShoppingClient",
        lambda credentials: TossShoppingClient(
            credentials, transport=_toss_transport(calls)
        ),
    )

    async with Client(
        build_live_server(cred_file, publish_prerequisites=prerequisites)
    ) as client:
        result = await client.call_tool(
            "commerce_publish_toss_product",
            {
                "draft": draft.model_dump(mode="json"),
                "approval": evidence.model_dump(mode="json"),
                "idempotency_key": evidence.artifact_digest,
            },
        )

    assert result.is_error is True
    assert calls == []


async def test_publish_rejects_mismatched_idempotency_key_before_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prerequisites = _publish_prerequisites(tmp_path)
    cred_file = _credential_file(tmp_path)
    draft = _coupang_draft()
    evidence = _evidence(CoupangApprovalEvidence, draft)
    assert prerequisites.dor_database is not None
    _seed_dor(prerequisites.dor_database, evidence, "coupang")
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        composition,
        "CoupangClient",
        lambda credentials: CoupangClient(
            credentials, transport=_coupang_transport(calls)
        ),
    )

    async with Client(
        build_live_server(cred_file, publish_prerequisites=prerequisites)
    ) as client:
        result = await client.call_tool(
            "commerce_publish_coupang_product",
            {
                "draft": draft.model_dump(mode="json"),
                "approval": evidence.model_dump(mode="json"),
                "idempotency_key": "b" * 64,
            },
        )

    assert result.is_error is True
    assert calls == []


async def test_coupang_readback_wraps_seller_product_detail(tmp_path: Path) -> None:
    calls: list[tuple[str, str]] = []
    client = CoupangClient(
        load_marketplace_credentials(_credential_file(tmp_path)).coupang,
        transport=_coupang_transport(calls),
    )
    gateway = CoupangPublishClient(client)

    readback = await gateway.get_seller_product(seller_product_id=COUPANG_PRODUCT_ID)

    assert readback == {
        "code": "SUCCESS",
        "data": {"sellerProductId": COUPANG_PRODUCT_ID},
    }
    assert calls == [
        (
            "GET",
            "/v2/providers/seller_api/apis/api/v1/marketplace"
            f"/seller-products/{COUPANG_PRODUCT_ID}",
        )
    ]


async def test_toss_readback_wraps_success_envelope(tmp_path: Path) -> None:
    calls: list[tuple[str, str]] = []
    client = TossShoppingClient(
        load_marketplace_credentials(_credential_file(tmp_path)).toss,
        transport=_toss_transport(calls),
    )
    gateway = TossPublishClient(client)

    readback = await gateway.get_product(product_id=TOSS_PRODUCT_ID)

    assert readback["resultType"] == "SUCCESS"
    assert readback["success"]["id"] == TOSS_PRODUCT_ID


async def test_coupang_readback_failure_surfaces_as_unverified(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": "ERROR", "data": None})

    client = CoupangClient(
        load_marketplace_credentials(_credential_file(tmp_path)).coupang,
        transport=httpx.MockTransport(handler),
    )
    gateway = CoupangPublishClient(client)

    readback = await gateway.get_seller_product(seller_product_id=1)

    assert readback["code"] != "SUCCESS"
    assert readback["data"] is None
