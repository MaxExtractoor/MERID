# MERID Production Readiness Audit
**Date:** 2026-03-15  
**Scope:** Full codebase sweep — config/secrets, error handling, CI/CD, mode integrity, kill switch wiring, logging/tracing, deployment manifests, reconciliation, runbooks  
**Verdict:** Not yet prod-ready. Specific blocking issues below, each assigned a ticket ID.

---

## Summary Table

| Area | Status | Blocking? | Ticket(s) |
|---|---|---|---|
| Secrets / Config | ⚠️ Mostly good, 3 gaps | **YES** | PR-01, PR-02, PR-03 |
| Error handling | ⚠️ Systemic silent-swallow | **YES** | PR-04 |
| CI/CD pipeline | ⚠️ Lint is non-blocking, no SAST | YES | PR-05, PR-06 |
| Mode integrity | ✅ Well-structured | No | — |
| Kill switch wiring | ✅ Solid; minor gap | No | PR-07 |
| Logging / Tracing | ⚠️ Tracing hard-wired to localhost | No | PR-08 |
| Deployment manifests | ⚠️ `docker-compose.yml` is stale | YES | PR-09 |
| Reconciliation | ✅ Implemented; no alert wiring | No | PR-10 |
| Runbooks | ⚠️ `RUNBOOK.md` exists; gaps | No | PR-11 |

---

## 1. Config & Secrets

### ✅ What's good
- `merid/settings.py` uses **pydantic-settings** — all config is externalized via env vars with typed fields, safe defaults, and a `validate_for_go_live()` helper.
- `trading/trade_mode.py` has a canonical `TradeMode` singleton; `MERID_ALLOW_LIVE_TRADES` env-var gate is enforced before any `LIVE` transition.
- `MERID_PM_LIVE_ENABLED = False` default; `KALSHI_USE_DEMO = True` default — both must be explicitly flipped for live.
- `core/secrets_guard.py` has `scan_for_tracked_secrets()` + `check_live_mode_safe()` + content-pattern scanning for PEM/AWS/OAI keys.
- `.gitignore` covers `*.pem`, `*.key`, `.env`, `.env.*`.

### ❌ Gaps

**PR-01 — `NEO4J_PASSWORD` ships with default `"change_me"`**  
`merid/settings.py:45` — the default value is a non-empty string that will silently pass validation in prod.  
**Fix:** Change default to `None` and add it to `validate_required_for_production()`.

**PR-02 — `SECRET_KEY` (JWT) defaults to `None`; no startup assertion**  
`merid/settings.py:257` — `SECRET_KEY: Optional[str] = None`. If unset in prod, JWT signing will fail at runtime, not at startup.  
**Fix:** Add a startup check: raise `RuntimeError` (or log CRITICAL + refuse to bind) if `MERID_ENV == production` and `SECRET_KEY is None`.

**PR-03 — `docker-compose.yml` hard-codes default passwords in plaintext**  
`docker-compose.yml:73` — `POSTGRES_PASSWORD=${POSTGRES_PASSWORD:-kalshi_password}`  
`docker-compose.yml:92` — `redis-server --requirepass ${REDIS_PASSWORD:-redis_password}`  
`docker-compose.yml:150` — `GF_SECURITY_ADMIN_PASSWORD=${GRAFANA_PASSWORD:-admin}`  
These compose defaults will be used if the operator forgets to set the env var in prod.  
**Fix:** Remove the `:-fallback` defaults for all password vars in the prod compose file; require them explicitly.

**PR-03b — No vault / KMS integration**  
`check_live_mode_safe()` already warns when `VAULT_ADDR` / `AWS_SECRET_ACCESS_KEY` are absent, but there is no actual fetch path. For production with real money the `.env` file approach is acceptable short-term only.  
**Action (not blocking):** Document in `ENV_SETUP.md` that prod should inject secrets via a secrets manager (Railway secrets, AWS SSM, etc.), not a `.env` file on disk.

---

## 2. Error Handling

### ✅ What's good
- Critical execution paths (`trade_mode.py`, `execution_guard.py`, `kill_switches.py`) have explicit typed exceptions with context.
- Most API-layer `except Exception` blocks return an `_offline({...})` stub rather than 500ing.
- Previous bug scrub removed bare `except: pass` blocks; remaining ones emit `logger.debug`.

### ❌ Gaps

**PR-04 — ~600 `except Exception` swallows across 291 files with no error classification**  
The top offenders in production code paths:  

| File | Swallow count | Risk |
|---|---|---|
| `web/api/real_data_endpoints.py` | 37 | Returns `_offline()` silently — no metric/alert |
| `web/api/system_endpoints.py` | 26 | Silent degradation in health reporting |
| `web/api/kalshi_api.py` | 22 | Silent failures in order/market data paths |
| `web/api/missing_endpoints.py` | 23 | Stubs that may hide real failures |
| `web/main.py` | 13 | App-level silencing |

The pattern `except Exception: return {}` or `return _offline(...)` without incrementing a counter means:
- Prometheus/Grafana never sees the errors.
- Sentry/alerting never fires.
- The operator has no idea if the system is degraded.

**Fix (3 steps):**
1. Add a `_error_counter` Prometheus `Counter` (or equivalent) in `web/api/real_data_endpoints.py` that increments on every silent fallback, labeled by endpoint.
2. For `except Exception` blocks in *execution* paths (order routing, kill switch, reconciliation), re-raise or log at `ERROR` with full traceback and a structured `event` field.
3. For *data-fetch* `except Exception` blocks (consensus, agents, prices), log at `WARNING` with `exc_info=True` on first occurrence and suppress repeats using a `_error_logged` set keyed on exception type + endpoint.

---

## 3. CI/CD Pipeline

### ✅ What's good
- `ci.yml` triggers on `push` to `main`/`develop` and PRs to `main`.
- Jobs: swarm integrity gate → backend tests → hardening tests → frontend tests → security scan → lint → full test discovery.
- `nightly-soak.yml` runs at 04:00 UTC: audit trail soak, position reconciliation under load, swarm benchmark, full test suite.
- `fast_safety.yml` runs on PRs touching core/analytics/swarm with coverage enforcement (≥18%) and Kalshi kill switch gate.
- Security scan checks for tracked `.pem`/`.key` files and `.env.backup`.

### ❌ Gaps

**PR-05 — Lint is non-blocking (`--exit-zero`)**  
`ci.yml:262` — `ruff check . --select E9,F63,F7,F82 --exit-zero`  
Only syntax errors and fatal issues are checked, and the job exits 0 regardless.  
**Fix:** Remove `--exit-zero`. Add `--select ALL --ignore ...` with a curated ignore list, or at minimum enforce `E9,F63,F7,F82` as hard failures. Add `mypy --strict` (or `pyright`) on the `core/`, `trading/`, `merid/` packages.

**PR-06 — No SAST / dependency scanning in CI**  
`fast_safety.yml` and `ci.yml` do not run `bandit`, `safety`/`pip-audit`, or `semgrep`.  
**Fix:** Add a step to `ci.yml`:
```yaml
- name: SAST + dependency scan
  run: |
    pip install bandit pip-audit
    bandit -r core/ trading/ merid/ web/ -ll -x archive/,tests/ -f json -o reports/bandit.json || true
    pip-audit --format json -o reports/pip-audit.json
```
Wire `bandit` failures at HIGH severity as blocking; `pip-audit` CRITICAL CVEs as blocking.

**PR-06b — No staged rollout gate between develop → main → prod**  
PRs from `develop` to `main` are gated only by CI. There is no:
- Manual approval step for risk-sensitive changes (execution, kill switch, mode logic).
- Required PR checklist for production-readiness items.
- Canary/staging environment gate.

**Fix:** Add a GitHub required reviewer rule for PRs touching `execution/`, `trading/`, `merid/execution/`, `web/api/operator_*`, `core/kill_switches` — enforced via `CODEOWNERS` file. Add a PR template section:
```markdown
## Production Readiness Checklist (required for execution/risk/mode changes)
- [ ] Tests added or updated
- [ ] Rollback path documented
- [ ] Risk limits unchanged or explicitly reviewed
- [ ] Kill switch path verified
```

---

## 4. Mode Integrity (Sim / Paper / Live)

### ✅ Strong — no blocking issues
- `trading/trade_mode.py` is the single canonical source; all mode transitions go through `set_trade_mode()`.
- Transition guards: `MOCK → LIVE` blocked; `* → LIVE` requires `MERID_ALLOW_LIVE_TRADES=true` env var; `LIVE` additionally requires `check_execution_gate()` to pass.
- `merid/settings.py` has both `MERID_LIVE_TRADING_UNLOCKED` and `MERID_PM_LIVE_ENABLED` double-locks.
- `assert_not_live()` helper available for use in paper-only code paths.
- `KALSHI_USE_DEMO = True` is the safe default.
- `Dockerfile` sets `MERID_ENV=production` and `MERID_PROFILE=kalshi-only` — limits surface area.

### Minor gap (non-blocking)

**PR-07 — `config/settings.py` `ServerConfig.debug` defaults to `True` in dev**  
`config/settings.py:41` — `debug: bool = True`. This file is deprecated but still imported by ~15 legacy modules. In the deprecated shim, `debug=True` is the default.  
**Fix:** Change default to `False` in the shim to avoid accidental debug mode if the shim is imported in a prod context. The deprecation warning is already there.

---

## 5. Kill Switch Wiring

### ✅ Strong — no blocking issues
- Three-layer kill switch architecture: `RiskController` (global + domain), `ExecutionGuard` (CQI + caps), `RiskGuard` (OTP reset).
- `merid/risk/kill_switches.py` — `reset()` is thread-safe (inside `self._lock`).
- `merid/execution_guard.py` — 7-layer pre-trade check run on every order.
- Kill switch state is loaded at startup via singleton initialisation before any trading loop starts.
- `RUNBOOK.md` documents kill-switch policy and halt conditions.

### Minor gap

**PR-07 (continued) — `core/tracing.py` hard-wires Jaeger agent to `localhost:6831`**  
See Section 6 below.

---

## 6. Logging & Tracing

### ✅ What's good
- `utils/logger.py` is the single structured logger used consistently (previous audit enforced this across ~55 files).
- `core/tracing.py` implements `TraceContext` with `trace_id`, `span_id`, `correlation_id` and propagation headers.
- OpenTelemetry SDK + Jaeger exporter wired via `TracerProvider` with `BatchSpanProcessor`.
- LLM governance store traces all agent queries with `trace_id` + `role`.

### ❌ Gaps

**PR-08 — Jaeger agent hard-coded to `localhost:6831`**  
`core/tracing.py:64-67`:
```python
jaeger_exporter = JaegerExporter(
    agent_host_name="localhost",
    agent_port=6831,
)
```
This will silently fail (drop all spans) in any containerised or remote deployment where Jaeger is not on localhost.  
**Fix:** Read from env vars:
```python
JaegerExporter(
    agent_host_name=os.getenv("JAEGER_AGENT_HOST", "localhost"),
    agent_port=int(os.getenv("JAEGER_AGENT_PORT", "6831")),
)
```

**PR-08b — Trace attributes `mode`, `agent_id`, `venue`, `symbol` not enforced on spans**  
The `TraceContext` propagates `trace_id`/`span_id` but does not mandate the trading-specific fields. Log lines in execution paths lack a consistent set of structured fields.  
**Fix:** Add a `MeridSpanAttributes` dataclass:
```python
@dataclass
class MeridSpanAttributes:
    mode: str        # "paper" | "live" | "mock"
    agent_id: str
    venue: str
    symbol: str
    trace_id: str
```
Enforce via a `@instrument_trade(...)` decorator wrapping order submission.

---

## 7. Deployment Manifests

### ✅ What's good
- `Dockerfile` is a proper multi-stage build: builder → production stage, non-root user, `HEALTHCHECK` wired to `/api/v1/health`, `MERID_PROFILE=kalshi-only` baked in.
- `docker-compose.monitoring.yml` (separate) includes Prometheus + Grafana + AlertManager.
- `deploy/k8s/merid-deployment.yaml` exists.

### ❌ Gaps

**PR-09 — `docker-compose.yml` is stale / wrong context**  
`docker-compose.yml` references:
- `./api/Dockerfile` (context `./api`) — this path does not exist; the actual Dockerfile is at repo root.
- Streamlit dashboard service — MERID no longer uses Streamlit; React is the UI.
- `postgres`, `redis`, `nginx` with hardcoded default passwords (see PR-03).
- Port `8000` — the app runs on `8011`.

This file will fail immediately if used. It is likely the archived compose from before the Kalshi pivot.

**Fix:** Replace with a correct `docker-compose.prod.yml`:
```yaml
version: "3.9"
services:
  merid-api:
    image: merid-api:${IMAGE_TAG}   # no "latest" in prod
    ports: ["8011:8011"]
    env_file: .env.prod             # injected by CI, never committed
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8011/api/v1/health"]
      interval: 30s
      timeout: 10s
      retries: 3
    restart: unless-stopped
    mem_limit: 2g
    cpus: "1.5"
  merid-ui:
    image: merid-ui:${IMAGE_TAG}
    ports: ["3000:3000"]
    depends_on: [merid-api]
    restart: unless-stopped
```

**PR-09b — No resource limits in `deploy/k8s/merid-deployment.yaml`**  
Check if `resources.requests`/`limits` are set on the K8s deployment. Without them, a runaway agent loop can OOM the node.

---

## 8. Reconciliation

### ✅ Strong
- `trading/reconciliation.py` — `ReconciliationReport` with 6 checks (balance identity, trade count, win/loss sum, per-position PnL, cash non-negative, PnL finite). Background thread runs every 5 min.
- `merid/reconciliation/kalshi_reconciler.py` — venue-level reconciliation for Kalshi positions.
- `merid/reconciliation/venue_reconciler.py` — multi-venue reconciler.
- `deployment/reconciliation_system.py` — extended system.
- `scripts/run_reconciliation.py` — CLI runner.

### Gap (non-blocking)

**PR-10 — Reconciliation drift is logged but not alerted**  
The `ReconciliationReport` detects `DELTA` and `ERROR` statuses but there is no wiring to:
- Prometheus metric increment on drift.
- Alert rule in `monitoring/alert_rules.yml` for reconciliation failures.
- Telegram/Slack notification on ERROR status.

The existing alert system (`system_observability.py`) has 8 alert rules but none for reconciliation drift.

**Fix:** Add to `monitoring/system_observability.py`:
```python
class ReconciliationDriftAlert(AlertRule):
    name = "ReconciliationDrift"
    severity = "critical"
    # fire when ReconciliationReport.status == "ERROR"
```
Wire `run_reconciliation()` result into this alert on each periodic run.

---

## 9. Runbooks & SRE Hooks

### ✅ What exists
- `RUNBOOK.md` (repo root) — created in Sprint A. Covers kill-switch policy, halt conditions, pre-open/post-close checklists, category caps table, credential rotation steps.
- `ops/drills/3am_simulation.py` — 3am failure drill.
- `docs/KALSHI_GO_LIVE_CHECKLIST.md` — 6-section go-live checklist.
- `nightly-soak.yml` — automated overnight soak with GitHub Issue creation on failure.

### Gap (non-blocking)

**PR-11 — No per-service runbooks for non-Kalshi services**  
`RUNBOOK.md` covers Kalshi execution only. Missing:
- Orchestrator runbook (how to restart `merid/loop.py`, what to do if the swarm jams).
- Data feed runbook (staleness response, which feeds to check first).
- UI/API runbook (how to restart FastAPI, nginx, React build).
- Incident playbooks for: venue outage, data corruption, runaway agent, bad deploy.

**Fix:** Create `docs/runbooks/` with one `.md` per service. Minimum template:
```markdown
# [Service] Runbook
## Start / Stop / Restart
## Health Check
## Common Failure Modes
## Escalation Path
```

---

## Prioritised Ticket List

### 🔴 Blocking (must fix before live money)

| ID | File(s) | Title | Effort |
|---|---|---|---|
| **PR-01** | `merid/settings.py:45` | `NEO4J_PASSWORD` default `"change_me"` passes prod validation | 15 min |
| **PR-02** | `merid/settings.py:257`, `web/main.py` | Add startup assertion: `SECRET_KEY` must be set in prod | 30 min |
| **PR-03** | `docker-compose.yml:73,92,150` | Remove hardcoded password fallbacks from compose | 15 min |
| **PR-04** | `web/api/real_data_endpoints.py` + 290 files | Wire error counters to silent `except Exception` fallbacks | 2–4 h |
| **PR-05** | `.github/workflows/ci.yml:262` | Make ruff lint blocking; add mypy to CI | 1 h |
| **PR-06** | `.github/workflows/ci.yml` | Add `bandit` + `pip-audit` SAST step | 1 h |
| **PR-09** | `docker-compose.yml` | Replace stale compose with correct `docker-compose.prod.yml` | 1 h |

### 🟡 High (fix before sustained live operation)

| ID | File(s) | Title | Effort |
|---|---|---|---|
| **PR-06b** | `.github/` | Add `CODEOWNERS` + PR checklist for execution/risk/mode changes | 1 h |
| **PR-08** | `core/tracing.py:64` | Jaeger host/port from env vars, not hardcoded `localhost` | 15 min |
| **PR-08b** | `core/tracing.py` | Enforce `mode`, `agent_id`, `venue`, `symbol` on trade spans | 2 h |
| **PR-09b** | `deploy/k8s/merid-deployment.yaml` | Add `resources.requests/limits` to K8s deployment | 30 min |
| **PR-10** | `monitoring/system_observability.py` | Add `ReconciliationDriftAlert` + metric increment | 1 h |

### 🟢 Medium (operational quality)

| ID | File(s) | Title | Effort |
|---|---|---|---|
| **PR-07** | `config/settings.py:41` | Change deprecated `ServerConfig.debug` default to `False` | 5 min |
| **PR-11** | `docs/runbooks/` | Create per-service runbooks + incident playbooks | 4 h |
| **PR-03b** | `ENV_SETUP.md` | Document secrets-manager injection pattern for prod | 1 h |

---

## Quick Wins (< 1 hour total, do these first)

1. **PR-01**: `merid/settings.py:45` — `NEO4J_PASSWORD` default `None` + add to `validate_required_for_production`.
2. **PR-03**: `docker-compose.yml:73,92,150` — remove `:-kalshi_password`, `:-redis_password`, `:-admin` fallbacks.
3. **PR-07**: `config/settings.py:41` — `debug: bool = False`.
4. **PR-05**: `ci.yml:262` — remove `--exit-zero`.
5. **PR-08**: `core/tracing.py:64-67` — `os.getenv("JAEGER_AGENT_HOST", "localhost")`.
