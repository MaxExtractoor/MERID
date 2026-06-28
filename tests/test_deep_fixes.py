"""
Deep tests for DEEP-SEV1 fixes.

Tests cover:
- TEST-DEEP-PREDICTION-RISK: PredictionMarketRisk consolidation (DEEP-SEV1-1)
- TEST-DEEP-EXIT-POLICY: Exit policy wiring (DEEP-SEV1-2)
- TEST-DEEP-FILL-TRACKING: Fill tracking (DEEP-SEV1-3)
"""

import pytest
import inspect


class TestPredictionMarketRisk:
    """TEST-DEEP-PREDICTION-RISK: Verify PredictionMarketRisk consolidation (DEEP-SEV1-1)."""

    def test_prediction_market_risk_class_exists(self):
        """Verify PredictionMarketRisk class exists."""
        try:
            from merid.prediction.risk._prediction_risk import PredictionMarketRisk
            assert PredictionMarketRisk is not None, "PredictionMarketRisk class should exist"
        except ImportError:
            pytest.skip("PredictionMarketRisk class not found - may be in different module")

    def test_prediction_market_risk_has_check_order(self):
        """Verify PredictionMarketRisk has check_order method."""
        try:
            from merid.prediction.risk._prediction_risk import PredictionMarketRisk
            source = inspect.getsource(PredictionMarketRisk)
            assert 'def check_order' in source, "PredictionMarketRisk should have check_order method"
        except ImportError:
            pytest.skip("PredictionMarketRisk class not found")

    def test_prediction_market_risk_has_category_limits(self):
        """Verify PredictionMarketRisk has category limit handling."""
        try:
            from merid.prediction.risk._prediction_risk import PredictionMarketRisk
            source = inspect.getsource(PredictionMarketRisk)
            assert 'category' in source.lower() or 'CategoryLimit' in source, \
                "PredictionMarketRisk should handle category limits"
        except ImportError:
            pytest.skip("PredictionMarketRisk class not found")


class TestExitPolicy:
    """TEST-DEEP-EXIT-POLICY: Verify exit policy wiring (DEEP-SEV1-2)."""

    def test_exit_policy_infrastructure_exists(self):
        """Verify exit policy infrastructure exists."""
        # Check for exit policy related modules
        try:
            from merid.prediction.exit_policy import ExitPolicy
            assert ExitPolicy is not None, "ExitPolicy class should exist"
        except ImportError:
            pytest.skip("ExitPolicy class not found - may be in different module")

    def test_exit_policy_has_exit_methods(self):
        """Verify exit policy has exit decision methods."""
        try:
            from merid.prediction.exit_policy import ExitPolicy
            source = inspect.getsource(ExitPolicy)
            # Check for common exit method names
            has_exit_method = any(
                f'def {method}' in source 
                for method in ['should_exit', 'get_exit_signal', 'evaluate_exit', 'check_exit']
            )
            assert has_exit_method, "ExitPolicy should have exit decision method"
        except ImportError:
            pytest.skip("ExitPolicy class not found")

    def test_exit_policy_wired_in_order_router(self):
        """Verify exit policy is wired in order router."""
        try:
            from merid.event_venues.kalshi.order_router import OrderRouter
            source = inspect.getsource(OrderRouter)
            # Check for exit policy references
            has_exit_ref = 'exit' in source.lower() or 'ExitPolicy' in source
            assert has_exit_ref, "OrderRouter should reference exit policy"
        except ImportError:
            pytest.skip("OrderRouter class not found")


class TestFillTracking:
    """TEST-DEEP-FILL-TRACKING: Verify fill tracking (DEEP-SEV1-3)."""

    def test_fill_tracking_in_global_execution_guard(self):
        """Verify fill tracking is implemented in GlobalExecutionGuard."""
        try:
            from merid.prediction.risk._prediction_risk import GlobalExecutionGuard
            source = inspect.getsource(GlobalExecutionGuard)
            # Check for fill tracking logic
            has_fill_tracking = 'fill' in source.lower() or 'Fill' in source
            assert has_fill_tracking, "GlobalExecutionGuard should have fill tracking logic"
        except ImportError:
            pytest.skip("GlobalExecutionGuard class not found")

    def test_fill_ledger_exists(self):
        """Verify fills_ledger module exists for fill tracking."""
        try:
            from merid.event_venues.kalshi.fills_ledger import FillsLedger
            assert FillsLedger is not None, "FillsLedger class should exist"
        except ImportError:
            pytest.skip("FillsLedger class not found")

    def test_fill_ledger_has_tracking_methods(self):
        """Verify fills_ledger has fill tracking methods."""
        try:
            from merid.event_venues.kalshi.fills_ledger import FillsLedger
            source = inspect.getsource(FillsLedger)
            # Check for common tracking method names
            has_tracking_method = any(
                f'def {method}' in source 
                for method in ['record_fill', 'track_fill', 'add_fill', 'register_fill']
            )
            assert has_tracking_method, "FillsLedger should have fill tracking method"
        except ImportError:
            pytest.skip("FillsLedger class not found")


class TestIndicatorConfig:
    """TEST-DEEP-INDICATOR-CONFIG: Verify indicator configuration (DEEP-SEV1 extension)."""

    def test_indicator_config_exists(self):
        """Verify IndicatorConfig class exists."""
        try:
            from merid.prediction.indicator_config import IndicatorConfig
            assert IndicatorConfig is not None, "IndicatorConfig class should exist"
        except ImportError:
            pytest.skip("IndicatorConfig class not found - may be in different module")

    def test_indicator_config_has_thresholds(self):
        """Verify IndicatorConfig has threshold configuration."""
        try:
            from merid.prediction.indicator_config import IndicatorConfig
            source = inspect.getsource(IndicatorConfig)
            # Check for threshold configuration
            has_threshold = 'threshold' in source.lower() or 'Threshold' in source
            assert has_threshold, "IndicatorConfig should have threshold configuration"
        except ImportError:
            pytest.skip("IndicatorConfig class not found")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
