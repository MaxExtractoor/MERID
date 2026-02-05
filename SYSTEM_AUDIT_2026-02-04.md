# MERID System Audit Report
**Date:** 2026-02-04  
**Status:** Comprehensive System Review  
**Purpose:** Full codebase audit, UI inventory, port configuration, missing components

---

## Executive Summary

### System Status
- **Backend API**: Running on port 8000 (FastAPI)
- **React Dashboard**: Running on port 5174 (Vite dev server)
- **Test Coverage**: 85.29% (2,205 tests passing)
- **Active Agents**: 8 agents operational
- **Live Data Feeds**: 6 exchanges, Kalshi markets, news feeds

### Critical Issues
1. **Port Configuration**: No centralized port management - services use different ports on restart
2. **Missing UI Components**: Some features lack frontend implementation
3. **Incomplete Integration**: Several API keys configured but not fully integrated

---

## 1. PORT CONFIGURATION AUDIT

### Current Port Usage (Inconsistent)
| Service | Current Port | Should Be | Config File |
|---------|-------------|-----------|-------------|
| FastAPI Backend | 8000 | 8000 | None (CLI arg) |
| React Dashboard | 5174 | 5173 | vite.config.ts |
| User UI (start_merid.py) | 3000 | 3000 | start_merid.py:L11 |
| Agent Mesh | 8080 | 8080 | start_merid.py:L12 |
| Ops/Admin | 9090 | 9090 | start_merid.py:L13 |
| Telemetry | 9091 | 9091 | start_merid.py:L14 |

### Issues
- React dev server increments port (5173 → 5174) if 5173 is occupied
- FastAPI has no default port config (relies on CLI)
- Frontend API config points to port 8000 but User UI runs on 3000

### Required Fixes
1. Create `.env` entries for all ports
2. Update `start_merid.py` to read from env
3. Update React config to use fixed port
4. Update frontend API config to match backend port

---

## 2. CODEBASE STRUCTURE AUDIT

### Core Modules (Complete)
```
c:\Dev\MERID\
├── agents/                  ✅ 71 files - Agent framework, charters, reflection
├── analytics/               ✅ 18 files - Brier metrics, performance tracking
├── arbitrage/              ✅ 12 files - Cross-venue arbitrage detection
├── auth/                   ✅ User authentication, JWT management
├── backtesting/            ✅ 4 files - Replay engine, deterministic testing
├── cognitive_core/         ✅ 20 files - Agent cognition, reasoning
├── compliance/             ✅ 7 files - Regulatory compliance checks
├── config/                 ✅ 8 files - System configuration
├── contracts/              ✅ 14 files - Smart contract interfaces
├── core/                   ✅ 170 files - Orchestrator, state, energy
├── data/                   ✅ 82 files - Price feeds, market data
├── defi/                   ✅ 13 files - DeFi protocol integrations
├── execution/              ✅ 10 files - Order execution, routing
├── governance/             ✅ 32 files - Policy engine, risk controls
├── hardening/              ✅ 5 files - Chaos testing, resilience
├── infra/                  ✅ 10 files - Infrastructure management
├── learning/               ✅ 22 files - ML models, training
├── memory/                 ✅ 5 files - Pattern storage, reality registry
├── merid/                  ✅ 38 files - Core MERID logic
├── monitoring/             ✅ 32 files - Health checks, prediction markets
├── observability/          ✅ 9 files - Metrics, event streams
├── ops/                    ✅ 24 files - Operations tooling
├── prediction/             ✅ 8 files - Prediction market logic
├── risk/                   ✅ 3 files - Risk management
├── security/               ✅ 16 files - Security controls
├── simulation/             ✅ 14 files - Market simulation
├── swarm/                  ✅ 92 files - Multi-agent swarm
├── trading/                ✅ 35 files - Trading adapters, execution
├── utils/                  ✅ 29 files - Utilities, logging
├── web/                    ✅ 236 files - API endpoints, UI
└── tests/                  ✅ 543 files - Test suite (2,205 tests)
```

### Trading Adapters (Status)
| Adapter | Status | Coverage | Notes |
|---------|--------|----------|-------|
| Alpaca | ✅ Complete | 100% | Paper trading ready |
| Binance | ✅ Complete | 95%+ | Live API configured |
| Coinbase | ✅ Complete | 95%+ | Live API configured |
| Kraken | ✅ Complete | 95%+ | Live API configured |
| OKX | ✅ Complete | 95%+ | Read-only configured |
| Paper Trading | ✅ Complete | 94% | Full simulation |
| PumpFun | ✅ Complete | 90%+ | Solana DEX |
| Polymarket | ✅ Complete | 100% | Prediction markets |
| Kalshi | ✅ Fixed | 95%+ | Now fetching real markets |

---

## 3. UI AUDIT

### A. React Dashboard (`web/react/`)
**Status:** 85% Complete  
**Port:** 5174 (should be 5173)  
**Framework:** React 18 + Vite + TypeScript

#### Implemented Views (8/8)
1. ✅ **Overview.tsx** - Dashboard home, metrics summary
2. ✅ **Trading.tsx** - Order ticket, positions, live trading
3. ✅ **Agents.tsx** - Bot status, performance, controls
4. ✅ **Predictions.tsx** - Polymarket/Kalshi markets
5. ✅ **Risk.tsx** - Risk alerts, health metrics
6. ✅ **Research.tsx** - Backtesting, analysis tools
7. ✅ **Logs.tsx** - System logs, audit trail
8. ✅ **Settings.tsx** - User preferences, config

#### Components (14/14)
- ✅ Sidebar, TopBar, MetricCard, DataTableEnhanced
- ✅ PriceTicker, StatusIndicator, RiskProtectionsPanel
- ✅ ConsoleViewer, ChartCard, ChartWrapper
- ✅ PortfolioChart, SocketTest, ThemeToggle

#### Hooks (23/23)
- ✅ useApiData, useWebSocket, useLocalStorage
- ✅ useAgentsHealth, useOpenOrders, usePredictions
- ✅ useRiskMetrics, useRiskProtections, useEquityChart
- ✅ useDashboard (fixed .tsx extension)

#### Missing/Incomplete
- ⚠️ **Testing**: Unit tests, E2E tests (low priority)
- ⚠️ **Documentation**: Component docs, API docs
- ⚠️ **Performance**: Bundle optimization, lazy loading

### B. Backend APIs (`web/api/`)
**Status:** Comprehensive  
**Port:** 8000  
**Framework:** FastAPI

#### API Routers (83 files)
```
web/api/
├── agents.py              ✅ Agent management
├── analytics.py           ✅ Analytics endpoints
├── arbitrage.py           ✅ Arbitrage opportunities
├── auth.py                ✅ Authentication
├── backup.py              ✅ Backup management
├── betting.py             ✅ Betting markets
├── compliance.py          ✅ Compliance checks
├── cost_models.py         ✅ Cost modeling
├── dashboard_data.py      ✅ Dashboard data
├── data_endpoints.py      ✅ Market data
├── explainability.py      ✅ AI explainability
├── governance.py          ✅ Governance policies
├── health.py              ✅ Health checks
├── institutional.py       ✅ Institutional features
├── live_stream.py         ✅ Live data streams
├── mining.py              ✅ Mining operations
├── monitoring.py          ✅ System monitoring
├── notifications.py       ✅ Notification system
├── offline.py             ✅ Offline mode
├── paper_trading.py       ✅ Paper trading
├── phase0_*.py            ✅ Phase 0 trial system
├── plugins.py             ✅ Plugin system
├── prediction.py          ✅ Prediction markets
├── quadratic_funding.py   ✅ Quadratic funding
├── ratelimit.py           ✅ Rate limiting
├── reality.py             ✅ Reality enforcement
├── recovery.py            ✅ Disaster recovery
├── referrals.py           ✅ Referral system
├── reflection.py          ✅ Agent reflection
├── schemas.py             ✅ Data schemas
├── sniping.py             ✅ MEV sniping
├── streams.py             ✅ Data streams
├── system_control.py      ✅ System controls
├── time_exploit.py        ✅ Time arbitrage
├── trading.py             ✅ Trading operations
├── treasury.py            ✅ Treasury management
├── ui_audit.py            ✅ UI auditing
├── us_compliant_markets.py ✅ US-compliant markets
├── wallet.py              ✅ Wallet management
└── ... (44 more files)
```

### C. Legacy/Alternative UIs
1. **web/templates/** - Jinja2 templates (12 files) - ⚠️ Legacy, not actively used
2. **web/static/** - Static assets (4 items) - ✅ Serving React build
3. **Flutter App** (`lib/`, `flutter/`) - ⚠️ Mobile app (incomplete, 418 files)

---

## 4. MISSING COMPONENTS & INCOMPLETE FEATURES

### High Priority Missing
1. **Port Configuration System**
   - No centralized port management
   - Services use hardcoded or CLI ports
   - **Fix:** Create port config in `.env` and startup scripts

2. **Frontend-Backend Connection**
   - React points to port 8000
   - `start_merid.py` runs User UI on port 3000
   - **Fix:** Align on single backend port (8000)

3. **Service Orchestration**
   - Multiple startup scripts (`start_merid.py`, `startup.py`, `startup_minimal.py`)
   - No single "start everything" command
   - **Fix:** Create unified startup script

### Medium Priority Missing
1. **Flutter Mobile App**
   - 418 files present but incomplete
   - Not integrated with backend
   - **Status:** Deprioritize or remove

2. **Testing Infrastructure**
   - React: No E2E tests
   - Backend: Good coverage (85%) but missing integration tests
   - **Status:** Low priority

3. **Documentation**
   - API documentation incomplete
   - Component documentation missing
   - **Status:** Medium priority

### Low Priority Missing
1. **Performance Optimization**
   - React bundle not optimized
   - No lazy loading
   - **Status:** Post-launch

2. **Advanced Features**
   - Some prediction market platforms not integrated (Augur, PredictIt)
   - Advanced charting not implemented
   - **Status:** Future enhancements

---

## 5. API KEY INTEGRATION STATUS

### Fully Integrated ✅
- Alpaca (paper trading)
- Binance (live trading)
- Coinbase (live trading)
- Kraken (live trading)
- OKX (read-only)
- Kalshi (prediction markets) - **Fixed today**
- OpenAI, Claude, DeepSeek (AI models)
- Telegram (notifications)
- MongoDB, Redis (databases)
- Helius (Solana RPC)

### Partially Integrated ⚠️
- Polygon (configured but not actively used)
- Messari (configured but limited usage)
- Alpha Vantage (configured but not primary data source)
- Finnhub (configured but not primary)
- FRED (configured but not primary)
- The Graph (configured but not actively queried)
- Nansen (configured but not integrated)
- Twilio (configured but not actively used)
- X/Twitter (configured but limited posting)

### Not Integrated ❌
- IBKR Paper Trading (credentials present but no adapter)
- Bybit (placeholder credentials)
- Polymarket (US-restricted, disabled)

---

## 6. STARTUP SCRIPTS INVENTORY

### Primary Startup Scripts
1. **`start_merid.py`** ✅ Main production startup
   - Starts 4 services: User UI (3000), Agent Mesh (8080), Ops (9090), Telemetry (9091)
   - Uses uvicorn subprocess spawning
   - **Issue:** Doesn't start main FastAPI app on port 8000

2. **`startup.py`** ⚠️ Alternative startup
   - More comprehensive initialization
   - Includes health checks
   - **Issue:** Some components fail (missing modules)

3. **`startup_minimal.py`** ⚠️ Minimal startup
   - Lightweight version
   - **Status:** Unclear when to use vs `start_merid.py`

### Supporting Scripts
- `web/main.py` - FastAPI app definition (must be started separately)
- `web/react/package.json` - React dev server (`npm run dev`)

---

## 7. CONFIGURATION FILES AUDIT

### Environment Configuration
- ✅ `.env` - Master environment file (242 lines, comprehensive)
- ✅ `.env.example` - Example template
- ✅ `.env.backup` - Backup copy

### Application Configuration
- ✅ `pytest.ini` - Test configuration
- ✅ `.coveragerc` - Coverage configuration (40% floor)
- ✅ `ruff.toml` - Linting configuration
- ✅ `mypy.ini` - Type checking
- ⚠️ **Missing:** Centralized port configuration file

### Build Configuration
- ✅ `web/react/vite.config.ts` - Vite config
- ✅ `web/react/package.json` - NPM dependencies
- ✅ `web/react/tsconfig.json` - TypeScript config
- ✅ `requirements.txt` - Python dependencies

---

## 8. DATABASE & PERSISTENCE AUDIT

### Databases in Use
1. **Neo4j** (Graph DB)
   - URI: `neo4j://localhost:7687`
   - Status: ✅ Configured, optional (skipped in Phase 0)

2. **MongoDB** (Document DB)
   - URI: Cloud Atlas
   - Status: ✅ Configured and connected

3. **Redis** (Cache/Queue)
   - URI: Cloud Redis Labs
   - Status: ✅ Configured and connected

4. **SQLite** (Local DBs)
   - `assertions.db` - Assertion framework
   - `brier_metrics.db` - Brier score tracking
   - Status: ✅ Active

5. **Supabase** (Cloud Postgres)
   - Status: ✅ Configured

---

## 9. EXTERNAL INTEGRATIONS AUDIT

### Trading Venues (9 total)
- ✅ Alpaca (paper)
- ✅ Binance
- ✅ Coinbase
- ✅ Kraken
- ✅ OKX
- ⚠️ Bybit (not configured)
- ⚠️ IBKR (credentials only)
- ✅ PumpFun (Solana)
- ✅ Kalshi (prediction)

### Data Providers (10 total)
- ✅ CCXT (multi-exchange)
- ⚠️ Polygon
- ⚠️ Messari
- ⚠️ Alpha Vantage
- ⚠️ Finnhub
- ⚠️ FRED
- ⚠️ The Graph
- ⚠️ Nansen
- ✅ Helius (Solana)
- ✅ News API

### AI/ML Services (5 total)
- ✅ OpenAI
- ✅ Claude (Anthropic)
- ✅ DeepSeek
- ✅ Ollama (local)
- ✅ OpenRouter

### Communication (3 total)
- ✅ Telegram
- ⚠️ Twilio
- ⚠️ X/Twitter

---

## 10. CRITICAL RECOMMENDATIONS

### Immediate Actions (This Week)
1. **Lock Port Configuration**
   - Add to `.env`: `MERID_BACKEND_PORT=8000`, `MERID_FRONTEND_PORT=5173`, etc.
   - Update all startup scripts to read from env
   - Update React config to use fixed port

2. **Unify Startup**
   - Create single `start.sh` / `start.ps1` that starts:
     - FastAPI backend (port 8000)
     - React frontend (port 5173)
   - Deprecate multiple startup scripts

3. **Fix Frontend-Backend Connection**
   - Ensure React API config points to correct backend port
   - Test all API endpoints from frontend

### Short-Term (This Month)
1. **Complete API Integration**
   - Integrate or remove unused API keys (Polygon, Messari, etc.)
   - Document which services are active vs configured

2. **Flutter App Decision**
   - Evaluate: Continue development or remove
   - If remove: Clean up 418 files

3. **Documentation**
   - Create API documentation
   - Document startup procedures
   - Create system architecture diagram

### Long-Term (Next Quarter)
1. **Performance Optimization**
   - React bundle optimization
   - Lazy loading
   - CDN for static assets

2. **Testing**
   - E2E tests for critical flows
   - Integration tests for external APIs
   - Load testing

3. **Monitoring**
   - Centralized logging
   - Performance metrics
   - Alerting system

---

## 11. SYSTEM HEALTH SUMMARY

### ✅ Strengths
- Comprehensive backend API (83 endpoints)
- High test coverage (85.29%, 2,205 tests)
- Complete React dashboard (8 views, 14 components)
- Live data feeds operational (6 exchanges, Kalshi markets)
- 8 active agents with reflection system
- Strong security (JWT, rate limiting, compliance)

### ⚠️ Weaknesses
- Port configuration not centralized
- Multiple startup scripts (confusing)
- Some API keys configured but not integrated
- Flutter app incomplete (418 files)
- Frontend-backend port mismatch

### 🔴 Critical Issues
1. Port management (services change ports on restart)
2. No single unified startup command
3. React dev server port increments

---

## 12. NEXT STEPS

### Phase 1: Port Configuration (Today)
- [ ] Add port env vars to `.env`
- [ ] Update `start_merid.py` to use env ports
- [ ] Update React `vite.config.ts` for fixed port
- [ ] Update frontend API config
- [ ] Test full startup

### Phase 2: Startup Unification (This Week)
- [ ] Create unified `start.sh` / `start.ps1`
- [ ] Document startup procedure
- [ ] Deprecate old startup scripts

### Phase 3: Integration Cleanup (This Month)
- [ ] Audit unused API integrations
- [ ] Remove or complete Flutter app
- [ ] Document active vs configured services

---

**End of Audit Report**
