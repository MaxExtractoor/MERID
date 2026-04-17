"""BaseDetector ABC — all detectors implement detect(root) -> list[Finding]."""
from __future__ import annotations

import os
import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Iterator

from tools.audit.models import Finding, Layer


class BaseDetector(ABC):
    name: str = ""

    @abstractmethod
    def detect(self, root: Path) -> list[Finding]:
        ...

    # ── helpers ────────────────────────────────────────────────────────

    _SKIP_DIRS = {"__pycache__", "archive", "node_modules", ".git", "__mocks__"}

    @staticmethod
    def _ts_files(root: Path) -> Iterator[Path]:
        base = root / "web" / "react" / "src"
        if not base.exists():
            return
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in BaseDetector._SKIP_DIRS and d != "__tests__"]
            for fn in filenames:
                if fn.endswith((".tsx", ".ts")) and not fn.endswith((".test.tsx", ".test.ts", ".smoke.test.tsx")):
                    yield Path(dirpath) / fn

    @staticmethod
    def _ts_test_files(root: Path) -> Iterator[Path]:
        """Only test files — useful for zombie/regression detectors."""
        base = root / "web" / "react" / "src"
        if not base.exists():
            return
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in BaseDetector._SKIP_DIRS]
            for fn in filenames:
                if fn.endswith((".test.tsx", ".test.ts", ".smoke.test.tsx")):
                    yield Path(dirpath) / fn

    @staticmethod
    def _py_files(root: Path) -> Iterator[Path]:
        scan_dirs = ["web", "agents", "merid", "core", "consensus", "swarm"]
        for d in scan_dirs:
            top = root / d
            if not top.exists():
                continue
            for dirpath, dirnames, filenames in os.walk(top):
                dirnames[:] = [x for x in dirnames if x not in BaseDetector._SKIP_DIRS]
                for fn in filenames:
                    if fn.endswith(".py"):
                        yield Path(dirpath) / fn

    @staticmethod
    def _is_test_file(p: Path) -> bool:
        name = p.name.lower()
        parts = str(p).lower()
        return (name.startswith("test_") or name.endswith("_test.py")
                or "/tests/" in parts or "\\tests\\" in parts
                or name.endswith(".test.tsx") or name.endswith(".test.ts"))

    @staticmethod
    def _rel(root: Path, p: Path) -> str:
        try:
            return str(p.relative_to(root))
        except ValueError:
            return str(p)

    @staticmethod
    def _lines(p: Path) -> list[str]:
        try:
            return p.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            return []

    @staticmethod
    def _grep(lines: list[str], pattern: str, flags: int = 0) -> Iterator[tuple[int, re.Match]]:
        rx = re.compile(pattern, flags)
        for i, line in enumerate(lines, 1):
            m = rx.search(line)
            if m:
                yield i, m
