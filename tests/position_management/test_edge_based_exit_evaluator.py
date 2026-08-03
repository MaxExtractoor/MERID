"""
Tests for Edge-Based Exit Evaluator
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from dataclasses import dataclass

from merid.position_management.edge_based_exit_evaluator import EdgeBasedExitEvaluator


@dataclass
class MockPosition:
    """Mock position for testing."""
    position_id: str = "test_position"
    market_id: str = "KXBTC15M"
    series_ticker: str = "KXBTC15M"
    avg_entry_price_cents: int = 50
    side: str = "yes"


@dataclass
class MockEdgeResult:
    """Mock edge result."""
    edge_pct: float = 0.05
    edge: float = 0.05
    edge_fee_adjusted: float = 0.05
    confidence: float = 0.8
    net_edge_cents: float = 5.0


@dataclass
class MockSpotData:
    """Mock spot data."""
    price: float = 50000.0
    price_usd: float = 50000.0
    source: str = "unified_spot_service"


class TestEdgeBasedExitEvaluator:
    """Tests for EdgeBasedExitEvaluator."""
    
    @pytest.fixture
    def evaluator(self):
        """Create an evaluator."""
        return EdgeBasedExitEvaluator()
    
    @pytest.fixture
    def mock_position(self):
        """Create a mock position."""
        return MockPosition()
    
    def test_compute_current_edge_success(self, evaluator, mock_position):
        """Test successful edge computation."""
        # Mock the internal dependencies
        mock_edge_computer = Mock()
        mock_edge_result = MockEdgeResult(edge_pct=0.05)
        mock_edge_computer.compute_edge.return_value = mock_edge_result
        evaluator._edge_computer = mock_edge_computer
        
        mock_spot_service = Mock()
        mock_spot_data = MockSpotData(price=50000.0)
        mock_spot_service.get_spot_data.return_value = mock_spot_data
        evaluator._spot_service = mock_spot_service
        
        # Compute edge
        edge_pct = evaluator.compute_current_edge(
            position=mock_position,
            current_price_cents=50,
            time_to_expiry_seconds=600,
        )
        
        assert edge_pct == 0.05
        mock_spot_service.get_spot_data.assert_called_once_with("BTC")
        mock_edge_computer.compute_edge.assert_called_once()
    
    def test_compute_current_edge_no_spot_data(self, evaluator, mock_position):
        """Test when no spot data available."""
        mock_edge_computer = Mock()
        evaluator._edge_computer = mock_edge_computer
        
        mock_spot_service = Mock()
        mock_spot_service.get_spot_data.return_value = None
        evaluator._spot_service = mock_spot_service
        
        edge_pct = evaluator.compute_current_edge(
            position=mock_position,
            current_price_cents=50,
            time_to_expiry_seconds=600,
        )
        
        assert edge_pct is None
    
    def test_compute_current_edge_edge_computation_fails(self, evaluator, mock_position):
        """Test when edge computation fails."""
        mock_edge_computer = Mock()
        mock_edge_computer.compute_edge.return_value = None
        evaluator._edge_computer = mock_edge_computer
        
        mock_spot_service = Mock()
        mock_spot_data = MockSpotData(price=50000.0)
        mock_spot_service.get_spot_data.return_value = mock_spot_data
        evaluator._spot_service = mock_spot_service
        
        edge_pct = evaluator.compute_current_edge(
            position=mock_position,
            current_price_cents=50,
            time_to_expiry_seconds=600,
        )
        
        assert edge_pct is None
    
    def test_extract_asset_from_market_id(self, evaluator):
        """Test extracting asset from market_id."""
        pos = MockPosition(market_id="KXETH15M")
        assert evaluator._extract_asset(pos) == "ETH"
        
        pos = MockPosition(market_id="KXSOL15M")
        assert evaluator._extract_asset(pos) == "SOL"
        
        pos = MockPosition(market_id="KXXRP15M")
        assert evaluator._extract_asset(pos) == "XRP"
        
        pos = MockPosition(market_id="KXDOGE15M")
        assert evaluator._extract_asset(pos) == "DOGE"
    
    def test_extract_asset_from_series_ticker(self, evaluator):
        """Test extracting asset from series_ticker."""
        pos = MockPosition(market_id="", series_ticker="KXETH15M")
        assert evaluator._extract_asset(pos) == "ETH"
    
    def test_extract_asset_not_found(self, evaluator):
        """Test when asset cannot be extracted."""
        pos = MockPosition(market_id="INVALID", series_ticker="INVALID")
        assert evaluator._extract_asset(pos) is None
    
    def test_extract_entry_price(self, evaluator):
        """Test extracting entry price."""
        pos = MockPosition(avg_entry_price_cents=50)
        assert evaluator._extract_entry_price(pos) == 50
    
    def test_extract_entry_price_not_found(self, evaluator):
        """Test when entry price cannot be extracted."""
        pos = Mock()
        delattr(pos, 'avg_entry_price_cents')
        assert evaluator._extract_entry_price(pos) is None
    
    def test_compute_current_edge_exception_handling(self, evaluator, mock_position):
        """Test exception handling during edge computation."""
        # Force an exception by setting edge_computer to raise
        mock_edge_computer = Mock()
        mock_edge_computer.compute_edge.side_effect = Exception("Edge computer failed")
        evaluator._edge_computer = mock_edge_computer
        
        edge_pct = evaluator.compute_current_edge(
            position=mock_position,
            current_price_cents=50,
            time_to_expiry_seconds=600,
        )
        
        assert edge_pct is None
