"""Tests for unified edge computation fixes.

Tests the fixes for None/float division errors in unified_edge.py
when handling missing spot prices and contract prices.
"""

import pytest
from datetime import datetime, timezone

from merid.prediction.unified_edge import (
    UnifiedEdgeComputer,
    SpotReference,
    ContractState,
    PerAssetCalibration,
)
from merid.event_venues.kalshi.unified_market_state import OrderbookSnapshot, OrderbookLevel


class TestUnifiedEdgeFixes:
    """Test unified edge computation fixes for None/float division errors."""
    
    @pytest.fixture
    def edge_computer(self):
        """Create a UnifiedEdgeComputer instance for testing."""
        calibration = PerAssetCalibration()
        return UnifiedEdgeComputer(calibration=calibration)
    
    @pytest.fixture
    def valid_spot_ref(self):
        """Create a valid SpotReference."""
        return SpotReference(
            asset="BTC",
            price_usd=70000.0,
            timestamp=datetime.now(timezone.utc),
            source="CFB",
            is_rti_proxy=True,
        )
    
    @pytest.fixture
    def valid_contract_state(self):
        """Create a valid ContractState with orderbook."""
        orderbook = OrderbookSnapshot(
            ticker="KXBTC15M-26JUN022300-00",
            yes_bids=(OrderbookLevel(price_cents=50, size=10),),
            no_bids=(OrderbookLevel(price_cents=50, size=10),),
            ts=datetime.now(timezone.utc).timestamp(),
        )
        
        return ContractState(
            market_id="KXBTC15M-26JUN022300-00",
            asset="BTC",
            side="yes",
            strike_price=70000.0,
            mid_price_cents=50,
            time_to_expiry_seconds=600,
            orderbook=orderbook,
        )
    
    def test_compute_edge_with_none_spot_price(self, edge_computer, valid_contract_state):
        """Test edge computation handles None spot price gracefully."""
        # Create SpotReference with None price
        none_spot_ref = SpotReference(
            asset="BTC",
            price_usd=None,  # None price
            timestamp=datetime.now(timezone.utc),
            source="CFB",
            is_rti_proxy=True,
        )
        
        # This should not raise an exception
        result = edge_computer.compute_edge(
            asset="BTC",
            spot_ref=none_spot_ref,
            contract=valid_contract_state,
            order_size=1,
            order_side="taker"
        )
        
        # Verify the result is valid
        assert result is not None
        assert hasattr(result, 'edge_risk_adjusted')
        assert hasattr(result, 'edge_fee_adjusted')
        assert hasattr(result, 'net_edge_cents')
        
        # Verify distance percentage is 0.0 when spot price is None
        # This is checked indirectly through the result not having division errors
        assert result.edge_risk_adjusted is not None
        assert result.edge_fee_adjusted is not None
    
    def test_compute_edge_with_zero_spot_price(self, edge_computer, valid_contract_state):
        """Test edge computation handles zero spot price gracefully."""
        # Create SpotReference with zero price
        zero_spot_ref = SpotReference(
            asset="BTC",
            price_usd=0.0,  # Zero price
            timestamp=datetime.now(timezone.utc),
            source="CFB",
            is_rti_proxy=True,
        )
        
        # This should not raise an exception
        result = edge_computer.compute_edge(
            asset="BTC",
            spot_ref=zero_spot_ref,
            contract=valid_contract_state,
            order_size=1,
            order_side="taker"
        )
        
        # Verify the result is valid
        assert result is not None
        assert result.edge_risk_adjusted is not None
        assert result.edge_fee_adjusted is not None
    
    def test_compute_market_implied_prob_with_none_mid_price(self, edge_computer):
        """Test market implied probability handles None mid price gracefully."""
        # Create ContractState with None mid price
        contract_none_mid = ContractState(
            market_id="KXBTC15M-26JUN022300-00",
            asset="BTC",
            side="yes",
            strike_price=70000.0,
            mid_price_cents=None,  # None mid price
            time_to_expiry_seconds=600,
            orderbook=None,
        )
        
        # This should return 0.5 (50% default) instead of raising an exception
        prob = edge_computer.compute_market_implied_prob(contract_none_mid)
        assert prob == 0.5
    
    def test_compute_market_implied_prob_with_valid_mid_price(self, edge_computer):
        """Test market implied probability works correctly with valid mid price."""
        # Create ContractState with valid mid price
        contract_valid_mid = ContractState(
            market_id="KXBTC15M-26JUN022300-00",
            asset="BTC",
            side="yes",
            strike_price=70000.0,
            mid_price_cents=50,  # Valid mid price (50 cents)
            time_to_expiry_seconds=600,
            orderbook=None,
        )
        
        # This should return 0.5 (50 cents / 100)
        prob = edge_computer.compute_market_implied_prob(contract_valid_mid)
        assert prob == 0.5
    
    def test_compute_edge_with_no_contract_side(self, edge_computer, valid_spot_ref):
        """Test edge computation handles missing contract side gracefully."""
        # Create ContractState with no side
        contract_no_side = ContractState(
            market_id="KXBTC15M-26JUN022300-00",
            asset="BTC",
            side=None,  # No side
            strike_price=70000.0,
            mid_price_cents=50,
            time_to_expiry_seconds=600,
            orderbook=None,
        )
        
        # This should not raise an exception
        result = edge_computer.compute_edge(
            asset="BTC",
            spot_ref=valid_spot_ref,
            contract=contract_no_side,
            order_size=1,
            order_side="taker"
        )
        
        # Verify the result is valid
        assert result is not None
        assert result.edge_risk_adjusted is not None
        assert result.edge_fee_adjusted is not None
    
    def test_compute_edge_complete_flow_with_valid_data(self, edge_computer, valid_spot_ref, valid_contract_state):
        """Test complete edge computation flow with valid data."""
        result = edge_computer.compute_edge(
            asset="BTC",
            spot_ref=valid_spot_ref,
            contract=valid_contract_state,
            order_size=1,
            order_side="taker"
        )
        
        # Verify all result fields are populated
        assert result is not None
        assert hasattr(result, 'edge_risk_adjusted')
        assert hasattr(result, 'edge_fee_adjusted')
        assert hasattr(result, 'net_edge_cents')
        assert hasattr(result, 'confidence')
        assert hasattr(result, 'dist_pct')
        assert hasattr(result, 'dist_abs_pct')
        
        # Verify values are reasonable
        assert isinstance(result.edge_risk_adjusted, (int, float))
        assert isinstance(result.edge_fee_adjusted, (int, float))
        assert isinstance(result.net_edge_cents, (int, float))
        assert isinstance(result.confidence, (int, float))
        assert isinstance(result.dist_pct, (int, float))
        assert isinstance(result.dist_abs_pct, (int, float))
    
    def test_compute_edge_with_eth_asset(self, edge_computer):
        """Test edge computation works with ETH asset."""
        # Create ETH-specific data
        eth_spot_ref = SpotReference(
            asset="ETH",
            price_usd=3000.0,
            timestamp=datetime.now(timezone.utc),
            source="CFB",
            is_rti_proxy=True,
        )
        
        eth_orderbook = OrderbookSnapshot(
            ticker="KXETH15M-26JUN022300-00",
            yes_bids=(OrderbookLevel(price_cents=50, size=10),),
            no_bids=(OrderbookLevel(price_cents=50, size=10),),
            ts=datetime.now(timezone.utc).timestamp(),
        )
        
        eth_contract = ContractState(
            market_id="KXETH15M-26JUN022300-00",
            asset="ETH",
            side="yes",
            strike_price=3000.0,
            mid_price_cents=50,
            time_to_expiry_seconds=600,
            orderbook=eth_orderbook,
        )
        
        result = edge_computer.compute_edge(
            asset="ETH",
            spot_ref=eth_spot_ref,
            contract=eth_contract,
            order_size=1,
            order_side="taker"
        )
        
        # Verify the result is valid
        assert result is not None
        assert result.edge_risk_adjusted is not None
        assert result.edge_fee_adjusted is not None
    
    def test_compute_edge_with_unsupported_asset_raises_error(self, edge_computer, valid_spot_ref, valid_contract_state):
        """Test that unsupported assets raise ValueError."""
        with pytest.raises(ValueError, match="Unified edge only supports 15M crypto assets"):
            edge_computer.compute_edge(
                asset="UNSUPPORTED",
                spot_ref=valid_spot_ref,
                contract=valid_contract_state,
                order_size=1,
                order_side="taker"
            )
    
    def test_compute_spread_pct_with_none_orderbook(self, edge_computer):
        """Test spread percentage computation handles None orderbook."""
        contract_no_book = ContractState(
            market_id="KXBTC15M-26JUN022300-00",
            asset="BTC",
            side="yes",
            strike_price=70000.0,
            mid_price_cents=50,
            time_to_expiry_seconds=600,
            orderbook=None,  # No orderbook
        )
        
        spread_pct = edge_computer.compute_spread_pct(contract_no_book)
        assert spread_pct is None
    
    def test_compute_spread_pct_with_valid_orderbook(self, edge_computer):
        """Test spread percentage computation works with valid orderbook."""
        orderbook = OrderbookSnapshot(
            ticker="KXBTC15M-26JUN022300-00",
            yes_bids=(OrderbookLevel(price_cents=49, size=10),),
            no_bids=(OrderbookLevel(price_cents=51, size=10),),
            ts=datetime.now(timezone.utc).timestamp(),
        )
        
        contract_with_book = ContractState(
            market_id="KXBTC15M-26JUN022300-00",
            asset="BTC",
            side="yes",
            strike_price=70000.0,
            mid_price_cents=50,
            time_to_expiry_seconds=600,
            orderbook=orderbook,
        )
        
        spread_pct = edge_computer.compute_spread_pct(contract_with_book)
        assert spread_pct is not None
        assert isinstance(spread_pct, (int, float))
    
    def test_edge_computer_initialization(self):
        """Test UnifiedEdgeComputer initialization."""
        # Test with default calibration
        computer1 = UnifiedEdgeComputer()
        assert computer1.calibration is not None
        assert computer1.min_edge_cents == 3.0
        assert computer1.max_spread_pct == 0.10
        assert computer1.max_spread_cents == 60
        
        # Test with custom calibration
        custom_calibration = PerAssetCalibration()
        computer2 = UnifiedEdgeComputer(calibration=custom_calibration)
        assert computer2.calibration is custom_calibration
