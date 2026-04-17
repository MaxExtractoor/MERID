"""Tests for core/environment.py."""
import pytest
from unittest.mock import Mock, patch
from core.environment import (
    EnvironmentFlags, EnvironmentState, get_environment_flags
)
from core.network_client import RoutingProfile


class TestEnvironmentFlags:
    """Test EnvironmentFlags dataclass."""

    def test_default_values(self):
        """Test default flag values."""
        flags = EnvironmentFlags()
        assert flags.online is True
        assert flags.enforced_routing_profile == RoutingProfile.DIRECT
        assert flags.allowed_domains is None
        assert flags.vpn_only is False
        assert flags.privacy_mode is False

    def test_custom_values(self):
        """Test custom flag values."""
        flags = EnvironmentFlags(
            online=False,
            enforced_routing_profile=RoutingProfile.VPN_A,
            allowed_domains=["example.com"],
            vpn_only=True,
            privacy_mode=True
        )
        assert flags.online is False
        assert flags.enforced_routing_profile == RoutingProfile.VPN_A
        assert flags.vpn_only is True
        assert flags.privacy_mode is True


class TestEnvironmentState:
    """Test EnvironmentState singleton."""

    def test_singleton(self):
        """Test EnvironmentState is singleton."""
        # Reset instance for test
        EnvironmentState._instance = None
        state1 = EnvironmentState.get_instance()
        state2 = EnvironmentState.get_instance()
        assert state1 is state2

    def test_initial_flags(self):
        """Test initial flags."""
        EnvironmentState._instance = None
        state = EnvironmentState.get_instance()
        flags = state.get_flags()
        assert flags.online is True

    @patch('core.environment.get_network_client')
    def test_set_flags(self, mock_get_client):
        """Test setting flags updates network client."""
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        
        EnvironmentState._instance = None
        state = EnvironmentState.get_instance()
        
        new_flags = EnvironmentFlags(
            online=False,
            enforced_routing_profile=RoutingProfile.VPN_B,
            vpn_only=True,
            privacy_mode=True
        )
        state.set_flags(new_flags)
        
        assert state.get_flags() == new_flags
        mock_client.set_config.assert_called_once()
        call_args = mock_client.set_config.call_args[0][0]
        assert call_args.enforce_offline is True
        assert call_args.enforce_vpn_only is True
        assert call_args.privacy_mode is True


class TestGetEnvironmentFlags:
    """Test get_environment_flags helper."""

    def test_returns_flags(self):
        """Test helper returns current flags."""
        EnvironmentState._instance = None
        flags = get_environment_flags()
        assert isinstance(flags, EnvironmentFlags)
        assert flags.online is True
