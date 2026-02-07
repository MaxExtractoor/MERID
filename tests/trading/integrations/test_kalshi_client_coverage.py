"""Comprehensive tests for trading/integrations/kalshi_client.py - Coverage improvement."""

import pytest
from unittest.mock import MagicMock, patch

from trading.integrations.kalshi_client import (
    _load_private_key, _build_client, get_kalshi_client, fetch_kalshi_balance
)


# =============================================================================
# Load Private Key Tests
# =============================================================================

class TestLoadPrivateKey:
    """Test _load_private_key function."""

    def test_from_env_var(self, monkeypatch):
        monkeypatch.setenv("KALSHI_PRIVATE_KEY_PEM", "-----BEGIN PRIVATE KEY-----\ntest\n-----END PRIVATE KEY-----")
        monkeypatch.delenv("KALSHI_PRIVATE_KEY_PATH", raising=False)
        
        result = _load_private_key()
        
        assert "BEGIN PRIVATE KEY" in result

    def test_from_file(self, monkeypatch, tmp_path):
        key_file = tmp_path / "key.pem"
        key_file.write_text("-----BEGIN PRIVATE KEY-----\nfile_key\n-----END PRIVATE KEY-----")
        
        monkeypatch.delenv("KALSHI_PRIVATE_KEY_PEM", raising=False)
        monkeypatch.setenv("KALSHI_PRIVATE_KEY_PATH", str(key_file))
        
        result = _load_private_key()
        
        assert "file_key" in result

    def test_file_not_found(self, monkeypatch):
        monkeypatch.delenv("KALSHI_PRIVATE_KEY_PEM", raising=False)
        monkeypatch.setenv("KALSHI_PRIVATE_KEY_PATH", "/nonexistent/path.pem")
        
        result = _load_private_key()
        
        assert result is None

    def test_no_credentials(self, monkeypatch):
        monkeypatch.delenv("KALSHI_PRIVATE_KEY_PEM", raising=False)
        monkeypatch.delenv("KALSHI_PRIVATE_KEY_PATH", raising=False)
        
        result = _load_private_key()
        
        assert result is None


# =============================================================================
# Build Client Tests
# =============================================================================

class TestBuildClient:
    """Test _build_client function."""

    def test_missing_credentials_raises(self, monkeypatch):
        monkeypatch.delenv("KALSHI_API_KEY_ID", raising=False)
        monkeypatch.delenv("KALSHI_API_KEY", raising=False)
        monkeypatch.delenv("KALSHI_PRIVATE_KEY_PEM", raising=False)
        monkeypatch.delenv("KALSHI_PRIVATE_KEY_PATH", raising=False)
        
        with pytest.raises(RuntimeError, match="credentials missing"):
            _build_client()

    def test_with_valid_credentials(self, monkeypatch):
        monkeypatch.setenv("KALSHI_API_KEY_ID", "test_key_id")
        monkeypatch.setenv("KALSHI_PRIVATE_KEY_PEM", "-----BEGIN PRIVATE KEY-----\ntest\n-----END PRIVATE KEY-----")
        
        with patch("trading.integrations.kalshi_client.KalshiClient") as mock_client:
            mock_client.return_value = MagicMock()
            
            client = _build_client()
            
            assert mock_client.called


# =============================================================================
# Get Kalshi Client Tests
# =============================================================================

class TestGetKalshiClient:
    """Test get_kalshi_client function."""

    def test_returns_client(self, monkeypatch):
        monkeypatch.setenv("KALSHI_API_KEY_ID", "test_key")
        monkeypatch.setenv("KALSHI_PRIVATE_KEY_PEM", "-----BEGIN PRIVATE KEY-----\ntest\n-----END PRIVATE KEY-----")
        
        get_kalshi_client.cache_clear()
        
        with patch("trading.integrations.kalshi_client.KalshiClient") as mock_client:
            mock_instance = MagicMock()
            mock_instance.api_client.configuration.host = "https://api.kalshi.com"
            mock_client.return_value = mock_instance
            
            client = get_kalshi_client()
            
            assert client is not None


# =============================================================================
# Fetch Balance Tests
# =============================================================================

class TestFetchKalshiBalance:
    """Test fetch_kalshi_balance function."""

    def test_with_to_dict(self, monkeypatch):
        monkeypatch.setenv("KALSHI_API_KEY_ID", "test_key")
        monkeypatch.setenv("KALSHI_PRIVATE_KEY_PEM", "-----BEGIN PRIVATE KEY-----\ntest\n-----END PRIVATE KEY-----")
        
        get_kalshi_client.cache_clear()
        
        with patch("trading.integrations.kalshi_client.KalshiClient") as mock_client:
            mock_instance = MagicMock()
            mock_instance.api_client.configuration.host = "https://api.kalshi.com"
            mock_balance = MagicMock()
            mock_balance.to_dict.return_value = {"balance": 1000}
            mock_instance.get_balance.return_value = mock_balance
            mock_client.return_value = mock_instance
            
            result = fetch_kalshi_balance()
            
            assert result["balance"] == 1000

    def test_with_dict_response(self, monkeypatch):
        monkeypatch.setenv("KALSHI_API_KEY_ID", "test_key")
        monkeypatch.setenv("KALSHI_PRIVATE_KEY_PEM", "-----BEGIN PRIVATE KEY-----\ntest\n-----END PRIVATE KEY-----")
        
        get_kalshi_client.cache_clear()
        
        with patch("trading.integrations.kalshi_client.KalshiClient") as mock_client:
            mock_instance = MagicMock()
            mock_instance.api_client.configuration.host = "https://api.kalshi.com"
            mock_instance.get_balance.return_value = {"available_cash": 500}
            mock_client.return_value = mock_instance
            
            result = fetch_kalshi_balance()
            
            assert result["balance"] == 500

    def test_with_object_response(self, monkeypatch):
        monkeypatch.setenv("KALSHI_API_KEY_ID", "test_key")
        monkeypatch.setenv("KALSHI_PRIVATE_KEY_PEM", "-----BEGIN PRIVATE KEY-----\ntest\n-----END PRIVATE KEY-----")
        
        get_kalshi_client.cache_clear()
        
        with patch("trading.integrations.kalshi_client.KalshiClient") as mock_client:
            mock_instance = MagicMock()
            mock_instance.api_client.configuration.host = "https://api.kalshi.com"
            
            class BalanceObj:
                def __init__(self):
                    self.available_balance = 750
            
            balance_obj = BalanceObj()
            mock_instance.get_balance.return_value = balance_obj
            mock_client.return_value = mock_instance
            
            result = fetch_kalshi_balance()
            
            assert result["balance"] == 750
