# MERID Reward Design Blueprint

_Last updated: 2026-01-17_

Reward design is how MERID “programs” emergent swarm behavior. This blueprint
codifies the local+global reward structure, CRM evaluator set, logging schema,
visualization hooks, and governance requirements needed to keep trading, risk,
marketing, and governance swarms transparent, auditable, and aligned.

---

## 1. Reward Architecture Overview

```
┌───────────────────────────────────────────────────────────┐
│ Natural-language spec (ReMAC-style bootstrapping)         │
├───────────────────────────────────────────────────────────┤
│ Reward compiler (LLM assisted) -> Agent + Team reward fns │
├───────────────────────────────────────────────────────────┤
│ Collaborative Reward Modeling (CRM) evaluators            │
│  • Risk evaluator                                         │
│  • Compliance evaluator                                   │
│  • Explainability evaluator                               │
│  • Performance evaluator (PnL/ARR/latency)                │
│  • UX/Stakeholder satisfaction evaluator                  │
│  • Collaboration/coverage evaluator                       │
├───────────────────────────────────────────────────────────┤
│ Reward aggregator                                         │
│  R_i = α_i * R_local,i + (1 - α_i) * R_team               │
│  + evaluator committee scores (vector logging)            │
├───────────────────────────────────────────────────────────┤
│ Telemetry & governance                                    │
│  • Reward vector logging                                  │
│  • Rationales per dimension                               │
│  • Coverage dashboards & policy enforcement               │
└───────────────────────────────────────────────────────────┘
```

- **Bootstrapping**: ReMAC-style process turns governance specs into reward
  functions with explicit terms. Humans review + check into `core/rewards.py`.
- **Ongoing evaluation**: CRM evaluators (risk, compliance, explainability, UX)
  run every decision/cycle and emit interpretable scores + rationales.

---

## 2. Local + Global Reward Formulation

For agent _i_:

```
R_i = α_i * R_local,i + (1 - α_i) * R_team
```

- α_i tuned per role:
  - Execution/bots (trading, x-bot endpoints): α ≈ 0.7 (strong local feedback).
  - Strategy orchestrators / marketing directors: α ≈ 0.3 (team-aligned).
  - Governance agents: α ≈ 0.5 but local penalties dominate on violations.

### 2.1 Difference Rewards / Counterfactuals

- For credit assignment, compute difference rewards (team with vs. without
  agent’s action) using simulation/backtest harnesses.
- Example: simulate trade without social confirmation to estimate marginal risk.

### 2.2 Shaping & Constraints

- Add explicit negative rewards for:
  - Risk breaches / limit hits.
  - Missing `DecisionRationale` (explainability violation).
  - Compliance failures (content, jurisdiction, disclosure).
- Lexicographic dominance for hard constraints: if compliance fails, total
  reward set to zero regardless of performance gains.

---

## 3. CRM Evaluator Set

| Evaluator | Domain Coverage | Signals | Output Schema |
| --- | --- | --- | --- |
| Risk Evaluator | Trading, treasury, arbitrage, marketing spend | VaR, drawdown, liquidity, exposure, risk buffers | `{dimension: "risk", score, reason, rules_fired}` |
| Compliance Evaluator | Governance, marketing, comms | Policy checks, jurisdictional rules, audit trail completeness | `{dimension: "compliance", ...}` |
| Explainability Evaluator | All swarms | Coverage of `DecisionRationale`, latency, clarity, counterfactual presence | `{dimension: "explainability", ...}` |
| Performance Evaluator | Trading PnL, marketing ARR, observability SLOs | PnL, ARR, latency, MTTR, conversions | `{dimension: "performance", ...}` |
| UX/Stakeholder Evaluator | Operator experience, client satisfaction | NPS, incident reports, support tickets, manual overrides | `{dimension: "ux", ...}` |
| Collaboration/Coverage Evaluator | Inter-swarm handoffs | Data freshness, documentation, reward reporting coverage | `{dimension: "collaboration", ...}` |

- Each evaluator outputs score (0-1), rationale string, and `rules_fired`.
- Aggregator stores entire vector and rationales.
- Missing evaluator output = policy violation (alerts + block).

---

## 4. Logging Schema

### 4.1 Reward Vector Record

Stored in `analytics/rewards/records/{date}/{domain}.jsonl` and streamed to
observability/governance dashboards.

```json
{
  "decision_id": "trade-20260117-001",
  "agent_id": "executor-04",
  "team_id": "trading_swarm_alpha",
  "domain": "trading",
  "alpha": 0.65,
  "local_reward": 0.82,
  "team_reward": 0.74,
  "composite_reward": 0.79,
  "reward_terms": [
    {"dimension": "performance", "score": 0.88, "reason": "+PnL 45bps", "rules_fired": ["PnL-Bound"]},
    {"dimension": "risk", "score": 0.91, "reason": "VaR under limit", "rules_fired": ["VAR-95"]},
    {"dimension": "compliance", "score": 1.0, "reason": "All disclosures included", "rules_fired": ["KYC-3"]},
    {"dimension": "explainability", "score": 0.85, "reason": "Rationale recorded <2s", "rules_fired": ["XAI-coverage"]},
    {"dimension": "ux", "score": 0.7, "reason": "Operator feedback good", "rules_fired": []},
    {"dimension": "collaboration", "score": 0.66, "reason": "Data handoff delayed", "rules_fired": ["handoff-lag"]}
  ],
  "lexicographic_failures": [],
  "counterfactual_baseline": {
    "team_reward_without_agent": 0.68,
    "notes": "Agent improved slippage"},
  "explainability_record_id": "expl_00001234",
  "timestamp": "2026-01-17T19:20:11Z"
}
```

### 4.2 Rationales

- Each `reward_terms` entry includes `reason` + `rules_fired` for dashboards.
- Link to `ExplainabilityService` record via `explainability_record_id`.
- Telemetry stream: `governance` or `strategy` with event type `reward_vector`.

---

## 5. Visualization & Thresholds

- **Merid-UI panels**:
  - Stacked bar per decision showing reward components.
  - Threshold markers (risk ≥ 0.7, explainability ≥ 0.8) w/ redline when violated.
  - Coverage heatmaps by swarm/domain.
- **Alerting**:
  - If any lexicographic constraint triggered, show incident banner.
  - Reward coverage < 95% triggers governance alert.
- **Drill-down**: click reward component → view evaluator rationale + telemetry
  trace + DecisionRationale.

---

## 6. Governance & Integration Hooks

1. **CI Enforcement** – tests ensure new agents report reward vectors + link to
   explainability records. Missing fields fail CI.
2. **Observability Integration** – `observability/observability_stack` ingests
   reward events, exposes metrics (coverage, average component scores, latency).
3. **Docs Linkage** – reference this file from `MERID_REWARD_AND_AGENCY_CHARTER.md`
   and `OBSERVABILITY_REQUIREMENTS_COMPLIANCE.md`.
4. **Sentience Framing** – UI copy includes disclaimers: “Decisions optimize
   explicit reward terms; agents are optimization policies, not sentient beings.”
5. **Governance Overrides** – incident workflows require referencing both reward
   vectors and explanation records before approval/resolution.

---

## 7. Implementation Checklist

- [ ] Create `core/rewards.py` utilities for α weights, evaluator registration,
      vector serialization, and lexicographic checks.
- [ ] Build evaluator services (risk/compliance/XAI/UX) under `governance/` or
      `analytics/` with stable APIs.
- [ ] Update trading, swarm, marketing orchestrators to produce reward vectors
      per decision/run.
- [ ] Extend observability dashboards + APIs to visualize reward components.
- [ ] Add operator UX copy clarifying non-sentience + reward structure.
- [ ] Run simulations/backtests measuring emergent behavior vs α weights.

---

## 8. Future Work

1. **Automated weight tuning** – use Bayesian optimization / governance motions
   to adjust α and evaluator weights with audit trail.
2. **Reward quality audits** – dedicate an Explainability/Reward watchdog swarm
   to spot drifts or reward hacking attempts.
3. **Cross-domain alignment tests** – nightly harness comparing marketing reward
   vectors vs risk constraints to prevent conflicting incentives.
4. **External assurance** – build exports for third-party compliance auditors.

---

## 9. Agent vs Team Reward Trade-offs & Failure Modes

| Reward Scheme | Strengths | Failure Modes | MERID Examples |
| --- | --- | --- | --- |
| Agent-only | Fast learning on local metrics; easy credit assignment | Agents compete/ignore externalities; selfish SDRs booking junk meetings; executors chasing fill rate over risk | Social SDR optimizing meetings regardless of risk/compliance; marketing copy bot spamming inaccurate offers |
| Team-only | Enforces cooperation through single objective | Credit assignment collapse; free-riding; single leader emerges and others stall | Risk swarm over-relies on one governor agent; trading agents coast while portfolio PnL drives reward |
| Combined (α-weighted) | Balances specialization + alignment; supports division of labor | α mis-specified → instability; if local constraints missing, agents exploit gaps | Execution α too low → agents ignore fill quality; marketing α too high → teams optimize ARR but drop explainability |

Failure scenarios to guard against:

1. **Mis-specified objectives** – missing compliance or explainability terms →
   reward hacking. Prevention: lexicographic penalties, CRM evaluators dedicated
   to safety/explainability.
2. **Sparse/delayed rewards** – only end-of-week PnL gives weak signal; add
   intermediate metrics (latency, coverage) and evaluators that score each
   decision.
3. **Unfair splits** – equal global reward share despite uneven work; use
   difference rewards/counterfactual baselines, and governance audits of reward
   vector distributions.
4. **Opaque scalars** – single RLHF score lacks interpretability; log reward
   vectors + evaluator rationales to keep governance in the loop.

---

## 10. ReMAC + CRM Hybrid Implementation Plan

### 10.1 ReMAC-style Bootstrapping

1. **Prompt library** – maintain governance-approved prompts describing trading,
   marketing, observability missions; feed to LLM reward compiler.
2. **Reward population** – auto-generate multiple candidate reward functions per
   domain (agent + team levels). Track metadata (prompt hash, version) under
   `rewards/specs/`.
3. **Evaluation harness** – run agents in simulation/backtest (e.g., ManiCraft
   analogs for trading/backtesting, marketing funnel sims) and score each reward
   population on skill/individual/team metrics.
4. **Selection + human review** – surface top-performing reward candidates for
   risk/governance sign-off before promotion to prod.

### 10.2 CRM-style Evaluator Layer

1. **Evaluator services** – implement risk/compliance/explainability/UX
   evaluators as FastAPI or gRPC services under `analytics/` or `governance/`.
2. **Structured traces** – feed evaluators rich context (`DecisionRationale`,
   telemetry spans, reward logs) so they can reason on `<think>`, `<answer>`
   style traces or execution logs.
3. **Aggregator** – weighting config stored in governance registry; aggregator
   outputs both scalar (for RL updates) and vector (for logging).
4. **Feedback loop** – evaluators produce rationales; explainability + reward
   dashboards highlight when components degrade, triggering prompt/weight
   updates.

### 10.3 Governance & Explainability Hooks

- ReMAC-generated rewards cannot deploy until CRM evaluators achieve coverage ≥
  95% per decision.
- Reward vector + evaluator rationale IDs attach to every `DecisionRationale`
  record so governance can replay “why this reward changed.”
- Observability alerts fire when:
  - α weights deviate from approved bounds.
  - Evaluator latency exceeds thresholds (risk of stale scoring).
  - Lexicographic constraints triggered > X times/day.

### 10.4 Adoption Checklist

1. Build prompt catalog + reward compiler workflows (scripts/CI).
2. Stand up evaluator services + aggregator pipeline.
3. Update swarm orchestrators to consume ReMAC-generated reward configs and emit
   CRM-scored vectors.
4. Extend `docs/MERID_REWARD_AND_AGENCY_CHARTER.md` to reference this hybrid
   stack (link section).
5. Train operators on interpreting reward dashboards and rationales; update UI
   copy to reiterate non-sentience and reward-driven behavior.

---

## 11. Implications for MERID Swarms

### 11.1 Agent-only Rewards

- **Behavior** – fast individual learning, but agents optimize their siloed KPI
  (fill quality, email CTR) regardless of portfolio risk, ARR quality, or
  explainability coverage.
- **Failure Modes** – SDR agents book unqualified meetings to inflate local
  reward; execution bots chase fill rate and ignore slippage or kill switches;
  research agents overfit to novelty metrics and burn compute budgets.
- **Governance Impact** – limited auditability: local metrics show success even
  as team performance degrades, forcing manual overrides. Explainability suffers
  because reasons reference only local goals.
- **Mitigation** – only acceptable for sandbox/skill-training phases with tight
  ceilings. In production, agent-only rewards must be wrapped with enforcement:
  lexicographic penalties and CRM evaluators to keep behaviors within guardrails.

### 11.2 Team-only Rewards

- **Behavior** – strong cooperation incentive (everyone shares Sharpe or ARR),
  but credit assignment collapses. Agents can free-ride, waiting for others to
  carry the team, or collapse into a single “leader” agent controlling most
  actions.
- **Failure Modes** – trading swarm devolves into one dominant strategy agent;
  supporting agents idle because they can’t detect their marginal contribution.
  Marketing swarm spams broad campaigns because ARR is all that matters; no
  signal for content accuracy or compliance.
- **Governance Impact** – debugging becomes near-impossible: a bad outcome only
  produces a scalar loss without pointing to the responsible agent. Training is
  unstable because gradients are noisy and delayed (weekly PnL, monthly ARR).
- **Mitigation** – introduce counterfactual/difference rewards and telemetry
  traces so governance can attribute responsibility. Prefer combined rewards.

### 11.3 Combined (α-weighted) Rewards

- **Behavior** – agents specialize (local rewards) yet stay aligned (team term).
  Division of labor emerges: research agents maximize signal quality, execution
  agents optimize fills within risk limits, marketing agents balance lead quality
  with ARR.
- **Design Considerations** – α tuning per role, plus explicit inter-agent
  constraints in team rewards (risk, compliance, explainability coverage). If α
  mis-set or constraints missing, agents exploit slack (e.g., low α on executors
  → no incentive to maintain local discipline; high α on marketing orchestrators
  → ignore team guardrails).
- **Explainability** – reward vectors show how local and team components combine;
  DecisionRationale references both, improving operator trust without implying
  sentience (“agent optimized for risk-adjusted PnL subject to coverage ≥0.8”).
- **Governance Impact** – combined rewards integrate smoothly with CRM
  evaluators and observability dashboards, enabling alerts when either local or
  team dimensions drift. This is MERID’s default operating mode.
