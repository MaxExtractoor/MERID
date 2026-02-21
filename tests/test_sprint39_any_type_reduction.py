"""Tests for Sprint 39 — 'any' Type Reduction."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WEB_REACT = ROOT / "web" / "react" / "src"
VIEWS_DIR = WEB_REACT / "views"
COMPONENTS_DIR = WEB_REACT / "components"

# Allowlist: files/lines where 'any' is acceptable (hook return types, etc.)
ALLOWLIST = {
    "Settings.tsx",  # useApiData hook return type — generic hook
}


# ── 1. No 'any' in catch blocks ───────────────────────────────

class TestNoCatchAny:
    """catch blocks should use 'unknown', not 'any'."""

    def test_no_catch_any_in_views(self):
        violations = []
        for f in sorted(VIEWS_DIR.glob("*.tsx")):
            text = f.read_text(encoding="utf-8")
            for m in re.finditer(r"catch\s*\(\s*\w+\s*:\s*any\s*\)", text):
                line = text[: m.start()].count("\n") + 1
                violations.append(f"{f.name}:{line}")
        assert len(violations) == 0, f"catch(e: any): {violations}"

    def test_no_catch_any_in_components(self):
        violations = []
        for f in sorted(COMPONENTS_DIR.glob("*.tsx")):
            text = f.read_text(encoding="utf-8")
            for m in re.finditer(r"catch\s*\(\s*\w+\s*:\s*any\s*\)", text):
                line = text[: m.start()].count("\n") + 1
                violations.append(f"{f.name}:{line}")
        assert len(violations) == 0, f"catch(e: any): {violations}"


# ── 2. No useState<any> ───────────────────────────────────────

class TestNoUseStateAny:
    """useState should not use <any> type parameter."""

    def test_no_usestate_any_in_views(self):
        violations = []
        for f in sorted(VIEWS_DIR.glob("*.tsx")):
            text = f.read_text(encoding="utf-8")
            for m in re.finditer(r"useState<any>", text):
                line = text[: m.start()].count("\n") + 1
                violations.append(f"{f.name}:{line}")
        assert len(violations) == 0, f"useState<any>: {violations}"

    def test_no_usestate_any_in_components(self):
        violations = []
        for f in sorted(COMPONENTS_DIR.glob("*.tsx")):
            text = f.read_text(encoding="utf-8")
            for m in re.finditer(r"useState<any>", text):
                line = text[: m.start()].count("\n") + 1
                violations.append(f"{f.name}:{line}")
        assert len(violations) == 0, f"useState<any>: {violations}"


# ── 3. Overall 'any' count reduced ────────────────────────────

class TestAnyCountReduced:
    """Total 'any' count should be minimal (<=5 allowed for edge cases)."""

    def test_any_count_views(self):
        count = 0
        for f in sorted(VIEWS_DIR.glob("*.tsx")):
            if f.name in ALLOWLIST:
                continue
            text = f.read_text(encoding="utf-8")
            lines = text.split("\n")
            for line in lines:
                stripped = line.strip()
                if stripped.startswith("//") or stripped.startswith("*"):
                    continue
                count += len(re.findall(r":\s*any\b|as\s+any\b|<any>|\bany\[\]", line))
        assert count == 0, f"Views have {count} 'any' usages (expected 0)"

    def test_any_count_components(self):
        count = 0
        for f in sorted(COMPONENTS_DIR.glob("*.tsx")):
            if f.name in ALLOWLIST:
                continue
            text = f.read_text(encoding="utf-8")
            lines = text.split("\n")
            for line in lines:
                stripped = line.strip()
                if stripped.startswith("//") or stripped.startswith("*"):
                    continue
                count += len(re.findall(r":\s*any\b|as\s+any\b|<any>|\bany\[\]", line))
        assert count == 0, f"Components have {count} 'any' usages (expected 0)"


# ── 4. No 'as any' casts ──────────────────────────────────────

class TestNoAsAnyCasts:
    """'as any' casts should be replaced with proper types."""

    def test_no_as_any_in_views(self):
        violations = []
        for f in sorted(VIEWS_DIR.glob("*.tsx")):
            if f.name in ALLOWLIST:
                continue
            text = f.read_text(encoding="utf-8")
            for m in re.finditer(r"\bas\s+any\b", text):
                line = text[: m.start()].count("\n") + 1
                violations.append(f"{f.name}:{line}")
        assert len(violations) == 0, f"as any: {violations}"

    def test_no_as_any_in_components(self):
        violations = []
        for f in sorted(COMPONENTS_DIR.glob("*.tsx")):
            if f.name in ALLOWLIST:
                continue
            text = f.read_text(encoding="utf-8")
            for m in re.finditer(r"\bas\s+any\b", text):
                line = text[: m.start()].count("\n") + 1
                violations.append(f"{f.name}:{line}")
        assert len(violations) == 0, f"as any: {violations}"
