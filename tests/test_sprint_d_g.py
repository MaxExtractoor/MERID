"""Tests for Sprints D–G: Correlation, Messages, Edge Recalibration, UI wiring.

Sprint D: Inter-asset correlation + diversity gate
Sprint E: Typed message schemas + bus publishing
Sprint F: UI component/view existence + API endpoint wiring
Sprint G: Edge threshold recalibration
"""

from __future__ import annotations

import asyncio
import math
import time
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch, AsyncMock

import pytest


# ═══════════════════════════════════════════════════════════════════════════
# Sprint D — Correlation Tracker
# ═══════════════════════════════════════════════════════════════════════════


class TestCorrelationTracker:
    """Tests for merid.risk.correlation.CorrelationTracker."""

    def _make_tracker(self, window=50):
        from merid.risk.correlation import CorrelationTracker
        return CorrelationTracker(window=window)

    def test_empty_tracker_returns_zero(self):
        tracker = self._make_tracker()
        assert tracker.get_correlation("BTC", "ETH") == 0.0

    def test_same_asset_returns_one(self):
        tracker = self._make_tracker()
        assert tracker.get_correlation("BTC", "BTC") == 1.0

    def test_perfectly_correlated(self):
        tracker = self._make_tracker()
        for i in range(20):
            r = 0.01 * (i % 5 - 2)
            tracker.record_return("BTC", r)
            tracker.record_return("ETH", r)  # Identical returns
        corr = tracker.get_correlation("BTC", "ETH")
        assert corr > 0.99, f"Expected ≈1.0, got {corr}"

    def test_perfectly_anticorrelated(self):
        tracker = self._make_tracker()
        for i in range(20):
            r = 0.01 * (i % 5 - 2)
            tracker.record_return("BTC", r)
            tracker.record_return("ETH", -r)  # Opposite returns
        corr = tracker.get_correlation("BTC", "ETH")
        assert corr < -0.99, f"Expected ≈-1.0, got {corr}"

    def test_uncorrelated_near_zero(self):
        import random
        random.seed(42)
        tracker = self._make_tracker()
        for _ in range(100):
            tracker.record_return("BTC", random.gauss(0, 0.01))
            tracker.record_return("SOL", random.gauss(0, 0.01))
        corr = tracker.get_correlation("BTC", "SOL")
        assert abs(corr) < 0.3, f"Expected ≈0, got {corr}"

    def test_insufficient_data_returns_zero(self):
        tracker = self._make_tracker()
        for i in range(3):  # < 5 minimum
            tracker.record_return("BTC", 0.01)
            tracker.record_return("ETH", 0.01)
        assert tracker.get_correlation("BTC", "ETH") == 0.0

    def test_window_trimming(self):
        tracker = self._make_tracker(window=10)
        for i in range(20):
            tracker.record_return("BTC", 0.01 * i)
        assert len(tracker._returns["BTC"]) == 10

    def test_case_insensitive(self):
        tracker = self._make_tracker()
        for i in range(10):
            tracker.record_return("btc", 0.01)
            tracker.record_return("BTC", 0.01)
        assert len(tracker._returns["BTC"]) == 20

    def test_tracked_assets(self):
        tracker = self._make_tracker()
        tracker.record_return("BTC", 0.01)
        tracker.record_return("ETH", 0.01)
        tracker.record_return("SOL", 0.01)
        assert tracker.tracked_assets == ["BTC", "ETH", "SOL"]

    def test_reset(self):
        tracker = self._make_tracker()
        tracker.record_return("BTC", 0.01)
        tracker.reset()
        assert tracker.tracked_assets == []


class TestExposureReductionFactor:
    """Tests for CorrelationTracker.exposure_reduction_factor."""

    def _make_tracker(self):
        from merid.risk.correlation import CorrelationTracker
        return CorrelationTracker()

    def test_no_data_returns_one(self):
        tracker = self._make_tracker()
        assert tracker.exposure_reduction_factor("BTC", "ETH") == 1.0

    def test_low_correlation_no_reduction(self):
        tracker = self._make_tracker()
        # Feed data that produces low correlation
        import random
        random.seed(99)
        for _ in range(30):
            tracker.record_return("BTC", random.gauss(0, 0.01))
            tracker.record_return("DOGE", random.gauss(0, 0.01))
        factor = tracker.exposure_reduction_factor("BTC", "DOGE")
        # With truly random data, correlation should be low → factor ≈ 1.0
        assert factor >= 0.7, f"Expected >= 0.7, got {factor}"

    def test_high_correlation_reduces(self):
        tracker = self._make_tracker()
        for i in range(30):
            r = 0.01 * (i % 5 - 2)
            tracker.record_return("BTC", r)
            tracker.record_return("ETH", r * 0.95)  # Very similar
        factor = tracker.exposure_reduction_factor("BTC", "ETH")
        assert factor < 0.8, f"Expected reduction, got {factor}"

    def test_factor_bounds(self):
        from merid.risk.correlation import MAX_REDUCTION
        tracker = self._make_tracker()
        for i in range(30):
            r = 0.01 * (i % 7 - 3)
            tracker.record_return("A", r)
            tracker.record_return("B", r)  # Perfect correlation
        factor = tracker.exposure_reduction_factor("A", "B")
        assert factor >= MAX_REDUCTION, f"Factor {factor} below floor {MAX_REDUCTION}"
        assert factor <= 1.0


class TestCorrelationMatrix:
    """Tests for the full matrix snapshot."""

    def test_matrix_structure(self):
        from merid.risk.correlation import CorrelationTracker
        tracker = CorrelationTracker()
        for i in range(10):
            tracker.record_return("BTC", 0.01 * i)
            tracker.record_return("ETH", 0.01 * i)
            tracker.record_return("SOL", 0.01 * i)
        matrix = tracker.get_matrix()
        assert len(matrix.assets) == 3
        assert len(matrix.pairs) == 3  # 3 choose 2

    def test_matrix_to_dict(self):
        from merid.risk.correlation import CorrelationTracker
        tracker = CorrelationTracker()
        for i in range(10):
            tracker.record_return("BTC", 0.01)
            tracker.record_return("ETH", 0.01)
        d = tracker.get_matrix().to_dict()
        assert "assets" in d
        assert "pairs" in d
        assert "timestamp" in d


class TestClusterFactor:
    """Tests for cluster-level reduction factor."""

    def test_cluster_factor_with_no_data(self):
        from merid.risk.correlation import CorrelationTracker
        tracker = CorrelationTracker()
        assert tracker.get_cluster_factor("BTC") == 1.0

    def test_cluster_factor_unknown_asset(self):
        from merid.risk.correlation import CorrelationTracker
        tracker = CorrelationTracker()
        assert tracker.get_cluster_factor("UNKNOWN") == 1.0


class TestCorrelationSingleton:
    """Test singleton behavior."""

    def test_singleton(self):
        from merid.risk.correlation import get_correlation_tracker
        t1 = get_correlation_tracker()
        t2 = get_correlation_tracker()
        assert t1 is t2


# ═══════════════════════════════════════════════════════════════════════════
# Sprint D — Portfolio Risk Correlation Wiring
# ═══════════════════════════════════════════════════════════════════════════


class TestPortfolioCorrelationCheck:
    """Test that PortfolioRiskAgent._check_limits includes correlation check."""

    def test_check_limits_includes_correlation_code(self):
        """Verify the correlation check was wired in."""
        import inspect
        from merid.prediction.portfolio_risk_agent import PortfolioRiskAgent
        source = inspect.getsource(PortfolioRiskAgent._check_limits)
        assert "correlation" in source.lower()
        assert "ASSET_CLUSTERS" in source


# ═══════════════════════════════════════════════════════════════════════════
# Sprint D — Consensus Diversity Gate
# ═══════════════════════════════════════════════════════════════════════════




# ═══════════════════════════════════════════════════════════════════════════
# Sprint E — Typed Message Schemas
# ═══════════════════════════════════════════════════════════════════════════












# ═══════════════════════════════════════════════════════════════════════════
# Sprint E — ForecasterRegistry Bus Publishing
# ═══════════════════════════════════════════════════════════════════════════


class TestRegistryBusPublishing:
    """Test that ForecasterRegistry publishes to the bus."""

    def test_publish_method_exists(self):
        from merid.prediction.forecasters.registry import ForecasterRegistry
        registry = ForecasterRegistry()
        assert hasattr(registry, '_publish_forecast_message')

    def test_publish_method_in_predict_all(self):
        import inspect
        from merid.prediction.forecasters.registry import ForecasterRegistry
        source = inspect.getsource(ForecasterRegistry.predict_all)
        assert "_publish_forecast_message" in source


# ═══════════════════════════════════════════════════════════════════════════
# Sprint F — UI Component/View Wiring
# ═══════════════════════════════════════════════════════════════════════════


class TestUIWiring:
    """Test that new UI components and views exist and are wired."""

    def test_calibration_dashboard_view_exists(self):
        import os
        path = os.path.join("web", "react", "src", "views", "CalibrationDashboardView.tsx")
        assert os.path.exists(path), f"Missing: {path}"

    def test_correlation_risk_panel_exists(self):
        import os
        path = os.path.join("web", "react", "src", "components", "CorrelationRiskPanel.tsx")
        assert os.path.exists(path), f"Missing: {path}"

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "DEFECT AUDIT-2026-09-22-10: calibration/correlation feature "
            "exists but is not wired into App/Sidebar/views/constants/main. "
            "Expiry 2026-10-15."
        ),
    )
    def test_calibration_view_in_app_tsx(self):
        import os
        app_path = os.path.join("web", "react", "src", "App.tsx")
        with open(app_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "CalibrationDashboardView" in content
        assert "calibration-dashboard" in content

    def test_calibration_view_in_views_ts(self):
        import os
        views_path = os.path.join("web", "react", "src", "types", "views.ts")
        with open(views_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "calibration-dashboard" in content

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "DEFECT AUDIT-2026-09-22-10: calibration/correlation feature "
            "exists but is not wired into App/Sidebar/views/constants/main. "
            "Expiry 2026-10-15."
        ),
    )
    def test_calibration_in_sidebar(self):
        import os
        sidebar_path = os.path.join("web", "react", "src", "components", "Sidebar.tsx")
        with open(sidebar_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "calibration-dashboard" in content
        assert "Target" in content  # Icon import

    def test_correlation_constants(self):
        import os
        constants_path = os.path.join("web", "react", "src", "config", "constants.ts")
        with open(constants_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "CORRELATION_MATRIX" in content
        assert "CORRELATION_CLUSTERS" in content
        assert "METRICS_FORECASTERS" in content


# ═══════════════════════════════════════════════════════════════════════════
# Sprint F — API Endpoint Wiring
# ═══════════════════════════════════════════════════════════════════════════


class TestAPIWiring:
    """Test that API endpoints are properly wired."""

    def test_correlation_api_file_exists(self):
        import os
        assert os.path.exists(os.path.join("web", "api", "correlation_api.py"))

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "DEFECT AUDIT-2026-09-22-10: calibration/correlation feature "
            "exists but is not wired into App/Sidebar/views/constants/main. "
            "Expiry 2026-10-15."
        ),
    )
    def test_correlation_api_in_main(self):
        import os
        main_path = os.path.join("web", "main.py")
        with open(main_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "correlation_api_router" in content

    def test_correlation_api_has_endpoints(self):
        from web.api.correlation_api import router
        routes = [r.path for r in router.routes]
        assert any("matrix" in r for r in routes)
        assert any("factor" in r for r in routes)
        assert any("clusters" in r for r in routes)
        assert any("record" in r for r in routes)


# ═══════════════════════════════════════════════════════════════════════════
# Sprint G — Edge Recalibrator
# ═══════════════════════════════════════════════════════════════════════════


class TestEdgeRecalibrator:
    """Tests for merid.prediction.edge_recalibrator."""

    def test_recalibrate_skips_without_data(self):
        from merid.prediction.edge_recalibrator import EdgeRecalibrator
        recal = EdgeRecalibrator()
        result = recal.recalibrate()
        assert result.skipped is True

    def test_recalibrate_skips_insufficient_trades(self):
        from merid.prediction.edge_recalibrator import EdgeRecalibrator
        recal = EdgeRecalibrator()

        with patch("merid.metrics.realized_edge.get_realized_edge_store") as mock_store:
            mock_store.return_value.get_summary.return_value = {
                "trade_count": 5,
                "avg_predicted_edge": 0.05,
                "avg_realized_edge": 0.03,
            }
            result = recal.recalibrate()
            assert result.skipped is True
            assert "Insufficient" in result.skip_reason

    def test_recalibrate_adjusts_thresholds(self):
        from merid.prediction.edge_recalibrator import EdgeRecalibrator
        from merid.prediction.strategy import StrategyConfig
        recal = EdgeRecalibrator()
        config = StrategyConfig()
        old_early = config.min_edge_early

        with patch("merid.metrics.realized_edge.get_realized_edge_store") as mock_store, \
             patch.object(recal, "_get_strategy_configs", return_value=[config]):
            mock_stat = MagicMock()
            mock_stat.resolved_count = 50
            mock_stat.sum_est_edge = 4.0   # avg 0.08
            mock_stat.sum_realized_edge = 1.5  # avg 0.03
            mock_store.return_value.get_all_edge_stats.return_value = [mock_stat]
            result = recal.recalibrate()
            assert result.skipped is False
            assert result.edge_bias > 0  # Over-estimating
            # Threshold should increase
            assert config.min_edge_early >= old_early

    def test_recalibrate_respects_floor(self):
        from merid.prediction.edge_recalibrator import EdgeRecalibrator, MIN_EDGE_FLOOR
        from merid.prediction.strategy import StrategyConfig
        config = StrategyConfig()
        config.min_edge_early = Decimal("0.02")  # Near floor
        recal = EdgeRecalibrator()

        with patch("merid.metrics.realized_edge.get_realized_edge_store") as mock_store, \
             patch.object(recal, "_get_strategy_configs", return_value=[config]):
            mock_stat = MagicMock()
            mock_stat.resolved_count = 50
            mock_stat.sum_est_edge = 1.0   # avg 0.02
            mock_stat.sum_realized_edge = 2.5  # avg 0.05
            mock_store.return_value.get_all_edge_stats.return_value = [mock_stat]
            result = recal.recalibrate()
            assert config.min_edge_early >= MIN_EDGE_FLOOR

    def test_recalibrate_history(self):
        from merid.prediction.edge_recalibrator import EdgeRecalibrator
        recal = EdgeRecalibrator()
        recal.recalibrate()
        assert len(recal.history) == 1
        assert recal.latest is not None

    def test_result_to_dict(self):
        from merid.prediction.edge_recalibrator import RecalibrationResult
        r = RecalibrationResult(
            timestamp=time.time(),
            trade_count=50,
            avg_predicted_edge=0.06,
            avg_realized_edge=0.04,
            edge_bias=0.02,
            adjustments={"early": "0.050 -> 0.054"},
        )
        d = r.to_dict()
        assert d["trade_count"] == 50
        assert d["edge_bias"] == 0.02


class TestEdgeRecalibratorSingleton:
    """Test singleton behavior."""

    def test_singleton(self):
        from merid.prediction.edge_recalibrator import get_edge_recalibrator
        r1 = get_edge_recalibrator()
        r2 = get_edge_recalibrator()
        assert r1 is r2


# ═══════════════════════════════════════════════════════════════════════════
# Sprint E — Message Enums
# ═══════════════════════════════════════════════════════════════════════════


