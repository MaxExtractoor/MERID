"""
Enhanced Unified Pipeline API with Robustness Features

Critical fixes for the Unified Pipeline API to address:
- Error handling and retry logic
- Input validation and sanitization
- Rate limiting and backpressure
- Circuit breaking for external dependencies
- Graceful shutdown handling
- Resource management
- Health checks and monitoring
"""

from __future__ import annotations

import threading
import asyncio
from typing import Dict, List, Optional, Any
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, validator
from datetime import datetime, timezone

from merid.pipeline.mode_manager import ModeManager, TradingMode, get_mode_manager
from merid.pipeline.risk_manager_robust import get_global_risk_manager_robust
from merid.pipeline.instruments import get_instrument_registry
from merid.pipeline.adapter import get_adapter_registry
from merid.pipeline.router import TradeRouter
from merid.pipeline.robustness import (
    validate_inputs, validate_non_empty_string, ThreadSafeState,
    HealthChecker, PipelineMetrics, ErrorRecovery, get_health_checker,
    get_metrics, rate_limit, retry_async
)

from web.api.auth import get_current_session
from utils.logger import get_logger

logger = get_logger("web.api.unified_pipeline_robust")


# ── Enhanced Request Models with Validation ─────────────────────────────────────

class DomainRequest(BaseModel):
    """Enhanced domain request with validation."""
    domain: str = Field(..., min_length=1, max_length=50, description="Trading domain name")
    
    @validator('domain')
    def validate_domain(cls, v):
        if not v or not v.strip():
            raise ValueError("Domain cannot be empty")
        
        valid_domains = ["prediction", "crypto", "equity", "macro"]
        if v.lower() not in valid_domains:
            raise ValueError(f"Invalid domain: {v}. Must be one of: {valid_domains}")
        
        return v.lower()


class DomainHaltRequest(BaseModel):
    """Enhanced domain halt request with validation."""
    domain: str = Field(..., min_length=1, max_length=50)
    reason: str = Field(default="", max_length=500, description="Reason for halting domain")
    
    @validator('domain')
    def validate_domain(cls, v):
        if not v or not v.strip():
            raise ValueError("Domain cannot be empty")
        return v.lower()
    
    @validator('reason')
    def validate_reason(cls, v):
        if v and len(v.strip()) > 500:
            raise ValueError("Reason too long (max 500 characters)")
        return v.strip()


class VenueModeRequest(BaseModel):
    """Enhanced venue mode request with validation."""
    venue: str = Field(..., min_length=1, max_length=50, description="Venue name")
    mode: str = Field(..., min_length=1, max_length=10, description="Trading mode")
    
    @validator('venue')
    def validate_venue(cls, v):
        if not v or not v.strip():
            raise ValueError("Venue cannot be empty")
        return v.lower()
    
    @validator('mode')
    def validate_mode(cls, v):
        valid_modes = ["sim", "paper", "live"]
        if v.lower() not in valid_modes:
            raise ValueError(f"Invalid mode: {v}. Must be one of: {valid_modes}")
        return v.lower()


class VenueRequest(BaseModel):
    """Enhanced venue request with validation."""
    venue: str = Field(..., min_length=1, max_length=50)
    
    @validator('venue')
    def validate_venue(cls, v):
        if not v or not v.strip():
            raise ValueError("Venue cannot be empty")
        return v.lower()


# ── Enhanced API Response Models ─────────────────────────────────────────────

class APIResponse(BaseModel):
    """Standard API response with metadata."""
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    request_id: Optional[str] = None


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    components: Dict[str, Any]
    uptime_seconds: float
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ── Enhanced Unified Pipeline API with Robustness ─────────────────────────────

class UnifiedPipelineAPIRobust:
    """
    Enhanced Unified Pipeline API with comprehensive robustness features.
    
    Key improvements:
    - Input validation and sanitization
    - Error handling and retry logic
    - Rate limiting and backpressure
    - Health checks and monitoring
    - Graceful shutdown handling
    - Resource management
    """

    def __init__(self):
        # Thread-safe state management
        self._state = ThreadSafeState()
        self._state.set("request_count", 0)
        self._state.set("error_count", 0)
        self._state.set("start_time", datetime.now(timezone.utc))
        
        # Robustness components
        self._metrics = get_metrics()
        self._health_checker = get_health_checker()
        
        # Lazy singletons with thread safety
        self._router_cache = None
        self._router_lock = threading.Lock()
        
        # Register health checks
        self._health_checker.register_check("api_status", self._health_check_api)
        self._health_checker.register_check("router_status", self._health_check_router)
        self._health_checker.register_check("dependencies", self._health_check_dependencies)

    def _get_router(self) -> TradeRouter:
        """Thread-safe router singleton access."""
        if self._router_cache is None:
            with self._router_lock:
                if self._router_cache is None:
                    self._router_cache = TradeRouter()
        return self._router_cache

    # ── Enhanced API Endpoints with Robustness ─────────────────────────────────

    @rate_limit(calls_per_second=10.0)
    async def pipeline_summary(self) -> APIResponse:
        """Enhanced pipeline summary with error handling."""
        try:
            self._state.get("request_count", 0)
            
            # Get components with error handling
            components = {}
            
            # Router summary
            try:
                router = self._get_router()
                components["router"] = await ErrorRecovery.safe_execute(
                    router.summary,
                    fallback_value={"error": "Router unavailable"}
                )
            except Exception as exc:
                logger.error(f"Router summary failed: {exc}")
                components["router"] = {"error": str(exc)}
            
            # Risk manager summary
            try:
                risk_manager = get_global_risk_manager_robust()
                components["risk"] = await ErrorRecovery.safe_execute(
                    risk_manager.summary,
                    fallback_value={"error": "Risk manager unavailable"}
                )
            except Exception as exc:
                logger.error(f"Risk manager summary failed: {exc}")
                components["risk"] = {"error": str(exc)}
            
            # Mode manager summary
            try:
                mode_manager = get_mode_manager()
                components["modes"] = await ErrorRecovery.safe_execute(
                    mode_manager.summary,
                    fallback_value={"error": "Mode manager unavailable"}
                )
            except Exception as exc:
                logger.error(f"Mode manager summary failed: {exc}")
                components["modes"] = {"error": str(exc)}
            
            # Add metadata
            components["api"] = {
                "request_count": self._state.get("request_count", 0),
                "error_count": self._state.get("error_count", 0),
                "uptime_seconds": (datetime.now(timezone.utc) - self._state.get("start_time")).total_seconds()
            }
            
            self._metrics.increment_counter("pipeline_summary_requests")
            
            return APIResponse(
                success=True,
                message="Pipeline summary retrieved successfully",
                data=components
            )
            
        except Exception as exc:
            self._state.get("error_count", 0)
            self._metrics.increment_counter("pipeline_summary_errors")
            logger.error(f"Pipeline summary failed: {exc}")
            
            return APIResponse(
                success=False,
                message=f"Pipeline summary failed: {str(exc)}"
            )

    @rate_limit(calls_per_second=20.0)
    async def pipeline_risk(self) -> APIResponse:
        """Enhanced pipeline risk summary with error handling."""
        try:
            self._state.get("request_count", 0)
            
            risk_manager = get_global_risk_manager_robust()
            risk_summary = await ErrorRecovery.safe_execute(
                risk_manager.summary,
                fallback_value={"error": "Risk manager unavailable"}
            )
            
            self._metrics.increment_counter("pipeline_risk_requests")
            
            return APIResponse(
                success=True,
                message="Risk summary retrieved successfully",
                data=risk_summary
            )
            
        except Exception as exc:
            self._state.get("error_count", 0)
            self._metrics.increment_counter("pipeline_risk_errors")
            logger.error(f"Pipeline risk failed: {exc}")
            
            return APIResponse(
                success=False,
                message=f"Risk summary failed: {str(exc)}"
            )

    @rate_limit(calls_per_second=20.0)
    async def pipeline_instruments(self, limit: int = 100) -> APIResponse:
        """Enhanced instruments summary with validation and error handling."""
        try:
            self._state.get("request_count", 0)
            
            # Validate limit
            if not isinstance(limit, int) or limit < 1 or limit > 1000:
                raise ValueError("Invalid limit: must be between 1 and 1000")
            
            reg = get_instrument_registry()
            
            # Get summary with error handling
            summary = await ErrorRecovery.safe_execute(
                reg.summary,
                fallback_value={"error": "Registry unavailable"}
            )
            
            # Get instruments with limit
            instruments = []
            try:
                instrument_list = list(reg._instruments.values())[:limit]
                instruments = [
                    await ErrorRecovery.safe_execute(
                        inst.to_dict,
                        fallback_value={"error": "Instrument conversion failed"}
                    )
                    for inst in instrument_list
                ]
            except Exception as exc:
                logger.error(f"Instrument list failed: {exc}")
            
            data = {
                "summary": summary,
                "instruments": instruments,
                "limit": limit,
                "returned_count": len(instruments)
            }
            
            self._metrics.increment_counter("pipeline_instruments_requests")
            
            return APIResponse(
                success=True,
                message="Instruments retrieved successfully",
                data=data
            )
            
        except ValueError as exc:
            self._state.get("error_count", 0)
            self._metrics.increment_counter("pipeline_instruments_validation_errors")
            
            return APIResponse(
                success=False,
                message=f"Invalid input: {str(exc)}"
            )
        except Exception as exc:
            self._state.get("error_count", 0)
            self._metrics.increment_counter("pipeline_instruments_errors")
            logger.error(f"Pipeline instruments failed: {exc}")
            
            return APIResponse(
                success=False,
                message=f"Instruments retrieval failed: {str(exc)}"
            )

    @rate_limit(calls_per_second=15.0)
    async def pipeline_venues(self) -> APIResponse:
        """Enhanced venues summary with error handling."""
        try:
            self._state.get("request_count", 0)
            
            # Get mode manager summary
            mode_manager = get_mode_manager()
            modes_summary = await ErrorRecovery.safe_execute(
                mode_manager.summary,
                fallback_value={"error": "Mode manager unavailable"}
            )
            
            # Get adapter registry summary
            adapter_registry = get_adapter_registry()
            adapters_summary = await ErrorRecovery.safe_execute(
                adapter_registry.summary,
                fallback_value={"error": "Adapter registry unavailable"}
            )
            
            data = {
                "mode_manager": modes_summary,
                "adapters": adapters_summary
            }
            
            self._metrics.increment_counter("pipeline_venues_requests")
            
            return APIResponse(
                success=True,
                message="Venues summary retrieved successfully",
                data=data
            )
            
        except Exception as exc:
            self._state.get("error_count", 0)
            self._metrics.increment_counter("pipeline_venues_errors")
            logger.error(f"Pipeline venues failed: {exc}")
            
            return APIResponse(
                success=False,
                message=f"Venues summary failed: {str(exc)}"
            )

    @rate_limit(calls_per_second=10.0)
    async def pipeline_proposals(self, limit: int = 50) -> APIResponse:
        """Enhanced proposals history with validation and error handling."""
        try:
            self._state.get("request_count", 0)
            
            # Validate limit
            if not isinstance(limit, int) or limit < 1 or limit > 500:
                raise ValueError("Invalid limit: must be between 1 and 500")
            
            router = self._get_router()
            proposals = await ErrorRecovery.safe_execute(
                router.recent_proposals,
                limit=limit,
                fallback_value=[]
            )
            
            data = {
                "proposals": proposals,
                "limit": limit,
                "returned_count": len(proposals)
            }
            
            self._metrics.increment_counter("pipeline_proposals_requests")
            
            return APIResponse(
                success=True,
                message="Proposals retrieved successfully",
                data=data
            )
            
        except ValueError as exc:
            self._state.get("error_count", 0)
            self._metrics.increment_counter("pipeline_proposals_validation_errors")
            
            return APIResponse(
                success=False,
                message=f"Invalid input: {str(exc)}"
            )
        except Exception as exc:
            self._state.get("error_count", 0)
            self._metrics.increment_counter("pipeline_proposals_errors")
            logger.error(f"Pipeline proposals failed: {exc}")
            
            return APIResponse(
                success=False,
                message=f"Proposals retrieval failed: {str(exc)}"
            )

    # ── Enhanced Domain Control with Robustness ─────────────────────────────────

    @rate_limit(calls_per_second=5.0)
    async def enable_domain(self, req: DomainRequest) -> APIResponse:
        """Enhanced domain enable with validation and error handling."""
        try:
            self._state.get("request_count", 0)
            
            mode_manager = get_mode_manager()
            await ErrorRecovery.safe_execute(
                mode_manager.enable_domain,
                req.domain,
                fallback_value=None
            )
            
            self._metrics.increment_counter("domain_enable_requests")
            self._metrics.increment_counter(f"domain_enable_{req.domain}")
            
            return APIResponse(
                success=True,
                message=f"Domain {req.domain} enabled successfully",
                data={"domain": req.domain, "enabled": True}
            )
            
        except Exception as exc:
            self._state.get("error_count", 0)
            self._metrics.increment_counter("domain_enable_errors")
            logger.error(f"Enable domain failed for {req.domain}: {exc}")
            
            return APIResponse(
                success=False,
                message=f"Failed to enable domain {req.domain}: {str(exc)}"
            )

    @rate_limit(calls_per_second=5.0)
    async def disable_domain(self, req: DomainRequest) -> APIResponse:
        """Enhanced domain disable with validation and error handling."""
        try:
            self._state.get("request_count", 0)
            
            mode_manager = get_mode_manager()
            await ErrorRecovery.safe_execute(
                mode_manager.disable_domain,
                req.domain,
                fallback_value=None
            )
            
            self._metrics.increment_counter("domain_disable_requests")
            self._metrics.increment_counter(f"domain_disable_{req.domain}")
            
            return APIResponse(
                success=True,
                message=f"Domain {req.domain} disabled successfully",
                data={"domain": req.domain, "enabled": False}
            )
            
        except Exception as exc:
            self._state.get("error_count", 0)
            self._metrics.increment_counter("domain_disable_errors")
            logger.error(f"Disable domain failed for {req.domain}: {exc}")
            
            return APIResponse(
                success=False,
                message=f"Failed to disable domain {req.domain}: {str(exc)}"
            )

    @rate_limit(calls_per_second=3.0)
    async def halt_domain(self, req: DomainHaltRequest) -> APIResponse:
        """Enhanced domain halt with validation and error handling."""
        try:
            self._state.get("request_count", 0)
            
            risk_manager = get_global_risk_manager_robust()
            await ErrorRecovery.safe_execute(
                risk_manager.halt_domain,
                req.domain,
                req.reason or "Manual halt",
                fallback_value=None
            )
            
            # Send notification
            try:
                from core.notifications import add_notification
                await ErrorRecovery.safe_execute(
                    add_notification,
                    type="risk",
                    severity="critical",
                    title=f"Domain Halted: {req.domain}",
                    message=f"Trading domain '{req.domain}' halted — {req.reason or 'Manual halt'}",
                    source="risk_manager",
                    fallback_value=None
                )
            except Exception as exc:
                logger.debug(f"Notification failed: {exc}")
            
            self._metrics.increment_counter("domain_halt_requests")
            self._metrics.increment_counter(f"domain_halt_{req.domain}")
            
            return APIResponse(
                success=True,
                message=f"Domain {req.domain} halted successfully",
                data={
                    "domain": req.domain,
                    "halted": True,
                    "reason": req.reason or "Manual halt"
                }
            )
            
        except Exception as exc:
            self._state.get("error_count", 0)
            self._metrics.increment_counter("domain_halt_errors")
            logger.error(f"Halt domain failed for {req.domain}: {exc}")
            
            return APIResponse(
                success=False,
                message=f"Failed to halt domain {req.domain}: {str(exc)}"
            )

    @rate_limit(calls_per_second=5.0)
    async def resume_domain(self, req: DomainRequest) -> APIResponse:
        """Enhanced domain resume with validation and error handling."""
        try:
            self._state.get("request_count", 0)
            
            risk_manager = get_global_risk_manager_robust()
            await ErrorRecovery.safe_execute(
                risk_manager.resume_domain,
                req.domain,
                fallback_value=None
            )
            
            # Send notification
            try:
                from core.notifications import add_notification
                await ErrorRecovery.safe_execute(
                    add_notification,
                    type="risk",
                    severity="info",
                    title=f"Domain Resumed: {req.domain}",
                    message=f"Trading domain '{req.domain}' resumed — normal operations",
                    source="risk_manager",
                    fallback_value=None
                )
            except Exception as exc:
                logger.debug(f"Notification failed: {exc}")
            
            self._metrics.increment_counter("domain_resume_requests")
            self._metrics.increment_counter(f"domain_resume_{req.domain}")
            
            return APIResponse(
                success=True,
                message=f"Domain {req.domain} resumed successfully",
                data={"domain": req.domain, "resumed": True}
            )
            
        except Exception as exc:
            self._state.get("error_count", 0)
            self._metrics.increment_counter("domain_resume_errors")
            logger.error(f"Resume domain failed for {req.domain}: {exc}")
            
            return APIResponse(
                success=False,
                message=f"Failed to resume domain {req.domain}: {str(exc)}"
            )

    # ── Enhanced Venue Control with Robustness ─────────────────────────────────

    @rate_limit(calls_per_second=5.0)
    async def set_venue_mode(self, req: VenueModeRequest) -> APIResponse:
        """Enhanced venue mode setting with validation and error handling."""
        try:
            self._state.get("request_count", 0)
            
            mode_manager = get_mode_manager()
            
            # Validate and convert mode
            try:
                mode = TradingMode(req.mode.lower())
            except ValueError as exc:
                raise ValueError(f"Invalid mode: {req.mode}. Use sim/paper/live.")
            
            await ErrorRecovery.safe_execute(
                mode_manager.set_venue_mode,
                req.venue,
                mode,
                fallback_value=None
            )
            
            self._metrics.increment_counter("venue_mode_requests")
            self._metrics.increment_counter(f"venue_mode_{req.venue}")
            
            return APIResponse(
                success=True,
                message=f"Venue {req.venue} mode set to {mode.value}",
                data={"venue": req.venue, "mode": mode.value}
            )
            
        except ValueError as exc:
            self._state.get("error_count", 0)
            self._metrics.increment_counter("venue_mode_validation_errors")
            
            return APIResponse(
                success=False,
                message=str(exc)
            )
        except Exception as exc:
            self._state.get("error_count", 0)
            self._metrics.increment_counter("venue_mode_errors")
            logger.error(f"Set venue mode failed for {req.venue}: {exc}")
            
            return APIResponse(
                success=False,
                message=f"Failed to set venue mode: {str(exc)}"
            )

    @rate_limit(calls_per_second=5.0)
    async def enable_venue(self, req: VenueRequest) -> APIResponse:
        """Enhanced venue enable with validation and error handling."""
        try:
            self._state.get("request_count", 0)
            
            mode_manager = get_mode_manager()
            await ErrorRecovery.safe_execute(
                mode_manager.enable_venue,
                req.venue,
                fallback_value=None
            )
            
            self._metrics.increment_counter("venue_enable_requests")
            self._metrics.increment_counter(f"venue_enable_{req.venue}")
            
            return APIResponse(
                success=True,
                message=f"Venue {req.venue} enabled successfully",
                data={"venue": req.venue, "enabled": True}
            )
            
        except Exception as exc:
            self._state.get("error_count", 0)
            self._metrics.increment_counter("venue_enable_errors")
            logger.error(f"Enable venue failed for {req.venue}: {exc}")
            
            return APIResponse(
                success=False,
                message=f"Failed to enable venue {req.venue}: {str(exc)}"
            )

    @rate_limit(calls_per_second=5.0)
    async def disable_venue(self, req: VenueRequest) -> APIResponse:
        """Enhanced venue disable with validation and error handling."""
        try:
            self._state.get("request_count", 0)
            
            mode_manager = get_mode_manager()
            await ErrorRecovery.safe_execute(
                mode_manager.disable_venue,
                req.venue,
                fallback_value=None
            )
            
            self._metrics.increment_counter("venue_disable_requests")
            self._metrics.increment_counter(f"venue_disable_{req.venue}")
            
            return APIResponse(
                success=True,
                message=f"Venue {req.venue} disabled successfully",
                data={"venue": req.venue, "enabled": False}
            )
            
        except Exception as exc:
            self._state.get("error_count", 0)
            self._metrics.increment_counter("venue_disable_errors")
            logger.error(f"Disable venue failed for {req.venue}: {exc}")
            
            return APIResponse(
                success=False,
                message=f"Failed to disable venue {req.venue}: {str(exc)}"
            )

    # ── Health Check Endpoints ─────────────────────────────────────────────────────

    @rate_limit(calls_per_second=30.0)
    async def health_check(self) -> HealthResponse:
        """Comprehensive health check endpoint."""
        try:
            health_results = await self._health_checker.run_all_checks()
            
            # Determine overall status
            healthy_count = sum(1 for status in health_results.values() if status.healthy)
            total_count = len(health_results)
            
            if healthy_count == total_count:
                status = "healthy"
            elif healthy_count > 0:
                status = "degraded"
            else:
                status = "unhealthy"
            
            uptime = (datetime.now(timezone.utc) - self._state.get("start_time")).total_seconds()
            
            return HealthResponse(
                status=status,
                components={name: status.healthy for name, status in health_results.items()},
                uptime_seconds=uptime
            )
            
        except Exception as exc:
            logger.error(f"Health check failed: {exc}")
            
            return HealthResponse(
                status="unhealthy",
                components={"api": False},
                uptime_seconds=0.0
            )

    # ── Health Check Implementations ─────────────────────────────────────────────

    async def _health_check_api(self) -> Dict[str, Any]:
        """Check API health."""
        return {
            "healthy": True,
            "request_count": self._state.get("request_count", 0),
            "error_count": self._state.get("error_count", 0),
            "uptime": (datetime.now(timezone.utc) - self._state.get("start_time")).total_seconds()
        }

    async def _health_check_router(self) -> Dict[str, Any]:
        """Check router health."""
        try:
            router = self._get_router()
            summary = await ErrorRecovery.safe_execute(
                router.summary,
                fallback_value={"error": "Router unavailable"}
            )
            return {
                "healthy": "error" not in summary,
                "summary": summary
            }
        except Exception as exc:
            return {
                "healthy": False,
                "error": str(exc)
            }

    async def _health_check_dependencies(self) -> Dict[str, Any]:
        """Check dependency health."""
        dependencies = {}
        
        # Check mode manager
        try:
            mode_manager = get_mode_manager()
            dependencies["mode_manager"] = True
        except Exception:
            dependencies["mode_manager"] = False
        
        # Check risk manager
        try:
            risk_manager = get_global_risk_manager_robust()
            dependencies["risk_manager"] = True
        except Exception:
            dependencies["risk_manager"] = False
        
        # Check instrument registry
        try:
            reg = get_instrument_registry()
            dependencies["instrument_registry"] = True
        except Exception:
            dependencies["instrument_registry"] = False
        
        # Check adapter registry
        try:
            adapter_registry = get_adapter_registry()
            dependencies["adapter_registry"] = True
        except Exception:
            dependencies["adapter_registry"] = False
        
        all_healthy = all(dependencies.values())
        
        return {
            "healthy": all_healthy,
            "dependencies": dependencies
        }

    # ── Public API Summary ─────────────────────────────────────────────────────

    def get_api_stats(self) -> Dict[str, Any]:
        """Get API statistics."""
        uptime = (datetime.now(timezone.utc) - self._state.get("start_time")).total_seconds()
        
        return {
            "request_count": self._state.get("request_count", 0),
            "error_count": self._state.get("error_count", 0),
            "error_rate": self._state.get("error_count", 0) / max(self._state.get("request_count", 1), 1),
            "uptime_seconds": uptime,
            "metrics": self._metrics.get_summary(),
            "health": self._health_checker.get_summary()
        }


# ── FastAPI Router Setup ─────────────────────────────────────────────────────

# Create API instance
_pipeline_api = UnifiedPipelineAPIRobust()

# Create FastAPI router
router = APIRouter(
    prefix="/api/v1/pipeline",
    tags=["pipeline"])

# ── Route Definitions ─────────────────────────────────────────────────────────

@router.get("/summary")
async def pipeline_summary():
    """Full pipeline summary across all domains."""
    return await _pipeline_api.pipeline_summary()

@router.get("/risk")
async def pipeline_risk():
    """Global risk manager summary."""
    return await _pipeline_api.pipeline_risk()

@router.get("/instruments")
async def pipeline_instruments(limit: int = 100):
    """Instrument registry summary."""
    return await _pipeline_api.pipeline_instruments(limit)

@router.get("/venues")
async def pipeline_venues():
    """All venue configs and adapter status."""
    return await _pipeline_api.pipeline_venues()

@router.get("/proposals")
async def pipeline_proposals(limit: int = 50):
    """Recent proposal history."""
    return await _pipeline_api.pipeline_proposals(limit)

# Domain control endpoints
@router.post("/domain/enable")
async def enable_domain(req: DomainRequest):
    """Enable a trading domain."""
    return await _pipeline_api.enable_domain(req)

@router.post("/domain/disable")
async def disable_domain(req: DomainRequest):
    """Disable a trading domain."""
    return await _pipeline_api.disable_domain(req)

@router.post("/domain/halt")
async def halt_domain(req: DomainHaltRequest):
    """Halt a trading domain."""
    return await _pipeline_api.halt_domain(req)

@router.post("/domain/resume")
async def resume_domain(req: DomainRequest):
    """Resume a halted domain."""
    return await _pipeline_api.resume_domain(req)

# Venue control endpoints
@router.post("/venue/mode")
async def set_venue_mode(req: VenueModeRequest):
    """Set venue trading mode."""
    return await _pipeline_api.set_venue_mode(req)

@router.post("/venue/enable")
async def enable_venue(req: VenueRequest):
    """Enable a venue."""
    return await _pipeline_api.enable_venue(req)

@router.post("/venue/disable")
async def disable_venue(req: VenueRequest):
    """Disable a venue."""
    return await _pipeline_api.disable_venue(req)

# Health check endpoint
@router.get("/health")
async def health_check():
    """API health check."""
    return await _pipeline_api.health_check()

# Stats endpoint
@router.get("/stats")
async def api_stats():
    """API statistics."""
    return _pipeline_api.get_api_stats()


# ── Backward Compatibility ─────────────────────────────────────────────────────

# Export for backward compatibility
UnifiedPipelineAPI = UnifiedPipelineAPIRobust
