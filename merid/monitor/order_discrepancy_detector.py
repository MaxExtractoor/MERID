"""
Order Discrepancy Detector — Live monitoring for intent-to-exposure mismatches.

This module provides production monitoring to detect when orders execute
with different exposure than intended (e.g., "buy NO" intent executing as "buy YES").

CRITICAL FIX (2026-07-19): Prevents silent intent-to-exposure mapping bugs by
continuously validating venue echoes against original intent contracts.

Usage::

    from merid.monitor.order_discrepancy_detector import (
        OrderDiscrepancyDetector, get_discrepancy_detector,
        DiscrepancyEvent, DiscrepancySeverity
    )
    
    detector = get_discrepancy_detector()
    
    # Record intent when order is submitted
    detector.record_intent(
        client_order_id="order_123",
        strategy_intent="bullish_event",
        expected_leg="yes",
        entry_or_exit="entry",
        asset="BTC",
        ticker="KXBTCD-25JUL-T100000",
    )
    
    # Validate fill when venue echoes back
    discrepancy = detector.validate_fill(
        client_order_id="order_123",
        fill_side="yes",
        fill_action="buy",
        fill_quantity=1,
    )
    
    if discrepancy:
        # Alert on discrepancy
        logger.error(f"ORDER_MISMATCH: {discrepancy.to_dict()}")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
import threading
import time

from utils.logger import get_logger

logger = get_logger("merid.monitor.order_discrepancy_detector")


class DiscrepancySeverity(str, Enum):
    """Severity level of order discrepancy."""
    CRITICAL = "critical"  # Wrong leg executed (e.g., buy NO → buy YES) OR co-occurring exposure + liquidity mismatch
    HIGH = "high"  # Wrong direction (e.g., entry → exit) OR liquidity role mismatch
    MEDIUM = "medium"  # Wrong quantity OR fee mismatch
    LOW = "low"  # Minor metadata mismatch


@dataclass
class DiscrepancyEvent:
    """Record of an order discrepancy event."""
    
    # Identification
    client_order_id: str
    timestamp: float = field(default_factory=lambda: datetime.now(timezone.utc).timestamp())
    severity: DiscrepancySeverity = DiscrepancySeverity.CRITICAL
    discrepancy_type: str = "EXPOSURE_MISMATCH"  # EXPOSURE_MISMATCH, LIQUIDITY_ROLE_MISMATCH, FEE_MISMATCH
    
    # Intent context
    strategy_intent: str = ""
    expected_leg: str = ""  # "yes" or "no"
    entry_or_exit: str = ""  # "entry" or "exit"
    asset: str = ""
    ticker: str = ""
    
    # Liquidity role context (CRITICAL FIX 2026-07-19)
    expected_liquidity_role: str = ""  # "maker", "taker", or "auto"
    realized_liquidity_role: str = ""  # Actual role from execution
    
    # Venue context
    venue_side: str = ""  # Actual side from fill
    venue_action: str = ""  # Actual action from fill
    venue_quantity: int = 0
    
    # Position context
    pre_position: Optional[str] = None
    post_position: Optional[str] = None
    
    # Fee context
    expected_fee_cents: int = 0
    realized_fee_cents: int = 0
    
    # Details
    trade_reason: str = ""
    error_message: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging/alerting."""
        return {
            "client_order_id": self.client_order_id,
            "timestamp": self.timestamp,
            "severity": self.severity.value,
            "discrepancy_type": self.discrepancy_type,
            "strategy_intent": self.strategy_intent,
            "expected_leg": self.expected_leg,
            "entry_or_exit": self.entry_or_exit,
            "asset": self.asset,
            "ticker": self.ticker,
            "expected_liquidity_role": self.expected_liquidity_role,
            "realized_liquidity_role": self.realized_liquidity_role,
            "venue_side": self.venue_side,
            "venue_action": self.venue_action,
            "venue_quantity": self.venue_quantity,
            "pre_position": self.pre_position,
            "post_position": self.post_position,
            "expected_fee_cents": self.expected_fee_cents,
            "realized_fee_cents": self.realized_fee_cents,
            "trade_reason": self.trade_reason,
            "error_message": self.error_message,
        }


@dataclass
class IntentRecord:
    """Record of an original intent for later validation."""
    
    client_order_id: str
    strategy_intent: str
    expected_leg: str
    entry_or_exit: str
    asset: str
    ticker: str
    timestamp: float = field(default_factory=lambda: datetime.now(timezone.utc).timestamp())
    trade_reason: str = ""
    
    # Liquidity role context (CRITICAL FIX 2026-07-19)
    expected_liquidity_role: str = ""  # "maker", "taker", or "auto"
    expected_fee_cents: int = 0
    
    # Optional context
    pre_position: Optional[str] = None
    expected_post_position: Optional[str] = None


class OrderDiscrepancyDetector:
    """Detects order discrepancies by comparing intent to venue echoes.
    
    This detector maintains an in-memory registry of submitted intents
    and validates fill notifications against the expected exposure.
    
    Thread-safe for concurrent access in production.
    """
    
    def __init__(self):
        self._intents: Dict[str, IntentRecord] = {}
        self._lock = threading.RLock()
        self._discrepancies: List[DiscrepancyEvent] = []
        self._max_discrepancy_history = 1000
    
    def record_intent(
        self,
        client_order_id: str,
        strategy_intent: str,
        expected_leg: str,
        entry_or_exit: str,
        asset: str,
        ticker: str,
        trade_reason: str = "",
        pre_position: Optional[str] = None,
        expected_post_position: Optional[str] = None,
        expected_liquidity_role: str = "",
        expected_fee_cents: int = 0,
    ) -> None:
        """Record an intent for later validation.
        
        Args:
            client_order_id: Unique order identifier
            strategy_intent: Strategy intent (bullish_event, bearish_event, neutral)
            expected_leg: Expected exposure leg (yes or no)
            entry_or_exit: Entry or exit classification
            asset: Asset symbol
            ticker: Kalshi market ticker
            trade_reason: Human-readable reason
            pre_position: Position before order (optional)
            expected_post_position: Expected position after order (optional)
            expected_liquidity_role: Expected liquidity role (maker, taker, auto)
            expected_fee_cents: Expected fee in cents
        """
        with self._lock:
            record = IntentRecord(
                client_order_id=client_order_id,
                strategy_intent=strategy_intent,
                expected_leg=expected_leg,
                entry_or_exit=entry_or_exit,
                asset=asset,
                ticker=ticker,
                trade_reason=trade_reason,
                pre_position=pre_position,
                expected_post_position=expected_post_position,
                expected_liquidity_role=expected_liquidity_role,
                expected_fee_cents=expected_fee_cents,
            )
            self._intents[client_order_id] = record
            logger.debug(
                f"[DISCREPANCY-DETECTOR] Recorded intent: {client_order_id} | "
                f"intent={strategy_intent} | expected_leg={expected_leg} | entry_or_exit={entry_or_exit} | "
                f"liquidity_role={expected_liquidity_role}"
            )
    
    def validate_fill(
        self,
        client_order_id: str,
        fill_side: str,
        fill_action: str,
        fill_quantity: int,
        post_position: Optional[str] = None,
        realized_liquidity_role: str = "",
        realized_fee_cents: int = 0,
    ) -> Optional[DiscrepancyEvent]:
        """Validate a fill against the recorded intent.
        
        Args:
            client_order_id: Order identifier
            fill_side: Fill side from venue (yes or no)
            fill_action: Fill action from venue (buy or sell)
            fill_quantity: Number of contracts filled
            post_position: Position after fill (optional)
            realized_liquidity_role: Actual liquidity role from execution (maker/taker)
            realized_fee_cents: Actual fee charged in cents
            
        Returns:
            DiscrepancyEvent if mismatch detected, None if valid
        """
        with self._lock:
            # Retrieve intent record
            intent = self._intents.get(client_order_id)
            if not intent:
                logger.warning(
                    f"[DISCREPANCY-DETECTOR] No intent record for {client_order_id} - cannot validate"
                )
                return None
            
            # Compute actual exposure from fill
            actual_exposure = self._compute_exposure_from_fill(fill_side, fill_action, fill_quantity)
            
            # Compute expected exposure from intent
            expected_exposure = self._compute_expected_exposure(intent)
            
            # Check for exposure mismatch
            exposure_mismatch = actual_exposure != expected_exposure
            
            # Check for liquidity role mismatch (CRITICAL FIX 2026-07-19)
            liquidity_role_mismatch = False
            if intent.expected_liquidity_role and realized_liquidity_role:
                if intent.expected_liquidity_role != realized_liquidity_role:
                    # AUTO role is allowed to resolve to either maker or taker
                    if intent.expected_liquidity_role != "auto":
                        liquidity_role_mismatch = True
            
            # CRITICAL FIX (2026-07-19): Co-occurring exposure + liquidity mismatch is CRITICAL
            if exposure_mismatch and liquidity_role_mismatch:
                discrepancy = DiscrepancyEvent(
                    client_order_id=client_order_id,
                    severity=DiscrepancySeverity.CRITICAL,
                    discrepancy_type="ORDER_CONTRACT_VIOLATION",
                    strategy_intent=intent.strategy_intent,
                    expected_leg=intent.expected_leg,
                    entry_or_exit=intent.entry_or_exit,
                    asset=intent.asset,
                    ticker=intent.ticker,
                    expected_liquidity_role=intent.expected_liquidity_role,
                    realized_liquidity_role=realized_liquidity_role,
                    expected_fee_cents=intent.expected_fee_cents,
                    realized_fee_cents=realized_fee_cents,
                    venue_side=fill_side,
                    venue_action=fill_action,
                    venue_quantity=fill_quantity,
                    pre_position=intent.pre_position,
                    post_position=post_position,
                    trade_reason=intent.trade_reason,
                    error_message=(
                        f"ORDER_CONTRACT_VIOLATION: Both exposure and liquidity role mismatched | "
                        f"exposure: expected {expected_exposure}, got {actual_exposure} | "
                        f"liquidity_role: expected {intent.expected_liquidity_role}, got {realized_liquidity_role}"
                    ),
                )
                
                self._record_discrepancy(discrepancy, intent)
                return discrepancy
            
            # Check for exposure mismatch alone
            if exposure_mismatch:
                discrepancy = DiscrepancyEvent(
                    client_order_id=client_order_id,
                    severity=self._determine_severity(intent, actual_exposure, expected_exposure),
                    discrepancy_type="EXPOSURE_MISMATCH",
                    strategy_intent=intent.strategy_intent,
                    expected_leg=intent.expected_leg,
                    entry_or_exit=intent.entry_or_exit,
                    asset=intent.asset,
                    ticker=intent.ticker,
                    expected_liquidity_role=intent.expected_liquidity_role,
                    realized_liquidity_role=realized_liquidity_role,
                    expected_fee_cents=intent.expected_fee_cents,
                    realized_fee_cents=realized_fee_cents,
                    venue_side=fill_side,
                    venue_action=fill_action,
                    venue_quantity=fill_quantity,
                    pre_position=intent.pre_position,
                    post_position=post_position,
                    trade_reason=intent.trade_reason,
                    error_message=(
                        f"Exposure mismatch: expected {expected_exposure}, "
                        f"got {actual_exposure} (fill_side={fill_side}, fill_action={fill_action})"
                    ),
                )
                
                self._record_discrepancy(discrepancy, intent)
                return discrepancy
            
            # Check for liquidity role mismatch alone
            if liquidity_role_mismatch:
                discrepancy = DiscrepancyEvent(
                    client_order_id=client_order_id,
                    severity=DiscrepancySeverity.HIGH,
                    discrepancy_type="LIQUIDITY_ROLE_MISMATCH",
                    strategy_intent=intent.strategy_intent,
                    expected_leg=intent.expected_leg,
                    entry_or_exit=intent.entry_or_exit,
                    asset=intent.asset,
                    ticker=intent.ticker,
                    expected_liquidity_role=intent.expected_liquidity_role,
                    realized_liquidity_role=realized_liquidity_role,
                    expected_fee_cents=intent.expected_fee_cents,
                    realized_fee_cents=realized_fee_cents,
                    venue_side=fill_side,
                    venue_action=fill_action,
                    venue_quantity=fill_quantity,
                    pre_position=intent.pre_position,
                    post_position=post_position,
                    trade_reason=intent.trade_reason,
                    error_message=(
                        f"Liquidity role mismatch: expected {intent.expected_liquidity_role}, "
                        f"got {realized_liquidity_role}"
                    ),
                )
                
                self._record_discrepancy(discrepancy, intent)
                return discrepancy
            
            # Check for fee mismatch
            if intent.expected_fee_cents and realized_fee_cents:
                fee_diff = abs(realized_fee_cents - intent.expected_fee_cents)
                if fee_diff > 1:  # Allow 1 cent tolerance
                    discrepancy = DiscrepancyEvent(
                        client_order_id=client_order_id,
                        severity=DiscrepancySeverity.MEDIUM,
                        discrepancy_type="FEE_MISMATCH",
                        strategy_intent=intent.strategy_intent,
                        expected_leg=intent.expected_leg,
                        entry_or_exit=intent.entry_or_exit,
                        asset=intent.asset,
                        ticker=intent.ticker,
                        expected_liquidity_role=intent.expected_liquidity_role,
                        realized_liquidity_role=realized_liquidity_role,
                        expected_fee_cents=intent.expected_fee_cents,
                        realized_fee_cents=realized_fee_cents,
                        venue_side=fill_side,
                        venue_action=fill_action,
                        venue_quantity=fill_quantity,
                        pre_position=intent.pre_position,
                        post_position=post_position,
                        trade_reason=intent.trade_reason,
                        error_message=(
                            f"Fee mismatch: expected {intent.expected_fee_cents}c, "
                            f"got {realized_fee_cents}c (diff {fee_diff}c)"
                        ),
                    )
                    
                    self._record_discrepancy(discrepancy, intent)
                    return discrepancy
            
            # Valid fill - clean up intent record
            logger.debug(
                f"[DISCREPANCY-DETECTOR] Fill validated: {client_order_id} | "
                f"exposure={actual_exposure} matches expected"
            )
            del self._intents[client_order_id]
            return None
    
    def _record_discrepancy(self, discrepancy: DiscrepancyEvent, intent: IntentRecord) -> None:
        """Record a discrepancy event and clean up intent record."""
        # Record discrepancy
        self._discrepancies.append(discrepancy)
        if len(self._discrepancies) > self._max_discrepancy_history:
            self._discrepancies.pop(0)
        
        # Log error
        logger.error(
            f"[ORDER_MISMATCH] {discrepancy.severity.value.upper()} | "
            f"type={discrepancy.discrepancy_type} | "
            f"order={discrepancy.client_order_id} | asset={intent.asset} | "
            f"intent={intent.strategy_intent} | expected_leg={intent.expected_leg} | "
            f"expected_role={intent.expected_liquidity_role} | realized_role={discrepancy.realized_liquidity_role} | "
            f"error={discrepancy.error_message}"
        )
        
        # CRITICAL FIX (2026-07-19): Record metrics for production observability
        try:
            from merid.monitor.discrepancy_metrics import (
                get_discrepancy_metrics_collector,
                DiscrepancyType,
            )
            metrics_collector = get_discrepancy_metrics_collector()
            
            # Map discrepancy_type string to enum
            discrepancy_type_map = {
                "EXPOSURE_MISMATCH": DiscrepancyType.EXPOSURE_MISMATCH,
                "LIQUIDITY_ROLE_MISMATCH": DiscrepancyType.LIQUIDITY_ROLE_MISMATCH,
                "FEE_MISMATCH": DiscrepancyType.FEE_MISMATCH,
                "ORDER_CONTRACT_VIOLATION": DiscrepancyType.ORDER_CONTRACT_VIOLATION,
            }
            
            discrepancy_type_enum = discrepancy_type_map.get(
                discrepancy.discrepancy_type,
                DiscrepancyType.EXPOSURE_MISMATCH,  # Default
            )
            
            metrics_collector.record_discrepancy(
                discrepancy_type=discrepancy_type_enum,
                asset=intent.asset,
                severity=discrepancy.severity.value,
            )
        except ImportError:
            logger.warning("[DISCREPANCY-METRICS] discrepancy_metrics module not available - skipping metrics recording")
        
        # Clean up intent record
        if discrepancy.client_order_id in self._intents:
            del self._intents[discrepancy.client_order_id]
    
    def _compute_exposure_from_fill(self, side: str, action: str, quantity: int) -> Dict[str, int]:
        """Compute net exposure change from fill.
        
        Returns dict with "yes" and "no" exposure changes (+/-).
        """
        exposure = {"yes": 0, "no": 0}
        
        if side == "yes":
            if action == "buy":
                exposure["yes"] += quantity
            else:  # sell
                exposure["yes"] -= quantity
        else:  # "no"
            if action == "buy":
                exposure["no"] += quantity
            else:  # sell
                exposure["no"] -= quantity
        
        return exposure
    
    def _compute_expected_exposure(self, intent: IntentRecord) -> Dict[str, int]:
        """Compute expected exposure from intent record."""
        exposure = {"yes": 0, "no": 0}
        
        # Determine direction from entry_or_exit
        if intent.entry_or_exit == "entry":
            direction = "increase"
        else:  # exit
            direction = "decrease"
        
        # Apply to expected leg
        if direction == "increase":
            exposure[intent.expected_leg] += 1  # Assume 1 contract for now
        else:  # decrease
            exposure[intent.expected_leg] -= 1
        
        return exposure
    
    def _determine_severity(
        self,
        intent: IntentRecord,
        actual_exposure: Dict[str, int],
        expected_exposure: Dict[str, int],
    ) -> DiscrepancySeverity:
        """Determine severity of discrepancy."""
        # Check if wrong leg (critical)
        if actual_exposure["yes"] != 0 and expected_exposure["yes"] == 0:
            return DiscrepancySeverity.CRITICAL
        if actual_exposure["no"] != 0 and expected_exposure["no"] == 0:
            return DiscrepancySeverity.CRITICAL
        
        # Check if wrong direction (high)
        if (actual_exposure["yes"] > 0 and expected_exposure["yes"] < 0) or \
           (actual_exposure["yes"] < 0 and expected_exposure["yes"] > 0) or \
           (actual_exposure["no"] > 0 and expected_exposure["no"] < 0) or \
           (actual_exposure["no"] < 0 and expected_exposure["no"] > 0):
            return DiscrepancySeverity.HIGH
        
        # Default to medium
        return DiscrepancySeverity.MEDIUM
    
    def get_discrepancies(self, limit: int = 100) -> List[DiscrepancyEvent]:
        """Get recent discrepancy events.
        
        Args:
            limit: Maximum number of events to return
            
        Returns:
            List of discrepancy events, most recent first
        """
        with self._lock:
            return list(reversed(self._discrepancies[-limit:]))
    
    def get_pending_intents(self) -> List[IntentRecord]:
        """Get intents awaiting validation.
        
        Returns:
            List of intent records that haven't been validated yet
        """
        with self._lock:
            return list(self._intents.values())
    
    def cleanup_old_intents(self, max_age_seconds: int = 300) -> int:
        """Clean up old intent records that were never validated.
        
        Args:
            max_age_seconds: Maximum age before cleanup
            
        Returns:
            Number of records cleaned up
        """
        with self._lock:
            now = time.time()
            to_remove = [
                order_id for order_id, record in self._intents.items()
                if now - record.timestamp > max_age_seconds
            ]
            
            for order_id in to_remove:
                logger.warning(
                    f"[DISCREPANCY-DETECTOR] Cleaning up unvalidated intent: {order_id} "
                    f"(age={now - self._intents[order_id].timestamp:.1f}s)"
                )
                del self._intents[order_id]
            
            return len(to_remove)


# Global singleton
_detector: Optional[OrderDiscrepancyDetector] = None
_detector_lock = threading.Lock()


def get_discrepancy_detector() -> OrderDiscrepancyDetector:
    """Get the global discrepancy detector singleton."""
    global _detector
    with _detector_lock:
        if _detector is None:
            _detector = OrderDiscrepancyDetector()
            logger.info("[DISCREPANCY-DETECTOR] Initialized global singleton")
        return _detector


def reset_discrepancy_detector() -> None:
    """Reset the global discrepancy detector (for testing)."""
    global _detector
    with _detector_lock:
        _detector = None
        logger.info("[DISCREPANCY-DETECTOR] Reset global singleton")
