"""Phase-B shadow all-gates attribution auditor (2026-10-24).

Purpose
-------
Measure *why* candidates cannot execute — across ALL gates, not just the
first failure a short-circuiting pipeline reports.  Answers the policy
question directly: how many otherwise-admissible candidates are blocked
solely by a cell/cap/threshold restriction?

Design constraints (operator-approved scope)
--------------------------------------------
* Shadow-only.  This module never submits orders, consumes quotas, mutates
  counters, reserves capital, or advances rehabilitation state.  It runs
  offline over emitted ``decision_record`` telemetry (or in-process behind
  ``MERID_ALL_GATES_AUDIT``), so production behavior is identical whether
  it runs or not.
* No copied formulas.  Threshold variants are replayed through the same
  ``_decompose_dynamic_min_required_edge`` production function under a
  temporary env overlay — the single source of truth stays the source.
* Gate states are explicit: PASS / FAIL / NOT_EVALUABLE / ERROR.
* Sole-blocker attribution is strict: a gate is a sole blocker only when
  every other required gate is PASS and none are NOT_EVALUABLE / ERROR.
  Otherwise the attribution is ``indeterminate`` or ``multiple``.
* ``otherwise_admissible_at_evaluated_size`` is labelled, never claimed as
  a guaranteed fill — a gate removal that would change size/price needs a
  separate deterministic replay.

Accounting contract (matches EdgeBreakdown)
-------------------------------------------
    gross_edge = p_selected - executable_entry_price
    ev_net     = gross_edge - entry_fee - exit_cost_reserve
                 - model_risk_reserve - adverse_selection_reserve
                 - policy_giveback_reserve - impl_shortfall_reserve
                 ± edge_bias_correction

EV-sum identity (same-basis top-of-book asks, complementary probs):

    EV_Y + EV_N = 100 - (ask_Y + ask_N) - (C_Y + C_N)

where C_s is the total deduction inside that side's reported net EV.
``ev_sum_residual`` = observed - expected; nonzero means unexplained cost
or a non-complementing probability pair.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

AUDIT_VERSION = "phase_b_v1"

# Gate states
PASS = "PASS"
FAIL = "FAIL"
NOT_EVALUABLE = "NOT_EVALUABLE"
NOT_APPLICABLE = "NOT_APPLICABLE"
ERROR = "ERROR"

# Asset extraction from Kalshi ticker (KXBTC15M-... -> BTC)
_ASSET_PREFIX = {"KXBTC": "BTC", "KXETH": "ETH", "KXSOL": "SOL",
                 "KXXRP": "XRP", "KXDOGE": "DOGE"}


def asset_of(ticker: Optional[str]) -> str:
    t = (ticker or "").upper()
    for p, a in _ASSET_PREFIX.items():
        if t.startswith(p):
            return a
    return "UNKNOWN"


# ---------------------------------------------------------------------------
# Gate results
# ---------------------------------------------------------------------------

@dataclass
class GateResult:
    gate_id: str
    category: str           # data_integrity|venue_validity|economics|
                            # cell_policy|evidence|portfolio_risk|operational
    status: str             # PASS|FAIL|NOT_EVALUABLE|ERROR
    reason_code: str = ""
    observed_value: Optional[float] = None
    required_value: Optional[float] = None
    policy_id: str = ""
    dependencies: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _f(d: Dict[str, Any], *names: str) -> Optional[float]:
    for n in names:
        v = d.get(n)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return None


def _s(d: Dict[str, Any], *names: str) -> Optional[str]:
    for n in names:
        v = d.get(n)
        if v:
            return str(v)
    return None


# ---------------------------------------------------------------------------
# Per-side gate evaluation over an emitted decision_record
# ---------------------------------------------------------------------------

def _data_integrity_gate(rec: Dict[str, Any]) -> GateResult:
    """Book/catalog health at decision time — uses recorded fields only."""
    book = (_s(rec, "book_state", "book_status") or "").lower()
    data_state = (_s(rec, "data_state") or "").lower()
    quote_owner = (_s(rec, "quote_owner") or "").lower()
    if not book and not data_state and not quote_owner:
        return GateResult("data_integrity", "data_integrity", NOT_EVALUABLE,
                          reason_code="no_snapshot_fields")
    if "untrusted" in book or data_state in ("stale", "invalid", "degraded"):
        return GateResult("data_integrity", "data_integrity", FAIL,
                          reason_code=f"{book or data_state}",
                          dependencies=["book_state", "data_state"])
    return GateResult("data_integrity", "data_integrity", PASS,
                      reason_code=book or data_state or "fresh")


def _economics_gates(rec: Dict[str, Any], side: str) -> List[GateResult]:
    """Positive-EV and admission-hurdle gates from recorded decomposition."""
    ev = _f(rec, f"{side}_ev_net_cents", f"{side}_gate_ev_cents")
    req = _f(rec, f"{side}_effective_required_edge_cents",
             f"{side}_formula_required_edge_cents",
             f"{side}_route_required_edge_cents")
    out: List[GateResult] = []
    if ev is None:
        out.append(GateResult(f"{side}_positive_ev", "economics",
                              NOT_EVALUABLE, "ev_missing"))
        return out
    out.append(GateResult(
        f"{side}_positive_ev", "economics",
        PASS if ev > 0 else FAIL,
        reason_code="ev_net_gt_0" if ev > 0 else "ev_net_le_0",
        observed_value=ev, required_value=0.0))
    if req is None:
        out.append(GateResult(f"{side}_admission_margin", "economics",
                              NOT_EVALUABLE, "required_edge_missing",
                              dependencies=[f"{side}_positive_ev"]))
    else:
        margin = ev - req
        out.append(GateResult(
            f"{side}_admission_margin", "economics",
            PASS if margin >= 0 else FAIL,
            reason_code="ev_net_minus_required_edge",
            observed_value=margin, required_value=0.0,
            dependencies=[f"{side}_positive_ev"]))
    return out


def _evidence_gate(rec: Dict[str, Any], side: str) -> GateResult:
    """Decision-time evidence verdict — uses the recorded verdict dict, not
    today's artifact (the artifact has rolled since decision time)."""
    ev = rec.get(f"evidence_{side}")
    if not isinstance(ev, dict):
        return GateResult(f"{side}_evidence", "evidence", NOT_EVALUABLE,
                          "evidence_verdict_absent")
    allowed = ev.get("allowed")
    if allowed is None:
        return GateResult(f"{side}_evidence", "evidence", NOT_EVALUABLE,
                          "allowed_flag_absent",
                          policy_id=str(ev.get("code") or ""))
    return GateResult(
        f"{side}_evidence", "evidence",
        PASS if allowed else FAIL,
        reason_code=str(ev.get("code") or ""),
        policy_id=str(ev.get("admission_state") or ev.get("cell_key") or ""),
        dependencies=[f"{side}_admission_margin"])


def _moneyness_gate(rec: Dict[str, Any], side: str, asset: str,
                    price: Optional[float]) -> GateResult:
    """Per-asset side cap — pure replay of the env-defined band."""
    if price is None:
        return GateResult(f"{side}_moneyness_cap", "cell_policy",
                          NOT_EVALUABLE, "price_missing")
    cap_env = f"MERID_MONEYNESS_MAX_ENTRY_PRICE_CENTS_{asset}_{side.upper()}"
    cap = _f({"v": os.environ.get(cap_env)}, "v")
    if cap is None and side == "no":
        cap = _f({"v": os.environ.get(
            "MERID_MONEYNESS_MAX_ENTRY_PRICE_CENTS_NO")}, "v") or 50.0
    if cap is None:
        # No configured cap for this side: non-applicable, not a failure
        # and not missing data — excluded from required-gate attribution.
        return GateResult(f"{side}_moneyness_cap", "cell_policy",
                          NOT_APPLICABLE, "no_cap_configured")
    return GateResult(f"{side}_moneyness_cap", "cell_policy",
                      PASS if price <= cap else FAIL,
                      reason_code="within_cap" if price <= cap else "above_cap",
                      observed_value=price, required_value=cap,
                      policy_id=cap_env)


def _cell_gate(rec: Dict[str, Any], side: str) -> GateResult:
    """Threshold-cell / provisional override + admission-cap verdict."""
    cell_id = _s(rec, f"{side}_thr_cell_id")
    cell_min = _f(rec, f"{side}_thr_cell_min_ev_cents")
    cap_hit = rec.get(f"{side}_thr_cell_cap_exhausted")
    if cap_hit:
        return GateResult(f"{side}_cell_policy", "cell_policy", FAIL,
                          "cell_cap_exhausted", policy_id=str(cell_id))
    if cell_id is not None or cell_min is not None:
        return GateResult(f"{side}_cell_policy", "cell_policy", PASS,
                          "cell_threshold_applied", policy_id=str(cell_id),
                          required_value=cell_min)
    return GateResult(f"{side}_cell_policy", "cell_policy", PASS,
                      "no_cell_matched")


# ---------------------------------------------------------------------------
# Threshold decomposition exposure (replay through production function)
# ---------------------------------------------------------------------------

def threshold_components(asset: str, side: str, price_cents: int,
                         tte_s: Optional[float],
                         env_overlay: Optional[Dict[str, str]] = None,
                         ) -> Dict[str, Any]:
    """Decompose the production required-edge for a side at a held price.

    Replays ``_decompose_dynamic_min_required_edge`` — the single source of
    truth — under an optional temporary env overlay (policy variants).
    """
    from merid.prediction.trade_decision import (
        _decompose_dynamic_min_required_edge, resolve_threshold_cell)
    overlay = env_overlay or {}
    saved: Dict[str, Optional[str]] = {}
    try:
        for k, v in overlay.items():
            saved[k] = os.environ.get(k)
            os.environ[k] = v
        d = _decompose_dynamic_min_required_edge(
            asset=asset, price_cents=int(price_cents), side=side,
            yes_bid_cents=0.0, yes_ask_cents=0.0,
            no_bid_cents=0.0, no_ask_cents=0.0,
            floor_min_required_edge=0.02,
            seconds_to_expiry=tte_s)
        cell = resolve_threshold_cell(asset, side, int(price_cents), tte_s)
        return {
            "selected_price_cents": int(price_cents),
            "convexity_k": d.convexity_k,
            "convexity_term_cents": d.convexity * 100.0,
            "base_threshold_cents": d.base_floor * 100.0,
            "global_floor_cents": d.global_floor * 100.0,
            "asset_base_cents": d.asset_base * 100.0,
            "flb_premium_cents": d.flb_premium * 100.0,
            "band_relief_cents": d.band_relief * 100.0,
            "formula_total_cents": (d.formula_total or 0.0) * 100.0,
            "floor_cents": 0.0,
            "cap_cents": 15.0,
            "clamped_floor": d.clamped_floor,
            "clamped_ceiling": d.clamped_ceiling,
            "cell_override_id": d.cell_id,
            "cell_override_value_cents": d.cell_min_ev_cents,
            "cell_block_reason": d.cell_block_reason,
            "cell_registered": cell is not None,
            "provisional_cell_id": d.provisional_cell_id,
            "final_required_edge_cents": d.total * 100.0,
            "override_operation": (
                "cell_replaces_formula" if d.cell_id else
                "provisional_replaces_formula" if d.provisional_cell_id else
                "formula"),
            "threshold_policy_version": AUDIT_VERSION,
        }
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


# Named shadow variants (operator-scoped).  Keys are env overlays replayed
# through the production function; NONE change live behavior.
POLICY_VARIANTS: Dict[str, Dict[str, str]] = {
    "SYMMETRIC_CONVEXITY_K": {
        # Uniform 0.02 coefficient — removes the sub-50c doubling.
        "MERID_EDGE_CONVEXITY_K_LO": "0.02",
    },
    "SYMMETRIC_RELIEF_ELIGIBILITY": {
        # Band relief applies at all held prices, not only >=50c.
        "MERID_EDGE_MID_BAND_LO_CENTS": "1",
    },
}
# REMOVE_SELECTED_CELL_CAP / REMOVE_SELECTED_CELL_BLOCK are evaluated
# structurally: the threshold a registered cell *would* impose when its
# lane admission is ignored (min(cell.min_net_ev_cents, 0.15)).


# ---------------------------------------------------------------------------
# Accounting decomposition + EV-sum identity
# ---------------------------------------------------------------------------

def accounting_block(rec: Dict[str, Any]) -> Dict[str, Any]:
    """Both-side cost decomposition + the EV-sum identity residual.

    EV_Y + EV_N = 100 - (ask_Y + ask_N) - (C_Y + C_N)   [cents]
    residual = observed_sum - expected_sum
    """
    out: Dict[str, Any] = {}
    ev_y = _f(rec, "yes_ev_net_cents", "yes_gate_ev_cents")
    ev_n = _f(rec, "no_ev_net_cents", "no_gate_ev_cents")
    ask_y = _f(rec, "yes_ask_cents", "yes_ask")
    ask_n = _f(rec, "no_ask_cents", "no_ask")
    q_yes = _f(rec, "p_yes_calibrated")
    comps: Dict[str, Dict[str, Optional[float]]] = {}
    for side in ("yes", "no"):
        comps[side] = {
            "q_side": _f(rec, f"p_{side}_calibrated"),
            "best_ask_cents": _f(rec, f"{side}_ask_cents", f"{side}_ask"),
            "entry_fee_cents": _f(rec, f"{side}_fee_reserve_cents"),
            "impact_cents": _f(rec, f"{side}_impact_reserve_cents"),
            "model_uncertainty_cents":
                _f(rec, f"{side}_model_uncertainty_reserve_cents"),
            "adverse_selection_cents":
                _f(rec, f"{side}_adverse_selection_reserve_cents"),
            "book_source_cents": _f(rec, "book_source_reserve_cents"),
            "impl_shortfall_cents":
                _f(rec, f"{side}_impl_shortfall_cents",
                   f"{side}_impl_shortfall_reserve_cents"),
            "ev_net_cents": _f(rec, f"{side}_ev_net_cents",
                               f"{side}_gate_ev_cents"),
            "required_edge_cents": _f(
                rec, f"{side}_effective_required_edge_cents"),
        }
    out["per_side"] = comps
    out["q_yes"] = q_yes
    ev_basis = "unavailable"
    if None not in (ev_y, ev_n, ask_y, ask_n):
        c_y = sum(v for k, v in comps["yes"].items()
                  if k.endswith("_cents") and k not in
                  ("best_ask_cents", "ev_net_cents", "required_edge_cents")
                  and v is not None)
        c_n = sum(v for k, v in comps["no"].items()
                  if k.endswith("_cents") and k not in
                  ("best_ask_cents", "ev_net_cents", "required_edge_cents")
                  and v is not None)
        # Generalized identity (2026-10-24 reviewer correction): EV sides
        # are computed on INDEPENDENTLY corrected probabilities — the
        # streaming bound caps each side separately, so q_y + q_n != 1 in
        # general.  expected = 100*(qY+qN) - (aY+aN) - (CY+CN); when the
        # selected probabilities complement this reduces to the spread
        # form.  Prefer the EV-used p_selected over the logged calibrated
        # probability; absent that field the identity is marked as using
        # the calibrated fallback (which does complement).
        qy_ev = _f(rec, "yes_p_selected")
        qn_ev = _f(rec, "no_p_selected")
        ev_basis = "p_selected" if (qy_ev is not None and qn_ev is not None) \
            else "calibrated_complement_fallback"
        if qy_ev is None:
            qy_ev = _f(rec, "p_yes_calibrated")
        if qn_ev is None:
            qn_ev = _f(rec, "p_no_calibrated")
        price_excess = (ask_y + ask_n) - 100.0   # 'spread' iff same-basis asks
        if None not in (qy_ev, qn_ev):
            q_sum = qy_ev + qn_ev
            expected = 100.0 * (q_sum - 1.0) - price_excess - c_y - c_n
        else:
            q_sum = None
            expected = -price_excess - c_y - c_n
        observed = ev_y + ev_n
        # Probability semantics: bound-vs-point-estimate provenance.
        # streaming_cal bound is tighten-only; p_selected below the logged
        # calibrated estimate marks a conservative adjustment, not a fee.
        sems = {}
        for side, qsel in (("yes", qy_ev), ("no", qn_ev)):
            qcal = _f(rec, f"p_{side}_calibrated")
            if ev_basis == "calibrated_complement_fallback":
                sems[side] = "UNKNOWN"
            elif _f(rec, "streaming_cal_applied") or (
                qcal is not None and qsel is not None
                and qsel < qcal - 1e-9
            ):
                sems[side] = "CONSERVATIVE_BOUND"
            else:
                sems[side] = "POINT_ESTIMATE"
        semantics = (
            sems["yes"] if sems["yes"] == sems["no"]
            else "MIXED"
            if "UNKNOWN" not in sems.values()
            else "UNKNOWN")
        out.update({
            "observed_ev_sum_cents": observed,
            "expected_ev_sum_cents": expected,
            "ev_sum_residual_cents": (
                observed - expected if expected is not None else None),
            "entry_price_excess_cents": price_excess,
            "combined_costs_cents": c_y + c_n,
            "q_selected_sum": q_sum,
            "selected_probability_gap": (
                1.0 - q_sum if q_sum is not None else None),
            "ev_probability_basis": ev_basis,
            "ev_probability_semantics": semantics,
            "ev_probability_semantics_by_side": sems,
            "price_basis": "top_of_book_ask",
        })
    else:
        out["ev_sum_residual_cents"] = None
        out["price_basis"] = "unavailable"
        out["ev_probability_semantics"] = "UNKNOWN"
    # Record class for reconciliation reporting: only exact_selected
    # records can definitively reconcile the bounded-q path.
    if ev_basis == "p_selected":
        out["record_class"] = "exact_selected_probability"
    elif ev_y is not None and ev_n is not None:
        out["record_class"] = "fallback_estimate"
    else:
        out["record_class"] = "insufficient_telemetry"
    # Probability-bound waterfall per side: separates tightening inside
    # probability construction from downstream economic/policy blocks.
    waterfall: Dict[str, Any] = {}
    for side in ("yes", "no"):
        q_sel = _f(rec, f"{side}_p_selected")
        q_pt = _f(rec, f"fe_final_p_{side}", f"p_{side}_calibrated")
        ask = _f(rec, f"{side}_ask_cents", f"{side}_ask")
        ev = _f(rec, f"{side}_ev_net_cents", f"{side}_gate_ev_cents")
        req = _f(rec, f"{side}_effective_required_edge_cents",
                 f"{side}_formula_required_edge_cents")
        wf: Dict[str, Any] = {}
        if None not in (q_pt, ask):
            gross_pt = q_pt * 100.0 - ask
            wf["point_est_gross_ev_cents"] = gross_pt
            # costs inside reported ev_net = gross_sel - ev_net; the
            # point-estimate net applies the same cost stack.
            if ev is not None and q_sel is not None:
                gross_sel = q_sel * 100.0 - ask
                cost_stack = gross_sel - ev
                wf["point_est_net_ev_cents"] = gross_pt - cost_stack
                wf["bound_net_ev_cents"] = ev
                wf["probability_tightening_cents"] = (
                    100.0 * (q_pt - q_sel))
            else:
                wf["point_est_net_ev_cents"] = None
                wf["bound_net_ev_cents"] = ev
                wf["probability_tightening_cents"] = None
        if ev is not None and req is not None:
            wf["required_edge_cents"] = req
            wf["admission_margin_cents"] = ev - req
        waterfall[side] = wf
    out["waterfall"] = waterfall
    return out


# ---------------------------------------------------------------------------
# Attribution
# ---------------------------------------------------------------------------

def attribute(gates: List[GateResult]) -> Dict[str, Any]:
    """Blocker attribution over a side's full gate vector.

    NOT_APPLICABLE gates are excluded from required-gate accounting.  A
    single FAIL among resolved gates earns 'otherwise_admissible'; the
    same single FAIL alongside NOT_EVALUABLE/ERROR is reported as a
    'candidate_blocker' pattern — never claimed as a proven sole blocker.
    """
    required = [g for g in gates if g.status != NOT_APPLICABLE]
    fails = [g for g in required if g.status == FAIL]
    not_eval = [g for g in required if g.status in (NOT_EVALUABLE, ERROR)]
    first_reject = fails[0].gate_id if fails else None
    fams = {g.category for g in fails}
    if len(fails) == 1 and not not_eval:
        sole_gate = fails[0].gate_id
        sole_family = fails[0].category
        label = "otherwise_admissible_at_evaluated_size"
    elif len(fails) == 1:
        sole_gate = fails[0].gate_id
        sole_family = fails[0].category
        label = "candidate_blocker_indeterminate"
    elif not fails and not_eval:
        sole_gate = sole_family = None
        label = "indeterminate_no_result"
    elif not fails:
        sole_gate = sole_family = None
        label = "all_pass"
    else:
        sole_gate = None
        sole_family = list(fams)[0] if len(fams) == 1 else None
        label = ("single_family_multiple_gates" if len(fams) == 1
                 else "multiple_blockers")
    return {
        "first_reject": first_reject,
        "all_failures": [g.gate_id for g in fails],
        "not_evaluable": [g.gate_id for g in not_eval],
        "sole_blocking_gate": sole_gate,
        "sole_blocking_policy_family": sole_family,
        "attribution": label,
        "n_failed": len(fails),
    }


# ---------------------------------------------------------------------------
# Record-level evaluation
# ---------------------------------------------------------------------------

def evaluate_record(rec: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Full shadow gate-vector + accounting for one decision_record."""
    if rec.get("type") != "decision_record":
        return None
    ticker = rec.get("ticker") or ""
    asset = asset_of(ticker)
    acct = accounting_block(rec)
    sides: Dict[str, Any] = {}
    for side in ("yes", "no"):
        ask = _f(rec, f"{side}_ask_cents", f"{side}_ask")
        gates = [_data_integrity_gate(rec)]
        gates += _economics_gates(rec, side)
        gates.append(_evidence_gate(rec, side))
        gates.append(_moneyness_gate(rec, side, asset, ask))
        gates.append(_cell_gate(rec, side))
        # portfolio/venue gates are only evaluable post-emission; the
        # decision record at signal stage has no router state.
        gates.append(GateResult(f"{side}_portfolio_risk", "portfolio_risk",
                                NOT_EVALUABLE, "pre_emission_record"))
        gates.append(GateResult(f"{side}_venue_validity", "venue_validity",
                                NOT_EVALUABLE, "pre_emission_record"))
        attr = attribute(gates)
        sides[side] = {
            "gates": [g.to_dict() for g in gates],
            "attribution": attr,
        }
        # Waterfall classification on EVERY record — not only positive-EV
        # candidates.  Separates "forecast didn't support entry" from
        # "probability tightening removed the estimated opportunity".
        wf = acct.get("waterfall", {}).get(side, {})
        pt_net = wf.get("point_est_net_ev_cents")
        bnd_net = wf.get("bound_net_ev_cents")
        marg = wf.get("admission_margin_cents")
        if pt_net is None or bnd_net is None:
            wc = "insufficient_telemetry"
        elif pt_net <= 0 and bnd_net <= 0:
            wc = "point_estimate_not_supportive"
        elif pt_net > 0 and bnd_net <= 0:
            wc = "probability_tightening_removed_opportunity"
        elif marg is not None and bnd_net > 0 and marg < 0:
            wc = "hurdle_removed_bound_positive"
        else:
            wc = "economics_survived"
        sides[side]["waterfall_class"] = wc
        # threshold decomposition exposure (production replay, no overlay)
        px = ask if ask is not None else _f(rec, f"{side}_thr_price_cents")
        tte = _f(rec, "tte_s", "seconds_to_expiry", "tte_seconds")
        if px is not None:
            try:
                sides[side]["threshold"] = threshold_components(
                    asset, side, int(round(px)), tte)
                for vname, overlay in POLICY_VARIANTS.items():
                    sides[side].setdefault("variants", {})[vname] = \
                        threshold_components(asset, side, int(round(px)),
                                             tte, overlay)
            except Exception as exc:  # ERROR never changes production state
                sides[side]["threshold_error"] = f"{type(exc).__name__}:{exc}"
    return {
        "type": "all_gates_audit",
        "audit_version": AUDIT_VERSION,
        "ticker": ticker,
        "asset": asset,
        "ts": rec.get("ts") or rec.get("timestamp"),
        "config_hash": rec.get("config_hash"),
        "run_id": rec.get("run_id"),
        "terminal_code": rec.get("terminal_code"),
        "production_first_reject": rec.get("rejection_stage"),
        "candidate_generated": rec.get("candidate_generated"),
        "accounting": acct,
        "sides": sides,
    }


def evaluate_records(records) -> "AuditSummary":
    """Evaluate a stream of decision_records -> AuditSummary."""
    summ = AuditSummary()
    for rec in records:
        try:
            audit = evaluate_record(rec)
        except Exception:
            continue
        if audit is None:
            continue
        summ.add(audit)
    return summ


# ---------------------------------------------------------------------------
# Ten-lane funnel
# ---------------------------------------------------------------------------

class AuditSummary:
    """Counts per asset x side lane: snapshot + distinct-market + blocker."""

    def __init__(self) -> None:
        self.lanes: Dict[str, Dict[str, Any]] = {}
        self.evaluated = 0
        self.side_evals = 0
        self.unscorable = 0
        self.record_classes: Dict[str, int] = {}
        self.waterfall_classes: Dict[str, int] = {}

    def _lane(self, asset: str, side: str) -> Dict[str, Any]:
        key = f"{asset}_{side.upper()}"
        if key not in self.lanes:
            self.lanes[key] = {
                "snapshots": 0, "markets": set(),
                "economics_positive": 0, "economics_admitted": 0,
                "evidence_pass": 0, "cell_policy_pass": 0,
                "moneyness_pass": 0, "data_integrity_pass": 0,
                "shadow_admissible": 0,
                "first_reject": {}, "all_failure": {},
                "sole_blocking_gate": {},
                "sole_blocking_policy_family": {},
                "indeterminate": 0,
            }
        return self.lanes[key]

    def add(self, audit: Dict[str, Any]) -> None:
        self.evaluated += 1
        rc = audit.get("accounting", {}).get("record_class", "?")
        self.record_classes[rc] = self.record_classes.get(rc, 0) + 1
        for side, sdata in audit["sides"].items():
            self.side_evals += 1
            wc = sdata.get("waterfall_class")
            if wc:
                self.waterfall_classes[wc] = \
                    self.waterfall_classes.get(wc, 0) + 1
            lane = self._lane(audit["asset"], side)
            lane["snapshots"] += 1
            if audit["ticker"]:
                lane["markets"].add(audit["ticker"])
            gates = {g["gate_id"]: g for g in sdata["gates"]}
            di = gates.get("data_integrity")
            if di and di["status"] == PASS:
                lane["data_integrity_pass"] += 1
            pe = gates.get(f"{side}_positive_ev")
            if pe and pe["status"] == PASS:
                lane["economics_positive"] += 1
            am = gates.get(f"{side}_admission_margin")
            if am and am["status"] == PASS:
                lane["economics_admitted"] += 1
            eg = gates.get(f"{side}_evidence")
            if eg and eg["status"] == PASS:
                lane["evidence_pass"] += 1
            cg = gates.get(f"{side}_cell_policy")
            if cg and cg["status"] == PASS:
                lane["cell_policy_pass"] += 1
            mg = gates.get(f"{side}_moneyness_cap")
            if mg and mg["status"] == PASS:
                lane["moneyness_pass"] += 1
            attr = sdata["attribution"]
            if attr["attribution"] == "all_pass":
                lane["shadow_admissible"] += 1
            if "indeterminate" in attr["attribution"]:
                lane["indeterminate"] += 1
            if attr["first_reject"]:
                lane["first_reject"][attr["first_reject"]] = \
                    lane["first_reject"].get(attr["first_reject"], 0) + 1
            for g in attr["all_failures"]:
                lane["all_failure"][g] = lane["all_failure"].get(g, 0) + 1
            if attr["sole_blocking_gate"]:
                # Reported as candidate patterns when the label is
                # indeterminate — definitive sole blockers only when all
                # required gates resolved.
                lane["sole_blocking_gate"][attr["sole_blocking_gate"]] = \
                    lane["sole_blocking_gate"].get(
                        attr["sole_blocking_gate"], 0) + 1
            if attr["sole_blocking_policy_family"]:
                fam = attr["sole_blocking_policy_family"]
                lane["sole_blocking_policy_family"][fam] = \
                    lane["sole_blocking_policy_family"].get(fam, 0) + 1

    def report(self) -> str:
        # Spec: all ten lanes appear, including zero-observation lanes.
        for asset in ("BTC", "ETH", "SOL", "XRP", "DOGE"):
            for side in ("YES", "NO"):
                self._lane(asset, side.lower())
        lines = [
            f"all-gates audit: {self.evaluated} records evaluated",
            f"  input records            {self.evaluated}",
            f"  side evaluations         {self.side_evals}",
            f"  record classes           {self.record_classes}",
            f"  waterfall classes        {self.waterfall_classes}",
            "",
        ]
        hdr = (f"{'lane':12s} {'snap':>5s} {'mkts':>4s} {'data_ok':>7s} "
               f"{'ev>0':>5s} {'adm_pass':>8s} {'evidence':>8s} {'cell':>4s} "
               f"{'moneyness':>9s} {'all_pass':>8s} {'indeterm':>8s}")
        lines.append(hdr)
        for key in sorted(self.lanes):
            l = self.lanes[key]
            lines.append(
                f"{key:12s} {l['snapshots']:5d} {len(l['markets']):4d} "
                f"{l['data_integrity_pass']:7d} {l['economics_positive']:5d} "
                f"{l['economics_admitted']:8d} {l['evidence_pass']:8d} "
                f"{l['cell_policy_pass']:4d} {l['moneyness_pass']:9d} "
                f"{l['shadow_admissible']:8d} {l['indeterminate']:8d}")
        lines.append("")
        lines.append("candidate blocker patterns (incl. indeterminate):")
        agg: Dict[str, int] = {}
        famagg: Dict[str, int] = {}
        for l in self.lanes.values():
            for g, n in l["sole_blocking_gate"].items():
                agg[g] = agg.get(g, 0) + n
            for f_, n in l["sole_blocking_policy_family"].items():
                famagg[f_] = famagg.get(f_, 0) + n
        for g, n in sorted(agg.items(), key=lambda kv: -kv[1]):
            lines.append(f"  {g:40s} {n}")
        lines.append("candidate blocking policy families:")
        for f_, n in sorted(famagg.items(), key=lambda kv: -kv[1]):
            lines.append(f"  {f_:40s} {n}")
        return "\n".join(lines)


def load_decision_records(path: str, limit: int = 0):
    """Stream decision_records from a decision_telemetry JSONL file."""
    n = 0
    with open(path, "r", errors="replace") as f:
        for line in f:
            if '"decision_record"' not in line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get("type") != "decision_record":
                continue
            yield d
            n += 1
            if limit and n >= limit:
                return
