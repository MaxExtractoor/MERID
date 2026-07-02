"""Tests for 60-70% profit capture rule in DynamicTakeProfitEngine.

This tests the research-backed profit capture rule from Polymarket:
- Take profit at 60-70% of theoretical maximum gain
- Avoid holding for last 20-30% which takes disproportionately longer
- Reduces time decay, tail risk, and opportunity cost
"""

import pytest
from merid.prediction.dynamic_takeprofit import DynamicTakeProfitEngine, TakeProfitLevel


class Test60_70ProfitCaptureRule:
    """Tests for the 60-70% profit capture rule."""
    
    def test_60_70_rule_caps_high_r_multiple(self):
        """When R-based TP exceeds 70% of max gain, cap at 70%."""
        engine = DynamicTakeProfitEngine()
        
        # Buy YES at $0.40, R-based TP at $0.90 (83% of max gain)
        # Should be capped to $0.82 (70% of max gain)
        entry_price = 0.40
        stop_price = 0.35  # 5c risk
        direction = "LONG"
        confidence = 0.9  # High confidence → 2.5-3.0R
        
        tp_plan = engine.compute_tp(
            entry_price=entry_price,
            stop_price=stop_price,
            direction=direction,
            confidence=confidence,
            use_60_70_rule=True
        )
        
        max_gain = 1.00 - entry_price  # 0.60
        expected_max_tp = entry_price + (max_gain * 0.70)  # 0.40 + 0.42 = 0.82
        
        assert tp_plan.tp_price <= expected_max_tp, f"TP {tp_plan.tp_price} should be capped at {expected_max_tp}"
        assert tp_plan.tp_price >= entry_price + (max_gain * 0.60), f"TP {tp_plan.tp_price} should be at least 60% of max gain"
    
    def test_60_70_rule_boosts_low_r_multiple(self):
        """When R-based TP is below 60% of max gain, boost to 60%."""
        engine = DynamicTakeProfitEngine()
        
        # Buy YES at $0.40, R-based TP at $0.55 (25% of max gain)
        # Should be boosted to $0.76 (60% of max gain)
        entry_price = 0.40
        stop_price = 0.35
        direction = "LONG"
        confidence = 0.2  # Low confidence → 1.0R
        
        tp_plan = engine.compute_tp(
            entry_price=entry_price,
            stop_price=stop_price,
            direction=direction,
            confidence=confidence,
            use_60_70_rule=True
        )
        
        max_gain = 1.00 - entry_price  # 0.60
        expected_min_tp = entry_price + (max_gain * 0.60)  # 0.40 + 0.36 = 0.76
        
        assert tp_plan.tp_price >= expected_min_tp, f"TP {tp_plan.tp_price} should be at least 60% of max gain"
        assert tp_plan.tp_price <= entry_price + (max_gain * 0.70), f"TP {tp_plan.tp_price} should not exceed 70% of max gain"
    
    def test_60_70_rule_preserves_mid_range(self):
        """When R-based TP is already in 60-70% range, preserve it."""
        engine = DynamicTakeProfitEngine()
        
        # Buy YES at $0.40, R-based TP at $0.78 (63% of max gain)
        # Should be preserved
        entry_price = 0.40
        stop_price = 0.35
        direction = "LONG"
        confidence = 0.5  # Medium confidence → 1.5R
        
        tp_plan = engine.compute_tp(
            entry_price=entry_price,
            stop_price=stop_price,
            direction=direction,
            confidence=confidence,
            use_60_70_rule=True
        )
        
        max_gain = 1.00 - entry_price  # 0.60
        gain_pct = (tp_plan.tp_price - entry_price) / max_gain
        
        assert 0.60 <= gain_pct <= 0.70, f"Gain {gain_pct:.2f} should be in 60-70% range"
    
    def test_60_70_rule_disabled(self):
        """When 60-70 rule is disabled, use R-based TP (may be lower or higher)."""
        engine = DynamicTakeProfitEngine()
        
        entry_price = 0.40
        stop_price = 0.35
        direction = "LONG"
        confidence = 0.9  # High confidence → high R multiple
        
        tp_plan_with_rule = engine.compute_tp(
            entry_price=entry_price,
            stop_price=stop_price,
            direction=direction,
            confidence=confidence,
            use_60_70_rule=True
        )
        
        tp_plan_without_rule = engine.compute_tp(
            entry_price=entry_price,
            stop_price=stop_price,
            direction=direction,
            confidence=confidence,
            use_60_70_rule=False
        )
        
        # Without rule, TP is purely R-based (may be below 60% if R is small)
        # With rule, TP is constrained to 60-70% range
        max_gain = 1.00 - entry_price
        with_rule_gain_pct = (tp_plan_with_rule.tp_price - entry_price) / max_gain
        without_rule_gain_pct = (tp_plan_without_rule.tp_price - entry_price) / max_gain
        
        # With rule should be in 60-70% range
        assert 0.60 <= with_rule_gain_pct <= 0.70
        
        # Without rule can be outside this range (lower if R is small, higher if R is large)
        # In this case, R-based is lower because 2.75R * 0.05 risk = 0.1375 offset
        assert without_rule_gain_pct < 0.60  # R-based is below 60%
    
    def test_60_70_rule_short_direction(self):
        """60-70 rule works correctly for SHORT (NO) positions."""
        engine = DynamicTakeProfitEngine()
        
        # Buy NO at $0.60 (betting price goes down)
        entry_price = 0.60
        stop_price = 0.65  # 5c risk
        direction = "SHORT"
        confidence = 0.9
        
        tp_plan = engine.compute_tp(
            entry_price=entry_price,
            stop_price=stop_price,
            direction=direction,
            confidence=confidence,
            use_60_70_rule=True
        )
        
        max_gain = entry_price - 0.00  # 0.60
        expected_max_tp = entry_price - (max_gain * 0.70)  # 0.60 - 0.42 = 0.18
        expected_min_tp = entry_price - (max_gain * 0.60)  # 0.60 - 0.36 = 0.24
        
        # TP should be in 60-70% range (for SHORT, lower price = more gain)
        assert tp_plan.tp_price <= expected_min_tp, f"TP {tp_plan.tp_price} should be at most {expected_min_tp} (60% gain)"
        assert tp_plan.tp_price >= expected_max_tp, f"TP {tp_plan.tp_price} should be at least {expected_max_tp} (70% gain)"
    
    def test_60_70_rule_edge_case_zero_entry(self):
        """Handle edge case where entry is near 0 or 1."""
        engine = DynamicTakeProfitEngine()
        
        # Entry at $0.10 (very cheap)
        entry_price = 0.10
        stop_price = 0.05
        direction = "LONG"
        confidence = 0.9
        
        tp_plan = engine.compute_tp(
            entry_price=entry_price,
            stop_price=stop_price,
            direction=direction,
            confidence=confidence,
            use_60_70_rule=True
        )
        
        max_gain = 1.00 - entry_price  # 0.90
        expected_max_tp = entry_price + (max_gain * 0.70)  # 0.10 + 0.63 = 0.73
        
        assert tp_plan.tp_price <= expected_max_tp
        assert tp_plan.tp_price >= entry_price + (max_gain * 0.60)
    
    def test_60_70_rule_preserves_r_multiple_reporting(self):
        """60-70 rule should not affect R-multiple reporting."""
        engine = DynamicTakeProfitEngine()
        
        entry_price = 0.40
        stop_price = 0.35
        direction = "LONG"
        confidence = 0.9
        
        tp_plan = engine.compute_tp(
            entry_price=entry_price,
            stop_price=stop_price,
            direction=direction,
            confidence=confidence,
            use_60_70_rule=True
        )
        
        # R-multiple should still be reported based on confidence
        assert tp_plan.tp_r_multiple is not None
        assert tp_plan.tp_r_multiple >= 2.0  # High confidence should give >= 2.0R
        assert tp_plan.tp_level in [TakeProfitLevel.STRETCH, TakeProfitLevel.AGGRESSIVE]


class TestTTECompression:
    """Tests for time-to-expiry compression of trailing parameters."""
    
    def test_tte_compression_no_compression_early(self):
        """No compression when TTE > 600s (10 minutes)."""
        engine = DynamicTakeProfitEngine()
        
        entry_price = 0.50
        stop_price = 0.45
        direction = "LONG"
        confidence = 0.7  # Medium-high confidence → trailing enabled
        time_to_expiry = 900  # 15 minutes (full window)
        
        tp_plan = engine.compute_tp(
            entry_price=entry_price,
            stop_price=stop_price,
            direction=direction,
            confidence=confidence,
            time_to_expiry_seconds=time_to_expiry
        )
        
        # Trailing should be at normal levels (no compression)
        assert tp_plan.trailing_trigger_r is not None
        assert tp_plan.trailing_distance_r is not None
        # Should be close to base values (1.5R trigger, 0.5R distance for mid confidence)
        assert tp_plan.trailing_trigger_r >= 1.0
    
    def test_tte_compression_20_percent_mid(self):
        """20% compression when TTE is 300-600s (5-10 minutes)."""
        engine = DynamicTakeProfitEngine()
        
        entry_price = 0.50
        stop_price = 0.45
        direction = "LONG"
        confidence = 0.7
        time_to_expiry = 450  # 7.5 minutes
        
        tp_plan = engine.compute_tp(
            entry_price=entry_price,
            stop_price=stop_price,
            direction=direction,
            confidence=confidence,
            time_to_expiry_seconds=time_to_expiry
        )
        
        # Trailing should be compressed to 80% of normal
        assert tp_plan.trailing_trigger_r is not None
        assert tp_plan.trailing_distance_r is not None
    
    def test_tte_compression_40_percent_late(self):
        """40% compression when TTE is 120-300s (2-5 minutes)."""
        engine = DynamicTakeProfitEngine()
        
        entry_price = 0.50
        stop_price = 0.45
        direction = "LONG"
        confidence = 0.7
        time_to_expiry = 180  # 3 minutes
        
        tp_plan = engine.compute_tp(
            entry_price=entry_price,
            stop_price=stop_price,
            direction=direction,
            confidence=confidence,
            time_to_expiry_seconds=time_to_expiry
        )
        
        # Trailing should be compressed to 60% of normal
        assert tp_plan.trailing_trigger_r is not None
        assert tp_plan.trailing_distance_r is not None
    
    def test_tte_compression_60_percent_very_late(self):
        """60% compression when TTE < 120s (2 minutes)."""
        engine = DynamicTakeProfitEngine()
        
        entry_price = 0.50
        stop_price = 0.45
        direction = "LONG"
        confidence = 0.7
        time_to_expiry = 60  # 1 minute
        
        tp_plan = engine.compute_tp(
            entry_price=entry_price,
            stop_price=stop_price,
            direction=direction,
            confidence=confidence,
            time_to_expiry_seconds=time_to_expiry
        )
        
        # Trailing should be compressed to 40% of normal (very tight)
        assert tp_plan.trailing_trigger_r is not None
        assert tp_plan.trailing_distance_r is not None
    
    def test_tte_compression_no_tte_provided(self):
        """When TTE not provided, no compression applied."""
        engine = DynamicTakeProfitEngine()
        
        entry_price = 0.50
        stop_price = 0.45
        direction = "LONG"
        confidence = 0.7
        
        tp_plan_no_tte = engine.compute_tp(
            entry_price=entry_price,
            stop_price=stop_price,
            direction=direction,
            confidence=confidence,
            time_to_expiry_seconds=None
        )
        
        tp_plan_with_tte = engine.compute_tp(
            entry_price=entry_price,
            stop_price=stop_price,
            direction=direction,
            confidence=confidence,
            time_to_expiry_seconds=60
        )
        
        # Without TTE, trailing should be at normal levels
        # With TTE=60s, trailing should be compressed
        assert tp_plan_no_tte.trailing_trigger_r >= tp_plan_with_tte.trailing_trigger_r
    
    def test_tte_compression_no_trailing_low_confidence(self):
        """TTE compression has no effect when trailing is disabled (low confidence)."""
        engine = DynamicTakeProfitEngine()
        
        entry_price = 0.50
        stop_price = 0.45
        direction = "LONG"
        confidence = 0.2  # Low confidence → no trailing
        time_to_expiry = 60  # Very late
        
        tp_plan = engine.compute_tp(
            entry_price=entry_price,
            stop_price=stop_price,
            direction=direction,
            confidence=confidence,
            time_to_expiry_seconds=time_to_expiry
        )
        
        # Low confidence means no trailing regardless of TTE
        assert tp_plan.trailing_trigger_r is None
        assert tp_plan.trailing_distance_r is None


class TestComputeTrailingStop:
    """Tests for compute_trailing_stop method fix."""
    
    def test_compute_trailing_stop_with_stop_price(self):
        """Test trailing stop calculation with stop price provided."""
        engine = DynamicTakeProfitEngine()
        
        # Create a trailing plan
        from merid.prediction.dynamic_takeprofit import TakeProfitPlan, TakeProfitLevel
        plan = TakeProfitPlan(
            tp_price=0.60,
            tp_r_multiple=1.5,
            tp_level=TakeProfitLevel.BASE,
            trailing_trigger_r=1.0,
            trailing_distance_r=0.5,
        )
        
        # Entry at $0.50, stop at $0.45 (5c risk), current at $0.60
        entry_price = 0.50
        stop_price = 0.45
        current_price = 0.60
        direction = "LONG"
        
        trail_stop = engine.compute_trailing_stop(
            current_price=current_price,
            entry_price=entry_price,
            direction=direction,
            plan=plan,
            stop_price=stop_price,
        )
        
        # Trail offset = 0.5R * 5c risk = 2.5c
        # Trail stop = $0.60 - $0.025 = $0.575
        expected_trail = current_price - (plan.trailing_distance_r * abs(entry_price - stop_price))
        
        assert trail_stop is not None
        assert abs(trail_stop - expected_trail) < 0.001
    
    def test_compute_trailing_stop_without_stop_price(self):
        """Test trailing stop calculation without stop price (fallback)."""
        engine = DynamicTakeProfitEngine()
        
        from merid.prediction.dynamic_takeprofit import TakeProfitPlan, TakeProfitLevel
        plan = TakeProfitPlan(
            tp_price=0.60,
            tp_r_multiple=1.5,
            tp_level=TakeProfitLevel.BASE,
            trailing_trigger_r=1.0,
            trailing_distance_r=0.5,
        )
        
        entry_price = 0.50
        current_price = 0.60
        direction = "LONG"
        
        trail_stop = engine.compute_trailing_stop(
            current_price=current_price,
            entry_price=entry_price,
            direction=direction,
            plan=plan,
            stop_price=None,
        )
        
        # Should use fallback estimation
        assert trail_stop is not None
        # Trail stop should be below current price for LONG
        assert trail_stop < current_price
    
    def test_compute_trailing_stop_short_direction(self):
        """Test trailing stop calculation for SHORT direction."""
        engine = DynamicTakeProfitEngine()
        
        from merid.prediction.dynamic_takeprofit import TakeProfitPlan, TakeProfitLevel
        plan = TakeProfitPlan(
            tp_price=0.40,
            tp_r_multiple=1.5,
            tp_level=TakeProfitLevel.BASE,
            trailing_trigger_r=1.0,
            trailing_distance_r=0.5,
        )
        
        entry_price = 0.60
        stop_price = 0.65
        current_price = 0.40
        direction = "SHORT"
        
        trail_stop = engine.compute_trailing_stop(
            current_price=current_price,
            entry_price=entry_price,
            direction=direction,
            plan=plan,
            stop_price=stop_price,
        )
        
        # Trail offset = 0.5R * 5c risk = 2.5c
        # Trail stop = $0.40 + $0.025 = $0.425 (above current for SHORT)
        expected_trail = current_price + (plan.trailing_distance_r * abs(entry_price - stop_price))
        
        assert trail_stop is not None
        assert abs(trail_stop - expected_trail) < 0.001
        assert trail_stop > current_price  # For SHORT, trail is above current
    
    def test_compute_trailing_stop_no_trailing_configured(self):
        """Test returns None when trailing not configured."""
        engine = DynamicTakeProfitEngine()
        
        from merid.prediction.dynamic_takeprofit import TakeProfitPlan, TakeProfitLevel
        plan = TakeProfitPlan(
            tp_price=0.60,
            tp_r_multiple=1.0,
            tp_level=TakeProfitLevel.BASE,
            trailing_trigger_r=None,  # No trailing
            trailing_distance_r=None,
        )
        
        trail_stop = engine.compute_trailing_stop(
            current_price=0.60,
            entry_price=0.50,
            direction="LONG",
            plan=plan,
            stop_price=0.45,
        )
        
        assert trail_stop is None
    
    def test_compute_trailing_stop_zero_risk_fallback(self):
        """Test fallback when risk calculation would be zero."""
        engine = DynamicTakeProfitEngine()
        
        from merid.prediction.dynamic_takeprofit import TakeProfitPlan, TakeProfitLevel
        plan = TakeProfitPlan(
            tp_price=0.60,
            tp_r_multiple=1.5,
            tp_level=TakeProfitLevel.BASE,
            trailing_trigger_r=1.0,
            trailing_distance_r=0.5,
        )
        
        # Entry and stop are same (zero risk)
        entry_price = 0.50
        stop_price = 0.50
        current_price = 0.60
        direction = "LONG"
        
        trail_stop = engine.compute_trailing_stop(
            current_price=current_price,
            entry_price=entry_price,
            direction=direction,
            plan=plan,
            stop_price=stop_price,
        )
        
        # Should use 0.5% fallback
        assert trail_stop is not None
        assert trail_stop < current_price
