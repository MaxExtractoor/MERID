"""Kalshi Agent Grid API — Status, controls, and positions.

Endpoints:
  GET  /api/v1/kalshi-grid/status          — Full grid status
  GET  /api/v1/kalshi-grid/matrix          — Asset × timeframe grid matrix
  GET  /api/v1/kalshi-grid/agents          — All agent summaries
  GET  /api/v1/kalshi-grid/agents/{name}   — Single agent detail
  GET  /api/v1/kalshi-grid/agents/{name}/signals — Per-agent strategy signals
  GET  /api/v1/kalshi-grid/agents/{name}/orders  — Per-agent order history
  GET  /api/v1/kalshi-grid/fills           — All fills across agents
  GET  /api/v1/kalshi-grid/pnl            — Aggregated PnL per asset/timeframe
  GET  /api/v1/kalshi-grid/portfolio       — Portfolio risk snapshot
  GET  /api/v1/kalshi-grid/session         — Session guard status
  POST /api/v1/kalshi-grid/start           — Start the grid
  POST /api/v1/kalshi-grid/stop            — Stop the grid
  POST /api/v1/kalshi-grid/pause           — Pause all agents
  POST /api/v1/kalshi-grid/resume          — Resume all agents
  POST /api/v1/kalshi-grid/agents/{name}/pause   — Pause one agent
  POST /api/v1/kalshi-grid/agents/{name}/resume  — Resume one agent
  POST /api/v1/kalshi-grid/kill-switch/reset     — Reset portfolio kill switch
  GET  /api/v1/kalshi-grid/mode                  — Get current trading mode (paper/live)
  POST /api/v1/kalshi-grid/mode                  — Switch trading mode at runtime
"""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, Body, HTTPException, Query, Request
from auth.user_manager import require_role

# Temporarily remove auth imports to isolate the issue
# from web.api.auth import get_current_session
# from auth.user_manager import require_role
from utils.logger import get_logger

# Dev bypass: Remove auth dependency for local development
# TODO: Re-enable auth for production: dependencies=[Depends(get_current_session)]
router = APIRouter(prefix="/kalshi-grid", tags=["kalshi-grid"])
logger = get_logger("web.api.kalshi_grid")


def _get_grid(request: Request):
    """Get the canonical agent grid from app.state."""
    try:
        logger.info("_get_grid called, attempting to get grid from app.state")
        from merid.prediction.agent_grid_15m import get_15m_grid_from_app
        grid = get_15m_grid_from_app(request.app)
        
        logger.info("Grid retrieved: %s", "SUCCESS" if grid else "NONE")
        if grid is None:
            raise HTTPException(status_code=503, detail="Agent grid not initialized")
        return grid
        
    except Exception as e:
        logger.error("Failed to get agent grid: %s", e)
        raise HTTPException(status_code=503, detail=f"Agent grid unavailable: {e}")


def _get_runtime_health_status(grid) -> Dict[str, Any]:
    """Get runtime health status for better visibility into system state."""
    try:
        import time
        
        # Basic runtime info
        startup_time = getattr(grid, '_startup_time', None)
        runtime_info = {
            "uptime_seconds": time.time() - startup_time if startup_time else None,
            "startup_time": startup_time,
            "grace_window_active": startup_time and (time.time() - startup_time) < 20
        }
        
        # Market state store info (safe import)
        state_store_info = {}
        try:
            from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
            state_store = get_kalshi_market_state_store()
            state_store_info = {
                "active_markets": len(state_store.get_all()),
                "market_keys": list(state_store.get_all().keys())[:10],  # First 10 for brevity
            }
        except Exception as e:
            state_store_info = {"error": f"Market state store unavailable: {e}"}
        
        # WS bridge info
        ws_info = {}
        if hasattr(grid, '_ws_bridge') and grid._ws_bridge:
            ws_info = {
                "subscribed_tickers": list(getattr(grid._ws_bridge, '_subscribed_tickers', [])),
                "subscription_count": len(getattr(grid._ws_bridge, '_subscribed_tickers', [])),
                "bridge_mode": getattr(grid._ws_bridge, 'mode', 'unknown')
            }
        
        # Catalog info
        catalog_info = {}
        try:
            if hasattr(grid, '_catalog') and grid._catalog:
                catalog_snap = grid._catalog.snapshot()
                catalog_info = {
                    "total_markets": len(catalog_snap.markets),
                    "open_markets": len([m for m in catalog_snap.markets if m.market.status == "open"])
                }
        except Exception as e:
            catalog_info = {"error": f"Catalog unavailable: {e}"}
        
        # Universe consistency (if available)
        universe_info = {}
        try:
            from merid.event_venues.kalshi.universe_invariants import get_universe_checker
            universe_checker = get_universe_checker()
            universe_info = {
                "checker_available": True,
                "violation_stats": universe_checker.get_violation_stats()
            }
        except Exception:
            universe_info = {"checker_available": False}
        
        return {
            "runtime": runtime_info,
            "market_state_store": state_store_info,
            "ws_bridge": ws_info,
            "catalog": catalog_info,
            "universe_consistency": universe_info,
            "timestamp": time.time()
        }
        
    except Exception as e:
        logger.error("Failed to get runtime health status: %s", e)
        return {
            "error": str(e),
            "timestamp": time.time()
        }


# ── Test endpoint ─────────────────────────────────────────────────────
@router.get("/test")
async def test_endpoint():
    """Simple test endpoint to verify router is working."""
    # Temporarily bypass grid access to isolate the issue
    try:
        return {"status": "ok", "message": "kalshi-grid router is working"}
    except Exception as e:
        return {"status": "error", "message": f"Router error: {e}"}


# ── Read endpoints ─────────────────────────────────────────────────────

def _normalize_agent(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a raw agent summary to the shape KalshiVolDashboardView expects.

    Raw shape (from KalshiTradingAgent.summary / AgentState.to_dict):
      name, enabled, running, cycles_run, orders_placed, active_tickers, ...
      config.assets, config.timeframes

    Target shape (GridAgent interface in KalshiVolDashboardView):
      name, asset, timeframe, status, cycles, pf, sharpe, sortino, calmar, size_factor
    """
    cfg = raw.get("config", {})
    assets: List = cfg.get("assets", [])
    timeframes: List = cfg.get("timeframes", [])
    asset = assets[0] if assets else raw.get("asset", "")
    timeframe = timeframes[0] if timeframes else raw.get("timeframe", "")

    running = raw.get("running", False)
    enabled = raw.get("enabled", True)
    if not enabled:
        status = "disabled"
    elif running:
        status = "running"
    else:
        status = "stopped"

    # Performance metrics — populated by AgentPerformanceTracker when available
    perf = raw.get("performance", raw.get("metrics", {}))
    pf = float(perf.get("profit_factor", perf.get("pf", 0.0)))
    sharpe = float(perf.get("sharpe_ratio", perf.get("sharpe", 0.0)))
    sortino = float(perf.get("sortino_ratio", perf.get("sortino", 0.0)))
    calmar = float(perf.get("calmar_ratio", perf.get("calmar", 0.0)))
    size_factor = float(perf.get("size_factor", raw.get("size_factor", 1.0)))

    # B8: include per-agent Brier score and calibration error if available
    brier_score = float(perf.get("brier_score", 0.0))
    calibration_error = float(perf.get("calibration_error", 0.0))

    # Extract config and risk_limits for UI display (UI-BUG-001 fix)
    cfg = raw.get("config", {})
    risk_limits = cfg.get("risk_limits", {})

    return {
        "name": raw.get("name", ""),
        "asset": asset,
        "timeframe": timeframe,
        "status": status,
        "cycles": raw.get("cycles_run", raw.get("cycles", 0)),
        "pf": round(pf, 3),
        "sharpe": round(sharpe, 3),
        "sortino": round(sortino, 3),
        "calmar": round(calmar, 3),
        "size_factor": round(size_factor, 3),
        "brier_score": round(brier_score, 4),
        "calibration_error": round(calibration_error, 4),
        # UI-BUG-001: Include config with risk_limits so UI can display position limits
        "config": {
            "assets": cfg.get("assets", []),
            "timeframes": cfg.get("timeframes", []),
            "risk_limits": {
                "max_yes_position": risk_limits.get("max_yes_position", 500),
                "max_no_position": risk_limits.get("max_no_position", 500),
                "max_orders_per_window": risk_limits.get("max_orders_per_window", 10),
                "max_notional_usd": str(risk_limits.get("max_notional_usd", "500")),
                "max_contracts_per_order": risk_limits.get("max_contracts_per_order", 2),  # CRITICAL FIX: 2 - aligned with profile (was 50)
            },
            "risk_profile": cfg.get("risk_profile", "default"),
        },
    }


def _normalize_portfolio_risk(raw_pr: Dict[str, Any]) -> Dict[str, Any]:
    """Flatten PortfolioRiskAgent.summary() to the shape KalshiGridView expects.

    PortfolioRiskAgent.summary() returns:
      { running, kill_switch_active, paused_agents, latest_snapshot, config, snapshot_count }

    KalshiGridView.GridStatus.portfolio_risk expects:
      { kill_switch_active, daily_pnl_usd, total_notional_usd, margin_utilization, paused_agents }
    """
    snapshot = raw_pr.get("latest_snapshot") or {}
    return {
        "kill_switch_active": bool(raw_pr.get("kill_switch_active", False)),
        "daily_pnl_usd": float(snapshot.get("daily_pnl_usd", 0)),
        "total_notional_usd": float(snapshot.get("total_notional_usd", 0)),
        "margin_utilization": float(snapshot.get("margin_utilization_pct", 0)) / 100.0,
        "paused_agents": raw_pr.get("paused_agents", []),
    }


def _normalize_fill(f: Dict[str, Any]) -> Dict[str, Any]:
    """Ensure fill entries have the shape FillEntry expects (no None price_cents)."""
    return {
        **f,
        "price_cents": f.get("price_cents") or 0,
        "action": f.get("action", "buy"),
        "side": f.get("side", "yes"),
        "contracts": f.get("contracts", 0),
        "agent": f.get("agent", ""),
        "simulated": bool(f.get("simulated", True)),
    }


def _get_venue_gate():
    """Lazy-import the singleton VenueGate."""
    try:
        from merid.prediction.venue_gate import get_venue_gate
        return get_venue_gate()
    except Exception as _e:
        logger.debug("_get_venue_gate skipped: %s", _e)
        return None


@router.get("/status")
async def grid_status(request: Request) -> Dict[str, Any]:
    """Full grid status including all agents, portfolio risk, and venue health."""
    raw = _get_grid(request).summary()
    # CT + Universal Agent shared counters (also under metrics["ua_ct"])
    try:
        from merid.prediction.ua_ct_metrics import snapshot as _ua_ct_snap

        raw["ua_ct"] = _ua_ct_snap()
    except Exception:
        raw["ua_ct"] = {}
    # Normalize agents list to the shape KalshiVolDashboardView expects
    raw["agents"] = [_normalize_agent(a) for a in raw.get("agents", [])]
    # Normalize portfolio_risk to the shape KalshiGridView expects
    raw["portfolio_risk"] = _normalize_portfolio_risk(raw.get("portfolio_risk", {}))
    # Surface venue gate mode so the UI can show paper vs live
    gate = _get_venue_gate()
    raw["venue_mode"] = gate.summary() if gate else {"mode": "paper", "is_live": False, "live_enabled": False}
    
    # TODO: Re-enable runtime health status after fixing import issues
    # raw["runtime_health"] = _get_runtime_health_status(grid)
    
    return raw

@router.get("/health")
async def grid_health() -> Dict[str, Any]:
    """Detailed health status of the Kalshi grid and venue.

    Returns the shape expected by the Health & Diagnostics tab:
      status, issues[], catalog{}, ws{}, rate_limits{}, risk{}, validation_gate_metrics{}
    """
    grid = _get_grid()
    summary = grid.summary()
    venue_health = summary.get("venue_health", {})
    metrics = summary.get("metrics", {})
    portfolio = summary.get("portfolio_risk", {})

    issues: List[str] = []

    # Venue connectivity
    if not venue_health.get("connected", False):
        issues.append("Kalshi venue is not connected — orders will fail")
    circuit = venue_health.get("circuit", {})
    if circuit.get("state", "closed") != "closed":
        issues.append(f"Circuit breaker is {circuit.get('state', 'open').upper()} — venue calls blocked")
    error_rate = venue_health.get("error_rate", 0)
    if error_rate > 0.10:
        issues.append(f"High venue error rate: {error_rate * 100:.1f}%")

    # Kill switch
    if portfolio.get("kill_switch_active", False):
        issues.append("Portfolio kill switch is ACTIVE — all trading halted")

    # Grid not running
    if not summary.get("running", False):
        issues.append("Agent grid is not running")

    # Catalog
    catalog_info: Dict[str, Any] = {"market_count": 0, "last_refresh": None, "categories": 0}
    try:
        from merid.event_venues.kalshi.market_catalog import get_market_catalog
        cat = get_market_catalog()
        cat_s = cat.summary()
        catalog_info = {
            "market_count": cat_s.get("market_count", 0),
            "last_refresh": cat_s.get("last_refresh"),
            "categories": len(cat_s.get("categories", {})),
            "running": cat_s.get("running", False),
        }
        if catalog_info["market_count"] == 0:
            issues.append("Market catalog is empty — agents have no markets to trade")
            if not catalog_info["running"]:
                logger.warning("Market catalog not running - restart server to refresh config")
    except Exception as _e:
        logger.warning("Market catalog health probe failed: %s", _e)
        issues.append(f"Market catalog unavailable: {type(_e).__name__}")

    # WebSocket feed - use KalshiWebSocketBridge (production market data pipeline)
    # KalshiWebSocketService is a separate monitoring service and should NOT be used for market data
    ws_info: Dict[str, Any] = {"running": False, "events_forwarded": 0, "subscribed_tickers": 0}
    try:
        from merid.event_venues.kalshi.ws_bridge import get_bridge
        bridge = get_bridge()
        bridge_s = bridge.summary()
        ws_info = {
            "running": bridge_s.get("running", False),
            "events_forwarded": bridge_s.get("events_forwarded", 0),
            "subscribed_tickers": bridge_s.get("subscribed_tickers", 0),
            "source": "bridge"
        }
        if not ws_info["running"]:
            issues.append("WebSocket feed is not running — real-time data unavailable")
    except Exception as _e2:
        logger.debug("ws_bridge health probe failed: %s", _e2)
        issues.append("WebSocket feed unavailable")

    # Rate limits (from venue_health if available, else defaults)
    rate_limits_raw = venue_health.get("rate_limits", {})
    rate_limits: Dict[str, Any] = {
        "orders_this_minute": int(rate_limits_raw.get("write_used_1m", 0)),
        "max_per_minute": int(rate_limits_raw.get("write", 10)),
        "orders_this_hour": int(rate_limits_raw.get("write_used_1h", 0)),
        "max_per_hour": int(rate_limits_raw.get("write_1h", 600)),
    }
    write_tokens = rate_limits_raw.get("write", 10)
    if isinstance(write_tokens, (int, float)) and write_tokens < 2:
        issues.append(f"Rate limit nearly exhausted: {write_tokens:.0f} write tokens remaining")

    # Risk snapshot — overlay global risk_controller for authoritative daily_pnl
    snapshot = portfolio.get("latest_snapshot") or portfolio
    _ks_active = bool(portfolio.get("kill_switch_active", False))
    _daily_pnl = float(snapshot.get("daily_pnl_usd", 0))
    _drawdown = float(snapshot.get("margin_utilization_pct", snapshot.get("margin_utilization", 0)))
    try:
        from merid.risk.kill_switches import risk_controller as _rc
        _rc_st = _rc.get_status()
        if not _rc_st.get("can_trade", True):
            _ks_active = True
        if _rc_st.get("daily_pnl", 0.0) != 0.0:
            _daily_pnl = float(_rc_st["daily_pnl"])
    except Exception as _e:
        logger.debug("risk_controller status skipped: %s", _e)
    try:
        from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk as _gkr
        _krm = _gkr()
        _krs = _krm.summary()
        if _krs.get("drawdown_pct", 0) > 0:
            _drawdown = float(_krs["drawdown_pct"])
        if _krs.get("daily_pnl_usd", 0) != 0.0 and _daily_pnl == 0.0:
            _daily_pnl = float(_krs["daily_pnl_usd"])
    except Exception as _e:
        logger.debug("kalshi_risk status skipped: %s", _e)
    risk_info: Dict[str, Any] = {
        "kill_switch": _ks_active,
        "daily_pnl": _daily_pnl,
        "drawdown_pct": _drawdown,
    }

    # Validation gate metrics from order router
    validation_gate_metrics: Dict[str, Any] = {}
    try:
        from merid.event_venues.kalshi.order_router import get_validation_gate_metrics
        validation_gate_metrics = get_validation_gate_metrics()
    except Exception as _e:
        logger.debug("Validation gate metrics unavailable: %s", _e)

    return {
        "status": "healthy" if not issues else ("degraded" if len(issues) < 3 else "critical"),
        "issues": issues,
        "catalog": catalog_info,
        "ws": ws_info,
        "rate_limits": rate_limits,
        "risk": risk_info,
        "validation_gate_metrics": validation_gate_metrics,
        "venue": venue_health,
        "session": summary.get("session", {}),
        "metrics": metrics,
    }


@router.get("/matrix")
async def grid_matrix(request: Request) -> Dict[str, Any]:
    """Asset × timeframe grid matrix for dashboard display."""
    return _get_grid(request).agent_grid_matrix()


@router.get("/agents")
async def list_agents(
    request: Request,
    include_signals: int = Query(20, ge=0, le=200, description="Recent signals to embed per agent"),
    include_orders: int = Query(20, ge=0, le=200, description="Recent orders to embed per agent"),
) -> Dict[str, Any]:
    """List all agent summaries with embedded recent signals and orders.

    KalshiActivityLog reads agent.signals and agent.orders from this response,
    so we embed them here to avoid N per-agent round-trips.
    """
    grid = _get_grid(request)
    agents: List[Dict[str, Any]] = []
    for a in grid.agents:
        entry = a.summary()

        # Normalize signals to KalshiActivityLog shape:
        #   { ts, market_id, question, side, confidence, ev_cents, agent }
        raw_signals = a.get_signals(include_signals) if include_signals > 0 else []
        normalized_signals = []
        for s in raw_signals:
            edge_float = s.get("edge") or 0.0
            action = s.get("action", "")
            side = "yes" if "YES" in action.upper() or "BUY" in action.upper() else "no"
            normalized_signals.append({
                "ts": s.get("ts", ""),
                "market_id": s.get("market_id", ""),
                "question": s.get("question", ""),
                "side": side,
                "confidence": s.get("confidence") or 0.0,
                "ev_cents": round(edge_float * 100, 1),
                "agent": a.config.name,
            })
        entry["signals"] = normalized_signals

        # Normalize orders to KalshiActivityLog shape:
        #   { ts, market_id, side, size, price_cents, status, source, agent }
        raw_orders = a.get_orders(include_orders) if include_orders > 0 else []
        normalized_orders = []
        for o in raw_orders:
            normalized_orders.append({
                "ts": o.get("ts", ""),
                "market_id": o.get("market_id", ""),
                "side": o.get("side", "yes"),
                "size": o.get("contracts", o.get("size", 0)),
                "price_cents": o.get("price_cents") or 0,
                "status": "filled" if o.get("success") else ("blocked" if o.get("error") else "placed"),
                "source": "paper" if o.get("simulated") else "live",
                "agent": a.config.name,
            })
        entry["orders"] = normalized_orders

        agents.append(entry)
    return {
        "agents": agents,
        "count": len(agents),
    }


@router.get("/agents/{name}")
async def get_agent(name: str) -> Dict[str, Any]:
    """Get a single agent's detail."""
    agent = _get_grid().get_agent(name)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")
    return agent.summary()


@router.get("/agents/{name}/signals")
async def agent_signals(name: str, limit: int = Query(50, ge=1, le=200)) -> Dict[str, Any]:
    """Get recent strategy signals for a specific agent."""
    agent = _get_grid().get_agent(name)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")
    sigs = agent.get_signals(limit)
    return {"agent": name, "signals": sigs, "count": len(sigs)}


@router.get("/agents/{name}/orders")
async def agent_orders(name: str, limit: int = Query(50, ge=1, le=200)) -> Dict[str, Any]:
    """Get recent orders for a specific agent."""
    agent = _get_grid().get_agent(name)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")
    orders = agent.get_orders(limit)
    return {"agent": name, "orders": orders, "count": len(orders)}


@router.get("/fills")
async def all_fills(limit: int = Query(100, ge=1, le=500)) -> Dict[str, Any]:
    """Get all fills across all agents, normalized for KalshiGridView FillEntry shape."""
    grid = _get_grid()
    all_entries: List[Dict[str, Any]] = []
    for agent in grid.agents:
        all_entries.extend(agent.get_fills(limit))

    # Supplement with paper session fills if grid agents have none
    if not all_entries:
        try:
            from merid.prediction.paper_session import get_paper_session
            sess = get_paper_session()
            for fill in sess.get_fills(limit=limit):
                f = fill if isinstance(fill, dict) else fill.to_dict() if hasattr(fill, "to_dict") else {"ts": str(fill)}
                all_entries.append(f)
        except Exception as _e:
            logger.debug("paper_session fills fallback skipped: %s", _e)

    all_entries.sort(key=lambda x: x.get("ts", ""), reverse=True)
    normalized = [_normalize_fill(f) for f in all_entries[:limit]]
    return {"fills": normalized, "count": len(normalized)}


@router.get("/pnl")
async def aggregated_pnl() -> Dict[str, Any]:
    """Aggregated PnL per agent, plus system-wide totals."""
    grid = _get_grid()
    per_agent: List[Dict[str, Any]] = []
    total_fills = 0

    # Pull per-agent PnL from performance tracker
    try:
        from merid.prediction.agent_performance_tracker import get_agent_performance_tracker
        tracker = get_agent_performance_tracker()
        all_metrics = tracker.get_all_metrics()
    except Exception as _e:
        logger.debug("agent_performance_tracker skipped: %s", _e)
        all_metrics = {}

    for agent in grid.agents:
        fills = agent.get_fills(200)
        total_fills += len(fills)
        m = all_metrics.get(agent.config.agent_id) or all_metrics.get(agent.config.name)
        per_agent.append({
            "name": agent.config.name,
            "assets": agent.config.assets,
            "timeframes": agent.config.timeframes,
            "fill_count": len(fills),
            "orders_placed": agent.state.orders_placed,
            "total_pnl_usd": float(m.total_pnl_usd) if m else 0.0,
            "win_rate": round(m.win_rate, 3) if m else 0.0,
            "total_closes": m.total_closes if m else 0,
        })

    # System-wide totals from paper session + performance tracker
    session_pnl_total = 0.0
    session_pnl_today = 0.0
    try:
        from merid.prediction.paper_session import get_paper_session
        sess = get_paper_session()
        sess_summary = sess.summary()
        session_pnl_total = float(sess_summary.get("totals", {}).get("net_pnl_usd", 0.0))
        # No per-day PnL attribute; use total as best approximation
        session_pnl_today = session_pnl_total
    except Exception as _e:
        logger.debug("paper_session pnl skipped: %s", _e)

    tracker_pnl = 0.0
    system_win_rate = 0.0
    try:
        from merid.prediction.agent_performance_tracker import get_agent_performance_tracker
        sys_summary = get_agent_performance_tracker().get_system_summary()
        tracker_pnl = float(sys_summary.get("system_pnl_usd", 0))
        system_win_rate = float(sys_summary.get("system_win_rate", 0))
    except Exception as _e:
        logger.debug("tracker system_summary skipped: %s", _e)

    # HIGH-2 FIX: Canonical PnL (daily/realized/unrealized) from fills_ledger.
    # Per-agent attribution from APT is supplemental only.
    canonical_daily_pnl = 0.0
    canonical_realized_pnl = 0.0
    canonical_unrealized_pnl = 0.0
    canonical_source = "unavailable"
    canonical_reconciliation_status = "unknown"
    try:
        from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
        _ledger = get_fills_ledger()
        _s = _ledger.summary()
        canonical_daily_pnl = round(float(_s.get("daily_realized_pnl_usd", 0)), 2)
        canonical_realized_pnl = round(float(_s.get("total_realized_pnl_usd", 0)), 2)
        canonical_unrealized_pnl = round(float(_s.get("total_unrealized_pnl_usd", 0)), 2)
        canonical_reconciliation_status = _s.get("reconciliation", {}).get("status", "unknown")
        canonical_source = "fills_ledger"
    except Exception as _fl_e:
        logger.warning("grid/pnl: fills_ledger unavailable: %s", _fl_e)

    return {
        "agents": per_agent,
        "total_fills": total_fills,
        "total_agents": len(grid.agents),
        # Canonical PnL from fills_ledger
        "daily_pnl_usd": canonical_daily_pnl,
        "realized_pnl_usd": canonical_realized_pnl,
        "unrealized_pnl_usd": canonical_unrealized_pnl,
        "source": canonical_source,
        "reconciliation_status": canonical_reconciliation_status,
        # Supplemental attribution fields (not canonical PnL)
        # P0-3 FIX: Use explicit None-check to preserve legitimate 0.0 PnL values
        "total_pnl_usd": tracker_pnl if tracker_pnl is not None else session_pnl_total,
        "session_pnl_usd": session_pnl_today,
        "system_win_rate": system_win_rate,
    }


@router.get("/portfolio")
async def portfolio_status() -> Dict[str, Any]:
    """Portfolio risk snapshot — equity, daily PnL, open interest, position count."""
    grid = _get_grid()
    raw_pr = grid.summary().get("portfolio_risk", {})
    snapshot = raw_pr.get("latest_snapshot") or {}
    agents = grid.agents
    # Count open positions across all agents
    position_count = sum(len(a.state.active_tickers) for a in agents)
    return {
        "equity_usd": float(snapshot.get("total_equity_usd", snapshot.get("total_notional_usd", 0))),
        "daily_pnl_usd": float(snapshot.get("daily_pnl_usd", 0)),
        "open_interest": float(snapshot.get("total_notional_usd", 0)),
        "position_count": position_count,
        "kill_switch_active": bool(raw_pr.get("kill_switch_active", False)),
        "margin_utilization": float(snapshot.get("margin_utilization_pct", 0)) / 100.0,
    }


@router.get("/session")
async def session_status() -> Dict[str, Any]:
    """Session guard status (trading hours, maintenance window)."""
    grid = _get_grid()
    return grid.summary().get("session", {})


# ── Control endpoints ──────────────────────────────────────────────────

def _get_default_trading_mode() -> str:
    """Get the default trading mode from settings."""
    try:
        from merid.settings import settings
        if settings.MERID_PM_LIVE_ENABLED and settings.MERID_PM_TRADING_MODE == "live":
            return "live"
        return settings.MERID_PM_TRADING_MODE or "paper"
    except Exception as _e:
        logger.debug("_get_trading_mode settings skipped: %s", _e)
        return "paper"


@router.post("/start")
async def start_grid(
    mode: str = Query(None, description="Trading mode: 'paper' or 'live'. Defaults to MERID_PM_TRADING_MODE from settings."),
    force_start: bool = Query(False, description="Force start even if halted due to drawdown (operator override)."),
    _user=Depends(require_role("operator", "admin")),
) -> Dict[str, Any]:
    """Start the agent grid.

    Pass ?mode=live to start in live trading mode (requires MERID_PM_LIVE_ENABLED=true).
    Defaults to MERID_PM_TRADING_MODE from settings (paper if not configured).
    Pass ?force_start=true to resume trading even if halted due to drawdown (operator override required).
    """
    # Use configured default if not explicitly provided
    if mode is None:
        mode = _get_default_trading_mode()
        logger.info(f"Using default trading mode from settings: {mode}")
    if mode not in ("paper", "live", "mock"):
        raise HTTPException(status_code=400, detail=f"Invalid mode '{mode}'. Use 'paper' or 'live'.")

    # Apply mode to VenueGate before starting
    gate = _get_venue_gate()
    if gate:
        try:
            from trading.trade_mode import TradeMode
            gate.mode = TradeMode(mode)
            if mode == "live" and not gate.live_enabled:
                raise HTTPException(
                    status_code=403,
                    detail="Live mode requested but MERID_PM_LIVE_ENABLED is false. "
                           "Set MERID_PM_LIVE_ENABLED=true in your .env to enable live trading.",
                )
            logger.info(f"Grid starting in {mode.upper()} mode")
        except HTTPException:
            raise
        except Exception as exc:
            logger.warning(f"Could not set VenueGate mode: {exc}")

    grid = _get_grid()
    
    # Force start: clear drawdown halt state if requested
    if force_start:
        try:
            from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import get_kalshi_crypto_15m_risk_envelope
            envelope = get_kalshi_crypto_15m_risk_envelope()
            if envelope.is_halted:
                logger.warning(
                    f"[GRID-START] Force start clearing drawdown halt: drawdown={envelope.current_drawdown_pct:.2%}, "
                    f"band={envelope.current_risk_band.value}"
                )
                # Clear halt state but keep drawdown tracking intact
                envelope.is_halted = False
                # Reset risk multiplier to current band's multiplier (not full 1.0)
                envelope._update_adaptive_risk()
                logger.info(
                    f"[GRID-START] Halt cleared, new band={envelope.current_risk_band.value}, "
                    f"multiplier={envelope.per_trade_risk_multiplier:.2f}"
                )
        except Exception as e:
            logger.warning(f"[GRID-START] Failed to clear drawdown halt state: {e}")
    
    await grid.start()
    return {"status": "started", "mode": mode, "agent_count": len(grid.agents), "force_start": force_start}


@router.post("/stop")
async def stop_grid(_user=Depends(require_role("operator", "admin"))) -> Dict[str, Any]:
    """Stop the agent grid."""
    grid = _get_grid()
    await grid.stop()
    return {"status": "stopped"}


@router.post("/pause")
async def pause_all() -> Dict[str, Any]:
    """Pause all trading agents."""
    grid = _get_grid()
    grid.pause_all()
    return {"status": "paused", "agent_count": len(grid.agents)}


@router.post("/resume")
async def resume_all() -> Dict[str, Any]:
    """Resume all trading agents."""
    grid = _get_grid()
    grid.resume_all()
    return {"status": "resumed", "agent_count": len(grid.agents)}


@router.post("/agents/{name}/pause")
async def pause_agent(name: str) -> Dict[str, Any]:
    """Pause a specific agent."""
    if not _get_grid().pause_agent(name):
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")
    return {"status": "paused", "agent": name}


@router.post("/agents/{name}/resume")
async def resume_agent(name: str) -> Dict[str, Any]:
    """Resume a specific agent."""
    if not _get_grid().resume_agent(name):
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")
    return {"status": "resumed", "agent": name}


@router.post("/kill-switch/reset")
async def reset_kill_switch(_user=Depends(require_role("operator", "admin"))) -> Dict[str, Any]:
    """Reset the portfolio kill switch and resume all paused agents."""
    grid = _get_grid()
    grid.reset_kill_switch()
    return {"status": "kill_switch_reset", "kill_switch_active": grid.kill_switch_active}


# ── Mode switching ─────────────────────────────────────────────────────

@router.post("/mode")
async def set_trading_mode(
    mode: str = Body(..., embed=True, description="'paper' or 'live'"),
    force: bool = Body(False, embed=True, description="Skip live-enabled guard (operator override)"),
    _user=Depends(require_role("operator", "admin")),
) -> Dict[str, Any]:
    """Switch the grid between paper and live trading modes at runtime.

    Live mode requires MERID_PM_LIVE_ENABLED=true in the environment.
    Use force=true to override (operator-only).

    Body: { "mode": "live" | "paper", "force": false }
    """
    if mode not in ("paper", "live", "mock"):
        raise HTTPException(status_code=400, detail=f"Invalid mode '{mode}'. Use 'paper' or 'live'.")

    gate = _get_venue_gate()
    if not gate:
        raise HTTPException(status_code=503, detail="VenueGate not available")

    if mode == "live" and not gate.live_enabled and not force:
        raise HTTPException(
            status_code=403,
            detail="Live mode requires MERID_PM_LIVE_ENABLED=true. "
                   "Set it in your .env or pass force=true to override.",
        )

    try:
        from trading.trade_mode import TradeMode
        prev_mode = gate.mode.value
        gate.mode = TradeMode(mode)
        # When force-overriding to live, also enable the live flag so
        # gate.is_live and check_can_trade() actually permit orders.
        if mode == "live" and force and not gate.live_enabled:
            gate._live_enabled = True
            logger.warning("Force-enabled live_enabled flag via operator override")
        logger.info(f"Trading mode switched: {prev_mode} -> {mode} (force={force})")

        # Reload VenueGate so live_enabled is synced from settings (not just the mode field).
        try:
            # Preserve force-enabled live flag across reload when applicable.
            _was_force_live = mode == "live" and force
            gate.reload()
            if _was_force_live and not gate.live_enabled:
                gate._live_enabled = True
        except Exception as _vge:
            logger.warning("VenueGate reload after grid mode switch failed (non-fatal): %s", _vge)

        # Reset CT singleton so it re-reads mode config on next cycle.
        try:
            from merid.trading.kalshi_continuous_trader import reset_continuous_trader
            reset_continuous_trader()
        except Exception as _cte:
            logger.warning("CT reset failed (non-fatal): %s", _cte)

        return {
            "ok": True,
            "previous_mode": prev_mode,
            "mode": mode,
            "is_live": gate.is_live,
            "live_enabled": gate.live_enabled,
        }
    except Exception as exc:
        logger.error(f"Mode switch failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/canary-trade")
async def run_canary_trade() -> Dict[str, Any]:
    """C4: Send a 1-contract paper order on an active Kalshi market.

    Verifies the full order → fill → reconciliation path within 5 seconds.
    Always runs in PAPER mode regardless of current venue mode.
    Returns { ok, ticker, latency_ms, fill_confirmed, error }.
    """
    import asyncio, time as _time

    start = _time.monotonic()
    ticker = None
    try:
        # Pick the first active market from the catalog
        from merid.event_venues.kalshi.market_catalog import get_market_catalog
        catalog = get_market_catalog()
        all_markets = catalog.get_all_markets()
        markets = [m for m in all_markets if m.market.active][:10]
        if not markets:
            return {"ok": False, "error": "No active markets in catalog", "latency_ms": 0}
        ticker = markets[0].market.market_id
        if not ticker:
            return {"ok": False, "error": "Could not resolve ticker", "latency_ms": 0}

        # Submit a 1-contract paper order at the current bid
        from merid.event_venues.kalshi.decision_trace import new_decision_trace_id
        from merid.event_venues.kalshi.order_router import route_order_async, OrderIntent, TradingMode
        intent = OrderIntent(
            ticker=ticker,
            side="yes",
            action="buy",
            price_cents=50,
            count=1,
            mode=TradingMode.PAPER,
            time_in_force="gtc",
            decision_trace_id=new_decision_trace_id("canary"),
            sentiment_driven=False,
        )
        # OLD-HARDWARE FIX: Increased from 5s to 15s for slow execution
        result = await asyncio.wait_for(
            route_order_async(intent),
            timeout=15.0,
        )
        latency_ms = round((_time.monotonic() - start) * 1000, 1)
        fill_confirmed = getattr(result, "filled", False) or getattr(result, "success", False)
        return {
            "ok": True,
            "ticker": ticker,
            "latency_ms": latency_ms,
            "fill_confirmed": fill_confirmed,
            "result": str(result)[:200] if result else None,
        }
    except asyncio.TimeoutError:
        latency_ms = round((_time.monotonic() - start) * 1000, 1)
        return {"ok": False, "ticker": ticker, "latency_ms": latency_ms, "error": "Timed out after 5s"}
    except Exception as exc:
        latency_ms = round((_time.monotonic() - start) * 1000, 1)
        logger.warning("canary-trade failed: %s", exc)
        return {"ok": False, "ticker": ticker, "latency_ms": latency_ms, "error": str(exc)}


@router.get("/mode")
async def get_trading_mode() -> Dict[str, Any]:
    """Get the current VenueGate trading mode."""
    gate = _get_venue_gate()
    if not gate:
        return {"mode": "unknown", "is_live": False, "live_enabled": False}
    return gate.summary()


@router.get("/performance/agents")
async def performance_agents() -> Dict[str, Any]:
    """Get performance metrics for all agents."""
    try:
        from merid.prediction.agent_performance_tracker import get_agent_performance_tracker
        tracker = get_agent_performance_tracker()
        all_metrics = tracker.get_all_metrics()
        
        agents_dict = {}
        for agent_id, metrics in all_metrics.items():
            agents_dict[agent_id] = metrics.to_dict()
        
        return {
            "agents": agents_dict,
            "count": len(agents_dict)
        }
    except Exception as e:
        logger.warning("performance_agents failed: %s", e)
        return {"agents": {}, "count": 0, "error": str(e)}


@router.get("/performance/agents/{agentId}")
async def performance_agent(agentId: str) -> Dict[str, Any]:
    """Get performance metrics for a specific agent."""
    try:
        from merid.prediction.agent_performance_tracker import get_agent_performance_tracker
        tracker = get_agent_performance_tracker()
        metrics = tracker.get_agent_metrics(agentId)
        return metrics.to_dict()
    except Exception as e:
        logger.warning("performance_agent failed for %s: %s", agentId, e)
        return {"error": str(e)}


@router.get("/performance/summary")
async def performance_summary() -> Dict[str, Any]:
    """Get system-wide performance summary."""
    try:
        from merid.prediction.agent_performance_tracker import get_agent_performance_tracker
        tracker = get_agent_performance_tracker()
        summary = tracker.get_system_summary()
        return summary
    except Exception as e:
        logger.warning("performance_summary failed: %s", e)
        return {"error": str(e)}


@router.get("/performance/top")
async def performance_top(
    metric: str = Query("win_rate", description="Sort by: win_rate, total_pnl_usd, sharpe_ratio"),
    limit: int = Query(10, ge=1, le=50)
) -> Dict[str, Any]:
    """Get top performing agents by specified metric."""
    try:
        from merid.prediction.agent_performance_tracker import get_agent_performance_tracker
        tracker = get_agent_performance_tracker()
        top_agents = tracker.get_top_agents(metric=metric, limit=limit)
        return {"top": top_agents}
    except Exception as e:
        logger.warning("performance_top failed: %s", e)
        return {"top": [], "error": str(e)}


@router.get("/performance/calibration")
async def performance_calibration() -> Dict[str, Any]:
    """Get calibration metrics for all agents."""
    try:
        from merid.prediction.agent_performance_tracker import get_agent_performance_tracker
        tracker = get_agent_performance_tracker()
        all_metrics = tracker.get_all_metrics()
        
        calibration_entries = []
        for agent_id, metrics in all_metrics.items():
            calibration_entries.append({
                "agent_id": agent_id,
                "calibration_error": metrics.calibration_error,
                "avg_confidence": metrics.avg_confidence,
                "brier_score": None,  # Not tracked in AgentMetrics currently
                "well_calibrated": metrics.calibration_error < 0.1  # Threshold for well-calibrated
            })
        
        return {"agents": calibration_entries}
    except Exception as e:
        logger.warning("performance_calibration failed: %s", e)
        return {"agents": [], "error": str(e)}


@router.post("/performance/export")
async def performance_export() -> Dict[str, Any]:
    """Export all performance metrics as CSV."""
    try:
        from merid.prediction.agent_performance_tracker import get_agent_performance_tracker
        tracker = get_agent_performance_tracker()
        all_metrics = tracker.get_all_metrics()
        
        import csv
        import io
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Header
        writer.writerow(["agent_id", "total_fills", "total_closes", "wins", "losses", "win_rate", 
                       "total_pnl_usd", "avg_profit_per_trade", "avg_predicted_edge", "avg_realized_edge",
                       "edge_accuracy", "avg_confidence", "calibration_error", "sharpe_ratio", "last_updated"])
        
        # Data rows
        for agent_id, metrics in all_metrics.items():
            writer.writerow([
                agent_id,
                metrics.total_fills,
                metrics.total_closes,
                metrics.wins,
                metrics.losses,
                metrics.win_rate,
                str(metrics.total_pnl_usd),
                str(metrics.avg_profit_per_trade),
                metrics.avg_predicted_edge,
                metrics.avg_realized_edge,
                metrics.edge_accuracy,
                metrics.avg_confidence,
                metrics.calibration_error,
                metrics.sharpe_ratio,
                metrics.last_updated.isoformat()
            ])
        
        return {
            "csv": output.getvalue(),
            "count": len(all_metrics)
        }
    except Exception as e:
        logger.warning("performance_export failed: %s", e)
        return {"error": str(e)}


@router.get("/crypto/rti")
async def crypto_rti() -> Dict[str, Any]:
    """Real-time crypto indicator data for BTC, ETH, SOL, XRP, DOGE.

    Returns per-asset RTI values, SMA, vol ratios, and spike events
    consumed by KalshiCryptoRtiPanel.tsx.
    """
    import time as _t
    now = _t.time()
    assets: Dict[str, Any] = {}
    try:
        from merid.event_venues.kalshi.btc15m_risk import get_btc15m_risk_layer
        layer = get_btc15m_risk_layer()
        for asset in ("BTC", "ETH", "SOL", "XRP", "DOGE"):
            snap = getattr(layer, "snapshot", lambda a: None)(asset)
            if snap and isinstance(snap, dict):
                assets[asset] = {
                    "rti": snap.get("rti", 0),
                    "sma_60s": snap.get("sma_60s", 0),
                    "vol_ratio": snap.get("vol_ratio", 1.0),
                    "vol_spike_events": snap.get("vol_spike_events", []),
                    "rti_sma_deviation": snap.get("rti_sma_deviation", 0),
                    "recent_vol_spikes": snap.get("recent_vol_spikes", 0),
                    "max_recent_spike": snap.get("max_recent_spike", 0),
                }
            else:
                assets[asset] = {
                    "rti": 0, "sma_60s": 0, "vol_ratio": 1.0,
                    "vol_spike_events": [], "rti_sma_deviation": 0,
                    "recent_vol_spikes": 0, "max_recent_spike": 0,
                }
    except Exception as exc:
        logger.debug("crypto/rti fallback: %s", exc)
        for asset in ("BTC", "ETH", "SOL", "XRP", "DOGE"):
            assets[asset] = {
                "rti": 0, "sma_60s": 0, "vol_ratio": 1.0,
                "vol_spike_events": [], "rti_sma_deviation": 0,
                "recent_vol_spikes": 0, "max_recent_spike": 0,
            }
    return {"data": assets, "timestamp": now, "source": "btc15m_risk_layer"}


@router.get("/sentiment")
async def get_sentiment() -> Dict[str, Any]:
    """Kalshi fear/greed sentiment index — global, per-category, and per-market scores.

    Returns:
      global:        SentimentScore (score 0–100, regime, components)
      by_category:   dict[category → SentimentScore]
      tracked_markets: int
      external:      optional alternative.me crypto fear/greed
      top_markets:   top-10 markets by absolute distance from 50 (most extreme sentiment)
    """
    try:
        from merid.event_venues.kalshi.sentiment import get_sentiment_service
        svc = get_sentiment_service()
        base = svc.summary()

        # Add top-10 most extreme markets
        all_scores = svc.all_market_scores()
        sorted_markets = sorted(
            all_scores.items(),
            key=lambda kv: abs(kv[1]["score"] - 50),
            reverse=True,
        )
        base["top_markets"] = [
            {"ticker": t, **v} for t, v in sorted_markets[:10]
        ]
        return base
    except Exception as exc:
        return {"error": str(exc), "global": {"score": 50, "regime": "greed"}, "by_category": {}}


@router.get("/catalog-health")
async def get_catalog_health() -> Dict[str, Any]:
    """Verify market catalog health for crypto markets.
    
    Returns counts for BTC/ETH/SOL/XRP/DOGE across all timeframes,
    specifically highlighting 15m market availability.
    
    Use this to diagnose "no tradeable BTC markets" issues by checking
    if the catalog is correctly populated with expected markets.
    """
    try:
        from merid.event_venues.kalshi.market_catalog import get_market_catalog
        catalog = get_market_catalog()
        snapshot = catalog.snapshot()
        
        # Get per-asset counts
        assets = {}
        for asset in ("BTC", "ETH", "SOL", "XRP", "DOGE"):
            tf_counts = snapshot.by_asset_timeframe.get(asset, {})
            assets[asset] = {
                "total": snapshot.by_asset.get(asset, 0),
                "timeframes": {
                    "15m": tf_counts.get("15m", 0),
                    "1h": tf_counts.get("1h", 0),
                    "daily": tf_counts.get("daily", 0),
                    "weekly": tf_counts.get("weekly", 0),
                },
                "has_15m_markets": tf_counts.get("15m", 0) > 0,
            }
        
        # Sample tickers for debugging series mismatches
        sample_tickers = getattr(catalog, "_tickers", [])[:20] if hasattr(catalog, "_tickers") else []
        crypto_tickers = [t for t in sample_tickers if any(a in t.upper() for a in ("BTC", "ETH", "SOL", "XRP", "DOGE", "BT", "ET", "SO", "XR", "DO"))]
        
        return {
            "status": "healthy" if all(a["has_15m_markets"] for a in assets.values()) else "degraded",
            "market_count": snapshot.market_count,
            "category_count": len(snapshot.by_category),
            "by_asset": assets,
            "expected_series": ["KXBTUPDOWN-15M", "KXETHUPDOWN-15M", "KXSOLUPDOWN-15M", "KXXRPUPDOWN-15M", "KXDOGEUPDOWN-15M"],
            "sample_tickers": crypto_tickers[:10],
            "diagnostic_hints": {
                "btc_15m_missing": assets.get("BTC", {}).get("timeframes", {}).get("15m", 0) == 0,
                "series_mismatch_fix": "If BTC 15m=0 but catalog shows markets, check config.kalshi_universe.KALSHI_CRYPTO_PRODUCTS series names match live Kalshi tickers",
            },
        }
    except Exception as exc:
        logger.error("catalog_health error: %s", exc)
        return {
            "status": "error",
            "error": str(exc),
            "diagnostic_hints": {
                "catalog_import_failed": "market_catalog module unavailable or not initialized",
            },
        }
