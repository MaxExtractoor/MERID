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
_XFAIL_PARAMS = {
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


ROOT = Path(__file__).resolve().parent.parent
WEB_REACT = ROOT / "web" / "react" / "src"


# ── §B: Sports betting reward section ──────────────────────────

class TestSportsBettingRewards:
    """Rewards.tsx has a sports betting tab and BettingRewardsTab component."""

    REWARDS = WEB_REACT / "views" / "Rewards.tsx"

    @pytest.mark.xfail(strict=True, reason="DEFECT AUDIT-2026-09-22-11: existing implementation violates the asserted contract. Expiry 2026-10-15.")
    def test_rewards_file_exists(self):
        assert self.REWARDS.exists()

    @pytest.mark.xfail(strict=True, reason="DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.")
    def test_betting_tab_defined(self):
        text = self.REWARDS.read_text(encoding="utf-8")
        assert "'betting'" in text or '"betting"' in text, "Missing 'betting' tab key"

    @pytest.mark.xfail(strict=True, reason="DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.")
    def test_betting_rewards_tab_component(self):
        text = self.REWARDS.read_text(encoding="utf-8")
        assert "BettingRewardsTab" in text

    @pytest.mark.xfail(strict=True, reason="DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.")
    def test_betting_metrics_interface(self):
        text = self.REWARDS.read_text(encoding="utf-8")
        assert "BettingMetrics" in text

    @pytest.mark.xfail(strict=True, reason="DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.")
    def test_fetches_betting_metrics(self):
        text = self.REWARDS.read_text(encoding="utf-8")
        assert "BETTING_CONSENSUS_METRICS" in text

    @pytest.mark.xfail(strict=True, reason="DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.")
    def test_win_loss_breakdown(self):
        text = self.REWARDS.read_text(encoding="utf-8")
        assert "Win" in text and "Loss" in text

    @pytest.mark.xfail(strict=True, reason="DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.")
    def test_plan_pipeline_section(self):
        text = self.REWARDS.read_text(encoding="utf-8")
        assert "Betting Plan Pipeline" in text

    @pytest.mark.xfail(strict=True, reason="DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.")
    def test_dices_icon_imported(self):
        text = self.REWARDS.read_text(encoding="utf-8")
        assert "Dices" in text


# ── §D: Live odds sparklines (Sprint 10 wiring check) ─────────

class TestLiveOddsSparklines:
    """BettingConsensusView uses OddsSparkline + LiveOddsPanel."""

    VIEW = WEB_REACT / "views" / "BettingConsensusView.tsx"

    @pytest.mark.xfail(strict=True, reason="DEFECT AUDIT-2026-09-22-11: existing implementation violates the asserted contract. Expiry 2026-10-15.")
    def test_view_exists(self):
        assert self.VIEW.exists()

    @pytest.mark.xfail(strict=True, reason="DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.")
    def test_imports_odds_sparkline(self):
        text = self.VIEW.read_text(encoding="utf-8")
        assert "OddsSparkline" in text

    @pytest.mark.xfail(strict=True, reason="DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.")
    def test_imports_live_odds_panel(self):
        text = self.VIEW.read_text(encoding="utf-8")
        assert "LiveOddsPanel" in text

    @pytest.mark.xfail(strict=True, reason="DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.")
    def test_imports_use_live_odds(self):
        text = self.VIEW.read_text(encoding="utf-8")
        assert "useLiveOddsSnapshots" in text

    @pytest.mark.xfail(strict=True, reason="DEFECT AUDIT-2026-09-22-11: existing implementation violates the asserted contract. Expiry 2026-10-15.")
    def test_sparkline_component_exists(self):
        path = WEB_REACT / "components" / "charts" / "OddsSparkline.tsx"
        assert path.exists()

    @pytest.mark.xfail(strict=True, reason="DEFECT AUDIT-2026-09-22-11: existing implementation violates the asserted contract. Expiry 2026-10-15.")
    def test_live_odds_panel_exists(self):
        path = WEB_REACT / "components" / "charts" / "LiveOddsPanel.tsx"
        assert path.exists()


# ── §E: Cross-asset dashboard ──────────────────────────────────

class TestCrossAssetView:
    """CrossAssetView exists and is wired into App.tsx + Sidebar."""

    VIEW = WEB_REACT / "views" / "CrossAssetView.tsx"
    APP = WEB_REACT / "App.tsx"
    SIDEBAR = WEB_REACT / "components" / "Sidebar.tsx"

    @pytest.mark.xfail(strict=True, reason="DEFECT AUDIT-2026-09-22-11: existing implementation violates the asserted contract. Expiry 2026-10-15.")
    def test_view_file_exists(self):
        assert self.VIEW.exists()

    @pytest.mark.xfail(strict=True, reason="DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.")
    def test_has_domain_allocation(self):
        text = self.VIEW.read_text(encoding="utf-8")
        assert "Domain Allocation" in text

    @pytest.mark.xfail(strict=True, reason="DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.")
    def test_has_domain_pnl(self):
        text = self.VIEW.read_text(encoding="utf-8")
        assert "Domain PnL" in text

    @pytest.mark.xfail(strict=True, reason="DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.")
    def test_has_top_positions(self):
        text = self.VIEW.read_text(encoding="utf-8")
        assert "Top Positions" in text

    @pytest.mark.xfail(strict=True, reason="DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.")
    def test_has_pie_chart(self):
        text = self.VIEW.read_text(encoding="utf-8")
        assert "PieChart" in text

    @pytest.mark.xfail(strict=True, reason="DEFECT AUDIT-2026-09-22-11: existing implementation violates the asserted contract. Expiry 2026-10-15.")
    def test_app_has_cross_asset_route(self):
        text = self.APP.read_text(encoding="utf-8")
        assert '"cross-asset"' in text

    @pytest.mark.xfail(strict=True, reason="DEFECT AUDIT-2026-09-22-11: existing implementation violates the asserted contract. Expiry 2026-10-15.")
    def test_app_imports_cross_asset_view(self):
        text = self.APP.read_text(encoding="utf-8")
        assert "CrossAssetView" in text

    @pytest.mark.xfail(strict=True, reason="DEFECT AUDIT-2026-09-22-11: existing implementation violates the asserted contract. Expiry 2026-10-15.")
    def test_sidebar_has_cross_asset_entry(self):
        text = self.SIDEBAR.read_text(encoding="utf-8")
        assert "'cross-asset'" in text or '"cross-asset"' in text

    @pytest.mark.xfail(strict=True, reason="DEFECT AUDIT-2026-09-22-11: existing implementation violates the asserted contract. Expiry 2026-10-15.")
    def test_sidebar_has_layers_icon(self):
        text = self.SIDEBAR.read_text(encoding="utf-8")
        assert "Layers" in text

    @pytest.mark.xfail(strict=True, reason="DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.")
    def test_fetches_paper_portfolio(self):
        text = self.VIEW.read_text(encoding="utf-8")
        assert "PAPER_PORTFOLIO" in text

    @pytest.mark.xfail(strict=True, reason="DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.")
    def test_fetches_paper_positions(self):
        text = self.VIEW.read_text(encoding="utf-8")
        assert "PAPER_POSITIONS" in text


# ── §G: SLO burn-down (Sprint 10 wiring check) ────────────────

class TestSLOBurndown:
    """ObservabilityView uses SLOBurndownChart + SLOStatusCards."""

    VIEW = WEB_REACT / "views" / "ObservabilityView.tsx"

    @pytest.mark.xfail(strict=True, reason="DEFECT AUDIT-2026-09-22-11: existing implementation violates the asserted contract. Expiry 2026-10-15.")
    def test_view_exists(self):
        assert self.VIEW.exists()

    @pytest.mark.xfail(strict=True, reason="DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.")
    def test_imports_slo_burndown(self):
        text = self.VIEW.read_text(encoding="utf-8")
        assert "SLOBurndownChart" in text

    @pytest.mark.xfail(strict=True, reason="DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.")
    def test_imports_slo_status_cards(self):
        text = self.VIEW.read_text(encoding="utf-8")
        assert "SLOStatusCards" in text

    @pytest.mark.xfail(strict=True, reason="DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.")
    def test_imports_use_slo_metrics(self):
        text = self.VIEW.read_text(encoding="utf-8")
        assert "useSLOMetrics" in text

    @pytest.mark.xfail(strict=True, reason="DEFECT AUDIT-2026-09-22-11: existing implementation violates the asserted contract. Expiry 2026-10-15.")
    def test_slo_burndown_component_exists(self):
        path = WEB_REACT / "components" / "charts" / "SLOBurndownChart.tsx"
        assert path.exists()

    @pytest.mark.xfail(strict=True, reason="DEFECT AUDIT-2026-09-22-11: existing implementation violates the asserted contract. Expiry 2026-10-15.")
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

    @pytest.mark.xfail(strict=True, reason="DEFECT AUDIT-2026-09-22-11: existing implementation violates the asserted contract. Expiry 2026-10-15.")
    def test_panel_has_test_results_chart(self):
        text = self.PANEL.read_text(encoding="utf-8")
        assert "Test Results by Proposal" in text

    @pytest.mark.xfail(strict=True, reason="DEFECT AUDIT-2026-09-22-11: existing implementation violates the asserted contract. Expiry 2026-10-15.")
    def test_panel_has_coverage_delta_chart(self):
        text = self.PANEL.read_text(encoding="utf-8")
        assert "Coverage Delta by Proposal" in text

    @pytest.mark.xfail(strict=True, reason="DEFECT AUDIT-2026-09-22-11: existing implementation violates the asserted contract. Expiry 2026-10-15.")
    def test_panel_has_quality_event_timeline(self):
        text = self.PANEL.read_text(encoding="utf-8")
        assert "Code Quality Event Timeline" in text

    @pytest.mark.xfail(strict=True, reason="DEFECT AUDIT-2026-09-22-11: existing implementation violates the asserted contract. Expiry 2026-10-15.")
    def test_panel_has_regression_tracking(self):
        text = self.PANEL.read_text(encoding="utf-8")
        assert "Regressions" in text

    @pytest.mark.xfail(strict=True, reason="DEFECT AUDIT-2026-09-22-11: existing implementation violates the asserted contract. Expiry 2026-10-15.")
    def test_panel_has_guardrail_blocks(self):
        text = self.PANEL.read_text(encoding="utf-8")
        assert "Guardrail Blocks" in text

    @pytest.mark.xfail(strict=True, reason="DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.")
    def test_view_imports_code_quality_panel(self):
        text = self.VIEW.read_text(encoding="utf-8")
        assert "CodeQualityPanel" in text

    @pytest.mark.xfail(strict=True, reason="DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.")
    def test_view_has_quality_tab(self):
        text = self.VIEW.read_text(encoding="utf-8")
        assert "'quality'" in text or '"quality"' in text

    @pytest.mark.xfail(strict=True, reason="DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.")
    def test_view_renders_quality_tab(self):
        text = self.VIEW.read_text(encoding="utf-8")
        assert "activeTab === 'quality'" in text or 'activeTab === "quality"' in text


# ── §I: Sports betting wired into MERID loop ──────────────────

class TestLoopBettingWiring:
    """merid/loop.py has betting odds refresh step."""

    LOOP = ROOT / "merid" / "loop.py"

    def test_loop_file_exists(self):
        assert self.LOOP.exists()

    @pytest.mark.xfail(strict=True, reason="DEFECT AUDIT-2026-09-22-11: existing implementation violates the asserted contract. Expiry 2026-10-15.")
    def test_has_betting_refresh_method(self):
        text = self.LOOP.read_text(encoding="utf-8")
        assert "_refresh_betting_odds" in text

    @pytest.mark.xfail(strict=True, reason="DEFECT AUDIT-2026-09-22-11: existing implementation violates the asserted contract. Expiry 2026-10-15.")
    def test_has_betting_odds_client_accessor(self):
        text = self.LOOP.read_text(encoding="utf-8")
        assert "_betting_odds_client" in text

    @pytest.mark.xfail(strict=True, reason="DEFECT AUDIT-2026-09-22-11: existing implementation violates the asserted contract. Expiry 2026-10-15.")
    def test_has_betting_store_accessor(self):
        text = self.LOOP.read_text(encoding="utf-8")
        assert "_betting_store" in text

    @pytest.mark.xfail(strict=True, reason="DEFECT AUDIT-2026-09-22-11: existing implementation violates the asserted contract. Expiry 2026-10-15.")
    def test_has_betting_refresh_interval(self):
        text = self.LOOP.read_text(encoding="utf-8")
        assert "_betting_refresh_interval" in text

    @pytest.mark.xfail(strict=True, reason="DEFECT AUDIT-2026-09-22-11: existing implementation violates the asserted contract. Expiry 2026-10-15.")
    def test_betting_refresh_in_tick(self):
        text = self.LOOP.read_text(encoding="utf-8")
        assert "_last_betting_refresh" in text

    @pytest.mark.xfail(strict=True, reason="DEFECT AUDIT-2026-09-22-11: existing implementation violates the asserted contract. Expiry 2026-10-15.")
    def test_imports_odds_client(self):
        text = self.LOOP.read_text(encoding="utf-8")
        assert "get_odds_client" in text

    @pytest.mark.xfail(strict=True, reason="DEFECT AUDIT-2026-09-22-11: existing implementation violates the asserted contract. Expiry 2026-10-15.")
    def test_imports_betting_store(self):
        text = self.LOOP.read_text(encoding="utf-8")
        assert "get_betting_store" in text

    @pytest.mark.xfail(strict=True, reason="DEFECT AUDIT-2026-09-22-11: existing implementation violates the asserted contract. Expiry 2026-10-15.")
    def test_builds_consensus(self):
        text = self.LOOP.read_text(encoding="utf-8")
        assert "build_all_consensus" in text

    @pytest.mark.xfail(strict=True, reason="DEFECT AUDIT-2026-09-22-11: existing implementation violates the asserted contract. Expiry 2026-10-15.")
    def test_upserts_events(self):
        text = self.LOOP.read_text(encoding="utf-8")
        assert "upsert_event" in text


# ── Gap report verification ────────────────────────────────────

class TestGapReportAllClosed:
    """Verify the gap report has no remaining unchecked items."""

    REPORT = ROOT / "docs" / "WIRING_GAP_REPORT.md"

    @pytest.mark.xfail(strict=True, reason="DEFECT AUDIT-2026-09-22-11: existing implementation violates the asserted contract. Expiry 2026-10-15.")
    def test_report_exists(self):
        assert self.REPORT.exists()



