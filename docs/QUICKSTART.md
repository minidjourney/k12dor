# 바로 적용 가이드

[README](../README.md) · [MCP 앱 연결](MCP_CLIENTS.md) · [전체 도구](TOOLS.md)

## 1. 대상 PC에 설치

기본 안내 대상은 Linux/macOS이며 Windows는 WSL을 권장합니다. 네이티브 Windows의 인증 파일 권한 동작과 실제 타 PC 설치는 검증하지 않았습니다.

Git·uv·Python 3.11이 준비된 PC에서:

```bash
git clone https://github.com/minidjourney/k12dor.git
cd k12dor
uv sync --frozen --python 3.11
uv run python scripts/smoke_offline.py
```

프로젝트는 `>=3.11,<3.12`를 요구합니다. uv가 Python을 찾지 못하면 Python 3.11을 먼저 준비하세요. `uv sync`는 해당 PC에 의존성을 설치하며 PyPI 접근이 필요할 수 있습니다. README의 설치 안내가 현재 서버의 설치 변경을 수행한다는 뜻은 아닙니다.

## 2. 인증 파일 준비 — 실제 조회를 사용할 때만

라이브 CLI는 현재 사용자의 **`~/.config/dor/marketplace-readonly.env`**만 읽습니다. 일반 셸 환경변수나 AI 앱의 `env`에 쇼핑몰 키를 넣는 것으로 대신할 수 없습니다. 파일 경로의 `dor`는 이름일 뿐 DOR 설치가 READ의 필수조건은 아닙니다.

반드시 일반 파일·현재 사용자 소유·권한 `0600`이어야 하고 symlink는 거부됩니다. 기존 파일이 있으면 새 템플릿으로 덮어쓰지 마세요.

아래는 새 PC에서 파일이 아직 없을 때만 사용하는 준비 예시입니다. **템플릿에는 인증값이 없으며** 사용자 본인이 안전한 로컬 편집기로 실제 값을 입력해야 합니다. 값에 따옴표를 붙이지 않고 `KEY=value`로 적으세요.

```bash
umask 077
mkdir -p "$HOME/.config/dor"
if [ ! -e "$HOME/.config/dor/marketplace-readonly.env" ] && [ ! -L "$HOME/.config/dor/marketplace-readonly.env" ]; then
  install -m 600 examples/marketplace-readonly.env.template "$HOME/.config/dor/marketplace-readonly.env"
fi
```

읽는 이름:

- 쿠팡 일반·RG: `DOR_COUPANG_VENDOR_ID`, `DOR_COUPANG_ACCESS_KEY`, `DOR_COUPANG_SECRET_KEY`
- 네이버: `DOR_NAVER_CLIENT_ID`, `DOR_NAVER_CLIENT_SECRET`
- 토스 쇼핑: `DOR_TOSS_SHOPPING_ACCESS_KEY`, `DOR_TOSS_SHOPPING_SECRET_KEY`

한 채널의 필수 값이 모두 있어야 그 채널의 adapter/client가 구성됩니다. 사용하지 않는 채널은 빈 값으로 두세요. 빈 템플릿의 존재만으로 실계정 조회가 활성화되지는 않습니다. 키는 각 제공자가 발급하며 별도의 계정 권한/IP 조건 등이 적용될 수 있습니다.

**READ 시작에는 `DOR_APPROVAL_DATABASE`나 `DOR_NAVER_ASSET_ROOT`를 설정하지 마세요.** 이 항목들은 실제 상품 등록 executor의 전제조건입니다. 등록 기능은 별도 검토와 건별 승인이 필요합니다. 인증 파일을 Git·Wiki·채팅·로그에 넣지 마세요.

## 3. AI 앱과 연결

[연결 예시](MCP_CLIENTS.md)의 `command`를 설치된 저장소의 `.venv/bin/k12-commerce-mcp` **절대 경로**로 바꾸세요. MCP 앱이 subprocess를 시작하고 stdin/stdout으로 통신합니다. 터미널에서 `uv run k12-commerce-mcp`를 실행했을 때 화면이 조용한 것은 대화형 CLI가 아니라 stdio 서버이기 때문입니다.

모의 사용만 원하면 `.venv/bin/k12-commerce-mcp-mock`을 사용합니다. 모의 `mock` 결과를 실제 주문/매출로 해석하지 마세요.

## 4. 첫 확인

AI 앱에서 아래 순서로 요청하세요.

1. `commerce_health_check` — 서버 모드 확인; 쇼핑몰 연결 성공 확인 아님.
2. `commerce_list_channels` — 인증 구성/활성 상태 확인; 키의 유효성 probe 아님.
3. `commerce_get_capabilities` + `channel: naver` 또는 사용할 채널 — 지원/보류 경계 확인.
4. 사용할 채널의 `commerce_get_products`를 작은 `page_size`로 조회 — 여기부터 실제 제공자 호출 가능.

`unavailable`·`unsupported`·`blocked`를 정상 조회나 값 0으로 해석하지 마세요.

## 5. 문제 해결

- Python 버전 오류: Python 3.11과 잠금 파일 기준 환경을 사용합니다.
- 라이브 서버 시작 거부: 인증 파일 존재·소유자·0600·symlink 여부를 확인합니다. 파일 내용이나 키를 로그에 출력하지 않습니다.
- `adapter_not_configured`: 해당 채널의 필수 항목이 모두 있는지 확인합니다.
- 인증 실패/403: 제공자의 앱 권한·키 상태·허용 IP를 확인합니다. 자동으로 새 키를 생성하거나 계정을 변경하지 않습니다.
- `rate_limited`: 오류의 retryable/제공자 제한을 확인하고 제한을 존중합니다. 무한 재시도하지 않습니다.
- 도구가 안 보임: 앱 실행 명령의 절대 경로, 서버 시작 실패, 클라이언트 도구 필터를 확인합니다. 등록 수와 현재 사용할 수 있는 기능 수는 다릅니다.
- 이미지 ref 만료: 같은 MCP 프로세스에서 content/detail을 다시 조회해 새 `asset_ref`를 얻습니다.
- 원격 접속이 안 됨: 기본 연결은 stdio이고 HTTP 모듈도 loopback 전용입니다. GitHub 업로드가 네트워크 배포는 아닙니다.
