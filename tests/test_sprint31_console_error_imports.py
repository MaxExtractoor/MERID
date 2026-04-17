"""Tests for Sprint 31 — console.error Removal from Views + Unused React Import Cleanup."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WEB_REACT = ROOT / "web" / "react" / "src"
VIEWS_DIR = WEB_REACT / "views"
COMPONENTS_DIR = WEB_REACT / "components"

# Files where console.error was removed
ERROR_CLEANED_FILES = [
    "Betting.tsx",
    "DevSwarm.tsx",
    "Health.tsx",
    "OperatorActivityStream.tsx",
    "Plugins.tsx",
    "Social.tsx",
    "TradeFloor.tsx",
]

# Files where unused React import was removed
REACT_IMPORT_CLEANED = [
    "DevProposalBoard.tsx",
    "DevProposalDetail.tsx",
]


# ── 1. No console.error in cleaned views ──────────────────────

class TestNoConsoleErrorViews:
    """Cleaned views should not use console.error."""

    @pytest.mark.parametrize("filename", ERROR_CLEANED_FILES)
    def test_no_console_error(self, filename: str):
        text = (VIEWS_DIR / filename).read_text(encoding="utf-8")
        errors = re.findall(r"console\.error\(", text)
        assert len(errors) == 0, f"{filename} still has {len(errors)} console.error calls"

    def test_no_console_error_in_any_view(self):
        violations = []
        for f in sorted(VIEWS_DIR.glob("*.tsx")):
            text = f.read_text(encoding="utf-8")
            if "console.error(" in text:
                violations.append(f.name)
        assert len(violations) == 0, f"Views with console.error: {violations}"


# ── 2. Unused React imports cleaned ───────────────────────────

class TestUnusedReactImports:
    """Components should not have unused React default imports."""

    @pytest.mark.parametrize("filename", REACT_IMPORT_CLEANED)
    def test_no_unused_react_import(self, filename: str):
        text = (COMPONENTS_DIR / filename).read_text(encoding="utf-8")
        # Should not have `import React,` or `import React from`
        # unless React.* is actually used in the body
        first_line = text.split("\n")[0]
        if "import React" in first_line and "React," not in first_line:
            # `import React from 'react'` with no named imports — should be removed
            body = "\n".join(text.split("\n")[1:])
            assert "React." in body, f"{filename} has unused React import"

    @pytest.mark.parametrize("filename", REACT_IMPORT_CLEANED)
    def test_named_imports_preserved(self, filename: str):
        text = (COMPONENTS_DIR / filename).read_text(encoding="utf-8")
        # Verify named imports still exist
        assert "from 'react'" in text, f"{filename} missing react import entirely"


# ── 3. Sanity: no console.warn either ─────────────────────────

class TestNoConsoleWarnSanity:
    """Verify console.warn is still clean from Sprint 30."""

    def test_no_console_warn_in_views(self):
        violations = []
        for f in sorted(VIEWS_DIR.glob("*.tsx")):
            text = f.read_text(encoding="utf-8")
            if "console.warn(" in text:
                violations.append(f.name)
        assert len(violations) == 0, f"Views with console.warn: {violations}"
