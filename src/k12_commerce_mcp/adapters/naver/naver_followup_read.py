"""Historical synthetic follow-up for the Naver size-type GET.

Official contract row 63 is ``get-size-type-vo-product`` (사이즈 타입 조회):
GET ``/v1/product-sizes/:sizeTypeId``, effect ``read``. The static capture has
no request or response field schema, so this module does not invent fields,
does not mark this facade callable, and does not open a network connection.
A separately registered MCP single reader now handles the live operation.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from ...clients.naver import NaverClient
from ...models.common import CanonicalModel, ErrorCode
from ...security import assert_agent_safe_value
from ..base import AdapterFailure, AdapterInvalidRequestError, AdapterInvalidResponseError
from .missing_reads import missing_read_catalog, normalize_operation_path
from .naver_full_classification import READ_GET, bind_path_params, classification_index
from .naver_full_reads import read_request_contract

_OPERATION_ID = "get-size-type-vo-product"
_OFFICIAL_EFFECT = "read"
_UNVERIFIED = "unverified"
_NOT_IN_CAPTURE = "not_in_official_capture"
_INT64_MAX = 2**63 - 1
_MAX_ROWS = 100
_SENSITIVE_MARKERS = (
    "account",
    "address",
    "answer",
    "auth",
    "bank",
    "buyer",
    "cookie",
    "customer",
    "depositor",
    "email",
    "inquiry",
    "memo",
    "mobile",
    "orderer",
    "password",
    "phone",
    "purchaser",
    "receiver",
    "recipient",
    "secret",
    "tel",
    "token",
)


class FollowupContractError(RuntimeError):
    """Existing catalogs do not agree on this one read."""


class FollowupReadStatusError(AdapterFailure):
    """Documented non-success status. The body is never part of the message."""

    retryable = False

    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        self.code = {
            400: ErrorCode.INVALID_REQUEST,
            401: ErrorCode.AUTHENTICATION_FAILED,
            403: ErrorCode.AUTHENTICATION_FAILED,
            404: ErrorCode.NOT_FOUND,
        }.get(status_code, ErrorCode.INVALID_ADAPTER_RESPONSE)
        super().__init__("naver size-type result was not a page")


class FollowupReadContract(CanonicalModel):
    """Pinned identity for the one follow-up read. Not a provider call."""

    operation_id: str
    method: str
    path: str
    path_params: tuple[str, ...]
    title: str
    official_effect: str
    documented_statuses: tuple[int, ...]
    callable_now: bool
    input_schema: str
    output_schema: str
    query_params: str
    on_client_allowlist: bool
    projection: str
    live_call: bool


def followup_read_contract() -> FollowupReadContract:
    """Return the size-type contract only when existing sources still agree."""
    classified = classification_index().get(_OPERATION_ID)
    if classified is None or classified.effect_class != READ_GET:
        raise FollowupContractError("size-type read is not a documented GET")
    if classified.execution_enabled or classified.live_call:
        raise FollowupContractError("size-type read must stay disabled")
    if classified.on_client_write_allowlist:
        raise FollowupContractError("size-type read cannot be write-allowlisted")
    catalog = next(
        (
            item
            for item in missing_read_catalog()
            if item.method == "GET"
            and normalize_operation_path(item.path) == normalize_operation_path(classified.path)
        ),
        None,
    )
    if catalog is None or catalog.projection != "fields_not_in_capture":
        raise FollowupContractError("size-type read is not an unprojected missing GET")
    if (
        catalog.query_params != _NOT_IN_CAPTURE
        or catalog.on_client_allowlist != classified.on_client_read_allowlist
    ):
        raise FollowupContractError("size-type query contract drifted")
    base = read_request_contract(_OPERATION_ID)
    if (
        base.method != "GET"
        or base.path != classified.path
        or base.path_params != ("sizeTypeId",)
        or base.source_title != catalog.source_title
        or base.dispatchable_now
        or base.on_client_read_allowlist != classified.on_client_read_allowlist
        or base.documented_statuses[0] != 200
    ):
        raise FollowupContractError("size-type request contract drifted")
    if classified.title != "사이즈 타입 조회" or catalog.source_title != classified.title:
        raise FollowupContractError("size-type title drifted")
    try:
        return FollowupReadContract(
            operation_id=_OPERATION_ID,
            method="GET",
            path=classified.path,
            path_params=classified.path_params,
            title=classified.title,
            official_effect=_OFFICIAL_EFFECT,
            documented_statuses=base.documented_statuses,
            callable_now=False,
            input_schema=_UNVERIFIED,
            output_schema=_UNVERIFIED,
            query_params=_NOT_IN_CAPTURE,
            on_client_allowlist=classified.on_client_read_allowlist,
            projection="withheld",
            live_call=False,
        )
    except (AdapterInvalidRequestError, ValueError) as exc:
        raise FollowupContractError("size-type contract is not agent-safe") from exc


def validate_size_type_request(*, size_type_id: Any, query: Mapping[str, Any] | None = None) -> str:
    """Bind the documented path token. Query names are not in the capture."""
    if query:
        raise AdapterInvalidRequestError(
            "naver size-type query params are not in the official capture"
        )
    if type(size_type_id) is not int or isinstance(size_type_id, bool):
        raise AdapterInvalidRequestError("invalid naver size-type id")
    if size_type_id <= 0 or size_type_id > _INT64_MAX:
        raise AdapterInvalidRequestError("invalid naver size-type id")
    contract = followup_read_contract()
    return bind_path_params(contract.path, {"sizeTypeId": str(size_type_id)})


class FollowupReadProjection(CanonicalModel):
    """Withheld size-type envelope. Values from the fixture are never copied."""

    operation_id: str
    method: str
    path: str
    bound_path: str
    title: str
    callable_now: bool
    live_call: bool
    field_schema: str
    kind: str
    row_count: int
    field_count: int
    blocked_sensitive_key_count: int
    withheld: bool
    completeness_reason: str
    observed_at: datetime


def _sensitive_key(key: object) -> bool:
    if not isinstance(key, str):
        return False
    folded = key.casefold()
    return any(marker in folded for marker in _SENSITIVE_MARKERS)


def _blocked_key_count(value: Any) -> int:
    if isinstance(value, dict):
        return sum(_sensitive_key(key) + _blocked_key_count(child) for key, child in value.items())
    if isinstance(value, list):
        return sum(_blocked_key_count(child) for child in value)
    return 0


def project_size_type(
    status: int,
    body: Any,
    *,
    bound_path: str,
    clock: Any,
) -> FollowupReadProjection:
    """Count an unverified body. Do not copy fields or mark the read callable."""
    if type(status) is not int:
        raise AdapterInvalidResponseError("naver size-type result shape is invalid")
    contract = followup_read_contract()
    if status != 200:
        if status in contract.documented_statuses:
            raise FollowupReadStatusError(status)
        raise AdapterInvalidResponseError("naver size-type result was not a page")
    if isinstance(body, dict):
        kind, row_count, field_count = "item", 1, len(body)
    elif isinstance(body, list):
        if len(body) > _MAX_ROWS or any(not isinstance(row, dict) for row in body):
            raise AdapterInvalidResponseError("naver size-type result shape is invalid")
        kind, row_count, field_count = "page", len(body), sum(len(row) for row in body)
    else:
        raise AdapterInvalidResponseError("naver size-type result shape is invalid")
    return FollowupReadProjection(
        operation_id=contract.operation_id,
        method=contract.method,
        path=contract.path,
        bound_path=bound_path,
        title=contract.title,
        callable_now=False,
        live_call=False,
        field_schema=_UNVERIFIED,
        kind=kind,
        row_count=row_count,
        field_count=field_count,
        blocked_sensitive_key_count=_blocked_key_count(body),
        withheld=True,
        completeness_reason="response_fields_not_in_official_capture",
        observed_at=clock(),
    )


class NaverFollowupRead:
    """Synthetic projector for the unconnected size-type GET."""

    def __init__(self, transport: Any, *, clock: Any = None) -> None:
        if isinstance(transport, NaverClient) or getattr(transport, "synthetic", False) is not True:
            raise AdapterInvalidRequestError(
                "naver follow-up reads accept a synthetic transport only"
            )
        if not callable(getattr(transport, "exchange", None)):
            raise AdapterInvalidRequestError(
                "naver follow-up reads accept a synthetic transport only"
            )
        self.transport = transport
        self._clock = clock or (lambda: datetime.now(UTC))

    async def preview_size_type(self, *, size_type_id: int) -> FollowupReadProjection:
        bound = validate_size_type_request(size_type_id=size_type_id)
        result = await self.transport.exchange(method="GET", path=bound)
        if not isinstance(result, tuple) or len(result) != 2 or type(result[0]) is not int:
            raise AdapterInvalidResponseError("naver size-type transport shape is invalid")
        projected = project_size_type(result[0], result[1], bound_path=bound, clock=self._clock)
        assert_agent_safe_value(projected)
        return projected
