"""Read-only paging of Coupang GENERAL (not RFM) display category tree."""

from __future__ import annotations

from typing import Annotated, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from .adapters.coupang.rg_category_pagination import (
    MAX_PAGE_SIZE,
    MAX_TOTAL_NODES,
    RgCategoryDriftError,
    RgCategoryIncompleteError,
    extract_category_nodes,
    paginate_rg_category_tree,
    validate_category_cursor,
)
from .security import assert_agent_safe_value


class GeneralCategoryTreeClient(Protocol):
    async def get_general_category_tree(self) -> object: ...


class GeneralCategoryNode(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    display_category_code: Annotated[str, Field(pattern=r"^[0-9]{1,20}$")]
    name: Annotated[str, Field(min_length=1, max_length=300)]
    status: Literal["ACTIVE", "READY", "DISABLED"]
    depth: Annotated[int, Field(ge=1, le=16)]
    parent_code: Annotated[str | None, Field(pattern=r"^[0-9]{1,20}$")] = None


class GeneralCategoryPage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    status: Literal["complete", "incomplete", "unavailable"]
    items: tuple[GeneralCategoryNode, ...] = Field(max_length=MAX_PAGE_SIZE)
    next_cursor: str | None = None
    total_count: int | None = Field(default=None, ge=0, le=MAX_TOTAL_NODES)
    source_endpoint: Literal["coupang:general-category-list"] | None = None
    reasons: tuple[
        Literal["not_configured", "provider_read_unavailable", "invalid_tree", "tree_drift"], ...
    ] = ()


async def general_category_page(
    client: GeneralCategoryTreeClient | None, *, page_size: int, cursor: str | None
) -> GeneralCategoryPage:
    if type(page_size) is not int or not 1 <= page_size <= MAX_PAGE_SIZE:
        raise ValueError("invalid category page size")
    validate_category_cursor(cursor)
    if client is None:
        return GeneralCategoryPage(status="unavailable", items=(), reasons=("not_configured",))
    try:
        payload = await client.get_general_category_tree()
        if not isinstance(payload, dict) or payload.get("code") != "SUCCESS":
            return GeneralCategoryPage(
                status="unavailable", items=(), reasons=("provider_read_unavailable",)
            )
        nodes = extract_category_nodes(payload)
        if not nodes:
            return GeneralCategoryPage(status="incomplete", items=(), reasons=("invalid_tree",))
        page = paginate_rg_category_tree(nodes, page_size=page_size, cursor=cursor)
        result = GeneralCategoryPage(
            status="complete",
            items=tuple(GeneralCategoryNode(**vars(item)) for item in page.items),
            next_cursor=page.next_cursor,
            total_count=page.total,
            source_endpoint="coupang:general-category-list",
        )
        assert_agent_safe_value(result)
        return result
    except RgCategoryDriftError:
        return GeneralCategoryPage(status="incomplete", items=(), reasons=("tree_drift",))
    except RgCategoryIncompleteError:
        return GeneralCategoryPage(status="incomplete", items=(), reasons=("invalid_tree",))
    except Exception:
        return GeneralCategoryPage(
            status="unavailable", items=(), reasons=("provider_read_unavailable",)
        )
