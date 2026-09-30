"""DOR approval verifier: fail-closed checks against append-only records.

The channel verifier requires exactly one approval: the latest
``external_publish`` row in ``approval_records`` for the exact
(project, batch, version, effective_from, channel) tuple must be a CEO
``approved`` row recorded at the evidence timestamp, plus exactly one
``intent_claimed`` row in ``product_automation_channel_publish_intents``
bound to the same attempt and artifact digest. No ``cmo_review`` or
``ceo_preview`` rows are required.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from k12_commerce_mcp.publishing.deferred_registration import PublishApprovalEvidence
from k12_commerce_mcp.publishing.dor_approval import (
    DorApprovalEvidenceVerifier,
    DorChannelApprovalVerifier,
)

EFFECTIVE_FROM = datetime(2026, 9, 1, tzinfo=UTC)
APPROVED_AT = datetime(2026, 9, 2, tzinfo=UTC)
EFFECTIVE_FROM_TEXT = "2026-09-01T00:00:00Z"
APPROVED_AT_TEXT = "2026-09-02T00:00:00Z"
DIGEST = "b" * 64
CHANNEL = "naver"


def _evidence(**overrides: Any) -> PublishApprovalEvidence:
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
    return PublishApprovalEvidence(**payload)


def _create_schema(
    path: Path, *, include_intents: bool = True, include_approvals: bool = True
) -> None:
    statements = []
    if include_approvals:
        statements.append(
            """CREATE TABLE approval_records(
                product_id TEXT NOT NULL,
                batch_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                effective_from TEXT NOT NULL,
                channel TEXT NOT NULL,
                approval_type TEXT NOT NULL,
                result TEXT NOT NULL,
                actor_role TEXT NOT NULL,
                recorded_at TEXT NOT NULL
            )"""
        )
    if include_intents:
        statements.append(
            """CREATE TABLE product_automation_channel_publish_intents(
                project TEXT NOT NULL,
                batch TEXT NOT NULL,
                version INTEGER NOT NULL,
                effective_from TEXT NOT NULL,
                channel TEXT NOT NULL,
                attempt_id TEXT NOT NULL,
                artifact_digest TEXT NOT NULL,
                status TEXT NOT NULL
            )"""
        )
    statements.append(
        """CREATE TABLE product_automation_naver_publication_attempts(
            attempt_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            batch_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            effective_from TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            result_status TEXT NOT NULL
        )"""
    )
    connection = sqlite3.connect(path)
    try:
        for statement in statements:
            connection.execute(statement)
        connection.commit()
    finally:
        connection.close()


def _insert_approval(
    path: Path,
    *,
    product_id: str = "project-1",
    batch_id: str = "batch-1",
    version: int = 3,
    effective_from: str = EFFECTIVE_FROM_TEXT,
    channel: str = CHANNEL,
    approval_type: str = "external_publish",
    result: str = "approved",
    actor_role: str = "CEO",
    recorded_at: str = APPROVED_AT_TEXT,
) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            """INSERT INTO approval_records
               (product_id,batch_id,version,effective_from,channel,
                approval_type,result,actor_role,recorded_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                product_id,
                batch_id,
                version,
                effective_from,
                channel,
                approval_type,
                result,
                actor_role,
                recorded_at,
            ),
        )
        connection.commit()
    finally:
        connection.close()


def _insert_intent(
    path: Path,
    *,
    project: str = "project-1",
    batch: str = "batch-1",
    version: int = 3,
    effective_from: str = EFFECTIVE_FROM_TEXT,
    channel: str = CHANNEL,
    attempt_id: str = "attempt-1",
    artifact_digest: str = DIGEST,
    status: str = "intent_claimed",
    count: int = 1,
) -> None:
    connection = sqlite3.connect(path)
    try:
        for _ in range(count):
            connection.execute(
                """INSERT INTO product_automation_channel_publish_intents
                   (project,batch,version,effective_from,channel,
                    attempt_id,artifact_digest,status)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    project,
                    batch,
                    version,
                    effective_from,
                    channel,
                    attempt_id,
                    artifact_digest,
                    status,
                ),
            )
        connection.commit()
    finally:
        connection.close()


def _insert_naver_attempt(
    path: Path,
    *,
    attempt_id: str = "attempt-1",
    project_id: str = "project-1",
    batch_id: str = "batch-1",
    version: int = 3,
    effective_from: str = EFFECTIVE_FROM_TEXT,
    idempotency_key: str = f"commerce-mcp:{DIGEST}",
    result_status: str = "intent_claimed",
) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            """INSERT INTO product_automation_naver_publication_attempts
               (attempt_id,project_id,batch_id,version,effective_from,
                idempotency_key,result_status)
               VALUES (?,?,?,?,?,?,?)""",
            (
                attempt_id,
                project_id,
                batch_id,
                version,
                effective_from,
                idempotency_key,
                result_status,
            ),
        )
        connection.commit()
    finally:
        connection.close()


def _ready_db(tmp_path: Path) -> Path:
    path = tmp_path / "dor.sqlite"
    _create_schema(path)
    _insert_approval(path)
    _insert_intent(path)
    return path


def _channel_verifier(path: Path) -> DorChannelApprovalVerifier:
    return DorChannelApprovalVerifier(path, channel=CHANNEL)


def test_single_ceo_external_publish_row_is_sufficient(tmp_path: Path) -> None:
    path = _ready_db(tmp_path)
    _channel_verifier(path).verify(_evidence(), idempotency_key=DIGEST)


def test_cmo_and_ceo_preview_rows_are_not_required(tmp_path: Path) -> None:
    """Approval rows of other types must not be consulted at all."""
    path = tmp_path / "dor.sqlite"
    _create_schema(path)
    _insert_approval(path)
    _insert_approval(
        path, approval_type="cmo_review", result="rejected", actor_role="CMO"
    )
    _insert_approval(
        path, approval_type="ceo_preview", result="rejected", actor_role="CEO"
    )
    _insert_intent(path)
    _channel_verifier(path).verify(_evidence(), idempotency_key=DIGEST)


def test_missing_external_publish_row_fails(tmp_path: Path) -> None:
    path = tmp_path / "dor.sqlite"
    _create_schema(path)
    _insert_intent(path)
    with pytest.raises(ValueError):
        _channel_verifier(path).verify(_evidence(), idempotency_key=DIGEST)


def test_revoked_latest_external_publish_row_fails(tmp_path: Path) -> None:
    path = tmp_path / "dor.sqlite"
    _create_schema(path)
    _insert_approval(path, recorded_at="2026-09-01T12:00:00Z")
    _insert_approval(path, result="revoked", recorded_at="2026-09-03T00:00:00Z")
    _insert_intent(path)
    with pytest.raises(ValueError):
        _channel_verifier(path).verify(_evidence(), idempotency_key=DIGEST)


def test_non_ceo_actor_role_fails(tmp_path: Path) -> None:
    path = tmp_path / "dor.sqlite"
    _create_schema(path)
    _insert_approval(path, actor_role="CMO")
    _insert_intent(path)
    with pytest.raises(ValueError):
        _channel_verifier(path).verify(_evidence(), idempotency_key=DIGEST)


def test_non_approved_result_fails(tmp_path: Path) -> None:
    path = tmp_path / "dor.sqlite"
    _create_schema(path)
    _insert_approval(path, result="rejected")
    _insert_intent(path)
    with pytest.raises(ValueError):
        _channel_verifier(path).verify(_evidence(), idempotency_key=DIGEST)


def test_wrong_channel_fails(tmp_path: Path) -> None:
    path = tmp_path / "dor.sqlite"
    _create_schema(path)
    _insert_approval(path, channel="coupang")
    _insert_intent(path, channel="coupang")
    with pytest.raises(ValueError):
        _channel_verifier(path).verify(_evidence(), idempotency_key=DIGEST)


def test_wrong_tuple_fails(tmp_path: Path) -> None:
    path = tmp_path / "dor.sqlite"
    _create_schema(path)
    _insert_approval(path, version=4)
    _insert_intent(path, version=4)
    with pytest.raises(ValueError):
        _channel_verifier(path).verify(_evidence(), idempotency_key=DIGEST)


def test_recorded_at_mismatch_fails(tmp_path: Path) -> None:
    path = tmp_path / "dor.sqlite"
    _create_schema(path)
    _insert_approval(path, recorded_at="2026-09-03T00:00:00Z")
    _insert_intent(path)
    with pytest.raises(ValueError):
        _channel_verifier(path).verify(_evidence(), idempotency_key=DIGEST)


def test_idempotency_key_must_equal_artifact_digest(tmp_path: Path) -> None:
    path = _ready_db(tmp_path)
    with pytest.raises(ValueError):
        _channel_verifier(path).verify(_evidence(), idempotency_key="c" * 64)


def test_missing_intent_row_fails(tmp_path: Path) -> None:
    path = tmp_path / "dor.sqlite"
    _create_schema(path)
    _insert_approval(path)
    with pytest.raises(ValueError):
        _channel_verifier(path).verify(_evidence(), idempotency_key=DIGEST)


def test_ambiguous_intent_rows_fail(tmp_path: Path) -> None:
    path = tmp_path / "dor.sqlite"
    _create_schema(path)
    _insert_approval(path)
    _insert_intent(path, count=2)
    with pytest.raises(ValueError):
        _channel_verifier(path).verify(_evidence(), idempotency_key=DIGEST)


def test_intent_attempt_mismatch_fails(tmp_path: Path) -> None:
    path = tmp_path / "dor.sqlite"
    _create_schema(path)
    _insert_approval(path)
    _insert_intent(path, attempt_id="attempt-2")
    with pytest.raises(ValueError):
        _channel_verifier(path).verify(_evidence(), idempotency_key=DIGEST)


def test_intent_artifact_mismatch_fails(tmp_path: Path) -> None:
    path = tmp_path / "dor.sqlite"
    _create_schema(path)
    _insert_approval(path)
    _insert_intent(path, artifact_digest="d" * 64)
    with pytest.raises(ValueError):
        _channel_verifier(path).verify(_evidence(), idempotency_key=DIGEST)


def test_intent_wrong_status_fails(tmp_path: Path) -> None:
    path = tmp_path / "dor.sqlite"
    _create_schema(path)
    _insert_approval(path)
    _insert_intent(path, status="published")
    with pytest.raises(ValueError):
        _channel_verifier(path).verify(_evidence(), idempotency_key=DIGEST)


def test_missing_intent_table_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "dor.sqlite"
    _create_schema(path, include_intents=False)
    _insert_approval(path)
    with pytest.raises(ValueError):
        _channel_verifier(path).verify(_evidence(), idempotency_key=DIGEST)


def test_missing_approval_table_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "dor.sqlite"
    _create_schema(path, include_approvals=False)
    _insert_intent(path)
    with pytest.raises(sqlite3.OperationalError):
        _channel_verifier(path).verify(_evidence(), idempotency_key=DIGEST)


def test_directory_database_path_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        _channel_verifier(tmp_path).verify(_evidence(), idempotency_key=DIGEST)


def test_symlink_database_path_fails_closed(tmp_path: Path) -> None:
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    target = _ready_db(real_dir)
    link = tmp_path / "link.sqlite"
    link.symlink_to(target)
    with pytest.raises(ValueError):
        _channel_verifier(link).verify(_evidence(), idempotency_key=DIGEST)


def test_naver_verifier_accepts_single_external_publish_row(tmp_path: Path) -> None:
    path = _ready_db(tmp_path)
    _insert_naver_attempt(path)
    DorApprovalEvidenceVerifier(path).verify(_evidence(), idempotency_key=DIGEST)


def test_naver_verifier_fails_without_intent_claimed_attempt(tmp_path: Path) -> None:
    path = _ready_db(tmp_path)
    with pytest.raises(ValueError):
        DorApprovalEvidenceVerifier(path).verify(_evidence(), idempotency_key=DIGEST)
