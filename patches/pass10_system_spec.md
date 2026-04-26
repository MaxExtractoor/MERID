# Pass 10: Integration + UX/Ops Sweep - System Spec

## Overview

Pass 10 is the **integration + UX/Ops sweep** that confirms the entire MERID + Kalshi architecture behaves as designed after Passes 1–9, and that humans and tooling around it can't accidentally subvert the safety model.

**Assumptions:**
- Passes 1–9 have identified and patched P0 issues
- Single canonical executor (`order_router.route_order_async()`) is implemented
- Unified risk model: ~2% global cap, rejection of unsafe configs, max 3 edges
- Endpoint guards for FIX, REST fallback, CT API, and archive imports are live
- Startup-time enforcement (`enforce_at_startup()`) is wired
- Pass 9 structural tests are fixed with proper `TestClient` wiring

**Goals:**
1. Verify codebase, tests, and CI rules collectively enforce intended architecture
2. Audit upstream (UI/UX, CLI, config flows) and downstream (logs, metrics, alerts, runbooks)
3. Produce single, opinionated architecture + operations spec and GO/NO-GO matrix

---

## 10.A – Architecture Consolidation

### 10.A.1 Execution Topology

**Task:** Enumerate all entry points where trade intent can be generated and prove no bypass exists in LIVE/PAPER.

**Entry Points to Audit:**
| Entry Point | Path to Executor | Bypass Risk? | Status |
|-------------|------------------|--------------|--------|
| Web API `/orders` | `order_router.route_order_async()` | REST fallback guarded (503) | ✅ |
| Web API `/fix/orders` | Direct FIX client (GUARDED) | Returns 403 in LIVE/PAPER | ✅ |
| Agent grid signals | `route_order_async()` via consensus | No direct client access | ✅ |
| CLI tools | Must use canonical API | To be verified | ⬜ |
| Scheduled jobs | Must use canonical API | To be verified | ⬜ |
| CT API `/continuous-trader/*` | Module guard blocks LIVE/PAPER | Returns 403 | ✅ |

**Verification Steps:**
1. Grep all files for `KalshiRestClient`, `KalshiFIXClient`, `create_order`
2. Confirm none called directly in web/API layers (only via `order_router`)
3. Verify `archive/` import guard prevents live trading influence
4. Confirm CT path is disabled or fully routed through executor

### 10.A.2 Risk Model Enforcement

**Source of Truth:**
| Component | Location | Enforcement Point |
|-----------|----------|-------------------|
| Bankroll | `merid/config/unified_risk_enforcement.py` | `enforce_at_startup()` |
| 2% Global Cap | `ABSOLUTE_MAX_CYCLE_RISK_PCT = 0.02` | Config clamp + startup reject |
| Max 3 Edges | `ABSOLUTE_MAX_EDGES_PER_CYCLE = 3` | `enforce_unified_risk_model()` |
| Fixed USD Ban | Live/PAPER rejection | `enforce_at_startup()` raises |

**Verification Steps:**
1. Confirm 6% config raises `RiskConfigViolationError` at startup
2. Verify fixed USD ($5000) rejected in LIVE with clear error
3. Check edge-count enforcement in `top3_batch_manager.py` or equivalent
4. Document where per-trade 1% cap is applied

### 10.A.3 Guards and Invariants

**Critical Guards Inventory:**

| Guard | Location | Behavior | Test Coverage | CI Coverage |
|-------|----------|----------|---------------|-------------|
| FIX Endpoint Guard | `web/api/kalshi_api.py:~5970` | 403 + "use canonical" in LIVE/PAPER | `test_pass9_scenarios.py` | ⬜ |
| REST Fallback Guard | `web/api/kalshi_api.py:~2890` | 503 + kill-switch in LIVE/PAPER | `test_pass9_scenarios.py` | ⬜ |
| CT API Module Guard | `web/api/kalshi_continuous_trader_api.py` | HTTPException on import in LIVE/PAPER | `test_pass9_scenarios.py` | ⬜ |
| Archive Import Guard | `archive/__init__.py` | ImportError in trading processes | `test_archive_import_guard.py` | ✅ |
| Startup Risk Enforcement | `web/main.py:~2164` | `enforce_at_startup()` aborts on violation | `test_unified_risk_enforcement.py` | ⬜ |

**Deliverable:** Complete the "CI Coverage" column and identify gaps.

### 10.A.4 CI and Regression Protection

**Inspect `scripts/ci/check_kalshi_invariants.py`:**

| Invariant | Check Implementation | Status |
|-----------|---------------------|--------|
| No direct Kalshi client usage | `check_direct_kalshi_clients()` | ✅ |
| No archive imports in production | `check_archive_imports()` | ✅ |
| No raw HTTP calls to Kalshi | `check_raw_http_calls()` | ✅ |
| Archive guard present | `check_archive_guard_present()` | ✅ |

**Gaps to Address:**
- [ ] Add check for FIX endpoint guard presence
- [ ] Add check for REST fallback fail-closed logic
- [ ] Add check for CT API module guard
- [ ] Add check for startup enforcement wiring

---

## 10.B – UI/UX Upstream Sweep

### 10.B.1 Mode Clarity (SIM / PAPER / LIVE)

**Audit Checklist:**

| Surface | Current Mode Display | Risk of Confusion | Recommendation |
|---------|---------------------|-------------------|----------------|
| Web Dashboard | ⬜ To audit | ⬜ | ⬜ |
| CLI Output | ⬜ To audit | ⬜ | ⬜ |
| Log Headers | ⬜ To audit | ⬜ | ⬜ |
| Config Files | ⬜ To audit | ⬜ | ⬜ |

**Key Questions:**
1. Is current mode displayed prominently in all UIs?
2. Is there color-coding (green=SIM, yellow=PAPER, red=LIVE)?
3. Are there confirmation dialogs for mode switches to LIVE?
4. Can an operator easily tell which mode they're in at a glance?

### 10.B.2 Risk Settings Interaction

**Audit Checklist:**

| Setting Location | 2% Cap Visible? | 3-Edge Rule Visible? | Unsafe Config Handling | Recommendation |
|------------------|-----------------|----------------------|------------------------|----------------|
| Web Risk Panel | ⬜ | ⬜ | ⬜ | ⬜ |
| CLI Config Tool | ⬜ | ⬜ | ⬜ | ⬜ |
| Config Files | ⬜ | ⬜ | ⬜ | ⬜ |

**Key Questions:**
1. Does UI explain global 2% cap and 3-edge rule?
2. Does it show current enforced values and source of truth?
3. What happens if user tries to set 6% global or fixed USD?
   - Immediate validation and rejection?
   - Or silent accept + startup failure?
4. Are there warnings before accepting risky configs?

### 10.B.3 Error and Guard Feedback

**Guard Trip Messages Audit:**

| Guard | Current Error Message | Clarity | Actionable? | Recommendation |
|-------|----------------------|---------|-------------|----------------|
| FIX 403 | "FIX protocol disabled in {mode} mode. Use /api/v1/kalshi/orders..." | ✅ | ✅ | - |
| REST 503 | "Trading system degraded. Order router unavailable..." | ✅ | ✅ | - |
| CT API 403 | "Continuous Trader API disabled..." | ✅ | ✅ | - |
| Archive Import | "Archive module imports are BLOCKED in trading processes..." | ✅ | ✅ | - |
| Config Violation | "Risk config violation: {details}" | ⬜ | ⬜ | ⬜ |

**Deliverable:** Table with recommended messaging improvements.

---

## 10.C – Downstream Observability & Ops

### 10.C.1 Logging

**Guard/Fail Logging Audit:**

| Event | Log Location | Level | Context Fields | Status |
|-------|--------------|-------|----------------|--------|
| FIX endpoint blocked | `web/api/kalshi_api.py` | ERROR | mode, ticker, side, qty | ✅ |
| REST fallback 503 | `web/api/kalshi_api.py` | ERROR | mode, error | ✅ |
| Kill-switch triggered | `merid/risk/kill_switches.py` | CRITICAL | reason, severity, source | ⬜ |
| Archive import blocked | `archive/__init__.py` | ERROR | env, process_type | ✅ |
| Config violation | `merid/config/unified_risk_enforcement.py` | CRITICAL | violation details | ✅ |
| Mode transition | ⬜ | ⬜ | ⬜ | ⬜ |

**Gap:** Add structured logging for mode transitions and kill-switch activations.

### 10.C.2 Metrics and Alerts

**Proposed Minimal Metrics Set:**

| Metric | Type | Alert Threshold | Purpose |
|--------|------|-----------------|---------|
| `orders_rejected_risk_cap` | Counter | > 0 in 1m | Detect risk clamping |
| `guard_trips_total{type}` | Counter | > 5 in 5m | Detect attack/bypass attempts |
| `mode_transitions_total{from,to}` | Counter | Any LIVE transition | Audit trail |
| `kill_switch_activations` | Counter | > 0 | Immediate page |
| `executor_failures_total` | Counter | > 0 in 5m | System health |

**Deliverable:** Prometheus/StatsD metric definitions and alert rules.

### 10.C.3 Runbooks

**Runbook Skeleton:**

#### RB-1: FIX Endpoint Guard Trip (403)
- **Symptoms:** Client receives 403 on `/fix/orders`
- **Root Cause:** Attempted bypass in LIVE/PAPER mode
- **Remediation:**
  1. Verify client is using `/api/v1/kalshi/orders`
  2. Check if intentional (legacy system) or malicious
  3. If legacy: migrate to canonical endpoint
  4. If malicious: review access logs, rotate credentials
- **Resume Criteria:** Client using canonical endpoint

#### RB-2: REST Fallback Fail-Closed (503)
- **Symptoms:** 503 on `/orders`, "router unavailable"
- **Root Cause:** `order_router` import failure or exception
- **Remediation:**
  1. Check application logs for import errors
  2. Verify `merid.event_venues.kalshi.order_router` exists
  3. Check for dependency issues
  4. Restart application if needed
- **Resume Criteria:** `/health` endpoint returns OK, test order succeeds

#### RB-3: Kill-Switch Activation
- **Symptoms:** Critical alert, trading halted
- **Root Cause:** Executor contract violation or manual trigger
- **Remediation:**
  1. Do NOT immediately resume trading
  2. Review kill-switch reason and severity
  3. If executor failure: fix root cause, verify with tests
  4. If config violation: fix config, restart, verify startup enforcement
  5. Run full Pass 9 scenario suite before resuming
- **Resume Criteria:** All tests pass, manual GO from on-call

#### RB-4: Config Violation at Startup
- **Symptoms:** Application aborts, "RiskConfigViolationError"
- **Root Cause:** 6% global risk, fixed USD in LIVE, or similar
- **Remediation:**
  1. Check error message for specific violation
  2. Fix config (reduce to ≤2%, remove fixed USD)
  3. Restart application
  4. Verify clean startup in logs
- **Resume Criteria:** Application starts without error

#### RB-5: Archive Import Blocked
- **Symptoms:** ImportError when importing from `archive/`
- **Root Cause:** Attempted archive import in trading process
- **Remediation:**
  1. Verify `MERID_TRADE_MODE` is correct (should be "sim" or "analytics")
  2. If intentional: set `MERID_PROCESS_TYPE=analytics`
  3. If accidental: move code to use canonical pipeline
- **Resume Criteria:** Import succeeds or code migrated

---

## 10.D – GO/NO-GO Matrix

### Summary Table

| Mode | Status | Conditions | Key Risks Remaining |
|------|--------|-----------|---------------------|
| **SIM** | ⬜ TBD | ⬜ | ⬜ |
| **PAPER** | ⬜ TBD | ⬜ | ⬜ |
| **LIVE** | ⬜ TBD | ⬜ | ⬜ |

### Decision Criteria

**SIM Mode GO Criteria:**
- [ ] All 17 Pass 9 scenario tests passing
- [ ] CI invariant script passing
- [ ] UI/UX audit complete (no blockers)
- [ ] Logging and metrics verified

**PAPER Mode GO Criteria:**
- [ ] All SIM criteria PLUS:
- [ ] 30-minute dry-run in PAPER without guard trips
- [ ] Kill-switch tested and verified
- [ ] Operator runbook reviewed
- [ ] Small bankroll limit enforced

**LIVE Mode GO Criteria:**
- [ ] All PAPER criteria PLUS:
- [ ] 7-day PAPER observation period
- [ ] No critical issues in PAPER phase
- [ ] Manual security review complete
- [ ] Incident response plan tested
- [ ] Explicit GO/NO-GO decision meeting

---

## Implementation Checklist

- [ ] 10.A.1: Complete execution topology table
- [ ] 10.A.2: Verify risk model enforcement points
- [ ] 10.A.3: Complete guards inventory with CI coverage
- [ ] 10.A.4: Extend CI invariant script
- [ ] 10.B.1: Audit mode clarity across all surfaces
- [ ] 10.B.2: Audit risk settings interaction
- [ ] 10.B.3: Improve error messages where needed
- [ ] 10.C.1: Add missing structured logging
- [ ] 10.C.2: Implement metrics and alerts
- [ ] 10.C.3: Complete runbook skeletons
- [ ] 10.D: Fill GO/NO-GO matrix with actual assessment

---

## Output Deliverables

1. **Architecture Invariants Table** (10.A)
2. **UI/UX Audit Checklist** (10.B)
3. **Observability & Runbook Spec** (10.C)
4. **GO/NO-GO Matrix with Recommendations** (10.D)

---

*This spec should be handed to the audit/implementation agent for Pass 10 execution.*
