"""Kalshi UI State API — /api/v1/kalshi/ui-state/*

Canonical state aggregation endpoint for UI consumption.
Provides single source of truth for all essential Kalshi operational state.

Endpoints:
  GET  /api/v1/kalshi/ui-state              — Aggregated core state
  WS   /api/v1/kalshi/ui-state/ws           — Real-time updates
  GET  /api/v1/kalshi/ui-state/agent/{id}  — Agent performance detail
  GET  /api/v1/kalshi/ui-state/sentiment/{asset} — Sentiment detail
  GET  /api/v1/kalshi/ui-state/market/{ticker} — Market detail
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from web.api.auth import get_current_session
from utils.logger import get_logger

logger = get_logger("web.api.kalshi_ui_state_api")

router = APIRouter(prefix="/api/v1/kalshi", tags=["kalshi-ui-state"])


# ── Response Models ────────────────────────────────────────────────────────────────

class SystemStatus(BaseModel):
    mode: str  # 'paper' | 'shadow' | 'live'
    is_live_enabled: bool
    execution_gate: str  # 'clear' | 'limited' | 'blocked'
    execution_gate_reasons: List[str]
    execution_gate_near_limit: Optional[Dict[str, Any]] = None
    kill_switch_active: bool
    kill_switch_reason: Optional[str]
    kill_switch_triggered_at: Optional[str]
    venue_healthy: bool
    venue_latency_ms: Optional[float]
    venue_last_error: Optional[str]
    reconciliation_status: str  # 'ok' | 'discrepancy' | 'error'
    reconciliation_last_check: Optional[str]
    reconciliation_discrepancy_count: int


class CapitalState(BaseModel):
    balance_usd: float
    portfolio_usd: float
    total_value_usd: float
    locked_usd: float
    daily_pnl_usd: float
    total_pnl_usd: float
    daily_pnl_pct: float
    drawdown_pct: float
    drawdown_tier: str  # 'normal' | 'warning' | 'downsize' | 'halt'
    drawdown_from_peak_usd: float
    peak_equity_usd: float
    daily_loss_limit_usd: float
    daily_loss_remaining_usd: float
    notional_limit_usd: float
    notional_used_usd: float
    notional_utilization_pct: float


class PositionSummary(BaseModel):
    ticker: str
    side: str  # 'yes' | 'no'
    contracts: int
    avg_price_cents: float
    current_price_cents: float
    unrealized_pnl_usd: float
    expiry_time: str
    seconds_to_expiry: int


class OrderSummary(BaseModel):
    order_id: str
    ticker: string
    side: str  # 'yes' | 'no'
    action: str  # 'buy' | 'sell'
    contracts: int
    limit_price_cents: float
    status: str  # 'pending' | 'open' | 'filled' | 'cancelled' | 'rejected'
    created_at: str
    seconds_ago: int


class FillSummary(BaseModel):
    fill_id: str
    order_id: str
    ticker: str
    side: str  # 'yes' | 'no'
    contracts: int
    price_cents: float
    fee_cents: float
    pnl_usd: float
    filled_at: str
    seconds_ago: int


class MarketState(BaseModel):
    open_position_count: int
    positions: List[PositionSummary]
    open_order_count: int
    recent_orders: List[OrderSummary]
    recent_fills: List[FillSummary]
    active_tickers: List[str]
    active_market_count: int
    avg_spread_cents: Optional[float]
    avg_depth_10c: Optional[float]
    illiquid_market_count: int


class BreachSummary(BaseModel):
    check: str
    reason: str
    severity: str  # 'warning' | 'critical'
    triggered_at: str
    acknowledged: bool


class RiskAlertSummary(BaseModel):
    id: str
    level: str  # 'warning' | 'critical' | 'info'
    category: str
    message: str
    timestamp: str
    acknowledged: bool


class RiskState(BaseModel):
    daily_loss_usd: float
    daily_loss_limit_usd: float
    daily_loss_pct: float
    total_notional_usd: float
    notional_limit_usd: float
    notional_utilization_pct: float
    gross_exposure_usd: float
    net_exposure_usd: float
    max_single_asset_exposure_pct: float
    breach_count: int
    active_breaches: List[BreachSummary]
    recent_alerts: List[RiskAlertSummary]
    unacknowledged_alert_count: int


class GridErrorSummary(BaseModel):
    agent_id: str
    error: str
    timestamp: str


class GridState(BaseModel):
    running: bool
    agent_count: int
    active_agent_count: int
    last_cycle_at: Optional[str]
    cycles_run: int
    cycles_per_minute: Optional[float]
    total_orders: int
    total_fills: int
    fill_rate_pct: Optional[float]
    active_markets: int
    coverage_pct: Optional[float]
    recent_errors: List[GridErrorSummary]
    error_count: int


class KalshiUIState(BaseModel):
    version: str
    timestamp: str
    cache_ttl_seconds: int
    system: SystemStatus
    capital: CapitalState
    markets: MarketState
    risk: RiskState
    grid: GridState


# ── Helper Functions ─────────────────────────────────────────────────────────────

def _safe_float(v: Any, default: float = 0.0) -> float:
    """Convert any numeric value to a JSON-safe float."""
    try:
        if v is None:
            return default
        return float(v)
    except (ValueError, TypeError):
        return default


def _safe_int(v: Any, default: int = 0) -> int:
    """Convert any numeric value to a JSON-safe int."""
    try:
        if v is None:
            return default
        return int(v)
    except (ValueError, TypeError):
        return default


def _seconds_ago(timestamp: Optional[str]) -> int:
    """Calculate seconds ago from ISO timestamp."""
    if not timestamp:
        return 0
    try:
        ts = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        delta = datetime.now(timezone.utc) - ts
        return int(delta.total_seconds())
    except (ValueError, AttributeError):
        return 0


# ── Data Fetchers ─────────────────────────────────────────────────────────────────

async def _fetch_system_status() -> SystemStatus:
    """Aggregate system status from multiple endpoints."""
    try:
        # Import grid API router to access mode endpoint
        from web.api.kalshi_grid_api import router as grid_router
        from web.api.system_endpoints import router as system_router
        
        # Fetch mode from grid
        # PRODUCTION STACK: Use agent_grid_15m instead of legacy agent_grid
        mode_data = None
        try:
            # Direct call to grid mode endpoint logic
            from merid.prediction.agent_grid_15m import get_agent_grid
            grid = get_agent_grid()
            if grid:
                mode_data = {
                    "mode": getattr(grid, "mode", "paper"),
                    "is_live_enabled": getattr(grid, "is_live_enabled", False),
                }
        except Exception as e:
            logger.warning(f"Failed to fetch grid mode: {e}")
        
        # Fetch execution gate
        execution_gate_data = None
        try:
            from core.execution_gate import get_execution_gate
            gate = get_execution_gate()
            if gate:
                status = gate.get_status()
                execution_gate_data = {
                    "state": status.get("state", "clear"),
                    "reasons": status.get("reasons", []),
                }
        except Exception as e:
            logger.warning(f"Failed to fetch execution gate: {e}")
        
        # Fetch kill switch
        kill_switch_data = None
        try:
            from merid.risk.kill_switches import get_risk_controller
            rc = get_risk_controller()
            if rc:
                kill_switch_data = {
                    "active": rc.is_global_kill_active(),
                    "reason": rc.get_kill_reason(),
                }
        except Exception as e:
            logger.warning(f"Failed to fetch kill switch: {e}")
        
        # Fetch venue health
        venue_healthy = True
        venue_latency_ms = None
        venue_last_error = None
        try:
            from merid.event_venues.kalshi.market_catalog import get_market_catalog
            catalog = get_market_catalog()
            if catalog:
                venue_healthy = len(catalog.markets) > 0
        except Exception as e:
            logger.warning(f"Failed to fetch venue health: {e}")
            venue_healthy = False
            venue_last_error = str(e)
        
        # Reconciliation status
        reconciliation_status = "ok"
        reconciliation_discrepancy_count = 0
        try:
            from merid.reconciliation.venue_reconciler import get_venue_reconciler
            reconciler = get_venue_reconciler()
            if reconciler:
                status = reconciler.get_status()
                reconciliation_status = status.get("status", "ok")
                reconciliation_discrepancy_count = status.get("discrepancy_count", 0)
        except Exception as e:
            logger.warning(f"Failed to fetch reconciliation status: {e}")
        
        return SystemStatus(
            mode=mode_data.get("mode", "paper") if mode_data else "paper",
            is_live_enabled=mode_data.get("is_live_enabled", False) if mode_data else False,
            execution_gate=execution_gate_data.get("state", "clear") if execution_gate_data else "clear",
            execution_gate_reasons=execution_gate_data.get("reasons", []) if execution_gate_data else [],
            execution_gate_near_limit=None,
            kill_switch_active=kill_switch_data.get("active", False) if kill_switch_data else False,
            kill_switch_reason=kill_switch_data.get("reason") if kill_switch_data else None,
            kill_switch_triggered_at=None,
            venue_healthy=venue_healthy,
            venue_latency_ms=venue_latency_ms,
            venue_last_error=venue_last_error,
            reconciliation_status=reconciliation_status,
            reconciliation_last_check=datetime.now(timezone.utc).isoformat(),
            reconciliation_discrepancy_count=reconciliation_discrepancy_count,
        )
    except Exception as e:
        logger.error(f"Error fetching system status: {e}")
        # Return safe defaults on error
        return SystemStatus(
            mode="paper",
            is_live_enabled=False,
            execution_gate="clear",
            execution_gate_reasons=[],
            kill_switch_active=False,
            kill_switch_reason=None,
            kill_switch_triggered_at=None,
            venue_healthy=False,
            venue_latency_ms=None,
            venue_last_error=str(e),
            reconciliation_status="error",
            reconciliation_last_check=datetime.now(timezone.utc).isoformat(),
            reconciliation_discrepancy_count=0,
        )


async def _fetch_capital_state() -> CapitalState:
    """Aggregate capital state from balance and risk endpoints."""
    try:
        from merid.event_venues.kalshi import get_bankroll_service
        
        bankroll_service = await get_bankroll_service()
        if bankroll_service:
            result = await bankroll_service.get_balance()
            if isinstance(result, BalanceSuccess):
                balance_cents = result.balance_cents
                portfolio_cents = result.portfolio_cents
                total_value_cents = balance_cents + portfolio_cents
                
                # Convert to USD
                balance_usd = balance_cents / 100
                portfolio_usd = portfolio_cents / 100
                total_value_usd = total_value_cents / 100
                
                # Get sizing metrics for drawdown and limits
                try:
                    from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk
                    risk_data = get_kalshi_risk()
                    if risk_data:
                        daily_pnl_usd = _safe_float(risk_data.get("daily_pnl_usd"))
                        daily_pnl_pct = _safe_float(risk_data.get("daily_pnl_pct"))
                        drawdown_pct = _safe_float(risk_data.get("drawdown_pct"))
                        drawdown_tier = risk_data.get("drawdown_tier", "normal")
                        daily_loss_limit_usd = _safe_float(risk_data.get("daily_loss_limit_usd"))
                        notional_limit_usd = _safe_float(risk_data.get("notional_limit_usd"))
                        notional_used_usd = _safe_float(risk_data.get("total_notional_usd"))
                    else:
                        daily_pnl_usd = 0.0
                        daily_pnl_pct = 0.0
                        drawdown_pct = 0.0
                        drawdown_tier = "normal"
                        daily_loss_limit_usd = 0.0
                        notional_limit_usd = 0.0
                        notional_used_usd = 0.0
                except Exception as e:
                    logger.warning(f"Failed to fetch risk data: {e}")
                    daily_pnl_usd = 0.0
                    daily_pnl_pct = 0.0
                    drawdown_pct = 0.0
                    drawdown_tier = "normal"
                    daily_loss_limit_usd = 0.0
                    notional_limit_usd = 0.0
                    notional_used_usd = 0.0
                
                return CapitalState(
                    balance_usd=balance_usd,
                    portfolio_usd=portfolio_usd,
                    total_value_usd=total_value_usd,
                    locked_usd=0.0,  # TODO: compute from pending orders
                    daily_pnl_usd=daily_pnl_usd,
                    total_pnl_usd=0.0,  # TODO: compute from historical data
                    daily_pnl_pct=daily_pnl_pct,
                    drawdown_pct=drawdown_pct,
                    drawdown_tier=drawdown_tier,
                    drawdown_from_peak_usd=0.0,  # TODO: compute from peak equity
                    peak_equity_usd=total_value_usd,  # TODO: track historical peak
                    daily_loss_limit_usd=daily_loss_limit_usd,
                    daily_loss_remaining_usd=max(0, daily_loss_limit_usd - min(0, daily_pnl_usd)),
                    notional_limit_usd=notional_limit_usd,
                    notional_used_usd=notional_used_usd,
                    notional_utilization_pct=(notional_used_usd / notional_limit_usd * 100) if notional_limit_usd > 0 else 0.0,
                )
        
        # Fallback if bankroll service unavailable
        return CapitalState(
            balance_usd=0.0,
            portfolio_usd=0.0,
            total_value_usd=0.0,
            locked_usd=0.0,
            daily_pnl_usd=0.0,
            total_pnl_usd=0.0,
            daily_pnl_pct=0.0,
            drawdown_pct=0.0,
            drawdown_tier="normal",
            drawdown_from_peak_usd=0.0,
            peak_equity_usd=0.0,
            daily_loss_limit_usd=0.0,
            daily_loss_remaining_usd=0.0,
            notional_limit_usd=0.0,
            notional_used_usd=0.0,
            notional_utilization_pct=0.0,
        )
    except Exception as e:
        logger.error(f"Error fetching capital state: {e}")
        return CapitalState(
            balance_usd=0.0,
            portfolio_usd=0.0,
            total_value_usd=0.0,
            locked_usd=0.0,
            daily_pnl_usd=0.0,
            total_pnl_usd=0.0,
            daily_pnl_pct=0.0,
            drawdown_pct=0.0,
            drawdown_tier="normal",
            drawdown_from_peak_usd=0.0,
            peak_equity_usd=0.0,
            daily_loss_limit_usd=0.0,
            daily_loss_remaining_usd=0.0,
            notional_limit_usd=0.0,
            notional_used_usd=0.0,
            notional_utilization_pct=0.0,
        )


async def _fetch_market_state() -> MarketState:
    """Aggregate market state from positions, orders, fills endpoints."""
    try:
        positions = []
        recent_orders = []
        recent_fills = []
        active_tickers = set()
        
        # Fetch positions
        try:
            from merid.event_venues.kalshi.kalshi_positions import get_kalshi_positions
            pos_data = get_kalshi_positions()
            if pos_data and "positions" in pos_data:
                for pos in pos_data["positions"][:50]:  # Limit to 50 positions
                    ticker = pos.get("ticker", "")
                    if not ticker or _is_test_ticker(ticker):
                        continue
                    
                    active_tickers.add(ticker)
                    positions.append(PositionSummary(
                        ticker=ticker,
                        side=pos.get("side", "yes"),
                        contracts=_safe_int(pos.get("contracts")),
                        avg_price_cents=_safe_float(pos.get("avg_price_cents")),
                        current_price_cents=_safe_float(pos.get("current_price_cents")),
                        unrealized_pnl_usd=_safe_float(pos.get("unrealized_pnl_usd")),
                        expiry_time=pos.get("expiry_time", ""),
                        seconds_to_expiry=_seconds_ago(pos.get("expiry_time")),
                    ))
        except Exception as e:
            logger.warning(f"Failed to fetch positions: {e}")
        
        # Fetch orders
        try:
            from merid.event_venues.kalshi.kalshi_orders import get_kalshi_orders
            order_data = get_kalshi_orders(limit=10)
            if order_data and "orders" in order_data:
                for order in order_data["orders"][:10]:
                    ticker = order.get("ticker", "")
                    if not ticker or _is_test_ticker(ticker):
                        continue
                    
                    active_tickers.add(ticker)
                    recent_orders.append(OrderSummary(
                        order_id=order.get("order_id", ""),
                        ticker=ticker,
                        side=order.get("side", "yes"),
                        action=order.get("action", "buy"),
                        contracts=_safe_int(order.get("contracts")),
                        limit_price_cents=_safe_float(order.get("limit_price_cents")),
                        status=order.get("status", "pending"),
                        created_at=order.get("created_at", ""),
                        seconds_ago=_seconds_ago(order.get("created_at")),
                    ))
        except Exception as e:
            logger.warning(f"Failed to fetch orders: {e}")
        
        # Fetch fills
        try:
            from merid.event_venues.kalshi.kalshi_fills import get_kalshi_fills
            fill_data = get_kalshi_fills(limit=10)
            if fill_data and "fills" in fill_data:
                for fill in fill_data["fills"][:10]:
                    ticker = fill.get("ticker", "")
                    if not ticker or _is_test_ticker(ticker):
                        continue
                    
                    active_tickers.add(ticker)
                    recent_fills.append(FillSummary(
                        fill_id=fill.get("fill_id", ""),
                        order_id=fill.get("order_id", ""),
                        ticker=ticker,
                        side=fill.get("side", "yes"),
                        contracts=_safe_int(fill.get("contracts")),
                        price_cents=_safe_float(fill.get("price_cents")),
                        fee_cents=_safe_float(fill.get("fee_cents")),
                        pnl_usd=_safe_float(fill.get("pnl_usd")),
                        filled_at=fill.get("filled_at", ""),
                        seconds_ago=_seconds_ago(fill.get("filled_at")),
                    ))
        except Exception as e:
            logger.warning(f"Failed to fetch fills: {e}")
        
        return MarketState(
            open_position_count=len(positions),
            positions=positions,
            open_order_count=len([o for o in recent_orders if o.status in ("pending", "open")]),
            recent_orders=recent_orders,
            recent_fills=recent_fills,
            active_tickers=list(active_tickers),
            active_market_count=len(active_tickers),
            avg_spread_cents=None,  # TODO: compute from orderbook
            avg_depth_10c=None,  # TODO: compute from orderbook
            illiquid_market_count=0,  # TODO: compute from liquidity health
        )
    except Exception as e:
        logger.error(f"Error fetching market state: {e}")
        return MarketState(
            open_position_count=0,
            positions=[],
            open_order_count=0,
            recent_orders=[],
            recent_fills=[],
            active_tickers=[],
            active_market_count=0,
            avg_spread_cents=None,
            avg_depth_10c=None,
            illiquid_market_count=0,
        )


async def _fetch_risk_state() -> RiskState:
    """Aggregate risk state from risk and alerts endpoints."""
    try:
        risk_data = None
        alerts = []
        
        # Fetch risk data
        try:
            from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk
            risk_data = get_kalshi_risk()
        except Exception as e:
            logger.warning(f"Failed to fetch risk data: {e}")
        
        # Fetch alerts
        try:
            from web.api.risk_routes import get_risk_alerts
            alert_data = get_risk_alerts()
            if alert_data and "alerts" in alert_data:
                for alert in alert_data["alerts"][:20]:
                    alerts.append(RiskAlertSummary(
                        id=alert.get("id", ""),
                        level=alert.get("level", "info"),
                        category=alert.get("category", ""),
                        message=alert.get("message", ""),
                        timestamp=alert.get("timestamp", ""),
                        acknowledged=alert.get("acknowledged", False),
                    ))
        except Exception as e:
            logger.warning(f"Failed to fetch risk alerts: {e}")
        
        if risk_data:
            daily_loss_usd = _safe_float(risk_data.get("daily_loss_usd"))
            daily_loss_limit_usd = _safe_float(risk_data.get("daily_loss_limit_usd"))
            total_notional_usd = _safe_float(risk_data.get("total_notional_usd"))
            notional_limit_usd = _safe_float(risk_data.get("notional_limit_usd"))
            breach_count = _safe_int(risk_data.get("breach_count"))
            
            # Parse breaches
            active_breaches = []
            if "recent_breaches" in risk_data:
                for breach in risk_data["recent_breaches"][:10]:
                    active_breaches.append(BreachSummary(
                        check=breach.get("check", ""),
                        reason=breach.get("reason", ""),
                        severity=breach.get("severity", "warning"),
                        triggered_at=breach.get("ts", ""),
                        acknowledged=breach.get("acknowledged", False),
                    ))
        else:
            daily_loss_usd = 0.0
            daily_loss_limit_usd = 0.0
            total_notional_usd = 0.0
            notional_limit_usd = 0.0
            breach_count = 0
            active_breaches = []
        
        return RiskState(
            daily_loss_usd=daily_loss_usd,
            daily_loss_limit_usd=daily_loss_limit_usd,
            daily_loss_pct=(daily_loss_usd / daily_loss_limit_usd * 100) if daily_loss_limit_usd > 0 else 0.0,
            total_notional_usd=total_notional_usd,
            notional_limit_usd=notional_limit_usd,
            notional_utilization_pct=(total_notional_usd / notional_limit_usd * 100) if notional_limit_usd > 0 else 0.0,
            gross_exposure_usd=0.0,  # TODO: compute from positions
            net_exposure_usd=0.0,  # TODO: compute from positions
            max_single_asset_exposure_pct=0.0,  # TODO: compute from positions
            breach_count=breach_count,
            active_breaches=active_breaches,
            recent_alerts=alerts,
            unacknowledged_alert_count=len([a for a in alerts if not a.acknowledged]),
        )
    except Exception as e:
        logger.error(f"Error fetching risk state: {e}")
        return RiskState(
            daily_loss_usd=0.0,
            daily_loss_limit_usd=0.0,
            daily_loss_pct=0.0,
            total_notional_usd=0.0,
            notional_limit_usd=0.0,
            notional_utilization_pct=0.0,
            gross_exposure_usd=0.0,
            net_exposure_usd=0.0,
            max_single_asset_exposure_pct=0.0,
            breach_count=0,
            active_breaches=[],
            recent_alerts=[],
            unacknowledged_alert_count=0,
        )


async def _fetch_grid_state() -> GridState:
    """Aggregate grid state from grid status endpoint."""
    try:
        from merid.prediction.agent_grid_15m import get_agent_grid

        grid = get_agent_grid()
        if grid:
            running = getattr(grid, "_running", False)
            agent_count = len(getattr(grid, "_agents", []))
            active_agent_count = len([a for a in getattr(grid, "_agents", []) if getattr(a.config, "enabled", False)])
            # LeanAgentGrid15m doesn't track last_cycle_at or cycles_run
            last_cycle_at = None
            cycles_run = 0

            # Compute cycles per minute
            cycles_per_minute = None
            if last_cycle_at and cycles_run > 0:
                try:
                    last_cycle_dt = datetime.fromisoformat(last_cycle_at.replace('Z', '+00:00'))
                    seconds_since_start = (datetime.now(timezone.utc) - last_cycle_dt).total_seconds()
                    if seconds_since_start > 0:
                        cycles_per_minute = (cycles_run / seconds_since_start) * 60
                except Exception:
                    pass
            
            # Get metrics from grid
            total_orders = 0
            total_fills = 0
            fill_rate_pct = None
            active_markets = 0
            coverage_pct = None
            
            metrics = getattr(grid, "metrics", {})
            if metrics:
                total_orders = _safe_int(metrics.get("total_orders"))
                total_fills = _safe_int(metrics.get("total_fills"))
                active_markets = _safe_int(metrics.get("active_markets"))
                coverage_pct = _safe_float(metrics.get("coverage_pct"))
                if total_orders > 0:
                    fill_rate_pct = (total_fills / total_orders) * 100
            
            # Get recent errors
            recent_errors = []
            error_count = 0
            try:
                error_log = getattr(grid, "error_log", [])
                for err in error_log[:5]:
                    recent_errors.append(GridErrorSummary(
                        agent_id=err.get("agent_id", ""),
                        error=err.get("error", ""),
                        timestamp=err.get("timestamp", ""),
                    ))
                error_count = len(error_log)
            except Exception:
                pass
            
            return GridState(
                running=running,
                agent_count=agent_count,
                active_agent_count=active_agent_count,
                last_cycle_at=last_cycle_at,
                cycles_run=cycles_run,
                cycles_per_minute=cycles_per_minute,
                total_orders=total_orders,
                total_fills=total_fills,
                fill_rate_pct=fill_rate_pct,
                active_markets=active_markets,
                coverage_pct=coverage_pct,
                recent_errors=recent_errors,
                error_count=error_count,
            )
        
        # Fallback if grid unavailable
        return GridState(
            running=False,
            agent_count=0,
            active_agent_count=0,
            last_cycle_at=None,
            cycles_run=0,
            cycles_per_minute=None,
            total_orders=0,
            total_fills=0,
            fill_rate_pct=None,
            active_markets=0,
            coverage_pct=None,
            recent_errors=[],
            error_count=0,
        )
    except Exception as e:
        logger.error(f"Error fetching grid state: {e}")
        return GridState(
            running=False,
            agent_count=0,
            active_agent_count=0,
            last_cycle_at=None,
            cycles_run=0,
            cycles_per_minute=None,
            total_orders=0,
            total_fills=0,
            fill_rate_pct=None,
            active_markets=0,
            coverage_pct=None,
            recent_errors=[],
            error_count=0,
        )


# ── Endpoints ─────────────────────────────────────────────────────────────────────

@router.get("/ui-state", response_model=KalshiUIState)
async def get_kalshi_ui_state():
    """
    Get aggregated canonical Kalshi UI state.
    
    This endpoint aggregates data from multiple existing Kalshi endpoints
    to provide a single source of truth for UI consumption.
    
    Cache TTL: 10 seconds recommended
    """
    # Fetch all state components in parallel
    system, capital, markets, risk, grid = await asyncio.gather(
        _fetch_system_status(),
        _fetch_capital_state(),
        _fetch_market_state(),
        _fetch_risk_state(),
        _fetch_grid_state(),
    )
    
    return KalshiUIState(
        version="1.0.0",
        timestamp=datetime.now(timezone.utc).isoformat(),
        cache_ttl_seconds=10,
        system=system,
        capital=capital,
        markets=markets,
        risk=risk,
        grid=grid,
    )


@router.websocket("/ui-state/ws")
async def kalshi_ui_state_websocket(websocket: WebSocket):
    """
    WebSocket endpoint for real-time UI state updates.
    
    Pushes updates for:
    - Fills
    - Orders
    - Risk alerts
    - Kill switch changes
    - Execution gate changes
    - Grid status changes
    - Capital updates
    """
    await websocket.accept()
    
    try:
        # TODO: Subscribe to event sources and push updates
        # For now, send initial state and keep connection alive
        initial_state = await get_kalshi_ui_state()
        await websocket.send_json(initial_state.dict())
        
        # Keepalive loop
        while True:
            await asyncio.sleep(30)
            await websocket.send_json({"type": "ping", "timestamp": datetime.now(timezone.utc).isoformat()})
            
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        await websocket.close()


# ── Detail Endpoints (Lazy-Loaded) ───────────────────────────────────────────────

@router.get("/ui-state/agent/{agent_id}")
async def get_agent_performance_detail(agent_id: str):
    """
    Get detailed agent performance data.
    
    Lazy-loaded on demand when user drills into agent details.
    """
    # TODO: Implement using KALSHI_GRID_PERFORMANCE_AGENT endpoint
    return {"agent_id": agent_id, "detail": "TODO"}


@router.get("/ui-state/sentiment/{asset}")
async def get_sentiment_detail(asset: str):
    """
    Get detailed sentiment data for an asset.
    
    Lazy-loaded on demand when user drills into sentiment details.
    """
    # TODO: Implement using SENTIMENT_VOL_ASSET endpoint
    return {"asset": asset, "detail": "TODO"}


@router.get("/ui-state/market/{ticker}")
async def get_market_detail(ticker: str):
    """
    Get detailed market data.
    
    Lazy-loaded on demand when user drills into market details.
    """
    # TODO: Implement using KALSHI_MARKET_DETAIL endpoint
    return {"ticker": ticker, "detail": "TODO"}
