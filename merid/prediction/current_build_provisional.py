"""Current-build dual-side provisional lane (``current_build_provisional``).

A bounded, versioned live-learning lane that evaluates BOTH the YES and NO
sides of every first-class asset (BTC, ETH, SOL, XRP, DOGE) under current
executable economics.  It exists because evidence produced by earlier builds —
different router semantics, fee schedules, evidence policy, and exit policy —
must not permanently paralyze the current system, but must not be blindly
trusted either.

Policy
------
    admit iff net_ev_current >= T_provisional(asset, side)

where ``net_ev_current`` is the same cost-aware executable net edge the
canonical pipeline computes (executable ask, exact fee, book/depth and
model-risk reserves already charged).  ``T_provisional`` is deliberately
lower than the legacy generic base+convexity+FLB formula but still positive:

    NO  side: BTC 2.0c, ETH 2.0c, SOL 2.5c, XRP 2.5c, DOGE 2.5c
    YES side: BTC 2.5c, ETH 2.5c, SOL 3.0c, XRP 3.0c, DOGE 3.0c

(YES carries a +0.5c measurement premium: historical YES counterfactuals were
weak and unvalidated for *execution*, so the measurement bar is stricter.)

Cell grid
---------
``asset x side x price-band x TTE-band`` over the bounded domain

    price: 20c <= ask < 90c   (10c bands: 20-30 ... 80-90)
    tte:   120s <= tte <= 600s (bands: [120,300], (300,600])

Cells are generated programmatically — there is no promotion pipeline for this
lane; coverage is a policy statement, not a data-qualified claim.  A region
covered by an approved ``threshold_cells`` registry cell is NEVER re-admitted
through this lane: the qualified cell (including SUSPENDED state) keeps sole
authority there.  The provisional lane owns only regions with no registered
cell.

Legacy-evidence treatment
-------------------------
Inside the provisional domain, the cell-aware evidence policy
(``evidence_policy.evaluate``) is demoted from gate to label:

    * every verdict — SPARSE_MATCHED_INSUFFICIENT, SOFT_PENALTY_INSUFFICIENT,
      CHALLENGE_INSUFFICIENT, ESCAPE_CAP_EXHAUSTED, MATCHING_TOXIC_CELL,
      CELL_EVIDENCE_INSUFFICIENT, and ``matching_hard_block`` alike — is
      recorded as ``legacy_risk_label`` and contributes monitoring intensity,
      never a block by itself;
    * the generic evidence escape-lane budget is not consumed — this lane's
      own caps apply instead;
    * current-build hard safety failures are untouched: stale/untrusted book,
      negative executable EV, unconstructable post-only order, tail/timing
      domain violations, depth/cost-basis/EV-gate failures, and the router's
      immutable ExecutionPolicy all still reject or veto normally.

Execution contract
------------------
Every admitted order is one contract, post-only maker, no taker fallback,
<=1 reprice, ~45s max resting lifetime (``ExecutionPolicy`` stamped at intent
construction; enforced pre-wire by the router).  Quantity is clamped to one
contract regardless of sizing output.

Caps (per UTC day, all independent, env-tunable):

    * ``MERID_PROVISIONAL_DAILY_MAX_FILLS_TOTAL``      (default 3)
    * ``MERID_PROVISIONAL_DAILY_MAX_FILLS_PER_ASSET``  (default 1)
    * ``MERID_PROVISIONAL_DAILY_MAX_FILLS_YES``        (default 1)
    * ``MERID_PROVISIONAL_DAILY_MAX_FILLS_NO``         (default 3)
    * ``MERID_PROVISIONAL_DAILY_MAX_FILLS``            (per cell, default 1)
    * ``MERID_PROVISIONAL_DAILY_MAX_SUBMISSIONS``      (lane-wide, default 20)
    * ``MERID_PROVISIONAL_PER_CELL_MAX_SUBMISSIONS``   (default 5)
    * ``MERID_PROVISIONAL_MAX_OPEN_ORDERS``            (per cell, default 1)
    * ``MERID_PROVISIONAL_MAX_OPEN_ORDERS_TOTAL``      (default 1)

Automatic suspension (fail-closed per cell; durable across restarts via
``data/current_build_provisional_lane.json``):

    * first fill: 5s markout <= -3c, or fill-time EV <= 0, or first settled
      trade worse than -(candidate EV + 2c);
    * ANY fill with fill-time EV <= 0;
    * post-only order fills as taker (fill price crossed the limit) or a
      side/mapping invariant violation — immediate;
    * >= 2 consecutive router rejects;
    * rolling MERID_PROVISIONAL_SUSPEND_MIN_FILLS (default 3): mean net PnL
      < -1c, or median 5s markout < -1c, or >=2 of the last N fills show a
      negative 5s markout;
    * router reject/cross rate > 40% once a cell has >=5 attempts;
    * > 2 execution/integrity failures.

Versioned evidence store
------------------------
Every lifecycle/economic record is appended to

    data/evidence/current_build/<build_sha>/<model_version>/resolutions.jsonl

with build_sha, model_version, calibration_version, evidence_generation,
policy_version, admission_lane, asset, side, price/tte buckets, current EV,
required EV, book source, and post-only state — so current-build fills are
never merged into or confused with legacy counterfactual evidence.  When
combining with legacy posteriors downstream, current-build fills carry high
authority and legacy data decays to prior weight.

Kill switches: ``MERID_PROVISIONAL_LANE=0`` disables the lane entirely (all
candidates fall back to the formula path); ``MERID_PROVISIONAL_MAKER=0``
suppresses emission rather than coercing to taker.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import statistics
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, NamedTuple, Optional, Tuple

logger = logging.getLogger(__name__)


LANE_NAME = "current_build_provisional"
POLICY_VERSION = "cbp_v1"
CELL_PREFIX = "cbp_"

ALL_ASSETS: Tuple[str, ...] = ("BTC", "ETH", "SOL", "XRP", "DOGE")
ALL_SIDES: Tuple[str, ...] = ("yes", "no")

# ---------------------------------------------------------------------------
# Domain + thresholds
# ---------------------------------------------------------------------------

# Hard domain (the approved contract): 20-89c executable ask, 120-600s TTE.
# Env overrides may only NARROW these bounds — widening past the generated
# cell grid admits nothing (fail closed).
_DOMAIN_PRICE_MIN_CENTS = 20
_DOMAIN_PRICE_MAX_CENTS = 90   # exclusive
_DOMAIN_TTE_MIN_S = 120.0
_DOMAIN_TTE_MAX_S = 600.0      # inclusive

_PRICE_BANDS: Tuple[Tuple[int, int], ...] = tuple(
    (lo, lo + 10) for lo in range(20, 90, 10)
)
# Lower band is [120, 300]; upper is (300, 600] — deterministic, no overlap.
_TTE_BANDS: Tuple[Tuple[float, float], ...] = ((120.0, 300.0), (300.0, 600.0))

# Provisional min net EV (cents) per asset x side.  NO follows the dual-side
# rollout table; YES carries the +0.5c measurement premium because legacy YES
# counterfactuals were never validated for passive execution.
_DEFAULT_MIN_EV_CENTS: Dict[str, Dict[str, float]] = {
    "BTC": {"yes": 2.5, "no": 2.0},
    "ETH": {"yes": 2.5, "no": 2.0},
    "SOL": {"yes": 3.0, "no": 2.5},
    "XRP": {"yes": 3.0, "no": 2.5},
    "DOGE": {"yes": 3.0, "no": 2.5},
}


def _env_flag(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    try:
        return int(float(os.environ.get(name, str(default))))
    except Exception:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except Exception:
        return default


def provisional_enabled() -> bool:
    """Master switch: ``MERID_PROVISIONAL_LANE=0`` disables the lane."""
    return _env_flag("MERID_PROVISIONAL_LANE", True)


def provisional_maker_enabled() -> bool:
    """``MERID_PROVISIONAL_MAKER=0`` suppresses emission rather than coercing
    to taker — identical contract to MERID_THRESHOLD_CELL_MAKER."""
    return _env_flag("MERID_PROVISIONAL_MAKER", True)


def provisional_evidence_override_enabled() -> bool:
    """``MERID_PROVISIONAL_EVIDENCE_OVERRIDE=0`` restores legacy evidence
    verdicts as blocks inside the provisional domain (emergency off-switch)."""
    return _env_flag("MERID_PROVISIONAL_EVIDENCE_OVERRIDE", True)


def domain_price_min_cents() -> int:
    return min(
        max(_env_int("MERID_PROVISIONAL_PRICE_MIN_CENTS", _DOMAIN_PRICE_MIN_CENTS),
            _DOMAIN_PRICE_MIN_CENTS),
        _DOMAIN_PRICE_MAX_CENTS,
    )


def domain_price_max_cents() -> int:
    return max(
        min(_env_int("MERID_PROVISIONAL_PRICE_MAX_CENTS", _DOMAIN_PRICE_MAX_CENTS),
            _DOMAIN_PRICE_MAX_CENTS),
        _DOMAIN_PRICE_MIN_CENTS + 1,
    )


def domain_tte_min_seconds() -> float:
    return min(
        max(_env_float("MERID_PROVISIONAL_TTE_MIN_S", _DOMAIN_TTE_MIN_S),
            _DOMAIN_TTE_MIN_S),
        _DOMAIN_TTE_MAX_S,
    )


def domain_tte_max_seconds() -> float:
    return max(
        min(_env_float("MERID_PROVISIONAL_TTE_MAX_S", _DOMAIN_TTE_MAX_S),
            _DOMAIN_TTE_MAX_S),
        _DOMAIN_TTE_MIN_S + 1.0,
    )


def provisional_min_ev_cents(asset: str, side: str) -> float:
    """Per (asset, side) provisional min net EV in cents; env-overridable via
    ``MERID_PROVISIONAL_MIN_EV_C_{ASSET}_{SIDE}`` or the shared
    ``MERID_PROVISIONAL_MIN_EV_C`` fallback."""
    a, s = str(asset).upper(), str(side).lower()
    default = _DEFAULT_MIN_EV_CENTS.get(a, {}).get(s, 3.0)
    v = os.environ.get(f"MERID_PROVISIONAL_MIN_EV_C_{a}_{s.upper()}")
    if v is None:
        v = os.environ.get("MERID_PROVISIONAL_MIN_EV_C")
    try:
        return float(v) if v is not None else float(default)
    except Exception:
        return float(default)


class ProvisionalCell(NamedTuple):
    """One bounded provisional cell: asset x side x price-band x tte-band.

    Price bounds are half-open (``pmin <= ask < pmax``); TTE bands are
    ``[120,300]`` then ``(300,600]`` — see :func:`_tte_in_band`.
    """

    cell_id: str
    asset: str
    side: str  # "yes" | "no"
    price_min_cents: int
    price_max_cents: int
    tte_min_seconds: float
    tte_max_seconds: float
    min_net_ev_cents: float


def _build_cells() -> Tuple[ProvisionalCell, ...]:
    cells: List[ProvisionalCell] = []
    for asset in ALL_ASSETS:
        for side in ALL_SIDES:
            for pmin, pmax in _PRICE_BANDS:
                for tlo, thi in _TTE_BANDS:
                    cells.append(ProvisionalCell(
                        cell_id=(
                            f"{CELL_PREFIX}{asset.lower()}_{side}_"
                            f"{pmin}_{pmax}_t{int(tlo)}_{int(thi)}"
                        ),
                        asset=asset,
                        side=side,
                        price_min_cents=pmin,
                        price_max_cents=pmax,
                        tte_min_seconds=tlo,
                        tte_max_seconds=thi,
                        min_net_ev_cents=provisional_min_ev_cents(asset, side),
                    ))
    return tuple(cells)


PROVISIONAL_CELLS: Tuple[ProvisionalCell, ...] = _build_cells()
_CBP_BY_ID: Dict[str, ProvisionalCell] = {c.cell_id: c for c in PROVISIONAL_CELLS}
assert len(_CBP_BY_ID) == len(PROVISIONAL_CELLS), "provisional cell ids must be unique"

CELLS_BY_ASSET: Dict[str, Tuple[str, ...]] = {
    a: tuple(c.cell_id for c in PROVISIONAL_CELLS if c.asset == a)
    for a in ALL_ASSETS
}


def provisional_cell_for_id(cell_id: Optional[str]) -> Optional[ProvisionalCell]:
    return _CBP_BY_ID.get(cell_id) if cell_id else None


def cell_min_ev_cents(cell: ProvisionalCell) -> float:
    """The cell's live min net EV — env overrides apply even post-import."""
    return provisional_min_ev_cents(cell.asset, cell.side)


def price_band_label(cell: ProvisionalCell) -> str:
    return f"{cell.price_min_cents}-{cell.price_max_cents}"


def tte_band_label(cell: ProvisionalCell) -> str:
    return f"{int(cell.tte_min_seconds)}-{int(cell.tte_max_seconds)}"


def _tte_in_band(tte: float, lo: float, hi: float, first: bool) -> bool:
    # [120,300] then (300,600]: the shared boundary belongs to the lower band.
    return (lo <= tte <= hi) if first else (lo < tte <= hi)


def resolve_provisional_cell(
    asset: str,
    side: str,
    price_cents: Optional[float],
    tte_seconds: Optional[float],
) -> Optional[ProvisionalCell]:
    """Return the provisional cell covering (asset, side, price, tte), or None.

    None means "outside the provisional domain" — the caller falls back to the
    formula path.  Never returns a cell outside the configured domain, even if
    env overrides are inconsistent.
    """
    if not provisional_enabled():
        return None
    if price_cents is None or tte_seconds is None:
        return None
    asset_u, side_l = str(asset).upper(), str(side).lower()
    if asset_u not in ALL_ASSETS or side_l not in ALL_SIDES:
        return None
    px, tte = float(price_cents), float(tte_seconds)
    if not (domain_price_min_cents() <= px < domain_price_max_cents()):
        return None
    if not (domain_tte_min_seconds() <= tte <= domain_tte_max_seconds()):
        return None
    for cell in PROVISIONAL_CELLS:
        if cell.asset != asset_u or cell.side != side_l:
            continue
        if not (cell.price_min_cents <= px < cell.price_max_cents):
            continue
        first_band = cell.tte_min_seconds == _TTE_BANDS[0][0]
        if not _tte_in_band(tte, cell.tte_min_seconds, cell.tte_max_seconds, first_band):
            continue
        return cell
    return None


def explain_provisional_miss(
    asset: str,
    side: str,
    price_cents: Optional[float],
    tte_seconds: Optional[float],
) -> Optional[str]:
    """Why no provisional cell covered this point — for heartbeat/telemetry."""
    if not provisional_enabled():
        return "provisional_lane_disabled"
    asset_u, side_l = str(asset).upper(), str(side).lower()
    if asset_u not in ALL_ASSETS:
        return "provisional_asset_not_in_universe"
    if price_cents is None:
        return "provisional_price_unknown"
    if tte_seconds is None:
        return "provisional_tte_unknown"
    if resolve_provisional_cell(asset_u, side_l, price_cents, tte_seconds) is not None:
        return None
    px, tte = float(price_cents), float(tte_seconds)
    if px < domain_price_min_cents():
        return "provisional_price_below_min"
    if px >= domain_price_max_cents():
        return "provisional_price_above_max"
    if tte < domain_tte_min_seconds():
        return "provisional_tte_below_min"
    if tte > domain_tte_max_seconds():
        return "provisional_tte_above_max"
    return "provisional_cell_gap"


# ---------------------------------------------------------------------------
# Version stamps + evidence store
# ---------------------------------------------------------------------------

def current_build_sha() -> str:
    v = os.environ.get("MERID_BUILD_SHA", "").strip()
    if v:
        return v
    try:
        from merid.config.live_config import get_resolved_live_config
        resolved = get_resolved_live_config(allow_unresolved=True)
        sha = getattr(resolved, "build_sha", "") if getattr(resolved, "resolved", False) else ""
        if sha:
            return str(sha)
    except Exception:
        pass
    return "unknown"


def current_model_version(indicators: Optional[Dict[str, Any]] = None) -> str:
    if indicators:
        mv = indicators.get("settlement_model_version") or indicators.get("model_version")
        if mv:
            return str(mv)
    v = os.environ.get("MERID_MODEL_VERSION", "").strip()
    return v or "bachelier_twap"


_CALIB_VERSION_CACHE: Dict[str, Optional[str]] = {"v": None}


def current_calibration_version() -> str:
    """Content hash of the live tail-calibration artifact (12 hex chars),
    ``MERID_CALIBRATION_VERSION`` override, or ``"none"`` when no calibrator."""
    v = os.environ.get("MERID_CALIBRATION_VERSION", "").strip()
    if v:
        return v
    if _CALIB_VERSION_CACHE["v"] is not None:
        return _CALIB_VERSION_CACHE["v"] or "none"
    digest: Optional[str] = None
    try:
        path = os.environ.get("MERID_TAIL_CALIBRATION_PATH") or os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "data", "probability_tail_calibration.json",
        )
        if os.path.exists(path):
            with open(path, "rb") as fh:
                digest = hashlib.sha256(fh.read()).hexdigest()[:12]
    except Exception:
        digest = None
    _CALIB_VERSION_CACHE["v"] = digest
    return digest or "none"


def reset_calibration_version_cache() -> None:
    _CALIB_VERSION_CACHE["v"] = None


def evidence_dir(
    build_sha: Optional[str] = None,
    model_version: Optional[str] = None,
) -> str:
    base = os.environ.get(
        "MERID_PROVISIONAL_EVIDENCE_DIR", "data/evidence/current_build"
    )
    return os.path.join(
        base,
        build_sha or current_build_sha(),
        model_version or current_model_version(),
    )


def record_cb_evidence(
    record_kind: str,
    *,
    build_sha: Optional[str] = None,
    model_version: Optional[str] = None,
    calibration_version: Optional[str] = None,
    evidence_generation: Optional[Any] = None,
    indicators: Optional[Dict[str, Any]] = None,
    **fields: Any,
) -> None:
    """Append one versioned record to the current-build evidence store.

    Layout: ``data/evidence/current_build/<build_sha>/<model_version>/
    resolutions.jsonl``.  Records carry the full provenance chain
    (build/model/calibration/policy versions + admission lane) so they are
    never merged with pre-change legacy evidence by mistake.
    """
    try:
        b = build_sha or current_build_sha()
        m = model_version or current_model_version(indicators)
        rec: Dict[str, Any] = {
            "event": "current_build_evidence",
            "record_kind": record_kind,
            "admission_lane": LANE_NAME,
            "policy_version": POLICY_VERSION,
            "build_sha": b,
            "model_version": m,
            "calibration_version": calibration_version
            or current_calibration_version(),
            "evidence_generation": evidence_generation,
            "ts": time.time(),
            "ts_utc": datetime.now(timezone.utc).isoformat(),
        }
        rec.update(fields)
        path = os.path.join(evidence_dir(b, m), "resolutions.jsonl")
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, default=str, separators=(",", ":")) + "\n")
    except Exception as exc:
        logger.debug("[CBP] evidence record failed: %s", exc)


# ---------------------------------------------------------------------------
# Lane state file: caps, per-cell state machine, outcomes, funnel counters
# ---------------------------------------------------------------------------
# ``data/current_build_provisional_lane.json`` mirrors the threshold-cell lane
# state: daily-scoped counters plus durable per-cell state so suspension
# survives restarts.

CELL_STATE_PROVISIONAL = "PROVISIONAL"
CELL_STATE_OBSERVATION = "OBSERVATION"
CELL_STATE_SUSPENDED = "SUSPENDED"
CELL_STATE_PROMOTED = "PROMOTED"
CELL_STATES = (
    CELL_STATE_PROVISIONAL,
    CELL_STATE_OBSERVATION,
    CELL_STATE_SUSPENDED,
    CELL_STATE_PROMOTED,
)

FUNNEL_STAGES = (
    "matched",
    "blocked_by_price_band",
    "blocked_by_evidence",
    "legacy_evidence_labelled",
    "emitted",
    "allocator_rejected",
    "router_rejected",
    "submitted",
    "filled",
)

_state_lock = threading.Lock()
_STATE_CACHE: Optional[Dict[str, Any]] = None
_STATE_CACHE_PATH: Optional[str] = None

_LIFECYCLE_PATH_ENV = "MERID_PROVISIONAL_LIFECYCLE_PATH"


def provisional_daily_max_submissions() -> int:
    return _env_int("MERID_PROVISIONAL_DAILY_MAX_SUBMISSIONS", 20)


def provisional_per_cell_max_submissions() -> int:
    return _env_int("MERID_PROVISIONAL_PER_CELL_MAX_SUBMISSIONS", 5)


def provisional_daily_max_fills_per_cell() -> int:
    return _env_int("MERID_PROVISIONAL_DAILY_MAX_FILLS", 1)


def provisional_daily_max_fills_per_asset() -> int:
    return _env_int("MERID_PROVISIONAL_DAILY_MAX_FILLS_PER_ASSET", 1)


def provisional_daily_max_fills_total() -> int:
    return _env_int("MERID_PROVISIONAL_DAILY_MAX_FILLS_TOTAL", 3)


def provisional_daily_max_fills_side(side: str) -> int:
    """Per-side fill budget.  YES defaults to the stricter measurement cap
    (1/day); NO to the lane total."""
    s = str(side).lower()
    default = 1 if s == "yes" else provisional_daily_max_fills_total()
    return _env_int(f"MERID_PROVISIONAL_DAILY_MAX_FILLS_{s.upper()}", default)


def provisional_max_open_orders_per_cell() -> int:
    return _env_int("MERID_PROVISIONAL_MAX_OPEN_ORDERS", 1)


def provisional_max_open_orders_total() -> int:
    return _env_int("MERID_PROVISIONAL_MAX_OPEN_ORDERS_TOTAL", 1)


def provisional_max_order_lifetime_s() -> int:
    return _env_int("MERID_PROVISIONAL_MAX_ORDER_LIFETIME_S", 45)


def adverse_selection_reserve_enabled() -> bool:
    """Master switch for the measured adverse-selection charge in the EV gate."""
    return _env_flag("MERID_ADV_SEL_RESERVE_ENABLED", True)


def adverse_selection_reserve_cents(
    asset: str,
    side: str,
    price_cents: Optional[float],
    tte_seconds: Optional[float],
) -> float:
    """Expected pick-off cost of a post-only fill at (asset, side, price, tte).

    A resting maker order fills exactly when counterparties cross to it — on
    a fast repricing book that correlates with informed flow.  The realized
    cost is measurable directly: per-fill markouts are already recorded in
    the cell's outcome window in the intent's outcome space, and a negative
    mean short-horizon markout is the observed adverse-selection charge for
    fills in this bucket.

    Estimate = max(floor, min(cap, -mean(markout_5s))) where the sample is
    the resolved cell's recent 5s markouts, widening to the asset+side
    aggregate when the cell has < MERID_ADV_SEL_MIN_SAMPLES.  The bounded
    floor (MERID_ADV_SEL_FLOOR_CENTS, default 0.5c) keeps a nonzero prior on
    cold cells — the 2026-10-01 loss audit showed first-fills are the most
    toxic (-8.5c at 1s on XRP NO@75) precisely because no local evidence
    existed yet.  Capped at MERID_ADV_SEL_CAP_CENTS (default 5c) so one bad
    window cannot veto the whole lane; that authority belongs to the
    suspension rules, not the cost stack.
    """
    if not adverse_selection_reserve_enabled():
        return 0.0
    floor = max(0.0, _env_float("MERID_ADV_SEL_FLOOR_CENTS", 0.5))
    cap = max(floor, _env_float("MERID_ADV_SEL_CAP_CENTS", 5.0))
    min_samples = max(1, _env_int("MERID_ADV_SEL_MIN_SAMPLES", 2))
    try:
        st = _load_state()
    except Exception:
        return floor
    outcomes = st.get("outcomes") or {}

    def _samples(cell_ids: Iterable[str]) -> List[float]:
        vals: List[float] = []
        for cid in cell_ids:
            for o in outcomes.get(cid) or []:
                v = o.get("markout_5s_cents")
                if v is None:
                    v = o.get("markout_1s_cents")
                if v is None:
                    continue
                try:
                    fv = float(v)
                except (TypeError, ValueError):
                    continue
                if math.isfinite(fv):
                    vals.append(fv)
        return vals

    cell = resolve_provisional_cell(asset, side, price_cents, tte_seconds)
    cell_ids = [cell.cell_id] if cell is not None else []
    vals = _samples(cell_ids)
    if len(vals) < min_samples:
        asset_u, side_l = str(asset).upper(), str(side).lower()
        sibling_ids = [
            c.cell_id
            for c in PROVISIONAL_CELLS
            if c.asset == asset_u and c.side == side_l
        ]
        vals = _samples(sibling_ids)
    if not vals:
        return floor
    evidence = max(0.0, -(sum(vals) / len(vals)))
    return min(cap, max(floor, evidence))


def _suspend_min_fills() -> int:
    return _env_int("MERID_PROVISIONAL_SUSPEND_MIN_FILLS", 3)


def _suspend_mean_pnl() -> float:
    return _env_float("MERID_PROVISIONAL_SUSPEND_MEAN_PNL_C", -1.0)


def _suspend_markout_median() -> float:
    return _env_float("MERID_PROVISIONAL_SUSPEND_MARKOUT_MEDIAN_C", -1.0)


def _suspend_reject_rate() -> float:
    return _env_float("MERID_PROVISIONAL_SUSPEND_REJECT_RATE", 0.40)


def _suspend_reject_min() -> int:
    return _env_int("MERID_PROVISIONAL_SUSPEND_REJECT_MIN", 5)


def _suspend_exec_failures() -> int:
    return _env_int("MERID_PROVISIONAL_SUSPEND_EXEC_FAILURES", 2)


def provisional_state_path() -> str:
    return os.environ.get(
        "MERID_PROVISIONAL_STATE_PATH",
        "data/current_build_provisional_lane.json",
    )


def _utc_day(now: float) -> str:
    return datetime.fromtimestamp(now, tz=timezone.utc).date().isoformat()


def _default_state(now: float) -> Dict[str, Any]:
    return {
        "date": _utc_day(now),
        "count": 0,
        "submissions": {},
        "submissions_total": {},
        "fills_today": {},
        "fills_today_asset": {},
        "fills_today_side": {},
        "open_orders": {},
        "router_attempts": {},
        "router_attempts_total": {},
        "router_rejects": {},
        "router_rejects_total": {},
        "router_consecutive_rejects": {},
        "cell_states": {},
        "outcomes": {},
        "decision_cell_map": {},
        "released_reservations": {},
        "review_reported": {},
        "funnel": {s: 0 for s in FUNNEL_STAGES},
        "funnel_by_cell": {},
    }


def _load_state(now: Optional[float] = None, path: Optional[str] = None) -> Dict[str, Any]:
    global _STATE_CACHE, _STATE_CACHE_PATH
    now = time.time() if now is None else float(now)
    p = path or provisional_state_path()
    with _state_lock:
        if _STATE_CACHE is not None and _STATE_CACHE_PATH == p:
            if _STATE_CACHE.get("date") != _utc_day(now):
                _STATE_CACHE["date"] = _utc_day(now)
                _STATE_CACHE["count"] = 0
                _STATE_CACHE["submissions"] = {}
                _STATE_CACHE["fills_today"] = {}
                _STATE_CACHE["fills_today_asset"] = {}
                _STATE_CACHE["fills_today_side"] = {}
                _STATE_CACHE["router_attempts"] = {}
                _STATE_CACHE["router_rejects"] = {}
                _STATE_CACHE["router_consecutive_rejects"] = {}
                _STATE_CACHE["funnel"] = {s: 0 for s in FUNNEL_STAGES}
                _STATE_CACHE["funnel_by_cell"] = {}
                _persist_state_locked(p, _STATE_CACHE)
            return _STATE_CACHE
        rec: Dict[str, Any] = {}
        try:
            with open(p, "r", encoding="utf-8") as f:
                rec = json.load(f)
        except Exception:
            rec = {}
        state = _default_state(now)
        for k in (
            "cell_states", "outcomes", "decision_cell_map",
            "open_orders", "released_reservations",
            # Cumulative evidence counters persist across days — daily caps
            # reset, but promotion/review evidence is build-scoped.
            "submissions_total", "router_attempts_total",
            "router_rejects_total", "review_reported",
        ):
            if isinstance(rec.get(k), dict):
                state[k] = rec[k]
        if rec.get("date") == state["date"]:
            for k in (
                "count", "submissions", "fills_today", "fills_today_asset",
                "fills_today_side", "router_attempts", "router_rejects",
                "router_consecutive_rejects",
            ):
                if isinstance(rec.get(k), (int, dict)):
                    state[k] = rec[k]
            if isinstance(rec.get("funnel"), dict):
                for s in FUNNEL_STAGES:
                    state["funnel"][s] = int(rec["funnel"].get(s) or 0)
            if isinstance(rec.get("funnel_by_cell"), dict):
                state["funnel_by_cell"] = rec["funnel_by_cell"]
        _STATE_CACHE = state
        _STATE_CACHE_PATH = p
        return _STATE_CACHE


def _persist_state_locked(path: str, state: Dict[str, Any]) -> None:
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(json.dumps(state, default=str, separators=(",", ":")))
        os.replace(tmp, path)
    except Exception as exc:
        logger.debug("[CBP] state persist failed: %s", exc)


def _save_state(path: Optional[str] = None) -> None:
    with _state_lock:
        if _STATE_CACHE is not None:
            _persist_state_locked(
                path or _STATE_CACHE_PATH or provisional_state_path(), _STATE_CACHE
            )


def reset_provisional_state_cache() -> None:
    """Test helper: drop the in-memory state cache."""
    global _STATE_CACHE, _STATE_CACHE_PATH
    with _state_lock:
        _STATE_CACHE = None
        _STATE_CACHE_PATH = None


# ---------------------------------------------------------------------------
# Per-cell state machine
# ---------------------------------------------------------------------------

def get_cell_state(cell_id: str) -> str:
    st = _load_state()
    rec = st.get("cell_states", {}).get(cell_id) or {}
    return str(rec.get("state") or CELL_STATE_PROVISIONAL)


def set_cell_state(cell_id: str, state: str, reason: Optional[str] = None) -> None:
    """Explicit state transition; PROMOTED is only reachable through here."""
    state = state.upper()
    if state not in CELL_STATES:
        raise ValueError(f"invalid provisional-cell state {state!r}")
    st = _load_state()
    rec = st["cell_states"].setdefault(cell_id, {})
    rec["state"] = state
    rec["since_ts"] = time.time()
    rec["reason"] = reason
    _save_state()
    logger.info("[CBP-STATE] cell=%s -> %s reason=%s", cell_id, state, reason)
    emit_provisional_lifecycle(
        "state_transition",
        provisional_cell_id=cell_id,
        terminal_state=state,
        reason=reason,
    )


def _suspend_cell(cell_id: str, reason: str) -> None:
    if get_cell_state(cell_id) != CELL_STATE_SUSPENDED:
        logger.warning(
            "[CBP-SUSPEND] cell=%s reason=%s — lane fails closed",
            cell_id, reason,
        )
        set_cell_state(cell_id, CELL_STATE_SUSPENDED, reason)


# ---------------------------------------------------------------------------
# Counters / caps
# ---------------------------------------------------------------------------

def provisional_submissions_today(path: Optional[str] = None, now: Optional[float] = None) -> int:
    st = _load_state(now, path)
    return int(st.get("count") or 0)


def provisional_submissions_today_cell(cell_id: str) -> int:
    st = _load_state()
    return int((st.get("submissions") or {}).get(cell_id) or 0)


def provisional_fills_today(cell_id: str) -> int:
    st = _load_state()
    return int((st.get("fills_today") or {}).get(cell_id) or 0)


def provisional_fills_today_asset(asset: str) -> int:
    st = _load_state()
    return int((st.get("fills_today_asset") or {}).get(str(asset).upper()) or 0)


def provisional_fills_today_side(side: str) -> int:
    st = _load_state()
    return int((st.get("fills_today_side") or {}).get(str(side).lower()) or 0)


def provisional_fills_today_total() -> int:
    st = _load_state()
    return sum(int(v or 0) for v in (st.get("fills_today") or {}).values())


def provisional_open_orders(cell_id: str) -> int:
    st = _load_state()
    return len((st.get("open_orders") or {}).get(cell_id) or [])


def provisional_open_orders_total() -> int:
    st = _load_state()
    return sum(len(v) for v in (st.get("open_orders") or {}).values() if v)


def provisional_cell_admission(cell_id: str) -> Tuple[bool, Optional[str]]:
    """(allowed, block_reason) — all lane admission checks in one place.

    Fail-closed: SUSPENDED or an unknown state blocks; PROMOTED keeps the
    same caps until a separate review widens them.
    """
    if not provisional_enabled():
        return False, "provisional_lane_disabled"
    if provisional_cell_for_id(cell_id) is None:
        return False, "unknown_cell_id"
    state = get_cell_state(cell_id)
    if state == CELL_STATE_SUSPENDED:
        return False, "cell_suspended"
    if state not in CELL_STATES:
        return False, f"cell_state_unknown:{state}"
    if provisional_fills_today(cell_id) >= provisional_daily_max_fills_per_cell():
        return False, "cell_fills_cap_exhausted"
    if provisional_fills_today_total() >= provisional_daily_max_fills_total():
        return False, "lane_fills_total_cap_exhausted"
    cell = provisional_cell_for_id(cell_id)
    if cell is not None:
        if provisional_fills_today_asset(cell.asset) >= provisional_daily_max_fills_per_asset():
            return False, "asset_fills_cap_exhausted"
        if provisional_fills_today_side(cell.side) >= provisional_daily_max_fills_side(cell.side):
            return False, "side_fills_cap_exhausted"
    if provisional_open_orders(cell_id) >= provisional_max_open_orders_per_cell():
        return False, "cell_open_order_exists"
    if provisional_open_orders_total() >= provisional_max_open_orders_total():
        return False, "lane_open_order_exists"
    if provisional_submissions_today_cell(cell_id) >= provisional_per_cell_max_submissions():
        return False, "cell_submissions_cap_exhausted"
    if provisional_submissions_today() >= provisional_daily_max_submissions():
        return False, "cap_exhausted"
    return True, None


def provisional_admission_allowed(
    cell_id: Optional[str],
    evidence_code: Optional[str],
    matching_hard_block: bool,
    net_ev_cents: Optional[float],
    effective_required_edge_cents: Optional[float],
) -> Tuple[bool, Optional[str]]:
    """Provisional-lane admission over ANY legacy evidence verdict.

    Legacy evidence (including hard verdicts like MATCHING_TOXIC_CELL /
    matching_hard_block) is a *label and reserve input*, never a block by
    itself, for a current-build candidate inside the provisional domain whose
    current executable net EV clears the cell threshold while the lane has
    capacity.  Returns ``(allowed, reason)``; ``reason`` is None both when
    allowed and when the candidate simply has no provisional cell.
    """
    if not cell_id:
        return False, None
    cell = provisional_cell_for_id(cell_id)
    if cell is None:
        return False, "unknown_cell_id"
    if not provisional_enabled():
        return False, "provisional_lane_disabled"
    if not provisional_evidence_override_enabled():
        return False, "legacy_override_disabled"
    if net_ev_cents is None or effective_required_edge_cents is None:
        return False, "missing_ev_or_threshold"
    if float(net_ev_cents) < float(effective_required_edge_cents):
        return False, "ev_below_provisional_threshold"
    state = get_cell_state(cell_id)
    if state not in (CELL_STATE_PROVISIONAL, CELL_STATE_OBSERVATION):
        return False, f"cell_state_{state.lower()}"
    allowed, block = provisional_cell_admission(cell_id)
    if not allowed:
        return False, block
    return True, None


# ---------------------------------------------------------------------------
# Recording: submissions, orders, fills, markouts, settlements, violations
# ---------------------------------------------------------------------------

def record_provisional_submission(
    path: Optional[str] = None,
    now: Optional[float] = None,
    cell_id: Optional[str] = None,
    decision_id: Optional[str] = None,
) -> int:
    """Increment today's lane submission counters; returns global count."""
    st = _load_state(now, path)
    st["count"] = int(st.get("count") or 0) + 1
    if cell_id:
        subs = st.setdefault("submissions", {})
        subs[cell_id] = int(subs.get(cell_id) or 0) + 1
        subs_t = st.setdefault("submissions_total", {})
        subs_t[cell_id] = int(subs_t.get(cell_id) or 0) + 1
        if decision_id:
            st.setdefault("decision_cell_map", {})[decision_id] = cell_id
    _save_state(path)
    _maybe_emit_promotion_review(cell_id, st=st)
    return int(st["count"])


def bind_decision_provisional(decision_id: str, cell_id: str) -> None:
    """Persist decision_id -> provisional cell so settlement/exits attribute PnL."""
    if not decision_id or not cell_id:
        return
    st = _load_state()
    st.setdefault("decision_cell_map", {})[decision_id] = cell_id
    _save_state()


def provisional_cell_for_decision(decision_id: str) -> Optional[str]:
    st = _load_state()
    return (st.get("decision_cell_map") or {}).get(decision_id)


def record_provisional_order_open(cell_id: str, order_id: Optional[str]) -> None:
    if not cell_id or not order_id:
        return
    st = _load_state()
    opens = st.setdefault("open_orders", {}).setdefault(cell_id, [])
    if order_id not in opens:
        opens.append(order_id)
    # An accepted order breaks any consecutive router-reject run.
    st.setdefault("router_consecutive_rejects", {})[cell_id] = 0
    _save_state()


def record_provisional_order_closed(cell_id: str, order_id: Optional[str]) -> None:
    if not cell_id or not order_id:
        return
    st = _load_state()
    opens = st.setdefault("open_orders", {}).setdefault(cell_id, [])
    if order_id in opens:
        opens.remove(order_id)
        _save_state()


def record_provisional_router_attempt(cell_id: str) -> None:
    st = _load_state()
    att = st.setdefault("router_attempts", {})
    att[cell_id] = int(att.get(cell_id) or 0) + 1
    att_t = st.setdefault("router_attempts_total", {})
    att_t[cell_id] = int(att_t.get(cell_id) or 0) + 1
    _save_state()


def record_provisional_router_reject(cell_id: str) -> None:
    """Post-only cross/reprice/venue reject; feeds the reject-rate rule and
    the consecutive-reject emergency rule (two in a row -> suspend)."""
    if not cell_id:
        return
    st = _load_state()
    rej = st.setdefault("router_rejects", {})
    rej[cell_id] = int(rej.get(cell_id) or 0) + 1
    rej_t = st.setdefault("router_rejects_total", {})
    rej_t[cell_id] = int(rej_t.get(cell_id) or 0) + 1
    consec = st.setdefault("router_consecutive_rejects", {})
    consec[cell_id] = int(consec.get(cell_id) or 0) + 1
    _save_state()
    bump_provisional_funnel("router_rejected", cell_id)
    _evaluate_suspension(cell_id)


def release_provisional_submission_reservation(
    cell_id: str,
    *,
    intent_id: Optional[str] = None,
    decision_id: Optional[str] = None,
) -> bool:
    """Release the submission slot a provisional candidate reserved at
    emission — a pre-wire drop must not burn scarce lane capacity."""
    if not cell_id:
        return False
    key = intent_id or decision_id
    if not key:
        return False
    st = _load_state()
    released = st.setdefault("released_reservations", {})
    if key in released:
        return False
    released[key] = {"cell_id": cell_id, "ts": time.time()}
    subs = st.setdefault("submissions", {})
    if int(subs.get(cell_id) or 0) > 0:
        subs[cell_id] = int(subs.get(cell_id) or 0) - 1
    subs_t = st.setdefault("submissions_total", {})
    if int(subs_t.get(cell_id) or 0) > 0:
        subs_t[cell_id] = int(subs_t.get(cell_id) or 0) - 1
    if int(st.get("count") or 0) > 0:
        st["count"] = int(st.get("count") or 0) - 1
    _save_state()
    return True


def record_provisional_pre_wire_reject(
    cell_id: str,
    *,
    decision_id: Optional[str] = None,
    intent_id: Optional[str] = None,
    rejection_code: str = "pre_wire_reject",
    stage: str = "pre_wire",
    asset: Optional[str] = None,
    ticker: Optional[str] = None,
) -> None:
    """Terminal accounting for a provisional intent rejected before the wire:
    release the submission reservation AND count toward the reject rule."""
    if not cell_id:
        return
    released = release_provisional_submission_reservation(
        cell_id, intent_id=intent_id, decision_id=decision_id
    )
    record_provisional_router_reject(cell_id)
    code = str(rejection_code or "pre_wire_reject")
    _base = {
        "provisional_cell_id": cell_id,
        "asset": asset,
        "ticker": ticker,
        "decision_id": decision_id,
        "intent_id": intent_id,
        "rejection_code": code.split(":", 1)[0].upper(),
        "rejection_detail": code[:200],
        "exec_stage": stage,
    }
    emit_provisional_lifecycle(
        "router_rejected", submitted=False, terminal_state="router_rejected",
        reservation_released=released, **_base,
    )
    emit_provisional_lifecycle(
        "submission_reservation_released", released=released, **_base,
    )
    emit_provisional_lifecycle("lane_state_updated", **_base)


def record_provisional_exec_failure(cell_id: str, reason: str) -> None:
    """Integrity/execution failure.  > _suspend_exec_failures -> SUSPENDED."""
    if not cell_id:
        return
    st = _load_state()
    outs = st.setdefault("outcomes", {}).setdefault(cell_id, [])
    outs.append({
        "ts": time.time(),
        "kind": "exec_failure",
        "reason": str(reason)[:120],
    })
    _save_state()
    _evaluate_suspension(cell_id)


def record_provisional_fill(
    cell_id: str,
    *,
    decision_id: Optional[str] = None,
    markout_5s_cents: Optional[float] = None,
    fill_ev_cents: Optional[float] = None,
    candidate_ev_cents: Optional[float] = None,
    fill_price_cents: Optional[float] = None,
    limit_price_cents: Optional[float] = None,
    action: Optional[str] = None,
) -> None:
    """Record a live fill for the cell; drives fills/day caps + suspension.

    A fill priced *through* the limit for a buy (or below it for a sell) means
    the post-only order behaved as a taker — a lane-contract breach recorded
    as an immediate-suspension outcome.
    """
    if not cell_id:
        return
    st = _load_state()
    fills = st.setdefault("fills_today", {})
    fills[cell_id] = int(fills.get(cell_id) or 0) + 1
    cell = provisional_cell_for_id(cell_id)
    if cell is not None:
        fa = st.setdefault("fills_today_asset", {})
        fa[cell.asset] = int(fa.get(cell.asset) or 0) + 1
        fs = st.setdefault("fills_today_side", {})
        fs[cell.side] = int(fs.get(cell.side) or 0) + 1
    outs = st.setdefault("outcomes", {}).setdefault(cell_id, [])
    outs.append({
        "ts": time.time(),
        "kind": "fill",
        "decision_id": decision_id,
        "markout_5s_cents": markout_5s_cents,
        "fill_ev_cents": fill_ev_cents,
        "candidate_ev_cents": candidate_ev_cents,
        "fill_price_cents": fill_price_cents,
        "limit_price_cents": limit_price_cents,
    })
    del outs[:-25]
    # Post-only->taker breach: a resting buy can only fill at/below its
    # limit; a resting sell only at/above.  Anything else means the order
    # crossed the spread — a contract breach, not performance.
    if fill_price_cents is not None and limit_price_cents is not None:
        _act = str(action or "buy").lower()
        _breach = (
            float(fill_price_cents) > float(limit_price_cents)
            if _act == "buy"
            else float(fill_price_cents) < float(limit_price_cents)
        )
    else:
        _breach = False
    if _breach:
        outs.append({
            "ts": time.time(),
            "kind": "post_only_breach",
            "decision_id": decision_id,
            "fill_price_cents": fill_price_cents,
            "limit_price_cents": limit_price_cents,
        })
        del outs[:-25]
    if decision_id:
        st.setdefault("decision_cell_map", {})[decision_id] = cell_id
    _save_state()
    bump_provisional_funnel("filled", cell_id)
    if get_cell_state(cell_id) == CELL_STATE_PROVISIONAL:
        set_cell_state(cell_id, CELL_STATE_OBSERVATION, "first_fill")
    _evaluate_suspension(cell_id)
    _maybe_emit_promotion_review(cell_id, st=st)


def record_provisional_markout(
    cell_id: str,
    decision_id: Optional[str],
    horizon_s: int,
    markout_cents: float,
) -> None:
    """Attach a post-fill markout to the cell's rolling outcome window and
    re-evaluate suspension (persistent negative 5s markouts are the primary
    adverse-selection signal for a passive lane)."""
    if not cell_id:
        return
    st = _load_state()
    outs = st.setdefault("outcomes", {}).setdefault(cell_id, [])
    key = f"markout_{horizon_s}s_cents"
    for o in reversed(outs):
        if o.get("decision_id") == decision_id and o.get("kind") in ("fill", "settled"):
            o[key] = float(markout_cents)
            break
    else:
        outs.append({
            "ts": time.time(),
            "kind": "markout",
            "decision_id": decision_id,
            key: float(markout_cents),
        })
        del outs[:-25]
    _save_state()
    if horizon_s == 5:
        _evaluate_suspension(cell_id)


def record_provisional_settlement(
    decision_id: str,
    net_pnl_cents: float,
    cell_id: Optional[str] = None,
) -> None:
    """Attach realized net PnL (exit or settlement join) to a cell's window."""
    cell_id = cell_id or provisional_cell_for_decision(decision_id)
    if not cell_id:
        return
    st = _load_state()
    outs = st.setdefault("outcomes", {}).setdefault(cell_id, [])
    for o in reversed(outs):
        if o.get("decision_id") == decision_id and o.get("kind") == "fill":
            o["net_pnl_cents"] = float(net_pnl_cents)
            o["kind"] = "settled"
            break
    else:
        outs.append({
            "ts": time.time(),
            "kind": "settled",
            "decision_id": decision_id,
            "net_pnl_cents": float(net_pnl_cents),
        })
        del outs[:-25]
    _save_state()
    _evaluate_suspension(cell_id)
    _maybe_emit_promotion_review(cell_id, st=st)


def record_provisional_invariant_violation(cell_id: Optional[str], reason: str) -> None:
    """Immediate suspension: a filled provisional order violated a
    price/side mapping invariant — structural corruption, not performance."""
    if not cell_id:
        return
    logger.warning(
        "[CBP-SUSPEND] cell=%s invariant_violation=%s", cell_id, reason,
    )
    _suspend_cell(cell_id, f"invariant_violation:{str(reason)[:120]}")
    emit_provisional_lifecycle(
        "suspended",
        provisional_cell_id=cell_id,
        terminal_state="SUSPENDED",
        reason=f"invariant_violation:{str(reason)[:120]}",
    )


def _evaluate_suspension(cell_id: str) -> None:
    """Fail-closed lane stop: any breached rule suspends the cell."""
    st = _load_state()
    if get_cell_state(cell_id) in (CELL_STATE_SUSPENDED, CELL_STATE_PROMOTED):
        return
    outs = list((st.get("outcomes") or {}).get(cell_id) or [])
    min_fills = _suspend_min_fills()

    # ── Immediate rules: a newly-live lane cannot wait for the rolling
    # window to discover adverse selection or contract breaches.
    consec = int((st.get("router_consecutive_rejects") or {}).get(cell_id) or 0)
    if consec >= 2:
        _suspend_cell(
            cell_id,
            f"consecutive_router_rejects={consec} (post-only cross/stale "
            "revalidation twice in a row)",
        )
        return

    # Post-only contract breach: the order filled as taker.
    if any(o.get("kind") == "post_only_breach" for o in outs):
        _suspend_cell(cell_id, "post_only_order_became_taker")
        return

    fills = [o for o in outs if o.get("kind") in ("fill", "settled")]
    if fills:
        first = fills[0]
        m5 = first.get("markout_5s_cents")
        if m5 is not None and float(m5) <= -3.0:
            _suspend_cell(
                cell_id,
                f"first_fill_markout_5s={float(m5):+.2f}c <= -3.00c",
            )
            return
        fev = first.get("fill_ev_cents")
        if fev is not None and float(fev) <= 0.0:
            _suspend_cell(cell_id, f"fill_ev_nonpositive={float(fev):+.2f}c")
            return
        pnl = first.get("net_pnl_cents")
        cand = first.get("candidate_ev_cents")
        if pnl is not None and cand is not None:
            bound = -(float(cand) + 2.0)
            if float(pnl) < bound:
                _suspend_cell(
                    cell_id,
                    f"first_trade_pnl={float(pnl):+.2f}c < -(edge {float(cand):+.2f}c + 2c)",
                )
                return
    for o in fills:
        fev = o.get("fill_ev_cents")
        if fev is not None and float(fev) <= 0.0:
            _suspend_cell(cell_id, f"fill_ev_nonpositive={float(fev):+.2f}c")
            return

    # ── Rolling rules (default window: 3 fills).
    net_pnls = [o["net_pnl_cents"] for o in outs if o.get("net_pnl_cents") is not None]
    if len(net_pnls) >= min_fills:
        window = net_pnls[-min_fills:]
        if (sum(window) / len(window)) < _suspend_mean_pnl():
            _suspend_cell(
                cell_id,
                f"rolling_{min_fills}_mean_net_pnl={sum(window)/len(window):+.2f}c < {_suspend_mean_pnl():+.2f}c",
            )
            return

    markouts = [
        o["markout_5s_cents"] for o in outs if o.get("markout_5s_cents") is not None
    ]
    if len(markouts) >= min_fills:
        window = markouts[-min_fills:]
        med = statistics.median(window)
        if med < _suspend_markout_median():
            _suspend_cell(
                cell_id,
                f"rolling_{min_fills}_median_markout_5s={med:+.2f}c < {_suspend_markout_median():+.2f}c",
            )
            return
        # Two-of-N negative 5s markouts: repeated adverse selection.
        if sum(1 for m in window if m < 0.0) >= 2:
            _suspend_cell(
                cell_id,
                f"rolling_{min_fills}_negative_markouts="
                f"{sum(1 for m in window if m < 0.0)}/{len(window)}",
            )
            return

    attempts = int((st.get("router_attempts") or {}).get(cell_id) or 0)
    rejects = int((st.get("router_rejects") or {}).get(cell_id) or 0)
    if attempts >= _suspend_reject_min():
        rate = rejects / float(attempts)
        if rate > _suspend_reject_rate():
            _suspend_cell(
                cell_id,
                f"router_reject_rate={rate:.2f} > {_suspend_reject_rate():.2f} (attempts={attempts})",
            )
            return

    failures = sum(1 for o in outs if o.get("kind") == "exec_failure")
    if failures > _suspend_exec_failures():
        _suspend_cell(cell_id, f"exec_failures={failures} > {_suspend_exec_failures()}")
        return


# ---------------------------------------------------------------------------
# Funnel counters
# ---------------------------------------------------------------------------

def bump_provisional_funnel(stage: str, cell_id: Optional[str] = None) -> None:
    if stage not in FUNNEL_STAGES:
        logger.debug("[CBP] unknown funnel stage %r", stage)
        return
    st = _load_state()
    st["funnel"][stage] = int(st["funnel"].get(stage) or 0) + 1
    if cell_id:
        per = st.setdefault("funnel_by_cell", {}).setdefault(cell_id, {})
        per[stage] = int(per.get(stage) or 0) + 1
    _save_state()


def provisional_funnel_counters() -> Dict[str, Any]:
    st = _load_state()
    return {
        "date": st.get("date"),
        "funnel": dict(st.get("funnel") or {}),
        "funnel_by_cell": dict(st.get("funnel_by_cell") or {}),
        "cell_states": {
            cid: dict(rec) for cid, rec in (st.get("cell_states") or {}).items()
        },
    }


# ---------------------------------------------------------------------------
# Lifecycle event log
# ---------------------------------------------------------------------------

def _lifecycle_path() -> str:
    return os.environ.get(
        _LIFECYCLE_PATH_ENV, "logs/current_build_provisional_lifecycle.jsonl"
    )


def emit_provisional_lifecycle(stage: str, **fields: Any) -> None:
    """Append one correlated lifecycle event to the lane's JSONL log."""
    try:
        rec = {
            "event": "current_build_provisional_lifecycle",
            "stage": stage,
            "lane": LANE_NAME,
            "ts": time.time(),
            "ts_utc": datetime.now(timezone.utc).isoformat(),
        }
        rec.update(fields)
        path = _lifecycle_path()
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, default=str, separators=(",", ":")) + "\n")
    except Exception as exc:
        logger.debug("[CBP] lifecycle emit failed: %s", exc)


# ---------------------------------------------------------------------------
# Heartbeat / status
# ---------------------------------------------------------------------------

def provisional_status_rollup() -> str:
    """One-line all-five status for the parity heartbeat:

        BTC: cells=14 suspended=0 fills_today=0 | ETH: ... |
        lane: fills=0/3 open=0 submissions=0/20 enabled=yes
    """
    st = _load_state()
    parts = []
    for a in ALL_ASSETS:
        ids = CELLS_BY_ASSET.get(a, ())
        n_susp = sum(
            1 for cid in ids if get_cell_state(cid) == CELL_STATE_SUSPENDED
        )
        parts.append(
            f"{a}: cells={len(ids)} suspended={n_susp} "
            f"fills_today={provisional_fills_today_asset(a)}"
        )
    lane = (
        f"lane: fills={provisional_fills_today_total()}/"
        f"{provisional_daily_max_fills_total()} "
        f"yes_fills={provisional_fills_today_side('yes')}/"
        f"{provisional_daily_max_fills_side('yes')} "
        f"no_fills={provisional_fills_today_side('no')}/"
        f"{provisional_daily_max_fills_side('no')} "
        f"open={provisional_open_orders_total()}/"
        f"{provisional_max_open_orders_total()} "
        f"submissions={provisional_submissions_today()}/"
        f"{provisional_daily_max_submissions()} "
        f"enabled={'yes' if provisional_enabled() else 'no'}"
    )
    parts.append(lane)
    return " | ".join(parts)


def provisional_thresholds() -> Dict[str, Dict[str, float]]:
    """Resolved per-asset/per-side provisional min net EV (cents) for audit."""
    return {
        a: {s: provisional_min_ev_cents(a, s) for s in ALL_SIDES}
        for a in ALL_ASSETS
    }


def validate_provisional_domain() -> List[Dict[str, Any]]:
    """Sanity report: every generated cell sits inside the configured domain
    and carries a positive min EV.  Raises AssertionError on any violation —
    a malformed lane must fail closed, never admit."""
    problems: List[str] = []
    report: List[Dict[str, Any]] = []
    pmin, pmax = domain_price_min_cents(), domain_price_max_cents()
    tmin, tmax = domain_tte_min_seconds(), domain_tte_max_seconds()
    for cell in PROVISIONAL_CELLS:
        ok = (
            cell.price_min_cents >= pmin
            and cell.price_max_cents <= pmax
            and cell.tte_min_seconds >= tmin - 1e-9
            and cell.tte_max_seconds <= tmax + 1e-9
            and cell.min_net_ev_cents > 0.0
            and cell.asset in ALL_ASSETS
            and cell.side in ALL_SIDES
        )
        report.append({"cell_id": cell.cell_id, "valid": ok})
        if not ok:
            problems.append(cell.cell_id)
    if problems:
        raise AssertionError(f"provisional cells outside domain/invalid: {problems}")
    return report


# ---------------------------------------------------------------------------
# Promotion review — current-build touchability/markout evidence
# ---------------------------------------------------------------------------

def review_min_attempts() -> int:
    """Passive attempts before a cell's report is promotion-eligible."""
    return _env_int("MERID_PROVISIONAL_REVIEW_MIN_ATTEMPTS", 10)


def review_min_fills() -> int:
    """Minimum live fills before promotion may be considered."""
    return _env_int("MERID_PROVISIONAL_REVIEW_MIN_FILLS", 3)


def promotion_review_report(
    asset: Optional[str] = None,
    side: Optional[str] = None,
    st: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build-specific touchability/markout review per provisional cell.

    A cell is ``promotion_ready`` only when ALL current-build conditions hold:

    * attempts >= ``MERID_PROVISIONAL_REVIEW_MIN_ATTEMPTS`` (default 10),
    * fills >= ``MERID_PROVISIONAL_REVIEW_MIN_FILLS`` (default 3),
    * cell not SUSPENDED,
    * mean realized net PnL >= 0 over observed fills,
    * median 5s markout >= 0 over observed fills,
    * router reject rate <= the suspension ceiling,
    * no post-only contract breach and no invariant violation observed.

    Legacy counterfactual data never feeds this report — promotion is earned
    only by current-build executions.
    """
    st = st if isinstance(st, dict) else _load_state()
    outcomes = st.get("outcomes") or {}
    states = st.get("cell_states") or {}
    # Review evidence is build-scoped, not day-scoped — daily counters reset
    # every UTC day and can never reach the review attempt threshold under
    # the per-cell daily submission cap.  Fall back to the daily maps so a
    # state file written before cumulative counters existed still reports.
    attempts_map = st.get("submissions_total") or st.get("submissions") or {}
    router_att = st.get("router_attempts_total") or st.get("router_attempts") or {}
    router_rej = st.get("router_rejects_total") or st.get("router_rejects") or {}
    cells: List[Dict[str, Any]] = []
    for cell in PROVISIONAL_CELLS:
        if asset and cell.asset != str(asset).upper():
            continue
        if side and cell.side != str(side).lower():
            continue
        outs = [
            o for o in (outcomes.get(cell.cell_id) or [])
            if o.get("kind") in ("fill", "settled")
        ]
        pnls = [float(o["net_pnl_cents"]) for o in outs
                if o.get("net_pnl_cents") is not None]
        m5s = [float(o["markout_5s_cents"]) for o in outs
               if o.get("markout_5s_cents") is not None]
        breaches = sum(
            1 for o in (outcomes.get(cell.cell_id) or [])
            if o.get("kind") == "post_only_breach"
        )
        attempts = int(attempts_map.get(cell.cell_id) or 0)
        att = int(router_att.get(cell.cell_id) or 0)
        rej = int(router_rej.get(cell.cell_id) or 0)
        state = str((states.get(cell.cell_id) or {}).get("state")
                    or CELL_STATE_PROVISIONAL)
        reject_rate = (rej / att) if att else 0.0
        ready = (
            attempts >= review_min_attempts()
            and len(outs) >= review_min_fills()
            and state != CELL_STATE_SUSPENDED
            # Realized PnL evidence must exist for the minimum fill count —
            # "no negative PnL observed" is not the same as "PnL observed".
            and len(pnls) >= review_min_fills()
            and (sum(pnls) / len(pnls)) >= 0.0
            and (not m5s or statistics.median(m5s) >= 0.0)
            and (att == 0 or reject_rate <= _suspend_reject_rate())
            and breaches == 0
        )
        cells.append({
            "cell_id": cell.cell_id,
            "asset": cell.asset,
            "side": cell.side,
            "price_bucket": price_band_label(cell),
            "tte_bucket": tte_band_label(cell),
            "state": state,
            "attempts": attempts,
            "fills": len(outs),
            "fill_rate": (len(outs) / attempts) if attempts else None,
            "mean_net_pnl_cents": (sum(pnls) / len(pnls)) if pnls else None,
            "median_markout_5s_cents": (
                statistics.median(m5s) if m5s else None
            ),
            "router_reject_rate": reject_rate if att else None,
            "post_only_breaches": breaches,
            "promotion_ready": ready,
        })
    return {
        "build_sha": current_build_sha(),
        "model_version": current_model_version(),
        "calibration_version": current_calibration_version(),
        "policy_version": POLICY_VERSION,
        "review_min_attempts": review_min_attempts(),
        "review_min_fills": review_min_fills(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cells": cells,
    }


def _maybe_emit_promotion_review(
    cell_id: Optional[str],
    st: Optional[Dict[str, Any]] = None,
) -> None:
    """Generate the build-specific touchability/markout review once per
    (build, cell) when both review thresholds are first met — attempts AND
    settled fills.  The report is the promotion instrument: it is emitted
    whether or not the cell is ``promotion_ready`` so a failing cell still
    produces a reviewable artifact.  Promotion itself stays an explicit act —
    nothing here widens caps or mutates the registry.

    Callers pass their already-loaded ``st`` so this never re-loads state
    with a different ``now`` — a fresh ``_load_state()`` could trip the
    UTC-day rollover and wipe the very daily counters the caller just wrote.
    """
    if not cell_id:
        return
    try:
        st = st if isinstance(st, dict) else _load_state()
        attempts = int(
            (st.get("submissions_total") or {}).get(cell_id)
            or (st.get("submissions") or {}).get(cell_id) or 0
        )
        outs = (st.get("outcomes") or {}).get(cell_id) or []
        n_fills = sum(
            1 for o in outs if o.get("kind") in ("fill", "settled")
        )
        # Require realized PnL on the minimum fill count — a fill whose
        # settlement join never landed is incomplete evidence, not a pass.
        n_settled = sum(1 for o in outs if o.get("kind") == "settled")
        if (
            attempts < review_min_attempts()
            or n_fills < review_min_fills()
            or n_settled < review_min_fills()
        ):
            return
        reported = st.setdefault("review_reported", {})
        dedupe_key = f"{current_build_sha()}:{cell_id}"
        if dedupe_key in reported:
            return
        reported[dedupe_key] = time.time()
        _save_state()

        cell = _CBP_BY_ID.get(cell_id)
        rep = promotion_review_report(
            asset=cell.asset if cell else None,
            side=cell.side if cell else None,
            st=st,
        )
        row = next(
            (c for c in rep.get("cells") or [] if c.get("cell_id") == cell_id),
            None,
        )
        ready = bool(row and row.get("promotion_ready"))
        record_cb_evidence(
            "promotion_review",
            provisional_cell_id=cell_id,
            promotion_ready=ready,
            report=rep,
        )
        try:
            rpath = os.path.join(
                evidence_dir(), f"promotion_review_{cell_id}.json"
            )
            os.makedirs(os.path.dirname(rpath) or ".", exist_ok=True)
            with open(rpath, "w", encoding="utf-8") as fh:
                fh.write(json.dumps(rep, indent=2, default=str))
        except Exception as exc:
            logger.debug("[CBP-REVIEW] report persist failed: %s", exc)
        emit_provisional_lifecycle(
            "promotion_review",
            provisional_cell_id=cell_id,
            promotion_ready=ready,
            attempts=attempts,
            fills=n_fills,
        )
        logger.info(
            "[CBP-REVIEW] cell=%s promotion_ready=%s attempts=%d fills=%d "
            "report=%s",
            cell_id, ready, attempts, n_fills, rpath,
        )
    except Exception:
        logger.debug(
            "[CBP-REVIEW] report generation failed for %s",
            cell_id, exc_info=True,
        )
