# 공개 저장소 동기화 규칙

이 저장소(`minidjourney/k12dor`)는 K12에서 실제로 돌리는 Commerce MCP의 **공개용 사본**입니다. 실행본을 그대로 올리지 않고, 아래 규칙대로 옮기고 바꾼 뒤 검사를 통과한 것만 올립니다. 커밋·푸시는 운영자가 승인한 뒤에만 합니다.

## 1. 옮기는 범위

- 옮긴다: `src/`, `tests/`, `scripts/` 아래 파일 중 실행본과 달라진 것과 새로 생긴 것.
- 옮기지 않는다: `README.md`·`docs/`·`examples/`(공개본 것을 유지하고 필요한 곳만 손으로 고친다), `*.egg-info/`, `__pycache__/`, `.bak`·실험 파일, 빌드 산출물, 운영 메모(`SPEC-*.md`, `tasks/`, 내부 `docs/`).
- 공개본에만 있는 `scripts/export_tool_catalog.py`, `scripts/smoke_offline.py`는 지우지 않는다.

## 2. 공개용 바꾸기 목록

옮긴 뒤 공개본에서만 아래처럼 바꿉니다. 실제 값은 이 문서에도 적지 않습니다(운영 쪽 비공개 기록에만 둡니다). 공개할 때마다 같은 규칙을 다시 적용합니다.

| # | 찾을 꼴 | 바꿀 값 | 들어 있는 곳 (2026-10-10 기준) |
|---|---|---|---|
| 1 | 내부 Tailscale 주소 `k12-server.<내부 tailnet 이름>.ts.net` | `k12-server.example.ts.net` | `src/k12_commerce_mcp/publishing/elevenst.py`, `tests/test_elevenst_publish.py`, `tests/test_elevenst_publish_xml.py`, `tests/test_noi_optional_images.py` |
| 2 | 1번의 정규식 이스케이프 꼴 `k12-server\.<내부 tailnet 이름>\.ts\.net` | `k12-server\.example\.ts\.net` | `src/k12_commerce_mcp/publishing/elevenst.py` |
| 3 | 실제 네이버 상품 번호(11자리) — 시험 예시 값 | 가짜 번호 `98765432100`(원상품)·`98765432101`·`98765432102`(채널상품) | `tests/test_naver_registration_defaults.py` |
| 4 | 실제 네이버 채널상품 번호를 든 주석 예시 | `1xxxxxxxxxx` | `src/k12_commerce_mcp/naver_registration_defaults.py` |
| 5 | 실제 서버 사용자 홈 경로 `/home/<운영 계정>/` — 시험 입력 | `/home/example/` | `tests/test_commerce_publish_tool_script.py` |

주의:

- 1·2번 때문에 공개본의 11번가 등록기는 사진 주소로 `https://k12-server.example.ts.net/11st/…`만 받습니다. 공개본을 그대로 설치해서는 11번가 등록에 쓸 수 없습니다(자리 표시 주소).
- 바꾼 뒤 남은 원래 값이 0건인지 검색으로 확인합니다.

## 3. 올리기 전 검사 (새로 들어가는 줄 전부)

검사 결과는 수로만 남기고, 걸린 값을 그대로 출력하지 않습니다.

1. 키·토큰·비밀번호 꼴: `Bearer`, `secret`, `api_key`, `token=`, 40자 넘는 영숫자, `-----BEGIN`. 시험 속 값은 `synthetic`처럼 가짜임이 드러나야 합니다.
2. 내부 호스트·IP: `ts.net`, `100.64.0.0/10`, `192.168.`, `10.`·`172.16-31.`, `127.0.0.1:포트`, `k12-server`.
3. 내부 경로: `/home/<운영 계정>`, `/ai/`, `/data/`. 9/30 공개본에 이미 있던 줄은 두고, 새로 늘어난 수를 기록합니다.
4. 실제 판매자·상점 ID: 쿠팡 vendorId(`A00…`), 네이버 채널 번호, 1688 회원 ID.
5. 전화·이메일·주소 꼴: `010-1234-5678`, `example.com`처럼 가짜임이 드러나는 값만 둡니다.
6. 실제 상품·주문 번호: 새 줄의 8자리 이상 숫자를 운영 DB(읽기 전용)의 모든 칸과 대조합니다. 날짜(`2026…`)와 네이버 공개 분류 번호(`500…`)처럼 공개 값은 그대로 두고, 상품·주문 번호와 겹치면 2번 표에 더하고 가짜 값으로 바꿉니다.
7. 실제 API 응답 덩어리, 실제 이미지·바이너리 파일이 없는지 봅니다.

## 4. 시험

```bash
uv sync --frozen --all-groups --python 3.11
uv run python -c "import k12_commerce_mcp; print(k12_commerce_mcp.__file__)"   # 이 checkout 의 src 를 가리켜야 한다
uv run pytest -p no:cacheprovider
uv run ruff check src tests scripts
uv run python scripts/smoke_offline.py
uv run python scripts/export_tool_catalog.py   # docs/TOOLS.md·TOOLS.json 다시 만들기
```

- `export_tool_catalog.py`는 새 도구의 분류를 「추가 검토 필요」로 둡니다. `docs/TOOLS.json`에서 분류를 정한 뒤 한 번 더 돌리고, README·`docs/`의 도구 수를 맞춥니다. 새 도구는 [변경 기록](CHANGES.md)에 한국어 한 줄 설명을 더합니다.
- 일부 대조 시험은 비공개 Wiki 스냅샷이 없으면 다른 PC에서 결과가 다를 수 있습니다([VERIFICATION](VERIFICATION.md)).

## 5. 올리기

- 실행본 폴더에서 직접 푸시하지 않습니다. 이 저장소를 따로 받은 공개용 checkout에서만 커밋합니다.
- 인증 파일·`.env`·DB·로그는 `.gitignore`가 막지만, 커밋 전 바뀐 파일 목록을 다시 봅니다.
- 푸시는 운영자 승인 뒤에 하고, 원격 커밋 번호를 다시 읽어 확인합니다.
