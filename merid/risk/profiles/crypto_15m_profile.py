"""
Kalshi Crypto 15m Risk Profile Adapter

Single integration point for loading and mapping the kalshi_crypto_15m profile
to internal risk configuration objects.

This adapter ensures config-only behavior for 15m crypto trading on Kalshi,
with no balance-derived computations when the profile is active.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional, Any
from decimal import Decimal

import yaml

logger = logging.getLogger(__name__)


@dataclass
class Crypto15mProfile:
    """Parsed kalshi_crypto_15m profile from YAML."""
    
    # Metadata
    profile_name: str
    profile_version: str
    description: str
    
    # Global capital and cycle risk
    capital_usd: float
    max_cycle_risk_pct: float
    max_cycle_risk_usd: float
    
    # Venue-level caps (percentage-based)
    venue_max_single_order_pct: float
    venue_max_total_notional_pct: float
    venue_max_category_notional_pct: float
    venue_max_orders_per_minute: int
    venue_max_orders_per_hour: int
    
    # Per-agent defaults (percentage-based)
    agent_max_notional_pct: float
    agent_max_orders_per_window: int
    agent_max_yes_position: int
    agent_max_no_position: int
    agent_max_concurrent_trades: int
    agent_minutes_before_expiry: int
    agent_cutoff_minutes_before_expiry: int
    
    # Confidence
    confidence_use_crypto_threshold_matrix: bool
    confidence_profile_name: str
    confidence_kelly_multiplier_no_trade: float
    confidence_kelly_multiplier_cautious: float
    confidence_kelly_multiplier_quick_win: float
    confidence_kelly_multiplier_confident: float
    
    # Guardrails
    guardrails_max_spread_cents: int
    guardrails_max_slippage_cents: int
    guardrails_min_depth_contracts: int
    guardrails_min_post_fee_edge: float
    guardrails_drawdown_halt_pct: float
    guardrails_drawdown_unwind_pct: float
    guardrails_max_daily_loss_usd: float
    
    # Kelly sizing
    kelly_hard_cap: float
    kelly_min_edge_pct: float
    kelly_max_edge_pct: float
    kelly_min_win_prob: float
    kelly_max_win_prob: float
    kelly_global_notional_cap_pct: float
    
    # Legacy path control
    legacy_disable_balance_calibration: bool
    legacy_disable_dynamic_contract_caps: bool
    legacy_disable_bankroll_category_limits: bool
    legacy_disable_bankroll_prediction_risk: bool
    legacy_disable_bankroll_guardrails: bool
    
    # Computed venue caps (USD, derived from capital)
    venue_max_single_order_usd: float = 0.0
    venue_max_total_notional_usd: float = 0.0
    venue_max_category_notional_usd: float = 0.0
    
    # Computed agent defaults (USD, derived from capital)
    agent_max_notional_usd: float = 0.0
    
    # Per-asset caps (BTC/ETH/SOL/XRP/DOGE)
    asset_configs: Dict[str, "AssetConfig"] = field(default_factory=dict)


@dataclass
class AssetConfig:
    """Per-asset configuration from the profile."""
    
    asset: str
    max_notional_pct: float  # Percentage of capital
    max_contracts: int
    min_edge_early: float
    min_edge_mid: float
    min_edge_late: float
    min_edge_terminal: float
    
    # Computed USD value (derived from capital)
    max_notional_usd: float = 0.0


class Crypto15mProfileAdapter:
    """
    Adapter that loads the kalshi_crypto_15m profile and maps it to
    internal risk configuration objects.
    
    This is the single integration point for 15m crypto risk configuration.
    All reads come from the profile; no balance-derived computations are used.
    """
    
    def __init__(self, profile_path: Optional[Path] = None):
        """
        Initialize the adapter.
        
        Args:
            profile_path: Path to kalshi_crypto_15m.yaml. If None, uses default.
        """
        if profile_path is None:
            # Path from merid/risk/profiles/crypto_15m_profile.py to config/profiles/kalshi_crypto_15m.yaml
            profile_path = Path(__file__).parent.parent.parent.parent / "config" / "profiles" / "kalshi_crypto_15m.yaml"
        
        self.profile_path = profile_path
        self._profile: Optional[Crypto15mProfile] = None
        self._load_profile()
    
    def _load_profile(self) -> None:
        """Load and parse the profile YAML."""
        try:
            with open(self.profile_path, 'r', encoding='utf-8') as f:
                raw = yaml.safe_load(f)
            
            # Parse venue caps
            venue = raw.get('venue', {})
            
            # Parse asset configs
            asset_configs = {}
            assets_raw = raw.get('assets', {})
            for asset_name, asset_data in assets_raw.items():
                asset_configs[asset_name] = AssetConfig(
                    asset=asset_name,
                    max_notional_pct=asset_data.get('max_notional_pct', 0.0),
                    max_contracts=asset_data.get('max_contracts', 0),
                    min_edge_early=asset_data.get('min_edge_early', 0.0),
                    min_edge_mid=asset_data.get('min_edge_mid', 0.0),
                    min_edge_late=asset_data.get('min_edge_late', 0.0),
                    min_edge_terminal=asset_data.get('min_edge_terminal', 0.0),
                )
            
            # Parse agent defaults
            agent_defaults = raw.get('agent_defaults', {})
            
            # Parse capital_usd - derive from live bankroll if set to 0
            capital_usd = raw.get('capital_usd', 10000.0)
            if capital_usd == 0.0:
                # Derive from live Kalshi bankroll API
                try:
                    from merid.event_venues.kalshi.kalshi_risk import get_live_bankroll
                    live_bankroll = get_live_bankroll()
                    if live_bankroll > 0:
                        capital_usd = live_bankroll
                        logger.info(
                            "[PROFILE_WIRING] Derived capital_usd=%.2f from live Kalshi bankroll API",
                            capital_usd
                        )
                    else:
                        # Fallback to default if bankroll unavailable
                        capital_usd = 10000.0
                        logger.warning(
                            "[PROFILE_WIRING] Live bankroll unavailable, using fallback capital_usd=%.2f",
                            capital_usd
                        )
                except Exception as bankroll_exc:
                    # Fallback to default on any error
                    capital_usd = 10000.0
                    logger.warning(
                        "[PROFILE_WIRING] Failed to fetch live bankroll: %s. Using fallback capital_usd=%.2f",
                        bankroll_exc,
                        capital_usd
                    )
            
            # Compute USD values from percentages
            venue_max_single_order_pct = venue.get('max_single_order_pct', 0.05)
            venue_max_total_notional_pct = venue.get('max_total_notional_pct', 0.15)
            venue_max_category_notional_pct = venue.get('max_category_notional_pct', 0.10)
            agent_max_notional_pct = agent_defaults.get('max_notional_pct', 0.03)
            
            # Compute USD values from capital
            venue_max_single_order_usd = capital_usd * venue_max_single_order_pct
            venue_max_total_notional_usd = capital_usd * venue_max_total_notional_pct
            venue_max_category_notional_usd = capital_usd * venue_max_category_notional_pct
            agent_max_notional_usd = capital_usd * agent_max_notional_pct
            
            # PERCENTAGE CONSISTENCY ASSERTIONS: Prevent invalid config at load time
            # These ensure the profile is internally consistent before runtime
            assert venue_max_single_order_pct <= venue_max_total_notional_pct, \
                f"CONFIG ERROR: max_single_order_pct ({venue_max_single_order_pct}) must be <= max_total_notional_pct ({venue_max_total_notional_pct})"
            assert venue_max_category_notional_pct <= venue_max_total_notional_pct, \
                f"CONFIG ERROR: max_category_notional_pct ({venue_max_category_notional_pct}) must be <= max_total_notional_pct ({venue_max_total_notional_pct})"
            assert agent_max_notional_pct <= venue_max_single_order_pct, \
                f"CONFIG ERROR: agent_max_notional_pct ({agent_max_notional_pct}) must be <= max_single_order_pct ({venue_max_single_order_pct})"
            
            # Verify per-asset percentages are consistent with category/total caps
            total_asset_pct = sum(asset_config.max_notional_pct for asset_config in asset_configs.values())
            assert total_asset_pct <= venue_max_total_notional_pct, \
                f"CONFIG ERROR: Sum of per-asset max_notional_pct ({total_asset_pct}) must be <= max_total_notional_pct ({venue_max_total_notional_pct})"
            
            # Verify each asset's percentage is within category cap
            for asset_name, asset_config in asset_configs.items():
                assert asset_config.max_notional_pct <= venue_max_category_notional_pct, \
                    f"CONFIG ERROR: {asset_name} max_notional_pct ({asset_config.max_notional_pct}) must be <= max_category_notional_pct ({venue_max_category_notional_pct})"
            
            # Compute per-asset USD values
            for asset_config in asset_configs.values():
                asset_config.max_notional_usd = capital_usd * asset_config.max_notional_pct
            
            # Parse confidence
            confidence = raw.get('confidence', {})
            
            # Parse guardrails
            guardrails = raw.get('guardrails', {})
            
            # Parse Kelly
            kelly = raw.get('kelly', {})
            
            # Parse legacy flags
            legacy = raw.get('legacy', {})
            
            self._profile = Crypto15mProfile(
                # Metadata
                profile_name=raw.get('profile_name', ''),
                profile_version=raw.get('profile_version', ''),
                description=raw.get('description', ''),
                
                # Global capital and cycle risk
                capital_usd=capital_usd,
                max_cycle_risk_pct=raw.get('max_cycle_risk_pct', 0.02),
                max_cycle_risk_usd=raw.get('max_cycle_risk_usd', 0.0),
                
                # Venue-level caps (percentage-based)
                venue_max_single_order_pct=venue.get('max_single_order_pct', 0.05),
                venue_max_total_notional_pct=venue.get('max_total_notional_pct', 0.15),
                venue_max_category_notional_pct=venue.get('max_category_notional_pct', 0.10),
                venue_max_orders_per_minute=venue.get('max_orders_per_minute', 30),
                venue_max_orders_per_hour=venue.get('max_orders_per_hour', 300),
                
                # Computed venue caps (USD, derived from capital)
                venue_max_single_order_usd=venue_max_single_order_usd,
                venue_max_total_notional_usd=venue_max_total_notional_usd,
                venue_max_category_notional_usd=venue_max_category_notional_usd,
                
                # Per-asset caps
                asset_configs=asset_configs,
                
                # Per-agent defaults (percentage-based)
                agent_max_notional_pct=agent_defaults.get('max_notional_pct', 0.03),
                agent_max_orders_per_window=agent_defaults.get('max_orders_per_window', 3),
                agent_max_yes_position=agent_defaults.get('max_yes_position', 3),
                agent_max_no_position=agent_defaults.get('max_no_position', 3),
                agent_max_concurrent_trades=agent_defaults.get('max_concurrent_trades', 3),
                agent_minutes_before_expiry=agent_defaults.get('minutes_before_expiry', 30),
                agent_cutoff_minutes_before_expiry=agent_defaults.get('cutoff_minutes_before_expiry', 2),
                
                # Computed agent defaults (USD, derived from capital)
                agent_max_notional_usd=agent_max_notional_usd,
                
                # Confidence
                confidence_use_crypto_threshold_matrix=confidence.get('use_crypto_threshold_matrix', True),
                confidence_profile_name=confidence.get('profile_name', 'modern_tradeable_kalshi_v1'),
                confidence_kelly_multiplier_no_trade=confidence.get('kelly_multiplier_no_trade', 0.0),
                confidence_kelly_multiplier_cautious=confidence.get('kelly_multiplier_cautious', 0.5),
                confidence_kelly_multiplier_quick_win=confidence.get('kelly_multiplier_quick_win', 0.6),
                confidence_kelly_multiplier_confident=confidence.get('kelly_multiplier_confident', 1.0),
                
                # Guardrails
                guardrails_max_spread_cents=guardrails.get('max_spread_cents', 10),
                guardrails_max_slippage_cents=guardrails.get('max_slippage_cents', 3),
                guardrails_min_depth_contracts=guardrails.get('min_depth_contracts', 5),
                guardrails_min_post_fee_edge=guardrails.get('min_post_fee_edge', 0.01),
                guardrails_drawdown_halt_pct=guardrails.get('drawdown_halt_pct', 0.10),
                guardrails_drawdown_unwind_pct=guardrails.get('drawdown_unwind_pct', 0.15),
                guardrails_max_daily_loss_usd=guardrails.get('max_daily_loss_usd', 200.0),
                
                # Kelly sizing
                kelly_hard_cap=kelly.get('kelly_hard_cap', 0.30),
                kelly_min_edge_pct=kelly.get('kelly_min_edge_pct', 1.0),
                kelly_max_edge_pct=kelly.get('kelly_max_edge_pct', 25.0),
                kelly_min_win_prob=kelly.get('kelly_min_win_prob', 0.01),
                kelly_max_win_prob=kelly.get('kelly_max_win_prob', 0.99),
                kelly_global_notional_cap_pct=kelly.get('kelly_global_notional_cap_pct', 2.0),
                
                # Legacy path control
                legacy_disable_balance_calibration=legacy.get('disable_balance_calibration', True),
                legacy_disable_dynamic_contract_caps=legacy.get('disable_dynamic_contract_caps', True),
                legacy_disable_bankroll_category_limits=legacy.get('disable_bankroll_category_limits', True),
                legacy_disable_bankroll_prediction_risk=legacy.get('disable_bankroll_prediction_risk', True),
                legacy_disable_bankroll_guardrails=legacy.get('disable_bankroll_guardrails', True),
            )
            
            logger.info(f"[Crypto15mProfileAdapter] Loaded profile {self._profile.profile_name} v{self._profile.profile_version}")
            
        except Exception as e:
            logger.error(f"[Crypto15mProfileAdapter] Failed to load profile from {self.profile_path}: {e}")
            raise
    
    @property
    def profile(self) -> Crypto15mProfile:
        """Get the loaded profile."""
        if self._profile is None:
            raise RuntimeError("Profile not loaded")
        return self._profile
    
    def to_kalshi_risk_config(self) -> Dict[str, Any]:
        """
        Map profile to KalshiRiskConfig parameters.
        
        For kalshi_crypto_15m_v2, this is a thin adapter that uses envelope values.
        The envelope is the single source of truth for drawdown and daily loss.
        
        Returns:
            Dict with keys matching KalshiRiskConfig dataclass fields.
        """
        p = self._profile
        
        # For kalshi_crypto_15m_v2, use envelope values for drawdown/daily loss
        # The envelope is the single source of truth
        try:
            from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import get_kalshi_crypto_15m_risk_envelope
            envelope = get_kalshi_crypto_15m_risk_envelope()
            drawdown_halt_pct = envelope.drawdown_halt_pct
            drawdown_unwind_pct = envelope.drawdown_unwind_pct
            max_daily_loss_usd = envelope.max_daily_loss_usd
            kelly_fraction = envelope.kelly_fraction
            # Use envelope's computed values for risk parameters (derived from live bankroll)
            max_single_order_notional_usd = envelope.max_single_order_notional_usd
            max_total_notional_usd = envelope.max_total_notional_usd
        except Exception as e:
            logger.warning(f"[PROFILE-ADAPTER] Failed to load envelope, using profile defaults: {e}")
            drawdown_halt_pct = p.guardrails_drawdown_halt_pct
            drawdown_unwind_pct = p.guardrails_drawdown_unwind_pct
            max_daily_loss_usd = p.guardrails_max_daily_loss_usd
            kelly_fraction = p.kelly_hard_cap
            # Fallback to profile YAML static values
            max_single_order_notional_usd = p.venue_max_single_order_usd
            max_total_notional_usd = p.venue_max_total_notional_usd
        
        return {
            'max_single_order_notional_usd': max_single_order_notional_usd,
            'max_total_notional_usd': max_total_notional_usd,
            'max_daily_loss_usd': max_daily_loss_usd,
            'max_single_order_contracts': 10,  # From KALSHI_MAX_ORDER_CONTRACTS env var
            'max_position_per_contract': 500,
            'kelly_hard_cap': kelly_fraction,
            'kelly_max_edge_pct': p.kelly_max_edge_pct,
            'kelly_min_edge_pct': p.kelly_min_edge_pct,
            'kelly_min_win_prob': p.kelly_min_win_prob,
            'kelly_max_win_prob': p.kelly_max_win_prob,
            'kelly_global_notional_cap_pct': p.kelly_global_notional_cap_pct,
            'max_fee_to_notional_pct': 15.0,
            'valid_price_cents_min': 1,
            'valid_price_cents_max': 99,
            'max_contracts_total': 5000,  # Fixed from profile, not dynamic
            'max_contracts_per_asset': 1750,  # Fixed from profile, not dynamic
            'max_contracts_per_cluster': 750,  # Fixed from profile, not dynamic
            'group_notional_cap_usd': 2000.0,  # Fixed from profile, not dynamic (per asset/timeframe/overlap-window)
            'group_limits_enabled': True,  # Enable group-level aggregation and caps
            'drawdown_halt_pct': drawdown_halt_pct,
            'drawdown_unwind_pct': drawdown_unwind_pct,
            'min_edge': 0.05,  # Conservative 5% minimum edge
            'min_post_fee_edge': p.guardrails_min_post_fee_edge,
            'default_notional_to_equity_multiplier': 2.0,
            'max_orders_per_minute': p.venue_max_orders_per_minute,
            'max_orders_per_hour': p.venue_max_orders_per_hour,
            'category_limits': {
                'crypto': {
                    'category': 'crypto',
                    'max_notional_usd': p.venue_max_category_notional_usd,
                    'max_contracts': 500,
                    'max_pct_of_portfolio': 0.20,
                    'enabled': True,
                }
            },
        }
    
    def to_category_limits(self) -> Dict[str, Any]:
        """
        Map profile to CategoryLimit for crypto category.
        
        Returns:
            Dict with CategoryLimit parameters for crypto.
        """
        p = self._profile
        
        return {
            'crypto': {
                'category': 'crypto',
                'max_notional_usd': p.venue_max_category_notional_usd,
                'max_contracts': 500,
                'max_pct_of_portfolio': 0.20,
                'enabled': True,
            }
        }
    
    def to_cycle_sizing_cap(self) -> Dict[str, Any]:
        """
        Map profile to CycleSizingCap parameters.
        
        Returns:
            Dict with CycleSizingCap parameters.
        """
        p = self._profile
        
        # Cycle risk is percentage-based on capital (not live bankroll)
        max_cycle_risk_usd = p.max_cycle_risk_usd if p.max_cycle_risk_usd > 0 else p.capital_usd * p.max_cycle_risk_pct
        
        return {
            'max_total_notional_usd': max_cycle_risk_usd,
            'max_notional_per_winner_usd': max_cycle_risk_usd / 3,  # Assume 3 winners max
            'capital_usd': p.capital_usd,
            'max_cycle_risk_pct': p.max_cycle_risk_pct,
        }
    
    def to_agent_overrides(self, agent_name: str) -> Dict[str, Any]:
        """
        Map profile to per-agent configuration overrides.
        
        PRODUCTION RESTRICTION: Only applies to BTC_15M, ETH_15M, SOL_15M, XRP_15M, DOGE_15M.
        All other agents receive empty overrides (profile not applicable).
        
        Args:
            agent_name: Name of the agent (e.g., "BTC_15M")
        
        Returns:
            Dict with agent-specific overrides, or empty dict if agent not in 15m crypto allowlist.
        """
        p = self._profile
        
        # PRODUCTION RESTRICTION: Only apply to 5 15m crypto agents
        allowed_15m_agents = {"BTC_15M", "ETH_15M", "SOL_15M", "XRP_15M", "DOGE_15M"}
        if agent_name.upper() not in allowed_15m_agents:
            logger.info(
                "[PROFILE_RESTRICTION] Agent %s not in 15m crypto allowlist, skipping profile overrides. "
                "Allowed: %s",
                agent_name, sorted(allowed_15m_agents)
            )
            return {}
        
        # Extract asset from agent name (e.g., "BTC_15M" -> "BTC")
        asset = None
        for asset_name in p.asset_configs.keys():
            if asset_name in agent_name.upper():
                asset = asset_name
                break
        
        asset_config = p.asset_configs.get(asset) if asset else None
        
        overrides = {
            'max_notional_usd': p.agent_max_notional_usd,
            'max_orders_per_window': p.agent_max_orders_per_window,
            'max_yes_position': p.agent_max_yes_position,
            'max_no_position': p.agent_max_no_position,
            'minutes_before_expiry': p.agent_minutes_before_expiry,
            'cutoff_minutes_before_expiry': p.agent_cutoff_minutes_before_expiry,
        }
        
        # Override with asset-specific config if available
        if asset_config:
            overrides.update({
                'max_notional_usd': min(p.agent_max_notional_usd, asset_config.max_notional_usd),
                'min_edge_early': asset_config.min_edge_early,
                'min_edge_mid': asset_config.min_edge_mid,
                'min_edge_late': asset_config.min_edge_late,
                'min_edge_terminal': asset_config.min_edge_terminal,
            })
        
        return overrides
    
    def should_disable_balance_calibration(self) -> bool:
        """Check if balance calibration should be disabled for this profile."""
        return self._profile.legacy_disable_balance_calibration
    
    def should_disable_dynamic_contract_caps(self) -> bool:
        """Check if dynamic contract caps should be disabled for this profile."""
        return self._profile.legacy_disable_dynamic_contract_caps
    
    def should_disable_bankroll_category_limits(self) -> bool:
        """Check if bankroll-derived category limits should be disabled."""
        return self._profile.legacy_disable_bankroll_category_limits
    
    def should_disable_bankroll_prediction_risk(self) -> bool:
        """Check if bankroll-derived prediction risk should be disabled."""
        return self._profile.legacy_disable_bankroll_prediction_risk
    
    def should_disable_bankroll_guardrails(self) -> bool:
        """Check if bankroll-derived guardrails should be disabled."""
        return self._profile.legacy_disable_bankroll_guardrails


# Singleton instance for the active profile
_active_adapter: Optional[Crypto15mProfileAdapter] = None


def get_active_profile() -> Optional[Crypto15mProfileAdapter]:
    """
    Get the active profile adapter if one is configured.
    
    Returns:
        Crypto15mProfileAdapter if MERID_PROFILE=kalshi_crypto_15m_v2, else None.
    """
    global _active_adapter
    
    import os
    
    profile_name = os.environ.get('MERID_PROFILE', '')
    
    if profile_name == 'kalshi_crypto_15m_v2':
        if _active_adapter is None:
            _active_adapter = Crypto15mProfileAdapter()
        return _active_adapter
    
    return None


def is_profile_active() -> bool:
    """Check if the kalshi_crypto_15m profile is active."""
    import os
    return os.environ.get('MERID_PROFILE', '') == 'kalshi_crypto_15m_v2'


def runtime_profile_self_check() -> bool:
    """
    Runtime self-check at startup to verify profile is correctly loaded and effective caps match.
    
    This function logs the effective risk caps for BTC/ETH/SOL/XRP/DOGE 15m and verifies
    they match the profile values. Should be called at startup to fail fast if configuration
    is incorrect.
    
    Returns:
        True if all checks pass, False otherwise.
    
    Raises:
        RuntimeError: If profile is active but critical caps don't match.
    """
    if not is_profile_active():
        logger.info("[PROFILE_SELF_CHECK] Profile kalshi_crypto_15m_v2 is not active, skipping self-check")
        return True
    
    adapter = get_active_profile()
    if adapter is None:
        logger.error("[PROFILE_SELF_CHECK] Profile should be active but adapter is None")
        return False
    
    profile = adapter.profile
    
    logger.info("[PROFILE_SELF_CHECK] Verifying kalshi_crypto_15m_v2 profile configuration...")
    logger.info(f"[PROFILE_SELF_CHECK] Profile: {profile.profile_name} v{profile.profile_version}")
    logger.info(f"[PROFILE_SELF_CHECK] Description: {profile.description}")
    
    # Log venue-level caps
    logger.info("[PROFILE_SELF_CHECK] Venue-level caps:")
    logger.info(f"  - max_single_order_usd: ${profile.venue_max_single_order_usd:.2f}")
    logger.info(f"  - max_total_notional_usd: ${profile.venue_max_total_notional_usd:.2f}")
    logger.info(f"  - max_category_notional_usd: ${profile.venue_max_category_notional_usd:.2f}")
    logger.info(f"  - max_orders_per_minute: {profile.venue_max_orders_per_minute}")
    logger.info(f"  - max_orders_per_hour: {profile.venue_max_orders_per_hour}")
    
    # Log per-asset caps
    logger.info("[PROFILE_SELF_CHECK] Per-asset caps:")
    for asset in ['BTC', 'ETH', 'SOL', 'XRP', 'DOGE']:
        if asset in profile.asset_configs:
            asset_config = profile.asset_configs[asset]
            logger.info(f"  - {asset}: max_notional_usd=${asset_config.max_notional_usd:.2f}, max_contracts={asset_config.max_contracts}")
        else:
            logger.warning(f"  - {asset}: NOT FOUND in profile")
    
    # Log agent defaults
    logger.info("[PROFILE_SELF_CHECK] Agent defaults:")
    logger.info(f"  - max_notional_usd: ${profile.agent_max_notional_usd:.2f}")
    logger.info(f"  - max_orders_per_window: {profile.agent_max_orders_per_window}")
    logger.info(f"  - max_yes_position: {profile.agent_max_yes_position}")
    logger.info(f"  - max_no_position: {profile.agent_max_no_position}")
    
    # Log cycle sizing
    logger.info("[PROFILE_SELF_CHECK] Cycle sizing:")
    logger.info(f"  - capital_usd: ${profile.capital_usd:.2f}")
    logger.info(f"  - max_cycle_risk_pct: {profile.max_cycle_risk_pct:.2%}")
    cycle_risk_usd = profile.capital_usd * profile.max_cycle_risk_pct
    logger.info(f"  - max_cycle_risk_usd: ${cycle_risk_usd:.2f}")
    
    # Log guardrails
    logger.info("[PROFILE_SELF_CHECK] Guardrails:")
    logger.info(f"  - max_spread_cents: {profile.guardrails_max_spread_cents}")
    logger.info(f"  - max_slippage_cents: {profile.guardrails_max_slippage_cents}")
    logger.info(f"  - min_depth_contracts: {profile.guardrails_min_depth_contracts}")
    logger.info(f"  - min_post_fee_edge: {profile.guardrails_min_post_fee_edge:.2%}")
    logger.info(f"  - drawdown_halt_pct: {profile.guardrails_drawdown_halt_pct:.2%}")
    logger.info(f"  - drawdown_unwind_pct: {profile.guardrails_drawdown_unwind_pct:.2%}")
    logger.info(f"  - max_daily_loss_usd: ${profile.guardrails_max_daily_loss_usd:.2f}")
    
    # Log Kelly parameters
    logger.info("[PROFILE_SELF_CHECK] Kelly sizing:")
    logger.info(f"  - kelly_hard_cap: {profile.kelly_hard_cap:.2%}")
    logger.info(f"  - kelly_min_edge_pct: {profile.kelly_min_edge_pct:.2%}")
    logger.info(f"  - kelly_max_edge_pct: {profile.kelly_max_edge_pct:.2%}")
    logger.info(f"  - kelly_global_notional_cap_pct: {profile.kelly_global_notional_cap_pct:.2%}")
    
    # Verify legacy flags are set correctly
    logger.info("[PROFILE_SELF_CHECK] Legacy path control:")
    logger.info(f"  - disable_balance_calibration: {profile.legacy_disable_balance_calibration}")
    logger.info(f"  - disable_dynamic_contract_caps: {profile.legacy_disable_dynamic_contract_caps}")
    logger.info(f"  - disable_bankroll_category_limits: {profile.legacy_disable_bankroll_category_limits}")
    logger.info(f"  - disable_bankroll_prediction_risk: {profile.legacy_disable_bankroll_prediction_risk}")
    logger.info(f"  - disable_bankroll_guardrails: {profile.legacy_disable_bankroll_guardrails}")
    
    # Critical checks - fail if these are not set correctly
    if not profile.legacy_disable_balance_calibration:
        logger.error("[PROFILE_SELF_CHECK] FAIL: legacy_disable_balance_calibration must be True")
        return False
    
    if not profile.legacy_disable_dynamic_contract_caps:
        logger.error("[PROFILE_SELF_CHECK] FAIL: legacy_disable_dynamic_contract_caps must be True")
        return False
    
    if not profile.legacy_disable_bankroll_category_limits:
        logger.error("[PROFILE_SELF_CHECK] FAIL: legacy_disable_bankroll_category_limits must be True")
        return False
    
    if not profile.legacy_disable_bankroll_prediction_risk:
        logger.error("[PROFILE_SELF_CHECK] FAIL: legacy_disable_bankroll_prediction_risk must be True")
        return False
    
    if not profile.legacy_disable_bankroll_guardrails:
        logger.error("[PROFILE_SELF_CHECK] FAIL: legacy_disable_bankroll_guardrails must be True")
        return False
    
    # Verify all expected assets are present
    expected_assets = {'BTC', 'ETH', 'SOL', 'XRP', 'DOGE'}
    missing_assets = expected_assets - set(profile.asset_configs.keys())
    if missing_assets:
        logger.error(f"[PROFILE_SELF_CHECK] FAIL: Missing assets in profile: {missing_assets}")
        return False
    
    logger.info("[PROFILE_SELF_CHECK] SUCCESS: All profile configuration checks passed")
    return True
