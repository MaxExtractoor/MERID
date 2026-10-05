"""Canonical executable-quote resolution for Kalshi binary markets.

Single source of truth for translating a ``KalshiMarketState`` + held side +
purpose into either an ``ExecutableQuote`` (fresh, sequence-valid,
duality-clean, side-correct) or a structured ``QuoteUnavailable`` explaining
exactly which gate rejected the quote.

Consumers (entry engine, position monitor exits, stop candidates,
settlement-aligned exits, hard-profit lock) must all resolve prices through
this module so that "executable" means the same thing everywhere.  Prices are
NEVER derived from midpoint, last trade, model fair value, or stale state.

Book model (Kalshi ``orderbook_fp``):
- ``yes_levels`` carries YES bids {price_cents: size}
- ``no_levels``  carries NO bids
- YES ask = 100 - best NO bid ; NO ask = 100 - best YES bid
- A NO exit sells into NO bids (direct) ; its reciprocal is the YES ask ladder
- A YES exit sells into YES bids (direct) ; its reciprocal is the NO ask ladder
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, List, Optional, Tuple

from merid.event_venues.kalshi.models import KalshiMarketState
from utils.logger import get_logger

logger = get_logger(__name__)


class QuotePurpose:
    ENTRY = "entry"      # buying the held side (walk the held-side ask ladder)
    EXIT = "exit"        # selling the held side (walk the held-side bid ladder)
    MARK = "mark"        # mark-to-market evaluation (same side as exit)


class QuoteUnavailableReason:
    """Canonical terminal reasons.  Stable strings - consumed by the
    opportunity scorecard and hard-lock recovery paths."""
    STATE_MISSING = "STATE_MISSING"
    BOOK_NOT_INITIALIZED = "BOOK_NOT_INITIALIZED"
    BOOK_NOT_EXECUTABLE = "BOOK_NOT_EXECUTABLE"
    BOOK_QUALITY_NOT_TRUSTED = "BOOK_QUALITY_NOT_TRUSTED"
    BOOK_UNCONFIRMED_SEQUENCE = "BOOK_UNCONFIRMED_SEQUENCE"
    QUOTE_STALE = "QUOTE_STALE"
    HELD_SIDE_BID_UNAVAILABLE = "HELD_SIDE_BID_UNAVAILABLE"
    HELD_SIDE_ASK_UNAVAILABLE = "HELD_SIDE_ASK_UNAVAILABLE"


@dataclass(frozen=True)
class ExecutableQuote:
    """A fresh, trusted, side-correct executable quote for one exact ticker.

    ``best_bid_cents`` / ``best_ask_cents`` are in the HELD side's price space
    (own-side convention used throughout the position monitor).
    """

    ticker: str
    held_side: str                      # "yes" | "no"
    purpose: str                        # QuotePurpose

    # Own-side top of book (None if that leg is absent from a trusted book)
    best_bid_cents: Optional[int]
    best_ask_cents: Optional[int]

    # Depth: size at the touched top level and VWAP over ``quantity``
    best_level_size: int = 0            # contracts at the touched level
    vwap_cents: Optional[float] = None  # depth-weighted executable price for qty
    available_depth: int = 0            # contracts covering the walked ladder
    depth_sufficient: bool = False      # True when available_depth >= quantity
    quantity: int = 1

    # Provenance / trust
    derived_from_reciprocal: bool = False   # True when price came from the
                                            # opposite-side ladder / fallback
    corrected_to_rest: bool = False         # True when a locked/crossed WS top
                                            # diverged from fresh REST and the
                                            # REST-derived bid won
    quote_source: str = ""                  # data_source / quote_owner
    data_quality: str = "UNKNOWN"
    book_health: str = "NO_SNAPSHOT"
    book_consistency: str = "GOOD"
    book_sequence: Optional[int] = None     # last applied WS delta seq
    quote_age_ms: float = 0.0
    snapshot_monotonic_ts: float = 0.0      # last_book_update_ts
    seconds_to_expiry: Optional[float] = None

    # Walked ladder ((price_cents, size) held-side, best-first) for audit
    levels: Tuple[Tuple[int, int], ...] = ()


@dataclass(frozen=True)
class QuoteUnavailable:
    """Structured refusal: which gate rejected the quote and what was seen."""

    ticker: str
    held_side: str
    purpose: str
    reason: str                          # QuoteUnavailableReason
    detail: str = ""

    observed_bid_cents: Optional[int] = None
    observed_ask_cents: Optional[int] = None
    data_quality: str = "UNKNOWN"
    data_source: str = ""
    book_health: str = "NO_SNAPSHOT"
    book_sequence: Optional[int] = None
    quote_age_ms: Optional[float] = None
    seconds_to_expiry: Optional[float] = None


def _ladder_levels(levels: Any) -> List[Tuple[int, int]]:
    """Normalize a ladder payload (state.yes_bids / state.no_bids) into a
    list of (price_cents, size) sorted best-first (descending price).

    Accepts lists of tuples/lists/dicts; silently drops malformed rows.
    """
    out: List[Tuple[int, int]] = []
    if not levels or not isinstance(levels, (list, tuple)):
        return out
    for lvl in levels:
        price = size = None
        if isinstance(lvl, (tuple, list)) and len(lvl) >= 2:
            price, size = lvl[0], lvl[1]
        elif isinstance(lvl, dict):
            price = lvl.get("price_cents", lvl.get("price"))
            size = lvl.get("size", lvl.get("count"))
        else:
            price = getattr(lvl, "price_cents", getattr(lvl, "price", None))
            size = getattr(lvl, "size", getattr(lvl, "count", None))
        try:
            p = int(price)
            s = int(size)
        except (TypeError, ValueError):
            continue
        if s > 0 and 0 < p < 100:
            out.append((p, s))
    out.sort(key=lambda x: x[0], reverse=True)
    return out


def _as_price(value: Any) -> Optional[int]:
    """Coerce a book price to int cents; non-numeric or out-of-range -> None."""
    try:
        p = int(value)  # noqa: E722 - bool/numeric coercion only
    except (TypeError, ValueError):
        return None
    if not (0 < p < 100):
        return None
    return p


def _as_size(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _vwap(levels: List[Tuple[int, int]], quantity: int) -> Tuple[Optional[float], int, int]:
    """Walk ``levels`` (best-first, in the trade's own price space) for
    ``quantity`` contracts.

    Returns (vwap_cents, contracts_covered, top_level_size).  If the ladder
    does not fully cover ``quantity`` the VWAP is over the covered depth only
    and ``contracts_covered < quantity``.
    """
    if quantity <= 0:
        return None, 0, 0
    total_cost = 0
    covered = 0
    top_size = levels[0][1] if levels else 0
    for price, size in levels:
        take = min(size, quantity - covered)
        if take <= 0:
            break
        total_cost += price * take
        covered += take
        if covered >= quantity:
            break
    if covered <= 0:
        return None, 0, top_size
    return total_cost / covered, covered, top_size


def _held_ladders(state: KalshiMarketState, held_side: str) -> Tuple[List[Tuple[int, int]], List[Tuple[int, int]]]:
    """Return (direct_ladder, reciprocal_ladder) in the held side's price space.

    - YES: direct = yes_bids (YES bid side) ; reciprocal asks = no_bids mapped
      100-p (NO bids are YES asks).
    - NO:  direct = no_bids ; reciprocal = yes_bids mapped 100-p.
    """
    yes_levels = _ladder_levels(getattr(state, "yes_bids", None))
    no_levels = _ladder_levels(getattr(state, "no_bids", None))
    if held_side == "yes":
        direct = yes_levels
        reciprocal = [(100 - p, s) for p, s in no_levels]
    else:
        direct = no_levels
        reciprocal = [(100 - p, s) for p, s in yes_levels]
    # Reciprocal ladder is an ask book in held-side space: cheapest first.
    reciprocal.sort(key=lambda x: x[0])
    return direct, reciprocal


def _rest_divergence_corrected_bid(
    state: KalshiMarketState, held_side: str
) -> Optional[int]:
    """Fresh REST-derived held-side bid when the raw WS top is locked/crossed
    (ws_bid >= ws_ask) and diverges from a just-fetched REST book beyond
    ``MERID_EXIT_QUOTE_DIVERGENCE_CENTS``.

    A locked WS top that disagrees with a fresh REST snapshot is a split-tape
    artifact: the local ladder lost a repricing burst and the apparent bid is
    a phantom an IOC can never hit.  Same semantics as
    ``stop_candidate._locked_ws_divergent_rest_bid`` — unified here so entry,
    exit, and hard-lock paths agree on what is executable.
    """
    try:
        ws_bid = getattr(state, "last_ws_bid_cents", None)
        ws_ask = getattr(state, "last_ws_ask_cents", None)
        if ws_bid is None or ws_ask is None or int(ws_bid) < int(ws_ask):
            return None
        rest_bid = getattr(state, "last_rest_bid_cents", None)
        rest_ask = getattr(state, "last_rest_ask_cents", None)
        rest_ts = getattr(state, "last_rest_quote_update_ts", 0.0) or 0.0
        if not isinstance(rest_ts, (int, float)):
            return None
        max_rest_age_s = float(os.environ.get("MERID_EXIT_QUOTE_REST_MAX_AGE_S", "5.0"))
        if (
            rest_bid is None
            or rest_ask is None
            or rest_ts <= 0
            or (time.monotonic() - rest_ts) > max_rest_age_s
        ):
            return None
        ws_held_bid = int(ws_bid) if held_side == "yes" else 100 - int(ws_ask)
        rest_held_bid = int(rest_bid) if held_side == "yes" else 100 - int(rest_ask)
        if not (0 < rest_held_bid < 100):
            return None
        div_cap = int(os.environ.get("MERID_EXIT_QUOTE_DIVERGENCE_CENTS", "3"))
        if abs(ws_held_bid - rest_held_bid) <= div_cap:
            return None
        return rest_held_bid
    except Exception:
        return None


def resolve_executable_quote(
    ticker: str,
    held_side: str,
    quantity: int = 1,
    purpose: str = QuotePurpose.EXIT,
    required_freshness_ms: Optional[float] = None,
    state: Optional[KalshiMarketState] = None,
) -> Any:
    """Resolve the canonical executable quote for ``held_side`` on ``ticker``.

    Trust gates (in order, each producing a distinct ``QuoteUnavailable``):
      1. state present
      2. book_initialized
      3. executable (duality / book-health)
      4. data_quality == GOOD (unless source attests otherwise)
      5. live_sequence_confirmed when source is BOOTSTRAP_VALID_BUT_UNCONFIRMED
      6. freshness (``required_freshness_ms``; None = no freshness gate)
      7. held-side top-of-book present (direct ladder first, then effective
         BBO fallbacks that market_state already merged from ticker/REST)

    Never falls back to midpoint, last trade, model fair value, or a stale
    snapshot.  Reciprocal derivation is used only for *marking* the missing
    leg of a trusted book, never to invent an executable price.
    """
    held_side = (held_side or "").lower()
    if held_side not in ("yes", "no"):
        return QuoteUnavailable(
            ticker=ticker, held_side=held_side or "unknown", purpose=purpose,
            reason="INVALID_HELD_SIDE", detail=f"held_side={held_side!r}",
        )

    now = time.monotonic()
    quantity = max(1, int(quantity or 1))

    def _unavail(reason: str, detail: str = "", st: Optional[KalshiMarketState] = state) -> QuoteUnavailable:
        bid = ask = None
        age_ms = None
        if st is not None:
            if held_side == "yes":
                bid = _as_price(getattr(st, "best_bid_cents", None))
                ask = _as_price(getattr(st, "best_ask_cents", None))
            else:
                bid = _as_price(getattr(st, "best_no_bid_cents", None))
                ask = _as_price(getattr(st, "best_no_ask_cents", None))
            _ts = getattr(st, "last_book_update_ts", None)
            if isinstance(_ts, (int, float)) and _ts:
                age_ms = (now - _ts) * 1000.0
        return QuoteUnavailable(
            ticker=ticker, held_side=held_side, purpose=purpose, reason=reason,
            detail=detail,
            observed_bid_cents=bid, observed_ask_cents=ask,
            data_quality=getattr(st, "data_quality", "UNKNOWN") or "UNKNOWN",
            data_source=getattr(st, "data_source", "") or "",
            book_health=getattr(st, "book_health", "NO_SNAPSHOT") or "NO_SNAPSHOT",
            book_sequence=getattr(st, "ws_last_seq", None),
            quote_age_ms=age_ms,
            seconds_to_expiry=getattr(st, "seconds_to_expiry", None),
        )

    # ── Trust gates ──────────────────────────────────────────────────────
    if state is None:
        return _unavail(QuoteUnavailableReason.STATE_MISSING, "no market state", None)

    if getattr(state, "book_initialized", False) is False:
        return _unavail(QuoteUnavailableReason.BOOK_NOT_INITIALIZED,
                        "book_initialized=False")

    if getattr(state, "executable", False) is False:
        return _unavail(QuoteUnavailableReason.BOOK_NOT_EXECUTABLE,
                        f"executable=False transition={getattr(state, 'transition', '')}")

    dq = getattr(state, "data_quality", "UNKNOWN")
    if isinstance(dq, str) and dq != "GOOD":
        return _unavail(QuoteUnavailableReason.BOOK_QUALITY_NOT_TRUSTED,
                        f"data_quality={dq}")

    src = getattr(state, "data_source", "") or ""
    if (src == "BOOTSTRAP_VALID_BUT_UNCONFIRMED"
            and not getattr(state, "live_sequence_confirmed", False)):
        return _unavail(QuoteUnavailableReason.BOOK_UNCONFIRMED_SEQUENCE,
                        "bootstrap snapshot without live-sequence confirmation")

    _raw_ts = getattr(state, "last_book_update_ts", None)
    last_book_ts = float(_raw_ts) if isinstance(_raw_ts, (int, float)) else 0.0
    age_ms = (now - last_book_ts) * 1000.0 if last_book_ts else None
    if required_freshness_ms is not None and last_book_ts:
        if age_ms is not None and age_ms > required_freshness_ms:
            return _unavail(QuoteUnavailableReason.QUOTE_STALE,
                            f"age={age_ms:.0f}ms > {required_freshness_ms:.0f}ms")

    # ── Held-side resolution ─────────────────────────────────────────────
    direct, reciprocal = _held_ladders(state, held_side)

    if held_side == "yes":
        eff_bid = _as_price(getattr(state, "best_bid_cents", None))
        eff_ask = _as_price(getattr(state, "best_ask_cents", None))
    else:
        eff_bid = _as_price(getattr(state, "best_no_bid_cents", None))
        eff_ask = _as_price(getattr(state, "best_no_ask_cents", None))

    # The effective BBO already merges ticker-quote and REST fallbacks; the
    # direct ladder may be empty while a verified fallback carries the level.
    direct_best = direct[0][0] if direct else None
    bid_from_ladder = direct_best is not None and direct_best == eff_bid

    derived = False
    corrected_to_rest = False
    bid_cents = eff_bid
    ask_cents = eff_ask

    # Split-tape correction: a locked/crossed WS top that diverges from a
    # fresh REST book means the effective bid is a phantom.  For exits the
    # REST-derived bid is the only executable reference.
    if purpose != QuotePurpose.ENTRY:
        _rest_bid = _rest_divergence_corrected_bid(state, held_side)
        if _rest_bid is not None and _rest_bid != bid_cents:
            logger.warning(
                "[EXECUTABLE-QUOTE-DIVERGENT] ticker=%s held=%s ws_bid=%sc rest_bid=%sc "
                "- locked WS top diverges from fresh REST; pricing off REST",
                ticker, held_side, bid_cents, _rest_bid,
            )
            bid_cents = _rest_bid
            corrected_to_rest = True
            bid_from_ladder = direct_best is not None and direct_best == bid_cents

    if purpose == QuotePurpose.ENTRY:
        # Buying: walk the reciprocal ladder (opposite bids are our asks).
        trade_levels = reciprocal
        touched = ask_cents
        missing_reason = QuoteUnavailableReason.HELD_SIDE_ASK_UNAVAILABLE
    else:
        # Exiting / marking: sell into the direct bid ladder.
        trade_levels = direct
        touched = bid_cents
        missing_reason = QuoteUnavailableReason.HELD_SIDE_BID_UNAVAILABLE

    if touched is None:
        # One-sided or empty on the held side even after fallbacks.
        return _unavail(
            missing_reason,
            f"held_{held_side}_{'ask' if purpose == QuotePurpose.ENTRY else 'bid'}"
            f" absent (ladder_levels={len(trade_levels)})",
        )

    if not bid_from_ladder and purpose != QuotePurpose.ENTRY:
        # Effective bid exists but the direct ladder doesn't carry it (e.g.
        # REST/ticker fallback owns the quote).  Still trusted: the trust
        # gates above already validated the owner.  Mark as reciprocal.
        derived = True
        if not trade_levels:
            _sz = getattr(state, "no_bid_size" if held_side == "no" else "yes_bid_size", 0)
            trade_levels = [(touched, _as_size(_sz) or 1)]

    if purpose == QuotePurpose.ENTRY and not trade_levels:
        derived = True
        top_size = 0
        try:
            top_size = _as_size(state.get_executable_ask_size(held_side, ask_cents))
        except Exception:
            top_size = 0
        trade_levels = [(ask_cents, top_size or 1)]

    vwap, covered, top_size = _vwap(trade_levels, quantity)
    total_depth = sum(s for _, s in trade_levels)

    # Missing leg marking: for an exit quote whose ask side is absent, derive
    # it reciprocally for telemetry only (not executable).
    if purpose != QuotePurpose.ENTRY and ask_cents is None and reciprocal:
        ask_cents = reciprocal[0][0]
        derived = True
    if purpose == QuotePurpose.ENTRY and bid_cents is None and direct:
        bid_cents = direct[0][0]
        derived = True

    return ExecutableQuote(
        ticker=ticker,
        held_side=held_side,
        purpose=purpose,
        best_bid_cents=bid_cents,
        best_ask_cents=ask_cents,
        best_level_size=top_size,
        vwap_cents=vwap,
        available_depth=total_depth,
        depth_sufficient=covered >= quantity,
        quantity=quantity,
        derived_from_reciprocal=derived,
        corrected_to_rest=corrected_to_rest,
        quote_source=src or getattr(state, "quote_owner", "") or "",
        data_quality=dq or "UNKNOWN",
        book_health=getattr(state, "book_health", "NO_SNAPSHOT") or "NO_SNAPSHOT",
        book_consistency=getattr(state, "book_consistency", "GOOD") or "GOOD",
        book_sequence=getattr(state, "ws_last_seq", None),
        quote_age_ms=age_ms or 0.0,
        snapshot_monotonic_ts=last_book_ts,
        seconds_to_expiry=getattr(state, "seconds_to_expiry", None),
        levels=tuple(trade_levels[:10]),
    )


__all__ = [
    "ExecutableQuote",
    "QuoteUnavailable",
    "QuotePurpose",
    "QuoteUnavailableReason",
    "resolve_executable_quote",
]
