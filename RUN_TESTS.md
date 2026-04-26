# Running MERID Tests

This document provides exact commands for running MERID tests in a clean environment.

## Prerequisites

- Python 3.11 or newer
- Windows with PowerShell or Command Prompt

## Quick Start (Windows)

### 1. Create and activate a clean virtual environment

```powershell
# Create virtual environment
py -3.11 -m venv .venv

# Activate it
.venv\Scripts\activate
```

### 2. Install dependencies

```powershell
pip install -e .
pip install pytest fastapi httpx
```

### 3. Disable auto-loaded plugins

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD="1"
```

Or in Command Prompt:
```cmd
set PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
```

### 4. Run tests

#### Risk Enforcement Tests (20 tests)

```powershell
pytest tests/risk/test_unified_risk_enforcement.py -vv
```

#### Pass 9 Scenario Tests (17 tests)

```powershell
pytest tests/scenario/test_pass9_scenarios.py -vv -p no:langsmith -p no:charset_normalizer
```

#### Single Test (Example)

```powershell
pytest tests/scenario/test_pass9_scenarios.py::TestScenarioB_ExecutorFailure::test_fail_closed_returns_503 -vv
```

## Alternative: Using Batch Script

For convenience, use the provided batch script:

```powershell
.\run_tests.bat
```

This will:
1. Create `.venv` if it doesn't exist
2. Activate the virtual environment
3. Install dependencies
4. Run all tests
5. Save results to `test_output_risk.txt` and `test_output_scenario.txt`

## Troubleshooting

### Plugin Errors

If you see errors about `langsmith` or `charset_normalizer` plugins:

1. Ensure `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` is set
2. Use `-p no:langsmith -p no:charset_normalizer` flags
3. Check that `pytest.ini` contains the plugin blacklist

### Import Errors

If tests fail with import errors:

1. Make sure you're in the repo root (`c:\Dev\MERID`)
2. Verify `pip install -e .` completed successfully
3. Check that `.venv\Scripts\activate` is active (you should see `(.venv)` in your prompt)

### Test Client Issues

The FastAPI tests require the app to import cleanly. If you see errors:

1. Check that `web.main.app` can be imported
2. Verify all dependencies are installed: `pip install fastapi httpx`
3. Look for missing fixtures in `tests/conftest.py`

## Expected Results

### Risk Tests
- **Expected:** 20/20 passing
- **Tests:** Unified risk enforcement, config validation, startup checks

### Scenario Tests
- **Expected:** 17/17 passing
- **Breakdown:**
  - Scenario A (Multi-agent flood): 3 tests
  - Scenario B (Executor failure): 3 tests (FastAPI endpoint tests)
  - Scenario C (Config mis-set): 3 tests
  - Scenario D (Rogue agent bypass): 3 tests (FastAPI endpoint tests)
  - Scenario E (Mode transitions): 4 tests
  - Runner: 1 test

## CI Configuration

The same commands are used in CI (`.github/workflows/merid-safety-ci.yml`):

```yaml
- name: Run Risk Tests
  run: |
    $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD="1"
    pytest tests/risk/test_unified_risk_enforcement.py -vv

- name: Run Scenario Tests
  run: |
    $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD="1"
    pytest tests/scenario/test_pass9_scenarios.py -vv -p no:langsmith -p no:charset_normalizer
```

## Linux/macOS Adaptation

For Unix-like systems:

```bash
# Create venv
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -e .
pip install pytest fastapi httpx

# Disable plugins and run tests
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
pytest tests/risk/test_unified_risk_enforcement.py -vv
pytest tests/scenario/test_pass9_scenarios.py -vv -p no:langsmith -p no:charset_normalizer
```
