"""
15M Strategy Risk Management - Conservative Position Sizing

Simple, conservative risk management with fraction-of-capital approach
and Kelly-style ceiling for crypto trading.
"""

import math
from dataclasses import dataclass
from typing import Dict, Optional
import logging

logger = logging.getLogger(__name__)

@dataclass
class RiskConfig:
    """Risk management configuration."""
    capital_usd: float
    max_risk_per_trade: float = 0.005  # 0.5% per trade
    max_exposure_per_asset: float = 0.10  # 10% per asset
    contract_notional_usd: float = 1.0  # Kalshi contract payout
    max_total_exposure: float = 0.20  # 20% total exposure
    min_signal_strength: float = 0.2  # Minimum signal strength to trade
    
    # Kelly-style parameters (can be refined via backtest)
    kelly_fraction: float = 0.25  # Use 25% of Kelly (conservative)
    expected_win_rate: float = 0.55  # Expected win rate
    avg_win_loss_ratio: float = 1.5  # Average win/loss ratio

@dataclass
class PositionLimits:
    """Position limits for risk checking."""
    max_contracts_per_trade: int
    max_contracts_per_asset: int
    max_total_contracts: int

class RiskManager:
    """Risk management for 15m strategy."""
    
    def __init__(self, config: RiskConfig):
        self.config = config
        self.limits = self._compute_limits()
        self.current_positions: Dict[str, int] = {}
        self.total_exposure = 0.0
        
    def _compute_limits(self) -> PositionLimits:
        """Compute position limits based on risk config."""
        max_contracts_per_trade = int(
            (self.config.capital_usd * self.config.max_risk_per_trade) / 
            self.config.contract_notional_usd
        )
        
        max_contracts_per_asset = int(
            (self.config.capital_usd * self.config.max_exposure_per_asset) / 
            self.config.contract_notional_usd
        )
        
        max_total_contracts = int(
            (self.config.capital_usd * self.config.max_total_exposure) / 
            self.config.contract_notional_usd
        )
        
        return PositionLimits(
            max_contracts_per_trade=max_contracts_per_trade,
            max_contracts_per_asset=max_contracts_per_asset,
            max_total_contracts=max_total_contracts
        )
    
    def compute_position_size(self, signal_strength: float, asset: str) -> int:
        """
        Compute optimal position size based on signal strength and risk limits.
        
        Uses fraction-of-capital approach with Kelly-style ceiling.
        """
        # Check minimum signal strength
        if signal_strength < self.config.min_signal_strength:
            logger.info(f"Signal strength {signal_strength:.2f} below minimum {self.config.min_signal_strength}")
            return 0
        
        # Base position size from risk budget
        risk_budget_usd = self.config.capital_usd * self.config.max_risk_per_trade
        base_contracts = int(risk_budget_usd / self.config.contract_notional_usd)
        
        # Scale by signal strength
        strength_scaled_contracts = int(base_contracts * signal_strength)
        
        # Apply Kelly-style ceiling (conservative)
        kelly_contracts = self._kelly_position_size()
        kelly_limited_contracts = int(kelly_contracts * self.config.kelly_fraction)
        
        # Take minimum of all constraints
        size = min(
            strength_scaled_contracts,
            kelly_limited_contracts,
            self.limits.max_contracts_per_trade
        )
        
        # Ensure at least 1 contract if signal is strong enough
        if signal_strength > 0.5 and size == 0:
            size = 1
        
        logger.info(f"Position size for {asset}: {size} contracts (strength: {signal_strength:.2f})")
        
        return max(size, 0)
    
    def _kelly_position_size(self) -> int:
        """
        Compute Kelly criterion position size.
        
        Kelly = (bp - q) / b
        where:
        - b = win/loss ratio
        - p = win probability
        - q = lose probability (1-p)
        """
        b = self.config.avg_win_loss_ratio
        p = self.config.expected_win_rate
        q = 1 - p
        
        if b <= 0 or p <= 0 or p >= 1:
            logger.warning("Invalid Kelly parameters, using conservative default")
            return int(self.config.capital_usd * 0.01 / self.config.contract_notional_usd)
        
        kelly_fraction = (b * p - q) / b
        kelly_fraction = max(0, min(kelly_fraction, 0.25))  # Cap at 25% for safety
        
        kelly_contracts = int(
            (self.config.capital_usd * kelly_fraction) / 
            self.config.contract_notional_usd
        )
        
        logger.info(f"Kelly position size: {kelly_contracts} contracts (fraction: {kelly_fraction:.3f})")
        
        return kelly_contracts
    
    def check_risk_limits(self, asset: str, proposed_contracts: int, side: str) -> bool:
        """
        Check if proposed trade respects risk limits.
        
        Args:
            asset: Asset name ("BTC", "ETH")
            proposed_contracts: Number of contracts to trade
            side: Trade side ("long_up", "long_down")
        
        Returns:
            True if trade respects risk limits
        """
        current_position = self.current_positions.get(asset, 0)
        new_position = current_position + proposed_contracts
        
        # Check per-trade limit
        if proposed_contracts > self.limits.max_contracts_per_trade:
            logger.warning(f"Trade size {proposed_contracts} exceeds per-trade limit {self.limits.max_contracts_per_trade}")
            return False
        
        # Check per-asset limit
        if abs(new_position) > self.limits.max_contracts_per_asset:
            logger.warning(f"Asset position {abs(new_position)} exceeds per-asset limit {self.limits.max_contracts_per_asset}")
            return False
        
        # Check total exposure
        total_exposure_contracts = sum(abs(pos) for pos in self.current_positions.values()) + proposed_contracts
        if total_exposure_contracts > self.limits.max_total_contracts:
            logger.warning(f"Total exposure {total_exposure_contracts} exceeds limit {self.limits.max_total_contracts}")
            return False
        
        # Check correlation (simplified - BTC and ETH correlation)
        if asset == "ETH" and "BTC" in self.current_positions:
            btc_position = abs(self.current_positions["BTC"])
            if btc_position > 0 and abs(new_position) > btc_position * 0.5:
                logger.warning(f"ETH position {abs(new_position)} too large relative to BTC {btc_position}")
                return False
        
        return True
    
    def update_position(self, asset: str, contracts: int):
        """Update current position after trade execution."""
        if asset not in self.current_positions:
            self.current_positions[asset] = 0
        
        self.current_positions[asset] += contracts
        
        # Update total exposure
        self.total_exposure = sum(
            abs(pos) * self.config.contract_notional_usd 
            for pos in self.current_positions.values()
        )
        
        logger.info(f"Updated {asset} position: {self.current_positions[asset]} contracts")
        logger.info(f"Total exposure: ${self.total_exposure:,.2f}")
    
    def get_risk_status(self) -> Dict[str, any]:
        """Get current risk status."""
        current_exposure_pct = self.total_exposure / self.config.capital_usd
        
        return {
            "capital_usd": self.config.capital_usd,
            "total_exposure_usd": self.total_exposure,
            "total_exposure_pct": current_exposure_pct,
            "current_positions": self.current_positions.copy(),
            "max_total_exposure_usd": self.config.capital_usd * self.config.max_total_exposure,
            "risk_utilization": current_exposure_pct / self.config.max_total_exposure,
            "limits": {
                "max_contracts_per_trade": self.limits.max_contracts_per_trade,
                "max_contracts_per_asset": self.limits.max_contracts_per_asset,
                "max_total_contracts": self.limits.max_total_contracts
            }
        }
    
    def should_reduce_risk(self) -> bool:
        """Check if risk should be reduced due to market conditions."""
        # Simple risk reduction trigger
        risk_utilization = self.total_exposure / (self.config.capital_usd * self.config.max_total_exposure)
        
        # Reduce risk if utilization > 80%
        return risk_utilization > 0.8
    
    def get_emergency_stop_level(self) -> float:
        """Get emergency stop level (max loss before stopping)."""
        return self.config.capital_usd * 0.05  # 5% max loss

# Default risk configuration
DEFAULT_RISK_CONFIG = RiskConfig(
    capital_usd=100000.0,  # $100k portfolio
    max_risk_per_trade=0.005,  # 0.5% per trade
    max_exposure_per_asset=0.10,  # 10% per asset
    contract_notional_usd=1.0,  # $1 per contract
    max_total_exposure=0.20,  # 20% total exposure
    min_signal_strength=0.2,  # Minimum 20% signal strength
    kelly_fraction=0.25,  # 25% of Kelly
    expected_win_rate=0.55,  # 55% expected win rate
    avg_win_loss_ratio=1.5  # 1.5:1 win/loss ratio
)

# Risk manager singleton
risk_manager = RiskManager(DEFAULT_RISK_CONFIG)

# Example usage:
"""
# Initialize risk manager
config = RiskConfig(capital_usd=100000.0)
risk_mgr = RiskManager(config)

# Compute position size
size = risk_mgr.compute_position_size(signal_strength=0.8, asset="BTC")

# Check risk limits
if risk_mgr.check_risk_limits("BTC", size, "long_up"):
    # Execute trade
    risk_mgr.update_position("BTC", size)
    
# Get risk status
status = risk_mgr.get_risk_status()
print(f"Risk status: {status}")
"""
