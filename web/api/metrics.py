"""
Metrics API — aggregated endpoints for dashboard charts and widgets.

Provides:
- GET /api/metrics/swarm_health — agents, queue depth, error rate, latency
- GET /api/metrics/heatmap — hierarchical sector → instrument → metrics
- GET /api/metrics/radar — instrument scanner with PnL, vol, signal, sector
- GET /api/metrics/latency — backend endpoint timing percentiles
- GET /api/metrics/breach_log — recent risk breaches with rule/action detail
"""

from __future__ import annotations

import time
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from utils.logger import get_logger

logger = get_logger("web.api.metrics")

router = APIRouter(prefix="/api/metrics", tags=["metrics"])


# ── Latency tracking ring buffer ──────────────────────────────────────

_latency_samples: List[Dict[str, Any]] = []
_LATENCY_BUFFER_MAX = 500


def record_latency(endpoint: str, duration_ms: float) -> None:
    """Record an endpoint latency sample (called from middleware)."""
    _latency_samples.append({
        "ts": time.time(),
        "endpoint": endpoint,
        "ms": round(duration_ms, 2),
    })
    if len(_latency_samples) > _LATENCY_BUFFER_MAX:
        del _latency_samples[: len(_latency_samples) - _LATENCY_BUFFER_MAX]


# ── Breach log ring buffer ────────────────────────────────────────────

_breach_log: List[Dict[str, Any]] = []
_BREACH_LOG_MAX = 200


def record_breach(
    rule: str,
    instrument: str,
    value: float,
    threshold: float,
    action: str,
    severity: str = "WARNING",
) -> None:
    """Record a risk breach event."""
    _breach_log.append({
        "ts": datetime.utcnow().isoformat(),
        "rule": rule,
        "instrument": instrument,
        "value": round(value, 4),
        "threshold": round(threshold, 4),
        "action": action,
        "severity": severity,
    })
    if len(_breach_log) > _BREACH_LOG_MAX:
        del _breach_log[: len(_breach_log) - _BREACH_LOG_MAX]


# ── Endpoints ─────────────────────────────────────────────────────────

@router.get("/swarm_health")
async def get_swarm_health() -> Dict[str, Any]:
    """
    Aggregated swarm health for dashboard widgets.

    Returns agent counts, queue depth, error rate, and decision latency stats.
    """
    result: Dict[str, Any] = {}

    # Agent & task stats
    try:
        from web.api.dev_swarm_routes import get_swarm
        swarm = await get_swarm()
        completed = sum(1 for t in swarm.task_history if t.status == "completed")
        failed = sum(1 for t in swarm.task_history if t.status == "failed")
        total = len(swarm.task_history)
        result["agents"] = {
            "total": len(swarm.agents),
            "online": sum(1 for a in swarm.agents if getattr(a, "status", "online") == "online"),
            "degraded": sum(1 for a in swarm.agents if getattr(a, "status", "online") == "degraded"),
            "offline": sum(1 for a in swarm.agents if getattr(a, "status", "online") == "offline"),
        }
        result["tasks"] = {
            "active": len(swarm.active_tasks),
            "queued": len(getattr(swarm, "task_queue", [])),
            "completed": completed,
            "failed": failed,
            "total": total,
        }
        result["error_rate"] = round(failed / total * 100, 2) if total else 0.0
        result["paused"] = swarm.is_paused
    except Exception as exc:
        logger.warning("swarm_health_swarm_error", error=str(exc))
        result["agents"] = {"total": 0, "online": 0, "degraded": 0, "offline": 0}
        result["tasks"] = {"active": 0, "queued": 0, "completed": 0, "failed": 0, "total": 0}
        result["error_rate"] = 0.0
        result["paused"] = False

    # Decision latency from recent samples
    now = time.time()
    recent = [s for s in _latency_samples if now - s["ts"] < 300]  # last 5 min
    if recent:
        ms_vals = sorted(s["ms"] for s in recent)
        result["latency"] = {
            "p50_ms": round(ms_vals[len(ms_vals) // 2], 1),
            "p95_ms": round(ms_vals[int(len(ms_vals) * 0.95)], 1),
            "p99_ms": round(ms_vals[int(len(ms_vals) * 0.99)], 1),
            "samples": len(ms_vals),
        }
    else:
        result["latency"] = {"p50_ms": 0, "p95_ms": 0, "p99_ms": 0, "samples": 0}

    # System resources
    try:
        import psutil
        result["system"] = {
            "cpu_percent": psutil.cpu_percent(interval=0),
            "memory_percent": psutil.virtual_memory().percent,
        }
    except Exception:
        result["system"] = {"cpu_percent": 0, "memory_percent": 0}

    return result


@router.get("/heatmap")
async def get_heatmap() -> Dict[str, Any]:
    """
    Hierarchical heatmap data: sector → instrument → {pnl, exposure, risk_pct}.

    Tile size should map to exposure, color to PnL or risk utilization.
    Uses dxFeed adapter for market quotes and paper engine for positions.
    """
    sectors: Dict[str, List[Dict[str, Any]]] = {}

    try:
        from core.market_heatmap import build_heatmap_snapshot
        from core.market_data_dxfeed import get_dxfeed_adapter
        from trading.paper_trading import get_paper_engine

        adapter = get_dxfeed_adapter()
        engine = get_paper_engine()

        # Get market quotes from dxFeed adapter
        ticks = adapter.get_watchlist()
        quotes = [t.to_dict() for t in ticks]

        # Get positions from paper engine
        positions: List[Dict[str, Any]] = []
        for _uid, portfolio in engine.portfolios.items():
            for _pk, pos in portfolio.positions.items():
                symbol = pos.asset.replace("/USDT", "").replace("USDT", "")
                pnl = engine._calculate_position_pnl(pos)
                exposure = abs(pos.size_usd) if hasattr(pos, "size_usd") else 0
                positions.append({
                    "symbol": symbol,
                    "pnl": pnl,
                    "exposure": exposure,
                    "side": pos.side,
                })

        sectors = build_heatmap_snapshot(quotes, positions)
    except Exception as exc:
        logger.warning("heatmap_data_error", error=str(exc))

    # If no real data, provide sample data for UI development
    if not sectors:
        sectors = {
            "Crypto Major": [
                {"symbol": "BTC", "pnl": 0, "exposure": 0, "side": "long", "risk_pct": 0, "change_pct": 0},
                {"symbol": "ETH", "pnl": 0, "exposure": 0, "side": "long", "risk_pct": 0, "change_pct": 0},
            ],
            "Crypto L1": [
                {"symbol": "SOL", "pnl": 0, "exposure": 0, "side": "long", "risk_pct": 0, "change_pct": 0},
                {"symbol": "AVAX", "pnl": 0, "exposure": 0, "side": "long", "risk_pct": 0, "change_pct": 0},
            ],
        }

    return {
        "sectors": dict(sectors),
        "sector_count": len(sectors),
        "instrument_count": sum(len(v) for v in sectors.values()),
    }


@router.get("/radar")
async def get_radar(
    category: str = Query(default="all", pattern="^(all|core|onchain|perps|defi|meme)$"),
) -> Dict[str, Any]:
    """
    Instrument radar/scanner: list of instruments with PnL, volume, signal, sector.

    Supports filtering by category tab.
    Uses dxFeed adapter for market quotes and paper engine for positions.
    """
    instruments: List[Dict[str, Any]] = []

    try:
        from core.market_heatmap import build_radar_snapshot
        from core.market_data_dxfeed import get_dxfeed_adapter
        from trading.paper_trading import get_paper_engine

        adapter = get_dxfeed_adapter()
        engine = get_paper_engine()

        # Get market quotes from dxFeed adapter
        ticks = adapter.get_watchlist()
        quotes = [t.to_dict() for t in ticks]

        # Get positions from paper engine
        positions: List[Dict[str, Any]] = []
        for _uid, portfolio in engine.portfolios.items():
            for _pk, pos in portfolio.positions.items():
                symbol = pos.asset.replace("/USDT", "").replace("USDT", "")
                pnl = engine._calculate_position_pnl(pos)
                exposure = abs(pos.size_usd) if hasattr(pos, "size_usd") else 0
                positions.append({
                    "symbol": symbol,
                    "pnl": pnl,
                    "exposure": exposure,
                })

        instruments = build_radar_snapshot(quotes, positions, category)

    except Exception as exc:
        logger.warning("radar_data_error", error=str(exc))

    return {
        "instruments": instruments,
        "category": category,
        "count": len(instruments),
    }


@router.get("/latency")
async def get_latency_stats(
    window: int = Query(default=300, ge=30, le=3600),
) -> Dict[str, Any]:
    """
    Backend endpoint latency percentiles over a time window.

    Returns per-endpoint and aggregate p50/p95/p99 in milliseconds.
    """
    cutoff = time.time() - window
    recent = [s for s in _latency_samples if s["ts"] >= cutoff]

    if not recent:
        return {"aggregate": {"p50": 0, "p95": 0, "p99": 0, "count": 0}, "by_endpoint": {}}

    # Aggregate
    all_ms = sorted(s["ms"] for s in recent)
    aggregate = {
        "p50": round(all_ms[len(all_ms) // 2], 1),
        "p95": round(all_ms[int(len(all_ms) * 0.95)], 1),
        "p99": round(all_ms[int(len(all_ms) * 0.99)], 1),
        "count": len(all_ms),
    }

    # Per-endpoint
    by_endpoint: Dict[str, Dict[str, Any]] = {}
    grouped: Dict[str, List[float]] = defaultdict(list)
    for s in recent:
        grouped[s["endpoint"]].append(s["ms"])

    for ep, vals in grouped.items():
        vals.sort()
        by_endpoint[ep] = {
            "p50": round(vals[len(vals) // 2], 1),
            "p95": round(vals[int(len(vals) * 0.95)], 1),
            "count": len(vals),
        }

    return {"aggregate": aggregate, "by_endpoint": by_endpoint}


@router.get("/breach_log")
async def get_breach_log(
    limit: int = Query(default=50, ge=1, le=200),
) -> Dict[str, Any]:
    """
    Recent risk breach events with rule, instrument, action, and severity.
    """
    # Also pull from risk.py circuit breaker history
    combined = list(_breach_log)

    try:
        from web.api.risk import _circuit_breaker_history
        for evt in _circuit_breaker_history[-50:]:
            combined.append({
                "ts": evt.get("timestamp", ""),
                "rule": evt.get("type", "circuit_breaker"),
                "instrument": evt.get("details", {}).get("instrument", "SYSTEM"),
                "value": 0,
                "threshold": 0,
                "action": evt.get("type", "unknown"),
                "severity": "CRITICAL" if "kill" in evt.get("type", "") else "WARNING",
            })
    except Exception:
        pass

    # Sort by timestamp descending, take limit
    combined.sort(key=lambda x: x.get("ts", ""), reverse=True)
    entries = combined[:limit]

    return {
        "breaches": entries,
        "total": len(combined),
    }
