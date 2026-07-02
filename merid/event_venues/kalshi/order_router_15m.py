"""Kalshi 15m Order Router — Lean Kalshi-only order execution.

⚠️ WARNING: THIS MODULE IS NOT USED IN PRODUCTION ⚠️

This module contains a MOCK order router implementation that does NOT execute real orders.
The production system uses merid.event_venues.kalshi.order_router.py instead.

This file is kept for reference only. Do NOT import or use this module in production code.

For production order routing, use:
    from merid.event_venues.kalshi.order_router import route_order_async, OrderIntent

This is a minimal, Kalshi-specific order router designed for the
kalshi_crypto_15m_v2 profile. It has NO dependencies on:
- PM runtime (DeploymentController, persisted agents, lane managers)
- Paper trading engine
- Multi-venue abstractions
- Swarm event schemas

This router only:
- Routes orders to Kalshi API (demo or live)
- Applies Kalshi-specific risk checks
- Enforces trading mode (demo vs live)

Usage:
    from merid.event_venues.kalshi.order_router_15m import Kalshi15mOrderRouter, get_kalshi_15m_order_router
    
    router = get_kalshi_15m_order_router()
    result = await router.submit_order(intent)
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.order_router_15m")


class KalshiTradingMode(str, Enum):
    """Kalshi trading mode - simplified for 15m stack."""
    DEMO = "demo"  # Paper trading on Kalshi demo API
    LIVE = "live"  # Live trading on Kalshi production API


class OrderSide(str, Enum):
    """Order side."""
    YES = "yes"
    NO = "no"


class OrderAction(str, Enum):
    """Order action."""
    BUY = "buy"
    SELL = "sell"


@dataclass
class KalshiOrderIntent:
    """Kalshi order intent - minimal data model."""
    ticker: str  # Kalshi market ticker (e.g., "KXBTCD-25JUN-T100000")
    side: OrderSide  # "yes" or "no"
    action: OrderAction  # "buy" or "sell"
    count: int  # Number of contracts
    price_cents: int  # Price in cents (e.g., 55 for $0.55)
    
    # Optional fields for risk checks
    client_order_id: Optional[str] = None
    risk_checked: bool = False  # Must be True before submission


@dataclass
class KalshiOrderResult:
    """Kalshi order result."""
    success: bool
    order_id: Optional[str] = None
    message: str = ""
    created_at: datetime = None
    
    # Filled details (if filled immediately)
    filled_count: int = 0
    avg_price_cents: int = 0
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now(timezone.utc)


class Kalshi15mOrderRouter:
    """Lean Kalshi order router for 15m stack.
    
    This router:
    - Only talks to Kalshi API (demo or live)
    - Applies minimal risk checks
    - Has no multi-venue or PM runtime dependencies
    """
    
    def __init__(self, mode: KalshiTradingMode = KalshiTradingMode.DEMO):
        self.mode = mode
        self._order_count = 0
        logger.info(f"[15M-ROUTER] Initialized in {mode.value} mode")
    
    async def submit_order(self, intent: KalshiOrderIntent) -> KalshiOrderResult:
        """Submit order to Kalshi API.
        
        Args:
            intent: KalshiOrderIntent with order details
            
        Returns:
            KalshiOrderResult with execution result
        """
        # Validate intent
        if not intent.risk_checked:
            logger.error("[15M-ROUTER] Order intent not risk-checked")
            return KalshiOrderResult(
                success=False,
                message="Order intent not risk-checked"
            )
        
        if intent.count <= 0:
            logger.error(f"[15M-ROUTER] Invalid count: {intent.count}")
            return KalshiOrderResult(
                success=False,
                message=f"Invalid count: {intent.count}"
            )
        
        if intent.price_cents <= 0:
            logger.error(f"[15M-ROUTER] Invalid price: {intent.price_cents}")
            return KalshiOrderResult(
                success=False,
                message=f"Invalid price: {intent.price_cents}"
            )
        
        # Route to Kalshi API
        try:
            result = await self._route_to_kalshi(intent)
            self._order_count += 1
            logger.info(
                f"[15M-ROUTER] Order submitted: {intent.ticker} "
                f"{intent.side} {intent.action} {intent.count} @ {intent.price_cents}c"
            )
            return result
        except Exception as e:
            logger.exception(f"[15M-ROUTER] Order submission failed: {e}")
            return KalshiOrderResult(
                success=False,
                message=f"Order submission failed: {e}"
            )
    
    async def _route_to_kalshi(self, intent: KalshiOrderIntent) -> KalshiOrderResult:
        """Route order to Kalshi API (demo or live)."""
        from merid.event_venues.kalshi import get_kalshi_client
        
        client = get_kalshi_client()
        
        # Convert intent to Kalshi API format
        # Note: This is a simplified implementation
        # In production, you would use the full Kalshi client API
        
        # For now, return a mock result
        # TODO: Implement actual Kalshi API call
        logger.warning(
            f"[15M-ROUTER] Mock order submission (not yet implemented): "
            f"{intent.ticker} {intent.side} {intent.action} {intent.count} @ {intent.price_cents}c"
        )
        
        return KalshiOrderResult(
            success=True,
            order_id=f"mock_{intent.client_order_id or 'unknown'}",
            message="Mock order submission (not yet implemented)"
        )


# Singleton instance
_kalshi_15m_order_router: Optional[Kalshi15mOrderRouter] = None


def get_kalshi_15m_order_router() -> Kalshi15mOrderRouter:
    """Get singleton Kalshi 15m order router instance."""
    global _kalshi_15m_order_router
    
    if _kalshi_15m_order_router is None:
        from merid.event_venues.kalshi.invariants import get_kalshi_base_url
        
        base_url = get_kalshi_base_url()
        mode = KalshiTradingMode.LIVE if "demo" not in base_url.lower() else KalshiTradingMode.DEMO
        
        _kalshi_15m_order_router = Kalshi15mOrderRouter(mode=mode)
        logger.info(f"[15M-ROUTER] Singleton created in {mode.value} mode")
    
    return _kalshi_15m_order_router
