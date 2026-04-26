# Pass 12: Final Integration + Validation System Spec

## Overview

Pass 12 is the **final integration and validation phase** that completes all remaining work from Wave 11, verifies the entire system end-to-end, and produces the final GO/NO-GO decision for production use.

**Prerequisites (from Wave 11):**
- 12/12 logic tests passing ✅
- 8/8 CI invariants passing ✅
- pytest plugin isolation configured ✅
- All critical code fixes implemented ✅

**Pass 12 Goals:**
1. Verify remaining 5 FastAPI endpoint tests in clean environment
2. Implement UX/Ops enhancements (mode clarity, risk settings)
3. Complete observability (structured logging, metrics, runbooks)
4. Final architecture verification and documentation
5. Produce definitive GO/NO-GO matrix

---

## 12.A – FastAPI Test Verification

**Objective:** Achieve 17/17 scenario tests passing in clean environment.

### 12.A.1 Clean Environment Setup

**Create isolated test environment:**

```bash
# Windows
python -m venv venv_pass12
venv_pass12\Scripts\activate

# Install minimal dependencies
pip install -e .
pip install pytest fastapi httpx pydantic pytest-asyncio
```

### 12.A.2 Run FastAPI Endpoint Tests

**Test the 5 pending endpoint tests:**

```bash
pytest tests/scenario/test_pass9_scenarios.py::TestScenarioB_ExecutorFailure -v
pytest tests/scenario/test_pass9_scenarios.py::TestScenarioD_RogueAgentBypass::test_fix_endpoint_blocked_in_live -v
pytest tests/scenario/test_pass9_scenarios.py::TestScenarioD_RogueAgentBypass::test_ct_api_blocked_in_live -v
```

**Expected Results:**
- `test_fail_closed_returns_503` → 503 response when router unavailable
- `test_no_rest_fallback_in_live` → REST client NOT called
- `test_kill_switch_triggered` → Kill switch triggered with severity=critical
- `test_fix_endpoint_blocked_in_live` → 403 response in LIVE mode
- `test_ct_api_blocked_in_live` → 403 response in LIVE mode

**Troubleshooting:**
- If imports fail: Check `web.main.app` exists and exports correctly
- If 404 errors: Verify routes are registered in FastAPI app
- If 200 instead of 403/503: Check guards are actually wired

### 12.A.3 Full Suite Verification

```bash
# Run all scenario tests
pytest tests/scenario/test_pass9_scenarios.py -v

# Expected: 17 passed, 0 failed
```

**Deliverable:** Screenshot or log showing "17 passed" with 0 failures.

---

## 12.B – UX/Ops Implementation

**Objective:** Implement all UX improvements identified in Pass 10.

### 12.B.1 Mode Clarity Enhancements

**Requirement:** Make SIM/PAPER/LIVE mode unmistakably clear in all interfaces.

**Implementation:**

1. **Web Dashboard Mode Banner**

```python
# web/templates/components/mode_banner.html
<div class="mode-banner mode-{{ mode }}">
    <span class="mode-indicator">⚡ {{ mode.upper() }} MODE</span>
    <span class="mode-description">{{ mode_descriptions[mode] }}</span>
</div>

<style>
.mode-banner.mode-sim { background: #4CAF50; color: white; }
.mode-banner.mode-paper { background: #FF9800; color: black; }
.mode-banner.mode-live { background: #F44336; color: white; font-size: 1.2em; }
</style>
```

2. **CLI Mode Indicator**

```python
# merid/cli/status.py
def show_mode_banner():
    mode = get_trade_mode()
    colors = {
        "sim": "\033[92m",      # Green
        "paper": "\033[93m",    # Yellow
        "live": "\033[91m",     # Red
    }
    reset = "\033[0m"
    
    print(f"{colors.get(mode, '')}╔════════════════════════════════════╗")
    print(f"║  MERID Trading System - {mode.upper():8} MODE  ║")
    print(f"╚════════════════════════════════════╝{reset}")
    
    if mode == "live":
        print("⚠️  LIVE TRADING - REAL FUNDS AT RISK")
```

3. **Startup Mode Announcement**

```python
# web/main.py - enhance existing startup logging
logger.info("╔════════════════════════════════════════════════╗")
logger.info(f"║  MERID Trading System - {trade_mode.upper()} MODE          ║")
logger.info("╚════════════════════════════════════════════════╝")

if trade_mode == "live":
    logger.critical("⚠️  SYSTEM IS IN LIVE TRADING MODE")
    logger.critical("⚠️  REAL FUNDS ARE AT RISK")
```

### 12.B.2 Risk Settings Pre-Validation

**Requirement:** Reject unsafe configs at UI level before they reach startup.

**Implementation:**

1. **Config Validation Endpoint**

```python
# web/api/config_validation.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, validator

router = APIRouter(prefix="/api/v1/config")

class RiskConfig(BaseModel):
    max_risk_pct_global: float
    max_risk_pct_per_trade: float
    max_total_notional_usd: float | None = None
    
    @validator('max_risk_pct_global')
    def validate_global_cap(cls, v):
        if v > 0.02:
            raise ValueError(f"Global risk cap {v*100}% exceeds maximum 2%")
        return v
    
    @validator('max_total_notional_usd')
    def validate_no_fixed_usd_in_live(cls, v, values):
        mode = get_trade_mode()
        if mode in ("live", "paper") and v is not None:
            raise ValueError(f"Fixed USD sizing not allowed in {mode} mode")
        return v

@router.post("/validate")
async def validate_config(config: RiskConfig):
    """Validate risk config before applying."""
    return {"valid": True, "warnings": []}
```

2. **CLI Config Validation**

```python
# merid/cli/config.py
def set_risk_config(max_global: float, max_per_trade: float, fixed_usd: float = None):
    """Set risk configuration with immediate validation."""
    mode = get_trade_mode()
    
    # Validate before setting
    if max_global > 0.02:
        print(f"❌ ERROR: Global cap {max_global*100}% exceeds 2% limit")
        print("   Maximum allowed: 2% (0.02)")
        return False
    
    if mode in ("live", "paper") and fixed_usd:
        print(f"❌ ERROR: Fixed USD sizing not allowed in {mode} mode")
        print("   Use percentage-based sizing instead")
        return False
    
    # Apply config
    # ...
    print(f"✓ Risk config applied for {mode} mode")
    return True
```

### 12.B.3 Enhanced Error Messages

**Requirement:** All guard trips must be clear, actionable, and include remediation.

**Implementation:**

Update all guard error messages to include:
- Error code (machine-readable)
- Human-readable description
- Current mode
- Guard type
- Remediation steps
- Contact information

**Example format:**
```json
{
  "error": "GUARD_TRIP_FIX_ENDPOINT_BLOCKED",
  "message": "FIX protocol disabled in live mode",
  "mode": "live",
  "guard": "PASS8_FIX_GUARD",
  "remediation": "Use POST /api/v1/kalshi/orders with canonical executor",
  "contact": "#risk-engineering",
  "timestamp": "2026-04-23T09:12:00Z"
}
```

---

## 12.C – Observability & Runbooks

**Objective:** Implement structured logging, metrics, and complete runbooks.

### 12.C.1 Structured Logging

**Requirement:** All critical events use structured logging with consistent fields.

**Implementation:**

```python
# merid/utils/structured_logging.py
import logging
import json
from datetime import datetime
from typing import Dict, Any

class StructuredLogger:
    def __init__(self, name: str):
        self.logger = logging.getLogger(name)
    
    def log_guard_trip(self, guard_type: str, mode: str, endpoint: str,
                       details: Dict[str, Any] = None):
        """Log guard trip event."""
        event = {
            "event_type": "GUARD_TRIP",
            "guard": guard_type,
            "mode": mode,
            "endpoint": endpoint,
            "timestamp": datetime.utcnow().isoformat(),
            "details": details or {}
        }
        self.logger.error(json.dumps(event))
    
    def log_mode_transition(self, from_mode: str, to_mode: str, triggered_by: str):
        """Log mode transition."""
        event = {
            "event_type": "MODE_TRANSITION",
            "from": from_mode,
            "to": to_mode,
            "triggered_by": triggered_by,
            "timestamp": datetime.utcnow().isoformat()
        }
        self.logger.critical(json.dumps(event))  # Critical: always audit
    
    def log_kill_switch(self, reason: str, severity: str, source: str):
        """Log kill switch activation."""
        event = {
            "event_type": "KILL_SWITCH",
            "reason": reason,
            "severity": severity,
            "source": source,
            "timestamp": datetime.utcnow().isoformat()
        }
        self.logger.critical(json.dumps(event))

# Use in guards:
from merid.utils.structured_logging import StructuredLogger
logger = StructuredLogger(__name__)

# In FIX endpoint guard:
logger.log_guard_trip(
    guard_type="PASS8_FIX_GUARD",
    mode=_mode,
    endpoint="/fix/orders",
    details={"ticker": ticker, "side": side, "quantity": quantity}
)
```

### 12.C.2 Metrics Implementation

**Requirement:** Export key metrics for monitoring.

**Implementation:**

```python
# merid/metrics/kalshi_metrics.py
from prometheus_client import Counter, Histogram, Gauge, start_http_server

# Guard metrics
guard_trips_total = Counter(
    'merid_guard_trips_total',
    'Total guard trips by type',
    ['guard_type', 'mode']
)

orders_rejected_risk = Counter(
    'merid_orders_rejected_risk_total',
    'Orders rejected by risk system',
    ['reason']
)

mode_transitions_total = Counter(
    'merid_mode_transitions_total',
    'Trading mode transitions',
    ['from_mode', 'to_mode']
)

kill_switch_activations = Counter(
    'merid_kill_switch_activations_total',
    'Kill switch activations',
    ['reason', 'severity']
)

# Current state
current_trade_mode = Gauge(
    'merid_trade_mode',
    'Current trading mode (0=sim, 1=paper, 2=live)'
)

executor_availability = Gauge(
    'merid_executor_available',
    'Order router availability (1=available, 0=unavailable)'
)

# Usage in guards:
guard_trips_total.labels(guard_type="FIX_ENDPOINT", mode="live").inc()
orders_rejected_risk.labels(reason="GLOBAL_CAP_EXCEEDED").inc()
```

### 12.C.3 Complete Runbooks

**Requirement:** Documented procedures for all failure modes.

**Runbook Template:**

---

#### RB-1: FIX Endpoint Guard Trip (403)

**Alert:** `merid_guard_trips_total{guard_type="FIX_ENDPOINT"} > 0`

**Symptoms:**
- Client receives HTTP 403 on `/api/v1/kalshi/fix/orders`
- Log: `{"event_type": "GUARD_TRIP", "guard": "PASS8_FIX_GUARD"}`

**Impact:** Order rejected, client must use canonical endpoint.

**Investigation:**
```bash
# Check recent guard trips
grep "GUARD_TRIP.*FIX_ENDPOINT" /var/log/merid/app.log | tail -20

# Identify client
jq 'select(.guard == "PASS8_FIX_GUARD") | .details' /var/log/merid/app.log
```

**Remediation:**
1. **If accidental:** Update client to use `/api/v1/kalshi/orders`
2. **If intentional bypass attempt:** Review access logs, consider credential rotation
3. **If legacy system:** Schedule migration to canonical endpoint

**Verification:**
```bash
# Test canonical endpoint works
curl -X POST /api/v1/kalshi/orders \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"ticker": "KXBTC-15M", "side": "buy", "quantity": 1}'
# Expected: 200 OK
```

**Escalation:** Contact #risk-engineering if repeated bypass attempts.

---

#### RB-2: REST Fallback Fail-Closed (503)

**Alert:** `merid_executor_available == 0`

**Symptoms:**
- HTTP 503 on `/api/v1/kalshi/orders`
- Message: "Trading system degraded"
- Kill switch may trigger

**Impact:** All trading halted until executor available.

**Investigation:**
```bash
# Check executor status
python -c "from merid.event_venues.kalshi.order_router import get_router; print(get_router())"

# Check logs for import errors
grep "ImportError\|ModuleNotFoundError" /var/log/merid/app.log | tail -10
```

**Remediation:**
1. Check `order_router` module exists and is importable
2. Verify `KalshiTradingMode` is properly initialized
3. Restart application if needed

**Verification:**
```bash
# Health check
curl /api/v1/health
# Expected: {"status": "ok", "executor": "available"}

# Test order
curl -X POST /api/v1/kalshi/orders \
  -d '{"ticker": "KXBTC-15M", "side": "buy", "quantity": 1}'
# Expected: 200 OK (or risk rejection, not 503)
```

**Resume Criteria:**
- `/health` returns 200 with executor available
- Test order returns non-503 response

---

#### RB-3: Kill-Switch Activation

**Alert:** `merid_kill_switch_activations_total > 0`

**Symptoms:**
- Critical alert fired
- Trading halted
- Log: `{"event_type": "KILL_SWITCH", "severity": "critical"}`

**Impact:** Complete trading halt.

**DO NOT IMMEDIATELY RESUME**

**Investigation:**
```bash
# Get kill switch reason
jq 'select(.event_type == "KILL_SWITCH") | {reason, severity, source, timestamp}' \
  /var/log/merid/app.log | tail -1

# Check recent executor errors
grep "Executor contract violation" /var/log/merid/app.log
```

**Remediation by Cause:**

| Cause | Action |
|-------|--------|
| Executor import failure | Fix import, restart, verify with tests |
| Config violation | Fix config, restart, verify startup enforcement |
| Manual trigger | Review trigger reason, confirm resolved |
| Unknown | Full system review before resume |

**Verification (Required Before Resume):**
```bash
# Run full scenario suite
pytest tests/scenario/test_pass9_scenarios.py -v
# Must pass 17/17

# Run CI invariants
python scripts/ci/check_kalshi_invariants.py
# Must pass 8/8
```

**Resume Criteria:**
1. Root cause identified and fixed
2. All tests passing (17/17)
3. All CI invariants passing (8/8)
4. Manual GO from on-call engineer

---

#### RB-4: Config Violation at Startup

**Alert:** Application fails to start.

**Symptoms:**
- Startup aborts with `RiskConfigViolationError`
- Log: "Risk config violation: {details}"

**Impact:** Application cannot start.

**Investigation:**
```bash
# Check specific violation
grep "RiskConfigViolationError\|Risk config violation" /var/log/merid/startup.log

# Common violations:
# - "max_risk_pct_global=0.06 exceeds maximum 0.02"
# - "Fixed USD sizing not allowed in live mode"
```

**Remediation:**
1. Identify violating config value
2. Reduce global cap to ≤2% (0.02)
3. Remove fixed USD settings for live mode
4. Restart application

**Verification:**
```bash
# Check startup logs
grep "Unified Risk Model Enforcement" /var/log/merid/startup.log
# Should show "✓ Risk model validated" or similar

# Verify risk config
curl /api/v1/risk/config
# Expected: max_risk_pct_global <= 0.02
```

---

#### RB-5: Archive Import Blocked

**Alert:** `ImportError` when importing from `archive`

**Symptoms:**
- `ImportError: Archive module imports are BLOCKED in trading processes`

**Impact:** Code cannot import archive modules.

**Investigation:**
```bash
# Check process type
echo $MERID_PROCESS_TYPE
echo $MERID_TRADE_MODE

# Check if intentional or accidental
ps aux | grep python | grep -i merid
```

**Remediation:**

| Situation | Action |
|-----------|--------|
| Analytics/reporting code | Set `MERID_PROCESS_TYPE=analytics`, restart |
| Accidental import in trading | Move code to use canonical pipeline |
| Development/debugging | Use SIM mode or analytics context |

**Verification:**
```bash
# In analytics context
export MERID_PROCESS_TYPE=analytics
python -c "from archive import outcome_scoring; print('OK')"

# In trading context (should fail)
export MERID_PROCESS_TYPE=trading_agent
python -c "from archive import outcome_scoring" 2>&1 | grep "BLOCKED"
```

---

## 12.D – Final Architecture Verification

**Objective:** Complete architecture map showing all components and their relationships.

### 12.D.1 Component Inventory

**Document:** `docs/architecture/merid_kalshi_architecture.md`

**Structure:**
```markdown
# MERID + Kalshi Architecture

## Execution Flow
1. [Entry Point] → [Validation] → [Risk Check] → [Canonical Executor] → [Kalshi API]
2. All paths must route through order_router

## Risk Stack
- Global Cap: 2% (enforced at startup + per trade)
- Per-Trade Cap: 1% (enforced in allocator)
- Edge Limit: 3 (enforced in batch manager)
- Kill Switch: Triggers on executor failure

## Guard Locations
| Guard | File | Line | Test | CI |
|-------|------|------|------|-----|
| FIX Endpoint | web/api/kalshi_api.py | 5970 | test_fix_endpoint_blocked | ✓ |
| REST Fallback | web/api/kalshi_api.py | 2890 | test_fail_closed_returns_503 | ✓ |
| CT API | web/api/kalshi_continuous_trader_api.py | 1 | test_ct_api_blocked | ✓ |
| Archive Import | archive/__init__.py | 1 | test_archive_import_blocked | ✓ |
| Startup Risk | web/main.py | 2164 | test_config_violation_prevents_trading | ✓ |
```

### 12.D.2 Dependency Graph

**Generate:**
```bash
# Install graph tool
pip install pydeps

# Generate dependency graph
pydeps merid --max-bacon 2 -o docs/architecture/merid_deps.png
```

**Key Check:** No direct edges from `web/api` to `merid/event_venues/kalshi/kalshi_rest_client.py` or `kalshi_fix_client.py` (must go through `order_router`).

---

## 12.E – GO/NO-GO Matrix (Final)

**Objective:** Definitive recommendation for production use.

### 12.E.1 Prerequisites Checklist

- [ ] 17/17 scenario tests passing in clean environment
- [ ] 8/8 CI invariants passing
- [ ] All UX enhancements implemented (mode banners, risk validation)
- [ ] Structured logging deployed
- [ ] Metrics endpoint available
- [ ] All 5 runbooks complete and reviewed
- [ ] Architecture documentation complete
- [ ] Code review complete
- [ ] Security review complete

### 12.E.2 Mode-Specific Criteria

| Mode | Prerequisites | Status | Recommendation |
|------|---------------|--------|----------------|
| **SIM** | All tests pass | ⏳ TBD | Proceed when 17/17 green |
| **PAPER** | SIM + 24hr observation | ⏳ TBD | 24hr SIM run without incidents |
| **LIVE** | PAPER + 7-day + reviews | ❌ NO-GO | Pending observation period |

### 12.E.3 Risk Acceptance

**Known Risks:**
1. FastAPI endpoint tests not yet verified in clean environment
2. UX enhancements not yet implemented
3. Metrics not yet deployed

**Mitigation:**
- Complete 12.A before SIM GO
- Complete 12.B before PAPER GO
- Complete 12.C before LIVE consideration

---

## Pass 12 Deliverables

| Deliverable | Location | Status |
|-------------|----------|--------|
| Test Verification Log | `tests/scenario/pass12_test_results.log` | ⏳ |
| UX Implementation | `web/templates/`, `merid/cli/` | ⏳ |
| Structured Logging | `merid/utils/structured_logging.py` | ⏳ |
| Metrics Endpoint | `merid/metrics/` | ⏳ |
| Complete Runbooks | `docs/runbooks/` | ✅ Skeleton |
| Architecture Doc | `docs/architecture/` | ⏳ |
| Final GO/NO-GO | `patches/pass12_completion_report.md` | ⏳ |

---

## Execution Order

1. **12.A** - Verify 5 FastAPI tests (priority: blocker for everything else)
2. **12.B** - Implement UX enhancements (priority: needed for PAPER)
3. **12.C** - Deploy observability (priority: needed for PAPER)
4. **12.D** - Document architecture (priority: needed for reviews)
5. **12.E** - Final GO/NO-GO (priority: needed for production)

---

**Next:** Execute 12.A.1 - set up clean environment and run FastAPI tests.
