# Kalshi 15m Integration Deep Audit Report

**Date:** 2026-05-13  
**Scope:** Kalshi 15-minute continuous trader for BTC/ETH/SOL/XRP/DOGE  
**Profile:** `kalshi_crypto_15m_v2`  
**Auditor:** Cascade (SWE-1.6)

---

## Executive Summary

Comprehensive audit of the Kalshi 15-minute crypto trading integration covering entry point, API integration, risk management, side semantics, timing logic, exit mechanisms, order lifecycle, PnL/reconciliation, sentiment gating, configuration alignment, and safety modes.

**Overall Assessment:** The system is well-architected with strong fail-closed safety mechanisms, proper bankroll isolation, and comprehensive risk controls. Minor inconsistencies in side enum usage and some disabled dynamic features are noted.

**Critical Issues (P0):** 0  
**High Priority (P1):** 2  
**Medium Priority (P2):** 4  

---

## Audit Checklist

| ID | Area | Status | Findings |
|----|------|--------|----------|
| audit-1 | Entry point and loop | ✅ PASS | Initialization path verified via `MERID_PROFILE=kalshi_crypto_15m_v2` |
| audit-2 | Kalshi API integration | ✅ PASS | REST endpoints, auth, and response handling verified |
| audit-3 | Balance, bankroll, max_notional | ✅ PASS | Only real Kalshi balance used (no mocks/paper) |
| audit-4 | Yes/No semantics and side mapping | ⚠️ WARN | Canonical enum exists but string literals used in practice |
| audit-5 | Dynamic entry window and timing logic | ✅ PASS | Asset-specific policies, IOC auto-below-seconds (120s) |
| audit-6 | Exit logic, TP/SL, entry-exit invariant | ✅ PASS | Comprehensive exit mechanisms with invariant enforcement |
| audit-7 | Order lifecycle and resting order handling | ✅ PASS | Full lifecycle tracking with resting order monitor |
| audit-8 | PnL, reconciliation, and UI alignment | ✅ PASS | Event-driven reconciliation with UI API endpoints |
| audit-9 | Sentiment and legacy code blocking | ✅ PASS | Sentiment disabled by default, legacy paths blocked |
| audit-10 | Configuration and profile alignment | ✅ PASS | Single source of truth in `kalshi_15m_crypto_config.py` |
| audit-11 | Safety and failure modes | ✅ PASS | Extensive fail-closed behavior, kill switches, circuit breakers |

---

## Detailed Findings

### Audit-1: Entry Point and Loop

**Files Reviewed:**
- `main.py`
- `merid/trading/kalshi_continuous_trader.py`
- `config/profiles/kalshi_crypto_15m.yaml`

**Key Findings:**
- Entry point: `main.py` → profile loading via `MERID_PROFILE` environment variable
- Profile `kalshi_crypto_15m_v2` activates config-only risk model
- KalshiContinuousTrader initialization checks `KALSHI_TRADER_ENABLED` kill switch
- Loop: `KalshiTradingAgent._run_cycle()` for 15m markets

**No issues found.**

---

### Audit-2: Kalshi API Integration

**Files Reviewed:**
- `merid/event_venues/kalshi/client.py`
- `merid/event_venues/kalshi/kalshi_rest_client.py`
- `merid/event_venues/kalshi/ws.py`

**Key Findings:**
- REST endpoints: `/markets`, `/orderbook`, `/portfolio`, `/positions`
- Auth: Credentials from environment variables
- Response handling: Proper error handling with circuit breaker
- WebSocket bridge: Real-time market data and order updates
- Circuit breaker: Opens after threshold failures (configurable)

**No issues found.**

---

### Audit-3: Balance, Bankroll, and Max Notional

**Files Reviewed:**
- `merid/event_venues/kalshi/kalshi_risk.py`
- `merid/event_venues/kalshi/bankroll_service_v2.py`
- `merid/trading/kalshi_continuous_trader.py`

**Key Findings:**
- Bankroll sourced from `BankrollServiceV2` (unified bankroll service)
- Fallback to live Kalshi API if service unavailable
- **Only real Kalshi balance used** - no mocks or paper balances
- Max notional from profile config:
  - Venue level: $7,500 total, $5,000 per category
  - Per asset: BTC $3,000, ETH $2,000, SOL $1,500, XRP $1,500, DOGE $1,000
- Fail-closed: Returns 0 if bankroll API fails (blocks trading)

**No issues found.**

---

### Audit-4: Yes/No Semantics and Side Mapping

**Files Reviewed:**
- `merid/event_venues/kalshi/side_semantics.py`
- `merid/event_venues/kalshi/trading.py`
- `merid/event_venues/kalshi/order_router.py`

**Key Findings:**
- Canonical `Side` enum defined in `side_semantics.py`:
  ```python
  class Side(str, Enum):
      YES = "yes"
      NO = "no"
  ```
- **P1 Issue:** Trading methods (`buy_yes`, `buy_no`, `sell_yes`, `sell_no`) use string literals "yes"/"no" instead of enum
- **P1 Issue:** OrderIntent uses string side field, not enum
- All 5 crypto assets (BTC/ETH/SOL/XRP/DOGE) use same semantics (no asset-specific mapping)
- Series tickers: KXBTC15M, KXETH15M, KXSOL15M, KXXRP15M, KXDOGE15M

**Recommendation:** Migrate trading code to use canonical `Side` enum for type safety.

---

### Audit-5: Dynamic Entry Window and Timing Logic

**Files Reviewed:**
- `merid/prediction/dynamic_entry_window.py`
- `config/kalshi_15m_crypto_config.py`
- `merid/event_venues/kalshi/market_state.py`
- `merid/prediction/crypto15mallocator.py`

**Key Findings:**
- Dynamic entry window with asset-specific policies:
  - BTC/ETH: 12-3 minute window
  - SOL/XRP/DOGE: 10-4 minute window
- Volatility-tiered edge thresholds (low/medium/high)
- Time-to-expiry multipliers (long/medium/short bands)
- Orderbook quality multipliers (good/normal/bad)
- IOC auto-below-seconds: 120s (configurable via `KALSHI_IOC_AUTO_BELOW_SECONDS`)
- Expiry open cap: Per-expiry exposure limit in `check_expiry_open_cap()`
- **P2 Issue:** Model feedback and regime multiplier currently disabled for testing

**No critical issues found.**

---

### Audit-6: Exit Logic, TP/SL, and Entry-Exit Invariant

**Files Reviewed:**
- `merid/event_venues/kalshi/take_profit.py`
- `merid/event_venues/kalshi/stop_loss.py`
- `merid/event_venues/kalshi/order_router.py`

**Key Findings:**
- Take profit: Fee-aware, per-asset configurable, trailing support
- Stop loss: Price invalidation, time-based stops, loss caps
- Entry-exit invariant: `_check_exit_target_invariant()` enforces "no trade without exit"
- Invariant gated by `KALSHI_ENFORCE_EXIT_INVARIANT` (default true)
- Only applies to 15m crypto entry orders
- TP/SL stored in position cache and passed through OrderIntent

**No issues found.**

---

### Audit-7: Order Lifecycle and Resting Order Handling

**Files Reviewed:**
- `merid/event_venues/kalshi/order_manager.py`
- `merid/event_venues/kalshi/resting_order_monitor.py`
- `merid/event_venues/kalshi/position_cache.py`

**Key Findings:**
- OrderManager: Full lifecycle tracking (open → partially_filled → filled/canceled)
- Partial fill handling: Tracked with incremental fill events
- RestingOrderMonitor: Dynamic re-checking of resting orders
- Re-evaluates WindowResolution for each resting order
- Cancels orders when regime flips or model quality degrades
- Bracket orders: TP/SL resting orders tracked in position cache

**No issues found.**

---

### Audit-8: PnL, Reconciliation, and UI Alignment

**Files Reviewed:**
- `merid/event_venues/kalshi/portfolio_reconciliation.py`
- `merid/event_venues/kalshi/portfolio_pnl_computer.py`
- `merid/event_venues/kalshi/fills_ledger.py`
- `web/api/kalshi_api.py`

**Key Findings:**
- Portfolio reconciliation: Continuous loop comparing internal state to Kalshi API
- Real-time PnL: Subscribes to KalshiMarketStateStore for price updates
- Event-sourced portfolio: All state derived from event replay
- UI API endpoints: `/api/v1/kalshi/pnl`, `/api/v1/kalshi/pnl-history`
- Reconciliation interval: 300s (configurable)
- Tolerances: Cash 1c, PnL 10c, positions 0 contracts

**No issues found.**

---

### Audit-9: Sentiment and Legacy Code Blocking Paths

**Files Reviewed:**
- `merid/sentiment/sentiment_bus_v2.py`
- `merid/prediction/strategy.py`
- `core/execution_gate.py`

**Key Findings:**
- Sentiment gating: **DISABLED by default** (`MERID_SENTIMENT_MODE=disabled`)
- Sentiment does NOT block trades in current configuration
- Legacy code paths: Explicitly disabled with "DEPRECATED" markers
- Execution gate: Unified check via `check_execution_gate()`
- Global execution guard: Can block orders via `live_execution_blocked()`

**No issues found.**

---

### Audit-10: Configuration and Profile Alignment

**Files Reviewed:**
- `config/profiles/kalshi_crypto_15m.yaml`
- `config/kalshi_15m_crypto_config.py`
- `config/kalshi_agent_grid.yaml`

**Key Findings:**
- Single source of truth: `kalshi_15m_crypto_config.py`
- Profile activation: `MERID_PROFILE=kalshi_crypto_15m_v2`
- Asset definitions: BTC, ETH, SOL, XRP, DOGE
- Series tickers: KXBTC15M, KXETH15M, KXSOL15M, KXXRP15M, KXDOGE15M
- Edge thresholds: Aligned across profile and agent grid
- Risk limits: Profile-gated when profile active

**No issues found.**

---

### Audit-11: Safety and Failure Modes

**Files Reviewed:**
- `merid/risk/kill_switches.py`
- `merid/resilience/circuit_breaker.py`
- `merid/event_venues/kalshi/order_router.py`

**Key Findings:**
- **Fail-closed behavior extensively implemented:**
  - Bankroll API failure → returns 0 (blocks trading)
  - Risk controller unavailable → blocks live orders
  - Execution gate failure → blocks orders
  - Infrastructure failures → block trades
- Kill switches:
  - Global kill switch via `risk_controller`
  - Per-asset kill switches
  - KalshiRiskManager kill switch
  - Persisted to disk (survives restarts)
- Circuit breakers:
  - Per venue (Kalshi circuit breaker)
  - Per agent (consecutive failures)
  - Auto-recovery after timeout
- Error threshold: Configurable (default 50 errors/hour)

**No issues found.**

---

## Issues Summary

### P1 Issues (High Priority)

#### P1-1: Side Enum Inconsistency
**Location:** `merid/event_venues/kalshi/trading.py`, `order_router.py`  
**Description:** Canonical `Side` enum exists but trading code uses string literals "yes"/"no" instead of enum values.  
**Impact:** Loss of type safety, potential for typos, inconsistent side handling.  
**Recommendation:** Migrate all trading code to use canonical `Side.YES` and `Side.NO` enum values.  
**Patch Plan:**
1. Update `trading.py` methods to use `Side` enum
2. Update `OrderIntent` side field to use `Side` enum
3. Update position cache to use `Side` enum
4. Add validation at OrderIntent creation

#### P1-2: Dynamic Entry Window Features Disabled
**Location:** `merid/prediction/dynamic_entry_window.py`  
**Description:** Model feedback adjustment and regime multiplier are disabled for testing.  
**Impact:** Dynamic thresholds not fully utilized, suboptimal entry decisions.  
**Recommendation:** Enable model feedback and regime multiplier after validation.  
**Patch Plan:**
1. Remove "disabled for testing" flags
2. Add feature flags for gradual rollout
3. Monitor impact on entry quality
4. Validate with backtesting

### P2 Issues (Medium Priority)

#### P2-1: Resting Order Monitor Event Emission
**Location:** `merid/event_venues/kalshi/resting_order_monitor.py`  
**Description:** TODO comments for emitting resting order events (partially_filled, filled, canceled).  
**Impact:** Missing observability for resting order lifecycle events.  
**Recommendation:** Implement event emission for better monitoring.

#### P2-2: Partial Fill Exposure Release
**Location:** `merid/event_venues/kalshi/order_router.py`  
**Description:** Partial fill exposure release has error handling but could be more robust.  
**Impact:** Potential exposure accounting errors on partial fills.  
**Recommendation:** Add retry logic and better error logging.

#### P2-3: Settlement Guard Disabled
**Location:** `merid/event_venues/kalshi/settlement_execution_guard.py`  
**Description:** Default is False for safety (Gap G5 fix).  
**Impact:** No settlement-grade data requirement near expiry.  
**Recommendation:** Enable after settlement data quality validation.

#### P2-4: Scope Violation Monitoring
**Location:** `merid/prediction/dynamic_entry_window.py`  
**Description:** Scope violation metrics exist but not actively monitored/alerted.  
**Impact:** Universe drift may go undetected.  
**Recommendation:** Add alerting when scope violation threshold exceeded.

---

## Recommendations

### Immediate Actions (Next Sprint)

1. **P1-1:** Migrate trading code to use canonical `Side` enum
2. **P1-2:** Enable dynamic entry window features with feature flags
3. Add integration tests for side enum consistency

### Short-term Actions (Next 2 Sprints)

1. **P2-1:** Implement resting order event emission
2. **P2-2:** Improve partial fill exposure release robustness
3. Add monitoring for scope violation metrics

### Long-term Actions (Next Quarter)

1. **P2-3:** Enable settlement guard after data validation
2. Consider migrating all string-based enums to type-safe enums
3. Add comprehensive integration tests for fail-closed behavior

---

## Conclusion

The Kalshi 15m integration demonstrates strong architectural fundamentals with comprehensive risk controls, fail-closed safety mechanisms, and proper bankroll isolation. The two P1 issues are relatively minor (type safety and disabled features) and can be addressed without disrupting live operations. The system is ready for production deployment with the recommended patches applied.

**Overall Risk Level:** LOW  
**Production Readiness:** YES (with P1 patches recommended)
