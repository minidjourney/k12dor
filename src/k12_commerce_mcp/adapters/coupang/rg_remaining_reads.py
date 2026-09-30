"""Connection catalog for the official nine Rocket Growth operations.

Six safe reads already send through injected readers in rg_extended,
rg_full_operations, or rg_followup_read. Product detail was projection-only;
this module sends that documented GET and keeps the shared seller_api URI
from being treated as RG proof. Product create and modify stay disabled.
Cancellation is not an official operation and is not assumed. No provider
client lives here, and nothing in this module is a live observation.
"""

from __future__ import annotations

import importlib
import re
from dataclasses import dataclass
from typing import Literal

from ...security import assert_agent_safe_value
from ...simulations.rocket_growth import OFFICIAL_RG_SIMULATIONS
from .rg_extended import (
    OFFICIAL_RG_OPERATIONS,
    SELLER_PRODUCTS,
    RgExtendedReader,
    RgRequestError,
    RgTransport,
)
from .rg_full_operations import (
    RG_FULL_OPERATIONS,
    project_rg_product_detail,
    rg_full_operation,
)

_PACKAGE = "k12_commerce_mcp.adapters.coupang"
_DIGITS = re.compile(r"^[0-9]{1,20}$")
_ALREADY = "already_connected_not_reimplemented_not_live"
_DETAIL_REASON = "synthetic_injected_transport_shared_uri_not_rg_proof_not_live"
_CHANGE_REASON = "disabled_change_approval_missing"


@dataclass(frozen=True)
class _Spec:
    disposition: str
    connection: str
    prior_connection: str | None
    this_module_sends: bool
    remaining_reason: str


def _name(module: str, symbol: str) -> str:
    return f"{_PACKAGE}.{module}.{symbol}"


_SPECS: dict[str, _Spec] = {
    "rg_order_list": _Spec(
        "already_connected",
        _name("rg_full_operations", "RgFullReader.list_orders"),
        None,
        False,
        _ALREADY,
    ),
    "rg_order_detail": _Spec(
        "already_connected",
        _name("rg_extended", "RgExtendedReader.get_order"),
        None,
        False,
        _ALREADY,
    ),
    "rg_inventory_summaries": _Spec(
        "already_connected",
        _name("rg_extended", "RgExtendedReader.get_inventory_summaries"),
        None,
        False,
        _ALREADY,
    ),
    "rg_product_list": _Spec(
        "already_connected",
        _name("rg_followup_read", "read_rg_product_list"),
        None,
        False,
        _ALREADY,
    ),
    "rg_product_create": _Spec(
        "disabled_change",
        _name("rg_remaining_reads", "disabled_rg_change"),
        _name("rg_extended", "RgExtendedReader.simulate_product_create"),
        False,
        _CHANGE_REASON,
    ),
    "rg_product_modify": _Spec(
        "disabled_change",
        _name("rg_remaining_reads", "disabled_rg_change"),
        _name("rg_extended", "RgExtendedReader.simulate_product_modify"),
        False,
        _CHANGE_REASON,
    ),
    "rg_product_detail": _Spec(
        "remaining_read",
        _name("rg_remaining_reads", "read_rg_product_detail"),
        _name("rg_full_operations", "project_rg_product_detail"),
        True,
        _DETAIL_REASON,
    ),
    "rg_category_meta": _Spec(
        "already_connected",
        _name("rg_extended", "RgExtendedReader.get_category_meta"),
        None,
        False,
        _ALREADY,
    ),
    "rg_category_list": _Spec(
        "already_connected",
        _name("rg_extended", "RgExtendedReader.list_categories"),
        None,
        False,
        _ALREADY,
    ),
}


@dataclass(frozen=True)
class RgOperationConnection:
    """Closed link from one official operation to the local callable."""

    operation_id: str
    method: str
    path_template: str
    source_file: str
    effect_class: str
    disposition: str
    connection: str
    prior_connection: str | None
    this_module_sends: bool
    official_rg_uri: bool
    rg_proof: bool
    shared_uri_promoted: bool
    live_verified: bool
    mcp_registered: bool
    cancellation_assumed: bool
    remaining_reason: str


@dataclass(frozen=True)
class RgProductDetailRead:
    """Closed product-detail page. The shared URI is not RG proof."""

    seller_product_id: str
    seller_product_name: str | None
    display_product_name: str | None
    status_name: str | None
    display_category_code: str | None
    items: tuple[dict[str, object], ...]
    operation_id: Literal["rg_product_detail"]
    method: Literal["GET"]
    path: str
    rg_proof: Literal[False]
    shared_uri_not_promoted: Literal[True]


@dataclass(frozen=True)
class RgDisabledChange:
    """Synthetic change contract. Never reaches a transport."""

    operation_id: str
    method: str
    enabled: bool
    approval_missing: bool
    network_calls: int
    execution_enabled: bool
    rg_proof: Literal[False]


@dataclass(frozen=True)
class RgUnconfirmedRefusal:
    """Unproven path. Not an official RG operation and not a cancellation claim."""

    operation_id: None
    reason: Literal["unsupported_unproven"]
    cancellation_assumed: Literal[False]
    enabled: Literal[False]
    network_calls: Literal[0]
    rg_proof: Literal[False]
    execution_enabled: Literal[False]


class _RefuseTransport:
    async def exchange(
        self,
        *,
        method: str,
        path: str,
        query: tuple[tuple[str, str], ...],
    ) -> object:
        del method, path, query
        raise RgRequestError("disabled change has no transport")


def _resolve(dotted: str) -> object:
    parts = dotted.split(".")
    for index in range(len(parts), 0, -1):
        module_name = ".".join(parts[:index])
        try:
            module = importlib.import_module(module_name)
        except ModuleNotFoundError:
            continue
        value: object = module
        for attr in parts[index:]:
            value = getattr(value, attr)
        return value
    raise RgRequestError("unknown rg connection")


def list_rg_connections() -> tuple[RgOperationConnection, ...]:
    """Return the official nine with local connection points. No network."""
    facade = {item.operation_id: item for item in OFFICIAL_RG_OPERATIONS}
    full = {item.operation_id: item for item in RG_FULL_OPERATIONS}
    designs = {item.operation_id: item for item in OFFICIAL_RG_SIMULATIONS}
    if set(facade) != set(full) or set(facade) != set(designs) or set(facade) != set(_SPECS):
        raise RgRequestError("rg catalog mismatch")
    rows: list[RgOperationConnection] = []
    for observed in OFFICIAL_RG_OPERATIONS:
        documented = full[observed.operation_id]
        design = designs[observed.operation_id]
        if (
            observed.method != documented.method
            or observed.path_template != documented.path_template
            or observed.path_template != design.path_template
        ):
            raise RgRequestError("rg catalog mismatch")
        spec = _SPECS[observed.operation_id]
        rows.append(
            RgOperationConnection(
                operation_id=observed.operation_id,
                method=observed.method,
                path_template=observed.path_template,
                source_file=documented.source_file,
                effect_class=documented.effect_class,
                disposition=spec.disposition,
                connection=spec.connection,
                prior_connection=spec.prior_connection,
                this_module_sends=spec.this_module_sends,
                official_rg_uri="/rg_open_api/" in observed.path_template,
                rg_proof=False,
                shared_uri_promoted=False,
                live_verified=False,
                mcp_registered=False,
                cancellation_assumed=False,
                remaining_reason=spec.remaining_reason,
            )
        )
    return tuple(rows)


def connection_for(operation_id: str) -> RgOperationConnection:
    """Return one closed catalog row."""
    for row in list_rg_connections():
        if row.operation_id == operation_id:
            return row
    raise RgRequestError("unknown rg operation")


def resolve_rg_connection(operation_id: str) -> object:
    """Resolve the local callable for an official operation. Does not call it."""
    return _resolve(connection_for(operation_id).connection)


def _vendor_from_body(body: object) -> str:
    if not isinstance(body, dict):
        raise RgRequestError("invalid disabled mutation body")
    vendor = body.get("vendorId")
    if not isinstance(vendor, str):
        raise RgRequestError("invalid disabled mutation body")
    return vendor


def disabled_rg_change(
    operation_id: str,
    body: object,
    transport: RgTransport | None = None,
) -> RgDisabledChange:
    """Validate a change body, then refuse it. The transport is never used."""
    operation = rg_full_operation(operation_id)
    if operation.effect_class != "change":
        raise RgRequestError("not a disabled rg change")
    reader = RgExtendedReader(transport or _RefuseTransport(), _vendor_from_body(body))
    if operation.method == "POST":
        simulated = reader.simulate_product_create(body)
    elif operation.method == "PUT":
        simulated = reader.simulate_product_modify(body)
    else:
        raise RgRequestError("not a disabled rg change")
    return RgDisabledChange(
        operation_id=operation_id,
        method=simulated.method,
        enabled=False,
        approval_missing=True,
        network_calls=0,
        execution_enabled=False,
        rg_proof=False,
    )


def refuse_unconfirmed(
    method: object,
    path: object,
    transport: RgTransport | None = None,
) -> RgUnconfirmedRefusal:
    """Refuse an unproven call. Does not classify it as Rocket Growth."""
    del transport
    if not isinstance(method, str) or not isinstance(path, str) or not path.startswith("/"):
        raise RgRequestError("invalid unconfirmed request")
    return RgUnconfirmedRefusal(
        operation_id=None,
        reason="unsupported_unproven",
        cancellation_assumed=False,
        enabled=False,
        network_calls=0,
        rg_proof=False,
        execution_enabled=False,
    )


async def read_rg_product_detail(
    transport: RgTransport,
    seller_product_id: str,
) -> RgProductDetailRead:
    """GET the documented product detail. Validation fails before any exchange."""
    if not isinstance(seller_product_id, str) or _DIGITS.fullmatch(seller_product_id) is None:
        raise RgRequestError("invalid seller product id")
    path = f"{SELLER_PRODUCTS}/{seller_product_id}"
    payload = await transport.exchange(method="GET", path=path, query=())
    detail = project_rg_product_detail(payload)
    if detail.seller_product_id != seller_product_id:
        raise RgRequestError("invalid product detail shape")
    result = RgProductDetailRead(
        seller_product_id=detail.seller_product_id,
        seller_product_name=detail.seller_product_name,
        display_product_name=detail.display_product_name,
        status_name=detail.status_name,
        display_category_code=detail.display_category_code,
        items=detail.items,
        operation_id="rg_product_detail",
        method="GET",
        path=path,
        rg_proof=False,
        shared_uri_not_promoted=True,
    )
    assert_agent_safe_value(
        {
            "seller_product_id": result.seller_product_id,
            "seller_product_name": result.seller_product_name,
            "display_product_name": result.display_product_name,
            "status_name": result.status_name,
            "display_category_code": result.display_category_code,
            "items": result.items,
            "operation_id": result.operation_id,
            "rg_proof": result.rg_proof,
            "shared_uri_not_promoted": result.shared_uri_not_promoted,
        }
    )
    return result
