# Hostile Deep Audit: Duplicates, Hardcodes, Orphans, Zombies, Crash Bugs

**Date:** 2026-05-13  
**Scope:** MERID ↔ Kalshi 15m crypto integration for BTC/ETH/SOL/XRP/DOGE  
**Profile:** `kalshi_crypto_15m_v2`  
**Assumption:** Previous audits are too optimistic. Hunt for structural landmines.

---

## 1. New Duplicate Clusters (Not in Prior Reports)

**Finding:** No new structural duplicate clusters found beyond those already documented in `KALSHI_15M_DUPLICATE_SYNTHETIC_LOGIC_AUDIT.md`.

**Reason:** The prior duplicate audit was comprehensive, covering:
- Dual trading engines (KalshiTradingAgent vs KalshiContinuousTrader)
- Duplicate bankroll services (V2 vs legacy)
- Multiple risk guard implementations
- Multiple PnL computation paths
- Multiple order intent creation paths
- Multiple TP/SL implementations

**Additional Note:** While no new structural duplicates were found, the audit revealed **functional duplication** in hardcoded risk constants across multiple modules (see Section 2).

---

## 2. Hardcoded Constants on Live Path

| Location | Value | Role | Severity | Refactor Plan |
|----------|-------|------|----------|---------------|
| `merid/trading/kalshi_continuous_trader.py:241-242` | `max_risk_per_trade_pct=0.03`, `kelly_fraction=0.20` | Unified cycle risk (3%) and Kelly fraction (fifth-Kelly) | P0 | Already env-backed (KALSHI_TRADER_RISK_PCT, KALSHI_TRADER_KELLY_FRAC) - **verified safe** |
| `merid/trading/kalshi_continuous_trader.py:255-259` | `asset_max_exposure_pct` = 0.03 for all assets | Per-asset exposure caps (3% each) | P0 | Already env-backed (KALSHI_TRADER_EXPOSURE_*) - **verified safe** |
| `merid/trading/kalshi_continuous_trader.py:273` | `global_max_exposure_pct=0.50` | 50% of bankroll across all crypto | P0 | Already env-backed (KALSHI_TRADER_GLOBAL_EXPOSURE) - **verified safe** |
| `merid/trading/kalshi_continuous_trader.py:278` | `drawdown_halt_pct=0.15` | Halt if bankroll drops 15% from peak | P0 | Already env-backed (KALSHI_TRADER_DD_HALT) - **verified safe** |
| `merid/trading/kalshi_continuous_trader.py:286` | `directional_max_tilt=0.15` | Max |P_yes - 0.5| from indicator confidence | P0 | Already env-backed (KALSHI_CT_DIRECTIONAL_MAX_TILT) - **verified safe** |
| `merid/trading/kalshi_continuous_trader.py:301` | `max_strike_distance_pct=0.125` | 12.5% max OTM distance | P0 | Already env-backed (KALSHI_TRADER_MAX_DISTANCE) - **verified safe** |
| `merid/trading/kalshi_continuous_trader.py:311` | `churn_edge_improvement=0.05` | Edge must improve by 5% absolute to churn | P1 | Already env-backed (KALSHI_TRADER_CHURN_EDGE_IMPROV) - **verified safe** |
| `merid/trading/kalshi_continuous_trader.py:314` | `max_fee_drag_pct=0.25` | Tighten filters if fees > 25% of gross edge | P1 | Already env-backed (KALSHI_TRADER_MAX_FEE_DRAG) - **verified safe** |
| `merid/trading/kalshi_continuous_trader.py:334` | `max_cycle_spend_pct=0.10` | Max 10% of balance per cycle | P0 | Already env-backed (KALSHI_TRADER_CYCLE_SPEND_PCT) - **verified safe** |
| `merid/trading/trading_state.py:58-65` | `warning_pct=0.03`, `hedge_active_pct=0.05`, `scalp_halt_pct=0.10`, `full_halt_pct=0.15` | Drawdown thresholds for state transitions | P0 | **NOT env-backed** - add env vars (TRADING_STATE_WARNING_PCT, etc.) |
| `merid/trading/topn_allocator.py:48` | `max_cycle_risk_pct=0.03` | 3% maximum cycle risk | P0 | Already env-backed (TOPN_CYCLE_RISK_PCT) - **verified safe** |
| `merid/trading/topn_allocator.py:100` | `min_notional_usd=0.50` | Reduced from $1.00 to $0.50 for small bankrolls | P2 | Already env-backed (TOPN_MIN_NOTIONAL) - **verified safe** |
| `merid/trading/topn_allocator.py:102` | `default_stop_distance_pct=0.03` | Default stop loss distance (3%) | P1 | **NOT env-backed** - add TOPN_DEFAULT_STOP_DISTANCE_PCT |
| `merid/trading/kalshi_crypto_configurator.py:17` | `WIDTH_MIN = 0.10` | Minimum width for strike selection (10%) | P1 | **NOT env-backed** - add KALSHI_STRIKE_WIDTH_MIN |
| `merid/trading/kalshi_crypto_configurator.py:83` | Clamp width to `[0.10, 0.35]` | Hardcoded width bounds | P1 | **NOT env-backed** - add KALSHI_STRIKE_WIDTH_MIN/MAX |
| `merid/trading/kalshi_crypto_spot_adapter.py:40` | `fallback_size_factor=0.5` | Reduce size on fallback sources | P2 | **NOT env-backed** - add KALSHI_SPOT_FALLBACK_SIZE_FACTOR |
| `merid/trading/kalshi_crypto_configurator.py:123` | `base_width_btc` example `0.125` | ±12.5% around spot for BTC | P1 | **NOT env-backed** - add KALSHI_STRIKE_WIDTH_BTC |

**Summary:** Most critical constants in `kalshi_continuous_trader.py` are already env-backed (good). However, `trading_state.py` drawdown thresholds and some sizing constants in `topn_allocator.py` and `kalshi_crypto_configurator.py` are **not** env-backed.

**Recommendation:** Add env var backing for all P0/P1 constants not already covered.

---

## 3. Orphans & Zombies

### Dead Code (Not Imported Anywhere)

| Module/Function | Why It's Dead | Action |
|----------------|---------------|--------|
| `merid/event_venues/kalshi/venue_adapter_enhanced.py:EnhancedKalshiVenueAdapter` | Not imported anywhere in production | Delete (dead code) |
| `merid/event_venues/kalshi/order_manager_enhanced.py:EnhancedOrderManager` | Not imported anywhere in production | Delete (dead code) |
| `merid/event_venues/kalshi/order_group_manager_enhanced.py:EnhancedOrderGroupRiskManager` | Not imported anywhere in production | Delete (dead code) |
| `merid/event_venues/kalshi/trading_enhanced.py:EnhancedKalshiTrader` | Not imported anywhere in production | Delete (dead code) |
| `merid/event_venues/kalshi/bankroll_service.py:KalshiBankrollService` | Legacy, superseded by BankrollServiceV2. Only exported from `__init__.py` but not used | Remove from exports, add deprecation warning |
| `merid/reconciliation/kalshi_reconciler.py:KalshiReconciler` | Legacy, superseded by PortfolioReconciler. Only exported from `__init__.py` but not used | Remove from exports, add deprecation warning |
| `merid/trading/ct_profit_taking_integration.py` | CT-specific TP integration. CT is gated by `pm_ct_policy.ct_legacy_must_not_trade()` | Remove (CT should use canonical TakeProfitManager) |
| `merid/trading/ct_pnl_reconciler.py` | CT-specific PnL reconciliation. CT is gated | Remove (CT should use canonical PortfolioReconciler) |

### Half-Wired Features (TODOs in Production Code)

| Location | TODO Comment | Risk | Action |
|----------|--------------|------|--------|
| `merid/event_venues/kalshi/resting_order_monitor.py:397` | "TODO: Emit resting_order_partially_filled event" | P1 - Missing event emission for partial fills | Implement event emission or remove if not needed |
| `merid/event_venues/kalshi/resting_order_monitor.py:406-417` | "TODO: Emit filled/canceled/expired/rejected event" | P1 - Missing terminal event emissions | Implement event emissions |
| `merid/event_venues/kalshi/resting_order_monitor.py:429` | "TODO: Trigger manual reconciliation alert" | P1 - Missing alert on expiration discrepancy | Implement alert |
| `merid/event_venues/kalshi/portfolio_pnl_computer.py:230` | "TODO: Support multiple accounts" | P2 - Multi-account not supported | Remove TODO if not needed, or implement |
| `merid/event_venues/kalshi/portfolio_pnl_computer.py:339` | "TODO: Implement actual subscription mechanism" | P2 - Subscription mechanism incomplete | Implement or remove |
| `merid/event_venues/kalshi/settlement_poller.py:978,1001` | "TODO: Investigate Redis connection pool" | P2 - Performance optimization | Remove TODO if not blocking |
| `merid/event_venues/kalshi/fills_ledger.py:1814` | "TODO: Implement prior day close tracking" | P2 - Daily PnL change calculation | Implement or remove TODO |
| `merid/event_venues/kalshi/fills_poller.py:725` | "TODO: Add reconciliation script" | P2 - Reconciliation tooling | Implement or remove TODO |
| `merid/prediction/dynamic_entry_window.py:926` | "TODO: Integrate with KalshiMarketStateStore" | P1 - Entry window not using real-time orderbook | Implement integration |

### Phantom Configs (Env Vars Not Read)

No phantom configs found. All env vars referenced in code are actually read.

---

## 4. Crash-Prone Sites

### P0: Can Crash Main Process or Trading Loop

| File:Line | Exception Type | Trigger Condition | Proposed Hardening |
|-----------|----------------|-------------------|-------------------|
| `merid/trading/kalshi_continuous_trader.py:3117` | `IndexError` | `yes_levels` empty list: `float(yes_levels[0][0])` | Add length check: `if yes_levels and yes_levels[0]:` |
| `merid/trading/kalshi_continuous_trader.py:3133` | `IndexError` | `no_levels` empty list: `float(no_levels[0][0])` | Add length check: `if no_levels and no_levels[0]:` |
| `merid/trading/kalshi_continuous_trader.py:3434` | `IndexError` | `yes_levels` empty: `float(yes_levels[0][0])` | Add length check |
| `merid/trading/kalshi_continuous_trader.py:3436` | `IndexError` | `no_levels` empty: `float(no_levels[0][0])` | Add length check |
| `merid/trading/kalshi_continuous_trader.py:3953` | `IndexError` | `tradeable` empty list: `tradeable[0].best_edge` | Add length check |
| `merid/trading/crypto_spot_service.py:487` | `IndexError` | `result.keys()` empty: `list(result.keys())[0]` | Add check: `if result and result.keys()` |
| `merid/trading/crypto_spot_service.py:491` | `IndexError` | `ticker_data.get("c", [None])[0]` when default `[None]` is used | Use `.get("c", [])` and check length |
| `merid/event_venues/kalshi/sentiment.py:396` | `IndexError` | `data.get("data", [{}])[0]` when default `[{}]` is used | Use `.get("data", [])` and check length |
| `merid/trading/kalshi_continuous_trader.py:1364` | `IndexError` | `series_tickers` empty list: `series_tickers[0]` | Add length check before access |
| `merid/trading/kalshi_continuous_trader.py:3764` | `IndexError` | `_top3_batch.allocations` empty: `allocations[0]` | Add length check |

### P1: Can Crash Background Worker or Reconciliation Loop

| File:Line | Exception Type | Trigger Condition | Proposed Hardening |
|-----------|----------------|-------------------|-------------------|
| `merid/trading/crypto_spot_service.py:568,570` | `IndexError` | `symbols` list empty: `symbols[0]` | Add length check before indexing |
| `merid/alignment/spot_basis_tracker.py:518` | `IndexError` | `result.keys()` empty: `list(result.keys())[0]` | Add check |
| `merid/strategies/binance_us_data.py:80,157` | `IndexError` | `result.keys()` empty: `list(result.keys())[0]` | Add check |
| `merid/signals/store.py:545` | `IndexError` | SQL query returns no rows: `fetchone()[0]` | Check for `None` before indexing |
| `merid/prediction/polygon_context.py:130` | `IndexError` | `closes` list too short: `closes[-6]` | Check length before negative indexing |

### P2: Can Crash Non-Critical Utility

| File:Line | Exception Type | Trigger Condition | Proposed Hardening |
|-----------|----------------|-------------------|-------------------|
| `merid/strategies/kelly_monte_carlo.py:277-278` | `IndexError` | Empty assessment dicts: `list(...)[0]` | Already has `if any(...)` guard - **safe** |
| `merid/signals/features.py:290` | `IndexError` | Empty data list: `p[0]` | Already has list comprehension filter - **safe** |
| `merid/signals/cqi_gating.py:167` | `IndexError` | Empty drift_data: `drift_data[0]` | Already has `if drift_data` guard - **safe** |

### Crash-Prone Bare Except Clauses (Silent Failures)

| File:Line | Pattern | Risk | Proposed Fix |
|-----------|---------|------|--------------|
| `merid/trading/kalshi_continuous_trader.py:552,575,903,926,933` | `except Exception:` | Swallows all errors, hides root cause | Replace with specific exception types |
| `merid/trading/kalshi_continuous_trader.py:2363,2582,2585,2624,2644` | `except Exception as exc:` | Swallows all errors, logs but continues | Add specific exception types |
| `merid/trading/topn_allocator.py:83,629,899` | `except Exception:` | Silent failures in sizing logic | Replace with specific exceptions |
| `merid/trading/top3_edge_allocator.py:503,545` | `except Exception as _e:` | Silent failures in edge allocation | Replace with specific exceptions |

### Module-Level Side Effects (Import-Time Crashes)

**No module-level side effects found that could crash on import.** All `os.getenv` calls are inside functions, not at module level.

---

## 5. Silent Liar & Anti-Pattern Findings

### Silent Liar: Logging Mismatches

| File:Line | Log Text vs Computed Value | Risk | Fix |
|-----------|---------------------------|------|-----|
| `merid/trading/kalshi_continuous_trader.py:3123-3124` | Logs "profit-taking zone" but uses `yes_profit_take_cents / 100.0` (decimal conversion) | P1 - Could mislead operator if conversion wrong | Log the actual value being compared, not just the threshold |
| `merid/trading/kalshi_continuous_trader.py:3129-3130` | Logs "stop-loss zone" but uses `yes_stop_loss_cents / 100.0` | P1 - Same issue | Fix log to show both threshold and current value |

### Anti-Pattern: @property Shadowing Methods

**No @property shadowing found.** All @property decorators are used correctly (read-only computed attributes).

### Anti-Pattern: Unused Parameters in Functions

| File:Line | Function | Unused Parameter | Risk | Fix |
|-----------|----------|-----------------|------|-----|
| `merid/event_venues/kalshi/portfolio_pnl_computer.py:230` | `_on_price_update` | `ticker` parameter is used, but TODO says "Support multiple accounts" - hardcoded to "default" | P2 - Misleading signature | Remove TODO or implement multi-account |

### Anti-Pattern: TODOs in Hot Path

| File:Line | TODO in Hot Path | Risk | Fix |
|-----------|-----------------|------|-----|
| `merid/event_venues/kalshi/resting_order_monitor.py:397-429` | Multiple TODOs in order status sync loop | P1 - Incomplete event emission could miss critical fills | Implement or remove TODOs |
| `merid/prediction/dynamic_entry_window.py:926` | TODO in entry window resolution | P1 - Entry window not using real-time orderbook data | Implement integration with KalshiMarketStateStore |

### Anti-Pattern: Assert Statements in Production Code

| File:Line | Assert Statement | Risk | Fix |
|-----------|-----------------|------|-----|
| `merid/trading/kalshi_continuous_trader.py:3537` | `assert Kelly values are finite` | P0 - Will crash in production if NaN/inf | Replace with runtime check and safe fallback |
| `merid/trading/kalshi_continuous_trader.py:4118-4129` | `assert False, "Unexpected low-edge candidate"` | P0 - Will crash in production | Replace with logger.error + safe rejection |
| `merid/event_venues/kalshi/client.py:795` | `assert self._rate_limiter is not None` | P0 - Will crash if rate limiter not initialized | Replace with runtime check |
| `merid/event_venues/kalshi/kalshi_risk.py:1441` | `assert isinstance(gid, str)` | P1 - Will crash if group_id is not string | Replace with runtime check |

**Note:** Assert statements in `settlement_poller.py` (lines 1379-1664) are in test code, not production - **safe**.

---

## 6. Summary and Priority

### Immediate Patch Before Next Restart (P0)

1. **Fix array indexing crashes in `kalshi_continuous_trader.py`:**
   - Lines 3117, 3133, 3434, 3436, 3953, 3764 - add length checks before `[0]` access
2. **Fix array indexing crashes in `crypto_spot_service.py`:**
   - Lines 487, 491 - add length checks
3. **Fix array indexing crash in `sentiment.py`:**
   - Line 396 - add length check
4. **Replace assert statements in production code:**
   - Lines 3537, 4118-4129 in `kalshi_continuous_trader.py`
   - Line 795 in `client.py`
   - Line 1441 in `kalshi_risk.py`

### Short-Term Fixes (P1)

1. **Add env var backing for unbacked risk constants:**
   - `trading_state.py` drawdown thresholds
   - `topn_allocator.py` default stop distance
   - `kalshi_crypto_configurator.py` width bounds
2. **Implement TODOs in hot path:**
   - `resting_order_monitor.py` event emissions
   - `dynamic_entry_window.py` KalshiMarketStateStore integration
3. **Fix bare except clauses:**
   - Replace with specific exception types in `kalshi_continuous_trader.py`, `topn_allocator.py`, `top3_edge_allocator.py`

### Long-Term Cleanup (P2)

1. **Remove dead code:**
   - Enhanced modules (venue_adapter, order_manager, order_group_manager, trading)
   - Legacy bankroll and reconciler exports
   - CT-specific integrations
2. **Remove or implement remaining TODOs:**
   - Multi-account support
   - Prior day close tracking
   - Reconciliation scripts

---

## 7. Recommended Hardening Code Snippets

### Fix Array Indexing (P0)

```python
# Before (crashes if empty):
current_bid = float(yes_levels[0][0]) if yes_levels else 0

# After (safe):
if yes_levels and yes_levels[0]:
    current_bid = float(yes_levels[0][0])
else:
    current_bid = 0
```

### Replace Assert with Runtime Check (P0)

```python
# Before (crashes in production):
assert self._rate_limiter is not None and self._request_semaphore is not None

# After (safe):
if self._rate_limiter is None or self._request_semaphore is None:
    raise RuntimeError("KalshiVenueClient not initialized: rate limiter or semaphore missing")
```

### Fix Bare Except (P1)

```python
# Before (swallows all errors):
try:
    result = risky_operation()
except Exception:
    logger.error("Operation failed")
    return None

# After (specific exceptions):
try:
    result = risky_operation()
except (ValueError, KeyError) as e:
    logger.error("Operation failed with expected error: %s", e)
    return None
except Exception as e:
    logger.error("Operation failed with unexpected error: %s", e, exc_info=True)
    raise  # Don't swallow unexpected errors
```

### Add Env Var Backing (P1)

```python
# trading_state.py - add env vars:
warning_pct: float = float(os.getenv("TRADING_STATE_WARNING_PCT", "0.03"))
hedge_active_pct: float = float(os.getenv("TRADING_STATE_HEDGE_ACTIVE_PCT", "0.05"))
scalp_halt_pct: float = float(os.getenv("TRADING_STATE_SCALP_HALT_PCT", "0.10"))
full_halt_pct: float = float(os.getenv("TRADING_STATE_FULL_HALT_PCT", "0.15"))
```
