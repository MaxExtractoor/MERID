"""Tests for Yes/No Parity Checker."""

import pytest
from merid.validation.yes_no_parity_checker import (
    YesNoParityChecker,
    MarketSnapshot,
    BotView,
    ExecutionDecision,
    ExposureIntent,
    IntendedAction,
    ParityMetrics,
    get_parity_checker,
    get_parity_metrics,
    reset_parity_metrics,
)


class TestYesNoParityChecker:
    """Test YesNoParityChecker functionality."""
    
    def test_probability_parity_pass(self):
        """Test probability parity check passes when prob_no ≈ 1 - prob_yes."""
        checker = YesNoParityChecker(prob_eps=1e-3)
        
        m = MarketSnapshot(
            market_id="BTC-15M-UP-20260719-1400",
            asset="BTC",
            expiry_ts=1721409600,
            yes_bid=0.45,
            yes_ask=0.47,
            no_bid=0.53,
            no_ask=0.55,
        )
        
        v = BotView(
            model_prob_yes=0.45,
            model_prob_no=0.55,  # 1 - 0.45 = 0.55
            edge_yes=0.05,
            edge_no=0.03,
            chosen_side="yes",
            exposure_intent=ExposureIntent.BULLISH_EVENT,
        )
        
        d = ExecutionDecision(
            intended_action=IntendedAction.BUY_YES,
            api_side="yes",
            api_yes_price=0.45,
            api_no_price=None,
        )
        
        result = checker.check(m, v, d)
        assert result.ok, f"Expected pass but got reasons: {result.reasons}"
    
    def test_probability_parity_fail(self):
        """Test probability parity check fails when prob_no != 1 - prob_yes."""
        checker = YesNoParityChecker(prob_eps=1e-3)
        
        m = MarketSnapshot(
            market_id="BTC-15M-UP-20260719-1400",
            asset="BTC",
            expiry_ts=1721409600,
            yes_bid=0.45,
            yes_ask=0.47,
            no_bid=0.53,
            no_ask=0.55,
        )
        
        v = BotView(
            model_prob_yes=0.45,
            model_prob_no=0.60,  # 1 - 0.45 = 0.55, but we have 0.60
            edge_yes=0.05,
            edge_no=0.03,
            chosen_side="yes",
            exposure_intent=ExposureIntent.BULLISH_EVENT,
        )
        
        d = ExecutionDecision(
            intended_action=IntendedAction.BUY_YES,
            api_side="yes",
            api_yes_price=0.45,
            api_no_price=None,
        )
        
        result = checker.check(m, v, d)
        assert not result.ok
        assert any("PROB_MISMATCH" in reason for reason in result.reasons)
    
    def test_edge_winner_parity_pass(self):
        """Test edge winner parity check passes when chosen side has higher edge."""
        checker = YesNoParityChecker(edge_eps=1e-3)
        
        m = MarketSnapshot(
            market_id="BTC-15M-UP-20260719-1400",
            asset="BTC",
            expiry_ts=1721409600,
            yes_bid=0.45,
            yes_ask=0.47,
            no_bid=0.53,
            no_ask=0.55,
        )
        
        v = BotView(
            model_prob_yes=0.45,
            model_prob_no=0.55,
            edge_yes=0.07,  # Higher than edge_no
            edge_no=0.03,
            chosen_side="yes",
            exposure_intent=ExposureIntent.BULLISH_EVENT,
        )
        
        d = ExecutionDecision(
            intended_action=IntendedAction.BUY_YES,
            api_side="yes",
            api_yes_price=0.45,
            api_no_price=None,
        )
        
        result = checker.check(m, v, d)
        assert result.ok, f"Expected pass but got reasons: {result.reasons}"
    
    def test_edge_winner_parity_fail(self):
        """Test edge winner parity check fails when chosen side has lower edge."""
        checker = YesNoParityChecker(edge_eps=1e-3)
        
        m = MarketSnapshot(
            market_id="BTC-15M-UP-20260719-1400",
            asset="BTC",
            expiry_ts=1721409600,
            yes_bid=0.45,
            yes_ask=0.47,
            no_bid=0.53,
            no_ask=0.55,
        )
        
        v = BotView(
            model_prob_yes=0.45,
            model_prob_no=0.55,
            edge_yes=0.03,  # Lower than edge_no
            edge_no=0.07,
            chosen_side="yes",  # Chose YES but NO has higher edge
            exposure_intent=ExposureIntent.BULLISH_EVENT,
        )
        
        d = ExecutionDecision(
            intended_action=IntendedAction.BUY_YES,
            api_side="yes",
            api_yes_price=0.45,
            api_no_price=None,
        )
        
        result = checker.check(m, v, d)
        assert not result.ok
        assert any("WINNER_MISMATCH" in reason for reason in result.reasons)
    
    def test_exposure_action_parity_bullish_pass(self):
        """Test exposure vs action parity passes for bullish intent with BUY_YES."""
        checker = YesNoParityChecker()
        
        m = MarketSnapshot(
            market_id="BTC-15M-UP-20260719-1400",
            asset="BTC",
            expiry_ts=1721409600,
            yes_bid=0.45,
            yes_ask=0.47,
            no_bid=0.53,
            no_ask=0.55,
        )
        
        v = BotView(
            model_prob_yes=0.45,
            model_prob_no=0.55,
            edge_yes=0.05,
            edge_no=0.03,
            chosen_side="yes",
            exposure_intent=ExposureIntent.BULLISH_EVENT,
        )
        
        d = ExecutionDecision(
            intended_action=IntendedAction.BUY_YES,  # Valid for bullish
            api_side="yes",
            api_yes_price=0.45,
            api_no_price=None,
        )
        
        result = checker.check(m, v, d)
        assert result.ok, f"Expected pass but got reasons: {result.reasons}"
    
    def test_exposure_action_parity_bullish_fail(self):
        """Test exposure vs action parity fails for bullish intent with SELL_YES (should be SELL_NO)."""
        checker = YesNoParityChecker()
        
        m = MarketSnapshot(
            market_id="BTC-15M-UP-20260719-1400",
            asset="BTC",
            expiry_ts=1721409600,
            yes_bid=0.45,
            yes_ask=0.47,
            no_bid=0.53,
            no_ask=0.55,
        )
        
        v = BotView(
            model_prob_yes=0.45,
            model_prob_no=0.55,
            edge_yes=0.05,
            edge_no=0.03,
            chosen_side="yes",
            exposure_intent=ExposureIntent.BULLISH_EVENT,
        )
        
        d = ExecutionDecision(
            intended_action=IntendedAction.SELL_YES,  # Invalid for bullish (should be SELL_NO)
            api_side="yes",
            api_yes_price=0.45,
            api_no_price=None,
        )
        
        result = checker.check(m, v, d)
        assert not result.ok
        assert any("INTENT_ACTION_CONFLICT" in reason for reason in result.reasons)
    
    def test_exposure_action_parity_bearish_pass(self):
        """Test exposure vs action parity passes for bearish intent with BUY_NO."""
        checker = YesNoParityChecker()
        
        m = MarketSnapshot(
            market_id="BTC-15M-UP-20260719-1400",
            asset="BTC",
            expiry_ts=1721409600,
            yes_bid=0.45,
            yes_ask=0.47,
            no_bid=0.53,
            no_ask=0.55,
        )
        
        v = BotView(
            model_prob_yes=0.45,
            model_prob_no=0.55,
            edge_yes=0.03,
            edge_no=0.05,
            chosen_side="no",
            exposure_intent=ExposureIntent.BEARISH_EVENT,
        )
        
        d = ExecutionDecision(
            intended_action=IntendedAction.BUY_NO,  # Valid for bearish
            api_side="no",
            api_yes_price=None,
            api_no_price=0.55,
        )
        
        result = checker.check(m, v, d)
        assert result.ok, f"Expected pass but got reasons: {result.reasons}"
    
    def test_exposure_action_parity_bearish_fail(self):
        """Test exposure vs action parity fails for bearish intent with BUY_YES (should be SELL_YES)."""
        checker = YesNoParityChecker()
        
        m = MarketSnapshot(
            market_id="BTC-15M-UP-20260719-1400",
            asset="BTC",
            expiry_ts=1721409600,
            yes_bid=0.45,
            yes_ask=0.47,
            no_bid=0.53,
            no_ask=0.55,
        )
        
        v = BotView(
            model_prob_yes=0.45,
            model_prob_no=0.55,
            edge_yes=0.03,
            edge_no=0.05,
            chosen_side="no",
            exposure_intent=ExposureIntent.BEARISH_EVENT,
        )
        
        d = ExecutionDecision(
            intended_action=IntendedAction.BUY_YES,  # Invalid for bearish (should be SELL_YES)
            api_side="yes",
            api_yes_price=0.45,
            api_no_price=None,
        )
        
        result = checker.check(m, v, d)
        assert not result.ok
        assert any("INTENT_ACTION_CONFLICT" in reason for reason in result.reasons)
    
    def test_api_side_price_mapping_buy_yes_pass(self):
        """Test API side/price mapping passes for BUY_YES."""
        checker = YesNoParityChecker()
        
        m = MarketSnapshot(
            market_id="BTC-15M-UP-20260719-1400",
            asset="BTC",
            expiry_ts=1721409600,
            yes_bid=0.45,
            yes_ask=0.47,
            no_bid=0.53,
            no_ask=0.55,
        )
        
        v = BotView(
            model_prob_yes=0.45,
            model_prob_no=0.55,
            edge_yes=0.05,
            edge_no=0.03,
            chosen_side="yes",
            exposure_intent=ExposureIntent.BULLISH_EVENT,
        )
        
        d = ExecutionDecision(
            intended_action=IntendedAction.BUY_YES,
            api_side="yes",  # Correct
            api_yes_price=0.45,  # Present
            api_no_price=None,
        )
        
        result = checker.check(m, v, d)
        assert result.ok, f"Expected pass but got reasons: {result.reasons}"
    
    def test_api_side_price_mapping_buy_yes_fail(self):
        """Test API side/price mapping fails for BUY_YES with wrong side."""
        checker = YesNoParityChecker()
        
        m = MarketSnapshot(
            market_id="BTC-15M-UP-20260719-1400",
            asset="BTC",
            expiry_ts=1721409600,
            yes_bid=0.45,
            yes_ask=0.47,
            no_bid=0.53,
            no_ask=0.55,
        )
        
        v = BotView(
            model_prob_yes=0.45,
            model_prob_no=0.55,
            edge_yes=0.05,
            edge_no=0.03,
            chosen_side="yes",
            exposure_intent=ExposureIntent.BULLISH_EVENT,
        )
        
        d = ExecutionDecision(
            intended_action=IntendedAction.BUY_YES,
            api_side="no",  # Wrong side
            api_yes_price=0.45,
            api_no_price=None,
        )
        
        result = checker.check(m, v, d)
        assert not result.ok
        assert any("API_MISMATCH" in reason for reason in result.reasons)
    
    def test_api_side_price_mapping_buy_no_pass(self):
        """Test API side/price mapping passes for BUY_NO."""
        checker = YesNoParityChecker()
        
        m = MarketSnapshot(
            market_id="BTC-15M-UP-20260719-1400",
            asset="BTC",
            expiry_ts=1721409600,
            yes_bid=0.45,
            yes_ask=0.47,
            no_bid=0.53,
            no_ask=0.55,
        )
        
        v = BotView(
            model_prob_yes=0.45,
            model_prob_no=0.55,
            edge_yes=0.03,
            edge_no=0.05,
            chosen_side="no",
            exposure_intent=ExposureIntent.BEARISH_EVENT,
        )
        
        d = ExecutionDecision(
            intended_action=IntendedAction.BUY_NO,
            api_side="no",  # Correct
            api_yes_price=None,
            api_no_price=0.55,  # Present
        )
        
        result = checker.check(m, v, d)
        assert result.ok, f"Expected pass but got reasons: {result.reasons}"
    
    def test_symmetric_evaluation_pass(self):
        """Test symmetric evaluation check passes when both edges are present."""
        checker = YesNoParityChecker()
        
        m = MarketSnapshot(
            market_id="BTC-15M-UP-20260719-1400",
            asset="BTC",
            expiry_ts=1721409600,
            yes_bid=0.45,
            yes_ask=0.47,
            no_bid=0.53,
            no_ask=0.55,
        )
        
        v = BotView(
            model_prob_yes=0.45,
            model_prob_no=0.55,
            edge_yes=0.05,  # Present
            edge_no=0.03,  # Present
            chosen_side="yes",
            exposure_intent=ExposureIntent.BULLISH_EVENT,
        )
        
        d = ExecutionDecision(
            intended_action=IntendedAction.BUY_YES,
            api_side="yes",
            api_yes_price=0.45,
            api_no_price=None,
        )
        
        result = checker.check(m, v, d)
        assert result.ok, f"Expected pass but got reasons: {result.reasons}"
    
    def test_symmetric_evaluation_fail(self):
        """Test symmetric evaluation check fails when one edge is None."""
        checker = YesNoParityChecker()
        
        m = MarketSnapshot(
            market_id="BTC-15M-UP-20260719-1400",
            asset="BTC",
            expiry_ts=1721409600,
            yes_bid=0.45,
            yes_ask=0.47,
            no_bid=0.53,
            no_ask=0.55,
        )
        
        v = BotView(
            model_prob_yes=0.45,
            model_prob_no=0.55,
            edge_yes=0.05,  # Present
            edge_no=None,  # Missing
            chosen_side="yes",
            exposure_intent=ExposureIntent.BULLISH_EVENT,
        )
        
        d = ExecutionDecision(
            intended_action=IntendedAction.BUY_YES,
            api_side="yes",
            api_yes_price=0.45,
            api_no_price=None,
        )
        
        result = checker.check(m, v, d)
        assert not result.ok
        assert any("MISSING_SIDE" in reason for reason in result.reasons)
    
    def test_kalshi_equivalence_buy_yes_sell_no(self):
        """Test that BUY_YES and SELL_NO are both valid for bullish intent per Kalshi semantics."""
        checker = YesNoParityChecker()
        
        m = MarketSnapshot(
            market_id="BTC-15M-UP-20260719-1400",
            asset="BTC",
            expiry_ts=1721409600,
            yes_bid=0.45,
            yes_ask=0.47,
            no_bid=0.53,
            no_ask=0.55,
        )
        
        v = BotView(
            model_prob_yes=0.45,
            model_prob_no=0.55,
            edge_yes=0.05,
            edge_no=0.03,
            chosen_side="yes",
            exposure_intent=ExposureIntent.BULLISH_EVENT,
        )
        
        # BUY_YES should pass
        d1 = ExecutionDecision(
            intended_action=IntendedAction.BUY_YES,
            api_side="yes",
            api_yes_price=0.45,
            api_no_price=None,
        )
        result1 = checker.check(m, v, d1)
        assert result1.ok, f"BUY_YES should pass but got: {result1.reasons}"
        
        # SELL_NO should also pass (economically equivalent per Kalshi semantics)
        d2 = ExecutionDecision(
            intended_action=IntendedAction.SELL_NO,
            api_side="no",
            api_yes_price=None,
            api_no_price=0.55,
        )
        result2 = checker.check(m, v, d2)
        assert result2.ok, f"SELL_NO should pass (Kalshi equivalence) but got: {result2.reasons}"
    
    def test_kalshi_equivalence_buy_no_sell_yes(self):
        """Test that BUY_NO and SELL_YES are both valid for bearish intent per Kalshi semantics."""
        checker = YesNoParityChecker()
        
        m = MarketSnapshot(
            market_id="BTC-15M-UP-20260719-1400",
            asset="BTC",
            expiry_ts=1721409600,
            yes_bid=0.45,
            yes_ask=0.47,
            no_bid=0.53,
            no_ask=0.55,
        )
        
        v = BotView(
            model_prob_yes=0.45,
            model_prob_no=0.55,
            edge_yes=0.03,
            edge_no=0.05,
            chosen_side="no",
            exposure_intent=ExposureIntent.BEARISH_EVENT,
        )
        
        # BUY_NO should pass
        d1 = ExecutionDecision(
            intended_action=IntendedAction.BUY_NO,
            api_side="no",
            api_yes_price=None,
            api_no_price=0.55,
        )
        result1 = checker.check(m, v, d1)
        assert result1.ok, f"BUY_NO should pass but got: {result1.reasons}"
        
        # SELL_YES should also pass (economically equivalent per Kalshi semantics)
        d2 = ExecutionDecision(
            intended_action=IntendedAction.SELL_YES,
            api_side="yes",
            api_yes_price=0.45,
            api_no_price=None,
        )
        result2 = checker.check(m, v, d2)
        assert result2.ok, f"SELL_YES should pass (Kalshi equivalence) but got: {result2.reasons}"


class TestParityMetrics:
    """Test ParityMetrics functionality."""
    
    def test_reset(self):
        """Test metrics reset."""
        metrics = ParityMetrics()
        metrics.record_evaluated()
        metrics.record_traded()
        metrics.reset()
        
        assert metrics.total_markets_evaluated == 0
        assert metrics.total_markets_traded == 0
        assert metrics.parity_checks_failed == 0
    
    def test_record_evaluated(self):
        """Test recording evaluated markets."""
        metrics = ParityMetrics()
        metrics.record_evaluated()
        metrics.record_evaluated()
        
        assert metrics.total_markets_evaluated == 2
    
    def test_record_traded(self):
        """Test recording traded markets."""
        metrics = ParityMetrics()
        metrics.record_traded()
        metrics.record_traded()
        
        assert metrics.total_markets_traded == 2
    
    def test_record_failure(self):
        """Test recording failures."""
        metrics = ParityMetrics()
        
        m = MarketSnapshot(
            market_id="BTC-15M-UP-20260719-1400",
            asset="BTC",
            expiry_ts=1721409600,
            yes_bid=0.45,
            yes_ask=0.47,
            no_bid=0.53,
            no_ask=0.55,
        )
        
        v = BotView(
            model_prob_yes=0.45,
            model_prob_no=0.60,  # Prob mismatch
            edge_yes=0.05,
            edge_no=0.03,
            chosen_side="yes",
            exposure_intent=ExposureIntent.BULLISH_EVENT,
        )
        
        d = ExecutionDecision(
            intended_action=IntendedAction.BUY_YES,
            api_side="yes",
            api_yes_price=0.45,
            api_no_price=None,
        )
        
        checker = YesNoParityChecker()
        result = checker.check(m, v, d)
        
        metrics.record_failure(result)
        
        assert metrics.parity_checks_failed == 1
        assert metrics.failures_by_reason["PROB_MISMATCH"] == 1
    
    def test_record_side_mismatch(self):
        """Test recording side mismatches."""
        metrics = ParityMetrics()
        
        metrics.record_side_mismatch("yes", "no")
        metrics.record_side_mismatch("no", "yes")
        
        assert metrics.yes_won_but_no_traded == 1
        assert metrics.no_won_but_yes_traded == 1
    
    def test_get_summary(self):
        """Test getting metrics summary."""
        metrics = ParityMetrics()
        metrics.record_evaluated()
        metrics.record_traded()
        
        summary = metrics.get_summary()
        
        assert summary["total_markets_evaluated"] == 1
        assert summary["total_markets_traded"] == 1
        assert summary["parity_checks_failed"] == 0
    
    def test_is_healthy(self):
        """Test health check."""
        metrics = ParityMetrics()
        
        assert metrics.is_healthy() is True
        
        metrics.parity_checks_failed = 1
        assert metrics.is_healthy() is False


class TestSingletons:
    """Test singleton instances."""
    
    def test_get_parity_checker(self):
        """Test parity checker singleton."""
        checker1 = get_parity_checker()
        checker2 = get_parity_checker()
        
        assert checker1 is checker2
    
    def test_get_parity_metrics(self):
        """Test parity metrics singleton."""
        metrics1 = get_parity_metrics()
        metrics2 = get_parity_metrics()
        
        assert metrics1 is metrics2
    
    def test_reset_parity_metrics(self):
        """Test resetting parity metrics singleton."""
        metrics = get_parity_metrics()
        metrics.record_evaluated()
        
        reset_parity_metrics()
        
        metrics = get_parity_metrics()
        assert metrics.total_markets_evaluated == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
