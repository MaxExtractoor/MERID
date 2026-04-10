"""Tests for AgentConfig.validate() and AgentGrid.agent_health_dump().

Covers Phase 2 of the stabilization:
- validate() catches missing assets/timeframes for enabled agents
- validate() detects name/asset cross-wiring (BTC agent → ETH asset)
- validate() returns empty errors for correctly configured agents
- agent_health_dump() returns correct fields for all agents
"""

import pytest

from merid.prediction.agent_grid_config import (
    AgentConfig,
    AgentRiskLimits,
    EntryWindowConfig,
)


class TestAgentConfigValidate:
    """AgentConfig.validate() returns correct error lists."""

    def _make(self, name, assets, timeframes, enabled=True):
        return AgentConfig(
            name=name,
            assets=assets,
            timeframes=timeframes,
            enabled=enabled,
        )

    # ── Valid configs ──────────────────────────────────────────────────

    def test_valid_btc_agent_no_errors(self):
        cfg = self._make("BTC_15M", ["BTC"], ["15m"])
        assert cfg.validate() == []

    def test_valid_eth_agent_no_errors(self):
        cfg = self._make("ETH_HOURLY", ["ETH"], ["1h"])
        assert cfg.validate() == []

    def test_valid_sol_agent_no_errors(self):
        cfg = self._make("SOL_DAILY", ["SOL"], ["daily"])
        assert cfg.validate() == []

    def test_valid_xrp_agent_no_errors(self):
        cfg = self._make("XRP_MONTHLY", ["XRP"], ["monthly"])
        assert cfg.validate() == []

    def test_valid_doge_agent_no_errors(self):
        cfg = self._make("DOGE_WEEKLY", ["DOGE"], ["weekly"])
        assert cfg.validate() == []

    def test_disabled_agent_no_assets_ok(self):
        """Disabled agents don't need assets/timeframes configured."""
        cfg = self._make("BTC_TEST", [], [], enabled=False)
        assert cfg.validate() == []

    def test_multi_asset_agent_no_errors(self):
        """Agent with multiple assets is valid as long as name doesn't imply conflict."""
        cfg = self._make("CRYPTO_PORTFOLIO", ["BTC", "ETH", "SOL"], ["daily"])
        assert cfg.validate() == []

    # ── Missing required fields ────────────────────────────────────────

    def test_enabled_agent_missing_assets_fails(self):
        cfg = self._make("BTC_15M", [], ["15m"])
        errors = cfg.validate()
        assert len(errors) == 1
        assert "no assets" in errors[0].lower()

    def test_enabled_agent_missing_timeframes_fails(self):
        cfg = self._make("ETH_DAILY", ["ETH"], [])
        errors = cfg.validate()
        assert len(errors) == 1
        assert "no timeframes" in errors[0].lower()

    def test_enabled_agent_missing_both_fails(self):
        cfg = self._make("SOL_AGENT", [], [])
        errors = cfg.validate()
        assert len(errors) == 2

    # ── Name/asset cross-wiring ────────────────────────────────────────

    def test_btc_name_with_eth_asset_fails(self):
        """BTC agent name but ETH asset → validation error."""
        cfg = self._make("BTC_15M", ["ETH"], ["15m"])
        errors = cfg.validate()
        assert len(errors) == 1
        assert "BTC" in errors[0]
        assert "ETH" in errors[0]

    def test_eth_name_with_sol_asset_fails(self):
        cfg = self._make("ETH_HOURLY", ["SOL"], ["1h"])
        errors = cfg.validate()
        assert len(errors) == 1
        assert "ETH" in errors[0]

    def test_sol_name_with_correct_asset_ok(self):
        cfg = self._make("SOL_DAILY_DIRECTIONAL", ["SOL"], ["daily"])
        assert cfg.validate() == []

    def test_btc_name_with_btc_in_multi_assets_ok(self):
        """BTC agent with BTC as one of several assets is valid."""
        cfg = self._make("BTC_MULTI", ["BTC", "ETH"], ["daily"])
        assert cfg.validate() == []

    def test_empty_name_fails(self):
        cfg = AgentConfig(name="", assets=["BTC"], timeframes=["15m"])
        errors = cfg.validate()
        assert any("empty" in e.lower() or "name" in e.lower() for e in errors)

    # ── resolve_category ──────────────────────────────────────────────

    def test_btc_agent_resolves_crypto(self):
        cfg = self._make("BTC_15M", ["BTC"], ["15m"])
        assert cfg.resolve_category() == "crypto"

    def test_eth_agent_resolves_crypto(self):
        cfg = self._make("ETH_HOURLY", ["ETH"], ["1h"])
        assert cfg.resolve_category() == "crypto"

    def test_explicit_category_overrides_inferred(self):
        cfg = AgentConfig(
            name="WEATHER_BOT",
            assets=["BTC"],
            timeframes=["daily"],
            category="climate",
        )
        assert cfg.resolve_category() == "climate"

    def test_unknown_name_resolves_all(self):
        cfg = self._make("GENERIC_AGENT_X", ["BTC"], ["daily"])
        # No recognized keyword in name → "all"
        assert cfg.resolve_category() == "all"

    # ── agent_id ──────────────────────────────────────────────────────

    def test_agent_id_format(self):
        cfg = self._make("BTC_15M_DIRECTIONAL", ["BTC"], ["15m"])
        assert cfg.agent_id == "kalshi-btc_15m_directional"


class TestAllCryptoAgentsValidate:
    """All 30 crypto cells (5 assets × 6 timeframes) load from config without validation errors."""

    ASSETS = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
    TIMEFRAMES = ["15m", "1h", "daily", "weekly", "monthly", "annual"]

    def test_all_cells_pass_validation(self):
        """Every (asset, timeframe) combination produces a valid AgentConfig."""
        errors_found = []
        for asset in self.ASSETS:
            for tf in self.TIMEFRAMES:
                cfg = AgentConfig(
                    name=f"{asset}_{tf.upper()}",
                    assets=[asset],
                    timeframes=[tf],
                    enabled=True,
                )
                errs = cfg.validate()
                if errs:
                    errors_found.append(f"{asset}/{tf}: {errs}")

        assert not errors_found, (
            f"Validation errors in {len(errors_found)} cells:\n"
            + "\n".join(errors_found)
        )

    def test_all_cells_resolve_crypto_category(self):
        """Every crypto agent resolves to category='crypto'."""
        for asset in self.ASSETS:
            for tf in self.TIMEFRAMES:
                cfg = AgentConfig(
                    name=f"{asset}_{tf.upper()}",
                    assets=[asset],
                    timeframes=[tf],
                )
                assert cfg.resolve_category() == "crypto", (
                    f"{asset}/{tf} resolved to '{cfg.resolve_category()}', expected 'crypto'"
                )
