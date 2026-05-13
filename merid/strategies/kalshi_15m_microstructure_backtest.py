"""
Kalshi 15m Microstructure Backtest
==================================
Backtest harness for comparing three SignalFusion integration strategies:

S0: base regime only (no orderflow_bias, no onchain_velocity)
S1: base + orderflow_bias boosts
S2: base + orderflow_bias + onchain_velocity gate (full current logic)

This backtests the actual Btc15mAgent signal generation logic with
different SignalFusion configurations to measure the marginal value
of microstructure signals.

Usage:
    from merid.strategies.kalshi_15m_microstructure_backtest import run_microstructure_backtest

    results = run_microstructure_backtest("BTC", df_kalshi, df_price)
    print(results["summary"])
"""

import math
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from enum import Enum

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class Strategy(Enum):
    """Backtest strategy variants."""
    S0_BASE = "S0_BASE"  # base regime only
    S1_ORDERFLOW = "S1_ORDERFLOW"  # base + orderflow_bias
    S2_FULL = "S2_FULL"  # base + orderflow_bias + onchain_velocity gate


@dataclass
class MicrostructureTradeRecord:
    """Single backtest trade with full signal context."""
    market_id: str
    entry_time: Any
    close_time: Any
    side: str
    entry_price: float  # Kalshi price in cents
    outcome: int  # 1 = Up wins, 0 = Down wins
    pnl_cents: float
    fee_cents: float
    contracts: int
    strategy: Strategy

    # Signal fusion inputs
    orderflow_bias: float = 0.0
    onchain_velocity: float = 0.0

    # Probability space metrics
    p_market: float = 0.0
    p_model_base: float = 0.0
    p_model: float = 0.0
    prob_boost: float = 0.0
    kelly_fraction: float = 0.0

    # Regime signal
    regime: str = ""
    regime_confidence: float = 0.0
    base_edge_est: float = 0.0

    # Volatility
    vol_15m_realized: float = 0.0
    vol_baseline_median: float = 0.0


@dataclass
class MicrostructureBacktestSummary:
    """Aggregate backtest performance metrics per strategy."""
    strategy: Strategy
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    total_pnl_cents: float = 0.0
    avg_pnl_per_trade: float = 0.0
    avg_ev_vs_outcome: float = 0.0  # avg edge_estimate vs realized outcome
    total_fees_cents: float = 0.0
    max_drawdown_cents: float = 0.0
    sharpe_ratio: float = 0.0
    avg_kelly_fraction: float = 0.0

    # Microstructure signal stats
    avg_orderflow_bias: float = 0.0
    avg_onchain_velocity: float = 0.0
    avg_prob_boost: float = 0.0

    # Calibration stats
    p_model_bins: Dict[str, Dict[str, float]] = field(default_factory=dict)


def kalshi_fee_cents(price_cents: float, contracts: int = 1) -> float:
    """Kalshi taker fee: ceil(0.07 * contracts * P * (1-P))."""
    p = price_cents / 100.0
    return math.ceil(0.07 * contracts * p * (1.0 - p))


def trade_pnl_cents(
    side: str,
    entry_price_cents: float,
    outcome: int,
    contracts: int,
) -> tuple:
    """Compute (gross_pnl, fee, net_pnl) in cents for a binary trade."""
    fee = kalshi_fee_cents(entry_price_cents, contracts)

    if side == "buy_yes":
        if outcome == 1:
            gross = (100.0 - entry_price_cents) * contracts
        else:
            gross = -entry_price_cents * contracts
    else:  # buy_no
        down_price = 100.0 - entry_price_cents
        if outcome == 0:
            gross = (100.0 - down_price) * contracts
        else:
            gross = -down_price * contracts

    net = gross - fee
    return gross, fee, net


def kelly_fraction(p_model: float, price_cents: float) -> float:
    """Calculate Kelly fraction for a YES bet.

    f* = (p(b+1) - 1) / b, where b = (1-p_market) / p_market
    """
    p_market = price_cents / 100.0
    b = (1 - p_market) / p_market
    numer = p_model * (b + 1) - 1
    if b <= 0 or numer <= 0:
        return 0.0
    f_star = numer / b
    return max(0.0, min(f_star, 1.0))


def cents_to_prob(edge_cents: float) -> float:
    """Convert edge in cents to probability points.

    Around 50c, 1c ≈ 1% probability.
    """
    return edge_cents / 100.0


def simulate_btc15m_signal(
    regime_signal: Dict[str, Any],
    kalshi_price: float,
    orderflow_bias: float,
    onchain_velocity: float,
    vol_15m_realized: float,
    vol_baseline_median: float,
    strategy: Strategy,
    kelly_shrink: float = 0.25,
    max_kelly_cap: float = 0.10,
) -> Optional[Dict[str, Any]]:
    """Simulate Btc15mSignalGenerator.generate_signal logic for backtesting.

    This replicates the signal generation logic from kalshi_btc_15m_agent_spec.py
    but allows toggling SignalFusion inputs via the strategy parameter.
    """
    # Risk filters (simplified for backtest)
    if regime_signal.get("confidence", 0) < 0.6:
        return None
    if regime_signal.get("regime") == "chop":
        return None

    base_edge_est = regime_signal.get("edge_estimate", 0.0)
    if base_edge_est < 0.02:  # 2¢ minimum edge
        return None

    direction = regime_signal.get("direction")
    if not direction:
        return None

    # Probability-space Kelly sizing
    p_market = kalshi_price / 100.0
    p_model_base = p_market + cents_to_prob(base_edge_est)

    # Microstructure fusion (strategy-dependent)
    prob_boost = 0.0
    onchain_gate_multiplier = 1.0

    if strategy in [Strategy.S1_ORDERFLOW, Strategy.S2_FULL]:
        # Apply orderflow_bias boosts
        direction_sign = 1 if direction == "up" else -1
        alignment_score = direction_sign * orderflow_bias

        if alignment_score > 0.5:
            prob_boost = cents_to_prob(0.03)  # +3¢ → +0.03 probability
        elif alignment_score > 0.2:
            prob_boost = cents_to_prob(0.02)  # +2¢ → +0.02 probability
        elif alignment_score < -0.1:
            prob_boost = 0.0

    if strategy == Strategy.S2_FULL:
        # Apply on-chain velocity gate
        if onchain_velocity < 0:
            onchain_gate_multiplier = 0.5
        elif onchain_velocity > 1.0 and vol_15m_realized > vol_baseline_median:
            onchain_gate_multiplier = 1.2

    p_model = p_model_base + prob_boost
    p_model = max(0.01, min(0.99, p_model))

    # Compute Kelly fraction
    base_kelly = kelly_fraction(p_model, kalshi_price)
    kelly_fraction = min(base_kelly * kelly_shrink, max_kelly_cap)
    kelly_fraction *= onchain_gate_multiplier

    # Calculate edge per unit stake
    p_mkt = kalshi_price / 100.0
    b = (1 - p_mkt) / p_mkt
    edge_per_stake = p_model * b - (1 - p_model)

    # Only trade if edge is positive
    if edge_per_stake <= 0:
        return None

    return {
        "action": "buy" if direction == "up" else "sell",
        "p_market": p_market,
        "p_model_base": p_model_base,
        "p_model": p_model,
        "prob_boost": prob_boost,
        "kelly_fraction": kelly_fraction,
        "edge_estimate": edge_per_stake,
    }


def run_microstructure_backtest(
    asset: str,
    df_kalshi: pd.DataFrame,
    df_orderflow: Optional[pd.DataFrame] = None,
    df_onchain: Optional[pd.DataFrame] = None,
    df_vol: Optional[pd.DataFrame] = None,
    contracts: int = 10,
) -> Dict[str, Any]:
    """Run backtest comparing S0, S1, S2 strategies for an asset.

    Args:
        asset: Asset ticker (BTC, ETH, SOL, XRP, DOGE)
        df_kalshi: Kalshi markets DataFrame with columns:
            - market_id: str
            - open_time: datetime
            - close_time: datetime
            - settle: int (1=Up wins, 0=Down wins)
            - entry_price: float (Kalshi YES price in cents)
            - regime_signal: dict (regime, confidence, direction, edge_estimate)
        df_orderflow: Optional orderflow_bias time series (timestamp, orderflow_bias)
        df_onchain: Optional onchain_velocity time series (timestamp, onchain_velocity)
        df_vol: Optional volatility data (timestamp, vol_15m_realized, vol_baseline_median)
        contracts: Number of contracts per trade

    Returns:
        Dict with strategy summaries and trade records.
    """
    results: Dict[Strategy, List[MicrostructureTradeRecord]] = {
        Strategy.S0_BASE: [],
        Strategy.S1_ORDERFLOW: [],
        Strategy.S2_FULL: [],
    }

    # Sort Kalshi markets by open time
    df_kalshi = df_kalshi.sort_values("open_time").reset_index(drop=True)

    logger.info(f"Microstructure backtest for {asset}: {len(df_kalshi)} markets")

    for _, mkt in df_kalshi.iterrows():
        t_entry = pd.Timestamp(mkt["open_time"])
        entry_price_cents = float(mkt["entry_price"])
        outcome = int(mkt["settle"])
        market_id = str(mkt["market_id"])
        regime_signal = mkt.get("regime_signal", {})

        # Get microstructure signals at entry time (fallback to 0 if not available)
        orderflow_bias = 0.0
        onchain_velocity = 0.0
        vol_15m_realized = 0.05  # default 5% vol
        vol_baseline_median = 0.04  # default 4% baseline

        if df_orderflow is not None:
            of_slice = df_orderflow[df_orderflow["timestamp"] <= t_entry]
            if not of_slice.empty:
                orderflow_bias = float(of_slice.iloc[-1]["orderflow_bias"])

        if df_onchain is not None:
            oc_slice = df_onchain[df_onchain["timestamp"] <= t_entry]
            if not oc_slice.empty:
                onchain_velocity = float(oc_slice.iloc[-1]["onchain_velocity"])

        if df_vol is not None:
            vol_slice = df_vol[df_vol["timestamp"] <= t_entry]
            if not vol_slice.empty:
                vol_15m_realized = float(vol_slice.iloc[-1]["vol_15m_realized"])
                vol_baseline_median = float(vol_slice.iloc[-1]["vol_baseline_median"])

        # Run signal generation for each strategy
        for strategy in Strategy:
            signal = simulate_btc15m_signal(
                regime_signal=regime_signal,
                kalshi_price=entry_price_cents,
                orderflow_bias=orderflow_bias,
                onchain_velocity=onchain_velocity,
                vol_15m_realized=vol_15m_realized,
                vol_baseline_median=vol_baseline_median,
                strategy=strategy,
            )

            if signal is None:
                continue

            # Compute PnL
            side = "buy_yes" if signal["action"] == "buy" else "buy_no"
            gross, fee, net = trade_pnl_cents(side, entry_price_cents, outcome, contracts)

            trade = MicrostructureTradeRecord(
                market_id=market_id,
                entry_time=t_entry,
                close_time=pd.Timestamp(mkt["close_time"]),
                side=side,
                entry_price=entry_price_cents,
                outcome=outcome,
                pnl_cents=net,
                fee_cents=fee,
                contracts=contracts,
                strategy=strategy,
                orderflow_bias=orderflow_bias,
                onchain_velocity=onchain_velocity,
                p_market=signal["p_market"],
                p_model_base=signal["p_model_base"],
                p_model=signal["p_model"],
                prob_boost=signal["prob_boost"],
                kelly_fraction=signal["kelly_fraction"],
                regime=regime_signal.get("regime", ""),
                regime_confidence=regime_signal.get("confidence", 0.0),
                base_edge_est=regime_signal.get("edge_estimate", 0.0),
                vol_15m_realized=vol_15m_realized,
                vol_baseline_median=vol_baseline_median,
            )
            results[strategy].append(trade)

    # Compute summaries
    summaries = {}
    for strategy, trades in results.items():
        summaries[strategy.value] = _compute_microstructure_summary(trades)

    return {
        "asset": asset,
        "summaries": summaries,
        "trades": {s.value: [t.__dict__ for t in ts] for s, ts in results.items()},
    }


def _compute_microstructure_summary(trades: List[MicrostructureTradeRecord]) -> MicrostructureBacktestSummary:
    """Aggregate trade records into performance metrics."""
    s = MicrostructureBacktestSummary(strategy=Strategy.S0_BASE)

    if not trades:
        return s

    s.total_trades = len(trades)
    s.wins = sum(1 for t in trades if t.pnl_cents > 0)
    s.losses = sum(1 for t in trades if t.pnl_cents <= 0)
    s.win_rate = s.wins / s.total_trades if s.total_trades > 0 else 0.0

    pnls = [t.pnl_cents for t in trades]
    fees = [t.fee_cents for t in trades]

    s.total_pnl_cents = sum(pnls)
    s.avg_pnl_per_trade = s.total_pnl_cents / s.total_trades
    s.total_fees_cents = sum(fees)

    # Avg EV vs outcome (p_model vs realized win rate)
    s.avg_ev_vs_outcome = np.mean([t.p_model - (1 if t.outcome == 1 else 0) for t in trades])

    # Drawdown
    equity = np.cumsum(pnls)
    peak = np.maximum.accumulate(equity)
    drawdown = peak - equity
    s.max_drawdown_cents = float(np.max(drawdown)) if len(drawdown) > 0 else 0.0

    # Sharpe (annualized assuming ~96 15m periods per day, 365 days)
    if len(pnls) > 1:
        pnl_arr = np.array(pnls)
        mean_pnl = np.mean(pnl_arr)
        std_pnl = np.std(pnl_arr, ddof=1)
        if std_pnl > 0:
            daily_trades = 96
            s.sharpe_ratio = (mean_pnl / std_pnl) * np.sqrt(daily_trades * 365)
        else:
            s.sharpe_ratio = 0.0

    # Microstructure signal stats
    s.avg_orderflow_bias = np.mean([t.orderflow_bias for t in trades])
    s.avg_onchain_velocity = np.mean([t.onchain_velocity for t in trades])
    s.avg_prob_boost = np.mean([t.prob_boost for t in trades])
    s.avg_kelly_fraction = np.mean([t.kelly_fraction for t in trades])

    # Calibration bins
    s.p_model_bins = _compute_calibration_bins(trades)

    return s


def _compute_calibration_bins(trades: List[MicrostructureTradeRecord]) -> Dict[str, Dict[str, float]]:
    """Bin trades by p_model and compute realized win rate per bin."""
    bins = [
        (0.40, 0.45),
        (0.45, 0.50),
        (0.50, 0.55),
        (0.55, 0.60),
        (0.60, 0.65),
        (0.65, 0.70),
    ]

    result = {}
    for low, high in bins:
        bin_trades = [t for t in trades if low <= t.p_model < high]
        if bin_trades:
            wins = sum(1 for t in bin_trades if t.outcome == 1)
            result[f"{low}-{high}"] = {
                "count": len(bin_trades),
                "avg_p_model": np.mean([t.p_model for t in bin_trades]),
                "realized_win_rate": wins / len(bin_trades),
                "calibration_error": (wins / len(bin_trades)) - np.mean([t.p_model for t in bin_trades]),
            }

    return result


def print_backtest_comparison(results: Dict[str, Any]) -> None:
    """Print a comparison table of S0, S1, S2 strategies."""
    asset = results["asset"]
    summaries = results["summaries"]

    print(f"\n{'='*80}")
    print(f"Microstructure Backtest Results: {asset}")
    print(f"{'='*80}")

    print(f"\n{'Strategy':<12} {'Trades':<8} {'Win Rate':<10} {'Total PnL':<12} {'Avg PnL':<10} {'Sharpe':<8} {'Max DD':<10}")
    print("-" * 80)

    for strategy_name, summary in summaries.items():
        print(
            f"{strategy_name:<12} {summary['total_trades']:<8} "
            f"{summary['win_rate']:.1%}  ${summary['total_pnl_cents']:>10.2f}c "
            f"${summary['avg_pnl_per_trade']:>8.2f}c  {summary['sharpe_ratio']:.2f}  "
            f"${summary['max_drawdown_cents']:>8.2f}c"
        )

    print(f"\n{'Strategy':<12} {'Avg Kelly':<10} {'Avg OF Bias':<12} {'Avg OC Vel':<12} {'Avg Boost':<10}")
    print("-" * 80)

    for strategy_name, summary in summaries.items():
        print(
            f"{strategy_name:<12} {summary['avg_kelly_fraction']:.3f}  "
            f"{summary['avg_orderflow_bias']:+.3f}  {summary['avg_onchain_velocity']:+.3f}  "
            f"{summary['avg_prob_boost']:.3f}"
        )

    print(f"\nCalibration (p_model bins):")
    for strategy_name, summary in summaries.items():
        if summary["p_model_bins"]:
            print(f"\n{strategy_name}:")
            for bin_name, bin_stats in summary["p_model_bins"].items():
                print(
                    f"  {bin_name}: n={bin_stats['count']}, "
                    f"p_model={bin_stats['avg_p_model']:.3f}, "
                    f"realized={bin_stats['realized_win_rate']:.3f}, "
                    f"err={bin_stats['calibration_error']:.3f}"
                )
