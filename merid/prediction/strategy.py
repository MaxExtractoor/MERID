"""§3 Kalshi Strategy — Edge thresholds, time-to-expiry logic, position sizing.

Provides named, testable prediction-market playbooks for Kalshi:
- Same-market consistency checks (multi-outcome arb).
- Time-to-expiry aware behaviour (early speculative vs late arb).
- Explicit position sizing and exit rules.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Any, Dict, List, Optional

from merid.prediction.model import (
    ContractState,
    EdgeEstimate,
    MarketSnapshot,
    max_spot_age_seconds,
    PredictionMarketModel,
)

# P0-001 FIX: Use helper function instead of constant for consistency across all PM paths.
# This ensures MERID_PM_MAX_SPOT_AGE_SECONDS env var is respected everywhere.
SNAPSHOT_STALE_SECONDS = max_spot_age_seconds()
from merid.formulas import (
    FORMULAS_VERSION,
    AUDIT_SPEC_VERSION,
    get_version_info,
    generate_correlation_id,
    kelly_fraction,
    kelly_fraction_from_edge,
    quarter_kelly_size,
    PositionSizingInputs,
)
from utils.logger import get_logger

logger = get_logger("merid.prediction.strategy")

# Log version info on module load
_version_info = get_version_info()
logger.info(
    "Strategy module loaded | formulas=%s audit_spec=%s",
    _version_info["formulas_version"],
    _version_info["audit_spec_version"],
)


class SignalAction(str, Enum):
    """What the strategy recommends."""
    BUY_YES = "buy_yes"
    BUY_NO = "buy_no"
    SELL_YES = "sell_yes"
    SELL_NO = "sell_no"
    CLOSE = "close"
    HOLD = "hold"
    NO_ACTION = "no_action"
    QUOTE = "quote"  # For market making: provides bid/ask


class ExpiryPhase(str, Enum):
    """Time-to-expiry regime."""
    UNKNOWN = "unknown"    # expiry not known — skip trading (D02 fix)
    EARLY = "early"        # > 24 h to expiry
    MID = "mid"            # 4–24 h
    LATE = "late"          # 1–4 h
    TERMINAL = "terminal"  # < 1 h


@dataclass
class StrategyConfig:
    """Tunable parameters for KalshiStrategy."""
    # Edge thresholds (as probability fraction, e.g. 0.07 = 7 %)
    # These are aggressively conservative defaults — crypto prediction markets are
    # binary instruments with short tenors and high volatility.  Per-agent YAML
    # overrides (kalshi_agent_grid.yaml ``strategy:`` block) can tighten further.
    # MERID_PM_MIN_EDGE_* env vars override for runtime ops tuning.
    min_edge_early: Decimal = Decimal("0.08")      # 8% — Kalshi EARLY phase (>24h to expiry); raised for higher win-rate targeting
    min_edge_mid: Decimal = Decimal("0.07")         # 7% — MID (4-24h)
    min_edge_late: Decimal = Decimal("0.06")        # 6% — LATE (1-4h)
    min_edge_terminal: Decimal = Decimal("0.06")    # 6% — TERMINAL (<1h); equal to late — terminal contracts carry max noise, don't relax here
    min_arb_edge: Decimal = Decimal("0.005")        # 0.5 % for pure arb (risk-free)

    # Position sizing
    max_contracts_per_market: int = 100
    max_contracts_per_order: int = 25
    kelly_fraction: Decimal = Decimal("0.25")       # Quarter-Kelly

    # Exit rules
    profit_target_pct: Decimal = Decimal("0.15")    # Take profit at 15 %
    stop_loss_pct: Decimal = Decimal("0.10")         # Cut at 10 % loss
    max_hold_hours: Decimal = Decimal("48")          # Force close after 48 h

    # Liquidity (post-edge guard — see _apply_liquidity_guard_after_edge).
    # Defaults are off: Kalshi often omits or zeroes 24h volume on short-dated crypto contracts;
    # set YAML ``min_volume`` / ``min_open_interest`` or env MERID_PM_MIN_VOLUME when you want a floor.
    min_volume: Decimal = Decimal("0")
    min_open_interest: Decimal = Decimal("0")
    min_depth_contracts: int = 5                      # Min depth at best price

    # Market Making
    mm_max_spread_cents: Decimal = Decimal("10")     # Don't quote if spread > 10c
    mm_target_spread_cents: Decimal = Decimal("2")   # Try to quote 2c spread
    mm_inventory_limit: int = 50                     # Max contracts to hold per side
    mm_skew_factor: Decimal = Decimal("0.5")         # How much to lean based on inventory

    # Confidence — raised from 0.5 to 0.60 to require meaningful model conviction.
    # Combined with higher edge thresholds, this is the primary lever for ~75% win-rate targeting.
    # Override per-agent via YAML ``strategy: min_confidence: 0.65`` or env MERID_PM_MIN_CONFIDENCE.
    min_confidence: Decimal = Decimal("0.60")

    # Archetype sentiment / regime tunables (YAML ``strategy:`` + pm_profiles + env)
    contrarian_sentiment_min: float = 75.0
    contrarian_model_gap_min: float = 0.10
    vol_breakout_neutral_low: float = 35.0
    vol_breakout_neutral_high: float = 65.0


@dataclass
class StrategySignal:
    """Output of strategy evaluation for one market."""
    market_id: str
    action: SignalAction
    side: str                  # "yes", "no", or "both"
    contracts: int             # Recommended size
    limit_price_cents: Optional[int] = None
    bid_price_cents: Optional[int] = None  # For QUOTE
    ask_price_cents: Optional[int] = None  # For QUOTE
    edge: Optional[EdgeEstimate] = None
    phase: Optional[ExpiryPhase] = None
    reason: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    correlation_id: Optional[str] = None  # [AGENT_AUDIT: Section 9] trace chain from DISCOVER
    # Optional structured gate context for PM_SIGNAL (thresholds, floors) — observability only
    eval_context: Dict[str, Any] = field(default_factory=dict)
    # Behavioral exploitation adjustments for logging
    behavioral_adjustments: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "market_id": self.market_id,
            "action": self.action.value,
            "side": self.side,
            "contracts": self.contracts,
            "limit_price_cents": self.limit_price_cents,
            "bid_price_cents": self.bid_price_cents,
            "ask_price_cents": self.ask_price_cents,
            "phase": self.phase.value if self.phase else None,
            "reason": self.reason,
            "net_edge": str(self.edge.net_edge) if self.edge else None,
            "timestamp": self.timestamp.isoformat(),
            "eval_context": dict(self.eval_context) if self.eval_context else {},
        }


@dataclass
class PositionState:
    """Tracks an open position for exit-rule evaluation."""
    market_id: str
    side: str
    contracts: int
    avg_entry_cents: Decimal
    opened_at: datetime
    current_price_cents: Optional[Decimal] = None
    unrealized_pnl_cents: Optional[Decimal] = None
    correlation_id: Optional[str] = None  # [AGENT_AUDIT: Section 9] trace chain from DISCOVER


class KalshiStrategy:
    """Prediction-market strategy dedicated to Kalshi.

    Evaluates MarketSnapshots and produces StrategySignals.
    """

    def __init__(
        self,
        config: Optional[StrategyConfig] = None,
        model: Optional[PredictionMarketModel] = None,
        agent_name: str = "strategy",
    ):
        self.config = config or StrategyConfig()
        self.model = model or PredictionMarketModel()
        self._agent_name = agent_name
        self._positions: Dict[str, PositionState] = {}

    # ------------------------------------------------------------------
    # Expiry phase
    # ------------------------------------------------------------------

    def _expiry_phase(self, hours_left: Optional[Decimal]) -> ExpiryPhase:
        if hours_left is None:
            return ExpiryPhase.UNKNOWN  # unknown expiry — skip trading (D02 fix)
        if hours_left > 24:
            return ExpiryPhase.EARLY
        if hours_left > 4:
            return ExpiryPhase.MID
        if hours_left > 1:
            return ExpiryPhase.LATE
        return ExpiryPhase.TERMINAL

    def _min_edge_for_phase(self, phase: ExpiryPhase) -> Decimal:
        return {
            ExpiryPhase.UNKNOWN: Decimal("999"),  # unreachable — UNKNOWN exits before edge check
            ExpiryPhase.EARLY: self.config.min_edge_early,
            ExpiryPhase.MID: self.config.min_edge_mid,
            ExpiryPhase.LATE: self.config.min_edge_late,
            ExpiryPhase.TERMINAL: self.config.min_edge_terminal,
        }[phase]

    # ------------------------------------------------------------------
    # Position sizing (quarter-Kelly)
    # ------------------------------------------------------------------

    def _sentiment_size_factor(self, snapshot: "MarketSnapshot") -> float:
        """Compute a 0.35–1.0 size_factor from fear/greed and vol regime.

        This is deliberately downside-only (max 1.0) so the PositionSizer
        hourly exposure cap is never bypassed by sentiment boosting.
        """
        factor = 1.0

        if snapshot.sentiment_global is not None:
            fg_score = snapshot.sentiment_global
            if fg_score <= 20 or fg_score >= 80:
                factor *= 0.5
            elif fg_score <= 30 or fg_score >= 70:
                factor *= 0.75

        if snapshot.sentiment_regime:
            regime = snapshot.sentiment_regime.lower()
            if "extreme" in regime:
                factor *= 0.7

        return max(0.35, min(1.0, factor))

    def _pm_vol_band_size_factor(self, snapshot: "MarketSnapshot") -> float:
        """Shrink/expand contracts from PM ``crypto_pm_vol_bridge`` (low/mid/high band)."""
        m = getattr(snapshot, "crypto_vol_size_mult", None)
        if m is None:
            return 1.0
        try:
            return max(0.1, min(1.5, float(m)))
        except (TypeError, ValueError):
            return 1.0

    def _kelly_size_with_sentiment(
        self,
        edge: EdgeEstimate,
        phase: ExpiryPhase,
        snapshot: "MarketSnapshot",
        correlation_id: Optional[str] = None,
    ) -> int:
        """Compute sentiment-adjusted position size.

        Passes the sentiment factor directly to PositionSizer.compute() as
        ``size_factor`` so the per-underlying hourly exposure cap is always
        enforced on the already-reduced size, not bypassed.

        Args:
            edge: Edge estimate
            phase: Expiry phase
            snapshot: Market snapshot with sentiment data
            correlation_id: Trace chain ID from DISCOVER

        Returns:
            Adjusted contract count
        """
        size_factor = self._sentiment_size_factor(snapshot) * self._pm_vol_band_size_factor(
            snapshot
        )
        return self._kelly_size(edge, phase, size_factor=size_factor, correlation_id=correlation_id)

    def _kelly_size(
        self,
        edge: EdgeEstimate,
        phase: ExpiryPhase,
        size_factor: float = 1.0,
        correlation_id: Optional[str] = None,
    ) -> int:
        """Compute position size via PositionSizer (fee-aware, adaptive Kelly).

        Delegates to the singleton PositionSizer which applies:
        - Fractional Kelly with Kalshi fee schedule
        - PF/expectancy scaling gates
        - Drawdown and vol-based adaptive shrinkage
        - Per-underlying hourly exposure caps

        ``size_factor`` (0.0–1.0) is a caller-supplied multiplier (e.g. from
        sentiment) applied *inside* PositionSizer so the hourly cap is always
        respected on the final contract count.

        Falls back to a simple inline calculation if the sizer is unavailable.
        
        [AGENT_AUDIT: Section 5] SIZE stage — Kelly/quarter-Kelly sizing with traceability.
        """
        # [TRACE] SIZE_DECISION entry
        if correlation_id:
            logger.info(
                "[TRACE] SIZE_DECISION | corr_id=%s | agent=%s | edge=%.4f | phase=%s | size_factor=%.2f | formulas=%s | audit_spec=%s",
                correlation_id,
                self._agent_name,
                float(edge.net_edge) if edge else 0.0,
                phase.value if phase else "unknown",
                size_factor,
                FORMULAS_VERSION,
                AUDIT_SPEC_VERSION,
            )
        _bankroll_cents = 0
        try:
            from merid.event_venues.kalshi.position_sizer import get_position_sizer
            sizer = get_position_sizer()

            # Convert edge fields to sizer inputs
            edge_pct = float(edge.net_edge) * 100.0  # fraction → percent
            market_prob = float(edge.market_prob)
            price_cents = max(1, min(99, int(round(market_prob * 100))))

            # Phase-based vol proxy: terminal contracts are noisier
            local_vol_pct = {
                ExpiryPhase.EARLY: 10.0,
                ExpiryPhase.MID: 15.0,
                ExpiryPhase.LATE: 20.0,
                ExpiryPhase.TERMINAL: 35.0,
            }.get(phase, 15.0)

            # CRITICAL FIX: Use unified v2 bankroll service for consistent sizing/risk
            # PM SIZING WIRING: All position sizing must use unified bankroll as single source of truth
            _bankroll_cents = 0
            try:
                from merid.event_venues.kalshi import get_equity_for_risk_calc_sync, get_summary_sync
                _effective_usd = get_equity_for_risk_calc_sync()
                _summary = get_summary_sync()
                if _effective_usd and _effective_usd > 0:
                    _bankroll_cents = int(_effective_usd * 100)
                    _state = _summary.state.value if _summary else "unknown"
                    logger.debug(
                        "[strategy] Using effective bankroll: $%.2f (state=%s)",
                        _effective_usd,
                        _state
                    )
                else:
                    # Effective bankroll is zero - trading should halt
                    logger.error(
                        "[TAINTED_PATH] strategy bankroll: effective_equity=$%.2f — "
                        "rejecting sizing request; check min_operational_balance or max_riskable caps",
                        _effective_usd,
                    )
                    # Emit alert for operator visibility
                    try:
                        from core.event_bus import get_event_bus
                        get_event_bus().emit("risk.bankroll_unavailable", {
                            "agent": self._agent_name,
                            "equity_usd": _effective_usd,
                            "reason": "zero_or_negative_equity",
                            "action": "reject_sizing",
                        })
                    except Exception:
                        pass
                    
                    # Tamper-evident audit log
                    try:
                        from core.risk_audit_chain import get_risk_audit_chain
                        get_risk_audit_chain().log_event("risk.bankroll_unavailable", {
                            "agent": self._agent_name,
                            "equity_usd": _effective_usd,
                            "reason": "zero_or_negative_equity",
                            "action": "reject_sizing",
                            "edge_pct": edge_pct,
                            "phase": phase.value if phase else None,
                        })
                    except Exception as _audit_exc:
                        logger.debug("Audit log failed (non-critical): %s", _audit_exc)
                    
                    return 0  # Fail closed: no size when bankroll unknown
            except Exception as _brk_exc:
                logger.error(
                    "[TAINTED_PATH] strategy bankroll: unified bankroll service unavailable (%s) — "
                    "rejecting sizing request; no fallback permitted",
                    _brk_exc,
                )
                # Emit alert for operator visibility
                try:
                    from core.event_bus import get_event_bus
                    get_event_bus().emit("risk.bankroll_unavailable", {
                        "agent": self._agent_name,
                        "reason": "risk_manager_exception",
                        "error": str(_brk_exc),
                        "action": "reject_sizing",
                    })
                except Exception:
                    pass
                
                # Tamper-evident audit log
                try:
                    from core.risk_audit_chain import get_risk_audit_chain
                    get_risk_audit_chain().log_event("risk.bankroll_unavailable", {
                        "agent": self._agent_name,
                        "reason": "risk_manager_exception",
                        "error": str(_brk_exc)[:200],
                        "action": "reject_sizing",
                        "edge_pct": edge_pct,
                        "phase": phase.value if phase else None,
                    })
                except Exception as _audit_exc:
                    logger.debug("Audit log failed (non-critical): %s", _audit_exc)
                
                return 0  # Fail closed: no size when bankroll unavailable

            # BUG-E fix: read per-underlying correlated notional to estimate
            # current open contracts, so the hourly exposure cap actually fires.
            _current_exposure = 0
            try:
                _underlying = self._agent_name.split("_")[0].upper()
                from merid.event_venues.kalshi.category_exposure import (
                    get_category_exposure_tracker,
                )
                _corr_notional = (
                    get_category_exposure_tracker()
                    .get_snapshot()
                    .corr_notional.get(_underlying, 0.0)
                )
                if price_cents > 0:
                    _current_exposure = int(_corr_notional * 100 / price_cents)
            except Exception:
                pass

            # BUG-L fix: wire PaperSession IntervalPnL stats and governance
            # factor into sizer so _pf_scale() gets real data instead of
            # always returning the minimum 0.125× floor.
            _profit_factor = 0.0
            _expectancy_cents = 0.0
            _total_trades = 0
            try:
                from merid.prediction.paper_session import get_paper_session
                _ps = get_paper_session()
                _pil = _ps._intervals.get(self._agent_name)
                if _pil:
                    _pf = _pil.profit_factor
                    _profit_factor = _pf if _pf != float("inf") else 5.0
                    _expectancy_cents = _pil.expectancy_cents
                    _total_trades = _pil.total_trades
                # Governance factor (1.0 / 0.5 / 0.0) multiplied into the
                # caller-supplied sentiment size_factor so the session halt/
                # downsize state propagates all the way into position sizing.
                _gov = _ps.get_size_factor(self._agent_name)
                size_factor = size_factor * _gov
            except Exception:
                pass

            size = sizer.compute(
                agent_name=self._agent_name,
                edge_pct=edge_pct,
                price_cents=price_cents,
                bankroll_cents=_bankroll_cents,
                local_vol_pct=local_vol_pct,
                size_factor=max(0.0, min(1.0, size_factor)),
                current_exposure_contracts=_current_exposure,
                profit_factor=_profit_factor,
                expectancy_cents=_expectancy_cents,
                total_trades=_total_trades,
            )
            return min(size, self.config.max_contracts_per_order)
        except Exception as _sze:
            logger.warning(
                "position sizer unavailable — falling back to un-gated Kelly "
                "(no fee/PF/drawdown gates): %s", _sze
            )

        # Fallback: use merid.formulas canonical Kelly implementation
        # [AGENT_AUDIT: Section 5] — quarter-Kelly sizing from source of truth
        try:
            # Convert edge to float for formulas module
            edge_float = float(edge.net_edge)
            market_prob_float = float(edge.market_prob)
            price_cents = max(1, min(99, int(round(market_prob_float * 100))))
            
            # Determine fractional Kelly based on phase
            fractional_kelly = float(self.config.kelly_fraction)  # 0.25 default
            if phase == ExpiryPhase.EARLY:
                fractional_kelly *= 1.5
            elif phase == ExpiryPhase.MID:
                fractional_kelly *= 1.2
            elif phase == ExpiryPhase.TERMINAL:
                fractional_kelly *= 0.5
            
            # Apply sentiment size_factor
            fractional_kelly *= max(0.0, min(1.0, size_factor))
            
            # Use canonical quarter_kelly_size from merid.formulas
            # CRITICAL: Use validated bankroll or fail closed
            if _bankroll_cents <= 0:
                logger.error(
                    "[TAINTED_PATH] quarter_kelly_size fallback: no valid bankroll "
                    "(_bankroll_cents=%s) — rejecting sizing", _bankroll_cents
                )
                # Audit log
                try:
                    from core.risk_audit_chain import get_risk_audit_chain
                    get_risk_audit_chain().log_event("risk.bankroll_unavailable", {
                        "agent": self._agent_name,
                        "reason": "quarter_kelly_fallback_no_bankroll",
                        "bankroll_cents": _bankroll_cents,
                        "action": "reject_sizing",
                        "phase": phase.value if phase else None,
                    })
                except Exception:
                    pass
                return 0
            
            inputs = PositionSizingInputs(
                bankroll_cents=_bankroll_cents,  # Use validated bankroll
                edge=edge_float,
                price_cents=price_cents,
                fractional_kelly=fractional_kelly,
            )
            
            contracts, kelly_used, warning = quarter_kelly_size(inputs)
            if warning:
                logger.debug("quarter_kelly_size warning: %s", warning)
            
            # Apply max contracts per order cap
            return min(contracts, self.config.max_contracts_per_order)
            
        except Exception as _formula_err:
            logger.error(
                "merid.formulas Kelly calculation failed: %s — "
                "this should never happen; check formulas module health",
                _formula_err
            )
            return 0

    # ------------------------------------------------------------------
    # Entry evaluation
    # ------------------------------------------------------------------

    def _emit_pm_signal_log(
        self,
        sig: StrategySignal,
        snapshot: MarketSnapshot,
        archetype: str,
        correlation_id: Optional[str],
    ) -> None:
        """Structured observability for PM: why NO_ACTION vs actionable."""
        if os.getenv("MERID_PM_SIGNAL_LOG", "true").lower() not in (
            "1",
            "true",
            "yes",
            "on",
        ):
            return
        ne = None
        if sig.edge and hasattr(sig.edge, "net_edge"):
            try:
                ne = float(sig.edge.net_edge)
            except (TypeError, ValueError):
                ne = None
        conf = None
        if sig.edge and hasattr(sig.edge, "confidence"):
            try:
                conf = float(sig.edge.confidence)
            except (TypeError, ValueError):
                conf = None
        ph = sig.phase.value if sig.phase else None
        _ctx = ""
        if getattr(sig, "eval_context", None):
            try:
                import json as _json

                _ctx = _json.dumps(sig.eval_context, default=str, sort_keys=True)
                if len(_ctx) > 450:
                    _ctx = _ctx[:450] + "…"
            except Exception:
                _ctx = str(sig.eval_context)[:450]
        
        # Behavioral exploitation context
        _beh_patterns = "—"
        _beh_size_mult = "—"
        if hasattr(sig, "behavioral_adjustments") and sig.behavioral_adjustments:
            _ba = sig.behavioral_adjustments
            _patterns = _ba.get("patterns_detected", [])
            _beh_patterns = ",".join(_patterns) if _patterns else "none"
            _beh_size_mult = f"{_ba.get('size_multiplier', 1.0):.2f}"
        
        _inc_spot = os.getenv("MERID_PM_SIGNAL_INCLUDE_SPOT_STRIKE", "true").lower() in (
            "1", "true", "yes", "on",
        )
        _spot_s = "—"
        _strike_s = "—"
        _dist_frac_s = "—"
        _dist_pct_human = "—"
        _basis = getattr(snapshot, "spot_strike_basis_note", "") or "—"
        if _inc_spot:
            sp = getattr(snapshot, "spot_price_usd", None)
            st = getattr(snapshot, "strike_price_usd", None)
            di = getattr(snapshot, "distance_to_strike_pct", None)
            _spot_s = str(sp) if sp is not None else "—"
            _strike_s = str(st) if st is not None else "—"
            if di is not None:
                try:
                    _df = float(di)
                    _dist_frac_s = f"{_df:.6f}"
                    _dist_pct_human = f"{_df * 100.0:.2f}"
                except (TypeError, ValueError):
                    _dist_frac_s = str(di)
                    _dist_pct_human = "—"
        if sig.action == SignalAction.NO_ACTION:
            if _inc_spot:
                logger.info(
                    "[PM_SIGNAL] agent=%s market=%s archetype=%s action=%s phase=%s "
                    "net_edge=%s confidence=%s spot=%s strike=%s dist_frac=%s dist_pct_pct=%s "
                    "spot_strike_basis=%s reason=%s corr_id=%s ctx=%s",
                    self._agent_name,
                    snapshot.market_id,
                    archetype,
                    sig.action.value,
                    ph,
                    f"{ne:.4f}" if ne is not None else "—",
                    f"{conf:.3f}" if conf is not None else "—",
                    _spot_s,
                    _strike_s,
                    _dist_frac_s,
                    _dist_pct_human,
                    _basis,
                    (sig.reason or "")[:500],
                    correlation_id or "—",
                    _ctx or "—",
                )
            else:
                logger.info(
                    "[PM_SIGNAL] agent=%s market=%s archetype=%s action=%s phase=%s "
                    "net_edge=%s confidence=%s reason=%s corr_id=%s ctx=%s",
                    self._agent_name,
                    snapshot.market_id,
                    archetype,
                    sig.action.value,
                    ph,
                    f"{ne:.4f}" if ne is not None else "—",
                    f"{conf:.3f}" if conf is not None else "—",
                    (sig.reason or "")[:500],
                    correlation_id or "—",
                    _ctx or "—",
                )
        else:
            if _inc_spot:
                logger.info(
                    "[PM_SIGNAL] agent=%s market=%s archetype=%s action=%s phase=%s "
                    "contracts=%s net_edge=%s confidence=%s spot=%s strike=%s dist_frac=%s "
                    "dist_pct_pct=%s spot_strike_basis=%s behavioral=%s beh_mult=%s corr_id=%s",
                    self._agent_name,
                    snapshot.market_id,
                    archetype,
                    sig.action.value,
                    ph,
                    sig.contracts,
                    f"{ne:.4f}" if ne is not None else "—",
                    f"{conf:.3f}" if conf is not None else "—",
                    _spot_s,
                    _strike_s,
                    _dist_frac_s,
                    _dist_pct_human,
                    _basis,
                    _beh_patterns,
                    _beh_size_mult,
                    correlation_id or "—",
                )
            else:
                logger.debug(
                    "[PM_SIGNAL] agent=%s market=%s archetype=%s action=%s phase=%s "
                    "contracts=%s net_edge=%s behavioral=%s beh_mult=%s corr_id=%s",
                    self._agent_name,
                    snapshot.market_id,
                    archetype,
                    sig.action.value,
                    ph,
                    sig.contracts,
                    f"{ne:.4f}" if ne is not None else "—",
                    _beh_patterns,
                    _beh_size_mult,
                    correlation_id or "—",
                )

    def evaluate(
        self,
        snapshot: MarketSnapshot,
        archetype: str = "directional",
        correlation_id: Optional[str] = None,
    ) -> StrategySignal:
        sig = self._evaluate_core(snapshot, archetype, correlation_id)
        self._emit_pm_signal_log(sig, snapshot, archetype, correlation_id)
        return sig

    def _evaluate_core(
        self,
        snapshot: MarketSnapshot,
        archetype: str = "directional",
        correlation_id: Optional[str] = None,
    ) -> StrategySignal:
        """Evaluate a market snapshot and produce a signal (inner implementation).

        DECISION HIERARCHY (highest priority first):
        ============================================
        Layer 1: Hard risk & sanity gates
          - Expiry known? (UNKNOWN expiry → NO_ACTION)
          - Staleness check (>30s old → NO_ACTION)
          - Market state (not TRADING/CLOSING → NO_ACTION)
        Volume/OI minimums run **after** archetype evaluation (edge-first) — see
        ``_apply_liquidity_guard_after_edge``.

        Layer 2: Global/regime filters
          - Sentiment regime (extreme_fear/greed, turbulent)
          - Applied via _sentiment_size_factor() and _sentiment_edge_floor()
        These modulate sizing and edge thresholds but don't veto directly.

        Layer 3: Structure (FVG zones + Fib context)
          - FVG pressure/direction vs trade alignment
          - Confluence with trend/RSI
          - Applied as multiplicative conviction factor to final size
        Never flips direction against higher-priority consensus.

        Layer 4: Momentum/microstructure entries
          - MACD/RSI signals
          - Orderbook forecaster imbalance
          - Edge estimates from models
        Only evaluated if all higher layers pass.

        Archetypes:
        - directional: Takes YES/NO positions based on speculative edge.
        - market_maker: Quotes two-sided markets.
        - arbitrage: Specifically looks for cross-market or internal arb.
        - contrarian: Fades extremes when model disagrees.
        - regime_switch: Rides momentum on sentiment shifts.
        - vol_breakout: Trades elevated vol with book imbalance.
        
        [AGENT_AUDIT: Section 9] Accepts correlation_id from DISCOVER for trace chain.
        """
        # Log ANALYZE stage entry with correlation_id
        if correlation_id:
            logger.info(
                "[TRACE] ANALYZE_START | corr_id=%s | market=%s | archetype=%s",
                correlation_id,
                snapshot.market_id,
                archetype,
            )
        
        phase = self._expiry_phase(snapshot.time_to_expiry_hours)

        # D02 fix: reject markets with unknown expiry — we cannot safely size
        # or risk-manage a contract whose time-to-expiry is unknown.
        if phase == ExpiryPhase.UNKNOWN:
            return StrategySignal(
                market_id=snapshot.market_id,
                action=SignalAction.NO_ACTION,
                side="none",
                contracts=0,
                phase=phase,
                reason="Market expiry unknown — skipping to avoid unsized risk.",
                correlation_id=correlation_id,
            )

        # 0. Staleness gate — reject orders on stale market data
        now_utc = datetime.now(timezone.utc)
        snap_age_s = (now_utc - snapshot.timestamp).total_seconds()
        if snap_age_s > SNAPSHOT_STALE_SECONDS:
            stale_int = int(snap_age_s)
            try:
                from merid.prediction.alerts import get_alert_manager
                get_alert_manager().fire_staleness(snapshot.market_id, stale_int)
            except Exception:
                pass
            logger.warning(
                "Stale snapshot for %s (%ds old) — skipping evaluation",
                snapshot.market_id, stale_int,
            )
            return StrategySignal(
                market_id=snapshot.market_id,
                action=SignalAction.NO_ACTION,
                side="none",
                contracts=0,
                phase=phase,
                reason=f"Stale snapshot: {stale_int}s old (max {SNAPSHOT_STALE_SECONDS}s).",
                correlation_id=correlation_id,
            )

        # 1. State filter
        if snapshot.state not in (ContractState.TRADING, ContractState.CLOSING):
            return StrategySignal(
                market_id=snapshot.market_id,
                action=SignalAction.NO_ACTION,
                side="none",
                contracts=0,
                phase=phase,
                reason=f"Market state is {snapshot.state.value}, not tradeable.",
                correlation_id=correlation_id,
            )

        # 1b. Spot–strike distance veto (optional — ``MERID_PM_SPOT_STRIKE_VETO_TRADES``)
        if getattr(snapshot, "spot_strike_veto", False):
            _dist = getattr(snapshot, "distance_to_strike_pct", None)
            return StrategySignal(
                market_id=snapshot.market_id,
                action=SignalAction.NO_ACTION,
                side="none",
                contracts=0,
                phase=phase,
                reason=getattr(snapshot, "spot_strike_veto_reason", None) or "spot_strike_veto",
                correlation_id=correlation_id,
                eval_context={
                    "block": "spot_strike_veto",
                    "distance_to_strike_pct": str(_dist) if _dist is not None else "",
                    "spot": str(snapshot.spot_price_usd) if getattr(snapshot, "spot_price_usd", None) is not None else "",
                    "strike": str(snapshot.strike_price_usd) if getattr(snapshot, "strike_price_usd", None) is not None else "",
                    "resolved_asset": getattr(snapshot, "resolved_asset", None) or "",
                    "spot_strike_basis": getattr(snapshot, "spot_strike_basis_note", "") or "",
                },
            )

        # 2. Archetype evaluation (edge / conviction / Kelly) — liquidity guard runs after.
        if archetype == "market_maker":
            sig = self._evaluate_mm(snapshot, phase, correlation_id)
        elif archetype == "arbitrage":
            sig = self._evaluate_arb(snapshot, phase, correlation_id)
        elif archetype == "contrarian":
            sig = self._evaluate_contrarian(snapshot, phase, correlation_id)
        elif archetype == "regime_switch":
            sig = self._evaluate_regime_switch(snapshot, phase, correlation_id)
        elif archetype == "vol_breakout":
            sig = self._evaluate_vol_breakout(snapshot, phase, correlation_id)
        else:
            sig = self._evaluate_directional(snapshot, phase, correlation_id)

        return self._apply_liquidity_guard_after_edge(snapshot, sig, phase, correlation_id)

    def _apply_liquidity_guard_after_edge(
        self,
        snapshot: MarketSnapshot,
        signal: StrategySignal,
        phase: ExpiryPhase,
        correlation_id: Optional[str],
    ) -> StrategySignal:
        """Enforce min volume/OI only after edge evaluation so NO_ACTION reasons reflect model thresholds first.

        If ``min_volume`` / ``min_open_interest`` are 0, that check is skipped (see StrategyConfig defaults).
        """
        if signal.action in (SignalAction.NO_ACTION, SignalAction.HOLD):
            return signal
        if signal.action == SignalAction.CLOSE:
            return signal

        parts: List[str] = []
        if self.config.min_volume > 0 and snapshot.volume < self.config.min_volume:
            parts.append(f"volume {snapshot.volume} < {self.config.min_volume}")
        if self.config.min_open_interest > 0 and snapshot.open_interest < self.config.min_open_interest:
            parts.append(f"OI {snapshot.open_interest} < {self.config.min_open_interest}")

        if not parts:
            return signal

        edge_hint = ""
        if signal.edge is not None and getattr(signal.edge, "net_edge", None) is not None:
            try:
                edge_hint = f" Edge had cleared strategy path (net_edge={signal.edge.net_edge:.4f})."
            except Exception:
                edge_hint = " Edge was present before liquidity veto."

        return StrategySignal(
            market_id=snapshot.market_id,
            action=SignalAction.NO_ACTION,
            side=signal.side,
            contracts=0,
            limit_price_cents=None,
            bid_price_cents=None,
            ask_price_cents=None,
            edge=signal.edge,
            phase=phase,
            reason=f"Liquidity guard: {'; '.join(parts)}.{edge_hint}",
            correlation_id=correlation_id or signal.correlation_id,
            eval_context={
                "min_volume": str(self.config.min_volume),
                "min_open_interest": str(self.config.min_open_interest),
                "block": "liquidity_guard",
            },
        )

    def _evaluate_directional(
        self,
        snapshot: MarketSnapshot,
        phase: ExpiryPhase,
        correlation_id: Optional[str] = None,
    ) -> StrategySignal:
        """Standard directional strategy."""
        # 3. Arb check (high priority even for directional)
        arb_edges = [e for e in snapshot.edges if e.edge_type == "arb"]
        if arb_edges:
            best_arb = max(arb_edges, key=lambda e: e.net_edge)
            if best_arb.net_edge >= self.config.min_arb_edge:
                return StrategySignal(
                    market_id=snapshot.market_id,
                    action=SignalAction.BUY_YES,  # arb buys both sides
                    side="both",
                    contracts=self.config.max_contracts_per_order,
                    edge=best_arb,
                    phase=phase,
                    reason=f"Pure arb detected: net edge {best_arb.net_edge:.4f}.",
                    correlation_id=correlation_id,
                )

        # 4. Best speculative edge
        spec_edges = [e for e in snapshot.edges if e.edge_type == "speculative"]
        if not spec_edges:
            return StrategySignal(
                market_id=snapshot.market_id,
                action=SignalAction.NO_ACTION,
                side="none",
                contracts=0,
                phase=phase,
                reason="No actionable edge found.",
                correlation_id=correlation_id,
            )

        best = max(spec_edges, key=lambda e: e.net_edge)

        # 5. Edge threshold
        min_edge = self._min_edge_for_phase(phase)
        if best.net_edge < min_edge:
            return StrategySignal(
                market_id=snapshot.market_id,
                action=SignalAction.NO_ACTION,
                side=best.side,
                contracts=0,
                edge=best,
                phase=phase,
                reason=f"Edge {best.net_edge:.4f} below {phase.value} threshold {min_edge}.",
                correlation_id=correlation_id,
                eval_context={
                    "min_edge_threshold": str(min_edge),
                    "phase": phase.value,
                    "archetype": "directional",
                    "block": "edge_below_threshold",
                },
            )

        # Confidence filter
        if best.confidence < self.config.min_confidence:
            return StrategySignal(
                market_id=snapshot.market_id,
                action=SignalAction.NO_ACTION,
                side=best.side,
                contracts=0,
                edge=best,
                phase=phase,
                reason=f"Confidence {best.confidence} below minimum {self.config.min_confidence}.",
                correlation_id=correlation_id,
                eval_context={
                    "min_confidence": str(self.config.min_confidence),
                    "block": "confidence_below_minimum",
                },
            )

        # 6. HARD PROBABILITY GATE - 80%+ hit-rate targeting
        
        # First: Validate model_prob p is calibrated and sane
        p = float(best.model_prob) if best.model_prob is not None else None
        
        # Check for NaN, None, or out-of-bounds
        import math
        if p is None or math.isnan(p) or p < 0.0 or p > 1.0:
            return StrategySignal(
                market_id=snapshot.market_id,
                action=SignalAction.NO_ACTION,
                side=best.side,
                contracts=0,
                edge=best,
                phase=phase,
                reason=f"blocked: invalid_model_prob p={p} (must be calibrated 0-1)",
                correlation_id=correlation_id,
            )
        
        # Compute probability edge = |p - 0.5|
        prob_edge = abs(p - 0.5)
        
        # Extract asset and get calibration config
        asset = self._extract_asset_from_market_id(snapshot.market_id)
        from merid.sentiment.crypto_registry import get_calibration_config
        calib = get_calibration_config(asset)
        
        # Determine timeframe type from the already-resolved timeframe on the
        # snapshot (set by trading_agent._build_snapshot via ticker inference).
        # Avoid substring matches on market_id: "D" would match KXDOGE, "M"
        # would match KXBTC15M, etc., causing all DOGE/15m markets to be
        # incorrectly classified as high-timeframe.
        _resolved_tf = getattr(snapshot, "resolved_timeframe", None)
        is_high_tf = _resolved_tf in ("daily", "weekly", "monthly", "annual")
        # Guard: calib can be None for assets not in the crypto registry (e.g. macro/politics tickers).
        # The previous one-liner ternary accessed calib attributes before the None-check when
        # is_high_tf=True, causing AttributeError on unknown assets.
        if calib:
            min_prob_edge = calib.min_prob_edge_high_tf if is_high_tf else calib.min_prob_edge_low_tf
        else:
            min_prob_edge = 0.15
        
        # Structural conviction computation (needed for both gate and sizing)
        structural_factor = 1.0
        conviction_details = {}
        conviction = 0.5  # default
        
        if hasattr(snapshot, 'fvg_context') and snapshot.fvg_context:
            from merid.sentiment.crypto_registry import get_crypto_registry
            
            conviction_result = get_crypto_registry().compute_structural_conviction(
                symbol=asset,
                fvg_pressure=snapshot.fvg_pressure,
                fvg_confluence=snapshot.has_local_fvg_confluence if hasattr(snapshot, 'has_local_fvg_confluence') else False,
                trend_aligned=snapshot.trend_aligned if hasattr(snapshot, 'trend_aligned') else False,
                sentiment_regime=snapshot.sentiment_regime or "neutral",
                nearest_fvg_distance_atr=snapshot.nearest_fvg_distance_atr,
            )
            conviction = conviction_result["conviction"]
            conviction_details = conviction_result
            
            # Map conviction (0.2-1.0) to size factor (0.4-1.2)
            structural_factor = 0.4 + (conviction * 0.8)
        
        # CONVICTION FLOOR VETO
        # If conviction < veto threshold, absolute NO_ACTION
        veto_threshold = calib.conviction_veto_threshold if calib else 0.4
        if conviction < veto_threshold:
            return StrategySignal(
                market_id=snapshot.market_id,
                action=SignalAction.NO_ACTION,
                side=best.side,
                contracts=0,
                edge=best,
                phase=phase,
                reason=f"blocked: low_structural_conviction={conviction:.2f} < veto_threshold={veto_threshold}",
                correlation_id=correlation_id,
            )
        
        # CONVICTION-MODULATED PROBABILITY EDGE
        # If conviction is borderline, require higher prob edge
        strict_threshold = calib.conviction_strict_threshold if calib else 0.6
        prob_edge_boost = calib.prob_edge_boost_for_low_conviction if calib else 0.10
        
        effective_min_prob_edge = min_prob_edge
        if conviction < strict_threshold:
            # Borderline conviction: require higher probability edge
            effective_min_prob_edge += prob_edge_boost
        
        # HARD PROBABILITY GATE CHECK
        if prob_edge < effective_min_prob_edge:
            return StrategySignal(
                market_id=snapshot.market_id,
                action=SignalAction.NO_ACTION,
                side=best.side,
                contracts=0,
                edge=best,
                phase=phase,
                reason=f"blocked: prob_edge={prob_edge:.3f} < required={effective_min_prob_edge:.3f} (conviction={conviction:.2f})",
                correlation_id=correlation_id,
            )
        
        # PASSED ALL GATES - log clear reason for allowed trade
        logger.info(
            "[PROB-GATE] allowed: %s | prob_edge=%.3f (min=%.3f) | conviction=%.2f | asset=%s",
            snapshot.market_id,
            prob_edge,
            effective_min_prob_edge,
            conviction,
            asset
        )

        # 7. Size calculation with structural conviction and behavioral exploitation
        # Layer 2: Base size from Kelly + sentiment regime
        base_size = self._kelly_size_with_sentiment(best, phase, snapshot, correlation_id=correlation_id)
        
        # Apply structural factor to base size
        size = int(base_size * structural_factor)
        
        # Layer 3: Behavioral exploitation adjustments
        # Detect and exploit behavioral biases (longshot, panic, FOMO, recency, etc.)
        model_prob = float(best.model_prob) if best.model_prob else None
        behavioral_adj = self._behavioral_exploitation_adjustments(snapshot, model_prob)
        
        # Apply behavioral size multiplier (reduces size for risky behavioral patterns)
        behavioral_size_mult = behavioral_adj.get("size_multiplier", 1.0)
        if behavioral_size_mult != 1.0 and behavioral_size_mult > 0:
            size = int(size * behavioral_size_mult)
            logger.debug(
                "[BEHAVIORAL] %s | size adjusted: %d -> %d (mult=%.2f, patterns=%s)",
                snapshot.market_id,
                int(size / behavioral_size_mult),
                size,
                behavioral_size_mult,
                behavioral_adj.get("patterns_detected", [])
            )
        
        # Apply LIVE mode size cap from guardian (fail-closed: 0.0 if unavailable)
        size_cap = self._get_size_cap_for_asset(asset)
        if size_cap < 1.0:
            # Cap is a fraction (e.g., 0.0 = blocked, 0.25 = 25% of Kelly)
            max_contracts = int(self.config.max_contracts_per_order * size_cap)
            if size > max_contracts:
                logger.info(
                    "[SIZE-CAP] %s | size reduced: %d -> %d (cap=%.0f%%)",
                    snapshot.market_id, size, max_contracts, size_cap * 100
                )
                size = max_contracts
        
        if size <= 0:
            return StrategySignal(
                market_id=snapshot.market_id,
                action=SignalAction.NO_ACTION,
                side=best.side,
                contracts=0,
                edge=best,
                phase=phase,
                reason="Kelly sizing returned 0 contracts.",
                correlation_id=correlation_id,
            )

        # Determine action
        if best.action == "buy":
            action = SignalAction.BUY_YES if best.side == "yes" else SignalAction.BUY_NO
        else:
            action = SignalAction.SELL_YES if best.side == "yes" else SignalAction.SELL_NO

        # Limit price: use the ask for buys, bid for sells
        limit_cents = None
        if best.side == "yes":
            if best.action == "buy" and snapshot.implied.yes_ask is not None:
                limit_cents = int(snapshot.implied.yes_ask)
            elif best.action == "sell" and snapshot.implied.yes_bid is not None:
                limit_cents = int(snapshot.implied.yes_bid)
        else:
            if best.action == "buy" and snapshot.implied.no_ask is not None:
                limit_cents = int(snapshot.implied.no_ask)
            elif best.action == "sell" and snapshot.implied.no_bid is not None:
                limit_cents = int(snapshot.implied.no_bid)

        # Build detailed reason with conviction components
        reason_parts = [
            f"{phase.value} phase",
            f"{best.edge_type} edge {best.net_edge:.4f}",
            f"base_size={base_size}",
            f"structural_factor={structural_factor:.2f}",
            f"final_size={size}",
        ]
        
        if conviction_details:
            reason_parts.append(
                f"conviction={conviction_details['conviction']:.2f} "
                f"(FVG:{conviction_details['fvg_component']:.2f} "
                f"trend:{conviction_details['trend_component']:.2f} "
                f"sent:{conviction_details['sentiment_component']:.2f})"
            )
        
        # Build final signal with behavioral adjustments for logging
        signal = StrategySignal(
            market_id=snapshot.market_id,
            action=action,
            side=best.side,
            contracts=size,
            limit_price_cents=limit_cents,
            edge=best,
            phase=phase,
            reason="; ".join(reason_parts),
            correlation_id=correlation_id,
            behavioral_adjustments=behavioral_adj,
        )
        
        return signal

    def _extract_asset_from_market_id(self, market_id: str) -> str:
        """Extract asset symbol from Kalshi market ID.
        
        Examples:
        - KXBTC15M-XXX -> BTC
        - KXETH-XXX -> ETH  
        - KXSOL1H-XXX -> SOL
        """
        # Remove KX prefix and extract next 2-4 chars (asset code)
        cleaned = market_id.upper().replace("KX", "")
        
        # Known asset codes in order of specificity (longer first)
        assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        for asset in assets:
            if asset in cleaned:
                return asset
        
        # Fallback: try common patterns
        if cleaned.startswith("BT"):
            return "BTC"
        if cleaned.startswith("ET"):
            return "ETH"
        if cleaned.startswith("SO"):
            return "SOL"
        if cleaned.startswith("XR"):
            return "XRP"
        if cleaned.startswith("DO"):
            return "DOGE"
        
        return "UNK"

    def _get_size_cap_for_asset(self, asset: str) -> float:
        """Get size cap for asset from TradingGuardian (legacy CT) when its loop runs.

        AgentGrid PM uses ExecutionGate + portfolio risk, not CT's guardian fractions.
        When CT is not running, missing guardian must **not** zero out Kelly size (that
        produced all-``NO_ACTION`` signals with ``Kelly sizing returned 0 contracts``).

        Returns:
            Size cap as fraction (0.0-1.0). ``1.0`` = full strategy sizing subject to
            ``StrategyConfig`` / risk agent limits.
        """
        try:
            from merid.trading.kalshi_continuous_trader import get_continuous_trader

            trader = get_continuous_trader()
            if trader and trader.is_running() and trader._guardian:
                # .get defaults to 0.0 → fail-closed for unknown assets on the CT path
                return trader._guardian.checklist.live_size_caps.get(asset, 0.0)
        except Exception:
            pass
        return 1.0

    def _sentiment_size_multiplier(self, snapshot: MarketSnapshot, action: SignalAction) -> Decimal:
        """Return a 0.5–1.5 multiplier applied to Kelly size based on regime.

        Logic:
          extreme_fear  + buying YES (contrarian long) → 1.3× (fear = discount)
          extreme_greed + buying YES (momentum chase)  → 0.6× (crowded, reduce)
          extreme_greed + buying NO  (fade greed)      → 1.2× (contrarian short)
          fear / greed  (moderate)                     → 1.0× (baseline)
          No sentiment data                            → 1.0×
        """
        regime = snapshot.sentiment_regime
        if not regime:
            return Decimal("1.0")
        buying_yes = action in (SignalAction.BUY_YES,)
        buying_no  = action in (SignalAction.BUY_NO,)
        if regime == "extreme_fear":
            return Decimal("1.3") if buying_yes else Decimal("0.8")
        if regime == "extreme_greed":
            if buying_yes:
                return Decimal("0.6")   # reduce momentum chase
            if buying_no:
                return Decimal("1.2")   # reward contrarian fade
        return Decimal("1.0")

    def _sentiment_edge_floor(self, snapshot: MarketSnapshot, phase: ExpiryPhase) -> Decimal:
        """Raise the minimum edge threshold in extreme regimes (more selective)."""
        base = self._min_edge_for_phase(phase)
        regime = snapshot.sentiment_regime
        if regime in ("extreme_fear", "extreme_greed"):
            return base * Decimal("1.25")   # +25% edge required in extreme regimes
        return base

    def _behavioral_exploitation_adjustments(
        self,
        snapshot: MarketSnapshot,
        model_prob: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Compute behavioral bias adjustments for edge and position sizing.
        
        Returns dict with:
        - edge_boost_bps: Additional edge requirement from behavioral patterns
        - size_multiplier: Position size adjustment (0.5-1.5x typical)
        - patterns_detected: List of detected behavioral patterns
        - recommended_side: Optional contrarian side recommendation
        - urgency: immediate, normal, delayed, avoid
        """
        try:
            from merid.sentiment.behavioral_exploitation import (
                get_behavioral_engine,
                MarketMicrostructure,
                SentimentContext,
            )
            
            engine = get_behavioral_engine()
            
            # Build market microstructure from snapshot
            micro = MarketMicrostructure(
                ticker=snapshot.market_id,
                asset=snapshot.resolved_asset or "UNKNOWN",
                timeframe=snapshot.resolved_timeframe or "15m",
                yes_price_cents=int(snapshot.yes_price * 100) if snapshot.yes_price else 50,
                no_price_cents=int(snapshot.no_price * 100) if snapshot.no_price else 50,
                mid_cents=float(snapshot.mid_price * 100) if snapshot.mid_price else 50.0,
                spread_cents=float(snapshot.spread * 100) if snapshot.spread else 2.0,
                volume_24h=int(snapshot.volume_24h) if snapshot.volume_24h else 0,
                open_interest=int(snapshot.open_interest) if snapshot.open_interest else 0,
                seconds_to_expiry=int(snapshot.time_to_expiry_hours * 3600) if snapshot.time_to_expiry_hours else 3600,
            )
            
            # Build sentiment context from snapshot
            sentiment = SentimentContext(
                fg_index=int(snapshot.sentiment_global) if snapshot.sentiment_global else 50,
                social_sentiment=0.0,  # Could be enriched from sentiment bus
                twitter_mention_velocity=0.0,
            )
            
            # Run behavioral analysis
            signals = engine.analyze(micro, sentiment, model_prob)
            composite = engine.get_composite_signal(signals)
            
            return {
                "edge_boost_bps": composite.get("behavioral_edge_boost_bps", 0),
                "size_multiplier": composite.get("position_size_mult", 1.0),
                "patterns_detected": composite.get("patterns", []),
                "recommended_side": composite.get("primary_recommendation"),
                "urgency": composite.get("urgency", "normal"),
                "raw_signals": signals,
            }
        except Exception as e:
            logger.debug("Behavioral exploitation analysis skipped: %s", e)
            return {
                "edge_boost_bps": 0,
                "size_multiplier": 1.0,
                "patterns_detected": [],
                "recommended_side": None,
                "urgency": "normal",
                "raw_signals": [],
            }

    # ------------------------------------------------------------------
    # Contrarian archetype
    # ------------------------------------------------------------------

    def _evaluate_contrarian(
        self,
        snapshot: MarketSnapshot,
        phase: ExpiryPhase,
        correlation_id: Optional[str] = None,
    ) -> StrategySignal:
        """Contrarian: only trades when local fear/greed >= 75 AND model disagrees by ≥10pp."""
        _cmin = float(self.config.contrarian_sentiment_min)
        local = snapshot.sentiment_local
        if local is None or local < _cmin:
            return StrategySignal(
                market_id=snapshot.market_id,
                action=SignalAction.NO_ACTION,
                side="none", contracts=0, phase=phase,
                reason=f"Contrarian requires local sentiment ≥{_cmin:.0f}; got {local}.",
                correlation_id=correlation_id,
                eval_context={
                    "contrarian_sentiment_min": _cmin,
                    "block": "sentiment_below_contrarian_floor",
                },
            )

        spec_edges = [e for e in snapshot.edges if e.edge_type == "speculative"]
        if not spec_edges:
            return StrategySignal(
                market_id=snapshot.market_id,
                action=SignalAction.NO_ACTION,
                side="none", contracts=0, phase=phase,
                reason="No speculative edge for contrarian.",
                correlation_id=correlation_id,
            )

        best = max(spec_edges, key=lambda e: e.net_edge)
        model_gap = abs(float(best.model_prob) - float(best.market_prob))
        _gmin = float(self.config.contrarian_model_gap_min)
        if model_gap < _gmin:
            return StrategySignal(
                market_id=snapshot.market_id,
                action=SignalAction.NO_ACTION,
                side=best.side, contracts=0, edge=best, phase=phase,
                reason=f"Contrarian model gap {model_gap:.2%} < {_gmin:.0%} required.",
                correlation_id=correlation_id,
                eval_context={
                    "contrarian_model_gap_min": _gmin,
                    "block": "model_gap_too_small",
                },
            )

        min_edge = self._sentiment_edge_floor(snapshot, phase)
        if best.net_edge < min_edge:
            return StrategySignal(
                market_id=snapshot.market_id,
                action=SignalAction.NO_ACTION,
                side=best.side, contracts=0, edge=best, phase=phase,
                reason=f"Contrarian edge {best.net_edge:.4f} below floor {min_edge}.",
                correlation_id=correlation_id,
                eval_context={
                    "min_edge_floor": str(min_edge),
                    "archetype": "contrarian",
                    "block": "edge_below_threshold",
                },
            )

        action = SignalAction.BUY_YES if best.side == "yes" else SignalAction.BUY_NO
        mult = self._sentiment_size_multiplier(snapshot, action)
        size_factor = max(0.35, min(1.5, float(mult))) * self._pm_vol_band_size_factor(snapshot)
        size = self._kelly_size(best, phase, size_factor=size_factor, correlation_id=correlation_id)
        size = max(1, min(size, self.config.max_contracts_per_order))

        limit_cents = int(snapshot.implied.yes_ask or 50) if best.side == "yes" else int(snapshot.implied.no_ask or 50)

        return StrategySignal(
            market_id=snapshot.market_id,
            action=action, side=best.side, contracts=size,
            limit_price_cents=limit_cents, edge=best, phase=phase,
            reason=f"Contrarian fade: sentiment={local:.0f}/100 gap={model_gap:.2%} size={size} factor={size_factor:.2f}.",
            correlation_id=correlation_id,
        )

    # ------------------------------------------------------------------
    # Regime-switch archetype
    # ------------------------------------------------------------------

    def _evaluate_regime_switch(
        self,
        snapshot: MarketSnapshot,
        phase: ExpiryPhase,
        correlation_id: Optional[str] = None,
    ) -> StrategySignal:
        """Regime-switch: rides momentum when category sentiment shifts fast (Δ > 20 in session).

        Uses category score as the regime signal; falls back to directional if no shift.
        """
        cat_score = snapshot.sentiment_category
        glob_score = snapshot.sentiment_global
        if cat_score is None:
            return self._evaluate_directional(snapshot, phase, correlation_id)

        # Momentum regime: category is greed/extreme_greed → ride YES momentum
        # Fear regime: category is fear/extreme_fear → ride NO momentum (things going lower)
        regime = snapshot.sentiment_regime or "greed"
        spec_edges = [e for e in snapshot.edges if e.edge_type == "speculative"]
        if not spec_edges:
            return StrategySignal(
                market_id=snapshot.market_id,
                action=SignalAction.NO_ACTION,
                side="none", contracts=0, phase=phase,
                reason="No speculative edge for regime-switch.",
                correlation_id=correlation_id,
            )

        best = max(spec_edges, key=lambda e: e.net_edge)
        min_edge = self._min_edge_for_phase(phase)
        if best.net_edge < min_edge:
            return StrategySignal(
                market_id=snapshot.market_id,
                action=SignalAction.NO_ACTION,
                side=best.side, contracts=0, edge=best, phase=phase,
                reason=f"Regime-switch edge {best.net_edge:.4f} below threshold {min_edge}.",
                correlation_id=correlation_id,
                eval_context={
                    "min_edge_threshold": str(min_edge),
                    "archetype": "regime_switch",
                    "block": "edge_below_threshold",
                },
            )

        # In greed regime, prefer YES; in fear regime, prefer NO
        if regime in ("greed", "extreme_greed") and best.side != "yes":
            return StrategySignal(
                market_id=snapshot.market_id,
                action=SignalAction.NO_ACTION,
                side=best.side, contracts=0, edge=best, phase=phase,
                reason=f"Regime-switch: greed regime, skipping NO-side trade.",
                correlation_id=correlation_id,
            )
        if regime in ("fear", "extreme_fear") and best.side != "no":
            return StrategySignal(
                market_id=snapshot.market_id,
                action=SignalAction.NO_ACTION,
                side=best.side, contracts=0, edge=best, phase=phase,
                reason=f"Regime-switch: fear regime, skipping YES-side trade.",
                correlation_id=correlation_id,
            )

        action = SignalAction.BUY_YES if best.side == "yes" else SignalAction.BUY_NO
        mult = self._sentiment_size_multiplier(snapshot, action)
        size_factor = max(0.35, min(1.5, float(mult))) * self._pm_vol_band_size_factor(snapshot)
        size = self._kelly_size(best, phase, size_factor=size_factor, correlation_id=correlation_id)
        size = max(1, min(size, self.config.max_contracts_per_order))
        limit_cents = int(snapshot.implied.yes_ask or 50) if best.side == "yes" else int(snapshot.implied.no_ask or 50)

        return StrategySignal(
            market_id=snapshot.market_id,
            action=action, side=best.side, contracts=size,
            limit_price_cents=limit_cents, edge=best, phase=phase,
            reason=f"Regime-switch: {regime} cat={cat_score:.0f} glob={glob_score:.0f} size={size} factor={size_factor:.2f}.",
            correlation_id=correlation_id,
        )

    # ------------------------------------------------------------------
    # Vol-breakout archetype
    # ------------------------------------------------------------------

    def _evaluate_vol_breakout(
        self,
        snapshot: MarketSnapshot,
        phase: ExpiryPhase,
        correlation_id: Optional[str] = None,
    ) -> StrategySignal:
        """Vol-breakout: trades when volatility component is high AND book is imbalanced.

        Scales risk with sentiment intensity — higher score = larger size up to cap.
        """
        local = snapshot.sentiment_local
        if local is None:
            return self._evaluate_directional(snapshot, phase, correlation_id)

        # Require elevated sentiment (either direction) to signal vol breakout
        lo, hi = float(self.config.vol_breakout_neutral_low), float(self.config.vol_breakout_neutral_high)
        if lo <= local <= hi:
            return StrategySignal(
                market_id=snapshot.market_id,
                action=SignalAction.NO_ACTION,
                side="none", contracts=0, phase=phase,
                reason=f"Vol-breakout requires sentiment outside {lo:.0f}–{hi:.0f}; got {local:.0f}.",
                correlation_id=correlation_id,
                eval_context={
                    "vol_breakout_neutral_low": lo,
                    "vol_breakout_neutral_high": hi,
                    "block": "sentiment_in_neutral_band",
                },
            )

        spec_edges = [e for e in snapshot.edges if e.edge_type == "speculative"]
        if not spec_edges:
            return StrategySignal(
                market_id=snapshot.market_id,
                action=SignalAction.NO_ACTION,
                side="none", contracts=0, phase=phase,
                reason="No speculative edge for vol-breakout.",
                correlation_id=correlation_id,
            )

        best = max(spec_edges, key=lambda e: e.net_edge)
        min_edge = self._min_edge_for_phase(phase)
        if best.net_edge < min_edge:
            return StrategySignal(
                market_id=snapshot.market_id,
                action=SignalAction.NO_ACTION,
                side=best.side, contracts=0, edge=best, phase=phase,
                reason=f"Vol-breakout edge {best.net_edge:.4f} below threshold {min_edge}.",
                correlation_id=correlation_id,
                eval_context={
                    "min_edge_threshold": str(min_edge),
                    "archetype": "vol_breakout",
                    "block": "edge_below_threshold",
                },
            )

        # Scale size by sentiment intensity (distance from 50).
        # Intensity only shrinks — capped at 1.0 so hourly exposure cap is
        # never bypassed by a 1.5× boost.  Minimum factor 0.35.
        intensity = abs(local - 50) / 50.0   # 0–1
        size_factor = (
            max(0.35, min(1.0, 1.0 - intensity * 0.3)) * self._pm_vol_band_size_factor(snapshot)
        )
        scaled = self._kelly_size(best, phase, size_factor=size_factor, correlation_id=correlation_id)
        scaled = max(1, min(scaled, self.config.max_contracts_per_order))

        action = SignalAction.BUY_YES if best.side == "yes" else SignalAction.BUY_NO
        limit_cents = int(snapshot.implied.yes_ask or 50) if best.side == "yes" else int(snapshot.implied.no_ask or 50)

        return StrategySignal(
            market_id=snapshot.market_id,
            action=action, side=best.side, contracts=scaled,
            limit_price_cents=limit_cents, edge=best, phase=phase,
            reason=f"Vol-breakout: sentiment={local:.0f} intensity={intensity:.2f} size={scaled}.",
            correlation_id=correlation_id,
        )

    def _evaluate_mm(
        self,
        snapshot: MarketSnapshot,
        phase: ExpiryPhase,
        correlation_id: Optional[str] = None,
    ) -> StrategySignal:
        """Market Maker strategy: quote bid and ask."""
        # Check spread
        if snapshot.implied.spread_cents is None or snapshot.implied.spread_cents > self.config.mm_max_spread_cents:
            return StrategySignal(
                market_id=snapshot.market_id,
                action=SignalAction.NO_ACTION,
                side="none",
                contracts=0,
                phase=phase,
                reason=f"Spread {snapshot.implied.spread_cents} exceeds MM limit.",
                correlation_id=correlation_id,
            )

        # Simple mid-price based quoting
        yes_mid = (snapshot.implied.yes_bid + snapshot.implied.yes_ask) / 2 if snapshot.implied.yes_bid and snapshot.implied.yes_ask else Decimal("50")
        
        # Apply target spread
        half_spread = self.config.mm_target_spread_cents / 2
        bid = int((yes_mid - half_spread).quantize(Decimal("1"), ROUND_HALF_UP))
        ask = int((yes_mid + half_spread).quantize(Decimal("1"), ROUND_HALF_UP))

        # Clamp to 1-99
        bid = max(1, min(98, bid))
        ask = max(bid + 1, min(99, ask))

        # Mid price (integer cents) for risk sizing, PM logs, and TradeProposal.intent_risk —
        # QUOTE previously omitted limit_price_cents, which made intent_risk=0 downstream.
        mid_cents = max(1, min(99, int((bid + ask) // 2)))

        _depth = int(self.config.min_depth_contracts)
        _vm = self._pm_vol_band_size_factor(snapshot)
        if _vm != 1.0:
            _depth = max(1, int(round(_depth * _vm)))

        # Cap by strategy limits (respects Top-N allocator downstream)
        _depth = min(_depth, self.config.max_contracts_per_order)
        _depth = min(_depth, self.config.mm_inventory_limit)

        return StrategySignal(
            market_id=snapshot.market_id,
            action=SignalAction.QUOTE,
            side="yes",
            contracts=_depth,
            limit_price_cents=mid_cents,
            bid_price_cents=bid,
            ask_price_cents=ask,
            phase=phase,
            reason=(
                f"MM quoting {bid}c/{ask}c (mid={mid_cents}c for risk) around mid {yes_mid:.1f}c."
            ),
            correlation_id=correlation_id,
        )

    def _evaluate_arb(
        self,
        snapshot: MarketSnapshot,
        phase: ExpiryPhase,
        correlation_id: Optional[str] = None,
    ) -> StrategySignal:
        """Arbitrage strategy: specifically focused on mispricings."""
        arb_edges = [e for e in snapshot.edges if e.edge_type == "arb"]
        if not arb_edges:
            return StrategySignal(
                market_id=snapshot.market_id,
                action=SignalAction.NO_ACTION,
                side="none",
                contracts=0,
                phase=phase,
                reason="No arb edge detected.",
                correlation_id=correlation_id,
            )

        best_arb = max(arb_edges, key=lambda e: e.net_edge)
        if best_arb.net_edge < self.config.min_arb_edge:
            return StrategySignal(
                market_id=snapshot.market_id,
                action=SignalAction.NO_ACTION,
                side="none",
                contracts=0,
                phase=phase,
                reason=f"Arb edge {best_arb.net_edge:.4f} below threshold.",
                correlation_id=correlation_id,
            )

        return StrategySignal(
            market_id=snapshot.market_id,
            action=SignalAction.BUY_YES, # Arb usually involves both, buy_yes side used as trigger
            side="both",
            contracts=self.config.max_contracts_per_order,
            edge=best_arb,
            phase=phase,
            reason=f"Arb opportunity: {best_arb.net_edge:.4f} edge.",
            correlation_id=correlation_id,
        )

    # ------------------------------------------------------------------
    # Exit evaluation
    # ------------------------------------------------------------------

    def register_position(self, pos: PositionState) -> None:
        """Register an open position for exit monitoring."""
        self._positions[pos.market_id] = pos

    def remove_position(self, market_id: str) -> None:
        """Remove a closed position."""
        self._positions.pop(market_id, None)

    def evaluate_exits(self, snapshots: Dict[str, MarketSnapshot]) -> List[StrategySignal]:
        """Check all open positions for exit conditions.

        Exit rules:
        - Profit target: unrealized PnL >= profit_target_pct of entry cost.
        - Stop loss: unrealized PnL <= -stop_loss_pct of entry cost.
        - Max hold: position held longer than max_hold_hours.
        - Market closing: force close if state is CLOSING or CLOSED.
        """
        signals: List[StrategySignal] = []

        for mid, pos in list(self._positions.items()):
            snap = snapshots.get(mid)
            if snap is None:
                continue

            phase = self._expiry_phase(snap.time_to_expiry_hours)

            # Update current price
            if pos.side == "yes" and snap.implied.yes_bid is not None:
                pos.current_price_cents = snap.implied.yes_bid
            elif pos.side == "no" and snap.implied.no_bid is not None:
                pos.current_price_cents = snap.implied.no_bid

            if pos.current_price_cents is not None:
                pnl_per_contract = pos.current_price_cents - pos.avg_entry_cents
                pos.unrealized_pnl_cents = pnl_per_contract * pos.contracts

            reason = None

            # Profit target
            if pos.unrealized_pnl_cents is not None:
                entry_cost = pos.avg_entry_cents * pos.contracts
                if entry_cost > 0:
                    pnl_pct = pos.unrealized_pnl_cents / entry_cost
                    if pnl_pct >= self.config.profit_target_pct:
                        reason = f"Profit target hit: {pnl_pct:.2%} >= {self.config.profit_target_pct:.2%}."
                    elif pnl_pct <= -self.config.stop_loss_pct:
                        reason = f"Stop loss hit: {pnl_pct:.2%} <= -{self.config.stop_loss_pct:.2%}."

            # Max hold
            if reason is None:
                hours_held = Decimal(str(
                    (datetime.now(timezone.utc) - pos.opened_at).total_seconds() / 3600
                ))
                if hours_held >= self.config.max_hold_hours:
                    reason = f"Max hold exceeded: {hours_held:.1f}h >= {self.config.max_hold_hours}h."

            # Market closing
            if reason is None and snap.state in (ContractState.CLOSING, ContractState.CLOSED):
                reason = f"Market state is {snap.state.value}, closing position."

            if reason:
                action = SignalAction.SELL_YES if pos.side == "yes" else SignalAction.SELL_NO
                
                # [TRACE] MONITOR_START — position exit signal detected
                if pos.correlation_id:
                    logger.info(
                        "[TRACE] MONITOR_EXIT | corr_id=%s | market=%s | side=%s | contracts=%s | pnl_cents=%s | reason=%s | formulas=%s | audit_spec=%s",
                        pos.correlation_id,
                        mid,
                        pos.side,
                        pos.contracts,
                        pos.unrealized_pnl_cents,
                        reason,
                        FORMULAS_VERSION,
                        AUDIT_SPEC_VERSION,
                    )
                
                signals.append(StrategySignal(
                    market_id=mid,
                    action=action,
                    side=pos.side,
                    contracts=pos.contracts,
                    phase=phase,
                    reason=reason,
                    correlation_id=pos.correlation_id,
                ))

        return signals

    # ------------------------------------------------------------------
    # Batch evaluation
    # ------------------------------------------------------------------

    def scan_markets(self, snapshots: List[MarketSnapshot]) -> List[StrategySignal]:
        """Evaluate multiple markets and return actionable signals only."""
        signals = []
        for snap in snapshots:
            sig = self.evaluate(snap)
            if sig.action != SignalAction.NO_ACTION:
                signals.append(sig)
        return signals
