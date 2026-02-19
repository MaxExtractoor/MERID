"""Tests for Sprint 45 — Hooks + Utils Code Quality."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WEB_REACT = ROOT / "web" / "react" / "src"
HOOKS_DIR = WEB_REACT / "hooks"
UTILS_DIR = WEB_REACT / "utils"

ALLOWLISTED_ANY_COMMENTS = [
    "any transform",  # useApiData.ts comment
    "any type",       # useConsensusStream.ts comment
    "if any",         # useConsensusStream.ts, useKafkaStream.ts comments
]


# ── 1. 'any' type reduction in hooks/utils ─────────────────────

class TestAnyTypeReduction:
    """Hooks and utils should minimize 'any' usage."""

    def test_hooks_any_count_low(self):
        """Non-comment 'any' in hooks should be <= 4 (allowlisted)."""
        count = 0
        for f in sorted(list(HOOKS_DIR.glob("*.ts")) + list(HOOKS_DIR.glob("*.tsx"))):
            text = f.read_text(encoding="utf-8")
            for i, line in enumerate(text.split("\n"), 1):
                stripped = line.strip()
                if stripped.startswith("//") or stripped.startswith("*") or stripped.startswith("/**"):
                    continue
                if re.search(r'\bany\b', line):
                    # Skip if it's in a comment portion of the line
                    code_part = line.split("//")[0] if "//" in line else line
                    if re.search(r'\bany\b', code_part):
                        count += 1
        assert count <= 4, f"Too many 'any' in hooks: {count}"

    def test_utils_no_any(self):
        """Utils should have 0 non-comment 'any'."""
        count = 0
        if not UTILS_DIR.exists():
            return
        for f in sorted(list(UTILS_DIR.glob("*.ts")) + list(UTILS_DIR.glob("*.tsx"))):
            text = f.read_text(encoding="utf-8")
            for line in text.split("\n"):
                stripped = line.strip()
                if stripped.startswith("//") or stripped.startswith("*"):
                    continue
                code_part = line.split("//")[0] if "//" in line else line
                if re.search(r'\bany\b', code_part):
                    count += 1
        assert count == 0, f"'any' in utils: {count}"


# ── 2. No console.log in hooks ─────────────────────────────────

class TestNoConsoleLog:
    """Hooks should not use console.log (use console.debug/warn/error)."""

    def test_no_console_log_in_hooks(self):
        violations = []
        for f in sorted(list(HOOKS_DIR.glob("*.ts")) + list(HOOKS_DIR.glob("*.tsx"))):
            text = f.read_text(encoding="utf-8")
            for i, line in enumerate(text.split("\n"), 1):
                stripped = line.strip()
                if stripped.startswith("//"):
                    continue
                if "console.log(" in line:
                    violations.append(f"{f.name}:{i}")
        assert len(violations) == 0, f"console.log in hooks: {violations}"


# ── 3. No hardcoded polling intervals in hooks ──────────────────

class TestNoHardcodedPolling:
    """Hooks should use DEFAULTS.POLLING_INTERVALS, not magic numbers."""

    def test_no_hardcoded_setinterval(self):
        violations = []
        for f in sorted(list(HOOKS_DIR.glob("*.ts")) + list(HOOKS_DIR.glob("*.tsx"))):
            text = f.read_text(encoding="utf-8")
            for i, line in enumerate(text.split("\n"), 1):
                stripped = line.strip()
                if stripped.startswith("//") or stripped.startswith("*"):
                    continue
                if "DEFAULTS" in line:
                    continue
                if re.search(r'setInterval\([^,]+,\s*\d+\)', line):
                    violations.append(f"{f.name}:{i}")
        assert len(violations) == 0, f"Hardcoded setInterval: {violations}"
