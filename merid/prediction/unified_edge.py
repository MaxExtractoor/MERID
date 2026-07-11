"""
Unified cross-asset edge computation for Kalshi 15m crypto markets.

This module implements a strict dynamic edge across assets by:
1. Normalizing everything into the same probability / R framework
2. Explicitly modeling the Kalshi contract–vs–spot relationship per asset
3. Making edge a cross-asset, spot-aligned quantity instead of raw contract price heuristic

Key concepts:
- MERID RTI spot feed (internal CFB-equivalent via unified_spot_service)
- Model win probability q_a(t) based on spot vs strike, time to expiry, vol
- Market-implied win probability π_a(t) = p_a(t) / 100
- Edge = q_a(t) - π_a(t) (unified across all assets)
- Risk-adjusted edge = edge / σ_a (normalized by volatility)
- Slippage-adjusted edge = edge - expected_slippage
- Latency-adjusted edge = edge - (lag_buffer + spread + slippage + safety_margin)
"""

from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional, Tuple, Literal, Any
from enum import Enum
import math

from utils.logger import get_logger

logger = get_logger("merid.prediction.unified_edge")

# Import rejection monitor for production rejection tracking
try:
    from merid.monitoring.rejection_monitor import get_rejection_monitor, log_edge_check_rejection
    REJECTION_MONITOR_ENABLED = True
except ImportError:
    REJECTION_MONITOR_ENABLED = False
    logger.debug("[REJECTION-MONITOR] Not available - rejection tracking disabled")

# Import canonical OrderbookSnapshot and microstructure utilities
# This is the single source of truth for order book representation
from merid.event_venues.kalshi.unified_market_state import OrderbookSnapshot
from merid.event_venues.kalshi.microstructure import (
    compute_side_microstructure,
    compute_effective_spread,
    compute_depth_at_price,
)


# Volatility regime thresholds (annualized %)
LOW_VOL = 30
NORMAL_VOL = 50
HIGH_VOL = 80


def classify_volatility_regime(volatility_pct: float) -> str:
    """Classify volatility regime based on annualized percentage.
    
    Args:
        volatility_pct: Annualized volatility percentage
        
    Returns:
        Regime string: "LOW", "NORMAL", "HIGH", "EXTREME"
    """
    if volatility_pct < LOW_VOL:
        return "LOW"
    elif volatility_pct < NORMAL_VOL:
        return "NORMAL"
    elif volatility_pct < HIGH_VOL:
        return "HIGH"
    else:
        return "EXTREME"


class EdgeCheckResult:
    """Result of edge check with detailed breakdown."""
    
    def __init__(
        self,
        passes: bool,
        reason: str,
        edge_result: Optional['EdgeResult'] = None,
        spread_pct: Optional[float] = None,
        min_edge_cents: Optional[float] = None,
        max_spread_pct: Optional[float] = None,
    ):
        self.passes = passes
        self.reason = reason
        self.edge_result = edge_result
        self.spread_pct = spread_pct
        self.min_edge_cents = min_edge_cents
        self.max_spread_pct = max_spread_pct
    
    def to_log_dict(self) -> Dict:
        """Convert to dictionary for logging."""
        return {
            "passes": self.passes,
            "reason": self.reason,
            "spread_pct": self.spread_pct,
            "min_edge_cents": self.min_edge_cents,
            "max_spread_pct": self.max_spread_pct,
        }
    
    def __str__(self) -> str:
        """String representation for logging."""
        if self.passes:
            return f"PASS: {self.reason}"
        else:
            return f"FAIL: {self.reason}"


@dataclass
class SpotReference:
    """CFB-anchored spot reference for an asset."""
    asset: str
    price_usd: float
    timestamp: datetime
    source: str  # "CFB", "composite", "exchange"
    is_rti_proxy: bool = True


@dataclass
class ContractState:
    """Kalshi contract state."""
    market_id: str
    asset: str
    side: str  # "yes" or "no"
    strike_price: float  # USD
    mid_price_cents: int
    time_to_expiry_seconds: float
    orderbook: Optional[OrderbookSnapshot] = None


@dataclass
class EdgeResult:
    """Result of edge computation."""
    edge: float  # Raw probability edge (q - π)
    edge_risk_adjusted: float  # Edge normalized by volatility
    edge_slippage_adjusted: float  # Edge after slippage penalty
    edge_fee_adjusted: float  # Edge after slippage and fees
    model_win_prob: float  # q_a(t)
    market_implied_prob: float  # π_a(t)
    spot_ref: SpotReference
    confidence: float
    metadata: Dict
    # Additional cost breakdown for logging
    raw_edge_cents: float  # Raw edge in cents (q_cents - price_cents)
    spread_cost_cents: float  # Half-spread cost in cents
    fee_cost_cents: float  # Fee cost in cents
    net_edge_cents: float  # Net edge in cents after spread and fees
    ev_per_contract_cents: float  # P1-FIX3: Expected value per contract in cents
    # Edge/lag ratio metrics for speed-adjusted edge screening
    lag_ms: Optional[float] = None  # Effective spot-to-book lag in milliseconds
    edge_lag_ratio: Optional[float] = None  # Edge per second of lag (edge_fee_adjusted / (lag_ms / 1000))
    # Spot-strike distance metrics for OTM filtering
    dist_pct: Optional[float] = None  # Signed distance percentage (strike - spot) / spot * 100
    dist_abs_pct: Optional[float] = None  # Absolute distance percentage


class PerAssetCalibration:
    """
    Per-asset spot-contract mapping calibration.
    
    This structure holds the empirically-fit mapping f_a(S, strike, τ) → q_a(t)
    for each asset, derived from historical RTI and contract outcomes.
    """
    
    def __init__(self, profile_config: Optional[Dict] = None):
        """
        Initialize per-asset calibration.
        
        Args:
            profile_config: Optional dict with edge/lag filter config from profile.
                          If provided, overrides hardcoded defaults.
        """
        # Per-asset calibration parameters (to be fitted from historical data)
        self.calibrations: Dict[str, Dict] = {
            "BTC": {
                "base_win_rate": 0.5,
                "spot_sensitivity": 0.1,  # How much win prob changes per 1% spot move
                "time_decay": 0.05,  # How win prob decays over time
                "vol_adjustment": 1.0,  # Volatility adjustment factor
                "rti_bias_cents": 0,  # Systematic bias vs CFB RTI
            },
            "ETH": {
                "base_win_rate": 0.5,
                "spot_sensitivity": 0.12,
                "time_decay": 0.06,
                "vol_adjustment": 1.1,
                "rti_bias_cents": 0,
            },
            "SOL": {
                "base_win_rate": 0.5,
                "spot_sensitivity": 0.15,
                "time_decay": 0.08,
                "vol_adjustment": 1.3,
                "rti_bias_cents": 0,
            },
            "XRP": {
                "base_win_rate": 0.5,
                "spot_sensitivity": 0.18,
                "time_decay": 0.09,
                "vol_adjustment": 1.4,
                "rti_bias_cents": 0,
            },
            "DOGE": {
                "base_win_rate": 0.5,
                "spot_sensitivity": 0.20,
                "time_decay": 0.10,
                "vol_adjustment": 1.5,
                "rti_bias_cents": 0,
            },
        }
        
        # Per-asset 15m volatility estimates (in RTI terms)
        self.volatility_15m: Dict[str, float] = {
            "BTC": 0.02,  # 2% 15m vol
            "ETH": 0.025,
            "SOL": 0.035,
            "XRP": 0.04,
            "DOGE": 0.05,
        }
        
        # Per-asset slippage models (expected slippage in cents per contract)
        self.slippage_models: Dict[str, Dict] = {
            "BTC": {"base_slippage_cents": 1, "depth_factor": 0.01},
            "ETH": {"base_slippage_cents": 1, "depth_factor": 0.015},
            "SOL": {"base_slippage_cents": 2, "depth_factor": 0.02},
            "XRP": {"base_slippage_cents": 2, "depth_factor": 0.025},
            "DOGE": {"base_slippage_cents": 3, "depth_factor": 0.03},
        }
        
        # Kalshi fee schedule (per contract in cents)
        # Kalshi charges 2% of notional for taker orders, 1% for maker orders
        # For 1 USD payoff contracts, this is 2 cents (taker) or 1 cent (maker)
        self.fee_schedule: Dict[str, float] = {
            "maker_fee_cents": 1.0,  # 1% of $1 = 1 cent
            "taker_fee_cents": 2.0,  # 2% of $1 = 2 cents
        }
        
        # Per-asset minimum edge/lag ratio thresholds (edge per second of lag)
        # Higher values = more conservative (require larger edge relative to lag)
        # BTC/ETH are more efficient, so require higher edge/lag ratio
        # SOL/XRP/DOGE are less efficient, allow lower edge/lag ratio
        if profile_config and profile_config.get('min_edge_lag_ratio'):
            self.min_edge_lag_ratio = profile_config['min_edge_lag_ratio']
        else:
            self.min_edge_lag_ratio = {
                "BTC": 0.02,   # 2 cents per second of lag
                "ETH": 0.02,
                "SOL": 0.03,
                "XRP": 0.03,
                "DOGE": 0.04,
            }
        
        # Per-asset edge/lag filter safety switch (1 = enabled, 0 = disabled)
        # Allows quick per-asset disable without code changes
        if profile_config and profile_config.get('edge_lag_filter_enabled'):
            self.edge_lag_filter_enabled = profile_config['edge_lag_filter_enabled']
        else:
            self.edge_lag_filter_enabled = {
                "BTC": 1,
                "ETH": 1,
                "SOL": 1,
                "XRP": 1,
                "DOGE": 1,
            }
        
        # Cold-start warmup: minimum lag samples before filter is active
        if profile_config and profile_config.get('cold_start_min_samples'):
            self.cold_start_min_samples = profile_config['cold_start_min_samples']
        else:
            self.cold_start_min_samples = 100
    
    def get_calibration(self, asset: str) -> Dict:
        """Get calibration parameters for an asset."""
        return self.calibrations.get(asset, self.calibrations["BTC"])
    
    def get_volatility(self, asset: str) -> float:
        """Get 15m volatility estimate for an asset."""
        return self.volatility_15m.get(asset, 0.02)
    
    def get_slippage_model(self, asset: str) -> Dict:
        """Get slippage model for an asset."""
        return self.slippage_models.get(asset, self.slippage_models["BTC"])
    
    def get_fee_schedule(self) -> Dict[str, float]:
        """Get Kalshi fee schedule."""
        return self.fee_schedule


class UnifiedEdgeComputer:
    """
    Unified cross-asset edge computation.
    
    This is the main entry point for computing edge across all assets.
    It ensures edge is a strict, cross-asset comparable quantity.
    """
    
    def __init__(self, calibration: Optional[PerAssetCalibration] = None):
        self.calibration = calibration or PerAssetCalibration()
        self.alignment_threshold_cents = 50  # Trigger degraded mode if gap > 50 cents

        # DELETED: Edge thresholds - now handled by profile edge_bands (1.25% unified minimum)
        # This module focuses on edge computation, not edge validation
        # UPDATED 2026-07-10: Changed from 4.0 to 1.25 to match moltbook research (BTC base)
        self.min_edge_cents = 1.25
        self.max_spread_pct = 0.70  # Maximum spread as percentage of mid (70%) - adjusted for crypto markets
        # CRITICAL FIX: Load max_spread_cents from profile guardrails_max_spread_cents
        self.max_spread_cents = self._load_max_spread_cents_from_profile()

    def _load_max_spread_cents_from_profile(self) -> int:
        """Load max_spread_cents from profile guardrails configuration.

        Returns:
            max_spread_cents from profile, or 100 as fallback
        """
        try:
            from merid.risk.profiles.crypto_15m_profile import get_active_profile
            profile_adapter = get_active_profile()
            if profile_adapter and hasattr(profile_adapter.profile, 'guardrails_max_spread_cents'):
                return profile_adapter.profile.guardrails_max_spread_cents
        except Exception as e:
            logger.debug("[EDGE-CHECK] Failed to load max_spread_cents from profile: %s, using fallback 100c", e)
        return 100  # Fallback to 100c if profile load fails

    def compute_spread_pct(self, contract: ContractState) -> Optional[float]:
        """
        Compute spread as percentage of mid price.
        
        Uses canonical OrderbookSnapshot from unified_market_state.
        
        Args:
            contract: Contract state with orderbook
        
        Returns:
            Spread as percentage of mid, or None if no orderbook
        """
        if contract.orderbook is None:
            return None
        
        # Use canonical snapshot's spread_cents property
        spread_cents = contract.orderbook.spread_cents
        if spread_cents is None:
            return None
        
        mid_cents = contract.orderbook.mid_cents
        if mid_cents is None or mid_cents == 0:
            return None
        
        spread_pct = spread_cents / mid_cents
        return spread_pct
    
    def check_edge(
        self,
        edge_result: EdgeResult,
        contract: ContractState,
        vol_regime: str = "NORMAL"
    ) -> EdgeCheckResult:
        """
        Check if edge meets thresholds for trading.
        
        This implements the full edge check pipeline:
        1. Spread check (liquidity/quality filter)
        2. Edge check (profitability filter)
        
        Args:
            edge_result: Result from compute_edge()
            contract: Contract state
            vol_regime: Volatility regime (LOW, NORMAL, HIGH, EXTREME)
        
        Returns:
            EdgeCheckResult with pass/fail and detailed reason
        """
        # Extract asset from metadata early (used in multiple checks)
        asset = edge_result.metadata.get("asset")
        
        # Compute spread percentage using canonical snapshot
        spread_pct = self.compute_spread_pct(contract)
        spread_cents = contract.orderbook.spread_cents if contract.orderbook else None
        
        # Get best bid/ask from canonical snapshot (YES-centric)
        best_yes_bid = contract.orderbook.best_yes_bid if contract.orderbook else None
        best_yes_ask = contract.orderbook.best_yes_ask if contract.orderbook else None
        
        # DELETED: Dynamic edge thresholds based on volatility regime
        # Edge validation now handled by profile edge_bands (4-5% watch, 5-7% small, >=7% standard)
        min_edge_cents = self.min_edge_cents
        max_spread_pct = self.max_spread_pct
        
        # Check 1: Spread too wide (liquidity/quality filter)
        if spread_cents is not None and spread_cents > self.max_spread_cents:
            if REJECTION_MONITOR_ENABLED:
                log_edge_check_rejection(
                    asset=asset,
                    reason=f"spread_too_wide: bid={best_yes_bid}c ask={best_yes_ask}c spread={spread_cents}c > {self.max_spread_cents}c threshold",
                    spread_cents=spread_cents,
                    threshold_value=self.max_spread_cents,
                    actual_value=spread_cents,
                )
            return EdgeCheckResult(
                passes=False,
                reason=f"spread_too_wide: bid={best_yes_bid}c ask={best_yes_ask}c spread={spread_cents}c > {self.max_spread_cents}c threshold",
                edge_result=edge_result,
                spread_pct=spread_pct,
                min_edge_cents=min_edge_cents,
                max_spread_pct=max_spread_pct,
            )
        
        # Check 2: Spread percentage too high
        if spread_pct is not None and spread_pct > max_spread_pct:
            if REJECTION_MONITOR_ENABLED:
                log_edge_check_rejection(
                    asset=asset,
                    reason=f"spread_pct_too_high: bid={best_yes_bid}c ask={best_yes_ask}c spread={spread_cents}c ({spread_pct:.1%}) > {max_spread_pct:.1%} threshold",
                    spread_cents=spread_cents,
                    threshold_value=max_spread_pct,
                    actual_value=spread_pct,
                )
            return EdgeCheckResult(
                passes=False,
                reason=f"spread_pct_too_high: bid={best_yes_bid}c ask={best_yes_ask}c spread={spread_cents}c ({spread_pct:.1%}) > {max_spread_pct:.1%} threshold",
                edge_result=edge_result,
                spread_pct=spread_pct,
                min_edge_cents=min_edge_cents,
                max_spread_pct=max_spread_pct,
            )
        
        # Check 2.75: Minimum contract price floor (longshot trap prevention)
        min_price_cents = 10  # 2026-07-11: Canonical price band (10c) - aligned with GlobalSlotAllocator
        try:
            from merid.risk.profiles.crypto_15m_profile import get_active_profile
            profile_adapter = get_active_profile()
            if profile_adapter and hasattr(profile_adapter.profile, 'guardrails_min_contract_price_cents'):
                min_price_cents = profile_adapter.profile.guardrails_min_contract_price_cents
        except Exception as e:
            logger.debug("[EDGE-CHECK] Failed to load min_contract_price_cents from profile: %s, using default 10c", e)
        
        # Check 2.76: Maximum contract price ceiling (low-profit trap prevention)
        # 2026-07-11: Canonical price band (50c) - aligned with GlobalSlotAllocator
        max_price_cents = 50  # Default fallback (50 cents / $0.50) - aligned with profile
        try:
            from merid.risk.profiles.crypto_15m_profile import get_active_profile
            profile_adapter = get_active_profile()
            if profile_adapter and hasattr(profile_adapter.profile, 'guardrails_max_contract_price_cents'):
                max_price_cents = profile_adapter.profile.guardrails_max_contract_price_cents
        except Exception as e:
            logger.debug("[EDGE-CHECK] Failed to load max_contract_price_cents from profile: %s, using default 50c", e)
        
        # Get contract price from mid_price_cents (ContractState only has mid_price_cents)
        # For YES contracts, mid_price_cents is the YES price
        # For NO contracts, mid_price_cents is the NO price
        contract_price_cents = contract.mid_price_cents
        
        if contract_price_cents < min_price_cents:
            if REJECTION_MONITOR_ENABLED:
                log_edge_check_rejection(
                    asset=asset,
                    reason=f"longshot_trap_price_too_low: asset={asset} side={contract.side} price={contract_price_cents}c < {min_price_cents}c threshold (deep OTM longshot rejected)",
                    threshold_value=min_price_cents,
                    actual_value=contract_price_cents,
                )
            return EdgeCheckResult(
                passes=False,
                reason=f"longshot_trap_price_too_low: asset={asset} side={contract.side} price={contract_price_cents}c < {min_price_cents}c threshold (deep OTM longshot rejected)",
                edge_result=edge_result,
                spread_pct=spread_pct,
                min_edge_cents=min_edge_cents,
                max_spread_pct=max_spread_pct,
            )
        
        if contract_price_cents > max_price_cents:
            if REJECTION_MONITOR_ENABLED:
                log_edge_check_rejection(
                    asset=asset,
                    reason=f"low_profit_trap_price_too_high: asset={asset} side={contract.side} price={contract_price_cents}c > {max_price_cents}c threshold (low-profit trade rejected - payout only {100 - contract_price_cents}¢)",
                    threshold_value=max_price_cents,
                    actual_value=contract_price_cents,
                )
            return EdgeCheckResult(
                passes=False,
                reason=f"low_profit_trap_price_too_high: asset={asset} side={contract.side} price={contract_price_cents}c > {max_price_cents}c threshold (low-profit trade rejected - payout only {100 - contract_price_cents}¢)",
                edge_result=edge_result,
                spread_pct=spread_pct,
                min_edge_cents=min_edge_cents,
                max_spread_pct=max_spread_pct,
            )
        
        # Check 2.5: Depth scaling with order size (microstructure trap prevention)
        if contract.orderbook is not None:
            depth_multiplier = 3.0  # Default fallback
            try:
                from merid.risk.profiles.crypto_15m_profile import get_active_profile
                profile_adapter = get_active_profile()
                if profile_adapter and hasattr(profile_adapter.profile, 'guardrails_depth_size_multiplier'):
                    depth_multiplier = profile_adapter.profile.guardrails_depth_size_multiplier
            except Exception as e:
                logger.debug("[EDGE-CHECK] Failed to load depth_size_multiplier from profile: %s, using default 3.0", e)
            
            # Check depth at target price using canonical microstructure utility
            order_size = edge_result.metadata.get("order_size", 1)
            required_depth = int(depth_multiplier * order_size)
            
            # Use canonical microstructure utility for depth calculation
            if contract.orderbook:
                micro = compute_side_microstructure(
                    contract.orderbook,
                    side=contract.side,
                    size=order_size,
                    depth_window_cents=10,
                )
                
                # Check fillability for the requested size
                if contract.side == "yes" and not micro.fillable_yes:
                    return EdgeCheckResult(
                        passes=False,
                        reason=f"microstructure_trap_insufficient_depth: asset={asset} side=yes depth_yes_at_best={micro.depth_yes_at_best} depth_yes_within_10c={micro.depth_yes_within_10c} < required={required_depth} (order_size={order_size} multiplier={depth_multiplier})",
                        edge_result=edge_result,
                        spread_pct=spread_pct,
                        min_edge_cents=min_edge_cents,
                        max_spread_pct=max_spread_pct,
                    )
                elif contract.side == "no" and not micro.fillable_no:
                    return EdgeCheckResult(
                        passes=False,
                        reason=f"microstructure_trap_insufficient_depth: asset={asset} side=no depth_no_at_best={micro.depth_no_at_best} depth_no_within_10c={micro.depth_no_within_10c} < required={required_depth} (order_size={order_size} multiplier={depth_multiplier})",
                        edge_result=edge_result,
                        spread_pct=spread_pct,
                        min_edge_cents=min_edge_cents,
                        max_spread_pct=max_spread_pct,
                    )
        
        # Check 3: Time trap prevention (entry window narrowing)
        # Aligned with TTE regimes from risk.tte_regime:
        # - NORMAL: > 10 minutes (allow entry)
        # - APPROACHING: 5-10 minutes (allow entry with tighter constraints)
        # - CRITICAL: 2-5 minutes (allow entry with very tight constraints)
        # - TERMINAL: < 2 minutes (block entry)
        time_to_expiry_min = contract.time_to_expiry_seconds / 60.0
        
        # Get entry window bounds from profile (aligned with TTE regime thresholds)
        # Default: max_entry = 12min (NORMAL regime), min_entry = 2min (TERMINAL threshold)
        max_entry_mins = 12.0  # Default fallback (aligned with TTE NORMAL > 10min)
        min_entry_mins = 2.0   # Default fallback (aligned with TTE TERMINAL < 2min)
        try:
            from merid.risk.profiles.crypto_15m_profile import get_active_profile
            profile_adapter = get_active_profile()
            if profile_adapter:
                if hasattr(profile_adapter.profile, 'guardrails_max_entry_mins'):
                    max_entry_mins = profile_adapter.profile.guardrails_max_entry_mins
                if hasattr(profile_adapter.profile, 'guardrails_min_entry_mins'):
                    min_entry_mins = profile_adapter.profile.guardrails_min_entry_mins
        except Exception as e:
            logger.debug("[EDGE-CHECK] Failed to load entry window bounds from profile: %s, using defaults", e)
        
        # Check if too early in window (exposed to drift with poor reward)
        # This aligns with TTE NORMAL regime (>10min, but we cap at 12min for 15m strip)
        if time_to_expiry_min > max_entry_mins:
            return EdgeCheckResult(
                passes=False,
                reason=f"time_trap_too_early: asset={asset} tte={time_to_expiry_min:.1f}min > {max_entry_mins:.1f}min threshold (TTE NORMAL regime, avoid early window exposure)",
                edge_result=edge_result,
                spread_pct=spread_pct,
                min_edge_cents=min_edge_cents,
                max_spread_pct=max_spread_pct,
            )
        
        # Check if too late in window (erratic orderbook behavior)
        # This aligns with TTE TERMINAL regime (<2min, block entry)
        if time_to_expiry_min < min_entry_mins:
            return EdgeCheckResult(
                passes=False,
                reason=f"time_trap_too_late: asset={asset} tte={time_to_expiry_min:.1f}min < {min_entry_mins:.1f}min threshold (TTE TERMINAL regime, avoid erratic orderbook near expiry)",
                edge_result=edge_result,
                spread_pct=spread_pct,
                min_edge_cents=min_edge_cents,
                max_spread_pct=max_spread_pct,
            )
        
        # Check 4: OTM distance filter (spot-strike distance too large)
        if edge_result.dist_abs_pct is not None:
            # Get max distance threshold from profile
            max_dist_pct = 2.0  # Default fallback
            try:
                from merid.risk.profiles.crypto_15m_profile import get_active_profile
                profile_adapter = get_active_profile()
                if profile_adapter and hasattr(profile_adapter.profile, 'guardrails_max_dist_pct_trade'):
                    max_dist_pct = profile_adapter.profile.guardrails_max_dist_pct_trade
            except Exception as e:
                logger.debug("[EDGE-CHECK] Failed to load max_dist_pct_trade from profile: %s, using default 2.0%%", e)
            
            # Adjust threshold based on volatility regime
            if vol_regime == "EXTREME":
                max_dist_pct *= 1.5  # Allow slightly wider distance in extreme vol
            elif vol_regime == "HIGH":
                max_dist_pct *= 1.2
            elif vol_regime == "LOW":
                max_dist_pct *= 0.8  # Tighten in low vol
            
            if edge_result.dist_abs_pct > max_dist_pct:
                return EdgeCheckResult(
                    passes=False,
                    reason=f"otm_distance_too_large: asset={asset} dist_abs_pct={edge_result.dist_abs_pct:.2f}% > {max_dist_pct:.2f}% threshold (spot={edge_result.spot_ref.price_usd:.2f} strike={edge_result.metadata.get('strike'):.2f})",
                    edge_result=edge_result,
                    spread_pct=spread_pct,
                    min_edge_cents=min_edge_cents,
                    max_spread_pct=max_spread_pct,
                )
            
            # Three-dimensional policy: edge + distance + TTE
            # Farther OTM requires stronger edge
            time_to_expiry_min = contract.time_to_expiry_seconds / 60.0
            
            # Distance-band-aware edge thresholds
            if edge_result.dist_abs_pct <= 0.5:
                # Close to spot: require modest edge
                min_edge_by_distance = 0.5  # 0.5% edge
            elif edge_result.dist_abs_pct <= 1.5:
                # Moderate distance: require stronger edge
                min_edge_by_distance = 1.5  # 1.5% edge
            else:
                # Far OTM: require very strong edge (will likely fail max_dist_pct check anyway)
                min_edge_by_distance = 2.5  # 2.5% edge
            
            # Adjust for time to expiry (less time = require stronger edge)
            if time_to_expiry_min < 5:
                min_edge_by_distance *= 1.5  # Tighten significantly near expiry
            elif time_to_expiry_min < 10:
                min_edge_by_distance *= 1.2  # Tighten moderately
            
            # Convert to cents for comparison
            min_edge_by_distance_cents = min_edge_by_distance
            
            if edge_result.net_edge_cents < min_edge_by_distance_cents:
                return EdgeCheckResult(
                    passes=False,
                    reason=f"otm_edge_insufficient: asset={asset} dist_abs_pct={edge_result.dist_abs_pct:.2f}% tte={time_to_expiry_min:.1f}min requires edge>={min_edge_by_distance_cents:.2f}c but net_edge={edge_result.net_edge_cents:.2f}c (distance-band policy)",
                    edge_result=edge_result,
                    spread_pct=spread_pct,
                    min_edge_cents=min_edge_by_distance_cents,
                    max_spread_pct=max_spread_pct,
                )
        
        # Check 5: Experimental slice - price band guard (45c-60c for BTC/ETH)
        # Based on PnL audit, restrict to mid-price range for experimental testing
        experimental_price_band_enabled = False
        try:
            from merid.risk.profiles.crypto_15m_profile import get_active_profile
            profile_adapter = get_active_profile()
            if profile_adapter and hasattr(profile_adapter.profile, 'guardrails_experimental_price_band_enabled'):
                experimental_price_band_enabled = profile_adapter.profile.guardrails_experimental_price_band_enabled
        except Exception as e:
            logger.debug("[EDGE-CHECK] Failed to load experimental_price_band_enabled from profile: %s", e)
        
        if experimental_price_band_enabled and asset in ["BTC", "ETH"]:
            min_price_cents = 45
            max_price_cents = 60
            try:
                if profile_adapter:
                    if hasattr(profile_adapter.profile, 'guardrails_experimental_min_price_cents'):
                        min_price_cents = profile_adapter.profile.guardrails_experimental_min_price_cents
                    if hasattr(profile_adapter.profile, 'guardrails_experimental_max_price_cents'):
                        max_price_cents = profile_adapter.profile.guardrails_experimental_max_price_cents
            except Exception as e:
                logger.debug("[EDGE-CHECK] Failed to load experimental price band thresholds from profile: %s", e)
            
            if price_cents < min_price_cents or price_cents > max_price_cents:
                return EdgeCheckResult(
                    passes=False,
                    reason=f"experimental_price_band: asset={asset} price={price_cents}c outside experimental range [{min_price_cents}c-{max_price_cents}c]",
                    edge_result=edge_result,
                    spread_pct=spread_pct,
                    min_edge_cents=min_edge_cents,
                    max_spread_pct=max_spread_pct,
                )
        
        # Check 6: Experimental slice - TTE band guard (4-7min window)
        experimental_tte_band_enabled = False
        try:
            from merid.risk.profiles.crypto_15m_profile import get_active_profile
            profile_adapter = get_active_profile()
            if profile_adapter and hasattr(profile_adapter.profile, 'guardrails_experimental_tte_band_enabled'):
                experimental_tte_band_enabled = profile_adapter.profile.guardrails_experimental_tte_band_enabled
        except Exception as e:
            logger.debug("[EDGE-CHECK] Failed to load experimental_tte_band_enabled from profile: %s", e)
        
        if experimental_tte_band_enabled and asset in ["BTC", "ETH"]:
            min_tte_min = 4.0
            max_tte_min = 7.0
            try:
                if profile_adapter:
                    if hasattr(profile_adapter.profile, 'guardrails_experimental_min_tte_min'):
                        min_tte_min = profile_adapter.profile.guardrails_experimental_min_tte_min
                    if hasattr(profile_adapter.profile, 'guardrails_experimental_max_tte_min'):
                        max_tte_min = profile_adapter.profile.guardrails_experimental_max_tte_min
            except Exception as e:
                logger.debug("[EDGE-CHECK] Failed to load experimental TTE band thresholds from profile: %s", e)
            
            if time_to_expiry_min < min_tte_min or time_to_expiry_min > max_tte_min:
                return EdgeCheckResult(
                    passes=False,
                    reason=f"experimental_tte_band: asset={asset} tte={time_to_expiry_min:.1f}min outside experimental range [{min_tte_min}min-{max_tte_min}min]",
                    edge_result=edge_result,
                    spread_pct=spread_pct,
                    min_edge_cents=min_edge_cents,
                    max_spread_pct=max_spread_pct,
                )
        
        # Check 7: Microstructure trap prevention (max effective spread rule)
        # Even if edge is positive, reject if spread is too wide for the given edge
        if spread_cents is not None:
            # Get max spread for edge from profile
            max_spread_for_edge = 30  # Default fallback (2026-07-10: OPTIMIZED to 30c - harmonizes with 10c-50c entry price sweet spot)
            try:
                from merid.risk.profiles.crypto_15m_profile import get_active_profile
                profile_adapter = get_active_profile()
                if profile_adapter and hasattr(profile_adapter.profile, 'guardrails_max_spread_for_edge'):
                    edge_pct_map = profile_adapter.profile.guardrails_max_spread_for_edge
                    # Convert net_edge_cents to percentage for lookup
                    edge_pct = edge_result.net_edge_cents
                    if edge_pct < 1.0:
                        max_spread_for_edge = edge_pct_map.get("1.0", 5)
                    elif edge_pct < 2.0:
                        max_spread_for_edge = edge_pct_map.get("2.0", 10)
                    else:
                        max_spread_for_edge = edge_pct_map.get("default", 10)  # 2026-07-09 optimized from 20c
            except Exception as e:
                logger.debug("[EDGE-CHECK] Failed to load max_spread_for_edge from profile: %s, using default 10c", e)
            
            if spread_cents > max_spread_for_edge:
                return EdgeCheckResult(
                    passes=False,
                    reason=f"microstructure_trap_spread_too_wide: asset={asset} spread={spread_cents}c > {max_spread_for_edge}c threshold for edge={edge_result.net_edge_cents:.2f}c (bid={best_yes_bid}c ask={best_yes_ask}c)",
                    edge_result=edge_result,
                    spread_pct=spread_pct,
                    min_edge_cents=min_edge_cents,
                    max_spread_pct=max_spread_pct,
                )
        
        # Check 6: Net edge insufficient (profitability filter)
        if edge_result.net_edge_cents < min_edge_cents:
            if REJECTION_MONITOR_ENABLED:
                log_edge_check_rejection(
                    asset=asset,
                    reason=f"edge_insufficient: bid={best_yes_bid}c ask={best_yes_ask}c spread={spread_cents}c ({spread_pct:.1%}) q={edge_result.model_win_prob*100:.0f}c raw_edge={edge_result.raw_edge_cents:.2f}c spread_cost={edge_result.spread_cost_cents:.2f}c fees={edge_result.fee_cost_cents:.2f}c net_edge={edge_result.net_edge_cents:.2f}c < {min_edge_cents:.2f}c threshold",
                    edge_cents=edge_result.net_edge_cents,
                    spread_cents=spread_cents,
                    threshold_value=min_edge_cents,
                    actual_value=edge_result.net_edge_cents,
                )
            return EdgeCheckResult(
                passes=False,
                reason=f"edge_insufficient: bid={best_yes_bid}c ask={best_yes_ask}c spread={spread_cents}c ({spread_pct:.1%}) q={edge_result.model_win_prob*100:.0f}c raw_edge={edge_result.raw_edge_cents:.2f}c spread_cost={edge_result.spread_cost_cents:.2f}c fees={edge_result.fee_cost_cents:.2f}c net_edge={edge_result.net_edge_cents:.2f}c < {min_edge_cents:.2f}c threshold",
                edge_result=edge_result,
                spread_pct=spread_pct,
                min_edge_cents=min_edge_cents,
                max_spread_pct=max_spread_pct,
            )
        
        # BYPASS: Regime cooldown disabled for kalshi_crypto_15m_v2 - use risk envelope drawdown only
        # This check is now handled by profile YAML regime_cooldown_enabled flag
        regime_cooldown_enabled = False
        try:
            from merid.risk.profiles.crypto_15m_profile import get_active_profile
            profile_adapter = get_active_profile()
            if profile_adapter and hasattr(profile_adapter.profile, 'guardrails_regime_cooldown_enabled'):
                regime_cooldown_enabled = profile_adapter.profile.guardrails_regime_cooldown_enabled
        except Exception as e:
            logger.debug("[EDGE-CHECK] Failed to load regime_cooldown_enabled from profile: %s", e)
        
        # Skip regime cooldown check if disabled (bypass for kalshi_crypto_15m_v2)
        if not regime_cooldown_enabled:
            logger.debug("[EDGE-CHECK] Regime cooldown disabled - skipping performance check for asset=%s", asset)
        else:
            # Check recent trade performance for this asset
            try:
                from merid.prediction.agent_performance_tracker import get_agent_performance_tracker
                tracker = get_agent_performance_tracker()
                
                # Get cooldown thresholds from profile
                min_trades = 20  # Default fallback
                min_winrate = 0.4  # Default fallback
                max_loss_pct = 0.1  # Default fallback
                
                try:
                    if profile_adapter:
                        if hasattr(profile_adapter.profile, 'guardrails_regime_cooldown_min_trades'):
                            min_trades = profile_adapter.profile.guardrails_regime_cooldown_min_trades
                        if hasattr(profile_adapter.profile, 'guardrails_regime_cooldown_min_winrate'):
                            min_winrate = profile_adapter.profile.guardrails_regime_cooldown_min_winrate
                        if hasattr(profile_adapter.profile, 'guardrails_regime_cooldown_max_loss_pct'):
                            max_loss_pct = profile_adapter.profile.guardrails_regime_cooldown_max_loss_pct
                except Exception as e:
                    logger.debug("[EDGE-CHECK] Failed to load regime cooldown thresholds from profile: %s", e)
                
                # Get recent performance for this asset
                asset_perf = tracker.get_asset_performance(asset, min_trades=min_trades)
                
                # Check if we have sufficient data and if performance is poor
                if asset_perf['sufficient_data']:
                    win_rate = asset_perf['win_rate']
                    total_pnl = float(asset_perf['total_pnl_usd'])
                    
                    # Calculate loss percentage (negative PnL / total risk)
                    # Simplified: use absolute PnL as loss percentage
                    loss_pct = abs(total_pnl) / max(abs(total_pnl), 1.0) if total_pnl < 0 else 0.0
                    
                    # Reject if win rate below threshold OR loss exceeds threshold
                    if win_rate < min_winrate or loss_pct > max_loss_pct:
                        reject_reason = (
                            f"[REGIME-COOLDOWN] asset={asset} win_rate={win_rate:.2f} "
                            f"(min={min_winrate:.2f}) loss_pct={loss_pct:.2f} "
                            f"(max={max_loss_pct:.2f}) trades={asset_perf['total_trades']}"
                        )
                        logger.warning(reject_reason)
                        return EdgeCheckResult(
                            passes=False,
                            reason=reject_reason,
                            spread_pct=spread_pct,
                            edge_cents=edge_cents,
                            min_edge_cents=min_edge_cents,
                            max_spread_cents=max_spread_cents,
                        )
                
                logger.debug(
                    "[EDGE-CHECK] Regime cooldown check passed for asset=%s (win_rate=%.2f trades=%d)",
                    asset, asset_perf['win_rate'], asset_perf['total_trades']
                )
                
            except Exception as e:
                logger.error("[EDGE-CHECK] Regime cooldown check failed for asset=%s: %s", asset, e, exc_info=True)
        
        # Check 7: Edge/lag ratio insufficient (speed-adjusted edge screening)
        
        # Validate asset is present in metadata
        if not asset:
            logger.warning("[EDGE-CHECK] Missing asset in EdgeResult metadata, skipping edge/lag ratio check")
            # Skip Check 4 - cannot determine which asset to apply thresholds to
        else:
            # Safety switch: check if filter is enabled for this asset
            filter_enabled = self.calibration.edge_lag_filter_enabled.get(asset, 1)
            if filter_enabled == 0:
                logger.debug("[EDGE-CHECK] edge/lag filter disabled for asset=%s via safety switch", asset)
                # Skip Check 4 entirely
            else:
                min_ratio = self.calibration.min_edge_lag_ratio.get(asset, 0.02)
                
                # Adjust threshold based on volatility regime
                if vol_regime in ("HIGH", "EXTREME"):
                    min_ratio *= 1.5  # Tighten in high vol
                elif vol_regime == "LOW":
                    min_ratio *= 0.8  # Relax in low vol
                
                # Cold-start fallback: skip Check 4 if lag data is not warm enough
                lag_sample_count = None
                if edge_result.lag_ms is None or edge_result.edge_lag_ratio is None:
                    # No lag data available - check if we have enough samples
                    try:
                        from merid.market_data.lag_tracker import get_lag_tracker
                        lag_tracker = get_lag_tracker()
                        stats = lag_tracker.get_stats(asset)
                        lag_sample_count = stats.get("count", 0) if stats else 0
                    except Exception as e:
                        logger.debug("[EDGE-CHECK] Failed to get lag stats for cold-start check: %s", e)
                        lag_sample_count = 0
                    
                    if lag_sample_count < 100:
                        # Cold start: skip Check 4 but log warning
                        logger.warning(
                            "[EDGE-CHECK] COLD-START: asset=%s lag_sample_count=%d < 100, skipping edge/lag ratio check (will enable after warmup)",
                            asset, lag_sample_count
                        )
                        # Proceed to pass - don't block trading during warmup
                    else:
                        # We have samples but edge_lag_ratio is None - this is unexpected
                        logger.warning(
                            "[EDGE-CHECK] UNEXPECTED: asset=%s has %d lag samples but edge_lag_ratio is None, skipping Check 4",
                            asset, lag_sample_count
                        )
                else:
                    # Lag data available - apply Check 4
                    if edge_result.edge_lag_ratio < min_ratio:
                        return EdgeCheckResult(
                            passes=False,
                            reason=f"edge_lag_ratio_insufficient: asset={asset} edge_lag_ratio={edge_result.edge_lag_ratio:.4f} lag_ms={edge_result.lag_ms:.1f} < {min_ratio:.4f} threshold (regime={vol_regime})",
                            edge_result=edge_result,
                            spread_pct=spread_pct,
                            min_edge_cents=min_edge_cents,
                            max_spread_pct=max_spread_pct,
                        )
        
        # All checks passed
        # Format detailed edge breakdown for logging using canonical snapshot
        edge_details = (
            f"bid={best_yes_bid}c ask={best_yes_ask}c spread={spread_cents}c ({spread_pct:.1%}) "
            f"q={edge_result.model_win_prob*100:.0f}c raw_edge={edge_result.raw_edge_cents:.2f}c "
            f"spread_cost={edge_result.spread_cost_cents:.2f}c fees={edge_result.fee_cost_cents:.2f}c "
            f"net_edge={edge_result.net_edge_cents:.2f}c >= min_edge={min_edge_cents:.2f}c -> OK"
        )
        
        return EdgeCheckResult(
            passes=True,
            reason=edge_details,
            edge_result=edge_result,
            spread_pct=spread_pct,
            min_edge_cents=min_edge_cents,
            max_spread_pct=max_spread_pct,
        )
    
    def compute_model_win_prob(
        self,
        asset: str,
        spot_ref: SpotReference,
        contract: ContractState
    ) -> float:
        """
        Compute model win probability q_a(t) = P(settlement_event_true | current_spot, time_to_expiry, vol, microstructure_state).
        
        This is explicitly anchored to Kalshi's settlement mechanism:
        - Kalshi crypto contracts settle on a 60-second average of CFB RTIs around event time
        - For "BTC > X in 15 minutes", we care about the distribution of the 60-second RTI average
        - The model incorporates settlement variance to account for RTI averaging uncertainty
        
        Args:
            asset: Asset symbol (BTC, ETH, etc.)
            spot_ref: CFB-anchored spot reference
            contract: Contract state with strike_price, side, time_to_expiry_seconds
        
        Returns:
            Model win probability q_a(t) in [0, 1]
        """
        cal = self.calibration.get_calibration(asset)
        
        # Handle missing spot price
        if spot_ref.price_usd is None:
            # Default to 50% probability when spot price is unavailable
            return 0.5
        
        # Compute spot move relative to strike (in price units, not percentage)
        spot_move = spot_ref.price_usd - contract.strike_price
        
        # Compute time decay factor (0 at expiry, 1 at start)
        time_decay_factor = min(1.0, contract.time_to_expiry_seconds / 900.0)  # 15 min = 900s
        
        # Get volatility for settlement variance estimation
        vol = self.calibration.get_volatility(asset)
        
        # Estimate settlement variance (60-RTI mean variance)
        # This accounts for the fact that settlement is an average, not a single tick
        try:
            from merid.prediction.risk.settlement_risk_model import estimate_settlement_variance
            settlement_variance = estimate_settlement_variance(
                asset=asset,
                horizon_seconds=contract.time_to_expiry_seconds,
                current_rti_vol=vol,
            )
            # Convert variance to standard deviation
            settlement_std = math.sqrt(settlement_variance)
        except Exception as e:
            logger.debug("[MODEL-WIN-PROB] Failed to estimate settlement variance for asset=%s: %s", asset, e)
            settlement_std = 0.0
        
        # Compute probability using Gaussian approximation
        # P(settlement > strike) = P(spot + move > strike) = P(move > strike - spot)
        # For side="yes" (e.g., UP contract): win if settlement > strike
        # For side="no" (e.g., DOWN contract): win if settlement < strike
        
        # Z-score: (spot - strike) / std
        # If std is 0 or None (no variance), use deterministic threshold
        if settlement_std is not None and settlement_std > 0:
            z_score = spot_move / settlement_std
            # Gaussian CDF approximation (error function)
            # For side="yes": P(Z > -z) = 0.5 * (1 + erf(z / sqrt(2)))
            # For side="no": P(Z < z) = 0.5 * (1 + erf(-z / sqrt(2)))
            if contract.side == "yes":
                # YES wins if settlement > strike (spot_move > 0)
                q = 0.5 * (1.0 + math.erf(z_score / math.sqrt(2)))
            else:  # side == "no"
                # NO wins if settlement < strike (spot_move < 0)
                q = 0.5 * (1.0 + math.erf(-z_score / math.sqrt(2)))
        else:
            # No variance: deterministic based on spot vs strike
            if contract.side == "yes":
                q = 1.0 if spot_move > 0 else 0.0
            else:
                q = 1.0 if spot_move < 0 else 0.0
        
        # Apply time decay adjustment (uncertainty increases as expiry approaches)
        # This accounts for the fact that longer time horizons have more variance
        time_adjustment = (1.0 - time_decay_factor) * cal["time_decay"]
        if contract.side == "yes":
            q -= time_adjustment
        else:
            q += time_adjustment
        
        # Clamp to [0, 1]
        q = max(0.0, min(1.0, q))
        
        logger.debug(
            "[MODEL-WIN-PROB] asset=%s spot=%.2f strike=%.2f move=%.2f side=%s vol=%.4f std=%.4f z=%.2f q=%.3f",
            asset, spot_ref.price_usd, contract.strike_price, spot_move,
            contract.side, vol, settlement_std, z_score if settlement_std > 0 else 0.0, q
        )
        
        return q
    
    def compute_market_implied_prob(self, contract: ContractState) -> float:
        """
        Compute market-implied win probability π_a(t) from contract price.
        
        Args:
            contract: Contract state
        
        Returns:
            Market-implied win probability π_a(t) in [0, 1]
        """
        if contract.mid_price_cents is None:
            return 0.5  # Default to 50% when price is unavailable
        pi = contract.mid_price_cents / 100.0
        return max(0.0, min(1.0, pi))
    
    def compute_raw_edge(
        self,
        model_win_prob: float,
        market_implied_prob: float
    ) -> float:
        """
        Compute raw edge = q_a(t) - π_a(t).
        
        This is unified across all assets - edge = 0.03 means the same thing
        for BTC and DOGE.
        
        Args:
            model_win_prob: q_a(t)
            market_implied_prob: π_a(t)
        
        Returns:
            Raw edge in probability space
        """
        edge = model_win_prob - market_implied_prob
        return edge
    
    def compute_risk_adjusted_edge(
        self,
        raw_edge: float,
        asset: str
    ) -> float:
        """
        Compute risk-adjusted edge = edge / σ_a.
        
        This normalizes edge by per-asset volatility, keeping you from
        over-weighting high-vol assets just because their raw price swings are bigger.
        
        Args:
            raw_edge: Raw probability edge
            asset: Asset symbol
        
        Returns:
            Risk-adjusted edge
        """
        vol = self.calibration.get_volatility(asset)
        if vol == 0:
            return raw_edge
        
        edge_risk_adjusted = raw_edge / vol
        return edge_risk_adjusted
    
    def compute_slippage_adjusted_edge(
        self,
        raw_edge: float,
        asset: str,
        contract: ContractState,
        order_size: int = 1
    ) -> Tuple[float, float]:
        """
        Compute slippage-adjusted edge = edge - expected_slippage.
        
        This incorporates order book microstructure and penalizes edge for
        wide spreads and thin books.
        
        Args:
            raw_edge: Raw probability edge
            asset: Asset symbol
            contract: Contract state
            order_size: Order size in contracts
        
        Returns:
            Tuple of (slippage_adjusted_edge, spread_cost_cents)
        """
        if contract.orderbook is None:
            # No orderbook data, return raw edge with zero spread cost
            return raw_edge, 0.0
        
        slippage_model = self.calibration.get_slippage_model(asset)
        
        # Base slippage from spread (half-spread cost for crossing the spread)
        # Use canonical snapshot's spread_cents property
        spread_cents = contract.orderbook.spread_cents if contract.orderbook else 0
        spread_cost_cents = spread_cents / 2.0
        
        # Depth penalty (thin books = more slippage)
        # Use canonical microstructure utility for depth calculation
        if contract.orderbook:
            micro = compute_side_microstructure(
                contract.orderbook,
                side=contract.side,
                size=order_size,
                depth_window_cents=10,
            )
            total_depth = micro.depth_yes_at_best + micro.depth_no_at_best
        else:
            total_depth = 0
        
        depth_penalty = slippage_model["depth_factor"] * (order_size / max(1, total_depth))
        
        # Total expected slippage in cents
        expected_slippage_cents = slippage_model["base_slippage_cents"] + spread_cost_cents + depth_penalty
        
        # Convert to probability space (divide by 100)
        expected_slippage_prob = expected_slippage_cents / 100.0
        
        # Subtract from edge
        edge_slippage_adjusted = raw_edge - expected_slippage_prob
        
        logger.debug(
            "[SLIPPAGE-ADJUSTMENT] asset=%s spread=%dc depth=%d expected_slippage=%.2fc edge=%.3f->%.3f",
            asset, spread_cents, total_depth, expected_slippage_cents,
            raw_edge, edge_slippage_adjusted
        )
        
        return edge_slippage_adjusted, spread_cost_cents
    
    def compute_fee_adjusted_edge(
        self,
        slippage_adjusted_edge: float,
        asset: str,
        contract: ContractState,
        order_size: int = 1,
        order_side: str = "taker"  # "maker" or "taker"
    ) -> Tuple[float, float]:
        """
        Compute fee-adjusted edge = edge - fee_cost.
        
        NOW USES: Canonical Kalshi tiered parabolic fee formula from fees.py
        fee = ceil(rate * C * P * (1-P) * 100)
        where rate = 7% (<100), 5% (100-999), 3% (1000+)
        
        Note: Kalshi fees depend on price and contract count, not explicitly on maker/taker
        in the public docs. The order_side parameter is kept for future flexibility.
        
        TODO: Use actual intended order price (YES/NO limit) instead of mid_price_cents
        when available for more accurate fee estimation.
        
        Args:
            slippage_adjusted_edge: Edge after slippage adjustment
            asset: Asset symbol
            contract: Contract state with price_cents
            order_size: Order size in contracts
            order_side: "maker" or "taker" (kept for future flexibility)
        
        Returns:
            Tuple of (fee_adjusted_edge, fee_cost_cents)
        """
        from merid.event_venues.kalshi.fees import calculate_kalshi_fee_cents
        
        # Use canonical fee formula
        total_fee_cents = calculate_kalshi_fee_cents(
            contracts=order_size,
            price_cents=contract.mid_price_cents,  # NOTE: Using mid_price; actual order price would be more accurate
        )
        fee_cost_cents = total_fee_cents / max(order_size, 1)
        
        # Convert to probability space (divide by 100)
        fee_cost_prob = fee_cost_cents / 100.0
        
        # Subtract from edge
        edge_fee_adjusted = slippage_adjusted_edge - fee_cost_prob
        
        logger.debug(
            "[FEE-ADJUSTMENT] asset=%s side=%s fee=%.2fc (canonical) edge=%.3f->%.3f",
            asset, order_side, fee_cost_cents, slippage_adjusted_edge, edge_fee_adjusted
        )
        
        return edge_fee_adjusted, fee_cost_cents
    
    def compute_latency_buffer(
        self,
        asset: str,
        contract: ContractState,
        order_size: int = 1,
        order_side: str = "taker"
    ) -> float:
        """
        Compute execution-adjusted threshold = lag_buffer + spread + slippage + safety_margin.
        
        This buffer ensures we only trade when edge survives feed lag, spread, slippage, and safety_margin.
        
        Args:
            asset: Asset symbol
            contract: Contract state with orderbook
            order_size: Order size in contracts
            order_side: "maker" or "taker"
        
        Returns:
            Buffer in probability space (0.0 to 1.0)
        """
        # P1: Load calibration config if available
        calibration_config = self._load_calibration_config()
        
        # Conservative defaults (will be overridden by calibration once data is available)
        # These are initial estimates based on typical Kalshi 15m crypto market behavior
        DEFAULT_LAG_BUFFER_TICKS = 1.0  # Expected lag move in ticks
        DEFAULT_SAFETY_MARGIN_TICKS = 0.5  # Safety margin for regime uncertainty
        DEFAULT_SLIPPAGE_TICKS = 0.5  # Expected slippage by size
        
        # Use calibrated latency buffer if available
        if calibration_config and asset in calibration_config.get("assets", {}):
            asset_metrics = calibration_config["assets"][asset]
            # Convert recommended_latency_buffer (seconds) to probability space
            # Assuming 1 second of lag ≈ 0.5 tick = 0.005 probability (conservative estimate)
            # This is a rough conversion - actual relationship depends on volatility
            calibrated_lag_buffer_seconds = asset_metrics.get("recommended_latency_buffer", 0)
            lag_buffer_prob = min(0.05, calibrated_lag_buffer_seconds * 0.005)  # Cap at 5%
            logger.debug(
                "[LATENCY-BUFFER] Using calibrated buffer for %s: %.3fs -> %.3f prob",
                asset, calibrated_lag_buffer_seconds, lag_buffer_prob
            )
        else:
            # Use default tick-based buffer
            lag_buffer_prob = DEFAULT_LAG_BUFFER_TICKS * 0.01
            logger.debug("[LATENCY-BUFFER] Using default buffer for %s", asset)
        
        # Get spread from orderbook
        spread_cents = 0
        if contract.orderbook is not None:
            spread_cents = contract.orderbook.spread_cents if hasattr(contract.orderbook, 'spread_cents') else 0
        
        # Convert spread to probability space (divide by 100)
        spread_prob = spread_cents / 100.0
        
        # Convert tick-based buffers to probability space
        # For Kalshi $1 payoff contracts, 1 tick = 1 cent = 0.01 probability
        safety_margin_prob = DEFAULT_SAFETY_MARGIN_TICKS * 0.01
        slippage_prob = DEFAULT_SLIPPAGE_TICKS * 0.01
        
        # Adjust buffer for maker vs taker
        # Maker orders have slightly lower effective buffer because they improve price
        if order_side == "maker":
            lag_buffer_prob *= 0.8  # Maker gets 20% discount on lag buffer
            slippage_prob *= 0.5  # Maker has less slippage risk
        else:  # taker
            # Taker requires half-spread as additional buffer (crossing the spread)
            lag_buffer_prob += (spread_prob / 2.0)
        
        # Total buffer
        total_buffer = lag_buffer_prob + spread_prob + slippage_prob + safety_margin_prob
        
        logger.debug(
            "[LATENCY-BUFFER] asset=%s side=%s spread=%.2fc lag=%.3f spread=%.3f slippage=%.3f safety=%.3f total=%.3f",
            asset, order_side, spread_cents, lag_buffer_prob, spread_prob, slippage_prob, safety_margin_prob, total_buffer
        )
        
        return total_buffer
    
    def _load_calibration_config(self) -> Optional[Dict[str, Any]]:
        """Load calibration config from file if available.
        
        Returns:
            Calibration config dict or None if not available
        """
        try:
            from pathlib import Path
            config_path = Path("config/feed_lag_calibration.json")
            if not config_path.exists():
                return None
            
            import json
            with open(config_path, "r") as f:
                config = json.load(f)
            
            logger.debug("[LATENCY-BUFFER] Loaded calibration config from %s", config_path)
            return config
        except Exception as e:
            logger.debug("[LATENCY-BUFFER] Failed to load calibration config: %s", e)
            return None
    
    def compute_edge(
        self,
        asset: str,
        spot_ref: SpotReference,
        contract: ContractState,
        order_size: int = 1,
        order_side: str = "taker"  # "maker" or "taker"
    ) -> EdgeResult:
        """
        Compute unified edge for a contract.
        
        This is the main entry point that combines all edge computations.
        
        Args:
            asset: Asset symbol
            spot_ref: CFB-anchored spot reference
            contract: Contract state
            order_size: Order size in contracts
            order_side: "maker" or "taker" (affects fee calculation)
        
        Returns:
            EdgeResult with all edge metrics
        """
        # ASSERTION: Only support 15M crypto assets
        SUPPORTED_15M_CRYPTO_ASSETS = {"BTC", "ETH", "SOL", "XRP", "DOGE"}
        if asset not in SUPPORTED_15M_CRYPTO_ASSETS:
            raise ValueError(
                f"Unified edge only supports 15M crypto assets (BTC/ETH/SOL/XRP/DOGE), got asset={asset}. "
                f"This prevents OTM tightening from affecting other Kalshi products."
            )
        
        # Compute model win probability
        model_win_prob = self.compute_model_win_prob(asset, spot_ref, contract)
        
        # Compute market-implied probability
        market_implied_prob = self.compute_market_implied_prob(contract)
        
        # Compute raw edge
        raw_edge = self.compute_raw_edge(model_win_prob, market_implied_prob)
        
        # Compute raw edge in cents (q_cents - price_cents)
        q_cents = model_win_prob * 100.0
        price_cents = contract.mid_price_cents
        raw_edge_cents = q_cents - price_cents
        
        # CRITICAL DEBUG: Log edge computation details
        logger.info(
            "[EDGE-COMPUTE-DEBUG] asset=%s model_prob=%.3f market_prob=%.3f raw_edge=%.3f q_cents=%.2f price_cents=%.2f raw_edge_cents=%.2f",
            asset, model_win_prob, market_implied_prob, raw_edge, q_cents, price_cents, raw_edge_cents
        )
        
        # Compute risk-adjusted edge
        edge_risk_adjusted = self.compute_risk_adjusted_edge(raw_edge, asset)
        
        # Compute slippage-adjusted edge (returns tuple with spread cost)
        edge_slippage_adjusted, spread_cost_cents = self.compute_slippage_adjusted_edge(
            raw_edge, asset, contract, order_size
        )
        
        # Compute fee-adjusted edge (returns tuple with fee cost)
        edge_fee_adjusted, fee_cost_cents = self.compute_fee_adjusted_edge(
            edge_slippage_adjusted, asset, contract, order_size, order_side
        )
        
        # Compute latency buffer (lag + spread + slippage + safety margin)
        latency_buffer = self.compute_latency_buffer(asset, contract, order_size, order_side)
        
        # Check if raw edge survives latency buffer
        # Only allow trade if raw_edge >= latency_buffer
        edge_passes_latency_buffer = raw_edge >= latency_buffer
        
        # Compute net edge in cents after spread and fees
        net_edge_cents = raw_edge_cents - spread_cost_cents - fee_cost_cents
        
        # P1-FIX3: Compute expected value per contract in cents
        # EV = q * (win_payout) - (1 - q) * (loss_amount)
        # For YES: win_payout = 100 - price_cents - fee_cost_cents, loss = price_cents
        # For NO: win_payout = price_cents - fee_cost_cents, loss = 100 - price_cents
        if contract.side == "yes":
            win_payout_cents = 100 - price_cents - fee_cost_cents
            loss_amount_cents = price_cents
        else:  # side == "no"
            win_payout_cents = price_cents - fee_cost_cents
            loss_amount_cents = 100 - price_cents
        ev_per_contract_cents = model_win_prob * win_payout_cents - (1 - model_win_prob) * loss_amount_cents
        
        # Compute spot-strike distance metrics for OTM filtering
        # For "≥ strike" questions (YES on up): dist_pct = (strike - spot) / spot * 100
        # For "≤ strike" questions (YES on down): dist_pct = (spot - strike) / spot * 100
        # Kalshi 15m crypto markets are directional (Up/Down), so we use:
        # - Up contracts (YES wins if spot > strike): dist_pct = (strike - spot) / spot * 100
        # - Down contracts (YES wins if spot < strike): dist_pct = (spot - strike) / spot * 100
        if spot_ref.price_usd is None or spot_ref.price_usd == 0 or contract.strike_price is None:
            # Handle missing or zero spot price or strike price
            dist_pct = 0.0
        elif contract.side == "yes":
            # Assuming up contract semantics (spot > strike to win)
            dist_pct = (contract.strike_price - spot_ref.price_usd) / spot_ref.price_usd * 100
        else:  # side == "no"
            # Assuming down contract semantics (spot < strike to win, NO wins if spot > strike)
            dist_pct = (spot_ref.price_usd - contract.strike_price) / spot_ref.price_usd * 100
        dist_abs_pct = abs(dist_pct)
        
        # Compute confidence (based on edge magnitude and time to expiry)
        confidence = self._compute_confidence(raw_edge, contract.time_to_expiry_seconds)
        
        # Compute edge/lag ratio using LagTracker
        lag_ms = None
        edge_lag_ratio = None
        try:
            from merid.market_data.lag_tracker import get_lag_tracker
            lag_tracker = get_lag_tracker()
            lag_ms = lag_tracker.get_effective_lag_ms(asset, quantile=0.5)
            if lag_ms is not None and lag_ms > 0:
                # Edge per second of lag (edge_fee_adjusted is in probability units)
                edge_lag_ratio = edge_fee_adjusted / (lag_ms / 1000.0)
                logger.debug(
                    "[EDGE-LAG-RATIO] asset=%s lag_ms=%.2f edge_fee=%.3f ratio=%.3f",
                    asset, lag_ms, edge_fee_adjusted, edge_lag_ratio
                )
        except Exception as e:
            logger.debug("[EDGE-LAG-RATIO] Failed to compute lag ratio for asset=%s: %s", asset, e)
        
        result = EdgeResult(
            edge=raw_edge,
            edge_risk_adjusted=edge_risk_adjusted,
            edge_slippage_adjusted=edge_slippage_adjusted,
            edge_fee_adjusted=edge_fee_adjusted,
            model_win_prob=model_win_prob,
            market_implied_prob=market_implied_prob,
            spot_ref=spot_ref,
            confidence=confidence,
            metadata={
                "asset": asset,
                "side": contract.side,
                "strike": contract.strike_price,
                "price_cents": contract.mid_price_cents,  # For Kelly sizing
                "time_to_expiry": contract.time_to_expiry_seconds,
                "volatility": self.calibration.get_volatility(asset),
                "latency_buffer": latency_buffer,
                "edge_passes_latency_buffer": edge_passes_latency_buffer,
            },
            raw_edge_cents=raw_edge_cents,
            spread_cost_cents=spread_cost_cents,
            fee_cost_cents=fee_cost_cents,
            net_edge_cents=net_edge_cents,
            ev_per_contract_cents=ev_per_contract_cents,  # P1-FIX3
            lag_ms=lag_ms,
            edge_lag_ratio=edge_lag_ratio,
            dist_pct=dist_pct,
            dist_abs_pct=dist_abs_pct,
        )
        
        logger.info(
            "[UNIFIED-EDGE] asset=%s side=%s edge=%.3f edge_r=%.3f edge_slip=%.3f edge_fee=%.3f q=%.3f pi=%.3f conf=%.2f raw_edge_c=%.2f spread_c=%.2f fee_c=%.2f net_c=%.2f dist_pct=%.2f%% dist_abs_pct=%.2f%% lag_buf=%.3f passes_buf=%s",
            asset, contract.side, raw_edge, edge_risk_adjusted, edge_slippage_adjusted, edge_fee_adjusted,
            model_win_prob, market_implied_prob, confidence, raw_edge_cents, spread_cost_cents, fee_cost_cents, net_edge_cents,
            dist_pct, dist_abs_pct, latency_buffer, edge_passes_latency_buffer
        )
        
        return result
    
    def _compute_confidence(self, edge: float, time_to_expiry: float) -> float:
        """
        Compute confidence score based on edge magnitude and time to expiry.
        
        CONFIDENCE FORMULA (2026-07-06 STANDARDIZED):
        confidence = 0.6 × edge_score + 0.4 × time_score
        
        Where:
        - edge_score = min(1.0, abs(edge) / 0.2)  # Normalize edge to [0, 1], max reasonable edge = 20%
        - time_score = min(1.0, time_to_expiry / 900.0)  # Normalize TTE to [0, 1], max = 15 minutes (900s)
        
        RATIONALE:
        - Edge contributes 60% to confidence (primary signal strength indicator)
        - Time to expiry contributes 40% (more time = more opportunity for edge to materialize)
        - Higher edge and more time to expiry = higher confidence
        - Output range: [0.0, 1.0]
        
        ALTERNATIVE FORMULAS (strategy-specific):
        - Momentum_FVG: confidence = 0.5 + (score × 0.1) + (fvg_conf × 0.1)  # Range: 0.5-0.95
        - Price-Based: confidence = 0.5 + 2.0 × distance_from_threshold  # Range: 0.5-0.99
        - Regime Detection: HMM probability  # Range: 0.0-1.0
        
        NOTE: Different strategies use different confidence formulas. This is the unified edge formula.
        """
        # Normalize edge to [0, 1] (assuming max reasonable edge is 0.2)
        edge_score = min(1.0, abs(edge) / 0.2)
        
        # Normalize time to expiry (0 = at expiry, 1 = at start)
        time_score = min(1.0, time_to_expiry / 900.0)
        
        # Combine scores
        confidence = 0.6 * edge_score + 0.4 * time_score
        return confidence
    
    def check_alignment(
        self,
        asset: str,
        spot_ref: SpotReference,
        contract: ContractState
    ) -> Tuple[bool, float]:
        """
        Check alignment between spot reference and contract pricing.
        
        Computes the difference between the spot-ref RTI proxy and the implied
        spot level that would make the market fairly priced.
        
        Args:
            asset: Asset symbol
            spot_ref: CFB-anchored spot reference
            contract: Contract state
        
        Returns:
            (is_aligned, gap_cents) tuple
        """
        # Compute implied spot from contract price
        # This is a simplified calculation - in production, invert the full mapping
        market_implied_prob = self.compute_market_implied_prob(contract)
        cal = self.calibration.get_calibration(asset)
        
        # Reverse the spot adjustment to get implied spot move
        if contract.side == "yes":
            implied_spot_move = (market_implied_prob - cal["base_win_rate"]) / cal["spot_sensitivity"]
        else:
            implied_spot_move = -(market_implied_prob - cal["base_win_rate"]) / cal["spot_sensitivity"]
        
        implied_spot = contract.strike_price * (1 + implied_spot_move)
        
        # Compute gap in cents
        gap_usd = abs(spot_ref.price_usd - implied_spot)
        gap_cents = gap_usd * 100
        
        # Sanity check: if gap is extremely large (> $1000), it's likely a data error
        # Log but don't fail alignment for data errors
        if gap_cents > 100000:  # $1000 threshold
            logger.error(
                "[ALIGNMENT-DATA-ERROR] asset=%s spot=%.2f implied=%.2f gap=%.2fc - likely data error, treating as aligned",
                asset, spot_ref.price_usd, implied_spot, gap_cents
            )
            return True, gap_cents  # Treat as aligned to prevent blocking
        
        # Check against threshold
        is_aligned = gap_cents < self.alignment_threshold_cents
        
        if not is_aligned:
            logger.warning(
                "[ALIGNMENT-FAIL] asset=%s spot=%.2f implied=%.2f gap=%.2fc threshold=%dc",
                asset, spot_ref.price_usd, implied_spot, gap_cents, self.alignment_threshold_cents
            )
        
        return is_aligned, gap_cents


# Singleton instance
_unified_edge_computer: Optional[UnifiedEdgeComputer] = None


def get_unified_edge_computer() -> UnifiedEdgeComputer:
    """Get the singleton unified edge computer instance."""
    global _unified_edge_computer
    if _unified_edge_computer is None:
        _unified_edge_computer = UnifiedEdgeComputer()
    return _unified_edge_computer
