# MERID Legacy Risk Matrix

**Last Updated**: 2026-02-06
**Purpose**: Track quarantined, broken, and environment-sensitive test suites as explicit operating assumptions for the Dev Swarm and CI pipeline.

---

## Quarantine Categories

### 1. IOCP Hang (Windows)

Tests that block indefinitely on Windows due to `GetQueuedCompletionStatus` in the asyncio IOCP event loop or threading primitives. `pytest-timeout` cannot reliably kill these.

| File | Marker | Root Cause | Remediation |
|------|--------|------------|-------------|
| `tests/core/test_connection_pool.py` | `iocp_hang` | `ConnectionPool.shutdown()` calls `Condition.wait(timeout=1.0)` which blocks the thread timeout plugin | Refactor shutdown to use `asyncio.wait_for` or add Windows-specific `Event` signaling |
| `tests/core/test_health_monitor.py` | `iocp_hang` | `_monitor_loop` calls `psutil.disk_usage()` which blocks, then `get_health_report` acquires a lock | Mock `psutil` calls in test or use async health checks |

### 2. Windows Flaky Async

Async tests that hang on the Windows `ProactorEventLoop` IOCP selector during `run_until_complete`.

| File | Marker | Root Cause | Remediation |
|------|--------|------------|-------------|
| `tests/streaming/test_stream_bus.py` | `windows_flaky_async` | Async subscriber/publisher tests block on `_poll` in Windows event loop | Use `asyncio.wait_for` with hard timeout in test body, or refactor to use `SelectorEventLoop` on Windows |
| `tests/consensus/test_consensus_coordinator.py` | `windows_flaky_async` | Consensus voting/quorum async tests block on IOCP select | Same as above; consider mocking the event loop or using synchronous test wrappers |

### 3. Legacy Broken (Pre-existing Failures)

Tests that fail due to missing infrastructure, API changes, or stale test code. Not related to swarm integration.

| File | Failure Count | Root Cause | Remediation |
|------|--------------|------------|-------------|
| `tests/contracts/test_intents.py` | 17 | `AttributeError` - Intent/IntentPayload API changed but tests not updated | Update test assertions to match current `IntentPayload` dataclass fields |
| `tests/core/test_cache.py` | 4 | Redis not available in test environment | Add `@pytest.mark.skipif` for Redis, or mock Redis client |
| `tests/compliance/test_audit_logger.py` | 2 | Time range query returns unexpected results | Fix query logic or test expectations |
| `tests/core/test_error_handling.py` | 1 | Sync decorator error handling test fails | Update decorator test to match current implementation |
| `tests/agents/core/test_market_analyst.py` | 6 | Agent interface mismatch (observe/analyze API changed) | Update tests to match current `MarketAnalystAgent` interface |
| `tests/integration/test_http_mocks.py` | 1 + 2 errors | HTTP retry test + mock infrastructure issues | Fix respx/httpx mock setup |
| `tests/integration/test_integration_components.py` | 2 + 3 errors | Redis EventBus not available | Skip when Redis unavailable, or mock |

### 4. Collection Errors (Import Failures)

Test files that fail to import/collect due to missing dependencies or broken module paths.

| File | Root Cause | Remediation |
|------|------------|-------------|
| `tests/execution/test_persistent_book_extended.py` | Import error in execution module | Fix import path or add conditional skip |
| `tests/merid/risk/test_chaos.py` | Missing risk module dependency | Add dependency or conditional import |
| `tests/merid/risk/test_kill_switches.py` | Missing risk module dependency | Same as above |
| `tests/trading/adapters/test_base_coverage.py` | Trading adapter import failure | Fix adapter base class imports |
| `tests/trading/test_router.py` | Router import failure | Fix router module path |
| `tests/trading/test_router_coverage.py` | Router import failure | Same as above |

---

## Frontend Legacy Errors

### TypeScript Source Errors (8 pre-existing, non-test)

| File | Error | Root Cause | Remediation |
|------|-------|------------|-------------|
| `src/App.tsx` (2) | `Type 'View' is not assignable to type 'View'` | Two `View` type definitions conflict | Consolidate View type into single source |
| `src/components/charts/AgentOpinionChart.tsx` (2) | Unused `React`, `useEffect` imports | Dead imports | Remove unused imports |
| `src/hooks/useKafkaStream.ts` (1) | Unused `event` variable | Dead variable in handler | Prefix with `_` or remove |
| `src/utils/websocketWithBackoff.ts` (1) | Unused `event` variable | Dead variable in handler | Prefix with `_` or remove |
| `src/views/TradeFloor.tsx` (2) | Unused `tradeWsStatus`, `riskWsStatus` | Destructured but unused | Remove from destructuring |

### TypeScript Test Errors (34 pre-existing)

| File | Count | Root Cause |
|------|-------|------------|
| `src/hooks/__tests__/useMeridSocket.test.tsx` | 28 | Test expects old `useMeridSocket` API (args, `send`, `error`, `lastMessage`) |
| `src/services/__tests__/api.test.ts` | 2 | `apiClient` and `ApiError` no longer exported from `api.ts` |
| `src/views/__tests__/Risk.test.tsx` | 2 | Unused `React`, `screen` imports |
| `src/views/__tests__/TradeFloor.test.tsx` | 1 | Unused `data` variable |

---

## Coverage Domains

### Domain 1: Dev Swarm Subsystem (Strict Gate)

**Target**: ≥90% coverage
**Scope**: `core/dev_swarm.py`, `core/dev_swarm_persistence.py`, `core/dev_swarm_metrics.py`, `web/api/dev_swarm_routes.py`
**Test file**: `tests/test_dev_swarm.py` (150 tests across 28+ classes)
**Current**: 150/150 passing, 93.52%+ combined coverage, 0 TS errors

```bash
# Run Dev Swarm coverage only (module-style paths required)
pytest -m dev_swarm --cov=core.dev_swarm --cov=core.dev_swarm_persistence --cov=core.dev_swarm_metrics --cov=web.api.dev_swarm_routes --cov-report=term --cov-fail-under=90 -p no:timeout
```

### Domain 2: Backend Baseline (Rising Floor)

**Target**: Slowly rising from current baseline
**Scope**: All backend code excluding quarantined tests
**Current**: 377 passed, 24 failed (legacy), ~7.5% of 41K lines

```bash
# Run all non-quarantined tests with coverage
pytest tests/ --cov=core --cov=agents --cov=web --cov=trading --cov-report=term -p no:timeout
# Quarantined tests auto-skipped via conftest.py hook
```

### Domain 3: Quarantined (Non-Gating, Visibility Only)

**Target**: Track, don't gate
**Scope**: IOCP hang + Windows flaky async tests

```bash
# Run ONLY quarantined tests (for remediation work)
pytest -m "iocp_hang or windows_flaky_async" --no-header -q
```

---

## DevTask Templates for Legacy Remediation

The Dev Swarm can be explicitly tasked with fixing these areas:

1. **Fix Intent Contract Tests** - Update `test_intents.py` to match current `IntentPayload` API
2. **Add Redis Skip Guards** - Add `@pytest.mark.skipif` to Redis-dependent tests
3. **Fix Market Analyst Tests** - Update to match current agent interface
4. **Resolve View Type Conflict** - Consolidate `View` type in React app
5. **Clean Frontend Dead Code** - Remove unused imports/vars in TS source files
6. **Refactor Connection Pool for Async** - Eliminate IOCP hang in shutdown

---

## Official Testing Policy

### Fast Suite (Default, Gating)

`pytest tests/` is **the official fast suite**. IOCP/legacy failures are auto-skipped via `conftest.py` quarantine hook on Windows. This is the suite that gates PRs and CI.

### Legacy Remediation Suite (Non-Gating, Monitored)

`pytest -m "iocp_hang or windows_flaky_async or legacy_broken"` is **the legacy remediation suite**. It runs non-gating on a schedule (e.g., nightly) and posts xfail/skip counts for visibility. Failures here do not block work.

### Operating Rules

1. **Default `pytest` runs** auto-skip quarantined tests via `conftest.py` hook on Windows
2. **CI gates** use Domain 1 (Dev Swarm ≥90%, ratcheting toward ≥95%) and Domain 2 (baseline floor)
3. **Quarantined tests** run in a separate non-gating job with visibility
4. **Legacy fixes** are explicit DevTask assignments, not background noise
5. **New code** must include tests in the appropriate domain
6. **Coverage ratchet**: When Dev Swarm domain coverage increases, raise `--cov-fail-under` to lock in the gain

### Current Coverage Snapshot (2026-02-06)

| Module | Coverage |
|--------|----------|
| `core/dev_swarm.py` | 98.92% |
| `core/dev_swarm_persistence.py` | 84.66% |
| `core/dev_swarm_metrics.py` | 78.43% |
| `web/api/dev_swarm_routes.py` | 99.40% |
| **Dev Swarm Domain Combined** | **93.52%** |
| Tests | 150/150 passing |

### CI Command

```bash
pytest -m dev_swarm --cov=core.dev_swarm --cov=core.dev_swarm_persistence --cov=core.dev_swarm_metrics --cov=web.api.dev_swarm_routes --cov-report=term --cov-fail-under=90 -p no:timeout
```

### Nightly Readiness Audit (CI / Cron)

The readiness auditor should run nightly to detect drift before it compounds.

```bash
# CI job (GitHub Actions / GitLab CI)
python -m core.dev_swarm_readiness_auditor --json
# Exit code 0 = all OK, 1 = drift detected

# Cron (e.g. every night at 2 AM)
0 2 * * * cd /path/to/MERID && python -m core.dev_swarm_readiness_auditor --fix >> /var/log/merid-readiness.log 2>&1

# API endpoint (for dashboard polling)
GET /api/dev-swarm/readiness
```

The `--fix` flag auto-creates DevTask dicts describing exactly what drifted and how to repair it.
The React dashboard at `/dev-swarm` shows a live readiness indicator with expand-to-detail.
