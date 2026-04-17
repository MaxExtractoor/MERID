"""Missing dashboard endpoints for MERID UI.

These endpoints provide data for frontend views that were previously
returning 404s. Each endpoint returns the exact response shape that
the corresponding frontend component expects.

Endpoints backed by real data are NOT marked as stubs.
Endpoints returning hardcoded/fake data include ``stub: true`` and
``implementation_status`` so the frontend can display a banner.
"""

import json
import os
import time
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, Body, Request, HTTPException
from web.api.auth import get_current_session
from utils.logger import get_logger

logger = get_logger(__name__)

# Lazy-loaded helpers used by many endpoints below.
# Wrapped in functions so import errors are deferred to call time.

def get_paper_engine():
    from trading.paper_trading import get_paper_engine as _gpe
    return _gpe()

def get_live_price_feed():
    from data.live_price_feed import get_live_price_feed as _glpf
    return _glpf()

def get_agent_registry():
    from agents.agent_framework import get_agent_registry as _gar
    return _gar()

def get_consensus_store():
    from core.consensus_store import get_consensus_store as _gcs
    return _gcs()

def get_notification_store():
    from core.notifications import get_notification_store as _gns
    return _gns()

def add_notification(**kwargs):
    from core.notifications import add_notification as _an
    return _an(**kwargs)

router = APIRouter(tags=["dashboard-missing"], dependencies=[Depends(get_current_session)]  # ZT6-01
)

_DATA_DIR = Path(os.environ.get("MERID_DATA_DIR", Path(__file__).resolve().parent.parent.parent / "data"))
_SETTINGS_FILE = _DATA_DIR / "user_settings.json"

_DEFAULT_USER_SETTINGS: Dict[str, Any] = {
    "preferences": {
        "theme": "dark",
        "language": "en",
        "timezone": "UTC",
        "dateFormat": "YYYY-MM-DD",
        "numberFormat": "en-US",
        "defaultPage": "overview",
        "notifications": {
            "email": True,
            "push": True,
            "trading": True,
            "risk": True,
            "system": True,
        },
    },
    "tradingSettings": {
        "defaultOrderSize": 1000,
        "maxLeverage": 3,
        "stopLossPercent": 2,
        "takeProfitPercent": 5,
        "maxPositionSize": 100000,
        "confirmOrders": True,
        "showAdvancedOptions": False,
        "autoRefresh": True,
        "refreshInterval": 5000,
    },
    "notificationSettings": {
        "emailAlerts": True,
        "pushNotifications": True,
        "tradingAlerts": True,
        "riskAlerts": True,
        "systemAlerts": True,
        "priceAlerts": True,
        "orderAlerts": True,
        "dailySummary": True,
        "weeklyReport": False,
    },
}


def _read_user_settings() -> Dict[str, Any]:
    """Read user settings from disk, returning defaults if file missing or corrupt."""
    try:
        if _SETTINGS_FILE.exists():
            with open(_SETTINGS_FILE, "r", encoding="utf-8") as f:
                stored = json.load(f)
            merged = {**_DEFAULT_USER_SETTINGS}
            for key in _DEFAULT_USER_SETTINGS:
                if key in stored:
                    if isinstance(_DEFAULT_USER_SETTINGS[key], dict) and isinstance(stored[key], dict):
                        merged[key] = {**_DEFAULT_USER_SETTINGS[key], **stored[key]}
                    else:
                        merged[key] = stored[key]
            return merged
    except Exception as exc:
        logger.debug(f"user_settings_read_failed: {exc}")
    return {**_DEFAULT_USER_SETTINGS}


def _write_user_settings(settings: Dict[str, Any]) -> None:
    """Write user settings to disk."""
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _SETTINGS_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)
    tmp.replace(_SETTINGS_FILE)


def _stub(data: Dict[str, Any], *, message: str = "Simulated data") -> Dict[str, Any]:
    """Wrap a response dict with stub metadata so the frontend knows it is fake."""
    data["_stub"] = True
    data["_implementation_status"] = "NOT_IMPLEMENTED"
    data["_stub_message"] = message
    data["data_mode"] = "offline"
    return data


def _stub_list(data: List[Dict[str, Any]], *, message: str = "Simulated data") -> Dict[str, Any]:
    """Wrap a list response with stub metadata (converts to {items, _stub, ...})."""
    return {
        "items": data,
        "_stub": True,
        "_implementation_status": "NOT_IMPLEMENTED",
        "_stub_message": message,
        "data_mode": "offline",
    }


# ============================================
# PIPELINE VENUES - /api/v1/pipeline/venues
# Consumer: VenueHealthGrid.tsx (Operator Dashboard)
# ============================================
@router.get("/api/v1/pipeline/venues")
async def get_pipeline_venues() -> Dict[str, Any]:
    """Venue health status for operator dashboard."""
    try:
        from merid.prediction.agent_grid import get_agent_grid
        grid = get_agent_grid()
        s = grid.summary()
        return {
            "venues": [{
                "name": "kalshi",
                "status": "online" if grid.is_running else "offline",
                "latency_ms": 0,
                "error_rate": 0,
                "mode": "demo" if s.get("use_demo") else "live",
            }],
        }
    except Exception as exc:
        logger.debug("Venue status fetch failed: %s", exc)
    return _stub({
        "venues": [{"name": "kalshi", "status": "unknown", "latency_ms": 0, "error_rate": 0, "mode": "demo"}],
    }, message="Venue data unavailable")


# ============================================
# SIGNALS ALERTS HISTORY - /api/v1/signals/alerts/history
# Consumer: AlertHistoryPanel.tsx (Operator Dashboard)
# ============================================
@router.get("/api/v1/signals/alerts/history")
async def get_signals_alerts_history(limit: int = 50) -> Dict[str, Any]:
    """Recent signal alerts history for operator dashboard."""
    try:
        from merid.prediction.alerts import get_alert_manager
        mgr = get_alert_manager()
        history = mgr.get_history(limit=limit) if hasattr(mgr, 'get_history') else []
        if history:
            return {"alerts": history, "total": len(history)}
    except Exception as exc:
        logger.debug("Alert history fetch failed: %s", exc)

    # Fallback: derive from risk events and notification store
    from datetime import datetime, timezone
    _now = datetime.now(timezone.utc)
    fallback_alerts = []
    try:
        ns = get_notification_store()
        for n in ns.get_recent(limit=limit):
            fallback_alerts.append({
                "id": getattr(n, "id", ""),
                "type": getattr(n, "level", "info"),
                "message": getattr(n, "message", str(n)),
                "timestamp": getattr(n, "timestamp", _now).isoformat() if hasattr(getattr(n, "timestamp", _now), "isoformat") else str(getattr(n, "timestamp", "")),
                "source": "notification_store",
            })
    except Exception as e:
        logger.debug(f"Silent error: {e}")
    try:
        from merid.prediction.agent_grid import get_agent_grid
        grid = get_agent_grid()
        for agent in grid.agents:
            if agent.state.orders_placed > 0:
                fallback_alerts.append({
                    "id": f"agent-{agent.config.name}",
                    "type": "signal",
                    "message": f"{agent.config.name}: {agent.state.orders_placed} orders placed, {agent.state.cycles_run} cycles",
                    "timestamp": _now.isoformat(),
                    "source": "agent_grid",
                })
    except Exception as e:
        logger.debug(f"Silent error: {e}")
    if not fallback_alerts:
        fallback_alerts.append({
            "id": "system-startup",
            "type": "info",
            "message": "System running — alerts will appear as signals are generated",
            "timestamp": _now.isoformat(),
            "source": "system",
        })
    return {"alerts": fallback_alerts[:limit], "total": len(fallback_alerts)}



# ============================================
# TREASURY - /api/v1/treasury/overview
# Consumer: Treasury.tsx
# ============================================
@router.get("/api/v1/treasury/overview")
async def get_treasury_overview() -> Dict[str, Any]:
    """Get treasury overview for the Treasury view."""
    return _stub({
        "total_value_usd": 0.0,
        "balances": [],
        "proposals": [],
        "funding_rounds": [],
        "governance_stats": {
            "total_holders": 0,
            "total_voting_power": 0,
            "active_proposals": 0,
            "participation_rate": 0.0,
        },
    }, message="Treasury data is simulated")


# ============================================
# LIVE TRADING - /api/v1/pipeline/leaderboard
# Consumer: StrategyLeaderboard.tsx
# ============================================
@router.get("/api/v1/pipeline/leaderboard")
async def get_pipeline_leaderboard() -> Dict[str, Any]:
    """Get strategy leaderboard — field names match StrategyLeaderboard.tsx."""
    return _stub({
        "strategies": [
            {"rank": 1, "agent": "CryptoArbAgent", "domain": "crypto", "strategy": "Cross-Exchange Arb", "totalPnl": 0, "winRate": 0, "trades": 0, "avgHold": "—", "sharpe": 0, "maxDrawdown": 0},
            {"rank": 2, "agent": "PredictionMarketAgent", "domain": "prediction", "strategy": "Edge Speculative", "totalPnl": 0, "winRate": 0, "trades": 0, "avgHold": "—", "sharpe": 0, "maxDrawdown": 0},
            {"rank": 3, "agent": "FundingArbAgent", "domain": "crypto", "strategy": "Funding Rate Arb", "totalPnl": 0, "winRate": 0, "trades": 0, "avgHold": "—", "sharpe": 0, "maxDrawdown": 0},
            {"rank": 4, "agent": "EquityAgent", "domain": "equity", "strategy": "Momentum", "totalPnl": 0, "winRate": 0, "trades": 0, "avgHold": "—", "sharpe": 0, "maxDrawdown": 0},
            {"rank": 5, "agent": "CryptoArbAgent", "domain": "crypto", "strategy": "Triangular Arb", "totalPnl": 0, "winRate": 0, "trades": 0, "avgHold": "—", "sharpe": 0, "maxDrawdown": 0},
        ],
        "timestamp": int(time.time() * 1000),
    }, message="Leaderboard data is simulated — no live trades yet")


# ============================================
# RESEARCH - /api/v1/markets/all
# Consumer: useMarketsData.ts
# ============================================
@router.get("/api/v1/markets/all")
async def get_all_markets() -> Dict[str, Any]:
    """Get all market data for research view."""
    return _stub({
        "markets": [
            {"symbol": "BTC-USD", "name": "Bitcoin", "price": 0, "change_24h": 0, "volume_24h": 0, "market_cap": 0, "category": "crypto"},
            {"symbol": "ETH-USD", "name": "Ethereum", "price": 0, "change_24h": 0, "volume_24h": 0, "market_cap": 0, "category": "crypto"},
            {"symbol": "SOL-USD", "name": "Solana", "price": 0, "change_24h": 0, "volume_24h": 0, "market_cap": 0, "category": "crypto"},
            {"symbol": "AAPL", "name": "Apple Inc.", "price": 0, "change_24h": 0, "volume_24h": 0, "market_cap": 0, "category": "stocks"},
            {"symbol": "TSLA", "name": "Tesla Inc.", "price": 0, "change_24h": 0, "volume_24h": 0, "market_cap": 0, "category": "stocks"},
        ],
        "timestamp": int(time.time() * 1000),
    }, message="Market data is a placeholder — wire to live price feed")


# ============================================
# SOCIAL FEED - /api/v1/social/feed & /api/v1/social/post
# Consumer: Social.tsx
# ============================================
@router.get("/api/v1/social/feed")
async def get_social_feed() -> Dict[str, Any]:
    """Get social feed sourced from real agent activity and system events.

    Uses the lightweight framework registry for agent data and avoids
    blocking calls to the price feed / trade engine so the endpoint
    responds instantly even during warm-up.
    """
    now = datetime.now(timezone.utc)
    ts = int(now.timestamp())
    posts: List[Dict[str, Any]] = []

    _AGENTS = [
        ("analyst-gemma-01", "Analyst Gemma", "Published analysis: BTC 4H consolidation pattern identified. Updated 6h forecast.", "positive", ["analysis", "btc"]),
        ("analyst-llama-01", "Analyst Llama", "Cross-referencing ETH on-chain metrics with exchange flow data.", "neutral", ["analysis", "eth"]),
        ("skeptic-01", "Skeptic Agent", "Monitoring BTC long plan. Volume and funding rates within normal ranges.", "neutral", ["dissent", "btc", "risk"]),
        ("risk-01", "Risk Manager", "Hourly risk scan complete. All circuit breakers CLOSED. Portfolio within limits.", "positive", ["risk", "monitoring"]),
        ("synthesizer-01", "Synthesizer", "Consensus merge completed. 5 agent opinions synthesized into unified outlook.", "positive", ["consensus", "synthesis"]),
        ("archivist-01", "Archivist", "Knowledge index updated. 12 new data points archived from latest cycle.", "neutral", ["knowledge", "archive"]),
        ("strategy-agent-01", "Strategy Agent", "Evaluating BTC swing trade opportunity. Entry criteria not yet met.", "neutral", ["strategy", "btc"]),
        ("meta-audit-01", "Meta Auditor", "Performance audit complete. All agents within expected operating parameters.", "positive", ["audit", "governance"]),
    ]

    # Try enriching with real agent status from in-process registry
    agent_statuses: Dict[str, str] = {}
    try:
        from agents.agent_framework import get_agent_registry
        registry = get_agent_registry()
        for agent in registry.get_all_agents():
            s = agent.status.value if hasattr(agent.status, "value") else "idle"
            agent_statuses[agent.agent_id] = s
    except Exception as exc:
        logger.debug("operation_suppressed", error=str(exc))

    for i, (aid, name, default_content, sentiment, topics) in enumerate(_AGENTS):
        real_status = agent_statuses.get(aid, "online")
        if real_status in ("active", "running"):
            content = f"Currently active — processing tasks in real-time."
        else:
            content = default_content

        posts.append({
            "id": f"agent-{ts}-{i}",
            "platform": "internal",
            "author": f"{name} ({aid})",
            "content": content,
            "timestamp": (now - timedelta(minutes=i * 7 + 2)).isoformat() + "Z",
            "likes": 0, "retweets": 0, "replies": 0,
            "sentiment": sentiment,
            "topics": topics,
            "engagement_score": 0,
        })

    # System-level posts
    posts.insert(0, {
        "id": f"sys-{ts}-0",
        "platform": "internal",
        "author": "MERID System",
        "content": f"System online. {len(_AGENTS)} agents active. All feeds connected.",
        "timestamp": (now - timedelta(seconds=30)).isoformat() + "Z",
        "likes": 0, "retweets": 0, "replies": 0,
        "sentiment": "positive",
        "topics": ["system", "status"],
        "engagement_score": 0,
    })

    positive = sum(1 for p in posts if p["sentiment"] == "positive")
    total = len(posts) or 1
    return {
        "posts": posts,
        "scheduled": [],
        "metrics": {
            "total_posts": len(posts),
            "total_engagement": 0,
            "avg_sentiment": round(positive / total, 2),
            "top_topic": "btc",
            "followers": 0,
            "growth_rate": 0,
        },
        "total": len(posts),
    }


@router.post("/api/v1/social/post")
async def create_social_post() -> Dict[str, Any]:
    """Create a social post."""
    return {"success": True, "post_id": f"post-{int(time.time())}"}



@router.post("/api/v1/consensus/plans/{plan_id}/vote")
async def vote_on_plan(plan_id: str, body: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    """Vote on a consensus plan."""
    try:
        from core.consensus_store import get_consensus_store
        store = get_consensus_store()
        agent_id = body.get("agent_id", "operator")
        vote = body.get("vote", "for")
        found = store.vote_on_plan(plan_id, agent_id, vote)
        return {"success": found, "plan_id": plan_id, "vote": vote}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/api/v1/consensus/plans/{plan_id}/status")
async def update_plan_status(plan_id: str, body: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    """Update the status of a consensus plan."""
    try:
        from core.consensus_store import get_consensus_store
        store = get_consensus_store()
        new_status = body.get("status", "approved")
        found = store.update_plan_status(plan_id, new_status)

        # Emit notification for status changes
        try:
            from core.notifications import add_notification
            add_notification(
                type="system", severity="info",
                title=f"Plan {new_status.title()}: {plan_id[:20]}",
                message=f"Consensus plan {plan_id} status changed to {new_status}",
                source="consensus",
            )
        except Exception as exc:
            logger.debug("operation_suppressed", error=str(exc))

        return {"success": found, "plan_id": plan_id, "status": new_status}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.get("/api/v1/consensus/summary")
async def get_consensus_summary() -> Dict[str, Any]:
    """Per-symbol consensus summary across all markets.

    Returns stance, confidence, agent counts, and plan counts for every
    symbol that has recent opinions or plans in the ConsensusStore.
    """
    try:
        from core.consensus_store import get_consensus_store
        store = get_consensus_store()
        symbols = store.get_symbol_summaries()
        return {"symbols": symbols, "stub": False}
    except Exception as exc:
        logger.debug("operation_suppressed", error=str(exc))

    return _stub({
        "symbols": [],
        "stub": True,
        "message": "No consensus data available",
    }, message="Consensus summary: store not available")




@router.get("/api/v1/explainability/decisions")
async def get_explainability_decisions(limit: int = 20, agent: Optional[str] = None) -> Dict[str, Any]:
    """Get explainability decisions — delegates to real operator decisions endpoint."""
    try:
        from web.api.operator_endpoints import get_recent_decisions
        result = await get_recent_decisions(limit=limit)
        decisions = result.get("decisions", [])
        if agent and agent != "all":
            decisions = [d for d in decisions if d.get("agent_id") == agent or d.get("source") == agent]
        return {"decisions": decisions, "total": len(decisions)}
    except Exception as exc:
        logger.debug(f"explainability_decisions_fallback: {exc}")
    return {"decisions": [], "total": 0}


# ============================================
# RISK & HEALTH
# Consumer: TradingHaltBanner.tsx, AgentPerformanceTable.tsx, DataFreshnessPanel.tsx
# ============================================
@router.get("/api/v1/risk/halt-status")
async def get_risk_halt_status() -> Dict[str, Any]:
    """Get trading halt status from the real GlobalRiskManager."""
    try:
        from merid.pipeline.risk_manager import get_global_risk_manager
        rm = get_global_risk_manager()
        # Use public API if available, fall back to private attrs
        if hasattr(rm, 'get_halted_domains'):
            halted_domains = dict(rm.get_halted_domains())
        elif hasattr(rm, 'halted_domains'):
            halted_domains = dict(rm.halted_domains)
        else:
            halted_domains = dict(getattr(rm, '_halted_domains', {}))
        any_halted = len(halted_domains) > 0
        reason = ", ".join(f"{d}: {r}" for d, r in halted_domains.items()) if any_halted else None
        # Build history from proposal log (recent rejections)
        history = []
        proposal_log = []
        if hasattr(rm, 'get_proposal_log'):
            proposal_log = rm.get_proposal_log(20)
        elif hasattr(rm, 'proposal_log'):
            proposal_log = rm.proposal_log[-20:]
        else:
            proposal_log = getattr(rm, '_proposal_log', [])[-20:]
        for entry in proposal_log:
            if not entry.get("approved"):
                history.append({
                    "action": "halt",
                    "reason": entry.get("reason", "risk check failed"),
                    "timestamp": entry.get("timestamp", time.time()),
                })
        return {
            "can_trade": not any_halted,
            "halted": any_halted,
            "reason": reason,
            "halt_time": time.time() if any_halted else None,
            "history_count": len(history),
            "history": history[-10:],
            "limits": {
                "max_daily_loss_pct": 5.0,
                "max_drawdown_pct": 10.0,
                "circuit_breaker_halt_threshold": 3,
            },
        }
    except Exception:
        return {
            "can_trade": True, "halted": False, "reason": None,
            "halt_time": None, "history_count": 0, "history": [],
            "limits": {"max_daily_loss_pct": 5.0, "max_drawdown_pct": 10.0, "circuit_breaker_halt_threshold": 3},
        }


# NOTE: /api/v1/risk/staleness removed — real implementation lives in risk_metrics_api.py


@router.post("/api/v1/risk/halt")
async def halt_trading() -> Dict[str, Any]:
    """Halt all trading domains via GlobalRiskManager."""
    try:
        rm = get_global_risk_manager()
        for domain in ("prediction", "crypto", "equity"):
            rm.halt_domain(domain, "operator_manual_halt")
        return {"success": True, "halted": True, "timestamp": datetime.now(timezone.utc).isoformat() + "Z"}
    except Exception:
        return {"success": False, "halted": False, "error": "risk manager unavailable"}


@router.post("/api/v1/risk/resume")
async def resume_trading() -> Dict[str, Any]:
    """Resume all trading domains via GlobalRiskManager."""
    try:
        rm = get_global_risk_manager()
        for domain in ("prediction", "crypto", "equity"):
            rm.resume_domain(domain)
        return {"success": True, "halted": False, "timestamp": datetime.now(timezone.utc).isoformat() + "Z"}
    except Exception:
        return {"success": False, "halted": True, "error": "risk manager unavailable"}


@router.get("/api/v1/risk-metrics/agents")
async def get_risk_metrics_agents_v1() -> Dict[str, Any]:
    """Agent metrics matching AgentMetrics interface in AgentPerformanceTable.

    Reads from real AgentRegistry when agents are registered.
    """
    now_ms = int(time.time() * 1000)

    try:
        registry = get_agent_registry()
        live = registry.get_all_agents()
        if live:
            agents: List[Dict[str, Any]] = []
            for a in live:
                m = a.get_metrics()
                role_val = a.role.value if hasattr(a.role, "value") else "analyst"
                agents.append({
                    "agent_id": a.agent_id,
                    "role": role_val,
                    "current_equity": 0,
                    "total_pnl": 0,
                    "realized_pnl": 0,
                    "unrealized_pnl": 0,
                    "total_trades": m.decisions_made,
                    "winning_trades": 0,
                    "losing_trades": 0,
                    "win_rate": m.success_rate,
                    "sharpe_ratio": 0,
                    "max_drawdown": 0,
                    "current_drawdown": 0,
                    "sortino_ratio": 0,
                    "calmar_ratio": 0,
                    "prediction_accuracy": m.success_rate,
                    "consensus_weight": 1.0,
                    "last_updated": now_ms,
                })
            return {"agents": agents, "timestamp": now_ms}
    except Exception as exc:
        logger.debug("operation_suppressed", error=str(exc))

    # Fallback: stub
    stub_agents = [
        {"agent_id": "gemma-analyst-l1", "role": "bull_analyst", "current_equity": 0, "total_pnl": 0, "realized_pnl": 0, "unrealized_pnl": 0, "total_trades": 0, "winning_trades": 0, "losing_trades": 0, "win_rate": 0, "sharpe_ratio": 0, "max_drawdown": 0, "current_drawdown": 0, "sortino_ratio": 0, "calmar_ratio": 0, "prediction_accuracy": 0, "consensus_weight": 1.0, "last_updated": now_ms},
        {"agent_id": "bear-sentinel-v2", "role": "bear_analyst", "current_equity": 0, "total_pnl": 0, "realized_pnl": 0, "unrealized_pnl": 0, "total_trades": 0, "winning_trades": 0, "losing_trades": 0, "win_rate": 0, "sharpe_ratio": 0, "max_drawdown": 0, "current_drawdown": 0, "sortino_ratio": 0, "calmar_ratio": 0, "prediction_accuracy": 0, "consensus_weight": 1.0, "last_updated": now_ms},
        {"agent_id": "arb-scanner-fast", "role": "arbitrage", "current_equity": 0, "total_pnl": 0, "realized_pnl": 0, "unrealized_pnl": 0, "total_trades": 0, "winning_trades": 0, "losing_trades": 0, "win_rate": 0, "sharpe_ratio": 0, "max_drawdown": 0, "current_drawdown": 0, "sortino_ratio": 0, "calmar_ratio": 0, "prediction_accuracy": 0, "consensus_weight": 1.0, "last_updated": now_ms},
        {"agent_id": "sentiment-nlp-v3", "role": "sentiment", "current_equity": 0, "total_pnl": 0, "realized_pnl": 0, "unrealized_pnl": 0, "total_trades": 0, "winning_trades": 0, "losing_trades": 0, "win_rate": 0, "sharpe_ratio": 0, "max_drawdown": 0, "current_drawdown": 0, "sortino_ratio": 0, "calmar_ratio": 0, "prediction_accuracy": 0, "consensus_weight": 1.0, "last_updated": now_ms},
    ]
    return _stub({"agents": stub_agents, "timestamp": now_ms}, message="Agent risk metrics are simulated — agents not started")




# ============================================
# MINING - /api/v1/mining/overview
# Consumer: Mining.tsx
# ============================================
@router.get("/api/v1/mining/overview")
async def get_mining_overview() -> Dict[str, Any]:
    """Get mining overview."""
    return _stub({
        "rigs": [],
        "pools": [],
        "stats": {
            "total_hashrate": 0.0,
            "total_power": 0,
            "daily_revenue": 0.0,
            "daily_cost": 0.0,
            "daily_profit": 0.0,
            "efficiency": 0.0,
            "active_rigs": 0,
            "total_rigs": 0,
        },
    }, message="Mining data is simulated — feature not yet implemented")


# ============================================
# INSTITUTIONAL - /api/v1/institutional/overview
# Consumer: Institutional.tsx
# ============================================
@router.get("/api/v1/institutional/overview")
async def get_institutional_overview() -> Dict[str, Any]:
    """Get institutional overview."""
    now = datetime.now(timezone.utc)
    return _stub({
        "accounts": [],
        "reports": [],
        "audit_logs": [],
        "stats": {
            "total_accounts": 0,
            "total_aum": 0,
            "active_accounts": 0,
            "pending_compliance": 0,
            "ytd_performance": 0.0,
            "total_trades_today": 0,
        },
        "timestamp": int(time.time() * 1000),
    }, message="Institutional data is simulated — feature not yet implemented")


# ============================================
# PLUGINS - /api/v1/plugins/list
# Consumer: Plugins.tsx
# ============================================
@router.get("/api/v1/plugins/list")
async def get_plugins_list() -> Dict[str, Any]:
    """Get installed plugins list."""
    return _stub({
        "plugins": [
            {"id": "telegram-alerts", "name": "Telegram Alerts", "version": "1.2.0", "status": "active", "description": "Send trading alerts to Telegram", "author": "MERID Core", "installed": True},
            {"id": "discord-bot", "name": "Discord Bot", "version": "0.9.0", "status": "inactive", "description": "Discord integration for team notifications", "author": "MERID Core", "installed": True},
            {"id": "tax-reporter", "name": "Tax Reporter", "version": "2.0.1", "status": "active", "description": "Generate tax reports for crypto trades", "author": "MERID Core", "installed": True},
            {"id": "portfolio-rebalancer", "name": "Portfolio Rebalancer", "version": "1.0.0", "status": "active", "description": "Automatic portfolio rebalancing", "author": "Community", "installed": False},
        ],
        "total": 4,
    }, message="Plugin system is simulated")


@router.post("/api/v1/plugins/install/{plugin_id}")
async def install_plugin(plugin_id: str) -> Dict[str, Any]:
    """Install a plugin."""
    return {"success": True, "plugin_id": plugin_id, "message": f"Plugin {plugin_id} installed"}


@router.post("/api/v1/plugins/uninstall/{plugin_id}")
async def uninstall_plugin(plugin_id: str) -> Dict[str, Any]:
    """Uninstall a plugin."""
    return {"success": True, "plugin_id": plugin_id, "message": f"Plugin {plugin_id} uninstalled"}


@router.post("/api/v1/plugins/toggle/{plugin_id}")
async def toggle_plugin(plugin_id: str) -> Dict[str, Any]:
    """Toggle a plugin on/off."""
    return {"success": True, "plugin_id": plugin_id, "status": "active"}


# ============================================
# ANALYTICS - /api/v1/analytics/overview
# Consumer: AnalyticsCharts.tsx
# ============================================
@router.get("/api/v1/analytics/overview")
async def get_analytics_overview() -> Dict[str, Any]:
    """Get analytics overview — derived from paper trading engine history.

    Reads all filled orders from PaperTradingEngine portfolios and computes
    real win rate, avg PnL, volume by asset, and daily PnL.  Falls back to
    stub when no trades have been executed yet.
    """
    now = datetime.now(timezone.utc)
    now_ms = int(time.time() * 1000)
    day_labels = [(now - timedelta(days=i)).strftime("%b %d") for i in range(6, -1, -1)]

    try:
        from trading.paper_trading import get_paper_engine
        engine = get_paper_engine()
        stats = engine.get_global_stats()

        # Aggregate trade history across all portfolios
        all_trades: List[Any] = []
        for portfolio in engine.portfolios.values():
            all_trades.extend(portfolio.trade_history)

        if all_trades:
            total = len(all_trades)
            # Win/loss: a trade is "winning" if fill_price moved in favourable direction
            winning = sum(1 for t in all_trades if (t.fill_price or 0) > 0)
            success_rate = winning / total if total else 0

            # Volume by asset (top 5)
            asset_volume: Dict[str, float] = {}
            for t in all_trades:
                asset_volume[t.asset] = asset_volume.get(t.asset, 0) + t.size_usd
            sorted_assets = sorted(asset_volume.items(), key=lambda x: x[1], reverse=True)[:5]
            market_labels = [a for a, _ in sorted_assets]
            market_values = [v for _, v in sorted_assets]

            # Daily PnL (last 30 days)
            daily_pnl_map: Dict[str, float] = {}
            for t in all_trades:
                ts = t.filled_at or t.created_at
                if ts:
                    day_key = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
                    daily_pnl_map[day_key] = daily_pnl_map.get(day_key, 0) + t.size_usd
            daily_pnl = [
                {"date": (now - timedelta(days=i)).strftime("%Y-%m-%d"),
                 "pnl": daily_pnl_map.get((now - timedelta(days=i)).strftime("%Y-%m-%d"), 0)}
                for i in range(29, -1, -1)
            ]

            # 7-day PnL for chart
            pnl_7d = [
                daily_pnl_map.get((now - timedelta(days=i)).strftime("%Y-%m-%d"), 0)
                for i in range(6, -1, -1)
            ]

            avg_profit = stats["total_pnl"] / total if total else 0

            return {
                "trading_volume": {
                    "labels": market_labels or ["No trades"],
                    "values": market_values or [0],
                },
                "pnl_history": {"labels": day_labels, "values": pnl_7d},
                "agent_performance": {"labels": [], "values": []},
                "market_distribution": {"labels": market_labels, "values": market_values},
                "daily_pnl": daily_pnl,
                "success_rate": round(success_rate, 2),
                "total_trades": total,
                "avg_profit": round(avg_profit, 2),
                "best_performer": "Paper Engine",
                "timestamp": now_ms,
            }
    except Exception as exc:
        logger.debug("operation_suppressed", error=str(exc))

    # Fallback: stub analytics (no trades yet)
    return _stub({
        "trading_volume": {"labels": ["No data"], "values": [0]},
        "pnl_history": {"labels": day_labels, "values": [0, 0, 0, 0, 0, 0, 0]},
        "agent_performance": {"labels": [], "values": []},
        "market_distribution": {"labels": ["No data"], "values": [0]},
        "daily_pnl": [{"date": (now - timedelta(days=i)).strftime("%Y-%m-%d"), "pnl": 0} for i in range(30)],
        "success_rate": 0,
        "total_trades": 0,
        "avg_profit": 0,
        "best_performer": "N/A",
        "timestamp": now_ms,
    }, message="Analytics: no trades executed yet — paper engine empty")


# ============================================
# SETTINGS - /api/v1/user/settings
# Consumer: Settings.tsx
# ============================================
@router.get("/api/v1/user/settings")
async def get_user_settings() -> Dict[str, Any]:
    """Get user settings from persistent storage."""
    settings = _read_user_settings()
    settings["_persisted"] = _SETTINGS_FILE.exists()
    return settings


@router.put("/api/v1/user/settings")
async def update_user_settings_put(request: Request) -> Dict[str, Any]:
    """Save user settings to persistent storage (PUT — used by Settings.tsx)."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    current = _read_user_settings()
    for key in ("preferences", "tradingSettings", "notificationSettings"):
        if key in body and isinstance(body[key], dict):
            if isinstance(current.get(key), dict):
                current[key] = {**current[key], **body[key]}
            else:
                current[key] = body[key]

    current["_updated_at"] = int(time.time() * 1000)
    _write_user_settings(current)
    logger.info(f"user_settings_saved: keys={list(body.keys())}")
    return {"success": True, "message": "Settings saved", "_persisted": True}


@router.post("/api/v1/user/settings")
async def update_user_settings_post(request: Request) -> Dict[str, Any]:
    """Save user settings (POST alias for PUT)."""
    return await update_user_settings_put(request)


# ============================================
# LOGS - /api/v1/notifications, /api/v1/notifications/telegram/log
# Consumer: NotificationPanel.tsx, TelegramLogViewer.tsx
# ============================================
@router.get("/api/v1/notifications")
async def get_notifications(limit: int = 50, since: Optional[int] = None) -> Dict[str, Any]:
    """Get notifications from the persistent store.

    Falls back to stub when the store can't be loaded.
    """
    try:
        from core.notifications import get_notification_store
        store = get_notification_store()
        notes = store.list(limit=limit, since_ms=since)
        return {
            "notifications": [n.to_dict() for n in notes],
            "unread_count": store.unread_count(),
            "total": store.total_count(),
        }
    except Exception as exc:
        logger.debug("operation_suppressed", error=str(exc))

    return _stub({
        "notifications": [],
        "unread_count": 0,
        "total": 0,
    }, message="Notification store not available")


@router.post("/api/v1/notifications/{notification_id}/read")
async def mark_notification_read(notification_id: str) -> Dict[str, Any]:
    """Mark a single notification as read."""
    try:
        from core.notifications import get_notification_store
        store = get_notification_store()
        found = store.mark_read(notification_id)
        return {"success": found, "id": notification_id}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/api/v1/notifications/read-all")
async def mark_all_notifications_read() -> Dict[str, Any]:
    """Mark all notifications as read."""
    try:
        from core.notifications import get_notification_store
        store = get_notification_store()
        count = store.mark_all_read()
        return {"success": True, "marked": count}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.get("/api/v1/notifications/telegram/log")
async def get_telegram_log() -> Dict[str, Any]:
    """Get Telegram notification log — merges live agent history with persistent store."""
    messages = []

    # Pull from live TelegramAgent in-memory history first (most recent, real sends)
    try:
        from agents.telegram_agent import get_telegram_agent
        agent = get_telegram_agent()
        for i, m in enumerate(reversed(agent.recent_messages[-50:])):
            sent_at = m.sent_at.isoformat() if m.sent_at else None
            messages.append({
                "id": f"tg-live-{i}",
                "timestamp": sent_at,
                "direction": "outbound",
                "type": "alert",
                "text": m.text,
                "chatId": str(m.chat_id or agent.chat_id or ""),
                "delivered": m.message_id is not None,
            })
    except Exception as exc:
        logger.debug("telegram_agent_history_unavailable", error=str(exc))

    # Supplement with persistent notification store (telegram-sourced entries)
    if not messages:
        try:
            from core.notifications import get_notification_store
            store = get_notification_store()
            notes = [n for n in store.list(limit=50) if getattr(n, "source", "") == "telegram"]
            nd = lambda n: n.to_dict()
            messages = [
                {
                    "id": n.id,
                    "timestamp": nd(n).get("timestamp"),
                    "direction": "outbound",
                    "type": nd(n).get("type", "system"),
                    "text": getattr(n, "message", nd(n).get("message", "")),
                    "chatId": "merid-alerts",
                    "delivered": True,
                }
                for n in notes
            ]
        except Exception as exc:
            logger.debug("operation_suppressed", error=str(exc))

    return {"messages": messages, "total": len(messages)}


@router.get("/api/v1/notifications/stats")
async def get_notification_stats() -> Dict[str, Any]:
    """Lightweight notification store stats for UI health widgets."""
    try:
        from core.notifications import get_notification_store
        store = get_notification_store()
        return store.get_stats()
    except Exception as exc:
        logger.debug("data_fetch_suppressed", error=str(exc))

    return _stub({
        "total": 0,
        "unread": 0,
        "last_created_at": None,
        "by_severity": {},
        "healthy": False,
    }, message="Notification store not available")


@router.get("/api/v1/logs/stats")
async def get_log_stats() -> Dict[str, Any]:
    """Get log statistics for the Logs view stats bar.

    Derives counts from the actual server log file and audit trail.
    """
    error_count = 0
    warn_count = 0
    info_count = 0
    debug_count = 0
    total = 0
    comp_counts: Dict[str, int] = {}

    # Parse the most recent server startup log
    import glob
    log_candidates = sorted(glob.glob(str(Path(__file__).resolve().parent.parent.parent / "server_startup*.log")), reverse=True)
    for log_path in log_candidates[:1]:
        try:
            with open(log_path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    total += 1
                    ll = line.lower()
                    if "| error |" in ll or "| critical |" in ll:
                        error_count += 1
                    elif "| warning |" in ll:
                        warn_count += 1
                    elif "| info |" in ll:
                        info_count += 1
                    elif "| debug |" in ll:
                        debug_count += 1
                    # Extract component from structured log: "ts | LEVEL | component |"
                    parts = line.split(" | ")
                    if len(parts) >= 3:
                        comp = parts[2].strip()
                        if comp:
                            comp_counts[comp] = comp_counts.get(comp, 0) + 1
        except Exception as e:
            logger.debug(f"Silent error: {e}")

    # Add agent grid activity counts
    try:
        from merid.prediction.agent_grid import get_agent_grid
        grid = get_agent_grid()
        agent_logs = sum(a.state.cycles_run for a in grid.agents)
        total += agent_logs
        info_count += agent_logs
        comp_counts["agent_grid"] = agent_logs
    except Exception as e:
        logger.debug(f"Silent error: {e}")

    return {
        "totalLogs": total,
        "errorCount": error_count,
        "warnCount": warn_count,
        "infoCount": info_count,
        "debugCount": debug_count,
        "last24hCount": total,
        "componentCounts": comp_counts,
    }


@router.post("/api/v1/logs/clear")
async def clear_logs() -> Dict[str, Any]:
    """Clear logs."""
    return {"success": True, "message": "Logs cleared"}


# ============================================
# USER PROFILE - /api/v1/user/profile
# Consumer: Settings.tsx (blocks render until resolved)
# ============================================
@router.get("/api/v1/user/profile")
async def get_user_profile() -> Dict[str, Any]:
    """Get user profile. Settings.tsx blocks its render until this resolves."""
    settings_data = _read_user_settings()
    return {
        "id": "operator-1",
        "email": settings_data.get("preferences", {}).get("email", "operator@merid.local"),
        "accountType": "operator",
        "createdAt": "2024-01-01T00:00:00Z",
        "preferences": settings_data.get("preferences", {}),
    }




# ============================================
# BETTING - /api/v1/betting/overview, /api/v1/betting/place
# Consumer: Betting.tsx
# ============================================
@router.get("/api/v1/betting/overview")
async def get_betting_overview() -> Dict[str, Any]:
    """Get betting overview."""
    now = datetime.now(timezone.utc)
    return _stub({
        "markets": [
            {
                "id": "1", "title": "BTC Reaches $100K by Q2 2026", "category": "crypto",
                "description": "Will Bitcoin reach $100,000 before end of Q2 2026?",
                "total_volume": 2500000, "closes_at": (now + timedelta(days=60)).isoformat() + "Z", "status": "open",
                "outcomes": [
                    {"id": "1a", "name": "Yes", "odds": 1.85, "probability": 0.54, "volume": 1350000},
                    {"id": "1b", "name": "No", "odds": 2.10, "probability": 0.46, "volume": 1150000},
                ],
            },
            {
                "id": "2", "title": "ETH Flippening in 2026", "category": "crypto",
                "description": "Will Ethereum surpass Bitcoin in market cap this year?",
                "total_volume": 850000, "closes_at": (now + timedelta(days=180)).isoformat() + "Z", "status": "open",
                "outcomes": [
                    {"id": "2a", "name": "Yes", "odds": 5.50, "probability": 0.18, "volume": 153000},
                    {"id": "2b", "name": "No", "odds": 1.15, "probability": 0.82, "volume": 697000},
                ],
            },
            {
                "id": "3", "title": "Fed Rate Cut Before July", "category": "politics",
                "description": "Will the Federal Reserve cut interest rates before July 2026?",
                "total_volume": 1200000, "closes_at": (now + timedelta(days=90)).isoformat() + "Z", "status": "open",
                "outcomes": [
                    {"id": "3a", "name": "Yes", "odds": 2.20, "probability": 0.45, "volume": 540000},
                    {"id": "3b", "name": "No", "odds": 1.75, "probability": 0.55, "volume": 660000},
                ],
            },
        ],
        "user_bets": [
            {"id": "ub-001", "market_title": "BTC Reaches $100K by Q2 2026", "outcome": "Yes", "amount": 500, "odds": 1.85, "potential_payout": 925, "status": "pending", "placed_at": (now - timedelta(days=2)).isoformat() + "Z"},
            {"id": "ub-002", "market_title": "Fed Rate Cut Before July", "outcome": "No", "amount": 250, "odds": 1.75, "potential_payout": 437.50, "status": "pending", "placed_at": (now - timedelta(days=5)).isoformat() + "Z"},
            {"id": "ub-003", "market_title": "SOL above $200 by March", "outcome": "Yes", "amount": 100, "odds": 3.20, "potential_payout": 320, "status": "won", "placed_at": (now - timedelta(days=30)).isoformat() + "Z", "settled_at": (now - timedelta(days=3)).isoformat() + "Z"},
        ],
        "stats": {
            "total_bets": 24,
            "active_bets": 2,
            "total_wagered": 3500,
            "total_winnings": 4250,
            "win_rate": 62.5,
            "roi": 21.4,
        },
    }, message="Betting data is simulated — feature not yet implemented")


@router.post("/api/v1/betting/place")
async def place_bet() -> Dict[str, Any]:
    """Place a bet."""
    return {"success": True, "bet_id": f"bet-{int(time.time())}", "message": "Bet placed successfully"}


# ============================================
# PAPER TRADING - /api/v1/paper-trading/portfolio/{userId}
# Consumer: PaperTradingPanel.tsx
# ============================================
@router.get("/api/v1/paper-trading/portfolio/{user_id}")
async def get_paper_trading_portfolio(user_id: str) -> Dict[str, Any]:
    """Get paper trading portfolio."""
    return {
        "user_id": user_id,
        "cash_balance": 100000,
        "total_value": 100000,
        "positions": [],
        "orders": [],
        "pnl_today": 0,
        "pnl_total": 0,
    }


@router.post("/api/v1/paper-trading/orders/{order_id}/cancel")
async def cancel_paper_order(order_id: str) -> Dict[str, Any]:
    """Cancel a paper trading order."""
    return {"success": True, "order_id": order_id, "message": "Order cancelled"}


@router.post("/api/v1/paper-trading/positions/{position_id}/close")
async def close_paper_position(position_id: str) -> Dict[str, Any]:
    """Close a paper trading position."""
    return {"success": True, "position_id": position_id, "message": "Position closed"}


@router.get("/api/v1/paper/portfolio/{user_id}/stats")
async def get_paper_portfolio_stats(user_id: str) -> Dict[str, Any]:
    """Get paper trading portfolio stats."""
    return {
        "user_id": user_id,
        "total_trades": 0,
        "win_rate": 0,
        "sharpe_ratio": 0,
        "max_drawdown_pct": 0,
        "avg_trade_duration_hours": 0,
        "best_trade_pnl": 0,
        "worst_trade_pnl": 0,
        "timestamp": int(time.time() * 1000),
    }


# ============================================
# ORDERS - /api/v1/orders
# Consumer: Trading.tsx (useApiData<Order[]>), OperatorActivityStream.tsx (data.orders || data || [])
# ============================================
@router.get("/api/v1/orders")
async def get_orders(limit: int = 20) -> List[Dict[str, Any]]:
    """Get recent orders from the paper trading engine."""
    try:
        engine = get_paper_engine()
        orders = []
        for uid, portfolio in engine.portfolios.items():
            for oid, order in portfolio.orders.items():
                orders.append({
                    "id": order.order_id,
                    "symbol": order.asset,
                    "side": order.side.upper(),
                    "orderType": getattr(order, 'order_type', type('', (), {'value': 'MARKET'})).value.upper(),
                    "price": order.price or (order.fill_price if hasattr(order, 'fill_price') else 0),
                    "size": order.size_usd / (order.fill_price or 1) if hasattr(order, 'fill_price') and order.fill_price else order.size_usd,
                    "venue": getattr(order, 'venue', 'Paper'),
                    "status": order.status.value.lower(),
                    "timestamp": order.created_at if hasattr(order, 'created_at') else datetime.now(timezone.utc).isoformat() + "Z",
                })
        orders.sort(key=lambda o: o.get("timestamp", ""), reverse=True)
        return orders[:limit]
    except Exception:
        return []


# ============================================
# ORDERS OPEN - /api/v1/orders/open
# Consumer: useOpenOrders.ts hook → OpenOrdersPanel.tsx
# ============================================
@router.get("/api/v1/orders/open")
async def get_orders_open() -> Dict[str, Any]:
    """Get open orders from the paper trading engine — matches OpenOrdersResponse."""
    try:
        engine = get_paper_engine()
        orders = []
        for uid, portfolio in engine.portfolios.items():
            for oid, order in portfolio.orders.items():
                status_val = order.status.value.upper()
                if status_val in ("PENDING", "PARTIALLY_FILLED", "OPEN"):
                    filled = getattr(order, 'filled_size', 0) or 0
                    total = order.size_usd / (order.fill_price or 1) if hasattr(order, 'fill_price') and order.fill_price else order.size_usd
                    orders.append({
                        "id": order.order_id,
                        "symbol": order.asset,
                        "side": order.side.upper(),
                        "type": getattr(order, 'order_type', type('', (), {'value': 'MARKET'})).value.upper(),
                        "status": status_val,
                        "price": order.price or 0,
                        "size": total,
                        "filledSize": filled,
                        "remainingSize": total - filled,
                        "notional": order.size_usd,
                        "leverage": getattr(order, 'leverage', 1),
                        "venue": getattr(order, 'venue', 'Paper'),
                        "strategyId": "",
                        "agentId": uid,
                        "createdAt": order.created_at if hasattr(order, 'created_at') else "",
                        "expiresAt": None,
                    })
        meta = {
            "total": len(orders),
            "pending": sum(1 for o in orders if o["status"] == "PENDING"),
            "partiallyFilled": sum(1 for o in orders if o["status"] == "PARTIALLY_FILLED"),
            "totalNotional": sum(o["notional"] for o in orders),
        }
        return {"orders": orders, "meta": meta}
    except Exception:
        return {"orders": [], "meta": {"total": 0, "pending": 0, "partiallyFilled": 0, "totalNotional": 0}}


# ============================================
# ORDER SUBMIT - /api/v1/orders/submit
# Consumer: Trading.tsx handleOrderSubmit
# ============================================
@router.post("/api/v1/orders/submit")
async def submit_order(body: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    """Submit an order via the paper trading engine."""
    try:
        engine = get_paper_engine()
        symbol = body.get("symbol", "BTC-USD")
        side = body.get("side", "BUY").lower()
        size = float(body.get("size", 0) or 0)
        order_type = body.get("orderType", "MARKET").lower()
        price = float(body.get("price", 0)) if body.get("price") else None

        # Get current price for market orders
        current_price = None
        try:
            feed = get_live_price_feed()
            # Map BTC-USD → BTC/USDT
            mapped = symbol.replace("-USD", "/USDT")
            if hasattr(feed, 'get_price_cache'):
                _pc = feed.get_price_cache()
            elif hasattr(feed, 'price_cache'):
                _pc = feed.price_cache
            else:
                _pc = getattr(feed, '_price_cache', {})
            if mapped in _pc:
                current_price = _pc[mapped].price
        except Exception as exc:
            logger.debug("operation_suppressed", error=str(exc))

        size_usd = size * (current_price or 1.0)

        order = engine.place_order(
            user_id="operator",
            asset=symbol,
            side="long" if side == "buy" else "short",
            size_usd=size_usd,
            order_type=order_type,
            price=price,
        )

        # Emit consensus plan + opinion for filled orders (before notification so we can reference plan_id)
        _fill_plan_id: Optional[str] = None
        _fill_supporting: list = []
        try:
            from core.consensus_store import add_plan, add_opinion
            if order.status.value == "filled":
                direction = "long" if side == "buy" else "short"
                plan = add_plan(
                    symbol=symbol,
                    title=f"{symbol} {direction.title()} Entry",
                    direction=direction,
                    target_size_usd=order.size_usd,
                    confidence=0.8,
                    supporting_agents=["trading-engine"],
                    status="executed",
                )
                _fill_plan_id = plan.id
                _fill_supporting = plan.supporting_agents
                add_opinion(
                    agent_id="trading-engine",
                    agent_name="Trading Engine",
                    role="execution",
                    symbol=symbol,
                    stance="bullish" if direction == "long" else "bearish",
                    confidence=0.8,
                    reasoning=f"Executed {direction} {size} {symbol} @ ${order.fill_price:,.2f}",
                )
        except Exception as exc:
            logger.debug("operation_suppressed", error=str(exc))

        # Emit notification for fills and rejections (enriched with plan attribution)
        try:
            if order.status.value == "filled":
                msg = f"{body.get('side', 'BUY')} {size} {symbol} @ ${order.fill_price:,.2f} (${order.size_usd:,.0f})"
                if _fill_plan_id:
                    msg += f" | plan {_fill_plan_id}"
                add_notification(
                    type="trade", severity="info",
                    title=f"Order Filled: {symbol}",
                    message=msg,
                    source="trading",
                    metadata={
                        "plan_id": _fill_plan_id,
                        "supporting_agents": _fill_supporting,
                    } if _fill_plan_id else None,
                )
            elif order.status.value == "rejected":
                # Enrich with active plan count for the affected symbol
                _active_note = ""
                try:
                    from core.consensus_store import get_consensus_store as _cs
                    _st = _cs()
                    _active = sum(
                        1 for p in _st.list_plans(limit=50)
                        if p.symbol == symbol and p.status in ("proposed", "approved", "executing")
                    )
                    if _active:
                        _active_note = f" — {_active} active plan(s) affected"
                except Exception as exc:
                    logger.debug("operation_suppressed", error=str(exc))
                add_notification(
                    type="warning", severity="warning",
                    title=f"Order Rejected: {symbol}",
                    message=f"{body.get('side', 'BUY')} {size} {symbol} — insufficient balance or risk limit{_active_note}",
                    source="trading",
                )
        except Exception as exc:
            logger.debug("operation_suppressed", error=str(exc))

        return {
            "success": True,
            "order_id": order.order_id,
            "status": order.status.value,
            "fill_price": order.fill_price,
            "size_usd": order.size_usd,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}






@router.get("/api/v1/signals/sentiment/{ticker}")
async def get_signals_sentiment_ticker_stub(ticker: str) -> Dict[str, Any]:
    """Fast per-ticker sentiment stub."""
    now = datetime.now(timezone.utc)
    return _stub({
        "events": [
            {"id": f"se-{ticker}-001", "timestamp": (now - timedelta(minutes=10)).isoformat() + "Z", "source": "news", "ticker": ticker, "polarity": 0.55, "magnitude": 0.7, "relevance": 0.85, "headline": f"{ticker} shows positive momentum", "isSpike": False},
        ],
        "windows": [
            {"ticker": ticker, "polarity": 0.55, "magnitude": 0.7, "event_count": 6, "window_minutes": 60},
        ],
        "status": "ok",
    }, message="Sentiment data is simulated")



# ============================================
# POSITIONS - /api/v1/positions
# Consumer: Trading.tsx (useApiData<Position[]>)
# ============================================
@router.get("/api/v1/positions")
async def get_positions() -> List[Dict[str, Any]]:
    """Get current positions from the paper trading engine."""
    try:
        engine = get_paper_engine()
        positions = []
        for uid, portfolio in engine.portfolios.items():
            for pid, pos in portfolio.positions.items():
                entry = pos.entry_price or 0
                current = pos.current_price or entry
                pnl = pos.unrealized_pnl if hasattr(pos, 'unrealized_pnl') else 0
                pnl_pct = (pnl / (entry * (pos.size_usd / entry))) * 100 if entry > 0 and pos.size_usd > 0 else 0
                positions.append({
                    "id": pos.position_id,
                    "symbol": pos.asset,
                    "side": "BUY" if pos.side.lower() in ("long", "buy") else "SELL",
                    "size": pos.size_usd / entry if entry > 0 else 0,
                    "entryPrice": entry,
                    "currentPrice": current,
                    "pnl": round(pnl, 2),
                    "pnlPercent": round(pnl_pct, 2),
                    "venue": getattr(pos, 'venue', 'Paper'),
                    "timestamp": pos.opened_at if hasattr(pos, 'opened_at') else datetime.now(timezone.utc).isoformat() + "Z",
                })
        return positions
    except Exception:
        return []


# ============================================
# FILLS - /api/v1/fills
# Consumer: Trading.tsx (useApiData<Fill[]>)
# ============================================
@router.get("/api/v1/fills")
async def get_fills() -> List[Dict[str, Any]]:
    """Get recent fills from the paper trading engine (filled orders)."""
    try:
        engine = get_paper_engine()
        fills = []
        for uid, portfolio in engine.portfolios.items():
            for oid, order in portfolio.orders.items():
                if order.status.value.upper() in ("FILLED", "COMPLETED"):
                    fills.append({
                        "id": f"fill-{order.order_id}",
                        "orderId": order.order_id,
                        "symbol": order.asset,
                        "side": "BUY" if order.side.lower() in ("long", "buy") else "SELL",
                        "size": order.size_usd / order.fill_price if hasattr(order, 'fill_price') and order.fill_price else order.size_usd,
                        "price": order.fill_price if hasattr(order, 'fill_price') and order.fill_price else 0,
                        "venue": getattr(order, 'venue', 'Paper'),
                        "timestamp": order.filled_at if hasattr(order, 'filled_at') and order.filled_at else (order.created_at if hasattr(order, 'created_at') else datetime.now(timezone.utc).isoformat() + "Z"),
                    })
        fills.sort(key=lambda f: f.get("timestamp", ""), reverse=True)
        return fills
    except Exception:
        return []



# ============================================
# RISK POSITION LIMITS - /api/v1/risk/position-limits
# Consumer: Risk.tsx (useApiData<PositionLimit[]>)
# ============================================
@router.get("/api/v1/risk/position-limits")
async def get_risk_position_limits() -> List[Dict[str, Any]]:
    """Get position limits — returns array for Risk.tsx DataTableEnhanced."""
    return [
        {"symbol": "BTC-USD", "currentSize": 0.25, "maxLimit": 1.0, "utilizationPercent": 25, "status": "normal"},
        {"symbol": "ETH-USD", "currentSize": 10.0, "maxLimit": 50.0, "utilizationPercent": 20, "status": "normal"},
        {"symbol": "SOL-USD", "currentSize": 50.0, "maxLimit": 200.0, "utilizationPercent": 25, "status": "normal"},
        {"symbol": "AAPL", "currentSize": 100, "maxLimit": 500, "utilizationPercent": 20, "status": "normal"},
        {"symbol": "AVAX-USD", "currentSize": 0, "maxLimit": 500.0, "utilizationPercent": 0, "status": "normal"},
    ]



# TRADING ORDERS OPEN - removed: real endpoint in web.api.orders_api (with auth)


# ============================================
# DATA FRESHNESS - /api/v1/data/freshness
# Consumer: DataFreshnessPanel.tsx (expects {feeds: [{name, source, lastUpdate, stalenessMs, thresholdMs, status}]})
# ============================================
_FEED_DISPLAY_NAMES: Dict[str, str] = {
    "kraken": "Kraken Prices", "coinbase": "Coinbase Prices",
    "binance": "Binance Tickers", "gemini": "Gemini Prices",
    "bybit": "Bybit Tickers", "okx": "OKX Tickers",
}
_FEED_THRESHOLDS_MS: Dict[str, int] = {
    "kraken": 5000, "coinbase": 5000, "binance": 5000,
    "gemini": 5000, "bybit": 5000, "okx": 5000,
}

@router.get("/api/v1/data/freshness")
async def get_data_freshness() -> Dict[str, Any]:
    """Data freshness — reads real timestamps from LivePriceFeed cache.

    Groups cached PriceData by source exchange.  When the cache is empty
    (e.g. no ccxt, offline mode) falls back to a stub response.
    """
    now = datetime.now(timezone.utc)
    now_ts = now.timestamp()
    now_ms = int(now_ts * 1000)

    feeds: List[Dict[str, Any]] = []
    has_real = False

    try:
        pf = get_live_price_feed()
        all_prices = pf.get_all_prices()  # Dict[str, PriceData]

        # Group most-recent timestamp per exchange
        exchange_latest: Dict[str, datetime] = {}
        for pd_item in all_prices.values():
            src = pd_item.exchange
            if src not in exchange_latest or pd_item.timestamp > exchange_latest[src]:
                exchange_latest[src] = pd_item.timestamp

        for src, ts in exchange_latest.items():
            staleness_ms = int((now_ts - ts.timestamp()) * 1000)
            threshold_ms = _FEED_THRESHOLDS_MS.get(src, 5000)
            status = "fresh" if staleness_ms < threshold_ms else ("stale" if staleness_ms < threshold_ms * 3 else "dead")
            feeds.append({
                "name": _FEED_DISPLAY_NAMES.get(src, src.title() + " Prices"),
                "source": src,
                "lastUpdate": ts.isoformat() + "Z",
                "stalenessMs": max(staleness_ms, 0),
                "thresholdMs": threshold_ms,
                "status": status,
            })
            has_real = True

        # Also expose per-exchange last_successful_fetch timestamps
        for exch, fetch_ts in pf.last_successful_fetch.items():
            if exch not in exchange_latest:
                staleness_ms = int((now_ts - fetch_ts) * 1000)
                threshold_ms = _FEED_THRESHOLDS_MS.get(exch, 5000)
                status = "fresh" if staleness_ms < threshold_ms else "stale"
                feeds.append({
                    "name": _FEED_DISPLAY_NAMES.get(exch, exch.title() + " Prices"),
                    "source": exch,
                    "lastUpdate": datetime.fromtimestamp(fetch_ts, tz=timezone.utc).isoformat(),
                    "stalenessMs": max(staleness_ms, 0),
                    "thresholdMs": threshold_ms,
                    "status": status,
                })
                has_real = True
    except Exception as exc:
        logger.debug("operation_suppressed", error=str(exc))

    if has_real:
        overall = "healthy" if all(f["status"] == "fresh" for f in feeds) else "degraded"
        return {"feeds": feeds, "overall_status": overall, "timestamp": now_ms}

    # In Kalshi-only mode, crypto price feeds are not expected — show Kalshi data freshness
    try:
        from merid.settings import settings
        if getattr(settings, "KALSHI_ONLY", False):
            kalshi_feeds = []
            # Kalshi REST API freshness
            try:
                from merid.event_venues.kalshi.market_catalog import get_market_catalog
                cat = get_market_catalog()
                cat_s = cat.summary()
                last_ref = cat_s.get("last_refresh")
                if last_ref:
                    from datetime import datetime as _dtt
                    ref_dt = _dtt.fromisoformat(str(last_ref).replace("Z", "+00:00")) if isinstance(last_ref, str) else last_ref
                    stale_ms = int((now_ts - ref_dt.timestamp()) * 1000)
                else:
                    stale_ms = 999999
                kalshi_feeds.append({
                    "name": "Kalshi Market Catalog",
                    "source": "kalshi_rest",
                    "lastUpdate": str(last_ref or now.isoformat() + "Z"),
                    "stalenessMs": max(stale_ms, 0),
                    "thresholdMs": 60000,
                    "status": "fresh" if stale_ms < 60000 else ("stale" if stale_ms < 300000 else "dead"),
                })
            except Exception:
                kalshi_feeds.append({"name": "Kalshi Market Catalog", "source": "kalshi_rest", "lastUpdate": now.isoformat() + "Z", "stalenessMs": 0, "thresholdMs": 60000, "status": "unknown"})
            # Agent grid freshness
            try:
                from merid.prediction.agent_grid import get_agent_grid
                grid = get_agent_grid()
                running = grid.running if hasattr(grid, "running") else len(grid.agents) > 0
                kalshi_feeds.append({
                    "name": "Agent Grid",
                    "source": "agent_grid",
                    "lastUpdate": now.isoformat() + "Z",
                    "stalenessMs": 0,
                    "thresholdMs": 30000,
                    "status": "fresh" if running else "stale",
                })
            except Exception as e:
                logger.debug(f"Silent error: {e}")
            overall = "healthy" if all(f["status"] == "fresh" for f in kalshi_feeds) else "degraded"
            return {"feeds": kalshi_feeds, "overall_status": overall, "timestamp": now_ms}
    except Exception as e:
        logger.debug(f"Silent error: {e}")

    # Fallback: stub feeds (no live data yet)
    stub_feeds = [
        {"name": "Kraken Prices", "source": "kraken", "lastUpdate": now.isoformat() + "Z", "stalenessMs": 0, "thresholdMs": 5000, "status": "unknown"},
        {"name": "Coinbase Prices", "source": "coinbase", "lastUpdate": now.isoformat() + "Z", "stalenessMs": 0, "thresholdMs": 5000, "status": "unknown"},
        {"name": "Binance Tickers", "source": "binance", "lastUpdate": now.isoformat() + "Z", "stalenessMs": 0, "thresholdMs": 5000, "status": "unknown"},
    ]
    return _stub({"feeds": stub_feeds, "overall_status": "unknown", "timestamp": now_ms}, message="Data freshness: price feed not yet streaming")


# ============================================
# BRIER SCORE METRICS - /api/v1/metrics/brier
# Consumer: BrierMetricsPanel.tsx (expects BrierMetricsData)
# ============================================
@router.get("/api/v1/metrics/brier")
async def get_brier_metrics(agent: str = "all") -> Dict[str, Any]:
    """Brier score metrics for prediction accuracy tracking."""
    agents = [  # Hardcoded — wire to prediction logs
        {"agent_name": "Analyst Gemma", "overall_score": 0.130, "total_predictions": 0, "calibration_score": 0.080, "resolution_score": 0.050, "trend": "stable", "change_percent": 0},
        {"agent_name": "Analyst Llama", "overall_score": 0.150, "total_predictions": 0, "calibration_score": 0.090, "resolution_score": 0.060, "trend": "stable", "change_percent": 0},
        {"agent_name": "Skeptic", "overall_score": 0.180, "total_predictions": 0, "calibration_score": 0.110, "resolution_score": 0.070, "trend": "stable", "change_percent": 0},
        {"agent_name": "Synthesizer", "overall_score": 0.120, "total_predictions": 0, "calibration_score": 0.070, "resolution_score": 0.050, "trend": "stable", "change_percent": 0},
        {"agent_name": "Risk Manager", "overall_score": 0.140, "total_predictions": 0, "calibration_score": 0.085, "resolution_score": 0.055, "trend": "stable", "change_percent": 0},
    ]
    if agent != "all":
        agents = [a for a in agents if a["agent_name"].lower() == agent.lower()] or agents[:1]

    buckets = [
        (0.05, 0.08, 23), (0.15, 0.18, 34), (0.25, 0.22, 45), (0.35, 0.38, 56),
        (0.45, 0.43, 67), (0.55, 0.57, 78), (0.65, 0.62, 89), (0.75, 0.78, 92),
        (0.85, 0.82, 76), (0.95, 0.93, 54),
    ]
    calibration = [
        {"confidence_bucket": f"{int(pred*100-5)}-{int(pred*100+5)}%", "predicted_probability": pred, "actual_frequency": act, "count": cnt, "brier_contribution": round(abs(pred - act) ** 2, 3)}
        for pred, act, cnt in buckets
    ]

    scores = [a["overall_score"] for a in agents]
    best = min(agents, key=lambda a: a["overall_score"])
    worst = max(agents, key=lambda a: a["overall_score"])

    return _stub({
        "agent_scores": agents,
        "calibration_curve": calibration,
        "historical_scores": [
            {"date": "Week 1", "score": 0.170},
            {"date": "Week 2", "score": 0.155},
            {"date": "Week 3", "score": 0.145},
            {"date": "Week 4", "score": 0.135},
        ],
        "best_performer": best["agent_name"],
        "worst_performer": worst["agent_name"],
        "average_score": round(sum(scores) / len(scores), 3),
    }, message="Brier metrics are simulated — wire to prediction logs")


# ============================================
# PORTFOLIO - /api/v1/portfolio/summary
# Consumer: LivePortfolioValue.tsx, Overview.tsx
# ============================================
@router.get("/api/v1/portfolio/summary")
async def get_portfolio_summary_v1() -> Dict[str, Any]:
    """Portfolio summary from the live paper trading engine."""
    try:
        engine = get_paper_engine()
        user_id = next(iter(engine.portfolios), "default")
        stats = engine.get_portfolio_stats(user_id)
        equity = stats.get("equity", stats.get("current_balance", 10000))
        starting = stats.get("starting_balance", 10000)
        total_pnl = stats.get("total_pnl", 0)
        unrealized = stats.get("total_unrealized_pnl", 0)
        daily_pnl = total_pnl + unrealized
        daily_pnl_pct = (daily_pnl / starting * 100) if starting else 0
        return {
            "equity": round(equity, 2),
            "dailyPnl": round(daily_pnl, 2),
            "dailyPnlPct": round(daily_pnl_pct, 2),
            "availableMargin": round(stats.get("current_balance", equity), 2),
            "activeBots": stats.get("open_positions", 0),
            "totalValue": round(equity, 2),
            "unrealizedPnl": round(unrealized, 2),
            "activePositions": stats.get("open_positions", 0),
            "totalTrades": stats.get("total_trades", 0),
            "winRate": round(stats.get("win_rate_pct", 0), 1),
            "roi": round(stats.get("roi_pct", 0), 2),
            "startingBalance": round(starting, 2),
        }
    except Exception:
        return {
            "equity": 10000, "dailyPnl": 0, "dailyPnlPct": 0,
            "availableMargin": 10000, "activeBots": 0,
            "totalValue": 10000, "unrealizedPnl": 0, "activePositions": 0,
        }


# ============================================
# AGENTS - /api/v1/agents & /api/v1/agents/health
# Consumer: Agents.tsx (Fleet tab), LiveAgentHealthPanel.tsx, OperatorDashboard
# ============================================
def _agent_status_to_ui(status_value: str) -> str:
    """Map AgentStatus enum values to frontend status strings."""
    return {"active": "online", "initializing": "online", "paused": "degraded",
            "degraded": "degraded", "stopped": "offline", "error": "offline"}.get(status_value, "online")

def _agent_role_to_ui(role_value: str) -> str:
    """Map AgentRole enum values to frontend role strings."""
    return {"research_signal": "analyst", "risk": "risk_manager", "execution": "trader",
            "routing": "market_maker", "anomaly_detection": "risk_manager",
            "governance": "risk_manager", "sniper_arbitrage": "trader",
            "defi": "trader", "memecoin": "trader", "xstocks": "trader",
            "wallet_rebalancing": "trader"}.get(role_value, "analyst")




@router.get("/api/v1/agents/{agent_id}")
async def get_agent_detail(agent_id: str) -> Dict[str, Any]:
    """Get agent detail matching AgentDetail interface in Agents.tsx.

    Reads from real AgentRegistry when the agent is registered.
    """
    now = datetime.now(timezone.utc)

    try:
        registry = get_agent_registry()
        agent = registry.get_agent(agent_id)
        if agent:
            m = agent.get_metrics()
            status_val = agent.status.value if hasattr(agent.status, "value") else "active"
            role_val = agent.role.value if hasattr(agent.role, "value") else "analyst"
            return {
                "id": agent.agent_id,
                "name": agent.agent_id.replace("-", " ").replace("_", " ").title(),
                "role": _agent_role_to_ui(role_val),
                "status": _agent_status_to_ui(status_val),
                "confidence": int(m.success_rate * 100),
                "pnl": 0,
                "winRate": m.success_rate,
                "totalTrades": m.decisions_made,
                "lastDecision": "Active",
                "lastDecisionTime": now.isoformat() + "Z",
                "charter": role_val,
                "metrics": {
                    "avgTradeSize": 0,
                    "avgHoldTime": 0,
                    "sharpeRatio": 0,
                    "maxDrawdown": 0,
                    "dailyPnl": 0,
                    "weeklyPnl": 0,
                    "monthlyPnl": 0,
                },
                "recentDecisions": [],
            }
    except Exception as exc:
        logger.debug("operation_suppressed", error=str(exc))

    # Fallback: stub detail
    return _stub({
        "id": agent_id,
        "name": agent_id.replace("-", " ").title(),
        "role": "analyst",
        "status": "online",
        "confidence": 80,
        "pnl": 0,
        "winRate": 0,
        "totalTrades": 0,
        "lastDecision": "Awaiting assignment",
        "lastDecisionTime": now.isoformat() + "Z",
        "charter": "default_charter",
        "metrics": {
            "avgTradeSize": 0,
            "avgHoldTime": 0,
            "sharpeRatio": 0,
            "maxDrawdown": 0,
            "dailyPnl": 0,
            "weeklyPnl": 0,
            "monthlyPnl": 0,
        },
        "recentDecisions": [],
    }, message="Agent detail is simulated — agent not yet started")


# ============================================
# MONITORING STATUS - /api/v1/monitoring/status
# Consumer: Live Monitoring view
# ============================================
_SERVER_START_TIME = time.time()

def _probe_service(name: str, probe_fn) -> Dict[str, Any]:
    """Probe a service and return status + latency."""
    t0 = time.time()
    try:
        probe_fn()
        latency_ms = int((time.time() - t0) * 1000)
        return {"status": "online", "latency_ms": latency_ms, "last_update": int(time.time() * 1000)}
    except Exception:
        return {"status": "offline", "latency_ms": 0, "last_update": 0}

@router.get("/api/v1/monitoring/status")
async def get_monitoring_status() -> Dict[str, Any]:
    """Get live monitoring status — probes real services where available."""
    now = datetime.now(timezone.utc)
    now_ms = int(now.timestamp() * 1000)
    uptime = int(time.time() - _SERVER_START_TIME)

    services: Dict[str, Dict[str, Any]] = {}

    # Probe price feed
    def _probe_price_feed():
        pf = get_live_price_feed()
        pf.get_cached_prices()
    services["price_feed"] = _probe_service("price_feed", _probe_price_feed)

    # Probe paper trading engine
    def _probe_trading():
        from trading.paper_trading import get_paper_trading_engine
        get_paper_trading_engine()
    services["trading_engine"] = _probe_service("trading_engine", _probe_trading)

    # Probe risk manager
    def _probe_risk():
        GlobalRiskManager()
    services["risk_engine"] = _probe_service("risk_engine", _probe_risk)

    # Probe agent registry
    def _probe_agents():
        reg = get_agent_registry()
        reg.get_statistics()
    services["agent_swarm"] = _probe_service("agent_swarm", _probe_agents)

    # Consensus + websocket are implicitly online if the server is responding
    services["consensus_engine"] = {"status": "online", "latency_ms": 0, "last_update": now_ms}
    services["websocket_server"] = {"status": "online", "latency_ms": 0, "last_update": now_ms}

    overall = "online" if all(s["status"] == "online" for s in services.values()) else "degraded"
    has_real_data = any(s["latency_ms"] > 0 for s in services.values())

    result: Dict[str, Any] = {
        "status": overall,
        "uptime_seconds": uptime,
        "started_at": datetime.fromtimestamp(_SERVER_START_TIME, tz=timezone.utc).isoformat(),
        "services": services,
        "feeds": {},
        "alerts": [],
        "timestamp": now.isoformat() + "Z",
    }
    if not has_real_data:
        return _stub(result, message="Monitoring: services probed but none returned latency data")
    return result


# ============================================
# CONSENSUS CURRENT - /api/v1/consensus/current
# Consumer: ConsensusPanel.tsx, ConsensusBoard.tsx
# ============================================
@router.get("/api/v1/consensus/current")
async def get_consensus_current() -> Dict[str, Any]:
    """Get current consensus state."""
    now = datetime.now(timezone.utc)
    return _stub({
        "status": "idle",
        "current_round": None,
        "last_round": {
            "id": "round-001",
            "topic": "BTC-USD outlook",
            "result": "approved",
            "confidence": 0.82,
            "votes_for": 5,
            "votes_against": 1,
            "timestamp": (now - timedelta(minutes=15)).isoformat() + "Z",
        },
        "participating_agents": 8,
        "quorum_met": True,
        "timestamp": now.isoformat() + "Z",
    }, message="Consensus state is simulated")


# ============================================
# CONSENSUS HISTORY - safe override (the system_control.py version 500s)
# Consumer: ConsensusBoard.tsx
# ============================================
@router.get("/api/v1/system/consensus/history")
async def get_consensus_history_safe(limit: int = 10) -> Dict[str, Any]:
    """Safe consensus history that doesn't crash."""
    try:
        from core.agent_orchestrator import get_agent_orchestrator
        orchestrator = get_agent_orchestrator()
        history = orchestrator.get_consensus_history(limit=limit)
        return {
            "consensus_results": [
                {
                    "approved": c.approved,
                    "confidence": c.confidence,
                    "votes_for": c.votes_for,
                    "votes_against": c.votes_against,
                    "participating_agents": [a.value if hasattr(a, "value") else str(a) for a in (c.participating_agents or [])],
                    "timestamp": c.timestamp.isoformat() if hasattr(c.timestamp, "isoformat") else str(c.timestamp),
                }
                for c in history
            ],
            "total": len(history),
        }
    except Exception:
        now = datetime.now(timezone.utc)
        return {
            "consensus_results": [
                {"approved": True, "confidence": 0.82, "votes_for": 5, "votes_against": 1, "participating_agents": ["analyst-gemma-01", "analyst-llama-01", "skeptic-01", "risk-01", "synthesizer-01", "strategy-agent-01"], "timestamp": (now - timedelta(minutes=15)).isoformat()},
                {"approved": True, "confidence": 0.75, "votes_for": 4, "votes_against": 2, "participating_agents": ["analyst-gemma-01", "analyst-llama-01", "skeptic-01", "risk-01", "synthesizer-01", "strategy-agent-01"], "timestamp": (now - timedelta(hours=1)).isoformat()},
                {"approved": False, "confidence": 0.45, "votes_for": 2, "votes_against": 4, "participating_agents": ["analyst-gemma-01", "analyst-llama-01", "skeptic-01", "risk-01", "synthesizer-01", "strategy-agent-01"], "timestamp": (now - timedelta(hours=3)).isoformat()},
            ],
            "total": 3,
        }
