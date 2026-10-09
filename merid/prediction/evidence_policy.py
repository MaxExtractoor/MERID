"""Cell-aware live entry-evidence policy (v1).

Replaces the coarse ``live_evidence_asset_{yes,no}`` vetoes with a deterministic
asset x side x price-bucket x TTE-bucket cell evaluation:

- The evidence artifact (``data/live_entry_evidence.json`` v2, rebuilt by
  ``decision_audit_ledger`` on every settlement) stores time-decayed,
  per-ticker-normalized win/loss aggregates at the finest cell grain.
- ``evaluate`` walks a fixed hierarchy (exact cell -> pooled parents ->
  side -> global), fits a Beta-binomial posterior whose prior is the nearest
  adequately-sampled ancestor (partial pooling), and converts the posterior
  10% lower credible bound into a fee-adjusted net-EV check against the
  *current* executable price.
- A dense, matched, recently-confirmed toxic cell stays a hard block;
  sparse cells never hard-block, they add an uncertainty uplift to the
  required margin and flag the bounded escape lane.

The gate is evidence-as-reserve, not evidence-as-ban: a pooled asset-side
cohort losing at ~61c cannot veto the same side at 24c, because the LCB is
scored at the candidate's own executable price.
"""
from __future__ import annotations

import json
import math
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

try:  # posterior quantile; falls back to a Wilson-style approximation
    from scipy.stats import beta as _beta_dist
except Exception:  # pragma: no cover - scipy is installed in prod/test envs
    _beta_dist = None


EVIDENCE_POLICY_VERSION = "cell_aware_v1"

# ---------------------------------------------------------------------------
# Configuration (env-tunable; deterministic defaults)
# ---------------------------------------------------------------------------

def _env_flag(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes")


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(float(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return default


def enabled() -> bool:
    """Master switch for the cell-aware policy (artifact v2 required)."""
    return _env_flag("MERID_EVIDENCE_CELL_POLICY", True)


def halflife_days() -> float:
    return _env_float("MERID_EVIDENCE_HALFLIFE_DAYS", 7.0)


def lcb_quantile() -> float:
    return _env_float("MERID_EVIDENCE_LCB_Q", 0.10)


def min_cell_neff() -> float:
    """Effective independent samples for a level to be *usable*."""
    return _env_float("MERID_EVIDENCE_MIN_CELL_NEFF", 8.0)


def min_parent_neff() -> float:
    return _env_float("MERID_EVIDENCE_MIN_PARENT_NEFF", 8.0)


def kappa_cap() -> float:
    """Max prior pseudo-count inherited from the parent level."""
    return _env_float("MERID_EVIDENCE_KAPPA_CAP", 30.0)


def sparse_full_neff() -> float:
    """At/above this effective n the sparse-uncertainty uplift reaches zero."""
    return _env_float("MERID_EVIDENCE_SPARSE_FULL_NEFF", 50.0)


def sparse_uplift_max_c() -> float:
    """Extra required evidence-margin (cents) for a fully sparse cell."""
    return _env_float("MERID_EVIDENCE_SPARSE_UPLIFT_C", 2.0)


def hard_min_neff() -> float:
    """Minimum effective n for a matched cell to hard-block."""
    return _env_float("MERID_EVIDENCE_HARD_MIN_NEFF", 50.0)


def hard_ev_floor_c() -> float:
    """LCB net EV (at the cohort's own entry prices) below this => toxic."""
    return _env_float("MERID_EVIDENCE_HARD_EV_C", 5.0)


def hard_sparse_min_neff() -> float:
    """Mid-tier hard block: minimum effective n for a matched cell to
    hard-block on the *severe* toxicity floor.

    2026-10-09 repair: n_eff is a market-normalized decayed count bounded by
    the number of distinct settled markets per cell; under current occupancy
    ``hard_min_neff`` (50) is unreachable even pooled to asset|side, which
    made the toxic-cell protection inert.  Rather than lowering the 50 bar,
    sparse cohorts may still hard-block — but only at a much deeper
    demonstrated-loss floor (``hard_sparse_ev_floor_c``).  Shallow adverse
    cells keep failing via the margin path (CELL_EVIDENCE_INSUFFICIENT /
    soft-penalty / challenge), unchanged.
    """
    return _env_float("MERID_EVIDENCE_HARD_SPARSE_MIN_NEFF", 8.0)


def hard_sparse_ev_floor_c() -> float:
    """Severe LCB net-EV floor required to hard-block a sparse matched cell."""
    return _env_float("MERID_EVIDENCE_HARD_SPARSE_EV_C", 10.0)


def hard_sparse_tier_enabled() -> bool:
    """``MERID_EVIDENCE_HARD_SPARSE_TIER`` gates the sparse-severe hard-block
    tier (n_eff>=8 & LCB-EV<-10c).  It is a POLICY change, not a bug fix —
    kept separately attributable and default-off until validated against
    known histories (see AUDIT_2026_10_09_SUSPENSION_PROBATION.md §7)."""
    return _env_flag("MERID_EVIDENCE_HARD_SPARSE_TIER", False)


def evidence_stale_s() -> float:
    """Artifact older than this cannot hard-block; uplift is maxed."""
    return _env_float("MERID_EVIDENCE_STALE_S", 3600.0)


def escape_lane_enabled() -> bool:
    """When off, sparse-cell passes are denied outright (fail closed)."""
    return _env_flag("MERID_EVIDENCE_ESCAPE_LANE", True)


def escape_daily_max() -> int:
    """Per-day cap on escape-lane order submissions (post-only canary)."""
    return _env_int("MERID_EVIDENCE_ESCAPE_DAILY_MAX", 12)


def escape_state_path() -> str:
    return os.environ.get(
        "MERID_EVIDENCE_ESCAPE_STATE_PATH", "data/evidence_escape_fills.json"
    )


def adaptive_states_enabled() -> bool:
    """Intermediate states between hard reject and free pass.

    When on, a matched-but-insufficient cell no longer permanently blocks:
    recent matched outcomes that contradict the stale posterior admit a
    bounded ``CHALLENGE_ELIGIBLE`` trial; absent contradiction the candidate
    must clear an elevated ``SOFT_PENALTY`` model-edge reserve.  Toxic dense
    cells (MATCHING_TOXIC_CELL) remain a hard block either way.
    """
    return _env_flag("MERID_EVIDENCE_ADAPTIVE_STATES", True)


def challenge_min_recent_n() -> int:
    """Min recent matched observations for a 'prior is stale' challenge."""
    return _env_int("MERID_EVIDENCE_CHALLENGE_MIN_RECENT_N", 3)


def soft_penalty_extra_c() -> float:
    """Extra model-edge margin (cents) for SOFT_PENALTY admission."""
    return _env_float("MERID_EVIDENCE_SOFT_PENALTY_C", 4.0)


# ---------------------------------------------------------------------------
# Cell dimensions
# ---------------------------------------------------------------------------

def price_bucket(price_cents: Optional[float]) -> str:
    """Canonical held-price bucket label."""
    if price_cents is None:
        return "unknown"
    p = int(round(float(price_cents)))
    if p <= 9:
        return "01-09"
    if p <= 24:
        return "10-24"
    if p <= 49:
        return "25-49"
    if p <= 74:
        return "50-74"
    if p <= 89:
        return "75-89"
    return "90-100"


def tte_bucket(tte_seconds: Optional[float]) -> str:
    """Time-to-expiry bucket for a 15-minute (900s) market."""
    if tte_seconds is None:
        return "unknown"
    t = float(tte_seconds)
    if t > 600.0:
        return "early"
    if t > 300.0:
        return "mid"
    if t > 120.0:
        return "late"
    return "final"


def cell_key(
    asset: str, side: str, price_cents: Optional[float], tte_seconds: Optional[float]
) -> str:
    return (
        f"{str(asset).upper()}|{str(side).lower()}|"
        f"{price_bucket(price_cents)}|{tte_bucket(tte_seconds)}"
    )


# Deterministic fallback chain, most specific -> most pooled.  The dims tuple
# names which cell fields must match at that level.
_HIERARCHY: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("asset_side_price_tte", ("asset", "side", "price_bucket", "tte_bucket")),
    ("asset_side_price", ("asset", "side", "price_bucket")),
    ("asset_side_tte", ("asset", "side", "tte_bucket")),
    ("asset_side", ("asset", "side")),
    ("side_price_tte", ("side", "price_bucket", "tte_bucket")),
    ("side_price", ("side", "price_bucket")),
    ("side", ("side",)),
    ("global", ()),
)

# Levels whose dims are specific enough to support a matched hard block.
_HARD_BLOCK_LEVELS = ("asset_side_price_tte", "asset_side_price")

# Levels that may be *scored* by the LCB net-EV check.  A win-rate posterior
# is only meaningful against a comparable cost basis, so every scored level
# matches the candidate's price bucket; all other chain levels (asset_side,
# side, global) inform the Beta prior but can never veto at a mismatched
# price — the flaw the old asset-side gate had.
_SCORED_LEVELS = (
    "asset_side_price_tte",
    "asset_side_price",
    "side_price_tte",
    "side_price",
)


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

@dataclass
class CellAgg:
    """Decayed, market-normalized aggregate for one evidence level."""

    n_eff: float = 0.0
    n_raw: int = 0
    w: float = 0.0
    l: float = 0.0
    entry_wsum: float = 0.0
    recent_w: float = 0.0
    recent_l: float = 0.0
    recent_n: int = 0

    @property
    def n(self) -> float:
        return self.w + self.l

    @property
    def wr(self) -> float:
        return self.w / self.n if self.n > 0 else 0.0

    @property
    def avg_entry_cents(self) -> float:
        return self.entry_wsum / self.n_eff if self.n_eff > 0 else 0.0

    @property
    def recent_wr(self) -> Optional[float]:
        rn = self.recent_w + self.recent_l
        return self.recent_w / rn if rn > 0 else None

    def add(self, cell: Dict[str, Any]) -> None:
        self.w += float(cell.get("w") or 0.0)
        self.l += float(cell.get("l") or 0.0)
        self.n_eff += float(cell.get("n_eff") or 0.0)
        self.n_raw += int(cell.get("n_raw") or 0)
        self.entry_wsum += float(cell.get("entry_wsum") or 0.0)
        self.recent_w += float(cell.get("recent_w") or 0.0)
        self.recent_l += float(cell.get("recent_l") or 0.0)
        self.recent_n += int(cell.get("recent_n") or 0)

    def minus(self, other: "CellAgg") -> "CellAgg":
        """Leave-one-out aggregate: this level excluding ``other``'s cells."""
        return CellAgg(
            w=max(0.0, self.w - other.w),
            l=max(0.0, self.l - other.l),
            n_eff=max(0.0, self.n_eff - other.n_eff),
            n_raw=max(0, self.n_raw - other.n_raw),
            entry_wsum=max(0.0, self.entry_wsum - other.entry_wsum),
            recent_w=max(0.0, self.recent_w - other.recent_w),
            recent_l=max(0.0, self.recent_l - other.recent_l),
            recent_n=max(0, self.recent_n - other.recent_n),
        )


_LEVEL_DIMS = {name: dims for name, dims in _HIERARCHY}


def _find_loo_parent(
    chain: List[Tuple[str, "CellAgg"]],
    used_idx: int,
    used_dims: Tuple[str, ...],
    used_agg: "CellAgg",
) -> Tuple[Optional[str], Optional["CellAgg"]]:
    """Nearest broader level's leave-one-out aggregate for ``used_agg``.

    A level is a valid parent only if its dims are a strict subset of the
    used level's dims (e.g. ``asset_side_price`` is not a parent of
    ``asset_side_tte``).  The used level's own cells are subtracted so the
    prior reflects the sibling cohort, not the cell itself.
    """
    for pname, pagg in chain[used_idx + 1:]:
        if not set(_LEVEL_DIMS[pname]) <= set(used_dims):
            continue
        rem = pagg.minus(used_agg)
        if rem.n_eff >= min_parent_neff():
            return pname, rem
    return None, None


def _cell_dims(key: str) -> Tuple[str, str, str, str]:
    parts = key.split("|")
    if len(parts) != 4:
        return ("", "", "", "")
    return (parts[0], parts[1], parts[2], parts[3])


def aggregate_at_level(
    cells: Dict[str, Dict[str, Any]],
    asset: str,
    side: str,
    price_b: str,
    tte_b: str,
    level_dims: Tuple[str, ...],
) -> CellAgg:
    """Sum every finest-grain cell matching ``level_dims`` for this candidate."""
    target = {
        "asset": str(asset).upper(),
        "side": str(side).lower(),
        "price_bucket": price_b,
        "tte_bucket": tte_b,
    }
    agg = CellAgg()
    for key, cell in cells.items():
        if not isinstance(cell, dict):
            continue
        a, s, pb, tb = _cell_dims(key)
        dims = {"asset": a, "side": s, "price_bucket": pb, "tte_bucket": tb}
        if all(dims[d] == target[d] for d in level_dims):
            agg.add(cell)
    return agg


# ---------------------------------------------------------------------------
# Posterior
# ---------------------------------------------------------------------------

def _beta_lcb(alpha: float, bet: float, q: float) -> float:
    """q-quantile of Beta(alpha, beta); Wilson-style approx if scipy missing."""
    alpha = max(alpha, 1e-9)
    bet = max(bet, 1e-9)
    if _beta_dist is not None:
        try:
            return float(_beta_dist.ppf(q, alpha, bet))
        except Exception:
            pass
    # Normal approx of a beta posterior lower bound.
    n = alpha + bet
    mean = alpha / n
    var = alpha * bet / (n * n * (n + 1.0))
    z = 1.2816 if q <= 0.10 else 1.6449  # q=0.10 / q=0.05
    return max(0.0, min(1.0, mean - z * math.sqrt(var)))


def _beta_std(alpha: float, bet: float) -> float:
    n = alpha + bet
    if n <= 0:
        return 0.0
    return math.sqrt(alpha * bet / (n * n * (n + 1.0)))


@dataclass
class EvidenceDecision:
    allowed: bool
    code: str
    cell_key: str
    evidence_level_used: str
    parent_level: Optional[str]
    effective_independent_n: float
    cell_n_eff: float
    wins_weighted: float
    losses_weighted: float
    n_raw: int
    posterior_mean: float
    posterior_lcb: float
    posterior_std: float
    lcb_net_ev_cents: Optional[float]
    required_margin_cents: float
    sparse_uplift_cents: float
    matching_hard_block: bool
    escape_required: bool
    evidence_stale: bool
    evidence_age_s: Optional[float]
    fallback_reason: Optional[str]
    hard_block_level: Optional[str] = None
    hard_block_ev_cents: Optional[float] = None

    @property
    def admission_state(self) -> str:
        """Spec vocabulary: HARD_BLOCK / SOFT_PENALTY / CHALLENGE_ELIGIBLE /
        NORMAL_ADMISSIBLE / REJECTED — the coarse lane this decision landed in."""
        c = self.code
        if c == "MATCHING_TOXIC_CELL":
            return "HARD_BLOCK"
        if c.startswith("SOFT_PENALTY"):
            return "SOFT_PENALTY"
        if c.startswith("CHALLENGE"):
            return "CHALLENGE_ELIGIBLE"
        if self.allowed and self.escape_required:
            # Bounded post-only trial (sparse/empty evidence or challenge).
            return "CHALLENGE_ELIGIBLE"
        if self.allowed:
            return "NORMAL_ADMISSIBLE"
        return "REJECTED"

    def detail(self) -> Dict[str, Any]:
        return {
            "evidence_policy_version": EVIDENCE_POLICY_VERSION,
            "code": self.code,
            "admission_state": self.admission_state,
            "allowed": self.allowed,
            "cell_key": self.cell_key,
            "evidence_level_used": self.evidence_level_used,
            "parent_level": self.parent_level,
            "effective_independent_n": round(self.effective_independent_n, 2),
            "cell_n_eff": round(self.cell_n_eff, 2),
            "wins_weighted": round(self.wins_weighted, 2),
            "losses_weighted": round(self.losses_weighted, 2),
            "n_raw": self.n_raw,
            "posterior_mean": round(self.posterior_mean, 4),
            "posterior_lcb": round(self.posterior_lcb, 4),
            "posterior_std": round(self.posterior_std, 4),
            "lcb_net_ev_cents": (
                round(self.lcb_net_ev_cents, 2)
                if self.lcb_net_ev_cents is not None
                else None
            ),
            "required_margin_cents": round(self.required_margin_cents, 2),
            "sparse_uplift_cents": round(self.sparse_uplift_cents, 2),
            "matching_hard_block": self.matching_hard_block,
            "escape_required": self.escape_required,
            "evidence_stale": self.evidence_stale,
            "evidence_age_s": (
                round(self.evidence_age_s, 1) if self.evidence_age_s is not None else None
            ),
            "fallback_reason": self.fallback_reason,
            "hard_block_level": self.hard_block_level,
            "hard_block_ev_cents": (
                round(self.hard_block_ev_cents, 2)
                if self.hard_block_ev_cents is not None
                else None
            ),
        }


def _posterior(
    agg: CellAgg, parent: Optional[CellAgg]
) -> Tuple[float, float, float, float]:
    """Beta(alpha, beta) posterior for a level, given its parent's prior.

    Prior = parent posterior mean held with strength min(parent_n_eff, KAPPA),
    i.e. partial pooling: a dense parent pins a sparse cell to the cohort,
    a dense cell can still pull away from a small parent.
    """
    if parent is not None and parent.n > 0:
        m = parent.w / parent.n if parent.n > 0 else 0.5
        kappa = min(parent.n_eff, kappa_cap())
        a0 = max(m * kappa, 0.0)
        b0 = max((1.0 - m) * kappa, 0.0)
    else:
        a0 = b0 = 1.0  # uniform
    alpha = a0 + agg.w
    bet = b0 + agg.l
    mean = alpha / (alpha + bet)
    lcb = _beta_lcb(alpha, bet, lcb_quantile())
    return alpha, bet, mean, lcb


def evaluate_missing_artifact(
    asset: str,
    side: str,
    entry_price_cents: Optional[float],
    tte_seconds: Optional[float],
    fee_frac: float,
    margin_frac: float,
    net_edge_cents: Optional[float],
    *,
    artifact_state: str = "missing",
    now: Optional[float] = None,
) -> EvidenceDecision:
    """Fail-closed verdict when the artifact file is absent/unreadable or
    carries no cell data.

    Runs the same empty-evidence economics test (model net edge must clear
    the max sparse-uncertainty uplift, escape-lane only) but re-codes the
    outcome so telemetry proves provenance: a missing artifact can admit a
    *bounded* trial, never an evidence-backed production entry.
    ``artifact_state``: ``missing`` (no readable file) or ``empty``
    (file present, no usable cells).
    """
    d = evaluate(
        {}, asset, side, entry_price_cents, tte_seconds,
        fee_frac, margin_frac, net_edge_cents, now=now,
    )
    tag = (
        "EVIDENCE_ARTIFACT_MISSING" if artifact_state == "missing"
        else "EVIDENCE_ARTIFACT_EMPTY"
    )
    d.code = f"{tag}_PASS" if d.allowed else tag
    d.fallback_reason = (
        f"artifact {artifact_state}; treated as empty evidence — "
        "bounded-lane admission only, never production"
    )
    return d


def _pick_cells(evidence: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Select the cell aggregate sub-dict for the configured half-life."""
    cells = evidence.get("cells")
    if not isinstance(cells, dict) or not cells:
        return {}
    h = halflife_days()
    for key in (str(int(h)), str(h), f"{h:g}"):
        sub = cells.get(key)
        if isinstance(sub, dict):
            return sub
    # Configured half-life absent: use the artifact's primary variant.
    primary = evidence.get("halflife_days_primary")
    if primary is not None:
        for key in (str(int(primary)), str(primary), f"{float(primary):g}"):
            sub = cells.get(key)
            if isinstance(sub, dict):
                return sub
    # Last resort: first dict-valued entry.
    for sub in cells.values():
        if isinstance(sub, dict):
            return sub
    return {}


def evaluate(
    evidence: Dict[str, Any],
    asset: str,
    side: str,
    entry_price_cents: Optional[float],
    tte_seconds: Optional[float],
    fee_frac: float,
    margin_frac: float,
    net_edge_cents: Optional[float],
    now: Optional[float] = None,
) -> EvidenceDecision:
    """Cell-aware evidence decision for one (asset, side) candidate.

    ``allowed=False`` only on a matched, dense, non-contradicted toxic cell
    (MATCHING_TOXIC_CELL) or when the conservative lower-bound net EV at the
    *current* executable price fails the required margin
    (CELL_EVIDENCE_INSUFFICIENT / ESCAPE_* codes).
    """
    now = time.time() if now is None else float(now)
    side_l = str(side).lower()
    pb = price_bucket(entry_price_cents)
    tb = tte_bucket(tte_seconds)
    ck = cell_key(asset, side_l, entry_price_cents, tte_seconds)

    gen_at = float(evidence.get("generated_at") or 0.0)
    age_s = (now - gen_at) if gen_at > 0 else None
    stale = age_s is not None and age_s > evidence_stale_s()

    cells = _pick_cells(evidence)

    # Chain aggregates, most specific first.
    chain = [
        (name, aggregate_at_level(cells, asset, side_l, pb, tb, dims))
        for name, dims in _HIERARCHY
    ]
    exact_cell = chain[0][1]  # L0 n_eff drives sparsity/escape flagging

    global_agg = chain[-1][1]

    def _base(**kw) -> EvidenceDecision:
        return EvidenceDecision(
            allowed=kw.pop("allowed"),
            code=kw.pop("code"),
            cell_key=ck,
            evidence_level_used=kw.pop("level", "none"),
            parent_level=kw.pop("parent_level", None),
            effective_independent_n=kw.pop("n_eff", 0.0),
            cell_n_eff=exact_cell.n_eff,
            wins_weighted=kw.pop("w", 0.0),
            losses_weighted=kw.pop("l", 0.0),
            n_raw=kw.pop("n_raw", 0),
            posterior_mean=kw.pop("p_mean", 0.5),
            posterior_lcb=kw.pop("p_lcb", 0.5),
            posterior_std=kw.pop("p_std", 0.5),
            lcb_net_ev_cents=kw.pop("lcb_ev", None),
            required_margin_cents=kw.pop("req_margin", 0.0),
            sparse_uplift_cents=kw.pop("uplift", 0.0),
            matching_hard_block=kw.pop("hard", False),
            escape_required=kw.pop("escape", False),
            evidence_stale=stale,
            evidence_age_s=age_s,
            fallback_reason=kw.pop("fallback", None),
            hard_block_level=kw.pop("hb_level", None),
            hard_block_ev_cents=kw.pop("hb_ev", None),
        )

    if entry_price_cents is None:
        return _base(
            allowed=True, code="NO_EXECUTABLE_PRICE",
            fallback="no executable price; evidence gate skipped",
        )

    # -- Hard block: matched cell, toxic, uncontradicted.  Two tiers -------
    # (2026-10-09): dense tier n_eff>=50 needs only the -5c demonstrated-loss
    # floor; a sparse matched cell (n_eff>=8) can still hard-block, but only
    # when toxicity is severe (LCB net EV < -10c at its own cost basis).
    if not stale:
        for hb_name in _HARD_BLOCK_LEVELS:
            hb_dims = dict(_HIERARCHY)[hb_name]
            hb_agg = aggregate_at_level(cells, asset, side_l, pb, tb, hb_dims)
            if hb_agg.n_eff < hard_sparse_min_neff():
                continue
            # Parent prior = nearest broader level, leave-one-out.
            idx = [n for n, _ in _HIERARCHY].index(hb_name)
            _hb_pname, hb_parent = _find_loo_parent(
                chain, idx, hb_dims, hb_agg
            )
            if hb_parent is None and global_agg.n > 0:
                hb_parent = global_agg.minus(hb_agg)
            ha, hb_, hm, hlcb = _posterior(hb_agg, hb_parent)
            # Toxicity measured at the prices the cohort actually traded:
            # LCB win prob must stay meaningfully below its own cost basis.
            hb_ev = (
                (hlcb - hb_agg.avg_entry_cents / 100.0 - float(fee_frac)) * 100.0
            )
            recent_wr = hb_agg.recent_wr
            recent_agrees = (
                recent_wr is None
                or recent_wr < hb_agg.avg_entry_cents / 100.0 + float(fee_frac)
            )
            dense_toxic = (
                hb_agg.n_eff >= hard_min_neff()
                and hb_ev < -abs(hard_ev_floor_c())
            )
            sparse_severe = (
                hard_sparse_tier_enabled()
                and hb_agg.n_eff < hard_min_neff()
                and hb_ev < -abs(hard_sparse_ev_floor_c())
            )
            if (dense_toxic or sparse_severe) and recent_agrees:
                tier = "dense" if dense_toxic else "sparse_severe"
                return _base(
                    allowed=False, code="MATCHING_TOXIC_CELL",
                    level=hb_name, n_eff=hb_agg.n_eff, w=hb_agg.w, l=hb_agg.l,
                    n_raw=hb_agg.n_raw, p_mean=hm, p_lcb=hlcb,
                    p_std=_beta_std(ha, hb_), lcb_ev=hb_ev, hard=True,
                    hb_level=hb_name, hb_ev=hb_ev,
                    fallback=(
                        f"matched {tier} toxic cell "
                        f"(n_eff={hb_agg.n_eff:.1f}, lcb_ev={hb_ev:+.1f}c) "
                        "with no contrary recent evidence"
                    ),
                )

    if not cells:
        # No cell data at all: no probability evidence to gate on.  The
        # uncertainty reserve is economic: the side's own net edge must clear
        # the max sparse uplift rather than a posterior bound.
        uplift = sparse_uplift_max_c()
        ok = net_edge_cents is not None and float(net_edge_cents) >= uplift
        if ok and not escape_lane_enabled():
            return _base(
                allowed=False, code="ESCAPE_LANE_DISABLED", level="none",
                uplift=uplift, req_margin=uplift, escape=True,
                fallback="no cell evidence; escape lane disabled",
            )
        if ok and escape_cap_remaining() <= 0:
            return _base(
                allowed=False, code="ESCAPE_CAP_EXHAUSTED", level="none",
                uplift=uplift, req_margin=uplift, escape=True,
                fallback="daily escape-lane submission cap reached",
            )
        return _base(
            allowed=bool(ok),
            code="EVIDENCE_EMPTY_PASS" if ok else "EVIDENCE_EMPTY_INSUFFICIENT",
            level="none", uplift=uplift, req_margin=uplift,
            escape=True,
            fallback="no cell evidence; required max uncertainty uplift on model edge",
        )

    # -- Scored level: first *price-matched* level with adequate sample -------
    # Cross-price pooling mixes different cost bases (the 61c cohort's win
    # rate does not bound a 24c entry's EV), so only levels matching the
    # candidate's price bucket produce a posterior bound.  All other chain
    # levels inform that posterior through the leave-one-out parent prior.
    used_idx: Optional[int] = None
    for i, (_name, _agg) in enumerate(chain):
        if _name in _SCORED_LEVELS and _agg.n_eff >= min_cell_neff():
            used_idx = i
            break

    if used_idx is None:
        # No adequately-sampled price-matched evidence at any level.  The
        # uncertainty reserve is economic: the model's own net edge must
        # clear the max sparse uplift, and the pass is escape-lane only.
        uplift = sparse_uplift_max_c()
        ok = net_edge_cents is not None and float(net_edge_cents) >= uplift
        if ok and not escape_lane_enabled():
            return _base(
                allowed=False, code="ESCAPE_LANE_DISABLED", level="none",
                uplift=uplift, req_margin=uplift, escape=True,
                fallback="no adequately-sampled price-matched cell; escape lane disabled",
            )
        if ok and escape_cap_remaining() <= 0:
            return _base(
                allowed=False, code="ESCAPE_CAP_EXHAUSTED", level="none",
                uplift=uplift, req_margin=uplift, escape=True,
                fallback="daily escape-lane submission cap reached",
            )
        return _base(
            allowed=bool(ok),
            code="SPARSE_MATCHED_PASS" if ok else "SPARSE_MATCHED_INSUFFICIENT",
            level="none", uplift=uplift, req_margin=uplift, escape=True,
            fallback="no adequately-sampled price-matched cell; "
                     "required max uncertainty uplift on model edge",
        )

    used_name, used_agg = chain[used_idx]

    # Parent = nearest broader level, leave-one-out on the used level's cells.
    used_dims = _LEVEL_DIMS[used_name]
    parent_name, parent_agg = _find_loo_parent(
        chain, used_idx, used_dims, used_agg
    )

    alpha, bet, mean, lcb = _posterior(used_agg, parent_agg)
    std = _beta_std(alpha, bet)

    # Sparse-uncertainty uplift: keyed off the *exact* cell's effective n —
    # a dense pooled parent cannot clear the uncertainty reserve for a cell
    # that has never traded on its own.  Saturates below the "full" band.
    sparsity = max(0.0, 1.0 - exact_cell.n_eff / max(sparse_full_neff(), 1.0))
    uplift = sparse_uplift_max_c() * sparsity
    if stale:
        uplift = sparse_uplift_max_c()

    req_margin = margin_frac * 100.0 + uplift
    lcb_ev = (lcb - float(entry_price_cents) / 100.0 - float(fee_frac)) * 100.0

    # 2026-10-09: a stale artifact can never authorize production.  Any pass
    # on stale evidence is escape-lane only (bounded, separately capped).
    escape = exact_cell.n_eff < sparse_full_neff() or stale
    ok = lcb_ev >= req_margin

    def _escape_gate(ok_pass: bool, code_off: str, code_cap: str,
                     fb_off: str, fb_cap: str) -> Optional[EvidenceDecision]:
        """Shared bounded-lane gate for sparse/challenge/soft-penalty passes."""
        if not ok_pass:
            return None
        if not escape_lane_enabled():
            return _base(
                allowed=False, code=code_off,
                level=used_name, parent_level=parent_name,
                n_eff=used_agg.n_eff, w=used_agg.w, l=used_agg.l,
                n_raw=used_agg.n_raw, p_mean=mean, p_lcb=lcb, p_std=std,
                lcb_ev=lcb_ev, req_margin=req_margin, uplift=uplift,
                escape=True, fallback=fb_off,
            )
        if escape_cap_remaining() <= 0:
            return _base(
                allowed=False, code=code_cap,
                level=used_name, parent_level=parent_name,
                n_eff=used_agg.n_eff, w=used_agg.w, l=used_agg.l,
                n_raw=used_agg.n_raw, p_mean=mean, p_lcb=lcb, p_std=std,
                lcb_ev=lcb_ev, req_margin=req_margin, uplift=uplift,
                escape=True, fallback=fb_cap,
            )
        return None

    if ok:
        if escape:
            gated = _escape_gate(
                True, "ESCAPE_LANE_DISABLED", "ESCAPE_CAP_EXHAUSTED",
                "sparse cell requires escape lane; lane disabled",
                "daily escape-lane submission cap reached",
            )
            if gated is not None:
                return gated
        return _base(
            allowed=True, code="CELL_EVIDENCE_PASS",
            level=used_name, parent_level=parent_name,
            n_eff=used_agg.n_eff, w=used_agg.w, l=used_agg.l,
            n_raw=used_agg.n_raw, p_mean=mean, p_lcb=lcb, p_std=std,
            lcb_ev=lcb_ev, req_margin=req_margin, uplift=uplift,
            escape=escape,
            fallback=(
                None if used_idx == 0
                else f"exact cell sparse (n_eff={exact_cell.n_eff:.1f}); "
                     f"fell back to {used_name}"
            ),
        )

    # -- Adaptive states ----------------------------------------------------
    # The matched-cell posterior LCB cannot clear the required margin at the
    # current price.  Instead of an unconditional permanent block:
    #   CHALLENGE_ELIGIBLE - recent *matched* outcomes already contradict the
    #       stale-looking prior (recent win rate >= this entry's break-even).
    #       Admits a bounded trial: model net edge must clear the sparse
    #       uncertainty uplift; execution is escape-lane (post-only, 1
    #       contract, shared daily cap).
    #   SOFT_PENALTY - no contradiction, evidence merely insufficient.  Admits
    #       only when the model's own net edge clears an elevated reserve
    #       (margin + uplift + soft_penalty_extra), again through the lane.
    #   otherwise CELL_EVIDENCE_INSUFFICIENT - reject as before.
    if adaptive_states_enabled() and not stale:
        breakeven_wr = float(entry_price_cents) / 100.0 + float(fee_frac)
        rec_n, rec_wr = used_agg.recent_n, used_agg.recent_wr
        if (
            (rec_wr is None or rec_n < challenge_min_recent_n())
            and exact_cell.recent_n >= challenge_min_recent_n()
        ):
            rec_n, rec_wr = exact_cell.recent_n, exact_cell.recent_wr
        contradicts = (
            rec_wr is not None
            and rec_n >= challenge_min_recent_n()
            and rec_wr >= breakeven_wr
        )
        if contradicts:
            # The stale posterior disagrees, so the model must still clear the
            # ordinary all-in margin (base margin + uncertainty uplift) on its
            # own edge — the challenge is bounded, not free.
            ch_ok = (
                net_edge_cents is not None
                and float(net_edge_cents) >= req_margin
            )
            gated = _escape_gate(
                ch_ok, "CHALLENGE_LANE_DISABLED", "CHALLENGE_CAP_EXHAUSTED",
                "challenge lane requires escape lane; lane disabled",
                "daily escape-lane submission cap reached (challenge)",
            )
            if gated is not None:
                return gated
            return _base(
                allowed=bool(ch_ok),
                code="CHALLENGE_ELIGIBLE" if ch_ok else "CHALLENGE_INSUFFICIENT",
                level=used_name, parent_level=parent_name,
                n_eff=used_agg.n_eff, w=used_agg.w, l=used_agg.l,
                n_raw=used_agg.n_raw, p_mean=mean, p_lcb=lcb, p_std=std,
                lcb_ev=lcb_ev, req_margin=req_margin, uplift=uplift,
                escape=True,
                fallback=(
                    f"recent matched outcomes contradict prior "
                    f"(recent_wr={rec_wr:.2f} on n={rec_n} >= "
                    f"breakeven={breakeven_wr:.2f}); bounded challenge"
                ),
            )
        soft_req = margin_frac * 100.0 + uplift + soft_penalty_extra_c()
        soft_ok = (
            net_edge_cents is not None and float(net_edge_cents) >= soft_req
        )
        gated = _escape_gate(
            soft_ok, "SOFT_PENALTY_LANE_DISABLED", "ESCAPE_CAP_EXHAUSTED",
            "soft-penalty pass requires escape lane; lane disabled",
            "daily escape-lane submission cap reached",
        )
        if gated is not None:
            return gated
        return _base(
            allowed=bool(soft_ok),
            code="SOFT_PENALTY_PASS" if soft_ok else "SOFT_PENALTY_INSUFFICIENT",
            level=used_name, parent_level=parent_name,
            n_eff=used_agg.n_eff, w=used_agg.w, l=used_agg.l,
            n_raw=used_agg.n_raw, p_mean=mean, p_lcb=lcb, p_std=std,
            lcb_ev=lcb_ev, req_margin=soft_req, uplift=uplift,
            escape=True,
            fallback=(
                "matched cell LCB insufficient; model edge tested against "
                "elevated soft-penalty reserve"
            ),
        )

    return _base(
        allowed=False, code="CELL_EVIDENCE_INSUFFICIENT",
        level=used_name, parent_level=parent_name,
        n_eff=used_agg.n_eff, w=used_agg.w, l=used_agg.l,
        n_raw=used_agg.n_raw, p_mean=mean, p_lcb=lcb, p_std=std,
        lcb_ev=lcb_ev, req_margin=req_margin, uplift=uplift,
        escape=escape,
        fallback=(
            None if used_idx == 0
            else f"exact cell sparse (n_eff={exact_cell.n_eff:.1f}); "
                 f"fell back to {used_name}"
        ),
    )


# ---------------------------------------------------------------------------
# Artifact builder (shared by the audit-ledger refresh and offline replays)
# ---------------------------------------------------------------------------

def build_cells(
    rows: List[Dict[str, Any]],
    half_life_days: float,
    now: Optional[float] = None,
    recent_days: float = 14.0,
) -> Dict[str, Dict[str, Any]]:
    """Aggregate settled-entry rows into finest-grain cells.

    ``rows`` must carry: asset, side, ticker (or decision_id), entry_cents,
    settled_yes, settled_at, seconds_to_close.  Each row is weighted by
    exp(-ln2/H * age_days) and normalized inside its market so one ticker's
    total contribution is its newest observation's decay weight — repeated
    5-second evaluations of one market are ~1 effective sample, not n.

    Returns ``{cell_key: {w, l, n_eff, n_raw, n_markets, entry_wsum,
    recent_w, recent_l, recent_n}}``.
    """
    now = time.time() if now is None else float(now)
    half = math.log(2.0) / max(float(half_life_days), 0.25)
    rows_by_market: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        entry_cents = row.get("entry_cents")
        if entry_cents is None or not (0 < int(entry_cents) <= 100):
            continue
        mkey = str(row.get("ticker") or row.get("decision_id") or id(row))
        rows_by_market.setdefault(mkey, []).append(row)

    cells: Dict[str, Dict[str, Any]] = {}
    for mkey, mrows in rows_by_market.items():
        decays = [
            math.exp(
                -half * max(0.0, now - float(r.get("settled_at") or now)) / 86400.0
            )
            for r in mrows
        ]
        tot = sum(decays) or 1.0
        mweight = max(decays)
        for r, dec in zip(mrows, decays):
            entry_cents = float(r["entry_cents"])
            asset = (str(r.get("asset") or "").upper()) or "UNKNOWN"
            side = str(r.get("side") or "").lower()
            won = 1.0 if ((side == "yes") == bool(r.get("settled_yes"))) else 0.0
            rw = dec * mweight / tot
            ck = cell_key(asset, side, entry_cents, r.get("seconds_to_close"))
            c = cells.setdefault(
                ck,
                {"w": 0.0, "l": 0.0, "n_eff": 0.0, "n_raw": 0,
                 "_markets": set(), "entry_wsum": 0.0,
                 "recent_w": 0.0, "recent_l": 0.0, "recent_n": 0},
            )
            c["w"] += rw * won
            c["l"] += rw * (1.0 - won)
            c["n_eff"] += rw
            c["n_raw"] += 1
            c["_markets"].add(mkey)
            c["entry_wsum"] += rw * entry_cents
            if now - float(r.get("settled_at") or now) <= recent_days * 86400.0:
                c["recent_w"] += won
                c["recent_l"] += 1.0 - won
                c["recent_n"] += 1

    return {
        k: {
            kk: (round(vv, 4) if isinstance(vv, float) else vv)
            for kk, vv in c.items()
            if kk != "_markets"
        } | {"n_markets": len(c["_markets"])}
        for k, c in cells.items()
    }


# ---------------------------------------------------------------------------
# Multi-horizon decayed-evidence report (diagnostic)
# ---------------------------------------------------------------------------

def decayed_evidence_report(
    evidence: Dict[str, Any],
    asset: str,
    side: str,
    entry_price_cents: Optional[float],
    tte_seconds: Optional[float],
    fee_frac: float = 0.0,
) -> Dict[str, Any]:
    """Per-horizon matched-cohort posterior for telemetry.

    w(d) = 2**(-d/H) is already applied at artifact build time; the artifact
    stores one cell table per half-life variant (H=7 responsive view,
    H=21 stable view).  This report re-aggregates the finest-grain cohort
    (asset x side x price-bucket x TTE-bucket) under each variant so a
    soft-override record can show whether the recent regime agrees with the
    stable prior.  ``*_raw`` columns are the undecayed observation counts —
    the full-history diagnostic view.

    Diagnostic only: a drifted hard block is an operator-review item, never
    an auto-downgrade — ``drift_score`` informs review, it does not flip a
    MATCHING_TOXIC_CELL into a soft verdict.
    """
    variants = evidence.get("cells")
    if not isinstance(variants, dict) or not variants:
        return {}
    pb = price_bucket(entry_price_cents)
    tb = tte_bucket(tte_seconds)
    out: Dict[str, Any] = {}
    for hkey in ("7", "21"):
        sub = variants.get(hkey)
        if not isinstance(sub, dict):
            continue
        agg = aggregate_at_level(
            sub, asset, side, pb, tb, _HIERARCHY[0][1]
        )
        # Leave-one-out parent = asset x side level minus the exact cohort.
        broad = aggregate_at_level(
            sub, asset, side, pb, tb, ("asset", "side")
        ).minus(agg)
        alpha, bet, mean, lcb = _posterior(agg, broad)
        out[f"h{hkey}_n_eff"] = round(agg.n_eff, 3)
        out[f"h{hkey}_n_raw"] = agg.n_raw
        out[f"h{hkey}_wr"] = round(mean, 4)
        out[f"h{hkey}_lcb_wr"] = round(lcb, 4)
        if entry_price_cents is not None:
            out[f"h{hkey}_lcb_ev_cents"] = round(
                (lcb - float(entry_price_cents) / 100.0 - float(fee_frac))
                * 100.0,
                3,
            )
    # User-facing aliases: historical = stable (H21) view, recent = H7.
    if "h21_n_eff" in out:
        out["historical_prior_n_eff"] = out["h21_n_eff"]
        out["historical_lcb"] = out.get("h21_lcb_ev_cents")
    if "h7_n_eff" in out:
        out["recent_n_eff"] = out["h7_n_eff"]
        out["recent_lcb"] = out.get("h7_lcb_ev_cents")
    if out.get("recent_lcb") is not None and out.get("historical_lcb") is not None:
        out["drift_score"] = round(out["recent_lcb"] - out["historical_lcb"], 3)
    return out


# ---------------------------------------------------------------------------
# Escape-lane daily cap (durable one-line counter)
# ---------------------------------------------------------------------------

def escape_fills_today(path: Optional[str] = None, now: Optional[float] = None) -> int:
    """Escape-lane submissions recorded for the current UTC day."""
    now = time.time() if now is None else float(now)
    day = datetime.fromtimestamp(now, tz=timezone.utc).date().isoformat()
    try:
        with open(path or escape_state_path(), "r", encoding="utf-8") as f:
            rec = json.load(f)
        if rec.get("date") == day:
            return int(rec.get("count") or 0)
    except Exception:
        pass
    return 0


def escape_cap_remaining(path: Optional[str] = None, now: Optional[float] = None) -> int:
    return max(0, escape_daily_max() - escape_fills_today(path, now))


def record_escape_submission(
    path: Optional[str] = None, now: Optional[float] = None
) -> int:
    """Increment today's escape-lane submission counter; returns new count.

    Atomic-enough for a single writer: read-modify-write under a small tmp
    rename.  Counting submissions (not fills) is the stricter bound; a
    post-only order that never fills still consumes the slot.
    """
    now = time.time() if now is None else float(now)
    p = path or escape_state_path()
    day = datetime.fromtimestamp(now, tz=timezone.utc).date().isoformat()
    count = escape_fills_today(p, now) + 1
    try:
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(json.dumps({"date": day, "count": count}))
        os.replace(tmp, p)
    except Exception:
        pass
    return count
