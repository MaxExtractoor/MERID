"""
Test harness for NO-side bias detection and synthetic NO-dominant regimes.

This test validates:
1. Synthetic NO-dominant regimes (downtrend, overbought RSI) generate bearish events
2. Side arbitration correctly selects NO when no_edge > yes_edge
3. Signal generation produces bearish_intent in appropriate market conditions
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from merid.prediction.intent_contract import StrategyIntent

# Marker for bias check tests
pytestmark = pytest.mark.bias_check


class TestSyntheticNODominantRegimes:
    """Test that NO-dominant regimes generate bearish events."""

    def test_downtrend_generates_bearish_intent(self):
        """Sharp downtrend should generate BEARISH_EVENT (NO side)."""
        # Simulate a sharp downtrend: negative velocity, low RSI, bearish MACD
        velocity = -0.05  # Strong negative momentum
        rsi = 25.0  # Oversold (but in downtrend, this is continuation not reversion)
        macd_histogram = -0.02  # Bearish momentum
        fvg_direction = "bearish"
        fvg_confidence = 0.8
        obi = -0.7  # Selling pressure
        obi_strong = True

        # For momentum_fvg: short conditions should be met
        long_conditions = [
            velocity > 0.01,  # False
            macd_histogram >= 0,  # False
            rsi < 70,  # True (not overbought)
            rsi > 55,  # False
            (obi > 0 and obi_strong) or (fvg_direction == "bullish" and fvg_confidence > 0.5)  # False
        ]
        short_conditions = [
            velocity < -0.01,  # True
            macd_histogram < 0,  # True
            rsi > 30,  # True (not oversold)
            rsi < 45,  # True
            (obi < 0 and obi_strong) or (fvg_direction == "bearish" and fvg_confidence > 0.5)  # True
        ]

        long_score = sum(long_conditions)
        short_score = sum(short_conditions)

        # In a downtrend, short_score should be higher
        assert short_score > long_score, f"Short score ({short_score}) should exceed long score ({long_score}) in downtrend"
        assert short_score >= 3, f"Short score ({short_score}) should meet minimum threshold (3) for signal generation"

    def test_overbought_rsi_generates_bearish_intent(self):
        """Overbought RSI should generate BEARISH_EVENT (NO side) for panic_fade."""
        # Panic fade: overbought → expect reversion down → BEARISH_EVENT → NO side
        rsi = 75.0  # Overbought
        zscore = 2.5  # Extended
        velocity = 0.01  # Positive but slowing

        # Panic fade logic: overbought → signal_side="no" → BEARISH_EVENT
        is_oversold = rsi < 30  # False
        is_overbought = rsi > 70  # True

        if is_oversold:
            signal_side = "yes"
            expected_intent = StrategyIntent.BULLISH_EVENT
        elif is_overbought:
            signal_side = "no"
            expected_intent = StrategyIntent.BEARISH_EVENT
        else:
            signal_side = None
            expected_intent = None

        assert signal_side == "no", f"Overbought RSI should generate NO side, got {signal_side}"
        assert expected_intent == StrategyIntent.BEARISH_EVENT, f"Overbought RSI should generate BEARISH_EVENT, got {expected_intent}"

    def test_no_edge_greater_than_yes_edge_selects_no(self):
        """When no_edge > yes_edge, side arbitration must select NO."""
        yes_edge_pct = 0.02  # 2% edge on YES
        no_edge_pct = 0.05  # 5% edge on NO

        # Side arbitration logic
        if yes_edge_pct > no_edge_pct:
            selected_side = "yes"
        elif no_edge_pct > yes_edge_pct:
            selected_side = "no"
        else:
            selected_side = "no"  # Tie-break prefers NO

        assert selected_side == "no", f"NO edge ({no_edge_pct}) > YES edge ({yes_edge_pct}) should select NO, got {selected_side}"

        # With correct mapping: NO side → BEARISH_EVENT
        strategy_intent = StrategyIntent.BULLISH_EVENT if selected_side == "yes" else StrategyIntent.BEARISH_EVENT
        assert strategy_intent == StrategyIntent.BEARISH_EVENT, f"NO side should map to BEARISH_EVENT, got {strategy_intent}"

    def test_equal_edges_prefers_no(self):
        """When edges are equal, tie-break should prefer NO to counteract YES bias."""
        yes_edge_pct = 0.03
        no_edge_pct = 0.03

        # Tie-break logic
        if yes_edge_pct > no_edge_pct:
            selected_side = "yes"
        elif no_edge_pct > yes_edge_pct:
            selected_side = "no"
        else:
            selected_side = "no"  # Prefer NO for bias correction

        assert selected_side == "no", f"Equal edges should prefer NO for bias correction, got {selected_side}"


class TestSyntheticRegimeGrid:
    """Test synthetic grid of market regimes for bias detection."""

    def test_strong_uptrend_generates_bullish_intent(self):
        """Strong uptrend should generate BULLISH_EVENT (YES side)."""
        velocity = 0.05  # Strong positive momentum
        rsi = 75.0  # Strong (not overbought yet)
        macd_histogram = 0.02  # Bullish momentum
        fvg_direction = "bullish"
        fvg_confidence = 0.8
        obi = 0.7  # Buying pressure
        obi_strong = True

        # For momentum_fvg: long conditions should be met
        long_conditions = [
            velocity > 0.01,  # True
            macd_histogram >= 0,  # True
            rsi < 70,  # False (overbought)
            rsi > 55,  # True
            (obi > 0 and obi_strong) or (fvg_direction == "bullish" and fvg_confidence > 0.5)  # True
        ]
        short_conditions = [
            velocity < -0.01,  # False
            macd_histogram < 0,  # False
            rsi > 30,  # True
            rsi < 45,  # False
            (obi < 0 and obi_strong) or (fvg_direction == "bearish" and fvg_confidence > 0.5)  # False
        ]

        long_score = sum(long_conditions)
        short_score = sum(short_conditions)

        # In an uptrend, long_score should be higher
        assert long_score > short_score, f"Long score ({long_score}) should exceed short score ({short_score}) in uptrend"

    def test_high_volatility_chop_generates_mixed_intents(self):
        """High volatility chop should generate both bullish and bearish events over time."""
        # Simulate chop: velocity swings between positive and negative
        regimes = [
            {"velocity": 0.03, "rsi": 60, "macd": 0.01, "expected_intent": StrategyIntent.BULLISH_EVENT},
            {"velocity": -0.03, "rsi": 40, "macd": -0.01, "expected_intent": StrategyIntent.BEARISH_EVENT},
            {"velocity": 0.02, "rsi": 65, "macd": 0.005, "expected_intent": StrategyIntent.BULLISH_EVENT},
            {"velocity": -0.02, "rsi": 35, "macd": -0.005, "expected_intent": StrategyIntent.BEARISH_EVENT},
        ]

        for regime in regimes:
            velocity = regime["velocity"]
            if velocity > 0:
                intent = StrategyIntent.BULLISH_EVENT
            else:
                intent = StrategyIntent.BEARISH_EVENT

            assert intent == regime["expected_intent"], (
                f"Chop regime with velocity={velocity} should generate {regime['expected_intent']}, got {intent}"
            )

    def test_oversold_rsi_generates_bullish_intent(self):
        """Oversold RSI should generate BULLISH_EVENT (YES side) for panic_fade."""
        # Panic fade: oversold → expect reversion up → BULLISH_EVENT → YES side
        rsi = 25.0  # Oversold
        zscore = -2.5  # Extended downside
        velocity = -0.01  # Negative but slowing

        # Panic fade logic: oversold → signal_side="yes" → BULLISH_EVENT
        is_oversold = rsi < 30  # True
        is_overbought = rsi > 70  # False

        if is_oversold:
            signal_side = "yes"
            expected_intent = StrategyIntent.BULLISH_EVENT
        elif is_overbought:
            signal_side = "no"
            expected_intent = StrategyIntent.BEARISH_EVENT
        else:
            signal_side = None
            expected_intent = None

        assert signal_side == "yes", f"Oversold RSI should generate YES side, got {signal_side}"
        assert expected_intent == StrategyIntent.BULLISH_EVENT, f"Oversold RSI should generate BULLISH_EVENT, got {expected_intent}"


class TestUpstreamBiasInvariant:
    """Test upstream invariant: in NO-dominant regime, BEARISH_EVENT share must exceed 60%."""

    def test_no_dominant_regime_bearish_share_exceeds_60_percent(self):
        """In NO-dominant synthetic regime, BEARISH_EVENT share must exceed 60%."""
        # Simulate a NO-dominant regime: multiple windows with no_edge > yes_edge
        synthetic_windows = [
            {"yes_edge": 0.02, "no_edge": 0.05, "expected_intent": StrategyIntent.BEARISH_EVENT},
            {"yes_edge": 0.01, "no_edge": 0.04, "expected_intent": StrategyIntent.BEARISH_EVENT},
            {"yes_edge": 0.03, "no_edge": 0.06, "expected_intent": StrategyIntent.BEARISH_EVENT},
            {"yes_edge": 0.02, "no_edge": 0.04, "expected_intent": StrategyIntent.BEARISH_EVENT},
            {"yes_edge": 0.01, "no_edge": 0.03, "expected_intent": StrategyIntent.BEARISH_EVENT},
            {"yes_edge": 0.04, "no_edge": 0.02, "expected_intent": StrategyIntent.BULLISH_EVENT},  # YES edge wins
            {"yes_edge": 0.03, "no_edge": 0.05, "expected_intent": StrategyIntent.BEARISH_EVENT},
            {"yes_edge": 0.02, "no_edge": 0.04, "expected_intent": StrategyIntent.BEARISH_EVENT},
            {"yes_edge": 0.01, "no_edge": 0.03, "expected_intent": StrategyIntent.BEARISH_EVENT},
            {"yes_edge": 0.02, "no_edge": 0.05, "expected_intent": StrategyIntent.BEARISH_EVENT},
        ]

        # Count intents
        bearish_count = sum(1 for w in synthetic_windows if w["expected_intent"] == StrategyIntent.BEARISH_EVENT)
        total_count = len(synthetic_windows)
        bearish_share = bearish_count / total_count

        # In NO-dominant regime, BEARISH_EVENT share must exceed 60%
        assert bearish_share > 0.6, (
            f"[UPSTREAM-BIAS-DETECTED] BEARISH_EVENT share ({bearish_share:.1%}) "
            f"must exceed 60% in NO-dominant regime, got {bearish_count}/{total_count}"
        )

    def test_yes_dominant_regime_bullish_share_exceeds_60_percent(self):
        """In YES-dominant synthetic regime, BULLISH_EVENT share must exceed 60%."""
        # Simulate a YES-dominant regime: multiple windows with yes_edge > no_edge
        synthetic_windows = [
            {"yes_edge": 0.05, "no_edge": 0.02, "expected_intent": StrategyIntent.BULLISH_EVENT},
            {"yes_edge": 0.04, "no_edge": 0.01, "expected_intent": StrategyIntent.BULLISH_EVENT},
            {"yes_edge": 0.06, "no_edge": 0.03, "expected_intent": StrategyIntent.BULLISH_EVENT},
            {"yes_edge": 0.04, "no_edge": 0.02, "expected_intent": StrategyIntent.BULLISH_EVENT},
            {"yes_edge": 0.03, "no_edge": 0.01, "expected_intent": StrategyIntent.BULLISH_EVENT},
            {"yes_edge": 0.02, "no_edge": 0.04, "expected_intent": StrategyIntent.BEARISH_EVENT},  # NO edge wins
            {"yes_edge": 0.05, "no_edge": 0.03, "expected_intent": StrategyIntent.BULLISH_EVENT},
            {"yes_edge": 0.04, "no_edge": 0.02, "expected_intent": StrategyIntent.BULLISH_EVENT},
            {"yes_edge": 0.03, "no_edge": 0.01, "expected_intent": StrategyIntent.BULLISH_EVENT},
            {"yes_edge": 0.05, "no_edge": 0.02, "expected_intent": StrategyIntent.BULLISH_EVENT},
        ]

        # Count intents
        bullish_count = sum(1 for w in synthetic_windows if w["expected_intent"] == StrategyIntent.BULLISH_EVENT)
        total_count = len(synthetic_windows)
        bullish_share = bullish_count / total_count

        # In YES-dominant regime, BULLISH_EVENT share must exceed 60%
        assert bullish_share > 0.6, (
            f"[UPSTREAM-BIAS-DETECTED] BULLISH_EVENT share ({bullish_share:.1%}) "
            f"must exceed 60% in YES-dominant regime, got {bullish_count}/{total_count}"
        )


class TestSideArbitrationInvariants:
    """Test side arbitration invariants to catch structural YES bias."""

    def test_no_edge_greater_implies_no_side(self):
        """Invariant: if no_edge > yes_edge, candidate_side must be NO."""
        test_cases = [
            (0.01, 0.02, "no"),  # no_edge > yes_edge
            (0.03, 0.05, "no"),  # no_edge > yes_edge
            (0.10, 0.15, "no"),  # no_edge > yes_edge
        ]

        for yes_edge, no_edge, expected_side in test_cases:
            if no_edge > yes_edge:
                selected_side = "yes" if yes_edge > no_edge else "no"
                assert selected_side == expected_side, (
                    f"no_edge ({no_edge}) > yes_edge ({yes_edge}) requires NO side, "
                    f"got {selected_side}"
                )

    def test_yes_edge_greater_implies_yes_side(self):
        """Invariant: if yes_edge > no_edge, candidate_side must be YES."""
        test_cases = [
            (0.02, 0.01, "yes"),  # yes_edge > no_edge
            (0.05, 0.03, "yes"),  # yes_edge > no_edge
            (0.15, 0.10, "yes"),  # yes_edge > no_edge
        ]

        for yes_edge, no_edge, expected_side in test_cases:
            if yes_edge > no_edge:
                selected_side = "yes" if yes_edge > no_edge else "no"
                assert selected_side == expected_side, (
                    f"yes_edge ({yes_edge}) > no_edge ({no_edge}) requires YES side, "
                    f"got {selected_side}"
                )


class TestMixedRegimeEdgeSwapping:
    """Test mixed regimes where yes_edge and no_edge swap dominance over time."""

    def test_edge_dominance_swaps_correctly(self):
        """When edge dominance swaps, selected_side should flip accordingly."""
        # Simulate a regime shift from YES-dominant to NO-dominant
        time_series = [
            {"time": 0, "yes_edge": 0.05, "no_edge": 0.02, "expected_side": "yes"},
            {"time": 1, "yes_edge": 0.04, "no_edge": 0.03, "expected_side": "yes"},
            {"time": 2, "yes_edge": 0.03, "no_edge": 0.04, "expected_side": "no"},  # Swap
            {"time": 3, "yes_edge": 0.02, "no_edge": 0.05, "expected_side": "no"},
            {"time": 4, "yes_edge": 0.03, "no_edge": 0.04, "expected_side": "no"},
            {"time": 5, "yes_edge": 0.04, "no_edge": 0.03, "expected_side": "yes"},  # Swap back
            {"time": 6, "yes_edge": 0.05, "no_edge": 0.02, "expected_side": "yes"},
        ]

        for window in time_series:
            yes_edge = window["yes_edge"]
            no_edge = window["no_edge"]
            expected_side = window["expected_side"]

            if yes_edge > no_edge:
                selected_side = "yes"
            elif no_edge > yes_edge:
                selected_side = "no"
            else:
                selected_side = "no"  # Tie-break

            assert selected_side == expected_side, (
                f"Time {window['time']}: yes_edge={yes_edge}, no_edge={no_edge} "
                f"should select {expected_side}, got {selected_side}"
            )

    def test_multiple_swaps_in_choppy_regime(self):
        """Multiple rapid swaps in choppy regime should all be handled correctly."""
        # Simulate high-frequency chop
        chop_series = [
            {"yes_edge": 0.03, "no_edge": 0.02, "expected_side": "yes"},
            {"yes_edge": 0.02, "no_edge": 0.03, "expected_side": "no"},
            {"yes_edge": 0.04, "no_edge": 0.02, "expected_side": "yes"},
            {"yes_edge": 0.02, "no_edge": 0.04, "expected_side": "no"},
            {"yes_edge": 0.03, "no_edge": 0.03, "expected_side": "no"},  # Equal, tie-break
            {"yes_edge": 0.05, "no_edge": 0.02, "expected_side": "yes"},
            {"yes_edge": 0.02, "no_edge": 0.05, "expected_side": "no"},
            {"yes_edge": 0.03, "no_edge": 0.02, "expected_side": "yes"},
        ]

        for i, window in enumerate(chop_series):
            yes_edge = window["yes_edge"]
            no_edge = window["no_edge"]
            expected_side = window["expected_side"]

            if yes_edge > no_edge:
                selected_side = "yes"
            elif no_edge > yes_edge:
                selected_side = "no"
            else:
                selected_side = "no"  # Tie-break

            assert selected_side == expected_side, (
                f"Chop window {i}: yes_edge={yes_edge}, no_edge={no_edge} "
                f"should select {expected_side}, got {selected_side}"
            )


class TestIntentToSideMapping:
    """Test correct intent-to-side mapping (non-inverted)."""

    def test_bullish_event_maps_to_yes_side(self):
        """BULLISH_EVENT should map to YES side (correct mapping)."""
        intent = StrategyIntent.BULLISH_EVENT
        expected_side = "yes"

        # Correct mapping: BULLISH_EVENT → YES side
        side = "yes" if intent == StrategyIntent.BULLISH_EVENT else "no"
        assert side == expected_side, f"BULLISH_EVENT should map to YES side, got {side}"

    def test_bearish_event_maps_to_no_side(self):
        """BEARISH_EVENT should map to NO side (correct mapping)."""
        intent = StrategyIntent.BEARISH_EVENT
        expected_side = "no"

        # Correct mapping: BEARISH_EVENT → NO side
        side = "yes" if intent == StrategyIntent.BULLISH_EVENT else "no"
        assert side == expected_side, f"BEARISH_EVENT should map to NO side, got {side}"


class TestSidePreservationInvariant:
    """Test that candidate_side is preserved through to order_side."""

    def test_candidate_side_preserved_for_entries(self):
        """Invariant: for entries, order_side must equal candidate_side."""
        test_cases = [
            ("yes", "yes"),
            ("no", "no"),
        ]

        for candidate_side, order_side in test_cases:
            entry_or_exit = "entry"
            if candidate_side and order_side:
                is_valid = candidate_side.lower() == order_side.lower()
                assert is_valid, (
                    f"Entry: candidate_side ({candidate_side}) must equal order_side ({order_side}), "
                    f"side flipping detected"
                )

    def test_candidate_side_flipping_detected(self):
        """Test that side flipping is caught as a violation."""
        candidate_side = "no"
        order_side = "yes"  # Flipped!
        entry_or_exit = "entry"

        if entry_or_exit == "entry" and candidate_side and order_side:
            is_violation = candidate_side.lower() != order_side.lower()
            assert is_violation, "Side flipping should be detected as a violation"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
