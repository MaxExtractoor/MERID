"""Rejection counterfactual logger for the 15m trade-decision path.

Every candidate that is rejected by an economic gate (edge threshold, cost
basis floor, pi* EV gate, held-price floor) is appended as a JSONL record to
``logs/rejected_candidates.jsonl``.  A post-settlement join script
(``scripts/rejection_counterfactual_report.py``) matches each record to the
market's realized outcome and classifies the rejection as:

- ``saved``   - the trade would have lost money (correct rejection)
- ``missed``  - the trade would have been net profitable (wrong rejection)
- ``flat``    - counterfactual P&L within +/-1c of zero
- ``unclassifiable`` - no settlement outcome found for the ticker

This is deliberately write-only and exception-safe: a logging failure must
never alter or delay a trading decision.
"""
from __future__ import annotations

import atexit
import json
import os
import queue
import threading
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("merid.prediction.rejection_counterfactual")

_DEFAULT_PATH = os.path.join("logs", "rejected_candidates.jsonl")
_lock = threading.Lock()

_ENABLED = os.environ.get("MERID_REJECTION_COUNTERFACTUAL_ENABLED", "1").strip().lower() in (
    "1",
    "true",
    "yes",
)

# Only economic rejections are interesting for counterfactual analysis.
# Infrastructure rejections (no market, stale data, halted reconciliation)
# carry no signal about threshold calibration.
_COUNTERFACTUAL_REASON_PREFIXES = (
    "yes_edge_below_threshold",
    "no_edge_below_threshold",
    "cost_basis_override_",
    "p_selected_below_pi_star",
    "held_entry_price_below_floor",
    "calibration_evidence_",
    "live_evidence_",
    "evidence_",
    "market_fade_blocked_",
    # 2026-10-04: structural strategy gates.  These veto candidates whose
    # economics already cleared, so they are the gates most in need of a
    # settlement counterfactual — previously they were a blind spot.
    "countertrend_",
    "bookflow_",
    "low_conviction",
    "strip_same_side_",
    "side_suspended",
    "trend_yes_hi",
    "yes_edge_below_lane_floor",
    "no_edge_below_lane_floor",
    # 2026-10-04: close the remaining outcome blind spots.
    #   bounded_domain_*  — TTE-ceiling downgrades (never previously logged)
    #   tail_lcb_gate     — high-price LCB downgrades (never previously logged)
    #   no_positive_executable_edge — the largest volume rejection class
    #   net_ev_below_min_dollar — flat $0.03/order floor rejects
    #   market_unavailable / book_not_trusted / no_eligible_price_band /
    #   tte_entry_cutoff — funnel kills upstream of qualification
    "bounded_domain_",
    "tail_lcb_gate",
    "no_positive_executable_edge",
    "net_ev_below_min_dollar",
    "market_unavailable",
    "book_not_trusted",
    "no_eligible_price_band",
    "tte_entry_cutoff",
    "structural_risk_veto",
    "edge_below_dynamic_threshold",
    # 2026-10-09: the fixed selected-side entry-price cap.  Cap rejections
    # carry the shadow verdict (qualified_ex_cap + other_failures) so the
    # marginal >75c cohort is measurable without submitting anything.
    "entry_price_cap_",
)


def should_log(reason: Optional[str]) -> bool:
    if not reason:
        return False
    return any(reason.startswith(p) for p in _COUNTERFACTUAL_REASON_PREFIXES)


def _price_bucket(price_cents: Optional[float]) -> Optional[str]:
    """Map a held-side executable price to the mandate's band vocabulary."""
    if price_cents is None:
        return None
    try:
        p = float(price_cents)
    except (TypeError, ValueError):
        return None
    if p < 0 or p > 100:
        return None
    bands = ((1, 9), (10, 19), (20, 39), (40, 59), (60, 79), (80, 89), (90, 99))
    for lo, hi in bands:
        if lo <= p <= hi:
            return f"{lo}-{hi}c"
    if p < 1:
        return "0-1c"
    return "100c"


# 2026-10-12: STRUCTURAL_RISK_VETO decomposition.  The canonical code bundles
# several unrelated risk conditions; the counterfactual join needs each
# sub-condition scored separately before any one of them is relaxed (a
# composite 43W/8L veto record cannot tell us WHICH guard is over/under
# strict).  Map the raw reason stem onto the sub-gate family that owns it.
# Prefixes matched against the emitted ``no_trade_reason`` stem (see
# directional_regime.py / trade_decision.py for the source strings).
_STRUCTURAL_SUBREASON_RULES = (
    # price-band / moneyness restriction
    ("moneyness_coin_flip", "moneyness_price_band"),
    ("entry_price_cap", "moneyness_price_band"),
    ("trend_yes_hi", "trend_hi_lane"),
    # late-time-to-expiry / bounded-domain restriction
    ("bounded_domain", "bounded_domain"),
    ("ev_to_tail_ratio_below_min", "ev_tail_ratio"),
    # spread / book-depth restriction
    ("bookflow_", "book_flow"),
    # countertrend / regime structure (regime_entry_block emits the
    # countertrend_* family directly)
    ("countertrend_", "countertrend_lane"),
    # suspension / probation state (side_throttle_block emits
    # side_suspended*; strip_concentration_block emits strip_same_side_*)
    ("side_suspended", "side_suspension"),
    ("strip_same_side_", "same_side_streak"),
    # conviction floor (LOW_CONVICTION canonical code — a structural veto
    # variant in the shared taxonomy)
    ("low_conviction", "conviction"),
)


def structural_subreason(reason: Optional[str]) -> Optional[str]:
    """Decompose a STRUCTURAL_RISK_VETO / LOW_CONVICTION reason into the
    sub-gate family that produced it (price-band/moneyness, bounded-domain,
    book-flow, countertrend/regime, suspension/probation, conviction).

    Returns None for non-structural reasons so the field stays sparse —
    scoring only needs the decomposition where the composite veto fired.
    """
    rl = (reason or "").strip().lower()
    if not rl:
        return None
    for prefix, family in _STRUCTURAL_SUBREASON_RULES:
        if rl.startswith(prefix):
            return family
    return None


def _canonical_reason(reason: str, net_edge: Optional[float]) -> Optional[str]:
    """Resolve the mutually exclusive top-level rejection code.

    Delegates to the shared ``canonical_terminal_code`` taxonomy so every
    funnel stage uses one vocabulary (MARKET_UNAVAILABLE / BOOK_NOT_TRUSTED /
    NO_ELIGIBLE_PRICE_BAND / NO_POSITIVE_EXECUTABLE_EDGE /
    EDGE_BELOW_DYNAMIC_THRESHOLD / ...).
    """
    try:
        from merid.prediction.terminal_codes import canonical_terminal_code

        best_ev_cents = None
        if net_edge is not None:
            try:
                best_ev_cents = float(net_edge) * 100.0
            except (TypeError, ValueError):
                best_ev_cents = None
        return canonical_terminal_code(reason, best_ev_cents)
    except Exception:
        return None


def log_rejected_candidate(
    *,
    reason: str,
    run_id: str,
    decision_id: str,
    asset: str,
    ticker: Optional[str],
    side: Optional[str],
    model_p_selected: Optional[float],
    held_price_cents: Optional[float],
    gross_edge: Optional[float],
    net_edge: Optional[float],
    edge_threshold: Optional[float] = None,
    pi_star: Optional[float] = None,
    min_p_selected: Optional[float] = None,
    tte_seconds: Optional[float] = None,
    spot_price: Optional[float] = None,
    strike_price: Optional[float] = None,
    fee_cents: Optional[float] = None,
    # 2026-10-05: executable-price counterfactual fields (mandate).  All
    # optional; the scorecard joins on whatever the producing gate could see.
    route: Optional[str] = None,
    depth_for_quantity_cc: Optional[float] = None,
    impact_reserve_cents: Optional[float] = None,
    risk_reserve_cents: Optional[float] = None,
    exit_cost_reserve_cents: Optional[float] = None,
    adverse_selection_reserve_cents: Optional[float] = None,
    book_imbalance: Optional[float] = None,
    quote_state: Optional[str] = None,
    quote_age_ms: Optional[float] = None,
    book_sequence: Optional[int] = None,
    intended_quantity: Optional[int] = None,
    # 2026-10-09: entry-cap shadow evaluation — the complete ex-cap gate
    # verdict for every cap-blocked side (qualified_ex_cap, other_failures,
    # price band, EV vs bound, depth, TTE).  Present only when the fixed
    # cap was a blocker.
    cap_shadow: Optional[dict] = None,
    # 2026-10-09 (evidence-policy audit): the three-axis admission verdicts
    # per side — economics_verdict / evidence_verdict / exploration_verdict
    # plus the mutually-exclusive admission_verdict — so a bounded
    # negative-floor admit never reads as a profitable production admit.
    side_verdicts: Optional[dict] = None,
    # 2026-10-09: BOTH side asks at decision time.  Without these the
    # non-selected side's price was reconstructed as 100 - selected ask,
    # which is actually the opposite-side BID (a_N = 1 - b_Y), understating
    # the true ask by the spread and inflating blocked-opportunity counts.
    yes_price_cents: Optional[float] = None,
    no_price_cents: Optional[float] = None,
    # ask | bid — which book level the yes/no price fields represent.  Under
    # bid-basis (maker lane) they are BIDS, not asks; band-matching on them
    # as asks would reintroduce the spread error this change removes.
    entry_price_basis: Optional[str] = None,
    # 2026-10-12: marginal-band shadow verdict — the would-be rescue verdict
    # for cohorts the release band does not yet admit (YES side, BTC/ETH).
    # Present only when the marginal-band domain was evaluated; carries
    # per-side shadow_rescued / live flags so the denied cohorts' outcomes
    # can be scored out-of-sample.
    band_shadow: Optional[dict] = None,
) -> None:
    """Append one rejected-candidate record.  Never raises."""
    if not _ENABLED or not should_log(reason):
        return
    try:
        # Derived attribution: the true shortfall is how far the candidate's
        # net edge fell below its active dynamic threshold (cents), and the
        # underlying distance is spot-vs-strike separation when both exist.
        true_shortfall_cents = None
        if net_edge is not None and edge_threshold is not None:
            try:
                true_shortfall_cents = max(
                    0.0, (float(edge_threshold) - float(net_edge)) * 100.0
                )
            except (TypeError, ValueError):
                true_shortfall_cents = None
        underlying_distance = None
        if spot_price is not None and strike_price is not None:
            try:
                underlying_distance = float(spot_price) - float(strike_price)
            except (TypeError, ValueError):
                underlying_distance = None

        record = {
            "type": "rejected_candidate",
            "schema_version": 3,
            "event_ts_utc": datetime.now(timezone.utc).isoformat(),
            "run_id": run_id,
            "decision_id": decision_id,
            "asset": asset,
            "ticker": ticker,
            "window_id": ticker,  # 15m ticker IS the window id
            "side": side,
            "route": route,
            "model_p_selected": model_p_selected,
            "fair_probability": model_p_selected,
            "held_price_cents": held_price_cents,
            "executable_price_cents": held_price_cents,
            "yes_price_cents": yes_price_cents,
            "no_price_cents": no_price_cents,
            "entry_price_basis": entry_price_basis,
            "price_bucket": _price_bucket(held_price_cents),
            "depth_for_quantity_cc": depth_for_quantity_cc,
            "intended_quantity": intended_quantity,
            "gross_edge": gross_edge,
            "net_edge": net_edge,
            "edge_threshold": edge_threshold,
            "dynamic_threshold": edge_threshold,
            "true_shortfall_cents": true_shortfall_cents,
            "pi_star": pi_star,
            "min_p_selected": min_p_selected,
            "tte_seconds": tte_seconds,
            "spot_price": spot_price,
            "strike_price": strike_price,
            "underlying_distance_from_strike": underlying_distance,
            "book_imbalance": book_imbalance,
            "quote_state": quote_state,
            "quote_age_ms": quote_age_ms,
            "book_sequence": book_sequence,
            "fee_cents": fee_cents,
            "impact_reserve_cents": impact_reserve_cents,
            "risk_reserve_cents": risk_reserve_cents,
            "exit_cost_reserve_cents": exit_cost_reserve_cents,
            "adverse_selection_reserve_cents": adverse_selection_reserve_cents,
            "reject_reason": reason,
            "canonical_reason": _canonical_reason(reason, net_edge),
            "structural_subreason": structural_subreason(reason),
            "cap_shadow": cap_shadow,
            "side_verdicts": side_verdicts,
            "band_shadow": band_shadow,
        }
        path = os.environ.get("MERID_REJECTED_CANDIDATES_LOG", _DEFAULT_PATH)
        line = json.dumps(record, default=str)
        _enqueue_line(path, line + "\n")
    except Exception as e:  # pragma: no cover - telemetry must never break trading
        logger.debug("[REJECTED-CANDIDATE] failed to write record: %s", e)


# ── Buffered async appender ────────────────────────────────────────────────
# 2026-10-14 (HDD-aware): the previous implementation did open+write+close
# per record synchronously on the decision thread — a ~100-200ms disk hit
# per rejected candidate on the production spindle.  Records now queue to a
# dedicated writer thread that drains bursts into one append+close per path
# per burst.  Loss window: bounded by the flush cadence (process kill loses
# <1s of telemetry; OS page-cache data survives process crash).  Queue
# backpressure drops records rather than ever blocking the decision path.
_LINE_Q: "queue.Queue[Tuple[str, str]]" = queue.Queue(
    maxsize=int(os.environ.get("MERID_REJECTED_CANDIDATES_QSIZE", "20000"))
)
_WRITER_STARTED = False
_WRITER_BOOT_LOCK = threading.Lock()
_FLUSH_IDLE_S = 1.0
_dropped_lines = 0


def _is_test_env() -> bool:
    return os.environ.get("MERID_ENV", "").lower() in ("testing", "test", "ci")


def _writer_main() -> None:
    pending: Dict[str, List[str]] = {}
    pending_items = 0
    while True:
        try:
            path, line = _LINE_Q.get(timeout=_FLUSH_IDLE_S)
            pending.setdefault(path, []).append(line)
            pending_items += 1
            while True:
                try:
                    p2, l2 = _LINE_Q.get_nowait()
                    pending.setdefault(p2, []).append(l2)
                    pending_items += 1
                except queue.Empty:
                    break
        except queue.Empty:
            pass
        if pending:
            for p, lines in pending.items():
                try:
                    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
                    with open(p, "a", encoding="utf-8") as f:
                        f.writelines(lines)
                except Exception as exc:
                    logger.debug("[REJECTED-CANDIDATE] writer flush failed: %s", exc)
            pending.clear()
            for _ in range(pending_items):
                try:
                    _LINE_Q.task_done()
                except ValueError:
                    break
            pending_items = 0


def _enqueue_line(path: str, line: str) -> None:
    """Queue a line for the writer thread; synchronous under tests."""
    global _WRITER_STARTED, _dropped_lines
    if _is_test_env():
        with _lock:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(line)
        return
    if not _WRITER_STARTED:
        with _WRITER_BOOT_LOCK:
            if not _WRITER_STARTED:
                threading.Thread(
                    target=_writer_main,
                    name="rejected-candidates-writer",
                    daemon=True,
                ).start()
                _WRITER_STARTED = True
    try:
        _LINE_Q.put_nowait((path, line))
    except queue.Full:
        _dropped_lines += 1
        if _dropped_lines % 100 == 1:
            logger.warning(
                "[REJECTED-CANDIDATE] writer queue full; dropped=%d lines",
                _dropped_lines,
            )


def _drain_at_exit() -> None:
    try:
        _LINE_Q.join()
    except Exception:
        pass


atexit.register(_drain_at_exit)
