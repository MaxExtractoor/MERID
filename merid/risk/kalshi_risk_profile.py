"""
KalshiRiskProfile — single entry point that combines all sizing inputs
into one per-trade dollar value for the BTC 15m lane.

Inputs (all optional; falls back gracefully when not provided):
  - Backtest Monte Carlo metrics  (prob_ruin, p5_eq)
  - Fractional Kelly              (yes_price_cents, est_prob)
  - Fear-Greed clamps             (FGState)
  - ATR volatility sizing         (atr_value, stop_dollars)
  - Drawdown guard                (equity, peak_equity)
  - Lifecycle base fraction       (from KalshiBotLifecycle)
  - Kalman sentiment adjustment   (raw_sentiment)

Resolution order (each step can only tighten, never loosen):
  1. lifecycle_frac              — state-machine base (0% / 1% / 2%)
  2. mc_adjust_risk_frac()       — halve if MC prob_ruin or p5 too high
  3. drawdown_guarded_risk_frac()— step-down at 5/7/10% drawdown
  4. dynamic_size()              — consec-loss + equity-high compounding
  5. vol_fg_position_size()      — ATR + FG extreme reduction
  6. kalshi_fractional_kelly_size()— quarter-Kelly cap
  7. kf_sentiment_adjust()       — ±20% Kalman sentiment nudge
  8. min(all above)              — take the tightest estimate
  9. Hard 5% equity cap

Usage:
    profile = KalshiRiskProfile(equity=10.52, peak_equity=10.52)
    profile.set_mc_metrics(mc_metrics)
    profile.set_fg(FGState(value=fg_index, combined=combined, confidence=conf))
    profile.set_atr(atr_value=0.04, stop_dollars=0.52)
    profile.set_lifecycle_frac(0.02)
    profile.set_sentiment(raw_combined=0.15)

    result = profile.compute(
        yes_price_cents=55,
        est_prob=0.62,
        consec_losses=1,
    )
    dollar_risk = result["final_size"]
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class KalshiRiskProfile:
    """
    Composable per-trade risk calculator for Kalshi BTC 15m lane.

    All inputs are set via setters before calling compute().
    compute() is idempotent — call it every cycle with fresh state.
    """

    equity: float
    peak_equity: float

    # Optional inputs — set via setters
    _mc_metrics: Optional[Dict[str, float]] = field(default=None, repr=False)
    _fg: Optional[object] = field(default=None, repr=False)          # FGState
    _atr_value: float = field(default=0.0, repr=False)
    _stop_dollars: float = field(default=0.0, repr=False)
    _lifecycle_frac: float = field(default=0.02, repr=False)
    _raw_sentiment: Optional[float] = field(default=None, repr=False)
    _kalman: Optional[object] = field(default=None, repr=False)       # SentimentKalman

    # ── Setters ───────────────────────────────────────────────────────────

    def set_mc_metrics(self, mc_metrics: Dict[str, float]) -> "KalshiRiskProfile":
        self._mc_metrics = mc_metrics
        return self

    def set_fg(self, fg) -> "KalshiRiskProfile":
        """Pass a FGState(value, combined, confidence)."""
        self._fg = fg
        return self

    def set_atr(self, atr_value: float, stop_dollars: float = 0.0) -> "KalshiRiskProfile":
        self._atr_value = atr_value
        self._stop_dollars = stop_dollars if stop_dollars > 0 else max(atr_value * self.equity, 0.01)
        return self

    def set_lifecycle_frac(self, frac: float) -> "KalshiRiskProfile":
        self._lifecycle_frac = max(0.0, min(frac, 0.05))
        return self

    def set_sentiment(self, raw_combined: float, kalman=None) -> "KalshiRiskProfile":
        self._raw_sentiment = raw_combined
        self._kalman = kalman
        return self

    # ── Core compute ──────────────────────────────────────────────────────

    def compute(
        self,
        yes_price_cents: int = 50,
        est_prob: float = 0.5,
        consec_losses: int = 0,
        initial_equity: Optional[float] = None,
        asset: Optional[str] = None,
        timeframe: Optional[str] = None,
    ) -> Dict:
        """
        Compute the final per-trade dollar risk.

        Returns a dict with all intermediate values for observability.

        Args:
            yes_price_cents: Current YES price in cents (1–99).
            est_prob:         Model-estimated win probability (0–1).
            consec_losses:    Consecutive losing trades (for dynamic_size).
            initial_equity:   Starting equity for compounding (defaults to current equity).
            asset:            Asset symbol for zone lookup (BTC/ETH/SOL/XRP/DOGE).
            timeframe:        Timeframe for zone lookup (15m/1h/4h/1d).
        """
        eq = self.equity
        peak = max(self.peak_equity, eq)
        init_eq = initial_equity if initial_equity is not None else eq

        # ── Step 1: lifecycle base fraction ──────────────────────────────
        base_frac = self._lifecycle_frac

        # ── Step 2: MC adjustment ─────────────────────────────────────────
        mc_frac = base_frac
        if self._mc_metrics:
            from merid.backtesting.monte_carlo import mc_adjust_risk_frac
            mc_frac = mc_adjust_risk_frac(base_frac, self._mc_metrics)

        # ── Step 3: drawdown guard ────────────────────────────────────────
        from merid.risk.promotion_engine import drawdown_guarded_risk_frac
        dd_frac = drawdown_guarded_risk_frac(
            equity=eq, peak_equity=peak, base_frac=mc_frac
        )

        # ── Step 4: dynamic size (consec-loss + compounding) ──────────────
        from merid.risk.promotion_engine import PerfState, dynamic_size
        dd_pct = (peak - eq) / max(peak, 1e-9)
        perf = PerfState(
            equity=eq,
            initial_equity=init_eq,
            drawdown=dd_pct,
            consec_losses=consec_losses,
        )
        dyn_size = dynamic_size(perf, base_risk_frac=dd_frac)

        # ── Step 5: ATR + FG volatility sizing ───────────────────────────
        vol_size: Optional[float] = None
        if self._fg is not None and self._atr_value > 0:
            from merid.sentiment.btc_risk_dial import vol_fg_position_size
            stop = max(self._stop_dollars, 0.01)
            vol_size = vol_fg_position_size(
                equity=eq,
                stop_dollars=stop,
                atr_value=self._atr_value,
                fg=self._fg,
            )

        # ── Step 6: fractional Kelly with volatility tax ──────────────────
        # Uses kelly_with_vol_tax (same formula as btc15m_lane._evaluate_risk)
        # so both callers produce identical sizing for the same inputs.
        kelly_size: Optional[float] = None
        if 0 < yes_price_cents < 100 and 0 < est_prob < 1:
            from merid.sentiment.btc_risk_dial import kelly_with_vol_tax
            # sigma=0 when no sentiment history available (no vol tax applied)
            sigma = 0.0
            if self._raw_sentiment is not None:
                # Use raw_sentiment magnitude as a vol proxy when no price series
                sigma = abs(self._raw_sentiment) * 0.02
            kelly_size = kelly_with_vol_tax(
                equity=eq,
                yes_price_cents=yes_price_cents,
                est_prob=est_prob,
                base_frac=0.25,
                sigma=sigma,
            )

        # ── Step 7: take minimum of all available estimates ───────────────
        candidates = [dyn_size]
        if vol_size is not None:
            candidates.append(vol_size)
        if kelly_size is not None:
            candidates.append(kelly_size)
        pre_kf_size = min(candidates)

        # ── Step 8: Kalman sentiment nudge (±20%) ─────────────────────────
        kf_size = pre_kf_size
        kf_mult = 1.0
        if self._raw_sentiment is not None:
            from merid.sentiment.kalman_sentiment import kf_sentiment_adjust
            kf_size = kf_sentiment_adjust(
                risk_dollars=pre_kf_size,
                raw_sentiment=self._raw_sentiment,
                kalman=self._kalman,
            )
            kf_mult = kf_size / max(pre_kf_size, 1e-9)

        # ── Step 9: hard 5% equity cap ────────────────────────────────────
        pre_zone_size = min(kf_size, 0.05 * eq)
        pre_zone_size = max(pre_zone_size, 0.0)

        # ── Step 10: drawdown zone multiplier ─────────────────────────────
        # Apply portfolio-level zone multiplier (green/yellow/orange/red).
        # This is the final, overriding step: even a perfectly-sized Kelly bet
        # should be cut when the portfolio is in drawdown.
        mult_dd = 1.0
        try:
            from merid.risk.drawdown_zones import get_drawdown_zone_manager
            _dzm = get_drawdown_zone_manager()
            mult_dd = _dzm.size_multiplier(dd_pct, asset=asset, timeframe=timeframe)
        except Exception:
            pass  # fail-open: no zone module → full size

        # ── Step 11: profit-lock multiplier ──────────────────────────────
        mult_lock = 1.0
        try:
            from merid.risk.profit_lock import get_profit_lock_engine
            mult_lock = get_profit_lock_engine().size_multiplier()
        except Exception:
            pass  # fail-open: no profit-lock engine → full size

        # ── Step 12: final composite size ─────────────────────────────────
        # size_final = Kelly × drawdown_zone_mult × profit_lock_mult
        final_size = pre_zone_size * mult_dd * mult_lock
        final_size = max(final_size, 0.0)

        return {
            "final_size": final_size,
            "lifecycle_frac": base_frac,
            "mc_frac": mc_frac,
            "dd_frac": dd_frac,
            "dyn_size": dyn_size,
            "vol_size": vol_size,
            "kelly_size": kelly_size,
            "pre_kf_size": pre_kf_size,
            "kf_mult": kf_mult,
            "kf_size": kf_size,
            "pre_zone_size": pre_zone_size,
            "mult_dd": mult_dd,
            "mult_lock": mult_lock,
            "drawdown_pct": dd_pct,
            "consec_losses": consec_losses,
            "yes_price_cents": yes_price_cents,
            "est_prob": est_prob,
        }
