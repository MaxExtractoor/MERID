# MERID High-Leverage Audit Findings
**Comprehensive Code Audit - Execution Path & Profitability Impact**
**Date:** May 1, 2026  
**Focus:** 15m-only micro-momentum scalping system

---

## EXECUTIVE SUMMARY

This audit identified **15 high-leverage issues** across the MERID codebase that directly impact profitability in the 15m micro-scalping system. Issues are categorized by severity and potential PnL impact.

---

## 🔴 CRITICAL (Immediate Fix Required)

### 1. Execution Guard Gaps - Far-OTM Contract Leakage
**File:** `merid/prediction/kalshi_strike_selector.py`  
**Line:** ~235-250 (DEFAULT_MAX_DISTANCE table)

**Issue:** The legacy `DEFAULT_MAX_DISTANCE` table in strike selector allows:
- BTC 15m: 6% max distance (0.06)
- ETH 15m: 6% max distance (0.06)

But our new execution guards enforce 0.75% max. This creates **conflicting authority** - the strike selector may pass contracts that the execution guard later blocks, wasting compute and causing confusion.

**Fix:** Synchronize `DEFAULT_MAX_DISTANCE` with new `MAX_DELTA_PCT`:
```python
DEFAULT_MAX_DISTANCE = {
    ("BTC", "15m"): 0.0075,  # was 0.06 - now matches execution guard
    ("ETH", "15m"): 0.0100,  # was 0.06
    ("SOL", "15m"): 0.0125,
    ("XRP", "15m"): 0.0150,
    ("DOGE", "15m"): 0.0175,
}
```

**Profitability Impact:** HIGH - Prevents wasted cycles on far-OTM contracts that would be blocked anyway.

---

### 2. YAML Config Edge Thresholds Too Low (Misalignment)
**File:** `config/kalshi_agent_grid.yaml`

**Issue:** YAML config has:
```yaml
min_edge_early: 0.025  # 2.5%
min_edge_mid: 0.020    # 2.0%
```

But our new execution guards require:
```python
MIN_EDGE_NEAR = {
    "BTC": 0.055,  # 5.5%
    "ETH": 0.055,
    "SOL": 0.060,
    "XRP": 0.060,
    "DOGE": 0.065,
}
```

**This 3% gap means agents will generate signals that get blocked by execution guards**, causing:
- Wasted compute cycles
- False confidence in signal quality
- Confusing logs ("why was my trade blocked?")

**Fix:** Update YAML to match execution guard thresholds:
```yaml
min_edge_early: 0.055   # was 0.025
min_edge_mid: 0.055     # was 0.020
min_edge_late: 0.060    # was 0.018
min_edge_terminal: 0.065 # was 0.025
```

**Profitability Impact:** HIGH - Eliminates edge-filtered waste; ensures signal generation aligns with execution reality.

---

### 3. Fee Calculation Inconsistency Across Modules
**Files:** 
- `merid/prediction/trading_agent.py` (uses 0.07 * P * (1-P))
- `merid/event_venues/kalshi/order_router.py` (uses `calculate_kalshi_fee_cents`)
- `merid/event_venues/kalshi/fees.py` (canonical tiered: 7%/5%/3%)
- `merid/prediction/risk.py` (uses `kalshi_fee_cents`)

**Issue:** Two different fee formulas in use:
1. **Simplified:** `0.07 * C * P * (1-P)` (trading_agent.py, line 250)
2. **Canonical:** Tiered rates with 7%/5%/3% (fees.py, line 47-50)

This causes **EV calculation drift** - edge metrics may show profitable trades that are actually losers after correct fees.

**Evidence:**
```python
# trading_agent.py:250
fee_per_contract = 0.07 * kalshi_price * (1.0 - kalshi_price)

# fees.py:47-50
TIER_RATES = {
    (0, 100): Decimal("0.07"),
    (100, 1000): Decimal("0.05"),
    (1000, 999999999): Decimal("0.03"),
}
```

**Fix:** Standardize all fee calculations to use `calculate_kalshi_fee_cents` from `merid.event_venues.kalshi.fees`.

**Profitability Impact:** CRITICAL - Wrong fee math = wrong EV = wrong trades.

---

### 4. Strike Selection Config vs Execution Guard Misalignment
**File:** `config/kalshi_agent_grid.yaml:57`

**Issue:** YAML config has:
```yaml
strike_selection:
  max_spot_to_strike_pct: 0.15   # 15%
  target_spot_band_pct: 0.06     # 6%
```

This is **20x wider** than the 0.75% execution guard. Agents will attempt to select strikes at 6% that will never execute.

**Fix:** Update YAML to match execution guards:
```yaml
strike_selection:
  max_spot_to_strike_pct: 0.0075   # 0.75% for BTC (align with MAX_DELTA_PCT)
  target_spot_band_pct: 0.003      # 0.3% target
```

**Profitability Impact:** HIGH - Prevents selection waste; focuses on executable strikes only.

---

## 🟠 HIGH (Fix This Week)

### 5. Non-15m Timeframe Agents Still Configured to Execute
**File:** `config/kalshi_agent_grid.yaml`

**Issue:** Config still has:
- `BTC_HOURLY` agent with `timeframes: [1h]`
- `BTC_DAILY` agent with `timeframes: [daily]`
- `BTC_WEEKLY` agent with `timeframes: [weekly]`

While execution guards will block these, they still:
- Consume CPU cycles
- Generate noise in logs
- Create confusion in monitoring

**Fix:** Either:
1. **Option A:** Remove non-15m agents from active config (keep as reference only)
2. **Option B:** Add `enabled: false` flag to non-15m agents
3. **Option C:** Create separate `kalshi_agent_grid_15m_only.yaml` for production

**Profitability Impact:** MEDIUM - Clean execution surface; no wasted cycles on blocked timeframes.

---

### 6. Edge Metrics Log Without Spot Price Fallback
**File:** `merid/prediction/trading_agent.py:6144-6162`

**Issue:** Edge metrics computation has:
```python
_spot_price = None
try:
    from merid.prediction.price_feed import get_latest_spot
    _spot_price = get_latest_spot(_trade_asset)
except Exception:
    _spot_price = None

if _spot_price and _strike_price:
    # compute metrics
else:
    # fallback - log without distance metrics
```

When spot is unavailable, we lose:
- Distance tracking (delta_pct, z_score)
- Distance guard protection
- Post-trade analytics capability

**Fix:** Add fallback spot sources (CoinGecko, Coinbase, Binance) before giving up:
```python
if _spot_price is None:
    _spot_price = await _fetch_spot_from_coingecko(_trade_asset)
if _spot_price is None:
    _spot_price = await _fetch_spot_from_coinbase(_trade_asset)
```

**Profitability Impact:** MEDIUM - Prevents "flying blind" when primary feed fails.

---

### 7. Position Cache PnL Rounding Drift (P0-2)
**File:** `merid/event_venues/kalshi/position_cache.py:42`

**Issue:** Line 42 has comment:
```python
# P0-2 FIX: Use proper rounding instead of integer division to prevent PnL drift
self.avg_price_cents = round((total_cost_old + total_cost_new) / self.contracts)
```

While this is marked as fixed, the rounding approach can still cause **1-cent drift** on certain position sizes.

**Evidence:** 
- 100 contracts at 55¢ entry + 50 more at 56¢ = 5500 + 2800 = 8300 / 150 = 55.333... → rounds to 55
- Real average is 55.333, but cache stores 55
- Close at 60¢: cache shows (60-55)*150 = 750¢ profit
- Actual: (60-55.333)*150 = 700¢ profit
- **Drift: 50¢ on single trade**

**Fix:** Store `avg_price_cents` as `Decimal` with 2 decimal places, not integer.

**Profitability Impact:** MEDIUM - Accurate PnL = accurate risk decisions.

---

### 8. WebSocket Fill Processing Without Retry
**File:** `merid/event_venues\kalshi/ws_bridge.py`

**Issue:** From memory [0d162437], Bug 17: WS bridge fire-and-forget tasks missing done-callbacks. While this was fixed, there's a deeper issue:

WS fills can be **lost during reconnects** without HTTP poller backfill. The fills_ledger has dual ingestion, but the reconciler doesn't aggressively alert on missing fills.

**Fix:** Add fill-count-based reconciliation alert:
```python
# In fills_ledger.py reconciler:
if abs(ws_fill_count - http_fill_count) > 3:
    logger.error("[FILL_DRIFT] WS=%d HTTP=%d - potential fill loss", 
                 ws_fill_count, http_fill_count)
    # Trigger immediate backfill
```

**Profitability Impact:** HIGH - Lost fills = wrong positions = wrong risk = losses.

---

### 9. Take-Profit Config vs Dynamic TP Misalignment
**File:** `config/kalshi_agent_grid.yaml:47-55`

**Issue:** YAML config has:
```yaml
take_profit:
  r_multiple_primary: 0.5         # close at +50% of entry risk
  min_cents: 5                    # need at least 5¢ profit
```

But `trading_agent.py` uses `DynamicTPConfig` with per-asset volatility scaling:
```python
_dtp_cfg = DynamicTPConfig(
    low_volatility_target=0.04 if _is_major else 0.025,
    normal_volatility_target=0.06 if _is_major else 0.04,
)
```

Which takes precedence? The code shows both are used in different places.

**Fix:** Remove YAML take_profit section entirely; rely on `DynamicTPConfig` exclusively.

**Profitability Impact:** MEDIUM - Single source of truth for TP logic.

---

### 10. Bankroll Adapter Legacy Code
**File:** `merid/event_venues/kalshi/bankroll_adapter.py:18`

**Issue:** File contains:
```python
"""This adapter maps legacy calls to v2 internally.

TODO: Once all agents are migrated, delete this adapter and use v2 directly.
"""
```

This is technical debt that adds indirection and potential for drift between v1 and v2 calculations.

**Fix:** Complete the migration; delete `bankroll_adapter.py`; update all imports to use `bankroll_service_v2` directly.

**Profitability Impact:** LOW-MEDIUM - Simpler code = fewer bugs; single source of truth for bankroll.

---

## 🟡 MEDIUM (Fix Within 2 Weeks)

### 11. Frontend Constants Without Backend (BUG-E2)
**File:** `web/react/src/config/constants.ts`

**Issue:** From memory [4c296704], these constants have no backend:
- `KALSHI_PUBLISH_PIPELINE` → 404
- `KALSHI_NEWS_SIGNALS` → 404
- `KALSHI_FAVORITES` → 404

Users clicking these in the UI get 404s, appearing broken.

**Fix:** Either implement stub handlers returning `501 Not Implemented` or remove from frontend until ready.

**Profitability Impact:** LOW - UI polish; operator confidence.

---

### 12. Stop-Loss Floor Cents Static vs Dynamic Volatility
**File:** `merid/event_venues/kalshi/stop_loss.py:45`

**Issue:** `SL_PRICE_FLOOR_CENTS = 8` is hardcoded. For a 15m scalp, this should be dynamic based on:
- Asset volatility (BTC vs DOGE)
- Current spread
- Time to expiry

8¢ floor on a 15¢ spread DOGE contract is inappropriate.

**Fix:** Replace with per-asset dynamic floor:
```python
SL_PRICE_FLOOR_CENTS = {
    "BTC": 8,
    "ETH": 8,
    "SOL": 10,
    "XRP": 12,
    "DOGE": 15,  # Higher floor for volatile asset
}
```

**Profitability Impact:** MEDIUM - Prevents premature stops on volatile assets.

---

### 13. Contract Expiry Handling Gap
**File:** `merid/event_venues/kalshi/settlement_poller.py` (from search)

**Issue:** Settlement poller exists, but there's no **pre-settlement exit logic**. For 15m contracts, holding to expiry:
- Ties up capital
- Risks binary outcome
- Misses recycling opportunity

**Fix:** Add time-based exit rule: exit all positions 30 seconds before 15m expiry if not already profitable.

**Profitability Impact:** MEDIUM - Faster capital recycling; avoid binary risk.

---

### 14. Kelly Sizing Fee-Aware Check Inconsistency
**File:** `merid/event_venues/kalshi/kalshi_risk.py:178-217`

**Issue:** Kelly sizing checks `fee_pct > max_fee_to_notional_pct`, but this uses **estimated** fee (tier <100), not actual tier-based fee.

```python
# Line 214: Uses tier <100 assumption
fee_per = math.ceil(kalshi_fee_cents(price_cents, 1))

# But contracts may be 500+, which is tier 2 (5% rate)
```

**Fix:** Compute actual fee using final contract count estimate, not assumption.

**Profitability Impact:** MEDIUM - Right-sizing with correct fees.

---

### 15. Auto-Promoter Rollback Cooldown Not Persisted
**File:** `merid/event_venues/kalshi/auto_promoter.py:421-424`

**Issue:** Rollback cooldown is in-memory only (`self._last_rollback_ts`). Process restart = lost cooldown = potential rapid rollback/promote cycles.

**Fix:** Persist cooldown timestamps to SQLite or use TTL cache.

**Profitability Impact:** LOW - Prevents flapping on restart.

---

## QUICK WINS (Fix Today)

1. **Remove legacy bankroll adapter imports** - Search and replace 5 files
2. **Add 501 stubs for missing frontend constants** - 6 endpoints, 30 min work
3. **Fix YAML edge thresholds** - One file edit
4. **Sync strike selector distances** - One table update

---

## PRIORITY MATRIX

| Issue | PnL Impact | Effort | Priority |
|-------|------------|--------|----------|
| 3. Fee inconsistency | CRITICAL | Medium | 🔴 |
| 1. Strike selector gap | HIGH | Low | 🔴 |
| 2. YAML edge misalignment | HIGH | Low | 🔴 |
| 4. Strike config gap | HIGH | Low | 🔴 |
| 8. Fill reconciliation | HIGH | Medium | 🟠 |
| 6. Spot fallback | MEDIUM | Low | 🟠 |
| 7. PnL rounding | MEDIUM | Medium | 🟠 |
| 5. Non-15m agents | MEDIUM | Low | 🟠 |
| 9. TP config duality | MEDIUM | Low | 🟠 |
| 13. Pre-settlement exit | MEDIUM | Low | 🟡 |
| 14. Kelly fee check | MEDIUM | Low | 🟡 |
| 12. Dynamic SL floor | MEDIUM | Low | 🟡 |
| 10. Bankroll adapter | LOW-MED | High | 🟡 |
| 11. Frontend 404s | LOW | Low | 🟡 |
| 15. Cooldown persist | LOW | Low | 🟡 |

---

## VERIFICATION COMMANDS

```bash
# Check for fee formula inconsistencies
grep -r "0.07.*P.*(1-P)" merid/prediction/trading_agent.py

# Check YAML edge thresholds
grep "min_edge" config/kalshi_agent_grid.yaml

# Check for non-15m agents
grep -E "timeframes.*\[.*1h|daily|weekly" config/kalshi_agent_grid.yaml

# Check for missing backend endpoints (will 404)
grep -E "KALSHI_(PUBLISH_PIPELINE|NEWS_SIGNALS|FAVORITES)" web/react/src/config/constants.ts

# Check strike selector distances
grep -A5 "DEFAULT_MAX_DISTANCE" merid/prediction/kalshi_strike_selector.py
```

---

## SUMMARY

The most critical issues causing immediate profitability leakage:

1. **Fee calculation inconsistency** - Trades look profitable on paper but lose after fees
2. **Edge threshold misalignment** - 3% gap between generation and execution
3. **Strike distance gaps** - 20x difference between selector and execution guard
4. **Fill reconciliation** - Lost fills = wrong positions

**Recommended immediate actions:**
1. Fix fee standardization (Issue 3) - CRITICAL
2. Align YAML with execution guards (Issues 2, 4) - HIGH
3. Add spot price fallback (Issue 6) - HIGH
4. Complete fill reconciliation hardening (Issue 8) - HIGH

These 4 fixes will eliminate the majority of execution path friction and align the system with the 15m-only micro-momentum mandate.
