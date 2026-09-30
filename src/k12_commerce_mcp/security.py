"""Security gates for Agent-visible schemas and results."""

import re
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel

FORBIDDEN_PII_FIELD_PARTS = (
    "access_token",
    "account_holder",
    "account_no",
    "address",
    "api_key",
    "authorization",
    "bank_account",
    "cookie",
    "customer_address",
    "customer_email",
    "customer_name",
    "customer_phone",
    "depositor",
    "email",
    "mobile",
    "phone",
    "purchaser",
    "raw_json",
    "raw_payload",
    "receiver",
    "refresh_token",
    "recipient",
    "telephone",
)


class PiiSchemaError(ValueError):
    """Raised when an Agent-visible schema contains a forbidden PII field."""


class PiiValueError(ValueError):
    """Raised when an Agent-visible value resembles PII, a secret, or raw JSON."""


# Canonical opaque references are HMAC-derived identifiers, not provider IDs.
# Their random hex can coincidentally contain phone/card-like digit runs, so
# validate the whole format first and exempt only this exact closed shape.
SAFE_OPAQUE_HMAC = re.compile(
    r"^(?:coupang|naver|toss)-(?:order|line|claim|cancel)-hmac-v1:[0-9a-f]{64}$"
)

UNSAFE_VALUE_PATTERNS = (
    re.compile(r"\b[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    re.compile(r"(?<!\d)(?:\+?82[- .]?)?0?1[016789][- .]?\d{3,4}[- .]?\d{4}(?!\d)"),
    re.compile(r"(?<!\d)0\d{1,2}[- .]\d{3,4}[- .]\d{4}(?!\d)"),
    re.compile(
        r"(?:(?:서울(?:특별시|시)?|부산(?:광역시|시)?|대구(?:광역시|시)?|"
        r"인천(?:광역시|시)?|광주(?:광역시|시)?|대전(?:광역시|시)?|"
        r"울산(?:광역시|시)?|세종(?:특별자치시|시)?|경기(?:도)?|"
        r"강원(?:특별자치도|도)?|충북|충청북도|충남|충청남도|전북|"
        r"전북특별자치도|전라북도|전남|전라남도|경북|경상북도|경남|"
        r"경상남도|제주(?:특별자치도|도)?)\s+"
        r"(?:[가-힣]+(?:시|군|구)\s+){0,3}|[가-힣]+(?:시|군|구)\s+)"
        r"\S+(?:대로|로|길)\s*\d+(?:-\d+)?"
    ),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~-]{8,}"),
    re.compile(r"(?i)\b(?:api[_-]?key|access[_-]?token|password|secret)\s*[:=]\s*\S{6,}"),
    re.compile(r"(?i)[?&](?:api[_-]?key|token|password|secret)=[^&\s]+"),
    re.compile(r"(?s)(?:^|[\s:(])\s*[\[{]\s*[\"']?[A-Za-z_][^}\]]*[}\]]"),
)


def assert_agent_safe_value(value: Any) -> None:
    """Reject known unsafe field names and string shapes in runtime output."""
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).lower()
            if any(part in normalized for part in FORBIDDEN_PII_FIELD_PARTS):
                raise PiiValueError(f"forbidden PII field: {key}")
            assert_agent_safe_value(child)
        return
    if isinstance(value, (list, tuple)):
        for child in value:
            assert_agent_safe_value(child)
        return
    if isinstance(value, str):
        if SAFE_OPAQUE_HMAC.fullmatch(value):
            return
        if any(pattern.search(value) for pattern in UNSAFE_VALUE_PATTERNS):
            raise PiiValueError("unsafe Agent-visible value")


def is_agent_safe_value(value: Any) -> bool:
    """Return True when a value survives the Agent-safety scan."""
    try:
        assert_agent_safe_value(value)
    except PiiValueError:
        return False
    return True


def safe_display_value(value: Any) -> str | None:
    """Return a display string when Agent-safe, else None."""
    if not isinstance(value, str):
        return None
    return value if is_agent_safe_value(value) else None


def assert_agent_safe_schema(model: type[BaseModel]) -> None:
    """Reject schemas containing known PII-bearing property names."""
    schema = model.model_json_schema()

    def visit(node: Any) -> None:
        if isinstance(node, Mapping):
            properties = node.get("properties")
            if isinstance(properties, Mapping):
                for field_name in properties:
                    normalized = str(field_name).lower()
                    if any(part in normalized for part in FORBIDDEN_PII_FIELD_PARTS):
                        raise PiiSchemaError(f"forbidden PII field: {field_name}")
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(schema)
