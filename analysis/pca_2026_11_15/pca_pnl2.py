"""PCA on market-date daily settlement P&L - corrected."""
import json, datetime
import numpy as np
ASSETS=['BTC','ETH','DOGE','SOL','XRP']
M=np.load("analysis/pca_2026_11_15/daily_pnl_mktdate.npy")
days=json.load(open("analysis/pca_2026_11_15/daily_pnl_mktdate_days.json"))
D,N=M.shape
mask=M.sum(1)!=0; Mm=M[mask]; dd=[d for d,m in zip(days,mask) if m]
print(f"=== Settlement P&L PCA (market-date): {Mm.shape[0]} active days x {N} ===")
C=np.corrcoef(Mm.T); w,V=np.linalg.eigh(C); w=w[::-1]; V=V[:,::-1]
ev=w/w.sum()
print("eigval:",np.round(w,3)); print("var%:",np.round(ev*100,2)," cum:",np.round(np.cumsum(ev)*100,1))
# parallel analysis null
rng=np.random.default_rng(1); nulls=[]
for _ in range(300):
    Z=rng.standard_normal(Mm.shape); 
    for j in range(N): rng.shuffle(Z[:,j])
    nulls.append(np.linalg.eigvalsh(np.corrcoef(Z.T))[::-1])
nulls=np.array(nulls)
print("null95:",np.round(np.percentile(nulls,95,0),3))
print("sig>95:",(w>np.percentile(nulls,95,0)).astype(int))
pr=w.sum()**2/(w**2).sum(); p=ev
encb=np.exp(-(p*np.log(p+1e-300)).sum())
print(f"PR={pr:.2f} ENCB={encb:.2f}")
for k in range(N):
    o=np.argsort(-np.abs(V[:,k]))
    print(f"PC{k+1} ({ev[k]*100:.1f}%):",{ASSETS[i]:round(V[i,k],3) for i in o})
# sub-periods
for name,sl in [("Jun-Aug",slice(0,62)),("Sep-Nov",slice(62,D))]:
    X=M[sl][M[sl].sum(1)!=0]
    if X.shape[0]<15: continue
    Cx=np.corrcoef(X.T); wx=np.linalg.eigvalsh(Cx)[::-1]
    print(f"\n{name}: n={X.shape[0]} eigvar%={np.round(wx/wx.sum()*100,1)}")
# weekly aggregation alternative (more stable)
# group days into ISO weeks
import collections
wk=collections.defaultdict(lambda: np.zeros(N))
for i,d in enumerate(days):
    dt=datetime.date.fromisoformat(d); iso=dt.isocalendar()[:2]
    wk[iso]+=M[i]
W=np.array([wk[k] for k in sorted(wk)])
W=W[W.sum(1)!=0]
Cw=np.corrcoef(W.T); ww=np.linalg.eigvalsh(Cw)[::-1]
print(f"\nweekly P&L: {W.shape[0]} weeks, eigvar%={np.round(ww/ww.sum()*100,1)}")
print("weekly corr:\n",np.round(Cw,2))
