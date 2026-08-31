"""Microstructure features for 15-minute Kalshi crypto binary signals.

All functions in this module are pure and stateless.  Callers (typically
``Crypto15mAgent``) maintain a per-ticker ring buffer of market snapshots and
pass it in.  No float is used for financial quantities; prices and sizes are
integers (cents / contracts) and only the derived *ratios* are float features.

References:
- Cont, Kukanov, Stoikov: order flow imbalance from best-bid/ask dynamics.
- Market microstructure research supplied by user for 15m crypto binaries.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Any, List, Optional, Sequence, Tuple


def _safe_log(x: float) -> float:
    return math.log(max(x, 1.0))


@dataclass(frozen=True)
class BookLevel:
    """Canonical level for book-imbalance math."""
    price_cents: int
    size: int


@dataclass
class BookSnapshot:
    """Extracted top-of-book snapshot for one outcome side.

    Prices are in *held-side* cents.  For the YES side this is the YES price;
    for the NO side this is the NO price.  Ask depth is mapped from the
    opposite side's best bid because of Kalshi's binary complementarity.
    """
    ts: float
    side: str
    bid_cents: int
    bid_size: int
    ask_cents: int
    ask_size: int


def _find_level_size(levels: Sequence[Any], price_cents: int) -> Optional[int]:
    """Return size at an exact price level, or None if missing."""
    if not levels:
        return None
    for lv in levels:
        if hasattr(lv, "price_cents"):
            if lv.price_cents == price_cents:
                return int(lv.size)
        if isinstance(lv, (list, tuple)) and len(lv) >= 2:
            if int(lv[0]) == price_cents:
                return int(lv[1])
    return None


def kalshi_state_book_levels(
    state: Any,
    side: str,
    ts: Optional[float] = None,
) -> Optional[BookSnapshot]:
    """Extract best held-side bid/ask and sizes from a ``KalshiMarketState``.

    Kalshi's binary orderbook stores YES bids in ``state.yes_bids`` and NO bids
    in ``state.no_bids``.  The ask side of one outcome is the bid side of the
    other at price ``100 - bid``.
    """
    if state is None:
        return None

    side = side.lower()
    if side == "yes":
        bid_cents = getattr(state, "best_bid_cents", None)
        ask_cents = getattr(state, "best_ask_cents", None)
        bid_levels = getattr(state, "yes_bids", None)
        ask_levels = getattr(state, "no_bids", None)  # NO bid == YES ask
    elif side == "no":
        bid_cents = getattr(state, "best_no_bid_cents", None)
        ask_cents = getattr(state, "best_no_ask_cents", None)
        if bid_cents is None or bid_cents == 0:
            yes_ask = getattr(state, "best_ask_cents", None)
            bid_cents = 100 - yes_ask if yes_ask is not None else None
        if ask_cents is None or ask_cents == 0:
            yes_bid = getattr(state, "best_bid_cents", None)
            ask_cents = 100 - yes_bid if yes_bid is not None else None
        bid_levels = getattr(state, "no_bids", None)
        ask_levels = getattr(state, "yes_bids", None)  # YES bid == NO ask
    else:
        raise ValueError(f"side must be 'yes' or 'no', got {side!r}")

    if bid_cents is None or ask_cents is None:
        return None

    if ts is None:
        ts = getattr(state, "last_book_update_ts", None) or time.time()

    bid_size = _find_level_size(bid_levels, bid_cents)
    # Ask side for YES = NO bid at (100 - YES ask); for NO = YES bid at (100 - NO ask)
    if side == "yes":
        ask_mirror_price = 100 - ask_cents
    else:
        ask_mirror_price = 100 - ask_cents
    ask_size = _find_level_size(ask_levels, ask_mirror_price)

    # Fallback: top_of_book_size is the sum of best-bid + best-ask sizes.
    # If we can only get one side, use the total and assume roughly half each.
    if bid_size is None and ask_size is None:
        total = getattr(state, "top_of_book_size", 0)
        if total > 0:
            bid_size = int(total / 2)
            ask_size = total - bid_size
    elif bid_size is None:
        bid_size = 0
    elif ask_size is None:
        ask_size = 0

    return BookSnapshot(
        ts=ts,
        side=side,
        bid_cents=int(bid_cents),
        bid_size=int(bid_size),
        ask_cents=int(ask_cents),
        ask_size=int(ask_size),
    )


def ofi_event(prev: BookSnapshot, curr: BookSnapshot) -> float:
    """Cont-Kukanov-Stoikov event between two consecutive book snapshots.

    ``e_n = +q_bid[n]  if P_bid[n]  >  P_bid[n-1]``
          ``-q_bid[n-1] if P_bid[n]  <  P_bid[n-1]``
          ``-q_ask[n]   if P_ask[n]  <  P_ask[n-1]``
          ``+q_ask[n-1] if P_ask[n]  >  P_ask[n-1]``

    Equal prices contribute size change directly: the formula reduces to the
    change in bid/ask size when price is unchanged.
    """
    e = 0.0

    # Bid side: demand
    if curr.bid_cents > prev.bid_cents:
        e += float(curr.bid_size)
    elif curr.bid_cents < prev.bid_cents:
        e -= float(prev.bid_size)
    else:
        e += float(curr.bid_size - prev.bid_size)

    # Ask side: supply (subtracted)
    if curr.ask_cents < prev.ask_cents:
        e -= float(curr.ask_size)
    elif curr.ask_cents > prev.ask_cents:
        e += float(prev.ask_size)
    else:
        e -= float(curr.ask_size - prev.ask_size)

    return e


def ofi_window(history: Sequence[BookSnapshot], window_s: float) -> float:
    """Aggregate OFI events over the trailing ``window_s`` seconds.

    ``history`` is in chronological order; the last element is current.
    Returns the signed sum of events.  Empty or singleton history returns 0.0.
    """
    if len(history) < 2:
        return 0.0
    cutoff = history[-1].ts - window_s
    total = 0.0
    for i in range(1, len(history)):
        if history[i].ts >= cutoff and history[i - 1].ts >= cutoff:
            total += ofi_event(history[i - 1], history[i])
    return total


def book_imbalance_ratio(snapshot: BookSnapshot) -> float:
    """Simple top-of-book imbalance: (bid_size - ask_size) / (bid_size + ask_size)."""
    total = float(snapshot.bid_size + snapshot.ask_size)
    if total == 0:
        return 0.0
    return (float(snapshot.bid_size - snapshot.ask_size)) / total


def log_depth_imbalance(snapshot: BookSnapshot) -> float:
    """Log difference between bid and ask top-of-book size."""
    return _safe_log(float(snapshot.bid_size)) - _safe_log(float(snapshot.ask_size))


def spread_cents(snapshot: BookSnapshot) -> int:
    """Held-side bid-ask spread in cents."""
    return max(0, snapshot.ask_cents - snapshot.bid_cents)


def top_book_depth_ratio(snapshot: BookSnapshot) -> float:
    """Bid size / ask size (top of book).  Returns 1.0 when balanced."""
    if snapshot.ask_size == 0:
        return float(snapshot.bid_size) if snapshot.bid_size > 0 else 1.0
    return float(snapshot.bid_size) / float(snapshot.ask_size)


def book_pressure_edge(
    snapshot: BookSnapshot,
    side: str,
    max_edge_pct: float = 2.0,
) -> float:
    """Translate book imbalance into a signed edge adjustment for ``side``.

    Positive imbalance -> positive edge for the held side; negative -> negative.
    The result is capped in percentage points (default ±2pp) so it cannot
    dominate Bachelier or other well-grounded components.
    """
    imb = book_imbalance_ratio(snapshot)
    return max(-max_edge_pct, min(max_edge_pct, imb * max_edge_pct))


def compute_microstructure_features(
    state: Any,
    side: str,
    history: Optional[Sequence[BookSnapshot]] = None,
    ofi_window_s: float = 30.0,
) -> Optional[dict]:
    """Compute a dictionary of microstructure features for one held side.

    If ``history`` is provided, an OFI feature is included; otherwise OFI is 0.
    All values are floats except ``spread_cents``.
    """
    snap = kalshi_state_book_levels(state, side)
    if snap is None:
        return None

    features: dict = {
        "book_imbalance": book_imbalance_ratio(snap),
        "log_depth_imbalance": log_depth_imbalance(snap),
        "spread_cents": spread_cents(snap),
        "bid_size": snap.bid_size,
        "ask_size": snap.ask_size,
        "bid_cents": snap.bid_cents,
        "ask_cents": snap.ask_cents,
        "depth_ratio": top_book_depth_ratio(snap),
    }

    if history:
        side_history = [h for h in history if h.side == side]
        features["ofi"] = ofi_window(side_history + [snap], ofi_window_s)
    else:
        features["ofi"] = 0.0

    return features


# ---------------------------------------------------------------------------
# Cross-asset lead-lag
# ---------------------------------------------------------------------------

@dataclass
class SpotHistory:
    """Small ring buffer of (ts, spot) for cross-asset return computation."""
    window_s: float
    spots: List[Tuple[float, float]] = None  # type: ignore

    def __post_init__(self):
        if self.spots is None:
            self.spots = []

    def update(self, ts: float, spot: float) -> None:
        """Add a spot observation and drop stale entries."""
        if not math.isfinite(spot) or spot <= 0:
            return
        self.spots.append((ts, spot))
        cutoff = ts - self.window_s
        while self.spots and self.spots[0][0] < cutoff:
            self.spots.pop(0)

    def log_return(self) -> float:
        """Log return of the asset over the window.  0 if insufficient data."""
        if len(self.spots) < 2:
            return 0.0
        first = self.spots[0][1]
        last = self.spots[-1][1]
        if first <= 0:
            return 0.0
        return math.log(last / first)


def cross_asset_lead_lag(
    base_hist: SpotHistory,
    target_spot: float,
    beta: float = 1.0,
    max_edge_pct: float = 2.0,
) -> float:
    """Return a signed edge adjustment from base-asset return to target asset.

    Base return is interpreted as short-horizon information that the target
    market's own price has not fully impounded.  The research finds
    BTC → altcoin predictability persists up to ~10 minutes, inside the 15m
    expiry window, with a one-sigma base move worth ~4.8 bps per minute.
    """
    base_ret = base_hist.log_return()
    if not math.isfinite(base_ret) or base_ret == 0.0:
        return 0.0
    # Translate log return into percentage points, scaled by a small beta.
    # 1% log return -> beta * max_edge_pct percentage points of edge.
    edge = base_ret * 100.0 * beta * max_edge_pct
    return max(-max_edge_pct, min(max_edge_pct, edge))


def compute_microstructure_signals(
    state: Any,
    history: Optional[Sequence[BookSnapshot]] = None,
    ofi_window_s: float = 30.0,
    max_edge_pct: float = 2.0,
    base_spot_history: Optional[SpotHistory] = None,
    target_spot: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    """Compute a unified microstructure signal from a ``KalshiMarketState``.

    Returns YES/NO feature dictionaries plus a signed edge adjustment in
    percentage points (positive = higher p_yes, negative = lower p_yes).
    The edge combines top-of-book pressure on both sides and, when a BTC
    spot history is supplied, a cross-asset lead-lag component.
    """
    yes_features = compute_microstructure_features(
        state, "yes", history=history, ofi_window_s=ofi_window_s
    )
    no_features = compute_microstructure_features(
        state, "no", history=history, ofi_window_s=ofi_window_s
    )
    if yes_features is None and no_features is None:
        return None

    yes_snap = kalshi_state_book_levels(state, "yes")
    no_snap = kalshi_state_book_levels(state, "no")
    yes_edge_pp = book_pressure_edge(yes_snap, "yes", max_edge_pct) if yes_snap else 0.0
    no_edge_pp = book_pressure_edge(no_snap, "no", max_edge_pct) if no_snap else 0.0
    # YES pressure raises p_yes; NO pressure lowers it.
    book_delta_pp = (yes_edge_pp - no_edge_pp) / 2.0

    cross_delta_pp = 0.0
    if base_spot_history is not None and target_spot is not None:
        cross_delta_pp = cross_asset_lead_lag(
            base_spot_history, target_spot, beta=1.0, max_edge_pct=max_edge_pct
        )

    return {
        "yes_features": yes_features,
        "no_features": no_features,
        "yes_edge_pp": yes_edge_pp,
        "no_edge_pp": no_edge_pp,
        "book_delta_pp": book_delta_pp,
        "cross_delta_pp": cross_delta_pp,
        "total_delta_pp": book_delta_pp + cross_delta_pp,
    }
