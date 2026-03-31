"""merid/formulas.py — Canonical math for the Kalshi sentiment stack.

**ALL** arithmetic that feeds the fear/greed index, score normalisation, and
R/A/G classification MUST live here.  No custom math may be defined elsewhere
in the Kalshi sentiment pipeline (enforced by the `kalshi-audit-gate` CI job).

Change-control
--------------
- Bump ``FORMULAS_VERSION`` on ANY change to a formula, constant, or band
  boundary.
- Bump ``AUDIT_SPEC_VERSION`` when the invariant set or the trace schema
  changes (add/remove/rename a stage hook, alter RAG thresholds, etc.).
- Every bump must be accompanied by:
  * an update to ``AGENT_AUDIT_KALSHI_SENTIMENT.md``
  * a corresponding bump in ``tests/event_venues/kalshi/test_kalshi_audit_trail.py``
  * (optional) a CHANGELOG entry

Correlation IDs
---------------
Every DISCOVER→PROTECT pipeline run is tied by a single opaque string created
with ``generate_correlation_id()``.  Pass the same ID through every stage so
that ``[TRACE]`` log lines can be reconstructed end-to-end from a single grep.
"""

from __future__ import annotations

import math
import uuid
from collections import deque
from typing import Deque

# ── Version sentinels ─────────────────────────────────────────────────────────

#: Bump when ANY formula, band boundary, or component weight changes.
FORMULAS_VERSION: str = "1.0.0"

#: Bump when the invariant set, trace schema, or R/A/G thresholds change.
AUDIT_SPEC_VERSION: str = "1.0.0"

# ── Fear/greed band boundaries (0–100 index) ──────────────────────────────────

EXTREME_FEAR_MAX: int = 24   # 0–24   → extreme_fear
FEAR_MAX: int = 49           # 25–49  → fear
GREED_MAX: int = 74          # 50–74  → greed
                             # 75–100 → extreme_greed

# ── Component weights (must sum to 1.0) ──────────────────────────────────────

COMPONENT_WEIGHTS: dict[str, float] = {
    "volatility":  0.30,
    "volume_heat": 0.30,
    "book_imbal":  0.40,
}

# ── R/A/G thresholds for operational health ───────────────────────────────────

#: Minimum markets that must have contributed to a score for it to be GREEN.
RAG_MIN_SAMPLE_COUNT: int = 1

#: Score deviation from prior composite that triggers AMBER drift warning.
RAG_DRIFT_AMBER_DELTA: float = 15.0

#: Score deviation from prior composite that triggers RED drift alert.
RAG_DRIFT_RED_DELTA: float = 30.0


# ── Correlation-ID factory ────────────────────────────────────────────────────

def generate_correlation_id() -> str:
    """Return a new UUID4-based correlation ID for one pipeline run.

    Usage::

        corr_id = generate_correlation_id()
        logger.info("[TRACE] stage=DISCOVER corr_id=%s ...", corr_id)
        # … pass corr_id to every subsequent stage …
        logger.info("[TRACE] stage=PROTECT corr_id=%s ...", corr_id)
    """
    return str(uuid.uuid4())


# ── Pure math helpers ─────────────────────────────────────────────────────────

def regime(score: float) -> str:
    """Map a 0–100 index value to its named fear/greed regime.

    >>> regime(10)
    'extreme_fear'
    >>> regime(37)
    'fear'
    >>> regime(62)
    'greed'
    >>> regime(88)
    'extreme_greed'
    """
    if score <= EXTREME_FEAR_MAX:
        return "extreme_fear"
    if score <= FEAR_MAX:
        return "fear"
    if score <= GREED_MAX:
        return "greed"
    return "extreme_greed"


def rolling_std(buf: Deque[float]) -> float:
    """Population σ of *buf*.  Returns 0.0 when fewer than 2 samples exist.

    >>> import math
    >>> round(rolling_std(deque([2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0])), 4)
    2.0
    """
    n = len(buf)
    if n < 2:
        return 0.0
    mean = sum(buf) / n
    variance = sum((x - mean) ** 2 for x in buf) / n
    return math.sqrt(variance)


def normalize_vol(sigma: float, baseline_sigma: float) -> float:
    """Map σ / baseline_σ to 0–1.  σ > 2× baseline → 1.0 (extreme vol).

    >>> normalize_vol(0.0, 0.0)
    0.5
    >>> normalize_vol(1.0, 0.5)
    1.0
    >>> normalize_vol(0.5, 1.0)
    0.25
    """
    if baseline_sigma <= 0:
        return 0.5
    ratio = sigma / baseline_sigma
    return min(1.0, ratio / 2.0)


def normalize_volume(current: float, baseline: float) -> float:
    """Map current / baseline to 0–1.  ≥ 3× baseline → 1.0.

    >>> normalize_volume(0.0, 0.0)
    0.5
    >>> normalize_volume(3.0, 1.0)
    1.0
    >>> normalize_volume(1.5, 3.0)
    0.16666666666666666
    """
    if baseline <= 0:
        return 0.5
    ratio = current / baseline
    return min(1.0, ratio / 3.0)


def book_imbalance(bid: float, ask: float) -> float:
    """|(bid − ask)| / (bid + ask) → 0–1.  0 = balanced, 1 = fully one-sided.

    >>> book_imbalance(0.0, 0.0)
    0.0
    >>> book_imbalance(3.0, 1.0)
    0.5
    >>> book_imbalance(1.0, 0.0)
    1.0
    """
    total = bid + ask
    if total <= 0:
        return 0.0
    return abs(bid - ask) / total


def score_to_100(vol: float, volume: float, imbal: float) -> float:
    """Combine normalised 0–1 components into a 0–100 index.

    Uses the canonical ``COMPONENT_WEIGHTS`` mapping.

    >>> round(score_to_100(0.5, 0.5, 0.5), 1)
    50.0
    >>> round(score_to_100(1.0, 1.0, 1.0), 1)
    100.0
    >>> score_to_100(0.0, 0.0, 0.0)
    0.0
    """
    raw = (
        COMPONENT_WEIGHTS["volatility"]  * vol +
        COMPONENT_WEIGHTS["volume_heat"] * volume +
        COMPONENT_WEIGHTS["book_imbal"]  * imbal
    )
    return raw * 100.0


# ── Invariant checker ─────────────────────────────────────────────────────────

def check_invariants() -> list[str]:
    """Validate the internal consistency of this module's constants.

    Returns a list of violation strings (empty list = all clear).  Called by
    the ``kalshi-audit-gate`` CI job and the smoke test.
    """
    violations: list[str] = []

    weight_sum = sum(COMPONENT_WEIGHTS.values())
    if abs(weight_sum - 1.0) > 1e-9:
        violations.append(
            f"COMPONENT_WEIGHTS do not sum to 1.0: {weight_sum}"
        )

    if not (0 <= EXTREME_FEAR_MAX < FEAR_MAX < GREED_MAX < 100):
        violations.append(
            f"Band boundaries out of order: "
            f"{EXTREME_FEAR_MAX=} {FEAR_MAX=} {GREED_MAX=}"
        )

    if RAG_DRIFT_AMBER_DELTA >= RAG_DRIFT_RED_DELTA:
        violations.append(
            f"RAG_DRIFT_AMBER_DELTA ({RAG_DRIFT_AMBER_DELTA}) must be "
            f"< RAG_DRIFT_RED_DELTA ({RAG_DRIFT_RED_DELTA})"
        )

    return violations
