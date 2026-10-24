#!/usr/bin/env python
"""Independent supervisor for the MERID 15m production process.

2026-10-24: tonight the server died three ways — two native access
violations (``python311.dll`` 0xc0000005 under market-data bursts) and one
silent stall (log went quiet at 04:05:26, process still "running", no
crash event).  Process-name polling catches neither the stall nor proves
forward progress.  This watchdog uses forward-progress signals:

  * port listener on the bound dashboard port,
  * ``decision_audit_heartbeats`` freshness (the loop's own liveness write),
  * ``logs/full.log`` mtime freshness (last-ditch signal),

and restarts through the canonical ``start_15m.ps1`` path — the same path
an operator restart takes, so preflight and the startup state machine
still govern whether entries re-enable.  Restarts are bounded:

  * max ``MERID_WATCHDOG_MAX_RESTARTS_PER_HOUR`` (default 3) per rolling
    hour, then the watchdog keeps monitoring and emits
    ``watchdog_budget_exhausted`` receipts instead of restart-looping,
  * min ``MERID_WATCHDOG_RESTART_COOLDOWN_S`` (default 60) between
    restarts,
  * a failure must persist ``MERID_WATCHDOG_MISS_THRESHOLD`` consecutive
    polls (default 3) before acting — single-poll blips are logged, not
    acted on,
  * a process younger than ``MERID_WATCHDOG_MIN_UPTIME_S`` (default 120)
    is still in preflight; stalls don't count.

``MERID_WATCHDOG_AUTO_RESTART=0`` makes it observe-only (receipts still
written).  Receipts append to ``logs/watchdog_receipts.jsonl`` so the
supervision decisions are themselves auditable.

Usage:  .\\.venv\\Scripts\\python.exe watchdog_15m.py
"""

from __future__ import annotations

import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent
LOG_DIR = REPO / "logs"
RECEIPTS_PATH = LOG_DIR / "watchdog_receipts.jsonl"
FULL_LOG = LOG_DIR / "full.log"
DECISION_AUDIT_DB = REPO / "decision_audit.db"
START_SCRIPT = REPO / "start_15m.ps1"


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _auto_restart_enabled() -> bool:
    return os.getenv("MERID_WATCHDOG_AUTO_RESTART", "1").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _port_listening(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=2.0):
            return True
    except OSError:
        return False


def _log_mtime_age_s(now: float) -> float | None:
    try:
        return now - FULL_LOG.stat().st_mtime
    except OSError:
        return None


def _heartbeat_age_s(now: float) -> float | None:
    """Age of the freshest loop heartbeat; None when unreadable/absent.

    Read-only with a short busy timeout — the live writer holds the db in
    WAL, and a blocked reader must fail fast rather than queue behind it.
    """
    if not DECISION_AUDIT_DB.exists():
        return None
    try:
        conn = sqlite3.connect(
            f"file:{DECISION_AUDIT_DB}?mode=ro", uri=True, timeout=0.5
        )
        try:
            conn.execute("PRAGMA busy_timeout=500")
            row = conn.execute(
                "SELECT MAX(created_at) FROM decision_audit_heartbeats"
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return None
    if not row or row[0] is None:
        return None
    try:
        ts = float(row[0])
    except (TypeError, ValueError):
        return None
    # created_at may be epoch or ISO; epoch assumed below 1e13.
    return now - ts if ts < 1e13 else None


def collect_status(now: float, port: int) -> dict:
    """Snapshot of forward-progress signals for one poll."""
    return {
        "port_listening": _port_listening(port),
        "heartbeat_age_s": _heartbeat_age_s(now),
        "log_age_s": _log_mtime_age_s(now),
    }


def signals_failed(status: dict, stale_s: float) -> list:
    """Which forward-progress signals are dead right now."""
    failed = []
    if not status.get("port_listening"):
        failed.append("port_closed")
    hb = status.get("heartbeat_age_s")
    log_age = status.get("log_age_s")
    # Heartbeat is primary; when the table is unreadable fall back to the
    # log mtime (the stall tonight showed as log silence).
    if hb is not None:
        if hb > stale_s:
            failed.append("heartbeat_stale")
    elif log_age is None or log_age > stale_s:
        failed.append("log_silent")
    return failed


def decide(
    failed_signals: list,
    consecutive_misses: int,
    restart_times: list,
    last_restart_at: float | None,
    now: float,
    *,
    miss_threshold: int = 3,
    max_restarts_per_hour: int = 3,
    cooldown_s: float = 60.0,
    auto_restart: bool = True,
) -> tuple[str, list, int]:
    """Pure supervision decision — returns (action, restart_times, misses).

    Actions: ``ok`` (healthy), ``wait`` (failing but below threshold or in
    cooldown), ``restart``, ``budget_exhausted`` (failing, out of budget),
    ``observe`` (failing but auto_restart disabled).
    """
    if not failed_signals:
        return "ok", [t for t in restart_times if now - t < 3600.0], 0
    misses = consecutive_misses + 1
    if misses < miss_threshold:
        return "wait", restart_times, misses
    if not auto_restart:
        return "observe", restart_times, misses
    window = [t for t in restart_times if now - t < 3600.0]
    if len(window) >= max_restarts_per_hour:
        return "budget_exhausted", window, misses
    if last_restart_at is not None and now - last_restart_at < cooldown_s:
        return "wait", window, misses
    return "restart", window, misses


def _server_uptime_s(now: float) -> float | None:
    """Age of the youngest uvicorn/pid marker we can see; None if unknown."""
    pid_file = LOG_DIR / "server_pid.txt"
    try:
        if pid_file.exists():
            return now - pid_file.stat().st_mtime
    except OSError:
        pass
    return None


def _restart(now: float) -> dict:
    """Launch the canonical start path detached; return receipt fields."""
    receipt = {"restart_invoked_at": _utcnow_iso(), "start_script": str(START_SCRIPT)}
    try:
        proc = subprocess.Popen(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(START_SCRIPT),
            ],
            cwd=str(REPO),
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "DETACHED_PROCESS", 0),
        )
        receipt["launcher_pid"] = proc.pid
        receipt["launch_error"] = None
    except OSError as exc:  # pragma: no cover - platform failure path
        receipt["launcher_pid"] = None
        receipt["launch_error"] = str(exc)
    return receipt


def _emit(receipt: dict) -> None:
    receipt.setdefault("ts", _utcnow_iso())
    try:
        LOG_DIR.mkdir(exist_ok=True)
        with RECEIPTS_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(receipt, default=str) + "\n")
    except OSError:
        pass


def main() -> int:
    port = _env_int("MERID_WATCHDOG_PORT", 8011)
    poll_s = _env_float("MERID_WATCHDOG_POLL_S", 15.0)
    stale_s = _env_float("MERID_WATCHDOG_STALE_S", 90.0)
    miss_threshold = _env_int("MERID_WATCHDOG_MISS_THRESHOLD", 3)
    max_restarts = _env_int("MERID_WATCHDOG_MAX_RESTARTS_PER_HOUR", 3)
    cooldown_s = _env_float("MERID_WATCHDOG_RESTART_COOLDOWN_S", 60.0)
    min_uptime_s = _env_float("MERID_WATCHDOG_MIN_UPTIME_S", 120.0)
    auto_restart = _auto_restart_enabled()

    restart_times: list = []
    last_restart_at: float | None = None
    misses = 0

    _emit(
        {
            "event": "watchdog_started",
            "port": port,
            "poll_s": poll_s,
            "stale_s": stale_s,
            "miss_threshold": miss_threshold,
            "max_restarts_per_hour": max_restarts,
            "cooldown_s": cooldown_s,
            "auto_restart": auto_restart,
        }
    )

    while True:
        now = time.time()
        status = collect_status(now, port)
        failed = signals_failed(status, stale_s)

        uptime = _server_uptime_s(now)
        if failed and uptime is not None and uptime < min_uptime_s:
            failed = [f for f in failed if f != "heartbeat_stale"]

        action, restart_times, misses = decide(
            failed,
            misses,
            restart_times,
            last_restart_at,
            now,
            miss_threshold=miss_threshold,
            max_restarts_per_hour=max_restarts,
            cooldown_s=cooldown_s,
            auto_restart=auto_restart,
        )

        if action != "ok" or misses:
            _emit(
                {
                    "event": "watchdog_poll",
                    "action": action,
                    "failed": failed,
                    "misses": misses,
                    "status": status,
                    "restarts_last_hour": len(restart_times),
                }
            )

        if action == "restart":
            receipt = _restart(now)
            last_restart_at = now
            restart_times.append(now)
            misses = 0
            _emit(
                {
                    "event": "watchdog_restart",
                    "failed": failed,
                    "status": status,
                    **receipt,
                }
            )
        elif action == "budget_exhausted":
            _emit(
                {
                    "event": "watchdog_budget_exhausted",
                    "failed": failed,
                    "restarts_last_hour": len(restart_times),
                }
            )

        time.sleep(poll_s)


if __name__ == "__main__":
    sys.exit(main())
