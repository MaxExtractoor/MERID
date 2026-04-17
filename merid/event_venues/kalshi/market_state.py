"""KalshiMarketStateStore — unified per-market live state.

Owns the merge point between:
  - WS ``orderbook_snapshot`` / ``orderbook_delta`` messages
  - REST ``GET /markets`` responses

Produces ``KalshiMarketState`` per ticker so every consumer — agents,
order router, UI API — reads a single consistent structure instead of
separate ad-hoc dicts.

Usage::

    from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store

    store = get_kalshi_market_state_store()

    # WS side (called from your ws bridge/handler):
    store.apply_orderbook_message(ws_msg)

    # REST side (called from your market scanner/A5 check):
    store.apply_rest_market(market_dict)

    # Consumers:
    state = store.get("KXBTCD-25JUN-T100000")
    if state and state.seconds_to_expiry is not None:
        use(state.seconds_to_expiry)
"""

from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from merid.event_venues.kalshi.models import KalshiMarketState
from merid.event_venues.kalshi.orderbook import LocalOrderbook, MultiMarketOrderbook
from merid.event_venues.kalshi.unified_market_state import (
    Candlestick,
    ExternalIndexSnapshot,
    OrderbookLevel,
    OrderbookSnapshot,
    UnifiedMarketState,
    recompute_derived,
)
from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.market_state")

# Orders placed when secondsToExpiry is below this threshold are auto-downgraded
# to IoC so they never rest on the book past settlement.
IOC_AUTO_BELOW_SECONDS: int = int(os.getenv("MERID_KALSHI_IOC_BELOW_SECS", "600"))

_TOP_N_BOOK_LEVELS = 10
_DEPTH_WINDOW_CENTS = 10


class KalshiMarketStateStore:
    """Thread-safe registry of KalshiMarketState keyed by ticker.

    Two independent write paths — neither blocks the other:

    **WS path** (``apply_orderbook_message``)
      Feeds ``orderbook_snapshot`` and ``orderbook_delta`` WS messages
      into a ``MultiMarketOrderbook``, then syncs the book-owned slice
      of ``KalshiMarketState``.

    **REST path** (``apply_rest_market``)
      Feeds a raw market dict from ``GET /markets`` into the REST-owned
      slice (volume_24h, open_interest, notional_value_cents, expiry).
      Also recomputes ``seconds_to_expiry``.
    """

    # H3: Max number of pending deltas queued per ticker while waiting for
    #     a snapshot.  Keeps memory bounded.  Oldest deltas are dropped when
    #     the queue is full so only the most recent context is replayed.
    _MAX_PENDING_DELTAS = 20

    def __init__(self) -> None:
        self._states: Dict[str, KalshiMarketState] = {}
        self._unified: Dict[str, UnifiedMarketState] = {}
        self._ob: MultiMarketOrderbook = MultiMarketOrderbook()
        self._lock = threading.Lock()
        # H3: per-ticker queue of delta messages received before snapshot.
        self._pending_deltas: Dict[str, List[Dict[str, Any]]] = {}

    # ── WS path ────────────────────────────────────────────────────────

    def apply_orderbook_message(self, msg: Dict[str, Any]) -> Optional[KalshiMarketState]:
        """Apply a WS ``orderbook_snapshot`` or ``orderbook_delta`` message.

        Updates the internal ``LocalOrderbook`` for the ticker, then
        syncs the book-owned fields of the corresponding
        ``KalshiMarketState``.

        Args:
            msg: Raw parsed WS message dict (already JSON-decoded).

        Returns:
            Updated ``KalshiMarketState``, or ``None`` if the message
            type is not an orderbook message or the ticker is missing.
        """
        channel = msg.get("type") or msg.get("channel", "")
        ticker = msg.get("ticker") or msg.get("market_ticker", "")
        if not ticker:
            return None

        with self._lock:
            if channel == "orderbook_snapshot":
                payload = msg.get("msg", msg)
                self._ob.apply_snapshot(ticker, payload)
                # H3: Replay any deltas that arrived before this snapshot.
                pending = self._pending_deltas.pop(ticker, [])
                for _delta in pending:
                    try:
                        self._ob.apply_delta(ticker, _delta)
                    except Exception as _re:
                        logger.debug(
                            "[market-state] replayed delta failed for %s: %s",
                            ticker, _re,
                        )
                if pending:
                    logger.debug(
                        "[market-state] replayed %d pending delta(s) for %s after snapshot",
                        len(pending), ticker,
                    )
            elif channel == "orderbook_delta":
                ob = self._ob.get_book(ticker)
                if not ob.initialized:
                    # H3: Queue the delta for replay when the snapshot arrives.
                    queue = self._pending_deltas.setdefault(ticker, [])
                    queue.append(msg)
                    if len(queue) > self._MAX_PENDING_DELTAS:
                        queue.pop(0)  # drop oldest to stay bounded
                    logger.debug(
                        "[market-state] queued pre-snapshot delta for %s (%d pending)",
                        ticker, len(queue),
                    )
                    return None
                self._ob.apply_delta(ticker, msg)
            else:
                return None

            state = self._get_or_create(ticker)
            self._sync_book_fields(state, self._ob.get_book(ticker))
            self._sync_unified_book(ticker, state)
            return state

    # ── REST path ──────────────────────────────────────────────────────

    def apply_rest_market(self, data: Dict[str, Any]) -> Optional[KalshiMarketState]:
        """Merge REST ``GET /markets`` fields into a ``KalshiMarketState``.

        Owns: ``volume_24h``, ``open_interest``, ``notional_value_cents``,
        all three expiry fields, and strike/underlying metadata.

        ``liquidity`` / ``liquidity_dollars`` are intentionally ignored —
        they are deprecated and always return 0.  Use ``top_of_book_size``
        and ``depth_10c`` (book-computed) instead.

        Args:
            data: Raw market dict from the Kalshi REST API.  SDK
                  ``Market`` objects should be converted via
                  ``model.model_dump()`` or ``vars(model)`` first.

        Returns:
            Updated ``KalshiMarketState``, or ``None`` if no ticker.
        """
        ticker = data.get("ticker")
        if not ticker:
            return None

        with self._lock:
            state = self._get_or_create(ticker)

            v24 = data.get("volume_24h")
            if v24 is not None:
                state.volume_24h = int(v24)

            oi = data.get("open_interest")
            if oi is not None:
                state.open_interest = int(oi)

            nv = data.get("notional_value")
            if nv is not None:
                state.notional_value_cents = int(nv)

            for attr, key in (
                ("expiration_time", "expiration_time"),
                ("expected_expiration_time", "expected_expiration_time"),
                ("latest_expiration_time", "latest_expiration_time"),
            ):
                val = data.get(key)
                if val:
                    setattr(state, attr, str(val))

            # NEW: Underlying asset and strike info (from catalog)
            underlying = data.get("underlying")
            if underlying:
                state.underlying = underlying

            strike = data.get("strike_price")
            if strike is not None:
                state.strike_price = float(strike)

            floor = data.get("floor_strike")
            if floor is not None:
                state.floor_strike = float(floor)

            cap = data.get("cap_strike")
            if cap is not None:
                state.cap_strike = float(cap)

            # External spot price (from CF Benchmarks RTI or other feed)
            spot = data.get("external_spot")
            if spot is not None:
                state.external_spot = float(spot)

            state.last_rest_update_ts = time.monotonic()
            _recompute_seconds_to_expiry(state)
            self._sync_unified_rest(ticker, state)
            return state

    # ── Quote path (from WS QuoteEvent) ─────────────────────────────────

    def apply_quote(
        self,
        ticker: str,
        *,
        bid_cents: Optional[int] = None,
        ask_cents: Optional[int] = None,
        last_cents: Optional[int] = None,
        volume: Optional[int] = None,
    ) -> Optional[KalshiMarketState]:
        """Lightweight update from a WS quote/ticker channel event.

        Fills in bid/ask/mid/spread when no orderbook subscription exists
        for this ticker.  If the book is already initialized from the
        orderbook channel, this is a no-op for bid/ask (book data is
        more authoritative), but volume is always updated.
        """
        if not ticker:
            return None
        with self._lock:
            state = self._get_or_create(ticker)

            if volume is not None:
                state.volume_24h = int(volume)

            # Only fill bid/ask/mid from quotes when book is NOT initialized
            # (orderbook data is higher fidelity).
            if not state.book_initialized:
                if bid_cents is not None:
                    state.best_bid_cents = bid_cents
                if ask_cents is not None:
                    state.best_ask_cents = ask_cents
                if bid_cents is not None and ask_cents is not None:
                    state.mid_cents = (bid_cents + ask_cents) // 2
                    state.spread_cents = ask_cents - bid_cents
                elif last_cents is not None:
                    state.mid_cents = last_cents

            state.last_book_update_ts = time.monotonic()
            return state

    # ── Read ───────────────────────────────────────────────────────────

    def get(self, ticker: str) -> Optional[KalshiMarketState]:
        """Return the current state for *ticker*, or ``None`` if unknown."""
        with self._lock:
            return self._states.get(ticker)

    def get_unified(self, ticker: str) -> Optional[UnifiedMarketState]:
        """Return the ``UnifiedMarketState`` for *ticker*, or ``None`` if unknown.

        ``UnifiedMarketState`` carries all derived consensus fields
        (``implied_prob``, ``external_fair_value``, ``edge_basis``) that
        ``KalshiMarketState`` does not have.  Agents and risk systems should
        prefer this when they need those fields.
        """
        with self._lock:
            return self._unified.get(ticker)

    def get_all(self) -> Dict[str, KalshiMarketState]:
        """Return a shallow copy of the full state registry."""
        with self._lock:
            return dict(self._states)

    def tickers(self) -> List[str]:
        """Return a snapshot of all tracked tickers."""
        with self._lock:
            return list(self._states.keys())

    def is_stale(self, ticker: str, max_age_seconds: float = 30.0) -> bool:
        """Return True if *ticker*'s book has not been updated within *max_age_seconds*.

        H3: Consumers (e.g. order router market-condition check) should call
        this to refuse to trade on a book that has gone silent after a WS
        reconnect.  A ticker that has never been seen is also considered stale.
        """
        with self._lock:
            state = self._states.get(ticker)
            if state is None or not state.book_initialized:
                return True
            # D-H3: use explicit > 0.0 guard so that the never-set sentinel
            # (last_book_update_ts=0.0) is treated as infinite age rather than
            # computing (monotonic() - 0.0) = monotonic() which could be less
            # than a very large max_age_seconds.
            if state.last_book_update_ts <= 0.0:
                return True
            age = time.monotonic() - state.last_book_update_ts
            return age > max_age_seconds

    # ── Candle / external-index write paths ────────────────────────────

    def apply_candle_dict(
        self,
        ticker: str,
        bar: Dict[str, Any],
        *,
        period_interval: int = 60,
    ) -> Optional[UnifiedMarketState]:
        """Merge a raw candlestick dict into the per-ticker ``UnifiedMarketState``.

        Called by ``CandlePoller`` after each successful REST fetch.
        The bar dict is expected to have Kalshi-style keys:
        ``ts``, ``open``, ``high``, ``low``, ``close``, ``volume``.
        Price values are in cents (0–100).

        Returns the updated ``UnifiedMarketState``, or ``None`` if *ticker*
        or the bar dict is invalid.
        """
        if not ticker or not bar:
            return None

        # ── Synthetic bar guard ─────────────────────────────────────────────
        # Kalshi's include_latest_before_start can prepend a synthetic candle
        # where OHLC are null and only previous_price is set. Reject these
        # to avoid feeding fake 0-price bars into the state machine.
        close = bar.get("close") or bar.get("close_cents")
        ts = bar.get("ts") or bar.get("start_ts")
        if close is None or ts is None:
            logger.debug("[market-state] Ignoring synthetic/malformed bar for %s", ticker)
            return None
        # ─────────────────────────────────────────────────────────────────────

        try:
            candle = Candlestick(
                ticker=ticker,
                ts=float(bar.get("ts") or bar.get("start_ts") or time.time()),
                open_cents=int(bar.get("open") or bar.get("open_cents") or 0),
                high_cents=int(bar.get("high") or bar.get("high_cents") or 0),
                low_cents=int(bar.get("low") or bar.get("low_cents") or 0),
                close_cents=int(bar.get("close") or bar.get("close_cents") or 0),
                volume=int(bar.get("volume") or 0),
                open_interest=int(bar.get("open_interest") or 0),
                period_interval=period_interval,
            )
        except (TypeError, ValueError) as exc:
            logger.debug("[market-state] apply_candle_dict bad bar for %s: %s", ticker, exc)
            return None

        with self._lock:
            u = self._get_or_create_unified(ticker)
            u.latest_candle = candle
            # Keep candles list bounded to last 100 bars (newest at end)
            u.candles.append(candle)
            if len(u.candles) > 100:
                u.candles = u.candles[-100:]
            u.candle_updated_ts = candle.ts
            recompute_derived(u)
            return u

    def apply_external_index(
        self,
        ticker: str,
        snapshot: ExternalIndexSnapshot,
    ) -> Optional[UnifiedMarketState]:
        """Merge an ``ExternalIndexSnapshot`` into the per-ticker ``UnifiedMarketState``.

        Called by the CFB RTI adapter or any external price feed after each tick.
        Triggers ``recompute_derived()`` so ``index_updated_ts``, ``edge_basis``,
        and ``external_fair_value`` are updated immediately.

        D-C1 safety: ``recompute_derived`` guards against ``snapshot.ts is None``
        internally — no crash even if the feed delivers a corrupt tick.
        """
        if not ticker or snapshot is None:
            return None
        with self._lock:
            u = self._get_or_create_unified(ticker)
            u.external = snapshot
            recompute_derived(u)
            return u

    # ── Internal helpers ───────────────────────────────────────────────

    def _get_or_create(self, ticker: str) -> KalshiMarketState:
        if ticker not in self._states:
            self._states[ticker] = KalshiMarketState(ticker=ticker)
        return self._states[ticker]

    def _get_or_create_unified(self, ticker: str) -> UnifiedMarketState:
        """Return the ``UnifiedMarketState`` for *ticker*, creating it if absent.

        Must be called with ``self._lock`` held.
        """
        if ticker not in self._unified:
            self._unified[ticker] = UnifiedMarketState(ticker=ticker)
        return self._unified[ticker]

    def _sync_unified_book(self, ticker: str, state: KalshiMarketState) -> None:
        """Rebuild the book snapshot in ``UnifiedMarketState`` from *state* and
        call ``recompute_derived()``.

        Must be called with ``self._lock`` held.
        """
        u = self._get_or_create_unified(ticker)

        # Build typed OrderbookSnapshot from the flat KalshiMarketState fields.
        # D-H2: require BOTH sides to be non-empty before assembling a snapshot.
        # A one-sided book produces spread_cents=None, mid_cents=None, and
        # implied_prob=None — all None — which confuses downstream consumers.
        yes_bids_raw = state.yes_bids or []
        no_bids_raw = state.no_bids or []

        if not yes_bids_raw or not no_bids_raw:
            # One-sided or empty book — do not assemble a snapshot.
            # Leave u.book as-is (None on first update; keep last valid book
            # until a two-sided book arrives so stale-book detection still fires).
            u.book = None
            recompute_derived(u)
            return

        def _to_levels(raw: list) -> tuple:
            levels = []
            for item in raw:
                if isinstance(item, (list, tuple)) and len(item) >= 2:
                    levels.append(OrderbookLevel(price_cents=int(item[0]), size=int(item[1])))
                elif isinstance(item, dict):
                    levels.append(
                        OrderbookLevel(
                            price_cents=int(item.get("price", item.get("price_cents", 0))),
                            size=int(item.get("size", item.get("quantity", 0))),
                        )
                    )
            return tuple(levels)

        book = OrderbookSnapshot(
            ticker=ticker,
            yes_bids=_to_levels(yes_bids_raw),
            no_bids=_to_levels(no_bids_raw),
            ts=time.time(),
        )
        u.book = book
        u.book_updated_ts = time.time()
        u.volume_24h = state.volume_24h
        u.open_interest = state.open_interest
        u.seconds_to_expiry = state.seconds_to_expiry
        recompute_derived(u)

    def _sync_unified_rest(self, ticker: str, state: KalshiMarketState) -> None:
        """Propagate REST-owned fields into ``UnifiedMarketState`` and
        call ``recompute_derived()``.

        Must be called with ``self._lock`` held.
        """
        u = self._get_or_create_unified(ticker)
        u.volume_24h = state.volume_24h
        u.open_interest = state.open_interest
        u.seconds_to_expiry = state.seconds_to_expiry
        u.rest_updated_ts = time.time()
        recompute_derived(u)

    def _sync_book_fields(
        self, state: KalshiMarketState, ob: LocalOrderbook
    ) -> None:
        """Copy the book-owned fields from a ``LocalOrderbook`` into *state*."""
        state.book_initialized = ob.initialized
        state.last_book_update_ts = time.monotonic()

        if not ob.initialized:
            return

        state.yes_bids = ob.get_book("yes", top_n=_TOP_N_BOOK_LEVELS)
        state.no_bids = ob.get_book("no", top_n=_TOP_N_BOOK_LEVELS)

        best_bid = ob.get_best_bid()    # (price_cents, size) or None
        best_ask = ob.get_best_ask()    # (yes_equivalent_cents, size) or None
        mid = ob.get_midpoint()

        state.best_bid_cents = best_bid[0] if best_bid else None
        state.best_ask_cents = best_ask[0] if best_ask else None
        state.mid_cents = mid
        state.spread_cents = ob.get_spread()

        # top_of_book_size: size at best bid + size at best ask (no-side)
        state.top_of_book_size = (
            (best_bid[1] if best_bid else 0)
            + (best_ask[1] if best_ask else 0)
        )

        # depth_10c: total contracts within ±10¢ of mid on both sides
        if mid is not None:
            lo = int(mid) - _DEPTH_WINDOW_CENTS
            hi = int(mid) + _DEPTH_WINDOW_CENTS
            yes_depth = sum(
                sz for p, sz in ob.yes_levels.items() if lo <= p <= hi
            )
            # no_levels keyed by no_price; yes-equivalent = 100 - no_price
            no_depth = sum(
                sz
                for p, sz in ob.no_levels.items()
                if lo <= (100 - p) <= hi
            )
            state.depth_10c = yes_depth + no_depth
        else:
            state.depth_10c = 0


# ── Helpers ────────────────────────────────────────────────────────────────


def _recompute_seconds_to_expiry(state: KalshiMarketState) -> None:
    """Recompute ``state.seconds_to_expiry`` in-place from expiry ISO strings."""
    expiry_str = state.expected_expiration_time or state.expiration_time
    if not expiry_str:
        state.seconds_to_expiry = None
        return
    try:
        expiry_dt = datetime.fromisoformat(expiry_str.replace("Z", "+00:00"))
        # If Kalshi returns a naive datetime (no tzinfo), assume UTC
        if expiry_dt.tzinfo is None:
            expiry_dt = expiry_dt.replace(tzinfo=timezone.utc)
        now_dt = datetime.now(timezone.utc)
        state.seconds_to_expiry = max(0.0, (expiry_dt - now_dt).total_seconds())
    except (ValueError, TypeError) as exc:
        logger.debug("Could not parse expiry %r for %s: %s", expiry_str, state.ticker, exc)
        state.seconds_to_expiry = None


# ── Singleton ──────────────────────────────────────────────────────────────

_store: Optional[KalshiMarketStateStore] = None
_store_lock = threading.Lock()


def get_kalshi_market_state_store() -> KalshiMarketStateStore:
    """Return the process-wide ``KalshiMarketStateStore`` singleton."""
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = KalshiMarketStateStore()
    return _store
