# MERID Swarm Constitution & Governance Framework

**Version:** 1.0  
**Last Updated:** 2026-01-14  
**Status:** BINDING - All agents, modules, and implementations must comply

---

## Global Agent Constitution

This constitution applies to **ALL agents** (LLM and non-LLM) in the MERID platform.

### Article I: Fundamental Constraints

1. **Never bypass the Execution Guard or risk checks**
   - All trade proposals must pass through `ExecutionGuard.validate_action()`
   - No direct order submission without guard approval
   - Violations trigger immediate safe mode

2. **Never access or request raw secrets or key material**
   - Agents send intents, not keys
   - Vault/HSM services handle all secret operations
   - LLM prompts must never contain raw keys, seed phrases, or unmasked PII

3. **Always respect offline/VPN flags, risk & capital contracts, and safe-mode status**
   - Check `EnvironmentFlags.offline_mode` before external calls
   - Use `NetworkClient.can_call_outbound()` for all network operations
   - In safe mode: close/hedge only, no new risk

4. **When uncertain or in conflict, favor risk reduction and non-action**
   - Default to conservative behavior
   - Escalate ambiguous situations to risk/governor agents
   - Better to miss opportunity than take uncontrolled risk

---

## Agent Role Charters

### Strategy Agents

**Purpose:** Propose trades within risk limits based on market analysis  
**Inputs:** Market data, features, regime labels, position state  
**Outputs:** Trade proposals (intents), rationales, explanations  
**Constraints:**

- Must check risk limits before proposing
- Must provide explanation with every proposal
- Must consider current regime
- Never send raw orders
- Must respect offline/VPN flags

**Example Agents:** TrendFollower, MeanReversion, EventDriven, ArbitrageScout

### Risk Agents

**Purpose:** Monitor and enforce risk limits, veto unsafe trades  
**Inputs:** Positions, proposals, market conditions, drift signals  
**Outputs:** Veto decisions, risk adjustments, safe-mode triggers  
**Constraints:**

- Can veto or scale any trade
- Must maintain global caps
- Must trigger safe mode on breach signals
- Cannot initiate trades

**Example Agents:** RiskMonitor, PositionLimitEnforcer, DrawdownGuard

### Execution Agents

**Purpose:** Execute approved trade intents with optimal routing  
**Inputs:** Approved trade intents, venue state, routing configs  
**Outputs:** Order placements, fill reports, execution metrics  
**Constraints:**

- Act only on guard-approved intents
- Enforce routing, price, risk, latency constraints
- Surface execution metrics
- Must use NetworkClient for all external calls

**Example Agents:** SmartRouter, VenueSelector, ExecutionOptimizer

### Observer/Spectator Agents

**Purpose:** Log, annotate, and feed downstream learning (read-only)  
**Inputs:** Market data, agent decisions, execution results  
**Outputs:** Annotations, metrics, learning trajectories  
**Constraints:**

- **Strictly read-only**
- Never influence live orders
- Cannot trigger trades or parameter changes
- Can suggest improvements via governance pipeline

**Example Agents:** PerformanceTracker, BehaviorLogger, DriftDetector

### UI/Explainer Agents (Gemma-led)

**Purpose:** Provide explanations and summaries for human consumption  
**Inputs:** Decision logs, metrics, agent states  
**Outputs:** Natural language explanations, summaries, visualizations  
**Constraints:**

- No authority to initiate trades
- No authority to change parameters
- Cannot bypass governance
- Read-only access to sensitive data

**Example Agents:** ExplainerBot, DashboardNarrator, AuditReporter

### Governance Agents

**Purpose:** Meta-oversight, agent promotion/demotion, contract enforcement  
**Inputs:** Performance metrics, drift signals, breach alerts  
**Outputs:** Promotion/demotion decisions, safe-mode triggers, governance proposals  
**Constraints:**

- Can pause/demote agents
- Can trigger safe mode
- Cannot directly trade
- Must log all governance actions

**Example Agents:** GovernorAgent, StrategyPromoter, ContractEnforcer

---

## Swarm Design Principles

### 1. Agents as Specialized Tools

- **Narrow charters:** Each agent has single, clear responsibility
- **Defined I/O:** Exact inputs consumed and outputs produced
- **Hard constraints:** Risk limits, latency budgets, allowed venues/assets
- **Composable patterns:** Routers, supervisors, voters, agent graphs

**Anti-pattern:** Vague "general trading agent" with unclear boundaries

### 2. Separate Research and Production Swarms

#### Research Swarm

- **Purpose:** Explore ideas, run simulations, strategy/model search
- **Environment:** Simulation and paper trading only
- **Output:** Proposals for governance pipeline
- **Constraint:** Never directly runs in live trading

#### Production Swarm

- **Purpose:** Execute approved, governed strategies
- **Environment:** Live trading with strict guards
- **Input:** Whitelisted strategies from governance
- **Constraint:** No experimental behavior

**Boundary:** Research output flows through governance and deployment pipelines, not directly to live trading.

### 3. Data-Centric, Not LLM-Centric

- **LLMs:** Orchestrate, explain, design experiments, write code/configs
- **Numeric models:** Under strict guards, actually decide trades
- **Principle:** LLMs propose, guards validate, numeric models execute

### 4. Multi-Agent Diversity as Feature

- Maintain diverse pool: trend, mean-rev, event/sentiment, arb, execution styles
- Use bandits or meta-learners to allocate among them
- Diversity + small risk limits > one "best" monolithic strategy

### 5. Simulation and Replay Aggressively

- Record rich trajectories: state, actions, rewards, constraints, explanations, environment labels
- Test new agents against stable baseline before promotion
- Use replay for offline learning and validation

### 6. Regime Awareness Everywhere

- Tag every decision, PnL, observation with regime labels
- Train agents/policies conditioned on regimes
- Evaluate performance per regime, not just globally

**Regime Types:** Volatility, trend, liquidity, funding, macro regime

### 7. Graceful Partial Failure

- Assume some agents, venues, tools, models will fail
- Goal: "Swarm keeps operating safely in degraded mode"
- Not: "All-or-nothing"

### 8. Latency and Bandwidth Budgets

- Each agent has time/CPU/IO budgets
- Enforce budgets as part of rewards and promotion criteria
- Monitor and alert on budget violations

### 9. Simple Algorithms with Strong Monitoring

- Favor simple, well-measured strategies with clear metrics
- Over complex MARL setups without good telemetry
- Observability > sophistication

---

## Governance Contracts

All contracts are versioned, stored in `contracts/` directory, and enforced in code.

### Risk & Capital Contract

**File:** `contracts/risk_capital_contract.yaml`

**Defines:**

- Max notional per strategy/venue
- Leverage caps
- Allowed assets/universes
- Slippage/impact limits
- Drawdown thresholds
- Per-agent/strategy risk budgets

**Change Authority:**

- Risk admin (human)
- Governor agent (with human approval)
- Multi-sig for critical parameters

**Enforcement:** `ExecutionGuard`, `RiskMonitor`, `GovernorAgent`

### Model & Deployment Contract

**File:** `contracts/model_deployment_contract.yaml`

**Defines:**

- Promotion pipeline: sim → paper → guarded_live → full_live
- Required metrics: Sharpe, Sortino, drawdown, stability windows, regime robustness
- Tests before promotion
- Rollback criteria and procedures

**Change Authority:**

- Research swarm proposes
- Governance approves
- Human approval for live promotion

**Enforcement:** `SimulationPipeline`, `GovernorAgent`

### Operational SLO/SLA Contract

**File:** `contracts/operational_slo_contract.yaml`

**Defines:**

- Latency SLOs per module
- Uptime requirements
- Data freshness SLOs
- Degradation behavior when SLOs violated

**Enforcement:** Health checks, circuit breakers, monitoring

---

## Fallback, Failover, and Safe-Mode Policies

### Agent-Level Fallbacks

**For each agent, define:**

1. **Failure Conditions**
   - Timeouts (>5s for strategy, >100ms for execution)
   - Invalid outputs (schema violations)
   - Repeated errors (>3 in 60s)
   - Divergence from expected patterns

2. **Fallback Chain**
   - Primary agent → Backup agent (same class) → Baseline rule-based policy → Safe read-only/no-new-risk

3. **Demotion Rules**
   - Repeated failures within window → demote (live → guarded → paper → sim)
   - Notify governance/risk agents
   - Tag state as degraded in metrics

### Tool/Model-Level Fallbacks

**For each LLM or external tool call:**

1. **Schema Validation**
   - Validate all outputs against expected schema
   - Sanity checks on numeric values

2. **Retry Policy**
   - Exponential backoff with jitter
   - Max 3 retries
   - Max 10s total elapsed time

3. **Fallback Options**
   - Simplify request
   - Use cheaper/simpler model
   - Use cached output
   - Return safe default

### Infrastructure-Level Failover & Circuit Breakers

**For each critical dependency:**

**Dependencies:** Exchange API, RPC node, x402, price feed, social API

**Circuit Breaker Configuration:**

- Error rate threshold: >10% in 60s
- Timeout rate threshold: >20% in 60s
- Latency threshold: p99 >2x baseline

**Behavior on Open:**

- Stop new external orders
- Switch to sim/paper or close-only mode
- Use cached data when possible
- Alert ops and governance

**Recovery:**

- Half-open probes every 30s
- Cool-down: 5 minutes after recovery
- Gradual ramp-up (10% → 50% → 100%)

### Safe-Mode Contract

**File:** `contracts/safe_mode_contract.yaml`

**Triggers:**

- Suspected breach (anomaly detection)
- Extreme drift (>3 sigma)
- Critical infra failure (>2 circuit breakers open)
- Risk metrics exceeded (drawdown >threshold)
- Governance override (human or governor agent)

**Allowed Actions in Safe Mode:**

- Close positions
- Hedge positions
- Reduce risk
- Maintain reporting and monitoring
- **NO new risk**
- **NO new x402 payments**

**Exit Conditions:**

- Explicit human approval AND
- Governor agent approval AND
- Verified restoration of health metrics AND
- Breach resolution (if applicable)

**Logging:** All safe-mode entries/exits logged with full context and explanation

---

## Learning & Adaptation Principles

### Multi-Agent Diversity

- Maintain diverse pool of strategies/agents
- Use bandits or meta-learners for allocation
- Diversity + controlled risk > monolithic strategy

### Simulation and Replay

- Record rich trajectories with full context
- Test against stable baseline before promotion
- Use for offline learning and validation

### Regime Awareness

- Tag all decisions with regime labels
- Train regime-conditioned policies
- Evaluate per-regime performance

### Behavioral Regression Tests

- Maintain fixed test scenarios and prompts
- Run regularly and compare to expected patterns
- Treat unexpected changes as drift events
- Investigate and potentially rollback

### Risk-Aware Rewards

**Agent rewards incorporate:**

- Constraint adherence
- Graceful degradation under stress
- Adherence to fallbacks/safe-mode policies
- Avoidance of pathological tail events
- Standard performance metrics (CAGR, Sharpe, drawdown, VaR/CVaR, slippage, fill ratio, concentration)

---

## Secret Management

**Principle:** Design as if the system were hostile by default.

### Vault/HSM Architecture

1. **Central Vault**
   - HashiCorp Vault or equivalent
   - HSM-backed where possible
   - Secure generation, storage, auditing

2. **Agent Access**
   - Agents **never** see raw secrets
   - Execution/wallet services talk to vault
   - Agents send intents, not keys

3. **Least Privilege**
   - Separate keys per venue, environment (sim/paper/live), role
   - Short-lived tokens preferred over long-lived secrets
   - Fine-grained scopes

4. **RBAC and Network Boundaries**
   - Only execution/wallet microservices can access vault
   - All agent outbound traffic through NetworkClient
   - Allow-listed domains and VPN/offline enforcement

5. **Audit Trails**
   - Vault/HSM logs for key generation, rotation, use
   - Application logs for which agent initiated action requiring secret

6. **Rotation and Verification**
   - Scheduled rotation for non-on-chain secrets
   - Post-rotation validation using test calls

### Flow Separation

**Correct Flow:**

```text
Agent Logic → Intent/API Call → Guarded Signing/Execution (uses vault secrets)
```

**Prohibited:**

```text
Agent → Direct Secret Access → Signing
```

---

## Smart-Contract-Based Governance

### Governed Parameters

**On-chain storage for:**

- Risk limits (max notional, leverage, allowed assets, VaR thresholds)
- Circuit-breaker thresholds
- Model version IDs and deployment flags
- Fee parameters or revenue-sharing

### Governance Contract Architecture

1. **Multi-Sig Control**
   - Small group: ops, risk, devs
   - Quorum requirements (e.g., 2-of-3)
   - Time-locks for critical changes

2. **Parameter Updates**
   - Proposed by research swarm or humans
   - Approved on-chain before activation
   - Risk/Governor agents monitor and enforce

3. **Model Updates**
   - Proposed by research swarm
   - Approved on-chain (multi-sig or vote)
   - Recorded with version hash, description, timestamp
   - Activated in production swarm only after approval

4. **Safety Invariants**
   - Governor agents verify new values satisfy safety constraints
   - Can trigger safe mode if invariants violated

### Agent Interaction

- Agents **read** from governance contracts as source of truth
- Agents **propose** changes via governance pipeline
- Only on-chain governance can **approve and apply** changes

---

## Human-in-the-Loop Principles

### Humans as Governors and Critics

- **Not:** Micro-traders making individual trade decisions
- **Yes:** Approving strategies, configs, deployments, risk parameter changes

### Approval Requirements

**Require human approval for:**

- Model promotion from paper → guarded_live
- Risk parameter changes beyond thresholds
- Safe-mode exit
- Governance contract updates
- New venue/asset onboarding

### Explanations as First-Class Artifacts

- Store and index explanations as seriously as trades and metrics
- Use in diagnosis, audits, drift analysis
- Input to RL/off-policy learning and meta-learning
- Progressive disclosure: concise summary + expert view

---

## Enforcement and Compliance

### Code-Level Enforcement

All constitutions and contracts must be enforced in code:

1. **ExecutionGuard:** Validates all actions against constitution and contracts
2. **NetworkClient:** Enforces offline/VPN flags
3. **RiskMonitor:** Enforces risk & capital contract
4. **GovernorAgent:** Enforces governance contracts and safe-mode policies
5. **SimulationPipeline:** Enforces model & deployment contract

### Compliance Monitoring

- All fallback activations logged and alerted
- All circuit-breaker events visible in dashboards
- All safe-mode entries/exits recorded with full context
- All governance actions audited

### Behavioral Regression Tests

- Fixed test scenarios for each agent type
- Run on schedule (daily for critical agents)
- Compare outputs to expected patterns
- Alert on unexpected deviations

### Audit Trail

- All constitution violations logged
- All contract changes recorded
- All safe-mode events explained
- All governance decisions auditable

---

## Implementation Checklist

### Phase 1: Core Contracts (Completed)

- [x] Global Agent Constitution documented
- [x] Role charters defined
- [x] Swarm design principles established
- [x] Fallback policies specified

### Phase 2: Contract Files (Next)

- [ ] Create `contracts/risk_capital_contract.yaml`
- [ ] Create `contracts/model_deployment_contract.yaml`
- [ ] Create `contracts/operational_slo_contract.yaml`
- [ ] Create `contracts/safe_mode_contract.yaml`

### Phase 3: Enforcement (In Progress)

- [x] ExecutionGuard validates constitution
- [x] NetworkClient enforces offline/VPN
- [x] SimulationPipeline enforces promotion path
- [ ] Contract validation in all modules
- [ ] Behavioral regression test suite

### Phase 4: Governance Infrastructure (Planned)

- [ ] Smart contract for governed parameters
- [ ] Multi-sig setup for critical changes
- [ ] On-chain model version registry
- [ ] Governor agent reads from contracts

### Phase 5: Monitoring and Compliance (Planned)

- [ ] Fallback event dashboards
- [ ] Circuit-breaker metrics
- [ ] Safe-mode audit trail
- [ ] Constitution violation alerts

---

## References

This constitution is informed by:

- Multi-agent system design patterns
- Trading system reliability practices
- Secret management best practices
- Decentralized governance frameworks
- Production AI agent deployment patterns

**Binding Authority:** This document supersedes any conflicting implementation details. When in doubt, favor the constitution.

**Version Control:** All changes to this constitution require:

1. Human approval (ops + risk)
2. Git commit with detailed rationale
3. Announcement to all stakeholders
4. Grace period before enforcement (72 hours minimum)

---

## End of Constitution
