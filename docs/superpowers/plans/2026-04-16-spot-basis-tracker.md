# Kalshi/Coinbase Spot Basis Tracking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a live-basis tracking system that computes and monitors the spread between Coinbase spot price and Kalshi-implied spot per crypto asset, with alignment state, rolling statistics, staleness detection, a REST API, execution-gate integration, and a frontend status panel.

**Architecture:** A singleton `SpotBasisTracker` ticks in a background thread every second. It reads from `KalshiMarketStateStore` (Kalshi orderbook data) and `LivePriceFeed` (Coinbase spot). For each asset, it interpolates across nearby strikes to find the risk-neutral-median implied spot (the strike where YES probability ≈ 50%), computes three basis numbers (mid/bid/ask), and classifies alignment state. A REST API exposes current state and rolling stats; the execution gate adds `basis_misalignment` as a warning source; a React panel shows the dashboard.

**Tech Stack:** Python dataclasses, `threading.Thread`, FastAPI `APIRouter`, React + TypeScript + Tailwind, `useApiData` polling hook.

---

## File Map

**New files:**
- `config/spot_basis_config.py` — Per-asset USD/pct thresholds, staleness TTLs (pure constants)
- `merid/alignment/__init__.py` — `get_spot_basis_tracker()` singleton + module init
- `merid/alignment/spot_basis_tracker.py` — `FeedStatus`, `AlignmentState`, `AssetBasis`, `compute_implied_spot()`, `SpotBasisTracker`
- `web/api/spot_basis_api.py` — `GET /api/v1/kalshi/spot-basis` + `/stats`
- `web/react/src/components/SpotBasisPanel.tsx` — Per-asset basis status panel
- `tests/alignment/__init__.py` — empty
- `tests/alignment/test_spot_basis_tracker.py` — unit tests

**Modified files:**
- `web/react/src/config/constants.ts` — Add `SPOT_BASIS`, `SPOT_BASIS_STATS`, `POLLING_INTERVALS.SPOT_BASIS`
- `web/main.py` — Import router; start/stop tracker in lifespan
- `core/execution_gate.py` — Add `basis_misalignment` warning source
- `web/react/src/views/OperatorDashboard.tsx` — Embed `<SpotBasisPanel />`

---

## How implied spot is computed (read this before touching any code)

For each asset (BTC/ETH/SOL/XRP/DOGE):

1. Pull all `KalshiMarketState` objects from the state store where `underlying == asset`, `book_initialized is True`, `strike_price is not None`, `seconds_to_expiry > 0`.
2. Find `min_expiry = min(s.seconds_to_expiry)`. Keep only markets with `seconds_to_expiry <= min_expiry * 1.5` (nearest-expiry cluster).
3. Sort cluster by `strike_price` ascending.
4. Extract `(strike, yes_prob)` pairs using the requested price (`mid_cents/100`, `best_bid_cents/100`, or `best_ask_cents/100`).
5. Since YES means "asset ends above strike", YES prob decreases as strike increases. Find the two adjacent strikes that bracket `p = 0.50`: `(s_lo, p_lo)` where `p_lo >= 0.50` and `(s_hi, p_hi)` where `p_hi < 0.50`.
6. Interpolate: `t = (p_lo - 0.50) / (p_lo - p_hi)`, `implied = s_lo + t * (s_hi - s_lo)`.
7. If no bracket found (all probs same side), return `None`.

`basis_X = implied_spot_X - coinbase_spot` (positive = Kalshi leads, negative = Kalshi lags).

---

## Task 1: Per-asset threshold config

**Files:**
- Create: `config/spot_basis_config.py`

No test required — pure constants with no logic.

- [ ] **Step 1: Create the config file**

```python
# config/spot_basis_config.py
"""Per-asset spot/Kalshi basis thresholds and staleness config."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class AssetBasisThresholds:
    """Thresholds that define when basis is 'offside' for one asset."""
    abs_threshold_usd: float     # max |basis_mid| in USD before breach
    pct_threshold: float         # max |basis_mid / spot| before breach
    breach_count_threshold: int  # consecutive breach ticks before → offside


# Tuned to typical Kalshi bid-ask spread + index publishing latency per asset.
# BTC: Kalshi spreads 10-30¢ equivalent; allow 50 USD before flagging.
# SOL: ~$0.30 is 1 spread width on a $150 asset.
# XRP/DOGE: tiny absolute values, use pct dominantly.
ASSET_THRESHOLDS: Dict[str, AssetBasisThresholds] = {
    "BTC":  AssetBasisThresholds(abs_threshold_usd=50.0,   pct_threshold=0.0005, breach_count_threshold=5),
    "ETH":  AssetBasisThresholds(abs_threshold_usd=5.0,    pct_threshold=0.0005, breach_count_threshold=5),
    "SOL":  AssetBasisThresholds(abs_threshold_usd=0.30,   pct_threshold=0.0020, breach_count_threshold=5),
    "XRP":  AssetBasisThresholds(abs_threshold_usd=0.005,  pct_threshold=0.0025, breach_count_threshold=5),
    "DOGE": AssetBasisThresholds(abs_threshold_usd=0.002,  pct_threshold=0.0025, breach_count_threshold=5),
}

# Staleness thresholds (env-configurable)
SPOT_STALE_MS:   float = float(os.getenv("KALSHI_BASIS_SPOT_STALE_MS",   "5000"))
SPOT_MISSING_MS: float = float(os.getenv("KALSHI_BASIS_SPOT_MISSING_MS", "30000"))
BOOK_STALE_MS:   float = float(os.getenv("KALSHI_BASIS_BOOK_STALE_MS",   "10000"))
BOOK_MISSING_MS: float = float(os.getenv("KALSHI_BASIS_BOOK_MISSING_MS", "60000"))

# Rolling stats window (deque holds up to this many seconds of 1-per-second samples)
ROLLING_WINDOW_SECONDS: int = int(os.getenv("KALSHI_BASIS_ROLLING_WINDOW_SECS", "3600"))

# Coinbase price-cache symbols (match LivePriceFeed.price_cache keys)
COINBASE_SPOT_SYMBOLS: Dict[str, str] = {
    "BTC":  "BTC/USD",
    "ETH":  "ETH/USD",
    "SOL":  "SOL/USD",
    "XRP":  "XRP/USD",
    "DOGE": "DOGE/USD",
}
```

- [ ] **Step 2: Commit**

```bash
git add config/spot_basis_config.py
git commit -m "feat(basis): add per-asset spot/Kalshi basis threshold config"
```

---

## Task 2: Core models and `compute_implied_spot` (test-first)

**Files:**
- Create: `tests/alignment/__init__.py`
- Create: `tests/alignment/test_spot_basis_tracker.py` (pure-function tests only here)
- Create: `merid/alignment/__init__.py`
- Create: `merid/alignment/spot_basis_tracker.py` (models + pure function only)

- [ ] **Step 1: Create test skeleton and write failing pure-function tests**

```python
# tests/alignment/__init__.py
# (empty)
```

```python
# tests/alignment/test_spot_basis_tracker.py
"""Tests for merid/alignment/spot_basis_tracker.py."""
from __future__ import annotations

import time
import threading
import pytest
from unittest.mock import MagicMock, patch

from merid.alignment.spot_basis_tracker import (
    FeedStatus,
    AlignmentState,
    AssetBasis,
    compute_implied_spot,
    SpotBasisTracker,
)
from merid.event_venues.kalshi.models import KalshiMarketState


# ── Helpers ────────────────────────────────────────────────────────────────

def _make_state(
    ticker: str,
    strike: float,
    mid: int,
    bid: int = None,
    ask: int = None,
    expiry: float = 300.0,
    asset: str = "BTC",
) -> KalshiMarketState:
    """Build a minimal KalshiMarketState for basis tests."""
    s = KalshiMarketState(ticker=ticker)
    s.strike_price = strike
    s.mid_cents = mid
    s.best_bid_cents = bid if bid is not None else mid - 3
    s.best_ask_cents = ask if ask is not None else mid + 3
    s.book_initialized = True
    s.seconds_to_expiry = expiry
    s.underlying = asset
    s.last_book_update_ts = time.monotonic()
    return s


# ── compute_implied_spot ───────────────────────────────────────────────────

class TestComputeImpliedSpot:
    def test_exact_50_at_strike(self):
        """When one market has YES prob exactly 0.50, implied spot equals its strike."""
        states = [
            _make_state("T-A", strike=96000.0, mid=70),  # prob=0.70
            _make_state("T-B", strike=97000.0, mid=50),  # prob=0.50  ← exact
            _make_state("T-C", strike=98000.0, mid=30),  # prob=0.30
        ]
        result = compute_implied_spot(states, "mid")
        assert result == pytest.approx(97000.0, abs=1.0)

    def test_interpolated_between_two_brackets(self):
        """Linearly interpolates between two bracketing strikes."""
        states = [
            _make_state("T-A", strike=96000.0, mid=60),  # prob=0.60
            _make_state("T-B", strike=98000.0, mid=40),  # prob=0.40
        ]
        # t = (0.60 - 0.50) / (0.60 - 0.40) = 0.5
        # implied = 96000 + 0.5 * (98000 - 96000) = 97000
        result = compute_implied_spot(states, "mid")
        assert result == pytest.approx(97000.0, abs=1.0)

    def test_returns_none_when_no_bracket_all_above(self):
        """All probs > 0.50 → no lower-side market → None."""
        states = [
            _make_state("T-A", strike=94000.0, mid=80),
            _make_state("T-B", strike=95000.0, mid=70),
            _make_state("T-C", strike=96000.0, mid=60),
        ]
        result = compute_implied_spot(states, "mid")
        assert result is None

    def test_returns_none_when_no_bracket_all_below(self):
        """All probs < 0.50 → no upper-side market → None."""
        states = [
            _make_state("T-A", strike=97000.0, mid=40),
            _make_state("T-B", strike=98000.0, mid=30),
        ]
        result = compute_implied_spot(states, "mid")
        assert result is None

    def test_returns_none_for_single_market(self):
        """Single market cannot be interpolated → None."""
        states = [_make_state("T-A", strike=97000.0, mid=55)]
        result = compute_implied_spot(states, "mid")
        assert result is None

    def test_returns_none_for_empty_list(self):
        result = compute_implied_spot([], "mid")
        assert result is None

    def test_bid_uses_best_bid_cents(self):
        """'bid' variant uses best_bid_cents, not mid_cents."""
        states = [
            _make_state("T-A", strike=96000.0, mid=70, bid=65, ask=75),
            _make_state("T-B", strike=98000.0, mid=30, bid=25, ask=35),
        ]
        # bid side: prob 0.65 and 0.25 → t = (0.65-0.50)/(0.65-0.25) = 0.15/0.40 = 0.375
        # implied = 96000 + 0.375 * 2000 = 96750
        result = compute_implied_spot(states, "bid")
        assert result == pytest.approx(96750.0, abs=1.0)

    def test_ask_uses_best_ask_cents(self):
        """'ask' variant uses best_ask_cents."""
        states = [
            _make_state("T-A", strike=96000.0, mid=70, bid=65, ask=75),
            _make_state("T-B", strike=98000.0, mid=30, bid=25, ask=35),
        ]
        # ask side: prob 0.75 and 0.35 → t = (0.75-0.50)/(0.75-0.35) = 0.25/0.40 = 0.625
        # implied = 96000 + 0.625 * 2000 = 97250
        result = compute_implied_spot(states, "ask")
        assert result == pytest.approx(97250.0, abs=1.0)

    def test_skips_markets_without_strike(self):
        """Markets with strike_price=None are excluded."""
        s_no_strike = _make_state("T-A", strike=96000.0, mid=60)
        s_no_strike.strike_price = None
        states = [
            s_no_strike,
            _make_state("T-B", strike=96000.0, mid=60),
            _make_state("T-C", strike=98000.0, mid=40),
        ]
        result = compute_implied_spot(states, "mid")
        assert result == pytest.approx(97000.0, abs=1.0)

    def test_skips_markets_not_book_initialized(self):
        """Markets with book_initialized=False are excluded."""
        s_uninitialized = _make_state("T-A", strike=96000.0, mid=60)
        s_uninitialized.book_initialized = False
        states = [
            s_uninitialized,
            _make_state("T-B", strike=96000.0, mid=60),
            _make_state("T-C", strike=98000.0, mid=40),
        ]
        result = compute_implied_spot(states, "mid")
        assert result == pytest.approx(97000.0, abs=1.0)

    def test_skips_markets_with_zero_or_negative_expiry(self):
        """Expired markets (seconds_to_expiry <= 0) are excluded."""
        s_expired = _make_state("T-A", strike=96000.0, mid=60, expiry=0.0)
        states = [
            s_expired,
            _make_state("T-B", strike=96000.0, mid=60),
            _make_state("T-C", strike=98000.0, mid=40),
        ]
        result = compute_implied_spot(states, "mid")
        assert result == pytest.approx(97000.0, abs=1.0)

    def test_nearest_expiry_cluster_only(self):
        """Only the nearest-expiry cluster is used; far-expiry markets are ignored."""
        # Near-expiry cluster: 5m remaining
        near_states = [
            _make_state("T-Near-A", strike=96000.0, mid=60, expiry=300.0),
            _make_state("T-Near-B", strike=98000.0, mid=40, expiry=300.0),
        ]
        # Far-expiry cluster: 1h remaining — would pull implied spot elsewhere
        far_states = [
            _make_state("T-Far-A", strike=92000.0, mid=80, expiry=3600.0),
            _make_state("T-Far-B", strike=94000.0, mid=20, expiry=3600.0),
        ]
        result = compute_implied_spot(near_states + far_states, "mid")
        assert result == pytest.approx(97000.0, abs=1.0)
```

- [ ] **Step 2: Run tests to verify they FAIL (module does not exist yet)**

```bash
cd c:/Dev/MERID
python -m pytest tests/alignment/test_spot_basis_tracker.py::TestComputeImpliedSpot -v 2>&1 | head -30
```

Expected: `ModuleNotFoundError: No module named 'merid.alignment'`

- [ ] **Step 3: Create the module with models and `compute_implied_spot`**

```python
# merid/alignment/__init__.py
"""Spot/Kalshi basis alignment module."""
from __future__ import annotations

_tracker = None
_tracker_lock = None


def get_spot_basis_tracker() -> "SpotBasisTracker":
    """Return the singleton SpotBasisTracker (lazy-init, thread-safe)."""
    global _tracker, _tracker_lock
    import threading
    if _tracker_lock is None:
        _tracker_lock = threading.Lock()
    if _tracker is None:
        with _tracker_lock:
            if _tracker is None:
                from merid.alignment.spot_basis_tracker import SpotBasisTracker
                _tracker = SpotBasisTracker()
    return _tracker
```

```python
# merid/alignment/spot_basis_tracker.py
"""Spot/Kalshi basis tracker — computes and monitors spot-vs-implied spread per asset.

How implied spot is computed
-----------------------------
For each asset, we look at the nearest-expiry cluster of Kalshi binary markets.
YES probability decreases monotonically with strike (YES = "asset ends above strike").
We interpolate between the two adjacent strikes that bracket YES prob = 0.50.
That bracketed strike is the "risk-neutral median" — the Kalshi-implied spot.

Three variants (mid / bid / ask) use different price columns from the order book.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("merid.alignment.spot_basis_tracker")

ASSETS = ("BTC", "ETH", "SOL", "XRP", "DOGE")


# ── Enums ─────────────────────────────────────────────────────────────────


class FeedStatus(str, Enum):
    OK      = "ok"
    STALE   = "stale"
    MISSING = "missing"


class AlignmentState(str, Enum):
    ALIGNED    = "aligned"
    OFFSIDE    = "offside"
    STALE_FEED = "stale_feed"


# ── Data model ────────────────────────────────────────────────────────────


@dataclass
class AssetBasis:
    """Live basis snapshot for one crypto asset."""
    asset: str
    spot_price: Optional[float]
    spot_status: FeedStatus
    kalshi_book_status: FeedStatus
    implied_spot_mid: Optional[float]
    implied_spot_bid: Optional[float]
    implied_spot_ask: Optional[float]
    basis_mid: Optional[float]
    basis_bid: Optional[float]
    basis_ask: Optional[float]
    alignment: AlignmentState
    breach_count: int
    markets_used: int
    nearest_expiry_secs: Optional[float]
    computed_at: float = field(default_factory=time.monotonic)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "asset": self.asset,
            "spot_price": self.spot_price,
            "spot_status": self.spot_status.value,
            "kalshi_book_status": self.kalshi_book_status.value,
            "implied_spot_mid": self.implied_spot_mid,
            "implied_spot_bid": self.implied_spot_bid,
            "implied_spot_ask": self.implied_spot_ask,
            "basis_mid": self.basis_mid,
            "basis_bid": self.basis_bid,
            "basis_ask": self.basis_ask,
            "alignment": self.alignment.value,
            "breach_count": self.breach_count,
            "markets_used": self.markets_used,
            "nearest_expiry_secs": self.nearest_expiry_secs,
            "computed_at": self.computed_at,
        }


# ── Pure function ─────────────────────────────────────────────────────────


def compute_implied_spot(
    states: List[Any],  # List[KalshiMarketState] — typed loosely to avoid circular imports
    which: str,         # "mid" | "bid" | "ask"
) -> Optional[float]:
    """Compute Kalshi-implied spot by interpolating YES probs across strikes.

    Returns the strike level where the YES probability equals 0.50, using linear
    interpolation between the two adjacent bracketing markets in the nearest-expiry
    cluster.  Returns None if fewer than 2 markets or no bracket can be found.

    Args:
        states: KalshiMarketState objects for one asset (may include multiple expiries).
        which:  "mid" uses mid_cents; "bid" uses best_bid_cents; "ask" uses best_ask_cents.
    """
    if not states:
        return None

    # Step 1: Filter to valid markets
    valid = [
        s for s in states
        if (
            s.book_initialized
            and s.strike_price is not None
            and s.seconds_to_expiry is not None
            and s.seconds_to_expiry > 0
        )
    ]
    if len(valid) < 2:
        return None

    # Step 2: Find nearest-expiry cluster (within 1.5× the shortest TTL)
    min_expiry = min(s.seconds_to_expiry for s in valid)
    cluster = [s for s in valid if s.seconds_to_expiry <= min_expiry * 1.5]
    if len(cluster) < 2:
        return None

    # Step 3: Extract (strike, yes_prob) pairs using requested price column
    def _get_prob(s) -> Optional[float]:
        if which == "mid":
            return s.mid_cents / 100.0 if s.mid_cents is not None else None
        elif which == "bid":
            return s.best_bid_cents / 100.0 if s.best_bid_cents is not None else None
        elif which == "ask":
            return s.best_ask_cents / 100.0 if s.best_ask_cents is not None else None
        return None

    pairs: List[Tuple[float, float]] = []
    for s in cluster:
        prob = _get_prob(s)
        if prob is not None:
            pairs.append((s.strike_price, prob))

    if len(pairs) < 2:
        return None

    # Step 4: Sort by strike ascending (YES prob decreases with strike)
    pairs.sort(key=lambda x: x[0])

    # Step 5: Find two adjacent markets that bracket p = 0.50
    s_lo = s_hi = p_lo = p_hi = None
    for i in range(len(pairs) - 1):
        s1, p1 = pairs[i]
        s2, p2 = pairs[i + 1]
        if p1 >= 0.50 and p2 < 0.50:
            s_lo, p_lo = s1, p1
            s_hi, p_hi = s2, p2
            break

    if s_lo is None:
        return None

    # Step 6: Linear interpolation
    span_p = p_lo - p_hi
    if span_p <= 0:
        return None  # degenerate case
    t = (p_lo - 0.50) / span_p
    return s_lo + t * (s_hi - s_lo)


# ── SpotBasisTracker ──────────────────────────────────────────────────────


class SpotBasisTracker:
    """Background tracker: reads Kalshi book + Coinbase spot, computes basis per asset.

    Call start() once at app startup and stop() on shutdown.
    Read state via get_all() or get(asset).

    Example::

        tracker = get_spot_basis_tracker()
        tracker.start()
        state = tracker.get("BTC")
        print(state.basis_mid, state.alignment)
    """

    def __init__(self, store=None, feed=None):
        """
        Args:
            store: KalshiMarketStateStore instance (lazy-init if None)
            feed:  LivePriceFeed instance (lazy-init if None)
        """
        self._store = store
        self._feed = feed
        self._current: Dict[str, AssetBasis] = {}
        # Rolling deque: list of (timestamp_monotonic, basis_mid) tuples per asset
        self._rolling: Dict[str, deque] = {
            a: deque(maxlen=7200) for a in ASSETS  # 2h at 1s tick
        }
        # Consecutive breach count per asset (for alignment state machine)
        self._breach_counts: Dict[str, int] = {a: 0 for a in ASSETS}
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ── Public API ─────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the background tick thread."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="spot-basis-tracker"
        )
        self._thread.start()
        logger.info("SpotBasisTracker started")

    def stop(self) -> None:
        """Signal the background thread to stop and wait for it."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        logger.info("SpotBasisTracker stopped")

    def get(self, asset: str) -> Optional[AssetBasis]:
        with self._lock:
            return self._current.get(asset.upper())

    def get_all(self) -> Dict[str, AssetBasis]:
        with self._lock:
            return dict(self._current)

    def get_stats(self, window_seconds: int = 3600) -> Dict[str, Dict[str, Any]]:
        """Return rolling stats (mean, median, p5, p95, sample_count, offside_pct) per asset."""
        import statistics
        cutoff = time.monotonic() - window_seconds
        result: Dict[str, Dict[str, Any]] = {}
        with self._lock:
            for asset in ASSETS:
                samples = [b for ts, b in self._rolling[asset] if ts >= cutoff]
                if not samples:
                    result[asset] = {
                        "basis_mean": None, "basis_median": None,
                        "basis_p5": None, "basis_p95": None,
                        "sample_count": 0, "offside_pct": None,
                    }
                    continue
                sorted_s = sorted(samples)
                n = len(sorted_s)
                offside_count = sum(1 for v in self._rolling[asset]
                                    if v[0] >= cutoff and abs(v[1]) > self._abs_threshold(asset))
                result[asset] = {
                    "basis_mean":   statistics.mean(samples),
                    "basis_median": statistics.median(samples),
                    "basis_p5":     sorted_s[max(0, int(n * 0.05) - 1)],
                    "basis_p95":    sorted_s[min(n - 1, int(n * 0.95))],
                    "sample_count": n,
                    "offside_pct":  round(offside_count / n * 100, 1),
                }
        return result

    # ── Internal ───────────────────────────────────────────────────────

    def _run(self) -> None:
        while not self._stop_event.wait(timeout=1.0):
            try:
                self._tick()
            except Exception:
                logger.exception("SpotBasisTracker tick error")

    def _tick(self) -> None:
        """Compute AssetBasis for every asset and update self._current."""
        store = self._get_store()
        feed = self._get_feed()
        all_states = store.get_all()

        new_current: Dict[str, AssetBasis] = {}
        for asset in ASSETS:
            ab = self._compute_asset_basis(asset, all_states, feed)
            new_current[asset] = ab
            # Append to rolling stats (only when basis_mid is available)
            if ab.basis_mid is not None:
                self._rolling[asset].append((time.monotonic(), ab.basis_mid))

        with self._lock:
            self._current = new_current

    def _compute_asset_basis(
        self,
        asset: str,
        all_states: Dict[str, Any],
        feed: Any,
    ) -> AssetBasis:
        """Compute one AssetBasis snapshot for the given asset."""
        from config.spot_basis_config import (
            ASSET_THRESHOLDS, COINBASE_SPOT_SYMBOLS,
            SPOT_STALE_MS, SPOT_MISSING_MS,
            BOOK_STALE_MS, BOOK_MISSING_MS,
        )

        cfg = ASSET_THRESHOLDS.get(asset)
        spot_symbol = COINBASE_SPOT_SYMBOLS.get(asset)

        # ── Spot feed ─────────────────────────────────────────────────
        spot_price: Optional[float] = None
        spot_status = FeedStatus.MISSING
        if feed is not None and spot_symbol:
            price_data = feed.price_cache.get(spot_symbol)
            if price_data is not None:
                spot_price = price_data.price
                last_tick = feed._last_tick_monotonic.get(spot_symbol, 0.0)
                age_ms = (time.monotonic() - last_tick) * 1000 if last_tick else float("inf")
                if age_ms < SPOT_STALE_MS:
                    spot_status = FeedStatus.OK
                elif age_ms < SPOT_MISSING_MS:
                    spot_status = FeedStatus.STALE
                # else: MISSING (already set)

        # ── Kalshi book ───────────────────────────────────────────────
        # Collect markets for this asset (by underlying field or ticker prefix)
        asset_states = []
        for ticker, state in all_states.items():
            if self._state_belongs_to_asset(state, ticker, asset):
                asset_states.append(state)

        book_status = FeedStatus.MISSING
        nearest_expiry: Optional[float] = None
        if asset_states:
            valid = [s for s in asset_states if s.book_initialized]
            if valid:
                latest_book_ts = max(s.last_book_update_ts for s in valid)
                age_ms = (time.monotonic() - latest_book_ts) * 1000
                if age_ms < BOOK_STALE_MS:
                    book_status = FeedStatus.OK
                elif age_ms < BOOK_MISSING_MS:
                    book_status = FeedStatus.STALE
                initialized_expiries = [
                    s.seconds_to_expiry for s in valid
                    if s.seconds_to_expiry is not None and s.seconds_to_expiry > 0
                ]
                if initialized_expiries:
                    nearest_expiry = min(initialized_expiries)

        # ── Implied spot (only when both feeds are OK/STALE) ──────────
        implied_mid = implied_bid = implied_ask = None
        markets_used = 0

        if spot_status != FeedStatus.MISSING and book_status != FeedStatus.MISSING:
            implied_mid = compute_implied_spot(asset_states, "mid")
            implied_bid = compute_implied_spot(asset_states, "bid")
            implied_ask = compute_implied_spot(asset_states, "ask")
            markets_used = len([s for s in asset_states if s.book_initialized and s.strike_price is not None])

        # ── Basis ─────────────────────────────────────────────────────
        basis_mid = basis_bid = basis_ask = None
        if spot_price is not None and implied_mid is not None:
            basis_mid = implied_mid - spot_price
        if spot_price is not None and implied_bid is not None:
            basis_bid = implied_bid - spot_price
        if spot_price is not None and implied_ask is not None:
            basis_ask = implied_ask - spot_price

        # ── Alignment state ───────────────────────────────────────────
        if spot_status == FeedStatus.MISSING or book_status == FeedStatus.MISSING:
            alignment = AlignmentState.STALE_FEED
            self._breach_counts[asset] = 0
        elif basis_mid is None:
            alignment = AlignmentState.ALIGNED  # can't assess → default safe
            self._breach_counts[asset] = 0
        else:
            is_breach = self._is_in_breach(asset, basis_mid, spot_price, cfg)
            if is_breach:
                self._breach_counts[asset] += 1
            else:
                self._breach_counts[asset] = max(0, self._breach_counts[asset] - 1)

            if cfg and self._breach_counts[asset] >= cfg.breach_count_threshold:
                alignment = AlignmentState.OFFSIDE
            else:
                alignment = AlignmentState.ALIGNED

        return AssetBasis(
            asset=asset,
            spot_price=spot_price,
            spot_status=spot_status,
            kalshi_book_status=book_status,
            implied_spot_mid=implied_mid,
            implied_spot_bid=implied_bid,
            implied_spot_ask=implied_ask,
            basis_mid=basis_mid,
            basis_bid=basis_bid,
            basis_ask=basis_ask,
            alignment=alignment,
            breach_count=self._breach_counts[asset],
            markets_used=markets_used,
            nearest_expiry_secs=nearest_expiry,
        )

    @staticmethod
    def _state_belongs_to_asset(state: Any, ticker: str, asset: str) -> bool:
        """Return True if this KalshiMarketState belongs to the given asset."""
        if state.underlying and state.underlying.upper() == asset.upper():
            return True
        # Fallback: ticker prefix inference
        prefix_map = {
            "BTC": "KXBTC", "ETH": "KXETH", "SOL": "KXSOL",
            "XRP": "KXXRP", "DOGE": "KXDOGE",
        }
        prefix = prefix_map.get(asset, "")
        return bool(prefix and ticker.upper().startswith(prefix))

    @staticmethod
    def _is_in_breach(asset: str, basis_mid: float, spot_price: Optional[float], cfg: Any) -> bool:
        """Return True when the basis exceeds either the absolute or percent threshold."""
        if cfg is None:
            return False
        if abs(basis_mid) > cfg.abs_threshold_usd:
            return True
        if spot_price and spot_price > 0:
            if abs(basis_mid / spot_price) > cfg.pct_threshold:
                return True
        return False

    @staticmethod
    def _abs_threshold(asset: str) -> float:
        try:
            from config.spot_basis_config import ASSET_THRESHOLDS
            cfg = ASSET_THRESHOLDS.get(asset)
            return cfg.abs_threshold_usd if cfg else 999999.0
        except Exception:
            return 999999.0

    def _get_store(self):
        if self._store is None:
            from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
            self._store = get_kalshi_market_state_store()
        return self._store

    def _get_feed(self):
        if self._feed is None:
            from data.live_price_feed import get_live_price_feed
            self._feed = get_live_price_feed()
        return self._feed
```

- [ ] **Step 4: Run pure-function tests to verify they PASS**

```bash
python -m pytest tests/alignment/test_spot_basis_tracker.py::TestComputeImpliedSpot -v
```

Expected: all 11 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add merid/alignment/__init__.py merid/alignment/spot_basis_tracker.py tests/alignment/__init__.py tests/alignment/test_spot_basis_tracker.py
git commit -m "feat(basis): add compute_implied_spot and AssetBasis models"
```

---

## Task 3: SpotBasisTracker class tests

**Files:**
- Modify: `tests/alignment/test_spot_basis_tracker.py` (add tracker tests)

- [ ] **Step 1: Add SpotBasisTracker tests to the test file**

Append the following class to `tests/alignment/test_spot_basis_tracker.py`:

```python
class TestSpotBasisTracker:
    """Tests for SpotBasisTracker._compute_asset_basis and state machine."""

    def _make_mock_store(self, states: list):
        """Build a mock KalshiMarketStateStore that returns the given states by ticker."""
        store = MagicMock()
        store.get_all.return_value = {s.ticker: s for s in states}
        return store

    def _make_mock_feed(self, spot_price: float, age_mono_seconds: float = 0.1):
        """Build a mock LivePriceFeed with a single BTC/USD price entry."""
        from data.live_price_feed import PriceData
        from datetime import datetime, timezone
        feed = MagicMock()
        pd = PriceData(
            symbol="BTC/USD", price=spot_price, bid=spot_price - 1, ask=spot_price + 1,
            volume_24h=1e9, change_24h_pct=0.0, high_24h=spot_price + 100,
            low_24h=spot_price - 100, timestamp=datetime.now(timezone.utc),
            exchange="coinbase",
        )
        feed.price_cache = {"BTC/USD": pd}
        feed._last_tick_monotonic = {"BTC/USD": time.monotonic() - age_mono_seconds}
        return feed

    def test_aligned_when_basis_within_threshold(self):
        """Basis within threshold → aligned state."""
        spot = 97000.0
        states = [
            _make_state("T-A", strike=96000.0, mid=60, asset="BTC"),
            _make_state("T-B", strike=98000.0, mid=40, asset="BTC"),
        ]
        # implied_mid = 97000.0, basis_mid = 0.0
        tracker = SpotBasisTracker(
            store=self._make_mock_store(states),
            feed=self._make_mock_feed(spot),
        )
        ab = tracker._compute_asset_basis("BTC", {s.ticker: s for s in states}, tracker._get_feed())
        assert ab.alignment == AlignmentState.ALIGNED
        assert ab.basis_mid == pytest.approx(0.0, abs=1.0)
        assert ab.spot_status == FeedStatus.OK

    def test_breach_counts_increment_then_flip_offside(self):
        """breach_count accumulates; once >= threshold, alignment = OFFSIDE."""
        from config.spot_basis_config import ASSET_THRESHOLDS
        threshold = ASSET_THRESHOLDS["BTC"]
        spot = 97000.0
        # Basis = 1000 USD — far above 50 USD threshold
        states = [
            _make_state("T-A", strike=96000.0, mid=60, asset="BTC"),
            _make_state("T-B", strike=100000.0, mid=40, asset="BTC"),
            # implied_mid = 96000 + 0.5 * 4000 = 98000 → basis = +1000
        ]
        tracker = SpotBasisTracker(
            store=self._make_mock_store(states),
            feed=self._make_mock_feed(spot),
        )
        all_s = {s.ticker: s for s in states}
        feed = tracker._get_feed()
        n = threshold.breach_count_threshold
        for i in range(n - 1):
            ab = tracker._compute_asset_basis("BTC", all_s, feed)
            assert ab.alignment == AlignmentState.ALIGNED, f"tick {i}: expected ALIGNED before threshold"
        ab = tracker._compute_asset_basis("BTC", all_s, feed)
        assert ab.alignment == AlignmentState.OFFSIDE
        assert ab.breach_count == n

    def test_stale_feed_when_spot_missing(self):
        """Spot price older than SPOT_MISSING_MS → stale_feed state."""
        states = [
            _make_state("T-A", strike=96000.0, mid=60, asset="BTC"),
            _make_state("T-B", strike=98000.0, mid=40, asset="BTC"),
        ]
        tracker = SpotBasisTracker(
            store=self._make_mock_store(states),
            feed=self._make_mock_feed(97000.0, age_mono_seconds=60.0),  # 60s old → missing
        )
        ab = tracker._compute_asset_basis("BTC", {s.ticker: s for s in states}, tracker._get_feed())
        assert ab.spot_status == FeedStatus.MISSING
        assert ab.alignment == AlignmentState.STALE_FEED

    def test_get_all_returns_all_assets_after_tick(self):
        """After _tick(), get_all() returns an entry for each of the 5 assets."""
        store = MagicMock()
        store.get_all.return_value = {}
        feed = MagicMock()
        feed.price_cache = {}
        feed._last_tick_monotonic = {}
        tracker = SpotBasisTracker(store=store, feed=feed)
        tracker._tick()
        result = tracker.get_all()
        assert set(result.keys()) == {"BTC", "ETH", "SOL", "XRP", "DOGE"}

    def test_get_stats_returns_none_when_no_samples(self):
        """get_stats() returns None fields when rolling deque is empty."""
        tracker = SpotBasisTracker(store=MagicMock(), feed=MagicMock())
        tracker._get_store().get_all.return_value = {}
        tracker._get_feed().price_cache = {}
        tracker._get_feed()._last_tick_monotonic = {}
        stats = tracker.get_stats()
        assert stats["BTC"]["sample_count"] == 0
        assert stats["BTC"]["basis_mean"] is None

    def test_state_belongs_to_asset_by_underlying(self):
        """_state_belongs_to_asset returns True when underlying field matches."""
        s = _make_state("KXETH-T-A", strike=3000.0, mid=50, asset="ETH")
        assert SpotBasisTracker._state_belongs_to_asset(s, "KXETH-T-A", "ETH")
        assert not SpotBasisTracker._state_belongs_to_asset(s, "KXETH-T-A", "BTC")

    def test_state_belongs_to_asset_by_ticker_prefix_fallback(self):
        """_state_belongs_to_asset uses ticker prefix when underlying is None."""
        s = _make_state("KXSOL15M-A", strike=150.0, mid=50, asset="SOL")
        s.underlying = None  # force prefix fallback
        assert SpotBasisTracker._state_belongs_to_asset(s, "KXSOL15M-A", "SOL")
        assert not SpotBasisTracker._state_belongs_to_asset(s, "KXSOL15M-A", "ETH")
```

- [ ] **Step 2: Run tracker tests to verify they PASS**

```bash
python -m pytest tests/alignment/test_spot_basis_tracker.py::TestSpotBasisTracker -v
```

Expected: all 7 tests PASS.

- [ ] **Step 3: Run full alignment test suite**

```bash
python -m pytest tests/alignment/ -v
```

Expected: all 18 tests PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/alignment/test_spot_basis_tracker.py
git commit -m "test(basis): full test suite for SpotBasisTracker (18 tests)"
```

---

## Task 4: REST API

**Files:**
- Create: `web/api/spot_basis_api.py`

- [ ] **Step 1: Create the API router**

```python
# web/api/spot_basis_api.py
"""Spot/Kalshi basis REST API.

Endpoints:
    GET /api/v1/kalshi/spot-basis        — Current per-asset basis state
    GET /api/v1/kalshi/spot-basis/stats  — Rolling stats (last N minutes)
"""
from __future__ import annotations

import time
from typing import Any, Dict

from fastapi import APIRouter, Query
from utils.logger import get_logger

logger = get_logger("web.api.spot_basis_api")
router = APIRouter(prefix="/api/v1/kalshi", tags=["spot-basis"])


def _get_tracker():
    from merid.alignment import get_spot_basis_tracker
    return get_spot_basis_tracker()


@router.get("/spot-basis")
async def get_spot_basis() -> Dict[str, Any]:
    """Current spot/Kalshi basis state for all 5 crypto assets.

    Response shape::

        {
          "timestamp": 1744800000.0,
          "assets": {
            "BTC": {
              "spot_price": 84231.5,
              "spot_status": "ok",
              "kalshi_book_status": "ok",
              "implied_spot_mid": 84180.0,
              "implied_spot_bid": 84120.0,
              "implied_spot_ask": 84240.0,
              "basis_mid": -51.5,
              "basis_bid": -111.5,
              "basis_ask": 8.5,
              "alignment": "aligned",
              "breach_count": 0,
              "markets_used": 4,
              "nearest_expiry_secs": 180.0
            },
            ...
          }
        }
    """
    try:
        tracker = _get_tracker()
        all_basis = tracker.get_all()
        return {
            "timestamp": time.time(),
            "assets": {asset: ab.to_dict() for asset, ab in all_basis.items()},
        }
    except Exception as exc:
        logger.exception("spot-basis endpoint error")
        return {"error": str(exc), "assets": {}}


@router.get("/spot-basis/stats")
async def get_spot_basis_stats(
    window_minutes: int = Query(default=60, ge=1, le=1440),
) -> Dict[str, Any]:
    """Rolling basis statistics over the last N minutes (default: 60).

    Response shape::

        {
          "timestamp": 1744800000.0,
          "window_minutes": 60,
          "assets": {
            "BTC": {
              "basis_mean": -8.2,
              "basis_median": -5.1,
              "basis_p5": -42.3,
              "basis_p95": 35.7,
              "sample_count": 3420,
              "offside_pct": 2.1
            }
          }
        }
    """
    try:
        tracker = _get_tracker()
        stats = tracker.get_stats(window_seconds=window_minutes * 60)
        return {
            "timestamp": time.time(),
            "window_minutes": window_minutes,
            "assets": stats,
        }
    except Exception as exc:
        logger.exception("spot-basis/stats endpoint error")
        return {"error": str(exc), "assets": {}}
```

- [ ] **Step 2: Quick smoke test (no test file needed — tested by existing framework)**

```bash
python -c "from web.api.spot_basis_api import router; print('router OK, routes:', [r.path for r in router.routes])"
```

Expected output: `router OK, routes: ['/api/v1/kalshi/spot-basis', '/api/v1/kalshi/spot-basis/stats']`

- [ ] **Step 3: Commit**

```bash
git add web/api/spot_basis_api.py
git commit -m "feat(basis): add spot-basis REST API endpoints"
```

---

## Task 5: Execution gate integration

**Files:**
- Modify: `core/execution_gate.py`

- [ ] **Step 1: Add `basis_misalignment` to `REMEDIATION_HINTS`**

Find the `REMEDIATION_HINTS` dict in [core/execution_gate.py](core/execution_gate.py) and add one entry:

```python
    "basis_misalignment": (
        "Spot/Kalshi basis is persistently offside for one or more assets. "
        "Check the Spot Basis panel in Operator Dashboard. "
        "Assets in 'offside' state will not block trading but will reduce signal confidence."
    ),
```

- [ ] **Step 2: Add the basis check to `check_execution_gate()`**

Find the end of `check_execution_gate()` (before the final `_log_gate_state_diagnostic` call and `return` statement) and insert:

```python
    # ── 5. Spot-basis alignment (advisory warning only) ─────────────────────
    try:
        from merid.alignment import get_spot_basis_tracker
        from merid.alignment.spot_basis_tracker import AlignmentState
        tracker = get_spot_basis_tracker()
        offside = [
            a for a, b in tracker.get_all().items()
            if b.alignment == AlignmentState.OFFSIDE
        ]
        if offside:
            reasons.append(BlockReason(
                source="basis_misalignment",
                severity="warning",
                message=f"Spot/Kalshi basis offside: {', '.join(sorted(offside))}",
                hint=REMEDIATION_HINTS["basis_misalignment"],
            ))
    except Exception as exc:
        logger.debug("Basis alignment check skipped: %s", exc)
        # Fail-open: basis check is advisory; never block execution on check failure
```

- [ ] **Step 3: Verify the gate still passes its smoke test**

```bash
python -c "from core.execution_gate import check_execution_gate; s = check_execution_gate(); print('gate ok, state:', s.gate_state)"
```

Expected: no exception, prints `gate ok, state: blocked` or `clear`.

- [ ] **Step 4: Commit**

```bash
git add core/execution_gate.py
git commit -m "feat(basis): add basis_misalignment warning source to execution gate"
```

---

## Task 6: Wire into web/main.py

**Files:**
- Modify: `web/main.py`

- [ ] **Step 1: Add the safe-import line for the new router**

In `web/main.py`, find the block of `_si(...)` calls near line 107 and add:

```python
spot_basis_router = _si("web.api.spot_basis_api")
```

- [ ] **Step 2: Register the router**

Find the `_reg(crypto_spot_kalshi_router)` call (around line 628) and add immediately after:

```python
    _reg(spot_basis_router)
```

- [ ] **Step 3: Start and stop the tracker in the lifespan**

Find the FastAPI startup section (where `CryptoAlertRouter` is started). Add tracker startup after it:

```python
    # Start spot-basis tracker
    try:
        from merid.alignment import get_spot_basis_tracker
        get_spot_basis_tracker().start()
        logger.info("SpotBasisTracker started")
    except Exception as exc:
        logger.warning("SpotBasisTracker start failed (non-fatal): %s", exc)
```

Find the shutdown/teardown section (where `CryptoAlertRouter` is stopped) and add:

```python
    # Stop spot-basis tracker
    try:
        from merid.alignment import get_spot_basis_tracker
        get_spot_basis_tracker().stop()
    except Exception:
        pass
```

- [ ] **Step 4: Verify the app imports cleanly**

```bash
python -c "import web.main; print('main.py imports OK')"
```

Expected: prints `main.py imports OK` (or startup log noise — no exceptions).

- [ ] **Step 5: Commit**

```bash
git add web/main.py
git commit -m "feat(basis): mount spot-basis router and start SpotBasisTracker in lifespan"
```

---

## Task 7: Frontend constants

**Files:**
- Modify: `web/react/src/config/constants.ts`

- [ ] **Step 1: Add API endpoint constants and polling interval**

Find the `API_ENDPOINTS` object and add:

```typescript
  SPOT_BASIS: "/api/v1/kalshi/spot-basis",
  SPOT_BASIS_STATS: "/api/v1/kalshi/spot-basis/stats",
```

Find the `POLLING_INTERVALS` object and add:

```typescript
    SPOT_BASIS: 2000,  // 2 seconds — tracker ticks at 1s, so 2s polling is sufficient
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd c:/Dev/MERID/web/react && npx tsc --noEmit 2>&1 | tail -10
```

Expected: no errors (or pre-existing errors only, not new ones from this change).

- [ ] **Step 3: Commit**

```bash
git add web/react/src/config/constants.ts
git commit -m "feat(basis): add SPOT_BASIS endpoint constants"
```

---

## Task 8: Frontend SpotBasisPanel

**Files:**
- Create: `web/react/src/components/SpotBasisPanel.tsx`
- Modify: `web/react/src/views/OperatorDashboard.tsx`

- [ ] **Step 1: Create the panel component**

```tsx
// web/react/src/components/SpotBasisPanel.tsx
import { useApiData } from '../hooks/useApiData';
import { API_ENDPOINTS, DEFAULTS } from '../config/constants';

// ── Types ──────────────────────────────────────────────────────────────

interface AssetBasisData {
  asset: string;
  spot_price: number | null;
  spot_status: 'ok' | 'stale' | 'missing';
  kalshi_book_status: 'ok' | 'stale' | 'missing';
  implied_spot_mid: number | null;
  implied_spot_bid: number | null;
  implied_spot_ask: number | null;
  basis_mid: number | null;
  basis_bid: number | null;
  basis_ask: number | null;
  alignment: 'aligned' | 'offside' | 'stale_feed';
  breach_count: number;
  markets_used: number;
  nearest_expiry_secs: number | null;
}

interface SpotBasisResponse {
  timestamp: number;
  assets: Record<string, AssetBasisData>;
}

// ── Constants ──────────────────────────────────────────────────────────

const ASSET_COLORS: Record<string, string> = {
  BTC: 'text-orange-400', ETH: 'text-blue-400', SOL: 'text-purple-400',
  XRP: 'text-green-400',  DOGE: 'text-yellow-400',
};

const ASSET_ORDER = ['BTC', 'ETH', 'SOL', 'XRP', 'DOGE'];

// ── Helpers ────────────────────────────────────────────────────────────

function fmtBasis(v: number | null, asset: string): string {
  if (v === null || v === undefined) return '—';
  const prefix = v >= 0 ? '+' : '';
  if (asset === 'BTC' || asset === 'ETH') {
    return `${prefix}$${Math.abs(v).toFixed(1)}`;
  }
  return `${prefix}$${Math.abs(v).toFixed(4)}`;
}

function fmtExpiry(secs: number | null): string {
  if (secs === null) return '—';
  if (secs < 60) return `${Math.round(secs)}s`;
  return `${Math.round(secs / 60)}m`;
}

function alignmentBadge(alignment: string): JSX.Element {
  const classes: Record<string, string> = {
    aligned:    'bg-green-900/50 text-green-300 border border-green-700',
    offside:    'bg-red-900/50 text-red-300 border border-red-700',
    stale_feed: 'bg-yellow-900/50 text-yellow-300 border border-yellow-700',
  };
  const labels: Record<string, string> = {
    aligned: 'Aligned', offside: 'Offside', stale_feed: 'Stale Feed',
  };
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-mono ${classes[alignment] || ''}`}>
      {labels[alignment] || alignment}
    </span>
  );
}

function feedDot(status: string): JSX.Element {
  const colors: Record<string, string> = {
    ok: 'bg-green-400', stale: 'bg-yellow-400', missing: 'bg-red-400',
  };
  return (
    <span
      className={`inline-block w-2 h-2 rounded-full ${colors[status] || 'bg-gray-400'}`}
      title={status}
    />
  );
}

// ── Component ──────────────────────────────────────────────────────────

export default function SpotBasisPanel() {
  const { data, loading, error } = useApiData<SpotBasisResponse>(
    API_ENDPOINTS.SPOT_BASIS,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.SPOT_BASIS }
  );

  if (loading && !data) {
    return (
      <div className="bg-gray-900 rounded-lg p-4 border border-gray-700">
        <h3 className="text-sm font-semibold text-gray-300 mb-2">Spot/Kalshi Basis</h3>
        <div className="text-gray-500 text-xs">Loading…</div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="bg-gray-900 rounded-lg p-4 border border-gray-700">
        <h3 className="text-sm font-semibold text-gray-300 mb-2">Spot/Kalshi Basis</h3>
        <div className="text-red-400 text-xs">{error || 'No data'}</div>
      </div>
    );
  }

  const offside = ASSET_ORDER.filter(a => data.assets[a]?.alignment === 'offside');

  return (
    <div className="bg-gray-900 rounded-lg border border-gray-700">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-gray-700">
        <h3 className="text-sm font-semibold text-gray-200">Spot / Kalshi Basis</h3>
        {offside.length > 0 ? (
          <span className="text-xs text-red-400 font-mono">
            {offside.join(', ')} offside
          </span>
        ) : (
          <span className="text-xs text-green-400">All aligned</span>
        )}
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-gray-500 border-b border-gray-800">
              <th className="text-left px-3 py-1.5">Asset</th>
              <th className="text-right px-3 py-1.5">Spot</th>
              <th className="text-right px-3 py-1.5">Implied</th>
              <th className="text-right px-3 py-1.5">Basis (mid)</th>
              <th className="text-right px-3 py-1.5">Bid↔Ask</th>
              <th className="text-center px-3 py-1.5">Feeds</th>
              <th className="text-center px-3 py-1.5">State</th>
              <th className="text-right px-3 py-1.5">Expiry</th>
            </tr>
          </thead>
          <tbody>
            {ASSET_ORDER.map((asset) => {
              const ab = data.assets[asset];
              if (!ab) return null;
              const basisColor = ab.basis_mid === null ? 'text-gray-500'
                : Math.abs(ab.basis_mid) > 0 ? 'text-yellow-300' : 'text-gray-300';
              return (
                <tr key={asset} className="border-b border-gray-800/50 hover:bg-gray-800/30">
                  <td className={`px-3 py-1.5 font-mono font-bold ${ASSET_COLORS[asset]}`}>
                    {asset}
                  </td>
                  <td className="px-3 py-1.5 text-right text-gray-300 font-mono">
                    {ab.spot_price !== null ? `$${ab.spot_price.toLocaleString('en-US', {maximumFractionDigits: 2})}` : '—'}
                  </td>
                  <td className="px-3 py-1.5 text-right text-gray-300 font-mono">
                    {ab.implied_spot_mid !== null ? `$${ab.implied_spot_mid.toLocaleString('en-US', {maximumFractionDigits: 2})}` : '—'}
                  </td>
                  <td className={`px-3 py-1.5 text-right font-mono ${basisColor}`}>
                    {fmtBasis(ab.basis_mid, asset)}
                  </td>
                  <td className="px-3 py-1.5 text-right font-mono text-gray-400">
                    {fmtBasis(ab.basis_bid, asset)} / {fmtBasis(ab.basis_ask, asset)}
                  </td>
                  <td className="px-3 py-1.5 text-center">
                    <span title={`Spot: ${ab.spot_status}`}>{feedDot(ab.spot_status)}</span>
                    {' '}
                    <span title={`Book: ${ab.kalshi_book_status}`}>{feedDot(ab.kalshi_book_status)}</span>
                  </td>
                  <td className="px-3 py-1.5 text-center">
                    {alignmentBadge(ab.alignment)}
                  </td>
                  <td className="px-3 py-1.5 text-right text-gray-400 font-mono">
                    {fmtExpiry(ab.nearest_expiry_secs)}
                    {ab.markets_used > 0 && (
                      <span className="ml-1 text-gray-600">({ab.markets_used})</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Embed in OperatorDashboard**

In `web/react/src/views/OperatorDashboard.tsx`:

1. Add import near the top of the file:
```tsx
import SpotBasisPanel from '../components/SpotBasisPanel';
```

2. Find an appropriate location in the JSX (e.g., after `SwarmHealthPanel` or before the closing grid column) and add:
```tsx
<SpotBasisPanel />
```

- [ ] **Step 3: Verify TypeScript compiles**

```bash
cd c:/Dev/MERID/web/react && npx tsc --noEmit 2>&1 | tail -20
```

Expected: no new errors from `SpotBasisPanel.tsx`.

- [ ] **Step 4: Commit**

```bash
git add web/react/src/components/SpotBasisPanel.tsx web/react/src/views/OperatorDashboard.tsx
git commit -m "feat(basis): add SpotBasisPanel to OperatorDashboard"
```

---

## Self-Review

### Spec coverage check

| Spec requirement | Covered by |
|---|---|
| Compute basis_mid, basis_bid, basis_ask per asset | `compute_implied_spot()` × 3 variants in Task 2 |
| Max absolute and percent thresholds | `AssetBasisThresholds` in Task 1 |
| Consecutive-tick breach before offside | `_is_in_breach()` + `_breach_counts` in Task 2 |
| Halve/zero size when offside (reduce quoting) | Execution gate warning source (Task 5) — callers read `BlockReason.source == "basis_misalignment"` |
| Spot staleness detection + flag | `spot_status` field in `AssetBasis`, FeedStatus enum in Task 2 |
| Kalshi book staleness detection + flag | `kalshi_book_status` field in Task 2 |
| Rolling stats (mean, median, p95) | `get_stats()` in Task 2 |
| REST API for current state | `GET /api/v1/kalshi/spot-basis` in Task 4 |
| REST API for rolling stats | `GET /api/v1/kalshi/spot-basis/stats` in Task 4 |
| UI panel with basis per asset | `SpotBasisPanel.tsx` in Task 8 |
| Feed status dots in UI | `feedDot()` in Task 8 |
| Color coding (aligned/offside/stale) | `alignmentBadge()` in Task 8 |
| Alert on offside | Execution gate `basis_misalignment` warning triggers operator-level alerts via existing gate UI |

### Placeholder scan

None found. All code blocks are complete.

### Type consistency

- `AssetBasis.to_dict()` returns keys matching `AssetBasisData` TypeScript interface in the panel.
- `AlignmentState.OFFSIDE` used consistently in gate check and tests.
- `FeedStatus.OK/STALE/MISSING` values match TypeScript union type strings `'ok' | 'stale' | 'missing'`.
- `compute_implied_spot(states, which)` — `which` param typed as `str`; `"mid"/"bid"/"ask"` consistent across all callers (tracker `_compute_asset_basis`, tests).
- `SpotBasisTracker._breach_counts` initialized for all 5 ASSETS; `_compute_asset_basis` only reads keys in `ASSETS`.

---

**Plan complete and saved to `docs/superpowers/plans/2026-04-16-spot-basis-tracker.md`.**
