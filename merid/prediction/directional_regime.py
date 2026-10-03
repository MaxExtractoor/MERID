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

    label: str  # NEUTRAL | RALLY_CONFIRMED | RALLY_WEAKENING | SELL_OFF_CONFIRMED | SELL_OFF_WEAKENING
    breadth60_pos: int
    breadth60_total: int
    btc_r60: Optional[float]
    asset_r60: Dict[str, Optional[float]]
    ts: float
    reason: str = ""
    score: float = 0.0       # EMA of the instant directional vote [-1, 1]
    up_ticks: int = 0        # consecutive rally-aligned observations
    down_ticks: int = 0      # consecutive selloff-aligned observations


def _min_breadth_assets() -> int:
    return _env_int("MERID_REGIME_BREADTH_MIN_ASSETS", 4)


def regime_hysteresis_enabled() -> bool:
    return _env_flag("MERID_REGIME_HYSTERESIS_ENABLED", True)


def _regime_state_path() -> str:
    return os.environ.get(
        "MERID_DIRECTIONAL_REGIME_STATE_PATH",
        "data/directional_regime_state.json",
    )


def _regime_lambda() -> float:
    return _env_float("MERID_REGIME_EMA_LAMBDA", 0.6)


def _regime_confirm_score() -> float:
    return _env_float("MERID_REGIME_CONFIRM_SCORE", 0.5)


def _regime_weaken_score() -> float:
    return _env_float("MERID_REGIME_WEAKEN_SCORE", 0.15)


def _regime_confirm_ticks() -> int:
    return _env_int("MERID_REGIME_CONFIRM_TICKS", 2)


def _regime_min_tick_s() -> float:
    return _env_float("MERID_REGIME_MIN_TICK_S", 1.5)


def _regime_stale_s() -> float:
    return _env_float("MERID_REGIME_STATE_STALE_S", 600.0)


_REGIME_LOCK = threading.Lock()
_regime_cache: Tuple[float, Dict[str, Any]] = (0.0, {})


def _default_regime_state() -> Dict[str, Any]:
    return {
        "epoch": POLICY_EPOCH,
        "score": 0.0,
        "up_ticks": 0,
        "down_ticks": 0,
        "label": "NEUTRAL",
        "last_ts": 0.0,
    }


def _load_regime_state(force: bool = False) -> Dict[str, Any]:
    """Persisted regime EMA state.  Epoch mismatches reset to the neutral
    prior.  Staleness is *not* checked here — the state's ``last_ts`` lives
    in the caller's clock domain (tests drive synthetic timestamps), so only
    ``_update_regime_state`` may compare it against the tick time."""
    global _regime_cache
    now = time.time()
    if not force and now - _regime_cache[0] < _THROTTLE_CACHE_TTL_S:
        return _regime_cache[1]
    path = _regime_state_path()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            st = json.load(fh)
    except Exception:
        st = {}
    if not isinstance(st, dict) or st.get("epoch") != POLICY_EPOCH:
        st = _default_regime_state()
    for k, v in _default_regime_state().items():
        st.setdefault(k, v)
    _regime_cache = (now, st)
    return st


def _save_regime_state(st: Dict[str, Any]) -> None:
    path = _regime_state_path()
    try:
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=d or ".", prefix=".regime_", suffix=".tmp")
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
        global _regime_cache
        _regime_cache = (time.time(), st)
    except Exception as exc:
        logger.debug("[REGIME] persist failed: %s", exc)


def _update_regime_state(
    instant_dir: int,
    btc_r60: Optional[float],
    ts: float,
) -> Dict[str, Any]:
    """Advance the persisted EMA at most once per ``MERID_REGIME_MIN_TICK_S``.

    ``compute_directional_regime`` is invoked several times inside one loop
    tick (once per asset's decision call plus the loop-level log).  Only the
    first observation inside a tick window may advance the score/counters;
    the rest reuse the stored state so one cycle cannot count as N ticks.
    """
    with _REGIME_LOCK:
        st = _load_regime_state(force=True)
        # Stale state (restart gap, clock jump): a hours-old confirmed label
        # must not carry into a fresh session — decay back to the prior.
        if ts - float(st.get("last_ts") or 0.0) > _regime_stale_s():
            st.update(_default_regime_state())
        elif ts - float(st.get("last_ts") or 0.0) < _regime_min_tick_s():
            return st
        lam = _regime_lambda()
        st["score"] = lam * float(st.get("score") or 0.0) + (1.0 - lam) * float(instant_dir)
        if instant_dir > 0:
            st["up_ticks"] = int(st.get("up_ticks") or 0) + 1
            st["down_ticks"] = 0
        elif instant_dir < 0:
            st["down_ticks"] = int(st.get("down_ticks") or 0) + 1
            st["up_ticks"] = 0
        else:
            st["up_ticks"] = 0
            st["down_ticks"] = 0
        prev_label = str(st.get("label") or "NEUTRAL")
        score = float(st["score"])
        confirm = _regime_confirm_score()
        weaken = _regime_weaken_score()
        ticks = _regime_confirm_ticks()
        if st["up_ticks"] >= ticks and score >= confirm and (btc_r60 or 0.0) > 0:
            label = "RALLY_CONFIRMED"
        elif st["down_ticks"] >= ticks and score <= -confirm and (btc_r60 or 0.0) < 0:
            label = "SELL_OFF_CONFIRMED"
        elif prev_label in ("RALLY_CONFIRMED", "RALLY_WEAKENING") and score >= weaken:
            label = "RALLY_WEAKENING"
        elif prev_label in ("SELL_OFF_CONFIRMED", "SELL_OFF_WEAKENING") and score <= -weaken:
            label = "SELL_OFF_WEAKENING"
        else:
            label = "NEUTRAL"
        st["label"] = label
        st["last_ts"] = ts
        _save_regime_state(st)
        return st


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

    With ``MERID_REGIME_HYSTERESIS_ENABLED`` (default on) the label is the
    output of a decayed confidence score ``R_t = λ·R_{t-1} + (1-λ)·vote``
    rather than the per-tick vote alone: a confirmed state requires
    ``MERID_REGIME_CONFIRM_TICKS`` consecutive aligned observations and a
    score beyond ``MERID_REGIME_CONFIRM_SCORE``; it decays through
    ``*_WEAKENING`` before returning to ``NEUTRAL``.  This prevents a single
    breadth flicker from toggling the countertrend prohibition.
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
    instant_dir = 0
    if n_total >= min_assets:
        if n_pos >= 4 and (btc_r60 or 0.0) > 0:
            label = "RALLY_CONFIRMED"
            instant_dir = 1
            reason = f"breadth60={n_pos}/{n_total} btc_r60={btc_r60:+.5f}"
        elif n_pos <= n_total - 4 and (btc_r60 or 0.0) < 0:
            label = "SELL_OFF_CONFIRMED"
            instant_dir = -1
            reason = f"breadth60={n_pos}/{n_total} btc_r60={btc_r60:+.5f}"

    score = 0.0
    up_ticks = down_ticks = 0
    if regime_hysteresis_enabled():
        st = _update_regime_state(instant_dir, btc_r60, ts)
        label = str(st.get("label") or "NEUTRAL")
        score = float(st.get("score") or 0.0)
        up_ticks = int(st.get("up_ticks") or 0)
        down_ticks = int(st.get("down_ticks") or 0)
        reason = (
            f"{reason} score={score:+.3f} up={up_ticks} down={down_ticks}"
        )

    return DirectionalRegime(
        label=label,
        breadth60_pos=n_pos,
        breadth60_total=n_total,
        btc_r60=btc_r60,
        asset_r60=asset_r60,
        ts=ts,
        reason=reason,
        score=score,
        up_ticks=up_ticks,
        down_ticks=down_ticks,
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


def _strip_max_open_same_side() -> int:
    """Max concurrent still-open same-side entries per 15-min strip.

    Default 1 = legacy behaviour (a second entry needs the first closed AND
    a better EV).  Values >1 permit bounded concurrent stacking across
    assets when the new candidate still clears the EV ladder.
    """
    return max(1, _env_int("MERID_STRIP_CONC_MAX_OPEN_SAME_SIDE", 1))


def _catastrophe_scope() -> str:
    """``asset`` = park only the offending ``{asset}:{side}`` lane;
    ``side`` = legacy whole-side stop."""
    v = os.environ.get("MERID_SIDE_CATASTROPHE_SCOPE", "asset").strip().lower()
    return "side" if v == "side" else "asset"


def _catastrophe_ttl_s() -> float:
    """Suspension TTL after a catastrophe; <=0 = until manual review."""
    return _env_float("MERID_SIDE_CATASTROPHE_TTL_S", 21600.0)


def _caution_ttl_s() -> float:
    return _env_float("MERID_SIDE_THROTTLE_CAUTION_S", 3600.0)


def _caution_ev_margin_cents() -> float:
    return _env_float("MERID_SIDE_THROTTLE_CAUTION_EV_CENTS", 2.0)


def throttle_enabled() -> bool:
    return _env_flag("MERID_SIDE_THROTTLE_ENABLED", True)


def _default_throttle_state() -> Dict[str, Any]:
    return {
        "epoch": POLICY_EPOCH,
        "recent_settlements": [],   # [{ts, side, pnl, decision_id}]
        "suspensions": {},          # side -> {until, reason, triggered_at}
        "cautions": {},             # side -> {until, reason, triggered_at}
        "released_at": {},          # side -> ts of last operator release
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
    since_ts: float = 0.0,
) -> int:
    """Trailing consecutive settled losses for ``side``.

    A win on that side breaks the run; other-side outcomes are ignored.
    ``window_s=None`` counts the epoch-wide run (for the manual-review tier);
    a finite window bounds the 60-minute suspension tier — losses older than
    the window no longer count toward it.  ``since_ts`` is the operator
    release watermark: settlements at or before it are review history and do
    not count toward re-suspension (release = fresh-start semantics).
    """
    streak = 0
    for rec in reversed(list(settlements or [])):
        if rec.get("side") != side:
            continue
        rts = float(rec.get("ts") or 0.0)
        if rts <= since_ts:
            break
        if window_s is not None and now - rts > window_s:
            break
        if float(rec.get("pnl") or 0.0) < 0:
            streak += 1
        else:
            break
    return streak


def _released_ts(st: Dict[str, Any], side: str) -> float:
    try:
        return float((st.get("released_at") or {}).get(side) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def record_side_settlement(
    side: Optional[str],
    pnl_cents: Optional[float],
    ts: Optional[float] = None,
    decision_id: Optional[str] = None,
) -> None:
    """Record a settled entry outcome for streak/concentration accounting.

    Called from the audit ledger's settlement attribution (the single funnel
    every settled decision passes through).  Maintains the rolling loss
    streak and applies the graded state machine:

      first post-release settled loss -> ``CAUTION`` for
          ``MERID_SIDE_THROTTLE_CAUTION_S`` (3600s): the side stays open but
          its required edge is raised by
          ``MERID_SIDE_THROTTLE_CAUTION_EV_CENTS`` (default 2.0c).  An
          ordinary one-off loss is signal noise, not proof of a broken lane.
      >= ``MERID_SIDE_THROTTLE_SUSPEND_COUNT`` (2) consecutive same-side
          losses inside ``MERID_SIDE_THROTTLE_LOSS_WINDOW_S`` (3600s)
          -> suspend that side for ``MERID_SIDE_THROTTLE_SUSPEND_S`` (3600s).
      >= ``MERID_SIDE_THROTTLE_REVIEW_COUNT`` (3) consecutive same-side
          losses post-release -> suspend until manual review or the next
          policy epoch.

    Streaks count only settlements after ``released_at[side]`` — an operator
    release is an explicit reviewed restart, not a continuation of the run
    that produced the suspension.
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
        released = _released_ts(st, side)
        streak_window = _streak(
            st["recent_settlements"], side, ts, window, since_ts=released
        )
        streak_epoch = _streak(
            st["recent_settlements"], side, ts, None, since_ts=released
        )
        if pnl < 0 and streak_epoch >= _loss_review_count():
            st["suspensions"][side] = {
                "until": None,
                "reason": f"{streak_epoch}_consecutive_losses_manual_review",
                "triggered_at": ts,
            }
            st.setdefault("cautions", {}).pop(side, None)
            logger.warning(
                "[SIDE-THROTTLE] side=%s suspended until manual review "
                "(%d consecutive post-release epoch losses)",
                side, streak_epoch,
            )
        elif pnl < 0 and streak_window >= _loss_suspend_count():
            st["suspensions"][side] = {
                "until": ts + _loss_suspend_seconds(),
                "reason": f"{streak_window}_consecutive_losses",
                "triggered_at": ts,
            }
            st.setdefault("cautions", {}).pop(side, None)
            logger.warning(
                "[SIDE-THROTTLE] side=%s suspended %.0fs "
                "(%d consecutive losses in %.0fs window)",
                side, _loss_suspend_seconds(), streak_window, window,
            )
        elif pnl < 0:
            st.setdefault("cautions", {})[side] = {
                "until": ts + _caution_ttl_s(),
                "reason": f"{streak_epoch}_post_release_loss",
                "triggered_at": ts,
            }
            logger.info(
                "[SIDE-THROTTLE] side=%s CAUTION %.0fs — edge floor +%.1fc "
                "(post-release loss streak=%d)",
                side, _caution_ttl_s(), _caution_ev_margin_cents(),
                streak_epoch,
            )
        else:
            # A win/push breaks the run and clears caution; timed suspensions
            # stay on their clock (deliberate: a fast win does not erase the
            # evidence that produced the suspension).
            (st.get("cautions") or {}).pop(side, None)
        _save_throttle_state(st)


def release_side(side: str, ts: Optional[float] = None) -> None:
    """Operator release from suspension/manual review.

    Clears the suspension and caution, and watermarks ``released_at[side]``
    so streak tiers count only settlements after the release — the reviewed
    history is preserved in ``recent_settlements`` but cannot re-lock the
    side on the very next loss.
    """
    if side not in ("yes", "no"):
        return
    ts = float(ts or time.time())
    with _THROTTLE_LOCK:
        st = _load_throttle_state(force=True)
        (st.get("suspensions") or {}).pop(side, None)
        (st.get("cautions") or {}).pop(side, None)
        # Clear any asset-scoped suspensions for this side too — an operator
        # release covers the whole side surface.
        for _k in [
            k for k in (st.get("suspensions") or {})
            if k.endswith(f":{side}")
        ]:
            st["suspensions"].pop(_k, None)
        st.setdefault("released_at", {})[side] = ts
        _save_throttle_state(st)
    logger.warning(
        "[SIDE-THROTTLE] side=%s released by operator at ts=%.0f — "
        "streak tiers restart from post-release settlements",
        side, ts,
    )


def release_all_sides(ts: Optional[float] = None) -> None:
    for _s in ("yes", "no"):
        release_side(_s, ts=ts)


def record_side_catastrophe(
    side: Optional[str],
    reason: str,
    ts: Optional[float] = None,
    asset: Optional[str] = None,
) -> None:
    """Immediate stop on catastrophic execution evidence.

    Reserved for structural breaches, not performance: wrong-side mapping,
    post-only order filling as taker, fill-time EV <= 0, or a 5s markout at
    or beyond ``MERID_SIDE_CATASTROPHE_M5_CENTS`` (default -5.0c).  These are
    integrity failures — the lane stops rather than earning a graded
    caution.

    Scope (``MERID_SIDE_CATASTROPHE_SCOPE``, default ``asset``): when the
    caller supplies ``asset`` the suspension parks only the
    ``"{asset}:{side}"`` key — a single-cell breach in SOL does not veto
    BTC/ETH/XRP/DOGE on the same side (2026-10-03: one SOL-YES markout
    suspended all YES flow ~19h).  Asset-scoped stops auto-release after
    ``MERID_SIDE_CATASTROPHE_TTL_S`` (default 21600s; ``<=0`` = until
    release).  A whole-side suspension (no asset context, or
    ``MERID_SIDE_CATASTROPHE_SCOPE=side``) stays manual-review — an
    unattributed breach is exactly the case that must not auto-heal.
    """
    if not throttle_enabled() or side not in ("yes", "no"):
        return
    ts = float(ts or time.time())
    scope_key = side
    until = None
    if asset and _catastrophe_scope() == "asset":
        scope_key = f"{str(asset).lower()}:{side}"
        ttl = _catastrophe_ttl_s()
        if ttl > 0:
            until = ts + ttl
    with _THROTTLE_LOCK:
        st = _load_throttle_state(force=True)
        st["suspensions"][scope_key] = {
            "until": until,
            "reason": f"catastrophic:{str(reason)[:120]}",
            "triggered_at": ts,
        }
        _save_throttle_state(st)
    logger.warning(
        "[SIDE-THROTTLE] scope=%s CATASTROPHE -> %s (%s)",
        scope_key,
        (f"suspended {ttl:.0f}s" if until is not None else "manual review"),
        reason,
    )


def _suspension_keys(side: str, asset: Optional[str] = None) -> List[str]:
    keys = [side]
    if asset:
        keys.append(f"{str(asset).lower()}:{side}")
    return keys


def side_throttle_block(
    side: str,
    now: Optional[float] = None,
    asset: Optional[str] = None,
) -> Optional[str]:
    """Return the active suspension reason for ``side``, if any.

    Checks the whole-side key plus the scoped ``"{asset}:{side}"`` key when
    ``asset`` is supplied — an asset-scoped catastrophe blocks only its own
    lane.
    """
    if not throttle_enabled() or side not in ("yes", "no"):
        return None
    now = float(now or time.time())
    st = _load_throttle_state()
    susp = st.get("suspensions") or {}
    for key in _suspension_keys(side, asset):
        sus = susp.get(key)
        if not sus:
            continue
        until = sus.get("until")
        if until is None:
            return f"side_suspended_manual_review:{sus.get('reason')}"
        if now < float(until):
            return f"side_suspended:{sus.get('reason')}"
    return None


def side_caution_margin_cents(side: str, now: Optional[float] = None) -> float:
    """Additive edge-floor margin while ``side`` is in the CAUTION tier.

    CAUTION is not a suspension — the side keeps trading, but each candidate
    must clear ``min_edge + margin`` until the caution expires or a win
    resets the streak.
    """
    if not throttle_enabled() or side not in ("yes", "no"):
        return 0.0
    now = float(now or time.time())
    st = _load_throttle_state()
    caution = (st.get("cautions") or {}).get(side)
    if not caution:
        return 0.0
    until = caution.get("until")
    if until is None or now >= float(until):
        return 0.0
    return _caution_ev_margin_cents()


def side_lane_state(
    side: str,
    now: Optional[float] = None,
    asset: Optional[str] = None,
) -> str:
    """Graded lane level for telemetry: OPEN | CAUTION | SUSPENDED | MANUAL_REVIEW."""
    if side not in ("yes", "no"):
        return "OPEN"
    now = float(now or time.time())
    st = _load_throttle_state()
    susp = st.get("suspensions") or {}
    for key in _suspension_keys(side, asset):
        sus = susp.get(key)
        if not sus:
            continue
        until = sus.get("until")
        if until is None:
            return "MANUAL_REVIEW"
        if now < float(until):
            return "SUSPENDED"
    if side_caution_margin_cents(side, now) > 0.0:
        return "CAUTION"
    return "OPEN"


def _strip_key(ts: float) -> str:
    return str(int(ts // 900))


def strip_concentration_block(
    side: str,
    ev_cents: Optional[float],
    ts: Optional[float] = None,
) -> Optional[str]:
    """One same-directional entry across all five assets per 15-minute strip.

    Additional same-side entries are permitted while fewer than
    ``MERID_STRIP_CONC_MAX_OPEN_SAME_SIDE`` (default 1) prior entries remain
    open — the new candidate must still beat the best prior entry's net EV
    by ``MERID_STRIP_CONC_EV_MARGIN_CENTS``.  Once all priors are closed the
    same EV ladder applies to re-entry.
    """
    if not throttle_enabled() or side not in ("yes", "no"):
        return None
    ts = float(ts or time.time())
    st = _load_throttle_state()
    entries = (st.get("strip_entries") or {}).get(_strip_key(ts)) or []
    same = [e for e in entries if e.get("side") == side]
    if not same:
        return None
    open_same = [e for e in same if e.get("open", True)]
    margin = _strip_ev_margin_cents()
    best_prior = max(float(e.get("ev") or 0.0) for e in same)
    if open_same and len(open_same) >= _strip_max_open_same_side():
        return f"strip_same_side_open:{side}"
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
    recs = st.get("recent_settlements")
    rel_no = _released_ts(st, "no")
    rel_yes = _released_ts(st, "yes")
    return {
        "epoch": st.get("epoch"),
        "suspensions": st.get("suspensions"),
        "cautions": st.get("cautions"),
        "released_at": st.get("released_at"),
        "yes_lane_state": side_lane_state("yes", now),
        "no_lane_state": side_lane_state("no", now),
        "no_streak_60m": _streak(recs, "no", now, _loss_window_s()),
        "yes_streak_60m": _streak(recs, "yes", now, _loss_window_s()),
        "no_streak_epoch": _streak(recs, "no", now, None),
        "yes_streak_epoch": _streak(recs, "yes", now, None),
        "no_streak_post_release": _streak(recs, "no", now, None, since_ts=rel_no),
        "yes_streak_post_release": _streak(recs, "yes", now, None, since_ts=rel_yes),
    }


# ---------------------------------------------------------------------------
# Trend-aligned high-price YES research lane (built, disabled by default)
# ---------------------------------------------------------------------------
#
# Rationale (2026-10-01 operator directive): in RALLY_CONFIRMED the only
# aligned side is YES, but YES asks frequently sit at 91-94c — outside every
# enabled market_regime band — so the band filter rejects the whole market
# before decision evaluation.  This lane is a *narrow* exception for that
# specific structure: it never re-opens 95-99c, it requires a confirmed
# multi-asset rally, and it is measured under its own ``decision_lane`` tag
# so it cannot contaminate the ordinary 10-90c evidence pools.
#
# Built but OFF: ``MERID_TREND_YES_HI_ENABLED`` defaults false.  Enabling is
# a replay-gated operator decision, not a code change.


def trend_yes_hi_enabled() -> bool:
    return _env_flag("MERID_TREND_YES_HI_ENABLED", False)


def _trend_yes_hi_lo() -> float:
    # 91c, not 90c: 90c is already inside the enabled skewed_high band and
    # trades under normal rules — the lane owns only the disabled region.
    return _env_float("MERID_TREND_YES_HI_PRICE_LO", 91.0)


def _trend_yes_hi_hi() -> float:
    return _env_float("MERID_TREND_YES_HI_PRICE_HI", 94.0)


def _trend_yes_hi_min_tte() -> float:
    return _env_float("MERID_TREND_YES_HI_MIN_TTE_S", 120.0)


def _trend_yes_hi_max_tte() -> float:
    return _env_float("MERID_TREND_YES_HI_MAX_TTE_S", 300.0)


def _trend_yes_hi_min_p() -> float:
    return _env_float("MERID_TREND_YES_HI_MIN_P", 0.94)


def _trend_yes_hi_min_ev_cents() -> float:
    return _env_float("MERID_TREND_YES_HI_MIN_EV_CENTS", 3.0)


def _trend_yes_hi_min_breadth() -> int:
    return _env_int("MERID_TREND_YES_HI_MIN_BREADTH", 4)


def _trend_yes_hi_m5_lookback() -> int:
    return _env_int("MERID_TREND_YES_HI_M5_LOOKBACK", 3)


def trend_yes_hi_band_match(price_cents: Optional[float]) -> bool:
    """True when the executable YES ask sits inside the lane's price window.

    Flag-independent on purpose: ``compute_trade_decision`` uses this to
    disable the *normal* YES-qualify path at 91-94c even when the lane is
    off, so a high-price candidate that somehow reaches the decision engine
    without the band filter cannot slip through the ordinary gates.
    """
    if price_cents is None:
        return False
    try:
        p = float(price_cents)
    except (TypeError, ValueError):
        return False
    return _trend_yes_hi_lo() <= p <= _trend_yes_hi_hi()


def trend_yes_hi_reachable(
    yes_price_cents: Optional[float],
    tte_seconds: Optional[float],
) -> bool:
    """Reachability check for the agent_grid band bypass.

    Lets a 91-94c YES ask pass the disabled-tail reject so
    ``compute_trade_decision`` can apply the strict lane gate.  False unless
    the lane is armed AND price/TTE are inside the lane window.
    """
    if not trend_yes_hi_enabled():
        return False
    if not trend_yes_hi_band_match(yes_price_cents):
        return False
    if tte_seconds is None:
        return False
    try:
        tte = float(tte_seconds)
    except (TypeError, ValueError):
        return False
    return _trend_yes_hi_min_tte() <= tte <= _trend_yes_hi_max_tte()


def _rti_return_at(feature_snapshot: Any, asset: str, key: str) -> Optional[float]:
    try:
        sl = (feature_snapshot.by_asset or {}).get(str(asset).upper())
    except Exception:
        sl = None
    if sl is None:
        return None
    try:
        v = (sl.rti_returns or {}).get(key)
    except Exception:
        v = None
    if v is None:
        return None
    try:
        fv = float(v)
    except (TypeError, ValueError):
        return None
    return fv if math.isfinite(fv) else None


def trend_yes_hi_block(
    asset: str,
    yes_price_cents: Optional[float],
    p_yes_cal: Optional[float],
    net_ev_cents: Optional[float],
    tte_seconds: Optional[float],
    regime: Optional[DirectionalRegime],
    feature_snapshot: Any,
) -> Optional[str]:
    """Strict trend-aligned high-price YES admission gate.

    Applies only when the lane is armed and the YES ask is in the lane
    window; returns ``None`` in both the inert case and when every strict
    condition passes.  Each failure names the violated condition so the
    [REGIME-ALIGNED-OPPORTUNITY] telemetry can say *why* an aligned rally
    candidate did not trade.

    Missing momentum inputs fail closed: a 91-94c YES needs positive asset
    30s/60s and BTC 120s returns, and an unverifiable input is a reject, not
    a pass.
    """
    if not trend_yes_hi_enabled():
        return None
    if not trend_yes_hi_band_match(yes_price_cents):
        # Fail closed when armed: a caller that forgot the band pre-check
        # must get a veto, not a pass.  (Inert when disabled so telemetry
        # can consult it unconditionally.)
        return "trend_yes_hi_band"
    if regime is None or regime.label != "RALLY_CONFIRMED":
        return "trend_yes_hi_regime_not_confirmed"
    min_breadth = _trend_yes_hi_min_breadth()
    if regime.breadth60_pos < min_breadth or regime.breadth60_total < min_breadth:
        return "trend_yes_hi_breadth"
    if not (regime.btc_r60 or 0.0) > 0.0:
        return "trend_yes_hi_btc_r60"
    btc_r120 = _rti_return_at(feature_snapshot, "BTC", "rti_return_120s")
    if btc_r120 is None or btc_r120 <= 0.0:
        return "trend_yes_hi_btc_r120"
    a_r30 = _rti_return_at(feature_snapshot, asset, "rti_return_30s")
    a_r60 = (regime.asset_r60 or {}).get(str(asset).upper())
    if a_r30 is None or a_r30 <= 0.0 or a_r60 is None or a_r60 <= 0.0:
        return "trend_yes_hi_asset_momentum"
    if p_yes_cal is None or float(p_yes_cal) < _trend_yes_hi_min_p():
        return "trend_yes_hi_low_conviction"
    if net_ev_cents is None or float(net_ev_cents) < _trend_yes_hi_min_ev_cents():
        return "trend_yes_hi_low_ev"
    if tte_seconds is None or not (
        _trend_yes_hi_min_tte() <= float(tte_seconds) <= _trend_yes_hi_max_tte()
    ):
        return "trend_yes_hi_tte"
    # Lane memory: any negative 5s markout in the asset's YES lane tagged
    # with RALLY_CONFIRMED this epoch closes the lane until the evidence
    # window rolls forward past it.
    try:
        from merid.prediction import current_build_provisional as _cbp

        m5s = _cbp.recent_regime_markout_values(
            asset, "yes", "RALLY_CONFIRMED", limit=_trend_yes_hi_m5_lookback()
        )
    except Exception:
        m5s = []
    if m5s and any(v < 0.0 for v in m5s):
        return "trend_yes_hi_adverse_markout"
    return None
