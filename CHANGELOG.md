# MERID Changelog

Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/)

---

## [3.1.0] - 2026-02-21

### Kalshi Swarm Gap Closure + UI Audit

All 62 Kalshi swarm workflow gaps closed (A+ across all 6 categories).
UI sidebar restructured with 5 sources of truth fully synchronized.

### Added

- **TimeSeriesForecaster** — AR(2) autoregressive model, EWMA volatility, OU half-life, Hurst exponent (Sprint Q)
- **ExternalSentimentForecaster** — Pluggable news/X feed providers, MarketMoodBus, fear/greed contrarian (Sprint Q)
- **AuctionConsensusResolver** — Multi-round escalation bidding with calibration weights for CONFLICTED consensus (Sprint R)
- **MCPMarketFeed** — Async MCP server client with aiohttp/urllib fallback, env-configurable (Sprint R)
- **Positions view** — Deep-link to Portfolio positions tab via `initialTab` prop
- **Orders view** — Deep-link to Portfolio orders tab via `initialTab` prop
- **Calibration view** — Forecaster Brier scores, weight matrix, resolver accuracy (existing, now in sidebar)

### Changed

- **UI** — Expanded from 14 to 17 views across 5 sidebar sections
- **Sidebar** — Restructured to 5 sections: Live Trading (6), Swarm Intelligence (5), Analytics (2), Command Center (2), System (2)
- **sidebar_config.py** — Added `swarm-consensus`, `lane-control` views with endpoint contracts
- **sidebarManifest.ts** — Synced with backend sidebar config (was 3 sections, now 5)
- **Sidebar.tsx** — Added Positions/Orders items with TrendingUp/ClipboardList icons
- **constants.ts** — Added 11 endpoint constants (portfolio, orchestrator, trade-mode, reconciliation, audit-trail, UI sidebar)
- **ForecasterRegistry** — Now 6 forecasters (momentum, mean-reversion, macro, orderbook, time-series, sentiment)
- **Gap analysis** — 62/62 A+ (was 57/62 A)

### Fixed

- **TypeScript lint errors** — `positions`/`orders` not in `View` type union
- **Sidebar wiring test failures** — 23 failures → 0 (stale legacy expectations, missing types/routes/constants)
- **Endpoint path mismatch** — `/api/system/health` → `/api/v1/system/health` in sidebar config

---

## [3.0.0] - 2026-02-21

### Kalshi-Focused Platform Release

Complete pivot to Kalshi prediction markets as the single trading venue.

### Added

- **Frozen 14-View UI** — Canonical operator dashboard with 5 sidebar groups: Trading, Swarm Intelligence, Analytics, Operator, System
- **8-Step Operator Workflow** — DISCOVER → ANALYZE → CONSENSUS → SIZE → EXECUTE → MONITOR → PROMOTE → PROTECT
- **Kalshi Workflow Doc** — `docs/ui/kalshi_workflow.md` as the single source of truth for UI and workflow

### Changed

- **requirements.txt** — Stripped from 270 lines to ~88. Removed blockchain, ML/RL, multi-exchange, web scraping, social media, prompt management, workflow orchestration, market making, and sniping dependencies
- **UI Architecture** — Consolidated from 28+ views to 14 frozen views. Positions and Orders absorbed into KalshiPortfolioView
- **Sidebar** — Reorganized from flat list to 5 workflow-aligned groups
- **CommandPalette** — Updated to match new 14-view layout
- **Documentation** — Complete rewrite of README, QUICKSTART, BUILD, ENV_SETUP, CONTRIBUTING, GETTING_STARTED, API_REFERENCE, LOCAL_DEV, TESTING_GUIDE

### Removed

- **Legacy Views** — Wallet, Treasury, Betting, Mining, Institutional, standalone Positions/Orders moved to `_legacy/`
- **Orphan Components** — SentimentBacktestPanel, ThresholdOptimizerPanel moved to `_legacy/`
- **Orphan Hooks** — websocketWithBackoff moved to `_legacy/`
- **Legacy Dependencies** — web3, torch, stable-baselines3, ray, ccxt, py-clob-client, celery, neo4j, redis, tweepy, playwright, langchain, swarms, crewai, and ~180 other unused packages
- **Duplicate UI** — OrderGroupPanel removed from KalshiDashboardView and KalshiGridView (lives only in Portfolio)

---

## [2.1.0] - 2026-02-11

### Fixed

- **Dev Swarm Core** — Fixed `execute_task` lifecycle and exception handling
- **Credit Ledger** — Soft warning instead of hard rejection
- **API Routes** — Health check includes `checks` key; added `POST /config`

### Added

- **DevTaskTemplates** — 19 static template methods
- **Router Registration** — Metrics, market data, and WS routers wired

---

## [2.0.0] - 2026-02-09

### Added

- **Unified Trade Pipeline** — TradeProposal, TradeRouter, GlobalRiskManager, ModeManager, InstrumentRegistry
- **MeridLoop Orchestrator** — Persistent tick cycle: feeds → agents → consensus → risk → execution → CQI
- **RiskContext** — System stress bridge with `size_scale_factor` and `approval_threshold_boost`
- **ExecutionGuard** — Kill switch, CQI throttle, per-domain caps, venue exposure caps
- **Signal Layer** — Decay-aware features, arb scanner, drift detector
- **Canonical Agents** — Domain-based agents with trust-weighted consensus
- **React Dashboard** — Primary UI with operator views
- **Golden Path Tests** — 490 tests across 7 test files

### Changed

- **Agent Architecture** — Migrated from metaphor agents to domain-based agents
- **Risk Controls** — Per-venue ModeManager gating replaces global env var
- **API** — Migrated to `/api/v1/` prefix structure

---

## [1.0.0] - 2026-01-26

### Added

- Core logging infrastructure, system health controller, Windows compatibility
- Production operations framework, security pipeline, analytics foundation

---

## Version History

| Version | Date | Summary |
|---------|------|---------|
| 3.1.0 | 2026-02-21 | 62/62 gap closure, 17-view UI, sidebar sync, 6 forecasters |
| 3.0.0 | 2026-02-21 | Kalshi-focused platform, frozen 14-view UI, stripped dependencies |
| 2.1.0 | 2026-02-11 | Dev Swarm fixes, task templates |
| 2.0.0 | 2026-02-09 | Unified pipeline, MeridLoop, RiskContext, 490 tests |
| 1.0.0 | 2026-01-26 | Implementation audit complete |

---

## License

Proprietary — All rights reserved.
