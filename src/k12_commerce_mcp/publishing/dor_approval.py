"""Read-only verification of DOR's append-only publication approval evidence."""

from __future__ import annotations

import sqlite3
import stat
from datetime import datetime
from pathlib import Path
from typing import Any

APPROVAL_TYPES = {
    "external_publish": "external_publish_approved_at",
}
CHANNEL_INTENT_TABLE = "product_automation_channel_publish_intents"
INTENT_STATUS = "intent_claimed"


def _instant(value: Any) -> float:
    if isinstance(value, datetime):
        return value.timestamp()
    text = str(value).replace("Z", "+00:00")
    return datetime.fromisoformat(text).timestamp()


def _open_readonly(database_path: Path) -> sqlite3.Connection:
    metadata = database_path.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ValueError("DOR approval database is invalid")
    connection = sqlite3.connect(f"file:{database_path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


def _verify_approval_records(
    connection: sqlite3.Connection, evidence: Any, channel: str
) -> None:
    """Require the latest external_publish record to be a CEO approval."""
    rows = connection.execute(
        """SELECT approval_type,result,actor_role,recorded_at
           FROM approval_records
           WHERE product_id=? AND batch_id=? AND version=?
             AND julianday(effective_from)=julianday(?) AND channel=?
           ORDER BY julianday(recorded_at),rowid""",
        (
            evidence.project_id,
            evidence.batch_id,
            evidence.version,
            evidence.effective_from.isoformat().replace("+00:00", "Z"),
            channel,
        ),
    ).fetchall()
    latest = {row["approval_type"]: row for row in rows}
    for approval_type, evidence_field in APPROVAL_TYPES.items():
        row = latest.get(approval_type)
        if row is None or row["result"] != "approved" or row["actor_role"] != "CEO":
            raise ValueError("DOR approval record is missing or revoked")
        if _instant(row["recorded_at"]) != _instant(getattr(evidence, evidence_field)):
            raise ValueError("DOR approval record does not match evidence")


class DorApprovalEvidenceVerifier:
    """Verify evidence against the exact latest DOR records without writing DOR state."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path

    def verify(self, evidence: Any, *, idempotency_key: str) -> None:
        if idempotency_key != evidence.artifact_digest:
            raise ValueError("idempotency key does not match approved artifact")
        connection = _open_readonly(self._database_path)
        try:
            _verify_approval_records(connection, evidence, "naver")
            attempt = connection.execute(
                """SELECT 1 FROM product_automation_naver_publication_attempts
                   WHERE attempt_id=? AND project_id=? AND batch_id=?
                     AND version=? AND julianday(effective_from)=julianday(?)
                     AND idempotency_key=? AND result_status='intent_claimed'""",
                (
                    evidence.attempt_id,
                    evidence.project_id,
                    evidence.batch_id,
                    evidence.version,
                    evidence.effective_from.isoformat().replace("+00:00", "Z"),
                    f"commerce-mcp:{idempotency_key}",
                ),
            ).fetchone()
            if attempt is None:
                raise ValueError("DOR publication intent is missing")
        finally:
            connection.close()


class DorChannelApprovalVerifier:
    """Verify evidence against exact DOR records for one configured channel.

    The channel is bound at construction; verification binds the exact tuple
    (project, batch, version, effective_from, channel, attempt_id,
    artifact_digest). The latest ``external_publish`` approval record must be
    CEO-approved at the evidence timestamp, and exactly one append-only row in
    ``product_automation_channel_publish_intents`` must match the tuple with
    status ``intent_claimed``. An absent table, an absent row, or more than
    one matching row fails closed.
    """

    def __init__(self, database_path: Path, *, channel: str) -> None:
        self._database_path = database_path
        self._channel = channel

    def verify(self, evidence: Any, *, idempotency_key: str) -> None:
        if idempotency_key != evidence.artifact_digest:
            raise ValueError("idempotency key does not match approved artifact")
        connection = _open_readonly(self._database_path)
        try:
            _verify_approval_records(connection, evidence, self._channel)
            try:
                intents = connection.execute(
                    f"""SELECT attempt_id FROM {CHANNEL_INTENT_TABLE}
                        WHERE project=? AND batch=? AND version=?
                          AND julianday(effective_from)=julianday(?)
                          AND channel=? AND attempt_id=? AND artifact_digest=?
                          AND status=?""",
                    (
                        evidence.project_id,
                        evidence.batch_id,
                        evidence.version,
                        evidence.effective_from.isoformat().replace("+00:00", "Z"),
                        self._channel,
                        evidence.attempt_id,
                        evidence.artifact_digest,
                        INTENT_STATUS,
                    ),
                ).fetchall()
            except sqlite3.Error as exc:
                raise ValueError(
                    "DOR channel publish intent is missing or ambiguous"
                ) from exc
            if len(intents) != 1:
                raise ValueError("DOR channel publish intent is missing or ambiguous")
        finally:
            connection.close()
