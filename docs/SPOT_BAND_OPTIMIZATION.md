# Spot Band Optimization — Implementation & Testing Guide

## Overview

This document describes the spot band optimization system for MERID's Kalshi continuous trader. The spot band controls how far from the current spot price we scan strikes for trading opportunities. This implementation allows per-(asset, timeframe) configuration instead of a global constant.

## Architecture

### 1. Current State (Pre-Optimization)

- **Global constant**: `spot_band_pct = 12.5` (±12.5% from spot)
- Applied uniformly to all assets (BTC, ETH, SOL, XRP, DOGE) and timeframes (15m, 1h, daily, weekly, monthly)
- Located in `market_filter.py:MarketFilterConfig`

### 2. New Architecture

#### Components

1. **SPOT_BANDS Configuration** (`market_filter.py:53-84`)
   - Dict mapping `(asset, timeframe)` → band percentage (as decimal)
   - Example: `("BTC", "15m"): 0.125` = ±12.5%
   - Covers all 25 combinations (5 assets × 5 timeframes)

2. **Dynamic Lookup Function** (`market_filter.py:87-107`)
   - `get_spot_band(asset: str, timeframe: str, default: float = 12.5) -> float`
   - Returns percentage (e.g., 12.5 for ±12.5%)
   - Falls back to `default` if pair not found in SPOT_BANDS

3. **Filter Integration** (`market_filter.py:387-395`)
   - `MarketFilter.evaluate()` calls `get_spot_band()` for each candidate
   - Uses candidate's `underlying` and `timeframe` fields for lookup
   - Backward compatible: falls back to config default if no specific band configured

4. **Optimization Script** (`scripts/optimize_spot_bands.py`)
   - CLI tool to analyze spot band configurations
   - Uses live Kalshi market data + existing edge/filter logic
   - Outputs CSV with metrics per (asset, timeframe, band) configuration
   - Prints Pareto-optimal recommendations

## How It Works

### Data Flow

```
KalshiContinuousTrader._refresh_candidates()
  → Creates MarketCandidate with asset + timeframe
    → MarketFilter.filter_markets(candidates)
      → For each candidate: MarketFilter.evaluate()
        → Calls get_spot_band(candidate.underlying, candidate.timeframe)
          → Looks up SPOT_BANDS[(asset, timeframe)]
          → Returns dynamic band percentage
        → Applies band check: distance_from_spot_pct <= band
```

### Key Invariants

1. **No behavior change without optimization**: Initial SPOT_BANDS values are all 0.125 (12.5%), matching the legacy default
2. **Backward compatible**: If a pair is missing from SPOT_BANDS, falls back to `config.spot_band_pct`
3. **Respects existing filters**: All other filters (spread, volume, edge thresholds, risk caps) remain unchanged

## Testing Procedure

### Phase 1: Script Validation

Run the optimization script on a subset of markets to verify it works correctly:

```bash
cd /home/runner/work/MERID/MERID

# Quick test: BTC + ETH, short timeframes only
MERID_TRADE_MODE=paper python scripts/optimize_spot_bands.py \
    --assets BTC,ETH \
    --horizons 15m,1h \
    --bands 0.10,0.15,0.20,0.25,0.30 \
    --output-dir output

# Check output
ls -lh output/spot_band_analysis_*.csv
head -20 output/spot_band_analysis_*.csv
```

**Expected Output:**

1. **CSV file** in `output/` with columns:
   - `asset`, `timeframe`, `band_pct`
   - `n_input`, `n_accepted` (candidate counts)
   - `avg_edge`, `median_edge`, `p25_edge`, `p75_edge` (edge distribution)
   - `avg_spread_cents`, `potential_notional`, `edge_weighted_opportunity`

2. **Console summary** showing:
   - Per-(asset, timeframe) analysis progress logs
   - Pareto-optimal candidates (highest edge, most trades, best opportunity)
   - Proposed SPOT_BANDS configuration in Python dict format

**Validation Checks:**

- ✅ Script completes without errors
- ✅ CSV contains data for all requested (asset, timeframe, band) combinations
- ✅ `n_accepted` is reasonable (0-50 per config, depending on liquidity)
- ✅ `avg_edge` is in expected range (2-10% for accepted candidates)
- ✅ Tighter bands (e.g., 10%) have fewer candidates than wider bands (e.g., 30%)
- ✅ Proposed configuration favors higher `edge_weighted_opportunity`

### Phase 2: Full Optimization Run

Once the script is validated, run a full analysis:

```bash
# Full analysis: all 5 assets × 5 timeframes
MERID_TRADE_MODE=paper python scripts/optimize_spot_bands.py \
    --assets BTC,ETH,SOL,XRP,DOGE \
    --horizons 15m,1h,daily,weekly,monthly \
    --output-dir output
```

**Analysis Steps:**

1. **Review CSV metrics** for each asset/timeframe:
   - Compare candidate count vs edge quality trade-offs
   - Identify configurations with `n_accepted >= 3` (minimum viable pool)
   - Look for sweet spots: high `edge_weighted_opportunity`

2. **Examine Pareto frontier**:
   - For each (asset, timeframe), note:
     - Config with highest avg_edge (quality focus)
     - Config with most candidates (throughput focus)
     - Config with best opportunity (balanced metric)

3. **Select optimal bands**:
   - Prefer configurations that maximize `edge_weighted_opportunity`
   - Ensure `n_accepted >= 3` for reliable trading
   - Balance asset liquidity:
     - BTC/ETH: Can use tighter bands (10-20%)
     - SOL/XRP: May need moderate bands (15-25%)
     - DOGE: Likely needs wider bands (20-35%)
   - Balance timeframe characteristics:
     - Short (15m, 1h): Tighter bands for near-the-money focus
     - Medium (daily): Moderate bands
     - Long (weekly, monthly): Wider bands for more candidates

### Phase 3: Update SPOT_BANDS Configuration

Based on the optimization analysis, update `market_filter.py:53-84`:

```python
SPOT_BANDS: Dict[Tuple[str, str], float] = {
    # Example optimized values (replace with actual recommendations)
    ("BTC", "15m"): 0.20,   # 20% band
    ("BTC", "1h"): 0.25,    # 25% band
    ("BTC", "daily"): 0.30,
    # ... update all 25 entries
}
```

**Commit message format:**

```
Optimize spot bands based on live market analysis

Applied data-driven spot band configuration per (asset, timeframe):
- BTC 15m/1h: 20-25% bands (high liquidity allows tighter focus)
- ETH 15m/1h: 25-30% bands (moderate liquidity)
- SOL/XRP/DOGE: 30-40% bands (lower liquidity requires wider search)
- Longer timeframes: 35-50% bands (more OTM/ITM candidates needed)

Analysis showed:
- Tighter bands: higher avg_edge (4-6%) but fewer candidates (3-5)
- Wider bands: more candidates (8-15) but lower avg_edge (2-3%)
- Optimal: maximize edge_weighted_opportunity metric

Results from scripts/optimize_spot_bands.py run on 2026-04-02.
CSV: output/spot_band_analysis_YYYYMMDD_HHMMSS.csv
```

### Phase 4: Paper Trading Validation

Test the new configuration in paper mode before live deployment:

```bash
# Start MERID in paper mode with new SPOT_BANDS
MERID_TRADE_MODE=paper python -m merid.loop
```

**Monitoring (first 5-10 cycles):**

1. **Candidate counts** (check logs):
   ```
   ContinuousTrader candidates: BTC 15m = 4
   ContinuousTrader candidates: ETH 1h = 7
   ContinuousTrader candidates: SOL daily = 3
   ```
   - Compare to optimization script predictions (should be within ±20%)
   - Verify each (asset, timeframe) has at least 2-3 candidates

2. **Edge distributions**:
   ```
   signal_to_sizing: KXBTC... edge=0.0325 ... ACCEPTED
   signal_to_sizing: KXETH... edge=0.0412 ... ACCEPTED
   ```
   - Verify accepted edges align with optimization analysis
   - Check that min edge thresholds (EDGE_THRESHOLDS) are still being respected

3. **Filter stats** (via `/health` endpoint or logs):
   ```
   ContinuousTrader filter: total_input=245 volume_band_rejected=48
       block_rate=0.196 rolling_avg=0.189
   ```
   - Volume band rejection rate should be 15-40% (healthy range)
   - Distance rejections should decrease if bands were widened

4. **No unexpected rejections**:
   - Check for increases in spread/liquidity/edge rejections
   - Verify risk caps (group notional, bankroll fraction) are not being hit more often

**Success Criteria:**

- ✅ All 25 (asset, timeframe) pairs have candidates in at least 80% of cycles
- ✅ Average edge of accepted candidates is >= baseline (pre-optimization)
- ✅ Total candidate throughput increases by 20-50% (if bands were widened)
- ✅ No increase in execution rejections or risk limit hits
- ✅ System remains stable (no errors, event loop lag < 500ms)

### Phase 5: Live Deployment

After 1-2 hours of successful paper trading:

```bash
# Deploy to production (assuming no MERID_TRADE_MODE override = live)
python -m merid.loop
```

**Post-deployment monitoring (first 24 hours):**

1. **Hourly checks**:
   - Review candidate counts per asset/timeframe
   - Check execution stats (fills, rejections, PnL)
   - Monitor for any alerts or anomalies

2. **Daily review**:
   - Compare pre/post optimization metrics:
     - Total trades executed
     - Average edge per trade
     - PnL per asset/timeframe
   - Validate that changes are directionally correct:
     - More candidates found → more trading opportunities
     - Higher quality candidates → better edge capture

3. **Weekly tuning** (if needed):
   - Re-run optimization script with fresh data
   - Adjust bands if market liquidity patterns have shifted
   - Update SPOT_BANDS and redeploy

## Troubleshooting

### Issue: Script fails with "No catalog markets for X Y"

**Cause**: Kalshi catalog may not have markets for that asset/timeframe.

**Fix**:
1. Check that `KalshiMarketCatalog` is populated (may need to wait for catalog refresh)
2. Verify Kalshi API is accessible (`KALSHI_API_KEY` set, network connectivity)
3. Run script with `--assets` and `--horizons` limited to known-active markets

### Issue: All candidates have n_accepted = 0

**Cause**: Bands may be too tight, or other filters are blocking all markets.

**Fix**:
1. Check that candidates have `spot_price` populated (required for distance check)
2. Review other filter settings (spread, volume, edge thresholds)
3. Try wider bands (e.g., 0.35, 0.45) to see if candidates appear

### Issue: Paper trading shows different candidate counts than script

**Cause**: Live market data may have changed between script run and paper test.

**Fix**:
1. Re-run optimization script immediately before paper test
2. Verify that catalog refresh is working in live system
3. Allow ±20% tolerance (market conditions fluctuate)

### Issue: Live trading shows increased execution rejections

**Cause**: Wider bands may be including lower-quality (illiquid, wide-spread) strikes.

**Fix**:
1. Check spread rejection rate (may need to tighten `max_spread_cents`)
2. Review volume band settings (`volume_band_min`, `volume_band_max`)
3. Tighten SPOT_BANDS for affected (asset, timeframe) pairs
4. Consider increasing `EDGE_THRESHOLDS` for low-quality assets/timeframes

## Maintenance

### Re-optimization Cadence

- **Weekly**: Run optimization script to check for market regime shifts
- **Monthly**: Full review and update of SPOT_BANDS if needed
- **Event-driven**: Re-optimize after major market moves or Kalshi platform changes

### Monitoring Metrics

Track these metrics to detect when re-optimization is needed:

1. **Candidate starvation**: Any (asset, timeframe) with < 2 candidates for > 1 hour
2. **Edge erosion**: Average accepted edge drops by > 20% from baseline
3. **Throughput collapse**: Total candidates drops by > 30% from baseline
4. **Filter block rate**: Volume band or distance rejections > 60% of input

## Related Files

- `merid/event_venues/kalshi/market_filter.py` — SPOT_BANDS config + get_spot_band()
- `merid/trading/kalshi_continuous_trader.py` — EDGE_THRESHOLDS (edge validation)
- `scripts/optimize_spot_bands.py` — Optimization analysis tool
- `output/spot_band_analysis_*.csv` — Historical optimization results

## Design Rationale

### Why per-(asset, timeframe) bands?

Different assets have different liquidity profiles:
- **BTC**: High liquidity, tight spreads → can focus on near-the-money (tighter bands)
- **DOGE**: Lower liquidity, wider spreads → need wider search to find candidates

Different timeframes have different strike spacing:
- **15m/1h**: Need tighter bands to avoid far-OTM noise
- **weekly/monthly**: Need wider bands to capture enough long-dated strikes

### Why optimize for edge_weighted_opportunity?

Simple candidate count optimization would favor wide bands that include low-quality strikes. Pure edge optimization would favor tight bands with too few trades. `edge_weighted_opportunity = sum(edge × notional)` balances both:
- Higher edge contributes more per dollar of notional
- More candidates → more opportunities to deploy capital
- Optimal config maximizes total risk-adjusted profit potential

### Why not remove the global spot_band_pct?

Backward compatibility: The global `spot_band_pct` in `MarketFilterConfig` serves as:
1. A fallback for any (asset, timeframe) not in SPOT_BANDS
2. A default for testing with non-crypto markets
3. An override for emergency tightening (can update config without code change)

## Future Enhancements

1. **Adaptive bands**: Dynamically adjust bands based on real-time volatility or liquidity
2. **Per-strike type**: Different bands for calls vs puts (currently not applicable to binary markets)
3. **Correlation with edge thresholds**: Joint optimization of spot bands + edge thresholds
4. **Machine learning**: Use historical PnL data to optimize bands via reinforcement learning
