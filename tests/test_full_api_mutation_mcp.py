"""Official non-read operation contract is visible in MCP but execution is blocked."""

from mcp import Client

from k12_commerce_mcp.server import build_server
from k12_commerce_mcp.simulations.full_api_contract import build_contract


def contract():
    return build_contract(
        [
            {
                "channel": "naver",
                "method": "PUT",
                "path": "/v1/products/{id}",
                "effect_class": "mutation",
                "function_name": "synthetic edit",
                "query_param_names": [],
            },
            {
                "channel": "coupang_general",
                "method": "GET",
                "path": "/v1/read",
                "effect_class": "read",
                "function_name": "synthetic read",
                "query_param_names": [],
            },
        ]
    )


async def test_mutation_mcp_lists_only_nonreads_and_blocks_execution():
    c = contract()
    async with Client(build_server(full_api_contract=c)) as client:
        page = await client.call_tool(
            "commerce_list_documented_change_operations", {"channel": "naver", "page_size": 10}
        )
        assert not page.is_error
        result = page.structured_content
        assert result["status"] == "disabled_simulation"
        assert len(result["items"]) == 1
        entry_id = result["items"][0]["entry_id"]
        assert result["items"][0]["execution_enabled"] is False
        assert result["items"][0]["kind"] == "documented_write"
        blocked = await client.call_tool(
            "commerce_simulate_documented_change", {"entry_id": entry_id}
        )
        assert not blocked.is_error
        assert blocked.structured_content["status"] == "blocked"
        assert blocked.structured_content["executed"] is False
        assert blocked.structured_content["ceo_per_target_approval_required"] is True
        assert blocked.structured_content["network_calls"] == 0


async def test_mutation_mcp_rejects_unlisted_reference_and_never_calls_transport():
    async with Client(build_server(full_api_contract=contract())) as client:
        bad = await client.call_tool(
            "commerce_simulate_documented_change", {"entry_id": "contract-ffffffffffffffff"}
        )
        assert not bad.is_error
        assert bad.structured_content["status"] == "unknown_reference"
        assert bad.structured_content["executed"] is False
        assert "ffffffff" not in str(bad.structured_content)


async def test_mutation_mcp_page_has_no_provider_path_or_raw_payload():
    c = contract()
    async with Client(build_server(full_api_contract=c)) as client:
        page = await client.call_tool(
            "commerce_list_documented_change_operations", {"channel": "naver", "page_size": 1}
        )
    entry = page.structured_content["items"][0]
    assert set(entry) == {"entry_id", "channel", "method", "kind", "execution_enabled"}
    assert "path" not in str(entry)
