from pathlib import Path

from mcp import Client

from k12_commerce_mcp.models import Channel, CredentialState
from k12_commerce_mcp.server import build_live_server, build_live_service


def unconfigured_toss_file(tmp_path: Path) -> Path:
    path = tmp_path / "marketplace-readonly.env"
    path.write_text("# no toss credentials\n", encoding="utf-8")
    path.chmod(0o600)
    return path


def test_toss_remains_not_configured_without_credentials(tmp_path: Path) -> None:
    service = build_live_service(unconfigured_toss_file(tmp_path))
    descriptor = next(
        row for row in service.list_channels().channels if row.channel is Channel.TOSS_STORE
    )

    assert "toss_store" not in service.registry.list_channels()
    assert descriptor.credential_state is CredentialState.NOT_CONFIGURED
    assert descriptor.external_calls_enabled is False


async def test_toss_read_tools_fail_closed_without_credentials(tmp_path: Path) -> None:
    async with Client(build_live_server(unconfigured_toss_file(tmp_path))) as client:
        health = await client.call_tool("commerce_health_check")
        orders = await client.call_tool(
            "commerce_get_orders",
            {"channel": "toss_store", "page_size": 1},
        )
        products = await client.call_tool(
            "commerce_get_products",
            {"channel": "toss_store", "page_size": 1},
        )
        settlements = await client.call_tool(
            "commerce_get_settlements",
            {"channel": "toss_store", "page_size": 1},
        )

    assert health.is_error is False
    assert health.structured_content["database_enabled"] is False
    for result in (orders, products, settlements):
        assert result.is_error is False
        assert result.structured_content["status"] == "unsupported"
        assert result.structured_content["errors"][0]["code"] == "adapter_not_configured"


async def test_configured_toss_order_detail_is_explicitly_unsupported(tmp_path: Path) -> None:
    path = tmp_path / "marketplace-readonly.env"
    path.write_text(
        "DOR_TOSS_SHOPPING_ACCESS_KEY=synthetic-access\n"
        "DOR_TOSS_SHOPPING_SECRET_KEY=synthetic-secret\n",
        encoding="utf-8",
    )
    path.chmod(0o600)
    service = build_live_service(path)

    result = await service.get_order_detail(Channel.TOSS_STORE, "opaque-ref")

    assert result.status.value == "unsupported"
    assert result.item is None
    assert result.reasons == ("adapter_not_configured",)
