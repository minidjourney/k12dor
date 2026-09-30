"""Documentation-based classification of the 116 official Naver operations.

The operation inventory comes from the preserved 2026-09-16 capture via
``simulations.naver.list_disabled_operations``. Effect classes follow what each
document says the call does, not the HTTP method alone: a POST is a read only
where the document describes a lookup or validation, and every mutation keeps
an approval-gated request contract for later CTO-approved synthesis. Nothing in
this module performs a provider call.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping

from ...clients.naver import ALLOWED_CALLS, WRITE_ALLOWED_CALLS
from ...models.common import CanonicalModel
from ...security import safe_display_value
from ...simulations.naver import DisabledOperation, list_disabled_operations
from ..base import AdapterInvalidRequestError
from .missing_reads import missing_read_catalog

READ_GET = "read_get"
READ_POST = "read_post"
MUTATION = "mutation"
AUTH_SECRET = "auth_secret"
EFFECT_CLASSES = frozenset({READ_GET, READ_POST, MUTATION, AUTH_SECRET})

APPROVAL_NONE = "none"
APPROVAL_CEO_PER_ITEM = "ceo_per_item_required"

_PLACEHOLDER = re.compile(r"\{[^}]+\}|:[A-Za-z0-9_]+")
_PATH_TOKEN = re.compile(r"[A-Za-z0-9_-]{1,64}")
_NOT_IN_CAPTURE = "not_in_official_capture"

# Query-shaped POSTs whose captured document text describes a lookup or a
# feasibility check, not a state change. Method name alone never decides this.
_POST_READ_EVIDENCE: dict[str, str] = {
    "search-product": (
        "documented as 상품 목록 조회 (product list query); "
        "POST body carries search filters"
    ),
    "seller-get-product-orders-pay-order-seller": (
        "documented as 상품 주문 상세 내역 조회 (order detail lookup); "
        "document accepts at most 300 product order ids per request"
    ),
    "get-ns-information-paged-list-nfa-product": (
        "documented as 네이버 SKU 목록을 페이지 단위로 조회 "
        "(paged SKU list query)"
    ),
    "validate-product-can-be-grouped-product": (
        "documented as 그룹상품으로 전환할 수 있는지 여부를 확인 "
        "(conversion feasibility check); the conversion itself is the separate "
        "group-products-product operation"
    ),
}
_POST_READ_MAX_IDS: dict[str, str] = {
    "seller-get-product-orders-pay-order-seller": "max_300_product_order_ids",
}
# Credential issuance or resolution. Secret material is never an agent tool.
_AUTH_OPERATIONS = frozenset(
    {"exchange-sellers-auth", "get-seller-info-by-token-merchant"}
)


class ClassificationError(RuntimeError):
    """The captured inventory cannot be classified precisely."""


class OperationClassification(CanonicalModel):
    """One official operation with its documented effect class."""

    operation_id: str
    method: str
    path: str
    effect_class: str
    mutation_kind: str | None
    path_params: tuple[str, ...]
    document_ref: str
    source_url: str
    title: str
    doc_evidence: str
    request_body_schema: str
    documented_request_bound: str | None
    on_client_read_allowlist: bool
    on_client_write_allowlist: bool
    synthetic_facade: str
    approval: str
    execution_enabled: bool
    live_call: bool


class MutationRequestContract(CanonicalModel):
    """Interface for a later CTO-approved mutation synthesis.

    This is a contract only: no provider call is supplied, the request body
    schema stays unclaimed while it is absent from the capture, and every
    mutation requires a per-item CEO approval before any live execution.
    """

    operation_id: str
    method: str
    path: str
    path_params: tuple[str, ...]
    mutation_kind: str
    destructive: bool
    document_ref: str
    source_url: str
    title: str
    request_body_schema: str
    response_schema: str
    dedupe_strategy: str
    approval_gate: str
    execution_enabled: bool
    provider_call_supplied: bool


def operation_path_params(path: str) -> tuple[str, ...]:
    """Documented path template parameter names, in path order."""
    names: list[str] = []
    for match in _PLACEHOLDER.finditer(path):
        token = match.group(0)
        names.append(token[1:-1] if token.startswith("{") else token[1:])
    return tuple(names)


def normalize_operation_path(path: str) -> str:
    """Compare `{id}` and `:id` templates without treating them as values."""
    return _PLACEHOLDER.sub("{}", path)


def bind_path_params(path: str, values: Mapping[str, str]) -> str:
    """Fill a documented path template with validated path tokens only."""
    names = operation_path_params(path)
    if sorted(values) != sorted(names):
        raise AdapterInvalidRequestError(
            "naver path parameters do not match the documented template"
        )

    def _sub(match: re.Match[str]) -> str:
        token = match.group(0)
        name = token[1:-1] if token.startswith("{") else token[1:]
        value = values[name]
        if not isinstance(value, str) or _PATH_TOKEN.fullmatch(value) is None:
            raise AdapterInvalidRequestError("invalid naver path parameter")
        if safe_display_value(value) is None:
            raise AdapterInvalidRequestError("invalid naver path parameter")
        return value

    bound = _PLACEHOLDER.sub(_sub, path)
    if _PLACEHOLDER.search(bound) or not bound.startswith("/"):
        raise AdapterInvalidRequestError("naver path template was not fully bound")
    return bound


def _mutation_kind(path: str) -> str:
    if path.startswith("/v1/pay-order/seller/"):
        return "order_state_transition"
    if path.startswith("/v1/commerce-solutions/subscriptions"):
        return "subscription_admin"
    if path == "/v1/commerce-solutions/external-transactions":
        return "payment_report_write"
    if path.startswith("/v1/contents/") or path.startswith("/v1/pay-merchant/inquiries"):
        return "content_write"
    if path.startswith("/v1/product-delivery-info/"):
        return "delivery_config_write"
    if path.startswith("/v1/product-fashion-models"):
        return "fashion_model_write"
    if path.startswith("/v1/product-inspections/"):
        return "inspection_restore"
    if path == "/v1/seller/this-day-dispatch":
        return "seller_config_write"
    if path.startswith(
        (
            "/v1/products",
            "/v2/products",
            "/v2/standard-group-products",
            "/v1/product-images",
        )
    ):
        return "product_write"
    return "unclassified_mutation"


def _facade_projection_map() -> dict[tuple[str, str], str]:
    by_path = {
        (item.method, normalize_operation_path(item.path)): item.projection
        for item in missing_read_catalog()
    }
    collapsed: dict[tuple[str, str], str] = {}
    for key, projection in by_path.items():
        if projection in {"pii_withheld", "fields_not_in_capture", "withheld_raw_content"}:
            collapsed[key] = "withheld"
        else:
            collapsed[key] = projection
    return collapsed


def _classify(
    item: DisabledOperation,
    *,
    allowed: frozenset[tuple[str, str]],
    write_allowed: frozenset[tuple[str, str]],
    facade: Mapping[tuple[str, str], str],
) -> OperationClassification:
    operation_id = item.operation_id
    if operation_id in _AUTH_OPERATIONS:
        effect_class = AUTH_SECRET
        evidence = "credential issuance or JWE resolution; secret material"
    elif item.disabled_reason == "mutation":
        effect_class = MUTATION
        evidence = f"documented state change: {item.title}"
    elif item.method == "GET":
        effect_class = READ_GET
        evidence = f"documented GET query: {item.title}"
    elif item.method == "POST" and operation_id in _POST_READ_EVIDENCE:
        effect_class = READ_POST
        evidence = _POST_READ_EVIDENCE[operation_id]
    else:
        raise ClassificationError(
            f"operation {operation_id} has no documented effect class"
        )
    mutation_kind = _mutation_kind(item.path) if effect_class == MUTATION else None
    if mutation_kind == "unclassified_mutation":
        raise ClassificationError(f"mutation {operation_id} has no kind")
    if item.execution_enabled or item.live_call:
        raise ClassificationError(f"operation {operation_id} is not disabled")
    key = (item.method, normalize_operation_path(item.path))
    return OperationClassification(
        operation_id=operation_id,
        method=item.method,
        path=item.path,
        effect_class=effect_class,
        mutation_kind=mutation_kind,
        path_params=operation_path_params(item.path),
        document_ref=item.document_ref,
        source_url=item.source_url,
        title=item.title,
        doc_evidence=evidence,
        request_body_schema=_NOT_IN_CAPTURE,
        documented_request_bound=_POST_READ_MAX_IDS.get(operation_id),
        on_client_read_allowlist=key in allowed,
        on_client_write_allowlist=key in write_allowed,
        synthetic_facade=facade.get(key, "none"),
        approval=APPROVAL_NONE if effect_class != MUTATION else APPROVAL_CEO_PER_ITEM,
        execution_enabled=False,
        live_call=False,
    )


def classify_operations() -> tuple[OperationClassification, ...]:
    """Classify every official operation from the preserved capture."""
    allowed = frozenset(
        (method, normalize_operation_path(path)) for method, path in ALLOWED_CALLS
    )
    write_allowed = frozenset(
        (method, normalize_operation_path(path)) for method, path in WRITE_ALLOWED_CALLS
    )
    facade = _facade_projection_map()
    classified = tuple(
        _classify(
            item, allowed=allowed, write_allowed=write_allowed, facade=facade
        )
        for item in list_disabled_operations()
    )
    if len(classified) != 116:
        raise ClassificationError("official operation count is not 116")
    ids = [item.operation_id for item in classified]
    if len(set(ids)) != 116:
        raise ClassificationError("duplicate official operation id")
    keys = {(item.method, normalize_operation_path(item.path)) for item in classified}
    if len(keys) != 116:
        raise ClassificationError("official method/path is not unique")
    if not {item.effect_class for item in classified} <= EFFECT_CLASSES:
        raise ClassificationError("unknown effect class")
    read_posts = {
        item.operation_id for item in classified if item.effect_class == READ_POST
    }
    if read_posts != set(_POST_READ_EVIDENCE):
        raise ClassificationError("documented read POST set drifted")
    auths = {item.operation_id for item in classified if item.effect_class == AUTH_SECRET}
    if auths != _AUTH_OPERATIONS:
        raise ClassificationError("auth operation set drifted")
    if any(item.execution_enabled or item.live_call for item in classified):
        raise ClassificationError("classification must never enable execution")
    return classified


def classification_index() -> dict[str, OperationClassification]:
    return {item.operation_id: item for item in classify_operations()}


def read_operations() -> tuple[OperationClassification, ...]:
    return tuple(
        item
        for item in classify_operations()
        if item.effect_class in {READ_GET, READ_POST}
    )


def mutation_operations() -> tuple[OperationClassification, ...]:
    return tuple(item for item in classify_operations() if item.effect_class == MUTATION)


def mutation_request_contracts() -> tuple[MutationRequestContract, ...]:
    """Per-mutation interfaces for later CTO-approved synthesis."""
    return tuple(
        MutationRequestContract(
            operation_id=item.operation_id,
            method=item.method,
            path=item.path,
            path_params=item.path_params,
            mutation_kind=item.mutation_kind or "unclassified_mutation",
            destructive=item.method == "DELETE",
            document_ref=item.document_ref,
            source_url=item.source_url,
            title=item.title,
            request_body_schema=_NOT_IN_CAPTURE,
            response_schema=_NOT_IN_CAPTURE,
            dedupe_strategy=_NOT_IN_CAPTURE,
            approval_gate=APPROVAL_CEO_PER_ITEM,
            execution_enabled=False,
            provider_call_supplied=False,
        )
        for item in mutation_operations()
    )


def mutation_request_contract(operation_id: str) -> MutationRequestContract:
    for contract in mutation_request_contracts():
        if contract.operation_id == operation_id:
            return contract
    raise AdapterInvalidRequestError("operation is not a documented mutation")


def classification_summary() -> dict[str, object]:
    """Aggregate counts for review. No provider call, no payload data."""
    classified = classify_operations()
    return {
        "operation_count": len(classified),
        "by_effect_class": dict(
            sorted(Counter(item.effect_class for item in classified).items())
        ),
        "by_mutation_kind": dict(
            sorted(
                Counter(
                    item.mutation_kind
                    for item in classified
                    if item.mutation_kind is not None
                ).items()
            )
        ),
        "mutations_on_client_write_allowlist": sum(
            1 for item in classified if item.on_client_write_allowlist
        ),
        "operations_on_client_read_allowlist": sum(
            1 for item in classified if item.on_client_read_allowlist
        ),
        "reads_with_synthetic_facade": sum(
            1 for item in classified if item.synthetic_facade != "none"
        ),
        "execution_enabled_total": sum(
            1 for item in classified if item.execution_enabled
        ),
        "live_call_total": sum(1 for item in classified if item.live_call),
    }
