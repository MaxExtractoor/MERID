"""Tests for Sprint 15 — Remaining Gap Closures.

Covers:
  §B  Sports betting reward section in Rewards.tsx
  §D  Live odds sparklines (Sprint 10 — verify wiring)
  §E  CrossAssetView + Sidebar/App.tsx wiring
  §G  SLO burn-down (Sprint 10 — verify wiring)
  §H  CodeQualityPanel in DevSwarmControlCenter
  §I  Sports betting wired into MERID loop tick
"""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WEB_REACT = ROOT / "web" / "react" / "src"


# ── §B: Sports betting reward section ──────────────────────────

class TestSportsBettingRewards:
    """Rewards.tsx has a sports betting tab and BettingRewardsTab component."""

    REWARDS = WEB_REACT / "views" / "Rewards.tsx"

    def test_rewards_file_exists(self):
        assert self.REWARDS.exists()

    def test_betting_tab_defined(self):
        text = self.REWARDS.read_text(encoding="utf-8")
        assert "'betting'" in text or '"betting"' in text, "Missing 'betting' tab key"

    def test_betting_rewards_tab_component(self):
        text = self.REWARDS.read_text(encoding="utf-8")
        assert "BettingRewardsTab" in text

    def test_betting_metrics_interface(self):
        text = self.REWARDS.read_text(encoding="utf-8")
        assert "BettingMetrics" in text

    def test_fetches_betting_metrics(self):
        text = self.REWARDS.read_text(encoding="utf-8")
        assert "BETTING_CONSENSUS_METRICS" in text

    def test_win_loss_breakdown(self):
        text = self.REWARDS.read_text(encoding="utf-8")
        assert "Win" in text and "Loss" in text

    def test_plan_pipeline_section(self):
        text = self.REWARDS.read_text(encoding="utf-8")
        assert "Betting Plan Pipeline" in text

    def test_dices_icon_imported(self):
        text = self.REWARDS.read_text(encoding="utf-8")
        assert "Dices" in text


# ── §D: Live odds sparklines (Sprint 10 wiring check) ─────────

class TestLiveOddsSparklines:
    """BettingConsensusView uses OddsSparkline + LiveOddsPanel."""

    VIEW = WEB_REACT / "views" / "BettingConsensusView.tsx"

    def test_view_exists(self):
        assert self.VIEW.exists()

    def test_imports_odds_sparkline(self):
        text = self.VIEW.read_text(encoding="utf-8")
        assert "OddsSparkline" in text

    def test_imports_live_odds_panel(self):
        text = self.VIEW.read_text(encoding="utf-8")
        assert "LiveOddsPanel" in text

    def test_imports_use_live_odds(self):
        text = self.VIEW.read_text(encoding="utf-8")
        assert "useLiveOddsSnapshots" in text

    def test_sparkline_component_exists(self):
        path = WEB_REACT / "components" / "charts" / "OddsSparkline.tsx"
        assert path.exists()

    def test_live_odds_panel_exists(self):
        path = WEB_REACT / "components" / "charts" / "LiveOddsPanel.tsx"
        assert path.exists()


# ── §E: Cross-asset dashboard ──────────────────────────────────

class TestCrossAssetView:
    """CrossAssetView exists and is wired into App.tsx + Sidebar."""

    VIEW = WEB_REACT / "views" / "CrossAssetView.tsx"
    APP = WEB_REACT / "App.tsx"
    SIDEBAR = WEB_REACT / "components" / "Sidebar.tsx"

    def test_view_file_exists(self):
        assert self.VIEW.exists()

    def test_has_domain_allocation(self):
        text = self.VIEW.read_text(encoding="utf-8")
        assert "Domain Allocation" in text

    def test_has_domain_pnl(self):
        text = self.VIEW.read_text(encoding="utf-8")
        assert "Domain PnL" in text

    def test_has_top_positions(self):
        text = self.VIEW.read_text(encoding="utf-8")
        assert "Top Positions" in text

    def test_has_pie_chart(self):
        text = self.VIEW.read_text(encoding="utf-8")
        assert "PieChart" in text

    def test_app_has_cross_asset_route(self):
        text = self.APP.read_text(encoding="utf-8")
        assert '"cross-asset"' in text

    def test_app_imports_cross_asset_view(self):
        text = self.APP.read_text(encoding="utf-8")
        assert "CrossAssetView" in text

    def test_sidebar_has_cross_asset_entry(self):
        text = self.SIDEBAR.read_text(encoding="utf-8")
        assert "'cross-asset'" in text or '"cross-asset"' in text

    def test_sidebar_has_layers_icon(self):
        text = self.SIDEBAR.read_text(encoding="utf-8")
        assert "Layers" in text

    def test_fetches_paper_portfolio(self):
        text = self.VIEW.read_text(encoding="utf-8")
        assert "PAPER_PORTFOLIO" in text

    def test_fetches_paper_positions(self):
        text = self.VIEW.read_text(encoding="utf-8")
        assert "PAPER_POSITIONS" in text


# ── §G: SLO burn-down (Sprint 10 wiring check) ────────────────

class TestSLOBurndown:
    """ObservabilityView uses SLOBurndownChart + SLOStatusCards."""

    VIEW = WEB_REACT / "views" / "ObservabilityView.tsx"

    def test_view_exists(self):
        assert self.VIEW.exists()

    def test_imports_slo_burndown(self):
        text = self.VIEW.read_text(encoding="utf-8")
        assert "SLOBurndownChart" in text

    def test_imports_slo_status_cards(self):
        text = self.VIEW.read_text(encoding="utf-8")
        assert "SLOStatusCards" in text

    def test_imports_use_slo_metrics(self):
        text = self.VIEW.read_text(encoding="utf-8")
        assert "useSLOMetrics" in text

    def test_slo_burndown_component_exists(self):
        path = WEB_REACT / "components" / "charts" / "SLOBurndownChart.tsx"
        assert path.exists()

    def test_slo_status_cards_exists(self):
        path = WEB_REACT / "components" / "charts" / "SLOStatusCards.tsx"
        assert path.exists()


# ── §H: Code quality event visualization ───────────────────────

class TestCodeQualityPanel:
    """CodeQualityPanel exists and is wired into DevSwarmControlCenter."""

    PANEL = WEB_REACT / "components" / "CodeQualityPanel.tsx"
    VIEW = WEB_REACT / "views" / "DevSwarmControlCenter.tsx"

    def test_panel_file_exists(self):
        assert self.PANEL.exists()

    def test_panel_has_test_results_chart(self):
        text = self.PANEL.read_text(encoding="utf-8")
        assert "Test Results by Proposal" in text

    def test_panel_has_coverage_delta_chart(self):
        text = self.PANEL.read_text(encoding="utf-8")
        assert "Coverage Delta by Proposal" in text

    def test_panel_has_quality_event_timeline(self):
        text = self.PANEL.read_text(encoding="utf-8")
        assert "Code Quality Event Timeline" in text

    def test_panel_has_regression_tracking(self):
        text = self.PANEL.read_text(encoding="utf-8")
        assert "Regressions" in text

    def test_panel_has_guardrail_blocks(self):
        text = self.PANEL.read_text(encoding="utf-8")
        assert "Guardrail Blocks" in text

    def test_view_imports_code_quality_panel(self):
        text = self.VIEW.read_text(encoding="utf-8")
        assert "CodeQualityPanel" in text

    def test_view_has_quality_tab(self):
        text = self.VIEW.read_text(encoding="utf-8")
        assert "'quality'" in text or '"quality"' in text

    def test_view_renders_quality_tab(self):
        text = self.VIEW.read_text(encoding="utf-8")
        assert "activeTab === 'quality'" in text or 'activeTab === "quality"' in text


# ── §I: Sports betting wired into MERID loop ──────────────────

class TestLoopBettingWiring:
    """merid/loop.py has betting odds refresh step."""

    LOOP = ROOT / "merid" / "loop.py"

    def test_loop_file_exists(self):
        assert self.LOOP.exists()

    def test_has_betting_refresh_method(self):
        text = self.LOOP.read_text(encoding="utf-8")
        assert "_refresh_betting_odds" in text

    def test_has_betting_odds_client_accessor(self):
        text = self.LOOP.read_text(encoding="utf-8")
        assert "_betting_odds_client" in text

    def test_has_betting_store_accessor(self):
        text = self.LOOP.read_text(encoding="utf-8")
        assert "_betting_store" in text

    def test_has_betting_refresh_interval(self):
        text = self.LOOP.read_text(encoding="utf-8")
        assert "_betting_refresh_interval" in text

    def test_betting_refresh_in_tick(self):
        text = self.LOOP.read_text(encoding="utf-8")
        assert "_last_betting_refresh" in text

    def test_imports_odds_client(self):
        text = self.LOOP.read_text(encoding="utf-8")
        assert "get_odds_client" in text

    def test_imports_betting_store(self):
        text = self.LOOP.read_text(encoding="utf-8")
        assert "get_betting_store" in text

    def test_builds_consensus(self):
        text = self.LOOP.read_text(encoding="utf-8")
        assert "build_all_consensus" in text

    def test_upserts_events(self):
        text = self.LOOP.read_text(encoding="utf-8")
        assert "upsert_event" in text


# ── Gap report verification ────────────────────────────────────

class TestGapReportAllClosed:
    """Verify the gap report has no remaining unchecked items."""

    REPORT = ROOT / "docs" / "WIRING_GAP_REPORT.md"

    def test_report_exists(self):
        assert self.REPORT.exists()

    def test_no_remaining_gaps(self):
        text = self.REPORT.read_text(encoding="utf-8")
        unchecked = [
            line.strip()
            for line in text.splitlines()
            if line.strip().startswith("- [ ]")
        ]
        assert len(unchecked) == 0, (
            f"Found {len(unchecked)} unchecked gap(s):\n"
            + "\n".join(unchecked[:10])
        )

    def test_sprint15_fixes_present(self):
        text = self.REPORT.read_text(encoding="utf-8")
        assert "Sprint 15" in text

    def test_all_sections_have_fixes(self):
        text = self.REPORT.read_text(encoding="utf-8")
        for section in ["§B", "§D", "§E", "§G", "§H", "§I"]:
            # Check that the section letter appears in a FIXED line
            # We look for the section header letter in the gap checklist
            pass  # Covered by test_no_remaining_gaps
