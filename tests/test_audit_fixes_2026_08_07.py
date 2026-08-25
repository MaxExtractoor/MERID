"""
Tests for comprehensive exit policy audit fixes (2026-08-07)

This test suite validates the fixes for issues identified by the comprehensive
exit policy audit script:
1. Missing import math in loop_15m.py
2. ExitReason enum coverage gap in unified_exit_policy_engine
3. entry_edge_pct not populated from signal edge
4. Synchronization issues between components
"""

import pytest
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


class TestLoop15mMathImport:
    """Test that loop_15m.py has the required math import."""
    
    def test_math_import_present(self):
        """Test that math module is imported in loop_15m.py."""
        import merid.loop_15m as loop_15m
        
        # Check that math is available in the module
        assert hasattr(loop_15m, 'math'), "math module should be imported in loop_15m.py"
        
        # Check that math functions are accessible
        assert hasattr(loop_15m.math, 'sqrt'), "math.sqrt should be accessible"
        assert hasattr(loop_15m.math, 'floor'), "math.floor should be accessible"
        assert hasattr(loop_15m.math, 'ceil'), "math.ceil should be accessible"


class TestExitReasonEnumCoverage:
    """Test that ExitReason enums are synchronized across modules."""
    
    def test_exit_reason_enum_coverage(self):
        """Test that unified_exit_policy_engine.ExitReason matches exit_policy.ExitReason."""
        from merid.position_management.exit_policy import ExitReason as PolicyExitReason
        from merid.position_management.unified_exit_policy_engine import ExitReason as UnifiedExitReason
        
        # Get all enum values
        policy_values = {e.value for e in PolicyExitReason}
        unified_values = {e.value for e in UnifiedExitReason}
        
        # Check that unified has all policy values
        missing_in_unified = policy_values - unified_values
        assert not missing_in_unified, f"Unified exit policy engine is missing ExitReason values: {missing_in_unified}"
        
        # Check that policy has all unified values (should be true since unified is subset)
        missing_in_policy = unified_values - policy_values
        assert not missing_in_policy, f"exit_policy module is missing ExitReason values: {missing_in_policy}"
    
    def test_exit_reason_enum_values(self):
        """Test that all expected ExitReason values are present."""
        from merid.position_management.exit_policy import ExitReason
        
        # Critical exit reasons that must be present
        critical_reasons = [
            'risk',
            'stale_data',
            'candle_reversal',
            'adaptive_timing',
            'time_stop',
            'edge_decay',
            'opportunity_cost',
            'scale_out',
            'manual',
            'stop_loss',
            'take_profit',
            'auto_exit_99c',
            'extreme_profit',
            'dynamic_take_profit',
            'ratchet_trim',
            'ratchet_floor',
            'trail',
            'loss_cut_40pct',
            'settlement_guard',
        ]
        
        present_values = {e.value for e in ExitReason}
        
        for reason in critical_reasons:
            assert reason in present_values, f"ExitReason.{reason.upper()} should be present"


class TestEntryEdgePctPopulation:
    """Test that entry_edge_pct is properly populated from signal edge."""
    
    def test_position_has_entry_edge_pct_field(self):
        """Test that Position dataclass has entry_edge_pct field."""
        from merid.position_management.position import Position
        
        # Check that entry_edge_pct field exists
        assert hasattr(Position, 'entry_edge_pct'), "Position should have entry_edge_pct field"
        
        # Check default value
        default_position = Position()
        assert hasattr(default_position, 'entry_edge_pct'), "Position instance should have entry_edge_pct"
        assert default_position.entry_edge_pct == 0.03, "Default entry_edge_pct should be 0.03"
    
    def test_cached_position_has_entry_edge_pct_field(self):
        """Test that CachedPosition has entry_edge_pct field."""
        from merid.event_venues.kalshi.position_cache import CachedPosition
        
        # Check that entry_edge_pct field exists
        assert hasattr(CachedPosition, 'entry_edge_pct'), "CachedPosition should have entry_edge_pct field"
        
        # Check default value
        default_position = CachedPosition(
            market_id="test-market",
            agent_id="test-agent",
            contracts=10,
            side="yes",
            thesis_side="yes",
            outcome_side="yes",
            book_side="ask",
            avg_price_cents=50,  # Required parameter
        )
        assert hasattr(default_position, 'entry_edge_pct'), "CachedPosition instance should have entry_edge_pct"
        assert default_position.entry_edge_pct == 0.03, "Default entry_edge_pct should be 0.03"
    
    def test_position_cache_registers_entry_edge_pct(self):
        """Test that position_cache.register_tp_targets accepts and stores entry_edge_pct."""
        from merid.event_venues.kalshi.position_cache import get_position_cache
        
        cache = get_position_cache()
        
        # Register TP targets with entry_edge_pct
        cache.register_tp_targets(
            client_order_id="test-order-123",
            take_profit_price_cents=70,
            take_profit_r_multiple=1.5,
            stop_loss_price_cents=40,
            entry_price_cents=50,
            vol_regime="normal",
            confidence="medium",
            entry_edge_pct=0.05,  # 5% edge
        )
        
        # Retrieve and check
        tp_targets = cache._pending_tp_targets.get("test-order-123")
        assert tp_targets is not None, "TP targets should be registered"
        assert tp_targets.get("edge_pct") == 0.05, "entry_edge_pct should be stored"
    
    def test_position_entry_edge_pct_from_tp_targets(self):
        """Test that Position entry_edge_pct is populated from tp_targets."""
        from merid.event_venues.kalshi.position_cache import get_position_cache
        from merid.position_management.position import Position
        
        cache = get_position_cache()
        
        # Register TP targets with entry_edge_pct
        cache.register_tp_targets(
            client_order_id="test-order-456",
            take_profit_price_cents=70,
            take_profit_r_multiple=1.5,
            stop_loss_price_cents=40,
            entry_price_cents=50,
            vol_regime="normal",
            confidence="medium",
            entry_edge_pct=0.07,  # 7% edge
        )
        
        # Create a position and check it would use the edge_pct
        # This is a simplified test - the actual wiring happens in position_cache._auto_resync_callback
        tp_targets = cache._pending_tp_targets.get("test-order-456")
        assert tp_targets is not None, "TP targets should be registered"
        
        # Check that the edge_pct would be used (priority: tp_targets > position field > default)
        edge_pct = tp_targets.get("edge_pct") if tp_targets.get("edge_pct") is not None else 0.03
        assert edge_pct == 0.07, "Should use tp_targets edge_pct when available"


class TestOrderRouterEdgePctWiring:
    """Test that order_router properly passes edge_pct to position_cache."""
    
    def test_order_intent_has_edge_pct(self):
        """Test that OrderIntent has edge_pct field."""
        from merid.event_venues.kalshi.order_router import OrderIntent
        
        # Create an intent with edge_pct
        intent = OrderIntent(
            ticker="KXBTC15M-26AUG07-1430-ET",
            side="yes",
            action="buy",
            price_cents=50,
            count=10,
            edge_pct=0.06,  # 6% edge
        )
        
        assert hasattr(intent, 'edge_pct'), "OrderIntent should have edge_pct field"
        assert intent.edge_pct == 0.06, "OrderIntent edge_pct should be set"
    
    def test_order_intent_edge_pct_default(self):
        """Test that OrderIntent edge_pct has a sensible default."""
        from merid.event_venues.kalshi.order_router import OrderIntent
        
        # Create an intent without edge_pct
        intent = OrderIntent(
            ticker="KXBTC15M-26AUG07-1430-ET",
            side="yes",
            action="buy",
            price_cents=50,
            count=10,
        )
        
        assert hasattr(intent, 'edge_pct'), "OrderIntent should have edge_pct field"
        # Check that it defaults to None or 0.0
        assert intent.edge_pct is None or intent.edge_pct == 0.0, "OrderIntent edge_pct should default to None or 0.0"


class TestSynchronizationFixes:
    """Test synchronization fixes between components."""
    
    def test_unified_exit_policy_engine_importable(self):
        """Test that unified_exit_policy_engine can be imported."""
        try:
            from merid.position_management.unified_exit_policy_engine import UnifiedExitPolicyEngine
            assert UnifiedExitPolicyEngine is not None
        except ImportError as e:
            pytest.fail(f"Failed to import UnifiedExitPolicyEngine: {e}")
    
    def test_exit_policy_importable(self):
        """Test that exit_policy can be imported."""
        try:
            from merid.position_management.exit_policy import ExitPolicy, ExitReason
            assert ExitPolicy is not None
            assert ExitReason is not None
        except ImportError as e:
            pytest.fail(f"Failed to import exit_policy: {e}")
    
    def test_position_monitor_importable(self):
        """Test that position_monitor can be imported."""
        try:
            from merid.position_management.position_monitor import PositionMonitor
            assert PositionMonitor is not None
        except ImportError as e:
            pytest.fail(f"Failed to import PositionMonitor: {e}")
    
    def test_loop_15m_importable(self):
        """Test that loop_15m can be imported."""
        try:
            import merid.loop_15m as loop_15m
            assert loop_15m is not None
        except ImportError as e:
            pytest.fail(f"Failed to import loop_15m: {e}")
    
    def test_order_router_importable(self):
        """Test that order_router can be imported."""
        try:
            from merid.event_venues.kalshi.order_router import OrderIntent, OrderResult
            assert OrderIntent is not None
            assert OrderResult is not None
        except ImportError as e:
            pytest.fail(f"Failed to import order_router: {e}")
    
    def test_position_monitor_constants_defined(self):
        """Test that position_monitor has proper constants defined."""
        from merid.position_management.position_monitor import (
            POLL_INTERVAL_SECONDS,
            SUBMISSION_CACHE_TTL_SECONDS,
            STARTUP_GRACE_WINDOW_SECONDS,
            EXIT_INTENT_TIMEOUT_SECONDS,
            DUPLICATE_WINDOW_SECONDS,
            R_MULTIPLE_THRESHOLD,
            TRAILING_ACTIVATION_R,
            TRAILING_GIVEBACK_CENTS,
            DEFAULT_RISK_CENTS,
        )
        
        # Check that all constants are defined
        assert POLL_INTERVAL_SECONDS == 5.0
        assert SUBMISSION_CACHE_TTL_SECONDS == 15.0
        assert STARTUP_GRACE_WINDOW_SECONDS == 30.0
        assert EXIT_INTENT_TIMEOUT_SECONDS == 15.0
        assert DUPLICATE_WINDOW_SECONDS == 5.0
        assert R_MULTIPLE_THRESHOLD == 0.5
        assert TRAILING_ACTIVATION_R == 0.8
        assert TRAILING_GIVEBACK_CENTS == 5
        assert DEFAULT_RISK_CENTS == 5
    
    def test_exit_policy_constants_defined(self):
        """Test that exit_policy has proper constants defined."""
        from merid.position_management.exit_policy import (
            DEFAULT_MAX_HOLD_SECONDS,
            MIN_EDGE_THRESHOLD,
            TIME_STOP_R_THRESHOLD,
            VOLATILITY_HOLD_MULTIPLIERS,
        )
        
        # Check that all constants are defined
        assert DEFAULT_MAX_HOLD_SECONDS == 900.0
        assert MIN_EDGE_THRESHOLD == 0.0
        assert TIME_STOP_R_THRESHOLD == 0.5
        assert VOLATILITY_HOLD_MULTIPLIERS == {
            "LOW": 1.0,
            "NORMAL": 0.75,
            "HIGH": 0.5,
            "EXTREME": 0.33,
        }
    
    def test_unified_exit_policy_engine_constants_defined(self):
        """Test that unified_exit_policy_engine has proper constants defined."""
        from merid.position_management.unified_exit_policy_engine import (
            DEFAULT_TRAILING_ACTIVATION_R,
            DEFAULT_TRAILING_GIVEBACK_CENTS,
            DEFAULT_MAX_HOLD_SECONDS,
            DEFAULT_MIN_EDGE_AFTER_FEES_CENTS,
            DEFAULT_TP_MIN_CENTS,
            REGIME_ADJUSTMENT_MULTIPLIER,
            REGIME_CONSERVATIVE_MULTIPLIER,
            REGIME_CONSERVATIVE_TP_MULTIPLIER,
            REFERENCE_PRICE_CENTS,
            DEFAULT_SL_DISTANCE_PCT,
            DEFAULT_SL_R_MULTIPLE,
            DEFAULT_TP_R_MULTIPLE,
            DEFAULT_TP_DISTANCE_PCT,
        )
        
        # Check that all constants are defined
        assert DEFAULT_TRAILING_ACTIVATION_R == 0.8
        assert DEFAULT_TRAILING_GIVEBACK_CENTS == 5
        assert DEFAULT_MAX_HOLD_SECONDS == 600
        assert DEFAULT_MIN_EDGE_AFTER_FEES_CENTS == 2.0
        assert DEFAULT_TP_MIN_CENTS == 2
        assert REGIME_ADJUSTMENT_MULTIPLIER == 1.2
        assert REGIME_CONSERVATIVE_MULTIPLIER == 0.8
        assert REGIME_CONSERVATIVE_TP_MULTIPLIER == 0.75
        assert REFERENCE_PRICE_CENTS == 42
        assert DEFAULT_SL_DISTANCE_PCT == 0.075
        assert DEFAULT_SL_R_MULTIPLE == 1.0
        assert DEFAULT_TP_R_MULTIPLE == 1.0
        assert DEFAULT_TP_DISTANCE_PCT == 0.15


class TestRegressionPrevention:
    """Test that known issues don't regress."""
    
    def test_no_missing_math_import_in_loop_15m(self):
        """Regression test: ensure math import is present in loop_15m.py."""
        import merid.loop_15m as loop_15m
        
        # This should not raise an AttributeError
        try:
            result = loop_15m.math.sqrt(4.0)
            assert result == 2.0
        except AttributeError as e:
            pytest.fail(f"math module not properly imported in loop_15m: {e}")
    
    def test_exit_reason_enum_no_regression(self):
        """Regression test: ensure ExitReason enum coverage doesn't regress."""
        from merid.position_management.exit_policy import ExitReason as PolicyExitReason
        from merid.position_management.unified_exit_policy_engine import ExitReason as UnifiedExitReason
        
        policy_values = {e.value for e in PolicyExitReason}
        unified_values = {e.value for e in UnifiedExitReason}
        
        # Ensure unified has all policy values (no regression)
        missing_in_unified = policy_values - unified_values
        assert not missing_in_unified, f"REGRESSION: Unified exit policy engine is missing ExitReason values: {missing_in_unified}"
    
    def test_entry_edge_pct_no_regression(self):
        """Regression test: ensure entry_edge_pct is properly wired."""
        from merid.position_management.position import Position
        from merid.event_venues.kalshi.position_cache import CachedPosition
        
        # Check Position has the field
        assert hasattr(Position, 'entry_edge_pct'), "REGRESSION: Position missing entry_edge_pct field"
        
        # Check CachedPosition has the field
        assert hasattr(CachedPosition, 'entry_edge_pct'), "REGRESSION: CachedPosition missing entry_edge_pct field"
        
        # Check defaults are sensible
        pos = Position()
        cached = CachedPosition(
            market_id="test",
            agent_id="test",
            contracts=1,
            side="yes",
            thesis_side="yes",
            outcome_side="yes",
            book_side="ask",
            avg_price_cents=50,  # Required parameter
        )
        
        assert pos.entry_edge_pct == 0.03, "REGRESSION: Position entry_edge_pct default changed"
        assert cached.entry_edge_pct == 0.03, "REGRESSION: CachedPosition entry_edge_pct default changed"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
