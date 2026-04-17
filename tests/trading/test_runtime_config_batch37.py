"""Tests for trading config runtime_config module - Batch 37 Coverage."""
import pytest
from unittest.mock import patch, MagicMock
import os
import time
import threading

from trading.config.runtime_config import (
    GlobalTradingMode,
    VenueMode,
    VenueConfig,
    TradingRuntimeState,
    TradingRuntimeConfig,
    get_runtime_config,
    _env_bool,
)


class TestGlobalTradingMode:
    """Tests for GlobalTradingMode enum."""

    def test_mode_values(self):
        # ZT2: OFFLINE, SIM, HYBRID are now aliased to MOCK
        assert GlobalTradingMode.OFFLINE == GlobalTradingMode.MOCK
        assert GlobalTradingMode.SIM == GlobalTradingMode.MOCK
        assert GlobalTradingMode.PAPER == "paper"
        assert GlobalTradingMode.LIVE == "live"
        assert GlobalTradingMode.HYBRID == GlobalTradingMode.MOCK


class TestVenueMode:
    """Tests for VenueMode enum."""

    def test_mode_values(self):
        assert VenueMode.DISABLED == "disabled"
        assert VenueMode.SIM == "sim"
        assert VenueMode.PAPER == "paper"
        assert VenueMode.LIVE == "live"


class TestVenueConfig:
    """Tests for VenueConfig dataclass."""

    @pytest.fixture
    def sample_config(self):
        return VenueConfig(
            venue_id="binance",
            label="Binance Exchange",
            mode=VenueMode.PAPER,
            enabled=True,
            max_notional_usd=10000.0,
            daily_limit_usd=50000.0,
            credentials_present=True,
        )

    def test_config_creation(self, sample_config):
        assert sample_config.venue_id == "binance"
        assert sample_config.label == "Binance Exchange"
        assert sample_config.mode == VenueMode.PAPER
        assert sample_config.enabled is True
        assert sample_config.max_notional_usd == 10000.0
        assert sample_config.daily_limit_usd == 50000.0
        assert sample_config.credentials_present is True

    def test_config_defaults(self):
        config = VenueConfig(venue_id="test", label="test")
        assert config.label == "test"
        assert config.mode == VenueMode.DISABLED
        assert config.enabled is False
        assert config.max_notional_usd == 0.0
        assert config.daily_limit_usd == 0.0
        assert config.credentials_present is False

    def test_to_dict(self, sample_config):
        d = sample_config.to_dict()
        assert d["venue_id"] == "binance"
        assert d["label"] == "Binance Exchange"
        assert d["mode"] == VenueMode.PAPER


class TestTradingRuntimeState:
    """Tests for TradingRuntimeState dataclass."""

    def test_state_defaults(self):
        state = TradingRuntimeState()
        assert state.mode == GlobalTradingMode.MOCK
        assert state.allow_live_trades is False
        assert state.spectator_mode is True
        assert state.venues == {}
        assert state.traders == {}

    def test_snapshot(self):
        state = TradingRuntimeState()
        state.venues["binance"] = VenueConfig(venue_id="binance", label="Binance")
        
        snapshot = state.snapshot()
        assert snapshot["mode"] == "mock"
        assert snapshot["allow_live_trades"] is False
        assert snapshot["spectator_mode"] is True
        assert "venues" in snapshot
        assert "binance" in snapshot["venues"]


class TestTradingRuntimeConfig:
    """Tests for TradingRuntimeConfig class."""

    @pytest.fixture
    def config(self):
        with patch.dict(os.environ, {}, clear=True):
            return TradingRuntimeConfig()

    def test_initialization_default(self, config):
        assert config._state.mode == GlobalTradingMode.MOCK
        assert config._state.allow_live_trades is False
        assert config._state.spectator_mode is True

    def test_initialization_with_env(self):
        env_vars = {
            "MERID_TRADING_MODE": "paper",
            "MERID_ALLOW_LIVE_TRADES": "false",
            "MERID_SPECTATOR_MODE": "true",
            "MERID_TRADING_ALLOWED_VENUES": "binance,coinbase",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            cfg = TradingRuntimeConfig()
            assert cfg._state.mode == GlobalTradingMode.PAPER
            assert "binance" in cfg._state.venues
            assert "coinbase" in cfg._state.venues

    def test_snapshot(self, config):
        snapshot = config.snapshot()
        assert "mode" in snapshot
        assert "venues" in snapshot

    def test_update_global_mode(self, config):
        result = config.update_global_mode(mode="paper", allow_live_trades=True, spectator_mode=False)
        assert config._state.mode == GlobalTradingMode.PAPER
        assert config._state.allow_live_trades is True
        assert config._state.spectator_mode is False
        assert result["mode"] == "paper"

    def test_update_global_mode_invalid_mode(self, config):
        with pytest.raises(ValueError, match="Invalid trading mode"):
            config.update_global_mode(mode="invalid_mode")

    def test_upsert_venue_new(self, config):
        result = config.upsert_venue("kraken", {
            "label": "Kraken Exchange",
            "mode": "paper",
            "max_notional_usd": 5000.0,
        })
        assert "kraken" in config._state.venues
        assert config._state.venues["kraken"].label == "Kraken Exchange"
        assert config._state.venues["kraken"].mode == VenueMode.PAPER

    def test_upsert_venue_update(self, config):
        config.upsert_venue("kraken", {"label": "Kraken", "mode": "paper"})
        result = config.upsert_venue("kraken", {"label": "Kraken Pro", "mode": "live"})
        assert config._state.venues["kraken"].label == "Kraken Pro"
        assert config._state.venues["kraken"].mode == VenueMode.LIVE

    def test_upsert_venue_invalid_mode(self, config):
        with pytest.raises(ValueError, match="Invalid venue mode"):
            config.upsert_venue("kraken", {"mode": "invalid"})

    def test_get_venue_exists(self, config):
        config.upsert_venue("kraken", {"label": "Kraken", "mode": "paper"})
        venue = config.get_venue("kraken")
        assert venue is not None
        assert venue.venue_id == "kraken"

    def test_get_venue_not_exists(self, config):
        venue = config.get_venue("nonexistent")
        assert venue is None

    def test_upsert_trader_new(self, config):
        result = config.upsert_trader("trader_1", {"mode": "paper", "spectator_only": True})
        assert "trader_1" in config._state.traders
        assert config._state.traders["trader_1"]["mode"] == "paper"

    def test_upsert_trader_update(self, config):
        config.upsert_trader("trader_1", {"mode": "paper"})
        result = config.upsert_trader("trader_1", {"mode": "live", "spectator_only": False})
        assert config._state.traders["trader_1"]["mode"] == "live"
        assert config._state.traders["trader_1"]["spectator_only"] is False

    def test_upsert_trader_with_metadata(self, config):
        config.upsert_trader("trader_1", {"metadata": {"strategy": "arbitrage"}})
        assert config._state.traders["trader_1"]["metadata"]["strategy"] == "arbitrage"

    def test_get_trader_exists(self, config):
        config.upsert_trader("trader_1", {"mode": "paper"})
        trader = config.get_trader("trader_1")
        assert trader is not None
        assert trader["mode"] == "paper"

    def test_get_trader_not_exists(self, config):
        trader = config.get_trader("nonexistent")
        assert trader is None

    def test_thread_safety(self, config):
        """Test that concurrent updates are thread-safe."""
        errors = []
        
        def updater():
            try:
                for i in range(10):
                    config.update_global_mode(spectator_mode=i % 2 == 0)
                    config.upsert_venue(f"venue_{i}", {"mode": "paper"})
            except Exception as e:
                errors.append(e)
        
        threads = [threading.Thread(target=updater) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        assert len(errors) == 0, f"Thread safety errors: {errors}"


class TestEnvBool:
    """Tests for _env_bool helper function."""

    def test_env_bool_true_values(self):
        for val in ["1", "true", "True", "TRUE", "yes", "YES", "on", "ON"]:
            with patch.dict(os.environ, {"TEST_VAR": val}):
                assert _env_bool("TEST_VAR", False) is True

    def test_env_bool_false_values(self):
        for val in ["0", "false", "False", "FALSE", "no", "NO", "off", "OFF", ""]:
            with patch.dict(os.environ, {"TEST_VAR": val}):
                assert _env_bool("TEST_VAR", True) is False

    def test_env_bool_default(self):
        with patch.dict(os.environ, {}, clear=True):
            assert _env_bool("NONEXISTENT_VAR", True) is True
            assert _env_bool("NONEXISTENT_VAR", False) is False


class TestSingleton:
    """Tests for singleton pattern."""

    def test_get_runtime_config(self):
        # Reset singleton
        import trading.config.runtime_config as rt_module
        rt_module._runtime_config = None

        with patch.dict(os.environ, {}, clear=True):
            cfg1 = get_runtime_config()
            cfg2 = get_runtime_config()
            assert cfg1 is cfg2
