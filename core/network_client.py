"""
NetworkClient abstraction for MERID.
Handles offline mode, VPN routing, and privacy-preserving logging.
"""
from __future__ import annotations

import enum
import logging
import threading
from dataclasses import dataclass
from typing import Dict, Optional

logger = logging.getLogger("core.network_client")


class RoutingProfile(str, enum.Enum):
    """Supported routing profiles for outbound connectivity."""

    DIRECT = "direct"
    VPN_A = "vpn_a"
    VPN_B = "vpn_b"
    OFFLINE = "offline"


@dataclass
class NetworkConfig:
    """Runtime configuration for network behavior."""

    enforced_profile: RoutingProfile = RoutingProfile.DIRECT
    enforce_offline: bool = False
    enforce_vpn_only: bool = False
    privacy_mode: bool = False


class NetworkClient:
    """Central client for all outbound network access."""

    _instance: Optional["NetworkClient"] = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._config = NetworkConfig()
        self._module_profiles: Dict[str, RoutingProfile] = {}

    @classmethod
    def get_instance(cls) -> "NetworkClient":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def set_config(self, config: NetworkConfig) -> None:
        self._config = config
        logger.info(
            "NetworkClient config updated: profile=%s offline=%s vpn_only=%s privacy=%s",
            config.enforced_profile.value,
            config.enforce_offline,
            config.enforce_vpn_only,
            config.privacy_mode,
        )

    def register_module_profile(self, module: str, profile: RoutingProfile) -> None:
        self._module_profiles[module] = profile
        logger.debug("Module %s set to routing profile %s", module, profile.value)

    def can_call_outbound(self, module: str) -> bool:
        if self._config.enforce_offline:
            return False
        if self._config.enforce_vpn_only:
            profile = self._resolve_profile(module)
            return profile in {RoutingProfile.VPN_A, RoutingProfile.VPN_B}
        return True

    def resolve_endpoint(self, module: str, endpoint: str) -> str:
        profile = self._resolve_profile(module)
        if self._config.enforce_offline or profile == RoutingProfile.OFFLINE:
            raise RuntimeError(f"Module {module} attempted outbound call while offline: {endpoint}")
        if self._config.enforce_vpn_only and profile not in {RoutingProfile.VPN_A, RoutingProfile.VPN_B}:
            raise RuntimeError(f"Module {module} must use VPN profile. Got {profile.value}")
        self._secure_log(module, endpoint, profile)
        return f"{profile.value}:{endpoint}"

    def _resolve_profile(self, module: str) -> RoutingProfile:
        return self._module_profiles.get(module, self._config.enforced_profile)

    def _secure_log(self, module: str, endpoint: str, profile: RoutingProfile) -> None:
        if self._config.privacy_mode:
            logger.debug("Network request module=%s profile=%s", module, profile.value)
        else:
            logger.info(
                "Network request module=%s profile=%s endpoint=%s",
                module,
                profile.value,
                endpoint,
            )


def get_network_client() -> NetworkClient:
    """Helper for global access."""
    return NetworkClient.get_instance()
