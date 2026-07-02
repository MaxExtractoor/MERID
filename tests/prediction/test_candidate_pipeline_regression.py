"""Regression tests for candidate pipeline audit fixes.

Tests for:
1. Full candidate pipeline cycle with synthetic state
2. Verify no COLLECT-CANDIDATE-EXCEPTION
3. Verify candidate.asset fix (not undefined asset variable)

These tests lock in the fixes from the trading loop audit to prevent regressions.
"""

from __future__ import annotations

import pytest
import asyncio
import time
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from typing import Dict, Any, List
from datetime import datetime, timezone

from merid.prediction.candidate_optimizer import (
    CandidateOptimizer, 
    MarketCandidate, 
    CandidatePipelineMetrics,
    get_candidate_optimizer,
    reset_candidate_optimizer
)


# ── Helpers ────────────────────────────────────────────────────────────────


def _mock_market_dict(ticker: str, asset: str = "BTC") -> Dict[str, Any]:
    """Create a mock market dict for generate_candidates input."""
    return {
        "ticker": ticker,
        "market_id": ticker,
        "asset": asset,
        "series_ticker": f"KX{asset}15M",
    }


def _mock_market_state(ticker: str, bid_cents: int = 45, ask_cents: int = 55, 
                      depth_yes: int = 50, depth_no: int = 30,
                      book_initialized: bool = True, last_update_ts: float = None):
    """Create a mock market state object."""
    if last_update_ts is None:
        last_update_ts = time.monotonic()
    
    state = MagicMock()
    state.ticker = ticker
    state.market_id = ticker
    state.best_bid_cents = bid_cents
    state.best_ask_cents = ask_cents
    state.mid_cents = (bid_cents + ask_cents) // 2
    state.spread_cents = ask_cents - bid_cents
    state.depth_yes = depth_yes
    state.depth_no = depth_no
    state.book_initialized = book_initialized
    state.last_update_ts = last_update_ts
    state.data_source = "WS"
    state.executable = True
    state.liquidity_status = "TWO_SIDED"
    state.initialized = True
    return state


# ── Candidate Pipeline Tests ────────────────────────────────────────────────


class TestCandidatePipelineRegression:
    """Regression tests for candidate pipeline fixes."""

    @pytest.mark.asyncio
    async def test_candidate_uses_asset_not_undefined(self):
        """Test that candidate.asset is used, not undefined asset variable.
        
        This tests the fix for COLLECT-CANDIDATE-EXCEPTION where
        _filter_by_quality used undefined 'asset' variable instead of
        candidate.asset.
        """
        optimizer = CandidateOptimizer()
        
        # Create a candidate with asset field (using correct MarketCandidate signature)
        candidate = MarketCandidate(
            market_id="KXBTC15M-T",
            asset="BTC",
            series_ticker="KXBTC15M",
            spread_cents=10,
            mid_cents=50,
            depth_yes=50,
            depth_no=30,
            quality_score=0.8,
            liquidity_score=0.7,
        )
        
        # Create metrics object
        metrics = CandidatePipelineMetrics(
            status="running",
            total_markets_scanned=1,
            markets_with_md=1,
            markets_with_spot=1,
            markets_passing_filters=0,
        )
        
        # This should not raise NameError for undefined 'asset'
        try:
            quality = await optimizer._filter_by_quality([candidate], metrics)
            assert quality is not None, "Quality filter should return result"
            # The key test is that it doesn't raise NameError for undefined 'asset'
            # The filter may return empty list due to quality thresholds
        except NameError as e:
            if "asset" in str(e):
                pytest.fail(f"Should not raise NameError for undefined 'asset': {e}")
            else:
                raise

    @pytest.mark.asyncio
    async def test_full_candidate_pipeline_no_exception(self):
        """Test full candidate pipeline cycle with synthetic state.
        
        This tests that the pipeline runs without COLLECT-CANDIDATE-EXCEPTION
        when given valid market states and catalog data.
        """
        optimizer = CandidateOptimizer()
        
        # Mock market dicts (for generate_candidates input)
        market_dicts = [
            _mock_market_dict("KXBTC15M-T", asset="BTC"),
            _mock_market_dict("KXETH15M-T", asset="ETH"),
        ]
        
        # Mock market state store
        mock_state_store = MagicMock()
        mock_state_store.get.side_effect = lambda ticker: _mock_market_state(ticker)
        
        # Mock spot service
        mock_spot_service = MagicMock()
        mock_spot_service.get.side_effect = lambda asset: MagicMock(price=65000.0 if asset == "BTC" else 3500.0)
        
        # This should not raise COLLECT-CANDIDATE-EXCEPTION
        try:
            candidates, metrics = await optimizer.generate_candidates(
                markets=market_dicts,
                asset="BTC",
                market_state_store=mock_state_store,
                spot_service=mock_spot_service,
            )
            
            # Should return candidates (possibly empty if filters reject)
            assert candidates is not None, "Should return candidates list"
            assert isinstance(candidates, list), "Should return a list"
            assert metrics is not None, "Should return metrics"
            
        except NameError as e:
            if "asset" in str(e):
                pytest.fail(f"COLLECT-CANDIDATE-EXCEPTION: undefined 'asset' variable: {e}")
            else:
                raise
        except Exception as e:
            # Other exceptions are OK for this test (e.g., missing dependencies)
            # We're specifically checking for the asset NameError
            if "COLLECT-CANDIDATE-EXCEPTION" in str(e):
                pytest.fail(f"COLLECT-CANDIDATE-EXCEPTION occurred: {e}")
            # Re-raise other exceptions for debugging
            raise

    @pytest.mark.asyncio
    async def test_quality_filter_with_multiple_candidates(self):
        """Test quality filter with multiple candidates of different assets."""
        optimizer = CandidateOptimizer()
        
        candidates = [
            MarketCandidate(
                market_id="KXBTC15M-T",
                asset="BTC",
                series_ticker="KXBTC15M",
                spread_cents=10,
                mid_cents=50,
                depth_yes=50,
                depth_no=30,
                quality_score=0.8,
                liquidity_score=0.7,
            ),
            MarketCandidate(
                market_id="KXETH15M-T",
                asset="ETH",
                series_ticker="KXETH15M",
                spread_cents=15,
                mid_cents=50,
                depth_yes=40,
                depth_no=25,
                quality_score=0.75,
                liquidity_score=0.65,
            ),
            MarketCandidate(
                market_id="KXSOL15M-T",
                asset="SOL",
                series_ticker="KXSOL15M",
                spread_cents=20,
                mid_cents=50,
                depth_yes=30,
                depth_no=20,
                quality_score=0.6,
                liquidity_score=0.5,
            ),
        ]
        
        # Create metrics object
        metrics = CandidatePipelineMetrics(
            status="running",
            total_markets_scanned=3,
            markets_with_md=3,
            markets_with_spot=3,
            markets_passing_filters=0,
        )
        
        # This should not raise NameError for undefined 'asset'
        quality = await optimizer._filter_by_quality(candidates, metrics)
        
        # Should filter based on quality thresholds
        assert quality is not None, "Quality filter should return result"
        assert isinstance(quality, list), "Should return a list"
        
        # All candidates should have asset field set
        for candidate in quality:
            assert hasattr(candidate, 'asset'), "Candidate should have asset field"
            assert candidate.asset is not None, "Candidate asset should not be None"

    @pytest.mark.asyncio
    async def test_generate_candidates_with_empty_inputs(self):
        """Test generate_candidates with empty inputs (edge case)."""
        optimizer = CandidateOptimizer()
        
        # Mock market state store
        mock_state_store = MagicMock()
        mock_state_store.get.return_value = None
        
        # Mock spot service
        mock_spot_service = MagicMock()
        mock_spot_service.get.return_value = None
        
        # Empty inputs
        candidates, metrics = await optimizer.generate_candidates(
            markets=[],
            asset="BTC",
            market_state_store=mock_state_store,
            spot_service=mock_spot_service,
        )
        
        # Should return empty list, not crash
        assert candidates == [], "Should return empty list for empty inputs"
        assert metrics.total_markets_scanned == 0, "Should track zero markets scanned"

    @pytest.mark.asyncio
    async def test_generate_candidates_with_stale_market_state(self):
        """Test generate_candidates handles stale market state gracefully."""
        optimizer = CandidateOptimizer()
        
        # Market dict
        market_dicts = [_mock_market_dict("KXBTC15M-T", asset="BTC")]
        
        # Market state with old timestamp (stale)
        stale_state = _mock_market_state(
            "KXBTC15M-T",
            last_update_ts=time.monotonic() - 100.0  # 100 seconds old
        )
        
        # Mock market state store
        mock_state_store = MagicMock()
        mock_state_store.get.return_value = stale_state
        
        # Mock spot service
        mock_spot_service = MagicMock()
        mock_spot_service.get.return_value = MagicMock(price=65000.0)
        
        # Should handle stale state without crashing
        candidates, metrics = await optimizer.generate_candidates(
            markets=market_dicts,
            asset="BTC",
            market_state_store=mock_state_store,
            spot_service=mock_spot_service,
        )
        
        # May return empty list due to staleness filter
        assert candidates is not None, "Should handle stale state"

    def test_candidate_metrics_tracking(self):
        """Test that candidate pipeline metrics are tracked correctly."""
        optimizer = CandidateOptimizer()
        
        # Check that optimizer has metrics tracking attributes
        assert hasattr(optimizer, '_total_candidates_generated'), "Should track total candidates generated"
        assert hasattr(optimizer, '_total_pipeline_time'), "Should track total pipeline time"
        assert hasattr(optimizer, '_total_errors'), "Should track total errors"
        
        # Metrics should start at 0
        assert optimizer._total_candidates_generated == 0, "Should start with 0 candidates"
        assert optimizer._total_pipeline_time == 0.0, "Should start with 0 pipeline time"
        assert optimizer._total_errors == 0, "Should start with 0 errors"
