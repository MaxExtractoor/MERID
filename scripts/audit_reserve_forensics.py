"""Third pass: reserve-stack forensics.

1. edge_bias rebate by price band — is favorite-measured bias leaking into
   cheap-band evals (cohort key lacks price/TTE)?
2. model_uncertainty / calib-gap / drift composition.
3. claim cohort TTE proxy via close_ts if present; else skip.
4. pf ENTER -> fill attrition.
"""
import pandas as pd
import numpy as np

df = pd.read_pickle("data/decision_spine.pkl")
for col in ["counterfactual_yes_pnl_cents","counterfactual_no_pnl_cents",
            "expected_net_ev_cents","gross_edge_cents","calibrated_probability",
            "executable_entry_price_cents","entry_fee_cents",
            "exit_or_settlement_fee_cents","model_uncertainty_haircut_cents",
            "adverse_selection_haircut_cents","edge_bias_correction_c",
            "lower_confidence_bound_ev_cents","required_edge_cents","gate_ev_cents",
            "executable_entry_depth_fp"]:
    df[col] = pd.to_numeric(df[col], errors="coerce")
df["held_pnl"] = np.where(df.side == "yes", df.counterfactual_yes_pnl_cents,
                          df.counterfactual_no_pnl_cents)
df["claim_gap"] = df.calibrated_probability*100.0 - df.executable_entry_price_cents
fe = df[(df.counterfactual_execution_status == "FULLY_EXECUTABLE") & df.model_evaluated.eq(1)].copy()

print("=== edge_bias_correction_c distribution (all FULLY_EXEC) ===")
print(fe.edge_bias_correction_c.describe(percentiles=[.05,.25,.5,.75,.95]).to_string())
print("\nvalue counts (top):")
print(fe.edge_bias_correction_c.round(2).value_counts().head(12).to_string())

print("\n=== edge_bias by price band (mean / share at -4 rebate cap) ===")
fe["pxband"] = pd.cut(fe.executable_entry_price_cents, [0,10,25,50,75,90,101],
                      labels=["0-10","10-25","25-50","50-75","75-90","90-100"])
g = fe.groupby("pxband", observed=True).edge_bias_correction_c.agg(
    ["count","mean","median"])
g["pct_at_-4"] = fe.groupby("pxband", observed=True).edge_bias_correction_c.apply(
    lambda s:(s<=-3.9).mean())
print(g.to_string())

print("\n=== edge_bias by asset|side (mean) ===")
print(fe.groupby([fe.ticker.str.extract(r'KX([A-Z]+)')[0].fillna('?'), "side"]).edge_bias_correction_c.agg(["count","mean","median"]).to_string())

# realized pnl for evals carrying the -4 rebate, by price band
dd = fe.sort_values("decision_ts").groupby(["ticker","side"], as_index=False).tail(1)
reb = dd[dd.edge_bias_correction_c <= -3.9]
print(f"\n=== deduped evals at rebate cap (-4c): n={len(reb)} ===")
print("mean held_pnl:", reb.held_pnl.mean(), " wr:", (reb.held_pnl>0).mean())
for lo,hi in [(0,10),(10,25),(25,50),(50,75),(75,90),(90,101)]:
    m = reb[(reb.executable_entry_price_cents>=lo)&(reb.executable_entry_price_cents<hi)]
    if len(m)<15: continue
    print(f"  px{lo}-{hi}: n={len(m):4d} mean={m.held_pnl.mean():7.3f}c wr={(m.held_pnl>0).mean()*100:5.1f}% claim_gap_med={m.claim_gap.median():.2f}")

# same but WITHOUT rebate (edge_bias ~0)
noreb = dd[(dd.edge_bias_correction_c > -0.5) & (dd.edge_bias_correction_c < 0.5)]
print(f"\n=== deduped evals with ~0 bias correction: n={len(noreb)} ===")
print("mean held_pnl:", noreb.held_pnl.mean(), " wr:", (noreb.held_pnl>0).mean())

# pf lane ENTER attrition
sel = df[df.selected == 1]
pf = sel[sel.decision_lane == "pinned_fav"]
print(f"\n=== pinned_fav selected={len(pf)} fills={int(pf.actual_fill_price_cents.notna().sum())} ===")
# price distribution of pf selections
print(pf.executable_entry_price_cents.describe(percentiles=[.1,.5,.9]).to_string())
# claim stats for pf
print("pf net_ev med:", pf.expected_net_ev_cents.median(),
      " gross med:", pf.gross_edge_cents.median(),
      " required med:", pf.required_edge_cents.median(),
      " edge_bias med:", pf.edge_bias_correction_c.median())
print("pf held_pnl mean (counterfactual):", pf.held_pnl.mean(),
      " wr:", (pf.held_pnl>0).mean())
# pf realized by price
pf2 = pf.copy()
for lo,hi in [(90,94),(94,96),(96,98),(98,101)]:
    m = pf2[(pf2.executable_entry_price_cents>=lo)&(pf2.executable_entry_price_cents<hi)]
    if len(m)<10: continue
    print(f"  pf px{lo}-{hi}: n={len(m):5d} mean={m.held_pnl.mean():7.3f}c wr={(m.held_pnl>0).mean()*100:5.1f}%")

# how many DISTINCT markets got a pf ENTER per day?
print("\npf ENTER distinct tickers:", pf.ticker.nunique(), "over",
      (df.decision_ts.max()-df.decision_ts.min())/86400, "days")
