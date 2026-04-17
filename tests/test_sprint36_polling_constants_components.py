"""Tests for Sprint 36 — Polling Constants in Components + Remaining Views."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WEB_REACT = ROOT / "web" / "react" / "src"
VIEWS_DIR = WEB_REACT / "views"
COMPONENTS_DIR = WEB_REACT / "components"
CONSTANTS_FILE = WEB_REACT / "config" / "constants.ts"

# Interval values that should use DEFAULTS.POLLING_INTERVALS
MAGIC_INTERVALS = {'1000', '2000', '3000', '5000', '10000', '15000',
                   '20000', '30000', '60000', '120000'}


# ── 1. New polling interval constants exist ────────────────────

class TestPollingIntervalConstants:
    """Verify new polling interval constants exist in constants.ts."""

    @pytest.mark.parametrize("name", [
        "STALENESS", "SIMULATION", "FAST_REFRESH", "STANDARD",
        "MEDIUM", "SLOW", "EXPLAINABILITY", "BACKGROUND",
        "INFREQUENT", "RARE",
    ])
    def test_constant_exists(self, name: str):
        text = CONSTANTS_FILE.read_text(encoding="utf-8")
        assert f"{name}:" in text, f"Missing POLLING_INTERVALS.{name}"


# ── 2. No magic number intervals in components ────────────────

class TestNoMagicIntervalsComponents:
    """Components should use DEFAULTS.POLLING_INTERVALS, not magic numbers."""

    def test_no_magic_intervals(self):
        violations = []
        for f in sorted(COMPONENTS_DIR.glob("*.tsx")):
            text = f.read_text(encoding="utf-8")
            for m in re.finditer(r'setInterval\([^,]+,\s*(\d+)\)', text):
                val = m.group(1)
                if val in MAGIC_INTERVALS:
                    line = text[:m.start()].count("\n") + 1
                    violations.append(f"{f.name}:{line} -> {val}ms")
        assert len(violations) == 0, f"Magic intervals: {violations}"


# ── 3. No magic number intervals in views ─────────────────────

class TestNoMagicIntervalsViews:
    """Views should use DEFAULTS.POLLING_INTERVALS, not magic numbers."""

    def test_no_magic_intervals(self):
        violations = []
        for f in sorted(VIEWS_DIR.glob("*.tsx")):
            text = f.read_text(encoding="utf-8")
            for m in re.finditer(r'setInterval\([^,]+,\s*(\d+)\)', text):
                val = m.group(1)
                if val in MAGIC_INTERVALS:
                    line = text[:m.start()].count("\n") + 1
                    violations.append(f"{f.name}:{line} -> {val}ms")
        assert len(violations) == 0, f"Magic intervals: {violations}"


# ── 4. DEFAULTS import present where used ──────────────────────

class TestDefaultsImport:
    """Files using DEFAULTS should import it."""

    def test_defaults_imported_in_components(self):
        violations = []
        for f in sorted(COMPONENTS_DIR.glob("*.tsx")):
            text = f.read_text(encoding="utf-8")
            if "DEFAULTS.POLLING_INTERVALS" in text and "DEFAULTS" not in text.split("DEFAULTS.")[0]:
                violations.append(f.name)
        assert len(violations) == 0, f"Missing DEFAULTS import: {violations}"

    def test_defaults_imported_in_views(self):
        violations = []
        for f in sorted(VIEWS_DIR.glob("*.tsx")):
            text = f.read_text(encoding="utf-8")
            if "DEFAULTS.POLLING_INTERVALS" in text and "import" in text:
                # Check that DEFAULTS appears in an import statement
                imports = [l for l in text.split("\n") if l.strip().startswith("import")]
                has_defaults_import = any("DEFAULTS" in l for l in imports)
                if not has_defaults_import:
                    violations.append(f.name)
        assert len(violations) == 0, f"Missing DEFAULTS import: {violations}"
