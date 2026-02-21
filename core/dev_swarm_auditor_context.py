"""
Dev Swarm Auditor Context - Ground truth for test/coverage reality.

This module provides the auditor agent with current test and coverage
state so it can make informed decisions about where to focus effort.
"""

# Appended to auditor agent system prompt at swarm initialization
AUDITOR_CONTEXT = """
Use the following current test and coverage reality for MERID as ground truth:

- Dev Swarm subsystem:
  - core/dev_swarm.py and related persistence/metrics/routes: 393/393 tests passing (93.52%+ domain coverage), no TypeScript errors in Dev Swarm UI components.
- Backend tests:
  - 377+ tests passed, 24 failed (all pre-existing), 2 skipped.
  - Overall backend coverage: ~7.5% over ~41K lines, because multiple test directories are excluded or failing.
  - Dev Swarm domain coverage gate: --cov-fail-under=90 (currently at 93.52%).
- Known hanging async test files on Windows (IOCP GetQueuedCompletionStatus issues):
  - tests/core/test_connection_pool.py
  - tests/core/test_health_monitor.py
  - tests/streaming/test_stream_bus.py
  - tests/consensus/test_consensus_coordinator.py
- Known failing test modules (pre-existing, not from Dev Swarm work):
  - tests/contracts/test_intents.py (17 failures - contracts API changed)
  - tests/core/test_cache.py (4 failures - Redis not available)
  - tests/compliance/test_audit_logger.py (2 failures - time range query)
  - tests/core/test_error_handling.py (1 failure - sync decorator)
  - tests/agents/core/test_market_analyst.py (6 failures - agent interface mismatch)
  - tests/integration/test_http_mocks.py (1 failure + 2 errors - mock infra)
  - tests/integration/test_integration_components.py (2 failures + 3 errors - Redis)
- Known collection errors (import failures):
  - tests/execution/test_persistent_book_extended.py
  - tests/merid/risk/test_chaos.py
  - tests/merid/risk/test_kill_switches.py
  - tests/trading/adapters/test_base_coverage.py
  - tests/trading/test_router.py
  - tests/trading/test_router_coverage.py
- Frontend:
  - 42 TypeScript errors total: 34 in test files, 8 in source files (all pre-existing).
  - 0 errors in swarm-related components (useSwarmEvents, OpinionFeed, SwarmActivityPanel, DevSwarm dashboard).

From now on:

1. Treat the Dev Swarm subsystem as its own coverage domain.
   - Maintain very high coverage on Dev Swarm code (target >=90%).
   - Add tests whenever new behavior is added or bugs are fixed in Dev Swarm.

2. Maintain a "Legacy Risk Matrix" for:
   - Hanging async IOCP tests.
   - Redis-dependent tests.
   - Contracts and compliance tests.
   - Other flaky or environment-sensitive suites.
   For each, track: status, root cause hypothesis, and recommended remediation steps.
   Reference: LEGACY_RISK_MATRIX.md

3. Adjust testing/coverage strategy:
   - Default coverage runs:
     - Include Dev Swarm tests and all non-hanging, non-broken backend tests.
     - Explicitly skip the known hanging async tests and failing legacy modules, tagging them with markers.
     - Quarantined tests auto-skipped via conftest.py hook on Windows.
   - Legacy remediation runs:
     - Run quarantined tests separately, non-gating, with longer timeouts or specialized Windows strategies.
     - Command: pytest -m "iocp_hang or windows_flaky_async" --no-header -q

4. When asked to "increase coverage":
   - First, prioritize adding tests in safe, fast, high-leverage areas (e.g., core business logic, Dev Swarm, critical backend modules that already pass).
   - Only work on quarantined/hanging tests if explicitly requested, and propose refactors to eliminate IOCP hangs, environment dependencies (like Redis), or brittle contract/compliance logic.
"""

# Legacy risk zones the swarm should be aware of but not touch unless directed
LEGACY_RISK_ZONES = {
    "iocp_hang": [
        "tests/core/test_connection_pool.py",
        "tests/core/test_health_monitor.py",
        "tests/streaming/test_stream_bus.py",
        "tests/consensus/test_consensus_coordinator.py",
    ],
    "redis_dependent": [
        "tests/core/test_cache.py",
        "tests/integration/test_integration_components.py",
    ],
    "contracts_broken": [
        "tests/contracts/test_intents.py",
    ],
    "compliance_broken": [
        "tests/compliance/test_audit_logger.py",
    ],
    "agent_interface_mismatch": [
        "tests/agents/core/test_market_analyst.py",
    ],
    "import_failures": [
        "tests/execution/test_persistent_book_extended.py",
        "tests/merid/risk/test_chaos.py",
        "tests/merid/risk/test_kill_switches.py",
        "tests/trading/adapters/test_base_coverage.py",
        "tests/trading/test_router.py",
        "tests/trading/test_router_coverage.py",
    ],
    "frontend_ts_errors": [
        "src/App.tsx",
        "src/components/charts/AgentOpinionChart.tsx",
        "src/hooks/useKafkaStream.ts",
        "src/utils/websocketWithBackoff.ts",
        "src/views/TradeFloor.tsx",
    ],
}

# DevTask templates for legacy remediation
LEGACY_REMEDIATION_TASKS = [
    {
        "description": "Fix Intent Contract Tests - Update test_intents.py to match current IntentPayload API",
        "target_files": ["tests/contracts/test_intents.py", "contracts/intents.py"],
        "success_criteria": "All 17 intent tests pass",
        "priority": 2,
        "estimated_effort": "medium",
    },
    {
        "description": "Add Redis Skip Guards - Add @pytest.mark.skipif to Redis-dependent tests when Redis unavailable",
        "target_files": ["tests/core/test_cache.py", "tests/integration/test_integration_components.py"],
        "success_criteria": "Tests skip gracefully when Redis is not available, pass when it is",
        "priority": 2,
        "estimated_effort": "small",
    },
    {
        "description": "Fix Market Analyst Agent Tests - Update to match current MarketAnalystAgent interface",
        "target_files": ["tests/agents/core/test_market_analyst.py", "agents/core/market_analyst.py"],
        "success_criteria": "All 6 market analyst tests pass",
        "priority": 3,
        "estimated_effort": "medium",
    },
    {
        "description": "Resolve React View Type Conflict - Consolidate View type into single source of truth",
        "target_files": ["web/react/src/App.tsx"],
        "success_criteria": "Zero TS errors in App.tsx, no View type conflicts",
        "priority": 3,
        "estimated_effort": "small",
    },
    {
        "description": "Clean Frontend Dead Code - Remove unused imports and variables in TS source files",
        "target_files": [
            "web/react/src/components/charts/AgentOpinionChart.tsx",
            "web/react/src/hooks/useKafkaStream.ts",
            "web/react/src/utils/websocketWithBackoff.ts",
            "web/react/src/views/TradeFloor.tsx",
        ],
        "success_criteria": "Zero TS6133 unused variable errors in source files",
        "priority": 4,
        "estimated_effort": "small",
    },
    {
        "description": "Refactor Connection Pool for Async Shutdown - Eliminate IOCP hang in ConnectionPool.shutdown()",
        "target_files": ["core/connection_pool.py", "tests/core/test_connection_pool.py"],
        "success_criteria": "test_connection_pool.py passes on Windows without hanging, iocp_hang marker removed",
        "priority": 3,
        "estimated_effort": "large",
    },
]
