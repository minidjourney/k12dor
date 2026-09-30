"""Unapplied connection proposals for Coupang general missing safe reads.

This module does not register tools, edit the client allowlist, import the
provider client, or issue HTTP. A synthetic facade is not a distinct MCP tool.
Vendor id stays a credential concern and is never a caller field.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .general_full_catalog_reads import list_unsupported_operations
from .general_missing_reads import (
    CoupangGeneralMissingReads,
    MissingReadError,
    list_disabled_query_posts,
    list_missing_reads,
    list_unconfirmed_exclusions,
)

_PLACEHOLDERS = {
    "vendorId": "vendor_id",
    "requestedId": "requested_id",
    "orderId": "order_id",
    "couponId": "coupon_id",
    "couponItemId": "coupon_item_id",
    "vendorItemId": "vendor_item_id",
}
_PLACEHOLDER = re.compile(r"\{([^}]+)\}")
_PROJECTION = (
    "k12_commerce_mcp.adapters.coupang.general_missing_reads.CoupangGeneralMissingReads"
)
_LATER_CLIENT = "src/k12_commerce_mcp/clients/coupang.py"
_COURIER_PAGE = "ko_api_logistics_courier-code.html"


class FollowupReadError(ValueError):
    """Raised when a connection proposal is rejected. The message never echoes input."""


@dataclass(frozen=True)
class _Contract:
    client_method: str
    caller_fields: tuple[str, ...]
    required_fields: tuple[str, ...]
    path_fields: tuple[str, ...]
    query_fields: tuple[str, ...]
    provider_query_names: tuple[str, ...]
    fixed_query: tuple[tuple[str, str], ...] = ()
    allowlist_segment_collision: tuple[str, ...] = ()


@dataclass(frozen=True)
class SafeReadConnectionProposal:
    operation_id: str
    method: str
    documented_path_template: str
    proposed_allowlist_template: str
    proposed_client_method: str
    source_doc: str
    category: str
    query_evidence: str
    caller_fields: tuple[str, ...]
    required_fields: tuple[str, ...]
    path_fields: tuple[str, ...]
    query_fields: tuple[str, ...]
    provider_query_names: tuple[str, ...]
    fixed_query: tuple[tuple[str, str], ...]
    allowlist_segment_collision: tuple[str, ...]
    vendor_id_source: str
    projection_owner: str
    later_client_file: str
    applied: bool = False
    transport_connected: bool = False
    live_call: bool = False
    transmit_now: bool = False
    mcp_callable: bool = False
    mcp_tool_name: str | None = None
    generic_facade_is_distinct_tool: bool = False
    state_change_explicitly_denied: bool = False


@dataclass(frozen=True)
class BlockedConnection:
    operation_id: str
    method: str
    reason: str
    source_doc: str
    applied: bool = False
    mcp_callable: bool = False
    generic_facade_is_distinct_tool: bool = False
    transmit_now: bool = False


_CONTRACTS: dict[str, _Contract] = {
    "budget_status": _Contract(
        "list_budget_status",
        ("contract_id", "target_month"),
        ("target_month",),
        (),
        ("contract_id", "target_month"),
        ("contractId", "targetMonth"),
    ),
    "instant_coupon_request_status": _Contract(
        "get_instant_coupon_request_status",
        ("requested_id",),
        ("requested_id",),
        ("requested_id",),
        (),
        (),
    ),
    "instant_coupons_by_order": _Contract(
        "list_instant_coupons_by_order",
        ("order_id",),
        ("order_id",),
        ("order_id",),
        (),
        (),
    ),
    "instant_coupons_by_status": _Contract(
        "list_instant_coupons_by_status",
        ("status", "page", "size", "sort"),
        ("status",),
        (),
        ("status", "page", "size", "sort"),
        ("status", "page", "size", "sort"),
    ),
    "instant_coupon_items_by_status": _Contract(
        "list_instant_coupon_items_by_status",
        ("coupon_id", "status", "page", "size", "sort"),
        ("coupon_id", "status"),
        ("coupon_id",),
        ("status", "page", "size", "sort"),
        ("status", "page", "size", "sort"),
    ),
    "instant_coupon_by_id": _Contract(
        "get_instant_coupon",
        ("coupon_id",),
        ("coupon_id",),
        (),
        ("coupon_id",),
        ("couponId",),
    ),
    "instant_coupon_item_by_coupon_item_id": _Contract(
        "get_instant_coupon_item_by_coupon_item_id",
        ("coupon_id", "coupon_item_id"),
        ("coupon_id", "coupon_item_id"),
        ("coupon_id", "coupon_item_id"),
        (),
        ("type",),
        (("type", "couponItemId"),),
        ("instant_coupon_item_by_vendor_item_id",),
    ),
    "instant_coupon_item_by_vendor_item_id": _Contract(
        "get_instant_coupon_item_by_vendor_item_id",
        ("coupon_id", "vendor_item_id"),
        ("coupon_id", "vendor_item_id"),
        ("coupon_id", "vendor_item_id"),
        (),
        ("type",),
        (("type", "vendorItemId"),),
        ("instant_coupon_item_by_coupon_item_id",),
    ),
    "cashback_rule": _Contract(
        "get_cashback_rule",
        ("rule_id", "vendor_item_id"),
        ("rule_id", "vendor_item_id"),
        (),
        ("rule_id", "vendor_item_id"),
        ("ruleId", "vendorItemId"),
    ),
}


def _allowlist_template(path: str) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        mapped = _PLACEHOLDERS.get(name)
        if mapped is None:
            raise FollowupReadError("unknown path placeholder")
        return "{" + mapped + "}"

    return _PLACEHOLDER.sub(replace, path)


def _proposal(item: object, contract: _Contract) -> SafeReadConnectionProposal:
    path = item.path_template
    vendor_in_path = "{vendorId}" in path
    if "vendor_id" in contract.caller_fields or "vendorId" in contract.caller_fields:
        raise FollowupReadError("vendor id is not a caller field")
    return SafeReadConnectionProposal(
        operation_id=item.operation_id,
        method="GET",
        documented_path_template=path,
        proposed_allowlist_template=_allowlist_template(path),
        proposed_client_method=contract.client_method,
        source_doc=item.source_doc,
        category=item.category,
        query_evidence=item.query_evidence,
        caller_fields=contract.caller_fields,
        required_fields=contract.required_fields,
        path_fields=contract.path_fields,
        query_fields=contract.query_fields,
        provider_query_names=contract.provider_query_names,
        fixed_query=contract.fixed_query,
        allowlist_segment_collision=contract.allowlist_segment_collision,
        vendor_id_source="client_credentials" if vendor_in_path else "not_in_path",
        projection_owner=_PROJECTION,
        later_client_file=_LATER_CLIENT,
        state_change_explicitly_denied=item.state_change_explicitly_denied,
    )


def list_blocked_connections() -> tuple[BlockedConnection, ...]:
    unsupported = {item.operation_id: item for item in list_unsupported_operations()}
    blocked: list[BlockedConnection] = []
    for item in list_missing_reads():
        conflict = unsupported.get(item.operation_id)
        if conflict is None:
            continue
        if conflict.effect_class != "get_effect_unknown":
            raise FollowupReadError("unexpected catalog conflict")
        blocked.append(
            BlockedConnection(
                operation_id=item.operation_id,
                method=item.method,
                reason="catalog_effect_unknown",
                source_doc=item.source_doc,
            )
        )
    for item in list_disabled_query_posts():
        blocked.append(
            BlockedConnection(
                operation_id=item.operation_id,
                method=item.method,
                reason="disabled_query_post",
                source_doc=item.source_doc,
            )
        )
    for item in list_unconfirmed_exclusions():
        page = item.source_doc.rsplit("/", 1)[-1]
        if page != _COURIER_PAGE:
            raise FollowupReadError("unknown exclusion")
        blocked.append(
            BlockedConnection(
                operation_id="courier_code_table",
                method="",
                reason="no_http_operation",
                source_doc=item.source_doc,
            )
        )
    return tuple(blocked)


def propose_safe_read_connections() -> tuple[SafeReadConnectionProposal, ...]:
    blocked_ids = {item.operation_id for item in list_blocked_connections()}
    proposals: list[SafeReadConnectionProposal] = []
    seen: set[str] = set()
    for item in list_missing_reads():
        if item.operation_id in blocked_ids:
            continue
        if item.method != "GET" or not item.execution_enabled:
            raise FollowupReadError("missing read is not a safe GET")
        if item.client_allowlisted or item.transport_connected or "/rg/" in item.path_template:
            raise FollowupReadError("missing read is already connected")
        contract = _CONTRACTS.get(item.operation_id)
        if contract is None:
            raise FollowupReadError("missing connection contract")
        proposal = _proposal(item, contract)
        if proposal.operation_id in seen:
            raise FollowupReadError("duplicate connection proposal")
        seen.add(proposal.operation_id)
        proposals.append(proposal)
    if seen != set(_CONTRACTS):
        raise FollowupReadError("connection contract does not match missing reads")
    return tuple(proposals)


def refuse_blocked_connection(operation_id: str) -> None:
    blocked = {item.operation_id: item for item in list_blocked_connections()}
    item = blocked.get(operation_id)
    if item is None:
        raise FollowupReadError("not a blocked connection")
    raise FollowupReadError(f"{item.reason} is not connectable")


_LIVE_READER_NAMES = frozenset({"CoupangClient", "CoupangGeneralAdapter"})


@dataclass(frozen=True)
class ConnectionDryRun:
    operation_id: str
    items: tuple[dict[str, object], ...]
    page: dict[str, int] | None
    proposal: SafeReadConnectionProposal
    applied: bool = False
    transport_connected: bool = False
    live_call: bool = False
    transmit_now: bool = False
    mcp_callable: bool = False
    mcp_tool_name: str | None = None
    generic_facade_is_distinct_tool: bool = False


def _ensure_synthetic_reader(reader: object) -> None:
    if reader is None or type(reader).__name__ in _LIVE_READER_NAMES:
        raise FollowupReadError("transport not connected")
    if type(reader).__module__.startswith("k12_commerce_mcp.clients"):
        raise FollowupReadError("transport not connected")


async def dry_run_connection(
    operation_id: str,
    reader: object,
    **filters: object,
) -> ConnectionDryRun:
    if operation_id in {item.operation_id for item in list_blocked_connections()}:
        refuse_blocked_connection(operation_id)
    proposal = next(
        (item for item in propose_safe_read_connections() if item.operation_id == operation_id),
        None,
    )
    if proposal is None:
        raise FollowupReadError("not a safe connection proposal")
    if "vendor_id" in filters or "vendorId" in filters:
        raise FollowupReadError("vendor id is not a caller field")
    _ensure_synthetic_reader(reader)
    try:
        projected = await CoupangGeneralMissingReads(reader).read(operation_id, **filters)
    except MissingReadError as exc:
        raise FollowupReadError(str(exc)) from None
    return ConnectionDryRun(
        operation_id=operation_id,
        items=projected.items,
        page=projected.page,
        proposal=proposal,
    )
