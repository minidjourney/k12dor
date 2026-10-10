# 구조와 개발 안내

## 진입점

- `k12-commerce-mcp`: 실제 구성의 stdio 서버. 시작 시 로컬 인증 파일을 읽지만 health/channels/capabilities는 제공자 probe를 하지 않습니다.
- `k12-commerce-mcp-mock`: 합성 mock 채널의 오프라인 stdio 서버.
- `k12-commerce-mcp-11st-public`: 11번가 공개 카테고리 GET opt-in(인증값을 붙이지 않음). 판매자 인증 READ·등록은 이 진입점과 별개로 인증 파일에 `DOR_11ST_API_KEY`가 있을 때만 구성됩니다.
- `k12-commerce-mcp-remote`: Bearer 보호 Streamable HTTP. 기본 host는 127.0.0.1이고 접근키 미구성은 시작 거부. 원격 네트워크 배포는 별도 범위.

## 파일 구조

- `src/k12_commerce_mcp/server.py`: MCP 도구 등록/진입점/합성·실계정 composition
- `permissions.py`: 정확한 READ/WRITE 도구 manifest
- `credentials.py`: owner·0600·일반 파일 검증과 로컬 인증 loader
- `clients/`: 제공자별 transport/인증/입출력 계약
- `adapters/`, `service/`, `models/`: canonical 투영·지원 capability·안전 모델
- `*_mcp.py`: 독립 조회/차단/등록 참고 기능
- `product_options.py`, `product_images.py`, `image_assets.py`, `clients/product_assets.py`: 옵션/이미지 출처·RAM ref·bounded 공개 CDN 취득
- `publishing/`, `composition.py`, `write_gate.py`: 건별 승인·idempotency·readback 경계
- `simulations/`: 외부 전송 없는 계약 시뮬레이션
- `tests/`: 모의 제공자 응답/합성 fixtures. 실제 인증값·실계정 결과를 넣지 않습니다.
- `scripts/`: 명시적으로 실행하는 브리지/계약 빌더/감사 스크립트. 파일 존재가 자동화 활성화를 뜻하지 않습니다.

## 설계 원칙

고객 개인정보·provider 원문을 canonical 결과에 그대로 넘기지 않으며 확정되지 않은 값이나 연결을 만들어내지 않습니다. 일반 쿠팡과 RG source를 분리하고 provider의 페이지/상태/nullable 근거를 보존합니다. 실행 가능한 원본 HTML을 돌려주지 않습니다. 로컬 초안과 실제 외부 변경은 다른 도구/전제조건으로 분리합니다.

## 명령

```bash
uv sync --frozen --all-groups --python 3.11
uv run pytest tests/test_minimal_server.py tests/test_permissions.py tests/test_models.py tests/test_security.py tests/test_error_handling.py
uv run ruff check src tests
uv run python scripts/smoke_offline.py
uv run python scripts/export_tool_catalog.py
uv build --wheel
```

전체 `uv run pytest`에는 K12의 비공개 Wiki HTML 스냅샷·별도 계약 문서가 필요한 일부 대조 시험도 있습니다. 해당 원본은 공개 패키지에 포함하지 않으므로 타 PC에서 전체 2,992건을 그대로 재현한다고 보장하지 않습니다. 위 명령은 이 의존성이 없는 기본 모의 시험 선택입니다.

lock은 공개 PyPI를 사용합니다. 설치/빌드 도구의 네트워크·환경 변경은 실행자가 승인한 환경에서만 수행하세요. 이 저장소에는 CI workflow·systemd·cron 자동 활성화를 추가하지 않았습니다.
