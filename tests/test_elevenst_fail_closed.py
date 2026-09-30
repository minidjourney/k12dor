from pathlib import Path

from mcp import Client

from k12_commerce_mcp.models import Channel, CredentialState
from k12_commerce_mcp.server import build_live_server, build_live_service


def unverified_elevenst_file(tmp_path: Path) -> Path:
    path = tmp_path / "marketplace-readonly.env"
    path.write_text(
        "DOR_11ST_API_KEY=must-not-activate\n"
        "DOR_11ST_SELLER_ID=must-not-activate\n",
        encoding="utf-8",
    )
    path.chmod(0o600)
    return path


def test_unverified_elevenst_variable_names_do_not_activate_adapter(tmp_path: Path) -> None:
    service = build_live_service(unverified_elevenst_file(tmp_path))
    descriptor = next(
        row for row in service.list_channels().channels if row.channel is Channel.ELEVENST
    )

    assert "elevenst" not in service.registry.list_channels()
    assert descriptor.credential_state is CredentialState.NOT_CONFIGURED
    assert descriptor.external_calls_enabled is False


async def test_elevenst_read_tools_fail_closed_without_provider_call(tmp_path: Path) -> None:
    async with Client(build_live_server(unverified_elevenst_file(tmp_path))) as client:
        results = [
            await client.call_tool(
                "commerce_get_orders",
                {"channel": "elevenst", "page_size": 1},
            ),
            await client.call_tool(
                "commerce_get_products",
                {"channel": "elevenst", "page_size": 1},
            ),
            await client.call_tool(
                "commerce_get_product_detail",
                {"channel": "elevenst", "external_product_id": "unverified"},
            ),
            await client.call_tool(
                "commerce_get_product_content",
                {"channel": "elevenst", "external_product_id": "unverified"},
            ),
            await client.call_tool(
                "commerce_get_inventory",
                {"channel": "elevenst", "page_size": 1},
            ),
            await client.call_tool(
                "commerce_get_returns",
                {"channel": "elevenst", "page_size": 1},
            ),
            await client.call_tool(
                "commerce_get_settlements",
                {"channel": "elevenst", "page_size": 1},
            ),
            await client.call_tool(
                "commerce_get_fees",
                {"channel": "elevenst", "page_size": 1},
            ),
        ]

    assert all(result.is_error is False for result in results)
    assert all(result.structured_content["status"] == "unsupported" for result in results)
    assert all(
        result.structured_content["errors"][0]["code"] == "adapter_not_configured"
        for result in results
    )
