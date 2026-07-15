# Legacy Test Audit Report

**Date:** 2026-07-13  
**Auditor:** Test Suite Consistency Audit  
**Scope:** All test files in `tests/` directory

## Summary

- **Total test files audited:** 1,388
- **Tests with legacy imports:** 54 (3.9%)
- **Tests with legacy comments:** 27 (1.9%)
- **Tests with obsolete date patterns:** 0 (0%)
- **Clean tests:** 1,334 (96.1%)

## Audit Criteria

Tests were flagged if they contained:
1. Legacy module imports (`archive.legacy`, `merid.legacy`, `import.*legacy`)
2. Legacy/Deprecated comments (`# LEGACY`, `# DEPRECATED`, `# OBSOLETE`)
3. Obsolete date patterns (`test_2024_`, `test_2025_01_` through `test_2025_05_`)

## Findings

### Category 1: Guardrail Tests (KEEP - Critical)

These tests actively prevent legacy contamination and should **NOT** be archived:

- `test_archive_import_guard.py` - Prevents imports from archive.legacy
- `test_legacy_module_guard.py` - Prevents imports from merid.legacy
- `test_no_legacy_router_imports.py` - Ensures order router doesn't use legacy
- `test_15m_architectural_separation.py` - Enforces production/legacy separation
- `test_production_stack_alignment.py` - Validates production stack integrity

### Category 2: Legacy Directory Tests (ARCHIVE)

Tests in the `tests/legacy/` directory are for deprecated functionality:

- `tests/legacy/test_dev_swarm.py` - Legacy dev swarm tests

**Recommendation:** Archive the entire `tests/legacy/` directory to `archive/legacy_tests/`

### Category 3: Polymarket Tests (REVIEW)

Polymarket venue tests may be obsolete if that venue is no longer used:

- `tests/event_venues/test_polymarket_client.py`
- `tests/event_venues/test_polymarket_models.py`
- `tests/event_venues/polymarket/*.py` (7 files)

**Recommendation:** Review with team to determine if Polymarket is still active. If not, archive these tests.

### Category 4: Historical Fix Tests (KEEP)

Tests for historical bug fixes should be kept for regression protection:

- `test_edge_stack_fixes_2026_07_12.py`
- `test_guardrail_fixes_2026_07_08.py`
- `test_kill_switch_bug_fixes_ks6_ks15.py`

**Recommendation:** Keep these as regression tests.

### Category 5: Diagnostic/Investigation Tests (REVIEW)

Tests that were created for specific investigations may be obsolete:

- `test_kalshi_bug_investigation_regressions.py`
- `test_prediction_audit_regressions.py`
- `test_audit_regression.py`

**Recommendation:** Review if these investigations are resolved. If yes, archive.

### Category 6: WebSocket Bridge Tests (REVIEW)

Tests marked as DEPRECATED for WebSocket bridge:

- `tests/event_venues/kalshi/test_ws_bridge.py`
- `tests/event_venues/kalshi/test_ws_bridge_crash_loud.py`
- `test_websocket_bridge_health.py`

**Recommendation:** Review if ws_bridge is still used. If not, archive.

## Recommendations

### Immediate Actions

1. **Archive `tests/legacy/` directory**
   - Move to `archive/legacy_tests/`
   - Update any references in CI/CD pipelines

2. **Review Polymarket tests**
   - Confirm if Polymarket venue is still active
   - If inactive, archive `tests/event_venues/polymarket/`

3. **Review WebSocket bridge tests**
   - Confirm if ws_bridge is still used
   - If deprecated, archive marked tests

### Keep as Guardrails

The following tests serve as critical guardrails and must be kept:

- All import guard tests (archive_import_guard, legacy_module_guard, etc.)
- Architectural separation tests
- Production stack alignment tests
- Legacy contamination detection tests

### Periodic Review

Schedule quarterly reviews of:
- Historical fix tests (can be archived after 1 year if no regressions)
- Investigation tests (archive after issue is resolved and stable)

## Next Steps

1. Create `archive/legacy_tests/` directory
2. Move identified obsolete tests
3. Update CI/CD to exclude archived tests
4. Document test lifecycle policy (Phase 5.2)
