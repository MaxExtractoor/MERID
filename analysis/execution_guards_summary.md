# Kalshi 15M Micro-Scalping: Execution Guards Implementation

## Three-Layer Fatal Execution Protection

### Layer 1: Asset Whitelist
```python
ALLOWED_ASSETS = {"BTC", "ETH", "SOL", "XRP", "DOGE"}
```
- **Action**: Block any non-crypto or non-approved assets
- **Log**: `[EXECUTION_BLOCKED] asset=X tf=Y reason=invalid_asset`

### Layer 2: Timeframe Gate (FATAL - No Fallback)
```python
EXECUTION_TIMEFRAMES = {"15m"}
```
- **Action**: Block 1h/daily/weekly from executing (signal-only)
- **Log**: `[EXECUTION_BLOCKED] asset=X tf=1h reason=non_15m_timeframe signal_only=true`
- **Note**: 1h/daily/weekly can still inform signals but CANNOT place orders

### Layer 3: Distance + Edge Guards

#### 3a. Hard Distance Caps (|delta_pct|)
| Asset | MAX_DELTA_PCT | Description |
|-------|---------------|---------------|
| BTC | 0.75% | Tightest - liquid, tight spreads |
| ETH | 1.00% | Tight |
| SOL | 1.25% | Moderate |
| XRP | 1.50% | Wider |
| DOGE | 1.75% | Widest - jumpiest asset |

**Log**: `[EXECUTION_BLOCKED] asset=X tf=15m reason=distance_too_far delta_pct=0.1064 max_delta_pct=0.0075 z=10.64`

#### 3b. Sigma-Based Distance Cap
```python
MAX_Z_DISTANCE = 0.75  # 0.75 sigma max
```
- Auto-tightens in low-vol regimes
- Gives slightly more room in high-vol regimes

**Log**: `[EXECUTION_BLOCKED] asset=X tf=15m reason=distance_too_far_z z=0.82 max_z=0.75`

#### 3c. Edge Floor (Near vs Far Contracts)

| Asset | MIN_EDGE_NEAR (|z| ≤ 0.5) | MIN_EDGE_FAR (|z| > 0.5) |
|-------|---------------------------|--------------------------|
| BTC | 5.5% | 7.5% |
| ETH | 5.5% | 7.5% |
| SOL | 6.0% | 8.0% |
| XRP | 6.0% | 8.0% |
| DOGE | 6.5% | 8.5% |

**Log**: `[EXECUTION_BLOCKED] asset=X tf=15m reason=edge_too_low edge=0.042 required_edge=0.055 contract_type=near`

---

## Regression Test Commands

### Verify 15m-Only Execution
```bash
# Should return EMPTY (no non-15m executions)
grep "\[TRADE_ENTRY\]" logs/trading_*.log | grep -v "15m"

# Should show blocked non-15m attempts
grep "\[EXECUTION_BLOCKED\]" logs/trading_*.log | grep "reason=non_15m_timeframe"
```

### Verify Asset Whitelist
```bash
# Should show blocked non-crypto assets (if any attempt)
grep "\[EXECUTION_BLOCKED\]" logs/trading_*.log | grep "reason=invalid_asset"
```

### Verify Distance Guards
```bash
# Find blocked far-OTM contracts
grep "\[EXECUTION_BLOCKED\]" logs/trading_*.log | grep "reason=distance_too_far"

# Check those $85,300 BTC trades would be blocked
grep "\[EXECUTION_BLOCKED\]" logs/trading_*.log | grep "T85300\|85300"

# Should show: delta_pct > 0.0075 (e.g., 0.1064 = 10.6%)
```

### Verify Edge Guards
```bash
# Find blocked low-edge trades
grep "\[EXECUTION_BLOCKED\]" logs/trading_*.log | grep "reason=edge_too_low"

# Verify new higher thresholds are enforced
grep "\[EXECUTION_BLOCKED\]" logs/trading_*.log | grep "edge_too_low" | \
  awk -F'required_edge=' '{print $2}' | awk '{print $1}' | sort | uniq
# Expected: 0.055, 0.060, 0.065, 0.075, 0.080, 0.085
```

### Summary Statistics
```bash
# Count blocks by reason
grep "\[EXECUTION_BLOCKED\]" logs/trading_*.log | \
  sed -n 's/.*reason=\([^ ]*\).*/\1/p' | sort | uniq -c

# Count successful entries
grep "\[TRADE_ENTRY\]" logs/trading_*.log | wc -l
```

---

## Invariant Checks (Production Safety)

Run these periodically to verify guards are working:

```python
# Python validation script
import re

def validate_guards(log_file: str) -> dict:
    results = {
        "non_15m_entries": [],
        "non_15m_blocks": [],
        "invalid_asset_blocks": [],
        "distance_blocks": [],
        "edge_blocks": [],
        "valid_entries": [],
    }
    
    with open(log_file) as f:
        for line in f:
            # Check for non-15m entries (SHOULD NOT EXIST)
            if "[TRADE_ENTRY]" in line and "15m" not in line:
                results["non_15m_entries"].append(line.strip())
            
            # Count valid entries
            if "[TRADE_ENTRY]" in line and "15m" in line:
                results["valid_entries"].append(line.strip())
            
            # Count blocks by type
            if "[EXECUTION_BLOCKED]" in line:
                if "reason=non_15m_timeframe" in line:
                    results["non_15m_blocks"].append(line.strip())
                elif "reason=invalid_asset" in line:
                    results["invalid_asset_blocks"].append(line.strip())
                elif "reason=distance_too_far" in line:
                    results["distance_blocks"].append(line.strip())
                elif "reason=edge_too_low" in line:
                    results["edge_blocks"].append(line.strip())
    
    return results

# Run validation
results = validate_guards("logs/trading_2026-05-01.log")

# Assertions (must pass)
assert len(results["non_15m_entries"]) == 0, "CRITICAL: Non-15m executions detected!"
assert len(results["non_15m_blocks"]) > 0 or len(results["valid_entries"]) > 0, "No activity detected"

print(f"✓ Valid 15m entries: {len(results['valid_entries'])}")
print(f"✓ Non-15m blocked: {len(results['non_15m_blocks'])}")
print(f"✓ Invalid asset blocked: {len(results['invalid_asset_blocks'])}")
print(f"✓ Distance too far blocked: {len(results['distance_blocks'])}")
print(f"✓ Edge too low blocked: {len(results['edge_blocks'])}")
print("✓ All invariants passed")
```

---

## Example Log Output

### Blocked Trade (Those $85,300 BTC Contracts)
```
[EXECUTION_BLOCKED] asset=BTC tf=15m reason=distance_too_far \
  delta_pct=0.10636 max_delta_pct=0.0075 z=10.64 max_z=0.75 \
  spot=77100.0 strike=85300.0
```

### Blocked Trade (Edge Too Low)
```
[EXECUTION_BLOCKED] asset=BTC tf=15m reason=edge_too_low \
  edge=0.042 required_edge=0.055 contract_type=near
```

### Blocked Trade (Non-15m Timeframe)
```
[EXECUTION_BLOCKED] asset=BTC tf=1h reason=non_15m_timeframe signal_only=true \
  Note: 1h/daily/weekly may be used for signal/context but CANNOT execute
```

### Successful Entry (Passes All Guards)
```
[TRADE_ENTRY] KXBTC-15M-250501-T77616 | asset_tf=BTC:15m | edge=0.065 | conf=0.72 |
  size=4 | price=52c | SL=2.0c | DTP=6.0% | trail=1.5%@+1.5% | max_hold=180s |
  corr_id=a1b2c3d4e5f67890 |
  spot=77100.0 strike=77616.0 delta_pct=0.00670 delta_bps=67.0 z=0.67 \
  sigma_15m=0.010 kalshi_price=0.52 implied_prob=0.52 model_prob=0.585 \
  edge=0.065 EV_gross=0.065 fee=0.0175 EV_net=0.047
```

---

## Configuration Parameters

All guard parameters are in `trading_agent.py`:

```python
# Lines 181-226
MAX_DELTA_PCT = {...}        # Hard distance caps
MAX_Z_DISTANCE = 0.75         # Sigma-based cap
Z_NEAR_THRESHOLD = 0.50     # Near vs far threshold
MIN_EDGE_NEAR = {...}        # Edge floors for near contracts
MIN_EDGE_FAR = {...}         # Edge floors for far contracts (+2%)
ALLOWED_ASSETS = {...}       # Asset whitelist
EXECUTION_TIMEFRAMES = {...} # 15m-only
```

---

## Post-Launch Calibration

After 100+ trades, analyze these buckets:

| Bucket | Metric | Action if Underperforming |
|--------|--------|--------------------------|
| Distance B1 (≤0.25%) | Win rate, EV_net | Reduce min_edge slightly |
| Distance B4 (>0.75%) | Win rate, EV_net | Already blocked by guard |
| Edge 4-6% | Win rate < 50% | Raise MIN_EDGE_NEAR by +0.5% |
| Edge 6-8% | EV_net < 0 | Investigate model calibration |
| BTC vs DOGE | PnL per contract | Adjust per-asset sigma/edge |

SQL queries in `edge_post_analysis.sql` provide the analysis framework.
