# MERID Anti-Overfitting Protocol

_Last updated: 2026-01-18_

This protocol codifies defensive measures against overfitting in MERID’s research, simulation, and promotion pipeline. It is mandatory for any strategy/simulation stack feeding swarms or guardrails.

---

## 1. Data Splitting & Walk-Forward Discipline

1. **Chronological splits**
   - Use strict time-based train (in-sample, IS), validation (model selection), and holdout (final confirmation) sets.
   - Never tune on the final holdout; check it only when a major strategy version is finalized.
2. **Walk-forward optimization (WFO)**
   - Rolling windows: IS window (e.g., 24 months) → optimize → freeze parameters → run on next OOS window (e.g., 3 months) → slide forward by OOS length.
   - Stitched OOS curve is the only performance accepted for promotion decisions.
3. **Multiple horizon support**
   - Daily/monthly strategies: IS 2–5 years, OOS 3–6 months.
   - Intraday strategies: IS 3–9 months, OOS 2–4 weeks.
4. **Holdout policy**
   - Maintain a final holdout (e.g., last 6 months) untouched until a strategy is ready for paper/live; log each holdout use.

---

## 2. Complexity Control & Search Accounting

1. **Feature discipline**
   - Limit indicators/features per strategy; require economic or microstructure rationale documented in the hypothesis.
   - Reject “mystery” features that cannot be justified without referencing the backtest.
2. **Parameter grids**
   - Coarse, economically grounded ranges only; avoid ultra-fine grids.
   - Max 3 simultaneously tuned parameters unless explicitly approved.
3. **Multiple testing corrections**
   - Track number of parameter/model trials.
   - Apply Deflated Sharpe Ratio (DSR), White’s Reality Check / SPA, and Probability of Backtest Overfitting (PBO) to adjust performance claims.
4. **Promotion thresholds**
   - Require DSR ≥ 0.6, PBO ≤ 0.4, Reality Check/SPA p-value ≤ 0.1 before any sim→paper promotion.

---

## 3. Robustness, Stress, and Monte Carlo

1. **Scenario sweeps**
   - Evaluate across bull, bear, sideways, high/low volatility, varying fee/slippage assumptions.
2. **Boundary tests**
   - Stress leverage, order size, illiquidity, and combined shocks (latency + volatility + liquidity) inside the simulation layer.
3. **Monte Carlo / bootstrap**
   - Use trade/return block bootstrapping to produce distributions of KPI outcomes; record 5th/95th percentile metrics.
4. **Sensitivity analysis**
   - Jitter parameters ±10% and re-run to ensure performance does not collapse.

---

## 4. Bias Checks & Realism Requirements

1. **Transaction costs & liquidity**
   - Include realistic spreads, partial fills, fees, funding, and market impact consistent with venue data.
2. **Latency & execution**
   - Model order/execution latency, queue priority, cancellations, and venue outages in sim.
3. **Survivorship/look-ahead**
   - Use point-in-time datasets with delisted instruments; signals must only use data available at decision time.
4. **Data provenance**
   - Document data sources, ingestion timestamps, and QA checks; link to `data/` catalog entries.

---

## 5. Behavioral & Governance Practices

1. **Pre-registration**
   - Each strategy has a written hypothesis including rationale, feature set, IS/OOS plan, metrics, acceptable drawdowns, and rejection criteria.
   - Stored in `research/hypotheses/<strategy>.md`; updates require new version IDs.
2. **Experiment tracking**
   - All experiments logged with parameter sets, metrics, PBO/DSR results, and scenario outcomes.
3. **Baseline comparison**
   - Always compare to simple baselines (buy & hold, equal-weight, MA crossovers). No promotion if improvement vs baseline is < specified delta.
4. **Reflection integration**
   - Failed robustness/bias checks emit reflection events; playbooks updated before re-running.

---

## 6. Quantitative Tests Reference

| Test | Purpose | Implementation Notes |
| --- | --- | --- |
| Walk-forward OOS | Sequential validation | Rolling IS/OOS windows, aggregated OOS equity curve. |
| PBO | Probability of backtest overfitting | Use Bailey–López de Prado logit method on subperiod × variant performance matrix. |
| Deflated Sharpe Ratio | Adjust Sharpe for multiple trials & non-normality | Requires Sharpe variance, skew, kurtosis, trial count. |
| White’s Reality Check / SPA | Correct for data-snooping | Bootstrap max differential vs benchmark. |
| Monte Carlo bootstraps | Fragility assessment | Resample trades/returns; compute distribution of KPIs. |

All tests must be scripted (Python notebooks/scripts in `research/tests/`) and results committed alongside strategy reports.

---

## 7. Promotion Pipeline Integration

1. **Sim → Paper**
   - Requirements: WFO stitched OOS meets KPI thresholds, DSR ≥ 0.6, PBO ≤ 0.4, no critical guardrail hits in sim, bias checks passed.
2. **Paper → Guarded Live**
   - Additional: paper trading metrics within ±20% of sim benchmarks, reflection logs show resolved issues, incident-free run (>30 days).
3. **Guarded Live → Full Live**
   - Additional: guardrail compliance in production, live PnL within tolerance bands, human review sign-off.
4. **Regression triggers**
   - Any guardrail breach, reflection alert, or major market shift requires re-running the anti-overfitting protocol before re-promotion.

---

## 8. Responsibilities

- **Research**: Perform WFO, record experiments, run PBO/DSR/Reality Check, document hypotheses.
- **Simulation team**: Enforce realism, scenario coverage, stress testing, and observability logging.
- **Governance**: Verify documentation, audit bias checks, ensure promotion gates enforced.
- **Reflection/Telemetry**: Consume failure signals, update playbooks, and monitor decay of hallucination/overfitting metrics.

Non-compliance blocks promotion and must be noted in readiness reports.
