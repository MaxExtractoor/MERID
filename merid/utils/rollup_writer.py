"""Bounded JSONL writer for low-frequency diagnostic aggregates.

2026-10-31: the async log queue drops records under backpressure — exactly
the burst windows ingestion diagnostics exist to measure.  Aggregates
(timing rollups, drain profiles) therefore write to their own JSONL
files instead of the app log.  This writer is the single owner of that
channel:

* bounded record frequency is the caller's responsibility (emit at most
  once per aggregation window — the writer itself never rate-limits,
  it just never blocks);
* bounded file size: the file is rotated at ``max_bytes`` into
  ``name.1``, ``name.2`` … up to ``backup_count``; older archives are
  deleted, so total disk use is capped;
* synchronous ``open/write/close`` per append — callers must only emit
  from worker threads or at aggregate cadence (once per >=30s), never
  per-message on the asyncio hot path;
* failures are counted on ``write_failures`` (never raised) so a dead
  disk cannot wedge the producer — callers surface the counter in
  their next emitted row.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional


class BoundedJsonlWriter:
    __slots__ = ("path", "max_bytes", "backup_count", "write_failures", "last_failure")

    def __init__(self, path: str, max_bytes: int = 20_000_000, backup_count: int = 3) -> None:
        self.path = path
        self.max_bytes = max_bytes
        self.backup_count = backup_count
        self.write_failures = 0
        self.last_failure: Optional[str] = None

    def append(self, row: Dict[str, Any]) -> bool:
        """Serialize + append one row.  Returns False (and counts) on failure."""
        try:
            if self.write_failures:
                row = dict(row)
                row["write_failures_total"] = self.write_failures
            line = json.dumps(row, default=str)
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            self._rotate_if_needed(len(line) + 1)
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
            return True
        except Exception as exc:  # never propagate I/O faults into producers
            self.write_failures += 1
            self.last_failure = f"{type(exc).__name__}: {exc}"
            return False

    def _rotate_if_needed(self, incoming: int) -> None:
        try:
            if os.path.getsize(self.path) + incoming <= self.max_bytes:
                return
        except OSError:
            return  # file does not exist yet — nothing to rotate
        for idx in range(self.backup_count - 1, 0, -1):
            src = f"{self.path}.{idx}"
            dst = f"{self.path}.{idx + 1}"
            try:
                if os.path.exists(src):
                    if idx + 1 > self.backup_count:
                        os.remove(src)
                    else:
                        os.replace(src, dst)
            except OSError:
                pass
        try:
            os.replace(self.path, f"{self.path}.1")
        except OSError:
            pass
