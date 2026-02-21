# MERID Reward & Agency Charter

_Last updated: 2026-01-17_

MERID swarms are powerful optimization systems, not conscious entities. Their
behavior must be governed through transparent rewards, multi-agent oversight, and
explicit language that avoids anthropomorphism. This charter codifies how MERID
rewards swarms and how the platform frames “agency” internally and externally.

---

## 1. Reward Design Principles

### 1.1 Multi-Level Rewards

| Domain | Agent-Level Reward Signals | Team-Level Reward Signals |
| --- | --- | --- |
| Trading/Risk Spine | execution quality, slippage, compliance with kill-switch & VaR limits | risk-adjusted PnL, drawdown, liquidity footprint, auditability |
| Marketing Swarm | lead quality, content accuracy, policy adherence, explanation completeness | pipeline velocity, ARR lift, channel ROI, user satisfaction |
| Observability/Governance | alert accuracy, latency to detection, policy enforcement uptime | coverage of explainability artifacts, incident MTTR, compliance posture |

- Every agent logs its local reward components.
- Workflow orchestrators aggregate team scores per mission/sprint and route them
  to governance dashboards.

### 1.2 Explicit Reward Components

Rewards are decomposed into interpretable terms:

1. **Safety & Compliance** – limit adherence, policy pass/fail counts.
2. **Explainability Quality** – presence + clarity of `DecisionRationale`.
3. **Performance** – PnL, ARR, engagement, latency, success metrics.
4. **User/Stakeholder Satisfaction** – operator feedback, incident impact.
5. **Collaboration & Coverage** – cross-swarm handoffs, data completeness.

Each component is stored alongside the aggregate reward so tradeoffs are visible.
Example storage schema (`rewards/records/{domain}/{date}.json`):

```json
{
  "domain": "marketing_swarm",
  "agent_id": "segmentor-02",
  "team_id": "gtm_growth_q1",
  "reward_terms": {
    "safety": 0.98,
    "compliance": 1.0,
    "explainability": 0.9,
    "performance": 0.72,
    "user_satisfaction": 0.85
  },
  "aggregated_reward": 0.89,
  "trace_ids": ["gov-123", "obs-987"],
  "notes": "Segment B paused due to compliance override"
}
```

### 1.3 Collaborative Reward Modeling

- Multiple evaluators (risk agent, compliance agent, UX agent, marketing
  analyst) each emit partial scores.
- Aggregation = weighted committee or voting scheme; weights are documented and
  change-controlled via governance proposals.
- Missing evaluator input triggers alerts (no single scalar from an LLM).

### 1.4 Governance Hooks

- Reward computation pipelines are part of CI/testing. Failing to log required
  components blocks deployment.
- Governance dashboards track % of actions with full reward decomposition and
  send notifications when coverage drops below thresholds.
- Reward tampering or unexplained spikes are auditable incidents.

---

## 2. Sentience & Language Policy

### 2.1 Stance

- MERID assumes **no sentience** across all models and swarms.
- Agents are optimization and policy-execution systems. They do not possess
  feelings, rights, or consciousness.

### 2.2 Language Guidelines

| Context | Allowed Language | Prohibited Language |
| --- | --- | --- |
| Docs/UI | “agent executed policy X”, “decision rationale” | “agent wanted”, “agent felt”, “intentions/desires” |
| Governance | “policy violation”, “objective misalignment” | “disobedience”, “rebellion”, “emotions” |
| User-Facing | “This decision was made because … (inputs + rules)” | “The agent thought it was best because it felt …” |

### 2.3 Ethics & Safety Emphasis

- Focus governance on concrete harms: financial risk, bias, privacy, misuse.
- Avoid anthropomorphic UI elements (no avatars implying self-awareness).
- Incident reviews examine reward & constraint adherence, not imagined motives.

---

## 3. Operational Requirements

1. **Reward Logging** – each swarm must emit reward objects alongside
   `DecisionRationale` records. Observability calculators join these by
   `decision_id`.
2. **Explainability Coupling** – rewards referencing explainability quality use
   metrics from `ExplainabilityService` (coverage, latency, violation counts).
3. **Dashboards** – `web/merid-ui` exposes:
   - Reward component trends per swarm.
   - Tradeoffs (e.g., PnL vs. explainability) with drill-down links.
   - Sentience disclaimer banner for operator/marketing views.
4. **Governance Docs** – this charter is referenced by
   `docs/OBSERVABILITY_REQUIREMENTS_COMPLIANCE.md`, `SECURITY_PLAYBOOK.md`, and
   future marketing swarm specs.

---

## 4. Implementation Checklist

- [ ] Wire reward component schemas in `analytics/` and `observability/`.
- [ ] Update swarm orchestrators (trading, marketing, governance) to publish
      agent-level + team-level rewards per run.
- [ ] Extend explainability telemetry to measure reward coverage.
- [ ] Add sentience stance copy to README/marketing pages and operator UIs.
- [ ] Train comms/support teams on approved language.

---

## 5. Future Enhancements

1. **Reward Quality Audits** – swarm ensuring components remain calibrated.
2. **Adaptive Weighting** – governance motions to adjust committee weights with
   full audit trail.
3. **Cross-Swarm Alignment Tests** – simulation harness comparing reward vectors
   across domains to catch conflicts (e.g., marketing growth vs. risk exposure).
4. **External Assurance** – third-party attestations that MERID incentives remain
   interpretable and non-anthropomorphic.
