import asyncio
import importlib.util
import sys
import types
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

# Stub trading.trade_mode to avoid importing heavy trading package dependencies during unit tests
_dummy_trade_mode = types.ModuleType("trading.trade_mode")
class _TradeMode:  # noqa: N801 - simple stub for tests
    MOCK = "mock"
    PAPER = "paper"
    LIVE = "live"
_dummy_trade_mode.TradeMode = _TradeMode
_dummy_trade_mode.get_trade_mode = lambda: _TradeMode.PAPER
_dummy_trade_mode.set_trade_mode = lambda mode, reason="": _TradeMode.PAPER
sys.modules.setdefault("trading", types.ModuleType("trading"))
sys.modules["trading.trade_mode"] = _dummy_trade_mode
setattr(sys.modules["trading"], "trade_mode", _dummy_trade_mode)

from merid.prediction.agent_grid_config import AgentRiskLimits
from merid.prediction.model import ContractState, MarketSnapshot, PredictionMarketModel
from merid.prediction.position_adjuster import PositionAdjustmentEngine
from merid.prediction.strategy import (
    EdgeEstimate,
    KalshiStrategy,
    SignalAction,
    StrategyConfig,
)
from merid.resilience import OperationResult

BASE_MODULE_PATH = Path(__file__).resolve().parents[2] / "merid" / "event_venues" / "base.py"
_base_spec = importlib.util.spec_from_file_location("merid.event_venues.base", BASE_MODULE_PATH)
_base_mod = importlib.util.module_from_spec(_base_spec)
assert _base_spec and _base_spec.loader
_base_spec.loader.exec_module(_base_mod)  # type: ignore
EventMarket = _base_mod.EventMarket
EventOutcome = _base_mod.EventOutcome

CATALOG_PATH = Path(__file__).resolve().parents[2] / "merid" / "event_venues" / "kalshi" / "market_catalog.py"
_catalog_spec = importlib.util.spec_from_file_location("merid.event_venues.kalshi.market_catalog", CATALOG_PATH)
_catalog_mod = importlib.util.module_from_spec(_catalog_spec)
assert _catalog_spec and _catalog_spec.loader
_catalog_spec.loader.exec_module(_catalog_mod)  # type: ignore
KalshiMarketCatalog = _catalog_mod.KalshiMarketCatalog


class _FakeKalshiClient:
    def __init__(self, markets):
        self._markets = markets

    async def list_markets_result(self, *_args, **_kwargs):
        return OperationResult.ok(self._markets)


def _market(ticker: str, question: str, end_delta_minutes: int, series: str) -> EventMarket:
    outcomes = [
        EventOutcome(outcome_id="yes", outcome_name="Yes", price=Decimal("0.55")),
        EventOutcome(outcome_id="no", outcome_name="No", price=Decimal("0.45")),
    ]
    return EventMarket(
        market_id=ticker,
        venue="kalshi",
        question=question,
        description="",
        outcomes=outcomes,
        category="crypto",
        end_date=datetime.now(timezone.utc) + timedelta(minutes=end_delta_minutes),
        raw_data={"event_ticker": series, "series_ticker": series},
    )


def test_catalog_uses_full_market_list_and_detects_crypto_series():
    m15 = _market("KXBTC15M-26MAR241500-00", "BTC up or down in 15 minutes?", 10, "KXBTC15M")
    thresh = _market("KXBTC-26MAR2415-T77699.99", "BTC above 77699?", 120, "KXBTC")

    catalog = KalshiMarketCatalog(client=_FakeKalshiClient([m15, thresh]))
    asyncio.run(catalog.refresh())

    btc_markets = catalog.get_markets_by_asset("BTC")
    assert {m.market.market_id for m in btc_markets} == {m15.market_id, thresh.market_id}

    fifteen_min = catalog.get_markets_by_asset_timeframe("BTC", "15m")
    assert len(fifteen_min) == 1
    assert fifteen_min[0].market.market_id == m15.market_id

    summary = catalog.crypto_series_summary()
    assert summary["BTC"]["15m"]["count"] == 1
    assert m15.market_id in summary["BTC"]["15m"]["sample"]


def _edge(market_id: str, side: str, net_edge: str, model_prob: str, market_prob: str) -> EdgeEstimate:
    return EdgeEstimate(
        market_id=market_id,
        side=side,
        action="buy",
        market_prob=Decimal(market_prob),
        model_prob=Decimal(model_prob),
        raw_edge=Decimal("0.10"),
        fee_drag=Decimal("0.01"),
        slippage_est=Decimal("0.01"),
        net_edge=Decimal(net_edge),
        edge_type="speculative",
        confidence=Decimal("0.8"),
    )


def _snapshot(market_id: str, implied, edges, minutes_to_expiry: Decimal, strike_price=None, spot_price=None, timeframe="15m", market_type=None):
    return MarketSnapshot(
        market_id=market_id,
        event_id=market_id,
        title=market_id,
        state=ContractState.TRADING,
        implied=implied,
        volume=Decimal("5000"),
        open_interest=Decimal("500"),
        time_to_expiry_hours=minutes_to_expiry / Decimal("60"),
        close_time=datetime.now(timezone.utc) + timedelta(minutes=float(minutes_to_expiry)),
        category="crypto",
        asset="BTC",
        timeframe=timeframe,
        market_type=market_type,
        strike_price=Decimal(str(strike_price)) if strike_price is not None else None,
        spot_price=Decimal(str(spot_price)) if spot_price is not None else None,
        minutes_to_expiry=minutes_to_expiry,
        edges=edges,
        timestamp=datetime.now(timezone.utc),
    )


def test_position_engine_buy_more_and_sell_reduce():
    strategy = KalshiStrategy()
    # Make sizing deterministic for the test
    strategy._kelly_size_with_sentiment = lambda edge, phase, snapshot: 10  # type: ignore
    engine = PositionAdjustmentEngine(strategy, AgentRiskLimits(max_yes_position=50, max_no_position=50))

    implied = PredictionMarketModel().implied_probabilities(Decimal("45"), Decimal("55"), Decimal("45"), Decimal("55"))
    market_id = "KXBTC15M-TEST"

    opening_edge = _edge(market_id, "yes", "0.05", "0.60", "0.50")
    improved_edge = _edge(market_id, "yes", "0.08", "0.64", "0.50")
    engine.apply_fill(market_id, side="yes", action="buy", contracts=5, price_cents=55, edge=opening_edge)

    snapshot = _snapshot(market_id, implied, [improved_edge], Decimal("8"), timeframe="15m")
    signal = engine.evaluate(snapshot)
    assert signal is not None
    assert signal.action == SignalAction.BUY_YES
    assert signal.contracts == 5  # target 10 vs current 5

    # Now edge flips negative → should trigger sell/close
    bad_edge = _edge(market_id, "yes", "-0.01", "0.40", "0.55")
    snapshot.edges = [bad_edge]
    signal = engine.evaluate(snapshot)
    assert signal is not None
    assert signal.action == SignalAction.SELL_YES
    assert signal.contracts == 5


def test_entry_rules_time_and_catastrophic_yes_guard():
    strategy = KalshiStrategy(StrategyConfig())
    implied = PredictionMarketModel().implied_probabilities(Decimal("45"), Decimal("55"), Decimal("45"), Decimal("55"))

    # Too late for 15m entry
    late_edge = _edge("KXBTC15M-LATE", "yes", "0.05", "0.60", "0.50")
    late_snapshot = _snapshot(
        "KXBTC15M-LATE",
        implied,
        [late_edge],
        minutes_to_expiry=Decimal("1"),
        timeframe="15m",
    )
    late_signal = strategy.evaluate(late_snapshot)
    assert late_signal.action == SignalAction.NO_ACTION

    # Catastrophic YES on deep OTM strike should be blocked
    cat_edge_yes = _edge("KXBTC-OTM", "yes", "0.06", "0.65", "0.55")
    cat_snapshot = _snapshot(
        "KXBTC-OTM",
        implied,
        [cat_edge_yes],
        minutes_to_expiry=Decimal("20"),
        strike_price=59100,
        spot_price=69480,
        timeframe="15m",
        market_type="threshold",
    )
    cat_signal = strategy.evaluate(cat_snapshot)
    assert cat_signal.action == SignalAction.NO_ACTION

    # NO side is allowed when edge is positive
    cat_edge_no = _edge("KXBTC-OTM", "no", "0.04", "0.45", "0.35")
    cat_snapshot.edges = [cat_edge_no]
    cat_signal_no = strategy.evaluate(cat_snapshot)
    assert cat_signal_no.action == SignalAction.BUY_NO
