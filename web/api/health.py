"""Global health endpoints for MERID."""

from __future__ import annotations

import os
import time
from typing import Optional

import httpx
from fastapi import APIRouter, Request, HTTPException
from utils.logger import get_logger

logger = get_logger(__name__)

from agents.registry import load_agents
from core.settings import OLLAMA_BASE_URL, OLLAMA_GENERATE_ENDPOINT
from data.live_price_feed import get_live_price_feed
from monitoring.health_checker import get_health_checker

# OLLAMA test-endpoint constants — use env vars if set, else fall back to sensible defaults.
_OLLAMA_MODEL_INTERFACE = os.environ.get("OLLAMA_MODEL_INTERFACE", "llama3")
_OLLAMA_CONNECT_TIMEOUT = float(os.environ.get("OLLAMA_CONNECT_TIMEOUT", "5.0"))
_OLLAMA_READ_TIMEOUT = float(os.environ.get("OLLAMA_READ_TIMEOUT", "30.0"))
# OLLAMA_GENERATE_ENDPOINT ("/api/generate") is already the path portion; use directly.
_OLLAMA_API_PREFIX = OLLAMA_GENERATE_ENDPOINT

router = APIRouter(tags=["health"])


@router.get("/api/health")
async def get_global_health(request: Request) -> dict:
    """Live health check for MERID system.

    Checks ExecutionGuard kill switch, Kalshi circuit breaker, MeridLoop
    liveness, and HealthMonitor status.  Returns HTTP 503 when any critical
    subsystem is unhealthy so k8s probes and load balancers see real state.
    """
    from fastapi.responses import JSONResponse

    ts = int(time.time())
    checks: dict = {}
    critical_failures: list = []

    # 1. ExecutionGuard — global kill switch
    try:
        from merid.execution_guard import get_execution_guard
        guard = get_execution_guard()
        ks_active = guard.kill_switch_active
        checks["kill_switch"] = {
            "active": ks_active,
            "reason": guard._global_kill_reason if ks_active else None,
        }
        if ks_active:
            critical_failures.append("kill_switch_active")
    except Exception as _e:
        checks["kill_switch"] = {"error": str(_e)}
        critical_failures.append("kill_switch_check_failed")

    # 2. Kalshi circuit breaker
    # BUG-L13 FIX: Skip in VALIDATION_MODE to prevent blocking I/O
    _is_validation = os.environ.get("MERID_VALIDATION_MODE", "") == "1"
    if _is_validation:
        checks["kalshi_circuit"] = {"open": False, "note": "validation_mode_skipped"}
    else:
        try:
            from merid.event_venues.kalshi.client import get_kalshi_client
            kc = get_kalshi_client()
            circuit_open = getattr(kc, "is_circuit_open", False)
            checks["kalshi_circuit"] = {
                "open": circuit_open,
                "stats": kc.get_circuit_status() if hasattr(kc, "get_circuit_status") else {},
            }
            if circuit_open:
                critical_failures.append("kalshi_circuit_open")
        except Exception as _e:
            checks["kalshi_circuit"] = {"error": str(_e)}
            critical_failures.append("kalshi_circuit_check_failed")

    # 3. MeridLoop liveness
    # BUG-L13 FIX: Skip failure in VALIDATION_MODE since MeridLoop is intentionally skipped
    _is_validation = os.environ.get("MERID_VALIDATION_MODE", "") == "1"
    try:
        from merid.loop import get_merid_loop
        loop = get_merid_loop()
        loop_status = loop.status()
        running = loop_status.get("running", False)
        metrics = loop_status.get("metrics", {})
        checks["merid_loop"] = {
            "running": running,
            "total_ticks": metrics.get("total_ticks", 0),
            "tick_errors": metrics.get("tick_errors", 0),
            "last_tick_duration_ms": metrics.get("last_tick_duration_ms"),
        }
        if not running and not _is_validation:
            # Only fail if not running AND not in validation mode
            critical_failures.append("merid_loop_stopped")
    except Exception as _e:
        checks["merid_loop"] = {"error": str(_e)}
        if not _is_validation:
            critical_failures.append("merid_loop_check_failed")

    # 4. HealthMonitor (core infrastructure)
    try:
        from core.health import get_health_monitor
        hm = get_health_monitor()
        hm_status = hm.get_status() if hasattr(hm, "get_status") else {}
        checks["health_monitor"] = hm_status
    except Exception as _e:
        checks["health_monitor"] = {"error": str(_e)}

    # 5. Event-loop lag — reported in `checks` only; does not fail overall health / HTTP status
    # (aligned with execution_gate: lag is diagnostic, not a trading or probe block).
    try:
        from merid.diagnostics.loop_lag import get_loop_lag_monitor
        lag_monitor = get_loop_lag_monitor()
        lag_health = lag_monitor.get_health()
        checks["event_loop_lag"] = lag_health
    except Exception as _e:
        checks["event_loop_lag"] = {"error": str(_e)}

    # 6. AgentGrid readiness
    # BUG-L13 FIX: Report ready in VALIDATION_MODE since AgentGrid is intentionally skipped
    _is_validation = os.environ.get("MERID_VALIDATION_MODE", "") == "1"
    try:
        from merid.prediction.agent_grid import get_agent_grid
        ag = get_agent_grid()
        # In validation mode, report startup as complete even though skipped
        if _is_validation:
            checks["agent_grid"] = {
                "startup_complete": True,
                "agents_ready": True,
                "ws_ready": True,
                "running": False,
                "note": "validation_mode_skipped",
            }
        else:
            checks["agent_grid"] = {
                "startup_complete": ag._startup_complete,
                "agents_ready": ag._agents_ready,
                "ws_ready": ag._ws_ready,
                "running": ag._running,
            }
            # Add to critical failures if startup not complete (but skip in validation mode)
            if not ag._startup_complete:
                critical_failures.append("agent_grid_warming_up")
    except Exception as _e:
        checks["agent_grid"] = {"error": str(_e)}
        if not _is_validation:
            critical_failures.append("agent_grid_check_failed")

    overall = "healthy" if not critical_failures else "unhealthy"
    body = {
        "status": overall,
        "timestamp": ts,
        "critical_failures": critical_failures,
        "checks": checks,
    }
    status_code = 503 if critical_failures else 200
    return JSONResponse(content=body, status_code=status_code)


@router.get("/health/event_loop/profiles")
async def get_event_loop_profiles(request: Request) -> dict:
    """Get captured high-lag profiling data.
    
    Returns list of high-lag events with task snapshots and stack traces.
    """
    try:
        from merid.diagnostics.loop_lag import get_loop_lag_monitor
        monitor = get_loop_lag_monitor()
        profiles = monitor.get_high_lag_profiles()
        return {
            "profiles": profiles,
            "count": len(profiles),
            "timestamp": time.time(),
        }
    except Exception as e:
        logger.error(f"Failed to get high-lag profiles: {e}")
        return {"error": str(e), "profiles": []}


@router.delete("/health/event_loop/profiles")
async def clear_event_loop_profiles(request: Request) -> dict:
    """Clear captured high-lag profiling data."""
    try:
        from merid.diagnostics.loop_lag import get_loop_lag_monitor
        monitor = get_loop_lag_monitor()
        # Clear profiles by resetting the list
        monitor._high_lag_profiles.clear()
        return {
            "cleared": True,
            "timestamp": time.time(),
        }
    except Exception as e:
        logger.error(f"Failed to clear high-lag profiles: {e}")
        return {"error": str(e), "cleared": False}


@router.get("/health/event_loop/profiles/summary")
async def get_event_loop_profiles_summary(request: Request) -> dict:
    """Get summary of high-lag profiling data.
    
    Aggregates coroutines/modules by frequency to identify hot spots.
    """
    try:
        from merid.diagnostics.loop_lag import get_loop_lag_monitor
        from collections import Counter
        monitor = get_loop_lag_monitor()
        profiles = monitor.get_high_lag_profiles()
        
        if not profiles:
            return {
                "profiles_count": 0,
                "top_coroutines": [],
                "lag_range_ms": {"min": 0, "max": 0, "avg": 0},
                "timestamp": time.time(),
            }
        
        # Analyze coroutines in profiles
        coro_counter = Counter()
        lag_values = []
        
        for profile in profiles:
            lag_values.append(profile.get("lag_ms", 0))
            tasks = profile.get("tasks", [])
            for task in tasks:
                coro_str = task.get("coro", "unknown")
                # Extract module/function name from coro string
                if "<coroutine object" in coro_str:
                    # Parse "<coroutine object X at Y>" -> X
                    try:
                        coro_name = coro_str.split("<coroutine object ")[1].split(" at ")[0]
                        coro_counter[coro_name] += 1
                    except IndexError:
                        coro_counter["unknown"] += 1
                else:
                    coro_counter[coro_str[:100]] += 1
        
        # Get top offending coroutines
        top_coroutines = [
            {"coroutine": name, "count": count}
            for name, count in coro_counter.most_common(10)
        ]
        
        return {
            "profiles_count": len(profiles),
            "top_coroutines": top_coroutines,
            "lag_range_ms": {
                "min": round(min(lag_values), 1),
                "max": round(max(lag_values), 1),
                "avg": round(sum(lag_values) / len(lag_values), 1),
            },
            "timestamp": time.time(),
        }
    except Exception as e:
        logger.error(f"Failed to get profiles summary: {e}")
        return {"error": str(e)}


@router.get("/api/v1/test/ollama")
async def test_ollama_health() -> dict:
    """Test Ollama connectivity with a minimal prompt."""
    start_time = time.time()
    
    try:
        # Build Ollama URL
        ollama_url = f"{OLLAMA_BASE_URL.rstrip('/')}{_OLLAMA_API_PREFIX.rstrip('/')}"
        
        # Minimal test prompt
        payload = {
            "model": _OLLAMA_MODEL_INTERFACE,
            "prompt": "Respond with JSON: {\"status\": \"ok\"}",
            "temperature": 0.1,
            "stream": False,
        }
        
        # Configure timeouts
        timeout = httpx.Timeout(
            connect=_OLLAMA_CONNECT_TIMEOUT,
            read=_OLLAMA_READ_TIMEOUT,
            write=30.0,
            pool=60.0
        )
        
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(ollama_url, json=payload)
            response.raise_for_status()
            data = response.json()
            
        latency_ms = int((time.time() - start_time) * 1000)
        
        return {
            "status": "ok",
            "latency_ms": latency_ms,
            "model": _OLLAMA_MODEL_INTERFACE,
            "response": data.get("response", "")[:100],  # Truncate for brevity
            "error": None
        }
        
    except httpx.ReadTimeout:
        return {
            "status": "error",
            "latency_ms": int((time.time() - start_time) * 1000),
            "model": _OLLAMA_MODEL_INTERFACE,
            "response": None,
            "error": f"Read timeout after {_OLLAMA_READ_TIMEOUT}s"
        }
        
    except httpx.ConnectTimeout:
        return {
            "status": "error", 
            "latency_ms": int((time.time() - start_time) * 1000),
            "model": _OLLAMA_MODEL_INTERFACE,
            "response": None,
            "error": f"Connection timeout after {_OLLAMA_CONNECT_TIMEOUT}s"
        }
        
    except httpx.HTTPStatusError as exc:
        return {
            "status": "error",
            "latency_ms": int((time.time() - start_time) * 1000),
            "model": _OLLAMA_MODEL_INTERFACE,
            "response": None,
            "error": f"HTTP {exc.response.status_code}: {exc.response.text[:200]}"
        }
        
    except Exception as exc:
        return {
            "status": "error",
            "latency_ms": int((time.time() - start_time) * 1000),
            "model": _OLLAMA_MODEL_INTERFACE,
            "response": None,
            "error": f"Unexpected error: {str(exc)[:200]}"
        }


@router.get("/api/v1/agents/{agent_id}/selftest")
async def test_agent_selftest(agent_id: str) -> dict:
    """Test a specific agent's LLM connectivity with a minimal prompt."""
    start_time = time.time()
    
    try:
        # Load agents and find the requested one
        agents = load_agents()
        target_agent = None
        
        for agent in agents:
            if agent.agent_id == agent_id:
                target_agent = agent
                break
        
        if not target_agent:
            return {
                "status": "error",
                "latency_ms": int((time.time() - start_time) * 1000),
                "agent_id": agent_id,
                "model": None,
                "response": None,
                "error": f"Agent '{agent_id}' not found. Available agents: {[a.agent_id for a in agents]}"
            }
        
        # Create minimal test energy
        test_energy = {
            "energy_id": f"selftest-{int(time.time())}",
            "source": "health_check",
            "payload": "Self-test health check"
        }
        
        # Run the agent with minimal processing
        result = await target_agent.process(test_energy, phase="reasoning")
        
        latency_ms = int((time.time() - start_time) * 1000)
        
        return {
            "status": "ok",
            "latency_ms": latency_ms,
            "agent_id": agent_id,
            "model": target_agent.model_name,
            "response": result.get("reasoning", "")[:100],  # Truncate for brevity
            "vote": result.get("vote"),
            "confidence": result.get("confidence"),
            "error": None
        }
        
    except Exception as exc:
        return {
            "status": "error",
            "latency_ms": int((time.time() - start_time) * 1000),
            "agent_id": agent_id,
            "model": None,
            "response": None,
            "error": f"Unexpected error: {str(exc)[:200]}"
        }
