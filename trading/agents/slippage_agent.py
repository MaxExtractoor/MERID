"""
Slippage Agent - Monitors and minimizes slippage on trades.

Analyzes:
- Order book depth
- Market impact estimation
- Optimal order sizing
- TWAP/VWAP execution strategies
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("trading.agents.slippage")


@dataclass
class OrderBookSnapshot:
    """Order book snapshot for slippage analysis."""
    venue: str
    asset: str
    timestamp: float
    bids: List[tuple[float, float]]  # [(price, size), ...]
    asks: List[tuple[float, float]]
    mid_price: float
    spread_bps: float
    
    def calculate_market_impact(self, size_usd: float, side: str) -> float:
        """Calculate expected market impact for given order size."""
        levels = self.asks if side == "buy" else self.bids
        
        remaining_size = size_usd
        total_cost = 0.0
        
        for price, available_size in levels:
            if remaining_size <= 0:
                break
            
            fill_size = min(remaining_size, available_size * price)
            total_cost += fill_size
            remaining_size -= fill_size
        
        if remaining_size > 0:
            # Not enough liquidity
            return float('inf')
        
        avg_fill_price = total_cost / size_usd
        slippage_bps = abs((avg_fill_price - self.mid_price) / self.mid_price) * 10000
        
        return slippage_bps


@dataclass
class ExecutionStrategy:
    """Optimal execution strategy recommendation."""
    strategy_type: str  # 'market', 'limit', 'twap', 'vwap', 'iceberg'
    order_size: float
    num_chunks: int
    time_interval_seconds: Optional[float]
    limit_price: Optional[float]
    expected_slippage_bps: float
    confidence: float


class SlippageAgent:
    """
    Monitors and minimizes slippage through intelligent order execution.
    
    Strategies:
    1. Market impact analysis
    2. TWAP (Time-Weighted Average Price)
    3. VWAP (Volume-Weighted Average Price)
    4. Iceberg orders
    5. Adaptive execution
    """
    
    def __init__(
        self,
        max_acceptable_slippage_bps: float = 10.0,
        min_liquidity_ratio: float = 0.1  # Order size / available liquidity
    ):
        self.max_acceptable_slippage_bps = max_acceptable_slippage_bps
        self.min_liquidity_ratio = min_liquidity_ratio
        
        self.slippage_history: List[Dict] = []
        self.avg_slippage = 0.0
        
        logger.info(
            "SlippageAgent initialized: max_slippage=%.1f bps, min_liquidity_ratio=%.2f",
            max_acceptable_slippage_bps, min_liquidity_ratio
        )
    
    def analyze_order_book(
        self,
        venue: str,
        asset: str,
        bids: List[tuple[float, float]],
        asks: List[tuple[float, float]]
    ) -> OrderBookSnapshot:
        """Analyze order book and create snapshot."""
        mid_price = (asks[0][0] + bids[0][0]) / 2
        spread_bps = ((asks[0][0] - bids[0][0]) / mid_price) * 10000
        
        snapshot = OrderBookSnapshot(
            venue=venue,
            asset=asset,
            timestamp=time.time(),
            bids=bids,
            asks=asks,
            mid_price=mid_price,
            spread_bps=spread_bps
        )
        
        return snapshot
    
    def recommend_execution_strategy(
        self,
        order_book: OrderBookSnapshot,
        order_size_usd: float,
        side: str,
        urgency: str = "normal"  # 'urgent', 'normal', 'patient'
    ) -> ExecutionStrategy:
        """
        Recommend optimal execution strategy based on order book and urgency.
        """
        # Calculate market impact for full order
        full_impact = order_book.calculate_market_impact(order_size_usd, side)
        
        # Calculate available liquidity
        levels = order_book.asks if side == "buy" else order_book.bids
        total_liquidity = sum(price * size for price, size in levels[:10])
        liquidity_ratio = order_size_usd / total_liquidity if total_liquidity > 0 else 1.0
        
        # Determine strategy based on impact and urgency
        if urgency == "urgent" or full_impact <= self.max_acceptable_slippage_bps:
            # Market order acceptable
            return ExecutionStrategy(
                strategy_type="market",
                order_size=order_size_usd,
                num_chunks=1,
                time_interval_seconds=None,
                limit_price=None,
                expected_slippage_bps=full_impact,
                confidence=0.95
            )
        
        elif liquidity_ratio > 0.5:
            # Large order relative to liquidity - use TWAP
            num_chunks = max(5, int(liquidity_ratio * 10))
            time_interval = 60.0  # 1 minute between chunks
            
            # Estimate TWAP slippage (lower than market)
            twap_slippage = full_impact * 0.4  # Rough estimate
            
            return ExecutionStrategy(
                strategy_type="twap",
                order_size=order_size_usd,
                num_chunks=num_chunks,
                time_interval_seconds=time_interval,
                limit_price=None,
                expected_slippage_bps=twap_slippage,
                confidence=0.85
            )
        
        elif urgency == "patient":
            # Use limit order at mid price
            limit_price = order_book.mid_price
            
            return ExecutionStrategy(
                strategy_type="limit",
                order_size=order_size_usd,
                num_chunks=1,
                time_interval_seconds=None,
                limit_price=limit_price,
                expected_slippage_bps=0.0,  # No slippage if filled
                confidence=0.70  # Lower confidence - may not fill
            )
        
        else:
            # Default to iceberg order
            num_chunks = 3
            
            return ExecutionStrategy(
                strategy_type="iceberg",
                order_size=order_size_usd,
                num_chunks=num_chunks,
                time_interval_seconds=30.0,
                limit_price=None,
                expected_slippage_bps=full_impact * 0.6,
                confidence=0.80
            )
    
    def track_execution(
        self,
        expected_slippage: float,
        actual_slippage: float,
        order_size: float
    ):
        """Track execution performance."""
        self.slippage_history.append({
            "timestamp": time.time(),
            "expected_slippage": expected_slippage,
            "actual_slippage": actual_slippage,
            "order_size": order_size,
            "slippage_error": abs(actual_slippage - expected_slippage)
        })
        
        # Update rolling average
        recent = self.slippage_history[-100:]
        self.avg_slippage = sum(h["actual_slippage"] for h in recent) / len(recent)
        
        logger.info(
            "Execution tracked: expected=%.2f bps, actual=%.2f bps, size=$%.2f",
            expected_slippage, actual_slippage, order_size
        )
    
    def get_performance_stats(self) -> Dict:
        """Get slippage agent performance statistics."""
        if not self.slippage_history:
            return {
                "total_executions": 0,
                "avg_slippage_bps": 0.0,
                "avg_slippage_error_bps": 0.0
            }
        
        recent = self.slippage_history[-100:]
        
        return {
            "total_executions": len(self.slippage_history),
            "avg_slippage_bps": sum(h["actual_slippage"] for h in recent) / len(recent),
            "avg_slippage_error_bps": sum(h["slippage_error"] for h in recent) / len(recent),
            "max_slippage_bps": max(h["actual_slippage"] for h in recent),
            "min_slippage_bps": min(h["actual_slippage"] for h in recent)
        }


# Global singleton
_slippage_agent: Optional[SlippageAgent] = None
_slippage_agent_lock = threading.Lock()


def get_slippage_agent() -> SlippageAgent:
    """Get or create slippage agent singleton."""
    global _slippage_agent
    if _slippage_agent is None:
        with _slippage_agent_lock:
            if _slippage_agent is None:
                _slippage_agent = SlippageAgent()
    return _slippage_agent
