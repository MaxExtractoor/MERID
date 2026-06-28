"""Bankroll panel snapshot when **AgentGrid** owns PM execution and CT loop is idle.

The Multi-Asset Continuous Trader singleton still exists and `status_snapshot()` may
return live balances, but `running=False` and `cycle=0` confuse operators.  This module
merges AgentGrid + KalshiRiskManager + ExecutionGate into the same JSON shape the UI
already consumes — no new endpoints.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("merid.prediction.pm_bankroll_snapshot")


def build_agent_grid_bankroll_overlay(
    ct_base: Dict[str, Any],
    *,
    ct_err: Optional[str] = None,
) -> Dict[str, Any]:
    """Mutate a CT-shaped snapshot so the bankroll panel reflects AgentGrid PM activity.

    When ``MERID_ENABLE_KALSHI_CT`` is false, CT's async loop never starts; this overlay
    sets ``running=True`` if AgentGrid is up and fills cycle/order aggregates.
    """
    out = dict(ct_base)
    grid_on = False
    agents: List[Any] = []

    try:
        from merid.prediction.agent_grid_15m import get_agent_grid

        grid = get_agent_grid()
        grid_on = bool(grid._running if grid else False)
        agents = list(getattr(grid, "_agents", []) or [])
    except Exception as exc:
        logger.debug("agent_grid overlay: grid unavailable (%s)", exc)

    ct_loop_running = bool(out.get("running"))

    if grid_on and not ct_loop_running:
        out["running"] = True
        out["available"] = True
        out["pm_signal_source"] = "agent_grid"
        out["pm_ct_loop_idle"] = True
        out["pm_note"] = (
            "KalshiContinuousTrader loop is disabled; PM bankroll/sizing is driven by "
            "AgentGrid agents + KalshiRiskManager + ExecutionGate (see MERID_ENABLE_KALSHI_CT)."
        )
        max_cyc = max((getattr(a.state, "cycles_run", 0) for a in agents), default=0)
        sum_cycles = sum(getattr(a.state, "cycles_run", 0) for a in agents)
        sum_orders = sum(getattr(a.state, "orders_placed", 0) for a in agents)
        out["cycle"] = max(int(out.get("cycle") or 0), max_cyc)
        out["agent_grid_cycles_total"] = sum_cycles
        out["agent_grid_agent_count"] = len(agents)
        # Prefer grid order count when CT tracker is idle
        out["orders_placed"] = max(int(out.get("orders_placed") or 0), sum_orders)
    elif ct_loop_running:
        out["pm_signal_source"] = "continuous_trader"
        out["pm_ct_loop_idle"] = False
    else:
        out.setdefault("pm_signal_source", "none")
        out["pm_ct_loop_idle"] = not ct_loop_running

    # Fresh execution gate (CT cache may be stale when its loop is off)
    try:
        from core.execution_gate import check_execution_gate

        _eg = check_execution_gate()
        _gd = _eg.to_dict()
        out["execution_gate_state"] = _gd.get("gate_state")
        out["execution_gate_blocked"] = _gd.get("blocked")
        out["execution_gate_safe_to_trade"] = _gd.get("safe_to_trade")
        out["execution_gate_reasons"] = _gd.get("reasons", [])
    except Exception as exc:
        logger.debug("execution_gate overlay: %s", exc)

    _pm_src = out.get("pm_signal_source")
    _eq_usd = 0.0
    _peak_usd = 0.0
    _live_usd = 0.0
    _risk_st = None
    try:
        # PM CYCLE WIRING: Use unified v2 bankroll service as primary source
        from merid.event_venues.kalshi.bankroll_service_v2 import (
            get_equity_for_risk_calc_sync, 
            get_summary_sync,
            get_bankroll_service,
        )
        _effective_usd = get_equity_for_risk_calc_sync() 
        _summary = get_summary_sync(caller_module="pm_bankroll_snapshot")
        _eq_usd = float(_effective_usd) if _effective_usd else 0.0
        _live_usd = float(_summary.equity_usd) if _summary and _summary.equity_usd else 0.0

        # Get peak/drawdown from risk manager for reporting (not for sizing)
        try:
            from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk
            _risk_st = get_kalshi_risk().state
            _peak_usd = float(_risk_st.peak_equity_usd or 0.0)
        except Exception:
            pass

        if _eq_usd > 0:
            _bal_cents = int(_eq_usd * 100)
            out["balance_cents"] = _bal_cents
            # Use centralized portfolio value calculation from v2 service (single source of truth)
            _portfolio_cents = 0
            try:
                service = asyncio.run(get_bankroll_service())
                _portfolio_cents = service.get_portfolio_value_cents_sync()
            except Exception as exc:
                logger.debug("[pm_bankroll_overlay] Failed to fetch portfolio value from v2 service: %s", exc)
            
            out["portfolio_cents"] = _portfolio_cents
            out["total_value_cents"] = _bal_cents + _portfolio_cents
            # Use live balance for peak/drawdown calculation if peak not tracked separately
            if _peak_usd > 0 and _eq_usd <= _peak_usd:
                out["peak_balance_cents"] = int(_peak_usd * 100)
                out["drawdown_pct"] = round((1.0 - _eq_usd / _peak_usd) * 100.0, 2)
            elif _live_usd > 0 and _eq_usd <= _live_usd:
                # Fallback: use live balance as peak if no tracked peak
                out["peak_balance_cents"] = int(_live_usd * 100)
                out["drawdown_pct"] = round((1.0 - _eq_usd / _live_usd) * 100.0, 2)
            out["pm_bankroll_equity_usd"] = round(_eq_usd, 2)
            out["pm_bankroll_live_usd"] = round(_live_usd, 2)
            out["pm_bankroll_source"] = "unified_bankroll_service"
    except Exception as exc:
        logger.debug("unified_bankroll overlay: %s", exc)

    # Kelly / risk-per-trade: CT TraderConfig env (Kelly caps). When AgentGrid owns PM,
    # headline ``initial_bankroll_cents`` must reflect live equity — not KALSHI_TRADER_BANKROLL placeholder.
    try:
        from merid.trading.kalshi_continuous_trader import TraderConfig

        tcfg = TraderConfig.from_env()
        cfg_block = out.get("config") or {}
        if not isinstance(cfg_block, dict):
            cfg_block = {}
        cfg_block.setdefault("initial_bankroll_cents", tcfg.initial_bankroll_cents)
        cfg_block["kelly_fraction"] = tcfg.kelly_fraction
        cfg_block["max_risk_per_trade_pct"] = tcfg.max_risk_per_trade_pct
        cfg_block.setdefault("drawdown_halt_pct", tcfg.drawdown_halt_pct)
        cfg_block.setdefault("drawdown_reduce_pct", tcfg.drawdown_reduce_pct)
        out["config"] = cfg_block
    except Exception as exc:
        logger.debug("TraderConfig overlay: %s", exc)

    if _pm_src == "agent_grid":
        if _eq_usd > 0:
            _bc = int(_eq_usd * 100)
            _cfg = out.get("config") or {}
            if not isinstance(_cfg, dict):
                _cfg = {}
            _cfg["initial_bankroll_cents"] = _bc
            _cfg["pm_reference_bankroll"] = "unified_bankroll_service"
            out["config"] = _cfg
        else:
            out["pm_equity_pending_sync"] = True
        # Get PnL from risk manager if available (regardless of bankroll state)
        if _risk_st is not None:
            out["total_pnl_cents"] = int(round(_risk_st.daily_pnl_usd * 100))
            out["total_fees_cents"] = int(round(_risk_st.daily_fees_usd * 100))

    if ct_err and not grid_on:
        out.setdefault("reason", ct_err)

    try:
        from merid.prediction import pm_ct_policy

        out["pm_ct_legacy_research_only"] = bool(pm_ct_policy.ct_loop_suppressed())
    except Exception:
        pass

    return out
