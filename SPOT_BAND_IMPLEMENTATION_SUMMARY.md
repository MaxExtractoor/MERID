# Spot Band Optimization — Implementation Summary

## What Was Done

Successfully implemented a comprehensive spot band optimization system for MERID's Kalshi continuous trader.

### 1. Core Architecture (market_filter.py)

**SPOT_BANDS Configuration** (lines 53-84)
- Dict mapping `(asset, timeframe)` → band percentage as decimal
- All 25 combinations initialized to 0.125 (12.5%, matching legacy default)
- Example: `("BTC", "15m"): 0.125` means ±12.5% from spot

**Dynamic Lookup Function** (lines 87-107)
```python
def get_spot_band(asset: str, timeframe: str, default: float = 12.5) -> float:
    """Returns percentage (e.g., 12.5 for ±12.5%)"""
```
- Looks up SPOT_BANDS by (asset, timeframe) key
- Falls back to `default` parameter if not found
- Converts decimal (0.125) → percentage (12.5) for evaluate()

**Filter Integration** (lines 387-395)
- `MarketFilter.evaluate()` now calls `get_spot_band()` per candidate
- Uses candidate's `underlying` and `timeframe` for lookup
- Backward compatible with config default

### 2. Optimization Tool (scripts/optimize_spot_bands.py)

**Full-featured CLI script** (575 lines)
- Analyzes live Kalshi market data across multiple band configurations
- Respects existing edge thresholds and filters (no safety rails bypassed)
- Uses Kelly sizing for notional estimation
- Outputs CSV with comprehensive metrics

**Usage:**
```bash
# Quick test
python scripts/optimize_spot_bands.py --assets BTC,ETH --horizons 15m,1h

# Full analysis
python scripts/optimize_spot_bands.py \
    --assets BTC,ETH,SOL,XRP,DOGE \
    --horizons 15m,1h,daily,weekly,monthly
```

**Output:**
- CSV: `output/spot_band_analysis_<timestamp>.csv` with columns:
  - asset, timeframe, band_pct
  - n_input, n_accepted (candidate counts)
  - avg_edge, median_edge, p25_edge, p75_edge (edge distribution)
  - avg_spread_cents, potential_notional, edge_weighted_opportunity
- Console: Pareto-optimal summary + proposed SPOT_BANDS dict

**Metrics:**
- `n_accepted`: Candidates passing all filters
- `avg_edge`: Mean edge of accepted candidates
- `potential_notional`: Sum of Kelly-sized notional
- `edge_weighted_opportunity`: Sum(edge × notional) — quality-adjusted throughput

### 3. Documentation (docs/SPOT_BAND_OPTIMIZATION.md)

**Comprehensive guide** (350+ lines) covering:
- Architecture overview and data flow
- 5-phase testing procedure:
  1. Script validation (quick test)
  2. Full optimization run (all assets/timeframes)
  3. Update SPOT_BANDS configuration
  4. Paper trading validation (5-10 cycles)
  5. Live deployment (with monitoring)
- Success criteria and validation checks
- Troubleshooting guide
- Maintenance recommendations (weekly re-optimization)

## How It Works

### Before (Legacy)
```
Global constant: spot_band_pct = 12.5
Applied to all 25 (asset, timeframe) combinations
```

### After (Optimized)
```
Per-configuration bands:
  BTC 15m: could be 10% (tight, high liquidity)
  ETH daily: could be 25% (moderate)
  DOGE weekly: could be 35% (wide, low liquidity)

Dynamic lookup in filter:
  MarketCandidate(underlying="BTC", timeframe="15m")
    → get_spot_band("BTC", "15m")
    → returns 10.0 (from SPOT_BANDS)
    → applies ±10% distance check
```

## Current State

✅ **Code complete and committed**
- Branch: `claude/optimize-spot-band-configuration`
- Commit: bc084f5 "Implement per-asset/timeframe spot band optimization"

⏳ **Ready for optimization run** (not yet executed)
- SPOT_BANDS currently has all values at 0.125 (no behavior change from legacy)
- Need to run `scripts/optimize_spot_bands.py` with live data
- Then update SPOT_BANDS with recommended values

## Next Steps for You

### Step 1: Run Optimization Script

```bash
cd /home/runner/work/MERID/MERID

# Test the script first
MERID_TRADE_MODE=paper python scripts/optimize_spot_bands.py \
    --assets BTC,ETH \
    --horizons 15m,1h \
    --bands 0.10,0.15,0.20,0.25,0.30
```

**Verify:**
- Script completes without errors
- CSV generated in `output/` directory
- Console shows Pareto summary for BTC/ETH 15m/1h
- Metrics look reasonable (edges 2-10%, candidates > 0)

### Step 2: Full Optimization

```bash
# Full run (all 5 assets × 5 timeframes)
python scripts/optimize_spot_bands.py \
    --assets BTC,ETH,SOL,XRP,DOGE \
    --horizons 15m,1h,daily,weekly,monthly \
    --output-dir output
```

**Review CSV and console output:**
- Identify Pareto-optimal bands per (asset, timeframe)
- Balance trade-offs: more candidates vs higher edge
- Focus on maximizing `edge_weighted_opportunity`

### Step 3: Update Configuration

Edit `merid/event_venues/kalshi/market_filter.py` lines 53-84:

```python
SPOT_BANDS: Dict[Tuple[str, str], float] = {
    # Replace 0.125 with optimized values from script output
    ("BTC", "15m"): 0.20,   # example: 20% band
    ("BTC", "1h"): 0.25,    # example: 25% band
    # ... update all 25 entries
}
```

Commit with rationale:
```bash
git add merid/event_venues/kalshi/market_filter.py
git commit -m "Update SPOT_BANDS with optimized values

Based on analysis from scripts/optimize_spot_bands.py:
- BTC 15m/1h: 20-25% (high liquidity → tighter focus)
- [list changes for each asset/timeframe]

Expected impact: +30% candidate throughput, +15% avg_edge
CSV: output/spot_band_analysis_YYYYMMDD_HHMMSS.csv"
```

### Step 4: Paper Trading Test

```bash
# Start MERID in paper mode
MERID_TRADE_MODE=paper python -m merid.loop
```

**Monitor for 5-10 cycles:**
- Check candidate counts per asset/timeframe in logs
- Verify edge distributions align with optimization predictions
- Ensure no increase in execution rejections
- Validate system stability (no errors, event loop lag < 500ms)

**Success criteria:**
- All 25 pairs have candidates in 80%+ of cycles
- Average edge >= baseline
- No new errors or alerts

### Step 5: Live Deployment

Once paper testing is successful:

```bash
# Deploy to production
python -m merid.loop
```

**Monitor first 24 hours:**
- Hourly: candidate counts, executions, PnL
- Daily: compare pre/post metrics (trades, edge, PnL by asset/timeframe)

## Key Design Decisions

### Why per-(asset, timeframe)?
- **Liquidity varies**: BTC has tight spreads → can focus near-the-money. DOGE is thin → needs wider search.
- **Timeframe matters**: 15m needs tight bands (avoid far-OTM noise). Weekly needs wide bands (capture long-dated strikes).

### Why not just make bands wider everywhere?
- Wider bands include lower-quality (illiquid, wide-spread) strikes
- Optimization finds the sweet spot: enough candidates, high quality

### Why optimize for edge_weighted_opportunity?
- Simple candidate count → favors wide bands with poor strikes
- Simple avg_edge → favors tight bands with too few trades
- `edge × notional` → balances quantity and quality

### Backward compatibility?
- Global `spot_band_pct` still exists in MarketFilterConfig
- Falls back if (asset, timeframe) not in SPOT_BANDS
- Initial values (0.125) match legacy default → zero behavior change until optimized

## Safety Guarantees

✅ **No safety rails removed**
- All existing filters still active (spread, volume, OI, dead-zone, volume band)
- Edge thresholds (EDGE_THRESHOLDS) still enforced
- Risk caps (group notional, bankroll fraction) unchanged
- Execution gate still blocks unsafe conditions

✅ **Backward compatible**
- If SPOT_BANDS lookup fails → uses config default
- Initial values = legacy default → zero behavior change
- Can emergency-revert by setting all values back to 0.125

✅ **Auditable**
- Optimization script uses same edge calculation as live trader
- CSV output provides full trace of analysis
- Test plan has clear success criteria and rollback procedure

## Files Changed

```
merid/event_venues/kalshi/market_filter.py  (+68 lines)
  ├─ SPOT_BANDS dict (25 entries)
  ├─ get_spot_band() helper
  └─ evaluate() uses dynamic lookup

scripts/optimize_spot_bands.py  (+575 lines, new file)
  ├─ SpotBandOptimizer class
  ├─ CLI with --assets, --horizons, --bands args
  ├─ CSV output with 11 metrics per config
  └─ Pareto summary printer

docs/SPOT_BAND_OPTIMIZATION.md  (+350 lines, new file)
  ├─ Architecture guide
  ├─ 5-phase testing procedure
  ├─ Troubleshooting section
  └─ Maintenance recommendations
```

## Questions?

Refer to:
- `docs/SPOT_BAND_OPTIMIZATION.md` — Complete testing guide
- `scripts/optimize_spot_bands.py --help` — Script usage
- Existing pattern: `EDGE_THRESHOLDS` in `kalshi_continuous_trader.py` (lines 65-96)

The implementation is complete and ready for optimization runs!
