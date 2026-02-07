"""Tests for trading integrations kalshi_client module - Batch 46 Coverage."""
import pytest
from unittest.mock import MagicMock, patch, mock_open
import os

from trading.integrations.kalshi_client import (
    _load_private_key,
    _build_client,
    get_kalshi_client,
    fetch_kalshi_balance,
)


class TestLoadPrivateKey:
    """Tests for _load_private_key function."""

    def test_load_from_env_pem(self):
        """Test loading private key from environment variable."""
        with patch.dict(os.environ, {"KALSHI_PRIVATE_KEY_PEM": "test_pem_content"}, clear=True):
            result = _load_private_key()
            assert result == "test_pem_content"

    def test_load_from_file(self):
        """Test loading private key from file path."""
        with patch.dict(os.environ, {"KALSHI_PRIVATE_KEY_PATH": "/path/to/key.pem"}, clear=True):
            with patch("builtins.open", mock_open(read_data="file_pem_content")):
                result = _load_private_key()
                assert result == "file_pem_content"

    def test_load_from_file_not_found(self):
        """Test handling of missing key file."""
        with patch.dict(os.environ, {"KALSHI_PRIVATE_KEY_PATH": "/path/to/missing.pem"}, clear=True):
            with patch("builtins.open", side_effect=FileNotFoundError()):
                with patch("trading.integrations.kalshi_client.logger") as mock_logger:
                    result = _load_private_key()
                    assert result is None
                    mock_logger.warning.assert_called_once()

    def test_load_no_credentials(self):
        """Test when no credentials are provided."""
        with patch.dict(os.environ, {}, clear=True):
            result = _load_private_key()
            assert result is None

    def test_env_pem_takes_precedence(self):
        """Test that env PEM takes precedence over file path."""
        with patch.dict(os.environ, {
            "KALSHI_PRIVATE_KEY_PEM": "env_pem",
            "KALSHI_PRIVATE_KEY_PATH": "/path/to/key.pem"
        }, clear=True):
            result = _load_private_key()
            assert result == "env_pem"


class TestBuildClient:
    """Tests for _build_client function."""

    @patch("trading.integrations.kalshi_client.KalshiClient")
    @patch("trading.integrations.kalshi_client.Configuration")
    def test_build_client_success(self, mock_config_class, mock_client_class):
        """Test successful client building."""
        with patch.dict(os.environ, {
            "KALSHI_API_KEY_ID": "test_key_id",
            "KALSHI_PRIVATE_KEY_PEM": "test_pem",
        }, clear=True):
            mock_config = MagicMock()
            mock_config_class.return_value = mock_config
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client

            result = _build_client()

            assert result is mock_client
            assert mock_config.api_key_id == "test_key_id"
            assert mock_config.private_key_pem == "test_pem"
            assert mock_config.ssl_ca_cert is None
            assert mock_config.verify_ssl is False
            assert mock_config.assert_hostname is False

    @patch("trading.integrations.kalshi_client.KalshiClient")
    @patch("trading.integrations.kalshi_client.Configuration")
    def test_build_client_custom_host(self, mock_config_class, mock_client_class):
        """Test client building with custom host."""
        with patch.dict(os.environ, {
            "KALSHI_API_KEY_ID": "test_key_id",
            "KALSHI_PRIVATE_KEY_PEM": "test_pem",
            "KALSHI_API_HOST": "https://custom.kalshi.com",
        }, clear=True):
            mock_config = MagicMock()
            mock_config_class.return_value = mock_config

            _build_client()

            mock_config_class.assert_called_once_with(host="https://custom.kalshi.com")

    def test_build_client_missing_key_id(self):
        """Test error when API key ID is missing."""
        with patch.dict(os.environ, {
            "KALSHI_PRIVATE_KEY_PEM": "test_pem",
        }, clear=True):
            with pytest.raises(RuntimeError, match="Kalshi credentials missing"):
                _build_client()

    def test_build_client_missing_private_key(self):
        """Test error when private key is missing."""
        with patch.dict(os.environ, {
            "KALSHI_API_KEY_ID": "test_key_id",
        }, clear=True):
            with pytest.raises(RuntimeError, match="Kalshi credentials missing"):
                _build_client()

    @patch("trading.integrations.kalshi_client.KalshiClient")
    @patch("trading.integrations.kalshi_client.Configuration")
    def test_build_client_with_api_key_alias(self, mock_config_class, mock_client_class):
        """Test using KALSHI_API_KEY as alias for KALSHI_API_KEY_ID."""
        with patch.dict(os.environ, {
            "KALSHI_API_KEY": "test_key",
            "KALSHI_PRIVATE_KEY_PEM": "test_pem",
        }, clear=True):
            mock_config = MagicMock()
            mock_config_class.return_value = mock_config

            _build_client()

            assert mock_config.api_key_id == "test_key"


class TestGetKalshiClient:
    """Tests for get_kalshi_client function."""

    @patch("trading.integrations.kalshi_client._build_client")
    @patch("trading.integrations.kalshi_client.logger")
    def test_get_client_cached(self, mock_logger, mock_build):
        """Test that client is cached."""
        mock_client = MagicMock()
        mock_client.api_client.configuration.host = "https://test.kalshi.com"
        mock_build.return_value = mock_client

        # Clear cache before test
        get_kalshi_client.cache_clear()

        client1 = get_kalshi_client()
        client2 = get_kalshi_client()

        assert client1 is client2
        mock_build.assert_called_once()
        mock_logger.debug.assert_called_once()


class TestFetchKalshiBalance:
    """Tests for fetch_kalshi_balance function."""

    @patch("trading.integrations.kalshi_client.get_kalshi_client")
    def test_fetch_balance_with_to_dict(self, mock_get_client):
        """Test fetching balance when response has to_dict method."""
        mock_balance = MagicMock()
        mock_balance.to_dict.return_value = {
            "balance": 1000.0,
            "available_cash": 950.0,
        }
        mock_get_client.return_value.get_balance.return_value = mock_balance

        result = fetch_kalshi_balance()

        assert result["balance"] == 1000.0
        assert "raw" in result

    @patch("trading.integrations.kalshi_client.get_kalshi_client")
    def test_fetch_balance_as_dict(self, mock_get_client):
        """Test fetching balance when response is already a dict."""
        mock_get_client.return_value.get_balance.return_value = {
            "balance": 500.0,
            "available_balance": 450.0,
        }

        result = fetch_kalshi_balance()

        assert result["balance"] == 500.0

    @patch("trading.integrations.kalshi_client.get_kalshi_client")
    def test_fetch_balance_fallback_to_dict(self, mock_get_client):
        """Test fetching balance fallback to __dict__."""
        class SimpleBalance:
            def __init__(self):
                self.balance = 250.0
                self.available_cash = 200.0

        mock_get_client.return_value.get_balance.return_value = SimpleBalance()

        result = fetch_kalshi_balance()

        assert result["balance"] == 250.0

    @patch("trading.integrations.kalshi_client.get_kalshi_client")
    def test_fetch_balance_available_cash_fallback(self, mock_get_client):
        """Test using available_cash when balance is not present."""
        mock_balance = MagicMock()
        mock_balance.to_dict.return_value = {
            "available_cash": 750.0,
        }
        mock_get_client.return_value.get_balance.return_value = mock_balance

        result = fetch_kalshi_balance()

        assert result["balance"] == 750.0

    @patch("trading.integrations.kalshi_client.get_kalshi_client")
    def test_fetch_balance_available_balance_fallback(self, mock_get_client):
        """Test using available_balance as last fallback."""
        mock_balance = MagicMock()
        mock_balance.to_dict.return_value = {
            "available_balance": 300.0,
        }
        mock_get_client.return_value.get_balance.return_value = mock_balance

        result = fetch_kalshi_balance()

        assert result["balance"] == 300.0
