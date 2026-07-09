"""
Kalshi Crypto 15m Canonical Risk Envelope

Single source of truth for all risk parameters for kalshi_crypto_15m_v2 profile.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from decimal import Decimal
from enum import Enum

from utils.logger import get_logger

logger = get_logger("merid.risk.profiles.kalshi_crypto_15m_risk_envelope")

# ── Module-Level Window Tracking State (2026-07-06 CRITICAL FIX) ────────────
# get_kalshi_crypto_15m_risk_envelope() computes a FRESH envelope on every call,
# so window exposure stored on envelope instances was discarded immediately:
# check_window_limit() always saw $0 exposure and the 3%/5% HARD STOPs never
# engaged. Window tracking state MUST live at module level so every envelope
# instance reads/writes the same cumulative exposure for the current 15m window.
# Windows are aligned to epoch 900s boundaries to match the Kalshi 15m market
# windows (e.g., 06:00:00-06:15:00).
_WINDOW_TRACKING_LOCK = threading.Lock()
_WINDOW_TRACKING_STATE: Dict[str, Any] = {
    "window_start_ts": 0.0,
    "agent_exposure_usd": {},   # agent_id -> cumulative executed notional this window
    "total_exposure_usd": 0.0,  # cumulative executed notional across all agents this window
    "agent_resting_exposure_usd": {},  # agent_id -> cumulative resting order notional this window (CRITICAL FIX 2026-07-08)
    "total_resting_exposure_usd": 0.0,  # cumulative resting order notional across all agents this window (CRITICAL FIX 2026-07-08)
    "peak_bankroll_usd": 0.0,  # CRITICAL FIX 2026-07-08: Peak bankroll at window start for consistent 5% calculation
    "asset_exposure_usd": {},  # CRITICAL FIX 2026-07-08: asset -> cumulative executed notional this window (3% per-asset limit)
}


def _reset_shared_window_state_for_testing() -> None:
    """
    Reset module-level shared window tracking state for testing.
    
    CRITICAL: This is a testing-only function that clears the shared state
    to ensure clean test isolation. Do not call this in production code.
    """
    with _WINDOW_TRACKING_LOCK:
        _WINDOW_TRACKING_STATE["window_start_ts"] = 0.0
        _WINDOW_TRACKING_STATE["agent_exposure_usd"] = {}
        _WINDOW_TRACKING_STATE["total_exposure_usd"] = 0.0
        _WINDOW_TRACKING_STATE["agent_resting_exposure_usd"] = {}
        _WINDOW_TRACKING_STATE["total_resting_exposure_usd"] = 0.0
        _WINDOW_TRACKING_STATE["peak_bankroll_usd"] = 0.0
        _WINDOW_TRACKING_STATE["asset_exposure_usd"] = {}


def force_reset_window_exposure(envelope=None, reason="startup") -> None:
    """
    Force reset window exposure tracking state.
    
    CRITICAL: This is for recovery when window exposure gets stuck due to
    missing position closure events (e.g., positions closed outside the system,
    or shutdown before closure events were processed).
    
    This should be called during startup if exposure is non-zero but position
    cache shows zero open positions (stale exposure condition).
    
    Args:
        envelope: Optional envelope instance to sync instance fields after reset.
                  If provided, instance fields will be updated to match shared state.
        reason: Reason for the reset (e.g., "startup", "stale_exposure", "manual")
    """
    import time
    current_ts = time.time()
    
    # Capture stale exposure before reset for logging
    with _WINDOW_TRACKING_LOCK:
        stale_agent_exposure = dict(_WINDOW_TRACKING_STATE["agent_exposure_usd"])
        stale_total_exposure = _WINDOW_TRACKING_STATE["total_exposure_usd"]
        stale_window_start = _WINDOW_TRACKING_STATE["window_start_ts"]
        
        _WINDOW_TRACKING_STATE["window_start_ts"] = _window_bucket_start(current_ts)
        _WINDOW_TRACKING_STATE["agent_exposure_usd"] = {}
        _WINDOW_TRACKING_STATE["total_exposure_usd"] = 0.0
        _WINDOW_TRACKING_STATE["agent_resting_exposure_usd"] = {}
        _WINDOW_TRACKING_STATE["total_resting_exposure_usd"] = 0.0
        _WINDOW_TRACKING_STATE["peak_bankroll_usd"] = 0.0
        _WINDOW_TRACKING_STATE["asset_exposure_usd"] = {}
        venue_total = _WINDOW_TRACKING_STATE["total_exposure_usd"]
    
    # Sync instance fields if envelope provided
    if envelope:
        envelope.window_start_ts = _WINDOW_TRACKING_STATE["window_start_ts"]
        envelope.agent_window_exposure_usd = {}
        envelope.total_window_exposure_usd = venue_total
    
    logger.warning(
        f"[WINDOW-TRACKING] FORCE RESET at ts={current_ts:.0f} - "
        f"reason={reason} "
        f"stale_total_exposure=${stale_total_exposure:.2f} "
        f"stale_agent_count={len(stale_agent_exposure)} "
        f"stale_window_start={stale_window_start:.0f} "
        f"new_window_start={_WINDOW_TRACKING_STATE['window_start_ts']:.0f}"
    )


def _window_bucket_start(current_ts: float) -> float:
    """Return the epoch-aligned start of the 15-minute window containing current_ts."""
    return current_ts - (current_ts % 900.0)


def _roll_window_if_needed_locked(current_ts: float, current_bankroll_usd: float = 0.0) -> None:
    """Reset shared window state when a new 15m window begins. Caller holds lock.
    
    CRITICAL FIX 2026-07-08: Capture peak bankroll at window start for consistent 5% calculation.
    This ensures the 5% limit doesn't fluctuate if bankroll changes mid-window.
    """
    bucket_start = _window_bucket_start(current_ts)
    if bucket_start != _WINDOW_TRACKING_STATE["window_start_ts"]:
        old_window_start = _WINDOW_TRACKING_STATE["window_start_ts"]
        old_total_exposure = _WINDOW_TRACKING_STATE["total_exposure_usd"]
        old_agent_count = len(_WINDOW_TRACKING_STATE["agent_exposure_usd"])
        old_resting_exposure = _WINDOW_TRACKING_STATE["total_resting_exposure_usd"]
        old_peak_bankroll = _WINDOW_TRACKING_STATE["peak_bankroll_usd"]
        
        _WINDOW_TRACKING_STATE["window_start_ts"] = bucket_start
        _WINDOW_TRACKING_STATE["agent_exposure_usd"] = {}
        _WINDOW_TRACKING_STATE["total_exposure_usd"] = 0.0
        _WINDOW_TRACKING_STATE["agent_resting_exposure_usd"] = {}
        _WINDOW_TRACKING_STATE["total_resting_exposure_usd"] = 0.0
        _WINDOW_TRACKING_STATE["asset_exposure_usd"] = {}
        
        # CRITICAL FIX 2026-07-08: Lock in peak bankroll at window start
        # If current bankroll is provided and > 0, use it. Otherwise use previous peak.
        # For first window start (old_peak_bankroll == 0), use current bankroll if provided.
        if current_bankroll_usd > 0:
            _WINDOW_TRACKING_STATE["peak_bankroll_usd"] = current_bankroll_usd
        elif old_peak_bankroll > 0:
            _WINDOW_TRACKING_STATE["peak_bankroll_usd"] = old_peak_bankroll
        else:
            # Fallback: use current bankroll even if 0 (shouldn't happen in production)
            _WINDOW_TRACKING_STATE["peak_bankroll_usd"] = current_bankroll_usd
        
        logger.info(
            f"[WINDOW-TRACKING] New 15m window started at ts={bucket_start:.0f} - "
            f"old_window_start={old_window_start:.0f} "
            f"old_total_exposure=${old_total_exposure:.2f} "
            f"old_agent_count={old_agent_count} "
            f"old_resting_exposure=${old_resting_exposure:.2f} "
            f"peak_bankroll=${_WINDOW_TRACKING_STATE['peak_bankroll_usd']:.2f} "
            f"exposure_reset"
        )

# VERSION TAG: This log identifies the deployed revision of kalshi_crypto_15m_risk_envelope.py
# Changes in v20260529a:
# - Added operation_mode support (test/prod) for daily loss limit
# - test mode: 10% daily loss limit for realistic live testing
# - prod mode: 5% daily loss limit for conservative production trading
# - Controlled via MERID_OPERATION_MODE env var or profile YAML

def log_risk_envelope_version() -> None:
    """Log risk envelope version at startup (not import time)."""
    logger.info("[RISK-ENVELOPE VERSION v20260529a-cache-fix] Loaded - operation_mode support for daily loss limit")


class RiskBand(Enum):
    """Explicit risk bands for drawdown-based scaling.
    
    Matches Kalshi's "take a break after losses" guidance:
    - Normal: 0-10% drawdown, 100% risk multiplier
    - Warning: 10-12% drawdown, 50% risk multiplier
    - Downsize: 12-15% drawdown, 25% risk multiplier
    - Halt: 15%+ drawdown, 0% risk multiplier (manual resume required)
    """
    NORMAL = "normal"
    WARNING = "warning"
    DOWNSIZE = "downsize"
    HALT = "halt"


def is_risk_envelope_enabled() -> bool:
    """Check if risk envelope is enabled via feature flag.
    
    Feature flag MERID_RISK_ENVELOPE_ENABLED allows runtime disabling of the envelope
    for rollback scenarios. Default is True (enabled).
    """
    enabled = os.getenv("MERID_RISK_ENVELOPE_ENABLED", "true").lower() in ("true", "1", "yes")
    logger.info(f"[RISK-ENVELOPE-FEATURE-FLAG] MERID_RISK_ENVELOPE_ENABLED={enabled}")
    return enabled


@dataclass
class KalshiCrypto15mRiskEnvelope:
    """
    Complete risk envelope for kalshi_crypto_15m_v2 profile.
    
    All values are derived from profile config and live bankroll.
    No hardcoded values, no legacy paths.
    """
    
    # ── Input Parameters ─────────────────────────────────────────────────────
    live_bankroll_usd: float
    profile_capital_usd: float  # From profile YAML (0 = use live bankroll)
    
    # ── Computed Venue-Level Caps ────────────────────────────────────────────
    # Per-trade cap (derived from profile percentage × capital)
    max_single_order_notional_usd: float
    
    # Max total notional (sum of all positions)
    max_total_notional_usd: float
    
    # Max concurrent trades (from profile agent_defaults)
    max_concurrent_trades: int
    
    # ── Per-Asset Caps (BTC/ETH/SOL/XRP/DOGE) ───────────────────────────────
    # Each asset has its own notional cap as percentage of capital
    asset_max_notional_usd: Dict[str, float]  # {"BTC": X, "ETH": Y, ...}
    
    # ── Depth Thresholds (single source of truth for 15m stack) ───────────────
    # Per-asset depth thresholds from profile YAML
    asset_depth_thresholds: Dict[str, Dict[str, int]]  # {"BTC": {"min_depth_yes": 30, "min_depth_no": 30}, ...}
    
    # ── Per-Agent Defaults ───────────────────────────────────────────────────
    agent_max_notional_usd: float  # From profile agent_defaults
    agent_max_orders_per_window: int
    agent_max_yes_position: int
    agent_max_no_position: int

    # ── Cycle Risk Cap ───────────────────────────────────────────────────────
    max_cycle_risk_pct: float  # Maximum risk per cycle as percentage of capital
    
    # ── Window-Based Risk Tracking (2026-07-06: HARD STOP) ─────────────────
    # Per-agent per-window limit: 3% per agent per 15-minute window
    # Total venue per-window limit: 5% across all agents per 15-minute window
    guardrails_per_window_risk_pct: float  # 3% per agent per 15m window (HARD STOP)
    guardrails_total_venue_risk_pct: float  # 5% total across all agents per 15m window (HARD STOP)
    
    # Computed window limits in USD (for easy access)
    per_agent_window_limit_usd: float  # 3% of capital in USD
    total_venue_window_limit_usd: float  # 5% of capital in USD
    
    # Window tracking state
    window_start_ts: float  # Timestamp when current 15m window started
    agent_window_exposure_usd: Dict[str, float]  # Cumulative exposure per agent this window
    total_window_exposure_usd: float  # Cumulative exposure across all agents this window
    agent_resting_exposure_usd: Dict[str, float]  # Cumulative resting order exposure per agent this window (CRITICAL FIX 2026-07-08)
    total_resting_exposure_usd: float  # Cumulative resting order exposure across all agents this window (CRITICAL FIX 2026-07-08)
    
    # ── Guardrails ───────────────────────────────────────────────────────────
    daily_loss_enabled: bool
    max_daily_loss_usd: float
    drawdown_halt_pct: float
    drawdown_unwind_pct: float
    
    # ── Drawdown Tracking ─────────────────────────────────────────────────────
    peak_equity_usd: float
    current_equity_usd: float
    current_drawdown_pct: float
    
    # ── Kelly Fraction ────────────────────────────────────────────────────────
    kelly_fraction: float
    
    # ── Adaptive Risk Scaling ────────────────────────────────────────────────
    adaptive_risk_bands: List[Dict[str, float]]  # From YAML
    per_trade_risk_multiplier: float
    is_halted: bool
    current_risk_band: RiskBand  # Explicit band state
    resume_if_drawdown_improves: bool  # Auto-resume when drawdown improves to lower band
    
    # ── Correlation Tracking (Phase 1 Profitability Enhancement) ─────────────
    correlation_tracking_enabled: bool
    correlation_threshold: float  # Threshold for exposure reduction
    correlation_multiplier: float  # Current correlation-based size multiplier
    
    def update_drawdown(self, current_equity_usd: float):
        """Update drawdown tracking with current equity.
        
        Args:
            current_equity_usd: Current equity from bankroll service
            
        Raises:
            ValueError: If current_equity_usd is invalid
        """
        # Validate input
        if current_equity_usd is None or current_equity_usd < 0:
            raise ValueError(f"Invalid current_equity_usd: {current_equity_usd}")
        
        self.current_equity_usd = current_equity_usd
        
        # Update peak equity
        if current_equity_usd > self.peak_equity_usd:
            self.peak_equity_usd = current_equity_usd
            logger.info(f"[DRAWDOWN] New peak equity: ${self.peak_equity_usd:.2f}")
        
        # Handle fresh account (peak_equity == 0)
        if self.peak_equity_usd == 0:
            self.current_drawdown_pct = 0.0
            logger.warning("[DRAWDOWN] Peak equity is 0, treating as fresh account")
        else:
            # Compute drawdown with floating-point tolerance
            self.current_drawdown_pct = (self.peak_equity_usd - current_equity_usd) / self.peak_equity_usd
            # Clamp to [0, 1] to handle floating-point edge cases
            self.current_drawdown_pct = max(0.0, min(1.0, self.current_drawdown_pct))
        
        # Update adaptive risk and halt state
        old_halted = self.is_halted
        old_band = self.current_risk_band
        self._update_adaptive_risk()
        
        # Auto-resume if drawdown improves to lower band (when enabled)
        if self.resume_if_drawdown_improves and old_halted and not self.is_halted:
            logger.info(
                f"[RISK-ENVELOPE] Auto-resume: drawdown improved from {old_band.value} to {self.current_risk_band.value}, "
                f"halt cleared (resume_if_drawdown_improves=True)"
            )
        
        # Set halt state based on drawdown threshold
        self.is_halted = self.current_drawdown_pct >= self.drawdown_halt_pct
    
    def _update_adaptive_risk(self):
        """Update per-trade risk multiplier based on drawdown bands."""
        old_multiplier = self.per_trade_risk_multiplier
        old_band = self.current_risk_band
        
        for band in self.adaptive_risk_bands:
            if self.current_drawdown_pct <= band['max_drawdown_pct']:
                self.per_trade_risk_multiplier = band['multiplier']
                # Map multiplier to explicit RiskBand
                if band['multiplier'] == 1.0:
                    self.current_risk_band = RiskBand.NORMAL
                elif band['multiplier'] == 0.5:
                    self.current_risk_band = RiskBand.WARNING
                elif band['multiplier'] == 0.25:
                    self.current_risk_band = RiskBand.DOWNSIZE
                elif band['multiplier'] == 0.0:
                    self.current_risk_band = RiskBand.HALT
                else:
                    self.current_risk_band = RiskBand.NORMAL  # Default
                
                # Log band change if multiplier or band changed
                if old_multiplier != self.per_trade_risk_multiplier or old_band != self.current_risk_band:
                    logger.info(
                        f"[RISK-ENVELOPE] Band change: drawdown={self.current_drawdown_pct:.2%}, "
                        f"multiplier={old_multiplier:.2f}→{self.per_trade_risk_multiplier:.2f}, "
                        f"band={old_band.value if old_band else 'none'}→{self.current_risk_band.value}, "
                        f"distance_to_halt={self.drawdown_halt_pct - self.current_drawdown_pct:.2%}"
                    )
                return
        
        # Default to halt if no band matches
        self.per_trade_risk_multiplier = 0.0
        self.current_risk_band = RiskBand.HALT
        if old_multiplier != 0.0 or old_band != RiskBand.HALT:
            logger.warning(
                f"[RISK-ENVELOPE] Halt triggered: drawdown={self.current_drawdown_pct:.2%} >= halt={self.drawdown_halt_pct:.2%}"
            )
    
    def get_per_trade_risk_pct(self) -> float:
        """Get per-trade risk percentage.
        
        2026-07-08 UPDATE: DISABLED in favor of fixed $1 exposure model.
        Per-trade risk is now enforced via slot-based position management:
        - Total exposure across all positions must be ≤ $1
        - Each contract consumes its price in USD from the $1 cap
        - Sequential trading blocks new entries until positions exit
        """
        # 2026-07-08: DISABLED - using fixed $1 exposure cap instead
        # Return 0.0 to indicate percentage-based sizing is disabled
        return 0.0
    
    def get_drawdown_halt_pct(self) -> float:
        """Get drawdown halt percentage."""
        return self.drawdown_halt_pct
    
    def get_drawdown_unwind_pct(self) -> float:
        """Get drawdown unwind percentage."""
        return self.drawdown_unwind_pct
    
    def get_kelly_fraction(self) -> float:
        """Get Kelly fraction."""
        return self.kelly_fraction
    
    def get_risk_multiplier_for_drawdown(self) -> float:
        """Get risk multiplier based on current drawdown."""
        return self.per_trade_risk_multiplier
    
    def get_effective_per_trade_risk_usd(self) -> float:
        """Get effective per-trade risk in USD (with adaptive scaling).
        
        2026-07-08 UPDATE: DISABLED percentage-based calculation in favor of fixed $1 exposure model.
        Per-trade risk is now enforced via slot-based position management:
        - Total exposure across all positions must be ≤ $1
        - Each contract consumes its price in USD from the $1 cap
        - Sequential trading blocks new entries until positions exit
        
        Returns fixed $1 exposure cap (or override from environment variable).
        """
        # 2026-07-08: DISABLED percentage-based calculation - using fixed $1 exposure cap
        import os
        fixed_exposure_cap_usd = float(os.getenv('MERID_FIXED_EXPOSURE_CAP_USD', '1.00'))
        return fixed_exposure_cap_usd
    
    def distance_to_halt_pct(self) -> float:
        """Distance from current drawdown to halt threshold."""
        return max(0.0, self.drawdown_halt_pct - self.current_drawdown_pct)
    
    def get_depth_thresholds(self, asset: str) -> Dict[str, int]:
        """Get depth thresholds for a specific asset from profile YAML.
        
        Args:
            asset: Asset symbol (e.g., "BTC", "ETH", "SOL", "XRP", "DOGE")
            
        Returns:
            Dict with min_depth_yes and min_depth_no thresholds
            
        Raises:
            KeyError: If asset not found in depth thresholds (no silent defaults)
        """
        if asset not in self.asset_depth_thresholds:
            raise KeyError(f"Asset {asset} not found in depth thresholds. "
                          f"Available assets: {list(self.asset_depth_thresholds.keys())}")
        return self.asset_depth_thresholds[asset]
    
    def get_base_position_size(self) -> int:
        """Get base position size (number of contracts) for a single trade.
        
        This is derived from max_single_order_notional_usd and assumes a
        conservative contract price of 50 cents (typical for 15m crypto futures).
        
        Returns:
            Base position size as integer number of contracts (minimum 1)
        """
        # Conservative contract price assumption (50 cents = 0.50 USD)
        # 15m crypto futures typically trade in the 40-60 cent range
        assumed_contract_price_usd = 0.50
        
        # Calculate base size from max single order notional
        base_size = self.max_single_order_notional_usd / assumed_contract_price_usd
        
        # Ensure minimum of 1 contract
        base_size = max(1.0, base_size)
        
        # Return as integer
        return int(base_size)
    
    def reset_window_tracking(self, current_ts: float) -> None:
        """Reset window tracking at start of new 15-minute window.
        
        CRITICAL (2026-07-06): Operates on module-level shared state so the reset
        is visible to ALL envelope instances (envelopes are recomputed per call).
        
        Args:
            current_ts: Current timestamp
        """
        with _WINDOW_TRACKING_LOCK:
            _WINDOW_TRACKING_STATE["window_start_ts"] = _window_bucket_start(current_ts)
            _WINDOW_TRACKING_STATE["agent_exposure_usd"] = {}
            _WINDOW_TRACKING_STATE["total_exposure_usd"] = 0.0
            _WINDOW_TRACKING_STATE["agent_resting_exposure_usd"] = {}
            _WINDOW_TRACKING_STATE["total_resting_exposure_usd"] = 0.0
            self.window_start_ts = _WINDOW_TRACKING_STATE["window_start_ts"]
        self.agent_window_exposure_usd = {}
        self.total_window_exposure_usd = 0.0
        self.agent_resting_exposure_usd = {}
        self.total_resting_exposure_usd = 0.0
        logger.info(
            f"[WINDOW-TRACKING] Reset 15m window tracking at ts={current_ts:.0f}"
        )
    
    def check_window_limit(
        self,
        agent_id: str,
        order_notional_usd: float,
        current_ts: float,
        custom_per_agent_limit_pct: Optional[float] = None,
        custom_total_venue_limit_pct: Optional[float] = None,
        asset: Optional[str] = None,
    ) -> tuple[bool, str]:
        """Check if order would exceed window-based risk limits (HARD STOP).
        
        CRITICAL FIX 2026-07-08: 
        - Uses peak bankroll at window start for consistent 5% calculation
        - Adds 3% per-asset window limit enforcement
        
        Args:
            agent_id: Agent identifier (e.g., "BTC_15M", "ETH_15M")
            order_notional_usd: Notional value of order in USD
            current_ts: Current timestamp
            custom_per_agent_limit_pct: Override per-agent limit (e.g., for exit orders)
            custom_total_venue_limit_pct: Override total venue limit (e.g., for exit orders)
            asset: Asset symbol (e.g., "BTC", "ETH") for per-asset limit check
            
        Returns:
            Tuple of (allowed, reason)
            - allowed: True if order is within window limits, False if blocked
            - reason: Reason string if blocked, empty string if allowed
        """
        # CRITICAL FIX (2026-07-08): Add assertions to validate inputs
        assert self.live_bankroll_usd > 0, "Bankroll must be positive for window limit check"
        # 2026-07-08: DISABLED percentage-based assertions - using fixed $1 exposure model
        # assert self.guardrails_per_window_risk_pct > 0, "Per-agent window limit must be positive"
        # assert self.guardrails_total_venue_risk_pct > 0, "Total venue window limit must be positive"
        assert order_notional_usd > 0, "Order notional must be positive"
        assert agent_id, "Agent ID must be provided"
        
        # CRITICAL (2026-07-06): Read cumulative exposure from module-level shared
        # state. Envelope instances are recomputed on every call, so instance
        # fields always start at zero - only the shared state carries the truth.
        # CRITICAL FIX (2026-07-08): Include resting order exposure to prevent
        # multiple resting orders from exceeding window limits when they execute.
        with _WINDOW_TRACKING_LOCK:
            _roll_window_if_needed_locked(current_ts, self.live_bankroll_usd)
            current_agent_exposure = _WINDOW_TRACKING_STATE["agent_exposure_usd"].get(agent_id, 0.0)
            current_total_exposure = _WINDOW_TRACKING_STATE["total_exposure_usd"]
            current_agent_resting = _WINDOW_TRACKING_STATE["agent_resting_exposure_usd"].get(agent_id, 0.0)
            current_total_resting = _WINDOW_TRACKING_STATE["total_resting_exposure_usd"]
            # CRITICAL FIX 2026-07-08: Use peak bankroll at window start for consistent limits
            peak_bankroll_usd = _WINDOW_TRACKING_STATE["peak_bankroll_usd"] or self.live_bankroll_usd
            # CRITICAL FIX 2026-07-08: Get per-asset exposure for 3% limit check
            current_asset_exposure = 0.0
            if asset:
                current_asset_exposure = _WINDOW_TRACKING_STATE["asset_exposure_usd"].get(asset, 0.0)
        
        # 2026-07-08: DISABLED percentage-based window limits - using fixed $1 exposure model
        # Use custom limits if provided, otherwise use fixed $1 exposure cap
        import os
        fixed_exposure_cap_usd = float(os.getenv('MERID_FIXED_EXPOSURE_CAP_USD', '1.00'))
        per_agent_limit_usd = custom_per_agent_limit_pct if custom_per_agent_limit_pct else fixed_exposure_cap_usd
        total_venue_limit_usd = custom_total_venue_limit_pct if custom_total_venue_limit_pct else fixed_exposure_cap_usd
        new_agent_exposure = current_agent_exposure + order_notional_usd
        new_agent_total = new_agent_exposure + current_agent_resting  # Executed + Resting
        
        # Check per-agent window limit (HARD STOP) - includes resting orders
        if new_agent_total > per_agent_limit_usd:
            reason = (
                f"per_agent_window_limit: agent={agent_id} "
                f"executed=${current_agent_exposure:.2f} + resting=${current_agent_resting:.2f} + order=${order_notional_usd:.2f} "
                f"= ${new_agent_total:.2f} > limit=${per_agent_limit_usd:.2f} - HARD STOP"
            )
            logger.warning(f"[WINDOW-TRACKING] {reason}")
            return False, reason
        
        # 2026-07-08: DISABLED percentage-based per-asset window limit - using fixed $1 exposure model
        if asset:
            import os
            fixed_exposure_cap_usd = float(os.getenv('MERID_FIXED_EXPOSURE_CAP_USD', '1.00'))
            per_asset_limit_usd = fixed_exposure_cap_usd
            new_asset_exposure = current_asset_exposure + order_notional_usd
            
            if new_asset_exposure > per_asset_limit_usd:
                reason = (
                    f"per_asset_window_limit: asset={asset} "
                    f"executed=${current_asset_exposure:.2f} + order=${order_notional_usd:.2f} "
                    f"= ${new_asset_exposure:.2f} > limit=${per_asset_limit_usd:.2f} - HARD STOP"
                )
                logger.warning(f"[WINDOW-TRACKING] {reason}")
                return False, reason
        
        # Calculate total venue window limit (including resting orders)
        # 2026-07-08: DISABLED percentage-based total venue window limit - using fixed $1 exposure model
        new_total_exposure = current_total_exposure + order_notional_usd
        new_total_venue = new_total_exposure + current_total_resting  # Executed + Resting
        
        # Check total venue window limit (HARD STOP) - includes resting orders
        if new_total_venue > total_venue_limit_usd:
            reason = (
                f"total_venue_window_limit: "
                f"executed=${current_total_exposure:.2f} + resting=${current_total_resting:.2f} + order=${order_notional_usd:.2f} "
                f"= ${new_total_venue:.2f} > limit=${total_venue_limit_usd:.2f} - HARD STOP"
            )
            logger.warning(f"[WINDOW-TRACKING] {reason}")
            return False, reason
        
        logger.info(
            f"[WINDOW-TRACKING] Window check OK: agent={agent_id} asset={asset or 'N/A'} "
            f"agent_exposure=${current_agent_exposure:.2f}+${order_notional_usd:.2f} <= ${per_agent_limit_usd:.2f}, "
            f"venue_exposure=${current_total_exposure:.2f}+${order_notional_usd:.2f} <= ${total_venue_limit_usd:.2f}"
        )
        return True, ""
    
    def record_order_execution(
        self,
        agent_id: str,
        order_notional_usd: float,
        asset: Optional[str] = None,
    ) -> None:
        """Record order execution in window tracking.
        
        CRITICAL FIX 2026-07-08: Added asset parameter for per-asset exposure tracking.
        
        Args:
            agent_id: Agent identifier
            order_notional_usd: Notional value of executed order in USD
            asset: Asset symbol (e.g., "BTC", "ETH") for per-asset tracking
        """
        # CRITICAL FIX (2026-07-08): Add assertions to validate inputs
        assert self.live_bankroll_usd > 0, "Bankroll must be positive for recording execution"
        assert order_notional_usd > 0, "Order notional must be positive for recording"
        assert agent_id, "Agent ID must be provided for recording"
        
        # CRITICAL (2026-07-06): Write to module-level shared state so the
        # recorded exposure survives envelope recomputation and is visible to
        # subsequent check_window_limit() calls (3%/5% allowance decrement).
        import time as _time_mod
        with _WINDOW_TRACKING_LOCK:
            _roll_window_if_needed_locked(_time_mod.time(), self.live_bankroll_usd)
            _WINDOW_TRACKING_STATE["agent_exposure_usd"][agent_id] = (
                _WINDOW_TRACKING_STATE["agent_exposure_usd"].get(agent_id, 0.0) + order_notional_usd
            )
            _WINDOW_TRACKING_STATE["total_exposure_usd"] += order_notional_usd
            # CRITICAL FIX 2026-07-08: Track per-asset exposure for 3% limit
            if asset:
                _WINDOW_TRACKING_STATE["asset_exposure_usd"][asset] = (
                    _WINDOW_TRACKING_STATE["asset_exposure_usd"].get(asset, 0.0) + order_notional_usd
                )
            agent_total = _WINDOW_TRACKING_STATE["agent_exposure_usd"][agent_id]
            venue_total = _WINDOW_TRACKING_STATE["total_exposure_usd"]
            asset_total = _WINDOW_TRACKING_STATE["asset_exposure_usd"].get(asset, 0.0) if asset else 0.0
        
        # Sync instance fields for observability/snapshots
        self.agent_window_exposure_usd[agent_id] = agent_total
        self.total_window_exposure_usd = venue_total
        
        logger.info(
            f"[WINDOW-TRACKING] Recorded execution: agent={agent_id} asset={asset or 'N/A'} "
            f"notional=${order_notional_usd:.2f} "
            f"agent_total=${agent_total:.2f} "
            f"asset_total=${asset_total:.2f} "
            f"venue_total=${venue_total:.2f}"
        )
    
    def record_position_closure(
        self,
        agent_id: str,
        position_notional_usd: float,
        asset: Optional[str] = None,
    ) -> None:
        """Record position closure (reduces window exposure).
        
        CRITICAL FIX 2026-07-08: Added asset parameter for per-asset exposure release.
        
        CRITICAL: This allows agents to re-enter after closing positions
        via trailing stop, ratchet, or mandatory 99c exit.
        
        Args:
            agent_id: Agent identifier
            position_notional_usd: Notional value of closed position in USD
            asset: Asset symbol (e.g., "BTC", "ETH") for per-asset tracking
        """
        # CRITICAL (2026-07-06): Operate on module-level shared state (see
        # record_order_execution for rationale).
        import time as _time_mod
        with _WINDOW_TRACKING_LOCK:
            _roll_window_if_needed_locked(_time_mod.time(), self.live_bankroll_usd)
            current_agent_exposure = _WINDOW_TRACKING_STATE["agent_exposure_usd"].get(agent_id, 0.0)
            new_agent_exposure = max(0.0, current_agent_exposure - position_notional_usd)
            _WINDOW_TRACKING_STATE["agent_exposure_usd"][agent_id] = new_agent_exposure
            _WINDOW_TRACKING_STATE["total_exposure_usd"] = max(
                0.0, _WINDOW_TRACKING_STATE["total_exposure_usd"] - position_notional_usd
            )
            # CRITICAL FIX 2026-07-08: Release per-asset exposure
            if asset:
                current_asset_exposure = _WINDOW_TRACKING_STATE["asset_exposure_usd"].get(asset, 0.0)
                new_asset_exposure = max(0.0, current_asset_exposure - position_notional_usd)
                _WINDOW_TRACKING_STATE["asset_exposure_usd"][asset] = new_asset_exposure
            venue_total = _WINDOW_TRACKING_STATE["total_exposure_usd"]
            asset_total = _WINDOW_TRACKING_STATE["asset_exposure_usd"].get(asset, 0.0) if asset else 0.0
        
        # Sync instance fields for observability/snapshots
        self.agent_window_exposure_usd[agent_id] = new_agent_exposure
        self.total_window_exposure_usd = venue_total
        
        logger.info(
            f"[WINDOW-TRACKING] Recorded closure: agent={agent_id} asset={asset or 'N/A'} "
            f"notional=${position_notional_usd:.2f} "
            f"agent_total=${current_agent_exposure:.2f}→${new_agent_exposure:.2f} "
            f"asset_total=${asset_total:.2f} "
            f"venue_total=${venue_total:.2f}"
        )
    
    def refund_order_execution(
        self,
        agent_id: str,
        order_notional_usd: float
    ) -> None:
        """Refund window exposure for rejected/unfilled orders.
        
        CRITICAL: This reverses the optimistic exposure recording done at gate pass time
        when orders are rejected by the exchange or fail to fill. Without this, window
        exposure accumulates even though no actual positions are taken, blocking all
        future orders until the 15m window expires.
        
        Args:
            agent_id: Agent identifier
            order_notional_usd: Notional value to refund in USD
        """
        # CRITICAL (2026-07-07): Operate on module-level shared state (see
        # record_order_execution for rationale).
        with _WINDOW_TRACKING_LOCK:
            current_agent_exposure = _WINDOW_TRACKING_STATE["agent_exposure_usd"].get(agent_id, 0.0)
            new_agent_exposure = max(0.0, current_agent_exposure - order_notional_usd)
            _WINDOW_TRACKING_STATE["agent_exposure_usd"][agent_id] = new_agent_exposure
            _WINDOW_TRACKING_STATE["total_exposure_usd"] = max(
                0.0, _WINDOW_TRACKING_STATE["total_exposure_usd"] - order_notional_usd
            )
            venue_total = _WINDOW_TRACKING_STATE["total_exposure_usd"]
        
        # Sync instance fields for observability/snapshots
        self.agent_window_exposure_usd[agent_id] = new_agent_exposure
        self.total_window_exposure_usd = venue_total
        
        logger.info(
            f"[WINDOW-TRACKING] Refunded execution: agent={agent_id} "
            f"notional=${order_notional_usd:.2f} "
            f"agent_total=${current_agent_exposure:.2f}→${new_agent_exposure:.2f} "
            f"venue_total=${venue_total:.2f}"
        )
    
    def record_resting_order_placement(
        self,
        agent_id: str,
        order_notional_usd: float
    ) -> None:
        """Record resting order placement (adds to resting exposure).
        
        CRITICAL FIX (2026-07-08): This prevents multiple resting orders from
        exceeding window limits. Resting orders are counted in window exposure
        at placement time, then released when they fill, cancel, or expire.
        
        Args:
            agent_id: Agent identifier
            order_notional_usd: Notional value of resting order in USD
        """
        import time as _time_mod
        with _WINDOW_TRACKING_LOCK:
            _roll_window_if_needed_locked(_time_mod.time())
            _WINDOW_TRACKING_STATE["agent_resting_exposure_usd"][agent_id] = (
                _WINDOW_TRACKING_STATE["agent_resting_exposure_usd"].get(agent_id, 0.0) + order_notional_usd
            )
            _WINDOW_TRACKING_STATE["total_resting_exposure_usd"] += order_notional_usd
            agent_total = _WINDOW_TRACKING_STATE["agent_resting_exposure_usd"][agent_id]
            venue_total = _WINDOW_TRACKING_STATE["total_resting_exposure_usd"]
        
        # Sync instance fields for observability/snapshots
        self.agent_resting_exposure_usd[agent_id] = agent_total
        self.total_resting_exposure_usd = venue_total
        
        logger.info(
            f"[WINDOW-TRACKING] Recorded resting order: agent={agent_id} "
            f"notional=${order_notional_usd:.2f} "
            f"agent_resting_total=${agent_total:.2f} "
            f"venue_resting_total=${venue_total:.2f}"
        )
    
    def release_resting_order_exposure(
        self,
        agent_id: str,
        order_notional_usd: float
    ) -> None:
        """Release resting order exposure (when order fills, cancels, or expires).
        
        CRITICAL FIX (2026-07-08): This reverses the resting exposure recording
        done at placement time. Called when resting orders fill, are canceled,
        or expire. Without this, resting exposure accumulates indefinitely.
        
        Args:
            agent_id: Agent identifier
            order_notional_usd: Notional value to release in USD
        """
        with _WINDOW_TRACKING_LOCK:
            current_agent_resting = _WINDOW_TRACKING_STATE["agent_resting_exposure_usd"].get(agent_id, 0.0)
            new_agent_resting = max(0.0, current_agent_resting - order_notional_usd)
            _WINDOW_TRACKING_STATE["agent_resting_exposure_usd"][agent_id] = new_agent_resting
            _WINDOW_TRACKING_STATE["total_resting_exposure_usd"] = max(
                0.0, _WINDOW_TRACKING_STATE["total_resting_exposure_usd"] - order_notional_usd
            )
            venue_total = _WINDOW_TRACKING_STATE["total_resting_exposure_usd"]
        
        # Sync instance fields for observability/snapshots
        self.agent_resting_exposure_usd[agent_id] = new_agent_resting
        self.total_resting_exposure_usd = venue_total
        
        logger.info(
            f"[WINDOW-TRACKING] Released resting order: agent={agent_id} "
            f"notional=${order_notional_usd:.2f} "
            f"agent_resting_total=${current_agent_resting:.2f}→${new_agent_resting:.2f} "
            f"venue_resting_total=${venue_total:.2f}"
        )



def compute_kalshi_crypto_15m_risk_envelope(
    live_bankroll_usd: float,
    profile_path: Optional[str] = None
) -> KalshiCrypto15mRiskEnvelope:
    """
    Compute the complete risk envelope for kalshi_crypto_15m_v2 profile.
    
    This is the SINGLE canonical function for all risk parameters.
    All other modules must call this function to get risk limits.
    
    Args:
        live_bankroll_usd: Live bankroll from BankrollServiceV2
        profile_path: Optional path to kalshi_crypto_15m.yaml (default: config/profiles/)
    
    Returns:
        KalshiCrypto15mRiskEnvelope with all computed risk limits
    
    Raises:
        RuntimeError: If profile cannot be loaded or validation fails
    """
    import os
    import yaml
    from pathlib import Path
    import time as _time_mod
    
    # CRITICAL FIX 2026-07-08: Initialize peak bankroll on envelope creation
    # This ensures peak bankroll is set even before first check_window_limit call
    with _WINDOW_TRACKING_LOCK:
        _roll_window_if_needed_locked(_time_mod.time(), live_bankroll_usd)
    
    # Load profile YAML
    if profile_path is None:
        # Use absolute path from repository root to avoid relative path issues
        repo_root = Path(__file__).parent.parent.parent.parent
        profile_path = repo_root / "config" / "profiles" / "kalshi_crypto_15m_v2.yaml"
    
    try:
        with open(profile_path, 'r', encoding='utf-8') as f:
            profile_config = yaml.safe_load(f)
    except Exception as e:
        logger.error(
            f"[RISK-ENVELOPE] Failed to load profile from {profile_path}: {e} - "
            f"profile loading failed, risk envelope cannot be computed"
        )
        raise RuntimeError(f"Failed to load {profile_path.name}: {e}")
    
    # Extract venue caps
    venue = profile_config.get('venue', {})
    agent_defaults = profile_config.get('agent_defaults', {})
    assets = profile_config.get('assets', {})
    guardrails = profile_config.get('guardrails', {})
    kelly_config = profile_config.get('kelly', {})
    
    # Extract Phase 1 profitability enhancements
    correlation_tracking_config = profile_config.get('correlation_tracking', {})
    
    # Extract window-based risk limits (2026-07-06: HARD STOP)
    guardrails_per_window_risk_pct_raw = profile_config.get('guardrails_per_window_risk_pct', 0.03)
    if isinstance(guardrails_per_window_risk_pct_raw, dict):
        guardrails_per_window_risk_pct = guardrails_per_window_risk_pct_raw.get('value', 0.03)
    else:
        guardrails_per_window_risk_pct = guardrails_per_window_risk_pct_raw
    
    guardrails_total_venue_risk_pct_raw = profile_config.get('guardrails_total_venue_risk_pct', 0.05)
    if isinstance(guardrails_total_venue_risk_pct_raw, dict):
        guardrails_total_venue_risk_pct = guardrails_total_venue_risk_pct_raw.get('value', 0.05)
    else:
        guardrails_total_venue_risk_pct = guardrails_total_venue_risk_pct_raw
    
    # 2026-07-08: DISABLED percentage-based window limits - using fixed $1 exposure model
    logger.info(
        "[RISK-ENVELOPE] Window-based limits: DISABLED (using fixed $1 exposure model)"
    )

    # Extract cycle risk cap (handle nested dict format)
    # Aligned with kalshi_crypto_15m_v2.yaml profile (2026-06-05)
    # Profile specifies: max_cycle_risk_pct: 0.05 (5%)
    max_cycle_risk_pct_raw = profile_config.get('max_cycle_risk_pct', 0.05)  # 5% - aligned with profile
    if isinstance(max_cycle_risk_pct_raw, dict):
        max_cycle_risk_pct = max_cycle_risk_pct_raw.get('value', 0.05)  # 5% - aligned with profile
    else:
        max_cycle_risk_pct = max_cycle_risk_pct_raw
    
    # ── Extract and Validate Guardrails (handle nested dict format) ─────────
    # Validate adaptive risk bands
    adaptive_risk_bands = guardrails.get('adaptive_risk_bands')
    if not adaptive_risk_bands:
        raise ValueError("adaptive_risk_bands is required in profile YAML")
    
    # Validate bands are in ascending order
    for i in range(len(adaptive_risk_bands) - 1):
        if adaptive_risk_bands[i]['max_drawdown_pct'] >= adaptive_risk_bands[i+1]['max_drawdown_pct']:
            raise ValueError(f"adaptive_risk_bands must be in ascending order: {adaptive_risk_bands}")
    
    # Validate multipliers are between 0 and 1
    for band in adaptive_risk_bands:
        if not (0.0 <= band['multiplier'] <= 1.0):
            raise ValueError(f"adaptive_risk_bands multiplier must be between 0 and 1: {band}")
    
    # Validate last band has multiplier 0 (halt)
    if adaptive_risk_bands[-1]['multiplier'] != 0.0:
        raise ValueError("Last adaptive_risk_bands entry must have multiplier 0.0 (halt)")
    
    # Extract drawdown thresholds (handle nested dict format)
    drawdown_halt_pct_raw = guardrails.get('drawdown_halt_pct', 0.15)
    if isinstance(drawdown_halt_pct_raw, dict):
        drawdown_halt_pct = drawdown_halt_pct_raw.get('value', 0.15)
    else:
        drawdown_halt_pct = drawdown_halt_pct_raw
    
    drawdown_unwind_pct_raw = guardrails.get('drawdown_unwind_pct', 0.20)
    if isinstance(drawdown_unwind_pct_raw, dict):
        drawdown_unwind_pct = drawdown_unwind_pct_raw.get('value', 0.20)
    else:
        drawdown_unwind_pct = drawdown_unwind_pct_raw
    
    # Validate drawdown thresholds (after extraction)
    if drawdown_halt_pct <= 0 or drawdown_halt_pct > 0.50:
        raise ValueError(f"drawdown_halt_pct must be between 0 and 0.50: {drawdown_halt_pct}")
    
    if drawdown_unwind_pct <= drawdown_halt_pct or drawdown_unwind_pct > 0.50:
        raise ValueError(f"drawdown_unwind_pct must be > drawdown_halt_pct and <= 0.50: {drawdown_unwind_pct}")
    
    # Determine effective capital (profile capital or live bankroll)
    profile_capital = profile_config.get('capital_usd', 0)
    # For production, always use live bankroll for dynamic risk scaling
    # Profile capital is only for validation/calibration mode
    import os
    is_validation = os.getenv('MERID_VALIDATION_MODE', 'false').lower() in ('true', '1')
    effective_capital = profile_capital if (profile_capital > 0 and is_validation) else live_bankroll_usd
    
    if is_validation and profile_capital > 0:
        logger.info(
            f"[RISK-ENVELOPE] Effective capital: ${effective_capital:.2f} (using profile capital for validation mode)"
        )
    else:
        logger.info(
            f"[RISK-ENVELOPE] Effective capital: ${effective_capital:.2f} (using live Kalshi bankroll)"
        )
        if profile_capital > 0:
            logger.info(
                f"[RISK-ENVELOPE] Profile capital ${profile_capital:.2f} is unused in production mode (live bankroll takes precedence)"
            )
    
    # ── Compute Venue-Level Caps ────────────────────────────────────────────
    # 2026-07-08: DISABLED percentage-based calculations - using fixed $1 exposure model
    # Fixed exposure cap from environment variable or default $1.00
    fixed_exposure_cap_usd = float(os.getenv('MERID_FIXED_EXPOSURE_CAP_USD', '1.00'))
    max_single_order_notional_usd = fixed_exposure_cap_usd
    max_total_notional_usd = fixed_exposure_cap_usd  # Total exposure cap = $1
    
    max_concurrent_trades = agent_defaults.get('max_concurrent_trades', 3)
    
    # 2026-07-08: DISABLED percentage-based venue caps - using fixed $1 exposure model
    logger.info(
        f"[RISK-ENVELOPE] Venue caps: "
        f"max_single_order=${max_single_order_notional_usd:.2f}, "
        f"max_total=${max_total_notional_usd:.2f}, "
        f"max_concurrent={max_concurrent_trades}"
    )
    
    # ── Compute Per-Asset Caps ────────────────────────────────────────────────
    # 2026-07-08: DISABLED percentage-based calculations - using fixed $1 exposure model
    # Global $1 exposure cap is shared across all assets (not per-asset)
    # The global slot allocator enforces the $1 total cap across all assets
    # Per-asset caps here are set to $1.00 as upper bounds, but actual allocation
    # is managed by the slot allocator which enforces the $1.00 total exposure limit
    fixed_exposure_cap_usd = float(os.getenv('MERID_FIXED_EXPOSURE_CAP_USD', '1.00'))
    
    asset_max_notional_usd = {}
    asset_depth_thresholds = {}
    
    for asset_symbol, asset_config in assets.items():
        # Per-asset cap equals global cap - slot allocator enforces $1.00 total across all assets
        # This means while each asset theoretically has $1.00 upper bound, the slot allocator
        # will only allow total exposure of $1.00 across BTC + ETH + SOL + XRP + DOGE
        asset_max_notional_usd[asset_symbol] = fixed_exposure_cap_usd
        
        # 2026-07-08: DISABLED percentage-based floor logic - using fixed $1 exposure model
        
        # 2026-07-08: DISABLED percentage-based asset caps - using fixed $1 exposure model
        logger.info(
            f"[RISK-ENVELOPE] Asset {asset_symbol}: "
            f"max_notional=${asset_max_notional_usd[asset_symbol]:.2f} "
            f"(NOTE: This is an upper bound. Global slot allocator enforces ${fixed_exposure_cap_usd:.2f} TOTAL across all 5 assets)"
        )
        
        # Extract depth thresholds from profile YAML (single source of truth)
        min_depth_yes = asset_config.get('min_depth_yes', 1)  # FIXED: Default 1 to match YAML (was 25)
        min_depth_no = asset_config.get('min_depth_no', 1)  # FIXED: Default 1 to match YAML (was 25)
        asset_depth_thresholds[asset_symbol] = {
            'min_depth_yes': min_depth_yes,
            'min_depth_no': min_depth_no
        }
        logger.info(
            f"[RISK-ENVELOPE] Asset {asset_symbol}: depth thresholds (yes={min_depth_yes}, no={min_depth_no})"
        )
    
    # ── Compute Per-Agent Defaults ────────────────────────────────────────────
    # 2026-07-08: DISABLED percentage-based calculations - using fixed $1 exposure model
    fixed_exposure_cap_usd = float(os.getenv('MERID_FIXED_EXPOSURE_CAP_USD', '1.00'))
    agent_max_notional_usd = fixed_exposure_cap_usd
    agent_max_orders_per_window = agent_defaults.get('max_orders_per_window', 20)  # FIXED: Default 20 to match YAML (was 3)
    agent_max_yes_position = agent_defaults.get('max_yes_position', 5)  # FIXED: Default 5 to match YAML
    agent_max_no_position = agent_defaults.get('max_no_position', 5)  # FIXED: Default 5 to match YAML
    
    # 2026-07-08: DISABLED percentage-based agent defaults - using fixed $1 exposure model
    logger.info(
        f"[RISK-ENVELOPE] Agent defaults: "
        f"max_notional=${agent_max_notional_usd:.2f}, "
        f"max_orders_per_window={agent_max_orders_per_window}, "
        f"max_yes_position={agent_max_yes_position}, "
        f"max_no_position={agent_max_no_position}"
    )
    
    # ── Compute Guardrails ───────────────────────────────────────────────────
    # Drawdown is the primary hard cap; daily loss is optional/soft
    # Handle nested dict format for per_trade_risk_pct
    # Aligned with kalshi_crypto_15m_v2.yaml profile (2026-06-05)
    # Profile specifies: per_trade_risk_pct: 0.03 (3%)
    per_trade_risk_pct_raw = guardrails.get('per_trade_risk_pct', 0.03)  # 3% - aligned with profile
    if isinstance(per_trade_risk_pct_raw, dict):
        per_trade_risk_pct = per_trade_risk_pct_raw.get('value', 0.03)  # 3% - aligned with profile
    else:
        per_trade_risk_pct = per_trade_risk_pct_raw
    
    # Handle nested dict format for drawdown thresholds
    drawdown_halt_pct_raw = guardrails.get('drawdown_halt_pct', 0.15)
    if isinstance(drawdown_halt_pct_raw, dict):
        drawdown_halt_pct = drawdown_halt_pct_raw.get('value', 0.15)
    else:
        drawdown_halt_pct = drawdown_halt_pct_raw
    
    drawdown_unwind_pct_raw = guardrails.get('drawdown_unwind_pct', 0.20)
    if isinstance(drawdown_unwind_pct_raw, dict):
        drawdown_unwind_pct = drawdown_unwind_pct_raw.get('value', 0.20)
    else:
        drawdown_unwind_pct = drawdown_unwind_pct_raw
    
    # Extract kelly fraction (CRITICAL FIX: 0.02 - aligned with profile (was 0.05))
    kelly_fraction = kelly_config.get('kelly_fraction', kelly_config.get('kelly_hard_cap', 0.02))
    
    daily_loss_enabled = guardrails.get('daily_loss_enabled', False)
    
    # Daily loss is optional; if disabled, set to very high value (effectively disabled)
    if daily_loss_enabled:
        # Get operation mode from profile YAML or environment variable
        # Priority: env var > profile YAML > default (prod)
        operation_mode = os.getenv('MERID_OPERATION_MODE', profile_config.get('operation_mode', 'prod')).lower()
        
        # Get daily loss limit based on operation mode
        max_daily_loss_pct_raw = guardrails.get('max_daily_loss_pct', 0.20)  # CRITICAL FIX: 20% aligned with drawdown halt (was 0.05)
        if isinstance(max_daily_loss_pct_raw, dict):
            # Mode-specific limits: {test: 0.20, prod: 0.20}
            max_daily_loss_pct = max_daily_loss_pct_raw.get(operation_mode, max_daily_loss_pct_raw.get('prod', 0.20))
        else:
            # Legacy single value (backward compatibility)
            max_daily_loss_pct = max_daily_loss_pct_raw
        
        # Log operation mode and limit
        logger.info(
            f"[RISK-ENVELOPE] Operation mode: {operation_mode}, "
            f"Daily loss limit: ${effective_capital * max_daily_loss_pct:.2f}"
        )
        
        max_daily_loss_usd = effective_capital * max_daily_loss_pct
    else:
        # Daily loss disabled; drawdown is the single source of truth
        max_daily_loss_pct = None
        max_daily_loss_usd = float('inf')  # Effectively disabled
    
    # 2026-07-08: DISABLED percentage-based guardrails - using fixed $1 exposure model
    logger.info(
        f"[RISK-ENVELOPE] Guardrails: "
        f"per_trade_risk=DISABLED, "
        f"drawdown_halt={drawdown_halt_pct*100:.1f}%, "
        f"drawdown_unwind={drawdown_unwind_pct*100:.1f}%, "
        f"daily_loss_enabled={daily_loss_enabled}, "
        f"kelly_fraction={kelly_fraction:.2f}"
    )
    if daily_loss_enabled:
        logger.info(
            f"[RISK-ENVELOPE] Daily loss: ${max_daily_loss_usd:.2f}"
        )
    else:
        logger.info(
            f"[RISK-ENVELOPE] Daily loss: DISABLED (drawdown is primary guardrail)"
        )
    
    # ── Initialize Drawdown Tracking ─────────────────────────────────────────
    peak_equity_usd = live_bankroll_usd
    current_equity_usd = live_bankroll_usd
    current_drawdown_pct = 0.0
    
    # ── Initialize Window-Based Risk Tracking (2026-07-06) ─────────────────
    # CRITICAL FIX: Seed from module-level shared state so fresh envelope
    # instances reflect the cumulative exposure already recorded this window.
    # (Envelopes are recomputed per call - instance-local init of {} / 0.0
    # made the 3%/5% window HARD STOPs a no-op.)
    # CRITICAL FIX (2026-07-08): Also seed resting order exposure to prevent
    # multiple resting orders from exceeding window limits.
    import time
    with _WINDOW_TRACKING_LOCK:
        _roll_window_if_needed_locked(time.time())
        window_start_ts = _WINDOW_TRACKING_STATE["window_start_ts"]
        agent_window_exposure_usd = dict(_WINDOW_TRACKING_STATE["agent_exposure_usd"])
        total_window_exposure_usd = _WINDOW_TRACKING_STATE["total_exposure_usd"]
        agent_resting_exposure_usd = dict(_WINDOW_TRACKING_STATE["agent_resting_exposure_usd"])
        total_resting_exposure_usd = _WINDOW_TRACKING_STATE["total_resting_exposure_usd"]
    
    # ── Initialize Adaptive Risk ───────────────────────────────────────────────
    per_trade_risk_multiplier = 1.0
    is_halted = False
    current_risk_band = RiskBand.NORMAL
    resume_if_drawdown_improves = False  # Default: manual operator intervention required
    
    # ── Initialize Correlation Tracking (Phase 1 Profitability Enhancement) ──
    correlation_tracking_enabled = correlation_tracking_config.get('enabled', False)
    correlation_threshold = correlation_tracking_config.get('threshold', 0.5)
    correlation_multiplier = 1.0  # Default: no reduction
    
    if correlation_tracking_enabled:
        logger.info(
            f"[RISK-ENVELOPE] Correlation tracking enabled: threshold={correlation_threshold:.2f}"
        )
    else:
        logger.info("[RISK-ENVELOPE] Correlation tracking disabled")
    
    # ── Validation ────────────────────────────────────────────────────────────
    # 2026-07-09: DISABLED per-asset cap rescaling - global allocator handles edge-based allocation
    # The global allocator at agent grid level now manages allocation under venue cap
    # Per-asset caps are no longer rescaled to fit venue cap - this allows best edges to use available venue cap
    # Previous logic: Scale all caps down proportionally to fit exactly into venue cap
    # This was causing equal $0.20 caps per asset, defeating edge-based allocation
    
    # Calculate total_asset_cap for logging (even though we don't rescale)
    total_asset_cap = sum(asset_max_notional_usd.values())
    
    # total_asset_cap = sum(asset_max_notional_usd.values())
    # if total_asset_cap > max_total_notional_usd:
    #     scale_factor = max_total_notional_usd / total_asset_cap
    #     old_total_asset_cap = total_asset_cap
    #     
    #     for asset_symbol in asset_max_notional_usd:
    #         old_cap = asset_max_notional_usd[asset_symbol]
    #         asset_max_notional_usd[asset_symbol] = old_cap * scale_factor
    #     
    #     total_asset_cap = sum(asset_max_notional_usd.values())
    #     
    #     logger.info(
    #         f"[RISK-ENVELOPE] CAPS-RESCALED: Sum of asset caps exceeded venue cap - "
    #         f"old sum=${old_total_asset_cap:.2f} -> new sum=${total_asset_cap:.2f} "
    #         f"(scale_factor={scale_factor:.4f}, venue_cap=${max_total_notional_usd:.2f})"
    #     )
    #     for asset_symbol in asset_max_notional_usd:
    #         logger.info(
    #             f"[RISK-ENVELOPE] Asset {asset_symbol}: "
    #             f"rescaled cap=${asset_max_notional_usd[asset_symbol]:.2f}"
    #         )
    
    logger.info(
        "[RISK-ENVELOPE] Per-asset cap rescaling DISABLED - global allocator handles edge-based allocation under venue cap"
    )
    
    # Ensure per-trade cap is reasonable relative to bankroll
    if max_single_order_notional_usd > live_bankroll_usd:
        logger.warning(
            f"[RISK-ENVELOPE] WARNING: Per-trade cap (${max_single_order_notional_usd:.2f}) "
            f"exceeds live bankroll (${live_bankroll_usd:.2f}). "
            f"Orders will be rejected due to insufficient funds."
        )
    
    # ── Return Envelope ────────────────────────────────────────────────────────
    # 2026-07-08: DISABLED percentage-based window limits - using fixed $1 exposure model
    fixed_exposure_cap_usd = float(os.getenv('MERID_FIXED_EXPOSURE_CAP_USD', '1.00'))
    per_agent_window_limit_usd = fixed_exposure_cap_usd
    total_venue_window_limit_usd = fixed_exposure_cap_usd
    
    envelope = KalshiCrypto15mRiskEnvelope(
        live_bankroll_usd=live_bankroll_usd,
        profile_capital_usd=profile_capital,
        max_single_order_notional_usd=max_single_order_notional_usd,
        max_total_notional_usd=max_total_notional_usd,
        max_concurrent_trades=max_concurrent_trades,
        asset_max_notional_usd=asset_max_notional_usd,
        asset_depth_thresholds=asset_depth_thresholds,
        agent_max_notional_usd=agent_max_notional_usd,
        agent_max_orders_per_window=agent_max_orders_per_window,
        agent_max_yes_position=agent_max_yes_position,
        agent_max_no_position=agent_max_no_position,
        max_cycle_risk_pct=max_cycle_risk_pct,
        guardrails_per_window_risk_pct=guardrails_per_window_risk_pct,
        guardrails_total_venue_risk_pct=guardrails_total_venue_risk_pct,
        per_agent_window_limit_usd=per_agent_window_limit_usd,
        total_venue_window_limit_usd=total_venue_window_limit_usd,
        window_start_ts=window_start_ts,
        agent_window_exposure_usd=agent_window_exposure_usd,
        total_window_exposure_usd=total_window_exposure_usd,
        agent_resting_exposure_usd=agent_resting_exposure_usd,
        total_resting_exposure_usd=total_resting_exposure_usd,
        daily_loss_enabled=daily_loss_enabled,
        max_daily_loss_usd=max_daily_loss_usd,
        drawdown_halt_pct=drawdown_halt_pct,
        drawdown_unwind_pct=drawdown_unwind_pct,
        peak_equity_usd=peak_equity_usd,
        current_equity_usd=current_equity_usd,
        current_drawdown_pct=current_drawdown_pct,
        kelly_fraction=kelly_fraction,
        adaptive_risk_bands=adaptive_risk_bands,
        per_trade_risk_multiplier=per_trade_risk_multiplier,
        is_halted=is_halted,
        current_risk_band=current_risk_band,
        resume_if_drawdown_improves=resume_if_drawdown_improves,
        correlation_tracking_enabled=correlation_tracking_enabled,
        correlation_threshold=correlation_threshold,
        correlation_multiplier=correlation_multiplier,
    )
    
    # ── Log Envelope Snapshot ───────────────────────────────────────────────────
    logger.info(
        "[RISK-ENVELOPE-SNAPSHOT] "
        f"live_bankroll=${live_bankroll_usd:.2f} "
        f"profile_capital=${profile_capital:.2f} "
        f"venue_cap=${max_total_notional_usd:.2f} "
        f"sum_caps=${total_asset_cap:.2f} "
        f"scaled={total_asset_cap > max_total_notional_usd}"
    )
    logger.info(
        f"[RISK-ENVELOPE-SNAPSHOT] Global slot allocator enforces ${fixed_exposure_cap_usd:.2f} total exposure across all assets "
        f"(per-asset caps shown below are upper bounds, actual allocation managed by slot allocator)"
    )
    for asset_symbol, cap in asset_max_notional_usd.items():
        # 2026-07-08: DISABLED percentage-based snapshot - using fixed $1 exposure model
        logger.info(
            f"[RISK-ENVELOPE-SNAPSHOT] {asset_symbol}: "
            f"final_cap=${cap:.2f}"
        )
    
    return envelope


def get_kalshi_crypto_15m_risk_envelope(test_bankroll_usd: Optional[float] = None) -> KalshiCrypto15mRiskEnvelope:
    """
    Convenience function to compute risk envelope with live bankroll from BankrollServiceV2.
    
    Args:
        test_bankroll_usd: Optional bankroll value for testing (bypasses BankrollServiceV2)
    
    Returns:
        KalshiCrypto15mRiskEnvelope with all computed risk limits
        
    Raises:
        RuntimeError: If bankroll service fails or returns invalid data
    """
    logger.info("[RISK-ENVELOPE] get_kalshi_crypto_15m_risk_envelope() called")
    
    # Use test bankroll if provided (for testing)
    if test_bankroll_usd is not None:
        live_bankroll_usd = test_bankroll_usd
        logger.info(f"[RISK-ENVELOPE] Using test bankroll: ${live_bankroll_usd}")
    else:
        try:
            from merid.event_venues.kalshi.bankroll_service_v2 import get_equity_for_risk_calc_sync
            live_bankroll_usd = get_equity_for_risk_calc_sync()
            logger.info(f"[RISK-ENVELOPE] Retrieved live bankroll: ${live_bankroll_usd}")
        except Exception as e:
            logger.error(
                f"[RISK-ENVELOPE] Failed to get live bankroll: {e} - "
                f"bankroll service unavailable, risk envelope cannot be computed",
                exc_info=True
            )
            raise RuntimeError(f"Failed to get live bankroll: {e}")
        
        if live_bankroll_usd is None or live_bankroll_usd <= 0:
            logger.warning(f"[RISK-ENVELOPE] Bankroll not ready yet (${live_bankroll_usd}), deferring envelope computation")
            raise RuntimeError(f"Bankroll not ready: ${live_bankroll_usd}")
    
    envelope = compute_kalshi_crypto_15m_risk_envelope(live_bankroll_usd)
    logger.info(f"[RISK-ENVELOPE] Computed envelope successfully: per_agent_limit={envelope.per_agent_window_limit_usd:.2f} total_venue_limit={envelope.total_venue_window_limit_usd:.2f}")
    return envelope


def safe_update_envelope_equity(envelope: KalshiCrypto15mRiskEnvelope) -> bool:
    """
    Safely update envelope equity with error handling.
    
    This is the preferred method for updating equity in the hot path.
    On failure, logs error and returns False without raising.
    
    Args:
        envelope: Risk envelope to update
        
    Returns:
        True if update succeeded, False otherwise
    """
    try:
        from merid.event_venues.kalshi.bankroll_service_v2 import get_equity_for_risk_calc_sync
        current_equity = get_equity_for_risk_calc_sync()
        
        # Handle None equity - fail-closed with clear logging
        if current_equity is None:
            logger.error(
                "[RISK-ENVELOPE] Failed to update equity: get_equity_for_risk_calc_sync returned None - "
                "bankroll service may not be initialized or failed to fetch, equity update failed"
            )
            return False
        
        envelope.update_drawdown(current_equity)
        
        # Collect drift metrics for risk envelope vs positions
        try:
            from merid.monitoring.drift_metrics import get_drift_metrics_collector
            from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
            
            drift_collector = get_drift_metrics_collector()
            fills_ledger = get_fills_ledger()
            
            # Get current exposure from fills ledger
            realized_exposure_usd = fills_ledger.get_total_exposure_usd() if fills_ledger else 0.0
            pending_orders_notional_usd = 0.0  # NOTE: Order tracker integration pending - currently using 0
            
            # Collect drift metric
            drift_collector.collect_risk_envelope_drift(
                envelope_max_notional_usd=envelope.max_total_notional_usd,
                realized_exposure_usd=realized_exposure_usd,
                pending_orders_notional_usd=pending_orders_notional_usd
            )
        except Exception as drift_err:
            logger.debug(f"[RISK-ENVELOPE] Failed to collect drift metrics: {drift_err}")
        
        return True
    except Exception as e:
        logger.error(
            f"[RISK-ENVELOPE] Failed to update equity: {e} - "
            f"equity update failed, risk envelope not updated"
        )
        return False


def reset_for_fresh_start(envelope: KalshiCrypto15mRiskEnvelope):
    """
    Reset envelope state for fresh start.
    
    Called when MERID_FRESH_START=1 to prevent old drawdown state from persisting.
    
    Args:
        envelope: Risk envelope to reset
    """
    envelope.peak_equity_usd = envelope.current_equity_usd
    envelope.current_drawdown_pct = 0.0
    envelope.per_trade_risk_multiplier = 1.0
    envelope.is_halted = False
    envelope.current_risk_band = RiskBand.NORMAL
    logger.info("[RISK-ENVELOPE] Reset for fresh start")

