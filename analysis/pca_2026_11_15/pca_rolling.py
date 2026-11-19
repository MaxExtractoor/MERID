"""Rolling-window PCA + regime diagnostics on 15m RTI returns."""
import json, datetime
import numpy as np

ASSETS=['BTC','ETH','DOGE','SOL','XRP']
R=np.load("analysis/pca_2026_11_15/rti_returns_15m.npy")
rts=np.array(json.load(open("analysis/pca_2026_11_15/rti_return_ts.json")))
T,N=R.shape

def roll_pca(R, win, step):
    out=[]
    for s in range(0, T-win+1, step):
        X=R[s:s+win]
        Z=(X-X.mean(0))/X.std(0,ddof=1)
        C=np.corrcoef(Z.T)
        w,V=np.linalg.eigh(C); w=w[::-1]; V=V[:,::-1]
        out.append((s+win//2, w, V[:,0], C))
    return out

# window ~ 2 weeks of covered returns? returns are clustered; use 500 obs (~16% of sample)
for WIN,STEP in [(500,100),(1000,200)]:
    res=roll_pca(R,WIN,STEP)
    l1=np.array([r[1][0]/N*100 for r in res])
    # eigenvector stability: |dot(u1_t,u1_{t-1})|
    stab=[]
    for i in range(1,len(res)):
        stab.append(abs(np.dot(res[i][2],res[i-1][2])))
    stab=np.array(stab)
    print(f"\n=== rolling win={WIN} step={STEP}: {len(res)} windows ===")
    print(f"PC1 var% : min {l1.min():.1f} med {np.median(l1):.1f} max {l1.max():.1f}")
    print(f"u1 stability |cos|: min {stab.min():.3f} med {np.median(stab):.3f}")
    # top/bottom windows by lambda1
    order=np.argsort(-l1)
    print("highest-PC1 windows:")
    for i in order[:5]:
        mid=res[i][0]; ts=rts[mid]
        print(f"  idx {mid} {datetime.datetime.utcfromtimestamp(ts/1000)}  PC1%={l1[i]:.1f}")
    print("lowest-PC1 windows:")
    for i in order[-5:]:
        mid=res[i][0]; ts=rts[mid]
        print(f"  idx {mid} {datetime.datetime.utcfromtimestamp(ts/1000)}  PC1%={l1[i]:.1f}")
    # save series
    np.save(f"analysis/pca_2026_11_15/roll_win{WIN}_pc1share.npy", l1)
    np.save(f"analysis/pca_2026_11_15/roll_win{WIN}_stab.npy", stab)
    json.dump([int(rts[r[0]]) for r in res], open(f"analysis/pca_2026_11_15/roll_win{WIN}_ts.json","w"))

# ---- correlation drift: first vs second half, and per-month ----
h=T//2
for name,sl in [("first half",slice(0,h)),("second half",slice(h,T))]:
    X=R[sl]; Z=(X-X.mean(0))/X.std(0,ddof=1); C=np.corrcoef(Z.T)
    w=np.linalg.eigvalsh(C)[::-1]
    print(f"\n{name}: eigvar% {np.round(w/w.sum()*100,1)}  mean|offdiag corr| {np.mean(np.abs(C-np.eye(N))):.3f}")
    print("  corr:\n", np.round(C,2))

# per-month correlation mean
months={}
for i,t in enumerate(rts):
    m=datetime.datetime.utcfromtimestamp(t/1000).strftime("%Y-%m")
    months.setdefault(m,[]).append(i)
print("\nper-month mean pairwise |corr| and PC1 share:")
for m,idx in sorted(months.items()):
    if len(idx)<30: continue
    X=R[idx]; Z=(X-X.mean(0))/X.std(0,ddof=1); C=np.corrcoef(Z.T)
    w=np.linalg.eigvalsh(C)[::-1]
    off=np.abs(C[np.triu_indices(N,1)]).mean()
    print(f"  {m}: n={len(idx):4d} PC1%={w[0]/N*100:5.1f}  mean|rho|={off:.3f}")
