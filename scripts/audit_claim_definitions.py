"""Second-pass: claim definition matters. Bucket realized by GROSS edge
(model p - executable price) and by deduped last-look, vs net_ev claim."""
import pandas as pd
import numpy as np

df = pd.read_pickle("data/decision_spine.pkl")
for col in ["counterfactual_yes_pnl_cents","counterfactual_no_pnl_cents",
            "expected_net_ev_cents","gross_edge_cents","calibrated_probability",
            "executable_entry_price_cents","entry_fee_cents",
            "exit_or_settlement_fee_cents","model_uncertainty_haircut_cents",
            "adverse_selection_haircut_cents","edge_bias_correction_c",
            "lower_confidence_bound_ev_cents","required_edge_cents","gate_ev_cents"]:
    df[col] = pd.to_numeric(df[col], errors="coerce")

df["held_pnl"] = np.where(df.side == "yes", df.counterfactual_yes_pnl_cents,
                          df.counterfactual_no_pnl_cents)
df["claim_gap"] = df.calibrated_probability*100.0 - df.executable_entry_price_cents

fe = df[(df.counterfactual_execution_status == "FULLY_EXECUTABLE") & df.model_evaluated.eq(1)].copy()
print("FULLY_EXEC n =", len(fe))

def bucket_report(frame, col, bins, label):
    print(f"\n=== REALIZED BY {label} ({col}) FULLY_EXEC ===")
    b = pd.cut(frame[col], bins)
    g = frame.groupby(b, observed=True).agg(
        n=("held_pnl","size"), mean=("held_pnl","mean"),
        med=("held_pnl","median"), wr=("held_pnl", lambda s:(s>0).mean()))
    print(g.to_string())

bins_claim = [-100,-10,-5,-2,0,1,2,3,5,8,15,50,200]
bucket_report(fe, "claim_gap", bins_claim, "model-vs-price gap (cents)")
bucket_report(fe, "gross_edge_cents", bins_claim, "gross_edge_cents")
bucket_report(fe, "expected_net_ev_cents", bins_claim, "expected_net_ev_cents (net of reserves)")

# dedup: last eval per (ticker, side) — the audit's cohort definition
dd = fe.sort_values("decision_ts").groupby(["ticker","side"], as_index=False).tail(1)
print("\ndeduped last-look n =", len(dd))
bucket_report(dd, "claim_gap", bins_claim, "claim_gap (deduped)")
bucket_report(dd, "expected_net_ev_cents", bins_claim, "net_ev (deduped)")

# claim_gap>=+2 deduped — replicate the +3.85c finding
cg = dd[dd.claim_gap >= 2.0]
print(f"\nclaim_gap>=+2 deduped: n={len(cg)} mkts={cg.ticker.nunique()} "
      f"mean={cg.held_pnl.mean():.3f}c med={cg.held_pnl.median():.3f} wr={(cg.held_pnl>0).mean()*100:.1f}%")
# split by price
for lo,hi in [(0,10),(10,25),(25,50),(50,75),(75,90),(90,101)]:
    m = cg[(cg.executable_entry_price_cents>=lo)&(cg.executable_entry_price_cents<hi)]
    if len(m)<20: continue
    print(f"  px{lo}-{hi}: n={len(m):4d} mean={m.held_pnl.mean():7.3f}c wr={(m.held_pnl>0).mean()*100:5.1f}%")

# does it pass gates?
print("\nclaim_gap>=+2 deduped gate stats:")
print(" passed_edge_gate:", int(cg.passed_edge_gate.sum()), "/", len(cg))
print(" selected:", int(cg.selected.sum()))
print(" executable:", int(cg.executable.sum()))
print("\nrequired_edge med:", cg.required_edge_cents.median(),
      " gate_ev med:", cg.gate_ev_cents.median(),
      " net_ev med:", cg.expected_net_ev_cents.median())
print("edge_bias med:", cg.edge_bias_correction_c.median())

# selected -> what decision?
sel = df[df.selected == 1]
print("\n=== SELECTED side-rows: decision values ===")
print(sel.decision.value_counts().head(10).to_string())
print("selected by decision_lane:")
print(sel.decision_lane.value_counts().head(15).to_string())
# of selected, how many have fill?
print("selected with fill_id:", int(sel.fill_id.notna().sum()), "/", len(sel))

# selected but no fill: what stops them? look at events later; for now
# check selected rows' outcome_status
print("\nselected outcome_status:")
print(sel.outcome_status.value_counts().head(10).to_string())
