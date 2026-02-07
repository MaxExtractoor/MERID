"""Comprehensive tests for trading/integrations/alpaca_client.py - Coverage improvement."""

import pytest
from unittest.mock import MagicMock, patch

from trading.integrations.alpaca_client import (
    _resolve_alpaca_base_url, _resolve_credentials, get_alpaca_client,
    fetch_account_snapshot
)


# =============================================================================
# Resolve Base URL Tests
# =============================================================================

class TestResolveAlpacaBaseUrl:
    """Test _resolve_alpaca_base_url function."""

    def test_explicit_url(self, monkeypatch):
        monkeypatch.setenv("ALPACA_BASE_URL", "https://custom.alpaca.com")
        
        result = _resolve_alpaca_base_url()
        
        assert result == "https://custom.alpaca.com"

    def test_live_environment(self, monkeypatch):
        monkeypatch.delenv("ALPACA_BASE_URL", raising=False)
        monkeypatch.setenv("ALPACA_ENVIRONMENT", "live")
        
        result = _resolve_alpaca_base_url()
        
        assert result == "https://api.alpaca.markets"

    def test_paper_environment(self, monkeypatch):
        monkeypatch.delenv("ALPACA_BASE_URL", raising=False)
        monkeypatch.setenv("ALPACA_ENVIRONMENT", "paper")
        
        result = _resolve_alpaca_base_url()
        
        assert result == "https://paper-api.alpaca.markets"

    def test_default_paper(self, monkeypatch):
        monkeypatch.delenv("ALPACA_BASE_URL", raising=False)
        monkeypatch.delenv("ALPACA_ENVIRONMENT", raising=False)
        monkeypatch.delenv("ALPACA_ENV", raising=False)
        
        result = _resolve_alpaca_base_url()
        
        assert result == "https://paper-api.alpaca.markets"


# =============================================================================
# Resolve Credentials Tests
# =============================================================================

class TestResolveCredentials:
    """Test _resolve_credentials function."""

    def test_primary_env_vars(self, monkeypatch):
        monkeypatch.setenv("ALPACA_API_KEY", "test_key")
        monkeypatch.setenv("ALPACA_API_SECRET", "test_secret")
        
        key, secret = _resolve_credentials()
        
        assert key == "test_key"
        assert secret == "test_secret"

    def test_merid_env_vars(self, monkeypatch):
        monkeypatch.delenv("ALPACA_API_KEY", raising=False)
        monkeypatch.delenv("ALPACA_API_SECRET", raising=False)
        monkeypatch.setenv("MERID_ALPACA_API_KEY", "merid_key")
        monkeypatch.setenv("MERID_ALPACA_API_SECRET", "merid_secret")
        
        key, secret = _resolve_credentials()
        
        assert key == "merid_key"
        assert secret == "merid_secret"

    def test_missing_credentials_raises(self, monkeypatch):
        monkeypatch.delenv("ALPACA_API_KEY", raising=False)
        monkeypatch.delenv("ALPACA_API_SECRET", raising=False)
        monkeypatch.delenv("MERID_ALPACA_API_KEY", raising=False)
        monkeypatch.delenv("MERID_ALPACA_API_SECRET", raising=False)
        
        with pytest.raises(RuntimeError, match="credentials missing"):
            _resolve_credentials()


# =============================================================================
# Get Alpaca Client Tests
# =============================================================================

class TestGetAlpacaClient:
    """Test get_alpaca_client function."""

    def test_returns_client(self, monkeypatch):
        monkeypatch.setenv("ALPACA_API_KEY", "test_key")
        monkeypatch.setenv("ALPACA_API_SECRET", "test_secret")
        monkeypatch.delenv("ALPACA_BASE_URL", raising=False)
        
        get_alpaca_client.cache_clear()
        
        with patch("trading.integrations.alpaca_client.REST") as mock_rest:
            mock_rest.return_value = MagicMock()
            
            client = get_alpaca_client()
            
            assert mock_rest.called


# =============================================================================
# Fetch Account Snapshot Tests
# =============================================================================

class TestFetchAccountSnapshot:
    """Test fetch_account_snapshot function."""

    def test_with_raw_attribute(self, monkeypatch):
        monkeypatch.setenv("ALPACA_API_KEY", "test_key")
        monkeypatch.setenv("ALPACA_API_SECRET", "test_secret")
        
        get_alpaca_client.cache_clear()
        
        with patch("trading.integrations.alpaca_client.REST") as mock_rest:
            mock_client = MagicMock()
            mock_account = MagicMock()
            mock_account._raw = {"equity": 10000}
            mock_client.get_account.return_value = mock_account
            mock_rest.return_value = mock_client
            
            result = fetch_account_snapshot()
            
            assert result["equity"] == 10000

    def test_with_to_dict(self, monkeypatch):
        monkeypatch.setenv("ALPACA_API_KEY", "test_key")
        monkeypatch.setenv("ALPACA_API_SECRET", "test_secret")
        
        get_alpaca_client.cache_clear()
        
        with patch("trading.integrations.alpaca_client.REST") as mock_rest:
            mock_client = MagicMock()
            mock_account = MagicMock(spec=["to_dict"])
            mock_account.to_dict.return_value = {"cash": 5000}
            mock_client.get_account.return_value = mock_account
            mock_rest.return_value = mock_client
            
            result = fetch_account_snapshot()
            
            assert result["cash"] == 5000

    def test_with_dict_fallback(self, monkeypatch):
        monkeypatch.setenv("ALPACA_API_KEY", "test_key")
        monkeypatch.setenv("ALPACA_API_SECRET", "test_secret")
        
        get_alpaca_client.cache_clear()
        
        with patch("trading.integrations.alpaca_client.REST") as mock_rest:
            mock_client = MagicMock()
            
            class AccountObj:
                def __init__(self):
                    self.buying_power = 25000
            
            mock_client.get_account.return_value = AccountObj()
            mock_rest.return_value = mock_client
            
            result = fetch_account_snapshot()
            
            assert result["buying_power"] == 25000
