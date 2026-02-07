"""Tests for config/settings.py."""
import pytest
import os
from unittest.mock import patch
from config.settings import (
    Environment, ServerConfig, Settings, get_settings, reload_settings, _settings
)


class TestEnvironment:
    """Test Environment enum."""

    def test_environment_values(self):
        """Test environment enum values."""
        assert Environment.DEVELOPMENT.value == "development"
        assert Environment.STAGING.value == "staging"
        assert Environment.PRODUCTION.value == "production"


class TestServerConfig:
    """Test ServerConfig dataclass."""

    def test_default_values(self):
        """Test default server config values."""
        config = ServerConfig()
        assert config.host == "0.0.0.0"
        assert config.port == 8001
        assert config.debug is True
        assert config.cors_origins == ["*"]

    def test_from_env_defaults(self):
        """Test ServerConfig.from_env with defaults."""
        with patch.dict(os.environ, {}, clear=True):
            config = ServerConfig.from_env()
            assert config.host == "0.0.0.0"
            assert config.port == 8001
            assert config.debug is True

    def test_from_env_custom(self):
        """Test ServerConfig.from_env with custom values."""
        env_vars = {
            "SERVER_HOST": "127.0.0.1",
            "SERVER_PORT": "9000",
            "DEBUG": "false",
            "CORS_ORIGINS": "http://localhost,http://example.com",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            config = ServerConfig.from_env()
            assert config.host == "127.0.0.1"
            assert config.port == 9000
            assert config.debug is False
            assert config.cors_origins == ["http://localhost", "http://example.com"]


class TestSettings:
    """Test Settings dataclass."""

    def test_default_values(self):
        """Test default settings values."""
        settings = Settings()
        assert settings.environment == Environment.DEVELOPMENT
        assert settings.enable_prediction_markets is True
        assert settings.enable_prediction_market_stub is True
        assert isinstance(settings.server, ServerConfig)

    def test_from_env_development(self):
        """Test Settings.from_env for development."""
        with patch.dict(os.environ, {"MERID_ENV": "development"}, clear=True):
            settings = Settings.from_env()
            assert settings.environment == Environment.DEVELOPMENT
            assert settings.enable_prediction_market_stub is True

    def test_from_env_production(self):
        """Test Settings.from_env for production."""
        env_vars = {
            "MERID_ENV": "production",
            "DEBUG": "false",
            "ENABLE_PREDICTION_MARKET_STUB": "false",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            settings = Settings.from_env()
            assert settings.environment == Environment.PRODUCTION
            assert settings.enable_prediction_market_stub is False

    def test_from_env_invalid_env(self):
        """Test Settings.from_env with invalid environment."""
        with patch.dict(os.environ, {"MERID_ENV": "invalid"}, clear=True):
            settings = Settings.from_env()
            assert settings.environment == Environment.DEVELOPMENT

    def test_from_env_staging(self):
        """Test Settings.from_env for staging."""
        with patch.dict(os.environ, {"MERID_ENV": "staging"}, clear=True):
            settings = Settings.from_env()
            assert settings.environment == Environment.STAGING

    def test_to_dict(self):
        """Test Settings.to_dict."""
        settings = Settings()
        d = settings.to_dict()
        
        assert d["environment"] == "development"
        assert "server" in d
        assert d["server"]["host"] == "0.0.0.0"
        assert d["server"]["port"] == 8001
        assert "features" in d
        assert d["features"]["prediction_markets"] is True

    def test_validate_no_warnings(self):
        """Test validate with no warnings."""
        settings = Settings(
            environment=Environment.DEVELOPMENT,
            server=ServerConfig(debug=True)
        )
        warnings = settings.validate()
        assert len(warnings) == 0

    def test_validate_production_debug_warning(self):
        """Test validate warns about debug in production."""
        settings = Settings(
            environment=Environment.PRODUCTION,
            server=ServerConfig(debug=True)
        )
        warnings = settings.validate()
        assert len(warnings) == 1
        assert "Debug mode enabled in production" in warnings[0]

    def test_validate_production_no_debug(self):
        """Test validate with production and no debug."""
        settings = Settings(
            environment=Environment.PRODUCTION,
            server=ServerConfig(debug=False)
        )
        warnings = settings.validate()
        assert len(warnings) == 0


class TestGetSettings:
    """Test get_settings function."""

    def setup_method(self):
        """Reset singleton before each test."""
        import config.settings as cs
        cs._settings = None

    def test_singleton(self):
        """Test get_settings returns singleton."""
        with patch.dict(os.environ, {}, clear=True):
            settings1 = get_settings()
            settings2 = get_settings()
            assert settings1 is settings2

    def test_get_settings_logs(self):
        """Test get_settings logs environment."""
        import config.settings as cs
        cs._settings = None
        
        with patch.dict(os.environ, {"MERID_ENV": "development"}, clear=True):
            with patch.object(cs.logger, 'info') as mock_info:
                with patch.object(cs.logger, 'warning'):
                    get_settings()
                    mock_info.assert_called_once()


class TestReloadSettings:
    """Test reload_settings function."""

    def setup_method(self):
        """Reset singleton before each test."""
        import config.settings as cs
        cs._settings = None

    def test_reload_creates_new_settings(self):
        """Test reload_settings creates new settings."""
        with patch.dict(os.environ, {}, clear=True):
            settings1 = get_settings()
            settings2 = reload_settings()
            assert settings1 is not settings2
            assert settings2.environment == Environment.DEVELOPMENT

    def test_reload_logs(self):
        """Test reload_settings logs."""
        import config.settings as cs
        cs._settings = None
        
        with patch.dict(os.environ, {}, clear=True):
            with patch.object(cs.logger, 'info') as mock_info:
                reload_settings()
                mock_info.assert_called_with("Settings reloaded")
