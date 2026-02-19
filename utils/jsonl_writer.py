"""Rotating JSONL writer for audit trails and tick logs.

Provides size-capped, append-only JSON-lines files with automatic rotation.
Detects write failures so callers can alert on disk-full or permission errors.

Usage:
    from utils.jsonl_writer import JsonlWriter
    writer = JsonlWriter("data/audit/audit_log.jsonl", max_bytes=10_000_000, backup_count=3)
    writer.append({"event": "trade", "symbol": "BTC/USD", "ts": time.time()})
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from threading import Lock
from typing import Any, Dict, Optional


class JsonlWriter:
    """Thread-safe, rotating JSONL file writer.

    Parameters
    ----------
    path : str | Path
        File path for the JSONL log.
    max_bytes : int
        Maximum file size before rotation (default 10 MB).
    backup_count : int
        Number of rotated backups to keep (default 3).
    """

    def __init__(
        self,
        path: str | Path,
        max_bytes: int = 10_000_000,
        backup_count: int = 3,
    ):
        self.path = Path(path)
        self.max_bytes = max_bytes
        self.backup_count = backup_count
        self._lock = Lock()
        self._write_errors: int = 0
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, record: Dict[str, Any]) -> bool:
        """Append a JSON record as a single line.  Returns True on success."""
        line = json.dumps(record, default=str) + "\n"
        with self._lock:
            try:
                self._maybe_rotate()
                with open(self.path, "a", encoding="utf-8") as f:
                    f.write(line)
                return True
            except Exception:
                self._write_errors += 1
                return False

    def _maybe_rotate(self) -> None:
        """Rotate the file if it exceeds max_bytes."""
        if not self.path.exists():
            return
        try:
            size = self.path.stat().st_size
        except OSError:
            return
        if size < self.max_bytes:
            return

        # Shift existing backups
        for i in range(self.backup_count - 1, 0, -1):
            src = self.path.with_suffix(f".jsonl.{i}")
            dst = self.path.with_suffix(f".jsonl.{i + 1}")
            if src.exists():
                try:
                    if dst.exists():
                        os.remove(dst)
                    os.rename(src, dst)
                except OSError:
                    pass

        # Move current → .1
        dst = self.path.with_suffix(f".jsonl.1")
        try:
            if dst.exists():
                os.remove(dst)
            os.rename(self.path, dst)
        except OSError:
            pass

    @property
    def write_errors(self) -> int:
        """Number of write failures since creation."""
        return self._write_errors

    def healthy(self) -> bool:
        """Return True if no write errors have occurred."""
        return self._write_errors == 0

    def stats(self) -> Dict[str, Any]:
        """Return diagnostics for monitoring."""
        size = 0
        try:
            if self.path.exists():
                size = self.path.stat().st_size
        except OSError:
            pass
        return {
            "path": str(self.path),
            "size_bytes": size,
            "max_bytes": self.max_bytes,
            "backup_count": self.backup_count,
            "write_errors": self._write_errors,
            "healthy": self.healthy(),
        }


# ── Module-level singletons for common log files ──────────────────────

_audit_writer: Optional[JsonlWriter] = None
_tick_writer: Optional[JsonlWriter] = None


def get_audit_writer() -> JsonlWriter:
    """Return the singleton audit-trail JSONL writer."""
    global _audit_writer
    if _audit_writer is None:
        _audit_writer = JsonlWriter(
            "data/audit/audit_log.jsonl",
            max_bytes=10_000_000,  # 10 MB
            backup_count=3,
        )
    return _audit_writer


def get_tick_writer() -> JsonlWriter:
    """Return the singleton tick-log JSONL writer."""
    global _tick_writer
    if _tick_writer is None:
        _tick_writer = JsonlWriter(
            "data/logs/merid_ticks.jsonl",
            max_bytes=5_000_000,  # 5 MB
            backup_count=5,
        )
    return _tick_writer
