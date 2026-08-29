"""
Test suite for Kalshi authentication fix (2026-07-24).

Tests verify that:
1. RSA signing uses current timestamp without buffer
2. Query parameters are stripped from path before signing
3. Fills poller correctly uses get_kalshi_config() for credentials
4. Authentication headers match Kalshi API requirements
"""

import pytest
import time
import os
from unittest.mock import Mock, patch, MagicMock
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
import base64


class TestKalshiRSASigning:
    """Test RSA signing implementation matches Kalshi requirements."""
    
    def test_timestamp_without_buffer(self):
        """Verify timestamp uses current time without 30s buffer."""
        from merid.event_venues.kalshi.client import KalshiVenueClient
        from merid.event_venues.kalshi.kalshi_config import KalshiConfig
        
        # Create mock config
        config = Mock(spec=KalshiConfig)
        config.rest_base_url = "https://api.elections.kalshi.com/trade-api/v2"
        config.ws_base_url = "wss://api.elections.kalshi.com/trade-api/ws/v2"
        config.api_key_id = "test-key-id"
        config.private_key_path = "test.pem"
        config.env = "prod"
        
        # Create client with mocked private key
        client = KalshiVenueClient(config)
        
        # Mock private key
        mock_private_key = Mock()
        mock_private_key.sign.return_value = b"signature"
        client._private_key = mock_private_key
        client._auth_mode = "rsa"
        
        # Capture timestamp used in signing
        captured_timestamp = None
        original_time = time.time
        
        def capture_time():
            nonlocal captured_timestamp
            captured_timestamp = original_time()
            return captured_timestamp
        
        with patch('merid.event_venues.kalshi.client._time.time', side_effect=capture_time):
            headers = client._sign_headers("GET", "/trade-api/v2/portfolio/fills")
        
        # Verify timestamp is close to current time (within 1s)
        # Should NOT have 30s buffer
        expected_timestamp = int(captured_timestamp * 1000)
        actual_timestamp = int(headers["KALSHI-ACCESS-TIMESTAMP"])
        
        # Allow 1s tolerance for test execution time
        assert abs(actual_timestamp - expected_timestamp) < 1000, \
            f"Timestamp should be current time without buffer. Expected ~{expected_timestamp}, got {actual_timestamp}"
    
    def test_query_params_stripped_from_path(self):
        """Verify query parameters are stripped from path before signing."""
        from merid.event_venues.kalshi.client import KalshiVenueClient
        from merid.event_venues.kalshi.kalshi_config import KalshiConfig
        
        # Create mock config
        config = Mock(spec=KalshiConfig)
        config.rest_base_url = "https://api.elections.kalshi.com/trade-api/v2"
        config.ws_base_url = "wss://api.elections.kalshi.com/trade-api/ws/v2"
        config.api_key_id = "test-key-id"
        config.private_key_path = "test.pem"
        config.env = "prod"
        
        # Create client with mocked private key
        client = KalshiVenueClient(config)
        
        # Mock private key to capture signed message
        signed_message = None
        def capture_sign(message, *args, **kwargs):
            nonlocal signed_message
            signed_message = message.decode() if isinstance(message, bytes) else message
            return b"signature"
        
        mock_private_key = Mock()
        mock_private_key.sign = capture_sign
        client._private_key = mock_private_key
        client._auth_mode = "rsa"
        
        # Test with query parameters
        path_with_params = "/trade-api/v2/portfolio/fills?limit=100&cursor=abc123"
        headers = client._sign_headers("GET", path_with_params)
        
        # Verify signed message does NOT include query parameters
        assert "?" not in signed_message, \
            f"Query parameters should be stripped from signed path. Signed message: {signed_message}"
        assert "limit=100" not in signed_message, \
            f"Query parameters should be stripped. Signed message: {signed_message}"
        assert "cursor=abc123" not in signed_message, \
            f"Query parameters should be stripped. Signed message: {signed_message}"
        
        # Verify signed message uses path without query params
        assert "/trade-api/v2/portfolio/fills" in signed_message, \
            f"Signed message should include base path. Signed message: {signed_message}"
    
    def test_signature_format(self):
        """Verify signature format matches Kalshi requirements."""
        from merid.event_venues.kalshi.client import KalshiVenueClient
        from merid.event_venues.kalshi.kalshi_config import KalshiConfig
        
        # Create mock config
        config = Mock(spec=KalshiConfig)
        config.rest_base_url = "https://api.elections.kalshi.com/trade-api/v2"
        config.ws_base_url = "wss://api.elections.kalshi.com/trade-api/ws/v2"
        config.api_key_id = "test-key-id"
        config.private_key_path = "test.pem"
        config.env = "prod"
        
        # Create client with mocked private key
        client = KalshiVenueClient(config)
        
        # Mock private key
        mock_private_key = Mock()
        mock_private_key.sign.return_value = b"test_signature_bytes"
        client._private_key = mock_private_key
        client._auth_mode = "rsa"
        
        headers = client._sign_headers("GET", "/trade-api/v2/portfolio/fills")
        
        # Verify required headers are present
        assert "KALSHI-ACCESS-KEY" in headers
        assert "KALSHI-ACCESS-TIMESTAMP" in headers
        assert "KALSHI-ACCESS-SIGNATURE" in headers
        assert "Content-Type" in headers
        
        # Verify signature is base64 encoded
        try:
            decoded = base64.b64decode(headers["KALSHI-ACCESS-SIGNATURE"])
            assert decoded == b"test_signature_bytes"
        except Exception as e:
            pytest.fail(f"Signature should be base64 encoded: {e}")
        
        # Verify API key is set
        assert headers["KALSHI-ACCESS-KEY"] == "test-key-id"
        
        # Verify Content-Type is application/json
        assert headers["Content-Type"] == "application/json"


class TestFillsPollerAuthentication:
    """Test fills poller uses correct authentication."""
    
    def test_fills_poller_uses_execution_port(self):
        """Verify fills poller returns the process-wide KalshiExecutionPort."""
        from merid.event_venues.kalshi.fills_poller import FillsPoller

        poller = FillsPoller()

        with patch('merid.event_venues.kalshi.port.get_kalshi_execution_port') as mock_get_port:
            mock_port = Mock()
            mock_get_port.return_value = mock_port

            client = poller._get_client()

            # Verify the port singleton is fetched
            mock_get_port.assert_called_once()
            assert client is mock_port

    def test_fills_poller_client_caching(self):
        """Verify fills poller reuses the same port instance."""
        from merid.event_venues.kalshi.fills_poller import FillsPoller

        poller = FillsPoller()

        with patch('merid.event_venues.kalshi.port.get_kalshi_execution_port') as mock_get_port:
            mock_port = Mock()
            mock_get_port.return_value = mock_port

            client1 = poller._get_client()
            client2 = poller._get_client()

            # The port singleton is fetched each call, but the same object is returned
            assert mock_get_port.call_count == 2, \
                "get_kalshi_execution_port should be called on each access"
            assert client1 is client2, \
                "Same client instance should be returned from cache"


class TestKalshiConfigCredentialPriority:
    """Test Kalshi config credential priority and fallback."""
    
    def test_live_env_uses_live_credentials(self):
        """Verify live environment uses KALSHI_LIVE_* credentials."""
        from merid.event_venues.kalshi.kalshi_config import get_kalshi_config
        
        with patch.dict('os.environ', {
            'KALSHI_ENV': 'live',
            'KALSHI_LIVE_API_KEY_ID': 'live-key-id',
            'KALSHI_LIVE_PRIVATE_KEY_PATH': 'live.pem',
            'KALSHI_API_KEY_ID': 'generic-key-id',
            'KALSHI_PRIVATE_KEY_PATH': 'generic.pem',
        }):
            config = get_kalshi_config()
            
            # Verify live credentials are used (not generic)
            assert config.api_key_id == 'live-key-id', \
                "Should use KALSHI_LIVE_API_KEY_ID in live environment"
            assert config.private_key_path == 'live.pem', \
                "Should use KALSHI_LIVE_PRIVATE_KEY_PATH in live environment"
    
    def test_live_env_falls_back_to_generic(self):
        """Verify live environment falls back to generic credentials if live not set."""
        from merid.event_venues.kalshi.kalshi_config import get_kalshi_config
        
        # Use clear=True to ensure only the patched environment is used
        with patch.dict('os.environ', {
            'KALSHI_ENV': 'live',
            'KALSHI_API_KEY_ID': 'generic-key-id',
            'KALSHI_PRIVATE_KEY_PATH': 'generic.pem',
        }, clear=True):
            config = get_kalshi_config()
            
            # Verify generic credentials are used as fallback
            assert config.api_key_id == 'generic-key-id', \
                "Should fall back to KALSHI_API_KEY_ID"
            assert config.private_key_path == 'generic.pem', \
                "Should fall back to KALSHI_PRIVATE_KEY_PATH"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
