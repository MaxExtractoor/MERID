# Kalshi Event-Loop Lag Audit

Context log:
- `2026-03-24 16:28:38 | WARNING | merid.event_venues.kalshi.ws | Event-loop lag: 454ms`
- `2026-03-24 16:28:39 | WARNING | merid.loop | Slow tick #154: 31093ms (threshold 30000ms). Actions: consensus_check:…, arb_scan:6signals, order_groups:synced, kalshi_signals:10, features_refreshed:0symbols, liquidity_sweep:20markets,40alerts`

## Upstream (Kalshi WS / ingestion)
- `merid/event_venues/kalshi/ws.py:334-428`: WS listen loop parses JSON and awaits `_process_queue` callback directly. Any slow callback (e.g., bridge publishing or downstream cache updates) stalls the queue and raises the lag warning. **Fix:** decouple callback via `asyncio.create_task` and add a small semaphore to bound concurrent handlers:
  ```python
  async def _process_queue(...):
      ...
      if event:
          loop = asyncio.get_running_loop()
          loop.create_task(callback(event))
  ```
- `merid/event_venues/kalshi/ws_bridge.py:217-360`: Forwarder performs heavy side effects inline (position cache updates, AgentPerformanceTracker, streaming_bus publish). A slow listener keeps `_queue` full and back-pressures the WS processor. **Fix:** move side effects off the event loop:
  ```python
  async def _publish_event(...):
      loop = asyncio.get_running_loop()
      await self._publish_to_bus("kalshi:trade", trade_payload)
      loop.run_in_executor(None, cache.on_fill, ...)
      loop.create_task(tracker.record_close_async(...))
  ```
- `merid/event_venues/kalshi/ws.py:398-429`: Handler timing only logs when >50ms, but no per-type stats surface. Add per-channel histograms to stats() and include queue depth + lag percentiles in the bridge summary to catch growth before drops.
- Potential egg: `_lag_check_handle` is not cancelled in `close()`, so a long-running loop may keep posting lag samples after shutdown. Cancel the timer in `close()` to avoid noisy warnings during reconnects.

## Downstream (tick actions / arb / consensus)
- Serial tick pipeline (`merid/loop.py:281-355`) runs every due action sequentially. When several intervals align (arb_scan + liquidity_sweep + kalshi_signals), one slow action delays all others and blocks the event loop.
- **liquidity_sweep** (`merid/loop.py:717-794`): Polls up to 20 markets sequentially; a 1.5s orderbook call → 30s tick (matches log). **Fix:** batch with bounded concurrency and timeouts:
  ```python
  sem = asyncio.Semaphore(5)
  async def fetch(t):
      async with sem:
          return t, await asyncio.wait_for(client.get_orderbook(t), 1.5)
  results = await asyncio.gather(*(fetch(t) for t in tickers), return_exceptions=True)
  ```
- **kalshi_signals** (`merid/loop.py:397-413`, `merid/signals/kalshi_signals.py:320-375`): `generate_all` lists instruments and loops synchronously; if HTTP is slow, the tick stalls. **Fix:** wrap with `asyncio.wait_for(..., timeout=2)` and cache recent signals; run heavy edge fetch in a background task that updates a shared cache consumed by the tick.
- **arb_scan** (`merid/loop.py:798-813`): `scanner.scan` is sync/CPU; large universes block the loop. **Fix:** `await asyncio.to_thread(scanner.scan, now)` and cap runtime with `asyncio.wait_for`.
- **consensus_check** (`merid/loop.py:598-715`): Iterates `_opinions` and calls private `_run_consensus_cycle` sequentially. If multiple symbols pile up, tick latency grows. **Fix:** batch with `asyncio.gather` over a small semaphore (e.g., 3) or move consensus to a background task and only collect results in the tick.
- **order_groups** (`merid/loop.py:1125-1189`): `og_lifecycle.start()` is awaited inside the tick if not running; WS start + REST sync can spike first tick. Start it during loop bootstrap and only read cached state during ticks.

## Event-loop / tick scheduler
- Tick cadence is fixed (`sleep_time` ~1–5s) and lacks per-action timing; the slow-tick log only emits after the fact. Instrument each action and emit durations + queue depths when `duration_ms` crosses a low threshold (e.g., 200ms) to pinpoint offenders.
- Run independent actions in phases with bounded concurrency:
  - Phase A (I/O): `feature_refresh`, `kalshi_signals`, `liquidity_sweep` via `asyncio.gather(..., return_exceptions=True)` with per-task timeouts.
  - Phase B (CPU): `arb_scan`, `consensus_check` via `asyncio.to_thread` or executor, keeping a small worker pool.
  - Phase C: execution + reconciliation.
- Add lightweight lag probes tied to the loop tick (not just WS) using `loop.slow_callback_duration` or a scheduled `call_later` that logs when drift >100ms.

## Concrete fix snippets
- Bounded fan-out for liquidity sweep:
  ```python
  async def _refresh_liquidity(...):
      sem = asyncio.Semaphore(5)
      async def fetch(t):
          async with sem:
              return t, await asyncio.wait_for(client.get_orderbook(t), 1.5)
      results = await asyncio.gather(*(fetch(t) for t in tickers), return_exceptions=True)
      for ticker, ob in results:
          if isinstance(ob, Exception) or not ob:
              continue
          ...
  ```
- Protect kalshi_signals:
  ```python
  signals = []
  try:
      signals = await asyncio.wait_for(generator.generate_all(now), timeout=2.0)
  except asyncio.TimeoutError:
      logger.warning("kalshi_signals timeout (2s) — using last cache")
      signals = generator.get_last_signals()
  ```
- Per-action timing in tick:
  ```python
  async def _run_step(name, coro):
      t0 = time.perf_counter()
      try:
          return await coro
      finally:
          summary.setdefault("timings_ms", {})[name] = (time.perf_counter()-t0)*1000
  ...
  await _run_step("liquidity_sweep", self._refresh_liquidity(now, summary))
  if summary["duration_ms"] > 200:
      logger.warning("Slow tick %s timings=%s", summary["tick"], summary.get("timings_ms"))
  ```
- WS bridge offload:
  ```python
  loop = asyncio.get_running_loop()
  await self._publish_to_bus("kalshi:order_filled", payload)
  loop.run_in_executor(None, cache.on_fill, ...)
  loop.create_task(streaming_bus.publish(_mkt_event))
  ```

## Egg checklist & how to catch them
- Sync DB/HTTP inside async paths (e.g., any `requests`/blocking client) → run `pytest -q --disable-warnings` with `PYTHONASYNCIODEBUG=1` and audit stack traces for `blocking` warnings.
- Heavy JSON/serialization in hot loops (WS parse, consensus serialization) → profile with `asyncio.get_running_loop().set_debug(True)` and `PYTHONASYNCIODEBUG` to surface slow callbacks; use `cProfile` around `tick()`.
- Long-lived WS subscriptions without cleanup → assert `ws_bridge.summary()["subscribed_tickers"]` matches agent grid; add a test that starts/stops the loop and checks `ws.stats()["subscriptions"]` returns to zero.
- Unbounded queues → verify `_msg_queue` (4096) and `_queue` (2048) do not grow: add metrics to health endpoints and alert when `qsize()/maxsize > 0.5`.
- `time.sleep` / `threading.Lock` in async code → `rg "time.sleep" merid` and run `pytest -k sleep` to ensure no blocking calls remain; replace with `asyncio.sleep` or `asyncio.Lock`.
- Order-group lifecycle leaks → after a simulated session, ensure `OrderGroupLifecycleManager.stop()` clears tasks and WS; add a unit test to assert no pending tasks via `asyncio.all_tasks()` snapshot.

## Notes on current validation
- Tried `pytest` from repo root; it is not installed in the environment (`pytest: command not found`). No tests were executed. Install deps or run in CI before relying on new changes.
