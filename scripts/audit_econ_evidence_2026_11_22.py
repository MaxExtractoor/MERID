"""Deep economics/evidence audit on the decision spine.

Answers: where do evals die, what does the claim tail look like vs the
enforced bound, and which reserve components eat the edge.
"""
import pandas as pd
import numpy as np

df = pd.read_pickle("data/decision_spine.pkl")
print("rows", len(df))

# ---- 0. basic funnel -------------------------------------------------
print("\n=== FUNNEL (all side evals) ===")
print("model_evaluated:", int(df.model_evaluated.sum()))
print("executable:", int(df.executable.sum()))
print("passed_edge_gate:", int(df.passed_edge_gate.sum()))
print("selected:", int(df.selected.sum()))
print("has fill_id:", int(df.fill_id.notna().sum()))
print("unique tickers:", df.ticker.nunique())
print("span days:", (df.decision_ts.max() - df.decision_ts.min()) / 86400)

# ---- 1. kill funnel by exclusion_reason --------------------------------
print("\n=== TOP exclusion_reason (model_evaluated & !passed_edge_gate) ===")
sub = df[(df.model_evaluated == 1) & (df.passed_edge_gate == 0)]
print(sub.exclusion_reason.value_counts().head(25).to_string())

# ---- 2. claim tail: expected_net_ev >= +2c ------------------------------
claim = df[(df.expected_net_ev_cents >= 2.0) & df.model_evaluated.eq(1)]
print(f"\n=== CLAIM>=+2c cohort: n={len(claim)} sides, "
      f"{claim.ticker.nunique()} mkts ===")
print("passed_edge_gate:", int(claim.passed_edge_gate.sum()),
      f"({claim.passed_edge_gate.mean()*100:.1f}%)")
print("selected:", int(claim.selected.sum()))
print("executable:", int(claim.executable.sum()))
print("FULLY_EXEC:", int((claim.counterfactual_execution_status == 'FULLY_EXECUTABLE').sum()))
print("\nexclusion_reason:")
print(claim.exclusion_reason.value_counts().head(20).to_string())
print("\nadmission_owner:")
print(claim.admission_owner.value_counts().head(15).to_string())

print("\nrequired_edge_cents describe:")
print(claim.required_edge_cents.describe(percentiles=[.1,.25,.5,.75,.9,.99]).to_string())
print("\ngate_ev_cents describe:")
print(claim.gate_ev_cents.describe(percentiles=[.1,.25,.5,.75,.9,.99]).to_string())

# how far below bound?
c = claim.copy()
c["shortfall"] = c.gate_ev_cents - c.enforced_edge_bound_cents if "enforced_edge_bound_cents" in c else np.nan
# spine lacks enforced_edge_bound_cents? check cols
print("\ncols w/ bound:", [x for x in df.columns if 'bound' in x or 'required' in x])

# ---- 3. reserves implied ----------------------------------------------
print("\n=== RESERVE COMPONENTS (claim>=+2 cohort, cents) ===")
for col in ["gross_edge_cents", "entry_fee_cents", "exit_or_settlement_fee_cents",
            "adverse_selection_haircut_cents", "model_uncertainty_haircut_cents",
            "edge_bias_correction_c", "expected_net_ev_cents", "calibrated_probability",
            "executable_entry_price_cents"]:
    if col in claim.columns:
        s = pd.to_numeric(claim[col], errors="coerce")
        print(f"{col:42s} mean={s.mean():8.3f} med={s.median():8.3f} p10={s.quantile(.1):8.3f} p90={s.quantile(.9):8.3f}")

# implied missing reserves = gross - shown deductions - net
c2 = claim.copy()
for col in c2.columns:
    c2[col] = pd.to_numeric(c2[col], errors="coerce")
implied = (c2.gross_edge_cents - c2.entry_fee_cents - c2.exit_or_settlement_fee_cents
           - c2.adverse_selection_haircut_cents.fillna(0)
           - c2.model_uncertainty_haircut_cents.fillna(0)
           - c2.edge_bias_correction_c.fillna(0)
           - c2.expected_net_ev_cents)
print("\nimplied unexported reserves (giveback+impl+other):")
print(implied.describe(percentiles=[.1,.25,.5,.75,.9]).to_string())

# ---- 4. realized counterfactual for claim tail -------------------------
# counterfactual pnl columns are per-contract cents at settlement
print("\n=== CLAIM>=+2 REALIZED (counterfactual, per-contract cents) ===")
for pxlo, pxhi in [(0,10),(10,25),(25,50),(50,75),(75,90),(90,100)]:
    m = claim[(claim.executable_entry_price_cents >= pxlo) &
              (claim.executable_entry_price_cents < pxhi)]
    if len(m) < 30:
        continue
    yes_pnl = pd.to_numeric(m.counterfactual_yes_pnl_cents, errors="coerce")
    no_pnl = pd.to_numeric(m.counterfactual_no_pnl_cents, errors="coerce")
    # pnl depends on side held
    held = np.where(m.side == "yes", yes_pnl, no_pnl)
    held = pd.Series(held)
    wr = (held > 0).mean()
    print(f"px {pxlo:3d}-{pxhi:3d}: n={len(m):6d} mkts={m.ticker.nunique():4d} "
          f"mean_pnl={held.mean():7.3f}c med={held.median():7.3f} wr={wr*100:5.1f}% "
          f"claim_mean={pd.to_numeric(m.expected_net_ev_cents,errors='coerce').mean():6.2f}c")

# FULLY_EXECUTABLE only
print("\n=== CLAIM>=+2 FULLY_EXECUTABLE only ===")
fe = claim[claim.counterfactual_execution_status == "FULLY_EXECUTABLE"].copy()
for col in ["counterfactual_yes_pnl_cents","counterfactual_no_pnl_cents","expected_net_ev_cents"]:
    fe[col] = pd.to_numeric(fe[col], errors="coerce")
fe["held_pnl"] = np.where(fe.side == "yes", fe.counterfactual_yes_pnl_cents, fe.counterfactual_no_pnl_cents)
print(f"n={len(fe)} mean={fe.held_pnl.mean():.3f}c med={fe.held_pnl.median():.3f} "
      f"wr={(fe.held_pnl>0).mean()*100:.1f}%")
for pxlo, pxhi in [(10,25),(25,50),(50,75),(75,90),(90,100)]:
    m = fe[(fe.executable_entry_price_cents >= pxlo) & (fe.executable_entry_price_cents < pxhi)]
    if len(m) < 30: continue
    print(f"  px {pxlo}-{pxhi}: n={len(m):5d} mean={m.held_pnl.mean():7.3f}c wr={(m.held_pnl>0).mean()*100:5.1f}%")

# ---- 5. what passes the edge gate but dies later -----------------------
print("\n=== claim>=+2 AND passed_edge_gate=1 ===")
passed = claim[claim.passed_edge_gate == 1]
print("n:", len(passed), "selected:", int(passed.selected.sum()))
print(passed.exclusion_reason.value_counts().head(15).to_string())
print("decision_lane:", passed.decision_lane.value_counts().head(10).to_string())

# ---- 6. whole-population realized by expected_net_ev bucket -------------
print("\n=== REALIZED BY CLAIM BUCKET (all evals, FULLY_EXEC only) ===")
allfe = df[(df.counterfactual_execution_status == "FULLY_EXECUTABLE") & df.model_evaluated.eq(1)].copy()
for col in ["counterfactual_yes_pnl_cents","counterfactual_no_pnl_cents","expected_net_ev_cents"]:
    allfe[col] = pd.to_numeric(allfe[col], errors="coerce")
allfe["held_pnl"] = np.where(allfe.side == "yes", allfe.counterfactual_yes_pnl_cents,
                             allfe.counterfactual_no_pnl_cents)
allfe["claim"] = allfe.expected_net_ev_cents
bins = [-100,-5,-2,0,2,4,6,10,20,50,200]
allfe["bucket"] = pd.cut(allfe.claim, bins)
g = allfe.groupby("bucket", observed=True).held_pnl.agg(["count","mean","median"])
g["wr"] = allfe.groupby("bucket", observed=True).held_pnl.apply(lambda s:(s>0).mean())
print(g.to_string())
