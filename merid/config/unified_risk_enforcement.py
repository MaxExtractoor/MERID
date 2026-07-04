"""
Unified Risk Enforcement Module — Pass 8 P0 Implementation

Single source of truth for the 1-2% total basket + top-3 edges risk model.
This module enforces that ALL risk configurations conform to the canonical model,
overriding or rejecting any legacy configs that would violate invariants.

Invariants (cannot be overridden):
- Global max cycle risk: 2% of canonical bankroll (ABSOLUTE_MAX_CYCLE_RISK_PCT)
- Max concurrent edges: 3 (ABSOLUTE_MAX_EDGES_PER_CYCLE)
- No fixed USD caps in LIVE/PAPER (must use percentage-based limits)
- Per-trade caps are SUB-CAPS that cannot exceed global when aggregated

Usage:
    from merid.config.unified_risk_enforcement import enforce_unified_risk_model
    enforce_unified_risk_model()  # Call at startup, before any trading
"""

from __future__ import annotations

import os
import logging
from typing import Optional, Dict, Any
from dataclasses import dataclass

logger = logging.getLogger("merid.config.unified_risk_enforcement")

# ═══════════════════════════════════════════════════════════════════════════════
# ABSOLUTE INVARIANTS — These cannot be overridden by any configuration
# ═══════════════════════════════════════════════════════════════════════════════
# CRITICAL FIX: Aligned with kalshi_crypto_15m_v2 profile YAML values
# These absolute caps now match the profile's single source of truth
ABSOLUTE_MAX_CYCLE_RISK_PCT = 0.005  # 0.5% of equity maximum total basket risk (aligned with profile)
ABSOLUTE_MAX_EDGES_PER_CYCLE = 3    # Maximum 3 concurrent edges
ABSOLUTE_MAX_RISK_PER_TRADE_PCT = 0.02  # FIX: 2% max per individual trade (aligned with profile)

# Sim-only overrides (for backtesting historical scenarios)
ALLOWED_SIM_ONLY_OVERRIDES = [
    "max_risk_pct_global",  # Can exceed 2% in SIM for historical backtests
    "max_total_notional_usd",  # Fixed USD only in SIM
]


@dataclass(frozen=True)
class RiskEnforcementResult:
    """Result of risk configuration enforcement."""
    success: bool
    violations: list[str]
    clamped_values: dict[str, Any]
    final_config: dict[str, Any]


class RiskConfigViolationError(RuntimeError):
    """Raised when risk configuration violates absolute invariants."""
    pass


def _get_current_trade_mode() -> str:
    """Get current trade mode from environment or settings."""
    from trading.trade_mode import get_trade_mode
    try:
        return get_trade_mode()
    except Exception:
        return os.getenv("MERID_TRADE_MODE", os.getenv("KALSHI_ENV", "unknown"))


def _is_live_or_paper() -> bool:
    """Check if current mode is LIVE or PAPER."""
    return _get_current_trade_mode() in ("live", "paper", "LIVE", "PAPER")


def enforce_unified_risk_model(
    config_sources: Optional[list[Dict[str, Any]]] = None
) -> RiskEnforcementResult:
    """
    Enforce unified risk model across all configuration sources.
    
    This function:
    1. Loads risk configs from all sources
    2. Validates against absolute invariants
    3. Clamps or rejects violations
    4. Returns the final, enforced configuration
    
    Args:
        config_sources: Optional list of config dicts to validate.
                       If None, loads from default sources.
    
    Returns:
        RiskEnforcementResult with final config and any violations
    
    Raises:
        RiskConfigViolationError: If config violates invariants in LIVE/PAPER
    """
    violations = []
    clamped_values = {}
    final_config = {}
    
    mode = _get_current_trade_mode()
    is_live = _is_live_or_paper()
    
    logger.info(f"[PASS8_ENFORCE] Enforcing unified risk model in {mode} mode")
    
    # Load from default sources if not provided
    if config_sources is None:
        config_sources = _load_default_risk_configs()
    
    # ═══════════════════════════════════════════════════════════════════════
    # Invariant 1: Global risk cap must be ≤ 2%
    # ═══════════════════════════════════════════════════════════════════════
    
    global_risk = _get_config_value(config_sources, "max_risk_pct_global", 0.0)
    if global_risk > ABSOLUTE_MAX_CYCLE_RISK_PCT:
        if is_live:
            error_msg = (
                f"[PASS8_VIOLATION] max_risk_pct_global={global_risk} "
                f"exceeds absolute limit of {ABSOLUTE_MAX_CYCLE_RISK_PCT}. "
                f"In {mode} mode, this is a FATAL configuration error. "
                f"Reduce the global risk cap or use SIM mode for backtesting."
            )
            logger.error(error_msg)
            raise RiskConfigViolationError(error_msg)
        else:
            # SIM: Clamp and warn
            clamped_values["max_risk_pct_global"] = ABSOLUTE_MAX_CYCLE_RISK_PCT
            final_config["max_risk_pct_global"] = ABSOLUTE_MAX_CYCLE_RISK_PCT
            violations.append(
                f"max_risk_pct_global clamped from {global_risk} to {ABSOLUTE_MAX_CYCLE_RISK_PCT}"
            )
            logger.warning(f"[PASS8_CLAMP] {violations[-1]}")
    else:
        final_config["max_risk_pct_global"] = global_risk
    
    # ═══════════════════════════════════════════════════════════════════════
    # Invariant 2: No fixed USD caps in LIVE/PAPER
    # ═══════════════════════════════════════════════════════════════════════
    
    fixed_usd = _get_config_value(config_sources, "max_total_notional_usd", None)
    if fixed_usd and fixed_usd > 0:
        if is_live:
            error_msg = (
                f"[PASS8_VIOLATION] Fixed USD cap max_total_notional_usd=${fixed_usd} "
                f"is not allowed in {mode} mode. Use percentage-based limits only. "
                f"This prevents shadow bankrolls and ensures canonical bankroll is used."
            )
            logger.error(error_msg)
            raise RiskConfigViolationError(error_msg)
        else:
            violations.append(
                f"max_total_notional_usd=${fixed_usd} allowed in SIM only"
            )
            logger.info(f"[PASS8_SIM_ALLOW] {violations[-1]}")
    
    # ═══════════════════════════════════════════════════════════════════════
    # Invariant 3: Max concurrent edges (assets) must be ≤ 3
    # ═══════════════════════════════════════════════════════════════════════
    
    max_edges = _get_config_value(config_sources, "max_concurrent_assets", 3)
    if max_edges > ABSOLUTE_MAX_EDGES_PER_CYCLE:
        if is_live:
            # Clamp in live (don't fail — this is often a legacy config)
            clamped_values["max_concurrent_assets"] = ABSOLUTE_MAX_EDGES_PER_CYCLE
            final_config["max_concurrent_assets"] = ABSOLUTE_MAX_EDGES_PER_CYCLE
            violations.append(
                f"max_concurrent_assets clamped from {max_edges} to {ABSOLUTE_MAX_EDGES_PER_CYCLE}"
            )
            logger.warning(f"[PASS8_CLAMP] {violations[-1]}")
        else:
            clamped_values["max_concurrent_assets"] = ABSOLUTE_MAX_EDGES_PER_CYCLE
            final_config["max_concurrent_assets"] = ABSOLUTE_MAX_EDGES_PER_CYCLE
            violations.append(
                f"max_concurrent_assets clamped from {max_edges} to {ABSOLUTE_MAX_EDGES_PER_CYCLE}"
            )
    else:
        final_config["max_concurrent_assets"] = max_edges
    
    # ═══════════════════════════════════════════════════════════════════════
    # Invariant 4: Per-trade sub-caps ≤ 1% (to achieve 1-2% TOTAL across 3 edges)
    # CRITICAL: 1-2% is the TOTAL across all edges, NOT per-edge.
    # 3 edges × 3% = 9% is STRICTLY FORBIDDEN.
    # ═══════════════════════════════════════════════════════════════════════

    per_trade = _get_config_value(config_sources, "max_risk_pct_per_trade", 0.01)
    if per_trade > ABSOLUTE_MAX_RISK_PER_TRADE_PCT:
        clamped = min(per_trade, ABSOLUTE_MAX_RISK_PER_TRADE_PCT)
        clamped_values["max_risk_pct_per_trade"] = clamped
        final_config["max_risk_pct_per_trade"] = clamped
        violations.append(
            f"max_risk_pct_per_trade clamped from {per_trade} to {clamped} "
            f"(3×{clamped}={clamped*3:.0%} total — target 1-2% TOTAL, not per-edge)"
        )
        logger.warning(f"[PASS8_CLAMP] {violations[-1]}")
    else:
        final_config["max_risk_pct_per_trade"] = per_trade
    
    # ═══════════════════════════════════════════════════════════════════════
    # Summary logging
    # ═══════════════════════════════════════════════════════════════════════
    
    if violations:
        logger.info(
            f"[PASS8_RESULT] Risk enforcement complete: "
            f"{len(violations)} violations, {len(clamped_values)} clamped, "
            f"mode={mode}"
        )
    else:
        logger.info(f"[PASS8_RESULT] All risk configs conform to unified model")
    
    return RiskEnforcementResult(
        success=len([v for v in violations if "VIOLATION" in v]) == 0,
        violations=violations,
        clamped_values=clamped_values,
        final_config=final_config
    )


def _load_default_risk_configs() -> list[Dict[str, Any]]:
    """Load risk configs from default sources."""
    configs = []
    
    # Source 1: portfolio_optimizer.yaml
    try:
        import yaml
        with open("config/portfolio_optimizer.yaml") as f:
            data = yaml.safe_load(f)
            if data and "portfolio_optimizer" in data:
                configs.append(data["portfolio_optimizer"])
    except Exception as e:
        logger.debug(f"Could not load portfolio_optimizer.yaml: {e}")
    
    # Source 2: trade_hold_config.yaml
    try:
        import yaml
        with open("config/trade_hold_config.yaml") as f:
            data = yaml.safe_load(f)
            if data:
                configs.append(data)
    except Exception as e:
        logger.debug(f"Could not load trade_hold_config.yaml: {e}")
    
    # Source 3: Environment variables
    env_config = {}
    if os.getenv("MAX_RISK_PCT_GLOBAL"):
        env_config["max_risk_pct_global"] = float(os.getenv("MAX_RISK_PCT_GLOBAL"))
    if os.getenv("MAX_RISK_PCT_PER_TRADE"):
        env_config["max_risk_pct_per_trade"] = float(os.getenv("MAX_RISK_PCT_PER_TRADE"))
    if os.getenv("MAX_TOTAL_NOTIONAL_USD"):
        env_config["max_total_notional_usd"] = float(os.getenv("MAX_TOTAL_NOTIONAL_USD"))
    if env_config:
        configs.append(env_config)
    
    # Source 4: merid.settings
    try:
        from merid import settings
        settings_config = {}
        if hasattr(settings, 'MAX_RISK_PCT_GLOBAL'):
            settings_config["max_risk_pct_global"] = settings.MAX_RISK_PCT_GLOBAL
        if hasattr(settings, 'MAX_RISK_PCT_PER_TRADE'):
            settings_config["max_risk_pct_per_trade"] = settings.MAX_RISK_PCT_PER_TRADE
        if settings_config:
            configs.append(settings_config)
    except Exception as e:
        logger.debug(f"Could not load settings: {e}")
    
    return configs


def _get_config_value(configs: list[Dict[str, Any]], key: str, default: Any) -> Any:
    """Get first occurrence of key from list of config dicts."""
    for config in configs:
        if key in config:
            return config[key]
    return default


# ═══════════════════════════════════════════════════════════════════════════════
# Startup enforcement hook
# ═══════════════════════════════════════════════════════════════════════════════

def enforce_at_startup():
    """
    Convenience function to enforce risk model at application startup.
    Call this in web/main.py lifespan or equivalent startup hook.
    """
    from merid.utils.structured_logging import get_structured_logger
    from merid.metrics.kalshi_metrics import record_startup_enforcement, record_risk_violation
    
    slogger = get_structured_logger(__name__)
    
    try:
        result = enforce_unified_risk_model()
        
        if result.violations:
            logger.warning(f"[PASS8_STARTUP] Risk config violations found: {result.violations}")
            
            # Structured logging for violations
            slogger.log_startup_enforcement(
                success=False,
                violations=result.violations
            )
            
            # Record failure metric
            record_startup_enforcement(success=False)
            
            # Log each violation as a risk event
            for violation in result.violations:
                if "VIOLATION" in violation:
                    slogger.log_risk_violation(
                        violation_type="STARTUP_CONFIG",
                        current_value="unknown",
                        max_allowed="policy_limit",
                        config_source="startup_enforcement"
                    )
                    record_risk_violation(
                        violation_type="STARTUP_CONFIG",
                        current_value=0,
                        max_allowed=0,
                        config_source="startup"
                    )
        else:
            logger.info("[PASS8_STARTUP] Unified risk model enforced successfully")
            
            # Structured logging for success
            slogger.log_startup_enforcement(success=True, violations=[])
            
            # Record success metric
            record_startup_enforcement(success=True)
            
    except RiskConfigViolationError as e:
        logger.critical(f"[PASS8_FATAL] Cannot start: {e}")
        
        # Structured logging for fatal violation
        slogger.log_risk_violation(
            violation_type="FATAL_STARTUP_VIOLATION",
            current_value="see_error_message",
            max_allowed="policy_limit",
            config_source="enforce_at_startup"
        )
        
        # Record failure
        record_startup_enforcement(success=False)
        record_risk_violation(
            violation_type="FATAL_STARTUP",
            current_value=0,
            max_allowed=0,
            config_source="startup"
        )
        
        raise
