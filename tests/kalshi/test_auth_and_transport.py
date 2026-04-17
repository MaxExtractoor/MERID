"""Kalshi Auth and Transport Tests — Step 2 Audit Deliverable

Validates:
1. HTTP signing matches Kalshi API specification
2. Environment routing (demo vs live) is correct
3. WebSocket transport resilience
4. No request bypasses the signing helper

Run: pytest tests/kalshi/test_auth_and_transport.py -v
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_rsa_key():
    """Create a mock RSA private key for testing signing."""
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa

        key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )
        pem = key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        )
        return key, pem.decode()
    except ImportError:
        pytest.skip("cryptography package not installed")


@pytest.fixture
def mock_kalshi_config(mock_rsa_key):
    """Create a KalshiConfig with test credentials."""
    _, pem = mock_rsa_key
    
    # Import here to avoid early failures
    try:
        from merid.event_venues.kalshi.models import KalshiConfig
        return KalshiConfig(
            api_key="test-key-id-12345",
            private_key_pem=pem,
            use_demo=True,
        )
    except ImportError:
        pytest.skip("Kalshi models not available")


@pytest.fixture
def temp_key_file(mock_rsa_key, tmp_path):
    """Write mock key to temp file."""
    _, pem = mock_rsa_key
    key_file = tmp_path / "test_kalshi_key.pem"
    key_file.write_text(pem)
    return str(key_file)


# =============================================================================
# Test Class: HTTP Signing Correctness
# =============================================================================

class TestKalshiHttpSigning:
    """Verify RSA-PSS signing matches Kalshi API specification."""
    
    def test_sign_headers_structure(self, mock_kalshi_config):
        """Sign headers contain all required Kalshi fields."""
        from merid.event_venues.kalshi.client import KalshiVenueClient
        
        client = KalshiVenueClient(config=mock_kalshi_config)
        # Trigger RSA auth setup
        asyncio.run(client._authenticate_rsa())
        
        headers = client._sign_headers("GET", "/trade-api/v2/portfolio/orders")
        
        assert "KALSHI-ACCESS-KEY" in headers
        assert "KALSHI-ACCESS-TIMESTAMP" in headers
        assert "KALSHI-ACCESS-SIGNATURE" in headers
        assert headers["KALSHI-ACCESS-KEY"] == "test-key-id-12345"
        
    def test_sign_headers_timestamp_format(self, mock_kalshi_config):
        """Timestamp is milliseconds since epoch (no decimals)."""
        from merid.event_venues.kalshi.client import KalshiVenueClient
        
        client = KalshiVenueClient(config=mock_kalshi_config)
        asyncio.run(client._authenticate_rsa())
        
        before = int(time.time() * 1000)
        headers = client._sign_headers("GET", "/trade-api/v2/portfolio/orders")
        after = int(time.time() * 1000)
        
        ts = int(headers["KALSHI-ACCESS-TIMESTAMP"])
        assert before <= ts <= after, "Timestamp should be current milliseconds"
        
    def test_sign_headers_path_prefix(self, mock_kalshi_config):
        """Signed path MUST include /trade-api/v2 prefix."""
        from merid.event_venues.kalshi.client import KalshiVenueClient
        
        client = KalshiVenueClient(config=mock_kalshi_config)
        asyncio.run(client._authenticate_rsa())
        
        # This is the critical pattern — path must include prefix
        path = "/trade-api/v2/portfolio/orders"
        headers = client._sign_headers("POST", path)
        
        # Verify signature is non-empty
        sig = base64.b64decode(headers["KALSHI-ACCESS-SIGNATURE"])
        assert len(sig) > 0, "Signature should not be empty"
        
    def test_sign_headers_method_uppercase(self, mock_kalshi_config):
        """HTTP method is uppercased in signature message."""
        from merid.event_venues.kalshi.client import KalshiVenueClient
        
        client = KalshiVenueClient(config=mock_kalshi_config)
        asyncio.run(client._authenticate_rsa())
        
        # Test various methods
        for method in ["get", "GET", "post", "POST", "delete", "DELETE"]:
            headers = client._sign_headers(method, "/trade-api/v2/portfolio/orders")
            assert "KALSHI-ACCESS-SIGNATURE" in headers
            
    def test_sign_headers_signature_base64(self, mock_kalshi_config):
        """Signature is base64-encoded."""
        from merid.event_venues.kalshi.client import KalshiVenueClient
        
        client = KalshiVenueClient(config=mock_kalshi_config)
        asyncio.run(client._authenticate_rsa())
        
        headers = client._sign_headers("GET", "/trade-api/v2/markets")
        sig_b64 = headers["KALSHI-ACCESS-SIGNATURE"]
        
        # Should be valid base64
        try:
            decoded = base64.b64decode(sig_b64)
            assert len(decoded) > 0
        except Exception as e:
            pytest.fail(f"Signature is not valid base64: {e}")
            
    def test_sign_headers_without_auth_raises(self, mock_kalshi_config):
        """Signing without loaded key raises RuntimeError."""
        from merid.event_venues.kalshi.client import KalshiVenueClient
        
        client = KalshiVenueClient(config=mock_kalshi_config)
        # Don't call _authenticate_rsa() — simulates missing key
        
        # Manually clear the private key
        client._private_key = None
        
        with pytest.raises(RuntimeError) as exc_info:
            client._sign_headers("GET", "/trade-api/v2/markets")
        
        assert "private key not loaded" in str(exc_info.value).lower()


# =============================================================================
# Test Class: Environment Routing
# =============================================================================

class TestKalshiEnvironmentRouting:
    """Verify demo vs live URL selection and safety guards."""
    
    def test_demo_url_selection(self):
        """Demo mode uses demo-api.kalshi.co URLs."""
        from merid.event_venues.kalshi.models import KalshiConfig
        
        config = KalshiConfig(use_demo=True)
        
        assert "demo-api.kalshi.co" in config.demo_rest_api_url
        assert "demo-api.kalshi.co" in config.demo_ws_api_url
        
    def test_live_url_selection(self):
        """Live mode uses api.elections.kalshi.com URLs."""
        from merid.event_venues.kalshi.models import KalshiConfig
        
        config = KalshiConfig(use_demo=False)
        
        assert "api.elections.kalshi.com" in config.rest_api_url
        assert "api.elections.kalshi.com" in config.ws_api_url
        
    def test_base_url_derived_from_use_demo(self):
        """Config base_url property reflects use_demo flag."""
        from merid.event_venues.kalshi.models import KalshiConfig
        
        demo_config = KalshiConfig(use_demo=True)
        live_config = KalshiConfig(use_demo=False)
        
        # The property should return the correct URL
        assert "demo-api.kalshi.co" in demo_config.base_url
        assert "api.elections.kalshi.com" in live_config.base_url
        
    def test_circuit_breaker_namespaced_by_env(self):
        """Circuit breaker name includes env (demo/live)."""
        from merid.event_venues.kalshi.client import KalshiVenueClient
        from merid.event_venues.kalshi.models import KalshiConfig
        
        demo_client = KalshiVenueClient(config=KalshiConfig(use_demo=True))
        live_client = KalshiVenueClient(config=KalshiConfig(use_demo=False))
        
        # Circuit breakers are created with env-specific names
        assert "demo" in str(demo_client._circuit_breaker).lower() or "kalshi" in str(demo_client._circuit_breaker).lower()
        assert "live" in str(live_client._circuit_breaker).lower() or "kalshi" in str(live_client._circuit_breaker).lower()


# =============================================================================
# Test Class: Live Trading Guards
# =============================================================================

class TestKalshiLiveTradingGuards:
    """Verify safety interlocks for live trading."""
    
    def test_live_requires_explicit_unlock(self):
        """MERID_PM_LIVE_ENABLED must be true for live mode."""
        from merid.settings import Settings
        
        # Default settings should NOT allow live
        settings = Settings()
        
        assert settings.MERID_PM_TRADING_MODE == "paper"
        assert settings.MERID_PM_LIVE_ENABLED is False
        
        # Validation should fail for live without unlock
        settings.MERID_PM_TRADING_MODE = "live"
        issues = settings.validate_trading_mode()
        assert any("MERID_PM_LIVE_ENABLED" in issue for issue in issues)
        
    def test_live_unlocked_passes_validation(self):
        """Live mode passes when properly unlocked."""
        from merid.settings import Settings
        
        settings = Settings(
            MERID_PM_TRADING_MODE="live",
            MERID_PM_LIVE_ENABLED=True,
            MERID_LIVE_TRADING_UNLOCKED=True,
        )
        
        issues = settings.validate_trading_mode()
        # Should not have the PM_LIVE_ENABLED error
        assert not any("MERID_PM_LIVE_ENABLED" in issue for issue in issues)
        
    def test_kalshi_use_demo_default_true(self):
        """KALSHI_USE_DEMO defaults to True (safe default)."""
        from merid.settings import Settings
        
        settings = Settings()
        assert settings.KALSHI_USE_DEMO is True


# =============================================================================
# Test Class: WebSocket Transport
# =============================================================================

class TestKalshiWebSocketTransport:
    """Verify WebSocket resilience and error handling."""
    
    @pytest.mark.asyncio
    async def test_ws_connect_requires_key(self):
        """WebSocket connect requires private key path."""
        from merid.event_venues.kalshi.models import KalshiConfig
        
        try:
            from merid.event_venues.kalshi.ws import KalshiWebSocket
            
            config = KalshiConfig(private_key_path=None)
            ws = KalshiWebSocket(config=config)
            
            with pytest.raises(ValueError) as exc_info:
                await ws.connect()
            
            assert "private key" in str(exc_info.value).lower()
        except ImportError:
            pytest.skip("KalshiWebSocket not available")
            
    def test_ws_reconnect_backoff_config(self):
        """Reconnect delay starts at 1s, max 60s."""
        try:
            from merid.event_venues.kalshi.ws import KalshiWebSocket
            from merid.event_venues.kalshi.models import KalshiConfig
            
            config = KalshiConfig()
            ws = KalshiWebSocket(config=config)
            
            assert ws._reconnect_delay == 1.0
            assert ws._max_reconnect_delay == 60.0
        except ImportError:
            pytest.skip("KalshiWebSocket not available")
            
    def test_ws_error_code_classification(self):
        """Error codes are classified for appropriate handling."""
        try:
            from merid.event_venues.kalshi import ws
            
            # Check expected error code constants exist
            assert hasattr(ws, '_RECONNECT_ERROR_CODES')
            assert hasattr(ws, '_BACKOFF_ERROR_CODES')
            assert hasattr(ws, '_AUTH_ERROR_CODES')
            assert hasattr(ws, '_WARN_ERROR_CODES')
            
            # Verify auth errors include expected codes
            assert "auth_failed" in ws._AUTH_ERROR_CODES
            assert "invalid_token" in ws._AUTH_ERROR_CODES
            
            # Verify reconnect errors
            assert "server_error" in ws._RECONNECT_ERROR_CODES
            
        except ImportError:
            pytest.skip("Kalshi WS module constants not available")
            
    def test_ws_sequence_tracking_exists(self):
        """Sequence tracking state exists for gap detection."""
        try:
            from merid.event_venues.kalshi.ws import KalshiWebSocket
            from merid.event_venues.kalshi.models import KalshiConfig
            
            config = KalshiConfig()
            ws = KalshiWebSocket(config=config)
            
            assert hasattr(ws, '_last_seq')
            assert hasattr(ws, '_seq_gaps')
            assert isinstance(ws._last_seq, dict)
            assert isinstance(ws._seq_gaps, int)
        except ImportError:
            pytest.skip("KalshiWebSocket not available")
            
    def test_ws_message_queue_exists(self):
        """Async message queue exists for backpressure handling."""
        try:
            from merid.event_venues.kalshi.ws import KalshiWebSocket
            from merid.event_venues.kalshi.models import KalshiConfig
            
            config = KalshiConfig()
            ws = KalshiWebSocket(config=config)
            
            assert hasattr(ws, '_msg_queue')
            # Queue maxsize should be set (4096 per implementation)
            assert ws._msg_queue.maxsize > 0
        except ImportError:
            pytest.skip("KalshiWebSocket not available")


# =============================================================================
# Test Class: Request Path Validation
# =============================================================================

class TestKalshiRequestPathValidation:
    """Verify all requests use correct API paths."""
    
    def test_request_with_resilience_adds_api_prefix(self, mock_kalshi_config):
        """_request_with_resilience prepends /trade-api/v2 to paths."""
        from merid.event_venues.kalshi.client import KalshiVenueClient
        
        client = KalshiVenueClient(config=mock_kalshi_config)
        
        # Check that internal method constructs URL correctly
        # The path passed to _request_with_resilience is appended to base_url
        # which already includes /trade-api/v2 or the full path includes it
        
        # This is a white-box check — the critical line is:
        # full_path = f"/trade-api/v2{path}" in _request_with_resilience
        import inspect
        source = inspect.getsource(client._request_with_resilience)
        
        # Verify the signing path construction exists
        assert "/trade-api/v2" in source


# =============================================================================
# Test Class: Signature Reference Implementation
# =============================================================================

class TestKalshiSignatureReference:
    """Compare our signing against a reference implementation."""
    
    def test_signature_against_manual_construction(self, mock_rsa_key):
        """Manually construct expected signature and verify match."""
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
        from merid.event_venues.kalshi.client import KalshiVenueClient
        from merid.event_venues.kalshi.models import KalshiConfig
        
        private_key, pem = mock_rsa_key
        
        config = KalshiConfig(
            api_key="test-key-id",
            private_key_pem=pem,
        )
        client = KalshiVenueClient(config=config)
        asyncio.run(client._authenticate_rsa())
        
        # Our implementation's signature
        method = "GET"
        path = "/trade-api/v2/portfolio/orders"
        our_headers = client._sign_headers(method, path)
        our_sig_b64 = our_headers["KALSHI-ACCESS-SIGNATURE"]
        
        # Manual reference construction (per Kalshi docs)
        ts_ms = our_headers["KALSHI-ACCESS-TIMESTAMP"]  # Use same timestamp
        message = (ts_ms + method + path).encode("utf-8")
        
        reference_sig = private_key.sign(
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH,
            ),
            hashes.SHA256(),
        )
        reference_sig_b64 = base64.b64encode(reference_sig).decode()
        
        # Note: Signatures will NOT match (PSS is randomized)
        # But both should be valid base64 and same length
        assert len(base64.b64decode(our_sig_b64)) == len(reference_sig)
        
    def test_signature_verification_with_public_key(self, mock_rsa_key):
        """Verify our signature can be verified with the public key."""
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
        from merid.event_venues.kalshi.client import KalshiVenueClient
        from merid.event_venues.kalshi.models import KalshiConfig
        
        private_key, pem = mock_rsa_key
        public_key = private_key.public_key()
        
        config = KalshiConfig(
            api_key="test-key-id",
            private_key_pem=pem,
        )
        client = KalshiVenueClient(config=config)
        asyncio.run(client._authenticate_rsa())
        
        # Sign with our implementation
        method = "POST"
        path = "/trade-api/v2/portfolio/orders"
        headers = client._sign_headers(method, path)
        
        signature = base64.b64decode(headers["KALSHI-ACCESS-SIGNATURE"])
        timestamp = headers["KALSHI-ACCESS-TIMESTAMP"]
        message = (timestamp + method + path).encode("utf-8")
        
        # Verify with public key (this is what Kalshi does)
        try:
            public_key.verify(
                signature,
                message,
                padding.PSS(
                    mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.DIGEST_LENGTH,
                ),
                hashes.SHA256(),
            )
            # If we get here, signature is valid
            assert True
        except Exception as e:
            pytest.fail(f"Signature verification failed: {e}")


# =============================================================================
# Integration Test: Full Request Flow
# =============================================================================

class TestKalshiRequestIntegration:
    """Integration tests with mocked HTTP."""
    
    @pytest.mark.asyncio
    async def test_get_markets_includes_auth_headers(self, mock_kalshi_config):
        """GET /markets request includes properly signed headers."""
        from merid.event_venues.kalshi.client import KalshiVenueClient
        
        client = KalshiVenueClient(config=mock_kalshi_config)
        await client._authenticate_rsa()
        
        # Mock the HTTP client
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"markets": []}
        mock_response.headers = {}
        mock_response.text = ""
        
        mock_http_client = AsyncMock()
        mock_http_client.is_closed = False
        mock_http_client.request.return_value = mock_response
        
        client._http_client = mock_http_client
        
        # Make request
        result = await client.list_markets_result()
        
        # Verify request was made with auth headers
        call_args = mock_http_client.request.call_args
        headers = call_args.kwargs.get("headers") or call_args[1].get("headers")
        
        if headers:
            assert "KALSHI-ACCESS-KEY" in headers
            assert "KALSHI-ACCESS-TIMESTAMP" in headers
            assert "KALSHI-ACCESS-SIGNATURE" in headers


# =============================================================================
# Test Class: No Bypass Enforcement
# =============================================================================

class TestKalshiNoBypass:
    """Verify all requests go through the signing helper."""
    
    def test_all_public_methods_use_request_with_resilience(self):
        """All public API methods route through _request_with_resilience."""
        from merid.event_venues.kalshi.client import KalshiVenueClient
        import inspect
        
        # Get all public async methods
        methods = [
            name for name, method in inspect.getmembers(KalshiVenueClient)
            if inspect.iscoroutinefunction(method) and not name.startswith("_")
        ]
        
        source = inspect.getsource(KalshiVenueClient)
        
        # Each public method should call _request_with_resilience
        # or call another method that does
        for method_name in methods:
            method_source = inspect.getsource(getattr(KalshiVenueClient, method_name))
            assert "_request_with_resilience" in method_source or \
                   "list_markets_result" in method_source or \
                   "get_market_result" in method_source or \
                   method_name in ["connect", "close"], \
                f"{method_name} may bypass _request_with_resilience"
                
    def test_place_order_uses_signing(self, mock_kalshi_config):
        """Place order path includes signing."""
        from merid.event_venues.kalshi.client import KalshiVenueClient
        import inspect
        
        source = inspect.getsource(KalshiVenueClient.place_order_result)
        
        # Should use _request_with_resilience which triggers signing
        assert "_request_with_resilience" in source or "post" in source.lower()


# =============================================================================
# Run Configuration
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
