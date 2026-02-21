"""
Sprint 10 — Live Odds & SLO Visualization Tests

Verifies:
  - New hooks: useLiveOdds, useSLOMetrics
  - New chart components: OddsSparkline, LiveOddsPanel, SLOBurndownChart, SLOStatusCards
  - Integration into BettingConsensusView and ObservabilityView
  - API endpoint constants wiring
"""

import ast
import os
import re
import json
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REACT = os.path.join(ROOT, "web", "react", "src")


def _read(relpath: str) -> str:
    full = os.path.join(ROOT, relpath)
    assert os.path.isfile(full), f"Missing file: {relpath}"
    with open(full, encoding="utf-8") as f:
        return f.read()


# ── Hook files exist and export correctly ─────────────────────────

class TestUseLiveOddsHook:
    SRC = "web/react/src/hooks/useLiveOdds.ts"

    def test_file_exists(self):
        assert os.path.isfile(os.path.join(ROOT, self.SRC))

    def test_exports_useLiveOddsSnapshots(self):
        src = _read(self.SRC)
        assert "export function useLiveOddsSnapshots" in src

    def test_exports_useEventOddsHistory(self):
        src = _read(self.SRC)
        assert "export function useEventOddsHistory" in src

    def test_exports_OddsPoint_type(self):
        src = _read(self.SRC)
        assert "export interface OddsPoint" in src

    def test_exports_EventOddsSnapshot_type(self):
        src = _read(self.SRC)
        assert "export interface EventOddsSnapshot" in src

    def test_exports_LiveOddsData_type(self):
        src = _read(self.SRC)
        assert "export interface LiveOddsData" in src

    def test_uses_BETTING_CONSENSUS_SUMMARY_endpoint(self):
        src = _read(self.SRC)
        assert "API_ENDPOINTS.BETTING_CONSENSUS_SUMMARY" in src

    def test_uses_SPORTS_LIVE_EVENT_endpoint(self):
        src = _read(self.SRC)
        assert "API_ENDPOINTS.SPORTS_LIVE_EVENT" in src

    def test_accumulates_sparkline_history(self):
        src = _read(self.SRC)
        assert "MAX_SPARKLINE_POINTS" in src
        assert "historyRef" in src

    def test_detects_line_move_alert(self):
        src = _read(self.SRC)
        assert "line_move_alert" in src
        assert "lineAlert" in src


class TestUseSLOMetricsHook:
    SRC = "web/react/src/hooks/useSLOMetrics.ts"

    def test_file_exists(self):
        assert os.path.isfile(os.path.join(ROOT, self.SRC))

    def test_exports_useSLOMetrics(self):
        src = _read(self.SRC)
        assert "export function useSLOMetrics" in src

    def test_exports_useSportsSLO(self):
        src = _read(self.SRC)
        assert "export function useSportsSLO" in src

    def test_exports_SubsystemSLO_type(self):
        src = _read(self.SRC)
        assert "export interface SubsystemSLO" in src

    def test_exports_SLOBurnPoint_type(self):
        src = _read(self.SRC)
        assert "export interface SLOBurnPoint" in src

    def test_exports_SLOMetricsData_type(self):
        src = _read(self.SRC)
        assert "export interface SLOMetricsData" in src

    def test_exports_SportsSLOData_type(self):
        src = _read(self.SRC)
        assert "export interface SportsSLOData" in src

    def test_uses_OBSERVABILITY_SUMMARY_endpoint(self):
        src = _read(self.SRC)
        assert "API_ENDPOINTS.OBSERVABILITY_SUMMARY" in src

    def test_uses_SPORTS_SLO_METRICS_endpoint(self):
        src = _read(self.SRC)
        assert "API_ENDPOINTS.SPORTS_SLO_METRICS" in src

    def test_computes_error_budget(self):
        src = _read(self.SRC)
        assert "computeErrorBudget" in src

    def test_accumulates_burn_history(self):
        src = _read(self.SRC)
        assert "MAX_BURN_POINTS" in src
        assert "burnRef" in src


# ── Chart components exist and render correctly ───────────────────

class TestOddsSparkline:
    SRC = "web/react/src/components/charts/OddsSparkline.tsx"

    def test_file_exists(self):
        assert os.path.isfile(os.path.join(ROOT, self.SRC))

    def test_default_export(self):
        src = _read(self.SRC)
        assert "export default function OddsSparkline" in src

    def test_uses_recharts_LineChart(self):
        src = _read(self.SRC)
        assert "LineChart" in src
        assert "Line" in src

    def test_renders_book_and_swarm_lines(self):
        src = _read(self.SRC)
        assert 'dataKey="book_prob"' in src
        assert 'dataKey="swarm_prob"' in src

    def test_accepts_showAlert_prop(self):
        src = _read(self.SRC)
        assert "showAlert" in src

    def test_imports_OddsPoint_type(self):
        src = _read(self.SRC)
        assert "OddsPoint" in src


class TestLiveOddsPanel:
    SRC = "web/react/src/components/charts/LiveOddsPanel.tsx"

    def test_file_exists(self):
        assert os.path.isfile(os.path.join(ROOT, self.SRC))

    def test_default_export(self):
        src = _read(self.SRC)
        assert "export default function LiveOddsPanel" in src

    def test_renders_OddsSparkline(self):
        src = _read(self.SRC)
        assert "OddsSparkline" in src

    def test_renders_sport_badges(self):
        src = _read(self.SRC)
        assert "SPORT_COLORS" in src

    def test_renders_line_alert_indicator(self):
        src = _read(self.SRC)
        assert "AlertTriangle" in src
        assert "line_move_alert" in src

    def test_sorts_live_first(self):
        src = _read(self.SRC)
        assert 'a.state === "live"' in src

    def test_imports_EventOddsSnapshot_type(self):
        src = _read(self.SRC)
        assert "EventOddsSnapshot" in src


class TestSLOBurndownChart:
    SRC = "web/react/src/components/charts/SLOBurndownChart.tsx"

    def test_file_exists(self):
        assert os.path.isfile(os.path.join(ROOT, self.SRC))

    def test_default_export(self):
        src = _read(self.SRC)
        assert "export default function SLOBurndownChart" in src

    def test_uses_recharts_ComposedChart(self):
        src = _read(self.SRC)
        assert "ComposedChart" in src
        assert "Area" in src
        assert "Bar" in src

    def test_renders_reference_lines(self):
        src = _read(self.SRC)
        assert "ReferenceLine" in src
        assert "80%" in src
        assert "50%" in src

    def test_renders_budget_area(self):
        src = _read(self.SRC)
        assert 'dataKey="budget"' in src

    def test_renders_violations_bar(self):
        src = _read(self.SRC)
        assert 'dataKey="violations"' in src

    def test_imports_SLOBurnPoint_type(self):
        src = _read(self.SRC)
        assert "SLOBurnPoint" in src


class TestSLOStatusCards:
    SRC = "web/react/src/components/charts/SLOStatusCards.tsx"

    def test_file_exists(self):
        assert os.path.isfile(os.path.join(ROOT, self.SRC))

    def test_default_export(self):
        src = _read(self.SRC)
        assert "export default function SLOStatusCards" in src

    def test_renders_overall_gauge(self):
        src = _read(self.SRC)
        assert "Overall SLO" in src
        assert "Error Budget" in src

    def test_renders_per_subsystem_cards(self):
        src = _read(self.SRC)
        assert "sub.name" in src
        assert "sub.p95_ms" in src
        assert "sub.threshold_ms" in src

    def test_renders_usage_bar(self):
        src = _read(self.SRC)
        assert "usagePct" in src

    def test_imports_SubsystemSLO_type(self):
        src = _read(self.SRC)
        assert "SubsystemSLO" in src


# ── Integration into views ────────────────────────────────────────

class TestBettingConsensusViewIntegration:
    SRC = "web/react/src/views/BettingConsensusView.tsx"

    def test_imports_useLiveOddsSnapshots(self):
        src = _read(self.SRC)
        assert "useLiveOddsSnapshots" in src

    def test_imports_OddsSparkline(self):
        src = _read(self.SRC)
        assert "OddsSparkline" in src

    def test_imports_LiveOddsPanel(self):
        src = _read(self.SRC)
        assert "LiveOddsPanel" in src

    def test_calls_useLiveOddsSnapshots_hook(self):
        src = _read(self.SRC)
        assert "useLiveOddsSnapshots(" in src

    def test_passes_sparkline_to_EventCard(self):
        src = _read(self.SRC)
        assert "sparklineData" in src

    def test_passes_lineAlert_to_EventCard(self):
        src = _read(self.SRC)
        assert "lineAlert" in src

    def test_renders_LiveOddsPanel_section(self):
        src = _read(self.SRC)
        assert "Live Odds Movement" in src

    def test_EventCard_accepts_sparkline_props(self):
        src = _read(self.SRC)
        assert "sparklineData?" in src
        assert "lineAlert?" in src

    def test_renders_OddsSparkline_in_EventCard(self):
        src = _read(self.SRC)
        assert "<OddsSparkline" in src


class TestObservabilityViewIntegration:
    SRC = "web/react/src/views/ObservabilityView.tsx"

    def test_imports_useSLOMetrics(self):
        src = _read(self.SRC)
        assert "useSLOMetrics" in src

    def test_imports_useSportsSLO(self):
        src = _read(self.SRC)
        assert "useSportsSLO" in src

    def test_imports_SLOBurndownChart(self):
        src = _read(self.SRC)
        assert "SLOBurndownChart" in src

    def test_imports_SLOStatusCards(self):
        src = _read(self.SRC)
        assert "SLOStatusCards" in src

    def test_calls_useSLOMetrics_hook(self):
        src = _read(self.SRC)
        assert "useSLOMetrics(" in src

    def test_calls_useSportsSLO_hook(self):
        src = _read(self.SRC)
        assert "useSportsSLO(" in src

    def test_renders_SLOStatusCards(self):
        src = _read(self.SRC)
        assert "<SLOStatusCards" in src

    def test_renders_SLOBurndownChart(self):
        src = _read(self.SRC)
        assert "<SLOBurndownChart" in src

    def test_renders_sports_slo_section(self):
        src = _read(self.SRC)
        assert "Live Betting SLO" in src

    def test_renders_error_budget_burndown_section(self):
        src = _read(self.SRC)
        assert "Error Budget Burn-Down" in src

    def test_renders_slo_section_header(self):
        src = _read(self.SRC)
        assert "SLO Metrics" in src


# ── API endpoint constants ────────────────────────────────────────

class TestAPIEndpointConstants:
    SRC = "web/react/src/config/constants.ts"

    def test_BETTING_CONSENSUS_SUMMARY(self):
        src = _read(self.SRC)
        assert "BETTING_CONSENSUS_SUMMARY" in src

    def test_SPORTS_LIVE_EVENT(self):
        src = _read(self.SRC)
        assert "SPORTS_LIVE_EVENT" in src

    def test_SPORTS_SLO_METRICS(self):
        src = _read(self.SRC)
        assert "SPORTS_SLO_METRICS" in src

    def test_OBSERVABILITY_SUMMARY(self):
        src = _read(self.SRC)
        assert "OBSERVABILITY_SUMMARY" in src

    def test_OBSERVABILITY_SLO(self):
        src = _read(self.SRC)
        assert "OBSERVABILITY_SLO" in src

    def test_SPORTS_LIVE_ODDS(self):
        src = _read(self.SRC)
        assert "SPORTS_LIVE_ODDS" in src

    def test_SPORTS_ODDS_HISTORY(self):
        src = _read(self.SRC)
        assert "SPORTS_ODDS_HISTORY" in src
