"""
Tests for model_execution_audit_invariants.py

Pure unit tests with synthetic inputs, no I/O, fully deterministic.
"""

import pytest
from datetime import datetime
from unittest.mock import MagicMock

from merid.validation.model_execution_audit_invariants import (
    ModelExecutionAuditChecker,
    AuditViolation,
    AuditCheckResult,
    ModelDecision,
    ExecutionRecord,
    check_model_vs_execution_consistency,
    detect_phantom_trades,
    replay_historical_data,
    generate_synthetic_audit_test_cases,
)


class TestModelExecutionAuditInvariants:
    """Test suite for model vs execution audit invariants."""
    
    @pytest.fixture
    def checker(self):
        """Fixture for ModelExecutionAuditChecker."""
        return ModelExecutionAuditChecker(
            min_edge_threshold=0.01,
            max_spread_cents=30,
            min_volume=10,
        )
    
    @pytest.fixture
    def valid_model_decision(self):
        """Fixture for a valid model decision."""
        return ModelDecision(
            timestamp=datetime(2026, 7, 23, 10, 0, 0),
            contract_ticker="KXBTC15M-26JUL211730-30",
            model_edge=0.15,
            model_probability=0.65,
            market_conditions={"volatility": 0.02, "volume": 50, "spread_cents": 5},
            should_trade=True,
            reason_for_suppression=None,
        )
    
    @pytest.fixture
    def valid_execution_record(self):
        """Fixture for a valid execution record."""
        return ExecutionRecord(
            timestamp=datetime(2026, 7, 23, 10, 0, 5),
            contract_ticker="KXBTC15M-26JUL211730-30",
            order_submitted=True,
            order_filled=True,
            fill_price_cents=50,
            fill_count=1,
            rejection_reason=None,
        )
    
    def test_missing_trade_detected_when_edge_and_filters_ok(self, checker, valid_model_decision):
        """
        Model says "trade"; execution is empty; expect MISSING_TRADE.
        """
        # Invalid case: model says trade but no execution record
        result = checker.check_model_vs_execution_consistency(
            model_decision=valid_model_decision,
            execution_record=None,
        )
        assert not result.is_valid
        assert result.violation_type == AuditViolation.MISSING_TRADE
        
        # Valid case: model says trade and execution exists
        result = checker.check_model_vs_execution_consistency(
            model_decision=valid_model_decision,
            execution_record=ExecutionRecord(
                timestamp=datetime(2026, 7, 23, 10, 0, 5),
                contract_ticker="KXBTC15M-26JUL211730-30",
                order_submitted=True,
                order_filled=True,
                fill_price_cents=50,
                fill_count=1,
            ),
        )
        assert result.is_valid
    
    def test_phantom_trade_detected_when_edge_below_threshold(self, checker):
        """
        Execution trade exist; model had edge<threshold or filters disallowed; expect PHANTOM_TRADE.
        """
        # Invalid case: model says no trade but execution exists
        model_decision = ModelDecision(
            timestamp=datetime(2026, 7, 23, 10, 0, 0),
            contract_ticker="KXBTC15M-26JUL211730-30",
            model_edge=0.005,  # Below threshold
            model_probability=0.51,
            market_conditions={"volatility": 0.02, "volume": 50, "spread_cents": 5},
            should_trade=False,
            reason_for_suppression=None,
        )
        
        execution_record = ExecutionRecord(
            timestamp=datetime(2026, 7, 23, 10, 0, 5),
            contract_ticker="KXBTC15M-26JUL211730-30",
            order_submitted=True,
            order_filled=True,
            fill_price_cents=50,
            fill_count=1,
        )
        
        result = checker.check_model_vs_execution_consistency(
            model_decision=model_decision,
            execution_record=execution_record,
        )
        assert not result.is_valid
        assert result.violation_type == AuditViolation.PHANTOM_TRADE
    
    def test_order_not_submitted_without_suppression_reason(self, checker, valid_model_decision):
        """Test that order not submitted requires suppression reason."""
        # Invalid case: model says trade but order not submitted without reason
        execution_record = ExecutionRecord(
            timestamp=datetime(2026, 7, 23, 10, 0, 5),
            contract_ticker="KXBTC15M-26JUL211730-30",
            order_submitted=False,
            order_filled=False,
            fill_price_cents=None,
            fill_count=0,
            rejection_reason=None,  # No reason
        )
        
        result = checker.check_model_vs_execution_consistency(
            model_decision=valid_model_decision,
            execution_record=execution_record,
        )
        assert not result.is_valid
        assert result.violation_type == AuditViolation.MISSING_TRADE
        
        # Valid case: order not submitted with suppression reason
        execution_record.rejection_reason = "Risk cap reached"
        
        result = checker.check_model_vs_execution_consistency(
            model_decision=valid_model_decision,
            execution_record=execution_record,
        )
        assert result.is_valid
    
    def test_detect_phantom_trades(self, checker):
        """Test phantom trade detection across multiple decisions."""
        model_decisions = [
            ModelDecision(
                timestamp=datetime(2026, 7, 23, 10, 0, 0),
                contract_ticker="KXBTC15M-26JUL211730-30",
                model_edge=0.005,
                model_probability=0.51,
                market_conditions={},
                should_trade=False,
            ),
        ]
        
        execution_records = [
            ExecutionRecord(
                timestamp=datetime(2026, 7, 23, 10, 0, 5),
                contract_ticker="KXBTC15M-26JUL211730-30",
                order_submitted=True,
                order_filled=True,
                fill_price_cents=50,
                fill_count=1,
            ),
        ]
        
        results = checker.detect_phantom_trades(model_decisions, execution_records)
        assert len(results) == 1
        assert results[0].violation_type == AuditViolation.PHANTOM_TRADE
    
    def test_stale_config_and_broken_risk_control_detection(self, checker):
        """
        Provide mismatched config snapshots, assert STALE_CONFIG or BROKEN_RISK_CONTROL.
        """
        # Invalid case: config mismatch
        model_config = {"min_edge_threshold": 0.01, "max_spread_cents": 30}
        execution_config = {"min_edge_threshold": 0.02, "max_spread_cents": 30}  # Mismatch
        
        result = checker.check_stale_config(model_config, execution_config)
        assert not result.is_valid
        assert result.violation_type == AuditViolation.STALE_CONFIG
        
        # Valid case: config matches
        execution_config = {"min_edge_threshold": 0.01, "max_spread_cents": 30}
        
        result = checker.check_stale_config(model_config, execution_config)
        assert result.is_valid
    
    def test_broken_risk_control(self, checker):
        """Test broken risk control detection."""
        # Invalid case: trade exceeded risk limits
        execution_record = ExecutionRecord(
            timestamp=datetime(2026, 7, 23, 10, 0, 5),
            contract_ticker="KXBTC15M-26JUL211730-30",
            order_submitted=True,
            order_filled=True,
            fill_price_cents=50,
            fill_count=2,  # Exceeds max_contracts=1
        )
        
        risk_limits = {"max_notional_usd": 1.00, "max_contracts": 1}
        
        result = checker.check_broken_risk_control(execution_record, risk_limits)
        assert not result.is_valid
        assert result.violation_type == AuditViolation.BROKEN_RISK_CONTROL
        
        # Valid case: trade within risk limits
        execution_record.fill_count = 1
        
        result = checker.check_broken_risk_control(execution_record, risk_limits)
        assert result.is_valid
    
    def test_replay_historical_data(self, checker):
        """Test offline replay of historical data."""
        historical_data = [
            {
                "timestamp": datetime(2026, 7, 23, 10, 0, 0),
                "ticker": "KXBTC15M-26JUL211730-30",
                "market_conditions": {"volatility": 0.02, "volume": 50, "spread_cents": 5},
            }
        ]
        
        def mock_model_function(snapshot):
            return {
                "edge": 0.15,
                "probability": 0.65,
                "should_trade": True,
                "suppression_reason": None,
            }
        
        risk_filters = {
            "max_volatility": 0.05,
            "min_volume": 10,
            "max_spread_cents": 30,
        }
        
        model_decisions, audit_results = checker.replay_historical_data(
            historical_data, mock_model_function, risk_filters
        )
        
        assert len(model_decisions) == 1
        assert model_decisions[0].should_trade is True
        assert len(audit_results) == 0  # No violations
    
    def test_replay_historical_data_with_filter_mismatch(self, checker):
        """Test replay with filter mismatch."""
        historical_data = [
            {
                "timestamp": datetime(2026, 7, 23, 10, 0, 0),
                "ticker": "KXBTC15M-26JUL211730-30",
                "market_conditions": {"volatility": 0.10, "volume": 5, "spread_cents": 5},  # High vol, low volume
            }
        ]
        
        def mock_model_function(snapshot):
            return {
                "edge": 0.15,
                "probability": 0.65,
                "should_trade": True,  # Model says trade despite bad conditions
                "suppression_reason": None,  # No suppression reason
            }
        
        risk_filters = {
            "max_volatility": 0.05,
            "min_volume": 10,
            "max_spread_cents": 30,
        }
        
        model_decisions, audit_results = checker.replay_historical_data(
            historical_data, mock_model_function, risk_filters
        )
        
        assert len(model_decisions) == 1
        assert len(audit_results) > 0  # Should have filter mismatch violation
        assert audit_results[0].violation_type == AuditViolation.FILTER_MISMATCH


class TestConvenienceFunctions:
    """Test convenience functions for direct use."""
    
    def test_check_model_vs_execution_consistency(self):
        """Test convenience function for model vs execution consistency."""
        model_decision = ModelDecision(
            timestamp=datetime(2026, 7, 23, 10, 0, 0),
            contract_ticker="KXBTC15M-26JUL211730-30",
            model_edge=0.15,
            model_probability=0.65,
            market_conditions={},
            should_trade=True,
        )
        
        execution_record = ExecutionRecord(
            timestamp=datetime(2026, 7, 23, 10, 0, 5),
            contract_ticker="KXBTC15M-26JUL211730-30",
            order_submitted=True,
            order_filled=True,
            fill_price_cents=50,
            fill_count=1,
        )
        
        result = check_model_vs_execution_consistency(model_decision, execution_record)
        assert result.is_valid
    
    def test_detect_phantom_trades(self):
        """Test convenience function for phantom trade detection."""
        model_decisions = [
            ModelDecision(
                timestamp=datetime(2026, 7, 23, 10, 0, 0),
                contract_ticker="KXBTC15M-26JUL211730-30",
                model_edge=0.15,
                model_probability=0.65,
                market_conditions={},
                should_trade=True,
            ),
        ]
        
        execution_records = [
            ExecutionRecord(
                timestamp=datetime(2026, 7, 23, 10, 0, 5),
                contract_ticker="KXBTC15M-26JUL211730-30",
                order_submitted=True,
                order_filled=True,
                fill_price_cents=50,
                fill_count=1,
            ),
        ]
        
        results = detect_phantom_trades(model_decisions, execution_records)
        assert len(results) == 0  # No phantom trades
    
    def test_replay_historical_data(self):
        """Test convenience function for historical data replay."""
        historical_data = [
            {
                "timestamp": datetime(2026, 7, 23, 10, 0, 0),
                "ticker": "KXBTC15M-26JUL211730-30",
                "market_conditions": {"volatility": 0.02, "volume": 50, "spread_cents": 5},
            }
        ]
        
        def mock_model_function(snapshot):
            return {
                "edge": 0.15,
                "probability": 0.65,
                "should_trade": True,
                "suppression_reason": None,
            }
        
        risk_filters = {
            "max_volatility": 0.05,
            "min_volume": 10,
            "max_spread_cents": 30,
        }
        
        model_decisions, audit_results = replay_historical_data(
            historical_data, mock_model_function, risk_filters
        )
        
        assert len(model_decisions) == 1


class TestSyntheticTestCases:
    """Test synthetic test case generator."""
    
    def test_generate_synthetic_audit_test_cases(self):
        """Test that synthetic test cases are generated correctly."""
        test_cases = generate_synthetic_audit_test_cases()
        
        assert len(test_cases) > 0
        assert all("model_decision" in tc for tc in test_cases)
        assert all("execution_record" in tc for tc in test_cases)
        assert all("expected_valid" in tc for tc in test_cases)
    
    def test_synthetic_test_cases_valid_and_invalid(self):
        """Test that synthetic test cases include both valid and invalid cases."""
        test_cases = generate_synthetic_audit_test_cases()
        
        valid_cases = [tc for tc in test_cases if tc["expected_valid"]]
        invalid_cases = [tc for tc in test_cases if not tc["expected_valid"]]
        
        assert len(valid_cases) > 0
        assert len(invalid_cases) > 0


class TestAuditCheckResult:
    """Test AuditCheckResult dataclass."""
    
    def test_to_dict(self):
        """Test conversion to dictionary."""
        result = AuditCheckResult(
            is_valid=True,
            violation_type=None,
            message="Test message",
            context={"key": "value"},
        )
        
        result_dict = result.to_dict()
        assert result_dict["is_valid"] is True
        assert result_dict["violation_type"] is None
        assert result_dict["message"] == "Test message"
        assert result_dict["context"] == {"key": "value"}
    
    def test_to_dict_with_violation(self):
        """Test conversion to dictionary with violation."""
        result = AuditCheckResult(
            is_valid=False,
            violation_type=AuditViolation.MISSING_TRADE,
            message="Test violation",
            context={},
        )
        
        result_dict = result.to_dict()
        assert result_dict["is_valid"] is False
        assert result_dict["violation_type"] == "missing_trade"


class TestModelDecision:
    """Test ModelDecision dataclass."""
    
    def test_model_decision_creation(self):
        """Test ModelDecision creation."""
        decision = ModelDecision(
            timestamp=datetime(2026, 7, 23, 10, 0, 0),
            contract_ticker="KXBTC15M-26JUL211730-30",
            model_edge=0.15,
            model_probability=0.65,
            market_conditions={"volatility": 0.02},
            should_trade=True,
        )
        
        assert decision.contract_ticker == "KXBTC15M-26JUL211730-30"
        assert decision.model_edge == 0.15
        assert decision.should_trade is True


class TestExecutionRecord:
    """Test ExecutionRecord dataclass."""
    
    def test_execution_record_creation(self):
        """Test ExecutionRecord creation."""
        record = ExecutionRecord(
            timestamp=datetime(2026, 7, 23, 10, 0, 5),
            contract_ticker="KXBTC15M-26JUL211730-30",
            order_submitted=True,
            order_filled=True,
            fill_price_cents=50,
            fill_count=1,
        )
        
        assert record.contract_ticker == "KXBTC15M-26JUL211730-30"
        assert record.order_submitted is True
        assert record.fill_price_cents == 50
