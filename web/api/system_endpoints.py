"""System and dashboard endpoints for MERID UI."""

import logging
import time
from typing import Dict, Any, List
from fastapi import APIRouter, HTTPException
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

router = APIRouter()

# Track server start time for uptime calculation
_server_start_time = time.time()


# ── Real data helpers ─────────────────────────────────────────────────
# Each helper tries to pull from the live subsystem and falls back to
# safe zero-state values so the UI never sees random noise.

def _real_system_metrics() -> Dict[str, Any]:
    """CPU / memory from psutil if available, else safe defaults."""
    try:
        import psutil
        return {
            "cpu_usage": round(psutil.cpu_percent(interval=0), 1),
            "memory_usage": round(psutil.virtual_memory().percent, 1),
            "active_connections": 0,
        }
    except Exception:
        return {"cpu_usage": 0.0, "memory_usage": 0.0, "active_connections": 0}


def _get_paper_engine():
    try:
        from trading.paper_trading import get_paper_engine
        return get_paper_engine()
    except Exception:
        return None


def _get_kalshi_risk():
    """Get KalshiRiskManager for live PnL data."""
    try:
        from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk
        return get_kalshi_risk()
    except Exception:
        return None


def _get_kalshi_grid():
    """Get AgentGrid for live trading summary."""
    try:
        from merid.prediction.agent_grid import get_agent_grid
        return get_agent_grid()
    except Exception:
        return None


def _kalshi_pnl() -> Dict[str, Any]:
    """P&L from Kalshi live risk manager."""
    risk = _get_kalshi_risk()
    if risk is None:
        return _zero_pnl()
    try:
        state = risk.state
        daily_pnl = state.daily_pnl_usd
        equity = state.current_equity_usd or state.peak_equity_usd or 10000.0
        peak = state.peak_equity_usd or equity
        drawdown = (peak - equity) / peak if peak > 0 else 0.0

        return {
            "today_pnl": round(daily_pnl, 2),
            "today_pnl_pct": round(daily_pnl / equity * 100, 2) if equity else 0.0,
            "mtm_pnl": round(daily_pnl, 2),
            "max_drawdown": round(peak - equity, 2),
            "max_drawdown_pct": round(drawdown * 100, 2),
            "limit_daily_loss": risk.config.max_daily_loss_usd,
            "limit_utilization_pct": round(abs(daily_pnl) / risk.config.max_daily_loss_usd * 100, 1) if risk.config.max_daily_loss_usd else 0.0,
            "total_pnl": round(daily_pnl, 2),
            "daily_pnl": round(daily_pnl, 2),
            "weekly_pnl": round(daily_pnl, 2),  # Will be enhanced with history
            "monthly_pnl": round(daily_pnl, 2),
            "unrealized_pnl": 0.0,  # Kalshi has no unrealized
            "realized_pnl": round(daily_pnl, 2),
            "win_rate": 0.0,  # From performance tracker
            "profit_factor": 0.0,
            "sharpe_ratio": 0.0,
        }
    except Exception:
        return _zero_pnl()


def _get_daily_loss_limit() -> float:
    """Return the configured daily loss limit from KalshiRiskConfig or risk_controller."""
    try:
        from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk
        return float(get_kalshi_risk().config.max_daily_loss_usd)
    except Exception as _e:
        logger.debug("_get_daily_loss_limit kalshi_risk skipped: %s", _e)
    try:
        from merid.risk.kill_switches import risk_controller
        return float(risk_controller.daily_loss_limit)
    except Exception:
        return 1000.0  # conservative safe default


def _real_pnl() -> Dict[str, Any]:
    """P&L from appropriate source based on trading mode."""
    # In Kalshi mode, use Kalshi risk manager
    from merid.settings import settings
    if settings.KALSHI_ONLY:
        return _kalshi_pnl()

    # Fallback to paper engine for non-Kalshi modes
    engine = _get_paper_engine()
    if engine is None:
        return _zero_pnl()
    try:
        port = engine.get_portfolio_summary("default")
        total_pnl = port.get("total_pnl", 0.0)
        equity = port.get("equity", 10000)
        pct = round(total_pnl / equity * 100, 2) if equity else 0.0
        return {
            "today_pnl": round(total_pnl, 2),
            "today_pnl_pct": pct,
            "mtm_pnl": round(port.get("unrealized_pnl", 0.0), 2),
            "max_drawdown": round(port.get("max_drawdown", 0.0), 2),
            "max_drawdown_pct": round(port.get("max_drawdown_pct", 0.0), 2),
            "limit_daily_loss": _get_daily_loss_limit(),
            "limit_utilization_pct": round(abs(total_pnl) / max(_get_daily_loss_limit(), 1) * 100, 1),
            "total_pnl": round(total_pnl, 2),
            "daily_pnl": round(total_pnl, 2),
            "weekly_pnl": round(total_pnl, 2),
            "monthly_pnl": round(total_pnl, 2),
            "unrealized_pnl": round(port.get("unrealized_pnl", 0.0), 2),
            "realized_pnl": round(port.get("realized_pnl", 0.0), 2),
            "win_rate": round(port.get("win_rate", 0.0), 1),
            "profit_factor": round(port.get("profit_factor", 0.0), 2),
            "sharpe_ratio": round(port.get("sharpe_ratio", 0.0), 2),
        }
    except Exception:
        return _zero_pnl()


def _zero_pnl() -> Dict[str, Any]:
    return {k: 0.0 for k in [
        "today_pnl", "today_pnl_pct", "mtm_pnl", "max_drawdown",
        "max_drawdown_pct", "limit_daily_loss", "limit_utilization_pct",
        "total_pnl", "daily_pnl", "weekly_pnl", "monthly_pnl",
        "unrealized_pnl", "realized_pnl", "win_rate", "profit_factor",
        "sharpe_ratio",
    ]}


def _real_trading_summary() -> Dict[str, Any]:
    """Trading summary from appropriate source based on trading mode."""
    from merid.settings import settings

    # In Kalshi mode, use Kalshi grid data
    if settings.KALSHI_ONLY:
        grid = _get_kalshi_grid()
        agent_count = len(grid.agents) if grid else 0
        summary = grid.summary() if grid else {}
        portfolio = summary.get("portfolio_risk", {})
        metrics = summary.get("metrics", {})

        return {
            "active_strategies": agent_count,
            "paused_strategies": 0,
            "venues_connected": 1,
            "venues": ["Kalshi"],
            "notional_deployed": round(portfolio.get("total_notional_usd", 0), 2),
            "notional_capacity": settings.MERID_MAX_POSITION_SIZE_USD * 10,
            "utilization_pct": round(portfolio.get("total_notional_usd", 0) / (settings.MERID_MAX_POSITION_SIZE_USD * 10) * 100, 1),
            "active_orders": metrics.get("total_orders", 0),
            "pending_orders": 0,
            "filled_orders_today": metrics.get("total_fills", 0),
            "total_volume_24h": 0.0,
            "average_trade_size": 0.0,
            "active_positions": len(portfolio.get("category_notional", {})),
            "total_positions_value": round(portfolio.get("total_notional_usd", 0), 2),
            "margin_used": 0.0,
            "margin_available": round(settings.MERID_MAX_POSITION_SIZE_USD * 10 - portfolio.get("total_notional_usd", 0), 2),
            "leverage": 1.0,
            "mode": settings.MERID_PM_TRADING_MODE,
        }

    # Fallback to paper engine for non-Kalshi modes
    engine = _get_paper_engine()
    positions = 0
    orders = 0
    total_value = 0.0
    if engine:
        try:
            port = engine.get_portfolio_summary("default")
            positions = port.get("open_positions", 0)
            total_value = port.get("equity", 0.0)
            orders = port.get("open_orders", 0)
        except Exception as exc:
            logger.debug(f"Portfolio summary error (ignored): {exc}")

    try:
        from trading.config.runtime import get_trading_runtime_config
        cfg = get_trading_runtime_config()
        state = cfg.get_state()
        mode = state.mode.value
    except Exception:
        mode = "offline"

    _capacity = float(os.getenv("MERID_NOTIONAL_CAPACITY_USD", "500000"))
    return {
        "active_strategies": 0,
        "paused_strategies": 0,
        "venues_connected": 1,
        "venues": ["Paper"],
        "notional_deployed": round(total_value, 2),
        "notional_capacity": _capacity,
        "utilization_pct": round(total_value / _capacity * 100, 1) if total_value else 0.0,
        "active_orders": orders,
        "pending_orders": 0,
        "filled_orders_today": 0,
        "total_volume_24h": 0.0,
        "average_trade_size": 0.0,
        "active_positions": positions,
        "total_positions_value": round(total_value, 2),
        "margin_used": 0.0,
        "margin_available": round(total_value, 2),
        "leverage": 1.0,
        "mode": mode,
    }


def _real_prime_status() -> Dict[str, Any]:
    """Prime screen status from live price feed state."""
    try:
        from data.live_price_feed import get_live_price_feed
        feed = get_live_price_feed()
        if feed:
            if hasattr(feed, 'get_cached_symbols'):
                cached = len(feed.get_cached_symbols())
            elif hasattr(feed, 'cached_symbols'):
                cached = len(feed.cached_symbols)
            else:
                cached = len(feed._price_cache) if hasattr(feed, '_price_cache') else 0
        else:
            cached = 0
        running = getattr(feed, "running", False) if feed else False
    except Exception:
        cached = 0
        running = False

    try:
        from trading.config.runtime import get_trading_runtime_config
        mode = get_trading_runtime_config().get_state().mode.value
    except Exception:
        mode = "offline"

    return {
        "status": "active" if running else "inactive",
        "mode": mode,
        "market_data_connected": running,
        "narrative_available": True,
        "last_narrative_timestamp": int(time.time()),
        "data_feeds": {
            "kraken": {"connected": running, "latency_ms": 0},
            "coinbase": {"connected": running, "latency_ms": 0},
            "alpaca": {"connected": running, "latency_ms": 0},
            "news": {"connected": running, "latency_ms": 0},
        },
        "confidence": 0.0,
        "active_strategies": 0,
        "signals_generated": 0,
        "execution_rate": 0.0,
        "performance_score": 0.0,
        "symbols_cached": cached,
        "last_update": int(time.time() * 1000),
        "next_rebalance": int((time.time() + 3600) * 1000),
    }


def _real_agents_summary() -> Dict[str, Any]:
    """Agent summary from orchestrator agents dict."""
    try:
        from core.agent_orchestrator import get_agent_orchestrator
        orch = get_agent_orchestrator()
        agents_dict = orch.agents
        agents_list = []
        active = 0
        paused = 0
        for role_enum, agent_obj in agents_dict.items():
            enabled = getattr(agent_obj, "enabled", True)
            status = "active" if enabled else "paused"
            if enabled:
                active += 1
            else:
                paused += 1
            agents_list.append({
                "id": role_enum.name.lower(),
                "name": role_enum.name.replace("_", " ").title(),
                "status": status,
                "heartbeat_age_ms": 0,
                "strategy": "default",
                "state": "running" if enabled else "paused",
                "positions_count": 0,
                "today_pnl": 0,
                "tasks_completed": 0,
                "uptime": 100.0 if enabled else 0.0,
            })
        total = len(agents_list)
        return {
            "total_agents": total,
            "active_agents": active,
            "idle_agents": total - active,
            "tasks_completed": 0,
            "tasks_pending": 0,
            "average_response_time": 0,
            "success_rate": 100.0,
            "agents": agents_list,
            "summary": {"total": total, "healthy": active, "paused": paused, "unhealthy": 0},
        }
    except Exception:
        return {
            "total_agents": 0, "active_agents": 0, "idle_agents": 0,
            "tasks_completed": 0, "tasks_pending": 0, "average_response_time": 0,
            "success_rate": 0.0, "agents": [],
            "summary": {"total": 0, "healthy": 0, "paused": 0, "unhealthy": 0},
        }


def _real_risk_protections() -> Dict[str, Any]:
    """Risk protections from runtime config."""
    now = datetime.now(timezone.utc).isoformat() + "Z"
    pnl = _real_pnl()
    daily_pnl = pnl.get("today_pnl", 0.0)
    max_daily_loss = _get_daily_loss_limit()

    try:
        from trading.config.runtime import get_trading_runtime_config
        cfg = get_trading_runtime_config()
        state = cfg.get_state()
        mode = state.mode.value
        spectator = state.spectator_mode
    except Exception:
        mode = "offline"
        spectator = True

    # Real circuit breaker state from risk_controller
    cb_state = "CLOSED"
    cb_color = "green"
    cb_error_count = 0
    cb_opened_at = None
    _rc_st: Dict[str, Any] = {}
    try:
        from merid.risk.kill_switches import risk_controller as _rc
        _rc_st = _rc.get_status()
        if not _rc_st.get("can_trade", True):
            cb_state = "OPEN"
            cb_color = "red"
            cb_opened_at = _rc_st.get("kill_timestamp")
        cb_error_count = _rc_st.get("error_count", 0)
    except Exception as _e:
        logger.debug("circuit_breaker risk_controller status skipped: %s", _e)

    # Real per-symbol cap and order limits from KalshiRiskConfig
    max_per_symbol = 5000.0
    max_open_orders = 30
    current_open_orders = 0
    try:
        from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk as _gkr
        _krm = _gkr()
        max_per_symbol = float(_krm.config.max_single_order_notional_usd)
        max_open_orders = int(_krm.config.max_orders_per_minute)
        current_open_orders = int(_krm.state.orders_this_minute)
    except Exception as _e:
        logger.debug("kalshi_risk order limits skipped: %s", _e)

    return {
        "timestamp": now,
        "circuit_breaker": {
            "state": cb_state,
            "state_color": cb_color,
            "error_count": cb_error_count,
            "window_seconds": int(os.getenv("MERID_CB_WINDOW_SECONDS", "300")),
            "threshold": _rc_st.get("error_threshold", int(os.getenv("MERID_CB_THRESHOLD", "5"))),
            "last_error_at": None,
            "opened_at": cb_opened_at,
            "cooldown_seconds": int(os.getenv("MERID_CB_COOLDOWN_SECONDS", "60")),
            "half_open_successes": 0,
        },
        "lockdown": {
            "trading_suite_enabled": cb_state == "CLOSED",
            "global_mode": mode,
            "spectator_mode": spectator,
            "lockdown_reason": None if cb_state == "CLOSED" else "Kill switch active",
        },
        "risk_limits": {
            "max_daily_loss_usd": max_daily_loss,
            "current_daily_pnl": daily_pnl,
            "daily_loss_utilization_pct": round(abs(daily_pnl) / max(max_daily_loss, 1) * 100, 1),
            "max_per_symbol_exposure_usd": max_per_symbol,
            "max_open_orders": max_open_orders,
            "current_open_orders": current_open_orders,
        },
        "recent_events": [],
    }


def _real_risk_exposure() -> Dict[str, Any]:
    """Risk exposure from appropriate source based on trading mode."""
    from merid.settings import settings

    # In Kalshi mode, use Kalshi risk manager
    if settings.KALSHI_ONLY:
        risk = _get_kalshi_risk()
        if risk:
            try:
                state = risk.state
                summary = risk.summary()
                category_exp = []
                for cat, notional in state.category_notional.items():
                    category_exp.append({
                        "symbol": cat,
                        "exposure": round(notional, 2),
                        "pct_of_equity": round(notional / max(state.current_equity_usd, 1) * 100, 2),
                    })
                total_exp = state.total_notional_usd
                equity = max(state.current_equity_usd, 10000.0)

                return {
                    "total_exposure": round(total_exp, 2),
                    "total_exposure_pct": round(total_exp / equity * 100, 2),
                    "buying_power": round(equity - total_exp, 2),
                    "open_orders_count": state.orders_this_hour,
                    "by_symbol": category_exp,
                    "long_exposure": round(total_exp, 2),
                    "short_exposure": 0.0,
                    "net_exposure": round(total_exp, 2),
                    "gross_exposure": round(total_exp, 2),
                    "leverage": 1.0,
                    "var_95": 0.0,
                    "var_99": 0.0,
                    "expected_shortfall": 0.0,
                    "beta": 1.0,
                    "correlation_to_market": 0.0,
                    "sector_exposure": {cat: 100.0 for cat in state.category_notional.keys()} or {"prediction_markets": 100.0},
                }
            except Exception as _e:
                logger.debug("kalshi position exposure build skipped: %s", _e)

    # Fallback to paper engine for non-Kalshi modes
    engine = _get_paper_engine()
    equity = 10000.0
    positions_by_sym: List[Dict[str, Any]] = []
    total_exp = 0.0

    if engine:
        try:
            port = engine.get_portfolio_summary("default")
            equity = port.get("equity", 10000.0)
            for pos in port.get("positions", []):
                sym = pos.get("symbol", "?")
                val = abs(pos.get("market_value", 0.0))
                total_exp += val
                positions_by_sym.append({
                    "symbol": sym,
                    "exposure": round(val, 2),
                    "pct_of_equity": round(val / equity, 4) if equity else 0.0,
                })
        except Exception as exc:
            logger.debug(f"Position exposure calc error (ignored): {exc}")

    return {
        "total_exposure": round(total_exp, 2),
        "total_exposure_pct": round(total_exp / equity, 4) if equity else 0.0,
        "buying_power": round(equity - total_exp, 2),
        "open_orders_count": 0,
        "by_symbol": positions_by_sym,
        "long_exposure": round(total_exp, 2),
        "short_exposure": 0.0,
        "net_exposure": round(total_exp, 2),
        "gross_exposure": round(total_exp, 2),
        "leverage": 1.0,
        "var_95": 0.0,
        "var_99": 0.0,
        "expected_shortfall": 0.0,
        "beta": 1.0,
        "correlation_to_market": 0.0,
        "sector_exposure": {"crypto": 100.0, "equities": 0.0, "commodities": 0.0, "forex": 0.0},
    }


@router.get("/api/system/health")
async def get_system_health() -> Dict[str, Any]:
    """Get system health status — real checks per subsystem."""
    import os
    uptime_seconds = time.time() - _server_start_time
    now = time.time()

    def _svc(check_fn) -> Dict[str, Any]:
        try:
            ok = check_fn()
            return {"status": "healthy" if ok else "degraded", "last_check": now}
        except Exception as exc:
            return {"status": "unavailable", "last_check": now, "error": str(exc)}

    try:
        from web.api.dependency_health import evaluate_dependencies

        dependencies = evaluate_dependencies()
    except Exception as exc:
        dependencies = {"overall_status": "unknown", "error": str(exc), "dependencies": {}}

    services = {
        "api_gateway": {"status": "healthy", "last_check": now},
        "risk_engine": _svc(lambda: __import__(
            "merid.risk.kill_switches", fromlist=["risk_controller"]
        ).risk_controller.can_trade() is not None),
        "agent_grid": _svc(lambda: __import__(
            "merid.prediction.agent_grid", fromlist=["get_agent_grid"]
        ).get_agent_grid() is not None),
        "audit_trail": _svc(lambda: __import__(
            "core.audit_trail", fromlist=["AuditTrail"]
        ).AuditTrail().entries is not None),
        "event_bus": _svc(lambda: __import__(
        "core.event_bus", fromlist=["get_event_bus"]
        ).get_event_bus() is not None),
    }
    all_ok = all(s["status"] == "healthy" for s in services.values())
    deps_ok = dependencies.get("overall_status") in ("healthy", "disabled")
    return {
        "status": "healthy" if all_ok and deps_ok else "degraded",
        "uptime_seconds": int(uptime_seconds),
        "uptime_hours": round(uptime_seconds / 3600, 2),
        "timestamp": now,
        "environment": os.getenv("MERID_ENV", "development"),
        "incident_flag": not (all_ok and deps_ok),
        "services": services,
        "dependencies": dependencies,
        "metrics": _real_system_metrics(),
    }


@router.get("/api/risk/pnl-summary")
async def get_pnl_summary() -> Dict[str, Any]:
    """Get P&L summary from paper trading engine."""
    pnl = _real_pnl()
    return {**pnl, "timestamp": int(time.time() * 1000)}


@router.get("/api/trading/summary")
async def get_trading_summary() -> Dict[str, Any]:
    """Get trading operations summary from paper engine."""
    ts = _real_trading_summary()
    return {**ts, "timestamp": int(time.time() * 1000)}


@router.get("/api/prime/status")
async def get_prime_status() -> Dict[str, Any]:
    """Get Prime Screen status from live feed state."""
    ps = _real_prime_status()
    return {**ps, "timestamp": int(time.time() * 1000)}


@router.get("/api/agents/summary")
async def get_agents_summary() -> Dict[str, Any]:
    """Get agents summary from orchestrator."""
    s = _real_agents_summary()
    return {**s, "timestamp": int(time.time() * 1000)}


@router.get("/api/risk/protections")
async def get_risk_protections() -> Dict[str, Any]:
    """Get risk protection settings and status from runtime config."""
    return _real_risk_protections()


@router.get("/api/risk/exposure")
async def get_risk_exposure() -> Dict[str, Any]:
    """Get current risk exposure from paper engine."""
    exp = _real_risk_exposure()
    return {**exp, "timestamp": int(time.time() * 1000)}


@router.get("/api/v1/system/health")
async def get_system_health_v1() -> Dict[str, Any]:
    """System health check — real status from grid and risk controller."""
    services: Dict[str, str] = {"api": "running"}
    try:
        from merid.prediction.agent_grid import get_agent_grid
        grid = get_agent_grid()
        services["prediction_markets"] = "running" if grid.is_running else "stopped"
    except Exception:
        services["prediction_markets"] = "unavailable"
    try:
        from merid.prediction.paper_session import get_paper_session
        sess = get_paper_session()
        services["paper_trading"] = "active" if sess.is_active else "idle"
    except Exception:
        services["paper_trading"] = "unavailable"
    try:
        from merid.risk.kill_switches import risk_controller
        services["risk"] = "halted" if not risk_controller.can_trade() else "running"
    except Exception:
        services["risk"] = "unavailable"
    all_ok = all(v in ("running", "active", "idle") for v in services.values())
    try:
        from web.api.dependency_health import evaluate_dependencies

        dependencies = evaluate_dependencies()
    except Exception as exc:
        dependencies = {"overall_status": "unknown", "error": str(exc), "dependencies": {}}
    _ver = os.getenv("MERID_VERSION", "")
    if not _ver:
        try:
            from importlib.metadata import version as _pkg_ver
            _ver = _pkg_ver("merid")
        except Exception:
            _ver = "dev"
    return {
        "status": "healthy" if all_ok and dependencies.get("overall_status") in ("healthy", "disabled") else "degraded",
        "timestamp": time.time(),
        "version": _ver,
        "services": services,
        "dependencies": dependencies,
    }


@router.get("/api/system/version")
async def get_system_version() -> Dict[str, Any]:
    """System version and build info from env and package metadata."""
    import os
    version = os.getenv("MERID_VERSION", "")
    if not version:
        try:
            from importlib.metadata import version as pkg_version
            version = pkg_version("merid")
        except Exception:
            version = "dev"
    build = os.getenv("MERID_BUILD_DATE", os.getenv("BUILD_DATE", ""))
    return {
        "version": version,
        "build": build or "unknown",
        "git_sha": os.getenv("GIT_SHA", os.getenv("COMMIT_SHA", "unknown")),
        "environment": os.getenv("MERID_ENV", "development"),
        "openapi_url": "/openapi.json",
    }


@router.get("/api/system/components")
async def get_system_components() -> Dict[str, Any]:
    """Real system component statuses — checks each subsystem."""
    def _check(name: str, fn) -> Dict[str, Any]:
        try:
            status = fn()
            return {"name": name, "status": "operational" if status else "degraded"}
        except Exception as exc:
            return {"name": name, "status": "unavailable", "error": str(exc)}

    components = [
        _check("API Gateway", lambda: True),
        _check("Risk Engine", lambda: __import__(
            "merid.risk.kill_switches", fromlist=["risk_controller"]
        ).risk_controller.can_trade() is not None),
        _check("Agent Manager", lambda: __import__(
            "merid.prediction.agent_grid", fromlist=["get_agent_grid"]
        ).get_agent_grid() is not None),
        _check("Paper Session", lambda: __import__(
            "merid.prediction.paper_session", fromlist=["get_paper_session"]
        ).get_paper_session() is not None),
        _check("Market Catalog", lambda: __import__(
            "merid.event_venues.kalshi.market_catalog", fromlist=["get_market_catalog"]
        ).get_market_catalog() is not None),
    ]
    return {"components": components}


@router.get("/api/risk/limits")
async def get_risk_limits() -> Dict[str, Any]:
    """Risk limits from live KalshiRiskConfig and global risk_controller."""
    try:
        from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk
        krm = get_kalshi_risk()
        cfg = krm.config
        return {
            "max_daily_loss": float(cfg.max_daily_loss_usd),
            "max_position_pct": float(cfg.max_total_notional_usd),
            "max_leverage": 1.0,
            "max_orders_per_minute": int(cfg.max_orders_per_minute),
            "max_notional_per_trade": float(cfg.max_single_order_notional_usd),
            "max_contracts_per_order": int(cfg.max_single_order_contracts),
            "drawdown_halt_pct": float(cfg.drawdown_halt_pct),
        }
    except Exception as exc:
        logger.debug(f"Risk limits from config unavailable: {exc}")
        try:
            from merid.risk.kill_switches import risk_controller
            return {
                "max_daily_loss": float(risk_controller.daily_loss_limit),
                "max_leverage": 1.0,
            }
        except Exception:
            return {"error": "Risk config unavailable"}


@router.post("/api/risk/circuit-breaker/reset")
async def reset_circuit_breaker() -> Dict[str, Any]:
    """Reset the circuit breaker — delegates to risk_controller.reset()."""
    try:
        from merid.risk.kill_switches import risk_controller
        risk_controller.reset()
        return {
            "success": True,
            "state": "CLOSED",
            "can_trade": risk_controller.can_trade(),
            "message": "Kill switch reset — trading re-enabled",
            "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
        }
    except Exception as exc:
        logger.error(f"Circuit breaker reset failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/api/risk/kill-switch/{action}")
async def toggle_kill_switch(action: str) -> Dict[str, Any]:
    """Enable or disable the trading kill switch via risk_controller."""
    if action not in ("enable", "disable"):
        raise HTTPException(status_code=400, detail="Action must be 'enable' or 'disable'")
    try:
        from merid.risk.kill_switches import risk_controller
        if action == "enable":
            risk_controller.emergency_stop("operator via kill-switch API")
        else:
            risk_controller.reset()
        can_trade = risk_controller.can_trade()
        return {
            "success": True,
            "kill_switch_enabled": action == "enable",
            "can_trade": can_trade,
            "message": f"Kill switch {'activated' if action == 'enable' else 'reset'}",
            "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
        }
    except Exception as exc:
        logger.error(f"Kill switch toggle failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


# ── Reconciliation & Audit Trail ──────────────────────────────────────

@router.get("/api/v1/reconciliation/run")
async def run_reconciliation_endpoint() -> Dict[str, Any]:
    """Run an on-demand reconciliation check and return the report."""
    try:
        from trading.reconciliation import run_reconciliation, store_report
        report = run_reconciliation()
        store_report(report)
        return report.to_dict()
    except Exception as exc:
        logger.debug("Reconciliation failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/api/v1/reconciliation/status")
async def reconciliation_status() -> Dict[str, Any]:
    """Return the most recent periodic reconciliation report."""
    try:
        from trading.reconciliation import get_last_report
        report = get_last_report()
        if report is None:
            return {"status": "no_report", "message": "No reconciliation has run yet"}
        return report.to_dict()
    except Exception as exc:
        logger.debug("Reconciliation status failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/api/v1/reconciliation/unified-status")
async def unified_reconciliation_status() -> Dict[str, Any]:
    """Unified reconciliation status merging trading/ and merid/ modules."""
    result: Dict[str, Any] = {"timestamp": time.time()}

    # trading.reconciliation (paper-truth checks)
    try:
        from trading.reconciliation import get_last_report
        report = get_last_report()
        if report is None:
            result["paper_truth"] = {"status": "never_run"}
        else:
            result["paper_truth"] = {
                "status": "ok" if report.all_ok else "degraded",
                "checks": len(report.checks),
                "ok": sum(1 for c in report.checks if c.status.value == "ok"),
                "delta": sum(1 for c in report.checks if c.status.value == "delta"),
                "error": sum(1 for c in report.checks if c.status.value == "error"),
                "snapshot_hash": report.snapshot_hash[:12],
                "checked_at": report.timestamp,
            }
    except Exception as exc:
        result["paper_truth"] = {"status": "unavailable", "error": str(exc)}

    # merid.reconciliation (venue-vs-internal checks)
    try:
        from merid.reconciliation import get_last_discrepancies, has_critical_discrepancies
        discs = get_last_discrepancies()
        has_crit = has_critical_discrepancies()
        n_crit = sum(1 for d in discs if d.severity == "critical")
        n_warn = sum(1 for d in discs if d.severity == "warning")
        result["venue_match"] = {
            "status": "blocked" if has_crit else ("warning" if n_warn > 0 else "ok"),
            "discrepancies": len(discs),
            "critical": n_crit,
            "warning": n_warn,
            "execution_gate": "BLOCKED" if has_crit else "CLEAR",
        }
    except Exception as exc:
        result["venue_match"] = {"status": "unavailable", "error": str(exc)}

    # Overall status
    pt = result.get("paper_truth", {}).get("status", "unavailable")
    vm = result.get("venue_match", {}).get("status", "unavailable")
    if pt == "ok" and vm == "ok":
        result["overall"] = "ok"
    elif "blocked" in (pt, vm) or "error" in (pt, vm):
        result["overall"] = "critical"
    elif "degraded" in (pt, vm) or "warning" in (pt, vm):
        result["overall"] = "degraded"
    else:
        result["overall"] = "unknown"

    return result


@router.get("/api/v1/audit-trail/summary")
async def audit_trail_summary() -> Dict[str, Any]:
    """Return a summary of the trade audit trail."""
    try:
        from trading.audit_trail import get_audit_summary
        return get_audit_summary()
    except Exception as exc:
        logger.debug("Audit trail summary failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/api/v1/audit-trail/entries")
async def audit_trail_entries(
    limit: int = 100,
    event_type: str = "",
    agent_id: str = "",
) -> Dict[str, Any]:
    """Return recent audit trail entries with optional filters."""
    try:
        from trading.audit_trail import load_entries
        entries = load_entries(
            limit=limit,
            event_type=event_type or None,
            agent_id=agent_id or None,
        )
        return {
            "entries": [e.to_dict() for e in entries],
            "count": len(entries),
        }
    except Exception as exc:
        logger.debug("Audit trail entries failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/api/v1/trade-mode")
async def get_trade_mode_endpoint() -> Dict[str, Any]:
    """Return the current canonical trade mode."""
    try:
        from trading.trade_mode import get_trade_mode
        mode = get_trade_mode()
        return {"mode": mode.value, "is_live": mode.value == "live"}
    except Exception as exc:
        logger.debug("Trade mode query failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/api/v1/system/fresh-start")
async def get_fresh_start_status() -> Dict[str, Any]:
    """Return whether this session was booted in fresh-start mode."""
    from core.fresh_start import is_fresh_start
    return {"fresh_start": is_fresh_start()}


@router.get("/api/v1/system/pnl-consistency")
async def get_pnl_consistency() -> Dict[str, Any]:
    """Compare PnL from multiple sources and flag disagreements.

    Sources: paper engine, risk controller daily PnL, equity series buffer.
    Returns each source's value and whether they agree within a threshold.
    """
    sources: Dict[str, Any] = {}
    threshold = 1.0  # $1 tolerance

    # Paper engine PnL
    try:
        from trading.paper_trading import get_paper_engine
        engine = get_paper_engine()
        total_pnl = 0.0
        unrealized = 0.0
        for _uid, portfolio in engine.portfolios.items():
            total_pnl += portfolio.total_pnl
            for _pk, pos in portfolio.positions.items():
                _calc = getattr(engine, 'calculate_position_pnl', None) or getattr(engine, '_calculate_position_pnl', None)
                unrealized += _calc(pos) if _calc else getattr(pos, 'unrealized_pnl', 0.0)
        sources["paper_engine"] = {
            "realized_pnl": round(total_pnl, 2),
            "unrealized_pnl": round(unrealized, 2),
            "total": round(total_pnl + unrealized, 2),
        }
    except Exception as exc:
        sources["paper_engine"] = {"error": str(exc)}

    # Risk controller daily PnL
    try:
        from merid.risk.kill_switches import risk_controller
        sources["risk_controller"] = {
            "daily_pnl": round(risk_controller.get_status().get("daily_pnl", 0.0), 2),
        }
    except Exception as exc:
        sources["risk_controller"] = {"error": str(exc)}

    # Equity series (latest point)
    try:
        from web.api.operator import _equity_buffer
        if _equity_buffer:
            latest = _equity_buffer[-1]
            sources["equity_series"] = {
                "equity": latest.get("equity", 0),
                "pnl": latest.get("pnl", 0),
                "ts": latest.get("ts", 0),
            }
        else:
            sources["equity_series"] = {"equity": 0, "pnl": 0, "ts": 0}
    except Exception as exc:
        sources["equity_series"] = {"error": str(exc)}

    # Check consistency
    pnl_values = []
    if "total" in sources.get("paper_engine", {}):
        pnl_values.append(("paper_engine", sources["paper_engine"]["total"]))
    if "pnl" in sources.get("equity_series", {}):
        pnl_values.append(("equity_series", sources["equity_series"]["pnl"]))

    consistent = True
    max_divergence = 0.0
    if len(pnl_values) >= 2:
        vals = [v for _, v in pnl_values]
        max_divergence = max(vals) - min(vals)
        consistent = max_divergence <= threshold

    return {
        "sources": sources,
        "consistent": consistent,
        "max_divergence_usd": round(max_divergence, 2),
        "threshold_usd": threshold,
        "timestamp": time.time(),
    }


@router.get("/api/v1/system/mode-safety")
async def get_mode_safety() -> Dict[str, Any]:
    """Unified mode & safety status for the operator dashboard.

    Aggregates trade mode, live flags, kill-switch, reconciliation,
    fresh-start, and feed health into a single response.
    """
    result: Dict[str, Any] = {"timestamp": time.time()}

    # Trade mode
    try:
        from trading.trade_mode import get_trade_mode
        mode = get_trade_mode()
        result["trade_mode"] = mode.value
        result["is_live"] = mode.value == "live"
    except Exception:
        result["trade_mode"] = "unknown"
        result["is_live"] = False

    # Live-trade env flag
    import os
    result["allow_live_trades"] = os.getenv("MERID_ALLOW_LIVE_TRADES", "").lower() in ("1", "true", "yes")

    # Fresh start
    try:
        from core.fresh_start import is_fresh_start
        result["fresh_start"] = is_fresh_start()
    except Exception:
        result["fresh_start"] = False

    # Kill switch
    try:
        from merid.risk.kill_switches import risk_controller
        _rc_st = risk_controller.get_status()
        result["kill_switch"] = {
            "active": not _rc_st.get("can_trade", True),
            "reason": _rc_st.get("kill_reason"),
            "timestamp": _rc_st.get("kill_timestamp"),
            "daily_pnl": _rc_st.get("daily_pnl", 0.0),
            "daily_loss_limit": _rc_st.get("daily_loss_limit", 500.0),
        }
    except Exception:
        result["kill_switch"] = {"active": False, "reason": None}

    # Kill switch event history
    try:
        from merid.risk.kill_switches import risk_controller as rc
        result["kill_switch_history"] = [
            {
                "old_state": str(e.old_state.value) if hasattr(e.old_state, 'value') else str(e.old_state),
                "new_state": str(e.new_state.value) if hasattr(e.new_state, 'value') else str(e.new_state),
                "reason": str(e.reason.value) if hasattr(e.reason, 'value') else str(e.reason),
                "details": e.details,
                "timestamp": e.timestamp.timestamp() if hasattr(e.timestamp, 'timestamp') else float(e.timestamp),
            }
            for e in rc.get_events(limit=20)
        ]
    except Exception:
        result["kill_switch_history"] = []

    # Reconciliation
    try:
        from trading.reconciliation import get_last_report, has_critical_discrepancies
        report = get_last_report()
        # Extract cross-source PnL delta from last reconciliation if available
        pnl_delta = None
        if report:
            for c in report.checks:
                if c.name == "cross_source/pnl_consistency" and c.delta is not None:
                    pnl_delta = c.delta
                    break
        result["reconciliation"] = {
            "has_run": report is not None,
            "all_ok": report.all_ok if report else None,
            "blocked": has_critical_discrepancies(),
            "check_count": len(report.checks) if report else 0,
            "pnl_delta": pnl_delta,
        }
    except Exception:
        result["reconciliation"] = {"has_run": False, "all_ok": None, "blocked": True, "pnl_delta": None}

    # Feed health summary
    try:
        from data.live_price_feed import get_live_feed
        feed = get_live_feed()
        if hasattr(feed, 'get_cached_symbols'):
            cached = len(feed.get_cached_symbols())
        elif hasattr(feed, 'cached_symbols'):
            cached = len(feed.cached_symbols)
        else:
            cached = len(feed._price_cache) if hasattr(feed, '_price_cache') else 0
        if hasattr(feed, 'get_all_symbols'):
            total = len(feed.get_all_symbols())
        elif hasattr(feed, 'symbols'):
            total = len(feed.symbols)
        else:
            total = len(feed._symbols) if hasattr(feed, '_symbols') else 0
        result["feed_health"] = {
            "symbols_cached": cached,
            "symbols_total": total,
            "healthy": cached > 0 and cached >= total * 0.8,
        }
    except Exception:
        result["feed_health"] = {"symbols_cached": 0, "symbols_total": 0, "healthy": False}

    return result


@router.get("/api/v1/system/execution-gate")
async def get_execution_gate() -> Dict[str, Any]:
    """Unified execution gate status.

    Returns whether trading is blocked and why, aggregating:
    kill switch, reconciliation, price feed staleness, PnL consistency.
    """
    from core.execution_gate import check_execution_gate
    return check_execution_gate().to_dict()


@router.get("/api/v1/system/price-feed-staleness")
async def get_price_feed_staleness() -> Dict[str, Any]:
    """Per-symbol price feed staleness with safe_to_trade flag."""
    from core.execution_gate import check_price_feed_staleness
    return check_price_feed_staleness()


@router.get("/api/v1/system/session-log")
async def get_session_log(
    limit: int = 50,
    category: str = None,
    since: float = None,
) -> Dict[str, Any]:
    """Session event log — time-ordered list of safety-relevant events."""
    from core.session_log import get_events, get_session_info
    events = get_events(limit=limit, category=category, since=since)
    return {
        "events": [e.to_dict() for e in events],
        "count": len(events),
        "session": get_session_info(),
    }


@router.get("/api/v1/system/symbol-status")
async def get_symbol_status_endpoint() -> Dict[str, Any]:
    """Per-symbol trading status matrix.

    Combines price feed staleness, venue health, and execution gate state
    to answer "Can we safely trade X right now?" for every tracked symbol.
    """
    from core.symbol_status import get_symbol_status
    return get_symbol_status()


@router.post("/api/v1/system/config-reload")
async def trigger_config_reload() -> Dict[str, Any]:
    """Operator-triggered hot-reload of live config without server restart.

    Re-registers RealityAuditor assertions from live subsystems (KalshiRisk,
    ExecutionGuard, paper_config, agent grid), re-bootstraps PortfolioRebalancer
    targets, and ensures the RewardEngine singleton is alive.

    Returns a summary of what was reloaded and any errors encountered.
    """
    results: Dict[str, Any] = {"reloaded": [], "errors": [], "ts": time.time()}

    # 1. RealityAuditor
    try:
        from core.reality_auditor import get_reality_auditor
        ok = get_reality_auditor().reload_from_persistent_store()
        results["reloaded"].append({"subsystem": "reality_auditor", "ok": ok})
    except Exception as exc:
        results["errors"].append({"subsystem": "reality_auditor", "error": str(exc)})
        logger.warning("config-reload: reality_auditor failed: %s", exc)

    # 2. PortfolioRebalancer
    try:
        from merid.event_venues.kalshi.rebalancer import get_portfolio_rebalancer
        rebalancer = get_portfolio_rebalancer()
        rebalancer._bootstrap_targets()
        results["reloaded"].append({"subsystem": "portfolio_rebalancer", "ok": True})
    except Exception as exc:
        results["errors"].append({"subsystem": "portfolio_rebalancer", "error": str(exc)})
        logger.warning("config-reload: portfolio_rebalancer failed: %s", exc)

    # 3. RewardEngine
    try:
        from merid.rewards.engine import get_reward_engine
        get_reward_engine()
        results["reloaded"].append({"subsystem": "reward_engine", "ok": True})
    except Exception as exc:
        results["errors"].append({"subsystem": "reward_engine", "error": str(exc)})
        logger.warning("config-reload: reward_engine failed: %s", exc)

    # 4. MeridLoop config-reload step (fires _reload_config immediately)
    try:
        from merid.loop import get_merid_loop
        loop = get_merid_loop()
        import asyncio
        summary: Dict[str, Any] = {}
        await loop._reload_config(summary)
        results["reloaded"].append({"subsystem": "merid_loop", "ok": True, "detail": summary.get("actions", [])})
    except Exception as exc:
        results["errors"].append({"subsystem": "merid_loop", "error": str(exc)})
        logger.warning("config-reload: merid_loop failed: %s", exc)

    results["success"] = len(results["errors"]) == 0
    results["reloaded_count"] = len(results["reloaded"])
    logger.info(
        "config-reload triggered: %d reloaded, %d errors",
        results["reloaded_count"], len(results["errors"]),
    )
    return results
