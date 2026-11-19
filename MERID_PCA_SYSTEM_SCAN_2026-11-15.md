# MERID System-Wide Principal Component Analysis — 2026-11-15

**Scope:** PCA across the three layers of the Kalshi 15m crypto system —
(1) underlying RTI return structure, (2) strategy settlement P&L structure,
(3) cross-layer linkage. Methodology follows current best practice for PCA on
financial time series: correlation-matrix PCA on standardized returns,
winsorization/robustness checks, Ledoit-Wolf shrinkage, Marchenko–Pastur /
parallel-analysis significance testing, rolling-window regime diagnostics, and
EWMA-volatility-standardized (DCC-style) corroboration.

**Artifacts:** `analysis/pca_2026_11_15/` — scripts (`pca_returns.py`,
`pca_rolling.py`, `pca_pnl2.py`, `pca_pnl_ewma.py`, `pca_linkage.py`), the
15m return panel (`rti_returns_15m.npy`, T=3077×5), settlement extracts, and
rolling-PCA series.

---

## 1. Data

| Layer | Source | Coverage | Sample |
|---|---|---|---|
| RTI spot ticks | `data/rti_backfill.db` + `data/cf_rti_ticks.db` | 2026-06-27 → 2026-11-15 | 3,531 common 15m buckets → **3,077 consecutive 15m log returns** (454 contiguous runs, mostly 8-bucket ≈ 2h sessions) |
| Settlement P&L | `data/trade_attribution_fact.db` (`event_type='settlement'`) | market-dates 2026-06-27 → 2026-11-15 | 3,759 settlements → **125 active days × 5 assets** |
| Entry orders | same DB (`event_type='order'`, `merid.prediction.agent_grid_15m`) | — | 2,323 parsed entries for side/window alignment |

Assets: BTC (BRTI), ETH, DOGE, SOL, XRP — the full traded universe.
Returns are log returns of the last RTI tick inside each 15m bucket, computed
only on exactly-consecutive buckets inside contiguous runs (no stale-price or
over-gap returns). Settlement P&L is aggregated by **market date parsed from
the ticker**, not `event_ts` (see Issue D).

15m volatilities (bps): BTC 20.7, ETH 26.2, DOGE 33.6, SOL 31.1, XRP 35.5 —
plausible for the horizon; zero-return fraction ≈ 0 (SOL 2.4%, thin book).

---

## 2. PCA — underlying RTI returns (market layer)

### Full-sample correlation PCA (T=3077, N=5)

| PC | Eigenvalue | Var % | Cum % | Interpretation |
|---|---|---|---|---|
| PC1 | 4.208 | **84.2** | 84.2 | Market factor — near-equal loadings (−0.43…−0.46) |
| PC2 | 0.318 | 6.4 | 90.5 | XRP-vs-rest contrast (XRP +0.74, BTC −0.47) |
| PC3 | 0.211 | 4.2 | 94.7 | SOL/DOGE contrast |
| PC4 | 0.158 | 3.2 | 97.9 | residual |
| PC5 | 0.105 | 2.1 | 100 | residual |

- Kaiser (>1): **1 factor**. Marchenko–Pastur bound [0.92, 1.08]; parallel
  analysis (300 column-shuffled nulls): **only PC1 significant at 95%**.
- Participation ratio **1.40**, effective number of bets **ENCB ≈ 1.9**.
- IPR: PC1 fully delocalized (0.20 = 1/N) — a genuine market mode, not a
  single-asset artifact. PC4/PC5 localized (IPR 0.46–0.50).
- Lag-0 correlations: 0.74–0.89 (BTC least correlated with all).
- Asset "betas" to PC1 score: −0.88…−0.94 — essentially identical; **no asset
  is a diversifier at the factor level.**

### Robustness (all confirm the above)

- Winsorized 1/99 returns: PC1 84.1% (unchanged) → not outlier-driven.
- Ledoit-Wolf shrunk correlation: λ1 4.18 vs 4.21 → sample matrix already
  well-estimated (T/N ≈ 615).
- Covariance (unstandardized) PCA: PC1 84.2% but loadings tilt to high-vol
  assets (XRP 0.53, DOGE 0.52 vs BTC 0.30) → correlation PCA is the correct
  basis for cross-asset structure; covariance view just re-weights by vol.
- EWMA-vol-standardized returns (λ=0.94, DCC-style): PC1 **84.6%** → the
  comovement is genuine correlation, not volatility clustering.
- Vol-of-|r| PCA: PC1 79.2% → vol clustering is also a common factor.
- Serial correlation: Ljung-Box significant for BTC/ETH/SOL (acf₂ ≈ −0.05…−0.07,
  bid-ask-bounce scale). Small; noted per Tsay (high-frequency PCA caveat),
  immaterial for the correlation structure.
- Lag-1 cross-correlations ≤ ~0.05 → no exploitable 15m lead-lag in this
  sample (the designed lead-lag lane operates at seconds horizon — different
  object).

### Time-of-day

| Session (UTC) | n | PC1 % | mean \|ρ\| |
|---|---|---|---|
| US-ish 11–16 | 1446 | 85.2 | 0.814 |
| EU-ish 7–9 | 739 | 82.6 | 0.782 |
| Asia 0,23 | 766 | 80.8 | 0.760 |

Correlations are moderately higher in US hours — consistent with heavier
institutional flow integrating the complex.

### Rolling-window regime diagnostics (the important part)

| Window | PC1 share range | u₁ stability \|cos\| |
|---|---|---|
| 500 obs / step 100 (26 windows) | **75.7% → 89.2%** | 1.000 (perfect) |
| 1000 obs / step 200 (11 windows) | 79.0% → 87.9% | 1.000 |

Per-month mean \|ρ\|: Jul 0.746 → Aug 0.730 → Sep 0.817 → Oct 0.839 →
**Nov 0.871**. First-half vs second-half mean \|ρ\|: 0.612 → 0.672.

**The factor structure is stable in direction (same eigenvector all along)
but the market is integrating: pairwise correlations have risen ~15–20%
across the sample.** This is the classic pre-/early-stage correlation-creep
regime documented in the RMT literature (leading-eigenvalue share rises as
diversification breaks down). At the current trajectory the universe is
converging toward a single-factor bet.

---

## 3. PCA — strategy settlement P&L (system layer)

Daily realized P&L per asset, keyed by **market date** (correcting the
`event_ts` bulk-ingestion artifact — see Issue D): 125 active days.

| PC | Var % | Loadings |
|---|---|---|
| PC1 | **63.3** | broad factor: DOGE −0.49, XRP −0.49, ETH −0.48, SOL −0.46, **BTC only −0.27** |
| PC2 | **18.1** | near-pure BTC contrast: BTC −0.90 vs SOL +0.36 |
| PC3–5 | 7.1 / 6.0 / 5.5 | residual structure |

- Parallel analysis: only PC1 > null-95 (T=125 is thin — treat PC2 as
  economically real but statistically unconfirmed).
- PR = 2.25, **ENCB ≈ 3.1** → roughly 2–3 effective P&L bets, not 5.
- Weekly aggregation (20 weeks): PC1 74.8%, PC2 18.6%; correlation structure
  similar (BTC least correlated: 0.17–0.49 vs alts 0.78–0.93).
- Winsorized daily P&L: spectrum unchanged (63.8/16.7) → robust.
- Sub-period: Jun–Aug spectrum [63.5, 20.1, 7.3…] vs Sep–Nov
  **[38.9, 22.9, 18.6, 11.1, 8.6]** — the P&L factor structure **flattened**
  recently (less single-factor dominance), opposite direction to the
  return-side correlation creep. Divergence worth monitoring.
- Per-asset win rate (settlement pnl > 0): BTC 31.4%, ETH 34.9%, DOGE 36.6%,
  SOL 34.0%, XRP 33.3%.
- Total settlement-attributed P&L: **−84,331c (−$843)** over the window;
  worst days cluster in Jul–Aug (Jul-21 −6,398c; Aug-25/26/27 ≈ −6,196 /
  −5,875 / −3,947c).

### Cross-layer linkage

- Daily total P&L vs daily mean market return: **corr = 0.08** — the system's
  daily P&L is essentially uncorrelated with market-factor direction. Losses
  are not a simple long/short-factor bet day-by-day; they look like a
  persistent negative carry (fees + calibration), worse on quiet days
  (high-|mkt| −474c/day vs low −961c/day).
- Mechanism check (2,323 entries): in the 479 market windows where ≥2 assets
  were entered, **314 (65%) took the same side on every asset**; only 5/240
  side-populated settlement windows were mixed. Entry side mix overall:
  **NO 62% / YES 38%**, NO-heavy on every asset (56–67%).

---

## 4. Issues discovered → researched solutions

### Issue A — Effective diversification is ~2 bets, and shrinking
PC1 = 84% of return variance, ENCB ≈ 1.9, all asset betas ≈ −0.9, and
correlations are still rising (Nov mean |ρ| = 0.871). The "5-asset"
allocation is closer to 1.4–1.9 independent bets and trending toward 1.

*Research basis:* eigenvalue-ratio / leading-eigenvalue crisis indicators
(RMT literature — sharp λ1 rise precedes diversification breakdown);
effective-number-of-bets risk budgeting; DCC-EWMA for time-varying
correlation; factor-exposure limits.

*Recommended solutions:*
1. **Instrument ENCB/PC1-share as a first-class risk metric.** Emit a
   structured telemetry field (rolling 500-obs PC1 share + ENCB) each cycle;
   alert/hate when ENCB < ~1.5 or PC1 share > ~90%. This is cheap — the
   correlation matrix is 5×5.
2. **Cap factor exposure, not just asset count.** Aggregate positions should
   be limited by net PC1-beta (Σ wᵢ·βᵢ) and by same-window same-side count —
   today 65% of multi-asset windows are same-side, so per-asset limits
   understate concentration ~5×.
3. **Prefer BTC for marginal diversification** (lowest market correlation,
   lowest P&L PC1 loading −0.27 vs alts ≈ −0.48). If adding capacity, BTC
   adds more independent risk than another alt.
4. If any gate consumes a covariance/correlation matrix, use **EWMA (DCC)
   estimation**, not a static/full-sample matrix — the structure is provably
   time-varying.

### Issue B — P&L factor structure is unstable and only ~3 effective bets
Daily-P&L spectrum flattened Sep–Nov (PC1 63%→39%) while return correlations
rose — the strategy's realized P&L is not simply tracking the return factor;
small samples (125 days) make eigen-estimates noisy.

*Research basis:* covariance-estimation error at small T/N (Ledoit-Wolf
shrinkage, nonlinear shrinkage); overlapping/weekly aggregation; block
bootstrap for eigenvalue uncertainty.

*Recommended solutions:*
1. Estimate the P&L correlation on **weekly or overlapping windows** and
   apply Ledoit-Wolf shrinkage before eigendecomposition; report bootstrap
   CIs on eigenvalue shares before acting on PC2/PC3.
2. Lengthen the settlement history (see Issue E) — 125 daily points is the
   binding constraint on all P&L-factor inference.
3. Track P&L PCs alongside return PCs as a divergence monitor: when the two
   spectra decouple, the lane mix (not the market) is driving outcomes.

### Issue C — Structural side concentration (62% NO, 65% same-side windows)
The entry stream is directionally synchronized across assets. Whatever the
model believes per-asset, the book-level bet is largely "crypto down-ish"
via NO contracts — a hidden short-vol/short-factor posture that the
per-asset gates cannot see.

*Research basis:* portfolio-level vs instrument-level risk (Euler risk
decomposition, component-vs-book covariance); factor budgeting.

*Recommended solutions:*
1. Add a **cross-asset window net-exposure gate**: cap total same-side
   notional per market window (or per factor-sign) across all five assets —
   the natural place is beside the existing shared daily budget
   (`MERID_PINNED_FAV` 480/day pattern).
2. Report aggregate **NO−YES delta** per window in telemetry; a sustained
   |delta| near 100% is a regime the per-asset moneyness caps were never
   audited against.
3. The existing lane budgets already bound count; extend the same pattern to
   factor exposure (net PC1-beta cap per window/day).

### Issue D — Settlement `event_ts` is ingestion time, not market time
The first attribution day (2026-08-29) bulk-recorded ~87% of all historical
losses (−73.8k of −84.3k cents) with June/July ticker dates. Any analysis
keyed on `event_ts` produces a spurious ~0.996 cross-asset P&L correlation
— an artifact, not a finding. Market-date keying is required.

*Recommended solutions:*
1. Persist **market timestamp** (parsed from ticker or `close_ts`) as a
   first-class column on settlement events; backfill where null.
2. Add a data-quality check to the existing provenance audits: flag any
   settlement batch whose `event_ts` − market-time exceeds a threshold.

### Issue E — Historical data coverage is sparse and session-selected
RTI backfill covers only ~29% of 15m buckets, clustered in specific UTC
hours (the windows the system actually traded/audited); live ticks retain
~10 days and have a daily 03:00–07:00 UTC gap; `decision_audit.db` holds
only ~4 days (archives exist back to September); book archives are ~1 day
each and `live2` is malformed.

*Consequences for PCA:* the return sample over-represents traded sessions —
fine for "what the system experiences" inference, biased for unconditional
market-structure claims. P&L-factor inference is T-limited.

*Recommended solutions:*
1. Schedule **systematic RTI backfill** (e.g., nightly pull of the prior
   day's full 24h for all five indexes) so coverage stops tracking activity.
2. Extend `cf_rti_ticks` retention or land it in the backfill store before
   rotation; the 03–07 UTC gap should be confirmed as a venue/market-hours
   fact vs a collector bug.
3. Repair or retire `kalshi_book_archive_live2.db` (malformed image).
4. If contract-price PCA is wanted later, the book archiver needs ≥2 weeks
   retention and a snapshot+deltareconstructor pass (`orderbook_reconstructor.py`
   exists) — currently infeasible at useful T.

### Issue F — Feature-level PCA not supported by durable data
`signals.db` features are sentiment-domain, not the 15m model's
microstructure inputs; `FeatureSnapshot` is in-memory only and audit
snapshots carry ~10 fields. A model-input PCA (multicollinearity diagnostic)
was therefore not possible from durable stores.

*Recommended solution:* if input-redundancy analysis is wanted, persist a
weekly sample of `FeatureSnapshot` vectors (or add a `feature_pca` rollup to
the decision audit) — cheap insurance before the feature set grows.

---

## 5. Caveats

- Settlement P&L attribution includes market outcomes that may not all map
  to live orders (only 256/3,759 carry `intent_id`); the P&L factor structure
  is therefore "system-attributed outcomes," which is the right object for
  strategy-level PCA but should not be read as exchange-verified P&L only.
- Returns are computed inside contiguous covered runs only; session-boundary
  returns are excluded by construction (avoids stale-price artifacts).
- Parallel analysis at T=125 (P&L) is low-power; PC2/PC3 should be treated as
  suggestive. Return-side results (T=3077) are high-confidence.
- PCA is a second-moment tool: it does not capture tail dependence. Crypto
  joint-tail risk (all assets crashing together) is *underestimated* by
  correlation PCA — worth a complementary extreme-value check if tail risk
  is a concern.

## 6. Bottom line

The system's market layer is a **one-factor complex getting more integrated
over time** (PC1 84%, ENCB ~1.9, correlations +15–20% across the sample).
The strategy layer converts that into **~2–3 effective P&L bets**, executed
with a structural NO tilt and 65% same-side multi-asset windows — real
diversification is materially below what "5 assets" suggests. Priorities:
(1) instrument ENCB/PC1-share + net factor exposure as risk metrics;
(2) fix settlement market-time provenance; (3) de-bias RTI coverage; (4)
treat P&L-factor estimates as provisional until history lengthens.
