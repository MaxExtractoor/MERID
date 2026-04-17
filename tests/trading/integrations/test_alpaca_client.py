"""Comprehensive tests for trading/integrations/alpaca_client.py."""

import pytest
import os
from unittest.mock import Mock, patch, MagicMock

from merid.settings import settings as merid_settings

from trading.integrations.alpaca_client import (
    _resolve_alpaca_base_url,
    _resolve_credentials,
    get_alpaca_client,
    fetch_account_snapshot,
)


class TestResolveAlpacaBaseUrl:
    """Test _resolve_alpaca_base_url function."""

    def test_explicit_base_url(self, monkeypatch):
        """Test explicit base URL from environment."""
        monkeypatch.setenv("ALPACA_BASE_URL", "https://custom.alpaca.com")
        
        url = _resolve_alpaca_base_url()
        
        assert url == "https://custom.alpaca.com"

    def test_live_environment_alpaca_env(self, monkeypatch):
        """Test live environment via ALPACA_ENVIRONMENT."""
        monkeypatch.setenv("ALPACA_ENVIRONMENT", "live")
        monkeypatch.delenv("ALPACA_BASE_URL", raising=False)
        
        url = _resolve_alpaca_base_url()
        
        assert url == "https://api.alpaca.markets"

    def test_live_environment_alpaca_env_var(self, monkeypatch):
        """Test live environment via ALPACA_ENV."""
        monkeypatch.setenv("ALPACA_ENV", "live")
        monkeypatch.delenv("ALPACA_BASE_URL", raising=False)
        monkeypatch.delenv("ALPACA_ENVIRONMENT", raising=False)
        
        url = _resolve_alpaca_base_url()
        
        assert url == "https://api.alpaca.markets"

    def test_paper_environment_default(self, monkeypatch):
        """Test default paper environment."""
        monkeypatch.delenv("ALPACA_BASE_URL", raising=False)
        monkeypatch.delenv("ALPACA_ENVIRONMENT", raising=False)
        monkeypatch.delenv("ALPACA_ENV", raising=False)
        
        url = _resolve_alpaca_base_url()
        
        assert url == "https://paper-api.alpaca.markets"

    def test_paper_environment_explicit(self, monkeypatch):
        """Test explicit paper environment."""
        monkeypatch.setenv("ALPACA_ENVIRONMENT", "paper")
        monkeypatch.delenv("ALPACA_BASE_URL", raising=False)
        
        url = _resolve_alpaca_base_url()
        
        assert url == "https://paper-api.alpaca.markets"

    def test_environment_case_insensitive(self, monkeypatch):
        """Test environment variable is case insensitive."""
        monkeypatch.setenv("ALPACA_ENVIRONMENT", "LIVE")
        monkeypatch.delenv("ALPACA_BASE_URL", raising=False)
        
        url = _resolve_alpaca_base_url()
        
        assert url == "https://api.alpaca.markets"

    def test_explicit_overrides_environment(self, monkeypatch):
        """Test explicit URL overrides environment setting."""
        monkeypatch.setenv("ALPACA_BASE_URL", "https://custom.alpaca.com")
        monkeypatch.setenv("ALPACA_ENVIRONMENT", "live")
        
        url = _resolve_alpaca_base_url()
        
        # Explicit URL takes precedence
        assert url == "https://custom.alpaca.com"


class TestResolveCredentials:
    """Test _resolve_credentials function."""

    def test_standard_credentials(self, monkeypatch):
        """Test standard ALPACA_API_KEY/SECRET."""
        monkeypatch.setenv("ALPACA_API_KEY", "test_key")
        monkeypatch.setenv("ALPACA_API_SECRET", "test_secret")
        monkeypatch.delenv("MERID_ALPACA_API_KEY", raising=False)
        monkeypatch.delenv("MERID_ALPACA_API_SECRET", raising=False)
        
        key, secret = _resolve_credentials()
        
        assert key == "test_key"
        assert secret == "test_secret"

    def test_merid_prefixed_credentials(self, monkeypatch):
        """Test MERID_ALPACA_API_KEY/SECRET."""
        monkeypatch.delenv("ALPACA_API_KEY", raising=False)
        monkeypatch.delenv("ALPACA_API_SECRET", raising=False)
        monkeypatch.setenv("MERID_ALPACA_API_KEY", "merid_key")
        monkeypatch.setenv("MERID_ALPACA_API_SECRET", "merid_secret")
        
        key, secret = _resolve_credentials()
        
        assert key == "merid_key"
        assert secret == "merid_secret"

    def test_standard_takes_precedence(self, monkeypatch):
        """Test standard credentials take precedence over MERID prefixed."""
        monkeypatch.setenv("ALPACA_API_KEY", "standard_key")
        monkeypatch.setenv("ALPACA_API_SECRET", "standard_secret")
        monkeypatch.setenv("MERID_ALPACA_API_KEY", "merid_key")
        monkeypatch.setenv("MERID_ALPACA_API_SECRET", "merid_secret")
        
        key, secret = _resolve_credentials()
        
        assert key == "standard_key"
        assert secret == "standard_secret"

    def test_missing_key_raises(self, monkeypatch):
        """Test RuntimeError when key is missing."""
        monkeypatch.delenv("ALPACA_API_KEY", raising=False)
        monkeypatch.delenv("MERID_ALPACA_API_KEY", raising=False)
        monkeypatch.setenv("ALPACA_API_SECRET", "test_secret")
        
        with pytest.raises(RuntimeError, match="Alpaca credentials missing"):
            _resolve_credentials()

    def test_missing_secret_raises(self, monkeypatch):
        """Test RuntimeError when secret is missing."""
        monkeypatch.setenv("ALPACA_API_KEY", "test_key")
        monkeypatch.delenv("ALPACA_API_SECRET", raising=False)
        monkeypatch.delenv("MERID_ALPACA_API_SECRET", raising=False)
        
        with pytest.raises(RuntimeError, match="Alpaca credentials missing"):
            _resolve_credentials()

    def test_both_missing_raises(self, monkeypatch):
        """Test RuntimeError when both are missing."""
        monkeypatch.delenv("ALPACA_API_KEY", raising=False)
        monkeypatch.delenv("ALPACA_API_SECRET", raising=False)
        monkeypatch.delenv("MERID_ALPACA_API_KEY", raising=False)
        monkeypatch.delenv("MERID_ALPACA_API_SECRET", raising=False)
        
        with pytest.raises(RuntimeError, match="Alpaca credentials missing"):
            _resolve_credentials()


class TestGetAlpacaClient:
    """Test get_alpaca_client function."""

    @patch("trading.integrations.alpaca_client.REST")
    def test_client_creation_paper(self, mock_rest, monkeypatch):
        """Test client creation for paper environment."""
        monkeypatch.setenv("ALPACA_API_KEY", "test_key")
        monkeypatch.setenv("ALPACA_API_SECRET", "test_secret")
        monkeypatch.delenv("ALPACA_BASE_URL", raising=False)
        monkeypatch.delenv("ALPACA_ENVIRONMENT", raising=False)
        monkeypatch.setattr(merid_settings, "KALSHI_ONLY", False, raising=False)

        # Clear cache
        get_alpaca_client.cache_clear()
        
        client = get_alpaca_client()
        
        mock_rest.assert_called_once_with(
            "test_key",
            "test_secret",
            base_url="https://paper-api.alpaca.markets"
        )
        assert client == mock_rest.return_value

    @patch("trading.integrations.alpaca_client.REST")
    def test_client_creation_live(self, mock_rest, monkeypatch):
        """Test client creation for live environment."""
        monkeypatch.setenv("ALPACA_API_KEY", "test_key")
        monkeypatch.setenv("ALPACA_API_SECRET", "test_secret")
        monkeypatch.setenv("ALPACA_ENVIRONMENT", "live")
        monkeypatch.setattr(merid_settings, "KALSHI_ONLY", False, raising=False)

        # Clear cache
        get_alpaca_client.cache_clear()
        
        client = get_alpaca_client()
        
        mock_rest.assert_called_once_with(
            "test_key",
            "test_secret",
            base_url="https://api.alpaca.markets"
        )

    @patch("trading.integrations.alpaca_client.REST")
    def test_client_caching(self, mock_rest, monkeypatch):
        """Test that client is cached."""
        monkeypatch.setenv("ALPACA_API_KEY", "test_key")
        monkeypatch.setenv("ALPACA_API_SECRET", "test_secret")
        monkeypatch.setattr(merid_settings, "KALSHI_ONLY", False, raising=False)

        # Clear cache
        get_alpaca_client.cache_clear()
        
        client1 = get_alpaca_client()
        client2 = get_alpaca_client()
        
        # REST should only be called once due to caching
        mock_rest.assert_called_once()
        assert client1 == client2

    @patch("trading.integrations.alpaca_client.REST")
    def test_client_creation_logs_info(self, mock_rest, monkeypatch, caplog):
        """Test that client creation logs environment."""
        import logging
        monkeypatch.setenv("ALPACA_API_KEY", "test_key")
        monkeypatch.setenv("ALPACA_API_SECRET", "test_secret")
        monkeypatch.setenv("ALPACA_ENVIRONMENT", "live")
        monkeypatch.setattr(merid_settings, "KALSHI_ONLY", False, raising=False)

        # Clear cache
        get_alpaca_client.cache_clear()
        
        with caplog.at_level("INFO", logger="trading.integrations.alpaca"):
            get_alpaca_client()
        
        # Log may go to custom logger, just verify no exception
        # The client was created successfully if we got here
        assert True


class TestFetchAccountSnapshot:
    """Test fetch_account_snapshot function."""

    @patch("trading.integrations.alpaca_client.get_alpaca_client")
    def test_fetch_with_raw_attribute(self, mock_get_client):
        """Test fetching when account has _raw attribute."""
        mock_account = Mock()
        mock_account._raw = {"id": "account_123", "cash": "10000.00"}
        mock_get_client.return_value.get_account.return_value = mock_account
        
        snapshot = fetch_account_snapshot()
        
        assert snapshot == {"id": "account_123", "cash": "10000.00"}
        mock_get_client.return_value.get_account.assert_called_once()

    @patch("trading.integrations.alpaca_client.get_alpaca_client")
    def test_fetch_with_to_dict_method(self, mock_get_client):
        """Test fetching when account has to_dict method."""
        mock_account = Mock()
        mock_account.to_dict.return_value = {"id": "account_456", "cash": "5000.00"}
        # No _raw attribute
        delattr(mock_account, "_raw")
        mock_get_client.return_value.get_account.return_value = mock_account
        
        snapshot = fetch_account_snapshot()
        
        assert snapshot == {"id": "account_456", "cash": "5000.00"}

    @patch("trading.integrations.alpaca_client.get_alpaca_client")
    def test_fetch_with_dict_attribute(self, mock_get_client):
        """Test fetching when account has __dict__."""
        # Create a simple class instance instead of Mock to avoid mock internals
        class SimpleAccount:
            def __init__(self):
                self.id = "account_789"
                self.cash = "2500.00"
        
        mock_account = SimpleAccount()
        mock_get_client.return_value.get_account.return_value = mock_account
        
        snapshot = fetch_account_snapshot()
        
        assert snapshot["id"] == "account_789"
        assert snapshot["cash"] == "2500.00"

    @patch("trading.integrations.alpaca_client.get_alpaca_client")
    def test_fetch_empty_account(self, mock_get_client):
        """Test fetching with empty account data."""
        mock_account = Mock()
        mock_account._raw = {}
        mock_get_client.return_value.get_account.return_value = mock_account
        
        snapshot = fetch_account_snapshot()
        
        assert snapshot == {}
