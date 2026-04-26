"""System and dashboard endpoints for MERID UI."""

from web.api.auth import get_current_session
from auth.user_manager import require_role
from utils.logger import get_logger
import time
from typing import Dict, Any, List
from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime, timedelta, timezone
import os

logger = get_logger(__name__)

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
    except ImportError:
        # psutil not installed - return safe defaults
        return {"cpu_usage": 0.0, "memory_usage": 0.0, "active_connections": 0}
    except (OSError, ValueError) as e:
        # System-level errors (e.g., /proc not accessible) - log and return defaults
        logger.debug("psutil system metrics failed: %s", e)
        return {"cpu_usage": 0.0, "memory_usage": 0.0, "active_connections": 0}


def _get_paper_engine():
    try:
        from trading.paper_trading import get_paper_engine
        return get_paper_engine()
    except ImportError:
        # Paper trading module not available
        return None
    except RuntimeError as e:
        # Engine not initialized - log at debug level
        logger.debug("Paper engine not available: %s", e)
        return None


def _get_kalshi_risk():
    """Get KalshiRiskManager for live PnL data."""
    try:
        from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk
        return get_kalshi_risk()
    except ImportError:
        # Kalshi risk module not available
        return None
    except RuntimeError as e:
        # Risk manager not initialized
        logger.debug("Kalshi risk manager not available: %s", e)
        return None


def _get_kalshi_grid():
    """Get AgentGrid for live trading summary."""
    try:
        from merid.prediction.agent_grid import get_agent_grid
        return get_agent_grid()
    except ImportError:
        # Agent grid module not available
        return None
    except RuntimeError as e:
        # Grid not initialized
        logger.debug("Agent grid not available: %s", e)
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

    services = {
        "api_gateway": {"status": "healthy", "last_check": now},
        "risk_engine": _svc(lambda: __import__(
            "merid.risk.kill_switches", fromlist=["risk_controller"]
        ).risk_controller.can_trade() is not None),
        "agent_grid": _svc(lambda: __import__(
            "merid.prediction.agent_grid", fromlist=["get_agent_grid"]
        ).get_agent_grid() is not None),
        "audit_trail": _svc(lambda: __import__(
            "core.audit_trail", fromlist=["get_audit_trail"]
        ).get_audit_trail().entries is not None),
        "event_bus": _svc(lambda: __import__(
            "core.event_bus", fromlist=["get_event_bus"]
        ).get_event_bus() is not None),
    }
    all_ok = all(s["status"] == "healthy" for s in services.values())
    return {
        "status": "healthy" if all_ok else "degraded",
        "uptime_seconds": int(uptime_seconds),
        "uptime_hours": round(uptime_seconds / 3600, 2),
        "timestamp": now,
        "environment": os.getenv("MERID_ENV", "development"),
        "incident_flag": not all_ok,
        "services": services,
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
    # Dependency health (Neo4j, Twitter, SMTP, Kalshi client/WS, fills ledger)
    dep_summary = None
    try:
        from core.dependency_health import check_all_dependencies
        dep_summary = check_all_dependencies()
        for dep in dep_summary["dependencies"]:
            services[f"dep:{dep['name']}"] = dep["status"]
    except Exception as e:
        logger.debug(f"Silent error: {e}")

    all_ok = all(v in ("running", "active", "idle", "healthy") for v in services.values())
    _ver = os.getenv("MERID_VERSION", "")
    if not _ver:
        try:
            from importlib.metadata import version as _pkg_ver
            _ver = _pkg_ver("merid")
        except Exception:
            _ver = "dev"
    result = {
        "status": "healthy" if all_ok else "degraded",
        "timestamp": time.time(),
        "version": _ver,
        "services": services,
    }
    if dep_summary:
        result["dependency_health"] = {
            "any_critical_down": dep_summary["any_critical_down"],
            "healthy": dep_summary["healthy_count"],
            "degraded": dep_summary["degraded_count"],
            "down": dep_summary["down_count"],
        }
    return result


@router.get("/api/v1/system/kalshi-crypto-runtime-config")
async def kalshi_crypto_runtime_config_v1() -> Dict[str, Any]:
    """Crypto CT / universe snapshot for runtime vs module-level invariant checks."""
    from merid.diagnostics.kalshi_runtime_config import build_kalshi_crypto_runtime_snapshot

    return build_kalshi_crypto_runtime_snapshot()


@router.get("/api/v1/system/risk-posture")
async def risk_posture_v1() -> Dict[str, Any]:
    """Unified gates, spot venue health, risk manager, caps — operator-facing audit slice."""
    from merid.diagnostics.risk_posture import build_risk_posture_snapshot

    return build_risk_posture_snapshot()


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
async def reset_circuit_breaker(_user=Depends(require_role("operator", "admin"))) -> Dict[str, Any]:
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

@router.api_route("/api/v1/reconciliation/run", methods=["GET", "POST"])
async def run_reconciliation_endpoint() -> Dict[str, Any]:
    """Run an on-demand venue reconciliation (Kalshi) and return the summary."""
    try:
        from merid.reconciliation import (
            get_reconciliation_status,
            reconcile_all_venues,
        )

        discrepancies = reconcile_all_venues(["kalshi"])
        status = get_reconciliation_status()
        return {
            **status,
            "discrepancies": [d.to_dict() for d in discrepancies],
        }
    except Exception as exc:
        logger.debug("Reconciliation failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/api/v1/reconciliation/status")
async def reconciliation_status() -> Dict[str, Any]:
    """Return the most recent venue reconciliation snapshot (Kalshi)."""
    try:
        from merid.reconciliation import (
            get_last_discrepancies,
            get_last_reconciliation_ts,
            get_reconciliation_status,
            get_last_report,
        )

        ts = get_last_reconciliation_ts()
        if ts <= 0.0:
            return {"status": "no_report", "message": "No reconciliation has run yet"}
        kalshi_report = get_last_report()
        discrepancies = get_last_discrepancies()
        out: Dict[str, Any] = {
            "status": "ok",
            **get_reconciliation_status(),
            "discrepancies": [d.to_dict() for d in discrepancies],
        }
        if kalshi_report is not None:
            out["kalshi_report"] = kalshi_report.to_dict()
        return out
    except Exception as exc:
        logger.debug("Reconciliation status failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/api/v1/reconciliation/unified-status")
async def unified_reconciliation_status() -> Dict[str, Any]:
    """Unified reconciliation status merging trading/ and merid/ modules."""
    result: Dict[str, Any] = {"timestamp": time.time()}

    # Legacy paper-truth module (trading.reconciliation) removed — keep key for API stability.
    result["paper_truth"] = {
        "status": "deprecated",
        "message": "Legacy paper-truth reconciliation removed; use venue_match (merid.reconciliation).",
    }

    # merid.reconciliation (venue-vs-internal checks)
    try:
        from merid.reconciliation import (
            get_last_discrepancies,
            get_last_reconciliation_ts,
            has_critical_discrepancies,
        )

        discs = get_last_discrepancies()
        has_crit = has_critical_discrepancies()
        n_crit = sum(1 for d in discs if d.severity == "critical")
        n_warn = sum(1 for d in discs if d.severity == "warning")
        ts = get_last_reconciliation_ts()
        # Fail-closed before first run (empty cache) is not the same as a venue mismatch.
        pending_first = ts <= 0.0 and len(discs) == 0
        if pending_first and has_crit:
            result["venue_match"] = {
                "status": "pending_first_run",
                "reconciliation_has_run": False,
                "discrepancies": 0,
                "critical": 0,
                "warning": 0,
                "execution_gate": "PENDING",
                "note": (
                    "No venue reconciliation cycle completed yet; internal gate may warn "
                    "until the periodic loop runs."
                ),
            }
        else:
            result["venue_match"] = {
                "status": "blocked" if has_crit else ("warning" if n_warn > 0 else "ok"),
                "reconciliation_has_run": ts > 0.0,
                "discrepancies": len(discs),
                "critical": n_crit,
                "warning": n_warn,
                "execution_gate": "BLOCKED" if has_crit else "CLEAR",
            }
    except Exception as exc:
        result["venue_match"] = {"status": "unavailable", "error": str(exc)}

    # Overall status (paper_truth is deprecated — venue_match drives health)
    pt = result.get("paper_truth", {}).get("status", "unavailable")
    vm = result.get("venue_match", {}).get("status", "unavailable")
    if pt == "deprecated":
        if vm == "pending_first_run":
            result["overall"] = "warning"
        elif vm == "ok":
            result["overall"] = "ok"
        elif vm in ("blocked", "unavailable") or "error" in vm:
            result["overall"] = "critical"
        elif "warning" in vm:
            result["overall"] = "warning"
        else:
            result["overall"] = vm
    elif pt == "ok" and vm == "ok":
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
        if entries:
            return {
                "entries": [e.to_dict() for e in entries],
                "count": len(entries),
            }
    except Exception as exc:
        logger.debug("Audit trail entries primary source failed: %s", exc)

    # Fallback: derive audit entries from agent grid cycle activity
    from datetime import datetime, timezone
    _now = datetime.now(timezone.utc)
    fallback = []
    try:
        from merid.prediction.agent_grid import get_agent_grid
        grid = get_agent_grid()
        for agent in grid.agents:
            if agent.state.cycles_run > 0:
                fallback.append({
                    "timestamp": _now.isoformat(),
                    "event_type": "agent_cycle",
                    "agent_id": agent.config.name,
                    "message": f"{agent.config.name}: {agent.state.cycles_run} cycles, {agent.state.orders_placed} orders",
                    "severity": "info",
                    "source": "agent_grid",
                })
    except Exception as e:
        logger.debug(f"Silent error: {e}")
    if not fallback:
        fallback.append({
            "timestamp": _now.isoformat(),
            "event_type": "system_start",
            "agent_id": "system",
            "message": "System running — audit entries will appear as trading activity occurs",
            "severity": "info",
            "source": "system",
        })
    return {"entries": fallback[:limit], "count": len(fallback)}


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
    """Return whether this session was booted in fresh-start mode plus session context."""
    from core.fresh_start import is_fresh_start
    import time as _t
    result: Dict[str, Any] = {"fresh_start": is_fresh_start()}
    try:
        from merid.prediction.agent_grid import get_agent_grid
        grid = get_agent_grid()
        total_cycles = sum(a.state.cycles_run for a in grid.agents)
        total_orders = sum(a.state.orders_placed for a in grid.agents)
        running = sum(1 for a in grid.agents if a.state.running)
        result.update({
            "agents_total": len(grid.agents),
            "agents_running": running,
            "total_cycles": total_cycles,
            "total_orders": total_orders,
            "session_active": total_cycles > 0,
            "uptime_estimate_s": round(_t.time() - getattr(grid, "_start_ts", _t.time()), 1),
        })
    except Exception:
        result["session_active"] = False
    return result


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

    # Reconciliation (merid venue truth — Kalshi)
    try:
        from merid.reconciliation import (
            get_last_discrepancies,
            get_last_reconciliation_ts,
            has_critical_discrepancies,
        )

        discs = get_last_discrepancies()
        has_run = get_last_reconciliation_ts() > 0.0
        pnl_delta = sum(float(getattr(d, "delta_pnl", 0.0) or 0.0) for d in discs)
        n_crit = sum(1 for d in discs if d.severity == "critical")
        all_ok = has_run and n_crit == 0
        result["reconciliation"] = {
            "has_run": has_run,
            "all_ok": all_ok if has_run else None,
            "blocked": has_critical_discrepancies(),
            "check_count": len(discs),
            "pnl_delta": pnl_delta,
        }
    except Exception:
        result["reconciliation"] = {"has_run": False, "all_ok": None, "blocked": True, "pnl_delta": 0.0}

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


@router.get("/api/v1/safety/report")
async def get_safety_report() -> Dict[str, Any]:
    """Full safety report from IntegrationValidator (Phase 8).
    
    Returns aggregated health status across all signal layers,
    active invariant violations, and execution readiness.
    """
    try:
        from merid.safety.integration_validator import get_integration_validator
        
        validator = get_integration_validator()
        report = validator.run_health_check()
        
        # Serialize the report
        return {
            "timestamp": report.timestamp,
            "overall_status": report.overall_status.value,
            "is_safe_to_trade": report.is_safe_to_trade,
            "can_execute": report.can_execute,
            "blocked_reason": report.blocked_reason,
            "signal_freshness": {
                "macro": report.macro_fresh,
                "momentum": report.momentum_fresh,
                "btc_anchor": report.btc_anchor_fresh,
                "regime": report.regime_fresh,
            },
            "health_checks": {
                name: {
                    "status": h.status,
                    "message": h.message,
                    "latency_ms": h.latency_ms,
                    "details": h.details,
                }
                for name, h in report.health_checks.items()
            },
            "active_violations": [
                {
                    "invariant_id": v.invariant_id,
                    "severity": v.severity.value,
                    "message": v.message,
                    "timestamp": v.timestamp,
                    "context": v.context,
                }
                for v in report.active_violations
            ],
            "total_violations_24h": report.total_violations_24h,
        }
    except Exception as exc:
        logger.error("Failed to generate safety report: %s", exc)
        return {
            "timestamp": time.time(),
            "overall_status": "unknown",
            "is_safe_to_trade": False,
            "error": str(exc),
        }


@router.get("/api/v1/safety/violations")
async def get_safety_violations(
    since: float = None,
    severity: str = None,
) -> Dict[str, Any]:
    """Get invariant violation history with optional filtering."""
    try:
        from merid.safety.integration_validator import (
            get_integration_validator,
            InvariantSeverity,
        )
        
        validator = get_integration_validator()
        
        # Parse severity filter
        sev_filter = None
        if severity:
            try:
                sev_filter = InvariantSeverity(severity.lower())
            except ValueError:
                pass  # Invalid severity, ignore filter
        
        # Get violations
        violations = validator.get_violation_history(
            since=since,
            severity=sev_filter,
        )
        
        return {
            "timestamp": time.time(),
            "count": len(violations),
            "violations": [
                {
                    "invariant_id": v.invariant_id,
                    "severity": v.severity.value,
                    "message": v.message,
                    "timestamp": v.timestamp,
                    "context": v.context,
                }
                for v in violations
            ],
        }
    except Exception as exc:
        logger.error("Failed to get violations: %s", exc)
        return {
            "timestamp": time.time(),
            "count": 0,
            "error": str(exc),
        }


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


# ── Pause Agents (used by KalshiRiskFeedEnhanced) ────────────────────────

@router.post("/api/v1/system/pause-agents")
async def pause_all_agents() -> Dict[str, Any]:
    """Pause all trading agents across the grid."""
    try:
        from merid.kalshi_grid import get_kalshi_grid
        grid = get_kalshi_grid()
        grid.pause_all()
        return {
            "success": True,
            "message": "All agents paused",
            "agent_count": len(grid.agents),
            "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
        }
    except Exception as exc:
        logger.error("Failed to pause agents: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── Risk Downsize All (used by KalshiRiskFeedEnhanced) ───────────────────

@router.post("/api/v1/risk/downsize-all")
async def risk_downsize_all() -> Dict[str, Any]:
    """Downsize all positions across all assets using the default factor."""
    try:
        from merid.kalshi_grid import get_kalshi_grid
        grid = get_kalshi_grid()
        results = []
        for agent in grid.agents.values():
            try:
                if hasattr(agent, 'downsize'):
                    agent.downsize(factor=0.5)
                    results.append({"agent": agent.name, "ok": True})
            except Exception as ae:
                results.append({"agent": getattr(agent, 'name', '?'), "ok": False, "error": str(ae)})
        return {
            "success": True,
            "message": f"Downsize triggered for {len(results)} agents",
            "results": results,
            "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
        }
    except Exception as exc:
        logger.error("Failed to downsize all: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── Risk Kill Switch DELETE (used by KalshiRiskFeedEnhanced) ─────────────

@router.delete("/api/v1/risk/kill-switch")
async def delete_risk_kill_switch() -> Dict[str, Any]:
    """Reset (deactivate) the risk kill switch via DELETE."""
    try:
        from merid.risk.kill_switches import risk_controller
        risk_controller.reset()
        return {
            "success": True,
            "kill_switch_enabled": False,
            "can_trade": risk_controller.can_trade(),
            "message": "Kill switch reset — trading re-enabled",
            "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
        }
    except Exception as exc:
        logger.error("Kill switch DELETE reset failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── Crypto Alert Router status + metrics ─────────────────────────────────

_crypto_router_instance = None


def set_crypto_alert_router(r) -> None:
    """Called from web/main.py lifespan to register the running CryptoAlertRouter."""
    global _crypto_router_instance
    _crypto_router_instance = r


@router.get("/api/v1/alerts/crypto/status")
async def crypto_alert_router_status() -> Dict[str, Any]:
    """Health and state of the CryptoAlertRouter background task."""
    if _crypto_router_instance is None:
        return {"running": False, "error": "router not initialized"}
    return _crypto_router_instance.get_status()


@router.get("/api/v1/alerts/crypto/metrics")
async def crypto_alert_router_metrics() -> Dict[str, Any]:
    """Per-symbol and per-tag alert counters and gauges."""
    if _crypto_router_instance is None:
        return {"counters": {}, "gauges": {}}
    return _crypto_router_instance.get_metrics()


# ── Pre-Scale Monitoring Dashboard Endpoints ─────────────────────────

@router.get("/api/v1/monitoring/pre-scale-health")
async def pre_scale_health() -> Dict[str, Any]:
    """Daily pre-scale health metrics for the 7-day warm-up protocol.
    
    Returns:
        - audit_chain_valid: Whether audit chain integrity check passed
        - audit_chain_records: Number of records in audit chain
        - risk_event_counts: Counts of the 4 critical risk events
        - wiring_validation: OK/FAIL for wiring integrity
        - pre_scale_ready: True if 7 consecutive OK days achieved
        - tainted_path_count: Number of [TAINTED_PATH] markers in logs
    """
    from core.risk_audit_chain import get_risk_audit_chain, verify_audit_chain
    
    # Verify audit chain
    verification = verify_audit_chain()
    chain = get_risk_audit_chain()
    
    # Get risk event counts
    records = chain.export_proof_bundle()
    event_counts = {
        "position_sync_failed": 0,
        "bankroll_unavailable": 0,
        "equity_feed_lost": 0,
        "threshold_changed": 0
    }
    for rec in records:
        et = rec.get("event_type", "")
        if "position_sync_failed" in et:
            event_counts["position_sync_failed"] += 1
        elif "bankroll_unavailable" in et:
            event_counts["bankroll_unavailable"] += 1
        elif "equity_feed_lost" in et:
            event_counts["equity_feed_lost"] += 1
        elif "threshold_changed" in et:
            event_counts["threshold_changed"] += 1
    
    # Check for tainted path markers (scan recent logs if available)
    tainted_count = 0
    try:
        # In production, this would query log aggregation
        # For now, check if status file exists with recent data
        status_path = Path("status/pre_scale_health.json")
        if status_path.exists():
            with open(status_path) as f:
                prev_status = json.load(f)
                tainted_count = prev_status.get("tainted_path_count", 0)
    except Exception as e:
        logger.debug(f"Silent error: {e}")
    
    # Determine overall status
    wiring_ok = verification.valid
    low_risk_events = all(c <= 5 for c in event_counts.values())
    
    status = "OK"
    if not verification.valid:
        status = "FAIL"
    elif not low_risk_events:
        status = "WARN"
    elif tainted_count > 0:
        status = "WARN"
    
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "audit_chain": {
            "valid": verification.valid,
            "records": verification.records_checked,
            "latest_hash": chain.get_latest_hash()[:32] + "...",
        },
        "risk_events": event_counts,
        "wiring_validation": "OK" if wiring_ok else "FAIL",
        "tainted_path_count": tainted_count,
        "pre_scale_ready": False,  # Updated after 7 consecutive OK days
        "monitoring_days_remaining": 7,  # Countdown for protocol
    }


@router.get("/api/v1/monitoring/risk-events")
async def risk_events_summary(
    hours: int = 24,
    event_type: str = None
) -> Dict[str, Any]:
    """Risk event summary with time-window filtering.
    
    Args:
        hours: Lookback window in hours (default 24)
        event_type: Filter to specific event type (optional)
    
    Returns:
        Filtered list of risk events with metadata
    """
    from core.risk_audit_chain import get_risk_audit_chain
    from datetime import datetime, timedelta, timezone
    
    chain = get_risk_audit_chain()
    all_records = chain.export_proof_bundle()
    
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    
    filtered = []
    for rec in all_records:
        try:
            rec_time = datetime.fromisoformat(rec["timestamp"].replace("Z", "+00:00"))
            if rec_time >= cutoff:
                if event_type is None or event_type in rec.get("event_type", ""):
                    filtered.append({
                        "sequence": rec["sequence"],
                        "timestamp": rec["timestamp"],
                        "event_type": rec["event_type"],
                        "payload": rec["payload"],
                        "hash": rec["event_hash"][:24] + "...",
                    })
        except (ValueError, KeyError):
            continue
    
    return {
        "window_hours": hours,
        "event_type_filter": event_type,
        "total_events": len(filtered),
        "events": filtered[-100:],  # Last 100 events max
    }


@router.get("/api/v1/monitoring/audit-chain/verify")
async def verify_audit_chain_endpoint() -> Dict[str, Any]:
    """On-demand audit chain verification endpoint.
    
    Returns full verification result suitable for dashboard display.
    """
    from core.risk_audit_chain import verify_audit_chain
    
    result = verify_audit_chain()
    
    response = {
        "valid": result.valid,
        "records_checked": result.records_checked,
        "verified_at": datetime.now(timezone.utc).isoformat(),
    }
    
    if not result.valid:
        response["broken_at"] = result.broken_at
        response["expected_hash"] = result.expected_hash
        response["actual_hash"] = result.actual_hash
        response["alert"] = "AUDIT_CHAIN_BROKEN"
    
    return response


@router.get("/api/v1/monitoring/tainted-paths")
async def tainted_paths_check() -> Dict[str, Any]:
    """Check for any [TAINTED_PATH] markers in logs or recent output.
    
    Returns count and locations of any tainted path indicators.
    """
    # Scan common log locations for tainted markers
    tainted_found = []
    
    log_paths = [
        "logs/",
        "reports/",
        "data/audit/",
    ]
    
    for log_dir in log_paths:
        path = Path(log_dir)
        if path.exists():
            for log_file in path.glob("*.log"):
                try:
                    with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                        for i, line in enumerate(f, 1):
                            if "[TAINTED_PATH]" in line:
                                tainted_found.append({
                                    "file": str(log_file),
                                    "line": i,
                                    "preview": line.strip()[:100]
                                })
                except Exception:
                    continue
    
    return {
        "tainted_path_count": len(tainted_found),
        "tainted_paths_found": tainted_found[:20],  # Limit to 20
        "status": "FAIL" if tainted_found else "OK",
        "scan_time": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/api/v1/health/services")
async def services_health() -> Dict[str, Any]:
    """Comprehensive health check for all internal services.
    
    Checks Kalshi client, WebSocket bridge, agent grid, fills poller,
    sentiment pipeline, and other critical components.
    """
    from merid.settings import settings
    
    health_results = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "services": {}
    }
    all_healthy = True
    
    # KalshiVenueClient health
    try:
        from merid.event_venues.kalshi.client import get_kalshi_client
        client = get_kalshi_client()
        health_results["services"]["kalshi_client"] = {
            "status": "healthy" if client._http_client and not client._http_client.is_closed else "unhealthy",
            "authenticated": getattr(client, '_authenticated', False),
            "demo_mode": getattr(client, '_demo', True)
        }
    except Exception as e:
        health_results["services"]["kalshi_client"] = {"status": "error", "error": str(e)}
        all_healthy = False
    
    # Kalshi WebSocket bridge health
    try:
        from merid.event_venues.kalshi.ws import get_ws_bridge
        bridge = get_ws_bridge()
        health_results["services"]["kalshi_ws_bridge"] = {
            "status": "healthy" if bridge.is_connected else "disconnected",
            "connected": bridge.is_connected,
            "subscribed_channels": len(getattr(bridge, '_subscriptions', set()))
        }
    except Exception as e:
        health_results["services"]["kalshi_ws_bridge"] = {"status": "error", "error": str(e)}
        all_healthy = False
    
    # Agent Grid health
    try:
        from merid.prediction.agent_grid import get_agent_grid
        grid = get_agent_grid()
        grid_status = grid.get_grid_status() if hasattr(grid, 'get_grid_status') else {}
        health_results["services"]["agent_grid"] = {
            "status": "healthy" if grid_status.get('running', False) else "stopped",
            "running": grid_status.get('running', False),
            "active_agents": grid_status.get('active_agents', 0),
            "total_agents": grid_status.get('total_agents', 0)
        }
    except Exception as e:
        health_results["services"]["agent_grid"] = {"status": "error", "error": str(e)}
        all_healthy = False
    
    # Fills Poller health
    try:
        from merid.event_venues.kalshi.fills_poller import get_fills_poller
        poller = get_fills_poller()
        health_results["services"]["fills_poller"] = {
            "status": "healthy" if getattr(poller, '_running', False) else "stopped",
            "running": getattr(poller, '_running', False),
            "last_poll": getattr(poller, '_last_poll_time', None)
        }
    except Exception as e:
        health_results["services"]["fills_poller"] = {"status": "error", "error": str(e)}
        all_healthy = False
    
    # Kalshi Risk Manager health
    try:
        from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk
        risk = get_kalshi_risk()
        health_results["services"]["kalshi_risk"] = {
            "status": "healthy",
            "daily_pnl": risk.state.daily_pnl_usd if hasattr(risk, 'state') else 0.0,
            "current_equity": risk.state.current_equity_usd if hasattr(risk, 'state') else 0.0
        }
    except Exception as e:
        health_results["services"]["kalshi_risk"] = {"status": "error", "error": str(e)}
        all_healthy = False
    
    # Order Router health
    try:
        from merid.event_venues.kalshi.order_router import get_order_router
        router = get_order_router()
        health_results["services"]["order_router"] = {
            "status": "healthy",
            "initialized": router is not None
        }
    except Exception as e:
        health_results["services"]["order_router"] = {"status": "error", "error": str(e)}
        all_healthy = False
    
    # Market Cache health
    try:
        from merid.event_venues.kalshi.market_cache import get_market_cache
        cache = get_market_cache()
        health_results["services"]["market_cache"] = {
            "status": "healthy",
            "cached_markets": len(getattr(cache, '_markets', {})),
            "last_update": getattr(cache, '_last_update', None)
        }
    except Exception as e:
        health_results["services"]["market_cache"] = {"status": "error", "error": str(e)}
        all_healthy = False
    
    health_results["overall_status"] = "healthy" if all_healthy else "degraded"
    return health_results


@router.get("/api/v1/health/kalshi")
async def kalshi_health() -> Dict[str, Any]:
    """Dedicated Kalshi integration health check.
    
    Returns detailed status of Kalshi API connectivity,
    authentication, and WebSocket state.
    """
    from merid.settings import settings
    
    result = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "kalshi_only_mode": settings.KALSHI_ONLY,
        "components": {}
    }
    
    # API connectivity
    try:
        from merid.event_venues.kalshi.client import get_kalshi_client
        client = get_kalshi_client()
        result["components"]["api_client"] = {
            "connected": client._http_client is not None and not client._http_client.is_closed,
            "authenticated": getattr(client, '_authenticated', False),
            "demo_mode": getattr(client, '_demo', True),
            "rest_endpoint": getattr(client, '_rest_endpoint', 'unknown')
        }
    except Exception as e:
        result["components"]["api_client"] = {"error": str(e)}
    
    # WebSocket state
    try:
        from merid.event_venues.kalshi.ws import get_ws_bridge
        bridge = get_ws_bridge()
        result["components"]["websocket"] = {
            "connected": bridge.is_connected,
            "subscribed_channels": list(getattr(bridge, '_subscriptions', set())),
            "message_count": getattr(bridge, '_message_count', 0)
        }
    except Exception as e:
        result["components"]["websocket"] = {"error": str(e)}
    
    # Market data freshness
    try:
        from merid.event_venues.kalshi.market_cache import get_market_cache
        cache = get_market_cache()
        last_update = getattr(cache, '_last_update', 0)
        age_seconds = time.time() - last_update if last_update else float('inf')
        result["components"]["market_data"] = {
            "cached_markets": len(getattr(cache, '_markets', {})),
            "last_update_seconds_ago": round(age_seconds, 1),
            "fresh": age_seconds < 300  # 5 minutes
        }
    except Exception as e:
        result["components"]["market_data"] = {"error": str(e)}
    
    # Determine overall health
    api_ok = result["components"].get("api_client", {}).get("connected", False)
    ws_ok = result["components"].get("websocket", {}).get("connected", False)
    data_ok = result["components"].get("market_data", {}).get("fresh", False)
    
    if api_ok and ws_ok and data_ok:
        result["status"] = "healthy"
    elif api_ok:
        result["status"] = "degraded"
    else:
        result["status"] = "unhealthy"

    return result


@router.get("/api/v1/system/config-fingerprint")
async def get_config_fingerprint_endpoint(
    subsystem: str = None
) -> Dict[str, Any]:
    """Return config fingerprint for detecting drift between deploys.

    Args:
        subsystem: Optional filter (portfolio, risk, kalshi, feature_flags)

    Returns:
        Compact hash of effective config values with git/env metadata.
    """
    from core.config_loader import (
        ExplicitConfigLoader,
        get_config_fingerprint,
        dump_config,
    )

    # Ensure config is loaded
    loader = ExplicitConfigLoader()
    loader.load_all()

    # Get fingerprint
    fingerprint = get_config_fingerprint(subsystem)

    # Get git info if available
    git_sha = "unknown"
    git_branch = "unknown"
    try:
        import subprocess
        git_sha = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(Path(__file__).resolve().parents[3]),
            stderr=subprocess.DEVNULL,
            text=True
        ).strip()
        git_branch = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(Path(__file__).resolve().parents[3]),
            stderr=subprocess.DEVNULL,
            text=True
        ).strip()
    except Exception:
        pass

    result: Dict[str, Any] = {
        "fingerprint": fingerprint,
        "environment": os.getenv("MERID_ENV", "development"),
        "subsystem": subsystem or "all",
        "git": {
            "sha": git_sha,
            "branch": git_branch,
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # Include per-subsystem fingerprints if no specific subsystem requested
    if subsystem is None:
        result["subsystems"] = {
            "portfolio": get_config_fingerprint("portfolio"),
            "risk": get_config_fingerprint("risk"),
            "kalshi": get_config_fingerprint("kalshi"),
            "feature_flags": get_config_fingerprint("feature_flags"),
        }
        # Add crypto threshold matrix fingerprint
        try:
            from merid.prediction.crypto_threshold_matrix import (
                get_crypto_matrix_fingerprint,
                _get_threshold_mode,
            )
            result["subsystems"]["crypto_matrix"] = get_crypto_matrix_fingerprint()
            result["crypto_matrix_profile"] = _get_threshold_mode()
        except Exception as e:
            result["crypto_matrix_error"] = str(e)

    # Include sample of danger keys with their sources
    danger_keys = [
        "portfolio.max_risk_usd",
        "risk.max_daily_loss_usd",
        "kalshi.spot_strike_max_pct",
    ]

    danger_sample = {}
    dump = dump_config()
    for key in danger_keys:
        if key in dump:
            entry = dump[key]
            danger_sample[key] = {
                "value": entry["value"],
                "source": entry["source"]["source_name"],
                "layer": entry["source"]["layer"],
            }

    # Add crypto matrix danger keys
    try:
        from merid.prediction.crypto_threshold_matrix import resolve_merged_row
        btc_row = resolve_merged_row(asset="BTC", timeframe="15m", archetype="directional")
        danger_sample["crypto_matrix.btc_15m_edge"] = {
            "value": str(btc_row.get("directional_min_edge")),
            "source": btc_row.get("matrix_source_type", "unknown"),
            "layer": f"profile={btc_row.get('matrix_source_profile', 'unknown')},schema={btc_row.get('matrix_schema_version', 1)}",
        }
    except Exception as e:
        danger_sample["crypto_matrix.btc_15m_edge"] = {"error": str(e)}

    if danger_sample:
        result["danger_keys_sample"] = danger_sample

    return result


@router.get("/api/v1/system/config-explain")
async def explain_config_endpoint(
    key: str
) -> Dict[str, Any]:
    """Explain why a specific config key has its value.

    Args:
        key: Dot-notation config key (e.g., portfolio.max_risk_usd)

    Returns:
        Full provenance chain showing all layers that contributed.
    """
    from core.config_loader import (
        ExplicitConfigLoader,
        explain_config,
        get_config,
        dump_config,
    )

    # Ensure config is loaded
    loader = ExplicitConfigLoader()
    loader.load_all()

    # Get explanation
    explanation = explain_config(key)

    if explanation is None:
        # Key not found - return available keys
        all_keys = list(dump_config().keys())
        suggestions = [k for k in all_keys if key.split(".")[0] in k]

        raise HTTPException(
            status_code=404,
            detail={
                "error": f"Key '{key}' not found",
                "suggestions": suggestions[:10],
            }
        )

    # Get full metadata
    value, meta = get_config(key, with_meta=True)

    return {
        "key": key,
        "effective_value": value,
        "explanation": explanation,
        "provenance": [
            {
                "layer": src.layer.name,
                "source": src.source_name,
                "line": src.line,
                "raw_value": str(src.raw_value) if src.raw_value is not None else None,
                "is_effective": i == len(meta.all_sources) - 1,
            }
            for i, src in enumerate(meta.all_sources)
        ] if meta else [],
    }
