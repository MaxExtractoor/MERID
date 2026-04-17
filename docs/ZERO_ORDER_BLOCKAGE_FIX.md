# Zero-Order Blockage Fix — Root Cause → Fix Mapping

## Problem Statement

The MERID trading agent grid was submitting **zero orders** in live/paper mode.
All agents completed cycles, evaluated markets, but no orders were ever placed.
No errors were logged — the system appeared healthy but was silently blocked.

---

## Root Cause Analysis

Four blockages were identified, listed by severity (order of execution in pipeline):

### Blockage #1 (CRITICAL): Strike Selector Rejects 100% of Directional Markets

**Root cause**: 15-minute crypto markets on Kalshi use **directional** tickers
(e.g. `KXBTC15M-26MAR250015-15`) that have **no strike price** — they are
up/down contracts, not threshold/bracket contracts. The `parse_strike_from_ticker()`
regex only matches `-T` and `-B` suffixes, returning `None` for directional tickers.
The strike selector then rejected them all as `missing_strike`.

**Impact**: 100% of 15m markets were silently rejected before strategy evaluation.
Every cycle showed `signals_evaluated=0`, `actionable=0`.

**Fix**: Added `allow_directional_passthrough` (default `True`) to `StrikeSelectionConfig`.
When a market has no strike and spot is available, the selector returns `accepted=True`
with `is_directional=True` instead of rejecting. Directional markets skip distance
checks (which are meaningless without a strike) but still require valid spot price.

**File**: `merid/prediction/kalshi_strike_selector.py`

### Blockage #2 (HIGH): Warmup Lifecycle Too Long

**Root cause**: `_WARMUP_SECONDS=60` + stagger up to 30s = up to 90s of warmup
during which execution was blocked. For 15m agents cycling every 30s, this meant
3+ dead cycles. The warmup was purely time-based with no data-readiness check.

**Fix**: Replaced with data-readiness promotion:
- `_WARMUP_MIN_SECONDS=15` + stagger (minimum before considering promotion)
- Promotion triggers when `cycles_run >= 1` (had at least one catalog cycle)
- Hard ceiling at `_WARMUP_MAX_SECONDS=90` (prevents infinite stall)
- Structured `[LIFECYCLE]` log on promotion with reason

**File**: `merid/prediction/trading_agent.py`

### Blockage #3 (MEDIUM): Solo Window Blocks First Cycles

**Root cause**: Default `MERID_PM_SWARM_SOLO_SECONDS=120` meant that when consensus
returned `None` (no proposals yet on first cycle), the agent waited 120s before
allowing solo execution. With a 30s cycle interval, this was 4 dead cycles.

**Fix**: Changed default to `0` (no hold). In a single-agent deployment, the agent
IS the consensus — there is no quorum to wait for. Multi-agent swarms can override
via `MERID_PM_SWARM_SOLO_SECONDS=120`.

**File**: `merid/prediction/trading_agent.py`

### Blockage #4 (CONFIRMED NOT BROKEN): Consensus Single-Agent Path

**Analysis**: The `SwarmConsensusAggregator._recompute_consensus()` already handles
single-agent mode correctly via `_consensus_from_single_proposal()`. When
`len(proposals) < min_agents` (default 2), a single proposal creates a READY
consensus. The `submit_proposal` → `_recompute_consensus` → `get_consensus` path
uses the same `{asset}:{timeframe}` key, so a proposal submitted in the same cycle
is immediately readable.

**No code change needed** — the path was never reached because Blockage #1 killed
all markets before consensus submission.

---

## Observability Enhancements

### PM_CYCLE_TRACE — New Fields
Three new counters in every cycle trace log:
- `strike_passed=%d` — markets that passed strike selection
- `strike_rejected=%d` — markets rejected by strike selector
- `strike_directional=%d` — directional markets that used passthrough

### [CONFIG_SANITY] — Startup Checks
Runs at agent start, emits WARNING-level logs for:
- Empty `assets=[]` or `timeframes=[]`
- Solo window > 2× cycle interval (dead cycles)
- `allow_directional_passthrough=false` with 15m timeframe
- Zero-width entry window (min ≤ cutoff)

### [LIFECYCLE] — Promotion Log
Structured log on WARMING_UP → ACTIVE transition:
```
[LIFECYCLE] Promoted BTC_15M WARMING_UP → ACTIVE after 18s (reason=data_ready stagger=3.2s cycles=1)
```

---

## Files Changed

| File | Changes |
|------|---------|
| `merid/prediction/kalshi_strike_selector.py` | `allow_directional_passthrough`, `DIRECTIONAL_NO_SPOT` reason, `is_directional` flag, config parsing |
| `merid/prediction/trading_agent.py` | Warmup min/max, data-readiness promotion, solo window default=0, strike counters, config sanity checks |
| `tests/prediction/test_zero_order_blockage_fixes.py` | 28 tests across 8 test classes |
| `docs/ZERO_ORDER_BLOCKAGE_FIX.md` | This document |

---

## Test Summary

**28/28 passing** in `tests/prediction/test_zero_order_blockage_fixes.py`:

| Class | Tests | Covers |
|-------|-------|--------|
| `TestStrikeSelectorDirectionalPassthrough` | 8 | Directional accept, reject, passthrough toggle |
| `TestStrikeSelectorConfigParsing` | 3 | Config default/override for passthrough |
| `TestStrikeSelectorBatchDirectional` | 1 | Mixed batch with directional + threshold |
| `TestWarmupLifecycleConstants` | 4 | Min/max warmup bounds, stagger |
| `TestLifecycleStateEnum` | 1 | All enum values present |
| `TestConsensusSingleAgent` | 3 | Single proposal → READY, usable, None when empty |
| `TestSoloWindowDefault` | 2 | Default=0, env override |
| `TestRejectionReasons` | 2 | New reason enum, string types |
| `TestConfigSanityChecks` | 2 | Entry window width detection |
| `TestCycleTraceStrikeCounters` | 1 | Format string includes new fields |
| `TestStrikeSelectorSnapshotIntegration` | 1 | Directional flag accessible |

---

## Operator Runbook — Next Live Test

### Pre-flight
1. Ensure `.env` has **no** `MERID_PM_BYPASS_SWARM_CONSENSUS_AGENTS` set
2. Ensure **no** `MERID_PM_SWARM_SOLO_SECONDS` override (default 0 is correct for single-agent)
3. Verify `config/kalshi_agent_grid.yaml` agents have `strike_selection.allow_directional_passthrough: true` (or omit — default is true)

### Start
```bash
py main.py  # or your standard launch
```

### Verify in logs (~30s after start)
1. `[CONFIG_SANITY] agent=BTC_15M — all checks passed`
2. `[LIFECYCLE] Promoted BTC_15M WARMING_UP → ACTIVE after Xs (reason=data_ready ...)`
3. `[PM_CYCLE_TRACE] agent=BTC_15M ... strike_passed=N strike_rejected=0 strike_directional=N ...`
4. `signals_evaluated > 0` and `actionable > 0` in trace

### If still zero orders
Check the trace for the **first non-zero** counter:
- `strike_rejected > 0, strike_passed = 0` → spot feed is stale or missing
- `signals_evaluated > 0, actionable = 0` → strategy edge thresholds too tight
- `actionable > 0, consensus_blocked > 0` → consensus key mismatch (check asset/timeframe)
- `risk_approved > 0, exec_dispatched = 0` → still in WARMING_UP (check lifecycle field)

### Rollback
All changes are backward-compatible. To revert to old behavior:
```bash
# Old warmup behavior (60s fixed)
export MERID_PM_WARMUP_MIN_SECONDS=60  # not yet env-configurable, edit source

# Old solo window (120s hold)
export MERID_PM_SWARM_SOLO_SECONDS=120

# Disable directional passthrough
# In kalshi_agent_grid.yaml:
#   strike_selection:
#     allow_directional_passthrough: false
```
