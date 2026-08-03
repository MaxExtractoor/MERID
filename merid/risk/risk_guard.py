"""
MERID RiskGuard Service - Section 7: Safety, Risk, and Governance

Validates all trade plans against global risk limits BEFORE execution.
Implements smart-contract-style rules that LLMs cannot bypass.

Key Features:
- Global risk limits (max position, max exposure, max daily loss)
- Tradable universe allowlist
- Permission model enforcement
- Kill switch implementation
- No agent has direct signing power
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from utils.logger import get_logger

logger = get_logger("risk.risk_guard")


class RiskDecision(str, Enum):
    """Risk review decisions."""
    APPROVE = "approve"
    APPROVE_REDUCED = "approve_reduced"
    REJECT = "reject"
    VETO = "veto"


class LimitType(str, Enum):
    """Types of risk limits."""
    MAX_POSITION_USD = "max_position_usd"
    MAX_EXPOSURE_USD = "max_exposure_usd"
    MAX_LEVERAGE = "max_leverage"
    MAX_DAILY_LOSS_USD = "max_daily_loss_usd"
    MAX_DRAWDOWN_PCT = "max_drawdown_pct"
    MAX_CONCENTRATION_PCT = "max_concentration_pct"
    MAX_SINGLE_TRADE_USD = "max_single_trade_usd"


@dataclass
class RiskLimits:
    """Global risk limit configuration.
    
    PRODUCTION SAFETY: All defaults are 0. Limits must be configured explicitly
    from live bankroll (1-2% of equity) - never use hardcoded values.
    """
    # Position limits - MUST be set from live bankroll (e.g., 1-2% of equity)
    max_position_usd_per_symbol: float = 0.0  # No default - configure from bankroll
    max_total_exposure_usd: float = 0.0  # No default - configure from bankroll
    max_leverage: float = 3.0
    
    # Loss limits - MUST be set from live bankroll (e.g., daily loss limit)
    max_daily_loss_usd: float = 0.0  # No default - configure from bankroll
    max_drawdown_pct: float = 10.0
    
    # Concentration limits
    max_concentration_pct: float = 25.0  # Max % of portfolio in single asset
    max_venue_concentration_pct: float = 50.0  # Max % on single venue
    
    # Per-trade limits - MUST be set from live bankroll
    max_single_trade_usd: float = 0.0  # No default - configure from bankroll
    # 2026-07-28: CRITICAL FIX - Lowered from 0.65 to 0.50 to match signal generation range
    # Signal generation produces confidence = 0.5 + edge (edge is 0.02-0.08), resulting in 52-58%
    # Profile YAML is the authoritative source for confidence thresholds
    min_confidence_for_trade: float = 0.50
    
    # Timing limits
    min_time_between_trades_seconds: float = 60.0
    max_trades_per_hour: int = 20
    
    # Version for tracking changes
    version: str = "1.0.0"
    updated_at: float = field(default_factory=time.time)
    updated_by: str = "system"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "max_position_usd_per_symbol": self.max_position_usd_per_symbol,
            "max_total_exposure_usd": self.max_total_exposure_usd,
            "max_leverage": self.max_leverage,
            "max_daily_loss_usd": self.max_daily_loss_usd,
            "max_drawdown_pct": self.max_drawdown_pct,
            "max_concentration_pct": self.max_concentration_pct,
            "max_venue_concentration_pct": self.max_venue_concentration_pct,
            "max_single_trade_usd": self.max_single_trade_usd,
            "min_confidence_for_trade": self.min_confidence_for_trade,
            "min_time_between_trades_seconds": self.min_time_between_trades_seconds,
            "max_trades_per_hour": self.max_trades_per_hour,
            "version": self.version,
            "updated_at": self.updated_at,
            "updated_by": self.updated_by,
        }


@dataclass
class TradableUniverse:
    """Allowlist of tradable symbols and venues."""
    allowed_symbols: Set[str] = field(default_factory=set)
    allowed_venues: Set[str] = field(default_factory=set)
    blocked_symbols: Set[str] = field(default_factory=set)
    blocked_venues: Set[str] = field(default_factory=set)
    
    # Per-symbol overrides
    symbol_limits: Dict[str, float] = field(default_factory=dict)  # symbol -> max_usd
    
    version: str = "1.0.0"
    updated_at: float = field(default_factory=time.time)
    
    def is_symbol_allowed(self, symbol: str) -> bool:
        """Check if symbol is allowed for trading."""
        if symbol in self.blocked_symbols:
            return False
        if self.allowed_symbols and symbol not in self.allowed_symbols:
            return False
        return True
    
    def is_venue_allowed(self, venue: str) -> bool:
        """Check if venue is allowed for trading."""
        if venue in self.blocked_venues:
            return False
        if self.allowed_venues and venue not in self.allowed_venues:
            return False
        return True
    
    def get_symbol_limit(self, symbol: str, default: float) -> float:
        """Get position limit for a specific symbol."""
        return self.symbol_limits.get(symbol, default)


@dataclass
class PortfolioState:
    """Current portfolio state for risk calculations."""
    total_exposure_usd: float = 0.0
    net_exposure_usd: float = 0.0
    positions: Dict[str, float] = field(default_factory=dict)  # symbol -> usd
    venue_exposure: Dict[str, float] = field(default_factory=dict)  # venue -> usd
    
    daily_pnl_usd: float = 0.0
    daily_trades: int = 0
    last_trade_time: float = 0.0
    
    current_drawdown_pct: float = 0.0
    high_water_mark_usd: float = 0.0
    
    def get_position_size(self, symbol: str) -> float:
        """Get current position size for symbol."""
        return self.positions.get(symbol, 0.0)
    
    def get_concentration(self, symbol: str) -> float:
        """Get concentration % for symbol."""
        if self.total_exposure_usd <= 0:
            return 0.0
        return abs(self.positions.get(symbol, 0.0)) / self.total_exposure_usd * 100


@dataclass
class RiskReviewResult:
    """Result of risk review."""
    review_id: str = field(default_factory=lambda: f"rr_{uuid.uuid4().hex[:12]}")
    plan_id: str = ""
    
    decision: RiskDecision = RiskDecision.REJECT
    approved_size_usd: float = 0.0
    original_size_usd: float = 0.0
    
    limit_breaches: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    reason: str = ""
    
    timestamp: float = field(default_factory=time.time)
    reviewed_by: str = "risk_guard"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "review_id": self.review_id,
            "plan_id": self.plan_id,
            "decision": self.decision.value,
            "approved_size_usd": self.approved_size_usd,
            "original_size_usd": self.original_size_usd,
            "limit_breaches": self.limit_breaches,
            "warnings": self.warnings,
            "reason": self.reason,
            "timestamp": self.timestamp,
            "reviewed_by": self.reviewed_by,
        }


@dataclass
class TradePlanInput:
    """Input trade plan for risk review."""
    plan_id: str
    symbol: str
    venue: str
    direction: str  # long, short, flat, reduce
    target_size_usd: float
    confidence: float
    agent_id: str
    consensus_score: float = 0.0


class RiskGuard:
    """
    Risk guard service that validates all trade plans.
    
    This is the gatekeeper - NO trade can execute without passing through here.
    Implements smart-contract-style rules that agents cannot bypass.
    """
    
    _instance: Optional["RiskGuard"] = None
    
    def __init__(self):
        self.limits = RiskLimits()
        self.universe = TradableUniverse()
        self.portfolio = PortfolioState()
        
        self._kill_switch_active = False
        self._kill_switch_reason = ""
        self._kill_switch_time: float = 0.0
        
        self._paused = False
        self._pause_reason = ""
        
        self._review_history: List[RiskReviewResult] = []
        self._event_handlers: List[Callable] = []
        self._lock = asyncio.Lock()
        
        # Hourly trade counter
        self._hourly_trades: List[float] = []

        # T-054: Persist drawdown state
        self._risk_state_path = Path("data/risk_state.json")
        self._load_risk_state()

        logger.info("RiskGuard initialized")
    
    @classmethod
    def get_instance(cls) -> "RiskGuard":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def _load_risk_state(self) -> None:
        """T-054: Load persisted drawdown state from disk."""
        try:
            if self._risk_state_path.exists():
                data = json.loads(self._risk_state_path.read_text())
                self.portfolio.high_water_mark_usd = data.get("high_water_mark", 0.0)
                self.portfolio.current_drawdown_pct = data.get("current_drawdown_pct", 0.0)
                self.portfolio.daily_pnl_usd = data.get("daily_pnl", 0.0)
                logger.info(
                    "Loaded risk state: HWM=%.2f drawdown=%.2f%%",
                    self.portfolio.high_water_mark_usd,
                    self.portfolio.current_drawdown_pct,
                )
            else:
                logger.warning("No risk state file — starting conservatively (0 drawdown)")
        except Exception as exc:
            logger.error("Failed to load risk state: %s — starting conservatively", exc)

    def _save_risk_state(self) -> None:
        """T-054: Persist drawdown state to disk."""
        try:
            self._risk_state_path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "high_water_mark": self.portfolio.high_water_mark_usd,
                "current_drawdown_pct": self.portfolio.current_drawdown_pct,
                "daily_pnl": self.portfolio.daily_pnl_usd,
                "daily_trades": self.portfolio.daily_trades,
                "last_updated": time.time(),
            }
            self._risk_state_path.write_text(json.dumps(data, indent=2))
        except Exception as exc:
            logger.error("Failed to save risk state: %s", exc)

    def subscribe_events(self, handler: Callable) -> None:
        """Subscribe to risk events."""
        self._event_handlers.append(handler)
    
    async def _emit_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """Emit risk event."""
        for handler in self._event_handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(event_type, data)
                else:
                    handler(event_type, data)
            except Exception as e:
                logger.error(f"Risk event handler error: {e}")
    
    # ============================================
    # KILL SWITCH
    # ============================================
    
    async def trigger_kill_switch(self, reason: str, triggered_by: str) -> None:
        """
        Trigger the global kill switch.
        Halts ALL trading immediately.
        """
        async with self._lock:
            self._kill_switch_active = True
            self._kill_switch_reason = reason
            self._kill_switch_time = time.time()
            
            logger.critical(f"KILL SWITCH ACTIVATED by {triggered_by}: {reason}")
            
            await self._emit_event("governance.kill_switch", {
                "active": True,
                "reason": reason,
                "triggered_by": triggered_by,
                "timestamp": self._kill_switch_time,
            })
    
    async def reset_kill_switch(self, reset_by: str, confirmation_code: str) -> bool:
        """
        Reset kill switch. Requires time-based OTP for safety (T-013).
        Rate limited: max 3 attempts per 5 minutes.
        Cooldown: minimum 60s between activation and reset.
        """
        now = time.time()

        # Rate limit: max 3 attempts per 5 minutes
        if not hasattr(self, '_reset_attempts'):
            self._reset_attempts: list = []
        self._reset_attempts = [t for t in self._reset_attempts if now - t < 300]
        if len(self._reset_attempts) >= 3:
            logger.warning("Kill switch reset rate limited: too many attempts by %s", reset_by)
            return False
        self._reset_attempts.append(now)

        # Cooldown: minimum 60s since kill switch was activated
        if hasattr(self, '_kill_switch_time') and self._kill_switch_time:
            elapsed = now - self._kill_switch_time
            if elapsed < 60:
                logger.warning(
                    "Kill switch reset too soon: %.0fs elapsed, 60s required (by %s)",
                    elapsed, reset_by,
                )
                return False

        # T-013: Time-based OTP — code rotates every 5 minutes based on secret seed
        import hashlib
        import os as _os
        seed = _os.environ.get("MERID_KILL_SWITCH_SEED", "merid-default-seed-CHANGE-ME")
        time_slot = str(int(now // 300))  # 5-minute window
        expected_code = hashlib.sha256(f"{seed}:{time_slot}".encode()).hexdigest()[:12]
        if confirmation_code != expected_code:
            logger.warning("Kill switch reset failed: invalid OTP by %s", reset_by)
            return False

        async with self._lock:
            self._kill_switch_active = False
            self._kill_switch_reason = ""

            logger.info("Kill switch reset by %s (OTP verified)", reset_by)

            await self._emit_event("governance.kill_switch", {
                "active": False,
                "reset_by": reset_by,
                "timestamp": now,
            })

            return True
    
    def is_kill_switch_active(self) -> bool:
        """Check if kill switch is active."""
        return self._kill_switch_active
    
    # ============================================
    # PAUSE/RESUME
    # ============================================
    
    async def pause_trading(self, reason: str, paused_by: str) -> None:
        """Pause trading temporarily."""
        async with self._lock:
            self._paused = True
            self._pause_reason = reason
            logger.warning(f"Trading paused by {paused_by}: {reason}")
            
            await self._emit_event("risk.trading_paused", {
                "paused": True,
                "reason": reason,
                "paused_by": paused_by,
            })
    
    async def resume_trading(self, resumed_by: str) -> None:
        """Resume trading."""
        async with self._lock:
            self._paused = False
            self._pause_reason = ""
            logger.info(f"Trading resumed by {resumed_by}")
            
            await self._emit_event("risk.trading_resumed", {
                "resumed_by": resumed_by,
            })
    
    # ============================================
    # LIMIT UPDATES
    # ============================================
    
    async def update_limits(
        self,
        new_limits: Dict[str, Any],
        updated_by: str,
        requires_dual_approval: bool = True,
    ) -> str:
        """
        Propose risk limit changes (T-012).
        Returns a change_id. Changes are NOT applied until a second
        distinct approver calls approve_limit_change(change_id).
        """
        import uuid as _uuid
        change_id = f"lc-{_uuid.uuid4().hex[:8]}"

        if not hasattr(self, '_pending_limit_changes'):
            self._pending_limit_changes: Dict[str, Dict[str, Any]] = {}

        self._pending_limit_changes[change_id] = {
            "proposed_by": updated_by,
            "proposed_at": time.time(),
            "new_limits": new_limits,
            "approvers": [updated_by],  # Proposer counts as first approver
            "applied": False,
        }

        logger.info(
            "Risk limit change proposed by %s (change_id=%s). Awaiting second approval.",
            updated_by, change_id,
        )

        await self._emit_event("governance.limit_change_proposed", {
            "change_id": change_id,
            "proposed_by": updated_by,
            "changes": new_limits,
        })

        if not requires_dual_approval:
            # Auto-approve if dual approval not required (testing only)
            await self._apply_limit_change(change_id)

        return change_id

    async def approve_limit_change(self, change_id: str, approved_by: str) -> bool:
        """
        Approve a pending limit change (T-012). Requires a DIFFERENT
        approver than the proposer. After 2 distinct approvers, changes apply.
        """
        if not hasattr(self, '_pending_limit_changes'):
            self._pending_limit_changes = {}

        pending = self._pending_limit_changes.get(change_id)
        if not pending:
            logger.warning("Limit change %s not found", change_id)
            return False
        if pending["applied"]:
            logger.warning("Limit change %s already applied", change_id)
            return False
        if approved_by in pending["approvers"]:
            logger.warning(
                "Limit change %s: %s already approved (need different approver)",
                change_id, approved_by,
            )
            return False

        pending["approvers"].append(approved_by)
        logger.info(
            "Limit change %s approved by %s (%d/2 approvals)",
            change_id, approved_by, len(pending["approvers"]),
        )

        if len(pending["approvers"]) >= 2:
            await self._apply_limit_change(change_id)
            return True
        return True

    async def _apply_limit_change(self, change_id: str) -> None:
        """Apply an approved limit change."""
        pending = self._pending_limit_changes[change_id]
        new_limits = pending["new_limits"]

        async with self._lock:
            old_version = self.limits.version

            for key, value in new_limits.items():
                if hasattr(self.limits, key):
                    setattr(self.limits, key, value)

            major, minor, _patch = self.limits.version.split(".")
            self.limits.version = f"{major}.{int(minor) + 1}.0"
            self.limits.updated_at = time.time()
            self.limits.updated_by = ", ".join(pending["approvers"])

            pending["applied"] = True

            logger.info(
                "Risk limits APPLIED (change_id=%s): %s -> %s (approved by: %s)",
                change_id, old_version, self.limits.version,
                ", ".join(pending["approvers"]),
            )

            await self._emit_event("governance.limit_change", {
                "change_id": change_id,
                "old_version": old_version,
                "new_version": self.limits.version,
                "changes": new_limits,
                "approvers": pending["approvers"],
            })
    
    # ============================================
    # UNIVERSE MANAGEMENT
    # ============================================
    
    def add_symbol(self, symbol: str, max_position_usd: Optional[float] = None) -> None:
        """Add symbol to tradable universe."""
        self.universe.allowed_symbols.add(symbol)
        self.universe.blocked_symbols.discard(symbol)
        if max_position_usd:
            self.universe.symbol_limits[symbol] = max_position_usd
        logger.info(f"Symbol {symbol} added to tradable universe")
    
    def remove_symbol(self, symbol: str) -> None:
        """Remove symbol from tradable universe."""
        self.universe.blocked_symbols.add(symbol)
        self.universe.allowed_symbols.discard(symbol)
        logger.info(f"Symbol {symbol} removed from tradable universe")
    
    def add_venue(self, venue: str) -> None:
        """Add venue to allowed venues."""
        self.universe.allowed_venues.add(venue)
        self.universe.blocked_venues.discard(venue)
        logger.info(f"Venue {venue} added to allowed venues")
    
    def remove_venue(self, venue: str) -> None:
        """Remove venue from allowed venues."""
        self.universe.blocked_venues.add(venue)
        self.universe.allowed_venues.discard(venue)
        logger.info(f"Venue {venue} removed from allowed venues")
    
    # ============================================
    # PORTFOLIO STATE UPDATE
    # ============================================
    
    def update_portfolio(self, state: PortfolioState) -> None:
        """Update current portfolio state."""
        self.portfolio = state
    
    def _sync_pnl_from_ledger(self) -> None:
        """Pull daily P&L from fills_ledger (canonical source).
        
        Fixes stale self.portfolio.daily_pnl_usd which was never updated
        because record_trade() was never called by any component.
        """
        try:
            from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
            _ledger = get_fills_ledger()
            _summary = _ledger.summary()
            # Include both realized and unrealized PnL for daily PnL to show mark-to-market performance
            daily_realized = float(_summary.get("daily_realized_pnl_usd", 0.0))
            total_unrealized = float(_summary.get("total_unrealized_pnl_usd", 0.0))
            self.portfolio.daily_pnl_usd = daily_realized + total_unrealized
        except Exception:
            pass

    def record_trade(self, symbol: str, size_usd: float, pnl_usd: float = 0.0) -> None:
        """Record a trade execution."""
        now = time.time()
        self.portfolio.last_trade_time = now
        self.portfolio.daily_trades += 1
        # Sync P&L from fills_ledger instead of naive accumulation
        self._sync_pnl_from_ledger()
        
        # Update position
        current = self.portfolio.positions.get(symbol, 0.0)
        self.portfolio.positions[symbol] = current + size_usd
        
        # Track hourly trades
        self._hourly_trades.append(now)
        # Prune old trades
        cutoff = now - 3600
        self._hourly_trades = [t for t in self._hourly_trades if t >= cutoff]
    
    # ============================================
    # RISK REVIEW
    # ============================================
    
    async def review_plan(self, plan: TradePlanInput) -> RiskReviewResult:
        """
        Review a trade plan against all risk limits.
        This is the main entry point for risk validation.
        """
        async with self._lock:
            result = RiskReviewResult(
                plan_id=plan.plan_id,
                original_size_usd=plan.target_size_usd,
            )
            
            # Check kill switch first
            if self._kill_switch_active:
                result.decision = RiskDecision.VETO
                result.reason = f"Kill switch active: {self._kill_switch_reason}"
                result.limit_breaches.append("KILL_SWITCH_ACTIVE")
                self._record_review(result)
                return result
            
            # Check if paused
            if self._paused:
                result.decision = RiskDecision.REJECT
                result.reason = f"Trading paused: {self._pause_reason}"
                result.limit_breaches.append("TRADING_PAUSED")
                self._record_review(result)
                return result
            
            # Check tradable universe
            if not self.universe.is_symbol_allowed(plan.symbol):
                result.decision = RiskDecision.REJECT
                result.reason = f"Symbol {plan.symbol} not in tradable universe"
                result.limit_breaches.append("SYMBOL_NOT_ALLOWED")
                self._record_review(result)
                return result
            
            if not self.universe.is_venue_allowed(plan.venue):
                result.decision = RiskDecision.REJECT
                result.reason = f"Venue {plan.venue} not in allowed venues"
                result.limit_breaches.append("VENUE_NOT_ALLOWED")
                self._record_review(result)
                return result
            
            # Check confidence
            if plan.confidence < self.limits.min_confidence_for_trade:
                result.decision = RiskDecision.REJECT
                result.reason = f"Confidence {plan.confidence:.2f} below minimum {self.limits.min_confidence_for_trade}"
                result.limit_breaches.append("LOW_CONFIDENCE")
                self._record_review(result)
                return result
            
            # Check time between trades
            time_since_last = time.time() - self.portfolio.last_trade_time
            if time_since_last < self.limits.min_time_between_trades_seconds:
                result.decision = RiskDecision.REJECT
                result.reason = f"Too soon since last trade ({time_since_last:.0f}s < {self.limits.min_time_between_trades_seconds}s)"
                result.limit_breaches.append("TRADE_RATE_LIMIT")
                self._record_review(result)
                return result
            
            # Check hourly trade count
            if len(self._hourly_trades) >= self.limits.max_trades_per_hour:
                result.decision = RiskDecision.REJECT
                result.reason = f"Hourly trade limit reached ({len(self._hourly_trades)}/{self.limits.max_trades_per_hour})"
                result.limit_breaches.append("HOURLY_TRADE_LIMIT")
                self._record_review(result)
                return result
            
            # Sync P&L from fills_ledger before daily loss check
            self._sync_pnl_from_ledger()
            
            # Check daily loss limit
            if self.portfolio.daily_pnl_usd <= -self.limits.max_daily_loss_usd:
                result.decision = RiskDecision.VETO
                result.reason = f"Daily loss limit reached (${abs(self.portfolio.daily_pnl_usd):.2f})"
                result.limit_breaches.append("DAILY_LOSS_LIMIT")
                self._record_review(result)
                return result
            
            # Check drawdown
            if self.portfolio.current_drawdown_pct >= self.limits.max_drawdown_pct:
                result.decision = RiskDecision.VETO
                result.reason = f"Max drawdown reached ({self.portfolio.current_drawdown_pct:.1f}%)"
                result.limit_breaches.append("MAX_DRAWDOWN")
                self._record_review(result)
                return result
            
            # Calculate approved size
            approved_size = plan.target_size_usd
            
            # Check single trade limit
            if approved_size > self.limits.max_single_trade_usd:
                approved_size = self.limits.max_single_trade_usd
                result.warnings.append(f"Reduced to max single trade limit: ${self.limits.max_single_trade_usd}")
            
            # Check position limit
            current_position = self.portfolio.get_position_size(plan.symbol)
            symbol_limit = self.universe.get_symbol_limit(
                plan.symbol, 
                self.limits.max_position_usd_per_symbol
            )
            
            if abs(current_position + approved_size) > symbol_limit:
                max_allowed = symbol_limit - abs(current_position)
                if max_allowed <= 0:
                    result.decision = RiskDecision.REJECT
                    result.reason = f"Position limit reached for {plan.symbol}"
                    result.limit_breaches.append("POSITION_LIMIT")
                    self._record_review(result)
                    return result
                
                approved_size = min(approved_size, max_allowed)
                result.warnings.append(f"Reduced due to position limit: ${approved_size:.2f}")
            
            # Check total exposure limit
            new_total = self.portfolio.total_exposure_usd + approved_size
            if new_total > self.limits.max_total_exposure_usd:
                max_allowed = self.limits.max_total_exposure_usd - self.portfolio.total_exposure_usd
                if max_allowed <= 0:
                    result.decision = RiskDecision.REJECT
                    result.reason = "Total exposure limit reached"
                    result.limit_breaches.append("EXPOSURE_LIMIT")
                    self._record_review(result)
                    return result
                
                approved_size = min(approved_size, max_allowed)
                result.warnings.append(f"Reduced due to exposure limit: ${approved_size:.2f}")
            
            # Check concentration
            new_concentration = (abs(current_position) + approved_size) / max(1, self.portfolio.total_exposure_usd + approved_size) * 100
            if new_concentration > self.limits.max_concentration_pct:
                result.warnings.append(f"High concentration warning: {new_concentration:.1f}%")
            
            # Determine final decision
            if approved_size <= 0:
                result.decision = RiskDecision.REJECT
                result.reason = "No size available within limits"
            elif approved_size < plan.target_size_usd:
                result.decision = RiskDecision.APPROVE_REDUCED
                result.approved_size_usd = approved_size
                result.reason = f"Approved with reduction: ${approved_size:.2f} (was ${plan.target_size_usd:.2f})"
            else:
                result.decision = RiskDecision.APPROVE
                result.approved_size_usd = approved_size
                result.reason = "Approved within all limits"
            
            self._record_review(result)
            return result
    
    def _record_review(self, result: RiskReviewResult) -> None:
        """Record review to history."""
        self._review_history.append(result)
        
        # Log based on decision
        if result.decision in [RiskDecision.REJECT, RiskDecision.VETO]:
            logger.warning(f"Risk review {result.decision.value}: {result.reason}")
        else:
            logger.info(f"Risk review {result.decision.value}: {result.reason}")
    
    # ============================================
    # STATUS & METRICS
    # ============================================
    
    def get_status(self) -> Dict[str, Any]:
        """Get current risk guard status."""
        # Sync P&L from fills_ledger before returning status
        self._sync_pnl_from_ledger()
        return {
            "kill_switch_active": self._kill_switch_active,
            "kill_switch_reason": self._kill_switch_reason,
            "paused": self._paused,
            "pause_reason": self._pause_reason,
            "limits": self.limits.to_dict(),
            "portfolio": {
                "total_exposure_usd": self.portfolio.total_exposure_usd,
                "daily_pnl_usd": self.portfolio.daily_pnl_usd,
                "daily_trades": self.portfolio.daily_trades,
                "current_drawdown_pct": self.portfolio.current_drawdown_pct,
            },
            "hourly_trades": len(self._hourly_trades),
            "review_count": len(self._review_history),
        }
    
    def get_recent_reviews(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent risk reviews."""
        return [r.to_dict() for r in self._review_history[-limit:]]


def get_risk_guard() -> RiskGuard:
    """Get the global risk guard instance."""
    return RiskGuard.get_instance()


# ============================================
# CONVENIENCE FUNCTIONS
# ============================================

async def review_trade_plan(
    plan_id: str,
    symbol: str,
    venue: str,
    direction: str,
    target_size_usd: float,
    confidence: float,
    agent_id: str,
) -> Tuple[bool, float, str]:
    """
    Convenience function to review a trade plan.
    
    Returns:
        Tuple of (is_approved, approved_size_usd, reason)
    """
    guard = get_risk_guard()
    
    plan = TradePlanInput(
        plan_id=plan_id,
        symbol=symbol,
        venue=venue,
        direction=direction,
        target_size_usd=target_size_usd,
        confidence=confidence,
        agent_id=agent_id,
    )
    
    result = await guard.review_plan(plan)
    
    is_approved = result.decision in [RiskDecision.APPROVE, RiskDecision.APPROVE_REDUCED]
    return is_approved, result.approved_size_usd, result.reason

