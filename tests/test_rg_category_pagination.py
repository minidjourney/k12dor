"""Local RG category-tree pagination. No provider transport."""

import inspect

import pytest

from k12_commerce_mcp.adapters.coupang import rg_category_pagination as pagination
from k12_commerce_mcp.adapters.coupang.rg_category_pagination import (
    MAX_DEPTH,
    MAX_TOTAL_NODES,
    RgCategoryDriftError,
    RgCategoryIncompleteError,
    RgCategoryRequestError,
    RgCategoryTreeNode,
    paginate_rg_category_tree,
)
from k12_commerce_mcp.security import assert_agent_safe_value


def test_page_size_must_be_an_int_from_1_to_100() -> None:
    for page_size in (0, 101, -1, True, False, 1.0, "10", None):
        with pytest.raises(RgCategoryRequestError):
            paginate_rg_category_tree([], page_size=page_size)


def test_empty_tree_returns_an_empty_complete_page() -> None:
    page = paginate_rg_category_tree([], page_size=1)

    assert page.items == ()
    assert page.next_cursor is None
    assert page.total == 0


def test_one_leaf_keeps_only_closed_fields() -> None:
    page = paginate_rg_category_tree(
        [
            {
                "displayCategoryCode": "69182",
                "displayItemCategoryCode": 1,
                "name": "synthetic-category",
                "status": "ACTIVE",
                "child": [],
                "note": "do-not-echo",
            }
        ],
        page_size=100,
    )

    assert page.total == 1
    assert page.next_cursor is None
    assert page.items == (
        RgCategoryTreeNode(
            display_category_code="69182",
            name="synthetic-category",
            status="ACTIVE",
            depth=1,
            parent_code=None,
        ),
    )
    rendered = repr(page)
    assert "displayItemCategoryCode" not in rendered
    assert "do-not-echo" not in rendered
    assert set(page.items[0].__dataclass_fields__) == {
        "display_category_code",
        "name",
        "status",
        "depth",
        "parent_code",
    }


def test_official_example_item_category_code_is_accepted_when_table_code_absent() -> None:
    page = paginate_rg_category_tree(
        [
            {
                "displayItemCategoryCode": 0,
                "name": "ROOT",
                "status": "ACTIVE",
                "child": [
                    {
                        "displayItemCategoryCode": 69182,
                        "name": "synthetic",
                        "status": "ACTIVE",
                        "child": [],
                    }
                ],
            }
        ],
        page_size=2,
    )
    assert [(node.display_category_code, node.parent_code) for node in page.items] == [
        ("0", None), ("69182", "0")
    ]


def test_table_category_code_takes_precedence_over_separate_item_code() -> None:
    page = paginate_rg_category_tree(
        [
            {
                "displayCategoryCode": "123",
                "displayItemCategoryCode": 456,
                "name": "synthetic",
                "status": "ACTIVE",
                "child": [],
            }
        ],
        page_size=1,
    )
    assert page.items[0].display_category_code == "123"


def _leaf(code: str) -> dict[str, object]:
    return {
        "displayCategoryCode": code,
        "name": f"node-{code}",
        "status": "ACTIVE",
        "child": [],
        "secret_note": "do-not-echo",
    }


def test_nested_nodes_keep_parent_and_depth_without_child_payload() -> None:
    page = paginate_rg_category_tree(
        [
            {
                "displayCategoryCode": "1",
                "name": "node-1",
                "status": "READY",
                "extra": "drop-me",
                "child": [
                    _leaf("2"),
                    {
                        "displayCategoryCode": 3,
                        "name": "node-3",
                        "status": "DISABLED",
                        "child": [_leaf("4")],
                    },
                ],
            }
        ],
        page_size=10,
    )

    assert page.total == 4
    assert page.next_cursor is None
    assert [
        (item.display_category_code, item.depth, item.parent_code, item.status)
        for item in page.items
    ] == [
        ("1", 1, None, "READY"),
        ("2", 2, "1", "ACTIVE"),
        ("3", 2, "1", "DISABLED"),
        ("4", 3, "3", "ACTIVE"),
    ]
    assert "child" not in page.items[0].__dataclass_fields__
    assert "drop-me" not in repr(page)
    assert "do-not-echo" not in repr(page)


def test_tree_larger_than_200_pages_without_dropping_nodes() -> None:
    children = [_leaf(str(index)) for index in range(2, 203)]
    roots = [
        {
            "displayCategoryCode": "1",
            "name": "node-1",
            "status": "ACTIVE",
            "child": children,
        }
    ]

    first = paginate_rg_category_tree(roots, page_size=100)
    assert first.total == 202
    assert len(first.items) == 100
    assert first.next_cursor is not None
    assert first.items[0].display_category_code == "1"
    assert first.items[1].parent_code == "1"

    second = paginate_rg_category_tree(roots, page_size=100, cursor=first.next_cursor)
    assert len(second.items) == 100
    assert second.total == 202
    assert second.next_cursor is not None
    assert second.items[0].display_category_code == "101"

    third = paginate_rg_category_tree(roots, page_size=50, cursor=second.next_cursor)
    assert [item.display_category_code for item in third.items] == ["201", "202"]
    assert third.next_cursor is None
    assert third.total == 202

    seen = [item.display_category_code for item in first.items]
    seen.extend(item.display_category_code for item in second.items)
    seen.extend(item.display_category_code for item in third.items)
    assert seen == [str(index) for index in range(1, 203)]
    assert "do-not-echo" not in repr((first, second, third))


def test_changed_tree_invalidates_the_cursor_digest() -> None:
    roots = [
        {
            "displayCategoryCode": "1",
            "name": "node-1",
            "status": "ACTIVE",
            "child": [_leaf("2"), _leaf("3")],
        }
    ]
    first = paginate_rg_category_tree(roots, page_size=1)
    assert first.next_cursor is not None

    roots[0]["child"][1]["name"] = "node-3b"
    with pytest.raises(RgCategoryDriftError) as raised:
        paginate_rg_category_tree(roots, page_size=1, cursor=first.next_cursor)

    assert "node-3b" not in str(raised.value)
    assert "node-3b" not in repr(raised.value)


def test_cycle_is_an_explicit_incomplete_error() -> None:
    node: dict[str, object] = {
        "displayCategoryCode": "1",
        "name": "node-1",
        "status": "ACTIVE",
        "child": [],
    }
    node["child"] = [node]

    with pytest.raises(RgCategoryIncompleteError) as raised:
        paginate_rg_category_tree([node], page_size=1)

    assert raised.value.reason == "cycle"
    assert "node-1" not in str(raised.value)

    shared = _leaf("8")
    alias = {
        "displayCategoryCode": "9",
        "name": "node-9",
        "status": "ACTIVE",
        "child": [shared, shared],
    }
    with pytest.raises(RgCategoryIncompleteError) as alias_raised:
        paginate_rg_category_tree([alias], page_size=10)
    assert alias_raised.value.reason == "cycle"


def _chain(depth: int) -> list[dict[str, object]]:
    node: dict[str, object] = {
        "displayCategoryCode": str(depth),
        "name": f"node-{depth}",
        "status": "ACTIVE",
        "child": [],
    }
    for index in range(depth - 1, 0, -1):
        node = {
            "displayCategoryCode": str(index),
            "name": f"node-{index}",
            "status": "ACTIVE",
            "child": [node],
        }
    return [node]


def test_depth_past_the_bound_is_incomplete_not_truncated() -> None:
    assert MAX_DEPTH >= 6
    allowed = paginate_rg_category_tree(_chain(6), page_size=10)
    assert allowed.total == 6
    assert allowed.items[-1].depth == 6
    at_bound = paginate_rg_category_tree(_chain(MAX_DEPTH), page_size=100)
    assert at_bound.total == MAX_DEPTH
    assert at_bound.items[-1].depth == MAX_DEPTH

    with pytest.raises(RgCategoryIncompleteError) as raised:
        paginate_rg_category_tree(_chain(MAX_DEPTH + 1), page_size=100)

    assert raised.value.reason == "depth"
    assert raised.value.reason not in {"truncated", "invalid category shape"}


def test_total_past_the_bound_is_incomplete_not_a_short_page() -> None:
    assert MAX_TOTAL_NODES >= 18_742
    over = [
        {
            "displayCategoryCode": "1",
            "name": "node-1",
            "status": "ACTIVE",
            "child": [_leaf(str(index)) for index in range(2, MAX_TOTAL_NODES + 2)],
        }
    ]

    with pytest.raises(RgCategoryIncompleteError) as raised:
        paginate_rg_category_tree(over, page_size=100)

    assert raised.value.reason == "total"

    exact = [
        {
            "displayCategoryCode": "1",
            "name": "node-1",
            "status": "ACTIVE",
            "child": [_leaf(str(index)) for index in range(2, MAX_TOTAL_NODES + 1)],
        }
    ]
    page = paginate_rg_category_tree(exact, page_size=1)
    assert page.total == MAX_TOTAL_NODES
    assert len(page.items) == 1
    assert page.next_cursor is not None


def test_malformed_child_is_incomplete_and_not_skipped() -> None:
    valid = _leaf("2")
    root = {
        "displayCategoryCode": "1",
        "name": "node-1",
        "status": "ACTIVE",
    }
    cases = (
        {**root, "child": "nope"},
        {**root, "child": {"sneaky": 1}},
        {**root, "child": None},
        root,
        {**root, "child": [valid, "bad-child"]},
    )

    for case in cases:
        with pytest.raises(RgCategoryIncompleteError) as raised:
            paginate_rg_category_tree([case], page_size=10)
        assert raised.value.reason == "malformed_child"
        assert "sneaky" not in str(raised.value)
        assert "bad-child" not in str(raised.value)


def test_pii_name_is_incomplete_and_not_echoed() -> None:
    names = ("010-1234-5678", "buyer@example.com", "서울시 강남구 테헤란로 1")
    for name in names:
        node = {
            "displayCategoryCode": "9",
            "name": name,
            "status": "ACTIVE",
            "child": [],
            "phone": "010-9999-8888",
            "customer_email": "hidden@example.com",
        }
        with pytest.raises(RgCategoryIncompleteError) as raised:
            paginate_rg_category_tree([node], page_size=1)
        rendered = f"{raised.value} {raised.value!r}"
        assert raised.value.reason == "unsafe_name"
        assert name not in rendered
        assert "010-9999-8888" not in rendered
        assert "hidden@example.com" not in rendered


def test_invalid_node_is_incomplete_and_not_echoed() -> None:
    cases = (
        {"displayCategoryCode": "nope", "name": "node-1", "status": "ACTIVE", "child": []},
        {"displayCategoryCode": True, "name": "node-1", "status": "ACTIVE", "child": []},
        {"displayCategoryCode": "1", "name": "", "status": "ACTIVE", "child": []},
        {"displayCategoryCode": "1", "name": "node-1", "status": "HIDDEN", "child": []},
        {"displayCategoryCode": "1", "name": 7, "status": "ACTIVE", "child": []},
        {"data": []},
    )
    for node in cases:
        with pytest.raises(RgCategoryIncompleteError) as raised:
            paginate_rg_category_tree([node] if node != {"data": []} else node, page_size=1)
        assert raised.value.reason == "invalid_node"
        assert "HIDDEN" not in str(raised.value)
        assert "nope" not in str(raised.value)


def test_duplicate_code_is_incomplete_not_deduped() -> None:
    with pytest.raises(RgCategoryIncompleteError) as raised:
        paginate_rg_category_tree([_leaf("7"), _leaf("7")], page_size=10)

    assert raised.value.reason == "duplicate_code"
    assert len(raised.value.reason) < 40


def test_malformed_cursor_is_rejected_without_a_page() -> None:
    roots = [_leaf("1")]
    for cursor in ("", "@@@", 3, "x" * 300, "not-a-cursor"):
        with pytest.raises(RgCategoryRequestError) as raised:
            paginate_rg_category_tree(roots, page_size=1, cursor=cursor)
        assert "node-1" not in str(raised.value)
        assert raised.value.args == ("invalid cursor",)


def test_paginator_has_no_provider_transport() -> None:
    parameters = inspect.signature(paginate_rg_category_tree).parameters
    assert "transport" not in parameters
    assert "client" not in parameters
    source = inspect.getsource(pagination)
    assert "httpx" not in source
    assert "CoupangClient" not in source
    assert "exchange(" not in source


def test_issued_page_is_agent_safe() -> None:
    page = paginate_rg_category_tree(
        [
            {
                "displayCategoryCode": "1",
                "name": "node-1",
                "status": "ACTIVE",
                "child": [_leaf("2")],
                "phone": "010-1111-2222",
            }
        ],
        page_size=1,
    )
    assert page.next_cursor is not None
    assert_agent_safe_value(
        {
            "items": [
                {
                    "display_category_code": item.display_category_code,
                    "name": item.name,
                    "status": item.status,
                    "depth": item.depth,
                    "parent_code": item.parent_code,
                }
                for item in page.items
            ],
            "next_cursor": page.next_cursor,
            "total": page.total,
        }
    )
    assert "010-1111-2222" not in repr(page)
