"""Probability calibration diagnostics (ECE, Brier, reliability curve).

These utilities are intentionally dependency-light (no scikit-learn/plotting)
and are used by both the offline calibration script and release-gate tests to
verify that a per-side tail calibration produces reliable probabilities.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Dict, List, Optional, Tuple


def brier_score(probs: List[float], outcomes: List[int]) -> Optional[float]:
    """Return the Brier score (mean squared error) for a set of predictions.

    ``outcomes`` are 0/1 win/loss labels in the same probability space as
    ``probs`` (i.e., for a NO-held contract, ``probs`` are p_no and outcomes are
    1 when NO settles).
    """
    if not probs or not outcomes or len(probs) != len(outcomes):
        return None
    n = len(probs)
    return sum((p - float(o)) ** 2 for p, o in zip(probs, outcomes)) / n


def _bin_indices(probs: List[float], n_bins: int) -> List[int]:
    """Assign each probability to a quantile-spaced bin."""
    sorted_probs = sorted(probs)
    if n_bins > len(sorted_probs):
        n_bins = max(1, len(sorted_probs))
    if n_bins == 1:
        return [0] * len(probs)
    # Quantile-based bin edges (same number of samples per bin when possible).
    edges: List[float] = [sorted_probs[0]]
    for i in range(1, n_bins):
        idx = int(round(i * len(sorted_probs) / n_bins))
        idx = max(0, min(len(sorted_probs) - 1, idx))
        edges.append(sorted_probs[idx])
    edges.append(sorted_probs[-1] + 1e-12)

    indices = []
    for p in probs:
        for i, (lo, hi) in enumerate(zip(edges[:-1], edges[1:])):
            if lo <= p < hi or (i == n_bins - 1 and lo <= p <= hi):
                indices.append(i)
                break
        else:
            indices.append(n_bins - 1)
    return indices


def reliability_curve(
    probs: List[float],
    outcomes: List[int],
    n_bins: int = 10,
) -> Tuple[List[float], List[float], List[int]]:
    """Return (bin_center, observed_rate, count) for a reliability diagram.

    Uses quantile-spaced bins so each bin has comparable support.
    """
    if not probs or not outcomes or len(probs) != len(outcomes):
        return [], [], []

    n_bins = max(1, min(n_bins, len(probs)))
    bin_idx = _bin_indices(probs, n_bins)
    bins: Dict[int, List[Tuple[float, int]]] = defaultdict(list)
    for i, (p, o) in enumerate(zip(probs, outcomes)):
        bins[bin_idx[i]].append((p, o))

    centers: List[float] = []
    observed: List[float] = []
    counts: List[int] = []
    for i in sorted(bins):
        entries = bins[i]
        pred = [p for p, _ in entries]
        outs = [o for _, o in entries]
        centers.append(sum(pred) / len(pred))
        observed.append(sum(outs) / len(outs))
        counts.append(len(entries))
    return centers, observed, counts


def expected_calibration_error(
    probs: List[float],
    outcomes: List[int],
    n_bins: int = 10,
) -> Optional[float]:
    """Compute Expected Calibration Error as the weighted average gap between
    bin-averaged predicted and observed probabilities.
    """
    if not probs or not outcomes or len(probs) != len(outcomes):
        return None

    centers, observed, counts = reliability_curve(probs, outcomes, n_bins)
    if not centers:
        return None
    total = sum(counts)
    if total == 0:
        return None
    return sum(abs(c - o) * n for c, o, n in zip(centers, observed, counts)) / total


def calibration_summary(
    probs: List[float],
    outcomes: List[int],
    n_bins: int = 10,
    label: str = "",
) -> Dict[str, float]:
    """Return a dict with Brier, ECE, and max absolute calibration gap.

    ``probs`` must already be in the correct side space (p_yes or p_no).
    """
    brier = brier_score(probs, outcomes)
    ece = expected_calibration_error(probs, outcomes, n_bins)
    centers, observed, counts = reliability_curve(probs, outcomes, n_bins)
    max_gap = max((abs(c - o) for c, o in zip(centers, observed)), default=0.0)
    return {
        "label": label,
        "n_samples": len(probs),
        "brier_score": brier if brier is not None else math.nan,
        "expected_calibration_error": ece if ece is not None else math.nan,
        "max_calibration_gap": max_gap,
        "n_bins": n_bins,
        "bin_centers": centers,
        "bin_observed_rates": observed,
        "bin_counts": counts,
    }


def evaluate_tail_calibrator_both_sides(
    yes_held_prices: List[float],
    yes_outcomes: List[int],
    no_held_prices: List[float],
    no_outcomes: List[int],
    n_bins: int = 5,
) -> Dict[str, Dict[str, float]]:
    """Compute YES and NO calibration summaries for a held-out test set.

    ``yes_outcomes`` are 1 when YES settles; ``no_outcomes`` are 1 when NO
    settles.  ``*_held_prices`` are the market prices paid for the held side.
    """
    return {
        "yes": calibration_summary(
            yes_held_prices, yes_outcomes, n_bins=n_bins, label="yes_held_price"
        ),
        "no": calibration_summary(
            no_held_prices, no_outcomes, n_bins=n_bins, label="no_held_price"
        ),
    }
