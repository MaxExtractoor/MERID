"""Comprehensive tests for trading/config/runtime_config.py - Coverage improvement."""

import pytest
from unittest.mock import patch

from trading.config.runtime_config import (
    GlobalTradingMode, VenueMode, VenueConfig, TradingRuntimeState,
    TradingRuntimeConfig, get_runtime_config, _env_bool
)


# =============================================================================
# Enum Tests
# =============================================================================

class TestGlobalTradingMode:
    """Test GlobalTradingMode enum."""

    def test_offline(self):
        # ZT2: OFFLINE is now aliased to MOCK (value="mock")
        assert GlobalTradingMode.OFFLINE.value == "mock"

    def test_sim(self):
        # ZT2: SIM is now aliased to MOCK (value="mock")
        assert GlobalTradingMode.SIM.value == "mock"

    def test_paper(self):
        assert GlobalTradingMode.PAPER.value == "paper"

    def test_live(self):
        assert GlobalTradingMode.LIVE.value == "live"

    def test_hybrid(self):
        # ZT2: HYBRID is now aliased to MOCK (value="mock")
        assert GlobalTradingMode.HYBRID.value == "mock"


class TestVenueMode:
    """Test VenueMode enum."""

    def test_disabled(self):
        assert VenueMode.DISABLED.value == "disabled"

    def test_sim(self):
        assert VenueMode.SIM.value == "sim"

    def test_paper(self):
        assert VenueMode.PAPER.value == "paper"

    def test_live(self):
        assert VenueMode.LIVE.value == "live"


# =============================================================================
# VenueConfig Tests
# =============================================================================

class TestVenueConfig:
    """Test VenueConfig dataclass."""

    def test_creation(self):
        config = VenueConfig(venue_id="alpaca", label="Alpaca")
        assert config.venue_id == "alpaca"
        assert config.label == "Alpaca"

    def test_defaults(self):
        config = VenueConfig(venue_id="test", label="Test")
        assert config.mode == VenueMode.DISABLED
        assert config.enabled is False
        assert config.max_notional_usd == 0.0

    def test_to_dict(self):
        config = VenueConfig(
            venue_id="coinbase",
            label="Coinbase",
            mode=VenueMode.LIVE,
            enabled=True
        )
        result = config.to_dict()
        assert result["venue_id"] == "coinbase"
        assert result["mode"] == VenueMode.LIVE


# =============================================================================
# TradingRuntimeState Tests
# =============================================================================

class TestTradingRuntimeState:
    """Test TradingRuntimeState dataclass."""

    def test_defaults(self):
        state = TradingRuntimeState()
        assert state.mode == GlobalTradingMode.MOCK
        assert state.allow_live_trades is False
        assert state.spectator_mode is True

    def test_snapshot(self):
        state = TradingRuntimeState()
        state.venues["alpaca"] = VenueConfig(venue_id="alpaca", label="Alpaca")
        
        snapshot = state.snapshot()
        
        assert snapshot["mode"] == "mock"
        assert "alpaca" in snapshot["venues"]


# =============================================================================
# TradingRuntimeConfig Tests
# =============================================================================

@pytest.fixture
def config(monkeypatch):
    """Create TradingRuntimeConfig with clean environment."""
    monkeypatch.delenv("MERID_TRADING_MODE", raising=False)
    monkeypatch.delenv("MERID_ALLOW_LIVE_TRADES", raising=False)
    monkeypatch.delenv("MERID_SPECTATOR_MODE", raising=False)
    monkeypatch.delenv("MERID_TRADING_ALLOWED_VENUES", raising=False)
    
    return TradingRuntimeConfig()


class TestTradingRuntimeConfigInit:
    """Test TradingRuntimeConfig initialization."""

    def test_defaults(self, config):
        snapshot = config.snapshot()
        assert snapshot["mode"] == "mock"

    def test_from_env(self, monkeypatch):
        monkeypatch.setenv("MERID_TRADING_MODE", "live")
        monkeypatch.setenv("MERID_ALLOW_LIVE_TRADES", "true")
        monkeypatch.setenv("MERID_SPECTATOR_MODE", "false")
        
        cfg = TradingRuntimeConfig()
        snapshot = cfg.snapshot()
        
        assert snapshot["mode"] == "live"
        assert snapshot["allow_live_trades"] is True

    def test_with_venues(self, monkeypatch):
        monkeypatch.setenv("MERID_TRADING_ALLOWED_VENUES", "alpaca,coinbase")
        monkeypatch.setenv("MERID_ALPACA_MODE", "paper")
        
        cfg = TradingRuntimeConfig()
        
        assert cfg.get_venue("alpaca") is not None


class TestUpdateGlobalMode:
    """Test update_global_mode method."""

    def test_update_mode(self, config):
        result = config.update_global_mode(mode="paper")
        assert result["mode"] == "paper"

    def test_update_allow_live(self, config):
        result = config.update_global_mode(allow_live_trades=True)
        assert result["allow_live_trades"] is True

    def test_update_spectator(self, config):
        result = config.update_global_mode(spectator_mode=False)
        assert result["spectator_mode"] is False

    def test_invalid_mode(self, config):
        with pytest.raises(ValueError, match="Invalid trading mode"):
            config.update_global_mode(mode="invalid_mode")


class TestUpsertVenue:
    """Test upsert_venue method."""

    def test_create_venue(self, config):
        result = config.upsert_venue("new_venue", {"label": "New Venue"})
        assert result["venue_id"] == "new_venue"

    def test_update_mode(self, config):
        config.upsert_venue("test", {"label": "Test"})
        result = config.upsert_venue("test", {"mode": "live"})
        assert result["mode"] == VenueMode.LIVE

    def test_update_limits(self, config):
        result = config.upsert_venue("test", {
            "label": "Test",
            "max_notional_usd": 10000,
            "daily_limit_usd": 50000
        })
        assert result["max_notional_usd"] == 10000

    def test_invalid_mode(self, config):
        with pytest.raises(ValueError, match="Invalid venue mode"):
            config.upsert_venue("test", {"mode": "invalid"})


class TestGetVenue:
    """Test get_venue method."""

    def test_existing_venue(self, config):
        config.upsert_venue("alpaca", {"label": "Alpaca"})
        venue = config.get_venue("alpaca")
        assert venue.venue_id == "alpaca"

    def test_missing_venue(self, config):
        venue = config.get_venue("nonexistent")
        assert venue is None


class TestUpsertTrader:
    """Test upsert_trader method."""

    def test_create_trader(self, config):
        result = config.upsert_trader("trader_001", {"mode": "paper"})
        assert result["mode"] == "paper"

    def test_update_spectator_only(self, config):
        config.upsert_trader("trader_002", {"mode": "live"})
        result = config.upsert_trader("trader_002", {"spectator_only": True})
        assert result["spectator_only"] is True

    def test_update_metadata(self, config):
        result = config.upsert_trader("trader_003", {"metadata": {"strategy": "momentum"}})
        assert result["metadata"]["strategy"] == "momentum"


class TestGetTrader:
    """Test get_trader method."""

    def test_existing_trader(self, config):
        config.upsert_trader("trader_001", {"mode": "paper"})
        trader = config.get_trader("trader_001")
        assert trader["mode"] == "paper"

    def test_missing_trader(self, config):
        trader = config.get_trader("nonexistent")
        assert trader is None


# =============================================================================
# Helper Function Tests
# =============================================================================

class TestEnvBool:
    """Test _env_bool function."""

    def test_default_true(self, monkeypatch):
        monkeypatch.delenv("TEST_VAR", raising=False)
        assert _env_bool("TEST_VAR", True) is True

    def test_default_false(self, monkeypatch):
        monkeypatch.delenv("TEST_VAR", raising=False)
        assert _env_bool("TEST_VAR", False) is False

    def test_true_values(self, monkeypatch):
        for val in ["1", "true", "yes", "on"]:
            monkeypatch.setenv("TEST_VAR", val)
            assert _env_bool("TEST_VAR", False) is True

    def test_false_values(self, monkeypatch):
        monkeypatch.setenv("TEST_VAR", "0")
        assert _env_bool("TEST_VAR", True) is False


# =============================================================================
# Singleton Tests
# =============================================================================

class TestGetRuntimeConfig:
    """Test get_runtime_config singleton."""

    def test_returns_config(self, monkeypatch):
        import trading.config.runtime_config as module
        module._runtime_config = None
        
        monkeypatch.delenv("MERID_TRADING_MODE", raising=False)
        
        cfg = get_runtime_config()
        assert isinstance(cfg, TradingRuntimeConfig)
