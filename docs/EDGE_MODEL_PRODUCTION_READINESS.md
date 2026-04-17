# Kalshi crypto edge model — production readiness

The crypto edge stack is **production ready** when wired through `merid.settings` and the live paths below. There is **no** time-based phased rollout in code: behavior is controlled only by Settings / environment variables and explicit trading-mode interlocks (`MERID_PM_LIVE_ENABLED`, execution gate, kill switches).

## Conservative baseline (legacy-equivalent swarm + strict floors)

Use on-disk defaults (or set explicitly):

| Knob | Value |
|------|--------|
| `MERID_CRYPTO_EDGE_FLOOR_PROFILE` | `strict` |
| `MERID_CRYPTO_MM_CONSENSUS_MODE` | `full` |
| `MERID_CRYPTO_SHADOW_EDGE_YES` / `_NO` | `0.00` |
| `MERID_CRYPTO_CONSENSUS_WAIT_TIMEOUT_MS` | `500` |
| `MERID_CRYPTO_EDGE_PRODUCTION_PROFILE` | *(empty)* |

**Effect:** tiered min-edge uses full grid multipliers (`strict` = 1.0). **FORMING** swarm consensus **holds** signals in the agent loop and returns **no execution** from `_check_consensus_gate`. Shadow edge fields only emit `SHADOW_EDGE_OBS` when non-zero and `MERID_CONSENSUS_PATH_LOG=true`.

## Full production tuning (single switch)

Set **one** environment variable:

```bash
MERID_CRYPTO_EDGE_PRODUCTION_PROFILE=modern
```

**Effect (session-wide):** `medium` floor profile (~0.92× tiered thresholds), `soft` MM consensus mode (brief wait + re-read; **FORMING** may proceed **small-sized**), shadow edges raised to at least **0.02**, and profile key **`modern`** vs **`legacy`** inside `config/crypto_threshold_matrix.yaml`.

To tune **without** the profile, set individuals explicitly, e.g. `MERID_CRYPTO_MM_CONSENSUS_MODE=soft`, `MERID_CRYPTO_EDGE_FLOOR_PROFILE=medium`, and non-zero shadow edges.

### Crypto threshold matrix (single source)

All tunable crypto PM/MM edges, spreads, contrarian floors, optional Kelly / min-notional / vol-size multipliers, and spot-strike veto flags live in **`config/crypto_threshold_matrix.yaml`**. Override the path with **`MERID_CRYPTO_THRESHOLD_MATRIX_PATH`**.

- **YAML wins** over AgentGrid `kalshi_agent_grid.yaml` `strategy:` `min_edge_early|mid|late|terminal` for crypto agents — the loader applies **one scalar** min edge to all phases; an INFO log `[CRYPTO_MATRIX] … overrides grid YAML` fires when YAML had different phase values.
- **Effective view:** `GET /api/v1/config/crypto-matrix` (authenticated) or `python scripts/print_crypto_agent_effective_config.py`.
- **Runtime helper:** `merid.prediction.crypto_threshold_matrix.get_effective_crypto_config(agent_name, market_id)` (and `get_min_order_notional_for_intent` for the order router).

Code bridges: `get_crypto_thresholds`, `integrate_crypto_tiered_min_edge`, `crypto_tier_min_edge_floor`, `effective_crypto_pm_max_spread_cents`, `apply_crypto_strategy_thresholds_to_config` in `merid/prediction/crypto_edge_production.py` all resolve from this file.

### Asset × timeframe threshold grid (5 assets mirror each row)

By default, YAML uses `asset: "*"` wildcards so BTC, ETH, SOL, XRP, and DOGE share the same row for a given timeframe; add asset-specific rows to diverge. `get_crypto_thresholds(asset, timeframe)` resolves the merged row (archetype `directional` for CT-style hooks).

| Timeframe | Mode | Directional min edge | Vol / regime min edge | Contrarian sentiment min | MM + PM risk max spread (¢) | Tier min-edge floor* |
|-----------|------|----------------------|------------------------|---------------------------|-------------------------------|----------------------|
| 15m | legacy | 0.04 | 0.04 | 75 | 10 | 0.08 |
| 1h | legacy | 0.04 | 0.04 | 75 | 10 | 0.08 |
| daily | legacy | 0.035 | 0.035 | 75 | 10 | 0.08 |
| weekly | legacy | 0.03 | 0.03 | 75 | 10 | 0.08 |
| monthly | legacy | 0.03 | 0.03 | 75 | 10 | 0.08 |
| annual | legacy | 0.03 | 0.03 | 75 | 10 | 0.08 |
| 15m | modern | 0.01 | 0.01 | 58 | **40** | 0.005 |
| 1h | modern | 0.0125 | 0.0125 | 58 | **40** | 0.005 |
| daily | modern | 0.015 | 0.015 | 58 | **40** | 0.005 |
| weekly | modern | 0.02 | 0.02 | 58 | **40** | 0.005 |
| monthly | modern | 0.02 | 0.02 | 58 | **40** | 0.005 |
| annual | modern | 0.02 | 0.02 | 58 | **40** | 0.005 |

\* **Tier floor** blends with `get_tiered_min_edge()` / `tiered_min_edge_multiplier()` for Kalshi crypto inventory paths (see `market_filter.py`). **Annual** (`KX*Y` series) uses the same row as **monthly** for directional / spread caps. Agent grid labels `HOURLY` / `ANNUAL` normalize to `1h` / `annual` in `normalize_crypto_timeframe()`.

### PM pre-trade spread: log vs reality (important)

`ImpliedProbability.yes_bid` / `yes_ask` are already **Kalshi cents** (see `PredictionMarketModel.implied_probabilities`). In `KalshiTradingAgent` pre-trade `check_order`, bid/ask for the spread check must **not** be multiplied by 100 again. A bug that scaled them twice reported **~100¢** spreads for **~1¢** wide books and blocked MM under a **10¢** cap even when the modern profile was on. After the fix, the `Spread … exceeds max …¢` line matches the true book and the effective cap from `effective_crypto_pm_max_spread_cents` (10¢ legacy, 40¢ modern when `MERID_CRYPTO_EDGE_PRODUCTION_PROFILE=modern`).

**If you still see 10¢ in the message:** the process is almost certainly on the **legacy** threshold mode (profile env var not set in that shell/service). Confirm with `[PM_CONFIG_SUMMARY]` / `crypto_threshold_mode` in logs or `print_validation_hints()`.

## Crypto vol bands (PM + continuous trader)

**Computed:** `merid/signals/crypto_15m_indicators.py` — `Crypto15mIndicatorStack.snapshot()` sets `realized_vol_annualized`, `vol_band` (`low` / `mid` / `high`), and `vol_gate_ok` from 1m bar windows and `IndicatorConfig.vol_low_threshold` / `vol_high_threshold`.

**Continuous trader:** `merid/trading/kalshi_continuous_trader.py` owns per-asset stacks for bias / `[CT-TRACE]` (`vol_band=...`).

**AgentGrid / PM (this repo):** `merid/signals/crypto_pm_vol_bridge.py` maintains **separate** stacks fed from `KalshiTradingAgent._build_snapshot` spot (one synthetic bar per asset per wall-clock minute). `MarketSnapshot` gets `crypto_vol_band`, `crypto_vol_size_mult`, etc. `KalshiStrategy` multiplies that factor into Kelly paths (directional via `_kelly_size_with_sentiment`, contrarian / regime / vol-breakout, and MM quote depth).

**Matrix vs stack thresholds:** `Crypto15mIndicatorStack` still uses `IndicatorConfig` (defaults + `MERID_CRYPTO_VOL_*` settings) internally. The PM bridge then **reclassifies** `vol_band` / `vol_gate_ok` from realized vol using `vol_low_threshold` / `vol_high_threshold` on the resolved crypto matrix row when those fields are non-null; otherwise it uses the stack’s config. `vol_size_mult_*` on the same row continue to scale sizing per band.

**Config:** `MERID_CRYPTO_PM_VOL_BRIDGE_ENABLED`, `MERID_CRYPTO_VOL_BANDS_LOG`, optional `MERID_CRYPTO_VOL_LOW_THRESHOLD` / `MERID_CRYPTO_VOL_HIGH_THRESHOLD`, and `MERID_CRYPTO_VOL_BAND_*_SIZE_MULT` (defaults low=0.7, mid=1.0, high=0.4).

**Logs:** `[PM_SIZE] ... vol_band=... vol_size_mult=...` and, if enabled, JSON lines with `"event":"CRYPTO_VOL_BANDS"`.

## Spot vs strike (`dist_pct`) on PM logs

``MarketSnapshot.distance_to_strike_pct`` is stored as a **fraction** \((\text{spot}-\text{strike})/\text{strike}\), consistent with ``spot_strike_context.distance_to_strike_pct``.

- **``[PM_SIGNAL]``** (when ``MERID_PM_SIGNAL_INCLUDE_SPOT_STRIKE`` is on): includes ``dist_frac``, ``dist_pct_pct`` (fraction × 100), and ``spot_strike_basis`` — use **basis** to see ``missing_spot``, ``missing_strike``, ``missing_asset_for_spot``, etc., instead of a silent blank.
- **``[PM_SIZE]``** includes ``spot``, ``strike``, ``dist_pct_pct``, ``spot_strike_basis``.
- If **spot** is None, check DEBUG for ``[model] get_spot_price`` (no feed, no quote, stale quote); ensure ``data.live_price_feed`` is running at PM cadence.

## Event-loop lag and slow actions (where to look)

Symptoms like `Slow action 'arb_scan'`, `'features'`, `'consensus'`, `'liquidity'`, `'order_groups'` or `Event-loop lag … halt band` mean work is stalling the asyncio loop.

| Area | Code | Notes |
|------|------|--------|
| Arb scan | `merid/loop.py` — `_run_arb_scan` | Heavy CPU paths are wrapped with `run_in_executor`; if durations stay &gt;1–3s, profile `scanner.scan` / `validate_plans` internally (sync HTTP, fat loops). |
| PM agent grid | `merid/prediction/agent_grid.py` | Prior fixes batch REST/WS work to avoid serial API storms; search for comments on event-loop lag. |
| Lag probe | `merid/diagnostics/loop_lag.py`, `merid/event_venues/kalshi/ws.py` | Correlates `loop_lag` with health / gate LIMITED. |
| External APIs | CoinGecko, news, etc. | Must not run synchronous network I/O on the main loop; prefer executor + timeouts or dedicated async client. |

Use health JSON (`event_loop_lag`) and grep for slow-action lines in the same time window as missed quotes; spike lag often aligns with stale snapshots or consensus timeout.

**Note on edge sign:** Min-edge bars require a **positive** net edge vs threshold. Lowering thresholds helps when edge is small-but-positive; a sustained **negative** net edge (e.g. −0.03) still fails until the model or directional path produces positive edge.

## Consensus → execution observability

Enable structured INFO lines (guarded — default **off**):

```bash
MERID_CONSENSUS_PATH_LOG=true
```

| Event | When |
|--------|------|
| `APPROVED_SIGNAL_CREATED` | Actionable PM signal after `_submit_to_consensus` (asset, timeframe, edge, feature hash) |
| `CONSENSUS_UPDATE` | Each swarm recomputation (`SwarmConsensusAggregator`) |
| `CONSENSUS_DEFAULT_LEAK` | READY consensus at neutral 0.5 with live votes |
| `CONSENSUS_READ` | Throttled read of `(asset:timeframe)` consensus (≤1/min/key) |
| `CONSENSUS_CONSUMED_FOR_TRADING` | PM agent after alignment / soft-FORMING path |
| `EXECUTION_DECISION` | After PM `route_order_async` / Kalshi CT HTTP result |

**NoTradeDecisionTracker** (`merid.prediction.crypto_edge_production`): records `NO_ACTION` buckets at **DEBUG** only — **does not block** trading.

## Health / silent-block checks (default ON)

| Setting | Default | Purpose |
|---------|---------|---------|
| `MERID_CRYPTO_CONSENSUS_HEALTH_LOG` | `true` | `[CONSENSUS_HEALTH]` warnings |
| `MERID_CRYPTO_CONSENSUS_STALE_AFTER_SIGNAL_SECONDS` | `120` | Signals without fresh consensus refresh |
| `MERID_CRYPTO_CONSENSUS_NEUTRAL_LEAK_MIN_SIGNALS` | `5` | Rolling-window neutral leak heuristic |
| `MERID_CRYPTO_CONSENSUS_NEUTRAL_LEAK_WINDOW_MINUTES` | `15` | Window for leak heuristic |
| `MERID_CRYPTO_EXECUTION_INVARIANT_LOG` | `true` | CT: tradeable > 0, orders = 0, gate `safe_to_trade` |

CT invariant may also raise a Telegram **risk_warning** when `get_alert_manager()` is available.

## Production code paths (Kalshi crypto)

1. **Tiered edge floor:** `get_tiered_min_edge()` in `merid/event_venues/kalshi/market_filter.py` applies `tiered_min_edge_multiplier()` from `crypto_edge_production` (used by **KalshiContinuousTrader** candidate analysis and related PM/CT paths that call `get_tiered_min_edge`).
2. **PM AgentGrid / `KalshiTradingAgent`:** `_run_cycle_body` → strategy → `_submit_to_consensus` / `_submit_consensus_proposal` → swarm gate (`full` / `soft` / `bypass` via `MERID_CRYPTO_MM_CONSENSUS_MODE` + profile) → `_execute_signal` → `_check_consensus_gate` → `route_order_async` / Kalshi tools.
3. **KalshiContinuousTrader:** Edge vs `max(tiered_min_edge, bankroll floor)` → optional TaCo consensus blend → bankroll caps → `EXECUTION_DECISION` on HTTP result → cycle invariant.

## Execution gate: LIMITED vs BLOCKED (crypto modern)

In `core/execution_gate.py`, **LIMITED** keeps **`blocked=false`** (warning-only state). For Kalshi **crypto** routes with the modern profile, `MERID_CRYPTO_MODERN_LIMITED_OVERRIDES_SAFE_TO_TRADE` (default **`true`** in `merid.settings`) lets **KalshiContinuousTrader** treat **LIMITED** like safe-to-trade for **new entries** when the only concern is advisory (e.g. `loop_lag`). **BLOCKED** still stops orders.

**PM / order router:** rejections tied to the execution gate log `execution_gate_sources` on `EXECUTION_DECISION`; when `loop_lag` contributes, look for a `execution_gate_loop_lag` prefix in the rejection path (`merid/event_venues/kalshi/order_router.py`).

## One-session verification checklist

1. Set `MERID_CRYPTO_EDGE_PRODUCTION_PROFILE=modern` and `MERID_CONSENSUS_PATH_LOG=true`.
2. Print the live matrix and grep hints:
   ```bash
   py -3 -c "from merid.prediction.crypto_session_validation import print_validation_hints; print_validation_hints()"
   ```
   Or dump JSON only: `threshold_matrix_snapshot()` in `merid/prediction/crypto_session_validation.py`.
3. Start live or paper with valid Kalshi credentials. For **LIMITED**, confirm crypto continues when override is on (see above); for **BLOCKED**, expect no submissions.
4. **PM:** over 15–30 minutes, for **each** of BTC/ETH/SOL/XRP/DOGE, grep for at least one timeframe with `[PM_SIGNAL]` / `action=enter` (or equivalent actionable) **without** steady `sentiment_below_contrarian_floor` or `edge_below_threshold` on every cycle for that agent.
5. **CRYPTO MM:** grep for `[KALSHI_ORDER_INTENT]` and `EXECUTION_DECISION` with `actual_order_submitted=true` while gate is **CLEAR** or **LIMITED** (warn-only). If blocked by spread, you should **not** see `Spread … exceeds max 10¢` on modern KX crypto—modern uses the **40¢** cap from the table above.
6. **CT:** grep `[KALSHI_ORDER_INTENT]`, `EXECUTION_DECISION`, and absence of `[EXECUTION_INVARIANT]` unless caps intentionally block.
7. Confirm `NoTradeDecisionTracker` output appears only at DEBUG and does not correlate with unexplained halts.
8. Any hold should show an explicit reason (`consensus_gate_skip`, execution gate, risk skip, `Skip ...` in CT).

## Note on `EDGE_MODEL_TESTING_SUMMARY.md`

If that document exists in your branch, add a cross-link to this file under “Production knobs.” It is not required for runtime behavior.
