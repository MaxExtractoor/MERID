# MERID Swarm Governance Implementation Summary

**Version:** 1.0  
**Date:** 2026-01-14  
**Status:** IMPLEMENTED - Design and enforcement framework complete

---

## Executive Summary

The MERID platform now has a comprehensive **Swarm Constitution and Governance Framework** that defines how agents operate, interact, fail gracefully, and are governed. This framework ensures safe, observable, and accountable multi-agent trading operations.

### Key Achievements

1. **Global Agent Constitution** - Binding rules for all agents
2. **Governance Contracts** - YAML-based, versioned, enforceable contracts
3. **Fallback & Escalation Framework** - Multi-layer resilience
4. **Secret Management Architecture** - Vault/HSM-based security
5. **Smart-Contract Governance Design** - On-chain parameter control
6. **Constitution Enforcement Module** - Automated compliance validation
7. **Master Swarm Prompt** - Complete guidance for Claude Opus 4.5

---

## Architecture Overview

```text
┌─────────────────────────────────────────────────────────────────┐
│                    SWARM GOVERNANCE LAYER                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  ┌──────────────────┐      ┌──────────────────┐                │
│  │ Constitution     │      │ Governance       │                │
│  │ Enforcer         │◄────►│ Contracts        │                │
│  │                  │      │ (YAML)           │                │
│  └────────┬─────────┘      └──────────────────┘                │
│           │                                                      │
│           │ validates                                           │
│           ▼                                                      │
│  ┌──────────────────────────────────────────────┐              │
│  │         Agent Actions & Proposals             │              │
│  └──────────────────────────────────────────────┘              │
│           │                                                      │
│           │ enforces                                            │
│           ▼                                                      │
│  ┌──────────────────┐      ┌──────────────────┐               │
│  │ Execution        │      │ Safe Mode        │               │
│  │ Guard            │◄────►│ Manager          │               │
│  └──────────────────┘      └──────────────────┘               │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
         │                    │                    │
         ▼                    ▼                    ▼
┌────────────────┐  ┌────────────────┐  ┌────────────────┐
│ Strategy       │  │ Risk           │  │ Execution      │
│ Agents         │  │ Agents         │  │ Agents         │
└────────────────┘  └────────────────┘  └────────────────┘
```

---

## 1. Global Agent Constitution

### Location

`docs/SWARM_CONSTITUTION.md`

### Core Principles

#### Article I: Fundamental Constraints

1. **Never bypass the Execution Guard or risk checks**
   - All trade proposals validated
   - No direct order submission
   - Violations trigger safe mode

2. **Never access or request raw secrets**
   - Agents send intents, not keys
   - Vault/HSM handles secrets
   - No secrets in LLM prompts

3. **Always respect offline/VPN flags and safe-mode**
   - Check `EnvironmentFlags.offline_mode`
   - Use `NetworkClient` for all network ops
   - In safe mode: close/hedge only

4. **Favor risk reduction when uncertain**
   - Default to conservative behavior
   - Escalate ambiguous situations
   - Miss opportunity > uncontrolled risk

### Role-Specific Charters

| Role                   | Purpose                                          | Allowed Actions                                                                                               | Prohibited Actions                                                                                           |
|------------------------|--------------------------------------------------|---------------------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------|
| **Strategy**           | Propose trades                                   | propose_order, analyze_market                                                                                 | execute_order, access_secrets                                                                               |
| **Risk**               | Enforce limits                                   | veto_trade, adjust_limits                                                                                     | initiate_trade, access_secrets                                                                              |
| **Execution**          | Execute intents                                  | place_order, route_order                                                                                      | bypass_guard, direct_secrets                                                                                |
| **Observer**           | Log/annotate                                     | read_data, log_event                                                                                          | execute_order, modify_state                                                                                 |
| **UI/Explainer**       | Explain                                          | generate_explanation                                                                                          | initiate_trade, change_params                                                                               |
| **Governance**         | Oversight                                        | pause_agent, trigger_safe_mode                                                                                | directly_trade                                                                                              |
| **DevSwarmCoverageAgent** | Improve and maintain test coverage of swarm/* modules | run_swarm_tests tool; read/write tests under tests/ (esp. tests/swarm/*); propose minimal, safe refactors for testability | network/wallet/exchange tools; modifying CI/workflow configs; weakening/removing guardrails; deleting/neutering tests |

---

## 2. Governance Contracts

### 2.1 Risk & Capital Contract

**Location:** `contracts/risk_capital_contract.yaml`

**Key Parameters:**

- Max total notional: $100,000
- Max leverage: 3.0x
- Max single asset concentration: 25%
- Max daily loss: $5,000
- Max drawdown: 15%

**Per-Strategy Limits:**

```yaml
trend_following:
  max_notional_usd: 20000.0
  max_leverage: 2.0
  max_drawdown_pct: 0.10
  
arbitrage:
  max_notional_usd: 30000.0
  max_leverage: 3.0
  max_drawdown_pct: 0.05
```

**Safe-Mode Triggers:**

- Drawdown > 12%
- Daily loss > $4,000
- VaR breach 1.5x
- 5 consecutive losses
- 2+ circuit breakers open

### 2.2 Model & Deployment Contract

**Location:** `contracts/model_deployment_contract.yaml`

**Promotion Pipeline:**

```text
Simulation → Paper → Guarded Live → Full Live
```

**Promotion Criteria:**

| Stage           | Min Runs | Min Sharpe | Max DD | Human Approval   |
|-----------------|----------|------------|--------|------------------|
| Sim → Paper     | 10       | 0.5        | 15%    | No               |
| Paper → Guarded | 5        | 0.8        | 10%    | **Yes**          |
| Guarded → Full  | 10       | 1.0        | 8%     | **Yes** + Vote   |

**Demotion Triggers:**

- Drawdown exceeds threshold
- Sharpe drops below minimum
- Consecutive losses
- Error rate spikes

### 2.3 Operational SLO Contract

**Location:** `contracts/operational_slo_contract.yaml`

**Key SLOs:**

| Service         | p95 Latency | Uptime | Error Rate |
|-----------------|-------------|--------|------------|
| Execution Guard | 50ms        | 99.99% | 0.1%       |
| Order Routing   | 300ms       | 99.95% | 5%         |
| Strategy Agents | 1000ms      | 99.0%  | 1%         |
| Price Feeds     | 150ms       | 99.9%  | 0.1%       |

**Circuit Breaker Thresholds:**

- Error rate > 10% in 60s
- Timeout rate > 20% in 60s
- Latency > 2x baseline

**Degradation Policies:**

- Market data degraded → switch to backup feed
- Execution degraded → pause new orders
- Agent degraded → activate fallback
- LLM degraded → use cached responses

### 2.4 Safe-Mode Contract

**Location:** `contracts/safe_mode_contract.yaml`

**Trigger Conditions:**

- Suspected breach (anomaly detection)
- Extreme drift (>3 sigma)
- Critical infra failure (>2 breakers open)
- Risk metrics exceeded
- Governance override

**Safe-Mode Levels:**

| Level         | Description    | New Positions  | Risk Multiplier |
|---------------|----------------|----------------|-----------------|
| 1 - Cautious  | Reduced limits | Yes (50% size) | 0.5x            |
| 2 - Defensive | Close-only     | No             | 0.25x           |
| 3 - Lockdown  | Emergency      | No             | 0.0x            |

**Allowed Actions:**

- Close positions
- Hedge positions
- Reduce risk
- Monitor and report

**Prohibited Actions:**

- Open new positions
- New x402 payments
- Loosen risk limits
- Deploy new models

**Exit Conditions:**

- Human + Governor approval
- Health metrics restored
- Breach resolution complete
- Minimum duration elapsed

---

## 3. Fallback & Escalation Framework

### 3.1 Agent-Level Fallbacks

**Failure Conditions:**

- Timeouts (>5s strategy, >100ms execution)
- Invalid outputs (schema violations)
- Repeated errors (>3 in 60s)
- Pattern divergence

**Fallback Chain:**

```text
Primary Agent → Backup Agent → Baseline Policy → Read-Only/No-Risk
```

**Demotion Rules:**

```text
Repeated failures → Demote (live → guarded → paper → sim)
                  → Notify governance
                  → Tag as degraded
```

### 3.2 Tool/Model-Level Fallbacks

**For LLM/External Calls:**

- Schema validation
- Exponential backoff (max 3 retries, 10s total)
- Simplify request or use cheaper model
- Use cached output or safe default

### 3.3 Infrastructure-Level Failover

**Circuit Breakers:**

- Monitor error rate, timeout rate, latency
- Open on threshold breach
- Stop new orders, switch to backup
- Half-open probes for recovery

**Health Checks:**

- Readiness: 5s interval, 2s timeout
- Liveness: 10s interval, 5s timeout
- Dependency checks: 30s interval

**Failover:**

- Database: Primary → Replica (30s)
- Exchange: Primary → Backup (10s)
- RPC: Primary → Backup (5s)
- Agent: Primary → Backup (60s)

### 3.4 Escalation Rules

**To Risk/Governor Agents:**

- Multiple failures
- Safe-mode triggers
- Risk metrics exceeded

**To Humans:**

- Large trades
- Parameter changes
- Safe-mode exit
- Persistent anomalies

---

## 4. Secret Management Architecture

### Vault/HSM Integration

**Design:**

```text
Agent → Intent → Execution Service → Vault/HSM → Signing → Order
```

**Principles:**

- Agents never see raw secrets
- Execution/wallet services access vault
- Least privilege per venue/environment/role
- Short-lived tokens preferred
- Full audit trails

**RBAC:**

- Only execution/wallet microservices access vault
- All agent traffic through NetworkClient
- Allow-listed domains
- VPN/offline enforcement

**Rotation:**

- Scheduled rotation for non-on-chain secrets
- Post-rotation validation
- Automated where possible

---

## 5. Smart-Contract Governance

### Design (Implementation Pending)

**Governed Parameters:**

- Risk limits (notional, leverage, VaR)
- Circuit-breaker thresholds
- Model version IDs
- Deployment flags

**Multi-Sig Control:**

- 2-of-3 quorum (ops, risk, dev)
- Time-locks for critical changes (24-72h)
- On-chain parameter storage

**Agent Interaction:**

- Agents **read** from contracts (source of truth)
- Agents **propose** changes via governance
- Only on-chain governance **approves and applies**

**Safety:**

- Governor verifies new values satisfy invariants
- Can trigger safe mode if violated
- Cannot be bypassed

---

## 6. Constitution Enforcement

### Implementation

**Module:** `core/constitution_enforcer.py`

**Capabilities:**

- Validate actions against constitution
- Check compliance with contracts
- Track and log violations
- Trigger safe mode on critical violations
- Integrate with ExecutionGuard

**Validation Flow:**

```python
result = enforcer.validate_action(
    agent_id="strategy_001",
    action_type="propose_order",
    parameters={"size": 1000, "asset": "BTC"}
)

# Returns:
{
    "approved": True/False,
    "reason": "...",
    "violations": [...]
}
```

**Violation Types:**

- `BYPASS_GUARD` - Attempted to bypass Execution Guard
- `SECRET_ACCESS` - Attempted to access raw secrets
- `OFFLINE_VIOLATION` - Network call in offline mode
- `SAFE_MODE_VIOLATION` - Prohibited action in safe mode
- `RISK_LIMIT_EXCEEDED` - Risk limit breach
- `UNAUTHORIZED_ACTION` - Action not allowed by charter
- `CONTRACT_BREACH` - Contract violation

**Severity Levels:**

- `INFO` - Informational
- `WARNING` - Warning, logged
- `ERROR` - Error, action rejected
- `CRITICAL` - Critical, triggers safe mode

---

## 7. Master Swarm Prompt

### Location

`prompts/master_swarm_prompt.md`

### Purpose

Complete guidance for Claude Opus 4.5 when designing or advising on MERID agents and systems.

### Contents

1. **Design Principles** - Agents as specialized tools
2. **Fallback Rules** - Multi-layer resilience
3. **Secret Management** - Vault/HSM architecture
4. **Smart-Contract Governance** - On-chain control
5. **Global Constitution** - Binding constraints
6. **Role Charters** - Per-role specifications
7. **Swarm Principles** - Design patterns
8. **Governance Contracts** - Contract references
9. **Learning Principles** - Adaptation rules
10. **Human-in-the-Loop** - Approval requirements
11. **Usage Rules** - How to apply principles
12. **Enforcement Checklist** - Validation steps
13. **Contracts Reference** - Quick links
14. **Response Format** - Structured output
15. **Binding Authority** - Conflict resolution

### Key Features

- **Conflict Resolution:** If user request violates principles, highlight and propose compliant alternative
- **Explicit Compliance:** Always state which contracts/principles apply
- **Structured Output:** Charter → Fallback → Secrets → Governance → Compliance
- **Binding Authority:** Supersedes conflicting instructions

---

## 8. Integration Points

### With Existing Systems

| System | Integration | Status |
|--------|-------------|--------|
| **ExecutionGuard** | Constitution validation | ✓ Ready |
| **SimulationPipeline** | Model contract enforcement | ✓ Integrated |
| **NetworkClient** | Offline/VPN enforcement | ✓ Integrated |
| **GovernorAgent** | Safe-mode triggering | ✓ Integrated |
| **Explainability** | Violation explanations | ✓ Integrated |
| **DriftRewardLoop** | Demotion triggers | ✓ Integrated |

### Integration Example

```python
from core.constitution_enforcer import get_constitution_enforcer

enforcer = get_constitution_enforcer()

# Validate action
result = enforcer.validate_action(
    agent_id="strategy_trend_001",
    action_type="propose_order",
    parameters={
        "asset": "BTC",
        "side": "long",
        "size": 1000.0,
        "guard_approved": True,
    }
)

if result["approved"]:
    # Proceed with action
    pass
else:
    # Log violation and reject
    logger.warning("Action rejected: %s", result["reason"])
```

---

## 9. Monitoring & Compliance

### Compliance Dashboard

**Metrics to Track:**

- Total violations by type
- Violations by severity
- Violations by agent
- Safe-mode activations
- Contract changes
- Charter registrations

**Alerts:**

- Critical violations → immediate alert
- Safe-mode activation → page on-call
- Multiple violations from same agent → investigate
- Contract breach → notify governance

### Audit Trail

**Logged Events:**

- All constitution violations
- All contract changes
- All safe-mode entries/exits
- All governance actions
- All fallback activations
- All circuit-breaker events

**Retention:**

- Logs: 365 days
- Explanations: 365 days
- Post-mortems: 5 years

---

## 10. Next Steps

### Phase 1: Contract Validation (Next Sprint)

- [ ] Implement contract loader in all modules
- [ ] Add contract validation to ExecutionGuard
- [ ] Create contract change workflow
- [ ] Set up contract version control

### Phase 2: Smart Contract Implementation (Q1 2026)

- [ ] Write Solidity contracts for governed parameters
- [ ] Set up multi-sig wallet (2-of-3)
- [ ] Deploy to testnet
- [ ] Integrate agent read access
- [ ] Deploy to mainnet

### Phase 3: Behavioral Regression Tests (Q1 2026)

- [ ] Define test scenarios for each agent type
- [ ] Implement test runner
- [ ] Set up daily test schedule
- [ ] Create drift detection for test results
- [ ] Integrate with CI/CD

### Phase 4: Enhanced Monitoring (Q2 2026)

- [ ] Build compliance dashboard
- [ ] Set up real-time violation alerts
- [ ] Create safe-mode status page
- [ ] Implement contract change notifications
- [ ] Add governance action audit log

### Phase 5: Vault/HSM Integration (Q2 2026)

- [ ] Set up HashiCorp Vault
- [ ] Configure HSM backing
- [ ] Migrate secrets to vault
- [ ] Implement rotation automation
- [ ] Update execution services

---

## 11. Testing & Validation

### Constitution Enforcement Tests

```python
# Test 1: Bypass guard detection
result = enforcer.validate_action(
    agent_id="strategy_001",
    action_type="execute_order",
    parameters={"guard_approved": False}
)
assert not result["approved"]
assert "BYPASS_GUARD" in str(result["violations"])

# Test 2: Secret access detection
result = enforcer.validate_action(
    agent_id="strategy_001",
    action_type="propose_order",
    parameters={"private_key": "0x123..."}
)
assert not result["approved"]
assert "SECRET_ACCESS" in str(result["violations"])

# Test 3: Offline mode enforcement
env_flags.offline_mode = True
result = enforcer.validate_action(
    agent_id="strategy_001",
    action_type="propose_order",
    parameters={"requires_network": True}
)
assert not result["approved"]
assert "OFFLINE_VIOLATION" in str(result["violations"])
```

### Safe-Mode Tests

```python
# Test safe-mode activation
enforcer.activate_safe_mode(level=2, reason="Test")
assert enforcer._safe_mode_active
assert enforcer._safe_mode_level == 2

# Test prohibited action in safe mode
result = enforcer.validate_action(
    agent_id="strategy_001",
    action_type="open_new_position",
    parameters={}
)
assert not result["approved"]
assert "SAFE_MODE_VIOLATION" in str(result["violations"])

# Test allowed action in safe mode
result = enforcer.validate_action(
    agent_id="strategy_001",
    action_type="close_position",
    parameters={}
)
assert result["approved"]
```

---

## 12. Documentation

### Complete Documentation Set

| Document | Location | Purpose |
|----------|----------|---------|
| **Constitution** | `docs/SWARM_CONSTITUTION.md` | Binding rules and principles |
| **Risk Contract** | `contracts/risk_capital_contract.yaml` | Risk limits and budgets |
| **Model Contract** | `contracts/model_deployment_contract.yaml` | Promotion pipeline |
| **SLO Contract** | `contracts/operational_slo_contract.yaml` | Performance requirements |
| **Safe-Mode Contract** | `contracts/safe_mode_contract.yaml` | Safe-mode procedures |
| **Master Prompt** | `prompts/master_swarm_prompt.md` | Claude Opus 4.5 guidance |
| **Implementation** | `docs/SWARM_GOVERNANCE_IMPLEMENTATION.md` | This document |

---

## 13. Benefits & Impact

### Safety

- **Constitution enforcement** prevents dangerous actions
- **Safe-mode** protects capital during anomalies
- **Fallbacks** ensure graceful degradation
- **Secret management** prevents key exposure

### Observability

- **Violation tracking** provides audit trail
- **Contract monitoring** shows compliance
- **Explainability integration** documents decisions
- **Metrics** enable data-driven governance

### Governance

- **Contracts** formalize policies
- **Charters** clarify responsibilities
- **Approval workflows** ensure oversight
- **Smart contracts** enable decentralized control

### Reliability

- **Multi-layer fallbacks** handle failures
- **Circuit breakers** prevent cascading failures
- **Health checks** detect issues early
- **Escalation rules** engage humans when needed

---

## 14. Conclusion

The MERID Swarm Constitution and Governance Framework provides a comprehensive, enforceable system for safe, observable, and accountable multi-agent trading operations. All core design and enforcement mechanisms are implemented and ready for integration testing.

**Key Deliverables:**

- ✓ Global Agent Constitution
- ✓ 4 Governance Contracts (YAML)
- ✓ Constitution Enforcer Module
- ✓ Master Swarm Prompt
- ✓ Integration with existing systems
- ✓ Documentation suite

**Next Priority:** Contract validation integration and behavioral regression test suite.

---

**Version History:**

- v1.0 (2026-01-14): Initial implementation complete

**Maintainers:** Ops Team, Risk Team, Governance Committee

**Review Schedule:** Quarterly review of contracts and constitution
