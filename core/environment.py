"""
Environment flags and context shared across agents and services.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from core.network_client import NetworkConfig, RoutingProfile, get_network_client


@dataclass
class EnvironmentFlags:
    """Represents current environment constraints."""

    online: bool = True
    enforced_routing_profile: RoutingProfile = RoutingProfile.DIRECT
    allowed_domains: Optional[List[str]] = None
    vpn_only: bool = False
    privacy_mode: bool = False


class EnvironmentState:
    """Singleton environment state."""

    _instance: Optional["EnvironmentState"] = None

    def __init__(self) -> None:
        self._flags = EnvironmentFlags()

    @classmethod
    def get_instance(cls) -> "EnvironmentState":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def set_flags(self, flags: EnvironmentFlags) -> None:
        self._flags = flags
        network_client = get_network_client()
        network_client.set_config(
            NetworkConfig(
                enforced_profile=flags.enforced_routing_profile,
                enforce_offline=not flags.online,
                enforce_vpn_only=flags.vpn_only,
                privacy_mode=flags.privacy_mode,
            )
        )

    def get_flags(self) -> EnvironmentFlags:
        return self._flags


def get_environment_flags() -> EnvironmentFlags:
    """Helper for modules/agents."""
    return EnvironmentState.get_instance().get_flags()
