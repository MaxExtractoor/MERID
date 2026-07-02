#!/usr/bin/env python3
"""
Feed lag calibration script for Kalshi 15m crypto trading.

This script reads trade trace data from the JSONL log file and computes:
- Latency distributions (signal_to_order, order_to_fill, signal_to_settle, etc.)
- Slippage distributions
- Post-fill move distributions
- Recommended latency buffers for each asset

The output is a calibration config file that can be loaded by the trading system
to dynamically adjust latency buffers based on empirical data.
"""
from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any
import sys


@dataclass
class CalibrationMetrics:
    """Calibration metrics for a single asset."""
    asset: str
    sample_count: int
    
    # Latency percentiles (in seconds)
    signal_to_order_p50: float
    signal_to_order_p90: float
    signal_to_order_p95: float
    signal_to_order_p99: float
    
    order_to_fill_p50: float
    order_to_fill_p90: float
    order_to_fill_p95: float
    order_to_fill_p99: float
    
    signal_to_fill_p50: float
    signal_to_fill_p90: float
    signal_to_fill_p95: float
    signal_to_fill_p99: float
    
    fill_to_settlement_p50: float
    fill_to_settlement_p90: float
    fill_to_settlement_p95: float
    fill_to_settlement_p99: float
    
    # Slippage (absolute difference in probability)
    slippage_mean: float
    slippage_std: float
    slippage_p50: float
    slippage_p90: float
    slippage_p95: float
    
    # Post-fill move (settlement_price - spot_price_at_signal)
    post_fill_move_mean: float
    post_fill_move_std: float
    post_fill_move_p50: float
    post_fill_move_p90: float
    post_fill_move_p95: float
    
    # Recommended latency buffer (seconds)
    # Uses p95 of signal_to_fill as conservative buffer
    recommended_latency_buffer: float


@dataclass
class CalibrationConfig:
    """Calibration config for all assets."""
    generated_at: str
    data_source: str
    total_samples: int
    assets: Dict[str, CalibrationMetrics]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "generated_at": self.generated_at,
            "data_source": self.data_source,
            "total_samples": self.total_samples,
            "assets": {k: asdict(v) for k, v in self.assets.items()}
        }


def percentile(data: List[float], p: float) -> float:
    """Compute percentile of data."""
    if not data:
        return 0.0
    sorted_data = sorted(data)
    k = (len(sorted_data) - 1) * p / 100
    f = int(k)
    c = f + 1
    if c >= len(sorted_data):
        return sorted_data[-1]
    return sorted_data[f] + (k - f) * (sorted_data[c] - sorted_data[f])


def compute_metrics(traces: List[Dict[str, Any]], asset: str) -> Optional[CalibrationMetrics]:
    """Compute calibration metrics for a single asset."""
    if not traces:
        return None
    
    # Extract latency values
    signal_to_order = []
    order_to_fill = []
    signal_to_fill = []
    fill_to_settlement = []
    slippage = []
    post_fill_move = []
    
    for trace in traces:
        # Signal to order latency
        if trace.get("spot_time") and trace.get("signal_time"):
            signal_to_order.append(trace["signal_time"] - trace["spot_time"])
        
        # Order to fill latency
        if trace.get("order_submit_time") and trace.get("fill_time"):
            order_to_fill.append(trace["fill_time"] - trace["order_submit_time"])
        
        # Signal to fill latency
        if trace.get("signal_time") and trace.get("fill_time"):
            signal_to_fill.append(trace["fill_time"] - trace["signal_time"])
        
        # Fill to settlement latency
        if trace.get("fill_time") and trace.get("settlement_time"):
            fill_to_settlement.append(trace["settlement_time"] - trace["fill_time"])
        
        # Slippage
        if trace.get("fill_price") and trace.get("kalshi_mid_at_signal"):
            slippage.append(abs(trace["fill_price"] - trace["kalshi_mid_at_signal"]))
        
        # Post-fill move
        if trace.get("post_fill_move") is not None:
            post_fill_move.append(trace["post_fill_move"])
    
    if not signal_to_fill:
        return None
    
    # Compute percentiles
    metrics = CalibrationMetrics(
        asset=asset,
        sample_count=len(traces),
        
        signal_to_order_p50=percentile(signal_to_order, 50),
        signal_to_order_p90=percentile(signal_to_order, 90),
        signal_to_order_p95=percentile(signal_to_order, 95),
        signal_to_order_p99=percentile(signal_to_order, 99),
        
        order_to_fill_p50=percentile(order_to_fill, 50),
        order_to_fill_p90=percentile(order_to_fill, 90),
        order_to_fill_p95=percentile(order_to_fill, 95),
        order_to_fill_p99=percentile(order_to_fill, 99),
        
        signal_to_fill_p50=percentile(signal_to_fill, 50),
        signal_to_fill_p90=percentile(signal_to_fill, 90),
        signal_to_fill_p95=percentile(signal_to_fill, 95),
        signal_to_fill_p99=percentile(signal_to_fill, 99),
        
        fill_to_settlement_p50=percentile(fill_to_settlement, 50),
        fill_to_settlement_p90=percentile(fill_to_settlement, 90),
        fill_to_settlement_p95=percentile(fill_to_settlement, 95),
        fill_to_settlement_p99=percentile(fill_to_settlement, 99),
        
        slippage_mean=statistics.mean(slippage) if slippage else 0.0,
        slippage_std=statistics.stdev(slippage) if len(slippage) > 1 else 0.0,
        slippage_p50=percentile(slippage, 50),
        slippage_p90=percentile(slippage, 90),
        slippage_p95=percentile(slippage, 95),
        
        post_fill_move_mean=statistics.mean(post_fill_move) if post_fill_move else 0.0,
        post_fill_move_std=statistics.stdev(post_fill_move) if len(post_fill_move) > 1 else 0.0,
        post_fill_move_p50=percentile(post_fill_move, 50),
        post_fill_move_p90=percentile(post_fill_move, 90),
        post_fill_move_p95=percentile(post_fill_move, 95),
        
        # Recommended buffer: p95 of signal_to_fill latency
        recommended_latency_buffer=percentile(signal_to_fill, 95),
    )
    
    return metrics


def main():
    parser = argparse.ArgumentParser(description="Calibrate feed lag from trade trace data")
    parser.add_argument(
        "--input",
        default="data/kalshi_trade_trace.jsonl",
        help="Path to trade trace JSONL file (default: data/kalshi_trade_trace.jsonl)"
    )
    parser.add_argument(
        "--output",
        default="config/feed_lag_calibration.json",
        help="Path to output calibration config (default: config/feed_lag_calibration.json)"
    )
    parser.add_argument(
        "--min-samples",
        type=int,
        default=10,
        help="Minimum samples per asset to include in calibration (default: 10)"
    )
    args = parser.parse_args()
    
    # Read trade traces
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: Input file not found: {input_path}")
        sys.exit(1)
    
    traces: List[Dict[str, Any]] = []
    with open(input_path, "r") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    trace = json.loads(line)
                    traces.append(trace)
                except json.JSONDecodeError as e:
                    print(f"Warning: Failed to parse line: {e}")
    
    print(f"Read {len(traces)} traces from {input_path}")
    
    # Group by asset
    traces_by_asset: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for trace in traces:
        asset = trace.get("symbol", "UNKNOWN")
        traces_by_asset[asset].append(trace)
    
    print(f"Found {len(traces_by_asset)} assets:")
    for asset, asset_traces in traces_by_asset.items():
        print(f"  {asset}: {len(asset_traces)} traces")
    
    # Compute metrics for each asset
    assets: Dict[str, CalibrationMetrics] = {}
    for asset, asset_traces in traces_by_asset.items():
        if len(asset_traces) < args.min_samples:
            print(f"Skipping {asset}: insufficient samples ({len(asset_traces)} < {args.min_samples})")
            continue
        
        metrics = compute_metrics(asset_traces, asset)
        if metrics:
            assets[asset] = metrics
            print(f"\n{asset} calibration metrics:")
            print(f"  Sample count: {metrics.sample_count}")
            print(f"  Signal to fill p50: {metrics.signal_to_fill_p50:.3f}s")
            print(f"  Signal to fill p90: {metrics.signal_to_fill_p90:.3f}s")
            print(f"  Signal to fill p95: {metrics.signal_to_fill_p95:.3f}s")
            print(f"  Recommended latency buffer: {metrics.recommended_latency_buffer:.3f}s")
            print(f"  Slippage mean: {metrics.slippage_mean:.4f}")
            print(f"  Post-fill move mean: {metrics.post_fill_move_mean:.4f}")
    
    if not assets:
        print("Error: No assets with sufficient samples for calibration")
        sys.exit(1)
    
    # Create calibration config
    config = CalibrationConfig(
        generated_at=datetime.now(timezone.utc).isoformat(),
        data_source=str(input_path),
        total_samples=len(traces),
        assets=assets,
    )
    
    # Write output
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, "w") as f:
        json.dump(config.to_dict(), f, indent=2)
    
    print(f"\nCalibration config written to {output_path}")
    print(f"Total samples: {config.total_samples}")
    print(f"Assets calibrated: {len(config.assets)}")


if __name__ == "__main__":
    main()
