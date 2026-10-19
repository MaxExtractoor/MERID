# Audit Step 1: Repository and Infrastructure Inventory

**Date:** 2026-05-12  
**Repository:** https://github.com/MaxExtractoor/MERID.git  
**Current Branch:** develop (commit 42ba0f26)  
**Production Branch:** main (inferred from git branches)

---

## Repository Structure

### Primary Repository
- **Path:** c:\Dev\MERID
- **Remote:** https://github.com/MaxExtractoor/MERID.git
- **Current Branch:** develop
- **Latest Commit:** 42ba0f26 - "Fix circular import: import _ALLOWED_TIMEFRAMES/_ALLOWED_UNDERLYINGS from market_constraints"
- **Production Branch:** main (inferred)

### Key Directories

| Directory | Purpose | Status |
|-----------|---------|--------|
| `merid/` | Core trading engine, agents, prediction, event venues | Active |
| `core/` | Core infrastructure (events, governance, consensus) | Active |
| `execution/` | Execution layer, order routing, executors | Active |
| `event_venues/kalshi/` | Kalshi integration (client, fills, positions, reconciliation) | Active |
| `risk/` | Risk management, kill switches, error classification | Active |
| `trading/` | Trading state, continuous trader, execution | Active |
| `prediction/` | Signal calculation, agents, consensus, strategy | Active |
| `data/` | Data ingestion, state, snapshots | Active |
| `monitoring/` | Metrics, alerts, dashboards | Active |
| `web/` | Web UI (React + FastAPI backend) | Active |
| `config/` | Configuration files, profiles, specs | Active |
| `scripts/` | 200+ utility scripts (audit, validation, deployment) | Active |
| `tests/` | 373+ test files | Active |
| `backtesting/` | Backtesting engine, replay | Active |
| `simulation/` | Shadow trading, simulation | Active |

---

## Live Services and Components

### Trading Engine
- **Main Loop:** `merid/loop.py`
- **Trading Agent:** `merid/prediction/trading_agent.py`
- **Signal Calculation:** `merid/prediction/crypto_edge_production.py`
- **Consensus:** `merid/swarm/consensus_aggregator.py`
- **Called by:** `web/main.py` (FastAPI server), `merid/trading/kalshi_continuous_trader.py`

### Data Ingestion
- **Crypto Spot:** `merid/data/rti_feed_service.py`
- **Kalshi Markets:** `merid/event_venues/kalshi/market_catalog.py`
- **Kalshi Fills:** `merid/event_venues/kalshi/fills_poller.py`
- **Kalshi Positions:** `merid/event_venues/kalshi/position_cache.py`
- **Called by:** Main loop, Kalshi continuous trader

### Signal Calculation
- **15m Crypto Edge:** `merid/prediction/crypto_edge_production.py`
- **Band Strategy:** `merid/strategies/band_strategy_15m.py`
- **FVG Integration:** `merid/prediction/fvg_integration.py`
- **Called by:** Trading agents, consensus aggregator

### Sizing/Risk
- **Position Sizing:** `merid/event_venues/kalshi/position_sizer.py`
- **Risk Engine:** `merid/risk/unified_risk_engine.py`
- **Kill Switches:** `merid/risk/kill_switches.py`
- **Error Budget:** `merid/core/error_budget.py`
- **Called by:** Order router, execution gate

### Execution/Venue Adapters
- **Kalshi Client:** `merid/event_venues/kalshi/client.py`, `client_v2.py`
- **Order Router:** `merid/event_venues/kalshi/order_router.py`
- **Execution Queue:** `merid/execution/execution_queue.py`
- **Kalshi Executor:** `merid/execution/executors/kalshi.py`
- **Called by:** Trading agent, continuous trader

### Kalshi Integration
- **Fills Ledger:** `merid/event_venues/kalshi/fills_ledger.py`
- **Portfolio Engine:** `merid/event_venues/kalshi/portfolio_engine.py`
- **PnL Computer:** `merid/event_venues/kalshi/portfolio_pnl_computer.py`
- **Reconciliation:** `merid/event_venues/kalshi/portfolio_reconciliation.py`
- **Called by:** Main loop, monitoring

### PnL/Reports
- **PnL Attribution:** `merid/prediction/pnl_attribution.py`
- **Hedge PnL Tracker:** `merid/hedging/pnl_tracker.py`
- **Agent Performance:** `merid/prediction/agent_performance_tracker.py`
- **Called by:** Analytics, reporting jobs

### Monitoring
- **Kalshi Metrics:** `merid/metrics/kalshi_metrics.py`
- **Monitoring:** `merid/monitoring/kalshi_metrics.py`
- **Alerts:** `merid/alerts/trade_notifier.py`, `reconciliation_alerts.py`
- **Called by:** Main loop, web API

---

## Configuration Files

### Environment Profiles
- **Baseline:** `config/profiles/env.baseline.kalshi-pm.live.example`
- **Production:** `config/profiles/env.prod.kalshi-pm.live.example`
- **Stage/Paper:** `config/profiles/env.stage.kalshi-pm.paper.example`

### Key Config Files
- `config/settings.py` - Main settings
- `config/settings.yaml` - YAML settings
- `config/kalshi_crypto_config.py` - Kalshi crypto configuration
- `config/kalshi_crypto_hedging.yaml` - Hedging rules
- `config/kalshi_agent_grid.yaml` - Agent grid configuration
- `config/crypto_spot_kalshi_config.py` - Spot vs Kalshi mapping
- `config/trade_hold_config.yaml` - Trade hold configuration
- `config/rate_limits.yaml` - Rate limiting

### Environment Variables (inferred from code)
- `KALSHI_ENV` - Kalshi environment (demo/production)
- `MERID_MAX_DAILY_LOSS_USD` - Daily loss limit
- `MERID_MAX_POSITION_VALUE_USD` - Max position size
- `MERID_ERROR_THRESHOLD` - Error threshold for kill switch
- `MERID_FRESH_START` - Fresh start mode flag

---

## Critical Findings

### 🔴 CRITICAL: Risk Bypass in Production Code

**File:** `merid/prediction/strategy.py` (line 1634)
```python
# TEMPORARILY DISABLED (2026-05-09): Blocking all trades due to neutral sentiment (MarketMoodBus issue)
# Re-enable after MarketMoodBus context population is fixed
# if phase == ExpiryPhase.TERMINAL and prob_edge < 0.03:
#     logger.warning(...)
#     return StrategySignal(action=SignalAction.NO_ACTION, ...)
```

**Impact:** Terminal phase trading ban (weak edge protection) is disabled. This allows trades in the last hour of contracts even when the model has weak edge (< 3%).

**Risk:** High - This bypasses a critical risk control designed to prevent bad trades at contract expiry.

**Recommendation:** Re-enable immediately after fixing MarketMoodBus context population issue.

---

### 🟡 WARNING: TODO/FIXME in Production Paths

**Files with TODO/FIXME in hot paths:**
- `merid/event_venues/kalshi/bankroll_service_v2.py:233` - "Temporary error - FAIL-CLOSED"
- `merid/event_venues/kalshi/order_manager.py:536` - "Temporarily allow polling by unsetting terminal"
- `merid/event_venues/kalshi/agent_example_v2.py:74` - "Temporary error but we have cached data"
- `merid/sentiment/news_sentiment_bridge.py:117` - "Hack/security"

**Impact:** These are mostly error handling paths, but should be reviewed to ensure they don't mask critical issues.

---

### 🟢 INFO: Template Files

Many files contain "Template" comments (e.g., `BACKEND_INTEGRATION_TEMPLATE.py`, `web/api/minimal_scope.py`). These are scaffolding and not production code.

---

## Untracked Scripts (Potential Risk)

**Scripts directory contains 200+ scripts, many with underscores (`_audit_*.py`, `_fix_*.py`, `_fpa_*.py`). These appear to be audit/fix utilities.**

**Key categories:**
- Audit scripts: `_audit_*.py`, `comprehensive_system_audit.py`, `deep_system_audit.py`
- Fix scripts: `_fix_*.py` (silent except, toFixed guards, etc.)
- FPA (Full Production Audit) scripts: `_fpa_*.py`
- Validation scripts: `validate_*.py`
- Deployment scripts: `configure_production.ps1`, `verify_deploy.py`

**Risk:** Some of these scripts may have production impact. Need to verify none are crontabbed on prod boxes.

---

## Next Steps for Step 1

1. ✅ Enumerate repos and services - DONE
2. ✅ Confirm production branches - DONE (develop is current, main is production)
3. ⏳ Check for untracked scripts crontabbed on prod boxes - NEED ACCESS TO PROD
4. ✅ Check for "temporary" risk bypass flags - FOUND 1 CRITICAL

---

## Summary

**Obviously Broken:**
1. Terminal phase trading ban disabled in `merid/prediction/strategy.py` (CRITICAL)

**Probably Fine:**
- Template files (scaffolding, not production)
- Most TODO/FIXME comments in error handling paths

**Weird/Unclear:**
- 200+ scripts in `scripts/` directory - need to verify none are crontabbed on prod
- Multiple underscore-prefixed scripts (`_audit_`, `_fix_`, `_fpa_`) - purpose unclear without prod access
