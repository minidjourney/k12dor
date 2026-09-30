"""Privacy-safe helpers for bounded live verification."""

from __future__ import annotations

from typing import Any

from .models import Channel, ResultStatus


async def collect_inventory_summary(
    service: Any,
    channel: Channel,
    *,
    page_size: int = 100,
    max_pages: int = 1000,
) -> dict[str, object]:
    """Exhaust an inventory cursor and return no item identifiers."""
    cursor: str | None = None
    seen_cursors: set[str] = set()
    quantities: dict[tuple[str, str], int] = {}
    error_types: set[str] = set()
    pages_completed = 0
    terminal_cursor_null = False
    identity_complete = True

    while pages_completed < max_pages:
        page = await service.get_inventory(channel, page_size=page_size, cursor=cursor)
        pages_completed += 1
        error_types.update(page.reasons)
        error_types.update(error.code.value for error in page.errors)
        if "invalid_inventory_row" in page.reasons:
            identity_complete = False
        for item in page.items:
            error_types.update(item.completeness.reasons)
            external_identity = item.external_option_id or item.external_product_id
            if external_identity is None:
                identity_complete = False
                error_types.add("missing_inventory_identity")
                continue
            identity = (item.inventory_source.value, external_identity)
            previous = quantities.get(identity)
            if previous is not None and previous != item.quantity:
                identity_complete = False
                error_types.add("conflicting_inventory_quantity")
                continue
            quantities.setdefault(identity, item.quantity)

        issued = page.next_cursor
        if issued is None:
            terminal_cursor_null = True
            break
        if issued in seen_cursors:
            error_types.add("repeated_cursor")
            break
        seen_cursors.add(issued)
        cursor = issued
    else:
        error_types.add("page_limit_exceeded")

    usable = terminal_cursor_null and identity_complete and page.status not in {
        ResultStatus.UNAVAILABLE,
        ResultStatus.UNSUPPORTED,
    }
    return {
        "channel": channel.value,
        "pages_completed": pages_completed,
        "terminal_cursor_null": terminal_cursor_null,
        "item_count": len(quantities) if usable else None,
        "quantity_sum": sum(quantities.values()) if usable else None,
        "status": "complete" if usable and not error_types else "incomplete",
        "error_types": sorted(error_types),
    }
