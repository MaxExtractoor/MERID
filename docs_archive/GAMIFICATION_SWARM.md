# MERID Gamification Swarm Specification

## 1. Goals & Principles

- Turn real engineering outcomes (quality, reliability, governance) into transparent quests and rewards.
- Motivate both humans and autonomous agents without compromising safety guardrails.
- Use telemetry-driven scoring so incentives remain aligned with Meta-Audit requirements.
- Provide adaptive, personalized quests and feedback to sustain engagement without spam.

Guiding principles:

1. **Outcome-first** – tie XP/levels to impact (bugs prevented, coverage raised, governance adherence), not raw activity.
2. **Transparent & governed** – document scoring logic; log every reward calculation in Meta-Audit telemetry for auditability.
3. **Adaptive** – quests and rewards adapt to behavior, load, and risk tier; avoid burnout.
4. **Separation of duties** – gamification cannot override risk/guardrail decisions; it only rewards compliant behavior.

## 2. Reward Model

### 2.1 Reward dimensions

| Dimension | Indicators | Telemetry Sources |
| --- | --- | --- |
| Code Quality | Test coverage delta, mutation scores, defect density, rollback rate | CI coverage reports, mutmut, Meta-Audit incidents |
| Testing Robustness | Flaky tests fixed, high-value tests added, bugs caught in sim vs live | Test swarm telemetry, simulation harness logs |
| Governance Hygiene | Promotion compliance, docs completeness, incident response speed | MetaAuditRuntime, promotion pipeline, doc linting |
| Collaboration Velocity | Cross-role quest completion, dependency resolution time | Dev swarm orchestrator logs, quest tracker |

### 2.2 Gamified primitives

- **XP**: earned per completed bounty (small task), quest (multi-step), protocol (recurring maintenance). Weighted by impact + risk tier.
- **Levels/Titles**: progression tiers emphasizing reliability roles (e.g., L2 “Module Steward”, L3 “Sim Guardian”, L4 “Meta Auditor”).
- **Badges**: sustained accomplishments (e.g., “Flake Slayer” for 4+ consecutive flaky fixes).
- **Unlocks**: access to advanced tools, higher autonomy, preferred experiment slots when maintaining positive reliability streaks.

## 3. Gamification Swarm Roles

### 3.1 Telemetry & Scoring Agent

- Subscribes to CI, sim, Meta-Audit streams (via event bus + telemetry manager `test_swarm` / `meta_audit` streams).
- Normalizes events into XP entries: formula includes base points × impact multiplier × risk multiplier.
- Maintains streaks (e.g., days without flaky regressions) and emits structured logs `gamification:score_update`.

### 3.2 Quest Designer Agent

- Consumes behavior data (coverage gaps, incident backlog, pending directives) to craft personalized quests.
- Quest types: Coverage Boost (raise module coverage), Sim Hardening (add hostile twin scenario), Governance Cleanse (close audit findings), Documentation Sprint (update runbooks).
- Uses ReAct loop: propose quest → check guardrails → publish to quest ledger.
- Difficulty adapts to past completion velocity and current workload.

### 3.3 Reward Curator Agent

- Maps achievements to meaningful rewards: dashboard highlights, experiment priority, access to advanced sandboxes, learning credits.
- Avoids “point spam” by enforcing cooldowns and requiring impact validation (e.g., promotion that avoided incident).

### 3.4 Coach / Feedback Agent

- Generates weekly retros summarizing XP sources, completed quests, recommended focus.
- Provides comparisons versus personal history, not peers, to avoid unhealthy competition.

### 3.5 Governance Liaison Agent

- Interfaces with Meta-Audit Swarm to ensure reward algorithms remain compliant.
- Processes appeals when contributors dispute scoring; references stored telemetry to adjust XP if warranted.

## 4. Multi-Agent Reward Shaping

### 4.1 Human-facing incentives

- Live quest board with progress bars and “seasonal” themes (e.g., “Simulation Hardening Season”).
- Visualizations of coverage, mutation, governance streaks.
- Recognitions (titles, badges) surfaced in dashboards and all-hands reports.

### 4.2 Agent-facing incentives

- Feed scoring metrics into agent reputation weights: agents proposing reliable changes gain higher execution priority or expanded autonomy.
- Integrate with `swarm.dev_swarm_orchestrator` to bias task assignment toward high-reputation agents/humans for critical quests.

## 5. Governance & Guardrails

- **Policy transparency**: reward formulas versioned in repo, referenced in Meta-Audit documentation.
- **Risk gates**: no XP for bypassing process; attempts trigger negative reputation and incident review.
- **Appeals**: contributors can file dispute -> Governance liaison reviews telemetry, emits decision event.
- **Audit logging**: all score updates, quest issuances, and reward grants logged via TelemetryManager (`gamification` stream to be registered) for chain-of-custody.

## 6. Tech Stack & Wiring

### 6.1 Event & Data Flow

```text
CI/Sim/Meta Audit events ──▶ Event Bus (Kafka/NATS)
                                 │
           ┌──────────────────────┴───────────────────────┐
      Scoring Agent (LLM tool)                 Quest Designer Agent
           │                                           │
 XP Ledger (Postgres/Redis) ◀─────┐           Quest Ledger (Postgres/Graph)
           │                      │
     Reward Curator Agent ────────┴──▶ Notifications / Dashboards
```

- Real-time store: Redis for streaks, Postgres for durable XP + quest state; optional graph DB for relationships between quests, contributors, modules.
- Workflow engine (e.g., Temporal/Argo) orchestrates quest lifecycle and reward grants.

### 6.2 Integration Points

- **Telemetry**: extend TelemetryManager with `gamification` stream (INTERNAL/WARM, 365 days) for scoring events.
- **Meta-Audit**: reward adjustments require `MetaAuditRuntime` directive referencing compliance state.
- **Dev/Test swarms**: quests automatically translate to `DevTask` entries; completion status flows back into scoring agent.

### 6.3 Coverage & KPI Tracking

- KPIs captured per contributor + swarm:
  - Coverage delta, mutation score improvements, flaky fixes.
  - Quest completion rate vs offered; quality engagement ratio (high-impact vs trivial quests).
  - Incident trend, escaped defect rate, governance adherence (% promotions without waiver).
- Metrics surfaced in dashboards + MAS KPI board.

## 7. Progression & Rewards

- **Tier ladder**: L1 Contributor, L2 Steward, L3 Sim Guardian, L4 Meta Auditor, L5 Governor.
- Advancement requires XP threshold + qualitative gates (incident leadership, governance compliance).
- Rewards include autonomy unlocks, access to advanced tooling, learning budget, experiment priority slots.

## 8. Implementation Path

1. **Infra setup**: register `gamification` telemetry stream; provision XP/quest storage schema.
2. **Scoring agent MVP**: subscribe to CI/test events, compute XP for coverage/test improvements, log via telemetry.
3. **Quest designer**: integrate with coverage analyzer + incident backlog to auto-create quests.
4. **Reward curator**: define reward catalog, integrate with dashboards/notification systems.
5. **Governance hooks**: document reward formulas, add appeal workflow tied to Meta-Audit.
6. **Seasonal campaigns**: configure themed quest batches aligned with strategic goals (e.g., reliability season).

## 9. Open Questions

- Define precise weighting for XP formulas (impact calibration with Meta-Audit).
- Determine privacy boundaries for telemetry used in scoring.
- Finalize UI surfaces for quest/XP dashboards.
