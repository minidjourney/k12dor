"""Bounded safe projections for authenticated 11st seller reads."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from .adapters.base import AdapterAuthenticationError
from .clients.elevenst import ElevenstClient
from .clients.elevenst_seller import ElevenstSellerClient
from .security import assert_agent_safe_value

MAX_LIST_ROWS = 10_000
MAX_CATEGORY_ROWS = 50_000

ElevenstReadReason = Literal[
    "not_configured", "provider_read_unavailable", "authentication_failed"
]


class ElevenstPlace(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    addr_seq: Annotated[str, Field(pattern=r"^[0-9]{1,20}$")]
    name: Annotated[str, Field(max_length=100)] | None = None


class ElevenstSendCloseTemplate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    template_no: Annotated[str, Field(pattern=r"^[0-9]{1,20}$")]
    name: Annotated[str, Field(max_length=100)] | None = None
    send_type_code: Literal["01", "02", "03"] | None = None


class ElevenstRegistrationOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    status: Literal["complete", "unavailable"]
    outbound_places: tuple[ElevenstPlace, ...] = Field(
        default=(), max_length=MAX_LIST_ROWS
    )
    return_places: tuple[ElevenstPlace, ...] = Field(
        default=(), max_length=MAX_LIST_ROWS
    )
    send_close_templates: tuple[ElevenstSendCloseTemplate, ...] = Field(
        default=(), max_length=MAX_LIST_ROWS
    )
    reasons: tuple[ElevenstReadReason, ...] = ()


class ElevenstProductSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    product_no: Annotated[str, Field(pattern=r"^[0-9]{1,20}$")]
    sale_status_code: Annotated[str, Field(pattern=r"^[0-9]{3}$")] | None = None
    category_no: Annotated[str, Field(pattern=r"^[0-9]{1,20}$")] | None = None
    sale_price: Annotated[int, Field(ge=0, le=999_999_999)] | None = None
    seller_product_code: Annotated[str, Field(max_length=100)] | None = None


class ElevenstProductLookup(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    status: Literal["complete", "not_found", "unavailable"]
    product: ElevenstProductSummary | None = None
    reasons: tuple[ElevenstReadReason, ...] = ()


class ElevenstLeafCategory(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    category_id: Annotated[str, Field(pattern=r"^[0-9]{1,20}$")]
    parent_category_id: Annotated[str, Field(pattern=r"^[0-9]{1,20}$")]
    name: Annotated[str, Field(min_length=1, max_length=300)]
    level: Annotated[int, Field(ge=1, le=9999)]
    is_leaf: bool


class ElevenstCategoryList(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    status: Literal["complete", "unavailable"]
    items: tuple[ElevenstLeafCategory, ...] = Field(
        default=(), max_length=MAX_CATEGORY_ROWS
    )
    total_count: Annotated[int, Field(ge=0, le=MAX_CATEGORY_ROWS)] | None = None
    reasons: tuple[ElevenstReadReason, ...] = ()


def _reason(exc: Exception) -> ElevenstReadReason:
    if isinstance(exc, AdapterAuthenticationError):
        return "authentication_failed"
    return "provider_read_unavailable"


async def registration_options(
    client: ElevenstSellerClient | None,
) -> ElevenstRegistrationOptions:
    """Read the outbound/return places and send-close templates once each."""
    if client is None:
        return ElevenstRegistrationOptions(
            status="unavailable", reasons=("not_configured",)
        )
    try:
        outbound = await client.list_outbound_places()
        inbound = await client.list_return_places()
        templates = await client.list_send_close_templates()
        result = ElevenstRegistrationOptions(
            status="complete",
            outbound_places=tuple(ElevenstPlace(**row) for row in outbound),
            return_places=tuple(ElevenstPlace(**row) for row in inbound),
            send_close_templates=tuple(
                ElevenstSendCloseTemplate(**row) for row in templates
            ),
        )
        assert_agent_safe_value(result)
        return result
    except Exception as exc:
        # Never leak upstream XML, network exception text, or the API key.
        return ElevenstRegistrationOptions(
            status="unavailable", reasons=(_reason(exc),)
        )


async def product_lookup(
    client: ElevenstSellerClient | None, product_no: str
) -> ElevenstProductLookup:
    """Read one seller product summary; not_found when the id is absent."""
    if client is None:
        return ElevenstProductLookup(
            status="unavailable", reasons=("not_configured",)
        )
    try:
        row = await client.get_product(product_no)
        if row is None:
            return ElevenstProductLookup(status="not_found")
        result = ElevenstProductLookup(
            status="complete", product=ElevenstProductSummary(**row)
        )
        assert_agent_safe_value(result)
        return result
    except Exception as exc:
        return ElevenstProductLookup(
            status="unavailable", reasons=(_reason(exc),)
        )


async def category_list(client: ElevenstClient | None) -> ElevenstCategoryList:
    """Read the public category list once and flag leaf categories."""
    if client is None:
        return ElevenstCategoryList(
            status="unavailable", items=(), reasons=("not_configured",)
        )
    try:
        rows = await client.list_categories()
        items = tuple(
            ElevenstLeafCategory(
                category_id=row["disp_no"],
                parent_category_id=row["parent_disp_no"],
                name=row["disp_nm"],
                level=row["depth"],
                is_leaf=row["leaf_yn"] == "Y",
            )
            for row in rows
        )
        result = ElevenstCategoryList(
            status="complete", items=items, total_count=len(items)
        )
        assert_agent_safe_value(result)
        return result
    except Exception as exc:
        return ElevenstCategoryList(
            status="unavailable", items=(), reasons=(_reason(exc),)
        )
