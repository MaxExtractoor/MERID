"""PM crypto vol bridge: minute-bucket feeds → band + size multiplier."""

from __future__ import annotations

import time

import pytest


@pytest.fixture(autouse=True)
def _clear_bridge():
    from merid.signals import crypto_pm_vol_bridge as br

    br._STACKS.clear()
    br._LAST_CTX.clear()
    br._LAST_MINUTE_BUCKET.clear()
    yield
    br._STACKS.clear()
    br._LAST_CTX.clear()
    br._LAST_MINUTE_BUCKET.clear()


def test_matrix_vol_thresholds_reclassify_band(monkeypatch):
    """Non-null matrix vol_low/high override stack defaults for band + vol_gate_ok."""
    from merid.prediction import crypto_threshold_matrix as ctm
    from merid.signals.crypto_pm_vol_bridge import feed_spot_and_get_context

    real = ctm.resolve_merged_row

    def _patched(**kwargs):
        r = dict(real(**kwargs))
        r["vol_low_threshold"] = 100.0
        r["vol_high_threshold"] = 120.0
        return r

    monkeypatch.setattr(ctm, "resolve_merged_row", _patched)
    t0 = 1_700_000_000.0
    ctx = None
    for i in range(55):
        ctx = feed_spot_and_get_context(
            "BTC",
            50000.0 + float(i) * 5.0,
            now=t0 + i * 60.0,
            timeframe="15m",
            archetype="directional",
        )
    assert ctx is not None
    assert ctx["vol_band"] == "low"
    assert ctx["vol_gate_ok"] is False


def test_feed_spot_builds_band_context():
    from merid.signals.crypto_pm_vol_bridge import feed_spot_and_get_context

    t0 = 1_700_000_000.0
    ctx = None
    for i in range(55):
        ctx = feed_spot_and_get_context("BTC", 50000.0 + float(i) * 5.0, now=t0 + i * 60.0)
    assert ctx is not None
    assert ctx["vol_band"] in ("low", "mid", "high")
    assert ctx["vol_size_mult"] > 0
    assert ctx["bars_available"] >= 5


def test_strategy_applies_vol_mult_to_mm_depth():
    from datetime import datetime, timezone
    from decimal import Decimal

    from merid.prediction.model import ContractState, ImpliedProbability, MarketSnapshot
    from merid.prediction.strategy import KalshiStrategy, StrategyConfig

    impl = ImpliedProbability(
        yes_prob=Decimal("0.5"),
        no_prob=Decimal("0.5"),
        yes_bid=Decimal("40"),
        yes_ask=Decimal("42"),
        spread_cents=Decimal("2"),
    )
    snap = MarketSnapshot(
        market_id="KXBTC15M-T",
        event_id="E",
        title="t",
        state=ContractState.TRADING,
        implied=impl,
        volume=Decimal("1000"),
        open_interest=Decimal("500"),
        time_to_expiry_hours=Decimal("10"),
        timestamp=datetime.now(timezone.utc),
        crypto_vol_size_mult=0.4,
    )
    cfg = StrategyConfig(min_depth_contracts=5)
    strat = KalshiStrategy(config=cfg, agent_name="CRYPTO_15M_MM")
    sig = strat.evaluate(snap, archetype="market_maker")
    assert sig.action.value == "quote"
    assert sig.contracts == 2  # round(5 * 0.4)
