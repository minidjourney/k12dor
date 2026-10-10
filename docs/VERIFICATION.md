# 검증 기록과 해석 범위

## 구현 검증 기록 — 2026-09-30

- 공개 source와 동일한 구현의 기존 전체 회귀 기록: **2,992 passed, 619.48초**.
- 기존 wheel 직접 시험 기록: **185 passed**. 이번 문서 공개 단계에서 해당 시험을 다시 실행한 것은 아닙니다.
- 공개 준비에서 `src/k12_commerce_mcp`의 Python 파일 **141개**가 회귀 시 고정한 SHA-256과 동일함을 대조했습니다.
- 이 전체 회귀에는 K12의 로컬 공식 문서 스냅샷/별도 계약 문서 대조도 포함되므로, 원본을 미배포한 다른 PC에서 동일한 2,992건을 그대로 재현한다고 주장하지 않습니다.

## 2026-10-10 동기화에서 직접 확인

- 실제 MCP `list_tools`의 전체 등록 **146개**와 permission manifest 일치(`scripts/export_tool_catalog.py`, 제공자 호출 0).
- READ 권한 142 / WRITE 권한 4. READ에는 무전송 차단 53개 등이 포함됩니다.
- 전체 시험(K12의 Python 3.11 가상환경에서 `PYTHONPATH`로 공개 checkout의 `src`를 앞세워 실행, 불러온 패키지 경로가 checkout인지 먼저 확인): **3,371개 중 3,341 통과, 실패 30**. 실패 30개는 2026-09-30 공개본을 같은 방법으로 돌린 결과(2,992개 중 2,962 통과, 실패 30)와 이름까지 같습니다.
  - 28개: 공개하지 않은 K12 내부 계약 문서(네이버 공식 읽기 계약, 3채널 작업 목록)가 없어서 실패합니다.
  - 2개: `tests/test_stdio_e2e.py`가 checkout 안의 `.venv/bin/k12-commerce-mcp-mock`을 찾는데, 시험한 자리에 가상환경이 없어 실패합니다. `uv sync`로 만든 checkout에서는 이 파일이 생깁니다.
- `ruff check src tests scripts` 통과.
- `scripts/smoke_offline.py`: 오프라인 mock stdio에서 도구 146개 등록, `commerce_health_check`의 `status=complete`, `external_calls_enabled=false`·`credentials_enabled=false`·`database_enabled=false`.
- 새로 들어간 줄 전부를 키·내부 주소·내부 경로·판매자 ID·연락처·실제 상품/주문 번호 꼴로 검사했습니다([PUBLISHING](PUBLISHING.md) 3절). 실제 값은 공개용 바꾸기로 지웠습니다.

## 2026-09-30 공개 준비에서 직접 확인

- 실제 MCP `list_tools`의 전체 등록 **136개**와 permission manifest 일치.
- READ 권한 133 / WRITE 권한 3. READ에는 무전송 차단 53개 등이 포함됩니다.
- 공개 checkout의 source로 실행한 별도 **오프라인 mock stdio subprocess**에서 전체 도구 목록 일치 및 `commerce_health_check`의 `status=complete` 확인.
- 그 health 결과의 `external_calls_enabled=false`, `credentials_enabled=false`, `database_enabled=false` 확인. 실제 쇼핑몰 조회/인증/DB 쓰기 검증이 아닙니다.
- 추가한 도구 목록 생성·소형 확인 스크립트의 Ruff 검사 통과. 첫 문서 스크립트 검사에서 길이/포맷 오류가 있었으며 수정 후 통과했습니다.
- 실제 데이터·인증 파일·내부 Wiki/운영 로그는 공개 파일 목록에서 제외합니다. 소스 테스트의 실패/거부용 합성 입력을 실데이터로 취급하지 않습니다.

## 실제 조회 기록의 제한

기존 구현 단계에서 RG 공용/독립 상세의 판매가와 네이버 본문 4장, 쿠팡 일반/RG 본문 각 3장 취득을 확인한 기록이 있습니다. 식별자·URL·이미지 원본·응답 body는 공개하지 않습니다. 특정 표본 성공이 모든 상품의 지속적 취득을 보장하지 않습니다.

네이버 표준옵션 이미지 그룹의 공식 구조를 지원하지만 확인한 실제 상품 표본에는 해당 그룹이 없어 실제 양성 검증은 미완료입니다.

## 확인하지 않은 것

- 다른 물리 PC의 실제 설치·API 연결
- 모든 공식 API 또는 모든 계정/상품/기간의 성공
- 원격 네트워크 실제 운영과 접근키 발급
- 실제 상품 등록/수정/삭제
- DOR 대시보드 배포·서비스 재시작·원장 변경

`complete_all_official_functions`는 **false**입니다. 등록 수·시험 통과·실조회 기록·설치/운영 완료를 혼동하지 마세요.
