# Intraday Walk-Forward Optimization (WFO) Guide

_Last updated: 2026-01-18_

This guide defines rigor for MERID’s intraday WFO pipelines: window sizing, trade-count thresholds, regime detection, and Sharpe/MinTRL handling for high-frequency equity strategies.

---

## 1. Trade Count Targets per Window

- **Minimum viable trades**: < 30 trades per IS window yields extremely noisy Sharpe/drawdown estimates. Target ≥ 50 trades, with ≥ 100 preferred when edge is modest or autocorrelation is high.
- **Sharpe-based confidence**:
  - Use Probabilistic Sharpe Ratio (PSR) and Minimum Track Record Length (MinTRL) to confirm the observed Sharpe exceeds hurdle `c` at 95% confidence.
  - Ensure each IS/OOS window meets the larger of (a) 50-trade heuristic and (b) `MinTRL(c)` observations (adjusted for autocorrelation, see §6).
- **Adaptive window sizing**:
  - If the strategy trades less frequently than the bar interval (e.g., rare signals on 1-minute data), extend IS length until trade counts thresholds are satisfied.

---

## 2. Window Length Recommendations

| Strategy Type | IS Window | OOS Window | Notes |
| --- | --- | --- | --- |
| **1-minute bars** | 1–3 months (active sessions) or until ≥100 trades | 5–10 trading days (≥20 trades) | Shorter windows acceptable if trade density is very high; extend IS for sparse traders. |
| **5-minute bars** | 3–6 months or until ≥100 trades | 10–20 trading days | Longer IS required due to fewer trades per day. |
| **Slower intraday (≤2 trades/day)** | 6–12 months | ≥1 month | Must hit trade-count thresholds; consider coarser bars if signals truly slow. |

- Always express IS/OOS both in calendar time and trade counts to ensure MinTRL is satisfied.

---

## 3. Regime Awareness

1. **Feature monitoring**
   - Track rolling realized volatility, spreads, depth, intraday volume profiles, and order-book imbalance.
   - Use change-point detection (CUSUM, variance tests) to flag structural breaks.
2. **Model-based detection**
   - Optional: Hidden Markov Models, regime-switching GARCH, or clustering daily features to label regimes.
3. **Response**
   - When regime-shift scores exceed thresholds, restart WFO with fresh IS windows or shorten OOS to revalidate faster.

---

## 4. OOS Hold & Step Size Rules

- **Length**: For most intraday strategies, OOS = 1–4 weeks, ensuring ≥20–50 trades. Very high-frequency strategies (thousands of trades/week) may use 3–5 trading days.
- **Step size**: Default to stepping forward by OOS length (non-overlapping OOS). For highly non-stationary edges, step at half OOS (overlapping) to improve responsiveness.
- **Evaluation**: Each OOS slice must record Sharpe, PSR, drawdown, risk metrics, guardrail events, and reflection outcomes before re-optimization.

---

## 5. Sharpe Significance: PSR & MinTRL

### 5.1 Probabilistic Sharpe Ratio (PSR)

For sample Sharpe `SR_hat`, skew `kappa_hat`, kurtosis `gamma_hat`, sample size `T`, reference Sharpe `c`:

```
PSR(c) = Phi( (SR_hat - c) / sqrt((1 - kappa_hat*SR_hat + (gamma_hat - 1)*(SR_hat**2)/4)/T) )
```

`Phi` = standard normal CDF. Require `PSR(0) >= 0.95` on stitched OOS before promotion.

### 5.2 Minimum Track Record Length (MinTRL)

```
MinTRL(c) = (1 - kappa_hat*SR_hat + (gamma_hat - 1)*(SR_hat**2)/4) * (z_(1-alpha)/(SR_hat - c))**2
```

- `z_(1-alpha)` ≈ 1.645 for 95% one-sided confidence.
- Use MinTRL to size IS windows in number of observations (trades or bars).
- Plug annualized Sharpe & hurdle `c` expressed on same horizon.

---

## 6. Autocorrelation & Effective Sample Size

- **Effective sample size**: `T_eff = T / (1 + 2*sum_{k=1}^K rho_k)`
  - Estimate autocorrelations `rho_k` up to cutoff `K` (e.g., where values drop below noise).
  - Use `T_eff` in PSR/MinTRL calculations.
- **AR(1) approximation**: For lag-1 autocorrelation `phi`, `T_eff ≈ T * (1 - phi)/(1 + phi)`.
- **Newey–West Sharpe SE**: Compute HAC variance for mean returns and divide by sample volatility to get autocorrelation-robust Sharpe SE; use this SE in PSR/MinTRL denominators if you prefer.

---

## 7. Frequency Comparison (1m vs 5m)

1. Compute per-bar return series at both 1-minute and 5-minute sampling.
2. For each frequency:
   - Estimate `SR_hat`, `kappa_hat`, `gamma_hat`, autocorrelations, and `T_eff`.
   - Evaluate `MinTRL` and `PSR` with `T_eff`.
3. Favor the sampling frequency that provides higher `PSR` / lower `MinTRL` for the same calendar span while meeting trade-count realism. Sometimes 5-minute bars reduce autocorrelation enough to require fewer observations than noisy 1-minute data.

---

## 8. WFO Automation Checklist

- [ ] Implement rolling WFO with IS/OOS/step parameters per strategy class.
- [ ] Enforce trade-count minima per window using MinTRL logic.
- [ ] Capture regime metrics and trigger reinitialization on regime shifts.
- [ ] After each OOS window:
  - Compute Sharpe, PSR, drawdown, guardrail hits.
  - Log reflection event summarizing outcomes and next actions.
- [ ] Store parameter selections per window for stability analysis (large swings imply overfitting/regime drift).
- [ ] Integrate PSR/MinTRL outputs into promotion dashboards alongside PBO/DSR metrics.

---

## 9. References

- Probabilistic Sharpe Ratio & MinTRL: PortfolioOptimizer, López de Prado, QuantConnect research notes.
- Intraday WFO heuristics: AlgoTrading101, Reddit/Quant forums, StrategyQuant documentation.
- Regime detection: volatility regime-switching literature, change-point detection methods.

This guide should be cited in strategy hypothesis docs and enforced by the simulation + research tooling before any intraday strategy advances beyond the research phase.
