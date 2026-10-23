"""Loss functions, comparators, and walk-forward fitted forecasts.

Comparators (all probabilities in canonical YES space)
------------------------------------------------------
- ``const_half``: 0.5 always.
- ``base_rate``: per-asset expanding mean of official outcomes with label
  availability strictly before the unit's target timestamp.
- ``mkt_cal`` (q0): ``logit(q0) = a + b * logit(m)`` fit on past units of
  the SAME horizon, expanding-window walk-forward per fold.
- ``mkt_plus_sig`` (q1): ``logit(q1) = a + b * logit(m) + g * z`` with
  ``z = logit(r) - logit(m)`` (r = pre-anchor probability). Same fitting
  discipline as q0. This is the incremental-information comparator.
- ``raw`` / ``anch_wf`` / ``final`` / ``mid``: pass-through stages.

Fitted comparators use only units whose LABEL was available before the
fold boundary (``label_ts < fold_start``). A unit whose label was not yet
available can never enter its own fit — earlier horizons of the same
contract share the contract's label, so they are excluded automatically.

Logistic fits are plain Newton-IRLS (numpy only): deterministic, no
regularization beyond a 1e-8 diagonal jitter, and the returned covariance
supplies standard errors for the residual coefficient diagnostic.
"""

from __future__ import annotations

import math
from bisect import bisect_left
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from .records import LabelVersion, OfficialOutcomes
from .units import EvalUnit, LABEL_AVAILABILITY_GRACE_S

CLIP_EPS = 1e-6
LOGIT_EPS = 1e-6

# Historical-training label policies (scoring always uses the final label).
LABEL_POLICY_OBSERVED = "observed_only"  # only documented observed_at_utc
LABEL_POLICY_GRACE = "grace"             # + settlement_ts + grace fallback


def version_availability(
    v: LabelVersion, policy: str
) -> Tuple[Optional[float], Optional[str]]:
    """(availability_ts, kind) for one label version under ``policy``.

    ``observed`` = documented export observation time; ``assumed`` =
    settlement_ts + grace (available only under the grace policy).
    """
    if v.observed_ts is not None:
        return v.observed_ts, "observed"
    if policy == LABEL_POLICY_GRACE and v.settlement_ts is not None:
        return v.settlement_ts + LABEL_AVAILABILITY_GRACE_S, "assumed"
    return None, None


def training_label_at(
    unit: EvalUnit, boundary_ts: float, policy: str
) -> Tuple[Optional[int], Optional[float], Optional[str]]:
    """The label version known at ``boundary_ts`` under ``policy``.

    Returns (y, avail_ts, kind) for the LATEST version whose availability
    precedes the boundary, or (None, None, reason) when no version qualifies.
    A correction published after the boundary never leaks backward.
    """
    best: Optional[Tuple[float, int, str]] = None
    any_undated = False
    for v in unit.label_versions:
        avail, kind = version_availability(v, policy)
        if avail is None:
            any_undated = True
            continue
        if avail < boundary_ts and (best is None or avail > best[0]):
            best = (avail, v.resolved_yes, kind)
    if best is not None:
        return best[1], best[0], best[2]
    return None, None, "no_available_version" if not any_undated else "undated_only"


def logit(p: float) -> float:
    p = min(max(float(p), LOGIT_EPS), 1.0 - LOGIT_EPS)
    return math.log(p / (1.0 - p))


def sigmoid(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    e = math.exp(x)
    return e / (1.0 + e)


def clip01(p: float, eps: float = CLIP_EPS) -> float:
    return min(max(float(p), eps), 1.0 - eps)


def brier(p: float, y: int) -> float:
    return (float(p) - float(y)) ** 2


def logloss(p: float, y: int, eps: float = CLIP_EPS) -> float:
    pc = clip01(p, eps)
    return -(float(y) * math.log(pc) + (1.0 - float(y)) * math.log(1.0 - pc))


LOSSES = {"brier": brier, "logloss": logloss}


def is_extreme_prob(p: float, eps: float = CLIP_EPS) -> bool:
    return p <= eps or p >= 1.0 - eps


# ---------------------------------------------------------------------------
# IRLS logistic regression
# ---------------------------------------------------------------------------

@dataclass
class LogisticFit:
    coef: np.ndarray
    cov: np.ndarray
    converged: bool
    n: int
    iterations: int

    def predict(self, x: Sequence[float]) -> float:
        return sigmoid(float(np.dot(self.coef, np.asarray(x, dtype=float))))

    @property
    def se(self) -> np.ndarray:
        return np.sqrt(np.maximum(np.diag(self.cov), 0.0))


def irls_logistic(
    X: np.ndarray,
    y: np.ndarray,
    *,
    max_iter: int = 60,
    tol: float = 1e-10,
    ridge: float = 1e-8,
) -> LogisticFit:
    """Newton-IRLS logistic regression.

    X: (n, k) design matrix (caller includes the intercept column).
    y: (n,) binary outcomes.
    """
    X = np.asarray(X, dtype=float)
    y = np.asarray(y, dtype=float)
    n, k = X.shape
    beta = np.zeros(k)
    converged = False
    it = 0
    xtwx_inv = np.eye(k)
    for it in range(1, max_iter + 1):
        eta = X @ beta
        # Numerically stable sigmoid
        mu = 1.0 / (1.0 + np.exp(-np.clip(eta, -35.0, 35.0)))
        w = np.maximum(mu * (1.0 - mu), 1e-9)
        grad = X.T @ (y - mu)
        xtwx = (X.T * w) @ X + ridge * np.eye(k)
        try:
            xtwx_inv = np.linalg.inv(xtwx)
        except np.linalg.LinAlgError:
            break
        step = xtwx_inv @ grad
        beta = beta + step
        if np.max(np.abs(step)) < tol:
            converged = True
            break
    return LogisticFit(coef=beta, cov=xtwx_inv, converged=converged, n=n, iterations=it)


# ---------------------------------------------------------------------------
# Comparator forecasts
# ---------------------------------------------------------------------------

STAGE_KEYS = ("const_half", "base_rate", "mid", "raw", "anch_wf", "final", "q0", "q1")


@dataclass
class FoldPlan:
    """Equal-time folds over target_ts. fold_of[i] -> index or None when the
    unit is excluded from fitted-comparator evaluation (insufficient train)."""

    boundaries: List[float]
    fold_of: Dict[int, int]
    train_n: Dict[Tuple[float, int], int]


def build_fold_plan(
    units: List[EvalUnit],
    *,
    n_folds: int,
    min_train_n: int,
    label_policy: str = LABEL_POLICY_OBSERVED,
) -> FoldPlan:
    """Assign each unit to an equal-time fold and compute the size of its
    label-available training set (same horizon only).

    The training set for fold k is every same-horizon unit with a label
    version available before ``boundary[k]`` under ``label_policy``.
    """
    boundaries: List[float] = []
    fold_of: Dict[int, int] = {}
    train_n: Dict[Tuple[float, int], int] = {}
    if n_folds < 1 or not units:
        return FoldPlan(boundaries, fold_of, train_n)

    targets = [u.target_ts for u in units]
    lo, hi = min(targets), max(targets)
    if hi <= lo:
        boundaries = [lo, hi + 1.0]
        n_folds = 1
    else:
        boundaries = list(np.linspace(lo, hi, n_folds + 1))

    by_horizon: Dict[float, List[int]] = {}
    for i, u in enumerate(units):
        by_horizon.setdefault(u.horizon_s, []).append(i)

    for h, idxs in by_horizon.items():
        for i in idxs:
            u = units[i]
            f = int(np.searchsorted(boundaries, u.target_ts, side="right") - 1)
            f = min(max(f, 0), len(boundaries) - 2)
            fold_of[i] = f
        for f in range(len(boundaries) - 1):
            b = boundaries[f]
            n = sum(
                1
                for i in idxs
                if training_label_at(units[i], b, label_policy)[0] is not None
            )
            train_n[(h, f)] = n
    return FoldPlan(boundaries, fold_of, train_n)


@dataclass
class FittedForecast:
    p_q0: Optional[float] = None
    p_q1: Optional[float] = None
    train_n_q0: int = 0
    train_n_q1: int = 0
    gamma: Optional[float] = None
    gamma_se: Optional[float] = None
    q0_converged: Optional[bool] = None
    q1_converged: Optional[bool] = None


def compute_fitted_forecasts(
    units: List[EvalUnit],
    plan: FoldPlan,
    *,
    n_folds: int,
    min_train_n: int,
    label_policy: str = LABEL_POLICY_OBSERVED,
) -> Tuple[Dict[int, FittedForecast], Dict[str, Dict[str, Any]]]:
    """Per-horizon expanding-window fits for q0 and q1.

    For each fold boundary, one model per horizon is fit on all units whose
    label VERSION was available before that boundary under ``label_policy``
    (``training_label_at``), then applied to the units in that fold. Units
    in folds with < ``min_train_n`` training labels get ``p_q0 = p_q1 =
    None`` — counted as ``insufficient_train`` coverage. No silent fallback:
    under ``observed_only``, labels without documented availability are
    excluded even when a final label exists for scoring.

    Returns (fitted, fold_stats): fold_stats[horizon][fold] carries the
    availability accounting per spec — observed / assumed / excluded and
    the latest training-label availability timestamp.
    """
    out: Dict[int, FittedForecast] = {}
    fold_stats: Dict[str, Dict[str, Any]] = {}
    if not plan.boundaries:
        return out, fold_stats

    by_horizon: Dict[float, List[int]] = {}
    for i, u in enumerate(units):
        by_horizon.setdefault(u.horizon_s, []).append(i)

    for h, idxs in by_horizon.items():
        h_stats: Dict[str, Any] = {}
        for f in range(len(plan.boundaries) - 1):
            b = plan.boundaries[f]
            train_idx: List[int] = []
            train_y: List[int] = []
            n_obs = 0
            n_assumed = 0
            n_excluded = 0
            latest_avail: Optional[float] = None
            for i in idxs:
                if units[i].m_mid is None:
                    continue
                ty, tavail, tkind = training_label_at(units[i], b, label_policy)
                if ty is None:
                    n_excluded += 1
                    continue
                train_idx.append(i)
                train_y.append(ty)
                if tkind == "observed":
                    n_obs += 1
                else:
                    n_assumed += 1
                if tavail is not None and (latest_avail is None or tavail > latest_avail):
                    latest_avail = tavail
            train_idx_q1 = [i for i in train_idx if units[i].p_raw is not None]
            q1_pos = {i: k for k, i in enumerate(train_idx)}
            fit0: Optional[LogisticFit] = None
            fit1: Optional[LogisticFit] = None
            if len(train_idx) >= min_train_n:
                X0 = np.array([[1.0, logit(units[i].m_mid)] for i in train_idx])
                yv = np.array(train_y, dtype=float)
                fit0 = irls_logistic(X0, yv)
            if len(train_idx_q1) >= min_train_n:
                X1 = np.array([
                    [1.0, logit(units[i].m_mid),
                     logit(units[i].p_raw) - logit(units[i].m_mid)]
                    for i in train_idx_q1
                ])
                yv1 = np.array([train_y[q1_pos[i]] for i in train_idx_q1], dtype=float)
                fit1 = irls_logistic(X1, yv1)
            h_stats[f"fold_{f}"] = {
                "boundary_ts": b,
                "train_n": len(train_idx),
                "train_labels_observed": n_obs,
                "train_labels_assumed": n_assumed,
                "train_labels_excluded_no_availability": n_excluded,
                "latest_train_label_avail_ts": latest_avail,
            }

            for i in idxs:
                if plan.fold_of.get(i) != f:
                    continue
                u = units[i]
                rec = FittedForecast(
                    train_n_q0=len(train_idx),
                    train_n_q1=len(train_idx_q1),
                )
                if fit0 is not None and u.m_mid is not None:
                    rec.p_q0 = fit0.predict([1.0, logit(u.m_mid)])
                    rec.q0_converged = fit0.converged
                if fit1 is not None and u.m_mid is not None and u.p_raw is not None:
                    z = logit(u.p_raw) - logit(u.m_mid)
                    rec.p_q1 = fit1.predict([1.0, logit(u.m_mid), z])
                    rec.gamma = float(fit1.coef[2])
                    rec.gamma_se = float(fit1.se[2]) if fit1.se.size > 2 else None
                    rec.q1_converged = fit1.converged
                out[i] = rec
        fold_stats[f"horizon_{int(h)}s"] = h_stats
    return out, fold_stats


def compute_base_rates(
    units: List[EvalUnit],
    official: OfficialOutcomes,
    label_policy: str = LABEL_POLICY_OBSERVED,
) -> Dict[int, float]:
    """Per-asset expanding base rate over OFFICIAL outcomes.

    For unit u the base rate is the mean of each ticker's label AS OF
    ``u.target_ts`` under ``label_policy`` — corrections after the target do
    not leak backward. Contract-level (one label per ticker), never
    unit-level, so horizon coverage cannot weight it.
    """
    # Per-asset event streams: (avail_ts, ticker, y). A correction re-dates
    # the ticker's current label; prefix sums over the sum of current labels
    # give the as-of mean at any query time.
    events_by_asset: Dict[str, List[Tuple[float, str, int]]] = {}
    for ticker, o in official.by_ticker.items():
        asset = o.asset
        if asset is None:
            from .records import asset_from_ticker
            asset = asset_from_ticker(ticker)
        if asset is None:
            continue
        for v in o.versions:
            avail, _kind = version_availability(v, label_policy)
            if avail is None:
                continue
            events_by_asset.setdefault(asset, []).append((avail, ticker, v.resolved_yes))

    # Build per-asset prefix (ts, sum_of_current_labels, n_labeled_tickers).
    pref_ts: Dict[str, List[float]] = {}
    pref_sum: Dict[str, List[float]] = {}
    pref_n: Dict[str, List[int]] = {}
    for a, evs in events_by_asset.items():
        evs.sort(key=lambda e: (e[0], e[1]))
        cur: Dict[str, int] = {}
        ts_l, sum_l, n_l = [], [], []
        run_sum = 0.0
        for ts, tk, y in evs:
            if tk in cur:
                run_sum += y - cur[tk]
            else:
                run_sum += y
            cur[tk] = y
            ts_l.append(ts)
            sum_l.append(run_sum)
            n_l.append(len(cur))
        pref_ts[a], pref_sum[a], pref_n[a] = ts_l, sum_l, n_l

    out: Dict[int, float] = {}
    for i, u in enumerate(units):
        ts = pref_ts.get(u.asset)
        if not ts:
            continue
        k = bisect_left(ts, u.target_ts)
        if k == 0 or pref_n[u.asset][k - 1] == 0:
            continue
        out[i] = pref_sum[u.asset][k - 1] / pref_n[u.asset][k - 1]
    return out


def stage_probability(
    unit: EvalUnit,
    stage: str,
    fitted: Optional[FittedForecast],
    base_rate: Optional[float],
) -> Optional[float]:
    if stage == "const_half":
        return 0.5
    if stage == "base_rate":
        return base_rate
    if stage == "mid":
        return unit.m_mid
    if stage == "raw":
        return unit.p_raw
    if stage == "anch_wf":
        return unit.p_anch_wf
    if stage == "final":
        return unit.p_final
    if stage == "q0":
        return fitted.p_q0 if fitted else None
    if stage == "q1":
        return fitted.p_q1 if fitted else None
    raise KeyError(stage)
