# Kalshi Latency Remediation — Reusable Prompt

Use this prompt to turn the audit in `docs/kalshi_latency_audit.md` into concrete code fixes.

```
You are a senior asyncio + trading-systems engineer continuing a **Kalshi latency remediation** that already produced `docs/kalshi_latency_audit.md`.

Context:
- Event-loop lag warnings and slow ticks:
  - `merid.event_venues.kalshi.ws | Event-loop lag: 454ms`
  - `merid.loop | Slow tick #154: 31093ms (threshold 30000ms)`
- The audit doc identifies likely causes:
  - WebSocket handlers/bridge awaiting heavy callbacks inline, so slow side-effects stall the loop.
  - Tick scheduler runs all actions serially; when `liquidity_sweep` + `kalshi_signals` + `arb_scan` align, tick latency explodes.
  - Liquidity sweep polls ~20 markets sequentially; orderbook calls may be sync or effectively blocking.
  - Event bus uses locks and synchronous publishes under load.

Task now:
1) For each hot path (`_refresh_kalshi_signals`, `_refresh_liquidity`, arb/consensus runners, Kalshi WS, WS bridge, event bus):
   - Locate the implementation.
   - Classify expensive ops as CPU-bound, blocking I/O, or safe.
   - Propose minimal, safe code changes to:
     - Move blocking work into `asyncio.to_thread` / executor.
     - Add bounded `gather`/task-groups for parallel I/O (orderbook fetches with concurrency limit + per-call timeout).
     - Replace sync HTTP/DB calls with async equivalents where practical.
2) In `merid.loop` scheduling:
   - Refactor tick into phases (I/O-heavy vs CPU-heavy) and run compatible actions concurrently.
   - Add per-action timers and an event-loop lag watchdog coroutine that logs when latency exceeds thresholds.
3) In Kalshi WS ingestion (`merid/event_venues/kalshi/ws.py`, `ws_bridge.py`):
   - Find where handlers await heavy downstream work (publishing, cache updates).
   - Dispatch heavy work via `create_task`/executor; keep parsing/validation on the loop.
   - Ensure backpressure via bounded queues and explicit drop/overflow strategy.
4) Event bus (`core/event_bus.py`):
   - Identify global locks or synchronous publish loops that can block.
   - Where safe, swap to non-blocking patterns (async queues, fire-and-forget tasks) with instrumentation.
5) Output:
   - Patch-style diffs per file (small, reviewable).
   - Checklist of instrumentation hooks: per-tick duration, per-action duration, event-loop lag, queue depths.

Constraints:
- Preserve external behavior and public APIs; keep changes minimal and latency-focused.
- Avoid speculative refactors; prefer small, obviously correct transformations.
- Assume CI can add pytest/async profiling later; keep changes test-friendly now.
```
