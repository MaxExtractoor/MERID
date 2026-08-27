"""
FVG wrong-side monitor.

Compares FVG-influenced live trades against non-FVG live trades by computing
model-side alignment from ``shadow_side_telemetry.jsonl``.  A trade is flagged
as "wrong-side in expectation" when the live selected side disagrees with the
model's own p_yes estimate (e.g. selected YES when p_yes_model < 0.5).

When the FVG-influenced wrong-side rate exceeds the non-FVG baseline by a
configurable margin, the monitor writes a kill-switch file and/or emits a
structured alert so the FVG layer can be disabled without stopping trading.

The monitor is intentionally decoupled from production execution so it can be
run as a separate process, a cron job, or an in-process health check.

Usage::

    from merid.monitoring.fvg_wrong_side_monitor import FVGWrongSideMonitor
    monitor = FVGWrongSideMonitor()
    report = monitor.check_file("data/logs/shadow_side_telemetry.jsonl")
    if report.fvg_mismatch_rate - report.non_fvg_mismatch_rate > 0.20:
        report.write_kill_switch()
"""

from __future__ import annotations

import json
import math
import os
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence
from collections import deque

try:
    from utils.logger import get_logger
    logger = get_logger("merid.monitoring.fvg_wrong_side_monitor")
except Exception:
    import logging
    logger = logging.getLogger("merid.monitoring.fvg_wrong_side_monitor")


_DEFAULT_TELEMETRY_PATH = os.environ.get(
    "MERID_SHADOW_TELEMETRY_PATH",
    "data/logs/shadow_side_telemetry.jsonl",
)
_DEFAULT_KILL_SWITCH_PATH = os.environ.get(
    "MERID_FVG_KILL_SWITCH_PATH",
    "data/fvg_kill_switch.json",
)
_DEFAULT_ALERT_THRESHOLD = float(os.environ.get("MERID_FVG_ALERT_THRESHOLD", "0.20"))
_DEFAULT_ABSOLUTE_THRESHOLD = float(os.environ.get("MERID_FVG_ABSOLUTE_THRESHOLD", "0.40"))
_DEFAULT_WINDOW_RECORDS = int(os.environ.get("MERID_FVG_WINDOW_RECORDS", "500"))
_DEFAULT_WINDOW_MINUTES = int(os.environ.get("MERID_FVG_WINDOW_MINUTES", "60"))
_DEFAULT_SLEEP_SECONDS = float(os.environ.get("MERID_FVG_MONITOR_SLEEP_SECONDS", "60"))


@dataclass
class FVGWrongSideReport:
    """Summary of a wrong-side comparison window."""

    timestamp_utc: str
    window_records: int
    window_minutes: float
    fvg_count: int
    fvg_mismatch_count: int
    fvg_mismatch_rate: float
    non_fvg_count: int
    non_fvg_mismatch_count: int
    non_fvg_mismatch_rate: float
    rate_delta: float
    alert: bool
    alert_reason: Optional[str] = None
    kill_switch_path: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def write_kill_switch(self, reason: str, path: Optional[str] = None) -> Path:
        """Persist a kill switch that live processes can poll to disable FVG."""
        kill_path = Path(path or self.kill_switch_path or _DEFAULT_KILL_SWITCH_PATH)
        kill_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "fvg_enabled": False,
            "reason": reason,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "report": self.to_dict(),
        }
        kill_path.write_text(json.dumps(payload, indent=2))
        logger.warning("[FVG-MONITOR] Kill switch written to %s: %s", kill_path, reason)
        return kill_path


def _is_fvg_influenced(record: Dict[str, Any]) -> bool:
    """Return True if the record carries a non-zero FVG contribution."""
    # Primary source: the hybrid_probability dict, which contains fvg_delta.
    hybrid = record.get("hybrid_probability") or {}
    if isinstance(hybrid, dict) and abs(float(hybrid.get("fvg_delta", 0.0) or 0.0)) > 0.0:
        return True

    # Fallback to extra fields if shadow telemetry uses a different schema.
    extra = record.get("extra") or {}
    if isinstance(extra, dict) and (
        extra.get("fvg_influenced")
        or abs(float(extra.get("fvg_delta", 0.0) or 0.0)) > 0.0
    ):
        return True

    # Last resort: explicit fvg_* fields on the record.
    if (
        record.get("fvg_active")
        or abs(float(record.get("fvg_delta", 0.0) or 0.0)) > 0.0
    ):
        return True

    return False


def _is_model_aligned(record: Dict[str, Any]) -> Optional[bool]:
    """Return True when the live selected side is aligned with the model p_yes.

    A return of ``None`` means the record cannot be classified (missing side
    or invalid probability).  This is *not* a realized PnL check; it is the
    fastest wrong-side proxy available before settlement.
    """
    selected_side = record.get("live", {}).get("selected_side")
    p_yes_model = record.get("p_yes_model")

    if selected_side not in ("yes", "no"):
        return None
    if p_yes_model is None:
        return None

    p_yes = float(p_yes_model)
    if not math.isfinite(p_yes) or p_yes < 0.0 or p_yes > 1.0:
        return None

    # Selected YES is "aligned" when the model thinks YES is more likely than NO.
    # Selected NO is "aligned" when the model thinks YES is less likely than NO.
    if selected_side == "yes":
        return p_yes > 0.5
    else:
        return p_yes < 0.5


def _parse_record_timestamp(record: Dict[str, Any]) -> Optional[float]:
    """Best-effort wall-clock timestamp for window filtering."""
    ts = record.get("timestamp_utc") or record.get("timestamp")
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts)).timestamp()
    except Exception:
        return None


class FVGWrongSideMonitor:
    """In-memory or file-backed monitor for FVG wrong-side drift."""

    def __init__(
        self,
        alert_threshold: float = _DEFAULT_ALERT_THRESHOLD,
        absolute_threshold: float = _DEFAULT_ABSOLUTE_THRESHOLD,
        window_records: int = _DEFAULT_WINDOW_RECORDS,
        window_minutes: int = _DEFAULT_WINDOW_MINUTES,
        kill_switch_path: Optional[str] = None,
    ) -> None:
        self.alert_threshold = alert_threshold
        self.absolute_threshold = absolute_threshold
        self.window_records = window_records
        self.window_minutes = window_minutes
        self.kill_switch_path = kill_switch_path or _DEFAULT_KILL_SWITCH_PATH

    def evaluate_records(self, records: Sequence[Dict[str, Any]]) -> FVGWrongSideReport:
        """Compute wrong-side mismatch rates over the supplied records."""
        # Keep only records within the rolling window.
        cutoff_ts = (datetime.now(timezone.utc) - timedelta(minutes=self.window_minutes)).timestamp()
        recent = []
        for rec in reversed(records):
            ts = _parse_record_timestamp(rec)
            if ts is not None and ts < cutoff_ts:
                continue
            recent.append(rec)
            if len(recent) >= self.window_records:
                break
        recent.reverse()

        fvg_count = 0
        fvg_mismatch = 0
        non_fvg_count = 0
        non_fvg_mismatch = 0
        oldest_ts: Optional[float] = None
        newest_ts: Optional[float] = None

        for rec in recent:
            aligned = _is_model_aligned(rec)
            if aligned is None:
                continue

            ts = _parse_record_timestamp(rec)
            if ts is not None:
                if oldest_ts is None or ts < oldest_ts:
                    oldest_ts = ts
                if newest_ts is None or ts > newest_ts:
                    newest_ts = ts

            if _is_fvg_influenced(rec):
                fvg_count += 1
                if not aligned:
                    fvg_mismatch += 1
            else:
                non_fvg_count += 1
                if not aligned:
                    non_fvg_mismatch += 1

        fvg_rate = fvg_mismatch / fvg_count if fvg_count > 0 else 0.0
        non_fvg_rate = non_fvg_mismatch / non_fvg_count if non_fvg_count > 0 else 0.0
        rate_delta = fvg_rate - non_fvg_rate

        window_minutes = 0.0
        if oldest_ts is not None and newest_ts is not None:
            window_minutes = (newest_ts - oldest_ts) / 60.0

        alert = False
        alert_reason: Optional[str] = None
        if fvg_count >= 5 and rate_delta > self.alert_threshold:
            alert = True
            alert_reason = (
                f"FVG wrong-side rate {fvg_rate:.2%} exceeds non-FVG "
                f"baseline {non_fvg_rate:.2%} by {rate_delta:.2%} "
                f"(threshold {self.alert_threshold:.2%})"
            )
        elif fvg_count >= 5 and fvg_rate > self.absolute_threshold:
            alert = True
            alert_reason = (
                f"FVG wrong-side rate {fvg_rate:.2%} exceeds absolute "
                f"threshold {self.absolute_threshold:.2%}"
            )

        return FVGWrongSideReport(
            timestamp_utc=datetime.now(timezone.utc).isoformat(),
            window_records=len(recent),
            window_minutes=window_minutes,
            fvg_count=fvg_count,
            fvg_mismatch_count=fvg_mismatch,
            fvg_mismatch_rate=fvg_rate,
            non_fvg_count=non_fvg_count,
            non_fvg_mismatch_count=non_fvg_mismatch,
            non_fvg_mismatch_rate=non_fvg_rate,
            rate_delta=rate_delta,
            alert=alert,
            alert_reason=alert_reason,
            kill_switch_path=self.kill_switch_path,
        )

    def read_records(self, path: str) -> List[Dict[str, Any]]:
        """Read JSONL records from ``path``.  Missing or unreadable files are non-fatal."""
        records: List[Dict[str, Any]] = []
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        logger.debug("[FVG-MONITOR] Skipping malformed JSONL line in %s", path)
        except FileNotFoundError:
            logger.debug("[FVG-MONITOR] Telemetry file not found: %s", path)
        except Exception as exc:
            logger.warning("[FVG-MONITOR] Failed to read %s: %s", path, exc)
        return records

    def check_file(self, path: Optional[str] = None) -> FVGWrongSideReport:
        """Evaluate a single telemetry file and optionally trigger alerts."""
        path = path or _DEFAULT_TELEMETRY_PATH
        records = self.read_records(path)
        report = self.evaluate_records(records)

        if report.alert:
            logger.warning(
                "[FVG-MONITOR-ALERT] %s fvg_count=%d non_fvg_count=%d "
                "fvg_rate=%.2f%% non_fvg_rate=%.2f%% delta=%+.2f%%",
                report.alert_reason,
                report.fvg_count,
                report.non_fvg_count,
                report.fvg_mismatch_rate * 100.0,
                report.non_fvg_mismatch_rate * 100.0,
                report.rate_delta * 100.0,
            )
            report.write_kill_switch(report.alert_reason or "fvg_wrong_side_alert", self.kill_switch_path)
        else:
            logger.info(
                "[FVG-MONITOR] fvg_count=%d non_fvg_count=%d "
                "fvg_rate=%.2f%% non_fvg_rate=%.2f%% delta=%+.2f%%",
                report.fvg_count,
                report.non_fvg_count,
                report.fvg_mismatch_rate * 100.0,
                report.non_fvg_mismatch_rate * 100.0,
                report.rate_delta * 100.0,
            )

        return report

    def run_tailing(self, path: Optional[str] = None, sleep_seconds: Optional[float] = None) -> None:
        """Tail a telemetry file and re-evaluate the window at intervals.

        This is intended to be run as a background process.  It does not follow
        the file by tailing new lines; it re-reads the file each cycle, which is
        acceptable for modest telemetry volumes.
        """
        path = path or _DEFAULT_TELEMETRY_PATH
        sleep = sleep_seconds or _DEFAULT_SLEEP_SECONDS

        logger.info("[FVG-MONITOR] Starting tailing monitor for %s (sleep=%.1fs)", path, sleep)
        while True:
            try:
                self.check_file(path)
            except Exception as exc:
                logger.error("[FVG-MONITOR] Check failed: %s", exc)
            time.sleep(sleep)


def run_monitor() -> None:
    """CLI entry point: ``python -m merid.monitoring.fvg_wrong_side_monitor``."""
    import argparse

    parser = argparse.ArgumentParser(description="FVG wrong-side monitor")
    parser.add_argument(
        "--telemetry",
        default=_DEFAULT_TELEMETRY_PATH,
        help="Path to shadow_side_telemetry.jsonl",
    )
    parser.add_argument(
        "--kill-switch",
        default=_DEFAULT_KILL_SWITCH_PATH,
        help="Path to write the FVG kill switch",
    )
    parser.add_argument(
        "--alert-threshold",
        type=float,
        default=_DEFAULT_ALERT_THRESHOLD,
        help="Rate-delta threshold that triggers an alert",
    )
    parser.add_argument(
        "--absolute-threshold",
        type=float,
        default=_DEFAULT_ABSOLUTE_THRESHOLD,
        help="Absolute FVG wrong-side rate threshold",
    )
    parser.add_argument(
        "--window-records",
        type=int,
        default=_DEFAULT_WINDOW_RECORDS,
        help="Maximum records in the rolling window",
    )
    parser.add_argument(
        "--window-minutes",
        type=int,
        default=_DEFAULT_WINDOW_MINUTES,
        help="Maximum age of records in the rolling window",
    )
    parser.add_argument(
        "--tail",
        action="store_true",
        help="Run in tailing mode",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=_DEFAULT_SLEEP_SECONDS,
        help="Sleep interval in tailing mode",
    )

    args = parser.parse_args()

    monitor = FVGWrongSideMonitor(
        alert_threshold=args.alert_threshold,
        absolute_threshold=args.absolute_threshold,
        window_records=args.window_records,
        window_minutes=args.window_minutes,
        kill_switch_path=args.kill_switch,
    )

    if args.tail:
        monitor.run_tailing(args.telemetry, args.sleep)
    else:
        report = monitor.check_file(args.telemetry)
        print(json.dumps(report.to_dict(), indent=2))


if __name__ == "__main__":
    run_monitor()
