# Test Maintenance Guide

**Version:** 1.0  
**Effective:** 2026-07-13  
**Related:** [TEST_LIFECYCLE_POLICY.md](TEST_LIFECYCLE_POLICY.md)

## Purpose

This guide provides practical instructions for maintaining the MERID test suite, covering day-to-day operations, troubleshooting, and best practices for the 15m Kalshi crypto trading system.

## Quick Reference

### Common Commands

```bash
# Run all tests
py -m pytest tests/ -v

# Run specific test file
py -m pytest tests/test_price_filtering_consistency.py -v

# Run specific test function
py -m pytest tests/test_price_filtering_consistency.py::TestProfileAdapter::test_default_range -v

# Run with coverage
py -m pytest tests/ --cov=merid --cov-report=html

# Run only production tests (skip legacy)
py -m pytest tests/ --ignore=tests/legacy/ --ignore=tests/event_venues/polymarket/

# Run guardrail tests only
py -m pytest tests/ -k "guard or import_guard or legacy_guard" -v

# Run property-based tests (Hypothesis)
py -m pytest tests/test_property_tests.py -v

# Run fuzzing tests
py -m pytest tests/test_fuzzing_*.py -v

# Run overfitting metrics tests
py -m pytest tests/test_overfitting_*.py -v
```

### Test Categories by Location

| Category | Location | Example |
|----------|----------|---------|
| Production Tests | `tests/` (root) | `test_price_filtering_consistency.py` |
| Regression Tests | `tests/` (root) | `test_75c_price_clamping_fix.py` |
| Guardrail Tests | `tests/` (root) | `test_archive_import_guard.py` |
| Integration Tests | `tests/api/`, `tests/merid/` | `tests/api/test_dashboard.py` |
| Chaos Tests | `tests/chaos/` | `tests/chaos/test_chaos_engineering.py` |
| Legacy Tests | `tests/legacy/` (archive) | `tests/legacy/test_dev_swarm.py` |
| Obsolete Tests | `archive/legacy_tests/` | N/A |

## Daily Maintenance

### Before Starting Work

1. **Pull latest changes:**
   ```bash
   git pull origin main
   ```

2. **Run full test suite:**
   ```bash
   py -m pytest tests/ -v --tb=short
   ```

3. **Check for new test failures:**
   - Note any new failures
   - Check if they're related to your changes
   - Document in issue tracker if needed

### During Development

1. **Run relevant tests:**
   ```bash
   # For price-related changes
   py -m pytest tests/test_price_*.py -v
   
   # For risk-related changes
   py -m pytest tests/test_risk_*.py -v
   
   # For agent grid changes
   py -m pytest tests/test_agent_grid_*.py -v
   ```

2. **Add new tests for new functionality:**
   - Follow naming conventions (see TEST_LIFECYCLE_POLICY.md)
   - Include docstrings
   - Ensure no legacy imports
   - Run locally before committing

3. **Update existing tests if behavior changes:**
   - Update assertions to match new behavior
   - Add comments explaining the change
   - Reference the issue/PR that caused the change

### Before Committing

1. **Run full test suite:**
   ```bash
   py -m pytest tests/ -v
   ```

2. **Check coverage:**
   ```bash
   py -m pytest tests/ --cov=merid --cov-report=term-missing
   ```

3. **Verify no legacy imports:**
   ```bash
   py tests/test_legacy_audit.py
   ```

4. **Run guardrail tests:**
   ```bash
   py -m pytest tests/ -k "guard" -v
   ```

## Weekly Maintenance

### Monday Morning Checklist

1. **Review test failures from weekend:**
   - Check CI/CD logs
   - Identify flaky tests
   - Create tickets for fixes

2. **Run legacy audit:**
   ```bash
   py tests/test_legacy_audit.py
   ```
   - Review new legacy imports
   - Address any contamination

3. **Check test coverage trends:**
   - Compare with previous week
   - Investigate coverage drops
   - Update documentation if needed

### End of Week Checklist

1. **Archive resolved investigation tests:**
   - Check `test_*investigation*.py` files
   - Move resolved ones to archive
   - Update archive log

2. **Review regression test age:**
   - Identify tests older than 1 year
   - Check if issue has recurred
   - Archive stable tests

3. **Update test documentation:**
   - Add new test categories if needed
   - Update maintenance guide with lessons learned
   - Document any new patterns

## Monthly Maintenance

### First Monday of Month

1. **Quarterly test review (per TEST_LIFECYCLE_POLICY.md):**
   - Review regression tests older than 1 year
   - Archive stable regression tests
   - Review investigation tests for resolution
   - Update test lifecycle documentation

2. **Performance audit:**
   - Identify slow tests (> 10s)
   - Optimize or mark as integration test
   - Update test categorization

3. **Dependency check:**
   - Update pytest and plugins
   - Update Hypothesis
   - Update other test dependencies
   - Test with new versions

## Troubleshooting

### Common Issues

#### Issue: Test fails with import error

**Symptom:** `ModuleNotFoundError: No module named 'merid.legacy'`

**Cause:** Test importing from legacy module

**Solution:**
1. Check if import is necessary
2. If yes, refactor to use production module
3. If no, remove import
4. Run guardrail test to verify fix

#### Issue: Test fails intermittently

**Symptom:** Test passes sometimes, fails other times

**Cause:** Flaky test (timing, state, external dependency)

**Solution:**
1. Add retries with `@pytest.mark.flaky`
2. Fix underlying timing issue
3. Mock external dependencies
4. Make test deterministic

#### Issue: Test times out

**Symptom:** Test runs for > 60 seconds then fails

**Cause:** Infinite loop, slow external call, resource leak

**Solution:**
1. Add timeout: `@pytest.mark.timeout(30)`
2. Mock slow external calls
3. Check for infinite loops
4. Profile to find bottleneck

#### Issue: Coverage dropped unexpectedly

**Symptom:** Coverage report shows decrease

**Cause:** Code removed without test updates, test disabled

**Solution:**
1. Identify uncovered code
2. Add tests for new code paths
3. Re-enable disabled tests
4. Check if code removal was intentional

### Debugging Flaky Tests

**Step 1: Isolate the test**
```bash
py -m pytest tests/test_flaky.py::test_flaky_function -v --tb=long
```

**Step 2: Run multiple times**
```bash
for i in {1..10}; do py -m pytest tests/test_flaky.py::test_flaky_function -v; done
```

**Step 3: Add debugging**
```python
def test_flaky_function():
    import time
    print(f"Test started at {time.time()}")
    # test code
    print(f"Test ended at {time.time()}")
```

**Step 4: Check for state**
```bash
# Run with fresh environment
py -m pytest tests/test_flaky.py::test_flaky_function -v --forked
```

**Step 5: Fix or mark as flaky**
```python
import pytest

@pytest.mark.flaky(reruns=3)
def test_flaky_function():
    # test code
```

## Adding New Tests

### Step-by-Step Process

**1. Determine test category:**
- Production test: For current functionality
- Regression test: For bug fix
- Guardrail test: For architectural rule
- Investigation test: For active debugging

**2. Choose appropriate location:**
- Root `tests/` for production/regression/guardrail
- Subdirectory for specific component (e.g., `tests/api/`)
- `tests/chaos/` for chaos tests

**3. Create test file with proper structure:**
```python
"""Tests for [feature name].

Validates that [feature] works correctly in the 15m Kalshi crypto trading system.

Related: [issue/PR reference]
"""

import pytest
from hypothesis import given, settings, Phase
from hypothesis.strategies import integers, sampled_from

class TestFeatureName:
    """Test class for [feature]."""
    
    def test_basic_functionality(self):
        """Test that basic functionality works."""
        # Arrange
        # Act
        # Assert
        pass
```

**4. Add docstrings:**
- Module docstring describing what's tested
- Class docstring describing test group
- Function docstrings for each test

**5. Verify no legacy imports:**
```bash
py tests/test_legacy_audit.py
```

**6. Run locally:**
```bash
py -m pytest tests/test_new_feature.py -v
```

**7. Commit with descriptive message:**
```
Add tests for [feature]

- Test basic functionality
- Test edge cases
- Test error handling
```

## Test Patterns

### Property-Based Testing Pattern

```python
from hypothesis import given, settings, Phase
from hypothesis.strategies import integers, sampled_from

@given(
    price_cents=integers(min_value=10, max_value=75),
    quantity=integers(min_value=1, max_value=10)
)
@settings(max_examples=100, phases=[Phase.generate])
def test_price_calculation_invariant(price_cents, quantity):
    """Price calculation should maintain invariant."""
    exposure = (price_cents / 100.0) * quantity
    assert exposure >= 0
    assert exposure <= 10.0  # $1 cap with 10 contracts max
```

### Fuzzing Pattern

```python
from hypothesis import given, settings, Phase
from hypothesis.strategies import text, dictionaries

@given(json_str=text(min_size=0, max_size=1000))
@settings(max_examples=100, phases=[Phase.generate])
def test_json_parsing_robustness(json_str):
    """JSON parsing should handle various inputs."""
    try:
        parsed = json.loads(json_str)
        assert isinstance(parsed, (dict, list, str, int, float, bool))
    except json.JSONDecodeError:
        assert True
```

### Differential Testing Pattern

```python
def test_price_clamping_consistency():
    """Price clamping should be consistent across implementations."""
    # Method 1
    price1 = max(10, min(75, raw_price))
    
    # Method 2
    price2 = clamp_to_canonical_range(raw_price)
    
    # Should match
    assert price1 == price2
```

### Chaos Testing Pattern

```python
def test_order_submission_with_network_failure():
    """Order submission should handle network failures gracefully."""
    with patch('merid.event_venues.kalshi.client.submit_order', side_effect=ConnectionError):
        result = submit_order(intent)
        assert result.status == "FAILED"
        assert result.error == "Network error"
```

## Performance Optimization

### Identifying Slow Tests

```bash
# Run with timing
py -m pytest tests/ --durations=10

# Profile specific test
py -m pytest tests/test_slow.py --profile
```

### Optimizing Strategies

1. **Mock external calls:**
```python
from unittest.mock import patch

def test_with_mock():
    with patch('external_api.call', return_value=42):
        result = function_using_api()
        assert result == 42
```

2. **Use fixtures for setup:**
```python
@pytest.fixture
def mock_client():
    return MockClient()

def test_with_fixture(mock_client):
    result = mock_client.call()
    assert result is not None
```

3. **Parallelize independent tests:**
```bash
py -m pytest tests/ -n auto  # Use pytest-xdist
```

## CI/CD Integration

### GitHub Actions Configuration

```yaml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Set up Python
        uses: actions/setup-python@v2
        with:
          python-version: '3.11'
      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install pytest pytest-cov hypothesis
      - name: Run tests
        run: |
          pytest tests/ -v --cov=merid --cov-report=xml
      - name: Upload coverage
        uses: codecov/codecov-action@v2
```

### Pre-commit Hooks

```yaml
# .pre-commit-config.yaml
repos:
  - repo: local
    hooks:
      - id: pytest
        name: Run pytest
        entry: pytest tests/ -v
        language: system
        pass_filenames: false
```

## Resources

### Documentation

- [TEST_LIFECYCLE_POLICY.md](TEST_LIFECYCLE_POLICY.md) - Test lifecycle and archival policy
- [LEGACY_AUDIT_REPORT.md](LEGACY_AUDIT_REPORT.md) - Legacy test audit results
- [pytest documentation](https://docs.pytest.org/)
- [Hypothesis documentation](https://hypothesis.readthedocs.io/)

### Internal References

- Price Range Expansion Reference (10-75c Canonical Range) - See system memory
- Duplicate Order Bug Fix (2026-07-12) - See system memory
- Execution Disconnect Fix (2026-07-12) - See system memory

### Key Invariants

- **Canonical price range:** 10-75c for order execution
- **Global exposure cap:** $1.00 fixed dollar exposure
- **Core assets:** BTC, ETH, SOL, XRP, DOGE (all 5 required)
- **Production entry point:** web/main_15m_lean.py (not web/main.py)
- **Legacy contamination:** Never import from legacy modules in production code

## Contact

For questions about test maintenance:
- Review this guide first
- Check TEST_LIFECYCLE_POLICY.md
- Consult team lead for exceptions
- Create GitHub issue for bugs or improvements

## Revision History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-07-13 | Initial guide creation |
