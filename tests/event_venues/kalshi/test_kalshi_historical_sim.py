"""Tests for Kalshi Historical Simulator."""

from decimal import Decimal

import pytest

from merid.event_venues.kalshi.historical_sim import (
    HistoricalTrade,
    KalshiHistoricalSimulator,
    SimFill,
    SimOrder,
    SimState,
    _sim_fee,
)


# ── Helpers ────────────────────────────────────────────────────────────

def _trade(ts: int, price: float, size: int = 1, side: str = "sell") -> HistoricalTrade:
    return HistoricalTrade(ts=ts, price=Decimal(str(price)), size=size, side=side)


def _buy_on_every_sell(tick: HistoricalTrade, state: SimState):
    """Simple strategy: buy 1 contract on every sell tick."""
    if tick.side == "sell":
        return [SimOrder(ts=tick.ts, price=tick.price, size=1, side="buy")]
    return []


def _sell_on_every_buy(tick: HistoricalTrade, state: SimState):
    """Close position on every buy tick."""
    if tick.side == "buy" and state.position > 0:
        return [SimOrder(ts=tick.ts, price=tick.price, size=1, side="sell")]
    return []


def _alternating_strategy(tick: HistoricalTrade, state: SimState):
    """Buy on sell ticks, sell on buy ticks."""
    if tick.side == "sell":
        return [SimOrder(ts=tick.ts, price=tick.price, size=1, side="buy")]
    elif tick.side == "buy" and state.position > 0:
        return [SimOrder(ts=tick.ts, price=tick.price, size=1, side="sell")]
    return []


# ── Fee calculation ───────────────────────────────────────────────────

class TestSimFee:
    def test_basic_fee(self):
        fee = _sim_fee(Decimal("0.55"), 10, 50)
        expected = Decimal("0.55") * 10 * Decimal(50) / Decimal(10_000)
        assert fee == expected

    def test_zero_size(self):
        assert _sim_fee(Decimal("0.55"), 0, 50) == Decimal("0")

    def test_zero_bps(self):
        assert _sim_fee(Decimal("0.55"), 10, 0) == Decimal("0")


# ── Basic simulation ─────────────────────────────────────────────────

class TestBasicSimulation:
    def test_empty_trades(self):
        sim = KalshiHistoricalSimulator([])
        fills = sim.run(_buy_on_every_sell)
        assert fills == []
        assert sim.state.total_trades == 0

    def test_single_buy_fill(self):
        trades = [_trade(1000, 0.55, side="sell")]
        sim = KalshiHistoricalSimulator(trades)
        fills = sim.run(_buy_on_every_sell)
        assert len(fills) == 1
        assert fills[0].side == "buy"
        assert fills[0].price == Decimal("0.55")
        assert sim.state.position == 1

    def test_no_fill_on_wrong_side(self):
        trades = [_trade(1000, 0.55, side="buy")]
        sim = KalshiHistoricalSimulator(trades)
        fills = sim.run(_buy_on_every_sell)
        assert len(fills) == 0

    def test_round_trip(self):
        trades = [
            _trade(1000, 0.55, side="sell"),  # buy here
            _trade(1001, 0.60, side="buy"),   # sell here
        ]
        sim = KalshiHistoricalSimulator(trades)
        fills = sim.run(_alternating_strategy)
        assert len(fills) == 2
        assert sim.state.position == 0

    def test_fees_deducted(self):
        trades = [_trade(1000, 0.55, side="sell")]
        sim = KalshiHistoricalSimulator(trades, fee_bps=100)
        sim.run(_buy_on_every_sell)
        assert sim.state.total_fees > 0

    def test_trades_sorted_by_ts(self):
        trades = [
            _trade(1002, 0.55, side="sell"),
            _trade(1000, 0.50, side="sell"),
            _trade(1001, 0.52, side="sell"),
        ]
        sim = KalshiHistoricalSimulator(trades)
        fills = sim.run(_buy_on_every_sell)
        assert fills[0].ts == 1000
        assert fills[1].ts == 1001
        assert fills[2].ts == 1002


# ── PnL tracking ─────────────────────────────────────────────────────

class TestPnLTracking:
    def test_winning_round_trip(self):
        trades = [
            _trade(1000, 0.50, side="sell"),  # buy at 0.50
            _trade(1001, 0.60, side="buy"),   # sell at 0.60
        ]
        sim = KalshiHistoricalSimulator(trades, fee_bps=0)
        sim.run(_alternating_strategy)
        assert sim.state.winning_trades == 1
        assert sim.state.losing_trades == 0

    def test_losing_round_trip(self):
        trades = [
            _trade(1000, 0.60, side="sell"),  # buy at 0.60
            _trade(1001, 0.50, side="buy"),   # sell at 0.50
        ]
        sim = KalshiHistoricalSimulator(trades, fee_bps=0)
        sim.run(_alternating_strategy)
        assert sim.state.winning_trades == 0
        assert sim.state.losing_trades == 1

    def test_consecutive_losers_tracked(self):
        trades = [
            _trade(1000, 0.60, side="sell"),
            _trade(1001, 0.50, side="buy"),
            _trade(1002, 0.60, side="sell"),
            _trade(1003, 0.50, side="buy"),
        ]
        sim = KalshiHistoricalSimulator(trades, fee_bps=0)
        sim.run(_alternating_strategy)
        assert sim.state.consecutive_losers == 2
        assert sim.state.max_consecutive_losers == 2


# ── Consecutive loser kill-switch ────────────────────────────────────

class TestConsecutiveLoserHalt:
    def test_halt_after_n_losers(self):
        trades = [
            _trade(1000, 0.60, side="sell"),
            _trade(1001, 0.50, side="buy"),
            _trade(1002, 0.60, side="sell"),
            _trade(1003, 0.50, side="buy"),
            _trade(1004, 0.60, side="sell"),  # would be 3rd entry but halted
            _trade(1005, 0.50, side="buy"),
        ]
        sim = KalshiHistoricalSimulator(trades, fee_bps=0, max_consecutive_losers=2)
        fills = sim.run(_alternating_strategy)
        assert sim.halted
        # Should have stopped after 2 losing round-trips (4 fills)
        assert len(fills) == 4

    def test_no_halt_when_disabled(self):
        trades = [
            _trade(1000, 0.60, side="sell"),
            _trade(1001, 0.50, side="buy"),
            _trade(1002, 0.60, side="sell"),
            _trade(1003, 0.50, side="buy"),
        ]
        sim = KalshiHistoricalSimulator(trades, fee_bps=0, max_consecutive_losers=0)
        sim.run(_alternating_strategy)
        assert not sim.halted

    def test_winner_resets_consecutive(self):
        trades = [
            _trade(1000, 0.60, side="sell"),  # buy
            _trade(1001, 0.50, side="buy"),   # sell (loss)
            _trade(1002, 0.40, side="sell"),  # buy
            _trade(1003, 0.60, side="buy"),   # sell (win — resets counter)
            _trade(1004, 0.60, side="sell"),  # buy
            _trade(1005, 0.50, side="buy"),   # sell (loss)
        ]
        sim = KalshiHistoricalSimulator(trades, fee_bps=0, max_consecutive_losers=2)
        sim.run(_alternating_strategy)
        assert not sim.halted  # Only 1 consecutive loser after the win


# ── Summary ──────────────────────────────────────────────────────────

class TestSummary:
    def test_summary_structure(self):
        sim = KalshiHistoricalSimulator([])
        sim.run(_buy_on_every_sell)
        s = sim.summary()
        assert "total_trades" in s
        assert "win_rate_pct" in s
        assert "total_pnl_usd" in s
        assert "max_drawdown_usd" in s
        assert "halted" in s

    def test_summary_with_trades(self):
        trades = [
            _trade(1000, 0.50, side="sell"),
            _trade(1001, 0.60, side="buy"),
        ]
        sim = KalshiHistoricalSimulator(trades, fee_bps=0)
        sim.run(_alternating_strategy)
        s = sim.summary()
        assert s["total_trades"] == 2
        assert s["winning_trades"] == 1


# ── Strategy error handling ──────────────────────────────────────────

class TestStrategyErrors:
    def test_strategy_exception_skipped(self):
        def bad_strategy(tick, state):
            raise ValueError("oops")

        trades = [_trade(1000, 0.55, side="sell")]
        sim = KalshiHistoricalSimulator(trades)
        fills = sim.run(bad_strategy)
        assert fills == []
        assert sim.state.total_trades == 0
