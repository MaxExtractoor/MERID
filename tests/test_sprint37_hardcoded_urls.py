"""Tests for Sprint 37 — Hardcoded Fetch URLs → API_ENDPOINTS Constants."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WEB_REACT = ROOT / "web" / "react" / "src"
VIEWS_DIR = WEB_REACT / "views"
COMPONENTS_DIR = WEB_REACT / "components"
CONSTANTS_FILE = WEB_REACT / "config" / "constants.ts"

# New function-style API_ENDPOINTS constants
NEW_CONSTANTS = [
    "PLUGINS_INSTALL",
    "PLUGINS_UNINSTALL",
    "PLUGINS_TOGGLE",
    "PREDICTION_MARKET_ACTION",
    "SIGNAL_LAYER_FEATURES",
    "PIPELINE_PNL",
    "PIPELINE_VENUE_TOGGLE",
    "RISK_AGENT_EQUITY_HISTORY",
    "RISK_AGENT_DRAWDOWN_HISTORY",
    "RISK_AGENT_METRICS",
    "NOTIFICATION_READ",
    "PAPER_TRADING_PORTFOLIO",
    "PAPER_TRADING_CLOSE_POSITION",
    "PAPER_TRADING_CANCEL_ORDER",
    "PAPER_TRADING_STATS",
    "SIMULATION_SPEED",
]


# ── 1. New constants exist ─────────────────────────────────────

class TestNewConstants:
    """Verify new function-style API_ENDPOINTS constants exist."""

    @pytest.mark.parametrize("name", NEW_CONSTANTS)
    def test_constant_exists(self, name: str):
        text = CONSTANTS_FILE.read_text(encoding="utf-8")
        assert f"{name}:" in text or f"{name} :" in text, f"Missing API_ENDPOINTS.{name}"

    @pytest.mark.parametrize("name", NEW_CONSTANTS)
    def test_constant_is_function(self, name: str):
        text = CONSTANTS_FILE.read_text(encoding="utf-8")
        # Should be a function: NAME: (param) => ...
        pattern = rf"{name}:\s*\("
        assert re.search(pattern, text), f"API_ENDPOINTS.{name} should be a function"


# ── 2. No hardcoded fetch URLs remain ──────────────────────────

class TestNoHardcodedUrls:
    """No hardcoded /api/ fetch URLs should remain in views or components."""

    def test_no_hardcoded_urls_in_views(self):
        violations = []
        for f in sorted(VIEWS_DIR.glob("*.tsx")):
            text = f.read_text(encoding="utf-8")
            for m in re.finditer(r"fetch\(\s*`(/api/[^`]*)`", text):
                line = text[: m.start()].count("\n") + 1
                violations.append(f"{f.name}:{line}")
        assert len(violations) == 0, f"Hardcoded URLs: {violations}"

    def test_no_hardcoded_urls_in_components(self):
        violations = []
        for f in sorted(COMPONENTS_DIR.glob("*.tsx")):
            text = f.read_text(encoding="utf-8")
            for m in re.finditer(r"fetch\(\s*`(/api/[^`]*)`", text):
                line = text[: m.start()].count("\n") + 1
                violations.append(f"{f.name}:{line}")
        assert len(violations) == 0, f"Hardcoded URLs: {violations}"


# ── 3. Files use API_ENDPOINTS ─────────────────────────────────

class TestFilesUseConstants:
    """Verify specific files now use API_ENDPOINTS."""

    @pytest.mark.parametrize("filename,directory", [
        ("Plugins.tsx", "views"),
        ("Predictions.tsx", "views"),
        ("SignalLayerView.tsx", "views"),
        ("DrawdownChart.tsx", "components"),
        ("PaperTradingPanel.tsx", "components"),
        ("SimulationControlPanel.tsx", "components"),
        ("VenueHealthGrid.tsx", "components"),
    ])
    def test_file_uses_api_endpoints(self, filename: str, directory: str):
        d = VIEWS_DIR if directory == "views" else COMPONENTS_DIR
        text = (d / filename).read_text(encoding="utf-8")
        assert "API_ENDPOINTS." in text, f"{filename} should use API_ENDPOINTS"
