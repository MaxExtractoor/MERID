# Background Work Patterns

> When should I use `BackgroundTasks` vs a job queue?

## Decision Matrix

| Criterion | FastAPI `BackgroundTasks` | Job Queue (Celery / RQ / NATS) |
|-----------|--------------------------|-------------------------------|
| **Latency budget** | Fire-and-forget, < 2 s | Any duration |
| **Failure tolerance** | Best-effort (lost on crash) | Durable, retryable |
| **Resource weight** | Light CPU / I/O | Heavy compute, external calls |
| **Scaling** | Same process | Separate worker pool |
| **Examples** | Emit notification, write audit log, refresh cache | Backtest run, bulk reconciliation, LLM inference |

## Pattern 1 — FastAPI `BackgroundTasks` (light)

Use for work that is **cheap, non-critical, and can be lost** if the
process restarts.

```python
from fastapi import BackgroundTasks

@router.post("/api/v1/example/action")
async def do_action(bg: BackgroundTasks):
    result = perform_action()
    bg.add_task(emit_audit_event, result)  # non-blocking
    return result
```

### Rules
- Task must complete in **< 2 seconds**.
- No database transactions — use for logging, cache warming, notifications.
- Never `await` inside `add_task` callbacks (they run synchronously on the
  event loop's thread pool).

## Pattern 2 — Job Queue (heavy)

Use when the work is **expensive, must survive restarts**, or needs
separate scaling.

MERID currently uses the **NATS event bus** for lightweight task dispatch
and can optionally use **Celery + Redis** for heavier workloads.

```python
from merid_core.event_bus import publish_task

@router.post("/api/v1/example/heavy")
async def start_heavy_job():
    job_id = await publish_task("backtest.run", {"strategy": "momentum"})
    return {"job_id": job_id, "status": "queued"}
```

### Rules
- Always return a `job_id` so the caller can poll for status.
- Workers should be idempotent — duplicate delivery is possible.
- Set a timeout on every task (`max_runtime_seconds`).

## Anti-patterns

1. **Blocking the event loop** — never do `time.sleep()` or synchronous
   HTTP calls inside an `async def` endpoint. Use `BackgroundTasks` or
   `asyncio.to_thread()`.
2. **Inline heavy queries** — if a query takes > 500 ms, move it to a
   background task and return a polling handle.
3. **Silent failures** — always log exceptions inside background
   callbacks; FastAPI swallows them silently.

## Decision Gate (required for new endpoints)

Before merging any endpoint that does non-trivial work, answer:

1. **Which pattern?** Pattern 1 (BackgroundTasks) or Pattern 2 (job queue)?
2. **Why?** One sentence referencing the decision matrix criteria.
3. **Timeout?** What happens if this runs forever?
4. **Failure mode?** If the background work fails, does the user see an error
   or silent data staleness?

Add the answers as a code comment above the endpoint:

```python
# Background: Pattern 1 (BackgroundTasks) — cache refresh < 1s, non-critical.
# Timeout: N/A (fire-and-forget). Failure: stale cache until next poll.
@router.post("/api/v1/example/refresh")
async def refresh_cache(bg: BackgroundTasks):
    bg.add_task(warm_cache)
    return {"status": "refreshing"}
```

## Migration Checklist

When moving inline work to background execution:

- [ ] Identify the work in the endpoint (look for `await` calls > 500 ms).
- [ ] Choose pattern 1 or 2 based on the decision matrix above.
- [ ] Ensure the endpoint returns immediately with a status/job handle.
- [ ] Add structured logging inside the background callback.
- [ ] Add a timeout to prevent runaway tasks.

## Incident Log

Record real incidents here so the patterns evolve with experience.

| Date | Endpoint | Issue | Root Cause | Fix / Lesson |
|------|----------|-------|-----------|--------------|
| 2026-03-19 | `PredictionAlertManager.fire_risk_breach` | 12,000+ Telegram messages in minutes; event-loop lag spiked to 7.7s | CRITICAL suppress window was 0s — every per-tick risk evaluation re-fired. Two independent Telegram send paths (agent + webhook_client) both active with no dedup. | CRITICAL suppress → 30s. Added edge-trigger breach latch (fire on False→True only, 5m reminders). Added `telegram_alerts` feature flag gate on both send paths. Added 401/403/429 exponential backoff in `_tg_raw_send`. |
| _template_ | `/api/v1/example` | 30s response time under load | Synchronous DB query in async handler | Moved to Pattern 2; added `asyncio.to_thread()` |

> When you hit a background-work incident, add a row above and update the
> Anti-patterns or Rules sections if the lesson is generalizable.
