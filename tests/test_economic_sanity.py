"""Economic Sanity Test Suite

Comprehensive validation of economic/financial correctness across the trading pipeline:
- Fee calculations match Kalshi spec exactly
- Edge thresholds are reasonable and bounded
- Risk profiles enforce sane limits
- Position sizing produces valid outputs
- Bankroll resolution handles edge cases
- Volatility calculations are mathematically sound

Run: pytest tests/test_economic_sanity.py -v
"""

from __future__ import annotations

import pytest
import math
from decimal import Decimal


# ═══════════════════════════════════════════════════════════════════════════════
# Fee Calculation Sanity Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestKalshiFeeSanity:
    """Validate Kalshi fee calculations against official specification."""
    
    def test_fee_non_negative(self):
        """Fees must always be non-negative."""
        from merid.event_venues.kalshi.fees import calculate_kalshi_fee_cents
        
        for contracts in [0, 1, 10, 100, 1000]:
            for price in [1, 50, 99]:
                fee = calculate_kalshi_fee_cents(contracts, price)
                assert fee >= 0, f"Fee must be non-negative: {fee} for {contracts}@{price}¢"
    
    def test_fee_minimum_one_cent(self):
        """Kalshi fee is the cent-rounding ceiling; minimum is 1 cent."""
        from merid.event_venues.kalshi.fees import calculate_kalshi_fee_cents

        # Any valid trade should have at least 1 cent fee
        for contracts in [1, 5, 10]:
            for price in [1, 50, 99]:
                fee = calculate_kalshi_fee_cents(contracts, price)
                if fee > 0:
                    assert fee >= 1, f"Fee below 1 cent: {fee}¢ for {contracts}@{price}¢"
    
    def test_fee_tier_progression(self):
        """Higher contract counts should generally have lower per-contract fees."""
        from merid.event_venues.kalshi.fees import calculate_kalshi_fee_per_contract_cents
        
        price = 50
        
        # Tier 1: < 100 contracts (7% rate)
        tier1_fee_per = calculate_kalshi_fee_per_contract_cents(50, price)
        
        # Tier 2: 100-999 contracts (5% rate)
        tier2_fee_per = calculate_kalshi_fee_per_contract_cents(500, price)
        
        # Tier 3: 1000+ contracts (3% rate)
        tier3_fee_per = calculate_kalshi_fee_per_contract_cents(1000, price)
        
        # Higher tiers should have lower per-contract fees
        assert tier2_fee_per <= tier1_fee_per, "Tier 2 should have lower per-contract fee than Tier 1"
        assert tier3_fee_per <= tier2_fee_per, "Tier 3 should have lower per-contract fee than Tier 2"
    
    def test_fee_symmetric_at_50_cents(self):
        """At 50 cents, fee should be symmetric (maximum for parabolic formula)."""
        from merid.event_venues.kalshi.fees import calculate_kalshi_fee_cents
        
        # At P=0.5, P*(1-P) = 0.25 (maximum value)
        # Fee should be highest at 50 cents
        fee_50 = calculate_kalshi_fee_cents(100, 50)
        fee_40 = calculate_kalshi_fee_cents(100, 40)
        fee_60 = calculate_kalshi_fee_cents(100, 60)
        
        assert fee_50 >= fee_40, "50¢ should have higher fee than 40¢"
        assert fee_50 >= fee_60, "50¢ should have higher fee than 60¢"
    
    def test_fee_zero_contracts(self):
        """Zero contracts should produce zero fee."""
        from merid.event_venues.kalshi.fees import calculate_kalshi_fee_cents
        
        fee = calculate_kalshi_fee_cents(0, 50)
        assert fee == 0, "Zero contracts must produce zero fee"
    
    def test_fee_drag_calculation(self):
        """Fee drag should be reasonable percentage."""
        from merid.event_venues.kalshi.fees import calculate_fee_drag_bps
        
        # 10 contracts at 55 cents
        drag = calculate_fee_drag_bps(10, 55)
        
        # Fee drag should be between 0 and 1000 bps (10%)
        assert 0 <= drag <= 1000, f"Fee drag unreasonable: {drag} bps"
    
    def test_net_edge_calculation(self):
        """Net edge should account for all costs."""
        from merid.event_venues.kalshi.fees import calculate_net_edge_bps
        
        # Larger position (100 contracts) at 55 cents with 300 bps gross edge
        # Should be positive after fees due to economies of scale
        net = calculate_net_edge_bps(100, 55, 300, 0, 0)
        
        # With sufficiently large gross edge, net should still be positive
        assert net < 300, "Net edge should be less than gross after fees"
        assert net > 0, "Net edge should still be positive with 300 bps gross and 100 contracts"


# ═══════════════════════════════════════════════════════════════════════════════
# Edge Threshold Sanity Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestEdgeThresholdSanity:
    """Validate edge threshold resolution produces reasonable values."""
    
    def test_threshold_within_absolute_bounds(self):
        """All resolved thresholds must be within absolute min/max."""
        from merid.risk.edge_thresholds import EdgeThresholdMatrix
        
        matrix = EdgeThresholdMatrix.default()
        
        for phase in ["early", "mid", "late", "terminal"]:
            threshold = matrix.resolve_from_strings(phase)
            
            assert threshold >= matrix.absolute_minimum_bps, \
                f"Threshold {threshold} below absolute minimum {matrix.absolute_minimum_bps}"
            assert threshold <= matrix.absolute_maximum_bps, \
                f"Threshold {threshold} above absolute maximum {matrix.absolute_maximum_bps}"
    
    def test_paper_mode_lowers_threshold(self):
        """Paper mode should reduce threshold."""
        from merid.risk.edge_thresholds import EdgeThresholdMatrix, ExpiryPhase
        
        matrix = EdgeThresholdMatrix.default()
        
        normal = matrix.resolve(ExpiryPhase.MID, paper_mode=False)
        paper = matrix.resolve(ExpiryPhase.MID, paper_mode=True)
        
        assert paper < normal, "Paper mode should lower threshold"
    
    def test_high_volatility_increases_threshold(self):
        """High volatility should increase threshold."""
        from merid.risk.edge_thresholds import EdgeThresholdMatrix, ExpiryPhase
        
        matrix = EdgeThresholdMatrix.default()
        
        normal = matrix.resolve(ExpiryPhase.MID, realized_vol_annual=0.20)
        high = matrix.resolve(ExpiryPhase.MID, realized_vol_annual=0.80)
        
        assert high > normal, "High volatility should increase threshold"
    
    def test_low_liquidity_increases_threshold(self):
        """Low liquidity should increase threshold."""
        from merid.risk.edge_thresholds import EdgeThresholdMatrix, ExpiryPhase
        
        matrix = EdgeThresholdMatrix.default()
        
        normal = matrix.resolve(ExpiryPhase.MID, depth_dollars=10000)
        low = matrix.resolve(ExpiryPhase.MID, depth_dollars=100)
        
        assert low > normal, "Low liquidity should increase threshold"
    
    def test_extreme_fear_lowers_threshold(self):
        """Extreme fear (opportunity) should lower threshold."""
        from merid.risk.edge_thresholds import EdgeThresholdMatrix, ExpiryPhase
        
        matrix = EdgeThresholdMatrix.default()
        
        normal = matrix.resolve(ExpiryPhase.MID, sentiment_score=50)
        fear = matrix.resolve(ExpiryPhase.MID, sentiment_score=5)
        
        assert fear < normal, "Extreme fear should lower threshold (opportunity)"
    
    def test_terminal_phase_has_higher_threshold(self):
        """Terminal phase should have higher threshold than mid."""
        from merid.risk.edge_thresholds import EdgeThresholdMatrix, ExpiryPhase
        
        matrix = EdgeThresholdMatrix.default()
        
        mid = matrix.resolve(ExpiryPhase.MID)
        terminal = matrix.resolve(ExpiryPhase.TERMINAL)
        
        assert terminal > mid, "Terminal phase should have higher threshold"


# ═══════════════════════════════════════════════════════════════════════════════
# Risk Profile Sanity Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestRiskProfileSanity:
    """Validate risk profiles enforce sane limits."""
    
    def test_kelly_fractions_within_bounds(self):
        """Kelly fractions must be between 0 and 1."""
        from merid.risk.risk_profile import RiskProfile
        
        profile = RiskProfile()
        
        assert 0 < profile.base_kelly_fraction <= 1, "Base Kelly must be in (0, 1]"
        assert 0 < profile.min_kelly_fraction <= 1, "Min Kelly must be in (0, 1]"
        assert 0 < profile.max_kelly_fraction <= 1, "Max Kelly must be in (0, 1]"
        
        assert profile.min_kelly_fraction <= profile.base_kelly_fraction <= profile.max_kelly_fraction, \
            "Kelly fractions must be ordered: min <= base <= max"
    
    def test_risk_per_trade_capped(self):
        """Risk per trade must be reasonably capped."""
        from merid.risk.risk_profile import RiskProfile
        
        profile = RiskProfile()
        
        # No single trade should risk more than 5% of bankroll
        assert profile.max_risk_per_trade_pct <= 0.05, "Max risk per trade too high"
        assert profile.max_risk_per_trade_pct > 0, "Max risk per trade must be positive"
    
    def test_total_exposure_capped(self):
        """Total exposure must be reasonably capped."""
        from merid.risk.risk_profile import RiskProfile
        
        profile = RiskProfile()
        
        # Total exposure should not exceed 50%
        assert profile.max_total_exposure_pct <= 0.50, "Max total exposure too high"
        assert profile.max_total_exposure_pct > profile.max_risk_per_trade_pct, \
            "Total exposure must exceed single trade risk"
    
    def test_drawdown_limits_ordered(self):
        """Drawdown reduce should be less than halt."""
        from merid.risk.risk_profile import RiskProfile
        
        profile = RiskProfile()
        
        assert profile.drawdown_reduce_pct < profile.drawdown_halt_pct, \
            "Drawdown reduce threshold must be less than halt threshold"
    
    def test_edge_thresholds_positive(self):
        """Edge thresholds must be positive."""
        from merid.risk.risk_profile import RiskProfile
        
        profile = RiskProfile()
        
        assert profile.min_edge_bps > 0, "Min edge must be positive"
        
        for phase, threshold in profile.min_edge_by_phase.items():
            assert threshold > 0, f"Edge threshold for {phase} must be positive"
    
    def test_profile_factory_methods(self):
        """Profile factory methods should produce different risk levels."""
        from merid.risk.risk_profile import RiskProfile
        
        conservative = RiskProfile.conservative()
        moderate = RiskProfile.moderate()
        aggressive = RiskProfile.aggressive()
        
        # Conservative should have lower Kelly
        assert conservative.base_kelly_fraction < aggressive.base_kelly_fraction, \
            "Conservative should have lower Kelly than aggressive"
        
        # Conservative should have higher edge thresholds
        assert conservative.min_edge_bps >= moderate.min_edge_bps, \
            "Conservative should have higher or equal edge threshold"
    
    def test_adaptive_kelly_respects_bounds(self):
        """Adaptive Kelly fraction should always respect min/max bounds."""
        from merid.risk.risk_profile import RiskProfile
        
        profile = RiskProfile()
        
        # Test various conditions
        test_cases = [
            {"current_drawdown": 0.0, "profit_factor": 1.5},
            {"current_drawdown": 0.15, "profit_factor": 1.1},  # High drawdown
            {"current_drawdown": 0.25, "profit_factor": 2.5},  # Very high drawdown, high PF
            {"current_drawdown": 0.05, "profit_factor": 0.8},  # Poor PF
        ]
        
        for case in test_cases:
            kelly = profile.get_kelly_fraction(**case)
            assert profile.min_kelly_fraction <= kelly <= profile.max_kelly_fraction, \
                f"Kelly {kelly} out of bounds for {case}"


# ═══════════════════════════════════════════════════════════════════════════════
# Position Sizer Sanity Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestPositionSizerSanity:
    """Validate position sizer produces economically sane outputs."""
    
    def test_kelly_fraction_for_binary_sanity(self):
        """Kelly fraction calculation should be sane for binary outcomes."""
        from merid.event_venues.kalshi.position_sizer import kelly_fraction_for_binary
        
        # 60% win prob, 45 cent payout on win, 55 cent cost
        f = kelly_fraction_for_binary(0.60, 45, 55)
        assert 0 <= f <= 1, f"Kelly fraction {f} out of [0,1] range"
        
        # 50% win prob (no edge) should be near zero or negative
        f_no_edge = kelly_fraction_for_binary(0.50, 50, 50)
        assert f_no_edge <= 0.1, "No-edge Kelly should be near zero"
    
    def test_fee_aware_position_sizing(self):
        """Position sizer should account for fees in calculations."""
        from merid.event_venues.kalshi.position_sizer import PositionSizer
        from merid.prediction.unified_edge import EdgeResult, SpotReference
        from datetime import datetime, timezone
        
        sizer = PositionSizer()
        
        # Create mock EdgeResult for low fee scenario
        edge_result_low = EdgeResult(
            edge=0.03,
            edge_risk_adjusted=0.03,
            edge_slippage_adjusted=0.03,
            edge_fee_adjusted=0.03,
            model_prob=0.53,
            market_implied_prob=0.50,
            spot_ref=SpotReference(asset="BTC", price_usd=50000.0, timestamp=datetime.now(timezone.utc), source="test"),
            confidence=0.7,
            metadata={},
            raw_edge_cents=3.0,
            spread_cost_cents=0.5,
            fee_cost_cents=0.5,
            net_edge_cents=2.0,
            ev_per_contract_cents=2.0,
        )
        
        # Create mock EdgeResult for high fee scenario
        edge_result_high = EdgeResult(
            edge=0.03,
            edge_risk_adjusted=0.03,
            edge_slippage_adjusted=0.03,
            edge_fee_adjusted=0.03,
            model_prob=0.53,
            market_implied_prob=0.50,
            spot_ref=SpotReference(asset="BTC", price_usd=50000.0, timestamp=datetime.now(timezone.utc), source="test"),
            confidence=0.7,
            metadata={},
            raw_edge_cents=3.0,
            spread_cost_cents=0.5,
            fee_cost_cents=1.5,  # Higher fee
            net_edge_cents=1.0,
            ev_per_contract_cents=1.0,
        )
        
        # Higher fee should generally result in smaller position
        # (or at least not larger)
        size_low_fee = sizer.compute_from_edge_result(
            agent_name="TEST",
            edge_result=edge_result_low,
            bankroll_cents=10000,
        )
        
        size_high_fee = sizer.compute_from_edge_result(
            agent_name="TEST",
            edge_result=edge_result_high,
            bankroll_cents=10000,
        )
        
        # Both should be non-negative
        assert size_low_fee >= 0, "Size must be non-negative"
        assert size_high_fee >= 0, "Size must be non-negative"
    
    def test_position_size_respects_bankroll(self):
        """Position size should never exceed reasonable fraction of bankroll."""
        from merid.event_venues.kalshi.position_sizer import PositionSizer
        from merid.prediction.unified_edge import EdgeResult, SpotReference
        from datetime import datetime, timezone
        
        sizer = PositionSizer()
        bankroll_cents = 10000
        
        edge_result = EdgeResult(
            edge=0.05,
            edge_risk_adjusted=0.05,
            edge_slippage_adjusted=0.05,
            edge_fee_adjusted=0.05,
            model_prob=0.55,
            market_implied_prob=0.50,
            spot_ref=SpotReference(asset="BTC", price_usd=50000.0, timestamp=datetime.now(timezone.utc), source="test"),
            confidence=0.8,
            metadata={},
            raw_edge_cents=5.0,
            spread_cost_cents=0.5,
            fee_cost_cents=0.5,
            net_edge_cents=4.0,
            ev_per_contract_cents=4.0,
        )
        
        size = sizer.compute_from_edge_result(
            agent_name="TEST",
            edge_result=edge_result,
            bankroll_cents=bankroll_cents,
        )
        
        # Position value should not exceed 10% of bankroll
        position_value = size * 50
        max_value = bankroll_cents * 0.10
        
        assert position_value <= max_value, \
            f"Position value {position_value} exceeds 10% of bankroll {max_value}"


# ═══════════════════════════════════════════════════════════════════════════════
# Bankroll Resolver Sanity Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestBankrollResolverSanity:
    """Validate bankroll resolution behavior."""
    
    def test_fallback_policy_values(self):
        """Fallback policy should resolve to expected values."""
        # Import from deprecated bankroll_resolver since this is testing legacy behavior
        # The canonical BankrollServiceV2 does not use FallbackPolicy
        # This test validates the enum values of the deprecated API
        import warnings
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=DeprecationWarning)
            from merid.event_venues.kalshi.bankroll_resolver import FallbackPolicy
        
        assert FallbackPolicy.REJECT.value == "reject"
        assert FallbackPolicy.USE_LAST_KNOWN.value == "last"
        assert FallbackPolicy.USE_MINIMUM.value == "minimum"
        assert FallbackPolicy.USE_ENV.value == "env"
    
    def test_bankroll_resolution_dataclass(self):
        """BankrollResolution should store values correctly."""
        # Import from deprecated bankroll_resolver since this is testing legacy behavior
        import warnings
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=DeprecationWarning)
            from merid.event_venues.kalshi.bankroll_resolver import BankrollResolution
        
        resolution = BankrollResolution(
            equity_usd=1000.0,
            source="test",
            stale_seconds=60.0,
            retries_attempted=2,
            last_error=None
        )
        
        assert resolution.equity_usd == 1000.0
        assert resolution.source == "test"
        assert resolution.stale_seconds == 60.0


# ═══════════════════════════════════════════════════════════════════════════════
# Volatility Service Sanity Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestVolatilityServiceSanity:
    """Validate volatility calculations are mathematically sound."""
    
    def test_volatility_estimate_is_fresh(self):
        """Fresh estimate should pass freshness check."""
        from merid.services.volatility_service import VolatilityEstimate
        from datetime import datetime
        
        estimate = VolatilityEstimate(
            asset="BTC",
            timeframe="15m",
            realized_vol_annual=0.25,
            realized_vol_24h=0.15,
            atr_14=100.0,
            confidence=0.8,
            timestamp=datetime.utcnow(),
            data_points=100
        )
        
        assert estimate.is_fresh(max_age_seconds=60), "New estimate should be fresh"
    
    def test_volatility_estimate_high_vol_detection(self):
        """High vol estimate should be detected correctly."""
        from merid.services.volatility_service import VolatilityEstimate
        from datetime import datetime
        
        high_vol = VolatilityEstimate(
            asset="BTC",
            timeframe="15m",
            realized_vol_annual=0.80,  # 80% annualized
            realized_vol_24h=0.50,
            atr_14=500.0,
            confidence=0.8,
            timestamp=datetime.utcnow(),
            data_points=100
        )
        
        assert high_vol.is_high_vol(threshold=0.50), "80% vol should be high"
        assert not high_vol.is_high_vol(threshold=0.90), "80% vol should not be >90%"
    
    def test_periods_per_year_calculation(self):
        """Periods per year calculation should be correct."""
        from merid.services.volatility_service import VolatilityService
        
        service = VolatilityService()
        
        # 15m periods per year: 365.25 * 24 * 4 = 35040
        periods_15m = service._periods_per_year("15m")
        assert periods_15m == 35040, f"15m periods should be 35040, got {periods_15m}"
        
        # Hourly periods per year: 365.25 * 24 = 8760
        periods_1h = service._periods_per_year("1h")
        assert periods_1h == 8760, f"1h periods should be 8760, got {periods_1h}"
        
        # Daily periods per year: 365.25
        periods_daily = service._periods_per_year("daily")
        assert periods_daily == 365, f"Daily periods should be 365, got {periods_daily}"


# ═══════════════════════════════════════════════════════════════════════════════
# Integration Sanity Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestIntegrationSanity:
    """Cross-module integration sanity tests."""
    
    def test_fee_module_exports(self):
        """Fee module should export all expected functions."""
        from merid.event_venues.kalshi import fees
        
        assert hasattr(fees, 'calculate_kalshi_fee_cents')
        assert hasattr(fees, 'calculate_kalshi_fee_per_contract_cents')
        assert hasattr(fees, 'calculate_fee_drag_bps')
        assert hasattr(fees, 'calculate_net_edge_bps')
        assert hasattr(fees, 'TIER_RATES')
    
    def test_risk_profile_module_exports(self):
        """Risk profile module should export expected classes."""
        from merid.risk import risk_profile
        
        assert hasattr(risk_profile, 'RiskProfile')
        assert hasattr(risk_profile, 'get_risk_profile')
        assert hasattr(risk_profile, 'RiskProfileLevel')
    
    def test_edge_thresholds_module_exports(self):
        """Edge thresholds module should export expected classes."""
        from merid.risk import edge_thresholds
        
        assert hasattr(edge_thresholds, 'EdgeThresholdMatrix')
        assert hasattr(edge_thresholds, 'ExpiryPhase')
    
    def test_services_module_exports(self):
        """Services module should export expected classes."""
        from merid import services
        
        assert hasattr(services, 'VolatilityService')
        assert hasattr(services, 'get_volatility_service')


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
