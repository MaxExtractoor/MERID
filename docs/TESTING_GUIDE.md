# MERID — Testing Guide

Testing strategy for the Kalshi swarm intelligence platform.

---

## Quick Commands

```bash
make golden-path              # full test suite
make preflight                # tests + readiness + drift audit + risk context
make risk-context             # print live risk state JSON
make pm-test                  # prediction market tests only
make pipeline-test            # pipeline tests only
pytest tests/ -v --tb=short   # run tests directly
```

---

## Test Suites

| Suite | File | Tests |
|-------|------|-------|
| E2E Golden Path | `tests/test_e2e_golden_path.py` | 25 |
| Signal Layer | `tests/test_signal_layer.py` | 98 |
| Live Feeds | `tests/test_live_feeds.py` | 26 |
| Prediction Markets | `tests/test_prediction_markets.py` | 109 |
| Unified Pipeline | `tests/test_unified_pipeline.py` | 75 |
| Canonical Agents | `tests/test_canonical_agents.py` | 73 |
| Hardening | `tests/test_hardening.py` | 84 |
| Forecasters | `tests/test_forecasters.py` | 22 |
| Sprint D–G | `tests/test_sprint_d_g.py` | 53 |
| Sprint H–I | `tests/test_sprint_h_i.py` | 44 |
| Sprint M | `tests/test_sprint_m.py` | 55 |
| Sprint N–O | `tests/test_sprint_n_o.py` | 46 |
| Sprint Q–R | `tests/test_sprint_q_r.py` | 36 |
| Sidebar Wiring | `tests/test_sidebar_wiring.py` | 36 |

---

## API Smoke Tests

Start the server (`make serve`) and test key endpoints:

```bash
# Health check
curl http://localhost:8000/healthz

# Kalshi markets
curl http://localhost:8000/api/v1/kalshi/markets

# Pipeline status
curl http://localhost:8000/api/v1/pipeline/summary

# Risk context
curl http://localhost:8000/api/v1/pipeline/risk-context

# Operator summary
curl http://localhost:8000/api/operator/summary

# Kill switch status
curl http://localhost:8000/risk/status
```

Full interactive API explorer at [http://localhost:8000/docs](http://localhost:8000/docs).

---

## Frontend Verification

Start the dashboard (`cd web/react && npm run dev`) and verify:

1. **All 17 views load** — Click through every sidebar item
2. **No console errors** — Open DevTools → Console
3. **API polling works** — Network tab shows periodic requests
4. **Kill switch responds** — Toggle in Kill Switch view
5. **Command palette works** — Press `Ctrl+K`, search for views

### Frozen View Checklist

- [ ] Overview
- [ ] Terminal (KalshiTerminal)
- [ ] Markets (KalshiDashboard)
- [ ] Portfolio (KalshiPortfolio)
- [ ] Positions (deep-link to Portfolio)
- [ ] Orders (deep-link to Portfolio)
- [ ] Agent Grid (KalshiGrid)
- [ ] Swarm Matrix (SwarmConsensus)
- [ ] Performance (KalshiPerformance)
- [ ] Calibration (CalibrationDashboard)
- [ ] Lane Control
- [ ] Fear/Greed (KalshiSentiment)
- [ ] Vol & Sizing (KalshiVolDashboard)
- [ ] Operator
- [ ] Kill Switch
- [ ] Logs
- [ ] Settings

---

## Integration Test: Paper Trading Flow

1. `make serve` + `cd web/react && npm run dev`
2. Open Overview — verify health status
3. Navigate to Markets — browse Kalshi markets
4. Navigate to Agent Grid — check agent signals
5. Navigate to Swarm Matrix — verify consensus
6. Navigate to Terminal — check orderbook loads
7. Navigate to Portfolio — verify positions/orders tabs
8. Navigate to Kill Switch — verify toggle works
9. `make loop-start-execute` — start paper trading
10. Return to Portfolio — verify paper positions appear

---

## Pre-Merge Testing

Before every merge:

```bash
make preflight
```

This runs:

- Full golden path test suite
- Readiness auditor
- Codebase drift audit
- RiskContext snapshot

All must pass before merging.

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Tests fail with import errors | `pip install -r requirements.txt` |
| API returns 500 | Check `make serve` terminal for traceback |
| Frontend shows loading forever | Verify backend is running on port 8000 |
| Stale test data | `MERID_FRESH_START=1 make serve` |
| Flaky async tests | Run with `pytest -x --timeout=30` |
| WS/gate tests green alone, red in batch | Missing singleton reset fixture — see *Kalshi / WS / Chokepoint Testing — Fixture Hygiene* below |

---

## Kalshi / WS / Chokepoint Testing — Fixture Hygiene

The Kalshi execution path (intent → gate → router → executor → WS) is
wired together with a handful of **process-wide singletons**.  Their
state persists across tests unless explicitly reset, which produces a
recurring pattern: *"tests pass individually, fail when batched with
others, and pass again when run in isolation"*.  This section
documents the singletons and the reset fixtures that keep their
behavior deterministic under pytest.

If you are adding or modifying a test that touches WebSocket reconnect
logic, the pre-trade gate, or contract leases, **read this section
first**.

### Singletons in the scalper chokepoint slice

| Singleton | Module | Reset helper | Why it matters in tests |
|-----------|--------|--------------|-------------------------|
| `FaultManager` | `core/fault_manager.py` | `reset_fault_manager()` | Tracks per-venue circuit-breaker state; once opened, `KalshiWebSocket._reconnect()` short-circuits and silently skips subsequent reconnect attempts. Leaking state across tests makes reconnect/backoff assertions flake. |
| `PreTradeGate` | `merid/event_venues/kalshi/order_gate.py` | `reset_pre_trade_gate_for_testing()` | Owns the idempotent `OrderRecord` store; stale PENDING records from a prior test block later dedup/reservation logic with `duplicate:pending` rejections. |
| `ContractLeaseRegistry` | `merid/event_venues/kalshi/contract_lease.py` | `reset_contract_lease_registry_for_testing()` | Holds per-(venue, contract, side, strategy) leases; a held lease from a prior test will reject the router with `lease_conflict`. |

A few other singletons live alongside these (e.g. the order-group
manager, risk kill switch) — if you discover one that affects your
tests, add it to this table in the same PR that fixes the flake.

### Canonical reset fixture

The standard form is an **autouse** fixture that resets the singleton
before and after each test, scoped to the module that needs it:

```python
import pytest
from core.fault_manager import reset_fault_manager


@pytest.fixture(autouse=True)
def _isolate_fault_manager():
    """Reset the process-wide FaultManager around each test.

    KalshiWebSocket._reconnect consults can_attempt_reconnect("kalshi")
    and short-circuits once the venue circuit breaker opens. Without
    this fixture, failure state from earlier tests leaks into later
    ones and silently blocks reconnects.
    """
    reset_fault_manager()
    try:
        yield
    finally:
        reset_fault_manager()
```

For gate + lease tests, reset **both** together — they're wired in
series:

```python
from merid.event_venues.kalshi.order_gate import reset_pre_trade_gate_for_testing
from merid.event_venues.kalshi.contract_lease import reset_contract_lease_registry_for_testing


@pytest.fixture(autouse=True)
def _isolate_gate_and_lease_singletons():
    reset_pre_trade_gate_for_testing()
    reset_contract_lease_registry_for_testing()
    try:
        yield
    finally:
        reset_pre_trade_gate_for_testing()
        reset_contract_lease_registry_for_testing()
```

### Checklist for new tests

If your test touches any of the following, it **must** either live in
a module that already defines the appropriate autouse reset fixture
or define an equivalent one:

- [ ] WebSocket connect / reconnect / backoff logic → `FaultManager` reset.
- [ ] Any `route_order_async` / `_run_pre_trade_gate` / `PreTradeGate` interaction → gate + lease reset.
- [ ] Contract lease acquisition or release directly → lease reset.
- [ ] Anything that exercises a "duplicate:pending" or "lease_conflict" rejection path → both.

Reference implementations:

- `tests/event_venues/kalshi/test_ws.py`
- `tests/event_venues/kalshi/test_ws_reconnect.py`
- `tests/event_venues/kalshi/test_ws_resilience.py`
- `tests/event_venues/kalshi/test_pre_trade_gate_dual_pending_regression.py`

### Chokepoint invariant tests (enforcement)

Two invariant tests guard the scalper chokepoint slice.  They're cheap
to run, they fail loudly, and they're the first thing to check when
touching this code:

- `tests/trading/test_execution_chokepoint.py` — forbids new
  production bypasses of `route_order_async` (direct venue submit
  patterns).  Each forbidden pattern is allow-listed per-file at its
  current count; any new occurrence fails the test.
- `tests/regression/test_no_silent_except_in_scalper_slice.py` —
  AST-based ratchet on `except Exception: pass` (and equivalent silent
  bodies) in the chokepoint slice.  The pattern hid the dual-PENDING
  gate-update bug for months; the ratchet prevents it from returning.
  Run `python -m tests.regression.test_no_silent_except_in_scalper_slice`
  to print a fresh baseline if you re-scope the slice or do a cleanup
  sweep.

When a ratchet fails, the preferred fix order is:

1. Refactor the handler to log + emit a metric (or bump a counter).
2. Narrow the caught exception type.
3. Re-raise a more specific exception.
4. Last resort — justify via inline comment and bump the allowlist.

Edits welcome: if you discover another singleton, cache, or
class-of-silent-failure affecting tests in this area, add it here in
the same PR that fixes the flake.

---

Last updated: 2026-04-21.
