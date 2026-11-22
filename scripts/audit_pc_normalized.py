"""Fourth pass: per-contract normalized counterfactuals.

cf_pnl is TOTAL cents across assumed filled contracts; normalize by
counterfactual_assumed_filled_contracts to get per-contract cents.
"""
import pandas as pd
import numpy as np

df = pd.read_pickle("data/decision_spine.pkl")
for col in ["counterfactual_yes_pnl_cents","counterfactual_no_pnl_cents",
            "expected_net_ev_cents","gross_edge_cents","calibrated_probability",
            "executable_entry_price_cents","entry_fee_cents",
            "exit_or_settlement_fee_cents","model_uncertainty_haircut_cents",
            "adverse_selection_haircut_cents","edge_bias_correction_c",
            "required_edge_cents","gate_ev_cents",
            "counterfactual_assumed_filled_contracts"]:
    df[col] = pd.to_numeric(df[col], errors="coerce")

df["held_pnl_tot"] = np.where(df.side=="yes", df.counterfactual_yes_pnl_cents,
                              df.counterfactual_no_pnl_cents)
q = df.counterfactual_assumed_filled_contracts.clip(lower=0)
df["pc_pnl"] = np.where(q>0, df.held_pnl_tot/q, np.nan)   # per-contract cents
df["claim_gap"] = df.calibrated_probability*100.0 - df.executable_entry_price_cents

fe = df[(df.counterfactual_execution_status=="FULLY_EXECUTABLE") & df.model_evaluated.eq(1)].copy()
fe = fe[fe.counterfactual_assumed_filled_contracts>0]
print("FULLY_EXEC q>0 n =", len(fe), " mean q =", fe.counterfactual_assumed_filled_contracts.mean())

def rep(frame, col, bins, label):
    print(f"\n=== per-contract realized by {label} ===")
    b = pd.cut(frame[col], bins)
    g = frame.groupby(b, observed=True).agg(
        n=("pc_pnl","size"), mean=("pc_pnl","mean"), med=("pc_pnl","median"),
        wr=("pc_pnl", lambda s:(s>0).mean()))
    print(g.to_string())

bins = [-100,-10,-5,-2,0,1,2,3,5,8,15,50,200]
rep(fe, "claim_gap", bins, "claim_gap")
rep(fe, "expected_net_ev_cents", bins, "expected_net_ev")
rep(fe, "gross_edge_cents", bins, "gross_edge")

# dedup last-look per (ticker,side)
dd = fe.sort_values("decision_ts").groupby(["ticker","side"], as_index=False).tail(1)
print("\ndeduped n =", len(dd))
rep(dd, "claim_gap", bins, "claim_gap deduped")
rep(dd, "expected_net_ev_cents", bins, "net_ev deduped")

cg = dd[dd.claim_gap>=2.0]
print(f"\nclaim_gap>=+2 deduped: n={len(cg)} mkts={cg.ticker.nunique()} "
      f"pc_mean={cg.pc_pnl.mean():.3f}c med={cg.pc_pnl.median():.3f} wr={(cg.pc_pnl>0).mean()*100:.1f}%")
for lo,hi in [(0,10),(10,25),(25,50),(50,75),(75,90),(90,101)]:
    m = cg[(cg.executable_entry_price_cents>=lo)&(cg.executable_entry_price_cents<hi)]
    if len(m)<20: continue
    print(f"  px{lo}-{hi}: n={len(m):4d} pc={m.pc_pnl.mean():7.3f}c wr={(m.pc_pnl>0).mean()*100:5.1f}%")

# pf selected per-contract
sel = df[df.selected==1]
pf = sel[sel.decision_lane=="pinned_fav"].copy()
pf["pc_pnl"] = np.where(pf.counterfactual_assumed_filled_contracts>0,
                         pf.held_pnl_tot/pf.counterfactual_assumed_filled_contracts.clip(lower=1), np.nan)
print(f"\npf selected n={len(pf)} pc_mean={pf.pc_pnl.mean():.3f}c wr={(pf.pc_pnl>0).mean()*100:.1f}%")
for lo,hi in [(85,90),(90,94),(94,96),(96,98),(98,101)]:
    m = pf[(pf.executable_entry_price_cents>=lo)&(pf.executable_entry_price_cents<hi)]
    if len(m)<10: continue
    print(f"  pf px{lo}-{hi}: n={len(m):5d} pc={m.pc_pnl.mean():7.3f}c wr={(m.pc_pnl>0).mean()*100:5.1f}% q={m.counterfactual_assumed_filled_contracts.mean():.1f}")

# all selected (any lane) per-contract
sel2 = sel.copy()
sel2["pc_pnl"] = np.where(sel2.counterfactual_assumed_filled_contracts>0,
                          sel2.held_pnl_tot/sel2.counterfactual_assumed_filled_contracts.clip(lower=1), np.nan)
print(f"\nALL selected n={len(sel2)} pc_mean={sel2.pc_pnl.mean():.3f}c wr={(sel2.pc_pnl>0).mean()*100:.1f}%")
print(sel2.groupby("decision_lane").pc_pnl.agg(["count","mean"]).to_string())
