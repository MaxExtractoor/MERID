# Legacy Systems Overview

**Modules and Subsystems Out of Scope for the 15m Lean Stack**

This document lists legacy modules that are kept for historical reasons and for non-15m profiles. These modules are **not** used by the `kalshi_crypto_15m_v2` production path and must not be wired into `main_15m_lean.py`.

---

## Core Legacy Modules

### `core/paper_session.py`

**Purpose**: Paper trading session runner for prediction markets.

**Components**:
- `PaperSession` - Main paper session class
- `PaperSessionState` - Session state dataclass
- `ReadinessBenchmark` - Readiness validation
- `IntervalPnL` - Interval PnL tracking
- `SessionRiskLimits` - Session risk limits

**Status**: **LEGACY** - Not used by `kalshi_crypto_15m_v2` profile. The lean 15m stack uses live bankroll service (`merid.event_venues.kalshi.bankroll_service_v2`).

**Tests**: Marked with `pytest.mark.legacy` in `tests/test_paper_session.py` and `tests/core/test_paper_session.py`.

**Migration**: Use `BankrollServiceV2` for live trading. Paper trading is not supported in the 15m lean stack.

---

### `swarm/agent_registry.py`

**Purpose**: Decentralized agent identity and registry system.

**Components**:
- `AgentRegistry` - Agent identity registry
- `CanonicalAgent` - Base agent class
- `CanonicalAgentRegistry` - Canonical agent management

**Status**: **LEGACY** - Not used by `kalshi_crypto_15m_v2` profile. The lean 15m stack uses `agent_grid_15m.py` for agent management.

**Tests**: Marked with `pytest.mark.legacy` in `tests/test_canonical_agents.py`, `tests/test_agent_wiring.py`, and `tests/test_realfirst_endpoints.py`.

**Migration**: Use `AgentGrid15m` from `merid/prediction/agent_grid_15m.py` for agent management.

---

### `agents/reflection/integration.py`

**Purpose**: Reflection system for agent learning and knowledge persistence.

**Components**:
- `ReflectionSystem` - Main reflection system
- `LongTermKnowledgeBase` - Long-term knowledge storage
- `LearningEngine` - Learning and insight tracking

**Status**: **LEGACY** - Not used by `kalshi_crypto_15m_v2` profile. The lean 15m stack does not use reflection systems.

**Tests**: Marked with `pytest.mark.legacy` in `tests/test_audit_fix_regressions.py`.

**Migration**: No migration path. Reflection systems are not part of the 15m lean stack architecture.

---

## Kalshi Legacy Modules

### `merid/event_venues/kalshi/deployment.py`

**Purpose**: Deployment controller for paper→live promotion.

**Components**:
- `DeploymentController` - Deployment state management
- `AutoPromoter` - Automatic promotion logic
- `PromotionState` - Promotion state tracking

**Status**: **LEGACY** - Not used by `kalshi_crypto_15m_v2` profile. The lean 15m stack uses live mode directly with explicit mode flags (`is_demo`/`is_live`).

**Migration**: Use mode flags in `KalshiVenueClient` and `BankrollServiceV2` to control demo/live mode. No automatic promotion in 15m stack.

---

## Prediction Market Legacy Modules

### `merid/prediction/paper_session.py`

**Purpose**: Prediction market paper session runner.

**Components**:
- `PaperSession` - Paper session for prediction markets
- `ReadinessBenchmark` - Readiness validation
- `IntervalPnL` - Interval PnL tracking

**Status**: **LEGACY** - Not used by `kalshi_crypto_15m_v2` profile. The lean 15m stack uses live bankroll service.

**Tests**: Marked with `pytest.mark.legacy` in `tests/test_paper_session.py`, `tests/test_audit_bug_fixes.py`, `tests/test_risk_audit_regressions.py`, `tests/test_prediction_audit_regressions.py`, `tests/test_agent_grid_audit.py`, and `tests/trading/test_lifecycle_bug_regressions.py`.

**Migration**: Use `BankrollServiceV2` for live trading.

---

### `merid/prediction/pm_profiles.py`

**Purpose**: PM (Prediction Market) profile management.

**Components**:
- `merge_profile_into_strategy_config` - Profile merging logic
- Sentiment override logic (removed in hardening)

**Status**: **LEGACY** - Not used by `kalshi_crypto_15m_v2` profile. The lean 15m stack uses profile YAML directly without PM runtime.

**Migration**: Use profile YAML configuration files directly. No PM profile merging in 15m stack.

---

### `merid/prediction/risk/kalshi_risk_engine.py`

**Purpose**: PM-level Kalshi risk configuration.

**Components**:
- `KalshiRiskConfig` - PM risk configuration (deprecated)

**Status**: **DEPRECATED** - Superseded by venue-level `KalshiRiskConfig` in `merid/event_venues/kalshi/kalshi_risk.py`. PM config is duplicate and only used by tests.

**Migration**: Import `KalshiRiskConfig` from `merid.event_venues.kalshi.kalshi_risk` instead of `merid.prediction.risk.kalshi_risk_engine`.

---

## Orchestrator Legacy Modules

### `core/agent_orchestrator.py`

**Purpose**: Agent orchestrator for PM runtime.

**Components**:
- `AgentOrchestrator` - Agent orchestration logic
- Canonical agent cycle management

**Status**: **LEGACY** - Not used by `kalshi_crypto_15m_v2` profile. The lean 15m stack uses `loop_15m.py` for execution.

**Migration**: Use `Loop15m` from `merid/loop_15m.py` for execution loop.

---

### `swarm/consensus_aggregator.py`

**Purpose**: Swarm consensus aggregation for PM runtime.

**Components**:
- `SwarmConsensusAggregator` - Consensus aggregation logic
- Proposal management

**Status**: **LEGACY** - Not used by `kalshi_crypto_15m_v2` profile. The lean 15m stack does not use swarm consensus.

**Migration**: No migration path. Swarm consensus is not part of the 15m lean stack architecture.

---

## Usage Guidelines

### For Non-15m Profiles

These legacy modules may still be used by other profiles (e.g., `kalshi-only`, `pm-production`). When working on non-15m profiles:

1. Check the profile's entrypoint to understand which modules are used
2. Legacy modules are acceptable for non-15m profiles
3. Do not wire legacy modules into `main_15m_lean.py`

### For 15m Stack Development

When working on the `kalshi_crypto_15m_v2` profile:

1. **Do not import** any legacy modules in `main_15m_lean.py`
2. **Do not add** dependencies on PaperSession, AgentRegistry, or ReflectionSystem
3. **Do not use** PM runtime components (orchestrator, consensus, canonical agents)
4. **Do not use** deployment controller or auto-promoter
5. **Use** venue-level components (KalshiVenueClient, BankrollServiceV2, KalshiRiskConfig)
6. **Use** agent_grid_15m.py for agent management
7. **Use** loop_15m.py for execution loop

### Testing

Legacy tests are marked with `pytest.mark.legacy` and can be excluded:

```bash
# Run only non-legacy tests
pytest tests/ -m "not legacy"

# Run only legacy tests
pytest tests/ -m legacy
```

---

## Migration Checklist

When migrating from legacy to lean stack:

- [ ] Remove imports of `core.paper_session`
- [ ] Remove imports of `swarm.agent_registry`
- [ ] Remove imports of `agents.reflection.integration`
- [ ] Remove imports of `merid.event_venues.kalshi.deployment`
- [ ] Remove imports of `merid.prediction.paper_session`
- [ ] Remove imports of `merid.prediction.pm_profiles`
- [ ] Replace `KalshiRiskConfig` imports with venue-level version
- [ ] Remove orchestrator and consensus logic
- [ ] Use `BankrollServiceV2` instead of `PaperSession`
- [ ] Use `AgentGrid15m` instead of `AgentRegistry`
- [ ] Use `Loop15m` instead of `AgentOrchestrator`
- [ ] Verify `/api/v1/self-check` shows no legacy modules loaded
- [ ] Run smoke tests: `pytest tests/test_15m_lean_smoke.py`

---

## Related Documentation

- [`docs/15m_lean_stack.md`](15m_lean_stack.md) - 15m lean stack architecture
- [`docs/15m_runbook.md`](15m_runbook.md) - 15m lean stack operational runbook
- [`README.md`](../README.md) - Project README
