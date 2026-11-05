#!/usr/bin/env python
"""Archive raw Kalshi orderbook_delta frames for the five 15m crypto series.

Standalone collector (Phase A' of the execution-audit spec): opens its own
authenticated Kalshi WebSocket, subscribes to ``orderbook_delta`` for every
open+upcoming market in the KX{BTC,ETH,SOL,XRP,DOGE}15M series, and persists
every frame — snapshot and delta — verbatim to ``data/kalshi_book_archive.db``
with connection/subscription sequence context, pre-parse receipt timestamps,
and explicit coverage/session bookkeeping.

It answers: "can we reconstruct the book we actually observed, in order, at
a specified local receipt time — and which intervals can we not?"

Read-only data collection — no order endpoints are touched.  Runs
independently of the trading server (Task Scheduler, restart-on-failure)
so server restarts do not create coverage gaps.  Single-active-collector
lock prevents double capture.

Usage:
    .venv\\Scripts\\python.exe scripts\\kalshi_book_archiver.py   # foreground
    Register via Task Scheduler like the RTI archiver for always-on capture.

Env:
    MERID_BOOK_ARCHIVE_DB            output path (default data/kalshi_book_archive.db)
    MERID_BOOK_ARCHIVE_RETENTION_H   retention horizon (default 24h —
        measured ~700 deltas/sec across the 5 live markets at window tail,
        ~100-250MB/hour aggregate; size retention accordingly)
    MERID_BOOK_ARCHIVE_ASSETS        CSV asset allowlist (default BTC,ETH,SOL,XRP,DOGE)
    MERID_BOOK_DISCOVERY_S           market re-discovery interval (default 20s)
    MERID_BOOK_CLOSE_GRACE_S         keep coverage open past close (default 120s)
    MERID_BOOK_SNAPSHOT_TIMEOUT_S    missing-snapshot alert delay (default 20s)
    MERID_BOOK_QUEUE_MAX             ingest buffer bound (default 50000)
    MERID_BOOK_SILENCE_RECONNECT_S   WS silence -> reconnect (default 45s)
    MERID_BOOK_UPDATE_INTERVAL_MS    server-side conflation (default 0 = unconflated)
    MERID_BOOK_HEARTBEAT_S           heartbeat write interval (default 15s)
    MERID_KALSHI_WS_BASE             WS endpoint override
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

# Deployment bootstrap: Task Scheduler should invoke the base interpreter
# directly (this venv's launcher is a redirector that spawns the base python
# as an untracked child — stopping the task would orphan the collector).
# Running the base interpreter loses the venv's site-packages, so make them
# importable here. No-op when already running inside the venv.
_VENV_SITE = _REPO_ROOT / ".venv" / "Lib" / "site-packages"
if _VENV_SITE.is_dir() and str(_VENV_SITE) not in sys.path:
    sys.path.insert(1, str(_VENV_SITE))

# pythonw.exe (scheduled-task mode) has no console: sys.stdout is None.
if sys.stdout is None:
    _log = open(_REPO_ROOT / "data" / "book_archiver.log", "a", buffering=1)
    sys.stdout = sys.stderr = _log

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_REPO_ROOT / ".env")

from merid.event_venues.kalshi.book_archive import (  # noqa: E402
    ALERT_BUFFER_OVERFLOW,
    ALERT_COLLECTOR_START,
    ALERT_DB_WRITE_ERROR,
    ALERT_MISSING_SNAPSHOT,
    ALERT_RECONNECT,
    AlertRecord,
    BookArchiveDB,
    BookArchiveStream,
    COV_AWAITING_SNAPSHOT,
    CoverageTracker,
    IngestQueue,
    envelope_from_frame,
)
from merid.event_venues.kalshi.contract_fingerprint import (  # noqa: E402
    compute_contract_fingerprints,
)
from merid.event_venues.kalshi.fifteen_minute_market_locator import (  # noqa: E402
    SERIES_BY_ASSET,
)

_DB_PATH = os.environ.get(
    "MERID_BOOK_ARCHIVE_DB", str(_REPO_ROOT / "data" / "kalshi_book_archive.db")
)
_LOCK_PATH = os.environ.get(
    "MERID_BOOK_ARCHIVE_LOCK",
    str(_REPO_ROOT / "data" / "kalshi_book_archiver.lock"),
)
_HEARTBEAT_PATH = os.environ.get(
    "MERID_BOOK_ARCHIVE_HEARTBEAT",
    str(_REPO_ROOT / "data" / "kalshi_book_archiver.heartbeat.json"),
)
_RETENTION_S = float(os.environ.get("MERID_BOOK_ARCHIVE_RETENTION_H", "24")) * 3600.0
_DISCOVERY_S = float(os.environ.get("MERID_BOOK_DISCOVERY_S", "20"))
_CLOSE_GRACE_S = float(os.environ.get("MERID_BOOK_CLOSE_GRACE_S", "120"))
_SNAPSHOT_TIMEOUT_S = float(os.environ.get("MERID_BOOK_SNAPSHOT_TIMEOUT_S", "20"))
# Fast tier; the overflow deque below takes floods past this.
_QUEUE_MAX = int(os.environ.get("MERID_BOOK_QUEUE_MAX", "600000"))
# Overflow tier: rollover floods run ~3.5k ev/s over ~3-7min while the
# writer sustains ~1.9k/s; observed bursts reached ~675k events.  Envelopes
# in overflow are delayed-not-dropped (persisted on catch-up); only frames
# beyond this cap become __dropped__ markers.  ~900MB envelope RAM worst.
_OVERFLOW_MAX = int(
    os.environ.get("MERID_BOOK_OVERFLOW_MAX", "1500000")
)
_HEARTBEAT_S = float(os.environ.get("MERID_BOOK_HEARTBEAT_S", "15"))
_SILENCE_RECONNECT_S = float(os.environ.get("MERID_BOOK_SILENCE_RECONNECT_S", "45"))
_PRUNE_EVERY_S = 14400.0  # 4h — a 24h retention window does not need 15min sweeps
_STATS_EVERY_S = 60.0
_WRITER_POLL_S = 0.25
# Discovery looks back far enough to keep just-closed windows under grace
# coverage, and forward covers upcoming windows Kalshi already lists.
_DISCOVERY_MIN_CLOSE_BACK_S = 1800
# Kalshi lists days of future 15m markets; subscribing to all of them would
# be unbounded.  Bound the wire set to windows opening soon (current plus
# the next two buckets per asset).
_DISCOVERY_OPEN_AHEAD_S = float(os.environ.get("MERID_BOOK_OPEN_AHEAD_S", "1800"))

_ASSETS = {
    a.strip().upper()
    for a in os.environ.get(
        "MERID_BOOK_ARCHIVE_ASSETS", "BTC,ETH,SOL,XRP,DOGE"
    ).split(",")
    if a.strip()
}
_SERIES = {SERIES_BY_ASSET[a]: a for a in _ASSETS if a in SERIES_BY_ASSET}


def _pid_alive(pid: int) -> bool:
    """Cross-platform liveness check (os.kill(pid,0) TERMINATES on Windows —
    never use it here)."""
    if os.name == "nt":
        import ctypes

        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if h:
            ctypes.windll.kernel32.CloseHandle(h)
            return True
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _acquire_single_collector_lock() -> bool:
    """Single-active-collector guard: lock file + heartbeat freshness."""
    lock = Path(_LOCK_PATH)
    if lock.exists():
        try:
            info = json.loads(lock.read_text())
            pid = int(info.get("pid", -1))
        except Exception:
            pid = -1
        if pid > 0 and _pid_alive(pid):
            print(
                f"[book-archiver] another collector holds the lock "
                f"(pid={pid}); refusing to start",
                flush=True,
            )
            return False
        print(
            f"[book-archiver] stale lock (pid={pid} dead); taking over",
            flush=True,
        )
    tmp = lock.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "started_utc": datetime.now(timezone.utc).isoformat(),
            }
        )
    )
    os.replace(tmp, lock)
    return True


def _iso_to_ts(v) -> float | None:
    if not v:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


async def _discover_markets(public_client, min_close_ts: int) -> dict:
    """Return {ticker: raw_market_dict} across all tracked series."""
    out: dict = {}
    for series, asset in _SERIES.items():
        try:
            markets = await public_client.list_open_markets_for_series(
                series, min_close_ts=min_close_ts
            )
        except Exception as exc:
            print(
                f"[book-archiver] discovery error series={series}: {exc}",
                flush=True,
            )
            continue
        for m in markets:
            raw = getattr(m, "raw", None) or {}
            ticker = getattr(m, "market_id", None) or raw.get("ticker")
            if not ticker:
                continue
            raw.setdefault("series_ticker", series)
            raw["__asset__"] = asset
            out[ticker] = raw
    return out


def main() -> int:
    if not _acquire_single_collector_lock():
        return 3

    collector_id = f"col-{os.getpid()}-{int(time.time())}"
    db = BookArchiveDB(_DB_PATH)
    tracker = CoverageTracker()
    ingest = IngestQueue(maxsize=_QUEUE_MAX, overflow_cap=_OVERFLOW_MAX)

    stop = threading.Event()
    session_events: "queue.SimpleQueue[dict]" = __import__("queue").SimpleQueue()
    discovery_results: "queue.SimpleQueue[dict]" = __import__("queue").SimpleQueue()

    # Writer-thread-owned state.
    recv_ordinal = [0]
    pending_subscribe: dict = {}  # connection_id -> last sent ticker set
    market_meta: dict = {}        # ticker -> {open_ts, close_ts, ...}
    subscribed_meta: dict = {}    # (conn, sid) -> tickers awaiting meta attach
    alerted_missing_snapshot: set = set()
    alerts_pending: list = []

    def _alert(code, severity, detail, conn=None, sid=None, ticker=None):
        alerts_pending.append(
            AlertRecord(
                severity=severity,
                code=code,
                detail=detail,
                connection_id=conn,
                subscription_id=sid,
                market_ticker=ticker,
                ts_utc_ns=time.time_ns(),
            )
        )

    # ── WS callbacks (WS thread; enqueue only — no state mutation) ──────
    def on_frame(raw_text: str, recv_utc: int, recv_mono: int, conn_id: str):
        recv_ordinal[0] += 1
        env = envelope_from_frame(
            raw_text,
            received_at_utc_ns=recv_utc,
            received_at_monotonic_ns=recv_mono,
            connection_id=conn_id,
            collector_instance_id=collector_id,
            recv_ordinal=recv_ordinal[0],
        )
        if not ingest.put(env):
            # Throttled: overflow floods alerts if we emit per-event.
            d = ingest.dropped_total
            if d <= 10 or d % 1000 == 0:
                _alert(
                    ALERT_BUFFER_OVERFLOW, "error",
                    f"ingest overflow cap reached; dropped_total={d} "
                    f"conn={conn_id}",
                    conn=conn_id,
                )

    def on_session(conn_id: str, event: str, detail: dict):
        session_events.put(
            {"connection_id": conn_id, "event": event, "detail": detail,
             "ts_utc_ns": time.time_ns()}
        )

    stream = BookArchiveStream(
        on_frame=on_frame,
        on_session=on_session,
        silence_reconnect_s=_SILENCE_RECONNECT_S,
    )

    # ── session-event application (writer thread) ──────────────────────
    msgs_by_conn: dict = {}

    def _apply_session_event(ev: dict):
        conn_id, event, detail = (
            ev["connection_id"], ev["event"], ev["detail"]
        )
        ts = ev["ts_utc_ns"]
        if event == "connect":
            db.insert_session(
                connection_id=conn_id,
                collector_instance_id=collector_id,
                ws_url=detail.get("ws_url") or "",
                connect_utc_ns=ts,
            )
            msgs_by_conn[conn_id] = 0
            _alert(
                ALERT_RECONNECT,
                "info",
                f"connection {conn_id} established",
                conn=conn_id,
            )
        elif event == "subscribe_sent":
            pending_subscribe[conn_id] = list(detail.get("tickers") or [])
        elif event == "disconnect":
            db.close_session(
                conn_id,
                disconnect_utc_ns=ts,
                reason="disconnect",
                msgs_received=msgs_by_conn.get(conn_id, 0),
                subscription_map={
                    sid: sorted(t)
                    for (c, sid), t in tracker._sid_tickers.items()
                    if c == conn_id
                },
            )
            db.upsert_coverage(
                tracker.note_session_end(conn_id, reason="disconnect", ts_utc_ns=ts)
            )
        elif event in ("silence_timeout", "connection_closed", "recv_error"):
            db.close_session(
                conn_id,
                disconnect_utc_ns=ts,
                reason=f"{event}:{detail.get('reason', '')}"[:200],
                msgs_received=msgs_by_conn.get(conn_id, 0),
                subscription_map={
                    sid: sorted(t)
                    for (c, sid), t in tracker._sid_tickers.items()
                    if c == conn_id
                },
            )
            db.upsert_coverage(
                tracker.note_session_end(conn_id, reason=event, ts_utc_ns=ts)
            )
            _alert(
                ALERT_RECONNECT,
                "warning",
                f"{event}: {detail}",
                conn=conn_id,
            )

    # ── writer loop ────────────────────────────────────────────────────
    writer_stats = {"iter_ms": 0.0, "batch": 0, "iters": 0,
                    "drain_ms": 0.0, "note_ms": 0.0, "insert_ms": 0.0,
                    "cov_ms": 0.0, "other_ms": 0.0}

    def writer_loop():
        last_prune = time.monotonic()
        last_cov_flush = time.monotonic()
        cov_pending = {}
        while not stop.is_set() or ingest.depth:
            iter_t0 = time.monotonic()
            if not ingest.depth:
                time.sleep(_WRITER_POLL_S)
            t_drain = time.monotonic()

            # 1. event batch FIRST: frames drained before session events so
            # a connection's last events still count toward its coverage and
            # message totals before the session closes over them.
            batch = ingest.drain(max_items=20000)
            t_note = time.monotonic()
            if batch:
                touched = {}
                for env in batch:
                    msgs_by_conn[env.connection_id] = (
                        msgs_by_conn.get(env.connection_id, 0) + 1
                    )
                    # 'subscribed' confirmations create coverage rows.
                    if env.message_type == "subscribed":
                        sid = env.subscription_id
                        if sid is not None:
                            tickers = pending_subscribe.get(
                                env.connection_id, []
                            )
                            meta = {
                                t: market_meta.get(t, {})
                                for t in tickers
                            }
                            for rec in tracker.note_subscription(
                                env.connection_id,
                                sid,
                                tickers,
                                ts_utc_ns=env.received_at_utc_ns,
                                market_meta=meta,
                            ):
                                touched[rec.coverage_id] = rec
                    for rec in tracker.note_event(env):
                        # Auto-registered rows (ticker joined an existing sid
                        # via add_markets) get their market meta attached
                        # lazily here.
                        m = market_meta.get(rec.market_ticker)
                        if m and rec.market_open_ts is None:
                            rec.market_open_ts = m.get("open_ts")
                            rec.market_close_ts = m.get("close_ts")
                            rec.discovered_at_utc_ns = (
                                rec.discovered_at_utc_ns
                                or m.get("discovered_at_utc_ns")
                            )
                            rec.discovery_late = rec.discovery_late or bool(
                                m.get("discovery_late")
                            )
                        touched[rec.coverage_id] = rec
                t_insert = time.monotonic()
                try:
                    db.insert_events(batch)
                except Exception as exc:
                    # Atomic failure: nothing persisted.  Queue dropped
                    # markers for every envelope so the stored stream
                    # explicitly records the loss window.
                    _alert(
                        ALERT_DB_WRITE_ERROR, "error",
                        f"event batch insert failed ({len(batch)} events): {exc}",
                    )
                    for env in batch:
                        ingest.dropped_total += 1
                        marker = type(env).dropped(
                            collector_instance_id=env.collector_instance_id,
                            connection_id=env.connection_id,
                            subscription_id=env.subscription_id,
                            market_ticker=env.market_ticker,
                            dropped_type=env.message_type,
                            sequence_number=env.sequence_number,
                            received_at_utc_ns=env.received_at_utc_ns,
                            received_at_monotonic_ns=env.received_at_monotonic_ns,
                            drop_ordinal=ingest.dropped_total,
                            reason="db_write_error",
                        )
                        try:
                            ingest.dropped_meta.put_nowait(marker)
                        except Exception:
                            pass
                t_cov = time.monotonic()
                cov_pending.update(touched)
                writer_stats["note_ms"] = round(
                    (t_insert - t_note) * 1000, 1
                )
                writer_stats["insert_ms"] = round(
                    (t_cov - t_insert) * 1000, 1
                )
                writer_stats["drain_ms"] = round(
                    (t_note - t_drain) * 1000, 1
                )

            # 1b. coverage flush: derived state — commit every ~2s (or when
            # the queue is empty) rather than per iteration.
            t_cov_flush = time.monotonic()
            if cov_pending and (
                not ingest.depth
                or time.monotonic() - last_cov_flush >= 2.0
            ):
                try:
                    db.upsert_coverage(list(cov_pending.values()))
                    cov_pending.clear()
                    last_cov_flush = time.monotonic()
                except Exception as exc:
                    _alert(
                        ALERT_DB_WRITE_ERROR, "error",
                        f"coverage upsert failed: {exc}",
                    )
            writer_stats["cov_ms"] = round(
                (time.monotonic() - t_cov_flush) * 1000, 1
            )

            # 2. session lifecycle
            while True:
                try:
                    ev = session_events.get_nowait()
                except Exception:
                    break
                try:
                    _apply_session_event(ev)
                except Exception as exc:
                    _alert(
                        ALERT_DB_WRITE_ERROR, "error",
                        f"session event apply failed: {exc}",
                    )

            # 3. discovery results -> market registry + close markers
            while True:
                try:
                    d = discovery_results.get_nowait()
                except Exception:
                    break
                market_rows = []
                for ticker, meta in d.get("meta", {}).items():
                    market_meta[ticker] = meta
                    market_rows.append(meta["db_row"])
                try:
                    db.upsert_markets(market_rows)
                except Exception as exc:
                    _alert(
                        ALERT_DB_WRITE_ERROR, "error",
                        f"market upsert failed ({len(market_rows)} rows): {exc}",
                    )
                for ticker in d.get("expired", []):
                    db.upsert_coverage(
                        tracker.note_market_closed(
                            ticker, reason="past_close_grace",
                            ts_utc_ns=time.time_ns(),
                        )
                    )

            # 4. missing-snapshot sweep (once per coverage row)
            now_ns = time.time_ns()
            for (cid, sid, t), rec in tracker.records.items():
                if (
                    rec.state == COV_AWAITING_SNAPSHOT
                    and rec.subscribed_utc_ns
                    and (now_ns - rec.subscribed_utc_ns)
                    > _SNAPSHOT_TIMEOUT_S * 1e9
                    and rec.coverage_id not in alerted_missing_snapshot
                ):
                    alerted_missing_snapshot.add(rec.coverage_id)
                    _alert(
                        ALERT_MISSING_SNAPSHOT, "warning",
                        f"no snapshot within {_SNAPSHOT_TIMEOUT_S}s of "
                        f"subscribe ticker={ticker} sid={sid}",
                        conn=cid, sid=sid, ticker=t,
                    )

            # 5. persist alerts (copy-then-slice-delete so alerts appended
            # by the WS thread between read and clear are not lost)
            pending_alerts = alerts_pending[:]
            if pending_alerts:
                try:
                    db.insert_alerts(pending_alerts)
                except Exception as exc:
                    print(
                        f"[book-archiver] alert insert failed: {exc}",
                        flush=True,
                    )
                for a in pending_alerts:
                    print(
                        f"[book-archiver][ALERT] {a.severity} {a.code} "
                        f"{a.detail}",
                        flush=True,
                    )
                del alerts_pending[:len(pending_alerts)]

            # 6. retention — only while idle: the DELETE scans received_at
            # (not a left-prefix of any index) and the TRUNCATE checkpoint
            # copies the WAL back; either freezes the writer for minutes if
            # it fires mid-flood.
            if (
                not ingest.depth
                and time.monotonic() - last_prune > _PRUNE_EVERY_S
            ):
                last_prune = time.monotonic()
                try:
                    cutoff = time.time_ns() - int(_RETENTION_S * 1e9)
                    n = db.prune(cutoff)
                    if n:
                        print(f"[book-archiver] pruned {n} events", flush=True)
                except Exception as exc:
                    print(f"[book-archiver] prune error: {exc}", flush=True)

            writer_stats["iters"] += 1
            writer_stats["batch"] = len(batch)
            writer_stats["iter_ms"] = round(
                (time.monotonic() - iter_t0) * 1000, 1
            )
            writer_stats["other_ms"] = round(
                writer_stats["iter_ms"]
                - writer_stats["drain_ms"]
                - writer_stats["note_ms"]
                - writer_stats["insert_ms"]
                - writer_stats["cov_ms"],
                1,
            )

        # Clean-shutdown checkpoint: leave a small WAL so the next open's
        # crash-recovery scan stays short even under disk contention.
        try:
            db.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except Exception:
            pass

    # ── discovery loop (own thread + own event loop; HTTP only) ────────
    def discovery_loop():
        from merid.event_venues.kalshi.client_public import (
            KalshiPublicDataClient,
        )
        from merid.event_venues.kalshi.kalshi_config import get_kalshi_config

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        client = KalshiPublicDataClient(get_kalshi_config())
        known: set = set()

        while not stop.is_set():
            try:
                now_s = time.time()
                markets = loop.run_until_complete(
                    _discover_markets(
                        client, int(now_s) - _DISCOVERY_MIN_CLOSE_BACK_S
                    )
                )
            except Exception as exc:
                print(f"[book-archiver] discovery loop error: {exc}", flush=True)
                markets = {}

            desired: set = set()
            meta: dict = {}
            expired: list = []
            for ticker, raw in markets.items():
                close_ts = _iso_to_ts(
                    raw.get("close_time") or raw.get("close_ts")
                )
                open_ts = _iso_to_ts(
                    raw.get("open_time") or raw.get("open_ts")
                )
                status = str(raw.get("status") or "")
                if close_ts is not None and now_s > close_ts + _CLOSE_GRACE_S:
                    if ticker in known:
                        expired.append(ticker)
                    continue
                # Far-future windows are registered in archive_markets but
                # not subscribed — Kalshi lists days of 15m markets ahead.
                if open_ts is None or open_ts <= now_s + _DISCOVERY_OPEN_AHEAD_S:
                    desired.add(ticker)
                discovered_at_ns = time.time_ns()
                sem, execv = compute_contract_fingerprints(raw)
                meta[ticker] = {
                    "open_ts": open_ts,
                    "close_ts": close_ts,
                    "discovered_at_utc_ns": discovered_at_ns,
                    # Late = subscribed after the window opened (or open time
                    # unknown — we cannot prove complete coverage for it).
                    "discovery_late": open_ts is None or now_s > open_ts,
                    "db_row": {
                        "ticker": ticker,
                        "series": raw.get("series_ticker"),
                        "asset": raw.get("__asset__"),
                        "status": status,
                        "open_ts": open_ts,
                        "close_ts": close_ts,
                        "expiration_ts": _iso_to_ts(
                            raw.get("expiration_time")
                            or raw.get("expected_expiration_time")
                        ),
                        "contract_semantics_hash": sem,
                        "execution_metadata_version": execv,
                        "discovered_at_utc_ns": discovered_at_ns,
                        "last_seen_utc_ns": discovered_at_ns,
                        "raw_market": json.dumps(raw, default=str),
                    },
                }
            # Tickers that disappeared from discovery entirely.
            for ticker in known - desired:
                expired.append(ticker)

            discovery_results.put({"meta": meta, "expired": expired})
            if desired != known:
                print(
                    f"[book-archiver] ticker set: +{sorted(desired - known)}"
                    f" -{sorted(known - desired)}",
                    flush=True,
                )
                stream.set_tickers(sorted(desired))
                known = desired

            stop.wait(_DISCOVERY_S)

        try:
            loop.run_until_complete(client.close())
        except Exception:
            pass
        loop.close()

    # ── heartbeat + stats ──────────────────────────────────────────────
    def heartbeat_loop():
        import shutil

        while not stop.is_set():
            stop.wait(_HEARTBEAT_S)
            now_ns = time.time_ns()
            cov_summary = {}
            for (_, _, t), rec in tracker.records.items():
                age = (
                    round((now_ns - rec.last_event_recv_utc_ns) / 1e9, 1)
                    if rec.last_event_recv_utc_ns
                    else None
                )
                cov_summary[t] = {
                    "state": rec.state,
                    "last_seq": rec.last_seq,
                    "last_event_age_s": age,
                    "events": rec.event_count,
                    "gaps": rec.gap_count,
                }
            try:
                du = shutil.disk_usage(str(Path(_DB_PATH).parent))
                free_mb = int(du.free / 1e6)
            except Exception:
                free_mb = None
            db_mb = None
            try:
                db_mb = int(os.path.getsize(_DB_PATH) / 1e6)
            except Exception:
                pass
            hb = {
                "collector_instance_id": collector_id,
                "pid": os.getpid(),
                "ts_utc": datetime.now(timezone.utc).isoformat(),
                "db_path": _DB_PATH,
                "db_size_mb": db_mb,
                "disk_free_mb": free_mb,
                "queue_depth": ingest.depth,
                "overflow_total": ingest.overflow_total,
                "dropped_total": ingest.dropped_total,
                "write_errors": db.write_errors,
                "coverage": cov_summary,
                "connection_id": stream.connection_id,
            }
            try:
                tmp = Path(str(_HEARTBEAT_PATH) + ".tmp")
                tmp.write_text(json.dumps(hb, default=str))
                os.replace(tmp, _HEARTBEAT_PATH)
            except Exception as exc:
                print(f"[book-archiver] heartbeat write error: {exc}",
                      flush=True)

    def checkpoint_loop():
        # Dedicated connection: a synchronous checkpoint on the WRITER's
        # connection froze the drain for ~17-25min per fire on this disk
        # (the pragma copies the whole WAL within the call). WAL-mode
        # PASSIVE checkpoints on a second connection run concurrently with
        # writer commits, so the WAL stays bounded without stalling the
        # drain. Skips trivial WALs; the shutdown TRUNCATE covers exits.
        try:
            ck = sqlite3.connect(_DB_PATH, timeout=5)
        except Exception:
            return
        try:
            while not stop.is_set():
                stop.wait(60)
                try:
                    wal = _DB_PATH + "-wal"
                    if (not os.path.exists(wal)
                            or os.path.getsize(wal) < 8 * 1024 * 1024):
                        continue
                    # TRUNCATE while idle: resets the WAL file so a quiet
                    # gap bounds both file size and crash-recovery cost to
                    # "since the last quiet gap". PASSIVE while draining —
                    # it can run concurrently with writer commits.
                    mode = "TRUNCATE" if not ingest.depth else "PASSIVE"
                    ck.execute(f"PRAGMA wal_checkpoint({mode})")
                except Exception:
                    pass
        finally:
            try:
                ck.close()
            except Exception:
                pass

    def stats_loop():
        # Dedicated read connection: queries on the writer's connection
        # serialize behind in-flight transactions — during a long insert that
        # froze stats/heartbeat for ~25min (monitoring blind spot) and the
        # writer's own GIL reacquire raced the shared conn.
        try:
            ro = sqlite3.connect(
                f"file:{_DB_PATH}?mode=ro", uri=True, timeout=30)
        except Exception:
            ro = None
        while not stop.is_set():
            stop.wait(_STATS_EVERY_S)
            st = db.stats(ro) if ro else db.stats()
            line = "  ".join(
                f"{t}:{s.state}(e={s.event_count},g={s.gap_count})"
                for t, s in sorted(
                    (
                        (t, r)
                        for (cid, sid, t), r in tracker.records.items()
                    ),
                    key=lambda x: x[0],
                )[
                    :20
                ]
            )
            print(
                f"[book-archiver] {time.strftime('%H:%M:%S')} "
                f"events={st['events']} q={ingest.depth}"
                f"(ovf={ingest.overflow_total}) "
                f"iter_ms={writer_stats['iter_ms']} "
                f"batch={writer_stats['batch']} "
                f"drain={writer_stats['drain_ms']} "
                f"note={writer_stats['note_ms']} "
                f"ins={writer_stats['insert_ms']} "
                f"cov={writer_stats['cov_ms']} "
                f"oth={writer_stats['other_ms']} "
                f"dropped={ingest.dropped_total} werr={db.write_errors}  {line}",
                flush=True,
            )

    # ── run ────────────────────────────────────────────────────────────
    db.close_orphaned_sessions(live_connection_ids=[])
    _alert(ALERT_COLLECTOR_START, "info",
           f"collector {collector_id} starting db={_DB_PATH}")
    db.insert_alert(alerts_pending.pop())

    stream.start()
    threads = [
        threading.Thread(target=writer_loop, name="book-arch-writer",
                         daemon=True),
        threading.Thread(target=discovery_loop, name="book-arch-discovery",
                         daemon=True),
        threading.Thread(target=heartbeat_loop, name="book-arch-heartbeat",
                         daemon=True),
        threading.Thread(target=stats_loop, name="book-arch-stats",
                         daemon=True),
        threading.Thread(target=checkpoint_loop, name="book-arch-ckpt",
                         daemon=True),
    ]
    for t in threads:
        t.start()
    print(f"[book-archiver] archiving -> {_DB_PATH} collector={collector_id}",
          flush=True)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        stop.set()
        stream.stop()
        for t in threads:
            t.join(timeout=5)
        # Final session close.
        if stream.connection_id:
            db.close_session(
                stream.connection_id,
                disconnect_utc_ns=time.time_ns(),
                reason="collector_shutdown",
                msgs_received=msgs_by_conn.get(stream.connection_id, 0),
                subscription_map={},
            )
        db.close()
        try:
            Path(_LOCK_PATH).unlink(missing_ok=True)
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
