"""
Tests for reconciliation_invariants.py

Pure unit tests with synthetic inputs, no I/O, fully deterministic.
"""

import pytest
from datetime import datetime

from merid.validation.reconciliation_invariants import (
    ReconciliationInvariantChecker,
    ReconciliationViolation,
    ReconciliationCheckResult,
    Episode,
    check_episode_conservation,
    check_pnl_calculation,
    check_orphan_detection,
    check_edge_attribution,
    generate_synthetic_reconciliation_test_cases,
)


class TestReconciliationInvariants:
    """Test suite for reconciliation invariants."""
    
    @pytest.fixture
    def checker(self):
        """Fixture for ReconciliationInvariantChecker."""
        return ReconciliationInvariantChecker(
            max_leverage=1.0,
            min_balance_usd=0.0,
        )
    
    @pytest.fixture
    def valid_episode(self):
        """Fixture for a valid episode."""
        return Episode(
            episode_id="test_episode_001",
            signals={"asset": "BTC", "timestamp": 1234567890},
            selected_contract={"ticker": "KXBTC15M-26JUL211730-30", "strike": 65000},
            risk_decision={"max_size": 1, "notional": 0.50},
            orders=[
                {"order_id": "order_001", "side": "yes", "action": "buy", "count": 1}
            ],
            fills=[
                {"fill_id": "fill_001", "order_id": "order_001", "side": "yes", "action": "buy", "count": 1, "price_cents": 50}
            ],
            realized_pnl_usd=0.10,
            edge_attribution={"strategy_edge_usd": 0.15, "execution_slippage_usd": 0.05},
        )
    
    def test_position_size_matches_fills(self, checker, valid_episode):
        """
        Build episode with two buy fills and one sell; assert net position equals sum.
        """
        # Valid case: single buy fill, net position = 1
        result = checker.check_episode_conservation(
            episode=valid_episode,
            net_position_size=1,
        )
        assert result.is_valid
        
        # Test with multiple fills
        episode_multi_fills = Episode(
            episode_id="test_episode_002",
            signals={},
            selected_contract={},
            risk_decision={},
            orders=[
                {"order_id": "order_001", "side": "yes", "action": "buy", "count": 1},
                {"order_id": "order_002", "side": "yes", "action": "buy", "count": 1},
                {"order_id": "order_003", "side": "yes", "action": "sell", "count": 1},
            ],
            fills=[
                {"fill_id": "fill_001", "order_id": "order_001", "side": "yes", "action": "buy", "count": 1, "price_cents": 50},
                {"fill_id": "fill_002", "order_id": "order_002", "side": "yes", "action": "buy", "count": 1, "price_cents": 50},
                {"fill_id": "fill_003", "order_id": "order_003", "side": "yes", "action": "sell", "count": 1, "price_cents": 60},
            ],
            realized_pnl_usd=0.10,
            edge_attribution={},
        )
        
        result = checker.check_episode_conservation(
            episode=episode_multi_fills,
            net_position_size=1,  # 1 + 1 - 1 = 1
        )
        assert result.is_valid
        
        # Invalid case: position size mismatch
        result = checker.check_episode_conservation(
            episode=episode_multi_fills,
            net_position_size=2,  # Wrong: should be 1
        )
        assert not result.is_valid
        assert result.violation_type == ReconciliationViolation.POSITION_SIZE_MISMATCH
    
    def test_pnl_calculation_matches_fills_and_fees(self, checker, valid_episode):
        """
        Controlled prices and fees → exact PnL; assert no PNL_CALCULATION_MISMATCH.
        """
        # Valid case: PnL = (60 - 50) * 1 - 0.02 = 0.10 - 0.02 = 0.08
        result = checker.check_pnl_calculation(
            episode=valid_episode,
            entry_price_cents=50,
            exit_price_cents=60,
            position_size=1,
            fees_usd=0.02,
        )
        # The episode has realized_pnl_usd=0.10, but calculation gives 0.08
        # This should fail unless we adjust the episode's PnL
        assert not result.is_valid  # Expected to fail due to PnL mismatch
        
        # Valid case: match the PnL
        valid_episode.realized_pnl_usd = 0.08
        result = checker.check_pnl_calculation(
            episode=valid_episode,
            entry_price_cents=50,
            exit_price_cents=60,
            position_size=1,
            fees_usd=0.02,
        )
        assert result.is_valid
    
    def test_no_orphan_orders_or_fills(self, checker, valid_episode):
        """
        Create an order with no episode_id → ORPHAN_ORDER.
        A fill with unknown order_id → ORPHAN_FILL.
        """
        # Valid case: all orders and fills belong to episode
        all_orders = valid_episode.orders
        all_fills = valid_episode.fills
        
        result = checker.check_orphan_detection(
            episode=valid_episode,
            all_orders=all_orders,
            all_fills=all_fills,
        )
        assert result.is_valid
        
        # Invalid case: orphan order
        orphan_order = {"order_id": "orphan_order", "side": "yes", "action": "buy", "count": 1}
        all_orders_with_orphan = all_orders + [orphan_order]
        
        result = checker.check_orphan_detection(
            episode=valid_episode,
            all_orders=all_orders_with_orphan,
            all_fills=all_fills,
        )
        assert not result.is_valid
        assert result.violation_type == ReconciliationViolation.ORPHAN_ORDER
        
        # Invalid case: orphan fill
        orphan_fill = {"fill_id": "orphan_fill", "order_id": "unknown_order", "side": "yes", "action": "buy", "count": 1, "price_cents": 50}
        all_fills_with_orphan = all_fills + [orphan_fill]
        
        result = checker.check_orphan_detection(
            episode=valid_episode,
            all_orders=all_orders,
            all_fills=all_fills_with_orphan,
        )
        assert not result.is_valid
        assert result.violation_type == ReconciliationViolation.ORPHAN_FILL
    
    def test_no_negative_balances_or_leverage_exceeded(self, checker):
        """
        Simulate over-levered episode and assert NEGATIVE_BALANCE or LEVERAGE_EXCEEDED.
        """
        # Invalid case: negative balance
        result = checker.check_negative_balance(
            balance_usd=-10.00,
        )
        assert not result.is_valid
        assert result.violation_type == ReconciliationViolation.NEGATIVE_BALANCE
        
        # Valid case: positive balance
        result = checker.check_negative_balance(
            balance_usd=100.00,
        )
        assert result.is_valid
        
        # Invalid case: leverage exceeded
        result = checker.check_leverage_exceeded(
            notional_usd=2.00,
            balance_usd=1.00,
        )
        assert not result.is_valid
        assert result.violation_type == ReconciliationViolation.LEVERAGE_EXCEEDED
        
        # Valid case: leverage within limit
        result = checker.check_leverage_exceeded(
            notional_usd=0.50,
            balance_usd=1.00,
        )
        assert result.is_valid
    
    def test_pnl_without_position(self, checker):
        """Test that PnL without position changes is caught."""
        # Invalid case: PnL recorded but no position changes
        episode_no_position = Episode(
            episode_id="test_episode_003",
            signals={},
            selected_contract={},
            risk_decision={},
            orders=[],
            fills=[],
            realized_pnl_usd=0.10,  # PnL but no position changes
            edge_attribution={},
        )
        
        result = checker.check_pnl_without_position(
            episode=episode_no_position,
            position_changes=[],
        )
        assert not result.is_valid
        assert result.violation_type == ReconciliationViolation.PNL_WITHOUT_POSITION
        
        # Valid case: PnL with position changes
        episode_with_position = Episode(
            episode_id="test_episode_004",
            signals={},
            selected_contract={},
            risk_decision={},
            orders=[],
            fills=[],
            realized_pnl_usd=0.10,
            edge_attribution={},
        )
        
        result = checker.check_pnl_without_position(
            episode=episode_with_position,
            position_changes=[{"ticker": "KXBTC15M-26JUL211730-30", "delta": 1}],
        )
        assert result.is_valid
    
    def test_edge_attribution(self, checker, valid_episode):
        """Test edge attribution invariant."""
        # Valid case: PnL = edge - slippage
        valid_episode.realized_pnl_usd = 0.10  # 0.15 - 0.05 = 0.10
        result = checker.check_edge_attribution(
            episode=valid_episode,
            strategy_edge_usd=0.15,
            execution_slippage_usd=0.05,
        )
        assert result.is_valid
        
        # Invalid case: edge attribution mismatch
        valid_episode.realized_pnl_usd = 0.20  # Wrong: should be 0.10
        result = checker.check_edge_attribution(
            episode=valid_episode,
            strategy_edge_usd=0.15,
            execution_slippage_usd=0.05,
        )
        assert not result.is_valid
        assert result.violation_type == ReconciliationViolation.EDGE_ATTRIBUTION_MISMATCH
    
    def test_episode_id_integrity(self, checker):
        """Test episode ID integrity."""
        # Invalid case: missing episode_id
        episode_no_id = Episode(
            episode_id="",
            signals={},
            selected_contract={},
            risk_decision={},
            orders=[],
            fills=[],
            realized_pnl_usd=0.0,
            edge_attribution={},
        )
        
        result = checker.check_episode_id_integrity(episode_no_id)
        assert not result.is_valid
        assert result.violation_type == ReconciliationViolation.EPISODE_ID_MISSING
        
        # Valid case: episode_id present
        episode_with_id = Episode(
            episode_id="test_episode_005",
            signals={},
            selected_contract={},
            risk_decision={},
            orders=[],
            fills=[],
            realized_pnl_usd=0.0,
            edge_attribution={},
        )
        
        result = checker.check_episode_id_integrity(episode_with_id)
        assert result.is_valid
    
    def test_check_all_invariants(self, checker, valid_episode):
        """Test running all reconciliation invariants together."""
        # Adjust episode PnL to match both checks:
        # PnL calculation: (exit - entry) * size - fees = (60 - 50) * 1 - 0.00 = 0.10
        # Edge attribution: edge - slippage = 0.15 - 0.05 = 0.10
        valid_episode.realized_pnl_usd = 0.10
        
        # Add exit fill to episode
        valid_episode.fills.append(
            {"fill_id": "fill_002", "order_id": "order_001", "side": "yes", "action": "sell", "count": 1, "price_cents": 60}
        )
        
        results = checker.check_all_invariants(
            episode=valid_episode,
            net_position_size=0,  # Net position after entry and exit is 0
            entry_price_cents=50,
            exit_price_cents=60,
            position_size=1,
            fees_usd=0.00,  # Set fees to 0 to align both checks
            all_orders=valid_episode.orders,
            all_fills=valid_episode.fills,
            position_changes=[{"ticker": "KXBTC15M-26JUL211730-30", "delta": 1}],
            balance_usd=100.00,
            notional_usd=0.50,
            strategy_edge_usd=0.15,
            execution_slippage_usd=0.05,
        )
        
        assert len(results) == 8  # Eight invariants checked
        assert all(r.is_valid for r in results)


class TestConvenienceFunctions:
    """Test convenience functions for direct use."""
    
    def test_check_episode_conservation(self):
        """Test convenience function for episode conservation."""
        episode = Episode(
            episode_id="test_episode",
            signals={},
            selected_contract={},
            risk_decision={},
            orders=[{"order_id": "order_001", "side": "yes", "action": "buy", "count": 1}],
            fills=[{"fill_id": "fill_001", "order_id": "order_001", "side": "yes", "action": "buy", "count": 1, "price_cents": 50}],
            realized_pnl_usd=0.0,
            edge_attribution={},
        )
        
        result = check_episode_conservation(episode, net_position_size=1)
        assert result.is_valid
    
    def test_check_pnl_calculation(self):
        """Test convenience function for PnL calculation."""
        episode = Episode(
            episode_id="test_episode",
            signals={},
            selected_contract={},
            risk_decision={},
            orders=[],
            fills=[],
            realized_pnl_usd=0.08,
            edge_attribution={},
        )
        
        result = check_pnl_calculation(
            episode,
            entry_price_cents=50,
            exit_price_cents=60,
            position_size=1,
            fees_usd=0.02,
        )
        assert result.is_valid
    
    def test_check_orphan_detection(self):
        """Test convenience function for orphan detection."""
        episode = Episode(
            episode_id="test_episode",
            signals={},
            selected_contract={},
            risk_decision={},
            orders=[{"order_id": "order_001", "side": "yes", "action": "buy", "count": 1}],
            fills=[{"fill_id": "fill_001", "order_id": "order_001", "side": "yes", "action": "buy", "count": 1, "price_cents": 50}],
            realized_pnl_usd=0.0,
            edge_attribution={},
        )
        
        result = check_orphan_detection(
            episode,
            all_orders=episode.orders,
            all_fills=episode.fills,
        )
        assert result.is_valid
    
    def test_check_edge_attribution(self):
        """Test convenience function for edge attribution."""
        episode = Episode(
            episode_id="test_episode",
            signals={},
            selected_contract={},
            risk_decision={},
            orders=[],
            fills=[],
            realized_pnl_usd=0.10,
            edge_attribution={},
        )
        
        result = check_edge_attribution(
            episode,
            strategy_edge_usd=0.15,
            execution_slippage_usd=0.05,
        )
        assert result.is_valid


class TestSyntheticTestCases:
    """Test synthetic test case generator."""
    
    def test_generate_synthetic_reconciliation_test_cases(self):
        """Test that synthetic test cases are generated correctly."""
        test_cases = generate_synthetic_reconciliation_test_cases()
        
        assert len(test_cases) > 0
        assert all("episode" in tc for tc in test_cases)
        assert all("net_position_size" in tc for tc in test_cases)
        assert all("entry_price_cents" in tc for tc in test_cases)
        assert all("exit_price_cents" in tc for tc in test_cases)
        assert all("expected_valid" in tc for tc in test_cases)
    
    def test_synthetic_test_cases_valid_and_invalid(self):
        """Test that synthetic test cases include both valid and invalid cases."""
        test_cases = generate_synthetic_reconciliation_test_cases()
        
        valid_cases = [tc for tc in test_cases if tc["expected_valid"]]
        invalid_cases = [tc for tc in test_cases if not tc["expected_valid"]]
        
        assert len(valid_cases) > 0
        assert len(invalid_cases) > 0


class TestReconciliationCheckResult:
    """Test ReconciliationCheckResult dataclass."""
    
    def test_to_dict(self):
        """Test conversion to dictionary."""
        result = ReconciliationCheckResult(
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
        result = ReconciliationCheckResult(
            is_valid=False,
            violation_type=ReconciliationViolation.POSITION_SIZE_MISMATCH,
            message="Test violation",
            context={},
        )
        
        result_dict = result.to_dict()
        assert result_dict["is_valid"] is False
        assert result_dict["violation_type"] == "position_size_mismatch"


class TestEpisode:
    """Test Episode dataclass."""
    
    def test_to_dict(self):
        """Test conversion to dictionary."""
        episode = Episode(
            episode_id="test_episode",
            signals={"asset": "BTC"},
            selected_contract={"ticker": "KXBTC15M-26JUL211730-30"},
            risk_decision={"max_size": 1},
            orders=[],
            fills=[],
            realized_pnl_usd=0.10,
            edge_attribution={"strategy_edge_usd": 0.15},
        )
        
        episode_dict = episode.to_dict()
        assert episode_dict["episode_id"] == "test_episode"
        assert episode_dict["signals"] == {"asset": "BTC"}
        assert episode_dict["realized_pnl_usd"] == 0.10
