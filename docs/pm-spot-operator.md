# PM crypto spot — operator guide

This document mirrors the section **Interpreting PM crypto spot warnings** in [`ENV_SETUP.md`](../ENV_SETUP.md) so runbooks and dashboards can link here without scrolling the env file.

## When you see “PM crypto spot missing or stale”

The system is enforcing **data-feed health** for prediction-market crypto pricing. It is usually an **operational** issue (Coinbase, network, or staleness settings), not a MERID code defect.

### Assets monitored

`ACTIVE_CRYPTO_ASSETS` in `config/kalshi_crypto_config.py` (typically **BTC, ETH, SOL, XRP, DOGE**). All use the same path: `PredictionMarketModel.get_spot_price` → `LivePriceFeed.get_current_price` tries **`ASSET/USD` first**, then `ASSET/USDT` (legacy mirror), with PM staleness vs `MERID_PM_MAX_SPOT_AGE_SECONDS`.

### Per-asset reasons (`pm_spot_unusable_reason`)

| Reason | Meaning |
|--------|--------|
| `no_price_feed` | No usable LivePriceFeed from the model’s perspective. |
| `no_quote_or_feed_ttl_expired` | No row, or row rejected by `CACHE_TTL_SECONDS` (`data/live_price_feed.py`). |
| `pm_max_age_exceeded` | Row exists for diagnostics but quote age exceeds `MERID_PM_MAX_SPOT_AGE_SECONDS`. |
| `no_asset` / `unknown` | Resolver or rare edge case; check Kalshi ticker → asset mapping. |

### Kalshi-only mode (`KALSHI_ONLY=true`)

CCXT is not initialized; **Coinbase Advanced HTTP** is the usual PM spot source. Expect `all_pm_assets_have_spot=false` and MM gating until Coinbase is healthy again.

### Market-maker hard gate (`pm_spot_hard_gate: true`)

For `market_maker` agents that opt in (e.g. **CRYPTO_15M_MM** in `config/kalshi_agent_grid.yaml`): missing/stale spot forces **QUOTE → NO_ACTION** with reason `pm_spot_gate:missing_or_stale_spot` and **`PM_SPOT_BLOCK`** logs. Disable process-wide with `MERID_CRYPTO_MM_PM_SPOT_HARD_GATE=0` only if you accept quoting without PM spot alignment.

### What to do

1. Use the **Operator Dashboard → PM Spot Health** table and/or `/api/v1/operator/risk-state`.
2. Fix upstream: credentials, network, Coinbase API errors, ensure ticker loops run.
3. If only **`pm_max_age_exceeded`**: tighten feeds or relax `MERID_PM_MAX_SPOT_AGE_SECONDS` deliberately.
4. When all monitored assets show `pm_spot_effective_ok=true`, warnings clear and MM quoting resumes automatically.
