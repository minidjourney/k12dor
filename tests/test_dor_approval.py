"""Channel-scoped DOR approval evidence verification against temp sqlite DBs.

The verifier only reads (`mode=ro`, `PRAGMA query_only=ON`). These tests build
disposable sqlite fixtures; no provider, network, or real DOR database is
touched.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from k12_commerce_mcp.publishing import (
    CoupangApprovalEvidence,
    NaverApprovalEvidence,
    TossApprovalEvidence,
)
from k12_commerce_mcp.publishing.dor_approval import DorChannelApprovalVerifier

CHANNELS = ("coupang", "naver", "toss")
EVIDENCE_MODELS = {
    "coupang": CoupangApprovalEvidence,
    "naver": NaverApprovalEvidence,
    "toss": TossApprovalEvidence,
}
INTENT_TABLE = "product_automation_channel_publish_intents"


def evidence(channel: str, **overrides: object) -> object:
    base = datetime(2026, 9, 19, tzinfo=UTC)
    fields = {
        "external_publish_approval": True,
        "external_publish_approved_at": base + timedelta(seconds=3),
        "artifact_digest": "a" * 64,
        "attempt_id": "attempt-1",
        "project_id": "project-1",
        "batch_id": "batch-1",
        "version": 1,
        "effective_from": base,
    }
    fields.update(overrides)
    return EVIDENCE_MODELS[channel](**fields)


def _open_db(tmp_path: Path, *, intents_table: bool = True) -> sqlite3.Connection:
    path = tmp_path / "dor.sqlite"
    db = sqlite3.connect(path)
    db.execute(
        """CREATE TABLE approval_records (
             product_id TEXT,batch_id TEXT,version INTEGER,effective_from TEXT,
             channel TEXT,approval_type TEXT,result TEXT,actor_role TEXT,
             recorded_at TEXT)"""
    )
    if intents_table:
        db.execute(
            f"""CREATE TABLE {INTENT_TABLE} (
                  project TEXT,batch TEXT,version INTEGER,effective_from TEXT,
                  channel TEXT,attempt_id TEXT,artifact_digest TEXT,
                  recorded_at TEXT,status TEXT)"""
        )
    return db


def _seed_approvals(db: sqlite3.Connection, value: object, channel: str) -> None:
    effective = value.effective_from.isoformat().replace("+00:00", "Z")
    for approval_type, recorded_at in (
        ("external_publish", value.external_publish_approved_at),
    ):
        db.execute(
            "INSERT INTO approval_records VALUES (?,?,?,?,?,?,?,?,?)",
            (
                value.project_id,
                value.batch_id,
                value.version,
                effective,
                channel,
                approval_type,
                "approved",
                "CEO",
                recorded_at.isoformat().replace("+00:00", "Z"),
            ),
        )
    db.commit()


def _seed_intent(
    db: sqlite3.Connection,
    value: object,
    channel: str,
    *,
    attempt_id: str | None = None,
    artifact_digest: str | None = None,
    status: str = "intent_claimed",
) -> None:
    effective = value.effective_from.isoformat().replace("+00:00", "Z")
    db.execute(
        f"INSERT INTO {INTENT_TABLE} VALUES (?,?,?,?,?,?,?,?,?)",
        (
            value.project_id,
            value.batch_id,
            value.version,
            effective,
            channel,
            attempt_id or value.attempt_id,
            artifact_digest or value.artifact_digest,
            "2026-09-19T00:00:10Z",
            status,
        ),
    )
    db.commit()


def _seeded_db(tmp_path: Path, channel: str) -> tuple[sqlite3.Connection, object]:
    db = _open_db(tmp_path)
    value = evidence(channel)
    _seed_approvals(db, value, channel)
    _seed_intent(db, value, channel)
    return db, value


@pytest.mark.parametrize("channel", CHANNELS)
def test_exact_tuple_with_claimed_intent_verifies(tmp_path: Path, channel: str) -> None:
    db, value = _seeded_db(tmp_path, channel)
    db.close()
    DorChannelApprovalVerifier(tmp_path / "dor.sqlite", channel=channel).verify(
        value, idempotency_key=value.artifact_digest
    )


def test_idempotency_key_must_equal_artifact_digest(tmp_path: Path) -> None:
    db, value = _seeded_db(tmp_path, "naver")
    db.close()
    with pytest.raises(ValueError, match="idempotency key"):
        DorChannelApprovalVerifier(tmp_path / "dor.sqlite", channel="naver").verify(
            value, idempotency_key="b" * 64
        )


def test_missing_intents_table_fails_closed(tmp_path: Path) -> None:
    db = _open_db(tmp_path, intents_table=False)
    value = evidence("coupang")
    _seed_approvals(db, value, "coupang")
    db.close()
    with pytest.raises(ValueError, match="publish intent"):
        DorChannelApprovalVerifier(tmp_path / "dor.sqlite", channel="coupang").verify(
            value, idempotency_key=value.artifact_digest
        )


def test_missing_intent_row_fails_closed(tmp_path: Path) -> None:
    db = _open_db(tmp_path)
    value = evidence("toss")
    _seed_approvals(db, value, "toss")
    db.close()
    with pytest.raises(ValueError, match="publish intent"):
        DorChannelApprovalVerifier(tmp_path / "dor.sqlite", channel="toss").verify(
            value, idempotency_key=value.artifact_digest
        )


def test_ambiguous_intent_rows_fail_closed(tmp_path: Path) -> None:
    db, value = _seeded_db(tmp_path, "coupang")
    _seed_intent(db, value, "coupang")
    db.close()
    with pytest.raises(ValueError, match="publish intent"):
        DorChannelApprovalVerifier(tmp_path / "dor.sqlite", channel="coupang").verify(
            value, idempotency_key=value.artifact_digest
        )


@pytest.mark.parametrize(
    "overrides",
    (
        {"channel": "toss"},
        {"attempt_id": "attempt-2"},
        {"artifact_digest": "c" * 64},
        {"status": "completed"},
    ),
    ids=("wrong_channel", "wrong_attempt", "wrong_digest", "not_claimed"),
)
def test_mismatched_intent_rows_fail_closed(tmp_path: Path, overrides: dict) -> None:
    db = _open_db(tmp_path)
    value = evidence("coupang")
    _seed_approvals(db, value, "coupang")
    row = {
        "channel": "coupang",
        "attempt_id": value.attempt_id,
        "artifact_digest": value.artifact_digest,
        "status": "intent_claimed",
    }
    row.update(overrides)
    _seed_intent(
        db,
        value,
        row["channel"],
        attempt_id=row["attempt_id"],
        artifact_digest=row["artifact_digest"],
        status=row["status"],
    )
    db.close()
    with pytest.raises(ValueError, match="publish intent"):
        DorChannelApprovalVerifier(tmp_path / "dor.sqlite", channel="coupang").verify(
            value, idempotency_key=value.artifact_digest
        )


def test_intent_version_tuple_mismatch_fails_closed(tmp_path: Path) -> None:
    db = _open_db(tmp_path)
    value = evidence("naver", version=2, attempt_id="attempt-2")
    _seed_approvals(db, value, "naver")
    _seed_intent(db, evidence("naver"), "naver")
    db.close()
    with pytest.raises(ValueError, match="publish intent"):
        DorChannelApprovalVerifier(tmp_path / "dor.sqlite", channel="naver").verify(
            value, idempotency_key=value.artifact_digest
        )


def test_missing_approval_type_fails_closed(tmp_path: Path) -> None:
    db = _open_db(tmp_path)
    value = evidence("naver")
    _seed_intent(db, value, "naver")
    db.close()
    with pytest.raises(ValueError, match="approval record"):
        DorChannelApprovalVerifier(tmp_path / "dor.sqlite", channel="naver").verify(
            value, idempotency_key=value.artifact_digest
        )


def test_latest_rejected_approval_revokes_evidence(tmp_path: Path) -> None:
    db, value = _seeded_db(tmp_path, "coupang")
    db.execute(
        "INSERT INTO approval_records VALUES (?,?,?,?,?,?,?,?,?)",
        (
            value.project_id,
            value.batch_id,
            value.version,
            value.effective_from.isoformat().replace("+00:00", "Z"),
            "coupang",
            "external_publish",
            "rejected",
            "CEO",
            "2026-09-19T00:00:04Z",
        ),
    )
    db.commit()
    db.close()
    with pytest.raises(ValueError, match="approval record"):
        DorChannelApprovalVerifier(tmp_path / "dor.sqlite", channel="coupang").verify(
            value, idempotency_key=value.artifact_digest
        )


def test_non_ceo_actor_fails_closed(tmp_path: Path) -> None:
    db = _open_db(tmp_path)
    value = evidence("toss")
    _seed_approvals(db, value, "toss")
    db.execute(
        "UPDATE approval_records SET actor_role='SYSTEM' WHERE approval_type='external_publish'"
    )
    db.commit()
    _seed_intent(db, value, "toss")
    db.close()
    with pytest.raises(ValueError, match="approval record"):
        DorChannelApprovalVerifier(tmp_path / "dor.sqlite", channel="toss").verify(
            value, idempotency_key=value.artifact_digest
        )


def test_recorded_at_mismatch_fails_closed(tmp_path: Path) -> None:
    db = _open_db(tmp_path)
    value = evidence("coupang")
    _seed_approvals(db, value, "coupang")
    db.execute(
        "UPDATE approval_records SET recorded_at='2026-09-19T01:00:00Z' "
        "WHERE approval_type='external_publish'"
    )
    db.commit()
    _seed_intent(db, value, "coupang")
    db.close()
    with pytest.raises(ValueError, match="does not match evidence"):
        DorChannelApprovalVerifier(tmp_path / "dor.sqlite", channel="coupang").verify(
            value, idempotency_key=value.artifact_digest
        )


def test_approvals_scoped_to_the_verifier_channel(tmp_path: Path) -> None:
    db = _open_db(tmp_path)
    value = evidence("coupang")
    _seed_approvals(db, value, "naver")
    _seed_intent(db, value, "coupang")
    db.close()
    with pytest.raises(ValueError, match="approval record"):
        DorChannelApprovalVerifier(tmp_path / "dor.sqlite", channel="coupang").verify(
            value, idempotency_key=value.artifact_digest
        )


def test_symlinked_database_is_rejected(tmp_path: Path) -> None:
    db, value = _seeded_db(tmp_path, "naver")
    db.close()
    link = tmp_path / "linked.sqlite"
    link.symlink_to(tmp_path / "dor.sqlite")
    with pytest.raises(ValueError, match="invalid"):
        DorChannelApprovalVerifier(link, channel="naver").verify(
            value, idempotency_key=value.artifact_digest
        )


def test_missing_database_file_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(OSError):
        DorChannelApprovalVerifier(
            tmp_path / "absent.sqlite", channel="naver"
        ).verify(evidence("naver"), idempotency_key="a" * 64)
