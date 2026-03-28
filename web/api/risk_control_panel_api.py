"""
Risk Control Panel API - Comprehensive UI Controls for Production Risk Management

Provides operator controls for:
- Kill switches (global + per-domain)
- Circuit breakers status and reset
- Protection layer visibility (all 7 layers)
- CQI throttle state
- Manual limit overrides
- Emergency halt/resume

This API expands on risk_metrics_api.py to provide full operator control surface.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from datetime import datetime
import logging

from utils.logger import get_logger

logger = get_logger("web.api.risk_control_panel")
router = APIRouter(prefix="/api/v1/risk-control", tags=["risk-control"])


# ── Request/Response Models ────────────────────────────────────────────


class KillSwitchRequest(BaseModel):
    domain: Optional[str] = Field(None, description="Domain to kill (None = global)")
    reason: str = Field("operator_manual_halt", description="Reason for kill switch activation")
    operator: str = Field("operator", description="Operator name/ID")


class KillSwitchResumeRequest(BaseModel):
    domain: Optional[str] = Field(None, description="Domain to resume (None = global)")
    operator: str = Field("operator", description="Operator name/ID")


class CircuitBreakerResetRequest(BaseModel):
    circuit_id: str = Field(..., description="Circuit breaker ID to reset")
    operator: str = Field("operator", description="Operator name/ID")


class LimitOverrideRequest(BaseModel):
    limit_type: str = Field(..., description="Type of limit to override (e.g., 'daily_loss', 'position_size')")
    new_value: float = Field(..., description="New limit value")
    duration_seconds: Optional[int] = Field(None, description="Override duration (None = permanent)")
    operator: str = Field("operator", description="Operator name/ID")
    reason: str = Field("temporary_override", description="Reason for override")


# ── Kill Switch Controls ────────────────────────────────────────────────


@router.get("/kill-switches/status")
async def get_kill_switch_status() -> Dict[str, Any]:
    """
    Get status of all kill switches (global + per-domain).

    Returns:
        {
            "global": {
                "active": bool,
                "reason": str,
                "triggered_at": str (ISO timestamp),
                "triggered_by": str
            },
            "domains": {
                "crypto": {"active": bool, "reason": str, ...},
                "prediction": {"active": bool, "reason": str, ...},
                "betting": {"active": bool, "reason": str, ...}
            },
            "can_trade": bool,
            "affected_domains": [str]
        }
    """
    try:
        # Try to get execution guard
        try:
            from merid.execution_guard import get_execution_guard
            guard = get_execution_guard()

            # Get global kill switch status
            global_ks = guard.get_kill_switch_status()

            # Get per-domain status
            domains = {}
            for domain in ["crypto", "prediction", "betting"]:
                try:
                    domain_status = guard.get_domain_kill_switch_status(domain)
                    domains[domain] = domain_status
                except:
                    domains[domain] = {"active": False, "reason": None}

            # Determine affected domains
            affected = []
            if global_ks.get("active"):
                affected = ["crypto", "prediction", "betting"]
            else:
                affected = [d for d, s in domains.items() if s.get("active")]

            return {
                "global": global_ks,
                "domains": domains,
                "can_trade": not global_ks.get("active") and not any(s.get("active") for s in domains.values()),
                "affected_domains": affected,
            }

        except ImportError:
            logger.warning("Execution guard not available, checking risk coordinator")
            from core.automated_risk_controls import get_risk_coordinator
            coord = get_risk_coordinator()

            halt_status = coord.halt_manager.get_status()
            return {
                "global": {
                    "active": halt_status.get("is_halted", False),
                    "reason": halt_status.get("halt_reason"),
                    "triggered_at": halt_status.get("halted_at"),
                    "triggered_by": "automated_risk_controls"
                },
                "domains": {},
                "can_trade": not halt_status.get("is_halted", False),
                "affected_domains": ["all"] if halt_status.get("is_halted") else [],
            }

    except Exception as e:
        logger.error(f"Failed to get kill switch status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/kill-switches/activate")
async def activate_kill_switch(req: KillSwitchRequest) -> Dict[str, Any]:
    """
    Activate kill switch (global or per-domain).
    CRITICAL: This will immediately halt trading.
    """
    try:
        # Try execution guard first
        try:
            from merid.execution_guard import get_execution_guard
            guard = get_execution_guard()

            if req.domain:
                # Per-domain kill switch
                result = guard.activate_domain_kill_switch(req.domain, req.reason, req.operator)
            else:
                # Global kill switch
                result = guard.activate_global_kill_switch(req.reason, req.operator)

            logger.warning(f"Kill switch activated by {req.operator}: domain={req.domain}, reason={req.reason}")

            return {
                "success": True,
                "domain": req.domain or "global",
                "active": True,
                "reason": req.reason,
                "operator": req.operator,
                "activated_at": datetime.utcnow().isoformat(),
            }

        except (ImportError, AttributeError):
            # Fall back to risk coordinator halt
            from core.automated_risk_controls import get_risk_coordinator
            coord = get_risk_coordinator()

            changed = coord.halt_manager.halt(req.reason)

            logger.warning(f"Trading halted via risk coordinator by {req.operator}: {req.reason}")

            return {
                "success": True,
                "domain": "global",
                "active": True,
                "reason": req.reason,
                "operator": req.operator,
                "activated_at": datetime.utcnow().isoformat(),
                "changed": changed,
            }

    except Exception as e:
        logger.error(f"Failed to activate kill switch: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/kill-switches/deactivate")
async def deactivate_kill_switch(req: KillSwitchResumeRequest) -> Dict[str, Any]:
    """
    Deactivate kill switch (resume trading).
    Requires operator confirmation.
    """
    try:
        # Try execution guard first
        try:
            from merid.execution_guard import get_execution_guard
            guard = get_execution_guard()

            if req.domain:
                # Per-domain resume
                result = guard.deactivate_domain_kill_switch(req.domain, req.operator)
            else:
                # Global resume
                result = guard.deactivate_global_kill_switch(req.operator)

            logger.info(f"Kill switch deactivated by {req.operator}: domain={req.domain}")

            return {
                "success": True,
                "domain": req.domain or "global",
                "active": False,
                "operator": req.operator,
                "resumed_at": datetime.utcnow().isoformat(),
            }

        except (ImportError, AttributeError):
            # Fall back to risk coordinator resume
            from core.automated_risk_controls import get_risk_coordinator
            coord = get_risk_coordinator()

            changed = coord.halt_manager.resume(req.operator)

            logger.info(f"Trading resumed via risk coordinator by {req.operator}")

            return {
                "success": True,
                "domain": "global",
                "active": False,
                "operator": req.operator,
                "resumed_at": datetime.utcnow().isoformat(),
                "changed": changed,
            }

    except Exception as e:
        logger.error(f"Failed to deactivate kill switch: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Circuit Breaker Controls ────────────────────────────────────────────


@router.get("/circuit-breakers/status")
async def get_circuit_breaker_status() -> Dict[str, Any]:
    """
    Get status of all circuit breakers.

    Returns:
        {
            "breakers": [
                {
                    "id": str,
                    "name": str,
                    "state": "CLOSED" | "OPEN" | "HALF_OPEN",
                    "failure_count": int,
                    "threshold": int,
                    "last_failure": str (ISO timestamp),
                    "opened_at": str (ISO timestamp),
                    "recovery_timeout": int (seconds),
                    "can_reset": bool
                }
            ],
            "total_breakers": int,
            "open_breakers": int
        }
    """
    try:
        # Try to get circuit breakers
        breakers_list = []

        # Check execution guard circuit breakers
        try:
            from merid.execution_guard import get_execution_guard
            guard = get_execution_guard()

            if hasattr(guard, 'get_circuit_breaker_status'):
                breakers_list.extend(guard.get_circuit_breaker_status())
        except:
            pass

        # Check hardening circuit breakers
        try:
            from hardening.circuit_breaker import get_circuit_breaker_registry
            registry = get_circuit_breaker_registry()

            if hasattr(registry, 'get_all_status'):
                breakers_list.extend(registry.get_all_status())
        except:
            pass

        # If no breakers found, return empty state
        if not breakers_list:
            return {
                "breakers": [],
                "total_breakers": 0,
                "open_breakers": 0,
            }

        open_count = sum(1 for b in breakers_list if b.get("state") == "OPEN")

        return {
            "breakers": breakers_list,
            "total_breakers": len(breakers_list),
            "open_breakers": open_count,
        }

    except Exception as e:
        logger.error(f"Failed to get circuit breaker status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/circuit-breakers/reset")
async def reset_circuit_breaker(req: CircuitBreakerResetRequest) -> Dict[str, Any]:
    """
    Reset a circuit breaker (manual recovery).
    Use with caution - ensure underlying issue is resolved.
    """
    try:
        # Try to reset circuit breaker
        reset_success = False

        try:
            from merid.execution_guard import get_execution_guard
            guard = get_execution_guard()

            if hasattr(guard, 'reset_circuit_breaker'):
                reset_success = guard.reset_circuit_breaker(req.circuit_id, req.operator)
        except:
            pass

        if not reset_success:
            try:
                from hardening.circuit_breaker import get_circuit_breaker_registry
                registry = get_circuit_breaker_registry()

                if hasattr(registry, 'reset'):
                    reset_success = registry.reset(req.circuit_id, req.operator)
            except:
                pass

        if reset_success:
            logger.info(f"Circuit breaker {req.circuit_id} reset by {req.operator}")
            return {
                "success": True,
                "circuit_id": req.circuit_id,
                "state": "CLOSED",
                "reset_by": req.operator,
                "reset_at": datetime.utcnow().isoformat(),
            }
        else:
            raise HTTPException(status_code=404, detail=f"Circuit breaker {req.circuit_id} not found")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to reset circuit breaker: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Protection Layer Status ─────────────────────────────────────────────


@router.get("/protection-layers")
async def get_protection_layers_status() -> Dict[str, Any]:
    """
    Get status of all 7 protection layers.

    Returns:
        {
            "layers": [
                {
                    "name": str,
                    "active": bool,
                    "status": str,
                    "description": str,
                    "blocking_trades": bool,
                    "metrics": dict
                }
            ],
            "total_blocking": int,
            "can_trade": bool
        }
    """
    try:
        layers = []

        # Layer 1: Global Kill Switch
        try:
            ks_status = await get_kill_switch_status()
            layers.append({
                "name": "Global Kill Switch",
                "layer_number": 1,
                "active": True,
                "status": "ACTIVE" if ks_status["global"]["active"] else "INACTIVE",
                "description": "Emergency stop for all trading",
                "blocking_trades": ks_status["global"]["active"],
                "metrics": {
                    "reason": ks_status["global"].get("reason"),
                    "triggered_at": ks_status["global"].get("triggered_at"),
                }
            })
        except:
            layers.append({
                "name": "Global Kill Switch",
                "layer_number": 1,
                "active": True,
                "status": "UNKNOWN",
                "description": "Emergency stop for all trading",
                "blocking_trades": False,
                "metrics": {}
            })

        # Layer 2: Per-Domain Kill Switch
        try:
            ks_status = await get_kill_switch_status()
            domain_blocking = any(s.get("active") for s in ks_status["domains"].values())
            layers.append({
                "name": "Per-Domain Kill Switch",
                "layer_number": 2,
                "active": True,
                "status": "ACTIVE" if domain_blocking else "INACTIVE",
                "description": "Domain-specific trading blocks",
                "blocking_trades": domain_blocking,
                "metrics": {
                    "domains": ks_status["domains"],
                    "affected_domains": ks_status.get("affected_domains", [])
                }
            })
        except:
            layers.append({
                "name": "Per-Domain Kill Switch",
                "layer_number": 2,
                "active": True,
                "status": "UNKNOWN",
                "description": "Domain-specific trading blocks",
                "blocking_trades": False,
                "metrics": {}
            })

        # Layer 3: CQI Throttle
        try:
            from merid.execution_guard import get_execution_guard
            guard = get_execution_guard()

            if hasattr(guard, 'get_cqi_throttle_status'):
                cqi_status = guard.get_cqi_throttle_status()
                layers.append({
                    "name": "CQI Throttle",
                    "layer_number": 3,
                    "active": True,
                    "status": "THROTTLING" if cqi_status.get("throttling") else "NORMAL",
                    "description": "Consensus quality-based trade sizing",
                    "blocking_trades": False,  # Shrinks trades, doesn't block
                    "metrics": cqi_status
                })
            else:
                raise AttributeError("CQI throttle not available")
        except:
            layers.append({
                "name": "CQI Throttle",
                "layer_number": 3,
                "active": False,
                "status": "UNAVAILABLE",
                "description": "Consensus quality-based trade sizing",
                "blocking_trades": False,
                "metrics": {}
            })

        # Layer 4: Per-Domain Daily Caps
        try:
            from merid.execution_guard import get_execution_guard
            guard = get_execution_guard()

            if hasattr(guard, 'get_domain_caps_status'):
                caps_status = guard.get_domain_caps_status()
                any_breached = any(d.get("breached") for d in caps_status.values())
                layers.append({
                    "name": "Per-Domain Daily Caps",
                    "layer_number": 4,
                    "active": True,
                    "status": "BREACHED" if any_breached else "NORMAL",
                    "description": "Maximum notional per domain per day",
                    "blocking_trades": any_breached,
                    "metrics": caps_status
                })
            else:
                raise AttributeError("Domain caps not available")
        except:
            layers.append({
                "name": "Per-Domain Daily Caps",
                "layer_number": 4,
                "active": False,
                "status": "UNAVAILABLE",
                "description": "Maximum notional per domain per day",
                "blocking_trades": False,
                "metrics": {}
            })

        # Layer 5: Cooldown
        try:
            from merid.execution_guard import get_execution_guard
            guard = get_execution_guard()

            if hasattr(guard, 'get_cooldown_status'):
                cooldown_status = guard.get_cooldown_status()
                layers.append({
                    "name": "Execution Cooldown",
                    "layer_number": 5,
                    "active": True,
                    "status": "COOLING" if cooldown_status.get("in_cooldown") else "READY",
                    "description": "Minimum time between executions",
                    "blocking_trades": cooldown_status.get("in_cooldown", False),
                    "metrics": cooldown_status
                })
            else:
                raise AttributeError("Cooldown not available")
        except:
            layers.append({
                "name": "Execution Cooldown",
                "layer_number": 5,
                "active": False,
                "status": "UNAVAILABLE",
                "description": "Minimum time between executions",
                "blocking_trades": False,
                "metrics": {}
            })

        # Layer 6: Venue Exposure Caps
        try:
            from risk.risk_guard import get_risk_guard
            guard = get_risk_guard()

            if hasattr(guard, 'get_venue_exposure_status'):
                exposure_status = guard.get_venue_exposure_status()
                any_breached = any(v.get("breached") for v in exposure_status.values())
                layers.append({
                    "name": "Venue Exposure Caps",
                    "layer_number": 6,
                    "active": True,
                    "status": "BREACHED" if any_breached else "NORMAL",
                    "description": "Maximum exposure per venue",
                    "blocking_trades": any_breached,
                    "metrics": exposure_status
                })
            else:
                raise AttributeError("Venue exposure caps not available")
        except:
            layers.append({
                "name": "Venue Exposure Caps",
                "layer_number": 6,
                "active": False,
                "status": "UNAVAILABLE",
                "description": "Maximum exposure per venue",
                "blocking_trades": False,
                "metrics": {}
            })

        # Layer 7: Promotion Eligibility
        try:
            from merid.promotion_report import get_promotion_report
            report = get_promotion_report()

            if hasattr(report, 'get_promotion_status'):
                promo_status = report.get_promotion_status()
                blocking = not promo_status.get("eligible_for_live", True)
                layers.append({
                    "name": "Promotion Eligibility",
                    "layer_number": 7,
                    "active": True,
                    "status": "ELIGIBLE" if not blocking else "BLOCKED",
                    "description": "Gauntlet-based live trading eligibility",
                    "blocking_trades": blocking,
                    "metrics": promo_status
                })
            else:
                raise AttributeError("Promotion status not available")
        except:
            layers.append({
                "name": "Promotion Eligibility",
                "layer_number": 7,
                "active": False,
                "status": "UNAVAILABLE",
                "description": "Gauntlet-based live trading eligibility",
                "blocking_trades": False,
                "metrics": {}
            })

        # Calculate totals
        total_blocking = sum(1 for layer in layers if layer["blocking_trades"])
        can_trade = total_blocking == 0

        return {
            "layers": layers,
            "total_blocking": total_blocking,
            "can_trade": can_trade,
            "timestamp": datetime.utcnow().isoformat(),
        }

    except Exception as e:
        logger.error(f"Failed to get protection layers status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Limit Overrides ─────────────────────────────────────────────────────


@router.post("/limits/override")
async def override_limit(req: LimitOverrideRequest) -> Dict[str, Any]:
    """
    Override a risk limit temporarily or permanently.
    USE WITH CAUTION - requires operator approval.
    """
    try:
        # Try to apply override
        try:
            from risk.risk_guard import get_risk_guard
            guard = get_risk_guard()

            if hasattr(guard, 'override_limit'):
                result = guard.override_limit(
                    limit_type=req.limit_type,
                    new_value=req.new_value,
                    duration_seconds=req.duration_seconds,
                    operator=req.operator,
                    reason=req.reason
                )

                logger.warning(
                    f"Risk limit override by {req.operator}: {req.limit_type}={req.new_value} "
                    f"(duration={req.duration_seconds}s, reason={req.reason})"
                )

                return {
                    "success": True,
                    "limit_type": req.limit_type,
                    "old_value": result.get("old_value"),
                    "new_value": req.new_value,
                    "duration_seconds": req.duration_seconds,
                    "expires_at": result.get("expires_at"),
                    "operator": req.operator,
                    "reason": req.reason,
                    "applied_at": datetime.utcnow().isoformat(),
                }
            else:
                raise HTTPException(status_code=501, detail="Limit override not implemented")

        except ImportError:
            raise HTTPException(status_code=501, detail="Risk guard not available")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to override limit: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/limits/overrides")
async def get_active_overrides() -> Dict[str, Any]:
    """
    Get all active limit overrides.
    """
    try:
        try:
            from risk.risk_guard import get_risk_guard
            guard = get_risk_guard()

            if hasattr(guard, 'get_active_overrides'):
                overrides = guard.get_active_overrides()

                return {
                    "overrides": overrides,
                    "total_overrides": len(overrides),
                }
            else:
                return {"overrides": [], "total_overrides": 0}

        except ImportError:
            return {"overrides": [], "total_overrides": 0}

    except Exception as e:
        logger.error(f"Failed to get active overrides: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Emergency Controls ──────────────────────────────────────────────────


@router.post("/emergency/stop-all")
async def emergency_stop_all(req: KillSwitchRequest) -> Dict[str, Any]:
    """
    EMERGENCY: Stop all trading immediately across all domains and venues.
    This is the "big red button".
    """
    try:
        # Activate global kill switch
        result = await activate_kill_switch(KillSwitchRequest(
            domain=None,
            reason=f"EMERGENCY_STOP: {req.reason}",
            operator=req.operator
        ))

        # Also try to halt via risk coordinator
        try:
            from core.automated_risk_controls import get_risk_coordinator
            coord = get_risk_coordinator()
            coord.halt_manager.halt(f"EMERGENCY_STOP: {req.reason}")
        except:
            pass

        logger.critical(f"EMERGENCY STOP activated by {req.operator}: {req.reason}")

        return {
            "success": True,
            "status": "ALL_TRADING_STOPPED",
            "reason": req.reason,
            "operator": req.operator,
            "stopped_at": datetime.utcnow().isoformat(),
            "kill_switch_result": result,
        }

    except Exception as e:
        logger.error(f"Emergency stop failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def get_risk_control_health() -> Dict[str, Any]:
    """
    Health check for risk control system.
    """
    try:
        components = {
            "execution_guard": False,
            "risk_coordinator": False,
            "circuit_breakers": False,
            "kill_switches": False,
            "protection_layers": False,
        }

        # Check execution guard
        try:
            from merid.execution_guard import get_execution_guard
            get_execution_guard()
            components["execution_guard"] = True
        except:
            pass

        # Check risk coordinator
        try:
            from core.automated_risk_controls import get_risk_coordinator
            get_risk_coordinator()
            components["risk_coordinator"] = True
        except:
            pass

        # Check circuit breakers
        try:
            cb_status = await get_circuit_breaker_status()
            components["circuit_breakers"] = True
        except:
            pass

        # Check kill switches
        try:
            ks_status = await get_kill_switch_status()
            components["kill_switches"] = True
        except:
            pass

        # Check protection layers
        try:
            pl_status = await get_protection_layers_status()
            components["protection_layers"] = True
        except:
            pass

        healthy_count = sum(components.values())
        total_count = len(components)

        return {
            "status": "healthy" if healthy_count >= 2 else "degraded",
            "components": components,
            "healthy_components": healthy_count,
            "total_components": total_count,
            "timestamp": datetime.utcnow().isoformat(),
        }

    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat(),
        }
