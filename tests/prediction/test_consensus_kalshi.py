"""Targeted consensus tests for Kalshi weighting & fallbacks."""
from __future__ import annotations

import time
from typing import Iterable, Tuple
import sys
from types import ModuleType

import pytest


@pytest.fixture(autouse=True)
def disable_network_calls():
    """Override global network guard for this lightweight unit module."""
    return


def _stub_core_dev_swarm() -> None:
    if "core.dev_swarm" in sys.modules:
        return
    stub = ModuleType("core.dev_swarm")
    stub.DevSwarm = object  # type: ignore[attr-defined]
    stub.SwarmConfig = object  # type: ignore[attr-defined]
    sys.modules["core.dev_swarm"] = stub


_stub_core_dev_swarm()


def _install_trade_mode_stub() -> None:
    trading_pkg = sys.modules.setdefault("trading", ModuleType("trading"))
    if "trading.trade_mode" in sys.modules:
        return

    trade_mode_mod = ModuleType("trading.trade_mode")

    class TradeMode:
        MOCK = "mock"
        PAPER = "paper"
        LIVE = "live"

    class TradeModeConfig:
        def __init__(self, mode: str = TradeMode.PAPER, **kwargs):
            self.mode = mode
            for key, value in kwargs.items():
                setattr(self, key, value)

    def get_trade_mode(*_args, **_kwargs):
        return TradeMode.PAPER

    def set_trade_mode(_mode, **_kwargs):  # noqa: D401 - stub
        return TradeMode.PAPER

    def is_paper_or_mock() -> bool:
        return True

    def assert_not_live(context: str = "") -> None:  # noqa: D401 - stub
        return None

    trade_mode_mod.TradeMode = TradeMode
    trade_mode_mod.TradeModeConfig = TradeModeConfig
    trade_mode_mod.get_trade_mode = get_trade_mode
    trade_mode_mod.set_trade_mode = set_trade_mode
    trade_mode_mod.is_paper_or_mock = is_paper_or_mock
    trade_mode_mod.assert_not_live = assert_not_live

    setattr(trading_pkg, "trade_mode", trade_mode_mod)
    sys.modules["trading.trade_mode"] = trade_mode_mod
    sys.modules.setdefault("merid.trading.trade_mode", trade_mode_mod)


_install_trade_mode_stub()


from merid.prediction.consensus import (
    PredictionConsensusStore,
    PredictionInstrument,
    PredictionOpinion,
    _make_pred_symbol,
)

OpinionRow = Tuple[str, float, float]


@pytest.fixture()
def store(tmp_path):
    """Provide a fresh on-disk consensus store per test."""
    db_path = tmp_path / "pred_consensus_test.db"
    return PredictionConsensusStore(db_path=str(db_path))


def _seed_instrument(
    store: PredictionConsensusStore,
    ticker: str = "KXBTC24",
    market_prob: float = 0.55,
) -> PredictionInstrument:
    symbol = _make_pred_symbol("kalshi", ticker, "YES")
    inst = PredictionInstrument(
        symbol=symbol,
        venue="kalshi",
        event_id=ticker,
        ticker=ticker,
        outcome="YES",
        category="crypto",
        title=f"Test market {ticker}",
        market_implied_prob=market_prob,
        expiry=time.time() + 3600,
    )
    store.upsert_instrument(inst)
    return inst


def _seed_opinions(
    store: PredictionConsensusStore,
    symbol: str,
    rows: Iterable[OpinionRow],
) -> None:
    for agent_id, probability, confidence in rows:
        store.add_opinion(
            PredictionOpinion(
                agent_id=agent_id,
                agent_name=agent_id,
                symbol=symbol,
                probability=probability,
                confidence=confidence,
                reasoning="unit-test",
            )
        )


def test_consensus_summary_multiple_opinions(store):
    inst = _seed_instrument(store, market_prob=0.40)
    _seed_opinions(
        store,
        inst.symbol,
        [
            ("kalshi-agent-1", 0.70, 0.9),
            ("kalshi-agent-2", 0.30, 0.6),
        ],
    )

    summaries = store.get_consensus_summary()

    assert len(summaries) == 1
    summary = summaries[0]
    expected_swarm = pytest.approx((0.70 * 0.9 + 0.30 * 0.6) / (0.9 + 0.6), rel=1e-3)
    assert summary["swarm_prob"] == expected_swarm
    assert summary["confidence"] == pytest.approx((0.9 + 0.6) / 2, rel=1e-3)
    assert summary["supporting_agents"] == 1
    assert summary["opposing_agents"] == 1
    assert summary["stance"] == "strong_yes"


def test_consensus_summary_defaults_when_no_opinions(store):
    _seed_instrument(store, ticker="KXETH24", market_prob=0.70)

    summaries = store.get_consensus_summary()

    assert len(summaries) == 1
    summary = summaries[0]
    assert summary["swarm_prob"] == pytest.approx(0.5, rel=1e-3)
    assert summary["confidence"] == 0.0
    assert summary["supporting_agents"] == 0
    assert summary["opposing_agents"] == 0
    assert summary["stance"] == "strong_no"


def test_consensus_summary_respects_brier_weighting(store, monkeypatch):
    inst = _seed_instrument(store, market_prob=0.50)
    _seed_opinions(
        store,
        inst.symbol,
        [
            ("good-agent", 0.80, 0.3),
            ("bad-agent", 0.20, 0.9),
        ],
    )

    # Force deterministic weights (good agent 6x the bad agent)
    monkeypatch.setattr(
        store,
        "get_agent_brier_weights",
        lambda window=50: {"good-agent": 3.0, "bad-agent": 0.5},
    )
    store.invalidate_summary_cache()

    summaries = store.get_consensus_summary()

    assert len(summaries) == 1
    summary = summaries[0]
    expected_swarm = pytest.approx((0.80 * 3.0 + 0.20 * 0.5) / (3.0 + 0.5), rel=1e-3)
    assert summary["swarm_prob"] == expected_swarm
    assert summary["stance"] == "strong_yes"
    # Confidence still reports the simple average of submitted confidences
    assert summary["confidence"] == pytest.approx((0.3 + 0.9) / 2, rel=1e-3)
