# MERID — Environment Configuration

## Quick Setup

```bash
cp .env.example .env        # copy template
make serve                  # start API server
```

MERID runs in paper mode with zero configuration. Add Kalshi credentials below for live market data.

---

## Kalshi Credentials

```bash
KALSHI_API_KEY_ID=your_key_id
KALSHI_PRIVATE_KEY_PATH=path/to/private_key.pem
KALSHI_USE_DEMO=true                  # true = demo environment, false = production
```

Get credentials at [https://kalshi.com/](https://kalshi.com/) → Account → API Keys.

---

## Trading Mode (prediction markets / Kalshi)

**Production (real orders on Kalshi)** — set on the server (`.env` is gitignored):

```bash
KALSHI_ENV=live
MERID_PM_TRADING_MODE=live
MERID_PM_LIVE_ENABLED=true
MERID_ALLOW_LIVE_TRADES=true
```

`MERID_ALLOW_LIVE_TRADES` is required: `VenueGate` downgrades to paper if prediction mode is `live` but this flag is not set.

At startup, each AgentGrid agent is still registered with `DeploymentController` in **PAPER**; execution routing for PM trades follows `VenueGate` + `MERID_PM_*` and the Kalshi adapter mode (live when `MERID_PM_LIVE_ENABLED=true`). Promotions logged in `[deploy]` come from the deployment controller when you promote agents explicitly.

### Production profile (AgentGrid belt)

```bash
MERID_PM_PROFILE=production
MERID_KALSHI_WS_CLIENT=ws
MERID_ENABLE_KALSHI_CT=false
```

With `MERID_PM_PROFILE=production` and `MERID_PM_TRADING_MODE=live`, startup runs stricter checks (including blocking `MERID_ENABLE_KALSHI_CT=true`). KalshiContinuousTrader is **off by default**; only AgentGrid (+ optional explicit CT) runs when enabled.

Before a live run: `python scripts/check_live_readiness.py` (wraps `go_live_preflight` and prints stack flags).

During a live run (cycles, vetoes, risk/gate): `python scripts/monitor_agentgrid_runtime.py` — polls `/api/v1/operator/ticks`, `/ticks/events`, Kalshi risk, operator risk-state, and execution-gate (set `MERID_MONITOR_SESSION_ID` or `--session` when auth is required).

**Local / demo** defaults:

```bash
KALSHI_ENV=demo
MERID_PM_TRADING_MODE=paper
MERID_PM_LIVE_ENABLED=false
MERID_ALLOW_LIVE_TRADES=false
```

| Mode | Behavior |
|------|----------|
| `mock` / legacy `sim` | Simulated fills, no API calls |
| `paper` | Real market data from Kalshi, simulated execution (unless other gates say live) |
| `live` | Real orders on Kalshi (`MERID_PM_LIVE_ENABLED=true` and `MERID_ALLOW_LIVE_TRADES=true`) |

---

## Crypto edge / threshold matrix (CRYPTO_15M_MM and PM crypto agents)

`MERID_CRYPTO_EDGE_PRODUCTION_PROFILE` selects **legacy** vs **modern** rows in `config/crypto_threshold_matrix.yaml` (min-notional floors, min edges, etc.). The **default in `merid.settings` is `modern`**, which also switches related behavior in `get_crypto_edge_runtime()` (medium edge-floor profile, soft MM consensus, non-zero shadow-edge hints) — **not** only min-notional. Set to empty or an unrecognized value for **legacy** matrix rows and stricter defaults.

- **Pre-trade** `check_order` for **QUOTE** signals uses the **bid** price for sizing checks in the agent loop. **CryptoSwarmRisk** uses **quote mid** (integer cents) × contracts for `intent_risk_usd`. **Order router sanity** uses each **leg’s** limit price (bid vs ask) × count. Expect different dollar amounts across these stages; all are intentional.

- If you see `[CRYPTO_MIN_NOTION_MATRIX]` in logs, `agent_id` did not resolve a matrix row — fix grid agent naming or YAML; the system falls back to the global sanity default min-notional until resolved.

- **Hourly ERROR_THRESHOLD kill** (`RiskController.record_error`, default 10/hour): only **incident-grade** order failures increment this counter (venue/routing exceptions, sanity-checker internal errors, etc.). Expected policy rejects (`sanity_check:`, `risk_check:`, caps, `live_not_enabled`, …) are **excluded** — see `merid.prediction.order_error_threshold.should_count_toward_error_threshold`. Set `MERID_ERROR_THRESHOLD_KILL_ENABLED=false` to log threshold warnings without halting trading while tuning.

### PM spot vs LivePriceFeed cache (Kalshi crypto PM / CRYPTO_15M_MM)

- **`MERID_PM_MAX_SPOT_AGE_SECONDS`** — used by `PredictionMarketModel.get_spot_price`: after `LivePriceFeed.get_current_price` returns a row, the quote **timestamp** must be within this age or spot is rejected (PM “effective” spot is unusable).
- **`CACHE_TTL_SECONDS`** (300s default in `data/live_price_feed.py`) — `get_current_price` returns **None** if the cache row is older than this, **before** PM age is checked.
- **Order of strictness:** Typically `get_current_price` applies TTL first; then PM max age can still reject a row that passed TTL if you set **`MERID_PM_MAX_SPOT_AGE_SECONDS` lower than the cache TTL** — operator UI exposes `pm_spot_unusable_reason` (`pm_max_age_exceeded` vs `no_quote_or_feed_ttl_expired`) and per-asset `live_price_feed.feed_ttl_expired` so dashboards are not ambiguous.
- **Market-maker hard gate** — YAML `pm_spot_hard_gate: true` on `archetype: market_maker` agents (e.g. `CRYPTO_15M_MM`) blocks **QUOTE** when snapshot PM spot is missing/stale; global override `MERID_CRYPTO_MM_PM_SPOT_HARD_GATE=0` disables the gate process-wide.

### KALSHI_ONLY mode and Coinbase (runbook)

When **`KALSHI_ONLY=true`**, `LivePriceFeed` **does not initialize CCXT exchanges** (`merid.settings` — see `data/live_price_feed._initialize_exchanges`). **Coinbase Advanced Trade HTTP** polling remains the primary path for filling `price_cache`. If Coinbase is unavailable or credentials are wrong:

- `get_spot_price` returns `None` → `pm_spot_effective_ok=false`, `all_pm_assets_have_spot=false`, operator dashboard and Kill Switch show **limited** PM spot state.
- Logs: `[PM_SPOT]`, `[model] get_spot_price`, `PM_SPOT_BLOCK` for opted-in MM agents; MM agents emit **NO_ACTION** instead of QUOTE (`pm_spot_gate:missing_or_stale_spot`).
- **Mitigation:** restore Coinbase connectivity or credentials; do not assume CCXT will backfill spot in Kalshi-only mode unless you change settings / init path.

### Interpreting PM crypto spot warnings

These messages mean the stack is enforcing **feed health**, not that MERID logic is “broken.” Use the **PM Spot Health (Coinbase / LivePriceFeed)** panel on the Operator Dashboard and `/api/v1/operator/risk-state` (`crypto_pm_feed`) for detail.

- **Assets monitored:** `ACTIVE_CRYPTO_ASSETS` from `config/kalshi_crypto_config.py` (typically **BTC, ETH, SOL, XRP, DOGE**). All of them use the same PM spot path: `PredictionMarketModel.get_spot_price` and `LivePriceFeed`.

- **What “PM crypto spot missing or stale” means:**
  - `get_spot_price` returned `None` for one or more monitored assets, so `pm_spot_effective_ok=false` for those rows.
  - Per-asset reasons are exposed as `pm_spot_unusable_reason`:
    - **`no_price_feed`** — model has no usable `LivePriceFeed` row (feeds not wired or not running).
    - **`no_quote_or_feed_ttl_expired`** — `LivePriceFeed.get_current_price` returned `None` (empty cache or row older than `CACHE_TTL_SECONDS` in `data/live_price_feed.py`).
    - **`pm_max_age_exceeded`** — a cache row exists for diagnostics, but the quote timestamp is older than **`MERID_PM_MAX_SPOT_AGE_SECONDS`** (the PM staleness limit applied after TTL).
    - **`no_asset`** / **`unknown`** — resolver/config edge case or unexpected path; investigate ticker ↔ asset mapping if persistent.

- **Kalshi-only mode:**
  - In **`KALSHI_ONLY`**, CCXT exchanges are **not** initialized; PM crypto spot depends on **Coinbase Advanced HTTP** via `LivePriceFeed` polling.
  - If Coinbase is unhealthy, expect:
    - `all_pm_assets_have_spot=false`,
    - `pm_spot_effective_ok=false` and a concrete `pm_spot_unusable_reason` per asset,
    - **CRYPTO_15M_MM** (and any `market_maker` with `pm_spot_hard_gate: true`) to **block QUOTE** for affected markets until spot recovers.

- **How CRYPTO_15M_MM reacts (`pm_spot_hard_gate`):**
  - For agents with **`pm_spot_hard_gate: true`** and **`archetype: market_maker`**, missing/stale PM spot (`snapshot.spot_price_usd is None`) triggers a **hard gate**:
    - `QUOTE` → `NO_ACTION`, `contracts=0`, reason `pm_spot_gate:missing_or_stale_spot`.
    - **`PM_SPOT_BLOCK`** at WARN (throttled) with agent and asset; global disable: `MERID_CRYPTO_MM_PM_SPOT_HARD_GATE=0`.

- **What operators should do when warnings appear:**
  1. Open the **PM Spot Health** panel: check per-asset **`pm_spot_effective_ok`**, **`pm_spot_unusable_reason`**, cache age, and **`feed_ttl_expired`**.
  2. If **`no_price_feed`** or **`no_quote_or_feed_ttl_expired`:** verify Coinbase Advanced HTTP credentials, network reachability, and logs from `LivePriceFeed` / Coinbase ticker loops (HTTP errors, auth failures, timeouts).
  3. If **`pm_max_age_exceeded`:** improve feed freshness (polling, latency) or, **only if acceptable for your risk**, increase **`MERID_PM_MAX_SPOT_AGE_SECONDS`** so PM allows slightly older quotes.
  4. When **`pm_spot_effective_ok`** is `true` again for all monitored assets, **`all_pm_assets_have_spot`** returns to `true` and MM quoting for those assets is **automatically** unblocked.

A standalone copy of this section lives in **`docs/pm-spot-operator.md`** for runbooks and links.

## Risk Limits

```bash
MERID_PM_MAX_NOTIONAL_PER_MARKET=500  # max notional per market ($)
MERID_PM_MAX_DAILY_LOSS=250           # daily loss limit ($)
MERID_PM_MAX_TOTAL_NOTIONAL=5000      # total portfolio notional cap ($)
MERID_TOTAL_CAPITAL_USD=50000         # total capital allocation
```

---

## Fills Polling Intervals

```bash
MERID_FILLS_POLL_INTERVAL_SEC=20      # fills HTTP polling interval (seconds, default 20)
MERID_FILLS_RECONCILE_INTERVAL_SEC=60 # fills reconciliation interval (seconds, default 60)
MERID_FILLS_BACKFILL_INTERVAL_SEC=300 # fills backfill interval (seconds, default 300)
```

---

## Safety Guardrails (new in Phase 23)

```bash
# Swarm consensus wall-clock kill switch
# When true: if an agent's swarm consensus is unavailable for > MERID_PM_SWARM_SOLO_WALL_SECONDS,
# the global kill switch fires. Default false (suppressed) for safe rollout.
MERID_DEPENDENCY_HEALTH_KILL_ENABLED=false

# Settlement outcome hard gate
# When true: if the Kalshi API returns no resolved outcome for a settled market,
# skip recording APT outcome instead of inferring from trade side.
# Default false (infer with WARNING log).
MERID_SETTLEMENT_REQUIRE_API_RESULT=false
```

---

## Fresh Start

```bash
MERID_FRESH_START=1                   # reset all state on next boot (paper mode only)
```

This clears paper positions, signals, consensus, and drift state. Kill switch state is preserved. Cannot be used in live mode.

---

## Notes

- Never commit `.env` to version control
- `.env.example` has the full variable list with defaults
- Run `make preflight` before committing to verify system health
