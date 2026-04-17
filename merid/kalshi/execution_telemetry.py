# merid/kalshi/execution_telemetry.py
"""Kalshi execution telemetry: latency and slippage tracking."""

import time
import statistics
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("merid.kalshi.execution_telemetry")


@dataclass
class OrderTelemetry:
    """Telemetry data for a single order."""
    order_id: str
    agent_id: str
    product: str  # e.g. "btc_15m"
    submit_ts: float
    ack_ts: Optional[float] = None
    fill_ts: Optional[float] = None
    submit_mid_price: Optional[float] = None
    fill_price: Optional[float] = None
    size_contracts: int = 0


class ExecutionTelemetryTracker:
    """Tracks execution latency and slippage metrics."""
    
    def __init__(self, window_size: int = 1000):
        self._window_size = window_size
        self._orders: Dict[str, OrderTelemetry] = {}
        self._latency_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=window_size))
        self._slippage_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=window_size))
    
    def record_submit(self, order_id: str, agent_id: str, product: str, 
                     mid_price: float, size_contracts: int) -> None:
        """Record order submission."""
        self._orders[order_id] = OrderTelemetry(
            order_id=order_id,
            agent_id=agent_id,
            product=product,
            submit_ts=time.time(),
            submit_mid_price=mid_price,
            size_contracts=size_contracts,
        )
    
    def record_ack(self, order_id: str) -> None:
        """Record order acknowledgment."""
        if order_id in self._orders:
            self._orders[order_id].ack_ts = time.time()
            self._update_latency(self._orders[order_id])
    
    def record_fill(self, order_id: str, fill_price: float) -> None:
        """Record order fill."""
        if order_id in self._orders:
            order = self._orders[order_id]
            order.fill_ts = time.time()
            order.fill_price = fill_price
            self._update_latency(order)
            self._update_slippage(order)
    
    def _update_latency(self, order: OrderTelemetry) -> None:
        """Update latency metrics for an order."""
        if order.ack_ts and order.submit_ts:
            submit_ack_latency = (order.ack_ts - order.submit_ts) * 1000  # ms
            self._latency_history[f"{order.product}_submit_ack"].append(submit_ack_latency)
        
        if order.fill_ts and order.submit_ts:
            submit_fill_latency = (order.fill_ts - order.submit_ts) * 1000  # ms
            self._latency_history[f"{order.product}_submit_fill"].append(submit_fill_latency)
    
    def _update_slippage(self, order: OrderTelemetry) -> None:
        """Update slippage metrics for an order."""
        if order.fill_price and order.submit_mid_price:
            # Slippage in cents relative to mid price
            slippage_cents = order.fill_price - order.submit_mid_price
            self._slippage_history[order.product].append(slippage_cents)
    
    def get_metrics(self, product: str) -> Dict[str, float]:
        """Get latency and slippage metrics for a product."""
        metrics = {}
        
        # Latency metrics
        submit_ack_key = f"{product}_submit_ack"
        submit_fill_key = f"{product}_submit_fill"
        
        if submit_ack_key in self._latency_history and self._latency_history[submit_ack_key]:
            latencies = list(self._latency_history[submit_ack_key])
            metrics[f"{product}_submit_ack_p50"] = statistics.median(latencies)
            metrics[f"{product}_submit_ack_p90"] = self._percentile(latencies, 0.9)
        
        if submit_fill_key in self._latency_history and self._latency_history[submit_fill_key]:
            latencies = list(self._latency_history[submit_fill_key])
            metrics[f"{product}_submit_fill_p50"] = statistics.median(latencies)
            metrics[f"{product}_submit_fill_p90"] = self._percentile(latencies, 0.9)
        
        # Slippage metrics
        if product in self._slippage_history and self._slippage_history[product]:
            slippages = list(self._slippage_history[product])
            metrics[f"{product}_avg_slippage_cents"] = statistics.mean(slippages)
            metrics[f"{product}_slippage_std"] = statistics.stdev(slippages) if len(slippages) > 1 else 0.0
        
        return metrics
    
    def _percentile(self, data: List[float], p: float) -> float:
        """Calculate percentile."""
        if not data:
            return 0.0
        sorted_data = sorted(data)
        index = int(p * len(sorted_data))
        return sorted_data[min(index, len(sorted_data) - 1)]
    
    def get_all_metrics(self) -> Dict[str, Dict[str, float]]:
        """Get metrics for all tracked products."""
        products = set()
        for key in self._latency_history:
            product = key.split("_")[0]
            products.add(product)
        for product in self._slippage_history:
            products.add(product)
        
        return {product: self.get_metrics(product) for product in products}


# Singleton
_tracker: Optional[ExecutionTelemetryTracker] = None
_tracker_lock = None  # Will be set when needed


def get_execution_telemetry_tracker() -> ExecutionTelemetryTracker:
    """Return the execution telemetry tracker singleton."""
    global _tracker, _tracker_lock
    if _tracker is None:
        if _tracker_lock is None:
            import threading
            _tracker_lock = threading.Lock()
        with _tracker_lock:
            if _tracker is None:
                _tracker = ExecutionTelemetryTracker()
    return _tracker
