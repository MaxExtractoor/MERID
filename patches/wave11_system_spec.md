# Wave 11: Hardening & Cleanup - System Spec

## Purpose

Wave 11 implements all remaining critical and high-priority fixes identified across Passes 1-10, resolves test and tooling blockers, and drives everything to a fully green, hardened system.

**End State:**
- All code, tests, CI checks, and UX/ops changes are **implemented**, not just planned
- **Fully green test suite** in a clean, controlled environment
- Clear **GO/NO-GO matrix** for SIM, PAPER, and LIVE modes

---

## Wave 11 Workstreams

### 11.A – Testing & Infrastructure Cleanup

**Goal:** Get to **17/17 scenario tests + all critical tests green**, with no flakiness or external plugin breakage.

#### 11.A.1 Isolate from Problematic Pytest Plugins

**Problem:** Current pytest runs fail due to langsmith/charset_normalizer import issues.

**Solution:**

1. **Create clean virtualenv for MERID tests:**

```bash
# Windows
python -m venv venv_merid_tests
venv_merid_tests\Scripts\activate

# Linux/Mac
python -m venv venv_merid_tests
source venv_merid_tests/bin/activate

# Install minimal deps
pip install -e .
pip install pytest fastapi httpx pydantic
pip install pytest-asyncio respx  # For async tests if needed
```

2. **Configure pytest.ini to blacklist problematic plugins:**

```ini
# pytest.ini - add to root of repo
[pytest]
addopts = -p no:langsmith -p no:charset_normalizer --tb=short
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
asyncio_mode = auto
```

3. **Verify clean environment:**

```bash
# Check no langsmith plugin loaded
pytest --version
# Should NOT show langsmith in plugins list

# Test with plugin disabled
pytest tests/scenario/test_pass9_scenarios.py -v
```

#### 11.A.2 Finalize FastAPI TestClient Setup

**Current Issue:** 5 FastAPI endpoint tests need working TestClient + app.

**Verify/fix the import path:**

```python
# tests/scenario/test_pass9_scenarios.py - confirm this works:
from web.main import app
from fastapi.testclient import TestClient

client = TestClient(app)
```

**If import fails, check:**
1. `web/main.py` exists and exports `app`
2. PYTHONPATH includes repo root
3. No circular imports in app startup

**Fix import issues:**

```python
# Add to tests/conftest.py if needed
import sys
import os

# Ensure repo root is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
from fastapi.testclient import TestClient

@pytest.fixture(scope="module")
def client():
    from web.main import app
    return TestClient(app)
```

#### 11.A.3 Lock in Minimal, Stable Test Matrix

**Mark slow tests:**

```python
# In test files
import pytest

@pytest.mark.slow
def test_long_running_simulation():
    pass
```

**Run critical tests only:**

```bash
# Default CI target (fast)
pytest tests/risk tests/security tests/scenario -m "not slow"

# Full suite (nightly/weekly)
pytest tests --runslow
```

**Deliverable:** Wave 11 test status summary showing 100% pass on:
- Unit risk tests
- Security/guard tests
- Pass 9 scenario tests (17/17)
- Pass 10-driven tests

---

### 11.B – Code & Config Fixes from Pass 10

**Goal:** Implement concrete fixes from Pass 10 architecture + UX/Ops sweep.

#### 11.B.1 Architecture Gaps (10.A)

**Inventory from Pass 10 spec:**

| Gap | Fix Required | Test Update | CI Check |
|-----|--------------|-------------|----------|
| FIX endpoint guard coverage | Verify test exists | Add to scenario suite | Add to invariant script |
| REST fallback guard coverage | Verify test exists | Add to scenario suite | Add to invariant script |
| CT API module guard coverage | Verify test exists | Add to scenario suite | Add to invariant script |
| Startup enforcement wiring | Verify in web/main.py | Add startup test | Add to invariant script |
| CI invariant gaps | Extend check_kalshi_invariants.py | Test the checker | N/A |

**Extend CI invariant script:**

```python
# scripts/ci/check_kalshi_invariants.py

def check_fix_endpoint_guard():
    """Verify FIX endpoint guard exists and is correct."""
    kalshi_api = Path("web/api/kalshi_api.py").read_text()
    assert "PASS 8 P0: Hard disable FIX endpoint" in kalshi_api
    assert 'if _mode in ("live", "paper")' in kalshi_api
    assert "403" in kalshi_api
    print("✓ FIX endpoint guard present")

def check_rest_fallback_guard():
    """Verify REST fallback is fail-closed."""
    kalshi_api = Path("web/api/kalshi_api.py").read_text()
    assert "PASS 8 P0: FAIL CLOSED" in kalshi_api
    assert "503" in kalshi_api
    print("✓ REST fallback guard present")

def check_ct_api_guard():
    """Verify CT API module guard exists."""
    ct_api = Path("web/api/kalshi_continuous_trader_api.py").read_text()
    assert "PASS 8 P0: Module-level guard" in ct_api
    assert "403" in ct_api
    print("✓ CT API guard present")

def check_startup_enforcement():
    """Verify startup enforcement is wired."""
    main = Path("web/main.py").read_text()
    assert "enforce_at_startup" in main
    assert "Phase -1c: Unified Risk Model Enforcement" in main
    print("✓ Startup enforcement wired")

# Update main() to call these
```

#### 11.B.2 UI/UX Upstream Fixes (10.B)

**From Pass 10 audit checklist, implement:**

1. **Mode clarity:**
   - Add mode banner to web dashboard
   - Add mode label to CLI output
   - Color-code: SIM=green, PAPER=yellow, LIVE=red

2. **Risk settings:**
   - Pre-validate configs in UI before submission
   - Show warning when approaching 2% cap
   - Block 6%+ configs at UI level

3. **Error messages:**
   - Include guard name, mode, remediation in all guard errors
   - Add "contact #risk-engineering" for bypass attempts

**Example UX improvements:**

```python
# web/api/kalshi_api.py - enhance error messages

# Before
raise HTTPException(status_code=403, detail="FIX disabled")

# After  
raise HTTPException(
    status_code=403,
    detail={
        "error": "FIX_ENDPOINT_BLOCKED",
        "mode": _mode,
        "guard": "PASS8_FIX_GUARD",
        "message": "FIX protocol disabled in live/paper mode",
        "remediation": "Use /api/v1/kalshi/orders with canonical executor",
        "contact": "#risk-engineering"
    }
)
```

#### 11.B.3 Observability & Runbook Gaps (10.C)

**Structured logging improvements:**

```python
# Standardize guard log format

logger.error(
    "[GUARD_TRIP] %(guard)s mode=%(mode)s endpoint=%(endpoint)s",
    extra={
        "guard": "FIX_ENDPOINT_GUARD",
        "mode": _mode,
        "endpoint": "/fix/orders",
        "ticker": ticker,
        "side": side,
        "quantity": quantity
    }
)
```

**Metrics to implement:**

```python
# Add to merid/risk/kill_switches.py or metrics module

from prometheus_client import Counter, Histogram

# Metrics
guard_trips_total = Counter(
    'guard_trips_total',
    'Total guard trips by type',
    ['guard_type', 'mode']
)

orders_rejected_risk_cap = Counter(
    'orders_rejected_risk_cap',
    'Orders rejected by risk caps',
    ['reason']
)

mode_transitions_total = Counter(
    'mode_transitions_total',
    'Mode transitions',
    ['from_mode', 'to_mode']
)

kill_switch_activations = Counter(
    'kill_switch_activations',
    'Kill switch activations',
    ['reason', 'severity']
)
```

**Runbook completion:**

Flesh out each RB-1 through RB-5 with:
- Detection query (log search, metric alert)
- Investigation steps
- Remediation commands
- Verification steps
- Escalation criteria

---

### 11.C – CI & Deployment Guardrails

**Goal:** Ensure nobody can regress architecture or bypass tests.

#### 11.C.1 Wire All Critical Tests into CI

**GitHub Actions example:**

```yaml
# .github/workflows/merid-ci.yml

name: MERID Safety CI

on:
  push:
    branches: [main, develop]
  pull_request:

jobs:
  test-clean-env:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Set up clean Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      
      - name: Create clean venv
        run: |
          python -m venv venv_merid_tests
          source venv_merid_tests/bin/activate
          pip install -e .
          pip install pytest fastapi httpx pydantic pytest-asyncio
      
      - name: Run critical tests
        run: |
          source venv_merid_tests/bin/activate
          pytest tests/risk tests/security tests/scenario -v --tb=short
      
      - name: Run CI invariants
        run: |
          source venv_merid_tests/bin/activate
          python scripts/ci/check_kalshi_invariants.py
```

#### 11.C.2 Tighten CI Invariants

**Update check_kalshi_invariants.py to fail on violations:**

```python
import sys

def main():
    all_pass = True
    
    checks = [
        check_direct_kalshi_clients,
        check_archive_imports,
        check_raw_http_calls,
        check_archive_guard_present,
        check_fix_endpoint_guard,
        check_rest_fallback_guard,
        check_ct_api_guard,
        check_startup_enforcement,
    ]
    
    for check in checks:
        try:
            check()
        except Exception as e:
            print(f"✗ {check.__name__}: {e}")
            all_pass = False
    
    if not all_pass:
        print("\nCI INVARIANTS FAILED")
        sys.exit(1)
    
    print("\n✓ All CI invariants passed")
    sys.exit(0)

if __name__ == "__main__":
    main()
```

#### 11.C.3 Mode-Specific Pipelines (Optional)

**SIM-only checks (fast):**
```bash
pytest tests/unit tests/risk -m "not live_required"
```

**PAPER gating (full safety):**
```bash
pytest tests/  # Full suite
python scripts/ci/check_kalshi_invariants.py
```

**LIVE pre-wiring:**
```yaml
# Placeholder - remains NO-GO until manual review
- name: LIVE Gate
  run: |
    echo "LIVE deployment requires manual GO/NO-GO decision"
    exit 1  # Always fail until explicitly enabled
```

---

## Wave 11 Completion Report Template

At end of Wave 11, produce a report with these sections:

### 1. Test Status
```
Unit Risk Tests:     20/20 PASS ✓
Security Tests:      16/16 PASS ✓
Scenario Tests:      17/17 PASS ✓
CI Invariants:       8/8 PASS ✓
---------------------------
TOTAL:               61/61 PASS ✓
```

### 2. Fixes Implemented

| Source | Fix | Status |
|--------|-----|--------|
| Pass 10 Architecture Gap | CI invariant: FIX guard | ✓ |
| Pass 10 Architecture Gap | CI invariant: REST fallback guard | ✓ |
| Pass 10 Architecture Gap | CI invariant: CT API guard | ✓ |
| Pass 10 Architecture Gap | CI invariant: Startup enforcement | ✓ |
| Pass 10 UX Audit | Mode clarity improvements | ✓ |
| Pass 10 UX Audit | Risk settings pre-validation | ✓ |
| Pass 10 UX Audit | Guard error message enhancement | ✓ |
| Pass 10 Observability | Structured logging | ✓ |
| Pass 10 Observability | Metrics implementation | ✓ |
| Pass 10 Observability | Runbook completion | ✓ |

### 3. CI/CD Status
- Clean test environment configured ✓
- All critical tests wired to CI ✓
- Invariant checks blocking regressions ✓
- Mode-specific pipelines defined ✓

### 4. GO/NO-GO Matrix

| Mode | Status | Conditions |
|------|--------|-----------|
| **SIM** | ✅ GO | All tests pass, no blockers |
| **PAPER** | ✅ GO | All tests pass + 30-min dry run successful |
| **LIVE** | ❌ NO-GO | Requires 7-day PAPER observation + manual review |

### 5. Remaining Work (Post-Wave 11)
- LIVE observation period
- Operator training on new runbooks
- Incident response drill
- Manual security review

---

## Implementation Checklist

- [ ] 11.A.1: Create clean virtualenv, configure pytest.ini
- [ ] 11.A.2: Verify TestClient setup, fix any import issues
- [ ] 11.A.3: Run all 17 scenario tests to green
- [ ] 11.B.1: Extend CI invariant script with all guards
- [ ] 11.B.2: Implement UX improvements (mode clarity, risk settings)
- [ ] 11.B.3: Implement observability (logging, metrics, runbooks)
- [ ] 11.C.1: Wire tests into CI with clean environment
- [ ] 11.C.2: Make invariant checks fail CI on violations
- [ ] 11.C.3: Define mode-specific pipelines
- [ ] Final: Produce Wave 11 Completion Report with GO/NO-GO matrix

---

**Next:** Begin 11.A.1 - create clean test environment and verify 17/17 tests pass.
