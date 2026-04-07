# Aggressively Conservative 15m Kalshi Crypto Strategy

**Profile name:** `kalshi_crypto_15m_conservative`  
**Assets:** BTC, ETH, SOL, XRP, DOGE  
**Primary timeframe:** 15 minutes  
**Context timeframes:** 1m, 5m, 15m, 1h, 4h  
**Target trade rate:** 10–15 approved trades/hour across all assets combined  
**Config file:** `config/strategies/kalshi_crypto_15m_conservative.yaml`

---

## What it does

The `kalshi_crypto_15m_conservative` profile is an _aggressively conservative_ 15-minute Kalshi prediction-market strategy.  It targets the "up/down 15m" contracts for the five supported crypto assets and only enters trades when all of the following conditions are simultaneously true:

1. **High model conviction** — the model's forecast probability for the signal direction must exceed a per-asset threshold (default 0.64 for BTC/ETH, 0.66 for SOL/XRP/DOGE).
2. **HTF/MTF structure alignment** — the multi-timeframe alignment score (`multi_tf_alignment`) must confirm the direction and must not contradict it.
3. **Positive net edge after fees** — edge in basis points must clear the `min_edge_bps` floor.
4. **Liquidity sanity** — the specific Kalshi 15m contract must have sufficient volume, open interest, and a narrow bid-ask spread.
5. **Global rate budget remaining** — the rolling 60-minute approval count across all five assets must be below the hard cap.
6. **Per-asset budget remaining** — no more than `per_asset_max_per_15m` trades per asset in any 15-minute window.

---

## Architecture integration

The strategy is implemented as `Conservative15mStrategy` in  
`merid/strategies/kalshi_crypto_15m_conservative.py`.

It is registered as the **first** entry in the `_STRATEGIES_BY_TIMEFRAME["15m"]` list inside `merid/event_venues/kalshi/strategy_grid.py`.  When the `KalshiTradingAgent` for any 15m cell calls `grid.first_estimate(asset, "15m", ...)`, the conservative strategy is evaluated first; if it returns `None` (all gates failed), the fallback `SpotMomentumStrategy` and `MeanRevertSpikeStrategy` are tried in order.

A companion batch-gate module  
`merid/trading/gates/kalshi_15m_conservative_gates.py`  
exposes `apply_15m_conservative_gates()` for use in pipeline tests and future batch workflows.

### Shared singletons

| Singleton | Class | Purpose |
|-----------|-------|---------|
| `get_rate_tracker()` | `GlobalRateTracker` | Rolling 60-min trade counter shared across all 5 asset agents |
| `get_drawdown_state()` | `DrawdownState` | Strategy-level drawdown tracking |
| `get_conservative_config()` | `Conservative15mConfig` | Loaded from YAML, cached in memory |

---

## Signal derivation

Edge is derived from three components (all from the `context` dict):

| Component | Context key | Weight |
|-----------|-------------|--------|
| Spot momentum | `spot_return_pct` | 45% |
| Orderbook imbalance | `orderbook_imbalance` | 25% |
| HTF/MTF alignment | `multi_tf_alignment` | 30% |

The combined raw edge is clamped to ±9%.  `agent_prob = clamp(market_prob + edge, 0.01, 0.99)`.

For the signal direction (YES or NO), the strategy computes the directional probability:
- YES: `directional_p = agent_prob`
- NO: `directional_p = 1 − agent_prob`

This must exceed `effective_min_p` (see below) for the signal to be approved.

---

## Thresholds and how they work

### Base probability threshold

| Asset tier | Default `min_p` |
|------------|-----------------|
| Core (BTC, ETH) | 0.64 |
| Satellite (SOL, XRP, DOGE) | 0.66 |

### Dynamic tightening

The effective threshold at any moment is:

```
effective_min_p = base_min_p + rate_increment + drawdown_increment
```

Where:
- **`rate_increment`** — `max(0, trades_over_soft_target) × rate_tighten_delta`.  Added when the 60-minute approval count exceeds `soft_target_trades_per_hour` (default 12).
- **`drawdown_increment`** — `drawdown_min_p_delta` (default 0.02) when strategy drawdown ≥ `drawdown_warning_pct` (default 3%).

### Rate limits

| Parameter | Default | Meaning |
|-----------|---------|---------|
| `soft_target_trades_per_hour` | 12 | Threshold above which `min_p` is raised dynamically |
| `global_max_trades_per_hour` | 30 | Hard cap — no new approvals above this |
| `per_asset_max_per_15m` | 2 | Max approved trades per asset per 15-minute window |

---

## Drawdown protection

| Threshold | Default | Effect |
|-----------|---------|--------|
| `drawdown_warning_pct` | 3% | Raises `min_p` by `drawdown_min_p_delta`; scales Kelly by `drawdown_kelly_scale` |
| `drawdown_pause_pct` | 6% | Pauses all new approvals until drawdown recovers |

---

## Position sizing

The strategy emits a `confidence` value in the `OpinionEstimate` that is proportional to:

```
kelly_scale = config.kelly_fraction          # default 0.125 (1/4 of standard 0.50)
confidence  = clamp(0.40 + |edge| × 4.0, 0.30, 0.90) × kelly_scale / 0.25
```

The `KalshiStrategy` and `PredictionMarketRisk` in the trading agent translate `confidence` into a final contract count, subject to per-agent notional caps from `config/kalshi_agent_grid.yaml`.

---

## How to enable / disable

### Enable (default on server start)

The profile is loaded automatically because `Conservative15mStrategy` is
prepended to the 15m strategy list at import time.  The `strategy_catalog.yaml`
also lists it under `trading.strategies.enabled_profiles`.

No code change is needed to keep it running.

### Kill switch (disable without code change)

Edit `config/strategies/kalshi_crypto_15m_conservative.yaml`:

```yaml
enabled: false
```

Then restart the server (or call `reload_conservative_config()` programmatically).

### Tune thresholds

All numeric parameters in `config/strategies/kalshi_crypto_15m_conservative.yaml`
can be edited and reloaded at runtime:

```python
from merid.strategies.kalshi_crypto_15m_conservative import reload_conservative_config
reload_conservative_config()   # re-reads YAML; takes effect on next strategy evaluation
```

---

## Monitoring

The strategy writes structured `DEBUG` log entries for every approved or
rejected signal under the logger `merid.strategies.kalshi_crypto_15m_conservative`.  Key log patterns:

| Pattern | Meaning |
|---------|---------|
| `[CONS15M] … skip=hard_cap` | Global cap reached; signal not evaluated |
| `[CONS15M] … skip=per_asset_15m_cap` | Asset quota for this 15m window reached |
| `[CONS15M] … skip=low_p` | Directional probability below effective threshold |
| `[CONS15M] … skip=htf_veto` | HTF structure contradicts the signal direction |
| `[CONS15M] … skip=htf_insufficient` | Alignment magnitude too weak |
| `[CONS15M] … skip=drawdown_pause` | Drawdown above pause threshold |
| `[GATE] APPROVED …` | Signal passed all gate-module checks |
| `[GATE] Rejected …` | Batch rejection summary (from gate module) |

The approved estimates also include a rich `OpinionExplanation` with:
- Current `effective_min_p`, `rate_increment`, `drawdown_increment`
- `trades_last_hour` and `drawdown_pct` at decision time
- Raw and attenuated edge contributions

---

## Tests

| Test file | What it covers |
|-----------|----------------|
| `tests/strategies/test_kalshi_15m_conservative.py` | Strategy unit tests: config, rate tracker, drawdown state, approve/reject paths, strategy grid integration |
| `tests/trading/gates/test_kalshi_15m_conservative_gates.py` | Gate module unit tests: kill switch, all gate types, priority ordering, synthetic batch integration |

Run:

```bash
pytest tests/strategies/test_kalshi_15m_conservative.py \
       tests/trading/gates/test_kalshi_15m_conservative_gates.py -v
```
