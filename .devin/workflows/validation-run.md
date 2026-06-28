---
description: Run 30-minute paper validation gate to confirm event-loop lag fixes
---

# /validation-run

Run the MERID backend in **paper mode** and execute a 30‑minute validation gate to confirm that the event loop lag fixes behave in a live‑like environment with all agents, pipelines, and WebSocket feeds active.

## 1. Startup (paper, monitored)

Ensure env is paper‑only:

```bash
export MERID_TRADE_MODE=paper
export MERID_ALLOW_LIVE_TRADES=false
```

Start the backend with full monitoring (using your existing ops script or `docker-compose.prod`).

Confirm from logs:
- Event loop monitor (Phase ‑1) starts successfully.
- Health endpoints `/api/health` and `/health/event_loop` are reachable.

## 2. Live‑like load

Bring up:
- All 35 `KalshiTradingAgent` instances (confirm `_run_loop` is active for each).
- All 11 `KalshiInsightPipeline` category loops.
- Kalshi WebSocket feeds and any reconciliation/notification tasks that normally run in production.

## 3. Monitoring during the 30‑minute gate

Every ~30 seconds during the 30‑minute window:

- Poll `/health/event_loop` and record:
  - P50, P95, P99 lag.
  - `degraded` flag.
- Watch logs for:
  - Any "critical lag" or "degraded=true" transitions.  
  - Any captured high‑lag profiles (these should *not* appear if thresholds are 500 ms and you're under that).

### Gate pass criteria (must hold for entire 30 minutes)

- P95 event loop lag < 500 ms for the full run (no sustained spikes above threshold).  
- `degraded=false` on all `/health` samples.  
- No high‑lag profiles captured by the monitor.  
- Agents and pipelines show normal behavior (no skipped cycles, missing heartbeats, or starved tasks).

## 4. Documentation

After the gate:

- Append a new entry to `fix_history.md` with:
  - Date/time, configuration (paper mode, full agent/pipeline set).  
  - Observed P50/P95/P99 over the 30‑minute window.  
  - Confirmation that no degraded periods or high‑lag profiles occurred.  
  - Any minor anomalies and their explanations.

## Next steps

If this gate passes cleanly, you can proceed to design the **incremental live trading plan** (very low initial risk caps, same lag/health guardrails) as the next step.

If it fails at any point (P95 ≥ 500 ms, `degraded=true`, or profiles captured), halt, investigate, and treat it as a new ANOMALY in `fix_history.md` before rerunning.
