# 15m Lean Kalshi Stack

**Production Entrypoint for `kalshi_crypto_15m_v2` Profile**

This document is the source of truth for the 15m lean stack. All future changes must respect the invariants and architecture described here.

---

## Scope and Intent

The 15m lean stack is the **only production path** for the `kalshi_crypto_15m_v2` profile. It is designed as a minimal, self-contained trading system with zero dependencies on legacy subsystems.

**Scope:**
- Trades **only** Kalshi 15-minute crypto contracts
- Supports **5 assets**: BTC, ETH, SOL, XRP, DOGE
- Uses **live bankroll service** (no paper trading engine)
- Runs **5 agents**: BTC_15M, ETH_15M, SOL_15M, XRP_15M, DOGE_15M

**Explicitly NO dependencies on:**
- `core.paper_session` (PaperSession, PaperSessionState)
- `swarm.agent_registry` (AgentRegistry, decentralized identity)
- `agents.reflection.integration` (ReflectionSystem)
- `merid.event_venues.kalshi.deployment` (DeploymentController, paper→live promotion)
- PM runtime (orchestrator, canonical agents, consensus aggregation)

---

## Key Components

### Core Entrypoint

**`web/main_15m_lean.py`** - FastAPI application
- Health-triggered startup pattern (replaces unreliable FastAPI lifespan events)
- `/api/v1/health` is the only startup trigger
- Observability endpoints with schema versions
- No legacy router includes
- Runtime profile enforcement (raises RuntimeError if profile != `kalshi_crypto_15m_v2`)

### Venue Layer

**`merid/event_venues/kalshi/client.py`** - KalshiVenueClient
- REST API client with circuit breaker
- WebSocket bridge integration
- **Mode flags**: `is_demo` (bool), `is_live` (bool) derived from `config.use_demo`
- RSA-PSS authentication
- Demo + production mode support

**`merid/event_venues/kalshi/bankroll_service_v2.py`** - BankrollServiceV2
- Unified bankroll store for live trading
- **Mode flags**: `is_demo` (bool), `is_live` (bool) derived from client config
- Bankroll state refresh with staleness detection
- Per-asset and global risk caps

**`merid/event_venues/kalshi/ws_bridge.py`** - WebSocket bridge
- Real-time market data streaming
- Orderbook updates
- Position and fill events
- Snapshot persistence for crash recovery

**`merid/event_venues/kalshi/market_catalog.py`** - Market catalog
- Kalshi universe discovery
- 15M series ticker filtering (KXBTC15M, KXETH15M, etc.)
- Liquidity and coverage tracking

**`merid/event_venues/kalshi/kalshi_risk.py`** - KalshiRiskConfig
- Venue-level risk configuration (canonical source)
- Per-asset risk limits
- Global risk limits
- Entry window constraints

### Agent Grid

**`merid/prediction/agent_grid_15m.py`** - Lean AgentGrid
- Minimal, self-contained agent grid
- **Exactly 5 agents**: BTC_15M, ETH_15M, SOL_15M, XRP_15M, DOGE_15M
- No PM runtime dependencies
- Direct venue adapter integration
- Autonomous gate enforcement (window match, freshness, spread, depth)

### Execution Loop

**`merid/loop_15m.py`** - 15m execution loop
- 15-minute interval trading cycle
- Agent grid execution
- Position and risk monitoring
- Error tracking and recovery

### Edge Computation

**`data/unified_spot_service.py`** - Spot price service
- External spot price feeds (CME CF Crypto Indices)
- Powers UnifiedEdgeComputer
- Real-time price updates

### Runtime Invariants

**`merid/kalshi_15m_runtime_check.py`** - Production invariants checker
- Profile validation (`kalshi_crypto_15m_v2` only)
- Mode consistency checks (is_demo/is_live)
- Legacy subsystem detection
- Startup state validation
- App state component verification
- Unified edge config validation
- Agent config consistency (exactly 5 agents)

---

## Startup Lifecycle

The 15m lean stack uses a **health-triggered startup pattern** instead of FastAPI lifespan events (which are unreliable).

### Trigger

Call `/api/v1/health` once to trigger startup. This endpoint calls `_run_startup_phases_v20260530()` with a 120-second timeout.

### Phase 1: Venue Initialization

1. **KalshiVenueClient** - Initialize REST client with credentials
2. **MarketCatalog** - Discover and filter 15M markets
3. **WebSocket Bridge** - Connect to real-time data streams
4. **FillsLedger** - Initialize fill tracking
5. **BankrollServiceV2** - Initialize bankroll state
6. **OrderRouter** - Initialize order routing logic
7. **UnifiedSpotService** - Connect to spot price feeds

### Phase 2: Trading Components

1. **AgentGrid15m** - Build 5-agent grid (BTC/ETH/SOL/XRP/DOGE)
2. **KalshiRiskConfig** - Initialize risk configuration (type assertion enforced)
3. **Loop15m** - Attach execution loop to app state

### Startup State

Startup progress is tracked in `startup_state`:
- `started`: True when startup begins
- `completed`: True when all phases finish successfully
- `failed`: True if any phase fails
- `error`: Error message if failed
- `started_at`: Timestamp when startup began
- `completed_at`: Timestamp when startup finished

---

## Observability Endpoints

All observability endpoints return structured JSON with schema versions for API contract tracking.

### `/api/v1/health`

System health and startup status.

```json
{
  "status": "ok",
  "api_version": "15m_v2",
  "health_impl": "health_v3_20260530_0940",
  "health_debug": "main_15m_lean_v4_1015",
  "startup_started": true,
  "startup_completed": true,
  "startup_failed": false,
  "error": null,
  "started_at": "2026-05-30T14:00:00Z",
  "completed_at": "2026-05-30T14:01:30Z"
}
```

### `/api/v1/self-check`

Production invariants check. Returns structured JSON with profile, mode, startup, components, and legacy sections.

```json
{
  "profile": {
    "name": "kalshi_crypto_15m_v2",
    "env": "production",
    "expected": "kalshi_crypto_15m_v2",
    "valid": true
  },
  "mode": {
    "is_demo": false,
    "is_live": true,
    "consistent": true
  },
  "startup": {
    "completed": true,
    "trading_enabled": false
  },
  "components": {
    "agent_grid_15m": true,
    "loop_15m": true,
    "bankroll": true,
    "kalshi_client": true
  },
  "legacy": {
    "modules_loaded": [],
    "count": 0
  },
  "invariants": {
    "all_passed": true,
    "checks": {
      "profile_and_env": {"passed": true, "message": "..."},
      "no_legacy_subsystems": {"passed": true, "message": "..."},
      "startup_state": {"passed": true, "message": "..."},
      "app_state_components": {"passed": true, "message": "..."},
      "unified_edge_config": {"passed": true, "message": "..."},
      "agent_config_consistency": {"passed": true, "message": "..."}
    }
  }
}
```

**Section meanings:**
- **profile**: Validates MERID_PROFILE is `kalshi_crypto_15m_v2`
- **mode**: Checks is_demo/is_live flags are consistent (not both true)
- **startup**: Reports startup completion and trading enabled state
- **components**: Verifies all required app state components are present
- **legacy**: Lists any legacy modules loaded (should be empty)
- **invariants**: Results of all runtime invariant checks

### `/api/v1/agents`

Agent grid status with schema version.

```json
{
  "schema_version": "1.0.0",
  "initialized": true,
  "agents": [
    {
      "name": "BTC_15M",
      "enabled": true,
      "open_positions": 2,
      "last_signal_ts": "2026-05-30T14:05:00Z",
      "last_signal_age_seconds": 30,
      "risk_budget_used": 0.45,
      "is_zombie": false
    },
    ...
  ],
  "summary": {
    "total": 5,
    "enabled": 5,
    "disabled": 0,
    "zombies": 0
  }
}
```

**Zombie detection**: An agent is marked as zombie if enabled but no signal in last 15 minutes.

### `/api/v1/risk-snapshot`

Bankroll and risk state with schema version.

```json
{
  "schema_version": "1.0.0",
  "initialized": true,
  "bankroll": {
    "equity_usd": 10000.00,
    "available_cash_usd": 8500.00,
    "open_pnl_usd": 1500.00
  },
  "risk_env": {
    "per_asset_caps": {
      "BTC": {"max_notional_usd": 2000, "current_notional_usd": 500},
      ...
    },
    "global_caps": {
      "max_total_notional_usd": 10000,
      "current_total_notional_usd": 2500
    },
    "utilization": {
      "BTC": 0.25,
      "ETH": 0.30,
      ...
    }
  }
}
```

### `/api/v1/loop-status`

Execution loop status with status string.

```json
{
  "status": "running",
  "running": true,
  "last_cycle_at": "2026-05-30T14:05:00Z",
  "cycle_duration_ms": 150,
  "error_count": 0
}
```

**Status strings:**
- `starting`: Loop not yet running, no cycles completed
- `running`: Loop active, cycles progressing
- `stopped`: Loop not running
- `error`: Loop has >10 errors, may need intervention

---

## Invariants (Never Violate)

These invariants are enforced by runtime checks and tests. Any violation will cause startup failure or test failure.

1. **Profile Invariant**: `MERID_PROFILE` must be exactly `kalshi_crypto_15m_v2` for `main_15m_lean.py`
2. **Agent Count Invariant**: Exactly 5 enabled agents (BTC_15M, ETH_15M, SOL_15M, XRP_15M, DOGE_15M)
3. **No Legacy Imports**: No imports of PaperSession, AgentRegistry, or ReflectionSystem in lean stack
4. **Mode Consistency**: `is_demo` and `is_live` cannot both be true
5. **Risk Config Type**: Risk config must be `KalshiRiskConfig` from `merid.event_venues.kalshi.kalshi_risk`
6. **Startup Completion**: All components must be initialized before trading
7. **Legacy Modules Empty**: Legacy module list in `/self-check` must be empty
8. **Schema Versions**: All observability endpoints must return schema version field

---

## Tests and CI

### Smoke Tests

**`tests/test_15m_lean_smoke.py`** - 13 smoke tests for the lean stack:
1. Import `main_15m_lean:app` without errors
2. `/health` endpoint returns expected structure
3. `/self-check` returns structured JSON with all sections
4. `/agents` returns schema version
5. `/risk-snapshot` returns schema version
6. `/loop-status` returns status string
7. No legacy router includes in app routes
8. Profile truth in settings
9. Kalshi client has is_demo/is_live properties
10. Bankroll service has is_demo/is_live properties
11. Runtime check module exists with required functions
12. Agent config consistency check validates 5 agents
13. All 5 agent names present in config

Run with:
```bash
pytest tests/test_15m_lean_smoke.py -v
```

### CI Workflow

**`.github/workflows/kalshi-15m-ci.yml`** - GitHub Actions workflow
- **kalshi-15m-smoke job**: Runs smoke tests with `MERID_PROFILE=kalshi_crypto_15m_v2`
- **kalshi-15m-tests job**: Runs Kalshi 15m specific tests

This workflow is the guardrail for the 15m production stack. All PRs to main/develop must pass these tests.

### Legacy Tests

Legacy tests are marked with `pytest.mark.legacy` and can be excluded with `-m "not legacy"`:
- `tests/test_paper_session.py` - PaperSession tests (not used by 15m stack)
- `tests/test_canonical_agents.py` - CanonicalAgentRegistry tests (not used by 15m stack)
- `tests/test_audit_fix_regressions.py` - ReflectionSystem tests (not used by 15m stack)
- `tests/test_audit_bug_fixes.py` - PaperSession tests (not used by 15m stack)
- `tests/test_agent_wiring.py` - CanonicalAgentRegistry tests (not used by 15m stack)
- `tests/test_kalshi_crypto_e2e_coverage.py` - PaperSession tests (not used by 15m stack)
- `tests/trading/test_lifecycle_bug_regressions.py` - PaperSession tests (not used by 15m stack)
- `tests/test_risk_audit_regressions.py` - PaperSession tests (not used by 15m stack)
- `tests/test_realfirst_endpoints.py` - AgentRegistry tests (not used by 15m stack)
- `tests/test_prediction_audit_regressions.py` - PaperSession/PaperLadder tests (not used by 15m stack)
- `tests/test_agent_grid_audit.py` - PaperSession tests (not used by 15m stack)
- `tests/core/test_paper_session.py` - PaperSessionState tests (not used by 15m stack)

---

## Change Management

### Contributing to the 15m Stack

Any change touching the following files must:
- Update this documentation if behavior changes
- Keep `/api/v1/self-check` green (all invariants passing)
- Pass `kalshi-15m-smoke` CI workflow

**Protected files:**
- `web/main_15m_lean.py`
- `merid/event_venues/kalshi/*`
- `merid/prediction/agent_grid_15m.py`
- `merid/loop_15m.py`
- `merid/kalshi_15m_runtime_check.py`

### New Features

Any new feature must:
- Declare which profiles it applies to
- For `kalshi_crypto_15m_v2`, obey the same invariants:
  - No legacy imports (PaperSession, AgentRegistry, ReflectionSystem)
  - No paper trading paths
  - Clear mode semantics (is_demo/is_live flags)
  - Schema version on observability endpoints

### Documentation Updates

When adding new endpoints or changing behavior:
1. Update the corresponding section in this document
2. Add example JSON response
3. Update invariants list if new constraints are introduced
4. Add smoke test for new behavior

---

## Related Documentation

- [`docs/15m_runbook.md`](15m_runbook.md) - Operational runbook for running and verifying the 15m stack
- [`docs/legacy_overview.md`](legacy_overview.md) - Legacy systems documentation (out of scope for 15m stack)
- [`README.md`](../README.md) - Project README with 15m Lean Stack section
- [`merid/kalshi_15m_runtime_check.py`](../merid/kalshi_15m_runtime_check.py) - Runtime invariants implementation
