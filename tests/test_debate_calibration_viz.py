"""§ Debate & Agent Calibration Visualization Tests

Verifies:
  1. New chart components exist on disk
  2. useDebateCalibration hook exists with expected exports
  3. Constants.ts has all debate/calibration endpoint keys
  4. PredictionConsensusView imports new components
  5. Backend API endpoints exist in prediction_consensus_api.py
  6. Backend debate.py has calibration/diversity/backtest methods
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WEB_REACT = ROOT / "web" / "react" / "src"
COMPONENTS = WEB_REACT / "components"
CHARTS = COMPONENTS / "charts"
HOOKS = WEB_REACT / "hooks"
VIEWS = WEB_REACT / "views"
CONFIG = WEB_REACT / "config"


# ── §1 Chart components exist ────────────────────────────────────

class TestChartComponentsExist:
    """All new chart components are on disk."""

    EXPECTED_CHARTS = [
        "CalibrationChart.tsx",
        "DebateLiftChart.tsx",
        "BrierTimeSeriesChart.tsx",
        "TeamDiversityCard.tsx",
        "AgentCalibrationProfile.tsx",
    ]

    @pytest.mark.parametrize("filename", EXPECTED_CHARTS)
    def test_chart_file_exists(self, filename: str):
        path = CHARTS / filename
        assert path.exists(), f"Missing chart component: {path}"

    @pytest.mark.parametrize("filename", EXPECTED_CHARTS)
    def test_chart_has_default_export(self, filename: str):
        text = (CHARTS / filename).read_text(encoding="utf-8")
        assert "export default function" in text, f"{filename} missing default export"

    def test_calibration_chart_uses_recharts(self):
        text = (CHARTS / "CalibrationChart.tsx").read_text(encoding="utf-8")
        assert "ScatterChart" in text
        assert "ReferenceLine" in text

    def test_brier_chart_uses_line_chart(self):
        text = (CHARTS / "BrierTimeSeriesChart.tsx").read_text(encoding="utf-8")
        assert "LineChart" in text
        assert "swarm_brier" in text
        assert "market_brier" in text

    def test_debate_lift_chart_uses_bar_chart(self):
        text = (CHARTS / "DebateLiftChart.tsx").read_text(encoding="utf-8")
        assert "BarChart" in text
        assert "lift" in text

    def test_team_diversity_has_gauge(self):
        text = (CHARTS / "TeamDiversityCard.tsx").read_text(encoding="utf-8")
        assert "diversityScore" in text
        assert "svg" in text.lower() or "circle" in text.lower()

    def test_agent_profile_has_badges(self):
        text = (CHARTS / "AgentCalibrationProfile.tsx").read_text(encoding="utf-8")
        assert "badges" in text
        assert "CalibrationChart" in text


# ── §2 Hook exists with expected exports ─────────────────────────

class TestDebateCalibrationHook:
    """useDebateCalibration hook has all required exports."""

    HOOK_FILE = HOOKS / "useDebateCalibration.ts"

    def test_hook_file_exists(self):
        assert self.HOOK_FILE.exists()

    def test_exports_use_debate_metrics(self):
        text = self.HOOK_FILE.read_text(encoding="utf-8")
        assert "export function useDebateMetrics" in text

    def test_exports_use_debate_leaderboard(self):
        text = self.HOOK_FILE.read_text(encoding="utf-8")
        assert "export function useDebateLeaderboard" in text

    def test_exports_use_agent_calibration(self):
        text = self.HOOK_FILE.read_text(encoding="utf-8")
        assert "export function useAgentCalibration" in text

    def test_exports_use_team_diversity(self):
        text = self.HOOK_FILE.read_text(encoding="utf-8")
        assert "export function useTeamDiversity" in text

    def test_exports_debate_metrics_type(self):
        text = self.HOOK_FILE.read_text(encoding="utf-8")
        assert "export interface DebateMetrics" in text

    def test_exports_calibration_bin_type(self):
        text = self.HOOK_FILE.read_text(encoding="utf-8")
        assert "export interface CalibrationBin" in text

    def test_exports_leaderboard_data_type(self):
        text = self.HOOK_FILE.read_text(encoding="utf-8")
        assert "export interface LeaderboardData" in text

    def test_exports_team_diversity_type(self):
        text = self.HOOK_FILE.read_text(encoding="utf-8")
        assert "export interface TeamDiversity" in text

    def test_exports_agent_badge_type(self):
        text = self.HOOK_FILE.read_text(encoding="utf-8")
        assert "export interface AgentBadge" in text

    def test_hook_uses_api_endpoints(self):
        text = self.HOOK_FILE.read_text(encoding="utf-8")
        assert "API_ENDPOINTS" in text


# ── §3 Constants have debate/calibration endpoints ───────────────

class TestConstantsDebateEndpoints:
    """constants.ts has all debate/calibration endpoint keys."""

    CONSTANTS_FILE = CONFIG / "constants.ts"

    REQUIRED_KEYS = [
        "DEBATE_METRICS",
        "DEBATE_LEADERBOARD",
        "DEBATE_BACKTEST",
        "AGENT_CALIBRATION",
        "AGENT_BADGES",
        "AGENT_REWARDS",
        "TEAM_LIST",
        "TEAM_DIVERSITY",
    ]

    def test_constants_file_exists(self):
        assert self.CONSTANTS_FILE.exists()

    @pytest.mark.parametrize("key", REQUIRED_KEYS)
    def test_endpoint_key_present(self, key: str):
        text = self.CONSTANTS_FILE.read_text(encoding="utf-8")
        assert key in text, f"Missing endpoint key: {key}"

    def test_agent_calibration_is_function(self):
        text = self.CONSTANTS_FILE.read_text(encoding="utf-8")
        assert "AGENT_CALIBRATION:" in text
        assert "agentId" in text

    def test_team_diversity_is_function(self):
        text = self.CONSTANTS_FILE.read_text(encoding="utf-8")
        assert "TEAM_DIVERSITY:" in text
        assert "teamId" in text


# ── §4 PredictionConsensusView integration ───────────────────────

class TestViewIntegration:
    """PredictionConsensusView imports and uses new components."""

    VIEW_FILE = VIEWS / "PredictionConsensusView.tsx"

    def test_view_exists(self):
        assert self.VIEW_FILE.exists()

    def test_imports_debate_hooks(self):
        text = self.VIEW_FILE.read_text(encoding="utf-8")
        assert "useDebateMetrics" in text
        assert "useDebateLeaderboard" in text
        assert "useAgentCalibration" in text

    def test_imports_calibration_chart(self):
        text = self.VIEW_FILE.read_text(encoding="utf-8")
        assert "CalibrationChart" in text

    def test_imports_debate_lift_chart(self):
        text = self.VIEW_FILE.read_text(encoding="utf-8")
        assert "DebateLiftChart" in text

    def test_imports_brier_time_series(self):
        text = self.VIEW_FILE.read_text(encoding="utf-8")
        assert "BrierTimeSeriesChart" in text

    def test_imports_agent_profile(self):
        text = self.VIEW_FILE.read_text(encoding="utf-8")
        assert "AgentCalibrationProfile" in text

    def test_has_calibration_section(self):
        text = self.VIEW_FILE.read_text(encoding="utf-8")
        assert "Calibration & Debate Lift" in text

    def test_has_agent_selection_state(self):
        text = self.VIEW_FILE.read_text(encoding="utf-8")
        assert "selectedAgentId" in text

    def test_has_debate_metrics_display(self):
        text = self.VIEW_FILE.read_text(encoding="utf-8")
        assert "avg_debate_lift" in text
        assert "active_debates" in text


# ── §5 Backend endpoints exist ───────────────────────────────────

class TestBackendEndpoints:
    """prediction_consensus_api.py has calibration/lift/diversity endpoints."""

    API_FILE = ROOT / "web" / "api" / "prediction_consensus_api.py"

    def test_api_file_exists(self):
        assert self.API_FILE.exists()

    def test_calibration_endpoint(self):
        text = self.API_FILE.read_text(encoding="utf-8")
        assert "/consensus/calibration/" in text

    def test_debate_metrics_endpoint(self):
        text = self.API_FILE.read_text(encoding="utf-8")
        assert "/consensus/debate-metrics" in text

    def test_team_diversity_endpoint(self):
        text = self.API_FILE.read_text(encoding="utf-8")
        assert "/consensus/teams/" in text
        assert "diversity" in text

    def test_leaderboard_endpoint(self):
        text = self.API_FILE.read_text(encoding="utf-8")
        assert "/consensus/leaderboard" in text

    def test_badges_endpoint(self):
        text = self.API_FILE.read_text(encoding="utf-8")
        assert "/consensus/badges/" in text

    def test_backtest_endpoint(self):
        text = self.API_FILE.read_text(encoding="utf-8")
        assert "/consensus/backtest" in text

    def test_parameter_sweep_endpoint(self):
        text = self.API_FILE.read_text(encoding="utf-8")
        assert "/consensus/parameter-sweep" in text


# ── §6 Backend debate.py has calibration methods ─────────────────

class TestDebateModule:
    """merid/prediction/debate.py has calibration/diversity/backtest classes."""

    DEBATE_FILE = ROOT / "merid" / "prediction" / "debate.py"

    def test_debate_file_exists(self):
        assert self.DEBATE_FILE.exists()

    def test_has_compute_calibration_score(self):
        text = self.DEBATE_FILE.read_text(encoding="utf-8")
        assert "compute_calibration_score" in text

    def test_has_compute_team_diversity_score(self):
        text = self.DEBATE_FILE.read_text(encoding="utf-8")
        assert "compute_team_diversity_score" in text

    def test_has_debate_backtester(self):
        text = self.DEBATE_FILE.read_text(encoding="utf-8")
        assert "DebateBacktester" in text

    def test_has_reward_parameter_sweep(self):
        text = self.DEBATE_FILE.read_text(encoding="utf-8")
        assert "RewardParameterSweep" in text

    def test_has_compute_leaderboard(self):
        text = self.DEBATE_FILE.read_text(encoding="utf-8")
        assert "compute_leaderboard" in text

    def test_has_compute_badges(self):
        text = self.DEBATE_FILE.read_text(encoding="utf-8")
        assert "compute_badges" in text
