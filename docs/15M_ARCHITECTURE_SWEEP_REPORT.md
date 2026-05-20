# 15m Stack Architecture Sweep Report
## Legacy Sentiment/Consensus/Opinion/Debate Removal

**Date**: 2026-05-19  
**Objective**: Full production-grade architecture sweep of Kalshi crypto 15m trading/execution stack to remove all legacy sentiment/mood/prob/consensus/opinion/narrative logic and enforce clean, auditable, deterministic architecture.

---

## Executive Summary

The sweep identified **extensive legacy decision-layer infrastructure** deeply embedded across the codebase:

- **Consensus**: 17 modules (~200KB) with active integration points in main loop, agent grid, and trading agents
- **Sentiment**: 30+ modules (~500KB) with active integration in agent grid startup and trading agent execution
- **Opinion**: 2 modules (~63KB) with active integration in agent grid opinion loop and consensus submission
- **Debate**: 6 modules (~200KB) with active integration in trading agent sizing and risk gating

**Critical Finding**: Legacy layers are **not isolated** - they are actively initialized at startup, called during loop cycles, and used in execution path decisions. This violates the "minimal deterministic architecture" requirement and creates startup hangs and hidden coupling.

---

## Module Classification

### DELETE - Remove Entirely (Not Used by 15m Runtime)

#### Consensus Layer (DELETE ALL)

| File | Size | Reason | Risk |
|------|------|--------|------|
| `consensus/consensus_coordinator.py` | 46KB | Central consensus coordinator, not used by 15m stack | Low - only used by legacy swarm |
| `consensus/taco_consensus.py` | 23KB | TaCo consensus engine, not used by 15m stack | Low - only used by legacy swarm |
| `consensus/feedback_scheduler.py` | 9KB | Feedback scheduler for consensus, not used by 15m stack | Low - only used by legacy swarm |
| `merid/prediction/consensus.py` | 52KB | Legacy consensus integration, not used by 15m stack | Low - only used by legacy agents |
| `merid/prediction/consensus_bridge.py` | 20KB | Bridge to consensus coordinator, not used by 15m stack | Low - only used by legacy agents |
| `merid/swarm/consensus_engine.py` | TBD | Swarm consensus engine, not used by 15m stack | Low - only used by legacy swarm |
| `merid/swarm/consensus_aggregator.py` | TBD | Consensus aggregator, not used by 15m stack | Low - only used by legacy swarm |
| `merid/swarm/consensus_forensics.py` | TBD | Consensus forensics, not used by 15m stack | Low - only used by legacy swarm |
| `core/consensus_engine.py` | TBD | Core consensus engine, not used by 15m stack | Low - only used by legacy swarm |
| `core/consensus_gate.py` | TBD | Consensus gate, not used by 15m stack | Low - only used by legacy swarm |
| `core/consensus_store.py` | TBD | Consensus store, not used by 15m stack | Low - only used by legacy swarm |
| `core/consensus_math.py` | TBD | Consensus math utilities, not used by 15m stack | Low - only used by legacy swarm |
| `core/consensus_logging.py` | TBD | Consensus logging, not used by 15m stack | Low - only used by legacy swarm |
| `core/consensus_graph.py` | TBD | Consensus graph, not used by 15m stack | Low - only used by legacy swarm |
| `merid/lanes/consensus_integration.py` | TBD | Lane consensus integration, not used by 15m stack | Low - only used by legacy lanes |
| `merid/lanes/consensus_engine_integration.py` | TBD | Lane consensus engine integration, not used by 15m stack | Low - only used by legacy lanes |

**Total Consensus DELETE**: 17 modules (~200KB)

#### Sentiment Layer (DELETE ALL)

| Directory/File | Size | Reason | Risk |
|----------------|------|--------|------|
| `merid/sentiment/` (entire directory) | ~500KB | Entire sentiment pipeline, not used by 15m stack | Low - only used by legacy agents |
| `core/social_sentiment.py` | TBD | Social sentiment processing, not used by 15m stack | Low - only used by legacy agents |
| `core/sentiment_nlp.py` | TBD | Sentiment NLP processing, not used by 15m stack | Low - only used by legacy agents |
| `merid/prediction/forecasters/sentiment.py` | TBD | Sentiment forecaster, not used by 15m stack | Low - only used by legacy agents |
| `merid/prediction/risk/sentiment_vol_types.py` | TBD | Sentiment volatility types, not used by 15m stack | Low - only used by legacy agents |
| `merid/prediction/risk/sentiment_vol_service.py` | TBD | Sentiment volatility service, not used by 15m stack | Low - only used by legacy agents |
| `merid/prediction/risk/sentiment_vol_metrics.py` | TBD | Sentiment volatility metrics, not used by 15m stack | Low - only used by legacy agents |

**Total Sentiment DELETE**: 30+ modules (~500KB)

#### Opinion Layer (DELETE ALL)

| File | Size | Reason | Risk |
|------|------|--------|------|
| `merid/prediction/opinion_strategy.py` | 48KB | Opinion strategy, not used by 15m stack | Low - only used by legacy agents |
| `merid/prediction/market_opinion.py` | 15KB | Market opinion, not used by 15m stack | Low - only used by legacy agents |

**Total Opinion DELETE**: 2 modules (~63KB)

#### Debate Layer (DELETE ALL)

| File | Size | Reason | Risk |
|------|------|--------|------|
| `merid/prediction/debate.py` | 62KB | Debate orchestrator, not used by 15m stack | Low - only used by legacy agents |
| `merid/prediction/debate_orchestrator.py` | 40KB | Debate deployment, not used by 15m stack | Low - only used by legacy agents |
| `merid/prediction/debate_backtest.py` | 13KB | Debate backtesting, not used by 15m stack | Low - only used by legacy agents |
| `merid/prediction/debate_deployment.py` | 18KB | Debate deployment logic, not used by 15m stack | Low - only used by legacy agents |
| `merid/prediction/debate_exit_policy.py` | 25KB | Debate exit policy, not used by 15m stack | Low - only used by legacy agents |
| `merid/prediction/debate_position_sizing.py` | 21KB | Debate position sizing, not used by 15m stack | Low - only used by legacy agents |

**Total Debate DELETE**: 6 modules (~200KB)

---

### REWRITE - Remove Legacy Integration Points

#### merid/loop.py (REWRITE)

**Legacy Integration Points to Remove:**
- Line 716-718: `_consensus_coordinator()` method - DELETE
- Line 1052-1058: `_run_consensus()` call in tick cycle - DELETE
- Line 132: `consensus_interval` in LoopConfig - DELETE
- Line 238: `consensus_cycles_run` in LoopMetrics - DELETE
- Line 343: `_last_consensus` timer - DELETE
- Line 1545-1633: Opinion submission to consensus coordinator - DELETE

**Required Changes:**
1. Remove `_consensus_coordinator()` method entirely
2. Remove `_run_consensus()` method entirely
3. Remove consensus_interval from LoopConfig
4. Remove consensus_cycles_run from LoopMetrics
5. Remove _last_consensus timer
6. Remove opinion submission logic in agent cycle
7. Remove consensus-related imports

**Risk**: HIGH - Loop is central orchestrator, requires careful testing

#### merid/prediction/agent_grid.py (REWRITE)

**Legacy Integration Points to Remove:**
- Line 145-146: Sentiment service initialization - DELETE
- Line 163-165: Regime agents (consensus) initialization - DELETE
- Line 399-400: Stale consensus opinion purge on startup - DELETE
- Line 592-596: Sentiment service start - DELETE
- Line 632-638: Regime opinion loop start - DELETE
- Line 1030-1031: Sentiment service stop - DELETE
- Line 1055-1063: Regime opinion loop stop - DELETE
- Line 1257-1315: Market mood bus feed logic - DELETE
- Line 1315-1364: Opinion loop and collection - DELETE

**Required Changes:**
1. Remove sentiment service initialization entirely
2. Remove regime agents initialization entirely
3. Remove stale consensus opinion purge logic
4. Remove sentiment service start/stop calls
5. Remove regime opinion loop start/stop calls
6. Remove market mood bus feed logic
7. Remove opinion loop and collection logic
8. Remove consensus-related imports

**Risk**: HIGH - AgentGrid is startup orchestrator, requires careful testing

#### merid/prediction/trading_agent.py (REWRITE)

**Legacy Integration Points to Remove:**
- Line 72-73: `consensus_bridge` and `consensus_aggregator` imports - DELETE
- Line 8425: `get_kalshi_consensus_adapter().signal_to_proposal()` usage - DELETE
- Line 1179, 1202: `last_consensus_at` field - DELETE
- Line 1845-1890: `_swarm_consensus_bypassed()` method - DELETE
- Line 2153: Consensus bypass check - DELETE
- Line 2315, 2379-2386: Consensus-based sizing logic - DELETE
- Line 3040-3041: Sentiment global/regime snapshot fields - DELETE
- Line 3216, 3222, 3258, 3408-3409: Consensus timing checks - DELETE
- Line 6305, 6770-6775: Consensus/sentiment metadata - DELETE
- Line 8336-8338: Sentiment score usage - DELETE

**Required Changes:**
1. Remove consensus_bridge and consensus_aggregator imports
2. Remove get_kalshi_consensus_adapter usage
3. Remove last_consensus_at field from agent state
4. Remove _swarm_consensus_bypassed() method entirely
5. Remove consensus bypass checks
6. Remove consensus-based sizing logic (use simple base size)
7. Remove sentiment global/regime snapshot fields
8. Remove consensus timing checks
9. Remove consensus/sentiment metadata
10. Remove sentiment score usage

**Risk**: HIGH - TradingAgent is core execution path, requires careful testing

---

### KEEP - Retain for 15m Stack

#### Core 15m Infrastructure (KEEP)

| Module | Reason |
|--------|--------|
| `merid/event_venues/kalshi/market_catalog.py` | Core market discovery and catalog bootstrap |
| `merid/event_venues/kalshi/client.py` | Core Kalshi API client |
| `merid/event_venues/kalshi/order_router.py` | Core order routing to Kalshi |
| `merid/event_venues/kalshi/ws.py` | Core websocket bridge for live market data |
| `merid/event_venues/kalshi/fills_poller.py` | Core fills reconciliation |
| `merid/event_venues/kalshi/settlement_poller.py` | Core settlement polling |
| `merid/prediction/venue_gate.py` | Core venue gate for risk checks |
| `merid/prediction/portfolio_risk_agent.py` | Core portfolio risk enforcement |
| `merid/prediction/portfolio_risk_manager.py` | Core portfolio risk manager |
| `merid/prediction/trading_agent.py` | Core trading agent (after rewrite) |
| `merid/prediction/agent_grid.py` | Core agent grid orchestrator (after rewrite) |
| `merid/loop.py` | Core main loop (after rewrite) |
| `merid/prediction/pm_profiles.py` | Core PM profile management |
| `merid/prediction/startup_validations.py` | Core startup validation (including sentiment isolation guard) |
| `merid/guardrails/` | Core guardrails infrastructure |
| `merid/risk/` | Core risk infrastructure |
| `config/kalshi_agent_grid.yaml` | Core agent grid config |
| `config/profiles/kalshi_crypto_15m.yaml` | Core 15m risk profile |

---

## Startup Hang Causes

### Identified Startup Hang Sources

1. **Consensus Coordinator Initialization** (merid/loop.py:716-718)
   - EnhancedConsensusCoordinator.get_instance() called during loop init
   - May block on database connection or singleton initialization
   - **Impact**: Medium - coordinator is lazy-loaded but may still cause delay on first access

2. **Stale Consensus Opinion Purge** (merid/prediction/agent_grid.py:399-400)
   - Called during AgentGrid.start()
   - May block on database operations
   - **Impact**: High - blocks agent grid startup

3. **Sentiment Service Start** (merid/prediction/agent_grid.py:592-596)
   - Called during AgentGrid.start()
   - May block on external API calls or data loading
   - **Impact**: High - blocks agent grid startup

4. **Regime Opinion Loop Start** (merid/prediction/agent_grid.py:632-638)
   - Creates background task during AgentGrid.start()
   - May block on initial opinion collection
   - **Impact**: Medium - background task but may still delay startup

5. **Consensus Cycle in Loop** (merid/loop.py:1052-1058)
   - Called every tick during loop execution
   - May block on consensus computation
   - **Impact**: High - blocks loop cadence

6. **Opinion Submission in Agent Cycle** (merid/loop.py:1545-1633)
   - Called during agent cycle
   - May block on consensus coordinator
   - **Impact**: Medium - blocks agent cycle

### Duplicate Initialization

1. **Consensus Coordinator Singleton**
   - Initialized in loop.py via _consensus_coordinator()
   - Also initialized in agent_grid.py via get_instance()
   - May cause duplicate initialization or race conditions

2. **Sentiment Service**
   - Initialized in agent_grid.py
   - May also be initialized elsewhere via global singleton
   - May cause duplicate initialization

---

## Remediation Plan

### Phase 1: Safe Removal (Low Risk)

**Goal**: Remove DELETE modules without touching active integration points

1. **Delete consensus/ directory entirely**
   - Remove consensus/consensus_coordinator.py
   - Remove consensus/taco_consensus.py
   - Remove consensus/feedback_scheduler.py

2. **Delete merid/sentiment/ directory entirely**
   - Remove all files in merid/sentiment/

3. **Delete core sentiment modules**
   - Remove core/social_sentiment.py
   - Remove core/sentiment_nlp.py

4. **Delete opinion modules**
   - Remove merid/prediction/opinion_strategy.py
   - Remove merid/prediction/market_opinion.py

5. **Delete debate modules**
   - Remove merid/prediction/debate.py
   - Remove merid/prediction/debate_orchestrator.py
   - Remove merid/prediction/debate_backtest.py
   - Remove merid/prediction/debate_deployment.py
   - Remove merid/prediction/debate_exit_policy.py
   - Remove merid/prediction/debate_position_sizing.py

**Verification**: Run test suite to identify any import errors

### Phase 2: Integration Point Removal (High Risk)

**Goal**: Remove legacy integration points from active code

1. **Rewrite merid/loop.py**
   - Remove _consensus_coordinator() method
   - Remove _run_consensus() method
   - Remove consensus_interval from LoopConfig
   - Remove consensus_cycles_run from LoopMetrics
   - Remove _last_consensus timer
   - Remove opinion submission logic

2. **Rewrite merid/prediction/agent_grid.py**
   - Remove sentiment service initialization
   - Remove regime agents initialization
   - Remove stale consensus opinion purge
   - Remove sentiment service start/stop
   - Remove regime opinion loop start/stop
   - Remove market mood bus feed
   - Remove opinion loop and collection

3. **Rewrite merid/prediction/trading_agent.py**
   - Remove consensus_bridge and consensus_aggregator imports
   - Remove get_kalshi_consensus_adapter usage
   - Remove last_consensus_at field
   - Remove _swarm_consensus_bypassed() method
   - Remove consensus bypass checks
   - Remove consensus-based sizing logic
   - Remove sentiment global/regime fields
   - Remove consensus timing checks
   - Remove consensus/sentiment metadata

**Verification**: Run full integration tests, monitor startup time, verify loop cadence

### Phase 3: Test Coverage and Validation

**Goal**: Ensure clean architecture with test coverage

1. **Add regression tests**
   - Startup hang prevention test
   - Double-start prevention test
   - Consensus removal test (verify no consensus imports)
   - No stale opinion store usage test
   - Market catalog bootstrap success test
   - Websocket subscription and snapshot bootstrap test
   - Spot warmup and streaming test
   - Fills poller restore test
   - Settlement poller start test
   - Loop cycle execution test
   - Agent idempotent start behavior test
   - Risk guard enforcement test
   - Config snapshot creation test

2. **Update existing tests**
   - Remove tests asserting legacy consensus behavior
   - Remove tests asserting legacy sentiment behavior
   - Remove tests asserting legacy opinion behavior
   - Remove tests asserting legacy debate behavior

**Verification**: Run full test suite, ensure 100% pass rate

---

## Final Architecture

### Target Architecture Layers

1. **Entry/Orchestration**
   - merid/loop.py (simplified, no consensus/sentiment)
   - merid/prediction/agent_grid.py (simplified, no sentiment/opinion loops)

2. **Venue/Market Data**
   - merid/event_venues/kalshi/market_catalog.py
   - merid/event_venues/kalshi/client.py
   - merid/event_venues/kalshi/ws.py

3. **Spot Pricing**
   - Unified spot service/cache (already exists)

4. **Risk/Guardrails**
   - merid/prediction/venue_gate.py
   - merid/prediction/portfolio_risk_agent.py
   - merid/prediction/portfolio_risk_manager.py

5. **Trading Loop**
   - merid/loop.py (simplified cadence)
   - merid/prediction/trading_agent.py (simplified execution)

6. **Persistence/State**
   - Fills ledger
   - Settlement polling
   - Bankroll service

7. **Tests**
   - Full test coverage for all retained boundaries

---

## Success Criteria

1. **No legacy imports**: No imports of consensus/sentiment/opinion/debate modules in 15m path
2. **No legacy initialization**: No legacy service startup in agent grid or loop
3. **No legacy execution**: No legacy decision logic in trading path
4. **Startup time < 5s**: AgentGrid starts in under 5 seconds
5. **Loop cadence stable**: Loop maintains 30s cadence without consensus overhead
6. **Test coverage 100%**: All retained modules have test coverage
7. **No startup hangs**: No blocking operations during startup
8. **No duplicate initialization**: No singleton race conditions
9. **Explicit dependencies**: All services explicitly dependency-injected
10. **Clean boundaries**: Clear separation between layers

---

## Blockers and Risks

### Blockers

1. **None identified** - All legacy modules can be removed safely

### Risks

1. **High Risk**: Loop rewrite may break loop cadence
   - **Mitigation**: Extensive testing, gradual rollout

2. **High Risk**: AgentGrid rewrite may break agent startup
   - **Mitigation**: Extensive testing, gradual rollout

3. **High Risk**: TradingAgent rewrite may break execution
   - **Mitigation**: Extensive testing, gradual rollout

4. **Medium Risk**: Test suite may have legacy dependencies
   - **Mitigation**: Update tests in parallel with code changes

5. **Low Risk**: Documentation may reference removed modules
   - **Mitigation**: Update documentation in parallel

---

## Next Steps

1. **Review and approve this plan** with stakeholders
2. **Create feature branch** for safe removal (Phase 1)
3. **Execute Phase 1** (safe removal)
4. **Run test suite** to identify import errors
5. **Create feature branch** for integration point removal (Phase 2)
6. **Execute Phase 2** (integration point removal)
7. **Run integration tests** to verify functionality
8. **Execute Phase 3** (test coverage and validation)
9. **Run full test suite** to ensure 100% pass rate
10. **Merge to main** after approval

---

## Appendix: File-by-File Inventory

### DELETE Files

**Consensus (17 files):**
- consensus/consensus_coordinator.py
- consensus/taco_consensus.py
- consensus/feedback_scheduler.py
- merid/prediction/consensus.py
- merid/prediction/consensus_bridge.py
- merid/swarm/consensus_engine.py
- merid/swarm/consensus_aggregator.py
- merid/swarm/consensus_forensics.py
- core/consensus_engine.py
- core/consensus_gate.py
- core/consensus_store.py
- core/consensus_math.py
- core/consensus_logging.py
- core/consensus_graph.py
- merid/lanes/consensus_integration.py
- merid/lanes/consensus_engine_integration.py

**Sentiment (30+ files):**
- merid/sentiment/* (entire directory)
- core/social_sentiment.py
- core/sentiment_nlp.py
- merid/prediction/forecasters/sentiment.py
- merid/prediction/risk/sentiment_vol_types.py
- merid/prediction/risk/sentiment_vol_service.py
- merid/prediction/risk/sentiment_vol_metrics.py

**Opinion (2 files):**
- merid/prediction/opinion_strategy.py
- merid/prediction/market_opinion.py

**Debate (6 files):**
- merid/prediction/debate.py
- merid/prediction/debate_orchestrator.py
- merid/prediction/debate_backtest.py
- merid/prediction/debate_deployment.py
- merid/prediction/debate_exit_policy.py
- merid/prediction/debate_position_sizing.py

### REWRITE Files

**Loop (1 file):**
- merid/loop.py (remove consensus integration)

**Agent Grid (1 file):**
- merid/prediction/agent_grid.py (remove sentiment/opinion integration)

**Trading Agent (1 file):**
- merid/prediction/trading_agent.py (remove consensus/sentiment integration)

### KEEP Files

**Core 15m Infrastructure (15+ files):**
- merid/event_venues/kalshi/market_catalog.py
- merid/event_venues/kalshi/client.py
- merid/event_venues/kalshi/order_router.py
- merid/event_venues/kalshi/ws.py
- merid/event_venues/kalshi/fills_poller.py
- merid/event_venues/kalshi/settlement_poller.py
- merid/prediction/venue_gate.py
- merid/prediction/portfolio_risk_agent.py
- merid/prediction/portfolio_risk_manager.py
- merid/prediction/trading_agent.py (after rewrite)
- merid/prediction/agent_grid.py (after rewrite)
- merid/loop.py (after rewrite)
- merid/prediction/pm_profiles.py
- merid/prediction/startup_validations.py
- merid/guardrails/*
- merid/risk/*
- config/kalshi_agent_grid.yaml
- config/profiles/kalshi_crypto_15m.yaml

---

**Report Generated**: 2026-05-19  
**Status**: Ready for review and approval
