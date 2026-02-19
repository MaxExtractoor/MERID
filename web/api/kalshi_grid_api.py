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

from fastapi import APIRouter, Body, HTTPException, Query

from utils.logger import get_logger

router = APIRouter(prefix="/api/v1/kalshi-grid", tags=["kalshi-grid"])
logger = get_logger("web.api.kalshi_grid")


def _get_grid():
    """Lazy import to avoid circular imports at module load."""
    from merid.prediction.agent_grid import get_agent_grid
    return get_agent_grid()


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
    except Exception:
        return None


@router.get("/status")
async def grid_status() -> Dict[str, Any]:
    """Full grid status including all agents, portfolio risk, and venue health."""
    raw = _get_grid().summary()
    # Normalize agents list to the shape KalshiVolDashboardView expects
    raw["agents"] = [_normalize_agent(a) for a in raw.get("agents", [])]
    # Normalize portfolio_risk to the shape KalshiGridView expects
    raw["portfolio_risk"] = _normalize_portfolio_risk(raw.get("portfolio_risk", {}))
    # Surface venue gate mode so the UI can show paper vs live
    gate = _get_venue_gate()
    raw["venue_mode"] = gate.summary() if gate else {"mode": "paper", "is_live": False, "live_enabled": False}
    return raw

@router.get("/health")
async def grid_health() -> Dict[str, Any]:
    """Detailed health status of the Kalshi grid and venue.

    Returns the shape expected by the Health & Diagnostics tab:
      status, issues[], catalog{}, ws{}, rate_limits{}, risk{}
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
        }
        if catalog_info["market_count"] == 0:
            issues.append("Market catalog is empty — agents have no markets to trade")
    except Exception:
        issues.append("Market catalog unavailable")

    # WebSocket feed
    ws_info: Dict[str, Any] = {"running": False, "events_forwarded": 0, "subscribed_tickers": 0}
    try:
        from merid.event_venues.kalshi.ws_bridge import get_ws_bridge
        bridge = get_ws_bridge()
        bridge_s = bridge.summary()
        ws_info = {
            "running": bridge_s.get("running", False),
            "events_forwarded": bridge_s.get("events_forwarded", 0),
            "subscribed_tickers": bridge_s.get("subscribed_tickers", 0),
        }
        if not ws_info["running"]:
            issues.append("WebSocket feed is not running — real-time data unavailable")
    except Exception:
        pass

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

    # Risk snapshot
    snapshot = portfolio.get("latest_snapshot") or portfolio
    risk_info: Dict[str, Any] = {
        "kill_switch": bool(portfolio.get("kill_switch_active", False)),
        "daily_pnl": float(snapshot.get("daily_pnl_usd", 0)),
        "drawdown_pct": float(snapshot.get("margin_utilization_pct", snapshot.get("margin_utilization", 0))),
    }

    return {
        "status": "healthy" if not issues else ("degraded" if len(issues) < 3 else "critical"),
        "issues": issues,
        "catalog": catalog_info,
        "ws": ws_info,
        "rate_limits": rate_limits,
        "risk": risk_info,
        "venue": venue_health,
        "session": summary.get("session", {}),
        "metrics": metrics,
    }


@router.get("/matrix")
async def grid_matrix() -> Dict[str, Any]:
    """Asset × timeframe grid matrix for dashboard display."""
    return _get_grid().agent_grid_matrix()


@router.get("/agents")
async def list_agents(
    include_signals: int = Query(20, ge=0, le=200, description="Recent signals to embed per agent"),
    include_orders: int = Query(20, ge=0, le=200, description="Recent orders to embed per agent"),
) -> Dict[str, Any]:
    """List all agent summaries with embedded recent signals and orders.

    KalshiActivityLog reads agent.signals and agent.orders from this response,
    so we embed them here to avoid N per-agent round-trips.
    """
    grid = _get_grid()
    agents: List[Dict[str, Any]] = []
    for a in grid.agents:
        entry = a.summary()
        entry["signals"] = a.get_signals(include_signals) if include_signals > 0 else []
        entry["orders"] = a.get_orders(include_orders) if include_orders > 0 else []
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
    return {"agent": name, "signals": agent.get_signals(limit), "count": len(agent.get_signals(limit))}


@router.get("/agents/{name}/orders")
async def agent_orders(name: str, limit: int = Query(50, ge=1, le=200)) -> Dict[str, Any]:
    """Get recent orders for a specific agent."""
    agent = _get_grid().get_agent(name)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")
    return {"agent": name, "orders": agent.get_orders(limit), "count": len(agent.get_orders(limit))}


@router.get("/fills")
async def all_fills(limit: int = Query(100, ge=1, le=500)) -> Dict[str, Any]:
    """Get all fills across all agents, normalized for KalshiGridView FillEntry shape."""
    grid = _get_grid()
    all_entries: List[Dict[str, Any]] = []
    for agent in grid.agents:
        all_entries.extend(agent.get_fills(limit))
    all_entries.sort(key=lambda x: x.get("ts", ""), reverse=True)
    normalized = [_normalize_fill(f) for f in all_entries[:limit]]
    return {"fills": normalized, "count": len(normalized)}


@router.get("/pnl")
async def aggregated_pnl() -> Dict[str, Any]:
    """Aggregated PnL per asset, per timeframe, and total."""
    grid = _get_grid()
    per_agent: List[Dict[str, Any]] = []
    total_fills = 0
    total_wins = 0
    for agent in grid.agents:
        fills = agent.get_fills(200)
        total_fills += len(fills)
        per_agent.append({
            "name": agent.config.name,
            "assets": agent.config.assets,
            "timeframes": agent.config.timeframes,
            "fill_count": len(fills),
            "orders_placed": agent.state.orders_placed,
        })
    return {
        "agents": per_agent,
        "total_fills": total_fills,
        "total_agents": len(grid.agents),
    }


@router.get("/portfolio")
async def portfolio_status() -> Dict[str, Any]:
    """Portfolio risk snapshot."""
    grid = _get_grid()
    return grid.summary().get("portfolio_risk", {})


@router.get("/session")
async def session_status() -> Dict[str, Any]:
    """Session guard status (trading hours, maintenance window)."""
    grid = _get_grid()
    return grid.summary().get("session", {})


# ── Control endpoints ──────────────────────────────────────────────────

@router.post("/start")
async def start_grid(
    mode: str = Query("paper", description="Trading mode: 'paper' or 'live'"),
) -> Dict[str, Any]:
    """Start the agent grid.

    Pass ?mode=live to start in live trading mode (requires MERID_PM_LIVE_ENABLED=true).
    Defaults to paper mode.
    """
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
    await grid.start()
    return {"status": "started", "mode": mode, "agent_count": len(grid.agents)}


@router.post("/stop")
async def stop_grid() -> Dict[str, Any]:
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
async def reset_kill_switch() -> Dict[str, Any]:
    """Reset the portfolio kill switch and resume all paused agents."""
    grid = _get_grid()
    grid.reset_kill_switch()
    return {"status": "kill_switch_reset", "kill_switch_active": grid.kill_switch_active}


# ── Mode switching ─────────────────────────────────────────────────────

@router.post("/mode")
async def set_trading_mode(
    mode: str = Body(..., embed=True, description="'paper' or 'live'"),
    force: bool = Body(False, embed=True, description="Skip live-enabled guard (operator override)"),
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
        logger.info(f"Trading mode switched: {prev_mode} -> {mode} (force={force})")
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


@router.get("/mode")
async def get_trading_mode() -> Dict[str, Any]:
    """Get the current VenueGate trading mode."""
    gate = _get_venue_gate()
    if not gate:
        return {"mode": "unknown", "is_live": False, "live_enabled": False}
    return gate.summary()


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
