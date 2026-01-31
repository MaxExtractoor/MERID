"""
Degraded Service Endpoints

Provides graceful degradation for missing or disabled services.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict, Any
import time

from utils.logger import get_logger

logger = get_logger("web.api.degraded")
router = APIRouter(prefix="/api/v1", tags=["degraded"])


class DegradedServiceResponse(BaseModel):
    """Response for degraded service status."""
    service: str
    status: str
    message: str
    timestamp: float
    available_alternatives: list = []


@router.get("/governance/charter-registry")
async def governance_charter_registry_degraded():
    """Degraded governance charter registry endpoint."""
    return DegradedServiceResponse(
        service="governance_charter_registry",
        status="degraded",
        message="Governance charter registry is not configured. Reality system requires bootstrap.",
        timestamp=time.time(),
        available_alternatives=[
            "POST /api/v1/reality/bootstrap - Initialize reality system",
            "GET /api/v1/reality/status - Check reality system status"
        ]
    )


@router.get("/intelligence/summary")
async def intelligence_summary_degraded():
    """Degraded intelligence summary endpoint."""
    return DegradedServiceResponse(
        service="intelligence_summary",
        status="degraded",
        message="Intelligence service is not configured. Reality system requires bootstrap.",
        timestamp=time.time(),
        available_alternatives=[
            "POST /api/v1/reality/bootstrap - Initialize reality system",
            "GET /api/v1/localvenue/validation-status - Check local venue status"
        ]
    )


@router.get("/governance/status")
async def governance_status_degraded():
    """Degraded governance status endpoint."""
    return DegradedServiceResponse(
        service="governance_status",
        status="degraded",
        message="Governance system is not configured. Reality system requires bootstrap.",
        timestamp=time.time(),
        available_alternatives=[
            "POST /api/v1/reality/bootstrap - Initialize reality system",
            "GET /api/v1/reality/status - Check reality system status"
        ]
    )


@router.get("/intelligence/dashboard")
async def intelligence_dashboard_degraded():
    """Degraded intelligence dashboard endpoint."""
    return DegradedServiceResponse(
        service="intelligence_dashboard",
        status="degraded",
        message="Intelligence dashboard is not configured. Reality system requires bootstrap.",
        timestamp=time.time(),
        available_alternatives=[
            "POST /api/v1/reality/bootstrap - Initialize reality system",
            "GET /api/v1/localvenue/validation-status - Check local venue status"
        ]
    )


@router.get("/governance/authority/status")
async def governance_authority_status_degraded():
    """Degraded governance authority status endpoint."""
    return DegradedServiceResponse(
        service="governance_authority_status",
        status="degraded",
        message="Governance authority system is not configured. Reality system requires bootstrap.",
        timestamp=time.time(),
        available_alternatives=[
            "POST /api/v1/reality/bootstrap - Initialize reality system",
            "GET /api/v1/reality/status - Check reality system status"
        ]
    )


@router.get("/governance/constitutional/status")
async def governance_constitutional_status_degraded():
    """Degraded governance constitutional status endpoint."""
    return DegradedServiceResponse(
        service="governance_constitutional_status",
        status="degraded",
        message="Governance constitutional system is not configured. Reality system requires bootstrap.",
        timestamp=time.time(),
        available_alternatives=[
            "POST /api/v1/reality/bootstrap - Initialize reality system",
            "GET /api/v1/reality/status - Check reality system status"
        ]
    )


@router.get("/governance/consensus/status")
async def governance_consensus_status_degraded():
    """Degraded governance consensus status endpoint."""
    return DegradedServiceResponse(
        service="governance_consensus_status",
        status="degraded",
        message="Governance consensus system is not configured. Reality system requires bootstrap.",
        timestamp=time.time(),
        available_alternatives=[
            "POST /api/v1/reality/bootstrap - Initialize reality system",
            "GET /api/v1/reality/status - Check reality system status"
        ]
    )
