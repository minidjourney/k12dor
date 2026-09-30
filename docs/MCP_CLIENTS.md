# MCP 앱 연결

[설치 가이드](QUICKSTART.md) · [사용법](USAGE.md)

## 일반 stdio MCP 앱

Claude Desktop 등 `mcpServers` 형식을 사용하는 앱의 **기존 설정에 이 항목을 병합**합니다. 설정 전체를 덮어쓰지 마세요. 앱마다 설정 파일 위치와 지원 범위가 다르므로 해당 앱의 안내도 확인하세요.

```json
{
  "mcpServers": {
    "k12-commerce": {
      "command": "/ABSOLUTE/PATH/k12dor/.venv/bin/k12-commerce-mcp",
      "args": []
    }
  }
}
```

`/ABSOLUTE/PATH`는 예시이며 설치한 PC의 실제 절대 경로로 교체합니다. 모의 서버로 시작하려면 마지막 실행파일을 `k12-commerce-mcp-mock`으로 바꿉니다. 실제 인증정보는 MCP JSON에 넣지 않습니다. subprocess를 실행하는 사용자의 HOME 아래 인증 파일을 준비합니다.

## Hermes Agent

Hermes는 일반 MCP 앱의 `mcpServers`가 아니라 **`mcp_servers`** 설정을 사용합니다. 활성 프로필의 `$HERMES_HOME/config.yaml` 범위를 선택하고 공식 설정 명령으로 지정하세요. 다음은 **대상 PC에서 사용자가 실행하는 예시**이며 기존 설정을 그대로 보존합니다.

```bash
hermes config set mcp_servers.k12-commerce.command /ABSOLUTE/PATH/k12dor/.venv/bin/k12-commerce-mcp
hermes config set mcp_servers.k12-commerce.args '[]'
hermes config set mcp_servers.k12-commerce.timeout 180
hermes config set mcp_servers.k12-commerce.connect_timeout 60
```

프로필을 지정할 때는 `hermes -p PROFILE config set ...` 형태를 사용합니다. 프로필 이름은 해당 환경의 실제 이름으로 교체합니다. 실제 서버 재시작이나 프로필 변경은 운영자의 승인 범위에 맞게 수행하세요. 이번 공개 작업은 Hermes 서비스 재시작이나 사용자 앱 설정 변경을 하지 않습니다.

참고 설정 형태:

```yaml
mcp_servers:
  k12-commerce:
    command: /ABSOLUTE/PATH/k12dor/.venv/bin/k12-commerce-mcp
    args: []
    timeout: 180
    connect_timeout: 60
```

Hermes 내부 도구 이름에는 `mcp_서버명_도구명` 접두사가 붙을 수 있습니다. 서버 등록의 136개와 AI 앱이 필터링 후 노출하는 개수는 다를 수 있습니다. 공식 참고: https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp

## 원격 HTTP는 별도 배포

`k12-commerce-mcp-remote` 모듈은 Bearer 보호와 loopback 제한을 포함하지만 현재 빠른 적용 안내는 **각 PC의 stdio 설치**입니다. 타 PC에서 K12의 프로세스를 공유하는 네트워크·터널·인증키 발급은 이 저장소를 clone한다고 자동 적용되지 않습니다. 공인 포트·방화벽·DNS를 변경하거나 인증키를 발급하는 것은 별도 승인 대상입니다. 원격 실제 운영은 검증하지 않았습니다.
