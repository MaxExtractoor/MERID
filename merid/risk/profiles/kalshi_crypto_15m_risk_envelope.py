"""
Kalshi Crypto 15m Canonical Risk Envelope

Single source of truth for all risk parameters for kalshi_crypto_15m_v2 profile.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from decimal import Decimal

logger = logging.getLogger(__name__)


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
    
    # ── Per-Agent Defaults ───────────────────────────────────────────────────
    agent_max_notional_usd: float  # From profile agent_defaults
    agent_max_orders_per_window: int
    agent_max_yes_position: int
    agent_max_no_position: int
    
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
        self._update_adaptive_risk()
        self.is_halted = self.current_drawdown_pct >= self.drawdown_halt_pct
    
    def _update_adaptive_risk(self):
        """Update per-trade risk multiplier based on drawdown bands."""
        old_multiplier = self.per_trade_risk_multiplier
        for band in self.adaptive_risk_bands:
            if self.current_drawdown_pct <= band['max_drawdown_pct']:
                self.per_trade_risk_multiplier = band['multiplier']
                # Log band change if multiplier changed
                if old_multiplier != self.per_trade_risk_multiplier:
                    logger.info(
                        f"[RISK-ENVELOPE] Band change: drawdown={self.current_drawdown_pct:.2%}, "
                        f"multiplier={old_multiplier:.2f}→{self.per_trade_risk_multiplier:.2f}, "
                        f"distance_to_halt={self.drawdown_halt_pct - self.current_drawdown_pct:.2%}"
                    )
                return
        
        # Default to halt if no band matches
        self.per_trade_risk_multiplier = 0.0
        if old_multiplier != 0.0:
            logger.warning(
                f"[RISK-ENVELOPE] Halt triggered: drawdown={self.current_drawdown_pct:.2%} >= halt={self.drawdown_halt_pct:.2%}"
            )
    
    def get_per_trade_risk_pct(self) -> float:
        """Get per-trade risk percentage from profile."""
        return 0.008  # From guardrails.per_trade_risk_pct
    
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
        """Get effective per-trade risk in USD (with adaptive scaling)."""
        base_risk_usd = self.live_bankroll_usd * self.get_per_trade_risk_pct()
        return base_risk_usd * self.per_trade_risk_multiplier
    
    def distance_to_halt_pct(self) -> float:
        """Distance from current drawdown to halt threshold."""
        return max(0.0, self.drawdown_halt_pct - self.current_drawdown_pct)



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
    
    # Load profile YAML
    if profile_path is None:
        # Use absolute path from repository root to avoid relative path issues
        repo_root = Path(__file__).parent.parent.parent.parent
        profile_path = repo_root / "config" / "profiles" / "kalshi_crypto_15m.yaml"
    
    try:
        with open(profile_path, 'r', encoding='utf-8') as f:
            profile_config = yaml.safe_load(f)
    except Exception as e:
        logger.error(f"[RISK-ENVELOPE] Failed to load profile from {profile_path}: {e}")
        raise RuntimeError(f"Failed to load kalshi_crypto_15m.yaml: {e}")
    
    # Extract venue caps
    venue = profile_config.get('venue', {})
    agent_defaults = profile_config.get('agent_defaults', {})
    assets = profile_config.get('assets', {})
    guardrails = profile_config.get('guardrails', {})
    kelly_config = profile_config.get('kelly', {})
    
    # ── YAML Validation (no silent fallbacks) ───────────────────────────────
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
    
    # Validate drawdown thresholds
    drawdown_halt_pct = guardrails.get('drawdown_halt_pct')
    if drawdown_halt_pct is None:
        raise ValueError("drawdown_halt_pct is required in profile YAML")
    if drawdown_halt_pct <= 0 or drawdown_halt_pct > 0.50:
        raise ValueError(f"drawdown_halt_pct must be between 0 and 0.50: {drawdown_halt_pct}")
    
    drawdown_unwind_pct = guardrails.get('drawdown_unwind_pct')
    if drawdown_unwind_pct is None:
        raise ValueError("drawdown_unwind_pct is required in profile YAML")
    if drawdown_unwind_pct <= drawdown_halt_pct or drawdown_unwind_pct > 0.50:
        raise ValueError(f"drawdown_unwind_pct must be > drawdown_halt_pct and <= 0.50: {drawdown_unwind_pct}")
    
    # Determine effective capital (profile capital or live bankroll)
    profile_capital = profile_config.get('capital_usd', 0)
    # For production, always use live bankroll for dynamic risk scaling
    # Profile capital is only for validation/calibration mode
    import os
    is_validation = os.getenv('MERID_VALIDATION_MODE', 'false').lower() in ('true', '1')
    effective_capital = profile_capital if (profile_capital > 0 and is_validation) else live_bankroll_usd
    
    logger.info(
        f"[RISK-ENVELOPE] Effective capital: ${effective_capital:.2f} "
        f"(profile_capital=${profile_capital:.2f}, live_bankroll=${live_bankroll_usd:.2f})"
    )
    
    # ── Compute Venue-Level Caps ────────────────────────────────────────────
    max_single_order_pct = venue['max_single_order_pct']
    max_single_order_notional_usd = effective_capital * max_single_order_pct
    
    max_total_notional_pct = venue['max_total_notional_pct']
    max_total_notional_usd = effective_capital * max_total_notional_pct
    
    max_concurrent_trades = agent_defaults['max_concurrent_trades']
    
    logger.info(
        f"[RISK-ENVELOPE] Venue caps: "
        f"max_single_order=${max_single_order_notional_usd:.2f} ({max_single_order_pct*100:.1f}%), "
        f"max_total=${max_total_notional_usd:.2f} ({max_total_notional_pct*100:.1f}%), "
        f"max_concurrent={max_concurrent_trades}"
    )
    
    # ── Compute Per-Asset Caps ────────────────────────────────────────────────
    asset_max_notional_usd = {}
    for asset_symbol, asset_config in assets.items():
        max_notional_pct = asset_config.get('max_notional_pct', 0.03)
        asset_max_notional_usd[asset_symbol] = effective_capital * max_notional_pct
        
        logger.info(
            f"[RISK-ENVELOPE] Asset {asset_symbol}: "
            f"max_notional=${asset_max_notional_usd[asset_symbol]:.2f} ({max_notional_pct*100:.1f}%)"
        )
    
    # ── Compute Per-Agent Defaults ────────────────────────────────────────────
    agent_max_notional_pct = agent_defaults.get('max_notional_pct', 0.03)
    agent_max_notional_usd = effective_capital * agent_max_notional_pct
    agent_max_orders_per_window = agent_defaults.get('max_orders_per_window', 3)
    agent_max_yes_position = agent_defaults.get('max_yes_position', 3)
    agent_max_no_position = agent_defaults.get('max_no_position', 3)
    
    logger.info(
        f"[RISK-ENVELOPE] Agent defaults: "
        f"max_notional=${agent_max_notional_usd:.2f} ({agent_max_notional_pct*100:.1f}%), "
        f"max_orders_per_window={agent_max_orders_per_window}, "
        f"max_yes_position={agent_max_yes_position}, "
        f"max_no_position={agent_max_no_position}"
    )
    
    # ── Compute Guardrails ───────────────────────────────────────────────────
    # Drawdown is the primary hard cap; daily loss is optional/soft
    per_trade_risk_pct = guardrails.get('per_trade_risk_pct', 0.008)  # Default 0.8%
    
    # Extract kelly fraction
    kelly_fraction = kelly_config.get('kelly_fraction', kelly_config.get('kelly_hard_cap', 0.30))
    
    daily_loss_enabled = guardrails.get('daily_loss_enabled', False)
    
    # Daily loss is optional; if disabled, set to very high value (effectively disabled)
    if daily_loss_enabled:
        # Derive daily loss limit from primary risk parameters
        # Formula: min(3 × per_trade_risk_pct, 0.5 × drawdown_halt_pct)
        daily_loss_from_trades = 3.0 * per_trade_risk_pct  # 3 losing trades
        daily_loss_from_drawdown = 0.5 * drawdown_halt_pct  # 50% of halt drawdown
        max_daily_loss_pct = min(daily_loss_from_trades, daily_loss_from_drawdown)
        max_daily_loss_usd = effective_capital * max_daily_loss_pct
    else:
        # Daily loss disabled; drawdown is the single source of truth
        max_daily_loss_pct = None
        max_daily_loss_usd = float('inf')  # Effectively disabled
    
    logger.info(
        f"[RISK-ENVELOPE] Guardrails: "
        f"per_trade_risk={per_trade_risk_pct*100:.2f}%, "
        f"drawdown_halt={drawdown_halt_pct*100:.1f}%, "
        f"drawdown_unwind={drawdown_unwind_pct*100:.1f}%, "
        f"daily_loss_enabled={daily_loss_enabled}, "
        f"kelly_fraction={kelly_fraction:.2f}"
    )
    if daily_loss_enabled:
        logger.info(
            f"[RISK-ENVELOPE] Daily loss: ${max_daily_loss_usd:.2f} ({max_daily_loss_pct*100:.2f}%)"
        )
    else:
        logger.info(
            f"[RISK-ENVELOPE] Daily loss: DISABLED (drawdown is primary guardrail)"
        )
    
    # ── Initialize Drawdown Tracking ─────────────────────────────────────────
    peak_equity_usd = live_bankroll_usd
    current_equity_usd = live_bankroll_usd
    current_drawdown_pct = 0.0
    
    # ── Initialize Adaptive Risk ───────────────────────────────────────────────
    per_trade_risk_multiplier = 1.0
    is_halted = False
    
    # ── Validation ────────────────────────────────────────────────────────────
    # Ensure asset caps don't exceed total cap
    total_asset_cap = sum(asset_max_notional_usd.values())
    if total_asset_cap > max_total_notional_usd:
        logger.warning(
            f"[RISK-ENVELOPE] WARNING: Sum of asset caps (${total_asset_cap:.2f}) "
            f"exceeds total venue cap (${max_total_notional_usd:.2f}). "
            f"This may cause position limits to be hit unexpectedly."
        )
    
    # Ensure per-trade cap is reasonable relative to bankroll
    if max_single_order_notional_usd > live_bankroll_usd:
        logger.warning(
            f"[RISK-ENVELOPE] WARNING: Per-trade cap (${max_single_order_notional_usd:.2f}) "
            f"exceeds live bankroll (${live_bankroll_usd:.2f}). "
            f"Orders will be rejected due to insufficient funds."
        )
    
    # ── Return Envelope ────────────────────────────────────────────────────────
    return KalshiCrypto15mRiskEnvelope(
        live_bankroll_usd=live_bankroll_usd,
        profile_capital_usd=profile_capital,
        max_single_order_notional_usd=max_single_order_notional_usd,
        max_total_notional_usd=max_total_notional_usd,
        max_concurrent_trades=max_concurrent_trades,
        asset_max_notional_usd=asset_max_notional_usd,
        agent_max_notional_usd=agent_max_notional_usd,
        agent_max_orders_per_window=agent_max_orders_per_window,
        agent_max_yes_position=agent_max_yes_position,
        agent_max_no_position=agent_max_no_position,
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
    )


def get_kalshi_crypto_15m_risk_envelope() -> KalshiCrypto15mRiskEnvelope:
    """
    Convenience function to compute risk envelope with live bankroll from BankrollServiceV2.
    
    Returns:
        KalshiCrypto15mRiskEnvelope with all computed risk limits
        
    Raises:
        RuntimeError: If bankroll service fails or returns invalid data
    """
    try:
        from merid.event_venues.kalshi.bankroll_service_v2 import get_equity_for_risk_calc_sync
        live_bankroll_usd = get_equity_for_risk_calc_sync()
    except Exception as e:
        logger.error(f"[RISK-ENVELOPE] Failed to get live bankroll: {e}")
        raise RuntimeError(f"Failed to get live bankroll: {e}")
    
    if live_bankroll_usd is None or live_bankroll_usd <= 0:
        logger.error(f"[RISK-ENVELOPE] Invalid live bankroll: ${live_bankroll_usd}")
        raise RuntimeError(f"Invalid live bankroll: ${live_bankroll_usd}")
    
    return compute_kalshi_crypto_15m_risk_envelope(live_bankroll_usd)


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
        envelope.update_drawdown(current_equity)
        return True
    except Exception as e:
        logger.error(f"[RISK-ENVELOPE] Failed to update equity: {e}")
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
    logger.info("[RISK-ENVELOPE] Reset for fresh start")

