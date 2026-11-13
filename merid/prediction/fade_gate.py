"""Evidence-decay fade gate (2026-11-12).

Replaces the static ``MERID_FADE_ALLOWED_ASSETS`` cohort list — which
permanently exempted ETH/SOL and permanently blocked BTC/XRP/DOGE fade
entries regardless of how the underlying cohorts evolved — with a
self-resetting per-(asset, side) counterfactual evidence gate.

Design (rolling-window + hysteresis + min-sample + fail-open, per
standard circuit-breaker/probation practice):

* Every fade-shaped candidate (entry side opposes a market lean >=
  ``MERID_FADE_BLOCK_MIN_LEAN_CENTS``) appends one sample
  ``{ticker, side, px, ts, route}`` to ``data/fade_gate_samples.jsonl`` —
  recorded whether the gate allows or blocks, so blocked cohorts keep
  producing settlement evidence and the window keeps rolling.
* A throttled refresh settles pending samples against
  ``logs/settlement_outcomes.jsonl`` and maintains a trailing window of
  counterfactual PnL per (asset, side) in ``data/fade_gate_state.json``.
* Hysteresis:
    allowed -> blocked : n >= MIN_SAMPLE and trailing EV < TRIP_EV_C
    blocked -> allowed : trailing EV >= RELEASE_EV_C
                         or no fresh settled sample within STALE_S
* Fail-open everywhere: missing/corrupt state, missing settlement feed,
  or any internal error resolves to ALLOW.  A gate that fails closed on
  its own bug silently halts the strategy.

Modes (``MERID_FADE_GATE_MODE``):
    auto       — evidence gate (default; releases all assets until a
                 trailing cohort proves toxic)
    allowlist  — legacy static MERID_FADE_ALLOWED_ASSETS behaviour
    off        — never block
"""

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

_MODE = os.environ.get("MERID_FADE_GATE_MODE", "auto").strip().lower()
_WINDOW = int(os.environ.get("MERID_FADE_GATE_WINDOW", "50"))
_MIN_SAMPLE = int(os.environ.get("MERID_FADE_GATE_MIN_SAMPLE", "20"))
_TRIP_EV_C = float(os.environ.get("MERID_FADE_GATE_TRIP_EV_C", "-2.0"))
_RELEASE_EV_C = float(os.environ.get("MERID_FADE_GATE_RELEASE_EV_C", "0.0"))
_STALE_S = float(os.environ.get("MERID_FADE_GATE_STALE_S", str(7 * 86400)))
_PENDING_TTL_S = float(os.environ.get("MERID_FADE_GATE_PENDING_TTL_S", str(6 * 3600)))
_REFRESH_S = float(os.environ.get("MERID_FADE_GATE_REFRESH_S", "300"))

# 2026-11-13 (cost-basis veto audit): unconditional admission vetoes
# (``cost_basis_override_{side}``) measured as net value-destroying on the
# settled counterfactual — the NO cohort ran +6.4c/trade forfeited
# (BTC-NO +17.4c, n=34) while XRP-NO stayed toxic (-36c).  Same evidence
# pattern as the fade gate, opposite polarity: the veto stands by default
# and releases per (gate, asset, side) only on POSITIVE settled proof —
# fail-CLOSED on missing evidence, matching the drift scope-release rule
# (releasing an admission broadener requires proof, not absence of proof).
_VETO_RELEASE_MODE = os.environ.get(
    "MERID_VETO_RELEASE_MODE", "auto"
).strip().lower()
_VETO_RELEASE_MIN_N = int(os.environ.get("MERID_VETO_RELEASE_MIN_N", "20"))
_VETO_RELEASE_MIN_EV_C = float(
    os.environ.get("MERID_VETO_RELEASE_MIN_EV_C", "2.0")
)

_STATE_PATH = Path(
    os.environ.get("MERID_FADE_GATE_STATE_PATH", "data/fade_gate_state.json")
)
_SAMPLES_PATH = Path(
    os.environ.get("MERID_FADE_GATE_SAMPLES_PATH", "data/fade_gate_samples.jsonl")
)
_SETTLEMENTS_PATH = Path(
    os.environ.get(
        "MERID_FADE_GATE_SETTLEMENTS_PATH", "logs/settlement_outcomes.jsonl"
    )
)

_lock = threading.Lock()
_last_refresh_ts = 0.0
# (gate, asset, side) -> {"state": "allowed"|"blocked", "trailing": [pnl,...], "last_settled_ts": float}
_cohorts: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
# pending samples awaiting settlement: (gate, ticker, side) -> sample dict
_pending: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
_state_loaded = False


def gate_mode() -> str:
    return _MODE


def _cohort_pnl(side: str, px: float, resolved_yes: int) -> float:
    win = (resolved_yes == 1 and side == "yes") or (
        resolved_yes == 0 and side == "no"
    )
    return (100.0 - px) if win else -px


def _load_state() -> None:
    """Load persisted gate state once per process.  Fail-open on any error."""
    global _state_loaded, _cohorts, _pending, _last_refresh_ts
    with _lock:
        if _state_loaded:
            return
        _state_loaded = True
        try:
            if _STATE_PATH.exists():
                data = json.loads(_STATE_PATH.read_text(encoding="utf-8"))
            else:
                data = {}
            for key, rec in (data.get("cohorts") or {}).items():
                parts = str(key).split("|")
                if len(parts) == 2:
                    gate, rest = "fade", parts[0] + "|" + parts[1]
                    asset, side = rest.split("|", 1)
                elif len(parts) == 3:
                    gate, asset, side = parts
                else:
                    continue
                trailing = [
                    float(x)
                    for x in (rec.get("trailing") or [])
                    if isinstance(x, (int, float))
                ][-_WINDOW:]
                _cohorts[(gate, asset.upper(), side.lower())] = {
                    "state": (
                        "blocked"
                        if rec.get("state") == "blocked"
                        else "allowed"
                    ),
                    "trailing": trailing,
                    "last_settled_ts": float(rec.get("last_settled_ts") or 0.0),
                }
            for s in data.get("pending") or []:
                try:
                    key = (
                        str(s.get("gate") or "fade"),
                        str(s["ticker"]),
                        str(s["side"]).lower(),
                    )
                    _pending[key] = {
                        "gate": key[0],
                        "asset": str(s.get("asset") or "").upper(),
                        "side": str(s.get("side") or "").lower(),
                        "px": float(s.get("px") or 0.0),
                        "ts": float(s.get("ts") or 0.0),
                        "route": s.get("route"),
                    }
                except (KeyError, TypeError, ValueError):
                    continue
            _last_refresh_ts = float(data.get("last_refresh_ts") or 0.0)
        except Exception as e:  # pragma: no cover - fail-open telemetry
            logger.debug("[FADE-GATE] state load failed (fail-open): %s", e)
            _cohorts = {}
            _pending = {}


def _save_state() -> None:
    """Persist state atomically.  Never raises."""
    try:
        _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "cohorts": {
                f"{g}|{a}|{s}": {
                    "state": rec["state"],
                    "trailing": rec["trailing"][-_WINDOW:],
                    "last_settled_ts": rec.get("last_settled_ts", 0.0),
                }
                for (g, a, s), rec in _cohorts.items()
            },
            "pending": [
                {
                    "gate": g,
                    "ticker": t,
                    "side": p["side"],
                    "asset": p["asset"],
                    "px": p["px"],
                    "ts": p["ts"],
                    "route": p.get("route"),
                }
                for (g, t, _s), p in _pending.items()
            ],
            "last_refresh_ts": _last_refresh_ts,
        }
        tmp = _STATE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(tmp, _STATE_PATH)
    except Exception as e:  # pragma: no cover
        logger.debug("[FADE-GATE] state save failed: %s", e)


def _settlement_map() -> Dict[str, int]:
    """ticker -> resolved_yes from the settlement outcome feed."""
    out: Dict[str, int] = {}
    try:
        with open(_SETTLEMENTS_PATH, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if '"ticker"' not in line:
                    continue
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                t = r.get("ticker")
                ry = r.get("resolved_yes")
                if t and ry is not None:
                    out[str(t)] = int(ry)
    except Exception as e:  # pragma: no cover
        logger.debug("[FADE-GATE] settlement feed read failed: %s", e)
    return out


def _refresh_if_due(now: float) -> None:
    """Settle pending samples and re-evaluate cohort states.  Throttled."""
    global _last_refresh_ts
    if now - _last_refresh_ts < _REFRESH_S:
        return
    _last_refresh_ts = now
    try:
        settlements = _settlement_map()
        changed = False
        # Settle pending samples whose market has resolved.
        for key in list(_pending.keys()):
            gate, ticker, side = key
            sample = _pending[key]
            ry = settlements.get(ticker)
            if ry is not None:
                asset = sample["asset"] or "UNKNOWN"
                ckey = (gate, asset, side)
                rec = _cohorts.setdefault(
                    ckey,
                    {"state": "allowed", "trailing": [], "last_settled_ts": 0.0},
                )
                rec["trailing"].append(
                    _cohort_pnl(side, float(sample["px"]), int(ry))
                )
                rec["trailing"] = rec["trailing"][-_WINDOW:]
                rec["last_settled_ts"] = now
                del _pending[key]
                changed = True
            elif now - float(sample.get("ts") or 0.0) > _PENDING_TTL_S:
                del _pending[key]
                changed = True
        # Re-evaluate hysteresis for every cohort with evidence.
        for (gate, asset, side), rec in _cohorts.items():
            trailing = rec["trailing"]
            n = len(trailing)
            if n == 0:
                continue
            ev = sum(trailing) / n
            state = rec["state"]
            if state == "allowed" and n >= _MIN_SAMPLE and ev < _TRIP_EV_C:
                rec["state"] = "blocked"
                changed = True
                logger.info(
                    "[FADE-GATE] BLOCK %s %s %s fade: trailing n=%d ev=%.2fc < %.2fc",
                    gate, asset, side.upper(), n, ev, _TRIP_EV_C,
                )
            elif state == "blocked" and (
                ev >= _RELEASE_EV_C
                or now - float(rec.get("last_settled_ts") or 0.0) > _STALE_S
            ):
                rec["state"] = "allowed"
                changed = True
                logger.info(
                    "[FADE-GATE] RELEASE %s %s %s fade: trailing n=%d ev=%.2fc",
                    gate, asset, side.upper(), n, ev,
                )
        if changed:
            _compact_samples_file()
            _save_state()
    except Exception as e:  # pragma: no cover - fail-open
        logger.debug("[FADE-GATE] refresh failed (fail-open): %s", e)


def _compact_samples_file() -> None:
    """Rewrite the samples file keeping only still-pending samples."""
    try:
        if not _SAMPLES_PATH.exists():
            return
        pending_keys = set(_pending.keys())
        kept = []
        with open(_SAMPLES_PATH, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    s = json.loads(line)
                except Exception:
                    continue
                key = (
                    str(s.get("gate") or "fade"),
                    str(s.get("ticker") or ""),
                    str(s.get("side") or "").lower(),
                )
                if key in pending_keys:
                    kept.append(line if line.endswith("\n") else line + "\n")
        tmp = _SAMPLES_PATH.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.writelines(kept)
        os.replace(tmp, _SAMPLES_PATH)
    except Exception as e:  # pragma: no cover
        logger.debug("[FADE-GATE] samples compaction failed: %s", e)


def _record_sample(
    *,
    gate: str,
    asset: str,
    side: str,
    ticker: str,
    px: float,
    route: Optional[str],
) -> None:
    """Append one gated-candidate sample.  Dedupes per (gate, ticker, side)."""
    try:
        gate = str(gate or "fade").lower()
        key = (gate, str(ticker), side)
        if key in _pending:
            return
        sample = {
            "gate": gate,
            "ticker": str(ticker),
            "side": side,
            "asset": str(asset).upper(),
            "px": float(px),
            "ts": time.time(),
            "route": route,
        }
        _pending[key] = sample
        _SAMPLES_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_SAMPLES_PATH, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(sample) + "\n")
    except Exception as e:  # pragma: no cover - telemetry must never break trading
        logger.debug("[FADE-GATE] sample record failed: %s", e)


def cohort_stats(gate: str, asset: str, side: str) -> Dict[str, Any]:
    """Return {state, n, ev_c} for a (gate, asset, side) cohort.

    Used by upstream scope gates (e.g. drift lane) that admit an excluded
    candidate only on POSITIVE settled-counterfactual proof — ``n`` samples
    and ``ev_c`` above the release bound — not merely 'not currently
    blocked'.  Fail-open shape: missing cohort returns n=0, ev_c=None.
    """
    try:
        _load_state()
        with _lock:
            _refresh_if_due(time.time())
            rec = _cohorts.get(
                (str(gate).lower(), str(asset).upper(), str(side).lower())
            )
            if not rec:
                return {"state": "allowed", "n": 0, "ev_c": None}
            trailing = rec.get("trailing") or []
            return {
                "state": rec.get("state", "allowed"),
                "n": len(trailing),
                "ev_c": (
                    round(sum(trailing) / len(trailing), 2) if trailing else None
                ),
            }
    except Exception as e:  # pragma: no cover - fail-open
        logger.debug("[FADE-GATE] cohort_stats failed (fail-open): %s", e)
        return {"state": "allowed", "n": 0, "ev_c": None}


def record_shadow_sample(
    *,
    gate: str,
    asset: str,
    side: str,
    ticker: str,
    px: float,
    route: Optional[str] = None,
) -> None:
    """Record a counterfactual sample for a candidate excluded upstream.

   Upstream scope gates (drift lane asset/side lists, midwin exclusions)
    reject candidates before they reach the decision engine, so they
    produce no rejected_candidate records and no settlement evidence.  This
    API lets them emit the same (gate, asset, side, ticker, px) sample the
    fade gate uses; ``cohort_stats`` then measures the excluded cohort's
    settled counterfactual EV and the gate can release on proof.
    Never raises; samples dedupe per (gate, ticker, side).
    """
    try:
        _load_state()
        _record_sample(
            gate=gate,
            asset=asset,
            side=side,
            ticker=ticker,
            px=float(px),
            route=route,
        )
        with _lock:
            _refresh_if_due(time.time())
    except Exception as e:  # pragma: no cover - telemetry must never break trading
        logger.debug("[FADE-GATE] shadow sample failed: %s", e)


def veto_release_check(
    *,
    gate: str,
    asset: str,
    side: str,
    ticker: str,
    px: float,
    route: Optional[str] = None,
) -> Tuple[bool, Dict[str, Any]]:
    """Evidence-release for unconditional admission vetoes.

    Every veto-eligible candidate appends a counterfactual sample under
    ``gate`` (deduped per ticker+side, same store as the fade gate), then
    the (gate, asset, side) cohort's settled trailing EV decides:

        released  : n >= MIN_N and trailing EV >= MIN_EV_C
        veto      : everything else — including no evidence at all

    ``MIN_EV_C`` defaults to +2c so the release clears the ~1-3c
    adverse-selection haircut quoted-price counterfactuals carry on maker
    fills.  Stateless by design: the rolling window re-derives the verdict
    on every refresh, so a released cohort whose evidence decays back below
    the bound is re-vetoed automatically (bounded flap at the boundary,
    smoothed by the 300s refresh throttle).

    Modes (``MERID_VETO_RELEASE_MODE``):
        auto — release on proven positive evidence (default)
        off  — never release; the caller's veto applies unconditionally

    Fail-closed on internal/evidence errors when mode=auto?  No — an
    internal error returns ``released=False`` (veto stands) because this
    gate exists to *broaden* admission; a broken evidence store must not
    silently admit.  Telemetry failures inside ``_record_sample`` still
    never raise.
    """
    detail: Dict[str, Any] = {"mode": _VETO_RELEASE_MODE, "gate": gate}
    if _VETO_RELEASE_MODE != "auto":
        detail["outcome"] = "mode_off_veto_stands"
        return False, detail
    try:
        _load_state()
        _record_sample(
            gate=str(gate or "veto").lower(),
            asset=asset,
            side=side,
            ticker=ticker,
            px=float(px),
            route=route,
        )
        with _lock:
            _refresh_if_due(time.time())
            rec = _cohorts.get(
                (str(gate).lower(), str(asset).upper(), str(side).lower())
            )
            trailing = (rec or {}).get("trailing") or []
            n = len(trailing)
            ev_c = (
                round(sum(trailing) / n, 2) if n else None
            )
            released = bool(
                n >= _VETO_RELEASE_MIN_N
                and ev_c is not None
                and ev_c >= _VETO_RELEASE_MIN_EV_C
            )
            detail["outcome"] = "released" if released else "veto_stands"
            detail["cohort"] = {"n": n, "ev_c": ev_c}
            if released:
                logger.info(
                    "[VETO-RELEASE] %s %s %s: trailing n=%d ev=%.2fc >= %.2fc",
                    gate, str(asset).upper(), str(side).upper(),
                    n, ev_c, _VETO_RELEASE_MIN_EV_C,
                )
            return released, detail
    except Exception as e:  # pragma: no cover - fail-closed for admission broadening
        logger.debug("[VETO-RELEASE] check failed (veto stands): %s", e)
        detail["outcome"] = "error_veto_stands"
        return False, detail


def fade_gate_check(
    *,
    asset: str,
    side: str,
    ticker: str,
    lean_cents: float,
    entry_price_cents: float,
    route: Optional[str] = None,
) -> Tuple[bool, Dict[str, Any]]:
    """Return (allowed, detail) for a fade-shaped candidate.

    ``lean_cents`` is the signed market lean (mid - 50c)*100; the caller has
    already determined the candidate fades a >= threshold lean and dispatches
    on ``gate_mode()`` — this function implements the ``auto`` evidence gate:
    every fade-shaped candidate is sampled for counterfactual evidence and
    the per-(asset, side) cohort state decides admission.
    """
    detail: Dict[str, Any] = {"mode": _MODE}
    if _MODE != "auto":
        detail["outcome"] = "non_auto_mode"
        return True, detail
    try:
        _load_state()
        now = time.time()
        _record_sample(
            gate="fade",
            asset=asset,
            side=side,
            ticker=ticker,
            px=float(entry_price_cents),
            route=route,
        )
        with _lock:
            _refresh_if_due(now)
            rec = _cohorts.get(("fade", str(asset).upper(), side.lower()))
            if rec is None or rec.get("state") != "blocked":
                detail["outcome"] = "allowed"
                detail["cohort"] = {
                    "state": (rec or {}).get("state", "allowed"),
                    "n": len((rec or {}).get("trailing") or []),
                    "ev_c": (
                        round(
                            sum(rec["trailing"]) / len(rec["trailing"]), 2
                        )
                        if rec and rec.get("trailing")
                        else None
                    ),
                }
                return True, detail
            detail["outcome"] = "blocked"
            detail["cohort"] = {
                "state": "blocked",
                "n": len(rec.get("trailing") or []),
                "ev_c": round(
                    sum(rec["trailing"]) / len(rec["trailing"]), 2
                )
                if rec.get("trailing")
                else None,
            }
            return False, detail
    except Exception as e:  # pragma: no cover - fail-open
        logger.debug("[FADE-GATE] check failed (fail-open): %s", e)
        detail["outcome"] = "error_fail_open"
        return True, detail
