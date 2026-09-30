from pathlib import Path

from mcp import Client

from k12_commerce_mcp.models import Channel, CredentialState, ImplementationStatus
from k12_commerce_mcp.permissions import APPROVED_TOOL_NAMES
from k12_commerce_mcp.server import build_live_server, build_live_service


def credential_file(tmp_path: Path) -> Path:
    path = tmp_path / "marketplace-readonly.env"
    path.write_text(
        "DOR_COUPANG_VENDOR_ID=vendor-fixture\n"
        "DOR_COUPANG_ACCESS_KEY=access-fixture\n"
        "DOR_COUPANG_SECRET_KEY=secret-fixture\n"
        "DOR_NAVER_CLIENT_ID=naver-client-fixture\n"
        "DOR_NAVER_CLIENT_SECRET=$2b$10$abcdefghijklmnopqrstuu\n",
        encoding="utf-8",
    )
    path.chmod(0o600)
    return path


def test_live_service_registers_configured_coupang_without_network(tmp_path: Path) -> None:
    service = build_live_service(credential_file(tmp_path))

    assert service.registry.list_channels() == (
        "coupang",
        "coupang_general",
        "coupang_rocket_growth",
        "naver",
    )
    channels = {item.channel: item for item in service.list_channels().channels}
    assert channels[Channel.COUPANG].implementation_status is ImplementationStatus.ACTIVE
    assert channels[Channel.COUPANG].credential_state is CredentialState.CONFIGURED
    assert channels[Channel.COUPANG].external_calls_enabled is True
    assert channels[Channel.COUPANG_GENERAL].credential_state is CredentialState.CONFIGURED
    assert channels[Channel.COUPANG_ROCKET_GROWTH].credential_state is CredentialState.CONFIGURED
    assert channels[Channel.NAVER].implementation_status is ImplementationStatus.ACTIVE
    assert channels[Channel.NAVER].credential_state is CredentialState.CONFIGURED
    assert channels[Channel.NAVER].external_calls_enabled is True
    assert channels[Channel.ELEVENST].credential_state is CredentialState.NOT_CONFIGURED
    assert channels[Channel.TOSS_STORE].credential_state is CredentialState.NOT_CONFIGURED


def test_live_health_reports_enabled_external_reads_but_no_database(tmp_path: Path) -> None:
    health = build_live_service(credential_file(tmp_path)).health_check()

    assert health.phase == "1B"
    assert health.external_calls_enabled is True
    assert health.credentials_enabled is True
    assert health.database_enabled is False


async def test_live_server_lists_tools_without_calling_provider(tmp_path: Path) -> None:
    async with Client(build_live_server(credential_file(tmp_path))) as client:
        listed = await client.list_tools()
        channels = await client.call_tool("commerce_list_channels")

    assert len(listed.tools) == len(APPROVED_TOOL_NAMES)
    by_channel = {row["channel"]: row for row in channels.structured_content["channels"]}
    assert by_channel["coupang"]["implementation_status"] == "active"
    assert by_channel["coupang"]["credential_state"] == "configured"


async def test_live_publish_tool_is_fetch_only_and_not_configured(tmp_path: Path) -> None:
    draft = {
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
        "image_storage_ref": "main.png",
        "image_mime_type": "image/png",
        "image_byte_size": 1,
        "image_sha256": "a" * 64,
    }
    approval = {
        "marketing_review": True,
        "ceo_preview_approval": True,
        "external_publish_approval": True,
        "evidence_recorded_at": "2026-09-14T00:00:00Z",
        "marketing_reviewed_at": "2026-09-14T00:00:01Z",
        "ceo_preview_approved_at": "2026-09-14T00:00:02Z",
        "external_publish_approved_at": "2026-09-14T00:00:03Z",
        "artifact_digest": "a" * 64,
        "attempt_id": "attempt-1",
        "project_id": "project-1",
        "batch_id": "batch-1",
        "version": 1,
        "effective_from": "2026-09-14T00:00:00Z",
    }

    async with Client(build_live_server(credential_file(tmp_path))) as client:
        result = await client.call_tool(
            "commerce_publish_naver_product",
            {
                "draft": draft,
                "approval": approval,
                "idempotency_key": "a" * 64,
            },
        )

    assert result.is_error is True
    text = " ".join(getattr(item, "text", "") for item in result.content)
    assert "Error executing tool commerce_publish_naver_product" in text
    assert "not configured" not in text
