"""Unconnected Naver read GETs, classified against the official contract.

The 116-operation ledger joins the official contract, the connection audit,
classification, the missing-read catalog, and the reference MCP. Change
operations stay disabled simulations. GETs whose effect is unknown and query
POSTs whose effect is unconfirmed are blocked. Schemas absent from the static
capture are not reported as supported. This module does not call a provider.
"""

from __future__ import annotations

import importlib.util
import inspect
import re
from collections import Counter
from collections.abc import Mapping
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from ...clients.naver import NaverClient
from ...models.common import CanonicalModel, ErrorCode
from ...naver_reference_mcp import _PATHS as _REFERENCE_MCP_PATHS
from ...security import assert_agent_safe_value
from ...simulations.naver import SimulationResult, simulate
from ..base import AdapterFailure, AdapterInvalidRequestError, AdapterInvalidResponseError
from .missing_reads import missing_read_catalog, normalize_operation_path
from .naver_followup_read import followup_read_contract
from .naver_full_classification import bind_path_params, classification_index
from .naver_full_reads import read_request_contract
from .naver_reference_full_reads import reference_read_ids

_ROOT = Path(__file__).resolve().parents[4]
_CONTRACT = _ROOT / "docs" / "naver-official-read-contract-20260929.md"
_AUDIT = _ROOT / "scripts" / "audit_naver_api_connections.py"
_UNVERIFIED = "unverified"
_NOT_IN_CAPTURE = "not_in_official_capture"
_EFFECT_RE = re.compile(
    r"auth: (\d+), get_effect_unknown: (\d+), mutation: (\d+), "
    r"post_effect_unknown: (\d+), read: (\d+), read_post: (\d+)"
)
_STATUS_RE = re.compile(r"\b(\d{3})\b")
_COMPATIBLE = {
    "read": "read_get",
    "read_post": "read_post",
    "mutation": "mutation",
    "auth": "auth_secret",
}
_OMISSION = {
    "blocked_get_effect_unknown": "get_effect_unknown",
    "blocked_post_effect_unconfirmed": "post_effect_unconfirmed",
    "disabled_simulation": "disabled_simulation_mutation",
    "blocked_auth": "auth_secret",
    "omitted_read_post_body_unverified": "read_post_body_unverified",
    "already_followup": "already_followup_read",
    "already_mcp_dispatched": "already_mcp_dispatched",
    "client_allowlisted_not_dispatched": "client_allowlisted_not_dispatched",
}
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
_STATUS_TO_CODE = {
    400: ErrorCode.INVALID_REQUEST,
    401: ErrorCode.AUTHENTICATION_FAILED,
    403: ErrorCode.AUTHENTICATION_FAILED,
    404: ErrorCode.NOT_FOUND,
}


class RemainingContractError(RuntimeError):
    """Existing sources do not agree on the remaining-read ledger."""


class RemainingReadBlocked(AdapterFailure):
    """Effect is unknown, unconfirmed, or not a remaining read GET."""

    retryable = False
    code = ErrorCode.ADAPTER_NOT_CONFIGURED

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__("naver remaining read is blocked")


class RemainingReadStatusError(AdapterFailure):
    """Documented non-success status. The body is never part of the message."""

    retryable = False

    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        self.code = _STATUS_TO_CODE.get(status_code, ErrorCode.INVALID_ADAPTER_RESPONSE)
        super().__init__("naver remaining read result was not a page")


class RemainingLedgerRow(CanonicalModel):
    """One official operation and why it is or is not a remaining read."""

    operation_id: str
    method: str
    path: str
    title: str
    official_effect: str
    classification_effect: str
    effects_compatible: bool
    client_allowlist: bool
    mcp_dispatch: bool
    synthetic_facade: bool
    existing_facade: str
    reference_mcp: bool
    path_params: tuple[str, ...]
    documented_statuses: tuple[int, ...]
    disposition: str
    omission_reason: str | None
    callable_now: bool
    supported: bool
    execution_enabled: bool
    live_call: bool
    field_schema: str
    input_schema: str
    query_params: str
    simulation_status: str


class RemainingReadProjection(CanonicalModel):
    """Withheld envelope. Fixture values are never copied."""

    operation_id: str
    method: str
    path: str
    bound_path: str
    title: str
    callable_now: bool
    supported: bool
    live_call: bool
    field_schema: str
    kind: str
    row_count: int
    field_count: int
    blocked_sensitive_key_count: int
    withheld: bool
    completeness_reason: str
    observed_at: datetime


def _official_contract() -> dict[str, dict[str, object]]:
    if not _CONTRACT.is_file():
        raise RemainingContractError("official naver read contract is missing")
    text = _CONTRACT.read_text(encoding="utf-8")
    aggregate = _EFFECT_RE.search(text)
    if aggregate is None or "| callable_now | 0 |" not in text:
        raise RemainingContractError("official contract aggregate is missing")
    expected = {
        "auth": int(aggregate.group(1)),
        "get_effect_unknown": int(aggregate.group(2)),
        "mutation": int(aggregate.group(3)),
        "post_effect_unknown": int(aggregate.group(4)),
        "read": int(aggregate.group(5)),
        "read_post": int(aggregate.group(6)),
    }
    rows: dict[str, dict[str, object]] = {}
    for line in text.splitlines():
        if not line.startswith("| ") or line.startswith("| #") or line.startswith("| ---"):
            continue
        parts = [part.strip() for part in line.strip().strip("|").split("|")]
        if not parts or not parts[0].isdigit() or len(parts) < 8:
            continue
        statuses = tuple(int(value) for value in _STATUS_RE.findall(parts[6]))
        if not statuses or len(statuses) != len(set(statuses)):
            raise RemainingContractError(f"statuses drifted for {parts[1]}")
        if parts[5] in {"read", "read_post"} and statuses[0] != 200:
            raise RemainingContractError(f"read statuses drifted for {parts[1]}")
        rows[parts[1]] = {
            "method": parts[2],
            "path": parts[3],
            "title": parts[4],
            "effect": parts[5],
            "statuses": statuses,
        }
    counted = Counter(str(item["effect"]) for item in rows.values())
    if len(rows) != 116 or dict(counted) != expected:
        raise RemainingContractError("official contract table does not match its aggregate")
    return rows


def _audit_report() -> dict[str, object]:
    if not _AUDIT.is_file():
        raise RemainingContractError("naver connection audit is missing")
    spec = importlib.util.spec_from_file_location("_naver_remaining_audit", _AUDIT)
    if spec is None or spec.loader is None:
        raise RemainingContractError("naver connection audit cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    report = module.build_audit()
    if report.get("official_operation_count") != 116:
        raise RemainingContractError("official operation count is not 116")
    return report


def _reference_ids() -> frozenset[str]:
    paths = {
        normalize_operation_path(path)
        for path, _parameter, _container in _REFERENCE_MCP_PATHS.values()
    }
    joined = {
        item.operation_id
        for item in classification_index().values()
        if item.method == "GET" and normalize_operation_path(item.path) in paths
    }
    if joined != reference_read_ids() or len(joined) != 8:
        raise RemainingContractError("reference MCP paths drifted")
    return joined


def _disposition(
    effect: str,
    *,
    operation_id: str,
    followup_id: str,
    allowlisted: bool,
    dispatched: bool,
) -> str:
    if effect == "get_effect_unknown":
        return "blocked_get_effect_unknown"
    if effect == "post_effect_unknown":
        return "blocked_post_effect_unconfirmed"
    if effect == "mutation":
        return "disabled_simulation"
    if effect == "auth":
        return "blocked_auth"
    if effect == "read_post":
        return "omitted_read_post_body_unverified"
    if effect != "read":
        raise RemainingContractError(f"unknown official effect for {operation_id}")
    if operation_id == followup_id:
        return "already_followup"
    if dispatched:
        return "already_mcp_dispatched"
    if allowlisted:
        return "client_allowlisted_not_dispatched"
    return "implemented_withheld"


def _statuses_agree(operation_id: str, parsed: tuple[int, ...]) -> None:
    try:
        contract = read_request_contract(operation_id)
    except AdapterInvalidRequestError:
        return
    if contract.documented_statuses != parsed:
        raise RemainingContractError(f"documented statuses drifted for {operation_id}")


@lru_cache(maxsize=1)
def remaining_ledger() -> tuple[RemainingLedgerRow, ...]:
    """Classify all 116 official operations. Does not call Naver."""
    official = _official_contract()
    audit = _audit_report()
    audit_rows = {str(item["operation_id"]): item for item in audit["rows"]}  # type: ignore[index]
    classified = classification_index()
    followup_id = followup_read_contract().operation_id
    references = _reference_ids()
    missing = {
        (item.method, normalize_operation_path(item.path)): item for item in missing_read_catalog()
    }
    if set(official) != set(classified) or set(official) != set(audit_rows):
        raise RemainingContractError("official operation ids drifted")
    rows: list[RemainingLedgerRow] = []
    for operation_id, source in official.items():
        found = classified[operation_id]
        audit_row = audit_rows[operation_id]
        method = str(source["method"])
        path = str(source["path"])
        effect = str(source["effect"])
        if (
            found.method != method
            or found.path != path
            or found.title != source["title"]
            or audit_row["method"] != method
            or audit_row["path"] != path
        ):
            raise RemainingContractError(f"identity drifted for {operation_id}")
        statuses = source["statuses"]
        if not isinstance(statuses, tuple):
            raise RemainingContractError(f"statuses drifted for {operation_id}")
        _statuses_agree(operation_id, statuses)
        allowlisted = audit_row["client_allowlist"] == "yes"
        dispatched = audit_row["mcp_tool_actual_dispatch"] == "yes"
        disposition = _disposition(
            effect,
            operation_id=operation_id,
            followup_id=followup_id,
            allowlisted=allowlisted,
            dispatched=dispatched,
        )
        query_params = _NOT_IN_CAPTURE
        if disposition == "implemented_withheld":
            catalog = missing.get((method, normalize_operation_path(path)))
            if (
                catalog is None
                or catalog.method != "GET"
                or catalog.query_params != _NOT_IN_CAPTURE
                or catalog.on_client_allowlist
                or catalog.projection in {"disabled_secret", "disabled_read_post"}
            ):
                raise RemainingContractError(f"{operation_id} is not an unconnected missing GET")
            query_params = catalog.query_params
        row = RemainingLedgerRow(
            operation_id=operation_id,
            method=method,
            path=path,
            title=str(source["title"]),
            official_effect=effect,
            classification_effect=found.effect_class,
            effects_compatible=_COMPATIBLE.get(effect) == found.effect_class,
            client_allowlist=allowlisted,
            mcp_dispatch=dispatched,
            synthetic_facade=audit_row["synthetic_only_facade"] == "yes",
            existing_facade=found.synthetic_facade,
            reference_mcp=operation_id in references,
            path_params=found.path_params,
            documented_statuses=statuses,
            disposition=disposition,
            omission_reason=_OMISSION.get(disposition),
            callable_now=False,
            supported=False,
            execution_enabled=False,
            live_call=False,
            field_schema=_UNVERIFIED,
            input_schema=_UNVERIFIED,
            query_params=query_params,
            simulation_status="disabled_simulation",
        )
        rows.append(row)
    _assert_partition(rows)
    return tuple(rows)


def _assert_partition(rows: list[RemainingLedgerRow]) -> None:
    if len(rows) != 116 or len({item.operation_id for item in rows}) != 116:
        raise RemainingContractError("official operation count is not 116")
    omissions = sum(item.omission_reason is not None for item in rows)
    implemented = sum(item.disposition == "implemented_withheld" for item in rows)
    if omissions + implemented != 116:
        raise RemainingContractError("omission reasons do not partition the ledger")
    if any(
        item.supported or item.callable_now or item.execution_enabled or item.live_call
        for item in rows
    ):
        raise RemainingContractError("incomplete contract was marked supported")
    references = [item for item in rows if item.reference_mcp]
    connected = all(item.disposition == "already_mcp_dispatched" for item in references)
    if len(references) != 8 or not connected:
        raise RemainingContractError("reference MCP reads are not connected")
    unconfirmed = sum(
        item.official_effect in {"get_effect_unknown", "post_effect_unknown"} for item in rows
    )
    incompatible = sum(not item.effects_compatible for item in rows)
    if unconfirmed != 18 or incompatible != unconfirmed:
        raise RemainingContractError("unconfirmed effect count drifted")


def _index() -> dict[str, RemainingLedgerRow]:
    return {item.operation_id: item for item in remaining_ledger()}


def remaining_reads_summary() -> dict[str, object]:
    """Reason counts for the 116-operation partition. No payload data."""
    rows = remaining_ledger()
    audit = _audit_report()
    omissions = Counter(item.omission_reason for item in rows if item.omission_reason is not None)
    dispositions = Counter(item.disposition for item in rows)
    effects = Counter(item.official_effect for item in rows)
    implemented = dispositions["implemented_withheld"]
    if sum(omissions.values()) + implemented != len(rows):
        raise RemainingContractError("omission reasons do not match the ledger")
    return {
        "official_operation_count": len(rows),
        "callable_now": 0,
        "supported_now": 0,
        "execution_enabled": 0,
        "live_call": 0,
        "audit_counts": audit["counts"],
        "by_official_effect": dict(sorted(effects.items())),
        "unconfirmed_effect": effects["get_effect_unknown"] + effects["post_effect_unknown"],
        "by_disposition": dict(dispositions),
        "by_omission_reason": dict(omissions),
        "implemented_rows": implemented,
        "partition_total": len(rows),
    }


def _row(operation_id: str) -> RemainingLedgerRow:
    found = _index().get(operation_id)
    if found is None:
        raise AdapterInvalidRequestError("naver operation is not in the official contract")
    return found


def _reject_blocked(row: RemainingLedgerRow) -> None:
    if row.disposition == "implemented_withheld":
        return
    raise RemainingReadBlocked(row.omission_reason or "blocked")


def _reject_query(query: Mapping[str, Any] | None) -> None:
    if query:
        raise AdapterInvalidRequestError(
            "naver remaining read query params are not in the official capture"
        )


def validate_remaining_request(
    operation_id: str,
    *,
    path_values: Mapping[str, str] | None = None,
    query: Mapping[str, Any] | None = None,
) -> str:
    """Bind documented path tokens. Undocumented query names are rejected."""
    row = _row(operation_id)
    _reject_blocked(row)
    _reject_query(query)
    values = {} if path_values is None else dict(path_values)
    if set(values) != set(row.path_params):
        raise AdapterInvalidRequestError(
            "naver remaining read path params do not match the contract"
        )
    for name in row.path_params:
        if type(values[name]) is not str:
            raise AdapterInvalidRequestError("invalid naver remaining-read path token")
    return bind_path_params(row.path, values)


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


def project_remaining_read(
    operation_id: str,
    status: int,
    body: Any,
    *,
    bound_path: str,
    clock: Any,
) -> RemainingReadProjection:
    """Count an unverified body. Do not copy fields or mark the read supported."""
    row = _row(operation_id)
    _reject_blocked(row)
    if type(status) is not int:
        raise AdapterInvalidResponseError("naver remaining read result shape is invalid")
    if status != 200:
        if status in row.documented_statuses:
            raise RemainingReadStatusError(status)
        raise AdapterInvalidResponseError("naver remaining read result was not a page")
    if isinstance(body, dict):
        kind, row_count, field_count = "item", 1, len(body)
    elif isinstance(body, list):
        if len(body) > _MAX_ROWS or any(not isinstance(item, dict) for item in body):
            raise AdapterInvalidResponseError("naver remaining read result shape is invalid")
        kind, row_count, field_count = "page", len(body), sum(len(item) for item in body)
    else:
        raise AdapterInvalidResponseError("naver remaining read result shape is invalid")
    return RemainingReadProjection(
        operation_id=row.operation_id,
        method=row.method,
        path=row.path,
        bound_path=bound_path,
        title=row.title,
        callable_now=False,
        supported=False,
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


def mutation_stays_disabled(operation_id: str, transport: object | None = None) -> SimulationResult:
    """Return the disabled simulation for one official change API. Never calls out."""
    row = _row(operation_id)
    if row.official_effect != "mutation" or row.disposition != "disabled_simulation":
        raise RemainingReadBlocked(row.omission_reason or "not_a_confirmed_mutation")
    result = simulate(operation_id, transport)
    disabled = (
        result.execution_enabled
        or result.network_calls != 0
        or result.status != "disabled_simulation"
    )
    if disabled:
        raise RemainingContractError("mutation simulation was not disabled")
    return result


class NaverRemainingReads:
    """Synthetic projector for unconnected official read GETs."""

    def __init__(self, transport: Any, *, clock: Any = None) -> None:
        if isinstance(transport, NaverClient) or getattr(transport, "synthetic", False) is not True:
            raise AdapterInvalidRequestError(
                "naver remaining reads accept a synthetic transport only"
            )
        if not callable(getattr(transport, "exchange", None)):
            raise AdapterInvalidRequestError(
                "naver remaining reads accept a synthetic transport only"
            )
        self.transport = transport
        self._clock = clock or (lambda: datetime.now(UTC))

    async def _preview(
        self, operation_id: str, *, path_values: Mapping[str, str]
    ) -> RemainingReadProjection:
        row = _row(operation_id)
        _reject_blocked(row)
        if row.method != "GET":
            raise RemainingReadBlocked("not_a_get")
        bound = validate_remaining_request(operation_id, path_values=path_values)
        result = await self.transport.exchange(method="GET", path=bound)
        if not isinstance(result, tuple) or len(result) != 2 or type(result[0]) is not int:
            raise AdapterInvalidResponseError("naver remaining read transport shape is invalid")
        projected = project_remaining_read(
            operation_id, result[0], result[1], bound_path=bound, clock=self._clock
        )
        assert_agent_safe_value(projected)
        return projected

    async def preview(self, operation_id: str, **path_values: str) -> RemainingReadProjection:
        """Project one remaining GET, or block before any exchange."""
        row = _row(operation_id)
        _reject_blocked(row)
        return await self._preview(operation_id, path_values=path_values)


def _signature(names: tuple[str, ...], *, self_param: bool, query: bool) -> inspect.Signature:
    parameters: list[inspect.Parameter] = []
    if self_param:
        parameters.append(inspect.Parameter("self", inspect.Parameter.POSITIONAL_OR_KEYWORD))
    parameters.extend(
        inspect.Parameter(name, inspect.Parameter.KEYWORD_ONLY, annotation=str) for name in names
    )
    if query:
        parameters.append(inspect.Parameter("query", inspect.Parameter.KEYWORD_ONLY, default=None))
    return inspect.Signature(parameters)


def _install_independent_functions() -> None:
    for item in remaining_ledger():
        if item.disposition != "implemented_withheld":
            continue
        if any(not name.isidentifier() or name == "query" for name in item.path_params):
            raise RemainingContractError(
                f"path parameter is not an identifier: {item.operation_id}"
            )
        operation_id = item.operation_id
        path_params = item.path_params
        expected = set(path_params)
        slug = operation_id.replace("-", "_")

        def validate(
            _operation_id: str = operation_id,
            _expected: set[str] = expected,
            **kwargs: Any,
        ) -> str:
            query = kwargs.pop("query", None)
            if set(kwargs) != _expected:
                raise TypeError("naver remaining read path params do not match the contract")
            return validate_remaining_request(_operation_id, path_values=kwargs, query=query)

        def project(
            status: int,
            body: Any,
            *,
            bound_path: str,
            clock: Any,
            _operation_id: str = operation_id,
        ) -> RemainingReadProjection:
            return project_remaining_read(
                _operation_id, status, body, bound_path=bound_path, clock=clock
            )

        async def preview(
            self: NaverRemainingReads,
            _operation_id: str = operation_id,
            _expected: set[str] = expected,
            **kwargs: Any,
        ) -> RemainingReadProjection:
            if set(kwargs) != _expected:
                raise TypeError("naver remaining read path params do not match the contract")
            return await self._preview(_operation_id, path_values=kwargs)

        validate.__name__ = "validate_" + slug
        validate.__signature__ = _signature(path_params, self_param=False, query=True)  # type: ignore[attr-defined]
        project.__name__ = "project_" + slug
        preview.__name__ = "preview_" + slug
        preview.__signature__ = _signature(path_params, self_param=True, query=False)  # type: ignore[attr-defined]
        globals()[validate.__name__] = validate
        globals()[project.__name__] = project
        setattr(NaverRemainingReads, preview.__name__, preview)


_install_independent_functions()
