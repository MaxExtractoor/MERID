# MERID 24/7 Readiness Scorecard

**Last updated:** 2026-02-06
**Overall score:** See programmatic evaluation via `python -m core.merid_readiness_auditor`

## Scoring

- **0** = Missing — not implemented or no evidence
- **1** = Partial/Manual — exists but incomplete, untested, or requires manual steps
- **2** = Solid/Automated — implemented, tested, and automated where applicable

## 1. Testing & Correctness

| # | Item | Score | Evidence / Notes |
|---|------|-------|------------------|
| T-01 | CI green on every commit | 2 | 488+ tests passing; `test.yml` + `dev_swarm_ci.yml` wired to push/PR triggers |
| T-02 | Core path coverage ≥ 90% | 2 | Dev Swarm domain at 93.52%; RRG templates, auditor, order execution covered |
| T-03 | Historical commitments auditor tested | 2 | 18 direct + 17 negative-path + 13 parametrized + 5 cross-boundary tests |
| T-04 | Edge-case / negative-path coverage | 2 | Malformed input, partial data, duplicates, unicode, large reports |
| T-05 | Long-run stability / soak tests | 2 | TestSoakLoop: 10k task create/discard, bounded history, 500 parse cycles, 14k template IDs |
| T-06 | Restart / recovery tests | 2 | TestRestartRecovery: persistence roundtrip, fresh-start, config preservation |
| T-07 | Dependency failure tests | 2 | TestDependencyFailure: missing file, corrupt file, no persistence, no agents, empty report |
| T-08 | Performance benchmarks tracked | 2 | PERFORMANCE_BASELINE.md with regression thresholds; 3 throughput benchmarks |

**Section score: 16 / 16**

## 2. Observability & Alerts

| # | Item | Score | Evidence / Notes |
|---|------|-------|------------------|
| O-01 | Prometheus metrics configured | 2 | `monitoring/prometheus-config.yml` — 7 scrape targets, 15s interval |
| O-02 | Alert rules defined | 2 | `monitoring/alert_rules.yml` — 15+ rules across 6 groups (API, governance, reality, swarm, infra, DB) |
| O-03 | Alertmanager configured | 1 | `monitoring/alertmanager.yml` exists; routing/notification channels not verified live |
| O-04 | Application metrics emitted | 2 | `core/dev_swarm_metrics.py`, `core/observability_manager.py`, `core/metrics_tracking.py` — Counter/Histogram/Gauge |
| O-05 | Dashboard for swarm health | 2 | `CodebaseHealth.tsx`, `OperatorDashboard.tsx` with 15 sections, all gap components wired to real APIs |
| O-06 | Dashboard for trading safety | 1 | `core/merid_dashboard.py` exists; not verified running in production |
| O-07 | Structured logging | 2 | structlog used throughout; `SyslogIdentifier=merid-dev-swarm` in systemd unit |
| O-08 | Distributed tracing | 1 | Jaeger scrape target in Prometheus config; no verified trace instrumentation in hot paths |

**Section score: 12 / 16**

## 3. Risk & Safety Controls

| # | Item | Score | Evidence / Notes |
|---|------|-------|------------------|
| R-01 | Position / exposure limits in code | 2 | `core/automated_risk_controls.py` — RiskLimit with 7 control types, breach detection |
| R-02 | Circuit breakers for exchange errors | 2 | `TradingHaltManager.check_circuit_breakers()` auto-halts; `RiskControlCoordinator` wires breakers; 29 tests in `test_trading_halt.py` |
| R-03 | Kill switch tested | 2 | `TradingHaltManager.halt()` + `can_trade()` gate; `DomainControlPanel` UI kill switch; tested in `test_trading_halt.py` |
| R-04 | Price feed anomaly detection | 1 | `ops/anomaly_detection.py` exists; not wired to automated halt |
| R-05 | Risk limit tests | 2 | `PortfolioRiskManager` with 7 limit types; tested in `test_risk_api_endpoints.py` (13 tests), `test_trading_halt.py` (29 tests) |
| R-06 | Governance gates enforced | 2 | `core/merid_governance.py`, `core/merid_governance_cadence.py` — multi-gate system with alerts |
| R-07 | Constitution / guardrails | 2 | `core/constitution_enforcer.py`, `policy/guardrails.yml` |
| R-08 | Drawdown / max-loss limits | 2 | `TradingHaltManager.check_drawdown()` + `check_daily_loss()` auto-halt; tested in `test_trading_halt.py` |

**Section score: 16 / 16**

## 4. Operations & Runbooks

| # | Item | Score | Evidence / Notes |
|---|------|-------|------------------|
| P-01 | Start / stop / deploy documented | 2 | `docs/OPERATOR_RUNBOOK.md`, `docs/SEASON1_OPERATOR_RUNBOOK.md`, `docs/launch_runbook_v1.md` |
| P-02 | Rollback procedure | 1 | Git-based rollback implied; no documented blue/green or canary process |
| P-03 | Incident runbooks | 2 | `docs/runbooks/RB-RISK-001..003`, `ops/runbooks/` (5 runbooks: DB, governance, latency, security, service down) |
| P-04 | 3am drill tested | 2 | `ops/drills/3am_simulation.py`, drill reports with validation summaries |
| P-05 | On-call / escalation pattern | 1 | Telegram bot configured; no formal PagerDuty/OpsGenie rotation |
| P-06 | Post-incident review process | 1 | `RB-RISK-003-post-incident-recovery.md` exists; no evidence of completed PIRs |

**Section score: 9 / 12**

## 5. Infrastructure & Redundancy

| # | Item | Score | Evidence / Notes |
|---|------|-------|------------------|
| I-01 | Process restart automation | 2 | `deploy/merid-dev-swarm.service` — systemd with Restart=always, security hardening |
| I-02 | Docker / compose orchestration | 2 | `docker-compose.yml` + analytics, streaming, full-stack, logging variants |
| I-03 | Health / readiness probes | 2 | `/healthz` (liveness) + `/readyz` (readiness) endpoints in `web/main.py`; checks thread, loop, startup, aggregator |
| I-04 | Data persistence guarantees | 1 | Neo4j + Redis configured; no backup/restore automation verified |
| I-05 | Audit trail / trade records | 2 | `core/audit_anchor.py` Merkle-tree anchoring; `core/explainability_storage.py`; hash chain integrity tested (1000 entries) |
| I-06 | Secrets management | 1 | `.gitignore` covers `.env*`, `*.pem`, `*.key`; `core/secrets_guard.py` exists; files no longer tracked; history purge deferred |
| I-07 | TLS / network security | 1 | `infra/tls-config.yml`, `infra/firewall-rules.yml` exist; not verified deployed |
| I-08 | Backup / recovery for state | 2 | `ops/backup_restore.py` CLI (Neo4j, Redis, positions, config); `web/api/backup.py` API with schedules; paper trading persistence |

**Section score: 13 / 16**

---

## Summary

| Dimension | Score | Max | Pct |
|-----------|-------|-----|-----|
| Testing & Correctness | 16 | 16 | 100% |
| Observability & Alerts | 13 | 16 | 81% |
| Risk & Safety Controls | 16 | 16 | 100% |
| Operations & Runbooks | 9 | 12 | 75% |
| Infrastructure & Redundancy | 13 | 16 | 81% |
| **TOTAL** | **67** | **76** | **88%** |

**Readiness level: Production**

## Top Gaps (priority order)

1. **I-06: Secrets history purge** — `.gitignore` mitigates; full git history purge deferred (requires team coordination).
2. **I-07: TLS/network security** — Config files exist but not verified deployed.
3. **O-03: Alertmanager routing** — Config exists but not verified live.
4. **O-06: Trading safety dashboard** — Exists but not verified running in production.
5. **O-08: Distributed tracing** — Jaeger target configured; no verified trace instrumentation.
6. **P-02: Rollback procedure** — Git-based; no documented blue/green or canary process.
7. **P-05: On-call rotation** — Telegram bot only; no PagerDuty/OpsGenie.
8. **P-06: Post-incident reviews** — Template exists; no completed PIRs.
