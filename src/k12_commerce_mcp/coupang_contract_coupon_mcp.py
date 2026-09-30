"""Independent Coupang FMS contract and download-coupon safe reads."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal

from .clients.coupang import COUPON_PATH, FMS_CONTRACT_PATH
from .models.common import CanonicalModel
from .security import assert_agent_safe_value

_MAX_ID = 2**63 - 1
_STAMP = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}$")


class ContractCouponPage(CanonicalModel):
    channel: Literal["coupang_general"] = "coupang_general"
    source_endpoint: str
    status: Literal["complete", "incomplete", "blocked", "unavailable", "invalid_request"]
    reasons: tuple[str, ...] = ()
    items: tuple[dict[str, Any], ...] = ()


def _page(
    endpoint: str, status: str, reason: str | None = None, item: dict | None = None
) -> ContractCouponPage:
    return ContractCouponPage.model_validate(
        {
            "source_endpoint": endpoint,
            "status": status,
            "reasons": [] if reason is None else [reason],
            "items": [] if item is None else [item],
        }
    )


def _integer(value: object, minimum: int = 0) -> bool:
    return type(value) is int and minimum <= value <= _MAX_ID


def _stamp(value: object) -> bool:
    if not isinstance(value, str) or _STAMP.fullmatch(value) is None:
        return False
    try:
        datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return False
    return True


def _safe_item(endpoint: str, item: dict) -> ContractCouponPage:
    page = _page(endpoint, "complete", item=item)
    try:
        assert_agent_safe_value(page)
    except ValueError:
        return _page(endpoint, "incomplete", "invalid_provider_shape")
    return page


async def read_fms_contract(client: Any | None, contract_id: object) -> ContractCouponPage:
    endpoint = "coupang:fms-contract"
    if not _integer(contract_id, 1):
        return _page(endpoint, "invalid_request", "invalid_request")
    if client is None:
        return _page(endpoint, "unavailable", "client_not_configured")
    try:
        payload = await client._get(
            FMS_CONTRACT_PATH.format(vendor_id=client.credentials.vendor_id),
            (("contractId", str(contract_id)),),
        )
    except Exception:
        return _page(endpoint, "unavailable", "provider_unavailable")
    if (
        not isinstance(payload, dict)
        or type(payload.get("code")) is not int
        or payload["code"] != 200
        or type(payload.get("httpStatus")) is not int
        or payload["httpStatus"] != 200
        or not isinstance(payload.get("data"), dict)
    ):
        return _page(endpoint, "incomplete", "invalid_provider_shape")
    data = payload["data"]
    if data.get("success") is not True or not isinstance(data.get("content"), dict):
        return _page(endpoint, "incomplete", "invalid_provider_shape")
    if any(data.get(key) is not None for key in ("pagination", "Pagination")):
        return _page(endpoint, "incomplete", "invalid_provider_shape")
    row = data["content"]
    if (
        not _integer(row.get("contractId"), 1)
        or row["contractId"] != contract_id
        or type(row.get("vendorContractId")) is not int
        or not -_MAX_ID <= row["vendorContractId"] <= _MAX_ID
        or any(
            not _integer(row.get(key))
            for key in ("sellerShareRatio", "coupangShareRatio", "gmvRatio")
        )
        or any(not _stamp(row.get(key)) for key in ("start", "end", "modifiedAt"))
        or row.get("type") not in ("CONTRACT_BASED", "NON_CONTRACT_BASED")
    ):
        return _page(endpoint, "incomplete", "invalid_provider_shape")
    return _safe_item(
        endpoint,
        {
            key: row[key]
            for key in (
                "contractId",
                "vendorContractId",
                "sellerShareRatio",
                "coupangShareRatio",
                "gmvRatio",
                "start",
                "end",
                "type",
                "modifiedAt",
            )
        },
    )


def block_fms_contract_list() -> ContractCouponPage:
    return _page("coupang:fms-contract-list", "blocked", "contract_list_envelope_uncontracted")


async def read_download_coupon(client: Any | None, coupon_id: object) -> ContractCouponPage:
    endpoint = "coupang:download-coupon"
    if (
        not isinstance(coupon_id, str)
        or re.fullmatch(r"[1-9][0-9]{0,18}", coupon_id) is None
        or int(coupon_id) > _MAX_ID
    ):
        return _page(endpoint, "invalid_request", "invalid_request")
    if client is None:
        return _page(endpoint, "unavailable", "client_not_configured")
    try:
        payload = await client._get(COUPON_PATH.format(coupon_id=coupon_id), ())
    except Exception:
        return _page(endpoint, "unavailable", "provider_unavailable")
    if not isinstance(payload, dict):
        return _page(endpoint, "incomplete", "invalid_provider_shape")
    if (
        not _integer(payload.get("couponId"), 1)
        or payload["couponId"] != int(coupon_id)
        or any(not _integer(payload.get(key)) for key in ("appliedOptionCount", "usageAmount"))
        or any(not _stamp(payload.get(key)) for key in ("startDate", "endDate"))
    ):
        return _page(endpoint, "incomplete", "invalid_provider_shape")
    return _safe_item(
        endpoint,
        {
            key: payload[key]
            for key in (
                "couponId",
                "appliedOptionCount",
                "usageAmount",
                "startDate",
                "endDate",
            )
        },
    )
