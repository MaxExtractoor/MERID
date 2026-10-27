# RB-5: Archive Import Blocked

**Alert:** `merid_guard_trips_total{guard_type="ARCHIVE_IMPORT"} > 0` or `ImportError: Archive module imports are BLOCKED`

## Symptoms

- `ImportError` raised when importing from `archive` module
- Error message: "Archive module imports are BLOCKED in trading processes"
- Log: `{"event_type": "GUARD_TRIP", "guard": "PASS8_ARCHIVE_GUARD"}`
- Code fails at import statement: `from archive import ...` or `import archive`

## Impact

- Code **cannot import archive modules**
- Prevents accidental use of legacy analytics code in trading paths
- If intentional (analytics/reporting), requires explicit context switch

## Investigation

### Step 1: Identify Intent

Determine if the import is:
- **Accidental:** Code meant for trading imported archive by mistake
- **Intentional:** Analytics/reporting code needs archive data
- **Debugging:** Developer trying to inspect archive data

### Step 2: Check Process Context

```bash
# Check environment variables
env | grep -E "MERID_TRADE_MODE|MERID_PROCESS_TYPE|KALSHI_ENV"

# Expected for trading:
# MERID_TRADE_MODE=live
# MERID_PROCESS_TYPE=trading_agent  # or missing (defaults to trading)

# Expected for analytics:
# MERID_PROCESS_TYPE=analytics
# or
# MERID_TRADE_MODE=sim  # sim allows archive imports
```

### Step 3: Locate Import

```bash
# Find the problematic import
grep -r "from archive import\|import archive" --include="*.py" merid/ web/

# Check if in trading path
# Should NOT be in:
#   - merid/trading/
#   - merid/risk/
#   - web/api/ (except archive.py)
#   - merid/execution/
```

### Step 4: Check Stack Trace

```python
# If you have the error:
Traceback (most recent call last):
  File "merid/trading/some_module.py", line 5, in <module>
    from archive import outcome_scoring  # <-- PROBLEM
ImportError: Archive module imports are BLOCKED in trading processes
```

## Remediation

### Case A: Accidental Import in Trading Code

**If:** Trading code accidentally imported archive module

**Fix:**
```python
# BEFORE (in merid/trading/some_module.py)
from archive import outcome_scoring  # WRONG - in trading path

# AFTER - Option 1: Remove unused import
# Just delete the line if not needed

# AFTER - Option 2: Move code to analytics module
# Move to web/api/archive.py or separate analytics module

# AFTER - Option 3: Use canonical data pipeline
from merid.data.pipeline import get_outcome_data  # Use canonical pipeline
```

### Case B: Intentional Analytics/Reporting

**If:** Code is legitimate analytics that needs archive data

**Fix:** Set process type to analytics

```bash
# Option 1: Environment variable (recommended)
export MERID_PROCESS_TYPE=analytics
python your_analytics_script.py

# Option 2: In code before import
import os
os.environ['MERID_PROCESS_TYPE'] = 'analytics'

from archive import outcome_scoring  # Now allowed

# Option 3: Use analytics entry point
python -m merid.analytics.report_generator
# (if entry point sets process type)
```

### Case C: Debugging/Development

**If:** Developer needs to inspect archive data for debugging

**Fix:**
```bash
# Use SIM mode (allows archive imports)
export MERID_TRADE_MODE=sim
export MERID_PROCESS_TYPE=analytics

python -c "
from archive import outcome_scoring
print(outcome_scoring.load_recent())
"
```

### Case D: Separate Analytics Service

**If:** You need analytics as a separate service

**Structure:**
```
merid/
  trading/          # Trading agents (no archive imports)
  analytics/        # Analytics service (can import archive)
    report_generator.py
    outcome_analyzer.py
web/
  api/
    archive.py      # Archive API endpoints (allowed to use archive)
```

**analytics/report_generator.py:**
```python
# This runs with MERID_PROCESS_TYPE=analytics
from archive import outcome_scoring, strategy_autopsy

def generate_report(strategy_id: str) -> dict:
    """Generate post-trade analysis report."""
    outcomes = outcome_scoring.load_for_strategy(strategy_id)
    autopsy = strategy_autopsy.analyze(outcomes)
    return {
        "strategy_id": strategy_id,
        "outcomes": outcomes,
        "analysis": autopsy
    }
```

## Verification

### After Fix

```bash
# Test in trading context (should fail if archive import present)
export MERID_TRADE_MODE=live
export MERID_PROCESS_TYPE=trading_agent
python -c "
try:
    from archive import something
    print('FAIL: Import should be blocked')
except ImportError as e:
    print(f'OK: Import blocked as expected: {e}')
"

# Test in analytics context (should succeed)
export MERID_PROCESS_TYPE=analytics
python -c "
from archive import outcome_scoring
print('OK: Import succeeded in analytics context')
"
```

### Application Startup

```bash
# Start trading application
export MERID_TRADE_MODE=live
export MERID_PROCESS_TYPE=trading_agent
python -m web.main

# Should start without ImportError
```

### CI Check

```bash
# Run invariant check
python scripts/ci/check_kalshi_invariants.py
# Should pass: check_archive_guard_present()
```

## Understanding the Guard

### Why Archive Imports Are Blocked

The `archive/` module contains:
- Legacy analytics code
- Post-trade analysis tools
- Historical data processing
- Strategy autopsy (after-the-fact analysis)

These should **never** influence live trading decisions because:
1. They may use data not available at decision time (look-ahead bias)
2. They may have different validation standards
3. They may bypass risk controls

### How the Guard Works

```python
# archive/__init__.py
import os

def _enforce_archive_import_guard():
    mode = os.getenv("MERID_TRADE_MODE", "sim")
    process_type = os.getenv("MERID_PROCESS_TYPE", "trading_agent")
    
    if mode in ("live", "paper") and process_type == "trading_agent":
        raise ImportError(
            "Archive module imports are BLOCKED in trading processes. "
            "Use MERID_PROCESS_TYPE=analytics for reporting."
        )

# Enforce on import
_enforce_archive_import_guard()
```

### Allowed Contexts

| Context | MERID_TRADE_MODE | MERID_PROCESS_TYPE | Archive Import |
|---------|-------------------|-------------------|----------------|
| Live trading | live | trading_agent | ❌ BLOCKED |
| Paper trading | paper | trading_agent | ❌ BLOCKED |
| SIM testing | sim | (any) | ✅ Allowed |
| Analytics | (any) | analytics | ✅ Allowed |
| Archive API | (any) | (any, in web/api/archive.py) | ✅ Allowed |

## Prevention

### Code Review Checklist

- [ ] No `from archive import` in trading modules
- [ ] No `import archive` in risk modules
- [ ] No `from archive import` in execution modules
- [ ] Analytics code explicitly sets `MERID_PROCESS_TYPE=analytics`

### CI Detection

```python
# In check_kalshi_invariants.py - already implemented
def check_archive_imports():
    """Check for archive imports in production code."""
    for directory in ["merid", "web", "core"]:
        for py_file in Path(directory).rglob("*.py"):
            content = py_file.read_text()
            if "from archive import" in content:
                if "web/api/archive.py" not in str(py_file):
                    violations.append(...)
```

### IDE/Editor Integration

Add to `.cursor/rules` or similar:

```
# Block archive imports in trading paths
error: from archive import
  in: merid/trading/**
  in: merid/risk/**
  in: merid/execution/**
  message: "Archive imports blocked in trading paths. Use analytics context or canonical pipeline."
```

## Escalation

**Contact:** #platform-engineering if:
- Legitimate need for archive data in trading context (design discussion needed)
- Unclear how to restructure code to avoid import
- Need to create new analytics pipeline

**Contact:** #risk-engineering if:
- Suspect look-ahead bias in existing code
- Concerned about data leakage between contexts

## Related

- Guard location: `archive/__init__.py`
- Test: `tests/security/test_archive_import_guard.py`
- CI Invariant: `check_archive_guard_present()`, `check_archive_imports()`
- Allowed API: `web/api/archive.py`
