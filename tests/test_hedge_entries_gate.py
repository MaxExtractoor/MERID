"""Hedge entry gate tests (2026-11-12).

Hedge entries (risk-increasing opposite-side buys) are disabled by default:
they bypass TradeDecision approval and window-plan reservation, and on 15m
binaries a same-market pair locks in spread+fees rather than reducing
variance.  Exits are unaffected.  Re-enable via entries_enabled /
MERID_HEDGE_ENTRIES_ENABLED only after shared producer accounting exists.
"""

import pytest


def _exposure_with_delta(asset="BTC", tf="15m", yes=10000, no=0):
    from merid.hedging.exposure import ExposureSnapshot

    snap = ExposureSnapshot()
    cell = snap.get_cell(asset, tf)
    cell.yes_notional_cents = yes
    cell.no_notional_cents = no
    cell.yes_contracts = yes // 50
    return snap


def _config(entries_enabled: bool):
    from merid.hedging.config import (
        AssetSliceConfig,
        HedgeConfig,
        TimeframeHedgeRule,
    )

    return HedgeConfig(
        enabled=True,
        entries_enabled=entries_enabled,
        asset_slices={a: AssetSliceConfig(slice_pct_of_bankroll=0.20)
                      for a in ("BTC", "ETH", "SOL", "XRP", "DOGE")},
        timeframes={"15m": TimeframeHedgeRule(
            max_net_exposure_pct_of_slice=10.0,
            target_hedge_ratio=0.5,
        )},
    )


class TestEntriesEnabledConfig:
    def test_yaml_default_is_disabled(self):
        from merid.hedging.config import load_hedge_config

        cfg = load_hedge_config()
        assert cfg.enabled is True
        assert cfg.entries_enabled is False

    def test_env_enables_entries(self, monkeypatch):
        from merid.hedging.config import load_hedge_config

        monkeypatch.setenv("MERID_HEDGE_ENTRIES_ENABLED", "1")
        assert load_hedge_config().entries_enabled is True

    def test_env_disables_entries_over_yaml(self, monkeypatch):
        from merid.hedging.config import load_hedge_config

        monkeypatch.setenv("MERID_HEDGE_ENTRIES_ENABLED", "0")
        # Even if a yaml set entries_enabled: true, explicit env wins.
        assert load_hedge_config().entries_enabled is False


class TestEngineEntriesGate:
    def test_entries_disabled_suppresses_orders(self):
        from merid.hedging.engine import CryptoHedgeEngine

        engine = CryptoHedgeEngine()
        snap = _exposure_with_delta()
        result = engine.compute_hedge_orders(
            snap, _config(entries_enabled=False), bankroll_cents=100000,
        )
        assert result.orders == []

    def test_entries_disabled_with_zero_exposure_still_empty(self):
        from merid.hedging.exposure import ExposureSnapshot
        from merid.hedging.engine import CryptoHedgeEngine

        engine = CryptoHedgeEngine()
        result = engine.compute_hedge_orders(
            ExposureSnapshot(), _config(entries_enabled=False),
            bankroll_cents=100000,
        )
        assert result.orders == []

    def test_entries_enabled_produces_orders(self):
        from merid.hedging.engine import CryptoHedgeEngine

        engine = CryptoHedgeEngine()
        snap = _exposure_with_delta()
        result = engine.compute_hedge_orders(
            snap, _config(entries_enabled=True), bankroll_cents=100000,
        )
        assert len(result.orders) >= 1
        assert all(o.action == "buy" for o in result.orders)

    def test_master_disabled_still_disabled(self):
        from merid.hedging.config import HedgeConfig
        from merid.hedging.engine import CryptoHedgeEngine

        engine = CryptoHedgeEngine()
        cfg = HedgeConfig(enabled=False, entries_enabled=True)
        result = engine.compute_hedge_orders(
            _exposure_with_delta(), cfg, bankroll_cents=100000,
        )
        assert result.orders == []
