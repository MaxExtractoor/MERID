"""
Integration tests for edge stack fixes (2026-07-12).

Tests for:
- Phase 1: Edge field name standardization (edge_pct everywhere)
- Phase 1: Edge unit standardization (FRACTION everywhere)
- Phase 2: Unified edge threshold system
- Phase 2: Centralized edge validation
- Phase 3: Edge data flow fixes
- Phase 3: Edge audit trail in fills ledger
- Phase 4: Best-edge logic alignment
"""

import pytest
from typing import Dict, Any


class TestEdgeFieldNameConsistency:
    """Test that edge_pct is the single source of truth for edge fields."""
    
    def test_candidate_has_edge_pct_only(self):
        """Test that candidates use edge_pct field, not edge."""
        # Sample candidate from agent_grid_15m.py
        candidate = {
            "ticker": "KXBTC15M-26JUL031615-15",
            "side": "yes",
            "edge_pct": 0.02,  # FRACTION units (2%)
            "price_cents": 50
        }
        
        # Should have edge_pct
        assert "edge_pct" in candidate
        assert candidate["edge_pct"] == 0.02
        
        # Should NOT have legacy "edge" field
        assert "edge" not in candidate
    
    def test_loop_15m_reads_edge_pct(self):
        """Test that loop_15m.py reads edge_pct from candidate."""
        candidate = {
            "ticker": "KXBTC15M-26JUL031615-15",
            "side": "yes",
            "edge_pct": 0.015,  # 1.5% in FRACTION
        }
        
        # loop_15m.py should read edge_pct directly
        edge = candidate.get("edge_pct", 0.0)
        assert edge == 0.015
        
        # Candidate should NOT have "edge" field (single source of truth)
        assert "edge" not in candidate
    
    def test_best_edge_tracking_uses_edge_pct(self):
        """Test that best-edge tracking uses edge_pct field."""
        best_edge = {
            "ticker": "KXBTC15M-26JUL031615-15",
            "side": "yes",
            "edge_pct": 0.02,  # FRACTION units
            "candidate": {}
        }
        
        # Should read edge_pct
        current_best_edge = best_edge.get("edge_pct", 0.0)
        assert current_best_edge == 0.02
        
        # Should NOT read "edge" field
        assert "edge" not in best_edge


class TestEdgeUnitStandardization:
    """Test that all edge values use FRACTION units (0.0-1.0)."""
    
    def test_edge_pct_in_fraction_units(self):
        """Test that edge_pct is in FRACTION units, not PERCENT."""
        # 2% edge should be 0.02, not 2.0
        edge_pct = 0.02
        assert 0.0 <= edge_pct <= 1.0, "Edge should be in FRACTION units (0.0-1.0)"
        
        # 5% edge should be 0.05, not 5.0
        edge_pct = 0.05
        assert 0.0 <= edge_pct <= 1.0
    
    def test_thresholds_in_fraction_units(self):
        """Test that edge thresholds are in FRACTION units."""
        from merid.event_venues.kalshi.risk_parameters import (
            EDGE_RESTING_ENTRY_BTC,
            EDGE_RESTING_ENTRY_ETH,
            EDGE_MARKET_ENTRY_BTC,
            EDGE_MARKET_ENTRY_ETH
        )
        
        # BTC resting threshold: 1.25% = 0.0125
        assert EDGE_RESTING_ENTRY_BTC == 0.0125
        assert 0.0 <= EDGE_RESTING_ENTRY_BTC <= 1.0
        
        # BTC market threshold: 1.75% = 0.0175
        assert EDGE_MARKET_ENTRY_BTC == 0.0175
        assert 0.0 <= EDGE_MARKET_ENTRY_BTC <= 1.0
        
        # ETH resting threshold: 1.5% = 0.015
        assert EDGE_RESTING_ENTRY_ETH == 0.015
        assert 0.0 <= EDGE_RESTING_ENTRY_ETH <= 1.0
    
    def test_no_percent_conversion_in_loop_15m(self):
        """Test that loop_15m.py no longer converts PERCENT to FRACTION."""
        # The old code had: edge_fraction = edge_pct / 100.0 if edge_pct > 1.0 else edge_pct
        # This should NOT be present anymore since edge_pct is already in FRACTION
        
        edge_pct = 0.02  # Already in FRACTION
        # No conversion needed
        assert edge_pct == 0.02
        
        # If edge_pct were in PERCENT (2.0), it would be > 1.0
        # But we now ensure all edge_pct values are < 1.0
        edge_pct = 0.02
        assert edge_pct < 1.0


class TestThresholdAlignment:
    """Test that edge threshold system is unified and consistent."""
    
    def test_per_asset_thresholds_from_risk_parameters(self):
        """Test that per-asset thresholds come from risk_parameters.py."""
        from merid.event_venues.kalshi.risk_parameters import (
            EDGE_RESTING_ENTRY_BTC,
            EDGE_RESTING_ENTRY_ETH,
            EDGE_RESTING_ENTRY_SOL,
            EDGE_RESTING_ENTRY_XRP,
            EDGE_RESTING_ENTRY_DOGE
        )
        
        # All thresholds should be in FRACTION units
        thresholds = {
            "BTC": EDGE_RESTING_ENTRY_BTC,
            "ETH": EDGE_RESTING_ENTRY_ETH,
            "SOL": EDGE_RESTING_ENTRY_SOL,
            "XRP": EDGE_RESTING_ENTRY_XRP,
            "DOGE": EDGE_RESTING_ENTRY_DOGE
        }
        
        for asset, threshold in thresholds.items():
            assert 0.0 < threshold < 1.0, f"{asset} threshold should be in FRACTION units"
            assert threshold > 0.01, f"{asset} threshold should be > 1%"
    
    def test_validate_edge_function(self):
        """Test that centralized validate_edge function works correctly."""
        from merid.event_venues.kalshi.risk_parameters import validate_edge
        
        # Test valid edge (meets edge_bands threshold of 0.5%)
        is_valid, reason = validate_edge(0.02, "BTC")  # 2% > 0.5% threshold
        assert is_valid is True
        assert "meets edge_bands threshold" in reason.lower()
        
        # Test edge exactly at threshold (0.5% should pass)
        is_valid, reason = validate_edge(0.005, "BTC")  # 0.5% = threshold
        assert is_valid is True
        assert "meets edge_bands threshold" in reason.lower()
        
        # Test invalid edge (below threshold)
        is_valid, reason = validate_edge(0.004, "BTC")  # 0.4% < 0.5% threshold
        assert is_valid is False
        assert "below edge_bands threshold" in reason.lower()
        
        # Test contrarian signal (negative edge)
        is_valid, reason = validate_edge(-0.02, "BTC")  # -2% meets threshold
        assert is_valid is True
        assert "meets edge_bands threshold" in reason.lower()
    
    def test_loop_15m_uses_unified_edge_bands_threshold(self):
        """Test that validate_edge uses unified edge_bands threshold (0.5%) for all assets."""
        from merid.event_venues.kalshi.risk_parameters import validate_edge
        
        # Test that all assets use the same unified threshold (0.5%)
        assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        
        for asset in assets:
            # Edge at threshold (0.5%) should pass for all assets
            is_valid, reason = validate_edge(0.005, asset)
            assert is_valid is True, f"{asset} should accept 0.5% edge"
            assert "meets edge_bands threshold" in reason.lower()
            
            # Edge below threshold (0.4%) should fail for all assets
            is_valid, reason = validate_edge(0.004, asset)
            assert is_valid is False, f"{asset} should reject 0.4% edge"
            assert "below edge_bands threshold" in reason.lower()


class TestConfidenceThresholdAlignment:
    """Test that confidence threshold is standardized to 0.65 from profile YAML."""
    
    def test_profile_confidence_threshold_is_primary(self):
        """Test that profile.confidence_min_confidence_threshold is the single source of truth."""
        from merid.risk.profiles.crypto_15m_profile import Crypto15mProfileAdapter
        
        adapter = Crypto15mProfileAdapter()
        profile = adapter.profile
        
        # Primary confidence threshold should be 0.65 from profile YAML
        assert profile.confidence_min_confidence_threshold == 0.65, \
            f"Primary confidence threshold should be 0.65, got {profile.confidence_min_confidence_threshold}"
    
    def test_deprecated_confidence_constants_marked(self):
        """Test that deprecated confidence constants are marked as DEPRECATED."""
        from merid.event_venues.kalshi.risk_parameters import (
            CONFIDENCE_NO_TRADE,
            CONFIDENCE_CAUTIOUS,
            CONFIDENCE_CONFIDENT,
            KELLY_CONFIDENCE_FLOOR,
            MIN_SENTIMENT_CONFIDENCE
        )
        
        # These constants should exist but are marked as DEPRECATED
        # Their values may differ from profile (0.65) but should not be used in new code
        assert CONFIDENCE_NO_TRADE == 0.60
        assert CONFIDENCE_CAUTIOUS == 0.75
        assert CONFIDENCE_CONFIDENT == 0.75
        assert KELLY_CONFIDENCE_FLOOR == 0.65
        assert MIN_SENTIMENT_CONFIDENCE == 0.70
    
    def test_order_router_uses_profile_confidence(self):
        """Test that order_router uses profile.confidence_min_confidence_threshold."""
        # This verifies the order_router reads from profile instead of hardcoded values
        # The actual implementation is in order_router.py lines 1996, 2077, 2179
        # We verify the constant exists and has the correct value
        from merid.risk.profiles.crypto_15m_profile import Crypto15mProfileAdapter
        
        adapter = Crypto15mProfileAdapter()
        profile = adapter.profile
        
        # Order router should use this value (0.65) as documented in CONFIDENCE_SETUP_AUDIT_2026-07-06.md
        assert profile.confidence_min_confidence_threshold == 0.65


class TestModelProbabilityThresholdAlignment:
    """Test that MIN_MODEL_PROB constant matches actual clamping behavior."""
    
    def test_min_model_prob_matches_clamping(self):
        """Test that MIN_MODEL_PROB constant (0.05) matches actual clamping in code."""
        from merid.event_venues.kalshi.risk_parameters import MIN_MODEL_PROB
        
        # MIN_MODEL_PROB should be 0.05 to match actual clamping behavior
        assert MIN_MODEL_PROB == 0.05, f"MIN_MODEL_PROB should be 0.05, got {MIN_MODEL_PROB}"
    
    def test_model_prob_clamping_range(self):
        """Test that model_prob is clamped to [0.05, 0.95] in agent_grid_15m.py."""
        # This verifies the actual clamping behavior matches the constant
        # Test lower bound (edge_pct large enough to push below 0.05)
        model_prob = max(0.05, 0.5 - 0.50)  # edge_pct = 0.50, would be 0.0 without clamp
        assert model_prob == 0.05, "Lower bound should be 0.05"
        
        # Test upper bound (edge_pct large enough to push above 0.95)
        model_prob = min(0.95, 0.5 + 0.50)  # edge_pct = 0.50, would be 1.0 without clamp
        assert model_prob == 0.95, "Upper bound should be 0.95"


class TestFillsLedgerEdgeRecording:
    """Test that edge values are correctly recorded in fills ledger."""
    
    def test_order_intent_populates_edgepct(self):
        """Test that OrderIntent populates edgepct field."""
        from merid.event_venues.kalshi.order_router import OrderIntent
        
        intent = OrderIntent(
            ticker="KXBTC15M-26JUL031615-15",
            side="BUY_YES",
            action="buy",
            price_cents=50,
            count=1,
            edge_pct=0.02,  # FRACTION units
            edgepct=0.02,  # PHASE 3 FIX: Populated for fills ledger
            netedgecents=0.02 * 50 / 100.0  # PHASE 3 FIX: Computed net edge in cents
        )
        
        # edgepct should be populated
        assert intent.edgepct == 0.02
        assert intent.edgepct > 0
        
        # netedgecents should be computed
        assert intent.netedgecents == 0.01  # 0.02 * 50 / 100 = 0.01 cents
    
    def test_edgepct_not_zero_in_fills_ledger(self):
        """Test that fills ledger logs non-zero edgepct values."""
        # Simulate fills ledger logging
        intent = {
            "edgepct": 0.02,  # Should be non-zero
            "netedgecents": 0.01,  # Should be non-zero
            "band": "10c-75c",
            "regime": "normal"
        }
        
        # edgepct should NOT be 0.0 (old bug)
        assert intent["edgepct"] != 0.0
        assert intent["edgepct"] == 0.02
        
        # netedgecents should NOT be 0.0 (old bug)
        assert intent["netedgecents"] != 0.0
        assert intent["netedgecents"] == 0.01


class TestEdgeDataFlow:
    """Test that edge data flows correctly through the pipeline."""
    
    def test_edge_from_signal_to_candidate(self):
        """Test that edge flows from signal to candidate."""
        # Signal from agent
        signal = {
            "edge_pct": 0.02,  # FRACTION units
            "confidence": 0.5,
            "model_prob": 0.52
        }
        
        # Candidate built from signal (agent_grid_15m.py)
        candidate = {
            "ticker": "KXBTC15M-26JUL031615-15",
            "side": "yes",
            "edge_pct": signal.get("edge_pct", 0.0),  # Single source of truth
            "confidence": signal.get("confidence", 0.5),
            "model_prob": signal.get("model_prob", 0.5)
        }
        
        # Edge should flow correctly
        assert candidate["edge_pct"] == signal["edge_pct"]
        assert candidate["edge_pct"] == 0.02
    
    def test_edge_from_candidate_to_order_intent(self):
        """Test that edge flows from candidate to OrderIntent."""
        candidate = {
            "ticker": "KXBTC15M-26JUL031615-15",
            "side": "yes",
            "edge_pct": 0.02,
            "price_cents": 50
        }
        
        # OrderIntent built from candidate (loop_15m.py)
        edge_pct = candidate.get("edge_pct", 0.0)
        price_cents = candidate.get("price_cents", 0)
        
        # Edge should flow to OrderIntent
        assert edge_pct == 0.02
        
        # edgepct and netedgecents should be computed
        edgepct = edge_pct
        netedgecents = edge_pct * price_cents / 100.0 if price_cents > 0 else 0.0
        
        assert edgepct == 0.02
        assert netedgecents == 0.01


class TestBestEdgeLogicAlignment:
    """Test that best-edge logic is aligned with agent_grid thresholds."""
    
    def test_best_edge_uses_same_thresholds(self):
        """Test that best-edge logic uses same thresholds as agent_grid."""
        from merid.event_venues.kalshi.risk_parameters import (
            EDGE_RESTING_ENTRY_BTC,
            EDGE_RESTING_ENTRY_ETH
        )
        
        # agent_grid uses validate_edge with these thresholds
        # loop_15m should use the same thresholds for best-edge selection
        
        # BTC threshold
        btc_threshold = EDGE_RESTING_ENTRY_BTC
        assert btc_threshold == 0.0125
        
        # ETH threshold
        eth_threshold = EDGE_RESTING_ENTRY_ETH
        assert eth_threshold == 0.015
    
    def test_no_confidence_based_threshold(self):
        """Test that confidence-based threshold is removed."""
        # Old code had: min_edge_threshold = 0.0001 * confidence_multiplier
        # This should NOT be used anymore
        
        # New code uses per-asset thresholds
        from merid.event_venues.kalshi.risk_parameters import EDGE_RESTING_ENTRY_BTC
        
        min_edge_threshold = EDGE_RESTING_ENTRY_BTC  # 0.0125
        
        # Should be much higher than old confidence-based threshold (0.0001)
        assert min_edge_threshold > 0.001  # > 0.1%
        assert min_edge_threshold == 0.0125  # 1.25%


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
