"""Pure safe-read projection and request-contract helpers for Naver reads.

Everything here is pure or synthetic-only: helpers bound documented path
templates, bound page sizes, and project transport bodies onto caller-named
allowlists. The one facade preview, for the validate-conversion check, runs
against a verified synthetic transport and never claims provider support.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ...clients.naver import NaverClient
from ...models.common import CanonicalModel, ErrorCode
from ...security import assert_agent_safe_value, safe_display_value
from ..base import (
    AdapterFailure,
    AdapterInvalidRequestError,
    AdapterInvalidResponseError,
)
from .naver_full_classification import (
    READ_GET,
    READ_POST,
    bind_path_params,
    classification_index,
)

_MAX_PAGE_SIZE = 100
_MAX_TEXT = 2000
_INT64_MIN = -(2**63)
_INT64_MAX = 2**63 - 1
_NOT_IN_CAPTURE = "not_in_official_capture"
_VALIDATION_CHECK = "validate-product-can-be-grouped-product"

# Keys matching these fragments are never copied into an agent-visible row.
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

# Error envelopes documented across the captured commerce pages. A provider
# body that is only an error object is not a page of rows.
_ERROR_CODES = frozenset(
    {
        "BAD_REQUEST",
        "CHANNEL_NOT_FOUND",
        "DATA_NOT_EXIST",
        "FORBIDDEN",
        "GENERAL_ERROR",
        "INTERNAL_SERVER_ERROR",
        "INTERLOCK_NOT_FOUND",
        "INVALID_CHANNEL_STATUS",
        "INVALID_DATA_STATUS",
        "INVALID_INPUT_DATA",
        "INVALID_INTERLOCK_STATUS",
        "INVALID_MEMBER_STATUS",
        "INVALID_REPRESENT_STATUS",
        "INVALID_STORE_STATUS",
        "MEMBER_NOT_FOUND",
        "NOT_FOUND",
        "PARSING_FAIL",
        "PERMANENT_REDIRECT",
        "PROVISION_NOT_FOUND",
        "REPRESENT_NOT_FOUND",
        "RESOURCE_NOT_AVAILABLE",
        "ROLE_NOT_FOUND",
        "SERDES_FAIL",
        "STORE_NOT_FOUND",
        "UNAUTHORIZED",
        "not_found",
        "server_error",
    }
)

_STATUS_TO_CODE = {
    400: ErrorCode.INVALID_REQUEST,
    401: ErrorCode.AUTHENTICATION_FAILED,
    403: ErrorCode.AUTHENTICATION_FAILED,
    404: ErrorCode.NOT_FOUND,
    429: ErrorCode.RATE_LIMITED,
}

# HTTP status codes printed on each operation page of the 2026-09-16 capture.
# Verified per document, not inferred from the method.
_DOCUMENTED_STATUSES: dict[str, tuple[int, ...]] = {
    "find-commission-details-pay-settle": (200, 400, 500),
    "find-daily-settle-pay-settle": (200, 400, 500),
    "find-daily-vat-declaration-pay-settle": (200, 400, 500),
    "find-settle-by-case-pay-settle": (200, 400, 500),
    "find-vat-declaration-by-case-pay-settle": (200, 400, 500),
    "get-account-info-by-account-no-sellers": (200, 400, 401, 403, 404, 500),
    "get-address-sellers": (200, 400, 401, 403, 404, 500),
    "get-all-origin-area-list-product": (200, 308, 400, 401, 403, 404, 500),
    "get-all-product-info-provided-notice-type-vo-product": (
        200, 308, 400, 401, 403, 404, 500,
    ),
    "get-attribute-list-product": (200, 308, 400, 401, 403, 404, 500),
    "get-attribute-value-list-product": (200, 308, 400, 401, 403, 404, 500),
    "get-attribute-value-unit-list-product": (200, 308, 400, 401, 403, 404, 500),
    "get-brand-list-product": (200, 308, 400, 401, 403, 404, 500),
    "get-category-list-product": (200, 308, 400, 401, 403, 404, 500),
    "get-category-product": (200, 308, 400, 401, 403, 404, 500),
    "get-channels-by-account-no-sellers": (200, 400, 401, 403, 404, 500),
    "get-comment-templates-contents": (200, 400, 401, 403, 404, 500),
    "get-comments-contents": (200, 400, 401, 403, 404, 500),
    "get-customer-inquiry-pay-user": (200, 400, 401, 404, 405, 406, 415, 500),
    "get-delivery-bundle-group-list-product": (200, 308, 400, 401, 403, 404, 500),
    "get-delivery-bundle-group-product": (200, 308, 400, 401, 403, 404, 500),
    "get-fashion-models-product": (200, 308, 400, 401, 403, 404, 500),
    "get-hope-delivery-group-list-product": (200, 308, 400, 401, 403, 404, 500),
    "get-hope-delivery-group-product": (200, 308, 400, 401, 403, 404, 500),
    "get-inspection-products-request-product": (200, 308, 400, 401, 403, 404, 500),
    "get-linked-products-nfa-product": (200, 400, 404, 500),
    "get-logistics-companies-nfa": (200, 400, 404, 500),
    "get-manufacturer-list-product": (200, 308, 400, 401, 403, 404, 500),
    "get-model-list-product": (200, 308, 400, 401, 403, 404, 500),
    "get-model-product": (200, 308, 400, 401, 403, 404, 500),
    "get-ns-detail-1-nfa-product": (200, 400, 404, 500),
    "get-ns-detail-nfa-product": (200, 400, 404, 500),
    "get-ns-information-paged-list-nfa-product": (200, 400, 404, 500),
    "get-option-guides-by-category-id-product": (200, 308, 400, 401, 403, 404, 500),
    "get-origin-area-list-product": (200, 308, 400, 401, 403, 404, 500),
    "get-outbound-locations-nfa": (200, 400, 404, 500),
    "get-page-addresses-sellers": (200, 400, 401, 403, 404, 500),
    "get-post-contents": (200, 400, 401, 403, 404, 500),
    "get-posts-contents": (200, 400, 401, 403, 404, 500),
    "get-product-info-provided-notice-type-vo-product": (
        200, 308, 400, 401, 403, 404, 500,
    ),
    "get-progress-product": (200, 308, 400, 401, 403, 404, 500),
    "get-recommend-tags-product": (200, 308, 400, 401, 403, 404, 500),
    "get-return-delivery-company-list-product": (200, 308, 400, 401, 403, 404, 500),
    "get-size-type-vo-list-product": (200, 308, 400, 401, 403, 404, 500),
    "get-size-type-vo-product": (200, 308, 400, 401, 403, 404, 500),
    "get-standard-option-by-category-product": (200, 308, 400, 401, 403, 404, 500),
    "get-sub-category-product": (200, 308, 400, 401, 403, 404, 500),
    "get-sub-origin-area-list-product": (200, 308, 400, 401, 403, 404, 500),
    "get-subscription-merchant": (200, 400, 401, 402, 403, 404, 406, 409, 500, 503),
    "get-today-dispatch-sellers": (200, 400, 401, 403, 404, 500),
    "get-transactions-merchant": (200, 400, 401, 402, 403, 404, 406, 409, 500, 503),
    "is-restrict-tags-product": (200, 308, 400, 401, 403, 404, 500),
    "read-channel-product-1-product": (200, 308, 400, 401, 403, 404, 500),
    "read-origin-product-product": (200, 308, 400, 401, 403, 404, 500),
    "read-product-product": (200, 308, 400, 401, 403, 404, 500),
    "search-product": (200, 308, 400, 401, 403, 404, 500),
    "seller-get-last-changed-status-pay-order-seller": (200, 400, 500),
    "seller-get-product-order-ids-pay-order-seller": (200, 400, 500),
    "seller-get-product-orders-pay-order-seller": (200, 400, 500),
    "seller-get-product-orders-with-conditions-pay-order-seller": (200, 400, 500),
    "validate-product-can-be-grouped-product": (200, 308, 400, 401, 403, 404, 500),
}


class FullReadStatusError(AdapterFailure):
    """Provider status or error envelope. The body is never part of the message."""

    retryable = False

    def __init__(self, status_code: int, *, code: ErrorCode, operation_id: str) -> None:
        self.status_code = status_code
        self.code = code
        self.operation_id = operation_id
        super().__init__("naver read result was not a page")


class FullReadEvidence(CanonicalModel):
    """Documented operation identity. Never a provider body."""

    operation_id: str
    method: str
    path: str
    effect_class: str
    document_ref: str
    source_title: str
    field_schema: str
    operational_integration: str
    transport_kind: str
    live_call: bool
    observed_at: datetime


class ProjectedRow(CanonicalModel):
    """One provider row after the caller-named allowlist projection."""

    fields: dict[str, str]
    dropped_key_count: int
    dropped_value_count: int
    unknown_field_count: int


class SafeReadPage(CanonicalModel):
    """Bounded read result. Pagination is not in the capture, so no cursor."""

    evidence: FullReadEvidence
    kind: str
    items: tuple[ProjectedRow, ...]
    row_count: int
    next_cursor: None = None
    pagination: str
    completeness_reason: str


class ConversionCheckPreview(CanonicalModel):
    """Withheld projection of the conversion-feasibility check.

    The response schema is absent from the capture, so counts are kept and
    values are never copied.
    """

    evidence: FullReadEvidence
    kind: str
    row_count: int
    field_count: int
    withheld: bool
    next_cursor: None = None
    pagination: str
    completeness_reason: str


class ReadRequestContract(CanonicalModel):
    """Request shape documented for one read operation."""

    operation_id: str
    method: str
    path: str
    path_params: tuple[str, ...]
    documented_statuses: tuple[int, ...]
    max_page_size: int
    cursor_param: str
    request_body_schema: str
    documented_request_bound: str | None
    document_ref: str
    source_title: str
    effect_class: str
    on_client_read_allowlist: bool
    dispatchable_now: bool


def read_request_contract(operation_id: str) -> ReadRequestContract:
    """Contract for one classified read. Mutations and auth are refused."""
    found = classification_index().get(operation_id)
    if found is None or found.effect_class not in {READ_GET, READ_POST}:
        raise AdapterInvalidRequestError("operation is not a documented read")
    statuses = _DOCUMENTED_STATUSES.get(operation_id)
    if statuses is None or statuses[0] != 200:
        raise AdapterInvalidRequestError("documented statuses are not in the contract")
    return ReadRequestContract(
        operation_id=found.operation_id,
        method=found.method,
        path=found.path,
        path_params=found.path_params,
        documented_statuses=statuses,
        max_page_size=_MAX_PAGE_SIZE,
        cursor_param=_NOT_IN_CAPTURE,
        request_body_schema=_NOT_IN_CAPTURE,
        documented_request_bound=found.documented_request_bound,
        document_ref=found.document_ref,
        source_title=found.title,
        effect_class=found.effect_class,
        on_client_read_allowlist=found.on_client_read_allowlist,
        dispatchable_now=False,
    )


def read_request_path(
    contract: ReadRequestContract, values: dict[str, str] | None = None
) -> str:
    """Resolve the contract path with documented params or refuse extras."""
    if not contract.path_params:
        if values:
            raise AdapterInvalidRequestError("read has no documented path params")
        return contract.path
    if values is None:
        raise AdapterInvalidRequestError("read requires its documented path params")
    return bind_path_params(contract.path, values)


def check_read_params(*, page_size: int, cursor: str | None = None) -> int:
    """Bound the page size; cursor params are not in the official capture."""
    if type(page_size) is not int or not 1 <= page_size <= _MAX_PAGE_SIZE:
        raise AdapterInvalidRequestError("invalid naver read page size")
    if cursor is not None:
        raise AdapterInvalidRequestError(
            "naver read cursor param is not in the official capture"
        )
    return page_size


def _sensitive(key: str) -> bool:
    folded = key.casefold()
    return any(marker in folded for marker in _SENSITIVE_MARKERS)


def _scalar(value: Any) -> str | None:
    if value is None or type(value) is bool:
        return None
    if type(value) is int:
        return str(value) if _INT64_MIN <= value <= _INT64_MAX else None
    if isinstance(value, str):
        text = value.strip()
        if not text or len(text) > _MAX_TEXT:
            return None
        return safe_display_value(text)
    return None


def project_row(row: Any, *, allowed_keys: frozenset[str]) -> ProjectedRow:
    """Copy only allowlisted scalar fields. Unknown values stay absent."""
    if not allowed_keys:
        raise AdapterInvalidRequestError("projection requires a non-empty allowlist")
    if not isinstance(row, dict):
        raise AdapterInvalidResponseError("naver read row shape is invalid")
    fields: dict[str, str] = {}
    dropped_values = 0
    unknown = 0
    for key in allowed_keys:
        value = row.get(key)
        if key not in row or value is None:
            unknown += 1
            continue
        if _sensitive(key):
            dropped_values += 1
            continue
        text = _scalar(value)
        if text is None:
            dropped_values += 1
            continue
        fields[key] = text
    return ProjectedRow(
        fields=fields,
        dropped_key_count=sum(1 for key in row if key not in allowed_keys),
        dropped_value_count=dropped_values,
        unknown_field_count=unknown,
    )


def _reject_error_envelope(body: Any, allowed_keys: frozenset[str]) -> None:
    if not isinstance(body, dict):
        return
    code = body.get("code")
    if not isinstance(code, str) or code not in _ERROR_CODES:
        return
    if any(key in body for key in allowed_keys):
        return
    raise FullReadStatusError(
        200, code=ErrorCode.INVALID_ADAPTER_RESPONSE, operation_id="envelope"
    )


def _check_status(contract: ReadRequestContract, status: int) -> None:
    if status == 200:
        return
    code = (
        _STATUS_TO_CODE.get(status, ErrorCode.INVALID_ADAPTER_RESPONSE)
        if status in contract.documented_statuses
        else ErrorCode.INVALID_ADAPTER_RESPONSE
    )
    raise FullReadStatusError(status, code=code, operation_id=contract.operation_id)


def _evidence(
    contract: ReadRequestContract,
    *,
    field_schema: str,
    transport_kind: str,
    clock: Any,
) -> FullReadEvidence:
    return FullReadEvidence(
        operation_id=contract.operation_id,
        method=contract.method,
        path=contract.path,
        effect_class=contract.effect_class,
        document_ref=contract.document_ref,
        source_title=contract.source_title,
        field_schema=field_schema,
        operational_integration="incomplete",
        transport_kind=transport_kind,
        live_call=False,
        observed_at=clock(),
    )


def project_read_result(
    status: int,
    body: Any,
    *,
    contract: ReadRequestContract,
    allowed_keys: frozenset[str],
    max_items: int = _MAX_PAGE_SIZE,
    transport_kind: str = "none",
    clock: Any = None,
) -> SafeReadPage:
    """Project a transport body onto the allowlist with bounded output."""
    if type(status) is not int:
        raise AdapterInvalidResponseError("naver read status shape is invalid")
    clock = clock or (lambda: datetime.now(UTC))
    _check_status(contract, status)
    _reject_error_envelope(body, allowed_keys)
    if isinstance(body, list):
        if len(body) > max_items or len(body) > contract.max_page_size:
            raise AdapterInvalidResponseError("naver read page exceeds the bound")
        items = tuple(project_row(row, allowed_keys=allowed_keys) for row in body)
        kind = "page"
    elif isinstance(body, dict):
        items = (project_row(body, allowed_keys=allowed_keys),)
        kind = "item"
    else:
        raise AdapterInvalidResponseError("naver read result is not a page")
    page = SafeReadPage(
        evidence=_evidence(
            contract,
            field_schema="caller_allowlist",
            transport_kind=transport_kind,
            clock=clock,
        ),
        kind=kind,
        items=items,
        row_count=len(items),
        pagination=_NOT_IN_CAPTURE,
        completeness_reason=(
            "allowlisted_scalars" if items else "empty_page"
        ),
    )
    assert_agent_safe_value(page)
    return page


def project_conversion_check(
    status: int,
    body: Any,
    *,
    transport_kind: str = "none",
    clock: Any = None,
) -> ConversionCheckPreview:
    """Withheld projection: the response schema is absent from the capture."""
    contract = read_request_contract(_VALIDATION_CHECK)
    if type(status) is not int:
        raise AdapterInvalidResponseError("naver read status shape is invalid")
    clock = clock or (lambda: datetime.now(UTC))
    _check_status(contract, status)
    _reject_error_envelope(body, frozenset({"convertible", "canBeGrouped"}))
    if isinstance(body, dict):
        kind, row_count, field_count = "item", 1, len(body)
    elif isinstance(body, list):
        if len(body) > contract.max_page_size or any(
            not isinstance(row, dict) for row in body
        ):
            raise AdapterInvalidResponseError("naver conversion check shape is invalid")
        kind = "page"
        row_count = len(body)
        field_count = sum(len(row) for row in body)
    else:
        raise AdapterInvalidResponseError("naver conversion check shape is invalid")
    preview = ConversionCheckPreview(
        evidence=_evidence(
            contract,
            field_schema=_NOT_IN_CAPTURE,
            transport_kind=transport_kind,
            clock=clock,
        ),
        kind=kind,
        row_count=row_count,
        field_count=field_count,
        withheld=True,
        pagination=_NOT_IN_CAPTURE,
        completeness_reason="response_fields_not_in_official_capture",
    )
    assert_agent_safe_value(preview)
    return preview


def previewed_read_ids() -> frozenset[str]:
    """Reads this module covers synthetically. Not provider support."""
    return frozenset({_VALIDATION_CHECK})


class NaverFullReads:
    """Synthetic-only previews for classified reads absent from other facades.

    A verified synthetic transport is required so this facade can never reach
    a provider, matching the missing-reads guard.
    """

    def __init__(self, transport: Any, *, clock: Any = None) -> None:
        if isinstance(transport, NaverClient) or getattr(
            transport, "synthetic", False
        ) is not True:
            raise AdapterInvalidRequestError(
                "naver full reads accept a synthetic transport only"
            )
        if not callable(getattr(transport, "exchange", None)):
            raise AdapterInvalidRequestError(
                "naver full reads accept a synthetic transport only"
            )
        self.transport = transport
        self._clock = clock or (lambda: datetime.now(UTC))

    async def conversion_check_preview(self) -> ConversionCheckPreview:
        """Synthetic exchange for the documented feasibility check.

        The request body schema is absent from the capture, so no body is sent
        and no real request shape is implied.
        """
        contract = read_request_contract(_VALIDATION_CHECK)
        result = await self.transport.exchange(
            method=contract.method, path=contract.path
        )
        if (
            not isinstance(result, tuple)
            or len(result) != 2
            or type(result[0]) is not int
        ):
            raise AdapterInvalidResponseError("naver read transport shape is invalid")
        return project_conversion_check(
            result[0],
            result[1],
            transport_kind="synthetic",
            clock=self._clock,
        )
