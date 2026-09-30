"""Claim and return service operations."""

from __future__ import annotations

from ..models import Channel, ErrorCode, ResultStatus, ReturnPageResult
from ..models.claims import ClaimKind


class ClaimsServiceMixin:
    async def get_returns(
        self,
        channel: Channel,
        *,
        page_size: int,
        cursor: str | None = None,
        kind: str | None = None,
    ) -> ReturnPageResult:
        if kind is not None:
            try:
                ClaimKind(kind)
            except ValueError:
                error = self._safe_error(ErrorCode.INVALID_REQUEST, retryable=False)
                return self._error_page(
                    ReturnPageResult,
                    channel,
                    ResultStatus.UNAVAILABLE,
                    error,
                )
        if channel is Channel.COUPANG_ROCKET_GROWTH:
            # The RG-specific official inventory does not establish a claim source.
            # This is not a missing credential and must never call the general
            # Coupang return endpoint on RG's behalf.
            error = self._safe_error(ErrorCode.SOURCE_UNPROVEN, retryable=False)
            return self._error_page(
                ReturnPageResult, channel, ResultStatus.UNSUPPORTED, error
            )
        return await self._get_page(
            channel,
            operation="get_returns",
            result_type=ReturnPageResult,
            page_size=page_size,
            cursor=cursor,
            adapter_arguments={"kind": kind} if kind is not None else None,
        )
