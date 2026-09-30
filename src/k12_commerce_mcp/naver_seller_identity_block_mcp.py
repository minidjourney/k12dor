"""Local-only deny records for seller identity, address, and channel GETs."""

from __future__ import annotations

from typing import Literal

from .models.common import CanonicalModel


class NaverSellerIdentityBlock(CanonicalModel):
    channel: Literal["naver"] = "naver"
    operation_id: Literal[
        "get-account-info-by-account-no-sellers",
        "get-address-sellers",
        "get-channels-by-account-no-sellers",
    ]
    status: Literal["blocked", "invalid_request"]
    reasons: tuple[str, ...]
    item: None = None


def _block(operation: str, reason: str, valid: bool = True) -> NaverSellerIdentityBlock:
    return NaverSellerIdentityBlock.model_validate(
        {
            "operation_id": operation,
            "status": "blocked" if valid else "invalid_request",
            "reasons": [reason if valid else "invalid_request"],
            "item": None,
        }
    )


def block_seller_account() -> NaverSellerIdentityBlock:
    """No provider call, since account identifiers have no approved projection."""
    return _block(
        "get-account-info-by-account-no-sellers", "account_identifier_projection_unapproved"
    )


def block_seller_address(address_book_no: object) -> NaverSellerIdentityBlock:
    """No provider call for /v1/seller/addressbooks/:addressBookNo."""
    return _block(
        "get-address-sellers",
        "pii_projection_unapproved",
        type(address_book_no) is int and 0 < address_book_no <= 2**63 - 1,
    )


def block_seller_channels() -> NaverSellerIdentityBlock:
    """No provider call for channel/account-linked response."""
    return _block("get-channels-by-account-no-sellers", "response_projection_unapproved")
