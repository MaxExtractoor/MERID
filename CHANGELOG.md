# MERID Change Log

All notable changes to MERID will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.1.0] - 2026-02-11

### Fixed
- **Dev Swarm Core** — Fixed `execute_task` lifecycle: tasks now register in `active_tasks` before pipeline, use per-task `timeout_seconds`, and always append to `task_history` (including early-return paths)
- **Credit Ledger** — Changed from hard rejection to soft warning; daily cost limit is the real budget gate
- **Pipeline Exception Handling** — Outer try/except/finally in `execute_task` catches all pipeline exceptions and properly sets `failed` status
- **Shutdown** — Uses `asyncio.wait_for` pattern; `_wait_for_active_tasks()` no longer takes args
- **`cancel_task`** — Made async-compatible
- **`pause`/`resume`** — Now return `bool` indicating state change
- **Persistence** — `_task_to_dict`/`_dict_to_task` aligned with `DevTask` fields; fresh import for test patching
- **API Routes** — Health check includes `checks` key; added `POST /config`; shutdown returns `message`/`warning`; task endpoints search `active_tasks` and `task_history`

### Added
- **`DevTask.cost_usd`** field for per-task cost tracking
- **`DevTaskTemplates`** — 19 static template methods (RG-01–RG-11, structural, RRG-01–RRG-09)
- **Router Registration** — `metrics_router`, `market_data_router`, `market_ws_router`, `latency_timing_middleware` wired into `web/main.py`
- **Readiness Auditor Prerequisites** — `dev_swarm` marker in `pytest.ini`, `LEGACY_RISK_MATRIX.md`, `QUARANTINE_MARKERS` hook in conftest, Makefile targets (`dev-swarm-test`, `backend-test`, `frontend-build`, `swarm-metrics`)
- **`HISTORICAL_AUDIT_GAP_REPORT.md`** — RRG-01 through RRG-10 and UW items
- **`LEGACY_RISK_MATRIX.md`** — Quarantine lists, CI gate, coverage snapshot

### Tests
- `test_dev_swarm.py`: **393/393 passing** (was ~130 failures)
- `test_dev_swarm_xdist_invariants.py`: 17/17 passing
- Zero regressions across broader test suite

---

## [2.0.0] - 2026-02-09

### Added
- **Unified Trade Pipeline** (`merid/pipeline/`) — TradeProposal, TradeRouter, GlobalRiskManager (7-point check), ModeManager (per-venue SIM/PAPER/LIVE), InstrumentRegistry, AdapterRegistry, DomainAgents
- **MeridLoop Orchestrator** (`merid/loop.py`) — Persistent tick cycle: features → agents → consensus → arb → plans → CQI → reconciliation
- **RiskContext** (`merid/pipeline/risk_context.py`) — System-level stress bridge aggregating ExecutionGuard, GlobalRiskManager, DrawdownGovernor, OperatorSession; produces `size_scale_factor` and `approval_threshold_boost`
- **ExecutionGuard** (`merid/execution_guard.py`) — Kill switch, CQI-based throttling, per-domain caps
- **Prediction Markets** (`merid/prediction/`) — VenueGate, PredictionMarketModel, KalshiStrategy, PredictionMarketRisk, AlertManager (109 tests)
- **Signal Layer** (`merid/signals/`) — Decay-aware features, arb scanner, drift detector, CQI dashboard (98 tests)
- **Betting Module** (`merid/betting/`) — BettingStore (SQLite), OddsAPIClient, swarm consensus, plan executability, settlement tracking (77 tests)
- **Canonical Agents** (`merid/agents/`) — Domain-based agents with consensus coordination, trust-weighted voting (73 tests)
- **Blockchain Module** (`merid/blockchain/`) — On-chain data (Helius/TheGraph/Nansen), execution service, secrets management with RBAC, signing service, wallet service, smart contract interfaces, compliance registry, blockchain gateway (135 tests)
- **Operator Dashboard** — Real-time operator view with status bar, control plane, activity stream
- **React Dashboard** (`web/react/`) — 28 sidebar views: Operator, Wallet, Treasury, Trading, Positions, Predictions, Betting, Flow Radar, Signal Layer, Health, and more
- **Wallet & Treasury Views** — Promoted from stubs to live views backed by real API endpoints
- **E2E Golden Path** — 490 tests across 7 test files covering full pipeline
- **Readiness Score** — 74/74 (100%) across all 10 sections
- **Makefile Targets** — `serve`, `loop-start`, `loop-start-execute`, `golden-path`, `preflight`, `risk-context`

### Changed
- **Agent Architecture** — Migrated from "Brain/Heart/Immune" metaphor to domain-based agents (PredictionMarket, CryptoArb, Equity, Macro)
- **Risk Controls** — Replaced env-var-based `MERID_TRADING_MODE` with per-venue ModeManager gating
- **Frontend** — React dashboard is now primary UI (28 views); Flutter UI is legacy
- **API Endpoints** — Migrated from `/institutional/` prefix to `/api/v1/pipeline/`, `/api/v1/prediction-markets/`, `/api/v1/wallet/`, `/api/v1/treasury/`, etc.
- **Server Entry** — `web/main.py` is the primary FastAPI entry point (not `main.py`)
- **Test Suite** — Expanded from ~150 to 490 golden path tests
- **UI Audit** — Removed all "coming soon", "mock", "demo" text from live views; data-driven badges only

### Removed
- **Random/mock data** — Purged all `random` calls from `missing_endpoints.py`; all endpoints return static zeros or real data
- **Stale env vars** — `MERID_ENABLE_TRADING_SUITE`, `MERID_SPECTATOR_MODE`, `MERID_LIVE_TRADING_UNLOCKED` no longer exist
- **Legacy agent names** — "Brain", "Heart", "Immune", "Spine" metaphor replaced by domain agents

### Security
- **ComplianceRegistry** — Polymarket/Augur/PredictIt prohibited; OKX restricted; OFAC-sanctioned assets blocked
- **SecretsManager** — RBAC-gated key access with audit logging, rotation tracking, revocation
- **SigningService** — Agents never hold private keys; submit sign requests through policy-checked service

---

## [1.0.0] - 2026-01-26

### Added
- **Complete Implementation Audit** - All 8 implementation stages completed successfully
- **MERID Logging Patterns** - Production-ready QueueListener/QueueHandler backend with dictConfig integration
- **System Health Controller** - `meridctl status` command for comprehensive health snapshots
- **Windows Compatibility** - Proper file handle cleanup and permission handling
- **Environment-Driven Configuration** - `MERID_LOG_PATH` environment variable support
- **Standardized API** - Clean `start_merid_logging()` / `shutdown_merid_logging()` interface
- **Production Operations Framework** - 3am operability drills and governance scheduler
- **Security Pipeline** - SonarQube integration and GitHub Actions SAST workflows
- **Analytics Foundation** - Database schema, event capture, cohort analysis, identity resolution
- **Governance Framework** - Continuous governance with evidence trail and blocking enforcement
- **Reality Enforcement System** - Assertion registry, UI gates, blindness detection
- **Documentation Suite** - Complete technical documentation and operational runbooks

### Changed
- **Logging Backend** - Migrated from direct file handlers to QueueListener/QueueHandler pattern
- **Configuration Management** - Centralized logging configuration with environment support
- **Testing Infrastructure** - Comprehensive pytest integration with Windows compatibility

### Deprecated
- **Legacy Logging Patterns** - Old direct file handler patterns replaced with queue-based backend

### Security
- **SAST Pipeline** - Automated security scanning with SonarQube and GitHub Actions
- **Audit Logging** - Comprehensive audit trails for all system operations
- **Identity Resolution** - Secure cross-device identity merging with validation

### Performance
- **Multiprocessing Logging** - Optimized queue-based logging for high-performance scenarios
- **Database Optimization** - Indexed queries for cohort analysis and identity resolution
- **Resource Management** - Proper handler cleanup and resource management

---

## [0.9.0] - 2026-01-19

### Added
- **Initial Implementation** - Core MERID systems and governance framework
- **Analytics Foundation** - Basic event capture and cohort analysis
- **Security Integration** - Initial SAST pipeline setup

---

## [0.8.0] - 2026-01-12

### Added
- **Prototype Systems** - Initial MERID prototype implementations
- **Basic Governance** - Early governance engine and reality enforcement

---

## [0.7.0] - 2026-01-05

### Added
- **Research Phase** - Initial MERID research and design documentation

---

## [0.6.0] - 2025-12-29

### Added
- **Concept Phase** - Initial MERID concept and architecture design

---

## [0.5.0] - 2025-12-22

### Added
- **Planning Phase** - MERID project planning and requirements gathering

---

## [0.4.0] - 2025-12-15

### Added
- **Discovery Phase** - Initial MERID discovery and feasibility analysis

---

## [0.3.0] - 2025-12-08

### Added
- **Exploration Phase** - Early MERID exploration and proof of concepts

---

## [0.2.0] - 2025-12-01

### Added
- **Inception Phase** - MERID project inception and initial research

---

## [0.1.0] - 2025-11-24

### Added
- **Project Kickoff** - MERID project initialization and team formation

---

## [Unreleased]

### Added
- **Future Enhancements** - JSON structured logging, remote sink forwarding, profile-based configurations

### Planned
- **Enhanced Analytics** - Real-time dashboard updates and advanced visualization
- **Extended Security** - Penetration testing framework and vulnerability management
- **Performance Optimization** - Load testing and scalability improvements
- **Integration Testing** - Cross-system integration validation and compatibility testing

---

## Version History

- **2.0.0** - Unified Pipeline, MeridLoop, RiskContext, 490 tests (2026-02-09)
- **1.0.0** - Implementation Audit Complete (2026-01-26)
- **0.9.0** - Initial Implementation (2026-01-19)
- **0.8.0** - Prototype Systems (2026-01-12)
- **0.7.0** - Basic Governance (2026-01-05)
- **0.6.0** - Research Phase (2025-12-29)
- **0.5.0** - Planning Phase (2025-12-22)
- **0.4.0** - Concept Phase (2025-12-15)
- **0.3.0** - Discovery Phase (2025-12-08)
- **0.2.0** - Exploration Phase (2025-12-01)
- **0.1.0** - Inception Phase (2025-11-24)

---

## Release Notes

### Version 1.0.0 - Implementation Audit Complete

This release marks the completion of MERID's comprehensive implementation audit. All 8 implementation stages have been successfully completed and validated:

1. **Core Analytics Foundation** - Database schema, event capture, cohort analysis
2. **Advanced Analytics & Identity** - Cross-device resolution, security validation
3. **Governance Integration** - Weekly dossiers, investor pack integration
4. **Dashboard & UI Integration** - Analytics dashboard, event tracking
5. **Testing & Validation** - Comprehensive stress testing and validation
6. **Documentation & Training** - Complete documentation and operational runbooks
7. **Production Operations Gates** - Technical readiness, 3am operability
8. **Continuous Governance Framework** - Automated governance with evidence trail

#### Key Features
- **Production-Ready Logging** - QueueListener/QueueHandler backend with Windows compatibility
- **System Health Monitoring** - Comprehensive health snapshots with `meridctl status`
- **Institutional Readiness** - Complete governance controls and compliance framework
- **Security Pipeline** - Automated SAST scanning and vulnerability management
- **Analytics Foundation** - Cohort analysis and identity resolution with security validation

#### Breaking Changes
- **Logging Backend Migration** - Direct file handlers replaced with queue-based backend
- **Configuration Changes** - Centralized logging configuration with environment support

#### Migration Guide
- Update logging calls to use new `merid_logging_config` module
- Set `MERID_LOG_PATH` environment variable for production deployments
- Use `meridctl status` for system health monitoring

#### Security Improvements
- Enhanced SAST pipeline with SonarQube integration
- Comprehensive audit logging for all system operations
- Secure identity resolution with validation and rate limiting

#### Performance Improvements
- Optimized multiprocessing logging with QueueListener/QueueHandler
- Database indexing for improved query performance
- Resource management improvements with proper cleanup

---

## Support

For support, questions, or contributions, please refer to the MERID documentation or contact the development team.

---

## License

Proprietary — All rights reserved.
