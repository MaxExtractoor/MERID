"""Take-Profit Manager for Kalshi binary contracts.

Implements a fee-aware, per-asset/timeframe configurable take-profit and
optional trailing take-profit layer, with round-trip capping for re-entry
control.

Architecture:
    - ``TakeProfitConfig``  — per-agent configuration dataclass loaded from YAML
    - ``FeesModel``         — Kalshi fee estimation; computes net edge after costs
    - ``TakeProfitState``   — enum: INACTIVE | ARMED_PRIMARY | TRAILING_ACTIVE | CLOSED
    - ``TakeProfitPositionState`` — per-position mutable state (peak price, round trips)
    - ``TakeProfitAction``  — action returned to the caller (CLOSE_PARTIAL | CLOSE_FULL)
    - ``TakeProfitManager`` — main engine; stateless across processes except for the
                              in-memory ``_states`` registry

Control flow (called from KalshiTradingAgent._check_stop_losses per cycle):
    1. Refresh current_price_cents from KalshiMarketStateStore (done by the agent)
    2. agent calls ``tp_manager.on_price_update(pos, bid_cents, ask_cents)``
    3. Manager returns ``TakeProfitAction`` or ``None``
    4. Agent routes the action as an ``OrderIntent`` through route_order_async
    5. On fill confirmation: agent calls ``tp_manager.on_fill(pos_id, filled_contracts)``
    6. On full close: agent calls ``tp_manager.on_position_closed(ticker, close_reason)``
    7. Before re-entry: agent calls ``tp_manager.can_reenter(ticker, current_price_cents)``

Global kill switch / risk-off:
    - TP exits (CLOSE_PARTIAL, CLOSE_FULL) are always allowed (reduce risk).
    - Re-entry (can_reenter) returns False when the system-level kill switch is active.
    - Caller must enforce this check independently; TakeProfitManager defers to caller.

Staleness guard:
    - If ``pos.current_price_cents == 0`` the price is considered stale and no
      TP action is emitted.  Caller must set a valid price before calling
      on_price_update.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Literal, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.take_profit")


# ── Kalshi fee formula ─────────────────────────────────────────────────────

class FeesModel:
    """Kalshi trading fee estimator.

    Kalshi charges: fee = ceil(0.07 × C × P × (1−P)) cents per leg
    where C = contracts, P = price in dollars [0, 1].

    For a complete round trip (buy then sell), total fees are:
        fee_buy + fee_sell

    Usage::
        fm = FeesModel()
        cost = fm.estimate_round_trip_cost(entry_cents=30, exit_cents=50, contracts=10)
        edge  = fm.estimate_edge_after_costs(30, 50, 10, side="yes")
    """

    # Kalshi tiered fee rates as of 2025:
    #   1-99 contracts:  7%
    #   100-999:         5%
    #   1000+:           3%
    KALSHI_FEE_RATE: float = 0.07  # base rate (tier <100)

    @staticmethod
    def _fee_rate(contracts: int) -> float:
        """Return tiered fee rate for a given contract count."""
        if contracts < 100:
            return 0.07
        elif contracts < 1000:
            return 0.05
        return 0.03

    def fee_cents(self, price_cents: int, contracts: int) -> float:
        """One-leg fee in cents (exact Kalshi parabolic formula, always rounded up).

        Uses tiered rates and a 2¢-per-contract floor.
        """
        if contracts <= 0 or price_cents <= 0 or price_cents >= 100:
            return 0
        rate = self._fee_rate(contracts)
        p = price_cents / 100.0
        raw = rate * contracts * p * (1.0 - p)
        return max(2, math.ceil(raw * 100))

    def estimate_round_trip_cost(
        self,
        entry_cents: int,
        exit_cents: int,
        contracts: int,
    ) -> float:
        """Total fee in cents for a full buy→sell round trip."""
        return self.fee_cents(entry_cents, contracts) + self.fee_cents(exit_cents, contracts)

    def estimate_edge_after_costs(
        self,
        entry_cents: int,
        exit_cents: int,
        contracts: int,
        side: str = "yes",
    ) -> float:
        """Net profit in cents after round-trip fees, for a single contract.

        For YES: profit = (exit - entry) × contracts − fees
        For NO:  profit = (entry - exit) × contracts − fees
        """
        if side == "yes":
            gross = (exit_cents - entry_cents) * contracts
        else:
            gross = (entry_cents - exit_cents) * contracts
        fees = self.estimate_round_trip_cost(entry_cents, exit_cents, contracts)
        return gross - fees

    def min_profitable_exit_cents(
        self,
        entry_cents: int,
        contracts: int,
        side: str = "yes",
        min_net_cents: float = 2.0,
    ) -> int:
        """Minimum exit price (in cents) required to yield at least min_net_cents profit.

        Returns the entry price itself if the calculation is infeasible (fee > any gain).
        """
        # Iterate from entry ± 1 cent outward until edge > min_net_cents
        if side == "yes":
            for delta in range(1, 100 - entry_cents + 1):
                exit_c = entry_cents + delta
                if self.estimate_edge_after_costs(entry_cents, exit_c, contracts, side) >= min_net_cents:
                    return exit_c
        else:
            # range(1, entry_cents + 1) to be symmetric with YES side: includes delta=entry_cents
            # so that exit_c=0 (full NO resolution) is also a valid candidate TP price.
            for delta in range(1, entry_cents + 1):
                exit_c = entry_cents - delta
                if self.estimate_edge_after_costs(entry_cents, exit_c, contracts, side) >= min_net_cents:
                    return exit_c
        return entry_cents  # fallback: at least break even


_DEFAULT_FEES_MODEL = FeesModel()


# ── Configuration ──────────────────────────────────────────────────────────

@dataclass
class TakeProfitConfig:
    """Per-agent take-profit configuration.

    All prices / distances are in cents (integer 1–99).  Fractions are 0–1.

    Field naming follows the spec:
      tp_r_multiple_primary        — R = entry for YES, (100-entry) for NO.
                                     Close scale_out_fraction when profit hits this multiple.
      tp_pct_of_max_gain_primary  — Alternative: close when gain is this % of max possible
                                     gain.  If both are set, the less-aggressive (lower) target wins.
      tp_min_cents                — Absolute minimum profit in cents required to fire TP;
                                     prevents triggering inside the spread or below fee cost.
      tp_scale_out_fraction       — Fraction of position to exit at primary TP (0.5 = half).
      tp_trailing_enabled         — Enable trailing TP on the remaining size.
      tp_trailing_activation_r_multiple — R-multiple at which trailing starts tracking.
                                          Usually same as primary.
      tp_trailing_giveback_cents  — Cents of giveback from peak before trailing closes remainder.
      tp_max_round_trips_per_contract — Max open→close→reopen cycles per contract ticker.
      tp_min_price_move_for_reentry — Min cents of additional price move from last exit
                                       before re-entry is allowed.
      tp_min_edge_after_fees_cents — Min net cents profit after estimated fees per contract;
                                      TP is suppressed (INACTIVE) when the target would yield less.
    """
    tp_enabled: bool = True

    # Primary TP target — R-multiple (0 = disable this mode)
    # OPTIMIZED (2026-05-10): 15m uses 0.4 with time-based dynamic adjustment
    tp_r_multiple_primary: float = 0.4

    # Primary TP target — fraction of max possible gain (0.0 = disable this mode)
    tp_pct_of_max_gain_primary: float = 0.0

    # Minimum absolute profit cents to allow TP to fire
    # OPTIMIZED (2026-05-10): 15m reduced from 5 to 3 cents
    tp_min_cents: int = 3

    # Fraction of position sold at primary TP
    tp_scale_out_fraction: float = 0.5

    # Trailing stop on the remainder
    tp_trailing_enabled: bool = True
    # OPTIMIZED (2026-05-10): 15m reduced from 0.5 to 0.3
    tp_trailing_activation_r_multiple: float = 0.3
    tp_trailing_giveback_cents: int = 5

    # Fee floor
    tp_min_edge_after_fees_cents: float = 2.0

    # ═══════════════════════════════════════════════════════════════════════════
    # Entry/Exit Timing Precision (REGRESSION PROTECTION)
    # ═══════════════════════════════════════════════════════════════════════════
    
    # Maximum acceptable latency from signal generation to entry execution (seconds)
    # If entry is delayed beyond this, position is NOT opened (prevents stale entries)
    max_entry_latency_seconds: float = 5.0
    
    # Maximum acceptable latency from TP trigger to exit execution (seconds)
    # If exit is delayed beyond this, emergency exit is triggered at market
    max_exit_latency_seconds: float = 3.0
    
    # Require entry execution timestamp to be within this many seconds of signal
    require_entry_timestamp_validation: bool = True
    
    # Require exit execution timestamp to be within this many seconds of TP trigger
    require_exit_timestamp_validation: bool = True
    # PnL-based hard take-profit (new)
    # ═══════════════════════════════════════════════════════════════════════════
    # Hard TP: close full position when unrealized PnL % reaches this threshold
    tp_min_unrealized_pct_hard_close: float = 100.0  # 100% = double your money
    # Partial TP: close partial when unrealized PnL % reaches this threshold
    tp_min_unrealized_pct_partial: float = 50.0  # 50% gain for scale-out

    # ═══════════════════════════════════════════════════════════════════════════
    # Dynamic trailing giveback based on PnL % (new)
    # ═══════════════════════════════════════════════════════════════════════════
    # Once unrealized PnL exceeds trailing_pct_activation_unrealized,
    # use percentage-based giveback instead of fixed cents
    trailing_giveback_pct_after_unrealized: float = 20.0  # 20% giveback from peak
    trailing_pct_activation_unrealized: float = 80.0  # activate at 80% PnL

    # ═══════════════════════════════════════════════════════════════════════════
    # Re-entry gating
    # ═══════════════════════════════════════════════════════════════════════════
    # Round-trip cap per contract - reset on contract expiry or daily
    tp_max_round_trips_per_contract: int = 2
    # Min price move from last exit before re-entry allowed
    tp_min_price_move_for_reentry: int = 5
    # Daily reset for round trips (if True, reset at midnight UTC)
    tp_round_trips_reset_daily: bool = True


# Conservative defaults that activate TP but are not hyper-aggressive.
DEFAULT_TP_CONFIG = TakeProfitConfig()

# Per-asset/timeframe presets — factory functions consumed by get_tp_config_for_agent()
def _btc_15m_config() -> TakeProfitConfig:
    """15m scalper config — aligned with 5% conservative edge threshold (2026-05-10).

    With 5% min entry edge, 0.40R gives ~2% profit target instead of 1.25%.
    Reduced scale-out and widened giveback to let more profit run.
    """
    return TakeProfitConfig(
        tp_enabled=True,
        tp_r_multiple_primary=0.40,       # RAISED from 0.25 → 0.40 (2% TP on 5% edge entries)
        tp_pct_of_max_gain_primary=0.0,   # disabled — use R-multiple only
        tp_min_cents=4,                    # need 4¢ minimum profit
        tp_scale_out_fraction=0.70,       # LOOSENED from 0.80 → 0.70 (let 30% trail for bigger wins)
        tp_trailing_enabled=True,
        tp_trailing_activation_r_multiple=0.40,  # trail activates at same R as primary
        tp_trailing_giveback_cents=4,     # WIDENED from 3 → 4 (allow more room for moves)
        tp_max_round_trips_per_contract=3,  # 3 round-trips max per contract
        tp_min_price_move_for_reentry=4,  # 4¢ min move before re-entry
        tp_min_edge_after_fees_cents=1.5,  # must net 1.5¢ after fees
    )

def _eth_15m_config() -> TakeProfitConfig:
    c = _btc_15m_config()
    c.tp_r_multiple_primary = 0.45      # ETH slightly wider than BTC (higher vol)
    c.tp_trailing_giveback_cents = 5    # wider giveback for ETH volatility
    return c

def _sol_15m_config() -> TakeProfitConfig:
    """15m scalper config for SOL — aligned with 5.5% edge threshold (2026-05-10).

    SOL higher volatility → slightly wider TP and giveback than BTC/ETH.
    """
    return TakeProfitConfig(
        tp_enabled=True,
        tp_r_multiple_primary=0.48,       # RAISED from 0.30 → 0.48 (2.6% TP on 5.5% edge)
        tp_min_cents=5,                    # 5¢ minimum (higher vol → wider floor)
        tp_scale_out_fraction=0.70,       # LOOSENED from 0.75 → 0.70 (let more trail)
        tp_trailing_enabled=True,
        tp_trailing_activation_r_multiple=0.48,  # trail at same R as primary
        tp_trailing_giveback_cents=5,     # 5¢ giveback (SOL vol needs room)
        tp_max_round_trips_per_contract=2,  # TIGHTENED from 3 → 2 (fewer re-entries)
        tp_min_price_move_for_reentry=5,   # 5¢ min move before re-entry
        tp_min_edge_after_fees_cents=2.0,  # must net 2¢ after fees
    )

def _xrp_15m_config() -> TakeProfitConfig:
    """15m scalper config for XRP — aligned with 5.7% edge threshold (2026-05-10)."""
    c = _sol_15m_config()
    c.tp_r_multiple_primary = 0.50       # RAISED from 0.35 → 0.50 (2.9% TP on 5.7% edge)
    c.tp_trailing_activation_r_multiple = 0.50
    c.tp_trailing_giveback_cents = 5    # same as SOL
    return c

def _doge_15m_config() -> TakeProfitConfig:
    """15m scalper config for DOGE — aligned with 6.0% edge threshold (2026-05-10).

    Meme-coin volatility → widest bands, but R-multiple raised to match entry edge.
    Take 65% at tier 1 (take more profit earlier on riskiest asset).
    """
    return TakeProfitConfig(
        tp_enabled=True,
        tp_r_multiple_primary=0.52,                # RAISED from 0.50 → 0.52 (3.1% TP on 6% edge)
        tp_min_cents=5,                            # 5¢ minimum profit to trigger
        tp_scale_out_fraction=0.65,                # take 65% at tier 1 (riskiest asset)
        tp_trailing_enabled=True,
        tp_trailing_activation_r_multiple=0.52,    # trail at same R as primary
        tp_trailing_giveback_cents=6,              # widest giveback — highest vol asset
        tp_max_round_trips_per_contract=2,         # TIGHTENED from 4 → 2 (meme-coin chop is expensive)
        tp_min_price_move_for_reentry=8,           # widest re-entry hysteresis
        tp_min_edge_after_fees_cents=2.0,          # higher fee floor due to vol
    )

def _hourly_config(asset: str) -> TakeProfitConfig:
    """Hourly contracts: wider giveback, slightly higher R-multiple."""
    c = TakeProfitConfig(
        tp_enabled=True,
        tp_r_multiple_primary=0.6,
        tp_min_cents=6,
        tp_scale_out_fraction=0.5,
        tp_trailing_enabled=True,
        tp_trailing_activation_r_multiple=0.6,
        tp_trailing_giveback_cents=8,
        tp_max_round_trips_per_contract=2,
        tp_min_price_move_for_reentry=6,
        tp_min_edge_after_fees_cents=2.0,
    )
    if asset in ("SOL", "XRP"):
        c.tp_r_multiple_primary = 0.7
        c.tp_trailing_giveback_cents = 10
    return c

def _daily_config(asset: str) -> TakeProfitConfig:
    return TakeProfitConfig(
        tp_enabled=True,
        tp_r_multiple_primary=0.65,
        tp_min_cents=8,
        tp_scale_out_fraction=0.5,
        tp_trailing_enabled=True,
        tp_trailing_activation_r_multiple=0.65,
        tp_trailing_giveback_cents=10,
        tp_max_round_trips_per_contract=1,
        tp_min_price_move_for_reentry=8,
        tp_min_edge_after_fees_cents=3.0,
    )

def _weekly_config(asset: str) -> TakeProfitConfig:
    c = _daily_config(asset)
    c.tp_r_multiple_primary = 0.7
    c.tp_min_cents = 10
    c.tp_trailing_giveback_cents = 12
    c.tp_max_round_trips_per_contract = 1
    return c

def _monthly_annual_config(asset: str) -> TakeProfitConfig:
    c = _weekly_config(asset)
    c.tp_r_multiple_primary = 0.75
    c.tp_min_cents = 12
    c.tp_trailing_giveback_cents = 15
    c.tp_max_round_trips_per_contract = 1
    c.tp_min_price_move_for_reentry = 10
    return c


# Agent name → TakeProfitConfig lookup (fallback: DEFAULT_TP_CONFIG)
_AGENT_TP_PRESETS: Dict[str, TakeProfitConfig] = {
    "BTC_15M":    _btc_15m_config(),
    "BTC_HOURLY": _hourly_config("BTC"),
    "BTC_DAILY":  _daily_config("BTC"),
    "BTC_WEEKLY": _weekly_config("BTC"),
    "BTC_MONTHLY": _monthly_annual_config("BTC"),
    "BTC_ANNUAL": _monthly_annual_config("BTC"),
    "ETH_15M":    _eth_15m_config(),
    "ETH_HOURLY": _hourly_config("ETH"),
    "ETH_DAILY":  _daily_config("ETH"),
    "ETH_WEEKLY": _weekly_config("ETH"),
    "ETH_MONTHLY": _monthly_annual_config("ETH"),
    "ETH_ANNUAL": _monthly_annual_config("ETH"),
    "SOL_15M":    _sol_15m_config(),
    "SOL_HOURLY": _hourly_config("SOL"),
    "SOL_DAILY":  _daily_config("SOL"),
    "SOL_WEEKLY": _weekly_config("SOL"),
    "XRP_15M":    _xrp_15m_config(),
    "XRP_HOURLY": _hourly_config("XRP"),
    "XRP_DAILY":  _daily_config("XRP"),
    "XRP_WEEKLY": _weekly_config("XRP"),
    "XRP_MONTHLY": _monthly_annual_config("XRP"),
    "XRP_ANNUAL": _monthly_annual_config("XRP"),
    "SOL_MONTHLY": _monthly_annual_config("SOL"),
    "SOL_ANNUAL": _monthly_annual_config("SOL"),
    "DOGE_15M":    _doge_15m_config(),
    "DOGE_HOURLY": _hourly_config("DOGE"),
    "DOGE_DAILY":  _daily_config("DOGE"),
    "DOGE_WEEKLY": _weekly_config("DOGE"),
    "DOGE_MONTHLY": _monthly_annual_config("DOGE"),
    "DOGE_ANNUAL": _monthly_annual_config("DOGE"),
}


def get_tp_config_for_agent(agent_name: str) -> TakeProfitConfig:
    """Return the TakeProfitConfig for a given agent name.

    Looks up the preset table first; falls back to the conservative default.
    The YAML ``take_profit:`` block (if present) should override this via
    ``TakeProfitConfig`` field merges in the agent_grid_config parser.
    """
    key = (agent_name or "").upper().strip()
    return _AGENT_TP_PRESETS.get(key, DEFAULT_TP_CONFIG)


def tp_config_from_yaml(raw: dict, base: Optional[TakeProfitConfig] = None) -> TakeProfitConfig:
    """Build a TakeProfitConfig from a YAML ``take_profit:`` dict.

    Merges raw overrides onto a base config (or DEFAULT_TP_CONFIG).
    Unknown keys are silently ignored.
    """
    cfg = base or TakeProfitConfig()
    if not raw:
        return cfg
    _bool = lambda v: str(v).lower() in ("true", "1", "yes")
    mapping = {
        "enabled":                    ("tp_enabled",                         _bool),
        "r_multiple_primary":         ("tp_r_multiple_primary",              float),
        "pct_of_max_gain_primary":    ("tp_pct_of_max_gain_primary",         float),
        "min_cents":                  ("tp_min_cents",                       int),
        "scale_out_fraction":         ("tp_scale_out_fraction",              float),
        "trailing_enabled":           ("tp_trailing_enabled",                _bool),
        "trailing_activation_r_multiple": ("tp_trailing_activation_r_multiple", float),
        "trailing_giveback_cents":    ("tp_trailing_giveback_cents",         int),
        "max_round_trips_per_contract": ("tp_max_round_trips_per_contract",  int),
        "min_price_move_for_reentry": ("tp_min_price_move_for_reentry",      int),
        "min_edge_after_fees_cents":  ("tp_min_edge_after_fees_cents",       float),
        # PnL-based hard TP (new)
        "min_unrealized_pct_hard_close": ("tp_min_unrealized_pct_hard_close", float),
        "min_unrealized_pct_partial": ("tp_min_unrealized_pct_partial",      float),
        # Dynamic trailing giveback (new)
        "trailing_giveback_pct_after_unrealized": ("trailing_giveback_pct_after_unrealized", float),
        "trailing_pct_activation_unrealized": ("trailing_pct_activation_unrealized", float),
        # Daily reset (new)
        "round_trips_reset_daily":    ("tp_round_trips_reset_daily",         _bool),
    }
    for yaml_key, (field_name, cast) in mapping.items():
        val = raw.get(yaml_key)
        if val is not None:
            try:
                setattr(cfg, field_name, cast(val))
            except (ValueError, TypeError) as e:
                logger.warning("take_profit YAML: bad value for %s=%r: %s", yaml_key, val, e)
    return cfg


# ── State machine ──────────────────────────────────────────────────────────

class TakeProfitState(str, Enum):
    """Per-position TP state machine states."""
    INACTIVE        = "inactive"        # TP disabled or target infeasible
    ARMED_PRIMARY   = "armed_primary"   # Waiting for primary TP target
    TRAILING_ACTIVE = "trailing_active" # Remainder under trailing watch
    CLOSED          = "closed"          # TP complete; no further action


@dataclass
class TakeProfitPositionState:
    """Mutable per-position state maintained by TakeProfitManager."""
    position_id: str
    ticker: str
    side: str                       # "yes" or "no"
    entry_price_cents: int
    total_contracts: int            # original size
    remaining_contracts: int        # after partial exits

    # Computed targets
    tp_state: TakeProfitState = TakeProfitState.ARMED_PRIMARY
    primary_target_cents: int = 0   # YES price target for primary TP trigger

    # Trailing
    peak_price_cents: int = 0       # best price reached since trailing activated
    peak_unrealized_pct: float = 0.0  # best unrealized PnL % reached (for dynamic giveback)

    # Re-entry tracking
    round_trips: int = 0            # completed TP round trips for this ticker
    last_exit_price_cents: int = 0  # price at which last TP close happened

    # Idempotency: last action time to avoid double-firing
    last_action_ts: float = 0.0
    pending_fill: bool = False      # True after order placed, before fill confirmed

    # ═══════════════════════════════════════════════════════════════════════
    # Entry/Exit Timing Precision (REGRESSION PROTECTION)
    # ═══════════════════════════════════════════════════════════════════════
    # These timestamps enable validation that entry/exit executed within
    # acceptable latency windows to prevent stale signal execution
    
    # UTC timestamp when signal was generated (for entry timing validation)
    signal_generated_ts: Optional[float] = None
    
    # UTC timestamp when entry was executed (for latency measurement)
    entry_executed_ts: Optional[float] = None
    
    # UTC timestamp when TP trigger was evaluated (for exit timing validation)
    tp_trigger_ts: Optional[float] = None
    
    # UTC timestamp when exit was executed (for latency measurement)
    exit_executed_ts: Optional[float] = None

    # Diagnostics
    created_ts: float = field(default_factory=time.time)


# ── Action ─────────────────────────────────────────────────────────────────

@dataclass
class TakeProfitAction:
    """Action proposed by TakeProfitManager to the calling agent.

    The agent is responsible for translating this into an OrderIntent
    and routing it through route_order_async.

    Attributes:
        position_id: Unique position identifier
        ticker: Kalshi market ticker
        side: "yes" or "no" (same as the open position — seller closes)
        action_type: "CLOSE_PARTIAL" or "CLOSE_FULL"
        quantity: Number of contracts to close
        limit_price_cents: Suggested limit price for the close order.
            For YES closes (action="sell"): bid_cents (sell to bid).
            For NO closes (action="sell"): ask_cents (buy YES back at ask — inverted).
        reason: Human-readable trigger description
    """
    position_id: str
    ticker: str
    side: str
    action_type: Literal["CLOSE_PARTIAL", "CLOSE_FULL"]
    quantity: int
    limit_price_cents: int
    reason: str


# ── Round-trip registry ────────────────────────────────────────────────────

@dataclass
class _TickerRoundTripRecord:
    """Per-ticker round-trip counter with last-exit price tracking."""
    round_trips: int = 0
    last_exit_price_cents: int = 0
    last_exit_ts: float = 0.0

    # Contract identification for expiry-based reset
    contract_id: str = ""  # market_id or ticker to detect contract changes
    contract_expiry_ts: float = 0.0  # expiry timestamp for TTL
    last_reset_day: str = ""  # YYYY-MM-DD for daily reset tracking

    # Idempotency tracking to prevent double-counting from race conditions
    # (e.g., hard TP fires AND settlement arrives simultaneously)
    _processed_reasons: set = field(default_factory=set)


# ── Main engine ────────────────────────────────────────────────────────────

class TakeProfitManager:
    """Fee-aware, trailing-capable take-profit manager.

    One instance per KalshiTradingAgent.  Thread-safe via no shared state
    across agents; each agent owns its own instance.

    Configuration is supplied once at construction and can be overridden
    per-call via the ``config`` argument to ``on_price_update``.

    Usage (from KalshiTradingAgent._check_stop_losses)::

        # After fill registration:
        tp_manager.on_position_open(pos)

        # Each cycle, after refreshing current_price_cents:
        for pos_id, pos in self._tracked_positions.items():
            bid = market_state.best_bid_cents
            ask = market_state.best_ask_cents
            action = tp_manager.on_price_update(pos, bid, ask)
            if action:
                ... route as OrderIntent ...

        # After TP fill confirmed:
        tp_manager.on_fill(pos_id, filled_contracts)

        # After full position close (any reason):
        tp_manager.on_position_closed(ticker, reason)

        # Before new entry:
        if not tp_manager.can_reenter(ticker, current_price_cents):
            ... skip entry ...
    """

    def __init__(
        self,
        config: Optional[TakeProfitConfig] = None,
        fees_model: Optional[FeesModel] = None,
    ) -> None:
        self._config = config or DEFAULT_TP_CONFIG
        self._fees = fees_model or _DEFAULT_FEES_MODEL

        # position_id → TakeProfitPositionState
        self._states: Dict[str, TakeProfitPositionState] = {}

        # ticker → _TickerRoundTripRecord  (shared across position_ids per contract)
        self._round_trips: Dict[str, _TickerRoundTripRecord] = {}

        # Debounce: minimum seconds between successive TP actions on same position
        self._min_action_interval_s: float = 2.0

    # ── Lifecycle hooks ────────────────────────────────────────────────

    def on_position_open(self, pos: "TrackedPosition") -> None:  # noqa: F821
        """Register a newly filled position with the TP state machine.

        Computes the primary TP target and sets initial state.
        Idempotent: calling again for the same position_id is a no-op.
        """
        if pos.position_id in self._states:
            return  # already tracking

        cfg = self._config
        if not cfg.tp_enabled:
            self._states[pos.position_id] = TakeProfitPositionState(
                position_id=pos.position_id,
                ticker=pos.ticker,
                side=pos.side,
                entry_price_cents=pos.entry_price_cents,
                total_contracts=pos.contracts,
                remaining_contracts=pos.contracts,
                tp_state=TakeProfitState.INACTIVE,
            )
            logger.debug(
                "[TP] %s: tp_enabled=False → INACTIVE", pos.ticker
            )
            return

        target_cents = self._compute_primary_target(
            entry_price_cents=pos.entry_price_cents,
            side=pos.side,
            cfg=cfg,
            contracts=pos.contracts,
        )

        if target_cents is None:
            state = TakeProfitState.INACTIVE
            target_cents = 0
        else:
            state = TakeProfitState.ARMED_PRIMARY

        ps = TakeProfitPositionState(
            position_id=pos.position_id,
            ticker=pos.ticker,
            side=pos.side,
            entry_price_cents=pos.entry_price_cents,
            total_contracts=pos.contracts,
            remaining_contracts=pos.contracts,
            tp_state=state,
            primary_target_cents=target_cents,
        )
        self._states[pos.position_id] = ps

        # Clear processed reasons for this ticker to allow new round trip closes
        # (idempotency is per-round-trip, not global per ticker)
        if pos.ticker in self._round_trips:
            self._round_trips[pos.ticker]._processed_reasons.clear()

        logger.info(
            "[TP] %s: opened %s@%dc × %d → state=%s target=%dc",
            pos.ticker, pos.side, pos.entry_price_cents,
            pos.contracts, state.value, target_cents,
        )

    def on_price_update(
        self,
        pos: "TrackedPosition",  # noqa: F821
        bid_cents: int,
        ask_cents: int,
        config: Optional[TakeProfitConfig] = None,
    ) -> Optional[TakeProfitAction]:
        """Evaluate TP conditions and return an action if one should fire.

        Called each cycle after refreshing pos.current_price_cents.

        Args:
            pos:        The TrackedPosition with up-to-date current_price_cents
            bid_cents:  Best bid in cents (used as exit price for YES closes)
            ask_cents:  Best ask in cents (used as exit price for NO closes)
            config:     Optional per-call config override (uses self._config otherwise)

        Returns:
            TakeProfitAction if an exit should be placed, else None.

        Notes:
            - Returns None if price is stale (current_price_cents == 0).
            - Returns None if a previous action is still pending fill.
            - Does not mutate pos; only mutates internal TakeProfitPositionState.
        """
        if pos.current_price_cents == 0:
            return None  # stale price — never fire on unknown price

        if pos.position_id not in self._states:
            self.on_position_open(pos)

        ps = self._states[pos.position_id]
        cfg = config or self._config

        if ps.tp_state in (TakeProfitState.INACTIVE, TakeProfitState.CLOSED):
            return None

        mid_cents = (bid_cents + ask_cents) // 2 if (bid_cents > 0 and ask_cents > 0) else pos.current_price_cents

        # ═══════════════════════════════════════════════════════════════════
        # PnL-based hard take-profit check (NEW)
        # Check for 100%+ unrealized gains before any other logic
        # ═══════════════════════════════════════════════════════════════════
        unrealized_pct = self._calc_unrealized_pct(ps, mid_cents)
        ps.peak_unrealized_pct = max(ps.peak_unrealized_pct, unrealized_pct)

        # Log high unrealized PnL for monitoring (smoke test verification)
        if unrealized_pct >= 80.0:
            logger.info(
                "[TP-PnL] %s: unrealized_pnl=%.1f%% (peak=%.1f%%) entry=%dc current=%dc state=%s",
                ps.ticker, unrealized_pct, ps.peak_unrealized_pct,
                ps.entry_price_cents, mid_cents, ps.tp_state.value
            )

        # Hard TP: 100%+ unrealized PnL → close full immediately
        if unrealized_pct >= cfg.tp_min_unrealized_pct_hard_close:
            logger.info(
                "[TP-HARD] %s: HARD TP triggered — unrealized_pnl=%.1f%% >= %.1f%%",
                ps.ticker, unrealized_pct, cfg.tp_min_unrealized_pct_hard_close
            )
            return self._create_hard_tp_action(ps, mid_cents, bid_cents, ask_cents, unrealized_pct, cfg)

        # Partial TP: 50%+ unrealized PnL in ARMED_PRIMARY state → scale out
        if (ps.tp_state == TakeProfitState.ARMED_PRIMARY and
            unrealized_pct >= cfg.tp_min_unrealized_pct_partial):
            logger.info(
                "[TP-PARTIAL] %s: partial TP via PnL — unrealized_pnl=%.1f%% >= %.1f%%",
                ps.ticker, unrealized_pct, cfg.tp_min_unrealized_pct_partial
            )
            return self._check_primary(ps, mid_cents, bid_cents, ask_cents, cfg, force_trigger=True)

        # ═══════════════════════════════════════════════════════════════════
        # FVG Exit Timing: Check for opposing FVG approaching (resistance/support)
        # ═══════════════════════════════════════════════════════════════════
        try:
            from merid.prediction.fvg_integration import get_fvg_entry_exit_timing, is_fvg_enabled
            if is_fvg_enabled():
                fvg_timing = get_fvg_entry_exit_timing(
                    ticker=ps.ticker,
                    bid=bid_cents / 100.0,
                    ask=ask_cents / 100.0,
                )
                if fvg_timing and fvg_timing.should_exit and fvg_timing.exit_urgency >= 0.8:
                    # FVG signals high urgency exit - treat as partial TP trigger
                    logger.info(
                        "[TP-FVG-EXIT] %s: FVG exit trigger — exit_urgency=%.2f target=%.1fc reason=%s",
                        ps.ticker, fvg_timing.exit_urgency, 
                        fvg_timing.target_price_cents or 0, fvg_timing.reason
                    )
                    return self._check_primary(ps, mid_cents, bid_cents, ask_cents, cfg, force_trigger=True)
        except Exception as e:
            logger.debug("FVG exit timing check skipped for %s: %s", ps.ticker, e)

        # Always update trailing peak before any debounce gate so the high-water
        # mark is correct even when no action fires this cycle.
        if ps.tp_state == TakeProfitState.TRAILING_ACTIVE and not ps.pending_fill:
            self._update_trailing_peak(ps, mid_cents, bid_cents, ask_cents, unrealized_pct, cfg)

        if ps.pending_fill:
            return None  # idempotency: wait for fill confirmation

        now = time.time()
        if now - ps.last_action_ts < self._min_action_interval_s:
            return None  # debounce

        if ps.tp_state == TakeProfitState.ARMED_PRIMARY:
            return self._check_primary(ps, mid_cents, bid_cents, ask_cents, cfg)

        if ps.tp_state == TakeProfitState.TRAILING_ACTIVE:
            return self._check_trailing_action(ps, mid_cents, bid_cents, ask_cents, cfg)

        return None

    def on_fill(self, position_id: str, filled_contracts: int) -> None:
        """Reconcile a TP fill — update remaining size and advance state.

        Args:
            position_id:      Position identifier (matches TrackedPosition.position_id)
            filled_contracts: Contracts actually filled (may be partial)
        """
        ps = self._states.get(position_id)
        if not ps:
            return

        ps.pending_fill = False
        ps.remaining_contracts = max(0, ps.remaining_contracts - filled_contracts)
        # Reset debounce timer so the next cycle can immediately evaluate
        # the trailing condition (or a new primary target on the remainder).
        ps.last_action_ts = 0.0

        logger.info(
            "[TP] %s: fill confirmed %d contracts → remaining=%d state=%s",
            ps.ticker, filled_contracts, ps.remaining_contracts, ps.tp_state.value,
        )

        if ps.remaining_contracts <= 0:
            ps.tp_state = TakeProfitState.CLOSED
            logger.info("[TP] %s: position CLOSED (no remaining contracts)", ps.ticker)

    def on_position_closed(self, ticker: str, close_reason: str) -> None:
        """Called when a position is fully closed (any reason: TP, SL, expiry).

        Updates the round-trip counter and last-exit-price for re-entry gating.
        Cleans up state for positions whose state machine is already at CLOSED.

        Idempotent: calling multiple times for the same close_reason is safe
        (round trips are only counted once per unique close_reason per ticker).

        Args:
            ticker:       Market ticker
            close_reason: Human-readable reason (e.g., "take_profit_primary",
                          "take_profit_trailing", "stop_loss", "expiry")
        """
        # ═══════════════════════════════════════════════════════════════════
        # Idempotency: track which close_reasons we've already processed
        # to prevent double-counting round trips from race conditions
        # (e.g., hard TP fires AND settlement arrives simultaneously)
        # ═══════════════════════════════════════════════════════════════════
        rec = self._round_trips.setdefault(ticker, _TickerRoundTripRecord())

        # Check if we've already processed this exact close_reason
        if close_reason in rec._processed_reasons:
            logger.debug(
                "[TP] %s: on_position_closed('%s') already processed — skipping idempotently",
                ticker, close_reason
            )
            return

        # Mark this reason as processed
        rec._processed_reasons.add(close_reason)

        # Record round trip for TP-driven closes only
        if "take_profit" in close_reason:
            rec.round_trips += 1
            rec.last_exit_ts = time.time()
            logger.info("[TP] %s: round trip #%d recorded (reason=%s)", ticker, rec.round_trips, close_reason)

        # Clean up any open states for this ticker
        _closed_any = False
        for pos_id, ps in list(self._states.items()):
            if ps.ticker == ticker and ps.tp_state != TakeProfitState.CLOSED:
                ps.tp_state = TakeProfitState.CLOSED
                _closed_any = True

        if _closed_any:
            logger.debug("[TP] %s: cleaned up %d open position states", ticker, sum(1 for ps in self._states.values() if ps.ticker == ticker and ps.tp_state == TakeProfitState.CLOSED))

    def record_exit_price(self, ticker: str, exit_price_cents: int) -> None:
        """Record the price of the last TP exit for re-entry distance gating."""
        rec = self._round_trips.setdefault(ticker, _TickerRoundTripRecord())
        rec.last_exit_price_cents = exit_price_cents
        rec.last_exit_ts = time.time()

    def can_reenter(
        self,
        ticker: str,
        current_price_cents: int,
        system_risk_off: bool = False,
        contract_id: Optional[str] = None,
        contract_expiry_ts: Optional[float] = None,
    ) -> bool:
        """Check whether re-entry into a contract is allowed after a TP close.

        Returns False when:
          - system_risk_off is True (kill switch active — never open new positions)
          - Round trips for this contract >= max_round_trips_per_contract
          - Price has not moved far enough from the last exit price
          - Contract has expired (round trips reset on new contract)
          - Daily reset has occurred (if tp_round_trips_reset_daily enabled)

        Returns True when there is no prior TP history for this ticker (first entry).

        Args:
            ticker: Market ticker
            current_price_cents: Current market price in cents
            system_risk_off: True if kill switch active
            contract_id: Unique contract identifier (market_id) to detect contract changes
            contract_expiry_ts: Contract expiry timestamp for TTL-based reset
        """
        if system_risk_off:
            logger.debug("[TP-REENTRY] %s: blocked — system risk_off (kill switch active)", ticker)
            return False

        rec = self._round_trips.get(ticker)
        if not rec:
            return True  # no TP history — normal entry

        now = time.time()
        now_day = datetime.fromtimestamp(now, tz=timezone.utc).strftime("%Y-%m-%d")

        # ═══════════════════════════════════════════════════════════════════
        # Reset checks: contract expiry or daily reset
        # ═══════════════════════════════════════════════════════════════════

        # 1. Contract expiry reset
        if rec.contract_expiry_ts > 0 and now >= rec.contract_expiry_ts:
            logger.info(
                "[TP-RESET] %s: round trips reset — contract expired (expiry_ts=%d, now=%d)",
                ticker, rec.contract_expiry_ts, now
            )
            self._round_trips.pop(ticker, None)
            return True

        # 2. Contract ID change reset (new contract, same ticker series)
        if contract_id and rec.contract_id and rec.contract_id != contract_id:
            logger.info(
                "[TP-RESET] %s: round trips reset — contract_id changed (%s → %s)",
                ticker, rec.contract_id, contract_id
            )
            self._round_trips.pop(ticker, None)
            return True

        # 3. Daily reset (if enabled)
        cfg = self._config
        if cfg.tp_round_trips_reset_daily and rec.last_reset_day and rec.last_reset_day != now_day:
            logger.info(
                "[TP-RESET] %s: round trips reset — new day (%s → %s)",
                ticker, rec.last_reset_day, now_day
            )
            self._round_trips.pop(ticker, None)
            return True

        # Update contract tracking on first call
        if contract_id and not rec.contract_id:
            rec.contract_id = contract_id
        if contract_expiry_ts and rec.contract_expiry_ts == 0:
            rec.contract_expiry_ts = contract_expiry_ts
        if cfg.tp_round_trips_reset_daily and not rec.last_reset_day:
            rec.last_reset_day = now_day

        # ═══════════════════════════════════════════════════════════════════
        # Re-entry gating checks
        # ═══════════════════════════════════════════════════════════════════

        if rec.round_trips >= cfg.tp_max_round_trips_per_contract:
            logger.debug(
                "[TP-REENTRY] %s: blocked — round trips exhausted (%d/%d)",
                ticker, rec.round_trips, cfg.tp_max_round_trips_per_contract,
            )
            return False

        if rec.last_exit_price_cents > 0 and current_price_cents > 0:
            move = abs(current_price_cents - rec.last_exit_price_cents)
            if move < cfg.tp_min_price_move_for_reentry:
                logger.debug(
                    "[TP-REENTRY] %s: blocked — price move insufficient (%dc < %dc needed from exit %dc)",
                    ticker, move, cfg.tp_min_price_move_for_reentry, rec.last_exit_price_cents,
                )
                return False

        logger.debug(
            "[TP-REENTRY] %s: allowed — round_trips=%d/%d, price_move_ok",
            ticker, rec.round_trips, cfg.tp_max_round_trips_per_contract
        )
        return True

    def get_state(self, position_id: str) -> Optional[TakeProfitPositionState]:
        """Return the current TP state for a position (for diagnostics/API)."""
        return self._states.get(position_id)

    def summary(self) -> dict:
        """Aggregate diagnostics — number of positions per state, round trips."""
        counts: Dict[str, int] = {}
        _max_peak_unrealized = 0.0
        for ps in self._states.values():
            counts[ps.tp_state.value] = counts.get(ps.tp_state.value, 0) + 1
            _max_peak_unrealized = max(_max_peak_unrealized, ps.peak_unrealized_pct)

        total_round_trips = sum(r.round_trips for r in self._round_trips.values())
        cfg = self._config

        return {
            "tracked_positions": len(self._states),
            "state_counts": counts,
            "total_round_trips": total_round_trips,
            "round_trip_detail": {
                t: {
                    "round_trips": r.round_trips,
                    "contract_id": r.contract_id,
                    "last_exit_price": r.last_exit_price_cents,
                }
                for t, r in self._round_trips.items()
            },
            # PnL-based TP diagnostics
            "max_peak_unrealized_pct": round(_max_peak_unrealized, 2),
            "hard_tp_threshold_pct": cfg.tp_min_unrealized_pct_hard_close,
            "partial_tp_threshold_pct": cfg.tp_min_unrealized_pct_partial,
            "trailing_dynamic_threshold_pct": cfg.trailing_pct_activation_unrealized,
            "trailing_dynamic_giveback_pct": cfg.trailing_giveback_pct_after_unrealized,
            "round_trips_reset_daily": cfg.tp_round_trips_reset_daily,
        }

    # ── Internal helpers ────────────────────────────────────────────────

    def _calc_unrealized_pct(
        self,
        ps: TakeProfitPositionState,
        current_price_cents: int,
    ) -> float:
        """Calculate unrealized PnL percentage for the position.

        For YES: unrealized_pct = (current - entry) / entry × 100
        For NO: unrealized_pct = (entry - current) / (100 - entry) × 100

        Returns 0.0 if entry price is 0 (should never happen).
        """
        if ps.entry_price_cents == 0:
            return 0.0

        if ps.side == "yes":
            # YES position: profit when price goes UP
            # unrealized = (current - entry) / entry
            unrealized = (current_price_cents - ps.entry_price_cents) / ps.entry_price_cents
        else:
            # NO position: profit when price goes DOWN
            # entry cost for NO = (100 - entry) cents
            # unrealized = (entry - current) / (100 - entry)
            no_entry_cost = 100 - ps.entry_price_cents
            if no_entry_cost == 0:
                return 0.0
            unrealized = (ps.entry_price_cents - current_price_cents) / no_entry_cost

        return unrealized * 100.0  # Convert to percentage

    def _create_hard_tp_action(
        self,
        ps: TakeProfitPositionState,
        mid_cents: int,
        bid_cents: int,
        ask_cents: int,
        unrealized_pct: float,
        cfg: TakeProfitConfig,
    ) -> TakeProfitAction:
        """Create a CLOSE_FULL action for hard PnL-based TP.

        Hard TP bypasses all other logic and closes the entire position immediately
        when unrealized PnL exceeds the configured threshold (default 100%).
        """
        # Determine exit price based on side
        if ps.side == "yes":
            exit_cents = bid_cents if bid_cents > 0 else mid_cents
        else:
            exit_cents = ask_cents if ask_cents > 0 else mid_cents

        # Close full remaining position
        qty = ps.remaining_contracts

        # Update state
        ps.tp_state = TakeProfitState.CLOSED
        ps.last_action_ts = time.time()
        ps.pending_fill = True
        ps.last_exit_price_cents = exit_cents

        # Calculate net edge after fees for logging
        net_edge = self._fees.estimate_edge_after_costs(
            entry_cents=ps.entry_price_cents,
            exit_cents=exit_cents,
            contracts=1,
            side=ps.side,
        )

        logger.info(
            "[TP-HARD-ACTION] %s %s: HARD TP firing — unrealized=%.1f%% entry=%dc exit=%dc qty=%d net_edge=%.1f¢",
            ps.ticker, ps.side, unrealized_pct, ps.entry_price_cents, exit_cents, qty, net_edge
        )

        return TakeProfitAction(
            position_id=ps.position_id,
            ticker=ps.ticker,
            side=ps.side,
            action_type="CLOSE_FULL",
            quantity=qty,
            limit_price_cents=exit_cents,
            reason=(
                f"hard_tp_pnl: unrealized={unrealized_pct:.1f}% "
                f"entry={ps.entry_price_cents}c exit={exit_cents}c "
                f"net_edge={net_edge:.1f}c"
            ),
        )

    def _compute_primary_target(
        self,
        entry_price_cents: int,
        side: str,
        cfg: TakeProfitConfig,
        contracts: int,
    ) -> Optional[int]:
        """Compute the YES price at which primary TP should fire.

        Returns None if the target is infeasible (< tp_min_cents gain after fees).
        """
        if not cfg.tp_enabled:
            return None

        e = entry_price_cents

        # R definitions per side
        if side == "yes":
            r_cents = e                    # risk = entry price
            max_gain_cents = 100 - e       # maximum gain per contract (cents)
        else:
            r_cents = 100 - e              # risk = NO price = (100 - YES entry)
            max_gain_cents = e             # maximum gain = YES entry price

        # Candidate from R-multiple
        candidates: List[int] = []
        if cfg.tp_r_multiple_primary > 0:
            if side == "yes":
                raw = e + cfg.tp_r_multiple_primary * r_cents
                cand = min(int(round(raw)), 99)
            else:
                raw = e - cfg.tp_r_multiple_primary * r_cents
                cand = max(int(round(raw)), 1)
            candidates.append(cand)

        # Candidate from pct-of-max-gain
        if cfg.tp_pct_of_max_gain_primary > 0:
            gain = cfg.tp_pct_of_max_gain_primary * max_gain_cents
            if side == "yes":
                cand = min(int(round(e + gain)), 99)
            else:
                cand = max(int(round(e - gain)), 1)
            candidates.append(cand)

        if not candidates:
            return None

        # Take the MORE CONSERVATIVE target (closer to entry = easier to hit)
        if side == "yes":
            target = min(candidates)  # lower YES price target = less gain required
        else:
            target = max(candidates)  # higher YES price target = less fall required

        # Validate: absolute gain in cents
        if side == "yes":
            gross_gain = (target - e) * contracts
        else:
            gross_gain = (e - target) * contracts

        if gross_gain < cfg.tp_min_cents * contracts:
            logger.debug(
                "[TP] %s: primary target %dc → gain %dc < min_cents %d — suppressed",
                side, target, gross_gain // contracts, cfg.tp_min_cents,
            )
            return None

        # Validate: edge after fees (per contract)
        net_edge = self._fees.estimate_edge_after_costs(
            entry_cents=e,
            exit_cents=target,
            contracts=1,
            side=side,
        )
        if net_edge < cfg.tp_min_edge_after_fees_cents:
            logger.debug(
                "[TP] %s: target %dc → net edge %.1f¢ < min %.1f¢ — suppressed",
                side, target, net_edge, cfg.tp_min_edge_after_fees_cents,
            )
            return None

        return target

    def _check_primary(
        self,
        ps: TakeProfitPositionState,
        mid_cents: int,
        bid_cents: int,
        ask_cents: int,
        cfg: TakeProfitConfig,
        force_trigger: bool = False,
    ) -> Optional[TakeProfitAction]:
        """Check primary TP trigger and return action if hit.

        Args:
            force_trigger: If True, bypass price target check (used for PnL-based partial TP)
        """
        if ps.primary_target_cents <= 0 and not force_trigger:
            ps.tp_state = TakeProfitState.INACTIVE
            return None

        # Determine check price based on side (always needed for exit calculation)
        if ps.side == "yes":
            # YES: profit as price rises — use bid (we sell to buyer's bid)
            check_price = bid_cents if bid_cents > 0 else mid_cents
        else:
            # NO: profit as YES price falls — use ask (we buy back YES at seller's ask)
            check_price = ask_cents if ask_cents > 0 else mid_cents

        triggered = force_trigger  # If forced, skip price check
        if not triggered:
            if ps.side == "yes":
                triggered = check_price >= ps.primary_target_cents
            else:
                triggered = check_price <= ps.primary_target_cents

        if not triggered:
            return None

        # Validate edge-after-fees at current market price
        exit_cents = check_price
        net_edge = self._fees.estimate_edge_after_costs(
            entry_cents=ps.entry_price_cents,
            exit_cents=exit_cents,
            contracts=1,
            side=ps.side,
        )
        if net_edge < cfg.tp_min_edge_after_fees_cents:
            logger.warning(
                "[TP] PRIMARY %s: target %dc hit (check_price=%dc) but net edge %.1f¢ "
                "< min %.1f¢ — suppressed",
                ps.ticker, ps.primary_target_cents, check_price,
                net_edge, cfg.tp_min_edge_after_fees_cents,
            )
            return None

        # Compute partial exit quantity
        qty = max(1, int(ps.remaining_contracts * cfg.tp_scale_out_fraction))
        is_full = qty >= ps.remaining_contracts
        action_type: Literal["CLOSE_PARTIAL", "CLOSE_FULL"] = (
            "CLOSE_FULL" if is_full else "CLOSE_PARTIAL"
        )

        # Advance state
        if is_full or not cfg.tp_trailing_enabled:
            ps.tp_state = TakeProfitState.CLOSED
        else:
            # Move to trailing on the remaining contracts
            ps.tp_state = TakeProfitState.TRAILING_ACTIVE
            ps.peak_price_cents = check_price

        ps.last_action_ts = time.time()
        ps.pending_fill = True
        ps.last_exit_price_cents = exit_cents

        logger.info(
            "[TP] PRIMARY fired %s %s: entry=%dc check=%dc target=%dc qty=%d/%d "
            "net_edge=%.1f¢ action=%s new_state=%s",
            ps.ticker, ps.side,
            ps.entry_price_cents, check_price, ps.primary_target_cents,
            qty, ps.remaining_contracts, net_edge,
            action_type, ps.tp_state.value,
        )

        return TakeProfitAction(
            position_id=ps.position_id,
            ticker=ps.ticker,
            side=ps.side,
            action_type=action_type,
            quantity=qty,
            limit_price_cents=exit_cents,
            reason=(
                f"primary_tp_hit: entry={ps.entry_price_cents}c "
                f"target={ps.primary_target_cents}c "
                f"exit={exit_cents}c net_edge={net_edge:.1f}c"
            ),
        )

    def _update_trailing_peak(
        self,
        ps: TakeProfitPositionState,
        mid_cents: int,
        bid_cents: int,
        ask_cents: int,
        unrealized_pct: float = 0.0,
        cfg: Optional[TakeProfitConfig] = None,
    ) -> None:
        """Update the trailing peak price and unrealized PnL — called every cycle regardless of debounce."""
        if ps.side == "yes":
            current_favorable = bid_cents if bid_cents > 0 else mid_cents
        else:
            current_favorable = ask_cents if ask_cents > 0 else mid_cents

        if current_favorable <= 0:
            return

        if ps.peak_price_cents == 0:
            ps.peak_price_cents = current_favorable

        # Update price-based peak
        if ps.side == "yes":
            if current_favorable > ps.peak_price_cents:
                ps.peak_price_cents = current_favorable
                logger.debug("[TP] TRAILING %s: new peak %dc", ps.ticker, ps.peak_price_cents)
        else:
            if current_favorable < ps.peak_price_cents:
                ps.peak_price_cents = current_favorable
                logger.debug("[TP] TRAILING %s: new peak %dc", ps.ticker, ps.peak_price_cents)

        # Track unrealized PnL peak for dynamic giveback
        ps.peak_unrealized_pct = max(ps.peak_unrealized_pct, unrealized_pct)

    def _check_trailing_action(
        self,
        ps: TakeProfitPositionState,
        mid_cents: int,
        bid_cents: int,
        ask_cents: int,
        cfg: TakeProfitConfig,
    ) -> Optional[TakeProfitAction]:
        """Check giveback threshold and return a close action if exceeded.

        Peak is already up-to-date (updated by _update_trailing_peak before debounce).
        """
        if ps.remaining_contracts <= 0:
            ps.tp_state = TakeProfitState.CLOSED
            return None

        if ps.side == "yes":
            current_favorable = bid_cents if bid_cents > 0 else mid_cents
            giveback = ps.peak_price_cents - current_favorable
        else:
            current_favorable = ask_cents if ask_cents > 0 else mid_cents
            giveback = current_favorable - ps.peak_price_cents

        # ═══════════════════════════════════════════════════════════════════
        # Dynamic trailing giveback: use percentage-based once PnL > threshold
        # ═══════════════════════════════════════════════════════════════════
        effective_giveback_cents = cfg.tp_trailing_giveback_cents

        if cfg.trailing_pct_activation_unrealized > 0 and ps.peak_unrealized_pct >= cfg.trailing_pct_activation_unrealized:
            # Dynamic mode: limit giveback to X% of peak unrealized PnL
            # Convert percentage giveback to cents based on entry price
            dynamic_giveback_cents = int(ps.entry_price_cents * cfg.trailing_giveback_pct_after_unrealized / 100.0)
            effective_giveback_cents = max(cfg.tp_trailing_giveback_cents, dynamic_giveback_cents)
            logger.debug(
                "[TP-TRAILING-DYNAMIC] %s: using dynamic giveback=%dc (fixed=%dc, peak_unrealized=%.1f%%)",
                ps.ticker, effective_giveback_cents, cfg.tp_trailing_giveback_cents, ps.peak_unrealized_pct
            )

        if ps.peak_price_cents == 0 or giveback < effective_giveback_cents:
            return None  # still within allowed pullback

        # Giveback exceeded → close remainder
        exit_cents = current_favorable
        net_edge = self._fees.estimate_edge_after_costs(
            entry_cents=ps.entry_price_cents,
            exit_cents=exit_cents,
            contracts=1,
            side=ps.side,
        )

        qty = ps.remaining_contracts
        ps.tp_state = TakeProfitState.CLOSED
        ps.last_action_ts = time.time()
        ps.pending_fill = True
        ps.last_exit_price_cents = exit_cents

        logger.info(
            "[TP] TRAILING fired %s %s: peak=%dc current=%dc giveback=%dc > threshold=%dc "
            "qty=%d net_edge=%.1f¢ peak_unrealized=%.1f%%",
            ps.ticker, ps.side,
            ps.peak_price_cents, current_favorable, giveback,
            effective_giveback_cents, qty, net_edge, ps.peak_unrealized_pct
        )

        return TakeProfitAction(
            position_id=ps.position_id,
            ticker=ps.ticker,
            side=ps.side,
            action_type="CLOSE_FULL",
            quantity=qty,
            limit_price_cents=exit_cents,
            reason=(
                f"trailing_giveback_exceeded: peak={ps.peak_price_cents}c "
                f"current={current_favorable}c giveback={giveback}c "
                f"threshold={effective_giveback_cents}c "
                f"net_edge={net_edge:.1f}c peak_unrealized={ps.peak_unrealized_pct:.1f}%"
            ),
        )

    def evict_expired(self, now_ts: Optional[float] = None) -> int:
        """Remove CLOSED states older than 24h to prevent unbounded growth.
        
        Returns number of evicted entries.
        """
        if now_ts is None:
            now_ts = time.time()
        
        expired = []
        cutoff = now_ts - (24 * 3600)  # 24 hours
        
        for position_id, ps in self._states.items():
            if ps.tp_state == TakeProfitState.CLOSED and ps.created_ts < cutoff:
                expired.append(position_id)
        
        for position_id in expired:
            del self._states[position_id]
        
        return len(expired)
    
    # ═══════════════════════════════════════════════════════════════════════════
    # Entry/Exit Timing Precision Validation
    # ═══════════════════════════════════════════════════════════════════════════
    
    def validate_entry_timing(
        self,
        position_id: str,
        signal_generated_ts: float,
        entry_executed_ts: float,
    ) -> Tuple[bool, str]:
        """Validate that entry executed within acceptable latency window.
        
        CRITICAL: Prevents stale entries - if entry is delayed too long
        after signal generation, the market may have moved unfavorably.
        
        Args:
            position_id: Unique identifier for this position
            signal_generated_ts: UTC timestamp when signal was generated
            entry_executed_ts: UTC timestamp when entry was executed
            
        Returns:
            Tuple of (valid: bool, reason: str)
            - valid: True if entry timing is acceptable, False if stale
            - reason: Empty if valid, descriptive error if invalid
        """
        cfg = self._config
        
        if not cfg.require_entry_timestamp_validation:
            return True, ""
        
        latency = entry_executed_ts - signal_generated_ts
        
        if latency < 0:
            return False, f"TIMING_VIOLATION: Entry executed {abs(latency):.2f}s BEFORE signal generated (impossible)"
        
        if latency > cfg.max_entry_latency_seconds:
            return False, (
                f"STALE_ENTRY: Entry latency {latency:.2f}s exceeds max {cfg.max_entry_latency_seconds}s "
                f"(signal ts={signal_generated_ts:.3f}, entry ts={entry_executed_ts:.3f})"
            )
        
        logger.info(
            "[TP-TIMING] %s: Entry valid - latency %.2fs (max %.2fs)",
            position_id, latency, cfg.max_entry_latency_seconds
        )
        return True, ""
    
    def validate_exit_timing(
        self,
        position_id: str,
        tp_trigger_ts: float,
        exit_executed_ts: float,
    ) -> Tuple[bool, str]:
        """Validate that exit executed within acceptable latency window.
        
        CRITICAL: Prevents stale exits - if exit is delayed too long
        after TP trigger, we may miss the optimal exit price.
        
        Args:
            position_id: Unique identifier for this position
            tp_trigger_ts: UTC timestamp when TP trigger was evaluated
            exit_executed_ts: UTC timestamp when exit was executed
            
        Returns:
            Tuple of (valid: bool, reason: str)
            - valid: True if exit timing is acceptable, False if delayed
            - reason: Empty if valid, descriptive error if invalid
        """
        cfg = self._config
        
        if not cfg.require_exit_timestamp_validation:
            return True, ""
        
        latency = exit_executed_ts - tp_trigger_ts
        
        if latency < 0:
            return False, f"TIMING_VIOLATION: Exit executed {abs(latency):.2f}s BEFORE TP trigger (impossible)"
        
        if latency > cfg.max_exit_latency_seconds:
            return False, (
                f"DELAYED_EXIT: Exit latency {latency:.2f}s exceeds max {cfg.max_exit_latency_seconds}s "
                f"(trigger ts={tp_trigger_ts:.3f}, exit ts={exit_executed_ts:.3f})"
            )
        
        logger.info(
            "[TP-TIMING] %s: Exit valid - latency %.2fs (max %.2fs)",
            position_id, latency, cfg.max_exit_latency_seconds
        )
        return True, ""
    
    def record_entry_execution(self, position_id: str, entry_ts: float) -> None:
        """Record entry execution timestamp for timing validation.
        
        Args:
            position_id: Position identifier
            entry_ts: UTC timestamp when entry was executed
        """
        ps = self._states.get(position_id)
        if ps:
            ps.entry_executed_ts = entry_ts
            logger.debug("[TP-TIMING] %s: Entry recorded at %.3f", position_id, entry_ts)
    
    def record_exit_execution(self, position_id: str, exit_ts: float) -> None:
        """Record exit execution timestamp for timing validation.
        
        Args:
            position_id: Position identifier
            exit_ts: UTC timestamp when exit was executed
        """
        ps = self._states.get(position_id)
        if ps:
            ps.exit_executed_ts = exit_ts
            logger.debug("[TP-TIMING] %s: Exit recorded at %.3f", position_id, exit_ts)
