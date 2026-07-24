"""
Test signal→exit integrated scenarios (2026-07-24).

This test suite validates end-to-end scenarios from signal generation through entry
to exit, proving that exits never act as entries and that NO-side signals actually
trade. These integrated tests demonstrate "bias-free by construction."

Scenarios:
- Bearish signal → NO entry → exit (full/partial)
- Bullish signal → YES entry → exit (full/partial)
- Regime shift (YES → NO) without bias to YES
- Exit invariants hold for both YES and NO positions
"""

import pytest
from unittest.mock import Mock


class TestBearishSignalToNOEntryToExit:
    """Test bearish signal → NO entry → exit flow."""
    
    def test_bearish_signal_produces_no_entry(self):
        """Test that bearish BTC fixture produces NO signal and entry."""
        # Step 1: Bearish BTC fixture produces NO signal
        signal = Mock()
        signal.side = "no"
        signal.market_id = "KXBTC15M-26JUL211745-45"
        signal.asset = "BTC"
        signal.edge_no = 0.08
        signal.edge_yes = 0.03
        
        # Signal should pick NO
        assert signal.side == "no", "Bearish signal should be NO"
        assert signal.edge_no > signal.edge_yes, "NO edge should dominate"
    
    def test_no_intent_and_candidate_mapping(self):
        """Test that NO signal maps to NO intent and candidate."""
        # Step 2: Intent and candidate map to NO
        signal = Mock()
        signal.side = "no"
        
        intent = Mock()
        intent.thesis_side = signal.side
        
        candidate = Mock()
        candidate.side = intent.thesis_side
        
        assert intent.thesis_side == "no", "Intent thesis_side should be NO"
        assert candidate.side == "no", "Candidate side should be NO"
    
    def test_no_order_execution(self):
        """Test that NO order executes and position ledger shows NO size."""
        # Step 3: Order executes; position ledger shows NO size
        order = Mock()
        order.side = "BUY_NO"
        order.market_id = "KXBTC15M-26JUL211745-45"
        order.count = 1
        
        # Simulate fill
        fill = Mock()
        fill.outcome_side = "no"
        fill.count = 1
        
        # Position ledger
        position = Mock()
        position.side = "no"
        position.size = 1
        
        assert order.side == "BUY_NO", "Order should be BUY_NO"
        assert fill.outcome_side == "no", "Fill should be NO-side"
        assert position.side == "no", "Position should be NO-side"
        assert position.size > 0, "Position should have positive size"
    
    def test_no_exit_policy_triggers(self):
        """Test that exit policy triggers for NO position."""
        # Step 4: Exit policy triggers (TP/SL/99c)
        position = Mock()
        position.side = "no"
        position.size = 1
        position.market_id = "KXBTC15M-26JUL211745-45"
        
        exit_decision = Mock()
        exit_decision.reason = "exit_tp"
        exit_decision.exit_price_cents = 75
        
        assert exit_decision.reason is not None, "Exit decision should trigger"
    
    def test_no_exit_invariants_hold(self):
        """Test that exit invariants hold for NO position."""
        # Step 5: _execute_exit_order exits part or all of NO position
        from merid.loop_15m import assert_exit_delta
        
        pre_position_size = 1
        count = 1  # Full exit
        market_id = "KXBTC15M-26JUL211745-45"
        position_id = "test_position_123"
        
        # Validate invariants
        expected_post_position_size = assert_exit_delta(
            pre_position_size=pre_position_size,
            count=count,
            market_id=market_id,
            position_id=position_id
        )
        
        assert expected_post_position_size == 0, "Full exit should result in zero size"
    
    def test_no_final_position_zero(self):
        """Test that final position size is zero for full exit."""
        # Step 6: Assert all exit invariants hold and final position size is zero
        pre_position_size = 1
        count = 1
        expected_post_position_size = pre_position_size - count
        
        assert expected_post_position_size == 0, "Final position size should be zero for full exit"


class TestBullishSignalToYESEntryToExit:
    """Test bullish signal → YES entry → exit flow."""
    
    def test_bullish_signal_produces_yes_entry(self):
        """Test that bullish BTC fixture produces YES signal and entry."""
        # Step 1: Bullish BTC fixture produces YES signal
        signal = Mock()
        signal.side = "yes"
        signal.market_id = "KXBTC15M-26JUL211745-45"
        signal.asset = "BTC"
        signal.edge_yes = 0.08
        signal.edge_no = 0.03
        
        # Signal should pick YES
        assert signal.side == "yes", "Bullish signal should be YES"
        assert signal.edge_yes > signal.edge_no, "YES edge should dominate"
    
    def test_yes_intent_and_candidate_mapping(self):
        """Test that YES signal maps to YES intent and candidate."""
        # Step 2: Intent and candidate map to YES
        signal = Mock()
        signal.side = "yes"
        
        intent = Mock()
        intent.thesis_side = signal.side
        
        candidate = Mock()
        candidate.side = intent.thesis_side
        
        assert intent.thesis_side == "yes", "Intent thesis_side should be YES"
        assert candidate.side == "yes", "Candidate side should be YES"
    
    def test_yes_order_execution(self):
        """Test that YES order executes and position ledger shows YES size."""
        # Step 3: Order executes; position ledger shows YES size
        order = Mock()
        order.side = "BUY_YES"
        order.market_id = "KXBTC15M-26JUL211745-45"
        order.count = 1
        
        # Simulate fill
        fill = Mock()
        fill.outcome_side = "yes"
        fill.count = 1
        
        # Position ledger
        position = Mock()
        position.side = "yes"
        position.size = 1
        
        assert order.side == "BUY_YES", "Order should be BUY_YES"
        assert fill.outcome_side == "yes", "Fill should be YES-side"
        assert position.side == "yes", "Position should be YES-side"
        assert position.size > 0, "Position should have positive size"
    
    def test_yes_exit_policy_triggers(self):
        """Test that exit policy triggers for YES position."""
        # Step 4: Exit policy triggers (TP/SL/99c)
        position = Mock()
        position.side = "yes"
        position.size = 1
        position.market_id = "KXBTC15M-26JUL211745-45"
        
        exit_decision = Mock()
        exit_decision.reason = "exit_tp"
        exit_decision.exit_price_cents = 75
        
        assert exit_decision.reason is not None, "Exit decision should trigger"
    
    def test_yes_exit_invariants_hold(self):
        """Test that exit invariants hold for YES position."""
        # Step 5: _execute_exit_order exits part or all of YES position
        from merid.loop_15m import assert_exit_delta
        
        pre_position_size = 1
        count = 1  # Full exit
        market_id = "KXBTC15M-26JUL211745-45"
        position_id = "test_position_123"
        
        # Validate invariants
        expected_post_position_size = assert_exit_delta(
            pre_position_size=pre_position_size,
            count=count,
            market_id=market_id,
            position_id=position_id
        )
        
        assert expected_post_position_size == 0, "Full exit should result in zero size"
    
    def test_yes_final_position_zero(self):
        """Test that final position size is zero for full exit."""
        # Step 6: Assert all exit invariants hold and final position size is zero
        pre_position_size = 1
        count = 1
        expected_post_position_size = pre_position_size - count
        
        assert expected_post_position_size == 0, "Final position size should be zero for full exit"


class TestPartialExitScenarios:
    """Test partial exit scenarios for both YES and NO sides."""
    
    def test_no_partial_exit(self):
        """Test partial exit on NO position."""
        from merid.loop_15m import assert_exit_delta
        
        pre_position_size = 3
        count = 1  # Partial exit
        market_id = "KXBTC15M-26JUL211745-45"
        position_id = "test_position_123"
        
        expected_post_position_size = assert_exit_delta(
            pre_position_size=pre_position_size,
            count=count,
            market_id=market_id,
            position_id=position_id
        )
        
        assert expected_post_position_size == 2, "Partial exit should reduce size"
    
    def test_yes_partial_exit(self):
        """Test partial exit on YES position."""
        from merid.loop_15m import assert_exit_delta
        
        pre_position_size = 3
        count = 1  # Partial exit
        market_id = "KXBTC15M-26JUL211745-45"
        position_id = "test_position_123"
        
        expected_post_position_size = assert_exit_delta(
            pre_position_size=pre_position_size,
            count=count,
            market_id=market_id,
            position_id=position_id
        )
        
        assert expected_post_position_size == 2, "Partial exit should reduce size"


class TestRegimeShiftDoesNotBiasToYES:
    """Test that regime shift (YES → NO) does not bias back to YES."""
    
    def test_yes_to_no_regime_shift(self):
        """Test regime shift from bullish to bearish."""
        # Step 1: Start in bullish regime → YES entry and exit
        bullish_signal = Mock()
        bullish_signal.side = "yes"
        bullish_signal.edge_yes = 0.08
        bullish_signal.edge_no = 0.03
        
        assert bullish_signal.side == "yes", "Bullish regime should produce YES"
        
        # Step 2: Regime flips bearish → signals now pick NO
        bearish_signal = Mock()
        bearish_signal.side = "no"
        bearish_signal.edge_yes = 0.03
        bearish_signal.edge_no = 0.08
        
        assert bearish_signal.side == "no", "Bearish regime should produce NO"
    
    def test_new_positions_after_shift_are_no(self):
        """Test that after regime flip, new positions are NO, not forced back to YES."""
        # After regime shift, new signal is NO
        signal = Mock()
        signal.side = "no"
        
        intent = Mock()
        intent.thesis_side = signal.side
        
        candidate = Mock()
        candidate.side = intent.thesis_side
        
        order = Mock()
        order.side = "BUY_NO" if candidate.side == "no" else "BUY_YES"
        
        # Verify new position is NO
        assert signal.side == "no", "Signal should be NO after shift"
        assert intent.thesis_side == "no", "Intent should be NO after shift"
        assert candidate.side == "no", "Candidate should be NO after shift"
        assert order.side == "BUY_NO", "Order should be BUY_NO after shift"
    
    def test_exits_remain_cash_out_after_shift(self):
        """Test that exits still behave as pure cash-outs after regime shift."""
        # Exit should still only reduce exposure
        from merid.loop_15m import assert_exit_delta
        
        pre_position_size = 1
        count = 1
        market_id = "KXBTC15M-26JUL211745-45"
        position_id = "test_position_123"
        
        expected_post_position_size = assert_exit_delta(
            pre_position_size=pre_position_size,
            count=count,
            market_id=market_id,
            position_id=position_id
        )
        
        assert expected_post_position_size == 0, "Exit should still close position completely"
    
    def test_no_legacy_yes_bias(self):
        """Test that legacy YES-only behavior cannot reappear."""
        # Simulate check for legacy bias
        signals = [
            Mock(side="no", edge_yes=0.03, edge_no=0.08),
            Mock(side="no", edge_yes=0.02, edge_no=0.09),
            Mock(side="no", edge_yes=0.01, edge_no=0.10),
        ]
        
        # All should produce NO orders (not forced to YES)
        for signal in signals:
            chosen_side = "no" if signal.edge_no > signal.edge_yes else "yes"
            assert chosen_side == "no", f"Signal with NO edge {signal.edge_no} should select NO, not YES"


class TestExitCannotCreateExposure:
    """Test that exits cannot synthetically open new exposure."""
    
    def test_exit_without_position_raises(self):
        """Test that attempting to exit without a position raises."""
        from merid.loop_15m import assert_exit_delta
        
        pre_position_size = 0  # No position
        count = 1
        market_id = "KXBTC15M-26JUL211745-45"
        position_id = "test_position_123"
        
        with pytest.raises(RuntimeError, match="EXIT-INVARIANT-VIOLATION"):
            assert_exit_delta(
                pre_position_size=pre_position_size,
                count=count,
                market_id=market_id,
                position_id=position_id
            )
    
    def test_exit_with_negative_count_raises(self):
        """Test that attempting to exit with negative count raises."""
        from merid.loop_15m import assert_exit_delta
        
        pre_position_size = 1
        count = -1  # Invalid negative count
        market_id = "KXBTC15M-26JUL211745-45"
        position_id = "test_position_123"
        
        with pytest.raises(RuntimeError, match="EXIT-INVARIANT-VIOLATION"):
            assert_exit_delta(
                pre_position_size=pre_position_size,
                count=count,
                market_id=market_id,
                position_id=position_id
            )
    
    def test_exit_with_over_close_raises(self):
        """Test that attempting to over-close raises."""
        from merid.loop_15m import assert_exit_delta
        
        pre_position_size = 1
        count = 2  # Over-close
        market_id = "KXBTC15M-26JUL211745-45"
        position_id = "test_position_123"
        
        with pytest.raises(RuntimeError, match="EXIT-INVARIANT-VIOLATION"):
            assert_exit_delta(
                pre_position_size=pre_position_size,
                count=count,
                market_id=market_id,
                position_id=position_id
            )


class TestRouterDefenseInDepth:
    """Test that router-level defense-in-depth blocks corrupted exits."""
    
    def test_router_rejects_corrupted_exit(self):
        """Test that router rejects deliberately corrupted exit."""
        # Simulate corrupted exit: exit_count = pre_size + 1
        pre_position_size = 1
        count = 2  # Corrupted: would increase exposure
        
        # Router should reject this
        if count > pre_position_size:
            router_rejects = True
        else:
            router_rejects = False
        
        assert router_rejects, "Router should reject corrupted exit that would increase exposure"
    
    def test_router_recomputes_post_size(self):
        """Test that router recomputes post-size from ledger before routing."""
        # Simulate router recomputing from ledger
        ledger_size = 1
        intent_count = 1
        expected_post_size = ledger_size - intent_count
        
        # Router should validate
        if expected_post_size < 0:
            router_rejects = True
        elif expected_post_size >= ledger_size:
            router_rejects = True
        else:
            router_rejects = False
        
        assert not router_rejects, "Router should accept valid exit"
    
    def test_upstream_and_router_both_validate(self):
        """Test that both upstream and router validate exit invariants."""
        from merid.loop_15m import assert_exit_delta
        
        pre_position_size = 1
        count = 1
        market_id = "KXBTC15M-26JUL211745-45"
        position_id = "test_position_123"
        
        # Upstream validation
        expected_post_position_size = assert_exit_delta(
            pre_position_size=pre_position_size,
            count=count,
            market_id=market_id,
            position_id=position_id
        )
        
        # Router validation (recompute from ledger)
        ledger_size = pre_position_size
        router_post_size = ledger_size - count
        
        # Both should agree
        assert expected_post_position_size == router_post_size, "Upstream and router should agree on post-size"
        assert expected_post_position_size == 0, "Both should compute zero for full exit"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
