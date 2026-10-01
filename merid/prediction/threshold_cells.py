"""Conditional threshold-cell policy for the 15m Kalshi crypto lane.

A data-driven replacement for the uniform dynamic edge threshold inside the
specific asset x side x price-band x TTE-band cells where the settled
counterfactual frontier (``scripts/_threshold_frontier.py``, ~69.5k deduped
settled candidates, 2026-09) showed the generic gate suppressing cohorts with
positive fill-adjusted LCB net EV.

Semantics
---------
A matching cell's ``min_net_ev_cents`` *replaces* the base+convexity+FLB
formula output for that side — the cell is the single source of truth for the
required edge inside its region (the formula decomposition is still emitted in
telemetry for audit).  No cell applies below a 20c ask or to the YES side, and
no cell relaxes any other gate: the held-price floor, tail guards, evidence
policy, depth requirement, confidence gate, pi* cost basis, TTE entry cutoff,
and the downstream authoritative EV gate all still apply unchanged.

Bounds are inclusive on TTE (``120 <= tte <= 600``) and half-open on price
(``price_min <= ask < price_max``), matching the frontier bucketing.

Routing
-------
A decision whose selected side was admitted by a cell is stamped
``decision_lane = "threshold_cell"`` (and ``threshold_cell_id``), which the
agent-grid order-style block forces to a one-contract post-only maker order —
the same bounded treatment as the evidence escape lane.

Per-cell lane state machine
---------------------------
Each cell carries a persistent lane state in ``data/threshold_cell_lane.json``:

    PROVISIONAL -> OBSERVATION -> SUSPENDED -> (manual review)
                   OBSERVATION -> PROMOTED (manual only)

- PROVISIONAL: default; one contract, post-only, strict caps.
- OBSERVATION: reached after the first recorded fill; identical admission
  policy — the label marks that live execution data exists for the cell.
- SUSPENDED: fail-closed — the cell stops admitting until an operator resets
  it (``set_cell_state(cell_id, "PROVISIONAL")``).
- PROMOTED: manual promotion only; admission policy unchanged until a
  separate review widens it.

Automatic suspension (evaluated on every recorded fill / router reject):
  - pre-five emergency rules: 5s markout <= -3c on the first fill, first
    settled trade losing more than candidate EV + 2c stress, nonpositive
    fill-time EV, two consecutive router rejects, or a price/side mapping
    invariant violation (``record_cell_invariant_violation``, immediate);
  - rolling ``MERID_THRESHOLD_CELL_SUSPEND_MIN_FILLS`` (default 5) filled
    trades: mean realized net PnL < ``_SUSPEND_MEAN_PNL`` (default -1c);
  - rolling 5 fills with a 5s markout: median markout_5s <
    ``_SUSPEND_MARKOUT_MEDIAN`` (default -1c);
  - router reject/cross rate > ``_SUSPEND_REJECT_RATE`` (default 0.40) once the
    cell has ``_SUSPEND_REJECT_MIN`` (default 5) attempts;
  - mean (fill_time EV - candidate EV) < ``_SUSPEND_EV_DROP`` (default -1.5c)
    over the rolling window — passive fills landing materially worse than the
    price the decision economics assumed;
  - more than ``_SUSPEND_EXEC_FAILURES`` (default 2) execution/integrity
    failures recorded for the cell.

Caps (all independent):
  - ``MERID_THRESHOLD_CELL_PER_CELL_MAX_SUBMISSIONS`` (default 5): candidate
    submissions per cell per UTC day.
  - ``MERID_THRESHOLD_CELL_DAILY_MAX_SUBMISSIONS`` (default 15): global lane
    submissions/day.  ``MERID_THRESHOLD_CELL_DAILY_MAX`` remains as a legacy
    alias.
  - ``MERID_THRESHOLD_CELL_DAILY_MAX_FILLS`` (default 2): filled trades per
    cell per UTC day — fills, not submissions, are the exposure.
  - ``MERID_THRESHOLD_CELL_DAILY_MAX_FILLS_TOTAL`` (default 3): lane-wide
    fills/day across all cells.
  - ``MERID_THRESHOLD_CELL_MAX_OPEN_ORDERS`` (default 1): resting orders per
    cell, tracked via the fill-quality tracker.

Funnel counters
---------------
``bump_cell_funnel(stage, cell_id=None)`` counts per-day stage transitions:
matched, blocked_by_price_band, blocked_by_evidence, emitted,
allocator_rejected, router_rejected, submitted, filled.  Invariant for audit:
``matched > 0`` with ``emitted == 0`` means a hidden gate is silently
suppressing admitted cells.  Counters persist in the lane state file and are
emitted on every lifecycle event.

Lifecycle event log
-------------------
``emit_cell_lifecycle(stage, **fields)`` appends one JSONL record per stage to
``logs/threshold_cell_lifecycle.jsonl`` carrying the full correlation chain
(decision_id, candidate_id, intent_id, client_order_id, order_id,
position_id, threshold_cell_id) so a single candidate can be traced from
decision through settlement.

Kill switch: ``MERID_THRESHOLD_CELLS=0`` reverts to the legacy formula
everywhere without a deploy.
"""

from __future__ import annotations

import json
import logging
import os
import statistics
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, NamedTuple, Optional, Tuple

logger = logging.getLogger(__name__)


class ThresholdCell(NamedTuple):
    """One empirically-qualified admission cell.

    Price bounds are half-open (``price_min_cents <= ask < price_max_cents``);
    TTE bounds are inclusive (``tte_min_seconds <= tte <= tte_max_seconds``),
    matching the approved ``120 <= tte <= 600`` contract.
    """

    cell_id: str
    asset: str
    side: str  # "yes" | "no"
    price_min_cents: int
    price_max_cents: int
    tte_min_seconds: float
    tte_max_seconds: float
    min_net_ev_cents: float
    evidence: str  # provenance note for audit
    # Historical counterfactual LCB10 (net c/contract at the executable ask)
    # from the settled frontier study — prior evidence only, never mixed into
    # the live-fill evidence store.  Emitted on sparse-override records.
    historical_lcb10_cents: float = 0.0


# Approved 2026-09-30 from the settled counterfactual frontier.  LCB10 = the
# ~10% lower confidence bound on mean net c/contract at the decision-time
# executable ask (taker-fee counterfactual — conservative vs post-only).
#
# The live registry is data, not code: rows are read from
# ``config/threshold_cells_live.yaml`` (override:
# ``MERID_THRESHOLD_CELLS_CONFIG``).  Cells reach that file only through the
# promotion pipeline — discovery report -> promotion compiler -> explicit
# approval manifest.  If the file is absent, the built-in fallback below is
# used (identical to the checked-in registry).  If the file is present but
# malformed, the registry loads EMPTY — no cell can admit, every candidate
# falls back to the formula path (fail-closed, never fail-open).

def _builtin_cells() -> List[ThresholdCell]:
    """Fallback registry — must mirror config/threshold_cells_live.yaml."""
    return [
        ThresholdCell(
            "sol_no_30_60_t120_600", "SOL", "no", 30, 60, 120.0, 600.0, 1.5,
            "frontier: SOL-NO 30-59c LCB10 +8.8..+14.7c; TTE120-300 LCB +14.1c",
            8.8,
        ),
        ThresholdCell(
            "sol_no_60_80_t120_600", "SOL", "no", 60, 80, 120.0, 600.0, 2.5,
            "frontier: SOL-NO 70-79c LCB +2.7c; 60-69c weak -> higher bar",
            2.7,
        ),
        ThresholdCell(
            "doge_no_20_30_t120_600", "DOGE", "no", 20, 30, 120.0, 600.0, 2.0,
            "frontier: DOGE-NO 20-29c LCB +1.6c (held floor still applies <25c)",
            1.6,
        ),
        ThresholdCell(
            "doge_no_40_50_t120_600", "DOGE", "no", 40, 50, 120.0, 600.0, 2.0,
            "frontier: DOGE-NO 40-49c LCB +2.4c",
            2.4,
        ),
        ThresholdCell(
            "doge_no_70_90_t120_600", "DOGE", "no", 70, 90, 120.0, 600.0, 3.0,
            "frontier: DOGE-NO 70-89c LCB +6.2..+21.5c",
            6.2,
        ),
        ThresholdCell(
            "xrp_no_30_40_t120_600", "XRP", "no", 30, 40, 120.0, 600.0, 2.5,
            "frontier: XRP-NO 30-39c LCB +3.7c",
            3.7,
        ),
        ThresholdCell(
            "xrp_no_80_90_t120_600", "XRP", "no", 80, 90, 120.0, 600.0, 2.5,
            "frontier: XRP-NO 80-89c LCB +2.2c",
            2.2,
        ),
        # 2026-09-30 batch 1: BTC/ETH PROVISIONAL measurement cells.
        ThresholdCell(
            "btc_no_30_40_t120_300", "BTC", "no", 30, 40, 120.0, 300.0, 2.5,
            "discovery20260930: BTC-NO 30-39c t120-300 n=85 mkts=72 LCB10 +5.23c",
            5.23,
        ),
        ThresholdCell(
            "btc_no_40_50_t120_300", "BTC", "no", 40, 50, 120.0, 300.0, 2.5,
            "discovery20260930: BTC-NO 40-49c t120-300 n=71 mkts=59 LCB10 +5.39c",
            5.39,
        ),
        ThresholdCell(
            "btc_no_50_60_t120_300", "BTC", "no", 50, 60, 120.0, 300.0, 3.0,
            "discovery20260930: BTC-NO 50-59c t120-300 n=70 mkts=62 LCB10 +4.19c",
            4.19,
        ),
        ThresholdCell(
            "eth_no_50_60_t120_300", "ETH", "no", 50, 60, 120.0, 300.0, 2.5,
            "discovery20260930: ETH-NO 50-59c t120-300 n=65 mkts=55 LCB10 +5.84c",
            5.84,
        ),
        ThresholdCell(
            "eth_no_60_70_t120_300", "ETH", "no", 60, 70, 120.0, 300.0, 3.0,
            "discovery20260930: ETH-NO 60-69c t120-300 n=76 mkts=69 LCB10 +3.98c",
            3.98,
        ),
    ]


# ---------------------------------------------------------------------------
# Five-asset registry (2026-09-30)
# ---------------------------------------------------------------------------
# Every first-class 15m asset is listed, even when it has zero enabled cells.
# An empty tuple means "no historically qualified cell currently exists —
# evaluate through the shared formula path and keep emitting discovery
# telemetry", never "do not evaluate this asset".  Cells are enabled by
# asset x side x price x TTE data, not by asset-level branches.
ALL_ASSETS: Tuple[str, ...] = ("BTC", "ETH", "SOL", "XRP", "DOGE")

_REGISTRY_REQUIRED_KEYS = (
    "cell_id", "asset", "side",
    "price_min_cents", "price_max_cents",
    "tte_min_seconds", "tte_max_seconds",
    "min_net_ev_cents",
)


def _registry_config_path() -> str:
    override = os.environ.get("MERID_THRESHOLD_CELLS_CONFIG")
    if override:
        return os.path.abspath(override)
    # merid/prediction/threshold_cells.py -> repo root/config/...
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))),
        "config", "threshold_cells_live.yaml",
    )


def _load_registry_from_config(path: str) -> Optional[List[ThresholdCell]]:
    """Parse a live-registry yaml.  Returns None if the file does not exist
    (caller falls back to built-in); returns a list — possibly EMPTY — for a
    present file.  Any malformed row empties the whole registry
    (fail-closed)."""
    if not os.path.exists(path):
        return None
    try:
        import yaml  # local import: threshold_cells is on the live hot path
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception as exc:
        logger.critical(
            "[THRESHOLD-CELL-REGISTRY] config %s unreadable (%s) -> EMPTY registry",
            path, exc,
        )
        return []
    rows = data.get("cells")
    if not isinstance(rows, list):
        logger.critical(
            "[THRESHOLD-CELL-REGISTRY] config %s missing cells list -> EMPTY registry",
            path,
        )
        return []
    cells: List[ThresholdCell] = []
    for row in rows:
        try:
            if not isinstance(row, dict) or any(
                k not in row for k in _REGISTRY_REQUIRED_KEYS
            ):
                raise ValueError(f"missing required keys: {row!r}")
            asset = str(row["asset"]).upper()
            side = str(row["side"]).lower()
            pmin = int(row["price_min_cents"])
            pmax = int(row["price_max_cents"])
            tlo = float(row["tte_min_seconds"])
            thi = float(row["tte_max_seconds"])
            cell_id = str(row["cell_id"])
            if asset not in ALL_ASSETS:
                raise ValueError(f"unknown asset {asset!r}")
            if side not in ("yes", "no"):
                raise ValueError(f"bad side {side!r}")
            if not (0 <= pmin < pmax <= 100 and 0 <= tlo < thi):
                raise ValueError(f"bad bounds px={pmin}-{pmax} tte={tlo}-{thi}")
            expected_id = (
                f"{asset.lower()}_{side}_{pmin}_{pmax}"
                f"_t{int(tlo)}_{int(thi)}"
            )
            if cell_id != expected_id:
                raise ValueError(
                    f"cell_id {cell_id!r} != canonical {expected_id!r}"
                )
            cells.append(ThresholdCell(
                cell_id=cell_id,
                asset=asset,
                side=side,
                price_min_cents=pmin,
                price_max_cents=pmax,
                tte_min_seconds=tlo,
                tte_max_seconds=thi,
                min_net_ev_cents=float(row["min_net_ev_cents"]),
                evidence=str(row.get("evidence") or ""),
                historical_lcb10_cents=float(
                    row.get("historical_lcb10_cents") or 0.0
                ),
            ))
        except Exception as exc:
            logger.critical(
                "[THRESHOLD-CELL-REGISTRY] malformed cell row in %s (%s) "
                "-> EMPTY registry",
                path, exc,
            )
            return []
    return cells


def _load_registry() -> Tuple[List[ThresholdCell], str]:
    path = _registry_config_path()
    loaded = _load_registry_from_config(path)
    if loaded is None:
        return _builtin_cells(), "builtin_fallback"
    return loaded, f"config:{os.path.basename(path)}"


THRESHOLD_CELLS, REGISTRY_SOURCE = _load_registry()

_CELLS_BY_ID: Dict[str, ThresholdCell] = {c.cell_id: c for c in THRESHOLD_CELLS}

CELLS_BY_ASSET: Dict[str, Tuple[str, ...]] = {
    a: tuple(c.cell_id for c in THRESHOLD_CELLS if c.asset == a)
    for a in ALL_ASSETS
}
assert {
    cid for ids in CELLS_BY_ASSET.values() for cid in ids
} == {c.cell_id for c in THRESHOLD_CELLS}, "CELLS_BY_ASSET must mirror THRESHOLD_CELLS"


def cells_for_asset(asset: str) -> Tuple[str, ...]:

    """Enabled cell ids for an asset (empty -> formula path, still evaluated)."""
    return CELLS_BY_ASSET.get(str(asset).upper(), ())


_DISCOVERY_ARTIFACT_ENV = "MERID_CELL_DISCOVERY_PATH"
_DISCOVERY_ARTIFACT_DEFAULT = "data/cell_discovery.json"

# Discovery artifact cache: (abs_path, mtime_ns, per_asset payload).
# Reloaded only when the file changes so the per-cycle parity heartbeat
# performs at most one stat call per cycle.
_discovery_cache: Dict[str, Any] = {"path": None, "mtime_ns": None, "per_asset": {}}


def _load_discovery_artifact() -> Dict[str, Any]:
    """mtime-cached reader for data/cell_discovery.json.

    Written by scripts/cell_discovery_report.py; a missing or stale artifact
    must never raise into the live loop — absence is itself a status.
    """
    path = os.path.abspath(
        os.environ.get(_DISCOVERY_ARTIFACT_ENV, _DISCOVERY_ARTIFACT_DEFAULT)
    )
    try:
        mtime = os.stat(path).st_mtime_ns
    except OSError:
        _discovery_cache.update(path=path, mtime_ns=None, per_asset={})
        return {}
    if _discovery_cache["path"] == path and _discovery_cache["mtime_ns"] == mtime:
        return _discovery_cache["per_asset"]
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        per_asset = payload.get("per_asset") or {}
        if not isinstance(per_asset, dict):
            per_asset = {}
    except Exception:
        per_asset = {}
    _discovery_cache.update(path=path, mtime_ns=mtime, per_asset=per_asset)
    return per_asset


def cell_discovery_status(asset: str) -> str:
    """Uniform discovery-state label for the parity heartbeat.

    Resolves, for every asset in the universe, why it is or is not on the
    cell path so 'evaluated but not qualified' can never be confused with
    'silently excluded'.  Statuses come from the same promotion rule the
    discovery report applies to all five assets:

      qualified:N_cells          - approved cells exist in the registry
      INSUFFICIENT_SAMPLE        - every bucket below n_min
      INSUFFICIENT_POSITIVE_LCB  - best bucket's LCB10 <= 0
      FAILS_+1C_STRESS           - LCB10 > 0 but fails +1c adverse stress
      FOLD_INSTABILITY           - passes stats but chronological folds
                                   disagree
      no_discovery_data          - asset absent from the report artifact
      no_discovery_artifact      - report has never been run
      registry_disabled          - MERID_THRESHOLD_CELLS=0 kill switch
    """
    if not threshold_cells_enabled():
        return "registry_disabled"
    asset_u = str(asset).upper()
    n_cells = len(CELLS_BY_ASSET.get(asset_u, ()))
    if n_cells:
        return f"qualified:{n_cells}_cells"
    per_asset = _load_discovery_artifact()
    if not per_asset:
        return "no_discovery_artifact" if not _discovery_cache["mtime_ns"] else "no_discovery_data"
    rec = per_asset.get(asset_u)
    if not rec:
        return "no_discovery_data"
    return str(rec.get("status") or "no_qualified_cells")


_CANDIDATES_ARTIFACT_ENV = "MERID_CELL_CANDIDATES_PATH"
_CANDIDATES_ARTIFACT_DEFAULT = "data/threshold_cell_candidates.json"
_candidates_cache: Dict[str, Any] = {"path": None, "mtime_ns": None, "rows": []}


def _load_candidates_artifact() -> List[Dict[str, Any]]:
    """mtime-cached reader for data/threshold_cell_candidates.json."""
    path = os.path.abspath(
        os.environ.get(_CANDIDATES_ARTIFACT_ENV, _CANDIDATES_ARTIFACT_DEFAULT)
    )
    try:
        mtime = os.stat(path).st_mtime_ns
    except OSError:
        _candidates_cache.update(path=path, mtime_ns=None, rows=[])
        return []
    if _candidates_cache["path"] == path and _candidates_cache["mtime_ns"] == mtime:
        return _candidates_cache["rows"]
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        rows = payload.get("per_cell") or []
        if not isinstance(rows, list):
            rows = []
    except Exception:
        rows = []
    _candidates_cache.update(path=path, mtime_ns=mtime, rows=rows)
    return rows


def cell_discovery_detail(asset: str) -> Dict[str, Any]:
    """Heartbeat detail for one asset — answers 'why is a qualifying
    discovery cell not live?' with the exact pipeline position:

      {status, top_candidate, promotion_status, live_registry}
    """
    asset_u = str(asset).upper()
    live = list(CELLS_BY_ASSET.get(asset_u, ()))
    detail = {
        "status": cell_discovery_status(asset_u),
        "live_registry": len(live),
        "top_candidate": None,
        "promotion_status": None,
    }
    # Best promotion-pipeline row for the asset (highest LCB10).
    best = None
    for row in _load_candidates_artifact():
        if str(row.get("asset", "")).upper() != asset_u:
            continue
        if best is None or (row.get("lcb10_cents") or -1e9) > (
            best.get("lcb10_cents") or -1e9
        ):
            best = row
    if best is not None:
        detail["top_candidate"] = best.get("cell_key")
        detail["promotion_status"] = best.get("promotion_status")
        return detail
    # No candidate row: check whether the asset's top IN-DOMAIN discovery
    # bucket was REJECTED by the compiler before reporting it as merely
    # uncompiled.  S2_domain rejections are expected tail-bucket vetoes —
    # they are never the asset's best candidate.
    rej_best = None
    for row in _load_rejections_artifact():
        if str(row.get("asset", "")).upper() != asset_u:
            continue
        if str(row.get("failed_stage")) == "S2_domain":
            continue
        if rej_best is None or (row.get("lcb10_cents") or -1e9) > (
            rej_best.get("lcb10_cents") or -1e9
        ):
            rej_best = row
    if rej_best is not None:
        detail["top_candidate"] = rej_best.get("cell_key")
        detail["promotion_status"] = (
            f"REJECTED@{rej_best.get('failed_stage') or 'unknown'}"
        )
        return detail
    # Fall back to the discovery artifact's top candidate.
    rec = _load_discovery_artifact().get(asset_u) or {}
    if rec.get("top_candidate"):
        detail["top_candidate"] = rec["top_candidate"]
        detail["promotion_status"] = "NOT_COMPILED"
    return detail


_REJECTIONS_ARTIFACT_ENV = "MERID_CELL_REJECTIONS_PATH"
_REJECTIONS_ARTIFACT_DEFAULT = "data/threshold_cell_rejections.json"
_rejections_cache: Dict[str, Any] = {"path": None, "mtime_ns": None, "rows": []}


def _load_rejections_artifact() -> List[Dict[str, Any]]:
    """mtime-cached reader for data/threshold_cell_rejections.json."""
    path = os.path.abspath(
        os.environ.get(_REJECTIONS_ARTIFACT_ENV, _REJECTIONS_ARTIFACT_DEFAULT)
    )
    try:
        mtime = os.stat(path).st_mtime_ns
    except OSError:
        _rejections_cache.update(path=path, mtime_ns=None, rows=[])
        return []
    if _rejections_cache["path"] == path and _rejections_cache["mtime_ns"] == mtime:
        return _rejections_cache["rows"]
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        rows = payload.get("per_cell") or []
        if not isinstance(rows, list):
            rows = []
    except Exception:
        rows = []
    _rejections_cache.update(path=path, mtime_ns=mtime, rows=rows)
    return rows


_ASSETS_UNIVERSE = ("BTC", "ETH", "SOL", "XRP", "DOGE")


def promotion_status_rollup() -> str:
    """One-line all-five promotion status — answers 'why is asset X not
    trading?' from the promotion artifacts plus the live registry:

        BTC: live=3 live_provisional=3 candidates=1 pending_feasibility=1
             rejected_domain=38 rejected_stats=19 rejected_concentration=0
             rejected_execution=0 suspended=0 | ETH: ...

    Absence of artifacts is explicit ('no_compiler_artifact') — never an
    error in the live loop.
    """
    cand = _load_candidates_artifact()
    rej = _load_rejections_artifact()
    by_asset: Dict[str, Any] = {a: defaultdict(int) for a in _ASSETS_UNIVERSE}
    for row in cand:
        a = str(row.get("asset", "")).upper()
        if a not in by_asset:
            continue
        by_asset[a]["candidates"] += 1
        st = str(row.get("promotion_status") or "")
        if st == "CANDIDATE_PENDING_EXECUTION_FEASIBILITY":
            by_asset[a]["pending_feasibility"] += 1
        elif st == "CANDIDATE_PENDING_RECENCY_AND_CALIBRATION":
            by_asset[a]["pending_recency"] += 1
        elif st == "CANDIDATE_READY_FOR_APPROVAL":
            by_asset[a]["ready_for_approval"] += 1
        elif st == "LIVE_PROVISIONAL":
            by_asset[a]["live_provisional"] += 1
        elif st == "APPROVED":
            by_asset[a]["approved"] += 1
    for row in rej:
        a = str(row.get("asset", "")).upper()
        if a not in by_asset:
            continue
        fs = str(row.get("failed_stage") or "")
        if fs == "S2_domain":
            by_asset[a]["rejected_domain"] += 1
        elif fs == "S1b_market_concentration":
            by_asset[a]["rejected_concentration"] += 1
        elif fs == "S3_execution_feasibility":
            by_asset[a]["rejected_execution"] += 1
        else:
            by_asset[a]["rejected_stats"] += 1
    parts = []
    for a in _ASSETS_UNIVERSE:
        c = by_asset[a]
        live = CELLS_BY_ASSET.get(a, ())
        n_susp = sum(
            1 for cid in live
            if get_cell_state(cid) == CELL_STATE_SUSPENDED
        )
        if not cand and not rej:
            parts.append(f"{a}: live={len(live)} no_compiler_artifact")
            continue
        parts.append(
            f"{a}: live={len(live)} suspended={n_susp} "
            f"candidates={c['candidates']} approved={c['approved']} "
            f"live_provisional={c['live_provisional']} "
            f"pending_feasibility={c['pending_feasibility']} "
            f"pending_recency={c['pending_recency']} "
            f"ready_for_approval={c['ready_for_approval']} "
            f"rejected_domain={c['rejected_domain']} "
            f"rejected_concentration={c['rejected_concentration']} "
            f"rejected_execution={c['rejected_execution']} "
            f"rejected_stats={c['rejected_stats']}"
        )
    return " | ".join(parts)


# Soft evidence codes the threshold-cell lane may override under its own
# caps/suspension state.  These are uncertainty or generic-budget verdicts,
# never adverse matched evidence:
#   SPARSE_MATCHED_INSUFFICIENT - no adequately-sampled price-matched cell.
#   SOFT_PENALTY_INSUFFICIENT   - matched LCB short, no contradiction.
#   CHALLENGE_INSUFFICIENT      - recent outcomes contradict prior but the
#                                 model edge did not clear the challenge
#                                 margin on its own.
#   ESCAPE_CAP_EXHAUSTED        - candidate cleared the uncertainty reserve
#                                 but the *generic* escape-lane daily budget
#                                 (shared with non-cell trades) is spent.
#   CHALLENGE_CAP_EXHAUSTED     - same generic escape budget reached via the
#                                 challenge path.
# Hard verdicts — MATCHING_TOXIC_CELL, CELL_EVIDENCE_INSUFFICIENT (matched,
# adequately-sampled adverse posterior), EVIDENCE_*_INSUFFICIENT without
# cells, *_LANE_DISABLED (deliberate config), and matching_hard_block=True —
# are never bypassable.
SOFT_EVIDENCE_CODES = frozenset({
    "SPARSE_MATCHED_INSUFFICIENT",
    "SOFT_PENALTY_INSUFFICIENT",
    "CHALLENGE_INSUFFICIENT",
    "ESCAPE_CAP_EXHAUSTED",
    "CHALLENGE_CAP_EXHAUSTED",
})


def threshold_cells_enabled() -> bool:
    """Single kill switch: ``MERID_THRESHOLD_CELLS=0`` reverts to formula."""
    return os.environ.get("MERID_THRESHOLD_CELLS", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def threshold_cell_maker_enabled() -> bool:
    """Lane-scoped post-only switch.

    ``MERID_ENTRY_MAKER_ENABLED`` stays off globally; this lane is an explicit
    instrumented post-only experiment.  ``MERID_THRESHOLD_CELL_MAKER=0``
    suppresses threshold-cell candidates entirely rather than coercing them to
    taker — a taker entry under cell economics is not the approved lane.
    """
    return os.environ.get("MERID_THRESHOLD_CELL_MAKER", "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def resolve_threshold_cell(
    asset: str,
    side: str,
    price_cents: float,
    tte_seconds: Optional[float],
) -> Optional[ThresholdCell]:
    """Return the most specific matching cell, or None -> legacy formula.

    Specificity = narrower price span wins, so a future override cell can
    tighten a band inside a broader qualified cell without reordering the
    table.  TTE bounds are inclusive; price bounds are half-open.
    """
    if tte_seconds is None or not threshold_cells_enabled():
        return None
    asset_u = asset.upper()
    side_l = side.lower()
    px = float(price_cents)
    tte = float(tte_seconds)
    best: Optional[ThresholdCell] = None
    for cell in THRESHOLD_CELLS:
        if cell.asset != asset_u or cell.side != side_l:
            continue
        if not (cell.price_min_cents <= px < cell.price_max_cents):
            continue
        if not (cell.tte_min_seconds <= tte <= cell.tte_max_seconds):
            continue
        if best is None or (
            cell.price_max_cents - cell.price_min_cents
            < best.price_max_cents - best.price_min_cents
        ):
            best = cell
    return best


def cell_region_registered(
    asset: str,
    side: str,
    price_cents: Optional[float],
    tte_seconds: Optional[float],
) -> bool:
    """True when *any* configured cell covers the point — regardless of the
    lane enabled flag or per-cell state.  Used by other lanes (the
    current-build provisional lane) so a disabled or suspended registered
    cell keeps sole authority over its band instead of silently releasing
    it to a different admission path.
    """
    if price_cents is None or tte_seconds is None:
        return False
    asset_u, side_l = asset.upper(), side.lower()
    px, tte = float(price_cents), float(tte_seconds)
    for cell in THRESHOLD_CELLS:
        if cell.asset != asset_u or cell.side != side_l:
            continue
        if cell.price_min_cents <= px < cell.price_max_cents and (
            cell.tte_min_seconds <= tte <= cell.tte_max_seconds
        ):
            return True
    return False


def explain_cell_miss(
    asset: str,
    side: str,
    price_cents: float,
    tte_seconds: Optional[float],
) -> Optional[str]:
    """Explain why no cell matched, or None when a cell would match.

    Only meaningful when the (asset, side) pair has configured cells —
    ``no_cells_for_asset_side`` is returned for pairs with none.  Explicit
    reasons keep near-boundary misses auditable instead of silently falling
    back to the generic formula.
    """
    asset_u = asset.upper()
    side_l = side.lower()
    candidates = [
        c for c in THRESHOLD_CELLS if c.asset == asset_u and c.side == side_l
    ]
    if not candidates:
        return "no_cells_for_asset_side"
    if not threshold_cells_enabled():
        return "threshold_cells_disabled"
    if tte_seconds is None:
        return "threshold_cell_tte_unknown"
    if price_cents is None:
        return "threshold_cell_price_unknown"
    # A real match is not a miss — resolve first so a covered point never
    # reports a spurious "unqualified gap" reason.
    if resolve_threshold_cell(asset_u, side_l, price_cents, tte_seconds) is not None:
        return None
    tte = float(tte_seconds)
    px = float(price_cents)
    lo_tte = min(c.tte_min_seconds for c in candidates)
    hi_tte = max(c.tte_max_seconds for c in candidates)
    if tte < lo_tte:
        return "threshold_cell_tte_below_min"
    if tte > hi_tte:
        return "threshold_cell_tte_above_max"
    lo_px = min(c.price_min_cents for c in candidates)
    hi_px = max(c.price_max_cents for c in candidates)
    if px < lo_px:
        return "threshold_cell_price_below_min"
    if px >= hi_px:
        return "threshold_cell_price_above_max"
    return "threshold_cell_price_in_unqualified_gap"


# ---------------------------------------------------------------------------
# Lane state file: caps, per-cell state machine, outcomes, funnel counters
# ---------------------------------------------------------------------------
# ``data/threshold_cell_lane.json`` carries a daily-scoped counter block plus
# durable per-cell state that survives restarts (suspension must not reset on
# redeploy).  Shape:
#   {
#     "date": "YYYY-MM-DD",                  # UTC day the counters belong to
#     "count": n,                            # legacy global submissions today
#     "submissions": {cell_id: n},
#     "fills_today": {cell_id: n},
#     "open_orders": {cell_id: [order_id]},
#     "router_attempts": {cell_id: n},
#     "router_rejects": {cell_id: n},
#     "cell_states": {cell_id: {"state": ..., "since_ts": ..., "reason": ...}},
#     "outcomes": {cell_id: [ {ts, net_pnl_cents, markout_5s_cents,
#                             fill_ev_cents, candidate_ev_cents,
#                             decision_id, kind} , ... ]},   # capped at 25
#     "decision_cell_map": {decision_id: cell_id},
#     "funnel": {stage: n, "by_cell": {cell_id: {stage: n}}},
#   }

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
    "soft_evidence_override",
    "emitted",
    "allocator_rejected",
    "router_rejected",
    "submitted",
    "filled",
)

_state_lock = threading.Lock()
_STATE_CACHE: Optional[Dict[str, Any]] = None
_STATE_CACHE_PATH: Optional[str] = None

_LIFECYCLE_PATH_ENV = "MERID_THRESHOLD_CELL_LIFECYCLE_PATH"


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except Exception:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except Exception:
        return default


def cell_daily_max() -> int:
    """Global lane submissions/day (legacy alias honored)."""
    v = os.environ.get("MERID_THRESHOLD_CELL_DAILY_MAX_SUBMISSIONS")
    if v is None:
        v = os.environ.get("MERID_THRESHOLD_CELL_DAILY_MAX", "15")
    try:
        return int(v)
    except Exception:
        return 15


def cell_daily_max_submissions_per_cell() -> int:
    """Per-cell candidate submissions/day — one cell must not consume the
    lane's whole exploration budget."""
    return _env_int("MERID_THRESHOLD_CELL_PER_CELL_MAX_SUBMISSIONS", 5)


def cell_daily_max_fills() -> int:
    """Per-cell filled trades/day — fills are the real exposure."""
    return _env_int("MERID_THRESHOLD_CELL_DAILY_MAX_FILLS", 2)


def cell_daily_max_fills_total() -> int:
    """Lane-wide filled trades/day across all cells."""
    return _env_int("MERID_THRESHOLD_CELL_DAILY_MAX_FILLS_TOTAL", 3)


def cell_max_open_orders() -> int:
    """Resting orders per cell — prevents duplicate race submissions."""
    return _env_int("MERID_THRESHOLD_CELL_MAX_OPEN_ORDERS", 1)


def cell_max_open_orders_total() -> int:
    """Resting cell orders across the whole lane — the measurement lane
    runs at most one open passive order at a time."""
    return _env_int("MERID_THRESHOLD_CELL_MAX_OPEN_ORDERS_TOTAL", 1)


def cell_daily_max_fills_per_asset() -> int:
    """Filled trades/day per asset — fair allocation across the universe."""
    return _env_int("MERID_THRESHOLD_CELL_DAILY_MAX_FILLS_PER_ASSET", 2)


def _suspend_min_fills() -> int:
    return _env_int("MERID_THRESHOLD_CELL_SUSPEND_MIN_FILLS", 5)


def _suspend_mean_pnl() -> float:
    return _env_float("MERID_THRESHOLD_CELL_SUSPEND_MEAN_PNL_C", -1.0)


def _suspend_markout_median() -> float:
    return _env_float("MERID_THRESHOLD_CELL_SUSPEND_MARKOUT_MEDIAN_C", -1.0)


def _suspend_reject_rate() -> float:
    return _env_float("MERID_THRESHOLD_CELL_SUSPEND_REJECT_RATE", 0.40)


def _suspend_reject_min() -> int:
    return _env_int("MERID_THRESHOLD_CELL_SUSPEND_REJECT_MIN", 5)


def _suspend_ev_drop() -> float:
    return _env_float("MERID_THRESHOLD_CELL_SUSPEND_EV_DROP_C", -1.5)


def _suspend_exec_failures() -> int:
    return _env_int("MERID_THRESHOLD_CELL_SUSPEND_EXEC_FAILURES", 2)


def cell_state_path() -> str:
    return os.environ.get(
        "MERID_THRESHOLD_CELL_STATE_PATH", "data/threshold_cell_lane.json"
    )


def _utc_day(now: float) -> str:
    return datetime.fromtimestamp(now, tz=timezone.utc).date().isoformat()


def _default_state(now: float) -> Dict[str, Any]:
    return {
        "date": _utc_day(now),
        "count": 0,
        "submissions": {},
        "fills_today": {},
        "open_orders": {},
        "open_orders_ts": {},
        "router_attempts": {},
        "router_rejects": {},
        "router_consecutive_rejects": {},
        "cell_states": {},
        "outcomes": {},
        "decision_cell_map": {},
        "funnel": {s: 0 for s in FUNNEL_STAGES},
        "funnel_by_cell": {},
    }


def _load_state(now: Optional[float] = None, path: Optional[str] = None) -> Dict[str, Any]:
    """Load the lane state, rolling daily counters and seeding the cache."""
    global _STATE_CACHE, _STATE_CACHE_PATH
    now = time.time() if now is None else float(now)
    p = path or cell_state_path()
    with _state_lock:
        if _STATE_CACHE is not None and _STATE_CACHE_PATH == p:
            # Roll daily-scoped counters if the UTC day moved.
            if _STATE_CACHE.get("date") != _utc_day(now):
                _STATE_CACHE["date"] = _utc_day(now)
                _STATE_CACHE["count"] = 0
                _STATE_CACHE["submissions"] = {}
                _STATE_CACHE["fills_today"] = {}
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
        # Durable keys that survive the daily roll.
        for k in ("cell_states", "outcomes", "decision_cell_map", "open_orders", "open_orders_ts"):
            if isinstance(rec.get(k), dict):
                state[k] = rec[k]
        # Daily-scoped keys only count when the file is from today.
        if rec.get("date") == state["date"]:
            for k in (
                "count",
                "submissions",
                "fills_today",
                "router_attempts",
                "router_rejects",
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
        logger.debug("[THRESHOLD-CELL] state persist failed: %s", exc)


def _save_state(path: Optional[str] = None) -> None:
    with _state_lock:
        if _STATE_CACHE is not None:
            _persist_state_locked(path or _STATE_CACHE_PATH or cell_state_path(), _STATE_CACHE)


def reset_cell_state_cache() -> None:
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
        raise ValueError(f"invalid threshold-cell state {state!r}")
    st = _load_state()
    rec = st["cell_states"].setdefault(cell_id, {})
    rec["state"] = state
    rec["since_ts"] = time.time()
    rec["reason"] = reason
    _save_state()
    logger.info(
        "[THRESHOLD-CELL-STATE] cell=%s -> %s reason=%s",
        cell_id, state, reason,
    )
    emit_cell_lifecycle(
        "state_transition",
        threshold_cell_id=cell_id,
        terminal_state=state,
        reason=reason,
    )


def _suspend_cell(cell_id: str, reason: str) -> None:
    if get_cell_state(cell_id) != CELL_STATE_SUSPENDED:
        logger.warning(
            "[THRESHOLD-CELL-SUSPEND] cell=%s reason=%s — lane fails closed",
            cell_id, reason,
        )
        set_cell_state(cell_id, CELL_STATE_SUSPENDED, reason)


# ---------------------------------------------------------------------------
# Counters / caps
# ---------------------------------------------------------------------------

def cell_submissions_today(
    path: Optional[str] = None, now: Optional[float] = None
) -> int:
    """Cell-lane submissions recorded for the current UTC day (global)."""
    st = _load_state(now, path)
    return int(st.get("count") or 0)


def cell_cap_remaining(path: Optional[str] = None, now: Optional[float] = None) -> int:
    return max(0, cell_daily_max() - cell_submissions_today(path, now))


def cell_fills_today(cell_id: str) -> int:
    st = _load_state()
    return int((st.get("fills_today") or {}).get(cell_id) or 0)


def cell_open_orders(cell_id: str) -> int:
    st = _load_state()
    if _prune_stale_open_orders(st, time.time()):
        _save_state()
    return len((st.get("open_orders") or {}).get(cell_id) or [])


def record_cell_submission(
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
        if decision_id:
            st.setdefault("decision_cell_map", {})[decision_id] = cell_id
            _cap_decision_cell_map(st)
    _save_state(path)
    return int(st["count"])


def _cap_decision_cell_map(st: Dict[str, Any], limit: int = 500) -> None:
    """Bound the persisted decision->cell map — 15m markets settle within
    the hour, so entries beyond the most recent few hundred can never be
    needed by a settlement/exit join and only bloat the state file."""
    m = st.get("decision_cell_map") or {}
    over = len(m) - limit
    if over > 0:
        for k in list(m.keys())[:over]:
            m.pop(k, None)


def bind_decision_cell(decision_id: str, cell_id: str) -> None:
    """Persist decision_id -> cell_id so settlement/exits can attribute PnL."""
    if not decision_id or not cell_id:
        return
    st = _load_state()
    st.setdefault("decision_cell_map", {})[decision_id] = cell_id
    _cap_decision_cell_map(st)
    _save_state()


def cell_for_decision(decision_id: str) -> Optional[str]:
    st = _load_state()
    return (st.get("decision_cell_map") or {}).get(decision_id)


def _open_order_stale_s() -> float:
    """Bound after which a persisted open order is presumed dead — the
    lane's ExecutionPolicy rests orders at most 60s, so anything older can
    no longer be live.  Covers the restart leak: the in-memory fill tracker
    drops its records on restart, so ``record_cell_order_closed`` never
    fires for orders opened before it and the map would block the lane."""
    return max(4.0 * 60.0, 300.0)


def _prune_stale_open_orders(st: Dict[str, Any], now: float) -> bool:
    opens = st.get("open_orders") or {}
    ts_map = st.setdefault("open_orders_ts", {})
    changed = False
    bound = _open_order_stale_s()
    for cid, ids in list(opens.items()):
        if not ids:
            continue
        cell_ts = ts_map.setdefault(cid, {})
        keep = []
        for oid in ids:
            ots = cell_ts.get(oid)
            if ots is None:
                cell_ts[oid] = now
                keep.append(oid)
                changed = True
            elif now - float(ots) <= bound:
                keep.append(oid)
            else:
                cell_ts.pop(oid, None)
                changed = True
        if len(keep) != len(ids):
            opens[cid] = keep
            changed = True
    return changed


def record_cell_order_open(cell_id: str, order_id: Optional[str]) -> None:
    if not cell_id or not order_id:
        return
    st = _load_state()
    now = time.time()
    _prune_stale_open_orders(st, now)
    opens = st.setdefault("open_orders", {}).setdefault(cell_id, [])
    if order_id not in opens:
        opens.append(order_id)
    st.setdefault("open_orders_ts", {}).setdefault(cell_id, {})[order_id] = now
    # An accepted order breaks any consecutive router-reject run.
    st.setdefault("router_consecutive_rejects", {})[cell_id] = 0
    _save_state()


def record_cell_order_closed(cell_id: str, order_id: Optional[str]) -> None:
    if not cell_id or not order_id:
        return
    st = _load_state()
    opens = st.setdefault("open_orders", {}).setdefault(cell_id, [])
    changed = False
    if order_id in opens:
        opens.remove(order_id)
        changed = True
    if (st.get("open_orders_ts") or {}).get(cell_id, {}).pop(order_id, None) is not None:
        changed = True
    if changed:
        _save_state()


def record_cell_router_attempt(cell_id: str) -> None:
    st = _load_state()
    att = st.setdefault("router_attempts", {})
    att[cell_id] = int(att.get(cell_id) or 0) + 1
    _save_state()


def record_cell_router_reject(cell_id: str) -> None:
    """Post-only cross/reprice/venue reject; feeds the reject-rate rule and
    the consecutive-reject emergency rule (two in a row -> suspend)."""
    if not cell_id:
        return
    st = _load_state()
    rej = st.setdefault("router_rejects", {})
    rej[cell_id] = int(rej.get(cell_id) or 0) + 1
    consec = st.setdefault("router_consecutive_rejects", {})
    consec[cell_id] = int(consec.get(cell_id) or 0) + 1
    _save_state()
    bump_cell_funnel("router_rejected", cell_id)
    _evaluate_suspension(cell_id)


def release_cell_submission_reservation(
    cell_id: str,
    *,
    intent_id: Optional[str] = None,
    decision_id: Optional[str] = None,
) -> bool:
    """Release the submission slot a cell candidate reserved at emission.

    A candidate whose intent never reached the venue (pre-wire reject) must
    not burn scarce lane capacity.  Idempotent per (intent_id | decision_id)
    so duplicate release calls are harmless.  Returns True when a slot was
    actually released.
    """
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
    if int(st.get("count") or 0) > 0:
        st["count"] = int(st.get("count") or 0) - 1
    _save_state()
    return True


def record_cell_pre_wire_reject(
    cell_id: str,
    *,
    decision_id: Optional[str] = None,
    intent_id: Optional[str] = None,
    rejection_code: str = "pre_wire_reject",
    stage: str = "pre_wire",
    asset: Optional[str] = None,
    ticker: Optional[str] = None,
) -> None:
    """Terminal accounting for a cell intent rejected before reaching the wire.

    Per the shared execution-lane contract: a pre-wire drop releases the
    submission reservation AND counts toward the router-reject suspension
    rule — the lane sees every attempt's true outcome instead of silently
    consuming its daily submission budget.
    """
    if not cell_id:
        return
    released = release_cell_submission_reservation(
        cell_id, intent_id=intent_id, decision_id=decision_id
    )
    record_cell_router_reject(cell_id)
    code = str(rejection_code or "pre_wire_reject")
    _base = {
        "threshold_cell_id": cell_id,
        "asset": asset,
        "ticker": ticker,
        "decision_id": decision_id,
        "intent_id": intent_id,
        "rejection_code": code.split(":", 1)[0].upper(),
        "rejection_detail": code[:200],
        "exec_stage": stage,
    }
    # Complete lifecycle accounting: every emitted candidate terminates in
    # router_rejected -> reservation released -> lane state updated.
    emit_cell_lifecycle(
        "router_rejected", submitted=False, terminal_state="router_rejected",
        reservation_released=released, **_base,
    )
    emit_cell_lifecycle(
        "submission_reservation_released", released=released, **_base,
    )
    emit_cell_lifecycle("lane_state_updated", **_base)


def record_cell_exec_failure(cell_id: str, reason: str) -> None:
    """Integrity/execution failure (e.g. identity mismatch, coercion, missing
    fill attribution).  More than ``_suspend_exec_failures`` -> SUSPENDED."""
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


def record_cell_fill(
    cell_id: str,
    *,
    decision_id: Optional[str] = None,
    markout_5s_cents: Optional[float] = None,
    fill_ev_cents: Optional[float] = None,
    candidate_ev_cents: Optional[float] = None,
) -> None:
    """Record a live fill for the cell; drives fills/day cap + suspension.

    ``net_pnl_cents`` arrives later via :func:`record_cell_settlement` — fills
    and settlements are separate lifecycle stages.
    """
    if not cell_id:
        return
    st = _load_state()
    fills = st.setdefault("fills_today", {})
    fills[cell_id] = int(fills.get(cell_id) or 0) + 1
    outs = st.setdefault("outcomes", {}).setdefault(cell_id, [])
    # Absorb standalone markout rows that emitted for this decision before
    # the fill was detected (the markout loop is submit-relative), so the
    # first-fill immediate rules see them and they don't double-count in the
    # rolling window.
    fill_row = {
        "ts": time.time(),
        "kind": "fill",
        "decision_id": decision_id,
        "markout_5s_cents": markout_5s_cents,
        "fill_ev_cents": fill_ev_cents,
        "candidate_ev_cents": candidate_ev_cents,
    }
    if decision_id:
        rest = []
        for o in outs:
            if o.get("decision_id") == decision_id and o.get("kind") == "markout":
                for k, v in o.items():
                    if k.startswith("markout_") and v is not None and fill_row.get(k) is None:
                        fill_row[k] = float(v)
            else:
                rest.append(o)
        if len(rest) != len(outs):
            outs[:] = rest
    outs.append(fill_row)
    del outs[:-25]
    if decision_id:
        st.setdefault("decision_cell_map", {})[decision_id] = cell_id
        _cap_decision_cell_map(st)
    _save_state()
    bump_cell_funnel("filled", cell_id)
    # PROVISIONAL -> OBSERVATION once real fills exist for the cell.
    if get_cell_state(cell_id) == CELL_STATE_PROVISIONAL:
        set_cell_state(cell_id, CELL_STATE_OBSERVATION, "first_fill")
    _evaluate_suspension(cell_id)


def record_cell_markout(
    cell_id: str,
    decision_id: Optional[str],
    horizon_s: int,
    markout_cents: float,
    regime: Optional[str] = None,
    policy_epoch: Optional[str] = None,
) -> None:
    """Attach a post-fill markout to the cell's rolling outcome window.

    Marks the most recent fill row for this decision (or appends a bare
    markout row when the fill was recorded elsewhere) and re-evaluates the
    suspension rules — persistent negative 5s markouts are the primary
    adverse-selection signal for a passive lane.
    """
    if not cell_id:
        return
    st = _load_state()
    outs = st.setdefault("outcomes", {}).setdefault(cell_id, [])
    key = f"markout_{horizon_s}s_cents"
    for o in reversed(outs):
        if o.get("decision_id") == decision_id and o.get("kind") in ("fill", "settled"):
            o[key] = float(markout_cents)
            if regime is not None:
                o["regime"] = regime
            if policy_epoch is not None:
                o["policy_epoch"] = policy_epoch
            break
    else:
        outs.append({
            "ts": time.time(),
            "kind": "markout",
            "decision_id": decision_id,
            key: float(markout_cents),
            "regime": regime,
            "policy_epoch": policy_epoch,
        })
        del outs[:-25]
    _save_state()
    if horizon_s == 5:
        _evaluate_suspension(cell_id)


def record_cell_settlement(
    decision_id: str,
    net_pnl_cents: float,
    cell_id: Optional[str] = None,
) -> None:
    """Attach realized net PnL (exit or settlement join) to a cell's window."""
    cell_id = cell_id or cell_for_decision(decision_id)
    if not cell_id:
        return
    st = _load_state()
    outs = st.setdefault("outcomes", {}).setdefault(cell_id, [])
    # Prefer updating the fill record for this decision to a settlement row.
    # Match settled rows too — a second attribution (exit path + settlement
    # join) updates in place instead of appending a duplicate outcome.
    for o in reversed(outs):
        if o.get("decision_id") == decision_id and o.get("kind") in ("fill", "settled"):
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


def _evaluate_suspension(cell_id: str) -> None:
    """Fail-closed lane stop: any breached rule suspends the cell."""
    st = _load_state()
    if get_cell_state(cell_id) in (CELL_STATE_SUSPENDED, CELL_STATE_PROMOTED):
        return
    outs = list((st.get("outcomes") or {}).get(cell_id) or [])
    min_fills = _suspend_min_fills()

    # ── Pre-five emergency rules (2026-09-30): a newly-live lane cannot wait
    # for five fills to discover adverse selection.  Any of these suspends
    # the cell immediately.
    consec = int((st.get("router_consecutive_rejects") or {}).get(cell_id) or 0)
    if consec >= 2:
        _suspend_cell(
            cell_id,
            f"consecutive_router_rejects={consec} (post-only cross/stale "
            "revalidation twice in a row)",
        )
        return

    fills = [o for o in outs if o.get("kind") in ("fill", "settled")]
    if fills:
        first = fills[0]
        # First fill whose 5s markout is deeply negative: adverse selection.
        m5 = first.get("markout_5s_cents")
        if m5 is not None and float(m5) <= -3.0:
            _suspend_cell(
                cell_id,
                f"first_fill_markout_5s={float(m5):+.2f}c <= -3.00c",
            )
            return
        # Fill-time EV nonpositive after revalidation: the passive fill
        # landed at or beyond the edge the decision economics assumed.
        fev = first.get("fill_ev_cents")
        if fev is not None and float(fev) <= 0.0:
            _suspend_cell(
                cell_id,
                f"fill_ev_nonpositive={float(fev):+.2f}c",
            )
            return
        # First settled trade lost more than expected edge + 2c stress.
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
    # Any fill (not just the first) with nonpositive fill-time EV suspends.
    for o in fills:
        fev = o.get("fill_ev_cents")
        if fev is not None and float(fev) <= 0.0:
            _suspend_cell(cell_id, f"fill_ev_nonpositive={float(fev):+.2f}c")
            return

    # Rolling-N realized net PnL (settled outcomes only).
    net_pnls = [o["net_pnl_cents"] for o in outs if o.get("net_pnl_cents") is not None]
    if len(net_pnls) >= min_fills:
        window = net_pnls[-min_fills:]
        if (sum(window) / len(window)) < _suspend_mean_pnl():
            _suspend_cell(
                cell_id,
                f"rolling_{min_fills}_mean_net_pnl={sum(window)/len(window):+.2f}c < {_suspend_mean_pnl():+.2f}c",
            )
            return

    # Rolling-N 5s markout median (adverse-selection proxy).
    markouts = [
        o["markout_5s_cents"] for o in outs if o.get("markout_5s_cents") is not None
    ]
    if len(markouts) >= min_fills:
        med = statistics.median(markouts[-min_fills:])
        if med < _suspend_markout_median():
            _suspend_cell(
                cell_id,
                f"rolling_{min_fills}_median_markout_5s={med:+.2f}c < {_suspend_markout_median():+.2f}c",
            )
            return

    # Fill-time EV materially below candidate-time EV (passive fills landing
    # worse than the decision economics assumed).
    ev_drops = [
        float(o["fill_ev_cents"]) - float(o["candidate_ev_cents"])
        for o in outs
        if o.get("fill_ev_cents") is not None and o.get("candidate_ev_cents") is not None
    ]
    if len(ev_drops) >= min_fills:
        window = ev_drops[-min_fills:]
        if (sum(window) / len(window)) < _suspend_ev_drop():
            _suspend_cell(
                cell_id,
                f"rolling_{min_fills}_mean_ev_drop={sum(window)/len(window):+.2f}c < {_suspend_ev_drop():+.2f}c",
            )
            return

    # Router reject/cross rate.
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

    # Execution/integrity failures.
    failures = sum(1 for o in outs if o.get("kind") == "exec_failure")
    if failures > _suspend_exec_failures():
        _suspend_cell(
            cell_id,
            f"exec_failures={failures} > {_suspend_exec_failures()}",
        )
        return


def cell_submissions_today_cell(cell_id: str) -> int:
    st = _load_state()
    return int((st.get("submissions") or {}).get(cell_id) or 0)


def cell_fills_today_total() -> int:
    st = _load_state()
    return sum(int(v or 0) for v in (st.get("fills_today") or {}).values())


def cell_fills_today_asset(asset: str) -> int:
    """Per-asset filled trades/day — fair allocation: no single asset may
    consume the lane's exploratory fill budget."""
    st = _load_state()
    want = str(asset).upper()
    total = 0
    for cid, n in (st.get("fills_today") or {}).items():
        cell = _CELLS_BY_ID.get(cid)
        if cell is not None and cell.asset == want:
            total += int(n or 0)
    return total


def cell_open_orders_total() -> int:
    """Resting cell orders across ALL cells — the lane runs at most one
    open passive order at a time (global serialization)."""
    st = _load_state()
    if _prune_stale_open_orders(st, time.time()):
        _save_state()
    return sum(
        len(v) for v in (st.get("open_orders") or {}).values() if v
    )


def cell_admission(cell_id: str) -> Tuple[bool, Optional[str]]:
    """(allowed, block_reason) — all lane admission checks in one place.

    Fail-closed: SUSPENDED or an unknown state blocks; PROMOTED keeps the
    same caps until a separate review widens them.
    """
    if not threshold_cells_enabled():
        return False, "threshold_cells_disabled"
    state = get_cell_state(cell_id)
    if state == CELL_STATE_SUSPENDED:
        return False, "cell_suspended"
    if state not in CELL_STATES:
        return False, f"cell_state_unknown:{state}"
    if cell_fills_today(cell_id) >= cell_daily_max_fills():
        return False, "cell_fills_cap_exhausted"
    if cell_fills_today_total() >= cell_daily_max_fills_total():
        return False, "cell_fills_total_cap_exhausted"
    if cell_open_orders(cell_id) >= cell_max_open_orders():
        return False, "cell_open_order_exists"
    # Fair allocation (2026-09-30): one resting cell order globally and at
    # most N fills per asset per day, so a single asset's regime cannot
    # consume the lane's exploratory budget ahead of the others.
    if cell_open_orders_total() >= cell_max_open_orders_total():
        return False, "lane_open_order_exists"
    _cell = _CELLS_BY_ID.get(cell_id)
    if _cell is not None and cell_fills_today_asset(
        _cell.asset
    ) >= cell_daily_max_fills_per_asset():
        return False, "asset_fills_cap_exhausted"
    if cell_submissions_today_cell(cell_id) >= cell_daily_max_submissions_per_cell():
        return False, "cell_submissions_cap_exhausted"
    if cell_submissions_today() >= cell_daily_max():
        return False, "cap_exhausted"
    return True, None


def threshold_cell_sparse_override_enabled() -> bool:
    """``MERID_THRESHOLD_CELL_SPARSE_OVERRIDE=0`` restores strict evidence
    gating for cell-matched candidates (emergency off-switch)."""
    return os.environ.get(
        "MERID_THRESHOLD_CELL_SPARSE_OVERRIDE", "1"
    ).strip().lower() in ("1", "true", "yes", "on")


def threshold_cell_admission_allowed(
    cell_id: Optional[str],
    evidence_code: Optional[str],
    matching_hard_block: bool,
    net_ev_cents: Optional[float],
    effective_required_edge_cents: Optional[float],
) -> Tuple[bool, Optional[str]]:
    """Bounded soft-evidence override for the threshold-cell lane.

    A matched, historically qualified cell whose *current* executable net EV
    clears its own effective threshold owns the admission decision for its
    candidate: soft evidence verdicts (``SOFT_EVIDENCE_CODES``) are routed
    through the cell lane's own caps and suspension state instead of the
    generic escape-lane budget.  Hard blocks (``matching_hard_block``,
    ``MATCHING_TOXIC_CELL``, matched adverse posteriors such as
    ``CELL_EVIDENCE_INSUFFICIENT``), disabled config lanes
    (``*_LANE_DISABLED``), low-EV candidates, suspended/capped lanes, and
    unmatched inputs keep their original rejection.

    Returns ``(allowed, reason)``.  ``reason`` is None both when allowed and
    when the candidate simply has no cell (not this policy's decision).
    """
    if not cell_id:
        return False, None
    # Registered cells only — a synthetic or stale id must never admit.
    # Membership is checked against the live table so tests/updates that
    # modify THRESHOLD_CELLS take effect immediately.
    if all(c.cell_id != cell_id for c in THRESHOLD_CELLS):
        return False, "unknown_cell_id"
    if not threshold_cell_sparse_override_enabled():
        return False, "soft_override_disabled"
    if matching_hard_block:
        return False, "matching_hard_block"
    if evidence_code not in SOFT_EVIDENCE_CODES:
        return False, f"evidence_code_not_soft:{evidence_code}"
    if net_ev_cents is None or effective_required_edge_cents is None:
        return False, "missing_ev_or_threshold"
    if float(net_ev_cents) < float(effective_required_edge_cents):
        return False, "ev_below_cell_threshold"
    state = get_cell_state(cell_id)
    if state not in (CELL_STATE_PROVISIONAL, CELL_STATE_OBSERVATION):
        return False, f"cell_state_{state.lower()}"
    allowed, block = cell_admission(cell_id)
    if not allowed:
        return False, block
    return True, None


# Backwards-compatible alias (earlier name covered only SPARSE_*).
def may_bypass_sparse_evidence(
    cell_id: Optional[str],
    evidence_code: Optional[str],
    matching_hard_block: bool,
    net_ev_cents: Optional[float],
    effective_required_edge_cents: Optional[float],
) -> Tuple[bool, Optional[str]]:
    return threshold_cell_admission_allowed(
        cell_id, evidence_code, matching_hard_block,
        net_ev_cents, effective_required_edge_cents,
    )


def record_cell_invariant_violation(cell_id: Optional[str], reason: str) -> None:
    """Immediate suspension: a filled threshold-cell order violated a
    price/side mapping invariant.  This is structural corruption, not
    performance — no rolling window applies."""
    if not cell_id:
        return
    logger.warning(
        "[THRESHOLD-CELL-SUSPEND] cell=%s invariant_violation=%s",
        cell_id, reason,
    )
    _suspend_cell(cell_id, f"invariant_violation:{str(reason)[:120]}")
    emit_cell_lifecycle(
        "suspended",
        threshold_cell_id=cell_id,
        terminal_state="SUSPENDED",
        reason=f"invariant_violation:{str(reason)[:120]}",
    )


# ---------------------------------------------------------------------------
# Funnel counters
# ---------------------------------------------------------------------------

def bump_cell_funnel(stage: str, cell_id: Optional[str] = None) -> None:
    """Increment a funnel stage counter (validated + persisted)."""
    if stage not in FUNNEL_STAGES:
        logger.debug("[THRESHOLD-CELL] unknown funnel stage %r", stage)
        return
    st = _load_state()
    st["funnel"][stage] = int(st["funnel"].get(stage) or 0) + 1
    if cell_id:
        per = st.setdefault("funnel_by_cell", {}).setdefault(cell_id, {})
        per[stage] = int(per.get(stage) or 0) + 1
    _save_state()


def funnel_counters() -> Dict[str, Any]:
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
        _LIFECYCLE_PATH_ENV, "logs/threshold_cell_lifecycle.jsonl"
    )


def emit_cell_lifecycle(stage: str, **fields: Any) -> None:
    """Append one correlated lifecycle event to logs/threshold_cell_lifecycle.jsonl."""
    try:
        rec = {
            "event": "threshold_cell_lifecycle",
            "stage": stage,
            "ts": time.time(),
            "ts_utc": datetime.now(timezone.utc).isoformat(),
        }
        rec.update(fields)
        path = _lifecycle_path()
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, default=str, separators=(",", ":")) + "\n")
    except Exception as exc:
        logger.debug("[THRESHOLD-CELL] lifecycle emit failed: %s", exc)


# ---------------------------------------------------------------------------
# Startup containment assertion
# ---------------------------------------------------------------------------

def validate_cells_within_price_bands() -> List[Dict[str, Any]]:
    """Assert every approved cell is reachable inside the live band domain.

    A cell is reachable when at least one (price, tte) point inside its
    rectangle is admitted by ``classify_market_regime``.  Raises
    ``AssertionError`` listing unreachable cells — the lane must fail closed
    rather than deploy a cell that can never fire.  Returns per-cell coverage
    detail for the startup log.
    """
    from merid.event_venues.kalshi.market_regime import classify_market_regime

    report: List[Dict[str, Any]] = []
    unreachable: List[str] = []
    for cell in THRESHOLD_CELLS:
        covered: List[Dict[str, Any]] = []
        blocked: List[Dict[str, Any]] = []
        # Scan each price in the cell's half-open band; for each band regime
        # overlapping that price, intersect the TTE window with the cell's.
        for px in range(cell.price_min_cents, cell.price_max_cents):
            for tte in (cell.tte_min_seconds, cell.tte_max_seconds):
                regime = classify_market_regime(px, int(tte))
                if regime is not None:
                    covered.append({"price": px, "tte": tte, "band": regime.name})
                else:
                    blocked.append({"price": px, "tte": tte})
        reachable = bool(covered)
        report.append({
            "cell_id": cell.cell_id,
            "reachable": reachable,
            "covered_points": len(covered),
            "blocked_points": len(blocked),
        })
        if not reachable:
            unreachable.append(cell.cell_id)
    if unreachable:
        raise AssertionError(
            f"threshold cells outside the live price-band domain: {unreachable}"
        )
    return report
