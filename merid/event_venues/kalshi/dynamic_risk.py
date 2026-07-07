"""Dynamic Risk Management for Kalshi 15m Crypto Trading.

This module replaces constant-based risk parameters with dynamic functions
that compute TP/SL, position sizing, and market bands based on live state:
- Bankroll and risk budget
- Edge (probability vs implied)
- Volatility and time to expiry
- Recent execution quality (slippage, fill rates)
- Real PnL and drawdown tracking
- Invariant-triggered cooldowns

Core Principles:
1. Risk per trade = function of bankroll and drawdown state
2. TP/SL = function of edge, volatility, time to expiry
3. Position size = function of risk per trade and risk per contract
4. Market bands = function of volatility, edge, depth
5. All decisions logged with inputs/outputs for traceability
6. Trading halted on cooldown or critical drawdown
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from typing import Dict, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.dynamic_risk")


class VolatilityRegime(Enum):
    """Volatility regimes for dynamic risk adjustment."""
    LOW = "low"           # Tight bands, standard risk
    NORMAL = "normal"     # Standard parameters
    HIGH = "high"         # Wider bands, reduced risk
    EXTREME = "extreme"   # Conservative mode, may skip trades


class DrawdownState(Enum):
    """Drawdown state for risk scaling."""
    FLAT = "flat"           # No drawdown, full risk
    MINOR = "minor"         # < 2% drawdown, 90% risk
    MODERATE = "moderate"   # 2-5% drawdown, 70% risk
    SEVERE = "severe"       # 5-10% drawdown, 50% risk
    CRITICAL = "critical"   # > 10% drawdown, halt trading


class InvariantSeverity(Enum):
    """Severity levels for invariant violations."""
    MINOR = "minor"         # Warning, 5 min cooldown
    MAJOR = "major"         # Significant, 15 min cooldown
    CRITICAL = "critical"   # Severe, 30 min cooldown + risk reduction


@dataclass
class VolatilityMetrics:
    """Volatility metrics for a market/asset."""
    regime: VolatilityRegime
    realized_vol_15m: float  # Realized vol over last 15m bars
    avg_range_cents: float   # Average price range in cents
    spread_cents: int        # Current spread in cents
    depth_at_top: int        # Volume at best bid/ask
    time_to_expiry_min: int  # Minutes to settlement
    
    def to_dict(self) -> Dict:
        return {
            "regime": self.regime.value,
            "realized_vol_15m": self.realized_vol_15m,
            "avg_range_cents": self.avg_range_cents,
            "spread_cents": self.spread_cents,
            "depth_at_top": self.depth_at_top,
            "time_to_expiry_min": self.time_to_expiry_min,
        }


@dataclass
class TP_SLResult:
    """Result of dynamic TP/SL computation."""
    tp_price_cents: int
    sl_price_cents: int
    risk_cents_per_contract: int  # |entry - sl| in cents
    tp_r_multiple: float
    sl_r_multiple: float
    confidence_used: float
    volatility_regime: VolatilityRegime
    computation_time_ms: float
    rationale: str
    
    def to_dict(self) -> Dict:
        return {
            "tp_price_cents": self.tp_price_cents,
            "sl_price_cents": self.sl_price_cents,
            "risk_cents_per_contract": self.risk_cents_per_contract,
            "tp_r_multiple": self.tp_r_multiple,
            "sl_r_multiple": self.sl_r_multiple,
            "confidence_used": self.confidence_used,
            "volatility_regime": self.volatility_regime.value,
            "computation_time_ms": self.computation_time_ms,
            "rationale": self.rationale,
        }


@dataclass
class PositionSizeResult:
    """Result of dynamic position sizing."""
    contracts: int
    risk_dollars: float
    risk_pct_of_bankroll: float
    bankroll_used: float
    per_market_cap: int
    per_asset_cap: int
    global_cap: int
    limiting_factor: str  # Which cap was binding
    computation_time_ms: float
    rationale: str
    
    def to_dict(self) -> Dict:
        return {
            "contracts": self.contracts,
            "risk_dollars": self.risk_dollars,
            "risk_pct_of_bankroll": self.risk_pct_of_bankroll,
            "bankroll_used": self.bankroll_used,
            "per_market_cap": self.per_market_cap,
            "per_asset_cap": self.per_asset_cap,
            "global_cap": self.global_cap,
            "limiting_factor": self.limiting_factor,
            "computation_time_ms": self.computation_time_ms,
            "rationale": self.rationale,
        }


@dataclass
class MarketBandResult:
    """Result of dynamic market band computation."""
    limit_price_cents: int
    aggressiveness_factor: float  # 0-1, higher = more aggressive
    ticks_from_mid: int
    should_skip: bool
    skip_reason: Optional[str]
    computation_time_ms: float
    rationale: str
    
    def to_dict(self) -> Dict:
        return {
            "limit_price_cents": self.limit_price_cents,
            "aggressiveness_factor": self.aggressiveness_factor,
            "ticks_from_mid": self.ticks_from_mid,
            "should_skip": self.should_skip,
            "skip_reason": self.skip_reason,
            "computation_time_ms": self.computation_time_ms,
            "rationale": self.rationale,
        }


@dataclass
class RiskBudget:
    """Dynamic risk budget based on bankroll and drawdown state."""
    risk_per_trade_pct: float  # e.g., 0.01 = 1% of bankroll
    max_daily_loss_pct: float
    max_rolling_loss_pct: float
    drawdown_state: DrawdownState
    bankroll_usd: float
    recent_trades_count: int
    recent_win_rate: float
    
    def to_dict(self) -> Dict:
        return {
            "risk_per_trade_pct": self.risk_per_trade_pct,
            "max_daily_loss_pct": self.max_daily_loss_pct,
            "max_rolling_loss_pct": self.max_rolling_loss_pct,
            "drawdown_state": self.drawdown_state.value,
            "bankroll_usd": self.bankroll_usd,
            "recent_trades_count": self.recent_trades_count,
            "recent_win_rate": self.recent_win_rate,
        }


class DynamicRiskEngine:
    """Dynamic risk management engine for Kalshi 15m crypto trading.
    
    Replaces constant-based risk parameters with functions of:
    - Bankroll and drawdown state
    - Edge (probability vs implied)
    - Volatility and time to expiry
    - Execution quality feedback
    - Real PnL and exposure tracking
    - Invariant-triggered cooldowns
    """
    
    # Base risk parameters (configurable via env or profile)
    BASE_RISK_PER_TRADE_PCT = 0.015  # 1.5% of bankroll per trade
    MAX_DAILY_LOSS_PCT = 0.02  # 2% daily loss limit
    MAX_ROLLING_LOSS_PCT = 0.05  # 5% rolling loss limit (over 100 trades)
    
    # Volatility thresholds for regime classification
    VOL_LOW_THRESHOLD = 0.02  # 2% realized vol = low
    VOL_HIGH_THRESHOLD = 0.05  # 5% realized vol = high
    VOL_EXTREME_THRESHOLD = 0.10  # 10% realized vol = extreme
    
    # Spread thresholds (cents)
    SPREAD_TIGHT = 2
    SPREAD_WIDE = 5
    SPREAD_EXTREME = 100  # Increased from 8c to align with microstructure gate (100c) for 15m crypto markets
    
    # Time to expiry thresholds (minutes)
    TIME_SHORT = 2  # < 2 min = very short
    TIME_LONG = 10  # > 10 min = plenty of time
    
    # Drawdown thresholds
    DRAWDOWN_MINOR_PCT = 0.02  # 2%
    DRAWDOWN_MODERATE_PCT = 0.05  # 5%
    DRAWDOWN_SEVERE_PCT = 0.10  # 10%
    
    # Cooldown durations (seconds)
    COOLDOWN_MINOR = 300  # 5 minutes
    COOLDOWN_MAJOR = 900  # 15 minutes
    COOLDOWN_CRITICAL = 1800  # 30 minutes
    
    def __init__(self):
        self._execution_metrics: Dict[str, Dict] = {}  # asset -> {avg_slippage, fill_rate}
        self._recent_pnl_history: list = []  # Last 100 trades PnL
        self._max_history_size = 100
        
        # PnL tracking for drawdown calculation
        self._daily_pnl_usd: float = 0.0
        self._daily_start_bankroll: float = 0.0
        self._peak_bankroll: float = 0.0
        self._last_daily_reset: datetime = datetime.now(timezone.utc)
        
        # Cooldown tracking
        self._cooldown_until: Optional[datetime] = None
        self._cooldown_reason: Optional[str] = None
        self._invariant_violation_count: int = 0
    
    def compute_volatility_regime(
        self,
        realized_vol: float,
        spread_cents: int,
        time_to_expiry_min: int,
    ) -> VolatilityRegime:
        """Classify market into volatility regime.
        
        Args:
            realized_vol: Realized volatility over last 15m bars (decimal, e.g., 0.03 = 3%)
            spread_cents: Current spread in cents
            time_to_expiry_min: Minutes to settlement
            
        Returns:
            VolatilityRegime classification
        """
        # High volatility dominates
        if realized_vol >= self.VOL_EXTREME_THRESHOLD:
            return VolatilityRegime.EXTREME
        if realized_vol >= self.VOL_HIGH_THRESHOLD:
            return VolatilityRegime.HIGH
        
        # Consider spread and time to expiry
        if spread_cents >= self.SPREAD_EXTREME:
            return VolatilityRegime.HIGH
        if spread_cents >= self.SPREAD_WIDE:
            return VolatilityRegime.NORMAL
        
        # Short expiry = higher effective volatility
        if time_to_expiry_min <= self.TIME_SHORT:
            # Bump up one regime
            if realized_vol < self.VOL_LOW_THRESHOLD:
                return VolatilityRegime.NORMAL
            return VolatilityRegime.HIGH
        
        # Low vol, tight spread, plenty of time
        if realized_vol < self.VOL_LOW_THRESHOLD and spread_cents <= self.SPREAD_TIGHT:
            return VolatilityRegime.LOW
        
        return VolatilityRegime.NORMAL
    
    def compute_drawdown_state(
        self,
        bankroll_usd: float,
        recent_pnl_usd: float,
        peak_bankroll_usd: float,
    ) -> DrawdownState:
        """Classify drawdown state for risk scaling using real PnL data.
        
        Args:
            bankroll_usd: Current bankroll
            recent_pnl_usd: PnL over recent window (e.g., last 100 trades)
            peak_bankroll_usd: Peak bankroll in recent history
            
        Returns:
            DrawdownState classification
        """
        if peak_bankroll_usd <= 0:
            return DrawdownState.FLAT
        
        drawdown_pct = (peak_bankroll_usd - bankroll_usd) / peak_bankroll_usd
        
        # Update internal tracking
        self._peak_bankroll = max(self._peak_bankroll, bankroll_usd)
        self._daily_pnl_usd = recent_pnl_usd
        
        # Check daily reset
        now = datetime.now(timezone.utc)
        if now.date() != self._last_daily_reset.date():
            self._daily_start_bankroll = bankroll_usd
            self._daily_pnl_usd = 0.0
            self._last_daily_reset = now
            logger.info(
                "[DYNAMIC-RISK] Daily reset: start_bankroll=$%.2f",
                self._daily_start_bankroll
            )
        
        if drawdown_pct >= self.DRAWDOWN_SEVERE_PCT:
            return DrawdownState.CRITICAL
        if drawdown_pct >= self.DRAWDOWN_MODERATE_PCT:
            return DrawdownState.SEVERE
        if drawdown_pct >= self.DRAWDOWN_MINOR_PCT:
            return DrawdownState.MODERATE
        if drawdown_pct > 0.001:  # Non-trivial but < 2%
            return DrawdownState.MINOR
        
        return DrawdownState.FLAT
    
    def register_invariant_violation(
        self,
        severity: InvariantSeverity,
        reason: str,
    ) -> None:
        """Register an invariant violation and trigger cooldown.
        
        Args:
            severity: Severity level of the violation
            reason: Human-readable reason for the violation
        """
        self._invariant_violation_count += 1
        
        # Set cooldown duration based on severity
        if severity == InvariantSeverity.MINOR:
            cooldown_seconds = self.COOLDOWN_MINOR
        elif severity == InvariantSeverity.MAJOR:
            cooldown_seconds = self.COOLDOWN_MAJOR
        else:  # CRITICAL
            cooldown_seconds = self.COOLDOWN_CRITICAL
        
        # Set cooldown deadline
        self._cooldown_until = datetime.now(timezone.utc) + timedelta(seconds=cooldown_seconds)
        self._cooldown_reason = reason
        
        logger.warning(
            "[INVARIANT-VIOLATION] severity=%s reason=%s cooldown=%ds violations=%d",
            severity.value, reason, cooldown_seconds, self._invariant_violation_count
        )
    
    def can_trade_now(self) -> Tuple[bool, Optional[str]]:
        """Check if trading is currently allowed.
        
        Returns:
            Tuple of (can_trade: bool, reason: Optional[str])
        """
        # Check cooldown
        if self._cooldown_until is not None:
            now = datetime.now(timezone.utc)
            if now < self._cooldown_until:
                remaining_seconds = (self._cooldown_until - now).total_seconds()
                return False, f"cooldown active: {self._cooldown_reason} ({int(remaining_seconds)}s remaining)"
            else:
                # Cooldown expired
                logger.info("[DYNAMIC-RISK] Cooldown expired, trading resumed")
                self._cooldown_until = None
                self._cooldown_reason = None
        
        # Check daily loss limit
        if self._daily_start_bankroll > 0:
            daily_loss_pct = -self._daily_pnl_usd / self._daily_start_bankroll
            if daily_loss_pct > self.MAX_DAILY_LOSS_PCT:
                return False, f"daily loss limit hit: {daily_loss_pct:.2%} > {self.MAX_DAILY_LOSS_PCT:.2%}"
        
        # Check rolling loss limit
        rolling_pnl = self.get_recent_pnl_sum(100)
        if self._daily_start_bankroll > 0:
            rolling_loss_pct = -rolling_pnl / self._daily_start_bankroll
            if rolling_loss_pct > self.MAX_ROLLING_LOSS_PCT:
                return False, f"rolling loss limit hit: {rolling_loss_pct:.2%} > {self.MAX_ROLLING_LOSS_PCT:.2%}"
        
        return True, None
    
    def update_daily_pnl(self, pnl_usd: float, current_bankroll: float) -> None:
        """Update daily PnL tracking.
        
        Args:
            pnl_usd: PnL from a completed trade
            current_bankroll: Current bankroll after trade
        """
        self._daily_pnl_usd += pnl_usd
        self._peak_bankroll = max(self._peak_bankroll, current_bankroll)
        
        # Also record in history for rolling calculations
        self.record_pnl(pnl_usd)
        
        logger.debug(
            "[DYNAMIC-RISK] PnL update: pnl=$%.2f daily_total=$%.2f peak=$%.2f",
            pnl_usd, self._daily_pnl_usd, self._peak_bankroll
        )
    
    def compute_risk_budget(
        self,
        bankroll_usd: float,
        drawdown_state: DrawdownState,
        recent_win_rate: float = 0.5,
        recent_trades_count: int = 0,
    ) -> RiskBudget:
        """Compute dynamic risk budget based on state.
        
        Args:
            bankroll_usd: Current bankroll
            drawdown_state: Current drawdown state
            recent_win_rate: Win rate over recent trades (0-1)
            recent_trades_count: Number of recent trades
            
        Returns:
            RiskBudget with dynamic risk parameters
        """
        # Scale risk per trade based on drawdown
        risk_scaling = {
            DrawdownState.FLAT: 1.0,
            DrawdownState.MINOR: 0.9,
            DrawdownState.MODERATE: 0.7,
            DrawdownState.SEVERE: 0.5,
            DrawdownState.CRITICAL: 0.0,  # Halt trading
        }
        
        base_risk_pct = self.BASE_RISK_PER_TRADE_PCT
        scaled_risk_pct = base_risk_pct * risk_scaling[drawdown_state]
        
        # Additional scaling based on win rate (if we have enough data)
        if recent_trades_count >= 20:
            if recent_win_rate < 0.05:  # <5% winrate - severe de-risking for negative edge systems
                scaled_risk_pct *= 0.5  # Halve size
                logger.warning(
                    "[DYNAMIC-RISK] Low winrate guard: %.2f%% < 5%% - halving risk budget",
                    recent_win_rate * 100
                )
            elif recent_win_rate < 0.4:
                scaled_risk_pct *= 0.8  # Reduce risk if losing
            elif recent_win_rate > 0.6:
                scaled_risk_pct *= 1.1  # Slightly increase if winning
        
        risk_budget = RiskBudget(
            risk_per_trade_pct=scaled_risk_pct,
            max_daily_loss_pct=self.MAX_DAILY_LOSS_PCT,
            max_rolling_loss_pct=self.MAX_ROLLING_LOSS_PCT,
            drawdown_state=drawdown_state,
            bankroll_usd=bankroll_usd,
            recent_trades_count=recent_trades_count,
            recent_win_rate=recent_win_rate,
        )

        logger.info(
            "[RISK-BUDGET] max_cycle_risk_pct=%.4f max_total_risk_pct=%.4f drawdown_state=%s bankroll_usd=%.2f recent_win_rate=%.2f recent_trades=%d",
            scaled_risk_pct, self.MAX_DAILY_LOSS_PCT, drawdown_state.value, bankroll_usd, recent_win_rate, recent_trades_count
        )

        return risk_budget
    
    def compute_tp_sl(
        self,
        entry_price_cents: int,
        edge_pct: float,
        confidence: float,
        vol_metrics: VolatilityMetrics,
        bankroll_usd: float,
        risk_budget: RiskBudget,
    ) -> TP_SLResult:
        """Compute dynamic TP/SL based on edge, volatility, and risk budget.
        
        Args:
            entry_price_cents: Entry price in cents (1-99)
            edge_pct: Edge as percentage (e.g., 0.05 = 5%)
            confidence: Signal confidence (0-1)
            vol_metrics: Volatility metrics for the market
            bankroll_usd: Current bankroll
            risk_budget: Current risk budget
            
        Returns:
            TP_SLResult with computed TP/SL prices and metadata
        """
        t0 = time.time()
        
        # Base SL: tighter in high vol, wider in low vol
        # SL is a function of volatility regime
        # CRITICAL FIX: Load SL cents from profile config (2026-07-06)
        # Previously hardcoded - now uses upstream/midstream/downstream consistency
        try:
            from merid.risk.profiles.crypto_15m_profile import get_active_profile
            profile = get_active_profile().profile
            
            sl_cents_map = {
                VolatilityRegime.LOW: profile.dynamic_risk_sl_cents_low_vol,
                VolatilityRegime.NORMAL: profile.dynamic_risk_sl_cents_normal_vol,
                VolatilityRegime.HIGH: profile.dynamic_risk_sl_cents_high_vol,
                VolatilityRegime.EXTREME: 15,  # Very wide SL in extreme vol (fallback)
            }
            logger.debug(
                "[DYNAMIC-RISK] Loaded SL cents from profile: low=%d, normal=%d, high=%d",
                profile.dynamic_risk_sl_cents_low_vol,
                profile.dynamic_risk_sl_cents_normal_vol,
                profile.dynamic_risk_sl_cents_high_vol
            )
        except Exception as e:
            logger.warning("[DYNAMIC-RISK] Failed to load SL config from profile: %s", e)
            # Fallback to hardcoded values (temporary)
            sl_cents_map = {
                VolatilityRegime.LOW: 6,      # Tight SL in low vol
                VolatilityRegime.NORMAL: 8,   # Standard SL
                VolatilityRegime.HIGH: 10,    # Wider SL in high vol
                VolatilityRegime.EXTREME: 15, # Very wide SL in extreme vol
            }
        
        sl_offset_cents = sl_cents_map[vol_metrics.regime]
        
        # Adjust SL based on time to expiry (tighter near expiry)
        if vol_metrics.time_to_expiry_min <= self.TIME_SHORT:
            sl_offset_cents = max(2, sl_offset_cents - 2)
        
        # Compute SL price
        sl_price_cents = max(1, entry_price_cents - sl_offset_cents)
        risk_cents_per_contract = entry_price_cents - sl_price_cents
        
        # TP based on edge and confidence
        # Higher edge + higher confidence = larger TP multiple
        # CRITICAL FIX: Aligned with 15m best practices research (1:1.5 to 1:2 R:R ratio)
        # Research shows 15m scalping should target 1.5-2.0R for optimal risk-reward
        # Base R-multiple ranges by confidence
        if confidence <= 0.3:
            tp_r_multiple = 1.0  # Conservative TP for low confidence
        elif confidence <= 0.6:
            tp_r_multiple = 1.5  # Base TP (1:1.5 R:R - research sweet spot)
        elif confidence <= 0.8:
            tp_r_multiple = 1.8  # Stretch TP (1:1.8 R:R)
        else:
            tp_r_multiple = 2.0  # Aggressive TP (1:2.0 R:R - research upper bound)
        
        # Adjust TP based on volatility (reduce in high vol)
        if vol_metrics.regime == VolatilityRegime.HIGH:
            tp_r_multiple *= 0.8
        elif vol_metrics.regime == VolatilityRegime.EXTREME:
            tp_r_multiple *= 0.6
        
        # Adjust TP based on edge (higher edge = larger TP)
        if edge_pct > 0.10:  # > 10% edge
            tp_r_multiple *= 1.2
        elif edge_pct < 0.03:  # < 3% edge
            tp_r_multiple *= 0.8
        
        tp_r_multiple = max(1.0, min(tp_r_multiple, 2.0))  # CRITICAL: Clamp to 1.0-2.0R (research-aligned)

        # P2 FIX: TTE regime integration - classify and adjust behavior
        from merid.risk.tte_regime import get_tte_classifier, TTERegime
        
        tte_classifier = get_tte_classifier()
        tte_seconds = vol_metrics.time_to_expiry_min * 60.0
        tte_regime = tte_classifier.classify(tte_seconds)
        
        # Adjust behavior based on TTE regime
        if tte_regime == TTERegime.TERMINAL:
            # TERMINAL (<2m): Prefer expiry-driven exits
            tp_r_multiple = 0.0  # Disable TP, rely on expiry
            rationale_base = "expiry_only_tte_terminal"
            logger.info(
                "[DYNAMIC-TP-SL-TTE] market=%s regime=TERMINAL (<2m) - TP disabled, expiry-driven exit",
                "unknown"
            )
        elif tte_regime == TTERegime.CRITICAL:
            # CRITICAL (<5m): Scale TP down aggressively
            tp_r_multiple *= 0.5  # Halve TP target
            rationale_base = "tte_critical_scaled_r"
            logger.info(
                "[DYNAMIC-TP-SL-TTE] market=%s regime=CRITICAL (<5m) - TP scaled by 0.5x",
                "unknown"
            )
        else:
            # NORMAL/APPROACHING: Use existing time-scaling logic
            minutes_to_expiry = vol_metrics.time_to_expiry_min
            if minutes_to_expiry > 10:
                time_scale = 1.0  # Full TP target early in window
            elif minutes_to_expiry > 5:
                time_scale = 0.8  # 80% of target at 5-10 min
            elif minutes_to_expiry > 2:
                time_scale = 0.6  # 60% of target at 2-5 min
            else:
                time_scale = 0.4  # 40% of target near cutoff

            tp_r_multiple_scaled = tp_r_multiple * time_scale
            logger.info(
                "[DYNAMIC-TP-SL] market=%s base_tp_R=%.2f scaled_tp_R=%.2f minutes_to_expiry=%.1f time_scale=%.2f tte_regime=%s",
                "unknown", tp_r_multiple, tp_r_multiple_scaled, minutes_to_expiry, time_scale, tte_regime.value
            )
            tp_r_multiple = tp_r_multiple_scaled
            rationale_base = f"tte_{tte_regime.value}_scaled_r"

        # Compute TP price
        tp_offset_cents = int(risk_cents_per_contract * tp_r_multiple)
        tp_price_cents = min(99, entry_price_cents + tp_offset_cents)

        # P1 FIX: Microstructure sanity check - warn if TP target is below spread
        move_to_tp = abs(tp_price_cents - entry_price_cents)
        spread_cents = vol_metrics.spread_cents if hasattr(vol_metrics, 'spread_cents') else 0
        if move_to_tp < spread_cents and spread_cents > 0:
            logger.warning(
                "[TP-MICROSTRUCTURE-WARN] entry=%dc tp=%dc spread=%dc edge=%.2f%% - TP target below spread, unlikely to hit",
                entry_price_cents, tp_price_cents, spread_cents, edge_pct * 100
            )

        # Compute SL R-multiple (should be 1.0 by definition)
        sl_r_multiple = 1.0
        
        # Build rationale with TTE regime information
        rationale_parts = [
            f"SL: {sl_offset_cents}c ({vol_metrics.regime.value} vol)",
            f"TP: {tp_r_multiple:.1f}R (conf={confidence:.2f}, edge={edge_pct:.1%})",
            f"TTE: {tte_regime.value}",
        ]
        if vol_metrics.time_to_expiry_min <= self.TIME_SHORT:
            rationale_parts.append("tightened for short expiry")
        
        computation_time_ms = (time.time() - t0) * 1000
        
        rationale = f"{rationale_base}; " + "; ".join(rationale_parts)
        
        logger.info(
            "[DYNAMIC-TP-SL] entry=%dc edge=%.1f%% conf=%.2f vol=%s "
            "tp=%dc (%.1fR) sl=%dc risk=%dc rationale=%s",
            entry_price_cents, edge_pct * 100, confidence, vol_metrics.regime.value,
            tp_price_cents, tp_r_multiple, sl_price_cents, risk_cents_per_contract,
            rationale
        )
        
        return TP_SLResult(
            tp_price_cents=tp_price_cents,
            sl_price_cents=sl_price_cents,
            risk_cents_per_contract=risk_cents_per_contract,
            tp_r_multiple=tp_r_multiple,
            sl_r_multiple=sl_r_multiple,
            confidence_used=confidence,
            volatility_regime=vol_metrics.regime,
            computation_time_ms=computation_time_ms,
            rationale="; ".join(rationale_parts),
        )
    
    def compute_position_size(
        self,
        bankroll_usd: float,
        entry_price_cents: int,
        sl_price_cents: int,
        asset: str,
        vol_metrics: VolatilityMetrics,
        risk_budget: RiskBudget,
        existing_exposure_contracts: int = 0,
        asset_exposure_contracts: int = 0,
        global_exposure_contracts: int = 0,
        asset_max_notional_usd: Optional[float] = None,
    ) -> PositionSizeResult:
        """Compute dynamic position size based on risk budget and volatility.
        
        Args:
            bankroll_usd: Current bankroll
            entry_price_cents: Entry price in cents
            sl_price_cents: Stop loss price in cents
            asset: Asset symbol (BTC, ETH, etc.)
            vol_metrics: Volatility metrics
            risk_budget: Current risk budget
            existing_exposure_contracts: Existing contracts in this market
            asset_exposure_contracts: Existing contracts for this asset
            global_exposure_contracts: Total contracts across all assets
            
        Returns:
            PositionSizeResult with computed size and limiting factor
        """
        t0 = time.time()
        
        # Risk per trade in dollars
        risk_dollars = bankroll_usd * risk_budget.risk_per_trade_pct
        
        # Risk per contract in dollars
        risk_cents = abs(entry_price_cents - sl_price_cents)
        risk_dollars_per_contract = risk_cents / 100.0
        
        if risk_dollars_per_contract <= 0:
            logger.warning(
                "[DYNAMIC-SIZING] Zero risk per contract: entry=%dc sl=%dc",
                entry_price_cents, sl_price_cents
            )
            return PositionSizeResult(
                contracts=0,
                risk_dollars=0,
                risk_pct_of_bankroll=0,
                bankroll_used=0,
                per_market_cap=0,
                per_asset_cap=0,
                global_cap=0,
                limiting_factor="zero_risk_per_contract",
                computation_time_ms=(time.time() - t0) * 1000,
                rationale="Risk per contract is zero or negative",
            )
        
        # Base contracts from risk budget
        contracts_from_risk = int(risk_dollars / risk_dollars_per_contract)
        
        # Dynamic caps based on bankroll (not fixed constants)
        # Per-market cap: 5% of bankroll / worst-case loss per contract
        worst_case_loss_cents = entry_price_cents  # Max loss if goes to 0
        worst_case_loss_dollars = worst_case_loss_cents / 100.0
        per_market_cap = int((bankroll_usd * 0.05) / worst_case_loss_dollars)
        
        # Per-asset cap: Use risk envelope's asset_max_notional_usd if provided, else 10% of bankroll
        if asset_max_notional_usd is not None:
            # Convert notional cap to contract cap: max_notional / entry_price
            per_asset_cap = int(asset_max_notional_usd / worst_case_loss_dollars)
        else:
            # Fallback: 10% of bankroll (all 5 crypto assets treated as correlated)
            per_asset_cap = int((bankroll_usd * 0.10) / worst_case_loss_dollars)
        
        # Global cap: 20% of bankroll across all positions
        global_cap = int((bankroll_usd * 0.20) / worst_case_loss_dollars)
        
        # Adjust caps based on volatility (reduce in high vol)
        # FIX: Ensure caps never drop to 0 - minimum of 1 contract to allow trading
        vol_adjustment = {
            VolatilityRegime.LOW: 1.0,
            VolatilityRegime.NORMAL: 1.0,
            VolatilityRegime.HIGH: 0.7,
            VolatilityRegime.EXTREME: 0.5,
        }
        per_market_cap = max(1, int(per_market_cap * vol_adjustment[vol_metrics.regime]))
        per_asset_cap = max(1, int(per_asset_cap * vol_adjustment[vol_metrics.regime]))
        global_cap = max(1, int(global_cap * vol_adjustment[vol_metrics.regime]))
        
        # Apply caps (min of all constraints)
        remaining_per_market = max(0, per_market_cap - existing_exposure_contracts)
        remaining_per_asset = max(0, per_asset_cap - asset_exposure_contracts)
        remaining_global = max(0, global_cap - global_exposure_contracts)
        
        contracts = min(contracts_from_risk, remaining_per_market, remaining_per_asset, remaining_global)
        
        # Determine limiting factor
        if contracts == 0:
            if contracts_from_risk == 0:
                limiting_factor = "risk_budget"
            elif remaining_per_market == 0:
                limiting_factor = "per_market_cap"
            elif remaining_per_asset == 0:
                limiting_factor = "per_asset_cap"
            else:
                limiting_factor = "global_cap"
        elif contracts == contracts_from_risk:
            limiting_factor = "risk_budget"
        elif contracts == remaining_per_market:
            limiting_factor = "per_market_cap"
        elif contracts == remaining_per_asset:
            limiting_factor = "per_asset_cap"
        else:
            limiting_factor = "global_cap"
        
        # Actual risk used
        actual_risk_dollars = contracts * risk_dollars_per_contract
        actual_risk_pct = actual_risk_dollars / bankroll_usd if bankroll_usd > 0 else 0
        
        computation_time_ms = (time.time() - t0) * 1000
        
        logger.info(
            "[DYNAMIC-SIZING] asset=%s entry=%dc sl=%dc bankroll=$%.2f "
            "risk_pct=%.2f%% contracts=%d (from_risk=%d) "
            "caps=[mkt=%d asset=%d glb=%d] limit=%s vol=%s",
            asset, entry_price_cents, sl_price_cents, bankroll_usd,
            actual_risk_pct * 100, contracts, contracts_from_risk,
            per_market_cap, per_asset_cap, global_cap, limiting_factor,
            vol_metrics.regime.value
        )
        
        return PositionSizeResult(
            contracts=contracts,
            risk_dollars=actual_risk_dollars,
            risk_pct_of_bankroll=actual_risk_pct,
            bankroll_used=bankroll_usd,
            per_market_cap=per_market_cap,
            per_asset_cap=per_asset_cap,
            global_cap=global_cap,
            limiting_factor=limiting_factor,
            computation_time_ms=computation_time_ms,
            rationale=f"Risk budget: {risk_budget.risk_per_trade_pct:.2%}, Vol: {vol_metrics.regime.value}, Limit: {limiting_factor}",
        )
    
    def compute_market_band(
        self,
        side: str,  # "buy" or "sell"
        best_bid_cents: int,
        best_ask_cents: int,
        vol_metrics: VolatilityMetrics,
        edge_pct: float,
        confidence: float,
        asset: Optional[str] = None,  # For execution feedback lookup
    ) -> MarketBandResult:
        """Compute dynamic limit price for market-like orders.
        
        Instead of fixed "1 tick beyond best", compute aggressiveness
        based on volatility, edge, confidence, depth, and execution feedback.
        
        Args:
            side: Order side ("buy" or "sell")
            best_bid_cents: Best bid price in cents
            best_ask_cents: Best ask price in cents
            vol_metrics: Volatility metrics
            edge_pct: Edge percentage
            confidence: Signal confidence
            asset: Asset symbol for execution feedback lookup
            
        Returns:
            MarketBandResult with limit price and aggressiveness factor
        """
        t0 = time.time()
        
        spread_cents = best_ask_cents - best_bid_cents
        mid_cents = (best_bid_cents + best_ask_cents) // 2
        
        # Skip if spread is too wide
        if spread_cents >= self.SPREAD_EXTREME:
            return MarketBandResult(
                limit_price_cents=mid_cents,
                aggressiveness_factor=0.0,
                ticks_from_mid=0,
                should_skip=True,
                skip_reason=f"spread too wide: {spread_cents}c",
                computation_time_ms=(time.time() - t0) * 1000,
                rationale=f"Spread {spread_cents}c exceeds threshold {self.SPREAD_EXTREME}c",
            )
        
        # Skip if depth is too low
        # DISABLED: System uses limit orders which wait for fills, not market orders
        # For 15m crypto markets, depth can be thin but limit orders will execute when liquidity appears
        # This check was causing excessive rejections in otherwise tradeable markets
        if False and vol_metrics.depth_at_top < 10:
            return MarketBandResult(
                limit_price_cents=mid_cents,
                aggressiveness_factor=0.0,
                ticks_from_mid=0,
                should_skip=True,
                skip_reason=f"insufficient depth: {vol_metrics.depth_at_top}",
                computation_time_ms=(time.time() - t0) * 1000,
                rationale=f"Depth {vol_metrics.depth_at_top} below threshold 10",
            )
        
        # Compute aggressiveness factor (0-1)
        # Higher edge + higher confidence + lower vol = more aggressive
        base_aggressiveness = 0.5
        
        # Edge contribution
        if edge_pct > 0.10:
            base_aggressiveness += 0.3
        elif edge_pct > 0.05:
            base_aggressiveness += 0.15
        
        # Confidence contribution
        if confidence > 0.8:
            base_aggressiveness += 0.2
        elif confidence > 0.6:
            base_aggressiveness += 0.1
        
        # Volatility penalty (reduce aggressiveness in high vol)
        if vol_metrics.regime == VolatilityRegime.HIGH:
            base_aggressiveness -= 0.2
        elif vol_metrics.regime == VolatilityRegime.EXTREME:
            base_aggressiveness -= 0.4
        
        # EXECUTION FEEDBACK: Adjust aggressiveness based on slippage history
        if asset and asset in self._execution_metrics:
            metrics = self._execution_metrics[asset]
            avg_slippage = metrics.get("avg_slippage", 0.0)
            fill_rate = metrics.get("fill_count", 0) / max(metrics.get("total_orders", 1), 1)
            
            # If slippage is consistently low and fill rate high, be more aggressive
            if avg_slippage < 1.0 and fill_rate > 0.9:
                base_aggressiveness += 0.1
                logger.debug(
                    "[EXECUTION-FEEDBACK] asset=%s slippage=%.2f fill_rate=%.2f -> +0.1 aggressiveness",
                    asset, avg_slippage, fill_rate
                )
            # If slippage is high or fill rate low, be more conservative
            elif avg_slippage > 3.0 or fill_rate < 0.7:
                base_aggressiveness -= 0.15
                logger.debug(
                    "[EXECUTION-FEEDBACK] asset=%s slippage=%.2f fill_rate=%.2f -> -0.15 aggressiveness",
                    asset, avg_slippage, fill_rate
                )
        
        # Spread penalty (reduce aggressiveness on wide spreads)
        if spread_cents >= self.SPREAD_WIDE:
            base_aggressiveness -= 0.15
        
        aggressiveness_factor = max(0.1, min(0.9, base_aggressiveness))
        
        # Compute ticks from mid based on aggressiveness
        # More aggressive = closer to best bid/ask (fewer ticks)
        # Less aggressive = more conservative (more ticks)
        max_ticks = 3
        ticks_from_mid = int(max_ticks * (1.0 - aggressiveness_factor))
        
        # Compute limit price
        if side == "buy":
            # Buy: go up from mid towards ask
            limit_price_cents = min(best_ask_cents, mid_cents + ticks_from_mid)
        else:  # sell
            # Sell: go down from mid towards bid
            limit_price_cents = max(best_bid_cents, mid_cents - ticks_from_mid)
        
        # CRITICAL FIX: Clamp to 55-75 cents to prevent extreme purchases
        # This aligns with kalshi_crypto_15m_v2.yaml price_range [55, 75]
        limit_price_cents = max(55, min(75, limit_price_cents))
        
        computation_time_ms = (time.time() - t0) * 1000
        
        logger.info(
            "[DYNAMIC-BAND] side=%s spread=%dc vol=%s edge=%.1f%% conf=%.2f "
            "agg=%.2f ticks=%d price=%dc",
            side, spread_cents, vol_metrics.regime.value, edge_pct * 100, confidence,
            aggressiveness_factor, ticks_from_mid, limit_price_cents
        )
        
        return MarketBandResult(
            limit_price_cents=limit_price_cents,
            aggressiveness_factor=aggressiveness_factor,
            ticks_from_mid=ticks_from_mid,
            should_skip=False,
            skip_reason=None,
            computation_time_ms=computation_time_ms,
            rationale=f"Aggressiveness {aggressiveness_factor:.2f} based on edge={edge_pct:.1%}, conf={confidence:.2f}, vol={vol_metrics.regime.value}",
        )
    
    def update_execution_metrics(
        self,
        asset: str,
        slippage_cents: float,
        filled: bool,
    ) -> None:
        """Update execution quality metrics for feedback loop.
        
        Args:
            asset: Asset symbol
            slippage_cents: Slippage in cents (intended - actual)
            filled: Whether order filled
        """
        if asset not in self._execution_metrics:
            self._execution_metrics[asset] = {
                "avg_slippage": 0.0,
                "fill_count": 0,
                "total_orders": 0,
            }
        
        metrics = self._execution_metrics[asset]
        metrics["total_orders"] += 1
        
        if filled:
            metrics["fill_count"] += 1
            # Update running average slippage
            n = metrics["fill_count"]
            metrics["avg_slippage"] = (
                (metrics["avg_slippage"] * (n - 1) + slippage_cents) / n
            )
    
    def get_execution_metrics(self, asset: str) -> Optional[Dict]:
        """Get execution metrics for an asset."""
        return self._execution_metrics.get(asset)
    
    def record_pnl(self, pnl_usd: float) -> None:
        """Record PnL for drawdown tracking.
        
        Args:
            pnl_usd: PnL in USD (positive for profit, negative for loss)
        """
        self._recent_pnl_history.append(pnl_usd)
        if len(self._recent_pnl_history) > self._max_history_size:
            self._recent_pnl_history.pop(0)
    
    def get_recent_pnl_sum(self, n: int = 100) -> float:
        """Get sum of recent PnL over last n trades."""
        return sum(self._recent_pnl_history[-n:])
    
    def get_recent_win_rate(self, n: int = 20) -> float:
        """Get win rate over last n trades."""
        if len(self._recent_pnl_history) < n:
            n = len(self._recent_pnl_history)
        if n == 0:
            return 0.5
        
        wins = sum(1 for pnl in self._recent_pnl_history[-n:] if pnl > 0)
        return wins / n


# Singleton instance
_dynamic_risk_engine: Optional[DynamicRiskEngine] = None


def get_dynamic_risk_engine() -> DynamicRiskEngine:
    """Get singleton dynamic risk engine."""
    global _dynamic_risk_engine
    if _dynamic_risk_engine is None:
        _dynamic_risk_engine = DynamicRiskEngine()
    return _dynamic_risk_engine
