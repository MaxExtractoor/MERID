"""Stress tests for crypto_top_edge module — Momentum scalping, rapid reversals, loop lag.

This test suite validates production readiness:
- Timeframe filtering (15m, 1h only)
- Position-aware deduplication
- In-cycle deduplication
- Rapid reversal handling
- Loop lag resilience
"""

from __future__ import annotations

import time
from typing import List

import pytest

from merid.prediction.crypto_top_edge import (
    CandidateSignal,
    CrossAssetCycleResult,
    CryptoTopEdgeArbiter,
    CRYPTO_ASSETS,
    MEAN_REVERSION_TIMEFRAMES,
    get_crypto_top_edge_arbiter,
    reset_crypto_top_edge_arbiter,
    select_top_edges,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset the singleton arbiter before each test."""
    reset_crypto_top_edge_arbiter()
    yield
    reset_crypto_top_edge_arbiter()


def create_momentum_candidate(
    asset: str = "BTC",
    timeframe: str = "15m",
    net_edge: float = 0.05,
    direction: str = "long",
    existing_position_contracts: int = 0,
    existing_position_direction: str = "none",
    position_entry_time: float = None,
    suggested_contracts: int = 5,
    archetype: str = "directional",
) -> CandidateSignal:
    """Create a momentum scalping candidate."""
    return CandidateSignal(
        signal_id=f"{asset}_{timeframe}_{int(time.time() * 1000)}",
        agent_id=f"{asset}_{timeframe.upper()}",
        asset=asset,
        timeframe=timeframe,
        ticker=f"KX{asset}{timeframe.upper()}-TEST",
        net_edge=net_edge,
        confidence=0.75,
        direction=direction,
        suggested_contracts=suggested_contracts,
        archetype=archetype,
        existing_position_contracts=existing_position_contracts,
        existing_position_direction=existing_position_direction,
        position_entry_time=position_entry_time,
    )


# =============================================================================
# Timeframe Filtering Tests
# =============================================================================

class TestTimeframeFiltering:
    """Test that only momentum scalping timeframes are accepted."""
    
    def test_only_15m_accepted(self):
        """Test 15m timeframe is accepted."""
        arbiter = CryptoTopEdgeArbiter()
        c = create_momentum_candidate(timeframe="15m")
        arbiter.submit_candidate(c)
        result = arbiter.run_cycle()
        assert len(result.all_candidates) == 1
    
    def test_only_1h_accepted(self):
        """Test 1h timeframe is accepted."""
        arbiter = CryptoTopEdgeArbiter()
        c = create_momentum_candidate(timeframe="1h")
        arbiter.submit_candidate(c)
        result = arbiter.run_cycle()
        assert len(result.all_candidates) == 1
    
    def test_daily_rejected(self):
        """Test daily timeframe is rejected."""
        arbiter = CryptoTopEdgeArbiter()
        c = create_momentum_candidate(timeframe="daily")
        arbiter.submit_candidate(c)
        result = arbiter.run_cycle()
        assert len(result.all_candidates) == 0
    
    def test_weekly_rejected(self):
        """Test weekly timeframe is rejected."""
        arbiter = CryptoTopEdgeArbiter()
        c = create_momentum_candidate(timeframe="weekly")
        arbiter.submit_candidate(c)
        result = arbiter.run_cycle()
        assert len(result.all_candidates) == 0
    
    def test_mixed_timeframes_filtered(self):
        """Test mixed timeframes are correctly filtered."""
        arbiter = CryptoTopEdgeArbiter()
        
        # These should be accepted
        c1 = create_momentum_candidate(asset="BTC", timeframe="15m")
        c2 = create_momentum_candidate(asset="ETH", timeframe="1h")
        
        # These should be rejected
        c3 = create_momentum_candidate(asset="SOL", timeframe="daily")
        c4 = create_momentum_candidate(asset="XRP", timeframe="weekly")
        
        for c in [c1, c2, c3, c4]:
            arbiter.submit_candidate(c)
        
        result = arbiter.run_cycle()
        
        # Only 15m and 1h should be present
        assert len(result.all_candidates) == 2
        assert all(c.timeframe in MEAN_REVERSION_TIMEFRAMES for c in result.all_candidates)


# =============================================================================
# Position-Aware Deduplication Tests
# =============================================================================

class TestPositionAwareDeduplication:
    """Test position-aware deduplication logic."""
    
    def test_no_position_allows_entry(self):
        """Test candidate with no existing position is allowed."""
        arbiter = CryptoTopEdgeArbiter(position_dedup_enabled=True)
        c = create_momentum_candidate(
            existing_position_contracts=0,
            existing_position_direction="none"
        )
        arbiter.submit_candidate(c)
        result = arbiter.run_cycle()
        
        assert len(result.winners) == 1
        assert result.rejected_by_position_dup == 0
    
    def test_same_direction_at_target_rejected(self):
        """Test duplicate in same direction at target size is rejected."""
        arbiter = CryptoTopEdgeArbiter(position_dedup_enabled=True)
        c = create_momentum_candidate(
            suggested_contracts=5,
            existing_position_contracts=5,
            existing_position_direction="long",
            direction="long"
        )
        arbiter.submit_candidate(c)
        result = arbiter.run_cycle()
        
        assert len(result.winners) == 0
        assert result.rejected_by_position_dup == 1
        assert result.deduped_contracts_saved == 5
    
    def test_same_direction_above_target_rejected(self):
        """Test duplicate in same direction above target size is rejected."""
        arbiter = CryptoTopEdgeArbiter(position_dedup_enabled=True)
        c = create_momentum_candidate(
            suggested_contracts=5,
            existing_position_contracts=7,  # Above target
            existing_position_direction="long",
            direction="long"
        )
        arbiter.submit_candidate(c)
        result = arbiter.run_cycle()
        
        assert len(result.winners) == 0
        assert result.rejected_by_position_dup == 1
    
    def test_partial_position_emits_incremental(self):
        """Test partial position emits only incremental size."""
        arbiter = CryptoTopEdgeArbiter(position_dedup_enabled=True)
        c = create_momentum_candidate(
            suggested_contracts=5,
            existing_position_contracts=2,  # Partial
            existing_position_direction="long",
            direction="long"
        )
        arbiter.submit_candidate(c)
        result = arbiter.run_cycle()
        
        assert len(result.winners) == 1
        assert result.winners[0].incremental_contracts == 3  # 5 - 2
        assert result.winners[0].suggested_contracts == 3  # Adjusted
        assert result.rejected_by_position_dup == 0
    
    def test_opposite_direction_allowed(self):
        """Test opposite direction is allowed (risk layer handles flip)."""
        arbiter = CryptoTopEdgeArbiter(position_dedup_enabled=True)
        c = create_momentum_candidate(
            suggested_contracts=5,
            existing_position_contracts=3,
            existing_position_direction="short",  # Opposite
            direction="long"
        )
        arbiter.submit_candidate(c)
        result = arbiter.run_cycle()
        
        assert len(result.winners) == 1
        assert result.rejected_by_position_dup == 0
    
    def test_expired_position_treated_as_fresh(self):
        """Test expired position is treated as fresh opportunity."""
        arbiter = CryptoTopEdgeArbiter(
            position_dedup_enabled=True,
            max_hold_minutes=60  # 1 hour max
        )
        
        # Position from 2 hours ago (expired)
        old_entry_time = time.time() - (2 * 3600)
        
        c = create_momentum_candidate(
            suggested_contracts=5,
            existing_position_contracts=5,
            existing_position_direction="long",
            direction="long",
            position_entry_time=old_entry_time
        )
        arbiter.submit_candidate(c)
        result = arbiter.run_cycle()
        
        assert len(result.winners) == 1  # Allowed because expired
        assert result.rejected_by_position_dup == 0
    
    def test_position_dedup_disabled(self):
        """Test position deduplication can be disabled."""
        arbiter = CryptoTopEdgeArbiter(position_dedup_enabled=False)
        c = create_momentum_candidate(
            suggested_contracts=5,
            existing_position_contracts=5,
            existing_position_direction="long",
            direction="long"
        )
        arbiter.submit_candidate(c)
        result = arbiter.run_cycle()
        
        assert len(result.winners) == 1  # Allowed because dedup disabled
        assert result.rejected_by_position_dup == 0


# =============================================================================
# In-Cycle Deduplication Tests
# =============================================================================

class TestInCycleDeduplication:
    """Test in-cycle deduplication prevents duplicate orders."""
    
    def test_same_ticker_direction_archetype_blocked(self):
        """Test same ticker/direction/archetype within cycle is blocked."""
        arbiter = CryptoTopEdgeArbiter(in_cycle_dedup_enabled=True)
        
        # Two candidates for same ticker/direction/archetype
        c1 = create_momentum_candidate(asset="BTC", direction="long", net_edge=0.06)
        c2 = create_momentum_candidate(asset="BTC", direction="long", net_edge=0.05)
        
        for c in [c1, c2]:
            arbiter.submit_candidate(c)
        
        result = arbiter.run_cycle()
        
        assert len(result.winners) == 1  # Only first wins
        assert result.winners[0].net_edge == 0.06  # Higher edge wins
        assert result.rejected_by_cycle_dup == 1
    
    def test_different_directions_allowed(self):
        """Test different directions for same ticker are allowed."""
        arbiter = CryptoTopEdgeArbiter(in_cycle_dedup_enabled=True)
        
        c1 = create_momentum_candidate(asset="BTC", direction="long", net_edge=0.06)
        c2 = create_momentum_candidate(asset="BTC", direction="short", net_edge=0.05)
        
        for c in [c1, c2]:
            arbiter.submit_candidate(c)
        
        result = arbiter.run_cycle()
        
        assert len(result.winners) == 2  # Both allowed (different directions)
        assert result.rejected_by_cycle_dup == 0
    
    def test_different_archetypes_allowed(self):
        """Test different archetypes for same ticker/direction are allowed."""
        arbiter = CryptoTopEdgeArbiter(in_cycle_dedup_enabled=True)
        
        c1 = create_momentum_candidate(asset="BTC", direction="long", net_edge=0.06, archetype="directional")
        c2 = create_momentum_candidate(asset="BTC", direction="long", net_edge=0.05, archetype="contrarian")
        
        for c in [c1, c2]:
            arbiter.submit_candidate(c)
        
        result = arbiter.run_cycle()
        
        assert len(result.winners) == 2  # Both allowed (different archetypes)
        assert result.rejected_by_cycle_dup == 0
    
    def test_cycle_dedup_disabled(self):
        """Test cycle deduplication can be disabled."""
        arbiter = CryptoTopEdgeArbiter(in_cycle_dedup_enabled=False)
        
        c1 = create_momentum_candidate(asset="BTC", direction="long", net_edge=0.06)
        c2 = create_momentum_candidate(asset="BTC", direction="long", net_edge=0.05)
        
        for c in [c1, c2]:
            arbiter.submit_candidate(c)
        
        result = arbiter.run_cycle()
        
        assert len(result.winners) == 2  # Both allowed because dedup disabled
        assert result.rejected_by_cycle_dup == 0


# =============================================================================
# Stress Test: Rapid Reversals
# =============================================================================

class TestRapidReversals:
    """Test rapid reversal scenarios (long→short→long within cycles)."""
    
    def test_reversal_same_cycle(self):
        """Test that opposite direction in same cycle is allowed."""
        arbiter = CryptoTopEdgeArbiter(
            position_dedup_enabled=True,
            in_cycle_dedup_enabled=True
        )
        
        # Long and short signals in same cycle
        # c1: Flip from short to long - should be allowed
        c1 = create_momentum_candidate(
            asset="BTC", direction="long", net_edge=0.06,
            existing_position_contracts=3,
            existing_position_direction="short"  # Flip
        )
        # c2: Same direction as existing position - emits incremental
        c2 = create_momentum_candidate(
            asset="BTC", direction="short", net_edge=0.04,
            suggested_contracts=3,  # Same as existing - will be rejected
            existing_position_contracts=3,
            existing_position_direction="short"  # Duplicate at target
        )
        
        for c in [c1, c2]:
            arbiter.submit_candidate(c)
        
        result = arbiter.run_cycle()
        
        # Long allowed (flip), short rejected (at target size)
        assert len(result.winners) == 1
        assert result.winners[0].direction == "long"
        assert result.rejected_by_position_dup == 1
    
    def test_consecutive_cycles_deduplication_reset(self):
        """Test that deduplication resets between cycles."""
        arbiter = CryptoTopEdgeArbiter(in_cycle_dedup_enabled=True)
        
        # Cycle 1: Submit BTC long
        c1 = create_momentum_candidate(asset="BTC", direction="long", net_edge=0.05)
        arbiter.submit_candidate(c1)
        result1 = arbiter.run_cycle(cycle_id="cycle_1")
        
        assert len(result1.winners) == 1
        
        # Cycle 2: Submit BTC long again (should be allowed in new cycle)
        c2 = create_momentum_candidate(asset="BTC", direction="long", net_edge=0.06)
        arbiter.submit_candidate(c2)
        result2 = arbiter.run_cycle(cycle_id="cycle_2")
        
        # Should be allowed because it's a new cycle
        # (unless position dedup kicks in)
        assert result2.rejected_by_cycle_dup == 0


# =============================================================================
# Stress Test: Loop Lag Resilience
# =============================================================================

class TestLoopLagResilience:
    """Test arbiter behavior under simulated loop lag conditions."""
    
    def test_stale_position_data_handled(self):
        """Test that stale position data doesn't cause errors."""
        arbiter = CryptoTopEdgeArbiter(position_dedup_enabled=True)
        
        # Position with no entry time (stale/unknown)
        c = create_momentum_candidate(
            existing_position_contracts=5,
            existing_position_direction="long",
            position_entry_time=None  # Unknown
        )
        
        arbiter.submit_candidate(c)
        result = arbiter.run_cycle()
        
        # Should not crash, treats as not expired
        assert len(result.winners) == 0  # Duplicate rejected
        assert result.rejected_by_position_dup == 1
    
    def test_partial_fills_accumulate(self):
        """Test that partial fills are correctly tracked across cycles."""
        arbiter = CryptoTopEdgeArbiter(
            position_dedup_enabled=True,
            max_hold_minutes=240
        )
        
        # Cycle 1: Partial fill (2 contracts)
        c1 = create_momentum_candidate(
            suggested_contracts=5,
            existing_position_contracts=2,  # Partial
            existing_position_direction="long",
            direction="long",
            position_entry_time=time.time()
        )
        arbiter.submit_candidate(c1)
        result1 = arbiter.run_cycle()
        
        assert len(result1.winners) == 1
        assert result1.winners[0].incremental_contracts == 3  # 5 - 2
        
        # Cycle 2: Now position is at 5, should reject
        c2 = create_momentum_candidate(
            suggested_contracts=5,
            existing_position_contracts=5,  # Now full
            existing_position_direction="long",
            direction="long",
            position_entry_time=time.time()
        )
        arbiter.submit_candidate(c2)
        result2 = arbiter.run_cycle()
        
        assert len(result2.winners) == 0
        assert result2.rejected_by_position_dup == 1


# =============================================================================
# Integration Test: Full Momentum Scalping Flow
# =============================================================================

class TestFullMomentumScalpingFlow:
    """Integration test for full momentum scalping workflow."""
    
    def test_full_flow_with_deduplication(self):
        """Test full flow with all deduplication enabled."""
        arbiter = CryptoTopEdgeArbiter(
            gamma=0.5,
            top_n=3,
            position_dedup_enabled=True,
            in_cycle_dedup_enabled=True,
            max_hold_minutes=240
        )
        
        # Create a mix of candidates
        candidates = [
            # 15m candidates (accepted)
            create_momentum_candidate(asset="BTC", timeframe="15m", net_edge=0.06, direction="long"),
            create_momentum_candidate(asset="ETH", timeframe="15m", net_edge=0.05, direction="long"),
            
            # 1h candidate (accepted)
            create_momentum_candidate(asset="SOL", timeframe="1h", net_edge=0.04, direction="short"),
            
            # Daily candidate (rejected by timeframe filter)
            create_momentum_candidate(asset="XRP", timeframe="daily", net_edge=0.07, direction="long"),
            
            # Duplicate within cycle (rejected)
            create_momentum_candidate(asset="BTC", timeframe="15m", net_edge=0.055, direction="long"),
            
            # Already positioned (rejected by position dedup)
            create_momentum_candidate(
                asset="DOGE", timeframe="15m", net_edge=0.045, direction="long",
                existing_position_contracts=5, existing_position_direction="long"
            ),
        ]
        
        for c in candidates:
            arbiter.submit_candidate(c)
        
        result = arbiter.run_cycle()
        
        # Verify results
        assert result.total_signals == 3  # Only 15m and 1h
        assert len(result.winners) <= 3  # Top N limit
        assert result.rejected_by_cycle_dup == 1  # BTC duplicate
        assert result.rejected_by_position_dup == 1  # DOGE already positioned
        
        # Verify timeframe filtering in metrics
        assert "15m" in result.timeframe_filter_used or "15m" in str(result.timeframe_filter_used)
    
    def test_cross_asset_competition(self):
        """Test that best edges across assets compete correctly."""
        arbiter = CryptoTopEdgeArbiter(gamma=0.5, top_n=2)
        
        # All 15m candidates
        candidates = [
            create_momentum_candidate(asset="BTC", timeframe="15m", net_edge=0.03),
            create_momentum_candidate(asset="ETH", timeframe="15m", net_edge=0.05),  # Best
            create_momentum_candidate(asset="SOL", timeframe="15m", net_edge=0.04),  # Second
            create_momentum_candidate(asset="XRP", timeframe="15m", net_edge=0.02),
            create_momentum_candidate(asset="DOGE", timeframe="15m", net_edge=0.01),
        ]
        
        for c in candidates:
            arbiter.submit_candidate(c)
        
        result = arbiter.run_cycle()
        
        # Top 2 should be ETH and SOL
        assert len(result.winners) == 2
        assert result.winners[0].asset == "ETH"
        assert result.winners[1].asset == "SOL"
        assert result.top_edge == 0.05


# =============================================================================
# Metrics and Monitoring Tests
# =============================================================================

class TestMetricsAndMonitoring:
    """Test metrics collection and reporting."""
    
    def test_metrics_include_dedup_stats(self):
        """Test that metrics include deduplication statistics."""
        arbiter = CryptoTopEdgeArbiter(
            position_dedup_enabled=True,
            in_cycle_dedup_enabled=True
        )
        
        # Run a cycle with dedup
        c1 = create_momentum_candidate(
            existing_position_contracts=5, existing_position_direction="long", direction="long"
        )
        c2 = create_momentum_candidate(asset="BTC", direction="long", net_edge=0.06)
        c3 = create_momentum_candidate(asset="BTC", direction="long", net_edge=0.05)  # Duplicate
        
        for c in [c1, c2, c3]:
            arbiter.submit_candidate(c)
        
        arbiter.run_cycle()
        
        # Check metrics
        metrics = arbiter.get_metrics()
        assert "total_contracts_deduped" in metrics
        assert "config" in metrics
        assert metrics["config"]["position_dedup_enabled"] == True
        assert metrics["config"]["in_cycle_dedup_enabled"] == True
        assert "timeframes" in metrics["config"]
    
    def test_result_serialization_includes_dedup(self):
        """Test that result serialization includes dedup fields."""
        arbiter = CryptoTopEdgeArbiter()
        
        c = create_momentum_candidate()
        arbiter.submit_candidate(c)
        result = arbiter.run_cycle()
        
        d = result.to_dict()
        assert "rejected_by_position_dup" in d["selection"]
        assert "rejected_by_cycle_dup" in d["selection"]
        assert "deduped_contracts_saved" in d["selection"]
        assert "timeframes_considered" in d["selection"]
