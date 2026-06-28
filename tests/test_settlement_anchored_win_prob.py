"""
Unit tests for settlement-anchored model win probability.

Tests verify that compute_model_win_prob() behaves sensibly under RTI-style settlement:
- 60-second averages
- Gaussian approximation
- Proper handling of variance and time decay

Reference:
- Kalshi crypto settlement: https://help.kalshi.com/en/articles/13823838-crypto-markets
- CME CF benchmarks: https://www.cmegroup.com/articles/faqs/cme-cf-cryptocurrency-benchmarks-faq.html
"""
from __future__ import annotations

import math
import pytest
from unittest.mock import Mock, patch
from dataclasses import dataclass

from merid.prediction.unified_edge import UnifiedEdgeComputer, SpotReference, ContractState


class MockCalibration(dict):
    """Mock calibration data for testing."""
    def __init__(self, time_decay: float = 0.05):
        super().__init__()
        self["time_decay"] = time_decay


class TestSettlementAnchoredWinProb:
    """Test suite for settlement-anchored model win probability computation."""
    
    @pytest.fixture
    def unified_edge(self):
        """Create UnifiedEdgeComputer instance with mock calibration."""
        edge = UnifiedEdgeComputer()
        # Mock calibration to return deterministic values
        edge.calibration = Mock()
        edge.calibration.get_calibration = Mock(return_value=MockCalibration(time_decay=0.05))
        edge.calibration.get_volatility = Mock(return_value=0.02)  # 2% vol
        return edge
    
    @pytest.fixture
    def spot_ref(self, price_usd: float = 50000.0):
        """Create SpotReference with given price."""
        from datetime import datetime, timezone
        return SpotReference(
            asset="BTC",
            price_usd=price_usd,
            timestamp=datetime.now(timezone.utc),
            source="test",
        )
    
    @pytest.fixture
    def contract(self, strike_price: float = 50000.0, side: str = "yes", time_to_expiry_seconds: float = 900.0):
        """Create ContractState with given parameters."""
        return ContractState(
            market_id="KXBTC-15M-TEST",
            asset="BTC",
            side=side,
            strike_price=strike_price,
            mid_price_cents=50,  # 0.50 probability
            time_to_expiry_seconds=time_to_expiry_seconds,
            orderbook=None,
        )
    
    def test_symmetry_around_threshold(self, unified_edge, spot_ref, contract):
        """
        Test symmetry: when spot == threshold, win_prob ≈ 0.5.
        
        Given:
        - spot_price == threshold
        - moderate variance (std > 0)
        
        Expect:
        - win_prob ≈ 0.5 for both yes and no sides
        """
        # Mock settlement variance to return a moderate std
        with patch('merid.prediction.risk.settlement_risk_model.estimate_settlement_variance') as mock_variance:
            mock_variance.return_value = 100.0  # variance -> std = 10
            mock_variance.__name__ = 'estimate_settlement_variance'
            
            # Test YES side
            contract_yes = ContractState(
                market_id="KXBTC-15M-TEST",
                asset="BTC",
                side="yes",
                strike_price=contract.strike_price,
                mid_price_cents=contract.mid_price_cents,
                time_to_expiry_seconds=contract.time_to_expiry_seconds,
                orderbook=None,
            )
            prob_yes = unified_edge.compute_model_win_prob("BTC", spot_ref, contract_yes)
            
            # Test NO side
            contract_no = ContractState(
                market_id="KXBTC-15M-TEST",
                asset="BTC",
                side="no",
                strike_price=contract.strike_price,
                mid_price_cents=contract.mid_price_cents,
                time_to_expiry_seconds=contract.time_to_expiry_seconds,
                orderbook=None,
            )
            prob_no = unified_edge.compute_model_win_prob("BTC", spot_ref, contract_no)
            
            # Both should be approximately 0.5 (within tolerance for time decay)
            assert 0.45 <= prob_yes <= 0.55, f"YES prob {prob_yes} not near 0.5"
            assert 0.45 <= prob_no <= 0.55, f"NO prob {prob_no} not near 0.5"
            
            # YES + NO should sum to approximately 1.0
            assert 0.9 <= (prob_yes + prob_no) <= 1.1, f"YES+NO {prob_yes + prob_no} not near 1.0"
    
    def test_monotonicity_with_distance(self, unified_edge, contract):
        """
        Test monotonicity: win_prob increases with distance from threshold.
        
        Case A: spot_price = threshold + 1 * std
        Case B: spot_price = threshold + 2 * std
        
        Expect:
        - win_prob(B) > win_prob(A)
        - Both > 0.5 for YES side
        """
        from datetime import datetime, timezone
        with patch('merid.prediction.risk.settlement_risk_model.estimate_settlement_variance') as mock_variance:
            mock_variance.return_value = 100.0  # variance -> std = 10
            mock_variance.__name__ = 'estimate_settlement_variance'
            
            std = 10.0
            
            # Case A: spot = threshold + 1 * std
            spot_ref_a = SpotReference(asset="BTC", price_usd=50000.0 + std, timestamp=datetime.now(timezone.utc), source="test")
            prob_a = unified_edge.compute_model_win_prob("BTC", spot_ref_a, contract)
            
            # Case B: spot = threshold + 2 * std
            spot_ref_b = SpotReference(asset="BTC", price_usd=50000.0 + 2 * std, timestamp=datetime.now(timezone.utc), source="test")
            prob_b = unified_edge.compute_model_win_prob("BTC", spot_ref_b, contract)
            
            # Monotonicity: prob_b > prob_a
            assert prob_b > prob_a, f"prob_b {prob_b} should be > prob_a {prob_a}"
            
            # Both > 0.5 for YES side
            assert prob_a > 0.5, f"prob_a {prob_a} should be > 0.5"
            assert prob_b > 0.5, f"prob_b {prob_b} should be > 0.5"
    
    def test_tail_behavior_upper(self, unified_edge, contract):
        """
        Test tail behavior: spot >= threshold + 4 * std -> win_prob very close to 1.
        
        Expect:
        - win_prob very close to 1 but < 1
        """
        from datetime import datetime, timezone
        with patch('merid.prediction.risk.settlement_risk_model.estimate_settlement_variance') as mock_variance:
            mock_variance.return_value = 100.0  # variance -> std = 10
            mock_variance.__name__ = 'estimate_settlement_variance'
            
            std = 10.0
            
            # spot = threshold + 4 * std
            spot_ref = SpotReference(asset="BTC", price_usd=50000.0 + 4 * std, timestamp=datetime.now(timezone.utc), source="test")
            prob = unified_edge.compute_model_win_prob("BTC", spot_ref, contract)
            
            # Very close to 1 but < 1
            assert 0.95 <= prob < 1.0, f"prob {prob} should be close to 1"
    
    def test_tail_behavior_lower(self, unified_edge, contract):
        """
        Test tail behavior: spot <= threshold - 4 * std -> win_prob very close to 0.
        
        Expect:
        - win_prob very close to 0 but > 0
        """
        from datetime import datetime, timezone
        with patch('merid.prediction.risk.settlement_risk_model.estimate_settlement_variance') as mock_variance:
            mock_variance.return_value = 100.0  # variance -> std = 10
            mock_variance.__name__ = 'estimate_settlement_variance'
            
            std = 10.0
            
            # spot = threshold - 4 * std
            spot_ref = SpotReference(asset="BTC", price_usd=50000.0 - 4 * std, timestamp=datetime.now(timezone.utc), source="test")
            prob = unified_edge.compute_model_win_prob("BTC", spot_ref, contract)
            
            # Very close to 0 but > 0
            assert 0.0 < prob <= 0.05, f"prob {prob} should be close to 0"
    
    def test_time_to_expiry_behavior(self, unified_edge, contract):
        """
        Test time-to-expiry behavior: vary time_to_expiry while holding spot and variance fixed.
        
        Expect:
        - No sign flips
        - No non-finite values
        - Probability remains in [0, 1]
        """
        from datetime import datetime, timezone
        with patch('merid.prediction.risk.settlement_risk_model.estimate_settlement_variance') as mock_variance:
            mock_variance.return_value = 100.0  # variance -> std = 10
            mock_variance.__name__ = 'estimate_settlement_variance'
            
            # Fixed spot above threshold
            spot_ref = SpotReference(asset="BTC", price_usd=50100.0, timestamp=datetime.now(timezone.utc), source="test")
            
            # Test different time-to-expiry values
            time_to_expiries = [900.0, 600.0, 300.0, 60.0, 10.0]
            probs = []
            
            for tte in time_to_expiries:
                contract_tte = ContractState(
                    market_id="KXBTC-15M-TEST",
                    asset="BTC",
                    strike_price=50000.0,
                    side="yes",
                    mid_price_cents=50,
                    time_to_expiry_seconds=tte,
                    orderbook=None,
                )
                prob = unified_edge.compute_model_win_prob("BTC", spot_ref, contract_tte)
                probs.append(prob)
                
                # Check finite
                assert math.isfinite(prob), f"prob {prob} not finite for tte={tte}"
                
                # Check in [0, 1]
                assert 0.0 <= prob <= 1.0, f"prob {prob} not in [0, 1] for tte={tte}"
            
            # Check no sign flips (all probabilities should have same sign relative to 0.5)
            # Since spot > threshold, all should be > 0.5
            for prob in probs:
                assert prob > 0.5, f"prob {prob} should be > 0.5 (spot above threshold)"
    
    def test_binary_contract_mapping(self, unified_edge, contract):
        """
        Test binary contract mapping: spot -> P(settlement > threshold).
        
        For binary YES contracts:
        - Ensure mapping from spot to P(settlement > threshold) is correct
        """
        from datetime import datetime, timezone
        with patch('merid.prediction.risk.settlement_risk_model.estimate_settlement_variance') as mock_variance:
            mock_variance.return_value = 100.0  # variance -> std = 10
            mock_variance.__name__ = 'estimate_settlement_variance'
            
            # Test mapping: higher spot -> higher win probability for YES
            spot_prices = [49900.0, 49950.0, 50000.0, 50050.0, 50100.0]
            probs = []
            
            for spot_price in spot_prices:
                spot_ref = SpotReference(asset="BTC", price_usd=spot_price, timestamp=datetime.now(timezone.utc), source="test")
                prob = unified_edge.compute_model_win_prob("BTC", spot_ref, contract)
                probs.append(prob)
            
            # Check monotonicity: probabilities should increase with spot price
            for i in range(len(probs) - 1):
                assert probs[i] <= probs[i + 1], f"probs not monotonic: {probs}"
    
    def test_no_variance_deterministic(self, unified_edge, spot_ref, contract):
        """
        Test behavior when settlement variance is zero (deterministic case).
        
        When std = 0:
        - YES wins if spot > strike
        - NO wins if spot < strike
        - At equality, depends on side
        """
        from datetime import datetime, timezone
        with patch('merid.prediction.risk.settlement_risk_model.estimate_settlement_variance') as mock_variance:
            mock_variance.return_value = 0.0  # zero variance
            mock_variance.__name__ = 'estimate_settlement_variance'
            
            # YES side: spot > strike -> prob = 1.0
            spot_ref_above = SpotReference(asset="BTC", price_usd=50100.0, timestamp=datetime.now(timezone.utc), source="test")
            prob_yes_above = unified_edge.compute_model_win_prob("BTC", spot_ref_above, contract)
            assert prob_yes_above == 1.0, f"YES above threshold should be 1.0, got {prob_yes_above}"
            
            # YES side: spot < strike -> prob = 0.0
            spot_ref_below = SpotReference(asset="BTC", price_usd=49900.0, timestamp=datetime.now(timezone.utc), source="test")
            prob_yes_below = unified_edge.compute_model_win_prob("BTC", spot_ref_below, contract)
            assert prob_yes_below == 0.0, f"YES below threshold should be 0.0, got {prob_yes_below}"
            
            # NO side: spot < strike -> prob = 1.0
            contract_no = ContractState(
                market_id="KXBTC-15M-TEST",
                asset="BTC",
                side="no",
                strike_price=contract.strike_price,
                mid_price_cents=contract.mid_price_cents,
                time_to_expiry_seconds=contract.time_to_expiry_seconds,
                orderbook=None,
            )
            prob_no_below = unified_edge.compute_model_win_prob("BTC", spot_ref_below, contract_no)
            assert prob_no_below == 1.0, f"NO below threshold should be 1.0, got {prob_no_below}"
    
    def test_no_side_vs_yes_side_complementarity(self, unified_edge, spot_ref):
        """
        Test that YES and NO sides are complementary (sum to ~1.0).
        
        For binary contracts:
        - P(YES) + P(NO) ≈ 1.0
        """
        from datetime import datetime, timezone
        with patch('merid.prediction.risk.settlement_risk_model.estimate_settlement_variance') as mock_variance:
            mock_variance.return_value = 100.0  # variance -> std = 10
            mock_variance.__name__ = 'estimate_settlement_variance'
            
            contract_yes = ContractState(
                market_id="KXBTC-15M-TEST",
                asset="BTC",
                strike_price=50000.0,
                side="yes",
                mid_price_cents=50,
                time_to_expiry_seconds=900.0,
                orderbook=None,
            )
            
            contract_no = ContractState(
                market_id="KXBTC-15M-TEST",
                asset="BTC",
                strike_price=50000.0,
                side="no",
                mid_price_cents=50,
                time_to_expiry_seconds=900.0,
                orderbook=None,
            )
            
            # Test at different spot prices
            spot_prices = [49900.0, 49950.0, 50000.0, 50050.0, 50100.0]
            
            for spot_price in spot_prices:
                spot_ref = SpotReference(asset="BTC", price_usd=spot_price, timestamp=datetime.now(timezone.utc), source="test")
                prob_yes = unified_edge.compute_model_win_prob("BTC", spot_ref, contract_yes)
                prob_no = unified_edge.compute_model_win_prob("BTC", spot_ref, contract_no)
                
                # Should sum to approximately 1.0 (allowing for time decay effects)
                assert 0.9 <= (prob_yes + prob_no) <= 1.1, \
                    f"YES+NO sum {prob_yes + prob_no} not near 1.0 for spot={spot_price}"
    
    def test_variance_sensitivity(self, unified_edge, contract):
        """
        Test sensitivity to settlement variance.
        
        Higher variance should:
        - Pull probabilities toward 0.5 (more uncertainty)
        - Reduce extreme probabilities
        """
        from datetime import datetime, timezone
        spot_ref = SpotReference(asset="BTC", price_usd=50100.0, timestamp=datetime.now(timezone.utc), source="test")
        
        # Test with different variance levels
        variances = [25.0, 100.0, 400.0]  # std: 5, 10, 20
        probs = []
        
        for variance in variances:
            with patch('merid.prediction.risk.settlement_risk_model.estimate_settlement_variance') as mock_variance:
                mock_variance.return_value = variance
                mock_variance.__name__ = 'estimate_settlement_variance'
                
                prob = unified_edge.compute_model_win_prob("BTC", spot_ref, contract)
                probs.append(prob)
        
        # Higher variance should pull probability toward 0.5
        # Since spot > threshold, higher variance should reduce probability
        assert probs[0] >= probs[1] >= probs[2], \
            f"Higher variance should reduce prob (spot > threshold): {probs}"
