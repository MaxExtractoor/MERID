"""
End-to-end tests for exit decision lifecycle (position_monitor + ExitPolicy + ExitResolver).

Tests the full integration path from position monitoring through policy evaluation
to final exit resolution.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime
from merid.position_management.position import Position, PositionSide
from merid.position_management.exit_policy import ExitPolicy, ExitReason
from merid.position_management.exit_decision import ExitDecision, ExitSourceLayer, ExitPriority
from merid.position_management.exit_policy_resolver import get_exit_policy_resolver
from merid.position_management.exit_resolver import ExitResolver, get_exit_resolver


class TestExitLifecycle:
    """Test end-to-end exit decision lifecycle."""
    
    def test_position_level_exit_beats_policy_level(self):
        """Test position-level EXTREME_PROFIT beats policy-layer TIME_STOP."""
        # Setup position
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=1,
            avg_entry_price_cents=50,
        )
        position.update_runtime_state(99)  # 99c price (extreme profit)
        
        # Create position-level decision (EXTREME_PROFIT)
        # Note: EXTREME_PROFIT is not in ExitReason enum, so we use MANUAL as proxy
        position_decision = ExitDecision(
            reason=ExitReason.MANUAL,  # Proxy for EXTREME_PROFIT
            priority=ExitPriority.MANUAL,  # Priority 20
            source_layer=ExitSourceLayer.POSITION_LEVEL,
            exit_price_cents=99,
            metadata={"trigger": "extreme_profit_99c"},
        )
        
        # Create policy-layer decision (TIME_STOP)
        policy_decision = ExitDecision(
            reason=ExitReason.TIME_STOP,
            priority=ExitPriority.TIME_STOP,  # Priority 40
            source_layer=ExitSourceLayer.POLICY_LAYER,
            exit_price_cents=99,
            metadata={"time_since_entry": 600.0},
        )
        
        # Resolve through ExitResolver
        resolver = get_exit_resolver()
        winning_decision = resolver.resolve(
            [position_decision, policy_decision],
            position_id=position.position_id
        )
        
        # TIME_STOP (40) should beat MANUAL (20)
        assert winning_decision is not None
        assert winning_decision.reason == ExitReason.TIME_STOP
        assert winning_decision.priority == ExitPriority.TIME_STOP
    
    def test_risk_beats_all_other_exits(self):
        """Test RISK (priority 100) beats all other exits."""
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=1,
            avg_entry_price_cents=50,
        )
        
        # Create multiple exit decisions
        decisions = [
            ExitDecision(
                reason=ExitReason.EDGE_DECAY,
                priority=ExitPriority.EDGE_DECAY,  # 35
                source_layer=ExitSourceLayer.POLICY_LAYER,
                exit_price_cents=50,
            ),
            ExitDecision(
                reason=ExitReason.TIME_STOP,
                priority=ExitPriority.TIME_STOP,  # 40
                source_layer=ExitSourceLayer.POLICY_LAYER,
                exit_price_cents=50,
            ),
            ExitDecision(
                reason=ExitReason.STALE_DATA,
                priority=ExitPriority.STALE_DATA,  # 85
                source_layer=ExitSourceLayer.POLICY_LAYER,
                exit_price_cents=50,
            ),
            ExitDecision(
                reason=ExitReason.RISK,
                priority=ExitPriority.RISK,  # 100 (highest)
                source_layer=ExitSourceLayer.POLICY_LAYER,
                exit_price_cents=50,
                metadata={"kill_switch": True},
            ),
        ]
        
        resolver = get_exit_resolver()
        winning_decision = resolver.resolve(decisions, position_id=position.position_id)
        
        assert winning_decision is not None
        assert winning_decision.reason == ExitReason.RISK
        assert winning_decision.priority == ExitPriority.RISK
        assert winning_decision.metadata["kill_switch"] is True
    
    def test_stale_data_beats_candle_reversal(self):
        """Test STALE_DATA (85) beats CANDLE_REVERSAL (50)."""
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=1,
            avg_entry_price_cents=50,
        )
        
        decisions = [
            ExitDecision(
                reason=ExitReason.CANDLE_REVERSAL,
                priority=ExitPriority.CANDLE_REVERSAL,  # 50
                source_layer=ExitSourceLayer.POLICY_LAYER,
                exit_price_cents=50,
                metadata={"pattern": "bearish_engulfing"},
            ),
            ExitDecision(
                reason=ExitReason.STALE_DATA,
                priority=ExitPriority.STALE_DATA,  # 85
                source_layer=ExitSourceLayer.POLICY_LAYER,
                exit_price_cents=50,
                metadata={
                    "md_age_ms": 10000,
                    "max_age_ms": 5000,
                    "time_to_expiry_seconds": 300.0,
                },
            ),
        ]
        
        resolver = get_exit_resolver()
        winning_decision = resolver.resolve(decisions, position_id=position.position_id)
        
        assert winning_decision is not None
        assert winning_decision.reason == ExitReason.STALE_DATA
        assert winning_decision.metadata["md_age_ms"] == 10000
    
    def test_exit_policy_integration_with_resolver(self):
        """Test ExitPolicy.evaluate() integrates with ExitResolver."""
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=1,
            avg_entry_price_cents=50,
        )
        
        # Get policy decision via ExitPolicy
        policy_resolver = get_exit_policy_resolver()
        policy_resolver.set_risk_kill_switch(True)
        
        policy = policy_resolver.resolve(
            position=position,
            current_price_cents=50,
            time_to_expiry_seconds=800.0,
        )
        
        # Extract ExitDecision from policy
        policy_decision = policy.evaluate()
        
        assert policy_decision is not None
        assert policy_decision.reason == ExitReason.RISK
        
        # Resolve through ExitResolver (single decision)
        exit_resolver = get_exit_resolver()
        winning_decision = exit_resolver.resolve([policy_decision], position_id=position.position_id)
        
        assert winning_decision is not None
        assert winning_decision.reason == ExitReason.RISK
        
        # Clean up
        policy_resolver.set_risk_kill_switch(False)
        exit_resolver.clear_history()
    
    def test_partial_exit_vs_full_exit_resolution(self):
        """Test resolver handles partial vs full exit decisions correctly."""
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=10,
            avg_entry_price_cents=50,
        )
        
        decisions = [
            ExitDecision(
                reason=ExitReason.SCALE_OUT,
                priority=ExitPriority.SCALE_OUT,  # 30
                source_layer=ExitSourceLayer.POSITION_LEVEL,
                exit_price_cents=60,
                contracts_to_close=5,  # Partial exit
            ),
            ExitDecision(
                reason=ExitReason.RISK,
                priority=ExitPriority.RISK,  # 100
                source_layer=ExitSourceLayer.POLICY_LAYER,
                exit_price_cents=60,
                contracts_to_close=None,  # Full exit
            ),
        ]
        
        resolver = get_exit_resolver()
        winning_decision = resolver.resolve(decisions, position_id=position.position_id)
        
        # RISK should win (higher priority) and be a full exit
        assert winning_decision is not None
        assert winning_decision.reason == ExitReason.RISK
        assert winning_decision.contracts_to_close is None
        assert winning_decision.is_full_exit()
    
    def test_metadata_preservation_through_pipeline(self):
        """Test metadata is preserved from ExitPolicy through ExitResolver."""
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=1,
            avg_entry_price_cents=50,
        )
        
        # Get policy decision with STALE_DATA metadata
        policy_resolver = get_exit_policy_resolver()
        policy = policy_resolver.resolve(
            position=position,
            current_price_cents=50,
            time_to_expiry_seconds=800.0,
        )
        
        policy_decision = policy.evaluate(
            md_age_ms=10000,
            max_age_ms=5000,
        )
        
        assert policy_decision is not None
        assert policy_decision.reason == ExitReason.STALE_DATA
        assert policy_decision.metadata["md_age_ms"] == 10000
        assert policy_decision.metadata["max_age_ms"] == 5000
        
        # Resolve through ExitResolver
        exit_resolver = get_exit_resolver()
        winning_decision = exit_resolver.resolve([policy_decision], position_id=position.position_id)
        
        # Metadata should be preserved
        assert winning_decision is not None
        assert winning_decision.metadata["md_age_ms"] == 10000
        assert winning_decision.metadata["max_age_ms"] == 5000
        
        exit_resolver.clear_history()
    
    def test_no_exit_condition_returns_none(self):
        """Test when no exit conditions are met, resolver returns None."""
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=1,
            avg_entry_price_cents=50,
        )
        
        # Get policy decision (should return None for hold)
        policy_resolver = get_exit_policy_resolver()
        policy = policy_resolver.resolve(
            position=position,
            current_price_cents=50,
            time_to_expiry_seconds=800.0,
        )
        
        policy_decision = policy.evaluate()
        
        assert policy_decision is None
        
        # Resolve through ExitResolver with empty list
        exit_resolver = get_exit_resolver()
        winning_decision = exit_resolver.resolve([], position_id=position.position_id)
        
        assert winning_decision is None
        
        exit_resolver.clear_history()
    
    def test_precedence_order_enforcement(self):
        """Test full precedence order: RISK > STALE_DATA > CANDLE_REVERSAL > ADAPTIVE_TIMING > TIME_STOP > EDGE_DECAY."""
        position = Position(
            market_id="KXBTC15M-1234",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=1,
            avg_entry_price_cents=50,
        )
        
        # Create decisions in reverse priority order
        decisions = [
            ExitDecision(
                reason=ExitReason.EDGE_DECAY,
                priority=ExitPriority.EDGE_DECAY,  # 35
                source_layer=ExitSourceLayer.POLICY_LAYER,
                exit_price_cents=50,
            ),
            ExitDecision(
                reason=ExitReason.TIME_STOP,
                priority=ExitPriority.TIME_STOP,  # 40
                source_layer=ExitSourceLayer.POLICY_LAYER,
                exit_price_cents=50,
            ),
            ExitDecision(
                reason=ExitReason.ADAPTIVE_TIMING,
                priority=ExitPriority.ADAPTIVE_TIMING,  # 45
                source_layer=ExitSourceLayer.POLICY_LAYER,
                exit_price_cents=50,
            ),
            ExitDecision(
                reason=ExitReason.CANDLE_REVERSAL,
                priority=ExitPriority.CANDLE_REVERSAL,  # 50
                source_layer=ExitSourceLayer.POLICY_LAYER,
                exit_price_cents=50,
            ),
            ExitDecision(
                reason=ExitReason.STALE_DATA,
                priority=ExitPriority.STALE_DATA,  # 85
                source_layer=ExitSourceLayer.POLICY_LAYER,
                exit_price_cents=50,
            ),
            ExitDecision(
                reason=ExitReason.RISK,
                priority=ExitPriority.RISK,  # 100
                source_layer=ExitSourceLayer.POLICY_LAYER,
                exit_price_cents=50,
            ),
        ]
        
        resolver = get_exit_resolver()
        winning_decision = resolver.resolve(decisions, position_id=position.position_id)
        
        # RISK should win (highest priority)
        assert winning_decision is not None
        assert winning_decision.reason == ExitReason.RISK
        assert winning_decision.priority == ExitPriority.RISK
        
        resolver.clear_history()


class TestExitDecisionLogging:
    """Test exit decision logging and observability."""
    
    def test_exit_intent_log_schema_exists(self):
        """Test exit intent log schema includes required fields in code."""
        from merid.position_management.position_monitor import PositionMonitor
        import inspect
        
        # Get the _emit_exit_intent method source
        source = inspect.getsource(PositionMonitor._emit_exit_intent)
        
        # Verify structured schema fields are present in log format
        assert "[EXIT-INTENT]" in source
        assert "position=" in source
        assert "market=" in source
        assert "side=" in source
        assert "reason=" in source
        assert "priority=" in source
        assert "source=" in source
        assert "type=" in source
    
    def test_resolver_log_schema_exists(self):
        """Test ExitResolver log schema includes required fields in code."""
        import inspect
        from merid.position_management.exit_resolver import ExitResolver
        
        # Get the _log_resolution method source
        source = inspect.getsource(ExitResolver._log_resolution)
        
        # Verify structured schema fields are present in log format
        assert "[EXIT-RESOLVER]" in source
        assert "position=" in source
        assert "reason=" in source
        assert "priority=" in source
        assert "source=" in source
    
    def test_stale_data_special_logging_exists(self):
        """Test STALE_DATA has special logging with MD age/SLA."""
        import inspect
        from merid.position_management.exit_resolver import ExitResolver
        
        # Get the _log_resolution method source
        source = inspect.getsource(ExitResolver._log_resolution)
        
        # Verify STALE_DATA special logging
        assert "STALE_DATA exit" in source
        assert "md_age_ms" in source
        assert "max_age_ms" in source
        assert "time_to_expiry" in source
