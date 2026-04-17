"""Spot vs Kalshi strike — parsing, distance metrics, model scaling, anomaly flags."""

from __future__ import annotations

from decimal import Decimal

import pytest

from config.kalshi_crypto_series_meta import infer_asset_from_kalshi_market_ticker, infer_asset_timeframe_from_ticker
from merid.event_venues.kalshi.market_filter import SAMPLE_TICKER_STRIKES, parse_strike_from_ticker
from merid.prediction.model import (
    ContractState,
    ImpliedProbability,
    MarketSnapshot,
    PredictionMarketModel,
    spot_dist_prob_scale,
)
from merid.prediction.spot_strike_context import (
    distance_to_strike_pct,
    resolve_asset_for_snapshot,
    resolve_timeframe_for_snapshot,
)
from merid.prediction.strategy import KalshiStrategy, SignalAction
from merid.prediction.trading_agent import _classify_pm_no_action_reason


@pytest.mark.parametrize(
    "ticker,asset,tf",
    [
        ("KXBTC15M-26APR071200-00", "BTC", "15m"),
        ("KXETH-26APR071200-T3500", "ETH", "1h"),
        ("KXXRPD1-26DEC31-T2.50", "XRP", "daily"),
        ("KXDOGEY-27DEC31-T0.50", "DOGE", "annual"),
    ],
)
def test_infer_asset_and_timeframe_from_kalshi_tickers(ticker: str, asset: str, tf: str):
    assert infer_asset_from_kalshi_market_ticker(ticker) == asset
    prefix = ticker.split("-")[0].upper()
    a2, t2 = infer_asset_timeframe_from_ticker(prefix)
    assert a2 == asset
    assert t2 == tf


@pytest.mark.parametrize("ticker,expected", list(SAMPLE_TICKER_STRIKES.items()))
def test_parse_strike_from_ticker_samples(ticker: str, expected: float | None):
    assert parse_strike_from_ticker(ticker) == expected


def test_resolve_asset_multi_asset_agent_uses_ticker():
    assert resolve_asset_for_snapshot([], "KXSOL15M-26APR071200-00") == "SOL"
    assert resolve_timeframe_for_snapshot([], "KXSOL15M-26APR071200-00") == "15m"


def test_resolve_asset_prefers_ticker_over_config_first_asset():
    """Multi-asset agents list BTC first; per-market spot must follow Kalshi prefix."""
    assert resolve_asset_for_snapshot(["BTC", "ETH", "SOL"], "KXETH-26APR071200-T3500") == "ETH"
    assert resolve_asset_for_snapshot(["BTC"], "KXBTC-26APR071200-T77799") == "BTC"
    assert resolve_timeframe_for_snapshot(["1h", "15m"], "KXETH15M-26APR071215-T3450") == "15m"


def test_distance_to_strike_pct_and_anomaly():
    d = distance_to_strike_pct(Decimal("100"), 100.0)
    assert d is not None and float(d) == 0.0
    d2 = distance_to_strike_pct(Decimal("110"), 100.0)
    assert d2 is not None and abs(float(d2) - 0.1) < 1e-6


def test_compute_edge_moves_with_spot_relative_to_strike(monkeypatch):
    """Higher spot above strike → higher model YES prob → higher buy-yes edge vs fixed implied."""
    implied = ImpliedProbability(
        yes_prob=Decimal("0.50"),
        no_prob=Decimal("0.50"),
        yes_bid=Decimal("0.49"),
        yes_ask=Decimal("0.51"),
        spread_cents=Decimal("2"),
    )
    m = PredictionMarketModel()
    monkeypatch.setenv("MERID_PM_SPOT_DIST_PROB_SCALE", "10")

    e_near = m.compute_edge(
        "KXBTC-TEST",
        implied,
        side="yes",
        action="buy",
        asset="BTC",
        strike_price=100000.0,
        spot_override=Decimal("100500"),
    )
    e_far = m.compute_edge(
        "KXBTC-TEST",
        implied,
        side="yes",
        action="buy",
        asset="BTC",
        strike_price=100000.0,
        spot_override=Decimal("110000"),
    )
    assert float(e_far.model_prob) > float(e_near.model_prob)
    assert float(e_far.net_edge) > float(e_near.net_edge)


def test_spot_strike_veto_returns_no_action(monkeypatch):
    monkeypatch.setenv("MERID_PM_SPOT_STRIKE_VETO_TRADES", "true")
    monkeypatch.setenv("MERID_PM_SPOT_STRIKE_VETO_ABS_DIST_PCT", "0.05")
    strat = KalshiStrategy(agent_name="t")
    snap = MarketSnapshot(
        market_id="KXBTC-T1",
        event_id="e",
        title="t",
        state=ContractState.TRADING,
        implied=ImpliedProbability(yes_prob=Decimal("0.5"), no_prob=Decimal("0.5")),
        volume=Decimal("1"),
        open_interest=Decimal("1"),
        time_to_expiry_hours=Decimal("10"),
    )
    snap.spot_strike_veto = True
    snap.spot_strike_veto_reason = "test veto"
    snap.distance_to_strike_pct = Decimal("0.10")
    sig = strat.evaluate(snap, archetype="directional")
    assert sig.action == SignalAction.NO_ACTION
    assert "veto" in (sig.reason or "").lower() or "spot_strike" in (sig.reason or "").lower()


def test_spot_dist_prob_scale_from_env(monkeypatch):
    monkeypatch.setenv("MERID_PM_SPOT_DIST_PROB_SCALE", "7")
    assert spot_dist_prob_scale() == Decimal("7")


def test_max_spot_age_seconds_env(monkeypatch):
    from merid.prediction.model import max_spot_age_seconds

    monkeypatch.setenv("MERID_PM_MAX_SPOT_AGE_SECONDS", "45")
    assert max_spot_age_seconds() == 45


def test_pm_cycle_trace_classifies_spot_strike_veto():
    assert _classify_pm_no_action_reason("spot_strike_anomaly: |dist|=2.0 >= veto 1.5") == "spot_strike_veto"
    assert _classify_pm_no_action_reason("spot_strike_veto: test") == "spot_strike_veto"
    assert _classify_pm_no_action_reason("Edge 0.01 below mid threshold 0.04") == "edge_below_threshold"


@pytest.mark.parametrize(
    "ticker,asset,tf,strike_expected",
    [
        ("KXBTCY-27DEC31-T200000", "BTC", "annual", 200000.0),
        ("KXETH15M-26APR071215-T3450", "ETH", "15m", 3450.0),
        ("KXSOL-26APR0713-T120", "SOL", "1h", 120.0),
    ],
)
def test_ticker_matrix_asset_timeframe_strike(
    ticker: str, asset: str, tf: str, strike_expected: float,
):
    assert infer_asset_from_kalshi_market_ticker(ticker) == asset
    prefix = ticker.split("-")[0].upper()
    a2, t2 = infer_asset_timeframe_from_ticker(prefix)
    assert a2 == asset and t2 == tf
    ps = parse_strike_from_ticker(ticker)
    assert ps == strike_expected


def test_warn_threshold_does_not_set_veto_without_env(monkeypatch):
    from merid.prediction.spot_strike_context import evaluate_spot_strike_anomaly

    monkeypatch.delenv("MERID_PM_SPOT_STRIKE_VETO_TRADES", raising=False)
    w, v, _ = evaluate_spot_strike_anomaly(Decimal("0.90"))
    assert w is True
    assert v is False
