"""Canonical Block Reasons — single source of truth for order rejection.

This module defines the ONLY allowed reasons an order can be blocked in MERID.
Any block not using one of these reasons is considered a bug or legacy code.

Block Categories:
1. RISK_LIMITS — Hard risk controls (bankroll, exposure, drawdown)
2. STRATEGY_FILTERS — Signal quality and strategy logic
3. VENUE_CONSTRAINTS — Market/venue-specific rules
4. SYSTEM_STATE — Global system state (kill switches, mode gates)
5. DATA_INTEGRITY — Missing or invalid data (should not happen in production)

Usage:
    from merid.guards.block_reasons import BlockReason, log_block_event
    
    if not risk_check_passes:
        log_block_event(
            order_id=order_id,
            stage="risk_gate",
            reason=BlockReason.BANKROLL_CAP,
            details={"current_bankroll": 1000, "required": 1500}
        )
        return None
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional

from utils.logger import get_logger

logger = get_logger("merid.guards.block_reasons")


class BlockReason(str, Enum):
    """Canonical reasons for order blocking.
    
    These are the ONLY legitimate reasons an order can be rejected.
    Any other reason is a bug or legacy code that needs refactoring.
    
    Categories:
    - RISK_LIMITS: Hard risk controls
    - STRATEGY_FILTERS: Signal quality checks
    - VENUE_CONSTRAINTS: Market/venue rules
    - SYSTEM_STATE: Global system state
    - DATA_INTEGRITY: Data validation failures
    """
    
    # ── RISK_LIMITS ───────────────────────────────────────────────────────
    BANKROLL_CAP = "bankroll_cap"  # Insufficient bankroll for trade size
    DAILY_LOSS_LIMIT = "daily_loss_limit"  # Daily loss limit reached
    POSITION_LIMIT = "position_limit"  # Max position size exceeded
    ASSET_EXPOSURE_CAP = "asset_exposure_cap"  # Per-asset exposure limit
    CATEGORY_EXPOSURE_CAP = "category_exposure_cap"  # Per-category exposure limit
    VENUE_EXPOSURE_CAP = "venue_exposure_cap"  # Per-venue exposure limit
    DOMAIN_DAILY_CAP = "domain_daily_cap"  # Per-domain daily notional cap
    DRAWDOWN_GUARD = "drawdown_guard"  # Drawdown threshold triggered
    
    # ── STRATEGY_FILTERS ───────────────────────────────────────────────────
    MIN_EDGE_THRESHOLD = "min_edge_threshold"  # Edge below minimum threshold
    MIN_CONFIDENCE_THRESHOLD = "min_confidence_threshold"  # Confidence too low
    MARKET_REGIME_GATE = "market_regime_gate"  # Market regime not allowed
    # SENTIMENT_NOTIONAL_CAP removed (2026-05-14): Sentiment should not gate trading
    CQI_THROTTLE = "cqi_throttle"  # CQI-based quality throttle
    PROMOTION_INELIGIBLE = "promotion_ineligible"  # Agent not promoted for live trading
    
    # ── VENUE_CONSTRAINTS ───────────────────────────────────────────────────
    MARKET_CLOSED = "market_closed"  # Market not open for trading
    INVALID_TICKER = "invalid_ticker"  # Ticker not recognized or invalid
    MAX_ORDER_SIZE = "max_order_size"  # Order exceeds venue max size
    PRICE_BAND_VIOLATION = "price_band_violation"  # Price outside allowed band
    DEEP_OTM_REJECT = "deep_otm_reject"  # Too far out-of-the-money
    DEEP_ITM_REJECT = "deep_itm_reject"  # Too far in-the-money
    MODEL_PROB_DISTANCE = "model_prob_distance"  # Model probability too far from market
    SETTLEMENT_GUARD = "settlement_guard"  # Too close to settlement
    EXPIRY_TOO_CLOSE = "expiry_too_close"  # Market expires too soon
    
    # ── SYSTEM_STATE ───────────────────────────────────────────────────────
    KILL_SWITCH = "kill_switch"  # Global kill switch engaged
    TRADING_MODE_GATE = "trading_mode_gate"  # Mode not allowed (SIM/PAPER/LIVE)
    EXECUTION_GATE_BLOCKED = "execution_gate_blocked"  # Execution gate in BLOCKED state
    EXECUTION_GATE_LIMITED = "execution_gate_limited"  # Execution gate in LIMITED state
    RECONCILIATION_BLOCKED = "reconciliation_blocked"  # Venue reconciliation critical
    LOOP_LAG_HALT = "loop_lag_halt"  # Event loop latency critical
    DEPENDENCY_HEALTH = "dependency_health"  # Critical dependency down
    
    # ── DATA_INTEGRITY ───────────────────────────────────────────────────────
    MISSING_PRICE = "missing_price"  # No price available
    STALE_PRICE = "stale_price"  # Price data too old
    MISSING_MARKET_DATA = "missing_market_data"  # Market data unavailable
    INVALID_ORDER_PARAMS = "invalid_order_params"  # Order parameters invalid
    SNAPSHOT_STALE = "snapshot_stale"  # Market snapshot too old
    DATA_VERSION_MISMATCH = "data_version_mismatch"  # Schema version mismatch
    
    # ── INTERNAL_ERROR (should not happen in production) ───────────────────
    INTERNAL_ERROR = "internal_error"  # Unexpected internal error
    INFRASTRUCTURE_UNAVAILABLE = "infrastructure_unavailable"  # Required service down


# ── Stage Enum ───────────────────────────────────────────────────────────

class OrderStage(str, Enum):
    """Stages in the order lifecycle where blocking can occur."""
    
    SIGNAL_GENERATION = "signal_generation"  # Agent generates signal
    SIGNAL_TO_INTENT = "signal_to_intent"  # Signal converted to OrderIntent
    STRATEGY_FILTER = "strategy_filter"  # Strategy-level validation
    RISK_GATE = "risk_gate"  # Risk limit checks
    EXECUTION_GATE = "execution_gate"  # System-level gate (kill switch, etc.)
    PRE_TRADE_GATE = "pre_trade_gate"  # Final pre-trade dedup/lease checks
    ROUTER_VALIDATION = "router_validation"  # Order router sanity checks
    VENUE_SUBMISSION = "venue_submission"  # Venue rejects order


# ── Block Event Record ────────────────────────────────────────────────────

@dataclass
class BlockEvent:
    """Structured record of a blocked order attempt."""
    
    order_id: str
    stage: OrderStage
    reason: BlockReason
    blocked: bool = True
    timestamp: float = field(default_factory=lambda: datetime.now(timezone.utc).timestamp())
    
    # Context fields
    asset: str = ""
    timeframe: str = ""
    side: str = ""
    action: str = ""
    edge_pct: Optional[float] = None
    confidence: Optional[float] = None
    
    # Additional details
    details: Dict[str, Any] = field(default_factory=dict)
    
    # Caller info
    caller_module: str = ""
    agent_id: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize for logging/metrics."""
        return {
            "order_id": self.order_id,
            "stage": self.stage.value,
            "reason": self.reason.value,
            "blocked": self.blocked,
            "timestamp": self.timestamp,
            "asset": self.asset,
            "timeframe": self.timeframe,
            "side": self.side,
            "action": self.action,
            "edge_pct": self.edge_pct,
            "confidence": self.confidence,
            "details": self.details,
            "caller_module": self.caller_module,
            "agent_id": self.agent_id,
        }


# ── Logging Function ─────────────────────────────────────────────────────

def log_block_event(
    order_id: str,
    stage: OrderStage,
    reason: BlockReason,
    asset: str = "",
    timeframe: str = "",
    side: str = "",
    action: str = "",
    edge_pct: Optional[float] = None,
    confidence: Optional[float] = None,
    details: Optional[Dict[str, Any]] = None,
    caller_module: str = "",
    agent_id: str = "",
) -> BlockEvent:
    """Log a structured block event.
    
    This is the canonical way to record order blocks. All block points
    in the codebase should call this function with appropriate parameters.
    
    Args:
        order_id: Unique order identifier
        stage: Where in the lifecycle the block occurred
        reason: Canonical block reason from BlockReason enum
        asset: Asset symbol (e.g., "BTC")
        timeframe: Timeframe (e.g., "15m")
        side: Order side ("yes"/"no" or "buy"/"sell")
        action: Order action ("buy"/"sell")
        edge_pct: Edge percentage if available
        confidence: Model confidence if available
        details: Additional context (dict)
        caller_module: Module that triggered the block
        agent_id: Agent identifier if applicable
    
    Returns:
        BlockEvent record for further processing
    """
    event = BlockEvent(
        order_id=order_id,
        stage=stage,
        reason=reason,
        asset=asset,
        timeframe=timeframe,
        side=side,
        action=action,
        edge_pct=edge_pct,
        confidence=confidence,
        details=details or {},
        caller_module=caller_module,
        agent_id=agent_id,
    )
    
    # Log with structured format
    logger.info(
        "ORDER_BLOCKED",
        extra={
            "order_id": order_id,
            "stage": stage.value,
            "reason": reason.value,
            "asset": asset,
            "timeframe": timeframe,
            "side": side,
            "action": action,
            "edge_pct": edge_pct,
            "confidence": confidence,
            "details": details or {},
            "caller_module": caller_module,
            "agent_id": agent_id,
        }
    )
    
    # Emit Prometheus metric if available
    try:
        from merid.resilience.metrics import inc_counter
        inc_counter("merid_orders_blocked_total", labels={
            "stage": stage.value,
            "reason": reason.value,
            "asset": asset or "unknown",
        })
    except (ImportError, AttributeError):
        # Metrics not available or inc_counter not found - silently skip
        try:
            # Fallback: try prometheus_client directly
            from prometheus_client import Counter
            if "merid_orders_blocked_total" not in globals():
                globals()["merid_orders_blocked_total"] = Counter(
                    "merid_orders_blocked_total",
                    "Total blocked orders by stage, reason, and asset",
                    ["stage", "reason", "asset"]
                )
            globals()["merid_orders_blocked_total"].labels(
                stage=stage.value,
                reason=reason.value,
                asset=asset or "unknown"
            ).inc()
        except ImportError:
            # Prometheus not available at all - silently skip
            pass
    
    return event


# ── Validation Helpers ───────────────────────────────────────────────────

def is_canonical_block_reason(reason: str) -> bool:
    """Check if a reason string is in the canonical BlockReason enum."""
    try:
        BlockReason(reason)
        return True
    except ValueError:
        return False


def get_block_reason_category(reason: BlockReason) -> str:
    """Get the category for a block reason."""
    reason_str = reason.value
    
    if reason_str.startswith(("bankroll", "daily_loss", "position", "exposure", "drawdown")):
        return "RISK_LIMITS"
    elif reason_str.startswith(("min_edge", "min_confidence", "market_regime", "sentiment", "cqi", "promotion")):
        return "STRATEGY_FILTERS"
    elif reason_str.startswith(("market_closed", "invalid_ticker", "max_order", "price_band", "deep_", "settlement", "expiry")):
        return "VENUE_CONSTRAINTS"
    elif reason_str.startswith(("kill_switch", "trading_mode", "execution_gate", "reconciliation", "loop_lag", "dependency")):
        return "SYSTEM_STATE"
    elif reason_str.startswith(("missing_", "stale_", "invalid_", "snapshot_", "data_")):
        return "DATA_INTEGRITY"
    elif reason_str in ("internal_error", "infrastructure_unavailable"):
        return "INTERNAL_ERROR"
    else:
        return "UNKNOWN"


# ── Module-level constants for validation ───────────────────────────────────

# All canonical reasons for validation
CANONICAL_BLOCK_REASONS = {r.value for r in BlockReason}

# All canonical stages
CANONICAL_STAGES = {s.value for s in OrderStage}

# Expected stages for each category (for audit)
STAGE_CATEGORY_MAPPING = {
    "RISK_LIMITS": {"risk_gate", "execution_gate"},
    "STRATEGY_FILTERS": {"strategy_filter", "signal_generation"},
    "VENUE_CONSTRAINTS": {"router_validation", "venue_submission"},
    "SYSTEM_STATE": {"execution_gate", "pre_trade_gate"},
    "DATA_INTEGRITY": {"signal_generation", "signal_to_intent", "router_validation"},
}
