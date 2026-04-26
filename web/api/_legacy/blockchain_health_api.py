"""
API endpoints for blockchain/on-chain health monitoring.
Exposes merid/blockchain/ package status to the frontend.
"""
from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter

from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/blockchain", tags=["blockchain"])


def _get_gateway():
    try:
        from merid.blockchain.gateway import get_blockchain_gateway
        return get_blockchain_gateway()
    except Exception as e:
        logger.warning(f"BlockchainGateway unavailable: {e}")
        return None


def _get_compliance():
    try:
        from merid.blockchain.compliance import get_compliance_registry
        return get_compliance_registry()
    except Exception as e:
        logger.warning(f"ComplianceRegistry unavailable: {e}")
        return None


def _get_execution():
    try:
        from merid.blockchain.execution import get_execution_service
        return get_execution_service()
    except Exception as e:
        logger.warning(f"ExecutionService unavailable: {e}")
        return None


@router.get("/health")
async def get_blockchain_health():
    """Get health status of all blockchain providers and services."""
    gateway = _get_gateway()
    execution = _get_execution()

    providers = []
    if gateway:
        try:
            summary = gateway.summary()
            for provider in summary.get("providers", []):
                providers.append({
                    "name": provider.get("name", "unknown"),
                    "chain": provider.get("chain", "unknown"),
                    "url": provider.get("url", "")[:40] + "...",
                    "status": "healthy" if provider.get("healthy", False) else "down",
                    "priority": provider.get("priority", 0),
                    "latencyMs": provider.get("latency_ms", 0),
                })
        except Exception as e:
            logger.error(f"Error fetching gateway health: {e}")

    circuit_breakers = []
    if execution:
        try:
            summary = execution.summary()
            for chain, cb_state in summary.get("circuit_breakers", {}).items():
                circuit_breakers.append({
                    "chain": chain,
                    "state": cb_state.get("state", "unknown"),
                    "trippedAt": cb_state.get("tripped_at", ""),
                    "reason": cb_state.get("reason", ""),
                })
        except Exception as e:
            logger.error(f"Error fetching execution health: {e}")

    return {
        "status": "ok",
        "providers": providers,
        "circuitBreakers": circuit_breakers,
        "providerCount": len(providers),
        "healthyCount": sum(1 for p in providers if p["status"] == "healthy"),
    }


@router.get("/compliance")
async def get_compliance_summary():
    """Get compliance registry summary."""
    registry = _get_compliance()
    if not registry:
        return {"status": "unavailable"}

    try:
        summary = registry.summary()
        return {"status": "ok", **summary}
    except Exception as e:
        logger.error(f"Error fetching compliance summary: {e}")
        return {"status": "error", "error": str(e)}
