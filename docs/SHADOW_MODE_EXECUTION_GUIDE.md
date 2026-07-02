# Shadow Mode Execution Guide

## Overview
Shadow mode allows you to run unified edge in "observe only" mode to validate behavior before live deployment. This compares unified edge decisions against production decisions without actual trading.

## Prerequisites

### 1. System Requirements
- MERID system running in staging or paper trading mode
- Access to log files
- Python environment for analysis scripts

### 2. Configuration
```bash
# Enable unified edge in shadow mode
MERID_UNIFIED_EDGE_ENABLED=true
MERID_CALIBRATION_VERSION=placeholder  # or v1 after calibration
MERID_PROFILE=kalshi_crypto_15m_v2
MERID_PM_PROFILE=baseline
```

### 3. Log Configuration
Ensure logging is enabled for:
- `[UNIFIED-EDGE-APPLIED]` - unified edge decisions
- `[UNIFIED-EDGE-ERROR]` - unified edge errors
- `[LEGACY-EDGE-APPLIED]` - production edge decisions
- `[DYNAMIC-RISK-ROUTING-SHADOW]` - shadow routing decisions
- `[ALIGNMENT-DEGRADED]` - alignment failures
- `[ALIGNMENT-RESTORED]` - alignment restorations

## Execution Steps

### Step 1: Enable Shadow Mode
```bash
# Set environment variables
export MERID_UNIFIED_EDGE_ENABLED=true
export MERID_CALIBRATION_VERSION=placeholder

# Restart system
# (system-specific restart command)
```

### Step 2: Run for Observation Period
- **Duration:** 2-4 hours minimum
- **Mode:** Observe only (no actual routing changes)
- **Monitoring:** Watch logs for unified edge decisions

### Step 3: Collect Logs
```bash
# Collect logs from observation period
# Logs should be in /var/log/merid/ or similar
log_dir="/path/to/logs"
```

### Step 4: Run Shadow Mode Analysis
```bash
# Run shadow mode comparison script
python scripts/shadow_unified_edge.py --log-dir $log_dir --hours 4
```

### Step 5: Review Results
Check for:
- Pathological cases (edge_R > 5.0, negative edge_R)
- Divergence between unified and production decisions
- Alignment failures
- NaN/None propagation

### Step 6: Decision
**If results are good:**
- Proceed to gradual rollout
- Start with reduced risk budget

**If results are bad:**
- Investigate issues
- Fix bugs
- Re-run shadow mode
- Consider delaying deployment

## Analysis Script Usage

### shadow_unified_edge.py
```bash
# Basic usage
python scripts/shadow_unified_edge.py --log-dir /path/to/logs --hours 2

# Extended observation
python scripts/shadow_unified_edge.py --log-dir /path/to/logs --hours 8

# Specific asset focus
python scripts/shadow_unified_edge.py --log-dir /path/to/logs --hours 4 --asset BTC
```

### Output Interpretation
```
SHADOW MODE COMPARISON
================================================================================

BTC:
  Unified edge decisions: 45
  Production decisions: 38
  Avg edge_R: 1.234
  Max edge_R: 3.456
  Avg production edge: 0.023

  ⚠️  PATHOLOGICAL: 2 decisions with edge_R > 5.0
  ⚠️  DIVERGENCE: Unified (45) vs Production (38)
```

**Good Indicators:**
- edge_R in range 0.5-2.0
- No pathological cases
- Similar decision counts (within 20%)
- No alignment failures

**Bad Indicators:**
- edge_R > 5.0 or edge_R < 0
- Pathological cases present
- Large divergence (> 50% difference)
- Frequent alignment failures

## Monitoring During Shadow Mode

### Key Metrics to Watch
1. **Edge Distribution**
   - Should be centered around 0
   - Range: -0.05 to +0.05
   - No extreme values

2. **Edge_R Distribution**
   - Should be positive for taken trades
   - Range: 0.5 to 2.0
   - No values > 5.0

3. **Alignment Gaps**
   - Should be < 50 cents for all assets
   - No consecutive failures
   - No degraded mode activations

4. **Decision Counts**
   - Similar to production (within 20%)
   - No sudden drops or spikes
   - Consistent across assets

### Log Tags to Monitor
- `[UNIFIED-EDGE-APPLIED]` - successful unified edge computation
- `[UNIFIED-EDGE-ERROR]` - unified edge computation failed
- `[LEGACY-EDGE-APPLIED]` - fallback to production edge
- `[ALIGNMENT-DEGRADED]` - alignment failure
- `[ALIGNMENT-RESTORED]` - alignment restored
- `[STRIKE-EXTRACTION-FALLBACK]` - strike extraction used fallback
- `[SPOT-REF-COMPOSITE]` - using composite spot (not CFB)

## Troubleshooting

### Issue: Frequent [UNIFIED-EDGE-ERROR]
**Possible Causes:**
- Missing market state
- Invalid spot price
- Invalid contract metadata
- NaN propagation

**Solutions:**
- Check market state availability
- Check spot price feed
- Check contract metadata extraction
- Add defensive checks

### Issue: Frequent [ALIGNMENT-DEGRADED]
**Possible Causes:**
- Spot feed divergence from CFB RTI
- Clock skew
- Invalid calibration parameters

**Solutions:**
- Check spot feed quality
- Check clock synchronization
- Verify calibration parameters
- Consider adjusting threshold

### Issue: Pathological edge_R values
**Possible Causes:**
- Invalid volatility estimates
- Invalid calibration parameters
- Edge computation bug

**Solutions:**
- Verify volatility estimates
- Verify calibration parameters
- Check edge computation logic
- Add edge_R caps

### Issue: Large divergence from production
**Possible Causes:**
- Different edge thresholds
- Different risk caps
- Different filtering logic

**Solutions:**
- Compare edge thresholds
- Compare risk caps
- Compare filtering logic
- Align configurations

## Rollback from Shadow Mode

If issues are detected during shadow mode:

```bash
# Disable unified edge
export MERID_UNIFIED_EDGE_ENABLED=false

# Restart system
# (system-specific restart command)

# Investigate logs
python scripts/production_bug_hunt.py --log-dir /path/to/logs
```

## Next Steps After Shadow Mode

### If Shadow Mode Successful
1. Proceed to gradual rollout
2. Start with reduced risk budget (50%)
3. Monitor for 24-48 hours
4. Gradually increase risk budget
5. Full deployment after validation

### If Shadow Mode Failed
1. Investigate issues
2. Fix bugs
3. Re-run shadow mode
4. Consider delaying deployment
5. Re-evaluate calibration parameters

## Documentation

- Log all shadow mode runs
- Document decisions and rationale
- Track metrics over time
- Maintain shadow mode history

## Contact

For issues during shadow mode:
- Check logs for error tags
- Run analysis scripts
- Review troubleshooting guide
- Rollback if issues cannot be resolved
