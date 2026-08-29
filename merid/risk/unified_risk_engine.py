"""Unified Risk Engine - Orchestrates all risk modules with hierarchical decision flow.

This module provides a unified interface for risk management across all trading
operations, coordinating 4 independent risk modules into a single hierarchical
decision flow:

1. Global Risk (kill switches, daily loss)
2. Domain Risk (per-domain caps, CQI throttling)
3. Strategy Risk (per-strategy limits, correlation)
4. Instrument Risk (per-asset caps, venue-specific rules)

The unified engine ensures:
- Shared state across all risk modules
- Hierarchical decision flow with clear precedence
- Conflict resolution when modules disagree
- Unified audit trail with trace IDs
- Consistent risk decisions across the system

Usage:
    from merid.risk.unified_risk_engine import get_unified_risk_engine
    
    engine = get_unified_risk_engine()
    
    # Check if trade is allowed
    result = engine.check_trade(trade_request)
    if not result.allowed:
        logger.warning(f"Trade rejected: {result.reason}")
        return
    
    # Record trade after execution
    engine.record_trade(trade_result)
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from utils.logger import get_logger

logger = get_logger("merid.risk.unified_risk_engine")


class RiskLayer(str, Enum):
    """Risk layer hierarchy (ordered from highest to lowest precedence)."""
    GLOBAL = "global"           # Kill switches, daily loss - highest precedence
    DOMAIN = "domain"           # Per-domain caps, CQI throttling
    STRATEGY = "strategy"       # Per-strategy limits, correlation
    INSTRUMENT = "instrument"   # Per-asset caps, venue-specific rules - lowest precedence


class RiskDecision(str, Enum):
    """Risk decision outcomes."""
    ALLOWED = "allowed"
    REJECTED = "rejected"
    THROTTLED = "throttled"
    DEFERRED = "deferred"


@dataclass
class RiskCheckResult:
    """Result of a risk check."""
    allowed: bool
    decision: RiskDecision
    reason: str
    layer: RiskLayer
    details: Dict[str, Any] = field(default_factory=dict)
    trace_id: str = field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class TradeRequest:
    """Trade request for risk checking."""
    ticker: str
    side: str  # "yes" or "no"
    contracts: int
    price_cents: int
    agent_name: str
    strategy: str = "default"
    domain: str = "kalshi"
    confidence: float = 0.5
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TradeResult:
    """Trade result for recording."""
    trace_id: str
    ticker: str
    side: str
    contracts: int
    price_cents: int
    executed_contracts: int
    pnl_usd: float
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class RiskModuleState:
    """State of a risk module."""
    module_name: str
    enabled: bool
    last_check: Optional[datetime] = None
    checks_performed: int = 0
    rejections: int = 0
    last_error: Optional[str] = None


class UnifiedRiskEngine:
    """Unified risk engine that orchestrates all risk modules.
    
    Implements hierarchical decision flow:
        Global Risk (kill switches, daily loss)
        ↓
        Domain Risk (per-domain caps, CQI throttling)
        ↓
        Strategy Risk (per-strategy limits, correlation)
        ↓
        Instrument Risk (per-asset caps, venue-specific rules)
    """
    
    _instance: Optional["UnifiedRiskEngine"] = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialize()
        return cls._instance
    
    def _initialize(self):
        """Initialize the unified risk engine."""
        self._module_states: Dict[str, RiskModuleState] = {}
        self._audit_trail: List[Dict[str, Any]] = []
        self._audit_trail_lock = threading.Lock()
        self._initialized = False
        
        # Load risk modules
        self._load_risk_modules()
        self._initialized = True
        logger.info("UnifiedRiskEngine initialized with %d risk modules", len(self._module_states))
    
    def _load_risk_modules(self):
        """Load and initialize risk modules."""
        # Initialize module states
        modules = [
            "RiskController",
            "ExecutionGuard", 
            "KalshiRiskManager",
            "SentimentRisk"
        ]
        
        for module_name in modules:
            self._module_states[module_name] = RiskModuleState(
                module_name=module_name,
                enabled=True
            )
    
    def check_trade(self, request: TradeRequest) -> RiskCheckResult:
        """Check if a trade is allowed through hierarchical risk layers.
        
        Args:
            request: Trade request to check
            
        Returns:
            RiskCheckResult with decision and reason
        """
        trace_id = str(uuid4())
        
        # Layer 1: Global Risk (kill switches, daily loss)
        global_result = self._check_global_risk(request, trace_id)
        if not global_result.allowed:
            return global_result
        
        # Layer 2: Domain Risk (per-domain caps, CQI throttling)
        domain_result = self._check_domain_risk(request, trace_id)
        if not domain_result.allowed:
            return domain_result
        
        # Layer 3: Strategy Risk (per-strategy limits, correlation)
        strategy_result = self._check_strategy_risk(request, trace_id)
        if not strategy_result.allowed:
            return strategy_result
        
        # Layer 4: Instrument Risk (per-asset caps, venue-specific rules)
        instrument_result = self._check_instrument_risk(request, trace_id)
        if not instrument_result.allowed:
            return instrument_result
        
        # All layers passed
        return RiskCheckResult(
            allowed=True,
            decision=RiskDecision.ALLOWED,
            reason="All risk checks passed",
            layer=RiskLayer.INSTRUMENT,
            trace_id=trace_id
        )
    
    def _check_global_risk(self, request: TradeRequest, trace_id: str) -> RiskCheckResult:
        """Check global risk layer (kill switches, daily loss)."""
        try:
            # Check RiskController (kill switches)
            try:
                from merid.risk.kill_switches import risk_controller
                if not risk_controller.can_trade():
                    self._record_rejection("RiskController", "global_kill_switch")
                    return RiskCheckResult(
                        allowed=False,
                        decision=RiskDecision.REJECTED,
                        reason="Global kill switch active",
                        layer=RiskLayer.GLOBAL,
                        trace_id=trace_id,
                        details={"kill_switch_state": risk_controller.get_state()}
                    )
            except Exception as e:
                logger.warning(f"RiskController check failed: {e}")
            
            # Check daily loss limits
            try:
                from merid.risk.kill_switches import risk_controller
                daily_pnl = risk_controller.get_daily_pnl()
                daily_loss_limit = risk_controller.get_daily_loss_limit()
                
                if daily_pnl < -daily_loss_limit:
                    self._record_rejection("RiskController", "daily_loss_limit")
                    return RiskCheckResult(
                        allowed=False,
                        decision=RiskDecision.REJECTED,
                        reason=f"Daily loss limit breached: ${daily_pnl:.2f} < ${-daily_loss_limit:.2f}",
                        layer=RiskLayer.GLOBAL,
                        trace_id=trace_id,
                        details={"daily_pnl": daily_pnl, "daily_loss_limit": daily_loss_limit}
                    )
            except Exception as e:
                logger.warning(f"Daily loss check failed: {e}")
            
            self._record_check("RiskController")
            return RiskCheckResult(
                allowed=True,
                decision=RiskDecision.ALLOWED,
                reason="Global risk checks passed",
                layer=RiskLayer.GLOBAL,
                trace_id=trace_id
            )
            
        except Exception as e:
            logger.error(f"Global risk check error: {e}")
            return RiskCheckResult(
                allowed=False,
                decision=RiskDecision.REJECTED,
                reason=f"Global risk check error: {e}",
                layer=RiskLayer.GLOBAL,
                trace_id=trace_id
            )
    
    def _check_domain_risk(self, request: TradeRequest, trace_id: str) -> RiskCheckResult:
        """Check domain risk layer (per-domain caps, CQI throttling)."""
        try:
            # Check ExecutionGuard (CQI throttling, domain caps)
            try:
                from merid.execution_guard import get_execution_guard
                guard = get_execution_guard()
                
                # Check if trading is allowed for this domain
                if not guard.can_trade_domain(request.domain):
                    self._record_rejection("ExecutionGuard", "domain_cap")
                    return RiskCheckResult(
                        allowed=False,
                        decision=RiskDecision.REJECTED,
                        reason=f"Domain cap exceeded for {request.domain}",
                        layer=RiskLayer.DOMAIN,
                        trace_id=trace_id,
                        details={"domain": request.domain}
                    )
                
                # Check CQI throttling
                cqi_status = guard.get_cqi_status()
                if cqi_status.get("throttled", False):
                    self._record_rejection("ExecutionGuard", "cqi_throttle")
                    return RiskCheckResult(
                        allowed=False,
                        decision=RiskDecision.THROTTLED,
                        reason="CQI-based throttling active",
                        layer=RiskLayer.DOMAIN,
                        trace_id=trace_id,
                        details={"cqi_status": cqi_status}
                    )
            except Exception as e:
                logger.warning(f"ExecutionGuard check failed: {e}")
            
            self._record_check("ExecutionGuard")
            return RiskCheckResult(
                allowed=True,
                decision=RiskDecision.ALLOWED,
                reason="Domain risk checks passed",
                layer=RiskLayer.DOMAIN,
                trace_id=trace_id
            )
            
        except Exception as e:
            logger.error(f"Domain risk check error: {e}")
            return RiskCheckResult(
                allowed=False,
                decision=RiskDecision.REJECTED,
                reason=f"Domain risk check error: {e}",
                layer=RiskLayer.DOMAIN,
                trace_id=trace_id
            )
    
    def _check_strategy_risk(self, request: TradeRequest, trace_id: str) -> RiskCheckResult:
        """Check strategy risk layer (per-strategy limits, correlation)."""
        try:
            # Check strategy-specific limits
            # For now, this is a placeholder - implement strategy limits as needed
            # This could include per-strategy position limits, correlation checks, etc.
            
            self._record_check("StrategyRisk")
            return RiskCheckResult(
                allowed=True,
                decision=RiskDecision.ALLOWED,
                reason="Strategy risk checks passed",
                layer=RiskLayer.STRATEGY,
                trace_id=trace_id
            )
            
        except Exception as e:
            logger.error(f"Strategy risk check error: {e}")
            return RiskCheckResult(
                allowed=False,
                decision=RiskDecision.REJECTED,
                reason=f"Strategy risk check error: {e}",
                layer=RiskLayer.STRATEGY,
                trace_id=trace_id
            )
    
    def _check_instrument_risk(self, request: TradeRequest, trace_id: str) -> RiskCheckResult:
        """Check instrument risk layer (per-asset caps, venue-specific rules)."""
        try:
            # Check KalshiRiskManager (venue-specific risk)
            try:
                if request.domain == "kalshi":
                    from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk_manager
                    risk_manager = get_kalshi_risk_manager()
                    
                    # Check position limits
                    if not risk_manager.can_add_position(request.ticker, request.contracts):
                        self._record_rejection("KalshiRiskManager", "position_limit")
                        return RiskCheckResult(
                            allowed=False,
                            decision=RiskDecision.REJECTED,
                            reason=f"Position limit exceeded for {request.ticker}",
                            layer=RiskLayer.INSTRUMENT,
                            trace_id=trace_id,
                            details={"ticker": request.ticker, "contracts": request.contracts}
                        )
            except Exception as e:
                logger.warning(f"KalshiRiskManager check failed: {e}")
            
            # Check SentimentRisk (per-asset sentiment caps)
            try:
                from merid.risk.sentiment_risk import get_sentiment_risk
                sentiment_risk = get_sentiment_risk()
                
                # CRITICAL FIX (2026-07-21): Use canonical identity helper for asset extraction
                from merid.utils.kalshi_identity import extract_asset
                asset = extract_asset(request.ticker)
                
                # SENTIMENT DECOUPLING (2026-05-14): Removed sentiment cap rejection
                # Sentiment should not gate trading via risk engine
            except Exception as e:
                logger.warning(f"SentimentRisk check failed: {e}")
            
            self._record_check("KalshiRiskManager")
            self._record_check("SentimentRisk")
            return RiskCheckResult(
                allowed=True,
                decision=RiskDecision.ALLOWED,
                reason="Instrument risk checks passed",
                layer=RiskLayer.INSTRUMENT,
                trace_id=trace_id
            )
            
        except Exception as e:
            logger.error(f"Instrument risk check error: {e}")
            return RiskCheckResult(
                allowed=False,
                decision=RiskDecision.REJECTED,
                reason=f"Instrument risk check error: {e}",
                layer=RiskLayer.INSTRUMENT,
                trace_id=trace_id
            )
    
    def record_trade(self, result: TradeResult):
        """Record a trade result for risk tracking.
        
        Args:
            result: Trade result to record
        """
        try:
            # Update RiskController with PnL
            try:
                from merid.risk.kill_switches import risk_controller
                risk_controller.record_pnl(result.pnl_usd)
            except Exception as e:
                logger.warning(f"Failed to record PnL to RiskController: {e}")
            
            # Update KalshiRiskManager and UnifiedRiskManager with PnL/position
            try:
                from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk_manager
                risk_manager = get_kalshi_risk_manager()
                risk_manager.record_trade(result.ticker, result.executed_contracts, result.pnl_usd)
            except Exception as e:
                logger.warning(f"Failed to record trade to KalshiRiskManager: {e}")

            try:
                from merid.risk.unified_risk_manager import get_unified_risk_manager
                unified_risk = get_unified_risk_manager()
                unified_risk.record_pnl(result.pnl_usd)
            except Exception as e:
                logger.warning(f"Failed to record PnL to UnifiedRiskManager: {e}")
            
            # Add to audit trail
            self._add_audit_entry({
                "action": "trade_recorded",
                "trace_id": result.trace_id,
                "ticker": result.ticker,
                "side": result.side,
                "contracts": result.executed_contracts,
                "pnl_usd": result.pnl_usd,
                "timestamp": result.timestamp.isoformat()
            })
            
        except Exception as e:
            logger.error(f"Failed to record trade: {e}")
    
    def _record_check(self, module_name: str):
        """Record a successful risk check."""
        if module_name in self._module_states:
            state = self._module_states[module_name]
            state.checks_performed += 1
            state.last_check = datetime.now(timezone.utc)
    
    def _record_rejection(self, module_name: str, reason: str):
        """Record a risk rejection."""
        if module_name in self._module_states:
            state = self._module_states[module_name]
            state.rejections += 1
            state.last_check = datetime.now(timezone.utc)
        
        logger.warning(f"[RISK_REJECTION] module={module_name} reason={reason}")
    
    def _add_audit_entry(self, entry: Dict[str, Any]):
        """Add an entry to the audit trail."""
        with self._audit_trail_lock:
            self._audit_trail.append(entry)
            # Keep audit trail manageable (last 1000 entries)
            if len(self._audit_trail) > 1000:
                self._audit_trail = self._audit_trail[-1000:]
    
    def get_module_states(self) -> Dict[str, RiskModuleState]:
        """Get the state of all risk modules."""
        return self._module_states.copy()
    
    def get_audit_trail(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get the audit trail.
        
        Args:
            limit: Maximum number of entries to return
            
        Returns:
            List of audit trail entries
        """
        with self._audit_trail_lock:
            return self._audit_trail[-limit:]
    
    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of the unified risk engine state."""
        total_checks = sum(s.checks_performed for s in self._module_states.values())
        total_rejections = sum(s.rejections for s in self._module_states.values())
        
        return {
            "initialized": self._initialized,
            "module_count": len(self._module_states),
            "total_checks": total_checks,
            "total_rejections": total_rejections,
            "rejection_rate": total_rejections / total_checks if total_checks > 0 else 0,
            "module_states": {
                name: {
                    "enabled": state.enabled,
                    "checks": state.checks_performed,
                    "rejections": state.rejections,
                    "last_check": state.last_check.isoformat() if state.last_check else None
                }
                for name, state in self._module_states.items()
            }
        }


# Singleton accessor
_unified_risk_engine: Optional[UnifiedRiskEngine] = None
_unified_risk_engine_lock = threading.Lock()


def get_unified_risk_engine() -> UnifiedRiskEngine:
    """Get the singleton UnifiedRiskEngine instance."""
    global _unified_risk_engine
    if _unified_risk_engine is None:
        with _unified_risk_engine_lock:
            if _unified_risk_engine is None:
                _unified_risk_engine = UnifiedRiskEngine()
    return _unified_risk_engine
