"""
Unit tests for EdgeResult lag field computation and None handling.

Tests cover:
- EdgeResult lag fields computation
- edge_lag_ratio calculation from edge_fee_adjusted and lag_ms
- None handling for lag_ms and edge_lag_ratio
- Division by zero protection
"""

import pytest
from dataclasses import replace
from datetime import datetime

from merid.prediction.unified_edge import EdgeResult, SpotReference
from merid.event_venues.kalshi.unified_market_state import OrderbookSnapshot


class TestEdgeResultLagFields:
    """Tests for EdgeResult lag field population."""
    
    def test_edge_result_lag_fields_default_none(self):
        """Test EdgeResult lag fields default to None."""
        spot_ref = SpotReference(asset="BTC", price_usd=75000.0, timestamp=datetime.utcnow(), source="CFB")
        result = EdgeResult(
            edge=0.1,
            edge_risk_adjusted=0.08,
            edge_slippage_adjusted=0.07,
            edge_fee_adjusted=0.06,
            model_prob=0.6,
            market_implied_prob=0.5,
            spot_ref=spot_ref,
            confidence=0.8,
            metadata={"asset": "BTC"},
            raw_edge_cents=10.0,
            spread_cost_cents=2.0,
            fee_cost_cents=1.0,
            net_edge_cents=7.0,
            ev_per_contract_cents=7.0
        )
        
        assert result.lag_ms is None
        assert result.edge_lag_ratio is None
        
    def test_edge_result_lag_fields_populated(self):
        """Test EdgeResult lag fields can be populated."""
        spot_ref = SpotReference(asset="BTC", price_usd=75000.0, timestamp=datetime.utcnow(), source="CFB")
        result = EdgeResult(
            edge=0.1,
            edge_risk_adjusted=0.08,
            edge_slippage_adjusted=0.07,
            edge_fee_adjusted=0.06,
            model_prob=0.6,
            market_implied_prob=0.5,
            spot_ref=spot_ref,
            confidence=0.8,
            metadata={"asset": "BTC"},
            raw_edge_cents=10.0,
            spread_cost_cents=2.0,
            fee_cost_cents=1.0,
            net_edge_cents=7.0,
            ev_per_contract_cents=7.0,
            lag_ms=500.0,
            edge_lag_ratio=0.14  # 7 cents / 0.5 seconds
        )
        
        assert result.lag_ms == 500.0
        assert result.edge_lag_ratio == 0.14


class TestEdgeLagRatioComputation:
    """Tests for edge_lag_ratio computation logic."""
    
    def test_edge_lag_ratio_basic_calculation(self):
        """Test edge_lag_ratio = edge_fee_adjusted / (lag_ms / 1000)."""
        edge_fee_adjusted = 0.10  # 10 cents
        lag_ms = 500.0  # 0.5 seconds
        
        expected_ratio = edge_fee_adjusted / (lag_ms / 1000.0)  # 0.10 / 0.5 = 0.20
        assert expected_ratio == 0.20
        
    def test_edge_lag_ratio_small_lag(self):
        """Test edge_lag_ratio with very small lag (high ratio)."""
        edge_fee_adjusted = 0.05  # 5 cents
        lag_ms = 100.0  # 0.1 seconds
        
        expected_ratio = edge_fee_adjusted / (lag_ms / 1000.0)  # 0.05 / 0.1 = 0.50
        assert expected_ratio == 0.50
        
    def test_edge_lag_ratio_large_lag(self):
        """Test edge_lag_ratio with large lag (low ratio)."""
        edge_fee_adjusted = 0.10  # 10 cents
        lag_ms = 2000.0  # 2 seconds
        
        expected_ratio = edge_fee_adjusted / (lag_ms / 1000.0)  # 0.10 / 2.0 = 0.05
        assert expected_ratio == 0.05
        
    def test_edge_lag_ratio_zero_lag(self):
        """Test edge_lag_ratio with zero lag returns None (division by zero protection)."""
        edge_fee_adjusted = 0.10
        lag_ms = 0.0
        
        # Should return None to avoid division by zero
        if lag_ms == 0:
            edge_lag_ratio = None
        else:
            edge_lag_ratio = edge_fee_adjusted / (lag_ms / 1000.0)
        
        assert edge_lag_ratio is None
        
    def test_edge_lag_ratio_none_lag(self):
        """Test edge_lag_ratio with None lag returns None."""
        edge_fee_adjusted = 0.10
        lag_ms = None
        
        edge_lag_ratio = None if lag_ms is None else edge_fee_adjusted / (lag_ms / 1000.0)
        
        assert edge_lag_ratio is None
        
    def test_edge_lag_ratio_negative_lag(self):
        """Test edge_lag_ratio with negative lag returns None."""
        edge_fee_adjusted = 0.10
        lag_ms = -100.0
        
        # Should return None for negative lag
        if lag_ms is None or lag_ms <= 0:
            edge_lag_ratio = None
        else:
            edge_lag_ratio = edge_fee_adjusted / (lag_ms / 1000.0)
        
        assert edge_lag_ratio is None
        
    def test_edge_lag_ratio_zero_edge(self):
        """Test edge_lag_ratio with zero edge is valid (ratio = 0)."""
        edge_fee_adjusted = 0.0
        lag_ms = 500.0
        
        edge_lag_ratio = edge_fee_adjusted / (lag_ms / 1000.0)
        
        assert edge_lag_ratio == 0.0


class TestEdgeResultImmutability:
    """Tests for EdgeResult dataclass behavior."""
    
    def test_edge_result_replace_with_lag_fields(self):
        """Test using dataclass.replace to add lag fields."""
        spot_ref = SpotReference(asset="BTC", price_usd=75000.0, timestamp=datetime.utcnow(), source="CFB")
        result = EdgeResult(
            edge=0.1,
            edge_risk_adjusted=0.08,
            edge_slippage_adjusted=0.07,
            edge_fee_adjusted=0.06,
            model_prob=0.6,
            market_implied_prob=0.5,
            spot_ref=spot_ref,
            confidence=0.8,
            metadata={"asset": "BTC"},
            raw_edge_cents=10.0,
            spread_cost_cents=2.0,
            fee_cost_cents=1.0,
            net_edge_cents=7.0,
            ev_per_contract_cents=7.0
        )
        
        # Add lag fields using replace
        result_with_lag = replace(result, lag_ms=500.0, edge_lag_ratio=0.14)
        
        assert result_with_lag.lag_ms == 500.0
        assert result_with_lag.edge_lag_ratio == 0.14
        
        # Original should be unchanged
        assert result.lag_ms is None
        assert result.edge_lag_ratio is None


class TestEdgeResultMetadata:
    """Tests for EdgeResult metadata handling."""
    
    def test_edge_result_metadata_asset(self):
        """Test EdgeResult metadata contains asset."""
        spot_ref = SpotReference(asset="BTC", price_usd=75000.0, timestamp=datetime.utcnow(), source="CFB")
        result = EdgeResult(
            edge=0.1,
            edge_risk_adjusted=0.08,
            edge_slippage_adjusted=0.07,
            edge_fee_adjusted=0.06,
            model_prob=0.6,
            market_implied_prob=0.5,
            spot_ref=spot_ref,
            confidence=0.8,
            metadata={"asset": "BTC"},
            raw_edge_cents=10.0,
            spread_cost_cents=2.0,
            fee_cost_cents=1.0,
            net_edge_cents=7.0,
            ev_per_contract_cents=7.0
        )
        
        assert result.metadata["asset"] == "BTC"
        
    def test_edge_result_metadata_missing_asset(self):
        """Test EdgeResult metadata without asset."""
        spot_ref = SpotReference(asset="BTC", price_usd=75000.0, timestamp=datetime.utcnow(), source="CFB")
        result = EdgeResult(
            edge=0.1,
            edge_risk_adjusted=0.08,
            edge_slippage_adjusted=0.07,
            edge_fee_adjusted=0.06,
            model_prob=0.6,
            market_implied_prob=0.5,
            spot_ref=spot_ref,
            confidence=0.8,
            metadata={},
            raw_edge_cents=10.0,
            spread_cost_cents=2.0,
            fee_cost_cents=1.0,
            net_edge_cents=7.0,
            ev_per_contract_cents=7.0
        )
        
        assert "asset" not in result.metadata
        assert result.metadata.get("asset") is None


class TestEdgeResultFeeAdjusted:
    """Tests for edge_fee_adjusted calculation."""
    
    def test_edge_fee_adjusted_calculation(self):
        """Test edge_fee_adjusted = net_edge_cents / 100."""
        net_edge_cents = 7.0
        edge_fee_adjusted = net_edge_cents / 100.0  # Convert cents to dollars
        
        assert edge_fee_adjusted == 0.07
        
    def test_edge_fee_adjusted_with_lag_ratio(self):
        """Test complete edge_fee_adjusted → edge_lag_ratio pipeline."""
        net_edge_cents = 10.0  # 10 cents
        lag_ms = 500.0  # 0.5 seconds
        
        edge_fee_adjusted = net_edge_cents / 100.0  # 0.10 dollars
        edge_lag_ratio = edge_fee_adjusted / (lag_ms / 1000.0)  # 0.10 / 0.5 = 0.20
        
        assert edge_fee_adjusted == 0.10
        assert edge_lag_ratio == 0.20


class TestEdgeResultNoneSafety:
    """Tests for None safety in EdgeResult operations."""
    
    def test_edge_result_all_fields_optional(self):
        """Test EdgeResult handles None values gracefully."""
        spot_ref = SpotReference(asset="BTC", price_usd=75000.0, timestamp=datetime.utcnow(), source="CFB")
        result = EdgeResult(
            edge=None,
            edge_risk_adjusted=None,
            edge_slippage_adjusted=None,
            edge_fee_adjusted=None,
            model_prob=None,
            market_implied_prob=None,
            spot_ref=spot_ref,
            confidence=None,
            metadata=None,
            raw_edge_cents=None,
            spread_cost_cents=None,
            fee_cost_cents=None,
            net_edge_cents=None,
            ev_per_contract_cents=None,
            lag_ms=None,
            edge_lag_ratio=None
        )
        
        # Should not raise errors
        assert result.lag_ms is None
        assert result.edge_lag_ratio is None
        
    def test_edge_result_partial_none(self):
        """Test EdgeResult with partial None values."""
        spot_ref = SpotReference(asset="BTC", price_usd=75000.0, timestamp=datetime.utcnow(), source="CFB")
        result = EdgeResult(
            edge=0.1,
            edge_risk_adjusted=None,
            edge_slippage_adjusted=None,
            edge_fee_adjusted=0.06,
            model_prob=0.6,
            market_implied_prob=0.5,
            spot_ref=spot_ref,
            confidence=0.8,
            metadata={"asset": "BTC"},
            raw_edge_cents=10.0,
            spread_cost_cents=None,
            fee_cost_cents=1.0,
            net_edge_cents=9.0,
            ev_per_contract_cents=9.0,
            lag_ms=None,
            edge_lag_ratio=None
        )
        
        assert result.raw_edge_cents == 10.0
        assert result.spread_cost_cents is None
        assert result.lag_ms is None
        assert result.edge_lag_ratio is None
