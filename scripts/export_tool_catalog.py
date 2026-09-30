"""Generate the full tool catalogue offline; never probes a marketplace."""

import asyncio
import json
from collections import Counter
from pathlib import Path

from mcp import Client

from k12_commerce_mcp.permissions import default_tool_policies
from k12_commerce_mcp.server import build_server

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "docs" / "TOOLS.json"


def type_label(field: dict) -> str:
    if "$ref" in field:
        return field["$ref"].rsplit("/", 1)[-1]
    if "anyOf" in field:
        return " | ".join(type_label(part) for part in field["anyOf"])
    if "enum" in field:
        return "enum " + json.dumps(field["enum"], ensure_ascii=False)
    return field.get("type", "JSON")


async def main() -> None:
    prior = json.loads(CATALOG.read_text()) if CATALOG.exists() else {"tools": []}
    classifications = {item["name"]: item["classification"] for item in prior["tools"]}
    policies = {policy.name: policy.permission.value for policy in default_tool_policies()}
    async with Client(build_server()) as client:
        tools = (await client.list_tools()).tools
    assert {tool.name for tool in tools} == set(policies)
    rows = [
        {
            "name": tool.name,
            "description": tool.description,
            "permission": policies[tool.name],
            "classification": classifications.get(tool.name, "추가 검토 필요"),
            "input_schema": tool.input_schema,
            "output_schema": tool.output_schema,
        }
        for tool in sorted(tools, key=lambda item: item.name)
    ]
    counts = dict(Counter(row["classification"] for row in rows))
    document = {
        "registered_count": len(rows),
        "permission_counts": dict(Counter(row["permission"] for row in rows)),
        "classification_counts": counts,
        "complete_all_official_functions": False,
        "source": (
            "offline MCP list_tools + permissions.py; "
            "classification is reviewed metadata, not a live probe"
        ),
        "tools": rows,
    }
    CATALOG.parent.mkdir(parents=True, exist_ok=True)
    CATALOG.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n")
    lines = [
        "# 전체 MCP 도구 목록",
        "",
        f"현재 서버 등록 **{len(rows)}개**. READ 권한에는 차단·시뮬레이션·로컬 초안도 포함됩니다.",
        (
            "등록과 실제 제공자 조회 가능/성공은 다릅니다. "
            "아래 분류는 코드 계약 기반이며 현재 계정의 live probe가 아닙니다."
        ),
        (
            "정확한 nested 입력·출력 구조, enum, default, pattern과 상한은 "
            "[TOOLS.json](TOOLS.json)이 기준입니다."
        ),
        "MCP 앱의 도구 필터와 채널 인증·지원 상태에 따라 가용성이 달라집니다.",
        "",
        "## 분류별 수",
    ]
    for classification, count in sorted(counts.items()):
        lines.append(f"- {classification}: {count}개")
    lines += [
        "",
        "- 무전송 차단: 이름이 GET/READ여도 제공자 요청 없이 거부합니다.",
        (
            "- 로컬 전용: 초안·정규화·상태·무전송 시뮬레이션. "
            "일부 계약 목록에는 미배포 Wiki 원본이 필요합니다."
        ),
        (
            "- 독립 제공자 READ/공용 채널 조회/등록 참고정보 READ/이미지 READ: "
            "구현된 경로이며 인증·지원·관측 ref·안전 정책의 조건이 있습니다. "
            "현재 환경 실성공을 보장하지 않습니다."
        ),
        (
            "- 이번 범위 밖: 11번가 공개 카테고리 opt-in·토스 가격비교 별도 경로. "
            "일반 판매자 전체 API 완료 아님."
        ),
        (
            "- 건별 승인 필요 WRITE: 외부 등록 가능 코드이나 "
            "별도 executor/로컬 승인 증거가 없으면 거부합니다. "
            "설치 안내에서 활성화하지 않습니다."
        ),
        "",
        "## 도구별 계약",
    ]
    for row in rows:
        name = row["name"]
        schema = row["input_schema"]
        required = set(schema.get("required", []))
        lines += [
            "",
            f"### `{name}`",
            "",
            f"- 권한: **{row['permission']}** · 분류: **{row['classification']}**",
            f"- 역할: {row['description']}",
        ]
        if not schema.get("properties"):
            lines.append("- 입력: `{}` (인자 없음)")
        for key, field in schema.get("properties", {}).items():
            necessity = "필수" if key in required else "선택"
            default = (
                " · 기본값 " + json.dumps(field["default"], ensure_ascii=False)
                if "default" in field
                else ""
            )
            bounds = ""
            for limit in (
                "minimum",
                "maximum",
                "minItems",
                "maxItems",
                "minLength",
                "maxLength",
                "pattern",
            ):
                if limit in field:
                    bounds += f" · {limit}=" + json.dumps(field[limit], ensure_ascii=False)
            lines.append(f"- `{key}`: {necessity} · {type_label(field)}{default}{bounds}")
        if row["output_schema"] is None:
            lines.append(
                "- 출력: MCP native image content. JSON output schema 없음; "
                "반환된 asset_ref만 사용합니다."
            )
        else:
            properties = list(row["output_schema"].get("properties", {}))
            lines.append("- 출력 최상위 필드: " + ", ".join(f"`{key}`" for key in properties))
        lines.append(f"- 정확한 전체 schema: `TOOLS.json` → name = `{name}`")
    (ROOT / "docs" / "TOOLS.md").write_text(
        "\n".join(line.rstrip() for line in "\n".join(lines).splitlines()) + "\n"
    )
    print(
        json.dumps(
            {
                "registered_count": len(rows),
                "permission_counts": document["permission_counts"],
                "classification_counts": counts,
                "provider_calls": 0,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
