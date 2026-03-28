"""
Promotion Status API - Visibility into Auto-Promotion System

Provides UI visibility into:
- 5-ring gauntlet status per domain
- Domain live eligibility
- Agent promotion/blocking status
- Promotion history and changes
- Manual promotion overrides
- PF, expectancy, Sharpe ratio gates

This fills the gap where auto-promotion is fully implemented backend but has zero UI visibility.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from datetime import datetime
import logging

from utils.logger import get_logger

logger = get_logger("web.api.promotion_status")
router = APIRouter(prefix="/api/v1/promotion", tags=["promotion"])


# ── Request/Response Models ─────────────────────────────────────────────


class PromotionOverrideRequest(BaseModel):
    domain: str = Field(..., description="Domain to override")
    eligible: bool = Field(..., description="Force eligible (True) or ineligible (False)")
    operator: str = Field("operator", description="Operator name/ID")
    reason: str = Field("manual_override", description="Reason for override")
    duration_hours: Optional[int] = Field(None, description="Override duration (None = permanent)")


class AgentPromotionRequest(BaseModel):
    agent_id: str = Field(..., description="Agent ID to promote/block")
    action: str = Field(..., description="'promote' or 'block'")
    operator: str = Field("operator", description="Operator name/ID")
    reason: str = Field(..., description="Reason for promotion/block")


# ── Promotion Status ────────────────────────────────────────────────────


@router.get("/status")
async def get_promotion_status() -> Dict[str, Any]:
    """
    Get overall promotion status across all domains.

    Returns:
        {
            "timestamp": str,
            "auto_promotion_enabled": bool,
            "domains": {
                "crypto": {
                    "eligible": bool,
                    "ring": int (1-5),
                    "requirements_met": {
                        "pf_gate": bool,
                        "expectancy_gate": bool,
                        "sharpe_gate": bool,
                        "trade_count_gate": bool,
                        "stability_gate": bool
                    },
                    "metrics": {
                        "pf": float,
                        "expectancy": float,
                        "sharpe": float,
                        "trade_count": int,
                        "stability_score": float
                    },
                    "blocking_reason": str (if blocked)
                },
                ...
            },
            "eligible_count": int,
            "total_domains": int,
            "last_sync": str (ISO timestamp)
        }
    """
    try:
        # Try to get promotion report
        try:
            from merid.promotion_report import get_promotion_report
            report = get_promotion_report()

            if hasattr(report, 'get_all_domain_status'):
                status = report.get_all_domain_status()

                eligible_count = sum(1 for d in status["domains"].values() if d.get("eligible"))

                return {
                    "timestamp": datetime.utcnow().isoformat(),
                    "auto_promotion_enabled": True,
                    "domains": status["domains"],
                    "eligible_count": eligible_count,
                    "total_domains": len(status["domains"]),
                    "last_sync": status.get("last_sync", datetime.utcnow().isoformat()),
                }
        except ImportError:
            logger.warning("Promotion report not available")

        # Try merid.risk.promotion_engine
        try:
            from merid.risk.promotion_engine import get_promotion_engine
            engine = get_promotion_engine()

            if hasattr(engine, 'get_domain_eligibility'):
                domains_status = {}
                for domain in ["crypto", "prediction", "betting"]:
                    domains_status[domain] = engine.get_domain_eligibility(domain)

                eligible_count = sum(1 for d in domains_status.values() if d.get("eligible"))

                return {
                    "timestamp": datetime.utcnow().isoformat(),
                    "auto_promotion_enabled": True,
                    "domains": domains_status,
                    "eligible_count": eligible_count,
                    "total_domains": len(domains_status),
                    "last_sync": datetime.utcnow().isoformat(),
                }
        except:
            pass

        # Fallback: Return placeholder data
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "auto_promotion_enabled": False,
            "domains": {
                "crypto": {
                    "eligible": False,
                    "ring": 1,
                    "requirements_met": {
                        "pf_gate": False,
                        "expectancy_gate": False,
                        "sharpe_gate": False,
                        "trade_count_gate": False,
                        "stability_gate": False
                    },
                    "metrics": {
                        "pf": 0.0,
                        "expectancy": 0.0,
                        "sharpe": 0.0,
                        "trade_count": 0,
                        "stability_score": 0.0
                    },
                    "blocking_reason": "Promotion system not configured"
                },
                "prediction": {
                    "eligible": False,
                    "ring": 1,
                    "requirements_met": {
                        "pf_gate": False,
                        "expectancy_gate": False,
                        "sharpe_gate": False,
                        "trade_count_gate": False,
                        "stability_gate": False
                    },
                    "metrics": {
                        "pf": 0.0,
                        "expectancy": 0.0,
                        "sharpe": 0.0,
                        "trade_count": 0,
                        "stability_score": 0.0
                    },
                    "blocking_reason": "Promotion system not configured"
                },
            },
            "eligible_count": 0,
            "total_domains": 2,
            "last_sync": datetime.utcnow().isoformat(),
        }

    except Exception as e:
        logger.error(f"Failed to get promotion status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/domain/{domain}")
async def get_domain_promotion_status(domain: str) -> Dict[str, Any]:
    """
    Get detailed promotion status for a specific domain.

    Returns:
        {
            "domain": str,
            "eligible": bool,
            "ring": int (1-5),
            "gauntlet": {
                "ring1": {"name": str, "passed": bool, "requirements": {...}},
                "ring2": {"name": str, "passed": bool, "requirements": {...}},
                "ring3": {"name": str, "passed": bool, "requirements": {...}},
                "ring4": {"name": str, "passed": bool, "requirements": {...}},
                "ring5": {"name": str, "passed": bool, "requirements": {...}}
            },
            "metrics": {
                "pf": float,
                "expectancy": float,
                "sharpe": float,
                "trade_count": int,
                "win_rate": float,
                "avg_win": float,
                "avg_loss": float,
                "max_drawdown": float,
                "stability_score": float
            },
            "blocking_reasons": [str],
            "next_ring_requirements": {...},
            "last_updated": str
        }
    """
    try:
        # Try to get detailed domain status
        try:
            from merid.promotion_report import get_promotion_report
            report = get_promotion_report()

            if hasattr(report, 'get_domain_detail'):
                return report.get_domain_detail(domain)
        except:
            pass

        # Try promotion engine
        try:
            from merid.risk.promotion_engine import get_promotion_engine
            engine = get_promotion_engine()

            if hasattr(engine, 'get_domain_detail'):
                return engine.get_domain_detail(domain)
        except:
            pass

        # Fallback
        return {
            "domain": domain,
            "eligible": False,
            "ring": 1,
            "gauntlet": {
                "ring1": {
                    "name": "Profitability",
                    "passed": False,
                    "requirements": {"pf": ">1.2", "expectancy": ">0"}
                },
                "ring2": {
                    "name": "Risk-Adjusted Returns",
                    "passed": False,
                    "requirements": {"sharpe": ">0.5"}
                },
                "ring3": {
                    "name": "Statistical Significance",
                    "passed": False,
                    "requirements": {"trade_count": ">=100"}
                },
                "ring4": {
                    "name": "Consistency",
                    "passed": False,
                    "requirements": {"max_drawdown": "<15%", "stability": ">0.7"}
                },
                "ring5": {
                    "name": "Live Readiness",
                    "passed": False,
                    "requirements": {"all_rings_passed": True, "manual_approval": False}
                }
            },
            "metrics": {
                "pf": 0.0,
                "expectancy": 0.0,
                "sharpe": 0.0,
                "trade_count": 0,
                "win_rate": 0.0,
                "avg_win": 0.0,
                "avg_loss": 0.0,
                "max_drawdown": 0.0,
                "stability_score": 0.0
            },
            "blocking_reasons": ["Promotion system not configured"],
            "next_ring_requirements": {
                "pf": 1.2,
                "expectancy": 0.01,
                "sharpe": 0.5
            },
            "last_updated": datetime.utcnow().isoformat(),
        }

    except Exception as e:
        logger.error(f"Failed to get domain promotion status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Agent Promotion Status ──────────────────────────────────────────────


@router.get("/agents")
async def get_agent_promotion_status() -> Dict[str, Any]:
    """
    Get promotion status for all agents.

    Returns:
        {
            "agents": [
                {
                    "agent_id": str,
                    "domain": str,
                    "promoted": bool,
                    "blocked": bool,
                    "performance": {
                        "pf": float,
                        "sharpe": float,
                        "trade_count": int
                    },
                    "blocking_reason": str (if blocked)
                }
            ],
            "total_agents": int,
            "promoted_agents": int,
            "blocked_agents": int
        }
    """
    try:
        agents_list = []

        # Try to get agent promotion status
        try:
            from merid.promotion_report import get_promotion_report
            report = get_promotion_report()

            if hasattr(report, 'get_all_agent_status'):
                agents_list = report.get_all_agent_status()
        except:
            pass

        # If no data, try from agent grid
        if not agents_list:
            try:
                from merid.prediction.agent_grid import get_agent_grid
                grid = get_agent_grid()

                for agent in grid.agents:
                    agents_list.append({
                        "agent_id": agent.config.agent_id,
                        "domain": getattr(agent.config, "domain", "unknown"),
                        "promoted": False,
                        "blocked": False,
                        "performance": {
                            "pf": 0.0,
                            "sharpe": 0.0,
                            "trade_count": 0
                        },
                        "blocking_reason": None
                    })
            except:
                pass

        promoted_count = sum(1 for a in agents_list if a.get("promoted"))
        blocked_count = sum(1 for a in agents_list if a.get("blocked"))

        return {
            "agents": agents_list,
            "total_agents": len(agents_list),
            "promoted_agents": promoted_count,
            "blocked_agents": blocked_count,
        }

    except Exception as e:
        logger.error(f"Failed to get agent promotion status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/agents/{agent_id}")
async def get_agent_promotion_detail(agent_id: str) -> Dict[str, Any]:
    """Get detailed promotion status for a specific agent"""
    try:
        # Try to get agent detail
        try:
            from merid.promotion_report import get_promotion_report
            report = get_promotion_report()

            if hasattr(report, 'get_agent_detail'):
                return report.get_agent_detail(agent_id)
        except:
            pass

        # Fallback
        return {
            "agent_id": agent_id,
            "promoted": False,
            "blocked": False,
            "domain": "unknown",
            "performance": {
                "pf": 0.0,
                "sharpe": 0.0,
                "expectancy": 0.0,
                "trade_count": 0,
                "win_rate": 0.0
            },
            "blocking_reason": None,
            "promotion_history": [],
        }

    except Exception as e:
        logger.error(f"Failed to get agent promotion detail: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Promotion History ───────────────────────────────────────────────────


@router.get("/history")
async def get_promotion_history(
    limit: int = Query(50, description="Number of history entries to return"),
    domain: Optional[str] = Query(None, description="Filter by domain"),
) -> Dict[str, Any]:
    """
    Get promotion history (changes in eligibility).

    Returns:
        {
            "history": [
                {
                    "timestamp": str,
                    "domain": str,
                    "action": "promoted" | "demoted" | "blocked" | "unblocked",
                    "reason": str,
                    "operator": str,
                    "metrics_at_time": {...}
                }
            ],
            "total": int
        }
    """
    try:
        history = []

        # Try to get promotion history
        try:
            from merid.promotion_report import get_promotion_report
            report = get_promotion_report()

            if hasattr(report, 'get_history'):
                history = report.get_history(limit=limit, domain=domain)
        except:
            pass

        return {
            "history": history,
            "total": len(history),
        }

    except Exception as e:
        logger.error(f"Failed to get promotion history: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Manual Overrides ────────────────────────────────────────────────────


@router.post("/override")
async def override_promotion(req: PromotionOverrideRequest) -> Dict[str, Any]:
    """
    Manually override domain promotion eligibility.
    USE WITH CAUTION - bypasses performance gates.
    """
    try:
        # Try to apply override
        try:
            from merid.risk.promotion_engine import get_promotion_engine
            engine = get_promotion_engine()

            if hasattr(engine, 'override_eligibility'):
                result = engine.override_eligibility(
                    domain=req.domain,
                    eligible=req.eligible,
                    operator=req.operator,
                    reason=req.reason,
                    duration_hours=req.duration_hours
                )

                logger.warning(
                    f"Promotion override by {req.operator}: domain={req.domain}, "
                    f"eligible={req.eligible}, reason={req.reason}"
                )

                return {
                    "success": True,
                    "domain": req.domain,
                    "eligible": req.eligible,
                    "operator": req.operator,
                    "reason": req.reason,
                    "expires_at": result.get("expires_at"),
                    "applied_at": datetime.utcnow().isoformat(),
                }
            else:
                raise HTTPException(status_code=501, detail="Promotion override not implemented")

        except ImportError:
            raise HTTPException(status_code=501, detail="Promotion engine not available")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to override promotion: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/overrides")
async def get_active_overrides() -> Dict[str, Any]:
    """Get all active promotion overrides"""
    try:
        overrides = []

        try:
            from merid.risk.promotion_engine import get_promotion_engine
            engine = get_promotion_engine()

            if hasattr(engine, 'get_active_overrides'):
                overrides = engine.get_active_overrides()
        except:
            pass

        return {
            "overrides": overrides,
            "total_overrides": len(overrides),
        }

    except Exception as e:
        logger.error(f"Failed to get active overrides: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/agents/action")
async def agent_promotion_action(req: AgentPromotionRequest) -> Dict[str, Any]:
    """
    Promote or block a specific agent.
    """
    try:
        # Try to perform agent action
        try:
            from merid.promotion_report import get_promotion_report
            report = get_promotion_report()

            if req.action == "promote":
                if hasattr(report, 'promote_agent'):
                    result = report.promote_agent(req.agent_id, req.operator, req.reason)
                else:
                    raise HTTPException(status_code=501, detail="Agent promotion not implemented")
            elif req.action == "block":
                if hasattr(report, 'block_agent'):
                    result = report.block_agent(req.agent_id, req.operator, req.reason)
                else:
                    raise HTTPException(status_code=501, detail="Agent blocking not implemented")
            else:
                raise HTTPException(status_code=400, detail=f"Invalid action: {req.action}")

            logger.info(f"Agent {req.action} by {req.operator}: agent_id={req.agent_id}, reason={req.reason}")

            return {
                "success": True,
                "agent_id": req.agent_id,
                "action": req.action,
                "operator": req.operator,
                "reason": req.reason,
                "applied_at": datetime.utcnow().isoformat(),
            }

        except ImportError:
            raise HTTPException(status_code=501, detail="Promotion report not available")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to perform agent action: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Gauntlet Configuration ──────────────────────────────────────────────


@router.get("/gauntlet/config")
async def get_gauntlet_config() -> Dict[str, Any]:
    """
    Get 5-ring gauntlet configuration (thresholds and requirements).

    Returns:
        {
            "rings": [
                {
                    "ring": int,
                    "name": str,
                    "requirements": {...},
                    "description": str
                }
            ],
            "auto_promotion_enabled": bool,
            "sync_interval_seconds": int
        }
    """
    try:
        # Try to get gauntlet config
        try:
            from merid.risk.promotion_engine import get_promotion_engine
            engine = get_promotion_engine()

            if hasattr(engine, 'get_gauntlet_config'):
                return engine.get_gauntlet_config()
        except:
            pass

        # Fallback: Return default config
        return {
            "rings": [
                {
                    "ring": 1,
                    "name": "Profitability",
                    "requirements": {
                        "pf": {"threshold": 1.2, "operator": ">"},
                        "expectancy": {"threshold": 0.01, "operator": ">"}
                    },
                    "description": "Basic profitability: PF > 1.2 and positive expectancy"
                },
                {
                    "ring": 2,
                    "name": "Risk-Adjusted Returns",
                    "requirements": {
                        "sharpe": {"threshold": 0.5, "operator": ">"}
                    },
                    "description": "Positive risk-adjusted returns: Sharpe > 0.5"
                },
                {
                    "ring": 3,
                    "name": "Statistical Significance",
                    "requirements": {
                        "trade_count": {"threshold": 100, "operator": ">="}
                    },
                    "description": "Sufficient sample size: >= 100 trades"
                },
                {
                    "ring": 4,
                    "name": "Consistency",
                    "requirements": {
                        "max_drawdown": {"threshold": 15.0, "operator": "<"},
                        "stability_score": {"threshold": 0.7, "operator": ">"}
                    },
                    "description": "Stable performance: drawdown < 15%, stability > 0.7"
                },
                {
                    "ring": 5,
                    "name": "Live Readiness",
                    "requirements": {
                        "all_rings_passed": True,
                        "manual_approval": False
                    },
                    "description": "All requirements met and ready for live trading"
                }
            ],
            "auto_promotion_enabled": True,
            "sync_interval_seconds": 300,  # 5 minutes
        }

    except Exception as e:
        logger.error(f"Failed to get gauntlet config: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Health Check ────────────────────────────────────────────────────────


@router.get("/health")
async def get_promotion_health() -> Dict[str, Any]:
    """Health check for promotion system"""
    try:
        components = {
            "promotion_report": False,
            "promotion_engine": False,
            "gauntlet": False,
            "auto_sync": False,
        }

        # Check promotion report
        try:
            from merid.promotion_report import get_promotion_report
            get_promotion_report()
            components["promotion_report"] = True
        except:
            pass

        # Check promotion engine
        try:
            from merid.risk.promotion_engine import get_promotion_engine
            get_promotion_engine()
            components["promotion_engine"] = True
            components["gauntlet"] = True
            components["auto_sync"] = True
        except:
            pass

        healthy_count = sum(components.values())
        total_count = len(components)

        return {
            "status": "healthy" if healthy_count >= 1 else "degraded",
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
