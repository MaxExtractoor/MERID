# MERID Simulation Hardening Checklist

_Last updated: 2026-01-18_

This checklist turns the simulation layer into a “hostile but faithful twin” of live MERID. Use it before promoting any swarm/strategy and when running regression sims.

---

## 1. Market Realism & Microstructure

- [ ] **Live parity data**: Simulation feed uses live tick/depth snapshots or recorded streams with intact timestamps, fees, and venue-specific rules.
- [ ] **Order book mechanics**: Partial fills, queue priority, cancel/replace latency, maker/taker fees, rebates, and funding rates mirrored per venue.
- [ ] **Margin & liquidation**: Perp/derivatives leverage, maintenance margin, auto-deleveraging paths identical to venue documentation.
- [ ] **Venue quirks**: Lot sizes, price bands, circuit breakers, auction opens/closes modeled.
- [ ] **Latency modeling**: Inject configurable baseline latency plus jitter distributions per venue/region.
- [ ] **Network fault injection**: Scenario hooks for packet loss, quote staleness, disconnects, and delayed cancel/ack loops.

## 2. Scenario & Adversarial Coverage

- [ ] **Scenario catalog** populated with at least: normal regime, high volatility spike, gap open, regime shift, broken feed, adversarial spoofing, prompt-injection events, malformed market data.
- [ ] **Stress matrix**: Automated runs combining shocks (e.g., latency + vol + illiquidity) across multiple horizons.
- [ ] **Boundary sweeps**: Tests hitting max leverage, max order size, extreme spreads, near-zero liquidity, negative net funding.
- [ ] **Adversarial LLM inputs**: Prompt injection/semantic attacks to ensure swarms/guards resist manipulation in sim.
- [ ] **Scenario rotation**: Randomized ordering and periodic refresh (e.g., weekly) to avoid overfitting.

## 3. Contracts with Swarms, Guardrails, Reflection

- [ ] **Unified APIs**: Simulation uses the exact same execution, guardrail, explainability, and reflection interfaces as live (no bypasses).
- [ ] **Policy parity**: All guardrails, authority checks, and Reality Gate logic run in sim and emit the same events/logs.
- [ ] **Ghost/Shadow swarms**: Mirror live decisions in sim (ghost mode) and log hypothetical PnL, risk, guardrail hits alongside live outcomes.
- [ ] **Reflection hooks**: Sim failures generate structured reflection events, updating playbooks before live deployment.

## 4. Observability & Promotion Gates

- [ ] **Telemetry bundle**: For every run, emit metrics for PnL, slippage, fill ratio, latency distribution, guardrail counts, risk breaches (sim vs live).
- [ ] **Full traceability**: Persist decision traces (inputs, prompts, responses, guardrail verdicts) for replay.
- [ ] **Promotion criteria dashboard** covering:
  - Scenarios passed/failed
  - Max drawdown & VAR vs limits
  - Guardrail violation counts (must be zero for promotion)
  - Reflection effectiveness (issues resolved)
- [ ] **Promotion gates enforced**: Strategy cannot advance from sim→paper→guarded_live→full_live without satisfying thresholds.
- [ ] **Failure incidents**: Sim regressions logged as incidents; remediation tracked before re-run.

## 5. Anti-Overfitting & Robustness

- [ ] **Cross-regime validation**: Run sims across multiple historical windows (bull, bear, sideways) + synthetic regimes.
- [ ] **Baseline comparisons**: Measure against naive baseline strategies (buy/hold, TWAP) to ensure meaningful uplift.
- [ ] **Randomization / noise**: Inject parameter jitters, random order of scenarios, noise to inputs (prices, latencies) to test stability.
- [ ] **Robustness stats**: Track variance of outcomes over randomized runs; flag strategies with high sensitivity.

## 6. Compliance & Reporting

- [ ] **Explainability bundle**: Each sim run produces explainability records compatible with governance/board reporting.
- [ ] **Audit log**: Append-only log of sim runs, triggers, outcomes, promotion decisions, and responsible reviewers.
- [ ] **Integration with reflection metrics**: Sim guardrail hits and hallucination regressions feed into reflection decay dashboards.

---

### Usage

1. Before promotion, run the entire checklist; sign off in readiness tracker.
2. For regression campaigns, select relevant subsets (e.g., only scenario coverage + observability) but always log results.
3. Store completed checklists in `docs/simulation_runs/<date>/<strategy>.md` with links to telemetry dashboards and reflection IDs.

Failure to satisfy any “hard gate” (market realism parity, policy parity, guardrail violations) blocks promotion until resolved.
