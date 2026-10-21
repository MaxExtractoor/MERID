"""Drift-favorite and cheap-NO-settle lanes: bounded mid-band maker
admissions for the 15-minute crypto grid.

2026-10-21 audit (15,637 settled market samples in kalshi_15m_features):

- From 40-74c entries, only ~25-34% of contracts ever quote >=90c before
  expiry, but the average post-entry max own-side bid is ~75-82c — the
  exploitable move is the *drift*, not the 90c hard-lock.  Under a
  buy-at-bid -> exit at entry+G -> salvage at entry-14c simulation, the
  NO-side 40-74c cohort measured +0.6..+3.0c/contract (SOL/DOGE/ETH/XRP
  positive, BTC marginal) while every YES cohort was thin or negative.
- Cheap NO (10-40c own-side) is systematically *underpriced* on YES-heavy
  books — realized settle win-rates 27-48% vs 17-33c sticker (+7..+15c
  settle EV pooled).  Under every scalp exit rule the same cohort is
  *negative*: the edge exists only as a hold-to-settlement claim, so the
  lane is a micro-sized settle sleeve, not a scalper.
- External checks (237-live-trade autopsy; SSRN maker/taker study):
  taker fees at 40-55c (~1.5-1.75c) exceed the measured edge — both lanes
  admit ONLY on the bid basis (resting post-only, fee ~0) and every lane
  bound is env-bounded so the cohort stays a measured probe until its own
  fills replace the pooled evidence.

Lane contracts:

- ``decision_lane="drift_fav"``: rescue-admission when the own-side bid
  sits in [DRIFT_LO, DRIFT_HI] with TTE in [DRIFT_TTE_LO, DRIFT_TTE_HI]
  and the claimed net EV clears DRIFT_MIN_NET_EV (default -2c — the
  pooled EV is ~0 under the reserve stack; a mild negative buffer for
  reserve noise, much tighter than pinned_fav's -12c probe floor).  The
  generic economics path still owns normal admissions in the band — the
  lane only rescues candidates the formula bound rejects.  Positions
  stamped with the lane carry a per-position profit-lock target of
  entry + MERID_DRIFT_LOCK_GAIN_CENTS (default 12c) instead of the global
  90c threshold, and retain the standard salvage floor.
- ``decision_lane="cheap_no_settle"``: NO-side-only settle sleeve for
  10-40c books on YES-heavy markets (complement >=55c).  Bounded claim
  floor (default -6c, matching the window-quota premium bound), p_no
  sanity floor, fractional size cap (default 0.75 contracts), and a
  per-ticker/daily attempt budget.  The position is stamped settle_hold —
  the monitor emits NO take-profit / trail / hard-lock exits for it; the
  no-edge LOSS_CAP salvage floor remains as the catastrophe protection.

Bounds (env-tunable):

  MERID_DRIFT_LANE_ENABLED            default 0 (explicit opt-in)
  MERID_DRIFT_PRICE_LO / _HI          40 / 74  own-side bid band
  MERID_DRIFT_TTE_MIN_S / _MAX_S      180 / 840  needs drift runway
  MERID_DRIFT_MIN_NET_EV_CENTS        -2.0     claimed-EV floor
  MERID_DRIFT_ASSETS                  SOL,ETH,DOGE,XRP  (BTC excluded —
                                      the pooled cohort measured -1.6c)
  MERID_DRIFT_MAX_CONTRACTS           2.0      sized so a drift fill
                                      leaves cap room for a pf lot
  MERID_DRIFT_LOCK_GAIN_CENTS         12       per-position lock offset
  MERID_DRIFT_MAX_PER_TICKER          2        emission attempts/window
  MERID_DRIFT_DAILY_MAX               96       catastrophic-bleed bound

  MERID_CHEAP_NO_LANE_ENABLED         default 0
  MERID_CHEAP_NO_PRICE_LO / _HI       25 / 40  NO bid band — the canonical
                                      NO entry floor is 25c and it binds
                                      in the intent contract / router /
                                      client, so a lower band here would
                                      only produce downstream vetoes.
  MERID_CHEAP_NO_COMPLEMENT_MIN       55       min opposite YES ask —
                                      the sleeve only exists on
                                      YES-leaning books
  MERID_CHEAP_NO_TTE_MIN_S            240      settle runway
  MERID_CHEAP_NO_MIN_NET_EV_CENTS     -6.0     premium-bound floor
  MERID_CHEAP_NO_MIN_P                0.12     anti-degenerate claim gate
  MERID_CHEAP_NO_MAX_CONTRACTS        0.75     fractional micro-sleeve
  MERID_CHEAP_NO_MAX_PER_TICKER       1
  MERID_CHEAP_NO_DAILY_MAX            24       a sleeve is a lottery,
                                      not a volume lane

Durable attempt state lives at MERID_DRIFT_LANE_STATE_PATH (default
``data/drift_lane_state.json``), same consume-then-suppress discipline as
window_quota.
"""

from __future__ import annotations

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


DRIFT_LANE_ID = "drift_fav"
CHEAP_NO_LANE_ID = "cheap_no_settle"
SALVAGE_BOUNDED_LANES = frozenset({DRIFT_LANE_ID, CHEAP_NO_LANE_ID})


# ---------------------------------------------------------------------------
# drift_fav lane
# ---------------------------------------------------------------------------

def drift_enabled() -> bool:
    return _env_flag("MERID_DRIFT_LANE_ENABLED", False)


def drift_price_lo() -> float:
    return _env_float("MERID_DRIFT_PRICE_LO", 40.0)


def drift_price_hi() -> float:
    return _env_float("MERID_DRIFT_PRICE_HI", 74.0)


def drift_tte_min_s() -> float:
    return _env_float("MERID_DRIFT_TTE_MIN_S", 180.0)


def drift_tte_max_s() -> float:
    return _env_float("MERID_DRIFT_TTE_MAX_S", 840.0)


def drift_min_ev_cents() -> float:
    return _env_float("MERID_DRIFT_MIN_NET_EV_CENTS", -2.0)


def drift_assets() -> frozenset:
    raw = os.environ.get("MERID_DRIFT_ASSETS", "SOL,ETH,DOGE,XRP")
    return frozenset(a.strip().upper() for a in raw.split(",") if a.strip())


def drift_max_contracts() -> float:
    return _env_float("MERID_DRIFT_MAX_CONTRACTS", 2.0)


def drift_lock_gain_cents() -> int:
    """Per-position profit-lock offset from entry.  The pooled path data
    measured ~75-82c average post-entry max for 40-74c entries — a +12c
    lock monetizes the modal drift that the global 90c threshold misses."""
    return int(_env_float("MERID_DRIFT_LOCK_GAIN_CENTS", 12.0))


def drift_max_per_ticker() -> int:
    return int(_env_float("MERID_DRIFT_MAX_PER_TICKER", 2.0))


def drift_daily_max() -> int:
    return int(_env_float("MERID_DRIFT_DAILY_MAX", 96.0))


def drift_band_match(price_cents: Optional[float]) -> bool:
    if price_cents is None:
        return False
    try:
        p = float(price_cents)
    except (TypeError, ValueError):
        return False
    return drift_price_lo() <= p <= drift_price_hi()


def drift_block(
    side_price_cents: Optional[float],
    net_ev_cents: Optional[float],
    tte_seconds: Optional[float],
    asset: Optional[str] = None,
    entry_price_basis: Optional[str] = None,
    ticker: Optional[str] = None,
) -> Optional[str]:
    """Strict drift-lane admission gate.  Returns a block reason on
    failure, ``None`` when every lane condition passes (or the lane is
    inert — callers gate on band_match + enabled before consulting this).
    """
    if not drift_enabled():
        return "drift_disabled"
    if not drift_band_match(side_price_cents):
        return "drift_band"
    if asset is not None and str(asset).upper() not in drift_assets():
        return "drift_asset"
    if tte_seconds is None or not (
        drift_tte_min_s() <= float(tte_seconds) <= drift_tte_max_s()
    ):
        return "drift_tte"
    if net_ev_cents is None or float(net_ev_cents) < drift_min_ev_cents():
        return "drift_low_ev"
    if entry_price_basis != "bid":
        return "drift_basis_not_bid"
    if ticker and lane_attempts_exhausted(DRIFT_LANE_ID, ticker):
        return "drift_attempts_exhausted"
    return None


# ---------------------------------------------------------------------------
# cheap_no_settle lane
# ---------------------------------------------------------------------------

def cheap_no_enabled() -> bool:
    return _env_flag("MERID_CHEAP_NO_LANE_ENABLED", False)


def cheap_no_price_lo() -> float:
    return _env_float("MERID_CHEAP_NO_PRICE_LO", 25.0)


def cheap_no_price_hi() -> float:
    return _env_float("MERID_CHEAP_NO_PRICE_HI", 40.0)


def cheap_no_complement_min() -> float:
    return _env_float("MERID_CHEAP_NO_COMPLEMENT_MIN", 55.0)


def cheap_no_tte_min_s() -> float:
    return _env_float("MERID_CHEAP_NO_TTE_MIN_S", 240.0)


def cheap_no_min_ev_cents() -> float:
    return _env_float("MERID_CHEAP_NO_MIN_NET_EV_CENTS", -6.0)


def cheap_no_min_p() -> float:
    return _env_float("MERID_CHEAP_NO_MIN_P", 0.12)


def cheap_no_max_contracts() -> float:
    return _env_float("MERID_CHEAP_NO_MAX_CONTRACTS", 0.75)


def cheap_no_max_per_ticker() -> int:
    return int(_env_float("MERID_CHEAP_NO_MAX_PER_TICKER", 1.0))


def cheap_no_daily_max() -> int:
    return int(_env_float("MERID_CHEAP_NO_DAILY_MAX", 24.0))


def cheap_no_band_match(price_cents: Optional[float]) -> bool:
    if price_cents is None:
        return False
    try:
        p = float(price_cents)
    except (TypeError, ValueError):
        return False
    return cheap_no_price_lo() <= p <= cheap_no_price_hi()


def cheap_no_block(
    side: Optional[str],
    side_price_cents: Optional[float],
    complement_price_cents: Optional[float],
    net_ev_cents: Optional[float],
    tte_seconds: Optional[float],
    p_selected: Optional[float] = None,
    entry_price_basis: Optional[str] = None,
    ticker: Optional[str] = None,
) -> Optional[str]:
    """Strict cheap-NO-settle admission gate.  NO side only — the pooled
    YES-side cheap cohort measured flat-to-negative while cheap NO on
    YES-heavy books carried the underpricing."""
    if not cheap_no_enabled():
        return "cheap_no_disabled"
    if str(side or "").lower() != "no":
        return "cheap_no_side"
    if not cheap_no_band_match(side_price_cents):
        return "cheap_no_band"
    if complement_price_cents is not None and float(
        complement_price_cents
    ) < cheap_no_complement_min():
        return "cheap_no_complement"
    if tte_seconds is None or float(tte_seconds) < cheap_no_tte_min_s():
        return "cheap_no_tte"
    if net_ev_cents is None or float(net_ev_cents) < cheap_no_min_ev_cents():
        return "cheap_no_low_ev"
    try:
        _p = float(p_selected) if p_selected is not None else None
    except (TypeError, ValueError):
        _p = None
    if _p is None or _p < cheap_no_min_p():
        return "cheap_no_low_p"
    if entry_price_basis != "bid":
        return "cheap_no_basis_not_bid"
    if ticker and lane_attempts_exhausted(CHEAP_NO_LANE_ID, ticker):
        return "cheap_no_attempts_exhausted"
    return None


# ---------------------------------------------------------------------------
# Durable attempt counter (shared by both lanes; lane-scoped records)
# ---------------------------------------------------------------------------

def lane_state_path() -> str:
    return os.environ.get(
        "MERID_DRIFT_LANE_STATE_PATH", "data/drift_lane_state.json"
    )


def _load_state(path: Optional[str] = None, now: Optional[float] = None) -> dict:
    now = time.time() if now is None else float(now)
    day = datetime.fromtimestamp(now, tz=timezone.utc).date().isoformat()
    st = {"date": day, "lanes": {}}
    try:
        with open(path or lane_state_path(), "r", encoding="utf-8") as f:
            rec = json.load(f)
        if rec.get("date") == day and isinstance(rec.get("lanes"), dict):
            st["lanes"] = rec["lanes"]
    except Exception:
        pass
    return st


def _lane_rec(st: dict, lane: str) -> dict:
    lanes = st.setdefault("lanes", {})
    return lanes.setdefault(lane, {"count": 0, "tickers": {}})


def lane_attempts_exhausted(
    lane: str,
    ticker: str,
    path: Optional[str] = None,
    now: Optional[float] = None,
) -> bool:
    """Fast pre-check so the decision layer skips instead of emitting
    into a spent slot (per-ticker bound + daily bound + min gap)."""
    if not ticker:
        return True
    now = time.time() if now is None else float(now)
    st = _load_state(path, now)
    rec = _lane_rec(st, lane)
    if lane == DRIFT_LANE_ID:
        per_ticker, daily = drift_max_per_ticker(), drift_daily_max()
    else:
        per_ticker, daily = cheap_no_max_per_ticker(), cheap_no_daily_max()
    if int(rec.get("count") or 0) >= daily:
        return True
    trec = (rec.get("tickers") or {}).get(ticker) or {}
    return int(trec.get("n") or 0) >= per_ticker


def record_lane_attempt(
    lane: str,
    ticker: str,
    path: Optional[str] = None,
    now: Optional[float] = None,
) -> Tuple[int, int]:
    """Consume an attempt slot; returns (per_ticker_n, lane_day_count)."""
    now = time.time() if now is None else float(now)
    p = path or lane_state_path()
    st = _load_state(p, now)
    rec = _lane_rec(st, lane)
    rec["count"] = int(rec.get("count") or 0) + 1
    tickers = rec.setdefault("tickers", {})
    trec = tickers.setdefault(ticker, {"n": 0, "first_ts": now})
    trec["n"] = int(trec.get("n") or 0) + 1
    trec["last_ts"] = now
    try:
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(json.dumps(st, separators=(",", ":")))
        os.replace(tmp, p)
    except Exception:
        pass
    return int(trec["n"]), int(rec["count"])
