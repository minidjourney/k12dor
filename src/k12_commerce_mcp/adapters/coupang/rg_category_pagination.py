"""Local pagination for an already-read RG category tree.

Callers pass the local node list. This module does not call a provider.
page_size must be an int from 1 to 100. Each page is a stable preorder of
closed fields only: display_category_code, name, status, depth, and
parent_code. The cursor stores the next offset and a digest of the full
walk; a changed tree raises drift instead of continuing. Cycle, depth,
total, malformed child, unsafe name, invalid node, and duplicate code
raise an incomplete error and return no page. A tree inside the bounds
is never shortened into a page that looks finished. The observed RFM
read (one root, 18,741 nested nodes, depth 6) is inside the defaults.
extract_category_nodes turns a documented display-categories payload
into the node list. The response table declares data as an array while
the captured example shows a single ROOT object, so a lone object is
wrapped once and anything else stops the walk before it begins.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass

from ...security import safe_display_value


class RgCategoryRequestError(ValueError):
    """Closed local pagination request failure. Never includes a tree payload."""


class RgCategoryDriftError(ValueError):
    """Tree identity changed between pages. Never includes node text."""


_INCOMPLETE_REASONS = frozenset(
    {
        "cycle",
        "depth",
        "duplicate_code",
        "invalid_node",
        "malformed_child",
        "total",
        "unsafe_name",
    }
)


class RgCategoryIncompleteError(ValueError):
    """Walk stopped before a complete closed tree. Never includes node text."""

    def __init__(self, reason: str) -> None:
        if reason not in _INCOMPLETE_REASONS:
            raise ValueError("invalid incomplete reason")
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class RgCategoryTreeNode:
    display_category_code: str
    name: str
    status: str
    depth: int
    parent_code: str | None


@dataclass(frozen=True)
class RgCategoryTreePage:
    items: tuple[RgCategoryTreeNode, ...]
    next_cursor: str | None
    total: int


_CLOSED_STATUSES = frozenset({"ACTIVE", "READY", "DISABLED"})
_DIGITS = re.compile(r"^[0-9]{1,20}$")
_CURSOR = re.compile(r"[A-Za-z0-9_-]+")
_DIGEST = re.compile(r"[0-9a-f]{64}")
MAX_PAGE_SIZE = 100
# Observed RFM read: one root plus 18,741 nested nodes, depth 6.
# These bounds must cover that tree. Exceeding them is an explicit error,
# never a shortened page that looks finished.
MAX_DEPTH = 16
MAX_TOTAL_NODES = 25_000
_MAX_CURSOR_LENGTH = 256


def _category_code(value: object) -> str | None:
    if type(value) is int and value >= 0:
        text = str(value)
    elif isinstance(value, str):
        text = value
    else:
        return None
    if _DIGITS.fullmatch(text) is None:
        return None
    return text


def _walk(
    nodes: object,
    parent_code: str | None,
    depth: int,
    out: list[RgCategoryTreeNode],
    seen_ids: set[int],
    seen_codes: set[str],
) -> None:
    if not isinstance(nodes, list):
        raise RgCategoryIncompleteError("invalid_node")
    for node in nodes:
        if id(node) in seen_ids:
            raise RgCategoryIncompleteError("cycle")
        if depth > MAX_DEPTH:
            raise RgCategoryIncompleteError("depth")
        if not isinstance(node, dict) or not isinstance(node.get("child"), list):
            raise RgCategoryIncompleteError("malformed_child")
        table_code = _category_code(node.get("displayCategoryCode"))
        example_code = _category_code(node.get("displayItemCategoryCode"))
        code = table_code if "displayCategoryCode" in node else example_code
        name = node.get("name")
        status = node.get("status")
        if isinstance(name, str) and name != "" and safe_display_value(name) is None:
            raise RgCategoryIncompleteError("unsafe_name")
        if (
            code is None
            or not isinstance(name, str)
            or name == ""
            or status not in _CLOSED_STATUSES
        ):
            raise RgCategoryIncompleteError("invalid_node")
        if len(out) >= MAX_TOTAL_NODES:
            raise RgCategoryIncompleteError("total")
        if code in seen_codes:
            raise RgCategoryIncompleteError("duplicate_code")
        seen_ids.add(id(node))
        seen_codes.add(code)
        out.append(
            RgCategoryTreeNode(
                display_category_code=code,
                name=name,
                status=status,
                depth=depth,
                parent_code=parent_code,
            )
        )
        _walk(node["child"], code, depth + 1, out, seen_ids, seen_codes)


def _digest(nodes: tuple[RgCategoryTreeNode, ...]) -> str:
    payload = [
        [node.display_category_code, node.name, node.status, node.depth, node.parent_code]
        for node in nodes
    ]
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def _encode_cursor(offset: int, digest: str) -> str:
    raw = json.dumps(
        {"v": 1, "offset": offset, "digest": digest},
        separators=(",", ":"),
    )
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def _decode_cursor(cursor: str | None) -> tuple[int, str | None]:
    if cursor is None:
        return 0, None
    if (
        not isinstance(cursor, str)
        or len(cursor) > _MAX_CURSOR_LENGTH
        or _CURSOR.fullmatch(cursor) is None
    ):
        raise RgCategoryRequestError("invalid cursor")
    try:
        padded = cursor + ("=" * (-len(cursor) % 4))
        data = json.loads(base64.urlsafe_b64decode(padded))
    except (ValueError, TypeError, UnicodeError):
        raise RgCategoryRequestError("invalid cursor") from None
    if (
        not isinstance(data, dict)
        or set(data) != {"v", "offset", "digest"}
        or data["v"] != 1
        or type(data["offset"]) is not int
        or not 0 <= data["offset"] <= MAX_TOTAL_NODES
        or not isinstance(data["digest"], str)
        or _DIGEST.fullmatch(data["digest"]) is None
        or _encode_cursor(data["offset"], data["digest"]) != cursor
    ):
        raise RgCategoryRequestError("invalid cursor")
    return data["offset"], data["digest"]


def validate_category_cursor(cursor: str | None) -> None:
    """Reject a malformed cursor before a caller performs any I/O.

    Structural validation only. Tree drift is still detected inside
    paginate_rg_category_tree once the walked digest is known.
    """
    _decode_cursor(cursor)


def extract_category_nodes(payload: object) -> list[object]:
    """Return the raw node list from a display-categories payload.

    data is documented as an array of category objects. The captured
    official example instead carries a single ROOT object, so one bare
    dict is wrapped into a one-element list. Any other shape is an
    incomplete tree, never a partial one.
    """
    if not isinstance(payload, dict):
        raise RgCategoryIncompleteError("invalid_node")
    data = payload.get("data")
    if isinstance(data, dict):
        return [data]
    if isinstance(data, list):
        return data
    raise RgCategoryIncompleteError("invalid_node")


def paginate_rg_category_tree(
    nodes: object,
    *,
    page_size: int,
    cursor: str | None = None,
) -> RgCategoryTreePage:
    if type(page_size) is not int or not 1 <= page_size <= MAX_PAGE_SIZE:
        raise RgCategoryRequestError("invalid page_size")
    offset, prior_digest = _decode_cursor(cursor)
    walked: list[RgCategoryTreeNode] = []
    _walk(nodes, None, 1, walked, set(), set())
    total = len(walked)
    digest = _digest(tuple(walked))
    if prior_digest is not None and prior_digest != digest:
        raise RgCategoryDriftError("drift")
    if offset > total or (offset == total and offset != 0):
        raise RgCategoryRequestError("invalid cursor")
    page = tuple(walked[offset : offset + page_size])
    end = offset + len(page)
    next_cursor = _encode_cursor(end, digest) if end < total else None
    return RgCategoryTreePage(items=page, next_cursor=next_cursor, total=total)
