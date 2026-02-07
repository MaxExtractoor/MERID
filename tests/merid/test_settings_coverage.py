"""Comprehensive tests for merid/settings.py - Coverage improvement."""

import pytest
import os
from unittest.mock import patch, MagicMock

from merid.settings import Settings


# =============================================================================
# Settings Initialization Tests
# =============================================================================

class TestSettingsInit:
    """Test Settings initialization."""

    def test_default_values(self, monkeypatch):
        monkeypatch.delenv("MERID_ENV", raising=False)
        monkeypatch.delenv("MERID_LOG_LEVEL", raising=False)
        
        settings = Settings()
        
        assert settings.MERID_ENV == "development"
        assert settings.MERID_LOG_LEVEL == "INFO"

    def test_env_file_exists_logging(self, monkeypatch, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("MERID_ENV=test")
        
        with patch("merid.settings.os.path.exists") as mock_exists:
            mock_exists.return_value = True
            settings = Settings()

    def test_env_file_not_found_logging(self, monkeypatch):
        with patch("merid.settings.os.path.exists") as mock_exists:
            mock_exists.return_value = False
            settings = Settings()


# =============================================================================
# Environment Mode Properties Tests
# =============================================================================

class TestIsDevelopment:
    """Test is_development property."""

    def test_development_mode(self, monkeypatch):
        monkeypatch.setenv("MERID_ENV", "development")
        settings = Settings()
        assert settings.is_development is True

    def test_dev_mode(self, monkeypatch):
        monkeypatch.setenv("MERID_ENV", "dev")
        settings = Settings()
        assert settings.is_development is True

    def test_local_mode(self, monkeypatch):
        monkeypatch.setenv("MERID_ENV", "local")
        settings = Settings()
        assert settings.is_development is True

    def test_not_development(self, monkeypatch):
        monkeypatch.setenv("MERID_ENV", "production")
        settings = Settings()
        assert settings.is_development is False


class TestIsProduction:
    """Test is_production property."""

    def test_production_mode(self, monkeypatch):
        monkeypatch.setenv("MERID_ENV", "production")
        settings = Settings()
        assert settings.is_production is True

    def test_prod_mode(self, monkeypatch):
        monkeypatch.setenv("MERID_ENV", "prod")
        settings = Settings()
        assert settings.is_production is True

    def test_not_production(self, monkeypatch):
        monkeypatch.setenv("MERID_ENV", "development")
        settings = Settings()
        assert settings.is_production is False


class TestIsTesting:
    """Test is_testing property."""

    def test_testing_mode(self, monkeypatch):
        monkeypatch.setenv("MERID_ENV", "testing")
        settings = Settings()
        assert settings.is_testing is True

    def test_test_mode(self, monkeypatch):
        monkeypatch.setenv("MERID_ENV", "test")
        settings = Settings()
        assert settings.is_testing is True

    def test_not_testing(self, monkeypatch):
        monkeypatch.setenv("MERID_ENV", "development")
        settings = Settings()
        assert settings.is_testing is False


# =============================================================================
# WebSocket Dev Mode Tests
# =============================================================================

class TestAllowWebsocketDevMode:
    """Test allow_websocket_dev_mode property."""

    def test_dev_mode_ws_allowed(self, monkeypatch):
        monkeypatch.setenv("MERID_ENV", "development")
        monkeypatch.setenv("MERID_DEV_ALLOW_WS", "true")
        settings = Settings()
        assert settings.allow_websocket_dev_mode is True

    def test_dev_mode_ws_not_allowed(self, monkeypatch):
        monkeypatch.setenv("MERID_ENV", "development")
        monkeypatch.setenv("MERID_DEV_ALLOW_WS", "false")
        settings = Settings()
        assert settings.allow_websocket_dev_mode is False

    def test_production_always_blocks_ws_dev(self, monkeypatch):
        monkeypatch.setenv("MERID_ENV", "production")
        monkeypatch.setenv("MERID_DEV_ALLOW_WS", "true")
        settings = Settings()
        # Production should ALWAYS block dev mode WebSocket
        assert settings.allow_websocket_dev_mode is False


# =============================================================================
# Live-Only Mode Tests
# =============================================================================

class TestIsLiveOnlyMode:
    """Test is_live_only_mode property."""

    def test_live_only_mode_enabled(self, monkeypatch):
        monkeypatch.setenv("MERID_USE_MOCK_ARB_DATA", "false")
        monkeypatch.setenv("MERID_USE_DEMO_TRADES", "false")
        monkeypatch.setenv("MERID_USE_SAMPLE_DATA", "false")
        monkeypatch.setenv("MERID_USE_MOCK_STREAMS", "false")
        settings = Settings()
        assert settings.is_live_only_mode is True

    def test_live_only_mode_disabled_by_mock_arb(self, monkeypatch):
        monkeypatch.setenv("MERID_USE_MOCK_ARB_DATA", "true")
        monkeypatch.setenv("MERID_USE_DEMO_TRADES", "false")
        monkeypatch.setenv("MERID_USE_SAMPLE_DATA", "false")
        monkeypatch.setenv("MERID_USE_MOCK_STREAMS", "false")
        settings = Settings()
        assert settings.is_live_only_mode is False

    def test_live_only_mode_disabled_by_demo_trades(self, monkeypatch):
        monkeypatch.setenv("MERID_USE_MOCK_ARB_DATA", "false")
        monkeypatch.setenv("MERID_USE_DEMO_TRADES", "true")
        settings = Settings()
        assert settings.is_live_only_mode is False


# =============================================================================
# Validate Live-Only Mode Tests
# =============================================================================

class TestValidateLiveOnlyMode:
    """Test validate_live_only_mode method."""

    def test_all_valid(self, monkeypatch):
        monkeypatch.setenv("MERID_USE_MOCK_ARB_DATA", "false")
        monkeypatch.setenv("MERID_USE_DEMO_TRADES", "false")
        monkeypatch.setenv("MERID_USE_SAMPLE_DATA", "false")
        monkeypatch.setenv("MERID_USE_MOCK_STREAMS", "false")
        monkeypatch.setenv("MERID_ENABLE_LIVE_PRICE_FEEDS", "true")
        monkeypatch.setenv("MERID_ENABLE_REAL_PREDICTION_MARKETS", "true")
        monkeypatch.setenv("MERID_ENABLE_REAL_SOLANA_WS", "true")
        settings = Settings()
        
        issues = settings.validate_live_only_mode()
        assert issues == []

    def test_mock_arb_data_issue(self, monkeypatch):
        monkeypatch.setenv("MERID_USE_MOCK_ARB_DATA", "true")
        settings = Settings()
        
        issues = settings.validate_live_only_mode()
        assert any("MERID_USE_MOCK_ARB_DATA" in issue for issue in issues)

    def test_demo_trades_issue(self, monkeypatch):
        monkeypatch.setenv("MERID_USE_DEMO_TRADES", "true")
        settings = Settings()
        
        issues = settings.validate_live_only_mode()
        assert any("MERID_USE_DEMO_TRADES" in issue for issue in issues)

    def test_sample_data_issue(self, monkeypatch):
        monkeypatch.setenv("MERID_USE_SAMPLE_DATA", "true")
        settings = Settings()
        
        issues = settings.validate_live_only_mode()
        assert any("MERID_USE_SAMPLE_DATA" in issue for issue in issues)

    def test_mock_streams_issue(self, monkeypatch):
        monkeypatch.setenv("MERID_USE_MOCK_STREAMS", "true")
        settings = Settings()
        
        issues = settings.validate_live_only_mode()
        assert any("MERID_USE_MOCK_STREAMS" in issue for issue in issues)

    def test_live_price_feeds_disabled(self, monkeypatch):
        monkeypatch.setenv("MERID_ENABLE_LIVE_PRICE_FEEDS", "false")
        settings = Settings()
        
        issues = settings.validate_live_only_mode()
        assert any("MERID_ENABLE_LIVE_PRICE_FEEDS" in issue for issue in issues)

    def test_real_prediction_markets_disabled(self, monkeypatch):
        monkeypatch.setenv("MERID_ENABLE_REAL_PREDICTION_MARKETS", "false")
        settings = Settings()
        
        issues = settings.validate_live_only_mode()
        assert any("MERID_ENABLE_REAL_PREDICTION_MARKETS" in issue for issue in issues)

    def test_real_solana_ws_disabled(self, monkeypatch):
        monkeypatch.setenv("MERID_ENABLE_REAL_SOLANA_WS", "false")
        settings = Settings()
        
        issues = settings.validate_live_only_mode()
        assert any("MERID_ENABLE_REAL_SOLANA_WS" in issue for issue in issues)


# =============================================================================
# Validate Required for Production Tests
# =============================================================================

class TestValidateRequiredForProduction:
    """Test validate_required_for_production method."""

    def test_not_production_returns_empty(self, monkeypatch):
        monkeypatch.setenv("MERID_ENV", "development")
        settings = Settings()
        
        missing = settings.validate_required_for_production()
        assert missing == []

    def test_production_missing_secret_key(self, monkeypatch):
        monkeypatch.setenv("MERID_ENV", "production")
        monkeypatch.delenv("SECRET_KEY", raising=False)
        settings = Settings()
        
        missing = settings.validate_required_for_production()
        assert "SECRET_KEY" in missing

    def test_production_missing_neo4j_password(self, monkeypatch):
        monkeypatch.setenv("MERID_ENV", "production")
        monkeypatch.setenv("NEO4J_PASSWORD", "")
        settings = Settings()
        
        missing = settings.validate_required_for_production()
        # Empty string is falsy, so it should be in missing
        assert "NEO4J_PASSWORD" in missing

    def test_production_all_required_present(self, monkeypatch):
        monkeypatch.setenv("MERID_ENV", "production")
        monkeypatch.setenv("SECRET_KEY", "test_secret")
        monkeypatch.setenv("NEO4J_PASSWORD", "test_password")
        monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
        monkeypatch.setenv("SUPABASE_ANON_KEY", "test_anon_key")
        settings = Settings()
        
        missing = settings.validate_required_for_production()
        assert missing == []


# =============================================================================
# Default Values Tests
# =============================================================================

class TestDefaultValues:
    """Test default configuration values."""

    def test_neo4j_defaults(self, monkeypatch):
        monkeypatch.delenv("NEO4J_URI", raising=False)
        monkeypatch.delenv("NEO4J_USER", raising=False)
        settings = Settings()
        
        # Check URI contains expected host (scheme may vary based on .env)
        assert "localhost:7687" in settings.NEO4J_URI
        assert settings.NEO4J_USER == "neo4j"

    def test_server_defaults(self, monkeypatch):
        monkeypatch.delenv("HOST", raising=False)
        monkeypatch.delenv("PORT", raising=False)
        settings = Settings()
        
        assert settings.HOST == "127.0.0.1"
        assert settings.PORT == 8011

    def test_access_token_default(self, monkeypatch):
        monkeypatch.delenv("ACCESS_TOKEN_EXPIRE_MINUTES", raising=False)
        settings = Settings()
        
        assert settings.ACCESS_TOKEN_EXPIRE_MINUTES == 30


# =============================================================================
# Trading Mode Properties Tests
# =============================================================================

class TestIsPaperTrading:
    """Test is_paper_trading property."""

    def test_paper_trading_mode(self, monkeypatch):
        monkeypatch.setenv("MERID_TRADING_MODE", "paper")
        settings = Settings()
        assert settings.is_paper_trading is True

    def test_live_trading_mode_not_paper(self, monkeypatch):
        monkeypatch.setenv("MERID_TRADING_MODE", "live")
        settings = Settings()
        assert settings.is_paper_trading is False


class TestIsLiveTrading:
    """Test is_live_trading property."""

    def test_live_trading_unlocked(self, monkeypatch):
        monkeypatch.setenv("MERID_TRADING_MODE", "live")
        monkeypatch.setenv("MERID_LIVE_TRADING_UNLOCKED", "true")
        settings = Settings()
        assert settings.is_live_trading is True

    def test_live_trading_locked(self, monkeypatch):
        monkeypatch.setenv("MERID_TRADING_MODE", "live")
        monkeypatch.setenv("MERID_LIVE_TRADING_UNLOCKED", "false")
        settings = Settings()
        assert settings.is_live_trading is False

    def test_paper_mode_not_live(self, monkeypatch):
        monkeypatch.setenv("MERID_TRADING_MODE", "paper")
        monkeypatch.setenv("MERID_LIVE_TRADING_UNLOCKED", "true")
        settings = Settings()
        assert settings.is_live_trading is False


# =============================================================================
# Validate Trading Mode Tests
# =============================================================================

class TestValidateTradingMode:
    """Test validate_trading_mode method."""

    def test_valid_paper_mode(self, monkeypatch):
        monkeypatch.setenv("MERID_TRADING_MODE", "paper")
        settings = Settings()
        issues = settings.validate_trading_mode()
        assert issues == []

    def test_invalid_trading_mode(self, monkeypatch):
        monkeypatch.setenv("MERID_TRADING_MODE", "invalid_mode")
        settings = Settings()
        issues = settings.validate_trading_mode()
        assert len(issues) > 0
        assert "must be one of" in issues[0]

    def test_live_mode_requires_unlock(self, monkeypatch):
        monkeypatch.setenv("MERID_TRADING_MODE", "live")
        monkeypatch.setenv("MERID_LIVE_TRADING_UNLOCKED", "false")
        settings = Settings()
        issues = settings.validate_trading_mode()
        assert any("MERID_LIVE_TRADING_UNLOCKED" in issue for issue in issues)

    def test_live_mode_requires_max_order_size(self, monkeypatch):
        monkeypatch.setenv("MERID_TRADING_MODE", "live")
        monkeypatch.setenv("MERID_LIVE_TRADING_UNLOCKED", "true")
        monkeypatch.setenv("MERID_MAX_ORDER_SIZE_USD", "0")
        settings = Settings()
        issues = settings.validate_trading_mode()
        assert any("MERID_MAX_ORDER_SIZE_USD" in issue for issue in issues)

    def test_live_mode_requires_max_daily_loss(self, monkeypatch):
        monkeypatch.setenv("MERID_TRADING_MODE", "live")
        monkeypatch.setenv("MERID_LIVE_TRADING_UNLOCKED", "true")
        monkeypatch.setenv("MERID_MAX_DAILY_LOSS_USD", "0")
        settings = Settings()
        issues = settings.validate_trading_mode()
        assert any("MERID_MAX_DAILY_LOSS_USD" in issue for issue in issues)

    def test_live_mode_requires_max_position_size(self, monkeypatch):
        monkeypatch.setenv("MERID_TRADING_MODE", "live")
        monkeypatch.setenv("MERID_LIVE_TRADING_UNLOCKED", "true")
        monkeypatch.setenv("MERID_MAX_POSITION_SIZE_USD", "0")
        settings = Settings()
        issues = settings.validate_trading_mode()
        assert any("MERID_MAX_POSITION_SIZE_USD" in issue for issue in issues)


# =============================================================================
# Validate Venue Credentials Tests
# =============================================================================

class TestValidateVenueCredentials:
    """Test validate_venue_credentials method."""

    def test_kalshi_missing_api_key(self, monkeypatch):
        monkeypatch.setenv("KALSHI_API_KEY_ID", "")
        settings = Settings()
        issues = settings.validate_venue_credentials("kalshi")
        assert any("KALSHI_API_KEY_ID" in issue for issue in issues)

    def test_kalshi_missing_private_key(self, monkeypatch):
        monkeypatch.setenv("KALSHI_API_KEY_ID", "test_key")
        monkeypatch.setenv("KALSHI_PRIVATE_KEY_PATH", "")
        monkeypatch.setenv("KALSHI_PRIVATE_KEY_PEM", "")
        settings = Settings()
        issues = settings.validate_venue_credentials("kalshi")
        assert any("KALSHI_PRIVATE_KEY" in issue for issue in issues)

    def test_polymarket_missing_api_key(self, monkeypatch):
        monkeypatch.setenv("POLYMARKET_API_KEY", "")
        settings = Settings()
        issues = settings.validate_venue_credentials("polymarket")
        assert any("POLYMARKET_API_KEY" in issue for issue in issues)

    def test_polymarket_missing_wallet(self, monkeypatch):
        monkeypatch.setenv("POLYMARKET_API_KEY", "test_key")
        monkeypatch.setenv("POLYMARKET_WALLET_ADDRESS", "")
        settings = Settings()
        issues = settings.validate_venue_credentials("polymarket")
        assert any("POLYMARKET_WALLET_ADDRESS" in issue for issue in issues)

    def test_alpaca_missing_api_key(self, monkeypatch):
        monkeypatch.setenv("ALPACA_API_KEY", "")
        settings = Settings()
        issues = settings.validate_venue_credentials("alpaca")
        assert any("ALPACA_API_KEY" in issue for issue in issues)

    def test_alpaca_missing_secret(self, monkeypatch):
        monkeypatch.setenv("ALPACA_API_KEY", "test_key")
        monkeypatch.setenv("ALPACA_API_SECRET", "")
        settings = Settings()
        issues = settings.validate_venue_credentials("alpaca")
        assert any("ALPACA_API_SECRET" in issue for issue in issues)

    def test_unknown_venue(self, monkeypatch):
        settings = Settings()
        issues = settings.validate_venue_credentials("unknown_venue")
        assert issues == []


# =============================================================================
# Validate For Go Live Tests
# =============================================================================

class TestValidateForGoLive:
    """Test validate_for_go_live method."""

    def test_go_live_with_issues(self, monkeypatch):
        monkeypatch.setenv("MERID_TRADING_MODE", "invalid")
        settings = Settings()
        result = settings.validate_for_go_live()
        assert result["ready"] is False
        assert len(result["issues"]) > 0

    def test_go_live_checks_venues(self, monkeypatch):
        monkeypatch.setenv("MERID_TRADING_MODE", "paper")
        monkeypatch.setenv("KALSHI_API_KEY_ID", "")
        settings = Settings()
        result = settings.validate_for_go_live(venues=["kalshi"])
        assert any("KALSHI" in issue for issue in result["issues"])

    def test_go_live_production_requirements(self, monkeypatch):
        monkeypatch.setenv("MERID_ENV", "production")
        monkeypatch.setenv("MERID_TRADING_MODE", "paper")
        monkeypatch.setenv("SECRET_KEY", "")
        settings = Settings()
        result = settings.validate_for_go_live(venues=[])
        assert any("SECRET_KEY" in issue for issue in result["issues"])

    def test_go_live_high_order_size_warning(self, monkeypatch):
        monkeypatch.setenv("MERID_TRADING_MODE", "paper")
        monkeypatch.setenv("MERID_MAX_ORDER_SIZE_USD", "2000")
        settings = Settings()
        result = settings.validate_for_go_live(venues=[])
        assert any("MERID_MAX_ORDER_SIZE_USD" in w for w in result["warnings"])

    def test_go_live_high_daily_loss_warning(self, monkeypatch):
        monkeypatch.setenv("MERID_TRADING_MODE", "paper")
        monkeypatch.setenv("MERID_MAX_DAILY_LOSS_USD", "10000")
        settings = Settings()
        result = settings.validate_for_go_live(venues=[])
        assert any("MERID_MAX_DAILY_LOSS_USD" in w for w in result["warnings"])

    def test_go_live_no_confirmation_warning(self, monkeypatch):
        monkeypatch.setenv("MERID_TRADING_MODE", "live")
        monkeypatch.setenv("MERID_LIVE_TRADING_UNLOCKED", "true")
        monkeypatch.setenv("MERID_REQUIRE_CONFIRMATION", "false")
        monkeypatch.setenv("MERID_MAX_ORDER_SIZE_USD", "100")
        monkeypatch.setenv("MERID_MAX_DAILY_LOSS_USD", "100")
        monkeypatch.setenv("MERID_MAX_POSITION_SIZE_USD", "100")
        settings = Settings()
        result = settings.validate_for_go_live(venues=[])
        assert any("MERID_REQUIRE_CONFIRMATION" in w for w in result["warnings"])

    def test_go_live_returns_mode_and_env(self, monkeypatch):
        monkeypatch.setenv("MERID_TRADING_MODE", "paper")
        monkeypatch.setenv("MERID_ENV", "development")
        settings = Settings()
        result = settings.validate_for_go_live(venues=[])
        assert result["mode"] == "paper"
        assert result["env"] == "development"
