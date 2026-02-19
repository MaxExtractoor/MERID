"""Tests for Sprint 52 — No deprecated datetime.utcnow() in backend."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MERID_DIR = ROOT / "merid"
WEB_API_DIR = ROOT / "web" / "api"


class TestNoDeprecatedUtcnow:
    """Backend should use datetime.now(timezone.utc) instead of utcnow()."""

    def test_no_utcnow_in_merid(self):
        violations = self._scan(MERID_DIR)
        assert len(violations) == 0, f"utcnow() in merid/: {violations}"

    def test_no_utcnow_in_web_api(self):
        violations = self._scan(WEB_API_DIR)
        assert len(violations) == 0, f"utcnow() in web/api/: {violations}"

    @staticmethod
    def _scan(directory: Path):
        violations = []
        if not directory.exists():
            return violations
        for f in directory.rglob("*.py"):
            text = f.read_text(encoding="utf-8", errors="ignore")
            for i, line in enumerate(text.split("\n"), 1):
                if line.strip().startswith("#"):
                    continue
                if "utcnow()" in line:
                    violations.append(f"{f.name}:L{i}")
        return violations
