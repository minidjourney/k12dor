"""Approval gate contract: one explicit CEO external-publish approval.

Publication evidence is a single external-publish approval recorded by the
CEO for the exact (project, batch, version, effective_from, channel)
artifact. There is no CMO review stage and no separate CEO preview stage.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from k12_commerce_mcp.models.common import CanonicalModel
from k12_commerce_mcp.publishing.deferred_registration import (
    PublishApprovalEvidence,
    approved_artifact_digest,
    assert_idempotency_key,
    revalidate_approval_evidence,
)

EFFECTIVE_FROM = datetime(2026, 9, 1, tzinfo=UTC)
APPROVED_AT = datetime(2026, 9, 2, tzinfo=UTC)
DIGEST = "a" * 64


def _payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "external_publish_approval": True,
        "external_publish_approved_at": APPROVED_AT,
        "artifact_digest": DIGEST,
        "attempt_id": "attempt-1",
        "project_id": "project-1",
        "batch_id": "batch-1",
        "version": 3,
        "effective_from": EFFECTIVE_FROM,
    }
    payload.update(overrides)
    return payload


def _evidence(**overrides: Any) -> PublishApprovalEvidence:
    return PublishApprovalEvidence(**_payload(**overrides))


def test_single_ceo_external_publish_approval_is_sufficient() -> None:
    evidence = _evidence()
    assert evidence.external_publish_approval is True
    assert evidence.external_publish_approved_at == APPROVED_AT
    assert evidence.artifact_digest == DIGEST


def test_external_publish_approval_must_be_true() -> None:
    with pytest.raises(ValidationError):
        _evidence(external_publish_approval=False)


def test_approval_cannot_predate_effective_from() -> None:
    with pytest.raises(ValidationError):
        _evidence(
            external_publish_approved_at=datetime(2026, 8, 31, 23, 59, 59, tzinfo=UTC)
        )


def test_approval_at_exactly_effective_from_is_accepted() -> None:
    evidence = _evidence(external_publish_approved_at=EFFECTIVE_FROM)
    assert evidence.external_publish_approved_at == EFFECTIVE_FROM


def test_retired_three_stage_fields_are_rejected() -> None:
    """A payload carrying the retired CMO/CEO-preview fields must not validate."""
    with pytest.raises(ValidationError):
        _evidence(
            marketing_review=True,
            ceo_preview_approval=True,
            evidence_recorded_at=EFFECTIVE_FROM,
            marketing_reviewed_at=EFFECTIVE_FROM,
            ceo_preview_approved_at=APPROVED_AT,
        )


@pytest.mark.parametrize(
    "removed_field,value",
    [
        ("marketing_review", True),
        ("ceo_preview_approval", True),
        ("evidence_recorded_at", APPROVED_AT),
        ("marketing_reviewed_at", APPROVED_AT),
        ("ceo_preview_approved_at", APPROVED_AT),
    ],
)
def test_each_retired_field_is_rejected(removed_field: str, value: Any) -> None:
    with pytest.raises(ValidationError):
        _evidence(**{removed_field: value})


@pytest.mark.parametrize(
    "bad_digest",
    ["", "a" * 63, "a" * 65, "g" * 64, "A" * 64],
)
def test_artifact_digest_must_be_64_lowercase_hex(bad_digest: str) -> None:
    with pytest.raises(ValidationError):
        _evidence(artifact_digest=bad_digest)


@pytest.mark.parametrize(
    "field",
    ["attempt_id", "project_id", "batch_id"],
)
def test_identifiers_are_bounded(field: str) -> None:
    with pytest.raises(ValidationError):
        _evidence(**{field: ""})
    with pytest.raises(ValidationError):
        _evidence(**{field: "x" * 201})


def test_version_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        _evidence(version=0)


@pytest.mark.parametrize(
    "field",
    ["external_publish_approved_at", "effective_from"],
)
def test_timestamps_must_be_timezone_aware(field: str) -> None:
    with pytest.raises(ValidationError):
        _evidence(**{field: datetime(2026, 9, 1)})


def test_revalidation_catches_construct_bypass_of_confirm_flag() -> None:
    evidence = PublishApprovalEvidence.model_construct(
        external_publish_approval=False,
        external_publish_approved_at=APPROVED_AT,
        artifact_digest=DIGEST,
        attempt_id="attempt-1",
        project_id="project-1",
        batch_id="batch-1",
        version=3,
        effective_from=EFFECTIVE_FROM,
    )
    with pytest.raises(ValidationError):
        revalidate_approval_evidence(evidence)


def test_revalidation_catches_construct_bypass_of_stale_timestamp() -> None:
    evidence = PublishApprovalEvidence.model_construct(
        external_publish_approval=True,
        external_publish_approved_at=datetime(2026, 8, 1, tzinfo=UTC),
        artifact_digest=DIGEST,
        attempt_id="attempt-1",
        project_id="project-1",
        batch_id="batch-1",
        version=3,
        effective_from=EFFECTIVE_FROM,
    )
    with pytest.raises(ValidationError):
        revalidate_approval_evidence(evidence)


class _Draft(CanonicalModel):
    title: str


def test_approved_artifact_digest_binds_exact_tuple_and_draft() -> None:
    draft = _Draft(title="Widget")
    evidence = _evidence()
    first = approved_artifact_digest(draft, evidence)
    assert first == approved_artifact_digest(draft, evidence)
    assert first != approved_artifact_digest(draft, _evidence(project_id="project-2"))
    assert first != approved_artifact_digest(draft, _evidence(batch_id="batch-2"))
    assert first != approved_artifact_digest(draft, _evidence(version=4))
    assert first != approved_artifact_digest(
        draft, _evidence(effective_from=datetime(2026, 9, 2, tzinfo=UTC))
    )
    assert first != approved_artifact_digest(_Draft(title="Gadget"), evidence)


def test_idempotency_key_must_be_64_hex() -> None:
    assert_idempotency_key("b" * 64)
    with pytest.raises(ValueError):
        assert_idempotency_key("b" * 63)
    with pytest.raises(ValueError):
        assert_idempotency_key("z" * 64)
