"""
Sprint 12 — Cognitive Layer UI tests.

Validates:
  1. Endpoint constants (COGNITIVE_SNAPSHOT, COGNITIVE_HEALTH, etc.)
  2. useCognitive hook types and data flow
  3. useRealityDebug + useCognitiveActions hook types
  4. RealityDebugPanel component structure
  5. RegimeTagCloud component structure
  6. HypothesisTimeline component structure
  7. CognitiveView assembly and integration
  8. Navigation wiring (App.tsx + Sidebar.tsx)
  9. Backend API endpoint availability
  10. Cross-file consistency
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# ── Paths ──────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parent.parent
REACT_SRC = ROOT / "web" / "react" / "src"
CONSTANTS_FILE = REACT_SRC / "config" / "constants.ts"
COGNITIVE_HOOK_FILE = REACT_SRC / "hooks" / "useCognitive.ts"
REALITY_DEBUG_HOOK_FILE = REACT_SRC / "hooks" / "useRealityDebug.ts"
REALITY_DEBUG_PANEL_FILE = REACT_SRC / "components" / "charts" / "RealityDebugPanel.tsx"
REGIME_TAG_CLOUD_FILE = REACT_SRC / "components" / "charts" / "RegimeTagCloud.tsx"
HYPOTHESIS_TIMELINE_FILE = REACT_SRC / "components" / "charts" / "HypothesisTimeline.tsx"
VIEW_FILE = REACT_SRC / "views" / "CognitiveView.tsx"
APP_FILE = REACT_SRC / "App.tsx"
SIDEBAR_FILE = REACT_SRC / "components" / "Sidebar.tsx"
COGNITIVE_API_FILE = ROOT / "web" / "api" / "cognitive_api.py"
REALITY_DEBUGGER_FILE = ROOT / "merid" / "cognitive" / "reality_debugger.py"
COGNITIVE_MODELS_FILE = ROOT / "merid" / "cognitive" / "models.py"
COGNITIVE_STORE_FILE = ROOT / "merid" / "cognitive" / "store.py"


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


# ═══════════════════════════════════════════════════════════════════
# §1  Endpoint Constants
# ═══════════════════════════════════════════════════════════════════


class TestEndpointConstants:
    """Verify all cognitive layer constants are defined."""

    src = _read(CONSTANTS_FILE)

    def test_cognitive_snapshot_constant(self):
        assert "COGNITIVE_SNAPSHOT" in self.src
        assert "/api/v1/cognitive/snapshot" in self.src

    def test_cognitive_hypotheses_constant(self):
        assert "COGNITIVE_HYPOTHESES" in self.src
        assert "/api/v1/cognitive/hypotheses" in self.src

    def test_cognitive_metrics_constant(self):
        assert "COGNITIVE_METRICS" in self.src
        assert "/api/v1/cognitive/metrics" in self.src

    def test_cognitive_stuck_constant(self):
        assert "COGNITIVE_STUCK" in self.src
        assert "/api/v1/cognitive/stuck-models" in self.src

    def test_cognitive_health_constant(self):
        assert "COGNITIVE_HEALTH" in self.src
        assert "/api/v1/cognitive/health" in self.src

    def test_cognitive_reality_debug_constant(self):
        assert "COGNITIVE_REALITY_DEBUG" in self.src
        assert "/api/v1/cognitive/reality-debug" in self.src

    def test_cognitive_actions_constant(self):
        assert "COGNITIVE_ACTIONS" in self.src
        assert "/api/v1/cognitive/actions" in self.src

    def test_cognitive_section_comment(self):
        assert "// Cognitive" in self.src

    def test_no_duplicate_cognitive_keys(self):
        matches = re.findall(r"COGNITIVE_SNAPSHOT:", self.src)
        assert len(matches) == 1, "COGNITIVE_SNAPSHOT defined more than once"
        matches = re.findall(r"COGNITIVE_HEALTH:", self.src)
        assert len(matches) == 1, "COGNITIVE_HEALTH defined more than once"
        matches = re.findall(r"COGNITIVE_REALITY_DEBUG:", self.src)
        assert len(matches) == 1, "COGNITIVE_REALITY_DEBUG defined more than once"


# ═══════════════════════════════════════════════════════════════════
# §2  useCognitive Hook
# ═══════════════════════════════════════════════════════════════════


class TestUseCognitiveHook:
    """Verify useCognitive hook structure, types, and exports."""

    src = _read(COGNITIVE_HOOK_FILE)

    def test_file_exists(self):
        assert COGNITIVE_HOOK_FILE.exists()

    def test_exports_useCognitive(self):
        assert "export function useCognitive" in self.src

    def test_hypothesis_interface(self):
        assert "export interface Hypothesis" in self.src

    def test_cognitive_metrics_interface(self):
        assert "export interface CognitiveMetrics" in self.src

    def test_cognitive_snapshot_interface(self):
        assert "export interface CognitiveSnapshot" in self.src

    def test_evidence_link_interface(self):
        assert "export interface EvidenceLink" in self.src

    def test_regime_tag_interface(self):
        assert "export interface RegimeTag" in self.src

    # ── Hypothesis fields ──

    def test_hypothesis_has_id(self):
        assert "id: string" in self.src

    def test_hypothesis_has_domain(self):
        assert "domain: string" in self.src

    def test_hypothesis_has_statement(self):
        assert "statement: string" in self.src

    def test_hypothesis_has_confidence(self):
        assert "confidence: number" in self.src

    def test_hypothesis_has_evidence_count(self):
        assert "evidence_count: number" in self.src

    def test_hypothesis_has_status(self):
        assert "status:" in self.src
        assert "'active'" in self.src
        assert "'confirmed'" in self.src
        assert "'refuted'" in self.src
        assert "'stale'" in self.src

    def test_hypothesis_has_flip_count(self):
        assert "flip_count: number" in self.src

    def test_hypothesis_has_regime_tag(self):
        assert "regime_tag: RegimeTag" in self.src

    def test_hypothesis_has_evidence_links(self):
        assert "evidence_links: EvidenceLink[]" in self.src

    def test_hypothesis_has_owner(self):
        assert "owner: string" in self.src

    def test_hypothesis_has_prior_confidence(self):
        assert "prior_confidence: number | null" in self.src

    def test_hypothesis_has_broken_at(self):
        assert "broken_at: number | null" in self.src

    def test_hypothesis_has_broken_reason(self):
        assert "broken_reason: string" in self.src

    # ── EvidenceLink fields ──

    def test_evidence_link_has_evidence_type(self):
        assert "evidence_type: string" in self.src

    def test_evidence_link_has_supports(self):
        assert "supports: boolean" in self.src

    def test_evidence_link_has_strength(self):
        assert "strength: number" in self.src

    def test_evidence_link_has_title(self):
        assert "title: string" in self.src

    def test_evidence_link_has_url(self):
        assert "url: string" in self.src

    def test_evidence_link_has_added_by(self):
        assert "added_by: string" in self.src

    # ── RegimeTag fields ──

    def test_regime_tag_has_category(self):
        assert "category: string" in self.src

    def test_regime_tag_has_label(self):
        assert "label: string" in self.src

    def test_regime_tag_has_description(self):
        assert "description: string" in self.src

    # ── Hook mechanics ──

    def test_imports_api_endpoints(self):
        assert "API_ENDPOINTS" in self.src

    def test_fetches_cognitive_snapshot(self):
        assert "COGNITIVE_SNAPSHOT" in self.src

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
# §3  useRealityDebug + useCognitiveActions Hooks
# ═══════════════════════════════════════════════════════════════════


class TestUseRealityDebugHook:
    """Verify useRealityDebug hook structure, types, and exports."""

    src = _read(REALITY_DEBUG_HOOK_FILE)

    def test_file_exists(self):
        assert REALITY_DEBUG_HOOK_FILE.exists()

    def test_exports_useRealityDebug(self):
        assert "export function useRealityDebug" in self.src

    def test_exports_useCognitiveActions(self):
        assert "export function useCognitiveActions" in self.src

    # ── Type exports ──

    def test_stuck_model_interface(self):
        assert "export interface StuckModel" in self.src

    def test_conceptual_disagreement_interface(self):
        assert "export interface ConceptualDisagreement" in self.src

    def test_hypothesis_dynamics_interface(self):
        assert "export interface HypothesisDynamics" in self.src

    def test_reality_debug_report_interface(self):
        assert "export interface RealityDebugReport" in self.src

    def test_cognitive_health_interface(self):
        assert "export interface CognitiveHealth" in self.src

    def test_cognitive_action_interface(self):
        assert "export interface CognitiveAction" in self.src

    # ── StuckModel fields ──

    def test_stuck_model_has_market_id(self):
        assert "market_id: string" in self.src

    def test_stuck_model_has_brier_score(self):
        assert "brier_score: number" in self.src

    def test_stuck_model_has_lag_seconds(self):
        assert "lag_seconds: number" in self.src

    def test_stuck_model_has_stale_hypotheses(self):
        assert "stale_hypotheses: number" in self.src

    def test_stuck_model_has_owners(self):
        assert "owners: string[]" in self.src

    def test_stuck_model_has_suggestion(self):
        assert "suggestion: string" in self.src

    # ── ConceptualDisagreement fields ──

    def test_disagreement_has_agents(self):
        assert "agents:" in self.src

    def test_disagreement_has_probability_spread(self):
        assert "probability_spread: number" in self.src

    def test_disagreement_has_regime_tags(self):
        assert "regime_tags_a: string[]" in self.src
        assert "regime_tags_b: string[]" in self.src

    # ── HypothesisDynamics fields ──

    def test_dynamics_has_flips(self):
        assert "flips: number" in self.src

    def test_dynamics_has_flip_rate_per_day(self):
        assert "flip_rate_per_day: number" in self.src

    def test_dynamics_has_rigidity_flag(self):
        assert "rigidity_flag: boolean" in self.src

    def test_dynamics_has_flailing_flag(self):
        assert "flailing_flag: boolean" in self.src

    def test_dynamics_has_total_actions(self):
        assert "total_actions: number" in self.src

    def test_dynamics_has_breakages(self):
        assert "breakages: number" in self.src

    # ── RealityDebugReport fields ──

    def test_report_has_stuck_models(self):
        assert "stuck_models: StuckModel[]" in self.src

    def test_report_has_conceptual_disagreements(self):
        assert "conceptual_disagreements: ConceptualDisagreement[]" in self.src

    def test_report_has_hypothesis_dynamics(self):
        assert "hypothesis_dynamics:" in self.src

    def test_report_has_stuck_count(self):
        assert "stuck_count: number" in self.src

    def test_report_has_disagreement_count(self):
        assert "disagreement_count: number" in self.src

    # ── CognitiveHealth fields ──

    def test_health_has_active_hypotheses(self):
        assert "active_hypotheses: number" in self.src

    def test_health_has_broken_hypotheses(self):
        assert "broken_hypotheses: number" in self.src

    def test_health_has_markets_covered(self):
        assert "markets_covered: number" in self.src

    def test_health_has_unique_owners(self):
        assert "unique_owners: number" in self.src

    def test_health_has_rigidity_count(self):
        assert "rigidity_count: number" in self.src

    def test_health_has_flailing_count(self):
        assert "flailing_count: number" in self.src

    # ── CognitiveAction fields ──

    def test_action_has_id(self):
        assert "id: string" in self.src

    def test_action_has_hypothesis_id(self):
        assert "hypothesis_id: string" in self.src

    def test_action_has_action_field(self):
        assert "action: string" in self.src

    def test_action_has_actor(self):
        assert "actor: string" in self.src

    def test_action_has_detail(self):
        assert "detail: string" in self.src

    def test_action_has_old_confidence(self):
        assert "old_confidence: number | null" in self.src

    def test_action_has_new_confidence(self):
        assert "new_confidence: number | null" in self.src

    def test_action_has_created_at(self):
        assert "created_at: number" in self.src

    # ── Hook mechanics ──

    def test_fetches_reality_debug_endpoint(self):
        assert "COGNITIVE_REALITY_DEBUG" in self.src

    def test_fetches_health_endpoint(self):
        assert "COGNITIVE_HEALTH" in self.src

    def test_fetches_actions_endpoint(self):
        assert "COGNITIVE_ACTIONS" in self.src

    def test_parallel_fetch_in_debug_hook(self):
        assert "Promise.all" in self.src

    def test_returns_report(self):
        assert "setReport" in self.src

    def test_returns_health(self):
        assert "setHealth" in self.src

    def test_returns_actions(self):
        assert "setActions" in self.src

    def test_poll_interval_parameter(self):
        assert "pollMs" in self.src

    def test_uses_useEffect_for_polling(self):
        assert "useEffect" in self.src
        assert "setInterval" in self.src

    def test_clears_interval_on_cleanup(self):
        assert "clearInterval" in self.src


# ═══════════════════════════════════════════════════════════════════
# §4  RealityDebugPanel Component
# ═══════════════════════════════════════════════════════════════════


class TestRealityDebugPanel:
    """Verify reality debug panel component structure."""

    src = _read(REALITY_DEBUG_PANEL_FILE)

    def test_file_exists(self):
        assert REALITY_DEBUG_PANEL_FILE.exists()

    def test_default_export(self):
        assert "export default function RealityDebugPanel" in self.src

    def test_accepts_report_prop(self):
        assert "report" in self.src

    def test_stuck_models_section(self):
        assert "Stuck Models" in self.src

    def test_conceptual_disagreements_section(self):
        assert "Conceptual Disagreements" in self.src

    def test_hypothesis_dynamics_section(self):
        assert "Hypothesis Dynamics" in self.src

    def test_stuck_model_card(self):
        assert "function StuckModelCard" in self.src

    def test_disagreement_card(self):
        assert "function DisagreementCard" in self.src

    def test_dynamics_card(self):
        assert "function DynamicsCard" in self.src

    def test_brier_score_display(self):
        assert "brier_score" in self.src or "brierScore" in self.src

    def test_lag_seconds_display(self):
        assert "lag_seconds" in self.src or "lagSeconds" in self.src

    def test_stale_hypotheses_display(self):
        assert "stale_hypotheses" in self.src or "staleHypotheses" in self.src

    def test_suggestion_display(self):
        assert "suggestion" in self.src

    def test_probability_spread_display(self):
        assert "probability_spread" in self.src or "probabilitySpread" in self.src

    def test_flip_rate_display(self):
        assert "flip_rate" in self.src or "flipRate" in self.src

    def test_rigidity_flag_display(self):
        assert "rigidity" in self.src

    def test_flailing_flag_display(self):
        assert "flailing" in self.src

    def test_collapsible_sections(self):
        assert "ChevronDown" in self.src
        assert "ChevronRight" in self.src

    def test_empty_state(self):
        assert "Reality debug data not available" in self.src

    def test_imports_hook_types(self):
        assert "../../hooks/useRealityDebug" in self.src

    def test_imports_lucide_icons(self):
        assert "from 'lucide-react'" in self.src

    def test_time_formatting(self):
        assert "timeAgo" in self.src or "formatTime" in self.src or "toFixed" in self.src

    def test_owners_display(self):
        assert "owners" in self.src


# ═══════════════════════════════════════════════════════════════════
# §5  RegimeTagCloud Component
# ═══════════════════════════════════════════════════════════════════


class TestRegimeTagCloud:
    """Verify regime tag cloud component structure."""

    src = _read(REGIME_TAG_CLOUD_FILE)

    def test_file_exists(self):
        assert REGIME_TAG_CLOUD_FILE.exists()

    def test_default_export(self):
        assert "export default function RegimeTagCloud" in self.src

    def test_regime_tag_entry_interface(self):
        assert "export interface RegimeTagEntry" in self.src

    def test_accepts_tags_prop(self):
        assert "tags" in self.src

    def test_category_styles_defined(self):
        assert "CATEGORY_STYLES" in self.src

    def test_macro_regime_category(self):
        assert "macro/regime" in self.src

    def test_policy_category(self):
        assert "policy" in self.src

    def test_micro_idiosyncratic_category(self):
        assert "micro/idiosyncratic" in self.src

    def test_crypto_narrative_category(self):
        assert "crypto/narrative" in self.src

    def test_infra_incident_category(self):
        assert "infra/incident" in self.src

    def test_confidence_mini_bar(self):
        assert "ConfidenceMini" in self.src

    def test_tag_pill_component(self):
        assert "TagPill" in self.src

    def test_groups_by_category(self):
        assert "grouped" in self.src

    def test_sorts_by_confidence(self):
        assert "confidence" in self.src
        assert "sort" in self.src

    def test_count_badge(self):
        assert "count" in self.src

    def test_broken_tag_styling(self):
        assert "broken" in self.src
        assert "line-through" in self.src

    def test_empty_state(self):
        assert "No regime tags available" in self.src

    def test_imports_lucide_icons(self):
        assert "Tag" in self.src
        assert "Layers" in self.src

    def test_tag_entry_has_category_field(self):
        assert "category: string" in self.src

    def test_tag_entry_has_label_field(self):
        assert "label: string" in self.src

    def test_tag_entry_has_confidence_field(self):
        assert "confidence: number" in self.src

    def test_tag_entry_has_count_field(self):
        assert "count: number" in self.src

    def test_tag_entry_has_status_field(self):
        assert "status: string" in self.src


# ═══════════════════════════════════════════════════════════════════
# §6  HypothesisTimeline Component
# ═══════════════════════════════════════════════════════════════════


class TestHypothesisTimeline:
    """Verify hypothesis timeline component structure."""

    src = _read(HYPOTHESIS_TIMELINE_FILE)

    def test_file_exists(self):
        assert HYPOTHESIS_TIMELINE_FILE.exists()

    def test_default_export(self):
        assert "export default function HypothesisTimeline" in self.src

    def test_accepts_actions_prop(self):
        assert "actions" in self.src

    def test_accepts_max_visible_prop(self):
        assert "maxVisible" in self.src

    def test_action_meta_mapping(self):
        assert "ACTION_META" in self.src

    def test_created_action_type(self):
        assert "created" in self.src

    def test_broken_action_type(self):
        assert "broken" in self.src

    def test_retired_action_type(self):
        assert "retired" in self.src

    def test_confidence_adjusted_action_type(self):
        assert "confidence_adjusted" in self.src

    def test_evidence_added_action_type(self):
        assert "evidence_added" in self.src

    def test_regime_tag_changed_action_type(self):
        assert "regime_tag_changed" in self.src

    def test_confidence_delta_component(self):
        assert "ConfidenceDelta" in self.src

    def test_timeline_entry_component(self):
        assert "TimelineEntry" in self.src

    def test_vertical_line_connector(self):
        assert "bg-slate-700" in self.src

    def test_time_ago_helper(self):
        assert "timeAgo" in self.src

    def test_show_more_button(self):
        assert "showAll" in self.src
        assert "Show" in self.src

    def test_collapse_button(self):
        assert "Collapse" in self.src

    def test_sorts_newest_first(self):
        assert "sort" in self.src
        assert "created_at" in self.src

    def test_empty_state(self):
        assert "No cognitive actions recorded" in self.src

    def test_imports_hook_types(self):
        assert "../../hooks/useRealityDebug" in self.src

    def test_imports_lucide_icons(self):
        for icon in ["Plus", "XCircle", "Archive", "TrendingUp", "TrendingDown", "FileText"]:
            assert icon in self.src

    def test_actor_display(self):
        assert "actor" in self.src
        assert "User" in self.src

    def test_market_id_display(self):
        assert "market_id" in self.src

    def test_detail_display(self):
        assert "detail" in self.src


# ═══════════════════════════════════════════════════════════════════
# §7  CognitiveView Assembly
# ═══════════════════════════════════════════════════════════════════


class TestCognitiveView:
    """Verify the main view assembles all components correctly."""

    src = _read(VIEW_FILE)

    def test_file_exists(self):
        assert VIEW_FILE.exists()

    def test_default_export(self):
        assert "export default function CognitiveView" in self.src

    # ── Imports ──

    def test_imports_useCognitive(self):
        assert "useCognitive" in self.src

    def test_imports_useRealityDebug(self):
        assert "useRealityDebug" in self.src

    def test_imports_useCognitiveActions(self):
        assert "useCognitiveActions" in self.src

    def test_imports_reality_debug_panel(self):
        assert "RealityDebugPanel" in self.src

    def test_imports_regime_tag_cloud(self):
        assert "RegimeTagCloud" in self.src

    def test_imports_hypothesis_timeline(self):
        assert "HypothesisTimeline" in self.src

    def test_imports_evidence_link_type(self):
        assert "EvidenceLink" in self.src

    def test_imports_regime_tag_entry_type(self):
        assert "RegimeTagEntry" in self.src

    # ── Health badge ──

    def test_health_config(self):
        assert "HEALTH_CONFIG" in self.src

    def test_healthy_status(self):
        assert "healthy" in self.src
        assert "emerald" in self.src

    def test_degraded_status(self):
        assert "degraded" in self.src
        assert "amber" in self.src

    def test_unhealthy_status(self):
        assert "unhealthy" in self.src
        assert "rose" in self.src

    # ── Status colors ──

    def test_status_colors_active(self):
        assert "active:" in self.src

    def test_status_colors_confirmed(self):
        assert "confirmed:" in self.src

    def test_status_colors_broken(self):
        assert "broken:" in self.src

    def test_status_colors_retired(self):
        assert "retired:" in self.src

    # ── Metric tiles ──

    def test_total_hypotheses_tile(self):
        assert "Total Hypotheses" in self.src

    def test_active_tile(self):
        assert "Active" in self.src

    def test_flip_rate_tile(self):
        assert "Flip Rate" in self.src

    def test_stuck_models_tile(self):
        assert "Stuck Models" in self.src

    # ── Evidence drawer ──

    def test_evidence_drawer_component(self):
        assert "EvidenceDrawer" in self.src

    def test_evidence_row_component(self):
        assert "EvidenceRow" in self.src

    def test_supporting_evidence_label(self):
        assert "Supporting" in self.src

    def test_contradicting_evidence_label(self):
        assert "Contradicting" in self.src

    def test_evidence_strength_bar(self):
        assert "strengthPct" in self.src

    def test_evidence_external_link(self):
        assert "ExternalLink" in self.src

    def test_evidence_type_badge(self):
        assert "evidence_type" in self.src

    # ── Hypothesis card enhancements ──

    def test_hypothesis_card_component(self):
        assert "function HypothesisCard" in self.src

    def test_confidence_bar_with_prior(self):
        assert "prior" in self.src

    def test_confidence_delta_display(self):
        assert "delta" in self.src

    def test_regime_tag_in_card(self):
        assert "regime_tag" in self.src

    def test_owner_display_in_card(self):
        assert "owner" in self.src

    def test_broken_reason_display(self):
        assert "broken_reason" in self.src

    # ── Collapsible sections ──

    def test_collapsible_section_component(self):
        assert "CollapsibleSection" in self.src

    def test_reality_debugger_section(self):
        assert "Reality Debugger" in self.src

    def test_regime_tags_section(self):
        assert "Regime Tags" in self.src

    def test_action_timeline_section(self):
        assert "Action Timeline" in self.src

    # ── Regime tag extraction ──

    def test_regime_tag_extraction_logic(self):
        assert "regimeTags" in self.src
        assert "tagMap" in self.src

    # ── Refresh all ──

    def test_refresh_all_function(self):
        assert "handleRefreshAll" in self.src

    def test_refresh_button(self):
        assert "RefreshCw" in self.src

    # ── Cognitive health from debugger ──

    def test_cog_health_display(self):
        assert "cogHealth" in self.src

    def test_markets_covered_display(self):
        assert "markets_covered" in self.src

    def test_unique_owners_display(self):
        assert "unique_owners" in self.src

    # ── Filter tabs ──

    def test_filter_tabs(self):
        for f in ["all", "active", "confirmed", "refuted", "stale"]:
            assert f"'{f}'" in self.src

    # ── Loading and error states ──

    def test_loading_state(self):
        assert "loading" in self.src
        assert "animate-spin" in self.src

    def test_error_state(self):
        assert "Cognitive API Error" in self.src

    # ── Status distribution ──

    def test_status_distribution_component(self):
        assert "StatusDistribution" in self.src

    # ── Stuck models panel ──

    def test_stuck_models_panel(self):
        assert "Stuck Models" in self.src

    # ── Tooltip component ──

    def test_tip_component(self):
        assert "function Tip" in self.src

    # ── Icons ──

    def test_brain_icon(self):
        assert "Brain" in self.src

    def test_shield_icon(self):
        assert "Shield" in self.src

    def test_layers_icon(self):
        assert "Layers" in self.src

    def test_activity_icon(self):
        assert "Activity" in self.src


# ═══════════════════════════════════════════════════════════════════
# §8  Navigation Wiring
# ═══════════════════════════════════════════════════════════════════


class TestNavigationWiring:
    """Verify App.tsx and Sidebar.tsx are wired correctly."""

    app_src = _read(APP_FILE)
    sidebar_src = _read(SIDEBAR_FILE)

    def test_app_imports_cognitive_view(self):
        assert "import CognitiveView" in self.app_src or "CognitiveView" in self.app_src

    def test_app_view_type_includes_cognitive(self):
        assert '"cognitive"' in self.app_src

    def test_app_renders_cognitive_view(self):
        assert "cognitive" in self.app_src
        assert "<CognitiveView" in self.app_src

    def test_sidebar_nav_entry(self):
        assert "Cognitive" in self.sidebar_src

    def test_sidebar_nav_href(self):
        assert "'cognitive'" in self.sidebar_src

    def test_sidebar_brain_icon(self):
        assert "Brain" in self.sidebar_src


# ═══════════════════════════════════════════════════════════════════
# §9  Backend API Endpoints
# ═══════════════════════════════════════════════════════════════════


class TestBackendAPIs:
    """Verify backend API files expose the expected endpoints."""

    api_src = _read(COGNITIVE_API_FILE)
    debugger_src = _read(REALITY_DEBUGGER_FILE)
    models_src = _read(COGNITIVE_MODELS_FILE)
    store_src = _read(COGNITIVE_STORE_FILE)

    # ── cognitive_api.py ──

    def test_snapshot_endpoint(self):
        assert "/snapshot" in self.api_src

    def test_hypotheses_endpoint(self):
        assert "/hypotheses" in self.api_src

    def test_reality_debug_endpoint(self):
        assert "/reality-debug" in self.api_src

    def test_health_endpoint(self):
        assert "/health" in self.api_src

    def test_actions_endpoint(self):
        assert "/actions" in self.api_src

    def test_create_snapshot_handler(self):
        assert "create_snapshot" in self.api_src

    def test_reality_debug_handler(self):
        assert "reality_debug" in self.api_src

    def test_cognitive_health_handler(self):
        assert "cognitive_health" in self.api_src

    def test_evidence_endpoint(self):
        assert "evidence" in self.api_src

    def test_confidence_update_endpoint(self):
        assert "confidence" in self.api_src

    # ── reality_debugger.py ──

    def test_reality_debugger_class(self):
        assert "class RealityDebugger" in self.debugger_src

    def test_detect_stuck_models_method(self):
        assert "def detect_stuck_models" in self.debugger_src

    def test_detect_conceptual_disagreements_method(self):
        assert "def detect_conceptual_disagreements" in self.debugger_src

    def test_compute_hypothesis_dynamics_method(self):
        assert "def compute_hypothesis_dynamics" in self.debugger_src

    def test_reality_debug_method(self):
        assert "def reality_debug" in self.debugger_src

    def test_get_cognitive_health_method(self):
        assert "def get_cognitive_health" in self.debugger_src

    def test_stuck_model_dataclass(self):
        assert "class StuckModel" in self.debugger_src

    def test_conceptual_disagreement_dataclass(self):
        assert "class ConceptualDisagreement" in self.debugger_src

    def test_hypothesis_dynamics_dataclass(self):
        assert "class HypothesisDynamics" in self.debugger_src

    # ── models.py ──

    def test_hypothesis_model(self):
        assert "class Hypothesis" in self.models_src

    def test_evidence_link_model(self):
        assert "class EvidenceLink" in self.models_src or "EvidenceLink" in self.models_src

    def test_regime_tag_model(self):
        assert "class RegimeTag" in self.models_src or "RegimeTag" in self.models_src

    def test_cognitive_snapshot_model(self):
        assert "class CognitiveSnapshot" in self.models_src

    # ── store.py ──

    def test_cognitive_store_class(self):
        assert "class CognitiveStore" in self.store_src

    def test_save_snapshot_method(self):
        assert "def save_snapshot" in self.store_src

    def test_get_actions_method(self):
        assert "get_actions" in self.store_src or "actions" in self.store_src

    def test_sqlite_persistence(self):
        assert "sqlite" in self.store_src.lower()


# ═══════════════════════════════════════════════════════════════════
# §10  Integration — Cross-file Consistency
# ═══════════════════════════════════════════════════════════════════


class TestIntegration:
    """Cross-file consistency checks."""

    constants_src = _read(CONSTANTS_FILE)
    cognitive_hook_src = _read(COGNITIVE_HOOK_FILE)
    debug_hook_src = _read(REALITY_DEBUG_HOOK_FILE)
    view_src = _read(VIEW_FILE)
    reality_panel_src = _read(REALITY_DEBUG_PANEL_FILE)
    regime_cloud_src = _read(REGIME_TAG_CLOUD_FILE)
    timeline_src = _read(HYPOTHESIS_TIMELINE_FILE)

    def test_cognitive_hook_uses_constants(self):
        assert "API_ENDPOINTS" in self.cognitive_hook_src
        assert "../config/constants" in self.cognitive_hook_src

    def test_debug_hook_uses_constants(self):
        assert "API_ENDPOINTS" in self.debug_hook_src
        assert "../config/constants" in self.debug_hook_src

    def test_view_imports_cognitive_hook(self):
        assert "../hooks/useCognitive" in self.view_src

    def test_view_imports_debug_hook(self):
        assert "../hooks/useRealityDebug" in self.view_src

    def test_view_imports_reality_panel(self):
        assert "../components/charts/RealityDebugPanel" in self.view_src

    def test_view_imports_regime_cloud(self):
        assert "../components/charts/RegimeTagCloud" in self.view_src

    def test_view_imports_timeline(self):
        assert "../components/charts/HypothesisTimeline" in self.view_src

    def test_reality_panel_imports_hook_types(self):
        assert "../../hooks/useRealityDebug" in self.reality_panel_src

    def test_timeline_imports_hook_types(self):
        assert "../../hooks/useRealityDebug" in self.timeline_src

    def test_constants_match_backend_routes(self):
        assert "/api/v1/cognitive/snapshot" in self.constants_src
        assert "/api/v1/cognitive/health" in self.constants_src
        assert "/api/v1/cognitive/reality-debug" in self.constants_src
        assert "/api/v1/cognitive/actions" in self.constants_src

    def test_all_new_files_exist(self):
        assert COGNITIVE_HOOK_FILE.exists()
        assert REALITY_DEBUG_HOOK_FILE.exists()
        assert REALITY_DEBUG_PANEL_FILE.exists()
        assert REGIME_TAG_CLOUD_FILE.exists()
        assert HYPOTHESIS_TIMELINE_FILE.exists()
        assert VIEW_FILE.exists()

    def test_hypothesis_type_consistency(self):
        """Hypothesis type in hook matches what view expects."""
        assert "regime_tag" in self.cognitive_hook_src
        assert "evidence_links" in self.cognitive_hook_src
        assert "regime_tag" in self.view_src
        assert "evidence_links" in self.view_src

    def test_evidence_link_type_consistency(self):
        """EvidenceLink type in hook matches what view expects."""
        assert "supports: boolean" in self.cognitive_hook_src
        assert "strength: number" in self.cognitive_hook_src
        assert "supports" in self.view_src
        assert "strength" in self.view_src

    def test_reality_debug_types_consistent(self):
        """Debug hook types match what panel expects."""
        for t in ["StuckModel", "ConceptualDisagreement", "HypothesisDynamics", "RealityDebugReport"]:
            assert t in self.debug_hook_src
            assert t in self.reality_panel_src

    def test_cognitive_action_type_consistent(self):
        """CognitiveAction type in hook matches what timeline expects."""
        assert "CognitiveAction" in self.debug_hook_src
        assert "CognitiveAction" in self.timeline_src

    def test_regime_tag_entry_consistent(self):
        """RegimeTagEntry in cloud matches what view passes."""
        assert "RegimeTagEntry" in self.regime_cloud_src
        assert "RegimeTagEntry" in self.view_src
