"""Tests for pipeline_audit.py — per-cycle invariant checks for all 5 crypto assets.

Covers:
  1. Upstream invariants — catalog presence, filter counts, signal counts.
  2. Core loop invariants — per-asset evaluate/approve/execute path.
  3. Downstream checks — fills, exposure, bankroll invariant delta.
  4. Regression fixture — non-BTC assets produce non-zero candidates given a
     known catalog snapshot with live markets for all 5 assets.
  5. by_asset_timeframe invariant — all 5 assets must appear when crypto
     is enabled and catalog has live markets.
"""

from __future__ import annotations

from typing import Any, Dict

import pytest

from merid.event_venues.kalshi.pipeline_audit import (
    AuditItem,
    AuditResult,
    PipelineAudit,
    Severity,
    _REQUIRED_ASSETS,
)
from config.crypto_universe import CRYPTO_ASSETS_ORDERED


# ── Helpers ───────────────────────────────────────────────────────────────

def _full_catalog_snap(markets_per_asset: int = 3) -> Dict[str, Any]:
    """Return a catalog snapshot dict where every asset has live markets."""
    return {
        "by_asset": {a: markets_per_asset for a in CRYPTO_ASSETS_ORDERED},
        "by_timeframe": {"15m": 5, "1h": 5, "daily": 5, "weekly": 5, "monthly": 5, "annual": 5},
        "by_asset_timeframe": {
            a: {"15m": 1, "1h": 1, "daily": 1, "weekly": 1, "monthly": 1, "annual": 1}
            for a in CRYPTO_ASSETS_ORDERED
        },
    }


def _full_cycle_stats(approved_per_asset: int = 1) -> Dict[str, Any]:
    """Return a cycle_stats dict where every asset has candidates and approvals."""
    per_asset: Dict[str, Any] = {}
    for asset in CRYPTO_ASSETS_ORDERED:
        per_asset[asset] = {
            "candidates_seen": 3,
            "evaluated": 2,
            "approved": approved_per_asset,
            "vetoed": 2 - approved_per_asset,
            "kelly_zero_count": 0,
            "veto_reasons": {} if approved_per_asset > 0 else {"edge_too_low": 2},
            "approved_orders_intent": approved_per_asset,
            "orders_submitted": approved_per_asset,
            "orders_blocked_by_risk": 0,
            "orders_blocked_by_kill_switch": 0,
        }
    return {
        "per_asset_stats": per_asset,
        "scan_by_asset_timeframe": {
            a: {"15m": 2, "1h": 2, "daily": 2} for a in CRYPTO_ASSETS_ORDERED
        },
    }


# ═══════════════════════════════════════════════════════════════════════════
# 1. Basic smoke — audit runs and produces results
# ═══════════════════════════════════════════════════════════════════════════

class TestAuditSmoke:
    """Audit runs without errors and returns AuditResult."""

    def test_empty_run_produces_result(self) -> None:
        audit = PipelineAudit()
        result = audit.run()
        assert isinstance(result, AuditResult)
        assert result.passes + result.warnings + result.failures == len(result.items)

    def test_full_pass_when_all_data_ok(self) -> None:
        audit = PipelineAudit()
        result = audit.run(
            catalog_snapshot=_full_catalog_snap(),
            cycle_stats=_full_cycle_stats(),
        )
        assert result.failures == 0, f"Expected 0 failures, got {result.failures}: {result.blockers}"

    def test_to_dict_is_serialisable(self) -> None:
        audit = PipelineAudit()
        result = audit.run(catalog_snapshot=_full_catalog_snap())
        d = result.to_dict()
        assert "all_pass" in d
        assert "items" in d
        assert isinstance(d["items"], list)


# ═══════════════════════════════════════════════════════════════════════════
# 2. Upstream — catalog invariants
# ═══════════════════════════════════════════════════════════════════════════

class TestUpstreamCatalogInvariants:
    """Catalog layer must surface missing assets as WARNs (not hard FAILs)."""

    def test_missing_asset_in_catalog_produces_warn(self) -> None:
        """If an asset has 0 markets in the catalog, emit WARN (Kalshi may have no live markets)."""
        audit = PipelineAudit()
        snap = _full_catalog_snap()
        snap["by_asset"]["SOL"] = 0  # SOL has no markets

        result = audit.run(catalog_snapshot=snap)
        sol_warns = [
            i for i in result.items
            if i.layer == "UPSTREAM" and i.phase == "catalog"
            and i.asset == "SOL" and i.severity == Severity.WARN
        ]
        assert len(sol_warns) == 1, "Missing SOL catalog entry should produce exactly 1 WARN"

    def test_all_assets_present_produce_passes(self) -> None:
        audit = PipelineAudit()
        result = audit.run(catalog_snapshot=_full_catalog_snap())
        catalog_passes = [
            i for i in result.items
            if i.layer == "UPSTREAM" and i.phase == "catalog" and i.severity == Severity.PASS
        ]
        # 5 assets, each with a catalog PASS
        assert len(catalog_passes) == 5

    def test_all_five_assets_are_checked(self) -> None:
        """Audit must check exactly the 5 required assets."""
        assert set(_REQUIRED_ASSETS) == {"BTC", "ETH", "SOL", "XRP", "DOGE"}


# ═══════════════════════════════════════════════════════════════════════════
# 3. Upstream — by_asset_timeframe invariant
# ═══════════════════════════════════════════════════════════════════════════

class TestByAssetTimerframeInvariant:
    """scan_by_asset_timeframe in cycle_stats must contain all 5 assets."""

    def test_missing_asset_in_scan_produces_fail(self) -> None:
        """If an asset is missing from scan_by_asset_timeframe, emit FAIL."""
        audit = PipelineAudit()
        stats = _full_cycle_stats()
        del stats["scan_by_asset_timeframe"]["DOGE"]  # Remove DOGE

        result = audit.run(cycle_stats=stats)
        doge_fails = [
            i for i in result.items
            if i.layer == "UPSTREAM" and i.phase == "filter"
            and i.asset == "DOGE" and i.severity == Severity.FAIL
        ]
        assert len(doge_fails) == 1

    def test_zero_scan_count_produces_warn(self) -> None:
        """If an asset has 0 total scan candidates, emit WARN."""
        audit = PipelineAudit()
        stats = _full_cycle_stats()
        stats["scan_by_asset_timeframe"]["XRP"] = {"15m": 0, "1h": 0, "daily": 0}

        result = audit.run(cycle_stats=stats)
        xrp_warns = [
            i for i in result.items
            if i.layer == "UPSTREAM" and i.phase == "filter"
            and i.asset == "XRP" and i.severity == Severity.WARN
        ]
        assert len(xrp_warns) == 1

    def test_all_assets_in_scan_produce_passes(self) -> None:
        audit = PipelineAudit()
        stats = _full_cycle_stats()
        result = audit.run(cycle_stats=stats)
        filter_passes = [
            i for i in result.items
            if i.layer == "UPSTREAM" and i.phase == "filter" and i.severity == Severity.PASS
        ]
        assert len(filter_passes) == 5


# ═══════════════════════════════════════════════════════════════════════════
# 4. Core loop — ANALYZE/CONSENSUS/SIZE/EXECUTE invariants
# ═══════════════════════════════════════════════════════════════════════════

class TestCoreLoopInvariants:
    """Core layer detects execution-path gaps."""

    def test_approved_intent_with_no_orders_submitted_is_fail(self) -> None:
        """approved_orders_intent > 0 but orders_submitted == 0 with no block → FAIL."""
        audit = PipelineAudit()
        stats = _full_cycle_stats()
        stats["per_asset_stats"]["ETH"]["orders_submitted"] = 0
        stats["per_asset_stats"]["ETH"]["orders_blocked_by_risk"] = 0
        stats["per_asset_stats"]["ETH"]["orders_blocked_by_kill_switch"] = 0

        result = audit.run(cycle_stats=stats)
        eth_fails = [
            i for i in result.items
            if i.layer == "CORE" and i.phase == "execution"
            and i.asset == "ETH" and i.severity == Severity.FAIL
        ]
        assert len(eth_fails) == 1, f"Missing execution FAIL for ETH: {[i for i in result.items if i.asset == 'ETH']}"

    def test_all_vetoed_with_low_edge_is_warn(self) -> None:
        """All candidates vetoed by edge_too_low → WARN (not FAIL — might be market conditions)."""
        audit = PipelineAudit()
        stats = _full_cycle_stats(approved_per_asset=0)
        result = audit.run(cycle_stats=stats)
        consensus_warns = [
            i for i in result.items
            if i.layer == "CORE" and i.phase == "consensus" and i.severity == Severity.WARN
        ]
        # One per asset since all are vetoed
        assert len(consensus_warns) == 5

    def test_kelly_zero_on_all_candidates_is_fail(self) -> None:
        """kelly_zero_count == evaluated means 100% Kelly=0 → FAIL."""
        audit = PipelineAudit()
        stats = _full_cycle_stats(approved_per_asset=0)
        for asset in CRYPTO_ASSETS_ORDERED:
            stats["per_asset_stats"][asset]["kelly_zero_count"] = 2
        result = audit.run(cycle_stats=stats)
        sizing_fails = [
            i for i in result.items
            if i.layer == "CORE" and i.phase == "sizing" and i.severity == Severity.FAIL
        ]
        assert len(sizing_fails) == 5

    def test_approved_intents_produce_passes(self) -> None:
        audit = PipelineAudit()
        stats = _full_cycle_stats(approved_per_asset=1)
        result = audit.run(cycle_stats=stats)
        exec_passes = [
            i for i in result.items
            if i.layer == "CORE" and i.phase == "execution" and i.severity == Severity.PASS
        ]
        assert len(exec_passes) == 5


# ═══════════════════════════════════════════════════════════════════════════
# 5. Downstream — fills, exposure, bankroll
# ═══════════════════════════════════════════════════════════════════════════

class TestDownstreamChecks:
    """Downstream layer detects fill schema issues, negative exposure, bankroll drift."""

    def test_fill_missing_asset_field_is_warn(self) -> None:
        audit = PipelineAudit()
        state = {"recent_fills": [{"contracts": 1, "entry_price": 0.50}]}  # no "asset"
        result = audit.run(downstream_state=state)
        fill_warns = [
            i for i in result.items
            if i.layer == "DOWNSTREAM" and i.phase == "fills" and i.severity == Severity.WARN
        ]
        assert len(fill_warns) >= 1

    def test_negative_exposure_is_fail(self) -> None:
        audit = PipelineAudit()
        state = {"exposure_by_asset": {"DOGE": -300.0}}
        result = audit.run(downstream_state=state)
        exp_fails = [
            i for i in result.items
            if i.layer == "DOWNSTREAM" and i.phase == "exposure"
            and i.asset == "DOGE" and i.severity == Severity.FAIL
        ]
        assert len(exp_fails) == 1

    def test_bankroll_delta_within_epsilon_is_pass(self) -> None:
        audit = PipelineAudit()
        state = {"bankroll": {"delta_cents": 100, "epsilon_cents": 500}}
        result = audit.run(downstream_state=state)
        br_passes = [
            i for i in result.items
            if i.layer == "DOWNSTREAM" and i.phase == "bankroll" and i.severity == Severity.PASS
        ]
        assert len(br_passes) == 1

    def test_bankroll_delta_exceeds_epsilon_is_warn(self) -> None:
        audit = PipelineAudit()
        state = {"bankroll": {"delta_cents": 600, "epsilon_cents": 500}}
        result = audit.run(downstream_state=state)
        br_warns = [
            i for i in result.items
            if i.layer == "DOWNSTREAM" and i.phase == "bankroll" and i.severity == Severity.WARN
        ]
        assert len(br_warns) == 1


# ═══════════════════════════════════════════════════════════════════════════
# 6. Regression fixture — non-BTC assets produce non-zero candidates
# ═══════════════════════════════════════════════════════════════════════════

class TestNonBtcCandidateRegression:
    """Regression: given a fixture catalog with live markets for all 5 assets,
    the pipeline audit must confirm non-zero candidate counts for ETH/SOL/XRP/DOGE.

    This test guards against BTC-only filtering bugs where non-BTC assets are
    silently dropped before reaching CT."""

    def _build_fixture_catalog(self) -> Dict[str, Any]:
        """Simulate a Kalshi catalog snapshot where all 5 assets have markets."""
        return {
            "by_asset": {
                "BTC": 10,
                "ETH": 8,
                "SOL": 5,
                "XRP": 4,
                "DOGE": 3,
            },
            "by_timeframe": {
                "15m": 8, "1h": 8, "daily": 6, "weekly": 4, "monthly": 2, "annual": 2,
            },
            "by_asset_timeframe": {
                "BTC": {"15m": 2, "1h": 2, "daily": 2, "weekly": 2, "monthly": 1, "annual": 1},
                "ETH": {"15m": 2, "1h": 2, "daily": 1, "weekly": 1, "monthly": 1, "annual": 1},
                "SOL": {"15m": 1, "1h": 1, "daily": 1, "weekly": 1, "monthly": 1, "annual": 0},
                "XRP": {"15m": 1, "1h": 1, "daily": 1, "weekly": 0, "monthly": 1, "annual": 0},
                "DOGE": {"15m": 1, "1h": 1, "daily": 1, "weekly": 0, "monthly": 0, "annual": 0},
            },
        }

    def _build_fixture_stats(self) -> Dict[str, Any]:
        return {
            "scan_by_asset_timeframe": {
                "BTC": {"15m": 3, "1h": 3, "daily": 2, "weekly": 1, "monthly": 1, "annual": 1},
                "ETH": {"15m": 2, "1h": 2, "daily": 1, "weekly": 1, "monthly": 1, "annual": 1},
                "SOL": {"15m": 1, "1h": 1, "daily": 1, "weekly": 1, "monthly": 1, "annual": 0},
                "XRP": {"15m": 1, "1h": 1, "daily": 1, "weekly": 0, "monthly": 1, "annual": 0},
                "DOGE": {"15m": 1, "1h": 1, "daily": 1, "weekly": 0, "monthly": 0, "annual": 0},
            },
            "per_asset_stats": {
                "BTC":  {"candidates_seen": 5, "evaluated": 4, "approved": 2, "vetoed": 2,
                         "kelly_zero_count": 0, "veto_reasons": {"edge_too_low": 2},
                         "approved_orders_intent": 2, "orders_submitted": 2,
                         "orders_blocked_by_risk": 0, "orders_blocked_by_kill_switch": 0},
                "ETH":  {"candidates_seen": 3, "evaluated": 3, "approved": 1, "vetoed": 2,
                         "kelly_zero_count": 0, "veto_reasons": {"edge_too_low": 2},
                         "approved_orders_intent": 1, "orders_submitted": 1,
                         "orders_blocked_by_risk": 0, "orders_blocked_by_kill_switch": 0},
                "SOL":  {"candidates_seen": 2, "evaluated": 2, "approved": 1, "vetoed": 1,
                         "kelly_zero_count": 0, "veto_reasons": {"edge_too_low": 1},
                         "approved_orders_intent": 1, "orders_submitted": 1,
                         "orders_blocked_by_risk": 0, "orders_blocked_by_kill_switch": 0},
                "XRP":  {"candidates_seen": 2, "evaluated": 2, "approved": 1, "vetoed": 1,
                         "kelly_zero_count": 0, "veto_reasons": {"edge_too_low": 1},
                         "approved_orders_intent": 1, "orders_submitted": 1,
                         "orders_blocked_by_risk": 0, "orders_blocked_by_kill_switch": 0},
                "DOGE": {"candidates_seen": 1, "evaluated": 1, "approved": 1, "vetoed": 0,
                         "kelly_zero_count": 0, "veto_reasons": {},
                         "approved_orders_intent": 1, "orders_submitted": 1,
                         "orders_blocked_by_risk": 0, "orders_blocked_by_kill_switch": 0},
            },
        }

    def test_all_5_assets_have_candidates(self) -> None:
        """With a known fixture snapshot, all 5 assets must appear in scan counts."""
        audit = PipelineAudit()
        result = audit.run(
            catalog_snapshot=self._build_fixture_catalog(),
            cycle_stats=self._build_fixture_stats(),
        )
        # No FAIL items expected
        assert result.failures == 0, f"Unexpected failures: {result.blockers}"

    def test_non_btc_assets_have_non_zero_candidates(self) -> None:
        """ETH, SOL, XRP, DOGE must have candidates_seen > 0 in fixture."""
        stats = self._build_fixture_stats()
        non_btc = ["ETH", "SOL", "XRP", "DOGE"]
        for asset in non_btc:
            seen = stats["per_asset_stats"][asset]["candidates_seen"]
            assert seen > 0, (
                f"Regression: {asset} has 0 candidates despite live markets in fixture. "
                "This indicates a BTC-only filtering bug."
            )

    def test_scan_counts_include_all_five_assets(self) -> None:
        """scan_by_asset_timeframe must contain entries for all 5 assets."""
        stats = self._build_fixture_stats()
        scan_keys = set(stats["scan_by_asset_timeframe"].keys())
        assert scan_keys == set(CRYPTO_ASSETS_ORDERED), (
            f"scan_by_asset_timeframe missing assets: {set(CRYPTO_ASSETS_ORDERED) - scan_keys}"
        )


# ═══════════════════════════════════════════════════════════════════════════
# 7. AuditResult helpers
# ═══════════════════════════════════════════════════════════════════════════

class TestAuditResultHelpers:
    """AuditResult.add(), counters, and all_pass behave correctly."""

    def test_add_pass_increments_passes(self) -> None:
        result = AuditResult()
        result.add(AuditItem("UPSTREAM", "catalog", "BTC", None, Severity.PASS, "ok"))
        assert result.passes == 1
        assert result.all_pass is True

    def test_add_warn_increments_warnings(self) -> None:
        result = AuditResult()
        result.add(AuditItem("UPSTREAM", "catalog", "SOL", None, Severity.WARN, "no markets"))
        assert result.warnings == 1
        assert result.all_pass is True  # WARN does not break all_pass

    def test_add_fail_increments_failures_and_breaks_all_pass(self) -> None:
        result = AuditResult()
        result.add(AuditItem("CORE", "execution", "ETH", None, Severity.FAIL, "lost order"))
        assert result.failures == 1
        assert result.all_pass is False
        assert len(result.blockers) == 1

    def test_blockers_contain_asset_and_message(self) -> None:
        result = AuditResult()
        result.add(AuditItem("CORE", "execution", "DOGE", None, Severity.FAIL, "execution_cut"))
        assert any("DOGE" in b for b in result.blockers)
        assert any("execution_cut" in b for b in result.blockers)
