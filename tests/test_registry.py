from dataclasses import dataclass

import pytest

from k12_commerce_mcp.adapters.base import CommerceAdapter
from k12_commerce_mcp.adapters.mock import MockAdapter
from k12_commerce_mcp.registry import (
    AdapterNotFoundError,
    AdapterRegistry,
    DuplicateAdapterError,
    InvalidAdapterError,
)


@dataclass(frozen=True)
class StubAdapter:
    channel: str


def test_commerce_adapter_protocol_requires_all_read_methods() -> None:
    assert not isinstance(StubAdapter("identity-only"), CommerceAdapter)
    assert isinstance(MockAdapter(), CommerceAdapter)



def test_registry_lists_registered_channel() -> None:
    registry = AdapterRegistry()
    registry.register(MockAdapter())

    assert registry.list_channels() == ("mock",)
    assert registry.get("mock").channel == "mock"


def test_registry_rejects_duplicate_channel() -> None:
    registry = AdapterRegistry([MockAdapter()])

    with pytest.raises(DuplicateAdapterError, match="mock"):
        registry.register(MockAdapter())


def test_registry_rejects_unknown_channel() -> None:
    registry = AdapterRegistry()

    with pytest.raises(AdapterNotFoundError, match="unknown"):
        registry.get("unknown")


def test_registry_rejects_incomplete_adapter() -> None:
    with pytest.raises(InvalidAdapterError, match="read-only contract"):
        AdapterRegistry([StubAdapter(channel="mock")])
