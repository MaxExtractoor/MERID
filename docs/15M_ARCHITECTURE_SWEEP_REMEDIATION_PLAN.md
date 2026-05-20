# 15m Stack Architecture Sweep - File-by-File Remediation Plan

**Date**: 2026-05-19  
**Reference**: 15M_ARCHITECTURE_SWEEP_REPORT.md

---

## 15m Kalshi Stack Non-Negotiables

These are the non-negotiable rules that *must* hold for the 15m Kalshi stack (BTC/ETH/SOL/XRP/DOGE). Any future change or feature must respect these rules. These are enforced in code, config, tests, and CI.

### 1. Asset and Scope Non-Negotiables

#### 1.1 Asset Set is Fixed and Explicit

**Rule**: The 15m Kalshi profile trades only this exact asset set: `BTC, ETH, SOL, XRP, DOGE`. No other assets may appear in 15m config profiles, market selector, UI routes, or risk calculators.

**Enforcement**:
- Config test: `rg "BTC" config/ merid/ -n`, `rg "ETH" config/ merid/ -n`, etc.
- Unit test: Assert that the 15m asset universe returned from `TradingScope` / `MarketSelector` is exactly `{BTC, ETH, SOL, XRP, DOGE}`.
- Single canonical source: `config/kalshi_crypto_15m.yaml` imported everywhere.

**Implemented in**: Phase 9 (Config & Profile Duplicates), Phase 14 (Config & Profile Duplicates)

---

#### 1.2 Timeframe is 15m and Only 15m

**Rule**: The 15m Kalshi profile only operates on 15-minute contracts. No daily/hourly/other timeframes are allowed in the 15m path. Market discovery and filters must enforce timeframe=15m.

**Enforcement**:
- Tests on `KalshiMarketCatalog` and `MarketSelector` verifying all allowed markets for 15m profile have timeframe=15m.
- UI must only list 15m markets when in 15m mode.

**Implemented in**: Phase 5 (Kalshi Parity and Contract Mapping), Phase 17 (Kalshi Fill-Lifecycle Alignment)

---

### 2. Venue and Market Data Non-Negotiables

#### 2.1 Kalshi is the Single Source of Truth

**Rule**: Kalshi venue data is the only authoritative source for market list, metadata, open/close status, order book, trades, fills, settlement, and final PnL. No external or synthetic feed may override Kalshi market state.

**Enforcement**:
- All market-state dependent code (loop/agents/risk) must read from `KalshiMarketCatalog` + `MarketStateStore`, not ad-hoc APIs.
- Tests that injecting fake external states does not bypass Kalshi's states for 15m.

**Implemented in**: Phase 14 (Market State & Catalog Usage), Phase 15 (Upstream Robustness)

---

#### 2.2 Market Catalog and State are Centralized

**Rule**: There is exactly one path for market discovery (catalog) and market health/state (state store). Agents and loop may not hard-code ticker parsing beyond what the catalog/state provide.

**Enforcement**:
- Grep for manual `KXBTC15M`, etc., in agents/loop; replace with calls into the catalog/selector.
- Tests that agents can only trade markets that the catalog reports as allowed.

**Implemented in**: Phase 14 (Market State & Catalog Usage)

---

### 3. Risk and Bankroll Non-Negotiables

#### 3.1 Single Risk Calculator

**Rule**: All order sizing and exposure decisions must go through a single risk engine for the 15m profile. No local per-agent "mini-risk" logic is allowed that contradicts global limits.

**Enforcement**:
- Consolidate all risk calculations into a single `RiskCalculator` / risk service.
- Tests that all sizing paths go through the single calculator.

**Implemented in**: Phase 14 (Risk & Notional Calculations)

---

#### 3.2 Bankroll Single Source of Truth

**Rule**: Bankroll is derived exclusively from Kalshi portfolio/balance API for the live 15m profile. The 15m risk envelope (max cycle % and total %) must be enforced for every order.

**Enforcement**:
- Tests that no order can be created that would violate max per-cycle, per-market, and total risk.
- If bankroll fetch fails or is stale, trading is disabled or degraded to a safe state.

**Implemented in**: Phase 14 (Risk & Notional Calculations), Phase 15 (Downstream Robustness)

---

### 4. Execution and Loop Non-Negotiables

#### 4.1 Deterministic, Non-Reentrant Loop

**Rule**: The 15m loop must run with fixed cadence, never re-enter `tick()` while a previous tick is still running, and fail fast and log on unexpected exceptions without silently dying.

**Enforcement**:
- Non-reentrancy test for `MeridLoop.tick()`.
- All `asyncio.gather()` in the loop uses `return_exceptions=True` with centralized handling.

**Implemented in**: Phase 8 (Loop Cadence Verification), Phase 15 (Midstream Robustness)

---

#### 4.2 No Hidden Background Decision Engines

**Rule**: No consensus/sentiment/opinion/debate engines may influence 15m execution. All execution decisions are explicitly visible in agent code, risk engine, and order router.

**Enforcement**:
- "No consensus/sentiment imports" tests for loop, agent_grid, trading_agent.
- Regression test ensuring 15m loop does not start any background tasks that are not market data, fills/settlement polling, or agent execution.

**Implemented in**: Phase 8 (No Legacy Imports Check), Phase 11 (CI Guard)

---

### 5. Fills, Settlement, and PnL Non-Negotiables

#### 5.1 Fill and Settlement Correctness Over Everything

**Rule**: The 15m stack must never mis-state position size, realized/unrealized PnL, or settlement results. When in doubt (any upstream inconsistency), the system must halt trading, re-sync from Kalshi, and only resume once reconciled.

**Enforcement**:
- Tests with synthetic fill streams for duplicate IDs, reordered fills, late settlements.
- Acceptance criteria: "PnL and positions remain correct under all tested fill lifecycle variants."

**Implemented in**: Phase 15 (Downstream Robustness), Phase 17 (Kalshi Fill-Lifecycle Alignment)

---

#### 5.2 Fills Ledger is Idempotent and Complete

**Rule**: Replaying fills from Kalshi must not double-count. Out-of-order or duplicate fills must not corrupt positions or PnL.

**Enforcement**:
- Tests with synthetic fill streams: duplicate IDs, reordered fills, late settlements.
- Acceptance criteria in the plan: "PnL and positions remain correct under all tested fill lifecycle variants."

**Implemented in**: Phase 15 (Downstream Robustness), Phase 17 (Kalshi Fill-Lifecycle Alignment)

---

### 6. UI/UX and Product Non-Negotiables

#### 6.1 UI Describes Only Real 15m Engine Behavior

**Rule**: Frontend must not expose sentiment, mood, consensus, opinion, debate artifacts or actions that the backend cannot perform. UI for 15m must be limited to market list/state, orders/fills, bankroll/risk, spot overlay, health/connectivity, and agent/loop status.

**Enforcement**:
- UI tests: Route tests for `/markets` verifying only the 5 assets.
- Component tests ensuring no consensus/sentiment widgets are mounted.
- Snapshot tests of the 15m dashboard with golden expectations.

**Implemented in**: Phase 4 (UI/UX Rewrite), Phase 6 (UI Test Coverage)

---

#### 6.2 UI Asset/Timeframe Contract

**Rule**: UI must show only BTC/ETH/SOL/XRP/DOGE in 15m mode and only 15m contracts for those assets. Any presence of other assets or timeframes in 15m screens is a bug.

**Enforcement**:
- UI tests: Route tests for `/markets` verifying only the 5 assets.
- Component tests ensuring only 15m contracts are displayed.
- Snapshot tests of the 15m dashboard with golden expectations.

**Implemented in**: Phase 4 (UI/UX Rewrite), Phase 5 (Kalshi Parity and Contract Mapping), Phase 6 (UI Test Coverage)

---

### 7. Operational and Safety Non-Negotiables

#### 7.1 Automatic Kill-Switch for Unsafe Conditions

**Rule**: The 15m profile must have a clearly defined set of kill conditions (Kalshi WS disconnected beyond X seconds, bankroll stale beyond Y seconds, market catalog corrupt/empty, risk calculations failing). Under kill conditions, new trading is disabled and existing positions are managed only in ways that cannot increase risk.

**Enforcement**:
- Tests for each kill condition.
- Acceptance criteria: Trading disabled under kill conditions, positions managed safely.

**Implemented in**: Phase 15 (Upstream Robustness), Phase 15 (Midstream Robustness)

---

#### 7.2 No Legacy Concepts in Active Paths

**Rule**: Any code path that is reachable from the 15m entrypoints must be free of `sentiment`, `mood`, `consensus`, `opinion`, `debate` concepts. These words may only appear in archived/legacy directories or migration documentation.

**Enforcement**:
- CI guard: Repository-wide grep for legacy concepts that fails if they appear outside `legacy/` or docs.

**Implemented in**: Phase 11 (CI Guard), Phase 12 (CI Guard Acceptance)

---

## Phase 1: Safe Module Deletion (Low Risk)

### 1.1 Delete Consensus Directory

**Command**:
```bash
rm -rf consensus/
```

**Files Deleted**:
- consensus/consensus_coordinator.py (46KB)
- consensus/taco_consensus.py (23KB)
- consensus/feedback_scheduler.py (9KB)

**Verification**:
```bash
# Only enforce in 15m execution domain
grep -r "from consensus" --include="*.py" merid/loop.py merid/prediction/ merid/event_venues/ merid/lanes/ config/
grep -r "import consensus" --include="*.py" merid/loop.py merid/prediction/ merid/event_venues/ merid/lanes/ config/
```

**Expected Errors**: None (consensus only used by legacy swarm, not 15m stack)

**Rollback**: Git revert if unexpected errors

---

### 1.2 Delete Core Consensus Modules

**Commands**:
```bash
rm core/consensus_engine.py
rm core/consensus_gate.py
rm core/consensus_store.py
rm core/consensus_math.py
rm core/consensus_logging.py
rm core/consensus_graph.py
```

**Verification**:
```bash
# Only enforce in 15m execution domain
grep -r "from core.consensus" --include="*.py" merid/loop.py merid/prediction/ merid/event_venues/ merid/lanes/
grep -r "from core import consensus" --include="*.py" merid/loop.py merid/prediction/ merid/event_venues/ merid/lanes/
```

**Expected Errors**: None (only used by legacy swarm)

**Rollback**: Git revert if unexpected errors

---

### 1.3 Delete Swarm Consensus Modules

**Commands**:
```bash
rm merid/swarm/consensus_engine.py
rm merid/swarm/consensus_aggregator.py
rm merid/swarm/consensus_forensics.py
```

**Verification**:
```bash
# Only enforce in 15m execution domain
grep -r "from merid.swarm.consensus" --include="*.py" merid/loop.py merid/prediction/
```

**Expected Errors**: None (only used by legacy swarm)

**Rollback**: Git revert if unexpected errors

---

### 1.4 Delete Lane Consensus Integration

**Commands**:
```bash
rm merid/lanes/consensus_integration.py
rm merid/lanes/consensus_engine_integration.py
```

**Verification**:
```bash
# Only enforce in 15m execution domain
grep -r "from merid.lanes.consensus" --include="*.py" merid/loop.py merid/prediction/ merid/lanes/
```

**Expected Errors**: None (only used by legacy lanes)

**Rollback**: Git revert if unexpected errors

---

### 1.5 Delete Prediction Consensus Modules

**Commands**:
```bash
rm merid/prediction/consensus.py
rm merid/prediction/consensus_bridge.py
```

**Verification**:
```bash
# Only enforce in 15m execution domain
grep -r "from merid.prediction.consensus" --include="*.py" merid/loop.py merid/prediction/
```

**Expected Errors**: 
- merid/loop.py line 716-718 (will be fixed in Phase 2)
- merid/prediction/agent_grid.py line 399-400 (will be fixed in Phase 2)
- merid/prediction/trading_agent.py line 72-73 (will be fixed in Phase 2)

**Rollback**: Git revert if unexpected errors beyond known integration points

---

### 1.6 Delete Sentiment Directory

**Command**:
```bash
rm -rf merid/sentiment/
```

**Files Deleted**:
- merid/sentiment/* (entire directory, ~30 files, ~500KB)

**Verification**:
```bash
# Only enforce in 15m execution domain
grep -r "from merid.sentiment" --include="*.py" merid/prediction/ web/ config/
grep -r "import sentiment" --include="*.py" merid/prediction/ web/ config/
```

**Expected Errors**: 
- merid/prediction/agent_grid.py line 145-146 (will be fixed in Phase 2)
- merid/prediction/trading_agent.py line 3040-3041 (will be fixed in Phase 2)

**Rollback**: Git revert if unexpected errors beyond known integration points

---

### 1.7 Delete Core Sentiment Modules

**Commands**:
```bash
rm core/social_sentiment.py
rm core/sentiment_nlp.py
```

**Verification**:
```bash
# Only enforce in 15m execution domain
grep -r "from core.social_sentiment" --include="*.py" merid/prediction/ web/
grep -r "from core.sentiment_nlp" --include="*.py" merid/prediction/ web/
```

**Expected Errors**: None (only used by legacy agents)

**Rollback**: Git revert if unexpected errors

---

### 1.8 Delete Prediction Sentiment Modules

**Commands**:
```bash
rm merid/prediction/forecasters/sentiment.py
rm merid/prediction/risk/sentiment_vol_types.py
rm merid/prediction/risk/sentiment_vol_service.py
rm merid/prediction/risk/sentiment_vol_metrics.py
```

**Verification**:
```bash
# Only enforce in 15m execution domain
grep -r "from merid.prediction.forecasters.sentiment" --include="*.py" merid/prediction/
grep -r "from merid.prediction.risk.sentiment" --include="*.py" merid/prediction/
```

**Expected Errors**: None (only used by legacy agents)

**Rollback**: Git revert if unexpected errors

---

### 1.9 Delete Opinion Modules

**Commands**:
```bash
rm merid/prediction/opinion_strategy.py
rm merid/prediction/market_opinion.py
```

**Verification**:
```bash
# Only enforce in 15m execution domain
grep -r "from merid.prediction.opinion" --include="*.py" merid/prediction/
```

**Expected Errors**: None (only used by legacy agents)

**Rollback**: Git revert if unexpected errors

---

### 1.10 Delete Debate Modules

**Commands**:
```bash
rm merid/prediction/debate.py
rm merid/prediction/debate_orchestrator.py
rm merid/prediction/debate_backtest.py
rm merid/prediction/debate_deployment.py
rm merid/prediction/debate_exit_policy.py
rm merid/prediction/debate_position_sizing.py
```

**Verification**:
```bash
# Only enforce in 15m execution domain
grep -r "from merid.prediction.debate" --include="*.py" merid/prediction/
```

**Expected Errors**: None (only used by legacy agents)

**Rollback**: Git revert if unexpected errors

---

### 1.11 Run Test Suite

**Command**:
```bash
pytest tests/ -v --tb=short 2>&1 | tee test_results_phase1.txt
```

**Expected**: Import errors only at known integration points (loop, agent_grid, trading_agent)

**Action**: Document all import errors, verify they are at expected locations

**Rollback**: If unexpected errors, review and rollback specific deletions

---

## Phase 2: Integration Point Removal (High Risk)

### 2.1 Rewrite merid/loop.py

**File**: merid/loop.py

**Change 1: Remove _consensus_coordinator() method**
- **Lines**: 716-718
- **Action**: Delete entire method
```python
# DELETE:
def _consensus_coordinator(self):
    from consensus.consensus_coordinator import EnhancedConsensusCoordinator
    return EnhancedConsensusCoordinator.get_instance()
```

**Change 2: Remove _run_consensus() method**
- **Lines**: 1760-1830 (approx)
- **Action**: Delete entire method
```python
# DELETE:
async def _run_consensus(self, summary: Dict):
    """Step 3: Run consensus for active symbols (decay-aware)."""
    # ... entire method ...
```

**Change 3: Remove consensus_interval from LoopConfig**
- **Lines**: 132
- **Action**: Delete field from LoopConfig dataclass
```python
# DELETE:
consensus_interval: float = 120.0  # CRYPTO-15M-ARB: Increased from 60s to 120s to reduce CPU strain
```

**Change 4: Remove consensus_interval from from_paper_config()**
- **Lines**: 206
- **Action**: Delete from return statement
```python
# DELETE:
consensus_interval=pc.consensus_interval,
```

**Change 5: Remove consensus_cycles_run from LoopMetrics**
- **Lines**: 238
- **Action**: Delete field from LoopMetrics dataclass
```python
# DELETE:
consensus_cycles_run: int = 0
```

**Change 6: Remove consensus_cycles_run from to_dict()**
- **Lines**: 261
- **Action**: Delete from to_dict() return
```python
# DELETE:
"consensus_cycles_run": self.consensus_cycles_run,
```

**Change 7: Remove _last_consensus timer**
- **Lines**: 343
- **Action**: Delete field from MeridLoop.__init__
```python
# DELETE:
self._last_consensus = 0.0
```

**Change 8: Remove consensus cycle trigger in tick()**
- **Lines**: 1052-1058
- **Action**: Delete consensus cycle check and call
```python
# DELETE:
if now - self._last_consensus >= self.config.consensus_interval:
    # FIX-3: Log stage boundary - CONSENSUS stage
    logger.info(
        "[CYCLE-TRACE] stage=CONSENSUS_START | tick=%d | correlation_id=%s",
        tick, correlation_id
    )
    parallel_coros.append(self._run_consensus(summary))
```

**Change 9: Remove opinion submission in agent cycle**
- **Lines**: 1545-1633
- **Action**: Delete entire opinion submission block
```python
# DELETE:
# Submit actionable signals to consensus coordinator as AgentOpinions
if actionable_signals:
    # ... entire opinion submission logic ...
```

**Verification**:
```bash
# Only enforce in 15m execution domain
grep -n "consensus" merid/loop.py
# Should return only comments/docstrings, no active code
```

**Test**:
```bash
pytest tests/test_loop.py -v --tb=short
```

**Rollback**: Git revert if tests fail

---

### 2.2 Rewrite merid/prediction/agent_grid.py

**File**: merid/prediction/agent_grid.py

**Change 1: Remove sentiment service initialization**
- **Lines**: 145-146
- **Action**: Delete sentiment service init
```python
# DELETE:
# REMOVED: Sentiment service - not used in 15m stack
self._sentiment = None
```

**Change 2: Remove regime agents initialization**
- **Lines**: 163-165
- **Action**: Delete regime agents init
```python
# DELETE:
# REMOVED: Regime agents (consensus) - not used in 15m stack
self._regime_agents: List[Any] = []
self._opinion_loop_task: Optional[asyncio.Task] = None
```

**Change 3: Remove stale consensus opinion purge**
- **Lines**: 397-403
- **Action**: Delete consensus purge logic
```python
# DELETE:
# Purge stale consensus opinions from before this startup (BUG-L8)
try:
    from consensus.consensus_coordinator import EnhancedConsensusCoordinator
    EnhancedConsensusCoordinator.get_instance().clear_stale_opinions(max_age_s=60)
    logger.info("✓ Stale consensus opinions purged (>60s)")
except Exception as _cce:
    logger.error("[STALE_OPINION_PURGE_FAILED] Stale consensus opinion purge failed: %s", _cce)
```

**Change 4: Remove sentiment service start**
- **Lines**: 592-596
- **Action**: Delete sentiment service start call
```python
# DELETE:
# Start sentiment service background loop
_t_sentiment_start = _timing.time()
await self._sentiment.start()
_t_sentiment_elapsed = (_timing.time() - _t_sentiment_start) * 1000
logger.info(f"[TIMING] Sentiment service started in {_t_sentiment_elapsed:.0f}ms")
```

**Change 5: Remove market mood bus start**
- **Lines**: 632 (approx)
- **Action**: Delete market mood bus start call
```python
# DELETE:
# Start market mood bus (unified sentiment aggregation)
await self._mood_bus.start()
```

**Change 6: Remove regime opinion loop start**
- **Lines**: 632-638 (approx)
- **Action**: Delete opinion loop start
```python
# DELETE:
# Start per-asset regime agent opinion loop (non-critical — guarded)
if self._regime_agents:
    self._opinion_loop_task = asyncio.create_task(
        self._opinion_loop(), name="kalshi-regime-opinions"
    )
    self._opinion_loop_task.add_done_callback(_bg_task_done_cb)
    logger.info("✓ Regime agent opinion loop started (%d agents)", len(self._regime_agents))
```

**Change 7: Remove sentiment service stop**
- **Lines**: 1030-1031
- **Action**: Delete sentiment service stop call
```python
# DELETE:
# Stop sentiment service
await self._sentiment.stop()
```

**Change 8: Remove regime opinion loop stop**
- **Lines**: 1055-1063
- **Action**: Delete opinion loop stop
```python
# DELETE:
# Stop regime opinion loop
if self._opinion_loop_task and not self._opinion_loop_task.done():
    self._opinion_loop_task.cancel()
    try:
        await self._opinion_loop_task
    except asyncio.CancelledError:
        pass
    self._opinion_loop_task = None  # CLEAR-FIX: Prevent double-cancel
```

**Change 9: Remove market mood bus feed**
- **Lines**: 1257-1315
- **Action**: Delete entire _feed_mood_bus() method
```python
# DELETE:
async def _feed_mood_bus(self) -> None:
    """Feed live Kalshi market data into MarketMoodBus for sentiment aggregation."""
    # ... entire method ...
```

**Change 10: Remove opinion loop**
- **Lines**: 1315-1364
- **Action**: Delete _opinion_loop() and _collect_regime_opinions() methods
```python
# DELETE:
async def _opinion_loop(self) -> None:
    """Background loop: collect per-asset regime opinions and submit to TaCo consensus."""
    # ... entire method ...

async def _collect_regime_opinions(self) -> None:
    """Call get_opinion() on every regime agent and submit non-None results to TaCo."""
    # ... entire method ...
```

**Change 11: Remove market mood bus init**
- **Lines**: Search for _mood_bus initialization
- **Action**: Delete _mood_bus field and initialization

**Verification**:
```bash
# Only enforce in 15m execution domain
grep -n "sentiment\|consensus\|opinion" merid/prediction/agent_grid.py
# Should return only comments/docstrings, no active code
```

**Test**:
```bash
pytest tests/prediction/test_agent_grid.py -v --tb=short
```

**Rollback**: Git revert if tests fail

---

### 2.3 Rewrite merid/prediction/trading_agent.py

**File**: merid/prediction/trading_agent.py

**Change 1: Remove consensus imports**
- **Lines**: 72-73
- **Action**: Delete consensus_bridge and consensus_aggregator imports
```python
# DELETE:
from merid.prediction.consensus_bridge import get_kalshi_consensus_adapter
from merid.swarm.consensus_aggregator import get_consensus_aggregator
```

**Change 2: Remove last_consensus_at field**
- **Lines**: 1179
- **Action**: Delete from AgentState dataclass
```python
# DELETE:
last_consensus_at: Optional[datetime] = None
```

**Change 3: Remove last_consensus_at from to_dict()**
- **Lines**: 1202
- **Action**: Delete from to_dict() return
```python
# DELETE:
"last_consensus_at": self.last_consensus_at.isoformat() if self.last_consensus_at else None,
```

**Change 4: Remove _swarm_consensus_bypassed() method**
- **Lines**: 1845-1890
- **Action**: Delete entire method
```python
# DELETE:
def _swarm_consensus_bypassed(self) -> bool:
    """SAFETY: All consensus bypass mechanisms are HARD-DISABLED."""
    # ... entire method ...
```

**Change 5: Remove consensus bypass check**
- **Lines**: 2153
- **Action**: Delete consensus bypass check in sizing logic
```python
# DELETE:
if _solo_s > 0 and not self._swarm_consensus_bypassed():
```

**Change 6: Remove consensus-based sizing**
- **Lines**: 2315, 2379-2386
- **Action**: Delete consensus_count and consensus_multiplier logic
```python
# DELETE:
consensus_count = getattr(signal, 'consensus_count', 1)
# ...
# Consensus-based sizing: increase size if multiple agents agree
# Base size * (1 + 0.25 * (consensus_count - 1)), capped at 2x
consensus_multiplier = min(2.0, 1.0 + 0.25 * (consensus_count - 1))
adjusted_size = int(signal.size * consensus_multiplier) if signal.size else 1

if consensus_count > 1:
    logger.info(
        "[SIGNAL-IN] Consensus boost: %s agents agree, size %s -> %s",
        consensus_count, signal.size, adjusted_size
    )
```

**Change 7: Remove sentiment snapshot fields**
- **Lines**: 3040-3041
- **Action**: Delete sentiment_global and sentiment_regime from snapshot
```python
# DELETE:
snapshot.sentiment_global = float(mood_context.fg_index)
snapshot.sentiment_regime = mood_context.volatility_regime.value
```

**Change 8: Remove consensus timing checks**
- **Lines**: 3216, 3222, 3258, 3408-3409
- **Action**: Delete consensus timing checks
```python
# DELETE:
if self._swarm_consensus_bypassed():
# ...
self.state.last_consensus_at = now
# ...
self.state.last_consensus_at = now
# ...
(now - self.state.last_consensus_at).total_seconds()
```

**Change 9: Remove consensus/sentiment metadata**
- **Lines**: 6305, 6770-6775
- **Action**: Delete consensus_bypassed and sentiment metadata
```python
# DELETE:
consensus_bypassed=consensus_bypassed or self._swarm_consensus_bypassed(),
# ...
fear_greed=int(getattr(snapshot, 'sentiment_global', 0.5) * 100)
getattr(snapshot, 'sentiment_global', None) is not None else None,
session_stable=getattr(snapshot, 'sentiment_regime', 'normal') != 'extreme_volatility',
```

**Change 10: Remove sentiment score usage**
- **Lines**: 8336-8338
- **Action**: Delete sentiment score usage
```python
# DELETE:
sent_score = getattr(snapshot, "sentiment_global", None)
# sentiment_global can be either:
```

**Change 11: Remove consensus adapter usage**
- **Lines**: 8425-8432
- **Action**: Delete get_kalshi_consensus_adapter usage
```python
# DELETE:
proposal = get_kalshi_consensus_adapter().signal_to_proposal(
    signal=signal,
    agent_id=self.config.agent_id,
    asset=asset,
    timeframe=timeframe,
    archetype=self.config.archetype,
    live_markets=self._live_markets,
    track_record=getattr(self, "_track_record", None),
)
```

**Verification**:
```bash
# Only enforce in 15m execution domain
grep -n "consensus\|sentiment" merid/prediction/trading_agent.py
# Should return only comments/docstrings, no active code
```

**Test**:
```bash
pytest tests/prediction/test_trading_agent.py -v --tb=short
```

**Rollback**: Git revert if tests fail

---

### 2.4 Add Profile-Level Assertion

**Command**:
```bash
# Sanity: 15m profile is independent of consensus/sentiment
grep -r "kalshicrypto15mv2" -n . | head -20
grep -r "kalshicrypto15m" -n . | grep -i "consensus\|sentiment\|opinion\|debate" || echo "OK: 15m profile clean"
```

**Expected**: No consensus/sentiment/opinion/debate references in 15m profile code

**Action**: Document any unexpected references, verify they are not in critical path

---

### 2.5 Run Integration Tests

**Command**:
```bash
pytest tests/ -v --tb=short 2>&1 | tee test_results_phase2.txt
```

**Expected**: All tests pass (or only tests specifically for removed features fail)

**Action**: 
1. Document all test failures
2. Determine if failures are expected (tests for removed features)
3. Update or remove tests for removed features

**Rollback**: If unexpected test failures, review and rollback specific changes

---

## Phase 3: Test Coverage and Validation

### 3.1 Add Startup Hang Prevention Test

**File**: tests/test_startup_hang_prevention.py (new)

**Content**:
```python
"""Test startup hang prevention for 15m stack."""

import asyncio
import time
import pytest

from merid.prediction.agent_grid import get_agent_grid


@pytest.mark.asyncio
async def test_agent_grid_startup_time():
    """AgentGrid should start in under 5 seconds."""
    start = time.time()
    grid = get_agent_grid()
    await grid.start()
    elapsed = time.time() - start
    await grid.stop()

    assert elapsed < 5.0, f"AgentGrid startup took {elapsed:.2f}s, expected < 5s"


@pytest.mark.asyncio
async def test_no_consensus_imports():
    """Verify no consensus imports in 15m path."""
    import merid.loop
    import merid.prediction.agent_grid
    import merid.prediction.trading_agent

    loop_source = open(merid.loop.__file__, encoding="utf-8").read()
    grid_source = open(merid.prediction.agent_grid.__file__, encoding="utf-8").read()
    agent_source = open(merid.prediction.trading_agent.__file__, encoding="utf-8").read()

    for src in (loop_source, grid_source, agent_source):
        assert "from consensus" not in src
        assert "import consensus" not in src


@pytest.mark.asyncio
async def test_no_sentiment_imports():
    """Verify no sentiment imports in 15m path."""
    import merid.prediction.agent_grid
    import merid.prediction.trading_agent

    grid_source = open(merid.prediction.agent_grid.__file__, encoding="utf-8").read()
    agent_source = open(merid.prediction.trading_agent.__file__, encoding="utf-8").read()

    for src in (grid_source, agent_source):
        assert "from merid.sentiment" not in src
        assert "import sentiment" not in src
```

**Test**:
```bash
pytest tests/test_startup_hang_prevention.py -v --tb=short
```

---

### 3.2 Remove Legacy Tests

**Files to Remove**:
- tests/test_consensus.py
- tests/test_consensus_bridge.py
- tests/test_consensus_engine.py
- tests/test_consensus_loop2.py
- tests/test_consensus_loop3.py
- tests/test_consensus_loop4.py
- tests/test_consensus_store_hardening.py
- tests/test_consensus_vertical_slice.py
- tests/test_prediction_consensus.py
- tests/test_market_opinion_invariants.py
- tests/prediction/test_opinion_strategy.py
- tests/prediction/test_crypto_opinion_strategies.py
- tests/legacy/research_sentiment/*.py (all sentiment tests)
- tests/strategies/test_sentiment_swarm_execution.py

**Commands**:
```bash
rm tests/test_consensus.py
rm tests/test_consensus_bridge.py
rm tests/test_consensus_engine.py
rm tests/test_consensus_loop2.py
rm tests/test_consensus_loop3.py
rm tests/test_consensus_loop4.py
rm tests/test_consensus_store_hardening.py
rm tests/test_consensus_vertical_slice.py
rm tests/test_prediction_consensus.py
rm tests/test_market_opinion_invariants.py
rm tests/prediction/test_opinion_strategy.py
rm tests/prediction/test_crypto_opinion_strategies.py
rm -rf tests/legacy/research_sentiment/
rm tests/strategies/test_sentiment_swarm_execution.py
```

**Verification**:
```bash
pytest tests/ --collect-only | grep -i "consensus\|sentiment\|opinion\|debate"
# Should return no test files
```

**Action**: Remove or update these tests to not assert legacy sentiment behavior

---

### 3.5 Run Full Test Suite

**Command**:
```bash
pytest tests/ -v --tb=short 2>&1 | tee test_results_phase3.txt
```

**Expected**: 100% pass rate for retained features

**Action**: 
1. Document any remaining failures
2. Fix or remove failing tests
3. Verify all critical 15m path tests pass

**Rollback**: If critical tests fail, review and rollback specific changes

---

## Phase 4: UI/UX Rewrite

### 4.1 Remove Legacy UI Components

**Files to Delete**:
- `web/react/src/components/ConsensusBoard.tsx` - Legacy consensus display
- `web/react/src/components/ConsensusPanel.tsx` - Legacy consensus panel
- `web/react/src/components/ConsensusPill.tsx` - Legacy consensus indicator
- `web/react/src/components/DebateCorrelationPanel.tsx` - Legacy debate correlation display
- `web/react/src/components/SentimentMeter.tsx` (if exists) - Legacy sentiment display
- `web/react/src/components/MoodIndex.tsx` (if exists) - Legacy mood display
- `web/react/src/components/OpinionLadder.tsx` (if exists) - Legacy opinion display
- `web/react/src/components/DebateRoom.tsx` (if exists) - Legacy debate room
- `web/react/src/components/ForecastConfidence.tsx` (if exists) - Legacy confidence display

**Commands**:
```bash
rm web/react/src/components/ConsensusBoard.tsx
rm web/react/src/components/ConsensusPanel.tsx
rm web/react/src/components/ConsensusPill.tsx
rm web/react/src/components/DebateCorrelationPanel.tsx
```

**Verification**:
```bash
grep -r "ConsensusBoard\|ConsensusPanel\|ConsensusPill" --include="*.tsx" web/react/src/
grep -r "DebateCorrelationPanel" --include="*.tsx" web/react/src/
# Should return no references after deletion
```

**Rollback**: Git revert if unexpected errors

---

### 4.2 Remove Navigation and Sidebar Items

**File**: `web/react/src/App.tsx` (or navigation/routing file)

**Legacy Routes to Remove**:
- `/consensus` - Consensus dashboard
- `/debate` - Debate room
- `/sentiment` - Sentiment analysis
- `/opinion` - Opinion ladder
- `/mood` - Mood index
- `/swarm` - Swarm consensus (if not used by 15m)

**Action**: Remove route definitions and navigation menu items

**Verification**:
```bash
grep -r "consensus\|debate\|sentiment\|opinion\|mood" --include="*.tsx" web/react/src/App.tsx
# Should return no route definitions
```

**Rollback**: Git revert if unexpected errors

---

### 4.3 Remove Legacy Dashboard Cards

**File**: `web/react/src/components/Dashboard.tsx` (or main dashboard)

**Legacy Cards to Remove**:
- Sentiment meter card
- Mood index card
- Consensus strength card
- Opinion distribution card
- Debate activity card
- Forecast confidence card

**Action**: Remove card components from dashboard layout

**Verification**:
```bash
grep -r "SentimentMeter\|MoodIndex\|ConsensusStrength\|OpinionDistribution\|DebateActivity\|ForecastConfidence" --include="*.tsx" web/react/src/
# Should return no references
```

**Rollback**: Git revert if unexpected errors

---

### 4.4 Rewrite Dashboard for 15m Execution Spine

**File**: `web/react/src/components/Dashboard.tsx` (or main dashboard)

**New Dashboard Cards**:
- Market Health Panel - Shows 15m market catalog health
- Loop Status Panel - Shows loop tick cadence and state
- Order State Panel - Shows active orders and execution status
- Fills Panel - Shows recent fills and settlement
- Risk Panel - Shows bankroll, exposure, and risk limits
- Spot Panel - Shows spot price feeds for 5 assets
- Connectivity Panel - Shows websocket and API connectivity
- Agent Status Panel - Shows 5 trading agents status (BTC_15M, ETH_15M, SOL_15M, XRP_15M, DOGE_15M)

**Action**: Replace legacy cards with execution-centric cards

**Verification**:
```bash
# Run UI tests
cd web/react
npm test -- Dashboard.test.tsx
```

**Rollback**: Git revert if tests fail

---

### 4.5 Rewrite Market Detail Panel

**File**: `web/react/src/components/MarketDetailPanel.tsx` (or market detail component)

**Legacy Fields to Remove**:
- Sentiment score
- Mood index
- Consensus percentage
- Opinion distribution
- Debate link
- Forecast confidence

**New Fields to Add/Keep**:
- Market ticker (KXBTC15M, KXETH15M, etc.)
- Market state (open/closed/settled)
- Best bid/ask
- Mid price
- Spread
- Spot price overlay
- Market expiration
- Tick size
- Contract size
- Last trade time
- Order book depth (if available)

**Action**: Rewrite component to show only execution-relevant fields

**Verification**:
```bash
cd web/react
npm test -- MarketDetailPanel.test.tsx
```

**Rollback**: Git revert if tests fail

---

### 4.6 Rewrite Copy to Match Live Trading Workflow

**Files to Update**:
- All component files with legacy copy
- Documentation strings
- Help text

**Legacy Copy to Replace**:
- "Swarm consensus" → "Market state"
- "Mood index" → "Market sentiment" (if still relevant) or remove
- "Opinion distribution" → "Position distribution" (if still relevant) or remove
- "Debate room" → Remove
- "Forecast confidence" → "Execution confidence" (if still relevant) or remove
- "Swarm judgment" → "System state"

**New Copy**:
- "What is the 15m system doing right now?"
- "Is it safe to trade?"
- "Market health"
- "Execution status"
- "Risk exposure"
- "Connectivity"

**Action**: Search and replace legacy copy throughout UI

**Verification**:
```bash
grep -r "swarm consensus\|mood index\|opinion distribution\|debate room\|forecast confidence\|swarm judgment" --include="*.tsx" web/react/src/
# Should return no results after replacement
```

**Rollback**: Git revert if unexpected errors

---

### 4.7 Define New 15m Screen Map

**File**: `web/react/src/App.tsx` (or routing file)

**New Routes**:
- `/` - Dashboard (execution spine)
- `/markets` - Market list (15m only)
- `/markets/:ticker` - Market detail (KXBTC15M, etc.)
- `/orders` - Order state panel
- `/fills` - Fills and settlement
- `/risk` - Risk and exposure
- `/health` - Loop and connectivity health
- `/agents` - Agent status (5 trading agents)

**Action**: Define new route structure

**Verification**:
```bash
cd web/react
npm test -- App.test.tsx
```

**Rollback**: Git revert if tests fail

---

## Phase 5: Kalshi Parity and Contract Mapping

### 5.1 Validate Ticker/Asset Labels

**File**: `web/react/src/components/MarketList.tsx` (or market list component)

**Validation**:
- Only show 5 assets: BTC, ETH, SOL, XRP, DOGE
- Use Kalshi ticker conventions: KXBTC15M, KXETH15M, KXSOL15M, KXXRP15M, KXDOGE15M
- Match backend market catalog semantics

**Action**: Update component to filter to 5 assets, use correct tickers

**Verification**:
```bash
cd web/react
npm test -- MarketList.test.tsx
```

**Rollback**: Git revert if tests fail

---

### 5.2 Validate Supported Actions and State Transitions

**File**: `web/react/src/components/MarketDetailPanel.tsx` (or market detail component)

**Validation**:
- Only show actions supported by Kalshi: buy yes, buy no, cancel order
- Hide unsupported actions: sell yes, sell no (if not supported)
- Match Kalshi market state transitions: open → closed → settled

**Action**: Update component to only show supported actions

**Verification**:
```bash
cd web/react
npm test -- MarketDetailPanel.test.tsx
```

**Rollback**: Git revert if tests fail

---

### 5.3 Remove Unsupported UI Affordances

**Files**: All UI components

**Unsupported Affordances to Remove**:
- Controls for consensus submission
- Controls for opinion voting
- Controls for debate participation
- Controls for mood adjustment
- Controls for forecast confidence setting
- Any control that suggests retired subsystem interaction

**Action**: Remove or disable unsupported controls

**Verification**:
```bash
grep -r "consensus.*submit\|opinion.*vote\|debate.*participate\|mood.*adjust\|forecast.*confidence" --include="*.tsx" web/react/src/
# Should return no results after removal
```

**Rollback**: Git revert if unexpected errors

---

### 5.4 Validate Display Names Match Backend Market Catalog

**File**: `web/react/src/components/MarketList.tsx` (or market list component)

**Validation**:
- Display names match Kalshi market catalog: "BTC 15min", "ETH 15min", etc.
- Use same terminology as backend: "series ticker", "market ID", "expiration"
- Match backend market state labels: "open", "closed", "settled"

**Action**: Update display names to match backend semantics

**Verification**:
```bash
# Compare UI display names with backend market catalog
curl http://localhost:8000/api/v1/kalshi/markets | jq '.[].title'
# Should match UI display names
```

**Rollback**: Git revert if unexpected errors

---

### 5.5 Ensure UI Driven by Same Source of Truth as Backend

**File**: `web/react/src/components/MarketList.tsx` (or market list component)

**Validation**:
- UI uses backend API `/api/v1/kalshi/markets` for market list
- UI uses backend API `/api/v1/kalshi/markets/:ticker` for market detail
- UI does not use static mocks or older product assumptions

**Action**: Update component to use backend API

**Verification**:
```bash
grep -r "mock.*market\|static.*market\|hardcoded.*ticker" --include="*.tsx" web/react/src/
# Should return no results after update
```

**Rollback**: Git revert if unexpected errors

---

## Phase 6: UI Test Coverage

### 6.1 Add Component Tests for Removed Legacy UI Elements

**File**: `web/react/src/__tests__/LegacyUIRemoval.test.tsx` (new)

**Content**:
```typescript
import { render, screen } from '@testing-library/react';
import App from '../App';

describe('Legacy UI Elements Removal', () => {
  test('should not render consensus components', () => {
    render(<App />);
    expect(screen.queryByText(/consensus/i)).not.toBeInTheDocument();
  });

  test('should not render sentiment components', () => {
    render(<App />);
    expect(screen.queryByText(/sentiment/i)).not.toBeInTheDocument();
  });

  test('should not render opinion components', () => {
    render(<App />);
    expect(screen.queryByText(/opinion/i)).not.toBeInTheDocument();
  });

  test('should not render debate components', () => {
    render(<App />);
    expect(screen.queryByText(/debate/i)).not.toBeInTheDocument();
  });

  test('should not render mood components', () => {
    render(<App />);
    expect(screen.queryByText(/mood/i)).not.toBeInTheDocument();
  });
});
```

**Test**:
```bash
cd web/react
npm test -- LegacyUIRemoval.test.tsx
```

**Rollback**: Git revert if tests fail

---

### 6.2 Add Regression Tests to Ensure Consensus/Sentiment Widgets Do Not Render

**File**: `web/react/src/__tests__/NoConsensusSentimentRegression.test.tsx` (new)

**Content**:
```typescript
import { render, screen } from '@testing-library/react';
import Dashboard from '../components/Dashboard';

describe('No Consensus/Sentiment Regression', () => {
  test('dashboard should not show consensus panel', () => {
    render(<Dashboard />);
    expect(screen.queryByTestId('consensus-panel')).not.toBeInTheDocument();
  });

  test('dashboard should not show sentiment meter', () => {
    render(<Dashboard />);
    expect(screen.queryByTestId('sentiment-meter')).not.toBeInTheDocument();
  });

  test('dashboard should not show opinion ladder', () => {
    render(<Dashboard />);
    expect(screen.queryByTestId('opinion-ladder')).not.toBeInTheDocument();
  });

  test('dashboard should not show debate room', () => {
    render(<Dashboard />);
    expect(screen.queryByTestId('debate-room')).not.toBeInTheDocument();
  });
});
```

**Test**:
```bash
cd web/react
npm test -- NoConsensusSentimentRegression.test.tsx
```

**Rollback**: Git revert if tests fail

---

### 6.3 Add Snapshot Tests for New 15m Dashboard

**File**: `web/react/src/__tests__/Dashboard15mSnapshot.test.tsx` (new)

**Content**:
```typescript
import { render } from '@testing-library/react';
import Dashboard from '../components/Dashboard';

describe('15m Dashboard Snapshot', () => {
  test('should match snapshot', () => {
    const { asFragment } = render(<Dashboard />);
    expect(asFragment()).toMatchSnapshot();
  });
});
```

**Test**:
```bash
cd web/react
npm test -- Dashboard15mSnapshot.test.tsx
```

**Rollback**: Git revert if tests fail

---

### 6.4 Add Route Tests for Minimal Navigation Model

**File**: `web/react/src/__tests__/Navigation15m.test.tsx` (new)

**Content**:
```typescript
import { render, screen } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';
import App from '../App';

const renderWithRouter = (ui) => {
  return render(<BrowserRouter>{ui}</BrowserRouter>);
};

describe('15m Navigation Routes', () => {
  test('should render dashboard at root', () => {
    renderWithRouter(<App />);
    expect(screen.getByText(/dashboard/i)).toBeInTheDocument();
  });

  test('should render markets at /markets', () => {
    renderWithRouter(<App />);
    // Navigate to /markets
    // Verify markets page renders
  });

  test('should not render consensus route', () => {
    renderWithRouter(<App />);
    // Try to navigate to /consensus
    // Verify 404 or redirect
  });

  test('should not render debate route', () => {
    renderWithRouter(<App />);
    // Try to navigate to /debate
    // Verify 404 or redirect
  });
});
```

**Test**:
```bash
cd web/react
npm test -- Navigation15m.test.tsx
```

**Rollback**: Git revert if tests fail

---

### 6.5 Add Contract-Mapping Tests for Valid Kalshi 15m Assets

**File**: `web/react/src/__tests__/Kalshi15mContractMapping.test.tsx` (new)

**Content**:
```typescript
import { render, screen } from '@testing-library/react';
import MarketList from '../components/MarketList';

describe('Kalshi 15m Contract Mapping', () => {
  test('should only show 5 crypto assets', () => {
    render(<MarketList />);
    const assets = screen.getAllByTestId(/market-/i);
    expect(assets).toHaveLength(5);
  });

  test('should use correct 15m tickers', () => {
    render(<MarketList />);
    expect(screen.getByText(/KXBTC15M/i)).toBeInTheDocument();
    expect(screen.getByText(/KXETH15M/i)).toBeInTheDocument();
    expect(screen.getByText(/KXSOL15M/i)).toBeInTheDocument();
    expect(screen.getByText(/KXXRP15M/i)).toBeInTheDocument();
    expect(screen.getByText(/KXDOGE15M/i)).toBeInTheDocument();
  });

  test('should not show other assets', () => {
    render(<MarketList />);
    expect(screen.queryByText(/KXSPY/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/KXGOLD/i)).not.toBeInTheDocument();
  });
});
```

**Test**:
```bash
cd web/react
npm test -- Kalshi15mContractMapping.test.tsx
```

**Rollback**: Git revert if tests fail

---

## Phase 7: Documentation Updates

### 7.1 Update Architecture Documentation

**Files to Update**:
- docs/README.md
- docs/architecture.md (if exists)
- docs/15m_stack.md (if exists)

**Action**: Remove references to consensus/sentiment/opinion/debate layers

---

### 7.2 Update API Documentation

**Files to Update**:
- web/api/consensus_api.py (remove or deprecate)
- web/api/sentiment_api.py (remove or deprecate)
- web/api/debate_api.py (remove or deprecate)

**Action**: Remove or deprecate legacy API endpoints

---

### 7.3 Update UI Documentation

**Files to Update**:
- web/README.md
- docs/UI_ARCHITECTURE.md (if exists)
- Component documentation

**Action**: Document new 15m screen map and execution-centric UI

---

## Phase 8: Final Verification

### 8.1 Startup Time Benchmark

**Command**:
```python
import time
from merid.prediction.agent_grid import get_agent_grid

start = time.time()
grid = get_agent_grid()
await grid.start()
elapsed = time.time() - start
await grid.stop()

print(f"Startup time: {elapsed:.2f}s")
assert elapsed < 5.0, f"Startup too slow: {elapsed:.2f}s"
```

**Expected**: < 5 seconds

---

### 8.2 Loop Cadence Verification

**Command**:
```python
import time
from merid.loop import MeridLoop

loop = MeridLoop()
start = time.time()
await loop.tick()
elapsed = time.time() - start

print(f"Loop tick time: {elapsed:.2f}s")
assert elapsed < 10.0, f"Loop tick too slow: {elapsed:.2f}s"
```

**Expected**: < 10 seconds per tick (without consensus overhead)

---

### 8.3 Memory Usage Check

**Command**:
```python
import psutil
import os

process = psutil.Process(os.getpid())
mem_before = process.memory_info().rss / 1024 / 1024

# Start system
from merid.prediction.agent_grid import get_agent_grid
grid = get_agent_grid()
await grid.start()

mem_after = process.memory_info().rss / 1024 / 1024
mem_increase = mem_after - mem_before

print(f"Memory increase: {mem_increase:.2f}MB")
await grid.stop()

assert mem_increase < 100, f"Memory increase too high: {mem_increase:.2f}MB"
```

**Expected**: < 100MB increase (without consensus/sentiment overhead)

---

### 8.4 No Legacy Imports Check

**Command**:
```bash
# Only enforce in 15m execution domain
grep -r "from consensus" --include="*.py" merid/loop.py merid/prediction/ merid/event_venues/ merid/lanes/ config/ | grep -v "# " | grep -v "\"\"\""
grep -r "from merid.sentiment" --include="*.py" merid/prediction/ web/ config/ | grep -v "# " | grep -v "\"\"\""
grep -r "from merid.prediction.opinion" --include="*.py" merid/prediction/ | grep -v "# " | grep -v "\"\"\""
grep -r "from merid.prediction.debate" --include="*.py" merid/prediction/ | grep -v "# " | grep -v "\"\"\""
```

**Expected**: No results (all legacy imports removed)

---

## Rollback Plan

### Branch-Safe Rollback Strategy

**Important**: Create a dedicated feature branch for each phase to enable safe rollouts and rollbacks.

```bash
# Create branch for Phase 1
git checkout -b feature/15m-sweep-phase1
# Execute Phase 1, commit changes
git add .
git commit -m "Phase 1: Delete legacy consensus/sentiment/opinion/debate modules"

# Create branch for Phase 2 (from Phase 1)
git checkout -b feature/15m-sweep-phase2
# Execute Phase 2, commit changes
git add .
git commit -m "Phase 2: Remove integration points from loop/agent_grid/trading_agent"

# Create branch for Phase 3 (from Phase 2)
git checkout -b feature/15m-sweep-phase3
# Execute Phase 3, commit changes
git add .
git commit -m "Phase 3: Add test coverage and validation"

# Create branch for Phase 4 (from Phase 3)
git checkout -b feature/15m-sweep-phase4
# Execute Phase 4, commit changes
git add .
git commit -m "Phase 4: UI/UX rewrite - remove legacy components"

# Create branch for Phase 5 (from Phase 4)
git checkout -b feature/15m-sweep-phase5
# Execute Phase 5, commit changes
git add .
git commit -m "Phase 5: Kalshi parity and contract mapping"

# Create branch for Phase 6 (from Phase 5)
git checkout -b feature/15m-sweep-phase6
# Execute Phase 6, commit changes
git add .
git commit -m "Phase 6: UI test coverage"

# Create branch for Phase 7 (from Phase 6)
git checkout -b feature/15m-sweep-phase7
# Execute Phase 7, commit changes
git add .
git commit -m "Phase 7: Documentation updates"

# Create branch for Phase 8 (from Phase 7)
git checkout -b feature/15m-sweep-phase8
# Execute Phase 8, commit changes
git add .
git commit -m "Phase 8: Final verification"

# Create branch for Phase 9 (from Phase 8)
git checkout -b feature/15m-sweep-phase9
# Execute Phase 9, commit changes
git add .
git commit -m "Phase 9: Config, profiles, and feature flags"

# Create branch for Phase 10 (from Phase 9)
git checkout -b feature/15m-sweep-phase10
# Execute Phase 10, commit changes
git add .
git commit -m "Phase 10: Observability, deployment, and security"

# Create branch for Phase 11 (from Phase 10)
git checkout -b feature/15m-sweep-phase11
# Execute Phase 11, commit changes
git add .
git commit -m "Phase 11: Global no-legacy guard and CI"

# Create branch for Phase 12 (from Phase 11)
git checkout -b feature/15m-sweep-phase12
# Execute Phase 12, commit changes
git add .
git commit -m "Phase 12: Final cross-cutting acceptance"

# Create branch for Phase 13 (from Phase 12)
git checkout -b feature/15m-sweep-phase13
# Execute Phase 13, commit changes
git add .
git commit -m "Phase 13: End-to-end 15m path inventory"

# Create branch for Phase 14 (from Phase 13)
git checkout -b feature/15m-sweep-phase14
# Execute Phase 14, commit changes
git add .
git commit -m "Phase 14: Duplicate detection and consolidation"

# Create branch for Phase 15 (from Phase 14)
git checkout -b feature/15m-sweep-phase15
# Execute Phase 15, commit changes
git add .
git commit -m "Phase 15: Robustness gaps"

# Create branch for Phase 16 (from Phase 15)
git checkout -b feature/15m-sweep-phase16
# Execute Phase 16, commit changes
git add .
git commit -m "Phase 16: Performance and optimization for 15m"

# Create branch for Phase 17 (from Phase 16)
git checkout -b feature/15m-sweep-phase17
# Execute Phase 17, commit changes
git add .
git commit -m "Phase 17: Kalshi fill-lifecycle alignment"

# Create branch for Phase 18 (from Phase 17)
git checkout -b feature/15m-sweep-phase18
# Execute Phase 18, commit changes
git add .
git commit -m "Phase 18: Consolidation & flaw checklist"

# Create branch for Phase 19 (from Phase 18)
git checkout -b feature/15m-sweep-phase19
# Execute Phase 19, commit changes
git add .
git commit -m "Phase 19: Full repo & git sweep"

# Create branch for Phase 20 (from Phase 19)
git checkout -b feature/15m-sweep-phase20
# Execute Phase 20, commit changes
git add .
git commit -m "Phase 20: Bloat & over-engineering audit"

# Create branch for Phase 21 (from Phase 20)
git checkout -b feature/15m-sweep-phase21
# Execute Phase 21, commit changes
git add .
git commit -m "Phase 21: External benchmark & gap analysis"
```

### Rollback Phase 1

```bash
git checkout feature/15m-sweep-phase1
git reset --hard HEAD~1  # Revert Phase 1 commit
```

### Rollback Phase 2

```bash
git checkout feature/15m-sweep-phase2
git reset --hard HEAD~1  # Revert Phase 2 commit (back to Phase 1 state)
```

### Rollback Phase 3

```bash
git checkout feature/15m-sweep-phase3
git reset --hard HEAD~1  # Revert Phase 3 commit (back to Phase 2 state)
```

### Rollback Phase 4

```bash
git checkout feature/15m-sweep-phase4
git reset --hard HEAD~1  # Revert Phase 4 commit (back to Phase 3 state)
```

### Rollback Phase 5

```bash
git checkout feature/15m-sweep-phase5
git reset --hard HEAD~1  # Revert Phase 5 commit (back to Phase 4 state)
```

### Rollback Phase 6

```bash
git checkout feature/15m-sweep-phase6
git reset --hard HEAD~1  # Revert Phase 6 commit (back to Phase 5 state)
```

### Rollback Phase 7

```bash
git checkout feature/15m-sweep-phase7
git reset --hard HEAD~1  # Revert Phase 7 commit (back to Phase 6 state)
```

### Rollback Phase 8

```bash
git checkout feature/15m-sweep-phase8
git reset --hard HEAD~1  # Revert Phase 8 commit (back to Phase 7 state)
```

### Rollback Phase 9

```bash
git checkout feature/15m-sweep-phase9
git reset --hard HEAD~1  # Revert Phase 9 commit (back to Phase 8 state)
```

### Rollback Phase 10

```bash
git checkout feature/15m-sweep-phase10
git reset --hard HEAD~1  # Revert Phase 10 commit (back to Phase 9 state)
```

### Rollback Phase 11

```bash
git checkout feature/15m-sweep-phase11
git reset --hard HEAD~1  # Revert Phase 11 commit (back to Phase 10 state)
```

### Rollback Phase 12

```bash
git checkout feature/15m-sweep-phase12
git reset --hard HEAD~1  # Revert Phase 12 commit (back to Phase 11 state)
```

### Rollback Phase 13

```bash
git checkout feature/15m-sweep-phase13
git reset --hard HEAD~1  # Revert Phase 13 commit (back to Phase 12 state)
```

### Rollback Phase 14

```bash
git checkout feature/15m-sweep-phase14
git reset --hard HEAD~1  # Revert Phase 14 commit (back to Phase 13 state)
```

### Rollback Phase 15

```bash
git checkout feature/15m-sweep-phase15
git reset --hard HEAD~1  # Revert Phase 15 commit (back to Phase 14 state)
```

### Rollback Phase 16

```bash
git checkout feature/15m-sweep-phase16
git reset --hard HEAD~1  # Revert Phase 16 commit (back to Phase 15 state)
```

### Rollback Phase 17

```bash
git checkout feature/15m-sweep-phase17
git reset --hard HEAD~1  # Revert Phase 17 commit (back to Phase 16 state)
```

### Rollback Phase 18

```bash
git checkout feature/15m-sweep-phase18
git reset --hard HEAD~1  # Revert Phase 18 commit (back to Phase 17 state)
```

### Rollback Phase 19

```bash
git checkout feature/15m-sweep-phase19
git reset --hard HEAD~1  # Revert Phase 19 commit (back to Phase 18 state)
```

### Rollback Phase 20

```bash
git checkout feature/15m-sweep-phase20
git reset --hard HEAD~1  # Revert Phase 20 commit (back to Phase 19 state)
```

### Rollback Phase 21

```bash
git checkout feature/15m-sweep-phase21
git reset --hard HEAD~1  # Revert Phase 21 commit (back to Phase 20 state)
```

### Full Rollback

```bash
git checkout main  # Return to main branch
git branch -D feature/15m-sweep-phase1
git branch -D feature/15m-sweep-phase2
git branch -D feature/15m-sweep-phase3
git branch -D feature/15m-sweep-phase4
git branch -D feature/15m-sweep-phase5
git branch -D feature/15m-sweep-phase6
git branch -D feature/15m-sweep-phase7
git branch -D feature/15m-sweep-phase8
git branch -D feature/15m-sweep-phase9
git branch -D feature/15m-sweep-phase10
git branch -D feature/15m-sweep-phase11
git branch -D feature/15m-sweep-phase12
git branch -D feature/15m-sweep-phase13
git branch -D feature/15m-sweep-phase14
git branch -D feature/15m-sweep-phase15
git branch -D feature/15m-sweep-phase16
git branch -D feature/15m-sweep-phase17
git branch -D feature/15m-sweep-phase18
git branch -D feature/15m-sweep-phase19
git branch -D feature/15m-sweep-phase20
git branch -D feature/15m-sweep-phase21
```

---

## Success Criteria Checklist

### Backend Sweep
- [ ] All consensus modules deleted
- [ ] All sentiment modules deleted
- [ ] All opinion modules deleted
- [ ] All debate modules deleted
- [ ] merid/loop.py has no consensus integration
- [ ] merid/prediction/agent_grid.py has no sentiment/opinion integration
- [ ] merid/prediction/trading_agent.py has no consensus/sentiment integration
- [ ] No legacy imports in 15m path (grep checks scoped to 15m execution domain)
- [ ] 15m profile independent of consensus/sentiment (profile-level assertion passes)
- [ ] Startup time < 5 seconds
- [ ] Loop tick time < 10 seconds
- [ ] Memory increase < 100MB
- [ ] All critical tests pass
- [ ] Legacy tests removed or updated
- [ ] Loop non-reentrancy test passes
- [ ] Pytest-asyncio tests properly decorated and running

### UI/UX Rewrite
- [ ] Legacy UI components deleted (ConsensusBoard, ConsensusPanel, ConsensusPill, DebateCorrelationPanel)
- [ ] Legacy navigation routes removed (/consensus, /debate, /sentiment, /opinion, /mood)
- [ ] Legacy dashboard cards removed (sentiment meter, mood index, consensus strength, opinion distribution, debate activity, forecast confidence)
- [ ] New dashboard shows execution spine (market health, loop status, order state, fills, risk, spot, connectivity, agent status)
- [ ] Market detail panel shows only execution-relevant fields (ticker, state, bid/ask, mid, spread, spot, expiration, tick size, contract size, last trade time)
- [ ] Copy updated to match live trading workflow (no "swarm consensus", "mood index", "opinion distribution", "debate room", "forecast confidence", "swarm judgment")
- [ ] New 15m screen map defined (/, /markets, /orders, /fills, /risk, /health, /agents)

### Kalshi Parity
- [ ] UI shows only 5 assets (BTC, ETH, SOL, XRP, DOGE)
- [ ] UI uses correct Kalshi tickers (KXBTC15M, KXETH15M, KXSOL15M, KXXRP15M, KXDOGE15M)
- [ ] UI shows only supported actions (buy yes, buy no, cancel order)
- [ ] UI matches Kalshi market state transitions (open → closed → settled)
- [ ] Unsupported UI affordances removed (consensus submission, opinion voting, debate participation, mood adjustment, forecast confidence)
- [ ] Display names match backend market catalog ("BTC 15min", "ETH 15min", etc.)
- [ ] UI driven by backend API (no static mocks or hardcoded tickers)

### UI Test Coverage
- [ ] Legacy UI removal tests pass (consensus, sentiment, opinion, debate, mood components not rendered)
- [ ] No consensus/sentiment regression tests pass (dashboard does not show legacy panels)
- [ ] 15m dashboard snapshot tests pass
- [ ] Navigation route tests pass (new routes work, legacy routes return 404)
- [ ] Kalshi 15m contract mapping tests pass (only 5 assets, correct tickers)

### Documentation
- [ ] Architecture documentation updated (no consensus/sentiment/opinion/debate references)
- [ ] API documentation updated (legacy endpoints deprecated)
- [ ] UI documentation updated (new 15m screen map documented)

### Cross-Cutting Infra and Ops
- [ ] No sentiment/consensus/debate config keys in 15m profiles
- [ ] No logs/metrics for legacy subsystems in the 15m process
- [ ] Deployments for 15m run only the trimmed services
- [ ] Legacy profiles cannot be selected by 15m entrypoints
- [ ] Legacy APIs and roles removed or disabled
- [ ] CI "no legacy concepts in active code" guard passing

### Quality Audit & Consolidation
- [ ] End-to-end 15m path inventory documented (upstream/midstream/downstream)
- [ ] Single canonical asset list and risk envelope
- [ ] Single source for market catalog and state
- [ ] Single risk calculator for sizing/exposure
- [ ] No duplicated ticker/series parsing
- [ ] All loop failures are contained and logged
- [ ] All Kalshi lifecycle states are mapped 1:1 with no gaps
- [ ] All upstream/downstream integration points have timeouts, retries, and safety modes
- [ ] Profiling verifies loop and agent cycles stay within budget
- [ ] Consolidation & flaw checklist created and verified

### Non-Negotiables
- [ ] Asset set for 15m is exactly BTC/ETH/SOL/XRP/DOGE
- [ ] 15m only uses 15m contracts
- [ ] Venue and market state come only from Kalshi
- [ ] Single risk calculator and bankroll source
- [ ] Loop is deterministic, non-reentrant, and consensus-free
- [ ] Fills/settlement lifecycle aligned and idempotent
- [ ] UI and backend present the same 15m execution model
- [ ] Kill-switch conditions are implemented and tested
- [ ] CI guards prevent reintroduction of legacy concepts

### Repo & Git Sweep
- [ ] All legacy/experimental files are removed or moved under `legacy/`/`archive/`
- [ ] Repo entrypoints, docs, and examples point to 15m Kalshi stack as mainline
- [ ] Legacy/pre-sweep state tagged (legacy-pre-15m-sweep)
- [ ] Clean 15m release tag exists (kalshi-15m-v1)
- [ ] No active branch suggests alternate execution architectures
- [ ] CI has dedicated "15m profile" job

### Bloat & Over-Engineering
- [ ] Layer count between agent and Kalshi order ≤ 3
- [ ] No pass-through wrappers in 15m path
- [ ] 15m config keys ≤ 50 (or defined threshold)
- [ ] No future-proofing constructs in 15m path
- [ ] README/docs describe 15m as only mainline
- [ ] Architectural budget script exists and passes
- [ ] Unused abstraction check script exists
- [ ] Simplification review process documented

### External Benchmark & Gap Analysis
- [ ] Market structure doc with public source references
- [ ] Whitepaper skeleton with all required sections
- [ ] Backtest harness structure with engine and reference strategy
- [ ] Gap map table comparing ideal vs current stack
- [ ] Reference implementation package with clean agent stubs

### 15m Operating Constitution
- [ ] Constitution document created with all sections
- [ ] Drift gate check script exists
- [ ] Current architecture doc template exists
- [ ] Concept to owner mapping defined
- [ ] Pre-release checklist defined
- [ ] CI enforcement rules defined

---

## Timeline Estimate

- **Phase 1**: 2 hours (safe deletion)
- **Phase 2**: 4 hours (integration point removal)
- **Phase 3**: 3 hours (test coverage)
- **Phase 4**: 8 hours (UI/UX rewrite - remove legacy components, rewrite dashboard, update market detail, rewrite copy, define screen map)
- **Phase 5**: 4 hours (Kalshi parity and contract mapping)
- **Phase 6**: 6 hours (UI test coverage)
- **Phase 7**: 2 hours (documentation updates)
- **Phase 8**: 2 hours (final verification)
- **Phase 9**: 4 hours (config, profiles, and feature flags)
- **Phase 10**: 8 hours (observability, deployment, and security)
- **Phase 11**: 4 hours (global no-legacy guard and CI)
- **Phase 12**: 2 hours (final cross-cutting acceptance)
- **Phase 13**: 6 hours (end-to-end 15m path inventory)
- **Phase 14**: 8 hours (duplicate detection and consolidation)
- **Phase 15**: 10 hours (robustness gaps - upstream, midstream, downstream)
- **Phase 16**: 6 hours (performance and optimization for 15m)
- **Phase 17**: 4 hours (Kalshi fill-lifecycle alignment)
- **Phase 18**: 2 hours (consolidation & flaw checklist)
- **Phase 19**: 6 hours (full repo & git sweep)
- **Phase 20**: 8 hours (bloat & over-engineering audit)
- **Phase 21**: 6 hours (external benchmark & gap analysis)
- **Total**: 99 hours

---

## Phase 9: Config, Profiles, and Feature Flags

### 9.1 Audit Profiles and YAMLs

**Scope**:
- `config/kalshi_crypto_15m.yaml`
- `config/kalshi_crypto_15m_v2.yaml` (or equivalent sealed profile)
- `config/kalshi_agent_grid.yaml`
- Any `*-15m*.yaml` or `*-crypto*.yaml`
- Env var templates and `.env.example` files

**Command**:
```bash
# Search for legacy knobs
grep -r -n "sentiment\|mood\|consensus\|opinion\|debate" config/ env/ docker/ web/ merid/ | grep -v "#"
```

**Action**:
- For each hit:
  - If the flag solely controls now-deleted logic, **delete** it from config and code
  - If the flag is shared between 15m and a non-15m path, **split it** into profile-specific flags and turn the legacy variant off for 15m

**Verification**:
```bash
# Verify 15m profile files contain no legacy flags
grep -r "sentiment\|mood\|consensus\|opinion\|debate" config/kalshi_crypto_15m*.yaml config/kalshi_agent_grid.yaml
# Should return no results
```

**Expected**: 15m profile files contain **no** sentiment/consensus/debate flags or references

**Rollback**: Git revert if unexpected errors

---

### 9.2 Verify Boot Log Cleanliness

**Command**:
```python
# Boot with 15m profile and check log
import os
os.environ["MERID_PROFILE"] = "kalshi_crypto_15m_v2"
from merid.loop import MeridLoop

# Capture boot log
import logging
import io
log_capture = io.StringIO()
handler = logging.StreamHandler(log_capture)
logging.getLogger().addHandler(handler)

loop = MeridLoop()
# Boot...

log_output = log_capture.getvalue()
assert "sentiment" not in log_output.lower()
assert "consensus" not in log_output.lower()
assert "mood" not in log_output.lower()
assert "debate" not in log_output.lower()
assert "opinion" not in log_output.lower()
assert "taco" not in log_output.lower()
```

**Expected**: Boot log for `kalshi_crypto_15m_v2` shows no mention of sentiment, consensus, mood, debate, opinion, or TaCo modules

**Rollback**: Git revert if boot fails

---

## Phase 10: Observability, Deployment, and Security

### 10.1 Log Surface Sweep

**Files**:
- `merid/logging*.py` or logging config modules
- Any `*_metrics.py` and `*_monitor.py` files
- Web logs and startup traces

**Command**:
```bash
# Search for obsolete log messages
grep -r -n "consensus\|sentiment\|mood\|debate\|opinion" merid/ web/ | grep -v "#"
```

**Action**:
- For each match:
  - If it logs a removed component, delete or rewrite
  - If it logs a still-existing component but with obsolete semantics (e.g., "consensus boost"), rewrite to risk/execution language
- Normalize stage names to match current loop phases (e.g., `MARKET_DATA`, `RISK`, `ORDER_EXECUTION`, `SETTLEMENT`) instead of `CONSENSUS`

**Verification**:
```bash
# Verify no obsolete log messages
grep -r "consensus\|sentiment\|mood\|debate\|opinion" merid/ web/ | grep -v "#" | grep -v "legacy" | grep -v "archive"
# Should return no results
```

**Rollback**: Git revert if unexpected errors

---

### 10.2 Metrics and Dashboards

**Scope**:
- Prometheus/Grafana (or equivalent) dashboards
- Custom metrics emitters

**Legacy Metrics to Remove**:
- `consensus_cycles_run`
- `sentiment_score`
- `debate_rounds`
- `opinion_volume`

**New Metrics to Add**:
- Loop tick latency and health
- Bankroll freshness and risk utilization
- WS bridge health and market state age
- Order submission / fill latency

**Command**:
```bash
# Search for legacy metric references
grep -r "consensus_cycles_run\|sentiment_score\|debate_rounds\|opinion_volume" merid/ monitoring/
```

**Action**: Remove or replace legacy metrics with execution-centric metrics

**Verification**:
```bash
# Verify no legacy metrics in code
grep -r "consensus_cycles_run\|sentiment_score\|debate_rounds\|opinion_volume" merid/ monitoring/ grafana/
# Should return no results
```

**Expected**: No Grafana panel or alert uses a metric name with sentiment/consensus/debate/opinion/mood

**Rollback**: Git revert if unexpected errors

---

### 10.3 Deployment Scripts and Containers

**Scope**:
- Dockerfiles for 15m
- `docker-compose` / Helm / K8s manifests
- Any `deploy_*.sh` scripts

**Actions**:
- Remove:
  - Sidecars or containers that run sentiment/consensus services
  - Env vars wiring those services into the pod
  - Cron jobs that call legacy sentiment/consensus backfills

- Ensure the only long-running components in the 15m deployment are:
  - 15m web app / API
  - Kalshi venue clients (REST + WS)
  - 15m loop / workers
  - Spot service
  - DB/cache (Redis, SQLite/Postgres, etc.) used by the trimmed stack

**Command**:
```bash
# Search for legacy service references in deployment
grep -r "sentiment\|consensus\|debate\|opinion" docker/ deploy/ k8s/
```

**Verification**:
```bash
# Verify no legacy services in deployment
grep -r "sentiment\|consensus\|debate\|opinion" docker/ deploy/ k8s/ | grep -v "#"
# Should return no results
```

**Rollback**: Git revert if unexpected errors

---

### 10.4 Promotion Workflows

**Scope**:
- CI/CD pipelines
- Promotion scripts or tools for profile rollouts

**Actions**:
- Check that no promotion job still runs tests or validations for the removed features (consensus, sentiment, debate)
- Ensure the promotion checklist references the new success criteria (15m path only, no legacy imports, UI parity, etc.), not the old swarm stack

**Verification**:
```bash
# Search for legacy feature references in CI/CD
grep -r "consensus\|sentiment\|debate\|opinion" .github/workflows/ .gitlab-ci.yml jenkins/
```

**Expected**: A new promotion pipeline for "15m profile" that runs:
- Code tests (backend + UI)
- No-legacy-import greps
- Startup and loop timing tests
- UI smoke tests

**Rollback**: Git revert if unexpected errors

---

### 10.5 Auth / API Surface Sweep

**Scope**:
- API router modules
- Any `*consensus*_api.py`, `*sentiment*_api.py`, `*debate*_api.py` endpoints

**Actions**:
- Remove or return 410/404:
  - `/api/consensus/...`
  - `/api/sentiment/...`
  - `/api/debate/...`
  - `/api/opinion/...`

- Validate that front-end no longer calls those endpoints (enforced by Phase 4/5/6)

**Command**:
```bash
# Search for legacy API endpoints
grep -r "consensus\|sentiment\|debate\|opinion" web/api/ merid/web/api/
```

**Verification**:
```bash
# Verify no legacy API endpoints
grep -r "consensus\|sentiment\|debate\|opinion" web/api/ merid/web/api/ | grep -v "#"
# Should return no results
```

**Rollback**: Git revert if unexpected errors

---

### 10.6 Permission Models

**Scope**:
- Role definitions, scopes, tokens

**Actions**:
- Remove roles like:
  - `sentiment_admin`
  - `consensus_operator`
  - `debate_moderator`
  - Any scope flags referencing these concepts

**Command**:
```bash
# Search for legacy roles and scopes
grep -r "sentiment_admin\|consensus_operator\|debate_moderator" auth/ security/
```

**Verification**:
```bash
# Verify no legacy roles
grep -r "sentiment_admin\|consensus_operator\|debate_moderator" auth/ security/
# Should return no results
```

**Expected**: Permission model only includes what the new 15m + venue + risk + basic product needs

**Rollback**: Git revert if unexpected errors

---

## Phase 11: Global "No Legacy" Guard and CI

### 11.1 Profile Registration Sweep

**Scope**:
- Profile registry / profile factory used at startup
- Any menu or CLI that selects profiles

**Action**:
- For each profile:
  - Classify as:
    - ACTIVE_15M
    - ACTIVE_NON_15M
    - LEGACY/ARCHIVE

- For LEGACY/ARCHIVE:
  - Move them into an `archive/` or `legacy/` namespace
  - Add a guard so they **cannot** be selected by default or via 15m endpoints

- Ensure that 15m entrypoints **only** allow `kalshi_crypto_15m` / `kalshi_crypto_15m_v2` or similarly named sealed profiles

**Command**:
```bash
# Search for all profile references
grep -r "profile" config/ merid/ | grep -v "#"
```

**Verification**:
```bash
# Verify legacy profiles are in archive namespace
ls config/profiles/archive/
# Verify 15m entrypoint only allows 15m profiles
grep "profile" merid/startup_validations.py
```

**Rollback**: Git revert if unexpected errors

---

### 11.2 Entrypoint Isolation

**Scope**:
- `web.main15m` app and any other ASGI/WSGI entrypoints

**Action**:
- Confirm the 15m entrypoint:
  - Does not import generic "all profiles" registries that might drag legacy behavior into the process
  - Only imports the minimal set of modules:
    - 15m profile config
    - venue services
    - risk
    - loop
    - agent grid
    - spot
    - health

**Command**:
```bash
# Check 15m entrypoint imports
grep -n "import" web/main15m.py
# Should only show minimal module imports
```

**Verification**:
```python
# Test 15m app in isolation
import subprocess
result = subprocess.run(
    ["uvicorn", "web.main15m:app", "--host", "127.0.0.1", "--port", "8001"],
    capture_output=True,
    text=True,
    timeout=10
)
assert "sentiment" not in result.stderr.lower()
assert "consensus" not in result.stderr.lower()
assert "legacy" not in result.stderr.lower()
```

**Expected**: Running the 15m app in isolation never loads legacy profile modules or services (confirmed via logs and import tracing)

**Rollback**: Git revert if unexpected errors

---

### 11.3 Repository-Wide "Legacy Concept" CI Guard

**File**: `.github/workflows/no-legacy-concepts.yml` (new)

**Content**:
```yaml
name: No Legacy Concepts Check

on:
  pull_request:
    branches: [ main, develop ]

jobs:
  check-legacy-concepts:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Block legacy concepts in active code
        run: |
          # Block any reintroduction of legacy concepts in 15m-related code
          grep -r -n "sentiment\|mood\|consensus\|opinion\|debate" \
              merid/ web/ config/ ui/ \
            | grep -v "legacy" \
            | grep -v "archive" \
            && { echo "ERROR: Legacy concepts found in active code"; exit 1; } \
            || echo "OK: No legacy concepts in active paths"
```

**Action**: Add CI job that blocks reintroduction of legacy concepts

**Verification**:
```bash
# Test the guard locally
grep -r -n "sentiment\|mood\|consensus\|opinion\|debate" \
    merid/ web/ config/ ui/ \
  | grep -v "legacy" \
  | grep -v "archive" \
  && { echo "ERROR: Legacy concepts found in active code"; exit 1; } \
  || echo "OK: No legacy concepts in active paths"
```

**Expected**: CI fails if any PR reintroduces those concepts into active code paths

**Rollback**: Git revert if unexpected errors

---

## Phase 12: Final Cross-Cutting Acceptance

**Goal**: Verify all cross-cutting infra and ops are clean of legacy concepts.

### 12.1 Config and Profile Acceptance

**Verification**:
```bash
# Verify no legacy config keys in 15m profiles
grep -r "sentiment\|mood\|consensus\|opinion\|debate" config/kalshi_crypto_15m*.yaml config/kalshi_agent_grid.yaml
# Should return no results
```

**Expected**: No sentiment/consensus/debate config keys in 15m profiles

---

### 12.2 Observability Acceptance

**Verification**:
```bash
# Verify no legacy logs/metrics in 15m process
grep -r "consensus_cycles_run\|sentiment_score\|debate_rounds\|opinion_volume" merid/ monitoring/ grafana/
# Should return no results
```

**Expected**: No logs/metrics for legacy subsystems in the 15m process

---

### 12.3 Deployment Acceptance

**Verification**:
```bash
# Verify deployment runs only trimmed services
grep -r "sentiment\|consensus\|debate\|opinion" docker/ deploy/ k8s/ | grep -v "#"
# Should return no results
```

**Expected**: Deployments for 15m run only the trimmed services

---

### 12.4 Profile Isolation Acceptance

**Verification**:
```bash
# Verify legacy profiles are archived
ls config/profiles/archive/
# Verify 15m entrypoint only allows 15m profiles
grep "profile" merid/startup_validations.py | grep "15m"
```

**Expected**: Legacy profiles cannot be selected by 15m entrypoints

---

### 12.5 Security Acceptance

**Verification**:
```bash
# Verify no legacy APIs or roles
grep -r "consensus\|sentiment\|debate\|opinion" web/api/ merid/web/api/ auth/ security/ | grep -v "#"
# Should return no results
```

**Expected**: Legacy APIs and roles removed or disabled

---

### 12.6 CI Guard Acceptance

**Verification**:
```bash
# Test the CI guard locally
grep -r -n "sentiment\|mood\|consensus\|opinion\|debate" \
    merid/ web/ config/ ui/ \
  | grep -v "legacy" \
  | grep -v "archive" \
  && { echo "ERROR: Legacy concepts found in active code"; exit 1; } \
  || echo "OK: No legacy concepts in active paths"
```

**Expected**: CI "no legacy concepts in active code" guard passing

---

## Phase 13: End-to-End 15m Path Inventory

### 13.1 Build an End-to-End Call Graph (15m Only)

**Scope**: Starting from 15m entrypoint (`web.main15m`, `MeridLoop`, agent grid, venue clients)

**Command**:
```bash
# Start from the 15m entrypoints
rg "kalshicrypto15m" -n web/ merid/ config/
rg "kalshicrypto15mv2" -n web/ merid/ config/

# Quick list of imported modules from 15m entrypoints
python - << 'PY'
import inspect, importlib
import web.main15m as m

# Dump source for quick manual follow-up
print(inspect.getsource(m))
PY
```

**Action**:
- Generate a list of all 15m-reachable modules
- Manually label each module/function as:
  - Upstream (inputs): configs, env, spot, Kalshi REST/WS
  - Midstream (logic): loop, risk, agent grid, decision logic
  - Downstream (outputs): order router, fills ledger, settlement, UI adapters

**Deliverable**: A simple markdown table in `15M_ARCHITECTURE_SWEEP_REPORT.md` listing:
- Module
- Layer (upstream/midstream/downstream)
- 15m role
- Keep/Delete/Rewrite/Consolidate

**Expected**: Canonical map of the 15m path for all dedup/optimization decisions

**Rollback**: Git revert if unexpected errors

---

## Phase 14: Duplicate Detection and Consolidation

### 14.1 Config & Profile Duplicates

**Command**:
```bash
# Search for multiple definitions of the same asset list and envelopes
rg "BTC15M" config/ merid/ -n
rg "KXBTC15M" config/ merid/ -n
rg "BTC, ETH, SOL, XRP, DOGE" config/ merid/ -n
```

**Action**:
- For each duplicated config:
  - Pick **one** canonical location (e.g., `config/kalshi_crypto_15m.yaml`)
  - Replace other occurrences with imports / references to that source

**Verification**:
```bash
# Verify single canonical asset list
grep -r "BTC, ETH, SOL, XRP, DOGE" config/ merid/ | wc -l
# Should return 1 (single source of truth)
```

**Expected**: Exactly one 15m crypto asset whitelist and one set of canonical risk envelope values

**Rollback**: Git revert if unexpected errors

---

### 14.2 Risk & Notional Calculations

**Command**:
```bash
# Search for multiple functions computing max size, notional, or exposure
rg "max_position" merid/ -n
rg "max_notional" merid/ -n
rg "max exposure" merid/ -n
```

**Action**: Consolidate into a single `RiskCalculator` / risk service used by both agent and venue layers

**Verification**:
```bash
# Verify single risk calculator
grep -r "class RiskCalculator" merid/ | wc -l
# Should return 1 (single implementation)
```

**Expected**: Order sizing code paths (agent -> router) all go through one risk calculator

**Rollback**: Git revert if unexpected errors

---

### 14.3 Market State & Catalog Usage

**Command**:
```bash
# Search for multiple code paths that fetch or interpret Kalshi markets
rg "KalshiMarketCatalog" merid/ -n
rg "MarketStateStore" merid/ -n
rg "series_ticker" merid/ -n
```

**Action**: Force all 15m components to use `KalshiMarketCatalog` + `MarketStateStore` as single sources of truth for:
- Market discovery
- Status open/closed
- Timeframe classification

**Verification**:
```bash
# Verify no custom ticker parsing in 15m path
grep -r "parse.*ticker\|extract.*ticker" merid/prediction/ merid/loop.py | grep -v "legacy" | grep -v "archive"
# Should return no results
```

**Expected**: No custom ticker parsing or ad-hoc series filtering in agents/loop

**Rollback**: Git revert if unexpected errors

---

## Phase 15: Robustness Gaps (Upstream & Downstream)

### 15.1 Upstream Robustness (Kalshi Venue, WS, REST)

**Scope**: Kalshi REST for market catalog and balance, Kalshi WS for orderbook, trades, ticker, fills

**Actions**:
- Ensure REST calls have timeouts and retry/backoff with **circuit breaker** semantics
- Ensure WS bridge has:
  - Reconnect with max backoff
  - Health logs and metrics
  - "Shed" mechanism for catastrophic failure (disable trading, keep process alive but safe)

**Verification**:
```bash
# Verify timeout configuration
grep -r "timeout" merid/event_venues/kalshi/ | grep -v "legacy"
# Verify circuit breaker
grep -r "circuit.*breaker\|CircuitBreaker" merid/event_venues/kalshi/
```

**Add Tests**:
```python
# Test file: tests/test_kalshi_venue_robustness.py

async def test_catalog_zero_markets():
    """Catalog returns 0 markets should degrade gracefully"""
    # Mock catalog to return empty list
    # Verify 15m does not crash
    pass

async def test_ws_disconnect_mid_session():
    """WS disconnects mid-session should disable trading but keep state coherent"""
    # Simulate WS disconnect
    # Verify trading disabled, state preserved
    pass
```

**Expected**: Under failure conditions, 15m degrades gracefully without crashing

**Rollback**: Git revert if unexpected errors

---

### 15.2 Midstream Robustness (Loop & Agent Grid)

**Actions**:
- Add tests for:
  - Partial failure: one agent throws, loop continues and logs
  - Slow agent: per-cycle time budget and logging when exceeded

- Code review:
  - Ensure all `asyncio.gather()` in the loop uses `return_exceptions=True` with centralized handling

**Verification**:
```bash
# Verify return_exceptions=True in loop
grep -r "asyncio.gather" merid/loop.py | grep "return_exceptions"
# Should show return_exceptions=True
```

**Add Tests**:
```python
# Test file: tests/test_loop_robustness.py

async def test_agent_partial_failure():
    """One agent throws should not halt loop"""
    # Mock one agent to raise exception
    # Verify loop continues, logs error
    pass

async def test_slow_agent_timeout():
    """Slow agent should log warning but not block loop"""
    # Mock one agent to exceed time budget
    # Verify warning logged, loop continues
    pass
```

**Expected**: All loop failures are contained and logged

**Rollback**: Git revert if unexpected errors

---

### 15.3 Downstream Robustness (Order Routing, Fills)

**Scope**: `KalshiFillsLedger` + fills poller + settlement poller, with DB and WAL mode

**Actions**:
- Verify:
  - Fills ledger writes are idempotent (replay from Kalshi does not double-count)
  - Fills poller does not block on a single bad fill
  - Settlement poller correctly transitions positions and PnL

**Add Tests**:
```python
# Test file: tests/test_fills_ledger_robustness.py

async def test_duplicate_fill_ids():
    """Duplicate fill ids should not double-count"""
    # Submit same fill twice
    # Verify ledger idempotent
    pass

async def test_out_of_order_fills():
    """Out-of-order fills should be handled correctly"""
    # Submit fills in wrong order
    # Verify ledger corrects order
    pass

async def test_settlement_after_reconnect():
    """Settlement arriving after WS reconnect should be handled"""
    # Simulate reconnect + late settlement
    # Verify PnL and positions correct
    pass
```

**Expected**: Under all edge cases, 15m PnL and positions remain correct

**Rollback**: Git revert if unexpected errors

---

## Phase 16: Performance and Optimization for 15m

### 16.1 Loop Performance Budget

**Scope**: AgentGrid startup < 5s, Loop tick < 10s

**Actions**:
- Profile a full cycle:
  - Breakdown of cycle time by stage: catalog refresh, market state, risk, agents, routing, persistence
  - Identify hotspots and:
    - Cache repeated computations (e.g., per-asset constants)
    - Batch network calls

- Add metrics:
  - `loop_tick_duration_ms`
  - `agent_cycle_duration_ms` per agent

**Command**:
```python
# Profiling script
import cProfile
import pstats
from merid.loop import MeridLoop

loop = MeridLoop()
profiler = cProfile.Profile()
profiler.enable()
await loop.tick()
profiler.disable()

stats = pstats.Stats(profiler)
stats.sort_stats('cumulative')
stats.print_stats(20)  # Top 20 hotspots
```

**Verification**:
```bash
# Verify metrics added
grep -r "loop_tick_duration_ms\|agent_cycle_duration_ms" merid/ monitoring/
```

**Expected**: Loop and agent cycles stay within budget with WARN/ERROR logging above thresholds

**Rollback**: Git revert if unexpected errors

---

### 16.2 Spot Service Optimization

**Actions**:
- Ensure spot service uses:
  - Efficient caching with TTL aligned to 15m needs
  - Incremental updates, not full fetch every cycle

**Verification**:
```bash
# Verify caching configuration
grep -r "cache\|TTL\|ttl" merid/services/spot/ | grep -v "legacy"
```

**Add Tests**:
```python
# Test file: tests/test_spot_service_optimization.py

async def test_spot_cache_hit_rate():
    """Spot service should cache efficiently under load"""
    # Repeated queries should hit cache
    pass

async def test_spot_incremental_updates():
    """Spot service should use incremental updates"""
    # Verify not full fetch every cycle
    pass
```

**Expected**: Under heavy load, spot queries don't explode external API calls

**Rollback**: Git revert if unexpected errors

---

## Phase 17: Kalshi Fill-Lifecycle Alignment

### 17.1 State Machine Comparison

**Kalshi States** (simplified):
- `NEW` → `OPEN` → `PARTIALLY_FILLED` → `FILLED` → `CANCELLED/EXPIRED` → `SETTLED`

**Actions**:
- Document internal state machine for each order from submission to settlement
- Ensure internal enums/state machine match Kalshi transitions
- Remove any intermediate "consensus" or "opinion" states

**Verification**:
```bash
# Verify no legacy states
grep -r "CONSENSUS\|OPINION\|SENTIMENT" merid/event_venues/kalshi/ | grep -i "state\|status"
# Should return no results
```

**Add Tests**:
```python
# Test file: tests/test_kalshi_lifecycle_alignment.py

async def test_lifecycle_state_transitions():
    """Synthetic Kalshi events should drive internal states correctly"""
    # Feed synthetic fills, cancels, settlements
    # Verify internal ledger, PnL, UI all move through same states
    pass
```

**Expected**: All Kalshi lifecycle states are mapped 1:1 with no gaps

**Rollback**: Git revert if unexpected errors

---

## Phase 18: Consolidation & Flaw Checklist

### 18.1 Consolidation & Flaw Verification

**Deliverable**: Add dedicated "Consolidation & Flaws" checklist to `15M_ARCHITECTURE_SWEEP_REPORT.md`:

```markdown
## Consolidation & Flaw Checklist

- [ ] Single canonical asset list and risk envelope
- [ ] Single source for market catalog and state
- [ ] Single risk calculator for sizing/exposure
- [ ] No duplicated ticker/series parsing
- [ ] All loop failures are contained and logged
- [ ] All Kalshi lifecycle states are mapped 1:1 with no gaps
- [ ] All upstream/downstream integration points have timeouts, retries, and safety modes
- [ ] Profiling verifies loop and agent cycles stay within budget
```

**Verification**:
```bash
# Verify checklist created
cat docs/15M_ARCHITECTURE_SWEEP_REPORT.md | grep -A 10 "Consolidation & Flaw Checklist"
```

**Expected**: All consolidation and flaw items verified and documented

**Rollback**: Git revert if unexpected errors

---

## Phase 19: Full Repo & Git Sweep

### 19.1 Live Tree Cleanup (Working Copy)

**Goal**: Remove useless files, dead directories, and ambiguous artifacts that don't belong in the 15m-centric future.

**Action 1: Classify directories**

Mark each directory as one of:
- `ACTIVE_15M_CORE` (must stay, kept clean)
- `ACTIVE_NON_15M` (clearly labeled, not loaded in 15m)
- `LEGACY/ARCHIVE` (kept only for reference)
- `DELETE`

**Typical candidates**:
- `research/`, `experiments/`, `notebooks/`
- `legacy/`, `old/`, `tmp/`, `sandbox/`
- Old entrypoints under `web/` that no longer fit non-negotiables

**Command**:
```bash
# List all directories
find . -type d -maxdepth 2 | grep -v ".git" | sort
```

**Action 2: Move and delete**

For code to keep as reference but never load:
```bash
mkdir -p legacy
git mv path/to/old_module.py legacy/old_module.py
```

For truly useless files:
```bash
git rm path/to/useless_file.py
git rm -r path/to/useless_dir/
```

**Action 3: Enforce "no legacy in active paths" rule**

Keep the CI grep defined in Phase 11, treating `legacy/` and `archive/` as the only safe homes for old patterns.

**Verification**:
```bash
# Verify no legacy concepts in active paths
grep -r -n "sentiment\|mood\|consensus\|opinion\|debate" \
    merid/ web/ config/ ui/ \
  | grep -v "legacy" \
  | grep -v "archive" \
  && { echo "ERROR: Legacy concepts found in active code"; exit 1; } \
  || echo "OK: No legacy concepts in active paths"
```

**Expected**: All legacy/experimental files are either removed or moved under `legacy/`/`archive/` and excluded from 15m runtime

**Rollback**: Git revert if unexpected errors

---

### 19.2 Git History: Tags, Branches, and Documentation

**Goal**: Make the repo's history reflect that 15m is now the primary direction, and legacy stacks are clearly labeled.

**Action 1: Tag key points**

Tag the last commit before this massive sweep:
```bash
git tag -a legacy-pre-15m-sweep -m "Last commit before 15m Kalshi stack refactor"
```

Tag the commit where the full 15m remediation plan is implemented and passing:
```bash
git tag -a kalshi-15m-v1 -m "Kalshi 15m stack v1 (BTC/ETH/SOL/XRP/DOGE)"
```

**Action 2: Clean up old branches**

List branches:
```bash
git branch -a
```

For pre-refactor experiments that are no longer relevant:
- Delete (if merged):
  ```bash
  git branch -d old/feature-consensus-swarm
  ```
- Or rename to clearly mark as legacy:
  ```bash
  git branch -m feature/swarm-research legacy/swarm-research
  ```

**Action 3: Update top-level docs**

Update `README.md` and any root-level docs to:
- Make the 15m Kalshi stack the clearly documented mainline
- Move previous architecture descriptions into `docs/legacy/` or mark as historical

**Verification**:
```bash
# Verify tags created
git tag -l | grep -E "legacy-pre-15m-sweep|kalshi-15m-v1"

# Verify no confusing branch names
git branch -a | grep -E "swarm|consensus|debate|sentiment" | grep -v "legacy"
# Should return no results (or only legacy/ prefixed)
```

**Expected**: Legacy/pre-sweep state tagged, clean 15m release tag exists, no active branch suggests alternate execution architectures

**Rollback**: Git revert if unexpected errors

---

### 19.3 Repository Search for Confusion Points

**Goal**: Find anything that contradicts the new direction or can mislead future work.

**Action 1: Search for stale concepts and adjectives**

```bash
rg "swarm" .
rg "debate" .
rg "oracle" .
rg "AI trader" .
rg "experimental" docs/ merid/ web/ ui/
```

For each occurrence in active code/docs:
- Delete, or
- Move to `legacy/` docs, or
- Rewrite to reflect the new deterministic 15m stack

**Action 2: Kill unused tests and fixtures**

```bash
# Collect all tests
pytest tests/ --collect-only -q > /tmp/test_list.txt

# Manually skim for test names referencing legacy concepts
grep -i "sentiment\|mood\|consensus\|debate\|opinion\|swarm\|oracle" /tmp/test_list.txt
```

For each test:
- Delete, or
- Move to `tests/legacy/` where excluded from default CI

**Verification**:
```bash
# Verify no stale concepts in active code/docs
rg "swarm|debate|oracle|AI trader|experimental" docs/ merid/ web/ ui/ | grep -v "legacy" | grep -v "archive"
# Should return no results

# Verify no legacy tests in active test suite
pytest tests/ --collect-only -q | grep -i "sentiment\|mood\|consensus\|debate\|opinion\|swarm\|oracle"
# Should return no results
```

**Expected**: No stale concepts in active code/docs, no legacy tests in active test suite

**Rollback**: Git revert if unexpected errors

---

### 19.4 Final CI Profile for "15m-Only" Reality

**Goal**: Make CI the arbiter of the new direction.

**Action 1: Define a 15m CI job**

Add a job in CI pipeline that runs:
```bash
# 1. Lint & type checks (optional but recommended)
# flake8 .
# mypy merid/ web/ ...

# 2. 15m test suite
pytest tests/ -v --tb=short

# 3. No legacy concepts in active code
./scripts/check_no_legacy.sh
```

Make this required for merging into `main`.

**Action 2: Optional "legacy" CI profile**

If keeping `legacy/` code:
- Exclude from default CI, or
- Have a separate, non-blocking job for legacy tests

**Verification**:
```bash
# Verify CI job exists
cat .github/workflows/15m-ci.yml | grep -A 20 "15m-profile"

# Verify check_no_legacy.sh exists
cat scripts/check_no_legacy.sh
```

**Expected**: CI has a dedicated "15m profile" job that must pass before merge

**Rollback**: Git revert if unexpected errors

---

### 19.5 Success Criteria for Repo & Git Sweep

**Verification**:
```bash
# Verify all success criteria
# 1. Legacy files moved or removed
ls legacy/ archive/ 2>/dev/null || echo "No legacy/archive dirs"

# 2. Tags created
git tag -l | grep -E "legacy-pre-15m-sweep|kalshi-15m-v1"

# 3. No confusing branches
git branch -a | grep -E "swarm|consensus|debate|sentiment" | grep -v "legacy"

# 4. CI job exists
cat .github/workflows/15m-ci.yml | grep "15m-profile"
```

**Expected**:
- All legacy/experimental files are removed or moved under `legacy/`/`archive/`
- Repo entrypoints, docs, and examples point to 15m Kalshi stack as mainline
- Legacy/pre-sweep state tagged
- Clean 15m release tag exists
- No active branch suggests alternate execution architectures
- CI has dedicated "15m profile" job

**Rollback**: Git revert if unexpected errors

---

## Phase 20: Bloat & Over-Engineering Audit

### 20.1 Identify Bloat Patterns in 15m Core

**Scope**: 15m execution path (entrypoints, Kalshi venue, loop, agent grid, risk, spot, UI)

**Patterns to identify**:
- Layer explosion (multiple wrappers/adapters with pass-through)
- Indirection without payoff (strategy managers, abstract base classes with single implementation)
- Config sprawl (too many flags/knobs for same behavior)
- Duplicated concepts (multiple representations of market, trade/fill, PnL, risk envelope)

**Command**:
```bash
# Search for thin wrapper patterns (classes that only forward calls)
rg "class.*Adapter" merid/ web/ -n
rg "class.*Manager" merid/ web/ -n
rg "class.*Wrapper" merid/ web/ -n

# Search for abstract base classes
rg "ABC\|abstract" merid/ web/ -n | grep "class"

# Search for config key sprawl
rg "max_" config/ -n
rg "enable_" config/ -n
rg "use_" config/ -n
```

**Action**:
- From Phase 13 inventory, mark modules/functions as:
  - `ESSENTIAL`
  - `THIN WRAPPER (candidate for deletion)`
  - `DUPLICATE CONCEPT (needs consolidation)`
- For each `THIN WRAPPER` that only forwards calls or adds trivial logging:
  - Inline it (move logic up/down one layer), or
  - Delete and adapt call sites

**Verification**:
```bash
# Verify no thin wrappers remain
rg "class.*Adapter.*:" merid/ web/ | grep -v "legacy" | grep -v "archive"
# Should return minimal results (only essential adapters)

# Verify no manager classes that just forward
rg "def.*\(self.*\):.*return.*\." merid/ -A 2 | grep -B 2 "class.*Manager"
# Should return minimal results
```

**Deliverable**: Add "Bloat findings" subsection to `15M_ARCHITECTURE_SWEEP_REPORT.md` listing specific modules/functions removed or merged

**Expected**: Layer count reduced, no pass-through wrappers, config keys consolidated

**Rollback**: Git revert if unexpected errors

---

### 20.2 Strip "Future-Proofing" Hurting 15m

**Rule**: 15m stack should be excellent at one thing, not "ready for everything"

**Actions**:
- Delete or isolate:
  - Hooks for other venues never used in 15m
  - Multi-timeframe logic inside 15m path (keep in non-15m profiles if needed)
  - "Strategy registries" designed for dozens of strategies but only wrap small fixed 15m agents
  - Generalized "prediction framework" abstractions between agent and order router with no real value

**Command**:
```bash
# Search for venue hooks
rg "venue.*hook\|VenueHook" merid/ -n
rg "multi.*venue\|MultiVenue" merid/ -n

# Search for multi-timeframe logic in 15m path
rg "timeframe.*=.*\|timeframe.*in" merid/loop.py merid/prediction/ -n | grep -v "15m"

# Search for strategy registries
rg "StrategyRegistry\|strategy.*registry\|registry.*strategy" merid/ -n

# Search for prediction framework abstractions
rg "PredictionFramework\|prediction.*framework\|framework.*prediction" merid/ -n
```

**Action**:
- For each construct that exists "only" for future support and complicates 15m path:
  - Move to `legacy/` or
  - Delete

**Verification**:
```bash
# Verify no venue hooks in 15m path
rg "venue.*hook\|VenueHook" merid/loop.py merid/prediction/ merid/event_venues/kalshi/ | grep -v "legacy"

# Verify no multi-timeframe logic in 15m loop
rg "timeframe" merid/loop.py | grep -v "15m" | grep -v "legacy"

# Verify no strategy registries in 15m path
rg "StrategyRegistry" merid/prediction/ merid/loop.py | grep -v "legacy"
```

**Expected**: No future-proofing constructs in 15m path, only essential 15m logic

**Rollback**: Git revert if unexpected errors

---

### 20.3 Delete Old Memories/Docs Contradicting 15m Stack

**Action 1: Docs & md sweep**

```bash
# Search for legacy concepts in docs
rg "consensus|sentiment|debate|swarm|oracle|AI trader|mood" docs/ . -g'*.md'
```

For each hit:
- If describes behavior that no longer exists: **delete the md file**
- If mixes old and new:
  - Move to `docs/legacy/` and label "Historical (pre-15m refactor)", or
  - Rewrite to match new non-negotiables

**Action 2: README & top-level docs**

Update root `README.md` and any `.github/README`:
- Describe 15m Kalshi BTC/ETH/SOL/XRP/DOGE stack as the **only** mainline
- Remove mentions of:
  - multi-venue prediction platform
  - swarm/consensus trading
  - sentiment-driven behavior

If preserving history, link to `docs/legacy/architecture_pre_15m.md` instead of mixed narratives

**Action 3: GitHub repo description & topics**

Update GitHub "Description" and tags to reflect:
- "Kalshi 15m crypto execution stack (BTC/ETH/SOL/XRP/DOGE)"

Remove buzzwords that no longer apply (swarm, sentiment, debate, etc.)

**Verification**:
```bash
# Verify no legacy concepts in active docs
rg "consensus|sentiment|debate|swarm|oracle|AI trader|mood" docs/ -g'*.md' | grep -v "legacy" | grep -v "archive"

# Verify README reflects 15m mainline
cat README.md | grep -i "15m\|kalshi.*crypto\|BTC.*ETH.*SOL.*XRP.*DOGE"
# Should return results

# Verify no legacy buzzwords
cat README.md | grep -i "swarm\|consensus\|sentiment\|debate" | grep -v "historical" | grep -v "legacy"
# Should return no results
```

**Expected**: New engineer reading README/docs gets exact same mental model as enforced in code

**Rollback**: Git revert if unexpected errors

---

### 20.4 Architectural Guardrails (Prevention Rules)

#### A. "15m RFC" for Structural Changes

Require short markdown RFC in `docs/rfcs/` for:
- Adding new layer (service, adapter, manager) in 15m path
- Changing risk model
- Changing asset universe or timeframe assumptions
- New cross-cutting abstraction touching loop/agents/venue

RFC must answer:
- How does this support 15m non-negotiables?
- Can this be done by extending existing module instead of adding new one?
- Is it 15m-only or general? If general, how do we keep 15m minimal?

**Enforcement**: Require RFC link in PR descriptions

---

#### B. Architectural "Budget" for Layers and Configs

Set explicit caps:
- **Layers between agent decision and Kalshi order**: at most 3 (e.g., `Agent` → `OrderRouter` → `KalshiClient`)
- **Configs for 15m**: all in one or two YAMLs, no more than N tunable parameters per asset/timeframe (e.g., 10)

**Enforcement script**:
```bash
# scripts/check_architectural_budget.sh
#!/bin/bash

# Count 15m config keys
CONFIG_KEYS=$(rg -o "[a-z_]+:" config/kalshi_crypto_15m.yaml | wc -l)
if [ $CONFIG_KEYS -gt 50 ]; then
  echo "ERROR: Too many 15m config keys ($CONFIG_KEYS, max 50)"
  exit 1
fi

echo "OK: 15m config keys within budget ($CONFIG_KEYS)"
```

**Verification**:
```bash
./scripts/check_architectural_budget.sh
```

---

#### C. "No Unused Abstraction" CI Check

Add CI script looking for "dead" interfaces:
- Interfaces/abstract base classes with only one implementation
- Adapters used in only one place with no non-trivial behavior

```bash
# scripts/check_unused_abstractions.sh
#!/bin/bash

# Find abstract base classes
ABSTRACT_CLASSES=$(rg "ABC\|@abstractmethod" merid/ -l | grep -v legacy)

for file in $ABSTRACT_CLASSES; do
  # Count implementations (heuristic: classes inheriting from this)
  IMPLEMENTATIONS=$(rg "class.*\(.*$(basename $file .py)\)" merid/ -l | wc -l)
  if [ $IMPLEMENTATIONS -le 1 ]; then
    echo "WARNING: Abstract base class with single implementation: $file"
  fi
done
```

---

#### D. Regular 15m "Simplification Review"

Once per release or per month, review focusing on:
- Has any new layer been added in 15m path?
- Have any new config flags appeared?
- Are there any new UI panels or routes?

For anything new, ask:
- Is it essential?
- Could this be done with less code?
- Does it conflict with or weaken any non-negotiable?

Log answers in `15M_ARCHITECTURE_SWEEP_REPORT.md` under "Simplification Reviews" section

---

### 20.5 Success Criteria for Bloat Audit

**Verification**:
```bash
# Verify all success criteria
# 1. Layer count reduced
# 2. No thin wrappers
# 3. Config keys consolidated
# 4. No future-proofing in 15m path
# 5. Docs reflect 15m mainline
# 6. Architectural budget script exists
# 7. Unused abstraction check script exists
```

**Expected**:
- Layer count between agent and Kalshi order ≤ 3
- No pass-through wrappers in 15m path
- 15m config keys ≤ 50 (or defined threshold)
- No future-proofing constructs in 15m path
- README/docs describe 15m as only mainline
- Architectural budget and unused abstraction CI checks in place
- Simplification review process documented

**Rollback**: Git revert if unexpected errors

---

## Phase 21: External Benchmark & Gap Analysis

### 21.1 Document Kalshi 15m Crypto Market Structure

**Goal**: Document Kalshi 15m crypto market structure and microstructure properties using public sources

**Action 1: Create market structure doc**

```bash
mkdir -p docs/15m_quant_kalshi
```

Create `docs/15m_quant_kalshi/market_structure.md` with:
- Kalshi 15m crypto contract specification (BTC/ETH/SOL/XRP/DOGE)
- Binary up/down questions with target prices and short expiry windows
- Implied probabilities and payout profiles
- Venue-side UI exposure (price, probability, payoff)
- Reference sources: Kalshi crypto 15m page, Good Money Guide article

**Action 2: Document microstructure properties**

Add to `docs/15m_quant_kalshi/market_structure.md`:
- Quote-driven orderbook with makers and takers
- Price vs probability deviations (cheap contracts win less often than price suggests)
- Ultra-short crypto prediction markets as binary options
- Volume and liquidity patterns
- Reference sources: CEPR research, European Business Magazine article

**Verification**:
```bash
# Verify docs created
ls docs/15m_quant_kalshi/market_structure.md
# Verify content includes key sections
grep -q "contract specification\|binary up/down\|implied probability\|orderbook\|price vs probability" docs/15m_quant_kalshi/market_structure.md
```

**Expected**: Market structure and microstructure documented with public source references

**Rollback**: Git revert if unexpected errors

---

### 21.2 Add Whitepaper-Style Strategy Doc

**Goal**: Create `docs/15m_quant_kalshi/whitepaper.md` with strategy + evaluation skeleton

**Action**: Create whitepaper with sections:

```bash
# Create whitepaper skeleton
cat > docs/15m_quant_kalshi/whitepaper.md << 'EOF'
# 15m Kalshi Crypto Quant Strategy

## Section 1: Market Description
- 15m BTC/ETH/SOL/XRP/DOGE contracts
- Binary up/down structure
- Microstructure properties

## Section 2: Data and Features
- Spot feed
- Orderbook state
- Time to expiry
- Venue signals

## Section 3: Strategy
- Entry criteria
- Exit criteria
- Sizing and risk

## Section 4: Backtest Results
- Tables + charts (placeholder)
- PnL, hit rate, edge vs price
- Risk metrics per asset

## Section 5: Live Monitoring
- Deviations vs backtest
- Gap map
- TODO items
EOF
```

**Verification**:
```bash
# Verify whitepaper created
ls docs/15m_quant_kalshi/whitepaper.md
# Verify sections exist
grep -q "Market Description\|Data and Features\|Strategy\|Backtest Results\|Live Monitoring" docs/15m_quant_kalshi/whitepaper.md
```

**Expected**: Whitepaper skeleton with all required sections

**Rollback**: Git revert if unexpected errors

---

### 21.3 Implement Minimal Backtest Harness

**Goal**: Implement minimal backtest harness for historical 15m crypto contracts

**Action 1: Create backtest directory structure**

```bash
mkdir -p backtests/kalshi_15m_crypto/data
mkdir -p backtests/kalshi_15m_crypto/strategies
mkdir -p backtests/kalshi_15m_crypto/results
```

**Action 2: Create backtest engine skeleton**

```python
# backtests/kalshi_15m_crypto/engine.py
"""
Minimal backtest harness for Kalshi 15m crypto contracts.
"""

from dataclasses import dataclass
from typing import List, Dict
import pandas as pd

@dataclass
class KalshiContract:
    """Historical Kalshi 15m contract."""
    market_id: str
    ticker: str
    target_price: float
    expiry_time: float
    yes_price: float
    no_price: float
    outcome: bool  # True if YES won

@dataclass
class BacktestResult:
    """Backtest results per asset."""
    asset: str
    total_trades: int
    hit_rate: float
    total_pnl: float
    edge_vs_price: float
    max_drawdown: float

class Kalshi15mBacktestEngine:
    """Backtest engine for 15m crypto contracts."""
    
    def __init__(self):
        self.contracts: List[KalshiContract] = []
        self.results: Dict[str, BacktestResult] = {}
    
    def load_historical_contracts(self, data_path: str):
        """Load historical 15m contracts from CSV/JSON."""
        # Placeholder: implement data loading
        pass
    
    def run_strategy(self, strategy_fn):
        """Run strategy on historical contracts."""
        # Placeholder: implement strategy execution
        pass
    
    def compute_metrics(self) -> Dict[str, BacktestResult]:
        """Compute backtest metrics per asset."""
        # Placeholder: implement metric computation
        pass
```

**Action 3: Create reference strategy stub**

```python
# backtests/kalshi_15m_crypto/strategies/reference_strategy.py
"""
Reference strategy for Kalshi 15m crypto contracts.
Clean, minimal, benchmark strategy.
"""

def reference_strategy(contract: KalshiContract, spot_price: float) -> bool:
    """
    Reference strategy: enter if YES price > threshold.
    
    Args:
        contract: Kalshi contract
        spot_price: Current spot price
    
    Returns:
        True if should enter YES, False otherwise
    """
    # Placeholder: implement simple threshold rule
    return contract.yes_price > 0.85
```

**Verification**:
```bash
# Verify backtest structure exists
ls backtests/kalshi_15m_crypto/engine.py
ls backtests/kalshi_15m_crypto/strategies/reference_strategy.py
# Verify Python syntax
python -m py_compile backtests/kalshi_15m_crypto/engine.py
python -m py_compile backtests/kalshi_15m_crypto/strategies/reference_strategy.py
```

**Expected**: Backtest harness structure with engine and reference strategy stubs

**Rollback**: Git revert if unexpected errors

---

### 21.4 Build and Maintain Gap Map

**Goal**: Build "gap map" table comparing ideal documented system vs current stack

**Action**: Create gap map in whitepaper

```bash
# Add gap map section to whitepaper
cat >> docs/15m_quant_kalshi/whitepaper.md << 'EOF'

## Gap Map

| Dimension | Ideal documented system | Our stack today | Gap/TODO |
|-----------|------------------------|-----------------|----------|
| Edge model | Explicit probability model with calibration plots | Deterministic signals and heuristics (document now) | Build and document calibration |
| Backtest harness | Full historical replay per asset/timeframe | Partial tests, no full replay | Implement 15m replay engine |
| Price–prob mapping | Empirical mapping of Kalshi price→probability | Assumed mapping (price≈prob) | Estimate mapping, adjust logic |
| Microstructure usage | Features from orderbook, volume, spread, latency | Orderbook used mainly for execution | Add microstructure features |
| Architecture transparency | Clean, documented layers (venue/data/strategy/execution/risk) | Layers exist but not fully documented | Add architecture diagram |
| Live vs backtest parity | Clear guarantees and monitoring | Partial parity checks | Implement parity harness |
EOF
```

**Verification**:
```bash
# Verify gap map added
grep -q "Gap Map\|Edge model\|Backtest harness\|Price–prob mapping" docs/15m_quant_kalshi/whitepaper.md
```

**Expected**: Gap map table showing ideal vs current stack with TODO items

**Rollback**: Git revert if unexpected errors

---

### 21.5 Add Reference Implementation Stubs

**Goal**: Add `strategies/kalshi_15m_reference/` package with clean reference agents

**Action**: Create reference implementation package

```bash
mkdir -p strategies/kalshi_15m_reference
```

```python
# strategies/kalshi_15m_reference/__init__.py
"""
Reference implementation package for Kalshi 15m crypto agents.
Clean, minimal, benchmark agents per asset.
"""
```

```python
# strategies/kalshi_15m_reference/btc_15m_agent.py
"""
Reference BTC 15m agent with clear docstrings and single signal path.
"""

class BTC15mReferenceAgent:
    """
    Reference agent for BTC 15m Kalshi contracts.
    
    Entry criteria: [TODO]
    Exit criteria: [TODO]
    Sizing: [TODO]
    Risk: [TODO]
    """
    
    def __init__(self, config):
        self.config = config
    
    def generate_signal(self, market_state):
        """Generate trading signal from market state."""
        # Placeholder: implement signal generation
        pass
    
    def calculate_size(self, signal, bankroll):
        """Calculate position size from signal and bankroll."""
        # Placeholder: implement sizing
        pass
```

```python
# strategies/kalshi_15m_reference/eth_15m_agent.py
"""
Reference ETH 15m agent with clear docstrings and single signal path.
"""

class ETH15mReferenceAgent:
    """
    Reference agent for ETH 15m Kalshi contracts.
    
    Entry criteria: [TODO]
    Exit criteria: [TODO]
    Sizing: [TODO]
    Risk: [TODO]
    """
    
    def __init__(self, config):
        self.config = config
    
    def generate_signal(self, market_state):
        """Generate trading signal from market state."""
        # Placeholder: implement signal generation
        pass
    
    def calculate_size(self, signal, bankroll):
        """Calculate position size from signal and bankroll."""
        # Placeholder: implement sizing
        pass
```

**Verification**:
```bash
# Verify reference agents created
ls strategies/kalshi_15m_reference/__init__.py
ls strategies/kalshi_15m_reference/btc_15m_agent.py
ls strategies/kalshi_15m_reference/eth_15m_agent.py
# Verify Python syntax
python -m py_compile strategies/kalshi_15m_reference/*.py
```

**Expected**: Reference implementation package with clean agent stubs for BTC/ETH

**Rollback**: Git revert if unexpected errors

---

### 21.6 Success Criteria for External Benchmark

**Verification**:
```bash
# Verify all success criteria
# 1. Market structure doc exists
ls docs/15m_quant_kalshi/market_structure.md

# 2. Whitepaper exists with all sections
ls docs/15m_quant_kalshi/whitepaper.md
grep -q "Market Description\|Data and Features\|Strategy\|Backtest Results\|Live Monitoring\|Gap Map" docs/15m_quant_kalshi/whitepaper.md

# 3. Backtest harness structure exists
ls backtests/kalshi_15m_crypto/engine.py
ls backtests/kalshi_15m_crypto/strategies/reference_strategy.py

# 4. Gap map filled
grep -q "Gap Map" docs/15m_quant_kalshi/whitepaper.md

# 5. Reference implementation exists
ls strategies/kalshi_15m_reference/btc_15m_agent.py
ls strategies/kalshi_15m_reference/eth_15m_agent.py
```

**Expected**:
- Market structure doc with public source references
- Whitepaper skeleton with all required sections
- Backtest harness structure with engine and reference strategy
- Gap map table comparing ideal vs current stack
- Reference implementation package with clean agent stubs

**Rollback**: Git revert if unexpected errors

---

## 15m Operating Constitution

This constitution governs ongoing development and operations of the 15m Kalshi crypto stack to prevent drift from creeping back in. These are hard rules that must be followed for any change to the production system.

---

### Core Principle: Shape Before Scale

The 15m stack must remain:
- **Minimal**: Only what is needed for 15m execution
- **Deterministic**: No hidden behavior, magic, or ambiguity
- **Testable**: Every component can be tested in isolation
- **Observable**: Clear logs, metrics, and state visibility
- **Easy to reason about**: One canonical path per concept
- **Hard to misuse**: Explicit wiring, no implicit assumptions

---

### 1. New Code Must Justify Itself

Any new module, class, config key, UI route, or agent must answer **YES** to at least one of these questions:

- Does this directly improve 15m execution, risk, market data, fills, or UI truth?
- Can this be done by extending an existing module instead?
- Does this duplicate an existing concept?

If the answer is unclear or NO, **do not add it**.

**Enforcement**: Code review checklist must include justification for new abstractions.

---

### 2. One Canonical Path Per Concept

For the 15m stack, there must be exactly **one place** for each of these:

| Concept | Canonical Owner | Location |
|---------|----------------|----------|
| Asset whitelist | Config | `config/kalshi_crypto_15m.yaml` |
| Market catalog | Venue adapter | `merid/event_venues/kalshi/market_catalog.py` |
| Market state | Venue adapter | `merid/event_venues/kalshi/` |
| Bankroll | Risk manager | `merid/event_venues/kalshi/kalshi_risk.py` |
| Risk sizing | Risk manager | `merid/event_venues/kalshi/kalshi_risk.py` |
| Loop orchestration | Loop | `merid/loop.py` |
| Fills ledger | Fills ledger | `merid/fills_ledger.py` |
| Settlement handling | Settlement | `merid/settlement/` |
| UI market list | UI frontend | `web_frontend/` |
| Health view | UI frontend | `web_frontend/` |

**Rule**: Any change that introduces a second version of the same concept is **rejected**.

---

### 3. Legacy Code Quarantine

If old code is still needed for reference, it must be in `legacy/` and must satisfy:

- **Never imported** by 15m entrypoints
- **Never shown** in current docs
- **Never included** in default tests or CI
- **Never wired** into UI routes or runtime config

**Enforcement**: CI check `scripts/check_no_legacy_imports.sh` fails if active code imports from `legacy/`.

---

### 4. Simplification Before Addition

Every new addition must go through a simplification step:

- **Merge before adding**: Can existing modules be merged instead?
- **Delete before wrapping**: Can we delete instead of adding a wrapper?
- **Refactor before duplicating**: Can we refactor instead of duplicating?
- **Document before shipping**: Is the new logic documented before merge?

**Rule**: If a change adds more lines than it removes, it needs special justification.

---

### 5. UI Follows Backend, Not Vice Versa

The UI must reflect the **real 15m backend truth**:

- Only supported assets (BTC/ETH/SOL/XRP/DOGE)
- Only supported actions (15m YES/NO trading)
- Only real statuses (live, filled, settled)
- Only current contract types (15m binary options)
- No dead controls
- No speculative widgets
- No legacy vocabulary

**Rule**: UI cannot invent concepts that the backend does not use.

---

### Drift Gate: Pre-Merge Checklist

Every meaningful change must pass this gate:

```bash
# scripts/drift_gate_check.sh
#!/bin/bash

# 1. New abstraction check
echo "Checking for new abstractions..."
# [Implementation: detect new classes/adapters]

# 2. Duplicate concept check
echo "Checking for duplicate concepts..."
# [Implementation: detect similar class names/functions]

# 3. Second source of truth check
echo "Checking for second source of truth..."
# [Implementation: detect duplicate config keys/data models]

# 4. Legacy import check
echo "Checking for legacy imports in active code..."
rg "from legacy" merid/ web/ && exit 1

# 5. Reasonability check
echo "Checking if change makes stack harder to reason about..."
# [Implementation: count layers, complexity metrics]
```

**Rule**: If drift gate fails, change must be revised.

---

### Concept to Owner Mapping

Each important concept has **one owner**:

| Concept | Owner Service | Owner Module |
|---------|--------------|--------------|
| Market state | Venue adapter | `merid/event_venues/kalshi/` |
| Bankroll | Risk manager | `merid/event_venues/kalshi/kalshi_risk.py` |
| Fills | Fills ledger | `merid/fills_ledger.py` |
| Order routing | Order router | `merid/order_router.py` |
| Loop orchestration | Loop | `merid/loop.py` |
| Market dashboard | UI frontend | `web_frontend/` |

**Rule**: If multiple modules own the same thing, drift will happen. Refactor to single owner.

---

### Current Architecture Doc (Living Document)

Keep `docs/15m/ARCHITECTURE_CURRENT.md` as a short, living document answering:

- **What the 15m stack is**: BTC/ETH/SOL/XRP/DOGE 15m Kalshi execution
- **What it is not**: Multi-venue, consensus, sentiment, debate, swarm
- **What modules are active**: List of active modules and their purpose
- **What modules are legacy**: List of legacy modules and why they're kept
- **What concepts are banned**: Consensus, sentiment, debate, swarm, oracle

**Rule**: This doc must be updated with every architectural change.

---

### Narrow Definition of "Production Ready"

Production ready means:

- **Minimal**: No unused code, no "just in case" modules
- **Deterministic**: Same inputs produce same outputs, no hidden state
- **Testable**: Unit tests for all critical paths
- **Observable**: Logs, metrics, and health checks for all components
- **Easy to reason about**: Clear data flow, no magic
- **Hard to misuse**: Explicit configuration, no implicit defaults

Production ready does **not** mean:
- Supports everything
- Flexible
- Future proof
- Generic

**Rule**: If code is not production ready, it cannot be merged to main.

---

### Outside-In Review Pattern

When shaping future work, follow this sequence:

1. **What the UI should show**: Define user-facing behavior first
2. **What the operator needs to know**: Define operational requirements
3. **What the backend must guarantee**: Define backend contracts
4. **What data must exist**: Define data requirements
5. **What logic is actually required**: Implement minimal logic

**Rule**: Start from user experience, not from implementation details.

---

### Anti-Drift Rulebook

These are explicit engineering rules that must be followed:

- **One concept, one owner**: No shared ownership
- **One source of truth per domain**: No duplicate configs
- **No new abstraction without concrete use case**: No "maybe useful later"
- **No legacy import in active code**: Quarantine enforced
- **No config knob unless actively used**: Remove unused knobs
- **No UI route unless reflects live backend state**: UI truth
- **No fallback logic unless safe and tested**: No silent fallbacks
- **No "just in case" modules**: Delete uncertainty
- **No duplicate data models**: Single source of truth
- **No hidden behavior in startup or loop**: Explicit orchestration

---

### Release Discipline

**Pre-release checklist**:

- [ ] All drift gate checks pass
- [ ] Current architecture doc updated
- [ ] No legacy imports in active code
- [ ] One canonical path per concept verified
- [ ] UI reflects backend truth
- [ ] Tests pass for new functionality
- [ ] No new config knobs without justification
- [ ] No new abstractions without RFC

**Post-release monitoring**:

- Track new abstractions added
- Track config key count
- Track test coverage
- Track layer count between agent and Kalshi order
- Track drift gate failures

---

### Constitution Enforcement

**CI enforcement**:
- Drift gate check runs on every PR
- Legacy import check runs on every PR
- Architectural budget check runs on every PR
- Config key count check runs on every PR

**Code review enforcement**:
- Reviewer must check drift gate results
- Reviewer must verify one canonical path per concept
- Reviewer must verify UI follows backend truth

**Monthly review**:
- Review drift gate failures
- Review new abstractions added
- Review config key count trend
- Update current architecture doc
- Run simplification review

---

### Constitution Amendments

This constitution can be amended only through:

1. RFC in `docs/rfcs/` with clear justification
2. Approval from system owner
3. Update to this constitution document
4. Update to current architecture doc

**Rule**: No ad-hoc exceptions to the constitution.

---

## Risk Mitigation

1. **Feature Branch**: Create dedicated feature branch for each phase
2. **Code Review**: Require code review before merging each phase
3. **Gradual Rollout**: Merge phases sequentially, not all at once
4. **Monitoring**: Monitor startup time, loop cadence, memory usage after each phase
5. **Rollback Ready**: Have rollback commands ready for each phase
6. **Test Coverage**: Ensure 100% test coverage for retained features

---

**Plan Created**: 2026-05-19  
**Status**: Ready for execution
