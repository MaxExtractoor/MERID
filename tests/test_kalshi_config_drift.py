"""Tests for Kalshi config drift detection and API key validation guards.

These tests ensure the fixes for config drift and 401 errors are working correctly.
"""

import pytest
from unittest.mock import MagicMock, patch
from merid.event_venues.kalshi.kalshi_config import KalshiConfig, get_kalshi_config
from merid.event_venues.kalshi.ws import KalshiWebSocket
from merid.event_venues.kalshi.client import KalshiVenueClient

pytestmark = pytest.mark.kalshi_15m


class TestConfigDriftDetection:
    """Tests for config drift detection logging."""

    def test_unified_config_has_correct_urls(self):
        """Verify unified config uses correct production URLs."""
        config = KalshiConfig(
            env="prod",
            rest_base_url="https://external-api.kalshi.com/trade-api/v2",
            ws_base_url="wss://external-api-ws.kalshi.com/trade-api/ws/v2",
            api_key_id="test_key",
            private_key_path="/path/to/key.pem",
            private_key_pem="test_pem"
        )
        
        # Verify production URLs
        assert config.rest_base_url == "https://external-api.kalshi.com/trade-api/v2"
        assert config.ws_base_url == "wss://external-api-ws.kalshi.com/trade-api/ws/v2"

    def test_demo_config_has_correct_urls(self):
        """Verify demo config uses correct demo URLs."""
        config = KalshiConfig(
            env="demo",
            rest_base_url="https://external-api.demo.kalshi.co/trade-api/v2",
            ws_base_url="wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2",
            api_key_id="test_key",
            private_key_path="/path/to/key.pem",
            private_key_pem="test_pem"
        )
        
        # Verify demo URLs
        assert config.rest_base_url == "https://external-api.demo.kalshi.co/trade-api/v2"
        assert config.ws_base_url == "wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2"

    def test_config_logging_on_ws_init(self):
        """Verify WebSocket client logs config drift detection on init."""
        config = KalshiConfig(
            env="prod",
            rest_base_url="https://external-api.kalshi.com/trade-api/v2",
            ws_base_url="wss://external-api-ws.kalshi.com/trade-api/ws/v2",
            api_key_id="test_key_12345678",
            private_key_path="/path/to/key.pem",
            private_key_pem="test_pem"
        )
        
        with patch("merid.event_venues.kalshi.ws.logger") as mock_logger:
            ws = KalshiWebSocket(config)
            
            # Verify config drift logging was called
            mock_logger.info.assert_called()
            call_args = str(mock_logger.info.call_args)
            assert "[KALSHI-CONFIG-DRIFT]" in call_args
            assert "KalshiWebSocket" in call_args
            assert "test****5678" in call_args  # Masked API key


class TestAPIKeyValidationGuards:
    """Tests for API key validation guards."""

    def test_ws_client_raises_on_missing_api_key(self):
        """Verify WebSocket client raises RuntimeError when API key is missing."""
        config = KalshiConfig(
            env="prod",
            rest_base_url="https://external-api.kalshi.com/trade-api/v2",
            ws_base_url="wss://external-api-ws.kalshi.com/trade-api/ws/v2",
            api_key_id=None,
            private_key_path="/path/to/key.pem",
            private_key_pem="test_pem"
        )
        
        with pytest.raises(RuntimeError) as exc_info:
            KalshiWebSocket(config)
        
        assert "Kalshi config missing API key" in str(exc_info.value)
        assert "config_class=" in str(exc_info.value)

    def test_ws_client_raises_on_empty_api_key(self):
        """Verify WebSocket client raises RuntimeError when API key is empty string."""
        config = KalshiConfig(
            env="prod",
            rest_base_url="https://external-api.kalshi.com/trade-api/v2",
            ws_base_url="wss://external-api-ws.kalshi.com/trade-api/ws/v2",
            api_key_id="",
            private_key_path="/path/to/key.pem",
            private_key_pem="test_pem"
        )
        
        with pytest.raises(RuntimeError) as exc_info:
            KalshiWebSocket(config)
        
        assert "Kalshi config missing API key" in str(exc_info.value)

    def test_ws_client_accepts_valid_api_key(self):
        """Verify WebSocket client accepts valid API key."""
        config = KalshiConfig(
            env="prod",
            rest_base_url="https://external-api.kalshi.com/trade-api/v2",
            ws_base_url="wss://external-api-ws.kalshi.com/trade-api/ws/v2",
            api_key_id="test_key_12345678",
            private_key_path="/path/to/key.pem",
            private_key_pem="test_pem"
        )
        
        # Should not raise
        ws = KalshiWebSocket(config)
        assert ws.config.api_key_id == "test_key_12345678"

    def test_ws_client_supports_legacy_api_key_field(self):
        """Verify WebSocket client supports legacy 'api_key' field for compatibility."""
        # Create a config-like object with legacy field
        class LegacyConfig:
            api_key = "legacy_key_12345678"
            private_key_pem = "test_pem"
            rest_base_url = "https://external-api.kalshi.com/trade-api/v2"
            ws_base_url = "wss://external-api-ws.kalshi.com/trade-api/ws/v2"
        
        config = LegacyConfig()
        
        # Should not raise - supports both api_key_id and api_key
        ws = KalshiWebSocket(config)
        assert ws.config.api_key == "legacy_key_12345678"


class TestUnifiedConfigMigration:
    """Tests verifying all clients use unified config by default."""

    def test_ws_client_uses_unified_config_by_default(self):
        """Verify WebSocket client uses unified config when no config provided."""
        with patch("merid.event_venues.kalshi.ws.get_kalshi_config") as mock_get_config:
            mock_config = KalshiConfig(
                env="prod",
                rest_base_url="https://external-api.kalshi.com/trade-api/v2",
                ws_base_url="wss://external-api-ws.kalshi.com/trade-api/ws/v2",
                api_key_id="test_key",
                private_key_path="/path/to/key.pem",
                private_key_pem="test_pem"
            )
            mock_get_config.return_value = mock_config
            
            ws = KalshiWebSocket()
            
            # Verify get_kalshi_config was called
            mock_get_config.assert_called_once()
            assert ws.config == mock_config

    def test_rest_client_uses_unified_config_by_default(self):
        """Verify REST client uses unified config when no config provided."""
        with patch("merid.event_venues.kalshi.client.get_kalshi_config") as mock_get_config:
            mock_config = KalshiConfig(
                env="prod",
                rest_base_url="https://external-api.kalshi.com/trade-api/v2",
                ws_base_url="wss://external-api-ws.kalshi.com/trade-api/ws/v2",
                api_key_id="test_key",
                private_key_path="/path/to/key.pem",
                private_key_pem="test_pem"
            )
            mock_get_config.return_value = mock_config
            
            client = KalshiVenueClient()
            
            # Verify get_kalshi_config was called
            mock_get_config.assert_called_once()
            assert client.config == mock_config


class TestConfigFieldCompatibility:
    """Tests for field name compatibility between unified and legacy configs."""

    def test_unified_config_api_key_id_field(self):
        """Verify unified config uses api_key_id field."""
        config = KalshiConfig(
            env="prod",
            rest_base_url="https://external-api.kalshi.com/trade-api/v2",
            ws_base_url="wss://external-api-ws.kalshi.com/trade-api/ws/v2",
            api_key_id="test_key",
            private_key_path="/path/to/key.pem",
            private_key_pem="test_pem"
        )
        
        assert hasattr(config, 'api_key_id')
        assert config.api_key_id == "test_key"

    def test_unified_config_private_key_pem_support(self):
        """Verify unified config supports private_key_pem field."""
        config = KalshiConfig(
            env="prod",
            rest_base_url="https://external-api.kalshi.com/trade-api/v2",
            ws_base_url="wss://external-api-ws.kalshi.com/trade-api/ws/v2",
            api_key_id="test_key",
            private_key_path="/path/to/key.pem",
            private_key_pem="test_pem_content"
        )
        
        assert hasattr(config, 'private_key_pem')
        assert config.private_key_pem == "test_pem_content"

    def test_unified_config_private_key_path_support(self):
        """Verify unified config supports private_key_path field."""
        config = KalshiConfig(
            env="prod",
            rest_base_url="https://external-api.kalshi.com/trade-api/v2",
            ws_base_url="wss://external-api-ws.kalshi.com/trade-api/ws/v2",
            api_key_id="test_key",
            private_key_path="/path/to/key.pem",
            private_key_pem=None
        )
        
        assert hasattr(config, 'private_key_path')
        assert config.private_key_path == "/path/to/key.pem"
