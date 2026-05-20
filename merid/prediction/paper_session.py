"""Paper Session Runner — Long-running paper trading sessions with readiness tracking.

Tracks per-agent, per-interval PnL and coverage metrics across the full Kalshi
crypto surface (BTC/ETH/SOL/XRP/DOGE × 15m/hourly/daily/weekly).

Readiness benchmarks gate paper→live promotion:
- Stable PnL (positive over rolling window)
- Low error rate (< threshold)
- Clean circuit-breaker history (no trips in window)
- Minimum trade count
- Minimum win rate
- Minimum profit factor (PF ≥ 1.1 safety, 1.4+ interesting, 1.6+ promotion)
- Minimum expectancy (avg PnL per trade > 0)

Per-cell benchmark overrides allow stricter gates for high-frequency cells
(BTC/ETH hourly, SOL 15m) vs slower cells (weekly).

The PredictionMarketRisk config is the single knob for flipping a market
from paper to live mode.
"""

from __future__ import annotations

import threading
import json
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from utils.logger import get_logger

logger = get_logger(__name__)

_PERSIST_FILE = Path("data/paper_session_state.json")

# ── Crypto surface definition ─────────────────────────────────────────

CRYPTO_ASSETS = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
CRYPTO_TIMEFRAMES = ["15m", "1h", "daily", "weekly"]

# Agent name convention: {ASSET}_{TIMEFRAME_LABEL}
_TF_LABELS = {"15m": "15M", "1h": "HOURLY", "daily": "DAILY", "weekly": "WEEKLY"}


def crypto_agent_names() -> List[str]:
    """Return all 20 crypto directional agent names."""
    return [
        f"{asset}_{_TF_LABELS[tf]}"
        for asset in CRYPTO_ASSETS
        for tf in CRYPTO_TIMEFRAMES
    ]


# ── Readiness benchmarks ──────────────────────────────────────────────

@dataclass
class ReadinessBenchmark:
    """Thresholds that must be met before paper→live promotion.

    Default floor raised to 55% win rate and PF≥1.3 (from 48%/1.1) to ensure
    only demonstrably edge-positive cells get promoted.  The 75% live-trading
    target requires at least this standard from paper before risking real capital.
    """
    min_trades: int = 50
    min_win_rate_pct: float = 55.0       # raised from 48% — require real edge evidence
    max_error_rate_pct: float = 5.0
    min_session_hours: float = 24.0
    max_drawdown_pct: float = 10.0
    min_profit_factor: float = 1.3       # raised from 1.1 — ensure positive expectancy
    min_expectancy_cents: float = 5.0    # raised from 0 — require ≥5¢ avg profit per trade
    max_circuit_breaker_trips: int = 0
    rolling_window_hours: float = 72.0
    min_daily_trades: int = 0


DEFAULT_BENCHMARK = ReadinessBenchmark()

# ── Per-cell benchmark overrides ──────────────────────────────────────
# Stricter gates for high-frequency / high-volume cells.

_CELL_BENCHMARKS: Dict[str, ReadinessBenchmark] = {
    # BTC/ETH hourly: high volume — require strong proof of edge before promotion
    "BTC_HOURLY": ReadinessBenchmark(
        min_trades=100, min_win_rate_pct=57.0, max_error_rate_pct=5.0,
        min_session_hours=24.0, max_drawdown_pct=10.0,
        min_profit_factor=1.5, min_expectancy_cents=18.0,
        max_circuit_breaker_trips=0, min_daily_trades=20,
    ),
    "ETH_HOURLY": ReadinessBenchmark(
        min_trades=100, min_win_rate_pct=57.0, max_error_rate_pct=5.0,
        min_session_hours=24.0, max_drawdown_pct=10.0,
        min_profit_factor=1.5, min_expectancy_cents=18.0,
        max_circuit_breaker_trips=0, min_daily_trades=20,
    ),
    # SOL 15m: stress-test cell, strictest gates — highest noise, requires largest margin
    "SOL_15M": ReadinessBenchmark(
        min_trades=100, min_win_rate_pct=60.0, max_error_rate_pct=3.0,
        min_session_hours=24.0, max_drawdown_pct=5.0,
        min_profit_factor=1.6, min_expectancy_cents=22.0,
        max_circuit_breaker_trips=0, min_daily_trades=30,
    ),
    # BTC/ETH 15m: fast cells — moderately strict
    "BTC_15M": ReadinessBenchmark(
        min_trades=100, min_win_rate_pct=57.0, max_error_rate_pct=5.0,
        min_session_hours=24.0, max_drawdown_pct=8.0,
        min_profit_factor=1.4, min_expectancy_cents=12.0,
        max_circuit_breaker_trips=0, min_daily_trades=20,
    ),
    "ETH_15M": ReadinessBenchmark(
        min_trades=100, min_win_rate_pct=57.0, max_error_rate_pct=5.0,
        min_session_hours=24.0, max_drawdown_pct=8.0,
        min_profit_factor=1.4, min_expectancy_cents=12.0,
        max_circuit_breaker_trips=0, min_daily_trades=20,
    ),
}


def get_benchmark_for(agent_name: str, fallback: Optional[ReadinessBenchmark] = None) -> ReadinessBenchmark:
    """Return the per-cell benchmark override, or the fallback/default."""
    return _CELL_BENCHMARKS.get(agent_name, fallback or DEFAULT_BENCHMARK)


# ── Session risk limits ─────────────────────────────────────────
# Per-session caps to prevent tail-risk blowups in long-running sessions.
# These are COMPLEMENTARY to the production risk limits in kalshi_15m_crypto_config.py:
# - kalshi_15m_crypto_config.py: Order-level limits (max_contracts_per_order, max_open_contracts, etc.)
# - paper_session.py: Session-level limits (daily/weekly loss caps, drawdown governance)
# Both LIVE and PAPER use these session-level limits for governance.

@dataclass
class SessionRiskLimits:
    """Risk limits enforced per session to prevent runaway losses.

    These complement PredictionMarketRisk (which governs per-order checks)
    by adding session-level loss caps, cluster caps, and drawdown governance.
    
    NOTE: These are session-level governance limits, not order-level sizing limits.
    DEPRECATED: Order-level limits from kalshi_15m_crypto_config.py are deprecated.
    Use profile config (kalshi_crypto_15m.yaml) for kalshi_crypto_15m_v2 profile.
    """
    # Per-cell daily/weekly loss caps (cents)
    max_daily_loss_cents: float = 5000.0     # $50/day per cell
    max_weekly_loss_cents: float = 15000.0   # $150/week per cell

    # Correlated-asset cluster caps (cents, combined across all timeframes)
    max_cluster_daily_loss_cents: float = 10000.0   # $100/day per cluster

    # Rolling drawdown governance
    drawdown_warning_pct: float = 5.0    # Warn at 5% DD from HWM
    drawdown_downsize_pct: float = 8.0   # Auto-downsize at 8%
    drawdown_halt_pct: float = 12.0      # Auto-halt at 12%
    downsize_factor: float = 0.5         # Reduce logical size to 50%


DEFAULT_RISK_LIMITS = SessionRiskLimits()

# Correlated-asset clusters — assets that move together and should share
# a combined loss cap so one move can't blow multiple hourly grids.
ASSET_CLUSTERS: Dict[str, List[str]] = {
    "BTC_ETH": ["BTC", "ETH"],
    "ALT_BASKET": ["SOL", "XRP", "DOGE"],
}


# ── Per-interval PnL bucket ───────────────────────────────────────────

@dataclass
class IntervalPnL:
    """PnL tracking for a single (asset, timeframe) cell."""
    asset: str
    timeframe: str
    agent_name: str
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    gross_pnl_cents: float = 0.0
    gross_wins_cents: float = 0.0
    gross_losses_cents: float = 0.0
    fees_cents: float = 0.0
    net_pnl_cents: float = 0.0
    high_water_mark_cents: float = 0.0
    max_drawdown_cents: float = 0.0
    errors: int = 0
    circuit_breaker_trips: int = 0
    first_trade_at: Optional[str] = None
    last_trade_at: Optional[str] = None
    last_updated: Optional[str] = None
    # Rolling daily/weekly loss tracking
    daily_loss_cents: float = 0.0
    daily_reset_date: Optional[str] = None
    weekly_loss_cents: float = 0.0
    weekly_reset_date: Optional[str] = None
    # Halt / downsize state
    halted: bool = False
    downsized: bool = False
    halt_reason: Optional[str] = None

    @property
    def win_rate_pct(self) -> float:
        total = self.winning_trades + self.losing_trades
        return (self.winning_trades / total * 100) if total > 0 else 0.0

    @property
    def net_pnl_usd(self) -> float:
        return self.net_pnl_cents / 100.0

    @property
    def drawdown_pct(self) -> float:
        # Anchor the HWM denominator at max(hwm, 0) so that cells which start
        # with a run of losses (hwm stays 0) still report meaningful drawdown.
        # If net_pnl_cents is negative and hwm is still 0, the drawdown from
        # the zero-equity starting point is reported as a positive percentage.
        hwm = max(self.high_water_mark_cents, 0.0)
        if hwm <= 0:
            # No peak established yet; express loss relative to a 1-unit base
            # so governance thresholds can still fire (treat starting equity
            # as the implicit HWM for cells that have never been profitable).
            if self.net_pnl_cents < 0:
                return 100.0  # 100% drawdown from zero base
            return 0.0
        return (self.max_drawdown_cents / hwm) * 100

    @property
    def profit_factor(self) -> float:
        if self.gross_losses_cents <= 0:
            return float("inf") if self.gross_wins_cents > 0 else 0.0
        return self.gross_wins_cents / self.gross_losses_cents

    @property
    def error_rate_pct(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return (self.errors / self.total_trades) * 100

    @property
    def avg_win_cents(self) -> float:
        """Average winning trade in cents."""
        return self.gross_wins_cents / self.winning_trades if self.winning_trades > 0 else 0.0

    @property
    def avg_loss_cents(self) -> float:
        """Average losing trade in cents (positive magnitude)."""
        return self.gross_losses_cents / self.losing_trades if self.losing_trades > 0 else 0.0

    @property
    def expectancy_cents(self) -> float:
        """Expected PnL per trade in cents.

        Formula: (win_rate × avg_win) − (loss_rate × avg_loss)
        """
        total = self.winning_trades + self.losing_trades
        if total == 0:
            return 0.0
        wr = self.winning_trades / total
        lr = 1.0 - wr
        return wr * self.avg_win_cents - lr * self.avg_loss_cents

    @property
    def expectancy_usd(self) -> float:
        return self.expectancy_cents / 100.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            **asdict(self),
            "win_rate_pct": round(self.win_rate_pct, 1),
            "net_pnl_usd": round(self.net_pnl_usd, 2),
            "drawdown_pct": round(self.drawdown_pct, 2),
            "profit_factor": round(self.profit_factor, 2) if self.profit_factor != float("inf") else "inf",
            "error_rate_pct": round(self.error_rate_pct, 2),
            "avg_win_cents": round(self.avg_win_cents, 2),
            "avg_loss_cents": round(self.avg_loss_cents, 2),
            "expectancy_cents": round(self.expectancy_cents, 2),
            "expectancy_usd": round(self.expectancy_usd, 4),
            "daily_loss_usd": round(self.daily_loss_cents / 100, 2),
            "weekly_loss_usd": round(self.weekly_loss_cents / 100, 2),
            "halted": self.halted,
            "downsized": self.downsized,
            "halt_reason": self.halt_reason,
        }


# ── Readiness verdict ─────────────────────────────────────────────────

@dataclass
class ReadinessVerdict:
    """Result of checking an agent against readiness benchmarks."""
    agent_name: str
    ready: bool
    checks: Dict[str, bool] = field(default_factory=dict)
    details: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_name": self.agent_name,
            "ready": self.ready,
            "checks": self.checks,
            "details": self.details,
        }


# ── Paper Session ─────────────────────────────────────────────────────

class PaperSession:
    """Manages a long-running paper trading session across the full crypto surface.

    Usage::

        session = get_paper_session()
        session.start_session()
        session.record_fill(agent_name, pnl_cents, fees_cents, won=True)
        session.record_error(agent_name)
        session.check_readiness("BTC_15M")
        session.summary()
    """

    def __init__(
        self,
        benchmark: Optional[ReadinessBenchmark] = None,
        risk_limits: Optional[SessionRiskLimits] = None,
    ):
        self._benchmark = benchmark or DEFAULT_BENCHMARK
        self._risk_limits = risk_limits or DEFAULT_RISK_LIMITS
        self._intervals: Dict[str, IntervalPnL] = {}
        self._session_start: Optional[float] = None
        self._session_id: Optional[str] = None
        self._live_promoted: Set[str] = set()
        self._open_trades: Dict[str, List[Dict[str, Any]]] = {}
        self._load_state()

    # ── Session lifecycle ──────────────────────────────────────────

    def start_session(self, session_id: Optional[str] = None) -> str:
        """Start or resume a paper session. Returns session ID."""
        if self._session_start is None:
            self._session_start = time.time()
            self._session_id = session_id or datetime.now(timezone.utc).strftime(
                "paper-%Y%m%d-%H%M%S"
            )

        # Ensure all 20 crypto agents have interval buckets
        for name in crypto_agent_names():
            if name not in self._intervals:
                parts = name.rsplit("_", 1)
                asset = parts[0]
                tf_label = parts[1] if len(parts) > 1 else "15M"
                tf_map = {"15M": "15m", "HOURLY": "1h", "DAILY": "daily", "WEEKLY": "weekly"}
                tf = tf_map.get(tf_label, "15m")
                self._intervals[name] = IntervalPnL(
                    asset=asset, timeframe=tf, agent_name=name,
                )

        self._save_state()
        logger.info(
            f"Paper session started: {self._session_id}, "
            f"{len(self._intervals)} interval buckets"
        )
        return self._session_id

    @property
    def session_id(self) -> Optional[str]:
        """Public accessor for the current session ID."""
        return self._session_id

    @property
    def session_hours(self) -> float:
        if self._session_start is None:
            return 0.0
        return (time.time() - self._session_start) / 3600

    @property
    def is_active(self) -> bool:
        return self._session_start is not None

    # ── Agent name resolution ──────────────────────────────────────

    def _resolve_agent_name(self, name: str) -> Optional[str]:
        """Normalize various agent name formats to canonical interval key.

        Handles:
          - Config names: BTC_1H → BTC_HOURLY, BTC_15m → BTC_15M
          - Agent IDs: kalshi-btc_15m → BTC_15M, kalshi-btc_1h → BTC_HOURLY
          - Canonical names: BTC_15M, BTC_HOURLY (pass-through)

        Returns None if name cannot be resolved.
        """
        if not name or not isinstance(name, str):
            return None

        # Already canonical (exists in intervals)
        if name in self._intervals:
            return name

        # Agent ID format: kalshi-{asset}_{timeframe}
        if name.startswith("kalshi-"):
            # Remove prefix
            core = name[7:]  # e.g., "btc_15m" or "btc_1h"
            parts = core.rsplit("_", 1)
            if len(parts) == 2:
                asset, tf = parts
                asset = asset.upper()
                # Normalize timeframe
                if tf in ("15m", "15M"):
                    canonical = f"{asset}_15M"
                elif tf in ("1h", "hourly"):
                    canonical = f"{asset}_HOURLY"
                elif tf in ("daily", "1d"):
                    canonical = f"{asset}_DAILY"
                elif tf in ("weekly", "1w"):
                    canonical = f"{asset}_WEEKLY"
                else:
                    return None
                if canonical in self._intervals:
                    return canonical
            return None

        # Config name format: BTC_1H → BTC_HOURLY
        if "_" in name:
            parts = name.rsplit("_", 1)
            if len(parts) == 2:
                asset, tf = parts
                asset = asset.upper()
                # Map config timeframes to canonical labels
                tf_map = {
                    "15M": "15M", "15m": "15M",
                    "1H": "HOURLY", "1h": "HOURLY", "hourly": "HOURLY",
                    "1D": "DAILY", "1d": "DAILY", "daily": "DAILY",
                    "1W": "WEEKLY", "1w": "WEEKLY", "weekly": "WEEKLY",
                }
                canonical_tf = tf_map.get(tf)
                if canonical_tf:
                    canonical = f"{asset}_{canonical_tf}"
                    if canonical in self._intervals:
                        return canonical

        return None

    # ── Recording ──────────────────────────────────────────────────

    def record_fill(
        self,
        agent_name: str,
        pnl_cents: float,
        fees_cents: float = 0.0,
        won: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Record a fill (entry) for an agent.

        Only books trade count, fees, and timestamps.  PnL and win/loss
        classification are intentionally deferred to ``record_settlement``
        so that binary-outcome markets are not double-counted (BUG-08/BUG-01
        fix: the preliminary ``pnl_cents`` / ``won`` arguments are accepted
        for backward compatibility but ignored for PnL bookkeeping when a
        corresponding ``register_open_trade`` call will precede settlement).

        For markets that settle immediately (e.g. closed contracts passed
        directly as resolved), callers may pass ``won`` explicitly and this
        method will book PnL directly — but only when ``won is not None``
        AND no pending open trade exists for the same market/agent pair
        (i.e. ``record_settlement`` will not fire later).

        Returns a status dict with ``accepted`` flag and any risk actions taken.
        """
        # Resolve agent name to canonical form (BUG-10 fix)
        resolved_name = self._resolve_agent_name(agent_name)
        if resolved_name is None:
            logger.debug(f"No interval bucket for {agent_name} (tried resolve), skipping")
            return {"accepted": False, "reason": "unknown_agent"}

        interval = self._intervals.get(resolved_name)
        if not interval:
            logger.debug(f"No interval bucket for {resolved_name}, skipping")
            return {"accepted": False, "reason": "unknown_agent"}

        if interval.halted:
            return {"accepted": False, "reason": "cell_halted", "halt_reason": interval.halt_reason}

        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()
        today_str = now.strftime("%Y-%m-%d")
        week_str = now.strftime("%Y-W%W")

        # ── Roll daily/weekly counters ────────────────────────────
        if interval.daily_reset_date != today_str:
            interval.daily_loss_cents = 0.0
            interval.daily_reset_date = today_str
        if interval.weekly_reset_date != week_str:
            interval.weekly_loss_cents = 0.0
            interval.weekly_reset_date = week_str

        # ── Trade count, fees, timestamps only ───────────────────
        # PnL and win/loss are booked exclusively in record_settlement.
        interval.total_trades += 1
        interval.fees_cents += fees_cents
        interval.last_trade_at = now_iso
        interval.last_updated = now_iso

        if interval.first_trade_at is None:
            interval.first_trade_at = now_iso

        # ── Fee drag on daily/weekly loss caps ───────────────────
        if fees_cents > 0:
            interval.daily_loss_cents += fees_cents
            interval.weekly_loss_cents += fees_cents

        # ── Direct PnL bookkeeping ────────────────────────────────
        # Book PnL immediately when pnl_cents is non-zero.  The
        # register_open_trade + record_settlement flow is a separate
        # path for markets that have not yet resolved; callers using
        # that path do not pass pnl_cents here.
        if pnl_cents != 0.0:
            resolved_won = won if won is not None else (pnl_cents > 0)
            interval.gross_pnl_cents += pnl_cents
            interval.net_pnl_cents += pnl_cents - fees_cents
            if resolved_won:
                interval.winning_trades += 1
                interval.gross_wins_cents += abs(pnl_cents)
            else:
                interval.losing_trades += 1
                interval.gross_losses_cents += abs(pnl_cents)
                if pnl_cents < 0:
                    interval.daily_loss_cents += abs(pnl_cents)
                    interval.weekly_loss_cents += abs(pnl_cents)
            if interval.net_pnl_cents > interval.high_water_mark_cents:
                interval.high_water_mark_cents = interval.net_pnl_cents
            dd = interval.high_water_mark_cents - interval.net_pnl_cents
            if dd > interval.max_drawdown_cents:
                interval.max_drawdown_cents = dd

        # ── Enforce session risk limits ───────────────────────────
        risk_actions = self._enforce_risk_limits(interval)

        self._save_state()
        return {"accepted": True, "risk_actions": risk_actions}

    def register_open_trade(
        self,
        agent_name: str,
        market_id: str,
        side: str,
        action: str,
        contracts: int,
        price_cents: float,
        entry_price_cents: Optional[float] = None,
    ) -> None:
        """Register an open paper trade awaiting settlement.

        Called at fill time (BUG-02 fix).  OutcomeResolver calls
        ``record_settlement`` once the market resolves so that PnL is
        booked from the real binary outcome, not a Bernoulli draw.

        Bug 6 fix: ``entry_price_cents`` records the original entry price for
        buy orders so that early sell-closes can compute the correct P&L
        (exit_price - entry_price) instead of being silently skipped.
        """
        key = market_id
        if key not in self._open_trades:
            self._open_trades[key] = []
        self._open_trades[key].append({
            "agent_name": agent_name,
            "market_id": market_id,
            "side": side,
            "action": action,
            "contracts": contracts,
            "price_cents": price_cents,
            # Bug 6 fix: entry_price_cents is the price paid at buy-open.  For
            # buy actions it equals price_cents.  For sell-close actions the
            # caller passes the original entry price here so early-exit PnL
            # can be computed as (exit_price - entry_price) * contracts.
            "entry_price_cents": entry_price_cents if entry_price_cents is not None else price_cents,
            "registered_at": datetime.now(timezone.utc).isoformat(),
        })

    def record_settlement(self, market_id: str, outcome: int) -> List[Dict[str, Any]]:
        """Settle all open paper trades for a market with the real binary outcome.

        Args:
            market_id: Kalshi market ticker.
            outcome: 1 if YES resolved, 0 if NO resolved.

        Returns:
            List of settlement result dicts for logging.
        """
        trades = self._open_trades.pop(market_id, [])
        results = []
        for trade in trades:
            agent_name = trade["agent_name"]
            contracts = trade["contracts"]
            price_cents = trade["price_cents"]
            side = trade["side"]   # "yes" or "no"
            action = trade["action"]  # "buy" or "sell"

            entry_price_cents = trade.get("entry_price_cents", price_cents)

            # Bug 6 fix: distinguish early sell-close from hold-to-expiry.
            # A sell-close has a known exit price (price_cents) and a known
            # entry price (entry_price_cents).  Its PnL is deterministic:
            #   YES sell-close: (exit - entry) * contracts
            #   NO  sell-close: (entry - exit) * contracts
            # We only use the binary payoff formula for positions held to expiry.
            if action == "sell":
                if side == "yes":
                    pnl_cents = (price_cents - entry_price_cents) * contracts
                else:
                    pnl_cents = (entry_price_cents - price_cents) * contracts
                won = pnl_cents > 0
                interval = self._intervals.get(agent_name)
                if interval:
                    interval.gross_pnl_cents += pnl_cents
                    interval.net_pnl_cents += pnl_cents
                    if won:
                        interval.winning_trades += 1
                        interval.gross_wins_cents += abs(pnl_cents)
                    else:
                        interval.losing_trades += 1
                        interval.gross_losses_cents += abs(pnl_cents)
                        if pnl_cents < 0:
                            interval.daily_loss_cents += abs(pnl_cents)
                            interval.weekly_loss_cents += abs(pnl_cents)
                    if interval.net_pnl_cents > interval.high_water_mark_cents:
                        interval.high_water_mark_cents = interval.net_pnl_cents
                    dd = interval.high_water_mark_cents - interval.net_pnl_cents
                    if dd > interval.max_drawdown_cents:
                        interval.max_drawdown_cents = dd
                    interval.last_updated = datetime.now(timezone.utc).isoformat()
                    self._enforce_risk_limits(interval)
                results.append({
                    "agent_name": agent_name,
                    "market_id": market_id,
                    "won": won,
                    "pnl_cents": pnl_cents,
                    "early_close": True,
                })
                continue

            # Binary payoff for positions held to expiry:
            # YES buyer wins (100 - price) per contract if outcome=1
            # NO  buyer wins price per contract if outcome=0
            if side == "yes":
                won = bool(outcome == 1)
                pnl_cents = ((100.0 - price_cents) * contracts) if won else (-price_cents * contracts)
            else:
                won = bool(outcome == 0)
                pnl_cents = (price_cents * contracts) if won else (-(100.0 - price_cents) * contracts)

            interval = self._intervals.get(agent_name)
            if interval:
                # Book PnL — fees already deducted at record_fill time.
                interval.gross_pnl_cents += pnl_cents
                interval.net_pnl_cents += pnl_cents
                if won:
                    interval.winning_trades += 1
                    interval.gross_wins_cents += abs(pnl_cents)
                else:
                    interval.losing_trades += 1
                    interval.gross_losses_cents += abs(pnl_cents)
                    if pnl_cents < 0:
                        interval.daily_loss_cents += abs(pnl_cents)
                        interval.weekly_loss_cents += abs(pnl_cents)
                # Update HWM and drawdown
                if interval.net_pnl_cents > interval.high_water_mark_cents:
                    interval.high_water_mark_cents = interval.net_pnl_cents
                dd = interval.high_water_mark_cents - interval.net_pnl_cents
                if dd > interval.max_drawdown_cents:
                    interval.max_drawdown_cents = dd
                interval.last_updated = datetime.now(timezone.utc).isoformat()
                self._enforce_risk_limits(interval)

            results.append({
                "agent_name": agent_name,
                "market_id": market_id,
                "won": won,
                "pnl_cents": pnl_cents,
                "outcome": outcome,
            })

        if trades:
            self._save_state()
        return results

    def record_error(self, agent_name: str) -> None:
        """Record an error for an agent."""
        resolved = self._resolve_agent_name(agent_name)
        if resolved is None:
            return
        interval = self._intervals.get(resolved)
        if interval:
            interval.errors += 1
            interval.last_updated = datetime.now(timezone.utc).isoformat()

    def record_circuit_breaker_trip(self, agent_name: str) -> None:
        """Record a circuit breaker trip for an agent."""
        resolved = self._resolve_agent_name(agent_name)
        if resolved is None:
            return
        interval = self._intervals.get(resolved)
        if interval:
            interval.circuit_breaker_trips += 1
            interval.last_updated = datetime.now(timezone.utc).isoformat()

    # ── Session risk governance ───────────────────────────────────

    def _enforce_risk_limits(self, interval: IntervalPnL) -> List[Dict[str, Any]]:
        """Check and enforce session risk limits after a fill.

        Returns a list of risk actions taken (halt, downsize, warning).
        """
        actions: List[Dict[str, Any]] = []
        rl = self._risk_limits

        # 1. Per-cell daily loss cap
        if interval.daily_loss_cents >= rl.max_daily_loss_cents:
            if not interval.halted:
                interval.halted = True
                interval.halt_reason = (
                    f"Daily loss cap: {interval.daily_loss_cents:.0f}c "
                    f">= {rl.max_daily_loss_cents:.0f}c"
                )
                actions.append({
                    "action": "halt", "agent": interval.agent_name,
                    "type": "daily_loss_cap", "reason": interval.halt_reason,
                })
                logger.warning(f"[risk] HALTED {interval.agent_name}: {interval.halt_reason}")

        # 2. Per-cell weekly loss cap
        if interval.weekly_loss_cents >= rl.max_weekly_loss_cents:
            if not interval.halted:
                interval.halted = True
                interval.halt_reason = (
                    f"Weekly loss cap: {interval.weekly_loss_cents:.0f}c "
                    f">= {rl.max_weekly_loss_cents:.0f}c"
                )
                actions.append({
                    "action": "halt", "agent": interval.agent_name,
                    "type": "weekly_loss_cap", "reason": interval.halt_reason,
                })
                logger.warning(f"[risk] HALTED {interval.agent_name}: {interval.halt_reason}")

        # 3. Correlated-asset cluster daily loss cap
        cluster_action = self._check_cluster_cap(interval.asset)
        if cluster_action:
            actions.append(cluster_action)

        # 4. Rolling drawdown governance
        dd_action = self._check_drawdown_governance(interval)
        if dd_action:
            actions.append(dd_action)

        return actions

    def _check_cluster_cap(self, asset: str) -> Optional[Dict[str, Any]]:
        """Check if the correlated-asset cluster daily loss exceeds cap."""
        rl = self._risk_limits
        for cluster_name, cluster_assets in ASSET_CLUSTERS.items():
            if asset not in cluster_assets:
                continue
            # Sum daily losses across all cells in this cluster
            cluster_daily_loss = 0.0
            cluster_cells: List[str] = []
            for name, interval in self._intervals.items():
                if interval.asset in cluster_assets:
                    cluster_daily_loss += interval.daily_loss_cents
                    cluster_cells.append(name)

            if cluster_daily_loss >= rl.max_cluster_daily_loss_cents:
                halted_any = False
                for cell_name in cluster_cells:
                    cell = self._intervals.get(cell_name)
                    if cell and not cell.halted:
                        cell.halted = True
                        cell.halt_reason = (
                            f"Cluster {cluster_name} daily loss: "
                            f"{cluster_daily_loss:.0f}c >= {rl.max_cluster_daily_loss_cents:.0f}c"
                        )
                        halted_any = True
                if halted_any:
                    logger.warning(
                        f"[risk] CLUSTER HALT {cluster_name}: "
                        f"{cluster_daily_loss:.0f}c daily loss, "
                        f"halted {len(cluster_cells)} cells"
                    )
                    return {
                        "action": "cluster_halt", "cluster": cluster_name,
                        "type": "cluster_daily_loss_cap",
                        "daily_loss_cents": round(cluster_daily_loss),
                        "cells_halted": cluster_cells,
                    }
        return None

    def _check_drawdown_governance(self, interval: IntervalPnL) -> Optional[Dict[str, Any]]:
        """Check drawdown thresholds and apply governance actions."""
        rl = self._risk_limits
        dd_pct = interval.drawdown_pct

        # Halt at severe drawdown
        if dd_pct >= rl.drawdown_halt_pct and not interval.halted:
            interval.halted = True
            interval.halt_reason = (
                f"Drawdown halt: {dd_pct:.1f}% >= {rl.drawdown_halt_pct}%"
            )
            logger.warning(f"[risk] DD HALT {interval.agent_name}: {interval.halt_reason}")
            return {
                "action": "halt", "agent": interval.agent_name,
                "type": "drawdown_halt",
                "drawdown_pct": round(dd_pct, 2),
                "threshold_pct": rl.drawdown_halt_pct,
            }

        # Auto-downsize at moderate drawdown
        if dd_pct >= rl.drawdown_downsize_pct and not interval.downsized:
            interval.downsized = True
            logger.info(
                f"[risk] DOWNSIZED {interval.agent_name}: DD={dd_pct:.1f}% "
                f">= {rl.drawdown_downsize_pct}%, factor={rl.downsize_factor}"
            )
            return {
                "action": "downsize", "agent": interval.agent_name,
                "type": "drawdown_downsize",
                "drawdown_pct": round(dd_pct, 2),
                "threshold_pct": rl.drawdown_downsize_pct,
                "downsize_factor": rl.downsize_factor,
            }

        # Warning at early drawdown
        if dd_pct >= rl.drawdown_warning_pct:
            return {
                "action": "warning", "agent": interval.agent_name,
                "type": "drawdown_warning",
                "drawdown_pct": round(dd_pct, 2),
                "threshold_pct": rl.drawdown_warning_pct,
            }

        return None

    # ── Halt / unhalt controls ────────────────────────────────────

    def halt_cell(self, agent_name: str, reason: str = "manual") -> bool:
        """Manually halt a cell."""
        interval = self._intervals.get(agent_name)
        if not interval:
            return False
        interval.halted = True
        interval.halt_reason = reason
        self._save_state()
        logger.info(f"[risk] Manual HALT {agent_name}: {reason}")
        return True

    def unhalt_cell(self, agent_name: str) -> bool:
        """Unhalt a cell (e.g. after daily reset or manual review)."""
        interval = self._intervals.get(agent_name)
        if not interval:
            return False
        interval.halted = False
        interval.downsized = False
        interval.halt_reason = None
        self._save_state()
        logger.info(f"[risk] UNHALTED {agent_name}")
        return True

    def unhalt_all(self) -> int:
        """Unhalt all cells. Returns count of cells unhalted."""
        count = 0
        for interval in self._intervals.values():
            if interval.halted or interval.downsized:
                interval.halted = False
                interval.downsized = False
                interval.halt_reason = None
                count += 1
        if count:
            self._save_state()
            logger.info(f"[risk] UNHALTED ALL: {count} cells")
        return count

    def is_halted(self, agent_name: str) -> bool:
        """Check if a cell is halted."""
        interval = self._intervals.get(agent_name)
        return interval.halted if interval else False

    def is_downsized(self, agent_name: str) -> bool:
        """Check if a cell is downsized."""
        interval = self._intervals.get(agent_name)
        return interval.downsized if interval else False

    def get_size_factor(self, agent_name: str) -> float:
        """Return the effective size factor for an agent (1.0 or downsize_factor)."""
        interval = self._intervals.get(agent_name)
        if not interval:
            return 1.0
        if interval.halted:
            return 0.0
        if interval.downsized:
            return self._risk_limits.downsize_factor
        return 1.0

    def risk_status(self) -> Dict[str, Any]:
        """Return session-wide risk status for API consumption."""
        halted = [n for n, i in self._intervals.items() if i.halted]
        downsized = [n for n, i in self._intervals.items() if i.downsized and not i.halted]

        # Cluster losses
        cluster_status: Dict[str, Dict[str, Any]] = {}
        for cluster_name, cluster_assets in ASSET_CLUSTERS.items():
            daily = sum(
                i.daily_loss_cents for i in self._intervals.values()
                if i.asset in cluster_assets
            )
            weekly = sum(
                i.weekly_loss_cents for i in self._intervals.values()
                if i.asset in cluster_assets
            )
            cluster_status[cluster_name] = {
                "assets": cluster_assets,
                "daily_loss_cents": round(daily),
                "weekly_loss_cents": round(weekly),
                "daily_cap_cents": self._risk_limits.max_cluster_daily_loss_cents,
                "utilization_pct": round(
                    daily / self._risk_limits.max_cluster_daily_loss_cents * 100, 1
                ) if self._risk_limits.max_cluster_daily_loss_cents > 0 else 0,
            }

        return {
            "halted_cells": halted,
            "halted_count": len(halted),
            "downsized_cells": downsized,
            "downsized_count": len(downsized),
            "clusters": cluster_status,
            "limits": asdict(self._risk_limits),
        }

    # ── Readiness checks ───────────────────────────────────────────

    def check_readiness(self, agent_name: str, benchmark_override: Optional[ReadinessBenchmark] = None) -> ReadinessVerdict:
        """Check if an agent meets all readiness benchmarks for live promotion.

        Accepts canonical names, config names (BTC_1H), and agent IDs (kalshi-btc_15m).

        Uses per-cell benchmark overrides when available (e.g. stricter PF for
        BTC_HOURLY, SOL_15M), falling back to the session-level default.
        """
        # Resolve agent name to canonical form (BUG-10 fix)
        resolved = self._resolve_agent_name(agent_name)
        if resolved is None:
            return ReadinessVerdict(
                agent_name=agent_name,
                ready=False,
                checks={"exists": False},
                details={"error": f"Unknown agent name: {agent_name}"},
            )

        interval = self._intervals.get(resolved)
        b = benchmark_override or get_benchmark_for(resolved, self._benchmark)
        checks: Dict[str, bool] = {}
        details: Dict[str, str] = {}

        if not interval:
            return ReadinessVerdict(
                agent_name=agent_name, ready=False,
                checks={"exists": False},
                details={"exists": f"No interval data for {agent_name}"},
            )

        # 1. Minimum trades
        checks["min_trades"] = interval.total_trades >= b.min_trades
        details["min_trades"] = f"{interval.total_trades}/{b.min_trades}"

        # 2. Win rate
        checks["win_rate"] = interval.win_rate_pct >= b.min_win_rate_pct
        details["win_rate"] = f"{interval.win_rate_pct:.1f}%/{b.min_win_rate_pct}%"

        # 3. Error rate
        checks["error_rate"] = interval.error_rate_pct <= b.max_error_rate_pct
        details["error_rate"] = f"{interval.error_rate_pct:.1f}%/{b.max_error_rate_pct}%"

        # 4. Session duration
        checks["session_hours"] = self.session_hours >= b.min_session_hours
        details["session_hours"] = f"{self.session_hours:.1f}h/{b.min_session_hours}h"

        # 5. Drawdown
        checks["drawdown"] = interval.drawdown_pct <= b.max_drawdown_pct
        details["drawdown"] = f"{interval.drawdown_pct:.1f}%/{b.max_drawdown_pct}%"

        # 6. Profit factor
        pf = interval.profit_factor
        pf_ok = pf >= b.min_profit_factor if pf != float("inf") else True
        checks["profit_factor"] = pf_ok
        pf_str = f"{pf:.2f}" if pf != float("inf") else "inf"
        details["profit_factor"] = f"{pf_str}/{b.min_profit_factor}"

        # 7. Expectancy
        exp = interval.expectancy_cents
        checks["expectancy"] = exp >= b.min_expectancy_cents
        details["expectancy"] = f"{exp:.1f}c/{b.min_expectancy_cents}c"

        # 8. Circuit breaker trips
        checks["circuit_breaker"] = interval.circuit_breaker_trips <= b.max_circuit_breaker_trips
        details["circuit_breaker"] = (
            f"{interval.circuit_breaker_trips}/{b.max_circuit_breaker_trips}"
        )

        # 9. Ladder tier gate — portfolio must be at Live-Ready (tier 4) before
        #    any agent may be promoted.  This links PaperSession to PaperLadder
        #    so the two systems cannot diverge.
        _LIVE_READY_TIER = 4
        ladder_tier_ok = False
        ladder_tier_detail = "ladder unavailable"
        try:
            from merid.paper_ladder import get_paper_ladder
            _ladder = get_paper_ladder()
            all_progress = _ladder.get_all_progress()
            if all_progress:
                # Use the highest tier across all tracked portfolios (any
                # portfolio that has reached Live-Ready unlocks agent promotion).
                max_tier = max(p.current_tier for p in all_progress.values())
                ladder_tier_ok = max_tier >= _LIVE_READY_TIER
                ladder_tier_detail = f"tier {max_tier}/{_LIVE_READY_TIER}"
            else:
                # No portfolios tracked → ladder hasn't been initialised yet;
                # treat as fail-open so unit tests and early deployments are not
                # permanently gated on ladder progression.
                ladder_tier_ok = True
                ladder_tier_detail = "no portfolios tracked"
        except Exception as _le:
            logger.debug("[paper-session] Ladder tier check skipped: %s", _le)
            ladder_tier_ok = True  # fail-open when ladder not available
            ladder_tier_detail = f"skipped ({_le})"
        checks["ladder_tier"] = ladder_tier_ok
        details["ladder_tier"] = ladder_tier_detail

        ready = all(checks.values())

        # ── Structured readiness audit log ──────────────────────────────────
        # Emit a single structured log line with all key metrics so operators
        # can grep for READINESS_AUDIT and reconstruct win-rate / R:R history
        # without parsing individual trade records.
        try:
            from merid.metrics.performance import TradeRecord, compute_performance_metrics

            _pf_val = interval.profit_factor
            _rr_val = (
                round(interval.avg_win_cents / interval.avg_loss_cents, 3)
                if interval.avg_loss_cents > 0
                else float("inf")
            )
            logger.info(
                "[READINESS_AUDIT] agent=%s ready=%s "
                "trades=%d win_rate=%.1f%% profit_factor=%.2f "
                "avg_rr=%.2f expectancy_cents=%.1f drawdown=%.1f%% "
                "meets_75pct=%s checks=%s",
                agent_name,
                ready,
                interval.total_trades,
                interval.win_rate_pct,
                _pf_val if _pf_val != float("inf") else 9999.0,
                _rr_val if _rr_val != float("inf") else 9999.0,
                interval.expectancy_cents,
                interval.drawdown_pct,
                interval.win_rate_pct >= 75.0,
                {k: v for k, v in checks.items() if not v} or "ALL_PASS",
            )
        except Exception as _log_err:
            logger.debug("readiness_audit log skipped: %s", _log_err)

        return ReadinessVerdict(
            agent_name=agent_name, ready=ready, checks=checks, details=details,
        )

    def check_all_readiness(self) -> Dict[str, ReadinessVerdict]:
        """Check readiness for all crypto agents."""
        return {name: self.check_readiness(name) for name in crypto_agent_names()}

    # ── Live promotion ─────────────────────────────────────────────

    def promote_to_live(self, agent_name: str, force: bool = False) -> Dict[str, Any]:
        """Promote an agent from paper to live mode.

        Uses PredictionMarketRisk config as the single knob — flips the
        VenueGate mode for the specific agent's markets.

        Args:
            agent_name: Agent to promote.
            force: Skip readiness checks (operator override).

        Returns:
            Promotion result dict.
        """
        if not force:
            verdict = self.check_readiness(agent_name)
            if not verdict.ready:
                failing = [k for k, v in verdict.checks.items() if not v]
                return {
                    "promoted": False,
                    "agent": agent_name,
                    "reason": f"Readiness checks failed: {', '.join(failing)}",
                    "verdict": verdict.to_dict(),
                }

        self._live_promoted.add(agent_name)
        self._save_state()

        # G5: Delegate actual mode change to DeploymentController (single source of truth)
        try:
            from merid.event_venues.kalshi.deployment import get_deployment_controller
            _dc = get_deployment_controller()
            _ok, _reason = _dc.promote_to_live(agent_name, readiness=None)
            if not _ok:
                logger.warning(
                    "[paper-session] DeploymentController rejected promotion for %s: %s",
                    agent_name, _reason,
                )
        except Exception as _dce:
            logger.debug("[paper-session] DeploymentController promote skipped: %s", _dce)

        logger.info(f"[paper-session] PROMOTED {agent_name} to LIVE (force={force})")
        return {
            "promoted": True,
            "agent": agent_name,
            "mode": "live",
            "force": force,
        }

    def demote_to_paper(self, agent_name: str) -> Dict[str, Any]:
        """Demote an agent back to paper mode."""
        self._live_promoted.discard(agent_name)
        self._save_state()

        # G5: Sync rollback to DeploymentController
        try:
            from merid.event_venues.kalshi.deployment import get_deployment_controller
            get_deployment_controller().rollback(agent_name, reason="paper-session-demote")
        except Exception as _dce:
            logger.debug("[paper-session] DeploymentController rollback skipped: %s", _dce)

        logger.info(f"[paper-session] DEMOTED {agent_name} back to PAPER")
        return {"demoted": True, "agent": agent_name, "mode": "paper"}

    @property
    def live_agents(self) -> Set[str]:
        # Bypass paper session gating when in live mode
        import os
        trading_mode = os.getenv("MERID_TRADING_MODE", "").lower()
        if trading_mode == "live":
            logger.info("[paper-session] MERID_TRADING_MODE=live - bypassing paper session gating, all agents considered live")
            return set(crypto_agent_names())  # All agents considered live
        return set(self._live_promoted)

    def is_live(self, agent_name: str) -> bool:
        # Bypass paper session gating when in live mode
        import os
        trading_mode = os.getenv("MERID_TRADING_MODE", "").lower()
        if trading_mode == "live":
            logger.debug("[paper-session] MERID_TRADING_MODE=live - agent %s considered live", agent_name)
            return True  # All agents considered live in live mode
        return agent_name in self._live_promoted

    # ── Coverage metrics ───────────────────────────────────────────

    def coverage_summary(self) -> Dict[str, Any]:
        """Return coverage metrics: how much of the crypto surface is actively trading."""
        total_cells = len(crypto_agent_names())
        active_cells = sum(
            1 for name in crypto_agent_names()
            if self._intervals.get(name) and self._intervals[name].total_trades > 0
        )
        by_asset: Dict[str, Dict[str, Any]] = {}
        for asset in CRYPTO_ASSETS:
            asset_intervals = {
                name: self._intervals[name]
                for name in crypto_agent_names()
                if name.startswith(asset + "_") and name in self._intervals
            }
            active = sum(1 for i in asset_intervals.values() if i.total_trades > 0)
            total_pnl = sum(i.net_pnl_usd for i in asset_intervals.values())
            total_trades = sum(i.total_trades for i in asset_intervals.values())
            by_asset[asset] = {
                "timeframes": len(asset_intervals),
                "active": active,
                "total_trades": total_trades,
                "net_pnl_usd": round(total_pnl, 2),
            }

        by_timeframe: Dict[str, Dict[str, Any]] = {}
        for tf in CRYPTO_TIMEFRAMES:
            tf_label = _TF_LABELS[tf]
            tf_intervals = {
                name: self._intervals[name]
                for name in crypto_agent_names()
                if name.endswith(f"_{tf_label}") and name in self._intervals
            }
            active = sum(1 for i in tf_intervals.values() if i.total_trades > 0)
            total_pnl = sum(i.net_pnl_usd for i in tf_intervals.values())
            total_trades = sum(i.total_trades for i in tf_intervals.values())
            by_timeframe[tf] = {
                "assets": len(tf_intervals),
                "active": active,
                "total_trades": total_trades,
                "net_pnl_usd": round(total_pnl, 2),
            }

        return {
            "total_cells": total_cells,
            "active_cells": active_cells,
            "coverage_pct": round((active_cells / total_cells * 100) if total_cells else 0, 1),
            "by_asset": by_asset,
            "by_timeframe": by_timeframe,
        }

    # ── Coverage gap alerts ──────────────────────────────────────────

    def coverage_gap_alerts(self, min_daily_trades: int = 20) -> List[Dict[str, Any]]:
        """Flag cells with low trade count relative to expectations.

        Policy: if a cell has fewer than *min_daily_trades* trades per 24h of
        session time, it is flagged as under-utilised.  Per-cell benchmarks
        override the default if ``min_daily_trades`` is set.

        Returns a list of alert dicts.
        """
        alerts: List[Dict[str, Any]] = []
        session_days = max(self.session_hours / 24.0, 1 / 24)  # at least 1 hour

        for name in crypto_agent_names():
            interval = self._intervals.get(name)
            if not interval:
                continue
            b = get_benchmark_for(name, self._benchmark)
            threshold = b.min_daily_trades if b.min_daily_trades > 0 else min_daily_trades
            expected = threshold * session_days
            if interval.total_trades < expected:
                alerts.append({
                    "agent": name,
                    "level": "warning",
                    "type": "coverage_gap",
                    "message": (
                        f"{name}: {interval.total_trades} trades in "
                        f"{self.session_hours:.1f}h (expected ≥{expected:.0f})"
                    ),
                    "trades": interval.total_trades,
                    "expected": round(expected),
                    "deficit_pct": round(
                        (1 - interval.total_trades / expected) * 100, 1
                    ) if expected > 0 else 100.0,
                })

        return sorted(alerts, key=lambda a: a["deficit_pct"], reverse=True)

    # ── PF / expectancy warning alerts ────────────────────────────────

    def health_alerts(self) -> List[Dict[str, Any]]:
        """Check all active cells for PF or expectancy degradation.

        Fires warnings when:
        - PF drops below 1.1 (safety floor)
        - Expectancy turns negative
        - Error rate exceeds benchmark

        Returns a list of alert dicts sorted by severity.
        """
        alerts: List[Dict[str, Any]] = []

        for name in crypto_agent_names():
            interval = self._intervals.get(name)
            if not interval or interval.total_trades < 10:
                continue

            b = get_benchmark_for(name, self._benchmark)

            # PF below safety floor
            pf = interval.profit_factor
            if pf != float("inf") and pf < 1.1:
                alerts.append({
                    "agent": name,
                    "level": "critical" if pf < 1.0 else "warning",
                    "type": "low_profit_factor",
                    "message": f"{name}: PF={pf:.2f} (floor=1.1, target={b.min_profit_factor})",
                    "value": round(pf, 3),
                    "threshold": 1.1,
                })

            # Negative expectancy
            exp = interval.expectancy_cents
            if exp < 0:
                alerts.append({
                    "agent": name,
                    "level": "critical",
                    "type": "negative_expectancy",
                    "message": f"{name}: expectancy={exp:.1f}c/trade (negative)",
                    "value": round(exp, 2),
                    "threshold": 0.0,
                })

            # Error rate above benchmark
            if interval.error_rate_pct > b.max_error_rate_pct:
                alerts.append({
                    "agent": name,
                    "level": "warning",
                    "type": "high_error_rate",
                    "message": (
                        f"{name}: error_rate={interval.error_rate_pct:.1f}% "
                        f"(max={b.max_error_rate_pct}%)"
                    ),
                    "value": round(interval.error_rate_pct, 2),
                    "threshold": b.max_error_rate_pct,
                })

        # Sort: critical first, then by agent name
        severity_order = {"critical": 0, "warning": 1}
        return sorted(alerts, key=lambda a: (severity_order.get(a["level"], 2), a["agent"]))

    # ── Nightly readiness recompute ───────────────────────────────────

    def promotion_candidates(self) -> List[Dict[str, Any]]:
        """Rank all agents by promotion readiness.

        Returns a sorted list (best candidates first) with:
        - readiness verdict
        - profit factor, expectancy, trade count
        - promotion tier: 'ready', 'close', 'not_ready'
        """
        candidates: List[Dict[str, Any]] = []

        for name in crypto_agent_names():
            interval = self._intervals.get(name)
            if not interval:
                continue

            verdict = self.check_readiness(name)
            b = get_benchmark_for(name, self._benchmark)
            pf = interval.profit_factor
            pf_val = pf if pf != float("inf") else 99.0

            # Classify tier
            passing_checks = sum(1 for v in verdict.checks.values() if v)
            total_checks = len(verdict.checks)
            if verdict.ready:
                tier = "ready"
            elif passing_checks >= total_checks - 2:
                tier = "close"
            else:
                tier = "not_ready"

            candidates.append({
                "agent": name,
                "tier": tier,
                "ready": verdict.ready,
                "passing_checks": passing_checks,
                "total_checks": total_checks,
                "profit_factor": round(pf_val, 3),
                "expectancy_cents": round(interval.expectancy_cents, 2),
                "win_rate_pct": round(interval.win_rate_pct, 1),
                "total_trades": interval.total_trades,
                "drawdown_pct": round(interval.drawdown_pct, 2),
                "net_pnl_usd": round(interval.net_pnl_usd, 2),
                "benchmark_pf": b.min_profit_factor,
                "benchmark_exp": b.min_expectancy_cents,
                "verdict": verdict.to_dict(),
                "is_live": self.is_live(name),
            })

        # Sort: ready first, then by PF descending
        tier_order = {"ready": 0, "close": 1, "not_ready": 2}
        candidates.sort(key=lambda c: (tier_order.get(c["tier"], 3), -c["profit_factor"]))
        return candidates

    def nightly_report(self) -> Dict[str, Any]:
        """Generate a nightly readiness report.

        Intended to be called by a scheduler. Logs warnings for degraded
        cells and returns a structured report with ranked candidates.
        """
        candidates = self.promotion_candidates()
        alerts = self.health_alerts()
        gaps = self.coverage_gap_alerts()

        # Log critical alerts
        for alert in alerts:
            if alert["level"] == "critical":
                logger.warning(f"[nightly] CRITICAL: {alert['message']}")
            else:
                logger.info(f"[nightly] {alert['level'].upper()}: {alert['message']}")

        for gap in gaps[:5]:
            logger.info(f"[nightly] COVERAGE GAP: {gap['message']}")

        ready = [c for c in candidates if c["tier"] == "ready"]
        close = [c for c in candidates if c["tier"] == "close"]

        logger.info(
            f"[nightly] Readiness report: {len(ready)} ready, "
            f"{len(close)} close, {len(alerts)} health alerts, "
            f"{len(gaps)} coverage gaps"
        )

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session_hours": round(self.session_hours, 2),
            "candidates": candidates,
            "ready_count": len(ready),
            "close_count": len(close),
            "health_alerts": alerts,
            "coverage_gaps": gaps,
        }

    # ── Summary ────────────────────────────────────────────────────

    def summary(self) -> Dict[str, Any]:
        """Full session summary for API consumption."""
        total_trades = sum(i.total_trades for i in self._intervals.values())
        total_pnl = sum(i.net_pnl_usd for i in self._intervals.values())
        total_errors = sum(i.errors for i in self._intervals.values())
        total_cb_trips = sum(i.circuit_breaker_trips for i in self._intervals.values())

        readiness = self.check_all_readiness()
        ready_count = sum(1 for v in readiness.values() if v.ready)

        return {
            "session_id": self._session_id,
            "active": self.is_active,
            "session_hours": round(self.session_hours, 2),
            "started_at": (
                datetime.fromtimestamp(self._session_start, tz=timezone.utc).isoformat()
                if self._session_start else None
            ),
            "totals": {
                "trades": total_trades,
                "net_pnl_usd": round(total_pnl, 2),
                "errors": total_errors,
                "circuit_breaker_trips": total_cb_trips,
                "error_rate_pct": round(
                    (total_errors / total_trades * 100) if total_trades else 0, 2
                ),
            },
            "coverage": self.coverage_summary(),
            "readiness": {
                "ready_count": ready_count,
                "total_agents": len(readiness),
                "ready_pct": round(
                    (ready_count / len(readiness) * 100) if readiness else 0, 1
                ),
                "agents": {name: v.to_dict() for name, v in readiness.items()},
            },
            "live_promoted": sorted(self._live_promoted),
            "intervals": {
                name: interval.to_dict()
                for name, interval in sorted(self._intervals.items())
            },
            "benchmark": asdict(self._benchmark),
        }

    # ── Persistence ────────────────────────────────────────────────

    def _save_state(self) -> None:
        try:
            _PERSIST_FILE.parent.mkdir(parents=True, exist_ok=True)
            state = {
                "session_id": self._session_id,
                "session_start": self._session_start,
                "live_promoted": sorted(self._live_promoted),
                "benchmark": asdict(self._benchmark),
                "intervals": {
                    name: asdict(interval)
                    for name, interval in self._intervals.items()
                },
                # BUG-R fix: persist pending paper trades so
                # record_settlement() can find them after a restart.
                "open_trades": self._open_trades,
            }
            _PERSIST_FILE.write_text(json.dumps(state, indent=2, default=str))
        except Exception as e:
            logger.warning(f"[paper-session] Failed to save state: {e}")

    def _load_state(self) -> None:
        if not _PERSIST_FILE.exists():
            return
        try:
            data = json.loads(_PERSIST_FILE.read_text())
            self._session_id = data.get("session_id")
            self._session_start = data.get("session_start")
            self._live_promoted = set(data.get("live_promoted", []))

            for name, idata in data.get("intervals", {}).items():
                self._intervals[name] = IntervalPnL(
                    asset=idata.get("asset", ""),
                    timeframe=idata.get("timeframe", ""),
                    agent_name=idata.get("agent_name", name),
                    total_trades=idata.get("total_trades", 0),
                    winning_trades=idata.get("winning_trades", 0),
                    losing_trades=idata.get("losing_trades", 0),
                    gross_pnl_cents=idata.get("gross_pnl_cents", 0.0),
                    gross_wins_cents=idata.get("gross_wins_cents", 0.0),
                    gross_losses_cents=idata.get("gross_losses_cents", 0.0),
                    fees_cents=idata.get("fees_cents", 0.0),
                    net_pnl_cents=idata.get("net_pnl_cents", 0.0),
                    high_water_mark_cents=idata.get("high_water_mark_cents", 0.0),
                    max_drawdown_cents=idata.get("max_drawdown_cents", 0.0),
                    errors=idata.get("errors", 0),
                    circuit_breaker_trips=idata.get("circuit_breaker_trips", 0),
                    first_trade_at=idata.get("first_trade_at"),
                    last_trade_at=idata.get("last_trade_at"),
                    last_updated=idata.get("last_updated"),
                    daily_loss_cents=idata.get("daily_loss_cents", 0.0),
                    daily_reset_date=idata.get("daily_reset_date"),
                    weekly_loss_cents=idata.get("weekly_loss_cents", 0.0),
                    weekly_reset_date=idata.get("weekly_reset_date"),
                    halted=idata.get("halted", False),
                    downsized=idata.get("downsized", False),
                    halt_reason=idata.get("halt_reason"),
                )

            # BUG-R fix: restore pending open trades from disk.
            self._open_trades = data.get("open_trades", {})

            logger.info(
                f"[paper-session] Restored session {self._session_id}: "
                f"{len(self._intervals)} intervals, "
                f"{len(self._live_promoted)} live-promoted, "
                f"{sum(len(v) for v in self._open_trades.values())} open trades"
            )
        except Exception as e:
            logger.warning(f"[paper-session] Failed to load state: {e}")


# ── Singleton ──────────────────────────────────────────────────────────

_session: Optional[PaperSession] = None
# TEMPORARILY DISABLED: threading.Lock causing deadlock during startup
# TODO: Re-enable lock after startup is stable and investigate proper async synchronization
# _session_lock = threading.Lock()
_session_lock = None  # Disabled to prevent startup hang


def get_paper_session() -> PaperSession:
    """Return the module-level PaperSession singleton."""
    global _session
    if _session is None:
        if _session_lock is not None:
            with _session_lock:
                if _session is None:
                    _session = PaperSession()
        else:
            # Lock disabled - direct initialization (startup workaround)
            _session = PaperSession()
    return _session
