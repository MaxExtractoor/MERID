"""Tests for trading.agents.slippage_agent."""

from __future__ import annotations

from typing import List, Tuple

import pytest

from trading.agents.slippage_agent import (
    OrderBookSnapshot,
    ExecutionStrategy,
    SlippageAgent,
    get_slippage_agent,
)


@pytest.fixture()
def basic_snapshot() -> OrderBookSnapshot:
    bids: List[Tuple[float, float]] = [(99.0, 5.0), (98.5, 5.0)]
    asks: List[Tuple[float, float]] = [(101.0, 5.0), (101.5, 5.0)]
    return OrderBookSnapshot(
        venue="test",
        asset="BTC",
        timestamp=0.0,
        bids=bids,
        asks=asks,
        mid_price=100.0,
        spread_bps=200.0,
    )


def test_order_book_snapshot_market_impact_full_fill(basic_snapshot):
    impact = basic_snapshot.calculate_market_impact(size_usd=400.0, side="buy")

    assert impact > 0
    assert impact != float("inf")


def test_order_book_snapshot_market_impact_insufficient_liquidity(basic_snapshot):
    impact = basic_snapshot.calculate_market_impact(size_usd=2000.0, side="buy")

    assert impact == float("inf")


def test_slippage_agent_recommendations_vary_by_context(basic_snapshot):
    agent = SlippageAgent(max_acceptable_slippage_bps=50.0, min_liquidity_ratio=0.1)

    # Market order path when impact acceptable
    strat_market = agent.recommend_execution_strategy(
        basic_snapshot,
        order_size_usd=10.0,
        side="buy",
        urgency="urgent",
    )
    assert strat_market.strategy_type == "market"

    # TWAP path when liquidity ratio high
    strat_twap = agent.recommend_execution_strategy(basic_snapshot, order_size_usd=2000.0, side="buy")
    assert strat_twap.strategy_type == "twap"
    assert strat_twap.num_chunks >= 5

    # Limit path when patient
    strat_limit = agent.recommend_execution_strategy(basic_snapshot, order_size_usd=100.0, side="buy", urgency="patient")
    assert strat_limit.strategy_type == "limit"
    assert strat_limit.limit_price == pytest.approx(basic_snapshot.mid_price)

    # Iceberg fallback
    strat_iceberg = agent.recommend_execution_strategy(basic_snapshot, order_size_usd=400.0, side="buy", urgency="normal")
    assert strat_iceberg.strategy_type == "iceberg"


def test_slippage_agent_tracking_and_stats(basic_snapshot):
    agent = SlippageAgent()
    agent.track_execution(expected_slippage=10.0, actual_slippage=12.0, order_size=1000.0)
    agent.track_execution(expected_slippage=8.0, actual_slippage=9.0, order_size=500.0)

    stats = agent.get_performance_stats()

    assert stats["total_executions"] == 2
    assert stats["avg_slippage_bps"] > 0
    assert stats["max_slippage_bps"] >= stats["min_slippage_bps"]


def test_get_slippage_agent_singleton(monkeypatch):
    # Reset singleton
    from trading.agents import slippage_agent as module

    monkeypatch.setattr(module, "_slippage_agent", None)

    agent1 = get_slippage_agent()
    agent2 = get_slippage_agent()

    assert agent1 is agent2
