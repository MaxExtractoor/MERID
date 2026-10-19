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
  MERID_WINDOW_QUOTA_PRICE_LO           20c  sanity floor (Bürgi DP20631:
                                             sub-20c longshots bleed)
  MERID_WINDOW_QUOTA_PRICE_HI           75c  sanity ceiling (picks up
                                             pennies in front of steamroller
                                             at higher prices)
  MERID_WINDOW_QUOTA_MIN_NET_EV_CENTS   -10  claimed-EV sanity floor
                                             (tightened from -15 after
                                             high-price losses)
  MERID_WINDOW_QUOTA_MAX_SPREAD_CENTS   6    liquidity sanity — wider
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
    return _env_float("MERID_WINDOW_QUOTA_PRICE_LO", 20.0)


def quota_price_hi() -> float:
    return _env_float("MERID_WINDOW_QUOTA_PRICE_HI", 75.0)


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
    return _env_float("MERID_WINDOW_QUOTA_MIN_NET_EV_CENTS", -10.0)


def quota_max_spread_cents() -> float:
    return _env_float("MERID_WINDOW_QUOTA_MAX_SPREAD_CENTS", 6.0)


def quota_max_per_ticker() -> int:
    return int(_env_float("MERID_WINDOW_QUOTA_MAX_PER_TICKER", 3.0))


def quota_daily_max() -> int:
    return int(_env_float("MERID_WINDOW_QUOTA_DAILY_MAX", 1440.0))


def quota_min_gap_s() -> float:
    return _env_float("MERID_WINDOW_QUOTA_MIN_GAP_S", 15.0)


def quota_max_contracts() -> float:
    return _env_float("MERID_WINDOW_QUOTA_MAX_CONTRACTS", 3.0)


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
    ticker: str, path: Optional[str] = None, now: Optional[float] = None
) -> Tuple[int, int]:
    """Durable consume-then-suppress counter.  Returns
    (per_ticker_attempts, day_total) after incrementing."""
    now = time.time() if now is None else float(now)
    p = path or quota_state_path()
    st = _load_state(p, now)
    st["count"] = int(st.get("count") or 0) + 1
    tickers = st.setdefault("tickers", {})
    rec = tickers.setdefault(ticker, {"n": 0, "first_ts": now})
    rec["prev_ts"] = float(rec.get("last_ts") or 0.0)
    rec["n"] = int(rec.get("n") or 0) + 1
    rec["last_ts"] = now
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
    if rec["n"] == 0:
        tickers.pop(ticker, None)
    try:
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(json.dumps(st, separators=(",", ":")))
        os.replace(tmp, p)
    except Exception:
        pass
