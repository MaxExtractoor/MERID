"""
Memecoin Safety Filters for MERID
Liquidity thresholds, contract safety, volatility limits, and exposure caps.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

from utils.logger import get_logger
from social.social_aware_quant import get_social_aware_quant_engine

logger = get_logger("core.memecoin_safety")


class SafetyLevel(Enum):
    """Safety level for memecoins."""
    SAFE = "safe"
    MODERATE = "moderate"
    RISKY = "risky"
    DANGEROUS = "dangerous"
    BLOCKED = "blocked"


class RiskFlag(Enum):
    """Risk flags for memecoins."""
    LOW_LIQUIDITY = "low_liquidity"
    NEW_TOKEN = "new_token"
    HONEYPOT = "honeypot"
    HIGH_VOLATILITY = "high_volatility"
    CONCENTRATED_OWNERSHIP = "concentrated_ownership"
    NO_VERIFIED_CONTRACT = "no_verified_contract"
    SUSPICIOUS_TRANSFERS = "suspicious_transfers"
    RUG_PULL_PATTERN = "rug_pull_pattern"


@dataclass
class TokenSafetyCheck:
    """Safety check result for a token."""
    token_address: str
    token_symbol: str
    safety_level: SafetyLevel
    risk_flags: List[RiskFlag]
    liquidity_usd: float
    age_days: int
    holder_count: int
    top_10_ownership: float
    volatility_24h: float
    contract_verified: bool
    honeypot_detected: bool
    timestamp: float


@dataclass
class ExposureLimit:
    """Exposure limits for memecoins."""
    max_position_size_usd: float
    max_portfolio_allocation: float
    max_daily_volume_usd: float
    max_tokens_held: int


class ContractAnalyzer:
    """Analyzes token contracts for safety."""
    
    def check_honeypot(self, token_address: str) -> bool:
        """Check if token is a honeypot."""
        # In production, analyze contract code for:
        # - Sell restrictions
        # - Hidden fees
        # - Blacklist functions
        # - Ownership concentration
        
        return False
    
    def check_verified(self, token_address: str) -> bool:
        """Check if contract is verified."""
        # In production, check on block explorer
        return True
    
    def analyze_ownership(self, token_address: str) -> Dict[str, float]:
        """Analyze token ownership distribution."""
        # In production, query on-chain data
        return {
            "top_1": 0.15,
            "top_10": 0.45,
            "top_100": 0.75
        }
    
    def detect_rug_pull_pattern(self, token_address: str) -> bool:
        """Detect rug pull patterns."""
        # In production, analyze:
        # - Liquidity removal events
        # - Large holder dumps
        # - Contract ownership changes
        # - Suspicious transfer patterns
        
        return False


class LiquidityAnalyzer:
    """Analyzes token liquidity."""
    
    def get_liquidity_usd(self, token_address: str) -> float:
        """Get total liquidity in USD."""
        # In production, query DEX pools
        return 50000.0
    
    def get_liquidity_depth(
        self,
        token_address: str,
        trade_size_usd: float
    ) -> Dict[str, float]:
        """Get liquidity depth for trade size."""
        # In production, calculate slippage for trade size
        return {
            "available_liquidity": 50000.0,
            "estimated_slippage": 0.02,
            "price_impact": 0.015
        }
    
    def check_liquidity_locked(self, token_address: str) -> Dict[str, Any]:
        """Check if liquidity is locked."""
        # In production, check for liquidity locks
        return {
            "locked": True,
            "lock_duration_days": 365,
            "locked_percentage": 0.8
        }


class VolatilityAnalyzer:
    """Analyzes token volatility."""
    
    def calculate_volatility_24h(self, token_address: str) -> float:
        """Calculate 24h volatility."""
        # In production, calculate from price history
        return 0.35  # 35% daily volatility
    
    def calculate_volatility_7d(self, token_address: str) -> float:
        """Calculate 7d volatility."""
        return 0.55
    
    def detect_pump_dump(self, token_address: str) -> bool:
        """Detect pump and dump patterns."""
        # In production, analyze price and volume patterns
        return False


class MemecoinSafetyFilter:
    """Comprehensive safety filter for memecoins."""
    
    def __init__(self):
        self._contract_analyzer = ContractAnalyzer()
        self._liquidity_analyzer = LiquidityAnalyzer()
        self._volatility_analyzer = VolatilityAnalyzer()
        
        # Safety thresholds
        self._min_liquidity_usd = 10000.0
        self._min_age_days = 7
        self._min_holder_count = 100
        self._max_top_10_ownership = 0.5
        self._max_volatility_24h = 0.5
        
        # Exposure limits
        self._exposure_limits = ExposureLimit(
            max_position_size_usd=1000.0,
            max_portfolio_allocation=0.05,
            max_daily_volume_usd=5000.0,
            max_tokens_held=10
        )
    
    def check_token_safety(
        self,
        token_address: str,
        token_symbol: str
    ) -> TokenSafetyCheck:
        """Perform comprehensive safety check."""
        risk_flags = []
        
        # Check liquidity
        liquidity_usd = self._liquidity_analyzer.get_liquidity_usd(token_address)
        if liquidity_usd < self._min_liquidity_usd:
            risk_flags.append(RiskFlag.LOW_LIQUIDITY)
        
        # Check age (simulated)
        age_days = 30
        if age_days < self._min_age_days:
            risk_flags.append(RiskFlag.NEW_TOKEN)
        
        # Check contract
        contract_verified = self._contract_analyzer.check_verified(token_address)
        if not contract_verified:
            risk_flags.append(RiskFlag.NO_VERIFIED_CONTRACT)
        
        honeypot_detected = self._contract_analyzer.check_honeypot(token_address)
        if honeypot_detected:
            risk_flags.append(RiskFlag.HONEYPOT)
        
        # Check ownership
        ownership = self._contract_analyzer.analyze_ownership(token_address)
        top_10_ownership = ownership["top_10"]
        if top_10_ownership > self._max_top_10_ownership:
            risk_flags.append(RiskFlag.CONCENTRATED_OWNERSHIP)
        
        # Check volatility
        volatility_24h = self._volatility_analyzer.calculate_volatility_24h(token_address)
        if volatility_24h > self._max_volatility_24h:
            risk_flags.append(RiskFlag.HIGH_VOLATILITY)
        
        # Check rug pull patterns
        if self._contract_analyzer.detect_rug_pull_pattern(token_address):
            risk_flags.append(RiskFlag.RUG_PULL_PATTERN)
        
        # Determine safety level
        safety_level = self._determine_safety_level(risk_flags)
        
        return TokenSafetyCheck(
            token_address=token_address,
            token_symbol=token_symbol,
            safety_level=safety_level,
            risk_flags=risk_flags,
            liquidity_usd=liquidity_usd,
            age_days=age_days,
            holder_count=1000,
            top_10_ownership=top_10_ownership,
            volatility_24h=volatility_24h,
            contract_verified=contract_verified,
            honeypot_detected=honeypot_detected,
            timestamp=time.time()
        )
    
    def _determine_safety_level(self, risk_flags: List[RiskFlag]) -> SafetyLevel:
        """Determine overall safety level."""
        critical_flags = {RiskFlag.HONEYPOT, RiskFlag.RUG_PULL_PATTERN}
        high_risk_flags = {RiskFlag.LOW_LIQUIDITY, RiskFlag.CONCENTRATED_OWNERSHIP}
        
        # Check for critical flags
        if any(flag in critical_flags for flag in risk_flags):
            return SafetyLevel.BLOCKED
        
        # Count risk flags
        high_risk_count = sum(1 for flag in risk_flags if flag in high_risk_flags)
        total_flags = len(risk_flags)
        
        if total_flags == 0:
            return SafetyLevel.SAFE
        elif total_flags <= 2 and high_risk_count == 0:
            return SafetyLevel.MODERATE
        elif total_flags <= 3 or high_risk_count <= 1:
            return SafetyLevel.RISKY
        else:
            return SafetyLevel.DANGEROUS
    
    def is_trade_allowed(
        self,
        token_address: str,
        trade_size_usd: float,
        strategy_id: Optional[str] = None,
    ) -> tuple[bool, str]:
        """Check if trade is allowed."""
        # Check safety
        safety_check = self.check_token_safety(token_address, "MEME")
        
        if safety_check.safety_level == SafetyLevel.BLOCKED:
            return False, "Token blocked due to critical safety issues"
        
        if safety_check.safety_level == SafetyLevel.DANGEROUS:
            return False, "Token too dangerous for trading"
        
        # Check position size
        if trade_size_usd > self._exposure_limits.max_position_size_usd:
            return False, f"Trade size exceeds limit of ${self._exposure_limits.max_position_size_usd}"
        
        # Check liquidity depth
        depth = self._liquidity_analyzer.get_liquidity_depth(token_address, trade_size_usd)
        if depth["estimated_slippage"] > 0.05:
            return False, f"Slippage too high: {depth['estimated_slippage']:.2%}"
        
        # Check social-specific constraints for social strategies
        if strategy_id:
            try:
                social_engine = get_social_aware_quant_engine()
                if social_engine.is_social_asset(token_address):
                    constraints = social_engine.get_position_constraints(token_address)
                    
                    if constraints.get("kill_switch_active"):
                        return False, f"Social kill switch active: {constraints.get('kill_switch_reason', 'unknown')}"
                    
                    if not constraints.get("data_fresh", True):
                        return False, "Social data is stale for this memecoin"
                    
                    if not constraints.get("confirmation_available", True):
                        return False, "No market confirmation available for social memecoin trade"
            except Exception as e:
                logger.error(f"Social risk check failed for memecoin: {e}")
        
        return True, "Trade allowed"
    
    def get_exposure_limits(self) -> ExposureLimit:
        """Get current exposure limits."""
        return self._exposure_limits
    
    def update_exposure_limits(self, limits: ExposureLimit) -> None:
        """Update exposure limits."""
        self._exposure_limits = limits
        logger.info(f"Updated memecoin exposure limits: {limits}")


class MemecoinPortfolioManager:
    """Manages memecoin portfolio with strict limits."""
    
    def __init__(self):
        self._safety_filter = MemecoinSafetyFilter()
        self._positions: Dict[str, float] = {}
        self._daily_volume: Dict[str, float] = {}
        self._last_reset = time.time()
    
    def can_open_position(
        self,
        token_address: str,
        size_usd: float
    ) -> tuple[bool, str]:
        """Check if can open new position."""
        # Reset daily volume if needed
        self._reset_daily_volume_if_needed()
        
        # Check safety
        allowed, reason = self._safety_filter.is_trade_allowed(token_address, size_usd)
        if not allowed:
            return False, reason
        
        limits = self._safety_filter.get_exposure_limits()
        
        # Check max tokens held
        if len(self._positions) >= limits.max_tokens_held:
            return False, f"Max tokens held: {limits.max_tokens_held}"
        
        # Check daily volume
        daily_vol = self._daily_volume.get(token_address, 0.0)
        if daily_vol + size_usd > limits.max_daily_volume_usd:
            return False, f"Daily volume limit exceeded: ${limits.max_daily_volume_usd}"
        
        # Check portfolio allocation
        total_portfolio = sum(self._positions.values())
        if total_portfolio > 0:
            new_allocation = size_usd / (total_portfolio + size_usd)
            if new_allocation > limits.max_portfolio_allocation:
                return False, f"Portfolio allocation limit: {limits.max_portfolio_allocation:.1%}"
        
        return True, "Position allowed"
    
    def open_position(self, token_address: str, size_usd: float) -> bool:
        """Open a position."""
        allowed, reason = self.can_open_position(token_address, size_usd)
        
        if not allowed:
            logger.warning(f"Position rejected: {reason}")
            return False
        
        self._positions[token_address] = size_usd
        self._daily_volume[token_address] = self._daily_volume.get(token_address, 0.0) + size_usd
        
        logger.info(f"Opened memecoin position: {token_address} ${size_usd}")
        return True
    
    def close_position(self, token_address: str) -> None:
        """Close a position."""
        if token_address in self._positions:
            size = self._positions[token_address]
            del self._positions[token_address]
            logger.info(f"Closed memecoin position: {token_address} ${size}")
    
    def _reset_daily_volume_if_needed(self) -> None:
        """Reset daily volume counter if day changed."""
        current_time = time.time()
        if current_time - self._last_reset > 86400:  # 24 hours
            self._daily_volume.clear()
            self._last_reset = current_time
    
    def get_portfolio_summary(self) -> Dict[str, Any]:
        """Get portfolio summary."""
        limits = self._safety_filter.get_exposure_limits()
        total_exposure = sum(self._positions.values())
        
        return {
            "positions": len(self._positions),
            "total_exposure_usd": total_exposure,
            "max_tokens": limits.max_tokens_held,
            "max_position_size": limits.max_position_size_usd,
            "max_portfolio_allocation": limits.max_portfolio_allocation,
            "positions_detail": self._positions.copy()
        }


# Global instances
_memecoin_safety_filter: Optional[MemecoinSafetyFilter] = None
_memecoin_safety_filter_lock = threading.Lock()
_memecoin_portfolio_manager: Optional[MemecoinPortfolioManager] = None
_memecoin_portfolio_manager_lock = threading.Lock()


def get_memecoin_safety_filter() -> MemecoinSafetyFilter:
    """Get the global memecoin safety filter."""
    global _memecoin_safety_filter
    if _memecoin_safety_filter is None:
        with _memecoin_safety_filter_lock:
            if _memecoin_safety_filter is None:
                _memecoin_safety_filter = MemecoinSafetyFilter()
    return _memecoin_safety_filter


def get_memecoin_portfolio_manager() -> MemecoinPortfolioManager:
    """Get the global memecoin portfolio manager."""
    global _memecoin_portfolio_manager
    if _memecoin_portfolio_manager is None:
        with _memecoin_portfolio_manager_lock:
            if _memecoin_portfolio_manager is None:
                _memecoin_portfolio_manager = MemecoinPortfolioManager()
    return _memecoin_portfolio_manager
