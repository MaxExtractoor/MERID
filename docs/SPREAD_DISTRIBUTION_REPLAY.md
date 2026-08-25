# Spread Distribution Replay Framework

## Overview

The Spread Distribution Replay Framework provides tools to analyze spread distributions across Kalshi 15-minute crypto markets to validate whether spread caps are appropriately calibrated. This addresses the concern that a fixed 20c spread cap may be too strict for certain assets (SOL, XRP, DOGE) and market conditions.

## Problem Statement

From the logs, we see repeated rejections like:
```
[MICROSTRUCTURE-GATE] ticker=KXBTC15M-26AUG020300-00 spread_too_wide: 46c > 20c
```

A 46c spread rejection in a 15-minute market with 5.2% edge suggests the gate may be too strict. The framework enables data-driven calibration by:

1. Measuring actual spread distributions per asset and time window
2. Computing reject rates at different cap levels
3. Identifying false rejects (candidates that would have had positive edge)
4. Providing recommendations for cap adjustments

## Architecture

### Core Components

1. **SpreadDataCollector**: Collects spread measurements from live market state
2. **SpreadDistributionAnalyzer**: Computes statistical summaries and reject rates
3. **SpreadReplayOrchestrator**: Orchestrates collection and analysis workflow
4. **TimeBucket**: Time-to-expiry buckets (0-3min, 3-6min, 6-10min, 10-13min, 13-15min)

### Data Model

```python
@dataclass
class SpreadMeasurement:
    timestamp: datetime
    asset: str
    market_id: str
    time_to_expiry_seconds: float
    time_bucket: TimeBucket
    yes_bid_cents: int
    no_bid_cents: int
    yes_spread_cents: float
    no_spread_cents: float
    canonical_spread_cents: float  # max(yes_spread, no_spread)
```

### Statistics Computed

For each asset and time bucket:
- **Count**: Number of samples
- **Min/Max Spread**: Observed range
- **Median Spread**: 50th percentile
- **75th/90th/95th Percentile**: Upper distribution bounds
- **Mean/Std Dev**: Central tendency and volatility

### Reject Rate Analysis

For each cap level tested:
- **Total Candidates**: Sample size
- **Rejected Count**: Samples exceeding cap
- **Reject Rate**: Percentage rejected
- **False Reject Count**: Would have had positive edge
- **False Reject Rate**: Percentage of false rejects
- **Missed Edge Sum**: Total edge missed (requires edge data integration)

## Usage

### Live Collection Mode

Collect spread samples in real-time from running system:

```bash
python -m merid.event_venues.kalshi.spread_distribution_replay \
    --mode live \
    --duration 300 \
    --interval 1.0 \
    --assets BTC ETH SOL XRP DOGE \
    --output-dir spread_analysis_output
```

**Parameters:**
- `--duration`: Collection duration in seconds (default: 300)
- `--interval`: Sampling interval in seconds (default: 1.0)
- `--assets`: Assets to analyze (default: all 5)
- `--output-dir`: Output directory (default: spread_analysis_output)

### Historical Analysis Mode

Analyze previously collected spread data:

```bash
python -m merid.event_venues.kalshi.spread_distribution_replay \
    --mode historical \
    --input-file spread_samples_20260802_020000.json \
    --output-dir spread_analysis_output
```

### Programmatic Usage

```python
import asyncio
from merid.event_venues.kalshi.spread_distribution_replay import (
    SpreadReplayOrchestrator,
    KalshiMarketStateStore
)

async def run_analysis():
    # Initialize
    market_state_store = KalshiMarketStateStore()
    orchestrator = SpreadReplayOrchestrator(market_state_store)
    
    # Run live collection for 5 minutes
    analyses = await orchestrator.run_live_collection(
        duration_seconds=300,
        sample_interval=1.0,
        assets=['BTC', 'ETH', 'SOL', 'XRP', 'DOGE']
    )
    
    # Print results
    for asset, analysis in analyses.items():
        print(f"{asset}: 90th percentile = {analysis.overall_stats.p90_spread:.1f}c")

asyncio.run(run_analysis())
```

## Output

### JSON Output

```json
{
  "BTC": {
    "asset": "BTC",
    "current_cap_cents": 10.0,
    "overall_stats": {
      "count": 1500,
      "min_spread_cents": 1.0,
      "max_spread_cents": 45.0,
      "median_spread_cents": 8.0,
      "p75_spread_cents": 12.0,
      "p90_spread_cents": 18.0,
      "p95_spread_cents": 25.0,
      "mean_spread_cents": 9.5,
      "std_spread_cents": 5.2
    },
    "time_bucket_stats": {
      "0-3min": {
        "count": 300,
        "median_spread_cents": 12.0,
        "p90_spread_cents": 25.0,
        "max_spread_cents": 45.0
      },
      ...
    },
    "cap_analysis": [
      {
        "cap_cents": 5.0,
        "reject_rate": 0.35,
        "false_reject_rate": 0.07
      },
      {
        "cap_cents": 10.0,
        "reject_rate": 0.15,
        "false_reject_rate": 0.03
      },
      ...
    ]
  }
}
```

### Human-Readable Report

```
================================================================================
SPREAD DISTRIBUTION REPLAY REPORT
================================================================================

================================================================================
ASSET: BTC
Current Cap: 10.0c
================================================================================

OVERALL STATISTICS:
  Samples: 1500
  Min Spread: 1.0c
  Max Spread: 45.0c
  Median Spread: 8.0c
  75th Percentile: 12.0c
  90th Percentile: 18.0c
  95th Percentile: 25.0c
  Mean Spread: 9.5c
  Std Dev: 5.2c

TIME BUCKET STATISTICS:

  0-3min:
    Samples: 300
    Median: 12.0c
    90th: 25.0c
    Max: 45.0c

  3-6min:
    Samples: 400
    Median: 8.0c
    90th: 15.0c
    Max: 30.0c

CAP LEVEL ANALYSIS:
Cap (c)   Reject Rate  False Reject Rate
--------------------------------------------------
5.0       35.00%       7.00%
7.5       22.00%       4.40%
10.0      15.00%       3.00%
12.5      10.00%       2.00%
15.0      5.00%        1.00%
20.0      2.00%        0.40%

RECOMMENDATIONS:
⚠️  CURRENT CAP (10.0c) IS TOO STRICT
   90th percentile spread (18.0c) exceeds cap.
   Consider raising to 25.0c (95th percentile) or 45.0c (max observed).
```

## Interpreting Results

### Key Metrics

1. **90th Percentile Spread**: If this exceeds your current cap, you're rejecting 10% of samples even during normal conditions
2. **95th Percentile Spread**: A more conservative target that accommodates brief dislocations
3. **Max Spread**: The widest spread observed - useful for understanding worst-case scenarios
4. **Reject Rate**: Percentage of samples that would be rejected at each cap level
5. **False Reject Rate**: Estimated percentage of rejected samples that would have had positive edge

### Recommendation Logic

The framework provides automated recommendations:

- **Too Strict**: If 90th percentile > current cap, consider raising to 95th percentile or max
- **Potentially Too Strict**: If 75th percentile > 80% of cap, monitor for increased rejects
- **Reasonable**: If 90th percentile is well below cap, current configuration is appropriate

### Time Bucket Analysis

Different time windows show different spread behavior:
- **0-3min (Market Open)**: Highest volatility, widest spreads
- **3-6min (Early)**: Elevated spreads as market stabilizes
- **6-10min (Mid)**: Normal trading conditions
- **10-13min (Late)**: Spreads may widen as expiry approaches
- **13-15min (Near Expiry)**: Highest volatility, potential for extreme spreads

Consider time-of-window caps if certain buckets consistently show wider spreads.

## Integration with Existing System

### Current Spread Cap Locations

1. **Profile Configuration** (`merid/risk/profiles/crypto_15m_profile.py`):
   ```python
   market_microstructure_max_spread_cents: float = 20.0
   ```

2. **Asset-Specific Caps** (`merid/event_venues/kalshi/spread_edge_analytics.py`):
   ```python
   ASSET_SPREAD_CAPS = {
       "BTC": 10,
       "ETH": 12,
       "SOL": 20,
       "XRP": 20,
       "DOGE": 30,
   }
   ```

### Updating Caps Based on Analysis

After running the replay framework, update caps in both locations:

```python
# Example: If analysis shows BTC 90th percentile = 18c, consider raising to 20c
ASSET_SPREAD_CAPS = {
    "BTC": 20,  # Raised from 10c
    "ETH": 20,  # Raised from 12c
    "SOL": 25,  # Raised from 20c
    "XRP": 25,  # Raised from 20c
    "DOGE": 35,  # Raised from 30c
}
```

### Adding Time-of-Window Caps

For more sophisticated gating, consider time-based caps:

```python
TIME_BUCKET_CAPS = {
    "BTC": {
        "0-3min": 25,   # Wider at market open
        "3-6min": 20,
        "6-10min": 15,
        "10-13min": 20,
        "13-15min": 25,  # Wider near expiry
    },
    # ... other assets
}
```

## Advanced Usage

### Custom Time Buckets

Modify the `TimeBucket` enum to match your specific needs:

```python
class TimeBucket(Enum):
    OPEN_0_2MIN = "0-2min"
    EARLY_2_5MIN = "2-5min"
    MID_5_10MIN = "5-10min"
    LATE_10_13MIN = "10-13min"
    EXPIRY_13_15MIN = "13-15min"
```

### Integration with Edge Data

To improve false reject analysis, integrate with actual edge data:

```python
@dataclass
class SpreadMeasurement:
    # ... existing fields ...
    model_edge_pct: float = 0.0  # Add edge data
    would_have_executed: bool = False  # Execution outcome
```

### Continuous Monitoring

Run the framework periodically to track spread regime changes:

```python
# Run daily and archive results
for day in range(7):
    analyses = await orchestrator.run_live_collection(
        duration_seconds=3600,  # 1 hour samples
        sample_interval=5.0
    )
    archive_results(analyses, day)
```

## Troubleshooting

### No Measurements Collected

- Verify market state store is being populated
- Check that assets are active and have orderbook data
- Ensure sampling interval is appropriate for market activity

### Inconsistent Results

- Increase sample duration for more data
- Check for market regime changes during collection
- Verify time bucket boundaries match your trading window

### High Memory Usage

- Reduce `max_samples_per_ticker` in `SpreadDataCollector`
- Increase sampling interval
- Process data in batches instead of holding all in memory

## Future Enhancements

1. **Edge Data Integration**: Connect to actual model edge calculations for precise false reject analysis
2. **Regime Detection**: Identify different spread regimes (normal, stressed, extreme)
3. **Predictive Modeling**: Forecast spread based on volatility and time to expiry
4. **Automated Cap Adjustment**: Dynamic cap adjustment based on real-time spread statistics
5. **Backtesting Integration**: Test cap changes against historical performance

## References

- **Spread Gate Implementation**: `merid/event_venues/kalshi/order_router.py` (lines 452-787)
- **Spread Analytics**: `merid/event_venues/kalshi/spread_edge_analytics.py`
- **Market State Storage**: `merid/event_venues/kalshi/market_state.py`
- **Current Asset Caps**: `merid/event_venues/kalshi/spread_edge_analytics.py` (lines 47-53)

## Contributing

When extending this framework:
1. Maintain backward compatibility with existing data format
2. Add unit tests for new functionality
3. Update this documentation with new features
4. Consider performance implications for live collection mode
