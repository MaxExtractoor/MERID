# Cross-Asset Arbiter QA Checklist — Production Readiness

**Module:** `merid/prediction/crypto_top_edge.py`  
**Purpose:** Cross-asset top-edge selection with momentum scalping alignment  
**Version:** Production Ready (v2.0)  
**Date:** 2025-01-24

---

## Executive Summary

This checklist ensures the cross-asset arbiter is production-ready with:
- Timeframe filtering (15m, 1h only for momentum scalping)
- Position-aware deduplication (prevent double orders)
- In-cycle deduplication by (market, direction, strategy_family)
- Alignment with continuous trader's max_edges
- Risk cap respect downstream
- Rapid reversal and loop-lag resilience

---

## Section 1: Upstream Data Validation

### 1.1 Signal Source Validation
- [ ] **Agent Signal Format**: Verify all crypto agents emit signals with `net_edge`, `confidence`, `direction`, `timeframe`
- [ ] **Asset Extraction**: Confirm `_extract_asset_from_market_id()` correctly maps all Kalshi market IDs to BTC/ETH/SOL/XRP/DOGE
- [ ] **Timeframe Parsing**: Verify agents set `timeframe` field correctly (15m, 1h, daily, weekly)
- [ ] **Edge Calculation**: Ensure `net_edge` is net of fees and properly normalized

**Test Command:**
```bash
py -m pytest tests/test_crypto_top_edge.py::TestCrossAssetSelection -v
```

### 1.2 Position Cache Integration
- [ ] **Position Cache Available**: Verify `merid/event_venues/kalshi/position_cache.py` is accessible
- [ ] **Reconciliation Ground Truth**: Confirm fills + reconciliation populate position cache
- [ ] **Position Data Format**: Verify position cache returns `(contracts, direction, entry_time)` per ticker
- [ ] **Stale Position Handling**: Confirm positions older than `max_hold_minutes` are treated as fresh

**Verification:**
```python
from merid.event_venues.kalshi.position_cache import get_position_cache
cache = get_position_cache()
positions = cache.get_open_positions("KXBTC15M-TEST")
assert "contracts" in positions
assert "direction" in positions
assert "entry_time" in positions
```

### 1.3 Continuous Trader Alignment
- [ ] **TOP_N Match maxedges**: Verify `CRYPTO_TOP_EDGE_TOP_N` equals continuous trader's `maxedges` setting
- [ ] **Environment Variable Consistency**: Confirm both systems read from same config source
- [ ] **Logging Consistency**: Check that both use same log tags for cross-referencing

**Config Check:**
```bash
echo "Arbiter TOP_N: $CRYPTO_TOP_EDGE_TOP_N"
echo "Trader maxedges: $KALSHI_CT_MAXEDGES"
```

---

## Section 2: Mid-Pipeline Arbiter Checks

### 2.1 Timeframe Filtering
- [ ] **15m Accepted**: Signals with `timeframe="15m"` pass through
- [ ] **1h Accepted**: Signals with `timeframe="1h"` pass through
- [ ] **Daily Rejected**: Signals with `timeframe="daily"` are dropped at submission
- [ ] **Weekly Rejected**: Signals with `timeframe="weekly"` are dropped at submission
- [ ] **Config Override**: `MEAN_REVERSION_TIMEFRAMES` env var can customize allowed timeframes

**Test Command:**
```bash
py -m pytest tests/test_crypto_top_edge_stress.py::TestTimeframeFiltering -v
```

### 2.2 Position-Aware Deduplication
- [ ] **No Position**: Candidate with no position is allowed
- [ ] **Same Direction Full**: Candidate already at target size is rejected with reason `position_already_at_target_size`
- [ ] **Partial Position**: Candidate below target emits incremental size only
- [ ] **Opposite Direction**: Candidate in opposite direction is allowed (risk layer handles flip)
- [ ] **Expired Position**: Position older than `max_hold_minutes` is treated as fresh
- [ ] **Metrics Tracked**: `rejected_by_position_dup` and `deduped_contracts_saved` are accurate

**Test Command:**
```bash
py -m pytest tests/test_crypto_top_edge_stress.py::TestPositionAwareDeduplication -v
```

### 2.3 In-Cycle Deduplication
- [ ] **Duplicate Detection**: Same `(ticker, direction, archetype)` within cycle is blocked
- [ ] **Different Direction**: Same ticker, different directions are both allowed
- [ ] **Different Archetype**: Same ticker/direction, different archetypes are both allowed
- [ ] **Fingerprint Format**: Dedup key is `ticker:direction:strategy_family`
- [ ] **Cycle Reset**: Fingerprints clear between cycles

**Test Command:**
```bash
py -m pytest tests/test_crypto_top_edge_stress.py::TestInCycleDeduplication -v
```

### 2.4 Dynamic Floor Calculation
- [ ] **Cross-Sectional Stats**: Top, median, std are calculated correctly
- [ ] **Floor from Top**: `floor_from_top = max(0, gamma * top_edge)`
- [ ] **Floor from Median**: `floor_from_median = max(0, gamma * median_edge)`
- [ ] **Conservative Floor**: `dynamic_floor = max(floor_from_top, floor_from_median)`
- [ ] **Global Floor**: Rolling history floor is applied when sufficient samples
- [ ] **Final Floor**: `final_floor = max(dynamic_floor, global_floor, min_edge_absolute)`

**Test Command:**
```bash
py -m pytest tests/test_crypto_top_edge.py::TestCryptoTopEdgeArbiter::test_floor_calculation -v
```

---

## Section 3: Downstream Strike Selection and Risk Guard

### 3.1 Risk Engine Integration
- [ ] **Winner Forwarding**: Top N winners are passed to risk engine correctly
- [ ] **Contract Sizing**: Incremental contracts from partial fills are respected
- [ ] **Risk Cap Respect**: Risk engine's `maxcycleriskpct` is enforced downstream
- [ ] **CapitalEngine Cap**: Per-asset caps are respected

### 3.2 Allocator Integration
- [ ] **TradeIntent Creation**: Winners are converted to `TradeIntent` for `Crypto15MAllocator`
- [ ] **Intent Submission**: Intents are submitted with mode="intent_only" for allocator
- [ ] **Budget Respect**: Allocator timeframe budget is respected
- [ ] **Expiry Cap**: Per-expiry open exposure cap is enforced

### 3.3 Execution Path
- [ ] **Order Router**: Winning intents reach order router
- [ ] **Fill Reconciliation**: Fills update position cache (ground truth)
- [ ] **Idempotency**: Duplicate orders rejected at order store level as backup

---

## Section 4: Rapid Reversal & Loop Lag Stress Tests

### 4.1 Rapid Reversal Scenario
**Scenario:** BTC flips from long to short within 2 cycles

1. **Cycle 1:**
   - Submit: BTC 15m long edge=0.05
   - Submit: BTC 15m short edge=0.03
   - Expected: Long wins, short rejected (lower edge)

2. **Cycle 2:**
   - Position: BTC long 5 contracts (from Cycle 1)
   - Submit: BTC 15m long edge=0.04 (duplicate)
   - Submit: BTC 15m short edge=0.06 (reversal)
   - Expected: Long rejected (position dup), short wins (flip)

**Test:**
```bash
py -m pytest tests/test_crypto_top_edge_stress.py::TestRapidReversals -v
```

### 4.2 Loop Lag Scenario
**Scenario:** 30-second loop lag causes stale position data

1. **Cycle 1:**
   - Submit: ETH 15m long with position from 1 hour ago
   - Expected: Allowed (position expired)

2. **Cycle 2:**
   - Submit: ETH 15m long with position from 10 minutes ago
   - Expected: Rejected (position valid, at target)

3. **Cycle 3:**
   - Submit: ETH 15m long with partial position (2/5 contracts)
   - Expected: Allowed with incremental=3

**Test:**
```bash
py -m pytest tests/test_crypto_top_edge_stress.py::TestLoopLagResilience -v
```

### 4.3 Convergent Strategies Scenario
**Scenario:** Multiple strategies converge on same market

1. **Same Cycle:**
   - Submit: BTC directional long
   - Submit: BTC contrarian long (different archetype)
   - Submit: BTC directional long (duplicate)
   - Expected: Both directional and contrarian allowed, duplicate blocked

**Test:**
```bash
py -m pytest tests/test_crypto_top_edge_stress.py::TestInCycleDeduplication::test_different_archetypes_allowed -v
```

---

## Section 5: Configuration and Environment

### 5.1 Environment Variables
| Variable | Default | Description |
|----------|---------|-------------|
| `CRYPTO_TOP_EDGE_GAMMA` | 0.5 | Dynamic floor as % of top edge [0.3, 0.7] |
| `CRYPTO_TOP_EDGE_ALPHA` | 0.0 | μ + α·σ floor (0 = use median) |
| `CRYPTO_TOP_EDGE_TOP_N` | 2 | How many winners per cycle |
| `CRYPTO_TOP_EDGE_MIN_EDGE` | 0.0 | Absolute minimum edge |
| `CRYPTO_TOP_EDGE_MAX_HOLD_MIN` | 240 | Max position hold time for scalps |
| `CRYPTO_TOP_EDGE_POSITION_DEDUP` | True | Enable position deduplication |
| `CRYPTO_TOP_EDGE_CYCLE_DEDUP` | True | Enable in-cycle deduplication |

**Verification:**
```bash
echo "=== Environment Configuration ==="
env | grep CRYPTO_TOP_EDGE
```

### 5.2 Continuous Trader Alignment
- [ ] `CRYPTO_TOP_EDGE_TOP_N` matches continuous trader `maxedges`
- [ ] Both use same BTC/ETH/SOL/XRP/DOGE asset set
- [ ] Log tags are consistent for cross-referencing

---

## Section 6: Logging and Observability

### 6.1 Log Tags
- `[CRYPTO_TOP_EDGE]` — Cycle execution summary
- `[CRYPTO_TOP_EDGE_WINNER]` — Per-winner details
- `[CRYPTO_TOP_EDGE] consensus_hold_by_reason=...` — All candidates rejected
- `[CRYPTO_TOP_EDGE] DEDUP: ...` — Position deduplication
- `[CRYPTO_TOP_EDGE] PARTIAL: ...` — Partial fill handling
- `[CRYPTO_TOP_EDGE] CYCLE_DEDUP: ...` — In-cycle deduplication

### 6.2 Metrics Available
```python
metrics = arbiter.get_metrics()
# {
#     "cycles_run": int,
#     "total_winners": int,
#     "winners_per_cycle": float,
#     "total_contracts_deduped": int,
#     "config": { ... }
# }
```

### 6.3 Result Serialization
```python
result = arbiter.run_cycle()
data = result.to_dict()
# Includes: rejected_by_position_dup, rejected_by_cycle_dup, 
#          deduped_contracts_saved, timeframes_considered
```

---

## Section 7: Production Safety Checklist

### Before Restart Checklist
- [ ] All environment variables are set in production config
- [ ] Position cache is populated and reconciled
- [ ] Continuous trader maxedges matches arbiter TOP_N
- [ ] Risk engine caps are configured correctly
- [ ] Allocator budgets are set for 15m and 1h timeframes
- [ ] Log aggregation is configured for `[CRYPTO_TOP_EDGE]` tags
- [ ] Metrics endpoint is accessible for monitoring
- [ ] Circuit breaker is configured for rapid reversal scenarios

### Monitoring Alerts
- [ ] Alert if `winners_per_cycle` drops below 0.5 for 10 cycles
- [ ] Alert if `rejected_by_position_dup` exceeds 50% of candidates
- [ ] Alert if `rejected_by_cycle_dup` exceeds 30% of candidates
- [ ] Alert if arbiter cycle time exceeds 100ms

### Rollback Plan
1. Set `CRYPTO_TOP_EDGE_POSITION_DEDUP=false` to disable position dedup
2. Set `CRYPTO_TOP_EDGE_CYCLE_DEDUP=false` to disable cycle dedup
3. Set `CRYPTO_TOP_EDGE_TOP_N=0` to bypass arbiter entirely
4. Revert to `KalshiStrategy._min_edge_for_phase()` hard thresholds

---

## Section 8: Test Summary

### Unit Tests
```bash
py -m pytest tests/test_crypto_top_edge.py -v
```
- `test_initialization` — Arbiter config
- `test_floor_calculation` — Dynamic floor math
- `test_winner_selection_top_n` — Top N selection
- `test_few_qualified_candidates_high_floor` — Edge cases
- `test_all_candidates_below_floor` — Rejection logging
- `test_rolling_edge_history` — History tracking

### Stress Tests
```bash
py -m pytest tests/test_crypto_top_edge_stress.py -v
```

**Timeframe Filtering (6 tests)**
- `test_only_15m_accepted`
- `test_only_1h_accepted`
- `test_daily_rejected`
- `test_weekly_rejected`
- `test_mixed_timeframes_filtered`

**Position-Aware Deduplication (7 tests)**
- `test_no_position_allows_entry`
- `test_same_direction_at_target_rejected`
- `test_same_direction_above_target_rejected`
- `test_partial_position_emits_incremental`
- `test_opposite_direction_allowed`
- `test_expired_position_treated_as_fresh`
- `test_position_dedup_disabled`

**In-Cycle Deduplication (4 tests)**
- `test_same_ticker_direction_archetype_blocked`
- `test_different_directions_allowed`
- `test_different_archetypes_allowed`
- `test_cycle_dedup_disabled`

**Rapid Reversals (2 tests)**
- `test_reversal_same_cycle`
- `test_consecutive_cycles_deduplication_reset`

**Loop Lag Resilience (2 tests)**
- `test_stale_position_data_handled`
- `test_partial_fills_accumulate`

**Full Flow Integration (2 tests)**
- `test_full_flow_with_deduplication`
- `test_cross_asset_competition`

**Metrics (2 tests)**
- `test_metrics_include_dedup_stats`
- `test_result_serialization_includes_dedup`

### Total: 25+ tests covering all production scenarios

---

## Section 9: Sign-off

| Role | Name | Date | Signature |
|------|------|------|-----------|
| Developer | AI Assistant | 2025-01-24 | ✓ |
| Code Review | [Pending] | | |
| QA Engineer | [Pending] | | |
| DevOps | [Pending] | | |
| Product Owner | [Pending] | | |

**Production Ready:** ☐ Yes ☐ No ☐ Conditional

**Conditions for Conditional:**
- [ ] Integration tests with live position cache
- [ ] Staging deployment with paper trading
- [ ] 24-hour burn-in period

---

## Appendix: Quick Reference

### Minimal Config for Production
```bash
export CRYPTO_TOP_EDGE_GAMMA=0.5
export CRYPTO_TOP_EDGE_TOP_N=2
export CRYPTO_TOP_EDGE_MAX_HOLD_MIN=240
export CRYPTO_TOP_EDGE_POSITION_DEDUP=true
export CRYPTO_TOP_EDGE_CYCLE_DEDUP=true
```

### Debug Config for Troubleshooting
```bash
export CRYPTO_TOP_EDGE_GAMMA=0.3
export CRYPTO_TOP_EDGE_TOP_N=5
export CRYPTO_TOP_EDGE_POSITION_DEDUP=false
export CRYPTO_TOP_EDGE_CYCLE_DEDUP=false
```

### Emergency Stop
```bash
export CRYPTO_TOP_EDGE_TOP_N=0
# Restarts will bypass arbiter, use hard thresholds only
```

---

*End of QA Checklist*
