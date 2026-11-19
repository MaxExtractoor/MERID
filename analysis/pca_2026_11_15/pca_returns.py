"""PCA on 15m RTI log returns - MERID underlying risk structure."""
import json, datetime
import numpy as np
from scipy import stats

ASSETS=['BTC','ETH','DOGE','SOL','XRP']
R=np.load("analysis/pca_2026_11_15/rti_returns_15m.npy")
rts=json.load(open("analysis/pca_2026_11_15/rti_return_ts.json"))
T,N=R.shape
print(f"=== PCA on {N} assets, T={T} 15m log returns ===")
print("span:", datetime.datetime.utcfromtimestamp(rts[0]/1000), "->", datetime.datetime.utcfromtimestamp(rts[-1]/1000))

def pca_report(R, label, standardize=True):
    X = R - R.mean(0)
    if standardize:
        sd = X.std(0, ddof=1)
        Z = X/sd
        C = np.corrcoef(Z.T)
    else:
        C = np.cov(X.T)
    w,V = np.linalg.eigh(C)          # ascending
    w=w[::-1]; V=V[:,::-1]
    ev = w/w.sum()
    print(f"\n--- {label} ---")
    print("eigenvalues:", np.round(w,4))
    print("variance explained %:", np.round(ev*100,2))
    print("cumvar %:", np.round(np.cumsum(ev)*100,2))
    # Kaiser: corr->>1, cov->>mean
    thr = 1.0 if standardize else w.mean()
    print("Kaiser (>%.3f) count:"%thr, int((w>thr).sum()))
    # participation ratio & effective bets
    pr = w.sum()**2/ (w**2).sum()
    p = ev/ev.sum()  # shares sum to 1
    encb = np.exp(-(p*np.log(p+1e-300)).sum())
    print(f"participation ratio: {pr:.3f}   ENCB: {encb:.3f}")
    # IPR per eigenvector (localization)
    ipr = (V**4).sum(0)
    print("IPR per PC:", np.round(ipr,3), " (1/N=%.2f delocalized)"%(1/N))
    # top loadings
    for k in range(min(3,N)):
        order=np.argsort(-np.abs(V[:,k]))
        print(f"PC{k+1} ({ev[k]*100:.1f}%): ", {ASSETS[i]: round(V[i,k],3) for i in order[:5]})
    return w,V,C

# ---- 1. correlation PCA (standard) ----
w,V,C = pca_report(R,"Correlation PCA (raw 15m returns)")

# ---- 2. winsorized returns ----
lo,hi = np.percentile(R,[1,99],axis=0)
Rw = np.clip(R,lo,hi)
pca_report(Rw,"Correlation PCA (winsorized 1/99)")

# ---- 3. covariance PCA ----
pca_report(R,"Covariance PCA (unstandardized)",standardize=False)

# ---- 4. Ledout-Wolf style shrinkage on correlation ----
from sklearn.covariance import LedoitWolf
lw = LedoitWolf().fit(R)   # assumes ~centered; fit on raw returns
Cs = lw.covariance_
# convert cov->corr shrinkage equivalence: eigen of shrunk cov on standardized data
sd = R.std(0,ddof=1); Z=(R-R.mean(0))/sd
lwz = LedoitWolf().fit(Z)
Cshr = lwz.covariance_
ws,Vs = np.linalg.eigh(Cshr); ws=ws[::-1]; Vs=Vs[:,::-1]
print("\n--- Ledoit-Wolf shrunk correlation eigenvalues ---")
print(np.round(ws,4), " var%:", np.round(ws/ws.sum()*100,2))

# ---- 5. Marchenko-Pastur noise bound ----
q = N/T
mp_hi = (1+np.sqrt(q))**2
mp_lo = (1-np.sqrt(q))**2
print(f"\nMP bounds for correlation (q=N/T={q:.4f}): [{mp_lo:.4f}, {mp_hi:.4f}]")
print("eigenvalues above MP upper:", int((w>mp_hi).sum()), " of", N)
# parallel-analysis style: eigenvalues of random corr matrices
rng=np.random.default_rng(0)
nulls=[]
for _ in range(200):
    Zr=rng.standard_normal((T,N))
    # shuffle each column independently to destroy cross-correlation but keep marginals
    for j in range(N): rng.shuffle(Zr[:,j])
    Cr=np.corrcoef(Zr.T)
    nulls.append(np.linalg.eigvalsh(Cr)[::-1])
nulls=np.array(nulls)
print("null 95th pct per PC:", np.round(np.percentile(nulls,95,axis=0),3))
print("observed > null95:", (w>np.percentile(nulls,95,axis=0)).astype(int))

# ---- 6. serial correlation (Ljung-Box) ----
print("\n--- serial correlation ---")
for j,a in enumerate(ASSETS):
    x=R[:,j]-R[:,j].mean()
    ac=[np.corrcoef(x[:-k],x[k:])[0,1] for k in range(1,6)]
    lb = T*(T+2)*sum((ac[k-1]**2)/(T-k) for k in range(1,6))
    print(f"  {a}: acf1-5={np.round(ac,4)} LB(5)={lb:.1f} p={1-stats.chi2.cdf(lb,5):.4f}")
# cross-correlation matrix at lag0 and lag1 (lead-lag)
C0=np.corrcoef(R.T)
print("\nlag-0 corr:\n", np.round(C0,3))
# lag-1 cross corr: corr(R_t^i, R_{t+1}^j)
X=R[:-1]; Y=R[1:]
Clag=np.corrcoef(np.hstack([X,Y]).T)[:N,N:]
print("\nlag+1 cross-corr (row asset leads col asset):\n", np.round(Clag,3))
