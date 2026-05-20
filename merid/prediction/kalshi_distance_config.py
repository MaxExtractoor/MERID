"""Kalshi Distance Config — Single Source of Truth for 15m Execution Guards.

This module loads and validates the canonical distance/edge configuration from:
1. Profile YAML (config/profiles/kalshi_crypto_15m.yaml) when MERID_PROFILE=kalshi_crypto_15m_v2
2. Legacy kalshi_distance.yaml for backward compatibility with other profiles

Provides:
1. Runtime access to all distance guards, edge thresholds, and validation rules
2. Startup assertions to ensure config consistency across all components
3. Frozen dataclasses to prevent runtime mutation

Usage:
    from merid.prediction.kalshi_distance_config import get_distance_config
    
    cfg = get_distance_config()
    max_delta = cfg.max_delta_pct["BTC"]  # Reads from profile YAML or kalshi_distance.yaml
    
    # Validate execution parameters
    result = cfg.check_execution_guards(asset="BTC", timeframe="15m", delta_pct=0.005, edge=0.06)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Any

import yaml

from utils.logger import get_logger

logger = get_logger("merid.prediction.kalshi_distance_config")

# Singleton instance
_distance_config: Optional["KalshiDistanceConfig"] = None


@dataclass(frozen=True)
class GuardCheckResult:
    """Result of execution guard validation."""
    allowed: bool
    reason: str
    asset: str
    timeframe: str
    details: Dict[str, Any] = field(default_factory=dict)
    
    def to_log_line(self) -> str:
        """Format as structured log line for grep analysis."""
        base = f"asset={self.asset} tf={self.timeframe} reason={self.reason}"
        if self.details:
            details_str = " ".join(f"{k}={v}" for k, v in self.details.items())
            return f"{base} {details_str}"
        return base


@dataclass(frozen=True)
class KalshiDistanceConfig:
    """Canonical configuration for Kalshi 15m distance guards and edge thresholds.
    
    This is the Single Source of Truth. All components must use this config;
    hardcoded values elsewhere are bugs.
    """
    
    # Meta
    version: str
    
    # Layer 1: Asset/Timeframe Whitelist
    allowed_assets: Set[str]
    execution_timeframes: Set[str]
    signal_only_timeframes: Set[str]
    
    # Layer 2: Distance Caps
    max_delta_pct: Dict[str, float]
    max_z_distance: float
    z_near_threshold: float
    
    # Layer 3: Edge Floors
    min_edge_near: Dict[str, float]
    min_edge_far: Dict[str, float]
    
    # Layer 4: Signal Quality
    max_bar_age_seconds: int
    block_on_stale_signal: bool
    max_spot_divergence_pct: float
    block_on_misaligned_reference: bool
    
    # Layer 5: Fee/EV
    use_tiered_fee_schedule: bool
    fee_mismatch_threshold_pct: float
    min_ev_after_fees_pct: float
    
    # Layer 6: Sizing
    kelly_fraction: float
    max_risk_per_trade_pct: float
    max_15m_positions_per_asset: int
    max_15m_exposure_pct: float
    
    def check_execution_guards(
        self,
        asset: str,
        timeframe: str,
        delta_pct: Optional[float] = None,
        z_score: Optional[float] = None,
        edge: Optional[float] = None,
    ) -> GuardCheckResult:
        """Validate execution against all configured guards.
        
        Args:
            asset: Asset symbol (BTC, ETH, etc.)
            timeframe: Timeframe string (15m, 1h, etc.)
            delta_pct: Spot-to-strike distance (optional)
            z_score: Normalized distance (optional)
            edge: Model edge value (optional)
            
        Returns:
            GuardCheckResult with allowed=True/False and detailed context
        """
        # Layer 1: Asset whitelist
        if asset not in self.allowed_assets:
            return GuardCheckResult(
                allowed=False,
                reason="invalid_asset",
                asset=asset,
                timeframe=timeframe,
                details={"allowed_assets": list(self.allowed_assets)}
            )
        
        # Layer 1: Timeframe execution gate
        if timeframe not in self.execution_timeframes:
            return GuardCheckResult(
                allowed=False,
                reason="non_15m_timeframe",
                asset=asset,
                timeframe=timeframe,
                details={"signal_only": True}
            )
        
        # Layer 2: Hard distance cap
        if delta_pct is not None:
            max_delta = self.max_delta_pct.get(asset, 0.015)
            if abs(delta_pct) > max_delta:
                return GuardCheckResult(
                    allowed=False,
                    reason="distance_too_far",
                    asset=asset,
                    timeframe=timeframe,
                    details={
                        "delta_pct": f"{delta_pct:.4f}",
                        "max_delta_pct": f"{max_delta:.4f}",
                        "z_score": f"{z_score:.2f}" if z_score else "unknown"
                    }
                )
        
        # Layer 2: Sigma-based distance cap
        if z_score is not None:
            if abs(z_score) > self.max_z_distance:
                return GuardCheckResult(
                    allowed=False,
                    reason="distance_too_far_z",
                    asset=asset,
                    timeframe=timeframe,
                    details={
                        "z_score": f"{z_score:.2f}",
                        "max_z_distance": f"{self.max_z_distance:.2f}"
                    }
                )
        
        # Layer 3: Edge floor (near vs far)
        if edge is not None:
            is_far = (z_score is not None and abs(z_score) > self.z_near_threshold)
            min_edge = self.min_edge_far.get(asset, 0.070) if is_far else self.min_edge_near.get(asset, 0.050)
            
            if edge < min_edge:
                return GuardCheckResult(
                    allowed=False,
                    reason="edge_too_low",
                    asset=asset,
                    timeframe=timeframe,
                    details={
                        "edge": f"{edge:.4f}",
                        "required_edge": f"{min_edge:.4f}",
                        "contract_type": "far" if is_far else "near"
                    }
                )
        
        return GuardCheckResult(
            allowed=True,
            reason="allowed",
            asset=asset,
            timeframe=timeframe
        )
    
    def check_signal_staleness(self, last_bar_age_seconds: float) -> Tuple[bool, Optional[str]]:
        """Check if signal is stale.
        
        Returns:
            (is_fresh, reason_if_stale)
        """
        if last_bar_age_seconds > self.max_bar_age_seconds:
            if self.block_on_stale_signal:
                return False, f"stale_signal last_bar_age={last_bar_age_seconds:.0f}s max={self.max_bar_age_seconds}s"
        return True, None
    
    def check_spot_reference_integrity(
        self,
        our_spot: float,
        kalshi_reference: float
    ) -> Tuple[bool, Optional[str], float]:
        """Check spot vs Kalshi reference price alignment.
        
        Returns:
            (is_aligned, reason_if_misaligned, divergence_pct)
        """
        if our_spot <= 0 or kalshi_reference <= 0:
            return False, "invalid_price_inputs", 0.0
        
        divergence = abs(our_spot - kalshi_reference) / our_spot
        
        if divergence > self.max_spot_divergence_pct:
            if self.block_on_misaligned_reference:
                return False, f"reference_misaligned divergence={divergence:.4f} max={self.max_spot_divergence_pct:.4f}", divergence
        
        return True, None, divergence
    
    def validate_all_assets_have_params(self) -> List[str]:
        """Validate that all allowed assets have required parameters.
        
        Returns:
            List of error messages (empty if all valid)
        """
        errors = []
        required_params = ["max_delta_pct", "min_edge_near", "min_edge_far"]
        
        for asset in self.allowed_assets:
            for param in required_params:
                param_dict = getattr(self, param, {})
                if asset not in param_dict:
                    errors.append(f"[CONFIG_ERROR] {asset} missing {param}")
        
        return errors
    
    def to_health_snapshot(self) -> Dict[str, Any]:
        """Generate health snapshot data for [HEALTH_15M] logging."""
        return {
            "version": self.version,
            "allowed_assets": list(self.allowed_assets),
            "execution_timeframes": list(self.execution_timeframes),
            "max_z_distance": self.max_z_distance,
            "z_near_threshold": self.z_near_threshold,
            "max_bar_age_seconds": self.max_bar_age_seconds,
            "kelly_fraction": self.kelly_fraction,
            "max_risk_per_trade_pct": self.max_risk_per_trade_pct,
        }


def _is_scalper_mode() -> bool:
    """Detect if 15m momentum scalper mode is active via env var."""
    import os
    return os.getenv("STRATEGY_MODE", "").upper() == "MOMENTUM_SCALPER"


def _apply_scalper_overrides(raw: dict) -> dict:
    """Apply 15m scalper mode overrides to raw config dict.
    
    This allows runtime mode switching without YAML edits.
    """
    import os
    import copy
    
    result = copy.deepcopy(raw)
    
    # Override sizing constraints for scalper mode
    sizing = result.get("sizing_constraints", {})
    
    # Apply env overrides if available, otherwise use scalper defaults
    max_positions = int(os.getenv("MAX_CONTRACTS_PER_TF_CRYPTO_15M", "8"))
    sizing["max_15m_positions_per_asset"] = max_positions
    
    max_exposure = float(os.getenv("SCALPER15M_BANKROLL_PCT", "0.02")) * 100  # Convert to pct (2% across top-3)
    sizing["max_15m_exposure_pct"] = max_exposure
    
    # Override risk per trade (2% across top-3 edges, priority to top-1)
    risk_pct = float(os.getenv("KALSHI_TRADER_RISK_PCT", "0.03")) * 100
    sizing["max_risk_per_trade_pct"] = risk_pct
    
    result["sizing_constraints"] = sizing
    
    logger.info(f"[SCALPER_MODE] Applied overrides: max_positions={max_positions}, "
                f"max_exposure={max_exposure:.1f}%, risk_per_trade={risk_pct:.1f}%")
    
    return result


def _transform_profile_to_distance_config(profile_raw: dict) -> dict:
    """Transform profile YAML structure to KalshiDistanceConfig format.
    
    The profile YAML (kalshi_crypto_15m.yaml) has a different structure than
    kalshi_distance.yaml. This function maps the profile structure to the
    KalshiDistanceConfig format.
    
    Args:
        profile_raw: Raw profile YAML dict
        
    Returns:
        Transformed dict matching KalshiDistanceConfig expected structure
    """
    assets = profile_raw.get("assets", {})
    agent_defaults = profile_raw.get("agent_defaults", {})
    
    # Extract per-asset max_distance_pct from profile
    max_delta_pct = {}
    min_edge_near = {}
    min_edge_far = {}
    
    for asset, config in assets.items():
        # max_distance_pct from profile → max_delta_pct
        if "max_distance_pct" in config:
            max_delta_pct[asset] = config["max_distance_pct"]
        
        # Edge thresholds from profile (early/mid/late/terminal) → near/far
        # Use mid edge as "near" threshold, terminal as "far" threshold
        if "min_edge_mid" in config:
            min_edge_near[asset] = config["min_edge_mid"]
        if "min_edge_terminal" in config:
            min_edge_far[asset] = config["min_edge_terminal"]
    
    # Build transformed structure
    transformed = {
        "meta": {
            "version": profile_raw.get("profile_version", "1.0.0"),
            "last_updated": "2026-05-17",
            "mandate": profile_raw.get("description", ""),
            "assets": list(assets.keys()),
            "env_override": False,
        },
        
        # Layer 1: Asset & Timeframe Whitelist
        "allowed_assets": list(assets.keys()),
        "execution_timeframes": ["15m"],
        "signal_only_timeframes": ["1h", "daily", "weekly"],
        
        # Layer 2: Distance Caps
        "max_delta_pct": max_delta_pct,
        "max_z_distance": 0.75,  # Default sigma-based cap
        "z_near_threshold": 0.50,  # Default near/far threshold
        
        # Layer 3: Edge Floors
        "min_edge_near": min_edge_near,
        "min_edge_far": min_edge_far,
        
        # Layer 4: Signal Quality
        "signal_staleness": {
            "max_bar_age_seconds": 900,
            "block_on_stale": True,
        },
        "spot_reference_integrity": {
            "max_divergence_pct": 0.005,
            "block_on_misaligned": True,
        },
        
        # Layer 5: Fee/EV
        "fee_schedule": {
            "use_tiered_fee_schedule": True,
            "fee_mismatch_threshold_pct": 5.0,
            "min_ev_after_fees_pct": 1.0,
        },
        
        # Layer 6: Sizing
        "sizing_constraints": {
            "kelly_fraction": 0.25,  # Default fractional Kelly
            "max_risk_per_trade_pct": agent_defaults.get("max_orders_per_window", 3),
            "max_15m_positions_per_asset": agent_defaults.get("max_concurrent_trades", 3),
            "max_15m_exposure_pct": sum(assets.get(a, {}).get("max_notional_pct", 0) for a in assets.keys()) * 100,
        },
    }
    
    logger.info(f"[PROFILE_TRANSFORM] Transformed profile YAML to distance config: "
                f"{len(max_delta_pct)} assets with distance caps, "
                f"{len(min_edge_near)} assets with edge thresholds")
    
    return transformed


def load_distance_config(config_path: Optional[str] = None) -> KalshiDistanceConfig:
    """Load and parse distance configuration from profile YAML or legacy config.
    
    Priority:
    1. Profile YAML (config/profiles/kalshi_crypto_15m.yaml) for kalshi_crypto_15m_v2
    2. Legacy kalshi_distance.yaml ONLY if MERID_ALLOW_LEGACY_DISTANCE_CONFIG=1 (explicit opt-in)
    3. Hard-fail for unknown profiles (no silent fallback)
    
    Args:
        config_path: Override path (default: auto-detect based on profile)
        
    Returns:
        Frozen KalshiDistanceConfig instance
        
    Raises:
        FileNotFoundError: If config file missing
        ValueError: If config invalid
        RuntimeError: If profile is unknown and legacy fallback is disabled
    """
    import os
    
    # Determine config source based on active profile
    profile_name = os.getenv("MERID_PROFILE", "")
    
    if config_path is None:
        # Find relative to this file
        base_dir = Path(__file__).parent.parent.parent
        
        if profile_name == "kalshi_crypto_15m_v2":
            # Load from profile YAML (canonical for 15m crypto)
            config_path = base_dir / "config" / "profiles" / "kalshi_crypto_15m.yaml"
            logger.info(f"[PROFILE_CONFIG] Loading distance config from profile: {config_path}")
        else:
            # Explicit compatibility mode required for legacy config
            if os.getenv("MERID_ALLOW_LEGACY_DISTANCE_CONFIG") == "1":
                config_path = base_dir / "config" / "kalshi_distance.yaml"
                logger.warning(
                    f"[LEGACY_CONFIG] Using legacy kalshi_distance.yaml for profile={profile_name} "
                    f"(MERID_ALLOW_LEGACY_DISTANCE_CONFIG=1). This fallback is deprecated; "
                    f"migrate to profile YAML for dynamic, bankroll-aware config."
                )
            else:
                raise RuntimeError(
                    f"Distance config not defined for profile={profile_name} "
                    f"and legacy fallback is disabled. Define per-profile distance in YAML "
                    f"or set MERID_ALLOW_LEGACY_DISTANCE_CONFIG=1 to opt into legacy behavior."
                )
    
    config_path = Path(config_path)
    
    if not config_path.exists():
        logger.error(f"[CONFIG_ERROR] Distance config not found: {config_path}")
        raise FileNotFoundError(f"Distance config not found: {config_path}")
    
    with open(config_path) as f:
        raw = yaml.safe_load(f)
    
    # If loading from profile YAML, transform structure to match KalshiDistanceConfig
    if profile_name == "kalshi_crypto_15m_v2":
        raw = _transform_profile_to_distance_config(raw)
    
    if _is_scalper_mode():
        logger.info("[SCALPER_MODE] STRATEGY_MODE=MOMENTUM_SCALPER detected - applying overrides")
        raw = _apply_scalper_overrides(raw)
    
    meta = raw.get("meta", {})
    
    # Build frozen config
    cfg = KalshiDistanceConfig(
        version=meta.get("version", "unknown"),
        
        # Layer 1
        allowed_assets=set(raw.get("allowed_assets", [])),
        execution_timeframes=set(raw.get("execution_timeframes", [])),
        signal_only_timeframes=set(raw.get("signal_only_timeframes", [])),
        
        # Layer 2
        max_delta_pct=raw.get("max_delta_pct", {}),
        max_z_distance=float(raw.get("max_z_distance", 0.75)),
        z_near_threshold=float(raw.get("z_near_threshold", 0.50)),
        
        # Layer 3
        min_edge_near=raw.get("min_edge_near", {}),
        min_edge_far=raw.get("min_edge_far", {}),
        
        # Layer 4
        max_bar_age_seconds=int(raw.get("signal_staleness", {}).get("max_bar_age_seconds", 900)),
        block_on_stale_signal=bool(raw.get("signal_staleness", {}).get("block_on_stale", True)),
        max_spot_divergence_pct=float(raw.get("spot_reference_integrity", {}).get("max_divergence_pct", 0.005)),
        block_on_misaligned_reference=bool(raw.get("spot_reference_integrity", {}).get("block_on_misaligned", True)),
        
        # Layer 5
        use_tiered_fee_schedule=bool(raw.get("fee_validation", {}).get("use_tiered_schedule", True)),
        fee_mismatch_threshold_pct=float(raw.get("fee_validation", {}).get("mismatch_threshold_pct", 5.0)),
        min_ev_after_fees_pct=float(raw.get("fee_validation", {}).get("min_ev_after_fees_pct", 0.02)),
        
        # Layer 6
        kelly_fraction=float(raw.get("sizing_constraints", {}).get("kelly_fraction", 0.25)),
        max_risk_per_trade_pct=float(raw.get("sizing_constraints", {}).get("max_risk_per_trade_pct", 1.0)),
        max_15m_positions_per_asset=int(raw.get("sizing_constraints", {}).get("max_15m_positions_per_asset", 3)),
        max_15m_exposure_pct=float(raw.get("sizing_constraints", {}).get("max_15m_exposure_pct", 2.5)),
    )
    
    # Validate
    errors = cfg.validate_all_assets_have_params()
    if errors:
        for err in errors:
            logger.error(err)
        raise ValueError(f"Config validation failed: {errors}")
    
    logger.info(f"[CONFIG_LOADED] KalshiDistanceConfig v{cfg.version} loaded from {config_path}")
    return cfg


def get_distance_config() -> KalshiDistanceConfig:
    """Get or load the singleton distance config.
    
    Returns:
        Frozen KalshiDistanceConfig instance
    """
    global _distance_config
    if _distance_config is None:
        _distance_config = load_distance_config()
    return _distance_config


def run_startup_assertions() -> Tuple[bool, List[str]]:
    """Run all config invariants at startup.
    
    Returns:
        (all_passed, list_of_errors)
        
    Usage:
        passed, errors = run_startup_assertions()
        if not passed:
            for err in errors:
                logger.error(err)
            raise RuntimeError(f"Startup assertions failed: {errors}")
    """
    cfg = get_distance_config()
    errors = []
    
    # Assertion 1: All assets have required parameters
    param_errors = cfg.validate_all_assets_have_params()
    errors.extend(param_errors)
    
    # Assertion 2: Timeframe sets don't overlap
    overlap = cfg.execution_timeframes & cfg.signal_only_timeframes
    if overlap:
        errors.append(f"[CONFIG_ERROR] Timeframe overlap: {overlap}")
    
    # Assertion 3: Edge thresholds are consistent (far > near)
    for asset in cfg.allowed_assets:
        near = cfg.min_edge_near.get(asset, 0)
        far = cfg.min_edge_far.get(asset, 0)
        if far <= near:
            errors.append(f"[CONFIG_ERROR] {asset} min_edge_far ({far}) <= min_edge_near ({near})")
    
    # Assertion 4: Distance caps are ordered by volatility
    expected_order = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
    prev_max = -1
    for asset in expected_order:
        if asset in cfg.max_delta_pct:
            current = cfg.max_delta_pct[asset]
            if current < prev_max:
                errors.append(f"[CONFIG_ERROR] {asset} max_delta_pct ({current}) < previous ({prev_max}) - should increase with volatility")
            prev_max = current
    
    passed = len(errors) == 0
    
    if passed:
        logger.info("[STARTUP_ASSERTIONS] All config invariants passed")
    else:
        logger.error(f"[STARTUP_ASSERTIONS] {len(errors)} config errors found")
    
    return passed, errors


# ═══════════════════════════════════════════════════════════════════════════
# Env Var Override Support (for 15m scalper mode without YAML edits)
# ═══════════════════════════════════════════════════════════════════════════

def _apply_env_edge_overrides(min_edge_dict: dict, far: bool = False) -> dict:
    """Apply MERID_PM_EDGE_NEAR_* and MERID_PM_EDGE_FAR_* env overrides.
    
    This allows runtime tuning of edge thresholds without YAML edits.
    Example: MERID_PM_EDGE_NEAR_BTC=0.020 overrides BTC near edge to 2.0%
    """
    import os
    import copy
    
    result = copy.deepcopy(min_edge_dict)
    prefix = "MERID_PM_EDGE_FAR_" if far else "MERID_PM_EDGE_NEAR_"
    
    for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
        env_val = os.getenv(f"{prefix}{asset}")
        if env_val:
            try:
                result[asset] = float(env_val)
                logger.info(f"[ENV_OVERRIDE] {prefix}{asset} = {env_val} (overrides YAML)")
            except ValueError:
                logger.warning(f"[ENV_OVERRIDE] Invalid {prefix}{asset}={env_val}, ignoring")
    
    return result


def get_max_delta_pct(asset: str) -> float:
    """Get max delta pct for asset (convenience function)."""
    return get_distance_config().max_delta_pct.get(asset, 0.015)


def get_min_edge(asset: str, is_far: bool = False) -> float:
    """Get min edge for asset with env var override support.
    
    Priority: Env var > YAML config > hardcoded default
    """
    import os
    
    # Check env var first (highest priority)
    prefix = "MERID_PM_EDGE_FAR_" if is_far else "MERID_PM_EDGE_NEAR_"
    env_val = os.getenv(f"{prefix}{asset}")
    if env_val:
        try:
            val = float(env_val)
            logger.debug(f"[EDGE_ENV] {asset} {'far' if is_far else 'near'} = {val} (from env)")
            return val
        except ValueError:
            logger.warning(f"[EDGE_ENV] Invalid {prefix}{asset}={env_val}, using config")
    
    # Fall back to YAML config
    cfg = get_distance_config()
    if is_far:
        val = cfg.min_edge_far.get(asset)
        if val is not None:
            return val
        logger.warning(f"[EDGE_CONFIG] {asset} far edge not in config, using default 0.070")
        return 0.070
    else:
        val = cfg.min_edge_near.get(asset)
        if val is not None:
            return val
        logger.warning(f"[EDGE_CONFIG] {asset} near edge not in config, using default 0.050")
        return 0.050
