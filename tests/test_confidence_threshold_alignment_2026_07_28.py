"""
Test suite for confidence threshold alignment fix (2026-07-28).

This test validates that confidence thresholds are consistently set to 0.50 (50%)
across all components of the trading system, matching the signal generation range
of 52-58% (confidence = 0.5 + edge, where edge is 0.02-0.08).

The previous mismatch (signal generation: 52-58%, allocator: 65%) was causing
all valid candidates to be filtered out before execution.
"""

import pytest
from dataclasses import dataclass
from typing import Dict, Any


class TestConfidenceThresholdAlignment:
    """Test confidence threshold alignment across all components."""
    
    def test_global_allocator_confidence_threshold(self):
        """Test that GlobalAllocator uses 0.50 min_confidence."""
        from merid.risk.profiles.global_allocator import GlobalAllocator
        
        allocator = GlobalAllocator(
            venue_cap_usd=1.00,
            min_edge_pct=0.025,
            min_confidence=0.50,  # Should be 0.50
            min_price_cents=10,
            max_price_cents=75
        )
        
        assert allocator.min_confidence == 0.50, \
            f"GlobalAllocator min_confidence should be 0.50, got {allocator.min_confidence}"
    
    def test_global_allocator_default_confidence(self):
        """Test that GlobalAllocator default constructor uses 0.50."""
        from merid.risk.profiles.global_allocator import GlobalAllocator
        
        allocator = GlobalAllocator()  # Use defaults
        
        assert allocator.min_confidence == 0.50, \
            f"GlobalAllocator default min_confidence should be 0.50, got {allocator.min_confidence}"
    
    def test_profile_yaml_confidence_threshold(self):
        """Test that profile YAML has 0.50 min_confidence_threshold."""
        # Use UTF-8 encoding to handle Unicode characters in YAML
        with open('config/profiles/kalshi_crypto_15m_v2.yaml', 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for the confidence threshold value
        assert 'min_confidence_threshold: 0.50' in content, \
            "Profile YAML should have min_confidence_threshold: 0.50"
    
    def test_crypto_15m_profile_default_confidence(self):
        """Test that crypto_15m_profile default is 0.50."""
        # Read the source file directly to check the default value
        with open('merid/risk/profiles/crypto_15m_profile.py', 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check that the default is 0.50 in the from_dict method
        assert "confidence.get('min_confidence_threshold', 0.50)" in content, \
            "Crypto15mProfile.from_dict should have default min_confidence_threshold of 0.50"
    
    def test_candidate_filtering_with_aligned_thresholds(self):
        """Test that candidates with 52-58% confidence pass filtering."""
        from merid.risk.profiles.global_allocator import GlobalAllocator, OrderCandidate
        
        allocator = GlobalAllocator(
            venue_cap_usd=1.00,
            min_edge_pct=0.025,
            min_confidence=0.50,
            min_price_cents=10,
            max_price_cents=75
        )
        
        # Test candidate with 52% confidence (signal generation minimum)
        candidate_52 = OrderCandidate(
            asset="BTC",
            ticker="KXBTC15M-TEST",
            side="yes",
            action="buy",
            price_cents=42,
            count=1,
            edge_pct=0.025,  # 2.5% edge
            confidence=0.52,  # 52% confidence (0.5 + 0.02 edge)
            model_prob=0.77,
            agent_name="BTC_15M"
        )
        
        # Test candidate with 58% confidence (signal generation maximum)
        candidate_58 = OrderCandidate(
            asset="ETH",
            ticker="KXETH15M-TEST",
            side="yes",
            action="buy",
            price_cents=42,
            count=1,
            edge_pct=0.08,  # 8% edge
            confidence=0.58,  # 58% confidence (0.5 + 0.08 edge)
            model_prob=0.83,
            agent_name="ETH_15M"
        )
        
        # Test candidate with 45% confidence (below threshold)
        candidate_45 = OrderCandidate(
            asset="SOL",
            ticker="KXSOL15M-TEST",
            side="yes",
            action="buy",
            price_cents=42,
            count=1,
            edge_pct=0.025,
            confidence=0.45,  # 45% confidence (below 50% threshold)
            model_prob=0.70,
            agent_name="SOL_15M"
        )
        
        candidates = [candidate_52, candidate_58, candidate_45]
        filtered = allocator.allocate(candidates, current_positions={})
        
        # Should select candidates with 52% and 58% confidence, but not 45%
        assert len(filtered) == 2, \
            f"Should select 2 candidates (52% and 58% confidence), got {len(filtered)}"
        
        selected_confidences = [c.confidence for c in filtered]
        assert 0.52 in selected_confidences, \
            "Candidate with 52% confidence should be selected"
        assert 0.58 in selected_confidences, \
            "Candidate with 58% confidence should be selected"
        assert 0.45 not in selected_confidences, \
            "Candidate with 45% confidence should be filtered out"
    
    def test_edge_bands_threshold_alignment(self):
        """Test that edge_bands in YAML match global_allocator (2.5%)."""
        # Use UTF-8 encoding to handle Unicode characters in YAML
        with open('config/profiles/kalshi_crypto_15m_v2.yaml', 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check that edge bands use 2.5% minimum (0.025)
        assert 'min_edge_pct: 0.025' in content, \
            "Profile YAML should have min_edge_pct: 0.025 (2.5%) in edge_bands"
        
        # Check that the comment mentions the restoration to 2.5%
        assert 'Restored to 2.5%' in content or '0.025' in content, \
            "Profile YAML should document the 2.5% edge threshold"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
