"""Inactive safety-contract simulations for the official Rocket Growth nine.

Identities are closed snapshot values. This module does not read the snapshot,
call a provider, or mark any operation live or verified.
"""

from __future__ import annotations

import inspect
import re
from dataclasses import dataclass

_SOURCE = "raw/documents/marketplace-api-docs-20260916/rocket-growth"
_SELLER_PRODUCTS = "/v2/providers/seller_api/apis/api/v1/marketplace/seller-products"
_RG_VENDOR = "/v2/providers/rg_open_api/apis/api/v1/vendors/{vendorId}"
CANCELLATION_STATUS = "unsupported_unproven"

_ACTION_VERBS = (
    "변경",
    "취소",
    "승인",
    "삭제",
    "수정",
    "생성",
    "등록",
    "발송",
    "처리",
    "환불",
    "change",
    "cancel",
    "delete",
    "update",
    "create",
    "modify",
    "approve",
    "register",
    "send",
    "upload",
    "confirm",
)
_READ_VERBS = ("조회", "검색", "목록", "query", "search", "list", "find")
_GENERAL_CLAIM_TITLES = frozenset(
    {
        "반품 / 취소 요청 목록 조회",
        "주문 상품 취소 처리",
        "Return / Cancellation Request List Query",
        "Cancel an order",
    }
)
_GENERAL_CLAIM_MARKERS = (
    "returnRequests",
    "exchangeRequests",
    "returnWithdrawRequests",
    "ordersheets",
    "cancel",
)


@dataclass(frozen=True)
class RgSimulationDesign:
    """One official RG operation. Execution stays inactive."""

    number: int
    operation_id: str
    method: str
    path_template: str
    source_file: str
    official_title: str
    effect_class: str
    query_names: tuple[str, ...] = ()
    required_query: tuple[tuple[str, str], ...] = ()
    forbidden_query_names: tuple[str, ...] = ()
    non_rg_query_values: tuple[tuple[str, str], ...] = ()
    locale_values: tuple[str, ...] = ()
    live_call: bool = False
    verification_complete: bool = False

    @property
    def source_doc(self) -> str:
        return f"{_SOURCE}/{self.source_file}"


@dataclass(frozen=True)
class PathVerdict:
    """Path identity only. Never an approval to call."""

    is_rg_operation: bool
    operation_id: str | None
    reason: str
    execution_enabled: bool = False
    live_call: bool = False


def effect_class_for(method: str, official_title: str) -> str:
    """Map a closed title to query, change, or effect_unknown. Not a live check."""
    folded = official_title.casefold()
    is_action = any(token.casefold() in folded for token in _ACTION_VERBS)
    is_read = any(token.casefold() in folded for token in _READ_VERBS)
    if method in {"PUT", "PATCH", "DELETE"}:
        return "change"
    if method == "POST":
        if is_read and not is_action:
            return "query"
        if is_action:
            return "change"
        return "effect_unknown"
    if is_action or not is_read:
        return "effect_unknown"
    return "query"


def _design(
    number: int,
    operation_id: str,
    method: str,
    path_template: str,
    source_file: str,
    official_title: str,
    *,
    query_names: tuple[str, ...] = (),
    required_query: tuple[tuple[str, str], ...] = (),
    forbidden_query_names: tuple[str, ...] = (),
    non_rg_query_values: tuple[tuple[str, str], ...] = (),
    locale_values: tuple[str, ...] = (),
) -> RgSimulationDesign:
    return RgSimulationDesign(
        number=number,
        operation_id=operation_id,
        method=method,
        path_template=path_template,
        source_file=source_file,
        official_title=official_title,
        effect_class=effect_class_for(method, official_title),
        query_names=query_names,
        required_query=required_query,
        forbidden_query_names=forbidden_query_names,
        non_rg_query_values=non_rg_query_values,
        locale_values=locale_values,
    )


OFFICIAL_RG_SIMULATIONS: tuple[RgSimulationDesign, ...] = (
    _design(
        1,
        "rg_order_list",
        "GET",
        f"{_RG_VENDOR}/rg/orders",
        "ko_api_rocket-growth_rg-order-apilist-query.html",
        "로켓그로스 주문 API(목록 쿼리)",
        query_names=("paidDateFrom", "paidDateTo", "nextToken"),
    ),
    _design(
        2,
        "rg_order_detail",
        "GET",
        f"{_RG_VENDOR}/rg/order/{{orderId}}",
        "ko_api_rocket-growth_api.html",
        "로켓그로스 주문API",
    ),
    _design(
        3,
        "rg_inventory_summaries",
        "GET",
        f"{_RG_VENDOR}/rg/inventory/summaries",
        "ko_api_rocket-growth_rg-inventory-api.html",
        "로켓창고 재고 API",
        query_names=("vendorItemId", "nextToken"),
        forbidden_query_names=("vendorIdItemId",),
    ),
    _design(
        4,
        "rg_product_list",
        "GET",
        _SELLER_PRODUCTS,
        (
            "ko_api_rocket-growth_product-list-paging-query-rocket-growth-"
            "rocket-growthmarketplace-hybrid-products.html"
        ),
        "상품 목록 페이징 조회 (로켓그로스 및 로켓그로스/마켓플레이스 동시 운영 상품)",
        query_names=(
            "vendorId",
            "nextToken",
            "maxPerPage",
            "sellerProductId",
            "sellerProductName",
            "status",
            "manufacture",
            "createdAt",
            "businessTypes",
        ),
        required_query=(("businessTypes", "rocketGrowth"),),
    ),
    _design(
        5,
        "rg_product_create",
        "POST",
        _SELLER_PRODUCTS,
        (
            "ko_api_rocket-growth_product-creation-rocket-growth-"
            "rocket-growthmarketplace-hybrid-products.html"
        ),
        "상품 생성 (로켓그로스 및 마켓플레이스/로켓그로스 동시 운영 상품)",
    ),
    _design(
        6,
        "rg_product_modify",
        "PUT",
        _SELLER_PRODUCTS,
        (
            "ko_api_rocket-growth_modify-product-rocket-growth-"
            "rocket-growthmarketplace-hybrid-products.html"
        ),
        "상품 수정 (로켓그로스 또는 마켓플레이스/로켓그로스 동시 운영 상품)",
    ),
    _design(
        7,
        "rg_product_detail",
        "GET",
        f"{_SELLER_PRODUCTS}/{{sellerProductId}}",
        (
            "ko_api_rocket-growth_query-product-rocket-growth-or-"
            "rocket-growthmarketplace-hybrid-products.html"
        ),
        "상품 조회 (로켓그로스 또는 마켓플레이스/로켓그로스 동시 운영 상품)",
    ),
    _design(
        8,
        "rg_category_meta",
        "GET",
        "/v2/providers/seller_api/apis/api/v1/marketplace/meta"
        "/category-related-metas/display-category-codes/{displayCategoryCode}",
        "ko_api_rocket-growth_category-metadata-query-39429124103449.html",
        "카테고리 메타 정보 조회",
    ),
    _design(
        9,
        "rg_category_list",
        "GET",
        "/v2/providers/seller_api/apis/api/v1/marketplace/meta/display-categories",
        "ko_api_rocket-growth_how-to-get-category-list-for-rocket-growth-products.html",
        "카테고리 목록 조회 (로켓그로스 운영 카테고리)",
        query_names=("registrationType", "locale"),
        required_query=(("registrationType", "RFM"),),
        non_rg_query_values=(("registrationType", "CGF"),),
        locale_values=("en", "zh-CN", "kr"),
    ),
)


def classify_claim_title(title: str) -> str:
    """General claim titles are never RG operation ids."""
    if title in _GENERAL_CLAIM_TITLES:
        return "general_claim_not_rg"
    return "not_an_rg_operation"


def _path_matches(template: str, path: str) -> bool:
    template_parts = template.split("/")
    path_parts = path.split("/")
    if len(template_parts) != len(path_parts):
        return False
    for expected, actual in zip(template_parts, path_parts, strict=True):
        placeholder = expected.startswith("{") and expected.endswith("}")
        if placeholder:
            if not actual or actual in {".", ".."}:
                return False
            continue
        if expected != actual:
            return False
    return True


def classify_provider_path(method: str, path: str) -> PathVerdict:
    """Identify a path without enabling a call. General claims are not RG."""
    if not isinstance(method, str) or not isinstance(path, str):
        return PathVerdict(False, None, "not_official_rg_operation")
    folded = path.casefold()
    if any(marker.casefold() in folded for marker in _GENERAL_CLAIM_MARKERS):
        return PathVerdict(False, None, "general_claim_not_rg")
    for operation in OFFICIAL_RG_SIMULATIONS:
        if operation.method != method or not _path_matches(operation.path_template, path):
            continue
        if "/rg_open_api/" not in operation.path_template:
            return PathVerdict(False, operation.operation_id, "shared_uri_not_rg_proof")
        return PathVerdict(True, operation.operation_id, "official_rg_uri_not_called")
    return PathVerdict(False, None, "not_official_rg_operation")


class InactiveSimulationError(RuntimeError):
    """Raised when an inactive simulation is asked to touch a provider."""


@dataclass(frozen=True)
class InactiveSimulationResult:
    """Closed inactive result. Not a live observation."""

    number: int
    operation_id: str
    method: str
    path_template: str
    source_file: str
    effect_class: str
    status: str = "disabled_simulation"
    execution_enabled: bool = False
    network_calls: int = 0
    approval: str = "none"
    live_call: bool = False
    verification_complete: bool = False
    knowledge_status: str = "snapshot_not_confirmed"
    external_read: bool = False
    external_write: bool = False
    treated_as_proven_query: bool = False
    mcp_registered: bool = False


class RocketGrowthInactiveSimulation:
    """Runs the official nine as inactive mocks. The transport is never used."""

    def __init__(self, transport: object | None = None) -> None:
        self._transport = transport

    def run(self, number: int) -> InactiveSimulationResult:
        design = next(
            (item for item in OFFICIAL_RG_SIMULATIONS if item.number == number),
            None,
        )
        if design is None:
            raise InactiveSimulationError("unknown rocket growth simulation")
        return InactiveSimulationResult(
            number=design.number,
            operation_id=design.operation_id,
            method=design.method,
            path_template=design.path_template,
            source_file=design.source_file,
            effect_class=design.effect_class,
        )

    def run_all(self) -> tuple[InactiveSimulationResult, ...]:
        return tuple(self.run(item.number) for item in OFFICIAL_RG_SIMULATIONS)

    def refuse_external(self, method: str, path: str) -> None:
        del method, path
        raise InactiveSimulationError("external rocket growth call is disabled")


@dataclass(frozen=True)
class CoverageGap:
    """Static comparison. Not a live call and not a verification result."""

    number: int
    operation_id: str
    effect_class: str
    client_status: str
    missing_client_parameters: tuple[str, ...]
    rg_extended_execution: str
    inactive_in_rg_extended: bool
    effect_unknown_transport_reader: bool
    facade_missing_query_names: tuple[str, ...]
    simulation_status: str = "disabled_simulation"
    live_call: bool = False
    verification_complete: bool = False
    external_read: bool = False
    external_write: bool = False
    cancellation_status: str = CANCELLATION_STATUS


_CLIENT_METHODS = {
    "rg_order_list": "list_rg_orders",
    "rg_inventory_summaries": "list_rg_inventory",
    "rg_product_list": "list_seller_products",
    "rg_product_create": "create_seller_product",
    "rg_product_detail": "get_seller_product",
    "rg_category_meta": "get_display_category_related_metas",
    "rg_category_list": "list_display_categories",
}
_CLIENT_PARAM_GAPS = {
    "rg_inventory_summaries": (("vendor_item_id", "vendorItemId"),),
    "rg_category_list": (("registration_type", "registrationType"),),
}
_PLACEHOLDERS = {
    "vendor_id": "vendorId",
    "seller_product_id": "sellerProductId",
    "display_category_code": "displayCategoryCode",
    "order_id": "orderId",
}


def _normalize_path(path: str) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        return "{" + _PLACEHOLDERS.get(name, name) + "}"

    return re.sub(r"\{([^}]+)\}", replace, path)


def _client_status(
    design: RgSimulationDesign,
    client: type,
    get_paths: set[str],
    post_paths: set[str],
) -> tuple[str, tuple[str, ...]]:
    method_name = _CLIENT_METHODS.get(design.operation_id)
    method = getattr(client, method_name, None) if method_name else None
    parameters = set(inspect.signature(method).parameters) if method is not None else set()
    missing = tuple(
        official
        for snake, official in _CLIENT_PARAM_GAPS.get(design.operation_id, ())
        if snake not in parameters
    )
    normalized = _normalize_path(design.path_template)
    shared = "/rg_open_api/" not in design.path_template
    if design.method == "PUT":
        return "mutation_absent", ()
    if design.method == "POST" and shared and method is not None and normalized in post_paths:
        return "shared_post_present_not_rg_approval", ()
    if design.method == "GET" and method is not None and normalized in get_paths:
        if shared and missing:
            return "shared_allowlisted_get_query_incomplete", missing
        if shared:
            return "shared_allowlisted_get_not_rg_proof", ()
        if missing:
            return "allowlisted_get_query_incomplete", missing
        return "allowlisted_get_not_called", ()
    return "absent", ()


def compare_current_coverage() -> tuple[CoverageGap, ...]:
    """Inspect local client and facade symbols. Does not construct or call them."""
    from k12_commerce_mcp.adapters.coupang.rg_extended import OFFICIAL_RG_OPERATIONS
    from k12_commerce_mcp.clients.coupang import (
        ALLOWED_GET_PATH_TEMPLATES,
        ALLOWED_POST_PATH_TEMPLATES,
        CoupangClient,
    )

    facade = {item.operation_id: item for item in OFFICIAL_RG_OPERATIONS}
    get_paths = {_normalize_path(path) for path in ALLOWED_GET_PATH_TEMPLATES}
    post_paths = {_normalize_path(path) for path in ALLOWED_POST_PATH_TEMPLATES}
    gaps: list[CoverageGap] = []
    for design in OFFICIAL_RG_SIMULATIONS:
        observed = facade[design.operation_id]
        status, missing = _client_status(design, CoupangClient, get_paths, post_paths)
        facade_missing = tuple(
            name for name in design.query_names if name not in observed.query_names
        )
        gaps.append(
            CoverageGap(
                number=design.number,
                operation_id=design.operation_id,
                effect_class=design.effect_class,
                client_status=status,
                missing_client_parameters=missing,
                rg_extended_execution=observed.local_execution,
                inactive_in_rg_extended=observed.local_execution == "disabled_simulation",
                effect_unknown_transport_reader=(
                    design.effect_class == "effect_unknown"
                    and observed.local_execution == "local_read"
                ),
                facade_missing_query_names=facade_missing,
            )
        )
    return tuple(gaps)
