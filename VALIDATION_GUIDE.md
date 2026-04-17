# VALIDATION GUIDE

**Purpose**: How to run validation gates and interpret results.

## Quick Reference

```bash
# Dry-run (basic wiring check, ~2 minutes)
python scripts/run_paper_gate.py --dry-run

# Full 30-minute paper gate
python scripts/run_paper_gate.py --duration 1800 --gate-id pre_live_check

# With output to specific directory
python scripts/run_paper_gate.py --duration 1800 --gate-id pre_live_check --output-dir ./validation_results
```

## What a Validation Gate Does

1. **Starts backend** in paper mode with full monitoring
2. **Waits for ready state** (health endpoint returns 200 with `startup_complete=true`)
3. **Monitors for N minutes** (default: 30), sampling every 30 seconds
4. **Records**:
   - P50, P95, P99 event-loop lag
   - `degraded` flag status
   - `startup_complete` and `agents_ready` flags
5. **Verifies** all pass criteria hold throughout
6. **Outputs JSON report** with verdict (PASS/FAIL)

## Pass Criteria (All Must Hold)

| Criterion | Threshold | Consequence if Failed |
|-----------|-----------|------------------------|
| P95 lag | < 500ms | FAIL - Event loop blocking |
| `degraded` flag | `false` | FAIL - System unhealthy |
| High-lag profiles | 0 captured | FAIL - Blocking operations detected |
| Health HTTP | 200 OK | FAIL - Backend not responding |
| `agents_ready` | `true` | FAIL - Agents not operational |

## Interpreting Results

### PASS

```json
{
  "gate_id": "pre_live_check",
  "duration_minutes": 30,
  "verdict": "PASS",
  "samples": 60,
  "p95_max": 234,
  "degraded_samples": 0,
  "high_lag_profiles": 0
}
```

**Meaning**: System healthy for 30 minutes. Safe to proceed to next phase.

### FAIL (P95 Exceeded)

```json
{
  "verdict": "FAIL",
  "failures": [
    "2026-03-31T12:00:00Z: P95=850ms >= 500ms threshold",
    "2026-03-31T12:01:30Z: degraded=true"
  ]
}
```

**Action**:
1. Check `lag_profiles.json` for blocking operations
2. Review `fix_history.md` for similar patterns
3. Identify root cause (tight loops, blocking I/O)
4. Apply fix and re-run gate
5. Document in `fix_history.md` as ANOMALY

### FAIL (Degraded Persisted)

**Meaning**: System returned 200 OK but marked itself degraded.

**Action**: Same as P95 exceeded - investigate why `degraded=true`.

## Artifacts and Documentation

Each gate produces:
- **JSON report**: `validation_gate_{gate_id}_{timestamp}.json`
- **Log excerpt**: Last 500 lines of backend logs
- **Health samples**: All individual sample data

**Link in `fix_history.md`**:
```markdown
#### Validation Gate
- **Gate ID**: pre_live_check
- **JSON**: `./validation_results/validation_gate_pre_live_check_20260331_120000.json`
- **Verdict**: PASS
- **P95 max**: 234ms
- **Samples**: 60/60 healthy
```

## VALIDATION_MODE — Infra Smoke Test vs Production Gate

**VALIDATION_MODE** (`MERID_VALIDATION_MODE=1`) is an **infrastructure smoke test**, not a production-readiness gate.

### What it disables (25+ services)

The following are all **skipped** when this flag is set:

- **MeridLoop** — the core swarm tick cycle (every ~5 s, each tick 250–400 ms in production)
- **35 KalshiTradingAgents** — constant `_run_loop` background tasks
- **AgentMesh / 8 StreamingAgents** — `_run_loop` tasks, top offenders in lag profiles
- **KalshiWebSocketBridge** — 669+ ticker subscriptions
- **KalshiContinuousTrader** — continuous market-trading loop
- **KalshiInsightPipeline** — 11 category loops
- **EnhancedConsensusCoordinator, MarketMoodBus, SentimentBus, HashtagMonitor** (HashtagMonitor caused 39 s+ startup lag)
- **RTIFeedService, KalshiFillsPoller, TickerCollector**
- **SystemOrchestrator, Consensus engine streaming**
- **All reconciliation loops** (startup + periodic + venue)
- **Matching engine and venue registry initialisation**
- **Intelligence news aggregation, API live data feed**
- **AgentOrchestrator loop** (`core/agent_orchestrator.py:105` — started but `start()` returns immediately)
- **InsightPipeline + OutcomeResolver inside AgentGrid** (`agent_grid.py:380,420` — defensive; grid itself is already skipped)
- **HashtagMonitor inside MeridLoop** (`loop.py:1681` — defensive; loop itself is already skipped)
- **`agents_real.py` module-level**: `agent_mesh = None` — all `/api/agents/*` routes that reference agent_mesh return empty/errors in validation mode
- **CFGI fear/greed refresh loop** — uses sync `requests.get()` for 5 assets; blocks event loop ~900ms per call every 5 minutes (confirmed in gate logs)
- **KalshiMarketCatalog periodic refresh** (5-min loop cancelled after initial load) — 20+ sequential Kalshi REST calls, 7s total, causes 1390ms lag spike every 5 min; initial catalog data is retained for validation

### What still runs

KalshiVenueClient (HTTP connect/auth), KalshiMarketCatalog (HTTP market fetch), KalshiMarketCache, CryptoAlertRouter, WatchdogCoordinator, AlertManager, AuditTrail, HealthMonitor, NotificationManager, CFGI refresh loop, LoopLagMonitor.

### Expected metrics in VALIDATION_MODE

| Metric | Value | Meaning |
|--------|-------|---------|
| Steady-state P95 | ~15–20 ms | Almost-empty event loop — **not** production load |
| Active asyncio tasks | ~10–15 | Production has ~90–100 tasks |
| Startup P95 (first sample) | 3–5 s | KalshiVenueClient.connect() + KalshiMarketCatalog.start() HTTP calls |

### Health fabrications in VALIDATION_MODE

`/api/health` returns these fields as **synthetic values** (not real):

| Field | Fabricated value | Reality |
|-------|-----------------|---------|
| `agent_grid.startup_complete` | `true` | No agents running |
| `agent_grid.agents_ready` | `true` | No agents running |
| `agent_grid.ws_ready` | `true` | WS bridge not started |
| `kalshi_circuit.open` | `false` | Circuit not queried |
| `merid_loop` failure | suppressed | Loop intentionally skipped |

Only `event_loop_lag` stats and `kill_switch` are genuine.

### Gate interpretation

A gate run in VALIDATION_MODE proves:
- HTTP path responds correctly
- KalshiClient + Catalog connect and load data
- LoopLagMonitor records clean readings on the stripped loop
- Nothing in the infra-only set of services is blocking the event loop

It does **not** prove anything about the trading stack. Do not use it as a production readiness gate.

### Startup spike — known and accepted

The first gate sample will show P95 3–5 s. This comes from `KalshiVenueClient.connect()` and `KalshiMarketCatalog.start()` running on the event loop before uvicorn yields. It is a one-time cost. All subsequent samples should show P95 < 50 ms.

The gate runner clears startup profiles before sampling begins (`DELETE /health/event_loop/profiles` immediately after ready-wait) so this spike does not count against the gate.

---

## CI/CD Integration

### GitHub Actions Example

```yaml
- name: Paper Gate (Dry Run)
  run: python scripts/run_paper_gate.py --dry-run
  
- name: Paper Gate (Full)
  if: github.event_name == 'workflow_dispatch'
  run: |
    python scripts/run_paper_gate.py \
      --duration 1800 \
      --gate-id "ci_${{ github.run_id }}" \
      --output-dir ./results
    
- name: Upload Results
  uses: actions/upload-artifact@v3
  with:
    name: validation-results
    path: ./results/
```

### Manual Staging Gate

For heavier checks before live transitions:
```bash
python scripts/run_paper_gate.py \
  --duration 1800 \
  --gate-id "staging_pre_live" \
  --output-dir /var/log/merid/validation
```

## Troubleshooting

### "Server did not start within 60 seconds"

- Check backend logs for startup errors
- Verify env vars are set correctly
- Check port 8011 is not already in use

### "No valid samples collected"

- Health endpoint may be returning errors
- Check `/api/health` manually: `curl http://127.0.0.1:8011/api/health`

### High-lag profiles captured but gate says PASS

- Profiles may be from previous runs
- Clear profiles before gate: restart backend with fresh state
- Or check profile timestamps to confirm they're from current run

---

*For operational emergencies, see `/diagnostic-runbook`.*

---

## Tick-Level Metrics (Phase 3)

With the tick processing optimizations, additional per-step metrics are available in tick summaries.

### Accessing Tick Metrics

Tick summaries now include `step_timings_ms` which tracks the duration of each major step:

```python
# From tick summary
summary = await loop.tick()
print(summary["step_timings_ms"])
# {
#   "features": 245.3,
#   "consensus": 180.5,
#   "liquidity": 420.1,
#   "notify": 15.2
# }
```

### Per-Step Budgets

| Step | Target Budget | Warning Threshold |
|------|---------------|-------------------|
| features | 250ms | 1000ms |
| consensus | 200ms | 800ms |
| liquidity | 500ms | 2000ms |
| arb_scan | 100ms | 500ms |
| execution | 100ms | 500ms |
| notify | 50ms | 250ms |

### Tick Overlap Detection

The loop now tracks `_tick_in_progress` to prevent overlapping tick execution:

- If a tick is already running, subsequent calls return:
  ```json
  {"tick": "skipped", "reason": "tick_in_progress", "actions": []}
  ```
- This is logged at WARNING level for operator visibility
- Tests can use `force=True` to override (for testing overlap scenarios)

### Performance Expectations

With optimizations applied:

| Metric | Before | Target | Notes |
|--------|--------|--------|-------|
| Feature refresh | ~1500ms | ~300ms | Batched (1→2→5 symbols) |
| Liquidity sweep | ~3000ms | ~1000ms | Parallel (2 concurrent) |
| Consensus cycle | ~800ms | ~400ms | Capped (max 10 symbols) |
| Total tick | ~500-800ms | ~250-400ms | Varies by enabled steps |

### Investigating Slow Ticks

If ticks exceed the 30-second warning threshold:

1. Check `step_timings_ms` to identify the slowest step
2. Look for `step_timeout:{name}` in actions - indicates timeout
3. Check `step_error:{name}` in actions - indicates failure
4. Review debug logs for `merid.loop.action_ms` and `merid.loop.sub_timings`

Example slow tick investigation:
```
WARNING Slow tick #42: 35000ms (threshold 30000ms). Actions: [
  'features_refreshed:5symbols',
  'step_timeout:liquidity',
  'consensus_check:forced=3',
  'kalshi_agents:12signals'
]
```

This indicates the liquidity step timed out (20s timeout), suggesting orderbook fetch issues.

---
