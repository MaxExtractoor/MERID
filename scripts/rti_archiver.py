#!/usr/bin/env python
"""Archive Kalshi ``cfbenchmarks_value`` RTI frames to ``data/cf_rti_ticks.db``.

Standalone collector: opens its own authenticated Kalshi WebSocket (same
credentials as the trading loop, broadcast market-data channel) and persists
every frame — value, CF's rolling 60s average, the 15-minute windowed 60s
average, source/receive timestamps, seq — plus the raw payload.

Purpose: the decision-audit DB loses ``settlement_reference_price`` in the
final ~40-70s of each 15-minute window, so open/close 60s settlement bands
cannot be reconstructed retrospectively.  This archive provides tick-level
coverage *through* the boundary, enabling exact Kalshi settlement replay.

Safety: read-only data collection — no order endpoints are touched; the
``cfbenchmarks_value`` channel is a broadcast feed.  Runs independently of the
trading server so restarts do not create coverage gaps.

Usage:
    .venv\\Scripts\\python.exe scripts\\rti_archiver.py            # foreground
    Register via start_15m.ps1 or Task Scheduler for always-on collection.

Env:
    MERID_RTI_TICK_DB             output path (default data/cf_rti_ticks.db)
    MERID_RTI_TICK_RETENTION_DAYS prune horizon (default 10)
    MERID_CFB_RTI_WS_URL          endpoint override (default Kalshi prod)
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import threading
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

# pythonw.exe (scheduled-task mode) has no console: sys.stdout is None.
# Redirect BEFORE importing merid modules so their loggers bind to the file.
if sys.stdout is None:
    _log = open(_REPO_ROOT / "data" / "rti_archiver.log", "a", buffering=1)
    sys.stdout = sys.stderr = _log

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_REPO_ROOT / ".env")

from merid.data.kalshi_cf_rti_ws import (  # noqa: E402
    KalshiCfRtiStream,
    index_id_to_asset,
)

_DB_PATH = os.environ.get(
    "MERID_RTI_TICK_DB", str(_REPO_ROOT / "data" / "cf_rti_ticks.db")
)
_RETENTION_S = float(os.environ.get("MERID_RTI_TICK_RETENTION_DAYS", "10")) * 86400.0
_PRUNE_EVERY_S = 900.0
_STATS_EVERY_S = 60.0

# Kalshi broadcasts every CF index on this channel; only archive the assets the
# 15m strategy trades (override via MERID_RTI_TICK_ASSETS=BTC,ETH,...).
_ASSET_ALLOWLIST = {
    a.strip().upper()
    for a in os.environ.get(
        "MERID_RTI_TICK_ASSETS", "BTC,ETH,SOL,XRP,DOGE"
    ).split(",")
    if a.strip()
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS rti_ticks(
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  index_id      TEXT NOT NULL,
  asset         TEXT,
  src_ts_ms     INTEGER,      -- upstream CF timestamp (normalized to ms)
  recv_ts_ms    INTEGER,      -- Kalshi received_at (ms)
  local_ts_ms   INTEGER NOT NULL,
  value         REAL,
  avg_60s       REAL,         -- CF rolling 60-second average
  avg_60s_15m   REAL,         -- last_60s_windowed_average_15min (settlement band)
  seq           INTEGER,
  lag_ms        INTEGER,      -- consumer event-loop lag
  raw_json      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rti_ticks_asset_ts ON rti_ticks(asset, local_ts_ms);
CREATE INDEX IF NOT EXISTS idx_rti_ticks_idx_ts   ON rti_ticks(index_id, local_ts_ms);
-- Expression index so band queries on the effective tick timestamp stay O(log n):
CREATE INDEX IF NOT EXISTS idx_rti_ticks_asset_effts ON rti_ticks(
    asset, COALESCE(src_ts_ms, recv_ts_ms, local_ts_ms));
"""

_VALUE_KEYS = ("value", "price", "last", "index_value", "rti")
_TS_KEYS = ("source_ts_ms", "ts", "timestamp", "time", "published_at")


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _src_ts_ms(data: dict, fallback_ms: int | None) -> int | None:
    for k in _TS_KEYS:
        v = _num(data.get(k))
        if v is None:
            continue
        if v > 1e12:
            return int(v)
        if v > 1e9:
            return int(v * 1000)
    return fallback_ms


def main() -> int:
    out = Path(_DB_PATH)
    out.parent.mkdir(parents=True, exist_ok=True)

    db = sqlite3.connect(str(out), check_same_thread=False)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=NORMAL")
    db.executescript(_SCHEMA)
    db.commit()

    lock = threading.Lock()
    pending: list[tuple] = []
    stats: dict[str, dict] = {}
    stop = threading.Event()

    def on_frame(frame) -> None:
        asset = index_id_to_asset(frame.index_id)
        if asset is None or asset not in _ASSET_ALLOWLIST:
            stats.setdefault("__skipped__", {"n": 0, "last_ms": 0})["n"] += 1
            return
        d = frame.data or {}
        now_ms = int(time.time() * 1000)
        recv = d.get("received_at")
        row = (
            frame.index_id,
            asset,
            _src_ts_ms(d, int(recv) if recv else None),
            int(recv) if recv else None,
            now_ms,
            _num(d.get("value")),
            _num(d.get("average_60s")),
            _num(d.get("last_60s_average_15min")),
            d.get("seq"),
            d.get("event_loop_lag_ms"),
            json.dumps(d, default=str),
        )
        s = stats.setdefault(asset, {"n": 0, "last_ms": 0})
        s["n"] += 1
        s["last_ms"] = now_ms
        with lock:
            pending.append(row)

    def writer_loop() -> None:
        last_prune = time.monotonic()
        while not stop.is_set() or pending:
            time.sleep(0.25)
            with lock:
                batch, pending[:] = pending[:], []
            if batch:
                try:
                    db.executemany(
                        "INSERT INTO rti_ticks(index_id,asset,src_ts_ms,recv_ts_ms,"
                        "local_ts_ms,value,avg_60s,avg_60s_15m,seq,lag_ms,raw_json)"
                        " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                        batch,
                    )
                    db.commit()
                except Exception as exc:  # keep collecting; log and drop batch
                    print(f"[rti-archiver] write error: {exc}", flush=True)
            if time.monotonic() - last_prune > _PRUNE_EVERY_S:
                last_prune = time.monotonic()
                cutoff = int((time.time() - _RETENTION_S) * 1000)
                db.execute("DELETE FROM rti_ticks WHERE local_ts_ms < ?", (cutoff,))
                db.commit()
                db.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def stats_loop() -> None:
        while not stop.is_set():
            time.sleep(_STATS_EVERY_S)
            now_ms = int(time.time() * 1000)
            line = "  ".join(
                f"{a}: n={s['n']}" + (
                    f" last={(now_ms - s['last_ms']) / 1000:.1f}s"
                    if s["last_ms"] else ""
                )
                for a, s in sorted(stats.items())
            )
            print(f"[rti-archiver] {time.strftime('%H:%M:%S')}  {line}", flush=True)

    stream = KalshiCfRtiStream(on_frame=on_frame)
    stream.start()
    w = threading.Thread(target=writer_loop, daemon=True)
    t = threading.Thread(target=stats_loop, daemon=True)
    w.start()
    t.start()
    print(f"[rti-archiver] archiving -> {out}", flush=True)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        stop.set()
        stream.stop()
        w.join(timeout=5)
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
