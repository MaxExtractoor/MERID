"""
Execution Coordinator - Bridge between Consensus and OrderRouter

Consumes ConsensusDecision events and creates TradeIntent for OrderRouter.
Integrates with risk management and position sizing.

This completes the swarm flow:
  Opinion → Consensus → TradeIntent → OrderRouter → OrderEvent
"""

from __future__ import annotations

import asyncio
import time
from typing import Dict, List, Optional

from schemas.swarm_events import (
    ConsensusDecision,
    TradeIntent,
    OrderEvent,
    TradingMode,
    OpinionDirection,
)
from execution.order_router import get_order_router, OrderRouter
from observability.event_stream import get_event_stream, publish_event
from observability.swarm_telemetry import get_swarm_telemetry
from utils.logger import get_logger

logger = get_logger("execution.coordinator")


class ExecutionCoordinator:
    """
    Execution Coordinator - Converts consensus into executable trades.
    
    Flow:
    1. Subscribe to consensus_decision events
    2. Run risk checks
    3. Create TradeIntent
    4. Submit to OrderRouter
    5. Emit OrderEvent
    """
    
    def __init__(
        self,
        mode: TradingMode = TradingMode.SIMULATION,
        enable_risk_checks: bool = True,
    ):
        self.mode = mode
        self.enable_risk_checks = enable_risk_checks
        self.event_stream = get_event_stream()
        self.order_router: Optional[OrderRouter] = None
        
        # Track active trades
        self._pending_trades: Dict[str, TradeIntent] = {}
        self._executed_trades: List[OrderEvent] = []
        
        # Subscriber task
        self._subscriber_task: Optional[asyncio.Task] = None
        
    async def start(self) -> None:
        """Start execution coordinator."""
        if self._subscriber_task is not None:
            logger.warning("Execution coordinator already running")
            return
        
        # Get order router
        self.order_router = get_order_router()
        
        # Start subscriber
        self._subscriber_task = asyncio.create_task(self._consensus_subscription_loop())
        logger.info(f"Execution coordinator started (mode={self.mode.value})")
    
    async def stop(self) -> None:
        """Stop execution coordinator."""
        if self._subscriber_task:
            self._subscriber_task.cancel()
            try:
                await self._subscriber_task
            except asyncio.CancelledError:
                pass
            self._subscriber_task = None
            logger.info("Execution coordinator stopped")
    
    async def _consensus_subscription_loop(self) -> None:
        """Background loop to consume consensus decisions."""
        queue = await self.event_stream.subscribe()
        
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=1.0)
                    
                    # Only process consensus_decision events
                    if event.event_type == "consensus_decision":
                        await self._handle_consensus_decision(event.payload)
                
                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    logger.error(f"Consensus subscription error: {e}")
                    await asyncio.sleep(1.0)
        
        finally:
            await self.event_stream.unsubscribe(queue)
    
    async def _handle_consensus_decision(self, payload: Dict[str, any]) -> None:
        """Handle incoming consensus decision event."""
        try:
            # Parse consensus decision
            decision = ConsensusDecision(**payload)
            
            logger.info(
                f"Received consensus: {decision.symbol} → {decision.decision.value} "
                f"(confidence={decision.confidence:.2f}, {len(decision.participating_agents)} agents)"
            )
            
            # Only execute if decision is actionable (not FLAT)
            if decision.decision == OpinionDirection.FLAT:
                logger.info(f"Skipping execution for FLAT decision on {decision.symbol}")
                return
            
            # Create trade intent
            intent = await self._create_trade_intent(decision)
            
            # Run risk checks if enabled
            if self.enable_risk_checks:
                risk_approved = await self._run_risk_checks(intent)
                intent.risk_checked = risk_approved
                
                if not risk_approved:
                    logger.warning(f"Risk check failed for {decision.symbol}, skipping execution")
                    return
            else:
                intent.risk_checked = True
            
            # Store pending trade
            self._pending_trades[intent.intent_id] = intent
            
            # Emit trade intent event
            await publish_event("trade_intent", intent.to_dict())
            
            # Submit to order router
            if self.order_router:
                order_event = await self.order_router.submit_order(intent)
                
                # Store executed trade
                self._executed_trades.append(order_event)
                
                # Remove from pending
                self._pending_trades.pop(intent.intent_id, None)
                
                logger.info(
                    f"Order executed: {order_event.symbol} {order_event.side} "
                    f"(status={order_event.status}, order_id={order_event.order_id})"
                )
            else:
                logger.error("OrderRouter not available")
        
        except Exception as e:
            logger.error(f"Failed to handle consensus decision: {e}", exc_info=True)
    
    async def _create_trade_intent(self, decision: ConsensusDecision) -> TradeIntent:
        """Create TradeIntent from ConsensusDecision."""
        # Map decision to order side
        side_map = {
            OpinionDirection.LONG: "buy",
            OpinionDirection.SHORT: "sell",
            OpinionDirection.REDUCE: "reduce",
            OpinionDirection.CLOSE: "close",
        }
        side = side_map.get(decision.decision, "buy")
        
        # Create trade intent
        intent = TradeIntent(
            symbol=decision.symbol,
            side=side,
            quantity=self._calculate_quantity(decision),
            price=0.0,  # Market order
            mode=self.mode,
            consensus_id=decision.consensus_round_id,
            risk_checked=False,  # Will be set by risk check
            opinion_refs=decision.opinion_ids,
            state_version="",  # Could track state version from decision
            confidence=decision.confidence,
        )
        
        return intent
    
    def _calculate_quantity(self, decision: ConsensusDecision) -> float:
        """Calculate order quantity from consensus decision."""
        # Simple implementation: use size_usd from decision
        # In production, would query current price and calculate quantity
        base_quantity = decision.size_usd / 50000.0  # Assume BTC price ~50k
        
        # Adjust by confidence
        adjusted_quantity = base_quantity * decision.confidence
        
        # Round to reasonable precision
        return round(adjusted_quantity, 4)
    
    async def _run_risk_checks(self, intent: TradeIntent) -> bool:
        """
        Run risk checks on trade intent.
        
        In production, this would:
        - Check position limits
        - Verify sufficient margin
        - Check correlation with existing positions
        - Validate against portfolio risk limits
        """
        # Simplified risk check for now
        
        # Check if quantity is reasonable
        if intent.quantity <= 0:
            logger.warning(f"Invalid quantity: {intent.quantity}")
            return False
        
        if intent.quantity > 100:
            logger.warning(f"Quantity too large: {intent.quantity}")
            return False
        
        # Check confidence threshold
        if intent.confidence < 0.5:
            logger.warning(f"Confidence too low: {intent.confidence}")
            return False
        
        # All checks passed
        return True
    
    def get_pending_count(self) -> int:
        """Get number of pending trades."""
        return len(self._pending_trades)
    
    def get_executed_count(self) -> int:
        """Get number of executed trades."""
        return len(self._executed_trades)
    
    def get_stats(self) -> Dict[str, any]:
        """Get execution statistics."""
        return {
            "mode": self.mode.value,
            "pending_trades": self.get_pending_count(),
            "executed_trades": self.get_executed_count(),
            "risk_checks_enabled": self.enable_risk_checks,
        }


# Global singleton
_execution_coordinator: Optional[ExecutionCoordinator] = None


def get_execution_coordinator(
    mode: TradingMode = TradingMode.SIMULATION,
    enable_risk_checks: bool = True,
) -> ExecutionCoordinator:
    """Get or create global execution coordinator."""
    global _execution_coordinator
    if _execution_coordinator is None:
        _execution_coordinator = ExecutionCoordinator(
            mode=mode,
            enable_risk_checks=enable_risk_checks,
        )
    return _execution_coordinator
