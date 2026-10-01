"""Fill-quality accounting for resting maker entry orders (2026-09-29).

For every ``post_only`` entry the exchange acknowledges, this tracker records:

- Entry context: intent/order ids, ticker, held side, limit price, BBO at
  submit, candidate-time edge metrics.
- Fill state: fill / no-fill, resting time before fill, fill price, and the
  model edge recomputed at the fill price.
- Markouts: the outcome-side mid observed at the first poll at-or-after the
  1s / 5s / 30s horizons (actual age recorded with each mark).
- Terminal state: cancel / expire / window end, plus settlement side when
  resolvable offline via the ticker join.

Events are appended as JSONL to ``logs/fill_quality.jsonl`` (one event per
stage: ``order_entry`` / ``markout`` / ``fill`` / ``terminal``).  ``poll()``
is driven by the WS-REFRESH loop (~5s cadence), so the 1s markout lands at
the first poll crossing that horizon — the recorded ``age_ms`` is exact.

Passive fills are often adversely selected; whether *filled* maker orders
remain positive after the market reacts is the question this ledger exists
to answer.  It is observability-only and never mutates order state.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_MARKOUT_HORIZONS_S = (1.0, 5.0, 30.0)
# Records are closed when the ticker expires or the order reaches a terminal
# state; this is a belt-and-braces bound so the map cannot grow unbounded.
_MAX_RECORD_AGE_S = 3600.0


def _logs_path() -> str:
    return os.getenv("MERID_FILL_QUALITY_PATH", "logs/fill_quality.jsonl")


def _now() -> float:
    return time.time()


def _append_event(record: Dict[str, Any]) -> None:
    try:
        path = _logs_path()
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, default=str, separators=(",", ":")) + "\n")
    except Exception as e:
        logger.debug("[FILL-QUALITY] append failed: %s", e)


class _OrderRecord:
    __slots__ = (
        "client_order_id", "intent_id", "order_id", "ticker", "asset",
        "side", "action", "limit_price_cents", "submit_ts",
        "yes_bid_cents", "yes_ask_cents", "edge_pct", "ev_net_cents",
        "p_selected", "markouts", "filled", "fill_ts", "fill_price_cents",
        "terminal", "terminal_ts", "closed",
        "decision_id", "threshold_cell_id", "provisional_cell_id",
        "expire_after_ts",
    )

    def __init__(self, **kw: Any) -> None:
        for f in self.__slots__:
            setattr(self, f, kw.get(f))
        self.markouts: Dict[str, Dict[str, Any]] = {}
        self.filled = False
        self.terminal = None
        self.closed = False


class FillQualityTracker:
    """In-memory tracker; ``poll()`` stamps markouts/detects fills/terminals."""

    def __init__(self) -> None:
        self._records: Dict[str, _OrderRecord] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ api
    def record_order(
        self,
        *,
        client_order_id: str,
        intent_id: str,
        order_id: Optional[str],
        ticker: str,
        side: str,
        action: str,
        limit_price_cents: Optional[int],
        yes_bid_cents: Optional[int],
        yes_ask_cents: Optional[int],
        edge_pct: Optional[float],
        ev_net_cents: Optional[float],
        p_selected: Optional[float],
        decision_id: Optional[str] = None,
        threshold_cell_id: Optional[str] = None,
        provisional_cell_id: Optional[str] = None,
        record_ttl_s: Optional[float] = None,
    ) -> None:
        """Register an acknowledged post_only entry order for tracking.

        ``record_ttl_s`` bounds how long an unfilled record stays open; lanes
        with a bounded resting lifetime (the current-build provisional lane's
        45s contract) pass it so an expired order frees its open-order slot
        promptly instead of holding it until ``_MAX_RECORD_AGE_S``.
        """
        if not client_order_id:
            return
        submit_ts = _now()
        rec = _OrderRecord(
            client_order_id=client_order_id,
            intent_id=intent_id,
            order_id=order_id,
            ticker=ticker,
            asset=(ticker.split("-")[0] if ticker else ""),
            side=side,
            action=action,
            limit_price_cents=limit_price_cents,
            submit_ts=submit_ts,
            yes_bid_cents=yes_bid_cents,
            yes_ask_cents=yes_ask_cents,
            edge_pct=edge_pct,
            ev_net_cents=ev_net_cents,
            p_selected=p_selected,
            decision_id=decision_id,
            threshold_cell_id=threshold_cell_id,
            provisional_cell_id=provisional_cell_id,
            expire_after_ts=(
                submit_ts + float(record_ttl_s)
                if record_ttl_s is not None else None
            ),
        )
        with self._lock:
            self._records[client_order_id] = rec
            if len(self._records) > 2000:
                # Drop the oldest closed records first, then oldest overall.
                closed = [k for k, r in self._records.items() if r.closed]
                for k in closed[:500]:
                    self._records.pop(k, None)
        _append_event({
            "event": "order_entry",
            "ts": rec.submit_ts,
            "client_order_id": client_order_id,
            "intent_id": intent_id,
            "order_id": order_id,
            "ticker": ticker,
            "side": side,
            "action": action,
            "limit_price_cents": limit_price_cents,
            "yes_bid_cents": yes_bid_cents,
            "yes_ask_cents": yes_ask_cents,
            "edge_pct": edge_pct,
            "ev_net_cents": ev_net_cents,
            "p_selected": p_selected,
            "decision_id": decision_id,
            "threshold_cell_id": threshold_cell_id,
            "provisional_cell_id": provisional_cell_id,
        })

    def poll(self) -> None:
        """Stamp markouts, detect fills, and close terminal records.

        Called by the WS-REFRESH loop every ~5s; safe to call more often.
        """
        now = _now()
        try:
            from merid.event_venues.kalshi.market_state import (
                get_kalshi_market_state_store,
            )
            store = get_kalshi_market_state_store()
        except Exception:
            store = None
        try:
            from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
            ledger = get_fills_ledger()
        except Exception:
            ledger = None

        with self._lock:
            records = list(self._records.values())
        for rec in records:
            if rec.closed:
                continue
            age = now - (rec.submit_ts or now)
            mid = self._side_mid_cents(rec, store)
            for horizon in _MARKOUT_HORIZONS_S:
                key = f"{int(horizon)}s"
                if key not in rec.markouts and age >= horizon and mid is not None:
                    rec.markouts[key] = {
                        "ts": now,
                        "age_ms": round(age * 1000.0, 1),
                        "mid_cents": mid,
                        "markout_cents": round(mid - (rec.limit_price_cents or 0), 2)
                        if rec.action == "buy"
                        else round((rec.limit_price_cents or 0) - mid, 2),
                    }
                    _append_event({
                        "event": "markout",
                        "ts": now,
                        "client_order_id": rec.client_order_id,
                        "ticker": rec.ticker,
                        "horizon": key,
                        "age_ms": rec.markouts[key]["age_ms"],
                        "mid_cents": mid,
                        "markout_cents": rec.markouts[key]["markout_cents"],
                        "decision_id": rec.decision_id,
                        "threshold_cell_id": rec.threshold_cell_id,
                        "provisional_cell_id": rec.provisional_cell_id,
                    })
                    # 2026-09-30: feed per-cell suspension stats — persistent
                    # negative markouts on a passive lane are the
                    # adverse-selection signal that suspends the cell.
                    if rec.threshold_cell_id:
                        try:
                            from merid.prediction import threshold_cells as _tc
                            _tc.record_cell_markout(
                                rec.threshold_cell_id,
                                rec.decision_id,
                                int(horizon),
                                rec.markouts[key]["markout_cents"],
                            )
                        except Exception:
                            pass
                    if rec.provisional_cell_id:
                        try:
                            from merid.prediction import (
                                current_build_provisional as _cbp,
                            )
                            _cbp.record_provisional_markout(
                                rec.provisional_cell_id,
                                rec.decision_id,
                                int(horizon),
                                rec.markouts[key]["markout_cents"],
                            )
                            _cbp.record_cb_evidence(
                                "markout",
                                provisional_cell_id=rec.provisional_cell_id,
                                asset=rec.asset,
                                side=(rec.side or "").upper(),
                                decision_id=rec.decision_id,
                                order_id=rec.order_id,
                                fill_price_cents=rec.fill_price_cents,
                                limit_price_cents=rec.limit_price_cents,
                                markout_1s_cents=(
                                    (rec.markouts.get("1s") or {}).get(
                                        "markout_cents"
                                    )
                                ),
                                markout_5s_cents=(
                                    (rec.markouts.get("5s") or {}).get(
                                        "markout_cents"
                                    )
                                ),
                                markout_30s_cents=(
                                    (rec.markouts.get("30s") or {}).get(
                                        "markout_cents"
                                    )
                                ),
                                horizon_s=int(horizon),
                                filled=rec.filled,
                            )
                        except Exception:
                            pass
            if not rec.filled:
                self._detect_fill(rec, ledger, now)
            if (
                rec.expire_after_ts is not None
                and not rec.filled
                and now >= rec.expire_after_ts
            ):
                # Lane-bounded resting lifetime elapsed with no fill — the
                # order is expired/cancelled on the venue; free the slot.
                self._close(rec, "rest_ttl_expired", now)
            elif age > _MAX_RECORD_AGE_S:
                self._close(rec, "aged_out", now)

    # -------------------------------------------------------------- helpers
    @staticmethod
    def _side_mid_cents(rec: _OrderRecord, store: Any) -> Optional[float]:
        """Outcome-side mid price for markouts (YES-space book -> side space)."""
        if store is None:
            return None
        try:
            state = store.get(rec.ticker)
            if state is None:
                return None
            yb = getattr(state, "best_bid_cents", None)
            ya = getattr(state, "best_ask_cents", None)
            if yb is None or ya is None:
                return None
            yes_mid = (float(yb) + float(ya)) / 2.0
            _s = (rec.side or "").lower()
            _is_no = _s == "no" or _s.endswith("_no")
            return yes_mid if not _is_no else 100.0 - yes_mid
        except Exception:
            return None

    def _detect_fill(self, rec: _OrderRecord, ledger: Any, now: float) -> None:
        if ledger is None:
            return
        try:
            fills = ledger.get_fills_by_market(rec.ticker)
        except Exception:
            return
        for f in fills:
            f_oid = getattr(f, "order_id", None)
            f_coid = getattr(f, "client_order_id", None)
            if rec.order_id and f_oid == rec.order_id:
                matched = True
            elif f_coid and f_coid == rec.client_order_id:
                matched = True
            else:
                matched = False
            if not matched:
                continue
            # 2026-09-30: threshold-cell lane invariant — a fill attributed to
            # this order must be on the intent's outcome side.  A side flip is
            # structural corruption, not performance: suspend the cell at once.
            # Compare OUTCOME sides, not traded legs: a BUY_NO intent rests as
            # a sell-YES leg (fill side=yes/action=sell produces a NO outcome),
            # which is legitimate, not corruption.
            _f_leg_side = str(
                getattr(f, "canonical_position_side", None)
                or getattr(f, "side", None) or ""
            ).lower()
            _f_leg_action = str(
                getattr(f, "canonical_position_action", None)
                or getattr(f, "action", None) or ""
            ).lower()
            if _f_leg_side in ("yes", "no"):
                _f_outcome = (
                    _f_leg_side
                    if _f_leg_action != "sell"
                    else ("no" if _f_leg_side == "yes" else "yes")
                )
            else:
                _f_outcome = ""
            _r_side = (rec.side or "").lower()
            _r_is_no = _r_side == "no" or _r_side.endswith("_no")
            if (
                (rec.threshold_cell_id or rec.provisional_cell_id)
                and _f_outcome in ("yes", "no")
                and (_f_outcome == "no") != _r_is_no
            ):
                try:
                    if rec.threshold_cell_id:
                        from merid.prediction import threshold_cells as _tc
                        _tc.record_cell_invariant_violation(
                            rec.threshold_cell_id,
                            f"fill_outcome={_f_outcome} intent_side={_r_side}",
                        )
                    if rec.provisional_cell_id:
                        from merid.prediction import (
                            current_build_provisional as _cbp,
                        )
                        _cbp.record_provisional_invariant_violation(
                            rec.provisional_cell_id,
                            f"fill_outcome={_f_outcome} intent_side={_r_side}",
                        )
                except Exception:
                    pass
            fill_ts = getattr(f, "created_time", None)
            fill_ts = fill_ts.timestamp() if hasattr(fill_ts, "timestamp") else (fill_ts or now)
            # Fill price in the intent's outcome space.  ``f.price_cents`` is
            # the canonical leg price on the *traded* leg — a BUY_NO intent
            # executes as a sell-YES leg whose price is YES-space — while
            # ``rec.limit_price_cents`` and ``rec.p_selected`` live in the
            # intent's outcome space.  Convert when the spaces differ or every
            # NO fill records a space-inverted edge and a false post-only
            # breach (fill 66 > limit 34 in mixed spaces).
            fill_px = getattr(f, "price_cents", None)
            _s = (rec.side or "").lower()
            _is_no = _s == "no" or _s.endswith("_no")
            if fill_px is not None:
                _leg_side = (
                    getattr(f, "canonical_position_side", None)
                    or getattr(f, "side", None) or ""
                ).lower()
                _leg_is_no = _leg_side == "no" or _leg_side.endswith("_no")
                fill_px = int(fill_px)
                if _leg_is_no != _is_no:
                    fill_px = 100 - fill_px
            rec.filled = True
            rec.fill_ts = float(fill_ts)
            rec.fill_price_cents = fill_px
            edge_at_fill = None
            if rec.p_selected is not None and fill_px is not None:
                try:
                    edge_at_fill = round(float(rec.p_selected) * 100.0 - float(fill_px), 2)
                except Exception:
                    edge_at_fill = None
            _append_event({
                "event": "fill",
                "ts": now,
                "client_order_id": rec.client_order_id,
                "order_id": rec.order_id,
                "ticker": rec.ticker,
                "resting_ms": round((rec.fill_ts - (rec.submit_ts or rec.fill_ts)) * 1000.0, 1),
                "limit_price_cents": rec.limit_price_cents,
                "fill_price_cents": fill_px,
                "edge_pct_at_candidate": rec.edge_pct,
                "ev_net_cents_at_candidate": rec.ev_net_cents,
                "gross_edge_cents_at_fill": edge_at_fill,
                "decision_id": rec.decision_id,
                "threshold_cell_id": rec.threshold_cell_id,
                "provisional_cell_id": rec.provisional_cell_id,
            })
            # 2026-09-30: threshold-cell lane bookkeeping — the fill is the
            # exposure event; drives fills/day caps and suspension stats.
            if rec.threshold_cell_id:
                try:
                    from merid.prediction import threshold_cells as _tc
                    _tc.record_cell_fill(
                        rec.threshold_cell_id,
                        decision_id=rec.decision_id,
                        fill_ev_cents=edge_at_fill,
                        candidate_ev_cents=rec.ev_net_cents,
                    )
                    _tc.record_cell_order_closed(rec.threshold_cell_id, rec.order_id)
                    _tc.emit_cell_lifecycle(
                        "filled",
                        threshold_cell_id=rec.threshold_cell_id,
                        asset=rec.asset,
                        side=(rec.side or "").upper(),
                        decision_id=rec.decision_id,
                        intent_id=rec.intent_id,
                        client_order_id=rec.client_order_id,
                        order_id=rec.order_id,
                        post_only=True,
                        submitted=True,
                        filled=True,
                        fill_price_cents=fill_px,
                        limit_price_cents=rec.limit_price_cents,
                        resting_ms=round(
                            (rec.fill_ts - (rec.submit_ts or rec.fill_ts)) * 1000.0, 1
                        ),
                        ev_net_cents_at_candidate=rec.ev_net_cents,
                        gross_edge_cents_at_fill=edge_at_fill,
                        terminal_state="filled",
                    )
                except Exception:
                    pass
            # Current-build provisional lane: the same fill event feeds the
            # lane's fills/day caps, first-fill suspension rules, and the
            # versioned evidence store.  A fill priced through the limit is a
            # post-only contract breach — the lane suspends immediately.
            if rec.provisional_cell_id:
                try:
                    from merid.prediction import (
                        current_build_provisional as _cbp,
                    )
                    _resting_ms = round(
                        (rec.fill_ts - (rec.submit_ts or rec.fill_ts)) * 1000.0,
                        1,
                    )
                    _cbp.record_provisional_fill(
                        rec.provisional_cell_id,
                        decision_id=rec.decision_id,
                        fill_ev_cents=edge_at_fill,
                        candidate_ev_cents=rec.ev_net_cents,
                        fill_price_cents=fill_px,
                        limit_price_cents=rec.limit_price_cents,
                        action=rec.action,
                    )
                    _cbp.record_provisional_order_closed(
                        rec.provisional_cell_id, rec.order_id
                    )
                    _pcell = _cbp.provisional_cell_for_id(rec.provisional_cell_id)
                    _cbp.emit_provisional_lifecycle(
                        "filled",
                        provisional_cell_id=rec.provisional_cell_id,
                        asset=rec.asset,
                        side=(rec.side or "").upper(),
                        decision_id=rec.decision_id,
                        intent_id=rec.intent_id,
                        client_order_id=rec.client_order_id,
                        order_id=rec.order_id,
                        post_only=True,
                        submitted=True,
                        filled=True,
                        fill_price_cents=fill_px,
                        limit_price_cents=rec.limit_price_cents,
                        resting_ms=_resting_ms,
                        ev_net_cents_at_candidate=rec.ev_net_cents,
                        gross_edge_cents_at_fill=edge_at_fill,
                        price_bucket=(
                            _cbp.price_band_label(_pcell) if _pcell else None
                        ),
                        tte_bucket=(
                            _cbp.tte_band_label(_pcell) if _pcell else None
                        ),
                        build_sha=_cbp.current_build_sha(),
                        calibration_version=_cbp.current_calibration_version(),
                        terminal_state="filled",
                    )
                    _cbp.record_cb_evidence(
                        "fill",
                        provisional_cell_id=rec.provisional_cell_id,
                        asset=rec.asset,
                        side=(rec.side or "").upper(),
                        decision_id=rec.decision_id,
                        order_id=rec.order_id,
                        entry_price_cents=rec.limit_price_cents,
                        fill_price_cents=fill_px,
                        fill_ev_cents=edge_at_fill,
                        decision_ev_cents=rec.ev_net_cents,
                        fill_latency_ms=_resting_ms,
                        post_only=True,
                        filled=True,
                        terminal_reason="filled",
                    )
                except Exception:
                    pass
            break

    def _close(self, rec: _OrderRecord, reason: str, now: float) -> None:
        rec.closed = True
        _append_event({
            "event": "terminal",
            "ts": now,
            "client_order_id": rec.client_order_id,
            "order_id": rec.order_id,
            "ticker": rec.ticker,
            "reason": reason,
            "filled": rec.filled,
            "fill_price_cents": rec.fill_price_cents,
            "markouts": rec.markouts or None,
            "decision_id": rec.decision_id,
            "threshold_cell_id": rec.threshold_cell_id,
            "provisional_cell_id": rec.provisional_cell_id,
        })
        # 2026-09-30: free the cell's open-order slot and leave a terminal
        # lifecycle record (fill/no-fill + markouts at close).
        if rec.threshold_cell_id:
            try:
                from merid.prediction import threshold_cells as _tc
                _tc.record_cell_order_closed(rec.threshold_cell_id, rec.order_id)
                _tc.emit_cell_lifecycle(
                    "terminal",
                    threshold_cell_id=rec.threshold_cell_id,
                    asset=rec.asset,
                    side=(rec.side or "").upper(),
                    decision_id=rec.decision_id,
                    intent_id=rec.intent_id,
                    client_order_id=rec.client_order_id,
                    order_id=rec.order_id,
                    post_only=True,
                    submitted=True,
                    filled=rec.filled,
                    fill_price_cents=rec.fill_price_cents,
                    markouts=rec.markouts or None,
                    terminal_state=reason,
                )
            except Exception:
                pass
        if rec.provisional_cell_id:
            try:
                from merid.prediction import (
                    current_build_provisional as _cbp,
                )
                _cbp.record_provisional_order_closed(
                    rec.provisional_cell_id, rec.order_id
                )
                _pcell = _cbp.provisional_cell_for_id(rec.provisional_cell_id)
                _cbp.emit_provisional_lifecycle(
                    "terminal",
                    provisional_cell_id=rec.provisional_cell_id,
                    asset=rec.asset,
                    side=(rec.side or "").upper(),
                    decision_id=rec.decision_id,
                    intent_id=rec.intent_id,
                    client_order_id=rec.client_order_id,
                    order_id=rec.order_id,
                    post_only=True,
                    submitted=True,
                    filled=rec.filled,
                    fill_price_cents=rec.fill_price_cents,
                    markouts=rec.markouts or None,
                    price_bucket=(
                        _cbp.price_band_label(_pcell) if _pcell else None
                    ),
                    tte_bucket=(
                        _cbp.tte_band_label(_pcell) if _pcell else None
                    ),
                    terminal_state=reason,
                )
                _mk = rec.markouts or {}
                _cbp.record_cb_evidence(
                    "terminal",
                    provisional_cell_id=rec.provisional_cell_id,
                    asset=rec.asset,
                    side=(rec.side or "").upper(),
                    decision_id=rec.decision_id,
                    order_id=rec.order_id,
                    entry_price_cents=rec.limit_price_cents,
                    fill_price_cents=rec.fill_price_cents,
                    filled=rec.filled,
                    markout_1s_cents=(_mk.get("1s") or {}).get("markout_cents"),
                    markout_5s_cents=(_mk.get("5s") or {}).get("markout_cents"),
                    markout_30s_cents=(
                        _mk.get("30s") or {}
                    ).get("markout_cents"),
                    post_only=True,
                    terminal_reason=reason,
                )
            except Exception:
                pass


_tracker: Optional[FillQualityTracker] = None
_tracker_lock = threading.Lock()


def get_fill_quality_tracker() -> FillQualityTracker:
    global _tracker
    with _tracker_lock:
        if _tracker is None:
            _tracker = FillQualityTracker()
        return _tracker
