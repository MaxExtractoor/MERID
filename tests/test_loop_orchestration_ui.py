"""
Sprint 11 — Loop Orchestration UI tests.

Validates:
  1. Endpoint constants (ORCHESTRATOR_SUMMARY, ORCHESTRATOR_HISTORY, etc.)
  2. useLoopOrchestration hook types and data flow
  3. useStageMetrics hook types and derivation logic
  4. LoopPipelineDiagram component structure
  5. LoopCadenceChart component structure
  6. StageHealthCards component structure
  7. WiringStatusPanel component structure
  8. LoopOrchestrationView assembly and integration
  9. Navigation wiring (App.tsx + Sidebar.tsx)
  10. Backend API endpoint availability
"""

from __future__ import annotations

import json
import os
import re
import textwrap
from pathlib import Path
from typing import Any, Dict, List

import pytest

# ── Paths ──────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parent.parent
REACT_SRC = ROOT / "web" / "react" / "src"
CONSTANTS_FILE = REACT_SRC / "config" / "constants.ts"
HOOK_FILE = REACT_SRC / "hooks" / "useLoopOrchestration.ts"
PIPELINE_DIAGRAM_FILE = REACT_SRC / "components" / "charts" / "LoopPipelineDiagram.tsx"
CADENCE_CHART_FILE = REACT_SRC / "components" / "charts" / "LoopCadenceChart.tsx"
STAGE_CARDS_FILE = REACT_SRC / "components" / "charts" / "StageHealthCards.tsx"
WIRING_PANEL_FILE = REACT_SRC / "components" / "charts" / "WiringStatusPanel.tsx"
VIEW_FILE = REACT_SRC / "views" / "LoopOrchestrationView.tsx"
APP_FILE = REACT_SRC / "App.tsx"
SIDEBAR_FILE = REACT_SRC / "components" / "Sidebar.tsx"
ORCHESTRATOR_API_FILE = ROOT / "web" / "api" / "orchestrator_api.py"
SYSTEM_OBS_FILE = ROOT / "web" / "api" / "system_observability.py"
SYSTEM_HEALTH_FILE = ROOT / "web" / "api" / "system_endpoints.py"


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


# ═══════════════════════════════════════════════════════════════════
# §1  Endpoint Constants
# ═══════════════════════════════════════════════════════════════════


class TestEndpointConstants:
    """Verify all loop orchestration constants are defined."""

    src = _read(CONSTANTS_FILE)

    def test_orchestrator_summary_constant(self):
        assert "ORCHESTRATOR_SUMMARY" in self.src
        assert "/api/v1/orchestrator/summary" in self.src

    def test_orchestrator_history_constant(self):
        assert "ORCHESTRATOR_HISTORY" in self.src
        assert "/api/v1/orchestrator/history" in self.src

    def test_decisions_recent_constant(self):
        assert "DECISIONS_RECENT" in self.src
        assert "/api/v1/system/decisions/recent" in self.src

    def test_consensus_history_constant(self):
        assert "CONSENSUS_HISTORY" in self.src
        assert "/api/v1/system/consensus/history" in self.src

    def test_existing_observability_constants_preserved(self):
        assert "OBSERVABILITY_SUMMARY" in self.src
        assert "OBSERVABILITY_ALERTS" in self.src
        assert "OBSERVABILITY_SLO" in self.src
        assert "SIGNAL_SLO_METRICS" in self.src

    def test_system_health_constants_exist(self):
        assert "SYSTEM_HEALTH" in self.src
        assert "SYSTEM_HEALTH_V2" in self.src

    def test_no_duplicate_orchestrator_keys(self):
        matches = re.findall(r"ORCHESTRATOR_SUMMARY:", self.src)
        assert len(matches) == 1, "ORCHESTRATOR_SUMMARY defined more than once"
        matches = re.findall(r"ORCHESTRATOR_HISTORY:", self.src)
        assert len(matches) == 1, "ORCHESTRATOR_HISTORY defined more than once"

    def test_loop_orchestration_section_comment(self):
        assert "// Loop Orchestration" in self.src


# ═══════════════════════════════════════════════════════════════════
# §2  useLoopOrchestration Hook
# ═══════════════════════════════════════════════════════════════════


class TestUseLoopOrchestrationHook:
    """Verify hook file structure, types, and exports."""

    src = _read(HOOK_FILE)

    def test_file_exists(self):
        assert HOOK_FILE.exists()

    def test_exports_useLoopOrchestration(self):
        assert "export function useLoopOrchestration" in self.src

    def test_exports_useStageMetrics(self):
        assert "export function useStageMetrics" in self.src

    def test_phaseagent_interface(self):
        assert "export interface PhaseAgent" in self.src

    def test_cyclephase_interface(self):
        assert "export interface CyclePhase" in self.src

    def test_latestcycle_interface(self):
        assert "export interface LatestCycle" in self.src

    def test_cyclehistoryentry_interface(self):
        assert "export interface CycleHistoryEntry" in self.src

    def test_loop_orchestration_data_interface(self):
        assert "export interface LoopOrchestrationData" in self.src

    def test_stage_health_interface(self):
        assert "export interface StageHealth" in self.src

    def test_wiring_link_interface(self):
        assert "export interface WiringLink" in self.src

    def test_stage_metrics_data_interface(self):
        assert "export interface StageMetricsData" in self.src

    def test_stage_status_type(self):
        assert "export type StageStatus" in self.src

    def test_imports_api_endpoints(self):
        assert "API_ENDPOINTS" in self.src

    def test_fetches_orchestrator_summary(self):
        assert "ORCHESTRATOR_SUMMARY" in self.src

    def test_fetches_orchestrator_history(self):
        assert "ORCHESTRATOR_HISTORY" in self.src

    def test_fetches_observability_summary(self):
        assert "OBSERVABILITY_SUMMARY" in self.src

    def test_pipeline_stages_defined(self):
        assert "PIPELINE_STAGES" in self.src
        for stage in ["signal", "consensus", "debate", "risk", "execution", "betting"]:
            assert f'"{stage}"' in self.src or f"'{stage}'" in self.src

    def test_pipeline_wiring_defined(self):
        assert "PIPELINE_WIRING" in self.src

    def test_computes_avg_cycle_duration(self):
        assert "avgCycleDurationMs" in self.src

    def test_computes_cycles_per_minute(self):
        assert "cyclesPerMinute" in self.src

    def test_computes_total_proposals(self):
        assert "totalProposals" in self.src

    def test_derives_stage_status(self):
        assert "deriveStageStatus" in self.src

    def test_extracts_latency(self):
        assert "extractLatency" in self.src

    def test_extracts_throughput(self):
        assert "extractThroughput" in self.src

    def test_extracts_error_rate(self):
        assert "extractErrorRate" in self.src

    def test_overall_status_derivation(self):
        assert "overallStatus" in self.src

    def test_returns_loading_state(self):
        assert "loading" in self.src

    def test_returns_error_state(self):
        assert "setError" in self.src

    def test_returns_refresh_function(self):
        assert "refresh" in self.src

    def test_poll_interval_parameter(self):
        assert "pollMs" in self.src

    def test_uses_useEffect_for_polling(self):
        assert "useEffect" in self.src
        assert "setInterval" in self.src

    def test_clears_interval_on_cleanup(self):
        assert "clearInterval" in self.src


# ═══════════════════════════════════════════════════════════════════
# §3  LoopPipelineDiagram Component
# ═══════════════════════════════════════════════════════════════════


class TestLoopPipelineDiagram:
    """Verify pipeline diagram component structure."""

    src = _read(PIPELINE_DIAGRAM_FILE)

    def test_file_exists(self):
        assert PIPELINE_DIAGRAM_FILE.exists()

    def test_default_export(self):
        assert "export default function LoopPipelineDiagram" in self.src

    def test_accepts_latest_cycle_prop(self):
        assert "latestCycle" in self.src

    def test_accepts_stage_statuses_prop(self):
        assert "stageStatuses" in self.src

    def test_stage_configs_defined(self):
        assert "STAGE_CONFIGS" in self.src

    def test_all_six_stages_present(self):
        for stage in ["Signal", "Consensus", "Debate", "Risk", "Execution", "Betting"]:
            assert stage in self.src

    def test_status_styles_defined(self):
        assert "STATUS_STYLES" in self.src

    def test_healthy_status_style(self):
        assert "healthy" in self.src
        assert "emerald" in self.src

    def test_degraded_status_style(self):
        assert "degraded" in self.src
        assert "amber" in self.src

    def test_down_status_style(self):
        assert "down:" in self.src or '"down"' in self.src or "'down'" in self.src
        assert "rose" in self.src

    def test_arrow_connectors(self):
        assert "ArrowRight" in self.src

    def test_phase_matching(self):
        assert "matchPhase" in self.src

    def test_duration_formatting(self):
        assert "formatDuration" in self.src

    def test_agent_count_display(self):
        assert "agentCount" in self.src
        assert "outputCount" in self.src

    def test_progress_bar(self):
        assert "bg-slate-700 rounded-full overflow-hidden" in self.src

    def test_cycle_summary_bar(self):
        assert "cycleId" in self.src
        assert "proposalsGenerated" in self.src
        assert "spikesDetected" in self.src
        assert "verdictsIssued" in self.src

    def test_imports_lucide_icons(self):
        for icon in ["Activity", "Users", "MessageSquare", "Shield", "Zap", "TrendingUp"]:
            assert icon in self.src

    def test_responsive_layout(self):
        assert "md:flex-row" in self.src


# ═══════════════════════════════════════════════════════════════════
# §4  LoopCadenceChart Component
# ═══════════════════════════════════════════════════════════════════


class TestLoopCadenceChart:
    """Verify cadence chart component structure."""

    src = _read(CADENCE_CHART_FILE)

    def test_file_exists(self):
        assert CADENCE_CHART_FILE.exists()

    def test_default_export(self):
        assert "export default function LoopCadenceChart" in self.src

    def test_accepts_history_prop(self):
        assert "history" in self.src

    def test_accepts_avg_duration_prop(self):
        assert "avgCycleDurationMs" in self.src

    def test_uses_composed_chart(self):
        assert "ComposedChart" in self.src

    def test_uses_bar_for_duration(self):
        assert "Bar" in self.src
        assert "durationMs" in self.src

    def test_uses_line_for_proposals(self):
        assert "Line" in self.src
        assert "proposals" in self.src

    def test_reference_line_for_average(self):
        assert "ReferenceLine" in self.src

    def test_dual_y_axes(self):
        assert 'yAxisId="duration"' in self.src
        assert 'yAxisId="count"' in self.src

    def test_responsive_container(self):
        assert "ResponsiveContainer" in self.src

    def test_custom_tooltip(self):
        assert "CadenceTooltip" in self.src

    def test_empty_state(self):
        assert "No cycle history available" in self.src

    def test_imports_recharts(self):
        assert "from \"recharts\"" in self.src or "from 'recharts'" in self.src

    def test_chart_data_mapping(self):
        assert "chartData" in self.src
        assert "useMemo" in self.src


# ═══════════════════════════════════════════════════════════════════
# §5  StageHealthCards Component
# ═══════════════════════════════════════════════════════════════════


class TestStageHealthCards:
    """Verify stage health cards component structure."""

    src = _read(STAGE_CARDS_FILE)

    def test_file_exists(self):
        assert STAGE_CARDS_FILE.exists()

    def test_default_export(self):
        assert "export default function StageHealthCards" in self.src

    def test_accepts_stages_prop(self):
        assert "stages" in self.src

    def test_stage_card_subcomponent(self):
        assert "function StageCard" in self.src

    def test_stage_icons_map(self):
        assert "STAGE_ICONS" in self.src

    def test_status_config(self):
        assert "STATUS_CFG" in self.src

    def test_latency_bar(self):
        assert "latencyPct" in self.src
        assert "latencyColor" in self.src

    def test_error_rate_bar(self):
        assert "errorPct" in self.src
        assert "errorColor" in self.src

    def test_throughput_display(self):
        assert "Throughput" in self.src

    def test_latency_thresholds(self):
        # 500ms and 1000ms thresholds
        assert "500" in self.src
        assert "1000" in self.src

    def test_error_rate_thresholds(self):
        # 0.01 and 0.05 thresholds
        assert "0.01" in self.src
        assert "0.05" in self.src

    def test_grid_layout(self):
        assert "grid" in self.src
        assert "lg:grid-cols-3" in self.src

    def test_empty_state(self):
        assert "No stage health data available" in self.src

    def test_imports_lucide_icons(self):
        assert "Clock" in self.src
        assert "BarChart3" in self.src
        assert "AlertOctagon" in self.src

    def test_status_labels(self):
        for label in ["Healthy", "Degraded", "Down", "Unknown"]:
            assert label in self.src


# ═══════════════════════════════════════════════════════════════════
# §6  WiringStatusPanel Component
# ═══════════════════════════════════════════════════════════════════


class TestWiringStatusPanel:
    """Verify wiring status panel component structure."""

    src = _read(WIRING_PANEL_FILE)

    def test_file_exists(self):
        assert WIRING_PANEL_FILE.exists()

    def test_default_export(self):
        assert "export default function WiringStatusPanel" in self.src

    def test_accepts_wiring_prop(self):
        assert "wiring" in self.src

    def test_accepts_services_prop(self):
        assert "services" in self.src

    def test_link_status_config(self):
        assert "LINK_STATUS" in self.src

    def test_stage_labels(self):
        assert "STAGE_LABELS" in self.src
        for label in ["Signal", "Consensus", "Debate", "Risk", "Execution", "Betting"]:
            assert label in self.src

    def test_arrow_connectors(self):
        assert "ArrowRight" in self.src

    def test_pipeline_wiring_section(self):
        assert "Pipeline Wiring" in self.src

    def test_infrastructure_services_section(self):
        assert "Infrastructure Services" in self.src

    def test_connection_status_labels(self):
        assert "Connected" in self.src
        assert "Disconnected" in self.src

    def test_data_flow_rate_display(self):
        assert "dataFlowRate" in self.src

    def test_empty_wiring_state(self):
        assert "No wiring data available" in self.src

    def test_service_health_indicator(self):
        assert "isHealthy" in self.src

    def test_imports_wifi_icons(self):
        assert "Wifi" in self.src
        assert "WifiOff" in self.src
        assert "Server" in self.src


# ═══════════════════════════════════════════════════════════════════
# §7  LoopOrchestrationView Assembly
# ═══════════════════════════════════════════════════════════════════


class TestLoopOrchestrationView:
    """Verify the main view assembles all components correctly."""

    src = _read(VIEW_FILE)

    def test_file_exists(self):
        assert VIEW_FILE.exists()

    def test_default_export(self):
        assert "export default function LoopOrchestrationView" in self.src

    def test_imports_useLoopOrchestration(self):
        assert "useLoopOrchestration" in self.src

    def test_imports_useStageMetrics(self):
        assert "useStageMetrics" in self.src

    def test_imports_pipeline_diagram(self):
        assert "LoopPipelineDiagram" in self.src

    def test_imports_cadence_chart(self):
        assert "LoopCadenceChart" in self.src

    def test_imports_stage_health_cards(self):
        assert "StageHealthCards" in self.src

    def test_imports_wiring_panel(self):
        assert "WiringStatusPanel" in self.src

    def test_pipeline_flow_section(self):
        assert "Pipeline Flow" in self.src

    def test_cadence_section(self):
        assert "Cycle Cadence" in self.src

    def test_stage_health_section(self):
        assert "Stage Health" in self.src

    def test_wiring_section(self):
        assert "Wiring" in self.src

    def test_collapsible_sections(self):
        assert "showPipeline" in self.src
        assert "showCadence" in self.src
        assert "showStages" in self.src
        assert "showWiring" in self.src

    def test_refresh_button(self):
        assert "handleRefresh" in self.src
        assert "RefreshCw" in self.src

    def test_overall_status_badge(self):
        assert "overallStatus" in self.src
        assert "statusCfg" in self.src

    def test_summary_stats_bar(self):
        assert "Avg Cycle" in self.src
        assert "Cycles/min" in self.src
        assert "Total Proposals" in self.src

    def test_error_banner(self):
        assert "loopError" in self.src
        assert "AlertTriangle" in self.src

    def test_loading_state(self):
        assert "loading" in self.src
        assert "animate-spin" in self.src

    def test_header_icon(self):
        assert "GitBranch" in self.src

    def test_accessibility_label(self):
        assert "aria-label" in self.src

    def test_chevron_toggle_icons(self):
        assert "ChevronDown" in self.src
        assert "ChevronRight" in self.src


# ═══════════════════════════════════════════════════════════════════
# §8  Navigation Wiring
# ═══════════════════════════════════════════════════════════════════


class TestNavigationWiring:
    """Verify App.tsx and Sidebar.tsx are wired correctly."""

    app_src = _read(APP_FILE)
    sidebar_src = _read(SIDEBAR_FILE)

    def test_app_imports_view(self):
        assert "import LoopOrchestrationView" in self.app_src

    def test_app_view_type_includes_route(self):
        assert '"loop-orchestration"' in self.app_src

    def test_app_renders_view(self):
        assert "loop-orchestration" in self.app_src
        assert "<LoopOrchestrationView" in self.app_src

    def test_sidebar_view_type_includes_route(self):
        assert '"loop-orchestration"' in self.sidebar_src

    def test_sidebar_nav_entry(self):
        assert "Loop Orchestration" in self.sidebar_src

    def test_sidebar_nav_href(self):
        assert "'loop-orchestration'" in self.sidebar_src

    def test_sidebar_icon(self):
        assert "GitBranch" in self.sidebar_src

    def test_sidebar_system_section(self):
        # Loop Orchestration should be in the system section
        system_match = re.search(r"const system\s*=\s*\[([^\]]+)\]", self.sidebar_src, re.DOTALL)
        assert system_match, "system nav section not found"
        assert "loop-orchestration" in system_match.group(1)


# ═══════════════════════════════════════════════════════════════════
# §9  Backend API Endpoints
# ═══════════════════════════════════════════════════════════════════


class TestBackendAPIs:
    """Verify backend API files expose the expected endpoints."""

    orch_src = _read(ORCHESTRATOR_API_FILE)
    obs_src = _read(SYSTEM_OBS_FILE)
    health_src = _read(SYSTEM_HEALTH_FILE)

    def test_orchestrator_summary_endpoint(self):
        assert "/summary" in self.orch_src
        assert "get_orchestrator_summary" in self.orch_src

    def test_orchestrator_history_endpoint(self):
        assert "/history" in self.orch_src
        assert "get_orchestrator_history" in self.orch_src

    def test_orchestrator_returns_phases(self):
        assert "phases" in self.orch_src

    def test_orchestrator_returns_cycle_id(self):
        assert "cycleId" in self.orch_src or "cycle_id" in self.orch_src

    def test_orchestrator_returns_duration(self):
        assert "totalDurationMs" in self.orch_src or "total_duration_ms" in self.orch_src

    def test_orchestrator_returns_proposals(self):
        assert "proposalsGenerated" in self.orch_src or "proposals_generated" in self.orch_src

    def test_observability_endpoint(self):
        assert "/api/v1/system/observability" in self.obs_src

    def test_observability_returns_signal_slo(self):
        assert "signal_metrics_slo" in self.obs_src

    def test_observability_returns_consensus_store(self):
        assert "consensus_store" in self.obs_src

    def test_observability_returns_collaboration(self):
        assert "collaboration_health" in self.obs_src

    def test_observability_returns_betting(self):
        assert "betting_health" in self.obs_src

    def test_observability_returns_alerts(self):
        assert "alerts" in self.obs_src

    def test_system_health_endpoint(self):
        assert "/api/system/health" in self.health_src

    def test_system_health_returns_services(self):
        assert "services" in self.health_src

    def test_system_health_returns_status(self):
        assert '"healthy"' in self.health_src or "'healthy'" in self.health_src


# ═══════════════════════════════════════════════════════════════════
# §10  Integration — Cross-file Consistency
# ═══════════════════════════════════════════════════════════════════


class TestIntegration:
    """Cross-file consistency checks."""

    constants_src = _read(CONSTANTS_FILE)
    hook_src = _read(HOOK_FILE)
    view_src = _read(VIEW_FILE)
    pipeline_src = _read(PIPELINE_DIAGRAM_FILE)
    cadence_src = _read(CADENCE_CHART_FILE)
    stage_cards_src = _read(STAGE_CARDS_FILE)
    wiring_src = _read(WIRING_PANEL_FILE)

    def test_hook_uses_constants_from_config(self):
        assert "API_ENDPOINTS" in self.hook_src
        assert "../config/constants" in self.hook_src

    def test_view_imports_from_hooks(self):
        assert "../hooks/useLoopOrchestration" in self.view_src

    def test_view_imports_all_chart_components(self):
        assert "../components/charts/LoopPipelineDiagram" in self.view_src
        assert "../components/charts/LoopCadenceChart" in self.view_src
        assert "../components/charts/StageHealthCards" in self.view_src
        assert "../components/charts/WiringStatusPanel" in self.view_src

    def test_pipeline_imports_hook_types(self):
        assert "../../hooks/useLoopOrchestration" in self.pipeline_src

    def test_cadence_imports_hook_types(self):
        assert "../../hooks/useLoopOrchestration" in self.cadence_src

    def test_stage_cards_imports_hook_types(self):
        assert "../../hooks/useLoopOrchestration" in self.stage_cards_src

    def test_wiring_imports_hook_types(self):
        assert "../../hooks/useLoopOrchestration" in self.wiring_src

    def test_six_pipeline_stages_consistent(self):
        """All files agree on the 6 pipeline stages."""
        stages = ["signal", "consensus", "debate", "risk", "execution", "betting"]
        for stage in stages:
            assert stage in self.hook_src, f"Stage '{stage}' missing from hook"

    def test_stage_statuses_consistent(self):
        """All status types are consistent across components."""
        for status in ["healthy", "degraded", "down", "unknown"]:
            assert status in self.hook_src
            assert status in self.pipeline_src

    def test_constants_match_backend_routes(self):
        assert "/api/v1/orchestrator/summary" in self.constants_src
        assert "/api/v1/orchestrator/history" in self.constants_src

    def test_all_new_files_exist(self):
        assert HOOK_FILE.exists()
        assert PIPELINE_DIAGRAM_FILE.exists()
        assert CADENCE_CHART_FILE.exists()
        assert STAGE_CARDS_FILE.exists()
        assert WIRING_PANEL_FILE.exists()
        assert VIEW_FILE.exists()
