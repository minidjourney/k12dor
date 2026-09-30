"""Commerce service entry point and channel discovery operations."""

from __future__ import annotations

from ..models import (
    CapabilitiesResult,
    Capability,
    Channel,
    ChannelDescriptor,
    ChannelListResult,
    CredentialState,
    HealthResult,
    ImplementationStatus,
)
from ..permissions import LOCAL_PROVIDER_METHOD_TOOL_NAMES, READ_TOOL_NAMES
from ..registry import AdapterRegistry
from .claims import ClaimsServiceMixin
from .dispatch import DispatchMixin
from .finance import FinanceServiceMixin
from .inventory import InventoryServiceMixin
from .keywords import KeywordsServiceMixin
from .orders import OrdersServiceMixin
from .products import ProductsServiceMixin
from .registration import RegistrationServiceMixin


class CommerceService(
    OrdersServiceMixin,
    ProductsServiceMixin,
    InventoryServiceMixin,
    ClaimsServiceMixin,
    FinanceServiceMixin,
    KeywordsServiceMixin,
    RegistrationServiceMixin,
    DispatchMixin,
):
    """Coordinates MCP tools without embedding channel-specific logic."""

    def __init__(
        self,
        registry: AdapterRegistry,
        *,
        phase: str = "1A",
        external_calls_enabled: bool = False,
        credentials_enabled: bool = False,
        credential_states: dict[Channel, CredentialState] | None = None,
    ) -> None:
        self.registry = registry
        self.phase = phase
        self.external_calls_enabled = external_calls_enabled
        self.credentials_enabled = credentials_enabled
        self.credential_states = dict(credential_states or {})

    def health_check(self) -> HealthResult:
        return HealthResult(
            phase=self.phase,
            external_calls_enabled=self.external_calls_enabled,
            credentials_enabled=self.credentials_enabled,
        )

    def list_channels(self) -> ChannelListResult:
        planned = (
            (Channel.MOCK, "Mock"),
            (Channel.COUPANG, "쿠팡 전체 (분리 반환)"),
            (Channel.COUPANG_GENERAL, "쿠팡 일반"),
            (Channel.COUPANG_ROCKET_GROWTH, "쿠팡 로켓그로스"),
            (Channel.NAVER, "네이버"),
            (Channel.ELEVENST, "11번가"),
            (Channel.TOSS_STORE, "토스스토어"),
        )
        registered = set(self.registry.list_channels())
        return ChannelListResult(
            channels=tuple(
                ChannelDescriptor(
                    channel=channel,
                    display_name=display_name,
                    implementation_status=(
                        ImplementationStatus.ACTIVE
                        if channel.value in registered
                        else ImplementationStatus.DEFERRED
                    ),
                    credential_state=self.credential_states.get(
                        channel,
                        CredentialState.NOT_CHECKED,
                    ),
                    external_calls_enabled=(
                        self.external_calls_enabled
                        and channel.value in registered
                        and channel is not Channel.MOCK
                    ),
                )
                for channel, display_name in planned
            )
        )

    def get_capabilities(self, channel: Channel) -> CapabilitiesResult:
        is_registered = channel.value in self.registry.list_channels()
        adapter = self.registry.get(channel.value) if is_registered else None
        return CapabilitiesResult(
            channel=channel,
            capabilities=tuple(
                Capability(
                    tool_name=name,
                    implementation_status=(
                        ImplementationStatus.ACTIVE
                        if adapter is not None
                        and (
                            name in adapter.capabilities or name in LOCAL_PROVIDER_METHOD_TOOL_NAMES
                        )
                        else ImplementationStatus.DEFERRED
                    ),
                    provider_method=(
                        "MOCK"
                        if adapter is not None
                        and channel is Channel.MOCK
                        and name in adapter.capabilities
                        else (
                            "LOCAL"
                            if adapter is not None and name in LOCAL_PROVIDER_METHOD_TOOL_NAMES
                            else (
                                (
                                    "POST+GET"
                                    if channel is Channel.NAVER and name == "commerce_get_inventory"
                                    else (
                                        "POST"
                                        if (
                                            channel is Channel.NAVER
                                            and name == "commerce_get_products"
                                        )
                                        else "GET"
                                    )
                                )
                                if adapter is not None and name in adapter.capabilities
                                else None
                            )
                        )
                    ),
                )
                for name in READ_TOOL_NAMES
            ),
        )
