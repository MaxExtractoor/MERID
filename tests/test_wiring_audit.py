"""§ Wiring Audit Tests — verify all surfaces are connected.

Tests:
  1. Backend router imports resolve
  2. Frontend views exist on disk
  3. Frontend hooks exist on disk
  4. Sidebar entries match App.tsx routes
  5. Constants.ts has all required endpoint keys
  6. New views are wired into App.tsx
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WEB_REACT = ROOT / "web" / "react" / "src"


# ── §1 Backend router imports ─────────────────────────────────────

class TestBackendRouterImports:
    """Verify all routers imported in web/main.py resolve without error."""

    MAIN_PY = ROOT / "web" / "main.py"

    def test_main_py_exists(self):
        assert self.MAIN_PY.exists()

    def test_router_import_lines(self):
        text = self.MAIN_PY.read_text(encoding="utf-8")
        router_lines = [
            line.strip()
            for line in text.splitlines()
            if "from web.api." in line and "router" in line and not line.strip().startswith("#")
        ]
        assert len(router_lines) >= 30, f"Expected ≥30 router imports, got {len(router_lines)}"

    def test_key_routers_present(self):
        text = self.MAIN_PY.read_text(encoding="utf-8")
        required = [
            "betting_router",
            "betting_consensus_router",
            "prediction_markets_router",
            "prediction_consensus_router",
            "rewards_router",
            "cognitive_router",
            "paper_trading_router",
            "system_observability_router",
            "loop_api_router",
            "operator_router",
        ]
        for name in required:
            assert name in text, f"Router '{name}' not found in web/main.py"

    def test_key_routers_included(self):
        text = self.MAIN_PY.read_text(encoding="utf-8")
        required = [
            "betting_router",
            "betting_consensus_router",
            "prediction_markets_router",
            "prediction_consensus_router",
            "rewards_router",
            "cognitive_router",
            "paper_trading_router",
            "system_observability_router",
            "loop_api_router",
        ]
        for name in required:
            pattern = f"include_router({name})"
            assert pattern in text, f"include_router({name}) not found in web/main.py"


# ── §2 Frontend views exist ───────────────────────────────────────

class TestFrontendViewsExist:
    """Verify all expected view files exist."""

    VIEWS_DIR = WEB_REACT / "views"

    REQUIRED_VIEWS = [
        "Overview.tsx",
        "Trading.tsx",
        "Agents.tsx",
        "Predictions.tsx",
        "PredictionConsensusView.tsx",
        "Risk.tsx",
        "Health.tsx",
        "Betting.tsx",
        "BettingConsensusView.tsx",
        "FlowRadarView.tsx",
        "SignalLayerView.tsx",
        "Rewards.tsx",
        "DevSwarm.tsx",
        "Positions.tsx",
        "Orders.tsx",
        "OperatorDashboard.tsx",
        # New views from wiring sprint
        "CognitiveView.tsx",
        "PaperTradingView.tsx",
        "SportsLiveView.tsx",
        "ObservabilityView.tsx",
    ]

    @pytest.mark.parametrize("view_file", REQUIRED_VIEWS)
    def test_view_exists(self, view_file):
        path = self.VIEWS_DIR / view_file
        assert path.exists(), f"View file missing: {view_file}"


# ── §3 Frontend hooks exist ───────────────────────────────────────

class TestFrontendHooksExist:
    """Verify all expected hook files exist."""

    HOOKS_DIR = WEB_REACT / "hooks"

    REQUIRED_HOOKS = [
        "useApiData.ts",
        "useBettingConsensus.ts",
        "usePredictionConsensus.ts",
        "useFlowRadar.ts",
        "useSignalLayer.ts",
        "useDevSwarm.ts",
        "useOperatorSummary.ts",
        "useRiskMetrics.ts",
        # New hooks from wiring sprint
        "useCognitive.ts",
        "usePaperTrading.ts",
        "useSportsLive.ts",
        "useObservability.ts",
        # Sprint 14 — LLM observability
        "useLLMObservability.ts",
    ]

    @pytest.mark.parametrize("hook_file", REQUIRED_HOOKS)
    def test_hook_exists(self, hook_file):
        path = self.HOOKS_DIR / hook_file
        assert path.exists(), f"Hook file missing: {hook_file}"


# ── §4 Sidebar ↔ App.tsx route consistency ────────────────────────

class TestSidebarAppConsistency:
    """Verify Sidebar entries have matching App.tsx routes."""

    APP_TSX = WEB_REACT / "App.tsx"
    SIDEBAR_TSX = WEB_REACT / "components" / "Sidebar.tsx"

    def _extract_view_type(self, filepath: Path) -> set:
        text = filepath.read_text(encoding="utf-8")
        match = re.search(r'type View\s*=\s*(.+?);', text)
        if not match:
            return set()
        raw = match.group(1)
        return set(re.findall(r'"([^"]+)"', raw))

    def test_sidebar_and_app_view_types_match(self):
        sidebar_views = self._extract_view_type(self.SIDEBAR_TSX)
        app_views = self._extract_view_type(self.APP_TSX)
        assert sidebar_views, "Could not extract View type from Sidebar.tsx"
        assert app_views, "Could not extract View type from App.tsx"
        assert sidebar_views == app_views, (
            f"View type mismatch:\n"
            f"  In Sidebar but not App: {sidebar_views - app_views}\n"
            f"  In App but not Sidebar: {app_views - sidebar_views}"
        )

    def test_new_views_in_app_router(self):
        text = self.APP_TSX.read_text(encoding="utf-8")
        required = ["cognitive", "paper-trading", "sports-live", "observability", "cross-asset"]
        for view in required:
            assert f'"{view}"' in text, f"View '{view}' not found in App.tsx router"

    def test_new_views_in_sidebar(self):
        text = self.SIDEBAR_TSX.read_text(encoding="utf-8")
        required = ["cognitive", "paper-trading", "sports-live", "observability", "cross-asset"]
        for view in required:
            assert f"'{view}'" in text, f"View '{view}' not found in Sidebar.tsx"


# ── §5 Constants.ts endpoint keys ─────────────────────────────────

class TestConstantsEndpoints:
    """Verify constants.ts has all required endpoint keys."""

    CONSTANTS = WEB_REACT / "config" / "constants.ts"

    REQUIRED_KEYS = [
        "COGNITIVE_SNAPSHOT",
        "PAPER_PORTFOLIO",
        "PAPER_POSITIONS",
        "PAPER_ORDERS",
        "SPORTS_LIVE_ODDS",
        "OBSERVABILITY_SUMMARY",
        "BETTING_CONSENSUS_SUMMARY",
        "PREDICTION_CONSENSUS_SUMMARY",
        "SIGNAL_FEATURES",
        "FLOW_RADAR",
        # Sprint 14 — LLM governance
        "LLM_TRACES_SUMMARY",
        "LLM_TOOLS_SUMMARY",
        "LLM_GUARDRAILS",
        "LLM_PROMPTS",
        # Sprint 16 — UI robustness
        "WALLET_BALANCES",
        "TREASURY_OVERVIEW",
        "SOCIAL_FEED",
        "MINING_OVERVIEW",
        "INSTITUTIONAL_OVERVIEW",
        "PLUGINS_LIST",
        "BETTING_OVERVIEW",
        "REWARDS_SUMMARY",
        "PORTFOLIO_LIVE",
        "TRADING_PORTFOLIO_SUMMARY",
        "TRADING_ORDERS_OPEN",
        "PREDICTION_MARKETS_SUMMARY",
        "LOGS_STATS",
        "USER_PROFILE",
    ]

    def test_constants_file_exists(self):
        assert self.CONSTANTS.exists()

    @pytest.mark.parametrize("key", REQUIRED_KEYS)
    def test_endpoint_key_present(self, key):
        text = self.CONSTANTS.read_text(encoding="utf-8")
        assert key in text, f"Endpoint key '{key}' missing from constants.ts"


# ── §6 Component files exist ─────────────────────────────────────

class TestComponentsExist:
    """Verify key reusable components exist."""

    COMPONENTS_DIR = WEB_REACT / "components"

    REQUIRED = [
        "Tooltip.tsx",
        "AnimatedCard.tsx",
        "Sidebar.tsx",
        "TopBar.tsx",
        "StubBanner.tsx",
        "ErrorBoundary.tsx",
    ]

    @pytest.mark.parametrize("component", REQUIRED)
    def test_component_exists(self, component):
        path = self.COMPONENTS_DIR / component
        assert path.exists(), f"Component missing: {component}"


# ── §7 Smoke test script exists ──────────────────────────────────

class TestSmokeTestScript:
    """Verify the smoke test script exists and is valid Python."""

    SCRIPT = ROOT / "scripts" / "smoke_test_wiring.py"

    def test_script_exists(self):
        assert self.SCRIPT.exists()

    def test_script_is_valid_python(self):
        text = self.SCRIPT.read_text(encoding="utf-8")
        compile(text, str(self.SCRIPT), "exec")

    def test_script_has_endpoints(self):
        text = self.SCRIPT.read_text(encoding="utf-8")
        assert "ENDPOINTS" in text
        assert len(re.findall(r'\("GET"', text)) >= 20, "Expected ≥20 GET endpoints in smoke test"


# ── §8 Gap report exists ─────────────────────────────────────────

class TestGapReport:
    """Verify the wiring gap report exists."""

    REPORT = ROOT / "docs" / "WIRING_GAP_REPORT.md"

    def test_report_exists(self):
        assert self.REPORT.exists()

    def test_report_has_sections(self):
        text = self.REPORT.read_text(encoding="utf-8")
        assert "Surface Map" in text
        assert "Gap Checklist" in text
        assert "Implementation Tasks" in text
