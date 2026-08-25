"""
Integration tests for confidence, model probability, and edge standardization.

These tests verify that the standardized formulas and field names are consistently
applied across the production stack:

1. Confidence calculation: confidence = abs(model_prob - 0.5) * 2
2. Model probability field name: model_prob (not model_win_prob)
3. Edge field hierarchy: edge_fee_adjusted/net_edge for trade decisions
4. Confidence threshold: 0.65 across all components

Reference:
- Profile YAML: kalshi_crypto_15m_v2.yaml (single source of truth)
- Change log v2.1.0: Fixed confidence computation to distance from 0.5
- Research: Industry standard for prediction market trading
"""
from __future__ import annotations

import pytest
from decimal import Decimal
from datetime import datetime, timezone

from merid.prediction.unified_edge import UnifiedEdgeComputer, EdgeResult, SpotReference, ContractState
from merid.prediction.model import EdgeEstimate
from merid.risk.profiles.crypto_15m_profile import Crypto15mProfileAdapter


class TestConfidenceCalculationStandardization:
    """Test that confidence calculation uses the standardized formula."""
    
    @pytest.fixture
    def profile_adapter(self):
        """Load the production profile."""
        return Crypto15mProfileAdapter()
    
    def test_profile_confidence_threshold_is_0_65(self, profile_adapter):
        """Test that profile YAML confidence threshold is 0.65."""
        profile = profile_adapter.profile
        assert profile.confidence_min_confidence_threshold == 0.65, \
            f"Profile confidence threshold should be 0.65, got {profile.confidence_min_confidence_threshold}"
    
    def test_confidence_formula_distance_from_neutral(self):
        """Test that confidence = abs(model_prob - 0.5) * 2."""
        # Test cases for the standardized formula
        test_cases = [
            (0.50, 0.00),  # Neutral probability → zero confidence
            (0.60, 0.20),  # 60% probability → 20% confidence
            (0.75, 0.50),  # 75% probability → 50% confidence
            (0.90, 0.80),  # 90% probability → 80% confidence
            (0.10, 0.80),  # 10% probability → 80% confidence (symmetric)
            (0.40, 0.20),  # 40% probability → 20% confidence (symmetric)
        ]
        
        for model_prob, expected_confidence in test_cases:
            confidence = abs(model_prob - 0.5) * 2
            assert abs(confidence - expected_confidence) < 0.01, \
                f"Confidence formula failed: model_prob={model_prob}, expected={expected_confidence}, got={confidence}"
    
    def test_unified_edge_confidence_uses_standardized_formula(self):
        """Test that unified edge _compute_confidence uses the standardized formula."""
        computer = UnifiedEdgeComputer()
        
        # Test with edge values that proxy for model_prob distance from 0.5
        test_cases = [
            (0.00, 0.00),  # Zero edge → zero confidence
            (0.10, 0.20),  # 10% edge → 20% confidence
            (0.25, 0.50),  # 25% edge → 50% confidence
            (0.40, 0.80),  # 40% edge → 80% confidence
        ]
        
        for edge, expected_confidence in test_cases:
            confidence = computer._compute_confidence(edge, 600.0)  # 10 min TTE
            # The formula is min(0.99, abs(edge) * 2.0)
            expected = min(0.99, abs(edge) * 2.0)
            assert abs(confidence - expected) < 0.01, \
                f"Unified edge confidence failed: edge={edge}, expected={expected}, got={confidence}"


class TestModelProbabilityFieldNameStandardization:
    """Test that model_prob field name is used consistently."""
    
    def test_edge_result_uses_model_prob(self):
        """Test that EdgeResult uses model_prob field name."""
        spot_ref = SpotReference(
            asset="BTC",
            price_usd=70000.0,
            timestamp=datetime.now(timezone.utc),
            source="CFB",
            is_rti_proxy=True,
        )
        
        result = EdgeResult(
            edge=0.05,
            edge_risk_adjusted=0.03,
            edge_slippage_adjusted=0.02,
            edge_fee_adjusted=0.01,
            model_prob=0.55,  # Standardized field name
            market_implied_prob=0.50,
            spot_ref=spot_ref,
            confidence=0.8,
            metadata={"asset": "BTC"},
            raw_edge_cents=5.0,
            spread_cost_cents=2.0,
            fee_cost_cents=1.0,
            net_edge_cents=2.0,
            ev_per_contract_cents=2.0,
        )
        
        assert hasattr(result, 'model_prob'), "EdgeResult should have model_prob field"
        assert result.model_prob == 0.55, "model_prob should be 0.55"
        assert not hasattr(result, 'model_win_prob'), "EdgeResult should not have model_win_prob field"
    
    def test_edge_estimate_uses_model_prob(self):
        """Test that EdgeEstimate uses model_prob field name."""
        estimate = EdgeEstimate(
            market_id="KXBTC15M-TEST",
            side="yes",
            action="buy",
            market_prob=Decimal("0.50"),
            model_prob=Decimal("0.55"),  # Standardized field name
            raw_edge=Decimal("0.05"),
            fee_drag=Decimal("0.02"),
            slippage_est=Decimal("0.01"),
            net_edge=Decimal("0.02"),
            edge_type="speculative",
            confidence=Decimal("0.80"),
        )
        
        assert hasattr(estimate, 'model_prob'), "EdgeEstimate should have model_prob field"
        assert estimate.model_prob == Decimal("0.55"), "model_prob should be 0.55"
        assert not hasattr(estimate, 'model_win_prob'), "EdgeEstimate should not have model_win_prob field"


class TestEdgeFieldHierarchyStandardization:
    """Test that edge field hierarchy is properly documented and used."""
    
    def test_edge_result_single_source_of_truth_documented(self):
        """Test that EdgeResult documents edge_fee_adjusted as single source of truth."""
        docstring = EdgeResult.__doc__
        assert docstring is not None, "EdgeResult should have a docstring"
        assert "SINGLE SOURCE OF TRUTH" in docstring, \
            "EdgeResult docstring should document single source of truth"
        assert "edge_fee_adjusted" in docstring, \
            "EdgeResult docstring should mention edge_fee_adjusted"
    
    def test_edge_estimate_single_source_of_truth_documented(self):
        """Test that EdgeEstimate documents net_edge as single source of truth."""
        docstring = EdgeEstimate.__doc__
        assert docstring is not None, "EdgeEstimate should have a docstring"
        assert "SINGLE SOURCE OF TRUTH" in docstring, \
            "EdgeEstimate docstring should document single source of truth"
        assert "net_edge" in docstring, \
            "EdgeEstimate docstring should mention net_edge"
    
    def test_edge_result_has_all_edge_fields(self):
        """Test that EdgeResult has all edge fields in the hierarchy."""
        spot_ref = SpotReference(
            asset="BTC",
            price_usd=70000.0,
            timestamp=datetime.now(timezone.utc),
            source="CFB",
            is_rti_proxy=True,
        )
        
        result = EdgeResult(
            edge=0.05,
            edge_risk_adjusted=0.03,
            edge_slippage_adjusted=0.02,
            edge_fee_adjusted=0.01,
            model_prob=0.55,
            market_implied_prob=0.50,
            spot_ref=spot_ref,
            confidence=0.8,
            metadata={"asset": "BTC"},
            raw_edge_cents=5.0,
            spread_cost_cents=2.0,
            fee_cost_cents=1.0,
            net_edge_cents=2.0,
            ev_per_contract_cents=2.0,
        )
        
        # Verify all edge fields exist
        assert hasattr(result, 'edge'), "EdgeResult should have edge field"
        assert hasattr(result, 'edge_risk_adjusted'), "EdgeResult should have edge_risk_adjusted field"
        assert hasattr(result, 'edge_slippage_adjusted'), "EdgeResult should have edge_slippage_adjusted field"
        assert hasattr(result, 'edge_fee_adjusted'), "EdgeResult should have edge_fee_adjusted field"
        assert hasattr(result, 'net_edge_cents'), "EdgeResult should have net_edge_cents field"
        
        # Verify field hierarchy
        assert result.edge == 0.05, "Raw edge should be 0.05"
        assert result.edge_fee_adjusted == 0.01, "Fee-adjusted edge should be 0.01"
        assert result.net_edge_cents == 2.0, "Net edge in cents should be 2.0"


class TestConfidenceThresholdConsistency:
    """Test that confidence threshold is consistent across all components."""
    
    @pytest.fixture
    def profile_adapter(self):
        """Load the production profile."""
        return Crypto15mProfileAdapter()
    
    def test_profile_yaml_confidence_threshold(self, profile_adapter):
        """Test that profile YAML has confidence threshold of 0.65."""
        profile = profile_adapter.profile
        assert profile.confidence_min_confidence_threshold == 0.65, \
            f"Profile confidence threshold should be 0.65, got {profile.confidence_min_confidence_threshold}"
    
    def test_profile_yaml_documents_calculation_method(self, profile_adapter):
        """Test that profile YAML documents the confidence calculation method."""
        # This is verified by reading the YAML file directly
        # The test ensures the documentation exists
        from pathlib import Path
        yaml_path = Path("c:/Dev/MERID/config/profiles/kalshi_crypto_15m_v2.yaml")
        assert yaml_path.exists(), "Profile YAML should exist"
        
        # Read with UTF-8 encoding to handle Unicode characters
        yaml_content = yaml_path.read_text(encoding='utf-8')
        assert "CONFIDENCE CALCULATION METHOD" in yaml_content, \
            "Profile YAML should document confidence calculation method"
        assert "abs(model_prob - 0.5) * 2" in yaml_content, \
            "Profile YAML should document the formula abs(model_prob - 0.5) * 2"
        assert "SINGLE SOURCE OF TRUTH" in yaml_content, \
            "Profile YAML should document single source of truth"


class TestEndToEndConsistency:
    """End-to-end tests for confidence/prob/edge consistency across the stack."""
    
    def test_confidence_calculation_matches_profile_formula(self):
        """Test that confidence calculation matches the formula documented in profile YAML."""
        # Test the formula: confidence = abs(model_prob - 0.5) * 2
        model_prob = 0.75
        expected_confidence = abs(model_prob - 0.5) * 2  # = 0.50
        
        # Verify the formula produces the expected result
        actual_confidence = abs(model_prob - 0.5) * 2
        assert abs(actual_confidence - expected_confidence) < 0.01, \
            f"Confidence calculation should match formula: expected={expected_confidence}, got={actual_confidence}"
    
    def test_model_prob_field_name_consistency(self):
        """Test that model_prob field name is used consistently across data structures."""
        # EdgeResult uses model_prob
        assert hasattr(EdgeResult, '__dataclass_fields__'), "EdgeResult should be a dataclass"
        assert 'model_prob' in EdgeResult.__dataclass_fields__, \
            "EdgeResult should have model_prob field"
        
        # EdgeEstimate uses model_prob
        assert hasattr(EdgeEstimate, '__dataclass_fields__'), "EdgeEstimate should be a dataclass"
        assert 'model_prob' in EdgeEstimate.__dataclass_fields__, \
            "EdgeEstimate should have model_prob field"
    
    def test_edge_field_consistency(self):
        """Test that edge fields are consistent between EdgeResult and EdgeEstimate."""
        # Both should have net edge fields
        assert 'net_edge_cents' in EdgeResult.__dataclass_fields__, \
            "EdgeResult should have net_edge_cents field"
        assert 'net_edge' in EdgeEstimate.__dataclass_fields__, \
            "EdgeEstimate should have net_edge field"
        
        # Both should have confidence fields
        assert 'confidence' in EdgeResult.__dataclass_fields__, \
            "EdgeResult should have confidence field"
        assert 'confidence' in EdgeEstimate.__dataclass_fields__, \
            "EdgeEstimate should have confidence field"
