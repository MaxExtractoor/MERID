"""Tests for Sprint 26 — Polling Interval Constants."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WEB_REACT = ROOT / "web" / "react" / "src"
VIEWS_DIR = WEB_REACT / "views"
CONSTANTS_FILE = WEB_REACT / "config" / "constants.ts"

# Views updated to use DEFAULTS.POLLING_INTERVALS
UPDATED_VIEWS = [
    "Agents.tsx",
    "ApiDashboard.tsx",
    "Logs.tsx",
    "Research.tsx",
    "Risk.tsx",
]

# New polling interval constants added
NEW_INTERVAL_KEYS = [
    "RISK_ALERTS",
    "SYSTEM_HEALTH",
    "API_STATUS",
    "LOGS",
    "LOG_STATS",
    "BACKTESTS",
    "RISK_POSITION_LIMITS",
]


# ── 1. New constants exist ─────────────────────────────────────

class TestNewPollingConstants:
    """New polling interval constants were added to DEFAULTS."""

    @pytest.mark.parametrize("key", NEW_INTERVAL_KEYS)
    def test_constant_exists(self, key: str):
        text = CONSTANTS_FILE.read_text(encoding="utf-8")
        assert key in text, f"Missing POLLING_INTERVALS.{key}"

    def test_all_values_are_numbers(self):
        text = CONSTANTS_FILE.read_text(encoding="utf-8")
        # Extract POLLING_INTERVALS block
        match = re.search(r'POLLING_INTERVALS:\s*\{([^}]+)\}', text)
        assert match, "POLLING_INTERVALS block not found"
        block = match.group(1)
        values = re.findall(r':\s*(\d+)', block)
        assert len(values) >= 12, f"Expected >=12 interval values, got {len(values)}"
        for v in values:
            assert int(v) > 0, f"Invalid interval value: {v}"


# ── 2. Views import DEFAULTS ──────────────────────────────────

class TestViewsImportDefaults:
    """Updated views import DEFAULTS from constants."""

    @pytest.mark.parametrize("filename", UPDATED_VIEWS)
    def test_imports_defaults(self, filename: str):
        text = (VIEWS_DIR / filename).read_text(encoding="utf-8")
        assert "DEFAULTS" in text, f"{filename} missing DEFAULTS import"


# ── 3. Views use POLLING_INTERVALS constants ──────────────────

class TestViewsUsePollingConstants:
    """Updated views use DEFAULTS.POLLING_INTERVALS instead of hardcoded numbers."""

    @pytest.mark.parametrize("filename", UPDATED_VIEWS)
    def test_uses_polling_constant(self, filename: str):
        text = (VIEWS_DIR / filename).read_text(encoding="utf-8")
        assert "DEFAULTS.POLLING_INTERVALS" in text, f"{filename} not using POLLING_INTERVALS"

    @pytest.mark.parametrize("filename", UPDATED_VIEWS)
    def test_no_hardcoded_polling_intervals(self, filename: str):
        text = (VIEWS_DIR / filename).read_text(encoding="utf-8")
        # Find pollingInterval values that are raw numbers (not using DEFAULTS)
        hardcoded = re.findall(r'pollingInterval:\s*(\d+)', text)
        assert len(hardcoded) == 0, (
            f"{filename} still has hardcoded pollingInterval: {hardcoded}"
        )
