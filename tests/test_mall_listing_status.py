from __future__ import annotations

import json
from typing import Any

from mcp import Client

from k12_commerce_mcp.clients.naver import NaverProviderError
from k12_commerce_mcp.clients.toss import TossShoppingPage, TossShoppingProviderError
from k12_commerce_mcp.mall_listing_status import read_mall_listing_status
from k12_commerce_mcp.publishing.deferred_registration import provider_id_digest
from k12_commerce_mcp.server import build_server

ARTIFACT = "a" * 64
ARTIFACT_B = "b" * 64
TOSS_PRODUCT_ID = 9871234560
TOSS_OTHER_ID = 9871234561
NAVER_CHANNEL_NO = 9812345671
NAVER_ORIGIN_NO = 9812345672


class FakeTossClient:
    """In-memory Toss listing/detail stub; no HTTP ever leaves the test."""

    def __init__(
        self,
        pages: tuple[TossShoppingPage, ...] = (),
        details: dict[int, dict[str, Any] | Exception] | None = None,
        default_detail: dict[str, Any] | None = None,
        list_error: Exception | None = None,
    ) -> None:
        self._pages = pages
        self._details = details or {}
        self._default_detail = default_detail
        self._list_error = list_error
        self.list_calls: list[tuple[int, str | None]] = []
        self.detail_calls: list[int] = []

    async def list_products(
        self, *, page_size: int, cursor: str | None = None
    ) -> TossShoppingPage:
        self.list_calls.append((page_size, cursor))
        if self._list_error is not None:
            raise self._list_error
        index = len(self.list_calls) - 1
        if index >= len(self._pages):
            return TossShoppingPage(rows=(), next_cursor=None)
        return self._pages[index]

    async def get_product_v2(self, product_id: int) -> dict[str, Any]:
        self.detail_calls.append(product_id)
        row = self._details.get(product_id, self._default_detail)
        if isinstance(row, Exception):
            raise row
        if row is None:
            raise TossShoppingProviderError("toss shopping product is missing")
        return row


class FakeNaverClient:
    """In-memory Naver search/detail stub; no HTTP ever leaves the test."""

    def __init__(
        self,
        pages: tuple[dict[str, Any], ...] = (),
        channel_products: dict[int, dict[str, Any] | Exception] | None = None,
        search_error: Exception | None = None,
    ) -> None:
        self._pages = pages
        self._channel_products = channel_products or {}
        self._search_error = search_error
        self.search_calls: list[int] = []
        self.channel_calls: list[int] = []

    async def search_products(self, *, page: int, size: int) -> dict[str, Any]:
        self.search_calls.append(page)
        if self._search_error is not None:
            raise self._search_error
        index = page - 1
        if index >= len(self._pages):
            return {"contents": [], "last": True, "page": page, "size": size}
        return self._pages[index]

    async def get_channel_product(self, *, channel_product_no: int) -> dict[str, Any]:
        self.channel_calls.append(channel_product_no)
        row = self._channel_products.get(channel_product_no)
        if isinstance(row, Exception):
            raise row
        if row is None:
            raise NaverProviderError("naver channel product is missing")
        return row


def _toss_page(*ids: int, next_cursor: str | None = None) -> TossShoppingPage:
    return TossShoppingPage(
        rows=tuple({"id": pid, "name": "상품"} for pid in ids),
        next_cursor=next_cursor,
    )


def _naver_page(
    *rows: dict[str, Any], last: bool = True
) -> dict[str, Any]:
    return {
        "contents": [{"channelProducts": list(rows)}],
        "last": last,
        "page": 1,
        "size": 50,
    }


async def test_toss_management_code_match_reports_inspection_rejected() -> None:
    reasons = [
        {"title": "상세 이미지 다운로드 실패", "message": "등록하신 상세 이미지의 다운로드에 실패"},
        {"title": "상세 이미지 다운로드 실패", "message": "등록하신 상세 이미지의 다운로드에 실패"},
        {"title": "옵션 정보 누락", "message": "필수 옵션 정보가 없습니다"},
    ]
    client = FakeTossClient(
        pages=(_toss_page(TOSS_OTHER_ID, TOSS_PRODUCT_ID),),
        details={
            TOSS_OTHER_ID: {
                "id": TOSS_OTHER_ID,
                "inspectionStatus": "COMPLETE",
                "exposureStatus": "EXPOSURE",
                "stocks": [{"managementCode": "OTHER-CODE"}],
            },
            TOSS_PRODUCT_ID: {
                "id": TOSS_PRODUCT_ID,
                "inspectionStatus": "REJECT",
                "exposureStatus": "UNEXPOSURE",
                "rejectionReasons": reasons,
                "lastInspectionRequestedAt": "2026-10-09T01:23:45",
                "stocks": [{"managementCode": "OPTION-REF-1"}],
            },
        },
    )

    result = await read_mall_listing_status(
        "toss_store",
        toss_client=client,
        naver_client=None,
        artifact_digests=(ARTIFACT,),
        management_codes=("OPTION-REF-1",),
    )

    assert result.status == "complete"
    assert result.match.kind == "management_code"
    assert result.match.product_digest == provider_id_digest(ARTIFACT, TOSS_PRODUCT_ID)
    assert client.detail_calls == [TOSS_OTHER_ID, TOSS_PRODUCT_ID]
    assert result.listing is not None
    assert result.listing.state == "inspection_rejected"
    assert result.listing.provider_status == {
        "inspectionStatus": "REJECT",
        "exposureStatus": "UNEXPOSURE",
    }
    # 같은 사유는 한 번만 — 3개 중복이 2개로 합쳐진다.
    assert [row.title for row in result.listing.rejection_reasons] == [
        "상세 이미지 다운로드 실패",
        "옵션 정보 누락",
    ]
    assert result.listing.last_inspection_requested_at == "2026-10-09T01:23:45"


async def test_toss_digest_match_reports_on_sale() -> None:
    client = FakeTossClient(
        pages=(_toss_page(TOSS_PRODUCT_ID),),
        details={
            TOSS_PRODUCT_ID: {
                "id": TOSS_PRODUCT_ID,
                "inspectionStatus": "COMPLETE",
                "exposureStatus": "EXPOSURE",
                "stocks": [{"managementCode": "OPTION-REF-1"}],
            }
        },
    )

    result = await read_mall_listing_status(
        "toss_store",
        toss_client=client,
        naver_client=None,
        artifact_digests=(ARTIFACT, ARTIFACT_B),
        product_digests=(provider_id_digest(ARTIFACT_B, TOSS_PRODUCT_ID),),
    )

    assert result.status == "complete"
    assert result.match.kind == "digest"
    assert result.match.product_digest == provider_id_digest(ARTIFACT, TOSS_PRODUCT_ID)
    assert client.detail_calls == [TOSS_PRODUCT_ID]
    assert result.listing is not None
    assert result.listing.state == "on_sale"
    assert result.listing.provider_status == {
        "inspectionStatus": "COMPLETE",
        "exposureStatus": "EXPOSURE",
    }


async def test_toss_no_match_returns_none_kind_and_null_listing() -> None:
    client = FakeTossClient(
        pages=(_toss_page(TOSS_PRODUCT_ID, TOSS_OTHER_ID),),
        default_detail={
            "inspectionStatus": "COMPLETE",
            "exposureStatus": "EXPOSURE",
            "stocks": [{"managementCode": "OTHER-CODE"}],
        },
    )

    result = await read_mall_listing_status(
        "toss_store",
        toss_client=client,
        naver_client=None,
        artifact_digests=(ARTIFACT,),
        product_digests=(provider_id_digest(ARTIFACT, 123),),
        management_codes=("OPTION-REF-1",),
    )

    assert result.status == "complete"
    assert result.match.kind == "none"
    assert result.match.product_digest is None
    assert result.listing is None
    assert result.candidates_scanned == 2
    assert client.detail_calls == [TOSS_PRODUCT_ID, TOSS_OTHER_ID]


async def test_toss_detail_get_is_capped_at_twenty() -> None:
    ids = list(range(9871200000, 9871200000 + 25))
    client = FakeTossClient(
        pages=(_toss_page(*ids),),
        default_detail={
            "inspectionStatus": "COMPLETE",
            "exposureStatus": "EXPOSURE",
            "stocks": [{"managementCode": "OTHER-CODE"}],
        },
    )

    result = await read_mall_listing_status(
        "toss_store",
        toss_client=client,
        naver_client=None,
        artifact_digests=(ARTIFACT,),
        management_codes=("OPTION-REF-1",),
    )

    assert result.status == "complete"
    assert result.match.kind == "none"
    assert len(client.detail_calls) == 20


async def test_naver_digest_match_reports_on_sale() -> None:
    client = FakeNaverClient(
        pages=(
            _naver_page(
                {
                    "channelProductNo": NAVER_CHANNEL_NO,
                    "originProductNo": NAVER_ORIGIN_NO,
                    "name": "상품",
                    "statusType": "SALE",
                }
            ),
        ),
        channel_products={
            NAVER_CHANNEL_NO: {
                "originProduct": {"statusType": "SALE"},
                "smartstoreChannelProduct": {
                    "channelProductNo": NAVER_CHANNEL_NO,
                    "channelProductDisplayStatusType": "ON",
                },
            }
        },
    )

    result = await read_mall_listing_status(
        "naver",
        toss_client=None,
        naver_client=client,
        artifact_digests=(ARTIFACT,),
        product_digests=(provider_id_digest(ARTIFACT, NAVER_CHANNEL_NO),),
    )

    assert result.status == "complete"
    assert result.match.kind == "digest"
    assert result.match.product_digest == provider_id_digest(ARTIFACT, NAVER_CHANNEL_NO)
    assert client.channel_calls == [NAVER_CHANNEL_NO]
    assert result.listing is not None
    assert result.listing.state == "on_sale"
    assert result.listing.provider_status == {
        "statusType": "SALE",
        "channelProductDisplayStatusType": "ON",
    }


async def test_naver_origin_number_digest_match_reports_inspection_waiting() -> None:
    client = FakeNaverClient(
        pages=(
            _naver_page(
                {
                    "channelProductNo": NAVER_CHANNEL_NO,
                    "originProductNo": NAVER_ORIGIN_NO,
                    "name": "상품",
                    "statusType": "WAIT",
                }
            ),
        ),
        channel_products={
            NAVER_CHANNEL_NO: {
                "originProduct": {"statusType": "WAIT"},
                "smartstoreChannelProduct": {
                    "channelProductNo": NAVER_CHANNEL_NO,
                    "channelProductDisplayStatusType": "WAIT",
                },
            }
        },
    )

    result = await read_mall_listing_status(
        "naver",
        toss_client=None,
        naver_client=client,
        artifact_digests=(ARTIFACT,),
        product_digests=(provider_id_digest(ARTIFACT, NAVER_ORIGIN_NO),),
    )

    assert result.match.kind == "digest"
    assert result.match.product_digest == provider_id_digest(ARTIFACT, NAVER_ORIGIN_NO)
    assert result.listing is not None
    assert result.listing.state == "inspection_waiting"


async def test_client_error_reports_incomplete_provider_unavailable() -> None:
    toss = FakeTossClient(list_error=TossShoppingProviderError("toss shopping HTTP 500"))
    result = await read_mall_listing_status(
        "toss_store",
        toss_client=toss,
        naver_client=None,
        artifact_digests=(ARTIFACT,),
    )
    assert result.status == "incomplete"
    assert result.reasons == ("provider_unavailable",)
    assert result.listing is None
    assert result.match.kind == "none"

    naver = FakeNaverClient(
        pages=(
            _naver_page({"channelProductNo": NAVER_CHANNEL_NO, "name": "상품"}),
        ),
        channel_products={NAVER_CHANNEL_NO: NaverProviderError("naver HTTP 500")},
    )
    result = await read_mall_listing_status(
        "naver",
        toss_client=None,
        naver_client=naver,
        artifact_digests=(ARTIFACT,),
        product_digests=(provider_id_digest(ARTIFACT, NAVER_CHANNEL_NO),),
    )
    assert result.status == "incomplete"
    assert result.reasons == ("provider_unavailable",)
    assert result.listing is None


async def test_result_never_contains_raw_product_numbers() -> None:
    client = FakeTossClient(
        pages=(_toss_page(TOSS_PRODUCT_ID),),
        details={
            TOSS_PRODUCT_ID: {
                "id": TOSS_PRODUCT_ID,
                "inspectionStatus": "REJECT",
                "exposureStatus": "UNEXPOSURE",
                "rejectionReasons": [
                    {"title": "반려", "message": "사유 문구"},
                ],
                "stocks": [{"managementCode": "OPTION-REF-1"}],
            }
        },
    )

    result = await read_mall_listing_status(
        "toss_store",
        toss_client=client,
        naver_client=None,
        artifact_digests=(ARTIFACT,),
        product_digests=(provider_id_digest(ARTIFACT, TOSS_PRODUCT_ID),),
    )

    body = json.dumps(result.model_dump(mode="json"), ensure_ascii=False)
    assert str(TOSS_PRODUCT_ID) not in body
    assert result.match.product_digest == provider_id_digest(ARTIFACT, TOSS_PRODUCT_ID)


async def test_mcp_tool_is_registered_and_returns_structured_result() -> None:
    client = FakeTossClient(
        pages=(_toss_page(TOSS_PRODUCT_ID),),
        details={
            TOSS_PRODUCT_ID: {
                "id": TOSS_PRODUCT_ID,
                "inspectionStatus": "LLM_INSPECTION_READY",
                "exposureStatus": "EXPOSURE_WAITING",
                "stocks": [{"managementCode": "OPTION-REF-1"}],
            }
        },
    )
    server = build_server(toss_registration_client=client)
    async with Client(server) as session:
        listed = await session.list_tools()
        result = await session.call_tool(
            "commerce_get_mall_listing_status",
            {"channel": "toss_store", "management_codes": ["OPTION-REF-1"]},
        )

    assert "commerce_get_mall_listing_status" in {tool.name for tool in listed.tools}
    assert result.is_error is False
    body = result.structured_content
    assert body["schema_version"] == "1.0"
    assert body["channel"] == "toss_store"
    assert body["status"] == "complete"
    assert body["match"]["kind"] == "management_code"
    assert body["listing"]["state"] == "inspection_waiting"
