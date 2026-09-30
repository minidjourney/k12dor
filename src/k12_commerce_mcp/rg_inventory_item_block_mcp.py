"""Fail-closed RG inventory-item operation, distinct from the list and generic inventory."""

from __future__ import annotations

import re
from typing import Literal

from .models.common import CanonicalModel


class RgInventoryItemBlock(CanonicalModel):
    channel: Literal["coupang_rocket_growth"] = "coupang_rocket_growth"
    operation_id: Literal["rg_inventory_item"] = "rg_inventory_item"
    method: Literal["GET"] = "GET"
    official_rg_uri: Literal[True] = True
    rg_proof: Literal[False] = False
    shared_uri_promoted: Literal[False] = False
    status: Literal["blocked", "invalid_request"]
    reasons: tuple[str, ...]
    items: tuple[dict[str, str], ...] = ()


def block_rg_inventory_item(vendor_item_id: object) -> RgInventoryItemBlock:
    """Never dispatch the contradictory rg/inventory/summaries single-item GET."""
    valid = (
        isinstance(vendor_item_id, str)
        and re.fullmatch(r"[1-9][0-9]{0,18}", vendor_item_id) is not None
        and int(vendor_item_id) <= 2**63 - 1
    )
    return RgInventoryItemBlock.model_validate(
        {
            "status": "blocked" if valid else "invalid_request",
            "reasons": (
                ["inventory_envelope_uncontracted", "vendor_item_type_uncontracted"]
                if valid
                else ["invalid_request"]
            ),
        }
    )
