"""Link return-factor structure to strategy P&L."""
import json, datetime
import numpy as np
ASSETS=['BTC','ETH','DOGE','SOL','XRP']
R=np.load("analysis/pca_2026_11_15/rti_returns_15m.npy")
rts=np.array(json.load(open("analysis/pca_2026_11_15/rti_return_ts.json")))
M=np.load("analysis/pca_2026_11_15/daily_pnl_mktdate.npy")
days=json.load(open("analysis/pca_2026_11_15/daily_pnl_mktdate_days.json"))

# --- factor betas: corr of each asset return with PC1 score ---
X=R-R.mean(0); Z=X/X.std(0,ddof=1)
C=np.corrcoef(Z.T); w,V=np.linalg.eigh(C); w=w[::-1]; V=V[:,::-1]
pc1=Z@V[:,0]  # PC1 score series
print("=== asset 'betas' to PC1 (corr of asset ret with PC1 score) ===")
for j,a in enumerate(ASSETS):
    print(f"  {a}: {np.corrcoef(R[:,j],pc1)[0,1]:.3f}")
# market factor = equal-weight mean return
mkt=R.mean(1)
print("\nasset corr to equal-weight market return:")
for j,a in enumerate(ASSETS):
    print(f"  {a}: {np.corrcoef(R[:,j],mkt)[0,1]:.3f}")

# --- daily market return vs daily P&L ---
# build daily mean RTI return per market-date from return ts
rts_dt=[datetime.datetime.utcfromtimestamp(t/1000).date().isoformat() for t in rts]
from collections import defaultdict
dm=defaultdict(list)
for i,d in enumerate(rts_dt): dm[d].append(R[i].mean())
daily_mkt={d:np.mean(v) for d,v in dm.items()}
daily_mkt_abs={d:np.mean(np.abs(v)) for d,v in dm.items()}
# align with P&L days
common=sorted(set(daily_mkt)&set(days))
x=np.array([daily_mkt[d] for d in common])
ya=np.array([M[days.index(d)].sum() for d in common])  # total daily pnl cents
# also per-asset pnl vs market
print(f"\n=== daily total P&L vs daily mean market return ({len(common)} days) ===")
print("corr(total_pnl, mkt_ret):", np.corrcoef(x,ya)[0,1])
print("corr(total_pnl, |mkt_ret|):", np.corrcoef(np.abs(x),ya)[0,1])
# per asset
for j,a in enumerate(ASSETS):
    yj=np.array([M[days.index(d),j] for d in common])
    print(f"  {a}: corr(pnl,mkt)={np.corrcoef(x,yj)[0,1]:.3f}  corr(pnl,|mkt|)={np.corrcoef(np.abs(x),yj)[0,1]:.3f}")
# regression: pnl ~ mkt_ret
A=np.vstack([x,np.ones_like(x)]).T
coef=np.linalg.lstsq(A,ya,rcond=None)[0]
print(f"\ntotal P&L ~ {coef[0]:.0f}*mkt_ret + {coef[1]:.0f}  (cents per unit log-ret)")
# same but only 'active' days (system traded?) - all days have some settlements
# check pnl on high-|mkt| days vs low
hi=np.abs(x)>np.median(np.abs(x))
print(f"mean daily pnl on high-|mkt| days: {ya[hi].mean():.0f}c  low: {ya[~hi].mean():.0f}c")
