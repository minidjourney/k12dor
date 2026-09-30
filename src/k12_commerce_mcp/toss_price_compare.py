"""Safe, bounded Toss price-comparison read projection."""
from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from .adapters.base import AdapterAuthenticationError, AdapterRateLimitError, AdapterTimeoutError
from .clients.toss import TossShoppingClient
from .security import assert_agent_safe_value, safe_display_value


class TossPriceCompareItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    item_id: Annotated[str, Field(pattern=r"^[1-9][0-9]{0,18}$")]
    name: Annotated[str | None, Field(max_length=300)] = None
    option_name: Annotated[str | None, Field(max_length=300)] = None
    brand_name: Annotated[str | None, Field(max_length=300)] = None


class TossPriceComparePage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    status: Literal["complete", "unavailable"]
    items: tuple[TossPriceCompareItem, ...] = Field(max_length=100)
    next_cursor: str | None = None
    reason: Literal[
        "not_configured", "provider_authentication", "provider_rate_limit",
        "provider_timeout", "provider_read_unavailable",
    ] | None = None


def _safe_name(value: object) -> str | None:
    text = safe_display_value(value)
    if not text or len(text) > 300 or "<" in text or ">" in text:
        return None
    if re.search(r"(?i)(?:https?://|www\.|\b(?:data|javascript):)", text):
        return None
    return text


async def price_compare_page(
    client: TossShoppingClient | None, *, page_size: int, cursor: str | None
) -> TossPriceComparePage:
    if client is None:
        return TossPriceComparePage(status="unavailable", items=(), reason="not_configured")
    try:
        page = await client.list_price_compare_products(page_size=page_size, cursor=cursor)
        items = tuple(
            TossPriceCompareItem(
                item_id=str(row["itemId"]),
                name=_safe_name(row.get("name")),
                option_name=_safe_name(row.get("optionName")),
                brand_name=_safe_name(row.get("brandName")),
            )
            for row in page.rows
        )
        result = TossPriceComparePage(
            status="complete", items=items, next_cursor=page.next_cursor
        )
        assert_agent_safe_value(result)
        return result
    except AdapterAuthenticationError:
        reason = "provider_authentication"
    except AdapterRateLimitError:
        reason = "provider_rate_limit"
    except AdapterTimeoutError:
        reason = "provider_timeout"
    except Exception:
        # Never leak credentials, upstream response bodies, or provider exception text.
        reason = "provider_read_unavailable"
    return TossPriceComparePage(status="unavailable", items=(), reason=reason)
