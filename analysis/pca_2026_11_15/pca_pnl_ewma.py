"""PCA on strategy settlement P&L + EWMA-vol-standardized return PCA."""
import json, datetime
import numpy as np

ASSETS=['BTC','ETH','DOGE','SOL','XRP']
R=np.load("analysis/pca_2026_11_15/rti_returns_15m.npy")
rts=np.array(json.load(open("analysis/pca_2026_11_15/rti_return_ts.json")))
T,N=R.shape

# ---------- A. EWMA-standardized returns (DCC-style) ----------
# standardize each return by its own EWMA vol -> correlation of "shocks"
lam=0.94
vol=np.zeros((T,N)); vol[:20]=R[:20].std(0)
for t in range(20,T):
    vol[t]=np.sqrt(lam*vol[t-1]**2+(1-lam)*R[t-1]**2)
Z=R/vol
Z=Z-Z.mean(0)
C=np.corrcoef(Z.T)
w,V=np.linalg.eigh(C); w=w[::-1]; V=V[:,::-1]
print("=== EWMA-vol-standardized return correlation PCA ===")
print("eigenvalues:",np.round(w,3)," var%:",np.round(w/w.sum()*100,2))
print("mean |corr| of standardized:", np.mean(np.abs(C[np.triu_indices(N,1)])))
Craw=np.corrcoef(R.T)
print("mean |corr| raw:", np.mean(np.abs(Craw[np.triu_indices(N,1)])))

# correlation of |returns| (vol co-movement) vs returns
A=np.abs(R-R.mean(0))
Cv=np.corrcoef(A.T)
print("\nvol-of-|r| correlation matrix:\n",np.round(Cv,2))
wv=np.linalg.eigvalsh(Cv)[::-1]
print("vol-corr eigvar%:",np.round(wv/wv.sum()*100,1))

# ---------- B. P&L PCA ----------
M=np.load("analysis/pca_2026_11_15/daily_pnl.npy")
days=json.load(open("analysis/pca_2026_11_15/daily_pnl_days.json"))
D,Np=M.shape
print(f"\n=== Settlement P&L PCA: {D} days x {Np} assets ===")
print("days:",days[0],"->",days[-1])
# active mask: days where all assets have nonzero activity? use all days but note zeros
act=(M!=0).sum(0)
print("nonzero asset-days:",act)
# correlation of daily P&L (days with all-zero row dropped)
mask=M.sum(1)!=0
Mm=M[mask]
print("active days used:",Mm.shape[0])
if Mm.shape[0]>10:
    Cp=np.corrcoef(Mm.T)
    wp,Vp=np.linalg.eigh(Cp); wp=wp[::-1]; Vp=Vp[:,::-1]
    print("P&L corr matrix:\n",np.round(Cp,3))
    print("eigval:",np.round(wp,3)," var%:",np.round(wp/wp.sum()*100,1))
    pr=wp.sum()**2/(wp**2).sum(); p=wp/wp.sum()
    encb=np.exp(-(p*np.log(p+1e-300)).sum())
    print(f"PR={pr:.2f} ENCB={encb:.2f}")
    for k in range(min(3,Np)):
        o=np.argsort(-np.abs(Vp[:,k]))
        print(f"PC{k+1} ({wp[k]/wp.sum()*100:.1f}%):",{ASSETS[i]:round(Vp[i,k],2) for i in o})
    # also PCA on wins/loss indicators? and on per-trade level
# per-trade settlement outcomes: win rate per asset
import sqlite3
con=sqlite3.connect("file:data/trade_attribution_fact.db?mode=ro&immutable=1", uri=True)
import re
wins={a:[0,0] for a in ASSETS}
for (tkr,pnl) in con.execute("SELECT ticker, realized_pnl_cents FROM trade_attribution_fact WHERE event_type='settlement'"):
    m=re.match(r'KX(BTC|ETH|DOGE|SOL|XRP)15M',tkr or '')
    if not m: continue
    a=m.group(1)
    if pnl is None: continue
    wins[a][1]+=1
    if pnl>0: wins[a][0]+=1
print("\nwin rate per asset (pnl>0):")
for a in ASSETS:
    w,n=wins[a]; print(f"  {a}: {w}/{n} = {w/n*100:.1f}%")
con.close()
