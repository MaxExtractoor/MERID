"""
Buffer calibration from trade trace data.

This module reads trade traces and computes empirical distributions for:
- Spot → Kalshi lead/lag
- Signal → fill latency
- Slippage by size and spread regime
- Overshoot / mean-reversion before settlement

These distributions are used to calibrate the latency buffer in unified_edge.py.
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
import statistics

from utils.logger import get_logger
from merid.prediction.trade_trace import TradeTrace, get_trace_logger

logger = get_logger(__name__)


@dataclass
class LagDistribution:
    """Distribution of latency metrics."""
    mean_sec: float
    median_sec: float
    p50_sec: float
    p75_sec: float
    p90_sec: float
    p95_sec: float
    p99_sec: float
    std_sec: float
    count: int


@dataclass
class SlippageCurve:
    """Slippage by size bin and spread regime."""
    size_bin: str  # e.g., "1-5", "5-10", "10+"
    spread_regime: str  # e.g., "tight" (<2c), "normal" (2-5c), "wide" (>5c)
    mean_slippage_cents: float
    median_slippage_cents: float
    p90_slippage_cents: float
    count: int


@dataclass
class EdgeRealization:
    """Edge realization metrics."""
    raw_edge_mean: float
    raw_edge_median: float
    edge_minus_buffer_mean: float
    edge_minus_buffer_median: float
    positive_realization_rate: float  # % of trades where edge - buffer > 0 at settlement
    count: int


@dataclass
class CalibrationResult:
    """Full calibration result."""
    timestamp: str  # ISO timestamp
    asset: str
    lag_distributions: Dict[str, LagDistribution]  # metric_name -> distribution
    slippage_curves: List[SlippageCurve]
    edge_realization: EdgeRealization
    recommended_buffer_ticks: float  # Recommended buffer in ticks
    recommended_buffer_prob: float  # Recommended buffer in probability space


def compute_percentiles(values: List[float], percentiles: List[float]) -> List[float]:
    """Compute percentiles from sorted values."""
    if not values:
        return [0.0] * len(percentiles)
    sorted_values = sorted(values)
    n = len(sorted_values)
    results = []
    for p in percentiles:
        idx = int(p * n / 100)
        idx = min(idx, n - 1)
        results.append(sorted_values[idx])
    return results


def compute_lag_distributions(traces: List[Dict[str, Any]]) -> Dict[str, LagDistribution]:
    """Compute lag distributions from trade traces."""
    lag_metrics = defaultdict(list)
    
    for trace in traces:
        # Compute latencies
        spot_time = trace.get("spot_time")
        signal_time = trace.get("signal_time")
        order_submit_time = trace.get("order_submit_time")
        fill_time = trace.get("fill_time")
        settlement_time = trace.get("settlement_time")
        
        if spot_time and signal_time:
            lag_metrics["spot_to_signal_sec"].append(signal_time - spot_time)
        if signal_time and order_submit_time:
            lag_metrics["signal_to_submit_sec"].append(order_submit_time - signal_time)
        if order_submit_time and fill_time:
            lag_metrics["submit_to_fill_sec"].append(fill_time - order_submit_time)
        if signal_time and fill_time:
            lag_metrics["signal_to_fill_sec"].append(fill_time - signal_time)
        if fill_time and settlement_time:
            lag_metrics["fill_to_settlement_sec"].append(settlement_time - fill_time)
    
    distributions = {}
    for metric_name, values in lag_metrics.items():
        if not values:
            continue
        
        mean_val = statistics.mean(values)
        median_val = statistics.median(values)
        std_val = statistics.stdev(values) if len(values) > 1 else 0.0
        
        p50, p75, p90, p95, p99 = compute_percentiles(values, [50, 75, 90, 95, 99])
        
        distributions[metric_name] = LagDistribution(
            mean_sec=mean_val,
            median_sec=median_val,
            p50_sec=p50,
            p75_sec=p75,
            p90_sec=p90,
            p95_sec=p95,
            p99_sec=p99,
            std_sec=std_val,
            count=len(values)
        )
        
        logger.debug(
            "[LAG-DIST] metric=%s mean=%.3f median=%.3f p90=%.3f p95=%.3f count=%d",
            metric_name, mean_val, median_val, p90, p95, len(values)
        )
    
    return distributions


def compute_slippage_curves(traces: List[Dict[str, Any]]) -> List[SlippageCurve]:
    """Compute slippage by size bin and spread regime."""
    # Group by size bin and spread regime
    slippage_groups = defaultdict(list)
    
    for trace in traces:
        size = trace.get("size", 1)
        kalshi_mid = trace.get("kalshi_mid_at_signal")
        fill_price = trace.get("fill_price")
        
        if kalshi_mid is None or fill_price is None:
            continue
        
        # Compute slippage in cents
        slippage_cents = fill_price - kalshi_mid
        
        # Size bin
        if size <= 5:
            size_bin = "1-5"
        elif size <= 10:
            size_bin = "5-10"
        else:
            size_bin = "10+"
        
        # Spread regime (we don't have spread in trace yet, use placeholder)
        # TODO: Add spread to TradeTrace and use it here
        spread_regime = "normal"  # Placeholder
        
        key = (size_bin, spread_regime)
        slippage_groups[key].append(slippage_cents)
    
    curves = []
    for (size_bin, spread_regime), slippage_values in slippage_groups.items():
        if not slippage_values:
            continue
        
        mean_slip = statistics.mean(slippage_values)
        median_slip = statistics.median(slippage_values)
        p90_slip = compute_percentiles(slippage_values, [90])[0]
        
        curves.append(SlippageCurve(
            size_bin=size_bin,
            spread_regime=spread_regime,
            mean_slippage_cents=mean_slip,
            median_slippage_cents=median_slip,
            p90_slippage_cents=p90_slip,
            count=len(slippage_values)
        ))
        
        logger.debug(
            "[SLIPPAGE-CURVE] size=%s spread=%s mean=%.2fc median=%.2fc p90=%.2fc count=%d",
            size_bin, spread_regime, mean_slip, median_slip, p90_slip, len(slippage_values)
        )
    
    return curves


def compute_edge_realization(traces: List[Dict[str, Any]]) -> EdgeRealization:
    """Compute edge realization metrics."""
    raw_edges = []
    edge_minus_buffers = []
    positive_realizations = 0
    total_count = 0
    
    for trace in traces:
        raw_edge = trace.get("raw_edge")
        latency_buffer = trace.get("latency_buffer")
        post_fill_move = trace.get("post_fill_move")
        
        if raw_edge is None:
            continue
        
        raw_edges.append(raw_edge)
        total_count += 1
        
        if latency_buffer is not None:
            edge_minus_buffers.append(raw_edge - latency_buffer)
        
        # Check if edge was positive at settlement
        # For YES contracts: positive post_fill_move means edge was realized
        # For NO contracts: negative post_fill_move means edge was realized
        # This is a simplified check - full analysis would compare to settlement outcome
        if post_fill_move is not None:
            # Simplified: if post_fill_move has same sign as raw_edge, count as positive
            if (raw_edge > 0 and post_fill_move > 0) or (raw_edge < 0 and post_fill_move < 0):
                positive_realizations += 1
    
    if not raw_edges:
        return EdgeRealization(
            raw_edge_mean=0.0,
            raw_edge_median=0.0,
            edge_minus_buffer_mean=0.0,
            edge_minus_buffer_median=0.0,
            positive_realization_rate=0.0,
            count=0
        )
    
    raw_edge_mean = statistics.mean(raw_edges)
    raw_edge_median = statistics.median(raw_edges)
    
    if edge_minus_buffers:
        edge_minus_buffer_mean = statistics.mean(edge_minus_buffers)
        edge_minus_buffer_median = statistics.median(edge_minus_buffers)
    else:
        edge_minus_buffer_mean = 0.0
        edge_minus_buffer_median = 0.0
    
    positive_rate = positive_realizations / total_count if total_count > 0 else 0.0
    
    logger.info(
        "[EDGE-REALIZATION] raw_mean=%.3f raw_median=%.3f buf_mean=%.3f buf_median=%.3f pos_rate=%.2f%% count=%d",
        raw_edge_mean, raw_edge_median, edge_minus_buffer_mean, edge_minus_buffer_median,
        positive_rate * 100, total_count
    )
    
    return EdgeRealization(
        raw_edge_mean=raw_edge_mean,
        raw_edge_median=raw_edge_median,
        edge_minus_buffer_mean=edge_minus_buffer_mean,
        edge_minus_buffer_median=edge_minus_buffer_median,
        positive_realization_rate=positive_rate,
        count=total_count
    )


def recommend_buffer(lag_distributions: Dict[str, LagDistribution], edge_realization: EdgeRealization) -> Tuple[float, float]:
    """
    Recommend buffer based on lag distributions and edge realization.
    
    Returns:
        (buffer_ticks, buffer_prob) - buffer in ticks and probability space
    """
    # Use p95 of signal_to_fill as base lag estimate
    signal_to_fill_dist = lag_distributions.get("signal_to_fill_sec")
    if signal_to_fill_dist:
        # Convert seconds to ticks (rough approximation: 1 tick per second of lag for crypto)
        # This is a heuristic - proper calibration would use historical price moves
        base_lag_ticks = signal_to_fill_dist.p95_sec
    else:
        base_lag_ticks = 1.0  # Default
    
    # Add safety margin based on edge realization
    # If positive realization rate is low, increase buffer
    if edge_realization.positive_realization_rate < 0.5:
        safety_multiplier = 1.5
    elif edge_realization.positive_realization_rate < 0.7:
        safety_multiplier = 1.2
    else:
        safety_multiplier = 1.0
    
    recommended_ticks = base_lag_ticks * safety_multiplier
    recommended_prob = recommended_ticks * 0.01  # Convert to probability space
    
    logger.info(
        "[BUFFER-RECOMMENDATION] base_lag=%.2f safety=%.2f recommended_ticks=%.2f recommended_prob=%.3f",
        base_lag_ticks, safety_multiplier, recommended_ticks, recommended_prob
    )
    
    return recommended_ticks, recommended_prob


def calibrate_buffers(asset: str, trace_limit: Optional[int] = None) -> CalibrationResult:
    """
    Calibrate buffers from trade trace data.
    
    Args:
        asset: Asset symbol (BTC, ETH, etc.)
        trace_limit: Maximum number of traces to read (most recent first)
    
    Returns:
        CalibrationResult with all metrics
    """
    logger.info("[CALIBRATION] Starting buffer calibration for asset=%s", asset)
    
    # Read trade traces
    trace_logger = get_trace_logger()
    traces = trace_logger.read_traces(limit=trace_limit)
    
    # Filter by asset
    asset_traces = [t for t in traces if t.get("symbol") == asset]
    logger.info("[CALIBRATION] Found %d traces for asset=%s", len(asset_traces), asset)
    
    if not asset_traces:
        logger.warning("[CALIBRATION] No traces found for asset=%s, using defaults", asset)
        return CalibrationResult(
            timestamp=datetime.now(timezone.utc).isoformat(),
            asset=asset,
            lag_distributions={},
            slippage_curves=[],
            edge_realization=EdgeRealization(0.0, 0.0, 0.0, 0.0, 0.0, 0),
            recommended_buffer_ticks=1.0,  # Default
            recommended_buffer_prob=0.01  # Default
        )
    
    # Compute metrics
    lag_distributions = compute_lag_distributions(asset_traces)
    slippage_curves = compute_slippage_curves(asset_traces)
    edge_realization = compute_edge_realization(asset_traces)
    recommended_ticks, recommended_prob = recommend_buffer(lag_distributions, edge_realization)
    
    result = CalibrationResult(
        timestamp=datetime.now(timezone.utc).isoformat(),
        asset=asset,
        lag_distributions=lag_distributions,
        slippage_curves=slippage_curves,
        edge_realization=edge_realization,
        recommended_buffer_ticks=recommended_ticks,
        recommended_buffer_prob=recommended_prob
    )
    
    logger.info(
        "[CALIBRATION] Complete for asset=%s: recommended_buffer=%.2f ticks (%.3f prob)",
        asset, recommended_ticks, recommended_prob
    )
    
    return result


def save_calibration_config(result: CalibrationResult, config_path: Optional[str] = None) -> None:
    """
    Save calibration result to config file.
    
    Args:
        result: CalibrationResult to save
        config_path: Path to config file. If None, uses default.
    """
    if config_path is None:
        config_path = "data/latency_buffer_config.json"
    
    config_file = Path(config_path)
    config_file.parent.mkdir(parents=True, exist_ok=True)
    
    # Convert to dict and save
    config_dict = {
        "timestamp": result.timestamp,
        "asset": result.asset,
        "recommended_buffer_ticks": result.recommended_buffer_ticks,
        "recommended_buffer_prob": result.recommended_buffer_prob,
        "lag_distributions": {k: asdict(v) for k, v in result.lag_distributions.items()},
        "slippage_curves": [asdict(c) for c in result.slippage_curves],
        "edge_realization": asdict(result.edge_realization)
    }
    
    with open(config_file, "w", encoding="utf-8") as f:
        json.dump(config_dict, f, indent=2)
    
    logger.info("[CALIBRATION] Saved config to %s", config_path)


def load_calibration_config(asset: str, config_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Load calibration config for an asset.
    
    Args:
        asset: Asset symbol
        config_path: Path to config file. If None, uses default.
    
    Returns:
        Config dict if found, None otherwise
    """
    if config_path is None:
        config_path = "data/latency_buffer_config.json"
    
    config_file = Path(config_path)
    if not config_file.exists():
        logger.debug("[CALIBRATION] Config file not found: %s", config_path)
        return None
    
    try:
        with open(config_file, "r", encoding="utf-8") as f:
            config = json.load(f)
        
        # Check if config matches asset
        if config.get("asset") == asset:
            logger.info("[CALIBRATION] Loaded config for asset=%s from %s", asset, config_path)
            return config
        else:
            logger.debug("[CALIBRATION] Config asset mismatch: expected %s, got %s", asset, config.get("asset"))
            return None
    except Exception as e:
        logger.error("[CALIBRATION] Failed to load config from %s: %s", config_path, e, exc_info=True)
        return None
