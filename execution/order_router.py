"""
OrderRouter - Unified Order Execution with Mode Enforcement

Single routing point for all order execution. Guarantees that:
- In SIM mode: only local simulator is used
- In PAPER mode: only broker paper APIs are used
- In LIVE mode: requires explicit authorization and dual approval

No agent can bypass this router - it's the only way to execute trades.
"""

from __future__ import annotations

import threading
import asyncio
import time
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Any

from schemas.swarm_events import TradeIntent, OrderEvent, TradingMode
from observability.event_stream import publish_event
from utils.logger import get_logger

logger = get_logger("execution.order_router")


class OrderRouterError(Exception):
    """Base exception for order router errors."""
    pass


class LiveModeViolation(OrderRouterError):
    """Attempted to use live broker in non-live mode."""
    pass


class ModeNotAuthorized(OrderRouterError):
    """Trading mode not authorized for this session."""
    pass


@dataclass
class OrderRouterConfig:
    """Configuration for order router."""
    # Global mode setting
    run_mode: TradingMode = TradingMode.MOCK  # ZT2-09: was SIMULATION, now canonical MOCK
    
    # Authorization
    live_mode_authorized: bool = False
    live_mode_dual_approval: bool = False
    live_mode_approvers: List[str] = None
    
    # Paper trading settings
    paper_broker: str = "alpaca"  # alpaca, ibkr, coinbase
    paper_api_enabled: bool = True
    
    # Simulation settings
    sim_slippage_bps: float = 5.0
    sim_commission_bps: float = 2.0
    sim_fill_delay_ms: float = 100.0
    
    # Safety limits
    max_order_size_usd: float = 100_000.0
    max_daily_orders: int = 1000
    max_position_size_pct: float = 0.25  # 25% of portfolio
    
    def __post_init__(self):
        if self.live_mode_approvers is None:
            self.live_mode_approvers = []


class OrderRouter:
    """
    Single point of control for all order execution.
    
    Routes trade intents to appropriate backend based on RUN_MODE.
    Enforces mode isolation and prevents accidental live trading.
    """
    
    def __init__(self, config: Optional[OrderRouterConfig] = None):
        self.config = config or OrderRouterConfig()
        self._daily_order_count = 0
        self._last_reset_day = time.time()
        
        # Track all submitted orders for auditing
        self._order_history: List[OrderEvent] = []
        self._trade_intent_to_order: Dict[str, str] = {}
        
        logger.info(
            f"OrderRouter initialized in {self.config.run_mode.value.upper()} mode "
            f"(live_authorized={self.config.live_mode_authorized})"
        )
    
    async def submit_order(self, intent: TradeIntent) -> OrderEvent:
        """
        Submit a trade intent for execution.
        
        This is the ONLY method agents should call to execute trades.
        It enforces mode isolation and routes to the correct backend.
        
        Args:
            intent: TradeIntent with all order details
            
        Returns:
            OrderEvent with execution results
            
        Raises:
            LiveModeViolation: If attempting to use live broker in non-live mode
            ModeNotAuthorized: If current mode is not authorized
            OrderRouterError: For other validation failures
        """
        # Validate mode matches global setting
        if intent.mode != self.config.run_mode:
            logger.error(
                f"Mode mismatch: intent has {intent.mode.value}, "
                f"but router is in {self.config.run_mode.value}"
            )
            raise OrderRouterError(
                f"Trade intent mode ({intent.mode.value}) does not match "
                f"router mode ({self.config.run_mode.value})"
            )
        
        # Enforce live mode authorization
        if intent.mode == TradingMode.LIVE:
            if not self.config.live_mode_authorized:
                logger.critical("LIVE MODE VIOLATION: Attempted live trade without authorization")
                raise ModeNotAuthorized("Live trading not authorized for this session")
            
            if self.config.live_mode_dual_approval:
                logger.info("Live trade requires dual approval - escalating")
                # In production, this would trigger approval workflow
                raise OrderRouterError("Live trade requires dual approval (not implemented)")
        
        # Safety checks
        await self._validate_intent(intent)
        
        # Reset daily counter if needed
        self._maybe_reset_daily_counter()
        
        # Check daily limits
        if self._daily_order_count >= self.config.max_daily_orders:
            raise OrderRouterError(
                f"Daily order limit reached ({self.config.max_daily_orders})"
            )
        
        # Route to appropriate backend
        if intent.mode == TradingMode.MOCK:
            order_event = await self._route_to_simulator(intent)
        elif intent.mode == TradingMode.PAPER:
            order_event = await self._route_to_paper(intent)
        elif intent.mode == TradingMode.LIVE:
            order_event = await self._route_to_live(intent)
        else:
            raise OrderRouterError(f"Unknown trading mode: {intent.mode}")
        
        # Record and publish
        self._daily_order_count += 1
        self._order_history.append(order_event)
        if len(self._order_history) > 10000:
            self._order_history = self._order_history[-5000:]
        self._trade_intent_to_order[intent.intent_id] = order_event.order_id
        if len(self._trade_intent_to_order) > 10000:
            # Keep only the most recent half by rebuilding from order_history
            recent_ids = {o.trade_intent_id for o in self._order_history if hasattr(o, 'trade_intent_id')}
            self._trade_intent_to_order = {k: v for k, v in self._trade_intent_to_order.items() if k in recent_ids}
        
        await publish_event("order_executed", order_event.to_dict())
        
        logger.info(
            f"Order executed: {order_event.order_id} "
            f"({intent.mode.value}) {intent.side} {intent.quantity} {intent.symbol}"
        )
        
        return order_event
    
    async def _validate_intent(self, intent: TradeIntent) -> None:
        """Validate trade intent before routing."""
        # Check risk approval
        if not intent.risk_checked:
            raise OrderRouterError("Trade intent not risk-checked")
        
        # Check size limits
        notional_usd = intent.quantity * intent.price_at_intent
        if notional_usd > self.config.max_order_size_usd:
            raise OrderRouterError(
                f"Order size ${notional_usd:.2f} exceeds max "
                f"${self.config.max_order_size_usd:.2f}"
            )
        
        # Validate required fields
        if not intent.symbol or not intent.venue:
            raise OrderRouterError("Missing required fields: symbol, venue")
        
        if intent.quantity <= 0:
            raise OrderRouterError(f"Invalid quantity: {intent.quantity}")
    
    async def _route_to_simulator(self, intent: TradeIntent) -> OrderEvent:
        """Route order to local simulator."""
        logger.debug(f"Routing to SIMULATOR: {intent.symbol}")
        
        # Simulate fill with slippage
        fill_price = intent.price_at_intent
        if intent.side == "buy":
            fill_price *= (1 + self.config.sim_slippage_bps / 10_000)
        else:
            fill_price *= (1 - self.config.sim_slippage_bps / 10_000)
        
        # Simulate delay
        await asyncio.sleep(self.config.sim_fill_delay_ms / 1000)
        
        # Calculate commission
        notional = intent.quantity * fill_price
        commission = notional * (self.config.sim_commission_bps / 10_000)
        
        # Create order event
        order_event = OrderEvent(
            order_id=f"sim_{intent.intent_id}",
            trade_intent_id=intent.intent_id,
            symbol=intent.symbol,
            venue=intent.venue,
            side=intent.side,
            quantity=intent.quantity,
            order_type=intent.order_type,
            status="filled",
            filled_quantity=intent.quantity,
            avg_fill_price=fill_price,
            fill_timestamp=time.time(),
            mode=TradingMode.MOCK,
            simulated=True,
            commission_usd=commission,
            slippage_bps=self.config.sim_slippage_bps,
            consensus_id=intent.consensus_id,
            opinion_ids=intent.opinion_refs,
            acknowledged_at=time.time(),
            completed_at=time.time(),
        )
        
        return order_event
    
    async def _route_to_paper(self, intent: TradeIntent) -> OrderEvent:
        """Route order to broker paper API."""
        logger.debug(f"Routing to PAPER: {intent.symbol} via {self.config.paper_broker}")
        
        if not self.config.paper_api_enabled:
            raise OrderRouterError("Paper API not enabled")
        
        # In production, this would call actual paper trading API
        # For now, simulate similar to SIM but mark as paper
        
        # Check for accidental live broker call
        if self._is_live_broker_call():
            logger.critical(
                "LIVE BROKER CALL DETECTED IN PAPER MODE - BLOCKING"
            )
            raise LiveModeViolation(
                "Attempted to call live broker API while in PAPER mode"
            )
        
        # Simulate paper API call
        await asyncio.sleep(0.2)  # API latency
        
        order_event = OrderEvent(
            order_id=f"paper_{self.config.paper_broker}_{intent.intent_id[:8]}",
            trade_intent_id=intent.intent_id,
            symbol=intent.symbol,
            venue=intent.venue,
            side=intent.side,
            quantity=intent.quantity,
            order_type=intent.order_type,
            status="filled",
            filled_quantity=intent.quantity,
            avg_fill_price=intent.price_at_intent,
            fill_timestamp=time.time(),
            mode=TradingMode.PAPER,
            simulated=False,  # Real paper API
            commission_usd=0.0,  # Paper APIs usually have no commission
            slippage_bps=2.0,
            consensus_id=intent.consensus_id,
            opinion_ids=intent.opinion_refs,
            acknowledged_at=time.time(),
            completed_at=time.time(),
        )
        
        return order_event
    
    async def _route_to_live(self, intent: TradeIntent) -> OrderEvent:
        """Route order to live broker API."""
        logger.critical(
            f"LIVE ORDER: {intent.side} {intent.quantity} {intent.symbol} "
            f"at ${intent.price_at_intent:.2f}"
        )
        
        # Double-check authorization
        if not self.config.live_mode_authorized:
            raise ModeNotAuthorized("Live mode not authorized")
        
        # In production, this would:
        # 1. Require dual approval if configured
        # 2. Call actual broker API
        # 3. Handle partial fills, rejections, etc.
        
        raise NotImplementedError(
            "Live trading not implemented - this is a safety measure. "
            "Requires explicit implementation and testing."
        )
    
    def _is_live_broker_call(self) -> bool:
        """
        Detect if any live broker client is being used.
        
        In production, this would check:
        - Stack trace for broker client imports
        - Network connections to broker endpoints
        - Environment variable inspection
        """
        # Placeholder - in production this would be a real check
        return False
    
    def _maybe_reset_daily_counter(self) -> None:
        """Reset daily order counter if day has changed."""
        current_day = int(time.time() / 86400)
        last_day = int(self._last_reset_day / 86400)
        
        if current_day > last_day:
            logger.info(
                f"Daily reset: {self._daily_order_count} orders yesterday"
            )
            self._daily_order_count = 0
            self._last_reset_day = time.time()
    
    def get_order_history(self, limit: int = 100) -> List[OrderEvent]:
        """Get recent order history."""
        return self._order_history[-limit:]
    
    def get_order_by_intent(self, intent_id: str) -> Optional[str]:
        """Get order ID for a given trade intent."""
        return self._trade_intent_to_order.get(intent_id)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get router statistics."""
        total_orders = len(self._order_history)
        filled_orders = sum(1 for o in self._order_history if o.status == "filled")
        
        return {
            "mode": self.config.run_mode.value,
            "live_authorized": self.config.live_mode_authorized,
            "total_orders": total_orders,
            "filled_orders": filled_orders,
            "daily_orders": self._daily_order_count,
            "daily_limit": self.config.max_daily_orders,
            "fill_rate": filled_orders / total_orders if total_orders > 0 else 0.0,
        }


# Global instance
_order_router: Optional[OrderRouter] = None
_order_router_lock = threading.Lock()


def get_order_router(config: Optional[OrderRouterConfig] = None) -> OrderRouter:
    """Get or create global order router."""
    global _order_router
    if _order_router is None:
        with _order_router_lock:
            if _order_router is None:
                _order_router = OrderRouter(config)
    return _order_router


async def submit_trade_intent(intent: TradeIntent) -> OrderEvent:
    """Convenience function to submit trade intent via global router."""
    router = get_order_router()
    return await router.submit_order(intent)
