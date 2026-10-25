"""Deterministic per-window trade plan: shared budget + contract cap +
submission quota + pacing across all five 15m crypto series.

2026-10-25: the operator asked for deterministic per-window allocation under
the configured $3 fixed-exposure cap — "deterministic about how many
contracts and candidates it should trade per 15-minute window" — while
keeping every existing EV/risk gate.  Research synthesis (multi-binary
Kelly with cardinality constraint, budget pacing, queue-position fill
theory): the *plan* can be deterministic — budget, caps, ranking, pacing —
while realized fills remain probabilistic unless a taker route is used.
This module implements the deterministic part; it never manufactures a
trade.

Design:

  * One WindowPlan state per 15-minute window, keyed by the shared ticker
    suffix (``KXBTC15M-26OCT251445-45`` -> ``26OCT251445``) so all five
    series draw on the same budget.
  * Committed exposure is RE-DERIVED from authoritative sources on every
    admission — trusted fills ledger (canonical fills), the resting order
    monitor (live resting entries), plus this module's own pending
    reservation map (in-flight intents not yet visible to either).  No
    release hooks are needed downstream: a terminal-unfilled resting order
    leaves the live set on the next sync and frees its reservation; a fill
    converts reservation to committed cost; a pending reservation expires
    on TTL if the order never materialized.
  * A position that fully exits mid-window frees its entry cost for re-use
    (net signed delta ~ 0 -> not committed).
  * Submissions are counted durably (consume-then-suppress sidecar JSON,
    same discipline as window_quota) so the wire quota survives restarts.
    A submission slot is consumed only when the loop reports the order
    actually reached execution (order_submitted=True); pre-wire deaths
    release the budget reservation without consuming a slot.
  * Pacing: the submission quota is partitioned across TTE cells by
    configured shares of measured +EV density; allowance is cumulative so
    unused early-cell capacity carries forward.

Knobs (all env-tunable):
  MERID_WINDOW_PLAN_ENABLED            1     master switch
  MERID_WINDOW_PLAN_BUDGET_USD         =MERID_FIXED_EXPOSURE_CAP_USD (3.00)
  MERID_WINDOW_PLAN_MAX_CONTRACTS      5     filled+resting+pending contracts
  MERID_WINDOW_PLAN_MAX_SUBMISSIONS    6     wire attempts per window
  MERID_WINDOW_PLAN_ORDER_CAP_USD      3.00  per-order notional ceiling
  MERID_WINDOW_PLAN_MAX_QTY_CC         400   per-order contract ceiling
  MERID_WINDOW_PLAN_PER_ASSET_CAP_USD  3.00  single asset may take budget;
                                             correlation cap does the spread
  MERID_WINDOW_PLAN_CORR_CAP_PCT       0.75  same-side committed <= 75% of
                                             budget ($2.25) — 5 crypto series
                                             are one correlated move; opposite
                                             side may use the remainder (hedge)
  MERID_WINDOW_PLAN_TTE_EARLY_S        300   early cell: tte > 300
  MERID_WINDOW_PLAN_TTE_MID_S          120   mid cell: 120 < tte <= 300
  MERID_WINDOW_PLAN_CELL_SHARES        0.35,0.45,0.20  early,mid,late
  MERID_WINDOW_PLAN_PENDING_TTL_S      45    pending reservation lifetime
  MERID_WINDOW_PLAN_LIFT_SIZING        1     plan may raise count toward the
                                             budget fit (never beyond lane /
                                             per-order / contract caps)
  MERID_WINDOW_PLAN_STATE_PATH         data/window_plan_state.json
"""

import json
import logging
import os
import time
from decimal import Decimal, ROUND_DOWN
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

_CC = Decimal("100")          # centi-contracts per contract
_TICKER_SUFFIX_PARTS = 3      # KX<ASSET>15M-<SUFFIX>-<STRIKE>


def _env_flag(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes")


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except Exception:
        return default


def plan_enabled() -> bool:
    return _env_flag("MERID_WINDOW_PLAN_ENABLED", True)


def plan_budget_usd() -> Decimal:
    """Window risk budget; defaults to the configured fixed exposure cap so
    the plan can never widen the account-level bound the operator set."""
    raw = os.environ.get("MERID_WINDOW_PLAN_BUDGET_USD")
    if raw is None:
        raw = os.environ.get("MERID_FIXED_EXPOSURE_CAP_USD", "3.00")
    try:
        return Decimal(str(raw))
    except Exception:
        return Decimal("3.00")


def plan_max_contracts_cc() -> int:
    return int(_env_float("MERID_WINDOW_PLAN_MAX_CONTRACTS", 5.0) * 100)


def plan_max_submissions() -> int:
    return int(_env_float("MERID_WINDOW_PLAN_MAX_SUBMISSIONS", 6.0))


def plan_order_cap_usd() -> Decimal:
    return Decimal(str(_env_float("MERID_WINDOW_PLAN_ORDER_CAP_USD", 3.00)))


def plan_max_qty_cc() -> int:
    return int(_env_float("MERID_WINDOW_PLAN_MAX_QTY_CC", 400.0))


def plan_min_qty_cc() -> int:
    """Minimum fit the plan will spend a submission slot on — a fit below 1
    contract is dust (sub-cent expected P&L), not depth."""
    return int(_env_float("MERID_WINDOW_PLAN_MIN_QTY_CC", 100.0))


def plan_per_asset_cap_usd() -> Decimal:
    return Decimal(str(_env_float("MERID_WINDOW_PLAN_PER_ASSET_CAP_USD", 3.00)))


def plan_corr_cap_usd() -> Decimal:
    pct = _env_float("MERID_WINDOW_PLAN_CORR_CAP_PCT", 0.75)
    return plan_budget_usd() * Decimal(str(pct))


def plan_pending_ttl_s() -> float:
    return _env_float("MERID_WINDOW_PLAN_PENDING_TTL_S", 45.0)


def plan_lift_sizing() -> bool:
    return _env_flag("MERID_WINDOW_PLAN_LIFT_SIZING", True)


def plan_state_path() -> str:
    return os.environ.get(
        "MERID_WINDOW_PLAN_STATE_PATH", "data/window_plan_state.json"
    )


def _cell_shares() -> Tuple[float, float, float]:
    raw = os.environ.get("MERID_WINDOW_PLAN_CELL_SHARES", "0.35,0.45,0.20")
    try:
        parts = [float(x) for x in raw.split(",")]
        if len(parts) == 3 and all(p >= 0 for p in parts):
            return parts[0], parts[1], parts[2]
    except Exception:
        pass
    return 0.35, 0.45, 0.20


def _tte_early_s() -> float:
    return _env_float("MERID_WINDOW_PLAN_TTE_EARLY_S", 300.0)


def _tte_mid_s() -> float:
    return _env_float("MERID_WINDOW_PLAN_TTE_MID_S", 120.0)


def tte_cell(tte_s: Optional[float]) -> int:
    """0=early (tte>early), 1=mid (mid<tte<=early), 2=late (tte<=mid)."""
    t = float(tte_s) if tte_s is not None else 0.0
    if t > _tte_early_s():
        return 0
    if t > _tte_mid_s():
        return 1
    return 2


def submission_allowance(tte_s: Optional[float]) -> int:
    """Cumulative submission allowance at this TTE — unused capacity from
    earlier cells carries forward automatically (a dry early cell does not
    starve the mid/late cells, and a rich early cell cannot borrow from
    later ones)."""
    shares = _cell_shares()
    total = plan_max_submissions()
    cell = tte_cell(tte_s)
    return min(total, int(total * sum(shares[: cell + 1])))


def window_suffix(ticker: str) -> Optional[str]:
    """``KXBTC15M-26OCT251445-45`` -> ``26OCT251445``; shared across series."""
    parts = str(ticker or "").split("-")
    return parts[1] if len(parts) >= _TICKER_SUFFIX_PARTS else None


def _extract_asset(ticker: str) -> str:
    t = str(ticker or "").upper()
    for a in ("BTC", "ETH", "SOL", "XRP", "DOGE"):
        if a in t:
            return a
    return t


class _PlanState:
    """Mutable per-window state; recreated on window change."""

    __slots__ = (
        "suffix",
        "pending",          # decision_id -> pending reservation dict
        "submissions",
        "submitted_ids",
        "first_seen",
    )

    def __init__(self, suffix: str):
        self.suffix = suffix
        self.pending: Dict[str, dict] = {}
        self.submissions = 0
        self.submitted_ids = []
        self.first_seen = time.time()


_state: Optional[_PlanState] = None


def _load_sidecar(suffix: str) -> Tuple[int, list]:
    """Durable submission counter for this window (restart-safe)."""
    try:
        with open(plan_state_path(), "r", encoding="utf-8") as f:
            rec = json.load(f)
        if rec.get("window") == suffix:
            return int(rec.get("submissions") or 0), list(
                rec.get("submitted_ids") or []
            )
    except Exception:
        pass
    return 0, []


def _save_sidecar(st: _PlanState) -> None:
    p = plan_state_path()
    try:
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(json.dumps({
                "window": st.suffix,
                "submissions": st.submissions,
                "submitted_ids": st.submitted_ids[-64:],
            }, separators=(",", ":")))
        os.replace(tmp, p)
    except Exception:
        pass


def _get_state(suffix: str) -> _PlanState:
    global _state
    if _state is None or _state.suffix != suffix:
        subs, ids = _load_sidecar(suffix)
        st = _PlanState(suffix)
        st.submissions, st.submitted_ids = subs, ids
        _state = st
    return _state


def _committed_from_authoritative(suffix: str) -> Tuple[Decimal, int, Dict[str, Decimal], Dict[str, Decimal], bool]:
    """(total_cost_usd, total_cc, per_asset_cost, per_side_cost, scan_ok)
    committed by fills ledger + resting monitor for this window's tickers.

    Fills: group canonical fills per ticker; a ticker whose net signed YES
    delta is ~0 is closed and commits nothing; an open ticker commits its
    entry cost scaled by the open fraction (partial exits release pro-rata).
    Resting: live non-terminal records' remaining size at limit price.

    scan_ok=False when either authoritative source errored — a risk bound
    that cannot read its ledger must not keep spending against a phantom
    zero, so admit() treats it as fail-closed.
    """
    cost = Decimal("0")
    cc = 0
    per_asset: Dict[str, Decimal] = {}
    per_side: Dict[str, Decimal] = {}
    scan_ok = True

    # --- trusted fills ledger -------------------------------------------
    try:
        from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
        ledger = get_fills_ledger()
        if ledger is not None:
            view = ledger.get_canonical_fills()
            by_ticker: Dict[str, dict] = {}
            for f in view.authoritative:
                tk = str(getattr(f, "market_ticker", "") or "")
                if suffix not in tk:
                    continue
                g = by_ticker.setdefault(tk, {
                    "net_yes_cc": 0, "entry_cc": 0, "entry_cost": Decimal("0"),
                })
                delta = getattr(f, "canonical_yes_delta_cc", None)
                if delta is None:
                    try:
                        from merid.event_venues.kalshi.binary_price_space import yes_delta
                        delta = yes_delta(
                            getattr(f, "action", ""), getattr(f, "side", ""),
                            int(getattr(f, "quantity_cc", 0) or 0),
                        )
                    except Exception:
                        delta = 0
                g["net_yes_cc"] += int(delta or 0)
                is_entry = (
                    str(getattr(f, "entry_or_exit", "entry") or "entry").lower() == "entry"
                    and not getattr(f, "reduce_only", False)
                    and not getattr(f, "is_exit", False)
                )
                if is_entry:
                    q = int(getattr(f, "quantity_cc", 0) or 0)
                    g["entry_cc"] += q
                    proc = getattr(f, "proceeds_dollars", None)
                    if proc is not None:
                        g["entry_cost"] += abs(Decimal(str(proc)))
                    else:
                        px = getattr(f, "yes_price_dollars", None) or getattr(f, "no_price_dollars", None)
                        if px is not None:
                            g["entry_cost"] += (Decimal(str(px)) * Decimal(q)) / _CC
            for tk, g in by_ticker.items():
                net = int(g["net_yes_cc"])
                if abs(net) < 1 or g["entry_cc"] <= 0:
                    continue  # flat — fully exited, cost recycled
                open_frac = min(1.0, abs(net) / float(g["entry_cc"]))
                c = g["entry_cost"] * Decimal(str(open_frac))
                cost += c
                open_cc = min(abs(net), g["entry_cc"])
                cc += open_cc
                asset = _extract_asset(tk)
                per_asset[asset] = per_asset.get(asset, Decimal("0")) + c
                side_dir = "yes" if net > 0 else "no"
                per_side[side_dir] = per_side.get(side_dir, Decimal("0")) + c
    except Exception as e:
        scan_ok = False
        logger.warning("[WINDOW-PLAN] ledger committed scan failed: %s", e)

    # --- resting order monitor (live entries only) ------------------------
    try:
        from merid.event_venues.kalshi.resting_order_monitor import (
            get_resting_order_monitor, TERMINAL_STATUSES,
        )
        from merid.event_venues.kalshi.exit_order_utils import is_exit_order_from_source
        mon = get_resting_order_monitor()
        if mon is not None:
            for rec in mon.get_all_orders():
                tk = str(getattr(rec, "ticker", "") or "")
                if suffix not in tk:
                    continue
                status = str(getattr(rec, "status", "") or "")
                if status in TERMINAL_STATUSES:
                    continue
                rem = float(getattr(rec, "remaining_size", 0) or 0)
                if rem <= 0:
                    continue
                coid = str(getattr(rec, "client_order_id", "") or "")
                if coid and is_exit_order_from_source(coid):
                    continue
                if str(getattr(rec, "action", "") or "").lower() != "buy":
                    continue  # entries are buys; sells are exits
                px = Decimal(str(getattr(rec, "price_cents", 0) or 0)) / _CC
                c = px * Decimal(str(rem))
                cost += c
                cc += int(rem * 100)
                asset = str(getattr(rec, "asset", "") or "") or _extract_asset(tk)
                per_asset[asset] = per_asset.get(asset, Decimal("0")) + c
                side_dir = str(getattr(rec, "side", "") or "").lower()
                if side_dir in ("yes", "no"):
                    per_side[side_dir] = per_side.get(side_dir, Decimal("0")) + c
    except Exception as e:
        scan_ok = False
        logger.warning("[WINDOW-PLAN] resting committed scan failed: %s", e)

    return cost, cc, per_asset, per_side, scan_ok


def _reconcile_pending(st: _PlanState, now: float) -> Decimal:
    """Drop pending reservations whose order is now authoritative elsewhere
    (resting monitor record or ledger fill) or too old to materialize.
    Returns pending committed cost."""
    try:
        from merid.event_venues.kalshi.resting_order_monitor import get_resting_order_monitor
        mon = get_resting_order_monitor()
        seen_ids = set()
        if mon is not None:
            for rec in mon.get_all_orders():
                if st.suffix not in str(getattr(rec, "ticker", "") or ""):
                    continue
                for key in (getattr(rec, "client_order_id", None), getattr(rec, "decision_id", None)):
                    if key:
                        seen_ids.add(str(key))
        try:
            from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
            ledger = get_fills_ledger()
            if ledger is not None:
                for f in ledger.get_canonical_fills().authoritative:
                    if st.suffix not in str(getattr(f, "market_ticker", "") or ""):
                        continue
                    coid = getattr(f, "client_order_id", None)
                    if coid:
                        seen_ids.add(str(coid))
        except Exception:
            pass
        ttl = plan_pending_ttl_s()
        for did in list(st.pending.keys()):
            prec = st.pending[did]
            coid = prec.get("client_order_id")
            if did in seen_ids or (coid and coid in seen_ids):
                del st.pending[did]
            elif now - float(prec.get("ts", now)) > ttl:
                del st.pending[did]
    except Exception as e:
        logger.debug("[WINDOW-PLAN] pending reconcile failed: %s", e)
    total = Decimal("0")
    for prec in st.pending.values():
        total += Decimal(str(prec.get("cost_usd", 0) or 0))
    return total


def _est_cost_per_contract_usd(price_cents: float, post_only: bool) -> Decimal:
    """Limit price + fee reserve per contract (taker unless maker/post-only;
    maker fee on the 15m crypto series is 0)."""
    px = Decimal(str(price_cents)) / _CC
    if post_only:
        return px
    try:
        from merid.event_venues.kalshi.parabolic_fees import kalshi_fee_cents_exact
        fee = kalshi_fee_cents_exact(float(px), Decimal("1"), "taker") / _CC
        return px + fee
    except Exception:
        # Parabolic bound: 7 * P(1-P) cents per contract.
        p = float(price_cents)
        return px + Decimal(str(7.0 * (p / 100.0) * (1.0 - p / 100.0))) / _CC


def admit(
    *,
    ticker: str,
    asset: str,
    side: str,
    price_cents: float,
    requested_count: float,
    tte_s: Optional[float] = None,
    post_only: bool = False,
    decision_id: str = "",
    allow_lift: bool = True,
    now: Optional[float] = None,
) -> Tuple[bool, float, str, dict]:
    """Deterministic admission into the shared window plan.

    Returns (allowed, final_count_contracts, reason, detail).  On allow,
    final_count is the count to submit (clamped to remaining budget; raised
    toward the budget fit when LIFT_SIZING is on and upstream sizing was
    more conservative).  On reject, final_count is 0 and reason is a stable
    ``window_plan_*`` code for telemetry."""
    now = time.time() if now is None else float(now)
    detail: dict = {}
    suffix = window_suffix(ticker)
    if suffix is None:
        return False, 0.0, "window_plan_no_window", detail
    st = _get_state(suffix)

    committed_cost, committed_cc, per_asset, per_side, scan_ok = _committed_from_authoritative(suffix)
    if not scan_ok:
        # Fail closed: cannot bound committed exposure without the ledger and
        # the resting monitor.  This is a budget control, not an entry gate —
        # refusing to spend is the safe direction.
        return False, 0.0, "window_plan_scan_failed", {"window": suffix}
    pending_cost = _reconcile_pending(st, now)
    pending_cc = int(sum(int(p.get("cc", 0) or 0) for p in st.pending.values()))
    pending_by_asset: Dict[str, Decimal] = {}
    pending_by_side: Dict[str, Decimal] = {}
    for p in st.pending.values():
        a = str(p.get("asset") or "")
        s = str(p.get("side") or "").lower()
        c = Decimal(str(p.get("cost_usd", 0) or 0))
        if a:
            pending_by_asset[a] = pending_by_asset.get(a, Decimal("0")) + c
        if s in ("yes", "no"):
            pending_by_side[s] = pending_by_side.get(s, Decimal("0")) + c

    budget = plan_budget_usd()
    used_cost = committed_cost + pending_cost
    used_cc = committed_cc + pending_cc
    asset_used = per_asset.get(asset, Decimal("0")) + pending_by_asset.get(asset, Decimal("0"))
    side_dir = str(side or "").lower()
    side_used = per_side.get(side_dir, Decimal("0")) + pending_by_side.get(side_dir, Decimal("0"))

    detail.update({
        "window": suffix,
        "budget_usd": str(budget),
        "committed_usd": str(used_cost.quantize(Decimal("0.0001"))),
        "committed_cc": used_cc,
        "asset_committed_usd": str(asset_used.quantize(Decimal("0.0001"))),
        "side_committed_usd": str(side_used.quantize(Decimal("0.0001"))),
        "submissions": st.submissions,
        "tte_s": tte_s,
    })

    # 1. Submission quota (wire attempts; deterministic bound).
    if st.submissions >= plan_max_submissions():
        return False, 0.0, "window_plan_submission_cap", detail

    # 2. Pacing: cumulative cell allowance.
    allowance = submission_allowance(tte_s)
    detail["tte_cell"] = tte_cell(tte_s)
    detail["cell_allowance"] = allowance
    if st.submissions >= allowance:
        return False, 0.0, "window_plan_pacing", detail

    # 3. Contract cap.
    remaining_cc = plan_max_contracts_cc() - used_cc
    if remaining_cc <= 0:
        return False, 0.0, "window_plan_contract_cap", detail

    # 4. Dollar caps -> size fit on the centi-contract grid.
    remaining_budget = budget - used_cost
    asset_room = plan_per_asset_cap_usd() - asset_used
    corr_room = plan_corr_cap_usd() - side_used
    order_room = plan_order_cap_usd()
    room_usd = min(remaining_budget, asset_room, corr_room, order_room)
    if room_usd <= 0:
        reason = (
            "window_plan_corr_cap" if corr_room <= 0 and corr_room <= asset_room and corr_room <= remaining_budget
            else "window_plan_per_asset_cap" if asset_room <= 0 and asset_room <= remaining_budget
            else "window_plan_budget_exhausted"
        )
        return False, 0.0, reason, detail

    cost_per = _est_cost_per_contract_usd(price_cents, post_only)
    if cost_per <= 0:
        return False, 0.0, "window_plan_no_price", detail

    fit_cc = int((room_usd / cost_per * _CC).to_integral_value(rounding=ROUND_DOWN))
    try:
        from merid.risk.global_slot_allocator import MAX_CONTRACTS_PER_ORDER as _GLOBAL_CAP
        global_cap_cc = int(_GLOBAL_CAP) * 100
    except Exception:
        global_cap_cc = plan_max_qty_cc()
    fit_cc = min(fit_cc, plan_max_qty_cc(), global_cap_cc, remaining_cc)
    detail["room_usd"] = str(room_usd.quantize(Decimal("0.0001")))
    detail["cost_per_contract_usd"] = str(cost_per.quantize(Decimal("0.0001")))
    detail["fit_cc"] = fit_cc
    if fit_cc <= 0 or fit_cc < plan_min_qty_cc():
        return False, 0.0, "window_plan_no_size", detail

    requested_cc = int(Decimal(str(requested_count or 0)) * _CC)
    if requested_cc <= 0:
        requested_cc = fit_cc  # sizing produced nothing; plan fit governs
    # With LIFT_SIZING the plan's budget fit IS the deterministic order size
    # (deploy the committed room on this top-ranked admission); without it the
    # plan only clamps upstream sizing down.  allow_lift=False (bounded lanes)
    # keeps the plan clamp-only so a lane's own stamped cap is never exceeded.
    final_cc = (
        fit_cc if (plan_lift_sizing() and allow_lift) else min(requested_cc, fit_cc)
    )
    if final_cc <= 0:
        return False, 0.0, "window_plan_no_size", detail

    final_contracts = float(Decimal(final_cc) / _CC)
    final_cost = (cost_per * Decimal(final_cc)) / _CC
    detail["final_cc"] = final_cc
    detail["reserved_usd"] = str(final_cost.quantize(Decimal("0.0001")))

    st.pending[decision_id or f"{ticker}:{now}"] = {
        "ticker": ticker,
        "asset": asset,
        "side": side_dir,
        "cc": final_cc,
        "cost_usd": str(final_cost.quantize(Decimal("0.0001"))),
        "ts": now,
        "submitted": False,
        "client_order_id": None,
    }
    return True, final_contracts, "window_plan_admitted", detail


def record_submission(decision_id: str, *, client_order_id: Optional[str] = None,
                      ticker: str = "") -> None:
    """Called when the loop reports order_submitted=True — the wire attempt
    is real, so consume a durable submission slot and bind the coid."""
    if not decision_id:
        return
    suffix = window_suffix(ticker) or (_state.suffix if _state else None)
    if suffix is None:
        return
    st = _get_state(suffix)
    # Idempotent per wire identity (client_order_id): every successful
    # submission is counted exactly once, even if two wire attempts share a
    # decision_id or the pending record was already reconciled out.
    wire_id = str(client_order_id or decision_id)
    if wire_id in st.submitted_ids:
        return
    st.submissions += 1
    st.submitted_ids.append(wire_id)
    prec = st.pending.get(decision_id)
    if prec is not None:
        prec["submitted"] = True
        if client_order_id:
            prec["client_order_id"] = client_order_id
    _save_sidecar(st)
    logger.info(
        "[WINDOW-PLAN] submission %d/%s consumed window=%s ticker=%s coid=%s",
        st.submissions, plan_max_submissions(), suffix, ticker, client_order_id,
    )


def release_reservation(decision_id: str) -> None:
    """Release the budget reservation for a candidate that died pre-wire
    (never consumed a submission slot).  Idempotent."""
    if not decision_id or _state is None:
        return
    if _state.pending.pop(decision_id, None) is not None:
        logger.info("[WINDOW-PLAN] released pre-wire reservation decision_id=%s", decision_id)


def sort_candidates(candidates) -> list:
    """Deterministic global rank: net edge desc, then confidence, then
    model_prob, then ticker, then candidate_id (stable, no dict-order
    dependence).  The shared plan gate then admits top-ranked first."""
    def _key(c: dict):
        td = c.get("trade_decision")
        did = getattr(td, "decision_id", None) if td is not None else None
        return (
            -float(c.get("edge_pct", 0.0) or 0.0),
            -float(c.get("confidence", 0.0) or 0.0),
            -float(c.get("model_prob", 0.0) or 0.0),
            str(c.get("ticker", "") or ""),
            str(c.get("candidate_id", "") or did or ""),
        )
    return sorted(list(candidates), key=_key)


def reset_for_tests() -> None:
    global _state
    _state = None
