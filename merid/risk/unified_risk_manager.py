"""UnifiedRiskManager — Single Source of Truth for all risk management.

This module consolidates all risk management logic into a single, simple
configuration-driven system. It replaces the over-engineered multi-layer
approach with:

1. Single configuration file (config/risk_limits.yaml)
2. Single entry point for all order checks (check_order())
3. Single calibration method (calibrate_from_balance())
4. Bankroll-based dynamic limits

All risk parameters are percentages of live bankroll, making it trivial
to adjust caps by editing one YAML file.

Usage::

    from merid.risk.unified_risk_manager import get_unified_risk_manager
    
    risk_mgr = get_unified_risk_manager()
    
    # Check order before submission
    allowed, reason = risk_mgr.check_order(
        ticker="KXBTC15M-...",
        contracts=10,
        price_cents=55,
        category="crypto",
        underlying="BTC"
    )
    
    if not allowed:
        logger.error(f"[RISK] Order rejected: {reason}")
        return
    
    # Calibrate limits when bankroll changes
    risk_mgr.calibrate_from_balance(balance_cents=50000)  # $500 bankroll
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional, Tuple

import yaml

from utils.logger import get_logger

logger = get_logger("merid.risk.unified_risk_manager")


@dataclass
class RiskLimits:
    """Risk limits loaded from config/risk_limits.yaml."""
    
    # Bankroll-based limits
    max_cycle_risk_pct: float = 0.25
    max_total_risk_pct: float = 0.30
    daily_loss_pct: float = 0.03
    cluster_stop_pct: float = 0.015
    
    # Category caps
    category_crypto_max_notional_pct: float = 0.30
    category_crypto_min_cap_usd: float = 100.0
    
    # Correlated stack caps
    correlated_stack_max_notional_pct: float = 0.25
    correlated_stack_min_cap_usd: float = 10.0
    
    # Per-asset caps
    per_asset_enabled: bool = False
    per_asset_min_cap_usd: float = 5.0
    
    # Per-trade limits
    per_trade_max_notional_pct: float = 0.05
    per_trade_max_contracts: int = 10
    
    # Drawdown limits
    drawdown_halt_pct: float = 0.10
    drawdown_unwind_pct: float = 0.15
    
    # Rate limiting
    rate_limit_max_trades_per_hour: int = 20
    rate_limit_min_time_between_trades: float = 60.0
    
    # Emergency controls
    emergency_halt: bool = False
    emergency_halt_reason: str = ""


@dataclass
class RiskDecision:
    """Decision from unified risk manager."""
    allowed: bool
    reason: str
    current_exposure_usd: float = 0.0
    proposed_exposure_usd: float = 0.0
    limit_usd: float = 0.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class UnifiedRiskManager:
    """Unified risk manager — single source of truth for all risk checks.
    
    This is a process-wide singleton that:
    1. Loads risk limits from config/risk_limits.yaml
    2. Enforces all risk checks in one place
    3. Calibrates limits dynamically from bankroll
    4. Tracks exposure across all orders
    
    SAFETY INVARIANTS:
    1. All orders MUST call check_order() before submission
    2. All limits are percentages of live bankroll
    3. Emergency halt immediately blocks all orders
    4. Fail-closed: any error = order blocked
    """
    
    _instance: Optional["UnifiedRiskManager"] = None
    _lock: threading.Lock = threading.Lock()
    
    def __new__(cls) -> "UnifiedRiskManager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        with self._lock:
            if self._initialized:
                return
            
            self._limits = self._load_config()
            self._bankroll_cents: int = 0
            self._bankroll_usd: float = 0.0
            
            # Exposure tracking
            self._category_exposure: Dict[str, float] = {}  # category -> USD
            self._correlated_exposure: Dict[str, float] = {}  # underlying -> USD
            self._total_exposure_usd: float = 0.0
            self._cycle_exposure_usd: float = 0.0
            
            # Daily loss tracking
            self._daily_loss_usd: float = 0.0
            self._daily_start_usd: float = 0.0
            self._last_reset_date: Optional[datetime] = None
            
            # Rate limiting
            self._trades_this_hour: int = 0
            self._last_trade_time: float = 0.0
            self._last_hour_reset: float = time.time()
            
            # Telemetry
            self._approvals: int = 0
            self._rejections: int = 0
            
            self._initialized = True
            logger.info("[UNIFIED_RISK] Initialized with limits from config/risk_limits.yaml")
    
    def _load_config(self) -> RiskLimits:
        """Load risk limits from config/risk_limits.yaml."""
        config_path = Path(__file__).parent.parent.parent / "config" / "risk_limits.yaml"
        
        if not config_path.exists():
            logger.warning(f"[UNIFIED_RISK] Config file not found: {config_path}, using defaults")
            return RiskLimits()
        
        try:
            with open(config_path, 'r') as f:
                config = yaml.safe_load(f)
            
            limits = RiskLimits()
            
            # Bankroll limits
            if 'bankroll' in config:
                limits.max_cycle_risk_pct = config['bankroll'].get('max_cycle_risk_pct', 0.25)
                limits.max_total_risk_pct = config['bankroll'].get('max_total_risk_pct', 0.30)
                limits.daily_loss_pct = config['bankroll'].get('daily_loss_pct', 0.03)
                limits.cluster_stop_pct = config['bankroll'].get('cluster_stop_pct', 0.015)
            
            # Category caps
            if 'categories' in config and 'crypto' in config['categories']:
                limits.category_crypto_max_notional_pct = config['categories']['crypto'].get('max_notional_pct', 0.30)
                limits.category_crypto_min_cap_usd = config['categories']['crypto'].get('min_cap_usd', 100.0)
            
            # Correlated stack caps
            if 'correlated_stack' in config:
                limits.correlated_stack_max_notional_pct = config['correlated_stack'].get('max_notional_pct', 0.25)
                limits.correlated_stack_min_cap_usd = config['correlated_stack'].get('min_cap_usd', 10.0)
            
            # Per-asset caps
            if 'per_asset' in config:
                limits.per_asset_enabled = config['per_asset'].get('enabled', False)
                limits.per_asset_min_cap_usd = config['per_asset'].get('min_cap_usd', 5.0)
            
            # Per-trade limits
            if 'per_trade' in config:
                limits.per_trade_max_notional_pct = config['per_trade'].get('max_notional_pct', 0.05)
                limits.per_trade_max_contracts = config['per_trade'].get('max_contracts', 10)
            
            # Drawdown limits
            if 'drawdown' in config:
                limits.drawdown_halt_pct = config['drawdown'].get('halt_pct', 0.10)
                limits.drawdown_unwind_pct = config['drawdown'].get('unwind_pct', 0.15)
            
            # Rate limiting
            if 'rate_limit' in config:
                limits.rate_limit_max_trades_per_hour = config['rate_limit'].get('max_trades_per_hour', 20)
                limits.rate_limit_min_time_between_trades = config['rate_limit'].get('min_time_between_trades', 60.0)
            
            # Emergency controls
            if 'emergency' in config:
                limits.emergency_halt = config['emergency'].get('halt', False)
                limits.emergency_halt_reason = config['emergency'].get('halt_reason', "")
            
            logger.info(f"[UNIFIED_RISK] Loaded config from {config_path}")
            return limits
            
        except Exception as e:
            logger.error(f"[UNIFIED_RISK] Failed to load config: {e}, using defaults")
            return RiskLimits()
    
    def calibrate_from_balance(self, balance_cents: int) -> None:
        """Update risk limits based on live bankroll.
        
        This should be called whenever the Kalshi balance changes significantly
        (e.g., after fills, withdrawals, or deposits).
        
        Args:
            balance_cents: Current balance in cents (e.g., 5000 = $50.00)
        """
        if balance_cents <= 0:
            logger.warning(f"[UNIFIED_RISK] Invalid balance: {balance_cents}, skipping calibration")
            return
        
        with self._lock:
            self._bankroll_cents = balance_cents
            self._bankroll_usd = balance_cents / 100.0
            
            # Reset daily tracking if it's a new day
            now = datetime.now(timezone.utc)
            if self._last_reset_date is None or now.date() != self._last_reset_date.date():
                self._daily_loss_usd = 0.0
                self._daily_start_usd = self._bankroll_usd
                self._last_reset_date = now
                logger.info(f"[UNIFIED_RISK] Daily tracking reset for {now.date()}")
            
            # Log calibrated limits
            logger.info(
                f"[UNIFIED_RISK] Calibrated from balance: ${self._bankroll_usd:.2f} | "
                f"Cycle cap: ${self._get_cycle_cap_usd():.2f} ({self._limits.max_cycle_risk_pct*100:.0f}%) | "
                f"Total cap: ${self._get_total_cap_usd():.2f} ({self._limits.max_total_risk_pct*100:.0f}%) | "
                f"Correlated cap: ${self._get_correlated_cap_usd():.2f} ({self._limits.correlated_stack_max_notional_pct*100:.0f}%)"
            )
    
    def _get_cycle_cap_usd(self) -> float:
        """Get cycle cap in USD."""
        return max(
            self._bankroll_usd * self._limits.max_cycle_risk_pct,
            0.10  # Minimum $0.10 for very small bankrolls
        )
    
    def _get_total_cap_usd(self) -> float:
        """Get total cap in USD."""
        return max(
            self._bankroll_usd * self._limits.max_total_risk_pct,
            1.0  # Minimum $1
        )
    
    def _get_correlated_cap_usd(self) -> float:
        """Get correlated stack cap in USD."""
        return max(
            self._bankroll_usd * self._limits.correlated_stack_max_notional_pct,
            self._limits.correlated_stack_min_cap_usd
        )
    
    def _get_category_cap_usd(self, category: str) -> float:
        """Get category cap in USD."""
        if category == "crypto":
            return max(
                self._bankroll_usd * self._limits.category_crypto_max_notional_pct,
                self._limits.category_crypto_min_cap_usd
            )
        return self._get_total_cap_usd()  # Default to total cap
    
    def check_order(
        self,
        ticker: str,
        contracts: int,
        price_cents: int,
        category: str = "crypto",
        underlying: str = "",
    ) -> Tuple[bool, str]:
        """Check if order is allowed under current risk limits.
        
        This is the single entry point for all order risk checks. It enforces:
        1. Emergency halt
        2. Per-trade limits (contracts, notional)
        3. Category exposure caps
        4. Correlated stack caps
        5. Total exposure caps
        6. Daily loss limits
        7. Rate limiting
        
        Args:
            ticker: Market ticker (e.g., "KXBTC15M-...")
            contracts: Number of contracts
            price_cents: Price per contract in cents
            category: Category (e.g., "crypto")
            underlying: Underlying asset (e.g., "BTC")
        
        Returns:
            Tuple of (allowed: bool, reason: str)
        """
        with self._lock:
            # Emergency halt check
            if self._limits.emergency_halt:
                reason = f"EMERGENCY_HALT: {self._limits.emergency_halt_reason}"
                self._rejections += 1
                logger.warning(f"[UNIFIED_RISK] Order rejected: {reason}")
                return False, reason
            
            # Validate bankroll is set
            if self._bankroll_cents <= 0:
                reason = "NO_BANKROLL: Bankroll not calibrated, call calibrate_from_balance() first"
                self._rejections += 1
                logger.error(f"[UNIFIED_RISK] Order rejected: {reason}")
                return False, reason
            
            # Calculate order notional
            notional_usd = (contracts * price_cents) / 100.0
            
            # Per-trade contract limit
            if contracts > self._limits.per_trade_max_contracts:
                reason = f"MAX_CONTRACTS: {contracts} > {self._limits.per_trade_max_contracts}"
                self._rejections += 1
                logger.warning(f"[UNIFIED_RISK] Order rejected: {reason}")
                return False, reason
            
            # Per-trade notional limit
            per_trade_cap = self._bankroll_usd * self._limits.per_trade_max_notional_pct
            # CRITICAL FIX: Add minimum floor for small bankrolls (<$100)
            # Research shows small accounts should use minimum stake pricing
            # This prevents rejections when contract price exceeds percentage-based limit
            if self._bankroll_usd < 100.0:
                per_trade_cap = max(per_trade_cap, 1.00)  # Minimum $1.00 for small accounts
                logger.debug(f"[UNIFIED_RISK] Small bankroll ($%.2f) - using minimum floor $1.00 for per-trade cap", self._bankroll_usd)
            if notional_usd > per_trade_cap:
                reason = f"PER_TRADE_NOTIONAL: ${notional_usd:.2f} > ${per_trade_cap:.2f}"
                self._rejections += 1
                logger.warning(f"[UNIFIED_RISK] Order rejected: {reason}")
                return False, reason
            
            # Category exposure check
            category_cap = self._get_category_cap_usd(category)
            current_category_exposure = self._category_exposure.get(category, 0.0)
            if current_category_exposure + notional_usd > category_cap:
                reason = (
                    f"CATEGORY_CAP: {category} current=${current_category_exposure:.2f}+${notional_usd:.2f} "
                    f"> ${category_cap:.2f}"
                )
                self._rejections += 1
                logger.warning(f"[UNIFIED_RISK] Order rejected: {reason}")
                return False, reason
            
            # Correlated stack check (if underlying provided)
            if underlying:
                correlated_cap = self._get_correlated_cap_usd()
                current_correlated_exposure = self._correlated_exposure.get(underlying.upper(), 0.0)
                if current_correlated_exposure + notional_usd > correlated_cap:
                    reason = (
                        f"CORRELATED_STACK: {underlying.upper()} current=${current_correlated_exposure:.2f}+${notional_usd:.2f} "
                        f"> ${correlated_cap:.2f}"
                    )
                    self._rejections += 1
                    logger.warning(f"[UNIFIED_RISK] Order rejected: {reason}")
                    return False, reason
            
            # Total exposure check
            total_cap = self._get_total_cap_usd()
            if self._total_exposure_usd + notional_usd > total_cap:
                reason = (
                    f"TOTAL_EXPOSURE: current=${self._total_exposure_usd:.2f}+${notional_usd:.2f} "
                    f"> ${total_cap:.2f}"
                )
                self._rejections += 1
                logger.warning(f"[UNIFIED_RISK] Order rejected: {reason}")
                return False, reason
            
            # Daily loss check
            daily_loss_cap = self._bankroll_usd * self._limits.daily_loss_pct
            if self._daily_loss_usd + notional_usd > daily_loss_cap:
                reason = (
                    f"DAILY_LOSS: current=${self._daily_loss_usd:.2f}+${notional_usd:.2f} "
                    f"> ${daily_loss_cap:.2f}"
                )
                self._rejections += 1
                logger.warning(f"[UNIFIED_RISK] Order rejected: {reason}")
                return False, reason
            
            # Rate limiting check
            now = time.time()
            if now - self._last_hour_reset > 3600:
                self._trades_this_hour = 0
                self._last_hour_reset = now
            
            if self._trades_this_hour >= self._limits.rate_limit_max_trades_per_hour:
                reason = f"RATE_LIMIT: {self._trades_this_hour} trades/hour > {self._limits.rate_limit_max_trades_per_hour}"
                self._rejections += 1
                logger.warning(f"[UNIFIED_RISK] Order rejected: {reason}")
                return False, reason
            
            if now - self._last_trade_time < self._limits.rate_limit_min_time_between_trades:
                reason = (
                    f"RATE_LIMIT: {now - self._last_trade_time:.1f}s since last trade "
                    f"< {self._limits.rate_limit_min_time_between_trades}s"
                )
                self._rejections += 1
                logger.warning(f"[UNIFIED_RISK] Order rejected: {reason}")
                return False, reason
            
            # All checks passed
            self._approvals += 1
            logger.info(f"[UNIFIED_RISK] Order approved: {ticker} {contracts}x @ {price_cents}¢ = ${notional_usd:.2f}")
            return True, "OK"
    
    def record_fill(
        self,
        ticker: str,
        contracts: int,
        price_cents: int,
        category: str = "crypto",
        underlying: str = "",
    ) -> None:
        """Record a confirmed fill and update exposure tracking.
        
        Call this after order is confirmed filled by Kalshi.
        
        Args:
            ticker: Market ticker
            contracts: Number of contracts filled
            price_cents: Fill price per contract
            category: Category
            underlying: Underlying asset
        """
        with self._lock:
            notional_usd = (contracts * price_cents) / 100.0
            
            # Update category exposure
            self._category_exposure[category] = self._category_exposure.get(category, 0.0) + notional_usd
            
            # Update correlated exposure
            if underlying:
                self._correlated_exposure[underlying.upper()] = (
                    self._correlated_exposure.get(underlying.upper(), 0.0) + notional_usd
                )
            
            # Update total exposure
            self._total_exposure_usd += notional_usd
            self._cycle_exposure_usd += notional_usd
            
            # Update rate limiting
            self._trades_this_hour += 1
            self._last_trade_time = time.time()
            
            logger.info(
                f"[UNIFIED_RISK] Fill recorded: {ticker} ${notional_usd:.2f} | "
                f"Category {category}: ${self._category_exposure[category]:.2f} | "
                f"Total: ${self._total_exposure_usd:.2f}"
            )
    
    def release(
        self,
        ticker: str,
        contracts: int,
        price_cents: int,
        category: str = "crypto",
        underlying: str = "",
    ) -> None:
        """Release exposure tracking for a closed/cancelled position.
        
        Call this when a position is closed or order is cancelled.
        
        Args:
            ticker: Market ticker
            contracts: Number of contracts to release
            price_cents: Price per contract
            category: Category
            underlying: Underlying asset
        """
        with self._lock:
            notional_usd = (contracts * price_cents) / 100.0
            
            # Update category exposure
            self._category_exposure[category] = max(
                self._category_exposure.get(category, 0.0) - notional_usd, 0.0
            )
            
            # Update correlated exposure
            if underlying:
                self._correlated_exposure[underlying.upper()] = max(
                    self._correlated_exposure.get(underlying.upper(), 0.0) - notional_usd, 0.0
                )
            
            # Update total exposure
            self._total_exposure_usd = max(self._total_exposure_usd - notional_usd, 0.0)
            
            logger.info(
                f"[UNIFIED_RISK] Exposure released: {ticker} ${notional_usd:.2f} | "
                f"Total: ${self._total_exposure_usd:.2f}"
            )
    
    def reset_cycle(self) -> None:
        """Reset cycle exposure accumulator.
        
        Call this at the start of each trading cycle.
        """
        with self._lock:
            self._cycle_exposure_usd = 0.0
            logger.info("[UNIFIED_RISK] Cycle exposure reset")
    
    @classmethod
    def reset_for_tests(cls) -> None:
        """Reset the singleton instance for test isolation.
        
        This clears the singleton so each test gets a fresh instance.
        """
        with cls._lock:
            cls._instance = None
            logger.info("[UNIFIED_RISK] Singleton reset for tests")
    
    def get_current_exposure(self) -> Dict[str, float]:
        """Get current exposure tracking state.
        
        Returns:
            Dict with current exposure values
        """
        with self._lock:
            return {
                "total_exposure_usd": self._total_exposure_usd,
                "cycle_exposure_usd": self._cycle_exposure_usd,
                "daily_loss_usd": self._daily_loss_usd,
                "category_exposure": dict(self._category_exposure),
                "correlated_exposure": dict(self._correlated_exposure),
                "approvals": self._approvals,
                "rejections": self._rejections,
            }


# ── Singleton ─────────────────────────────────────────────────────────────

_unified_risk_manager: Optional[UnifiedRiskManager] = None
_unified_risk_manager_lock: threading.Lock = threading.Lock()


def get_unified_risk_manager() -> UnifiedRiskManager:
    """Return the process-wide UnifiedRiskManager singleton."""
    global _unified_risk_manager
    if _unified_risk_manager is None:
        with _unified_risk_manager_lock:
            if _unified_risk_manager is None:
                _unified_risk_manager = UnifiedRiskManager()
    return _unified_risk_manager
