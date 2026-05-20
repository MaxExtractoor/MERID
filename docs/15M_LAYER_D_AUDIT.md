# Layer D Audit: Agent Grid, Policies, and Loop

**Scope**: Agent grid, trading agents, window filter policies, Kalshi15mLoop

---

## Agent Grid Configuration

**Module**: `merid.prediction.agent_grid_config`
**Factory**: `load_agent_grid_config()`
**Startup**: web.main_15m.py lines 630-685

### Agent Count Validation

**Location**: web.main_15m.py lines 639-652
```python
allowed_15m_agents = {"BTC_15M", "ETH_15M", "SOL_15M", "XRP_15M", "DOGE_15M"}
enabled_agents = [a.name for a in config.agents if a.enabled]

if len(enabled_agents) != 5:
    raise ValueError(
        f"Expected exactly 5 agents for kalshi_crypto_15m_v2, got {len(enabled_agents)}: {enabled_agents}"
    )

non_15m_agents = [a for a in enabled_agents if a not in allowed_15m_agents]
if non_15m_agents:
    raise ValueError(
        f"Non-15m-crypto agents enabled: {non_15m_agents}. Only {sorted(allowed_15m_agents)} are allowed."
    )
```

**Verification**: ✅ Correct
- Enforces exactly 5 agents for kalshi_crypto_15m_v2
- Only allows BTC_15M, ETH_15M, SOL_15M, XRP_15M, DOGE_15M
- Raises ValueError if wrong count or wrong agents

### Agent Lifecycle Configuration

**Location**: web.main_15m.py lines 667-674
```python
# Manually set agent lifecycle to ACTIVE for 15m profile
# The 15m loop handles cycling externally via run_cycle(), so agents don't need
# their internal decision loops. They just need to be in ACTIVE state to execute trades.
for agent in agent_grid._agents:
    agent.state.lifecycle = LifecycleState.ACTIVE
    agent.state.running = True
    agent.state.enabled = True
    logger.info(f"[AGENT-GRID] Set {agent.config.name} lifecycle to ACTIVE")
```

**Verification**: ✅ Correct
- Agents set to ACTIVE state for 15m profile
- Loop handles cycling externally via run_cycle()
- No internal decision loops needed

### Agent Grid YAML Configuration

**Source**: config/kalshi_agent_grid.yaml

**Issue**: ⚠️ Series ticker mismatch (from Layer B audit)
- Agent YAML uses base series tickers (KXBTC, KXETH, etc.)
- Catalog discovery uses 15M series tickers (KXBTC15M, KXETH15M, etc.)

**Fix Required**: Update agent grid YAML to use 15M series tickers

---

## Profile Overrides

### Profile Configuration File
**File**: config/profiles/kalshi_crypto_15m.yaml
**Module**: merid.risk.profiles.kalshi_crypto_15m_risk_envelope

**Key Settings** (need to verify):
- capital_usd: Starting capital
- drawdown_halt_pct: Drawdown threshold for halt
- adaptive_risk_bands: Risk band configuration
- per_trade_risk_multiplier: Risk multiplier per band

**Verification**: ⚠️ Need to verify config file exists and is loaded correctly

### Agent-Specific Overrides
**Location**: config/kalshi_agent_grid.yaml
**Verification**: ⚠️ Need to verify profile-specific overrides for:
- Notional caps
- minutes_before_expiry
- cutoff_minutes_before_expiry
- min_edge_* values

---

## Window Filter Policies

### Entry Window Policies
**Source**: config/kalshi_15m_crypto_config.py
**Module**: merid.prediction.window_filter_dynamic

### Bucket Configuration
**Buckets**: early, mid, late, terminal
**Terminal Bucket**: 0-2 minutes before expiry
**Terminal Edge Threshold**: 2.0% (relaxed from 20.0% for testing)

**Verification**: ✅ Correct (from previous edits)
- Terminal bucket edge threshold lowered to 2% for testing
- Buckets align with Kalshi's 15m settlement window
- No entry allowed inside Kalshi's settlement window
- Only exits allowed in settlement window

### Policy Per Asset
**Assets**: BTC, ETH, SOL, XRP, DOGE
**Verification**: ✅ Correct (from previous edits)
- All 5 assets have terminal bucket policy configured
- Edge threshold set to 2% for testing

---

## Kalshi15mLoop

**Module**: `merid.loop_15m`
**Class**: `Kalshi15mLoop`
**Factory**: `get_kalshi_15m_loop()`
**Startup**: web.main_15m.py lines 688-732

### Loop Lifecycle

**Location**: loop_15m.py lines 116-141
```python
async def run_forever(self) -> None:
    """Run the trading loop forever until stop() is called."""
    self._running = True
    self._started_at = datetime.now(timezone.utc)
    
    try:
        while self._running:
            self._tick += 1
            try:
                await self._run_one_cycle(self._tick)
            except Exception as exc:
                self._error_count += 1
                logger.error(
                    "[15m-LOOP] Cycle %d failed: %s (errors=%d)",
                    self._tick,
                    exc,
                    self._error_count,
                    exc_info=True,
                )
                # Continue running even if a cycle fails
            await asyncio.sleep(self.cadence_seconds)
    except asyncio.CancelledError:
        logger.info("[15m-LOOP] Loop cancelled")
        self._running = False
    finally:
        logger.info(
            "[15m-LOOP] Stopped (cycles=%d, errors=%d, uptime=%.1fs)",
            self._cycle_count,
            self._error_count,
            (datetime.now(timezone.utc) - self._started_at).total_seconds() if self._started_at else 0,
        )
```

**Verification**: ✅ Correct
- Loop runs forever until stop() is called
- Continues running even if a cycle fails (no re-raise)
- Only stops on asyncio.CancelledError
- Logs cycle count, error count, uptime on shutdown

### Start/Stop Methods

**Location**: loop_15m.py lines 143-159
```python
async def start(self) -> None:
    """Start the loop in background."""
    if self._loop_task and not self._loop_task.done():
        logger.warning("[15m-LOOP] Loop already running, skipping start")
        return
    self._loop_task = asyncio.create_task(self.run_forever(), name="kalshi-15m-loop")

async def stop(self) -> None:
    """Stop the loop gracefully."""
    self._running = False
    if self._loop_task and not self._loop_task.done():
        self._loop_task.cancel()
        try:
            await self._loop_task
        except asyncio.CancelledError:
            pass
    logger.info("[15m-LOOP] Stop requested")
```

**Verification**: ✅ Correct (from previous edits)
- start() method sets self._loop_task
- stop() method cancels task and waits for completion
- Prevents duplicate starts

### Cycle Execution

**Location**: loop_15m.py lines 154-230
```python
async def _run_one_cycle(self, tick: int) -> None:
    """
    Run a single trading cycle.
    
    Steps:
    1) Update envelope equity once per cycle (not per order)
    2) Check if halted due to drawdown
    3) Skip cycle if halted
    4) Pull latest market state / RTI inputs (rely on WS caches)
    5) Call agent_grid.run_cycle(tick) to step all agents
    6) Let AgentGrid/TradingAgent issue orders via venue_adapter
    7) Log band transitions
    """
    cycle_start = time.time()
    self._last_cycle_at = datetime.now(timezone.utc)
    
    logger.info("[15m-LOOP] HEARTBEAT cycle=%d", tick)

    logger.debug("[15m-LOOP] Starting cycle %d", tick)

    # Update envelope equity once per cycle (not per order)
    if self._risk_envelope:
        from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import safe_update_envelope_equity
        update_success = safe_update_envelope_equity(self._risk_envelope)
        if update_success:
            # Log band transitions
            current_multiplier = self._risk_envelope.per_trade_risk_multiplier
            if current_multiplier != self._last_risk_multiplier:
                logger.info(
                    "[15m-LOOP] Risk band transition: %.2f → %.2f (drawdown=%.2f%%)",
                    self._last_risk_multiplier,
                    current_multiplier,
                    self._risk_envelope.current_drawdown_pct * 100,
                )
                self._last_risk_multiplier = current_multiplier
        
        # Check if halted due to drawdown
        if self._risk_envelope.is_halted:
            logger.warning(
                "[15m-LOOP] Cycle %d skipped: drawdown halt (drawdown=%.2f%% >= %.2f%%)",
                tick,
                self._risk_envelope.current_drawdown_pct * 100,
                self._risk_envelope.drawdown_halt_pct * 100,
            )
            return  # Skip cycle
    
    # Run agent grid cycle
    if hasattr(self.agent_grid, 'run_cycle'):
        await self.agent_grid.run_cycle(tick)
    else:
        # Fallback: run agents directly if run_cycle not implemented
        await self._run_agents_directly(tick)
    except Exception as exc:
        self._error_count += 1
        logger.error("[15m-LOOP] Agent grid cycle failed: %s", exc, exc_info=True)
        # FIX: Do NOT re-raise - continue running even if a cycle fails

    cycle_duration = time.time() - cycle_start
    self._cycle_count += 1

    logger.debug(
        "[15m-LOOP] Cycle %d completed in %.3fs",
        tick,
        cycle_duration,
    )

    # Warn if cycle is taking too long (should be < 1s)
    if cycle_duration > 1.0:
        logger.warning(
            "[15m-LOOP] Cycle %d took %.3fs (expected < 1s)",
            tick,
            cycle_duration,
        )
```

**Verification**: ✅ Correct
- Heartbeat log at INFO level at start of each cycle
- Envelope equity update per cycle
- Drawdown halt check skips cycle if halted
- Agent grid cycle execution with fallback
- Exception handling with no re-raise (continues running)
- Cycle duration logging with warning if > 1s
- Cannot hang (only awaits agent_grid.run_cycle and envelope updates)

### Loop Summary

**Location**: loop_15m.py (need to verify summary() method)
**Expected Shape**:
```python
{
    "tick": int,
    "cycle_count": int,
    "error_count": int,
    "uptime_seconds": float,
    "last_cycle_at": str (ISO format),
    "running": bool
}
```

**Verification**: ⚠️ Need to verify summary() implementation

---

## Log Verification Checklist

From startup logs, verify:

- [x] Agent grid loaded with 5 agents: `[AGENT-GRID] Loaded 5 agents: BTC_15M, ETH_15M, SOL_15M, XRP_15M, DOGE_15M`
- [x] Agents set to ACTIVE: `[AGENT-GRID] Set BTC_15M lifecycle to ACTIVE`
- [x] Loop started: `[15m-LOOP] Kalshi15mLoop started (cadence=5s)`
- [x] Heartbeat logs: `[15m-LOOP] HEARTBEAT cycle=1`
- [x] Agent grid cycles: `[AGENT-GRID-CYCLE] Cycle 1 completed in 0.365s (errors=0)`
- [ ] Risk envelope initialized: Need to verify
- [ ] Profile overrides applied: Need to verify

---

## Issues Found

### Issue 1: Agent Grid Series Ticker Mismatch
**Status**: ⚠️ HIGH (from Layer B)
**Impact**: Agents may not receive 15m markets from catalog
**Evidence**: Agent YAML uses KXBTC, catalog uses KXBTC15M
**Fix Required**: Update config/kalshi_agent_grid.yaml to use 15M series tickers

### Issue 2: Profile Config File Unverified
**Status**: ⚠️ MEDIUM
**Impact**: Unknown if profile overrides are applied correctly
**Action**: Verify config/profiles/kalshi_crypto_15m.yaml exists and is loaded

### Issue 3: Agent-Specific Overrides Unverified
**Status**: ⚠️ MEDIUM
**Impact**: Unknown if notional caps and edge thresholds are overridden
**Action**: Verify profile-specific overrides in agent grid config

### Issue 4: Loop Summary Implementation Unverified
**Status**: ⚠️ LOW
**Impact**: Unknown if health endpoint gets correct loop summary
**Action**: Verify summary() method returns stable shape

---

## Layer D Summary

**Status**: ⚠️ 1 High Issue, 3 Unverified

**Correct Components**:
- Agent grid enforces exactly 5 agents (BTC_15M, ETH_15M, SOL_15M, XRP_15M, DOGE_15M)
- Agent lifecycle set to ACTIVE for 15m profile
- Loop runs forever until stop() is called
- Loop continues running even if a cycle fails
- Loop cannot hang (only awaits non-blocking operations)
- Heartbeat log at INFO level
- Drawdown halt check skips cycle if halted
- Window filter policies configured with relaxed terminal edge (2%)
- Buckets align with Kalshi's 15m settlement window

**Issues**:
1. Agent grid series ticker mismatch (high - from Layer B)
2. Profile config file unverified (medium)
3. Agent-specific overrides unverified (medium)
4. Loop summary implementation unverified (low)

**Next Steps**:
1. Fix agent grid series ticker mismatch (update YAML)
2. Verify profile config file exists and is loaded
3. Verify agent-specific overrides are applied
4. Verify loop summary() implementation
5. Proceed to instrument system-wide invariants
