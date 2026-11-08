"""Calibration artifact freshness telemetry + scheduled refits.

2026-11-07: ``data/probability_tail_calibration.json`` went ~23 days stale
while refits stayed a manual step, and ``data/calibration/
walkforward_calibrator.json`` aged the same way — the tighten-only
streaming overlay kept the system conservative, but stale caps kept
inflating edge vetoes.  This module closes the ops gap:

* :func:`artifact_health_report` — per-artifact age/staleness for telemetry.
* :func:`write_calibration_health_status` — durable status file ops can
  alert on (``data/calibration_health.json``).
* :func:`maybe_run_scheduled_refits` — detached subprocess refits gated on
  artifact age, invoked from the settlement poller's periodic maintenance
  so the live decision path never blocks on a refit.

Refit scripts write to a ``*.refit-<pid>.tmp.json`` sibling which is
atomically ``os.replace``d onto the live artifact only after the script
exits 0 — a failed or killed refit can never leave a torn artifact behind,
and the mtime-aware loaders (``load_tail_calibrator``,
``_load_walkforward_calibrator``) hot-pick-up the new curve on the next
decision.  An orphaned tmp file after a process restart is inert.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[2]

# Artifact registry.  ``refit`` is None for self-refreshing artifacts —
# they are tracked for staleness telemetry only (their staleness signals
# upstream settlement/evidence starvation, not a missing refit).
_ARTIFACTS: List[Dict[str, Any]] = [
    {
        "name": "tail_calibration",
        "path": "data/probability_tail_calibration.json",
        "max_age_env": "MERID_TAIL_CALIBRATION_MAX_AGE_S",
        "max_age_default_s": 7 * 86400.0,
        "refit": {
            "script": "scripts/refit_tail_calibration.py",
            "args": [],  # temp output path appended by the scheduler
        },
    },
    {
        "name": "walkforward_calibrator",
        "path": "data/calibration/walkforward_calibrator.json",
        "max_age_env": "MERID_WALKFWD_CAL_MAX_AGE_S",
        "max_age_default_s": 14 * 86400.0,
        "refit": {
            "script": "scripts/build_walkforward_calibrator.py",
            "args": ["--days", "14"],
        },
    },
    {
        "name": "streaming_calibration",
        "path": "data/streaming_calibration.json",
        "max_age_env": "MERID_STREAMING_CAL_MAX_AGE_S",
        # Self-refreshing overlay; staleness here signals settlement/evidence
        # starvation upstream, not a missing refit.
        "max_age_default_s": 86400.0,
        "refit": None,
    },
    {
        "name": "live_entry_evidence",
        "path": "data/live_entry_evidence.json",
        "max_age_env": "MERID_LIVE_EVIDENCE_MAX_AGE_S",
        "max_age_default_s": 86400.0,
        "refit": None,
    },
]

_STATUS_PATH = _ROOT / "data" / "calibration_health.json"
_lock = threading.Lock()
_state: Dict[str, Any] = {
    "last_check_ts": 0.0,
    # name -> {"proc": Popen, "tmp": Path, "artifact": Path, "script": str}
    "refit_procs": {},
    "last_refit_attempt": {},  # name -> epoch of last spawn attempt
    "stale_warned": {},  # name -> bool, log-once-per-transition
}


def _max_age_s(spec: Dict[str, Any]) -> float:
    try:
        return float(os.environ.get(spec["max_age_env"], spec["max_age_default_s"]))
    except (TypeError, ValueError):
        return float(spec["max_age_default_s"])


def artifact_health_report(now: Optional[float] = None) -> Dict[str, Any]:
    """Per-artifact freshness report.

    Returns ``{name: {path, exists, age_s, max_age_s, stale, fitted_at}}``.
    ``age_s`` is time since file mtime; ``stale`` means older than the
    artifact's configured max age.  Missing artifacts report ``exists=False``
    and are always stale.
    """
    now_ts = now if now is not None else time.time()
    out: Dict[str, Any] = {}
    for spec in _ARTIFACTS:
        path = _ROOT / spec["path"]
        entry: Dict[str, Any] = {
            "path": spec["path"],
            "max_age_s": _max_age_s(spec),
            "exists": False,
            "age_s": None,
            "stale": True,
            "fitted_at": None,
        }
        try:
            st = path.stat()
            entry["exists"] = True
            entry["age_s"] = max(0.0, now_ts - st.st_mtime)
            entry["stale"] = entry["age_s"] > entry["max_age_s"]
            # fitted_at is informational only — mtime is the freshness truth
            # (a refit can rewrite the file without bumping embedded stamps).
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                entry["fitted_at"] = (
                    data.get("fitted_at_utc")
                    or (data.get("metadata") or {}).get("fit_time")
                )
            except Exception:
                pass
        except OSError:
            pass
        out[spec["name"]] = entry
    return out


def write_calibration_health_status(now: Optional[float] = None) -> Dict[str, Any]:
    """Persist the health report to ``data/calibration_health.json``.

    Atomic tmp+replace so a concurrent reader never sees a torn file.
    Returns the report for logging.
    """
    report = artifact_health_report(now)
    payload = {
        "ts": time.time(),
        "artifacts": report,
        "refit": {
            "running": sorted(_state.get("refit_procs") or {}),
            "last_attempt": dict(_state.get("last_refit_attempt") or {}),
        },
    }
    try:
        _STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _STATUS_PATH.with_suffix(_STATUS_PATH.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=1, default=str))
        os.replace(tmp, _STATUS_PATH)
    except Exception as exc:
        logger.debug("[CALIB-HEALTH] status write failed: %s", exc)
    return report


def _refit_interval_s() -> float:
    try:
        return float(os.environ.get("MERID_CALIBRATION_REFIT_INTERVAL_S", str(24 * 3600)))
    except (TypeError, ValueError):
        return 24 * 3600.0


def _check_interval_s() -> float:
    try:
        return float(os.environ.get("MERID_CALIBRATION_HEALTH_INTERVAL_S", "300"))
    except (TypeError, ValueError):
        return 300.0


def _poll_refit_procs() -> None:
    """Reap finished refit subprocesses; promote their output atomically.

    Called under ``_lock`` from the maintenance tick.  A refit that exited 0
    has its tmp artifact ``os.replace``d onto the live path — the mtime-aware
    loaders hot-pick it up on the next decision.  Failures drop the tmp file
    and leave the previous artifact untouched.
    """
    procs = _state.get("refit_procs") or {}
    for name in list(procs):
        job = procs[name]
        proc = job.get("proc")
        try:
            rc = proc.poll() if proc is not None else 0
        except Exception:
            rc = None
        if rc is None:
            continue  # still running
        tmp_path = Path(job["tmp"])
        artifact = Path(job["artifact"])
        if rc == 0 and tmp_path.exists():
            try:
                os.replace(tmp_path, artifact)
                logger.info(
                    "[CALIB-HEALTH] promoted refit artifact %s -> %s",
                    name,
                    artifact.name,
                )
            except Exception as exc:
                logger.warning(
                    "[CALIB-HEALTH] promote failed for %s: %s", name, exc
                )
        else:
            logger.warning(
                "[CALIB-HEALTH] refit %s exited rc=%s; keeping prior artifact",
                name,
                rc,
            )
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass
        procs.pop(name, None)


def _spawn_refit(spec: Dict[str, Any]) -> bool:
    """Spawn one refit script as a detached subprocess writing to a tmp path.

    The artifact is promoted by :func:`_poll_refit_procs` on a later
    maintenance tick once the script exits 0.  Returns True when spawned.
    """
    refit = spec.get("refit")
    if not refit:
        return False
    script = _ROOT / refit["script"]
    if not script.exists():
        logger.warning("[CALIB-HEALTH] refit script missing: %s", script)
        return False
    artifact = _ROOT / spec["path"]
    tmp_out = artifact.with_name(
        f"{artifact.name}.refit-{os.getpid()}-{int(time.time())}.tmp.json"
    )
    # Both refit scripts take the output path via --out (the walk-forward
    # builder gained the flag with this scheduler); extra args come first.
    cmd = (
        [sys.executable, str(script)]
        + [str(a) for a in (refit.get("args") or [])]
        + ["--out", str(tmp_out)]
    )
    log_path = _ROOT / "logs" / "calibration_refit.log"
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_f = open(log_path, "ab", buffering=0)
        proc = subprocess.Popen(
            cmd,
            cwd=str(_ROOT),
            stdout=log_f,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
        )
        _state.setdefault("refit_procs", {})[spec["name"]] = {
            "proc": proc,
            "tmp": str(tmp_out),
            "artifact": str(artifact),
            "script": str(script),
        }
        logger.info(
            "[CALIB-HEALTH] spawned refit for %s -> %s",
            spec["name"],
            tmp_out.name,
        )
        return True
    except Exception as exc:
        logger.warning("[CALIB-HEALTH] refit spawn failed for %s: %s", spec["name"], exc)
        return False


def maybe_run_scheduled_refits(now: Optional[float] = None) -> Dict[str, Any]:
    """Rate-limited maintenance entry point for the settlement poller.

    Cheap path: stat the artifacts and refresh the health file at most
    every ``MERID_CALIBRATION_HEALTH_INTERVAL_S`` (default 300s).  When an
    artifact with a refit script is older than its max age AND its last
    attempt is older than ``MERID_CALIBRATION_REFIT_INTERVAL_S`` (default
    24h), spawn the refit detached — at most one refit process at a time,
    refits serialized across maintenance ticks.
    """
    enabled = os.environ.get("MERID_CALIBRATION_REFIT_ENABLED", "1")
    if enabled != "1":
        return {}
    # Hermetic-test guard (same convention as the walk-forward calibrator
    # loader): under pytest the scheduler is off unless a test explicitly
    # sets MERID_CALIBRATION_REFIT_ENABLED — a stale machine-local artifact
    # must never spawn a real refit subprocess inside a test run.
    if (
        "PYTEST_CURRENT_TEST" in os.environ
        and "MERID_CALIBRATION_REFIT_ENABLED" not in os.environ
    ):
        return {}
    now_ts = now if now is not None else time.time()
    with _lock:
        _poll_refit_procs()
        if now_ts - float(_state.get("last_check_ts") or 0.0) < _check_interval_s():
            return {}
        _state["last_check_ts"] = now_ts
        report = write_calibration_health_status(now_ts)

        # Stale-transition warnings (log once per crossing, not per cycle).
        for name, entry in report.items():
            was = bool(_state["stale_warned"].get(name))
            if entry.get("stale") and not was:
                logger.warning(
                    "[CALIB-HEALTH] %s artifact stale: age=%s max=%ss path=%s",
                    name,
                    entry.get("age_s"),
                    entry.get("max_age_s"),
                    entry.get("path"),
                )
            _state["stale_warned"][name] = bool(entry.get("stale"))

        if _state.get("refit_procs"):
            return report  # one refit at a time; next tick continues

        refit_interval = _refit_interval_s()
        for spec in _ARTIFACTS:
            if spec.get("refit") is None:
                continue
            entry = report[spec["name"]]
            if not entry.get("stale"):
                continue
            last_attempt = float(
                (_state.get("last_refit_attempt") or {}).get(spec["name"]) or 0.0
            )
            if now_ts - last_attempt < refit_interval:
                continue
            # Record the attempt BEFORE spawning so a missing script or a
            # spawn failure backs off for the full refit interval instead of
            # re-warning every health tick.
            _state.setdefault("last_refit_attempt", {})[spec["name"]] = now_ts
            if _spawn_refit(spec):
                break  # serialize heavy jobs — one per maintenance tick
        return report
