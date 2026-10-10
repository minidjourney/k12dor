# 전체 MCP 도구 목록

현재 서버 등록 **146개**. READ 권한에는 차단·시뮬레이션·로컬 초안도 포함됩니다.
등록과 실제 제공자 조회 가능/성공은 다릅니다. 아래 분류는 코드 계약 기반이며 현재 계정의 live probe가 아닙니다.
정확한 nested 입력·출력 구조, enum, default, pattern과 상한은 [TOOLS.json](TOOLS.json)이 기준입니다.
MCP 앱의 도구 필터와 채널 인증·지원 상태에 따라 가용성이 달라집니다.

## 분류별 수
- 건별 승인 필요 WRITE: 4개
- 공용 채널 조회: 9개
- 독립 제공자 READ: 64개
- 등록 참고정보 READ: 3개
- 로컬 전용: 9개
- 무전송 차단: 53개
- 이미지 READ: 1개
- 이번 범위 밖: 3개

- 무전송 차단: 이름이 GET/READ여도 제공자 요청 없이 거부합니다.
- 로컬 전용: 초안·정규화·상태·무전송 시뮬레이션. 일부 계약 목록에는 미배포 Wiki 원본이 필요합니다.
- 독립 제공자 READ/공용 채널 조회/등록 참고정보 READ/이미지 READ: 구현된 경로이며 인증·지원·관측 ref·안전 정책의 조건이 있습니다. 현재 환경 실성공을 보장하지 않습니다.
- 이번 범위 밖: 11번가 공개 카테고리 opt-in·토스 가격비교 별도 경로. 일반 판매자 전체 API 완료 아님.
- 건별 승인 필요 WRITE: 외부 등록 가능 코드이나 별도 executor/로컬 승인 증거가 없으면 거부합니다. 설치 안내에서 활성화하지 않습니다.

## 도구별 계약

### `commerce_block_rg_product_create`

- 권한: **read** · 분류: **무전송 차단**
- 역할: Deny POST shared seller-products: no RG-only proof, no write transport.
- 입력: `{}` (인자 없음)
- 출력 최상위 필드: `channel`, `operation_id`, `method`, `status`, `rg_proof`, `shared_uri_promoted`, `official_rg_uri`, `reasons`, `items`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_block_rg_product_create`

### `commerce_block_rg_product_modify`

- 권한: **read** · 분류: **무전송 차단**
- 역할: Deny PUT shared seller-products: no RG-only proof, no write transport.
- 입력: `{}` (인자 없음)
- 출력 최상위 필드: `channel`, `operation_id`, `method`, `status`, `rg_proof`, `shared_uri_promoted`, `official_rg_uri`, `reasons`, `items`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_block_rg_product_modify`

### `commerce_get_capabilities`

- 권한: **read** · 분류: **로컬 전용**
- 역할: Describe READ capabilities without probing external services or credentials.
- `channel`: 필수 · Channel
- 출력 최상위 필드: `schema_version`, `status`, `channel`, `capabilities`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_capabilities`

### `commerce_get_coupang_auto_category_agreement`

- 권한: **read** · 분류: **무전송 차단**
- 역할: Block check-auto-category-agreed GET before transport: data type uncontracted.
- 입력: `{}` (인자 없음)
- 출력 최상위 필드: `channel`, `source_endpoint`, `status`, `reasons`, `items`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_coupang_auto_category_agreement`

### `commerce_get_coupang_brand`

- 권한: **read** · 분류: **독립 제공자 READ**
- 역할: Read safe general-Coupang brand fields; exclude logo URLs and raw data.
- `brand_id`: 필수 · string · pattern="^(?:[A-Z]{2}-[1-9][0-9]{0,11}|[0-9]{1,18})$"
- 출력 최상위 필드: `channel`, `status`, `brand_id`, `brand_name`, `uid_required`, `allowed_uid_types`, `reasons`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_coupang_brand`

### `commerce_get_coupang_budget_status`

- 권한: **read** · 분류: **무전송 차단**
- 역할: Block budget status GET before transport; envelope is contradictory.
- `contract_id`: 선택 · integer | null · 기본값 null
- `target_month`: 선택 · string | null · 기본값 null
- 출력 최상위 필드: `channel`, `source_endpoint`, `status`, `reasons`, `items`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_coupang_budget_status`

### `commerce_get_coupang_call_center_inquiries`

- 권한: **read** · 분류: **무전송 차단**
- 역할: Block customer-center list GET: call_center_inquiries_pii_envelope_uncontracted.
- `partner_counseling_status`: 필수 · enum ["NONE", "ANSWER", "NO_ANSWER", "TRANSFER"]
- `inquiry_start_at`: 선택 · string | null · 기본값 null
- `inquiry_end_at`: 선택 · string | null · 기본값 null
- `page_num`: 선택 · integer · 기본값 1 · minimum=1
- `page_size`: 선택 · integer · 기본값 10 · minimum=1 · maximum=30
- 출력 최상위 필드: `channel`, `source_endpoint`, `status`, `reasons`, `items`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_coupang_call_center_inquiries`

### `commerce_get_coupang_call_center_inquiry`

- 권한: **read** · 분류: **무전송 차단**
- 역할: Block customer-center single GET: call_center_inquiry_pii_uncontracted.
- `inquiry_id`: 필수 · string · pattern="^[1-9][0-9]{0,19}$"
- 출력 최상위 필드: `channel`, `source_endpoint`, `status`, `reasons`, `items`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_coupang_call_center_inquiry`

### `commerce_get_coupang_cashback_rule`

- 권한: **read** · 분류: **무전송 차단**
- 역할: Block products/items/cashback GET: cashback_envelope_uncontracted.
- `rule_id`: 필수 · string · pattern="^[1-9][0-9]{0,19}$"
- `vendor_item_id`: 필수 · string · pattern="^[1-9][0-9]{0,19}$"
- 출력 최상위 필드: `channel`, `source_endpoint`, `status`, `reasons`, `items`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_coupang_cashback_rule`

### `commerce_get_coupang_category_detail`

- 권한: **read** · 분류: **독립 제공자 READ**
- 역할: Read a single general-Coupang category and at most 100 direct children.
- `category_code`: 필수 · string · pattern="^[0-9]{1,20}$"
- 출력 최상위 필드: `status`, `category_code`, `name`, `category_status`, `children`, `reasons`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_coupang_category_detail`

### `commerce_get_coupang_category_status`

- 권한: **read** · 분류: **무전송 차단**
- 역할: Block category status GET: provider data type is uncontracted.
- `display_category_code`: 필수 · string · pattern="^[1-9][0-9]{0,19}$"
- 출력 최상위 필드: `channel`, `status`, `source_endpoint`, `items`, `reasons`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_coupang_category_status`

### `commerce_get_coupang_contract`

- 권한: **read** · 분류: **독립 제공자 READ**
- 역할: Read FMS single contract GET with only documented numeric and timestamp fields.
- `contract_id`: 필수 · integer · minimum=1 · maximum=9223372036854775807
- 출력 최상위 필드: `channel`, `source_endpoint`, `status`, `reasons`, `items`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_coupang_contract`

### `commerce_get_coupang_contract_list`

- 권한: **read** · 분류: **무전송 차단**
- 역할: Block FMS contract-list GET before transport: envelope uncontracted.
- 입력: `{}` (인자 없음)
- 출력 최상위 필드: `channel`, `source_endpoint`, `status`, `reasons`, `items`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_coupang_contract_list`

### `commerce_get_coupang_display_category_related_metas`

- 권한: **read** · 분류: **무전송 차단**
- 역할: display_category_related_metas; general, not rg_category_meta. GET /v2/providers/seller_api/apis/api/v1/marketplace/meta/category-related-metas/display-category-codes/{displayCategoryCode}. response_field_contract_conflict; no client call or RG alias.
- 입력: `{}` (인자 없음)
- 출력 최상위 필드: `channel`, `operation_id`, `status`, `reasons`, `item`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_coupang_display_category_related_metas`

### `commerce_get_coupang_download_coupon`

- 권한: **read** · 분류: **독립 제공자 READ**
- 역할: Read independent download coupon GET; do not expose policy or title.
- `coupon_id`: 필수 · string · pattern="^[1-9][0-9]{0,19}$"
- 출력 최상위 필드: `channel`, `source_endpoint`, `status`, `reasons`, `items`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_coupang_download_coupon`

### `commerce_get_coupang_download_coupon_transaction_status`

- 권한: **read** · 분류: **무전송 차단**
- 역할: Block coupon transactionStatus GET: request_transaction_id_type_uncontracted.
- `request_transaction_id`: 필수 · string
- 출력 최상위 필드: `channel`, `source_endpoint`, `status`, `reasons`, `items`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_coupang_download_coupon_transaction_status`

### `commerce_get_coupang_enrolled_brands`

- 권한: **read** · 분류: **독립 제공자 READ**
- 역할: Read GET /marketplace/brands/enrolled, projecting only safe brand metadata.
- 입력: `{}` (인자 없음)
- 출력 최상위 필드: `channel`, `source_endpoint`, `status`, `reasons`, `items`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_coupang_enrolled_brands`

### `commerce_get_coupang_exchange_requests`

- 권한: **read** · 분류: **독립 제공자 READ**
- 역할: Read GET /v4/vendors/{vendorId}/exchangeRequests; never return customer data.
        created_at_from/created_at_to: local datetimes YYYY-MM-DDTHH:MM:SS (no
        timezone suffix; date-only and minute-precision forms are rejected)
        spanning a window shorter than 7 days. Claim ids are opaque digests.

- `created_at_from`: 필수 · string
- `created_at_to`: 필수 · string
- `status`: 선택 · string | null · 기본값 null
- `order_id`: 선택 · string | null · 기본값 null
- `max_per_page`: 선택 · integer | null · 기본값 null
- `next_token`: 선택 · string | null · 기본값 null
- 출력 최상위 필드: `channel`, `status`, `source_endpoint`, `items`, `next_token`, `reasons`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_coupang_exchange_requests`

### `commerce_get_coupang_general_category_page`

- 권한: **read** · 분류: **독립 제공자 READ**
- 역할: Page the general seller category tree, distinct from RG RFM.
- `page_size`: 선택 · integer · 기본값 100 · minimum=1 · maximum=100
- `cursor`: 선택 · string | null · 기본값 null
- 출력 최상위 필드: `status`, `items`, `next_cursor`, `total_count`, `source_endpoint`, `reasons`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_coupang_general_category_page`

### `commerce_get_coupang_instant_coupon_by_id`

- 권한: **read** · 분류: **무전송 차단**
- 역할: GET /v2/providers/fms/apis/api/v2/vendors/{vendorId}/coupon, query couponId.

        instant_coupon_by_id_envelope_uncontracted; not downloadable-coupon GET.

- `coupon_id`: 필수 · string · pattern="^[1-9][0-9]{0,19}$"
- 출력 최상위 필드: `channel`, `source_endpoint`, `status`, `reasons`, `items`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_coupang_instant_coupon_by_id`

### `commerce_get_coupang_instant_coupon_item`

- 권한: **read** · 분류: **무전송 차단**
- 역할: GET coupons/{couponId}/items/{couponItemId}, fixed query type=couponItemId.

        instant_coupon_item_envelope_uncontracted; no provider method.

- `coupon_id`: 필수 · string · pattern="^[1-9][0-9]{0,19}$"
- `coupon_item_id`: 필수 · string · pattern="^[1-9][0-9]{0,19}$"
- 출력 최상위 필드: `channel`, `source_endpoint`, `status`, `reasons`, `items`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_coupang_instant_coupon_item`

### `commerce_get_coupang_instant_coupon_item_by_vendor_item`

- 권한: **read** · 분류: **무전송 차단**
- 역할: GET coupons/{couponId}/items/{vendorItemId}, fixed query type=vendorItemId.

        instant_coupon_item_by_vendor_item_envelope_uncontracted; not couponItemId.

- `coupon_id`: 필수 · string · pattern="^[1-9][0-9]{0,19}$"
- `vendor_item_id`: 필수 · string · pattern="^[1-9][0-9]{0,19}$"
- 출력 최상위 필드: `channel`, `source_endpoint`, `status`, `reasons`, `items`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_coupang_instant_coupon_item_by_vendor_item`

### `commerce_get_coupang_instant_coupon_items`

- 권한: **read** · 분류: **무전송 차단**
- 역할: GET /v2/providers/fms/apis/api/v1/vendors/{vendorId}/coupons/{couponId}/items.

        instant_coupon_items_envelope_uncontracted. Page is zero-based; the size
        upper bound is local safety, not an official maximum. No item-add POST.

- `coupon_id`: 필수 · string · pattern="^[1-9][0-9]{0,19}$"
- `status`: 필수 · enum ["STANDBY", "APPLIED", "PAUSED", "EXPIRED"]
- `page`: 선택 · integer · 기본값 0 · minimum=0
- `size`: 선택 · integer · 기본값 100 · minimum=1 · maximum=1000
- 출력 최상위 필드: `channel`, `source_endpoint`, `status`, `reasons`, `items`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_coupang_instant_coupon_items`

### `commerce_get_coupang_instant_coupon_request`

- 권한: **read** · 분류: **독립 제공자 READ**
- 역할: Read independent instant discount request status GET, no query.
- `requested_id`: 필수 · string · pattern="^[1-9][0-9]{0,19}$"
- 출력 최상위 필드: `channel`, `source_endpoint`, `status`, `reasons`, `items`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_coupang_instant_coupon_request`

### `commerce_get_coupang_instant_coupons`

- 권한: **read** · 분류: **무전송 차단**
- 역할: Block status-filtered instant-coupon GET: instant_coupons_envelope_uncontracted.
- `status`: 필수 · enum ["STANDBY", "APPLIED", "PAUSED", "EXPIRED", "DETACHED"]
- 출력 최상위 필드: `channel`, `source_endpoint`, `status`, `reasons`, `items`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_coupang_instant_coupons`

### `commerce_get_coupang_instant_coupons_by_order`

- 권한: **read** · 분류: **무전송 차단**
- 역할: GET /v2/providers/fms/apis/api/v2/vendors/{vendorId}/{orderId}/coupons.

        instant_coupons_by_order_envelope_uncontracted; no query or dispatch.

- `order_id`: 필수 · string · pattern="^[1-9][0-9]{0,19}$"
- 출력 최상위 필드: `channel`, `source_endpoint`, `status`, `reasons`, `items`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_coupang_instant_coupons_by_order`

### `commerce_get_coupang_online_inquiries`

- 권한: **read** · 분류: **독립 제공자 READ**
- 역할: Read GET /v2/providers/openapi/apis/api/v5/vendors/{vendorId}/onlineInquiries.
        Return identifiers and timestamps, never question or reply content.

- `answered_type`: 필수 · enum ["ALL", "ANSWERED", "NOANSWER"]
- `inquiry_start_at`: 필수 · string
- `inquiry_end_at`: 필수 · string
- `page_num`: 선택 · integer · 기본값 1
- `page_size`: 선택 · integer · 기본값 10
- 출력 최상위 필드: `channel`, `status`, `source_endpoint`, `items`, `pagination`, `reasons`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_coupang_online_inquiries`

### `commerce_get_coupang_order_sheet`

- 권한: **read** · 분류: **독립 제공자 READ**
- 역할: Read one shipment-box order sheet, excluding customer and free-text fields.
- `shipment_box_id`: 필수 · string · pattern="^[1-9][0-9]{0,19}$"
- 출력 최상위 필드: `channel`, `status`, `source_endpoint`, `items`, `reasons`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_coupang_order_sheet`

### `commerce_get_coupang_order_sheet_history`

- 권한: **read** · 분류: **무전송 차단**
- 역할: Block the uncontracted history response envelope without provider I/O.
- `shipment_box_id`: 필수 · string · pattern="^[1-9][0-9]{0,19}$"
- 출력 최상위 필드: `channel`, `status`, `source_endpoint`, `items`, `reasons`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_coupang_order_sheet_history`

### `commerce_get_coupang_order_sheets_by_order`

- 권한: **read** · 분류: **독립 제공자 READ**
- 역할: Read one order's bounded shipment-box list without customer PII.
- `order_id`: 필수 · string · pattern="^[1-9][0-9]{0,19}$"
- 출력 최상위 필드: `channel`, `status`, `source_endpoint`, `items`, `reasons`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_coupang_order_sheets_by_order`

### `commerce_get_coupang_outbound_shipping_places`

- 권한: **read** · 분류: **독립 제공자 READ**
- 역할: Read GET outbound shipping-place page; omit address and phone fields.
- `page_num`: 필수 · integer · minimum=1 · maximum=2147483647
- `page_size`: 필수 · integer · minimum=1 · maximum=50
- 출력 최상위 필드: `channel`, `source_endpoint`, `status`, `reasons`, `items`, `page`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_coupang_outbound_shipping_places`

### `commerce_get_coupang_product_by_external_sku`

- 권한: **read** · 분류: **무전송 차단**
- 역할: Block SKU summary GET: seller_product_by_sku_envelope_uncontracted.
- `external_vendor_sku_code`: 필수 · string
- 출력 최상위 필드: `channel`, `source_endpoint`, `status`, `reasons`, `items`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_coupang_product_by_external_sku`

### `commerce_get_coupang_product_registration_quota`

- 권한: **read** · 분류: **독립 제공자 READ**
- 역할: Read independent seller-products/inflow-status GET with no query.
- 입력: `{}` (인자 없음)
- 출력 최상위 필드: `channel`, `status`, `source_endpoint`, `items`, `reasons`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_coupang_product_registration_quota`

### `commerce_get_coupang_product_time_frame`

- 권한: **read** · 분류: **무전송 차단**
- 역할: Block seller-products/time-frame GET: success envelope uncontracted.
- `created_at_from`: 필수 · string · pattern="^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}$"
- `created_at_to`: 필수 · string · pattern="^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}$"
- 출력 최상위 필드: `channel`, `source_endpoint`, `status`, `reasons`, `items`, `page`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_coupang_product_time_frame`

### `commerce_get_coupang_return_center_codes`

- 권한: **read** · 분류: **독립 제공자 READ**
- 역할: Read GET /v2/providers/openapi/apis/api/v3/return/shipping-places/center-code.
        Exact returnCenterCodes query only.

- `return_center_codes`: 필수 · string · pattern="^[1-9][0-9]{0,19}(,[1-9][0-9]{0,19}){0,99}$"
- 출력 최상위 필드: `channel`, `status`, `source_endpoint`, `items`, `reasons`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_coupang_return_center_codes`

### `commerce_get_coupang_return_request`

- 권한: **read** · 분류: **독립 제공자 READ**
- 역할: Read one return receipt; omit requester, address, and reason text.
- `receipt_id`: 필수 · string · pattern="^[1-9][0-9]{0,19}$"
- 출력 최상위 필드: `channel`, `status`, `source_endpoint`, `items`, `reasons`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_coupang_return_request`

### `commerce_get_coupang_return_requests`

- 권한: **read** · 분류: **무전송 차단**
- 역할: return_requests.

        GET /v2/providers/openapi/apis/api/v6/vendors/{vendorId}/returnRequests
        response_envelope_contract_conflict, search_type_inputs_uncontracted,
        requester_pii_projection_unapproved. Local-only block; no client calls.

- 입력: `{}` (인자 없음)
- 출력 최상위 필드: `channel`, `operation_id`, `status`, `reasons`, `item`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_coupang_return_requests`

### `commerce_get_coupang_return_shipping_centers`

- 권한: **read** · 분류: **무전송 차단**
- 역할: Block returnShippingCenters GET before transport: response envelope uncontracted.
- `page_num`: 선택 · integer · 기본값 1
- `page_size`: 선택 · integer · 기본값 10
- 출력 최상위 필드: `channel`, `source_endpoint`, `status`, `reasons`, `items`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_coupang_return_shipping_centers`

### `commerce_get_coupang_return_withdraw_requests`

- 권한: **read** · 분류: **독립 제공자 READ**
- 역할: Read GET /v4/vendors/{vendorId}/returnWithdrawRequests without customer data.
        date_from/date_to: YYYY-MM-DD spanning at most 7 inclusive days.
        Claim and item ids are opaque digests.

- `date_from`: 필수 · string
- `date_to`: 필수 · string
- `page_index`: 선택 · integer · 기본값 1
- `size_per_page`: 선택 · integer · 기본값 10
- 출력 최상위 필드: `channel`, `status`, `source_endpoint`, `items`, `next_page_index`, `reasons`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_coupang_return_withdraw_requests`

### `commerce_get_coupang_revenue_history`

- 권한: **read** · 분류: **무전송 차단**
- 역할: Block recognition-date revenue GET: recognition_date_order_linkage_unapproved.

        This is not paid-order revenue, fee lookup or settlement histories.
        No provider method is called, even if a legacy client is configured.

- `recognition_date_from`: 필수 · string · pattern="^[0-9]{4}-[0-9]{2}-[0-9]{2}$"
- `recognition_date_to`: 필수 · string · pattern="^[0-9]{4}-[0-9]{2}-[0-9]{2}$"
- `token`: 선택 · string · 기본값 ""
- `max_per_page`: 선택 · integer · 기본값 50 · minimum=1 · maximum=50
- 출력 최상위 필드: `channel`, `source_endpoint`, `status`, `reasons`, `items`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_coupang_revenue_history`

### `commerce_get_coupang_seller_product_histories`

- 권한: **read** · 분류: **무전송 차단**
- 역할: Block product status history GET: seller_product_histories_envelope_uncontracted.
- `seller_product_id`: 필수 · string · pattern="^[1-9][0-9]{0,19}$"
- 출력 최상위 필드: `channel`, `source_endpoint`, `status`, `reasons`, `items`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_coupang_seller_product_histories`

### `commerce_get_coupang_seller_product_partial`

- 권한: **read** · 분류: **무전송 차단**
- 역할: Block GET seller-products/{sellerProductId}/partial: success code is uncontracted.
- `seller_product_id`: 필수 · string · pattern="^[A-Za-z0-9_-]{1,40}$"
- 출력 최상위 필드: `channel`, `status`, `source_endpoint`, `items`, `reasons`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_coupang_seller_product_partial`

### `commerce_get_coupang_settlement_histories`

- 권한: **read** · 분류: **무전송 차단**
- 역할: Block settlement-histories GET: success envelope uncontracted.
- `revenue_recognition_year_month`: 필수 · string
- 출력 최상위 필드: `channel`, `status`, `source_endpoint`, `items`, `pagination`, `reasons`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_coupang_settlement_histories`

### `commerce_get_coupang_shipment_history`

- 권한: **read** · 분류: **독립 제공자 READ**
- 역할: Read bounded shipment states and timestamps without recipient or address.
- `shipment_box_id`: 필수 · string · pattern="^[1-9][0-9]{0,19}$"
- 출력 최상위 필드: `status`, `events`, `source_endpoint`, `reasons`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_coupang_shipment_history`

### `commerce_get_elevenst_categories`

- 권한: **read** · 분류: **이번 범위 밖**
- 역할: Read the unauthenticated 11st category list with leaf flags.
- 입력: `{}` (인자 없음)
- 출력 최상위 필드: `status`, `items`, `total_count`, `reasons`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_elevenst_categories`

### `commerce_get_elevenst_product`

- 권한: **read** · 분류: **독립 제공자 READ**
- 역할: Read one 11st seller product summary by product number.
- `product_no`: 필수 · string · pattern="^[1-9][0-9]{0,19}$"
- 출력 최상위 필드: `status`, `product`, `reasons`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_elevenst_product`

### `commerce_get_elevenst_public_categories`

- 권한: **read** · 분류: **이번 범위 밖**
- 역할: Page public unauthenticated 11st category GETs; no seller data.
- `page_size`: 선택 · integer · 기본값 50 · minimum=1 · maximum=100
- `cursor`: 선택 · string | null · 기본값 null
- `parent_category_id`: 선택 · string | null · 기본값 null
- 출력 최상위 필드: `status`, `items`, `next_cursor`, `total_count`, `source_endpoint`, `reasons`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_elevenst_public_categories`

### `commerce_get_elevenst_registered_defaults`

- 권한: **read** · 분류: **독립 제공자 READ**
- 역할: Most-used seller-policy values across our registered 11st products (GET 1620/1621).

        product_nos: 11st product numbers (max 20); seller_product_codes: seller product
        codes resolved by GET 1621 (max 10). 11st has no GET list of our own products, so
        with neither argument nothing is called and sample_count is 0. Each field returns
        {value, count, candidates, conflict}. Seller-published A/S and return text may carry
        the company phone number; buyer data, addresses and HTML are never read.

- `product_nos`: 선택 · array · 기본값 [] · maxItems=20
- `seller_product_codes`: 선택 · array · 기본값 [] · maxItems=10
- 출력 최상위 필드: `status`, `sample_count`, `requested`, `reasons`, `notice`, `notice_agree_count`, `notice_type_candidates`, `as_detail`, `return_exchange_detail`, `category_no`, `tax_code`, `minor_purchasable`, `beef_trace`, `raw_material_type`, `origin`, `delivery`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_elevenst_registered_defaults`

### `commerce_get_elevenst_registration_options`

- 권한: **read** · 분류: **독립 제공자 READ**
- 역할: Read 11st seller registration selectors; no address or contact data.
- 입력: `{}` (인자 없음)
- 출력 최상위 필드: `status`, `outbound_places`, `return_places`, `send_close_templates`, `reasons`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_elevenst_registration_options`

### `commerce_get_fees`

- 권한: **read** · 분류: **공용 채널 조회**
- 역할: Return only fee values actually reported by the marketplace API.

        business_date (KST pay date) narrows the Naver commission read to that
        day; other channels ignore it.

- `channel`: 필수 · Channel
- `page_size`: 선택 · integer · 기본값 50 · minimum=1 · maximum=100
- `cursor`: 선택 · string | null · 기본값 null
- `business_date`: 선택 · string | null · 기본값 null
- 출력 최상위 필드: `schema_version`, `status`, `channel`, `next_cursor`, `reasons`, `errors`, `items`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_fees`

### `commerce_get_inventory`

- 권한: **read** · 분류: **공용 채널 조회**
- 역할: Return separate inventory-source rows without aggregation or inference.
- `channel`: 필수 · Channel
- `page_size`: 선택 · integer · 기본값 50 · minimum=1 · maximum=100
- `cursor`: 선택 · string | null · 기본값 null
- `vendor_item_id`: 선택 · string | null · 기본값 null
- 출력 최상위 필드: `schema_version`, `status`, `channel`, `next_cursor`, `reasons`, `errors`, `items`, `summary`, `groups`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_inventory`

### `commerce_get_mall_listing_status`

- 권한: **read** · 분류: **독립 제공자 READ**
- 역할: 몰 등록 상태 읽기 (RV-20261009 CONTRACT 3절) — 읽기 전용.

        최신 상품 목록 최대 3쪽(쪽당 50)에서 artifact·product digest 또는
        management_codes(토스만, 상세 GET 최대 20번)로 상품 하나를 찾아
        2절 상태 낱말(on_sale·inspection_waiting·inspection_rejected·
        not_on_sale·unknown)로 돌려준다. 상품 번호 원문은 나가지 않는다.

- `channel`: 필수 · enum ["naver", "toss_store"]
- `artifact_digests`: 선택 · array · 기본값 [] · maxItems=10
- `product_digests`: 선택 · array · 기본값 [] · maxItems=20
- `management_codes`: 선택 · array · 기본값 [] · maxItems=50
- 출력 최상위 필드: `schema_version`, `channel`, `status`, `match`, `listing`, `candidates_scanned`, `reasons`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_mall_listing_status`

### `commerce_get_marketplace_categories`

- 권한: **read** · 분류: **등록 참고정보 READ**
- 역할: Return bounded canonical marketplace categories for registration.
- `channel`: 필수 · enum ["naver", "toss_store"]
- `parent_category_id`: 선택 · string | null · 기본값 null
- 출력 최상위 필드: `schema_version`, `status`, `channel`, `reasons`, `errors`, `items`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_marketplace_categories`

### `commerce_get_marketplace_category_requirements`

- 권한: **read** · 분류: **등록 참고정보 READ**
- 역할: Return safe option/attribute descriptors and notice codes for one category.
- `channel`: 필수 · enum ["naver", "toss_store"]
- `category_id`: 필수 · string · pattern="^[1-9][0-9]{0,19}$"
- `notice_category_code`: 선택 · string | null · 기본값 null
- 출력 최상위 필드: `schema_version`, `status`, `channel`, `category_id`, `item`, `reasons`, `errors`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_marketplace_category_requirements`

### `commerce_get_marketplace_registration_resources`

- 권한: **read** · 분류: **등록 참고정보 READ**
- 역할: Return safe registration resource selectors; never address or contact data.
- `channel`: 필수 · enum ["naver", "toss_store"]
- 출력 최상위 필드: `schema_version`, `status`, `channel`, `reasons`, `errors`, `items`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_marketplace_registration_resources`

### `commerce_get_naver_address_books`

- 권한: **read** · 분류: **독립 제공자 READ**
- 역할: get-page-addresses-sellers GET /v1/seller/addressbooks-for-page.

        Only hasLocation and pagination; no identity, contact or street fields.

- `page`: 선택 · integer · 기본값 1
- 출력 최상위 필드: `channel`, `operation_id`, `status`, `reasons`, `items`, `page`, `totalPage`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_naver_address_books`

### `commerce_get_naver_attribute_units`

- 권한: **read** · 분류: **독립 제공자 READ**
- 역할: Read GET /v1/product-attributes/attribute-value-units; query must be omitted.
- `query`: 선택 · string | null · 기본값 null
- `page_size`: 선택 · integer · 기본값 100 · minimum=1 · maximum=100
- `cursor`: 선택 · string | null · 기본값 null
- 출력 최상위 필드: `channel`, `kind`, `status`, `items`, `page_count`, `total_count`, `has_more`, `next_cursor`, `reasons`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_naver_attribute_units`

### `commerce_get_naver_attribute_values`

- 권한: **read** · 분류: **독립 제공자 READ**
- 역할: Read GET /v1/product-attributes/attribute-values; query = numeric categoryId (required).
- `query`: 선택 · string | null · 기본값 null
- `page_size`: 선택 · integer · 기본값 100 · minimum=1 · maximum=100
- `cursor`: 선택 · string | null · 기본값 null
- 출력 최상위 필드: `channel`, `kind`, `status`, `items`, `page_count`, `total_count`, `has_more`, `next_cursor`, `reasons`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_naver_attribute_values`

### `commerce_get_naver_attributes`

- 권한: **read** · 분류: **독립 제공자 READ**
- 역할: Read GET /v1/product-attributes/attributes; query = numeric categoryId (required, e.g. from commerce_get_naver_subcategories).
- `query`: 선택 · string | null · 기본값 null
- `page_size`: 선택 · integer · 기본값 100 · minimum=1 · maximum=100
- `cursor`: 선택 · string | null · 기본값 null
- 출력 최상위 필드: `channel`, `kind`, `status`, `items`, `page_count`, `total_count`, `has_more`, `next_cursor`, `reasons`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_naver_attributes`

### `commerce_get_naver_brands`

- 권한: **read** · 분류: **독립 제공자 READ**
- 역할: Read GET /v1/product-brands; query = brand name (required, 80 chars max).
- `query`: 선택 · string | null · 기본값 null
- `page_size`: 선택 · integer · 기본값 100 · minimum=1 · maximum=100
- `cursor`: 선택 · string | null · 기본값 null
- 출력 최상위 필드: `channel`, `kind`, `status`, `items`, `page_count`, `total_count`, `has_more`, `next_cursor`, `reasons`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_naver_brands`

### `commerce_get_naver_categories`

- 권한: **read** · 분류: **독립 제공자 READ**
- 역할: get-category-list-product GET /v1/categories; safe full catalog fields.
- `last`: 선택 · boolean · 기본값 false
- 출력 최상위 필드: `channel`, `operation_id`, `status`, `reasons`, `items`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_naver_categories`

### `commerce_get_naver_category`

- 권한: **read** · 분류: **독립 제공자 READ**
- 역할: get-category-product GET /v1/categories/:categoryId.

        Supported safe alphanumeric path subset, local max200; closed public fields.

- `categoryId`: 필수 · string
- 출력 최상위 필드: `channel`, `operation_id`, `status`, `reasons`, `item`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_naver_category`

### `commerce_get_naver_changed_product_order_statuses`

- 권한: **read** · 분류: **무전송 차단**
- 역할: seller-get-last-changed-status-pay-order-seller.

        GET /v1/pay-order/seller/product-orders/last-changed-statuses.

        order_linkage_projection_unapproved; local block only, no provider call or token access.

- 입력: `{}` (인자 없음)
- 출력 최상위 필드: `channel`, `operation_id`, `status`, `reasons`, `item`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_naver_changed_product_order_statuses`

### `commerce_get_naver_channel_product`

- 권한: **read** · 분류: **독립 제공자 READ**
- 역할: read-channel-product-1-product GET /v2/products/channel-products/:channelProductNo.

        Closed catalog projection only; no same-path mutations, contact or raw content.
        channelProductNo: positive int64; the digit-string external_product_id
        from commerce_get_products is also accepted.

- `channelProductNo`: 필수 · integer
- 출력 최상위 필드: `channel`, `operation_id`, `status`, `reasons`, `item`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_naver_channel_product`

### `commerce_get_naver_commission_details`

- 권한: **read** · 분류: **무전송 차단**
- 역할: find-commission-details-pay-settle GET /v1/pay-settle/settle/commission-details.

        order_linked_commission_projection_unapproved;
        local block only, no provider call or token access.

- 입력: `{}` (인자 없음)
- 출력 최상위 필드: `channel`, `operation_id`, `status`, `reasons`, `item`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_naver_commission_details`

### `commerce_get_naver_conditional_product_orders`

- 권한: **read** · 분류: **무전송 차단**
- 역할: seller-get-product-orders-with-conditions-pay-order-seller.

        GET /v1/pay-order/seller/product-orders.

        order_linkage_projection_unapproved; local block only, no provider call or token access.

- 입력: `{}` (인자 없음)
- 출력 최상위 필드: `channel`, `operation_id`, `status`, `reasons`, `item`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_naver_conditional_product_orders`

### `commerce_get_naver_customer_inquiries`

- 권한: **read** · 분류: **무전송 차단**
- 역할: get-customer-inquiry-pay-user GET /v1/pay-user/inquiries.

        customer_inquiry_projection_unapproved; local block only, no provider call or token access.

- 입력: `{}` (인자 없음)
- 출력 최상위 필드: `channel`, `operation_id`, `status`, `reasons`, `item`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_naver_customer_inquiries`

### `commerce_get_naver_daily_settlements`

- 권한: **read** · 분류: **독립 제공자 READ**
- 역할: find-daily-settle-pay-settle GET /v1/pay-settle/settle/daily.

        Closed dates and amounts; one response page, no bank/account/merchant fields.

- `startDate`: 필수 · string
- `endDate`: 필수 · string
- `pageNumber`: 필수 · integer
- `pageSize`: 필수 · integer
- 출력 최상위 필드: `channel`, `operation_id`, `status`, `reasons`, `items`, `pagination`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_naver_daily_settlements`

### `commerce_get_naver_daily_vat_declarations`

- 권한: **read** · 분류: **무전송 차단**
- 역할: Block GET /v1/pay-settle/vat/daily before transport: PII review pending.
- `startDate`: 필수 · string
- `endDate`: 필수 · string
- `pageNumber`: 필수 · integer · minimum=1
- `pageSize`: 필수 · integer · maximum=1000
- 출력 최상위 필드: `channel`, `operation_id`, `status`, `reasons`, `item`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_naver_daily_vat_declarations`

### `commerce_get_naver_delivery_bundle_group`

- 권한: **read** · 분류: **독립 제공자 READ**
- 역할: Read GET /v1/product-delivery-info/bundle-groups/:deliveryBundleGroupId.
        Operation: get-delivery-bundle-group-product.
        deliveryBundleGroupId: int64 id from commerce_get_naver_delivery_bundle_groups;
        a digit string is also accepted.

- `deliveryBundleGroupId`: 필수 · integer
- 출력 최상위 필드: `channel`, `operation_id`, `status`, `reasons`, `item`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_naver_delivery_bundle_group`

### `commerce_get_naver_delivery_bundle_groups`

- 권한: **read** · 분류: **독립 제공자 READ**
- 역할: Read GET /v1/product-delivery-info/bundle-groups.
        Operation: get-delivery-bundle-group-list-product.

- `name`: 선택 · string | null · 기본값 null
- `baseGroup`: 선택 · boolean | null · 기본값 null
- `usable`: 선택 · boolean | null · 기본값 null
- `page`: 선택 · integer | null · 기본값 null
- `size`: 선택 · integer | null · 기본값 null
- 출력 최상위 필드: `channel`, `operation_id`, `status`, `reasons`, `items`, `page`, `size`, `totalElements`, `totalPages`, `first`, `last`, `sort`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_naver_delivery_bundle_groups`

### `commerce_get_naver_fashion_models`

- 권한: **read** · 분류: **무전송 차단**
- 역할: Block get-fashion-models-product GET /v1/product-fashion-models.

        pii_projection_unapproved; never dispatch.

- 입력: `{}` (인자 없음)
- 출력 최상위 필드: `channel`, `operation_id`, `status`, `reasons`, `item`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_naver_fashion_models`

### `commerce_get_naver_group_product`

- 권한: **read** · 분류: **무전송 차단**
- 역할: read-product-product GET /v2/standard-group-products/:groupProductNo.

        raw_content_projection_unapproved; no same-path PUT or DELETE.

- `groupProductNo`: 필수 · integer
- 출력 최상위 필드: `channel`, `operation_id`, `status`, `reasons`, `item`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_naver_group_product`

### `commerce_get_naver_group_product_status`

- 권한: **read** · 분류: **무전송 차단**
- 역할: Block get-progress-product GET /v2/standard-group-products/status.

        response_projection_unapproved; never transport.

- `type`: 선택 · enum ["CREATE", "UPDATE", "CONVERT"] · 기본값 null
- `requestId`: 선택 · string · 기본값 null
- 출력 최상위 필드: `channel`, `operation_id`, `status`, `reasons`, `item`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_naver_group_product_status`

### `commerce_get_naver_hope_delivery_group`

- 권한: **read** · 분류: **독립 제공자 READ**
- 역할: Read GET /v1/product-delivery-info/hope-delivery-groups/:hopeDeliveryGroupId.
        Operation: get-hope-delivery-group-product.

- `hopeDeliveryGroupId`: 필수 · integer
- 출력 최상위 필드: `channel`, `operation_id`, `status`, `reasons`, `item`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_naver_hope_delivery_group`

### `commerce_get_naver_hope_delivery_groups`

- 권한: **read** · 분류: **독립 제공자 READ**
- 역할: Read GET /v1/product-delivery-info/hope-delivery-groups.
        Operation: get-hope-delivery-group-list-product.

- `name`: 선택 · string | null · 기본값 null
- `baseGroup`: 선택 · boolean | null · 기본값 null
- `usable`: 선택 · boolean | null · 기본값 null
- `page`: 선택 · integer | null · 기본값 null
- `size`: 선택 · integer | null · 기본값 null
- 출력 최상위 필드: `channel`, `operation_id`, `status`, `reasons`, `items`, `page`, `size`, `totalElements`, `totalPages`, `first`, `last`, `sort`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_naver_hope_delivery_groups`

### `commerce_get_naver_inspection_products`

- 권한: **read** · 분류: **무전송 차단**
- 역할: Block get-inspection-products-request-product GET.

        /v1/product-inspections/channel-products; response_projection_unapproved.

- `page`: 선택 · integer · 기본값 1 · minimum=1
- `size`: 선택 · enum [10, 50, 100] · 기본값 100
- 출력 최상위 필드: `channel`, `operation_id`, `status`, `reasons`, `item`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_naver_inspection_products`

### `commerce_get_naver_logistics_companies`

- 권한: **read** · 분류: **독립 제공자 READ**
- 역할: Read GET /v1/logistics/logistics-companies (get-logistics-companies-nfa).
- 입력: `{}` (인자 없음)
- 출력 최상위 필드: `channel`, `operation_id`, `status`, `items`, `page_count`, `total_count`, `has_more`, `next_cursor`, `reasons`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_naver_logistics_companies`

### `commerce_get_naver_manufacturers`

- 권한: **read** · 분류: **독립 제공자 READ**
- 역할: Read GET /v1/product-manufacturers; query = manufacturer name (required, 80 chars max).
- `query`: 선택 · string | null · 기본값 null
- `page_size`: 선택 · integer · 기본값 100 · minimum=1 · maximum=100
- `cursor`: 선택 · string | null · 기본값 null
- 출력 최상위 필드: `channel`, `kind`, `status`, `items`, `page_count`, `total_count`, `has_more`, `next_cursor`, `reasons`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_naver_manufacturers`

### `commerce_get_naver_origin_area_by_name`

- 권한: **read** · 분류: **독립 제공자 READ**
- 역할: Read GET /v1/product-origin-areas/query; query = origin area name (required).
- `query`: 선택 · string | null · 기본값 null
- `page_size`: 선택 · integer · 기본값 100 · minimum=1 · maximum=100
- `cursor`: 선택 · string | null · 기본값 null
- 출력 최상위 필드: `channel`, `kind`, `status`, `items`, `page_count`, `total_count`, `has_more`, `next_cursor`, `reasons`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_naver_origin_area_by_name`

### `commerce_get_naver_origin_areas`

- 권한: **read** · 분류: **독립 제공자 READ**
- 역할: Read GET /v1/product-origin-areas; query must be omitted.
- `query`: 선택 · string | null · 기본값 null
- `page_size`: 선택 · integer · 기본값 100 · minimum=1 · maximum=100
- `cursor`: 선택 · string | null · 기본값 null
- 출력 최상위 필드: `channel`, `kind`, `status`, `items`, `page_count`, `total_count`, `has_more`, `next_cursor`, `reasons`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_naver_origin_areas`

### `commerce_get_naver_origin_product`

- 권한: **read** · 분류: **독립 제공자 READ**
- 역할: read-origin-product-product GET /v2/products/origin-products/:originProductNo.

        Closed catalog projection only; no same-path mutations, contact or raw content.
        originProductNo: positive int64; a digit string is also accepted.

- `originProductNo`: 필수 · integer
- 출력 최상위 필드: `channel`, `operation_id`, `status`, `reasons`, `item`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_naver_origin_product`

### `commerce_get_naver_outbound_locations`

- 권한: **read** · 분류: **독립 제공자 READ**
- 역할: Read GET /v1/logistics/outbound-locations (get-outbound-locations-nfa).
- 입력: `{}` (인자 없음)
- 출력 최상위 필드: `channel`, `operation_id`, `status`, `items`, `page_count`, `total_count`, `has_more`, `next_cursor`, `reasons`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_naver_outbound_locations`

### `commerce_get_naver_product_inquiries`

- 권한: **read** · 분류: **무전송 차단**
- 역할: get-comments-contents GET /v1/contents/qnas.

        customer_content_projection_unapproved; local block only, no provider call or token access.

- 입력: `{}` (인자 없음)
- 출력 최상위 필드: `channel`, `operation_id`, `status`, `reasons`, `item`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_naver_product_inquiries`

### `commerce_get_naver_product_model`

- 권한: **read** · 분류: **독립 제공자 READ**
- 역할: Read GET /v1/product-models/:id (get-model-product); closed catalog projection.
- `id`: 필수 · integer
- 출력 최상위 필드: `channel`, `operation_id`, `status`, `reasons`, `item`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_naver_product_model`

### `commerce_get_naver_product_models`

- 권한: **read** · 분류: **무전송 차단**
- 역할: Block GET /v1/product-models (get-model-list-product): response skeleton only.
- 입력: `{}` (인자 없음)
- 출력 최상위 필드: `channel`, `operation_id`, `status`, `items`, `page_count`, `total_count`, `has_more`, `next_cursor`, `reasons`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_naver_product_models`

### `commerce_get_naver_product_order_ids`

- 권한: **read** · 분류: **무전송 차단**
- 역할: seller-get-product-order-ids-pay-order-seller GET.

        /v1/pay-order/seller/orders/:orderId/product-order-ids.
        order_identifier_projection_unapproved; no provider call.

- `orderId`: 필수 · string
- 출력 최상위 필드: `channel`, `operation_id`, `status`, `reasons`, `item`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_naver_product_order_ids`

### `commerce_get_naver_provided_notice_type`

- 권한: **read** · 분류: **독립 제공자 READ**
- 역할: Read GET /v1/products-for-provided-notice/:productInfoProvidedNoticeType
        (get-product-info-provided-notice-type-vo-product).
- `productInfoProvidedNoticeType`: 필수 · enum ["WEAR", "SHOES", "BAG", "FASHION_ITEMS", "SLEEPING_GEAR", "FURNITURE", "IMAGE_APPLIANCES", "HOME_APPLIANCES", "SEASON_APPLIANCES", "OFFICE_APPLIANCES", "OPTICS_APPLIANCES", "MICROELECTRONICS", "CELLPHONE", "NAVIGATION", "CAR_ARTICLES", "MEDICAL_APPLIANCES", "KITCHEN_UTENSILS", "COSMETIC", "JEWELLERY", "FOOD", "GENERAL_FOOD", "DIET_FOOD", "KIDS", "MUSICAL_INSTRUMENT", "SPORTS_EQUIPMENT", "BOOKS", "LODGMENT_RESERVATION", "TRAVEL_PACKAGE", "AIRLINE_TICKET", "RENT_CAR", "RENTAL_HA", "RENTAL_ETC", "DIGITAL_CONTENTS", "GIFT_CARD", "MOBILE_COUPON", "MOVIE_SHOW", "ETC_SERVICE", "BIOCHEMISTRY", "BIOCIDAL", "ETC"]
- 출력 최상위 필드: `channel`, `operation_id`, `status`, `items`, `page_count`, `total_count`, `has_more`, `next_cursor`, `reasons`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_naver_provided_notice_type`

### `commerce_get_naver_provided_notice_types`

- 권한: **read** · 분류: **독립 제공자 READ**
- 역할: Read GET /v1/products-for-provided-notice
        (get-all-product-info-provided-notice-type-vo-product).
- `categoryId`: 선택 · string | null · 기본값 null
- 출력 최상위 필드: `channel`, `operation_id`, `status`, `items`, `page_count`, `total_count`, `has_more`, `next_cursor`, `reasons`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_naver_provided_notice_types`

### `commerce_get_naver_purchase_option_guides`

- 권한: **read** · 분류: **독립 제공자 READ**
- 역할: Read GET /v2/standard-purchase-option-guides.

        Operation: get-option-guides-by-category-id-product.

- `categoryId`: 필수 · string · pattern="^[1-9][0-9]{0,17}$"
- 출력 최상위 필드: `channel`, `operation_id`, `status`, `reasons`, `item`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_naver_purchase_option_guides`

### `commerce_get_naver_qna_answer_templates`

- 권한: **read** · 분류: **무전송 차단**
- 역할: Block get-comment-templates-contents GET /v1/contents/qnas/templates.

        response_projection_unapproved; never dispatch.

- 입력: `{}` (인자 없음)
- 출력 최상위 필드: `channel`, `operation_id`, `status`, `reasons`, `item`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_naver_qna_answer_templates`

### `commerce_get_naver_recommend_tags`

- 권한: **read** · 분류: **독립 제공자 READ**
- 역할: Read GET /v2/tags/recommend-tags (get-recommend-tags-product).
- `keyword`: 필수 · string · 기본값 null
- 출력 최상위 필드: `channel`, `operation_id`, `status`, `items`, `page_count`, `total_count`, `has_more`, `next_cursor`, `reasons`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_naver_recommend_tags`

### `commerce_get_naver_reference_page`

- 권한: **read** · 분류: **독립 제공자 READ**
- 역할: Page eight official Naver reference GETs; output only whitelisted fields.
- `kind`: 필수 · enum ["brand", "manufacturer", "origin_all", "origin_query_name", "origin_query_code", "origin_sub", "attribute", "attribute_value", "attribute_unit"]
- `query`: 선택 · string | null · 기본값 null
- `page_size`: 선택 · integer · 기본값 100 · minimum=1 · maximum=100
- `cursor`: 선택 · string | null · 기본값 null
- 출력 최상위 필드: `channel`, `kind`, `status`, `items`, `page_count`, `total_count`, `has_more`, `next_cursor`, `reasons`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_naver_reference_page`

### `commerce_get_naver_registration_defaults`

- 권한: **read** · 분류: **독립 제공자 READ**
- 역할: Registered Naver product's registration values for DOR defaults (read-only).

        Exactly one of originProductNo / channelProductNo. A channel product number
        (the id kept on orders and SKU links) is resolved to its origin product first.
        Returns only origin area, minor purchase, notice type+items, A/S guide text,
        the seller-registered A/S contact (as_telephone and the notice items
        afterServiceDirector / customerServicePhoneNumber — company contact, CEO
        2026-10-07), shipping/return address-book ids (numbers only) and delivery
        fee policy. Never buyer data, other phone fields, or address text.

- `originProductNo`: 선택 · integer · 기본값 null
- `channelProductNo`: 선택 · integer · 기본값 null
- 출력 최상위 필드: `channel`, `operation_id`, `status`, `reasons`, `origin_product_no`, `item`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_naver_registration_defaults`

### `commerce_get_naver_restricted_tags`

- 권한: **read** · 분류: **무전송 차단**
- 역할: GET /v2/tags/restricted-tags (is-restrict-tags-product).

        Blocked: query_array_encoding_unverified.

- `tags`: 필수 · array · 기본값 null
- 출력 최상위 필드: `channel`, `operation_id`, `status`, `items`, `page_count`, `total_count`, `has_more`, `next_cursor`, `reasons`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_naver_restricted_tags`

### `commerce_get_naver_return_delivery_companies`

- 권한: **read** · 분류: **독립 제공자 READ**
- 역할: Read GET /v2/product-delivery-info/return-delivery-companies
        (get-return-delivery-company-list-product).
- `name`: 선택 · string | null · 기본값 null
- 출력 최상위 필드: `channel`, `operation_id`, `status`, `items`, `page_count`, `total_count`, `has_more`, `next_cursor`, `reasons`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_naver_return_delivery_companies`

### `commerce_get_naver_seller_account`

- 권한: **read** · 분류: **무전송 차단**
- 역할: Block get-account-info-by-account-no-sellers GET /v1/seller/account.

        account_identifier_projection_unapproved; never dispatch.

- 입력: `{}` (인자 없음)
- 출력 최상위 필드: `channel`, `operation_id`, `status`, `reasons`, `item`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_naver_seller_account`

### `commerce_get_naver_seller_address`

- 권한: **read** · 분류: **무전송 차단**
- 역할: Block get-address-sellers GET /v1/seller/addressbooks/:addressBookNo.

        pii_projection_unapproved; distinct from addressbooks-for-page.

- `addressBookNo`: 필수 · integer · minimum=1
- 출력 최상위 필드: `channel`, `operation_id`, `status`, `reasons`, `item`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_naver_seller_address`

### `commerce_get_naver_seller_channels`

- 권한: **read** · 분류: **무전송 차단**
- 역할: Block get-channels-by-account-no-sellers GET /v1/seller/channels.

        response_projection_unapproved; never dispatch.

- 입력: `{}` (인자 없음)
- 출력 최상위 필드: `channel`, `operation_id`, `status`, `reasons`, `item`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_naver_seller_channels`

### `commerce_get_naver_seller_notice`

- 권한: **read** · 분류: **무전송 차단**
- 역할: Block get-post-contents GET /v1/contents/seller-notices/:sellerNoticeId.

        raw_content_projection_unapproved; never dispatch.

- `sellerNoticeId`: 필수 · integer · minimum=1
- 출력 최상위 필드: `channel`, `operation_id`, `status`, `reasons`, `item`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_naver_seller_notice`

### `commerce_get_naver_seller_notices`

- 권한: **read** · 분류: **무전송 차단**
- 역할: get-posts-contents GET /v1/contents/seller-notices.

        raw_content_projection_unapproved; not the single-notice GET.

- `page`: 선택 · integer · 기본값 1
- `size`: 선택 · integer · 기본값 10
- 출력 최상위 필드: `channel`, `operation_id`, `status`, `reasons`, `item`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_naver_seller_notices`

### `commerce_get_naver_settle_cases`

- 권한: **read** · 분류: **무전송 차단**
- 역할: find-settle-by-case-pay-settle GET /v1/pay-settle/settle/case.

        order_linked_purchaser_unapproved; privacy boundary, never dispatch.

- `pageNumber`: 필수 · JSON
- `pageSize`: 필수 · JSON
- `periodType`: 선택 · JSON · 기본값 null
- `searchDate`: 선택 · JSON · 기본값 null
- 출력 최상위 필드: `channel`, `operation_id`, `status`, `reasons`, `item`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_naver_settle_cases`

### `commerce_get_naver_size_type`

- 권한: **read** · 분류: **독립 제공자 READ**
- 역할: get-size-type-vo-product GET /v1/product-sizes/:sizeTypeId; closed single object.
        sizeTypeId: int64 id from commerce_get_naver_size_types;
        a digit string is also accepted.

- `sizeTypeId`: 필수 · integer
- 출력 최상위 필드: `channel`, `operation_id`, `status`, `reasons`, `item`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_naver_size_type`

### `commerce_get_naver_size_types`

- 권한: **read** · 분류: **독립 제공자 READ**
- 역할: Read GET /v1/product-sizes with a closed nested-field projection.
- 입력: `{}` (인자 없음)
- 출력 최상위 필드: `channel`, `operation_id`, `status`, `items`, `page_count`, `total_count`, `has_more`, `next_cursor`, `reasons`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_naver_size_types`

### `commerce_get_naver_sku`

- 권한: **read** · 분류: **독립 제공자 READ**
- 역할: get-ns-detail-nfa-product GET /v2/logistics/products/sellers/me/skus/:nsId.

        Supported subset [A-Za-z0-9]{1,20}; other ids never dispatch. Closed catalog.

- `nsId`: 필수 · string
- 출력 최상위 필드: `channel`, `operation_id`, `status`, `reasons`, `item`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_naver_sku`

### `commerce_get_naver_sku_product_mappings`

- 권한: **read** · 분류: **무전송 차단**
- 역할: get-linked-products-nfa-product GET.

        /v1/logistics/products/sellers/me/skus/:nsId/product-mappings.
        identifier_pattern_uncontracted; never dispatch.

- `nsId`: 필수 · string
- `page`: 선택 · integer · 기본값 1
- `size`: 선택 · integer · 기본값 50
- 출력 최상위 필드: `channel`, `operation_id`, `status`, `reasons`, `item`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_naver_sku_product_mappings`

### `commerce_get_naver_sku_v1`

- 권한: **read** · 분류: **독립 제공자 READ**
- 역할: get-ns-detail-1-nfa-product GET /v1/logistics/products/sellers/me/skus/:nsId.

        Deprecated provider version 1, supported alphanumeric subset only;
        closed catalog, absent stays absent. No v2 fallback or stock inference.

- `nsId`: 필수 · string
- 출력 최상위 필드: `channel`, `operation_id`, `status`, `reasons`, `item`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_naver_sku_v1`

### `commerce_get_naver_solution_transactions`

- 권한: **read** · 분류: **무전송 차단**
- 역할: Block get-transactions-merchant GET /v1/commerce-solutions/transactions.

        account_identifier_projection_unapproved; never dispatch.

- `paymentConfirmStartDate`: 필수 · string
- `paymentConfirmEndDate`: 필수 · string
- `transactionId`: 선택 · JSON · 기본값 null
- `originalTransactionId`: 선택 · JSON · 기본값 null
- `solutionName`: 선택 · JSON · 기본값 null
- `transactionType`: 선택 · enum ["FREE_TRIAL", "PAYMENT", "UPGRADE", "DOWNGRADE", "REFUND"] · 기본값 null
- `planId`: 선택 · JSON · 기본값 null
- `accountUid`: 선택 · JSON · 기본값 null
- 출력 최상위 필드: `channel`, `operation_id`, `status`, `reasons`, `item`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_naver_solution_transactions`

### `commerce_get_naver_standard_options`

- 권한: **read** · 분류: **독립 제공자 READ**
- 역할: Read GET /v1/options/standard-options (get-standard-option-by-category-product).
- `categoryId`: 필수 · string · pattern="^[1-9][0-9]{0,17}$"
- 출력 최상위 필드: `channel`, `operation_id`, `status`, `reasons`, `item`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_naver_standard_options`

### `commerce_get_naver_sub_origin_areas`

- 권한: **read** · 분류: **독립 제공자 READ**
- 역할: Read GET /v1/product-origin-areas/sub-origin-areas; query = parent area code (optional).
- `query`: 선택 · string | null · 기본값 null
- `page_size`: 선택 · integer · 기본값 100 · minimum=1 · maximum=100
- `cursor`: 선택 · string | null · 기본값 null
- 출력 최상위 필드: `channel`, `kind`, `status`, `items`, `page_count`, `total_count`, `has_more`, `next_cursor`, `reasons`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_naver_sub_origin_areas`

### `commerce_get_naver_subcategories`

- 권한: **read** · 분류: **독립 제공자 READ**
- 역할: get-sub-category-product GET /v1/categories/:categoryId/sub-categories.

        Alphanumeric path subset max200 (local); safe child-category array, no facade.

- `categoryId`: 필수 · string
- 출력 최상위 필드: `channel`, `operation_id`, `status`, `reasons`, `items`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_naver_subcategories`

### `commerce_get_naver_subscription_status`

- 권한: **read** · 분류: **무전송 차단**
- 역할: Block get-subscription-merchant GET /v1/commerce-solutions/subscriptions/:accountUid.

        account_identifier_projection_unapproved; never transport.

- `accountUid`: 필수 · string
- 출력 최상위 필드: `channel`, `operation_id`, `status`, `reasons`, `item`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_naver_subscription_status`

### `commerce_get_naver_today_dispatch`

- 권한: **read** · 분류: **무전송 차단**
- 역할: Block get-today-dispatch-sellers GET /v1/seller/this-day-dispatch.

        account_id_projection_unapproved; never transport.

- 입력: `{}` (인자 없음)
- 출력 최상위 필드: `channel`, `operation_id`, `status`, `reasons`, `item`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_naver_today_dispatch`

### `commerce_get_naver_vat_case_declarations`

- 권한: **read** · 분류: **무전송 차단**
- 역할: Block GET /v1/pay-settle/vat/case before transport: PII review pending.
- `startDate`: 필수 · string
- `endDate`: 필수 · string
- `pageNumber`: 필수 · integer · minimum=1
- `pageSize`: 필수 · integer · maximum=1000
- 출력 최상위 필드: `channel`, `operation_id`, `status`, `reasons`, `item`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_naver_vat_case_declarations`

### `commerce_get_order_detail`

- 권한: **read** · 분류: **공용 채널 조회**
- 역할: Return one canonical order without customer PII.
- `channel`: 필수 · Channel
- `order_ref`: 필수 · string · minLength=1 · maxLength=200
- 출력 최상위 필드: `schema_version`, `status`, `channel`, `item`, `reasons`, `errors`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_order_detail`

### `commerce_get_orders`

- 권한: **read** · 분류: **공용 채널 조회**
- 역할: Return one bounded canonical order page from an active adapter.
- `channel`: 필수 · Channel
- `page_size`: 선택 · integer · 기본값 50 · minimum=1 · maximum=100
- `cursor`: 선택 · string | null · 기본값 null
- `business_date`: 선택 · string | null · 기본값 null
- `collection_mode`: 선택 · enum ["rolling_30_day", "exact_day"] · 기본값 "rolling_30_day"
- 출력 최상위 필드: `schema_version`, `status`, `channel`, `next_cursor`, `reasons`, `errors`, `items`, `summary`, `groups`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_orders`

### `commerce_get_product_content`

- 권한: **read** · 분류: **공용 채널 조회**
- 역할: Read canonical detail-page content without raw provider payloads.
- `channel`: 필수 · Channel
- `external_product_id`: 필수 · string · minLength=1 · maxLength=200
- 출력 최상위 필드: `schema_version`, `status`, `channel`, `item`, `reasons`, `errors`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_product_content`

### `commerce_get_product_detail`

- 권한: **read** · 분류: **공용 채널 조회**
- 역할: Return metadata and exact-ID option rows. Opt in to bounded Coupang stock GETs.

        Naver observed base sale price and provider option-price component remain
        separate; neither is asserted as a discounted final customer price.

- `channel`: 필수 · Channel
- `external_product_id`: 필수 · string · minLength=1 · maxLength=200
- `include_option_inventory`: 선택 · boolean · 기본값 false
- 출력 최상위 필드: `schema_version`, `status`, `channel`, `item`, `reasons`, `errors`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_product_detail`

### `commerce_get_product_image`

- 권한: **read** · 분류: **이미지 READ**
- 역할: Return original PNG/JPEG/GIF/WebP bytes for an observed image reference.

        References come from product content image_refs or option_image_groups.
        They expire after one hour and require the same running MCP process.
        Never accepts arbitrary URLs, emits source URLs, or sends credentials.

- `asset_ref`: 필수 · string · pattern="^commerce-asset-v1:[a-p]{64}$"
- 출력: MCP native image content. JSON output schema 없음; 반환된 asset_ref만 사용합니다.
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_product_image`

### `commerce_get_products`

- 권한: **read** · 분류: **공용 채널 조회**
- 역할: Return one bounded canonical product page without SKU inference.
- `channel`: 필수 · Channel
- `page_size`: 선택 · integer · 기본값 50 · minimum=1 · maximum=100
- `cursor`: 선택 · string | null · 기본값 null
- 출력 최상위 필드: `schema_version`, `status`, `channel`, `next_cursor`, `reasons`, `errors`, `items`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_products`

### `commerce_get_returns`

- 권한: **read** · 분류: **공용 채널 조회**
- 역할: Return one bounded claim and return page without customer PII.
- `channel`: 필수 · Channel
- `page_size`: 선택 · integer · 기본값 50 · minimum=1 · maximum=100
- `cursor`: 선택 · string | null · 기본값 null
- `kind`: 선택 · enum ["cancel", "return", "exchange"] | null · 기본값 null
- 출력 최상위 필드: `schema_version`, `status`, `channel`, `next_cursor`, `reasons`, `errors`, `items`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_returns`

### `commerce_get_rg_category_metadata`

- 권한: **read** · 분류: **독립 제공자 READ**
- 역할: Read bounded shared metadata for an RFM-listed category, not RG-only proof.
- `category_code`: 필수 · string · pattern="^[0-9]{1,20}$"
- 출력 최상위 필드: `status`, `is_allow_single_item`, `expiration_required`, `attributes`, `source_endpoint`, `reasons`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_rg_category_metadata`

### `commerce_get_rg_inventory_item`

- 권한: **read** · 분류: **무전송 차단**
- 역할: Block rg/inventory/summaries single item GET before transport.

        inventory_envelope_uncontracted; vendor_item_type_uncontracted.

- `vendor_item_id`: 필수 · string
- 출력 최상위 필드: `channel`, `operation_id`, `method`, `official_rg_uri`, `rg_proof`, `shared_uri_promoted`, `status`, `reasons`, `items`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_rg_inventory_item`

### `commerce_get_rg_inventory_summaries`

- 권한: **read** · 분류: **무전송 차단**
- 역할: Block ambiguous RG inventory response envelope; no provider request.
- 입력: `{}` (인자 없음)
- 출력 최상위 필드: `channel`, `operation_id`, `method`, `official_rg_uri`, `rg_proof`, `shared_uri_promoted`, `status`, `items`, `reasons`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_rg_inventory_summaries`

### `commerce_get_rg_order_detail`

- 권한: **read** · 분류: **독립 제공자 READ**
- 역할: Read one RG order by supplied ID; expose digests, amounts, and no PII.
- `order_id`: 필수 · string · pattern="^[1-9][0-9]{0,19}$"
- 출력 최상위 필드: `channel`, `status`, `order_ref`, `paid_at`, `lines`, `reasons`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_rg_order_detail`

### `commerce_get_rg_order_list`

- 권한: **read** · 분류: **독립 제공자 READ**
- 역할: GET one RG order page using caller's bounded paid dates; digest identities.
- `paid_date_from`: 필수 · string · pattern="^[0-9]{8}$"
- `paid_date_to`: 필수 · string · pattern="^[0-9]{8}$"
- `next_token`: 선택 · string | null · 기본값 null
- 출력 최상위 필드: `channel`, `operation_id`, `method`, `official_rg_uri`, `rg_proof`, `shared_uri_promoted`, `status`, `items`, `next_cursor`, `reasons`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_rg_order_list`

### `commerce_get_rg_product_detail`

- 권한: **read** · 분류: **독립 제공자 READ**
- 역할: Observe documented RG/Hybrid item branches; shared URI never proves RG.
- `seller_product_id`: 필수 · string · pattern="^[1-9][0-9]{0,19}$"
- 출력 최상위 필드: `operation_id`, `method`, `status`, `rg_proof`, `shared_detail_uri_proves_rg`, `filter_scope`, `seller_product_id`, `observed_branch`, `seller_product_name`, `display_product_name`, `status_name`, `display_category_code`, `items`, `reasons`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_rg_product_detail`

### `commerce_get_rg_product_list`

- 권한: **read** · 분류: **독립 제공자 READ**
- 역할: Read RG-or-Hybrid GET seller-products; shared URI is not RG-only proof.
- `page_size`: 선택 · integer · 기본값 10 · minimum=1 · maximum=100
- `cursor`: 선택 · string | null · 기본값 null
- 출력 최상위 필드: `operation_id`, `method`, `status`, `rg_proof`, `shared_list_uri_proves_rg`, `shared_detail_uri_proves_rg`, `filter_scope`, `items`, `next_cursor`, `reasons`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_rg_product_list`

### `commerce_get_rg_rfm_category_page`

- 권한: **read** · 분류: **독립 제공자 READ**
- 역할: Page the official RG RFM tree; never truncate a malformed tree as complete.
- `page_size`: 선택 · integer · 기본값 100 · minimum=1 · maximum=100
- `cursor`: 선택 · string | null · 기본값 null
- 출력 최상위 필드: `status`, `items`, `next_cursor`, `total_count`, `source_endpoint`, `reasons`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_rg_rfm_category_page`

### `commerce_get_settlements`

- 권한: **read** · 분류: **공용 채널 조회**
- 역할: Return marketplace settlement evidence without profit calculations.
- `channel`: 필수 · Channel
- `page_size`: 선택 · integer · 기본값 50 · minimum=1 · maximum=100
- `cursor`: 선택 · string | null · 기본값 null
- 출력 최상위 필드: `schema_version`, `status`, `channel`, `next_cursor`, `reasons`, `errors`, `items`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_settlements`

### `commerce_get_toss_notice_categories`

- 권한: **read** · 분류: **독립 제공자 READ**
- 역할: Toss 상품정보제공고시 카테고리 코드 목록 (GET notices/category-codes).

        items: [{category_code, name, first_category_name, second_category_name}].

- 입력: `{}` (인자 없음)
- 출력 최상위 필드: `status`, `items`, `skipped_rows`, `reasons`, `source`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_toss_notice_categories`

### `commerce_get_toss_notice_items`

- 권한: **read** · 분류: **독립 제공자 READ**
- 역할: Toss 고시 항목 목록 for one category code (GET notices?categoryCode=).

        items: [{notice_id, title, order, required, required_basis, default_hint}] — titles
        only; content is the seller's to fill.

- `category_code`: 필수 · string · pattern="^[A-Za-z0-9_-]{1,64}$"
- 출력 최상위 필드: `status`, `category_code`, `items`, `skipped_rows`, `reasons`, `source`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_toss_notice_items`

### `commerce_get_toss_price_compare_products`

- 권한: **read** · 분류: **이번 범위 밖**
- 역할: Read seller price-comparison item IDs and safe labels, never HTML or URLs.
- `page_size`: 선택 · integer · 기본값 50 · minimum=1 · maximum=100
- `cursor`: 선택 · string | null · 기본값 null
- 출력 최상위 필드: `status`, `items`, `next_cursor`, `reason`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_toss_price_compare_products`

### `commerce_get_toss_registration_locations`

- 권한: **read** · 분류: **독립 제공자 READ**
- 역할: Toss 배송비 묶음 그룹·교환반품지 번호 (GET .../delivery-location/v2,
        GET .../exchange-refund-location/v2).

        Only {location_id, name, is_main} — never address, zip code or contact text.

- 입력: `{}` (인자 없음)
- 출력 최상위 필드: `status`, `delivery_locations`, `exchange_refund_locations`, `delivery_locations_has_more`, `exchange_refund_locations_has_more`, `skipped_rows`, `reasons`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_get_toss_registration_locations`

### `commerce_health_check`

- 권한: **read** · 분류: **로컬 전용**
- 역할: Report service mode without probing a provider.
- 입력: `{}` (인자 없음)
- 출력 최상위 필드: `schema_version`, `status`, `service`, `phase`, `transport`, `external_calls_enabled`, `credentials_enabled`, `database_enabled`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_health_check`

### `commerce_list_channels`

- 권한: **read** · 분류: **로컬 전용**
- 역할: List channel implementation, credential, and external-read states.
- 입력: `{}` (인자 없음)
- 출력 최상위 필드: `schema_version`, `status`, `channels`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_list_channels`

### `commerce_list_documented_change_operations`

- 권한: **read** · 분류: **로컬 전용**
- 역할: List documented non-read contracts, all disabled and never callable.
- `channel`: 필수 · enum ["coupang_general", "rocket_growth", "naver"]
- `page_size`: 선택 · integer · 기본값 25 · minimum=1 · maximum=50
- `cursor`: 선택 · integer · 기본값 0 · minimum=0 · maximum=1000
- 출력 최상위 필드: `status`, `items`, `next_cursor`, `total_count`, `reasons`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_list_documented_change_operations`

### `commerce_normalize_naver_keyword_pack`

- 권한: **read** · 분류: **로컬 전용**
- 역할: Normalize observed Naver keyword rows into a bounded pack; no provider calls.
- `observation`: 필수 · NaverKeywordPackObservation
- 출력 최상위 필드: `schema_version`, `status`, `search_query`, `observed_at`, `data_basis`, `organic_title_target`, `organic_title_count`, `organic_titles`, `excluded_ad_count`, `keyword_count`, `keywords`, `unavailable_volume_count`, `reasons`, `provenance`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_normalize_naver_keyword_pack`

### `commerce_prepare_detail_page_draft`

- 권한: **read** · 분류: **로컬 전용**
- 역할: Project caller-supplied facts for review only; never validate CEO approval.
- `source`: 필수 · ProductContent
- `channel`: 필수 · Channel
- `external_product_id`: 필수 · string · minLength=1 · maxLength=200
- `approved_texts`: 필수 · array
- `local_version`: 필수 · integer · minimum=1
- `image_candidates`: 선택 · array · 기본값 []
- `prior_draft`: 선택 · JSON | null · 기본값 null
- 출력 최상위 필드: `schema_version`, `status`, `channel`, `draft`, `reasons`, `draft_only`, `external_write_performed`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_prepare_detail_page_draft`

### `commerce_prepare_marketplace_product_drafts`

- 권한: **read** · 분류: **로컬 전용**
- 역할: Evaluate per-channel publish readiness locally; never call providers.
- `product`: 필수 · CanonicalCommonProduct
- `channel_configs`: 필수 · array · minItems=1
- 출력 최상위 필드: `schema_version`, `status`, `stage`, `channels`, `external_write_performed`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_prepare_marketplace_product_drafts`

### `commerce_prepare_product_content_draft`

- 권한: **read** · 분류: **로컬 전용**
- 역할: Validate a local working-lane draft; never publish or call a provider.
- `channel`: 필수 · Channel
- `external_product_id`: 필수 · string · minLength=1 · maxLength=200
- `title`: 필수 · string · minLength=1 · maxLength=1000
- `description_text`: 필수 · string · minLength=1 · maxLength=100000
- `image_urls`: 선택 · array · 기본값 []
- 출력 최상위 필드: `schema_version`, `status`, `channel`, `draft`, `reasons`, `errors`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_prepare_product_content_draft`

### `commerce_publish_coupang_product`

- 권한: **write** · 분류: **건별 승인 필요 WRITE**
- 역할: Publish one approved canonical draft to Coupang and verify it by GET.
- `draft`: 필수 · CoupangCanonicalDraft
- `approval`: 필수 · CoupangApprovalEvidence
- `idempotency_key`: 필수 · string · pattern="^[a-f0-9]{64}$"
- 출력 최상위 필드: `status`, `receipt_verified`, `seller_product_digest`, `reason`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_publish_coupang_product`

### `commerce_publish_elevenst_product`

- 권한: **write** · 분류: **건별 승인 필요 WRITE**
- 역할: Publish one approved canonical draft to 11st (euc-kr XML) and verify it by GET.
- `draft`: 필수 · ElevenstCanonicalDraft
- `approval`: 필수 · ElevenstApprovalEvidence
- `idempotency_key`: 필수 · string · pattern="^[a-f0-9]{64}$"
- 출력 최상위 필드: `status`, `receipt_verified`, `product_digest`, `reason`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_publish_elevenst_product`

### `commerce_publish_naver_product`

- 권한: **write** · 분류: **건별 승인 필요 WRITE**
- 역할: Publish one DOR-approved canonical draft to Naver and verify it by GET.
- `draft`: 필수 · NaverCanonicalDraft
- `approval`: 필수 · NaverApprovalEvidence
- `idempotency_key`: 필수 · string · pattern="^[a-f0-9]{64}$"
- 출력 최상위 필드: `status`, `receipt_verified`, `origin_product_digest`, `channel_product_digest`, `reason`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_publish_naver_product`

### `commerce_publish_toss_product`

- 권한: **write** · 분류: **건별 승인 필요 WRITE**
- 역할: Publish one approved canonical draft to Toss and verify it by GET.
- `draft`: 필수 · TossCanonicalDraft
- `approval`: 필수 · TossApprovalEvidence
- `idempotency_key`: 필수 · string · pattern="^[a-f0-9]{64}$"
- 출력 최상위 필드: `status`, `receipt_verified`, `product_digest`, `reason`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_publish_toss_product`

### `commerce_simulate_documented_change`

- 권한: **read** · 분류: **로컬 전용**
- 역할: Unconditionally block external change; no approval input or transport.
- `entry_id`: 필수 · string · pattern="^contract-[0-9a-f]{16}$"
- 출력 최상위 필드: `status`, `executed`, `transport_enabled`, `network_calls`, `ceo_per_target_approval_required`
- 정확한 전체 schema: `TOOLS.json` → name = `commerce_simulate_documented_change`
