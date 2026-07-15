"""
Unit tests for unified edge module.
"""

import pytest
from datetime import datetime, timezone
from decimal import Decimal

from merid.prediction.unified_edge import (
    UnifiedEdgeComputer,
    SpotReference,
    ContractState,
    EdgeResult,
    PerAssetCalibration,
)
from merid.event_venues.kalshi.unified_market_state import OrderbookSnapshot, OrderbookLevel


class TestSpotReference:
    """Test SpotReference dataclass."""
    
    def test_spot_reference_creation(self):
        """Test creating a SpotReference."""
        spot_ref = SpotReference(
            asset="BTC",
            price_usd=70000.0,
            timestamp=datetime.now(timezone.utc),
            source="CFB",
            is_rti_proxy=True,
        )
        assert spot_ref.asset == "BTC"
        assert spot_ref.price_usd == 70000.0
        assert spot_ref.source == "CFB"
        assert spot_ref.is_rti_proxy is True


class TestContractState:
    """Test ContractState dataclass."""
    
    def test_contract_state_creation(self):
        """Test creating a ContractState."""
        contract = ContractState(
            market_id="KXBTC15M-26APR141315-30",
            asset="BTC",
            side="yes",
            strike_price=70000.0,
            mid_price_cents=5000,  # $50.00
            time_to_expiry_seconds=600,  # 10 minutes
            orderbook=None,
        )
        assert contract.market_id == "KXBTC15M-26APR141315-30"
        assert contract.asset == "BTC"
        assert contract.side == "yes"
        assert contract.strike_price == 70000.0
        assert contract.mid_price_cents == 5000
        assert contract.time_to_expiry_seconds == 600


class TestOrderBookSnapshot:
    """Test OrderBookSnapshot dataclass."""
    
    def test_orderbook_snapshot_creation(self):
        """Test creating an OrderbookSnapshot."""
        from merid.event_venues.kalshi.unified_market_state import OrderbookLevel, OrderbookSnapshot
        
        yes_bids = (OrderbookLevel(price_cents=49, size=100),)
        no_bids = (OrderbookLevel(price_cents=49, size=100),)  # 100 - 51 = 49
        orderbook = OrderbookSnapshot(
            ticker="KXBTC15M-TEST",
            yes_bids=yes_bids,
            no_bids=no_bids,
            ts=datetime.now(timezone.utc).timestamp()
        )
        assert orderbook.ticker == "KXBTC15M-TEST"
        assert orderbook.yes_bids[0].price_cents == 49
        assert orderbook.no_bids[0].price_cents == 49


class TestPerAssetCalibration:
    """Test PerAssetCalibration class."""
    
    def test_calibration_creation(self):
        """Test creating a PerAssetCalibration."""
        cal = PerAssetCalibration(profile_config=None)
        assert cal.calibrations is not None
        assert "BTC" in cal.calibrations
        assert cal.calibrations["BTC"]["base_win_rate"] == 0.5
        assert cal.calibrations["BTC"]["spot_sensitivity"] == 0.1
        assert cal.calibrations["BTC"]["time_decay"] == 0.05


class TestUnifiedEdgeComputer:
    """Test UnifiedEdgeComputer."""
    
    def test_initialization(self):
        """Test initializing UnifiedEdgeComputer."""
        computer = UnifiedEdgeComputer()
        assert computer.calibration is not None
    
    def test_compute_market_implied_prob(self):
        """Test computing market implied probability."""
        computer = UnifiedEdgeComputer()
        
        contract = ContractState(
            market_id="KXBTC15M-26APR141315-30",
            asset="BTC",
            side="yes",
            strike_price=70000.0,
            mid_price_cents=50,  # $0.50 = 50% probability (cents, not dollars)
            time_to_expiry_seconds=600,
            orderbook=None,
        )
        
        pi = computer.compute_market_implied_prob(contract)
        assert pi == 0.5  # 50 cents = 50% probability
    
    def test_compute_model_prob(self):
        """Test computing model win probability."""
        computer = UnifiedEdgeComputer()
        
        spot_ref = SpotReference(
            asset="BTC",
            price_usd=70000.0,
            timestamp=datetime.now(timezone.utc),
            source="CFB",
            is_rti_proxy=True,
        )
        
        contract = ContractState(
            market_id="KXBTC15M-26APR141315-30",
            asset="BTC",
            side="yes",
            strike_price=70000.0,
            mid_price_cents=5000,
            time_to_expiry_seconds=600,
            orderbook=None,
        )
        
        q = computer.compute_model_prob("BTC", spot_ref, contract)
        assert 0.0 <= q <= 1.0  # Probability should be in [0, 1]
    
    def test_compute_edge(self):
        """Test computing edge."""
        computer = UnifiedEdgeComputer()
        
        spot_ref = SpotReference(
            asset="BTC",
            price_usd=70000.0,
            timestamp=datetime.now(timezone.utc),
            source="CFB",
            is_rti_proxy=True,
        )
        
        contract = ContractState(
            market_id="KXBTC15M-26APR141315-30",
            asset="BTC",
            side="yes",
            strike_price=70000.0,
            mid_price_cents=5000,
            time_to_expiry_seconds=600,
            orderbook=None,
        )
        
        edge_result = computer.compute_edge("BTC", spot_ref, contract, order_size=1)
        assert isinstance(edge_result, EdgeResult)
        assert isinstance(edge_result.edge, float)
        assert isinstance(edge_result.edge_risk_adjusted, float)
        assert isinstance(edge_result.edge_slippage_adjusted, float)
        assert isinstance(edge_result.confidence, float)
    
    def test_compute_edge_with_orderbook(self):
        """Test computing edge with orderbook (slippage adjustment)."""
        computer = UnifiedEdgeComputer()
        
        spot_ref = SpotReference(
            asset="BTC",
            price_usd=70000.0,
            timestamp=datetime.now(timezone.utc),
            source="CFB",
            is_rti_proxy=True,
        )
        
        from merid.event_venues.kalshi.unified_market_state import OrderbookLevel, OrderbookSnapshot
        
        yes_bids = (OrderbookLevel(price_cents=49, size=100),)
        no_bids = (OrderbookLevel(price_cents=49, size=100),)
        orderbook = OrderbookSnapshot(
            ticker="KXBTC15M-TEST",
            yes_bids=yes_bids,
            no_bids=no_bids,
            ts=datetime.now(timezone.utc).timestamp()
        )
        
        contract = ContractState(
            market_id="KXBTC15M-26APR141315-30",
            asset="BTC",
            side="yes",
            strike_price=70000.0,
            mid_price_cents=5000,
            time_to_expiry_seconds=600,
            orderbook=orderbook,
        )
        
        edge_result = computer.compute_edge("BTC", spot_ref, contract, order_size=1)
        assert edge_result.edge_slippage_adjusted is not None
    
    def test_check_alignment(self):
        """Test checking alignment between spot and contract."""
        computer = UnifiedEdgeComputer()
        
        spot_ref = SpotReference(
            asset="BTC",
            price_usd=70000.0,
            timestamp=datetime.now(timezone.utc),
            source="CFB",
            is_rti_proxy=True,
        )
        
        contract = ContractState(
            market_id="KXBTC15M-26APR141315-30",
            asset="BTC",
            side="yes",
            strike_price=70000.0,
            mid_price_cents=50,  # 50 cents (not 5000 cents)
            time_to_expiry_seconds=600,
            orderbook=None,
        )
        
        is_aligned, gap_cents = computer.check_alignment("BTC", spot_ref, contract)
        assert isinstance(is_aligned, bool)
        assert isinstance(gap_cents, float)
        # Spot and strike are equal, so gap should be small
        assert gap_cents < 100  # < $1.00


class TestEdgeResult:
    """Test EdgeResult dataclass."""
    
    def test_edge_result_creation(self):
        """Test creating an EdgeResult."""
        result = EdgeResult(
            edge=0.05,
            edge_risk_adjusted=0.03,
            edge_slippage_adjusted=0.02,
            edge_fee_adjusted=0.01,
            model_prob=0.55,
            market_implied_prob=0.50,
            spot_ref=SpotReference(
                asset="BTC",
                price_usd=70000.0,
                timestamp=datetime.now(timezone.utc),
                source="CFB",
                is_rti_proxy=True,
            ),
            confidence=0.8,
            metadata={"asset": "BTC"},
            raw_edge_cents=5.0,
            spread_cost_cents=1.0,
            fee_cost_cents=1.0,
            net_edge_cents=3.0,
            ev_per_contract_cents=3.0,
        )
        assert result.edge == 0.05
        assert result.edge_risk_adjusted == 0.03
        assert result.edge_slippage_adjusted == 0.02
        assert result.edge_fee_adjusted == 0.01
        assert result.fee_cost_cents == 1.0
        assert result.net_edge_cents == 3.0
    
    def test_edge_result_distance_metrics(self):
        """Test EdgeResult distance metrics (dist_pct, dist_abs_pct)."""
        result = EdgeResult(
            edge=0.05,
            edge_risk_adjusted=0.03,
            edge_slippage_adjusted=0.02,
            edge_fee_adjusted=0.01,
            model_prob=0.55,
            market_implied_prob=0.50,
            spot_ref=SpotReference(
                asset="BTC",
                price_usd=73000.0,
                timestamp=datetime.now(timezone.utc),
                source="CFB",
                is_rti_proxy=True,
            ),
            confidence=0.8,
            metadata={"asset": "BTC", "strike": 73500.0},
            raw_edge_cents=5.0,
            spread_cost_cents=1.0,
            fee_cost_cents=1.0,
            net_edge_cents=3.0,
            ev_per_contract_cents=3.0,
            dist_pct=0.68,  # (73500 - 73000) / 73000 * 100 ≈ 0.68%
            dist_abs_pct=0.68,
        )
        assert result.dist_pct == 0.68
        assert result.dist_abs_pct == 0.68
        assert result.dist_abs_pct == abs(result.dist_pct)


class TestCanonicalFeeWiring:
    """Test canonical fee wiring in compute_fee_adjusted_edge."""
    
    def test_compute_fee_adjusted_edge_uses_canonical_formula(self):
        """Test that compute_fee_adjusted_edge uses canonical Kalshi fee formula."""
        from merid.event_venues.kalshi.fees import calculate_kalshi_fee_cents
        
        computer = UnifiedEdgeComputer()
        
        contract = ContractState(
            market_id="KXBTC15M-26APR141315-30",
            asset="BTC",
            side="yes",
            strike_price=70000.0,
            mid_price_cents=50,  # 50 cents (not 5000 cents)
            time_to_expiry_seconds=600,
            orderbook=None,
        )
        
        # Test with 1 contract at 50 cents
        edge_fee_adjusted, fee_cost_cents = computer.compute_fee_adjusted_edge(
            slippage_adjusted_edge=0.05,
            asset="BTC",
            contract=contract,
            order_size=1,
            order_side="taker",
        )
        
        # Verify fee matches canonical formula
        expected_fee = calculate_kalshi_fee_cents(contracts=1, price_cents=50)
        assert fee_cost_cents == expected_fee / 1  # Per-contract fee
        
        # Fee should be at least 2 cents (floor)
        assert fee_cost_cents >= 2
        
        # Edge should be reduced by fee probability
        expected_fee_prob = fee_cost_cents / 100.0
        assert edge_fee_adjusted == 0.05 - expected_fee_prob
    
    def test_compute_fee_adjusted_edge_tiered_pricing(self):
        """Test that fees use tiered pricing (7%/5%/3%)."""
        from merid.event_venues.kalshi.fees import calculate_kalshi_fee_cents
        
        computer = UnifiedEdgeComputer()
        
        contract = ContractState(
            market_id="KXBTC15M-26APR141315-30",
            asset="BTC",
            side="yes",
            strike_price=70000.0,
            mid_price_cents=50,  # 50 cents (not 5000 cents)
            time_to_expiry_seconds=600,
            orderbook=None,
        )
        
        # Test tier 1: < 100 contracts (7% rate)
        _, fee_1 = computer.compute_fee_adjusted_edge(0.05, "BTC", contract, 50, "taker")
        expected_1 = calculate_kalshi_fee_cents(contracts=50, price_cents=50) / 50
        assert fee_1 == expected_1
        
        # Test tier 2: 100-999 contracts (5% rate)
        _, fee_100 = computer.compute_fee_adjusted_edge(0.05, "BTC", contract, 100, "taker")
        expected_100 = calculate_kalshi_fee_cents(contracts=100, price_cents=50) / 100
        assert fee_100 == expected_100
        
        # Tier 2 should have lower per-contract fee than tier 1
        assert fee_100 < fee_1
    
    def test_compute_edge_includes_price_cents_in_metadata(self):
        """Test that compute_edge includes price_cents in EdgeResult.metadata."""
        computer = UnifiedEdgeComputer()
        
        spot_ref = SpotReference(
            asset="BTC",
            price_usd=70000.0,
            timestamp=datetime.now(timezone.utc),
            source="CFB",
            is_rti_proxy=True,
        )
        
        contract = ContractState(
            market_id="KXBTC15M-26APR141315-30",
            asset="BTC",
            side="yes",
            strike_price=70000.0,
            mid_price_cents=5000,
            time_to_expiry_seconds=600,
            orderbook=None,
        )
        
        edge_result = computer.compute_edge("BTC", spot_ref, contract, order_size=1)
        
        # Verify price_cents is in metadata
        assert "price_cents" in edge_result.metadata
        assert edge_result.metadata["price_cents"] == 5000


class TestPositionSizerCanonicalPath:
    """Test PositionSizer.compute_from_edge_result canonical path."""
    
    def test_compute_from_edge_result_basic(self):
        """Test basic compute_from_edge_result functionality."""
        from merid.event_venues.kalshi.position_sizer import PositionSizer
        
        sizer = PositionSizer()
        
        # Create synthetic EdgeResult
        edge_result = EdgeResult(
            edge=0.05,
            edge_risk_adjusted=0.03,
            edge_slippage_adjusted=0.02,
            edge_fee_adjusted=0.01,  # 1% fee-adjusted edge
            model_prob=0.55,
            market_implied_prob=0.50,
            spot_ref=SpotReference(
                asset="BTC",
                price_usd=70000.0,
                timestamp=datetime.now(timezone.utc),
                source="CFB",
                is_rti_proxy=True,
            ),
            confidence=0.8,
            metadata={"asset": "BTC", "price_cents": 50},
            raw_edge_cents=5.0,
            spread_cost_cents=1.0,
            fee_cost_cents=1.0,  # 1 cent fee
            net_edge_cents=3.0,
            ev_per_contract_cents=3.0,
        )
        
        # Compute size
        size = sizer.compute_from_edge_result(
            agent_name="BTC_15M",
            edge_result=edge_result,
            bankroll_cents=500_000,  # $5000
        )
        
        # Should return a non-negative integer
        assert isinstance(size, int)
        assert size >= 0
    
    def test_compute_from_edge_result_reconstructs_win_prob(self):
        """Test that compute_from_edge_result correctly reconstructs win probability."""
        from merid.event_venues.kalshi.position_sizer import PositionSizer, PROB_MIN_BOUND, PROB_MAX_BOUND
        
        sizer = PositionSizer()
        
        # Create EdgeResult with known values
        # edge_fee_adjusted = q - π - fee_prob
        # So q = π + edge_fee_adjusted + fee_prob
        market_implied_prob = 0.50
        edge_fee_adjusted = 0.02
        fee_cost_cents = 1.0  # 1 cent
        fee_prob = fee_cost_cents / 100.0  # 0.01
        expected_q = market_implied_prob + edge_fee_adjusted + fee_prob  # 0.53
        
        edge_result = EdgeResult(
            edge=0.03,
            edge_risk_adjusted=0.025,
            edge_slippage_adjusted=0.022,
            edge_fee_adjusted=edge_fee_adjusted,
            model_prob=expected_q,
            market_implied_prob=market_implied_prob,
            spot_ref=SpotReference(
                asset="BTC",
                price_usd=70000.0,
                timestamp=datetime.now(timezone.utc),
                source="CFB",
                is_rti_proxy=True,
            ),
            confidence=0.8,
            metadata={"asset": "BTC", "price_cents": 50},
            raw_edge_cents=3.0,
            spread_cost_cents=0.8,
            fee_cost_cents=fee_cost_cents,
            net_edge_cents=2.2,
            ev_per_contract_cents=2.2,
        )
        
        # This should not raise an error
        size = sizer.compute_from_edge_result(
            agent_name="BTC_15M",
            edge_result=edge_result,
            bankroll_cents=500_000,
        )
        
        # Should succeed
        assert size >= 0
    
    def test_compute_from_edge_result_negative_edge_returns_zero(self):
        """Test that negative edge returns 0 contracts."""
        from merid.event_venues.kalshi.position_sizer import PositionSizer
        
        sizer = PositionSizer()
        
        # EdgeResult with negative fee-adjusted edge
        edge_result = EdgeResult(
            edge=-0.01,
            edge_risk_adjusted=-0.02,
            edge_slippage_adjusted=-0.03,
            edge_fee_adjusted=-0.05,  # Negative edge
            model_prob=0.45,
            market_implied_prob=0.50,
            spot_ref=SpotReference(
                asset="BTC",
                price_usd=70000.0,
                timestamp=datetime.now(timezone.utc),
                source="CFB",
                is_rti_proxy=True,
            ),
            confidence=0.5,
            metadata={"asset": "BTC", "price_cents": 50},
            raw_edge_cents=-1.0,
            spread_cost_cents=1.0,
            fee_cost_cents=1.0,
            net_edge_cents=-3.0,
            ev_per_contract_cents=-3.0,
        )
        
        size = sizer.compute_from_edge_result(
            agent_name="BTC_15M",
            edge_result=edge_result,
            bankroll_cents=500_000,
        )
        
        # Should return 0 for negative edge
        assert size == 0
    
    def test_compute_from_edge_result_invalid_price_returns_zero(self):
        """Test that invalid price returns 0 contracts."""
        from merid.event_venues.kalshi.position_sizer import PositionSizer
        
        sizer = PositionSizer()
        
        # EdgeResult with invalid price_cents
        edge_result = EdgeResult(
            edge=0.05,
            edge_risk_adjusted=0.03,
            edge_slippage_adjusted=0.02,
            edge_fee_adjusted=0.01,
            model_prob=0.55,
            market_implied_prob=0.50,
            spot_ref=SpotReference(
                asset="BTC",
                price_usd=70000.0,
                timestamp=datetime.now(timezone.utc),
                source="CFB",
                is_rti_proxy=True,
            ),
            confidence=0.8,
            metadata={"asset": "BTC", "price_cents": 0},  # Invalid: 0 cents
            raw_edge_cents=5.0,
            spread_cost_cents=1.0,
            fee_cost_cents=1.0,
            net_edge_cents=3.0,
            ev_per_contract_cents=3.0,
        )
        
        size = sizer.compute_from_edge_result(
            agent_name="BTC_15M",
            edge_result=edge_result,
            bankroll_cents=500_000,
        )
        
        # Should return 0 for invalid price
        assert size == 0


class TestTrapAvoidance:
    """Test trap-avoidance rules in unified edge."""
    
    def test_otm_reject_beyond_max_dist_pct(self):
        """Test OTM reject when beyond guardrails_max_dist_pct_trade."""
        computer = UnifiedEdgeComputer()
        
        spot_ref = SpotReference(
            asset="BTC",
            price_usd=73000.0,
            timestamp=datetime.now(timezone.utc),
            source="CFB",
            is_rti_proxy=True,
        )
        
        from merid.event_venues.kalshi.unified_market_state import OrderbookLevel, OrderbookSnapshot
        
        yes_bids = (OrderbookLevel(price_cents=49, size=100),)
        no_bids = (OrderbookLevel(price_cents=49, size=100),)
        orderbook = OrderbookSnapshot(
            ticker="KXBTC15M-TEST",
            yes_bids=yes_bids,
            no_bids=no_bids,
            ts=datetime.now(timezone.utc).timestamp()
        )
        
        contract = ContractState(
            market_id="KXBTC15M-26APR141315-30",
            asset="BTC",
            side="yes",
            strike_price=75000.0,  # 2.74% away from spot (beyond 2.0% threshold)
            mid_price_cents=70,  # Within 10-75c canonical range
            time_to_expiry_seconds=600,  # 10 minutes (in window)
            orderbook=orderbook,
        )
        
        # Compute edge (will include dist metrics)
        edge_result = computer.compute_edge("BTC", spot_ref, contract, order_size=1)
        
        # Check edge - should reject on OTM distance
        check_result = computer.check_edge(edge_result, contract, vol_regime="NORMAL")
        
        assert check_result.passes is False
        assert "otm_distance_too_large" in check_result.reason
    
    def test_otm_within_distance_but_fails_edge_requirement(self):
        """Test within distance but fails on edge requirement for distance band."""
        computer = UnifiedEdgeComputer()
        
        spot_ref = SpotReference(
            asset="BTC",
            price_usd=73000.0,
            timestamp=datetime.now(timezone.utc),
            source="CFB",
            is_rti_proxy=True,
        )
        
        from merid.event_venues.kalshi.unified_market_state import OrderbookLevel, OrderbookSnapshot
        
        yes_bids = (OrderbookLevel(price_cents=49, size=100),)
        no_bids = (OrderbookLevel(price_cents=49, size=100),)
        orderbook = OrderbookSnapshot(
            ticker="KXBTC15M-TEST",
            yes_bids=yes_bids,
            no_bids=no_bids,
            ts=datetime.now(timezone.utc).timestamp()
        )
        
        contract = ContractState(
            market_id="KXBTC15M-26APR141315-30",
            asset="BTC",
            side="yes",
            strike_price=74000.0,  # 1.37% away (in 0.5-1.5% band)
            mid_price_cents=70,  # Within 10-75c canonical range
            time_to_expiry_seconds=600,
            orderbook=orderbook,
        )
        
        edge_result = computer.compute_edge("BTC", spot_ref, contract, order_size=1)
        
        # Manually set low edge to trigger distance-band edge requirement failure
        edge_result.net_edge_cents = 0.3  # Below 1.5% threshold for 0.5-1.5% band
        
        check_result = computer.check_edge(edge_result, contract, vol_regime="NORMAL")
        
        assert check_result.passes is False
        assert "otm_edge_insufficient" in check_result.reason
    
    def test_time_trap_too_early(self):
        """Test TIME-REJECT when too early in window."""
        pytest.skip("Time trap checks require calibration data and specific configuration not available in test environment")
    
    def test_time_trap_too_late(self):
        """Test TIME-REJECT when too late in window."""
        pytest.skip("Time trap checks require calibration data and specific configuration not available in test environment")
    
    def test_time_trap_in_window_passes(self):
        """Test that in-window TTE passes time checks."""
        computer = UnifiedEdgeComputer()
        
        spot_ref = SpotReference(
            asset="BTC",
            price_usd=73000.0,
            timestamp=datetime.now(timezone.utc),
            source="CFB",
            is_rti_proxy=True,
        )
        
        from merid.event_venues.kalshi.unified_market_state import OrderbookLevel, OrderbookSnapshot
        
        yes_bids = (OrderbookLevel(price_cents=49, size=100),)
        no_bids = (OrderbookLevel(price_cents=49, size=100),)
        orderbook = OrderbookSnapshot(
            ticker="KXBTC15M-TEST",
            yes_bids=yes_bids,
            no_bids=no_bids,
            ts=datetime.now(timezone.utc).timestamp()
        )
        
        contract = ContractState(
            market_id="KXBTC15M-26APR141315-30",
            asset="BTC",
            side="yes",
            strike_price=73000.0,
            mid_price_cents=70,  # Within 10-75c canonical range
            time_to_expiry_seconds=300,  # 5 minutes (in 2-12min window)
            orderbook=orderbook,
        )
        
        edge_result = computer.compute_edge("BTC", spot_ref, contract, order_size=1)
        check_result = computer.check_edge(edge_result, contract, vol_regime="NORMAL")
        
        # Should not fail on time traps (may fail on other checks)
        assert "time_trap" not in check_result.reason.lower()
    
    def test_microstructure_trap_spread_acceptable_for_strong_edge(self):
        """Test that spread is acceptable for strong edge."""
        computer = UnifiedEdgeComputer()
        
        spot_ref = SpotReference(
            asset="BTC",
            price_usd=73000.0,
            timestamp=datetime.now(timezone.utc),
            source="CFB",
            is_rti_proxy=True,
        )
        
        from merid.event_venues.kalshi.unified_market_state import OrderbookLevel, OrderbookSnapshot
        
        yes_bids = (OrderbookLevel(price_cents=40, size=100),)
        no_bids = (OrderbookLevel(price_cents=59, size=100),)  # 100 - 41 = 59
        orderbook = OrderbookSnapshot(
            ticker="KXBTC15M-TEST",
            yes_bids=yes_bids,
            no_bids=no_bids,
            ts=datetime.now(timezone.utc).timestamp()
        )
        
        contract = ContractState(
            market_id="KXBTC15M-26APR141315-30",
            asset="BTC",
            side="yes",
            strike_price=73000.0,
            mid_price_cents=70,  # Within 10-75c canonical range
            time_to_expiry_seconds=300,
            orderbook=orderbook,
        )
        
        edge_result = computer.compute_edge("BTC", spot_ref, contract, order_size=1)
        # Manually set strong edge
        edge_result.net_edge_cents = 2.5  # Above 2% threshold
        
        check_result = computer.check_edge(edge_result, contract, vol_regime="NORMAL")
        
        # Should not fail on spread check (may fail on other checks)
        assert "microstructure_trap_spread_too_wide" not in check_result.reason
    
    def test_microstructure_trap_insufficient_depth(self):
        """Test DEPTH-REJECT when depth insufficient for order size."""
        pytest.skip("Microstructure depth checks require specific configuration not available in test environment")
    
    def test_microstructure_trap_sufficient_depth(self):
        """Test that sufficient depth passes depth check."""
        computer = UnifiedEdgeComputer()
        
        spot_ref = SpotReference(
            asset="BTC",
            price_usd=73000.0,
            timestamp=datetime.now(timezone.utc),
            source="CFB",
            is_rti_proxy=True,
        )
        
        from merid.event_venues.kalshi.unified_market_state import OrderbookLevel, OrderbookSnapshot
        
        yes_bids = (OrderbookLevel(price_cents=49, size=10),)  # Sufficient depth
        no_bids = (OrderbookLevel(price_cents=49, size=100),)
        orderbook = OrderbookSnapshot(
            ticker="KXBTC15M-TEST",
            yes_bids=yes_bids,
            no_bids=no_bids,
            ts=datetime.now(timezone.utc).timestamp()
        )
        
        contract = ContractState(
            market_id="KXBTC15M-26APR141315-30",
            asset="BTC",
            side="yes",
            strike_price=73000.0,
            mid_price_cents=70,  # Within 10-75c canonical range
            time_to_expiry_seconds=300,
            orderbook=orderbook,
        )
        
        edge_result = computer.compute_edge("BTC", spot_ref, contract, order_size=2)
        edge_result.metadata["order_size"] = 2
        
        check_result = computer.check_edge(edge_result, contract, vol_regime="NORMAL")
        
        # Should not fail on depth check (may fail on other checks)
        assert "microstructure_trap_insufficient_depth" not in check_result.reason
    
    def test_regime_cooldown_disabled(self):
        """Test that regime cooldown disabled does not reject."""
        computer = UnifiedEdgeComputer()
        
        spot_ref = SpotReference(
            asset="BTC",
            price_usd=73000.0,
            timestamp=datetime.now(timezone.utc),
            source="CFB",
            is_rti_proxy=True,
        )
        
        from merid.event_venues.kalshi.unified_market_state import OrderbookLevel, OrderbookSnapshot
        
        yes_bids = (OrderbookLevel(price_cents=49, size=100),)
        no_bids = (OrderbookLevel(price_cents=49, size=100),)
        orderbook = OrderbookSnapshot(
            ticker="KXBTC15M-TEST",
            yes_bids=yes_bids,
            no_bids=no_bids,
            ts=datetime.now(timezone.utc).timestamp()
        )
        
        contract = ContractState(
            market_id="KXBTC15M-26APR141315-30",
            asset="BTC",
            side="yes",
            strike_price=73000.0,
            mid_price_cents=70,  # Within 10-75c canonical range
            time_to_expiry_seconds=300,
            orderbook=orderbook,
        )
        
        edge_result = computer.compute_edge("BTC", spot_ref, contract, order_size=1)
        
        # With regime cooldown disabled (default), should not reject on regime
        check_result = computer.check_edge(edge_result, contract, vol_regime="NORMAL")
        
        assert "regime_trap_cooldown" not in check_result.reason


class TestUnifiedEdgeNoneHandling:
    """Test unified edge None handling fixes."""
    
    def test_compute_market_implied_prob_with_none_mid_price(self):
        """Test market implied probability handles None mid price gracefully."""
        computer = UnifiedEdgeComputer()
        
        contract = ContractState(
            market_id="KXBTC15M-26APR141315-30",
            asset="BTC",
            side="yes",
            strike_price=70000.0,
            mid_price_cents=None,  # None mid price
            time_to_expiry_seconds=600,
            orderbook=None,
        )
        
        # Should return 0.5 (50% default) instead of raising exception
        pi = computer.compute_market_implied_prob(contract)
        assert pi == 0.5
    
    def test_compute_edge_with_none_spot_price(self):
        """Test edge computation handles None spot price gracefully."""
        computer = UnifiedEdgeComputer()
        
        # Create SpotReference with None price
        none_spot_ref = SpotReference(
            asset="BTC",
            price_usd=None,  # None price
            timestamp=datetime.now(timezone.utc),
            source="CFB",
            is_rti_proxy=True,
        )
        
        contract = ContractState(
            market_id="KXBTC15M-26APR141315-30",
            asset="BTC",
            side="yes",
            strike_price=70000.0,
            mid_price_cents=50,
            time_to_expiry_seconds=600,
            orderbook=None,
        )
        
        # Should not raise an exception
        result = computer.compute_edge(
            asset="BTC",
            spot_ref=none_spot_ref,
            contract=contract,
            order_size=1,
            order_side="taker"
        )
        
        # Verify result is valid
        assert result is not None
        assert hasattr(result, 'edge_risk_adjusted')
        assert hasattr(result, 'edge_fee_adjusted')
        assert result.edge_risk_adjusted is not None
        assert result.edge_fee_adjusted is not None
    
    def test_compute_edge_with_zero_spot_price(self):
        """Test edge computation handles zero spot price gracefully."""
        computer = UnifiedEdgeComputer()
        
        # Create SpotReference with zero price
        zero_spot_ref = SpotReference(
            asset="BTC",
            price_usd=0.0,  # Zero price
            timestamp=datetime.now(timezone.utc),
            source="CFB",
            is_rti_proxy=True,
        )
        
        contract = ContractState(
            market_id="KXBTC15M-26APR141315-30",
            asset="BTC",
            side="yes",
            strike_price=70000.0,
            mid_price_cents=50,
            time_to_expiry_seconds=600,
            orderbook=None,
        )
        
        # Should not raise an exception
        result = computer.compute_edge(
            asset="BTC",
            spot_ref=zero_spot_ref,
            contract=contract,
            order_size=1,
            order_side="taker"
        )
        
        # Verify result is valid
        assert result is not None
        assert result.edge_risk_adjusted is not None
        assert result.edge_fee_adjusted is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
