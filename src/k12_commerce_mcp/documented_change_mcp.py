"""Closed MCP-facing catalogue of non-read contracts; never invokes a provider."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from .simulations.full_api_contract import ContractRefusal, FullApiContract, contract_from_manifest


class DocumentedChangeItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    entry_id: Annotated[str, Field(pattern=r"^contract-[0-9a-f]{16}$")]
    channel: Literal["coupang_general", "rocket_growth", "naver"]
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
    kind: Literal[
        "documented_write",
        "auth_token_issue",
        "unknown_effect_get",
        "unknown_effect_post",
        "unclassified_blocked",
    ]
    execution_enabled: Literal[False] = False


class DocumentedChangePage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    status: Literal["disabled_simulation", "unavailable"]
    items: tuple[DocumentedChangeItem, ...] = Field(max_length=50)
    next_cursor: int | None = None
    total_count: int | None = None
    reasons: tuple[Literal["contract_not_configured"], ...] = ()


class DocumentedChangeBlock(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    status: Literal["blocked", "unknown_reference"]
    executed: Literal[False] = False
    transport_enabled: Literal[False] = False
    network_calls: Literal[0] = 0
    ceo_per_target_approval_required: Literal[True] = True


def list_documented_changes(
    contract: FullApiContract | None, *, channel: str, page_size: int, cursor: int
) -> DocumentedChangePage:
    if (
        channel not in {"coupang_general", "rocket_growth", "naver"}
        or type(page_size) is not int
        or not 1 <= page_size <= 50
        or type(cursor) is not int
        or not 0 <= cursor <= 1000
    ):
        raise ValueError("invalid documented change request")
    if contract is None:
        return DocumentedChangePage(
            status="unavailable", items=(), reasons=("contract_not_configured",)
        )
    rows = [item for item in contract.entries if item.channel == channel]
    page = rows[cursor : cursor + page_size]
    return DocumentedChangePage(
        status="disabled_simulation",
        items=tuple(
            DocumentedChangeItem(
                entry_id=item.entry_id, channel=item.channel, method=item.method, kind=item.kind
            )
            for item in page
        ),
        next_cursor=cursor + len(page) if cursor + len(page) < len(rows) else None,
        total_count=len(rows),
    )


def simulate_documented_change(
    contract: FullApiContract | None, entry_id: str
) -> DocumentedChangeBlock:
    if contract is None or not isinstance(entry_id, str) or len(entry_id) != 25:
        return DocumentedChangeBlock(status="unknown_reference")
    try:
        contract.request_execution(entry_id)
    except ContractRefusal:
        return DocumentedChangeBlock(status="unknown_reference")
    return DocumentedChangeBlock(status="blocked")


def load_local_documented_change_contract() -> FullApiContract | None:
    """Use the existing immutable Wiki snapshot and builder, not a second API census."""
    script = Path(__file__).resolve().parents[2] / "scripts" / "build_three_channel_api_manifest.py"
    snapshot = Path("/data/documents/second-brain/raw/documents/marketplace-api-docs-20260916")
    try:
        spec = importlib.util.spec_from_file_location("_commerce_snapshot_builder", script)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        contract = contract_from_manifest(module.build_manifest(snapshot))
        if contract.operations_seen != 215 or len(contract.entries) != 115 or contract.collisions:
            return None
        return contract
    except (OSError, ValueError, TypeError, ImportError):
        return None
