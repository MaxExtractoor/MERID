"""Measured policy give-back reserve (2026-10-15, FIX 11).

The entry EV claims ``p * 100 - price`` — a binary {0,100} settlement payoff —
but the armed exit policy (profit_only_v1 + HARD_PROFIT_LOCK) actually pays
{0, TP, 100}: triggered exits sell the held side before settlement.  A
profit-path exit only costs EV when the contract would have been worth more
held; the measurable quantity is the post-exit *give-back* — how far the held
mid recovered within the markout horizon after the fill.

``logs/exit_markouts.jsonl`` already records, per executed exit fill, the
held-side markout at +5s/+15s/+60s (``markout_cents = exit_price - held_mid``
— negative means the market recovered, i.e. value left on the table).  The
reserve per *entry* is the trigger probability times the per-trigger give-back:

    policy_giveback_reserve = p_trigger * E[max(0, -markout_60s)]

restricted to profit-path reasons (take_profit, hard_profit_lock, trail,
edge_realization/overpay) — loss-side exits are EV-salvage measured against
conservative hold value, a different trade-off owned by the exit EV evaluator.

Missing/sparse data degrades to ``floor_cents`` so a fresh host does not
silently run with a zero reserve; the cap keeps one extreme window from
vetoing a lane (cell suspension owns that authority).
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Dict, Optional, Tuple

_PROFIT_REASONS = frozenset(
    {
        "take_profit",
        "hard_profit_lock",
        "trail",
        "trailing_profit",
        "edge_realization",
        "overpay",
        "dynamic_take_profit",
    }
)

_TAIL_BYTES = 256 * 1024
_CACHE_TTL_S = 60.0
_cache_lock = threading.Lock()
_cache: Tuple[float, Dict[str, float], Dict[str, int]] = (0.0, {}, {})


def _enabled() -> bool:
    return os.environ.get("MERID_POLICY_GIVEBACK_ENABLED", "1").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _min_samples() -> int:
    try:
        return max(1, int(os.environ.get("MERID_POLICY_GIVEBACK_MIN_SAMPLES", "3")))
    except Exception:
        return 3


def _floor_cents() -> float:
    try:
        return max(0.0, float(os.environ.get("MERID_POLICY_GIVEBACK_FLOOR_CENTS", "1.0")))
    except Exception:
        return 1.0


def _cap_cents() -> float:
    try:
        return max(0.0, float(os.environ.get("MERID_POLICY_GIVEBACK_CAP_CENTS", "15.0")))
    except Exception:
        return 15.0


def _log_path() -> Path:
    base = os.environ.get("MERID_EXIT_MARKOUT_LOG", "").strip()
    if base:
        return Path(base)
    return Path("logs") / "exit_markouts.jsonl"


def _read_tail_rows() -> list:
    """Tail-read the markout log without loading a potentially huge file."""
    path = _log_path()
    try:
        size = path.stat().st_size
    except OSError:
        return []
    try:
        with path.open("rb") as fh:
            if size > _TAIL_BYTES:
                fh.seek(-_TAIL_BYTES, os.SEEK_END)
                fh.readline()  # skip partial line
            data = fh.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    rows = []
    for line in data.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    return rows


def _compute() -> Tuple[Dict[str, float], Dict[str, int]]:
    """Mean give-back per triggered profit exit, per asset + '_all' fallback.

    Uses the 60s horizon marks (longest recorded); a mark is a give-back of
    ``max(0, -markout_cents)`` cents per contract.  Returns ``(means,
    counts)`` — every cohort's raw sample count is reported alongside its
    mean so provenance can name exactly which cohort supplied a charge.
    """
    sums: Dict[str, list] = {}
    for r in _read_tail_rows():
        if r.get("event") != "exit_markout":
            continue
        try:
            if float(r.get("horizon_s") or 0.0) != 60.0:
                continue
        except Exception:
            continue
        if str(r.get("reason") or "").strip().lower() not in _PROFIT_REASONS:
            continue
        try:
            m = float(r.get("markout_cents"))
        except (TypeError, ValueError):
            continue
        gb = max(0.0, -m)
        asset = str(r.get("asset") or "").strip().upper() or "_UNKNOWN"
        sums.setdefault(asset, []).append(gb)
        sums.setdefault("_all", []).append(gb)
    out = {}
    counts = {}
    for key, vals in sums.items():
        counts[key] = len(vals)
        if len(vals) >= _min_samples():
            out[key] = sum(vals) / len(vals)
    return out, counts


def giveback_per_trigger_cents(asset: Optional[str] = None) -> float:
    """E[give-back | profit-exit triggers] for ``asset`` (global fallback).

    Bounded to [floor, cap]; returns 0.0 when the feature is disabled.  A
    sparse asset falls back to the pooled cross-asset estimate — the trigger
    mechanism is policy-global even if the cost is measured per asset.
    """
    if not _enabled():
        return 0.0
    now = time.time()
    with _cache_lock:
        if now - _cache[0] >= _CACHE_TTL_S:
            _new, _new_counts = _compute()
            _cache_update(_new, _new_counts, now)
        stats = _cache[1]
    val = None
    if asset:
        val = stats.get(str(asset).upper())
    if val is None:
        val = stats.get("_all")
    if val is None:
        return _floor_cents()
    return min(_cap_cents(), max(_floor_cents(), val))


def giveback_provenance(asset: Optional[str] = None) -> Dict[str, object]:
    """Resolved cohort identity for the give-back reserve (metadata only).

    Returns ``{"key", "n", "mean_cents", "value_cents"}`` where ``key`` is
    the cohort whose mean the reserve consumed (``ASSET`` or the ``_all``
    pooled fallback), ``n`` its markout sample count, ``mean_cents`` the
    unbounded cohort mean, and ``value_cents`` the bounded per-trigger
    give-back actually charged.  When no cohort is measured the asset's own
    sparse count is still reported so a floor-charge reads as
    under-sampled, not silent.
    """
    if not _enabled():
        return {"key": None, "n": 0, "mean_cents": None, "value_cents": 0.0}
    now = time.time()
    with _cache_lock:
        if now - _cache[0] >= _CACHE_TTL_S:
            _new, _new_counts = _compute()
            _cache_update(_new, _new_counts, now)
        stats = _cache[1]
        counts = _cache[2]
    akey = str(asset).upper() if asset else None
    mean = stats.get(akey) if akey else None
    used_key = akey if mean is not None else "_all"
    if mean is None:
        mean = stats.get("_all")
    if mean is None:
        return {
            "key": None,
            "n": counts.get(akey or "_all", 0),
            "mean_cents": None,
            "value_cents": _floor_cents(),
        }
    return {
        "key": used_key,
        "n": counts.get(used_key, 0),
        "mean_cents": mean,
        "value_cents": min(_cap_cents(), max(_floor_cents(), mean)),
    }


def _cache_update(
    new_stats: Dict[str, float], new_counts: Dict[str, int], now: float
) -> None:
    global _cache
    _cache = (now, new_stats, new_counts)


def reset_cache() -> None:
    """Test hook: drop the TTL cache."""
    global _cache
    with _cache_lock:
        _cache = (0.0, {}, {})
