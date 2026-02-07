# Meta-Audit Swarm Charter & Runtime Specification

## 1. Purpose and Mandate

The Meta-Audit Swarm ("MAS") is MERID's independent governance layer. It reports directly to the Board-level AI Governance Committee, not to product or trading swarms. MAS owns:

- **Assurance & compliance** – Validate that every production-relevant agent, swarm, or model operates within approved policies, regulatory obligations, and defined risk tolerances. Violations must be detected and remediated with published playbooks.
- **Integrity & accountability** – Guarantee that material AI decisions are attributable, reproducible, and explainable through tamper-evident audit trails, with human ownership for outcomes.
- **Risk & performance oversight** – Continuously watch systemic safety indicators (drift, overfitting, hallucinations, data misuse, coordination failures) and gate any promotion/autonomy change until quantitative evidence satisfies governance contracts.

MAS is empowered to veto or downgrade any promotion, throttle/ pause live systems, compel mitigations, and escalate incidents to the AI Governance Committee within defined SLAs.

---

## 2. Scope Boundaries

| In Scope | Out of Scope (default) |
| --- | --- |
| Production or pre-production agents, swarms, ensembles, data pipelines, model deployments, promotion pipelines, governance contracts. | Low-risk sandbox experiments and offline research **only if** they do not access live data/capital and cannot alter governed configs. Crossing either boundary immediately brings them in scope. |

Lifecycle coverage: design → data → training → validation → deployment → monitoring → retirement. Environments: dev, sim, paper, live. Risk-tiered scrutiny (Tier 1 critical, Tier 2 material, Tier 3 low-risk) determines evidence depth.

---

## 3. Governance Roles & Obligations

### 3.1 Role definitions

- **Policy & Risk Owner (MAS Policy Cell)** – Enforces AI policies, risk appetite statements, capital/permission limits. Issues vetoes, throttles, or downgrades when boundaries are breached.
- **Inventory & Classification Steward (MAS Inventory Cell)** – Maintains canonical AI inventory with risk tier, intended use, deployment status, and assigned owners. Ensures Tier 1 systems receive deep reviews and refreshed artifacts (model cards, hazard analyses, privacy impact assessments).
- **Change & Promotion Gatekeeper (MAS Promotion Cell)** – Controls stage transitions (dev→sim→paper→live), model updates, and config changes. All promotions require signed MetaAuditRuntime verdicts referencing evidence bundles.

### 3.2 RACI Matrix by lifecycle stage

| Lifecycle Stage | Board / AI Gov Committee | Meta-Audit Swarm | Product / Model Owners | Risk / Compliance / Legal / Security |
| --- | --- | --- | --- | --- |
| **Design** | A | R (bias/threat review), C on architecture decisions, I on escalations | R for specs, A for local guardrails | C on high-risk use cases, A for external mandates |
| **Data & Feature Mgmt** | A | R for data lineage attestations, I on minor updates | R for sourcing & labeling | C/A for privacy, data sharing |
| **Training / Reflection** | A | R for sim/WFO gate confirmations, C on experiment plans, I on telemetry deviations | R/A for experiment quality | C for policy-sensitive datasets |
| **Validation / Testing** | A | R for control testing, KPI sign-off | R for generating evidence | C/A for regulatory tests |
| **Promotion / Deployment** | A | R (veto/approve), C on technical rollout plans, I on change tickets | R for rollout execution, A for rollback plans | C for regulatory filings |
| **Monitoring / Drift / Hallucination** | A for outcomes | R (alerts, drift dashboards, hallucination KPIs), I to Board | R for fixes | C for compliance reporting |
| **Retirement / Incident Response** | A for final decision | R for verification & evidence hand-off | R for remediation | C/A for regulatory disclosure |

(A = Accountable, R = Responsible, C = Consulted, I = Informed)

Inventory entries must reference: business owner, risk owner, MAS coverage cell, promotion status, latest audit date, risk tier, control posture, telemetry bindings.

---

## 4. KPIs & Success Criteria

| KPI Pillar | Metrics | Targets / Interpretation |
| --- | --- | --- |
| **Coverage & Completeness** | % agents inventoried vs deployed, % material decisions with queryable audit trails, % models with current risk assessments/model cards. | ≥ 99% Tier1 coverage, ≥ 95% Tier2. Any gap auto-triggers remediation ticket. |
| **Risk/Safety/Compliance** | Count & severity-weighted sum of policy violations, MTTR for violations, % regulator/internal audit requests met within SLA, high-severity incident trend. | MTTR < 24h Tier1, <72h Tier2. SLA compliance ≥ 98%. Incident trend must be flat/down. |
| **Oversight Quality** | % promotions passing full evidence pack (WFO, PBO/DSR, privacy, risk, explainability), false positive/negative rate of MAS alerts, human override rate & post-override success/failure. | <2% overrides for Tier1; FP/FN tracked monthly; promotions blocked if evidence missing. |
| **Drift & Performance** | Ensemble performance drift (Sharpe, hit rate), sub-population drift, PSI/Wasserstein stats, drift alert rate & MTTR. | PSI thresholds: <0.1 warn, 0.1–0.25 review, >0.25 block. Wasserstein thresholds calibrated per feature distribution. |
| **Hallucination/Toxicity** | Global hallucination rate, critical vs functional hallucination rate, detection latency, coverage of detectors, post-mitigation deltas. | Critical hallucinations <0.5% for Tier1 surfaces; detection latency <5 min; coverage ≥ 95% of critical flows. |
| **Meta-Swarm Effectiveness** | % control self-tests passed, % MAS findings closed on time, external assurance score. | ≥ 99% control uptime; findings closure SLA < 10 business days; external review every 12 months. |

---

## 5. Audit Evidence & Immutable Log Standards

### 5.1 Evidence bundle requirements

Each audited decision/promotion must include:

1. Configuration & environment state (hashes, parameters, feature toggles).
2. Data / feature provenance proof (source IDs, lineage graph).
3. Model version + artifact fingerprint + training dataset snapshot.
4. Risk assessment + model card + privacy impact summary.
5. Test results: WFO runs, hostile twin sims, anti-overfitting gates (PBO, DSR), hallucination decay regression, policy guardrails.
6. Approvals & sign-offs (human + MAS digital signatures) with timestamps.
7. Resulting actions & deployment diffs.

### 5.2 Tamper-proof logging controls

- **Append-only storage** – Write-once (WORM) medium; no in-place edits. Retention aligned with NIST SP 800-53 AU-9/AU-11.
- **Cryptographic chaining** – Every log record hashed and linked (hash chain or Merkle tree). Hash roots anchored in MAS ledger and optionally external timestamping service.
- **Identity binding** – Digital signatures/HMAC tied to agent or service keys; include caller/callee, correlation IDs, monotonic timestamps.
- **Independent verification** – Publish hash roots + verification procedure so external auditors can recompute integrity without trusting runtime.
- **Granularity w/ privacy** – Log schemas capture action type, parameters, decision rationale, severity. Sensitive payloads stored encrypted; MAS enforces least-privilege read paths with full access logging.
- **Monitoring & alerts** – MAS checks log coverage, detects missing intervals, and alarms on unauthorized access attempts to logging infra.

---

## 6. Minimum Technical Controls

1. **Enforcement hooks** –
   - Central Promotion Pipeline exposes `submit_promotion_evidence()` and requires `MetaAuditRuntime.review_promotion()` verdict before activating.
   - Runtime kill/pause switches (per strategy + global) callable by MAS only through governance-signed transactions.
   - Configuration registry mutations travel exclusively through MAS-approved workflows (signed change tickets).
2. **Access & Separation of Duties** –
   - MAS has read-all, write-governance-only permissions. It cannot directly move capital or edit model weights; it writes approvals, findings, directives, and kill-switch triggers.
   - Dual control for high-severity actions (e.g., MAS directive + human chair sign-off).
3. **Control self-tests** –
   - Scheduled probes to verify logging integrity, telemetry coverage, enforcement latch wiring, and kill-switch responsiveness.
   - MAS autopings reflection/sim/observability feeds; missing telemetry escalates.

---

## 7. Telemetry & Inputs

| Source | Signal Type | MAS Usage |
| --- | --- | --- |
| ReflectionRuntime | Producer/Critic/Meta loops, hallucination decay metrics, guardrail denials. | Correlate hallucination trends with promotions; trigger safe-mode if decay reverses. |
| Simulation/WFO harness | Hostile twin sims, walk-forward stats, PBO/DSR, Monte Carlo stress. | Gate promotions; trend systemic robustness. |
| Observability stack | Drift monitors (PSI, Wasserstein), toxicity detectors, latency/error metrics. | Drive drift dashboards & incident alerts. |
| Promotion pipeline | Evidence bundles, stage transitions, manual overrides. | Ensure RACI compliance, log override rationale. |
| Reality Enforcement system | TruthGate states, assertion gaps. | Block UI/exec surfaces lacking valid assertions. |

### 7.1 Meta-Audit Telemetry Stream & Reflection Coupling

- **Dedicated stream** – `core.telemetry_manager` registers a `meta_audit` stream (INTERNAL classification, WARM retention, 365-day horizon, 1.0 sampling) owned by `meta_audit_runtime`. All MAS structured logs and metrics MUST target this stream so dashboards can slice governance posture independently from trading/runtime noise.
- **Structured events** – `MetaAuditRuntime` emits events such as `system_registered`, `evidence_recorded`, `promotion_decision`, `directive_issued`, and `incident_logged`, each tagged with `strategy_id`, lifecycle stage, severity, and required actions. These payloads propagate both into observability backends and the MAS ledger for crypto chaining.
- **Reflection loop binding** – Every promotion decision is mirrored into the `ReflectionLayer` (`agents.reflection_layer.reflection_layer`) via `record_decision` + `record_outcome` calls. Energy IDs encode `{strategy_id}:{stage}:{evidence_id}` so hallucination analytics and promotion post-mortems can replay the exact governance rationale.
- **Event stream parity** – In parallel with telemetry/logging, MAS publishes `meta_audit:*` topics (`promotion_decision`, `directive`, `incident`) over `core.event_bus.event_stream`, enabling UI surfaces and auditors to subscribe without scraping raw logs.

---

## 8. MetaAuditRuntime Interface

The runtime formalizes MAS interactions with other swarms.

```python
class MetaAuditRuntime(Protocol):
    def register_system(self, system: MetaAuditSystemSpec) -> str: ...
    def record_evidence(self, evidence: PromotionEvidence) -> str: ...
    def review_promotion(self, request: PromotionGateRequest) -> PromotionGateDecision: ...
    def issue_directive(self, directive: GovernanceDirective) -> str: ...
    def log_incident(self, incident: MetaAuditIncident) -> str: ...
    def attest_audit_trail(self, chain_head: str, proof: AuditProof) -> bool: ...
    def get_inventory_snapshot(self, risk_tier: Optional[str] = None) -> InventorySnapshot: ...
    def get_kpi_dashboard(self) -> MetaAuditKPIs: ...
```

### Key Schemas

- `MetaAuditSystemSpec`: `{ system_id, owner, risk_owner, risk_tier, lifecycle_stage, envs, telemetry_bindings, last_audit_at }`
- `PromotionEvidence`: references evidence bundle IDs + hash roots.
- `PromotionGateRequest`: `{ strategy_id, from_stage, to_stage, evidence_ids, requested_by, change_ticket }`
- `PromotionGateDecision`: `{ decision (approve|reject|throttle), severity, rationale, required_actions, signatures, expiry }`
- `GovernanceDirective`: used for vetoes, throttles, safe-mode triggers.
- `MetaAuditIncident`: captures drift/hallucination/policy events with impact class (functional vs critical) and remediation clock.
- `MetaAuditKPIs`: structured metrics described in §4.

Runtime implementations must:

1. Seal every `record_evidence` / `review_promotion` call into the immutable log pipeline.
2. Emit structured telemetry + metrics on the `meta_audit` stream **and** publish events over `event_stream` (e.g., `meta_audit:directive`, `meta_audit:promotion_decision`).
3. Forward every promotion verdict into the ReflectionRuntime to maintain longitudinal reasoning context and hallucination coverage.
4. Integrate with PromotionPipeline such that `request_promotion` blocks until `review_promotion` returns `approve`. Any `reject/throttle` forces rollback and records MAS directive ID.
5. Provide API access for dashboards (`/api/v1/meta_audit/...`) with read-only JWT scopes and proof-export endpoints.

---

## 9. Drift & Hallucination Monitoring Blueprint

- **Statistical drift** – PSI for legacy comparability; Wasserstein for quantitative magnitude. Use per-feature + ensemble aggregates. Thresholds drive MAS directives: warning, require retrain, block.
- **Model-based drift** – Ensemble detectors or shadow models generate anomaly scores. MAS correlates with statistical signals to avoid false positives and surfaces root-cause diagnostics.
- **Hallucination taxonomy** – Tag events as functional vs critical. Critical events auto-open incidents with MTTR KPIs and optional safe-mode triggers. MAS tracks post-mitigation deltas to ensure improvements stick.

### 9.1 PSI Implementation Guidance

- **Binning discipline** – Define bins once on the baseline window and freeze them. Use:
  1. Quantile (10–20 equi-depth) bins for skewed/long-tailed numeric features.
  2. Equal-width bins when features have physical ranges traders already understand.
  3. Domain bins (credit tiers, vol regimes) when policy already references those bands.
  4. Dedicated `MISSING` bins and `OTHER` bins for rare categories to surface missingness or categorization drift.
- **Mixed data** – Numeric columns follow the frozen-bin rules above; categorical columns use their categories (plus `OTHER`). Document bin schemas in the AI inventory so audits are reproducible.
- **Thresholds & sample size** – Keep the conventional interpretation (<0.1 none, 0.1–0.25 review, >0.25 block). PSI is largely sample-size invariant, so MAS policy should **raise** alert thresholds only when per-window counts are tiny (to avoid noisy bins) and allow **lower** thresholds for very large samples. Extra data alone will not make PSI see <10% shifts, so treat PSI as a coarse, stakeholder-friendly indicator.

### 9.2 Wasserstein (Optimal Transport) Guidance

- **When to prefer Wasserstein** – Use it for small-but-meaningful shifts, gradual mean drift, and continuous features where PSI stays near zero. Wasserstein grows roughly with drift magnitude, making it suitable for comparing severity across time.
- **Per-feature monitoring** – Default to 1-D Wasserstein per feature (cheap `O(n log n)` sort). Track a vector of distances plus trend lines.
- **Threshold calibration** – For each feature, compute Wasserstein over “stable” historical windows, then set alert bands such as mean + 3σ or the 95th percentile. Because Wasserstein is in feature units, compare features only after normalization (divide by baseline σ or IQR) or by converting to z-scores relative to the baseline distribution.
- **Alignment with PSI** – Where PSI thresholds already exist (e.g., 0.1/0.25), pick Wasserstein thresholds whose historical breaches coincide with those PSI boundaries so stakeholders get coherent alarms even while MAS benefits from higher sensitivity.
- **Missing data** – Run Wasserstein both on raw values and on binary “is missing” indicators so missingness drift is detectable alongside PSI’s missing bin.

### 9.3 Model-Based & Multivariate Drift Stack

- **Combined pattern** – MAS treats univariate PSI + Wasserstein as Tier-0 signals (fast attribution). For concept drift or correlated shifts, add Tier-1 detectors:
  - Model-based monitors (shadow models, classifier-based drift, MMD) tied to business metrics (e.g., Sharpe, error rate).
  - Approximate multivariate Wasserstein (sliced or tree-sliced) on embeddings or key feature groups for joint-structure awareness.
- **Approximation techniques** – Favor sliced Wasserstein (many 1-D projections averaged) or tree-based approaches (Tree-Wasserstein, tree-sliced) for high dimensions. These deliver OT-like behavior without the `O(n^3)` cost of exact multi-D OT, enabling real-time alerts.
- **Feature prioritization** – Combine feature importance (SHAP/feature gain) with Wasserstein drift magnitudes to focus remediation on high-impact, high-drift dimensions. MAS dashboards highlight the top-k drifting features alongside their owners and policies.
- **Escalation wiring** – Tier-0 (PSI/W Wasserstein) warns; Tier-1 (model-based, multivariate) confirms impact. MAS directives must cite which tier triggered the block and include the evidence bundle (per §5).

### 9.4 Practical Checklist for MAS Drift Monitors

| Step | PSI | Wasserstein | Model-Based |
| --- | --- | --- | --- |
| Baseline setup | Freeze bins; document schema + MISSING/OTHER bins. | Store baseline samples & σ/IQR for normalization. | Train/validate auxiliary detectors (shadow models, MMD, etc.). |
| Runtime metrics | Compute PSI per feature per window; apply policy thresholds. | Compute normalized 1-D Wasserstein per feature; trend + alert when calibrated band breached. | Monitor performance/detector scores (Sharpe drift, classifier AUC, etc.). |
| Multivariate coverage | Not applicable; rely on feature-level context. | Optional sliced/tree-sliced runs on grouped features or embeddings. | Classifier or autoencoder-based drift for joint shifts. |
| Governance hooks | MAS logs PSI bins + thresholds in evidence bundles. | MAS records raw/normalized Wasserstein, calibration stats, and detected tree/sliced approximations. | MAS includes detector configs, train dates, and validation stats with promotion evidence. |
| Escalation | PSI ≥0.25 → block; 0.1–0.25 → MAS review ticket. | Wasserstein beyond “severe” band → throttle or retrain; “warning” band → heightened monitoring. | Concept-drift breach or degraded business KPI → mandatory remediation plan before promotion. |

### 9.5 Tree-Wasserstein (TWD) Implementation Path

1. **Minimal in-house implementation** – Treat multivariate Wasserstein on a tree as:
   \[
   W_T(p, q) = \sum_{(u\to v)\in E} w_{uv} \left| \sum_{i\in\text{subtree}(v)} (p_i - q_i) \right|,
   \]
   where \(p,q\) are distributions over leaf nodes. A ~30-line Python helper (DFS to accumulate subtree mass differences, then sum weighted absolute values per edge) is enough for prototypes and regression tests. MAS keeps this snippet checked into the repo for transparency and deterministic unit tests.
2. **Tree construction** – Build the tree via hierarchical clustering (k-means splits, agglomerative, or regime-specific taxonomies). Every distribution (e.g., regime embeddings, feature bundles) collapses to leaf probabilities by summing weights per leaf.
3. **Performance tiering** – Use the minimal implementation for CI/regression; call optimized libraries (next section) for production telemetry where thousands of distributions must be compared per hour.

### 9.6 External Libraries & Tooling

- **treeOT (OIST)** – Reference implementation for “Approximating 1-Wasserstein Distance with Trees.” Provides `ClusterTree` builders + `tree_wasserstein_distance`. Recommended for MAS workloads once vetted. Repo: `github.com/oist/treeOT`.
- **tree-wsv (kiradust)** – Fast ground-metric learning & tree-sliced Wasserstein variants. Useful when MAS needs tree construction + metric learning + batched distance queries. Repo: `github.com/kiradust/tree-wsv`.
- **Adoption model** – Vendor a subset or run them via a separate service container. Guard with checksum attestation and reproducible builds before wiring into critical KPIs. The MAS runtime should detect library unavailability and fall back to the minimal implementation with degraded-mode alerts.

### 9.7 L1-Regularized Edge Weight Learning

To align tree distances with true 1-Wasserstein (or domain ground metrics), MAS fits non-negative edge weights by solving a Lasso-style regression:

1. For each training pair of leaves \((i,j)\), build feature vector \(x_{ij}\in\{0,1\}^{|E|}\) indicating which edges lie on the path between \(i\) and \(j\).
2. Collect target distances \(d_{ij}\) (exact OT via POT for small samples, or trusted ground metric measurements).
3. Solve
   \[
   \min_{w\ge0} \frac{1}{2N}\sum_{(i,j)} (d_{ij} - x_{ij}^T w)^2 + \lambda \lVert w \rVert_1.
   \]
4. Implement with a PyTorch FISTA loop (gradient step + soft-threshold prox + non-negativity clamp). MAS keeps this trainer under `analytics/drift/tree_metric_fit.py` with unit tests covering convergence and edge-case handling.
5. Store learned weights with metadata (training set hash, λ, convergence stats) and reference IDs so promotion evidence can cite exactly which metric calibration justified a veto/approval.

### 9.8 Validation & Synthetic Evaluation

Before deploying TWD for governance gating:

1. **Synthetic harness** – Generate mixtures/regimes, compute exact 1-Wasserstein via POT (or similar) on modest sample sizes.
2. **Tree approximation** – Build the tree, learn weights via §9.7, compute TWD for the same distribution pairs.
3. **Metrics** – Track absolute/relative error plus Pearson/Spearman correlation vs exact OT; record runtime deltas. MAS policy sets acceptance thresholds (e.g., RE < 5%, corr ≥ 0.98 for Tier-1 workloads).
4. **Regression tests** – Check that updates to trees/weights/libraries keep approximation error within tolerance. Failure automatically downgrades MAS drift confidence and blocks promotions relying on the degraded signal.
5. **Live shadowing** – In production, periodically sample distribution pairs, compute exact OT asynchronously, and compare to TWD to catch silent drift in the approximation pipeline.

---

## 10. Success Criteria & External Assurance

- Minimum quarterly reporting to AI Governance Committee summarizing KPIs, findings, overrides, drift/hallucination posture, and remediation backlog.
- Annual independent assessment of MAS controls (crypto logs, runtimes, KPIs) with published opinion.
- Continuous improvement loop: MAS findings feed reflection learning so agents internalize governance constraints.

---

## 11. Next Implementation Steps

1. **Code** – Implement `MetaAuditRuntime` interface + persistence, hook PromotionPipeline, expose API.
2. **Telemetry wiring** – Bind reflection, observability, sim harness streams into MAS dashboards.
3. **Audit trail infra** – Deploy hash-chain log service with export tooling and retention policy enforcement.
4. **Dashboards** – Build MAS console section (coverage, KPIs, incidents, directives, promotion queue).
5. **Testing** – Regression tests for promotion gating, log integrity proofs, drift/hallucination alert thresholds, and kill-switch invocation.
6. **Telemetry verification** – `tests/test_meta_audit_runtime.py` exercises the telemetry/reflection wiring by mocking persistence, telemetry, reflection, and event stream dependencies to ensure promotion approvals emit `meta_audit.promotion_decision` metrics, rejections issue directives, and reflection records carry the proper rationale.

The Meta-Audit Swarm now has a concrete charter, KPIs, RACI, and runtime specification so it can operate as MERID’s internal audit + GRC function for agents.
