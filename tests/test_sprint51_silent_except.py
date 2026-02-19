"""Tests for Sprint 51 — No silent except-pass blocks in backend."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MERID_DIR = ROOT / "merid"
WEB_API_DIR = ROOT / "web" / "api"


class TestNoSilentExceptPass:
    """Backend Python files should not silently swallow exceptions."""

    def test_no_except_pass_in_merid(self):
        violations = self._scan(MERID_DIR)
        assert len(violations) == 0, f"Silent except-pass in merid/: {violations}"

    def test_no_except_pass_in_web_api(self):
        violations = self._scan(WEB_API_DIR)
        assert len(violations) == 0, f"Silent except-pass in web/api/: {violations}"

    @staticmethod
    def _scan(directory: Path):
        violations = []
        if not directory.exists():
            return violations
        for f in directory.rglob("*.py"):
            text = f.read_text(encoding="utf-8", errors="ignore")
            lines = text.split("\n")
            for i, line in enumerate(lines):
                if re.match(r"\s*except\s+(Exception|BaseException).*:", line):
                    if i + 1 < len(lines) and lines[i + 1].strip() == "pass":
                        violations.append(f"{f.name}:L{i+1}")
        return violations
