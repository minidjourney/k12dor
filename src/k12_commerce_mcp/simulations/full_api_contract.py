"""Fail-closed full-API contract for the three-channel 20260916 snapshot.

Covers every documented Coupang general, Rocket Growth, and Naver operation
whose effect is a mutation, an auth/token issuance, or not yet proven
side-effect free. The caller supplies the operation inventory produced by
``scripts/build_three_channel_api_manifest.py``; this module never reads the
snapshot, never imports a network client or credential, never opens HTTP, a
database, or a file, and never issues an approval.

Simulating returns a bounded synthetic receipt. Every execution request
returns an unconditional CEO-approval-required block: a real call needs a
separate per-target CEO approval granted outside this module, and a
simulated approval grant never enables transport. Caller-supplied payloads,
tokens, and freeform values are ignored and never echoed.

Entries keep the manifest channel labels verbatim (``coupang_general``,
``rocket_growth``, ``naver``) so every entry joins back to its manifest row.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace

SNAPSHOT_ID = "20260916"
MANIFEST_BUILDER = "scripts/build_three_channel_api_manifest.py"

KIND_WRITE = "documented_write"
KIND_AUTH = "auth_token_issue"
KIND_UNKNOWN_GET = "unknown_effect_get"
KIND_UNKNOWN_POST = "unknown_effect_post"
KIND_UNCLASSIFIED = "unclassified_blocked"

_EFFECT_KIND = {
    "mutation": KIND_WRITE,
    "auth": KIND_AUTH,
    "get_effect_unknown": KIND_UNKNOWN_GET,
    "post_effect_unknown": KIND_UNKNOWN_POST,
}
_READ_EFFECTS = frozenset({"read", "read_post"})
_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE"})

RG_CHANNEL = "rocket_growth"
_RG_DEDICATED = "/rg_open_api/"
_GENERAL_CLAIM_MARKERS = (
    "returnrequests",
    "exchangerequests",
    "returnwithdrawrequests",
    "ordersheets",
    "cancel",
)
_PLACEHOLDER = re.compile(r"\{[^}]*\}|:[A-Za-z0-9_]+")

_MALFORMED = "malformed contract input"
_REFUSAL = "full-api contract refused"
_APPROVAL_SCOPE = "ceo_per_target_single_operation"
_BLOCK_REASONS = {
    "absent": "ceo_per_target_approval_required",
    "malformed": "approval_token_malformed_blocked",
    "denied": "approval_denied_blocked",
    "target_mismatch": "approval_target_mismatch_blocked",
    "simulated_grant_present": "simulated_grant_never_enables_transport",
}


class ContractError(Exception):
    """Malformed contract input. The message is fixed and echoes nothing."""


class ContractRefusal(Exception):
    """Unknown or ambiguous reference. The message is fixed and echoes nothing."""


@dataclass(frozen=True)
class ContractEntry:
    """One documented non-read operation. It is never executable from here."""

    entry_id: str
    manifest_key: str
    channel: str
    method: str
    path: str
    kind: str
    effect_class: str
    function_name: str
    query_signature: str
    query_param_names: tuple[str, ...]
    path_shape: str
    rg_dedicated: bool
    rg_shared_general_uri: bool
    ambiguous: bool = False
    status: str = "disabled_simulation"
    execution_enabled: bool = False
    approval: str = "none"
    live_call: bool = False
    external_calls: int = 0

    @property
    def binding_key(self) -> str:
        return "|".join((self.channel, self.method, self.path, self.query_signature))


@dataclass(frozen=True)
class CollisionGroup:
    """Entries sharing channel, method, path shape, and query signature.

    Colliding entries cannot be told apart, so binding refuses them instead
    of merging same-URI variants into one operation.
    """

    binding_shape: str
    entry_ids: tuple[str, ...]


@dataclass(frozen=True)
class SimulatedApprovalGrant:
    """Local stand-in for a later CEO per-target grant. Never enables transport."""

    decision: str
    scope: str
    target_entry_id: str


@dataclass(frozen=True)
class BindingVerdict:
    """Identity verdict for one channel+method+path+query-variant. Never a call."""

    status: str
    reason: str
    entry_id: str | None = None
    candidates: int = 0
    rg_proof: bool = False
    execution_enabled: bool = False
    live_call: bool = False


@dataclass(frozen=True)
class SyntheticResult:
    """Bounded synthetic receipt. No caller data is copied into it."""

    entry_id: str
    channel: str
    method: str
    path: str
    kind: str
    binding_digest: str
    status: str = "disabled_simulation"
    executed: bool = False
    transmitted: bool = False
    network_calls: int = 0
    approval: str = "none"
    external_calls: int = 0


@dataclass(frozen=True)
class ExecutionBlock:
    """Unconditional block. Execution needs separate CEO per-target approval."""

    entry_id: str
    approval_status: str
    blocked_reason: str
    status: str = "blocked"
    executed: bool = False
    transport_enabled: bool = False
    network_calls: int = 0
    ceo_per_target_approval_required: bool = True
    external_calls: int = 0


def _require_str(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ContractError(_MALFORMED)
    return value


def _entry_from(op: Mapping[str, object]) -> ContractEntry | None:
    channel = _require_str(op.get("channel"))
    method = _require_str(op.get("method"))
    path = _require_str(op.get("path"))
    effect = _require_str(op.get("effect_class"))
    if (
        method not in _METHODS
        or not path.startswith("/")
        or "//" in path
        or "?" in path
        or any(char.isspace() for char in path)
    ):
        raise ContractError(_MALFORMED)
    raw_names = op.get("query_param_names")
    if raw_names is None:
        names: tuple[str, ...] = ()
        signature = "unknown"
    elif isinstance(raw_names, (list, tuple)) and all(
        isinstance(name, str) and name for name in raw_names
    ):
        names = tuple(raw_names)
        signature = "params:" + ",".join(names)
    else:
        raise ContractError(_MALFORMED)
    prefix = f"{channel}|{method}|{path}|"
    key = op.get("operation_key")
    if key is None:
        manifest_key = prefix + signature
    elif isinstance(key, str) and key.startswith(prefix):
        manifest_key = key
    else:
        raise ContractError(_MALFORMED)
    if effect in _READ_EFFECTS:
        return None
    name = op.get("function_name")
    dedicated = channel == RG_CHANNEL and _RG_DEDICATED in path
    return ContractEntry(
        entry_id="contract-" + hashlib.sha256(manifest_key.encode("utf-8")).hexdigest()[:16],
        manifest_key=manifest_key,
        channel=channel,
        method=method,
        path=path,
        kind=_EFFECT_KIND.get(effect, KIND_UNCLASSIFIED),
        effect_class=effect,
        function_name=name if isinstance(name, str) else "",
        query_signature=signature,
        query_param_names=names,
        path_shape=_PLACEHOLDER.sub("{}", path),
        rg_dedicated=dedicated,
        rg_shared_general_uri=channel == RG_CHANNEL and not dedicated,
    )


def _approval_status(approval: object, entry_id: str) -> str:
    if approval is None:
        return "absent"
    if not isinstance(approval, SimulatedApprovalGrant):
        return "malformed"
    fields = (approval.decision, approval.scope, approval.target_entry_id)
    if not all(isinstance(item, str) and item for item in fields):
        return "malformed"
    if approval.decision != "approved":
        return "denied"
    if approval.scope != _APPROVAL_SCOPE:
        return "malformed"
    if approval.target_entry_id != entry_id:
        return "target_mismatch"
    return "simulated_grant_present"


@dataclass(frozen=True)
class FullApiContract:
    """Closed contract over the documented non-read operations."""

    entries: tuple[ContractEntry, ...]
    collisions: tuple[CollisionGroup, ...]
    operations_seen: int
    read_operations: int
    snapshot_id: str = SNAPSHOT_ID
    knowledge_status: str = "snapshot_not_confirmed"
    post_snapshot_document_change: str = "unknown"

    def get(self, ref: object) -> ContractEntry:
        return self._require(ref)

    def _require(self, ref: object) -> ContractEntry:
        if not isinstance(ref, str):
            raise ContractRefusal(_REFUSAL)
        matches = [
            item for item in self.entries if item.entry_id == ref or item.manifest_key == ref
        ]
        if len(matches) != 1 or matches[0].ambiguous:
            raise ContractRefusal(_REFUSAL)
        return matches[0]

    def resolve_binding(
        self,
        channel: object,
        method: object,
        path: object,
        *,
        query_params: Iterable[str] | None = None,
    ) -> BindingVerdict:
        """Identify one entry without enabling a call.

        Same-URI operations are never merged: a URI alone does not bind.
        Unknown-effect variants stay distinct from documented writes, and a
        shared general URI is never Rocket Growth proof.
        """
        if not all(isinstance(value, str) for value in (channel, method, path)):
            return BindingVerdict("rejected", "malformed_binding")
        if method not in _METHODS:
            return BindingVerdict("rejected", "malformed_method")
        if not path.startswith("/") or "//" in path or "?" in path:
            return BindingVerdict("rejected", "malformed_path")
        if channel == RG_CHANNEL and any(
            marker in path.casefold() for marker in _GENERAL_CLAIM_MARKERS
        ):
            return BindingVerdict("rejected", "general_claim_not_rg")
        shape = _PLACEHOLDER.sub("{}", path)
        candidates = [
            item
            for item in self.entries
            if item.channel == channel and item.method == method and item.path_shape == shape
        ]
        if query_params is not None:
            if not isinstance(query_params, (list, tuple)) or not all(
                isinstance(name, str) for name in query_params
            ):
                return BindingVerdict("rejected", "malformed_query")
            wanted = "params:" + ",".join(query_params)
            candidates = [
                item for item in candidates if item.query_signature in (wanted, "unknown")
            ]
        if not candidates:
            return BindingVerdict("unbound", "unknown_feature")
        if len(candidates) > 1 or candidates[0].ambiguous:
            return BindingVerdict("ambiguous", "binding_not_unique", candidates=len(candidates))
        entry = candidates[0]
        if channel == RG_CHANNEL:
            if not entry.rg_dedicated:
                return BindingVerdict(
                    "bound",
                    "shared_general_uri_not_rg_proof",
                    entry.entry_id,
                    1,
                )
            return BindingVerdict(
                "bound", "official_rg_uri_not_called", entry.entry_id, 1, rg_proof=True
            )
        return BindingVerdict("bound", "bound_not_called", entry.entry_id, 1)

    def simulate(
        self,
        ref: object,
        *,
        transport: object = None,
        payload: object = None,
        approval: object = None,
    ) -> SyntheticResult:
        """Return a bounded disabled receipt. transport and payload are unused."""
        del transport, payload, approval
        entry = self._require(ref)
        return SyntheticResult(
            entry_id=entry.entry_id,
            channel=entry.channel,
            method=entry.method,
            path=entry.path,
            kind=entry.kind,
            binding_digest=hashlib.sha256(entry.manifest_key.encode("utf-8")).hexdigest()[:16],
        )

    def request_execution(
        self,
        ref: object,
        *,
        approval: object = None,
        transport: object = None,
        payload: object = None,
    ) -> ExecutionBlock:
        """Always block. No approval object passed here can enable transport."""
        del transport, payload
        entry = self._require(ref)
        status = _approval_status(approval, entry.entry_id)
        return ExecutionBlock(
            entry_id=entry.entry_id,
            approval_status=status,
            blocked_reason=_BLOCK_REASONS[status],
        )

    def activate(self, ref: object) -> None:
        """Refuse activation for every reference, known or not."""
        del ref
        raise ContractRefusal(_REFUSAL)

    def summary(self) -> dict[str, object]:
        by_channel = Counter(item.channel for item in self.entries)
        by_kind = Counter(item.kind for item in self.entries)
        return {
            "snapshot_id": self.snapshot_id,
            "operations_seen": self.operations_seen,
            "contract_entries": len(self.entries),
            "read_operations_excluded": self.read_operations,
            "by_channel": dict(sorted(by_channel.items())),
            "by_kind": dict(sorted(by_kind.items())),
            "collision_groups": len(self.collisions),
            "enabled_entries": sum(1 for item in self.entries if item.execution_enabled),
            "live_call_entries": sum(1 for item in self.entries if item.live_call),
            "knowledge_status": self.knowledge_status,
            "post_snapshot_document_change": self.post_snapshot_document_change,
        }


def build_contract(operations: Iterable[Mapping[str, object]]) -> FullApiContract:
    """Build the closed contract over manifest operation rows."""
    entries: list[ContractEntry] = []
    reads = 0
    seen = 0
    for op in operations:
        if not isinstance(op, Mapping):
            raise ContractError(_MALFORMED)
        seen += 1
        entry = _entry_from(op)
        if entry is None:
            reads += 1
        else:
            entries.append(entry)
    groups: dict[tuple[str, str, str, str], list[ContractEntry]] = {}
    for entry in entries:
        key = (entry.channel, entry.method, entry.path_shape, entry.query_signature)
        groups.setdefault(key, []).append(entry)
    collisions: list[CollisionGroup] = []
    ambiguous_ids: set[str] = set()
    for (channel, method, shape, signature), group in groups.items():
        if len(group) < 2:
            continue
        ids = tuple(sorted({item.entry_id for item in group}))
        collisions.append(CollisionGroup("|".join((channel, method, shape, signature)), ids))
        ambiguous_ids.update(ids)
    if ambiguous_ids:
        entries = [
            replace(item, ambiguous=True) if item.entry_id in ambiguous_ids else item
            for item in entries
        ]
    return FullApiContract(
        entries=tuple(entries),
        collisions=tuple(collisions),
        operations_seen=seen,
        read_operations=reads,
    )


def contract_from_manifest(manifest: Mapping[str, object]) -> FullApiContract:
    """Build the contract from a ``build_manifest`` result dict."""
    if not isinstance(manifest, Mapping):
        raise ContractError(_MALFORMED)
    operations = manifest.get("operations")
    if not isinstance(operations, Iterable) or isinstance(operations, (str, bytes)):
        raise ContractError(_MALFORMED)
    return build_contract(operations)
