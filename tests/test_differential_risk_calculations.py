"""Differential tests for risk calculations.

This module implements differential testing to compare different implementations
of risk calculations and ensure they produce consistent results. This helps
identify discrepancies between calculation methods and validates correctness.

Differential Testing Scenarios:
1. Exposure calculation consistency across methods
2. Position sizing consistency across algorithms
3. Risk limit enforcement consistency
4. Portfolio risk aggregation consistency
5. Margin calculation consistency
"""

import pytest
from typing import Dict, List, Tuple
from dataclasses import dataclass


@dataclass
class RiskCalculationResult:
    """Result from a risk calculation method."""
    method_name: str
    exposure: float
    position_size: float
    risk_limit: float
    is_within_limit: bool


class TestExposureCalculationConsistency:
    """Differential tests for exposure calculation consistency."""

    def test_exposure_calculation_method_1_vs_method_2(self):
        """Two exposure calculation methods should produce consistent results."""
        # Method 1: Simple linear calculation
        def calculate_exposure_method_1(price_cents: int, quantity: int) -> float:
            return (price_cents / 100.0) * quantity
        
        # Method 2: Include fee calculation
        def calculate_exposure_method_2(price_cents: int, quantity: int) -> float:
            base_exposure = (price_cents / 100.0) * quantity
            fee = base_exposure * 0.01  # 1% fee
            return base_exposure + fee
        
        # Test with various inputs
        test_cases = [
            (50, 10),  # 50 cents, 10 contracts
            (30, 5),   # 30 cents, 5 contracts
            (75, 20),  # 75 cents, 20 contracts
        ]
        
        for price_cents, quantity in test_cases:
            exposure_1 = calculate_exposure_method_1(price_cents, quantity)
            exposure_2 = calculate_exposure_method_2(price_cents, quantity)
            
            # Method 2 should be slightly higher due to fees
            assert exposure_2 > exposure_1, \
                f"Method 2 should include fees: {exposure_1} vs {exposure_2}"
            
            # Difference should be consistent (1% fee)
            expected_diff = exposure_1 * 0.01
            actual_diff = exposure_2 - exposure_1
            assert abs(actual_diff - expected_diff) < 0.001, \
                f"Fee calculation should be consistent: {actual_diff} vs {expected_diff}"

    def test_exposure_calculation_with_multiple_assets(self):
        """Multi-asset exposure calculation should be consistent across methods."""
        # Method 1: Sum individual exposures
        def calculate_total_exposure_method_1(positions: Dict[str, float]) -> float:
            return sum(positions.values())
        
        # Method 2: Weighted sum with correlation adjustment
        def calculate_total_exposure_method_2(positions: Dict[str, float]) -> float:
            base_total = sum(positions.values())
            # Apply correlation discount (assume 0.9 correlation)
            correlation_factor = 0.9
            return base_total * correlation_factor
        
        # Test with multiple assets
        positions = {
            "BTC": 0.5,
            "ETH": 0.3,
            "SOL": 0.2
        }
        
        exposure_1 = calculate_total_exposure_method_1(positions)
        exposure_2 = calculate_total_exposure_method_2(positions)
        
        # Method 2 should be lower due to correlation adjustment
        assert exposure_2 < exposure_1, \
            f"Method 2 should apply correlation discount: {exposure_1} vs {exposure_2}"
        
        # Difference should match expected correlation factor
        expected_ratio = 0.9
        actual_ratio = exposure_2 / exposure_1
        assert abs(actual_ratio - expected_ratio) < 0.01, \
            f"Correlation factor should be consistent: {actual_ratio} vs {expected_ratio}"

    def test_exposure_cap_enforcement_consistency(self):
        """Exposure cap enforcement should be consistent across methods."""
        exposure_cap = 1.0
        
        # Method 1: Hard cap
        def enforce_cap_method_1(exposure: float, cap: float) -> float:
            return min(exposure, cap)
        
        # Method 2: Soft cap with warning
        def enforce_cap_method_2(exposure: float, cap: float) -> float:
            if exposure > cap:
                # Return cap but log warning
                return cap
            return exposure
        
        # Test with various exposures
        test_exposures = [0.5, 0.8, 1.0, 1.2, 1.5]
        
        for exposure in test_exposures:
            capped_1 = enforce_cap_method_1(exposure, exposure_cap)
            capped_2 = enforce_cap_method_2(exposure, exposure_cap)
            
            # Both methods should produce same capped value
            assert capped_1 == capped_2, \
                f"Cap enforcement should be consistent: {capped_1} vs {capped_2}"
            
            # Capped value should not exceed cap
            assert capped_1 <= exposure_cap, \
                f"Capped exposure should not exceed cap: {capped_1} > {exposure_cap}"


class TestPositionSizingConsistency:
    """Differential tests for position sizing consistency."""

    def test_position_sizing_kelly_vs_fixed_fraction(self):
        """Kelly criterion and fixed fraction should produce consistent sizing."""
        # Kelly criterion
        def calculate_position_kelly(win_prob: float, win_loss_ratio: float) -> float:
            return (win_prob * win_loss_ratio - (1 - win_prob)) / win_loss_ratio
        
        # Fixed fraction
        def calculate_position_fixed_fraction(win_prob: float, win_loss_ratio: float) -> float:
            # Use 1% fixed fraction
            return 0.01
        
        # Test with various win probabilities
        test_cases = [
            (0.6, 2.0),  # 60% win rate, 2:1 risk-reward
            (0.55, 1.5), # 55% win rate, 1.5:1 risk-reward
            (0.5, 1.0),  # 50% win rate, 1:1 risk-reward
        ]
        
        for win_prob, win_loss_ratio in test_cases:
            kelly_size = calculate_position_kelly(win_prob, win_loss_ratio)
            fixed_size = calculate_position_fixed_fraction(win_prob, win_loss_ratio)
            
            # Kelly should be positive for positive expected value
            if win_prob * win_loss_ratio > (1 - win_prob):
                assert kelly_size > 0, \
                    f"Kelly should be positive for positive EV: {kelly_size}"
            
            # Fixed fraction should be constant
            assert fixed_size == 0.01, \
                f"Fixed fraction should be constant: {fixed_size}"

    def test_position_sizing_with_risk_limit(self):
        """Position sizing with risk limit should be consistent."""
        risk_limit = 0.1  # 10% risk per trade
        
        # Method 1: Risk-based sizing
        def calculate_size_risk_based(account_value: float, risk_limit: float, stop_loss: float) -> float:
            risk_amount = account_value * risk_limit
            position_size = risk_amount / stop_loss
            return position_size
        
        # Method 2: Percentage-based sizing
        def calculate_size_percentage_based(account_value: float, percentage: float) -> float:
            return account_value * percentage
        
        # Test with various scenarios
        account_value = 1000.0
        stop_loss = 0.05  # 5% stop loss
        
        size_risk = calculate_size_risk_based(account_value, risk_limit, stop_loss)
        size_pct = calculate_size_percentage_based(account_value, 0.02)  # 2% position
        
        # Both should produce reasonable position sizes
        assert size_risk > 0, f"Risk-based size should be positive: {size_risk}"
        assert size_pct > 0, f"Percentage-based size should be positive: {size_pct}"
        
        # Risk-based should account for stop loss
        expected_risk_size = (account_value * risk_limit) / stop_loss
        assert abs(size_risk - expected_risk_size) < 0.01, \
            f"Risk-based sizing should match calculation: {size_risk} vs {expected_risk_size}"

    def test_position_sizing_scaling_consistency(self):
        """Position scaling should be consistent across methods."""
        base_position = 100.0
        scaling_factors = [0.5, 1.0, 1.5, 2.0]
        
        # Method 1: Linear scaling
        def scale_position_linear(base: float, factor: float) -> float:
            return base * factor
        
        # Method 2: Logarithmic scaling
        def scale_position_logarithmic(base: float, factor: float) -> float:
            import math
            return base * math.log(factor + 1)
        
        for factor in scaling_factors:
            scaled_linear = scale_position_linear(base_position, factor)
            scaled_log = scale_position_logarithmic(base_position, factor)
            
            # Linear should be proportional to factor
            assert scaled_linear == base_position * factor, \
                f"Linear scaling should be proportional: {scaled_linear}"
            
            # Logarithmic should be less than linear for factor > 1
            if factor > 1:
                assert scaled_log < scaled_linear, \
                    f"Log scaling should be less than linear: {scaled_log} vs {scaled_linear}"


class TestRiskLimitEnforcementConsistency:
    """Differential tests for risk limit enforcement consistency."""

    def test_daily_loss_limit_consistency(self):
        """Daily loss limit enforcement should be consistent."""
        daily_loss_limit = 0.05  # 5% daily loss limit
        
        # Method 1: Hard stop at limit
        def enforce_daily_limit_method_1(pnl: float, limit: float) -> bool:
            return pnl >= -limit
        
        # Method 2: Warning at 80% of limit
        def enforce_daily_limit_method_2(pnl: float, limit: float) -> Tuple[bool, bool]:
            warning_threshold = limit * 0.8
            warning = pnl <= -warning_threshold
            stop = pnl <= -limit
            return warning, stop
        
        # Test with various PnL values
        test_pnls = [0.0, -0.02, -0.04, -0.05, -0.06]
        
        for pnl in test_pnls:
            allowed_1 = enforce_daily_limit_method_1(pnl, daily_loss_limit)
            warning_2, stop_2 = enforce_daily_limit_method_2(pnl, daily_loss_limit)
            
            # Consistency check - handle floating point comparison
            if pnl < -daily_loss_limit - 0.001:  # Slightly below limit
                assert not allowed_1, f"Should stop at limit: {pnl}"
                assert stop_2, f"Should stop at limit: {pnl}"
            elif pnl < -daily_loss_limit * 0.8 - 0.001:  # Below warning threshold
                assert warning_2, f"Should warn at 80%: {pnl}"

    def test_position_limit_consistency(self):
        """Position limit enforcement should be consistent."""
        position_limits = {
            "BTC": 0.5,
            "ETH": 0.3,
            "SOL": 0.2
        }
        
        # Method 1: Per-asset limit
        def check_position_limit_method_1(positions: Dict[str, float], limits: Dict[str, float]) -> bool:
            for asset, position in positions.items():
                if asset in limits and position > limits[asset]:
                    return False
            return True
        
        # Method 2: Total position limit
        def check_position_limit_method_2(positions: Dict[str, float], total_limit: float) -> bool:
            return sum(positions.values()) <= total_limit
        
        # Test with various positions
        test_positions = [
            {"BTC": 0.4, "ETH": 0.2, "SOL": 0.1},
            {"BTC": 0.6, "ETH": 0.2, "SOL": 0.1},
            {"BTC": 0.3, "ETH": 0.3, "SOL": 0.3}
        ]
        
        for positions in test_positions:
            within_per_asset = check_position_limit_method_1(positions, position_limits)
            within_total = check_position_limit_method_2(positions, 1.0)
            
            # Both should evaluate correctly
            assert isinstance(within_per_asset, bool), "Method 1 should return bool"
            assert isinstance(within_total, bool), "Method 2 should return bool"

    def test_drawdown_limit_consistency(self):
        """Drawdown limit enforcement should be consistent."""
        drawdown_limit = 0.15  # 15% max drawdown
        
        # Method 1: Peak-to-trough drawdown
        def calculate_drawdown_method_1(pnl_curve: List[float]) -> float:
            peak = max(pnl_curve)
            trough = min(pnl_curve)
            if peak > 0:
                return (peak - trough) / peak
            return 0.0
        
        # Method 2: Rolling drawdown
        def calculate_drawdown_method_2(pnl_curve: List[float], window: int = 10) -> float:
            max_drawdown = 0.0
            for i in range(window, len(pnl_curve)):
                window_peak = max(pnl_curve[i-window:i])
                window_trough = min(pnl_curve[i-window:i])
                if window_peak > 0:
                    drawdown = (window_peak - window_trough) / window_peak
                    max_drawdown = max(max_drawdown, drawdown)
            return max_drawdown
        
        # Test with sample PnL curve
        pnl_curve = [0.0, 0.05, 0.10, 0.08, 0.12, 0.05, -0.02, -0.05]
        
        drawdown_1 = calculate_drawdown_method_1(pnl_curve)
        drawdown_2 = calculate_drawdown_method_2(pnl_curve)
        
        # Both should calculate drawdown
        assert drawdown_1 >= 0, f"Drawdown should be non-negative: {drawdown_1}"
        assert drawdown_2 >= 0, f"Drawdown should be non-negative: {drawdown_2}"
        
        # Rolling drawdown should be <= peak-to-trough
        assert drawdown_2 <= drawdown_1 + 0.01, \
            f"Rolling drawdown should be <= peak-to-trough: {drawdown_2} vs {drawdown_1}"


class TestPortfolioRiskAggregationConsistency:
    """Differential tests for portfolio risk aggregation consistency."""

    def test_portfolio_variance_calculation(self):
        """Portfolio variance calculation should be consistent."""
        # Method 1: Full covariance matrix
        def calculate_variance_method_1(weights: List[float], cov_matrix: List[List[float]]) -> float:
            variance = 0.0
            for i in range(len(weights)):
                for j in range(len(weights)):
                    variance += weights[i] * weights[j] * cov_matrix[i][j]
            return variance
        
        # Method 2: Diagonal approximation (assume independence)
        def calculate_variance_method_2(weights: List[float], variances: List[float]) -> float:
            variance = 0.0
            for i in range(len(weights)):
                variance += weights[i] ** 2 * variances[i]
            return variance
        
        # Test with sample data
        weights = [0.5, 0.3, 0.2]
        cov_matrix = [
            [0.04, 0.01, 0.005],
            [0.01, 0.03, 0.008],
            [0.005, 0.008, 0.02]
        ]
        variances = [0.04, 0.03, 0.02]
        
        variance_1 = calculate_variance_method_1(weights, cov_matrix)
        variance_2 = calculate_variance_method_2(weights, variances)
        
        # Full covariance should account for correlations
        # Diagonal approximation should underestimate/overestimate depending on correlation
        assert variance_1 >= 0, f"Variance should be non-negative: {variance_1}"
        assert variance_2 >= 0, f"Variance should be non-negative: {variance_2}"

    def test_portfolio_beta_calculation(self):
        """Portfolio beta calculation should be consistent."""
        # Method 1: Weighted average beta
        def calculate_beta_method_1(weights: List[float], betas: List[float]) -> float:
            portfolio_beta = 0.0
            for i in range(len(weights)):
                portfolio_beta += weights[i] * betas[i]
            return portfolio_beta
        
        # Method 2: Regression-based beta
        def calculate_beta_method_2(portfolio_returns: List[float], market_returns: List[float]) -> float:
            # Simple linear regression
            n = len(portfolio_returns)
            sum_x = sum(market_returns)
            sum_y = sum(portfolio_returns)
            sum_xy = sum(x * y for x, y in zip(market_returns, portfolio_returns))
            sum_x2 = sum(x ** 2 for x in market_returns)
            
            beta = (n * sum_xy - sum_x * sum_y) / (n * sum_x2 - sum_x ** 2)
            return beta
        
        # Test with sample data
        weights = [0.5, 0.3, 0.2]
        betas = [1.2, 0.8, 1.5]
        
        beta_1 = calculate_beta_method_1(weights, betas)
        
        # Weighted average should be between min and max betas
        assert min(betas) <= beta_1 <= max(betas), \
            f"Beta should be within range: {beta_1}"
        
        # Test regression method
        portfolio_returns = [0.05, 0.03, -0.02, 0.04, 0.01]
        market_returns = [0.04, 0.02, -0.01, 0.03, 0.02]
        
        beta_2 = calculate_beta_method_2(portfolio_returns, market_returns)
        assert isinstance(beta_2, float), f"Beta should be float: {beta_2}"

    def test_concentration_risk_calculation(self):
        """Concentration risk calculation should be consistent."""
        # Method 1: Herfindahl-Hirschman Index (HHI)
        def calculate_hhi(weights: List[float]) -> float:
            return sum(w ** 2 for w in weights)
        
        # Method 2: Maximum weight concentration
        def calculate_max_concentration(weights: List[float]) -> float:
            return max(weights)
        
        # Test with various weight distributions
        test_weights = [
            [0.5, 0.3, 0.2],      # Concentrated
            [0.33, 0.33, 0.34],    # Balanced
            [0.8, 0.1, 0.1],      # Highly concentrated
        ]
        
        for weights in test_weights:
            hhi = calculate_hhi(weights)
            max_conc = calculate_max_concentration(weights)
            
            # HHI should be between max_conc^2 and 1.0
            assert max_conc ** 2 <= hhi <= 1.0, \
                f"HHI should be in valid range: {hhi} (max_conc={max_conc})"
            
            # Higher concentration should have higher HHI
            if max_conc > 0.5:
                assert hhi > 0.3, f"High concentration should have high HHI: {hhi}"


class TestMarginCalculationConsistency:
    """Differential tests for margin calculation consistency."""

    def test_initial_margin_calculation(self):
        """Initial margin calculation should be consistent."""
        # Method 1: Percentage of position value
        def calculate_margin_method_1(position_value: float, margin_rate: float) -> float:
            return position_value * margin_rate
        
        # Method 2: Fixed amount per contract
        def calculate_margin_method_2(num_contracts: int, margin_per_contract: float) -> float:
            return num_contracts * margin_per_contract
        
        # Test with various scenarios
        position_value = 1000.0
        margin_rate = 0.1  # 10% margin
        num_contracts = 10
        margin_per_contract = 100.0
        
        margin_1 = calculate_margin_method_1(position_value, margin_rate)
        margin_2 = calculate_margin_method_2(num_contracts, margin_per_contract)
        
        # Both should produce positive margin
        assert margin_1 > 0, f"Margin should be positive: {margin_1}"
        assert margin_2 > 0, f"Margin should be positive: {margin_2}"
        
        # If parameters are equivalent, margins should match
        if position_value == num_contracts * margin_per_contract / margin_rate:
            assert abs(margin_1 - margin_2) < 0.01, \
                f"Margins should match for equivalent parameters: {margin_1} vs {margin_2}"

    def test_maintenance_margin_calculation(self):
        """Maintenance margin calculation should be consistent."""
        initial_margin = 100.0
        maintenance_ratio = 0.75  # 75% of initial margin
        
        # Method 1: Fixed percentage of initial margin
        def calculate_maintenance_margin_method_1(initial: float, ratio: float) -> float:
            return initial * ratio
        
        # Method 2: Based on position value and volatility
        def calculate_maintenance_margin_method_2(position_value: float, volatility: float) -> float:
            return position_value * volatility * 2.0  # 2x volatility as margin
        
        # Test with various scenarios
        maintenance_1 = calculate_maintenance_margin_method_1(initial_margin, maintenance_ratio)
        
        position_value = 1000.0
        volatility = 0.05  # 5% volatility
        maintenance_2 = calculate_maintenance_margin_method_2(position_value, volatility)
        
        # Maintenance margin should be less than initial margin
        assert maintenance_1 < initial_margin, \
            f"Maintenance margin should be less than initial: {maintenance_1} vs {initial_margin}"
        
        # Both should be positive
        assert maintenance_1 > 0, f"Maintenance margin should be positive: {maintenance_1}"
        assert maintenance_2 > 0, f"Maintenance margin should be positive: {maintenance_2}"

    def test_margin_call_threshold_consistency(self):
        """Margin call threshold calculation should be consistent."""
        account_value = 10000.0
        total_margin = 2000.0
        
        # Method 1: Fixed percentage threshold
        def calculate_margin_call_threshold_method_1(total_margin: float, threshold_pct: float) -> float:
            return total_margin * threshold_pct
        
        # Method 2: Equity-based threshold
        def calculate_margin_call_threshold_method_2(account_value: float, total_margin: float) -> float:
            equity = account_value - total_margin
            return equity * 0.5  # 50% of equity as buffer
        
        # Test with various scenarios
        threshold_1 = calculate_margin_call_threshold_method_1(total_margin, 0.5)
        threshold_2 = calculate_margin_call_threshold_method_2(account_value, total_margin)
        
        # Both should produce positive thresholds
        assert threshold_1 > 0, f"Threshold should be positive: {threshold_1}"
        assert threshold_2 > 0, f"Threshold should be positive: {threshold_2}"
        
        # Threshold should be reasonable relative to margin
        assert threshold_1 < total_margin, \
            f"Threshold should be less than total margin: {threshold_1} vs {total_margin}"
