"""Cross-asset directional regime + post-drawdown entry controls.

2026-10-01 (policy_epoch ``post_drawdown_2026-10-01``): the 6-win / 7-loss
forensic audit showed the failure was not a side-inversion bug — it was a
regime failure.  The six winners were deep-ITM NO buys (|z| 0.7-2.1, model
p 0.77-0.95) into a flat/falling tape.  Six of the seven losers were
near-money NO buys (|z| < 0.5, model p 0.42-0.82) while cross-asset 60s
breadth was 3-5/5 positive — passive bids adversely selected into a rally.

This module supplies four shared, deterministic controls consumed by
``compute_trade_decision`` (single choke point for every admission lane):

1. ``compute_directional_regime`` — builds ``DirectionalRegime`` from the
   per-tick ``FeatureSnapshot`` (CF-RTI 60s returns = the settlement index).
   ``RALLY_CONFIRMED`` when >= 4 of the 5 assets have positive 60s returns
   and BTC's 60s return is positive; symmetric ``SELL_OFF_CONFIRMED``.

2. ``regime_entry_block`` — countertrend side block.  NO in a rally / YES in
   a selloff is rejected unless the position is already deep-ITM
   (|z| >= ``MERID_REGIME_DEEP_ITM_Z``), because deep-ITM entries are the
   profile that actually won during the episode.

3. ``conviction_block_reason`` — side-aware distance-from-50% floor.
   |p_cal - 0.5| must clear ``MERID_CONVICTION_MIN_DIST_<ASSET>``.  A coin-flip
   read (BTC NO at p=0.501) cannot be a directional trade.

4. ``SideThrottle`` — persisted same-side loss-streak suspension and
   per-strip same-direction concentration cap.  Two same-side settled losses
   inside 60 minutes suspend that side for 60 minutes; three suspend it
   until manual review or the next policy epoch.  ``data/directional_throttle.json``
   is written atomically (tmp + replace).

Adverse-selection conditioning lives in
``current_build_provisional.adverse_selection_reserve_cents`` (regime-aware
signature added in the same change); this module supplies the regime label it
consumes and the min-sample countertrend gate ``countertrend_lane_block``.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import logging

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Policy epoch
# ---------------------------------------------------------------------------

POLICY_EPOCH: str = os.environ.get("MERID_POLICY_EPOCH", "post_drawdown_2026-10-01")

_REGIME_ASSETS = ("BTC", "ETH", "SOL", "XRP", "DOGE")


def _env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return default


def directional_regime_enabled() -> bool:
    return _env_flag("MERID_DIRECTIONAL_REGIME_ENABLED", True)


# ---------------------------------------------------------------------------
# Cross-asset regime state
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DirectionalRegime:
    """Shared cross-asset directional state for one decision tick."""

    label: str  # NEUTRAL | RALLY_CONFIRMED | SELL_OFF_CONFIRMED
    breadth60_pos: int
    breadth60_total: int
    btc_r60: Optional[float]
    asset_r60: Dict[str, Optional[float]]
    ts: float
    reason: str = ""


def _min_breadth_assets() -> int:
    return _env_int("MERID_REGIME_BREADTH_MIN_ASSETS", 4)


def compute_directional_regime(
    feature_snapshot: Any,
    now: Optional[float] = None,
) -> DirectionalRegime:
    """Build the shared regime state from a per-tick ``FeatureSnapshot``.

    Uses each asset's ``rti_return_60s`` (the CF Benchmarks settlement index,
    the same stream that settles the contract).  Assets with missing or
    ineligible RTI data are excluded from breadth and counted in
    ``breadth60_total`` so the gate degrades honestly instead of blocking on
    missing data.
    """
    ts = now or time.time()
    asset_r60: Dict[str, Optional[float]] = {}
    n_pos = n_total = 0
    btc_r60: Optional[float] = None
    for asset in _REGIME_ASSETS:
        r60: Optional[float] = None
        try:
            sl = (feature_snapshot.by_asset or {}).get(asset)
        except Exception:
            sl = None
        if sl is not None:
            try:
                r60 = (sl.rti_returns or {}).get("rti_return_60s")
            except Exception:
                r60 = None
            if r60 is not None:
                try:
                    r60 = float(r60)
                    if not math.isfinite(r60):
                        r60 = None
                except (TypeError, ValueError):
                    r60 = None
            if r60 is not None and not getattr(sl, "rti_execution_eligible", True):
                r60 = None
        asset_r60[asset] = r60
        if r60 is not None:
            n_total += 1
            if r60 > 0:
                n_pos += 1
        if asset == "BTC":
            btc_r60 = r60

    min_assets = _min_breadth_assets()
    label = "NEUTRAL"
    reason = "insufficient_rti_breadth" if n_total < min_assets else "mixed"
    if n_total >= min_assets:
        if n_pos >= 4 and (btc_r60 or 0.0) > 0:
            label = "RALLY_CONFIRMED"
            reason = f"breadth60={n_pos}/{n_total} btc_r60={btc_r60:+.5f}"
        elif n_pos <= n_total - 4 and (btc_r60 or 0.0) < 0:
            label = "SELL_OFF_CONFIRMED"
            reason = f"breadth60={n_pos}/{n_total} btc_r60={btc_r60:+.5f}"

    return DirectionalRegime(
        label=label,
        breadth60_pos=n_pos,
        breadth60_total=n_total,
        btc_r60=btc_r60,
        asset_r60=asset_r60,
        ts=ts,
        reason=reason,
    )


def _deep_itm_z() -> float:
    return _env_float("MERID_REGIME_DEEP_ITM_Z", 0.6)


def regime_entry_block(
    regime: Optional[DirectionalRegime],
    side: str,
    zscore: Optional[float],
) -> Optional[str]:
    """Countertrend side block.

    A countertrend entry (NO into a confirmed rally, YES into a confirmed
    selloff) is rejected unless the contract is already deep-ITM on the held
    side (|z| >= deep_itm_z with the safe sign), which is the only near-money
    exception that survived the loss audit.
    """
    if regime is None or not directional_regime_enabled():
        return None
    deep = _deep_itm_z()
    z = zscore if (zscore is not None and math.isfinite(zscore)) else None
    if regime.label == "RALLY_CONFIRMED" and side == "no":
        if z is not None and z <= -deep:
            return None  # deep-ITM NO is already aligned with settlement
        return "countertrend_no_rally_regime"
    if regime.label == "SELL_OFF_CONFIRMED" and side == "yes":
        if z is not None and z >= deep:
            return None
        return "countertrend_yes_selloff_regime"
    return None


# ---------------------------------------------------------------------------
# Side-aware conviction distance gate
# ---------------------------------------------------------------------------

_CONVICTION_DEFAULTS = {"BTC": 0.06, "ETH": 0.06, "SOL": 0.07, "XRP": 0.07, "DOGE": 0.08}


def conviction_min_distance(asset: str) -> float:
    default = _CONVICTION_DEFAULTS.get(str(asset).upper(), 0.07)
    return _env_float(f"MERID_CONVICTION_MIN_DIST_{str(asset).upper()}", default)


def conviction_enabled() -> bool:
    return _env_flag("MERID_CONVICTION_GATE_ENABLED", True)


def conviction_block_reason(asset: str, p_selected: Optional[float]) -> Optional[str]:
    """|p_cal - 0.5| must clear the per-asset floor.  A coin-flip read is not
    directional edge — BTC NO at p=0.501 (fill 42c, -42c) is the canonical
    violation."""
    if not conviction_enabled() or p_selected is None:
        return None
    delta = conviction_min_distance(asset)
    dist = abs(float(p_selected) - 0.5)
    if dist < delta:
        return "low_conviction"
    return None


# ---------------------------------------------------------------------------
# Book-flow confirmation for passive entries
# ---------------------------------------------------------------------------

def bookflow_enabled() -> bool:
    return _env_flag("MERID_BOOKFLOW_GATE_ENABLED", True)


def _bookflow_imb_block() -> float:
    return _env_float("MERID_BOOKFLOW_IMB_BLOCK", 0.20)


def bookflow_block_reason(
    feature_snapshot: Any,
    asset: str,
    side: str,
) -> Optional[str]:
    """Require book-flow confirmation for resting entries.

    A passive NO bid must not rest while YES-side book pressure dominates
    (book_imbalance_yes > imb_block) — that is the signature of being picked
    off into the move.  Missing features degrade to no-block (the regime and
    conviction gates still apply); the feature_missing_reasons telemetry on
    the slice records why.
    """
    if not bookflow_enabled() or feature_snapshot is None:
        return None
    try:
        sl = (feature_snapshot.by_asset or {}).get(str(asset).upper())
    except Exception:
        sl = None
    if sl is None:
        return None
    imb = _bookflow_imb_block()
    if side == "no":
        yes_imb = getattr(sl, "book_imbalance_yes", None)
        if yes_imb is not None and math.isfinite(float(yes_imb)) and float(yes_imb) > imb:
            return "bookflow_yes_pressure"
    elif side == "yes":
        no_imb = getattr(sl, "book_imbalance_no", None)
        if no_imb is not None and math.isfinite(float(no_imb)) and float(no_imb) > imb:
            return "bookflow_no_pressure"
    return None


# ---------------------------------------------------------------------------
# Conditional adverse-selection sample gate
# ---------------------------------------------------------------------------

def countertrend_min_markouts() -> int:
    return _env_int("MERID_ASR_COUNTERTREND_MIN_MARKOUTS", 20)


def countertrend_lane_block(
    asset: str,
    side: str,
    regime: Optional[DirectionalRegime],
) -> Optional[str]:
    """No passive countertrend entry until the lane has measured its cost.

    ``MERID_ASR_COUNTERTREND_MIN_MARKOUTS`` (default 20) current-build
    post-only markouts on (asset, side) tagged with the current regime are
    required before a rally-NO / selloff-YES lane opens.  Counts marks
    regardless of fill — an unfilled resting order that never got picked off
    is itself evidence the context is not toxic.
    """
    if regime is None or not directional_regime_enabled():
        return None
    want = None
    if regime.label == "RALLY_CONFIRMED" and side == "no":
        want = "RALLY_CONFIRMED"
    elif regime.label == "SELL_OFF_CONFIRMED" and side == "yes":
        want = "SELL_OFF_CONFIRMED"
    if want is None:
        return None
    try:
        from merid.prediction import current_build_provisional as _cbp
        n = _cbp.regime_markout_sample_count(asset, side, want)
    except Exception:
        n = 0
    if n < countertrend_min_markouts():
        return f"countertrend_lane_cold_start(n={n})"
    return None


# ---------------------------------------------------------------------------
# Side throttle: loss streaks + same-direction strip concentration
# ---------------------------------------------------------------------------

_THROTTLE_LOCK = threading.Lock()
_THROTTLE_CACHE_TTL_S = 2.0
_throttle_cache: Tuple[float, Dict[str, Any]] = (0.0, {})


def throttle_state_path() -> str:
    return os.environ.get(
        "MERID_DIRECTIONAL_THROTTLE_PATH", "data/directional_throttle.json"
    )


def _loss_window_s() -> float:
    return _env_float("MERID_SIDE_THROTTLE_LOSS_WINDOW_S", 3600.0)


def _loss_suspend_count() -> int:
    return _env_int("MERID_SIDE_THROTTLE_SUSPEND_COUNT", 2)


def _loss_suspend_seconds() -> float:
    return _env_float("MERID_SIDE_THROTTLE_SUSPEND_S", 3600.0)


def _loss_review_count() -> int:
    return _env_int("MERID_SIDE_THROTTLE_REVIEW_COUNT", 3)


def _strip_ev_margin_cents() -> float:
    return _env_float("MERID_STRIP_CONC_EV_MARGIN_CENTS", 3.0)


def throttle_enabled() -> bool:
    return _env_flag("MERID_SIDE_THROTTLE_ENABLED", True)


def _default_throttle_state() -> Dict[str, Any]:
    return {
        "epoch": POLICY_EPOCH,
        "recent_settlements": [],   # [{ts, side, pnl, decision_id}]
        "suspensions": {},          # side -> {until, reason, triggered_at}
        "strip_entries": {},        # strip_key -> [{side, ev, decision_id, open}]
    }


def _load_throttle_state(force: bool = False) -> Dict[str, Any]:
    global _throttle_cache
    now = time.time()
    if not force and now - _throttle_cache[0] < _THROTTLE_CACHE_TTL_S:
        return _throttle_cache[1]
    path = throttle_state_path()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            st = json.load(fh)
    except Exception:
        st = {}
    if not isinstance(st, dict) or st.get("epoch") != POLICY_EPOCH:
        st = _default_throttle_state()
    for k, v in _default_throttle_state().items():
        st.setdefault(k, v)
    _throttle_cache = (now, st)
    return st


def _save_throttle_state(st: Dict[str, Any]) -> None:
    path = throttle_state_path()
    try:
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=d or ".", prefix=".throttle_", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(st, fh, separators=(",", ":"))
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        global _throttle_cache
        _throttle_cache = (time.time(), st)
    except Exception as exc:
        logger.debug("[SIDE-THROTTLE] persist failed: %s", exc)


def _streak(
    settlements: Any,
    side: str,
    now: float,
    window_s: Optional[float],
) -> int:
    """Trailing consecutive settled losses for ``side``.

    A win on that side breaks the run; other-side outcomes are ignored.
    ``window_s=None`` counts the epoch-wide run (for the manual-review tier);
    a finite window bounds the 60-minute suspension tier — losses older than
    the window no longer count toward it.
    """
    streak = 0
    for rec in reversed(list(settlements or [])):
        if rec.get("side") != side:
            continue
        if window_s is not None and now - float(rec.get("ts") or 0.0) > window_s:
            break
        if float(rec.get("pnl") or 0.0) < 0:
            streak += 1
        else:
            break
    return streak


def record_side_settlement(
    side: Optional[str],
    pnl_cents: Optional[float],
    ts: Optional[float] = None,
    decision_id: Optional[str] = None,
) -> None:
    """Record a settled entry outcome for streak/concentration accounting.

    Called from the audit ledger's settlement attribution (the single funnel
    every settled decision passes through).  Maintains the rolling loss
    streak and applies the suspension rules:

      >= ``MERID_SIDE_THROTTLE_SUSPEND_COUNT`` (2) consecutive same-side
          losses inside ``MERID_SIDE_THROTTLE_LOSS_WINDOW_S`` (3600s)
          -> suspend that side for ``MERID_SIDE_THROTTLE_SUSPEND_S`` (3600s).
      >= ``MERID_SIDE_THROTTLE_REVIEW_COUNT`` (3) consecutive same-side
          losses -> suspend until manual review or the next policy epoch.
    """
    if not throttle_enabled() or side not in ("yes", "no"):
        return
    ts = float(ts or time.time())
    pnl = float(pnl_cents or 0.0)
    with _THROTTLE_LOCK:
        st = _load_throttle_state(force=True)
        st["recent_settlements"].append(
            {"ts": ts, "side": side, "pnl": pnl, "decision_id": decision_id}
        )
        st["recent_settlements"] = st["recent_settlements"][-300:]
        # close any open strip entries for this decision
        for entries in (st.get("strip_entries") or {}).values():
            for e in entries:
                if decision_id and e.get("decision_id") == decision_id:
                    e["open"] = False
        window = _loss_window_s()
        streak_window = _streak(st["recent_settlements"], side, ts, window)
        streak_epoch = _streak(st["recent_settlements"], side, ts, None)
        if pnl < 0 and streak_epoch >= _loss_review_count():
            st["suspensions"][side] = {
                "until": None,
                "reason": f"{streak_epoch}_consecutive_losses_manual_review",
                "triggered_at": ts,
            }
            logger.warning(
                "[SIDE-THROTTLE] side=%s suspended until manual review "
                "(%d consecutive epoch losses)",
                side, streak_epoch,
            )
        elif pnl < 0 and streak_window >= _loss_suspend_count():
            st["suspensions"][side] = {
                "until": ts + _loss_suspend_seconds(),
                "reason": f"{streak_window}_consecutive_losses",
                "triggered_at": ts,
            }
            logger.warning(
                "[SIDE-THROTTLE] side=%s suspended %.0fs "
                "(%d consecutive losses in %.0fs window)",
                side, _loss_suspend_seconds(), streak_window, window,
            )
        _save_throttle_state(st)


def side_throttle_block(side: str, now: Optional[float] = None) -> Optional[str]:
    """Return the active suspension reason for ``side``, if any."""
    if not throttle_enabled() or side not in ("yes", "no"):
        return None
    now = float(now or time.time())
    st = _load_throttle_state()
    sus = (st.get("suspensions") or {}).get(side)
    if not sus:
        return None
    until = sus.get("until")
    if until is None:
        return f"side_suspended_manual_review:{sus.get('reason')}"
    if now < float(until):
        return f"side_suspended:{sus.get('reason')}"
    return None


def _strip_key(ts: float) -> str:
    return str(int(ts // 900))


def strip_concentration_block(
    side: str,
    ev_cents: Optional[float],
    ts: Optional[float] = None,
) -> Optional[str]:
    """One same-directional entry across all five assets per 15-minute strip.

    A second same-side entry in the strip is permitted only when every prior
    same-side entry has been derisked/closed AND the new candidate's net EV
    exceeds the best prior entry's by ``MERID_STRIP_CONC_EV_MARGIN_CENTS``.
    """
    if not throttle_enabled() or side not in ("yes", "no"):
        return None
    ts = float(ts or time.time())
    st = _load_throttle_state()
    entries = (st.get("strip_entries") or {}).get(_strip_key(ts)) or []
    same = [e for e in entries if e.get("side") == side]
    if not same:
        return None
    all_closed = all(not e.get("open", True) for e in same)
    if not all_closed:
        return f"strip_same_side_open:{side}"
    margin = _strip_ev_margin_cents()
    best_prior = max(float(e.get("ev") or 0.0) for e in same)
    if ev_cents is None or float(ev_cents) < best_prior + margin:
        return f"strip_same_side_ev:{side}"
    return None


def record_strip_entry(
    side: Optional[str],
    ev_cents: Optional[float],
    ts: Optional[float] = None,
    decision_id: Optional[str] = None,
) -> None:
    """Record a submitted entry's strip for the concentration cap."""
    if not throttle_enabled() or side not in ("yes", "no"):
        return
    ts = float(ts or time.time())
    with _THROTTLE_LOCK:
        st = _load_throttle_state(force=True)
        key = _strip_key(ts)
        entries = st.setdefault("strip_entries", {}).setdefault(key, [])
        entries.append(
            {
                "side": side,
                "ev": float(ev_cents) if ev_cents is not None else None,
                "decision_id": decision_id,
                "open": True,
            }
        )
        # bound: keep the last 8 strips
        keys = sorted(st["strip_entries"].keys())[-8:]
        st["strip_entries"] = {k: st["strip_entries"][k] for k in keys}
        _save_throttle_state(st)


def throttle_status() -> Dict[str, Any]:
    """Observability snapshot for heartbeats/tests."""
    st = _load_throttle_state()
    now = time.time()
    return {
        "epoch": st.get("epoch"),
        "suspensions": st.get("suspensions"),
        "no_streak_60m": _streak(st.get("recent_settlements"), "no", now, _loss_window_s()),
        "yes_streak_60m": _streak(st.get("recent_settlements"), "yes", now, _loss_window_s()),
        "no_streak_epoch": _streak(st.get("recent_settlements"), "no", now, None),
        "yes_streak_epoch": _streak(st.get("recent_settlements"), "yes", now, None),
    }
