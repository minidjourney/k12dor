"""Canonical marketplace claim and return records."""

from __future__ import annotations

from enum import StrEnum

from pydantic import AwareDatetime, Field

from .common import CanonicalModel, Channel, ClaimState, Completeness, Money, SourceEvidence


class ClaimKind(StrEnum):
    """Provider-verified claim kind; omitted when the provider did not supply one."""

    CANCEL = "cancel"
    RETURN = "return"
    EXCHANGE = "exchange"


class ClaimReturn(CanonicalModel):
    channel: Channel
    claim_ref: str = Field(min_length=1)
    order_ref: str = Field(min_length=1)
    state: ClaimState
    kind: ClaimKind | None = None
    quantity: int = Field(gt=0)
    requested_at: AwareDatetime
    completed_at: AwareDatetime | None = None
    refund_amount: Money | None = None
    completeness: Completeness
    source: SourceEvidence
