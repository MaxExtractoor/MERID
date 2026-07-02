"""
Trade trace infrastructure for Kalshi 15m crypto feed lag calibration.

This module provides a unified trace per trade that captures:
- spot_time, kalshi_book_time, fill_time, settlement_time
- spot_price_at_signal, kalshi_mid_at_signal, fill_price, settlement_price
- post_fill_move (settlement_price - spot_price_at_signal)
- All metadata needed to compute lag distributions, slippage curves, and edge realization

This enables empirical calibration of latency buffers from actual execution history.
"""
from __future__ import annotations

import json
import time
import threading
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from pathlib import Path

from utils.logger import get_logger

logger = get_logger(__name__)

# Global trace cache for in-progress trades (trace_id -> TradeTrace)
# This allows cross-module access to update traces from different parts of the system
_trade_trace_cache: Dict[str, TradeTrace] = {}
_trace_lock = threading.Lock()


def get_trace(trace_id: str) -> Optional[TradeTrace]:
    """Get a TradeTrace by ID from the global cache."""
    with _trace_lock:
        return _trade_trace_cache.get(trace_id)


def update_trace(trace_id: str, **kwargs) -> bool:
    """Update a TradeTrace with new field values.
    
    Args:
        trace_id: Trace ID to update
        **kwargs: Field names and values to update
    
    Returns:
        True if trace was found and updated, False otherwise
    """
    with _trace_lock:
        trace = _trade_trace_cache.get(trace_id)
        if trace is None:
            logger.warning("[TRACE-UPDATE] trace_id=%s not found in cache", trace_id)
            return False
        
        for key, value in kwargs.items():
            if hasattr(trace, key):
                setattr(trace, key, value)
            else:
                logger.warning("[TRACE-UPDATE] trace_id=%s has no field %s", trace_id, key)
        
        return True


def finalize_trace(trace_id: str) -> Optional[TradeTrace]:
    """
    Finalize a trace by computing latencies, slippage, and post-fill move,
    then logging it to the trace logger and removing from cache.
    
    Args:
        trace_id: Trace ID to finalize
    
    Returns:
        The finalized TradeTrace if found, None otherwise
    """
    with _trace_lock:
        trace = _trade_trace_cache.get(trace_id)
        if trace is None:
            logger.warning("[TRACE-FINALIZE] trace_id=%s not found in cache", trace_id)
            return None
        
        # Compute latencies, slippage, post-fill move
        latencies = trace.compute_latencies()
        slippage = trace.compute_slippage()
        trace.compute_post_fill_move()
        
        # P1: Record monitoring metrics if Prometheus is available
        try:
            from prometheus_client import Histogram
            # Get metrics from agent_grid_15m if available
            try:
                from merid.prediction.agent_grid_15m import signal_to_fill_latency_ms, slippage_ticks
                # Record signal to fill latency
                if "signal_to_fill_sec" in latencies and latencies["signal_to_fill_sec"] is not None:
                    latency_ms = latencies["signal_to_fill_sec"] * 1000
                    signal_to_fill_latency_ms.labels(symbol=trace.symbol).observe(latency_ms)
                
                # Record slippage with size bucket
                if slippage is not None:
                    # Determine size bucket
                    if trace.size <= 5:
                        size_bucket = "small"
                    elif trace.size <= 20:
                        size_bucket = "medium"
                    else:
                        size_bucket = "large"
                    slippage_ticks.labels(symbol=trace.symbol, size_bucket=size_bucket).observe(abs(slippage) * 100)  # Convert prob to cents
            except ImportError:
                # Metrics not available - skip
                pass
        except Exception as e:
            logger.debug("[TRACE-FINALIZE] Failed to record metrics: %s", e)
        
        # Log to trace logger
        trace_logger = get_trace_logger()
        trace_logger.log_trace(trace)
        
        # Remove from cache
        del _trade_trace_cache[trace_id]
        
        logger.info(
            "[TRACE-FINALIZED] trace_id=%s symbol=%s contract_id=%s fill_price=%.2f settlement_price=%.2f post_fill_move=%.2f",
            trace_id, trace.symbol, trace.contract_id, trace.fill_price, trace.settlement_price, trace.post_fill_move
        )
        
        return trace


def find_trace_by_contract_id(contract_id: str) -> Optional[TradeTrace]:
    """Find a trace by contract_id (market_id).
    
    This is used by the settlement listener to find the trace to finalize.
    
    Args:
        contract_id: The Kalshi market ID (contract_id)
    
    Returns:
        The TradeTrace if found, None otherwise
    """
    with _trace_lock:
        for trace in _trade_trace_cache.values():
            if trace.contract_id == contract_id:
                return trace
    return None


@dataclass
class TradeTrace:
    """
    Unified trace for a single trade from signal to settlement.
    
    Captures all timestamps and prices needed to separate signal quality
    from timing issues (feed lag, execution latency, slippage).
    """
    # Identifiers
    trace_id: str  # Unique trace ID (UUID or timestamp-based)
    symbol: str  # Asset symbol (BTC, ETH, etc.)
    contract_id: str  # Kalshi market ID
    side: str  # YES/NO or UP/DOWN
    order_id: Optional[str] = None  # Kalshi order ID
    
    # Timestamps (all UTC Unix timestamps in seconds)
    spot_time: Optional[float] = None  # When spot price was captured
    kalshi_book_time: Optional[float] = None  # When Kalshi orderbook snapshot was taken
    signal_time: Optional[float] = None  # When signal was generated
    order_submit_time: Optional[float] = None  # When order was submitted to Kalshi
    fill_time: Optional[float] = None  # When order was filled
    settlement_time: Optional[float] = None  # When settlement was known
    
    # Prices
    spot_price_at_signal: Optional[float] = None  # Spot price when signal generated
    kalshi_mid_at_signal: Optional[float] = None  # Kalshi mid price when signal generated
    fill_price: Optional[float] = None  # Actual fill price
    settlement_price: Optional[float] = None  # 60-second RTI average at settlement
    
    # Order details
    size: int = 1  # Order size in contracts
    order_side: str = "taker"  # "maker" or "taker"
    
    # Edge metrics (for calibration)
    raw_edge: Optional[float] = None  # Raw edge at signal time
    latency_buffer: Optional[float] = None  # Computed latency buffer
    edge_passes_latency_buffer: Optional[bool] = None  # Whether edge survived buffer
    
    # Post-fill analysis
    post_fill_move: Optional[float] = None  # settlement_price - spot_price_at_signal
    
    # Metadata
    source: Optional[str] = None  # Spot feed source
    metadata: Optional[Dict[str, Any]] = None  # Additional context
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        d = asdict(self)
        # Convert None to empty string for JSON compatibility
        return {k: (v if v is not None else "") for k, v in d.items()}
    
    def compute_latencies(self) -> Dict[str, Optional[float]]:
        """Compute latency metrics from timestamps."""
        latencies = {}
        if self.spot_time and self.signal_time:
            latencies["spot_to_signal_sec"] = self.signal_time - self.spot_time
        if self.signal_time and self.order_submit_time:
            latencies["signal_to_submit_sec"] = self.order_submit_time - self.signal_time
        if self.order_submit_time and self.fill_time:
            latencies["submit_to_fill_sec"] = self.fill_time - self.order_submit_time
        if self.signal_time and self.fill_time:
            latencies["signal_to_fill_sec"] = self.fill_time - self.signal_time
        if self.fill_time and self.settlement_time:
            latencies["fill_to_settlement_sec"] = self.settlement_time - self.fill_time
        return latencies
    
    def compute_slippage(self) -> Optional[float]:
        """Compute slippage = fill_price - kalshi_mid_at_signal."""
        if self.fill_price is not None and self.kalshi_mid_at_signal is not None:
            return self.fill_price - self.kalshi_mid_at_signal
        return None
    
    def compute_post_fill_move(self) -> Optional[float]:
        """Compute post-fill move = settlement_price - spot_price_at_signal."""
        if self.settlement_price is not None and self.spot_price_at_signal is not None:
            self.post_fill_move = self.settlement_price - self.spot_price_at_signal
            return self.post_fill_move
        return None


class TradeTraceLogger:
    """
    Logger for trade traces to JSONL file for offline calibration.
    
    Writes one JSON line per trade with all trace data.
    """
    
    def __init__(self, log_path: Optional[str] = None):
        """
        Initialize trade trace logger.
        
        Args:
            log_path: Path to JSONL log file. If None, uses default.
        """
        if log_path is None:
            # Default: data/kalshi_trade_trace.jsonl
            log_path = "data/kalshi_trade_trace.jsonl"
        
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        
        logger.info("[TRACE-LOGGER] Initialized with log_path=%s", self.log_path)
    
    def log_trace(self, trace: TradeTrace) -> None:
        """Log a trade trace to JSONL file."""
        try:
            # Compute post-fill move if not already computed
            if trace.post_fill_move is None:
                trace.compute_post_fill_move()
            
            # Convert to dict and write as JSON line
            trace_dict = trace.to_dict()
            json_line = json.dumps(trace_dict)
            
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json_line + "\n")
            
            logger.debug(
                "[TRACE-LOGGER] Logged trace_id=%s symbol=%s contract_id=%s fill_price=%.2f settlement_price=%.2f",
                trace.trace_id, trace.symbol, trace.contract_id, trace.fill_price, trace.settlement_price
            )
        except Exception as e:
            logger.error("[TRACE-LOGGER] Failed to log trace_id=%s: %s", trace.trace_id, e, exc_info=True)
    
    def read_traces(self, limit: Optional[int] = None) -> list[Dict[str, Any]]:
        """
        Read trade traces from log file.
        
        Args:
            limit: Maximum number of traces to read (most recent first). If None, read all.
        
        Returns:
            List of trace dictionaries.
        """
        traces = []
        if not self.log_path.exists():
            logger.warning("[TRACE-LOGGER] Log file does not exist: %s", self.log_path)
            return traces
        
        try:
            with open(self.log_path, "r", encoding="utf-8") as f:
                for line in f:
                    if limit is not None and len(traces) >= limit:
                        break
                    line = line.strip()
                    if line:
                        trace_dict = json.loads(line)
                        traces.append(trace_dict)
            
            # Reverse to get most recent first
            traces.reverse()
            logger.info("[TRACE-LOGGER] Read %d traces from %s", len(traces), self.log_path)
        except Exception as e:
            logger.error("[TRACE-LOGGER] Failed to read traces from %s: %s", self.log_path, e, exc_info=True)
        
        return traces


# Singleton instance
_trace_logger: Optional[TradeTraceLogger] = None


def get_trace_logger() -> TradeTraceLogger:
    """Get singleton trade trace logger instance."""
    global _trace_logger
    if _trace_logger is None:
        _trace_logger = TradeTraceLogger()
    return _trace_logger


def create_trace_id() -> str:
    """Create a unique trace ID from timestamp."""
    return f"trace_{int(time.time() * 1000)}"


def log_trade_trace(trace: TradeTrace) -> None:
    """Convenience function to log a trade trace."""
    get_trace_logger().log_trace(trace)
