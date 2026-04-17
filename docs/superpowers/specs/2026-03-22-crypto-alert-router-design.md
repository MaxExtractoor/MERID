# MERID Crypto Alert Router — Design Spec

**Date:** 2026-03-22
**Status:** Approved (rev 2 — spec-reviewer fixes applied)

---

## 1. Problem & Goal

MERID trades Kalshi crypto markets (BTC, ETH, SOL, XRP, DOGE) across six frequencies (15m, hourly, daily, weekly, monthly, annual). Today:

- Risk alerts are fired per-individual event with no per-symbol cooldown or deduplication.
- There is no classification of "which markets are trending / volatile / closing soon / near 50-50".
- Telegram receives one-off signals but no batched market-selection summaries.
- Config has no per-symbol or per-frequency thresholds.

**Goal:** A self-contained `CryptoAlertRouter` that runs every 30 s, classifies all live crypto markets into six tags, emits clean batched Telegram summaries and risk alerts, and exposes metrics — without touching the ingestion hot path.

---

## 2. Architecture Decision

**Choice: Option A (periodic router) with path to B (enrichment baked into KalshiMarketState).**

The router reads from the existing `KalshiMarketStateStore`, computes tags on-the-fly, and lives entirely in one new file. The tag computation is a pure function over a `MarketSnapshot` dataclass, so it can be promoted into `KalshiMarketState` later (B migration) without changing any downstream consumer.

Option C (event-driven) is deferred until multiple independent consumers exist.

---

## 3. Data Model

### `MarketSnapshot`

```python
@dataclass
class MarketSnapshot:
    # Identity
    symbol: str                  # "BTC"|"ETH"|"SOL"|"XRP"|"DOGE"
    market_id: str               # e.g. "KXBTCD-26MAR2220"
    episode_id: str              # ladder/event ticker (series_ticker from KalshiMarket REST)
    frequency: str               # "15m"|"hourly"|"daily"|"weekly"|"monthly"|"annual"|"one_time"
    status: str                  # "pre"|"live"|"closing_soon"|"settled"
    title: str = ""              # short human label for Telegram/logs (never None; default "")

    # Volume & liquidity
    volume_24h: int = 0
    oi: int | None = None        # open interest (optional, for richer ranking)

    # Pricing (single source of truth: always 0–1)
    p_yes: float = 0.5           # always yes_price / 100; never branch on raw yes_price

    # Book state
    spread_cents: float = 0.0
    depth_10c: int = 0

    # Timing
    seconds_to_expiry: float = 0.0
    created_at: float = 0.0      # Unix timestamp (for is_new computation)

    # Computed flags (set during snapshot construction, NOT inputs to compute_tags)
    is_new: bool = False
    is_trending: bool = False
    volatility_score: float = 0.0  # 0–1, normalized per symbol
    closing_soon: bool = False
```

### Snapshot construction — field sources

The router maintains a side-table (`_market_meta: dict[str, KalshiMarketMeta]`) populated from a periodic Kalshi REST call to `GET /markets` (crypto category filter). Each entry provides the fields not present in `KalshiMarketStateStore`:

| `MarketSnapshot` field | Source |
|---|---|
| `symbol` | Parsed from `ticker` via `_ticker_to_symbol(ticker)`: look up prefix ("KXBTC" → "BTC", "KXETH" → "ETH", etc.) |
| `episode_id` | `KalshiMarket.series_ticker` (from REST) |
| `frequency` | Mapped from `KalshiMarket.series_ticker` suffix or category tag via `_series_to_frequency()` |
| `status` | `KalshiMarket.status` (from REST, one of "active"/"paused"/"closed"/"settled") |
| `title` | `KalshiMarket.title` (from REST); HTML-escaped before use (see §7) |
| `created_at` | `KalshiMarket.created_at.timestamp()` (from REST); 0.0 if absent |
| `oi` | `KalshiMarket.open_interest` (from REST, optional) |
| `volume_24h` | `KalshiMarketState.volume_24h` (from WS/book store) |
| `spread_cents` | `KalshiMarketState.spread_cents` |
| `depth_10c` | `KalshiMarketState.depth_10c` |
| `seconds_to_expiry` | `KalshiMarketState.seconds_to_expiry` |
| `p_yes` | `KalshiMarketState.mid_cents / 100` |

`_market_meta` is refreshed every `META_REFRESH_INTERVAL_SECONDS` (default 300s) in a background subtask. Markets not in `_market_meta` are skipped during snapshot construction.

**Ticker-to-symbol mapping** (required, not inferred at runtime):

```python
TICKER_PREFIX_TO_SYMBOL = {
    "KXBTC": "BTC",
    "KXETH": "ETH",
    "KXSOL": "SOL",
    "KXXRP": "XRP",
    "KXDOGE": "DOGE",
}
```

**Computed construction rules:**

- `p_yes` = `mid_cents / 100`; clamped to `[0.0, 1.0]`.
- `is_new` = `created_at > 0 and (now() - created_at) < config.NEW_MARKET_WINDOW_MINUTES * 60`
- `is_trending` = `volume_24h > _volume_baseline.get(symbol, 0) * config.TREND_VOLUME_MULTIPLIER` where `_volume_baseline[symbol]` is the per-symbol rolling 1-hour average updated in router state each tick.
- `volatility_score` = `spread_cents / max(depth_10c, 1)`, then min-max normalized across all snapshots for the same symbol in the current tick. Result clamped to `[0.0, 1.0]`.
- `closing_soon` = `0 < seconds_to_expiry < config.CLOSING_SOON_WINDOW_MINUTES * 60`

---

## 4. Tag Computation (pure function)

```python
class MarketTag(str, Enum):
    TRENDING     = "TRENDING"
    VOLATILE     = "VOLATILE"
    NEW          = "NEW"
    CLOSING_SOON = "CLOSING_SOON"
    HIGH_VOLUME  = "HIGH_VOLUME"
    FIFTY_FIFTY  = "FIFTY_FIFTY"

def compute_tags(snap: MarketSnapshot, cfg: CryptoAlertConfig) -> set[MarketTag]:
    tags = set()
    if snap.is_trending:
        tags.add(MarketTag.TRENDING)
    if snap.volatility_score > cfg.volatility_threshold(snap.symbol, snap.frequency):
        tags.add(MarketTag.VOLATILE)
    if snap.is_new:
        tags.add(MarketTag.NEW)
    if snap.closing_soon:
        tags.add(MarketTag.CLOSING_SOON)
    if snap.volume_24h > cfg.volume_threshold(snap.symbol, snap.frequency):
        tags.add(MarketTag.HIGH_VOLUME)
    if (
        cfg.enable_fifty_fifty
        and snap.volume_24h >= cfg.min_volume_for_fifty_fifty(snap.symbol, snap.frequency)
        and cfg.fifty_low(snap.symbol) <= snap.p_yes <= cfg.fifty_high(snap.symbol)
    ):
        tags.add(MarketTag.FIFTY_FIFTY)
    return tags
```

A market can carry multiple tags. Tags are independent; no hierarchy.

**Config threshold lookups use `.get()` with symbol-level then global fallback:**

```python
def volatility_threshold(self, symbol: str, frequency: str) -> float:
    sym_map = self.VOLATILITY_THRESHOLDS.get(symbol, {})
    return sym_map.get(frequency, sym_map.get("_default", self._global_volatility_default))
```

Same pattern applies to `volume_threshold`, `min_volume_for_fifty_fifty`. A `KeyError` is never raised.

**Ranking order per tag (for top-N selection):**

| Tag | Sort key |
|---|---|
| TRENDING | Filter to `is_trending == True` first, then sort by `volume_24h` desc |
| VOLATILE | `volatility_score` desc |
| NEW | `created_at` desc (most recent first) |
| CLOSING_SOON | `seconds_to_expiry` asc (soonest first) |
| HIGH_VOLUME | `volume_24h` desc |
| FIFTY_FIFTY | `volume_24h` desc, then `seconds_to_expiry` asc |

(TRENDING filter-then-rank avoids the meaningless `bool + int` comparison.)

---

## 5. Router Tick Loop

Runs every `TICK_INTERVAL_SECONDS` (default 30s) as a background asyncio task.

```python
async def run(self) -> None:
    try:
        while True:
            await self._tick()
            await asyncio.sleep(self._cfg.TICK_INTERVAL_SECONDS)
    except asyncio.CancelledError:
        return   # clean shutdown; no cleanup needed

async def stop(self) -> None:
    if self._task:
        self._task.cancel()
        await asyncio.gather(self._task, return_exceptions=True)
```

`run()` is wrapped in a top-level `try/except Exception` inside `_tick()` so a single bad tick increments `_error_count` and logs without crashing the loop.

**Order of operations per tick:**

1. **Risk alerts first** — drain `PredictionAlertManager` of alerts newer than `_last_tick_ts` (using `get_history()` filtered by timestamp), aggregate per `(symbol, episode_id)`, deduplicate per severity, apply cooldown, emit.
2. **Refresh meta** — if `now - _last_meta_refresh > META_REFRESH_INTERVAL_SECONDS`, re-fetch `_market_meta` from Kalshi REST.
3. **Build snapshots** — join `_market_meta` with `KalshiMarketStateStore`, filter to supported symbols, construct `MarketSnapshot` per market.
4. **Update baselines** — update `_volume_baseline[symbol]` rolling average from current snapshots.
5. **Compute tags** — call `compute_tags()` per snapshot.
6. **Rank & select** — for each `(symbol, tag)` pair, rank by the appropriate key, take top-N.
7. **Emit market-selection alerts** — apply cooldown per `(symbol, tag)`, emit batched Telegram + log + metrics.
8. **Update metrics** — write live/by-tag gauges.
9. **Set `_last_tick_ts`** — record current monotonic time.

Risk alerts are handled first (step 1) so a heavy tagging pass never delays risk notification.

**Risk alert drain from `PredictionAlertManager`:**

```python
# Filter to alerts fired after last tick
pending = [a for a in alert_mgr.get_history() if a.timestamp > self._last_tick_ts]
# Group by (symbol, episode_id) — extract symbol from alert.data["symbol"] if present
```

This requires no new queue on `PredictionAlertManager`. The router is responsible for deduplication via its own cooldown map.

---

## 6. Cooldown Map

```python
_cooldowns: dict[tuple, float]  # key → last_fired monotonic time

def _key_risk(symbol: str, episode_id: str, severity: str) -> tuple:
    return ("risk_limit", symbol, episode_id, severity)

def _key_market_selection(symbol: str, tag: MarketTag) -> tuple:
    return ("market_selection", symbol, tag.value, "info")

def _is_suppressed(self, key: tuple, cooldown_minutes: float) -> bool:
    last = self._cooldowns.get(key, 0.0)
    return (time.monotonic() - last) < cooldown_minutes * 60

def _record_fired(self, key: tuple) -> None:
    self._cooldowns[key] = time.monotonic()
```

- Risk: suppress within `RISK_ALERT_COOLDOWN_MINUTES`; override (always fire) on severity escalation.
- Market-selection: suppress within `MARKET_SELECTION_COOLDOWN_MINUTES` (default 10 min).

---

## 7. Telegram Batching

### Updated `send_risk_alert` signature

The existing method is extended to carry `symbol` and `episode_id`:

```python
async def send_risk_alert(
    self,
    alert_type: str,
    message: str,
    severity: str = "warning",
    symbol: str | None = None,
    episode_id: str | None = None,
    frequency: str | None = None,
    total_risk: float | None = None,
    risk_limit: float | None = None,
) -> None:
```

Existing call sites that omit the new kwargs continue to work unchanged (all new params are optional with `None` defaults).

### `MarketSelectionItem` dataclass

```python
@dataclass
class MarketSelectionItem:
    market_id: str
    title: str          # pre-HTML-escaped before passing here
    frequency: str
    volume_24h: int
    p_yes: float
    tags: set[MarketTag]
```

### New `send_market_selection_batch`

```python
async def send_market_selection_batch(
    self,
    symbol: str,
    tag: MarketTag,
    markets: list[MarketSelectionItem],
) -> None:
```

**HTML escaping:** Before building the message, escape `title` and `market_id` using Python's `html.escape()`. This prevents broken HTML parse mode for any title containing `<`, `>`, or `&`.

**Message format (HTML mode):**

```html
📈 [<b>BTC</b>] [<b>TRENDING</b>] markets
Top BTC TRENDING markets

- KXBTCD-26MAR22: Will BTC close above 87000? (freq=daily, vol=12,400, p_yes≈0.52)
- KXBTCD-26MAR22H: Will BTC close above 90000? (freq=daily, vol=8,100, p_yes≈0.34)
```

At N=5, max 80 chars/bullet → ~450 chars total. Well within Telegram's 4096-char limit.

**Risk alert format:**

```
🚨 [WARNING] [BTC] [risk_limit]
Risk limit breached on BTC daily ladder
KXBTCD-26MAR22 (daily)
Total risk: $480 / Limit: $500
```

---

## 8. Metrics (REST, no Prometheus)

In-process `collections.Counter` and `dict` updated each tick. Exposed via:

- `GET /api/v1/alerts/crypto/metrics` — JSON with counters, gauges, and symbol+tag breakdown
- `GET /api/v1/alerts/crypto/status` — router health (`running`, `last_tick_ts`, `error_count`, `cooldown_map_size`)

**Counter keys:**

```
merid_crypto_selected_markets_total[(symbol, tag)]
merid_risk_alerts_total[(symbol, episode_id, severity, alert_type)]
```

**Gauge keys:**

```
merid_crypto_markets_live[symbol]           # count of live markets this tick
merid_crypto_markets_by_tag[(symbol, tag)]  # count with this tag (before top-N filter)
```

**Note:** Per-process only. Acceptable for current single-process deployment.

---

## 9. Config (`CryptoAlertConfig`)

All thresholds live in `config/crypto_alert_config.py`. Never hard-coded in the router.

```python
VOLATILITY_THRESHOLDS: dict[str, dict[str, float]]
# symbol → frequency → threshold
# Each symbol dict may include "_default" key as fallback.
# Global default: 0.5

HIGH_VOLUME_THRESHOLDS: dict[str, dict[str, int]]
# symbol → frequency → min contracts; "_default" fallback supported

FIFTY_FIFTY_BAND: dict[str, tuple[float, float]]
# symbol → (low, high); default (0.45, 0.55)

MIN_VOLUME_FOR_FIFTY_FIFTY: dict[str, dict[str, int]]
# symbol → frequency → min volume; "_default" fallback supported

NEW_MARKET_WINDOW_MINUTES: int = 60
CLOSING_SOON_WINDOW_MINUTES: int = 10
TOP_N_PER_TAG_PER_SYMBOL: int = 5
TICK_INTERVAL_SECONDS: int = 30
META_REFRESH_INTERVAL_SECONDS: int = 300
RISK_ALERT_COOLDOWN_MINUTES: int = 5
MARKET_SELECTION_COOLDOWN_MINUTES: int = 10
TREND_VOLUME_MULTIPLIER: float = 1.5

# Feature flags
ENABLE_LOGGING: bool = True
ENABLE_TELEGRAM_RISK_ALERTS: bool = True
ENABLE_TELEGRAM_MARKET_ALERTS: bool = True
ENABLE_METRICS: bool = True
ENABLE_FIFTY_FIFTY: bool = True

SUPPORTED_SYMBOLS: list[str] = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
```

All per-symbol/frequency threshold lookups use `.get()` with `"_default"` fallback so unknown symbols or frequencies never raise `KeyError`.

---

## 10. Files Created / Modified

| File | Change |
|---|---|
| `merid/alerts/crypto_alert_router.py` | **NEW** — `MarketSnapshot`, `MarketTag`, `MarketSelectionItem`, `compute_tags()`, `CryptoAlertRouter` |
| `config/crypto_alert_config.py` | **NEW** — `CryptoAlertConfig` dataclass + sensible defaults |
| `agents/telegram_agent.py` | **MODIFY** — add `send_market_selection_batch()`; extend `send_risk_alert()` with optional `symbol`/`episode_id`/`frequency`/`total_risk`/`risk_limit` kwargs |
| `merid/prediction/alerts.py` | **MODIFY** — add `AlertCategory.MARKET_SELECTION` |
| `web/main.py` | **MODIFY** — wire `router = CryptoAlertRouter(...)` + `asyncio.create_task(router.run())`; call `await router.stop()` in lifespan teardown |
| `web/api/system_endpoints.py` | **MODIFY** — add `/api/v1/alerts/crypto/status` and `/api/v1/alerts/crypto/metrics` endpoints |

---

## 11. Path to B (KalshiMarketState Enrichment)

When heuristics are stable, `compute_tags` pure function and `MarketSnapshot` construction logic move into `KalshiMarketStateStore`. No change to the tag contract or any consumer downstream of the router.

Migration checklist (deferred):
- Add `is_trending`, `is_new`, `volatility_score`, `closing_soon` cached fields to `KalshiMarketState`
- Add `symbol`, `episode_id`, `frequency`, `status`, `title`, `created_at`, `oi` fields to `KalshiMarketState` (currently populated from REST side-table in the router; move to store)
- Move `_volume_baseline[symbol]` rolling-average state from `CryptoAlertRouter` into `KalshiMarketStateStore` or a shared `MarketStatisticsCache`; do not delete it — `is_trending` depends on it
- Compute all enriched fields in `_sync_book_fields()` after each orderbook update
- Remove snapshot-construction logic and `_market_meta` side-table from the router; read enriched fields directly from the store
- Expose enriched fields through existing `/api/v1/kalshi/markets` REST response

---

## 12. Out of Scope (this iteration)

- Prometheus integration (use REST metrics)
- Multi-chat-id Telegram routing
- UI filter by tag (deferred to B migration)
- Event-bus subscription model (Option C)
- Per-tag risk limits in `PredictionRiskConfig`
