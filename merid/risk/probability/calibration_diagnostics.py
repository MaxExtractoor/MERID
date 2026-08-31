"""Probability calibration diagnostics (ECE, Brier, reliability curve, AUC).

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


def roc_auc_score(probs: List[float], outcomes: List[int]) -> Optional[float]:
    """Compute the area under the ROC curve using the Mann-Whitney U statistic.

    ``probs`` are predicted probabilities of the positive class; ``outcomes``
    are 0/1.  Ties use the standard correction where pairs with equal
    probabilities contribute 0.5.  Returns ``None`` for degenerate input
    (empty, single class, or len mismatch).
    """
    if not probs or not outcomes or len(probs) != len(outcomes):
        return None
    if len(probs) < 2:
        return None

    n_pos = sum(outcomes)
    n_neg = len(outcomes) - n_pos
    if n_pos == 0 or n_neg == 0:
        return None

    # Sort ascending; higher probabilities should get larger ranks.
    sorted_idx = sorted(range(len(probs)), key=lambda i: probs[i])
    sorted_probs = [probs[i] for i in sorted_idx]
    sorted_outs = [outcomes[i] for i in sorted_idx]

    # Average ranks for ties.
    ranks: List[float] = []
    i = 0
    n = len(sorted_probs)
    while i < n:
        j = i + 1
        while j < n and sorted_probs[j] == sorted_probs[i]:
            j += 1
        # indices i..j-1 have the same probability.
        avg_rank = (i + 1 + j) / 2.0  # 1-indexed rank average
        for _ in range(i, j):
            ranks.append(avg_rank)
        i = j

    sum_pos_ranks = sum(r for r, o in zip(ranks, sorted_outs) if o == 1)
    # Mann-Whitney U = sum_pos_ranks - n_pos*(n_pos+1)/2
    # AUC = U / (n_pos * n_neg)
    return (sum_pos_ranks - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)


def murphy_decomposition(
    probs: List[float], outcomes: List[int], n_bins: int = 10
) -> Dict[str, Optional[float]]:
    """Return the Murphy Brier decomposition (reliability, resolution, uncertainty).

    ``reliability`` measures calibration misfit within bins.
    ``resolution`` measures how much the bin rates vary from the base rate.
    ``uncertainty`` is the base-rate variance (irreducible error).
    The signed identity is ``brier = reliability - resolution + uncertainty``.
    """
    if not probs or not outcomes or len(probs) != len(outcomes):
        return {"reliability": None, "resolution": None, "uncertainty": None}

    n = len(outcomes)
    overall_rate = sum(outcomes) / n
    uncertainty = overall_rate * (1.0 - overall_rate)

    centers, observed, counts = reliability_curve(probs, outcomes, n_bins)
    total = sum(counts)
    if total == 0:
        return {"reliability": None, "resolution": None, "uncertainty": uncertainty}

    reliability = sum(c * (c - o) ** 2 for c, o, ccount in zip(centers, observed, counts)) / total
    resolution = sum(ccount * (o - overall_rate) ** 2 for o, ccount in zip(observed, counts)) / total
    return {
        "reliability": reliability,
        "resolution": resolution,
        "uncertainty": uncertainty,
    }


def calibration_summary(
    probs: List[float],
    outcomes: List[int],
    n_bins: int = 10,
    label: str = "",
) -> Dict[str, float]:
    """Return a dict with Brier, ECE, AUC, and Murphy decomposition.

    ``probs`` must already be in the correct side space (p_yes or p_no).
    """
    brier = brier_score(probs, outcomes)
    ece = expected_calibration_error(probs, outcomes, n_bins)
    centers, observed, counts = reliability_curve(probs, outcomes, n_bins)
    max_gap = max((abs(c - o) for c, o in zip(centers, observed)), default=0.0)
    auc = roc_auc_score(probs, outcomes)
    murphy = murphy_decomposition(probs, outcomes, n_bins)
    return {
        "label": label,
        "n_samples": len(probs),
        "brier_score": brier if brier is not None else math.nan,
        "expected_calibration_error": ece if ece is not None else math.nan,
        "max_calibration_gap": max_gap,
        "auc_roc": auc if auc is not None else math.nan,
        "reliability": murphy["reliability"] if murphy["reliability"] is not None else math.nan,
        "resolution": murphy["resolution"] if murphy["resolution"] is not None else math.nan,
        "uncertainty": murphy["uncertainty"] if murphy["uncertainty"] is not None else math.nan,
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
