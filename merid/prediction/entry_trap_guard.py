"""Shared anti-trap admission guard — applies to EVERY emitted entry lane.

2026-10-20 audit findings this gate exists to stop:

* The window-quota book-drop veto was lane-local, so other lanes kept
  buying into collapsing books.  KXBTC15M-0515 emitted YES@59 while its
  own ask fell 66->59c in 9s; KXETH15M-0515 YES@36 carried a -11.5c/30s
  markout; DOGE/XRP same-window YES emits hit the same pattern.  A
  falling own-side ask is informed flow repricing faster than our lagging
  inputs (r60/regime/calibration) can see — buying it is the measured
  dip-chase failure (Graveyard 15m study: -8.3c/fill).
* Sticky-calibration phantom edge: the candidate's claimed edge appeared
  only because the market moved while p_calibrated did not.  When the
  own-side ask drops materially but the model claim is static, the edge
  is not real — it is staleness.
* Whipsaw / flat regimes: FlatTrapFilter flags chop where any directional
  entry pays spread+fees for noise.  The trap veto applies to every lane;
  the flat veto applies only to spread-crossing (taker) emissions — a
  resting maker bid in a flat book is the one externally-validated edge
  on this product, while a taker buy in a flat book is a guaranteed bleed.
* Correlated-basket stacking: all five 15m crypto series are one move.
  2026-10-20 0515 emitted YES on all five series into a single down leg
  (BTC -59c, ETH -36c, DOGE -26c).  Same-direction emissions across the
  basket are capped per window (MERID_BASKET_SAME_SIDE_MAX, default 2).

Everything here is a pure function of already-collected per-ticker history
plus a small process-local emission registry — no I/O, no venue calls.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Dict, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("merid.prediction.entry_trap_guard")


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except Exception:
        return default


def _env_flag(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes")


# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

def trap_veto_enabled() -> bool:
    """Master switch for the shared gate.  Default ON."""
    return _env_flag("MERID_ENTRY_TRAP_VETO_ENABLED", True)


def book_lookback_s() -> float:
    return _env_float("MERID_ENTRY_TRAP_LOOKBACK_S", 45.0)


def book_drop_veto_c() -> float:
    """Own-side ask drop inside the lookback that vetoes the entry."""
    return _env_float("MERID_ENTRY_TRAP_DROP_C", 5.0)


def sticky_p_drop_c() -> float:
    """Smaller ask drop that vetoes when the model claim did not move."""
    return _env_float("MERID_ENTRY_TRAP_STICKY_P_DROP_C", 3.0)


def sticky_p_max_dp() -> float:
    """Max |Δp_calibrated| (probability units) tolerated as 'static'."""
    return _env_float("MERID_ENTRY_TRAP_STICKY_P_MAX_DP", 0.02)


def flat_trap_enabled() -> bool:
    return _env_flag("MERID_ENTRY_FLAT_TRAP_ENABLED", True)


def exempt_lanes() -> Tuple[str, ...]:
    """Lanes exempt from the sticky-p veto (banked-sample p is legitimately
    static for the settlement-convergence lane — its edge IS the divergence
    between the banked average and the terminal tick the book quotes)."""
    raw = os.environ.get(
        "MERID_ENTRY_TRAP_EXEMPT_LANES", "settlement_convergence"
    )
    return tuple(s.strip() for s in raw.split(",") if s.strip())


def basket_same_side_max() -> int:
    """Max same-direction emissions per 15m window across the 5 correlated
    crypto series.  2 lets a leader + one follower through; the 2026-10-20
    five-way same-side basket is the pattern this cap removes."""
    return int(_env_float("MERID_BASKET_SAME_SIDE_MAX", 2.0))


# ---------------------------------------------------------------------------
# Sample layout + accessors
# ---------------------------------------------------------------------------
# History samples are tuples:
#   7-tuple (current): (ts, yes_bid, yes_ask, no_bid, no_ask, p_yes_cal, p_no_cal)
#   3-tuple (legacy):  (ts, yes_ask, no_ask)
# ``p_*`` entries may be None when the decision's calibrated fields were
# unavailable; sticky-p checks skip unrecorded samples.

def side_ask(sample, side: str) -> Optional[float]:
    try:
        if len(sample) >= 7:
            v = sample[2] if side == "yes" else sample[4]
        else:
            v = sample[1] if side == "yes" else sample[2]
        return float(v) if v is not None else None
    except Exception:
        return None


def side_bid(sample, side: str) -> Optional[float]:
    try:
        if len(sample) < 7:
            return None
        v = sample[1] if side == "yes" else sample[3]
        return float(v) if v is not None else None
    except Exception:
        return None


def side_mid_cents(sample, side: str) -> Optional[float]:
    a = side_ask(sample, side)
    b = side_bid(sample, side)
    if a is None:
        return None
    if b is None:
        return a
    return (a + b) / 2.0


def side_p(sample, side: str) -> Optional[float]:
    try:
        if len(sample) < 7:
            return None
        v = sample[5] if side == "yes" else sample[6]
        return float(v) if v is not None else None
    except Exception:
        return None


def record_sample(
    hist: Dict[str, object],
    key: str,
    ts: float,
    yes_bid: Optional[float],
    yes_ask: Optional[float],
    no_bid: Optional[float],
    no_ask: Optional[float],
    p_yes_cal: Optional[float] = None,
    p_no_cal: Optional[float] = None,
    maxlen: int = 240,
) -> None:
    """Append a BBO+model snapshot to ``hist[key]`` (a bounded deque)."""
    from collections import deque

    dq = hist.get(key)
    if dq is None:
        dq = deque(maxlen=maxlen)
        hist[key] = dq
    dq.append((float(ts), yes_bid, yes_ask, no_bid, no_ask, p_yes_cal, p_no_cal))


# ---------------------------------------------------------------------------
# Vetoes
# ---------------------------------------------------------------------------

def _window_samples(history, now: float, lookback_s: float) -> list:
    out = []
    for s in history or ():
        try:
            if s and now - float(s[0]) <= lookback_s:
                out.append(s)
        except Exception:
            continue
    return out


def entry_book_veto(
    history,
    side: str,
    *,
    lane: Optional[str] = None,
    crosses_spread: bool = True,
    now: Optional[float] = None,
) -> Optional[str]:
    """Return a veto reason string, or None when the entry may proceed.

    ``history`` is the per-ticker deque of recorded samples (see module
    docstring for the layout); ``side`` is ``"yes"``/``"no"``;
    ``crosses_spread`` marks emissions that will execute as taker/marketable
    — the flat-book veto only applies to those.
    """
    if not trap_veto_enabled() or side not in ("yes", "no"):
        return None
    now = time.time() if now is None else float(now)
    samples = _window_samples(history, now, book_lookback_s())
    asks = [a for a in (side_ask(s, side) for s in samples) if a is not None]
    if len(asks) >= 3:
        drop = max(asks) - asks[-1]
        if drop >= book_drop_veto_c():
            return f"own_side_ask_falling:{drop:.0f}c"
        # Sticky-calibration veto: book fell materially but the p claim is
        # static — the apparent edge is staleness, not signal.  Exempt lanes
        # (settlement_convergence) legitimately hold a static banked-sample p.
        _exempt = str(lane or "") in exempt_lanes()
        if drop >= sticky_p_drop_c() and not _exempt:
            ps = [
                p for p in (side_p(s, side) for s in samples)
                if p is not None
            ]
            if len(ps) >= 3 and abs(ps[-1] - ps[0]) <= sticky_p_max_dp():
                return (
                    f"stale_model_divergence:ask_drop={drop:.0f}c "
                    f"dp={abs(ps[-1] - ps[0]):.3f}"
                )
    if flat_trap_enabled() and str(lane or "") not in exempt_lanes():
        # Exempt lanes profit from settlement arithmetic, not book movement —
        # a flat 95-99c book in the final minute is their normal state.
        mids = [
            m for m in (side_mid_cents(s, side) for s in samples)
            if m is not None
        ]
        if len(mids) >= 6:
            try:
                from merid.event_venues.kalshi.flat_trap_filter import (
                    FlatTrapFilter,
                )
                verdict = FlatTrapFilter().evaluate([int(round(m)) for m in mids])
                if not verdict.tradeable:
                    if verdict.reason == "trap":
                        return "mid_whipsaw_trap"
                    if verdict.reason == "flat" and crosses_spread:
                        # Resting maker bids in a flat book are the validated
                        # edge — only a taker cross pays for zero move.
                        return "flat_book_taker_cross"
            except Exception as exc:
                logger.warning(
                    "[ENTRY-TRAP-GUARD] flat/trap check failed: %s", exc
                )
    return None


# ---------------------------------------------------------------------------
# Correlated-basket emission registry (process-local)
# ---------------------------------------------------------------------------
# Keyed by the 15-minute window id shared by sibling series tickers; each
# entry records the emitted side per series.  Recording at emission (not
# fill) is deliberate — a cancelled or unfilled same-side intent still
# represents correlated risk the basket must not stack.

_REG_LOCK = threading.RLock()
_WINDOW_EMISSIONS: Dict[str, Dict[str, Tuple[str, float]]] = {}


def _ticker_window_key(ticker: str) -> Optional[str]:
    parts = str(ticker or "").split("-")
    return parts[1] if len(parts) >= 3 else None


def _ticker_series(ticker: str) -> str:
    parts = str(ticker or "").split("-")
    return parts[0].upper() if parts else ""


def record_window_emission(
    ticker: str, side: str, ts: Optional[float] = None
) -> None:
    """Record an emitted entry for basket-correlation accounting."""
    key = _ticker_window_key(ticker)
    series = _ticker_series(ticker)
    if not key or not series or side not in ("yes", "no"):
        return
    ts = time.time() if ts is None else float(ts)
    with _REG_LOCK:
        (_WINDOW_EMISSIONS.setdefault(key, {}))[series] = (side, ts)


def same_side_sibling_count(
    ticker: str, side: str, now: Optional[float] = None
) -> int:
    """Count *sibling series* in the same window already emitted on ``side``."""
    key = _ticker_window_key(ticker)
    series = _ticker_series(ticker)
    if not key or not series or side not in ("yes", "no"):
        return 0
    with _REG_LOCK:
        recs = _WINDOW_EMISSIONS.get(key) or {}
        return sum(
            1 for s, (sd, _ts) in recs.items() if s != series and sd == side
        )


def basket_same_side_veto(
    ticker: str, side: str, now: Optional[float] = None
) -> Optional[str]:
    """Veto reason when this emission would exceed the same-direction basket
    cap for the window — the five-way single-move stack observed 2026-10-20."""
    cap = basket_same_side_max()
    if cap <= 0:
        return None
    n = same_side_sibling_count(ticker, side, now)
    if n >= cap:
        return f"basket_same_side_cap:siblings={n}>=cap={cap}"
    return None


def _reset_registry_for_tests() -> None:
    with _REG_LOCK:
        _WINDOW_EMISSIONS.clear()
