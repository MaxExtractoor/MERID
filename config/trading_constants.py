"""Trading Constants — Canonical source for all financial / risk magic numbers.

Import from here instead of using inline literals anywhere in the codebase.

Usage::

    from config.trading_constants import (
        KELLY_MAX_FRACTION,
        EDGE_MIN_THRESHOLD,
        POSITION_MAX_PCT,
    )
"""

from __future__ import annotations

import os

# ── Kelly / Position sizing ───────────────────────────────────────────────

# Maximum fractional Kelly to apply — prevents over-betting on high-edge signals
KELLY_MAX_FRACTION: float = float(os.getenv("MERID_KELLY_MAX_FRACTION", "0.25"))

# Hard cap on adjusted Kelly after all multipliers (50% of bankroll absolute max)
KELLY_ABSOLUTE_CAP: float = float(os.getenv("MERID_KELLY_ABSOLUTE_CAP", "0.50"))

# Minimum edge (probability points) — aligned to modern profile's lowest threshold
# BTC 15m = 0.011; setting floor at 0.011 ensures profile drives behavior, not this constant
EDGE_MIN_THRESHOLD: float = float(os.getenv("MERID_EDGE_MIN_THRESHOLD", "0.011"))

# Per-phase edge floors — used by StrategyConfig defaults and any sanity callers that
# want to check the canonical threshold without importing the strategy module.
# These must stay in sync with StrategyConfig in merid/prediction/strategy.py.
EDGE_FLOOR_EARLY: float = float(os.getenv("MERID_PM_MIN_EDGE_EARLY", "0.08"))
EDGE_FLOOR_MID: float = float(os.getenv("MERID_PM_MIN_EDGE_MID", "0.07"))
EDGE_FLOOR_LATE: float = float(os.getenv("MERID_PM_MIN_EDGE_LATE", "0.06"))
EDGE_FLOOR_TERMINAL: float = float(os.getenv("MERID_PM_MIN_EDGE_TERMINAL", "0.06"))

# Minimum model confidence (0–1) before a signal may proceed to consensus+execution.
# Aligned with StrategyConfig.min_confidence (0.60 default).
CONFIDENCE_MIN_THRESHOLD: float = float(os.getenv("MERID_PM_MIN_CONFIDENCE", "0.60"))

# Max single position as % of total bankroll
POSITION_MAX_PCT: float = float(os.getenv("MERID_POSITION_MAX_PCT", "0.10"))

# Max simultaneous open positions across the entire portfolio.
# Runtime default matches CT (KALSHI_TRADER_MAX_OPEN=5) and risk engine (KALSHI_MAX_OPEN_POSITIONS=5).
MAX_OPEN_POSITIONS: int = int(os.getenv("MERID_MAX_OPEN_POSITIONS", "5"))

# Max open positions sharing the same underlying asset/category
MAX_CORRELATED_POSITIONS: int = int(os.getenv("MERID_MAX_CORRELATED_POSITIONS", "5"))

# ── Debate position sizing multipliers ──────────────────────────────────

# Boost tiers — avg improvement must exceed these to qualify
DEBATE_BOOST_STRONG_THRESHOLD: float = 10.0  # > 10% improvement → 2.0x
DEBATE_BOOST_MEDIUM_THRESHOLD: float = 7.0   # > 7% improvement  → 1.5x
DEBATE_BOOST_MILD_THRESHOLD: float = 5.0     # > 5% improvement  → 1.25x
DEBATE_NORMAL_THRESHOLD: float = 2.0         # > 2% improvement  → 1.0x (hold)
DEBATE_REDUCE_THRESHOLD: float = 0.0         # < 0% improvement  → 0.75x
DEBATE_AVOID_THRESHOLD: float = -2.0         # < -2% improvement → 0.5x

# Debate win rate thresholds for recommendation classification
DEBATE_BOOST_WIN_RATE: float = 0.70          # Must win >70% of debates to boost
DEBATE_NORMAL_WIN_RATE: float = 0.50         # Must win >50% for normal
DEBATE_REDUCE_WIN_RATE: float = 0.30         # Win <30% → reduce

# Minimum number of debate outcomes required before any sizing adjustment
DEBATE_MIN_SAMPLES: int = 3

# Position size multipliers
DEBATE_MULT_BOOST_STRONG: float = 2.0
DEBATE_MULT_BOOST_MEDIUM: float = 1.5
DEBATE_MULT_BOOST_MILD: float = 1.25
DEBATE_MULT_NORMAL: float = 1.0
DEBATE_MULT_REDUCE: float = 0.75
DEBATE_MULT_AVOID: float = 0.5

# ── Correlation / Exposure ────────────────────────────────────────────────

# Rolling window (number of return observations) for Pearson correlation
CORRELATION_WINDOW: int = int(os.getenv("MERID_CORRELATION_WINDOW", "50"))

# Correlation above this threshold triggers exposure reduction
CORRELATION_THRESHOLD: float = 0.5

# Maximum exposure reduction factor at ρ=1.0 (reduce combined cap to 40%)
CORRELATION_MAX_REDUCTION: float = 0.4

# ── Paper trading simulation ─────────────────────────────────────────────

# Slippage in basis points applied to paper fills
PAPER_SLIPPAGE_BPS: float = float(os.getenv("MERID_KALSHI_PAPER_SLIPPAGE_BPS", "8.0"))

# Probability that a paper order gets a partial fill (when size > 1)
PAPER_PARTIAL_FILL_PROB: float = float(os.getenv("MERID_KALSHI_PAPER_PARTIAL_FILL_PROB", "0.35"))

# Minimum fill ratio when a partial fill occurs
PAPER_MIN_FILL_RATIO: float = float(os.getenv("MERID_KALSHI_PAPER_MIN_FILL_RATIO", "0.4"))

# ── Order sanity / hard limits ────────────────────────────────────────────

# Absolute maximum contracts per order — hard safety cap
ORDER_MAX_CONTRACTS: int = int(os.getenv("MERID_ORDER_MAX_CONTRACTS", "10000"))

# Maximum total notional portfolio value used in sanity checker ($USD)
SANITY_PORTFOLIO_USD: float = float(os.getenv("MERID_PM_MAX_TOTAL_NOTIONAL", "5000.0"))

# ── Passive-first execution ──────────────────────────────────────────────

# Seconds to wait for a passive (limit) order to fill before upgrading to aggressive
PASSIVE_ORDER_TIMEOUT_S: float = float(os.getenv("MERID_PASSIVE_ORDER_TIMEOUT_S", "30.0"))

# Price offset in cents used when posting passive (below ask for buys)
PASSIVE_PRICE_OFFSET_CENTS: int = int(os.getenv("MERID_PASSIVE_PRICE_OFFSET_CENTS", "1"))

# ── Signal quality / Kalshi generation ──────────────────────────────────

# Minimum Kalshi edge % to emit a signal (expressed as %, e.g. 5.0 = 5%)
KALSHI_EDGE_THRESHOLD_PCT: float = float(os.getenv("MERID_KALSHI_EDGE_THRESHOLD_PCT", "5.0"))

# Max signals generated per pipeline run
KALSHI_MAX_SIGNALS_PER_RUN: int = int(os.getenv("MERID_KALSHI_MAX_SIGNALS_PER_RUN", "50"))

# ── Performance / Sharpe ─────────────────────────────────────────────────

# Rolling trade windows for Sharpe calculation
SHARPE_WINDOW_SHORT: int = 15    # Fast window — responsive
SHARPE_WINDOW_MEDIUM: int = 50   # Standard window — consensus votes
SHARPE_WINDOW_LONG: int = 200    # Long-term stability

# Annualisation factor for Sharpe (prediction market trades, ~4/day)
SHARPE_ANNUALISATION: float = float(os.getenv("MERID_SHARPE_ANNUALISATION", "252.0"))

# Min sample count before Sharpe is trusted (below this: return None)
SHARPE_MIN_SAMPLES: int = 5

# Sharpe threshold below which an agent is considered underperforming
SHARPE_DOWNWEIGHT_THRESHOLD: float = 0.5

# Vote-weight multiplier applied to downweighted agents (50% reduction).
# Used by ConsensusAggregator._calculate_agent_weight() when proposal.downweight=True.
DOWNWEIGHT_VOTE_PENALTY: float = float(os.getenv("MERID_DOWNWEIGHT_VOTE_PENALTY", "0.5"))

# ── Brier calibration ────────────────────────────────────────────────────

# Brier score below which a forecaster is considered well-calibrated
BRIER_CALIBRATION_FLOOR: float = 0.2

# Default/uninformative Brier score (random guessing on binary outcome)
BRIER_UNINFORMATIVE: float = 0.25

# ── PnL / Reconciliation ─────────────────────────────────────────────────

# Maximum acceptable PnL divergence between paper and live engines ($)
PNL_DIVERGENCE_THRESHOLD_USD: float = float(os.getenv("MERID_PNL_DIVERGENCE_THRESHOLD", "5.0"))

# ── Cache TTLs ────────────────────────────────────────────────────────────

DEBATE_PERFORMANCE_CACHE_TTL_S: int = 3600   # 1 hour
CQI_SUMMARY_CACHE_TTL_S: int = 60            # 1 minute
SWARM_MATRIX_CACHE_TTL_S: int = 10           # 10 seconds

# ── Take-profit layer ────────────────────────────────────────────────────────

# Kalshi fee rate — 7% of C × P × (1−P) per leg
KALSHI_FEE_RATE: float = float(os.getenv("MERID_KALSHI_FEE_RATE", "0.07"))

# Default primary TP R-multiple for 15m crypto contracts
TP_DEFAULT_R_MULTIPLE_15M: float = float(os.getenv("MERID_TP_R_MULTIPLE_15M", "0.5"))

# Default primary TP R-multiple for hourly+ contracts
TP_DEFAULT_R_MULTIPLE_HOURLY: float = float(os.getenv("MERID_TP_R_MULTIPLE_HOURLY", "0.6"))

# Minimum absolute profit in cents before TP fires (prevents sub-spread targets)
TP_MIN_GAIN_CENTS: int = int(os.getenv("MERID_TP_MIN_GAIN_CENTS", "5"))

# Minimum net edge in cents per contract after fees required for TP to fire
TP_MIN_EDGE_AFTER_FEES_CENTS: float = float(os.getenv("MERID_TP_MIN_EDGE_AFTER_FEES_CENTS", "2.0"))

# ── Stop-loss layer ───────────────────────────────────────────────────────────

# Cents a position must drop from entry before the price-invalidation stop fires.
# Binary YES at 50¢ with a 20¢ drop fires at 30¢ — conservative vs. the Kalshi
# spread width of ~2-4¢ on liquid markets.
SL_PRICE_INVALIDATION_DROP_CENTS: int = int(os.getenv("MERID_SL_INVALIDATION_DROP_CENTS", "20"))

# Absolute price floor in cents — close any position if price falls to or below this.
SL_PRICE_FLOOR_CENTS: int = int(os.getenv("MERID_SL_PRICE_FLOOR_CENTS", "8"))

# Max loss per position as % of session equity before the position is force-closed.
SL_MAX_LOSS_PER_TRADE_PCT: float = float(os.getenv("MERID_SL_MAX_LOSS_PER_TRADE_PCT", "2.0"))

# Cumulative session loss as % of session equity that halts all new trading for the day.
SL_SESSION_LOSS_CAP_PCT: float = float(os.getenv("MERID_SL_SESSION_LOSS_CAP_PCT", "5.0"))

# Fraction of contract duration elapsed before a losing position is force-closed.
# 0.75 = close any loser when 75% of the contract's life has passed.
SL_CLOSE_IF_LOSING_AFTER_PCT: float = float(os.getenv("MERID_SL_CLOSE_LOSING_AFTER_PCT", "0.75"))

# Trailing TP: cents of giveback from peak before trailing close fires (15m)
TP_TRAILING_GIVEBACK_CENTS_15M: int = int(os.getenv("MERID_TP_TRAILING_GIVEBACK_CENTS_15M", "5"))

# Maximum round trips per contract (limits churn on single expiry)
TP_MAX_ROUND_TRIPS: int = int(os.getenv("MERID_TP_MAX_ROUND_TRIPS", "2"))

# Minimum price move (cents) from last TP exit before re-entry is allowed
TP_MIN_REENTRY_MOVE_CENTS: int = int(os.getenv("MERID_TP_MIN_REENTRY_MOVE_CENTS", "5"))
