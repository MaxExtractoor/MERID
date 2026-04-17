# Consensus Full Wiring — Design Spec

**Date:** 2026-03-21
**Status:** Approved
**Scope:** Wire all grid agents + external agents into `SwarmConsensusAggregator` using only existing infrastructure

---

## Problem

`Consensus #7: REJECTED — Confidence: 14.3% (7 agents)`

The consensus engine is production-ready but operating on two hardcoded agents (sentiment + Fear/Greed contrarian) that only consume news/social data. The 22-agent grid defined in `kalshi_agent_grid.yaml` is fully configured but silent. Live Kalshi market data (which contracts are open, their prices, spreads, distance from spot) never reaches the consensus vote. The result is a systemically low-confidence consensus that has no awareness of actual tradeable markets.

---

## What Already Exists (No New Abstractions Needed)

| Component | File | Status |
|---|---|---|
| `SwarmConsensusAggregator` | `merid/swarm/consensus_aggregator.py` | Production-ready |
| `KalshiConsensusAdapter` | `merid/prediction/consensus_bridge.py` | Has `signal_to_energy()` and `order_intent_to_vote()`; `signal_to_proposal()` is **fully new** |
| `get_kalshi_consensus_adapter()` | `merid/prediction/consensus_bridge.py:340` | Singleton accessor — use this, not `KalshiConsensusAdapter()` directly |
| `AgentGrid` | `merid/prediction/agent_grid.py` | Full — instantiates all grid agents from YAML in `__init__`, starts in `start()` |
| `AgentGridConfig` | `merid/prediction/agent_grid_config.py` | Full — typed loader for `kalshi_agent_grid.yaml` |
| `KalshiTradingAgent` | `merid/prediction/trading_agent.py` | Has `_run_cycle_body()` (signal) and `_execute_signal_body()` (order submission); has degradation tracking + solo-trade caps; never calls `submit_proposal()` |
| `CryptoSurfaceLoader` | `services/crypto_surface_loader.py` | Has `subscribe_updates(callback)` — no agent subscribes; callback may be sync or async |
| `ConsensusStatus` enum | `merid/swarm/consensus_aggregator.py:39` | `FORMING`, `READY`, `CONFLICTED`, `STALE` — must use enum members, not strings |
| `ConsensusView` | `merid/swarm/consensus_aggregator.py` | Field is `consensus_direction` (not `direction`); values are `"yes"/"no"/"neutral"` |
| `MarketMoodBus` | `merid/swarm/market_mood_bus.py` | Running, feeds context |
| `ConsensusBlock` + audit | `merid/lanes/consensus_integration.py` | Full — `create_consensus_block_from_lane(market_data, consensus_result)` |
| `AuctionConsensusResolver` | `merid/swarm/auction_consensus.py` | Full, called on CONFLICTED |

---

## Design — Three Wires

### Wire 1 — `CryptoSurfaceLoader` → Each Grid Agent

**Where:** `AgentGrid.__init__()` acquires the loader; `AgentGrid.start()` does the subscriptions.

**What:**

```python
# In AgentGrid.__init__() — acquire singleton loader:
from services.crypto_surface_loader import get_crypto_surface_loader
self._surface_loader = get_crypto_surface_loader()

# In AgentGrid.start() — subscribe each crypto agent:
for agent in self._agents:
    if agent.config.category == "crypto":
        self._surface_loader.subscribe_updates(agent.on_surface_update)
```

**Agent side:** Add `on_surface_update(snapshot: CryptoSurfaceSnapshot)` to `KalshiTradingAgent`:

```python
def on_surface_update(self, snapshot: CryptoSurfaceSnapshot) -> None:
    entry = snapshot.get_entry(self.asset, self.timeframe)
    if entry is None:
        return
    # Both _live_markets writes and _run_cycle_body reads run in the same
    # asyncio event loop — cooperative scheduling makes this safe without a lock.
    self._live_markets = select_markets_near_spot(entry)
```

The result is stored as `self._live_markets: List[KalshiMarketView]` (initialised to `[]` in `__init__`).

**Non-crypto agents** (macro, politics, financials): `category != "crypto"` agents skip `on_surface_update`. They call `KalshiMarketCatalog.get_markets_by_filter(agent.config.market_filter)` on each cycle and store results in the same `self._live_markets` field. Wire 2 and Wire 3 are identical for both paths.

**Effect:** Every agent knows its live tradeable contracts at all times. Proposals are grounded in actual open markets with real spread/distance data rather than a stale catalog scan.

---

### Wire 2 — `KalshiTradingAgent` → `KalshiConsensusAdapter` → `SwarmConsensusAggregator`

**Where:** `KalshiTradingAgent._run_cycle_body()` in `merid/prediction/trading_agent.py`, after strategy signal is computed.

**What:**

```python
from merid.prediction.consensus_bridge import get_kalshi_consensus_adapter
from merid.swarm.consensus_aggregator import get_consensus_aggregator

# After strategy_signal is computed inside _run_cycle_body():
proposal = get_kalshi_consensus_adapter().signal_to_proposal(
    signal=strategy_signal,
    agent_id=self.agent_id,
    asset=self.asset,
    timeframe=self.timeframe,
    live_markets=self._live_markets,  # from Wire 1
    track_record=self._track_record,  # already on agent
)
get_consensus_aggregator().submit_proposal(proposal)
```

**`signal_to_proposal()` is a fully new method** — not a skeleton completion. Add it to `KalshiConsensusAdapter` in `consensus_bridge.py`:

- Maps `StrategySignal.action` (a `SignalAction` enum: `BUY_YES`, `BUY_NO`, `HOLD`) → `AgentProposal.direction` (`"yes"` / `"no"` / `"neutral"`). Use the existing `_action_to_direction()` helper but extend its output mapping from `"long"/"short"` to `"yes"/"no"`.
- Sets `probability` from signal's edge estimate + base rate (0.5 + edge/100 clamped to [0.05, 0.95])
- Sets `confidence` from signal's confidence score
- Sets `agent_archetype` from `agent.config.archetype` (passed in via `track_record` or a separate param)
- Populates `market_data: Optional[Dict[str, Any]]` from `live_markets[0]` if available (see Proposal Enrichment section below)

**`AgentProposal.market_data`** is defined as `Optional[Dict[str, Any]]` in the dataclass but is currently always `None`. This wires it for the first time.

**Effect:** All 22 grid agents submit weighted proposals each cycle. `SwarmConsensusAggregator` gains archetype diversity (directional, market_maker, contrarian, macro, etc.), enabling `READY` status.

---

### Wire 3 — Consensus Reads Back Into Execution Gate

**Where:** `KalshiTradingAgent._execute_signal_body()` in `merid/prediction/trading_agent.py`, before order submission.

**What:**

```python
from merid.swarm.consensus_aggregator import get_consensus_aggregator, ConsensusStatus

consensus = get_consensus_aggregator().get_consensus(self.asset, self.timeframe)

if consensus is None or consensus.status == ConsensusStatus.STALE:
    # Existing degradation path — AgentState.swarm_degraded already tracks this.
    # _apply_solo_trade_cap() is a NEW helper: cap contracts to "small" band,
    # enforce max 3 trades per degraded session (already tracked in AgentState).
    self._apply_solo_trade_cap(order_intent)
    # Continue to execution at capped size — do not skip.

elif consensus.status == ConsensusStatus.FORMING:
    # Not enough agent diversity yet — skip this cycle, do not trade.
    return

else:
    # Map strategy signal action to consensus vocabulary before comparing.
    # SignalAction uses BUY_YES/BUY_NO; ConsensusView.consensus_direction uses "yes"/"no"/"neutral".
    signal_dir = _signal_action_to_consensus_dir(strategy_signal.action)
    if signal_dir != consensus.consensus_direction and consensus.confidence > 0.7:
        # High-confidence consensus opposes this agent's view — skip.
        return
    # Apply size band from consensus (small / reduced / base / large).
    # _apply_size_band() is a NEW helper that maps band string → contracts scalar.
    order_intent.contracts = self._apply_size_band(
        base_contracts=order_intent.contracts,
        band=consensus.size_band,
    )
```

Where `_signal_action_to_consensus_dir` is a small module-level helper:

```python
def _signal_action_to_consensus_dir(action: SignalAction) -> str:
    if action == SignalAction.BUY_YES:
        return "yes"
    if action == SignalAction.BUY_NO:
        return "no"
    return "neutral"
```

**New helpers needed in `trading_agent.py`** (both small, no external deps):

- `_apply_solo_trade_cap(order_intent)` — enforce "small" size band + check `AgentState.solo_trades_this_degraded_session < 3`
- `_apply_size_band(base_contracts, band) -> int` — multiply by band scalar (`small=0.25`, `reduced=0.5`, `base=1.0`, `large=1.5`) and round down

**`ConsensusBlock` audit wiring:** After `KalshiExecutor.submit()` succeeds, write the audit block:

```python
from merid.lanes.consensus_integration import create_consensus_block_from_lane

# market_data and consensus_result must be built from locals available in _execute_signal_body():
create_consensus_block_from_lane(
    market_data={
        "ticker": order_intent.market_id,
        "market_ticker": order_intent.market_id,
        "yes_bid": self._live_markets[0].yes_price if self._live_markets else None,
        "no_bid": self._live_markets[0].no_price if self._live_markets else None,
        "spread_bps": self._live_markets[0].spread_bps if self._live_markets else None,
    },
    consensus_result={
        "direction": consensus.consensus_direction if consensus else "neutral",
        "probability": consensus.probability if consensus else 0.5,
        "confidence": consensus.confidence if consensus else 0.0,
        "status": consensus.status.value if consensus else "stale",
        "size_band": consensus.size_band if consensus else "small",
    },
)
```

**Effect:** Agents no longer trade against consensus. The consensus direction acts as a circuit gate. Solo-trading caps activate correctly when consensus is stale.

---

## Proposal Enrichment — Market Data Field

After Wire 1 + Wire 2, each `AgentProposal.market_data` carries:

```python
{
    "top_market_id": "KXBTC15M-71000",
    "spot_price": 70743.69,
    "target_price": 71000.00,
    "distance_pct": 0.36,
    "yes_price_cents": 49,
    "no_price_cents": 51,
    "spread_bps": 20,
    "open_interest": 1240,
    "expiry_minutes": 8,
    "markets_in_band": 4,
}
```

This data is already fetched by `CryptoSurfaceLoader` every 10s but currently discarded. The `SwarmConsensusAggregator` stores it on each proposal unchanged — the field exists in `AgentProposal`, just never populated.

---

## Data Flow After Wiring

```text
CryptoSurfaceLoader (every 10s)
    │  notify_subscribers(snapshot)
    ▼
KalshiTradingAgent.on_surface_update(snapshot)          [Wire 1]
    │  self._live_markets = select_markets_near_spot(entry)
    ▼
KalshiTradingAgent._run_cycle_body()
    │  strategy_signal = strategy.compute(sentiment, market_data)
    │
    ├──► get_kalshi_consensus_adapter().signal_to_proposal()   [Wire 2]
    │         │  market_data = self._live_markets[0]
    │         │  direction mapped: SignalAction → "yes"/"no"/"neutral"
    │         ▼
    │    get_consensus_aggregator().submit_proposal(proposal)
    │         │  weighted vote from 22 agents
    │         │  Brier calibration weights applied
    │         │  archetype diversity check (need 2+ archetypes for READY)
    │         ▼
    │    ConsensusView (status: ConsensusStatus.READY / FORMING / CONFLICTED)
    │         │  published to MarketMoodBus + event_bus
    │         ▼
    │    AuctionConsensusResolver (if CONFLICTED)
    │
    └──► KalshiTradingAgent._execute_signal_body()             [Wire 3]
              │  consensus = get_consensus(asset, tf)
              │  compare consensus.consensus_direction vs signal_dir
              │  apply size band or solo-trade cap
              ▼
         KalshiExecutor.submit(order_intent)
              │
              └──► create_consensus_block_from_lane(market_data, consensus_result)
```

---

## What Does NOT Change

- `SwarmConsensusAggregator` — untouched
- `AuctionConsensusResolver` — untouched
- `MarketMoodBus` — untouched
- `SwarmMatrixBuilder` — untouched
- All existing proposal weighting / Brier calibration logic — untouched
- `SwarmVerdictFeed` (Phase 13b) — automatically improves as more proposals arrive
- Hardcoded sentiment + FG contrarian agents in `BTC15MLane` — kept as-is (they contribute additional archetypes)

---

## Files Changed

| File | Change |
|---|---|
| `merid/prediction/agent_grid.py` | Wire 1: acquire `CryptoSurfaceLoader` singleton in `__init__`; subscribe each crypto agent in `start()` |
| `merid/prediction/trading_agent.py` | Wire 1: add `on_surface_update()` + init `_live_markets = []`; Wire 2: call `submit_proposal()` in `_run_cycle_body()`; Wire 3: consensus gate + `_apply_solo_trade_cap()` + `_apply_size_band()` in `_execute_signal_body()`; audit block after submit |
| `merid/prediction/consensus_bridge.py` | Wire 2: add full new `signal_to_proposal()` method; extend `_action_to_direction()` to output `"yes"/"no"` |
| `merid/lanes/btc15m_lane.py` | Wire 3 (optional): forward consensus read to existing lane risk check |

---

## Out of Scope (Follow-on)

- RCK + Bayesian dataclasses from `rck_complete_example.py` — drop-in after this ships
- LLM agent roles (`agents/llm_roles.py`) submitting proposals — same Wire 2 pattern, separate PR
- Signal quality monitoring degradation — frontend ready, backend wiring is post-this
- HTTP client migration (unrelated)
