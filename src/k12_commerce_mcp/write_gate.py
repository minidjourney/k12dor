"""Fail-closed gate for marketplace registration writes."""

from __future__ import annotations

from enum import StrEnum

REGISTRATION_DEFERRED_REASON = "registration_deferred_until_detail_page_automation"


class RegistrationDeferredError(ValueError):
    """Raised when a registration write runs before detail-page automation opens it."""


class DeferredWrite(StrEnum):
    """Marketplace writes reserved for the detail-page automation batch."""

    COUPANG_SELLER_PRODUCT_CREATE = "coupang_seller_product_create"
    COUPANG_SELLER_PRODUCT_UPDATE = "coupang_seller_product_update"
    NAVER_PRODUCT_CREATE = "naver_product_create"
    TOSS_PRODUCT_REGISTER = "toss_product_register"


DEFERRED_WRITE_NAMES: tuple[str, ...] = tuple(write.value for write in DeferredWrite)

# CEO 2026-09-19: only these three product-registration writes may unseal, and
# only after approval evidence validates inside the publisher. Every other
# mutation (for example COUPANG_SELLER_PRODUCT_UPDATE) stays deferred.
APPROVAL_RELEASED_WRITES: tuple[DeferredWrite, ...] = (
    DeferredWrite.COUPANG_SELLER_PRODUCT_CREATE,
    DeferredWrite.NAVER_PRODUCT_CREATE,
    DeferredWrite.TOSS_PRODUCT_REGISTER,
)
APPROVAL_RELEASED_WRITE_NAMES: tuple[str, ...] = tuple(
    write.value for write in APPROVAL_RELEASED_WRITES
)


def registration_enabled(write: DeferredWrite | None = None) -> bool:
    """True only for the three CEO-released product-registration writes.

    There is no environment or runtime override; released writes still require
    validated approval evidence before any provider client call runs.
    """
    return write in APPROVAL_RELEASED_WRITES


def assert_registration_enabled(write: DeferredWrite | None = None) -> None:
    """Raise when a write is attempted while the gate is closed for it."""
    if not registration_enabled(write):
        raise RegistrationDeferredError(REGISTRATION_DEFERRED_REASON)
