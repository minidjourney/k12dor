"""Bounded, one-depth general Coupang category detail projection."""

from __future__ import annotations

import re
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from .security import assert_agent_safe_value, safe_display_value


class GeneralCategoryClient(Protocol):
    async def get_display_category(self, display_category_code: str) -> dict[str, Any] | None: ...


class GeneralCategoryChild(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    category_code: str
    name: str
    status: Literal["ACTIVE", "READY", "DISABLED"]


class GeneralCategoryDetail(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    status: Literal["complete", "incomplete", "unavailable", "invalid_request"]
    category_code: str | None = None
    name: str | None = None
    category_status: Literal["ACTIVE", "READY", "DISABLED"] | None = None
    children: tuple[GeneralCategoryChild, ...] = Field(default=(), max_length=100)
    reasons: tuple[str, ...] = ()


def _code(value: Any) -> str | None:
    if isinstance(value, int) and not isinstance(value, bool):
        value = str(value)
    return value if isinstance(value, str) and re.fullmatch(r"[0-9]{1,20}", value) else None


def _child(value: Any) -> GeneralCategoryChild | None:
    if not isinstance(value, dict):
        return None
    code = _code(value.get("displayItemCategoryCode", value.get("displayCategoryCode")))
    name = value.get("name")
    status = value.get("status")
    if (
        code is None
        or not isinstance(name, str)
        or not safe_display_value(name)
        or status not in {"ACTIVE", "READY", "DISABLED"}
    ):
        return None
    return GeneralCategoryChild(category_code=code, name=name, status=status)


async def get_general_category_detail(
    client: GeneralCategoryClient | None, code: str
) -> GeneralCategoryDetail:
    if _code(code) != code:
        return GeneralCategoryDetail(status="invalid_request", reasons=("invalid_category_code",))
    if client is None:
        return GeneralCategoryDetail(status="unavailable", reasons=("client_not_configured",))
    try:
        data = await client.get_display_category(code)
    except Exception:
        return GeneralCategoryDetail(status="unavailable", reasons=("provider_unavailable",))
    invalid = GeneralCategoryDetail(status="incomplete", reasons=("invalid_provider_shape",))
    if not isinstance(data, dict):
        return invalid
    category = _child(data)
    children = data.get("child")
    if (
        category is None
        or category.category_code != code
        or not isinstance(children, list)
        or len(children) > 100
    ):
        return invalid
    projected = tuple(_child(item) for item in children)
    if any(item is None for item in projected):
        return invalid
    result = GeneralCategoryDetail(
        status="complete",
        category_code=category.category_code,
        name=category.name,
        category_status=category.status,
        children=projected,
    )
    try:
        assert_agent_safe_value(result)
    except ValueError:
        return GeneralCategoryDetail(status="incomplete", reasons=("unsafe_provider_value",))
    return result
