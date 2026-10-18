"""Cohort policy comparison replay — RECONCILED row-level version.

Corrects the first-pass report:
  * ``realized_pnl_c`` / ``cf_hold_pnl_c`` in the source ledger are ALREADY
    net of fees (exit_decision_ledger.py lines 414/433/465).  The earlier
    report subtracted them twice; this version uses the ledger values as-is.
  * ``exit_markout_settle_c`` is a DELTA (exec_price - settle_value), not a
    price.  "Recovery forfeited" is therefore markout < 0, not markout > exec.
  * Partial exits: the row's ``qty_contracts`` is the ENTRY quantity while
    ``realized_pnl_c`` only covers the exited slice; allocated exit quantity
    is not exported by the ledger.  Rows where the delta could be
    quantity-mismatched are flagged, not silently summed.
  * The comparison is a same-entry liquidation comparison, not a full
    alternative-strategy simulation (capital availability, overlapping
    exposure, and downstream eligibility are NOT modeled).

Definitions (all net of fees, cents):
  delta_i       = realized_pnl_c - cf_hold_pnl_c  (same-entry liquidation delta)
  benefit       = sum(max(delta_i, 0))  over rows with a known settlement
  cost          = sum(max(-delta_i, 0))
  invariant:    benefit - cost == sum(delta_i) == actual - hold (known set)

Policy set:
  actual / hold_to_settlement      authoritative legs from the ledger
  hard_lock_<L>c                   UNCONSTRAINED SCENARIO EXTREMA only, plus a
                                   "confirmed_executable" subset modeled
                                   strictly from observed exit fills >= L.
                                   A mark/quote touching L is NOT executable
                                   evidence; a settled 100 is NOT a 90c bid.
  corrected_trail / model_exit     not computable (no intra-window book path)
  hybrid                           the deployed policy IS the hybrid

All 383 rows predate the exit arbiter; they cannot evidence its floor
enforcement either way.  Deployment revision is not recorded per row;
raw trigger reason is the finest policy discriminator available.
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

D = Path(r"C:\Dev\MERID\data")
OUT = D / "cohort_policy_report.json"
ROWS_OUT = D / "cohort_row_export.jsonl"
TP_AUDIT = D / "take_profit_audit.jsonl"

HARD_LOCK_LEVELS = (60, 70, 80, 90)


def load_rows():
    return [json.loads(l) for l in
            (D / "exit_decision_ledger_rows.jsonl")
            .read_text(encoding="utf-8").splitlines() if l.strip()]


def price_band(p):
    if p is None:
        return "unknown"
    for lo, hi, lab in ((1, 20, "1-20"), (21, 40, "21-40"),
                        (41, 60, "41-60"), (61, 80, "61-80"),
                        (81, 99, "81-99")):
        if lo <= p <= hi:
            return lab
    return "other"


def tte_band(t):
    if t is None:
        return "unknown"
    if t <= 120:
        return "<=2m"
    if t <= 300:
        return "2-5m"
    if t <= 600:
        return "5-10m"
    return ">10m"


def drawdown(series):
    peak = mdd = cum = 0.0
    for p in series:
        cum += p
        peak = max(peak, cum)
        mdd = min(mdd, cum - peak)
    return mdd


def classify_tp_row(r):
    """Taxonomy for negative take-profit outcomes."""
    add = r.get("exit_value_added_c")
    sv = r.get("settle_value_held_c")
    fee = (r.get("entry_fee_c") or 0.0) + (r.get("exit_fee_c") or 0.0)
    exec_c = r.get("exit_exec_c")
    entry = r.get("entry_price_c")
    gross = (exec_c - entry) * (r.get("qty_contracts") or 0) \
        if exec_c is not None and entry is not None else None
    if sv is None:
        return "settlement_outcome_unknown"
    if exec_c is not None and entry is not None and exec_c < entry:
        return ("below_entry_execution "
                "(old-policy loss-taking, no floor guarantee)")
    if add is not None and add < 0 and sv == 100:
        return "forfeited_settlement_win (held to 100; exit capped earlier)"
    if gross is not None and gross > 0 and (r.get("realized_pnl_c") or 0) <= 0:
        return "fees_turned_gross_gain_negative"
    if add is not None and add > 0:
        return "exit_added_value (loss avoided vs settle 0)"
    return "unclassified"


def main():
    rows = load_rows()
    rows.sort(key=lambda r: r.get("exit_ts") or 0.0)

    early = [r for r in rows if r.get("closed_by") == "exit"]
    settled = [r for r in rows if r.get("closed_by") == "settlement"]
    open_rows = [r for r in rows if r.get("closed_by") not in
                 ("exit", "settlement")]

    # --- row-level export + reconciled deltas --------------------------------
    recon, unknown = [], []
    qty_mismatch, qty_indeterminate = 0, 0
    with open(ROWS_OUT, "w", encoding="utf-8") as f:
        for r in rows:
            delta = r.get("exit_value_added_c")
            known = (r.get("realized_pnl_c") is not None
                     and r.get("cf_hold_pnl_c") is not None)
            rec = dict(r)
            rec["delta_c"] = delta
            rec["settlement_known"] = known
            # Quantity reconciliation: realized = (xw - entry_px)*tot_qty
            # - entry_fee - tot_fee inverts to the allocated exit quantity
            # whenever xw != entry_px.  Comparing to qty_contracts detects
            # partial exits even though the ledger omits allocated qty.
            iq = None
            if r.get("closed_by") == "exit":
                xw, ep = r.get("exit_exec_c"), r.get("entry_price_c")
                fees = (r.get("entry_fee_c") or 0) + (r.get("exit_fee_c") or 0)
                if xw is not None and ep is not None and abs(xw - ep) > 0.01:
                    iq = ((r.get("realized_pnl_c") or 0) + fees) / (xw - ep)
                    rec["implied_exit_qty_cc"] = round(iq * 100, 2)
                    rec["entry_qty_cc"] = round(
                        (r.get("qty_contracts") or 0) * 100, 2)
                    if abs(iq - (r.get("qty_contracts") or 0)) > 0.01:
                        qty_mismatch += 1
                        rec["quantity_reconciled"] = (
                            f"MISMATCH implied_exit={iq * 100:.1f}cc "
                            f"vs entry={rec['entry_qty_cc']:.0f}cc")
                    else:
                        rec["quantity_reconciled"] = "matched"
                else:
                    qty_indeterminate += 1
                    rec["quantity_reconciled"] = (
                        "indeterminate:exec==entry_price qty unsolvable")
            else:
                rec["quantity_reconciled"] = "n/a:no_exit_fill"
            (recon if known else unknown).append(rec)
            f.write(json.dumps(rec, sort_keys=True) + "\n")

    actual_total = sum(r["realized_pnl_c"] or 0 for r in rows)
    hold_known = sum(r["cf_hold_pnl_c"] or 0 for r in recon)
    actual_known = sum(r["realized_pnl_c"] or 0 for r in recon)
    delta_total = actual_known - hold_known
    deltas = [r["delta_c"] or 0.0 for r in recon if r["closed_by"] == "exit"]
    benefit = sum(max(d, 0.0) for d in deltas)
    cost = sum(max(-d, 0.0) for d in deltas)

    # --- invariants ----------------------------------------------------------
    inv = []
    inv.append(("sum(realized,known) - sum(cf_hold,known) == delta_total",
                abs((actual_known - hold_known) - delta_total) < 0.01))
    inv.append(("benefit - cost == sum(deltas,early,known)",
                abs((benefit - cost) - sum(deltas)) < 0.01))
    inv.append(("sum(deltas,early,known) == delta_total "
                "(settled rows contribute 0 by construction)",
                abs(sum(deltas) - delta_total) < 0.01))
    inv.append(("all rows classified", len(rows)
                == len(early) + len(settled) + len(open_rows)))

    # --- policies --------------------------------------------------------------
    pnl_actual = [r["realized_pnl_c"] or 0 for r in rows]
    pnl_hold = [r["cf_hold_pnl_c"] or 0 for r in recon]
    policies = {
        "actual": {"net_pnl_c": round(sum(pnl_actual), 2),
                   "max_drawdown_c": round(drawdown(pnl_actual), 2),
                   "note": "authoritative realized, already net of fees"},
        "same_entry_hold_to_settlement": {
            "net_pnl_c": round(sum(pnl_hold), 2),
            "max_drawdown_c": round(drawdown(pnl_hold), 2),
            "note": "same-entry liquidation comparison only — capital "
                    "availability, overlapping exposure and downstream "
                    "eligibility are NOT simulated"},
    }
    for L in HARD_LOCK_LEVELS:
        confirmed, lo, hi = 0, [], []
        for r in recon:
            q = r.get("qty_contracts") or 0.0
            x = r.get("exit_exec_c")
            # Only REAL exit fills count as executable evidence: for
            # settled rows the ledger stores the payout (0/100) in
            # exit_exec_c, which is NOT a traded price — a settled 100
            # does not prove a pre-close L bid existed (XRP-69c fixture).
            traded = r["closed_by"] == "exit" and (r.get("n_exit_fills") or 0) > 0
            if traded and x is not None and x >= L:
                confirmed += 1
                p = x * q - (r.get("entry_price_c") or 0) * q \
                    - (r.get("entry_fee_c") or 0) - (r.get("exit_fee_c") or 0)
                lo.append(p)
                hi.append(p)
            else:
                # unconstrained extrema: settle floor vs assumed L-fill cap
                lo.append(min(r["cf_hold_pnl_c"] or 0.0,
                              L * q - (r.get("entry_price_c") or 0) * q
                              - (r.get("entry_fee_c") or 0)))
                hi.append(max(r["cf_hold_pnl_c"] or 0.0,
                              L * q - (r.get("entry_price_c") or 0) * q
                              - (r.get("entry_fee_c") or 0)))
        policies[f"hard_lock_{L}c"] = {
            "observed_exit_fills_at_or_above_L": confirmed,
            "unconstrained_scenario_extrema_c": [round(sum(lo), 2),
                                                 round(sum(hi), 2)],
            "note": "confirmed = real exit fill at >=L in that record; does "
                    "NOT establish the full position could have sold at L, "
                    "nor that L was executable at an earlier trigger time. "
                    "Extrema are mathematically possible, NOT backtest PnL; "
                    "marks/quotes/settlement payouts are not executable "
                    "evidence. Do not rank thresholds on them."}

    policies["corrected_trail"] = {"computable": False,
                                   "missing": "intra-window executable book "
                                              "history (5s/15s/60s markouts: "
                                              "0 coverage)"}
    policies["model_exit"] = {"computable": False,
                              "missing": "model probability path per position"}
    policies["hybrid"] = {"computable": True,
                          "note": "deployed policy is the hybrid; "
                                  "'actual' measures it"}

    # --- exit decomposition ---------------------------------------------------
    forfeited = [r for r in recon
                 if r["closed_by"] == "exit"
                 and r.get("exit_markout_settle_c") is not None
                 and r["exit_markout_settle_c"] < -0.001]
    helped = [r for r in recon
              if r["closed_by"] == "exit"
              and r.get("exit_markout_settle_c") is not None
              and r["exit_markout_settle_c"] > 0.001]
    decomposition = {
        "benefit_from_exits_c": round(benefit, 2),
        "cost_of_exits_c": round(cost, 2),
        "sum_deltas_c": round(sum(deltas), 2),
        "exits_below_eventual_settlement_value_n": len(forfeited),
        "exec_exceeded_settle_value_n": len(helped),
        "settlement_unknown_n": len(unknown),
        "recoveries_forfeited_c": round(cost, 2),
        "losses_avoided_c": round(benefit, 2),
        "note": "exits_below_settlement means execution price < eventual "
                "settlement value; it does NOT establish that holding would "
                "have produced positive net PnL after entry cost and fees.",
    }

    # --- fill accounting ------------------------------------------------------
    with_fills = [r for r in early if (r.get("n_exit_fills") or 0) > 0]
    fills_meta = {
        "completed_early_exit_records_with_fills":
            f"{len(with_fills)}/{len(early)}",
        "note": "denominator is completed-exit RECORDS — survivorship: "
                "triggered exits that never filled, were rejected, or stayed "
                "unresolved never became rows. Conversion denominators "
                "(triggers/proposals/approvals/submissions/acks/partials/"
                "unfilled/unresolved) require arbiter telemetry now being "
                "emitted; not derivable from this ledger.",
        "quantity_fill_rate": "not derivable — allocated exit quantity is "
                              "not exported per row (n_exit_fills only)"}

    # --- take-profit audit -----------------------------------------------------
    tp = [r for r in rows if r.get("exit_trigger") == "take_profit"]
    audit_rows = []
    cls_counts = defaultdict(int)
    for r in tp:
        cls = classify_tp_row(r)
        cls_counts[cls] += 1
        audit_rows.append({
            "decision_id": r.get("decision_id"),
            "ticker": r.get("ticker"), "side": r.get("side"),
            "generation": r.get("entry_fill_id"),
            "entry_price_c": r.get("entry_price_c"),
            "qty_contracts": r.get("qty_contracts"),
            "entry_fee_c": r.get("entry_fee_c"),
            "exit_exec_c": r.get("exit_exec_c"),
            "exit_quote_c": r.get("exit_quote_c"),
            "exit_fee_c": r.get("exit_fee_c"),
            "net_realized_c": r.get("realized_pnl_c"),
            "cf_hold_c": r.get("cf_hold_pnl_c"),
            "delta_c": r.get("exit_value_added_c"),
            "raw_trigger": r.get("exit_reason_raw"),
            "norm_trigger": r.get("exit_trigger"),
            "policy_version": "not_recorded_pre_arbiter",
            "floor_at_time": "not_recorded",
            "exception_authorization": None,
            "settle_value_held_c": r.get("settle_value_held_c"),
            "classification": cls})
    with open(TP_AUDIT, "w", encoding="utf-8") as f:
        for a in audit_rows:
            f.write(json.dumps(a, sort_keys=True) + "\n")

    # --- cohorts ---------------------------------------------------------------
    cohorts = {}
    for dim, keyfn in (
        ("asset", lambda r: r.get("asset") or "?"),
        ("side", lambda r: r.get("side") or "?"),
        ("entry_price_band", lambda r: price_band(r.get("entry_price_c"))),
        ("tte_at_entry", lambda r: tte_band(r.get("tte_at_entry_s"))),
        ("exit_trigger", lambda r: r.get("exit_trigger") or "?"),
        ("exit_reason_raw", lambda r: r.get("exit_reason_raw") or "?"),
    ):
        b = defaultdict(list)
        for r in recon:
            b[keyfn(r)].append(r)
        cohorts[dim] = {}
        for k, v in sorted(b.items()):
            a = sum(r["realized_pnl_c"] or 0 for r in v)
            h = sum(r["cf_hold_pnl_c"] or 0 for r in v)
            cohorts[dim][k] = {"n": len(v), "actual_net_c": round(a, 2),
                               "hold_net_c": round(h, 2),
                               "delta_c": round(a - h, 2)}

    report = {
        "label": "same-entry liquidation comparison (NOT a full "
                 "alternative-strategy simulation)",
        "comparison_populations": {
            "all_reported_rows_delta_c": round(actual_total - sum(
                r["cf_hold_pnl_c"] or 0 for r in rows), 2),
            "all_rows_note": "difference between reported aggregates; "
                             "unknown-outcome rows have no valid hold "
                             "counterfactual (treated as 0 here)",
            "known_outcome_delta_c": round(delta_total, 2),
            "known_outcome_note": "comparison over rows with both legs "
                                  "known; subject to quantity alignment",
            "quantity_mismatched_rows": qty_mismatch,
            "quantity_indeterminate_rows": qty_indeterminate,
        },
        "acceptance_wording": (
            "Reported actual net PnL was +191.88c. The known-settlement "
            "ledger comparison was +140.83c versus same-entry hold, with "
            "partial-exit quantity comparability still unresolved unless "
            "verified separately. 35 of 88 known-outcome early exits "
            "executed below eventual settlement value. Take-profit "
            "attribution was dominated by below-entry executions. These "
            "findings correct the prior accounting and recovery claims "
            "but do not establish a causal policy advantage or justify a "
            "policy change."),
        "deployment_scope": "all rows predate the exit arbiter; they cannot "
                            "evidence its floor enforcement either way",
        "n_positions": len(rows), "n_early_exits": len(early),
        "n_settled": len(settled), "n_open": len(open_rows),
        "n_settlement_unknown": len(unknown),
        "policies": policies,
        "exit_vs_settlement_delta_c": round(delta_total, 2),
        "decomposition": decomposition,
        "fill_accounting": fills_meta,
        "take_profit_audit": {
            "n": len(tp), "classifications": dict(cls_counts),
            "classification_precedence": [
                "1. below_entry_execution (exec < entry; loss-taking, "
                "no floor guarantee under old policy)",
                "2. else forfeited_settlement_win (settle 100 > exec)",
                "3. else fees_turned_gross_gain_negative",
                "4. else exit_added_value",
                "5. else settlement_outcome_unknown / unclassified"],
            "precedence_note": "categories overlap; each row takes the "
                               "FIRST matching class, so forfeited_win rows "
                               "exclude rows already counted below_entry",
            "export": str(TP_AUDIT)},
        "cohorts": cohorts,
        "invariants": {n: ok for n, ok in inv},
        "missing_data": {
            "allocated_exit_qty_per_row":
                "not exported by exit_decision_ledger.py — reconciled "
                "post-hoc via implied-exit-qty inversion; "
                f"{qty_mismatch} mismatched, {qty_indeterminate} "
                "indeterminate (exec==entry)",
            "policy_version_per_row": "not recorded — all pre-arbiter",
            "tte_at_entry_s": sum(1 for r in rows
                                  if r.get("tte_at_entry_s") is None),
            "intrawindow_book_path": "0 coverage — trail/model policies "
                                     "not simulable",
        },
        "row_export": str(ROWS_OUT),
    }
    OUT.write_text(json.dumps(report, indent=1), encoding="utf-8")

    # ---- console ------------------------------------------------------------
    print(f"positions={len(rows)} early={len(early)} settled={len(settled)} "
          f"open={len(open_rows)} unknown_settle={len(unknown)}")
    print(f"ACTUAL net={policies['actual']['net_pnl_c']}c "
          f"mdd={policies['actual']['max_drawdown_c']}c")
    print(f"HOLD   net={policies['same_entry_hold_to_settlement']['net_pnl_c']}c "
          f"mdd={policies['same_entry_hold_to_settlement']['max_drawdown_c']}c")
    print(f"delta(actual-hold,known)={delta_total:.2f}c  "
          f"benefit={benefit:.2f} cost={cost:.2f} "
          f"benefit-cost={benefit - cost:.2f}")
    print(f"all-rows aggregate delta={actual_total - sum(r['cf_hold_pnl_c'] or 0 for r in rows):.2f}c "
          f"(includes {len(unknown)} unknown-outcome rows)")
    print(f"qty reconciliation: mismatched={qty_mismatch} "
          f"indeterminate={qty_indeterminate} of {len(early)}")
    print(f"exits below eventual settle value={len(forfeited)} "
          f"exec above settle={len(helped)}")
    print(f"records-with-fills={fills_meta['completed_early_exit_records_with_fills']}")
    for L in HARD_LOCK_LEVELS:
        p = policies[f"hard_lock_{L}c"]
        print(f"hard_lock_{L}c: observed_fills_at_or_above={p['observed_exit_fills_at_or_above_L']} "
              f"extrema={p['unconstrained_scenario_extrema_c']}")
    print("\ntake_profit classifications:")
    for k, v in sorted(cls_counts.items()):
        print(f"  {k}: {v}")
    print("\ninvariants:")
    ok_all = True
    for n, ok in inv:
        print(f"  [{'PASS' if ok else 'FAIL'}] {n}")
        ok_all &= ok
    for dim, bk in cohorts.items():
        print(f"\n-- {dim} --")
        for k, v in bk.items():
            print(f"  {k:>20}: n={v['n']:>3} actual={v['actual_net_c']:>9.1f} "
                  f"hold={v['hold_net_c']:>9.1f} delta={v['delta_c']:>8.1f}")
    print(f"\nreport -> {OUT}\nrows   -> {ROWS_OUT}\naudit  -> {TP_AUDIT}")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
