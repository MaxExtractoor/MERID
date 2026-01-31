from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Iterable, Optional


class AuditBackend:
    """Abstract audit backend interface."""

    def append(self, entry: Dict) -> Dict:
        raise NotImplementedError

    def list(self, limit: int = 100, offset: int = 0) -> Iterable[Dict]:
        raise NotImplementedError

    def clear(self) -> None:
        raise NotImplementedError


class FileAuditBackend(AuditBackend):
    """Append-only JSON lines backend for simple durable storage.

    Each entry is written as a single JSON object on its own line. Reads
    return parsed JSON objects in insertion order.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        # ensure directory exists
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)

    def append(self, entry: Dict) -> Dict:
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    def list(self, limit: int = 100, offset: int = 0) -> Iterable[Dict]:
        out = []
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                out.append(json.loads(line))
        return out[offset : offset + limit]

    def clear(self) -> None:
        # truncate the file
        with self.path.open("w", encoding="utf-8"):
            pass
