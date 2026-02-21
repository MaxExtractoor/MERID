"""
CryptoSwarmRiskBTC15m — Single-lane risk manager for BTC 15m live trading.

Implements the phased risk guardrails for 10.52→equity growth:
- Per-trade cost caps (0.25 base, 0.30 hard)
- Daily loss limits (-0.50 soft stop, -1.00 hard stop)
- Max open exposure (0.50 live BTC 15m)
- Fear/greed size multiplier
- BTC 15m specific filters
- Live vs paper routing
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Dict, List, Optional, Tuple, Any
import logging

logger = logging.getLogger(__name__)


class TradeMode(Enum):
    """Trading mode decision."""
    LIVE = "live"
    PAPER = "paper"
    BLOCKED = "blocked"


class RiskPhase(Enum):
    """Expansion phases based on equity."""
    PHASE_0 = 0  # 10.52-15: BTC 15m only live
    PHASE_1 = 1  # 15-25: BTC 1h live + increased caps
    PHASE_2 = 2  # 25-50: ETH 15m live, more intervals


@dataclass
class FearGreedReading:
    """Fear/greed index reading."""
    value: int  # 0-100
    timestamp: datetime
    
    @property
    def zone(self) -> str:
        if self.value <= 20:
            return "extreme_fear"
        elif self.value >= 80:
            return "extreme_greed"
        else:
            return "normal"


@dataclass
class TradeProposal:
    """Agent trade proposal."""
    asset: str
    timeframe: str
    side: str  # "yes" or "no"
    price_cents: int
    intent_risk: float  # Proposed dollar amount
    tags: List[str] = field(default_factory=list)
    fear_greed: Optional[int] = None
    spread_ticks: Optional[int] = None
    volume_24h: Optional[float] = None
    minutes_to_expiry: Optional[int] = None
    session_stable: bool = True


@dataclass
class RiskDecision:
    """Risk layer output decision."""
    mode: TradeMode
    final_size: float  # Approved dollar amount
    reason: str
    adjustments: Dict[str, Any] = field(default_factory=dict)
    blocked_reason: Optional[str] = None


@dataclass
class DailyRiskState:
    """Daily tracking for loss limits."""
    date: str
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    trades_today: int = 0
    soft_stop_triggered: bool = False
    hard_stop_triggered: bool = False


class CryptoSwarmRiskBTC15m:
    """
    Risk manager for BTC 15m single-lane live trading.
    
    Implements the complete guardrail system:
    - Per-trade cost caps
    - Daily loss limits
    - Open exposure limits
    - Fear/greed multipliers
    - BTC 15m routing logic
    - Phase-based expansion
    """
    
    # === Guardrail Constants (PHASE_0 defaults; overridden by update_from_phase()) ===
    PER_TRADE_BASE = 0.25
    PER_TRADE_HARD_CAP = 0.30
    
    DAILY_SOFT_STOP = -0.50
    DAILY_HARD_STOP = -1.00
    
    MAX_OPEN_EXPOSURE_LIVE = 0.50
    
    # Fear/greed multipliers
    FEAR_GREED_NORMAL_MULT = 1.0
    FEAR_GREED_EXTREME_MULT = 0.6  # 0.15/0.25 = 0.6
    
    # BTC 15m filters
    MAX_SPREAD_TICKS = 4
    MIN_MINUTES_TO_EXPIRY = 3
    
    def __init__(
        self,
        current_equity: float = 0.0,
        phase: RiskPhase = RiskPhase.PHASE_0,
    ):
        self.current_equity = current_equity
        self.phase = phase
        
        # Daily tracking
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self.daily_state = DailyRiskState(date=today)
        
        # Open positions tracking
        self.open_positions: Dict[str, float] = {}  # ticker -> dollar exposure
        self.open_exposure_total = 0.0
        
        # 30-day rolling window for phase promotion
        self.pnl_history: List[Tuple[datetime, float]] = []
        self.max_drawdown_30d = 0.0
        self.risk_overrides_count = 0
        
        # Fear/greed cache
        self.fear_greed_cache: Optional[FearGreedReading] = None
        
        logger.info(
            f"CryptoSwarmRiskBTC15m initialized: equity=${current_equity:.2f}, "
            f"phase={phase.name}"
        )

    def update_from_phase(self, equity: float) -> None:
        """
        Sync per-trade cap and exposure limit from the PromotionEngine's
        current phase.  Call this whenever PromotionEngine advances/demotes.

        Falls back to PHASE_0 constants if PromotionEngine is unavailable.
        """
        try:
            from merid.risk.promotion_engine import get_promotion_engine
            caps = get_promotion_engine().get_caps(equity)
            self.PER_TRADE_HARD_CAP = caps["per_trade"]
            self.MAX_OPEN_EXPOSURE_LIVE = caps["max_exposure"]
            logger.debug(
                "CryptoSwarmRiskBTC15m: caps updated from phase %s — "
                "per_trade=%.3f max_exposure=%.3f",
                caps["phase"], self.PER_TRADE_HARD_CAP, self.MAX_OPEN_EXPOSURE_LIVE,
            )
        except Exception as exc:
            logger.debug("update_from_phase: PromotionEngine unavailable (%s), using defaults", exc)
    
    def evaluate_proposal(self, proposal: TradeProposal) -> RiskDecision:
        """
        Main entry point: evaluate a trade proposal and return decision.
        
        Implements the complete risk pipeline:
        1. Route: Live vs Paper vs Blocked
        2. Daily loss checks
        3. Exposure checks
        4. Fear/greed sizing
        5. BTC 15m filters
        6. Final size adjustment
        """
        adjustments = {}
        
        # === Step 1: Route decision ===
        route_decision = self._determine_route(proposal)
        if route_decision.mode == TradeMode.BLOCKED:
            return route_decision
        
        # === Step 2: Daily loss limit checks ===
        loss_check = self._check_daily_loss_limits()
        if loss_check:
            return RiskDecision(
                mode=TradeMode.BLOCKED,
                final_size=0.0,
                reason=loss_check,
                blocked_reason=loss_check,
            )
        
        # === Step 3: Open exposure check ===
        exposure_check = self._check_open_exposure(proposal.intent_risk)
        if exposure_check:
            return RiskDecision(
                mode=TradeMode.BLOCKED,
                final_size=0.0,
                reason=exposure_check,
                blocked_reason=exposure_check,
            )
        
        # === Step 4: BTC 15m microstructure filters ===
        filter_check = self._apply_btc15m_filters(proposal)
        if filter_check:
            # Filters force to paper, not block entirely
            route_decision.mode = TradeMode.PAPER
            adjustments['filter_forced_paper'] = filter_check
        
        # === Step 5: Fear/greed sizing ===
        fear_greed_mult = self._get_fear_greed_multiplier(proposal)
        base_size = min(proposal.intent_risk, self.PER_TRADE_HARD_CAP)
        adjusted_size = base_size * fear_greed_mult
        
        if fear_greed_mult != 1.0:
            adjustments['fear_greed_multiplier'] = fear_greed_mult
            adjustments['fear_greed_value'] = proposal.fear_greed or self.fear_greed_cache.value if self.fear_greed_cache else None
        
        # === Step 6: Per-trade cap enforcement ===
        final_size = min(adjusted_size, self.PER_TRADE_HARD_CAP)
        if final_size < proposal.intent_risk:
            adjustments['capped_by_per_trade_limit'] = {
                'requested': proposal.intent_risk,
                'approved': final_size,
            }
        
        # === Step 7: Daily soft stop sizing ===
        if self.daily_state.soft_stop_triggered:
            final_size = final_size * 0.5  # Halve size on soft stop
            adjustments['soft_stop_halved'] = True
        
        # Build reason string
        if route_decision.mode == TradeMode.PAPER:
            reason = f"Routed to paper: {route_decision.reason}"
        else:
            reason = f"Approved live: size=${final_size:.2f}"
            if adjustments:
                reason += f" (adjustments: {list(adjustments.keys())})"
        
        return RiskDecision(
            mode=route_decision.mode,
            final_size=final_size,
            reason=reason,
            adjustments=adjustments,
        )
    
    def _determine_route(self, proposal: TradeProposal) -> RiskDecision:
        """
        Determine if proposal goes live, paper, or blocked.
        
        Phase 0 rules:
        - BTC 15m: Eligible for live
        - Everything else: Forced to paper
        """
        # Check instrument eligibility
        is_btc = proposal.asset.upper() == "BTC"
        is_15m = proposal.timeframe == "15m"
        
        if not is_btc or not is_15m:
            # Force to paper
            return RiskDecision(
                mode=TradeMode.PAPER,
                final_size=proposal.intent_risk,
                reason=f"{proposal.asset} {proposal.timeframe} forced to paper (Phase 0: BTC 15m only live)",
            )
        
        # BTC 15m is eligible for live
        return RiskDecision(
            mode=TradeMode.LIVE,
            final_size=proposal.intent_risk,
            reason="BTC 15m eligible for live",
        )
    
    def _check_daily_loss_limits(self) -> Optional[str]:
        """Check if daily loss limits are breached."""
        total_pnl = self.daily_state.realized_pnl + self.daily_state.unrealized_pnl
        
        # Hard stop check
        if total_pnl <= self.DAILY_HARD_STOP:
            self.daily_state.hard_stop_triggered = True
            return f"Daily hard stop breached: ${total_pnl:.2f} <= ${self.DAILY_HARD_STOP:.2f}"
        
        # Soft stop check (only trigger once)
        if total_pnl <= self.DAILY_SOFT_STOP and not self.daily_state.soft_stop_triggered:
            self.daily_state.soft_stop_triggered = True
            logger.warning(f"Daily soft stop triggered: ${total_pnl:.2f}")
        
        return None
    
    def _check_open_exposure(self, proposed_size: float) -> Optional[str]:
        """Check if adding this trade would breach exposure limits."""
        projected_exposure = self.open_exposure_total + proposed_size
        
        if projected_exposure > self.MAX_OPEN_EXPOSURE_LIVE:
            return (
                f"Max open exposure would be breached: "
                f"${projected_exposure:.2f} > ${self.MAX_OPEN_EXPOSURE_LIVE:.2f} "
                f"(current: ${self.open_exposure_total:.2f})"
            )
        
        return None
    
    def _apply_btc15m_filters(self, proposal: TradeProposal) -> Optional[str]:
        """
        Apply BTC 15m specific microstructure filters.
        Returns reason if trade should be forced to paper.
        """
        filters_triggered = []
        
        # Spread filter
        if proposal.spread_ticks is not None:
            if proposal.spread_ticks > self.MAX_SPREAD_TICKS:
                filters_triggered.append(f"spread {proposal.spread_ticks} > {self.MAX_SPREAD_TICKS} ticks")
        
        # Time to expiry filter
        if proposal.minutes_to_expiry is not None:
            if proposal.minutes_to_expiry < self.MIN_MINUTES_TO_EXPIRY:
                filters_triggered.append(f"expires in {proposal.minutes_to_expiry}m < {self.MIN_MINUTES_TO_EXPIRY}m")
        
        # Session stability filter
        if not proposal.session_stable:
            filters_triggered.append("unstable regime (volatility spike)")
        
        # Volume filter (minimum $10k volume)
        if proposal.volume_24h is not None:
            if proposal.volume_24h < 10000:
                filters_triggered.append(f"low volume ${proposal.volume_24h:.0f} < $10k")
        
        if filters_triggered:
            return "; ".join(filters_triggered)
        
        return None
    
    def _get_fear_greed_multiplier(self, proposal: TradeProposal) -> float:
        """
        Calculate fear/greed size multiplier.
        
        Logic:
        - 20-80 (normal): base multiplier 1.0
        - 0-20 (extreme fear) or 80-100 (extreme greed): 0.6 multiplier
        - Exception: contrarian trades in extremes keep 1.0
        """
        fg_value = proposal.fear_greed
        if fg_value is None and self.fear_greed_cache:
            fg_value = self.fear_greed_cache.value
        
        if fg_value is None:
            return self.FEAR_GREED_NORMAL_MULT
        
        # Normal zone
        if 20 <= fg_value <= 80:
            return self.FEAR_GREED_NORMAL_MULT
        
        # Extreme zone - check for contrarian
        is_extreme = fg_value <= 20 or fg_value >= 80
        
        if is_extreme:
            # Determine if this is contrarian
            # Extreme fear (0-20): crowd is fearful, "yes" is contrarian (bullish)
            # Extreme greed (80-100): crowd is greedy, "no" is contrarian (bearish)
            if fg_value <= 20 and proposal.side == "yes":
                # Contrarian bullish in extreme fear - full size OK
                return self.FEAR_GREED_NORMAL_MULT
            elif fg_value >= 80 and proposal.side == "no":
                # Contrarian bearish in extreme greed - full size OK
                return self.FEAR_GREED_NORMAL_MULT
            else:
                # Pro-trend in extremes - reduce size
                return self.FEAR_GREED_EXTREME_MULT
        
        return self.FEAR_GREED_NORMAL_MULT
    
    def evaluate_arb_proposal(self, proposal: TradeProposal) -> RiskDecision:
        """
        Risk path for correlation/arbitrage trades.

        Skips the BTC-15m instrument gate (arb trades are not directional
        15m bets) but still enforces:
          - Daily hard/soft stop
          - Open exposure cap
          - Fear/greed size multiplier
          - Per-trade hard cap

        Returns RiskDecision with mode LIVE/PAPER/BLOCKED.
        """
        adjustments: Dict[str, Any] = {}

        # Daily loss limits
        loss_check = self._check_daily_loss_limits()
        if loss_check:
            return RiskDecision(
                mode=TradeMode.BLOCKED,
                final_size=0.0,
                reason=loss_check,
                blocked_reason=loss_check,
            )

        # Exposure cap
        exposure_check = self._check_open_exposure(proposal.intent_risk)
        if exposure_check:
            return RiskDecision(
                mode=TradeMode.BLOCKED,
                final_size=0.0,
                reason=exposure_check,
                blocked_reason=exposure_check,
            )

        # Fear/greed sizing
        fg_mult = self._get_fear_greed_multiplier(proposal)
        base_size = min(proposal.intent_risk, self.PER_TRADE_HARD_CAP)
        adjusted_size = base_size * fg_mult

        if fg_mult != 1.0:
            adjustments["fear_greed_multiplier"] = fg_mult

        final_size = min(adjusted_size, self.PER_TRADE_HARD_CAP)

        if self.daily_state.soft_stop_triggered:
            final_size *= 0.5
            adjustments["soft_stop_halved"] = True

        # Arb trades are paper-only by default regardless of phase.
        # Set arb_live_enabled=True on the instance to allow live arb execution.
        arb_live = getattr(self, "arb_live_enabled", False)
        mode = TradeMode.LIVE if arb_live else TradeMode.PAPER
        reason = f"Arb approved ({mode.value}): size=${final_size:.2f}"
        if adjustments:
            reason += f" adjustments={list(adjustments.keys())}"

        logger.info("evaluate_arb_proposal: %s", reason)
        return RiskDecision(
            mode=mode,
            final_size=final_size,
            reason=reason,
            adjustments=adjustments,
        )

    def update_fear_greed(self, value: int) -> None:
        """Update cached fear/greed reading."""
        self.fear_greed_cache = FearGreedReading(
            value=value,
            timestamp=datetime.now(timezone.utc),
        )
        logger.info(f"Fear/greed updated: {value} ({self.fear_greed_cache.zone})")
    
    def record_trade_result(
        self,
        ticker: str,
        realized_pnl: float,
        mode: TradeMode,
    ) -> None:
        """Record trade result for daily tracking."""
        self.daily_state.realized_pnl += realized_pnl
        self.daily_state.trades_today += 1
        
        # Track for 30-day window
        self.pnl_history.append((datetime.now(timezone.utc), realized_pnl))
        self._trim_pnl_history()
        self._update_drawdown()
        
        logger.info(
            f"Trade result recorded: {ticker} ${realized_pnl:+.2f} "
            f"(mode={mode.value}, daily_pnl=${self.daily_state.realized_pnl:+.2f})"
        )
    
    def _trim_pnl_history(self) -> None:
        """Remove entries older than 30 days."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        self.pnl_history = [(t, p) for t, p in self.pnl_history if t > cutoff]
    
    def _update_drawdown(self) -> None:
        """Calculate max drawdown from 30-day history."""
        if not self.pnl_history:
            return
        
        cumulative = 0.0
        peak = 0.0
        max_dd = 0.0
        
        for _, pnl in sorted(self.pnl_history, key=lambda x: x[0]):
            cumulative += pnl
            if cumulative > peak:
                peak = cumulative
            dd = peak - cumulative
            if dd > max_dd:
                max_dd = dd
        
        self.max_drawdown_30d = max_dd
    
    def get_phase_promotion_status(self) -> Dict[str, Any]:
        """
        Check if current performance qualifies for phase promotion.
        
        Phase 1 requirements (from 10.52→15):
        - End 30-day window with PnL >= +5
        - Max drawdown <= 20%
        - No risk rule overrides
        """
        if self.phase != RiskPhase.PHASE_0:
            return {"eligible": False, "reason": "Already beyond Phase 0"}
        
        thirty_day_pnl = sum(p for _, p in self.pnl_history)
        
        requirements = {
            "30d_pnl_min_5": thirty_day_pnl >= 5.0,
            "max_dd_under_20pct": self.max_drawdown_30d <= (self.current_equity * 0.20),
            "no_risk_overrides": self.risk_overrides_count == 0,
        }
        
        all_met = all(requirements.values())
        
        return {
            "eligible": all_met,
            "current_equity": self.current_equity,
            "30d_pnl": thirty_day_pnl,
            "max_drawdown_30d": self.max_drawdown_30d,
            "risk_overrides": self.risk_overrides_count,
            "requirements": requirements,
            "next_phase": RiskPhase.PHASE_1.name if all_met else None,
        }
    
    def reset_daily_state(self) -> None:
        """Reset daily tracking (call at market open)."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if today != self.daily_state.date:
            logger.info(f"Resetting daily risk state for {today}")
            self.daily_state = DailyRiskState(date=today)
    
    def add_open_position(self, ticker: str, size: float) -> None:
        """Track open position."""
        self.open_positions[ticker] = size
        self.open_exposure_total = sum(self.open_positions.values())
        logger.debug(f"Open position added: {ticker} ${size:.2f} (total: ${self.open_exposure_total:.2f})")
    
    def remove_open_position(self, ticker: str) -> None:
        """Remove closed position."""
        if ticker in self.open_positions:
            size = self.open_positions.pop(ticker)
            self.open_exposure_total = sum(self.open_positions.values())
            logger.debug(f"Open position removed: {ticker} ${size:.2f} (total: ${self.open_exposure_total:.2f})")
    
    def get_status_summary(self) -> Dict[str, Any]:
        """Get current risk status for dashboard."""
        total_pnl = self.daily_state.realized_pnl + self.daily_state.unrealized_pnl
        
        return {
            "phase": self.phase.name,
            "equity": self.current_equity,
            "daily_realized_pnl": self.daily_state.realized_pnl,
            "daily_unrealized_pnl": self.daily_state.unrealized_pnl,
            "daily_total_pnl": total_pnl,
            "soft_stop_triggered": self.daily_state.soft_stop_triggered,
            "hard_stop_triggered": self.daily_state.hard_stop_triggered,
            "open_exposure": self.open_exposure_total,
            "open_positions_count": len(self.open_positions),
            "max_open_exposure": self.MAX_OPEN_EXPOSURE_LIVE,
            "trades_today": self.daily_state.trades_today,
            "fear_greed": {
                "value": self.fear_greed_cache.value if self.fear_greed_cache else None,
                "zone": self.fear_greed_cache.zone if self.fear_greed_cache else None,
            },
            "phase_promotion": self.get_phase_promotion_status(),
        }
