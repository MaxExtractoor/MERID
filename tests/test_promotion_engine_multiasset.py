"""Multi-asset, multi-timeframe PromotionEngine tests.

Verifies that the PromotionEngine:
  1. Accepts and correctly returns promotions for every supported asset
     (BTC, ETH, SOL, XRP, DOGE) at every supported timeframe (15m, 1h, 4h, 1d).
  2. Fails fast with a clear ValueError for unsupported asset/timeframe
     combinations rather than silently defaulting to BTC.
  3. get_coverage_matrix() returns the correct shape and values for each phase.
  4. LaneOrchestrator.LANE_UNLOCK_REQUIREMENTS covers all 5 assets × 4 timeframes.
  5. The promotion coverage API endpoints return valid multi-asset data.
"""

from __future__ import annotations

import datetime
import importlib.util
import sys
from pathlib import Path
from typing import List

import pytest

from merid.risk.btc_promotion_config import (
    PHASES,
    SUPPORTED_ASSETS,
    SUPPORTED_TIMEFRAMES,
    PHASE_BY_NAME,
)
from merid.risk.promotion_engine import (
    PromotionEngine,
    PerformanceSnapshot,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _perf(**kwargs) -> PerformanceSnapshot:
    defaults = dict(
        equity=100.0,
        max_drawdown=0.05,
        sharpe=2.0,
        total_trades=500,
        first_live_date=datetime.date(2024, 1, 1),
        win_rate=0.6,
        avg_pnl_per_trade=5.0,
    )
    defaults.update(kwargs)
    return PerformanceSnapshot(**defaults)


def _engine_at_phase(phase_name: str) -> PromotionEngine:
    """Return a fresh PromotionEngine locked to the given phase."""
    engine = PromotionEngine()
    engine.current_phase = PHASE_BY_NAME[phase_name]
    return engine


def _load_coverage_router():
    """Load promotion_coverage_api.router without triggering web/api/__init__.py."""
    module_path = (
        Path(__file__).parent.parent / "web" / "api" / "promotion_coverage_api.py"
    )
    spec = importlib.util.spec_from_file_location(
        "web.api.promotion_coverage_api_isolated", module_path
    )
    module = importlib.util.module_from_spec(spec)
    # Register under an isolated name so __init__.py is never executed
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.router


# ---------------------------------------------------------------------------
# 1. Canonical constants
# ---------------------------------------------------------------------------

class TestSupportedConstants:
    """Verify canonical asset and timeframe lists are correct."""

    def test_supported_assets_contains_all_five(self):
        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            assert asset in SUPPORTED_ASSETS, f"{asset} missing from SUPPORTED_ASSETS"

    def test_supported_timeframes_contains_all_four(self):
        for tf in ["15m", "1h", "4h", "1d"]:
            assert tf in SUPPORTED_TIMEFRAMES, f"{tf} missing from SUPPORTED_TIMEFRAMES"

    def test_supported_assets_no_extras(self):
        assert set(SUPPORTED_ASSETS) == {"BTC", "ETH", "SOL", "XRP", "DOGE"}

    def test_supported_timeframes_no_extras(self):
        assert set(SUPPORTED_TIMEFRAMES) == {"15m", "1h", "4h", "1d"}


# ---------------------------------------------------------------------------
# 2. is_combination_supported — fast validation
# ---------------------------------------------------------------------------

class TestCombinationSupported:
    """Verify is_combination_supported and assert_combination_supported."""

    @pytest.mark.parametrize("asset", ["BTC", "ETH", "SOL", "XRP", "DOGE"])
    @pytest.mark.parametrize("timeframe", ["15m", "1h", "4h", "1d"])
    def test_all_valid_combinations_supported(self, asset, timeframe):
        engine = PromotionEngine()
        assert engine.is_combination_supported(asset, timeframe) is True

    @pytest.mark.parametrize("asset,timeframe", [
        ("BTC", "5m"),
        ("BTC", "2h"),
        ("USDC", "15m"),
        ("LTC", "1h"),
        ("", "15m"),
        ("BTC", ""),
    ])
    def test_unsupported_combinations_return_false(self, asset, timeframe):
        engine = PromotionEngine()
        assert engine.is_combination_supported(asset, timeframe) is False

    @pytest.mark.parametrize("asset,timeframe,match", [
        ("LTC", "15m", "Unsupported asset"),
        ("BTC", "5m", "Unsupported timeframe"),
    ])
    def test_assert_raises_value_error_with_clear_message(self, asset, timeframe, match):
        engine = PromotionEngine()
        with pytest.raises(ValueError, match=match):
            engine.assert_combination_supported(asset, timeframe)

    def test_assert_passes_for_valid_combination(self):
        engine = PromotionEngine()
        for asset in SUPPORTED_ASSETS:
            for tf in SUPPORTED_TIMEFRAMES:
                engine.assert_combination_supported(asset, tf)  # must not raise


# ---------------------------------------------------------------------------
# 3. Phase-gated asset/timeframe unlocks
# ---------------------------------------------------------------------------

class TestPhaseUnlocks:
    """Verify correct assets and timeframes unlock at each phase."""

    def test_phase0_only_unlocks_btc(self):
        engine = _engine_at_phase("PHASE_0")
        assert engine.is_asset_unlocked("BTC") is True
        for asset in ["ETH", "SOL", "XRP", "DOGE"]:
            assert engine.is_asset_unlocked(asset) is False, (
                f"PHASE_0 should not unlock {asset}"
            )

    def test_phase0_only_unlocks_15m(self):
        engine = _engine_at_phase("PHASE_0")
        assert engine.is_timeframe_unlocked("15m") is True
        for tf in ["1h", "4h", "1d"]:
            assert engine.is_timeframe_unlocked(tf) is False

    def test_phase1_adds_1h_timeframe(self):
        engine = _engine_at_phase("PHASE_1")
        assert engine.is_timeframe_unlocked("15m") is True
        assert engine.is_timeframe_unlocked("1h") is True
        assert engine.is_timeframe_unlocked("4h") is False

    def test_phase2_adds_eth(self):
        engine = _engine_at_phase("PHASE_2")
        assert engine.is_asset_unlocked("ETH") is True
        for asset in ["SOL", "XRP", "DOGE"]:
            assert engine.is_asset_unlocked(asset) is False

    def test_phase3_unlocks_all_five_assets(self):
        engine = _engine_at_phase("PHASE_3")
        for asset in SUPPORTED_ASSETS:
            assert engine.is_asset_unlocked(asset) is True, (
                f"PHASE_3 must unlock {asset}"
            )

    def test_phase3_unlocks_all_four_timeframes(self):
        engine = _engine_at_phase("PHASE_3")
        for tf in SUPPORTED_TIMEFRAMES:
            assert engine.is_timeframe_unlocked(tf) is True, (
                f"PHASE_3 must unlock timeframe {tf}"
            )


# ---------------------------------------------------------------------------
# 4. get_coverage_matrix shape and correctness
# ---------------------------------------------------------------------------

class TestCoverageMatrix:
    """Verify get_coverage_matrix() returns correct shape and values."""

    def test_matrix_has_all_assets(self):
        engine = PromotionEngine()
        matrix = engine.get_coverage_matrix()
        for asset in SUPPORTED_ASSETS:
            assert asset in matrix, f"matrix missing asset {asset}"

    def test_matrix_has_all_timeframes_per_asset(self):
        engine = PromotionEngine()
        matrix = engine.get_coverage_matrix()
        for asset in SUPPORTED_ASSETS:
            for tf in SUPPORTED_TIMEFRAMES:
                assert tf in matrix[asset], f"matrix missing {asset}:{tf}"

    def test_matrix_cell_structure(self):
        engine = PromotionEngine()
        matrix = engine.get_coverage_matrix()
        for asset in SUPPORTED_ASSETS:
            for tf in SUPPORTED_TIMEFRAMES:
                cell = matrix[asset][tf]
                assert "unlocked" in cell
                assert "asset_unlocked" in cell
                assert "timeframe_unlocked" in cell
                assert isinstance(cell["unlocked"], bool)

    def test_phase0_matrix_only_btc_15m_unlocked(self):
        engine = _engine_at_phase("PHASE_0")
        matrix = engine.get_coverage_matrix()
        # Only BTC:15m should be fully unlocked
        assert matrix["BTC"]["15m"]["unlocked"] is True
        # Everything else must be locked
        for asset in SUPPORTED_ASSETS:
            for tf in SUPPORTED_TIMEFRAMES:
                if asset == "BTC" and tf == "15m":
                    continue
                assert matrix[asset][tf]["unlocked"] is False, (
                    f"PHASE_0 should not unlock {asset}:{tf}"
                )

    def test_phase3_matrix_all_unlocked(self):
        engine = _engine_at_phase("PHASE_3")
        matrix = engine.get_coverage_matrix()
        for asset in SUPPORTED_ASSETS:
            for tf in SUPPORTED_TIMEFRAMES:
                assert matrix[asset][tf]["unlocked"] is True, (
                    f"PHASE_3 must unlock {asset}:{tf}"
                )

    def test_get_status_includes_coverage_matrix(self):
        engine = _engine_at_phase("PHASE_3")
        status = engine.get_status()
        assert "coverage_matrix" in status
        assert "supported_assets" in status
        assert "supported_timeframes" in status
        assert status["supported_assets"] == list(SUPPORTED_ASSETS)
        assert status["supported_timeframes"] == list(SUPPORTED_TIMEFRAMES)


# ---------------------------------------------------------------------------
# 5. Promotion/demotion cycle preserves multi-asset awareness
# ---------------------------------------------------------------------------

class TestPromotionCycleMaintainsMultiAsset:
    """End-to-end: promote through phases, verify asset unlocks at each level."""

    def test_full_promotion_cycle_unlocks_assets_in_order(self):
        engine = PromotionEngine()
        assert engine.current_phase.name == "PHASE_0"
        # At PHASE_0, only BTC is unlocked
        assert engine.is_asset_unlocked("BTC") is True
        assert engine.is_asset_unlocked("ETH") is False

        # Promote to PHASE_2 (ETH unlocks at PHASE_2)
        result = engine.maybe_promote(_perf(equity=35.0, total_trades=120, max_drawdown=0.05,
                                            sharpe=0.8, first_live_date=datetime.date(2023, 1, 1)))
        assert engine.current_phase.name in ("PHASE_2", "PHASE_3")
        assert engine.is_asset_unlocked("ETH") is True

        # At PHASE_3, all assets and timeframes unlock
        result = engine.maybe_promote(_perf(equity=75.0, total_trades=300, max_drawdown=0.05,
                                            sharpe=1.5, first_live_date=datetime.date(2023, 1, 1)))
        assert engine.current_phase.name == "PHASE_3"
        for asset in SUPPORTED_ASSETS:
            assert engine.is_asset_unlocked(asset) is True
        for tf in SUPPORTED_TIMEFRAMES:
            assert engine.is_timeframe_unlocked(tf) is True

    def test_demotion_reverts_asset_access(self):
        """After demotion, assets that were unlocked at higher phase should lock."""
        engine = _engine_at_phase("PHASE_3")
        # Demote by presenting degraded performance
        engine.maybe_promote(_perf(equity=40.0, total_trades=10, max_drawdown=0.15,
                                   sharpe=0.2, first_live_date=datetime.date(2025, 1, 1)))
        assert engine.current_phase.name != "PHASE_3"
        # SOL/XRP/DOGE should no longer be unlocked
        if engine.current_phase.name in ("PHASE_0", "PHASE_1"):
            assert engine.is_asset_unlocked("SOL") is False
            assert engine.is_asset_unlocked("XRP") is False
            assert engine.is_asset_unlocked("DOGE") is False


# ---------------------------------------------------------------------------
# 6. LaneOrchestrator LANE_UNLOCK_REQUIREMENTS coverage
# ---------------------------------------------------------------------------

class TestLaneOrchestratorCoverage:
    """Verify LANE_UNLOCK_REQUIREMENTS covers all 5 assets × 4 timeframes."""

    def test_all_combinations_present_in_requirements(self):
        from merid.lanes.btc15m_lane import LaneOrchestrator
        reqs = LaneOrchestrator.LANE_UNLOCK_REQUIREMENTS
        for asset in SUPPORTED_ASSETS:
            for tf in SUPPORTED_TIMEFRAMES:
                assert (asset, tf) in reqs, (
                    f"LANE_UNLOCK_REQUIREMENTS missing ({asset}, {tf})"
                )

    def test_btc_15m_is_phase0(self):
        from merid.lanes.btc15m_lane import LaneOrchestrator
        assert LaneOrchestrator.LANE_UNLOCK_REQUIREMENTS[("BTC", "15m")] == "PHASE_0"

    def test_sol_xrp_doge_at_phase3(self):
        from merid.lanes.btc15m_lane import LaneOrchestrator
        reqs = LaneOrchestrator.LANE_UNLOCK_REQUIREMENTS
        for asset in ["SOL", "XRP", "DOGE"]:
            for tf in SUPPORTED_TIMEFRAMES:
                assert reqs[(asset, tf)] == "PHASE_3", (
                    f"({asset}, {tf}) should require PHASE_3"
                )

    def test_no_unknown_assets_in_requirements(self):
        from merid.lanes.btc15m_lane import LaneOrchestrator
        reqs = LaneOrchestrator.LANE_UNLOCK_REQUIREMENTS
        for asset, tf in reqs:
            assert asset in SUPPORTED_ASSETS, f"Unknown asset '{asset}' in LANE_UNLOCK_REQUIREMENTS"
            assert tf in SUPPORTED_TIMEFRAMES, f"Unknown timeframe '{tf}' in LANE_UNLOCK_REQUIREMENTS"


# ---------------------------------------------------------------------------
# 7. Promotion coverage API
# ---------------------------------------------------------------------------

class TestPromotionCoverageAPI:
    """Verify the /api/v1/crypto/promotion-coverage API endpoint."""

    @pytest.fixture(scope="class")
    def client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        router = _load_coverage_router()
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_coverage_endpoint_returns_matrix(self, client):
        resp = client.get("/api/v1/crypto/promotion-coverage")
        assert resp.status_code == 200
        data = resp.json()
        assert "matrix" in data
        assert "supported_assets" in data
        assert "supported_timeframes" in data
        assert set(data["supported_assets"]) == set(SUPPORTED_ASSETS)
        assert set(data["supported_timeframes"]) == set(SUPPORTED_TIMEFRAMES)

    def test_coverage_matrix_all_assets_present(self, client):
        resp = client.get("/api/v1/crypto/promotion-coverage")
        data = resp.json()
        matrix = data["matrix"]
        for asset in SUPPORTED_ASSETS:
            assert asset in matrix, f"matrix missing asset {asset}"
            for tf in SUPPORTED_TIMEFRAMES:
                assert tf in matrix[asset], f"matrix missing {asset}:{tf}"

    def test_status_endpoint_valid_combination(self, client):
        for asset in SUPPORTED_ASSETS:
            for tf in SUPPORTED_TIMEFRAMES:
                resp = client.get(
                    f"/api/v1/crypto/promotion-status?asset={asset}&timeframe={tf}"
                )
                assert resp.status_code == 200, (
                    f"Expected 200 for {asset}/{tf}, got {resp.status_code}: {resp.text}"
                )
                data = resp.json()
                assert data["asset"] == asset
                assert data["timeframe"] == tf
                assert "combination_unlocked" in data

    def test_status_endpoint_invalid_asset_returns_400(self, client):
        resp = client.get("/api/v1/crypto/promotion-status?asset=LTC&timeframe=15m")
        assert resp.status_code == 400
        assert "Unsupported asset" in resp.json()["detail"]

    def test_status_endpoint_invalid_timeframe_returns_400(self, client):
        resp = client.get("/api/v1/crypto/promotion-status?asset=BTC&timeframe=5m")
        assert resp.status_code == 400
        assert "Unsupported timeframe" in resp.json()["detail"]

    def test_status_endpoint_no_btc_only_fallback(self, client):
        """Requesting ETH explicitly should return ETH, not silently fall back to BTC."""
        resp = client.get("/api/v1/crypto/promotion-status?asset=ETH&timeframe=1h")
        assert resp.status_code == 200
        data = resp.json()
        assert data["asset"] == "ETH"
        assert data["timeframe"] == "1h"
