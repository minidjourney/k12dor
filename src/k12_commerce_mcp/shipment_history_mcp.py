"""Bounded, PII-free seller-shipment state history from Coupang's GET."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal, Protocol

from pydantic import Field

from .models.common import CanonicalModel
from .security import assert_agent_safe_value

_ID = re.compile(r"[1-9][0-9]{0,19}\Z")
_STATES = {"ACCEPT", "INSTRUCT", "DEPARTURE", "DELIVERING", "FINAL_DELIVERY", "NONE_TRACKING"}


class ShipmentHistoryClient(Protocol):
    async def get_order_sheet_history(self, shipment_box_id: str) -> tuple[dict, ...]: ...


class ShipmentEvent(CanonicalModel):
    state: str
    updated_at: str


class ShipmentHistory(CanonicalModel):
    status: Literal["complete", "incomplete", "unavailable", "invalid_request"]
    events: tuple[ShipmentEvent, ...] = Field(default=(), max_length=100)
    source_endpoint: Literal["coupang:order-sheet-history"] | None = None
    reasons: tuple[str, ...] = ()


async def shipment_history(
    client: ShipmentHistoryClient | None, shipment_box_id: str
) -> ShipmentHistory:
    if not isinstance(shipment_box_id, str) or not _ID.fullmatch(shipment_box_id):
        return ShipmentHistory(status="invalid_request", reasons=("invalid_shipment_box_id",))
    if client is None:
        return ShipmentHistory(status="unavailable", reasons=("client_not_configured",))
    try:
        rows = await client.get_order_sheet_history(shipment_box_id)
    except Exception:
        return ShipmentHistory(status="unavailable", reasons=("provider_unavailable",))
    if not isinstance(rows, tuple) or len(rows) > 100:
        return ShipmentHistory(status="incomplete", reasons=("invalid_provider_shape",))
    events = []
    for row in rows:
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("deliveryStatus"), str)
            or row["deliveryStatus"] not in _STATES
        ):
            return ShipmentHistory(status="incomplete", reasons=("invalid_provider_shape",))
        raw_time = row.get("updatedAt")
        try:
            stamp = datetime.fromisoformat(raw_time) if isinstance(raw_time, str) else None
        except ValueError:
            stamp = None
        if stamp is None or stamp.tzinfo is None:
            return ShipmentHistory(status="incomplete", reasons=("invalid_provider_shape",))
        events.append(ShipmentEvent(state=row["deliveryStatus"], updated_at=stamp.isoformat()))
    result = ShipmentHistory(
        status="complete", events=tuple(events), source_endpoint="coupang:order-sheet-history"
    )
    assert_agent_safe_value(result)
    return result
