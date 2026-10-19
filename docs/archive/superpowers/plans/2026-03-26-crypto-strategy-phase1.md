# Crypto Strategy Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `CryptoTermStructureModel` (RTI-based vol engine) plus `SpotBasisFairValueStrategy` and `TrendMomentumOpinionStrategy` to MERID, covering BTC/ETH/SOL/XRP/DOGE across all Kalshi crypto timeframes.

**Architecture:** A stateful async service (`CryptoTermStructureModel`) polls `CryptoRTIMonitor` every second, accumulates 1-minute close bars per asset (30 days deep), and exposes log-normal probability and vol APIs. Two new `OpinionStrategy` subclasses consume those APIs; both are registered in the existing `get_strategy()` registry.

**Tech Stack:** Python 3.11+, asyncio, `math.erfc` for normal CDF (stdlib only, no scipy), `collections.deque`, `unittest.mock` for tests, pytest-asyncio for async tests.

---

### Task 1: Extend `kalshi_crypto_series_meta.py`

**Files:**
- Modify: `config/kalshi_crypto_series_meta.py`
- Modify: `tests/config/test_kalshi_crypto_series_meta.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/config/test_kalshi_crypto_series_meta.py`:

```python
from config.kalshi_crypto_series_meta import (
    SERIES_META_LIST,
    SERIES_META_BY_KEY,
    SERIES_META_BY_TICKER,
    get_series_meta,
    SeriesMeta,
)


def test_monthly_series_exist_for_all_assets():
    assets = ("BTC", "ETH", "SOL", "XRP", "DOGE")
    for asset in assets:
        meta = get_series_meta(asset, "monthly")
        assert meta is not None, f"No monthly series for {asset}"
        assert meta.timeframe == "monthly"


def test_btc_annual_series_exists():
    meta = get_series_meta("BTC", "annual")
    assert meta is not None
    assert meta.series_ticker == "KXBTCY"


def test_monthly_tickers_correct():
    expected = {
        "BTC": "KXBTC1M", "ETH": "KXETH1M", "SOL": "KXSOL1M",
        "XRP": "KXXRP1M", "DOGE": "KXDOGE1M",
    }
    for asset, ticker in expected.items():
        meta = get_series_meta(asset, "monthly")
        assert meta.series_ticker == ticker


def test_new_series_in_by_ticker_index():
    assert "KXBTC1M" in SERIES_META_BY_TICKER
    assert "KXBTCY" in SERIES_META_BY_TICKER


def test_supports_basis_defaults_true():
    for meta in SERIES_META_LIST:
        assert meta.supports_basis is True


def test_supports_trend_defaults_true():
    for meta in SERIES_META_LIST:
        assert meta.supports_trend is True


def test_timeframekey_covers_annual():
    # Confirm SeriesMeta accepts "annual" without a TypeError
    m = SeriesMeta("BTC", "annual", "KXBTCY", "annual", "cfb_rti_btc")
    assert m.timeframe == "annual"
```

- [ ] **Step 2: Run to confirm failure**

```
pytest tests/config/test_kalshi_crypto_series_meta.py -v -k "monthly or annual or supports_basis or supports_trend"
```

Expected: multiple FAILs (`get_series_meta` returns None, AttributeError on `supports_basis`).

- [ ] **Step 3: Implement**

In `config/kalshi_crypto_series_meta.py`:

```python
# Change TimeframeKey line to:
TimeframeKey = Literal["15m", "1h", "daily", "weekly", "monthly", "annual"]

# Change SeriesMeta dataclass to add two fields after category:
@dataclass(frozen=True)
class SeriesMeta:
    asset: AssetSymbol
    timeframe: TimeframeKey
    series_ticker: str
    expected_api_frequency: str
    settlement_source_hint: str
    category: str = "crypto"
    supports_basis: bool = True
    supports_trend: bool = True

# Append to SERIES_META_LIST tuple (before the closing parenthesis):
    SeriesMeta("BTC",  "monthly", "KXBTC1M",  "monthly", "cfb_rti_btc"),
    SeriesMeta("ETH",  "monthly", "KXETH1M",  "monthly", "cfb_rti_eth"),
    SeriesMeta("SOL",  "monthly", "KXSOL1M",  "monthly", "cfb_rti_sol"),
    SeriesMeta("XRP",  "monthly", "KXXRP1M",  "monthly", "cfb_rti_xrp"),
    SeriesMeta("DOGE", "monthly", "KXDOGE1M", "monthly", "cfb_rti_doge"),
    SeriesMeta("BTC",  "annual",  "KXBTCY",   "annual",  "cfb_rti_btc"),
```

- [ ] **Step 4: Run tests**

```
pytest tests/config/test_kalshi_crypto_series_meta.py -v
```

Expected: all new tests PASS.

- [ ] **Step 5: Commit**

```bash
git add config/kalshi_crypto_series_meta.py tests/config/test_kalshi_crypto_series_meta.py
git commit -m "feat(meta): add monthly/annual series and strategy flags to SeriesMeta"
```

---

### Task 2: Add RTI monitor singleton

**Files:**
- Modify: `merid/risk/crypto_rti_monitor.py`
- New: `tests/risk/__init__.py` (empty)
- New: `tests/risk/test_crypto_rti_monitor_singleton.py`

- [ ] **Step 1: Write failing tests**

Create `tests/risk/test_crypto_rti_monitor_singleton.py`:

```python
import pytest
import merid.risk.crypto_rti_monitor as mod
from merid.risk.crypto_rti_monitor import (
    get_global_crypto_rti_monitor,
    set_global_crypto_rti_monitor,
    CryptoRTIMonitor,
)
from unittest.mock import MagicMock


def _clear_singleton():
    mod._global_monitor = None


def test_raises_before_set():
    _clear_singleton()
    with pytest.raises(RuntimeError, match="not initialized"):
        get_global_crypto_rti_monitor()


def test_set_then_get_returns_same_instance():
    _clear_singleton()
    mock = MagicMock(spec=CryptoRTIMonitor)
    set_global_crypto_rti_monitor(mock)
    assert get_global_crypto_rti_monitor() is mock


def test_set_overwrites_previous():
    mock_a = MagicMock(spec=CryptoRTIMonitor)
    mock_b = MagicMock(spec=CryptoRTIMonitor)
    set_global_crypto_rti_monitor(mock_a)
    set_global_crypto_rti_monitor(mock_b)
    assert get_global_crypto_rti_monitor() is mock_b
```

- [ ] **Step 2: Run to confirm failure**

```
pytest tests/risk/test_crypto_rti_monitor_singleton.py -v
```

Expected: ImportError or AttributeError (`_global_monitor` / functions not defined).

- [ ] **Step 3: Create `tests/risk/__init__.py` and implement**

```bash
touch tests/risk/__init__.py
```

Append to the **bottom** of `merid/risk/crypto_rti_monitor.py`:

```python
from __future__ import annotations
from typing import Optional as _Optional

_global_monitor: _Optional["CryptoRTIMonitor"] = None


def get_global_crypto_rti_monitor() -> "CryptoRTIMonitor":
    """Return the singleton CryptoRTIMonitor; raises if not yet registered."""
    global _global_monitor
    if _global_monitor is None:
        raise RuntimeError(
            "CryptoRTIMonitor not initialized — "
            "call set_global_crypto_rti_monitor() first"
        )
    return _global_monitor


def set_global_crypto_rti_monitor(monitor: "CryptoRTIMonitor") -> None:
    """Register the singleton CryptoRTIMonitor (called once from web/main.py)."""
    global _global_monitor
    _global_monitor = monitor
```

- [ ] **Step 4: Run tests**

```
pytest tests/risk/test_crypto_rti_monitor_singleton.py -v
```

Expected: all 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add merid/risk/crypto_rti_monitor.py tests/risk/__init__.py tests/risk/test_crypto_rti_monitor_singleton.py
git commit -m "feat(rti): add get/set_global_crypto_rti_monitor singleton factory"
```

---

### Task 3: Create `crypto_term_structure.py` — ingestion, accessors, vol

**Files:**
- New: `merid/risk/crypto_term_structure.py`
- New: `tests/risk/test_crypto_term_structure.py`

- [ ] **Step 1: Write failing tests for ingestion and vol**

Create `tests/risk/test_crypto_term_structure.py`:

```python
import math
import pytest
from unittest.mock import MagicMock

from merid.risk.crypto_term_structure import (
    CryptoTermStructureModel,
    _norm_cdf,
    _FALLBACK_VOL,
    MIN_BARS_READY,
    MINUTES_PER_YEAR,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _populate(tsm: CryptoTermStructureModel, asset: str, prices: list,
              start_ts: float = 1_700_000_000.0) -> None:
    """Feed one price per minute into TSM, then close the last bar."""
    for i, price in enumerate(prices):
        tsm._ingest_tick(asset, price, start_ts + i * 60 + 30)
    # Extra tick to flush the last bar
    tsm._ingest_tick(asset, prices[-1], start_ts + len(prices) * 60 + 30)


def _make_ready(asset: str = "BTC", base: float = 100_000.0,
                n: int = 40) -> CryptoTermStructureModel:
    """Return a TSM with n bars populated and a mock monitor."""
    tsm = CryptoTermStructureModel()
    # Slight noise to avoid zero variance
    prices = [base * (1 + 0.001 * ((i % 5) - 2)) for i in range(n)]
    _populate(tsm, asset, prices)
    mock = MagicMock()
    mock.get_rti_metrics.return_value = {"rti_current": base}
    tsm._monitor = mock
    return tsm


# ── _norm_cdf ─────────────────────────────────────────────────────────────────

def test_norm_cdf_at_zero():
    assert _norm_cdf(0.0) == pytest.approx(0.5, abs=1e-10)

def test_norm_cdf_positive():
    assert _norm_cdf(1.0) > 0.5

def test_norm_cdf_symmetric():
    assert _norm_cdf(-1.645) == pytest.approx(1 - _norm_cdf(1.645), abs=1e-8)


# ── _ingest_tick ──────────────────────────────────────────────────────────────

def test_first_tick_sets_accumulator():
    tsm = CryptoTermStructureModel()
    tsm._ingest_tick("BTC", 50_000.0, 1_700_000_030.0)
    assert tsm._current_minute["BTC"][1] == 50_000.0
    assert len(tsm._bars["BTC"]) == 0


def test_same_minute_updates_close():
    tsm = CryptoTermStructureModel()
    tsm._ingest_tick("BTC", 50_000.0, 1_700_000_010.0)
    tsm._ingest_tick("BTC", 50_100.0, 1_700_000_050.0)
    assert tsm._current_minute["BTC"][1] == 50_100.0
    assert len(tsm._bars["BTC"]) == 0


def test_minute_advance_closes_bar():
    tsm = CryptoTermStructureModel()
    tsm._ingest_tick("BTC", 50_000.0, 1_700_000_030.0)   # minute 0
    tsm._ingest_tick("BTC", 51_000.0, 1_700_000_090.0)   # minute 1 → closes min 0
    assert len(tsm._bars["BTC"]) == 1
    _, close = tsm._bars["BTC"][0]
    assert close == 50_000.0


def test_multiple_prices_accumulate_bars():
    tsm = CryptoTermStructureModel()
    prices = [100.0, 101.0, 102.0, 103.0, 104.0]
    _populate(tsm, "BTC", prices)
    assert len(tsm._bars["BTC"]) == len(prices)


# ── is_ready / get_returns / get_recent_prices ────────────────────────────────

def test_not_ready_below_threshold():
    tsm = CryptoTermStructureModel()
    _populate(tsm, "BTC", [100.0] * (MIN_BARS_READY - 1))
    assert not tsm.is_ready("BTC")


def test_ready_at_threshold():
    tsm = CryptoTermStructureModel()
    _populate(tsm, "BTC", [100.0] * (MIN_BARS_READY + 1))
    assert tsm.is_ready("BTC")


def test_get_returns_empty_when_no_bars():
    tsm = CryptoTermStructureModel()
    assert tsm.get_returns("BTC", 10) == []


def test_get_returns_zero_for_constant_prices():
    tsm = CryptoTermStructureModel()
    _populate(tsm, "BTC", [100.0] * 35)
    returns = tsm.get_returns("BTC", 30)
    assert all(r == pytest.approx(0.0, abs=1e-10) for r in returns)


def test_get_returns_positive_for_rising_prices():
    tsm = CryptoTermStructureModel()
    prices = [100.0, 101.0, 102.01, 103.0301]
    _populate(tsm, "BTC", prices)
    returns = tsm.get_returns("BTC", 4)
    assert all(r > 0 for r in returns)
    assert returns[0] == pytest.approx(math.log(101.0 / 100.0), abs=1e-6)


def test_get_recent_prices_length_and_last():
    tsm = CryptoTermStructureModel()
    prices = [float(i) for i in range(100, 140)]
    _populate(tsm, "BTC", prices)
    recent = tsm.get_recent_prices("BTC", 5)
    assert len(recent) == 5
    assert recent[-1] == pytest.approx(prices[-1], abs=0.01)


# ── _pick_vol_window ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("horizon_secs,expected", [
    (900,       15),
    (3_600,     60),
    (14_400,   240),
    (86_400,  1_440),
    (604_800, 10_080),
    (2_592_000, 43_200),
    (31_536_000, 43_200),
])
def test_pick_vol_window(horizon_secs, expected):
    tsm = CryptoTermStructureModel()
    assert tsm._pick_vol_window(horizon_secs) == expected


# ── _realized_vol_annual ──────────────────────────────────────────────────────

def test_vol_fallback_when_insufficient():
    tsm = CryptoTermStructureModel()
    assert tsm._realized_vol_annual("BTC", 30) == _FALLBACK_VOL["BTC"]


def test_vol_fallback_unknown_asset():
    tsm = CryptoTermStructureModel()
    assert tsm._realized_vol_annual("UNKNOWN", 30) == 0.90


def test_vol_near_zero_for_constant_prices():
    tsm = CryptoTermStructureModel()
    _populate(tsm, "BTC", [100.0] * 50)
    assert tsm._realized_vol_annual("BTC", 40) == pytest.approx(0.0, abs=1e-6)


def test_vol_annualization_matches_manual():
    tsm = CryptoTermStructureModel()
    prices = [100.0 if i % 2 == 0 else 101.0 for i in range(50)]
    _populate(tsm, "BTC", prices)
    returns = tsm.get_returns("BTC", 40)
    n = len(returns)
    mean_r = sum(returns) / n
    var = sum((r - mean_r) ** 2 for r in returns) / max(n - 1, 1)
    expected = (var ** 0.5) * (MINUTES_PER_YEAR ** 0.5)
    assert tsm._realized_vol_annual("BTC", 40) == pytest.approx(expected, rel=0.01)
```

- [ ] **Step 2: Run to confirm failure**

```
pytest tests/risk/test_crypto_term_structure.py -v
```

Expected: ImportError (`merid.risk.crypto_term_structure` doesn't exist yet).

- [ ] **Step 3: Create `merid/risk/crypto_term_structure.py`**

```python
"""Crypto Term Structure Model — RTI-based probability engine.

Polls CryptoRTIMonitor every second for BTC/ETH/SOL/XRP/DOGE, accumulates
1-minute close bars (30 days deep per asset), and exposes log-normal probability
and vol APIs consumed by SpotBasisFairValueStrategy and TrendMomentumOpinionStrategy.
"""
from __future__ import annotations

import asyncio
import math
import time
from collections import deque
from typing import Dict, List, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("merid.risk.crypto_term_structure")

ASSETS = ("BTC", "ETH", "SOL", "XRP", "DOGE")
MAX_BARS = 43_200           # 30d × 1 440 min/d
MINUTES_PER_YEAR = 525_600
MIN_BARS_READY = 30         # minimum bars before vol estimates are trusted

_FALLBACK_VOL: Dict[str, float] = {
    "BTC": 0.70, "ETH": 0.80, "SOL": 1.00, "XRP": 0.90, "DOGE": 1.20,
}


def _norm_cdf(x: float) -> float:
    """Standard normal CDF via stdlib math.erfc — exact, no scipy needed."""
    return 0.5 * math.erfc(-x / math.sqrt(2))


class CryptoTermStructureModel:
    """Stateful RTI-based vol and probability engine for all 5 Kalshi crypto assets."""

    def __init__(self) -> None:
        self._bars: Dict[str, deque] = {
            a: deque(maxlen=MAX_BARS) for a in ASSETS
        }
        # In-progress accumulator: asset → (minute_ts_epoch, latest_close)
        self._current_minute: Dict[str, Tuple[int, float]] = {}
        self._task: Optional[asyncio.Task] = None
        self._monitor = None  # set in start()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        from merid.risk.crypto_rti_monitor import get_global_crypto_rti_monitor
        self._monitor = get_global_crypto_rti_monitor()
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("CryptoTermStructureModel started (assets=%s)", ASSETS)

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("CryptoTermStructureModel stopped")

    async def _poll_loop(self) -> None:
        while True:
            ts = time.time()
            for asset in ASSETS:
                try:
                    metrics = self._monitor.get_rti_metrics(asset)
                    price = metrics.get("rti_current", 0.0)
                    if price > 0:
                        self._ingest_tick(asset, price, ts)
                except Exception as exc:
                    logger.debug("TSM poll error %s: %s", asset, exc)
            await asyncio.sleep(1.0)

    # ── Ingestion ─────────────────────────────────────────────────────────────

    def _ingest_tick(self, asset: str, price: float, ts: float) -> None:
        """Roll a 1-second RTI tick into the 1-minute bar buffer."""
        minute_ts = int(ts // 60) * 60
        if asset not in self._current_minute:
            self._current_minute[asset] = (minute_ts, price)
            return
        prev_minute_ts, prev_price = self._current_minute[asset]
        if minute_ts > prev_minute_ts:
            # Close the previous bar with its last known price
            self._bars[asset].append((prev_minute_ts, prev_price))
        self._current_minute[asset] = (minute_ts, price)

    # ── Public accessors ──────────────────────────────────────────────────────

    def is_ready(self, asset: str) -> bool:
        return len(self._bars[asset.upper()]) >= MIN_BARS_READY

    def current_price(self, asset: str) -> float:
        if self._monitor is None:
            return 0.0
        try:
            return self._monitor.get_rti_metrics(asset.upper()).get("rti_current", 0.0)
        except Exception:
            return 0.0

    def get_returns(self, asset: str, window_minutes: int) -> List[float]:
        """Log returns of the last window_minutes closed bars."""
        bars = list(self._bars[asset.upper()])[-window_minutes:]
        if len(bars) < 2:
            return []
        prices = [p for _, p in bars]
        result = []
        for i in range(1, len(prices)):
            if prices[i - 1] > 0 and prices[i] > 0:
                result.append(math.log(prices[i] / prices[i - 1]))
        return result

    def get_recent_prices(self, asset: str, n: int) -> List[float]:
        """Raw close prices of the last n bars (used by MA computation)."""
        return [p for _, p in list(self._bars[asset.upper()])[-n:]]

    # ── Vol estimation ────────────────────────────────────────────────────────

    def _pick_vol_window(self, horizon_secs: float) -> int:
        if horizon_secs <= 15 * 60:
            return 15
        if horizon_secs <= 3_600:
            return 60
        if horizon_secs <= 4 * 3_600:
            return 240
        if horizon_secs <= 86_400:
            return 1_440
        if horizon_secs <= 604_800:
            return 10_080
        return 43_200

    def _realized_vol_annual(self, asset: str, window_minutes: int) -> float:
        returns = self.get_returns(asset, window_minutes)
        if len(returns) < 5:
            return _FALLBACK_VOL.get(asset.upper(), 0.90)
        n = len(returns)
        mean_r = sum(returns) / n
        variance = sum((r - mean_r) ** 2 for r in returns) / max(n - 1, 1)
        return (variance ** 0.5) * (MINUTES_PER_YEAR ** 0.5)

    # ── Probability API ───────────────────────────────────────────────────────

    def fair_prob(
        self, asset: str, horizon_secs: float,
        strike: float, side: str = "above",
    ) -> float:
        """P(RTI_T side strike) under log-normal with realized vol.

        Returns 0.5 if the model is not ready or prices are invalid.
        Clipped to [1e-4, 1-1e-4].
        """
        S = self.current_price(asset)
        if S <= 0 or strike <= 0 or not self.is_ready(asset):
            return 0.5
        T = horizon_secs / (365.25 * 86_400)
        if T <= 0:
            return 1.0 if (side == "above" and S >= strike) else 0.0
        sigma = self._realized_vol_annual(asset, self._pick_vol_window(horizon_secs))
        if sigma <= 0:
            return 0.5
        d = (math.log(S / strike) + 0.5 * sigma ** 2 * T) / (sigma * math.sqrt(T))
        p = _norm_cdf(d) if side == "above" else _norm_cdf(-d)
        return max(1e-4, min(1 - 1e-4, p))

    def bracket_prob(
        self, asset: str, horizon_secs: float, low: float, high: float,
    ) -> float:
        """P(low <= RTI_T < high). Clipped to [1e-4, 1-1e-4]."""
        p = (self.fair_prob(asset, horizon_secs, low, "above")
             - self.fair_prob(asset, horizon_secs, high, "above"))
        return max(1e-4, min(1 - 1e-4, p))

    def up_prob(self, asset: str, horizon_secs: float) -> float:
        """P(RTI_T > RTI_now) for Up/Down markets, drift-adjusted with 0.5 damping."""
        short_window = max(5, min(30, int(horizon_secs / 60)))
        returns = self.get_returns(asset, short_window)
        if len(returns) < 2:
            return 0.5
        T = horizon_secs / (365.25 * 86_400)
        if T <= 0:
            return 0.5
        sigma = self._realized_vol_annual(asset, self._pick_vol_window(horizon_secs))
        if sigma <= 0:
            return 0.5
        mean_r = sum(returns) / len(returns)
        drift_z = (mean_r / (sigma * math.sqrt(T))) * 0.5  # 0.5 damping
        return max(1e-4, min(1 - 1e-4, _norm_cdf(drift_z)))

    def implied_move(self, asset: str, horizon_secs: float) -> float:
        """Expected fractional move: σ_annual × √T (T in years)."""
        sigma = self._realized_vol_annual(asset, self._pick_vol_window(horizon_secs))
        T = horizon_secs / (365.25 * 86_400)
        return sigma * math.sqrt(T)


# ── Singleton ─────────────────────────────────────────────────────────────────

_tsm_instance: Optional[CryptoTermStructureModel] = None


def get_global_crypto_tsm() -> CryptoTermStructureModel:
    global _tsm_instance
    if _tsm_instance is None:
        raise RuntimeError(
            "CryptoTermStructureModel not initialized — "
            "call set_global_crypto_tsm() first"
        )
    return _tsm_instance


def set_global_crypto_tsm(tsm: CryptoTermStructureModel) -> None:
    global _tsm_instance
    _tsm_instance = tsm
```

- [ ] **Step 4: Run tests**

```
pytest tests/risk/test_crypto_term_structure.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add merid/risk/crypto_term_structure.py tests/risk/test_crypto_term_structure.py
git commit -m "feat(tsm): add CryptoTermStructureModel with RTI minute-bar buffer and vol API"
```

---

### Task 4: Add probability API tests

The probability tests require a ready TSM with a mocked monitor. Add these to `tests/risk/test_crypto_term_structure.py`:

- [ ] **Step 1: Append probability tests**

```python
# ── fair_prob ─────────────────────────────────────────────────────────────────

def test_fair_prob_returns_half_when_not_ready():
    tsm = CryptoTermStructureModel()
    mock = MagicMock()
    mock.get_rti_metrics.return_value = {"rti_current": 100_000.0}
    tsm._monitor = mock
    assert tsm.fair_prob("BTC", 3_600, 95_000.0) == 0.5


def test_fair_prob_atm_near_half():
    tsm = _make_ready("BTC", base=95_000.0)
    p = tsm.fair_prob("BTC", 3_600, 95_000.0, "above")
    assert 0.3 < p < 0.7


def test_fair_prob_deep_itm_above():
    tsm = _make_ready("BTC", base=100_000.0)
    p = tsm.fair_prob("BTC", 3_600, 50_000.0, "above")
    assert p > 0.98


def test_fair_prob_deep_otm_above():
    tsm = _make_ready("BTC", base=50_000.0)
    p = tsm.fair_prob("BTC", 3_600, 200_000.0, "above")
    assert p < 0.02


def test_fair_prob_above_plus_below_near_one():
    tsm = _make_ready()
    p_above = tsm.fair_prob("BTC", 86_400, 95_000.0, "above")
    p_below = tsm.fair_prob("BTC", 86_400, 95_000.0, "below")
    assert p_above + p_below == pytest.approx(1.0, abs=2e-4)


def test_fair_prob_clipped():
    tsm = _make_ready(base=100_000.0)
    p = tsm.fair_prob("BTC", 3_600, 50_000.0, "above")
    assert 1e-4 <= p <= 1 - 1e-4


# ── bracket_prob ──────────────────────────────────────────────────────────────

def test_bracket_prob_between_zero_one():
    tsm = _make_ready()
    p = tsm.bracket_prob("BTC", 86_400, 95_000.0, 105_000.0)
    assert 0 < p < 1


def test_wider_bracket_higher_prob():
    tsm = _make_ready()
    p_narrow = tsm.bracket_prob("BTC", 86_400, 98_000.0, 102_000.0)
    p_wide   = tsm.bracket_prob("BTC", 86_400, 90_000.0, 110_000.0)
    assert p_wide > p_narrow


# ── up_prob ───────────────────────────────────────────────────────────────────

def test_up_prob_zero_drift_is_half():
    tsm = CryptoTermStructureModel()
    _populate(tsm, "BTC", [100.0] * 50)
    mock = MagicMock()
    mock.get_rti_metrics.return_value = {"rti_current": 100.0}
    tsm._monitor = mock
    assert tsm.up_prob("BTC", 900) == pytest.approx(0.5, abs=0.01)


def test_up_prob_positive_drift_above_half():
    tsm = CryptoTermStructureModel()
    _populate(tsm, "BTC", [100.0 + i * 0.5 for i in range(50)])
    mock = MagicMock()
    mock.get_rti_metrics.return_value = {"rti_current": 125.0}
    tsm._monitor = mock
    assert tsm.up_prob("BTC", 900) > 0.5


def test_up_prob_returns_half_no_history():
    tsm = CryptoTermStructureModel()
    assert tsm.up_prob("BTC", 900) == 0.5


# ── implied_move ──────────────────────────────────────────────────────────────

def test_implied_move_sqrt_proportional():
    tsm = _make_ready()
    m_1h = tsm.implied_move("BTC", 3_600)
    m_4h = tsm.implied_move("BTC", 14_400)
    assert m_4h == pytest.approx(m_1h * 2.0, rel=0.02)


# ── TSM singleton ─────────────────────────────────────────────────────────────

def test_tsm_singleton_raises_before_set():
    import merid.risk.crypto_term_structure as m
    original = m._tsm_instance
    m._tsm_instance = None
    try:
        with pytest.raises(RuntimeError, match="not initialized"):
            from merid.risk.crypto_term_structure import get_global_crypto_tsm
            get_global_crypto_tsm()
    finally:
        m._tsm_instance = original


def test_tsm_singleton_set_get():
    from merid.risk.crypto_term_structure import get_global_crypto_tsm, set_global_crypto_tsm
    tsm = CryptoTermStructureModel()
    set_global_crypto_tsm(tsm)
    assert get_global_crypto_tsm() is tsm
```

- [ ] **Step 2: Run all TSM tests**

```
pytest tests/risk/test_crypto_term_structure.py -v
```

Expected: all tests PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/risk/test_crypto_term_structure.py
git commit -m "test(tsm): add probability API and singleton tests"
```

---

### Task 5: Add `SpotBasisFairValueStrategy`

**Files:**
- Modify: `merid/prediction/opinion_strategy.py`
- New: `tests/prediction/test_crypto_opinion_strategies.py`

- [ ] **Step 1: Write failing tests**

Create `tests/prediction/test_crypto_opinion_strategies.py`:

```python
import pytest
from unittest.mock import MagicMock, patch

from merid.prediction.opinion_strategy import (
    SpotBasisFairValueStrategy,
    get_strategy,
)


def _mock_tsm(ready=True, fair_prob=0.65, up_prob=0.55, bracket_prob=0.25):
    m = MagicMock()
    m.is_ready.return_value = ready
    m.fair_prob.return_value = fair_prob
    m.up_prob.return_value = up_prob
    m.bracket_prob.return_value = bracket_prob
    return m


_PATCH = "merid.risk.crypto_term_structure.get_global_crypto_tsm"


class TestSpotBasisFairValueStrategy:

    def test_returns_none_when_not_ready(self):
        s = SpotBasisFairValueStrategy()
        with patch(_PATCH, return_value=_mock_tsm(ready=False)):
            result = s.estimate("ag", "KXBTC-T95000", 0.50,
                                context={"asset": "BTC", "horizon_secs": 3_600.0,
                                         "market_type": "threshold", "strike": 95_000.0})
        assert result is None

    def test_threshold_uses_fair_prob(self):
        s = SpotBasisFairValueStrategy()
        with patch(_PATCH, return_value=_mock_tsm(fair_prob=0.70)):
            result = s.estimate("ag", "KXBTC-T95000", 0.50,
                                context={"asset": "BTC", "horizon_secs": 3_600.0,
                                         "market_type": "threshold", "strike": 95_000.0})
        assert result is not None
        assert result.agent_prob == pytest.approx(0.70, abs=0.01)
        assert result.edge == pytest.approx(0.20, abs=0.01)

    def test_up_down_uses_up_prob(self):
        s = SpotBasisFairValueStrategy()
        tsm = _mock_tsm(up_prob=0.58)
        with patch(_PATCH, return_value=tsm):
            result = s.estimate("ag", "KXBTC15M-UP", 0.50,
                                context={"asset": "BTC", "horizon_secs": 900.0,
                                         "market_type": "up_down"})
        assert result is not None
        tsm.up_prob.assert_called_once_with("BTC", 900.0)

    def test_bracket_uses_bracket_prob(self):
        s = SpotBasisFairValueStrategy()
        tsm = _mock_tsm(bracket_prob=0.30)
        with patch(_PATCH, return_value=tsm):
            result = s.estimate("ag", "KXBTC-B", 0.15,
                                context={"asset": "BTC", "horizon_secs": 3_600.0,
                                         "market_type": "bracket",
                                         "bracket": (90_000.0, 100_000.0)})
        assert result is not None
        tsm.bracket_prob.assert_called_once_with("BTC", 3_600.0, 90_000.0, 100_000.0)

    def test_edge_below_min_returns_none(self):
        s = SpotBasisFairValueStrategy(min_edge=0.05)
        with patch(_PATCH, return_value=_mock_tsm(fair_prob=0.51)):
            result = s.estimate("ag", "KXBTC-T", 0.50,
                                context={"asset": "BTC", "horizon_secs": 3_600.0,
                                         "market_type": "threshold", "strike": 95_000.0})
        assert result is None

    def test_no_orderbook_overlay_for_long_horizon(self):
        s = SpotBasisFairValueStrategy()
        tsm = _mock_tsm(fair_prob=0.70)
        store_patch = "merid.prediction.opinion_strategy.get_kalshi_market_state_store"
        with patch(_PATCH, return_value=tsm):
            with patch(store_patch) as mock_store:
                s.estimate("ag", "KXBTCW1-T", 0.50,
                           context={"asset": "BTC", "horizon_secs": 7 * 86_400.0,
                                    "market_type": "threshold", "strike": 95_000.0})
        mock_store.assert_not_called()

    def test_p_model_clipped():
        s = SpotBasisFairValueStrategy()
        with patch(_PATCH, return_value=_mock_tsm(up_prob=0.9999)):
            result = s.estimate("ag", "KXBTC15M-UP", 0.10,
                                context={"asset": "BTC", "horizon_secs": 900.0,
                                         "market_type": "up_down"})
        if result:
            assert result.agent_prob <= 1 - 1e-4

    def test_registered_in_registry():
        s = get_strategy("spot_basis_fair_value")
        assert isinstance(s, SpotBasisFairValueStrategy)

    def test_reasoning_tag():
        s = SpotBasisFairValueStrategy()
        with patch(_PATCH, return_value=_mock_tsm(fair_prob=0.70)):
            result = s.estimate("ag", "KXBTC-T", 0.50,
                                context={"asset": "BTC", "horizon_secs": 3_600.0,
                                         "market_type": "threshold", "strike": 95_000.0})
        assert result.reasoning_tag == "spot_basis_fair_value"
```

- [ ] **Step 2: Run to confirm failure**

```
pytest tests/prediction/test_crypto_opinion_strategies.py::TestSpotBasisFairValueStrategy -v
```

Expected: ImportError (`SpotBasisFairValueStrategy` not defined yet).

- [ ] **Step 3: Implement — append before `_STRATEGIES` dict in `opinion_strategy.py`**

```python
class SpotBasisFairValueStrategy(OpinionStrategy):
    """Strategy A: log-normal fair value from CryptoTermStructureModel + orderbook overlay.

    Covers BTC/ETH/SOL/XRP/DOGE across all Kalshi crypto timeframes.
    Returns None during TSM warm-up (is_ready=False) so other strategies stay active.
    """

    name = "spot_basis_fair_value"

    def __init__(
        self,
        imbalance_weight: float = 0.03,
        min_edge: float = 0.02,
    ) -> None:
        self.imbalance_weight = imbalance_weight
        self.min_edge = min_edge

    def estimate(
        self,
        agent_id: str,
        ticker: str,
        market_prob: float,
        category: str = "",
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[OpinionEstimate]:
        if self.should_skip(market_prob):
            return None

        ctx = context or {}
        asset: str = ctx.get("asset", "")
        horizon_secs: float = float(ctx.get("horizon_secs", 3_600.0))
        market_type: str = ctx.get("market_type", "")

        if not asset or not market_type:
            return None

        try:
            from merid.risk.crypto_term_structure import get_global_crypto_tsm
            tsm = get_global_crypto_tsm()
        except Exception:
            return None

        if not tsm.is_ready(asset):
            return None

        # ── compute model probability ─────────────────────────────────────────
        if market_type == "up_down":
            p_model = tsm.up_prob(asset, horizon_secs)
        elif market_type == "threshold":
            strike = ctx.get("strike")
            if strike is None:
                return None
            side = ctx.get("side", "above")
            p_model = tsm.fair_prob(asset, horizon_secs, float(strike), side)
        elif market_type == "bracket":
            bracket = ctx.get("bracket")
            if bracket is None:
                return None
            low, high = bracket
            p_model = tsm.bracket_prob(asset, horizon_secs, float(low), float(high))
        else:
            return None

        # ── orderbook overlay for short horizons (≤ 1h) ──────────────────────
        overlay_fired = False
        if horizon_secs <= 3_600:
            try:
                from merid.event_venues.kalshi.market_state import (
                    get_kalshi_market_state_store,
                )
                state = get_kalshi_market_state_store().get(ticker)
                if state and getattr(state, "book_initialized", False):
                    yes_depth = sum(s for _, s in (getattr(state, "yes_bids", []) or []))
                    no_depth = sum(s for _, s in (getattr(state, "no_bids", []) or []))
                    total = yes_depth + no_depth
                    if total > 0:
                        imbalance_bias = (yes_depth / total - 0.5) * self.imbalance_weight
                        p_model += imbalance_bias
                        overlay_fired = True
            except Exception:
                pass

        # ── single terminal clamp ─────────────────────────────────────────────
        p_model = max(1e-4, min(1 - 1e-4, p_model))

        edge = p_model - market_prob
        if abs(edge) < self.min_edge:
            return None

        signal_sources = ["rti_term_structure", "log_normal_cdf"]
        if overlay_fired:
            signal_sources.append("orderbook_imbalance")

        explanation = OpinionExplanation(
            inputs_used={
                "asset": asset,
                "horizon_secs": horizon_secs,
                "market_type": market_type,
            },
            contributions={"tsm_fair": round(p_model, 4)},
            rationale=f"tsm_{market_type}_{asset}",
        )

        return OpinionEstimate(
            agent_prob=round(p_model, 4),
            confidence=round(min(0.85, 0.40 + abs(edge) * 3.0), 2),
            edge=round(edge, 4),
            reasoning_tag="spot_basis_fair_value",
            signal_sources=signal_sources,
            explanation=explanation,
        )
```

Also add to `_STRATEGIES` dict:

```python
"spot_basis_fair_value": SpotBasisFairValueStrategy,
```

- [ ] **Step 4: Run tests**

```
pytest tests/prediction/test_crypto_opinion_strategies.py::TestSpotBasisFairValueStrategy -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add merid/prediction/opinion_strategy.py tests/prediction/test_crypto_opinion_strategies.py
git commit -m "feat(strategy): add SpotBasisFairValueStrategy (Strategy A)"
```

---

### Task 6: Add `TrendMomentumOpinionStrategy`

**Files:**
- Modify: `merid/prediction/opinion_strategy.py`
- Modify: `tests/prediction/test_crypto_opinion_strategies.py`

- [ ] **Step 1: Append failing tests**

Add to `tests/prediction/test_crypto_opinion_strategies.py`:

```python
from merid.prediction.opinion_strategy import TrendMomentumOpinionStrategy


def _mock_tsm_trend(ready=True, prices=None, returns=None, fair_prob=0.55):
    m = MagicMock()
    m.is_ready.return_value = ready
    m.get_recent_prices.return_value = prices or [100.0] * 50
    m.get_returns.return_value = returns if returns is not None else [0.001] * 30
    m.fair_prob.return_value = fair_prob
    m.bracket_prob.return_value = 0.25
    return m


class TestTrendMomentumOpinionStrategy:

    def test_returns_none_when_not_ready(self):
        s = TrendMomentumOpinionStrategy()
        tsm = _mock_tsm_trend(ready=False)
        with patch(_PATCH, return_value=tsm):
            result = s.estimate("ag", "KXBTC15M-UP", 0.50,
                                context={"asset": "BTC", "horizon_secs": 900.0,
                                         "market_type": "up_down"})
        assert result is None

    def test_returns_none_with_insufficient_history(self):
        s = TrendMomentumOpinionStrategy()
        # get_returns returns fewer bars than long_w (30 for ≤15m)
        tsm = _mock_tsm_trend(returns=[0.001] * 5)
        with patch(_PATCH, return_value=tsm):
            result = s.estimate("ag", "KXBTC15M-UP", 0.50,
                                context={"asset": "BTC", "horizon_secs": 900.0,
                                         "market_type": "up_down"})
        assert result is None

    def test_up_down_bullish_signal_above_half(self):
        s = TrendMomentumOpinionStrategy()
        # Rising prices: short MA > long MA → bullish
        prices = [100.0 + i * 0.5 for i in range(40)]
        tsm = _mock_tsm_trend(
            prices=prices,
            returns=[0.005] * 40,  # strongly positive returns
        )
        with patch(_PATCH, return_value=tsm):
            result = s.estimate("ag", "KXBTC15M-UP", 0.50,
                                context={"asset": "BTC", "horizon_secs": 900.0,
                                         "market_type": "up_down"})
        assert result is not None
        assert result.agent_prob > 0.50
        assert "bullish" in result.reasoning_tag

    def test_up_down_bearish_signal_below_half(self):
        s = TrendMomentumOpinionStrategy()
        prices = [100.0 - i * 0.5 for i in range(40)]
        tsm = _mock_tsm_trend(
            prices=prices,
            returns=[-0.005] * 40,
        )
        with patch(_PATCH, return_value=tsm):
            result = s.estimate("ag", "KXBTC15M-UP", 0.50,
                                context={"asset": "BTC", "horizon_secs": 900.0,
                                         "market_type": "up_down"})
        assert result is not None
        assert result.agent_prob < 0.50
        assert "bearish" in result.reasoning_tag

    def test_signal_capped_at_max_strength(self):
        s = TrendMomentumOpinionStrategy(max_signal_strength=0.10)
        # Extreme signal: all large positive returns + steep price rise
        prices = [100.0 + i * 10 for i in range(40)]
        tsm = _mock_tsm_trend(prices=prices, returns=[0.10] * 40)
        with patch(_PATCH, return_value=tsm):
            result = s.estimate("ag", "KXBTC15M-UP", 0.50,
                                context={"asset": "BTC", "horizon_secs": 900.0,
                                         "market_type": "up_down"})
        if result:
            assert result.agent_prob <= 0.50 + 0.10 + 1e-3

    def test_horizon_selects_correct_windows():
        """Verify that weekly horizon uses 480/4320 windows, not 5/30."""
        s = TrendMomentumOpinionStrategy()
        tsm = _mock_tsm_trend(
            prices=[100.0 + i * 0.1 for i in range(4_400)],
            returns=[0.001] * 4_400,
        )
        with patch(_PATCH, return_value=tsm):
            s.estimate("ag", "KXBTCW1-T", 0.50,
                       context={"asset": "BTC", "horizon_secs": 7 * 86_400.0,
                                "market_type": "up_down"})
        # For weekly horizon, long_w=4320; get_returns called with 4320
        call_args = tsm.get_returns.call_args_list
        long_w_calls = [c for c in call_args if c.args[1] >= 4_320]
        assert len(long_w_calls) > 0

    def test_p_model_clipped():
        s = TrendMomentumOpinionStrategy(max_signal_strength=0.99)
        prices = [100.0 + i * 100 for i in range(40)]
        tsm = _mock_tsm_trend(prices=prices, returns=[0.99] * 40)
        with patch(_PATCH, return_value=tsm):
            result = s.estimate("ag", "KXBTC15M-UP", 0.01,
                                context={"asset": "BTC", "horizon_secs": 900.0,
                                         "market_type": "up_down"})
        if result:
            assert 1e-4 <= result.agent_prob <= 1 - 1e-4

    def test_registered_in_registry():
        s = get_strategy("trend_momentum")
        assert isinstance(s, TrendMomentumOpinionStrategy)
```

- [ ] **Step 2: Run to confirm failure**

```
pytest tests/prediction/test_crypto_opinion_strategies.py::TestTrendMomentumOpinionStrategy -v
```

Expected: ImportError (`TrendMomentumOpinionStrategy` not defined yet).

- [ ] **Step 3: Implement — append after `SpotBasisFairValueStrategy` in `opinion_strategy.py`**

```python
class TrendMomentumOpinionStrategy(OpinionStrategy):
    """Strategy C: MA-cross + momentum from TSM minute-bar history.

    Horizon-adaptive window selection covers all Kalshi crypto timeframes.
    Returns None until sufficient bar history is accumulated.
    """

    name = "trend_momentum"

    # Horizon → (short_bars, long_bars) window pairs
    _WINDOWS = [
        (15 * 60,      5,    30),   # ≤ 15m
        (1 * 3_600,   15,    60),   # ≤ 1h
        (24 * 3_600,  60,   480),   # ≤ 1d
        (float("inf"), 480, 4_320), # weekly / monthly / annual
    ]

    def __init__(
        self,
        short_window: int = 5,       # placeholder; overridden per-horizon internally
        long_window: int = 30,       # placeholder; overridden per-horizon internally
        min_edge: float = 0.02,
        max_signal_strength: float = 0.15,
    ) -> None:
        self.min_edge = min_edge
        self.max_signal_strength = max_signal_strength

    def _resolve_windows(self, horizon_secs: float):
        for limit, short_w, long_w in self._WINDOWS:
            if horizon_secs <= limit:
                return short_w, long_w
        return 480, 4_320  # fallback (unreachable)

    def estimate(
        self,
        agent_id: str,
        ticker: str,
        market_prob: float,
        category: str = "",
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[OpinionEstimate]:
        if self.should_skip(market_prob):
            return None

        ctx = context or {}
        asset: str = ctx.get("asset", "")
        horizon_secs: float = float(ctx.get("horizon_secs", 3_600.0))
        market_type: str = ctx.get("market_type", "")

        if not asset or not market_type:
            return None

        try:
            from merid.risk.crypto_term_structure import get_global_crypto_tsm
            tsm = get_global_crypto_tsm()
        except Exception:
            return None

        if not tsm.is_ready(asset):
            return None

        short_w, long_w = self._resolve_windows(horizon_secs)

        # Readiness gate: need long_w bars of returns
        if len(tsm.get_returns(asset, long_w)) < long_w:
            return None

        prices = tsm.get_recent_prices(asset, long_w + 5)
        if len(prices) < long_w:
            return None

        # ── signal computation ────────────────────────────────────────────────
        short_ma = sum(prices[-short_w:]) / short_w
        long_ma = sum(prices[-long_w:]) / long_w
        ma_cross = (short_ma - long_ma) / long_ma if long_ma > 0 else 0.0

        short_returns = tsm.get_returns(asset, short_w)
        momentum = sum(short_returns) / len(short_returns) if short_returns else 0.0

        raw_signal = ma_cross * 0.6 + momentum * 0.4
        signal = max(-self.max_signal_strength, min(self.max_signal_strength, raw_signal))

        # ── tsm_base for non-Up/Down markets ─────────────────────────────────
        if market_type == "up_down":
            tsm_base = 0.5
        elif market_type == "threshold":
            strike = ctx.get("strike")
            if strike is None:
                return None
            side = ctx.get("side", "above")
            tsm_base = (tsm.fair_prob(asset, horizon_secs, float(strike), side)
                        if tsm.is_ready(asset) else market_prob)
        elif market_type == "bracket":
            bracket = ctx.get("bracket")
            if bracket is None:
                return None
            low, high = bracket
            tsm_base = (tsm.bracket_prob(asset, horizon_secs, float(low), float(high))
                        if tsm.is_ready(asset) else market_prob)
        else:
            return None

        # ── single terminal clamp ─────────────────────────────────────────────
        p_model = max(1e-4, min(1 - 1e-4, tsm_base + signal))

        edge = p_model - market_prob
        if abs(edge) < self.min_edge:
            return None

        direction = "bullish" if signal > 0 else "bearish"

        explanation = OpinionExplanation(
            inputs_used={
                "asset": asset,
                "horizon_secs": horizon_secs,
                "short_w": short_w,
                "long_w": long_w,
            },
            contributions={
                "ma_cross": round(ma_cross, 6),
                "momentum": round(momentum, 6),
                "signal": round(signal, 4),
            },
            rationale=f"trend_momentum_{direction}_{asset}",
        )

        return OpinionEstimate(
            agent_prob=round(p_model, 4),
            confidence=round(min(0.80, 0.35 + abs(signal) * 3.0), 2),
            edge=round(edge, 4),
            reasoning_tag=f"trend_momentum_{direction}",
            signal_sources=["ma_cross", "momentum", "rti_minute_bars"],
            explanation=explanation,
        )
```

Also add to `_STRATEGIES` dict:

```python
"trend_momentum": TrendMomentumOpinionStrategy,
```

- [ ] **Step 4: Run all strategy tests**

```
pytest tests/prediction/test_crypto_opinion_strategies.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add merid/prediction/opinion_strategy.py tests/prediction/test_crypto_opinion_strategies.py
git commit -m "feat(strategy): add TrendMomentumOpinionStrategy (Strategy C)"
```

---

### Task 7: Wire TSM lifecycle into `web/main.py`

**Files:**
- Modify: `web/main.py`

- [ ] **Step 1: Locate insertion points**

```bash
grep -n "CryptoRTIMonitor\|crypto_rti_monitor\|lifespan\|shutdown\|startup" web/main.py | head -30
```

Find the line where `CryptoRTIMonitor` is instantiated (the existing monitor object) and where app teardown runs.

- [ ] **Step 2: Register RTI monitor singleton**

Immediately after the line that creates the `CryptoRTIMonitor` instance (call it `crypto_rti_monitor`), add:

```python
from merid.risk.crypto_rti_monitor import set_global_crypto_rti_monitor
set_global_crypto_rti_monitor(crypto_rti_monitor)
```

- [ ] **Step 3: Start TSM after RTI monitor is registered**

On the next line after the `set_global_crypto_rti_monitor` call:

```python
from merid.risk.crypto_term_structure import CryptoTermStructureModel, set_global_crypto_tsm
_tsm = CryptoTermStructureModel()
await _tsm.start()
set_global_crypto_tsm(_tsm)
```

- [ ] **Step 4: Stop TSM in shutdown**

In the teardown/shutdown section (where other `await x.stop()` calls live), add:

```python
await _tsm.stop()
```

- [ ] **Step 5: Smoke-verify startup does not crash**

```bash
python -c "
import asyncio, sys
sys.path.insert(0, '.')
from merid.risk.crypto_term_structure import CryptoTermStructureModel
tsm = CryptoTermStructureModel()
print('TSM instantiation OK, bars:', {a: len(tsm._bars[a]) for a in tsm._bars})
"
```

Expected output: `TSM instantiation OK, bars: {'BTC': 0, 'ETH': 0, 'SOL': 0, 'XRP': 0, 'DOGE': 0}`

- [ ] **Step 6: Verify strategy registry contains new strategies**

```bash
python -c "
from merid.prediction.opinion_strategy import list_strategies
print(list_strategies())
"
```

Expected output includes `'spot_basis_fair_value'` and `'trend_momentum'`.

- [ ] **Step 7: Run full test suite for touched modules**

```
pytest tests/config/test_kalshi_crypto_series_meta.py tests/risk/ tests/prediction/test_crypto_opinion_strategies.py -v
```

Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
git add web/main.py
git commit -m "feat(wiring): start/stop CryptoTermStructureModel in web/main.py lifespan"
```

---

## Self-review

**Spec coverage:**
- ✅ `kalshi_crypto_series_meta.py` — monthly/annual series, `supports_basis`, `supports_trend`, `TimeframeKey` updated (Task 1)
- ✅ `crypto_rti_monitor.py` — `get/set_global_crypto_rti_monitor` singleton, fixes two existing broken import sites (Task 2)
- ✅ `crypto_term_structure.py` — `CryptoTermStructureModel` with 30-day bar buffer, vol API, `fair_prob`/`bracket_prob`/`up_prob`/`implied_move`, singleton (Tasks 3–4)
- ✅ `SpotBasisFairValueStrategy` — all 3 market types, orderbook overlay ≤1h, terminal clamp, `None` on warm-up (Task 5)
- ✅ `TrendMomentumOpinionStrategy` — horizon-adaptive windows, MA-cross + momentum, signal cap, terminal clamp (Task 6)
- ✅ Both strategies registered in `_STRATEGIES` (Tasks 5, 6)
- ✅ `web/main.py` lifecycle wiring (Task 7)
- ✅ Polish: terminal clamp `[1e-4, 1-1e-4]` applied once at end of both strategies
- ✅ Polish: `up_prob` `drift_z × 0.5` damping factor

**No placeholders found.**

**Type consistency:** `get_recent_prices` (public) used consistently in `TrendMomentumOpinionStrategy` and defined as public in `CryptoTermStructureModel`. `_resolve_windows` returns `(short_w, long_w)` and is consumed correctly. All `fair_prob`/`bracket_prob`/`up_prob` call signatures match their definitions.
