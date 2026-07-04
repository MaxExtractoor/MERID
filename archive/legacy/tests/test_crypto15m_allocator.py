"""Unit tests for Crypto15MAllocator — cross-asset risk allocator for 15m crypto markets.

Test coverage:
1. Allocator selection logic (scoring, ranking, selection)
2. Timeframe budget enforcement
3. Per-expiry open exposure cap enforcement
4. Directional/MM conflict resolution
5. Risk gate integration helpers
6. Position tracking and sync
"""

from __future__ import annotations

import time
import pytest
from typing import List, Tuple

from merid.prediction.crypto15mallocator import (
    Crypto15MAllocator,
    Crypto15MAllocatorConfig,
    TradeIntent,
    HoldReason,
    compute_score,
    is_15m_crypto_ticker,
    resolve_expiry_id_from_ticker,
    extract_asset_from_ticker,
    compute_15m_tf_bucket,
    check_timeframe_budget,
    check_expiry_open_cap,
    is_increasing_exposure_check,
    get_crypto15m_allocator,
    reset_crypto15m_allocator_for_testing,
)


class TestCrypto15MConstants:
    """Test constant definitions."""
    
    def test_15m_crypto_pattern_matches_valid_tickers(self):
        """Test that 15m crypto pattern matches valid tickers."""
        valid_tickers = [
            "KXBTC15M-26APR191400-00",
            "KXETH15M-26APR191400-00",
            "KXSOL15M-26APR191400-00",
            "KXXRP15M-26APR191400-00",
            "KXDOGE15M-26APR191400-00",
        ]
        for ticker in valid_tickers:
            assert is_15m_crypto_ticker(ticker), f"Should match: {ticker}"
    
    def test_15m_crypto_pattern_rejects_invalid_tickers(self):
        """Test that 15m crypto pattern rejects invalid tickers."""
        invalid_tickers = [
            "KXBTC-26APR191400-00",  # Missing 15M
            "KXETH1H-26APR191400-00",  # Wrong timeframe
            "KXBTCD-26APR191400-00",  # Daily
            "KXFED-26APR191400-00",  # Not crypto
            "random",
            "",
        ]
        for ticker in invalid_tickers:
            assert not is_15m_crypto_ticker(ticker), f"Should NOT match: {ticker}"


class TestExpiryIdResolution:
    """Test expiry ID extraction from tickers."""
    
    def test_resolve_expiry_id_success(self):
        """Test successful expiry ID resolution."""
        ticker = "KXBTC15M-26APR191400-00"
        expiry_id = resolve_expiry_id_from_ticker(ticker)
        assert expiry_id == "CRYPTO_15M:26APR191400"
    
    def test_resolve_expiry_id_failure(self):
        """Test expiry ID resolution failure for non-15m ticker."""
        ticker = "KXBTC-26APR191400-00"
        expiry_id = resolve_expiry_id_from_ticker(ticker)
        assert expiry_id is None


class TestAssetExtraction:
    """Test asset symbol extraction from tickers."""
    
    def test_extract_all_crypto_assets(self):
        """Test extraction of all supported crypto assets."""
        test_cases = [
            ("KXBTC15M-26APR191400-00", "BTC"),
            ("KXETH15M-26APR191400-00", "ETH"),
            ("KXSOL15M-26APR191400-00", "SOL"),
            ("KXXRP15M-26APR191400-00", "XRP"),
            ("KXDOGE15M-26APR191400-00", "DOGE"),
        ]
        for ticker, expected in test_cases:
            result = extract_asset_from_ticker(ticker)
            assert result == expected, f"Expected {expected}, got {result} for {ticker}"


class TestTimeframeBucket:
    """Test 15m timeframe bucket computation."""
    
    def test_bucket_computation(self):
        """Test that bucket computation returns correct values."""
        # Use a known timestamp
        ts = 1713549600  # 2024-04-19 18:00:00 UTC
        bucket_start, bucket_iso = compute_15m_tf_bucket(ts)
        
        # Should align to 15m boundary
        assert bucket_start % 900 == 0  # 900 seconds = 15 minutes
        assert len(bucket_iso) == 13  # Format: YYYYMMDD_HHMM
    
    def test_bucket_consistency(self):
        """Test that same 15m window produces same bucket."""
        base_ts = 1713549600
        # Two timestamps within same 15m window (first 10 minutes)
        ts1 = base_ts
        ts2 = base_ts + 600  # +10 minutes
        
        bucket1, _ = compute_15m_tf_bucket(ts1)
        bucket2, _ = compute_15m_tf_bucket(ts2)
        
        assert bucket1 == bucket2
    
    def test_bucket_different_windows(self):
        """Test that different 15m windows produce different buckets."""
        ts1 = 1713549600  # 18:00
        ts2 = 1713550500  # 18:15 (next window)
        
        bucket1, _ = compute_15m_tf_bucket(ts1)
        bucket2, _ = compute_15m_tf_bucket(ts2)
        
        assert bucket1 != bucket2


class TestScoring:
    """Test intent scoring logic."""
    
    def test_directional_scoring(self):
        """Test directional intent scoring (netedge * confidence)."""
        intent = TradeIntent(
            intent_id="test-1",
            agent_id="BTC15M",
            ticker="KXBTC15M-26APR191400-00",
            asset="BTC",
            timeframe="15m",
            expiry_id="CRYPTO_15M:26APR191400",
            side="YES",
            intended_contracts=1,
            limit_price_cents=55,
            netedge=0.05,
            confidence=60.0,
            is_market_maker=False,
        )
        score = compute_score(intent)
        expected = 0.05 * 60.0  # 3.0
        assert score == pytest.approx(expected, 0.001)
    
    def test_mm_scoring_with_implied_edge(self):
        """Test MM intent scoring with implied edge available."""
        intent = TradeIntent(
            intent_id="test-2",
            agent_id="CRYPTO15MMM",
            ticker="KXBTC15M-26APR191400-00",
            asset="BTC",
            timeframe="15m",
            expiry_id="CRYPTO_15M:26APR191400",
            side="YES",
            intended_contracts=1,
            limit_price_cents=55,
            is_market_maker=True,
            implied_edge_from_spread=0.03,
            confidence=50.0,
        )
        score = compute_score(intent)
        expected = 0.03 * 50.0  # 1.5
        assert score == pytest.approx(expected, 0.001)
    
    def test_mm_scoring_fallback(self):
        """Test MM intent scoring fallback (no implied edge)."""
        intent = TradeIntent(
            intent_id="test-3",
            agent_id="CRYPTO15MMM",
            ticker="KXBTC15M-26APR191400-00",
            asset="BTC",
            timeframe="15m",
            expiry_id="CRYPTO_15M:26APR191400",
            side="YES",
            intended_contracts=1,
            limit_price_cents=55,
            is_market_maker=True,
            consensus_confidence=40.0,
        )
        score = compute_score(intent)
        assert score == 40.0


class TestAllocatorSelection:
    """Test allocator selection logic."""
    
    def setup_method(self):
        """Reset allocator before each test."""
        reset_crypto15m_allocator_for_testing()
        self.allocator = get_crypto15m_allocator()
        self.allocator.reset()
    
    def test_single_intent_approved(self):
        """Test that a single valid intent gets approved."""
        intent = TradeIntent(
            intent_id="test-1",
            agent_id="BTC15M",
            ticker="KXBTC15M-26APR191400-00",
            asset="BTC",
            timeframe="15m",
            expiry_id="CRYPTO_15M:26APR191400",
            side="YES",
            intended_contracts=1,
            limit_price_cents=55,
            netedge=0.05,
            confidence=60.0,
        )
        
        self.allocator.submit_intent(intent)
        approved, blocked = self.allocator.run_allocation_cycle(bankroll_equity_usd=1000.0)
        
        assert len(approved) == 1
        assert len(blocked) == 0
        assert approved[0].intent_id == "test-1"
        assert approved[0].mode == "live"
    
    def test_budget_exhaustion_blocks_new(self):
        """Test that timeframe budget exhaustion blocks new intents."""
        config = Crypto15MAllocatorConfig(
            max_contracts_per_tf_crypto_15m=1,
            max_markets_per_tf_crypto_15m=3,
        )
        allocator = Crypto15MAllocator(config)
        
        # First intent uses the 1 contract budget
        intent1 = TradeIntent(
            intent_id="test-1",
            agent_id="BTC15M",
            ticker="KXBTC15M-26APR191400-00",
            asset="BTC",
            timeframe="15m",
            expiry_id="CRYPTO_15M:26APR191400",
            side="YES",
            intended_contracts=1,
            limit_price_cents=55,
            netedge=0.05,
            confidence=60.0,
        )
        
        # Second intent should be blocked
        intent2 = TradeIntent(
            intent_id="test-2",
            agent_id="ETH15M",
            ticker="KXETH15M-26APR191400-00",
            asset="ETH",
            timeframe="15m",
            expiry_id="CRYPTO_15M:26APR191400",
            side="YES",
            intended_contracts=1,
            limit_price_cents=55,
            netedge=0.04,
            confidence=55.0,
        )
        
        allocator.submit_intent(intent1)
        allocator.submit_intent(intent2)
        approved, blocked = allocator.run_allocation_cycle()
        
        assert len(approved) == 1
        assert len(blocked) == 1
        assert blocked[0].hold_reason == HoldReason.TIMEFRAME_BUDGET_EXHAUSTED.value
    
    def test_markets_limit_enforced(self):
        """Test that markets limit is enforced."""
        config = Crypto15MAllocatorConfig(
            max_contracts_per_tf_crypto_15m=10,
            max_markets_per_tf_crypto_15m=2,  # Only 2 markets allowed
            max_open_contracts_per_expiry_crypto_15m=10,  # High cap so expiry doesn't block
        )
        allocator = Crypto15MAllocator(config)
        
        # Submit 3 intents for 3 different markets
        for i, asset in enumerate(["BTC", "ETH", "SOL"]):
            intent = TradeIntent(
                intent_id=f"test-{i}",
                agent_id=f"{asset}15M",
                ticker=f"KX{asset}15M-26APR191400-00",
                asset=asset,
                timeframe="15m",
                expiry_id="CRYPTO_15M:26APR191400",
                side="YES",
                intended_contracts=1,
                limit_price_cents=55,
                netedge=0.05 - (i * 0.01),  # Decreasing edge
                confidence=60.0,
            )
            allocator.submit_intent(intent)
        
        approved, blocked = allocator.run_allocation_cycle()
        
        assert len(approved) == 2  # Only top 2 by score
        assert len(blocked) == 1
        assert blocked[0].hold_reason == HoldReason.MARKETS_LIMIT_REACHED.value
    
    def test_scoring_ranking(self):
        """Test that intents are ranked by score correctly."""
        config = Crypto15MAllocatorConfig(
            max_contracts_per_tf_crypto_15m=1,
            max_markets_per_tf_crypto_15m=1,  # Only 1 market
        )
        allocator = Crypto15MAllocator(config)
        
        # BTC has highest score: 0.05 * 60 = 3.0
        # ETH: 0.04 * 55 = 2.2
        intents = [
            TradeIntent(
                intent_id="eth",
                agent_id="ETH15M",
                ticker="KXETH15M-26APR191400-00",
                asset="ETH",
                timeframe="15m",
                expiry_id="CRYPTO_15M:26APR191400",
                side="YES",
                intended_contracts=1,
                limit_price_cents=55,
                netedge=0.04,
                confidence=55.0,
            ),
            TradeIntent(
                intent_id="btc",
                agent_id="BTC15M",
                ticker="KXBTC15M-26APR191400-00",
                asset="BTC",
                timeframe="15m",
                expiry_id="CRYPTO_15M:26APR191400",
                side="YES",
                intended_contracts=1,
                limit_price_cents=55,
                netedge=0.05,
                confidence=60.0,
            ),
        ]
        
        for intent in intents:
            allocator.submit_intent(intent)
        
        approved, blocked = allocator.run_allocation_cycle()
        
        assert len(approved) == 1
        assert approved[0].intent_id == "btc"  # Highest score wins
        assert blocked[0].intent_id == "eth"
    
    def test_directional_mm_conflict_resolution(self):
        """Test that directional/MM conflicts are resolved (winner takes ticker)."""
        config = Crypto15MAllocatorConfig(
            max_contracts_per_tf_crypto_15m=2,
            max_markets_per_tf_crypto_15m=2,
            max_open_contracts_per_expiry_crypto_15m=10,  # High cap so expiry doesn't block
        )
        allocator = Crypto15MAllocator(config)
        
        # Both want same ticker
        directional = TradeIntent(
            intent_id="dir",
            agent_id="BTC15M",
            ticker="KXBTC15M-26APR191400-00",
            asset="BTC",
            timeframe="15m",
            expiry_id="CRYPTO_15M:26APR191400",
            side="YES",
            intended_contracts=1,
            limit_price_cents=55,
            netedge=0.05,
            confidence=60.0,  # Score = 3.0
            is_market_maker=False,
        )
        
        mm = TradeIntent(
            intent_id="mm",
            agent_id="CRYPTO15MMM",
            ticker="KXBTC15M-26APR191400-00",
            asset="BTC",
            timeframe="15m",
            expiry_id="CRYPTO_15M:26APR191400",
            side="YES",
            intended_contracts=1,
            limit_price_cents=55,
            is_market_maker=True,
            consensus_confidence=50.0,  # Score = 50.0 (wins!)
        )
        
        allocator.submit_intent(directional)
        allocator.submit_intent(mm)
        approved, blocked = allocator.run_allocation_cycle()
        
        # MM wins due to higher score
        assert len(approved) == 1
        assert approved[0].intent_id == "mm"
        assert len(blocked) == 1
        assert blocked[0].intent_id == "dir"
        assert blocked[0].hold_reason == HoldReason.DIRECTIONAL_MM_CONFLICT.value


class TestExpiryCap:
    """Test per-expiry open exposure cap."""
    
    def test_expiry_cap_enforced(self):
        """Test that expiry cap blocks new exposure when at limit."""
        config = Crypto15MAllocatorConfig(
            max_contracts_per_tf_crypto_15m=10,
            max_markets_per_tf_crypto_15m=10,
            max_open_contracts_per_expiry_crypto_15m=1,
        )
        allocator = Crypto15MAllocator(config)
        
        # Manually set up expiry state with 1 open contract
        expiry_state = allocator._get_or_create_expiry_state("CRYPTO_15M:26APR191400")
        expiry_state.open_contracts_long = 1
        
        # New intent for same expiry
        intent = TradeIntent(
            intent_id="test-1",
            agent_id="SOL15M",
            ticker="KXSOL15M-26APR191400-00",
            asset="SOL",
            timeframe="15m",
            expiry_id="CRYPTO_15M:26APR191400",
            side="YES",
            intended_contracts=1,
            limit_price_cents=55,
            netedge=0.05,
            confidence=60.0,
        )
        
        allocator.submit_intent(intent)
        approved, blocked = allocator.run_allocation_cycle()
        
        assert len(approved) == 0
        assert len(blocked) == 1
        assert blocked[0].hold_reason == HoldReason.EXPIRY_OPEN_EXPOSURE_EXHAUSTED.value


class TestRiskGateHelpers:
    """Test risk gate integration helpers."""
    
    def test_increasing_exposure_new_position(self):
        """Test that new position is considered increasing."""
        result = is_increasing_exposure_check(
            ticker="KXBTC15M-26APR191400-00",
            side="YES",
            requested_contracts=1,
            existing_position_contracts=0,
        )
        assert result is True
    
    def test_increasing_exposure_same_side(self):
        """Test that adding to same side is increasing."""
        result = is_increasing_exposure_check(
            ticker="KXBTC15M-26APR191400-00",
            side="YES",
            requested_contracts=1,
            existing_position_contracts=2,
            existing_position_side="YES",
        )
        assert result is True
    
    def test_decreasing_exposure_opposite_side(self):
        """Test that opposite side (smaller) is decreasing."""
        result = is_increasing_exposure_check(
            ticker="KXBTC15M-26APR191400-00",
            side="NO",  # Opposite of existing
            requested_contracts=1,
            existing_position_contracts=2,
            existing_position_side="YES",
        )
        assert result is False
    
    def test_increasing_exposure_flip(self):
        """Test that opposite side (larger) is increasing (flip)."""
        result = is_increasing_exposure_check(
            ticker="KXBTC15M-26APR191400-00",
            side="NO",
            requested_contracts=5,  # Larger than existing
            existing_position_contracts=2,
            existing_position_side="YES",
        )
        assert result is True  # Net flip is treated as increase
    
    def test_timeframe_budget_check_non_15m(self):
        """Test that non-15m tickers pass through."""
        allowed, approved, reason = check_timeframe_budget(
            ticker="KXBTC-26APR191400-00",  # Daily
            requested_contracts=5,
            bankroll_equity_usd=1000.0,
        )
        assert allowed is True
        assert approved == 5
        assert "not_15m_crypto" in reason
    
    def test_expiry_cap_reduction_always_allowed(self):
        """Test that reductions are always allowed."""
        allowed, approved, reason = check_expiry_open_cap(
            ticker="KXBTC15M-26APR191400-00",
            requested_contracts=1,
            is_increasing_exposure=False,  # Reduction
        )
        assert allowed is True
        assert "reduction_always_allowed" in reason


class TestConfig:
    """Test allocator configuration."""
    
    def test_constant_budget(self):
        """Test constant budget scaling."""
        config = Crypto15MAllocatorConfig(
            max_contracts_per_tf_crypto_15m=2,
            contract_budget_scale_crypto_15m="constant",
        )
        
        # Should always return base value regardless of bankroll
        assert config.compute_effective_budget(50.0) == 2
        assert config.compute_effective_budget(1000.0) == 2
        assert config.compute_effective_budget(10000.0) == 2
    
    def test_linear_budget(self):
        """Test linear budget scaling."""
        config = Crypto15MAllocatorConfig(
            max_contracts_per_tf_crypto_15m=1,
            contract_budget_scale_crypto_15m="linear",
            contract_budget_scale_factor=0.02,  # +1 contract per $5000
        )
        
        # Base 1 + ($10000 * 0.02 / 100) = 1 + 2 = 3
        effective = config.compute_effective_budget(10000.0)
        assert effective >= 1
        assert effective <= 3  # Capped at 3x base


class TestPositionTracking:
    """Test position tracking and sync."""
    
    def setup_method(self):
        """Reset allocator before each test."""
        reset_crypto15m_allocator_for_testing()
        self.allocator = get_crypto15m_allocator()
        self.allocator.reset()
    
    def test_record_fill_updates_expiry(self):
        """Test that fill recording updates expiry state."""
        # Record a fill
        self.allocator.record_fill(
            ticker="KXBTC15M-26APR191400-00",
            contracts=1,
            side="YES",
        )
        
        # Check expiry state
        expiry_state = self.allocator.get_expiry_exposure("CRYPTO_15M:26APR191400")
        assert expiry_state is not None
        assert expiry_state.open_contracts_long == 1
        assert expiry_state.open_contracts_short == 0
    
    def test_record_close_updates_expiry(self):
        """Test that position closure updates expiry state."""
        # First open a position
        self.allocator.record_fill(
            ticker="KXBTC15M-26APR191400-00",
            contracts=2,
            side="YES",
        )
        
        # Then close it partially
        self.allocator.record_position_close(
            ticker="KXBTC15M-26APR191400-00",
            contracts=1,
            side="YES",
        )
        
        expiry_state = self.allocator.get_expiry_exposure("CRYPTO_15M:26APR191400")
        assert expiry_state.open_contracts_long == 1
    
    def test_multiple_assets_same_expiry(self):
        """Test that multiple assets for same expiry accumulate."""
        # BTC and ETH for same expiry
        self.allocator.record_fill("KXBTC15M-26APR191400-00", 1, "YES")
        self.allocator.record_fill("KXETH15M-26APR191400-00", 1, "YES")
        
        expiry_state = self.allocator.get_expiry_exposure("CRYPTO_15M:26APR191400")
        assert expiry_state.open_contracts_long == 2  # Both count
        assert expiry_state.net_open_contracts == 2


class TestIntegrationScenario:
    """Integration test scenarios matching spec requirements."""
    
    def setup_method(self):
        """Reset allocator before each test."""
        reset_crypto15m_allocator_for_testing()
        self.allocator = get_crypto15m_allocator()
        self.allocator.reset()
    
    def test_spec_scenario_5_assets_1_wins(self):
        """Spec scenario: 5 assets, only 1 contract budget → 1 winner."""
        config = Crypto15MAllocatorConfig(
            max_contracts_per_tf_crypto_15m=1,
            max_markets_per_tf_crypto_15m=3,
        )
        allocator = Crypto15MAllocator(config)
        
        # 5 intents, BTC has highest score
        assets = [
            ("BTC", 0.06, 65.0),  # Score: 3.9 (winner)
            ("ETH", 0.05, 60.0),  # Score: 3.0
            ("SOL", 0.04, 55.0),  # Score: 2.2
            ("XRP", 0.03, 50.0),  # Score: 1.5
            ("DOGE", 0.02, 45.0),  # Score: 0.9
        ]
        
        for asset, edge, conf in assets:
            intent = TradeIntent(
                intent_id=f"{asset.lower()}",
                agent_id=f"{asset}15M",
                ticker=f"KX{asset}15M-26APR191400-00",
                asset=asset,
                timeframe="15m",
                expiry_id="CRYPTO_15M:26APR191400",
                side="YES",
                intended_contracts=1,
                limit_price_cents=55,
                netedge=edge,
                confidence=conf,
            )
            allocator.submit_intent(intent)
        
        approved, blocked = allocator.run_allocation_cycle()
        
        assert len(approved) == 1
        assert approved[0].asset == "BTC"
        assert len(blocked) == 4
        
        # All blocked due to budget exhaustion
        for b in blocked:
            assert b.hold_reason == HoldReason.TIMEFRAME_BUDGET_EXHAUSTED.value
    
    def test_spec_scenario_existing_expiry_blocks(self):
        """Spec scenario: existing open position blocks new for same expiry."""
        config = Crypto15MAllocatorConfig(
            max_contracts_per_tf_crypto_15m=10,
            max_markets_per_tf_crypto_15m=10,
            max_open_contracts_per_expiry_crypto_15m=1,
        )
        allocator = Crypto15MAllocator(config)
        
        # Pre-populate with 1 open contract for this expiry
        expiry_state = allocator._get_or_create_expiry_state("CRYPTO_15M:26APR191400")
        expiry_state.open_contracts_long = 1
        
        # Try to open another for same expiry
        intent = TradeIntent(
            intent_id="btc",
            agent_id="BTC15M",
            ticker="KXBTC15M-26APR191400-00",
            asset="BTC",
            timeframe="15m",
            expiry_id="CRYPTO_15M:26APR191400",
            side="YES",
            intended_contracts=1,
            limit_price_cents=55,
            netedge=0.05,
            confidence=60.0,
        )
        allocator.submit_intent(intent)
        
        approved, blocked = allocator.run_allocation_cycle()
        
        assert len(approved) == 0
        assert len(blocked) == 1
        assert blocked[0].hold_reason == HoldReason.EXPIRY_OPEN_EXPOSURE_EXHAUSTED.value


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
