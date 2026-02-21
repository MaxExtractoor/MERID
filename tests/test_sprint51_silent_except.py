"""Tests for Sprint 51 — No silent except-pass blocks in backend."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MERID_DIR = ROOT / "merid"
WEB_API_DIR = ROOT / "web" / "api"

# Pre-existing violations present before Sprint 51 debt-cleanup session.
# These are tracked here so new regressions are caught immediately.
# Do NOT add new entries — fix the code instead.
MERID_KNOWN: set = set()  # All previously tracked violations have been fixed.

WEB_API_KNOWN: set = {
    # kalshi_api.py: ws.close() in SSE generator finally blocks — legitimate cleanup
    "kalshi_api.py:L525",
    "kalshi_api.py:L646",
}


class TestNoSilentExceptPass:
    """Backend Python files should not silently swallow exceptions."""

    def test_no_except_pass_in_merid(self):
        violations = self._scan(MERID_DIR)
        new_violations = set(violations) - MERID_KNOWN
        assert len(new_violations) == 0, f"New silent except-pass in merid/: {sorted(new_violations)}"

    def test_no_except_pass_in_web_api(self):
        violations = self._scan(WEB_API_DIR)
        new_violations = set(violations) - WEB_API_KNOWN
        assert len(new_violations) == 0, f"New silent except-pass in web/api/: {sorted(new_violations)}"

    def test_known_merid_count(self):
        """Track known count — shrinking is good, growing means regression."""
        violations = self._scan(MERID_DIR)
        actual = set(violations)
        assert actual <= MERID_KNOWN, (
            f"New violations not in known set: {sorted(actual - MERID_KNOWN)}"
        )

    def test_known_web_api_count(self):
        """Track known count — shrinking is good, growing means regression."""
        violations = self._scan(WEB_API_DIR)
        actual = set(violations)
        assert actual <= WEB_API_KNOWN, (
            f"New violations not in known set: {sorted(actual - WEB_API_KNOWN)}"
        )

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
