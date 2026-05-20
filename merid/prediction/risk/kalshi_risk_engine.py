"""
Kalshi Risk Engine — Shared risk/sizing/fee/churn logic
========================================================
Extracted from the BTC continuous trader (``scripts/kalshi_continuous_trader.py``
and ``merid/trading/kalshi_continuous_trader.py``) so every grid agent can reuse
the same leak-proof bankroll management rules:

  - Fractional Kelly sizing with hard caps
  - Drawdown halt / reduce
  - Fee-aware minimum edge by price band
  - Anti-churn hysteresis (cooldown + edge-improvement gate)
  - Rolling fee-drag monitor with auto-tightening
  - Volatility-adaptive fee-drag window
  - Effective limit reduction under fee stress

DEPRECATION NOTICE:
====================
This module contains a duplicate KalshiRiskConfig dataclass. The canonical
single source of truth for Kalshi risk configuration is:
    merid.event_venues.kalshi.kalshi_risk.KalshiRiskConfig

The PM-specific KalshiRiskConfig in this file is deprecated and should only
be used by tests. Live trading code should use the venue config from:
    from merid.event_venues.kalshi.kalshi_risk import KalshiRiskConfig

Usage::

    from merid.prediction.risk.kalshi_risk_engine import KalshiRiskEngine, KalshiRiskConfig

    cfg = KalshiRiskConfig()                       # default (conservative)
    cfg = KalshiRiskConfig.aggressive()             # preset
    cfg = KalshiRiskConfig.from_risk_profile("conservative")

    engine = KalshiRiskEngine(cfg)

    # Each cycle:
    engine.advance_cycle()
    engine.update_peak(balance_cents)
    engine.record_cycle_snapshot(balance_cents)

    # Before placing an order:
    if not engine.check_churn(ticker, side, edge):
        ...  # blocked

    size = engine.calculate_order_size(
        balance_cents, edge, price_cents, existing_pos, total_open,
    )

    # After fill:
    engine.record_fee(fee_cents, gross_edge_cents)
    engine.record_trade_direction(ticker, side, edge)
    engine.record_trade_result(pnl_cents)
"""

from __future__ import annotations

import collections
import math
import os
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from utils.logger import get_logger

logger = get_logger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# Settings helpers (bankroll-driven configuration)
# ═══════════════════════════════════════════════════════════════════════════

def _get_setting_float(name: str, default: float) -> float:
    """Get a float setting from environment or merid.settings if available."""
    # First try environment variable
    env_val = os.getenv(name)
    if env_val is not None:
        try:
            return float(env_val)
        except ValueError:
            pass
    # Try merid.settings if available
    try:
        from merid.settings import settings
        return float(getattr(settings, name, default))
    except Exception:
        return default


def _get_setting_int(name: str, default: int) -> int:
    """Get an int setting from environment or merid.settings if available."""
    env_val = os.getenv(name)
    if env_val is not None:
        try:
            return int(env_val)
        except ValueError:
            pass
    try:
        from merid.settings import settings
        return int(getattr(settings, name, default))
    except Exception:
        return default


# ═══════════════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class KalshiRiskConfig:
    """All tunable risk/sizing knobs — the superset of BankrollManager config
    minus script-only fields (interval_seconds, max_cycles, dry_run, CLI stuff).

    Three built-in presets are provided via class methods:
      - ``KalshiRiskConfig()``            — default (conservative, quarter-Kelly)
      - ``KalshiRiskConfig.aggressive()`` — higher Kelly, wider price range
      - ``KalshiRiskConfig.conservative()`` — tighter everything
    """

    # ── Bankroll management ────────────────────────────────────────────
    initial_bankroll_cents: int = 1000
    # CRITICAL: 1% per trade max (NOT 2%). With 3 trades, 3×1% = 3% worst case.
    # 3×2% = 6% is STRICTLY FORBIDDEN. Always use TopNAllocator (1-2% total).
    # This is a FAIL-SAFE fallback if someone disables TopNAllocator.
    max_risk_per_trade_pct: float = field(default_factory=lambda: _get_setting_float("KALSHI_MAX_RISK_PER_TRADE_PCT", 0.01))
    kelly_fraction: float = field(default_factory=lambda: _get_setting_float("KALSHI_KELLY_FRACTION", 0.25))
    max_contract_price_cents: int = field(default_factory=lambda: _get_setting_int("KALSHI_MAX_CONTRACT_PRICE_CENTS", 35))
    min_contract_price_cents: int = field(default_factory=lambda: _get_setting_int("KALSHI_MIN_CONTRACT_PRICE_CENTS", 2))
    max_position_per_market: int = field(default_factory=lambda: _get_setting_int("KALSHI_MAX_POSITION_PER_MARKET", 3))
    max_open_positions: int = field(default_factory=lambda: _get_setting_int("KALSHI_MAX_OPEN_POSITIONS", 5))
    max_total_exposure_pct: float = field(default_factory=lambda: _get_setting_float("KALSHI_MAX_TOTAL_EXPOSURE_PCT", 0.20))

    # ── Drawdown protection ────────────────────────────────────────────
    drawdown_halt_pct: float = field(default_factory=lambda: _get_setting_float("KALSHI_DRAWDOWN_HALT_PCT", 0.20))
    drawdown_reduce_pct: float = field(default_factory=lambda: _get_setting_float("KALSHI_DRAWDOWN_REDUCE_PCT", 0.10))
    min_balance_cents: int = field(default_factory=lambda: _get_setting_int("KALSHI_MIN_BALANCE_CENTS", 200))

    # ── Edge requirements ──────────────────────────────────────────────
    min_edge: Decimal = field(default_factory=lambda: Decimal("0.08"))
    fee_per_contract: Decimal = field(default_factory=lambda: Decimal("0.02"))  # ~2¢ (= 0.07*P*(1-P) at 50¢)
    slippage: Decimal = field(default_factory=lambda: Decimal("0.01"))

    # ── Fee-aware edge scaling ─────────────────────────────────────────
    fee_edge_multiplier_midcurve: float = 1.5
    fee_edge_multiplier_penny: float = 2.0

    # ── Anti-churn hysteresis ──────────────────────────────────────────
    churn_cooldown_cycles: int = 3
    churn_edge_improvement: float = 0.05

    # ── Fee drag monitoring ────────────────────────────────────────────
    max_fee_drag_pct: float = 0.30
    fee_drag_lookback: int = 30

    # ── Volatility-adaptive fee-drag window ────────────────────────────
    vol_lookback_bars: int = 20
    vol_low_threshold: float = 0.40
    vol_high_threshold: float = 0.80
    fee_window_low_vol: int = 50
    fee_window_mid_vol: int = 30
    fee_window_high_vol: int = 20

    # ── Order management ───────────────────────────────────────────────
    max_orders_per_cycle: int = 1

    # ── Cycle interval (needed for vol annualisation) ──────────────────
    interval_seconds: int = 60

    # ── Presets ────────────────────────────────────────────────────────

    @classmethod
    def conservative(cls) -> "KalshiRiskConfig":
        """Tightest risk profile — smallest positions, highest edge bar.

        Uses settings-driven base values with conservative multipliers.
        """
        # Get base values from settings (or defaults)
        base_kelly = _get_setting_float("KALSHI_KELLY_FRACTION", 0.25)
        # SAFETY: Use 0.01 (1%) base to prevent 3×2% = 6% total risk
        base_risk = _get_setting_float("KALSHI_MAX_RISK_PER_TRADE_PCT", 0.01)
        base_exposure = _get_setting_float("KALSHI_MAX_TOTAL_EXPOSURE_PCT", 0.20)
        base_dd_halt = _get_setting_float("KALSHI_DRAWDOWN_HALT_PCT", 0.20)
        base_dd_reduce = _get_setting_float("KALSHI_DRAWDOWN_REDUCE_PCT", 0.10)

        return cls(
            kelly_fraction=base_kelly * 0.60,  # 60% of base
            # 75% of 1% = 0.75% per trade. 3×0.75% = 2.25% max (within 1-2% target)
            max_risk_per_trade_pct=base_risk * 0.75,
            max_contract_price_cents=_get_setting_int("KALSHI_MAX_CONTRACT_PRICE_CENTS", 35) - 10,
            max_position_per_market=2,
            max_open_positions=3,
            max_total_exposure_pct=base_exposure * 0.60,  # 60% of base
            min_edge=Decimal("0.10"),
            drawdown_halt_pct=base_dd_halt * 0.75,  # Tighter halt
            drawdown_reduce_pct=base_dd_reduce * 0.70,  # Tighter reduce
            churn_cooldown_cycles=5,
            max_orders_per_cycle=1,
        )

    @classmethod
    def aggressive(cls) -> "KalshiRiskConfig":
        """Wider risk profile — larger positions, lower edge bar.

        Uses settings-driven base values with aggressive multipliers.
        """
        # Get base values from settings (or defaults)
        base_kelly = _get_setting_float("KALSHI_KELLY_FRACTION", 0.25)
        # SAFETY: Use 0.01 (1%) base to prevent 3×2% = 6% total risk
        base_risk = _get_setting_float("KALSHI_MAX_RISK_PER_TRADE_PCT", 0.01)
        base_exposure = _get_setting_float("KALSHI_MAX_TOTAL_EXPOSURE_PCT", 0.20)
        base_dd_halt = _get_setting_float("KALSHI_DRAWDOWN_HALT_PCT", 0.20)
        base_dd_reduce = _get_setting_float("KALSHI_DRAWDOWN_REDUCE_PCT", 0.10)

        return cls(
            kelly_fraction=min(0.50, base_kelly * 1.40),  # 40% more, cap at 50%
            # Even aggressive: max 1.5% per trade (150% of 1%). 3×1.5% = 4.5% worst case.
            # Still over 1-2% target — ALWAYS use TopNAllocator for proper 1-2% total cap.
            max_risk_per_trade_pct=min(0.015, base_risk * 1.50),  # 50% more, HARD CAP 1.5%
            max_contract_price_cents=_get_setting_int("KALSHI_MAX_CONTRACT_PRICE_CENTS", 35) + 15,
            max_position_per_market=5,
            max_open_positions=8,
            max_total_exposure_pct=min(0.50, base_exposure * 1.50),  # 50% more, cap at 50%
            min_edge=Decimal("0.06"),
            drawdown_halt_pct=min(0.35, base_dd_halt * 1.25),  # Wider halt
            drawdown_reduce_pct=min(0.20, base_dd_reduce * 1.20),  # Wider reduce
            churn_cooldown_cycles=2,
            max_orders_per_cycle=2,
        )

    @classmethod
    def from_risk_profile(cls, profile: str) -> "KalshiRiskConfig":
        """Resolve a named risk profile string to a config instance.

        Accepted values: ``conservative``, ``default``/``moderate``, ``aggressive``.
        """
        profile = (profile or "default").lower().strip()
        if profile == "conservative":
            return cls.conservative()
        elif profile == "aggressive":
            return cls.aggressive()
        else:
            return cls()  # default / moderate


# ═══════════════════════════════════════════════════════════════════════════
# Risk Engine
# ═══════════════════════════════════════════════════════════════════════════

class KalshiRiskEngine:
    """Capital-preservation-first risk engine.

    Rules enforced:
     1. NEVER risk more than ``max_risk_per_trade_pct`` of bankroll per trade
     2. NEVER buy contracts priced above ``max_contract_price_cents``
     3. Fractional Kelly sizing — mathematically optimal growth with safety margin
     4. HALT all trading if drawdown from peak exceeds ``drawdown_halt_pct``
     5. REDUCE sizing by 50% if drawdown exceeds ``drawdown_reduce_pct``
     6. Compound: position sizes grow as bankroll grows (balance-relative)
     7. Cap total exposure so no single bad run wipes us out
     8. Fee-aware edge: require higher edge at mid-curve prices
     9. Anti-churn hysteresis: block direction flips within N cycles
    10. Fee drag monitor: auto-tighten filters when fees exceed % of gross edge
    """

    def __init__(
        self,
        config: KalshiRiskConfig,
        *,
        name: str = "",
        quiet_bankroll_log: bool = False,
    ) -> None:
        self.config = config
        self._name = name  # agent name for logging
        self._quiet_bankroll_log = quiet_bankroll_log

        # Peak seeded to 0 — first update_peak() sets from real balance
        self._peak_balance_cents = 0
        self._halted = False
        self._halt_reason = ""

        # Trade stats
        self._total_trades = 0
        self._total_wins = 0
        self._total_losses = 0
        self._total_pnl_cents = 0
        self._total_fees_cents = 0

        # Anti-churn: {ticker: (last_side, last_edge, cycle_number)}
        self._last_trade: Dict[str, Tuple[str, float, int]] = {}
        self._current_cycle = 0

        # Fee drag monitor: rolling window of (fee_cents, gross_edge_cents)
        self._fee_history: collections.deque = collections.deque(
            maxlen=config.fee_drag_lookback,
        )
        self._fee_drag_tightening = False

        # Volatility-adaptive fee-drag window
        self._spot_history: collections.deque = collections.deque(
            maxlen=config.vol_lookback_bars + 1,
        )
        # Start aligned with vol=0: classifies as \"low\" (not default \"mid\", which
        # looked like real mid-vol regime in the CT bankroll panel).
        self._current_vol_band = "low"
        self._annualized_vol = 0.0
        self._update_vol_band()

        # Sparkline history — last 60 cycles
        self._cycle_history: collections.deque = collections.deque(maxlen=60)

        _label = f" ({name})" if name else ""
        _msg = (
            "KalshiRiskEngine%s: bankroll=$%.2f, risk/trade=%.1f%%, kelly=%.0f%%, "
            "max_price=%d¢, dd_halt=%.0f%%, dd_reduce=%.0f%%, "
            "fee_mult_mid=%.1fx, fee_mult_penny=%.1fx, churn_cooldown=%d"
        )
        _args = (
            _label,
            config.initial_bankroll_cents / 100,
            config.max_risk_per_trade_pct * 100,
            config.kelly_fraction * 100,
            config.max_contract_price_cents,
            config.drawdown_halt_pct * 100,
            config.drawdown_reduce_pct * 100,
            config.fee_edge_multiplier_midcurve,
            config.fee_edge_multiplier_penny,
            config.churn_cooldown_cycles,
        )
        if quiet_bankroll_log:
            logger.debug(_msg + " [PM mode: CT engine config only — use KalshiRiskManager equity for sizing]", *_args)
        else:
            logger.info(_msg, *_args)

    # ── Cycle tracking ─────────────────────────────────────────────────

    def advance_cycle(self) -> None:
        """Call once at the start of each trading cycle."""
        self._current_cycle += 1

    def record_cycle_snapshot(self, balance_cents: int) -> None:
        """Append a per-cycle data point for sparkline rendering."""
        self._cycle_history.append({
            "cycle": self._current_cycle,
            "drawdown_pct": round(self.get_drawdown_pct(balance_cents) * 100, 2),
            "fee_drag_pct": round(self.get_fee_drag_pct() * 100, 1),
            "pnl_cents": self._total_pnl_cents,
            "balance_cents": balance_cents,
            "vol_pct": round(self._annualized_vol * 100, 1),
        })

    @property
    def cycle_history(self) -> list:
        """Return cycle history as a plain list (for JSON serialisation)."""
        return list(self._cycle_history)

    # ── Volatility-adaptive fee-drag window ────────────────────────────

    def record_spot(self, spot: float) -> None:
        """Record a spot observation and update vol-adaptive window."""
        if spot <= 0:
            return
        self._spot_history.append(spot)
        if len(self._spot_history) >= 3:
            self._compute_vol()
        # Always re-map band: with <3 samples _annualized_vol may still be 0, which
        # should classify as \"low\" per thresholds (not stale default \"mid\").
        self._update_vol_band()

    def apply_external_annualized_vol(self, annualized_fraction: float) -> None:
        """Blend in a finer-grained vol estimate (e.g. BTC Crypto15mIndicatorStack).

        Cycle-based `record_spot` can sit at 0% for many minutes when spot prints
        are nearly flat per interval; the stack uses a longer price history updated
        each cycle and is a better display + fee-window driver when higher.
        """
        try:
            v = float(annualized_fraction)
        except (TypeError, ValueError):
            return
        if v <= 0.0 or not math.isfinite(v):
            return
        if v > self._annualized_vol:
            self._annualized_vol = v
            self._update_vol_band()

    def _compute_vol(self) -> None:
        """Compute annualized realized vol from log-returns."""
        spots = list(self._spot_history)
        if len(spots) < 3:
            return
        log_returns = [
            math.log(spots[i] / spots[i - 1])
            for i in range(1, len(spots))
            if spots[i - 1] > 0
        ]
        if len(log_returns) < 2:
            return
        mean_r = sum(log_returns) / len(log_returns)
        var = sum((r - mean_r) ** 2 for r in log_returns) / (len(log_returns) - 1)
        bar_vol = math.sqrt(var)
        bars_per_year = 365.25 * 24 * 3600 / max(1, self.config.interval_seconds)
        self._annualized_vol = bar_vol * math.sqrt(bars_per_year)

    def _update_vol_band(self) -> None:
        """Map annualized vol to a band and resize fee_history if band changed."""
        cfg = self.config
        vol = self._annualized_vol

        if vol < cfg.vol_low_threshold:
            new_band = "low"
            new_window = cfg.fee_window_low_vol
        elif vol > cfg.vol_high_threshold:
            new_band = "high"
            new_window = cfg.fee_window_high_vol
        else:
            new_band = "mid"
            new_window = cfg.fee_window_mid_vol

        if new_band != self._current_vol_band:
            old_band = self._current_vol_band
            self._current_vol_band = new_band
            old_data = list(self._fee_history)
            self._fee_history = collections.deque(
                old_data[-new_window:], maxlen=new_window,
            )
            logger.info(
                "VOL BAND%s: %s → %s (ann_vol=%.0f%%, window %d → %d)",
                f" [{self._name}]" if self._name else "",
                old_band, new_band, vol * 100,
                len(old_data), new_window,
            )

    @property
    def vol_band(self) -> str:
        """Current volatility band: 'low', 'mid', or 'high'."""
        return self._current_vol_band

    @property
    def annualized_vol(self) -> float:
        return self._annualized_vol

    # ── Drawdown ───────────────────────────────────────────────────────

    def update_peak(self, balance_cents: int) -> None:
        """Update peak balance for drawdown tracking."""
        if balance_cents > self._peak_balance_cents:
            self._peak_balance_cents = balance_cents
            logger.debug("NEW PEAK%s: $%.2f",
                         f" [{self._name}]" if self._name else "",
                         balance_cents / 100)

    def check_drawdown(self, balance_cents: int) -> bool:
        """Check drawdown and return True if trading is allowed.

        Auto-resets halt state when drawdown recovers below drawdown_reduce_pct
        to ensure trading resumes once capital returns to tradable zone.
        """
        if self._peak_balance_cents <= 0:
            return True

        drawdown = 1.0 - (balance_cents / self._peak_balance_cents)

        if drawdown >= self.config.drawdown_halt_pct:
            self._halted = True
            self._halt_reason = (
                f"Drawdown {drawdown:.1%} >= halt threshold "
                f"{self.config.drawdown_halt_pct:.0%}. "
                f"Peak=${self._peak_balance_cents / 100:.2f}, "
                f"now=${balance_cents / 100:.2f}"
            )
            logger.warning("DRAWDOWN HALT%s: %s",
                           f" [{self._name}]" if self._name else "",
                           self._halt_reason)
            return False

        # Auto-reset halt when drawdown recovers to tradable zone
        if self._halted and drawdown < self.config.drawdown_reduce_pct:
            self._halted = False
            self._halt_reason = ""
            logger.info(
                "DRAWDOWN RECOVERY%s: drawdown %.1f%% below reduce threshold %.0f%% — halt auto-reset, trading resumed",
                f" [{self._name}]" if self._name else "",
                drawdown * 100,
                self.config.drawdown_reduce_pct * 100,
            )
            return True

        if drawdown >= self.config.drawdown_reduce_pct:
            logger.info("Drawdown %.1f%%%s — reduced sizing active",
                        drawdown * 100,
                        f" [{self._name}]" if self._name else "")

        # Return False if still halted, True otherwise
        return not self._halted

    @property
    def is_halted(self) -> bool:
        return self._halted

    @property
    def halt_reason(self) -> str:
        return self._halt_reason

    @property
    def peak_balance_cents(self) -> int:
        return self._peak_balance_cents

    def reset_halt(self, new_peak_cents: Optional[int] = None) -> None:
        """Clear halt state and optionally reset peak."""
        self._halted = False
        self._halt_reason = ""
        if new_peak_cents is not None and new_peak_cents > 0:
            self._peak_balance_cents = new_peak_cents

    def get_drawdown_pct(self, balance_cents: int) -> float:
        if self._peak_balance_cents <= 0:
            return 0.0
        return 1.0 - (balance_cents / self._peak_balance_cents)

    # ── Fee-aware minimum edge by price band ───────────────────────────

    def min_edge_for_price(self, contract_price_cents: int) -> Decimal:
        """Dynamic minimum edge required for a given contract price.

        Price bands:
          ≤ 5¢   → 2.0x base (rounding kills small contracts)
          6-39¢  → 1.0x base (sweet spot)
          40-60¢ → 1.5x base (highest absolute fee per contract)
          61-99¢ → 1.0x base (symmetric)
        """
        cfg = self.config
        base = cfg.min_edge

        if self._fee_drag_tightening:
            base = (base * Decimal("1.25")).quantize(Decimal("0.0001"))

        if contract_price_cents <= 5:
            return (base * Decimal(str(cfg.fee_edge_multiplier_penny))).quantize(Decimal("0.0001"))
        elif 40 <= contract_price_cents <= 60:
            return (base * Decimal(str(cfg.fee_edge_multiplier_midcurve))).quantize(Decimal("0.0001"))
        else:
            return base

    @staticmethod
    def kalshi_fee_cents(contracts: int, price_cents: int) -> int:
        """Compute Kalshi taker fee: ceil(rate * C * P * (1-P)).

        Tiered rates: 7% (<100 contracts), 5% (100-999), 3% (1000+).
        Floor: 2¢ per contract.
        """
        if contracts <= 0 or price_cents <= 0 or price_cents >= 100:
            return 0
        if contracts < 100:
            rate = 0.07
        elif contracts < 1000:
            rate = 0.05
        else:
            rate = 0.03
        p = price_cents / 100.0
        raw = rate * contracts * p * (1.0 - p)
        return max(2, math.ceil(raw * 100))

    # ── Anti-churn hysteresis ──────────────────────────────────────────

    def check_churn(self, ticker: str, side: str, edge: float) -> bool:
        """Return True if this trade is allowed (not a churn flip).

        Blocks direction flips on the same ticker within ``churn_cooldown_cycles``
        unless the edge has improved by at least ``churn_edge_improvement``.
        """
        cfg = self.config
        prev = self._last_trade.get(ticker)
        if prev is None:
            return True

        prev_side, prev_edge, prev_cycle = prev

        if side == prev_side:
            return True

        cycles_since = self._current_cycle - prev_cycle
        if cycles_since < cfg.churn_cooldown_cycles:
            edge_improvement = edge - prev_edge
            if edge_improvement < cfg.churn_edge_improvement:
                logger.debug(
                    "CHURN BLOCK%s: %s flip %s→%s after %d cycles "
                    "(need %d), edge_improve=%.4f (need %.4f)",
                    f" [{self._name}]" if self._name else "",
                    ticker, prev_side, side, cycles_since,
                    cfg.churn_cooldown_cycles, edge_improvement,
                    cfg.churn_edge_improvement,
                )
                return False

        return True

    def record_trade_direction(self, ticker: str, side: str, edge: float) -> None:
        """Record that we traded this ticker/side for churn tracking."""
        self._last_trade[ticker] = (side, edge, self._current_cycle)

    # ── Fee drag monitor ───────────────────────────────────────────────

    def record_fee(self, fee_cents: int, gross_edge_cents: int) -> None:
        """Record a trade's fee and gross edge for rolling fee drag calc."""
        self._fee_history.append((fee_cents, max(1, gross_edge_cents)))
        self._total_fees_cents += fee_cents
        self._update_fee_drag_state()

    def _update_fee_drag_state(self) -> None:
        """Check rolling fee drag and enable/disable tightening."""
        if len(self._fee_history) < 5:
            return

        total_fees = sum(f for f, _ in self._fee_history)
        total_edge = sum(e for _, e in self._fee_history)

        if total_edge <= 0:
            return

        fee_drag = total_fees / total_edge
        was_tightening = self._fee_drag_tightening
        self._fee_drag_tightening = fee_drag > self.config.max_fee_drag_pct

        if self._fee_drag_tightening and not was_tightening:
            logger.warning(
                "FEE DRAG WARNING%s: fees=%.0f%% of gross edge (threshold=%.0f%%) "
                "— tightening edge requirements 1.25x",
                f" [{self._name}]" if self._name else "",
                fee_drag * 100, self.config.max_fee_drag_pct * 100,
            )
        elif not self._fee_drag_tightening and was_tightening:
            logger.info("Fee drag normalized%s — relaxing edge requirements",
                        f" [{self._name}]" if self._name else "")

    def get_fee_drag_pct(self) -> float:
        """Current rolling fee drag as fraction of gross edge."""
        if len(self._fee_history) < 2:
            return 0.0
        total_fees = sum(f for f, _ in self._fee_history)
        total_edge = sum(e for _, e in self._fee_history)
        if total_edge <= 0:
            return 0.0
        return total_fees / total_edge

    @property
    def fee_drag_tightening(self) -> bool:
        return self._fee_drag_tightening

    # ── Effective limits (auto-reduce under fee stress) ─────────────────

    def effective_max_orders_per_cycle(self) -> int:
        """When fee drag is high, cut max orders per cycle in half (min 1)."""
        base = self.config.max_orders_per_cycle
        if self._fee_drag_tightening:
            return max(1, base // 2)
        return base

    def effective_max_exposure_pct(self) -> float:
        """When fee drag is high, reduce max exposure by 25%."""
        base = self.config.max_total_exposure_pct
        if self._fee_drag_tightening:
            return base * 0.75
        return base

    # ── Core sizing logic ──────────────────────────────────────────────

    def calculate_order_size(
        self,
        balance_cents: int,
        edge: Decimal,
        contract_price_cents: int,
        existing_position: int,
        total_open_positions: int,
    ) -> int:
        """Calculate safe order size using fractional Kelly + hard caps.

        Returns 0 if the trade should be skipped.
        """
        cfg = self.config

        # Gate 1: hard halts
        if self._halted:
            return 0
        if balance_cents < cfg.min_balance_cents:
            return 0
        if existing_position >= cfg.max_position_per_market:
            return 0
        if total_open_positions >= cfg.max_open_positions:
            return 0

        # Gate 2: contract price filter
        if contract_price_cents > cfg.max_contract_price_cents:
            return 0
        if contract_price_cents < cfg.min_contract_price_cents:
            return 0

        # Gate 3: fee-aware minimum edge
        required_edge = self.min_edge_for_price(contract_price_cents)
        if edge < required_edge:
            logger.debug(
                "REJECTED_BY_FEE%s: price=%d¢ edge=%.4f < required=%.4f "
                "(band=%s, tight=%s)",
                f" [{self._name}]" if self._name else "",
                contract_price_cents, float(edge), float(required_edge),
                "penny" if contract_price_cents <= 5
                else "midcurve" if 40 <= contract_price_cents <= 60
                else "sweet",
                self._fee_drag_tightening,
            )
            return 0

        # Gate 4: total exposure cap (auto-reduced under fee stress)
        max_exposure_cents = int(balance_cents * self.effective_max_exposure_pct())

        # Kelly sizing — implied probability from contract price, not fixed 0.5
        edge_f = float(edge)
        implied_prob = contract_price_cents / 100.0
        win_prob = min(0.95, max(0.05, implied_prob + edge_f))
        payout_ratio = (100 - contract_price_cents) / max(1, contract_price_cents)

        q = 1.0 - win_prob
        raw_kelly = (win_prob * payout_ratio - q) / payout_ratio
        raw_kelly = max(0.0, raw_kelly)

        frac_kelly = raw_kelly * cfg.kelly_fraction

        # Drawdown multiplier: halve sizing if in drawdown zone
        dd = self.get_drawdown_pct(balance_cents)
        if dd >= cfg.drawdown_reduce_pct:
            frac_kelly *= 0.5

        # Dollar amount to risk
        kelly_risk_cents = int(balance_cents * frac_kelly)
        max_risk_cents = int(balance_cents * cfg.max_risk_per_trade_pct)
        risk_cents = min(kelly_risk_cents, max_risk_cents, max_exposure_cents)

        # Convert to contracts
        if contract_price_cents <= 0:
            return 0
        contracts = risk_cents // contract_price_cents
        contracts = max(0, min(contracts, cfg.max_position_per_market - existing_position))

        # At minimum, if we can afford 1 contract and Kelly says go, do 1
        if contracts == 0 and risk_cents >= contract_price_cents and frac_kelly > 0:
            contracts = 1

        # Final fee sanity: reject if fee would eat >50% of expected profit
        if contracts > 0:
            expected_profit = int(float(edge) * contracts * contract_price_cents)
            fee = self.kalshi_fee_cents(contracts, contract_price_cents)
            if expected_profit > 0 and fee > expected_profit * 0.5:
                logger.debug(
                    "REJECTED_BY_FEE%s: price=%d¢ size=%d fee=%d¢ > 50%% "
                    "of expected_profit=%d¢ (fee_pct=%.0f%%)",
                    f" [{self._name}]" if self._name else "",
                    contract_price_cents, contracts, fee, expected_profit,
                    (fee / expected_profit) * 100,
                )
                return 0

        return contracts

    # ── Trade result tracking ──────────────────────────────────────────

    def record_trade_entry(self) -> None:
        """Record that a new trade was opened (fill confirmed).

        Called at fill time when PnL is still unknown.  Increments total_trades
        so the trade count is accurate while the position is open.  Win/loss
        classification and PnL are deferred to record_trade_result() at settlement.
        """
        self._total_trades += 1

    def record_trade_result(self, pnl_cents: int) -> None:
        """Record the settlement outcome of a previously opened trade.

        Called by OutcomeResolver._notify_bankroll_of_settlement() when a Kalshi
        market settles.  Does NOT touch total_trades — that was already incremented
        by record_trade_entry() at fill time.
        """
        self._total_pnl_cents += pnl_cents
        if pnl_cents >= 0:
            self._total_wins += 1
        else:
            self._total_losses += 1

    # ── Stats ──────────────────────────────────────────────────────────

    @property
    def total_trades(self) -> int:
        return self._total_trades

    @property
    def total_wins(self) -> int:
        return self._total_wins

    @property
    def total_losses(self) -> int:
        return self._total_losses

    @property
    def total_pnl_cents(self) -> int:
        return self._total_pnl_cents

    @property
    def total_fees_cents(self) -> int:
        return self._total_fees_cents

    @property
    def pending_trades(self) -> int:
        """Trades that have been entered but not yet settled."""
        return self._total_trades - (self._total_wins + self._total_losses)

    @property
    def win_rate(self) -> float:
        """Win rate as fraction of all entered trades.

        Uses _total_trades as denominator to include pending trades.
        This gives a more conservative estimate while trades are open.
        """
        if self._total_trades == 0:
            return 0.0
        return self._total_wins / self._total_trades

    def summary(self, balance_cents: int) -> str:
        """One-line bankroll summary string."""
        wr = self.win_rate * 100
        dd = self.get_drawdown_pct(balance_cents)
        fee_drag = self.get_fee_drag_pct()
        tight = " [TIGHT]" if self._fee_drag_tightening else ""
        return (
            f"Bankroll: ${balance_cents / 100:.2f} | "
            f"Peak: ${self._peak_balance_cents / 100:.2f} | "
            f"DD: {dd:.1%} | "
            f"Trades: {self._total_trades} "
            f"(W:{self._total_wins} L:{self._total_losses} WR:{wr:.0f}%) | "
            f"PnL: {self._total_pnl_cents:+d}¢ | "
            f"Fees: {self._total_fees_cents}¢ | "
            f"FeeDrag: {fee_drag:.0%}{tight}"
        )

    def status_snapshot(self, balance_cents: int = 0) -> dict:
        """Return a JSON-serialisable dict of engine state for API/UI."""
        dd = self.get_drawdown_pct(balance_cents)
        return {
            "halted": self._halted,
            "halt_reason": self._halt_reason,
            "peak_balance_cents": self._peak_balance_cents,
            "drawdown_pct": round(dd * 100, 2),
            "total_trades": self._total_trades,
            "total_wins": self._total_wins,
            "total_losses": self._total_losses,
            "pending_trades": self.pending_trades,
            "win_rate_pct": round(self.win_rate * 100, 1),
            "total_pnl_cents": self._total_pnl_cents,
            "total_fees_cents": self._total_fees_cents,
            "fee_drag_pct": round(self.get_fee_drag_pct() * 100, 1),
            "fee_drag_tightening": self._fee_drag_tightening,
            "vol_band": self._current_vol_band,
            "annualized_vol_pct": round(self._annualized_vol * 100, 1),
            "current_cycle": self._current_cycle,
            "effective_max_orders": self.effective_max_orders_per_cycle(),
            "effective_max_exposure_pct": round(self.effective_max_exposure_pct() * 100, 1),
        }
