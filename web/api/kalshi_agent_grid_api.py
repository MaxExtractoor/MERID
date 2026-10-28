"""Kalshi Agent Grid API — read-only telemetry for ``LeanAgentGrid15m``.

All endpoints are defensive read/diagnostic surfaces over the real production
objects:

* ``request.app.state.agent_grid_15m``  — ``LeanAgentGrid15m`` (``_agents``,
  ``_running``, ``_executed_candidates``, ``_last_exchange_positions``,
  ``_last_open_orders``, ``position_cache``).
* ``request.app.state.kalshi_15m_loop`` — ``Kalshi15mLoop`` (``summary()``,
  ``_candidate_event_log``, ``_candidate_lifecycle_states``,
  ``_rejection_counters``, ``_best_edge_per_asset``,
  ``_executed_candidates_this_window``).
* ``KalshiMarketStateStore``            — quotes/depth/health per ticker.
* ``RestingOrderMonitor``               — actual working (resting) orders.
* ``KalshiPositionCache``               — canonical cached positions.
* ``RealizedEdgeStore``                 — realized-edge telemetry.
* ``KalshiFillsLedger`` / ``ExecutionGuard`` — fills and verdict telemetry.

Nothing in this module mutates trading, execution, risk, reconciliation, or
kill-switch state.  Where an attribute does not exist the response carries an
explicit ``null``/empty value plus ``available``/``error`` metadata — no
telemetry is fabricated.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request

from utils.logger import get_logger

logger = get_logger("web.api.kalshi_agent_grid_api")

router = APIRouter(prefix="/api/v1/kalshi-grid", tags=["Kalshi Agent Grid"])

# Routes provided here (all GET, read-only):
#   /summary            — grid + loop truth (was: broken grid.summary() wrapper)
#   /agents             — per-agent ServerAgent records from real telemetry
#   /agents/{asset}     — single agent detail
#   /decision-feed      — unified lifecycle/decision/verdict event feed
#   /edge-snapshots     — realized-edge trade records (RealizedEdgeStore)
#   /scheduler-metrics  — real loop/grid counters (replaces dead get_scheduler_metrics)
#   /edge-aggregations  — windowed realized-edge aggregates (replaces dead
#                         compute_edge_aggregations)
#
# NOTE: web/api/kalshi_grid_api.py (prefix="/kalshi-grid") is intentionally not
# mounted by main_15m_lean.py; this router is the only /api/v1 kalshi-grid
# surface.  Its start/stop/pause/resume endpoints are deliberately absent here —
# this module is diagnostic-only.

_BOOK_STALE_MS = 60_000
_ZOMBIE_SIGNAL_AGE_S = 900.0  # 15 min without a signal => zombie candidate


# ── Safe serialization ──────────────────────────────────────────────────

def _json_safe(value: Any, _depth: int = 0) -> Any:
    """Best-effort JSON-safe conversion.  Unknown objects -> str()."""
    if _depth > 6:
        return str(value)
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        out: Dict[str, Any] = {}
        for k, v in list(value.items())[:256]:
            try:
                out[str(k)] = _json_safe(v, _depth + 1)
            except Exception:
                out[str(k)] = str(v)
        return out
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v, _depth + 1) for v in list(value)[:200]]
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        try:
            return _json_safe(to_dict(), _depth + 1)
        except Exception:
            pass
    try:
        return str(value)
    except Exception:
        return None


def _f(val: Any) -> Optional[float]:
    """Float-or-None coercion (Decimal-aware, NaN/Inf filtered)."""
    if val is None:
        return None
    try:
        x = float(val)
    except (TypeError, ValueError):
        return None
    if x != x or x in (float("inf"), float("-inf")):
        return None
    return x


def _cents_to_usd(val: Any) -> Optional[float]:
    x = _f(val)
    return x / 100.0 if x is not None else None


def _usd_to_cents(val: Any) -> Optional[float]:
    x = _f(val)
    return x * 100.0 if x is not None else None


def _iso(ts: Any) -> Optional[str]:
    """Epoch-seconds or datetime -> ISO string, else None."""
    if ts is None:
        return None
    if isinstance(ts, datetime):
        return ts.isoformat()
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError, OverflowError):
        return str(ts) if isinstance(ts, str) else None


# ── Object accessors (all defensive) ────────────────────────────────────

def _get_grid(request: Request) -> Optional[Any]:
    grid = getattr(request.app.state, "agent_grid_15m", None)
    if grid is None:
        try:
            from merid.prediction.agent_grid_15m import get_agent_grid
            grid = get_agent_grid()
        except Exception as exc:
            logger.debug("agent_grid_15m unavailable: %s", exc)
            grid = None
    return grid


def _get_loop(request: Request) -> Optional[Any]:
    """The production 15m loop lives on app.state (see main_15m_lean.py)."""
    return (
        getattr(request.app.state, "kalshi_15m_loop", None)
        or getattr(request.app.state, "loop_15m", None)
    )


def _get_market_store(request: Request) -> Optional[Any]:
    store = getattr(request.app.state, "market_state_store", None)
    if store is None:
        try:
            from merid.event_venues.kalshi.market_state import (
                get_kalshi_market_state_store,
            )
            store = get_kalshi_market_state_store()
        except Exception as exc:
            logger.debug("market_state_store unavailable: %s", exc)
            store = None
    return store


def _get_position_cache() -> Optional[Any]:
    try:
        from merid.event_venues.kalshi.position_cache import get_position_cache
        return get_position_cache()
    except Exception as exc:
        logger.debug("position_cache unavailable: %s", exc)
        return None


def _get_resting_monitor(request: Request) -> Optional[Any]:
    mon = getattr(request.app.state, "resting_order_monitor", None)
    if mon is None:
        try:
            from merid.event_venues.kalshi.resting_order_monitor import (
                get_resting_order_monitor,
            )
            mon = get_resting_order_monitor()
        except Exception as exc:
            logger.debug("resting_order_monitor unavailable: %s", exc)
            mon = None
    return mon


def _terminal_statuses() -> frozenset:
    try:
        from merid.event_venues.kalshi.resting_order_monitor import TERMINAL_STATUSES
        return TERMINAL_STATUSES
    except Exception:
        return frozenset({"filled", "cancelled", "canceled", "rejected",
                          "expired", "gave_up"})


def _loop_summary(loop: Optional[Any]) -> Dict[str, Any]:
    if loop is None:
        return {}
    summary_fn = getattr(loop, "summary", None)
    if callable(summary_fn):
        try:
            out = summary_fn()
            if isinstance(out, dict):
                return out
        except Exception as exc:
            logger.debug("loop.summary() failed: %s", exc)
    # Minimal truth if summary() is missing/broken.
    running = getattr(loop, "is_running", getattr(loop, "_running", None))
    return {
        "running": bool(running) if running is not None else None,
        "tick": getattr(loop, "_tick", None),
        "cycle_count": getattr(loop, "_cycle_count", None),
        "error_count": getattr(loop, "_error_count", None),
        "cadence_seconds": getattr(loop, "cadence_seconds", None),
        "last_cycle_at": _iso(getattr(loop, "_last_cycle_at", None)),
        "started_at": _iso(getattr(loop, "_started_at", None)),
        "halted_due_to_drawdown": getattr(loop, "_halted_due_to_drawdown", None),
    }


def _loop_cycle_age_ms(loop: Optional[Any]) -> Optional[float]:
    """Wall-clock age of the last completed loop cycle (ms)."""
    if loop is None:
        return None
    last = getattr(loop, "_last_cycle_at", None)
    if last is None:
        return None
    try:
        if isinstance(last, datetime):
            ref = last if last.tzinfo else last.replace(tzinfo=timezone.utc)
            return (datetime.now(timezone.utc) - ref).total_seconds() * 1000.0
        return (time.time() - float(last)) * 1000.0
    except (TypeError, ValueError, OSError):
        return None


# ── Per-agent extraction helpers ────────────────────────────────────────

def _agent_name(agent: Any) -> Optional[str]:
    cfg = getattr(agent, "config", None)
    name = getattr(cfg, "name", None)
    return str(name) if name else None


def _agent_series_prefixes(agent: Any) -> List[str]:
    cfg = getattr(agent, "config", None)
    tickers = getattr(cfg, "series_tickers", None) or []
    return [str(t).upper() for t in tickers if t]


def _agent_asset(agent: Any) -> Optional[str]:
    """BTC/ETH/SOL/... derived from the series prefix, else config name."""
    prefixes = _agent_series_prefixes(agent)
    if prefixes:
        p = prefixes[0]
        if p.startswith("KX"):
            p = p[2:]
        if p.endswith("15M"):
            p = p[:-3]
        if p:
            return p
    name = _agent_name(agent)
    if name:
        return name.split("_")[0].upper()
    return None


def _agent_cycle_decision(agent: Any) -> Dict[str, Any]:
    cd = getattr(agent, "_cycle_decision", None)
    return cd if isinstance(cd, dict) else {}


def _agent_enabled(agent: Any) -> bool:
    """No universal `enabled` flag exists on LeanAgent15m — defensive only."""
    for attr in ("enabled", "is_enabled"):
        val = getattr(agent, attr, None)
        if isinstance(val, bool):
            return val
    return True  # Agents in the live grid are evaluated every cycle.


def _resolve_agent_ticker(agent: Any, grid: Optional[Any], store: Optional[Any]) -> Optional[str]:
    """Resolve the agent's currently tracked market ticker (real sources only)."""
    # 1) agent's own per-cycle market-id map {strip_ticker: market_id}
    for strip, mid in (getattr(agent, "_current_market_ids", None) or {}).items():
        if mid:
            return str(mid)
    # 2) cycle decision / pdr context ticker
    cd = _agent_cycle_decision(agent)
    for key in ("ticker", "market_id"):
        if cd.get(key):
            return str(cd[key])
    pdr = getattr(agent, "_pdr_ctx", None)
    if isinstance(pdr, dict) and pdr.get("ticker"):
        return str(pdr["ticker"])
    # 3) grid-level map matched to this agent's series prefixes
    prefixes = _agent_series_prefixes(agent)
    grid_ids = getattr(grid, "_current_market_ids", None) or {}
    for strip, mid in grid_ids.items():
        hay = f"{strip}|{mid}".upper()
        if any(p in hay for p in prefixes):
            return str(mid)
    # 4) market-state store scan for a live market on the agent's series
    if store is not None and prefixes:
        try:
            tickers = store.get_all_tickers() if hasattr(store, "get_all_tickers") else (
                list(getattr(store, "tickers", lambda: [])()))
        except Exception:
            tickers = []
        for t in tickers or []:
            if any(str(t).upper().startswith(p) for p in prefixes):
                return str(t)
    return None


def _market_block(state: Optional[Any]) -> Optional[Dict[str, Any]]:
    if state is None:
        return None
    book_age_ms = None
    wall_ts = getattr(state, "last_book_update_wall_ts", 0.0) or 0.0
    if wall_ts > 0:
        book_age_ms = (time.time() - wall_ts) * 1000.0
    elif getattr(state, "age_ms", None) is not None:
        book_age_ms = _f(getattr(state, "age_ms"))
    bid = _f(getattr(state, "best_bid_cents", None))
    ask = _f(getattr(state, "best_ask_cents", None))
    spread = _f(getattr(state, "spread_cents", None))
    if spread is None and bid is not None and ask is not None:
        spread = ask - bid
    return {
        "ticker": getattr(state, "ticker", None),
        "strike": _f(getattr(state, "floor_strike", None)) or _f(getattr(state, "strike_price", None)),
        "yes_bid_c": bid,
        "yes_ask_c": ask,
        "no_bid_c": _f(getattr(state, "best_no_bid_cents", None)),
        "no_ask_c": _f(getattr(state, "best_no_ask_cents", None)),
        "mid_c": _f(getattr(state, "mid_cents", None)),
        "spread_c": spread,
        "secs_to_close": _f(getattr(state, "seconds_to_expiry", None)),
        "status": getattr(state, "status", None),
        "book_age_ms": book_age_ms,
        "book_fresh": (book_age_ms is not None and book_age_ms <= _BOOK_STALE_MS),
        "ws_last_event_age_ms": _f(getattr(state, "ws_last_event_age_ms", None)),
        "last_update_ts": _f(getattr(state, "last_update_ts", None)),
        "last_price_c": _f(getattr(state, "last_price_cents", None)),
        "external_spot": _f(getattr(state, "external_spot", None)),
        "model_fair_prob": _f(getattr(state, "model_fair_prob", None)),
        "annualized_vol": _f(getattr(state, "annualized_vol", None)),
        "min_depth_yes": getattr(state, "min_depth_yes", None),
        "min_depth_no": getattr(state, "min_depth_no", None),
        "depth_10c_yes": getattr(state, "depth_10c_yes", None),
        "depth_10c_no": getattr(state, "depth_10c_no", None),
        "executable": getattr(state, "executable", None),
        "book_health": getattr(state, "book_health", None),
        "data_quality": getattr(state, "data_quality", None),
        "exchange_index": getattr(state, "exchange_index", None),
    }


def _live_resting_orders(mon: Optional[Any], prefixes: List[str]) -> List[Any]:
    """Actual live working orders on the agent's series (never inferred)."""
    if mon is None or not prefixes:
        return []
    terminal = _terminal_statuses()
    try:
        records = mon.get_all_orders() if hasattr(mon, "get_all_orders") else []
    except Exception as exc:
        logger.debug("resting_order_monitor.get_all_orders failed: %s", exc)
        return []
    out = []
    for rec in records or []:
        t = str(getattr(rec, "ticker", "") or "").upper()
        if not any(t.startswith(p) for p in prefixes):
            continue
        status = str(getattr(rec, "status", "") or "").lower()
        remaining = getattr(rec, "remaining_size", None)
        if status in terminal:
            continue
        if remaining is not None and remaining <= 0:
            continue
        out.append(rec)
    return out


def _order_dict(rec: Any) -> Dict[str, Any]:
    return {
        "kalshi_order_id": getattr(rec, "kalshi_order_id", None),
        "ticker": getattr(rec, "ticker", None),
        "side": getattr(rec, "side", None),
        "price_cents": getattr(rec, "price_cents", None),
        "remaining_size": getattr(rec, "remaining_size", None),
        "filled_size": getattr(rec, "filled_size", None),
        "original_size": getattr(rec, "original_size", None),
        "status": getattr(rec, "status", None),
        "decision_lane": getattr(rec, "decision_lane", None),
        "created_at": _iso(getattr(rec, "created_at", None)),
    }


def _positions_for_agent(
    agent: Any, grid: Optional[Any], prefixes: List[str]
) -> List[Dict[str, Any]]:
    """Positions on the agent's series from position_cache, then the grid's
    last exchange snapshot.  Returns normalized dicts."""
    out: List[Dict[str, Any]] = []
    seen: set = set()
    cache = _get_position_cache()
    if cache is not None and prefixes:
        try:
            all_pos = cache.get_all_positions(validate_freshness=False)
        except Exception as exc:
            logger.debug("position_cache.get_all_positions failed: %s", exc)
            all_pos = {}
        for mid, pos in (all_pos or {}).items():
            t = str(mid or getattr(pos, "market_id", "") or "").upper()
            if not any(t.startswith(p) for p in prefixes):
                continue
            qty = getattr(pos, "quantity_cc", None)
            if qty in (None, 0):
                continue
            seen.add(str(mid))
            out.append({
                "market_id": getattr(pos, "market_id", None) or mid,
                "side": getattr(pos, "side", None),
                "qty_centi": qty,
                "avg_price_c": _f(getattr(pos, "avg_price_cents", None)),
                "realized_pnl_c": _usd_to_cents(getattr(pos, "realized_pnl_usd", None)),
                "unrealized_pnl_c": _usd_to_cents(getattr(pos, "unrealized_pnl_usd", None)),
                "exits_armed": bool(
                    getattr(pos, "exit_policy_id", None)
                    or getattr(pos, "stop_loss_enabled", False)
                    or getattr(pos, "stop_loss_price_cents", None)
                    or getattr(pos, "take_profit_price_cents", None)
                ),
                "source": "position_cache",
            })
    # Fallback/cross-check: grid's last REST exchange snapshot.
    for row in getattr(grid, "_last_exchange_positions", None) or []:
        try:
            mid = str(row.get("market_id") or "").upper()
            if not any(mid.startswith(p) for p in prefixes) or mid in seen:
                continue
            qty = row.get("quantity_cc")
            if qty in (None, 0):
                continue
            out.append({
                "market_id": row.get("market_id"),
                "side": row.get("side"),
                "qty_centi": qty,
                "avg_price_c": _f(row.get("avg_price_cents")),
                "realized_pnl_c": _usd_to_cents(row.get("realized_pnl")),
                "unrealized_pnl_c": _usd_to_cents(row.get("unrealized_pnl")),
                "exits_armed": None,
                "source": "exchange_snapshot",
            })
        except Exception:
            continue
    return out


def _edge_block(cycle: Dict[str, Any]) -> Dict[str, Any]:
    side = cycle.get("selected_side")
    edge_pct = None
    if side == "yes":
        edge_pct = cycle.get("edge_yes_pct")
    elif side == "no":
        edge_pct = cycle.get("edge_no_pct")
    # Thresholds/edges inside _cycle_decision are probability fractions
    # (0.0-1.0); *-cents keys are already cents.  No unit guessing.
    threshold_c = None
    for k in ("ev_threshold_cents", "required_edge_cents", "edge_threshold_cents"):
        if _f(cycle.get(k)) is not None:
            threshold_c = _f(cycle[k])
            break
    if threshold_c is None and _f(cycle.get("edge_threshold")) is not None:
        threshold_c = _f(cycle["edge_threshold"]) * 100.0
    net_ev_c = _f(cycle.get("ev_net_cents"))
    if net_ev_c is None and _f(cycle.get("robust_ev_cents")) is not None:
        net_ev_c = _f(cycle["robust_ev_cents"])
    if net_ev_c is None and _f(cycle.get("net_edge")) is not None:
        net_ev_c = _f(cycle["net_edge"]) * 100.0
    return {
        "net_ev_c": net_ev_c,
        "threshold_c": threshold_c,
        "model_p": _f(cycle.get("model_p_yes")) or _f(cycle.get("model_prob"))
            or _f(cycle.get("p_yes")),
        "market_p": _f(cycle.get("market_prob")) or _f(cycle.get("p_implied")),
        "calibrated": bool(
            cycle.get("walkforward_cal_applied")
            or cycle.get("tail_calibration_yes_applied")
            or cycle.get("tail_calibration_no_applied")
            or cycle.get("streaming_cal_applied")
        ) or None,
        "selected_side": side,
        "edge_pct": _f(edge_pct),
        "all_in_cost_c": _f(cycle.get("all_in_cost_cents")),
    }


def _waterfall_list(agent: Any) -> List[Dict[str, Any]]:
    """Normalize {stages:{name:{status,reason}}, final_reason} -> compact list."""
    wf: Dict[str, Any] = {}
    try:
        fn = getattr(agent, "get_rejection_waterfall", None)
        if callable(fn):
            wf = fn() or {}
        else:
            raw = getattr(agent, "_rejection_waterfall", None)
            wf = raw if isinstance(raw, dict) else {}
    except Exception:
        wf = {}
    stages = wf.get("stages") or {}
    final_reason = wf.get("final_reason") or ""
    out = []
    if isinstance(stages, dict):
        for name, st in stages.items():
            status = bool(st.get("status", True)) if isinstance(st, dict) else None
            reason = (st.get("reason") or "") if isinstance(st, dict) else ""
            out.append({
                "stage": str(name),
                "rejected": (status is False),
                "final_reason": reason or (final_reason if status is False else ""),
            })
    if not out and final_reason:
        out.append({"stage": "final", "rejected": True, "final_reason": final_reason})
    return out


def _heartbeat_block(
    agent: Any, loop: Optional[Any], market: Optional[Dict[str, Any]], state: Optional[Any]
) -> Dict[str, Any]:
    return {
        "last_eval_ms": _loop_cycle_age_ms(loop),
        "book_age_ms": (market or {}).get("book_age_ms"),
        "watermark_ms": _f(getattr(state, "ws_last_event_age_ms", None)) if state else None,
        "spot_age_ms": _f(getattr(agent, "_last_velocity_age_ms", None)),
    }


def _lanes_block(agent: Any, cycle: Dict[str, Any], orders: List[Any]) -> List[Dict[str, Any]]:
    lanes: Dict[str, Dict[str, Any]] = {}
    for rec in orders:
        lane = getattr(rec, "decision_lane", None)
        if not lane:
            continue
        entry = lanes.setdefault(str(lane), {
            "lane": str(lane), "status": "working_order",
            "reason": None, "last_order_ts": None,
        })
        ts = _iso(getattr(rec, "created_at", None))
        if ts and (entry["last_order_ts"] is None or ts > entry["last_order_ts"]):
            entry["last_order_ts"] = ts
    for key in ("decision_lane", "entry_lane", "admission_owner", "lane"):
        lane = cycle.get(key)
        if lane and str(lane) not in lanes:
            rejected = bool(cycle.get("rejection_reason"))
            lanes[str(lane)] = {
                "lane": str(lane),
                "status": "vetoed" if rejected else ("selected" if cycle.get("selected_side") else "observed"),
                "reason": cycle.get("rejection_reason") or None,
                "last_order_ts": None,
            }
    return list(lanes.values())


def _pnl_block(agent: Any, asset: Optional[str], positions: List[Dict[str, Any]]) -> Dict[str, Any]:
    realized_c = 0.0
    have_realized = False
    for p in positions:
        if p.get("realized_pnl_c") is not None:
            realized_c += p["realized_pnl_c"]
            have_realized = True
    session_c = None
    hist = getattr(agent, "_rolling_pnl_history", None) or {}
    entries = hist.get(asset or "", []) if isinstance(hist, dict) else []
    if entries:
        now = time.time()
        session_c = sum(
            float(pnl) * 100.0
            for ts, pnl in entries
            if isinstance(ts, (int, float)) and (now - ts) <= 900.0
        )
        if not have_realized:
            realized_c = sum(float(pnl) * 100.0 for _, pnl in entries)
            have_realized = True
    fills_24h = None
    try:
        from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
        since = datetime.now(timezone.utc) - timedelta(hours=24)
        fills_24h = len(get_fills_ledger().get_fills(since=since, asset=asset, limit=1000))
    except Exception as exc:
        logger.debug("fills_ledger.get_fills unavailable: %s", exc)
    return {
        "realized_c": realized_c if have_realized else None,
        "session_c": session_c,
        "fills_24h": fills_24h,
    }


def _server_agent(
    agent: Any, grid: Optional[Any], loop: Optional[Any], store: Optional[Any],
    mon: Optional[Any],
) -> Dict[str, Any]:
    name = _agent_name(agent)
    asset = _agent_asset(agent)
    prefixes = _agent_series_prefixes(agent)
    cycle = _agent_cycle_decision(agent)
    grid_running = bool(getattr(grid, "_running", False)) if grid is not None else False
    enabled = _agent_enabled(agent)

    ticker = _resolve_agent_ticker(agent, grid, store)
    state = None
    if ticker and store is not None:
        try:
            state = store.get(ticker)
        except Exception:
            state = None
    market = _market_block(state)

    orders = _live_resting_orders(mon, prefixes)
    positions = _positions_for_agent(agent, grid, prefixes)
    position_for_ticker = next(
        (p for p in positions if str(p.get("market_id") or "").upper() == str(ticker or "").upper()),
        positions[0] if positions else None,
    )

    rejection_reason = (
        cycle.get("rejection_reason")
        or (getattr(agent, "_last_signal_rejection", {}) or {}).get("reason")
        or None
    )
    wf = getattr(agent, "_rejection_waterfall", {}) or {}
    if not rejection_reason:
        rejection_reason = wf.get("final_reason") or None

    # has_signal: True only when the cycle recorded an actual selection.
    if cycle.get("rejection_reason"):
        has_signal: Optional[bool] = False
    elif cycle.get("selected_side") or cycle.get("ev_net_cents") is not None \
            or cycle.get("model_prob") is not None:
        has_signal = True
    else:
        has_signal = None  # undeterminable — no signal telemetry recorded

    # trend_aligned from the cached indicator snapshot (never recompute here).
    trend_aligned = None
    stack = (getattr(agent, "_indicator_stacks", None) or {}).get(asset)
    snap = getattr(stack, "_last_snapshot", None) if stack is not None else None
    if snap is not None:
        trend_aligned = getattr(snap, "trend_aligned", None)

    last_signal_ts = getattr(agent, "last_signal_ts", None)

    # Zombie detection: only when staleness is provable — absent evidence is
    # NOT reported as healthy ("False" here means "not observed as zombie").
    is_zombie = False
    if enabled and grid_running:
        if isinstance(last_signal_ts, (int, float)) and last_signal_ts > 0:
            is_zombie = (time.time() - last_signal_ts) > _ZOMBIE_SIGNAL_AGE_S
        else:
            pdr = getattr(agent, "_pdr_ctx", None)
            pdr_tick = pdr.get("tick") if isinstance(pdr, dict) else None
            loop_tick = getattr(loop, "_tick", None)
            cadence = getattr(loop, "cadence_seconds", None) or 5.0
            if isinstance(pdr_tick, int) and isinstance(loop_tick, int) and cadence > 0:
                stale_ticks = max(int(_ZOMBIE_SIGNAL_AGE_S / cadence), 1)
                is_zombie = (loop_tick - pdr_tick) > stale_ticks

    # State priority: STALE_FEED > HALTED > IN_POSITION > WORKING_ORDER >
    # VETOED > SCANNING.
    book_age = (market or {}).get("book_age_ms")
    if book_age is not None and book_age > _BOOK_STALE_MS:
        agent_state = "STALE_FEED"
    elif not enabled or not grid_running:
        agent_state = "HALTED"
    elif positions:
        agent_state = "IN_POSITION"
    elif orders:
        agent_state = "WORKING_ORDER"
    elif rejection_reason:
        agent_state = "VETOED"
    else:
        agent_state = "SCANNING"

    session_risk = getattr(agent, "_session_risk_usd", None)
    session_risk_cap = getattr(agent, "_session_risk_cap_usd", None)

    return {
        "id": name,
        "name": name,
        "asset": asset,
        "running": bool(grid_running and enabled),
        "enabled": enabled,
        "current_task": getattr(agent, "current_task", None)
            or getattr(agent, "_current_task", None),
        "state": agent_state,
        "last_signal_ts": _iso(last_signal_ts) if last_signal_ts else None,
        "position_count": len(positions),
        "working_order": bool(orders),
        "has_signal": has_signal,
        "trend_aligned": trend_aligned,
        "risk_budget_used": _f(session_risk),
        "risk_budget_cap_usd": _f(session_risk_cap),
        "rejected_reason": rejection_reason,
        "heartbeat": _heartbeat_block(agent, loop, market, state),
        "market": market,
        "position": position_for_ticker,
        "edge": _edge_block(cycle),
        "pnl": _pnl_block(agent, asset, positions),
        "lanes": _lanes_block(agent, cycle, orders),
        "working_orders": [_order_dict(r) for r in orders],
        "cycle_decision": _json_safe(cycle),
        "rejection_waterfall": _waterfall_list(agent),
        "is_zombie": is_zombie,
        "run_id": getattr(agent, "run_id", None),
    }


# ── Endpoints ───────────────────────────────────────────────────────────

@router.get("/summary")
async def get_grid_summary(request: Request) -> Dict[str, Any]:
    """Truthful grid + loop summary from the real ``LeanAgentGrid15m``."""
    grid = _get_grid(request)
    loop = _get_loop(request)
    if grid is None:
        return {
            "available": False,
            "reason": "agent_grid_15m not initialized (loop may not have started)",
            "running": False,
            "agent_count": 0,
            "loop": _json_safe(_loop_summary(loop)),
        }

    agents = getattr(grid, "_agents", []) or []
    loop_summary = _loop_summary(loop)
    agent_rows = []
    for agent in agents:
        agent_rows.append({
            "name": _agent_name(agent),
            "asset": _agent_asset(agent),
            "rejection_reason": _agent_cycle_decision(agent).get("rejection_reason") or None,
        })

    return {
        "available": True,
        "running": bool(getattr(grid, "_running", False)),
        "agent_count": len(agents),
        "agents": agent_rows,
        "executed_candidates": sorted(
            str(c) for c in (getattr(grid, "_executed_candidates", None) or set())
        )[:200],
        "exchange_positions": len(getattr(grid, "_last_exchange_positions", None) or []),
        "open_orders": len(getattr(grid, "_last_open_orders", None) or []),
        "loop": _json_safe(loop_summary),
    }


@router.get("/agents")
async def list_agents(request: Request) -> Dict[str, Any]:
    """Per-agent records built from real grid/agent telemetry."""
    grid = _get_grid(request)
    loop = _get_loop(request)
    if grid is None:
        return {"available": False, "reason": "agent_grid_15m not initialized",
                "count": 0, "agents": []}
    store = _get_market_store(request)
    mon = _get_resting_monitor(request)
    agents = getattr(grid, "_agents", []) or []
    return {
        "available": True,
        "running": bool(getattr(grid, "_running", False)),
        "count": len(agents),
        "agents": [_server_agent(a, grid, loop, store, mon) for a in agents],
    }


@router.get("/agents/{asset}")
async def get_agent_detail(asset: str, request: Request) -> Dict[str, Any]:
    """Single-agent detail — matched by asset (BTC) or config name (BTC_15M)."""
    grid = _get_grid(request)
    if grid is None:
        return {"available": False, "reason": "agent_grid_15m not initialized",
                "agent": None}
    loop = _get_loop(request)
    store = _get_market_store(request)
    mon = _get_resting_monitor(request)
    wanted = asset.upper()
    for agent in getattr(grid, "_agents", []) or []:
        if _agent_asset(agent) == wanted or (_agent_name(agent) or "").upper() == wanted:
            return {"available": True, "agent": _server_agent(agent, grid, loop, store, mon)}
    raise HTTPException(status_code=404, detail=f"Unknown agent asset/name: {asset}")


@router.get("/decision-feed")
async def get_decision_feed(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    asset: Optional[str] = Query(None, description="Filter by asset (e.g. BTC)"),
) -> Dict[str, Any]:
    """Unified decision event feed from real sources:

    * ``Kalshi15mLoop._candidate_event_log`` — lifecycle transitions.
    * ``Kalshi15mLoop._executed_candidates_this_window`` — window executions.
    * Each agent's ``_cycle_decision`` — latest per-cycle decision snapshot.
    * ``ExecutionGuard.recent_verdicts`` — pre-trade guard verdicts.
    """
    events: List[Dict[str, Any]] = []
    grid = _get_grid(request)
    loop = _get_loop(request)
    wanted = asset.upper() if asset else None

    def _keep(ev_asset: Optional[str]) -> bool:
        return wanted is None or (ev_asset or "").upper() == wanted

    # 1) Candidate lifecycle transitions (authoritative, timestamped).
    for ev in (getattr(loop, "_candidate_event_log", None) or [])[-500:]:
        try:
            ctx = ev.get("context") or {}
            ev_asset = ctx.get("asset")
            if not _keep(ev_asset):
                continue
            to_state = str(ev.get("to_state") or "")
            up = to_state.upper()
            if any(k in up for k in ("EXECUT", "FILL")):
                kind = "fill"
            elif any(k in up for k in ("SUBMIT", "ORDER")):
                kind = "order"
            elif any(k in up for k in ("BLOCK", "REJECT", "VETO")):
                kind = "veto"
            elif any(k in up for k in ("SUPPRESS", "SKIP", "DUPLICATE")):
                kind = "skip"
            elif "EXIT" in up:
                kind = "exit"
            elif "SETTLE" in up:
                kind = "settle"
            else:
                kind = "state"
            events.append({
                "ts": _iso((ev.get("timestamp_ms") or 0) / 1000.0) if ev.get("timestamp_ms") else None,
                "_sort_ts": float(ev.get("timestamp_ms") or 0) / 1000.0,
                "kind": kind,
                "state": to_state or None,
                "reason": ev.get("reason") or None,
                "candidate_id": ev.get("candidate_id"),
                "agent": ctx.get("agent") or ctx.get("agent_id"),
                "asset": ev_asset,
                "ticker": ctx.get("ticker"),
                "side": ctx.get("side"),
                "decision_lane": ctx.get("decision_lane") or ctx.get("lane"),
                "source": ctx.get("source") or "candidate_lifecycle",
                "detail": _json_safe({k: v for k, v in ctx.items()
                                      if k not in {"asset", "ticker", "side", "source"}}),
            })
        except Exception:
            continue

    # 2) Per-window executed candidates (dicts with timestamp/edge/status).
    exec_win = getattr(loop, "_executed_candidates_this_window", None) or {}
    try:
        items = exec_win.items() if isinstance(exec_win, dict) else []
        for key, cand in items:
            if not isinstance(cand, dict):
                continue
            ev_asset = cand.get("asset")
            if not _keep(ev_asset):
                continue
            events.append({
                "ts": _iso(cand.get("timestamp")),
                "_sort_ts": float(cand.get("timestamp") or 0),
                "kind": "order" if cand.get("has_execution") else "state",
                "state": cand.get("status"),
                "reason": None,
                "candidate_id": cand.get("candidate_id"),
                "agent": cand.get("agent_id"),
                "asset": ev_asset,
                "ticker": cand.get("ticker"),
                "side": cand.get("side"),
                "decision_lane": cand.get("decision_lane") or cand.get("entry_lane"),
                "source": "executed_candidates_this_window",
                "detail": {"edge_pct": cand.get("edge_pct"),
                           "window_key": str(key)},
            })
    except Exception:
        pass

    # 3) Latest per-agent cycle decision snapshot.
    cycle_ts = _iso(getattr(loop, "_last_cycle_at", None))
    for agent in (getattr(grid, "_agents", []) or []):
        try:
            cd = _agent_cycle_decision(agent)
            if not cd:
                continue
            ev_asset = _agent_asset(agent)
            if not _keep(ev_asset):
                continue
            reason = cd.get("rejection_reason")
            kind = "veto" if reason else ("signal" if cd.get("selected_side") else "scan")
            events.append({
                "ts": cycle_ts,
                "_sort_ts": float(getattr(loop, "_last_cycle_at", None) and
                                (getattr(loop, "_last_cycle_at").timestamp()
                                 if isinstance(getattr(loop, "_last_cycle_at"), datetime) else 0) or 0),
                "kind": kind,
                "state": None,
                "reason": reason or None,
                "candidate_id": cd.get("candidate_id"),
                "agent": _agent_name(agent),
                "asset": ev_asset,
                "ticker": cd.get("ticker"),
                "side": cd.get("selected_side"),
                "decision_lane": cd.get("decision_lane") or cd.get("entry_lane"),
                "source": "agent_cycle_decision",
                "detail": _json_safe(cd),
            })
        except Exception:
            continue

    # 4) Execution guard verdicts.
    try:
        from merid.execution_guard import get_execution_guard
        for v in get_execution_guard().recent_verdicts(limit=limit):
            if not isinstance(v, dict):
                continue
            ev_asset = (v.get("domain") or "").split("_")[0] or None
            if not _keep(ev_asset):
                continue
            allowed = v.get("allowed")
            events.append({
                "ts": _iso(v.get("ts")),
                "_sort_ts": float(v.get("ts") or 0),
                "kind": "guard",
                "state": "allowed" if allowed else "blocked",
                "reason": v.get("reason"),
                "candidate_id": v.get("plan_id"),
                "agent": None,
                "asset": ev_asset,
                "ticker": None,
                "side": None,
                "decision_lane": v.get("domain"),
                "source": "execution_guard",
                "detail": _json_safe(v),
            })
    except Exception as exc:
        logger.debug("execution_guard verdicts unavailable: %s", exc)

    events.sort(key=lambda e: e.get("_sort_ts") or 0.0, reverse=True)
    events = events[:limit]
    for e in events:
        e.pop("_sort_ts", None)
    return {"available": grid is not None or loop is not None,
            "count": len(events), "events": events}


@router.get("/edge-snapshots")
async def get_edge_snapshots(
    request: Request,
    asset: Optional[str] = Query(None, description="Asset ticker (e.g., BTC, ETH)"),
    market_id: Optional[str] = Query(None, description="Explicit market ticker"),
    limit: int = Query(100, ge=1, le=500),
) -> Dict[str, Any]:
    """Realized-edge trade records (``TradeEdgeRecord``) — replaces the old
    deprecated stub.  Snapshots are captured at entry time by
    ``RealizedEdgeStore`` and carry realized PnL/edge once resolved."""
    try:
        from merid.metrics.realized_edge import get_realized_edge_store
        store = get_realized_edge_store()
    except Exception as exc:
        logger.warning("realized edge store unavailable: %s", exc)
        return {"available": False, "reason": str(exc),
                "asset": asset, "market_id": market_id,
                "count": 0, "snapshots": []}

    markets: List[str] = []
    if market_id:
        markets = [market_id]
    elif asset:
        # Resolve the asset's currently tracked market via the grid/store.
        grid = _get_grid(request)
        mstore = _get_market_store(request)
        for agent in getattr(grid, "_agents", []) or []:
            if _agent_asset(agent) == asset.upper():
                t = _resolve_agent_ticker(agent, grid, mstore)
                if t:
                    markets.append(t)
    else:
        try:
            markets = list(store.get_unresolved_markets())[:25]
        except Exception:
            markets = []

    records = []
    for m in markets:
        try:
            records.extend(store.get_trades_for_market(m))
        except Exception as exc:
            logger.debug("get_trades_for_market(%s) failed: %s", m, exc)
    records.sort(key=lambda r: r.timestamp or 0.0, reverse=True)
    snapshots = [r.to_dict() for r in records[:limit]]
    return {
        "available": True,
        "asset": asset,
        "market_id": market_id,
        "markets_queried": markets,
        "count": len(snapshots),
        "snapshots": snapshots,
    }


@router.get("/scheduler-metrics")
async def get_scheduler_metrics(
    request: Request,
    asset: Optional[str] = Query(None, description="Asset ticker (optional; aggregate if omitted)"),
) -> Dict[str, Any]:
    """Scheduler/loop counters from the real ``Kalshi15mLoop`` + grid.

    Replaces the removed ``get_scheduler_metrics()`` compatibility API with
    truthful counters: tick/cycle/error counts, cadence, rejection breakdown,
    candidate lifecycle states, and per-asset best-edge tracking.
    """
    grid = _get_grid(request)
    loop = _get_loop(request)
    if grid is None and loop is None:
        return {"available": False,
                "reason": "agent grid and 15m loop not initialized"}

    loop_summary = _loop_summary(loop)

    rejection_counters = getattr(loop, "_rejection_counters", None)
    try:
        rejection_counters = dict(rejection_counters) if rejection_counters else {}
    except Exception:
        rejection_counters = {}

    lifecycle = getattr(loop, "_candidate_lifecycle_states", None) or {}
    lifecycle_counts: Dict[str, int] = {}
    try:
        for state_name in lifecycle.values():
            lifecycle_counts[str(state_name)] = lifecycle_counts.get(str(state_name), 0) + 1
    except Exception:
        lifecycle_counts = {}

    best_edge = getattr(loop, "_best_edge_per_asset", None) or {}
    per_asset: Dict[str, Any] = {}
    agents = getattr(grid, "_agents", []) or []
    for agent in agents:
        a = _agent_asset(agent)
        if not a:
            continue
        cd = _agent_cycle_decision(agent)
        be = best_edge.get(a)
        per_asset[a] = {
            "agent": _agent_name(agent),
            "rejection_reason": cd.get("rejection_reason") or None,
            "selected_side": cd.get("selected_side") or None,
            "ticker": cd.get("ticker") or None,
            "best_edge": _json_safe(
                {k: v for k, v in be.items() if k != "candidate"}
            ) if isinstance(be, dict) else None,
        }

    out: Dict[str, Any] = {
        "available": True,
        "loop": _json_safe(loop_summary),
        "scheduler": {
            "tick": getattr(loop, "_tick", None),
            "cycle_count": getattr(loop, "_cycle_count", None),
            "error_count": getattr(loop, "_error_count", None),
            "cadence_seconds": getattr(loop, "cadence_seconds", None),
            "halted_due_to_drawdown": getattr(loop, "_halted_due_to_drawdown", None),
            "candidate_events_logged": len(getattr(loop, "_candidate_event_log", None) or []),
            "lifecycle_states": lifecycle_counts,
            "executed_candidates_this_window": len(
                getattr(loop, "_executed_candidates_this_window", None) or {}),
            "grid_executed_candidates": len(
                getattr(grid, "_executed_candidates", None) or set()),
            "exchange_positions": len(getattr(grid, "_last_exchange_positions", None) or []),
            "open_orders": len(getattr(grid, "_last_open_orders", None) or []),
        },
        "rejection_counters": rejection_counters,
        "per_asset": per_asset,
    }
    if asset:
        out["asset"] = asset.upper()
        out["asset_metrics"] = per_asset.get(asset.upper())
    return out


@router.get("/edge-aggregations")
async def get_edge_aggregations(
    request: Request,
    asset: str = Query(..., description="Asset ticker (e.g., BTC, ETH)"),
    window_minutes: int = Query(15, ge=1, le=1440),
) -> Dict[str, Any]:
    """Windowed realized-edge aggregates per asset.

    Built from ``RealizedEdgeStore`` trade records: markets touched in the
    window are enumerated from the canonical fills ledger, then each market's
    edge records are aggregated.  Lifetime ``EdgeStats`` rows matching the
    asset's forecaster are included for reference.  Returns explicit empty
    aggregates (not fabricated stats) when no trades exist in the window.
    """
    since_ts = time.time() - window_minutes * 60.0
    since_dt = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)
    asset_u = asset.upper()

    markets: List[str] = []
    try:
        from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
        for f in get_fills_ledger().get_fills(since=since_dt, asset=asset_u, limit=1000):
            if f.market_ticker and f.market_ticker not in markets:
                markets.append(f.market_ticker)
    except Exception as exc:
        logger.debug("fills ledger unavailable for edge aggregations: %s", exc)

    # Always include the asset's currently tracked market (it may have edge
    # records with no fills yet).
    grid = _get_grid(request)
    mstore = _get_market_store(request)
    for agent in getattr(grid, "_agents", []) or []:
        if _agent_asset(agent) == asset_u:
            t = _resolve_agent_ticker(agent, grid, mstore)
            if t and t not in markets:
                markets.append(t)

    try:
        from merid.metrics.realized_edge import get_realized_edge_store
        store = get_realized_edge_store()
    except Exception as exc:
        logger.warning("realized edge store unavailable: %s", exc)
        return {"available": False, "reason": str(exc), "asset": asset_u,
                "window_minutes": window_minutes, "count": 0, "aggregation": None}

    recs = []
    for m in markets:
        try:
            recs.extend(r for r in store.get_trades_for_market(m)
                        if (r.timestamp or 0) >= since_ts)
        except Exception as exc:
            logger.debug("get_trades_for_market(%s) failed: %s", m, exc)

    resolved = [r for r in recs if r.resolved]
    sum_est = sum(r.est_edge for r in resolved)
    sum_real = sum(r.realized_edge or 0.0 for r in resolved)
    wins = sum(1 for r in resolved if (r.realized_pnl_cents or 0) > 0)
    losses = sum(1 for r in resolved if (r.realized_pnl_cents or 0) <= 0)
    agg = {
        "trade_count": len(recs),
        "resolved_count": len(resolved),
        "mean_est_edge": round(sum_est / len(resolved), 6) if resolved else None,
        "mean_realized_edge": round(sum_real / len(resolved), 6) if resolved else None,
        "edge_ratio": round(sum_real / sum_est, 4) if abs(sum_est) > 1e-9 else None,
        "sum_pnl_cents": sum(r.realized_pnl_cents or 0 for r in resolved),
        "sum_fee_cents": sum(r.fee_cents or 0 for r in recs),
        "win_rate": round(wins / (wins + losses), 4) if (wins + losses) else None,
        "winning_trades": wins,
        "losing_trades": losses,
    }

    lifetime = []
    try:
        for st in store.get_all_edge_stats():
            if asset_u in str(st.forecaster_id).upper() or asset_u in str(st.bucket).upper():
                lifetime.append(st.to_dict())
    except Exception as exc:
        logger.debug("get_all_edge_stats failed: %s", exc)

    return {
        "available": True,
        "asset": asset_u,
        "window_minutes": window_minutes,
        "markets": markets,
        "count": len(recs),
        "aggregation": agg,
        "lifetime_stats": lifetime,
        "source": "realized_edge_store",
    }
