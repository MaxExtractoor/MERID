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

Routing
-------
A decision whose selected side was admitted by a cell is stamped
``decision_lane = "threshold_cell"`` (and ``threshold_cell_id``), which the
agent-grid order-style block forces to a one-contract post-only maker order —
the same bounded treatment as the evidence escape lane.

Kill switch: ``MERID_THRESHOLD_CELLS=0`` reverts to the legacy formula
everywhere without a deploy.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from typing import List, NamedTuple, Optional


class ThresholdCell(NamedTuple):
    """One empirically-qualified admission cell.

    Bounds are half-open: ``price_min_cents <= ask < price_max_cents`` and
    ``tte_min_seconds <= tte < tte_max_seconds``.
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


# Approved 2026-09-30 from the settled counterfactual frontier.  LCB10 = the
# ~10% lower confidence bound on mean net c/contract at the decision-time
# executable ask (taker-fee counterfactual — conservative vs post-only).
THRESHOLD_CELLS: List[ThresholdCell] = [
    # SOL NO mid band: frontier marginal band realized +14.4/+21.3/+18.7c mean
    # at 30-59c asks (LCB +8.8..+14.7); blocked cohort avg req was 6.4c.
    ThresholdCell(
        "sol_no_30_60_t120_600", "SOL", "no", 30, 60, 120.0, 600.0, 1.5,
        "frontier: SOL-NO 30-59c LCB10 +8.8..+14.7c; TTE120-300 LCB +14.1c",
    ),
    # SOL NO 60-79c: 70-79c bucket +10.3c (LCB +2.7) but 60-69c weak (-2.3c);
    # admitted at a higher bar.
    ThresholdCell(
        "sol_no_60_80_t120_600", "SOL", "no", 60, 80, 120.0, 600.0, 2.5,
        "frontier: SOL-NO 70-79c LCB +2.7c; 60-69c weak -> higher bar",
    ),
    # DOGE NO: 20-29c +7.7c (LCB +1.6) and 40-49c +9.5c (LCB +2.4); the 30-39c
    # cell was inconclusive (LCB -4.8) and is deliberately not qualified.
    # Note: the held-price floor (25c) still vetoes the 20-24c half of the
    # first cell — the cell relaxes only the edge gate.
    ThresholdCell(
        "doge_no_20_30_t120_600", "DOGE", "no", 20, 30, 120.0, 600.0, 2.0,
        "frontier: DOGE-NO 20-29c LCB +1.6c (held floor still applies <25c)",
    ),
    ThresholdCell(
        "doge_no_40_50_t120_600", "DOGE", "no", 40, 50, 120.0, 600.0, 2.0,
        "frontier: DOGE-NO 40-49c LCB +2.4c",
    ),
    # DOGE NO 70-89c: +22.2c (70-79, LCB +21.5) / +9.6c (80-89, LCB +6.2);
    # higher bar for the execution-sensitive upper band.
    ThresholdCell(
        "doge_no_70_90_t120_600", "DOGE", "no", 70, 90, 120.0, 600.0, 3.0,
        "frontier: DOGE-NO 70-89c LCB +6.2..+21.5c",
    ),
    # XRP NO 30-39c +9.8c (LCB +3.7) and 80-89c +5.8c (LCB +2.2); the 40-79c
    # middle was mixed and stays on the legacy formula.
    ThresholdCell(
        "xrp_no_30_40_t120_600", "XRP", "no", 30, 40, 120.0, 600.0, 2.5,
        "frontier: XRP-NO 30-39c LCB +3.7c",
    ),
    ThresholdCell(
        "xrp_no_80_90_t120_600", "XRP", "no", 80, 90, 120.0, 600.0, 2.5,
        "frontier: XRP-NO 80-89c LCB +2.2c",
    ),
]


def threshold_cells_enabled() -> bool:
    """Single kill switch: ``MERID_THRESHOLD_CELLS=0`` reverts to formula."""
    return os.environ.get("MERID_THRESHOLD_CELLS", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
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
    table.
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
        if not (cell.tte_min_seconds <= tte < cell.tte_max_seconds):
            continue
        if best is None or (
            cell.price_max_cents - cell.price_min_cents
            < best.price_max_cents - best.price_min_cents
        ):
            best = cell
    return best


# ---------------------------------------------------------------------------
# Lane daily submission cap (durable one-line counter)
# ---------------------------------------------------------------------------
# The approved stop condition for this first deployment is a bounded daily
# submission budget: counting submissions (not fills) is the stricter bound —
# a post-only order that never fills still consumes the slot.  Realized-PnL /
# markout-based lane suspension is layered on top via the audit-ledger review
# once the lane has live fills to score.

def cell_daily_max() -> int:
    try:
        return int(os.environ.get("MERID_THRESHOLD_CELL_DAILY_MAX", "20"))
    except Exception:
        return 20


def cell_state_path() -> str:
    return os.environ.get(
        "MERID_THRESHOLD_CELL_STATE_PATH", "data/threshold_cell_lane.json"
    )


def cell_submissions_today(
    path: Optional[str] = None, now: Optional[float] = None
) -> int:
    """Cell-lane submissions recorded for the current UTC day."""
    now = time.time() if now is None else float(now)
    day = datetime.fromtimestamp(now, tz=timezone.utc).date().isoformat()
    try:
        with open(path or cell_state_path(), "r", encoding="utf-8") as f:
            rec = json.load(f)
        if rec.get("date") == day:
            return int(rec.get("count") or 0)
    except Exception:
        pass
    return 0


def cell_cap_remaining(path: Optional[str] = None, now: Optional[float] = None) -> int:
    return max(0, cell_daily_max() - cell_submissions_today(path, now))


def record_cell_submission(
    path: Optional[str] = None, now: Optional[float] = None
) -> int:
    """Increment today's cell-lane submission counter; returns new count."""
    now = time.time() if now is None else float(now)
    p = path or cell_state_path()
    day = datetime.fromtimestamp(now, tz=timezone.utc).date().isoformat()
    count = cell_submissions_today(p, now) + 1
    try:
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(json.dumps({"date": day, "count": count}))
        os.replace(tmp, p)
    except Exception:
        pass
    return count
