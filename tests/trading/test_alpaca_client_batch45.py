"""Tests for trading integrations alpaca_client module - Batch 45 Coverage."""
import pytest
from unittest.mock import MagicMock, patch
import os

from merid.settings import settings as merid_settings

from trading.integrations.alpaca_client import (
    _resolve_alpaca_base_url,
    _resolve_credentials,
    get_alpaca_client,
    fetch_account_snapshot,
)


class TestResolveAlpacaBaseUrl:
    """Tests for _resolve_alpaca_base_url function."""

    def test_explicit_base_url(self):
        with patch.dict(os.environ, {"ALPACA_BASE_URL": "https://custom.alpaca.com"}, clear=True):
            assert _resolve_alpaca_base_url() == "https://custom.alpaca.com"

    def test_live_environment(self):
        with patch.dict(os.environ, {"ALPACA_ENVIRONMENT": "live"}, clear=True):
            assert _resolve_alpaca_base_url() == "https://api.alpaca.markets"

    def test_live_env_short(self):
        with patch.dict(os.environ, {"ALPACA_ENV": "live"}, clear=True):
            assert _resolve_alpaca_base_url() == "https://api.alpaca.markets"

    def test_paper_default(self):
        with patch.dict(os.environ, {}, clear=True):
            assert _resolve_alpaca_base_url() == "https://paper-api.alpaca.markets"

    def test_paper_explicit(self):
        with patch.dict(os.environ, {"ALPACA_ENVIRONMENT": "paper"}, clear=True):
            assert _resolve_alpaca_base_url() == "https://paper-api.alpaca.markets"


class TestResolveCredentials:
    """Tests for _resolve_credentials function."""

    def test_standard_env_vars(self):
        with patch.dict(os.environ, {
            "ALPACA_API_KEY": "test_key",
            "ALPACA_API_SECRET": "test_secret"
        }, clear=True):
            key, secret = _resolve_credentials()
            assert key == "test_key"
            assert secret == "test_secret"

    def test_merid_prefixed_env_vars(self):
        with patch.dict(os.environ, {
            "MERID_ALPACA_API_KEY": "merid_key",
            "MERID_ALPACA_API_SECRET": "merid_secret"
        }, clear=True):
            key, secret = _resolve_credentials()
            assert key == "merid_key"
            assert secret == "merid_secret"

    def test_standard_overrides_merid(self):
        """Standard env vars should take precedence over MERID prefixed ones."""
        with patch.dict(os.environ, {
            "ALPACA_API_KEY": "standard_key",
            "ALPACA_API_SECRET": "standard_secret",
            "MERID_ALPACA_API_KEY": "merid_key",
            "MERID_ALPACA_API_SECRET": "merid_secret"
        }, clear=True):
            key, secret = _resolve_credentials()
            assert key == "standard_key"
            assert secret == "standard_secret"

    def test_missing_key(self):
        with patch.dict(os.environ, {"ALPACA_API_SECRET": "test_secret"}, clear=True):
            with pytest.raises(RuntimeError, match="credentials missing"):
                _resolve_credentials()

    def test_missing_secret(self):
        with patch.dict(os.environ, {"ALPACA_API_KEY": "test_key"}, clear=True):
            with pytest.raises(RuntimeError, match="credentials missing"):
                _resolve_credentials()


class TestGetAlpacaClient:
    """Tests for get_alpaca_client function."""

    @patch('trading.integrations.alpaca_client.REST')
    @patch.dict(os.environ, {
        "ALPACA_API_KEY": "test_key",
        "ALPACA_API_SECRET": "test_secret"
    }, clear=True)
    def test_get_client_creates_rest_instance(self, mock_rest, monkeypatch):
        monkeypatch.setattr(merid_settings, "KALSHI_ONLY", False, raising=False)
        # Clear the lru_cache from previous tests
        get_alpaca_client.cache_clear()
        mock_rest.return_value = MagicMock()
        client = get_alpaca_client()
        assert client is not None
        mock_rest.assert_called_once_with(
            "test_key",
            "test_secret",
            base_url="https://paper-api.alpaca.markets"
        )

    @patch('trading.integrations.alpaca_client.REST')
    @patch.dict(os.environ, {
        "ALPACA_API_KEY": "test_key",
        "ALPACA_API_SECRET": "test_secret",
        "ALPACA_ENVIRONMENT": "live"
    }, clear=True)
    def test_get_client_live_environment(self, mock_rest, monkeypatch):
        monkeypatch.setattr(merid_settings, "KALSHI_ONLY", False, raising=False)
        # Clear the lru_cache from previous tests
        get_alpaca_client.cache_clear()
        mock_rest.return_value = MagicMock()
        client = get_alpaca_client()
        mock_rest.assert_called_once_with(
            "test_key",
            "test_secret",
            base_url="https://api.alpaca.markets"
        )


class TestFetchAccountSnapshot:
    """Tests for fetch_account_snapshot function."""

    @patch('trading.integrations.alpaca_client.get_alpaca_client')
    def test_fetch_with_raw_attribute(self, mock_get_client):
        """Test when account has _raw attribute."""
        mock_account = MagicMock()
        mock_account._raw = {"id": "account_123", "cash": 10000.0}
        mock_get_client.return_value.get_account.return_value = mock_account

        result = fetch_account_snapshot()

        assert result == {"id": "account_123", "cash": 10000.0}

    @patch('trading.integrations.alpaca_client.get_alpaca_client')
    def test_fetch_with_to_dict_method(self, mock_get_client):
        """Test when account has to_dict method."""
        mock_account = MagicMock()
        mock_account.to_dict.return_value = {"id": "account_456", "cash": 5000.0}
        del mock_account._raw  # Remove _raw attribute
        mock_get_client.return_value.get_account.return_value = mock_account

        result = fetch_account_snapshot()

        assert result == {"id": "account_456", "cash": 5000.0}

    @patch('trading.integrations.alpaca_client.get_alpaca_client')
    def test_fetch_fallback_to_dict(self, mock_get_client):
        """Test fallback to __dict__ when no _raw or to_dict."""
        # Create a simple object with __dict__ but no _raw or to_dict
        class SimpleAccount:
            def __init__(self):
                self.id = "account_789"
                self.cash = 2500.0
        
        mock_account = SimpleAccount()
        mock_get_client.return_value.get_account.return_value = mock_account

        result = fetch_account_snapshot()

        assert result == {"id": "account_789", "cash": 2500.0}
