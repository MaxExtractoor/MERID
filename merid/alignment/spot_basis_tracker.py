"""Spot/Kalshi basis tracker.

Computes and monitors the spread between Coinbase live spot price and the
Kalshi-implied spot price per crypto asset every second in a background thread.

NOTE: This module produces analytics for UI/monitoring purposes. 15m Kalshi agents
do not consume this data for edge computation — 15m signals are driven purely by
market prices, volatility regime, and risk config.

How implied spot is computed
-----------------------------
Kalshi crypto binary markets are YES/NO contracts where YES = "asset ends above
strike at expiry".  YES probability decreases monotonically as strike increases
(higher strike = harder to be above it).

For each asset we:
1. Pull all KalshiMarketState objects with a known strike_price and a live book.
2. Group by expiry proximity (markets settling within the same ~1-minute window).
3. Scan clusters from nearest to farthest expiry, taking the FIRST cluster that
   has ≥2 distinct strikes (15m "up/down" contracts typically have only 1 strike,
   so we fall through to the 1H level-based markets which have many strikes).
4. Interpolate to find the strike where YES prob = 0.50 — that is the risk-neutral
   median, i.e. the Kalshi-implied spot.
5. basis = implied_spot − coinbase_spot

Three variants (mid / bid / ask) use different order-book price columns so
callers can see the full ask-side / bid-side basis spread.

Feed staleness
--------------
spot_status  : ok (<5s), stale (<30s), missing (≥30s) — configurable via env
kalshi_book_status : ok (<10s), stale (<60s), missing (≥60s) — configurable via env

Alignment state machine
-----------------------
ALIGNED    : |basis_mid| within abs + pct thresholds for all recent ticks
OFFSIDE    : breach persists for ≥ breach_count_threshold consecutive ticks
STALE_FEED : either spot or Kalshi book is MISSING (can't assess)
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Iterator, List, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("merid.alignment.spot_basis_tracker")

ASSETS: Tuple[str, ...] = ("BTC", "ETH", "SOL", "XRP", "DOGE")

# Import composite and alignment modules (optional)
try:
    from data.spot_models import Asset, SpotAlignment
    from data.spot_composite import get_spot_composite
    from data.cfb_rti_client import get_cfb_rti_client
    _COMPOSITE_AVAILABLE = True
except ImportError:
    _COMPOSITE_AVAILABLE = False
    logger.debug("Composite/CFB modules not available - running in legacy mode")

# Seconds between tracker ticks
_TICK_INTERVAL: float = 1.0

# Maximum seconds between two markets' expiries to still consider them
# part of the same "cluster" (1-minute bucket covers most rounding error).
_CLUSTER_BUCKET_SECONDS: float = 90.0


# ── Enums ──────────────────────────────────────────────────────────────────────


class FeedStatus(str, Enum):
    OK      = "ok"
    STALE   = "stale"
    MISSING = "missing"


class AlignmentState(str, Enum):
    ALIGNED    = "aligned"
    OFFSIDE    = "offside"
    STALE_FEED = "stale_feed"


# ── AssetBasis dataclass ───────────────────────────────────────────────────────


@dataclass
class AssetBasis:
    """Live basis snapshot for one crypto asset.

    Produced by SpotBasisTracker every second.  Immutable after creation
    (callers should not mutate fields).
    """
    asset: str
    spot_price: Optional[float]           # Coinbase USD price
    spot_status: FeedStatus               # ok / stale / missing
    kalshi_book_status: FeedStatus        # ok / stale / missing
    implied_spot_mid: Optional[float]     # Risk-neutral median (mid-price interpolation)
    implied_spot_bid: Optional[float]     # Risk-neutral median using YES bid prices
    implied_spot_ask: Optional[float]     # Risk-neutral median using YES ask prices
    basis_mid: Optional[float]            # implied_mid − spot  (+ = Kalshi leads)
    basis_bid: Optional[float]            # implied_bid − spot
    basis_ask: Optional[float]            # implied_ask − spot
    alignment: AlignmentState             # aligned / offside / stale_feed
    breach_count: int                     # Consecutive ticks in breach
    markets_used: int                     # Markets contributing to implied spot
    nearest_expiry_secs: Optional[float]  # Seconds to nearest eligible cluster
    spot_source: Optional[str] = None        # Feed source: coinbase, kraken, coingecko
    cfb_rti_alignment: Optional[str] = None  # CFB/RTI alignment state
    computed_at: float = field(default_factory=time.monotonic)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "asset":                self.asset,
            "spot_price":           self.spot_price,
            "spot_status":          self.spot_status.value,
            "kalshi_book_status":   self.kalshi_book_status.value,
            "implied_spot_mid":     self.implied_spot_mid,
            "implied_spot_bid":     self.implied_spot_bid,
            "implied_spot_ask":     self.implied_spot_ask,
            "basis_mid":            self.basis_mid,
            "basis_bid":            self.basis_bid,
            "basis_ask":            self.basis_ask,
            "alignment":            self.alignment.value,
            "breach_count":         self.breach_count,
            "markets_used":         self.markets_used,
            "nearest_expiry_secs":  self.nearest_expiry_secs,
            "spot_source":          self.spot_source,
            "cfb_rti_alignment":    self.cfb_rti_alignment,
            "computed_at":          self.computed_at,
        }


# ── Pure computation ───────────────────────────────────────────────────────────


def _iter_clusters(valid: List[Any]) -> Iterator[List[Any]]:
    """Yield clusters of markets sorted by seconds_to_expiry, grouped into
    windows of _CLUSTER_BUCKET_SECONDS.  Yields clusters in order of
    ascending (nearest) expiry.

    Each yielded cluster contains only markets within the same time window,
    so 15m markets (expiry ~5 min) and 1H markets (expiry ~30 min) will be
    in different clusters even if both are "near".
    """
    # Sort by expiry ascending
    sorted_valid = sorted(valid, key=lambda s: s.seconds_to_expiry)
    if not sorted_valid:
        return

    cluster: List[Any] = [sorted_valid[0]]
    bucket_start = sorted_valid[0].seconds_to_expiry

    for s in sorted_valid[1:]:
        if s.seconds_to_expiry - bucket_start <= _CLUSTER_BUCKET_SECONDS:
            cluster.append(s)
        else:
            yield cluster
            cluster = [s]
            bucket_start = s.seconds_to_expiry

    if cluster:
        yield cluster


def compute_implied_spot(
    states: List[Any],  # List[KalshiMarketState] — typed loosely to avoid circular imports
    which: str,         # "mid" | "bid" | "ask"
) -> Optional[float]:
    """Compute Kalshi-implied spot by interpolating YES probabilities across strikes.

    For multi-strike markets (1H+): Returns the strike where YES probability = 0.50.
    For single-strike 15m markets: Returns the reference spot (market-implied from single YES prob).

    Returns None if no valid data available.

    Algorithm for multi-strike:
        1. Filter markets: book_initialized, strike_price set, seconds_to_expiry > 0.
        2. Iterate over expiry clusters from nearest to farthest.
        3. Take the FIRST cluster with ≥2 distinct strikes (skips 15m single-strike).
        4. Extract (strike, yes_prob) using `which` price column.
        5. Sort by strike ascending (YES prob decreases with strike).
        6. Find adjacent pair that brackets p = 0.50 and linearly interpolate.

    Algorithm for single-strike 15m:
        1. Find markets with book_initialized and YES price, but no strike_price.
        2. For single-strike, the YES probability itself is the market's view of "above current level".
        3. Return None (can't compute implied spot from single probability).
        4. Instead, track the YES probability directly for calibration.

    Args:
        states: KalshiMarketState objects for one asset (any mix of expiries/timeframes).
        which:  Price column — "mid" (mid_cents), "bid" (best_bid_cents), "ask" (best_ask_cents).

    Returns:
        Float implied spot in USD, or None (for single-strike 15m markets).
    """
    if not states:
        return None

    # Separate single-strike (15m) from multi-strike markets
    single_strike = [
        s for s in states
        if (
            getattr(s, "book_initialized", False)
            and getattr(s, "strike_price", None) is None
            and getattr(s, "seconds_to_expiry", None) is not None
            and s.seconds_to_expiry > 0
        )
    ]
    
    multi_strike = [
        s for s in states
        if (
            getattr(s, "book_initialized", False)
            and getattr(s, "strike_price", None) is not None
            and getattr(s, "seconds_to_expiry", None) is not None
            and s.seconds_to_expiry > 0
        )
    ]

    # For single-strike 15m markets, we can't compute implied spot via interpolation
    # Instead, we return None and track the YES probability directly
    if single_strike and not multi_strike:
        # Single-strike markets only - return None, caller should use YES prob directly
        return None

    # For multi-strike markets, use the existing interpolation algorithm
    if not multi_strike:
        return None

    # Step 2–3: Find the nearest cluster with ≥2 distinct strikes
    chosen_cluster: Optional[List[Any]] = None
    for cluster in _iter_clusters(multi_strike):
        strikes = {s.strike_price for s in cluster}
        if len(strikes) >= 2:
            chosen_cluster = cluster
            break

    if chosen_cluster is None or len(chosen_cluster) < 2:
        return None

    # Step 4: Extract (strike, yes_prob) pairs
    def _get_prob(s: Any) -> Optional[float]:
        if which == "mid":
            v = getattr(s, "mid_cents", None)
        elif which == "bid":
            v = getattr(s, "best_bid_cents", None)
        elif which == "ask":
            v = getattr(s, "best_ask_cents", None)
        else:
            return None
        return v / 100.0 if v is not None else None

    pairs: List[Tuple[float, float]] = []
    for s in chosen_cluster:
        prob = _get_prob(s)
        if prob is not None:
            pairs.append((s.strike_price, prob))

    if len(pairs) < 2:
        return None

    # Step 5: Sort by strike ascending (YES prob should decrease with strike)
    pairs.sort(key=lambda x: x[0])

    # Step 6: Find bracketing pair and interpolate
    for i in range(len(pairs) - 1):
        s_lo, p_lo = pairs[i]
        s_hi, p_hi = pairs[i + 1]
        # YES prob should be monotonically decreasing with strike.
        # p_lo >= 0.50 and p_hi < 0.50 means we straddle the 50th percentile.
        if p_lo >= 0.50 and p_hi < 0.50:
            span_p = p_lo - p_hi
            if span_p <= 0:
                continue  # degenerate (non-monotonic or same prob)
            t = (p_lo - 0.50) / span_p
            return s_lo + t * (s_hi - s_lo)

    return None  # No bracket found (all probs same side of 0.50)


# ── SpotBasisTracker ────────────────────────────────────────────────────────────


class SpotBasisTracker:
    """Background thread that computes spot/Kalshi basis per asset every second.

    Reads from the KalshiMarketStateStore (Kalshi WS orderbook data) and the
    LivePriceFeed (Coinbase spot), then exposes AssetBasis snapshots via
    get() and get_all().

    Thread safety: _current and _rolling are protected by _lock.  _tick()
    only acquires the lock at the end of each tick (one bulk swap), keeping
    the hot path lock-free.

    Lifecycle::

        tracker = get_spot_basis_tracker()
        tracker.start()    # call once at app startup (idempotent)
        ...
        tracker.stop()     # call at shutdown
    """

    def __init__(self, store: Any = None, feed: Any = None) -> None:
        """
        Args:
            store: KalshiMarketStateStore (lazy-init from singleton if None)
            feed:  LivePriceFeed (lazy-init from singleton if None)
        """
        self._store = store
        self._feed = feed

        # Current snapshots per asset (swapped atomically under _lock)
        self._current: Dict[str, AssetBasis] = {}

        # Rolling basis_mid samples: deque of (monotonic_ts, basis_mid_float)
        # maxlen = 2 hours at 1s tick to cap memory while audit window is ≤1h
        self._rolling: Dict[str, deque] = {
            a: deque(maxlen=7200) for a in ASSETS
        }

        # Consecutive breach counters — live outside _lock (only written by _tick thread)
        self._breach_counts: Dict[str, int] = {a: 0 for a in ASSETS}

        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ── Public API ──────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the background tick thread (idempotent)."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="spot-basis-tracker",
        )
        self._thread.start()
        logger.info("SpotBasisTracker started")

    def stop(self) -> None:
        """Signal the background thread to stop and wait up to 5 s."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
        logger.info("SpotBasisTracker stopped")

    def get(self, asset: str) -> Optional[AssetBasis]:
        """Return the latest AssetBasis snapshot for *asset*, or None if not yet computed."""
        with self._lock:
            return self._current.get(asset.upper())

    def get_all(self) -> Dict[str, AssetBasis]:
        """Return a shallow copy of all current AssetBasis snapshots."""
        with self._lock:
            return dict(self._current)

    def get_stats(self, window_seconds: int = 3600) -> Dict[str, Dict[str, Any]]:
        """Return rolling basis statistics per asset.

        Args:
            window_seconds: How far back to look (default 1 hour).

        Returns:
            Dict keyed by asset → dict with keys:
                basis_mean, basis_median, basis_p5, basis_p95 (float or None),
                sample_count (int),
                offside_pct (float or None — % of samples in breach).
        """
        import statistics as _stats

        cutoff = time.monotonic() - window_seconds
        result: Dict[str, Dict[str, Any]] = {}

        with self._lock:
            for asset in ASSETS:
                samples = [b for ts, b in self._rolling[asset] if ts >= cutoff]
                if not samples:
                    result[asset] = {
                        "basis_mean":   None,
                        "basis_median": None,
                        "basis_p5":     None,
                        "basis_p95":    None,
                        "sample_count": 0,
                        "offside_pct":  None,
                    }
                    continue

                sorted_s = sorted(samples)
                n = len(sorted_s)
                abs_thr = self._abs_threshold(asset)
                offside_n = sum(1 for v in samples if abs(v) > abs_thr)

                result[asset] = {
                    "basis_mean":   _stats.mean(samples),
                    "basis_median": _stats.median(samples),
                    "basis_p5":     sorted_s[max(0, int(n * 0.05) - 1)],
                    "basis_p95":    sorted_s[min(n - 1, int(n * 0.95))],
                    "sample_count": n,
                    "offside_pct":  round(offside_n / n * 100.0, 1),
                }

        return result

    # ── Internal ────────────────────────────────────────────────────────────

    def _run(self) -> None:
        """Background thread entry point — ticks every _TICK_INTERVAL seconds.
        
        BUG-FIX (2026-05-12): Added diagnostic logging to detect where thread is stuck
        when faulthandler timeout fires. Logs entry/exit of _tick and key operations.
        """
        logger.info("[SPOT-BASIS-TRACKER] _run: thread started")
        tick_count = 0
        while not self._stop_event.wait(timeout=_TICK_INTERVAL):
            tick_count += 1
            tick_start = time.monotonic()
            logger.info(f"[SPOT-BASIS-TRACKER] tick #{tick_count} starting at {tick_start:.3f}")
            try:
                self._tick()
                tick_elapsed = time.monotonic() - tick_start
                logger.info(f"[SPOT-BASIS-TRACKER] tick #{tick_count} completed in {tick_elapsed*1000:.1f}ms")
                if tick_elapsed > 2.0:
                    logger.warning(f"[SPOT-BASIS-TRACKER] tick #{tick_count} took {tick_elapsed*1000:.1f}ms - SLOW")
            except Exception:
                logger.exception("SpotBasisTracker tick error")
        logger.info("[SPOT-BASIS-TRACKER] _run: thread stopped")

    def _tick(self) -> None:
        """Compute one AssetBasis per asset and atomically swap _current.
        
        BUG-FIX (2026-05-12): Added lock acquisition timeout to prevent indefinite blocking
        if lock is held elsewhere, which could cause faulthandler timeouts.
        
        BUG-FIX (2026-05-12): Added diagnostic logging to detect blocking operations.
        """
        logger.info("[SPOT-BASIS-TRACKER] _tick: starting")
        
        store = self._get_store()
        logger.info("[SPOT-BASIS-TRACKER] _tick: got store")
        
        feed = self._get_feed()
        logger.info("[SPOT-BASIS-TRACKER] _tick: got feed")
        
        get_all_start = time.monotonic()
        all_states = store.get_all()  # thread-safe read; returns a copy
        get_all_elapsed = (time.monotonic() - get_all_start) * 1000
        logger.info(f"[SPOT-BASIS-TRACKER] _tick: get_all returned {len(all_states)} states in {get_all_elapsed:.1f}ms")

        new_current: Dict[str, AssetBasis] = {}
        for asset in ASSETS:
            ab = self._compute_asset_basis(asset, all_states, feed)
            new_current[asset] = ab
            # Append to rolling stats only when basis_mid is meaningful
            if ab.basis_mid is not None:
                self._rolling[asset].append((time.monotonic(), ab.basis_mid))

        # Acquire lock with timeout to prevent indefinite blocking
        lock_acquired = self._lock.acquire(timeout=2.0)  # 2 second timeout
        if lock_acquired:
            try:
                self._current = new_current
            finally:
                self._lock.release()
        else:
            logger.warning("SpotBasisTracker failed to acquire lock within timeout - skipping update")

    def _compute_asset_basis(
        self,
        asset: str,
        all_states: Dict[str, Any],
        feed: Any,
    ) -> AssetBasis:
        """Compute one AssetBasis snapshot for *asset*."""
        from config.spot_basis_config import (
            ASSET_THRESHOLDS,
            COINBASE_SPOT_SYMBOLS,
            KRAKEN_SPOT_SYMBOLS,
            COINGECKO_IDS,
            KALSHI_TICKER_PREFIXES,
            SPOT_FEED_SOURCE,
            SPOT_STALE_MS,
            SPOT_MISSING_MS,
            BOOK_STALE_MS,
            BOOK_MISSING_MS,
        )
        import requests

        cfg = ASSET_THRESHOLDS.get(asset)
        
        # ── Spot feed (configurable: coinbase, kraken, coingecko) ──────────────
        spot_price: Optional[float] = None
        spot_status = FeedStatus.MISSING
        spot_source: Optional[str] = SPOT_FEED_SOURCE

        if SPOT_FEED_SOURCE == "coinbase":
            # Use Coinbase LivePriceFeed
            spot_symbol = COINBASE_SPOT_SYMBOLS.get(asset)
            if feed is not None and spot_symbol:
                price_data = (feed.price_cache or {}).get(spot_symbol)
                if price_data is not None:
                    spot_price = float(price_data.price) if price_data.price is not None else None

                last_tick = (feed._last_tick_monotonic or {}).get(spot_symbol, 0.0)
                if last_tick > 0:
                    age_ms = (time.monotonic() - last_tick) * 1000.0
                    if age_ms < SPOT_STALE_MS:
                        spot_status = FeedStatus.OK
                    elif age_ms < SPOT_MISSING_MS:
                        spot_status = FeedStatus.STALE
        
        elif SPOT_FEED_SOURCE == "kraken":
            # Use Kraken public API ticker
            spot_symbol = KRAKEN_SPOT_SYMBOLS.get(asset)
            try:
                url = "https://api.kraken.com/0/public/Ticker"
                params = {"pair": spot_symbol}
                resp = requests.get(url, params=params, timeout=5)
                resp.raise_for_status()
                data = resp.json()
                
                if data.get("error"):
                    logger.warning(f"Kraken ticker error for {spot_symbol}: {data['error']}")
                else:
                    result = data.get("result", {})
                    if result:
                        # Get first key (pair name)
                        pair_key = list(result.keys())[0]
                        ticker = result[pair_key]
                        # c = last trade price, c[0] = last closed trade price
                        spot_price = float(ticker["c"][0]) if ticker.get("c") else None
                        spot_status = FeedStatus.OK
            except Exception as e:
                logger.debug(f"Kraken ticker fetch failed for {spot_symbol}: {e}")
                spot_status = FeedStatus.MISSING
        
        elif SPOT_FEED_SOURCE == "coingecko":
            # Use CoinGecko API
            coin_id = COINGECKO_IDS.get(asset)
            try:
                url = f"https://api.coingecko.com/api/v3/simple/price"
                params = {"ids": coin_id, "vs_currencies": "usd"}
                resp = requests.get(url, params=params, timeout=5)
                resp.raise_for_status()
                data = resp.json()
                
                if coin_id in data:
                    spot_price = float(data[coin_id]["usd"])
                    spot_status = FeedStatus.OK
            except Exception as e:
                logger.debug(f"CoinGecko fetch failed for {coin_id}: {e}")
                spot_status = FeedStatus.MISSING

        # ── Kalshi book states for this asset ──────────────────────────────
        prefix = KALSHI_TICKER_PREFIXES.get(asset, "")
        asset_states: List[Any] = []
        for ticker, state in all_states.items():
            if self._state_belongs_to_asset(state, ticker, asset, prefix):
                asset_states.append(state)

        book_status = FeedStatus.MISSING
        nearest_expiry: Optional[float] = None

        if asset_states:
            initialized = [s for s in asset_states if getattr(s, "book_initialized", False)]
            if initialized:
                latest_book_ts = max(
                    getattr(s, "last_book_update_ts", 0.0) for s in initialized
                )
                if latest_book_ts > 0:
                    age_ms = (time.monotonic() - latest_book_ts) * 1000.0
                    if age_ms < BOOK_STALE_MS:
                        book_status = FeedStatus.OK
                    elif age_ms < BOOK_MISSING_MS:
                        book_status = FeedStatus.STALE
                    # else: MISSING

                expiries = [
                    getattr(s, "seconds_to_expiry", None)
                    for s in initialized
                    if getattr(s, "seconds_to_expiry", None) is not None
                    and s.seconds_to_expiry > 0
                ]
                if expiries:
                    nearest_expiry = min(expiries)

        # ── Implied spot (only when both feeds are at least STALE) ─────────
        implied_mid = implied_bid = implied_ask = None
        markets_used = 0

        if spot_status != FeedStatus.MISSING and book_status != FeedStatus.MISSING:
            implied_mid = compute_implied_spot(asset_states, "mid")
            implied_bid = compute_implied_spot(asset_states, "bid")
            implied_ask = compute_implied_spot(asset_states, "ask")
            markets_used = sum(
                1 for s in asset_states
                if getattr(s, "book_initialized", False)
                and getattr(s, "strike_price", None) is not None
            )

        # ── Basis ──────────────────────────────────────────────────────────
        basis_mid = basis_bid = basis_ask = None
        if spot_price is not None and implied_mid is not None:
            basis_mid = implied_mid - spot_price
        if spot_price is not None and implied_bid is not None:
            basis_bid = implied_bid - spot_price
        if spot_price is not None and implied_ask is not None:
            basis_ask = implied_ask - spot_price

        # ── Alignment state machine ─────────────────────────────────────────
        if spot_status == FeedStatus.MISSING or book_status == FeedStatus.MISSING:
            alignment = AlignmentState.STALE_FEED
            self._breach_counts[asset] = 0
        elif basis_mid is None:
            # Can't compute basis (no eligible cluster) → treat as aligned (fail-open)
            alignment = AlignmentState.ALIGNED
            self._breach_counts[asset] = 0
        else:
            is_breach = self._is_in_breach(basis_mid, spot_price, cfg)
            if is_breach:
                self._breach_counts[asset] += 1
            else:
                self._breach_counts[asset] = max(0, self._breach_counts[asset] - 1)

            breach_thr = cfg.breach_count_threshold if cfg else 5
            if self._breach_counts[asset] >= breach_thr:
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
            spot_source=spot_source,
            cfb_rti_alignment=cfb_alignment if 'cfb_alignment' in locals() else None,
        )

    @staticmethod
    def _state_belongs_to_asset(
        state: Any, ticker: str, asset: str, prefix: str
    ) -> bool:
        """Return True if this KalshiMarketState belongs to *asset*.

        Primary: checks state.underlying field (set by REST path).
        Fallback: checks ticker prefix (e.g. "KXBTC" for BTC).
        """
        underlying = getattr(state, "underlying", None)
        if underlying:
            return underlying.upper() == asset.upper()
        # Fallback for markets that have a book but no REST metadata yet
        return bool(prefix and ticker.upper().startswith(prefix.upper()))

    @staticmethod
    def _is_in_breach(
        basis_mid: float,
        spot_price: Optional[float],
        cfg: Any,
    ) -> bool:
        """Return True when basis_mid exceeds either the absolute or percent threshold."""
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
        """Return the abs_threshold_usd for *asset* (for rolling stats offside_pct)."""
        try:
            from config.spot_basis_config import ASSET_THRESHOLDS
            cfg = ASSET_THRESHOLDS.get(asset)
            return cfg.abs_threshold_usd if cfg else 999_999.0
        except Exception:
            return 999_999.0

    def _get_store(self) -> Any:
        if self._store is None:
            logger.info("[SPOT-BASIS-TRACKER] _get_store: initializing store singleton")
            from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
            self._store = get_kalshi_market_state_store()
            logger.info("[SPOT-BASIS-TRACKER] _get_store: store initialized")
        return self._store

    def _get_feed(self) -> Any:
        if self._feed is None:
            logger.info("[SPOT-BASIS-TRACKER] _get_feed: initializing feed singleton")
            from data.live_price_feed import get_live_price_feed
            self._feed = get_live_price_feed()
            logger.info("[SPOT-BASIS-TRACKER] _get_feed: feed initialized")
        return self._feed
