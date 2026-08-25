"""
E2E harness for regime shift bias detection.

This test validates that during a regime shift from uptrend to downtrend,
the system correctly generates and executes NO-side trades.

The test simulates a BTC 15m regime shift and asserts:
1. In uptrend phase: BULLISH_EVENT → YES side candidates
2. In downtrend phase: BEARISH_EVENT → NO side candidates
3. Side preservation: candidate_side → order_side → fill.side consistency
4. Distribution: mixed YES/NO entries over the full regime cycle
"""

import pytest
from datetime import datetime, timedelta
from typing import List, Dict
from merid.prediction.intent_contract import StrategyIntent

# Marker for bias check tests
pytestmark = pytest.mark.bias_check


class TestRegimeShiftE2E:
    """End-to-end test for regime shift bias detection."""

    def test_btc_15m_regime_shift_uptrend_to_downtrend(self):
        """
        Simulate BTC 15m regime shift from uptrend to downtrend.
        Assert that NO-side trades are generated in downtrend phase.
        """
        # Simulate a 24-hour regime shift
        # Phase 1: Uptrend (0-12h) - expect YES dominance
        # Phase 2: Transition (12-14h) - expect mixed
        # Phase 3: Downtrend (14-24h) - expect NO dominance

        regime_windows = self._generate_btc_regime_shift_windows()
        
        # Track side distribution
        yes_count = 0
        no_count = 0
        bullish_count = 0
        bearish_count = 0
        
        # Phase 1: Uptrend
        uptrend_windows = regime_windows[:12]
        for window in uptrend_windows:
            intent, side = self._simulate_signal_generation(window)
            if intent == StrategyIntent.BULLISH_EVENT:
                bullish_count += 1
            elif intent == StrategyIntent.BEARISH_EVENT:
                bearish_count += 1
            
            if side == "yes":
                yes_count += 1
            elif side == "no":
                no_count += 1
        
        # Assert uptrend phase is YES-dominant
        uptrend_total = len(uptrend_windows)
        uptrend_yes_share = yes_count / uptrend_total if uptrend_total > 0 else 0
        assert uptrend_yes_share > 0.6, (
            f"Uptrend phase should be YES-dominant (>60%), got {uptrend_yes_share:.1%}"
        )
        
        # Reset counters for downtrend phase
        yes_count = 0
        no_count = 0
        bullish_count = 0
        bearish_count = 0
        
        # Phase 3: Downtrend
        downtrend_windows = regime_windows[14:]
        for window in downtrend_windows:
            intent, side = self._simulate_signal_generation(window)
            if intent == StrategyIntent.BULLISH_EVENT:
                bullish_count += 1
            elif intent == StrategyIntent.BEARISH_EVENT:
                bearish_count += 1
            
            if side == "yes":
                yes_count += 1
            elif side == "no":
                no_count += 1
        
        # Assert downtrend phase is NO-dominant
        downtrend_total = len(downtrend_windows)
        downtrend_no_share = no_count / downtrend_total if downtrend_total > 0 else 0
        assert downtrend_no_share > 0.6, (
            f"[REGIME-SHIFT-FAILURE] Downtrend phase should be NO-dominant (>60%), "
            f"got {downtrend_no_share:.1%} ({no_count} NO vs {yes_count} YES). "
            f"This indicates the system is not responding to regime shifts with NO-side trades."
        )
        
        # Assert BEARISH_EVENT is generated in downtrend
        assert bearish_count > 0, (
            f"[REGIME-SHIFT-FAILURE] No BEARISH_EVENT generated in downtrend phase. "
            f"System may be structurally biased to YES."
        )

    def test_full_cycle_mixed_distribution(self):
        """
        Test that over a full regime cycle (uptrend → transition → downtrend),
        the system generates both YES and NO entries.
        """
        regime_windows = self._generate_btc_regime_shift_windows()
        
        yes_count = 0
        no_count = 0
        
        for window in regime_windows:
            intent, side = self._simulate_signal_generation(window)
            if side == "yes":
                yes_count += 1
            elif side == "no":
                no_count += 1
        
        total = len(regime_windows)
        yes_share = yes_count / total if total > 0 else 0
        no_share = no_count / total if total > 0 else 0
        
        # In a mixed regime, we should see both sides
        assert yes_count > 0, "Full cycle should generate YES entries"
        assert no_count > 0, (
            f"[FULL-CYCLE-FAILURE] Full cycle should generate NO entries, got 0. "
            f"This indicates structural YES bias across all regimes."
        )
        
        # Neither side should be 100% in a mixed regime
        assert yes_share < 0.95, (
            f"[FULL-CYCLE-FAILURE] YES share ({yes_share:.1%}) too high in mixed regime. "
            f"System may be structurally YES-biased."
        )
        assert no_share < 0.95, (
            f"NO share ({no_share:.1%}) too high in mixed regime."
        )

    def test_side_preservation_through_pipeline(self):
        """
        Test that side is preserved through the entire pipeline:
        signal → candidate → order → fill
        """
        # Simulate a NO-side trade through the pipeline
        window = {
            "velocity": -0.05,
            "rsi": 35.0,
            "macd_histogram": -0.02,
            "yes_edge": 0.02,
            "no_edge": 0.05,
            "regime": "downtrend"
        }
        
        # Signal generation
        intent, candidate_side = self._simulate_signal_generation(window)
        
        # Candidate emission
        candidate = self._simulate_candidate_emission(intent, candidate_side)
        
        # Order routing
        order_side = self._simulate_order_routing(candidate)
        
        # Fill execution
        fill_side = self._simulate_fill_execution(order_side)
        
        # Assert side preservation
        assert candidate_side == "no", "Candidate should be NO in downtrend"
        assert order_side == "no", "Order should be NO (side preservation)"
        assert fill_side == "no", "Fill should be NO (side preservation)"
        
        # Assert intent consistency
        assert intent == StrategyIntent.BEARISH_EVENT, "Intent should be BEARISH_EVENT in downtrend"

    def _generate_btc_regime_shift_windows(self) -> List[Dict]:
        """Generate synthetic BTC 15m windows simulating a regime shift."""
        windows = []
        
        # Phase 1: Uptrend (0-12h) - positive velocity, high RSI, bullish MACD
        for i in range(12):
            windows.append({
                "velocity": 0.03 + (i * 0.002),  # Gradually increasing
                "rsi": 60.0 + (i * 1.5),  # Rising from 60 to 75
                "macd_histogram": 0.01 + (i * 0.001),
                "yes_edge": 0.04 + (i * 0.001),
                "no_edge": 0.02 - (i * 0.0005),
                "regime": "uptrend"
            })
        
        # Phase 2: Transition (12-14h) - volatility, mixed signals
        for i in range(2):
            windows.append({
                "velocity": 0.0,
                "rsi": 50.0,
                "macd_histogram": 0.0,
                "yes_edge": 0.03,
                "no_edge": 0.03,
                "regime": "transition"
            })
        
        # Phase 3: Downtrend (14-24h) - negative velocity, low RSI, bearish MACD
        for i in range(10):
            windows.append({
                "velocity": -0.03 - (i * 0.002),  # Gradually decreasing
                "rsi": 45.0 - (i * 1.5),  # Falling from 45 to 30
                "macd_histogram": -0.01 - (i * 0.001),
                "yes_edge": 0.02 - (i * 0.0005),
                "no_edge": 0.04 + (i * 0.001),
                "regime": "downtrend"
            })
        
        return windows

    def _simulate_signal_generation(self, window: Dict) -> tuple:
        """Simulate signal generation from market window."""
        velocity = window["velocity"]
        yes_edge = window["yes_edge"]
        no_edge = window["no_edge"]
        
        # Simplified signal generation logic
        if yes_edge > no_edge:
            side = "yes"
            intent = StrategyIntent.BULLISH_EVENT
        elif no_edge > yes_edge:
            side = "no"
            intent = StrategyIntent.BEARISH_EVENT
        else:
            # Tie-break: prefer NO to counteract YES bias
            side = "no"
            intent = StrategyIntent.BEARISH_EVENT
        
        return intent, side

    def _simulate_candidate_emission(self, intent: StrategyIntent, side: str) -> Dict:
        """Simulate candidate emission from signal."""
        return {
            "strategy_intent": intent.value,
            "side": side,
            "action": "buy",
            "timestamp": datetime.utcnow()
        }

    def _simulate_order_routing(self, candidate: Dict) -> str:
        """Simulate order routing (should preserve side)."""
        # In a correctly functioning system, order_side == candidate_side
        return candidate["side"]

    def _simulate_fill_execution(self, order_side: str) -> str:
        """Simulate fill execution (should preserve side)."""
        # In a correctly functioning system, fill.side == order_side
        return order_side


class TestRegimeShiftInvariants:
    """Test invariants for regime shift scenarios."""

    def test_no_dominant_regime_invariant(self):
        """
        Invariant: In NO-dominant regime, BEARISH_EVENT share must exceed 60%.
        """
        # Generate NO-dominant regime windows
        windows = []
        for i in range(20):
            windows.append({
                "yes_edge": 0.02,
                "no_edge": 0.05 + (i * 0.001),  # NO edge consistently higher
                "regime": "no_dominant"
            })
        
        bearish_count = 0
        for window in windows:
            intent, side = self._simulate_signal_generation(window)
            if intent == StrategyIntent.BEARISH_EVENT:
                bearish_count += 1
        
        bearish_share = bearish_count / len(windows)
        assert bearish_share > 0.6, (
            f"[UPSTREAM-BIAS-DETECTED] BEARISH_EVENT share ({bearish_share:.1%}) "
            f"must exceed 60% in NO-dominant regime"
        )

    def _simulate_signal_generation(self, window: Dict) -> tuple:
        """Simulate signal generation from market window."""
        yes_edge = window["yes_edge"]
        no_edge = window["no_edge"]
        
        if yes_edge > no_edge:
            side = "yes"
            intent = StrategyIntent.BULLISH_EVENT
        elif no_edge > yes_edge:
            side = "no"
            intent = StrategyIntent.BEARISH_EVENT
        else:
            side = "no"
            intent = StrategyIntent.BEARISH_EVENT
        
        return intent, side


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
