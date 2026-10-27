# Kalshi Alignment Log Analysis Guide

This guide provides commands and procedures for analyzing the alignment logs to identify why `markets_passing_shouldtrade=0`.

## Prerequisites

- System running in dry-run mode with all gates enabled
- Logs captured to `logs/full.log` or dedicated file
- At least 1 hour of runtime during active market hours (US session overlap preferred)

## Log Analysis Commands

### 1. Check Lag Gate Decisions

```bash
# View recent lag gate decisions
grep '[SIGNAL-GATE-TRACE].*gate=lag' logs/full.log | tail -50

# Count lag pass vs fail
grep '[SIGNAL-GATE-TRACE].*gate=lag' logs/full.log | grep 'lag_pass=True' | wc -l
grep '[SIGNAL-GATE-TRACE].*gate=lag' logs/full.log | grep 'lag_pass=False' | wc -l

# View lag failures by asset
grep '[SIGNAL-GATE-TRACE].*gate=lag.*lag_pass=False' logs/full.log | grep -o 'asset=[A-Z]*' | sort | uniq -c
```

### 2. Check Contract-Spot Alignment

```bash
# View recent alignment logs
grep '[CONTRACT-SPOT-ALIGN]' logs/full.log | tail -50

# Extract lag_rel_bps distribution per asset
grep '[CONTRACT-SPOT-ALIGN].*asset=BTC' logs/full.log | grep -o 'lag_rel_bps=[0-9.]*' | cut -d= -f2 | sort -n | uniq -c

# Count alignment pass vs fail
grep '[CONTRACT-SPOT-ALIGN]' logs/full.log | grep 'lag_pass=True' | wc -l
grep '[CONTRACT-SPOT-ALIGN]' logs/full.log | grep 'lag_pass=False' | wc -l

# Check time skew distribution
grep '[CONTRACT-SPOT-ALIGN]' logs/full.log | grep -o 'delta_seconds=[0-9.]*' | cut -d= -f2 | sort -n | uniq -c
```

### 3. Check Cycle Summary

```bash
# View recent cycle summaries
grep '[CYCLE-SUMMARY]' logs/full.log | tail -20

# Extract markets_passing_shouldtrade over time
grep '[CYCLE-SUMMARY]' logs/full.log | grep -o 'markets_passing_shouldtrade=[0-9]*' | cut -d= -f2

# Check rejection breakdown
grep '[CYCLE-SUMMARY]' logs/full.log | tail -5
```

### 4. Check Asset Gate Summary

```bash
# View recent asset gate summaries
grep '[ASSET-GATE-SUMMARY]' logs/full.log | tail -20

# Check which assets have pass > 0
grep '[ASSET-GATE-SUMMARY]' logs/full.log | grep 'pass=[1-9]' | tail -10

# Check dominant rejection reason per asset
grep '[ASSET-GATE-SUMMARY].*asset=BTC' logs/full.log | tail -5
```

### 5. Check Signal Errors

```bash
# Count signal errors by stage
grep '[SIGNAL-ERROR]' logs/full.log | grep -o 'stage=[a-z_]*' | sort | uniq -c

# View recent signal errors
grep '[SIGNAL-ERROR]' logs/full.log | tail -20
```

### 6. Check Spot Service Health

```bash
# View spot tick arrivals
grep 'UNIFIED-SPOT-TICK' logs/full.log | tail -20

# Check spot staleness
grep '[SPOT-STALE-SKIP]' logs/full.log | wc -l
```

## Analysis Checklist

### Step 1: Identify Dominant Rejection Reason

1. Check CYCLE-SUMMARY to see which `blocked_by_*` counter is highest
2. Check ASSET-GATE-SUMMARY to see if rejection is asset-specific or systemic
3. If `blocked_by_lag` dominates, proceed to Step 2
4. If `blocked_by_spread` dominates, check spread thresholds
5. If `blocked_by_liquidity` dominates, check depth thresholds
6. If `blocked_by_indicator` dominates, check edge thresholds
7. If `blocked_by_risk` or `blocked_by_cooldown` dominates, check risk/cooldown settings

### Step 2: Analyze Lag Gate (if dominant)

1. Extract `lag_rel_bps` distribution from CONTRACT-SPOT-ALIGN logs
2. Calculate 95th and 99th percentiles of `lag_rel_bps` per asset
3. Compare current `max_rel_diff_bps` in `KALSHI_ALIGNMENT_TOLERANCES` to empirical distribution
4. If current threshold is below 95th percentile, increase to 95th or 99th percentile
5. Verify `delta_seconds` distribution is within `max_allowed_time_skew` (2s)

### Step 3: Verify Lag Gate Logic

1. Find examples where `lag_rel_bps < max_rel_diff_bps` but `lag_pass=False`
2. Find examples where `lag_rel_bps > max_rel_diff_bps` but `lag_pass=True`
3. If found, check for logical inversion in lag gate code
4. Verify `lag_abs_diff` and `delta_seconds` checks are correct

### Step 4: Check Other Gates (if lag is not dominant)

1. For spread: Check `spread_cents` distribution vs spread threshold
2. For liquidity: Check `depth_at_top` distribution vs depth threshold
3. For indicator: Check `edge` distribution vs edge threshold
4. For risk/cooldown: Check if risk limits or cooldown are too aggressive

### Step 5: Verify Pipeline Can Pass Markets

1. Temporarily relax dominant gate threshold
2. Run system for 15-30 minutes
3. Check if `markets_passing_shouldtrade > 0` in CYCLE-SUMMARY
4. Check if `pass > 0` in ASSET-GATE-SUMMARY
5. If yes, gradually re-tighten threshold to acceptable level
6. If no, check next dominant gate

## Threshold Tuning Procedure

### Lag Threshold Tuning

1. Extract `lag_rel_bps` distribution:
   ```bash
   grep '[CONTRACT-SPOT-ALIGN].*asset=BTC' logs/full.log | grep -o 'lag_rel_bps=[0-9.]*' | cut -d= -f2 | sort -n > btc_lag_bps.txt
   ```

2. Calculate percentiles (Python):
   ```python
   import numpy as np
   data = np.loadtxt('btc_lag_bps.txt')
   p95 = np.percentile(data, 95)
   p99 = np.percentile(data, 99)
   print(f"95th percentile: {p95:.2f} bps")
   print(f"99th percentile: {p99:.2f} bps")
   ```

3. Update `KALSHI_ALIGNMENT_TOLERANCES` in `agent_grid_15m.py`:
   ```python
   "BTC": {
       "max_rel_diff_bps": int(p95),  # or p99 for more permissive
       ...
   }
   ```

4. Restart system and verify improvement

### Spread Threshold Tuning

1. Extract `spread_cents` distribution from SIGNAL-GATE-TRACE logs
2. Calculate 95th percentile
3. Update spread threshold in agent config or code
4. Restart and verify

### Edge Threshold Tuning

1. Extract `edge` distribution from SIGNAL-EDGE logs
2. Calculate 95th percentile
3. Update edge threshold in agent config or profile
4. Restart and verify

## Expected Healthy State

In a healthy dry run, you should see:

- `markets_seen > 0` in CYCLE-SUMMARY
- `markets_with_md > 0` in CYCLE-SUMMARY
- `markets_with_spot > 0` in CYCLE-SUMMARY
- `markets_passing_shouldtrade > 0` intermittently in CYCLE-SUMMARY
- `pass > 0` intermittently in ASSET-GATE-SUMMARY for at least some assets
- No repeated `[SIGNAL-ERROR]` logs
- `lag_rel_bps` distribution mostly within `max_rel_diff_bps` threshold
- `delta_seconds` distribution mostly within `max_allowed_time_skew` threshold

## Common Issues and Fixes

### Issue: 100% blocked_by_lag

**Diagnosis:**
- Check if `lag_rel_bps` distribution is above threshold
- Check if `delta_seconds` is above threshold
- Check if spot service is stale (UNIFIED-SPOT-TICK frequency)

**Fix:**
- Increase `max_rel_diff_bps` to 95th percentile of empirical distribution
- Increase `max_allowed_time_skew` if time skew is high
- Fix spot service staleness if present

### Issue: 100% blocked_by_spread

**Diagnosis:**
- Check spread distribution vs threshold
- Check if markets are illiquid

**Fix:**
- Increase spread threshold temporarily
- Filter to more liquid markets
- Check if spread calculation is correct

### Issue: 100% blocked_by_indicator

**Diagnosis:**
- Check edge distribution vs threshold
- Check if edge calculation is correct

**Fix:**
- Lower edge threshold temporarily
- Check SIGNAL-EDGE logs for edge values
- Verify edge calculation logic

### Issue: SIGNAL-ERROR in get_spot_price

**Diagnosis:**
- Check spot service health
- Check network connectivity to Coinbase

**Fix:**
- Fix spot service connectivity
- Add retry logic if transient
- Check spot service logs

## Next Steps After Analysis

1. Identify dominant rejection reason
2. Tune thresholds based on empirical distribution
3. Verify pipeline can pass markets with relaxed thresholds
4. Gradually re-tighten to production levels
5. Monitor for stable `markets_passing_shouldtrade > 0`
6. Proceed to live trading verification
