"""commerce_get_mall_listing_status — 몰 등록 상태 읽기 (RV-20261009 CONTRACT 3절).

DOR 의 「몰 상태 다시 확인」이 부르는 읽기 전용 도구. 토스 `list_products`·`get_product_v2`,
네이버 `search_products`·`get_channel_product` 만 쓴다 — 등록·수정·삭제 경로는 없다.

찾기: 최신 상품 목록 최대 3쪽(쪽당 50)을 훑어, 후보 번호마다 sha256(artifact:번호) 가
product_digests 에 있으면 digest 일치. 토스는 그다음 management_codes 가 있을 때만
후보마다 get_product_v2 의 stocks[].managementCode 와 겹치는지 본다(상세 GET 최대 20번).
일치한 상품 하나만 상태를 읽는다.

상품 번호 원문·응답 원문·주소·연락처는 결과에 넣지 않는다 — 번호는 digest 만,
상태는 2절 열거값만 돌려준다. 클라이언트 오류(HTTP·시간 초과)는 예외를 밖으로 던지지 않고
status "incomplete"·reasons ["provider_unavailable"]·listing null 로 돌린다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any, Literal, Protocol

from pydantic import Field

from .models.common import CanonicalModel
from .publishing.deferred_registration import provider_id_digest
from .security import is_agent_safe_value

Hex64 = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
ManagementCode = Annotated[str, Field(min_length=1, max_length=100)]

_LIST_PAGE_LIMIT = 3
_LIST_PAGE_SIZE = 50
_DETAIL_GET_LIMIT = 20
_REJECTION_LIMIT = 5
_REJECTION_MESSAGE_MAX = 500
_INSPECTION_REQUESTED_AT_MAX = 64

_TOSS_INSPECTION_STATUSES = frozenset({"LLM_INSPECTION_READY", "COMPLETE", "REJECT"})
_TOSS_EXPOSURE_STATUSES = frozenset(
    {"UNEXPOSURE", "EXPOSURE_WAITING", "EXPOSURE", "EXPOSURE_FINISHED"}
)
_NAVER_STATUS_TYPES = frozenset(
    {
        "WAIT",
        "SALE",
        "OUTOFSTOCK",
        "UNADMISSION",
        "REJECTION",
        "SUSPENSION",
        "CLOSE",
        "PROHIBITION",
        "DELETE",
    }
)
_NAVER_DISPLAY_TYPES = frozenset({"WAIT", "ON", "SUSPENSION"})
_NAVER_ON_SALE_STATUS = frozenset({"SALE", "OUTOFSTOCK"})
_NAVER_WAITING_STATUS = frozenset({"WAIT", "UNADMISSION"})
_NAVER_NOT_ON_SALE_STATUS = frozenset({"SUSPENSION", "CLOSE", "PROHIBITION", "DELETE"})

MallChannel = Literal["naver", "toss_store"]
MallState = Literal[
    "on_sale",
    "inspection_waiting",
    "inspection_rejected",
    "not_on_sale",
    "not_found",
    "unknown",
]


class MallListingMatch(CanonicalModel):
    """Which lookup key found the listing; product number stays digested."""

    kind: Literal["management_code", "digest", "none"]
    product_digest: Hex64 | None = None


class MallListingRejection(CanonicalModel):
    """토스 rejectionReasons 의 title·message 만 — 같은 내용은 한 번, message 500자."""

    title: str = Field(min_length=1, max_length=300)
    message: str = Field(min_length=1, max_length=_REJECTION_MESSAGE_MAX)


class MallListing(CanonicalModel):
    """2절 상태 낱말 + 몰 열거값만 — 원문 칸은 절대 싣지 않는다."""

    state: MallState
    provider_status: dict[str, str] = Field(default_factory=dict, max_length=4)
    rejection_reasons: tuple[MallListingRejection, ...] = Field(
        default=(), max_length=_REJECTION_LIMIT
    )
    last_inspection_requested_at: str | None = Field(
        default=None, max_length=_INSPECTION_REQUESTED_AT_MAX
    )


class MallListingStatusResult(CanonicalModel):
    schema_version: Literal["1.0"] = "1.0"
    channel: MallChannel
    status: Literal["complete", "incomplete"]
    match: MallListingMatch
    listing: MallListing | None = None
    candidates_scanned: int = Field(ge=0)
    reasons: tuple[str, ...] = Field(default=(), max_length=10)


class _TossListingClient(Protocol):
    async def list_products(
        self, *, page_size: int, cursor: str | None = None
    ) -> Any: ...

    async def get_product_v2(self, product_id: int) -> dict[str, Any]: ...


class _NaverListingClient(Protocol):
    async def search_products(self, *, page: int, size: int) -> dict[str, Any]: ...

    async def get_channel_product(self, *, channel_product_no: int) -> dict[str, Any]: ...


@dataclass(frozen=True)
class _NaverCandidate:
    channel_no: int
    origin_no: int | None


def _positive_int(value: object) -> int | None:
    if type(value) is int and 0 < value <= 2**63 - 1:
        return value
    if isinstance(value, str) and value.isdigit() and 0 < int(value) <= 2**63 - 1:
        return int(value)
    return None


def _incomplete(channel: str, scanned: int) -> MallListingStatusResult:
    return MallListingStatusResult(
        channel=channel,  # type: ignore[arg-type]
        status="incomplete",
        match=MallListingMatch(kind="none"),
        listing=None,
        candidates_scanned=scanned,
        reasons=("provider_unavailable",),
    )


def _digest_hit(number: int, artifacts: tuple[str, ...], wanted: frozenset[str]) -> bool:
    return any(provider_id_digest(artifact, number) in wanted for artifact in artifacts)


async def _collect_toss_candidates(client: _TossListingClient, out: list[int]) -> None:
    seen: set[int] = set()
    cursor: str | None = None
    for _ in range(_LIST_PAGE_LIMIT):
        page = await client.list_products(page_size=_LIST_PAGE_SIZE, cursor=cursor)
        rows = getattr(page, "rows", None)
        if not isinstance(rows, (list, tuple)):
            raise ValueError("toss product page shape is invalid")
        for row in rows:
            product_id = _positive_int(row.get("id")) if isinstance(row, dict) else None
            if product_id is not None and product_id not in seen:
                seen.add(product_id)
                out.append(product_id)
        cursor = getattr(page, "next_cursor", None)
        if cursor is None:
            break


def _toss_management_codes(row: Any) -> frozenset[str]:
    stocks = row.get("stocks") if isinstance(row, dict) else None
    if not isinstance(stocks, list):
        return frozenset()
    return frozenset(
        code
        for stock in stocks
        if isinstance(stock, dict)
        for code in (stock.get("managementCode"),)
        if isinstance(code, str) and code
    )


def _toss_rejections(value: Any) -> tuple[MallListingRejection, ...]:
    if not isinstance(value, list):
        return ()
    out: list[MallListingRejection] = []
    seen: set[tuple[str, str]] = set()
    for entry in value:
        if not isinstance(entry, dict):
            continue
        title, message = entry.get("title"), entry.get("message")
        if (
            not isinstance(title, str)
            or not title.strip()
            or not isinstance(message, str)
            or not message.strip()
        ):
            continue
        title, message = title.strip()[:300], message.strip()[:_REJECTION_MESSAGE_MAX]
        if (title, message) in seen or not (
            is_agent_safe_value(title) and is_agent_safe_value(message)
        ):
            continue
        seen.add((title, message))
        out.append(MallListingRejection(title=title, message=message))
        if len(out) >= _REJECTION_LIMIT:
            break
    return tuple(out)


def _toss_listing(row: Any) -> MallListing:
    if not isinstance(row, dict):
        row = {}
    inspection = row.get("inspectionStatus")
    exposure = row.get("exposureStatus")
    provider_status: dict[str, str] = {}
    if inspection in _TOSS_INSPECTION_STATUSES:
        provider_status["inspectionStatus"] = inspection
    if exposure in _TOSS_EXPOSURE_STATUSES:
        provider_status["exposureStatus"] = exposure
    if inspection == "REJECT":
        state: MallState = "inspection_rejected"
    elif inspection == "COMPLETE":
        if exposure == "EXPOSURE":
            state = "on_sale"
        elif exposure == "EXPOSURE_WAITING":
            state = "inspection_waiting"
        elif exposure in {"UNEXPOSURE", "EXPOSURE_FINISHED"}:
            state = "not_on_sale"
        else:
            state = "unknown"
    elif inspection == "LLM_INSPECTION_READY":
        state = "inspection_waiting"
    else:
        state = "unknown"
    requested_at = row.get("lastInspectionRequestedAt")
    return MallListing(
        state=state,
        provider_status=provider_status,
        rejection_reasons=_toss_rejections(row.get("rejectionReasons")),
        last_inspection_requested_at=(
            requested_at
            if isinstance(requested_at, str)
            and len(requested_at) <= _INSPECTION_REQUESTED_AT_MAX
            and is_agent_safe_value(requested_at)
            else None
        ),
    )


async def _collect_naver_candidates(
    client: _NaverListingClient, out: list[_NaverCandidate]
) -> None:
    seen: set[int] = set()
    for page_no in range(1, _LIST_PAGE_LIMIT + 1):
        payload = await client.search_products(page=page_no, size=_LIST_PAGE_SIZE)
        contents = payload.get("contents") if isinstance(payload, dict) else None
        if not isinstance(contents, list):
            raise ValueError("naver product search page shape is invalid")
        for content in contents:
            rows = content.get("channelProducts") if isinstance(content, dict) else None
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                channel_no = _positive_int(row.get("channelProductNo"))
                if channel_no is None or channel_no in seen:
                    continue
                seen.add(channel_no)
                origin_no = _positive_int(row.get("originProductNo"))
                if origin_no is None:
                    origin_no = _positive_int(content.get("originProductNo"))
                out.append(_NaverCandidate(channel_no=channel_no, origin_no=origin_no))
        if payload.get("last") is not False:
            break


def _naver_listing(row: Any) -> MallListing:
    origin = row.get("originProduct") if isinstance(row, dict) else None
    channel_row = row.get("smartstoreChannelProduct") if isinstance(row, dict) else None
    status_type = origin.get("statusType") if isinstance(origin, dict) else None
    display = (
        channel_row.get("channelProductDisplayStatusType")
        if isinstance(channel_row, dict)
        else None
    )
    provider_status: dict[str, str] = {}
    if status_type in _NAVER_STATUS_TYPES:
        provider_status["statusType"] = status_type
    if display in _NAVER_DISPLAY_TYPES:
        provider_status["channelProductDisplayStatusType"] = display
    if status_type in _NAVER_ON_SALE_STATUS and display == "ON":
        state: MallState = "on_sale"
    elif status_type in _NAVER_WAITING_STATUS:
        state = "inspection_waiting"
    elif status_type == "REJECTION":
        state = "inspection_rejected"
    elif status_type in _NAVER_NOT_ON_SALE_STATUS or display == "SUSPENSION":
        state = "not_on_sale"
    else:
        state = "unknown"
    return MallListing(state=state, provider_status=provider_status)


async def read_mall_listing_status(
    channel: MallChannel,
    *,
    toss_client: _TossListingClient | None,
    naver_client: _NaverListingClient | None,
    artifact_digests: tuple[str, ...] = (),
    product_digests: tuple[str, ...] = (),
    management_codes: tuple[str, ...] = (),
) -> MallListingStatusResult:
    """Read one mall listing state; never emit raw product numbers or payloads."""
    client = toss_client if channel == "toss_store" else naver_client
    if client is None:
        return _incomplete(channel, 0)
    artifacts = tuple(artifact_digests)
    wanted = frozenset(product_digests)
    matched: int | None = None
    matched_number: int | None = None
    kind: Literal["management_code", "digest", "none"] = "none"
    listing: MallListing | None = None
    scanned: list[Any] = []
    try:
        if channel == "toss_store":
            candidates: list[int] = scanned
            await _collect_toss_candidates(client, candidates)
            if wanted and artifacts:
                matched = next(
                    (
                        product_id
                        for product_id in candidates
                        if _digest_hit(product_id, artifacts, wanted)
                    ),
                    None,
                )
                if matched is not None:
                    matched_number, kind = matched, "digest"
            detail: dict[str, Any] | None = None
            if matched is None and management_codes:
                wanted_codes = frozenset(management_codes)
                for product_id in candidates[:_DETAIL_GET_LIMIT]:
                    row = await client.get_product_v2(product_id)
                    if _toss_management_codes(row) & wanted_codes:
                        matched, kind, detail = product_id, "management_code", row
                        matched_number = product_id
                        break
            if matched is not None:
                if detail is None:
                    detail = await client.get_product_v2(matched)
                listing = _toss_listing(detail)
        else:
            naver_candidates: list[_NaverCandidate] = scanned
            await _collect_naver_candidates(client, naver_candidates)
            if wanted and artifacts:
                for candidate in naver_candidates:
                    hit = next(
                        (
                            number
                            for number in (candidate.channel_no, candidate.origin_no)
                            if number is not None
                            and _digest_hit(number, artifacts, wanted)
                        ),
                        None,
                    )
                    if hit is not None:
                        matched, kind = candidate.channel_no, "digest"
                        matched_number = hit
                        break
            if matched is not None:
                row = await client.get_channel_product(channel_product_no=matched)
                listing = _naver_listing(row)
    except Exception:
        return _incomplete(channel, len(scanned))
    return MallListingStatusResult(
        channel=channel,
        status="complete",
        match=MallListingMatch(
            kind=kind,
            product_digest=(
                provider_id_digest(artifacts[0], matched_number)
                if matched_number is not None and artifacts
                else None
            ),
        ),
        listing=listing,
        candidates_scanned=len(scanned),
        reasons=(),
    )


def register_mall_listing_status_tool(
    server: Any,
    *,
    toss_client: _TossListingClient | None,
    naver_client: _NaverListingClient | None,
    annotations: Any,
) -> None:
    @server.tool(annotations=annotations, structured_output=True)
    async def commerce_get_mall_listing_status(
        channel: MallChannel,
        artifact_digests: Annotated[tuple[Hex64, ...], Field(max_length=10)] = (),
        product_digests: Annotated[tuple[Hex64, ...], Field(max_length=20)] = (),
        management_codes: Annotated[
            tuple[ManagementCode, ...], Field(max_length=50)
        ] = (),
    ) -> MallListingStatusResult:
        """몰 등록 상태 읽기 (RV-20261009 CONTRACT 3절) — 읽기 전용.

        최신 상품 목록 최대 3쪽(쪽당 50)에서 artifact·product digest 또는
        management_codes(토스만, 상세 GET 최대 20번)로 상품 하나를 찾아
        2절 상태 낱말(on_sale·inspection_waiting·inspection_rejected·
        not_on_sale·unknown)로 돌려준다. 상품 번호 원문은 나가지 않는다.
        """
        return await read_mall_listing_status(
            channel,
            toss_client=toss_client,
            naver_client=naver_client,
            artifact_digests=tuple(artifact_digests),
            product_digests=tuple(product_digests),
            management_codes=tuple(management_codes),
        )
