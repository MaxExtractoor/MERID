"""Tests for MERID settings module - Batch 27 Coverage."""
import pytest
from unittest.mock import patch, MagicMock
import os

from merid.settings import Settings, settings


class TestSettings:
    """Tests for Settings class."""

    def test_default_values(self):
        """Test default settings values (may be overridden by .env)."""
        s = Settings()
        # These may be overridden by environment, just check they exist
        assert hasattr(s, 'MERID_ENV')
        assert hasattr(s, 'MERID_LOG_LEVEL')
        assert hasattr(s, 'HOST')
        assert hasattr(s, 'PORT')
        assert isinstance(s.PORT, int)

    def test_database_settings(self):
        """Test database settings are loaded."""
        s = Settings()
        assert hasattr(s, 'NEO4J_URI')
        assert hasattr(s, 'NEO4J_USER')
        assert hasattr(s, 'NEO4J_PASSWORD')

    def test_feature_flags(self):
        """Test feature flags are loaded."""
        s = Settings()
        assert hasattr(s, 'MERID_ENABLE_CHAINLINK')
        assert hasattr(s, 'MERID_ENABLE_AUGUR')
        assert hasattr(s, 'MERID_ENABLE_POLYMARKET')
        assert isinstance(s.MERID_ENABLE_POLYMARKET, bool)

    def test_live_only_mode_defaults(self):
        """Test live-only mode default settings."""
        s = Settings()
        assert s.MERID_USE_MOCK_ARB_DATA is False
        assert s.MERID_USE_DEMO_TRADES is False
        assert s.MERID_USE_SAMPLE_DATA is False
        assert s.MERID_USE_MOCK_STREAMS is False
        assert s.MERID_ENABLE_LIVE_PRICE_FEEDS is True
        assert s.MERID_ENABLE_REAL_PREDICTION_MARKETS is True
        assert s.MERID_ENABLE_REAL_SOLANA_WS is True
        assert s.MERID_ENABLE_REAL_NEWS is True

    def test_is_development(self):
        """Test is_development property."""
        s = Settings(MERID_ENV="development")
        assert s.is_development is True
        
        s = Settings(MERID_ENV="dev")
        assert s.is_development is True
        
        s = Settings(MERID_ENV="local")
        assert s.is_development is True
        
        s = Settings(MERID_ENV="production")
        assert s.is_development is False

    def test_is_production(self):
        """Test is_production property."""
        s = Settings(MERID_ENV="production")
        assert s.is_production is True
        
        s = Settings(MERID_ENV="prod")
        assert s.is_production is True
        
        s = Settings(MERID_ENV="development")
        assert s.is_production is False

    def test_is_testing(self):
        """Test is_testing property."""
        s = Settings(MERID_ENV="testing")
        assert s.is_testing is True
        
        s = Settings(MERID_ENV="test")
        assert s.is_testing is True
        
        s = Settings(MERID_ENV="development")
        assert s.is_testing is False

    def test_allow_websocket_dev_mode_development(self):
        """Test WebSocket dev mode in development."""
        s = Settings(MERID_ENV="development", MERID_DEV_ALLOW_WS=True)
        assert s.allow_websocket_dev_mode is True
        
        s = Settings(MERID_ENV="development", MERID_DEV_ALLOW_WS=False)
        assert s.allow_websocket_dev_mode is False

    def test_allow_websocket_dev_mode_production(self):
        """Test WebSocket dev mode always disabled in production."""
        s = Settings(MERID_ENV="production", MERID_DEV_ALLOW_WS=True)
        assert s.allow_websocket_dev_mode is False  # Always False in production

    def test_is_live_only_mode_true(self):
        """Test live-only mode detection when true."""
        s = Settings(
            MERID_USE_MOCK_ARB_DATA=False,
            MERID_USE_DEMO_TRADES=False,
            MERID_USE_SAMPLE_DATA=False,
            MERID_USE_MOCK_STREAMS=False
        )
        assert s.is_live_only_mode is True

    def test_is_live_only_mode_false(self):
        """Test live-only mode detection when false."""
        s = Settings(MERID_USE_MOCK_ARB_DATA=True)
        assert s.is_live_only_mode is False
        
        s = Settings(MERID_USE_DEMO_TRADES=True)
        assert s.is_live_only_mode is False

    def test_validate_live_only_mode_no_issues(self):
        """Test live-only mode validation with no issues."""
        s = Settings(
            MERID_USE_MOCK_ARB_DATA=False,
            MERID_USE_DEMO_TRADES=False,
            MERID_USE_SAMPLE_DATA=False,
            MERID_USE_MOCK_STREAMS=False,
            MERID_ENABLE_LIVE_PRICE_FEEDS=True,
            MERID_ENABLE_REAL_PREDICTION_MARKETS=True,
            MERID_ENABLE_REAL_SOLANA_WS=True
        )
        issues = s.validate_live_only_mode()
        assert issues == []

    def test_validate_live_only_mode_with_mock_data(self):
        """Test validation detects mock data usage."""
        s = Settings(MERID_USE_MOCK_ARB_DATA=True)
        issues = s.validate_live_only_mode()
        assert len(issues) == 1
        assert "MERID_USE_MOCK_ARB_DATA" in issues[0]

    def test_validate_live_only_mode_with_demo_trades(self):
        """Test validation detects demo trades."""
        s = Settings(MERID_USE_DEMO_TRADES=True)
        issues = s.validate_live_only_mode()
        assert any("MERID_USE_DEMO_TRADES" in issue for issue in issues)

    def test_validate_live_only_mode_with_sample_data(self):
        """Test validation detects sample data."""
        s = Settings(MERID_USE_SAMPLE_DATA=True)
        issues = s.validate_live_only_mode()
        assert any("MERID_USE_SAMPLE_DATA" in issue for issue in issues)

    def test_validate_live_only_mode_with_mock_streams(self):
        """Test validation detects mock streams."""
        s = Settings(MERID_USE_MOCK_STREAMS=True)
        issues = s.validate_live_only_mode()
        assert any("MERID_USE_MOCK_STREAMS" in issue for issue in issues)

    def test_validate_live_only_mode_disabled_features(self):
        """Test validation detects disabled real-time features."""
        s = Settings(
            MERID_ENABLE_LIVE_PRICE_FEEDS=False,
            MERID_ENABLE_REAL_PREDICTION_MARKETS=False,
            MERID_ENABLE_REAL_SOLANA_WS=False
        )
        issues = s.validate_live_only_mode()
        assert any("MERID_ENABLE_LIVE_PRICE_FEEDS" in issue for issue in issues)
        assert any("MERID_ENABLE_REAL_PREDICTION_MARKETS" in issue for issue in issues)
        assert any("MERID_ENABLE_REAL_SOLANA_WS" in issue for issue in issues)

    def test_validate_required_for_production_not_production(self):
        """Test production validation in non-production environment."""
        s = Settings(MERID_ENV="development")
        missing = s.validate_required_for_production()
        assert missing == []

    def test_validate_required_for_production_all_missing(self):
        """Test production validation with all required vars missing."""
        s = Settings(
            MERID_ENV="production",
            SECRET_KEY=None,
            NEO4J_PASSWORD="change_me",
            SUPABASE_URL=None,
            SUPABASE_ANON_KEY=None
        )
        missing = s.validate_required_for_production()
        assert "SECRET_KEY" in missing
        assert "SUPABASE_URL" in missing
        assert "SUPABASE_ANON_KEY" in missing

    def test_validate_required_for_production_some_present(self):
        """Test production validation with some vars present."""
        s = Settings(
            MERID_ENV="production",
            SECRET_KEY="secret",
            NEO4J_PASSWORD="password",
            SUPABASE_URL="https://example.supabase.co",
            SUPABASE_ANON_KEY="anon_key"
        )
        missing = s.validate_required_for_production()
        assert missing == []

    def test_custom_values(self):
        """Test settings with custom values."""
        s = Settings(
            MERID_ENV="production",
            HOST="0.0.0.0",
            PORT=8080,
            MERID_LOG_LEVEL="DEBUG",
            MERID_ENABLE_WHALE_INTEL=True
        )
        assert s.MERID_ENV == "production"
        assert s.HOST == "0.0.0.0"
        assert s.PORT == 8080
        assert s.MERID_LOG_LEVEL == "DEBUG"
        assert s.MERID_ENABLE_WHALE_INTEL is True


class TestGlobalSettings:
    """Tests for global settings instance."""

    def test_global_settings_exists(self):
        """Test that global settings instance exists."""
        assert settings is not None
        assert isinstance(settings, Settings)

    def test_global_settings_singleton(self):
        """Test that global settings is a singleton-like instance."""
        from merid.settings import settings as settings2
        assert settings is settings2
