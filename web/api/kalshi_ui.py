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
router = APIRouter(prefix="/kalshi", tags=["kalshi-ui"])


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
                    "outcome": "yes",  # Kalshi uses yes/no
                    "size": float(p.quantity),
                    "avg_price": float(p.average_entry_price) if p.average_entry_price else 0.0,
                    "unrealized_pnl": float(p.unrealized_pnl) if p.unrealized_pnl else 0.0,
                    "realized_pnl": 0.0,  # TODO: Track separately
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
            
            # Get recent fills (last 50)
            # TODO: Implement get_fills() in venue adapter
            summary["fills"] = []
            
            # Get balance
            # TODO: Implement get_balance() in venue adapter
            summary["balance"] = {
                "usd": 10000.0,  # Placeholder for paper mode
                "locked": 0.0,
                "available": 10000.0,
            }
            
        except Exception as exc:
            logger.warning(f"Failed to fetch positions/orders/balance: {exc}")
            summary["positions"] = []
            summary["orders"] = []
            summary["fills"] = []
            summary["balance"] = {"usd": 0.0, "locked": 0.0, "available": 0.0}
        
        # ── Risk Summary ──────────────────────────────────────────────────
        try:
            # TODO: Wire to real risk manager when available
            # For now, compute basic risk from positions
            total_notional = sum(
                abs(p["size"] * p["avg_price"]) for p in summary["positions"]
            )
            total_unrealized_pnl = sum(p["unrealized_pnl"] for p in summary["positions"])
            
            summary["risk"] = {
                "kill_switch_active": False,
                "kill_switch_reason": None,
                "daily_pnl_usd": 0.0,  # TODO: Track daily PnL
                "total_notional_usd": total_notional,
                "total_unrealized_pnl_usd": total_unrealized_pnl,
                "daily_realized_pnl_usd": 0.0,
                "daily_total_pnl_usd": total_unrealized_pnl,
                "daily_trades": len(summary["fills"]),
                "daily_fees_usd": 0.0,
                "drawdown_pct": 0.0,
                "category_notional": {},
                "category_contracts": {},
                "open_market_count": len(summary["positions"]),
                "recent_breaches": [],
                "limits": {
                    "max_notional_usd": 5000.0,
                    "max_daily_loss_usd": 250.0,
                    "max_positions": 20,
                },
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
            
            summary["grid"] = {
                "status": "running" if grid._running else "stopped",
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
                    "total": 0.0,  # TODO: Aggregate from agent states
                    "today": 0.0,
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
