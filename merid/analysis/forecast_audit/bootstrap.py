"""Paired contiguous-block bootstrap for forecast-loss comparisons.

Design
------
- Blocks are contiguous wall-clock intervals on contract ``close_ts``:
  ``block_id = floor(close_ts / L)``. Every horizon of a contract shares
  its close, so contract-linked observations stay together; all five
  assets' contracts closing in the same interval share the block, so
  cross-asset simultaneity is preserved.
- Resampling uses a multinomial weight vector ``w ~ Multinomial(B, 1/B)``
  per draw — exactly equivalent to resampling B blocks with replacement —
  and the SAME weight vector is applied to every comparison, so paired
  draws stay aligned.
- Two statistics are recomputed inside every draw:
    * loss-difference mean:  mean(L_base - L_cand)  (positive favors cand)
    * Brier skill:           1 - BS_cand / BS_base
  The BSS interval is obtained by recomputing the ratio per draw, never by
  attaching an interval to the numerator.

Inference target: resampling frozen evaluation predictions quantifies
uncertainty in their observed performance. It does not account for model
training/selection uncertainty upstream of the ledger.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

import numpy as np


@dataclass
class CompBlocks:
    """Per-block aggregates for one (candidate, baseline) comparison on the
    comparison's common support."""

    n: np.ndarray       # unit counts per block
    sum_d: np.ndarray   # sum of (L_base - L_cand) per block
    sum_c: np.ndarray   # sum of candidate losses per block
    sum_b: np.ndarray   # sum of baseline losses per block


@dataclass
class BootstrapResult:
    n_units: int
    n_blocks_used: int
    point_mean_d: Optional[float]
    point_bs_cand: Optional[float]
    point_bs_base: Optional[float]
    point_bss: Optional[float]
    draw_mean_d: Optional[float]
    ci_d: Optional[tuple]
    draw_mean_bss: Optional[float]
    ci_bss: Optional[tuple]
    replicates: int
    seed: int
    # Replicate accounting (per spec: distinguish empty support from
    # undefined-skill draws; a zero-baseline draw still contributes to the
    # loss-difference interval).
    n_requested_draws: int = 0
    n_valid_loss_draws: int = 0
    n_empty_support_draws: int = 0
    n_valid_skill_draws: int = 0
    n_zero_baseline_loss_draws: int = 0


def shared_draws(n_blocks: int, replicates: int, seed: int) -> np.ndarray:
    """The (replicates, n_blocks) block-multiplicity matrix shared by every
    comparison. Resampling B blocks with replacement == multinomial(B, 1/B)
    block weights. Exposed so tests can drive a reference implementation
    over the IDENTICAL draws."""
    rng = np.random.default_rng(seed)
    probs = np.full(n_blocks, 1.0 / n_blocks)
    return rng.multinomial(n_blocks, probs, size=replicates).astype(np.float64)


def make_comp_blocks(
    block_of_unit: np.ndarray,
    support_idx: Sequence[int],
    d: np.ndarray,
    loss_c: np.ndarray,
    loss_b: np.ndarray,
    n_blocks: int,
) -> CompBlocks:
    """Aggregate per-unit paired losses into per-block sums."""
    b_idx = np.array(
        [int(block_of_unit[i]) for i in support_idx], dtype=np.int64)
    keep = b_idx >= 0  # no-close units are never valid support
    b_idx = b_idx[keep]
    d = np.asarray(d)[keep]
    loss_c = np.asarray(loss_c)[keep]
    loss_b = np.asarray(loss_b)[keep]
    n = np.bincount(b_idx, minlength=n_blocks).astype(np.int64)
    sum_d = np.bincount(b_idx, weights=d, minlength=n_blocks)
    sum_c = np.bincount(b_idx, weights=loss_c, minlength=n_blocks)
    sum_b = np.bincount(b_idx, weights=loss_b, minlength=n_blocks)
    return CompBlocks(n=n, sum_d=sum_d, sum_c=sum_c, sum_b=sum_b)


def _pct(samples: np.ndarray, q: float) -> float:
    return float(np.percentile(samples, q))


def paired_bootstrap(
    comps: Dict[str, CompBlocks],
    *,
    replicates: int,
    seed: int,
    ci: float = 0.95,
) -> Dict[str, BootstrapResult]:
    """Run the shared-draw block bootstrap over all comparisons.

    ``comps`` maps comparison name -> CompBlocks. Every comparison must have
    been built against the same block universe (array lengths equal).
    """
    if not comps:
        return {}
    n_blocks = len(next(iter(comps.values())).n)
    for name, c in comps.items():
        if len(c.n) != n_blocks:
            raise ValueError(
                f"block universe mismatch: {name} has {len(c.n)} blocks, "
                f"expected {n_blocks}")
    if n_blocks == 0 or replicates < 1:
        # Empty block universe: every comparison gets an explicit empty
        # result — never a crash on np.full(0, 1/0) or an empty multinomial.
        return {
            name: BootstrapResult(
                n_units=int(c.n.sum()), n_blocks_used=0,
                point_mean_d=None, point_bs_cand=None, point_bs_base=None,
                point_bss=None, draw_mean_d=None, ci_d=None,
                draw_mean_bss=None, ci_bss=None,
                replicates=replicates, seed=seed,
                n_requested_draws=int(replicates),
                n_empty_support_draws=int(replicates))
            for name, c in comps.items()
        }

    # (R, n_blocks) block-multiplicity draws; one matrix shared by all comps.
    draws = shared_draws(n_blocks, replicates, seed)

    alpha = (1.0 - ci) / 2.0
    lo_q, hi_q = 100.0 * alpha, 100.0 * (1.0 - alpha)
    results: Dict[str, BootstrapResult] = {}

    for name, cb in comps.items():
        denom = draws @ cb.n.astype(np.float64)
        valid = denom > 0
        mean_d = np.full(replicates, np.nan)
        bs_c = np.full(replicates, np.nan)
        bs_b = np.full(replicates, np.nan)
        bss = np.full(replicates, np.nan)
        if valid.any():
            dsum = draws @ cb.sum_d
            csum = draws @ cb.sum_c
            bsum = draws @ cb.sum_b
            mean_d[valid] = dsum[valid] / denom[valid]
            bs_c[valid] = csum[valid] / denom[valid]
            bs_b[valid] = bsum[valid] / denom[valid]
            nonzero_base = valid & (bs_b > 0)
            bss[nonzero_base] = 1.0 - bs_c[nonzero_base] / bs_b[nonzero_base]
        # Zero-baseline draws are valid loss draws but not skill draws.
        zero_base_valid = int(np.count_nonzero(valid & (bs_b <= 0))) \
            if valid.any() else 0

        total_n = int(cb.n.sum())
        total_d = float(cb.sum_d.sum())
        total_c = float(cb.sum_c.sum())
        total_b = float(cb.sum_b.sum())
        point_bss = (1.0 - (total_c / total_n) / (total_b / total_n)) if total_n and total_b > 0 else None
        md = mean_d[~np.isnan(mean_d)]
        sb = bss[~np.isnan(bss)]
        results[name] = BootstrapResult(
            n_units=total_n,
            n_blocks_used=int((cb.n > 0).sum()),
            point_mean_d=(total_d / total_n) if total_n else None,
            point_bs_cand=(total_c / total_n) if total_n else None,
            point_bs_base=(total_b / total_n) if total_n else None,
            point_bss=point_bss,
            draw_mean_d=(float(md.mean()) if md.size else None),
            ci_d=((_pct(md, lo_q), _pct(md, hi_q)) if md.size else None),
            draw_mean_bss=(float(sb.mean()) if sb.size else None),
            ci_bss=((_pct(sb, lo_q), _pct(sb, hi_q)) if sb.size else None),
            replicates=replicates,
            seed=seed,
            n_requested_draws=int(replicates),
            n_valid_loss_draws=int(valid.sum()),
            n_empty_support_draws=int(replicates - int(valid.sum())),
            n_valid_skill_draws=int((valid & (bs_b > 0)).sum())
            if valid.any() else 0,
            n_zero_baseline_loss_draws=zero_base_valid,
        )
    return results


def block_ids_for_units(close_ts: Sequence[Optional[float]], block_len_s: float) -> tuple:
    """Assign contiguous wall-clock block ids on close_ts.

    Returns (block_id_per_unit, n_blocks) where block ids are COMPACTED to
    ``0..n_blocks-1`` over observed blocks only. Units without close_ts get
    -1 (they must not be on support). Compaction is required: raw
    ``floor(epoch/block_len)`` ids are ~1e6 sparse ints and would blow up
    the (replicates x n_blocks) draws matrix and count empty blocks in the
    resample.
    """
    raw = np.array(
        [math.floor(t / block_len_s) if t is not None else -1 for t in close_ts],
        dtype=np.int64,
    )
    if raw.size == 0:
        return raw, 0
    valid = raw >= 0
    uniq = np.unique(raw[valid])
    id_map = {int(v): k for k, v in enumerate(uniq)}
    compact = np.full(raw.size, -1, dtype=np.int64)
    for i, v in enumerate(raw):
        if v >= 0:
            compact[i] = id_map[int(v)]
    return compact, int(uniq.size)
