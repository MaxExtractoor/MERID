"""
Test suite for Maker/Taker Gate Split (CRITICAL FIX 2026-08-03).

Tests the split gate logic that applies different controls for maker vs taker economics:
- Maker gate: Relaxed spread controls (ratio=1.0, no spread cap)
- Taker gate: Strict spread controls (ratio from config, spread cap enforced)

This addresses the issue where maker orders were being rejected by taker-focused spread gates.
"""

import pytest
from unittest.mock import Mock, patch
from dataclasses import dataclass


@dataclass
class MockEdgeMetrics:
    """Mock edge metrics for testing."""
    side: str
    raw_edge_cents: float
    spread_cents: int
    executable_edge_cents: float
    spread_cost_cents: float
    taker_fee_cents: float
    spread_to_edge_ratio: float
    p_hat_yes_cents: float


@dataclass
class MockDynamicThresholdResult:
    """Mock dynamic threshold result for testing."""
    threshold_cents: float
    spread_component: float
    volatility_component: float
    fee_component: float
    slippage_component: float
    base_hurdle: float
    asset_config_name: str


class TestMakerTakerGateSplit:
    """
    Source-contract tests for the maker/taker gate split in order_router.

    The gate function (edge_aware_microstructure_gate) is imported lazily inside
    the router and lives in spread_edge_analytics; the previous tests patched a
    module attribute that does not exist and then called the mock directly,
    which tested nothing about production.  These tests pin the real contract:
    the router's maker branch must pass relaxed spread controls and the taker
    branch must pass the configured strict controls.
    """

    ROUTER_SRC = "merid/event_venues/kalshi/order_router.py"

    def _router_source(self) -> str:
        with open(self.ROUTER_SRC, "r", encoding="utf-8") as f:
            return f.read()

    def _gate_branch(self, src: str, marker: str) -> str:
        """Return the source slice starting at a log marker through the next gate call."""
        idx = src.index(marker)
        return src[idx:idx + 2500]

    def test_maker_economics_bypasses_strict_spread_cap(self):
        """Maker branch must call the gate with max_spread_cents=None (disabled)."""
        branch = self._gate_branch(self._router_source(), "[MAKER-GATE]")
        assert "edge_aware_microstructure_gate(" in branch
        assert "max_spread_cents=None" in branch,             "maker gate must disable the strict spread cap (makers capture spread)"

    def test_taker_economics_enforces_spread_cap(self):
        """Taker branch must call the gate with the configured max_spread_cents."""
        branch = self._gate_branch(self._router_source(), "[TAKER-GATE]")
        assert "edge_aware_microstructure_gate(" in branch
        assert "max_spread_cents=max_spread_cents" in branch,             "taker gate must enforce the configured spread cap"

    def test_maker_gate_uses_relaxed_ratio(self):
        """Maker branch must pass max_spread_to_edge_ratio=1.0 (relaxed)."""
        branch = self._gate_branch(self._router_source(), "[MAKER-GATE]")
        assert "max_spread_to_edge_ratio=1.0" in branch,             "maker gate must use the relaxed 1.0 spread/edge ratio"

    def test_taker_gate_uses_configured_ratio(self):
        """Taker branch must pass the configured max_spread_to_edge_ratio."""
        branch = self._gate_branch(self._router_source(), "[TAKER-GATE]")
        assert "max_spread_to_edge_ratio=max_spread_to_edge_ratio" in branch,             "taker gate must use the configured strict spread/edge ratio"

    def test_maker_and_taker_paths_log_distinct_diagnostics(self):
        """Both branches must emit distinct [MAKER-GATE]/[TAKER-GATE] markers."""
        src = self._router_source()
        assert "[MAKER-GATE]" in src
        assert "[TAKER-GATE]" in src
        # The maker branch must come before the taker fallback in the same
        # conditional so economics mode actually splits the paths.
        assert src.index("[MAKER-GATE]") < src.index("[TAKER-GATE]")

    def test_maker_gate_no_spread_cap_parameter(self):
        """Maker gate must explicitly pass max_spread_cents=None."""
        branch = self._gate_branch(self._router_source(), "[MAKER-GATE]")
        assert "max_spread_cents=None" in branch

    def test_taker_gate_enforces_spread_cap_parameter(self):
        """Taker gate must explicitly pass the configured spread cap."""
        branch = self._gate_branch(self._router_source(), "[TAKER-GATE]")
        assert "max_spread_cents=max_spread_cents" in branch


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
