"""Bounded safe projection for unauthenticated 11st public category reads."""
from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from .clients.elevenst import ElevenstClient
from .security import assert_agent_safe_value

MAX_PAGE_SIZE = 100
_CURSOR = re.compile(r"(?:0|[1-9][0-9]{0,4})\Z")

class ElevenstPublicCategoryItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    category_id: Annotated[str, Field(pattern=r"^[0-9]{1,20}$")]
    parent_category_id: Annotated[str, Field(pattern=r"^[0-9]{1,20}$")]
    name: Annotated[str, Field(min_length=1, max_length=300)]
    level: Annotated[int, Field(ge=1, le=9999)]
    has_children: bool | None = None
    required: bool | None = None
    cert_type: Literal["1", "2"] | None = None

class ElevenstPublicCategoryPage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    status: Literal["complete", "unavailable"]
    items: tuple[ElevenstPublicCategoryItem, ...] = Field(max_length=MAX_PAGE_SIZE)
    next_cursor: str | None = None
    total_count: int | None = Field(default=None, ge=0, le=50_000)
    source_endpoint: Literal[
        "11st:public-category-list", "11st:public-category-children"
    ] | None = None
    reasons: tuple[Literal["not_configured", "provider_read_unavailable"], ...] = ()

async def category_page(
    client: ElevenstClient | None,
    *,
    parent_category_id: str | None,
    cursor: str | None,
    page_size: int,
) -> ElevenstPublicCategoryPage:
    if client is None:
        return ElevenstPublicCategoryPage(
            status="unavailable", items=(), reasons=("not_configured",)
        )
    if cursor is not None and not _CURSOR.fullmatch(cursor):
        raise ValueError("invalid 11st category cursor")
    offset = int(cursor) if cursor is not None else 0
    try:
        rows = (
            await client.list_categories()
            if parent_category_id is None
            else await client.list_subcategories(parent_category_id)
        )
        selected = rows[offset : offset + page_size]
        items = tuple(
            ElevenstPublicCategoryItem(
                category_id=row["disp_no"],
                parent_category_id=row["parent_disp_no"],
                name=row["disp_nm"],
                level=row["depth"],
                has_children=(row["leaf_yn"] == "N") if "leaf_yn" in row else None,
                required=(row["required_yn"] == "Y") if "required_yn" in row else None,
                cert_type=row.get("cert_type"),
            )
            for row in selected
        )
        result = ElevenstPublicCategoryPage(
            status="complete", items=items,
            next_cursor=str(offset + page_size) if offset + page_size < len(rows) else None,
            total_count=len(rows),
            source_endpoint=(
                "11st:public-category-list"
                if parent_category_id is None
                else "11st:public-category-children"
            ),
        )
        assert_agent_safe_value(result)
        return result
    except Exception:
        # Do not leak upstream XML, network exception text, or synthetic raw data.
        return ElevenstPublicCategoryPage(
            status="unavailable", items=(), reasons=("provider_read_unavailable",)
        )
