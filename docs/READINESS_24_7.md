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
| O-03 | Alertmanager configured | 2 | `monitoring/alertmanager.yml` — 7 receivers (incl. telegram-critical), 9 routes, inhibit rules; `verify-alertmanager.py` validator |
| O-04 | Application metrics emitted | 2 | `core/dev_swarm_metrics.py`, `core/observability_manager.py`, `core/metrics_tracking.py` — Counter/Histogram/Gauge |
| O-05 | Dashboard for swarm health | 2 | `CodebaseHealth.tsx`, `OperatorDashboard.tsx` with 15 sections, all gap components wired to real APIs |
| O-06 | Dashboard for trading safety | 2 | `OperatorDashboard.tsx` with 15 sections (risk strips, domain controls, venue health, breach log); `core/merid_dashboard.py` Brier metrics |
| O-07 | Structured logging | 2 | structlog used throughout; `SyslogIdentifier=merid-dev-swarm` in systemd unit |
| O-08 | Distributed tracing | 2 | `core/tracing.py` OpenTelemetry + Jaeger; `CorrelationMiddleware` wired into FastAPI; `AgentTracer` for agent decisions |

**Section score: 15 / 16**

## 3. Risk & Safety Controls

| # | Item | Score | Evidence / Notes |
|---|------|-------|------------------|
| R-01 | Position / exposure limits in code | 2 | `core/automated_risk_controls.py` — RiskLimit with 7 control types, breach detection |
| R-02 | Circuit breakers for exchange errors | 2 | `TradingHaltManager.check_circuit_breakers()` auto-halts; `RiskControlCoordinator` wires breakers; 29 tests in `test_trading_halt.py` |
| R-03 | Kill switch tested | 2 | `TradingHaltManager.halt()` + `can_trade()` gate; `DomainControlPanel` UI kill switch; tested in `test_trading_halt.py` |
| R-04 | Price feed anomaly detection | 2 | `ops/anomaly_detection.py` 3-layer stack (IsolationForest, CUSUM, Page-Hinkley); wired to `TradingHaltManager` via `RiskControlCoordinator` |
| R-05 | Risk limit tests | 2 | `PortfolioRiskManager` with 7 limit types; tested in `test_risk_api_endpoints.py` (13 tests), `test_trading_halt.py` (29 tests) |
| R-06 | Governance gates enforced | 2 | `core/merid_governance.py`, `core/merid_governance_cadence.py` — multi-gate system with alerts |
| R-07 | Constitution / guardrails | 2 | `core/constitution_enforcer.py`, `policy/guardrails.yml` |
| R-08 | Drawdown / max-loss limits | 2 | `TradingHaltManager.check_drawdown()` + `check_daily_loss()` auto-halt; tested in `test_trading_halt.py` |

**Section score: 16 / 16**

## 4. Operations & Runbooks

| # | Item | Score | Evidence / Notes |
|---|------|-------|------------------|
| P-01 | Start / stop / deploy documented | 2 | `docs/OPERATOR_RUNBOOK.md`, `docs/SEASON1_OPERATOR_RUNBOOK.md`, `docs/launch_runbook_v1.md` |
| P-02 | Rollback procedure | 2 | `docs/runbooks/RB-OPS-001-rollback-procedure.md` — halt, revert, restart, verify, resume + backup restore |
| P-03 | Incident runbooks | 2 | `docs/runbooks/RB-RISK-001..003`, `ops/runbooks/` (5 runbooks: DB, governance, latency, security, service down) |
| P-04 | 3am drill tested | 2 | `ops/drills/3am_simulation.py`, drill reports with validation summaries |
| P-05 | On-call / escalation pattern | 2 | `docs/runbooks/RB-OPS-003-escalation-policy.md` — 4-tier escalation (T0 auto, T1 Telegram, T2 eng, T3 IC), severity matrix, verification checklist |
| P-06 | Post-incident review process | 2 | `docs/runbooks/RB-OPS-002-post-incident-review.md` — PIR template, timeline, meeting agenda, blameless rules |

**Section score: 12 / 12**

## 5. Infrastructure & Redundancy

| # | Item | Score | Evidence / Notes |
|---|------|-------|------------------|
| I-01 | Process restart automation | 2 | `deploy/merid-dev-swarm.service` — systemd with Restart=always, security hardening |
| I-02 | Docker / compose orchestration | 2 | `docker-compose.yml` + analytics, streaming, full-stack, logging variants |
| I-03 | Health / readiness probes | 2 | `/healthz` (liveness) + `/readyz` (readiness) endpoints in `web/main.py`; checks thread, loop, startup, aggregator |
| I-04 | Data persistence guarantees | 2 | Neo4j + Redis configured; `data/` dir verified at startup; backup API checked; paper trading state persisted to disk |
| I-05 | Audit trail / trade records | 2 | `core/audit_anchor.py` Merkle-tree anchoring; `core/explainability_storage.py`; hash chain integrity tested (1000 entries) |
| I-06 | Secrets management | 2 | `.gitignore` covers `.env*`, `*.pem`, `*.key`; `core/secrets_guard.py` pre-commit guard; git history verified clean (no secrets ever committed) |
| I-07 | TLS / network security | 2 | `infra/tls-config.yml` (API+Neo4j+Redis TLS), `infra/firewall-rules.yml` (network isolation), `infra/verify-tls.sh` verification script |
| I-08 | Backup / recovery for state | 2 | `ops/backup_restore.py` CLI (Neo4j, Redis, positions, config); `web/api/backup.py` API with schedules; paper trading persistence |

**Section score: 16 / 16**

---

## Summary

| Dimension | Score | Max | Pct |
|-----------|-------|-----|-----|
| Testing & Correctness | 16 | 16 | 100% |
| Observability & Alerts | 15 | 16 | 94% |
| Risk & Safety Controls | 16 | 16 | 100% |
| Operations & Runbooks | 12 | 12 | 100% |
| Infrastructure & Redundancy | 16 | 16 | 100% |
| **TOTAL** | **75** | **76** | **99%** |

**Readiness level: Production**

## Remaining Gap

1. **O-04 (implicit)**: Alertmanager live deployment verification requires a running Prometheus + Alertmanager stack. Config and validator are in place; final verification is an ops task during deployment.
