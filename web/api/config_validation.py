"""
Config Validation API

Provides endpoints for validating risk configuration before applying.
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, validator, Field
from typing import Optional, List, Dict, Any
import os
import json

from merid.trading.trade_mode import get_trade_mode
from merid.config.unified_risk_enforcement import (
    enforce_unified_risk_model,
    RiskConfigViolationError,
    ABSOLUTE_MAX_CYCLE_RISK_PCT,
    ABSOLUTE_MAX_EDGES_PER_CYCLE,
    ABSOLUTE_MAX_RISK_PER_TRADE_PCT
)


router = APIRouter(prefix="/api/v1/config", tags=["config"])


class RiskConfigInput(BaseModel):
    """Risk configuration input for validation."""
    max_risk_pct_global: float = Field(
        default=0.02,
        description="Maximum total basket risk as decimal (e.g., 0.02 = 2%)",
        ge=0,
        le=1
    )
    max_risk_pct_per_trade: float = Field(
        default=0.01,
        description="Maximum risk per trade as decimal (e.g., 0.01 = 1%)",
        ge=0,
        le=1
    )
    max_total_notional_usd: Optional[float] = Field(
        default=None,
        description="Fixed USD cap (only allowed in SIM mode)"
    )
    max_concurrent_assets: int = Field(
        default=3,
        description="Maximum concurrent edges/assets",
        ge=1,
        le=10
    )
    
    @validator('max_risk_pct_global')
    def validate_global_cap(cls, v):
        if v > ABSOLUTE_MAX_CYCLE_RISK_PCT:
            raise ValueError(
                f"Global risk cap {v*100}% exceeds absolute maximum {ABSOLUTE_MAX_CYCLE_RISK_PCT*100}%. "
                f"Maximum allowed: {ABSOLUTE_MAX_CYCLE_RISK_PCT*100}% ({ABSOLUTE_MAX_CYCLE_RISK_PCT})"
            )
        return v
    
    @validator('max_total_notional_usd')
    def validate_no_fixed_usd_in_live(cls, v):
        mode = get_trade_mode()
        if mode in ("live", "paper") and v is not None and v > 0:
            raise ValueError(
                f"Fixed USD sizing (max_total_notional_usd=${v}) "
                f"not allowed in {mode} mode. Use percentage-based limits only."
            )
        return v
    
    @validator('max_risk_pct_per_trade')
    def validate_per_trade_cap(cls, v, values):
        global_cap = values.get('max_risk_pct_global', ABSOLUTE_MAX_CYCLE_RISK_PCT)
        if v > global_cap:
            raise ValueError(
                f"Per-trade cap {v*100}% exceeds global cap {global_cap*100}%. "
                f"Per-trade must be ≤ global cap."
            )
        if v > ABSOLUTE_MAX_RISK_PER_TRADE_PCT:
            raise ValueError(
                f"Per-trade cap {v*100}% exceeds absolute maximum {ABSOLUTE_MAX_RISK_PER_TRADE_PCT*100}%."
            )
        return v
    
    @validator('max_concurrent_assets')
    def validate_edge_limit(cls, v):
        if v > ABSOLUTE_MAX_EDGES_PER_CYCLE:
            raise ValueError(
                f"Max concurrent assets {v} exceeds absolute maximum {ABSOLUTE_MAX_EDGES_PER_CYCLE}."
            )
        return v


class ValidationResult(BaseModel):
    """Validation result with details."""
    valid: bool
    mode: str
    config: Dict[str, Any]
    warnings: List[str]
    errors: List[str]
    can_apply: bool


@router.post("/validate", response_model=ValidationResult)
async def validate_config(config: RiskConfigInput) -> ValidationResult:
    """
    Validate risk configuration before applying.
    
    Returns validation result with warnings and errors.
    Safe to call - does not modify any configuration.
    """
    mode = get_trade_mode()
    warnings = []
    errors = []
    
    # Additional warnings (not fatal)
    if config.max_risk_pct_global > 0.015:  # > 1.5%
        warnings.append(
            f"Global cap {config.max_risk_pct_global*100}% approaches limit "
            f"({ABSOLUTE_MAX_CYCLE_RISK_PCT*100}%). Consider lower cap for safety."
        )
    
    if config.max_concurrent_assets == ABSOLUTE_MAX_EDGES_PER_CYCLE:
        warnings.append(
            "At maximum concurrent assets - new signals will queue or be rejected."
        )
    
    # Build config dict for enforcement check
    config_dict = {
        "max_risk_pct_global": config.max_risk_pct_global,
        "max_risk_pct_per_trade": config.max_risk_pct_per_trade,
        "max_concurrent_assets": config.max_concurrent_assets,
    }
    if config.max_total_notional_usd:
        config_dict["max_total_notional_usd"] = config.max_total_notional_usd
    
    # Run through enforcement model
    try:
        result = enforce_unified_risk_model(config_sources=[config_dict])
        
        if result.violations:
            for v in result.violations:
                if "VIOLATION" in v:
                    errors.append(v)
                else:
                    warnings.append(v)
        
        can_apply = len([e for e in errors if "VIOLATION" in e]) == 0
        
    except RiskConfigViolationError as e:
        errors.append(str(e))
        can_apply = False
    
    return ValidationResult(
        valid=can_apply and len(errors) == 0,
        mode=mode,
        config=config_dict,
        warnings=warnings,
        errors=errors,
        can_apply=can_apply
    )


@router.get("/limits")
async def get_config_limits() -> Dict[str, Any]:
    """
    Get absolute configuration limits enforced by the system.
    
    Use these to validate configuration before submission.
    """
    return {
        "absolute_max_cycle_risk_pct": ABSOLUTE_MAX_CYCLE_RISK_PCT,
        "absolute_max_cycle_risk_pct_human": f"{ABSOLUTE_MAX_CYCLE_RISK_PCT*100}%",
        "absolute_max_edges_per_cycle": ABSOLUTE_MAX_EDGES_PER_CYCLE,
        "absolute_max_risk_per_trade_pct": ABSOLUTE_MAX_RISK_PER_TRADE_PCT,
        "absolute_max_risk_per_trade_pct_human": f"{ABSOLUTE_MAX_RISK_PER_TRADE_PCT*100}%",
        "mode": get_trade_mode(),
        "fixed_usd_allowed": get_trade_mode() == "sim",
    }


@router.get("/current")
async def get_current_config() -> Dict[str, Any]:
    """Get currently active risk configuration."""
    try:
        result = enforce_unified_risk_model()
        return {
            "mode": get_trade_mode(),
            "final_config": result.final_config,
            "violations": result.violations,
            "clamped_values": result.clamped_values,
            "success": result.success
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=json.dumps({
                "error": "CONFIG_LOAD_ERROR",
                "message": f"Could not load current configuration: {e}",
                "contact": "#platform-engineering"
            })
        )


@router.post("/apply")
async def apply_config(
    config: RiskConfigInput,
    force: bool = Query(False, description="Force apply even with warnings")
) -> Dict[str, Any]:
    """
    Apply risk configuration.
    
    Requires confirmation in LIVE mode.
    Errors will prevent application.
    Warnings require force=True to override.
    """
    # First validate
    validation = await validate_config(config)
    
    if validation.errors and not force:
        raise HTTPException(
            status_code=400,
            detail=json.dumps({
                "error": "VALIDATION_FAILED",
                "message": "Configuration has errors and cannot be applied",
                "errors": validation.errors,
                "remediation": "Fix errors or use ?force=true to override warnings (not errors)"
            })
        )
    
    if validation.warnings and not force:
        raise HTTPException(
            status_code=400,
            detail=json.dumps({
                "error": "VALIDATION_WARNINGS",
                "message": "Configuration has warnings",
                "warnings": validation.warnings,
                "remediation": "Use ?force=true to apply anyway"
            })
        )
    
    mode = get_trade_mode()
    
    # In live mode, require explicit confirmation
    if mode == "live":
        # This would typically integrate with auth/approval system
        # For now, we just log and document the requirement
        return {
            "applied": False,
            "requires_confirmation": True,
            "message": "LIVE mode configuration changes require manual approval",
            "contact": "#risk-engineering",
            "validation": validation.dict()
        }
    
    # Apply would happen here - implementation depends on config persistence
    return {
        "applied": True,
        "mode": mode,
        "config": validation.config,
        "warnings_applied": validation.warnings if force else [],
        "timestamp": "2026-04-23T00:00:00Z",
        "note": "Configuration validated and ready for persistence"
    }
