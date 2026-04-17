# MERID Intelligence & Data Layer Audit Report

**Date:** 2026  
**Auditor role:** Senior quant engineer / ML systems architect  
**Scope:** Data pipelines → signal engineering → swarm reasoning → consensus → risk → order  
**Branch audited:** develop  

---

## Data Layer Map

### Primary Data Sources and Ingest Paths

| Source | Ingest Path | Consumer | Validation |
|--------|-------------|----------|------------|
| Kalshi REST API | `KalshiVenueClient.get_market_result()` → `OutcomeResolver._get_outcome_from_kalshi()` | `CalibrationStore`, `RealizedEdgeStore` | None — silent `None` return on any API error |
| Kalshi WebSocket | `merid/event_venues/kalshi/ws.py` | `KalshiTradingAgent._resolve_markets()` → `EventMarket` objects | No schema version check |
| Live crypto price feed | `data/live_price_feed.py` `LivePriceFeed` → `price_cache` | `PredictionMarketModel._price_feed` for crypto-relative probabilities | `timestamp` field exists but **age is never checked** at consumer |
| Kalshi market catalog | `merid/event_venues/kalshi/market_catalog.py` → `get_market_catalog()` | `KalshiTradingAgent._build_snapshot()` (strike lookup), `OutcomeResolver` fallback | No staleness check on cached entries |
| Backtesting OHLCV | `LivePriceFeed.fetch_historical_ohlcv()` | `BacktestEngine._fetch_historical_data()` | Limit hard-coded to 500 candles; no date-range alignment check |
| Sentiment service | `merid/event_venues/kalshi/sentiment.py` `get_sentiment_service()` | `KalshiTradingAgent._build_snapshot()` → `snapshot.sentiment_*` fields | Entirely swallowed on exception; snapshot retains `None` |
| MarketMoodBus | `merid/swarm/market_mood_bus.py` | `KalshiTradingAgent._get_mood_context()` | No freshness check; `fg_index` injected verbatim into `sentiment_global` |
| CalibrationStore | `merid/metrics/calibration.py` SQLite | `ForecasterRegistry`, `SwarmConsensusAggregator`, `ConsensusEngine` | No read-freshness check; `DEFAULT_WEIGHT=1.0` silently on any error |

---

## 1. High-Risk Intelligence / Data Bugs

### BUG-01 — Stale Price Feed Injected Into Edge Computation Without Age Check

- **Name:** `stale-price-feed-edge`
- **Location:** `data/live_price_feed.py` (`PriceData.timestamp`), `merid/prediction/model.py` `compute_edge()`, `KalshiTradingAgent._build_snapshot()`
- **Category:** Data-quality / Robustness
- **Description:**  
  `LivePriceFeed` caches prices in `self.price_cache: Dict[str, PriceData]` keyed by symbol. Each `PriceData` carries a `timestamp: datetime` field. `PredictionMarketModel.compute_edge()` (line ~139) calls `get_live_price_feed()` and reads from the same cache. **No consumer checks `price_cache[symbol].timestamp` against a maximum age before using the price.** If the feed loop stops (exchange circuit breaker trips, network failure, KALSHI_ONLY mode silently skips initialization), the cache goes stale indefinitely and `compute_edge()` continues deriving crypto-relative implied probabilities from a days-old price — with no exception or flag. Additionally, `_initialize_exchanges()` is a no-op in `KALSHI_ONLY` mode (`data/live_price_feed.py` line 105), leaving the cache permanently empty; if any code downstream calls the feed outside of that guard the result is `None`.
- **Impact:**  
  During a fast BTC move, `compute_edge()` could be working from a price that is hours old — a 5 % BTC move would shift a BTC-strike Kalshi contract's "fair value" by several cents while `p_model` stays anchored to the stale reference. The edge estimate would appear positive (or negative) in the wrong direction, and the swarm would size into a position the live market has already priced out.
- **Proposed fix:**  
  Add a `MAX_PRICE_AGE_SECONDS = 30` constant. In `compute_edge()` (and anywhere else `price_cache` is read), assert `(datetime.now() - cached.timestamp).total_seconds() < MAX_PRICE_AGE_SECONDS` before using the price; return `None` edge or raise a `StalePriceError` otherwise. Emit a DataFreshness alert when age exceeds threshold.

---

### BUG-02 — Global `_momentum_history` and `_active_snapshots` Not Thread-Safe

- **Name:** `global-state-race`
- **Location:** `merid/prediction/forecasters/momentum.py` line 26 (`_momentum_history`), `merid/prediction/model.py` line 101 (`_active_snapshots`)
- **Category:** Data-quality / Robustness
- **Description:**  
  `_momentum_history` is a module-level `defaultdict(list)` and `_active_snapshots` is a module-level `List[MarketSnapshot]`. Both are mutated by `_record_observation()` and `build_snapshot()` respectively. Multiple `KalshiTradingAgent` instances (one per asset/timeframe cell) each create their own `PredictionMarketModel()` instance (line 100 of `trading_agent.py`) and their own `MomentumForecaster()` via the registry — but all share the **same module-level global dicts**. There is no lock protecting concurrent appends or reads. Under asyncio this is usually safe for single-threaded coroutines, but `get_forecaster_registry()` is also called from the CalibrationStore thread context (via `_log_forecast`), and the singleton lock pattern in `registry.py` lines 248-261 does not lock the global `_momentum_history` it populates.
- **Impact:**  
  Cross-contamination of momentum history between different asset agents (BTC 15m agent's volume signal leaking into ETH 1h agent's history), and potential list corruption under concurrent access, causing `_volume_momentum` to compute momentum from a mixed-asset history and generate a spurious directional signal.
- **Proposed fix:**  
  Move `_momentum_history` into the `MomentumForecaster` instance (per-forecaster state), not the module. Each `ForecasterRegistry` instance would own its own `MomentumForecaster`, eliminating sharing. Alternatively, key `_momentum_history` by `(market_id, forecaster_instance_id)` and protect mutations with `threading.Lock()`.

---

### BUG-03 — Backtest Engine Uses Live Feed for "Historical" Data (Look-Ahead / Wrong-Feed Bug)

- **Name:** `backtest-live-feed-lookahead`
- **Location:** `backtesting/engine.py` lines 249-262 (`_fetch_historical_data`), `backtesting/engine.py` line 257 (`limit=500` candles)
- **Category:** Backtest/live gap
- **Description:**  
  `BacktestEngine._fetch_historical_data()` calls `get_live_price_feed().fetch_historical_ohlcv(symbol, timeframe, limit=500)`. This means:  
  1. **The same live-feed singleton used for real-time trading is also the data source for backtests.** If the feed was recently reset or has sparse history, the backtest silently runs on whatever partial data the exchange returns.  
  2. The `limit=500` cap is hard-coded with no check against the requested `start_date`/`end_date` range from `BacktestConfig`. A 500-candle 1h backtest only reaches back ~21 days, but the config freely accepts date ranges spanning years — the strategy will silently run on 21 days of data with no error.  
  3. There is no timestamp alignment: OHLCV candle timestamps are compared to `BacktestConfig.start_date`/`end_date` only inside each strategy, and all built-in strategies (`_strategy_momentum`, `_strategy_mean_reversion`) ignore `config.start_date` entirely — they iterate all candles returned.  
  4. Slippage (`commission_pct`, `slippage_pct`) in `BacktestConfig` defaults to 0.1% / 0.05% but the live Kalshi system uses a flat `KALSHI_FEE_PER_CONTRACT_CENTS = Decimal("2")` tiered fee schedule (`merid/prediction/risk.py:143`). Backtest and live use **completely different fee models** with no reconciliation.
- **Impact:**  
  A strategy calibrated on 21-day backtest data looks good but is actually curve-fit to the trailing month. Optimistic backtested returns (missing tiered Kalshi fees) cause the system to treat speculative edges as actionable that would be fee-negative in live.
- **Proposed fix:**  
  Require `BacktestEngine` to use a dedicated historical data store (separate from the live feed singleton). Add a guard: `assert n_candles_returned >= expected_range_candles * 0.9`. Implement `KalshiBacktestFeeModel` using the same tiered schedule as `kalshi_fee_cents()` in `risk.py`.

---

### BUG-04 — Calibration Weights Bootstrapped at `DEFAULT_WEIGHT=1.0` Until 10 Resolved Outcomes

- **Name:** `cold-start-calibration-equal-weight`
- **Location:** `merid/metrics/calibration.py` lines 349-353 (`get_weight()`), `merid/swarm/consensus_aggregator.py` lines 468-475 (`_calculate_agent_weight()`), `merid/prediction/forecasters/registry.py` lines 233-240 (`_get_calibration_weight()`)
- **Category:** Swarm-logic / Data-quality
- **Description:**  
  `CalibrationStore.get_weight()` returns `DEFAULT_WEIGHT = 1.0` for any forecaster with fewer than `MIN_FORECASTS_FOR_WEIGHT = 10` resolved outcomes. This means:  
  - All 6 forecasters (momentum, mean_reversion, macro_regime, orderbook, time_series, sentiment) registered in `get_forecaster_registry()` start with equal weight `1.0` regardless of how many forecasts each has resolved.  
  - During the cold-start window (which could last **days** for slow-expiring contracts), the ensemble gives equal weight to every forecaster.  
  - More importantly, `_calculate_agent_weight()` in the consensus aggregator also falls back to `brier_weight * proposal.confidence` (line 497), meaning newly deployed agents with zero history get the **same** base weight as experienced agents, biasing the consensus toward whichever archetype has the most fresh proposals.
  - The 70/30 Brier-trust blend in `ConsensusEngine._extract_vote()` (line 213) multiplies a stale `1.0` Brier weight against the trust score — so the blend provides no calibration signal until 10+ contracts settle.
- **Impact:**  
  In the first week of live trading, the ensemble and consensus are equally influenced by every forecaster including untested ones. A spurious `MacroRegimeForecaster` or `ExternalSentimentForecaster` with no resolved Brier history can pull the consensus probability significantly in the wrong direction.
- **Proposed fix:**  
  Use a Bayesian prior: new forecasters start at `ewma_brier = 0.25` (coin-flip) which maps to weight `1.0` via `0.25/0.25`. This is already the design intent, but the guard at line 349 short-circuits it. Remove `MIN_FORECASTS_FOR_WEIGHT` guard or lower it to `1`. On the first resolved forecast, compute the real weight immediately. Add a `is_calibrated: bool` flag to `BrierStats` and expose it in the API so operators can see which forecasters are still cold.

---

### BUG-05 — Solo Execution Fallback After 3 Cycles Bypasses Swarm Consensus

- **Name:** `solo-execution-consensus-bypass`
- **Location:** `merid/prediction/trading_agent.py` lines 364-373 (`_run_cycle_body`)
- **Category:** Swarm-logic
- **Description:**  
  After cycle 3 with no consensus available, the agent falls through with `logger.debug("No consensus after %d cycles — proceeding solo")` and executes the signal without consensus validation. The explicit comment reads: *"Allow solo execution after 3 cycles without consensus to prevent permanent blocking when swarm bus is unavailable."*  
  This means:  
  - A single `KalshiTradingAgent` (e.g., BTC 15m) can unilaterally place real orders after just ~90 seconds if `SwarmConsensusAggregator` hasn't received proposals from a second archetype.  
  - The `min_archetypes = 2` diversity check in `consensus_aggregator.py` line 420 (which blocks consensus if only 1 archetype is present) is entirely bypassed in solo mode.  
  - The 3-cycle threshold (`cycles_run <= 3`) is evaluated against the **lifetime** cycle count, not a "cycles since last consensus", meaning once it exceeds 3 it never re-checks if the swarm recovers — the agent trades solo indefinitely.
- **Impact:**  
  A swarm bus disruption (NATS/event bus outage, import failure in `merid.swarm.consensus_aggregator`) silently degrades to single-agent trading. The system log would show `DEBUG` messages but no alerts. The risk layer (`PredictionMarketRisk`) still runs, but the swarm diversity guard is gone. A single miscalibrated agent can trade at full size.
- **Proposed fix:**  
  Replace the hard `cycles_run <= 3` guard with a `last_consensus_at` timestamp and a configurable `max_solo_run_seconds` (e.g. 120s). After solo threshold is crossed, downgrade `size_band` to `"small"` and emit a `WARNING` alert — never silently proceed at full size. Track a `swarm_degraded` flag in `AgentState` that is surfaced in the API and UI.

---

### BUG-06 — `compute_edge()` `p_model` Derivation: `implied + net_edge` Is Circular

- **Name:** `circular-p-model-derivation`
- **Location:** `merid/prediction/trading_agent.py` lines 773-779 (`_record_signal`)
- **Category:** Swarm-logic / Data-quality
- **Description:**  
  When `signal.edge.model_prob` is absent, `_record_signal()` reconstructs `p_model` as:
  ```python
  p_model = max(0.01, min(0.99, imp + edge_val))
  ```
  where `edge_val = signal.edge.net_edge`. But `net_edge` is itself computed by `compute_edge()` as `raw_edge - fee_drag - slippage_est`, and `raw_edge` is `model_prob - implied_yes_prob`. The reconstruction is therefore:  
  `p_model ≈ implied + (model_prob - implied - fees - slippage) ≈ model_prob - fees`  
  This underestimates the true `p_model` by exactly the fee drag, logged to the calibration store. Every Brier score computed against this synthetic `p_model` is systematically biased — it measures "model_prob minus fees" accuracy, not model probability accuracy. Forecasters that have high edge (and therefore high fee drag) will appear less well-calibrated than those with thin edge.
- **Impact:**  
  Calibration weights diverge from true forecaster skill. High-edge strategies get penalized in the Brier-weighted ensemble. The feedback loop (Sprint C) systematically tilts weight toward lower-conviction forecasters.
- **Proposed fix:**  
  Always store `model_prob` explicitly on `EdgeEstimate` (it is already computed inside `compute_edge()` — just expose it). In `_record_signal()`, assert `signal.edge.model_prob is not None` rather than reconstructing from net edge. Add a schema test that verifies `EdgeEstimate.model_prob` is set before any calibration call.

---

### BUG-07 — Consensus Outcome Resolution: `_get_outcome_from_kalshi` Falls Through to `None` on `"closed"` Status Without `"result"` Field

- **Name:** `settlement-result-field-ambiguity`
- **Location:** `merid/metrics/outcome_resolver.py` lines 256-268 (`_get_outcome_from_kalshi`)
- **Category:** Data-quality / Contract
- **Description:**  
  The outcome fetch logic checks `raw.get("result")` for `"yes"` or `"no"`. If the field is absent but `status == "closed"`, the function returns `None` (line 265-268 falls through). Kalshi markets can be in `"closed"` state before the result field is populated (they enter a settling state). However, the function also returns `None` for `status not in ("settled", "finalized", "closed")`, but then also returns `None` if status IS `"closed"` but result is absent — the logic on lines 264-268:
  ```python
  status = raw.get("status", "")
  if status not in ("settled", "finalized", "closed"):
      return None  # Not yet settled
  return None  # Falls through even when status is "settled"
  ```
  The final `return None` on line 268 executes regardless of status — meaning a market with `status="settled"` but an unrecognized `result` value (e.g., `"YES"` uppercase, or `"win"`) will never be resolved. The forecasts accumulate unresolved indefinitely, growing the SQLite `forecasts` table without bound and falsely showing 0 resolved Brier scores.
- **Impact:**  
  If Kalshi changes the settlement field casing or value, all outcomes silently go unresolved. Calibration weights never update from `DEFAULT_WEIGHT=1.0`. The system degrades to uncalibrated equal-weight consensus indefinitely.
- **Proposed fix:**  
  Normalize `settlement.lower()` before comparison. Log a `WARNING` when `status` is `"settled"` or `"finalized"` but `result` is not parseable. Add a maximum unresolved age threshold (e.g., 48h after `end_date`) after which the market is flagged for manual review.

---

### BUG-08 — `_build_snapshot` Injects `no-expiry` Markets as Always Tradeable

- **Name:** `no-expiry-always-allowed`
- **Location:** `merid/prediction/trading_agent.py` lines 619-628 (`_in_entry_window`), lines 641-644 (`tte_hours` computation in `_build_snapshot`)
- **Category:** Contract / Robustness
- **Description:**  
  `_in_entry_window()` returns `True` when `market.end_date is None` ("No expiry info — allow"). `_build_snapshot()` sets `tte_hours = None` for markets without an `end_date`. `KalshiStrategy._expiry_phase()` (line 146-147) then returns `ExpiryPhase.EARLY` for `hours_left is None`. This means a market with a missing or unparseable `end_date` is:  
  1. Always considered within entry window  
  2. Always assigned `ExpiryPhase.EARLY` (highest minimum edge threshold `0.05`, which is correct)  
  3. Never subject to the time-decay weaker momentum signal in `MomentumForecaster` (time decay factor is 1.0 when `minutes_to_expiry is None`)  
  4. Never flagged as stale or missing data  
  
  Importantly, `EventMarket.end_date` is populated from `datetime.fromisoformat(m["end_date"])` (trading_agent line 604) which will throw `ValueError` on bad formats — but this is inside a `try/except Exception` block that silently sets `end_date=None`.
- **Impact:**  
  A market with a missing or corrupted `end_date` field gets treated as an infinitely early, always-open market. If a fast-expiring contract has its timestamp malformed, the agent will under-price urgency, apply too-high an edge threshold, and hold positions past settlement without stop-loss triggers.
- **Proposed fix:**  
  Reject markets with `end_date is None` from the resolved market list entirely, or treat them as `ExpiryPhase.TERMINAL` (requiring the highest edge, tightest risk). Log a `WARNING` when `end_date` is absent. Never silently return `True` from `_in_entry_window` on missing data.

---

## 2. Medium-Risk Issues and Missing Invariants

- **`merid/prediction/forecasters/registry.py` lines 248-261 (`get_forecaster_registry`) — Missing lock (singleton race).**  
  The outer `if _registry is None:` check is not inside a lock. Two threads hitting simultaneously can each enter the `None` branch and register duplicate `MacroRegimeForecaster` / `OrderbookForecaster` instances. **Invariant:** `_registry` must be initialized exactly once; outer check must be inside `_registry_lock`.

- **`merid/swarm/consensus_aggregator.py` line 324 (`"mode": "paper"` hardcoded in event payload).**  
  The `kalshi:consensus_decision` event always carries `"mode": "paper"` regardless of `VenueGate` mode. Any downstream consumer routing on this field will always see paper mode. **Invariant:** mode field must reflect `VenueGate.mode` at publish time.

- **`merid/prediction/trading_agent.py` line 977 (`update_from_phase(_init_equity)`).**  
  On every `_execute_signal` call, `update_from_phase` is called with `_init_equity` — a variable only assigned inside the preceding `if self._btc15m_risk is None:` block, meaning it's always `0.0` after the first call. Passing `0.0` equity to the phase updater on every cycle may corrupt phase-cap state. **Invariant:** equity passed to `update_from_phase` must be the current account equity, fetched unconditionally.

- **`backtesting/engine.py` `_fetch_historical_data` — `asyncio.get_event_loop().create_task()` called from sync context in `_initialize_exchanges`.**  
  `data/live_price_feed.py` line 120 calls `asyncio.get_event_loop().create_task(self._close_exchanges())` from `_initialize_exchanges()` which is called from `__init__`. In Python 3.10+, `get_event_loop()` in a non-async context emits a `DeprecationWarning` and may return a closed loop. **Invariant:** `close_exchanges` must only be scheduled from an async context.

- **`merid/metrics/calibration.py` `check_same_thread=True` for in-memory DB only.**  
  The SQLite connection for the production DB uses `check_same_thread=False`. This is intentional for multi-thread access but SQLite in WAL mode is not safe for concurrent writes without external locking. The calibration store has no write mutex. **Invariant:** all writes to `CalibrationStore` must be serialized through a `threading.Lock()`.

- **`merid/prediction/model.py` `_active_snapshots` capped at 200 — but there is no lock.**  
  `build_snapshot()` appends to and slices `_active_snapshots` without a lock. **Invariant:** same fix as `_momentum_history` — protect with instance-level lock.

- **`merid/prediction/trading_agent.py` `_build_snapshot` line 636 — `yes_price = Decimal("50")` default.**  
  If neither `"yes"` nor `"no"` outcome IDs are found in `market.outcomes`, both sides default to 50 cents. The strategy then evaluates edge on a 50/50 market that may actually be at 90/10, silently producing a phantom edge signal. **Invariant:** snapshot must be rejected (not defaulted) if outcome prices are missing.

- **`core/consensus_engine.py` vote deduplication — missing.**  
  `ConsensusEngine.pending_votes` is a `Dict[str, Vote]` keyed by `agent_id`, so the last vote per agent wins. However the `SwarmConsensusAggregator` does its own deduplication (line 194-197). These two consensus systems are **parallel, not integrated** — a signal can be simultaneously evaluated by both with different results. There is no explicit hand-off. **Invariant:** only one consensus path should be authoritative for any given decision.

- **`merid/prediction/trading_agent.py` line 800 `tte` — minutes computed as `hours * 60.0` as `float`, passed where `Optional[float]` expected — no precision validation.**  
  If `time_to_expiry_hours` is a `Decimal`, multiplying by `60.0` produces a Python `float` via `Decimal.__float__()`. Downstream `MomentumForecaster` and `MeanReversionForecaster` use this directly in division. A `Decimal` with a very large exponent could produce `inf`. **Invariant:** `minutes_to_expiry` must be validated as finite and positive before use.

---

## 3. Recommended Invariants, Canary Tests, and Data Monitors

### Invariants (plain language)

1. **Price freshness:** No edge computation shall use a price older than 30 seconds. Any component reading `price_cache` must verify `now - cached.timestamp < MAX_PRICE_AGE_SECONDS` and raise/return None otherwise.
2. **Model-prob on edge estimate:** Every `EdgeEstimate` produced by `compute_edge()` must carry an explicit `model_prob` field set before the fee/slippage deduction. The calibration store must only accept this field — never a reconstructed one.
3. **Consensus authority:** Exactly one consensus path is authoritative per decision. `SwarmConsensusAggregator` (for Kalshi prediction markets) and `ConsensusEngine` (for crypto/swarm bus events) must not simultaneously evaluate the same signal. Add an `authority` field to each consensus output.
4. **No solo trades above `small` size band:** When `swarm_degraded=True` (no consensus after N seconds), all orders must use `size_band="small"` and emit a WARNING alert. Never silently proceed at full size.
5. **End-date required:** All `EventMarket` objects must have a valid, parseable `end_date` before entering the strategy loop. Missing end-date is a rejection reason, not a pass-through.
6. **Brier resolution completeness:** Any market with `status in ("settled","finalized")` must be resolved within 1 hour. Monitor `forecasts WHERE resolved=0 AND timestamp < now-86400` — alert if count > 0.
7. **Fee model consistency:** The fee model used in `compute_edge()` must match the fee model used in `BacktestEngine`. Assert they are the same function (`kalshi_fee_cents`) at startup.
8. **Momentum history isolation:** `_momentum_history` must never contain observations from more than one `market_id` per key. Assert `all(k == market_id for obs in _momentum_history[market_id])`.
9. **Consensus mode field accuracy:** The `mode` field in any published consensus event must equal `get_venue_gate().mode` at the time of publication.
10. **All agents see the same snapshot:** When forming consensus, agents must reference snapshots built at the same cycle timestamp (±1 cycle interval). Reject proposals older than 2× the cycle interval.

### Canary Tests

| Test | Trigger condition | Expected behavior |
|------|------------------|-------------------|
| `test_stale_price_rejected` | Inject a `PriceData` with `timestamp = now - 60s`, call `compute_edge()` | `EdgeEstimate` is `None` or exception raised |
| `test_no_end_date_market_rejected` | Pass `EventMarket(end_date=None)` to `_in_entry_window` | Returns `False`, not `True` |
| `test_solo_execution_uses_small_band` | Disable swarm bus, run agent for >3 cycles | All orders use `size_band="small"`, WARNING emitted |
| `test_calibration_weight_not_biased_by_fees` | Record forecast with `p_model=0.7`, `net_edge=0.05` (fee drag 0.02), resolve with outcome=1 | Brier computed against `0.7`, not `0.68` |
| `test_backtest_fee_matches_live` | Run backtest on same trade as live; compare fee charged | Delta < 0.001 |
| `test_settlement_result_normalized` | Return `{"result": "YES", "status": "settled"}` from mock Kalshi API | Outcome resolved as `1` (case-insensitive) |
| `test_momentum_history_isolation` | Create two agents (BTC, ETH), run 5 cycles each | `_momentum_history["BTC-market"]` contains no ETH observations |
| `test_consensus_mode_field` | Set `VenueGate.mode = "live"`, trigger consensus | Published event `mode == "live"` |

### Data Monitors / Alerts

| Monitor | Metric | Alert threshold |
|---------|--------|-----------------|
| Price age monitor | `max(now - price_cache[s].timestamp for s in symbols)` | > 30 s: WARNING, > 120 s: CRITICAL |
| Unresolved forecasts backlog | `SELECT COUNT(*) FROM forecasts WHERE resolved=0` | > 50 markets pending > 24 h: WARNING |
| Calibration weight distribution | `stddev(get_weight(f, b) for f in forecasters)` | If all weights = 1.0 after 7 days: WARNING (no outcomes resolving) |
| Solo-execution rate | `signals_consensus_blocked / signals_actionable` per agent per hour | > 80%: WARNING (swarm degraded) |
| Brier score outlier | `ewma_brier > 0.20` for any forecaster after 50+ resolved | WARNING — forecaster worse than coin flip |
| Momentum history size | `max(len(h) for h in _momentum_history.values())` | Should never exceed `_MAX_HISTORY = 20` — if it does, the cap is broken |
| Schema drift detector | Hash of `MarketSnapshot`, `EdgeEstimate`, `AgentProposal` field names on startup | Alert if hash differs from last known-good |
| Consensus dual-path | Count of markets where both `ConsensusEngine.pending_votes` and `SwarmConsensusAggregator._proposals` are active | Any non-zero: WARNING |

---

## 4. Design Risks in Intelligence Architecture

### A. Two Parallel Consensus Systems With No Integration Contract

`ConsensusEngine` (core/) and `SwarmConsensusAggregator` (merid/swarm/) are both active in production and both receive agent proposals, but they operate independently. `ConsensusEngine` processes `EventChannel.AGENT_OUTPUT` bus events; `SwarmConsensusAggregator` receives `AgentProposal` objects via `submit_proposal()`. Both feed into downstream decision paths. There is no explicit contract defining which is authoritative, no deduplication between them, and the `ConsensusEngine` trust scores and `SwarmConsensusAggregator` Brier weights can diverge independently. This will generate future bugs when architectural changes affect one path but not the other.

### B. Sentiment Data Is Enrichment-Only With No Fallback Quality Signal

Sentiment (`snapshot.sentiment_local`, `sentiment_category`, `sentiment_global`, `sentiment_regime`) is injected via a `try/except` block that swallows all failures. Strategy and risk logic that consumes these fields cannot distinguish "neutral sentiment" from "sentiment unavailable." The `KalshiStrategy.evaluate()` call receives a snapshot where `sentiment_global=None` and a snapshot where `sentiment_global=0.5` identically — there is no `sentiment_valid: bool` flag. Over time, prompts and strategies will be tuned assuming sentiment is always present, and the silent None will introduce subtle feature-engineering bugs.

### C. `ForecasterRegistry` Dynamically Imports 4 Additional Forecasters on First Access

`get_forecaster_registry()` (lines 248-261) imports and instantiates `MacroRegimeForecaster`, `OrderbookForecaster`, `TimeSeriesForecaster`, and `ExternalSentimentForecaster` that are not audited in this report. These forecasters operate with the same calibration bootstrap (`DEFAULT_WEIGHT=1.0`) and the same global `_momentum_history` risk. If any of these modules have their own global state or I/O dependencies (e.g., `ExternalSentimentForecaster` calling an external API), a slow or failing dependency will block the first `predict_all()` call on the hot path.

### D. CalibrationStore Singleton `db_path` Is Fixed at First Call

`get_calibration_store(db_path=None)` creates the singleton with the first `db_path` value passed; all subsequent calls ignore `db_path`. Tests that call `get_calibration_store(":memory:")` after a production call will silently share the production SQLite connection. The test suite must always call this before any production code initializes the singleton. This is fragile across test ordering.

### E. Quarter-Kelly Sizing Applied to Prediction-Market-Specific Constraints Without Probability Calibration Guard

`KalshiStrategy` applies `kelly_fraction = Decimal("0.25")` (quarter-Kelly). Kelly optimal sizing assumes `p_model` is the true probability. If `p_model` is systematically biased (see BUG-06 — fee deduction in reconstruction), quarter-Kelly over-sizes relative to true edge. There is no guard that requires `abs(p_model - implied_yes_prob) > calibration_confidence_band` before Kelly sizing is applied; the system will produce positive (small) Kelly sizes even when the edge estimate is within the noise of the calibration uncertainty.

---

*End of audit. Total high-risk bugs: 8. Medium-risk issues: 9. All findings reference concrete code locations.*
