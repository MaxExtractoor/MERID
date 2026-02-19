"""Tests for Sprint 50 — All test files wired into Makefile targets."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = ROOT / "tests"
MAKEFILE = ROOT / "Makefile"

# Known-failing orphaned tests (pre-existing issues, not regressions)
KNOWN_FAILING: set = set()  # All previously-failing tests fixed in Sprint 54


class TestAllTestsWired:
    """Every test file should be referenced in at least one Makefile target."""

    def test_all_test_files_in_makefile(self):
        makefile_text = MAKEFILE.read_text(encoding="utf-8")
        all_tests = {f.name for f in TESTS_DIR.glob("test_*.py")}
        referenced = set(re.findall(r"tests/(test_\w+\.py)", makefile_text))

        unwired = all_tests - referenced - KNOWN_FAILING - {"test_sprint50_test_coverage.py"}
        assert len(unwired) == 0, f"Test files not in any Makefile target: {sorted(unwired)}"

    def test_known_failing_count(self):
        """Track known-failing count so we notice when they get fixed."""
        assert len(KNOWN_FAILING) == 0, f"Update KNOWN_FAILING if tests are fixed: {len(KNOWN_FAILING)}"
