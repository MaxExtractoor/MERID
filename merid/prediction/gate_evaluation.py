"""Pure, read-only evaluation of the complete decision gate vector.

The live execution path in ``compute_trade_decision`` intentionally
short-circuits at the first failing gate.  For research and audit we need the
opposite view: *every* gate's state at decision time, evaluated against the
exact evidence the decision consumed.

This module never re-runs gate logic against fresh data.  It projects the
already-computed decision evidence (``TradeDecision.indicators`` plus the
decision's own fields) into a structured ``GateEvaluation``.  It is pure:

* no mutation of cooldowns, allocations, bankroll, or venue state;
* no network/venue calls;
* optional ``market_state`` is read-only snapshot evidence.

Persisted on ``strategy_decisions.gate_results_json`` /
``all_failed_gates_json`` so the hourly report can distinguish the live
first-failure blocker from the complete set of simultaneous gate failures.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, Mapping, Optional, Tuple

GATE_EVALUATION_SCHEMA_VERSION = 1

# Stage vocabulary shared with merid.execution.decision_audit_ledger so gate
# rows and lifecycle events speak the same language.
STAGE_PRE_DECISION = "PRE_DECISION"
STAGE_MODEL = "MODEL"

# Canonical gate name -> the raw no_trade_reason fragments that mean "this
# gate was the live blocker".  Matching is prefix/substring tolerant because
# live reasons append side suffixes (``_yes``/``_no``) and parameters.
_REASON_TO_GATE: Tuple[Tuple[str, str], ...] = (
    ("expired_or_no_time", "market_time"),
    ("final_minute_entry_disabled", "market_time"),
    ("settlement_lane_price_cap", "market_time"),
    ("invalid_executable_asks", "executable_quotes"),
    ("non_finite_", "executable_quotes"),
    ("data_state_not_healthy", "data_state"),
    ("bachelier_vol_resolution_failed", "data_state"),
    ("regime_unclassified", "data_state"),
    ("regime_uncertain", "data_state"),
    ("invalid_confidence", "confidence_valid"),
    ("directional_tie", "side_selection"),
    ("no_qualifying_side", "side_selection"),
    ("insufficient_depth", "depth"),
    ("tail_guard", "tail_guard"),
    ("no_positive_executable_edge", "positive_ev"),
    ("edge_below_threshold", "edge_threshold"),
    ("cost_basis", "cost_basis"),
    ("held_entry_price_below_floor", "cost_basis"),
    ("evidence_", "evidence"),
    ("calibration_evidence", "evidence"),
    ("live_evidence_", "evidence"),
    ("market_fade_blocked", "fade_gate"),
    ("regime_block", "regime"),
    ("low_conviction", "conviction"),
    ("conviction", "conviction"),
    ("throttle", "throttle"),
    ("ct_lane", "countertrend_lane"),
    ("countertrend", "countertrend_lane"),
    ("bookflow", "book_flow"),
    ("book_flow", "book_flow"),
    ("trend_yes_hi", "trend_hi_lane"),
    ("both_sides_out_of_range", "price_band"),
    ("both_sides_out_of_canonical", "price_band"),
    ("price_out_of_canonical_range", "price_band"),
    ("ev_gate_rejected", "ev_gate"),
)


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, Decimal):
        value = float(value)
    try:
        f = float(value)
    except Exception:
        return None
    return f if math.isfinite(f) else None


def _to_bool(value: Any) -> Optional[bool]:
    if value is None:
        return None
    return bool(value)


def _ind_flag(indicators: Mapping[str, Any], key: str) -> Tuple[bool, Optional[bool]]:
    """Return (evaluated, passed) for a flag that may be absent."""
    if key not in indicators:
        return False, None
    v = indicators.get(key)
    return True, bool(v)


def _block_gate(
    indicators: Mapping[str, Any],
    key: str,
) -> Tuple[bool, Optional[bool], Optional[str]]:
    """A block-reason gate: absent key -> not evaluated; value None -> pass."""
    if key not in indicators:
        return False, None, None
    v = indicators.get(key)
    return True, (v is None), (str(v) if v is not None else None)


def _blocking_gate_names(reason: Optional[str], side: Optional[str]) -> set:
    """Map a live no_trade_reason to the gate names that owned it."""
    if not reason:
        return set()
    r = str(reason).lower()
    names: set = set()
    for fragment, gate in _REASON_TO_GATE:
        if fragment in r:
            if gate in (
                "depth",
                "tail_guard",
                "positive_ev",
                "edge_threshold",
                "cost_basis",
                "evidence",
                "regime",
                "conviction",
                "throttle",
                "countertrend_lane",
                "book_flow",
                "fade_gate",
            ):
                # Per-side gate: attach the side encoded in the reason, else
                # the decision's best_side.
                s = (
                    "yes"
                    if r.endswith("_yes")
                    else "no"
                    if r.endswith("_no")
                    else side
                )
                names.add(f"{s}_{gate}" if s else f"unknown_{gate}")
            else:
                names.add(gate)
    return names


@dataclass(frozen=True)
class GateResult:
    gate_name: str
    gate_code: str
    stage: str
    # None == the live path never reached this gate (early short-circuit) or
    # the evidence was absent; the gate is not assumed pass or fail.
    passed: Optional[bool]
    observed: Dict[str, Any]
    threshold: Dict[str, Any]
    blocking_in_live_path: bool = False
    evaluation_error: Optional[str] = None


@dataclass(frozen=True)
class GateEvaluation:
    primary_reason_code: Optional[str]
    all_failed_gates: Tuple[str, ...]
    gate_results: Tuple[GateResult, ...]
    evaluation_schema_version: int = GATE_EVALUATION_SCHEMA_VERSION

    def gate_results_dict(self) -> Dict[str, Any]:
        """JSON-serializable ``{gate_name: {...}}`` mapping for the audit row."""
        out: Dict[str, Any] = {}
        for g in self.gate_results:
            out[g.gate_name] = {
                "gate_code": g.gate_code,
                "stage": g.stage,
                "passed": g.passed,
                "observed": g.observed,
                "threshold": g.threshold,
                "blocking_in_live_path": g.blocking_in_live_path,
            }
            if g.evaluation_error:
                out[g.gate_name]["evaluation_error"] = g.evaluation_error
        return out


def _book_is_crossed(market_state: Optional[Any]) -> Optional[bool]:
    if market_state is None:
        return None
    bid = _to_float(getattr(market_state, "best_bid_cents", None))
    ask = _to_float(getattr(market_state, "best_ask_cents", None))
    if bid is None or ask is None:
        return None
    return bid > ask


def evaluate_all_gates(
    decision: Any, market_state: Optional[Any] = None
) -> Optional[GateEvaluation]:
    """Project a TradeDecision's recorded evidence into the full gate vector.

    Read-only; returns None only if ``decision`` is unusable.  Gates whose
    evidence never materialized (early-return decisions) are emitted with
    ``passed=None`` — they are not counted as failures and not credited as
    passes.
    """
    if decision is None:
        return None

    ind = getattr(decision, "indicators", None) or {}
    if not isinstance(ind, Mapping):
        ind = {}
    reason = getattr(decision, "no_trade_reason", None)
    best_side = getattr(decision, "best_side", None) or getattr(
        decision, "selected_outcome", None
    )
    blocking = _blocking_gate_names(reason, best_side)

    results = []

    def _add(
        name: str,
        code: str,
        stage: str,
        evaluated: bool,
        passed: Optional[bool],
        observed: Optional[Dict[str, Any]] = None,
        threshold: Optional[Dict[str, Any]] = None,
    ) -> None:
        results.append(
            GateResult(
                gate_name=name,
                gate_code=code,
                stage=stage,
                passed=(passed if evaluated else None),
                observed=dict(observed or {}),
                threshold=dict(threshold or {}),
                blocking_in_live_path=name in blocking,
            )
        )

    # ── Layer-1 input gates (evaluated at the model boundary) ────────────
    seconds_to_expiry = _to_float(getattr(decision, "seconds_to_expiry", None))
    tte_failed = reason in (
        "expired_or_no_time",
        "final_minute_entry_disabled",
        "settlement_lane_price_cap",
    )
    _add(
        "market_time",
        "TTE_ENTRY_CUTOFF",
        STAGE_PRE_DECISION,
        evaluated=seconds_to_expiry is not None or tte_failed,
        passed=not tte_failed if (seconds_to_expiry is not None or tte_failed) else None,
        observed={"seconds_to_expiry": seconds_to_expiry},
        threshold={"min_seconds_to_close": None},
    )

    yes_entry = _to_float(ind.get("yes_entry_price_cents"))
    no_entry = _to_float(ind.get("no_entry_price_cents"))
    quotes_failed = bool(
        reason
        and (
            str(reason).startswith("invalid_executable_asks")
            or str(reason).startswith("non_finite_")
        )
    )
    _add(
        "executable_quotes",
        "MARKET_UNAVAILABLE",
        STAGE_PRE_DECISION,
        evaluated=(yes_entry is not None or no_entry is not None or quotes_failed),
        passed=not quotes_failed,
        observed={
            "yes_entry_price_cents": yes_entry,
            "no_entry_price_cents": no_entry,
        },
        threshold={},
    )

    data_state = getattr(decision, "data_state", None)
    ds_failed = bool(
        reason
        and str(reason).startswith(
            ("data_state_not_healthy", "bachelier_vol_resolution_failed")
        )
    )
    _add(
        "data_state",
        "SPOT_NOT_TRUSTED",
        STAGE_PRE_DECISION,
        evaluated=data_state is not None or ds_failed,
        passed=(not ds_failed) if (data_state is not None or ds_failed) else None,
        observed={"data_state": data_state, "data_quality": getattr(decision, "data_quality", None)},
        threshold={},
    )

    conf_valid = getattr(decision, "confidence_valid", None)
    conf_failed = reason == "invalid_confidence"
    _add(
        "confidence_valid",
        "EVIDENCE_HARD_BLOCK",
        STAGE_PRE_DECISION,
        evaluated=conf_valid is not None or conf_failed,
        passed=not conf_failed if conf_valid is None else bool(conf_valid),
        observed={
            "confidence": _to_float(getattr(decision, "confidence", None)),
            "confidence_source": getattr(decision, "confidence_source", None),
        },
        threshold={},
    )

    book_crossed = _book_is_crossed(market_state)
    book_initialized = (
        getattr(market_state, "book_initialized", None)
        if market_state is not None
        else None
    )
    book_quality = (
        getattr(market_state, "data_quality", None)
        if market_state is not None
        else None
    )
    book_eval = market_state is not None
    book_ok = (
        book_eval
        and book_initialized is True
        and book_quality == "GOOD"
        and book_crossed is False
    )
    _add(
        "book_trusted",
        "BOOK_NOT_TRUSTED",
        STAGE_PRE_DECISION,
        evaluated=book_eval,
        passed=book_ok if book_eval else None,
        observed={
            "book_initialized": book_initialized,
            "data_quality": book_quality,
            "is_crossed": book_crossed,
        },
        threshold={"required_data_quality": "GOOD"},
    )

    # ── Per-side model-stage gates ────────────────────────────────────────
    for side in ("yes", "no"):
        depth_cc = _to_float(getattr(decision, f"{side}_depth_cc", None))
        net_edge_cents = _to_float(ind.get(f"{side}_ev_net_cents"))
        if net_edge_cents is None:
            bd = getattr(decision, f"{side}_edge_breakdown", None)
            ne = _to_float(getattr(bd, "net_edge", None)) if bd is not None else None
            net_edge_cents = ne * 100.0 if ne is not None else None
        gross_edge_cents = _to_float(ind.get(f"{side}_gross_edge_cents"))
        min_edge_cents = _to_float(ind.get(f"{side}_min_edge"))
        if min_edge_cents is not None and abs(min_edge_cents) <= 1.0:
            # indicators store min_edge in probability units on some paths.
            min_edge_cents = min_edge_cents * 100.0
        p_selected = _to_float(ind.get(f"{side}_p_selected"))
        min_p = _to_float(ind.get(f"{side}_min_p_selected"))
        qualifies = _to_bool(ind.get(f"{side}_qualifies"))
        side_block = ind.get(f"{side}_block")

        dep_eval, dep_pass = _ind_flag(ind, f"{side}_depth_ok")
        if not dep_eval and depth_cc is not None:
            dep_eval, dep_pass = True, depth_cc >= 100.0
        _add(
            f"{side}_depth",
            "SIDE_NOT_LIQUID",
            STAGE_MODEL,
            evaluated=dep_eval,
            passed=dep_pass,
            observed={"depth_cc": depth_cc},
            threshold={"min_depth_cc": 100.0},
        )

        tail_eval = f"tail_guard_violation_{side}" in ind
        tail_pass = not bool(ind.get(f"tail_guard_violation_{side}")) if tail_eval else None
        _add(
            f"{side}_tail_guard",
            "EVIDENCE_HARD_BLOCK",
            STAGE_MODEL,
            evaluated=tail_eval,
            passed=tail_pass,
            observed={"violation": bool(ind.get(f"tail_guard_violation_{side}")) if tail_eval else None},
            threshold={},
        )

        pev_eval = net_edge_cents is not None
        _add(
            f"{side}_positive_ev",
            "NO_POSITIVE_EXECUTABLE_EDGE",
            STAGE_MODEL,
            evaluated=pev_eval,
            passed=(net_edge_cents > 0.0) if pev_eval else None,
            observed={
                "net_edge_cents": net_edge_cents,
                "gross_edge_cents": gross_edge_cents,
            },
            threshold={"min_net_edge_cents": 0.0},
        )

        thr_eval = net_edge_cents is not None and min_edge_cents is not None
        _add(
            f"{side}_edge_threshold",
            "EDGE_BELOW_DYNAMIC_THRESHOLD",
            STAGE_MODEL,
            evaluated=thr_eval,
            passed=(net_edge_cents >= min_edge_cents - 1e-9) if thr_eval else None,
            observed={
                "net_edge_cents": net_edge_cents,
                "threshold_cents": min_edge_cents,
            },
            threshold={"min_net_edge_cents": min_edge_cents},
        )

        cb_eval = p_selected is not None and min_p is not None
        _add(
            f"{side}_cost_basis",
            "NO_POSITIVE_EXECUTABLE_EDGE",
            STAGE_MODEL,
            evaluated=cb_eval,
            passed=(p_selected > min_p) if cb_eval else None,
            observed={"p_selected": p_selected, "min_p_selected": min_p},
            threshold={"min_p_selected": min_p},
        )

        ev_eval, ev_pass = _ind_flag(ind, f"{side}_evidence_ok")
        _add(
            f"{side}_evidence",
            "EVIDENCE_HARD_BLOCK",
            STAGE_MODEL,
            evaluated=ev_eval,
            passed=ev_pass,
            observed={"evidence_reason": ind.get(f"{side}_evidence_reason")},
            threshold={},
        )

        for key, gate_suffix, code in (
            (f"{side}_regime_block", "regime", "EVIDENCE_HARD_BLOCK"),
            (f"{side}_conviction_block", "conviction", "EVIDENCE_HARD_BLOCK"),
            (f"{side}_throttle_block", "throttle", "EVIDENCE_HARD_BLOCK"),
            (f"{side}_ct_lane_block", "countertrend_lane", "EVIDENCE_HARD_BLOCK"),
            (f"{side}_bookflow_block", "book_flow", "EVIDENCE_HARD_BLOCK"),
        ):
            beval, bpass, breason = _block_gate(ind, key)
            _add(
                f"{side}_{gate_suffix}",
                code,
                STAGE_MODEL,
                evaluated=beval,
                passed=bpass,
                observed={"block_reason": breason},
                threshold={},
            )

        # trend_hi lane only applies to YES in the 91-94c window.
        if side == "yes":
            beval, bpass, breason = _block_gate(ind, "yes_trend_hi_block")
            hi_applies = _to_bool(ind.get("yes_trend_hi_price"))
            _add(
                "yes_trend_hi_lane",
                "EVIDENCE_HARD_BLOCK",
                STAGE_MODEL,
                evaluated=beval or hi_applies is not None,
                passed=(bpass if beval else True),
                observed={"block_reason": breason, "hi_price_window": hi_applies},
                threshold={},
            )

        _add(
            f"{side}_qualified",
            "CANDIDATE_EMITTED",
            STAGE_MODEL,
            evaluated=qualifies is not None,
            passed=qualifies,
            observed={"first_block": side_block},
            threshold={},
        )

    all_failed = tuple(g.gate_name for g in results if g.passed is False)
    primary = reason or (
        "selected" if getattr(decision, "selected_outcome", None) else "unknown"
    )
    return GateEvaluation(
        primary_reason_code=primary,
        all_failed_gates=all_failed,
        gate_results=tuple(results),
    )
