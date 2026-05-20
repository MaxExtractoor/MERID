"""Kalshi UI Summary Endpoint — Single unified data source for React frontend.

Provides a complete snapshot of Kalshi state for initial UI render:
- Positions, orders, fills, balance
- Risk summary and reconciliation status
- Signals (edge, liquidity, volume, risk events)
- Agent grid status and PnL

Purpose: Eliminate UI-side mocks/fallbacks by providing all truth sources in one call.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from typing import Any, Dict, List, Optional

from merid.event_venues.kalshi.venue_adapter import get_kalshi_venue_adapter
from merid.reconciliation.kalshi_reconciler import get_kalshi_reconciler
from merid.signals.store import get_signal_store
from merid.signals.kalshi_signals import get_kalshi_signal_generator
from utils.logger import get_logger

logger = get_logger("web.api.kalshi_ui")
router = APIRouter(prefix="/api/v1/kalshi", tags=["kalshi-ui"])


@router.get("/ui-summary")
async def get_kalshi_ui_summary() -> Dict[str, Any]:
    """Get unified Kalshi UI summary with all real data sources.
    
    Returns complete snapshot for initial UI render, eliminating need for
    multiple separate API calls and ensuring consistency across cards/panels.
    
    Returns:
        {
            "positions": [...],       # From venue adapter
            "orders": [...],          # From venue adapter
            "fills": [...],           # From venue adapter
            "balance": {...},         # From venue adapter
            "risk": {...},            # From risk manager
            "reconciliation": {...},  # From reconciler
            "signals": {              # From signal store
                "edge_top": [...],
                "liquidity": [...],
                "volume_anomalies": [...],
                "risk_events": [...]
            },
            "grid": {                 # From agent grid
                "status": "...",
                "agents": [...],
                "pnl": {...}
            },
            "mode": "paper" | "live",
            "timestamp": 1234567890.0
        }
    """
    try:
        import time
        from merid.paper_config import DOMAIN_CONFIGS
        
        summary: Dict[str, Any] = {
            "timestamp": time.time(),
            "mode": "paper" if DOMAIN_CONFIGS["prediction"].mode.value == "paper" else "live",
        }
        
        # ── Positions, Orders, Fills, Balance ────────────────────────────
        try:
            adapter = get_kalshi_venue_adapter()
            
            # Get positions
            positions_raw = await adapter.get_positions()
            summary["positions"] = [
                {
                    "ticker": p.symbol,
                    "outcome": getattr(p, "side", getattr(p, "outcome", "yes")).lower(),
                    "size": float(p.quantity),
                    "avg_price": float(p.average_entry_price) if p.average_entry_price else 0.0,
                    "unrealized_pnl": float(p.unrealized_pnl) if p.unrealized_pnl else 0.0,
                    "realized_pnl": float(getattr(p, "realized_pnl", 0.0) or 0.0),
                }
                for p in positions_raw
            ]
            
            # Get orders
            orders_raw = await adapter.get_orders()
            summary["orders"] = [
                {
                    "order_id": o.order_id,
                    "ticker": o.symbol,
                    "side": o.side,
                    "size": float(o.quantity),
                    "price": float(o.limit_price) if o.limit_price else None,
                    "filled": float(o.filled_quantity) if o.filled_quantity else 0.0,
                    "remaining": float(o.remaining_quantity) if o.remaining_quantity else None,
                    "status": o.status,
                    "created_at": o.timestamp.isoformat() if o.timestamp else None,
                }
                for o in orders_raw
            ]
            
            # Get recent fills — aggregate from agent grid
            try:
                from merid.prediction.agent_grid import get_agent_grid as _get_ag
                _grid = _get_ag()
                _all_fills: list = []
                for _agent in _grid.agents:
                    _all_fills.extend(_agent.get_fills(50))
                _all_fills.sort(key=lambda x: x.get("ts", ""), reverse=True)
                summary["fills"] = _all_fills[:50]
            except Exception as _e:
                logger.debug("fills aggregation skipped: %s", _e)
                summary["fills"] = []

            # Get balance from BankrollServiceV2 via unified API (single source of truth)
            try:
                from web.api.kalshi_api import get_balance as _get_bal
                import asyncio as _aio
                _bal = await _get_bal()
                summary["balance"] = {
                    "usd": float(_bal.get("usd", 0.0)),
                    "locked": float(_bal.get("locked", 0.0)),
                    "available": float(_bal.get("available", 0.0)),
                    "portfolio_cents": _bal.get("portfolio_cents", 0),
                    "total_value_cents": _bal.get("total_value_cents", 0),
                    "state": _bal.get("state", "UNKNOWN"),
                }
            except Exception as _e:
                logger.debug("balance lookup skipped: %s", _e)
                summary["balance"] = {"usd": 0.0, "locked": 0.0, "available": 0.0, "portfolio_cents": 0, "total_value_cents": 0, "state": "UNKNOWN"}
            
        except Exception as exc:
            logger.warning(f"Failed to fetch positions/orders/balance: {exc}")
            summary["positions"] = []
            summary["orders"] = []
            summary["fills"] = []
            summary["balance"] = {"usd": 0.0, "locked": 0.0, "available": 0.0}
        
        # ── Risk Summary ──────────────────────────────────────────────────
        try:
            total_notional = sum(
                abs(p["size"] * p["avg_price"]) for p in summary["positions"]
            )
            total_unrealized_pnl = sum(p["unrealized_pnl"] for p in summary["positions"])

            # Pull real kill-switch state + daily PnL from global risk_controller
            # P0-6 FIX: Default to fail-safe (active=True) when monitoring fails
            _ks_active = True
            _ks_reason = "monitoring_failure: risk system unavailable"
            _daily_pnl = 0.0
            _drawdown = 0.0
            _recent_breaches: list = []
            _limits: dict = {}
            try:
                from merid.risk.kill_switches import risk_controller as _rc
                _rc_status = _rc.get_status()
                _ks_active = not bool(_rc_status.get("can_trade", True))
                _ks_reason = _rc_status.get("kill_reason")
                _daily_pnl = float(_rc_status.get("daily_pnl", 0.0))
            except Exception as _e:
                logger.warning("risk_controller status failed - defaulting to kill_active: %s", _e)
            try:
                from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk as _gkr
                _kr = _gkr()
                _rs = _kr.summary()
                # Only update if we successfully got data (don't override the fail-safe default on error)
                if _rs:
                    _ks_active = bool(_rs.get("kill_switch_active", _ks_active))
                    _ks_reason = _rs.get("kill_switch_reason", _ks_reason)
                    if _daily_pnl == 0.0:
                        _daily_pnl = float(_rs.get("daily_pnl_usd", _rs.get("daily_total_pnl_usd", 0.0)))
                    _drawdown = float(_rs.get("drawdown_pct", _drawdown))
                    _recent_breaches = _rs.get("recent_breaches", [])
                    _limits = _rs.get("limits", {})
            except Exception as _e:
                logger.warning("kalshi_risk summary failed: %s", _e)

            summary["risk"] = {
                "kill_switch_active": _ks_active,
                "kill_switch_reason": _ks_reason,
                "daily_pnl_usd": _daily_pnl,
                "total_notional_usd": total_notional,
                "total_unrealized_pnl_usd": total_unrealized_pnl,
                "daily_realized_pnl_usd": _daily_pnl,
                "daily_total_pnl_usd": _daily_pnl + total_unrealized_pnl,
                "daily_trades": len(summary["fills"]),
                "daily_fees_usd": 0.0,
                "drawdown_pct": _drawdown,
                "category_notional": {},
                "category_contracts": {},
                "open_market_count": len(summary["positions"]),
                "recent_breaches": _recent_breaches,
                "limits": _limits,
            }
        except Exception as exc:
            logger.warning(f"Failed to compute risk summary: {exc}")
            summary["risk"] = {
                "kill_switch_active": False,
                "kill_switch_reason": None,
                "daily_pnl_usd": 0.0,
                "total_notional_usd": 0.0,
                "total_unrealized_pnl_usd": 0.0,
                "daily_realized_pnl_usd": 0.0,
                "daily_total_pnl_usd": 0.0,
                "daily_trades": 0,
                "daily_fees_usd": 0.0,
                "drawdown_pct": 0.0,
                "category_notional": {},
                "category_contracts": {},
                "open_market_count": 0,
                "recent_breaches": [],
                "limits": {},
            }
        
        # ── Reconciliation ────────────────────────────────────────────────
        try:
            reconciler = get_kalshi_reconciler()
            adapter = get_kalshi_venue_adapter()
            
            # Run reconciliation check
            venue_positions = await adapter.get_positions()
            venue_orders = await adapter.get_orders()
            
            report = reconciler.reconcile(
                internal_positions=summary["positions"],
                venue_positions=venue_positions,
                internal_orders=summary["orders"],
                venue_orders=venue_orders,
            )
            
            summary["reconciliation"] = {
                "severity": report.severity.value,
                "summary": report.summary,
                "issue_count": len(report.issues),
                "issues": [
                    {
                        "type": issue.issue_type.value,
                        "severity": issue.severity.value,
                        "description": issue.description,
                        "internal_value": issue.internal_value,
                        "venue_value": issue.venue_value,
                    }
                    for issue in report.issues[:10]  # Top 10 issues
                ],
                "timestamp": report.timestamp,
            }
        except Exception as exc:
            logger.warning(f"Failed to run reconciliation: {exc}")
            summary["reconciliation"] = {
                "severity": "UNKNOWN",
                "summary": "Reconciliation unavailable",
                "issue_count": 0,
                "issues": [],
                "timestamp": time.time(),
            }
        
        # ── Signals ───────────────────────────────────────────────────────
        try:
            store = get_signal_store()
            
            # Get top edge signals
            all_signals = store.list_signals(
                signal_type="market_edge",
                domain="prediction",
                venue="kalshi",
                limit=20,
            )
            
            # Sort by edge_pct and take top 5
            edge_signals = sorted(
                all_signals,
                key=lambda s: s.get("edge_pct", 0),
                reverse=True,
            )[:5]
            
            # Get liquidity signals
            liquidity_signals = store.list_signals(
                signal_type="liquidity",
                domain="prediction",
                venue="kalshi",
                limit=5,
            )
            
            # Get volume anomalies
            volume_signals = store.list_signals(
                signal_type="volume_anomaly",
                domain="prediction",
                venue="kalshi",
                limit=5,
            )
            
            # Get risk events
            risk_signals = store.list_signals(
                signal_type="risk_event",
                domain="prediction",
                venue="kalshi",
                limit=5,
            )
            
            summary["signals"] = {
                "edge_top": edge_signals,
                "liquidity": liquidity_signals,
                "volume_anomalies": volume_signals,
                "risk_events": risk_signals,
            }
        except Exception as exc:
            logger.warning(f"Failed to fetch signals: {exc}")
            summary["signals"] = {
                "edge_top": [],
                "liquidity": [],
                "volume_anomalies": [],
                "risk_events": [],
            }
        
        # ── Agent Grid ────────────────────────────────────────────────────
        try:
            from merid.prediction.agent_grid import get_agent_grid
            
            grid = get_agent_grid()
            
            # Aggregate PnL from paper session
            _pnl_total = 0.0
            _pnl_today = 0.0
            try:
                from merid.prediction.paper_session import get_paper_session as _gps
                _sess = _gps()
                _pnl_total = float(getattr(_sess, "total_pnl_cents", 0.0)) / 100.0
                _pnl_today = float(getattr(_sess, "session_pnl_cents", 0.0)) / 100.0
            except Exception as _e:
                logger.debug("paper_session pnl skipped: %s", _e)

            summary["grid"] = {
                "status": "running" if grid.is_running else "stopped",
                "agents": [
                    {
                        "agent_id": agent.config.agent_id,
                        "enabled": agent.state.enabled,
                        "signal_count": len(agent.state.signal_log),
                        "order_count": agent.state.orders_placed,
                    }
                    for agent in grid.agents
                ],
                "pnl": {
                    "total": _pnl_total,
                    "today": _pnl_today,
                },
            }
        except Exception as exc:
            logger.warning(f"Failed to fetch agent grid status: {exc}")
            summary["grid"] = {
                "status": "unknown",
                "agents": [],
                "pnl": {"total": 0.0, "today": 0.0},
            }
        
        return summary
        
    except Exception as exc:
        logger.error(f"Failed to generate UI summary: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))
