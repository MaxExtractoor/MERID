"""
Tests for regime_gating_invariants.py

Pure unit tests with synthetic inputs, no I/O, fully deterministic.
"""

import pytest
from unittest.mock import patch, MagicMock

from merid.validation.regime_gating_invariants import (
    RegimeGatingInvariantChecker,
    RegimeGatingViolation,
    RegimeGatingCheckResult,
    check_volatility_gating,
    check_volume_gating,
    check_velocity_gating,
    check_regime_tag_inclusion,
    generate_synthetic_regime_gating_test_cases,
)


class TestRegimeGatingInvariants:
    """Test suite for regime gating invariants."""
    
    @pytest.fixture
    def checker(self):
        """Fixture for RegimeGatingInvariantChecker."""
        return RegimeGatingInvariantChecker(
            max_volatility_threshold=0.05,
            min_volume_threshold=10,
            max_spread_cents=30,
            max_velocity_threshold=0.002,
            max_notional_usd=1.00,
        )
    
    def test_high_volatility_shrinks_size_or_disables_strategy(self, checker):
        """
        Given volatility > max, trade size > allowed, expect VOL_TOO_HIGH violation.
        Given volatility > max but strategy_disabled=True, expect invariant passes.
        """
        # Invalid case: high volatility with trade emitted and position not shrunk
        result = checker.check_volatility_gating(
            volatility=0.06,
            volatility_flag="high",
            position_size=1,
            strategy_disabled=False,
            trade_emitted=True,
        )
        assert not result.is_valid
        assert result.violation_type == RegimeGatingViolation.POSITION_SIZE_NOT_SHRUNK
        
        # Valid case: high volatility but strategy disabled
        result = checker.check_volatility_gating(
            volatility=0.06,
            volatility_flag="high",
            position_size=1,
            strategy_disabled=True,
            trade_emitted=False,
        )
        assert result.is_valid
        
        # Valid case: high volatility but position shrunk
        result = checker.check_volatility_gating(
            volatility=0.06,
            volatility_flag="high",
            position_size=0,  # Shrunk to 0
            strategy_disabled=False,
            trade_emitted=False,
        )
        assert result.is_valid
    
    def test_volatility_halt_forbids_trades(self, checker):
        """Test that volatility halt flag forbids trades."""
        # Invalid case: volatility halt with trade emitted
        result = checker.check_volatility_gating(
            volatility=0.10,
            volatility_flag="halt",
            position_size=1,
            strategy_disabled=False,
            trade_emitted=True,
        )
        assert not result.is_valid
        assert result.violation_type == RegimeGatingViolation.VOLATILITY_HALT_TRADE
        
        # Valid case: volatility halt with no trade
        result = checker.check_volatility_gating(
            volatility=0.10,
            volatility_flag="halt",
            position_size=1,
            strategy_disabled=False,
            trade_emitted=False,
        )
        assert result.is_valid
    
    def test_low_volume_forbids_large_orders(self, checker):
        """
        volume < min, size > limit. Expect VOLUME_ILLIQUID and violation.
        """
        # Invalid case: low volume with trade emitted
        result = checker.check_volume_gating(
            bid_size=5,
            ask_size=5,
            volume_flag="illiquid",
            notional_usd=0.50,
            trade_emitted=True,
        )
        assert not result.is_valid
        assert result.violation_type == RegimeGatingViolation.VOLUME_ILLIQUID_TRADE
        
        # Valid case: low volume with no trade
        result = checker.check_volume_gating(
            bid_size=5,
            ask_size=5,
            volume_flag="illiquid",
            notional_usd=0.50,
            trade_emitted=False,
        )
        assert result.is_valid
        
        # Valid case: sufficient volume
        result = checker.check_volume_gating(
            bid_size=50,
            ask_size=50,
            volume_flag="liquid",
            notional_usd=0.50,
            trade_emitted=True,
        )
        assert result.is_valid
    
    def test_max_notional_exceeded(self, checker):
        """Test that max notional cap is enforced."""
        # Invalid case: notional exceeds cap
        result = checker.check_volume_gating(
            bid_size=50,
            ask_size=50,
            volume_flag="liquid",
            notional_usd=2.00,  # Exceeds $1.00 cap
            trade_emitted=True,
        )
        assert not result.is_valid
        assert result.violation_type == RegimeGatingViolation.MAX_NOTIONAL_EXCEEDED
        
        # Valid case: notional within cap
        result = checker.check_volume_gating(
            bid_size=50,
            ask_size=50,
            volume_flag="liquid",
            notional_usd=0.50,
            trade_emitted=True,
        )
        assert result.is_valid
    
    def test_extreme_velocity_forbids_contrarian_entries(self, checker):
        """
        velocity > threshold, intent=contrarian. Expect VELOCITY_EXTREME_CONTRARIAN.
        """
        # Invalid case: extreme velocity with contrarian entry
        result = checker.check_velocity_gating(
            velocity=0.003,
            velocity_flag="extreme",
            entry_type="contrarian",
            edge=0.05,
            trade_emitted=True,
        )
        assert not result.is_valid
        assert result.violation_type == RegimeGatingViolation.VELOCITY_EXTREME_CONTRARIAN
        
        # Valid case: extreme velocity with momentum entry and sufficient edge
        result = checker.check_velocity_gating(
            velocity=0.003,
            velocity_flag="extreme",
            entry_type="momentum",
            edge=0.03,  # Sufficient edge
            trade_emitted=True,
        )
        assert result.is_valid
        
        # Valid case: extreme velocity with momentum entry but insufficient edge
        result = checker.check_velocity_gating(
            velocity=0.003,
            velocity_flag="extreme",
            entry_type="momentum",
            edge=0.01,  # Insufficient edge
            trade_emitted=True,
        )
        assert not result.is_valid
        assert result.violation_type == RegimeGatingViolation.VELOCITY_EXTREME_CONTRARIAN
    
    def test_spread_too_wide(self, checker):
        """Test that spread too wide forbids trades."""
        # Invalid case: spread exceeds max
        result = checker.check_spread_gating(
            spread_cents=35,
            trade_emitted=True,
        )
        assert not result.is_valid
        assert result.violation_type == RegimeGatingViolation.SPREAD_TOO_WIDE
        
        # Valid case: spread within max
        result = checker.check_spread_gating(
            spread_cents=25,
            trade_emitted=True,
        )
        assert result.is_valid
    
    def test_regime_tag_present_on_all_trade_decisions(self, checker):
        """
        A trade decision without regime_tag must be flagged.
        """
        # Invalid case: trade decision without regime tag
        result = checker.check_regime_tag_inclusion(
            trade_decision={"ticker": "KXBTC15M-26JUL211730-30"},
            regime_tag=None,
        )
        assert not result.is_valid
        assert result.violation_type == RegimeGatingViolation.REGIME_TAG_MISSING
        
        # Invalid case: trade decision dict missing regime_tag field
        result = checker.check_regime_tag_inclusion(
            trade_decision={"ticker": "KXBTC15M-26JUL211730-30"},
            regime_tag="normal",
        )
        assert not result.is_valid
        assert result.violation_type == RegimeGatingViolation.REGIME_TAG_MISSING
        
        # Invalid case: regime tag mismatch
        result = checker.check_regime_tag_inclusion(
            trade_decision={"regime_tag": "high_volatility"},
            regime_tag="normal",
        )
        assert not result.is_valid
        assert result.violation_type == RegimeGatingViolation.REGIME_TAG_MISSING
        
        # Valid case: regime tag present and matches
        result = checker.check_regime_tag_inclusion(
            trade_decision={"regime_tag": "normal"},
            regime_tag="normal",
        )
        assert result.is_valid
    
    def test_check_all_invariants(self, checker):
        """Test running all regime gating invariants together."""
        results = checker.check_all_invariants(
            volatility=0.02,
            volatility_flag="normal",
            bid_size=50,
            ask_size=50,
            volume_flag="liquid",
            velocity=0.0005,
            velocity_flag="normal",
            entry_type="momentum",
            edge=0.05,
            spread_cents=5,
            position_size=1,
            notional_usd=0.50,
            strategy_disabled=False,
            trade_emitted=True,
            trade_decision={"regime_tag": "normal"},
            regime_tag="normal",
        )
        
        assert len(results) == 5  # Five invariants checked
        assert all(r.is_valid for r in results)
    
    def test_check_all_invariants_with_violations(self, checker):
        """Test running all invariants with violations."""
        results = checker.check_all_invariants(
            volatility=0.10,
            volatility_flag="halt",
            bid_size=5,
            ask_size=5,
            volume_flag="illiquid",
            velocity=0.003,
            velocity_flag="extreme",
            entry_type="contrarian",
            edge=0.05,
            spread_cents=35,
            position_size=1,
            notional_usd=2.00,
            strategy_disabled=False,
            trade_emitted=True,
            trade_decision={},
            regime_tag=None,
        )
        
        assert len(results) == 5
        assert not all(r.is_valid for r in results)
        # At least one should be invalid
        assert sum(1 for r in results if not r.is_valid) >= 1


class TestConvenienceFunctions:
    """Test convenience functions for direct use."""
    
    def test_check_volatility_gating(self):
        """Test convenience function for volatility gating."""
        result = check_volatility_gating(
            volatility=0.02,
            volatility_flag="normal",
            position_size=1,
            strategy_disabled=False,
            trade_emitted=True,
        )
        assert result.is_valid
    
    def test_check_volume_gating(self):
        """Test convenience function for volume gating."""
        result = check_volume_gating(
            bid_size=50,
            ask_size=50,
            volume_flag="liquid",
            notional_usd=0.50,
            trade_emitted=True,
        )
        assert result.is_valid
    
    def test_check_velocity_gating(self):
        """Test convenience function for velocity gating."""
        result = check_velocity_gating(
            velocity=0.0005,
            velocity_flag="normal",
            entry_type="momentum",
            edge=0.05,
            trade_emitted=True,
        )
        assert result.is_valid
    
    def test_check_regime_tag_inclusion(self):
        """Test convenience function for regime tag inclusion."""
        result = check_regime_tag_inclusion(
            trade_decision={"regime_tag": "normal"},
            regime_tag="normal",
        )
        assert result.is_valid


class TestSyntheticTestCases:
    """Test synthetic test case generator."""
    
    def test_generate_synthetic_regime_gating_test_cases(self):
        """Test that synthetic test cases are generated correctly."""
        test_cases = generate_synthetic_regime_gating_test_cases()
        
        assert len(test_cases) > 0
        assert all("volatility" in tc for tc in test_cases)
        assert all("bid_size" in tc for tc in test_cases)
        assert all("ask_size" in tc for tc in test_cases)
        assert all("velocity" in tc for tc in test_cases)
        assert all("spread_cents" in tc for tc in test_cases)
        assert all("expected_valid" in tc for tc in test_cases)
    
    def test_synthetic_test_cases_valid_and_invalid(self):
        """Test that synthetic test cases include both valid and invalid cases."""
        test_cases = generate_synthetic_regime_gating_test_cases()
        
        valid_cases = [tc for tc in test_cases if tc["expected_valid"]]
        invalid_cases = [tc for tc in test_cases if not tc["expected_valid"]]
        
        assert len(valid_cases) > 0
        assert len(invalid_cases) > 0


class TestRegimeGatingCheckResult:
    """Test RegimeGatingCheckResult dataclass."""
    
    def test_to_dict(self):
        """Test conversion to dictionary."""
        result = RegimeGatingCheckResult(
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
        result = RegimeGatingCheckResult(
            is_valid=False,
            violation_type=RegimeGatingViolation.VOLATILITY_HALT_TRADE,
            message="Test violation",
            context={},
        )
        
        result_dict = result.to_dict()
        assert result_dict["is_valid"] is False
        assert result_dict["violation_type"] == "volatility_halt_trade"
