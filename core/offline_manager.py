"""
Offline mode controller and VPN enforcement helpers for MERID.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

from core.environment import EnvironmentFlags, EnvironmentState
from core.network_client import RoutingProfile
from utils.logger import get_logger

logger = get_logger("core.offline_manager")


@dataclass
class LocalResource:
    """Represents an offline data/model resource."""

    name: str
    path: str
    description: str


class OfflineManager:
    """Toggles offline/VPN modes and tracks local resources."""

    def __init__(self) -> None:
        self._local_resources: Dict[str, LocalResource] = {}
        self._current_profile: RoutingProfile = RoutingProfile.DIRECT
        self._offline_reason: Optional[str] = None

    def register_local_resource(self, name: str, path: str, description: str) -> None:
        self._local_resources[name] = LocalResource(name, path, description)
        logger.info("Registered local resource %s (%s)", name, path)

    def enable_offline_mode(self, reason: str) -> None:
        self._offline_reason = reason
        flags = EnvironmentFlags(
            online=False,
            enforced_routing_profile=RoutingProfile.OFFLINE,
            allowed_domains=[],
            vpn_only=False,
            privacy_mode=True,
        )
        EnvironmentState.get_instance().set_flags(flags)
        logger.warning("Offline mode enabled: %s", reason)

    def enable_vpn_mode(self, profile: RoutingProfile) -> None:
        if profile not in {RoutingProfile.VPN_A, RoutingProfile.VPN_B}:
            raise ValueError("VPN mode must use VPN_A or VPN_B profile")
        self._current_profile = profile
        flags = EnvironmentFlags(
            online=True,
            enforced_routing_profile=profile,
            allowed_domains=None,
            vpn_only=True,
            privacy_mode=True,
        )
        EnvironmentState.get_instance().set_flags(flags)
        logger.info("VPN-only mode enforced via %s", profile.value)

    def disable_offline_mode(self) -> None:
        self._offline_reason = None
        flags = EnvironmentFlags(
            online=True,
            enforced_routing_profile=self._current_profile,
            allowed_domains=None,
            vpn_only=False,
            privacy_mode=False,
        )
        EnvironmentState.get_instance().set_flags(flags)
        logger.info("Offline mode disabled")

    def get_local_resource(self, name: str) -> Optional[LocalResource]:
        return self._local_resources.get(name)

    def list_local_resources(self) -> Dict[str, LocalResource]:
        return self._local_resources.copy()

    def get_offline_reason(self) -> Optional[str]:
        return self._offline_reason


_manager: Optional[OfflineManager] = None


def get_offline_manager() -> OfflineManager:
    global _manager
    if _manager is None:
        _manager = OfflineManager()
    return _manager
