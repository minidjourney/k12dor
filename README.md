# k12dor

## K12 Commerce MCP

쿠팡 일반·로켓그로스(RG)·네이버 스마트스토어 등의 쇼핑몰 정보를 AI 앱에서 조회하는 Python MCP 서버입니다. **이 저장소는 통합 Commerce MCP 배포용이며 DOR 대시보드 자체를 포함하지 않습니다.**

- 주 사용 방식: 각 PC에 설치하고 AI 앱과 **stdio**로 연결합니다. 공인 포트를 열 필요가 없습니다.
- 상품·옵션·가격·재고·주문·클레임·정산·수수료·카테고리/등록 참고정보를 지원 범위 내에서 안전하게 투영합니다.
- RG 판매가와 본문 이미지, 네이버 표준옵션 이미지 구조 및 본문 이미지 참조/취득을 포함합니다.
- 미확인 값은 `null` 또는 상태/사유로 표시하며 매출·정산·이익을 임의로 동일시하지 않습니다.
- **등록 도구 146개 = READ 권한 142개 + WRITE 권한 4개.** READ 권한에는 로컬 초안·시뮬레이션·무전송 차단 도구도 포함됩니다. 146개가 전부 실제 조회 가능한 API라는 뜻은 아닙니다.
- 실제 쇼핑몰 변경은 **건별 승인** 대상입니다. 기본 설치에서 변경 실행 전제조건을 설정하지 않으면 WRITE는 거부됩니다.

### 바로 시작

필요: Git, uv, Python **3.11**. 아래 명령은 설치할 대상 PC에서 실행합니다.

```bash
git clone https://github.com/minidjourney/k12dor.git
cd k12dor
uv sync --frozen --python 3.11
uv run python scripts/smoke_offline.py
```

마지막 명령은 **합성 mock 서버의 health 확인**이며 쇼핑몰을 호출하거나 실계정 연결을 확인하지 않습니다. 실제 사용에는 다음 단계가 필요합니다.

1. [바로 적용 가이드](docs/QUICKSTART.md)에 따라 해당 PC의 로컬 인증 파일을 준비합니다.
2. [MCP 앱 연결](docs/MCP_CLIENTS.md)의 stdio 실행 명령을 AI 앱에 등록합니다.
3. `commerce_list_channels`, `commerce_get_capabilities`로 해당 환경의 활성/지원 상태를 확인합니다.
4. [사용법과 예시](docs/USAGE.md)를 따라 조회합니다. 원본 식별자는 검증된 목록에서 얻은 값만 사용합니다.

**GitHub에 올라왔다고 AI 앱에 자동으로 연결되는 것은 아닙니다.** 다른 PC에는 Python 3.11·의존성과 해당 환경의 쇼핑몰 API 인증 설정이 필요합니다. 다른 PC 설치 성공은 아직 검증하지 않았습니다.

### 문서 지도

- [QUICKSTART](docs/QUICKSTART.md): Linux/macOS/WSL 설치·인증 파일·첫 실행·문제 해결
- [MCP_CLIENTS](docs/MCP_CLIENTS.md): 일반 MCP 앱 / Hermes 설정 형태
- [USAGE](docs/USAGE.md): 조회 순서·페이지·상품/이미지·오류·로컬 초안
- [TOOLS](docs/TOOLS.md): **전체 146개** 이름·역할·권한·필수/선택 인자·지원 경계
- [TOOLS.json](docs/TOOLS.json): 전체 도구의 정확한 입력·출력 JSON Schema
- [CHANGES](docs/CHANGES.md): 공개 이후 바뀐 점과 새 도구 한 줄 설명
- [LIMITATIONS](docs/LIMITATIONS.md): 차단·미지원·실검증 공백·원격/WRITE 경계
- [ARCHITECTURE](docs/ARCHITECTURE.md): 구조·진입점·보안·개발 명령
- [VERIFICATION](docs/VERIFICATION.md): 시험 종류와 확인 범위의 구분
- [PUBLISHING](docs/PUBLISHING.md): 공개 저장소 동기화 규칙과 공개용 바꾸기 목록
- [SECURITY](SECURITY.md): 인증정보·실데이터·공개 저장소 안전 수칙

### 개발 명령

```bash
uv sync --frozen --all-groups --python 3.11
uv run pytest tests/test_minimal_server.py tests/test_permissions.py tests/test_models.py tests/test_security.py tests/test_error_handling.py
uv run ruff check src tests
uv run python scripts/export_tool_catalog.py
```

테스트는 모의 응답과 합성 입력을 사용합니다. 일부 전체 계약 대조 시험은 미배포 로컬 Wiki 스냅샷/계약 문서가 필요하므로 위 명령은 휴대 가능한 기본 선택 시험입니다. `live`가 파일명에 있어도 실제 계정 데이터 파일을 배포하는 뜻은 아닙니다. 감사/호출 스크립트는 별도 명시 실행 시 외부 조회를 할 수 있으므로 자동으로 일괄 실행하지 마세요. 테스트 성공은 각 쇼핑몰의 권한·모든 API의 실작동을 증명하지 않습니다.

### 공개 범위와 라이선스

코드·합성 테스트·잠금 파일·사용 안내만 포함합니다. 실제 인증 파일, 계정별 설정, 원본 API 응답, 실제 주문/상품 데이터, 내부 Wiki 원본과 운영 로그는 포함하지 않습니다. 기존 저장소의 [Apache-2.0 LICENSE](LICENSE)를 유지합니다.
