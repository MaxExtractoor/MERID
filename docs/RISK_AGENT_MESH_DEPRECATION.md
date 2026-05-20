# Risk Agent Mesh Deprecation Notice

**Status:** LEGACY - Not used in production 15m Kalshi crypto stack  
**Profile:** `kalshi_crypto_15m_v2`  
**Date:** 2026-05-17

---

## Summary

`risk-agent-01` and its "hard veto with no target — cleared all pending votes" behavior are part of an old LLM-driven AgentMesh consensus layer, not the current 15m Kalshi stack. They are **sentiment-contaminated, legacy**, and **completely disconnected** from `kalshi_crypto_15m_v2`.

For 15m BTC/ETH/SOL/XRP/DOGE, the only live risk/consensus path is Crypto15MLane's deterministic RCK + Bayesian logic, which is aligned with how a real risk team should operate.

---

## Architecture

### Where risk-agent-01 lives

**Three implementations exist:**

1. **`agents/streaming/risk_agent.py`** (LLM-based, sentiment-contaminated)
   - Uses `model="merid-interface:latest"` (gemma3:1b fine-tune)
   - Veto logic: confidence < 0.6 triggers "risk_veto" event
   - Inputs: market price history, agent confidence levels
   - This is the version instantiated in `agents/agent_mesh.py`

2. **`agents/core/risk_agent.py`** (deterministic, pure risk metrics)
   - Pure risk logic: volatility, drawdown, exposure, VaR, Sharpe
   - No LLM dependency
   - Not used in production AgentMesh

3. **`agents/risk.py`** (LLM-based, gemma3:1b)
   - Another LLM-based implementation
   - Not used in production AgentMesh

### Consensus engine location

**`core/consensus_engine.py`** (OLD multi-agent mesh system)
- Line 385: "Hard veto from {event.source} with no target — cleared all pending votes"
- Handles `risk_veto` events via StreamEvent
- Subscribes to AGENT_OUTPUT channel
- Clears pending votes when veto received

### Profile gating (CRITICAL)

**`web/startup_agents.py` lines 161-162:**
```python
elif _profile == "kalshi_crypto_15m_v2":
    logger.info("[PROFILE-GUARD] AgentMesh skipped for kalshi_crypto_15m_v2 (LLM agents not needed for 15m crypto)")
```

**`web/main_15m.py`** is the dedicated entrypoint for kalshi_crypto_15m_v2 profile
- Does NOT start AgentMesh
- Does NOT start core consensus engine
- Uses Crypto15MLane instead (pure lane-based orchestration)

### Inputs and veto conditions

**Streaming risk-agent-01 (the one in AgentMesh):**
- Inputs: price history, agent confidence, signal type
- Veto condition: `confidence < 0.6` triggers "risk_veto"
- Veto action: emits `{"type": "risk_veto", "action": "VETO", ...}`

**Consensus engine veto semantics:**
- Event type: "risk_veto"
- When veto_target is specified: clears votes for that proposal only
- When veto_target is NOT specified: **clears ALL pending votes** (legacy behavior)
- This is the "hard veto" path being deprecated

### Interaction with 15m Kalshi stack

**NONE.** The risk-agent-01 hard veto path is completely disconnected from the production 15m Kalshi stack:

1. AgentMesh is skipped for kalshi_crypto_15m_v2 profile
2. Crypto15MLane uses its own consensus logic (RCK + Bayesian)
3. Crypto15MLane does not emit "risk_veto" events
4. Crypto15MLane does not subscribe to core consensus engine
5. The only reference to `core.consensus_engine` in lanes is in `consensus_engine_integration.py`, which is documentation-only (example code in comments, not actually called by Crypto15MLane)

---

## Production Invariant

For `MERID_PROFILE=kalshi_crypto_15m_v2`:

> **AgentMesh and `core.consensus_engine` are disabled by design.**
> 
> All production risk decisions are handled inside Crypto15MLane with deterministic RCK + Bayesian logic (no LLM, no sentiment, no mesh).

This invariant is enforced by:
- Profile guard in `web/startup_agents.py` (raises if AgentMesh is started under kalshi_crypto_15m_v2)
- Deprecation guards in legacy modules (log warnings if imported under kalshi_crypto_15m_v2)
- Dedicated entrypoint `web/main_15m.py` that does not start AgentMesh or consensus engine

---

## Veto Log Contract (15m Profile)

Since risk-agent-01 is deprecated, the log contract applies to any future veto mechanisms in Crypto15MLane.

**Current Implementation:**
Crypto15MLane uses deterministic RCK + Bayesian logic that rejects trades by returning `position_size=0` (no order submission) rather than emitting veto events. This is the correct behavior for the 15m profile - deterministic, explainable risk controls without opaque veto events.

**Future Veto Mechanisms:**
If any veto mechanism is added to Crypto15MLane (e.g., liquidity guard, edge threshold guard, etc.), every veto log in the 15m profile must include:
- **agent**: Which component issued the veto (e.g., "RCK_SOLVER", "EDGE_THRESHOLD", "LIQUIDITY_GUARD")
- **asset**: Target asset (BTC/ETH/SOL/XRP/DOGE) or `target=global`
- **series**: Kalshi series ticker (e.g., KXBTC15M)
- **reason**: Standardized reason code (e.g., "EDGE_TOO_LOW", "DRAWDOWN_RISK", "LIQUIDITY_INSUFFICIENT")
- **Key risk metrics**:
  - edge_bps: Edge in basis points
  - kelly_full: Full Kelly fraction
  - kelly_rck: RCK-constrained Kelly fraction
  - kelly_used: Final Kelly fraction used
  - dd_prob: Drawdown probability
  - size_contracts: Position size in contracts
  - bankroll_before: Bankroll before trade
  - bankroll_after: Bankroll after trade

**Example log format:**
```
[VETO] agent=RCK_SOLVER asset=BTC series=KXBTC15M reason=EDGE_TOO_LOW edge_bps=25 min_edge_bps=50 kelly_used=0.15 dd_prob=0.08 size=0 bankroll_before=100000 bankroll_after=100000
```

---

## Why This Is Safe

- Kalshi's risk/guardrail story is at the exchange level (prohibited trading, rate limits, integrity rules)
- The job is to implement **deterministic, explainable risk controls** on top of that, not a black-box LLM veto mesh
- Crypto15MLane already does this with RCK/Bayesian risk and position sizing; the mesh path was duplicate, unaligned logic from an older architecture

By fencing `risk-agent-01` and the mesh consensus as legacy:
- The 15m Kalshi profile remains sentiment-free and reproducible
- Mystery "hard veto" behavior that can silently nuke trading cycles is avoided
- Code readability is improved (obvious what is live vs experiment)

---

## Files Marked as Legacy

The following files are part of the deprecated LLM/mesh risk system and must NOT be wired into any production trading or execution path for `kalshi_crypto_15m_v2`:

- `agents/streaming/risk_agent.py` (LLM-based risk agent)
- `agents/agent_mesh.py` (multi-agent mesh orchestration)
- `core/consensus_engine.py` (old consensus engine)
- `merid/lanes/consensus_engine_integration.py` (documentation-only integration example)

Each file contains a deprecation guard with module-level constant `LEGACY_EXPERIMENTAL_ONLY = True` and a clear deprecation notice.
