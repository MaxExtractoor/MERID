"""Unified per-ticker market state schema for MERID's DISCOVER→PROTECT pipeline.

Normalizes three data sources into a single read model agents share:

  1. **Kalshi L2 orderbook**  — REST snapshot + WS deltas
     ``GET /markets/{ticker}/orderbook`` → bids/asks for YES and NO sides
  2. **Kalshi candlesticks**  — OHLCV bars from REST
     ``GET /markets/{ticker}/candlesticks`` → configurable-interval bars
  3. **External crypto index** — spot price or CFB RTI when available

Pipeline alignment
------------------
  DISCOVER  — ticker, asset, timeframe, seconds_to_expiry, volume_24h, oi
  ANALYZE   — book (spread/depth/imbalance), candles (vol/range/trend), external
  CONSENSUS — implied_prob, external_fair_value, edge_basis
  SIZE      — depth_10c, spread_cents, kelly_fraction_hint
  EXECUTE   — book.best_yes_bid/ask, seconds_to_expiry, spread_cents
  MONITOR   — book_age_s, candle_age_s, index_age_s; stale flag trio
  PROMOTE   — candles list for dashboard chart rendering
  PROTECT   — book_stale, index_stale, spread_blown, in_settlement_window
"""
from __future__ import annotations

import time as _time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


# ── L2 orderbook primitives ───────────────────────────────────────────────────

@dataclass(frozen=True)
class OrderbookLevel:
    """Single price level in a Kalshi L2 orderbook.

    Prices are in cents (1–99 for YES side).
    NO side mirrors: ``100 - yes_price`` due to Kalshi's binary duality.
    """

    price_cents: int
    size: int  # contracts available at this level


@dataclass(frozen=True)
class OrderbookSnapshot:
    """Typed, immutable L2 orderbook snapshot for one market.

    Kalshi's YES-centric convention:
      ``yes_bids`` — descending by price (index 0 = best YES bid)
      ``no_bids``  — descending by price (index 0 = best NO bid →
                     best YES ask = 100 − no_bids[0].price_cents)

    Derived properties expose the L1 view, spread, depth, and imbalance
    that agents need for ANALYZE / SIZE / EXECUTE.
    """

    ticker: str
    yes_bids: Tuple[OrderbookLevel, ...]  # sorted descending
    no_bids: Tuple[OrderbookLevel, ...]   # sorted descending
    seq: int = 0
    ts: float = 0.0  # unix epoch

    @property
    def best_yes_bid(self) -> Optional[int]:
        return self.yes_bids[0].price_cents if self.yes_bids else None

    @property
    def best_yes_ask(self) -> Optional[int]:
        """Best YES ask = 100 − best NO bid (Kalshi binary duality)."""
        return (100 - self.no_bids[0].price_cents) if self.no_bids else None

    @property
    def spread_cents(self) -> Optional[float]:
        ask, bid = self.best_yes_ask, self.best_yes_bid
        return float(ask - bid) if ask is not None and bid is not None else None

    @property
    def mid_cents(self) -> Optional[float]:
        ask, bid = self.best_yes_ask, self.best_yes_bid
        return (ask + bid) / 2.0 if ask is not None and bid is not None else None

    @property
    def implied_prob(self) -> Optional[float]:
        """Implied YES probability derived from the mid-price."""
        m = self.mid_cents
        return m / 100.0 if m is not None else None

    def depth_within(self, cents: int) -> int:
        """YES contracts within *cents* of the best bid (slippage estimation)."""
        bid = self.best_yes_bid
        if bid is None:
            return 0
        return sum(lv.size for lv in self.yes_bids if lv.price_cents >= bid - cents)

    def imbalance(self) -> Optional[float]:
        """Order imbalance: (yes_sz − no_sz) / (yes_sz + no_sz).

        Ranges from −1 (pure NO pressure) to +1 (pure YES pressure).
        Short-term directional ANALYZE feature for the consensus layer.
        """
        yes_sz = sum(lv.size for lv in self.yes_bids)
        no_sz = sum(lv.size for lv in self.no_bids)
        total = yes_sz + no_sz
        return (yes_sz - no_sz) / total if total > 0 else None


# ── Candlestick ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Candlestick:
    """Kalshi OHLCV candlestick bar.

    Prices are in cents (YES probability × 100, range 0–100).
    ``ts`` is the bar open time in seconds since epoch.
    ``period_interval`` is bar duration in seconds (60 = 1-min, 900 = 15-min).
    Source: ``GET /markets/{ticker}/candlesticks``
    """

    ticker: str
    ts: float
    open_cents: int
    high_cents: int
    low_cents: int
    close_cents: int
    volume: int
    open_interest: int = 0
    period_interval: int = 60  # seconds

    @property
    def range_cents(self) -> int:
        return self.high_cents - self.low_cents

    @property
    def close_prob(self) -> float:
        return self.close_cents / 100.0

    @property
    def is_bullish(self) -> bool:
        return self.close_cents >= self.open_cents


# ── External crypto index ─────────────────────────────────────────────────────

@dataclass
class ExternalIndexSnapshot:
    """Normalized external crypto price — the fair-value reference for agents.

    Source priority (best → worst):
      1. CFB RTI live feed  (``MERID_CFB_RTI_ADAPTER=live``)
      2. CFB RTI simulation ticks
      3. Free REST API      (CoinGecko, Binance public)
      4. Stub / synthetic

    Agents use ``price_usd`` to compute the fair YES probability for
    strike-based contracts and derive ``edge_basis`` vs the Kalshi book mid.
    """

    asset: str          # "BTC", "ETH", "SOL", "XRP", "DOGE"
    price_usd: float
    ts: float           # unix epoch
    source: str         # "cfb_rti" | "coingecko" | "binance" | "stub"
    volume_24h_usd: float = 0.0
    change_24h_pct: float = 0.0
    # RTI rolling metrics — populated when source == "cfb_rti"
    rti_60s_sma: Optional[float] = None
    rti_60s_vol: Optional[float] = None     # realized vol (not annualized)


# ── Unified read model ────────────────────────────────────────────────────────

@dataclass
class UnifiedMarketState:
    """Per-ticker read model shared across all MERID pipeline phases.

    ``KalshiMarketStateStore`` assembles this on every WS book update,
    REST poll, candle tick, or external index update — whichever fires.

    Agents and risk systems **read** from this object; they never write to it
    directly.  All mutations go through the store's update methods.

    Identity fields (DISCOVER)
    --------------------------
    ``ticker``, ``asset``, ``timeframe``, ``seconds_to_expiry``,
    ``volume_24h``, ``open_interest``

    Analysis fields (ANALYZE)
    -------------------------
    ``book`` → spread, depth, imbalance
    ``candles`` → realized vol, range, trend
    ``external`` → spot price, RTI SMA/vol

    Consensus inputs (CONSENSUS / SIZE)
    ------------------------------------
    ``implied_prob``, ``external_fair_value``, ``edge_basis``,
    ``kelly_fraction_hint``, ``depth_10c``

    Execution shortcuts (EXECUTE)
    -----------------------------
    ``mid_cents``, ``spread_cents``, ``book.best_yes_bid/ask``

    Observability (MONITOR / PROTECT)
    -----------------------------------
    ``book_age_s``, ``candle_age_s``, ``index_age_s``
    ``book_stale``, ``index_stale``, ``spread_blown``,
    ``in_settlement_window``
    """

    # ── Identity ──────────────────────────────────────────────────────────
    ticker: str
    asset: Optional[str] = None        # "BTC", "ETH", etc.
    timeframe: Optional[str] = None    # "15m", "1h", "daily"
    question: str = ""

    # ── Data sources ──────────────────────────────────────────────────────
    book: Optional[OrderbookSnapshot] = None
    latest_candle: Optional[Candlestick] = None  # Last CLOSED bar (Kalshi OHLCV); forming bar excluded
    candles: List[Candlestick] = field(default_factory=list)  # recent bars, newest last
    external: Optional[ExternalIndexSnapshot] = None

    # ── REST metadata ─────────────────────────────────────────────────────
    volume_24h: int = 0
    open_interest: int = 0
    seconds_to_expiry: Optional[float] = None

    # ── Derived consensus inputs (set by store after each update) ─────────
    implied_prob: Optional[float] = None
    external_fair_value: Optional[float] = None   # P(YES) from external price vs strike
    edge_basis: Optional[float] = None            # implied_prob − external_fair_value
    kelly_fraction_hint: Optional[float] = None   # |edge_basis| / max_loss

    # ── Freshness timestamps ──────────────────────────────────────────────
    book_updated_ts: float = 0.0
    candle_updated_ts: float = 0.0
    rest_updated_ts: float = 0.0
    index_updated_ts: float = 0.0

    # ── PROTECT flags (set by store, read by execution gate) ──────────────
    book_stale: bool = False
    index_stale: bool = False
    spread_blown: bool = False
    in_settlement_window: bool = False  # seconds_to_expiry ≤ 60

    # ── Derived convenience properties ───────────────────────────────────

    @property
    def mid_cents(self) -> Optional[float]:
        return self.book.mid_cents if self.book else None

    @property
    def spread_cents(self) -> Optional[float]:
        return self.book.spread_cents if self.book else None

    @property
    def depth_10c(self) -> int:
        """YES contracts within 10 cents of best bid."""
        return self.book.depth_within(10) if self.book else 0

    @property
    def imbalance(self) -> Optional[float]:
        return self.book.imbalance() if self.book else None

    @property
    def book_age_s(self) -> float:
        return _time.time() - self.book_updated_ts

    @property
    def candle_age_s(self) -> float:
        return _time.time() - self.candle_updated_ts

    @property
    def index_age_s(self) -> float:
        return _time.time() - self.index_updated_ts

    def is_tradeable(
        self,
        *,
        max_book_age_s: float = 5.0,
        max_index_age_s: float = 30.0,
        max_spread_cents: float = 15.0,
    ) -> bool:
        """PROTECT gate: True when state is fresh, spread is tight, and no stale flags.

        Defaults are conservative — callers should tighten for live trading.
        """
        if self.book_stale or self.index_stale or self.spread_blown:
            return False
        if self.book_updated_ts and self.book_age_s > max_book_age_s:
            return False
        if self.index_updated_ts and self.index_age_s > max_index_age_s:
            return False
        s = self.spread_cents
        if s is not None and s > max_spread_cents:
            return False
        return True

    def freshness_summary(self) -> dict:
        """Compact dict for MONITOR / dashboard logging."""
        return {
            "ticker": self.ticker,
            "book_age_s": round(self.book_age_s, 2),
            "candle_age_s": round(self.candle_age_s, 2),
            "index_age_s": round(self.index_age_s, 2),
            "book_stale": self.book_stale,
            "index_stale": self.index_stale,
            "spread_blown": self.spread_blown,
            "in_settlement_window": self.in_settlement_window,
            "spread_cents": self.spread_cents,
            "mid_cents": self.mid_cents,
            "implied_prob": self.implied_prob,
            "edge_basis": self.edge_basis,
            "depth_10c": self.depth_10c,
            "imbalance": self.imbalance,
        }


# ── Derived-field recomputation ───────────────────────────────────────────────


def recompute_derived(state: "UnifiedMarketState") -> None:
    """Populate all derived consensus and freshness fields on *state* in-place.

    Called by the store after any of the three data sources (book, candles,
    external index) is updated.  Safe to call multiple times — idempotent.

    D-C1 fix
    --------
    ``state.index_updated_ts`` is set from ``state.external.ts`` only when
    both ``state.external`` and ``state.external.ts`` are non-None.  If either
    is None the field falls back to ``0.0`` (never-updated sentinel) to prevent
    ``TypeError: unsupported operand type(s) for -: 'float' and 'NoneType'``
    downstream in ``index_age_s`` and age comparisons.

    D-C2 fix
    --------
    ``implied_prob``, ``external_fair_value``, and ``edge_basis`` were
    previously never computed; all consumers silently received ``None`` and
    skipped trades.  This function now:

    * Derives ``implied_prob`` from the book mid-price (cents → 0–1 float).
    * Reads ``external_fair_value`` from ``getattr(external, "fair_prob", None)``
      so that subclasses or duck-typed snapshots that carry a pre-computed fair
      probability are honoured without requiring a schema change on
      ``ExternalIndexSnapshot``.
    * Computes ``edge_basis = implied_prob − external_fair_value`` (rounded to
      4 d.p.) when both inputs are available.
    """
    external = state.external

    # ── D-C1: guard external.ts before arithmetic ───────────────────────────
    if external is not None and getattr(external, "ts", None) is not None:
        state.index_updated_ts = float(external.ts)
    else:
        state.index_updated_ts = 0.0

    # ── Implied probability from book mid ───────────────────────────────────
    book = state.book
    mid_cents: Optional[float] = book.mid_cents if book is not None else None
    implied: Optional[float] = (mid_cents / 100.0) if mid_cents is not None else None
    state.implied_prob = implied

    # ── D-C2: external_fair_value and edge_basis ────────────────────────────
    ext_fp: Optional[float] = (
        getattr(external, "fair_prob", None) if external is not None else None
    )
    if ext_fp is not None:
        state.external_fair_value = float(ext_fp)
        if implied is not None:
            state.edge_basis = round(implied - float(ext_fp), 4)
        else:
            state.edge_basis = None
    else:
        state.external_fair_value = None
        state.edge_basis = None
