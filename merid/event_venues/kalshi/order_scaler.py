"""Order Scaling Engine for Limit Order Execution.

Implements institutional-grade scaling strategies:
- TWAP (Time-Weighted Average Price)
- VWAP (Volume-Weighted Average Price)  
- Iceberg (hidden size display)
- Adaptive scaling based on edge and market conditions

This module answers: "How do we scale into high-edge contracts without signaling?"
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Tuple
from decimal import Decimal

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.order_scaler")


class ScalingStrategy(Enum):
    """Order scaling strategy types."""
    NONE = "none"  # Single order (current behavior)
    TWAP = "twap"  # Time-weighted average price
    VWAP = "vwap"  # Volume-weighted average price
    ICEBERG = "iceberg"  # Hidden size display
    ADAPTIVE = "adaptive"  # Edge-based adaptive scaling


@dataclass
class ScalingConfig:
    """Configuration for order scaling."""
    strategy: ScalingStrategy = ScalingStrategy.NONE
    min_child_orders: int = 1  # Minimum number of child orders
    max_child_orders: int = 5  # Maximum number of child orders
    time_window_seconds: float = 300.0  # Time window for execution (5 min default)
    participation_rate: float = 0.10  # Max 10% of market volume
    visible_pct: float = 0.10  # Iceberg: 10% visible
    time_jitter_pct: float = 0.10  # ±10% timing randomization
    size_jitter_pct: float = 0.10  # ±10% size randomization
    edge_threshold: float = 0.02  # 2% edge minimum for scaling
    size_threshold_contracts: int = 3  # Scale only if size >= 3 contracts


@dataclass
class ChildOrder:
    """A child order in a scaled execution plan."""
    ticker: str
    side: str
    action: str
    price_cents: int
    count: int
    delay_seconds: float  # Delay from parent order submission
    order_type: str = "limit"
    time_in_force: str = "gtc"
    visible_count: Optional[int] = None  # For iceberg orders


@dataclass
class ScalingPlan:
    """Complete scaling plan for a parent order."""
    parent_intent_id: str
    strategy: ScalingStrategy
    total_contracts: int
    child_orders: List[ChildOrder] = field(default_factory=list)
    expected_duration_seconds: float = 0.0
    rationale: str = ""


class OrderScaler:
    """
    Scales orders into child orders using institutional strategies.
    
    Strategies:
    1. TWAP: Equal-sized orders at regular time intervals
    2. VWAP: Size proportional to expected volume (U-shaped profile)
    3. Iceberg: Display small tip, hide bulk
    4. Adaptive: Scale based on edge and market conditions
    """
    
    def __init__(self, config: Optional[ScalingConfig] = None):
        self.config = config or ScalingConfig()
        logger.info("[ORDER-SCALER] Initialized with strategy=%s", self.config.strategy)
    
    def should_scale(
        self,
        contracts: int,
        edge_pct: float,
        market_depth: int,
    ) -> bool:
        """
        Determine if an order should be scaled.
        
        Args:
            contracts: Total contract count
            edge_pct: Edge percentage (0-1)
            market_depth: Market depth at target price
            
        Returns:
            True if scaling is recommended
        """
        # PRODUCTION SAFETY: Don't scale if contracts would exceed per-order limit
        # Kalshi max_single_order_contracts is typically 2 in production
        # Scaling is only useful if we can actually place larger orders
        if contracts <= self.config.size_threshold_contracts:
            logger.debug(
                "[ORDER-SCALER] Skip scaling: contracts=%d <= threshold=%d (too small to benefit)",
                contracts, self.config.size_threshold_contracts
            )
            return False
        
        # Don't scale low-edge orders
        if edge_pct < self.config.edge_threshold:
            logger.debug(
                "[ORDER-SCALER] Skip scaling: edge=%.4f < threshold=%.4f (insufficient edge)",
                edge_pct, self.config.edge_threshold
            )
            return False
        
        # Don't scale in thin markets (risk of slippage)
        if market_depth < 20:
            logger.debug(
                "[ORDER-SCALER] Skip scaling: depth=%d < 20 (thin market, slippage risk)",
                market_depth
            )
            return False
        
        # PRODUCTION SAFETY: Cap max child orders to prevent position explosion
        if self.config.max_child_orders > 10:
            logger.warning(
                "[ORDER-SCALER] PRODUCTION SAFETY: max_child_orders=%d > 10, capping to 10",
                self.config.max_child_orders
            )
            self.config.max_child_orders = 10
        
        return True
    
    def create_scaling_plan(
        self,
        ticker: str,
        side: str,
        action: str,
        price_cents: int,
        total_contracts: int,
        edge_pct: float,
        market_depth: int,
        parent_intent_id: str,
    ) -> Optional[ScalingPlan]:
        """
        Create a scaling plan for the order.
        
        Args:
            ticker: Market ticker
            side: "yes" or "no"
            action: "buy" or "sell"
            price_cents: Limit price in cents
            total_contracts: Total contract count
            edge_pct: Edge percentage
            market_depth: Market depth
            parent_intent_id: Parent order intent ID
            
        Returns:
            ScalingPlan or None if scaling not recommended
        """
        if not self.should_scale(total_contracts, edge_pct, market_depth):
            return None
        
        strategy = self.config.strategy
        
        if strategy == ScalingStrategy.TWAP:
            plan = self._create_twap_plan(
                ticker, side, action, price_cents, total_contracts, parent_intent_id
            )
        elif strategy == ScalingStrategy.ICEBERG:
            plan = self._create_iceberg_plan(
                ticker, side, action, price_cents, total_contracts, parent_intent_id
            )
        elif strategy == ScalingStrategy.ADAPTIVE:
            plan = self._create_adaptive_plan(
                ticker, side, action, price_cents, total_contracts, edge_pct, parent_intent_id
            )
        else:
            # Default to TWAP
            plan = self._create_twap_plan(
                ticker, side, action, price_cents, total_contracts, parent_intent_id
            )
        
        logger.info(
            "[ORDER-SCALER] Created %s plan: %d contracts -> %d child orders over %.1fs",
            strategy.value, total_contracts, len(plan.child_orders), plan.expected_duration_seconds
        )
        
        return plan
    
    def _create_twap_plan(
        self,
        ticker: str,
        side: str,
        action: str,
        price_cents: int,
        total_contracts: int,
        parent_intent_id: str,
    ) -> ScalingPlan:
        """Create TWAP scaling plan (equal-sized, time-distributed)."""
        # Determine number of child orders
        n_orders = min(
            self.config.max_child_orders,
            max(self.config.min_child_orders, total_contracts)
        )
        
        # Equal-sized orders
        contracts_per_order = total_contracts // n_orders
        remainder = total_contracts % n_orders
        
        # Time interval between orders
        interval = self.config.time_window_seconds / n_orders
        
        child_orders = []
        allocated_contracts = 0
        
        for i in range(n_orders):
            # Add remainder to first order
            count = contracts_per_order + (1 if i < remainder else 0)
            
            # PRODUCTION SAFETY: Ensure each child order is at least 1 contract
            count = max(1, count)
            
            # Add timing jitter (±10%)
            jitter = interval * self.config.time_jitter_pct * (random.random() * 2 - 1)
            delay = (i * interval) + jitter
            
            # PRODUCTION SAFETY: Apply size jitter but ensure total matches
            # We apply jitter to the last order to absorb any differences
            if i < n_orders - 1:
                # For all but last order, use base count
                final_count = count
            else:
                # Last order gets the remainder to ensure total matches
                final_count = total_contracts - allocated_contracts
                final_count = max(1, final_count)  # Ensure at least 1
            
            allocated_contracts += final_count
            
            child_orders.append(ChildOrder(
                ticker=ticker,
                side=side,
                action=action,
                price_cents=price_cents,
                count=final_count,
                delay_seconds=max(0, delay),
            ))
        
        # PRODUCTION SAFETY: Verify total matches
        actual_total = sum(child.count for child in child_orders)
        if actual_total != total_contracts:
            logger.warning(
                "[ORDER-SCALER] TWAP plan total mismatch: expected=%d actual=%d, correcting",
                total_contracts, actual_total
            )
            # Adjust last order to match
            if child_orders:
                child_orders[-1].count += (total_contracts - actual_total)
                child_orders[-1].count = max(1, child_orders[-1].count)
        
        return ScalingPlan(
            parent_intent_id=parent_intent_id,
            strategy=ScalingStrategy.TWAP,
            total_contracts=total_contracts,
            child_orders=child_orders,
            expected_duration_seconds=self.config.time_window_seconds,
            rationale=f"TWAP: {n_orders} equal orders over {self.config.time_window_seconds}s"
        )
    
    def _create_iceberg_plan(
        self,
        ticker: str,
        side: str,
        action: str,
        price_cents: int,
        total_contracts: int,
        parent_intent_id: str,
    ) -> ScalingPlan:
        """Create iceberg scaling plan (hidden size, small visible tip)."""
        # Visible portion (10% of total)
        visible_count = max(1, int(total_contracts * self.config.visible_pct))
        hidden_count = total_contracts - visible_count
        
        # Number of refreshes (hidden portion / visible portion)
        n_refreshes = max(1, hidden_count // visible_count)
        
        child_orders = []
        for i in range(n_refreshes + 1):  # +1 for initial visible
            # Each refresh shows visible_count
            count = visible_count
            
            # Randomize timing between refreshes
            if i == 0:
                delay = 0.0
            else:
                interval = self.config.time_window_seconds / n_refreshes
                jitter = interval * self.config.time_jitter_pct * (random.random() * 2 - 1)
                delay = (i * interval) + jitter
            
            child_orders.append(ChildOrder(
                ticker=ticker,
                side=side,
                action=action,
                price_cents=price_cents,
                count=count,
                delay_seconds=max(0, delay),
                visible_count=visible_count,  # Iceberg: visible tip
            ))
        
        return ScalingPlan(
            parent_intent_id=parent_intent_id,
            strategy=ScalingStrategy.ICEBERG,
            total_contracts=total_contracts,
            child_orders=child_orders,
            expected_duration_seconds=self.config.time_window_seconds,
            rationale=f"Iceberg: {visible_count} visible, {hidden_count} hidden over {n_refreshes} refreshes"
        )
    
    def _create_adaptive_plan(
        self,
        ticker: str,
        side: str,
        action: str,
        price_cents: int,
        total_contracts: int,
        edge_pct: float,
        parent_intent_id: str,
    ) -> ScalingPlan:
        """Create adaptive scaling plan based on edge."""
        # Higher edge = more aggressive (fewer, larger orders)
        # Lower edge = more conservative (more, smaller orders)
        
        if edge_pct >= 0.05:  # 5%+ edge: very aggressive
            n_orders = 2
        elif edge_pct >= 0.03:  # 3-5% edge: aggressive
            n_orders = 3
        elif edge_pct >= 0.02:  # 2-3% edge: moderate
            n_orders = 4
        else:  # 1-2% edge: conservative
            n_orders = 5
        
        n_orders = min(n_orders, self.config.max_child_orders)
        n_orders = max(n_orders, self.config.min_child_orders)
        
        # Front-load orders for high edge (capture quickly)
        if edge_pct >= 0.03:
            # 60% in first order, 40% spread over rest
            first_order_pct = 0.60
        else:
            # Equal distribution for lower edge
            first_order_pct = 1.0 / n_orders
        
        child_orders = []
        interval = self.config.time_window_seconds / n_orders
        allocated_contracts = 0
        
        for i in range(n_orders):
            if i == 0:
                count = int(total_contracts * first_order_pct)
            else:
                remaining_pct = (1.0 - first_order_pct) / (n_orders - 1)
                count = int(total_contracts * remaining_pct)
            
            # PRODUCTION SAFETY: Ensure each child order is at least 1 contract
            count = max(1, count)
            
            # PRODUCTION SAFETY: Ensure total matches by adjusting last order
            if i < n_orders - 1:
                final_count = count
            else:
                final_count = total_contracts - allocated_contracts
                final_count = max(1, final_count)
            
            allocated_contracts += final_count
            
            # Add timing jitter
            jitter = interval * self.config.time_jitter_pct * (random.random() * 2 - 1)
            delay = (i * interval) + jitter
            
            child_orders.append(ChildOrder(
                ticker=ticker,
                side=side,
                action=action,
                price_cents=price_cents,
                count=final_count,
                delay_seconds=max(0, delay),
            ))
        
        # PRODUCTION SAFETY: Verify total matches
        actual_total = sum(child.count for child in child_orders)
        if actual_total != total_contracts:
            logger.warning(
                "[ORDER-SCALER] Adaptive plan total mismatch: expected=%d actual=%d, correcting",
                total_contracts, actual_total
            )
            # Adjust last order to match
            if child_orders:
                child_orders[-1].count += (total_contracts - actual_total)
                child_orders[-1].count = max(1, child_orders[-1].count)
        
        return ScalingPlan(
            parent_intent_id=parent_intent_id,
            strategy=ScalingStrategy.ADAPTIVE,
            total_contracts=total_contracts,
            child_orders=child_orders,
            expected_duration_seconds=self.config.time_window_seconds,
            rationale=f"Adaptive: {n_orders} orders based on edge={edge_pct:.2%}"
        )


# Module-level singleton
_scaler: Optional[OrderScaler] = None


def get_order_scaler(config: Optional[ScalingConfig] = None) -> OrderScaler:
    """Get the order scaler singleton."""
    global _scaler
    if _scaler is None:
        _scaler = OrderScaler(config)
    return _scaler
