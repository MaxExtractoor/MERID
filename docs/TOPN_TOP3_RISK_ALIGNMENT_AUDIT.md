# Top-N / Top-3 Risk Alignment Audit

**Date:** 2026-04-20
**Scope:** Bankroll consistency + "top 3 only, N ∈ {0,1,2,3}" enforcement across the Kalshi continuous trading pipeline.
**Primary references:**
- `merid/trading/kalshi_continuous_trader.py`
- `merid/trading/topn_allocator.py`
- `merid/trading/top3_edge_allocator.py`, `top3_batch_manager.py`
- `core/settings.py`
- `tests/trading/test_topn_top3_alignment.py` (new)
- `tests/trading/test_risk_oversizing_regression.py`
- `tests/trading/test_topn_allocator.py`, `test_topn_integration.py`

---

## Phase 1 — Bankroll Source Alignment

### 1.1 Component → field → source map

| Component | Param name | Source in CT loop | Units |
|---|---|---|---|
| `TopNEdgeAllocator.compute_allocations` | `equity_cents` | `_bankroll_cents = total_value_cents` (line 3259) | cents |
| `GlobalRiskGuard.check_order` | `equity_cents` | `_guard_equity_cents = total_value_cents` (line 4105) | cents |
| `KalshiRiskManager.check_order` | internal | reads venue/positions inside `get_kalshi_risk()` | cents |
| `BANKROLL-SOURCES` log | `topn_B` / `cash_B` / `portfolio` | `total_value_cents` / `balance_cents` / `portfolio_cents` | cents → USD |
| Kalshi `/portfolio/balance` | `balance_cents` | raw cash from Kalshi REST | cents |

**`total_value_cents = balance_cents + portfolio_cents`** (cash + position MTM). This is the canonical "equity" notion that both the allocator and the last-line guard agree on.

### 1.2 Verified alignment

Both call sites in `merid/trading/kalshi_continuous_trader.py` read from the same local variable `total_value_cents`:

```python
# Line 3259 — TopN allocator
_bankroll_cents = total_value_cents  # cash + portfolio, NOT just balance_cents
_cycle = self._topn_allocator.compute_allocations(
    equity_cents=_bankroll_cents, ...
)

# Line 4105 — GlobalRiskGuard (per order)
_guard_equity_cents = total_value_cents  # NOT just balance_cents
_guard_allowed, _guard_reason = self._risk_guard.check_order(
    equity_cents=_guard_equity_cents, ...
)
```

`tests/trading/test_topn_top3_alignment.py::TestBankrollSourceAlignment` asserts this via regex on the source, so it cannot silently drift.

### 1.3 Cycle-cap caps wiring

`GlobalRiskGuard` is constructed with `MAX_CYCLE_RISK_PCT` / `MAX_TOTAL_RISK_PCT` imported from `core.settings` (env-backed, default `0.02` each). No hard-coded caps shadow them. `.env` sets both to `0.02` and `USE_TOPN_ALLOCATOR=true`.

---

## Phase 2 — Top 3 Only, N ∈ {0, 1, 2, 3}

### 2.1 Ranking & restriction

`merid/trading/topn_allocator.py::select_topn_allocations` (lines 277-392):

1. Filter invalid candidates (`edge <= 0`, asset ∉ {BTC,ETH,SOL,XRP,DOGE}, bad price/stop).
2. Sort by `edge` descending.
3. Try `n = min(max_edges_per_cycle, len(valid))` down to `1`. The first `n` that fits budget + min-contracts + min-notional is accepted; otherwise `n = 0`.

`max_edges_per_cycle` defaults to `3` (config) and is load-able from env `TOPN_MAX_EDGES`.

### 2.2 Selection monotonicity proof sketch

For each candidate N:
- Only the first `N` elements of `sorted_candidates` (descending by edge) are passed to `_allocate_to_candidates`.
- If N fails constraints, loop descends to `N-1`, which is the first `N-1` elements — strictly a prefix.
- Therefore the selected set is always a prefix of the edge-sorted list. T2 cannot trade without T1; T3 cannot trade without T1 and T2.

Covered by `test_topn_top3_alignment.py::TestTopNSelectionScenarios` (scenarios A/B/C) and `test_topn_integration.py::test_scenario_budget_accommodates_2_only`.

### 2.3 Assets outside top 3 cannot reach order submission

In `kalshi_continuous_trader.py` lines 3531-3556 inside the per-candidate order loop:

```python
if _USE_TOPN_ALLOCATOR and _topn_allocations and _candidate_asset in _topn_allocations:
    order_count = _topn_allocations[_candidate_asset].target_contracts
else:
    if _USE_TOPN_ALLOCATOR:
        logger.debug("[TOPN-SKIP] %s | asset=%s not in top-n allocations, skipping", ...)
        continue        # <-- skip, no Kelly fallback
    order_count = self.bankroll.calculate_order_size(...)   # only when flag is False
```

When `USE_TOPN_ALLOCATOR=true`, any asset not in `_topn_allocations` is **skipped**; there is no fallback to legacy Kelly. Top-3 batch manager provides a second, independent gate at line 3466.

### 2.4 Edge-threshold gating

- Per-phase min edge is enforced upstream in `FilterPipeline` via `kalshi_agent_grid.yaml` per-phase `min_edge`.
- `TopNEdgeAllocator._filter_valid_candidates` drops `edge <= 0`.
- Diagnostic overrides `KALSHI_CT_DIAGNOSTIC_MIN_EDGE`, `EDGE_MIN_THRESHOLD`, `KALSHI_TRADER_SMOKE_ALLOW_NO_SETTINGS` — verified **not set** in `.env`. Production leaves defaults.

---

## Phase 3 — GlobalRiskGuard Integration

### 3.1 Every live order flows through the guard

Single order-submit site in `kalshi_continuous_trader.py` at line 4107. No other "emergency" or direct path exists — grep confirms exactly one `_risk_guard.check_order` invocation and one submit flow.

### 3.2 Per-cycle reset

`self._risk_guard.reset_cycle()` is called at line 2366 (top of `_run_cycle_inner`, before any order evaluation). This clears `_cycle_new_risk_cents` so the per-cycle cap is fresh each cycle.

### 3.3 Guard-rejection semantics (no reallocation)

If `check_order` rejects an order mid-cycle, the loop `continue`s; the rejected allocation's max-loss is NOT added to `_cycle_new_risk_cents`, so subsequent lower-ranked orders still compete against the remaining budget but are evaluated on their **own** size, not a re-allocated amount. The TopN allocator has already decided sizing before the guard sees each order; a rejection is terminal for that asset this cycle.

Scenario E in the new test suite exercises this: after T2 is blocked by cycle-cap, T3 with a smaller max-loss still passes independently without any re-sizing.

An explicit log line documents the behavior:
```
[GLOBAL-RISK-GUARD] BLOCKED | <ticker> | reason=...
```

---

## Phase 4 — Invariants & Regression Tests

### 4.1 Invariants enforced at runtime

`AllocationCycle.validate_invariants` in `topn_allocator.py:239-269`:
- `num_edges_traded <= max_edges_per_cycle` (≤ 3)
- `sum_risk_usd <= cycle_risk_usd` (≤ `equity * MAX_CYCLE_RISK_PCT`)
- every allocation has `target_contracts >= min_contracts`

`kalshi_continuous_trader.py:3294-3299` validates each cycle and emits `[TOPN-INVARIANT-VIOLATION]` at CRITICAL level if anything fails.

Additionally `test_topn_top3_alignment.py::TestTopNInvariants` adds:
- edges strictly descending in allocations
- only assets ∈ {BTC,ETH,SOL,XRP,DOGE} can be allocated

### 4.2 Regression test suite

| File | Tests | Purpose |
|---|---|---|
| `tests/trading/test_topn_allocator.py` | 42 | core allocator logic |
| `tests/trading/test_topn_integration.py` | 22 | realistic end-to-end |
| `tests/trading/test_risk_oversizing_regression.py` | 10 | 7-BTC-with-$28 bug regression |
| `tests/trading/test_topn_top3_alignment.py` (new) | 13 | Phase 1/2/4 scenarios A–E + bankroll source |

**Total: 87 tests, all green.** Run:

```
py -m pytest tests/trading/test_topn_allocator.py \
             tests/trading/test_topn_integration.py \
             tests/trading/test_risk_oversizing_regression.py \
             tests/trading/test_topn_top3_alignment.py -q
```

### 4.3 Scenarios A–E mapping

| Scenario | Test | Expectation |
|---|---|---|
| A — tiny bankroll, only T1 fits | `test_scenario_A_small_bankroll_only_T1` | `N ≤ 1`, T1 only if any |
| B — T1+T2 fit, T3 breaks cap | `test_scenario_B_medium_bankroll_T1_and_T2` | alloc prefix of sorted edges |
| C — all of T1+T2+T3 fit | `test_scenario_C_large_bankroll_all_top3` | `N = 3`, BTC/ETH/SOL only |
| D — all edges ≤ threshold | `test_scenario_D_all_edges_below_threshold` | `N = 0` |
| E — guard rejects one mid-cycle | `test_scenario_E_guard_rejects_no_reallocation` | rejection is terminal, no re-alloc |

### 4.4 Production env validation

Verified in `.env`:
- `USE_TOPN_ALLOCATOR=true` ✅
- `MAX_CYCLE_RISK_PCT=0.02` ✅
- `MAX_TOTAL_RISK_PCT=0.02` ✅
- `TOP3_ENABLED` defaults `true` (env unset → default)
- No diagnostic flags loosening min_edge in `.env`

---

## Phase 5 — Findings & Recommendations

### 5.1 Findings

1. **Bankroll alignment is correct.** Both TopN allocator and GlobalRiskGuard consume `total_value_cents` (cash + portfolio MTM). The `[BANKROLL-SOURCES]` log already surfaces delta-vs-cash, gated on > $1 difference to avoid log spam.
2. **Top-3-only enforcement is verified.** Two independent gates (`TOP3_ENABLED` batch manager at line 3466 and `USE_TOPN_ALLOCATOR` at line 3531) both require the asset to be in their respective allocation map. `continue` is the only exit — no Kelly fallback.
3. **N ∈ {0,1,2,3} is guaranteed** by `max_edges_per_cycle=3` + step-down algorithm; proven by prefix-only selection and enforced by invariant validation + regression tests.
4. **Guard catches any cap breach.** The guard sees every order via the single submit path. Reset-per-cycle is wired. Guard rejection does not trigger re-allocation — verified in Scenario E.

### 5.2 Recommendations (non-blocking)

- Consider emitting `[BANKROLL-SOURCES]` at `DEBUG` always (not only on delta > $1) for full-cycle audit replay. Current behavior is fine for production noise levels.
- The two overlapping restriction gates (`TOP3_ENABLED` batch manager and TopN allocator) are redundant but harmless; leaving both in place is defense-in-depth.
- `TOPN_STRICT_INVARIANTS=true` can be enabled in staging/CI to hard-fail on invariant violations rather than logging.

### 5.3 Sign-off

Claims:
- ✅ Bankroll source aligned (TopN ↔ Guard)
- ✅ Top-3 restriction provable and enforced by two gates
- ✅ `N ∈ {0,1,2,3}` guaranteed by algorithm + invariants
- ✅ Every order flows through `GlobalRiskGuard.check_order`
- ✅ Scenarios A–E covered by tests, 87 / 87 passing

No further action required to lock in current behavior. Regression shield in place.
