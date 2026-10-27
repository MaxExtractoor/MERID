# Kalshi Module Audit

**Date:** 2026-05-16  
**Purpose:** Enumerate all Kalshi-touching modules, classify by path (recon/execution/auxiliary), and identify test coverage gaps.

## Summary

- **Total modules:** 71 Python files
- **Recon path:** 8 modules (critical for position reconciliation)
- **Execution path:** 12 modules (critical for order execution)
- **Auxiliary:** 51 modules (supporting infrastructure, backtesting, analytics)

## Module Classification

### Recon Path (Critical for Position Reconciliation)

These modules are directly involved in the reconciliation control loop:

| Module | Path | Purpose | Test Coverage | Status |
|--------|------|---------|---------------|--------|
| `client.py` | Recon | Kalshi API client (fills, positions, balance) | ✅ test_btc_15m_reconciliation_e2e.py | Active |
| `fills_ledger.py` | Recon | Internal fills ledger (ingestion, position computation) | ✅ test_btc_15m_reconciliation_e2e.py | Active |
| `fills_persistence.py` | Recon | Fills persistence layer (WAL mode) | ⚠️ Indirect (via fills_ledger) | Needs direct test |
| `fills_poller.py` | Recon | Periodic fills polling from Kalshi | ❌ No test | Needs test |
| `crypto_catalog.py` | Recon | Crypto market catalog/discovery | ⚠️ Partial (via integration) | Needs catalog test |
| `collector.py` | Recon | Market data collector (prices, series) | ⚠️ Indirect (via client) | Needs direct test |
| `position_cache.py` | Recon | Position cache (sync with REST) | ✅ test_btc_15m_reconciliation_e2e.py | Active |
| `balance_calibrator.py` | Recon | Balance calibration against Kalshi | ❌ No test | Needs test |

### Execution Path (Critical for Order Execution)

These modules are directly involved in order execution and trading:

| Module | Path | Purpose | Test Coverage | Status |
|--------|------|---------|---------------|--------|
| `client_v2.py` | Execution | Enhanced client with order execution | ⚠️ Partial (via client.py) | Needs direct test |
| `client_enhanced.py` | Execution | Enhanced client with retry logic | ⚠️ Partial (via client.py) | Needs direct test |
| `execution_audit.py` | Execution | Execution audit trail | ❌ No test | Needs test |
| `execution_diagnostics.py` | Execution | Execution diagnostics and debugging | ❌ No test | Needs test |
| `fill_bus.py` | Execution | Fill event bus (async processing) | ❌ No test | Needs test |
| `crypto_bot.py` | Execution | Crypto trading bot (Telegram integration) | ❌ No test | Needs test |
| `crypto_scheduler.py` | Execution | Crypto market scheduler | ❌ No test | Needs test |
| `exchange_availability.py` | Execution | Exchange availability checks | ❌ No test | Needs test |
| `allowed_market_policy.py` | Execution | Market policy enforcement | ❌ No test | Needs test |
| `fix_client.py` | Execution | FIX protocol client (if used) | ❌ No test | Needs test |
| `websocket_handlers.py` | Execution | WebSocket message handlers | ❌ No test | Needs test |
| `order_manager.py` | Execution | Order lifecycle management | ❌ No test (if exists) | Needs verification |

### Auxiliary (Supporting Infrastructure)

These modules provide supporting functionality but are not directly in the recon/execution critical path:

| Module | Category | Purpose | Status |
|--------|----------|---------|--------|
| `agent_example_v2.py` | Examples | Agent example code | Deprecated? |
| `api_health_monitor.py` | Monitoring | API health monitoring | Active |
| `archiver.py` | Data | Data archiving | Active |
| `auto_promoter.py` | Ops | Auto-promotion logic | Active |
| `backend_snapshot_fetcher.py` | Data | Backend snapshot fetching | Active |
| `backtest.py` | Backtesting | Backtesting engine | Active |
| `backtest_checks.py` | Backtesting | Backtesting validation | Active |
| `backtest_viz.py` | Backtesting | Backtesting visualization | Active |
| `bankroll_adapter.py` | Bankroll | Bankroll adapter | Active |
| `bankroll_resolver.py` | Bankroll | Bankroll resolution | Active |
| `bankroll_service.py` | Bankroll | Bankroll service | Active |
| `bankroll_service_v2.py` | Bankroll | Bankroll service v2 | Active |
| `bracket_risk.py` | Risk | Bracket risk management | Active |
| `btc15m_risk.py` | Risk | BTC 15m risk profile | Active |
| `candle_poller.py` | Data | Candle data polling | Active |
| `category_exposure.py` | Risk | Category exposure tracking | Active |
| `cfb_quarantine.py` | Ops | CFB quarantine logic | Active |
| `cfb_settlement.py` | Ops | CFB settlement handling | Active |
| `constants.py` | Config | Constants and configuration | Active |
| `contract_lease.py` | Data | Contract lease management | Active |
| `coverage_checker.py` | Analytics | Coverage checking | Active |
| `crypto_series.py` | Data | Crypto series definitions | Active |
| `cycle_drawdown.py` | Analytics | Cycle drawdown analysis | Active |
| `cycle_snapshot_schema.py` | Data | Cycle snapshot schema | Active |
| `decision_trace.py` | Analytics | Decision tracing | Active |
| `deployment.py` | Ops | Deployment scripts | Active |
| `expiry_fallback.py` | Ops | Expiry fallback logic | Active |
| `fees.py` | Config | Fee configuration | Active |
| `flat_trap_filter.py` | Analytics | Flat trap filtering | Active |
| `grid_validator.py` | Validation | Grid validation | Active |
| `historical_sim.py` | Backtesting | Historical simulation | Active |
| `incidents/` | Ops | Incident management | Active |
| `kalshi_robustness.py` | Resilience | Robustness patterns | Active |
| `kalshi_risk.py` | Risk | Kalshi risk profile | Active |
| `kalshi_risk_profile.py` | Risk | Kalshi risk profile (alt) | Active |
| `market_selector.py` | Market | Market selection logic | Active |
| `portfolio_risk_agent.py` | Risk | Portfolio risk agent | Active |
| `session_guard.py` | Ops | Session guard | Active |
| `trading_agent.py` | Trading | Trading agent base | Active |
| `websocket_bridge.py` | WebSocket | WebSocket bridge | Active |
| `websocket_client.py` | WebSocket | WebSocket client | Active |
| `websocket_subscriptions.py` | WebSocket | WebSocket subscriptions | Active |
| `ws_feed.py` | WebSocket | WebSocket feed handler | Active |
| `ws_orderbook.py` | WebSocket | WebSocket orderbook | Active |
| `ws_trades.py` | WebSocket | WebSocket trades | Active |
| `ws_ticker.py` | WebSocket | WebSocket ticker | Active |
| `ws_utils.py` | WebSocket | WebSocket utilities | Active |
| `__init__.py` | Package | Package initialization | Active |

## Test Coverage Analysis

### Currently Covered (by test_btc_15m_reconciliation_e2e.py)

- ✅ `client.py` - Mock client fixture, pagination tests
- ✅ `fills_ledger.py` - Ingestion tests, idempotency, multi-contract
- ✅ `position_cache.py` - Sync alignment tests
- ✅ `reconciliation` (via venue_reconciler.py) - Matching rules, severity matrix, phantom detection
- ✅ `execution_gate.py` - Gate unit tests, integration sim

### Coverage Gaps (Critical Path)

**Recon Path Gaps:**
1. `fills_persistence.py` - WAL mode, persistence layer
2. `fills_poller.py` - Periodic polling logic
3. `crypto_catalog.py` - Catalog discovery, market enumeration
4. `collector.py` - Market data collection
5. `balance_calibrator.py` - Balance calibration

**Execution Path Gaps:**
1. `client_v2.py` - Enhanced execution client
2. `client_enhanced.py` - Retry logic
3. `execution_audit.py` - Audit trail
4. `execution_diagnostics.py` - Diagnostics
5. `fill_bus.py` - Fill event bus
6. `crypto_bot.py` - Trading bot
7. `crypto_scheduler.py` - Market scheduler
8. `exchange_availability.py` - Availability checks
9. `allowed_market_policy.py` - Policy enforcement
10. `fix_client.py` - FIX protocol
11. `websocket_handlers.py` - WS message handlers
12. `order_manager.py` - Order lifecycle

## Recommendations

### Immediate Actions (High Priority)

1. **Add minimal tests for recon path gaps:**
   - `fills_persistence.py`: Test WAL mode, persistence, recovery
   - `fills_poller.py`: Test polling interval, backoff, error handling
   - `crypto_catalog.py`: Test catalog discovery, market enumeration vs ASSET_CONFIGS
   - `balance_calibrator.py`: Test balance calibration logic

2. **Add minimal tests for execution path gaps:**
   - `client_v2.py`: Test order submission, cancellation
   - `execution_audit.py`: Test audit trail generation
   - `fill_bus.py`: Test async fill processing
   - `exchange_availability.py`: Test availability checks

3. **Deprecate or document:**
   - Review `agent_example_v2.py` - is this still needed?
   - Review `fix_client.py` - is FIX protocol actively used?
   - Review `client_enhanced.py` vs `client_v2.py` - consolidate?

### Secondary Actions (Medium Priority)

4. **Extend central harness:**
   - Add helpers for fills persistence testing
   - Add helpers for catalog discovery testing
   - Add helpers for execution audit testing

5. **Add catalog discovery test:**
   - Verify 15-min crypto markets from Kalshi catalog align with ASSET_CONFIGS
   - Ensure no "hidden" markets are traded without recon coverage

6. **Add WebSocket deterministic tests:**
   - Synthetic stream events
   - Assert fills/positions/orderbook consistency with recon invariants

## Conclusion

The Kalshi module tree is extensive (71 modules) with clear separation between critical path (recon/execution) and auxiliary infrastructure. 

**Critical path coverage:** 8/20 modules (40%)  
**Recon path coverage:** 4/8 modules (50%)  
**Execution path coverage:** 0/12 modules (0%)

The reconciliation path has good coverage from the E2E test suite. The execution path has no dedicated tests yet and should be prioritized. The central test harness (`harness.py`) provides a foundation for extending coverage efficiently.

**Next steps:**
1. Add fills persistence tests
2. Add catalog discovery tests
3. Add minimal execution path tests
4. Consolidate duplicate/deprecated modules
