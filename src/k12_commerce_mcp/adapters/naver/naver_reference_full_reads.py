"""Static-capture audit and synthetic previews for Naver reference reads.

This module records what the 2026-09-16 static HTML capture alone established;
its missing JavaScript-rendered schemas are NOT a finding that the official
provider contract is unavailable. The rendered official documentation was
subsequently verified and the live bounded shared MCP implementation is in
``naver_reference_mcp.py``. The disabled flags here describe only this
synthetic-only facade, not the active shared MCP endpoint.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ...clients.naver import NaverClient
from ...models.common import CanonicalModel
from ..base import AdapterInvalidRequestError, AdapterInvalidResponseError
from .naver_full_classification import READ_GET, classification_index
from .naver_full_reads import (
    SafeReadPage,
    check_read_params,
    project_read_result,
    read_request_contract,
)

_SCHEMA_ABSENT = "unverified_absent_in_static_capture"
_SCHEMA_NO_SECTION = "unverified_no_request_section"
_PAGINATION_UNVERIFIED = "unverified"
_BLOCKED_REASON = "request_schema_unverified_js_rendered"

# operation_id -> request section present in the static capture, verified by
# scripts/build_naver_official_contract.py against the 2026-09-16 snapshot.
# Two pages show no Request section at all; the other six render the section
# heading but only openapi-skeleton placeholders, never field names.
_REFERENCE_ROWS: tuple[tuple[str, bool], ...] = (
    ("get-brand-list-product", True),
    ("get-manufacturer-list-product", True),
    ("get-all-origin-area-list-product", False),
    ("get-origin-area-list-product", True),
    ("get-sub-origin-area-list-product", True),
    ("get-attribute-list-product", True),
    ("get-attribute-value-list-product", True),
    ("get-attribute-value-unit-list-product", False),
)


class ReferenceContractError(RuntimeError):
    """The reference-read slice no longer matches the capture."""


class ReferenceReadContract(CanonicalModel):
    """Verified identity and verification gaps of one reference read.

    Method/path/status/document evidence is captured truth; the request and
    response field schemas are not in the capture, so dispatch stays disabled
    and ``mcp_tool`` stays ``None``.
    """

    operation_id: str
    method: str
    path: str
    title: str
    document_ref: str
    source_url: str
    documented_statuses: tuple[int, ...]
    effect_class: str
    path_params: tuple[str, ...]
    request_section_present: bool
    request_schema: str
    response_schema: str
    pagination: str
    on_client_read_allowlist: bool
    mcp_tool: str | None
    dispatchable_now: bool
    execution_enabled: bool
    live_call: bool
    blocked_reason: str


def reference_read_ids() -> frozenset[str]:
    """The eight official reference-read operation ids."""
    return frozenset(operation_id for operation_id, _ in _REFERENCE_ROWS)


def reference_read_contracts() -> tuple[ReferenceReadContract, ...]:
    """Slice contracts joined to the classified capture inventory."""
    index = classification_index()
    contracts: list[ReferenceReadContract] = []
    for operation_id, request_section in _REFERENCE_ROWS:
        item = index.get(operation_id)
        if item is None or item.effect_class != READ_GET or item.method != "GET":
            raise ReferenceContractError(
                f"reference read {operation_id} is not a documented GET read"
            )
        if item.execution_enabled or item.live_call:
            raise ReferenceContractError(f"reference read {operation_id} is not disabled")
        base = read_request_contract(operation_id)
        contracts.append(
            ReferenceReadContract(
                operation_id=operation_id,
                method=base.method,
                path=base.path,
                title=base.source_title,
                document_ref=base.document_ref,
                source_url=item.source_url,
                documented_statuses=base.documented_statuses,
                effect_class=base.effect_class,
                path_params=base.path_params,
                request_section_present=request_section,
                request_schema=_SCHEMA_ABSENT if request_section else _SCHEMA_NO_SECTION,
                response_schema=_SCHEMA_ABSENT,
                pagination=_PAGINATION_UNVERIFIED,
                on_client_read_allowlist=base.on_client_read_allowlist,
                mcp_tool=None,
                dispatchable_now=False,
                execution_enabled=False,
                live_call=False,
                blocked_reason=_BLOCKED_REASON,
            )
        )
    return tuple(contracts)


def reference_read_contract(operation_id: str) -> ReferenceReadContract:
    """One slice contract; operations outside the slice are refused."""
    for item in reference_read_contracts():
        if item.operation_id == operation_id:
            return item
    raise AdapterInvalidRequestError("operation is not a reference-slice read")


def reference_read_summary() -> dict[str, object]:
    """Aggregate counts for review. No provider call, no payload data."""
    contracts = reference_read_contracts()
    return {
        "operation_count": len(contracts),
        "on_client_read_allowlist": sum(1 for item in contracts if item.on_client_read_allowlist),
        "mcp_exposed": sum(1 for item in contracts if item.mcp_tool is not None),
        "dispatchable_now": sum(1 for item in contracts if item.dispatchable_now),
        "execution_enabled": sum(1 for item in contracts if item.execution_enabled),
        "live_call": sum(1 for item in contracts if item.live_call),
        "request_section_present": sum(1 for item in contracts if item.request_section_present),
        "request_schema_unverified": sum(
            1 for item in contracts if item.request_schema != "documented"
        ),
    }


class NaverReferenceFullReads:
    """Synthetic-only previews for the reference-read slice.

    A verified synthetic transport is required so this facade can never reach
    a provider. The request schema is unverified for every slice operation, so
    exchanges send only the documented method and path — never query params
    or a body — and results are projected onto caller-named scalar allowlists
    with bounded output.
    """

    def __init__(self, transport: Any, *, clock: Any = None) -> None:
        if isinstance(transport, NaverClient) or getattr(transport, "synthetic", False) is not True:
            raise AdapterInvalidRequestError(
                "naver reference reads accept a synthetic transport only"
            )
        if not callable(getattr(transport, "exchange", None)):
            raise AdapterInvalidRequestError(
                "naver reference reads accept a synthetic transport only"
            )
        self.transport = transport
        self._clock = clock or (lambda: datetime.now(UTC))

    async def preview_reference_read(
        self,
        operation_id: str,
        *,
        allowed_keys: frozenset[str],
        page_size: int,
        cursor: str | None = None,
    ) -> SafeReadPage:
        """Synthetic exchange and bounded projection for one slice read."""
        spec = reference_read_contract(operation_id)
        if not allowed_keys:
            raise AdapterInvalidRequestError("projection requires a non-empty allowlist")
        bound = check_read_params(page_size=page_size, cursor=cursor)
        result = await self.transport.exchange(method=spec.method, path=spec.path)
        if not isinstance(result, tuple) or len(result) != 2 or type(result[0]) is not int:
            raise AdapterInvalidResponseError("naver reference read transport shape is invalid")
        return project_read_result(
            result[0],
            result[1],
            contract=read_request_contract(operation_id),
            allowed_keys=allowed_keys,
            max_items=bound,
            transport_kind="synthetic",
            clock=self._clock,
        )

    async def preview_brands(
        self,
        *,
        allowed_keys: frozenset[str],
        page_size: int,
        cursor: str | None = None,
    ) -> SafeReadPage:
        return await self.preview_reference_read(
            "get-brand-list-product",
            allowed_keys=allowed_keys,
            page_size=page_size,
            cursor=cursor,
        )

    async def preview_manufacturers(
        self,
        *,
        allowed_keys: frozenset[str],
        page_size: int,
        cursor: str | None = None,
    ) -> SafeReadPage:
        return await self.preview_reference_read(
            "get-manufacturer-list-product",
            allowed_keys=allowed_keys,
            page_size=page_size,
            cursor=cursor,
        )

    async def preview_origin_areas(
        self,
        *,
        allowed_keys: frozenset[str],
        page_size: int,
        cursor: str | None = None,
    ) -> SafeReadPage:
        return await self.preview_reference_read(
            "get-all-origin-area-list-product",
            allowed_keys=allowed_keys,
            page_size=page_size,
            cursor=cursor,
        )

    async def preview_origin_area_query(
        self,
        *,
        allowed_keys: frozenset[str],
        page_size: int,
        cursor: str | None = None,
    ) -> SafeReadPage:
        return await self.preview_reference_read(
            "get-origin-area-list-product",
            allowed_keys=allowed_keys,
            page_size=page_size,
            cursor=cursor,
        )

    async def preview_sub_origin_areas(
        self,
        *,
        allowed_keys: frozenset[str],
        page_size: int,
        cursor: str | None = None,
    ) -> SafeReadPage:
        return await self.preview_reference_read(
            "get-sub-origin-area-list-product",
            allowed_keys=allowed_keys,
            page_size=page_size,
            cursor=cursor,
        )

    async def preview_attributes(
        self,
        *,
        allowed_keys: frozenset[str],
        page_size: int,
        cursor: str | None = None,
    ) -> SafeReadPage:
        return await self.preview_reference_read(
            "get-attribute-list-product",
            allowed_keys=allowed_keys,
            page_size=page_size,
            cursor=cursor,
        )

    async def preview_attribute_values(
        self,
        *,
        allowed_keys: frozenset[str],
        page_size: int,
        cursor: str | None = None,
    ) -> SafeReadPage:
        return await self.preview_reference_read(
            "get-attribute-value-list-product",
            allowed_keys=allowed_keys,
            page_size=page_size,
            cursor=cursor,
        )

    async def preview_attribute_value_units(
        self,
        *,
        allowed_keys: frozenset[str],
        page_size: int,
        cursor: str | None = None,
    ) -> SafeReadPage:
        return await self.preview_reference_read(
            "get-attribute-value-unit-list-product",
            allowed_keys=allowed_keys,
            page_size=page_size,
            cursor=cursor,
        )
