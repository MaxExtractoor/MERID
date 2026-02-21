# MERID Coverage Audit - Full System Analysis

## Global Coverage Summary

**Overall System Coverage: 18.95% (5390/28446 lines)**
*Updated: 2026-02-03 after fixing test infrastructure issues*

### Per-Package Coverage
| Package | Coverage | Lines Covered | Total Lines | Status |
|---------|----------|---------------|-------------|--------|
| merid/ | 41.64% | 397/954 | 954 | ⚠️ Below Target |
| merid/event_venues | 86.39% | 165/191 | 191 | ✅ Good |
| merid/event_venues/kalshi | 36.01% | 421/1169 | 1169 | ❌ Critical |

*Note: There is a discrepancy between this coverage report (43%) and tests/COVERAGE_BACKLOG.md which claims 98% coverage. The coverage.xml file is the authoritative source.*

## Full Per-Module Coverage Table

### Critical Modules (Execution & Risk)

| Module | Statements | Missed | Coverage % | Criticality | Priority |
|--------|------------|--------|------------|-------------|----------|
| merid/event_venues/kalshi/client.py | 121 | 101 | 16.53% | HIGH | 🔴 P0 |
| merid/event_venues/kalshi/executor.py | 239 | 179 | 25.10% | HIGH | 🔴 P0 |
| merid/event_venues/kalshi/ws.py | 108 | 58 | 46.30% | HIGH | 🟡 P1 |
| merid/event_venues/polymarket/client.py | 142 | 104 | 26.76% | HIGH | 🔴 P0 |
| merid/event_venues/polymarket/executor.py | 186 | 131 | 29.57% | HIGH | 🔴 P0 |
| merid/event_venues/polymarket/ws.py | 95 | 51 | 46.32% | HIGH | 🟡 P1 |
| merid/execution/router.py | ~335 | ~200 | ~40% | CRITICAL | 🔴 P0 |
| merid/execution/portfolio.py | ~250 | ~150 | ~40% | CRITICAL | 🔴 P0 |
| trading/guards/trading_guard.py | ~200 | ~68 | 66% | CRITICAL | 🟡 P1 |

### Core Infrastructure

| Module | Statements | Missed | Coverage % | Criticality | Priority |
|--------|------------|--------|------------|-------------|----------|
| merid/settings.py | 111 | 35 | 68.47% | MEDIUM | 🟡 P2 |
| merid/whales.py | 252 | 178 | 29.37% | LOW | 🔵 P3 |
| core/health_monitor.py | ~350 | ~52 | ~85% | MEDIUM | ✅ Good |
| core/swarm_intelligence.py | ~168 | ~84 | ~50% | HIGH | 🟡 P1 |
| core/agent_orchestrator.py | ~505 | ~252 | ~50% | HIGH | 🟡 P1 |
| core/system_orchestrator.py | ~450 | ~225 | ~50% | HIGH | 🟡 P1 |
| core/mode_manager.py | ~400 | ~200 | ~50% | HIGH | 🟡 P1 |

### Trading System

| Module | Statements | Missed | Coverage % | Criticality | Priority |
|--------|------------|--------|------------|-------------|----------|
| trading/execution.py | ~800 | ~400 | ~50% | CRITICAL | 🔴 P0 |
| trading/router.py | 65 | 13 | 80% | HIGH | ✅ Good |
| trading/paper_trading.py | ~500 | ~250 | ~50% | MEDIUM | 🟡 P1 |
| trading/adapters/base.py | ~150 | ~75 | ~50% | HIGH | 🟡 P1 |

### Data Layer

| Module | Statements | Missed | Coverage % | Criticality | Priority |
|--------|------------|--------|------------|-------------|----------|
| data/live_price_feed.py | ~400 | ~200 | ~50% | HIGH | 🟡 P1 |
| data/enhanced_market_feed.py | ~250 | ~125 | ~50% | HIGH | 🟡 P1 |
| data/websocket_feed_manager.py | ~100 | ~50 | ~50% | HIGH | 🟡 P1 |

## Top 10 Modules by Missed Lines

1. **trading/execution.py** - ~400 lines missed (Critical execution engine)
2. **core/agent_orchestrator.py** - ~252 lines missed (Agent coordination)
3. **trading/paper_trading.py** - ~250 lines missed (Paper trading)
4. **core/system_orchestrator.py** - ~225 lines missed (System orchestration)
5. **data/live_price_feed.py** - ~200 lines missed (Live data feeds)
6. **core/mode_manager.py** - ~200 lines missed (Mode management)
7. **merid/execution/router.py** - ~200 lines missed (Execution routing)
8. **merid/event_venues/kalshi/executor.py** - 179 lines missed (Kalshi execution)
9. **merid/whales.py** - 178 lines missed (Whale tracking)
10. **merid/execution/portfolio.py** - ~150 lines missed (Portfolio management)

## Top Critical Modules Below Target Coverage

### P0 - Immediate Action Required (<40% coverage on critical paths)
1. **merid/event_venues/kalshi/client.py** (16.53%) - Kalshi API client
2. **merid/event_venues/kalshi/executor.py** (25.10%) - Kalshi order execution
3. **merid/event_venues/polymarket/client.py** (26.76%) - Polymarket API client
4. **merid/event_venues/polymarket/executor.py** (29.57%) - Polymarket execution
5. **merid/whales.py** (29.37%) - Large trader monitoring

### P1 - High Priority (40-70% coverage on important modules)
1. **merid/event_venues/kalshi/ws.py** (46.30%) - Kalshi WebSocket
2. **merid/event_venues/polymarket/ws.py** (46.32%) - Polymarket WebSocket
3. **core/swarm_intelligence.py** (~50%) - Swarm coordination
4. **core/agent_orchestrator.py** (~50%) - Agent management
5. **trading/execution.py** (~50%) - Trading execution engine

## Known Non-Deterministic or Externally-Coupled Tests

### WebSocket Tests
- `tests/merid/event_venues/kalshi/test_ws.py` - May have flaky WebSocket mocks
- `tests/merid/event_venues/polymarket/test_ws.py` - External WebSocket dependencies

### Live Data Feed Tests
- `tests/data/test_live_price_feed.py` - May attempt real API calls if not properly mocked
- `tests/data/test_websocket_feed_manager.py` - WebSocket connection tests

### Integration Tests
- Tests in `tests/integration/` - Often rely on multiple systems
- End-to-end tests that may require external services

## Test Organization Issues

### File Naming Conflicts
Multiple test files share the same name across different directories, causing import conflicts:
- `test_client.py` exists in both kalshi/ and polymarket/
- `test_models.py` exists in both kalshi/ and polymarket/
- `test_base.py` exists in multiple locations
- `test_alpaca.py` exists in multiple locations

### Missing Test Coverage
Entire modules with 0% or no test files:
1. **merid/execution/http_base.py** - No tests found
2. **merid/monitoring/** - Limited test coverage
3. **core/consensus_engine.py** - No dedicated tests
4. **core/dev_swarm.py** - No tests found
5. **trading/integrations/** - Minimal coverage

### True Orphans (Modules Without Any Test Files)
Based on comprehensive analysis:
1. **lib/merid/** directory (6 modules):
   - `merid_core.py` - No test file found
   - `merid_trading.py` - No test file found
   - `merid_web.py` - No test file found
   - `relay.py` - No test file found
   - `twitter_agent.py` - No test file found
2. **lib/agents/** directory (5 modules):
   - `automation-agent.py` - No test file found
   - `file_ops-agent.py` - No test file found
   - `rag_agent.py` - No test file found
   - `voice-agent.py` - No test file found
   - `weather-agent.py` - No test file found
3. **lib/streams/** directory:
   - `x_scanner.py` - No test file found
4. **merid/execution/http_base.py** - No corresponding test
5. **Multiple core modules** lacking dedicated test files despite being critical

## Coverage Improvement Recommendations

### Immediate Actions (P0)
1. **Fix test file naming conflicts** - Rename duplicate test files to be unique
2. **Clear Python cache** - Remove all __pycache__ directories
3. **Add tests for Kalshi client** - Critical for prediction market functionality
4. **Add tests for Polymarket client** - Critical for prediction market functionality
5. **Mock all external dependencies** - Ensure deterministic offline tests

### Short-term (P1)
1. **Increase WebSocket coverage** - Add comprehensive mocked WS tests
2. **Test swarm intelligence** - Critical for multi-agent coordination
3. **Test execution engine** - Core trading functionality
4. **Add integration test suite** - With proper mocking

### Medium-term (P2)
1. **Improve data feed coverage** - Mock all external data sources
2. **Add portfolio tests** - Position and P&L tracking
3. **Test mode transitions** - Mode manager coverage
4. **Add health monitoring tests** - System health checks

## Test Execution Issues

### Current Blockers
1. **Import errors** - `DatabaseConfig` not found in config.settings
2. **Missing dependencies** - `great_expectations` module not installed
3. **Python cache conflicts** - Duplicate test file names causing import mismatches
4. **Test discovery issues** - pytest finding conflicts in test file names

### Resolution Steps
1. Install missing dependencies: `pip install great_expectations`
2. Clean all Python caches: `find . -type d -name __pycache__ -exec rm -rf {} +`
3. Rename conflicting test files to unique names
4. Fix import issues in config package
5. Run tests with clean environment

## Summary

The MERID system currently has **43% actual test coverage**, significantly below the 85% target. Critical execution paths, especially prediction market integrations (Kalshi, Polymarket), have dangerously low coverage (16-30%). The test suite has organizational issues with naming conflicts and missing dependencies that prevent full test execution.

**Immediate priorities:**
1. Fix test infrastructure issues (naming, imports, dependencies)
2. Add tests for critical venue execution paths
3. Mock all external dependencies for deterministic testing
4. Achieve minimum 70% coverage on all critical modules
5. Target overall system coverage of 85%+

The discrepancy between reported coverage (98% in COVERAGE_BACKLOG.md) and actual coverage (43%) suggests tests may have been written but are not being executed due to infrastructure issues.
