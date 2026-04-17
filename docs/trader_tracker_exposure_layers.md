# Kalshi risk layers (CT, bankroll, category exposure)

Three **independent** mechanisms apply at different stages of the stack. They do not replace one another.

## 1. BankrollManager (order sizing)

- **Role:** How large each **new** order may be (Kelly, contract count, per-market limits).
- **Config:** `TraderConfig.max_total_exposure_pct` → env `KALSHI_TRADER_MAX_EXPOSURE` (default `0.20`).
- **Important:** This fraction drives **sizing only** inside `KalshiRiskEngine` / `BankrollManager`. It is **not** the Continuous Trader per-asset skip cap.

## 2. Continuous Trader skip gates (`KalshiContinuousTrader`)

- **Role:** Before submitting a buy, the CT loop applies:
  1. **Per-asset cap (cents):** `asset_max_exposure_pct[asset] × series_exposure_multiplier[timeframe] × balance`, floored by `min_asset_cap_cents`.
  2. **Global cap (cents):** `global_max_exposure_pct × balance` across all crypto positions.
- **Units:** All of the above are **integer cents** of bankroll / notional at risk. They are **not** converted to USD in the API layer for CT.
- **Env (per-asset fractions):**
  - `KALSHI_TRADER_EXPOSURE_BTC`, `_ETH`, `_SOL`, `_XRP`, `_DOGE`
  - `KALSHI_TRADER_EXPOSURE_DEFAULT`
  - `KALSHI_TRADER_GLOBAL_EXPOSURE`
  - `KALSHI_TRADER_MIN_ASSET_CAP_CENTS`
- **`series_exposure_multiplier`:** CT-only multipliers (`15m` / `1h` / `daily` / `weekly`) applied **on top of** each asset’s percentage. They are **dataclass defaults** in `TraderConfig` — **not** loaded from environment today. To change them, edit code or extend `from_env()` deliberately.

## 3. CategoryExposureTracker (multi-agent / order router)

- **Role:** Cross-agent **category** USD caps and **per-underlying correlated stack** USD caps when routing through the shared tracker (`check_and_reserve`, etc.).
- **Env:**
  - Category: `MERID_CAT_CAP_*_USD`
  - Default corr stack: `MERID_CORR_STACK_CAP_USD`
  - Per-asset corr overrides: `MERID_ASSET_CAP_BTC_USD`, `_ETH_USD`, `_SOL_USD`, `_XRP_USD`, `_DOGE_USD`
- **Does not gate CT directly:** The Continuous Trader loop does **not** call `CategoryExposureTracker`. Those caps apply to paths that use the tracker (e.g. order router / agents). Keep CT env vars and `MERID_ASSET_CAP_*` mentally separate.

---

## New Kalshi series or assets (avoid hidden “UNK” exposure)

When Kalshi adds a **new crypto series ticker** not in `config.kalshi_crypto_series_meta`:

1. Add metadata (or extend heuristics in `KalshiContinuousTrader._infer_asset_timeframe`).
2. If the CT should treat it as a named bucket, add `KALSHI_TRADER_EXPOSURE_*` or rely on `KALSHI_TRADER_EXPOSURE_DEFAULT` for unknown symbols.
3. For multi-agent corr caps, extend `MERID_ASSET_CAP_*` or rely on `MERID_CORR_STACK_CAP_USD`.

If inference yields **`UNK`**, CT logs a **warning** and uses **`asset_exposure_default_pct`** for the per-asset skip gate; the **global** cent cap still applies.

---

## Quick reference

| Concern | Where | Units | Primary env |
|--------|--------|-------|-------------|
| Order size / Kelly exposure | BankrollManager | contracts / cents sizing | `KALSHI_TRADER_MAX_EXPOSURE` |
| CT per-asset + global skip | `kalshi_continuous_trader` | **cents** | `KALSHI_TRADER_EXPOSURE_*`, `KALSHI_TRADER_GLOBAL_EXPOSURE` |
| Router / swarm corr stack | `category_exposure` | **USD** | `MERID_CORR_STACK_CAP_USD`, `MERID_ASSET_CAP_*_USD` |
