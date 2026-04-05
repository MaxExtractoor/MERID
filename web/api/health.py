"""Global health endpoints for MERID."""

from __future__ import annotations

import time
from typing import Optional

import httpx
from fastapi import APIRouter, Request, HTTPException
from utils.logger import get_logger

logger = get_logger(__name__)

# from agents.base_agent import AgentErrorResponse, AgentErrorType
from agents.registry import load_agents
# from core.settings import OLLAMA_BASE_URL, OLLAMA_API_PREFIX, OLLAMA_CONNECT_TIMEOUT, OLLAMA_READ_TIMEOUT, OLLAMA_MODEL_INTERFACE
from data.live_price_feed import get_live_price_feed
from monitoring.health_checker import get_health_checker

router = APIRouter(tags=["health"])


@router.get("/api/health")
async def get_global_health(request: Request) -> dict:
    """Simple health check for MERID system."""

    # Check event loop lag
    event_loop_status = "healthy"
    event_loop_degraded = False
    event_loop_metrics = {}

    try:
        from observability.event_loop_monitor import get_event_loop_monitor
        monitor = get_event_loop_monitor()
        status = monitor.get_current_status()
        event_loop_degraded = status.get("degraded", False)
        event_loop_metrics = status.get("stats_5m", {})

        # Determine health status based on P95 lag
        p95_lag = event_loop_metrics.get("p95_ms", 0.0)
        if p95_lag > 500:
            event_loop_status = "degraded"
        elif p95_lag > 200:
            event_loop_status = "warning"
        else:
            event_loop_status = "healthy"
    except Exception as exc:
        logger.debug(f"Event loop monitor check failed: {exc}")
        event_loop_status = "unknown"

    # Check settlement poller
    settlement_poller_status = "unknown"
    settlement_poller_running = False
    settlement_poller_info = {}
    try:
        from merid.event_venues.kalshi.settlement_poller import get_settlement_poller
        poller = get_settlement_poller(client=None)
        poller_status = poller.status()
        settlement_poller_running = poller_status.get("running", False)
        settlement_poller_status = "running" if settlement_poller_running else "stopped"
        settlement_poller_info = {
            "poll_count": poller_status.get("poll_count", 0),
            "settlement_count": poller_status.get("settlement_count", 0),
        }
    except Exception as exc:
        logger.debug(f"Settlement poller check failed: {exc}")
        settlement_poller_status = "not_configured"

    return {
        "status": "degraded" if event_loop_degraded else "healthy",
        "timestamp": int(time.time()),
        "degraded": event_loop_degraded,
        "checks": {
            "event_loop": {
                "status": event_loop_status,
                "degraded": event_loop_degraded,
                "p50_lag_ms": event_loop_metrics.get("p50_ms", 0.0),
                "p95_lag_ms": event_loop_metrics.get("p95_ms", 0.0),
                "p99_lag_ms": event_loop_metrics.get("p99_ms", 0.0),
                "max_lag_ms": event_loop_metrics.get("max_ms", 0.0),
                "samples_above_warn": event_loop_metrics.get("samples_above_warn", 0),
                "samples_above_crit": event_loop_metrics.get("samples_above_crit", 0),
            },
            "settlement_poller": {
                "status": settlement_poller_status,
                "running": settlement_poller_running,
                **settlement_poller_info,
            },
            "price_feed": {
                "status": "healthy",
                "last_update": int(time.time()),
                "connected_exchanges": ["kraken", "coinbase", "gemini"],
            },
            "database": {
                "connected": False,
                "error": None
            },
            "cache": {
                "connected": False,
                "error": None
            }
        }
    }


@router.get("/api/v1/test/ollama")
async def test_ollama_health() -> dict:
    """Test Ollama connectivity with a minimal prompt."""
    start_time = time.time()
    
    try:
        # Build Ollama URL
        ollama_url = f"{OLLAMA_BASE_URL.rstrip('/')}{OLLAMA_API_PREFIX.rstrip('/')}/generate"
        
        # Minimal test prompt
        payload = {
            "model": OLLAMA_MODEL_INTERFACE,
            "prompt": "Respond with JSON: {\"status\": \"ok\"}",
            "temperature": 0.1,
            "stream": False,
        }
        
        # Configure timeouts
        timeout = httpx.Timeout(
            connect=OLLAMA_CONNECT_TIMEOUT,
            read=OLLAMA_READ_TIMEOUT,
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
            "model": OLLAMA_MODEL_INTERFACE,
            "response": data.get("response", "")[:100],  # Truncate for brevity
            "error": None
        }
        
    except httpx.ReadTimeout:
        return {
            "status": "error",
            "latency_ms": int((time.time() - start_time) * 1000),
            "model": OLLAMA_MODEL_INTERFACE,
            "response": None,
            "error": f"Read timeout after {OLLAMA_READ_TIMEOUT}s"
        }
        
    except httpx.ConnectTimeout:
        return {
            "status": "error", 
            "latency_ms": int((time.time() - start_time) * 1000),
            "model": OLLAMA_MODEL_INTERFACE,
            "response": None,
            "error": f"Connection timeout after {OLLAMA_CONNECT_TIMEOUT}s"
        }
        
    except httpx.HTTPStatusError as exc:
        return {
            "status": "error",
            "latency_ms": int((time.time() - start_time) * 1000),
            "model": OLLAMA_MODEL_INTERFACE,
            "response": None,
            "error": f"HTTP {exc.response.status_code}: {exc.response.text[:200]}"
        }
        
    except Exception as exc:
        return {
            "status": "error",
            "latency_ms": int((time.time() - start_time) * 1000),
            "model": OLLAMA_MODEL_INTERFACE,
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
        
    except AgentErrorResponse as exc:
        return {
            "status": "error",
            "latency_ms": int((time.time() - start_time) * 1000),
            "agent_id": agent_id,
            "model": exc.details.get('model_name') if exc.details else None,
            "response": None,
            "error": f"Agent {exc.error_type.value}: {exc.message}"
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


@router.get("/health/cfb_rti")
async def get_cfb_rti_health() -> dict:
    """CFB RTI (CF Benchmarks Real-Time Index) feed health.

    Returns the current state of the RTI buffer used by the Kalshi live
    trading safety gate.  Useful for monitoring, alerting, and diagnosing
    "no ticks" issues before they block order submission.

    Response fields
    ---------------
    ``status``
        ``"healthy"`` — at least one non-stale tick is buffered.
        ``"no_data"`` — buffer empty or all ticks are stale.
        ``"error"``   — unable to inspect the buffer.
    ``adapter``
        ``"live"`` or ``"simulation"``.
    ``tick_count``
        Number of ticks currently held in the rolling buffer.
    ``last_tick``
        Most-recent tick details (index_name, value, age_seconds), or
        ``null`` when no ticks are present.
    ``kalshi_env``
        Current ``KALSHI_ENV`` value — gate is only enforced when
        this is ``"live"``.
    ``gate_active``
        ``true`` when ``KALSHI_ENV=live`` and ``MERID_ALLOW_NULL_CFB``
        is not set (i.e., the safety gate is in force).
    ``cfb_rti_enabled``
        ``false`` when ``MERID_CFB_RTI_ENABLED`` is not set; in that case
        ``status`` will be ``"disabled-by-config"`` and the gate is never
        enforced regardless of ``KALSHI_ENV``.
    """
    import os

    try:
        from merid.data.settlement_rti_buffer import get_rti_buffer, is_cfb_rti_enabled

        kalshi_env = os.getenv("KALSHI_ENV", "paper").lower()
        allow_null = os.getenv("MERID_ALLOW_NULL_CFB", "0") == "1"
        cfb_enabled = is_cfb_rti_enabled()

        if not cfb_enabled:
            return {
                "status": "disabled-by-config",
                "cfb_rti_enabled": False,
                "adapter": None,
                "tick_count": 0,
                "last_tick": None,
                "kalshi_env": kalshi_env,
                "gate_active": False,
                "message": (
                    "CFB RTI disabled by config (MERID_CFB_RTI_ENABLED=false). "
                    "Set MERID_CFB_RTI_ENABLED=true to enable."
                ),
                "timestamp": time.time(),
            }

        buf = get_rti_buffer()
        health = buf.health_dict()  # type: ignore[union-attr]

        gate_active = kalshi_env == "live" and not allow_null

        health["cfb_rti_enabled"] = True
        health["kalshi_env"] = kalshi_env
        health["gate_active"] = gate_active
        return health
    except Exception as exc:
        logger.error("CFB RTI health check failed: %s", exc)
        return {
            "status": "error",
            "error": str(exc),
            "timestamp": time.time(),
        }


@router.get("/health/event_loop")
async def get_event_loop_health() -> dict:
    """Event loop lag monitoring health check.

    Returns detailed metrics about event loop responsiveness, including:
    - P50/P95/P99 lag percentiles over 1-minute and 5-minute windows
    - Count of samples exceeding warning (200ms) and critical (500ms) thresholds
    - Degraded status if P95 lag consistently exceeds 500ms

    This is critical for detecting event loop starvation, tight loops without
    yields, and blocking operations on the main event loop.

    Response fields
    ---------------
    ``status``
        ``"healthy"`` — P95 lag < 200ms
        ``"warning"`` — P95 lag 200-500ms
        ``"degraded"`` — P95 lag > 500ms
        ``"unknown"`` — Monitor not running
    ``degraded``
        ``true`` when event loop is currently experiencing sustained high lag
    ``degraded_since``
        ISO timestamp when degradation started, or ``null`` if healthy
    ``stats_1m`` / ``stats_5m``
        Statistical summary over 1-minute and 5-minute windows
    ``total_profiles``
        Number of high-lag profiles captured
    """
    try:
        from observability.event_loop_monitor import get_event_loop_monitor

        monitor = get_event_loop_monitor()
        status = monitor.get_current_status()

        # Determine overall health status
        p95_lag = status.get("stats_5m", {}).get("p95_ms", 0.0)
        if p95_lag > 500:
            health_status = "degraded"
        elif p95_lag > 200:
            health_status = "warning"
        else:
            health_status = "healthy"

        return {
            "status": health_status,
            "timestamp": time.time(),
            **status,
        }
    except Exception as exc:
        logger.error(f"Event loop health check failed: {exc}")
        return {
            "status": "unknown",
            "error": str(exc),
            "timestamp": time.time(),
        }


@router.get("/health/event_loop/profiles")
async def get_event_loop_profiles(limit: Optional[int] = 10) -> dict:
    """Get captured high-lag profiles for analysis.

    Returns stack traces and task information captured during high-lag events
    (lag >= 500ms). Profiles are ordered most recent first.

    Query parameters
    ----------------
    ``limit``
        Maximum number of profiles to return (default 10, max 50)

    Response fields
    ---------------
    ``profile_count``
        Number of profiles returned
    ``total_profiles``
        Total number of profiles stored
    ``profiles``
        List of high-lag profile objects, each containing:
        - captured_at: ISO timestamp when profile was captured
        - lag_ms: Event loop lag in milliseconds
        - active_task_count: Number of active tasks at capture time
        - top_tasks: List of top offending tasks with stack traces
    """
    try:
        from observability.event_loop_monitor import get_event_loop_monitor

        monitor = get_event_loop_monitor()

        # Limit to max 50 profiles
        requested_limit = min(limit or 10, 50)

        profiles = monitor.get_profiles(max_count=requested_limit)

        return {
            "profile_count": len(profiles),
            "total_profiles": len(monitor._profiles),
            "max_profiles": monitor.max_profiles,
            "profile_threshold_ms": monitor.profile_threshold_ms,
            "timestamp": time.time(),
            "profiles": [p.to_dict() for p in profiles],
        }
    except Exception as exc:
        logger.error(f"Failed to retrieve event loop profiles: {exc}")
        return {
            "error": str(exc),
            "timestamp": time.time(),
        }


@router.delete("/health/event_loop/profiles")
async def clear_event_loop_profiles() -> dict:
    """Clear all captured high-lag profiles.

    Useful for resetting profiling state between test runs or after
    resolving identified performance issues.

    Returns
    -------
    ``cleared_count``
        Number of profiles that were cleared
    """
    try:
        from observability.event_loop_monitor import get_event_loop_monitor

        monitor = get_event_loop_monitor()
        cleared_count = monitor.clear_profiles()

        return {
            "status": "success",
            "cleared_count": cleared_count,
            "timestamp": time.time(),
        }
    except Exception as exc:
        logger.error(f"Failed to clear event loop profiles: {exc}")
        return {
            "status": "error",
            "error": str(exc),
            "timestamp": time.time(),
        }


@router.get("/health/event_loop/profiles/summary")
async def get_event_loop_profiles_summary() -> dict:
    """Get a summary analysis of captured high-lag profiles.

    Aggregates profile data to identify the most common offending subsystems
    and coroutines causing event loop lag.

    Response fields
    ---------------
    ``total_profiles``
        Total number of profiles analyzed
    ``offenders_by_coroutine``
        Dictionary mapping coroutine names to frequency counts
    ``offenders_by_module``
        Dictionary mapping module names to frequency counts
    ``max_lag_ms``
        Maximum lag observed across all profiles
    ``avg_lag_ms``
        Average lag across all profiles
    ``avg_task_count``
        Average number of active tasks during high-lag events
    """
    try:
        from observability.event_loop_monitor import get_event_loop_monitor

        monitor = get_event_loop_monitor()
        profiles = monitor.get_profiles(max_count=None)  # Get all profiles

        if not profiles:
            return {
                "total_profiles": 0,
                "offenders_by_coroutine": {},
                "offenders_by_module": {},
                "max_lag_ms": 0.0,
                "avg_lag_ms": 0.0,
                "avg_task_count": 0,
                "timestamp": time.time(),
            }

        # Aggregate statistics
        offenders_by_coroutine: dict = {}
        offenders_by_module: dict = {}
        total_lag = 0.0
        max_lag = 0.0
        total_tasks = 0

        for profile in profiles:
            total_lag += profile.lag_ms
            max_lag = max(max_lag, profile.lag_ms)
            total_tasks += profile.active_task_count

            # Count coroutines
            for task in profile.top_tasks:
                coro = task.get("coro", "unknown")
                offenders_by_coroutine[coro] = offenders_by_coroutine.get(coro, 0) + 1

                # Extract module from file path
                file_path = task.get("file", "")
                if file_path:
                    # Extract module name from path like "/path/to/merid/loop.py" -> "merid.loop"
                    if "merid" in file_path:
                        parts = file_path.split("merid")[-1].strip("/").replace("/", ".").replace(".py", "")
                        if parts:
                            module = f"merid.{parts}"
                            offenders_by_module[module] = offenders_by_module.get(module, 0) + 1

        # Sort by frequency
        sorted_coros = sorted(offenders_by_coroutine.items(), key=lambda x: x[1], reverse=True)
        sorted_modules = sorted(offenders_by_module.items(), key=lambda x: x[1], reverse=True)

        return {
            "total_profiles": len(profiles),
            "offenders_by_coroutine": dict(sorted_coros[:20]),  # Top 20
            "offenders_by_module": dict(sorted_modules[:10]),  # Top 10
            "max_lag_ms": round(max_lag, 2),
            "avg_lag_ms": round(total_lag / len(profiles), 2),
            "avg_task_count": round(total_tasks / len(profiles), 1),
            "timestamp": time.time(),
        }
    except Exception as exc:
        logger.error(f"Failed to generate profile summary: {exc}")
        return {
            "error": str(exc),
            "timestamp": time.time(),
        }


@router.get("/health/settlement_poller")
async def get_settlement_poller_health() -> dict:
    """KalshiSettlementPoller health check and status.

    Returns:
        - status: running, stopped, or not_configured
        - running: boolean indicating if the poll loop is active
        - poll_count: number of polls executed since start
        - settlement_count: number of settlements processed
        - last_cursor: most recent cursor value
        - seen_ids_count: number of settlement IDs in deduplication cache
        - cursor_history_len: number of cursor checkpoints saved
        - timestamp: current server time
    """
    try:
        from merid.event_venues.kalshi.settlement_poller import get_settlement_poller

        # Try to get the singleton poller instance
        try:
            poller = get_settlement_poller(client=None)
        except Exception as e:
            # If getting the poller fails, it's likely not configured
            return {
                "status": "not_configured",
                "error": str(e),
                "timestamp": time.time(),
            }

        # Get status from the poller
        poller_status = poller.status()

        # Determine overall health status
        is_running = poller_status.get("running", False)
        poll_count = poller_status.get("poll_count", 0)
        settlement_count = poller_status.get("settlement_count", 0)

        # Interpret status
        if is_running:
            status = "running"
            health = "healthy"
        else:
            status = "stopped"
            health = "inactive"

        return {
            "status": status,
            "health": health,
            "running": is_running,
            "poll_count": poll_count,
            "settlement_count": settlement_count,
            "last_cursor": poller_status.get("last_cursor"),
            "seen_ids_count": poller_status.get("seen_ids_count", 0),
            "cursor_history_len": poller_status.get("cursor_history_len", 0),
            "timestamp": time.time(),
        }
    except Exception as exc:
        logger.error(f"Failed to check settlement poller health: {exc}")
        return {
            "status": "error",
            "health": "unknown",
            "error": str(exc),
            "timestamp": time.time(),
        }


