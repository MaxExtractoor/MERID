"""Paired YES/NO funnel telemetry — both sides of every evaluated market.

Rationale: rare BUY-YES frequency is not evidence of directional bias, and
equal trade counts must never be forced.  What is required is *evidence*:
for every market evaluation, retain both economic sides computed from the
same input snapshot, then record where each side died in the funnel
(eligibility -> allocator -> submit revalidation -> wire).

One ``PAIRED-SIDE-EVAL`` record is emitted per market evaluation.  Downstream
stages attach their results via :func:`update_stage`, which emits
``PAIRED-SIDE-STAGE`` records keyed by ``decision_id`` so the funnel can be
reconstructed off the log stream.  The non-selected side keeps
``*_result="not_selected"`` — honest, not a synthetic counterfactual order.

Deliberate asymmetries are declared in :data:`DOCUMENTED_ASYMMETRIES` and
carried on every record so reviewers can separate intended policy from drift.
"""
from __future__ import annotations

import json
import logging
import os
import time
from collections import OrderedDict
from dataclasses import asdict, dataclass, field, replace
from decimal import Decimal
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_ENABLED = os.environ.get("MERID_PAIRED_SIDE_TELEMETRY", "1").strip().lower() not in (
    "0", "false", "off")

# ---------------------------------------------------------------------------
# Deliberate directional asymmetries.  Everything NOT listed here is required
# to be complement-symmetric: swap YES<->NO, complement probabilities, swap
# book-side inputs and the economics must mirror.
# ---------------------------------------------------------------------------
DOCUMENTED_ASYMMETRIES: Dict[str, str] = {
    "counter_model_premium": (
        "trade_decision._counter_model_veto: a side the model scores below "
        "0.5 must clear an extra edge premium; below the hard p-floor it is "
        "ineligible outright. Deliberate: requires stronger evidence to "
        "trade against the model's own probability."),
    "thesis_side_lock": (
        "agent_grid_15m momentum path: only the thesis side may be selected; "
        "the counter-trend side is recorded but never traded. Deliberate "
        "containment of an unvalidated signal path."),
    "equal_edge_no_tiebreak_signal_path": (
        "agent_grid_15m price-based signal path breaks exact edge ties "
        "toward NO to counteract historical YES-selection bias. Deliberate "
        "but confined to signal generation; canonical TradeDecision "
        "selection treats ties as directional_tie (no-trade)."),
    "directional_tie_no_trade": (
        "trade_decision._select_best_side: |yes_edge - no_edge| <= 1e-9 is "
        "an explicit no-trade (directional_tie), never a hidden side pick."),
    "no_tail_calibration_block": (
        "AGENTS.md: NO-tail entries blocked until a validated NO-held "
        "calibration artifact is approved; YES tail calibration applies "
        "unconditionally below the price floor. Deliberate fail-closed gap."),
    "fvg_size_scale": (
        "agent_grid_15m: FVG-influenced trades are size-scaled (default "
        "0.5) regardless of side; containment sizing is side-symmetric."),
}


@dataclass
class SideEval:
    """One economic side of a market evaluation."""
    side: str                                   # "yes" | "no"
    model_prob: Optional[float] = None          # p_held for this side
    acq_price_cents: Optional[float] = None     # entry vwap / executable ask
    depth_cc: Optional[float] = None            # eligible depth (centi-contracts)
    fee_cents: Optional[float] = None           # entry fee for this side
    exit_reserve_cents: Optional[float] = None  # expected exit cost reserve
    model_risk_reserve_cents: Optional[float] = None
    gross_edge_cents: Optional[float] = None
    net_edge_cents: Optional[float] = None
    edge_meets_threshold: Optional[bool] = None
    eligible: bool = False
    eligibility_reason: str = ""
    # Filled by downstream stages via update_stage():
    allocator_result: Optional[str] = None
    submit_result: Optional[str] = None
    final_direction: Optional[str] = None
    router_handoff: Optional[Dict[str, Any]] = None  # intent-created economics


@dataclass
class PairedSideEval:
    """Both sides of one market evaluation, same input snapshot."""
    decision_id: str
    run_id: str
    ticker: str
    asset: str
    eval_ts_utc: float
    p_yes: Optional[float]
    p_no: Optional[float]
    complement_sum_ok: Optional[bool]           # p_yes + p_no ~= 1
    yes: SideEval
    no: SideEval
    selected_side: Optional[str]
    selection_reason: str
    best_side: Optional[str]
    no_trade_reason: Optional[str]
    ev_gate_allowed: Optional[bool]
    edge_threshold_cents: Optional[float]
    book_sequence: Optional[int] = None
    quote_age_ms: Optional[float] = None
    policy_version: str = ""
    asymmetries: List[str] = field(default_factory=list)

    def side(self, name: str) -> SideEval:
        return self.yes if name == "yes" else self.no

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# Bounded registry: decision_id -> PairedSideEval (stage updates + tests).
_REGISTRY: "OrderedDict[str, PairedSideEval]" = OrderedDict()
_REGISTRY_MAX = 2000


def _f(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except Exception:
        return None


def from_decision(decision: Any, *,
                  book_sequence: Optional[int] = None,
                  quote_age_ms: Optional[float] = None) -> PairedSideEval:
    """Build the paired record from a TradeDecision (reads getattr fields)."""
    p_yes = _f(getattr(decision, "p_yes_calibrated", None))
    p_no = _f(getattr(decision, "p_no_calibrated", None))
    comp_ok = (abs((p_yes or 0.0) + (p_no or 0.0) - 1.0) <= 0.02
               if p_yes is not None and p_no is not None else None)
    sel = getattr(decision, "selected_outcome", None)
    ntr = getattr(decision, "no_trade_reason", None)
    threshold = _f(getattr(decision, "edge_threshold", None))

    def _side(name: str, prob, vwap_f, depth_f, fee_f,
              exit_r_f, mrr_f, gross_f, net_f) -> SideEval:
        net = _f(net_f)
        meets = (net >= threshold if net is not None and threshold is not None
                 else None)
        selected = (sel == name)
        if selected and ntr is None:
            elig, reason = True, "selected"
        elif ntr and name in str(ntr):
            elig, reason = False, str(ntr)
        elif ntr:
            elig, reason = False, f"no_trade:{ntr}"
        elif sel is not None:
            elig, reason = False, "not_selected:lower_net_edge"
        else:
            elig, reason = False, "not_selected"
        vwap = _f(vwap_f)
        acq = (float(Decimal(str(vwap)) * Decimal(100))
               if vwap is not None else None)
        return SideEval(
            side=name, model_prob=prob,
            acq_price_cents=acq,
            depth_cc=_f(depth_f), fee_cents=_f(fee_f),
            exit_reserve_cents=_f(exit_r_f),
            model_risk_reserve_cents=_f(mrr_f),
            gross_edge_cents=_f(gross_f), net_edge_cents=net,
            edge_meets_threshold=meets,
            eligible=elig, eligibility_reason=reason,
            allocator_result=None if selected else "not_selected",
            submit_result=None if selected else "not_selected")

    rec = PairedSideEval(
        decision_id=str(getattr(decision, "decision_id", "") or ""),
        run_id=str(getattr(decision, "run_id", "") or ""),
        ticker=str(getattr(decision, "ticker", "") or ""),
        asset=str(getattr(decision, "asset", "") or ""),
        eval_ts_utc=time.time(),
        p_yes=p_yes, p_no=p_no, complement_sum_ok=comp_ok,
        yes=_side("yes", p_yes,
                  getattr(decision, "yes_entry_vwap", None),
                  getattr(decision, "yes_depth_cc", None),
                  getattr(decision, "entry_fee_yes", None),
                  getattr(decision, "exit_cost_reserve_yes", None),
                  getattr(decision, "model_risk_reserve_yes", None),
                  getattr(decision, "gross_edge_yes", None),
                  getattr(decision, "net_edge_yes", None)),
        no=_side("no", p_no,
                 getattr(decision, "no_entry_vwap", None),
                 getattr(decision, "no_depth_cc", None),
                 getattr(decision, "entry_fee_no", None),
                 getattr(decision, "exit_cost_reserve_no", None),
                 getattr(decision, "model_risk_reserve_no", None),
                 getattr(decision, "gross_edge_no", None),
                 getattr(decision, "net_edge_no", None)),
        selected_side=sel,
        selection_reason=str(getattr(decision, "selection_reason", "") or ""),
        best_side=getattr(decision, "best_side", None),
        no_trade_reason=ntr,
        ev_gate_allowed=getattr(decision, "ev_gate_allowed", None),
        edge_threshold_cents=threshold,
        book_sequence=book_sequence,
        quote_age_ms=quote_age_ms,
        policy_version=str(getattr(decision, "policy_version", "") or ""),
        asymmetries=sorted(DOCUMENTED_ASYMMETRIES.keys()),
    )
    _register(rec)
    return rec


def _register(rec: PairedSideEval) -> None:
    if not rec.decision_id:
        return
    _REGISTRY[rec.decision_id] = rec
    _REGISTRY.move_to_end(rec.decision_id)
    while len(_REGISTRY) > _REGISTRY_MAX:
        _REGISTRY.popitem(last=False)


def get(decision_id: str) -> Optional[PairedSideEval]:
    return _REGISTRY.get(decision_id)


def emit_paired_eval(rec: PairedSideEval) -> None:
    if not _ENABLED:
        return
    try:
        logger.info("[PAIRED-SIDE-EVAL] %s",
                    json.dumps(rec.to_dict(), sort_keys=True, default=str))
    except Exception:
        pass


def update_stage(decision_id: Optional[str], side: Optional[str], *,
                 allocator_result: Optional[str] = None,
                 submit_result: Optional[str] = None,
                 final_direction: Optional[str] = None,
                 router_handoff: Optional[Dict[str, Any]] = None) -> None:
    """Attach a downstream funnel result to the selected side's record."""
    if not _ENABLED or not decision_id or side not in ("yes", "no"):
        return
    rec = _REGISTRY.get(decision_id)
    if rec is None:
        return
    se = rec.side(side)
    if allocator_result is not None:
        se.allocator_result = allocator_result
    if submit_result is not None:
        se.submit_result = submit_result
    if final_direction is not None:
        se.final_direction = final_direction
    if router_handoff is not None:
        se.router_handoff = router_handoff
    try:
        logger.info("[PAIRED-SIDE-STAGE] %s", json.dumps({
            "decision_id": decision_id, "side": side,
            "allocator_result": se.allocator_result,
            "submit_result": se.submit_result,
            "final_direction": se.final_direction,
            "router_handoff": se.router_handoff,
        }, sort_keys=True, default=str))
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Side-swap support for the metamorphic test.  ``swap_decision`` returns a
# copy of the decision with every outcome-specific field exchanged
# (YES<->NO) and probabilities complemented.  Feeding the swapped decision
# through from_decision must produce a mirror-image PairedSideEval.
# ---------------------------------------------------------------------------

_SWAP_FIELDS = (
    ("p_yes_calibrated", "p_no_calibrated", "swap"),
    ("p_selected", "p_opposite", "swap"),
    ("yes_entry_vwap", "no_entry_vwap", "swap"),
    ("yes_depth_cc", "no_depth_cc", "swap"),
    ("fee_yes", "fee_no", "swap"),
    ("expected_exit_cost_yes", "expected_exit_cost_no", "swap"),
    ("yes_score", "no_score", "swap"),
    ("gross_edge_yes", "gross_edge_no", "swap"),
    ("net_edge_yes", "net_edge_no", "swap"),
    ("yes_net_edge", "no_net_edge", "swap"),
    ("entry_fee_yes", "entry_fee_no", "swap"),
    ("exit_cost_reserve_yes", "exit_cost_reserve_no", "swap"),
    ("model_risk_reserve_yes", "model_risk_reserve_no", "swap"),
    ("yes_edge_breakdown", "no_edge_breakdown", "swap"),
)


def swap_decision(decision: Any) -> Any:
    """Return a swapped copy: YES<->NO fields exchanged, probs complemented."""
    kw: Dict[str, Any] = {}
    one = Decimal("1")

    def _comp(v):
        return None if v is None else one - Decimal(str(v))

    for a, b, mode in _SWAP_FIELDS:
        va, vb = getattr(decision, a, None), getattr(decision, b, None)
        if mode == "complement":
            kw[a], kw[b] = _comp(vb), _comp(va)
        else:
            kw[a], kw[b] = vb, va
    sel = getattr(decision, "selected_outcome", None)
    kw["selected_outcome"] = ("no" if sel == "yes"
                             else "yes" if sel == "no" else sel)
    best = getattr(decision, "best_side", None)
    kw["best_side"] = ("no" if best == "yes"
                       else "yes" if best == "no" else best)
    spe = getattr(decision, "selected_side_pre_edge", None)
    kw["selected_side_pre_edge"] = ("no" if spe == "yes"
                                    else "yes" if spe == "no" else spe)
    # p_yes_raw is the anchor: complement it; uncertainty stays.
    raw = getattr(decision, "p_yes_raw", None)
    if raw is not None:
        kw["p_yes_raw"] = _comp(raw)
    try:
        return replace(decision, **kw)
    except TypeError:
        ns = type("SwappedDecision", (), {})()
        for f_ in getattr(decision, "__dataclass_fields__", {}):
            setattr(ns, f_, kw.get(f_, getattr(decision, f_, None)))
        return ns
