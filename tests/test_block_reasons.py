"""Tests for canonical BlockReason enum and structured logging."""

import pytest
from datetime import datetime, timezone

from merid.guards.block_reasons import (
    BlockReason,
    OrderStage,
    BlockEvent,
    log_block_event,
    is_canonical_block_reason,
    get_block_reason_category,
    CANONICAL_BLOCK_REASONS,
    CANONICAL_STAGES,
)


class TestBlockReasonEnum:
    """Test BlockReason enum completeness and categorization."""
    
    def test_all_reasons_have_categories(self):
        """Every BlockReason should map to a valid category."""
        for reason in BlockReason:
            category = get_block_reason_category(reason)
            assert category in [
                "RISK_LIMITS", "STRATEGY_FILTERS", "VENUE_CONSTRAINTS",
                "SYSTEM_STATE", "DATA_INTEGRITY", "INTERNAL_ERROR", "UNKNOWN"
            ]
    
    def test_risk_limit_reasons_exist(self):
        """Critical risk limit reasons should be defined."""
        assert BlockReason.BANKROLL_CAP in BlockReason
        assert BlockReason.DAILY_LOSS_LIMIT in BlockReason
        assert BlockReason.POSITION_LIMIT in BlockReason
        assert BlockReason.DRAWDOWN_GUARD in BlockReason
    
    def test_strategy_filter_reasons_exist(self):
        """Strategy filter reasons should be defined."""
        assert BlockReason.MIN_EDGE_THRESHOLD in BlockReason
        assert BlockReason.MIN_CONFIDENCE_THRESHOLD in BlockReason
        assert BlockReason.MARKET_REGIME_GATE in BlockReason
    
    def test_venue_constraint_reasons_exist(self):
        """Venue constraint reasons should be defined."""
        assert BlockReason.MARKET_CLOSED in BlockReason
        assert BlockReason.INVALID_TICKER in BlockReason
        assert BlockReason.DEEP_OTM_REJECT in BlockReason
        assert BlockReason.DEEP_ITM_REJECT in BlockReason
    
    def test_system_state_reasons_exist(self):
        """System state reasons should be defined."""
        assert BlockReason.KILL_SWITCH in BlockReason
        assert BlockReason.TRADING_MODE_GATE in BlockReason
        assert BlockReason.EXECUTION_GATE_BLOCKED in BlockReason
    
    def test_data_integrity_reasons_exist(self):
        """Data integrity reasons should be defined."""
        assert BlockReason.MISSING_PRICE in BlockReason
        assert BlockReason.STALE_PRICE in BlockReason
        assert BlockReason.INVALID_ORDER_PARAMS in BlockReason


class TestOrderStageEnum:
    """Test OrderStage enum completeness."""
    
    def test_all_stages_defined(self):
        """All expected lifecycle stages should be defined."""
        expected_stages = [
            "signal_generation",
            "signal_to_intent",
            "strategy_filter",
            "risk_gate",
            "execution_gate",
            "pre_trade_gate",
            "router_validation",
            "venue_submission",
        ]
        for stage in expected_stages:
            assert stage in CANONICAL_STAGES
    
    def test_stage_ordering_is_logical(self):
        """Stages should follow logical order from signal to venue."""
        stage_list = list(OrderStage)
        # Signal stages come first
        assert OrderStage.SIGNAL_GENERATION in stage_list
        assert OrderStage.SIGNAL_TO_INTENT in stage_list
        # Risk/execution gates in middle
        assert OrderStage.STRATEGY_FILTER in stage_list
        assert OrderStage.RISK_GATE in stage_list
        assert OrderStage.EXECUTION_GATE in stage_list
        # Final stages last
        assert OrderStage.PRE_TRADE_GATE in stage_list
        assert OrderStage.ROUTER_VALIDATION in stage_list
        assert OrderStage.VENUE_SUBMISSION in stage_list


class TestBlockEvent:
    """Test BlockEvent dataclass serialization."""
    
    def test_block_event_creation(self):
        """BlockEvent should create with all fields."""
        event = BlockEvent(
            order_id="test-order-1",
            stage=OrderStage.RISK_GATE,
            reason=BlockReason.BANKROLL_CAP,
            asset="BTC",
            timeframe="15m",
            side="yes",
            action="buy",
            edge_pct=0.05,
            confidence=0.75,
        )
        
        assert event.order_id == "test-order-1"
        assert event.stage == OrderStage.RISK_GATE
        assert event.reason == BlockReason.BANKROLL_CAP
        assert event.asset == "BTC"
        assert event.timeframe == "15m"
        assert event.edge_pct == 0.05
        assert event.confidence == 0.75
    
    def test_block_event_to_dict(self):
        """BlockEvent should serialize to dict correctly."""
        event = BlockEvent(
            order_id="test-order-1",
            stage=OrderStage.RISK_GATE,
            reason=BlockReason.BANKROLL_CAP,
            asset="BTC",
            details={"current_bankroll": 1000, "required": 1500},
        )
        
        d = event.to_dict()
        
        assert d["order_id"] == "test-order-1"
        assert d["stage"] == "risk_gate"
        assert d["reason"] == "bankroll_cap"
        assert d["asset"] == "BTC"
        assert d["details"]["current_bankroll"] == 1000
        assert isinstance(d["timestamp"], float)


class TestLogBlockEvent:
    """Test log_block_event function."""
    
    def test_log_block_event_creates_event(self):
        """log_block_event should return a BlockEvent."""
        event = log_block_event(
            order_id="test-order-1",
            stage=OrderStage.RISK_GATE,
            reason=BlockReason.BANKROLL_CAP,
            asset="BTC",
            edge_pct=0.05,
            details={"test": "data"},
        )
        
        assert isinstance(event, BlockEvent)
        assert event.order_id == "test-order-1"
        assert event.stage == OrderStage.RISK_GATE
        assert event.reason == BlockReason.BANKROLL_CAP
    
    def test_log_block_event_handles_optional_params(self):
        """log_block_event should handle missing optional params gracefully."""
        event = log_block_event(
            order_id="test-order-2",
            stage=OrderStage.STRATEGY_FILTER,
            reason=BlockReason.MIN_EDGE_THRESHOLD,
        )
        
        assert event.order_id == "test-order-2"
        assert event.asset == ""
        assert event.edge_pct is None
        assert event.details == {}


class TestValidationHelpers:
    """Test validation helper functions."""
    
    def test_is_canonical_block_reason_valid(self):
        """Valid canonical reasons should return True."""
        assert is_canonical_block_reason("bankroll_cap")
        assert is_canonical_block_reason("daily_loss_limit")
        assert is_canonical_block_reason("kill_switch")
    
    def test_is_canonical_block_reason_invalid(self):
        """Invalid reasons should return False."""
        assert not is_canonical_block_reason("random_reason")
        assert not is_canonical_block_reason("legacy_block")
        assert not is_canonical_block_reason("")
    
    def test_get_block_reason_category_risk_limits(self):
        """Risk limit reasons should map to RISK_LIMITS category."""
        assert get_block_reason_category(BlockReason.BANKROLL_CAP) == "RISK_LIMITS"
        assert get_block_reason_category(BlockReason.DAILY_LOSS_LIMIT) == "RISK_LIMITS"
        assert get_block_reason_category(BlockReason.POSITION_LIMIT) == "RISK_LIMITS"
    
    def test_get_block_reason_category_strategy_filters(self):
        """Strategy filter reasons should map to STRATEGY_FILTERS category."""
        assert get_block_reason_category(BlockReason.MIN_EDGE_THRESHOLD) == "STRATEGY_FILTERS"
        assert get_block_reason_category(BlockReason.MIN_CONFIDENCE_THRESHOLD) == "STRATEGY_FILTERS"
    
    def test_get_block_reason_category_venue_constraints(self):
        """Venue constraint reasons should map to VENUE_CONSTRAINTS category."""
        assert get_block_reason_category(BlockReason.MARKET_CLOSED) == "VENUE_CONSTRAINTS"
        assert get_block_reason_category(BlockReason.INVALID_TICKER) == "VENUE_CONSTRAINTS"
    
    def test_get_block_reason_category_system_state(self):
        """System state reasons should map to SYSTEM_STATE category."""
        assert get_block_reason_category(BlockReason.KILL_SWITCH) == "SYSTEM_STATE"
        assert get_block_reason_category(BlockReason.EXECUTION_GATE_BLOCKED) == "SYSTEM_STATE"
    
    def test_get_block_reason_category_data_integrity(self):
        """Data integrity reasons should map to DATA_INTEGRITY category."""
        assert get_block_reason_category(BlockReason.MISSING_PRICE) == "DATA_INTEGRITY"
        assert get_block_reason_category(BlockReason.STALE_PRICE) == "DATA_INTEGRITY"


class TestCanonicalConstants:
    """Test CANONICAL_* constants are correct."""
    
    def test_canonical_block_reasons_set(self):
        """CANONICAL_BLOCK_REASONS should contain all BlockReason values."""
        for reason in BlockReason:
            assert reason.value in CANONICAL_BLOCK_REASONS
    
    def test_canonical_stages_set(self):
        """CANONICAL_STAGES should contain all OrderStage values."""
        for stage in OrderStage:
            assert stage.value in CANONICAL_STAGES


class TestIntegrationScenarios:
    """Integration tests for common blocking scenarios."""
    
    def test_bankroll_cap_block(self):
        """Test bankroll cap blocking scenario."""
        event = log_block_event(
            order_id="order-1",
            stage=OrderStage.RISK_GATE,
            reason=BlockReason.BANKROLL_CAP,
            asset="BTC",
            timeframe="15m",
            details={
                "current_bankroll_usd": 1000.0,
                "required_bankroll_usd": 1500.0,
            },
        )
        
        assert event.reason == BlockReason.BANKROLL_CAP
        assert event.stage == OrderStage.RISK_GATE
        assert get_block_reason_category(event.reason) == "RISK_LIMITS"
    
    def test_min_edge_threshold_block(self):
        """Test minimum edge threshold blocking scenario."""
        event = log_block_event(
            order_id="order-2",
            stage=OrderStage.STRATEGY_FILTER,
            reason=BlockReason.MIN_EDGE_THRESHOLD,
            asset="ETH",
            timeframe="1h",
            edge_pct=0.015,  # Below threshold
            confidence=0.80,
            details={"threshold": 0.02},
        )
        
        assert event.reason == BlockReason.MIN_EDGE_THRESHOLD
        assert event.stage == OrderStage.STRATEGY_FILTER
        assert get_block_reason_category(event.reason) == "STRATEGY_FILTERS"
    
    def test_kill_switch_block(self):
        """Test kill switch blocking scenario."""
        event = log_block_event(
            order_id="order-3",
            stage=OrderStage.EXECUTION_GATE,
            reason=BlockReason.KILL_SWITCH,
            details={"trigger_reason": "manual_operator"},
        )
        
        assert event.reason == BlockReason.KILL_SWITCH
        assert event.stage == OrderStage.EXECUTION_GATE
        assert get_block_reason_category(event.reason) == "SYSTEM_STATE"
    
    def test_invalid_ticker_block(self):
        """Test invalid ticker blocking scenario."""
        event = log_block_event(
            order_id="order-4",
            stage=OrderStage.ROUTER_VALIDATION,
            reason=BlockReason.INVALID_TICKER,
            asset="UNKNOWN",
            details={"ticker": "INVALID-TICKER"},
        )
        
        assert event.reason == BlockReason.INVALID_TICKER
        assert event.stage == OrderStage.ROUTER_VALIDATION
        assert get_block_reason_category(event.reason) == "VENUE_CONSTRAINTS"
    
    def test_missing_price_block(self):
        """Test missing price blocking scenario."""
        event = log_block_event(
            order_id="order-5",
            stage=OrderStage.SIGNAL_GENERATION,
            reason=BlockReason.MISSING_PRICE,
            asset="SOL",
            details={"source": "coinbase", "last_update": "never"},
        )
        
        assert event.reason == BlockReason.MISSING_PRICE
        assert event.stage == OrderStage.SIGNAL_GENERATION
        assert get_block_reason_category(event.reason) == "DATA_INTEGRITY"
