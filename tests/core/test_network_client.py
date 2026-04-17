"""Tests for core/network_client.py."""
import pytest
from unittest.mock import patch
from core.network_client import (
    RoutingProfile, NetworkConfig, NetworkClient, get_network_client
)


class TestRoutingProfile:
    """Test RoutingProfile enum."""

    def test_profile_values(self):
        """Test RoutingProfile enum values."""
        assert RoutingProfile.DIRECT == "direct"
        assert RoutingProfile.VPN_A == "vpn_a"
        assert RoutingProfile.VPN_B == "vpn_b"
        assert RoutingProfile.OFFLINE == "offline"


class TestNetworkConfig:
    """Test NetworkConfig dataclass."""

    def test_default_values(self):
        """Test default config values."""
        config = NetworkConfig()
        assert config.enforced_profile == RoutingProfile.DIRECT
        assert config.enforce_offline is False
        assert config.enforce_vpn_only is False
        assert config.privacy_mode is False

    def test_custom_values(self):
        """Test custom config values."""
        config = NetworkConfig(
            enforced_profile=RoutingProfile.VPN_A,
            enforce_offline=True,
            enforce_vpn_only=True,
            privacy_mode=True
        )
        assert config.enforced_profile == RoutingProfile.VPN_A
        assert config.enforce_offline is True


class TestNetworkClient:
    """Test NetworkClient singleton."""

    def test_singleton(self):
        """Test NetworkClient is thread-safe singleton."""
        # Reset for test
        NetworkClient._instance = None
        client1 = NetworkClient.get_instance()
        client2 = NetworkClient.get_instance()
        assert client1 is client2

    def test_initial_config(self):
        """Test initial config."""
        NetworkClient._instance = None
        client = NetworkClient.get_instance()
        assert client._config.enforced_profile == RoutingProfile.DIRECT

    def test_set_config(self):
        """Test setting config."""
        NetworkClient._instance = None
        client = NetworkClient.get_instance()
        new_config = NetworkConfig(
            enforced_profile=RoutingProfile.VPN_B,
            enforce_offline=True
        )
        client.set_config(new_config)
        assert client._config == new_config

    def test_register_module_profile(self):
        """Test registering module profile."""
        NetworkClient._instance = None
        client = NetworkClient.get_instance()
        client.register_module_profile("trading", RoutingProfile.VPN_A)
        assert client._module_profiles["trading"] == RoutingProfile.VPN_A

    def test_can_call_outbound_default(self):
        """Test can_call_outbound with default config."""
        NetworkClient._instance = None
        client = NetworkClient.get_instance()
        assert client.can_call_outbound("any_module") is True

    def test_can_call_outbound_offline(self):
        """Test can_call_outbound when offline enforced."""
        NetworkClient._instance = None
        client = NetworkClient.get_instance()
        client.set_config(NetworkConfig(enforce_offline=True))
        assert client.can_call_outbound("any_module") is False

    def test_can_call_outbound_vpn_only_allowed(self):
        """Test can_call_outbound with VPN-only and VPN profile."""
        NetworkClient._instance = None
        client = NetworkClient.get_instance()
        client.set_config(NetworkConfig(enforce_vpn_only=True))
        client.register_module_profile("trading", RoutingProfile.VPN_A)
        assert client.can_call_outbound("trading") is True

    def test_can_call_outbound_vpn_only_denied(self):
        """Test can_call_outbound with VPN-only and non-VPN profile."""
        NetworkClient._instance = None
        client = NetworkClient.get_instance()
        client.set_config(NetworkConfig(enforce_vpn_only=True))
        client.register_module_profile("trading", RoutingProfile.DIRECT)
        assert client.can_call_outbound("trading") is False

    def test_resolve_endpoint_success(self):
        """Test resolve_endpoint success."""
        NetworkClient._instance = None
        client = NetworkClient.get_instance()
        result = client.resolve_endpoint("trading", "https://api.example.com")
        assert result == "direct:https://api.example.com"

    def test_resolve_endpoint_offline_raises(self):
        """Test resolve_endpoint raises when offline."""
        NetworkClient._instance = None
        client = NetworkClient.get_instance()
        client.set_config(NetworkConfig(enforce_offline=True))
        with pytest.raises(RuntimeError, match="offline"):
            client.resolve_endpoint("trading", "https://api.example.com")

    def test_resolve_endpoint_vpn_only_raises(self):
        """Test resolve_endpoint raises with wrong profile in VPN-only mode."""
        NetworkClient._instance = None
        client = NetworkClient.get_instance()
        client.set_config(NetworkConfig(enforce_vpn_only=True))
        with pytest.raises(RuntimeError, match="VPN"):
            client.resolve_endpoint("trading", "https://api.example.com")

    def test_resolve_profile_custom(self):
        """Test _resolve_profile returns registered profile."""
        NetworkClient._instance = None
        client = NetworkClient.get_instance()
        client.register_module_profile("module1", RoutingProfile.VPN_A)
        profile = client._resolve_profile("module1")
        assert profile == RoutingProfile.VPN_A

    def test_resolve_profile_default(self):
        """Test _resolve_profile returns default when not registered."""
        NetworkClient._instance = None
        client = NetworkClient.get_instance()
        profile = client._resolve_profile("unknown_module")
        assert profile == RoutingProfile.DIRECT


class TestGetNetworkClient:
    """Test get_network_client helper."""

    def test_returns_client(self):
        """Test helper returns NetworkClient."""
        NetworkClient._instance = None
        client = get_network_client()
        assert isinstance(client, NetworkClient)
