"""Fail-closed channel adapter registry."""

from collections.abc import Iterable

from .adapters.base import CommerceAdapter


class AdapterRegistryError(LookupError):
    """Base class for registry lookup and registration failures."""


class AdapterNotFoundError(AdapterRegistryError):
    """Raised when a requested channel has no registered adapter."""


class DuplicateAdapterError(AdapterRegistryError):
    """Raised when a channel is registered more than once."""


class InvalidAdapterError(AdapterRegistryError):
    """Raised when an object does not implement the read-only adapter contract."""


class AdapterRegistry:
    """Owns the explicit set of available channel adapters."""

    def __init__(self, adapters: Iterable[CommerceAdapter] = ()) -> None:
        self._adapters: dict[str, CommerceAdapter] = {}
        for adapter in adapters:
            self.register(adapter)

    def register(self, adapter: CommerceAdapter) -> None:
        if not isinstance(adapter, CommerceAdapter):
            raise InvalidAdapterError("adapter does not satisfy the read-only contract")
        channel = adapter.channel
        if channel in self._adapters:
            raise DuplicateAdapterError(f"adapter already registered: {channel}")
        self._adapters[channel] = adapter

    def get(self, channel: str) -> CommerceAdapter:
        try:
            return self._adapters[channel]
        except KeyError as exc:
            raise AdapterNotFoundError(f"adapter not registered: {channel}") from exc

    def list_channels(self) -> tuple[str, ...]:
        return tuple(sorted(self._adapters))
