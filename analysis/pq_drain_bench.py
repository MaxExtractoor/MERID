"""Offline acceptance harness for the ws.py _msg_queue drain path.

2026-10-31: rollover measurement localized residual lag to _process_queue
residence (~3.2s mean at ~840/s arrival).  Before any drain-path change,
the acceptance criteria require replaying the same burst through current
and proposed implementations and comparing:

  - drain rate + queue-age distribution (performance)
  - delivery order vs enqueue order (ordering / no hidden loss)
  - queue-age recovery after the burst (responsiveness)
  - bounded tasks (resources)

Usage:  .venv/Scripts/python.exe analysis/pq_drain_bench.py [--rate R] [--burst B]

The harness drives the REAL KalshiWebSocket._process_queue (via
object.__new__ — no credentials/network) with a stub bridge callback
that records delivery order and timing.  A per-item sequence check on
the delivered stream proves order preservation; the delivered sequence
is then applied to a real KalshiMarketStateStore so book equality can
be asserted against a sequential reference in later variants.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from merid.event_venues.kalshi.ws import KalshiWebSocket


import threading
from concurrent.futures import ThreadPoolExecutor


def _bare_ws() -> KalshiWebSocket:
    """KalshiWebSocket without __init__: only attrs the drain path touches.

    Every mutable-state access in the drain loop is getattr-lazy already;
    we seed the handful the loop reads unconditionally, plus a
    __getattr__-style defaulting for the rest via a subclass.
    """

    class _BenchWS(KalshiWebSocket):
        pass

    ws = object.__new__(_BenchWS)
    ws._running = True
    ws._msg_queue = None
    ws._priority_msg_queue = None
    ws._msg_queue_guard = threading.Lock()
    ws._parse_lock = threading.Lock()
    ws._callback = None
    ws._callback_executor = ThreadPoolExecutor(max_workers=2)
    ws._messages_dropped = 0
    ws._last_drop_log_ts = 0.0
    ws._drop_log_interval_s = 5.0
    ws._last_seq = {}
    ws._seq_gaps = 0
    ws._loop_lag_samples = []
    ws._process_time_sum = 0.0
    ws._process_time_max = 0.0
    ws._process_time_count = 0
    return ws


def _delta(seq: int, ticker: str = "KXBTC15M-T") -> dict:
    """Synthetic orderbook_delta carrying the stamps the drain path uses."""
    return {
        "type": "orderbook_delta",
        "sid": 1,
        "seq": seq,
        "ticker": ticker,
        "msg": {
            "market_ticker": ticker,
            "side": "yes",
            "price_dollars": 0.49,
            "delta_fp": 3.0,
            "seq": seq,
            "ts": time.time() - 0.1,  # recent venue ts
        },
    }


async def _bench(
    rate: int, burst: int, baseline_s: float, burst_s: float,
    realistic: bool, loop_noise_ms: float,
) -> dict:
    ws = _bare_ws()
    delivered: list[tuple[int, int]] = []  # (seq, delivered_mono_ns)
    enq_ns: dict[int, int] = {}
    fwd_q: asyncio.Queue = asyncio.Queue(maxsize=8192)  # bridge-queue analog

    async def stub_callback(event, *a):
        data = a[-1] if a else event
        d = data if isinstance(data, dict) else getattr(event, "raw", {})
        seq = (d or {}).get("seq")
        delivered.append((seq, time.monotonic_ns()))

    async def bridgeish_callback(event, *a):
        """Approximate ws_bridge._enqueue_event cost: stamps, type/seq
        counters, sid-scoped seq check, bounded queue put — the real
        awaited dependency inside _handle_event_async."""
        data = a[-1] if a else event
        d = data if isinstance(data, dict) else event
        now_ns = time.monotonic_ns()
        d["_t_bridge_recv_ns"] = now_ns
        d["_t_bridge_recv_wall_ms"] = time.time() * 1000.0
        payload = d.get("msg")
        if isinstance(payload, dict):
            payload["_t_bridge_recv_ns"] = now_ns
            payload["_t_bridge_recv_wall_ms"] = time.time() * 1000.0
        seq = d.get("seq")
        if seq is not None:
            last = bridgeish_callback._last.get(d.get("sid"))
            if last is not None and seq > last + 1:
                bridgeish_callback._gaps += seq - last - 1
            bridgeish_callback._last[d.get("sid")] = seq
        try:
            fwd_q.put_nowait(d)
        except asyncio.QueueFull:
            fwd_q.get_nowait()
            fwd_q.put_nowait(d)
        delivered.append((seq, now_ns))

    bridgeish_callback._last = {}
    bridgeish_callback._gaps = 0

    cb = bridgeish_callback if realistic else stub_callback

    async def forwarder():
        """Bridge forward-loop analog: drains fwd_q to a sink."""
        try:
            while ws._running:
                try:
                    fwd_q.get_nowait()
                except asyncio.QueueEmpty:
                    await asyncio.sleep(0.002)

        except asyncio.CancelledError:
            pass

    async def noise_task():
        """Competing event-loop work: sync CPU bursts modelling co-tenant
        tasks (loop cycles, REST pollers, forwarder) starving the drain."""
        try:
            while ws._running:
                await asyncio.sleep(0.010)
                t = time.monotonic() + loop_noise_ms / 1000.0
                while time.monotonic() < t:
                    pass
        except asyncio.CancelledError:
            pass

    async def producer(rate_per_s: float, seconds: float, seq_start: int) -> int:
        seq = seq_start
        q = ws._ensure_msg_queue()
        interval = 1.0 / rate_per_s
        t_end = time.monotonic() + seconds
        next_t = time.monotonic()
        while time.monotonic() < t_end:
            next_t += interval
            msg = _delta(seq)
            msg["_t_ws_recv_ns"] = time.monotonic_ns()
            enq_ns[seq] = msg["_t_ws_recv_ns"]
            q.put_nowait((99, msg))
            seq += 1
            delay = next_t - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
            else:
                await asyncio.sleep(0)  # yield when behind schedule
        return seq

    proc = asyncio.create_task(ws._process_queue(cb))
    fwd = asyncio.create_task(forwarder())
    noise = asyncio.create_task(noise_task()) if loop_noise_ms > 0 else None
    seq = 0
    seq = await producer(rate, baseline_s, seq)          # baseline arrival
    seq = await producer(burst, burst_s, seq)            # rollover burst
    total = seq
    # drain tail: wait until delivered or bounded timeout
    t0 = time.monotonic()
    while len(delivered) < total and time.monotonic() - t0 < 30.0:
        await asyncio.sleep(0.05)
    ws._running = False
    proc.cancel()
    fwd.cancel()
    if noise is not None:
        noise.cancel()
    for t in (proc, fwd, noise):
        if t is not None:
            try:
                await t
            except asyncio.CancelledError:
                pass

    waits = sorted(
        (d - enq_ns[s]) / 1e6 for s, d in delivered if s in enq_ns
    )
    order_ok = all(
        delivered[i][0] == i for i in range(len(delivered))
    )
    n = len(waits)
    return {
        "rate": rate,
        "burst": burst,
        "realistic_callback": realistic,
        "loop_noise_ms_per_10ms": loop_noise_ms,
        "total_enqueued": total,
        "delivered": len(delivered),
        "order_preserved": order_ok,
        "lost": total - len(delivered),
        "pq_wait_ms_p50": round(waits[n // 2], 1) if n else None,
        "pq_wait_ms_p95": round(waits[int(n * 0.95)], 1) if n else None,
        "pq_wait_ms_max": round(waits[-1], 1) if n else None,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rate", type=int, default=650)
    ap.add_argument("--burst", type=int, default=840)
    ap.add_argument("--baseline-s", type=float, default=10.0)
    ap.add_argument("--burst-s", type=float, default=10.0)
    ap.add_argument("--realistic-callback", action="store_true",
                    help="approximate ws_bridge._enqueue_event cost")
    ap.add_argument("--loop-noise-ms", type=float, default=0.0,
                    help="sync CPU per 10ms tick competing for the loop")
    args = ap.parse_args()
    out = asyncio.run(_bench(
        args.rate, args.burst, args.baseline_s, args.burst_s,
        args.realistic_callback, args.loop_noise_ms,
    ))
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
