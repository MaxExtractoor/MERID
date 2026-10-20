"""Window-quota lane: bounded per-ticker emission when no upstream lane
selected a side this window.

The lane exists so each asset-window produces measurable live flow even
when the model claims no positive edge: when every upstream lane declines,
the grid force-selects the ungated best side (the net-edge argmax) and
emits a bounded 1-contract taker IOC.  This is paid telemetry — the
expected value is deliberately allowed to be negative inside a capped
spend bound — not an edge claim.  Normal lane admissions always take
precedence; quota only fires on a selection that otherwise would have
been a no-trade.

Bounds (all env-tunable):
  MERID_WINDOW_QUOTA_ENABLED            default 0 (explicit opt-in)
  MERID_WINDOW_QUOTA_TTE_MIN_S          120  (never fire inside the final
                                             settlement stretch)
  MERID_WINDOW_QUOTA_TTE_MAX_S          600  (stays inside
                                             MERID_LIVE_ENTRY_MAX_TTE_S)
  MERID_WINDOW_QUOTA_PRICE_LO           25c  sanity floor (Bürgi DP20631:
                                             sub-25c longshots bleed)
  MERID_WINDOW_QUOTA_PRICE_HI           80c  sanity ceiling (avoids 85c+
                                             bounce/negative-skew traps)
  MERID_WINDOW_QUOTA_MIN_NET_EV_CENTS   -15  claimed-EV sanity floor
                                             (blocks crossed-book noise,
                                             not economics vetoes; was
                                             -25 until the -5c XRP entry
                                             rode to zero 2026-10-19)
  MERID_WINDOW_QUOTA_MAX_SPREAD_CENTS   8    liquidity sanity — wider
                                             spreads are pure bleed
  MERID_WINDOW_QUOTA_MAX_PER_TICKER     3    emission attempts per window
                                             per asset (a pre-venue reject
                                             may retry on the next tick;
                                             a fill blocks the ticker
                                             upstream via the position
                                             gate)
  MERID_WINDOW_QUOTA_DAILY_MAX          1440 total quota submissions/day;
                                             sized to exactly cover the full
                                             universe: 5 assets x 96
                                             15-minute windows x
                                             MAX_PER_TICKER(3).  The real
                                             spend limiters are the
                                             per-ticker budget, the position
                                             gate, and allocator caps — this
                                             counter is only a
                                             catastrophic-bleed bound, so it
                                             must not starve normal
                                             operation before day-end.
  MERID_WINDOW_QUOTA_MIN_GAP_S          15   minimum seconds between quota
                                             emissions on the same ticker
  MERID_WINDOW_QUOTA_P_CAP              0.99 router-side model-prob ceiling

Durable state lives at MERID_WINDOW_QUOTA_STATE_PATH (default
``data/window_quota_fills.json``) and counts submissions, not fills — a
consumed slot stays consumed even if the order is rejected pre-venue,
matching the pinned_fav/escape-lane consume-then-suppress discipline.
"""

import json
import os
import time
from datetime import datetime, timezone
from typing import Optional, Tuple


def _env_flag(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes")


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except Exception:
        return default


def quota_enabled() -> bool:
    return _env_flag("MERID_WINDOW_QUOTA_ENABLED", False)


def quota_tte_lo() -> float:
    return _env_float("MERID_WINDOW_QUOTA_TTE_MIN_S", 120.0)


def quota_tte_hi() -> float:
    return _env_float("MERID_WINDOW_QUOTA_TTE_MAX_S", 600.0)


def quota_price_lo() -> float:
    return _env_float("MERID_WINDOW_QUOTA_PRICE_LO", 25.0)


def quota_price_hi() -> float:
    return _env_float("MERID_WINDOW_QUOTA_PRICE_HI", 80.0)


def quota_band_match(price_cents: Optional[float]) -> bool:
    if price_cents is None:
        return False
    try:
        p = float(price_cents)
    except Exception:
        return False
    return quota_price_lo() <= p <= quota_price_hi()


def quota_min_ev_cents() -> float:
    """Claimed net-EV sanity floor in cents (negative).  This is not an
    edge threshold — it only rejects degenerate claims (crossed books,
    missing probability)."""
    # 2026-10-20: tightened -15 -> -6.  The -15 floor admitted paying 12c+
    # premiums over model fair - KXXRP15M-0015 bought YES@39/34 with
    # claimed EV -12.27c/-7.24c into a crashing book (-20c); KXDOGE15M-0015
    # claimed -12.41c.  The Graveyard 18k-market study measured spread-
    # crossing favorites at ~-6c/fill - claims beyond that are premium
    # chasing, not bounded telemetry.
    return _env_float("MERID_WINDOW_QUOTA_MIN_NET_EV_CENTS", -6.0)


def quota_max_spread_cents() -> float:
    return _env_float("MERID_WINDOW_QUOTA_MAX_SPREAD_CENTS", 8.0)


def quota_max_per_ticker() -> int:
    return int(_env_float("MERID_WINDOW_QUOTA_MAX_PER_TICKER", 3.0))


def quota_daily_max() -> int:
    return int(_env_float("MERID_WINDOW_QUOTA_DAILY_MAX", 1440.0))


def quota_min_gap_s() -> float:
    return _env_float("MERID_WINDOW_QUOTA_MIN_GAP_S", 15.0)


def quota_max_contracts() -> float:
    return _env_float("MERID_WINDOW_QUOTA_MAX_CONTRACTS", 3.0)


def quota_dir_absent_min_p() -> float:
    """2026-10-19: when the lane has no directional read (no asset r60 beyond
    the dir threshold, no regime label, or a demoted flip), the ungated argmax
    side is a coin-flip the lane still paid taker for — observed live as
    dir_pref=None emissions at 75-80c with -3..-10c claimed EV.  External
    evidence on 15m binaries (Turbine KXBTC15M drift study; the 237-live-trade
    calibration audit) is unambiguous that undirected taker flow cannot clear
    the ~2.5c round-trip cost.  With no directional read the emitted side must
    therefore clear a conviction floor (default 0.60) instead of the 0.25
    longshot floor — buying the measured favorite is the only argmax entry the
    evidence supports.  Set to <= the MIN_P floor to disable."""
    return _env_float("MERID_WINDOW_QUOTA_DIR_ABSENT_MIN_P", 0.60)


def quota_candidate_order(
    dir_pref: Optional[str], argmax: Optional[str]
) -> list:
    """Side try-order for the lane.  With a directional read, that side leads
    and the argmax is the fallback.  Without one, only the argmax may emit:
    the alternate side has neither model nor tape support, and buying it is
    the exact undirected-taker loss pattern this gate removes."""
    order: list = []
    if dir_pref is not None:
        order.append(dir_pref)
        if argmax is not None and argmax != dir_pref:
            order.append(argmax)
    elif argmax is not None:
        order.append(argmax)
    return order


def quota_book_drop_veto_c() -> float:
    return _env_float("MERID_WINDOW_QUOTA_BOOK_DROP_VETO_C", 6.0)


def quota_book_lookback_s() -> float:
    return _env_float("MERID_WINDOW_QUOTA_BOOK_LOOKBACK_S", 45.0)


def quota_side_book_fell(
    history,
    side: str,
    current_ask: float,
    *,
    now: Optional[float] = None,
    lookback_s: Optional[float] = None,
    drop_cents: Optional[float] = None,
) -> bool:
    """True when the side's own ask collapsed within the lookback — a
    falling ask means the book is repricing on information our lagging
    inputs (r60/regime label/model) haven't caught, and buying it is the
    dip-chase failure measured at -8.3c/fill in the Graveyard 15m study.
    ``history`` is an iterable of (ts, yes_ask, no_ask) samples; at least
    3 samples inside the lookback are required so a lone stale tick
    cannot veto.

    2026-10-20 KXXRP15M-0015: three YES emissions at asks 43/39/34 (-20c
    LOSS_CAP) — every emission bought into an already-falling book."""
    if not history:
        return False
    now = time.time() if now is None else float(now)
    lb = quota_book_lookback_s() if lookback_s is None else float(lookback_s)
    thr = quota_book_drop_veto_c() if drop_cents is None else float(drop_cents)
    idx = 1 if side == "yes" else 2
    asks = [
        float(s[idx]) for s in history
        if s and now - float(s[0]) <= lb
    ]
    if len(asks) < 3:
        return False
    return (max(asks) - float(current_ask)) >= thr


def quota_consensus_min_votes() -> int:
    return int(_env_float("MERID_WINDOW_QUOTA_CONSENSUS_MIN", 2.0))


def _ticker_window_key(ticker: str) -> Optional[str]:
    """The 15-minute window id shared by sibling series tickers —
    ``KXBTC15M-26OCT192315-15`` -> ``26OCT192315``."""
    parts = str(ticker or "").split("-")
    return parts[1] if len(parts) >= 3 else None


def quota_ticker_locked_side(
    ticker: str, path: Optional[str] = None, now: Optional[float] = None
) -> Optional[str]:
    """The side this ticker already emitted this window (a ticker lives
    exactly one window).  Recorded even when the slot was later released
    pre-wire — the whipsaw being prevented is a direction flip across
    emission decisions, not just across transmitted orders."""
    st = _load_state(path, now)
    rec = (st.get("tickers") or {}).get(ticker) or {}
    s = rec.get("side") or rec.get("first_side")
    return s if s in ("yes", "no") else None


def quota_window_consensus(
    ticker: str, path: Optional[str] = None, now: Optional[float] = None
) -> Optional[str]:
    """Majority emitted side among SIBLING tickers in the same window.

    All five series are one correlated 15-minute crypto move — a lone
    dissenter trading the opposite direction is the observed repeat-loss
    pattern (KXSOL15M-2315: YES attempt dropped pre-wire, retry flipped to
    NO@52 on a -4.8bp r60 flick while the basket bought YES and rallied
    -> -35c stopout; KXDOGE15M-2315 flipped NO->YES and was saved only by
    a lucky miss).  Only sibling records fresher than
    MERID_WINDOW_QUOTA_CONSENSUS_MAX_AGE_S (default 120s) vote — a
    majority built early in the window must not bind a dissenter minutes
    later after the basket may have genuinely turned.  Returns the
    majority side when at least MERID_WINDOW_QUOTA_CONSENSUS_MIN siblings
    recorded the same side and it strictly leads, else None."""
    key = _ticker_window_key(ticker)
    if key is None:
        return None
    now = time.time() if now is None else float(now)
    min_votes = quota_consensus_min_votes()
    max_age = _env_float("MERID_WINDOW_QUOTA_CONSENSUS_MAX_AGE_S", 120.0)
    votes = {"yes": 0, "no": 0}
    for t, rec in (_load_state(path, now).get("tickers") or {}).items():
        if t == ticker or _ticker_window_key(t) != key:
            continue
        last_ts = float((rec or {}).get("last_ts") or 0.0)
        if max_age > 0 and last_ts > 0.0 and (now - last_ts) > max_age:
            continue
        s = (rec or {}).get("side") or (rec or {}).get("first_side")
        if s in votes:
            votes[s] += 1
    if votes["yes"] == votes["no"]:
        return None
    top = "yes" if votes["yes"] > votes["no"] else "no"
    return top if votes[top] >= min_votes else None


def quota_basket_leader_side(
    ticker: str, path: Optional[str] = None, now: Optional[float] = None
) -> Optional[str]:
    """BTC's emitted side this window — the basket leader.

    2026-10-20: the crypto majors are one correlated 15-minute move and
    BTC carries the deepest book / cleanest signal — external research
    ("cross-asset BTC bleed") documents alt markets repricing 2-10s
    behind BTC.  Observed live (0300 window): BTC emitted NO under
    SELL_OFF_CONFIRMED (dir_pref=no argmax=no, -11c winner) while
    SOL/XRP/DOGE/ETH each emitted YES on +0.02-0.08bp r60 microstructure
    noise and lost their full premiums.  A sibling whose candidate
    disagrees with the leader's recorded side is vetoed — abstained, not
    flipped.  The leader's side binds siblings for the WHOLE window
    (MERID_BASKET_LEADER_MAX_AGE_S, default 900s): 2026-10-20 0430 BTC
    recorded yes at :17 (+12c) and a 180s bound let ETH emit no at :20:43
    — the veto expired mid-window and ETH lost -26c on a rallying basket.
    Returns None when the leader has no record (first emissions stay
    independent) or when this ticker IS the leader."""
    leader_series = (
        os.environ.get("MERID_BASKET_LEADER_SERIES", "KXBTC15M").strip().upper()
    )
    if not leader_series or str(ticker or "").upper().startswith(leader_series):
        return None
    key = _ticker_window_key(ticker)
    if key is None:
        return None
    now = time.time() if now is None else float(now)
    max_age = _env_float("MERID_BASKET_LEADER_MAX_AGE_S", 900.0)
    for t, rec in (_load_state(path, now).get("tickers") or {}).items():
        if not str(t).upper().startswith(leader_series + "-"):
            continue
        if _ticker_window_key(t) != key:
            continue
        last_ts = float((rec or {}).get("last_ts") or 0.0)
        if max_age > 0 and last_ts > 0.0 and (now - last_ts) > max_age:
            continue
        s = (rec or {}).get("side") or (rec or {}).get("first_side")
        if s in ("yes", "no"):
            return s
    return None


def quota_state_path() -> str:
    return os.environ.get(
        "MERID_WINDOW_QUOTA_STATE_PATH", "data/window_quota_fills.json"
    )


def _load_state(path: Optional[str] = None, now: Optional[float] = None) -> dict:
    now = time.time() if now is None else float(now)
    day = datetime.fromtimestamp(now, tz=timezone.utc).date().isoformat()
    st = {"date": day, "count": 0, "tickers": {}}
    try:
        with open(path or quota_state_path(), "r", encoding="utf-8") as f:
            rec = json.load(f)
        if rec.get("date") == day:
            st["count"] = int(rec.get("count") or 0)
            tickers = rec.get("tickers")
            if isinstance(tickers, dict):
                st["tickers"] = tickers
    except Exception:
        pass
    return st


def quota_submissions_today(
    path: Optional[str] = None, now: Optional[float] = None
) -> int:
    return int(_load_state(path, now).get("count") or 0)


def quota_ticker_attempts(
    ticker: str, path: Optional[str] = None, now: Optional[float] = None
) -> int:
    st = _load_state(path, now)
    rec = (st.get("tickers") or {}).get(ticker) or {}
    return int(rec.get("n") or 0)


def quota_ticker_exhausted(
    ticker: str, path: Optional[str] = None, now: Optional[float] = None
) -> bool:
    """Fast pre-check: per-ticker attempt budget spent, per-ticker min
    gap not elapsed, or daily cap reached.  The durable
    record_quota_submission counter remains the single source of truth —
    this read exists so the decision layer skips quickly instead of
    emitting into a suppressed slot."""
    if not ticker:
        return True
    now = time.time() if now is None else float(now)
    st = _load_state(path, now)
    if int(st.get("count") or 0) >= quota_daily_max():
        return True
    rec = (st.get("tickers") or {}).get(ticker) or {}
    if int(rec.get("n") or 0) >= quota_max_per_ticker():
        return True
    last_ts = float(rec.get("last_ts") or 0.0)
    if last_ts > 0.0 and (now - last_ts) < quota_min_gap_s():
        return True
    return False


def record_quota_submission(
    ticker: str,
    path: Optional[str] = None,
    now: Optional[float] = None,
    side: Optional[str] = None,
) -> Tuple[int, int]:
    """Durable consume-then-suppress counter.  Returns
    (per_ticker_attempts, day_total) after incrementing.  ``side`` is the
    emitted outcome — retained on the ticker record (as ``first_side``
    plus the latest ``side``) so the window side-lock and basket
    consensus see the direction even when the slot is later released."""
    now = time.time() if now is None else float(now)
    p = path or quota_state_path()
    st = _load_state(p, now)
    st["count"] = int(st.get("count") or 0) + 1
    tickers = st.setdefault("tickers", {})
    rec = tickers.setdefault(ticker, {"n": 0, "first_ts": now})
    rec["prev_ts"] = float(rec.get("last_ts") or 0.0)
    rec["n"] = int(rec.get("n") or 0) + 1
    rec["last_ts"] = now
    if side in ("yes", "no"):
        rec.setdefault("first_side", side)
        rec["side"] = side
    try:
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(json.dumps(st, separators=(",", ":")))
        os.replace(tmp, p)
    except Exception:
        pass
    return int(rec["n"]), int(st["count"])


def release_quota_submission(
    ticker: str, path: Optional[str] = None, now: Optional[float] = None
) -> None:
    """Release a quota slot when a candidate is dropped pre-wire
    (e.g. GlobalAllocator KNAPSACK_CAP or pre-wire router rejection) so
    internal multi-asset contention does not exhaust the ticker's
    3-attempt window budget without transmitting an order."""
    if not ticker:
        return
    now = time.time() if now is None else float(now)
    p = path or quota_state_path()
    st = _load_state(p, now)
    tickers = st.get("tickers") or {}
    rec = tickers.get(ticker)
    if not isinstance(rec, dict) or int(rec.get("n") or 0) <= 0:
        return
    rec["n"] = max(0, int(rec.get("n") or 0) - 1)
    rec["last_ts"] = float(rec.get("prev_ts") or 0.0)
    st["count"] = max(0, int(st.get("count") or 0) - 1)
    # Keep the record when a side was emitted — the released slot frees the
    # attempt budget, but the directional memory must survive so a retry
    # cannot whipsaw onto the opposite side (2026-10-20 KXSOL15M-2315).
    if rec["n"] == 0 and not (rec.get("side") or rec.get("first_side")):
        tickers.pop(ticker, None)
    try:
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(json.dumps(st, separators=(",", ":")))
        os.replace(tmp, p)
    except Exception:
        pass
