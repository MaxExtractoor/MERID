# Test Lifecycle Policy

**Version:** 1.0  
**Effective:** 2026-07-13  
**Owner:** Test Suite Consistency Audit

## Purpose

This policy defines the lifecycle of tests in the MERID codebase, from creation through archival, to ensure a maintainable and effective test suite that supports the production 15m Kalshi crypto trading system.

## Test Categories

### 1. Production Tests (ACTIVE)

**Definition:** Tests that validate current production functionality.

**Lifecycle:**
- **Creation:** Created when implementing new features or fixing bugs
- **Maintenance:** Updated when production code changes
- **Archival:** Never archived unless the feature is removed from production

**Examples:**
- `test_15m_production_guardrails.py`
- `test_price_filtering_consistency.py`
- `test_agent_grid_spot_data_fixes.py`

**Requirements:**
- Must pass in CI/CD pipeline
- Must have clear docstrings
- Must not import from legacy modules
- Must use production stack (web/main_15m_lean.py, not web/main.py)

### 2. Regression Tests (ACTIVE)

**Definition:** Tests that prevent recurrence of historical bugs.

**Lifecycle:**
- **Creation:** Created when fixing a bug
- **Maintenance:** Reviewed quarterly for relevance
- **Archival:** After 1 year of stability with no regressions

**Examples:**
- `test_75c_price_clamping_fix.py`
- `test_robustness_fixes_2026.py`
- `test_execution_disconnect_fixes_2026_07_12.py`

**Requirements:**
- Must reference the original bug/issue
- Must include date in filename (YYYY-MM-DD format)
- Must be reviewed quarterly
- Can be archived after 1 year if no regressions

### 3. Guardrail Tests (PERMANENT)

**Definition:** Tests that prevent architectural violations and legacy contamination.

**Lifecycle:**
- **Creation:** Created when architectural guardrails are defined
- **Maintenance:** Updated when architecture changes
- **Archival:** Never archived

**Examples:**
- `test_archive_import_guard.py`
- `test_legacy_module_guard.py`
- `test_15m_architectural_separation.py`
- `test_production_stack_alignment.py`

**Requirements:**
- Must be permanently active
- Must run in every CI/CD pipeline
- Must fail loudly if violated
- Must never be skipped or marked as xfail

### 4. Investigation Tests (TEMPORARY)

**Definition:** Tests created during bug investigation or debugging.

**Lifecycle:**
- **Creation:** Created during active investigation
- **Maintenance:** Updated as investigation progresses
- **Archival:** Archived immediately after issue resolution

**Examples:**
- `test_kalshi_bug_investigation_regressions.py`
- `test_prediction_audit_regressions.py`
- `test_audit_regression.py`

**Requirements:**
- Must be marked with `# INVESTIGATION` comment
- Must be archived after issue is resolved
- Should not be added to permanent test suite
- Can be converted to regression tests if the issue was significant

### 5. Obsolete Tests (ARCHIVED)

**Definition:** Tests for deprecated functionality or removed features.

**Lifecycle:**
- **Creation:** N/A (already existed)
- **Maintenance:** None
- **Archival:** Moved to `archive/legacy_tests/`

**Examples:**
- Tests in `tests/legacy/` directory
- Polymarket venue tests (if venue no longer used)
- WebSocket bridge tests (if component deprecated)

**Requirements:**
- Must be moved to `archive/legacy_tests/`
- Must not run in CI/CD pipeline
- Must be kept for historical reference (minimum 1 year)

## Test Creation Guidelines

### Naming Conventions

**Production Tests:**
- Use descriptive names: `test_<feature>_<aspect>.py`
- Example: `test_price_filtering_consistency.py`

**Regression Tests:**
- Include date: `test_<issue>_<YYYY_MM_DD>.py`
- Example: `test_75c_price_clamping_fix.py`

**Guardrail Tests:**
- Use `_guard` or `_enforcement` suffix
- Example: `test_archive_import_guard.py`

**Investigation Tests:**
- Include `investigation` in name
- Example: `test_kalshi_bug_investigation_regressions.py`

### Documentation Requirements

All tests must include:
1. **Module docstring** describing what the test validates
2. **Function docstrings** for each test function
3. **Comments** explaining complex logic
4. **References** to related issues or PRs

Example:
```python
"""Tests for price filtering consistency.

Validates that price filtering logic maintains the canonical 10-75c range
across all components of the 15m Kalshi crypto trading system.

Related: Price Range Expansion Reference (10-75c Canonical Range)
"""

def test_profile_adapter_default_range():
    """Profile adapter should default to 75c max price."""
    # Test implementation
```

### Import Guidelines

**Allowed:**
- Production modules (merid.*, merid_core.*, web.main_15m_lean)
- Test utilities (pytest, hypothesis, unittest.mock)
- Standard library

**Prohibited:**
- Legacy modules (merid.legacy, archive.legacy)
- Legacy entry points (web.main)
- Deprecated components

**Enforcement:**
- Guardrail tests will fail if legacy imports detected
- CI/CD will reject PRs with legacy imports in new tests

## Test Maintenance

### Quarterly Review Process

**Schedule:** First Monday of each quarter

**Review Checklist:**
1. Identify regression tests older than 1 year
2. Check if original issue has recurred
3. Archive stable regression tests
4. Review investigation tests for resolution
5. Update test documentation if needed

**Outcome:**
- Archive obsolete tests
- Update test lifecycle documentation
- Create action items for any failing tests

### Continuous Maintenance

**Before Code Changes:**
- Run affected tests locally
- Update tests to match new behavior
- Add new tests for new functionality

**After Code Changes:**
- Verify all tests pass in CI/CD
- Check test coverage metrics
- Update documentation if behavior changed

## Test Archival Process

### When to Archive

Archive tests when:
1. Feature is removed from production
2. Component is deprecated
3. Investigation is resolved
4. Regression test is stable for 1+ year

### Archival Steps

1. **Move file:**
   ```bash
   mv tests/test_obsolete.py archive/legacy_tests/test_obsolete.py
   ```

2. **Update CI/CD:**
   - Remove from test suite configuration
   - Update pytest.ini exclusions if needed

3. **Document:**
   - Add entry to `archive/legacy_tests/ARCHIVE_LOG.md`
   - Include reason and date of archival

4. **Verify:**
   - Run CI/CD to ensure archived tests don't run
   - Confirm production tests still pass

### Archive Log Format

```markdown
## test_obsolete.py

**Archived:** 2026-07-13  
**Reason:** Feature X removed from production  
**Replaced by:** None  
**Reference:** Issue #123  
```

## Test Quality Standards

### Coverage Requirements

- **Critical paths:** 100% coverage
- **Core trading logic:** 90%+ coverage
- **Risk enforcement:** 95%+ coverage
- **Overall suite:** 80%+ coverage

### Performance Requirements

- **Unit tests:** < 1 second per test
- **Integration tests:** < 10 seconds per test
- **Full suite:** < 5 minutes total

### Reliability Requirements

- **Flaky tests:** Not tolerated
- **Intermittent failures:** Must be fixed before merge
- **Test dependencies:** Must be mocked or stubbed

## Enforcement

### CI/CD Gates

**Required for Merge:**
1. All production tests pass
2. All guardrail tests pass
3. Coverage threshold met
4. No legacy imports in new code
5. No test timeouts

**Blocked by:**
1. Failing production tests
2. Failing guardrail tests
3. New legacy imports
4. Coverage below threshold
5. Flaky tests

### Code Review Checklist

Reviewers must verify:
- [ ] Tests follow naming conventions
- [ ] Tests have docstrings
- [ ] Tests don't import legacy modules
- [ ] Tests are appropriately categorized
- [ ] Tests pass locally
- [ ] Tests are not flaky

## Exceptions

### Emergency Exceptions

In emergencies (production outage, critical bug):
- Tests can be temporarily skipped with `@pytest.mark.skip`
- Must include issue reference in skip reason
- Must be resolved within 1 week

### Approval Process

Exceptions require:
1. Team lead approval
2. Documented reason
3. Resolution timeline
4. Follow-up ticket created

## Revision History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-07-13 | Initial policy creation |
