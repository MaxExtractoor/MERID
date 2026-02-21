# MERID Codebase Baseline

> Generated: 2026-02-06 | Auditor: Full Codebase Auditor (automated)
> Purpose: Establish a clean baseline of quality, risk, and coverage across ALL domains.
> Future drift auditors will enforce this baseline.
>
> **History Layer**: See [`HISTORICAL_AUDIT_GAP_REPORT.md`](HISTORICAL_AUDIT_GAP_REPORT.md) for
> legacy commitments, silent downgrades, and cross-audit reconciliation.
> Do **not** hand-edit old audit docs — append new commitments here or in the historical report.

---

## Executive Summary

### Top 5 Strongest Areas

1. **Dev Swarm Subsystem** — 128 tests, 93.52% coverage, strict ≥90% gate, self-auditing readiness loop, full API + dashboard.
2. **Hardening Module** — Small, focused (5 files), circuit breaker + watchdog + lockdown patterns, low complexity.
3. **FastAPI Route Layer** — 100+ route files in `web/api/`, comprehensive REST surface for all domains.
4. **Compliance Module** — Dedicated audit logger, transaction log, regulatory reports, data retention — correct architecture for regulated trading.
5. **Governance Framework** — Constitutional enforcement, model risk management, surveillance, multi-agent risk controls — deep governance stack.

### Top 5 Weakest Areas

1. **Security: Secrets in Git** — `kalshi_private_key.pem` and `.env.backup` are tracked in git history. `.gitignore` has only 5 entries. **CRITICAL**.
2. **Test Coverage: 177 Empty Test Files** — 32% of all test files (177/550) are 0-byte placeholders. Most domains outside Dev Swarm have near-zero effective coverage.
3. **Documentation Sprawl** — 323 root-level `.md` files, many duplicated/stale (e.g., 20+ UTF8 pattern docs, 10+ phase completion reports). No single source of truth.
4. **Trading Execution Engine** — `trading/execution.py` is 46KB (largest single file), likely a god class. Critical path with low test coverage.
5. **Core Module Sprawl** — 176 Python files in `core/`, many >15KB, mixing concerns (blockchain, social scraping, trading, governance in one package).

### Suggested Order of Attack

1. **Rotate all secrets** and remove `.env.backup` + `kalshi_private_key.pem` from git history.
2. **Expand `.gitignore`** to cover secrets, build artifacts, coverage files, IDE configs.
3. **Add tests for trading execution** — highest-criticality zero-coverage domain.
4. **Add tests for compliance/audit** — regulatory requirement, currently ~0% coverage.
5. **Refactor `core/` into sub-packages** — reduce 176-file flat package to logical groups.
6. **Archive stale root `.md` files** into `docs_archive/`.
7. **Delete 177 empty test files** or populate them with at least smoke tests.
8. **Add coverage gates** for trading (≥60%) and compliance (≥80%) domains.

---

## Domain Map

| # | Domain | Paths | Purpose | Criticality | Python Files | Test Files (non-empty) |
|---|--------|-------|---------|-------------|-------------|----------------------|
| 1 | **Core Engine** | `core/` | Central business logic: orchestration, state, events, health, caching, error handling, streaming, resilience | High | 176 | ~72 (in `tests/core/`) |
| 2 | **Dev Swarm** | `core/dev_swarm*.py`, `core/dev_swarm_readiness_auditor.py` | Autonomous dev agents, task execution, persistence, metrics, readiness auditor | High | 5 | 1 (128 tests) |
| 3 | **Agents** | `agents/` | Agent framework, prediction analysts, governors, watchdogs, streaming agents, swarm coordination | High | 71 | ~3 (in `tests/agents/`) |
| 4 | **Trading** | `trading/` | Execution engine, paper trading, adapters (Alpaca, Polymarket), mode controller, routing | Critical | 35 | ~108 (in `tests/trading/`) |
| 5 | **Data** | `data/` | Live price feeds, market data schemas, feed handlers, asset universe, US-compliant data sources | High | 18 | ~3 (in `tests/data/`) |
| 6 | **Web API** | `web/api/` | FastAPI routes: trading, agents, governance, compliance, dev swarm, predictions, paper trading, WebSocket | High | 124 | ~4 (in `tests/web/`) |
| 7 | **Web Frontend** | `web/react/src/` | React dashboard: views (35), components (59), hooks (31), services, types | Medium | N/A (TSX) | 0 (no React tests) |
| 8 | **Compliance** | `compliance/` | Audit logging, compliance management, regulatory reports, transaction log, data retention | Critical | 7 | ~1 (in `tests/compliance/`) |
| 9 | **Monitoring** | `monitoring/` | Prediction markets, metrics, health checker, regime classifier, news feeds, performance tracker | Medium | 24 | ~1 (in `tests/monitoring/`) |
| 10 | **Security** | `security/` | Secrets manager, breach detection, AGI safety rails, quantum-resistant keys, sybil detection | Critical | 17 | ~2 (in `tests/security/`) |
| 11 | **Governance** | `governance/` | Constitutional enforcement, model risk, surveillance, multi-agent risk controls, operational gates | High | 23 | ~1 (in `tests/governance/`) |
| 12 | **Hardening** | `hardening/` | Circuit breaker, chaos engineering, lockdown, watchdog | Medium | 5 | ~3 (in `tests/hardening/`) |
| 13 | **Infrastructure** | `infra/` | Deployment orchestrator, latency monitor, low-latency RPC, firewall/RBAC/TLS configs | Medium | 7 | 0 |
| 14 | **Merid App** | `merid/` | Event venues, execution layer, resilience, risk, settings, whale tracking | High | 38 | ~87 (in `tests/merid/`) |
| 15 | **Utils** | `utils/` | Logger, Brier score, UTF-8 logging patterns (28 variant files) | Low | 29 | ~3 (in `tests/utils/`) |
| 16 | **Scripts** | `scripts/` | CLI tools, coverage analysis, seeding, validation, swarm CLI, war games | Low | 59 | 0 |

---

## Per-Domain Coverage Estimates & Targets

| Domain | Current Coverage (est.) | Target | Gate Enforced? | Notes |
|--------|----------------------|--------|---------------|-------|
| Dev Swarm | **93.52%** | ≥90% | **Yes** (`--cov-fail-under=90`) | Gold standard. Self-auditing. |
| Trading Core | ~5-10% | ≥60% | No | `execution.py` (46KB) is largely untested. Critical path. |
| Compliance | ~0-5% | ≥80% | No | Regulatory requirement. `audit_logger.py` (14KB) untested. |
| Agents | ~5-10% | ≥50% | No | `prediction_arbitrage_analyst.py` (86KB) is the largest file in the repo. |
| Core Engine | ~7.5% | ≥40% | No | 176 files, massive surface area. Prioritize health, state, events. |
| Web API | ~5-10% | ≥50% | No | 124 route files. Only dev_swarm_routes tested well. |
| Security | ~0% | ≥70% | No | `breach_detection.py` (24KB) + `secrets_manager.py` (15KB) untested. |
| Governance | ~0-5% | ≥50% | No | Complex enforcement logic. `constitutional.py` (24KB) untested. |
| Data | ~5% | ≥40% | No | `live_price_feed.py` (22KB) is critical infrastructure. |
| Monitoring | ~5% | ≥30% | No | `prediction_markets.py` (52KB) is the second-largest file. |
| Merid App | ~15-20% | ≥40% | No | Best-tested domain after Dev Swarm (87 test files in `tests/merid/`). |
| Hardening | ~10% | ≥50% | No | Small module, high-value. `circuit_breaker.py` (10KB). |
| Infra | ~0% | ≥20% | No | Config-heavy, some IaC. Low priority for unit tests. |
| Frontend | ~0% | ≥30% | No | No React tests exist. 59 components, 31 hooks, 35 views. |
| Utils | ~0% | ≥20% | No | Mostly UTF-8 logging variants (28 files). Consolidation needed first. |
| Scripts | N/A | N/A | No | Utility scripts, not gated. |

### Restored Module Tracking (from Silent Downgrade Resolutions)

> These modules were previously tracked at 95% targets in `TEST_COVERAGE_PLAN.md` but
> silently dropped from the baseline. Per `HISTORICAL_AUDIT_GAP_REPORT.md` Part 10,
> they are now restored with revised, realistic targets.

| Module | Domain | Old Target | Official Target | Rationale |
|--------|--------|-----------|----------------|-----------|
| `merid/event_venues/kalshi/client.py` | Merid App | 95% | **75%** | Critical trading gateway; 95% aspirational |
| `merid/event_venues/polymarket/client.py` | Merid App | 95% | **75%** | Critical trading gateway; 95% aspirational |
| `core/persistence_manager.py` | Core Engine | 95% | **70%** | State infrastructure; 95% aspirational |
| `core/state.py` | Core Engine | 95% | **70%** | Critical state management |
| `core/error_handling.py` | Core Engine | 95% | **60%** | Complex decorator patterns |

---

## Legacy Risk Zones

### LRZ-1: Async IOCP Hangs (Windows)

- **Files**: `tests/core/test_connection_pool.py`, `tests/core/test_health_monitor.py`, `tests/streaming/test_stream_bus.py`, `tests/consensus/test_consensus_coordinator.py`
- **Reason**: `GetQueuedCompletionStatus` hangs on Windows due to asyncio event loop issues.
- **Status**: Quarantined via `iocp_hang` marker + `conftest.py` auto-deselect hook.
- **Gating**: Non-gating (auto-skipped on Windows).

### LRZ-2: Redis-Dependent Tests

- **Files**: `tests/core/test_redis_events.py`, various integration tests
- **Reason**: Require running Redis instance. Fail in CI without Redis service.
- **Status**: Known failures, not quarantined.
- **Gating**: Non-gating (pre-existing).

### LRZ-3: Contract/Audit Logger Tests

- **Files**: `tests/contracts/`, `tests/compliance/`
- **Reason**: Depend on database state, external services, or complex setup.
- **Status**: Mostly empty test files (0-byte placeholders).
- **Gating**: Non-gating.

### LRZ-4: Secrets in Git History

- **Files**: `kalshi_private_key.pem`, `.env.backup`
- **Reason**: Tracked in git. `.env.backup` contains API keys/secrets. Private key file at repo root.
- **Status**: **ACTIVE RISK**. Must be remediated immediately.
- **Gating**: N/A — security issue, not a test issue.

### LRZ-5: God Classes / Giant Files

- **Files**: `agents/prediction_arbitrage_analyst.py` (86KB), `trading/execution.py` (46KB), `monitoring/prediction_markets.py` (52KB), `web/api/institutional.py` (86KB)
- **Reason**: Files >40KB are extremely difficult to test, review, and maintain.
- **Status**: Consciously accepted tech debt. Refactoring is a future priority.
- **Gating**: Non-gating.

### LRZ-6: Empty Test File Sprawl

- **Files**: 177 files across `tests/` with 0 bytes
- **Reason**: Created as placeholders but never populated. Create false sense of coverage.
- **Status**: Consciously accepted. Should be either populated or deleted.
- **Gating**: Non-gating.

### LRZ-7: Documentation Sprawl

- **Files**: 323 root-level `.md` files
- **Reason**: Accumulated over multiple phases/sprints without cleanup. Many are duplicates or stale.
- **Status**: Consciously accepted. Archival recommended.
- **Gating**: Non-gating.

### LRZ-8: Minimal .gitignore

- **File**: `.gitignore` (6 lines)
- **Reason**: Missing entries for `.env.backup`, `*.pem`, `*.key`, `coverage.*`, `htmlcov/`, `*.db`, `node_modules/`, `build/`, `dist/`, IDE configs.
- **Status**: **ACTIVE RISK**. Sensitive files may be committed accidentally.
- **Gating**: N/A.

---

## Risk & Gap Matrix

| ID | Domain | Type | Severity | Summary | Suggested Fix |
|----|--------|------|----------|---------|---------------|
| RG-01 | Security | security | **critical** | `kalshi_private_key.pem` tracked in git | Rotate key, remove from history with `git filter-repo`, add `*.pem` to `.gitignore` |
| RG-02 | Security | security | **critical** | `.env.backup` (18KB of secrets) tracked in git | Rotate all exposed credentials, remove from history, add `.env*` pattern to `.gitignore` |
| RG-03 | Security | security | **high** | `.gitignore` has only 5 entries | Expand to cover secrets, build artifacts, coverage files, IDE configs, `*.db`, `node_modules/` |
| RG-04 | Trading | coverage | **critical** | `trading/execution.py` (46KB) — near-zero test coverage on critical execution path | Add unit tests for order routing, position management, risk checks |
| RG-05 | Compliance | coverage | **critical** | `compliance/audit_logger.py` (14KB) — untested audit trail | Add tests for audit log integrity, retention, regulatory report generation |
| RG-06 | Agents | coverage | **high** | `agents/prediction_arbitrage_analyst.py` (86KB) — largest file, minimal tests | Break into sub-modules, add focused tests for signal generation and risk logic |
| RG-07 | Security | coverage | **high** | `security/breach_detection.py` (24KB) — zero tests | Add tests for breach detection logic, alert thresholds, false positive handling |
| RG-08 | Governance | coverage | **high** | `governance/constitutional.py` (24KB) — zero tests | Add tests for constitutional enforcement rules, veto logic, override paths |
| RG-09 | Core | arch | **high** | `core/` has 176 files in a flat package | Refactor into sub-packages: `core/blockchain/`, `core/social/`, `core/trading/`, `core/governance/` |
| RG-10 | Web API | coverage | **high** | 124 route files, only `dev_swarm_routes.py` well-tested | Add smoke tests for top 20 critical endpoints (health, trading, compliance, agents) |
| RG-11 | Tests | coverage | **high** | 177 empty test files (0-byte placeholders) | Delete or populate with at least one smoke test each |
| RG-12 | Frontend | coverage | **high** | Zero React tests for 59 components, 31 hooks, 35 views | Add Vitest/RTL tests for critical components (trading, governance, dev swarm) |
| RG-13 | Data | coverage | **medium** | `data/live_price_feed.py` (22KB) — critical infra, low coverage | Add tests for feed initialization, reconnection, error handling |
| RG-14 | Monitoring | arch | **medium** | `monitoring/prediction_markets.py` (52KB) — god class | Break into sub-modules: market sources, scoring, analytics |
| RG-15 | Docs | arch | **medium** | 323 root-level `.md` files, many stale/duplicated | Archive into `docs_archive/`, keep ≤20 active root docs |
| RG-16 | Utils | arch | **low** | 28 UTF-8 logging variant files in `utils/` | Consolidate to 1-2 canonical files, delete variants |
| RG-17 | Core | arch | **medium** | `web/api/institutional.py` (86KB) — god route file | Break into sub-routers: orders, portfolio, analytics, compliance |
| RG-18 | Infra | coverage | **low** | Zero tests for infrastructure code | Add basic tests for deployment orchestrator, latency monitor |
| RG-19 | Hardening | coverage | **medium** | `hardening/circuit_breaker.py` (10KB) — low coverage | Add tests for trip/reset/half-open state transitions |
| RG-20 | Core | coverage | **medium** | `core/health_monitor.py` (18KB) — quarantined due to IOCP | Fix async test isolation or add sync-only unit tests |

---

## Consciously Accepted Issues

These are known tech debt items that are tolerated for now with documented reasoning:

1. **Overall backend coverage ~7.5%** — Too large to fix in one pass. Domain-by-domain improvement via Dev Swarm tasks.
2. **IOCP async hangs on Windows** — Quarantined. Will be fixed when moving to Linux CI or fixing event loop handling.
3. **God classes (4 files >40KB)** — Refactoring is high-effort. Will be addressed incrementally.
4. **Empty test files (177)** — Placeholders from sprint planning. Will be populated or deleted domain-by-domain.
5. **Root doc sprawl (323 .md files)** — Historical artifacts. Archival is low-priority compared to code quality.
6. **Frontend zero tests** — React dashboard is supplementary to API. Will add tests when frontend stabilizes.

---

## CI Gates (Current)

| Gate | Threshold | Enforced? | Command |
|------|-----------|-----------|---------|
| Dev Swarm Domain | ≥90% | **Yes** | `make dev-swarm-test` |
| Dev Swarm Readiness | 15/15 checks | **Yes** | `make readiness-audit` |
| Backend Full | None | No | `make backend-test` |
| Frontend Build | Compiles | No | `make frontend-build` |
| Frontend Lint | No errors | No | `make frontend-lint` |

### Recommended New Gates

| Gate | Threshold | Priority |
|------|-----------|----------|
| Trading Domain | ≥60% | High |
| Compliance Domain | ≥80% | High |
| Security Domain | ≥70% | High |
| Agents Domain | ≥50% | Medium |
| Core Domain | ≥40% | Medium |

---

## Recommended DevTasks (Ordered)

1. **[CRITICAL] Rotate secrets and purge from git history** — `kalshi_private_key.pem`, `.env.backup`. Use `git filter-repo`. Rotate all exposed API keys.
2. **[CRITICAL] Expand .gitignore** — Add patterns for `*.pem`, `*.key`, `.env*`, `!.env.example`, `coverage.*`, `htmlcov/`, `*.db`, `node_modules/`, `build/`, `dist/`, `.idea/`, `.vscode/`.
3. **[CRITICAL] Add trading execution tests** — Target `trading/execution.py`, `trading/execution_engine.py`, `trading/paper_trading.py`. Goal: ≥60% coverage.
4. **[CRITICAL] Add compliance audit tests** — Target `compliance/audit_logger.py`, `compliance/compliance_manager.py`, `compliance/transaction_log.py`. Goal: ≥80% coverage.
5. **[HIGH] Add security domain tests** — Target `security/breach_detection.py`, `security/secrets_manager.py`. Goal: ≥70% coverage.
6. **[HIGH] Add governance domain tests** — Target `governance/constitutional.py`, `governance/model_risk.py`. Goal: ≥50% coverage.
7. **[HIGH] Add Web API smoke tests** — Test top 20 critical endpoints with FastAPI TestClient.
8. **[HIGH] Clean up empty test files** — Delete 177 zero-byte test files or populate with smoke tests.
9. **[MEDIUM] Refactor core/ into sub-packages** — Group 176 files into `core/blockchain/`, `core/social/`, `core/trading/`, `core/governance/`, `core/infra/`.
10. **[MEDIUM] Break up god classes** — `prediction_arbitrage_analyst.py` (86KB), `execution.py` (46KB), `prediction_markets.py` (52KB), `institutional.py` (86KB).
11. **[MEDIUM] Add data feed tests** — Target `data/live_price_feed.py`, `data/feed_handlers.py`. Goal: ≥40% coverage.
12. **[MEDIUM] Add React frontend tests** — Set up Vitest + RTL, add tests for critical views and hooks.
13. **[MEDIUM] Archive stale docs** — Move 300+ root `.md` files to `docs_archive/`, keep ≤20 active.
14. **[LOW] Consolidate UTF-8 utils** — Reduce 28 variant files in `utils/` to 1-2 canonical implementations.
15. **[LOW] Add infra tests** — Basic tests for `infra/deployment_orchestrator.py`, `infra/latency_monitor.py`.
