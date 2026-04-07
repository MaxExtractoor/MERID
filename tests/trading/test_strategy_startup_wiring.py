"""Tests for strategy configuration startup wiring.

Verifies that:
1. All strategy YAML files map cleanly to Python config types (no unknown keys,
   correct types, sane defaults).
2. ``validate_all_strategy_configs()`` passes against the real YAML files.
3. ``STRATEGY_REGISTRY`` contains the expected profile names.
4. ``build_strategy_from_profile()`` returns a live, callable strategy instance.
5. ``load_strategy_catalog()`` returns the enabled_profiles list from
   ``config/strategy_catalog.yaml``.
6. Every profile listed in ``enabled_profiles`` is registered in the registry.
7. ``AgentGrid`` can be constructed (mocked) with the strategy wiring active,
   and exposes ``loaded_profiles`` and ``active_strategies`` attributes that
   reflect the catalog.

YAML ↔ Python mapping being validated
──────────────────────────────────────
  config/strategies/kalshi_crypto_15m_conservative.yaml
    → Conservative15mConfig (merid.strategies.kalshi_crypto_15m_conservative)
    → Conservative15mStrategy (via registry "kalshi_crypto_15m_conservative")

  config/strategy_catalog.yaml
    → enabled_profiles: [kalshi_crypto_15m_conservative]
    → per-cell kelly_fraction / min_edge_bps / max_risk_per_trade_pct
"""

from __future__ import annotations

import dataclasses
import os
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import yaml

# ── Paths ──────────────────────────────────────────────────────────────────

_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
_CONSERVATIVE_YAML = os.path.join(
    _REPO_ROOT, "config", "strategies", "kalshi_crypto_15m_conservative.yaml"
)
_CATALOG_YAML = os.path.join(_REPO_ROOT, "config", "strategy_catalog.yaml")
_AGENT_GRID_YAML = os.path.join(_REPO_ROOT, "config", "kalshi_agent_grid.yaml")


# ── 1. YAML loading fixtures ───────────────────────────────────────────────

@pytest.fixture(scope="module")
def conservative_yaml_raw() -> dict:
    with open(_CONSERVATIVE_YAML) as f:
        return yaml.safe_load(f) or {}


@pytest.fixture(scope="module")
def catalog_yaml_raw() -> dict:
    with open(_CATALOG_YAML) as f:
        return yaml.safe_load(f) or {}


@pytest.fixture(scope="module")
def agent_grid_yaml_raw() -> dict:
    with open(_AGENT_GRID_YAML) as f:
        return yaml.safe_load(f) or {}


# ── 2. Conservative 15m YAML → Conservative15mConfig ──────────────────────

class TestConservative15mYamlMapping:
    """YAML keys map cleanly to Conservative15mConfig fields."""

    # Metadata keys in the YAML that are NOT fields of Conservative15mConfig.
    METADATA_KEYS = frozenset(
        {"profile", "version", "assets", "primary_timeframe", "context_timeframes"}
    )

    def test_yaml_file_exists(self) -> None:
        assert os.path.isfile(_CONSERVATIVE_YAML), (
            f"Expected strategy YAML at {_CONSERVATIVE_YAML}"
        )

    def test_profile_key_correct(self, conservative_yaml_raw: dict) -> None:
        assert conservative_yaml_raw.get("profile") == "kalshi_crypto_15m_conservative"

    def test_no_unknown_config_keys(self, conservative_yaml_raw: dict) -> None:
        """Every non-metadata YAML key must be a field of Conservative15mConfig."""
        from merid.strategies.kalshi_crypto_15m_conservative import Conservative15mConfig
        known_fields = {f.name for f in dataclasses.fields(Conservative15mConfig)}
        config_keys = {
            k for k in conservative_yaml_raw if k not in self.METADATA_KEYS
        }
        unknown = config_keys - known_fields
        assert not unknown, (
            f"YAML contains unknown keys not in Conservative15mConfig: {sorted(unknown)}"
        )

    def test_all_config_fields_have_defaults(self) -> None:
        """Conservative15mConfig must have defaults for every field (graceful degradation)."""
        from merid.strategies.kalshi_crypto_15m_conservative import Conservative15mConfig
        instance = Conservative15mConfig()
        for f in dataclasses.fields(Conservative15mConfig):
            assert hasattr(instance, f.name), f"Field {f.name!r} has no default"

    def test_yaml_types_match_config(self, conservative_yaml_raw: dict) -> None:
        """Critical numeric and bool fields have the expected Python types."""
        raw = conservative_yaml_raw
        numeric_keys = [
            "min_p", "min_p_satellite", "kelly_fraction", "max_risk_per_trade_pct",
            "htf_alignment_min", "htf_contradiction_threshold", "rate_tighten_delta",
            "drawdown_warning_pct", "drawdown_pause_pct", "drawdown_min_p_delta",
            "drawdown_kelly_scale", "min_contract_volume", "min_contract_oi",
            "max_spread_cents",
        ]
        int_keys = [
            "min_edge_bps", "soft_target_trades_per_hour",
            "global_max_trades_per_hour", "per_asset_max_per_15m",
        ]
        for key in numeric_keys:
            if key in raw:
                assert isinstance(raw[key], (int, float)), (
                    f"YAML key '{key}' expected numeric, got {type(raw[key])}"
                )
        for key in int_keys:
            if key in raw:
                assert isinstance(raw[key], (int, float)), (
                    f"YAML key '{key}' expected numeric, got {type(raw[key])}"
                )
        if "enabled" in raw:
            assert isinstance(raw["enabled"], bool), (
                f"YAML key 'enabled' expected bool, got {type(raw['enabled'])}"
            )

    def test_yaml_values_are_sane(self, conservative_yaml_raw: dict) -> None:
        """Key probability and Kelly values are within sane operational ranges."""
        raw = conservative_yaml_raw
        for prob_key in ("min_p", "min_p_satellite"):
            if prob_key in raw:
                v = float(raw[prob_key])
                assert 0.5 <= v < 1.0, (
                    f"'{prob_key}' = {v} outside expected range [0.5, 1.0)"
                )
        if "kelly_fraction" in raw:
            kf = float(raw["kelly_fraction"])
            assert 0 < kf <= 0.5, f"'kelly_fraction' = {kf} outside (0, 0.5]"
        if "max_risk_per_trade_pct" in raw:
            mr = float(raw["max_risk_per_trade_pct"])
            assert 0 < mr <= 100, f"'max_risk_per_trade_pct' = {mr} outside (0, 100]"

    def test_yaml_loads_into_config_without_error(self) -> None:
        """_load_config_from_yaml must succeed and return correct values."""
        from merid.strategies.kalshi_crypto_15m_conservative import _load_config_from_yaml
        cfg = _load_config_from_yaml(_CONSERVATIVE_YAML)
        assert cfg.min_p == 0.64
        assert cfg.min_p_satellite == 0.66
        assert cfg.kelly_fraction == 0.125
        assert cfg.enabled is True
        assert cfg.min_edge_bps == 50
        assert cfg.soft_target_trades_per_hour == 12
        assert cfg.global_max_trades_per_hour == 30


# ── 3. validate_all_strategy_configs() ────────────────────────────────────

class TestValidateAllStrategyConfigs:
    """Smoke-tests the public validation entry point against real YAML files."""

    def test_passes_with_real_yamls(self) -> None:
        """validate_all_strategy_configs() must not raise on the current YAML files."""
        from merid.trading.strategy_registry import validate_all_strategy_configs
        validate_all_strategy_configs()  # raises StrategyConfigError if bad

    def test_raises_on_unknown_yaml_key(self, tmp_path: Any) -> None:
        """Injecting an unknown key into the YAML triggers StrategyConfigError."""
        with open(_CONSERVATIVE_YAML) as f:
            raw = yaml.safe_load(f) or {}
        raw["totally_unknown_key_xyz"] = "bad"

        bad_yaml = tmp_path / "bad_conservative.yaml"
        with open(bad_yaml, "w") as f:
            yaml.dump(raw, f)

        from merid.trading.strategy_registry import StrategyConfigError, validate_all_strategy_configs
        with pytest.raises(StrategyConfigError, match="unknown config keys"):
            validate_all_strategy_configs(conservative_yaml_path=str(bad_yaml))

    def test_raises_on_wrong_profile_name(self, tmp_path: Any) -> None:
        """Wrong profile value in YAML triggers StrategyConfigError."""
        with open(_CONSERVATIVE_YAML) as f:
            raw = yaml.safe_load(f) or {}
        raw["profile"] = "wrong_profile_name"

        bad_yaml = tmp_path / "bad_profile.yaml"
        with open(bad_yaml, "w") as f:
            yaml.dump(raw, f)

        from merid.trading.strategy_registry import StrategyConfigError, validate_all_strategy_configs
        with pytest.raises(StrategyConfigError, match="profile="):
            validate_all_strategy_configs(conservative_yaml_path=str(bad_yaml))

    def test_raises_on_unregistered_enabled_profile(self, tmp_path: Any) -> None:
        """An enabled_profiles entry with no registry match triggers StrategyConfigError."""
        with open(_CATALOG_YAML) as f:
            raw_catalog = yaml.safe_load(f) or {}

        # Inject an unregistered profile
        raw_catalog.setdefault("trading", {}).setdefault("strategies", {})[
            "enabled_profiles"
        ] = ["not_a_real_strategy_xyz"]

        bad_catalog = tmp_path / "bad_catalog.yaml"
        with open(bad_catalog, "w") as f:
            yaml.dump(raw_catalog, f)

        from merid.trading.strategy_registry import StrategyConfigError, validate_all_strategy_configs
        with pytest.raises(StrategyConfigError, match="not_a_real_strategy_xyz"):
            validate_all_strategy_configs(catalog_path=str(bad_catalog))


# ── 4. Strategy Registry ──────────────────────────────────────────────────

class TestStrategyRegistry:
    """STRATEGY_REGISTRY contains the expected built-in profiles."""

    def test_conservative_15m_is_registered(self) -> None:
        from merid.trading.strategy_registry import STRATEGY_REGISTRY
        assert "kalshi_crypto_15m_conservative" in STRATEGY_REGISTRY

    def test_register_strategy_decorator(self) -> None:
        """@register_strategy adds a factory to STRATEGY_REGISTRY."""
        from merid.trading.strategy_registry import STRATEGY_REGISTRY, register_strategy

        @register_strategy("_test_profile_xyz_unique")
        def _factory():
            return object()

        assert "_test_profile_xyz_unique" in STRATEGY_REGISTRY
        # Cleanup
        del STRATEGY_REGISTRY["_test_profile_xyz_unique"]

    def test_build_strategy_from_profile_returns_instance(self) -> None:
        """build_strategy_from_profile returns a callable strategy instance."""
        from merid.trading.strategy_registry import build_strategy_from_profile
        instance = build_strategy_from_profile("kalshi_crypto_15m_conservative")
        assert instance is not None
        assert callable(getattr(instance, "estimate", None)), (
            "strategy instance must have a callable estimate() method"
        )

    def test_build_unknown_profile_raises_key_error(self) -> None:
        from merid.trading.strategy_registry import build_strategy_from_profile
        with pytest.raises(KeyError, match="not registered"):
            build_strategy_from_profile("this_profile_does_not_exist")


# ── 5. Catalog loader ─────────────────────────────────────────────────────

class TestLoadStrategyCatalog:
    """load_strategy_catalog() correctly extracts enabled_profiles from YAML."""

    def test_returns_enabled_profiles_list(self) -> None:
        from merid.trading.strategy_registry import load_strategy_catalog
        catalog = load_strategy_catalog()
        assert "enabled_profiles" in catalog
        assert isinstance(catalog["enabled_profiles"], list)

    def test_conservative_15m_in_enabled_profiles(self) -> None:
        from merid.trading.strategy_registry import load_strategy_catalog
        catalog = load_strategy_catalog()
        assert "kalshi_crypto_15m_conservative" in catalog["enabled_profiles"]

    def test_assets_dict_present(self) -> None:
        from merid.trading.strategy_registry import load_strategy_catalog
        catalog = load_strategy_catalog()
        assert "assets" in catalog
        assert isinstance(catalog["assets"], dict)
        for asset in ("BTC", "ETH", "SOL", "XRP", "DOGE"):
            assert asset in catalog["assets"], f"Asset {asset} missing from catalog"

    def test_all_assets_have_all_six_timeframes(self) -> None:
        from merid.trading.strategy_registry import load_strategy_catalog
        catalog = load_strategy_catalog()
        expected_timeframes = {"15m", "1h", "daily", "weekly", "monthly", "annual"}
        for asset, cells in catalog["assets"].items():
            for tf in expected_timeframes:
                assert tf in cells, (
                    f"Asset {asset} missing timeframe {tf!r} in strategy_catalog.yaml"
                )

    def test_enabled_profiles_all_registered(self) -> None:
        """Every profile in enabled_profiles has a registry entry."""
        from merid.trading.strategy_registry import STRATEGY_REGISTRY, load_strategy_catalog
        catalog = load_strategy_catalog()
        for profile_name in catalog["enabled_profiles"]:
            assert profile_name in STRATEGY_REGISTRY, (
                f"Enabled profile '{profile_name}' has no entry in STRATEGY_REGISTRY"
            )

    def test_falls_back_on_missing_file(self, tmp_path: Any) -> None:
        """Missing catalog file returns safe defaults."""
        from merid.trading.strategy_registry import load_strategy_catalog
        result = load_strategy_catalog(str(tmp_path / "nonexistent.yaml"))
        assert result["enabled_profiles"] == []
        assert result["assets"] == {}


# ── 6. StrategyGrid has Conservative15mStrategy in 15m slot ──────────────

class TestStrategyGridWiring:
    """StrategyGrid correctly contains Conservative15mStrategy for 15m cells."""

    def test_15m_strategy_list_contains_conservative(self) -> None:
        from merid.event_venues.kalshi.strategy_grid import StrategyGrid
        from merid.strategies.kalshi_crypto_15m_conservative import Conservative15mStrategy
        grid = StrategyGrid()
        entry = grid.get("BTC", "15m")
        assert entry is not None
        strategy_types = [type(s) for s in entry.strategies]
        assert Conservative15mStrategy in strategy_types, (
            f"Conservative15mStrategy not in BTC/15m strategies: {strategy_types}"
        )

    def test_conservative_is_first_in_15m(self) -> None:
        """Conservative15mStrategy is the first (highest-priority) 15m strategy."""
        from merid.event_venues.kalshi.strategy_grid import StrategyGrid
        from merid.strategies.kalshi_crypto_15m_conservative import Conservative15mStrategy
        grid = StrategyGrid()
        for asset in ("BTC", "ETH", "SOL", "XRP", "DOGE"):
            entry = grid.get(asset, "15m")
            assert entry is not None
            assert isinstance(entry.strategies[0], Conservative15mStrategy), (
                f"{asset}/15m: first strategy must be Conservative15mStrategy, "
                f"got {type(entry.strategies[0])}"
            )

    def test_all_30_cells_have_strategies(self) -> None:
        """All 30 (asset × timeframe) cells are populated."""
        from merid.event_venues.kalshi.strategy_grid import StrategyGrid
        grid = StrategyGrid()
        expected_assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        expected_tfs = ["15m", "1h", "daily", "weekly", "monthly", "annual"]
        for asset in expected_assets:
            for tf in expected_tfs:
                entry = grid.get(asset, tf)
                assert entry is not None and entry.strategies, (
                    f"No strategies found for {asset}/{tf}"
                )

    def test_conservative_strategy_is_callable(self) -> None:
        """Conservative15mStrategy.estimate() is callable (live and not broken)."""
        from merid.strategies.kalshi_crypto_15m_conservative import (
            Conservative15mStrategy,
            Conservative15mConfig,
        )
        strategy = Conservative15mStrategy()
        config = Conservative15mConfig(enabled=True)
        # Monkey-patch the module config to avoid singleton side-effects
        ctx = {
            "asset": "BTC",
            "timeframe": "15m",
            "volume": 200.0,
            "open_interest": 50.0,
            "spot_return_pct": 3.0,
            "orderbook_imbalance": 0.3,
            "multi_tf_alignment": 0.55,
        }
        # Import and patch the module singleton
        import merid.strategies.kalshi_crypto_15m_conservative as _mod
        original_config = _mod._CONFIG
        _mod._CONFIG = config
        try:
            result = strategy.estimate(
                agent_id="test-agent",
                ticker="KXBTC15M-TEST",
                market_prob=0.45,
                context=ctx,
            )
            # Result can be None or OpinionEstimate — both are valid; the point
            # is that no exception is raised.
            assert result is None or hasattr(result, "confidence"), (
                f"Unexpected return type: {type(result)}"
            )
        finally:
            _mod._CONFIG = original_config


# ── 7. AgentGrid startup wiring (mocked) ──────────────────────────────────

class TestAgentGridStrategyWiring:
    """AgentGrid exposes loaded_profiles and active_strategies after construction."""

    def _make_minimal_agent_grid_config(self) -> Any:
        """Return a minimal AgentGridConfig with no agents."""
        from merid.prediction.agent_grid_config import (
            AgentGridConfig,
            VenueConfig,
            SessionConfig,
            PortfolioRiskConfig,
            MonitoringConfig,
        )
        return AgentGridConfig(
            venue=VenueConfig(),
            session=SessionConfig(),
            agents=[],
            portfolio_risk=PortfolioRiskConfig(),
            monitoring=MonitoringConfig(),
        )

    def _grid_patches(self):
        """Context managers that mock all heavy external dependencies of AgentGrid."""
        return (
            patch("merid.prediction.kalshi_tools.register_kalshi_tools"),
            patch("merid.event_venues.kalshi.market_catalog.get_market_catalog"),
            patch("merid.prediction.portfolio_risk_agent.PortfolioRiskAgent"),
            patch("merid.prediction.social_broadcaster.get_social_broadcaster"),
            patch("merid.prediction.paper_session.get_paper_session"),
            patch("merid.event_venues.kalshi.sentiment.get_sentiment_service"),
            patch("merid.swarm.market_mood_bus.get_market_mood_bus"),
            patch("merid.publishing.kalshi_insight_pipeline.get_insight_pipeline"),
            patch("merid.publishing.kalshi_news_agent.KalshiNewsAgent"),
            patch("merid.prediction.alerts.get_alert_manager"),
        )

    def _build_grid(self) -> Any:
        """Construct an AgentGrid with heavy deps mocked out."""
        config = self._make_minimal_agent_grid_config()
        from contextlib import ExitStack
        from merid.prediction.agent_grid import AgentGrid
        stack = ExitStack()
        for cm in self._grid_patches():
            stack.enter_context(cm)
        with stack:
            grid = AgentGrid(config=config)
        return grid

    def test_loaded_profiles_reflects_catalog(self) -> None:
        """AgentGrid.loaded_profiles includes 'kalshi_crypto_15m_conservative'."""
        grid = self._build_grid()
        assert "kalshi_crypto_15m_conservative" in grid.loaded_profiles

    def test_active_strategies_contains_live_instance(self) -> None:
        """AgentGrid.active_strategies returns the live Conservative15mStrategy instance."""
        from merid.strategies.kalshi_crypto_15m_conservative import Conservative15mStrategy
        grid = self._build_grid()
        active = grid.active_strategies
        assert "kalshi_crypto_15m_conservative" in active
        assert isinstance(active["kalshi_crypto_15m_conservative"], Conservative15mStrategy)

    def test_strategy_instance_is_callable(self) -> None:
        """The live strategy instance has a callable estimate() method."""
        grid = self._build_grid()
        strategy = grid.active_strategies["kalshi_crypto_15m_conservative"]
        assert callable(getattr(strategy, "estimate", None)), (
            "Strategy must expose a callable estimate() method"
        )

    def test_grid_raises_on_bad_yaml(self, tmp_path: Any) -> None:
        """AgentGrid construction raises StrategyConfigError on bad strategy YAML."""
        from merid.trading.strategy_registry import StrategyConfigError

        config = self._make_minimal_agent_grid_config()

        from contextlib import ExitStack
        from merid.prediction.agent_grid import AgentGrid
        stack = ExitStack()
        for cm in self._grid_patches():
            stack.enter_context(cm)
        stack.enter_context(
            patch(
                "merid.trading.strategy_registry.validate_all_strategy_configs",
                side_effect=StrategyConfigError(
                    "injected: unknown config keys ['totally_unknown_key_xyz']"
                ),
            )
        )
        with stack:
            with pytest.raises(StrategyConfigError):
                AgentGrid(config=config)
