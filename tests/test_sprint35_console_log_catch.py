"""Tests for Sprint 35 — console.log Removal + Empty Catch Block Fix."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WEB_REACT = ROOT / "web" / "react" / "src"
VIEWS_DIR = WEB_REACT / "views"
COMPONENTS_DIR = WEB_REACT / "components"


# ── 1. No console.log in views or components ──────────────────

class TestNoConsoleLog:
    """No console.log calls should exist in production code."""

    def test_no_console_log_in_views(self):
        violations = []
        for f in sorted(VIEWS_DIR.glob("*.tsx")):
            text = f.read_text(encoding="utf-8")
            if "console.log(" in text:
                violations.append(f.name)
        assert len(violations) == 0, f"Views with console.log: {violations}"

    def test_no_console_log_in_components(self):
        violations = []
        for f in sorted(COMPONENTS_DIR.glob("*.tsx")):
            text = f.read_text(encoding="utf-8")
            if "console.log(" in text:
                violations.append(f.name)
        assert len(violations) == 0, f"Components with console.log: {violations}"


# ── 2. No empty catch blocks ──────────────────────────────────

class TestNoEmptyCatch:
    """All catch blocks should have a comment or statement."""

    def test_no_empty_catch_in_views(self):
        violations = []
        for f in sorted(VIEWS_DIR.glob("*.tsx")):
            text = f.read_text(encoding="utf-8")
            for m in re.finditer(r"\}\s*catch\s*(?:\(\w+\))?\s*\{\s*\}", text):
                line = text[: m.start()].count("\n") + 1
                violations.append(f"{f.name}:{line}")
        assert len(violations) == 0, f"Empty catch blocks: {violations}"

    def test_no_empty_catch_in_components(self):
        violations = []
        for f in sorted(COMPONENTS_DIR.glob("*.tsx")):
            text = f.read_text(encoding="utf-8")
            for m in re.finditer(r"\}\s*catch\s*(?:\(\w+\))?\s*\{\s*\}", text):
                line = text[: m.start()].count("\n") + 1
                violations.append(f"{f.name}:{line}")
        assert len(violations) == 0, f"Empty catch blocks: {violations}"


# ── 3. Full console sanity check ──────────────────────────────

class TestConsoleCleanSanity:
    """Full sanity: no console.log/warn/error (except ErrorBoundary)."""

    def test_no_console_warn_anywhere(self):
        violations = []
        for d in [VIEWS_DIR, COMPONENTS_DIR]:
            for f in sorted(d.glob("*.tsx")):
                text = f.read_text(encoding="utf-8")
                if "console.warn(" in text:
                    violations.append(f.name)
        assert len(violations) == 0

    def test_no_console_error_except_boundary(self):
        violations = []
        for d in [VIEWS_DIR, COMPONENTS_DIR]:
            for f in sorted(d.glob("*.tsx")):
                if f.name == "ErrorBoundary.tsx":
                    continue
                text = f.read_text(encoding="utf-8")
                if "console.error(" in text:
                    violations.append(f.name)
        assert len(violations) == 0
