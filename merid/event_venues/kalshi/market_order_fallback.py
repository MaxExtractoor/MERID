"""Market Order Fallback Engine for Resting Orders.

This module implements a conditional market order fallback mechanism for
resting limit orders that are unlikely to fill. The engine evaluates each
resting order against conviction, time to expiry, and market conditions,
and converts to market orders when appropriate to prevent missed winning trades.

Key features:
- Conditional fallback (not automatic)
- Time-based triggers with conviction checks
- Market condition awareness (spread, depth)
- Per-asset configuration
- Comprehensive audit trail
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


@dataclass
class FallbackConfig:
    """Configuration for market order fallback."""
    
    # Time-based triggers
    fallback_after_seconds: int = 90  # Convert after 90s (half of max hold)
    min_age_before_fallback: int = 30  # Minimum age before considering fallback
    
    # Conviction thresholds
    min_edge_pct: float = 0.0125  # Minimum edge for fallback (1.25% BTC base)
    min_confidence: float = 0.70  # Minimum model confidence
    
    # Time to expiry
    max_tte_for_fallback: int = 300  # Max 5 minutes to expiry
    urgent_tte_threshold: int = 120  # Urgent if < 2 minutes to expiry
    
    # Market conditions
    max_spread_cents: int = 10  # Max spread for fallback
    min_depth_contracts: int = 5  # Minimum depth at best price
    
    # Asset-specific overrides
    asset_overrides: Dict[str, Dict] = field(default_factory=dict)
    
    def get_asset_config(self, asset: str) -> Dict[str, Any]:
        """Get asset-specific configuration or use defaults."""
        return self.asset_overrides.get(asset, {})


@dataclass
class FallbackDecision:
    """Decision whether to fallback to market order."""
    
    should_fallback: bool
    reason: str
    original_order: Any  # RestingOrderRecord
    current_market_state: Optional[Any] = None
    edge_at_placement: Optional[float] = None
    current_edge: Optional[float] = None
    time_to_expiry: Optional[float] = None
    confidence: Optional[float] = None
    age_seconds: Optional[float] = None
    spread_cents: Optional[int] = None
    depth_contracts: Optional[int] = None


class MarketOrderFallbackEngine:
    """Evaluates resting orders and decides on market order fallback."""
    
    def __init__(self, config: Optional[FallbackConfig] = None):
        self.config = config or FallbackConfig()
        self._fallback_count = 0
        self._skip_count = 0
        self._execution_failures = 0
    
    def evaluate_fallback(
        self,
        order: Any,
        market_state: Optional[Any] = None
    ) -> FallbackDecision:
        """Evaluate if order should fallback to market order.
        
        Args:
            order: RestingOrderRecord to evaluate
            market_state: Optional KalshiMarketState for market conditions
            
        Returns:
            FallbackDecision with should_fallback flag and reason
        """
        try:
            # Get asset-specific config
            asset = getattr(order, 'asset', None)
            asset_config = self.config.get_asset_config(asset) if asset else {}
            
            # Apply asset-specific overrides
            fallback_after = asset_config.get('fallback_after_seconds', self.config.fallback_after_seconds)
            min_age = asset_config.get('min_age_before_fallback', self.config.min_age_before_fallback)
            min_edge = asset_config.get('min_edge_pct', self.config.min_edge_pct)
            min_conf = asset_config.get('min_confidence', self.config.min_confidence)
            max_spread = asset_config.get('max_spread_cents', self.config.max_spread_cents)
            min_depth = asset_config.get('min_depth_contracts', self.config.min_depth_contracts)
            
            # Check 1: Minimum age
            age_seconds = (datetime.utcnow() - order.created_at).total_seconds()
            if age_seconds < min_age:
                return FallbackDecision(
                    should_fallback=False,
                    reason=f"too_young:{age_seconds:.0f}s<{min_age}s",
                    original_order=order,
                    age_seconds=age_seconds
                )
            
            # Check 2: Time-based trigger
            if age_seconds < fallback_after:
                # Check urgency (near expiry)
                tte = self._get_time_to_expiry(order)
                # If TTE is None or not urgent, return not_old_enough
                if tte is None or tte <= self.config.urgent_tte_threshold:
                    return FallbackDecision(
                        should_fallback=False,
                        reason=f"not_old_enough:{age_seconds:.0f}s<{fallback_after}s",
                        original_order=order,
                        age_seconds=age_seconds,
                        time_to_expiry=tte
                    )
                # TTE is not urgent (too far from expiry)
                return FallbackDecision(
                    should_fallback=False,
                    reason=f"not_urgent:tte={tte:.0f}s>{self.config.urgent_tte_threshold}s",
                    original_order=order,
                    age_seconds=age_seconds,
                    time_to_expiry=tte
                )
            
            # Check 3: Conviction (edge and confidence)
            edge = getattr(order, 'original_edge_pct', None)
            if edge is not None and edge < min_edge:
                return FallbackDecision(
                    should_fallback=False,
                    reason=f"low_edge:{edge:.3f}<{min_edge:.3f}",
                    original_order=order,
                    age_seconds=age_seconds,
                    edge_at_placement=edge
                )
            
            confidence = getattr(order, 'confidence', None)
            if confidence is not None and confidence < min_conf:
                return FallbackDecision(
                    should_fallback=False,
                    reason=f"low_confidence:{confidence:.2f}<{min_conf:.2f}",
                    original_order=order,
                    age_seconds=age_seconds,
                    confidence=confidence
                )
            
            # Check 4: Time to expiry (not too close to settlement)
            tte = self._get_time_to_expiry(order)
            if tte is not None and tte > self.config.max_tte_for_fallback:
                return FallbackDecision(
                    should_fallback=False,
                    reason=f"too_far_from_expiry:{tte:.0f}s>{self.config.max_tte_for_fallback}s",
                    original_order=order,
                    age_seconds=age_seconds,
                    time_to_expiry=tte
                )
            
            # Check 5: Market conditions (spread and depth)
            spread_cents = None
            depth_contracts = None
            
            if market_state:
                spread_cents = getattr(market_state, 'spread_cents', None)
                if spread_cents is not None and spread_cents > max_spread:
                    return FallbackDecision(
                        should_fallback=False,
                        reason=f"wide_spread:{spread_cents}c>{max_spread}c",
                        original_order=order,
                        current_market_state=market_state,
                        age_seconds=age_seconds,
                        spread_cents=spread_cents
                    )
                
                # Calculate total depth (YES + NO)
                yes_depth = getattr(market_state, 'min_depth_yes', 0)
                no_depth = getattr(market_state, 'min_depth_no', 0)
                depth_contracts = yes_depth + no_depth
                
                if depth_contracts < min_depth:
                    return FallbackDecision(
                        should_fallback=False,
                        reason=f"thin_depth:{depth_contracts}<{min_depth}",
                        original_order=order,
                        current_market_state=market_state,
                        age_seconds=age_seconds,
                        depth_contracts=depth_contracts
                    )
            
            # All checks passed - fallback to market
            return FallbackDecision(
                should_fallback=True,
                reason=f"all_checks_passed:age={age_seconds:.0f}s",
                original_order=order,
                current_market_state=market_state,
                edge_at_placement=edge,
                time_to_expiry=tte,
                confidence=confidence,
                age_seconds=age_seconds,
                spread_cents=spread_cents,
                depth_contracts=depth_contracts
            )
            
        except Exception as e:
            logger.error(f"[MARKET-ORDER-FALLBACK] Evaluation failed for order {getattr(order, 'kalshi_order_id', 'unknown')}: {e}")
            # On error, skip fallback to be safe
            return FallbackDecision(
                should_fallback=False,
                reason=f"evaluation_error:{str(e)}",
                original_order=order
            )
    
    def _get_time_to_expiry(self, order: Any) -> Optional[float]:
        """Get time to expiry in seconds from order record."""
        try:
            # Try to get from original_minutes_to_expiry
            original_tte = getattr(order, 'original_minutes_to_expiry', None)
            if original_tte is not None:
                elapsed_minutes = (datetime.utcnow() - order.created_at).total_seconds() / 60.0
                current_tte = max(0, original_tte - elapsed_minutes)
                return current_tte * 60.0  # Convert to seconds
            
            # Try to get from market state if available
            # This would require accessing market_state_store, which we don't have here
            return None
        except Exception as e:
            logger.debug(f"[MARKET-ORDER-FALLBACK] Could not get time to expiry: {e}")
            return None
    
    async def execute_fallback(
        self,
        decision: FallbackDecision
    ) -> Dict[str, Any]:
        """Execute market order fallback.
        
        Args:
            decision: FallbackDecision with should_fallback=True
            
        Returns:
            Dict with execution result
        """
        if not decision.should_fallback:
            self._skip_count += 1
            return {"status": "skipped", "reason": decision.reason}
        
        try:
            from merid.event_venues.kalshi.client import get_kalshi_client
            from merid.event_venues.kalshi.order_router import OrderIntent, route_order_async
            
            client = get_kalshi_client()
            
            # Cancel original limit order
            logger.info(
                "[MARKET-ORDER-FALLBACK] Cancelling original limit order: kalshi_order_id=%s ticker=%s",
                decision.original_order.kalshi_order_id,
                decision.original_order.ticker
            )
            
            cancel_result = await client.cancel_order(
                decision.original_order.kalshi_order_id,
                decision.original_order.ticker
            )
            
            logger.info(
                "[MARKET-ORDER-FALLBACK] Cancel result: %s",
                cancel_result
            )
            
            # Place market order
            intent = OrderIntent(
                ticker=decision.original_order.ticker,
                side=decision.original_order.side,
                action=decision.original_order.action,
                price_cents=0,  # Market order
                count=decision.original_order.remaining_size,
                order_type="market",
                time_in_force="ioc",
                source="market_order_fallback",
                intent_id=f"fallback_{decision.original_order.intent_id}",
                agent_id=decision.original_order.intent_id,
                rationale=f"Fallback from limit order: {decision.reason}"
            )
            
            logger.info(
                "[MARKET-ORDER-FALLBACK] Placing market order: ticker=%s side=%s action=%s count=%d",
                intent.ticker, intent.side, intent.action, intent.count
            )
            
            result = await route_order_async(intent)
            
            self._fallback_count += 1
            
            logger.info(
                "[MARKET-ORDER-FALLBACK] Executed fallback: kalshi_order_id=%s "
                "ticker=%s side=%s count=%d reason=%s result=%s",
                decision.original_order.kalshi_order_id,
                decision.original_order.ticker,
                decision.original_order.side,
                decision.original_order.remaining_size,
                decision.reason,
                result
            )
            
            return {
                "status": "executed",
                "original_order_id": decision.original_order.kalshi_order_id,
                "fallback_order_id": result.get("order_id"),
                "reason": decision.reason,
                "result": result
            }
            
        except Exception as e:
            self._execution_failures += 1
            logger.error(f"[MARKET-ORDER-FALLBACK] Failed to execute fallback: {e}")
            return {"status": "failed", "error": str(e)}
    
    def get_stats(self) -> Dict[str, Any]:
        """Get fallback engine statistics."""
        return {
            "fallback_count": self._fallback_count,
            "skip_count": self._skip_count,
            "execution_failures": self._execution_failures,
            "total_evaluations": self._fallback_count + self._skip_count,
            "fallback_rate": (
                self._fallback_count / (self._fallback_count + self._skip_count)
                if (self._fallback_count + self._skip_count) > 0
                else 0.0
            )
        }


# Global singleton instance
_fallback_engine_instance: Optional[MarketOrderFallbackEngine] = None


def get_market_order_fallback_engine() -> MarketOrderFallbackEngine:
    """Get the global market order fallback engine singleton.
    
    Returns:
        MarketOrderFallbackEngine instance
    """
    global _fallback_engine_instance
    if _fallback_engine_instance is None:
        _fallback_engine_instance = MarketOrderFallbackEngine()
    return _fallback_engine_instance


def configure_fallback(config: FallbackConfig) -> None:
    """Configure the global fallback engine with custom config.
    
    Args:
        config: FallbackConfig with custom settings
    """
    global _fallback_engine_instance
    _fallback_engine_instance = MarketOrderFallbackEngine(config)
    logger.info("[MARKET-ORDER-FALLBACK] Configured with custom config")
