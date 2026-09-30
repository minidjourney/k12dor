"""Shared scaffolding for approval-gated marketplace publishers."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Protocol

from pydantic import AwareDatetime, ConfigDict, Field, model_validator

from ..models.common import CanonicalModel
from ..write_gate import DeferredWrite


class DeferredRegistrationPublisher:
    """Sealed publisher seam for writes gated until detail-page automation.

    The optional client is stored for the future batch only. ``publish``
    implementations must call ``assert_registration_enabled()`` before any
    client interaction, so no provider request can run in this batch.
    """

    intended_writes: tuple[DeferredWrite, ...] = ()

    def __init__(self, *, client: Any | None = None) -> None:
        self._client = client


class PublishApprovalEvidence(CanonicalModel):
    """One explicit CEO external-publish approval bound to the exact artifact.

    Approval covers a single (project, batch, version, effective_from,
    channel) artifact digest. Retired multi-stage fields are rejected rather
    than silently ignored.
    """

    model_config = ConfigDict(extra="forbid")

    external_publish_approval: bool
    external_publish_approved_at: AwareDatetime
    artifact_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    attempt_id: str = Field(min_length=1, max_length=200)
    project_id: str = Field(min_length=1, max_length=200)
    batch_id: str = Field(min_length=1, max_length=200)
    version: int = Field(ge=1)
    effective_from: AwareDatetime

    @model_validator(mode="after")
    def validate_evidence(self) -> PublishApprovalEvidence:
        if not self.external_publish_approval:
            raise ValueError("approval evidence is incomplete")
        if self.external_publish_approved_at < self.effective_from:
            raise ValueError("approval evidence is stale or out of order")
        return self


class PublishApprovalVerifier(Protocol):
    def verify(self, evidence: Any, *, idempotency_key: str) -> None: ...


def revalidate_approval_evidence(evidence: PublishApprovalEvidence) -> None:
    """Re-run evidence validators so model_construct cannot bypass confirm flags."""
    type(evidence).model_validate(evidence.model_dump(mode="json"))


def assert_idempotency_key(idempotency_key: str) -> None:
    """Require the opaque 64-hex idempotency key shape before any write."""
    if not isinstance(idempotency_key, str) or len(idempotency_key) != 64:
        raise ValueError("idempotency key is invalid")
    if any(character not in "0123456789abcdef" for character in idempotency_key):
        raise ValueError("idempotency key is invalid")


def utc_milliseconds(value: datetime) -> str:
    utc = value.astimezone(UTC)
    return f"{utc.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3]}Z"


def approved_artifact_digest(
    draft: CanonicalModel, approval: PublishApprovalEvidence
) -> str:
    """Digest binding one canonical draft to one approved artifact envelope."""
    envelope = {
        "projectId": approval.project_id,
        "batchId": approval.batch_id,
        "version": approval.version,
        "effectiveFrom": utc_milliseconds(approval.effective_from),
        "canonical": draft.model_dump(mode="json"),
    }
    encoded = json.dumps(envelope, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(encoded.encode()).hexdigest()


def provider_id_digest(artifact_digest: str, value: object) -> str:
    """Derive an opaque canonical ID so raw provider IDs never reach results."""
    return hashlib.sha256(f"{artifact_digest}:{value}".encode()).hexdigest()


def provider_payload_camelize(value: Any) -> Any:
    """Map canonical snake_case keys to the provider's documented camelCase."""
    if isinstance(value, dict):
        converted: dict[Any, Any] = {}
        for key, child in value.items():
            if not isinstance(key, str):
                converted[key] = provider_payload_camelize(child)
                continue
            parts = key.split("_")
            converted[parts[0] + "".join(part.title() for part in parts[1:])] = (
                provider_payload_camelize(child)
            )
        return converted
    if isinstance(value, (list, tuple)):
        return [provider_payload_camelize(child) for child in value]
    return value
