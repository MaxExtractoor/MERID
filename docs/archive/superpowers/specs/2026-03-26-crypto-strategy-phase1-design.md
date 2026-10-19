# Crypto Strategy Phase 1 — Design Spec

**Date:** 2026-03-26
**Phase:** 1 of 2
**Status:** Approved — ready for implementation plan

---

## Scope

Phase 1 delivers three components that together give every Kalshi crypto market a
model-derived probability estimate and a directional view, across all five assets and
all active Kalshi crypto timeframes.

| Component | File | Purpose |
|---|---|---|
| `CryptoTermStructureModel` | `merid/risk/crypto_term_structure.py` (new) | RTI-based vol engine; shared data source for both strategies |
| `SpotBasisFairValueStrategy` | `merid/prediction/opinion_strategy.py` (extend) | Strategy A — log-normal fair value + orderbook overlay |
| `TrendMomentumOpinionStrategy` | `merid/prediction/opinion_strategy.py` (extend) | Strategy C — MA-cross + momentum directional push |

**Phase 2 (deferred):** `CryptoJointModel`, `VolTailHedgeStrategy`, `CrossCoinRVStrategy`,
`EventReactiveStrategy`. Phase 2 depends on the correlation history accumulated by Phase 1.

---

## Assets and timeframes covered

All five assets: **BTC, ETH, SOL, XRP, DOGE**
All active Kalshi crypto timeframes:

| Timeframe | Example market | Kalshi series prefix |
|---|---|---|
| 15-minute | "BTC Up or Down – 15 minutes" | `KXBTC15M`, `KXETH15M`, … |
| Hourly | "BTC price today at 5pm ≥ X" | `KXBTC`, `KXETH`, … |
| Daily | "BTC price today at 5pm (daily close)" | `KXBTCD1`, … |
| Weekly | "BTC price on Friday at 5pm" | `KXBTCW1`, … |
| Monthly | "BTC price range this month / how high/low" | `KXBTC1M`, … |
| Annual / one-time | "BTC price at end of 2026" | `KXBTCY` |

---

## Data layer changes

### `config/kalshi_crypto_series_meta.py`

**Add monthly series** for all 5 assets (append to `SERIES_META_LIST`):

```python
SeriesMeta("BTC",  "monthly", "KXBTC1M",  "monthly", "cfb_rti_btc"),
SeriesMeta("ETH",  "monthly", "KXETH1M",  "monthly", "cfb_rti_eth"),
SeriesMeta("SOL",  "monthly", "KXSOL1M",  "monthly", "cfb_rti_sol"),
SeriesMeta("XRP",  "monthly", "KXXRP1M",  "monthly", "cfb_rti_xrp"),
SeriesMeta("DOGE", "monthly", "KXDOGE1M", "monthly", "cfb_rti_doge"),
```

**Add annual/one-time** BTC series:

```python
SeriesMeta("BTC", "annual", "KXBTCY", "annual", "cfb_rti_btc"),
```

**Add two boolean fields** to `SeriesMeta` (both default `True`):

```python
@dataclass(frozen=True)
class SeriesMeta:
    ...
    supports_basis: bool = True   # eligible for SpotBasisFairValueStrategy
    supports_trend: bool = True   # eligible for TrendMomentumOpinionStrategy
```

Update `TimeframeKey` literal to include `"monthly"` and `"annual"`.

### `merid/risk/crypto_rti_monitor.py`

**Add singleton factory** at module bottom. Two existing import sites
(`merid/data/rti_feed_service.py` and `merid/event_venues/kalshi/btc15m_risk.py`)
already import `get_global_crypto_rti_monitor` from this module; this makes those
imports resolve correctly for the first time.

```python
_global_monitor: Optional["CryptoRTIMonitor"] = None


def get_global_crypto_rti_monitor() -> "CryptoRTIMonitor":
    global _global_monitor
    if _global_monitor is None:
        raise RuntimeError(
            "CryptoRTIMonitor not initialized — "
            "call set_global_crypto_rti_monitor() first"
        )
    return _global_monitor


def set_global_crypto_rti_monitor(monitor: "CryptoRTIMonitor") -> None:
    global _global_monitor
    _global_monitor = monitor
```

---

## `merid/risk/crypto_term_structure.py` (new file)

### Purpose

Stateful async service. Polls `CryptoRTIMonitor` every second, aggregates into
1-minute close bars per asset, and exposes probability and vol accessors consumed by
both new strategies. Single source of RTI-derived data for all of Phase 1.

### Constants

```python
ASSETS       = ("BTC", "ETH", "SOL", "XRP", "DOGE")
MAX_BARS     = 43_200      # 30d × 1 440 min/d
MINUTES_PER_YEAR = 525_600
MIN_BARS_READY   = 30      # warm-up threshold before vol estimates are trusted

_FALLBACK_VOL = {          # annualized σ used before MIN_BARS_READY
    "BTC": 0.70, "ETH": 0.80, "SOL": 1.00, "XRP": 0.90, "DOGE": 1.20,
}
```

### Class `CryptoTermStructureModel`

```python
class CryptoTermStructureModel:

    def __init__(self) -> None:
        # Per-asset circular buffers of (minute_ts: int, close: float)
        self._bars: Dict[str, deque]           # maxlen=MAX_BARS
        # Accumulator for in-progress current minute
        self._current_minute: Dict[str, Tuple[int, float]]  # asset → (minute_ts, latest_price)
        self._task: Optional[asyncio.Task]
        self._monitor: Optional[CryptoRTIMonitor]

    # ── Lifecycle ──────────────────────────────────────────────────────
    async def start(self) -> None
        # Resolves monitor via get_global_crypto_rti_monitor()
        # Creates asyncio.Task(_poll_loop)

    async def stop(self) -> None
        # Cancels and awaits _task

    async def _poll_loop(self) -> None
        # Runs indefinitely; sleeps 1.0s per iteration
        # For each asset in ASSETS: reads monitor.get_rti_metrics(asset)["rti_current"]
        #   and calls _ingest_tick if price > 0

    def _ingest_tick(self, asset: str, price: float, ts: float) -> None
        # Computes minute_ts = int(ts // 60) * 60
        # If minute has advanced: appends closed bar to _bars[asset], updates accumulator
        # If same minute: overwrites accumulator with latest close

    # ── Public accessors ───────────────────────────────────────────────
    def is_ready(self, asset: str) -> bool
        # True iff len(_bars[asset]) >= MIN_BARS_READY

    def current_price(self, asset: str) -> float
        # Returns monitor.get_rti_metrics(asset).get("rti_current", 0.0)

    def get_returns(self, asset: str, window_minutes: int) -> List[float]
        # Log returns of last window_minutes closed bars
        # Used directly by TrendMomentumOpinionStrategy
        # Returns [] if fewer than 2 bars available

    def get_recent_prices(self, asset: str, n: int) -> List[float]
        # Raw close prices of last n bars (for MA computation)
        # Public — called directly by TrendMomentumOpinionStrategy

    # ── Vol estimation ─────────────────────────────────────────────────
    def _realized_vol_annual(self, asset: str, window_minutes: int) -> float
        # Annualized σ from log returns over window_minutes bars
        # σ_per_minute = std(returns); annualized = σ_per_minute × √MINUTES_PER_YEAR
        # Falls back to _FALLBACK_VOL[asset] if len(returns) < 5

    def _pick_vol_window(self, horizon_secs: float) -> int
        # Maps contract horizon to vol estimation window:
        #   ≤  15 × 60   →    15 bars  (15m markets)
        #   ≤   1 × 3600 →    60 bars  (hourly)
        #   ≤   4 × 3600 →   240 bars  (4h)
        #   ≤  86_400    →  1_440 bars (daily)
        #   ≤ 604_800    → 10_080 bars (weekly)
        #   else         → 43_200 bars (monthly / annual)

    # ── Probability API ────────────────────────────────────────────────
    def fair_prob(
        self, asset: str, horizon_secs: float,
        strike: float, side: str = "above",
    ) -> float
        # Log-normal CDF: Φ((ln(S/K) + ½σ²T) / (σ√T))
        # side="above" → Φ(d); side="below" → Φ(−d)
        # Normal CDF via stdlib: 0.5 * math.erfc(-x / math.sqrt(2))
        # Clipped to [1e-4, 1 - 1e-4]
        # Returns 0.5 if current_price <= 0 or TSM not ready

    def bracket_prob(
        self, asset: str, horizon_secs: float,
        low: float, high: float,
    ) -> float
        # fair_prob(above low) − fair_prob(above high)
        # Clipped to [1e-4, 1 - 1e-4]

    def up_prob(self, asset: str, horizon_secs: float) -> float
        # P(RTI_T > RTI_now) for "Up or Down" markets
        # short_window = max(5, min(30, int(horizon_secs / 60)))
        # returns = get_returns(asset, short_window)
        # T = horizon_secs / (365.25 × 86400)          # years
        # σ = _realized_vol_annual(asset, _pick_vol_window(horizon_secs))
        # drift_z = mean(returns) / (σ × √T)           # drift normalized to horizon
        # p = Φ(drift_z)                                # no scaling factor; full drift signal
        # Returns 0.5 if insufficient history (< 2 returns)
        # Clipped to [1e-4, 1 - 1e-4]

    def implied_move(self, asset: str, horizon_secs: float) -> float
        # σ_annual × √T; T in years
        # Returns fractional expected move (e.g., 0.05 = 5%)
```

### Singleton

```python
_tsm_instance: Optional[CryptoTermStructureModel] = None

def get_global_crypto_tsm() -> CryptoTermStructureModel:
    if _tsm_instance is None:
        raise RuntimeError("CryptoTermStructureModel not initialized")
    return _tsm_instance

def set_global_crypto_tsm(tsm: CryptoTermStructureModel) -> None:
    global _tsm_instance
    _tsm_instance = tsm
```

---

## `SpotBasisFairValueStrategy` (Strategy A)

**File:** `merid/prediction/opinion_strategy.py` — new class, appended before registry.
**Registry name:** `"spot_basis_fair_value"`

### Constructor

```python
def __init__(
    self,
    imbalance_weight: float = 0.03,
    min_edge: float = 0.02,
) -> None
```

### Context keys consumed from `context` dict

| Key | Type | Required | Notes |
|---|---|---|---|
| `asset` | str | yes | `"BTC"` … `"DOGE"` |
| `horizon_secs` | float | yes | Seconds to expiry |
| `market_type` | str | yes | `"up_down"`, `"threshold"`, `"bracket"` |
| `strike` | float | when threshold | Absolute price level |
| `bracket` | tuple[float,float] | when bracket | `(low, high)` |
| `side` | str | optional | `"above"` (default) or `"below"` |

### Logic

```
0. self.should_skip(market_prob) → return None  (base class extreme-prob guard)
1. Guard: if not tsm.is_ready(asset) → return None
2. Dispatch on market_type:
     up_down   → p_model = tsm.up_prob(asset, horizon_secs)
     threshold → p_model = tsm.fair_prob(asset, horizon_secs, strike, side)
     bracket   → p_model = tsm.bracket_prob(asset, horizon_secs, low, high)
     other     → return None
3. Clip p_model to [1e-4, 1 − 1e-4]
4. Orderbook overlay (only when horizon_secs ≤ 3600):
     - Load KalshiMarketStateStore.get(ticker)
     - If book_initialized: compute yes_depth/no_depth imbalance
     - imbalance_bias = (yes_depth/total − 0.5) × imbalance_weight
     - p_model = clip(p_model + imbalance_bias, 1e-4, 1 − 1e-4)
     - Silently skip if state unavailable
5. edge = p_model − market_prob
6. If |edge| < min_edge → return None
7. Return OpinionEstimate(
       agent_prob   = round(p_model, 4),
       confidence   = clip(0.40 + |edge| × 3.0, 0, 0.85),
       edge         = round(edge, 4),
       reasoning_tag = "spot_basis_fair_value",
       signal_sources = ["rti_term_structure", "log_normal_cdf"]
                        + (["orderbook_imbalance"] if overlay fired),
       explanation  = OpinionExplanation(
           inputs_used   = {asset, horizon_secs, market_type, strike_or_bracket},
           contributions = {tsm_fair: p_model_pre_overlay, imbalance: bias},
           rationale     = f"tsm_{market_type}_{asset}",
       ),
   )
```

---

## `TrendMomentumOpinionStrategy` (Strategy C)

**File:** `merid/prediction/opinion_strategy.py` — new class, appended after Strategy A.
**Registry name:** `"trend_momentum"`

### Context keys consumed from `context` dict

| Key | Type | Required | Notes |
|---|---|---|---|
| `asset` | str | yes | `"BTC"` … `"DOGE"` |
| `horizon_secs` | float | yes | Seconds to expiry |
| `market_type` | str | yes | `"up_down"`, `"threshold"`, `"bracket"` |
| `strike` | float | when threshold | Used for tsm_base when market_type=threshold |
| `bracket` | tuple[float,float] | when bracket | `(low, high)`; used for tsm_base when market_type=bracket |
| `side` | str | optional | `"above"` (default) or `"below"`; for threshold tsm_base |

### Constructor

```python
def __init__(
    self,
    short_window: int = 5,       # placeholder; overridden per-horizon internally
    long_window: int = 30,       # placeholder; overridden per-horizon internally
    min_edge: float = 0.02,
    max_signal_strength: float = 0.15,
) -> None
```

### Horizon-adaptive MA windows (internal, not constructor params)

| Contract horizon | Short MA | Long MA |
|---|---|---|
| ≤ 15 min | 5 bars | 30 bars |
| ≤ 1 h | 15 bars | 60 bars |
| ≤ 24 h | 60 bars | 480 bars |
| > 24 h (weekly / monthly / annual) | 480 bars | 4 320 bars |

### Logic

```
0. self.should_skip(market_prob) → return None  (base class extreme-prob guard)
1. Resolve short_w, long_w from horizon_secs using the table above
2. Guard: if len(tsm.get_returns(asset, long_w)) < long_w → return None
3. prices = tsm.get_recent_prices(asset, long_w + 5)
   Guard: if len(prices) < long_w → return None
4. short_MA = mean(prices[−short_w:])
   long_MA  = mean(prices[−long_w:])
   ma_cross = (short_MA − long_MA) / long_MA   # normalized
5. short_returns = tsm.get_returns(asset, short_w)
   momentum = mean(short_returns) if short_returns else 0.0
6. signal = clip(ma_cross × 0.6 + momentum × 0.4,
                 −max_signal_strength, +max_signal_strength)
7. Determine tsm_base:
     up_down   → tsm_base = 0.5
     threshold → tsm_base = tsm.fair_prob(asset, horizon_secs, strike, side)
                            if tsm.is_ready(asset) else market_prob
     bracket   → tsm_base = tsm.bracket_prob(asset, horizon_secs, low, high)
                            if tsm.is_ready(asset) else market_prob
8. p_model = clip(tsm_base + signal, 1e-4, 1 − 1e-4)
9. edge = p_model − market_prob
10. If |edge| < min_edge → return None
11. direction = "bullish" if signal > 0 else "bearish"
12. Return OpinionEstimate(
        agent_prob    = round(p_model, 4),
        confidence    = clip(0.35 + |signal| × 3.0, 0, 0.80),
        edge          = round(edge, 4),
        reasoning_tag = f"trend_momentum_{direction}",
        signal_sources = ["ma_cross", "momentum", "rti_minute_bars"],
        explanation   = OpinionExplanation(
            inputs_used   = {asset, horizon_secs, short_w, long_w},
            contributions = {ma_cross, momentum, signal},
            rationale     = f"trend_momentum_{direction}_{asset}",
        ),
    )
```

---

## Lifecycle wiring in `web/main.py`

### Startup (in lifespan, after existing monitor init)

```python
# 1. Register RTI monitor singleton (fixes two existing broken import sites)
from merid.risk.crypto_rti_monitor import set_global_crypto_rti_monitor
set_global_crypto_rti_monitor(crypto_rti_monitor)   # existing CryptoRTIMonitor instance

# 2. Start CryptoTermStructureModel
from merid.risk.crypto_term_structure import CryptoTermStructureModel, set_global_crypto_tsm
_tsm = CryptoTermStructureModel()
await _tsm.start()
set_global_crypto_tsm(_tsm)
```

### Shutdown

```python
await _tsm.stop()
```

### Strategy registry entries (in `opinion_strategy.py`)

```python
_STRATEGIES: Dict[str, type] = {
    ...existing entries...,
    "spot_basis_fair_value": SpotBasisFairValueStrategy,
    "trend_momentum":        TrendMomentumOpinionStrategy,
}
```

---

## What is explicitly NOT in Phase 1

- `CryptoJointModel` and cross-coin correlation math (Phase 2)
- `VolTailHedgeStrategy`, `CrossCoinRVStrategy`, `EventReactiveStrategy` (Phase 2)
- Strategy-level notional caps in `kalshi_filter_pipeline.py` (Phase 2)
- Exchange spot feeds (Binance/Coinbase WS) — RTI-only for Phase 1
- `allowed_strategies` per series in `kalshi_crypto_series_meta.py` (Phase 2)

---

## Files touched

| File | Change type |
|---|---|
| `config/kalshi_crypto_series_meta.py` | Extend — monthly + annual series, two new fields |
| `merid/risk/crypto_rti_monitor.py` | Extend — add `get/set_global_crypto_rti_monitor` singleton |
| `merid/risk/crypto_term_structure.py` | **New file** |
| `merid/prediction/opinion_strategy.py` | Extend — two new strategy classes + registry entries |
| `web/main.py` | Extend — TSM lifecycle wiring (start/stop/register) |
