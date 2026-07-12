"""
Production Rejection Monitor for 15M Kalshi Crypto Trading System

This module integrates rejection tracking into the production pipeline with minimal overhead.
It provides structured logging of all rejection events for post-hoc analysis and real-time monitoring.

Key Features:
- Zero-overhead rejection capture (async logging)
- Structured event format compatible with rejection_analyzer.py
- Per-asset, per-category rejection tracking
- Real-time rejection rate monitoring
- Integration with existing logger infrastructure
- Configurable sampling rates for high-frequency systems

Usage in production code:
    from merid.monitoring.rejection_monitor import RejectionMonitor, get_rejection_monitor
    
    monitor = get_rejection_monitor()
    monitor.log_rejection(
        asset="BTC",
        category="time_window",
        reason="too early: >15.0min",
        minutes_to_expiry=16.5,
        additional_context={"market_id": "KXBTC15M-..."}
    )
"""

import json
import asyncio
import threading
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict, deque
from typing import Dict, Optional, Any
from dataclasses import dataclass, asdict
import queue

try:
    from utils.logger import get_logger
    logger = get_logger("merid.monitoring.rejection_monitor")
except ImportError:
    import logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("merid.monitoring.rejection_monitor")


@dataclass
class RejectionEvent:
    """Structured rejection event for production logging."""
    timestamp: str
    asset: str
    rejection_category: str
    rejection_reason: str
    market_id: Optional[str] = None
    spot_price: Optional[float] = None
    yes_price_cents: Optional[int] = None
    no_price_cents: Optional[int] = None
    minutes_to_expiry: Optional[float] = None
    velocity: Optional[float] = None
    edge_cents: Optional[float] = None
    spread_cents: Optional[float] = None
    threshold_value: Optional[float] = None
    actual_value: Optional[float] = None
    session_active: Optional[bool] = None
    trend_aligned: Optional[bool] = None
    additional_context: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict:
        return asdict(self)


class RejectionMonitor:
    """
    Production rejection monitor with async logging and real-time metrics.
    
    Designed for minimal overhead - uses background thread for file I/O
    and in-memory counters for real-time metrics.
    """
    
    def __init__(
        self,
        output_dir: str = "data/rejections",
        max_memory_events: int = 10000,
        enable_file_logging: bool = True,
        sampling_rate: float = 1.0,  # 1.0 = log all, 0.1 = log 10%
    ):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.max_memory_events = max_memory_events
        self.enable_file_logging = enable_file_logging
        self.sampling_rate = sampling_rate
        
        # In-memory event buffer (circular buffer)
        self._event_buffer: deque = deque(maxlen=max_memory_events)
        
        # Real-time counters
        self._counters: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self._lock = threading.Lock()
        
        # Async logging queue
        self._log_queue: queue.Queue = queue.Queue(maxsize=10000)
        self._logging_thread: Optional[threading.Thread] = None
        self._running = False
        
        # Current log file
        self._current_log_file = self._get_log_file_path()
        
        logger.info(
            f"[REJECTION-MONITOR-INIT] output_dir={self.output_dir} "
            f"max_memory_events={max_memory_events} enable_file_logging={enable_file_logging} "
            f"sampling_rate={sampling_rate}"
        )
    
    def _get_log_file_path(self) -> Path:
        """Generate log file path with current date."""
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return self.output_dir / f"rejections_{date_str}.jsonl"
    
    def _logging_worker(self):
        """Background thread for async file logging."""
        while self._running or not self._log_queue.empty():
            try:
                event_dict = self._log_queue.get(timeout=1.0)
                if event_dict is None:  # Poison pill
                    break
                
                # Rotate log file if date changed
                current_file = self._get_log_file_path()
                if current_file != self._current_log_file:
                    self._current_log_file = current_file
                
                # Write to file
                with open(self._current_log_file, 'a', encoding='utf-8') as f:
                    f.write(json.dumps(event_dict) + '\n')
                
                self._log_queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"[REJECTION-MONITOR-LOGGING-ERROR] {e}")
    
    def start(self):
        """Start the background logging thread."""
        if self._running:
            return
        
        self._running = True
        self._logging_thread = threading.Thread(target=self._logging_worker, daemon=True)
        self._logging_thread.start()
        logger.info("[REJECTION-MONITOR-START] Background logging thread started")
    
    def stop(self):
        """Stop the background logging thread."""
        if not self._running:
            return
        
        self._running = False
        self._log_queue.put(None)  # Poison pill
        
        if self._logging_thread:
            self._logging_thread.join(timeout=5.0)
        
        logger.info("[REJECTION-MONITOR-STOP] Background logging thread stopped")
    
    def log_rejection(
        self,
        asset: str,
        category: str,
        reason: str,
        market_id: Optional[str] = None,
        spot_price: Optional[float] = None,
        yes_price_cents: Optional[int] = None,
        no_price_cents: Optional[int] = None,
        minutes_to_expiry: Optional[float] = None,
        velocity: Optional[float] = None,
        edge_cents: Optional[float] = None,
        spread_cents: Optional[float] = None,
        threshold_value: Optional[float] = None,
        actual_value: Optional[float] = None,
        session_active: Optional[bool] = None,
        trend_aligned: Optional[bool] = None,
        additional_context: Optional[Dict[str, Any]] = None,
    ):
        """
        Log a rejection event.
        
        This method is designed for minimal overhead:
        - Sampling check first (fast path)
        - In-memory counter update (thread-safe)
        - Queue put for async file I/O (non-blocking)
        
        Args:
            asset: Asset symbol (BTC, ETH, SOL, XRP, DOGE)
            category: Rejection category (time_window, price_range, etc.)
            reason: Human-readable rejection reason
            market_id: Kalshi market ID
            spot_price: Current spot price
            yes_price_cents: YES contract price in cents
            no_price_cents: NO contract price in cents
            minutes_to_expiry: Time to expiry in minutes
            velocity: Velocity value
            edge_cents: Edge value in cents
            spread_cents: Spread value in cents
            threshold_value: Threshold that was exceeded
            actual_value: Actual value that exceeded threshold
            session_active: Whether trading session was active
            trend_aligned: Whether trends were aligned
            additional_context: Additional context dict
        """
        # Sampling check (fast path)
        if self.sampling_rate < 1.0:
            import random
            if random.random() > self.sampling_rate:
                return
        
        # Create event
        event = RejectionEvent(
            timestamp=datetime.now(timezone.utc).isoformat(),
            asset=asset,
            rejection_category=category,
            rejection_reason=reason,
            market_id=market_id,
            spot_price=spot_price,
            yes_price_cents=yes_price_cents,
            no_price_cents=no_price_cents,
            minutes_to_expiry=minutes_to_expiry,
            velocity=velocity,
            edge_cents=edge_cents,
            spread_cents=spread_cents,
            threshold_value=threshold_value,
            actual_value=actual_value,
            session_active=session_active,
            trend_aligned=trend_aligned,
            additional_context=additional_context,
        )
        
        # Update in-memory counters (thread-safe)
        with self._lock:
            self._event_buffer.append(event)
            self._counters[asset][category] += 1
        
        # Queue for async file logging (non-blocking)
        if self.enable_file_logging:
            try:
                self._log_queue.put_nowait(event.to_dict())
            except queue.Full:
                logger.warning("[REJECTION-MONITOR-QUEUE-FULL] Dropping rejection event (queue full)")
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get real-time rejection metrics."""
        with self._lock:
            total_rejections = len(self._event_buffer)
            
            # Per-asset totals
            asset_totals = {}
            for asset, categories in self._counters.items():
                asset_totals[asset] = sum(categories.values())
            
            # Per-category totals
            category_totals = defaultdict(int)
            for asset_categories in self._counters.values():
                for category, count in asset_categories.items():
                    category_totals[category] += count
            
            return {
                "total_rejections": total_rejections,
                "buffer_utilization": total_rejections / self.max_memory_events,
                "by_asset": asset_totals,
                "by_category": dict(category_totals),
                "current_log_file": str(self._current_log_file),
                "sampling_rate": self.sampling_rate,
            }
    
    def get_recent_events(self, limit: int = 100) -> list:
        """Get recent rejection events from memory buffer."""
        with self._lock:
            events = list(self._event_buffer)[-limit:]
            return [e.to_dict() for e in events]
    
    def reset_counters(self):
        """Reset in-memory counters (useful for testing or periodic resets)."""
        with self._lock:
            self._counters.clear()
            logger.info("[REJECTION-MONITOR-RESET] Counters reset")


# Global singleton instance
_global_monitor: Optional[RejectionMonitor] = None
_monitor_lock = threading.Lock()


def get_rejection_monitor(
    output_dir: str = "data/rejections",
    max_memory_events: int = 10000,
    enable_file_logging: bool = True,
    sampling_rate: float = 1.0,
) -> RejectionMonitor:
    """
    Get or create the global rejection monitor singleton.
    
    Args:
        output_dir: Directory for rejection log files
        max_memory_events: Maximum events to keep in memory
        enable_file_logging: Whether to enable file logging
        sampling_rate: Sampling rate (1.0 = all, 0.1 = 10%)
    
    Returns:
        RejectionMonitor instance
    """
    global _global_monitor
    
    with _monitor_lock:
        if _global_monitor is None:
            _global_monitor = RejectionMonitor(
                output_dir=output_dir,
                max_memory_events=max_memory_events,
                enable_file_logging=enable_file_logging,
                sampling_rate=sampling_rate,
            )
            _global_monitor.start()
        
        return _global_monitor


def shutdown_rejection_monitor():
    """Shutdown the global rejection monitor."""
    global _global_monitor
    
    with _monitor_lock:
        if _global_monitor is not None:
            _global_monitor.stop()
            _global_monitor = None


# Convenience functions for common rejection patterns
def log_time_window_rejection(
    asset: str,
    minutes_to_expiry: float,
    reason: str,
    market_id: Optional[str] = None,
):
    """Log a time window rejection."""
    monitor = get_rejection_monitor()
    monitor.log_rejection(
        asset=asset,
        category="time_window",
        reason=reason,
        market_id=market_id,
        minutes_to_expiry=minutes_to_expiry,
    )


def log_price_range_rejection(
    asset: str,
    yes_price_cents: int,
    no_price_cents: int,
    reason: str,
    market_id: Optional[str] = None,
):
    """Log a price range rejection."""
    monitor = get_rejection_monitor()
    monitor.log_rejection(
        asset=asset,
        category="price_range",
        reason=reason,
        market_id=market_id,
        yes_price_cents=yes_price_cents,
        no_price_cents=no_price_cents,
    )


def log_trend_alignment_rejection(
    asset: str,
    reason: str,
    market_id: Optional[str] = None,
):
    """Log a trend alignment rejection."""
    monitor = get_rejection_monitor()
    monitor.log_rejection(
        asset=asset,
        category="trend_alignment",
        reason=reason,
        market_id=market_id,
        trend_aligned=False,
    )


def log_edge_check_rejection(
    asset: str,
    reason: str,
    edge_cents: Optional[float] = None,
    spread_cents: Optional[float] = None,
    threshold_value: Optional[float] = None,
    actual_value: Optional[float] = None,
    market_id: Optional[str] = None,
):
    """Log an edge check rejection."""
    monitor = get_rejection_monitor()
    monitor.log_rejection(
        asset=asset,
        category="edge_insufficient",
        reason=reason,
        market_id=market_id,
        edge_cents=edge_cents,
        spread_cents=spread_cents,
        threshold_value=threshold_value,
        actual_value=actual_value,
    )
