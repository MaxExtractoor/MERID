from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Request, status

from core.agent_orchestrator import get_agent_orchestrator
from core.cross_domain_portfolio import get_portfolio_engine
from core.automated_risk_controls import get_risk_coordinator
from core.env import capabilities
from security.breach_detection import get_breach_detection_system
from social.social_aware_quant import (
    get_social_aware_quant_engine,
    get_social_bot_health_monitor,
)
from social.social_data_quality import get_social_data_quality_monitor
from social.x_bot_commands import get_default_commands
from swarm.anti_silent_failure import get_anti_silent_failure_system
from swarm.security_defense_system import get_security_defense_system


router = APIRouter(tags=["x-bot"])


def _require_service_token(request: Request) -> None:
    """Simple auth gate for internal bot calls."""
    expected = capabilities.x_bot_service_token
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="X bot service token not configured",
        )

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")

    token = auth_header.split(" ", 1)[1]
    if token != expected:
        system = get_breach_detection_system()
        system.detect_auth_failure("x_bot_service", request.client.host if request.client else "unknown", "invalid_token")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


@router.get("/x/status")
async def get_x_status(_: None = Depends(_require_service_token)) -> Dict[str, Any]:
    orchestrator = get_agent_orchestrator()
    anti_silent = get_anti_silent_failure_system()
    health_monitor = get_social_bot_health_monitor()
    data_quality = get_social_data_quality_monitor()

    system_stats = orchestrator.get_system_stats()
    health = anti_silent.get_health_report()

    return {
        "system_running": system_stats.get("running", False),
        "agents": system_stats,
        "health": {
            "components": health["components"],
            "data_feeds": health["data_feeds"],
            "incidents": health["incidents"],
            "generated_at": health["generated_at"],
        },
        "social_bot_health": health_monitor.get_health_status(),
        "social_data_quality": data_quality.get_status(),
    }


@router.get("/x/portfolio")
async def get_x_portfolio(_: None = Depends(_require_service_token)) -> Dict[str, Any]:
    engine = get_portfolio_engine()
    total_value = engine.get_total_value()
    pnl = engine.get_total_pnl()
    allocation = engine.get_allocation_by_class()

    positions = [
        {
            "position_id": pos.position_id,
            "asset_class": pos.asset_class.value,
            "symbol": pos.symbol,
            "quantity": pos.quantity,
            "entry_price": pos.entry_price,
            "current_price": pos.current_price,
            "unrealized_pnl": pos.unrealized_pnl,
        }
        for pos in engine._positions.values()  # type: ignore[attr-defined]
    ]

    return {
        "portfolio_value": total_value,
        "total_pnl": pnl,
        "allocation": {k.value: v for k, v in allocation.items()},
        "positions": positions[:25],
    }


@router.get("/x/risk")
async def get_x_risk(_: None = Depends(_require_service_token)) -> Dict[str, Any]:
    coordinator = get_risk_coordinator()
    status_payload = coordinator.get_comprehensive_risk_status()

    social_engine = get_social_aware_quant_engine()
    social_status = social_engine.get_social_risk_status()

    return {
        "portfolio_risk": status_payload["portfolio_risk"],
        "active_stops": status_payload["active_stops"],
        "monitoring_active": status_payload["monitoring_active"],
        "social_kill_switch": social_status,
    }


def _collect_incidents() -> List[Dict[str, Any]]:
    anti_silent = get_anti_silent_failure_system()
    security_system = get_security_defense_system()

    incidents = []
    for incident in anti_silent.get_active_incidents():
        incidents.append(
            {
                "source": "anti_silent_failure",
                "incident_id": incident.incident_id,
                "failure_class": incident.failure_class.value,
                "severity": incident.severity,
                "component_id": incident.component_id,
                "description": incident.description,
                "evidence": incident.evidence,
            }
        )

    for sec_incident in security_system._incidents:  # type: ignore[attr-defined]
        if sec_incident.resolved:
            continue
        incidents.append(
            {
                "source": "security_defense",
                "incident_id": sec_incident.incident_id,
                "attack_vector": sec_incident.attack_vector.value,
                "threat_level": sec_incident.threat_level.value,
                "description": sec_incident.description,
                "affected_components": sec_incident.affected_components,
                "evidence": sec_incident.evidence,
            }
        )

    return incidents


@router.get("/x/incidents")
async def get_x_incidents(_: None = Depends(_require_service_token)) -> Dict[str, Any]:
    incidents = _collect_incidents()
    return {"incidents": incidents, "total": len(incidents)}


@router.get("/x/social-intel")
async def get_x_social_intel(_: None = Depends(_require_service_token)) -> Dict[str, Any]:
    engine = get_social_aware_quant_engine()
    risk_status = engine.get_social_risk_status()
    top_assets = engine.get_top_asset_exposure(limit=5)

    return {
        "risk_status": risk_status,
        "top_assets": top_assets,
    }


@router.get("/x/help")
async def get_x_help(_: None = Depends(_require_service_token)) -> Dict[str, Any]:
    commands = get_default_commands()
    return {
        "commands": [
            {
                "name": cmd.name,
                "description": cmd.description,
                "required_role": cmd.required_role.value,
                "type": cmd.command_type.value,
                "risk_level": cmd.risk_level,
            }
            for cmd in commands.values()
        ]
    }
