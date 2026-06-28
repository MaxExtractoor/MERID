"""Runtime configuration validator for 15m scalper mode.

This module validates that all configuration files and environment variables
are properly aligned for 15m momentum scalping mode.

Usage:
    from merid.prediction.config_validator import validate_15m_scalper_config
    validate_15m_scalper_config()  # Call at startup
"""

import os
import logging
from typing import List, Tuple

logger = logging.getLogger(__name__)


def validate_15m_scalper_config() -> Tuple[bool, List[str]]:
    """Validate 15m scalper configuration alignment.
    
    Returns:
        Tuple of (is_valid, list_of_warnings)
    """
    warnings = []
    
    # Check STRATEGY_MODE
    strategy_mode = os.getenv("STRATEGY_MODE", "").upper()
    if strategy_mode != "MOMENTUM_SCALPER":
        warnings.append(f"STRATEGY_MODE={strategy_mode} (expected MOMENTUM_SCALPER)")
    
    # Check critical env vars for scalper mode
    critical_vars = {
        "MAX_CYCLE_RISK_PCT": ("0.01", "0.05"),  # 1-5% range (production: 3%)
        "TOPN_MAX_CYCLE_RISK_PCT": ("0.01", "0.05"),
        "MAX_CONTRACTS_PER_TF_CRYPTO_15M": ("20", "100"),
        "KALSHI_TRADER_RISK_PCT": ("0.01", "0.05"),
        "KALSHI_TRADER_MAX_POSITION": ("1", "5"),
    }
    
    for var, (min_val, max_val) in critical_vars.items():
        val = os.getenv(var)
        if not val:
            warnings.append(f"{var} not set (critical for scalper mode)")
        else:
            try:
                fval = float(val)
                if fval < float(min_val) or fval > float(max_val):
                    warnings.append(f"{var}={val} outside recommended range [{min_val}, {max_val}]")
            except ValueError:
                pass  # Non-numeric value, skip range check
    
    # Check kill switch
    if os.getenv("KALSHI_TRADER_ENABLED", "").lower() not in ("true", "1", "yes"):
        warnings.append("KALSHI_TRADER_ENABLED is not true (kill switch engaged)")
    
    # Log results
    if warnings:
        logger.warning("[CONFIG-VALIDATOR] 15m scalper config warnings:")
        for w in warnings:
            logger.warning(f"  - {w}")
    else:
        logger.info("[CONFIG-VALIDATOR] 15m scalper config validated successfully")
    
    return len(warnings) == 0, warnings


def log_config_compliance_check():
    """Log whether scalper mode config is properly loaded."""
    is_scalper = os.getenv("STRATEGY_MODE", "").upper() == "MOMENTUM_SCALPER"
    
    try:
        # LEGACY REMOVAL: kalshi_distance_config moved to archive/legacy/ during 15m stack cleanup
        # cfg = get_distance_config()
        cfg = None
        
        logger.info(
            "[CONFIG_CHECK] STRATEGY_MODE=%s, max_15m_positions=%d, max_exposure=%.1f%%",
            "SCALPER" if is_scalper else "OTHER",
            cfg.sizing_constraints.max_15m_positions_per_asset,
            cfg.sizing_constraints.max_15m_exposure_pct
        )
        
        if is_scalper and cfg.sizing_constraints.max_15m_positions_per_asset < 8:
            logger.warning(
                "[CONFIG_CHECK] WARNING: Scalper mode active but positions capped at %d (expected 8+)",
                cfg.sizing_constraints.max_15m_positions_per_asset
            )
    except Exception as e:
        logger.error(f"[CONFIG_CHECK] Error checking config: {e}")


if __name__ == "__main__":
    # Run validation
    valid, warns = validate_15m_scalper_config()
    print(f"Config valid: {valid}")
    if warns:
        print("Warnings:", warns)
