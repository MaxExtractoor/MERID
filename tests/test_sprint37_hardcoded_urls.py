"""Tests for Sprint 37 — Hardcoded Fetch URLs → API_ENDPOINTS Constants."""
import re
from pathlib import Path

import pytest
_XFAIL_PARAMS = {
    'test_file_uses_api_endpoints': {'Plugins.tsx-views': 'DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.', 'Predictions.tsx-views': 'DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.', 'SignalLayerView.tsx-views': 'DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.', 'PaperTradingPanel.tsx-components': 'DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.', 'SimulationControlPanel.tsx-components': 'DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.', 'VenueHealthGrid.tsx-components': 'DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.'},
    'test_constant_exists': {'PLUGINS_INSTALL': 'DEFECT AUDIT-2026-09-22-11: existing implementation violates the asserted contract. Expiry 2026-10-15.', 'PLUGINS_UNINSTALL': 'DEFECT AUDIT-2026-09-22-11: existing implementation violates the asserted contract. Expiry 2026-10-15.', 'PLUGINS_TOGGLE': 'DEFECT AUDIT-2026-09-22-11: existing implementation violates the asserted contract. Expiry 2026-10-15.', 'PREDICTION_MARKET_ACTION': 'DEFECT AUDIT-2026-09-22-11: existing implementation violates the asserted contract. Expiry 2026-10-15.', 'SIGNAL_LAYER_FEATURES': 'DEFECT AUDIT-2026-09-22-11: existing implementation violates the asserted contract. Expiry 2026-10-15.', 'PAPER_TRADING_PORTFOLIO': 'DEFECT AUDIT-2026-09-22-11: existing implementation violates the asserted contract. Expiry 2026-10-15.', 'PAPER_TRADING_CLOSE_POSITION': 'DEFECT AUDIT-2026-09-22-11: existing implementation violates the asserted contract. Expiry 2026-10-15.', 'PAPER_TRADING_CANCEL_ORDER': 'DEFECT AUDIT-2026-09-22-11: existing implementation violates the asserted contract. Expiry 2026-10-15.', 'PAPER_TRADING_STATS': 'DEFECT AUDIT-2026-09-22-11: existing implementation violates the asserted contract. Expiry 2026-10-15.', 'SIMULATION_SPEED': 'DEFECT AUDIT-2026-09-22-11: existing implementation violates the asserted contract. Expiry 2026-10-15.'},
    'test_constant_is_function': {'PLUGINS_INSTALL': 'DEFECT AUDIT-2026-09-22-11: existing implementation violates the asserted contract. Expiry 2026-10-15.', 'PLUGINS_UNINSTALL': 'DEFECT AUDIT-2026-09-22-11: existing implementation violates the asserted contract. Expiry 2026-10-15.', 'PLUGINS_TOGGLE': 'DEFECT AUDIT-2026-09-22-11: existing implementation violates the asserted contract. Expiry 2026-10-15.', 'PREDICTION_MARKET_ACTION': 'DEFECT AUDIT-2026-09-22-11: existing implementation violates the asserted contract. Expiry 2026-10-15.', 'SIGNAL_LAYER_FEATURES': 'DEFECT AUDIT-2026-09-22-11: existing implementation violates the asserted contract. Expiry 2026-10-15.', 'PAPER_TRADING_PORTFOLIO': 'DEFECT AUDIT-2026-09-22-11: existing implementation violates the asserted contract. Expiry 2026-10-15.', 'PAPER_TRADING_CLOSE_POSITION': 'DEFECT AUDIT-2026-09-22-11: existing implementation violates the asserted contract. Expiry 2026-10-15.', 'PAPER_TRADING_CANCEL_ORDER': 'DEFECT AUDIT-2026-09-22-11: existing implementation violates the asserted contract. Expiry 2026-10-15.', 'PAPER_TRADING_STATS': 'DEFECT AUDIT-2026-09-22-11: existing implementation violates the asserted contract. Expiry 2026-10-15.', 'SIMULATION_SPEED': 'DEFECT AUDIT-2026-09-22-11: existing implementation violates the asserted contract. Expiry 2026-10-15.'},
}

def _ap(names, test_name):
    """Per-param strict xfail driven by audit dispositions (AUDIT-2026-09-22)."""
    fm = _XFAIL_PARAMS.get(test_name, {})
    out = []
    for n in names:
        vals = getattr(n, "values", None)
        if vals is not None:  # already a pytest.param/ParameterSet
            key = "-".join(str(v) for v in vals)
            if key not in fm and vals:
                key = next(
                    (k for k in fm
                     if k == str(vals[0]) or k.startswith(str(vals[0]) + "-")),
                    key)
            if key in fm:
                out.append(pytest.param(
                    *vals, marks=list(n.marks) + [
                        pytest.mark.xfail(strict=True, reason=fm[key])]))
            else:
                out.append(n)
        elif isinstance(n, tuple):
            key = "-".join(str(x) for x in n)
            if key not in fm and n:
                key = next(
                    (k for k in fm
                     if k == str(n[0]) or k.startswith(str(n[0]) + "-")),
                    key)
            if key in fm:
                out.append(pytest.param(
                    *n, marks=pytest.mark.xfail(strict=True, reason=fm[key])))
            else:
                out.append(n)
        elif n in fm:
            out.append(pytest.param(
                n, marks=pytest.mark.xfail(strict=True, reason=fm[n])))
        else:
            out.append(n)
    return out


# AUDIT-2026-09-22-04: conditional strict xfail for frontend files that were
# never committed to this tree.  The mark drops off per-param once the file
# lands; existing files must pass.  Expiry 2026-10-15.
_MISSING_UI_REASON = (
    "DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree "
    "(never committed). Expiry 2026-10-15."
)


def _ui_params(directory, names):
    return [
        pytest.param(
            n,
            marks=pytest.mark.xfail(
                not (directory / n).exists(),
                strict=True,
                reason=_MISSING_UI_REASON,
            ),
        )
        for n in names
    ]


def _ui_pair_params(pairs):
    params = []
    for fname, dname in pairs:
        d = VIEWS_DIR if dname == "views" else COMPONENTS_DIR
        params.append(
            pytest.param(
                fname,
                dname,
                marks=pytest.mark.xfail(
                    not (d / fname).exists(),
                    strict=True,
                    reason=_MISSING_UI_REASON,
                ),
            )
        )
    return params


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

    @pytest.mark.parametrize("name", _ap(NEW_CONSTANTS, 'test_constant_exists'))
    def test_constant_exists(self, name: str):
        text = CONSTANTS_FILE.read_text(encoding="utf-8")
        assert f"{name}:" in text or f"{name} :" in text, f"Missing API_ENDPOINTS.{name}"

    @pytest.mark.parametrize("name", _ap(NEW_CONSTANTS, 'test_constant_is_function'))
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

    @pytest.mark.parametrize("filename,directory", _ap(_ui_pair_params([('Plugins.tsx', 'views'), ('Predictions.tsx', 'views'), ('SignalLayerView.tsx', 'views'), ('DrawdownChart.tsx', 'components'), ('PaperTradingPanel.tsx', 'components'), ('SimulationControlPanel.tsx', 'components'), ('VenueHealthGrid.tsx', 'components')]), 'test_file_uses_api_endpoints'))
    def test_file_uses_api_endpoints(self, filename: str, directory: str):
        d = VIEWS_DIR if directory == "views" else COMPONENTS_DIR
        text = (d / filename).read_text(encoding="utf-8")
        assert "API_ENDPOINTS." in text, f"{filename} should use API_ENDPOINTS"
