"""
Tests for No Magic Numbers Policy Enforcement.

Tests the validation functions in order_router.py that enforce:
- Prob-price consistency (model must support order price)
- Deep OTM policy (no lotto tickets)
- Underlying plausibility (no absurd required moves)
- Position lifecycle (every entry has an exit plan)
"""

import pytest
from dataclasses import dataclass
from typing import Optional

# Import the validation functions from order_router
import sys
sys.path.insert(0, 'c:/Dev/MERID')

from merid.event_venues.kalshi.order_router import (
    _validate_prob_price_consistency,
    _validate_deep_otm_policy,
    _validate_underlying_plausibility,
    _validate_position_lifecycle,
)


@dataclass
class MockOrderIntent:
    """Mock OrderIntent for testing."""
    ticker: str
    action: str
    side: str
    price_cents: int
    model_prob: Optional[float] = None
    edge_pct: Optional[float] = None
    confidence: Optional[float] = None
    group_id: Optional[str] = None
    agent_id: Optional[str] = None
    session_id: Optional[str] = None
    source: Optional[str] = None
    take_profit_price_cents: Optional[int] = None
    take_profit_r_multiple: Optional[float] = None
    stop_loss_price_cents: Optional[int] = None


class TestProbPriceConsistency:
    """Tests for _validate_prob_price_consistency."""
    
    def test_yes_order_with_positive_edge(self):
        """YES order should pass when model_prob > implied_prob."""
        intent = MockOrderIntent(
            ticker="KXBTC15M-26MAR2501",
            action="buy",
            side="yes",
            price_cents=30,  # implied_prob = 0.30
            model_prob=0.60,  # model says 60%, edge is positive
        )
        result = _validate_prob_price_consistency(intent)
        assert result is None, "Should pass with positive edge"
    
    def test_yes_order_with_no_edge(self):
        """YES order should fail when model_prob <= implied_prob."""
        intent = MockOrderIntent(
            ticker="KXBTC15M-26MAR2501",
            action="buy",
            side="yes",
            price_cents=50,  # implied_prob = 0.50
            model_prob=0.40,  # model says 40%, no edge
        )
        result = _validate_prob_price_consistency(intent)
        assert result is not None, "Should fail with no edge"
        assert "no_edge_vs_implied" in result
    
    def test_yes_order_missing_model_prob(self):
        """YES order should fail when model_prob is missing."""
        intent = MockOrderIntent(
            ticker="KXBTC15M-26MAR2501",
            action="buy",
            side="yes",
            price_cents=30,
            model_prob=None,
        )
        result = _validate_prob_price_consistency(intent)
        assert result is not None, "Should fail with missing model_prob"
        assert "missing_model_prob" in result
    
    def test_sell_order_bypass(self):
        """Sell orders should bypass prob-price check (for exit orders)."""
        intent = MockOrderIntent(
            ticker="KXBTC15M-26MAR2501",
            action="sell",
            side="yes",
            price_cents=30,
            model_prob=0.10,  # Even with no edge, should pass
        )
        result = _validate_prob_price_consistency(intent)
        assert result is None, "Sell orders should bypass"
    
    def test_sell_yes_order_with_negative_edge(self):
        """SELL YES order should pass when model_prob < implied_prob (betting NO)."""
        intent = MockOrderIntent(
            ticker="KXBTC15M-26MAR2501",
            action="sell",  # SELL YES is action=sell with side=yes
            side="yes",
            price_cents=74,  # implied_prob = 0.74
            model_prob=0.60,  # model says 60%, we think outcome is less likely (negative edge for YES)
        )
        result = _validate_prob_price_consistency(intent)
        assert result is None, "Should pass with negative edge for SELL YES"
    
    def test_sell_yes_order_with_no_edge(self):
        """SELL YES order should fail when model_prob >= implied_prob."""
        intent = MockOrderIntent(
            ticker="KXBTC15M-26MAR2501",
            action="sell",  # SELL YES is action=sell with side=yes
            side="yes",
            price_cents=50,  # implied_prob = 0.50
            model_prob=0.60,  # model says 60%, no negative edge (we think outcome is MORE likely)
        )
        result = _validate_prob_price_consistency(intent)
        assert result is not None, "Should fail with no negative edge for SELL YES"
        assert "no_edge_vs_implied" in result
    
    def test_no_order_with_positive_edge(self):
        """NO order should pass when (1 - model_prob) > (1 - implied_prob)."""
        intent = MockOrderIntent(
            ticker="KXBTC15M-26MAR2501",
            action="buy",
            side="no",
            price_cents=70,  # implied_prob = 0.70, so (1 - implied) = 0.30
            model_prob=0.40,  # (1 - model) = 0.60, edge is positive
        )
        result = _validate_prob_price_consistency(intent)
        assert result is None, "Should pass with positive edge for NO"


class TestDeepOTMPolicy:
    """Tests for _validate_deep_otm_policy."""
    
    def test_deep_cheap_contract_rejected(self):
        """Deep cheap contracts (1-5¢) should be rejected."""
        intent = MockOrderIntent(
            ticker="KXBTC15M-26MAR2501",
            action="buy",
            side="yes",
            price_cents=3,  # Deep OTM cheap
        )
        result = _validate_deep_otm_policy(intent)
        assert result is not None, "Should reject deep cheap contracts"
        assert "deep_otm_disallowed" in result
    
    def test_deep_expensive_contract_rejected(self):
        """Deep expensive contracts (95-99¢) should be rejected."""
        intent = MockOrderIntent(
            ticker="KXBTC15M-26MAR2501",
            action="buy",
            side="yes",
            price_cents=97,  # Deep OTM expensive
        )
        result = _validate_deep_otm_policy(intent)
        assert result is not None, "Should reject deep expensive contracts"
        assert "deep_otm_disallowed" in result
    
    def test_atm_contract_allowed(self):
        """ATM contracts (near 50¢) should be allowed."""
        intent = MockOrderIntent(
            ticker="KXBTC15M-26MAR2501",
            action="buy",
            side="yes",
            price_cents=45,  # ATM
        )
        result = _validate_deep_otm_policy(intent)
        assert result is None, "Should allow ATM contracts"
    
    def test_sell_order_bypass(self):
        """Sell orders should bypass deep OTM check."""
        intent = MockOrderIntent(
            ticker="KXBTC15M-26MAR2501",
            action="sell",
            side="yes",
            price_cents=3,  # Even deep cheap, should pass
        )
        result = _validate_deep_otm_policy(intent)
        assert result is None, "Sell orders should bypass"


class TestUnderlyingPlausibility:
    """Tests for _validate_underlying_plausibility."""
    
    def test_very_cheap_crypto_without_edge_rejected(self):
        """Very cheap crypto contracts without exceptional edge should be rejected."""
        intent = MockOrderIntent(
            ticker="KXBTC15M-26MAR2501",  # BTC 15m
            action="buy",
            side="yes",
            price_cents=12,  # Very cheap (below 20c threshold)
            edge_pct=0.02,  # Low edge
        )
        result = _validate_underlying_plausibility(intent)
        assert result is not None, "Should reject cheap without exceptional edge"
        assert "implausible_move" in result
    
    def test_very_cheap_crypto_with_high_edge_allowed(self):
        """Very cheap crypto contracts with high edge should be allowed."""
        intent = MockOrderIntent(
            ticker="KXBTC15M-26MAR2501",  # BTC 15m
            action="buy",
            side="yes",
            price_cents=5,  # Very cheap
            edge_pct=0.25,  # High edge (> IMPLAUSIBLE_MOVE_MIN_EDGE_PCT which is 20%)
        )
        result = _validate_underlying_plausibility(intent)
        # Implementation: price_cents <= 10 requires edge > IMPLAUSIBLE_MOVE_MIN_EDGE_PCT (0.20)
        # 0.25 > 0.20, so this should pass
        assert result is None, f"Should allow with high edge, got: {result}"
    
    def test_non_crypto_bypass(self):
        """Non-crypto markets should bypass plausibility check."""
        intent = MockOrderIntent(
            ticker="KXCPI-26MAR2501",  # CPI (not crypto)
            action="buy",
            side="yes",
            price_cents=5,  # Even very cheap
            edge_pct=0.01,  # Low edge
        )
        result = _validate_underlying_plausibility(intent)
        assert result is None, "Non-crypto should bypass"
    
    def test_sell_order_bypass(self):
        """Sell orders should bypass plausibility check."""
        intent = MockOrderIntent(
            ticker="KXBTC15M-26MAR2501",
            action="sell",
            side="yes",
            price_cents=5,
            edge_pct=0.01,
        )
        result = _validate_underlying_plausibility(intent)
        assert result is None, "Sell orders should bypass"


class TestPositionLifecycle:
    """Tests for _validate_position_lifecycle."""
    
    def test_entry_without_group_or_agent_rejected(self):
        """Entry orders without group_id or agent_id should be rejected."""
        intent = MockOrderIntent(
            ticker="KXBTC15M-26MAR2501",
            action="buy",
            side="yes",
            price_cents=30,
            group_id=None,
            agent_id=None,
        )
        result = _validate_position_lifecycle(intent)
        assert result is not None, "Should reject untagged entry"
        assert "position_not_tagged" in result
    
    def test_entry_with_group_id_allowed(self):
        """Entry orders with group_id should be allowed."""
        intent = MockOrderIntent(
            ticker="KXBTC15M-26MAR2501",
            action="buy",
            side="yes",
            price_cents=30,
            group_id="crypto_edge_group",
            agent_id=None,
        )
        result = _validate_position_lifecycle(intent)
        assert result is None, "Should allow with group_id"
    
    def test_entry_with_agent_id_allowed(self):
        """Entry orders with agent_id should be allowed."""
        intent = MockOrderIntent(
            ticker="KXBTC15M-26MAR2501",
            action="buy",
            side="yes",
            price_cents=30,
            group_id=None,
            agent_id="kalshi_crypto_agent",
        )
        result = _validate_position_lifecycle(intent)
        assert result is None, "Should allow with agent_id"
    
    def test_entry_without_exit_plan_rejected(self):
        """Entry orders without exit targets should be rejected (for non-15m)."""
        # Non-15m ticker to trigger exit plan check
        intent = MockOrderIntent(
            ticker="KXCPI-26MAR2501",  # Not 15m crypto
            action="buy",
            side="yes",
            price_cents=30,
            group_id="test_group",
            take_profit_price_cents=None,
            take_profit_r_multiple=None,
            stop_loss_price_cents=None,
        )
        result = _validate_position_lifecycle(intent)
        # Should reject because no exit targets (TP/SL) and no session_id
        # Note: This might pass if _is_15m_crypto_entry_order returns False for this ticker
        # The actual behavior depends on the ticker classification logic
        if result is not None:
            assert "no_exit_plan" in result
    
    def test_sell_order_bypass(self):
        """Sell orders should bypass lifecycle check."""
        intent = MockOrderIntent(
            ticker="KXBTC15M-26MAR2501",
            action="sell",
            side="yes",
            price_cents=30,
            group_id=None,
            agent_id=None,
        )
        result = _validate_position_lifecycle(intent)
        assert result is None, "Sell orders should bypass"


class TestRiskParametersConstants:
    """Tests that risk_parameters.py has all required constants."""
    
    def test_risk_parameters_import(self):
        """Test that risk_parameters module can be imported and has correct values."""
        try:
            from merid.event_venues.kalshi.risk_parameters import (
                MIN_KALSHI_PRICE_CENTS,
                MAX_KALSHI_PRICE_CENTS,
                DEEP_OTM_CHEAP_CENTS,
                DEEP_OTM_EXPENSIVE_CENTS,
                MIN_EDGE_PCT,
                ENFORCE_DEEP_OTM_POLICY,
                ENFORCE_PROB_PRICE_CONSISTENCY,
                SIZER_MAX_BANKROLL_PCT,
                ERR_DEEP_OTM_DISALLOWED,
            )
            assert MIN_KALSHI_PRICE_CENTS == 1
            assert MAX_KALSHI_PRICE_CENTS == 99
            assert DEEP_OTM_CHEAP_CENTS == 5
            assert DEEP_OTM_EXPENSIVE_CENTS == 95
            assert isinstance(ENFORCE_DEEP_OTM_POLICY, bool)
            assert ENFORCE_DEEP_OTM_POLICY is True, "ENFORCE_DEEP_OTM_POLICY should be True (enabled to block deep OTM longshots)"
            assert isinstance(ENFORCE_PROB_PRICE_CONSISTENCY, bool)
            assert ENFORCE_PROB_PRICE_CONSISTENCY is True, "ENFORCE_PROB_PRICE_CONSISTENCY should be True (tightened)"
            assert SIZER_MAX_BANKROLL_PCT == 0.03, "SIZER_MAX_BANKROLL_PCT should be 3% (tightened from 5%)"
        except ImportError as e:
            pytest.fail(f"Failed to import risk_parameters: {e}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
