"""Unit tests for dynamic window evaluation.

Tests cover:
- Early-window behavior under different vol/spread/depth conditions
- Late-window behavior with different drawdown/execution states
- Staleness and risk state blocking
- Threshold computation logic
"""

import pytest
from datetime import datetime, timedelta, timezone

from merid.event_venues.kalshi.dynamic_window import (
    evaluate_dynamic_window,
    WindowReason,
    DynamicWindowResult,
)


@pytest.fixture
def now():
    """Current UTC time for tests."""
    return datetime.now(timezone.utc)


@pytest.fixture
def strip_start(now):
    """Strip start time (60 seconds ago)."""
    return now - timedelta(seconds=60)


@pytest.fixture
def strip_end(now):
    """Strip end time (600 seconds from now)."""
    return now + timedelta(seconds=600)


class TestEarlyWindowBehavior:
    """Tests for early-side (min_seconds_from_open) logic."""
    
    def test_low_vol_tight_spread_deep_book_allows_early_entry(self, now, strip_start, strip_end):
        """LOW vol, tight spread, deep book should allow early entry (min_from_open near 0-30s)."""
        result = evaluate_dynamic_window(
            now=now,
            strip_start=strip_start,
            strip_end=strip_end,
            spread_cents=2,  # Tight spread
            depth_at_top=50,  # Deep book
            is_stale=False,
            vol_regime="LOW",
            execution_slippage=0.5,
            execution_fill_rate=0.95,
            cooldown_active=False,
            drawdown_state="FLAT",
            recent_invariant_violations=0,
            shadow_mode=False,
        )
        
        assert result.would_allow_trade
        assert result.min_seconds_from_open <= 30  # Should allow early entry
        assert result.reason == WindowReason.ALLOWED
    
    def test_high_vol_wide_spread_delays_entry(self, now, strip_start, strip_end):
        """HIGH vol, wide spread should delay entry (min_from_open near cap)."""
        result = evaluate_dynamic_window(
            now=now,
            strip_start=strip_start,
            strip_end=strip_end,
            spread_cents=8,  # Wide spread
            depth_at_top=10,  # Shallow book
            is_stale=False,
            vol_regime="HIGH",
            execution_slippage=2.0,
            execution_fill_rate=0.8,
            cooldown_active=False,
            drawdown_state="FLAT",
            recent_invariant_violations=0,
            shadow_mode=False,
        )
        
        # With high vol and wide spread, should require more time from open
        assert result.min_seconds_from_open >= 60  # At least 60 seconds
        assert result.min_seconds_from_open <= 120  # Capped at 120 seconds
    
    def test_extreme_vol_max_delay(self, now, strip_start, strip_end):
        """EXTREME vol with wide spread should block due to market quality first."""
        result = evaluate_dynamic_window(
            now=now,
            strip_start=strip_start,
            strip_end=strip_end,
            spread_cents=10,  # Very wide spread - triggers hard block
            depth_at_top=5,  # Very shallow
            is_stale=False,
            vol_regime="EXTREME",
            execution_slippage=4.0,
            execution_fill_rate=0.6,
            cooldown_active=False,
            drawdown_state="FLAT",
            recent_invariant_violations=0,
            shadow_mode=False,
        )
        
        # Spread >= 10c triggers hard block before early window logic
        assert not result.would_allow_trade
        assert result.reason == WindowReason.SPREAD_TOO_WIDE
    
    def test_too_early_blocks_entry(self, now, strip_start, strip_end):
        """Entry blocked if time_since_open < min_seconds_from_open."""
        # Simulate being only 10 seconds after strip open
        early_now = strip_start + timedelta(seconds=10)
        
        result = evaluate_dynamic_window(
            now=early_now,
            strip_start=strip_start,
            strip_end=strip_end,
            spread_cents=5,
            depth_at_top=20,
            is_stale=False,
            vol_regime="NORMAL",
            execution_slippage=1.0,
            execution_fill_rate=0.9,
            cooldown_active=False,
            drawdown_state="FLAT",
            recent_invariant_violations=0,
            shadow_mode=False,
        )
        
        assert not result.would_allow_trade
        assert result.reason in (
            WindowReason.TOO_EARLY_VOL_HIGH,
            WindowReason.TOO_EARLY_SPREAD_WIDE,
            WindowReason.TOO_EARLY_DEPTH_LOW,
            WindowReason.TOO_EARLY_EXECUTION_POOR,
            WindowReason.TOO_EARLY_RECENT_INVARIANT,
        )
    
    def test_recent_invariant_violations_delay_entry(self, now, strip_start, strip_end):
        """Recent invariant violations should delay entry."""
        result = evaluate_dynamic_window(
            now=now,
            strip_start=strip_start,
            strip_end=strip_end,
            spread_cents=3,
            depth_at_top=20,
            is_stale=False,
            vol_regime="NORMAL",
            execution_slippage=1.0,
            execution_fill_rate=0.9,
            cooldown_active=False,
            drawdown_state="FLAT",
            recent_invariant_violations=3,  # 3 recent violations
            shadow_mode=False,
        )
        
        # Should add 60 seconds for 3+ violations
        assert result.min_seconds_from_open >= 60
    
    def test_poor_execution_delays_entry(self, now, strip_start, strip_end):
        """Poor execution quality should delay entry."""
        result = evaluate_dynamic_window(
            now=now,
            strip_start=strip_start,
            strip_end=strip_end,
            spread_cents=3,
            depth_at_top=20,
            is_stale=False,
            vol_regime="NORMAL",
            execution_slippage=4.0,  # High slippage
            execution_fill_rate=0.6,  # Low fill rate
            cooldown_active=False,
            drawdown_state="FLAT",
            recent_invariant_violations=0,
            shadow_mode=False,
        )
        
        # Should add 60 seconds for poor execution
        assert result.min_seconds_from_open >= 60


class TestLateWindowBehavior:
    """Tests for late-side (min_seconds_to_expiry) logic."""
    
    def test_ideal_conditions_standard_threshold(self, now, strip_start, strip_end):
        """Ideal conditions with good execution should use reduced 150s threshold."""
        result = evaluate_dynamic_window(
            now=now,
            strip_start=strip_start,
            strip_end=strip_end,
            spread_cents=3,
            depth_at_top=20,
            is_stale=False,
            vol_regime="NORMAL",
            execution_slippage=0.5,
            execution_fill_rate=0.95,
            cooldown_active=False,
            drawdown_state="FLAT",
            recent_invariant_violations=0,
            shadow_mode=False,
        )
        
        # Implementation uses 150s for ideal conditions (FLAT + good execution)
        assert result.min_seconds_to_expiry == 150  # Reduced for ideal conditions
    
    def test_ideal_conditions_reduced_threshold(self, now, strip_start, strip_end):
        """Ideal conditions (FLAT + good exec) should reduce threshold to 150s."""
        result = evaluate_dynamic_window(
            now=now,
            strip_start=strip_start,
            strip_end=strip_end,
            spread_cents=2,
            depth_at_top=30,
            is_stale=False,
            vol_regime="LOW",
            execution_slippage=0.3,  # Very low slippage
            execution_fill_rate=0.98,  # Very high fill rate
            cooldown_active=False,
            drawdown_state="FLAT",
            recent_invariant_violations=0,
            shadow_mode=False,
        )
        
        assert result.min_seconds_to_expiry == 150  # Reduced for ideal conditions
    
    def test_elevated_drawdown_extended_threshold(self, now, strip_start, strip_end):
        """Elevated drawdown should extend threshold to 240s."""
        result = evaluate_dynamic_window(
            now=now,
            strip_start=strip_start,
            strip_end=strip_end,
            spread_cents=3,
            depth_at_top=20,
            is_stale=False,
            vol_regime="NORMAL",
            execution_slippage=1.0,
            execution_fill_rate=0.9,
            cooldown_active=False,
            drawdown_state="MODERATE",  # Elevated risk
            recent_invariant_violations=0,
            shadow_mode=False,
        )
        
        assert result.min_seconds_to_expiry == 240  # Extended for elevated risk
    
    def test_too_close_to_expiry_blocks_entry(self, now, strip_start, strip_end):
        """Entry blocked if time_to_expiry < min_seconds_to_expiry."""
        # Simulate being only 100 seconds to expiry
        near_expiry_now = strip_end - timedelta(seconds=100)
        
        result = evaluate_dynamic_window(
            now=near_expiry_now,
            strip_start=strip_start,
            strip_end=strip_end,
            spread_cents=3,
            depth_at_top=20,
            is_stale=False,
            vol_regime="NORMAL",
            execution_slippage=1.0,
            execution_fill_rate=0.9,
            cooldown_active=False,
            drawdown_state="FLAT",
            recent_invariant_violations=0,
            shadow_mode=False,
        )
        
        assert not result.would_allow_trade
        assert result.reason == WindowReason.TOO_CLOSE_TO_EXPIRY


class TestMarketQualityGates:
    """Tests for market quality hard blocks."""
    
    def test_stale_book_blocks(self, now, strip_start, strip_end):
        """Stale book should block trading."""
        result = evaluate_dynamic_window(
            now=now,
            strip_start=strip_start,
            strip_end=strip_end,
            spread_cents=3,
            depth_at_top=20,
            is_stale=True,  # Stale
            vol_regime="NORMAL",
            execution_slippage=1.0,
            execution_fill_rate=0.9,
            cooldown_active=False,
            drawdown_state="FLAT",
            recent_invariant_violations=0,
            shadow_mode=False,
        )
        
        assert not result.would_allow_trade
        assert result.reason == WindowReason.BOOK_STALE
    
    def test_wide_spread_blocks(self, now, strip_start, strip_end):
        """Wide spread (>=10c) should block trading."""
        result = evaluate_dynamic_window(
            now=now,
            strip_start=strip_start,
            strip_end=strip_end,
            spread_cents=12,  # Too wide
            depth_at_top=20,
            is_stale=False,
            vol_regime="NORMAL",
            execution_slippage=1.0,
            execution_fill_rate=0.9,
            cooldown_active=False,
            drawdown_state="FLAT",
            recent_invariant_violations=0,
            shadow_mode=False,
        )
        
        assert not result.would_allow_trade
        assert result.reason == WindowReason.SPREAD_TOO_WIDE
    
    def test_shallow_depth_blocks(self, now, strip_start, strip_end):
        """Shallow depth (<5) should block trading."""
        result = evaluate_dynamic_window(
            now=now,
            strip_start=strip_start,
            strip_end=strip_end,
            spread_cents=3,
            depth_at_top=3,  # Too shallow
            is_stale=False,
            vol_regime="NORMAL",
            execution_slippage=1.0,
            execution_fill_rate=0.9,
            cooldown_active=False,
            drawdown_state="FLAT",
            recent_invariant_violations=0,
            shadow_mode=False,
        )
        
        assert not result.would_allow_trade
        assert result.reason == WindowReason.DEPTH_TOO_LOW


class TestRiskStateGates:
    """Tests for risk state hard blocks."""
    
    def test_cooldown_active_blocks(self, now, strip_start, strip_end):
        """Active cooldown should block trading."""
        result = evaluate_dynamic_window(
            now=now,
            strip_start=strip_start,
            strip_end=strip_end,
            spread_cents=3,
            depth_at_top=20,
            is_stale=False,
            vol_regime="NORMAL",
            execution_slippage=1.0,
            execution_fill_rate=0.9,
            cooldown_active=True,  # Cooldown active
            drawdown_state="FLAT",
            recent_invariant_violations=0,
            shadow_mode=False,
        )
        
        assert not result.would_allow_trade
        assert result.reason == WindowReason.COOLDOWN_ACTIVE
    
    def test_severe_drawdown_blocks(self, now, strip_start, strip_end):
        """SEVERE drawdown should block trading."""
        result = evaluate_dynamic_window(
            now=now,
            strip_start=strip_start,
            strip_end=strip_end,
            spread_cents=3,
            depth_at_top=20,
            is_stale=False,
            vol_regime="NORMAL",
            execution_slippage=1.0,
            execution_fill_rate=0.9,
            cooldown_active=False,
            drawdown_state="SEVERE",  # Severe drawdown
            recent_invariant_violations=0,
            shadow_mode=False,
        )
        
        assert not result.would_allow_trade
        assert result.reason == WindowReason.DAILY_LOSS_LIMIT
    
    def test_critical_drawdown_blocks(self, now, strip_start, strip_end):
        """CRITICAL drawdown should block trading."""
        result = evaluate_dynamic_window(
            now=now,
            strip_start=strip_start,
            strip_end=strip_end,
            spread_cents=3,
            depth_at_top=20,
            is_stale=False,
            vol_regime="NORMAL",
            execution_slippage=1.0,
            execution_fill_rate=0.9,
            cooldown_active=False,
            drawdown_state="CRITICAL",  # Critical drawdown
            recent_invariant_violations=0,
            shadow_mode=False,
        )
        
        assert not result.would_allow_trade
        assert result.reason == WindowReason.DAILY_LOSS_LIMIT


class TestResultStructure:
    """Tests for DynamicWindowResult structure and metadata."""
    
    def test_result_contains_all_fields(self, now, strip_start, strip_end):
        """Result should contain all expected fields."""
        result = evaluate_dynamic_window(
            now=now,
            strip_start=strip_start,
            strip_end=strip_end,
            spread_cents=3,
            depth_at_top=20,
            is_stale=False,
            vol_regime="NORMAL",
            execution_slippage=1.0,
            execution_fill_rate=0.9,
            cooldown_active=False,
            drawdown_state="FLAT",
            recent_invariant_violations=0,
            shadow_mode=False,
        )
        
        assert isinstance(result, DynamicWindowResult)
        assert hasattr(result, 'would_allow_trade')
        assert hasattr(result, 'reason')
        assert hasattr(result, 'min_seconds_from_open')
        assert hasattr(result, 'min_seconds_to_expiry')
        assert hasattr(result, 'time_since_open')
        assert hasattr(result, 'time_to_expiry')
        assert hasattr(result, 'vol_regime')
        assert hasattr(result, 'spread_cents')
        assert hasattr(result, 'depth_at_top')
        assert hasattr(result, 'is_stale')
        assert hasattr(result, 'execution_slippage')
        assert hasattr(result, 'execution_fill_rate')
        assert hasattr(result, 'cooldown_active')
        assert hasattr(result, 'drawdown_state')
        assert hasattr(result, 'rationale')
        assert hasattr(result, 'computation_time_ms')
    
    def test_computation_time_is_reasonable(self, now, strip_start, strip_end):
        """Computation time should be reasonable (<10ms)."""
        result = evaluate_dynamic_window(
            now=now,
            strip_start=strip_start,
            strip_end=strip_end,
            spread_cents=3,
            depth_at_top=20,
            is_stale=False,
            vol_regime="NORMAL",
            execution_slippage=1.0,
            execution_fill_rate=0.9,
            cooldown_active=False,
            drawdown_state="FLAT",
            recent_invariant_violations=0,
            shadow_mode=False,
        )
        
        assert result.computation_time_ms < 10  # Should be very fast
    
    def test_rationale_is_informative(self, now, strip_start, strip_end):
        """Rationale should contain useful information."""
        result = evaluate_dynamic_window(
            now=now,
            strip_start=strip_start,
            strip_end=strip_end,
            spread_cents=3,
            depth_at_top=20,
            is_stale=False,
            vol_regime="NORMAL",
            execution_slippage=1.0,
            execution_fill_rate=0.9,
            cooldown_active=False,
            drawdown_state="FLAT",
            recent_invariant_violations=0,
            shadow_mode=False,
        )
        
        assert len(result.rationale) > 0
        # Should mention key factors
        assert any(keyword in result.rationale.lower() for keyword in ["vol", "spread", "depth", "seconds"])


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
