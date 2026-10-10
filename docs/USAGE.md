# 사용법과 호출 예시

[전체 도구](TOOLS.md) · [정확한 JSON Schema](TOOLS.json) · [제한](LIMITATIONS.md)

## 권장 순서

- `commerce_health_check({})`로 모드를 확인합니다. 제공자에 요청하지 않습니다.
- `commerce_list_channels({})`로 구성 상태를 확인합니다. 인증 유효성 확인은 아닙니다.
- `commerce_get_capabilities({"channel":"naver"})`처럼 채널의 지원/보류 상태를 확인합니다.
- 각 도구의 필수 인자·페이지 크기·허용값은 [전체 목록](TOOLS.md) 및 `TOOLS.json`을 따릅니다.

일반 채널 선택자는 `coupang_general`, `coupang_rocket_growth`, `naver`, `toss_store` 등이며 상세 enum은 도구별 schema가 기준입니다. 독립 RG 도구의 인자에 임의로 `channel`을 추가하지 마세요. `coupang` aggregate는 하위 scoped groups를 반환하는 경우가 있어 일반 items와 동일하게 취급하지 않습니다.

## 공용 조회 예시

아래는 **요청 예시**이지 실제 API 응답이나 실행 결과가 아닙니다.

```json
{"tool":"commerce_get_products","arguments":{"channel":"naver","page_size":5}}
{"tool":"commerce_get_products","arguments":{"channel":"coupang_rocket_growth","page_size":5}}
{"tool":"commerce_get_inventory","arguments":{"channel":"coupang_general","page_size":5}}
```

MCP 클라이언트에서는 `tool`을 도구 이름으로, `arguments`를 인자 객체로 전달합니다. 상품 detail/content 입력의 `external_product_id`에는 목록에서 확인한 실제 상품 식별자를 사용합니다. 상품명 유사도나 임의 숫자로 ID를 만들어 조회하지 않습니다. 상품 detail의 옵션 목록이 모든 필드를 보장하는 것은 아닙니다.

주문은 제공자 원본 주문 ID 대신 process-local 비식별 `order_ref`를 사용하는 상세 경로가 있습니다. 목록에서 얻은 ref를 같은 MCP 세션에서 사용하세요. RG 당일 조회의 `collection_mode="exact_day"`는 해당 공용 도구의 지원 채널에만 사용합니다. 조회창/필터 기준과 정산 기준이 같다고 추정하지 마세요.

## 상품 가격·옵션·본문 이미지

- RG는 고유 `priceData.salePrice`를 정규화합니다. 공용 detail의 `options[].listing_price`와 독립 `commerce_get_rg_product_detail`의 `rg_listing_price`를 구분합니다. 다른 가지의 가격을 가져와 채우지 않습니다.
- 이미지 역할은 대표/추가/본문/옵션/미분류로 구분하며 role과 출처가 불명확하면 임의로 연결하지 않습니다.
- 네이버 표준옵션 이미지는 공식 그룹·속성·값 ID의 `imageUrls` 구조에서 `option_image_groups`로 투영합니다. 색상 이름 유사도만으로 판매 옵션과 연결하지 않습니다.
- 상세/본문 결과의 `image_refs`에서 **반환된 `asset_ref`**를 얻어 `commerce_get_product_image`에 전달합니다.
- `commerce_get_product_image`의 인자는 `asset_ref` 하나뿐입니다. 직접 이미지 URL을 전달하지 않습니다. 결과는 JSON이 아니라 MCP native image content이며 클라이언트가 이를 지원해야 합니다.
- ref는 서버 메모리에만 보관되며 **같은 MCP 프로세스·최대 1시간** 내에 사용합니다. 재시작/만료/용량 축출 뒤에는 다시 조회해야 합니다.
- 실제 취득은 안전 정책을 통과한 공개 CDN 이미지에 한정됩니다. 로그인 이미지·임의 호스트·리다이렉트·사설 IP·위험한 형식/큰 응답은 거부될 수 있습니다. 실행 가능한 원본 HTML은 돌려주지 않습니다.
- 쿠팡 옵션별 추가 재고 조회는 공용 detail의 `include_option_inventory` opt-in을 사용합니다. 기본값은 false이며 채널 지원 여부를 확인하세요.

## 상태·페이지·금액

공용 조회는 `status`와 completeness/reasons/errors 등을 확인합니다. 독립 도구는 도구별 출력 schema가 기준이며 모두 같은 envelope라고 가정하지 마세요.

- `complete`: 해당 요청 범위를 정상 처리했음. 전체 API·전체 기간·실변경 성공을 의미하지 않습니다.
- `incomplete`: 일부 누락·보류·비식별 처리. 누락된 수량/금액을 0으로 보정하지 않습니다.
- `unavailable`: 제공자 오류·timeout·잘못된 응답·전제조건 미구성 등.
- `unsupported`: 채널/연산 미지원 또는 adapter 미구성.
- `blocked` 등: 전송 전에 차단. 조회 완료로 해석하지 않습니다.

정상 응답의 빈 items와 오류 때문에 빈 items인 상황을 구분합니다. `next_cursor`가 있으면 해당 도구가 반환한 값을 그대로 다음 요청에 넣습니다. 커서 종류·인자명·페이지 최대치는 도구마다 다릅니다.

판매가·주문액·결제액·인식 매출·정산금·수수료는 다른 근거입니다. 이 MCP는 근거 없는 이익/매출을 만들어 계산하거나 실제 판매가격을 변경하지 않습니다.

## 로컬 초안과 변경 도구

`commerce_prepare_*`, `commerce_normalize_naver_keyword_pack`, `commerce_simulate_documented_change`는 해당 계약에 따라 로컬 검증/정규화/무전송 시뮬레이션을 수행합니다. 초안 검증 성공은 쇼핑몰 등록·승인·파일 저장 완료가 아닙니다.

`commerce_publish_naver_product`, `commerce_publish_coupang_product`, `commerce_publish_toss_product`는 **WRITE**입니다. 인증정보만으로 허가되지 않으며 구성된 executor·로컬 DOR 승인 증거·승인된 정확한 draft·idempotency/readback 등의 전제조건을 만족해야 합니다. 이 공개 작업은 실제 상품 등록을 실행하거나 새로운 승인 DB를 생성하지 않습니다.

## 기존 READ 브리지 스크립트

`scripts/call_commerce_read_tool.py`는 고정 allowlist의 일부 JSON READ만 지원합니다. 모든 146개를 지원하지 않으며 native image 도구는 포함하지 않습니다.

```bash
printf '%s' '{"tool":"commerce_health_check","arguments":{}}' | uv run python scripts/call_commerce_read_tool.py
```

이 브리지는 라이브 서버를 구성하므로 인증 파일이 필요합니다. `COMMERCE_MCP_READ_SESSION=1`이면 한 줄당 요청/응답인 NDJSON 세션을 사용합니다. 전체 도구는 표준 MCP 앱으로 사용하세요.
