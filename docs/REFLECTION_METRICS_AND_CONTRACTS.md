# MERID Reflection Subsystem & Hallucination Metrics Contracts

_Last updated: 2026-01-18_

This document converts the reflection layer from loosely coupled “think again” prompts into a first-class, auditable subsystem with defined roles, triggers, evidence schemas, and quantitative hallucination metrics. It is the authoritative contract for engineering, safety, and observability teams.

---

## 1. System objectives

1. **Structured roles** – Explicit Producer, Critic, and Meta-Reflector agents with clear responsibilities and data contracts.
2. **Telemetry-grounded decisions** – Every reflection references concrete signals (tests, guardrails, PnL/risk deltas, latency SLOs, user feedback, hallucination metrics).
3. **Guardrail invariants** – Reflection can recommend but never override policy/guardrail outcomes; scope-limited loops (max two rounds) avoid hallucination cascades.
4. **Quantified hallucination decay** – Hallucination tracked like loss curves with domain/severity breakdowns, checkpoint decay fits, and reflection-vs-baseline deltas.
5. **Auditable memory** – Structured “experience pool” keyed by task type, trigger, and evidence with forgetting/compression rules and stale-flag handling.

---

## 2. Core roles & loops

| Role | Responsibilities | Inputs | Outputs |
| --- | --- | --- | --- |
| **Producer** | Executes assigned workflow step (code change, risk analysis, narrative, etc.). | Task spec, current plan, reflection context, guardrail constraints. | Primary artifact + telemetry snapshot + self-declared confidence. |
| **Critic** | Evaluates Producer output against specs, tests, telemetry, guardrails, hallucination detectors. Runs quick _in-task_ loop before side effects. | Producer artifact, observability/test results, guardrail responses, detector scores. | Pass/fail verdict, defect list, severity tags, references to evidence IDs. |
| **Meta-Reflector / Planner** | Performs _post-task_ analysis, updates playbooks/policies, decides remediation or escalation, manages experience log. | Critic verdicts, telemetry deltas, reflection history, reward signals. | Updated plan/policy references, reflection_event records, reward adjustments, execution directives (retry, degrade, escalate). |

### Loops

1. **In-task reflection loop** (fast): Triggered inside critical sections _before_ side effects. Sequence: Producer draft → Critic check → (optional) single remediation attempt → Guardrail gate. Max 1 remediation.
2. **Post-task reflection loop** (trajectory): Runs once workflow completes (success or failure). Meta-Reflector ingests telemetry bundle, compares against KPIs, updates playbooks, and may schedule future tasks.

---

## 3. Trigger matrix

| Trigger | Signal Source | Threshold | Loop | Action |
| --- | --- | --- | --- | --- |
| **Unit/integration test failure** | `pytest`/CI events, `testsuite.results` channel | Any non-flaky FAIL | In-task + Post-task | Block release, annotate evidence, Meta-Reflector records remediation steps. |
| **Guardrail denial** | Policy engine, Reality Auditor, truth-gate | Any DENY/LOCK | In-task | Halt action, log guardrail_id, require human or policy override. |
| **PnL/Risk deviation** | Treasury/risk telemetry (`risk.delta_pct`) | > 50 bps PnL drawdown OR risk bucket breach | Post-task | Generate risk reflection, update risk playbook, escalate if repeated. |
| **Latency SLO breach** | Observability stack (`latency.p99`) | > 10% above SLO for >2 samples | In-task (if action would worsen), Post-task (for incident) | Insert latency mitigation instructions, log incident. |
| **User negative feedback** | Governance/UI feedback queue | severity ≥ MEDIUM | Post-task | Meta-Reflector generates customer remediation playbook entries. |
| **Hallucination metric regression** | Eval harness (Section 6) | HR exceeds target or half-life > policy | Post-task | Schedule mitigation sprint, adjust reflection policies. |
| **Explainability mismatch** | Explainability records vs output | missing/contradicting evidence | In-task | Block action, require evidence alignment. |

No other events trigger reflection automatically to avoid noise. Manual triggers permitted for human auditors.

---

## 4. Evidence schemas & logging

### 4.1 Reflection event schema

All reflection events are stored as JSON (append-only) and mirrored into observability traces:

```json
{
  "reflection_id": "uuid4",
  "loop_type": "in_task" | "post_task",
  "producer_id": "agent://dev-swarm/producer-1",
  "critic_id": "agent://qa/critic-2",
  "meta_id": "agent://planner/meta-1",
  "trigger": {
    "type": "test_failure" | "guardrail_deny" | "pnl_drawdown" | "latency_slo" | "hallucination_regression" | "user_feedback",
    "source_ref": "trace_id or guardrail_id",
    "severity": "minor" | "major",
    "metrics": {"risk_delta_bps": 72.1, "latency_ms": 912}
  },
  "evidence_refs": [
    {"type": "test_log", "id": "pytest://reports/run123"},
    {"type": "detector_score", "id": "hallu_eval://ckpt_180k"}
  ],
  "producer_output_hash": "sha256...",
  "critic_findings": [
    {"issue": "test_module_fail", "severity": "major", "details": "tests/test_latency.py::test_probe"}
  ],
  "meta_decision": "retry" | "defer" | "escalate" | "playbook_update",
  "actions": ["rerun_tests", "notify_risk"],
  "guardrail_status": "deny" | "allow",
  "loop_iteration": 1,
  "timestamp": "UTC ISO",
  "outcome": "resolved" | "unresolved",
  "experience_key": "dev-swarm::testsuite"  
}
```

### 4.2 Experience pool & memory hygiene

- Storage: `logs/reflection_events.jsonl` (short term) + `data/reflection_experiences.parquet` (long term).
- Indexing keys: task_type, domain, trigger_type, failure_mode, severity, guardrail_id.
- **Forgetting policy**: recency decay half-life 30 days, importance boost for events linked to Major guardrail or P0 incident.
- **Compression**: Weekly job collapses old records into playbook rules ("When guardrail R-12 triggers twice in 7 days, disable strategy variant B") stored under `reflection/playbooks/*.yaml`.
- **Stale markers**: When code/policy versions change, associated experiences flagged `status="stale"` until revalidated.

### 4.3 Observability integration

- Every reflection event emits `reflection_event_total{trigger,domain,severity}` counter and `reflection_resolution_seconds` histogram.
- Explainability records add a `reflection_refs` array pointing to `reflection_id`s to maintain audit trail.
- Board/governance reporting consumes aggregated summaries (top triggers, resolved vs unresolved, guardrail suggestions flagged for human review).

---

## 5. Guardrails & safety boundaries

1. Reflection agents **cannot** override guardrail/policy decisions. Suggestions to weaken guardrails require human approval and are logged as `meta_decision="escalate"` with severity HIGH.
2. Max reflections per workflow: 2 (one in-task, one post-task). Additional loops require human override to prevent hallucination cascades.
3. Each reflection must cite concrete evidence IDs; the critic rejects free-form reflections lacking references.
4. Circuit breaker: if two consecutive reflections cite low-confidence evidence or conflicting telemetry, halt automation and escalate to human + safe fallback plan.

---

## 6. Hallucination metrics & decay tracking

### 6.1 Metrics

- **Basic rate** per checkpoint/domain:  
  \( HR_{c,d} = \frac{H_{c,d}}{N_{c,d}} \times 100\% \)
- **Severity-weighted**:  
  \( HR^{(w)}_c = \frac{\sum_i w_i H_{c,i}}{N_c} \), weights {minor:1, major:3}.
- **Reflection delta**:  
  \( \Delta HR^{\text{refl}}_c = HR^{\text{base}}_c - HR^{\text{refl}}_c \).
- **Decay summaries**: absolute drop, relative drop, half-life \(t_{1/2}\), exponential decay fit parameter `b` in \(HR_t = a e^{-bt}\).

### 6.2 Evaluation suite

| Dataset | Purpose | Domain tag |
| --- | --- | --- |
| TruthfulQA (filtered) | open-domain truthfulness | docs |
| HaluEval / CHALE | hallucination regression | general |
| HalluMix | multi-domain robustness | mixed |
| MERID trading/risk Q&A | domain-specific accuracy | trading/risk |
| MERID dev-swarm bug→patch tasks | code reasoning | engineering |
| Grounded governance reports | textual grounding | governance |

- **Detectors**: gold answers when available; else FEWL-style LLM judge + entailment check; RAG grounding for doc tasks. Severity derived from domain impact (e.g., trading risk statements marked major).
- **Cadence**: run on every saved checkpoint (default every 2k gradient steps). Use fixed decoding parameters and seeds for comparability.

### 6.3 Logging schema (per checkpoint)

```json
{
  "checkpoint": "ckpt_180k",
  "step": 180000,
  "domain": "trading",
  "dataset": "merid_trading_eval_v3",
  "hr_basic": 4.1,
  "hr_weighted": 6.3,
  "hr_base": 5.7,
  "hr_reflection": 3.2,
  "delta_hr_reflection": 2.5,
  "decay_rate_b": 0.0041,
  "half_life_steps": 16800,
  "task_accuracy": 82.4,
  "factual_claim_density": 3.1,
  "avg_response_tokens": 412,
  "timestamp": "UTC ISO"
}
```

Metrics flow into Prometheus/W&B and MERID dashboards showing HR vs training loss to catch divergences.

### 6.4 Policy targets

- Trading/risk domains: `hr_weighted <= 2%` and `t_half <= 25k steps`.
- Documentation/governance: `hr_weighted <= 3%`.
- Reflection improvement target: `ΔHR_reflection >= 1% absolute` per checkpoint; if not met for 3 checkpoints, Meta-Reflector flags remediation sprint.

---

## 7. Rewards & learning integration

- Reward vector gains new component `R_reflection` that measures effective reflections: positive when reflections reduce future trigger frequency or HR; zero/negative for noisy reflections rejected by critic.
- Bandit update: maintain success probability per reflection playbook; underperforming playbooks get demoted or retired.
- Meta-Reflector updates swarm decomposition when repeated failures occur (e.g., restructure task graph if guardrail R-12 triggers >3 times/week).

---

## 8. Implementation roadmap

1. **Spec enforcement** (current document) – baseline complete.
2. **Code scaffolding**
   - Add `reflection/orchestrator.py` coordinating Producer/Critic/Meta roles.
   - Implement trigger listeners (tests, guardrails, telemetry, eval harness) publishing to `reflection.event_bus`.
   - Define `ReflectionEvent` dataclass matching schema; integrate with explainability + observability.
3. **Experience pool + memory hygiene**
   - Create storage + maintenance jobs for compression and stale flagging.
4. **Eval harness + metrics**
   - Build checkpoint evaluation runner, dataset configs, detectors, and logging pipeline.
   - Dashboard panels (reflection frequency vs success uplift, HR decay curves, domain breakdowns).
5. **Reward wiring & policy updates**
   - Extend reward vectors, add RL/bandit updates, and annotate playbooks with success metrics.
6. **Testing**
   - Unit tests for orchestrator, trigger dispatch, memory rotation.
   - Regression tests verifying reflection response to mocked triggers.
   - Eval harness CI job to assert HR metrics logged for synthetic checkpoints.

---

## 9. Compliance & audit

- Reflection logs are immutable (append-only + hash chain) and referenced in explainability + board reports.
- Any suggestion touching guardrails flagged for human review with severity HIGH.
- Audit queries supported: `get_reflections(trigger="guardrail_deny", guardrail_id="R-12", window=30d)` returning evidence + actions.
- Incident response workflow ties reflection IDs to incident tickets for traceability.

---

This contract remains in force until superseded; engineering work must reference section numbers when implementing or modifying the reflection subsystem.
