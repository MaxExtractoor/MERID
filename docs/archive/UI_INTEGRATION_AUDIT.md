# MERID UI Integration Audit
**Date:** 2026-02-04  
**Status:** Comprehensive Backend-to-Frontend Mapping

---

## Executive Summary

This document provides a complete audit of all MERID backend components (API routers, adapters, aggregators) and their integration status with the React dashboard UI.

---

## 🎯 Current UI Views

### Implemented Views
1. **Overview** (`Overview.tsx`) - Main dashboard
2. **Trading** (`Trading.tsx`) - Trading interface
3. **Positions** (`Positions.tsx`) - Position management
4. **Orders** (`Orders.tsx`) - Order history
5. **Agents** (`Agents.tsx`) - Agent management
6. **Research** (`Research.tsx`) - Research tools
7. **Risk** (`Risk.tsx`) - Risk management
8. **Health** (`Health.tsx`) - System health
9. **Logs** (`Logs.tsx`) - System logs
10. **Settings** (`Settings.tsx`) - Configuration
11. **Predictions** (`Predictions.tsx`) - Prediction markets (minimal)
12. **PredictionsPanel** (`PredictionsPanel.tsx`) - Prediction markets panel
13. **ApiDashboard** (`ApiDashboard.tsx`) - API status

---

## 📡 Backend API Routers (85 Total)

### ✅ CONNECTED TO UI (13 routers)

| Router | Prefix | UI Component | Status |
|--------|--------|--------------|--------|
| `dashboard.py` | `/api` | Overview.tsx | ✅ Active |
| `dashboard_data.py` | `/api/v1/dashboard` | Overview.tsx | ✅ Active |
| `us_compliant_markets.py` | `/api/v1/us-compliant` | PredictionsPanel.tsx | ✅ Active |
| `health.py` | `/api/v1/health` | Health.tsx | ✅ Active |
| `agents.py` | `/api/v1/agents` | Agents.tsx | ✅ Active |
| `system_control.py` | `/api/v1/system` | Settings.tsx | ✅ Active |
| `trading.py` | `/api/v1/trading` | Trading.tsx | ✅ Active |
| `paper_trading.py` | `/api/v1/paper` | Trading.tsx | ✅ Active |
| `risk.py` | `/risk` | Risk.tsx | ✅ Active |
| `streams.py` | `/ws` | Multiple | ✅ Active |
| `dashboard_ws.py` | `/ws/dashboard` | Overview.tsx | ✅ Active |
| `api_status.py` | `/api/v1/status` | ApiDashboard.tsx | ✅ Active |
| `live_data.py` | `/api/v1/live` | Multiple | ✅ Active |

### ⚠️ PARTIALLY CONNECTED (12 routers)

| Router | Prefix | Potential UI | Missing |
|--------|--------|--------------|---------|
| `analytics.py` | `/api/v1/analytics` | Research.tsx | No charts/graphs |
| `monitoring.py` | `/api/v1/monitoring` | Health.tsx | Limited metrics |
| `observability.py` | `/api/v1/observability` | Logs.tsx | No traces view |
| `trading_suite.py` | `/api/v1/trading-suite` | Trading.tsx | Advanced features |
| `arbitrage.py` | `/api/v1/arbitrage` | Trading.tsx | No arb panel |
| `prediction.py` | `/api/v1/prediction` | Predictions.tsx | Limited integration |
| `intelligence.py` | `/api/v1/intelligence` | Research.tsx | No AI insights |
| `explainability.py` | `/api/v1/explainability` | Agents.tsx | No explain view |
| `reflection.py` | `/api/v1/reflection` | Agents.tsx | No reflection UI |
| `brier_metrics.py` | `/api/v1/brier` | Predictions.tsx | No metrics display |
| `feedback.py` | `/api/v1/feedback` | Settings.tsx | No feedback form |
| `schemas.py` | `/api/v1/schemas` | Multiple | No schema browser |

### ❌ NOT CONNECTED TO UI (60 routers)

#### High Priority - Should Have UI
| Router | Prefix | Suggested UI Location |
|--------|--------|----------------------|
| `wallet.py` | `/api/v1/wallet` | New: Wallet view |
| `treasury.py` | `/api/v1/treasury` | New: Treasury view |
| `swarm.py` | `/swarm` | Agents.tsx expansion |
| `prime_screen.py` | `/api/v1/swarm/prime-screen` | Agents.tsx expansion |
| `autonomy.py` | `/api/v1/autonomy` | Settings.tsx |
| `governance.py` | `/api/v1/governance` | New: Governance view |
| `quadratic_funding.py` | `/api/v1/quadratic-funding` | Treasury view |
| `referrals.py` | `/api/v1/referrals` | Settings.tsx |
| `notifications.py` | `/api/v1/notifications` | Header component |
| `backup.py` | `/api/v1/backup` | Settings.tsx |
| `recovery.py` | `/api/v1/recovery` | Settings.tsx |
| `compliance.py` | `/api/v1/compliance` | Settings.tsx |
| `ratelimit.py` | `/api/v1/ratelimit` | ApiDashboard.tsx |
| `cost_models.py` | `/api/v1/cost-models` | Settings.tsx |

#### Medium Priority - Nice to Have
| Router | Prefix | Suggested UI Location |
|--------|--------|----------------------|
| `betting.py` | `/api/v1/betting` | New: Betting view |
| `sniping.py` | `/api/v1/sniping` | Trading.tsx |
| `time_exploit.py` | `/api/v1/time-exploit` | Trading.tsx |
| `mining.py` | `/api/v1/mining` | New: Mining view |
| `offline.py` | `/api/v1/offline` | Settings.tsx |
| `x_bot.py` | `/x-bot` | New: Social view |
| `moat.py` | `/moat` | Research.tsx |
| `institutional.py` | `/api/v1/institutional` | New: Institutional view |
| `local_venue.py` | `/api/v1/local-venue` | Trading.tsx |
| `plugins.py` | `/api/v1/plugins` | Settings.tsx |

#### Low Priority - Internal/Admin
| Router | Prefix | Notes |
|--------|--------|-------|
| `ops.py` | `/api/v1/ops` | Admin only |
| `archive.py` | `/api/v1/archive` | Admin only |
| `degraded.py` | `/api/v1/degraded` | Admin only |
| `trading_mode.py` | `/api/v1/trading-mode` | Admin only |
| `production_status.py` | `/api/v1/production` | Admin only |
| `minimal_scope.py` | `/api/v1/minimal-scope` | Internal |
| `phase0_*` | `/api/v1/phase0/*` | Experimental |
| `reality.py` | `/api/v1/reality` | Experimental |
| `*_assertions.py` | `/api/v1/*/assertions` | Testing |
| `domain_priority.py` | `/api/v1/domain-priority` | Internal |
| `auth.py` | `/api/v1/auth` | Backend only |
| `ui_audit.py` | `/api/v1/ui-audit` | This audit |
| `test_page.py` | `/test-*` | Testing |
| `ws_paper.py` | `/ws/paper` | Internal WS |
| `data_endpoints.py` | `/api/v1/data` | Internal |
| `live_stream.py` | `/api/v1/stream` | Internal |
| `governance_cadence.py` | `/api/v1/governance-cadence` | Disabled |
| `mock_*.py` | Various | Testing only |
| `predictions_backup.py` | N/A | Backup file |
| `dev_chat.py` | N/A | Development |

---

## 🔌 Trading Venue Adapters (16 Total)

### Crypto Exchanges
| Adapter | Status | UI Integration |
|---------|--------|----------------|
| `alpaca_adapter.py` | ✅ Active | Trading.tsx (stocks) |
| `coinbase_advanced_adapter.py` | ✅ Active | Trading.tsx (crypto) |
| `kraken_adapter.py` | ✅ Active | Trading.tsx (crypto) |
| `binanceus_adapter.py` | ⚠️ Limited | Not visible in UI |
| `gemini_adapter.py` | ⚠️ Limited | Not visible in UI |
| `kucoin_adapter.py` | ⚠️ Limited | Not visible in UI |
| `okx_adapter.py` | ⚠️ Limited | Not visible in UI |
| `bitget_adapter.py` | ⚠️ Limited | Not visible in UI |
| `gateio_adapter.py` | ⚠️ Limited | Not visible in UI |
| `htx_adapter.py` | ⚠️ Limited | Not visible in UI |
| `mexc_adapter.py` | ⚠️ Limited | Not visible in UI |

### Traditional/Other
| Adapter | Status | UI Integration |
|---------|--------|----------------|
| `ibkr_adapter.py` | ⚠️ Limited | Not visible in UI |
| `kalshi_adapter.py` | ✅ Active | PredictionsPanel.tsx |
| `polymarket_adapter.py` | ⚠️ Limited | Not visible in UI |
| `merid_sim_adapter.py` | ✅ Active | Trading.tsx (paper) |
| `local_sim_adapter.py` | ✅ Active | Trading.tsx (paper) |

**Missing UI:** Venue selector dropdown in Trading view to choose exchange

---

## 📊 Data Aggregators

### Market Data
| Aggregator | Location | UI Integration |
|------------|----------|----------------|
| `USCompliantDataAggregator` | `data/us_compliant_data_sources.py` | ✅ us_compliant_markets.py |
| `PredictionMarketsAggregator` | `data/us_compliant_data_sources.py` | ⚠️ Partially (empty data) |
| `PredictionMarketAggregator` | `monitoring/prediction_markets.py` | ⚠️ Partially (Kalshi) |
| `LivePriceFeed` | `data/live_price_feed.py` | ✅ dashboard.py |
| `PortfolioAggregator` | `execution/portfolio.py` | ❌ Not connected |

### Agent/System
| Aggregator | Location | UI Integration |
|------------|----------|----------------|
| `SwarmLabOrchestrator` | `swarm/orchestrator.py` | ❌ Not connected |
| `AgentOrchestrator` | `core/agent_orchestrator.py` | ✅ Agents.tsx |
| `ReflectionLayer` | `agents/reflection_layer.py` | ❌ Not connected |

---

## 🚨 Critical Missing UI Components

### 1. **Wallet Management** (HIGH PRIORITY)
- **Backend:** `wallet.py` - Full wallet API ready
- **Missing:** Wallet view with balances, transfers, hardware wallet support
- **Impact:** Users can't manage funds through UI

### 2. **Treasury/DAO** (HIGH PRIORITY)
- **Backend:** `treasury.py`, `quadratic_funding.py`, `governance.py`
- **Missing:** Treasury dashboard, governance voting, funding proposals
- **Impact:** No DAO functionality visible

### 3. **Venue Selector** (HIGH PRIORITY)
- **Backend:** 16 venue adapters ready
- **Missing:** Dropdown to select trading venue
- **Impact:** Can only trade on default venue

### 4. **Swarm Intelligence** (MEDIUM PRIORITY)
- **Backend:** `swarm.py`, `prime_screen.py`, `SwarmLabOrchestrator`
- **Missing:** Swarm coordination view, agent spawning UI
- **Impact:** Advanced agent features hidden

### 5. **Advanced Analytics** (MEDIUM PRIORITY)
- **Backend:** `analytics.py`, `brier_metrics.py`, `intelligence.py`
- **Missing:** Charts, graphs, AI insights panels
- **Impact:** Limited data visualization

### 6. **Notifications** (MEDIUM PRIORITY)
- **Backend:** `notifications.py` - Full notification system
- **Missing:** Notification bell/panel in header
- **Impact:** Users miss important alerts

### 7. **Arbitrage Trading** (MEDIUM PRIORITY)
- **Backend:** `arbitrage.py` - Full arb detection
- **Missing:** Arbitrage opportunities panel
- **Impact:** Can't see/execute arb trades

### 8. **Explainability** (MEDIUM PRIORITY)
- **Backend:** `explainability.py` - Agent decision explanations
- **Missing:** "Why did the agent do this?" UI
- **Impact:** Black box agent behavior

### 9. **Social/X Bot** (LOW PRIORITY)
- **Backend:** `x_bot.py` - Twitter integration
- **Missing:** Social feed view
- **Impact:** No social trading features

### 10. **Institutional Features** (LOW PRIORITY)
- **Backend:** `institutional.py` - 82KB of institutional APIs
- **Missing:** Institutional dashboard
- **Impact:** Institutional features hidden

---

## 📋 Recommended Implementation Priority

### Phase 1: Critical (Week 1)
1. ✅ **Wallet View** - Create `Wallet.tsx` connected to `wallet.py`
2. ✅ **Venue Selector** - Add dropdown in `Trading.tsx` for all 16 venues
3. ✅ **Notifications** - Add notification bell to header using `notifications.py`
4. ✅ **Portfolio Aggregator** - Wire `PortfolioAggregator` to Overview

### Phase 2: High Value (Week 2)
5. ✅ **Treasury View** - Create `Treasury.tsx` for DAO/governance
6. ✅ **Arbitrage Panel** - Add arb opportunities to `Trading.tsx`
7. ✅ **Analytics Charts** - Add charts to `Research.tsx` using `analytics.py`
8. ✅ **Swarm View** - Expand `Agents.tsx` with swarm features

### Phase 3: Enhancement (Week 3)
9. ✅ **Explainability** - Add "Explain" buttons to agent actions
10. ✅ **Brier Metrics** - Add prediction accuracy metrics to `Predictions.tsx`
11. ✅ **Advanced Settings** - Wire all settings APIs to `Settings.tsx`
12. ✅ **Social Feed** - Create `Social.tsx` for X bot integration

### Phase 4: Nice to Have (Week 4)
13. ✅ **Betting View** - Create `Betting.tsx` for betting markets
14. ✅ **Mining View** - Create `Mining.tsx` for mining operations
15. ✅ **Institutional View** - Create `Institutional.tsx` for institutions
16. ✅ **Plugin Manager** - Add plugin management to `Settings.tsx`

---

## 🔍 Component Mapping Details

### Overview.tsx - Currently Connected
- ✅ `/api/portfolio/summary` - Portfolio data
- ✅ `/api/prices/live` - Live prices
- ✅ `/api/orders/recent` - Recent orders
- ✅ `/api/agents/activity` - Agent activity
- ✅ `/api/v1/dashboard/*` - Dashboard cards
- ❌ Missing: Treasury balance, Wallet balance, Notifications

### Trading.tsx - Currently Connected
- ✅ `/api/v1/trading/*` - Trading operations
- ✅ `/api/v1/paper/*` - Paper trading
- ❌ Missing: Venue selector, Arbitrage panel, Sniping tools

### Agents.tsx - Currently Connected
- ✅ `/api/v1/agents/*` - Agent management
- ❌ Missing: Swarm view, Reflection layer, Explainability

### Predictions.tsx - Currently Connected
- ✅ `/api/v1/us-compliant/prediction-markets` - Kalshi markets
- ❌ Missing: Brier metrics, Multiple platforms, Betting integration

### Risk.tsx - Currently Connected
- ✅ `/risk/*` - Risk metrics
- ❌ Missing: Circuit breaker controls, Advanced risk analytics

### Settings.tsx - Currently Connected
- ✅ `/api/v1/system/*` - System control
- ❌ Missing: Backup/recovery, Compliance, Plugins, Referrals

---

## 📊 Statistics

- **Total API Routers:** 85
- **Connected to UI:** 13 (15%)
- **Partially Connected:** 12 (14%)
- **Not Connected:** 60 (71%)

- **Total Venue Adapters:** 16
- **Visible in UI:** 3 (19%)
- **Not Visible:** 13 (81%)

- **Total Aggregators:** 8
- **Connected:** 3 (38%)
- **Not Connected:** 5 (62%)

---

## 🎯 Next Steps

1. **Review this audit** with team
2. **Prioritize missing components** based on user needs
3. **Create UI components** for Phase 1 items
4. **Wire backend APIs** to new components
5. **Test end-to-end** functionality
6. **Iterate** based on feedback

---

**Last Updated:** 2026-02-04  
**Audit By:** Cascade AI  
**Status:** Complete - Ready for Implementation
