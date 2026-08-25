"""Regression tests for YES/NO parity winner mismatch fix (2026-07-20).

This test suite ensures:
1. Canonical edge computation is symmetric and correct
2. Winner selection is based on edge comparison, not order side
3. Parity checker blocks orders on winner mismatches
4. The specific XRP incident (edge_yes=0.02 > edge_no=-0.42 but chose NO) cannot recur
"""

import pytest
from merid.prediction.canonical_edge import (
    compute_canonical_edges,
    select_winner_side,
    validate_price_parity,
)
from merid.validation.yes_no_parity_checker import (
    YesNoParityChecker,
    MarketSnapshot,
    BotView,
    ExecutionDecision,
    ExposureIntent,
    IntendedAction,
)


class TestCanonicalEdgeComputation:
    """Test canonical edge computation formulas."""
    
    def test_basic_edge_computation(self):
        """Test basic YES/NO edge computation."""
        model_prob_yes = 0.60
        market_price_yes = 0.50
        market_price_no = 0.50
        
        edge_yes, edge_no = compute_canonical_edges(
            model_prob_yes, market_price_yes, market_price_no
        )
        
        # edge_yes = model_prob_yes - market_price_yes = 0.60 - 0.50 = 0.10
        assert edge_yes == pytest.approx(0.10, abs=1e-6)
        # edge_no = (1 - model_prob_yes) - market_price_no = 0.40 - 0.50 = -0.10
        assert edge_no == pytest.approx(-0.10, abs=1e-6)
    
    def test_edge_computation_with_missing_yes_price(self):
        """Test edge computation when YES price is missing (derive from NO)."""
        model_prob_yes = 0.70
        market_price_yes = None
        market_price_no = 0.30
        
        edge_yes, edge_no = compute_canonical_edges(
            model_prob_yes, market_price_yes, market_price_no
        )
        
        # YES price derived: 1.0 - 0.30 = 0.70
        # edge_yes = 0.70 - 0.70 = 0.00
        assert edge_yes == pytest.approx(0.00, abs=1e-6)
        # edge_no = 0.30 - 0.30 = 0.00
        assert edge_no == pytest.approx(0.00, abs=1e-6)
    
    def test_edge_computation_with_missing_no_price(self):
        """Test edge computation when NO price is missing (derive from YES)."""
        model_prob_yes = 0.30
        market_price_yes = 0.30
        market_price_no = None
        
        edge_yes, edge_no = compute_canonical_edges(
            model_prob_yes, market_price_yes, market_price_no
        )
        
        # edge_yes = 0.30 - 0.30 = 0.00
        assert edge_yes == pytest.approx(0.00, abs=1e-6)
        # NO price derived: 1.0 - 0.30 = 0.70
        # edge_no = 0.70 - 0.70 = 0.00
        assert edge_no == pytest.approx(0.00, abs=1e-6)
    
    def test_edge_computation_both_prices_missing(self):
        """Test edge computation when both prices are missing."""
        edge_yes, edge_no = compute_canonical_edges(0.50, None, None)
        
        assert edge_yes == 0.0
        assert edge_no == 0.0
    
    def test_xrp_incident_case(self):
        """Test the specific XRP incident case from the log.
        
        Context: model_prob_yes=0.81, api_no_price=0.39
        Expected: edge_yes should be positive, edge_no should be negative
        """
        model_prob_yes = 0.81
        market_price_yes = None  # Not in log
        market_price_no = 0.39
        
        edge_yes, edge_no = compute_canonical_edges(
            model_prob_yes, market_price_yes, market_price_no
        )
        
        # YES price derived: 1.0 - 0.39 = 0.61
        # edge_yes = 0.81 - 0.61 = 0.20
        assert edge_yes == pytest.approx(0.20, abs=1e-6)
        # edge_no = 0.19 - 0.39 = -0.20
        assert edge_no == pytest.approx(-0.20, abs=1e-6)
        
        # YES edge should be positive, NO edge should be negative
        assert edge_yes > 0
        assert edge_no < 0


class TestWinnerSelection:
    """Test winner selection based on edge comparison."""
    
    def test_yes_wins_with_higher_edge(self):
        """Test YES wins when it has higher positive edge."""
        edge_yes = 0.10
        edge_no = -0.05
        min_edge = 0.02
        
        winner = select_winner_side(edge_yes, edge_no, min_edge)
        
        assert winner == "yes"
    
    def test_no_wins_with_higher_edge(self):
        """Test NO wins when it has higher positive edge."""
        edge_yes = -0.05
        edge_no = 0.10
        min_edge = 0.02
        
        winner = select_winner_side(edge_yes, edge_no, min_edge)
        
        assert winner == "no"
    
    def test_none_when_both_below_threshold(self):
        """Test 'none' when both edges are below threshold."""
        edge_yes = 0.01
        edge_no = 0.005
        min_edge = 0.02
        
        winner = select_winner_side(edge_yes, edge_no, min_edge)
        
        assert winner == "none"
    
    def test_none_when_both_negative(self):
        """Test 'none' when both edges are negative."""
        edge_yes = -0.10
        edge_no = -0.20
        min_edge = 0.02
        
        winner = select_winner_side(edge_yes, edge_no, min_edge)
        
        assert winner == "none"
    
    def test_none_on_tie(self):
        """Test 'none' when edges are within epsilon."""
        edge_yes = 0.05
        edge_no = 0.0500005
        min_edge = 0.02
        
        winner = select_winner_side(edge_yes, edge_no, min_edge)
        
        assert winner == "none"
    
    def test_xrp_incident_winner_selection(self):
        """Test winner selection for XRP incident case.
        
        Context: edge_yes=0.02, edge_no=-0.42
        Expected: winner should be "yes" (positive edge wins over negative)
        """
        edge_yes = 0.02
        edge_no = -0.42
        min_edge = 0.02
        
        winner = select_winner_side(edge_yes, edge_no, min_edge)
        
        # YES should win (positive edge > negative edge)
        assert winner == "yes"
        # This is the fix: previously, chosen_side was derived from kalshi_side
        # which could be "no" even when YES had better edge
    
    def test_yes_wins_small_positive_vs_negative(self):
        """Test YES wins with small positive edge vs large negative edge."""
        edge_yes = 0.015
        edge_no = -0.50
        min_edge = 0.01
        
        winner = select_winner_side(edge_yes, edge_no, min_edge)
        
        assert winner == "yes"


class TestPriceParityValidation:
    """Test price parity validation."""
    
    def test_perfect_parity(self):
        """Test perfect parity (yes + no = 1.0)."""
        yes_price = 0.60
        no_price = 0.40
        
        parity_ok = validate_price_parity(yes_price, no_price)
        
        assert parity_ok is True
    
    def test_parity_within_epsilon(self):
        """Test parity within epsilon tolerance."""
        yes_price = 0.60
        no_price = 0.405  # Combined = 1.005, within 1 cent epsilon
        
        parity_ok = validate_price_parity(yes_price, no_price)
        
        assert parity_ok is True
    
    def test_parity_violation(self):
        """Test parity violation (yes + no != 1.0)."""
        yes_price = 0.60
        no_price = 0.50  # Combined = 1.10, violation
        
        parity_ok = validate_price_parity(yes_price, no_price)
        
        assert parity_ok is False
    
    def test_parity_with_missing_prices(self):
        """Test parity validation with missing prices (should pass)."""
        parity_ok = validate_price_parity(None, None)
        assert parity_ok is True
        
        parity_ok = validate_price_parity(0.50, None)
        assert parity_ok is True


class TestParityCheckerBlocking:
    """Test parity checker blocking behavior for winner mismatches."""
    
    def test_winner_mismatch_yes_chosen_but_no_wins(self):
        """Test parity checker detects when YES chosen but NO has higher edge."""
        checker = YesNoParityChecker()
        
        market_snapshot = MarketSnapshot(
            market_id="KXBTC-TEST",
            asset="BTC",
            expiry_ts=1234567890,
            yes_bid=0.50,
            yes_ask=0.52,
            no_bid=0.48,
            no_ask=0.50,
        )
        
        bot_view = BotView(
            model_prob_yes=0.60,
            model_prob_no=0.40,
            edge_yes=0.05,  # Lower edge
            edge_no=0.15,  # Higher edge
            chosen_side="yes",  # WRONG: should be "no"
            exposure_intent=ExposureIntent.BULLISH_EVENT,
        )
        
        execution_decision = ExecutionDecision(
            intended_action=IntendedAction.BUY_YES,
            api_side="yes",
            api_yes_price=0.50,
            api_no_price=None,
        )
        
        result = checker.check(market_snapshot, bot_view, execution_decision)
        
        assert result.ok is False
        assert any("WINNER_MISMATCH" in reason for reason in result.reasons)
    
    def test_winner_mismatch_no_chosen_but_yes_wins(self):
        """Test parity checker detects when NO chosen but YES has higher edge.
        
        This is the XRP incident case: edge_yes=0.02 > edge_no=-0.42 but chose NO
        """
        checker = YesNoParityChecker()
        
        market_snapshot = MarketSnapshot(
            market_id="KXXRP-TEST",
            asset="XRP",
            expiry_ts=1234567890,
            yes_bid=None,
            yes_ask=None,
            no_bid=39.0,
            no_ask=39.0,
        )
        
        bot_view = BotView(
            model_prob_yes=0.81,
            model_prob_no=0.19,
            edge_yes=0.02,  # Higher edge
            edge_no=-0.42,  # Lower edge
            chosen_side="no",  # WRONG: should be "yes"
            exposure_intent=ExposureIntent.BEARISH_EVENT,
        )
        
        execution_decision = ExecutionDecision(
            intended_action=IntendedAction.BUY_NO,
            api_side="no",
            api_yes_price=None,
            api_no_price=0.39,
        )
        
        result = checker.check(market_snapshot, bot_view, execution_decision)
        
        assert result.ok is False
        assert any("WINNER_MISMATCH" in reason for reason in result.reasons)
    
    def test_parity_ok_when_winner_correct(self):
        """Test parity checker passes when winner is correct."""
        checker = YesNoParityChecker()
        
        market_snapshot = MarketSnapshot(
            market_id="KXETH-TEST",
            asset="ETH",
            expiry_ts=1234567890,
            yes_bid=0.50,
            yes_ask=0.52,
            no_bid=0.48,
            no_ask=0.50,
        )
        
        bot_view = BotView(
            model_prob_yes=0.60,
            model_prob_no=0.40,
            edge_yes=0.15,  # Higher edge
            edge_no=0.05,  # Lower edge
            chosen_side="yes",  # CORRECT: YES has higher edge
            exposure_intent=ExposureIntent.BULLISH_EVENT,
        )
        
        execution_decision = ExecutionDecision(
            intended_action=IntendedAction.BUY_YES,
            api_side="yes",
            api_yes_price=0.50,
            api_no_price=None,
        )
        
        result = checker.check(market_snapshot, bot_view, execution_decision)
        
        assert result.ok is True
    
    def test_parity_ok_when_none_chosen_and_both_below_threshold(self):
        """Test parity checker passes when 'none' chosen and both edges below threshold."""
        checker = YesNoParityChecker()
        
        market_snapshot = MarketSnapshot(
            market_id="KXSOL-TEST",
            asset="SOL",
            expiry_ts=1234567890,
            yes_bid=0.50,
            yes_ask=0.52,
            no_bid=0.48,
            no_ask=0.50,
        )
        
        bot_view = BotView(
            model_prob_yes=0.50,
            model_prob_no=0.50,
            edge_yes=0.01,  # Below threshold
            edge_no=0.005,  # Below threshold
            chosen_side="none",  # CORRECT: both below threshold
            exposure_intent=ExposureIntent.NEUTRAL,
        )
        
        execution_decision = ExecutionDecision(
            intended_action=IntendedAction.NONE,
            api_side=None,
            api_yes_price=None,
            api_no_price=None,
        )
        
        result = checker.check(market_snapshot, bot_view, execution_decision)
        
        assert result.ok is True


class TestXRPIncidentRegression:
    """Regression tests for the specific XRP incident."""
    
    def test_xrp_incident_cannot_recur(self):
        """Test that the XRP incident cannot recur with the fix.
        
        Original incident:
        - model_prob_yes = 0.81
        - edge_yes = 0.0200
        - edge_no = -0.4200
        - chosen_side = "no" (WRONG)
        - intended_action = "buy_no"
        
        With the fix:
        - select_winner_side should return "yes"
        - Parity checker should block if "no" is chosen
        """
        # Step 1: Winner selection should pick YES
        edge_yes = 0.02
        edge_no = -0.42
        min_edge = 0.02
        
        winner = select_winner_side(edge_yes, edge_no, min_edge)
        assert winner == "yes", "Winner selection should pick YES (positive edge)"
        
        # Step 2: Parity checker should block if NO is incorrectly chosen
        checker = YesNoParityChecker()
        
        market_snapshot = MarketSnapshot(
            market_id="KXXRP-15M-TEST",
            asset="XRP",
            expiry_ts=0,
            yes_bid=None,
            yes_ask=None,
            no_bid=39.0,
            no_ask=39.0,
        )
        
        bot_view = BotView(
            model_prob_yes=0.81,
            model_prob_no=0.19,
            edge_yes=0.02,
            edge_no=-0.42,
            chosen_side="no",  # INCORRECT - this should be blocked
            exposure_intent=ExposureIntent.BEARISH_EVENT,
        )
        
        execution_decision = ExecutionDecision(
            intended_action=IntendedAction.BUY_NO,
            api_side="no",
            api_yes_price=None,
            api_no_price=0.39,
        )
        
        result = checker.check(market_snapshot, bot_view, execution_decision)
        
        assert result.ok is False, "Parity checker should block winner mismatch"
        assert any("WINNER_MISMATCH" in reason for reason in result.reasons)
    
    def test_xrp_incident_correct_flow(self):
        """Test the correct flow for XRP incident case."""
        # Step 1: Compute edges canonically
        model_prob_yes = 0.81
        market_price_no = 0.39
        market_price_yes = 1.0 - market_price_no  # Derive from parity
        
        edge_yes, edge_no = compute_canonical_edges(
            model_prob_yes, market_price_yes, market_price_no
        )
        
        assert edge_yes > 0, "YES edge should be positive"
        assert edge_no < 0, "NO edge should be negative"
        
        # Step 2: Select winner
        winner = select_winner_side(edge_yes, edge_no, min_edge=0.02)
        assert winner == "yes", "Winner should be YES"
        
        # Step 3: Parity check with correct winner should pass
        checker = YesNoParityChecker()
        
        market_snapshot = MarketSnapshot(
            market_id="KXXRP-15M-TEST",
            asset="XRP",
            expiry_ts=0,
            yes_bid=61.0,
            yes_ask=61.0,
            no_bid=39.0,
            no_ask=39.0,
        )
        
        bot_view = BotView(
            model_prob_yes=0.81,
            model_prob_no=0.19,
            edge_yes=edge_yes,
            edge_no=edge_no,
            chosen_side="yes",  # CORRECT
            exposure_intent=ExposureIntent.BULLISH_EVENT,
        )
        
        execution_decision = ExecutionDecision(
            intended_action=IntendedAction.BUY_YES,
            api_side="yes",
            api_yes_price=0.61,
            api_no_price=None,
        )
        
        result = checker.check(market_snapshot, bot_view, execution_decision)
        
        assert result.ok is True, "Parity check should pass with correct winner"


class TestDirectionalAnomalyCircuitBreaker:
    """Tests for the rolling-window directional anomaly circuit breaker."""

    def test_prob_parity_violation_blocks(self, monkeypatch):
        """Block when yes_model_prob + no_model_prob != 1."""
        monkeypatch.setenv("MERID_DIRECTIONAL_ANOMALY_BREAKER_DISABLED", "0")
        from merid.validation.yes_no_parity_checker import DirectionalAnomalyCircuitBreaker
        breaker = DirectionalAnomalyCircuitBreaker()
        allowed, reason = breaker.record_and_check(
            asset="BTC",
            ticker="KXBTC15M-TEST",
            buy_threshold=0.50,
            sell_threshold=0.50,
            yes_model_prob=0.60,
            no_model_prob=0.30,  # sum = 0.90, parity violation
            yes_edge=0.10,
            no_edge=-0.05,
            selected_side="yes",
            selected_action="buy",
            market_price=0.45,
        )
        assert allowed is False
        assert "prob_parity_violation" in reason

    def test_edge_winner_mismatch_blocks(self, monkeypatch):
        """Block when the selected side does not have the highest edge."""
        monkeypatch.setenv("MERID_DIRECTIONAL_ANOMALY_BREAKER_DISABLED", "0")
        from merid.validation.yes_no_parity_checker import DirectionalAnomalyCircuitBreaker
        breaker = DirectionalAnomalyCircuitBreaker()
        allowed, reason = breaker.record_and_check(
            asset="BTC",
            ticker="KXBTC15M-TEST",
            buy_threshold=0.50,
            sell_threshold=0.50,
            yes_model_prob=0.50,
            no_model_prob=0.50,
            yes_edge=0.15,
            no_edge=0.05,
            selected_side="no",  # wrong winner
            selected_action="buy",
            market_price=0.60,
        )
        assert allowed is False
        assert "edge_winner_mismatch" in reason

    def test_allows_correct_selection(self, monkeypatch):
        """Allow symmetric probabilities with correct edge winner."""
        monkeypatch.setenv("MERID_DIRECTIONAL_ANOMALY_BREAKER_DISABLED", "0")
        from merid.validation.yes_no_parity_checker import DirectionalAnomalyCircuitBreaker
        breaker = DirectionalAnomalyCircuitBreaker()
        allowed, reason = breaker.record_and_check(
            asset="BTC",
            ticker="KXBTC15M-TEST",
            buy_threshold=0.50,
            sell_threshold=0.50,
            yes_model_prob=0.50,
            no_model_prob=0.50,
            yes_edge=0.05,
            no_edge=0.15,
            selected_side="no",
            selected_action="buy",
            market_price=0.60,
        )
        assert allowed is True
        assert reason == ""

    def test_disabled_by_env(self, monkeypatch):
        """Breaker can be disabled via environment variable."""
        monkeypatch.setenv("MERID_DIRECTIONAL_ANOMALY_BREAKER_DISABLED", "1")
        from merid.validation.yes_no_parity_checker import DirectionalAnomalyCircuitBreaker
        breaker = DirectionalAnomalyCircuitBreaker()
        allowed, reason = breaker.record_and_check(
            asset="BTC",
            ticker="KXBTC15M-TEST",
            buy_threshold=0.50,
            sell_threshold=0.50,
            yes_model_prob=0.50,
            no_model_prob=0.50,
            yes_edge=0.15,
            no_edge=0.05,
            selected_side="no",  # would block if enabled
            selected_action="buy",
            market_price=0.60,
        )
        assert allowed is True

    def test_yes_frequency_anomaly_blocks(self, monkeypatch):
        """Block when YES is selected too often at non-cheap prices."""
        monkeypatch.setenv("MERID_DIRECTIONAL_ANOMALY_BREAKER_DISABLED", "0")
        from merid.validation.yes_no_parity_checker import DirectionalAnomalyCircuitBreaker
        breaker = DirectionalAnomalyCircuitBreaker(window_size=5, side_ratio=0.8, price_eps=0.05)

        # One NO trade to keep the window from being all-YES too early.
        allowed, _ = breaker.record_and_check(
            asset="BTC",
            ticker="KXBTC15M-TEST",
            buy_threshold=0.50,
            sell_threshold=0.50,
            yes_model_prob=0.50,
            no_model_prob=0.50,
            yes_edge=0.00,
            no_edge=0.10,
            selected_side="no",
            selected_action="buy",
            market_price=0.40,
        )
        assert allowed is True

        # Three expensive YES selections; total=4, yes=3 (ratio 0.75) so still allowed.
        for _ in range(3):
            allowed, _ = breaker.record_and_check(
                asset="BTC",
                ticker="KXBTC15M-TEST",
                buy_threshold=0.50,
                sell_threshold=0.50,
                yes_model_prob=0.50,
                no_model_prob=0.50,
                yes_edge=0.10,
                no_edge=0.00,
                selected_side="yes",
                selected_action="buy",
                market_price=0.60,
            )
            assert allowed is True

        # Fifth call makes total=5, yes=4 (0.80), avg_yes_price=0.60 > 0.55.
        allowed, reason = breaker.record_and_check(
            asset="BTC",
            ticker="KXBTC15M-TEST",
            buy_threshold=0.50,
            sell_threshold=0.50,
            yes_model_prob=0.50,
            no_model_prob=0.50,
            yes_edge=0.10,
            no_edge=0.00,
            selected_side="yes",
            selected_action="buy",
            market_price=0.60,
        )
        assert allowed is False
        assert "yes_frequency_anomaly" in reason


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
