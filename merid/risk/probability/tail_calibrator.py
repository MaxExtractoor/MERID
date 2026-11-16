"""Tail probability calibrator for held-side binary contracts.

The 7-day corrected trade data showed a severe miscalibration in the 0-19c
held-side price tail: contracts bought at 0.00-0.19 won 0/16 while the model
assigned them >0.5 probability.  This module fits an isotonic (PAVA) regression
from held-side market price to observed win rate and uses it to cap model
probability, preventing the model from overestimating cheap contracts.

The calibrator is fit on the held side (e.g., YES-held contracts for the
current 15m crypto universe).  For the opposite held side we use the dual
relationship: ``p_no(n) = 1 - p_yes(1 - n)``.

The runtime calibrator has no heavy-ML dependencies: it loads a pre-fitted
piecewise-linear calibration from a JSON file.  The fitting step is done offline
by ``scripts/calibrate_tail_probability.py`` (or any caller) and can use NumPy.
"""

from __future__ import annotations

import json
import logging
import math
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def _default_calibration_path() -> Path:
    return Path(__file__).resolve().parent.parent.parent.parent / "data" / "probability_tail_calibration.json"


def _sort_price_prob_pair(prices: List[float], probs: List[float]) -> Tuple[List[float], List[float]]:
    """Sort held-price / actual-probability pairs by price ascending.

    PAVA and the lookup function both assume monotonically increasing held prices.
    Sorting defensively prevents a malformed or manually-edited calibration file
    from silently disabling the cheap-tail cap.
    """
    if not prices:
        return prices, probs
    paired = list(zip(prices, probs))
    paired.sort(key=lambda pair: pair[0])
    return [p for p, _ in paired], [q for _, q in paired]


def _pava_isotonic_full(
    x: List[float],
    y: List[float],
    weights: Optional[List[float]] = None,
) -> Tuple[List[float], List[float], List[float]]:
    """PAVA isotonic regression returning (right-endpoint x, block y, block n).

    ``block n`` is each pooled block's total weight — the effective sample
    size backing that knot.  Used by the two-sided recalibration lift gate.
    """
    import numpy as np

    x_arr = np.asarray(x, dtype=float)
    y_arr = np.asarray(y, dtype=float)
    w_arr = np.asarray(weights if weights is not None else [1.0] * len(y), dtype=float)

    if len(x_arr) == 0:
        return [], [], []

    order = np.argsort(x_arr)
    x_sorted = x_arr[order]
    y_sorted = y_arr[order]
    w_sorted = w_arr[order]

    # Each block: [start_idx, end_idx, weighted_mean, total_weight]
    blocks: List[List[float]] = []
    for i in range(len(x_sorted)):
        blocks.append([float(i), float(i), float(y_sorted[i]), float(w_sorted[i])])

    i = 0
    while i < len(blocks) - 1:
        if blocks[i][2] > blocks[i + 1][2]:
            # Merge i and i+1, with end at i+1's end
            blocks[i][1] = blocks[i + 1][1]
            total_w = blocks[i][3] + blocks[i + 1][3]
            blocks[i][2] = (
                blocks[i][2] * blocks[i][3] + blocks[i + 1][2] * blocks[i + 1][3]
            ) / total_w
            blocks[i][3] = total_w
            blocks.pop(i + 1)
            if i > 0:
                i -= 1
        else:
            i += 1

    # Right-endpoint x for each block gives the knot set
    # PAVA blocks have the right-endpoint x of each block.  Collapse any
    # duplicate x values that can arise from repeated prices: the rightmost
    # block (largest observed y) wins.
    right_xs: List[float] = []
    ys: List[float] = []
    ns: List[float] = []
    for b in blocks:
        x_val = float(x_sorted[int(b[1])])
        y_val = float(b[2])
        n_val = float(b[3])
        if right_xs and abs(right_xs[-1] - x_val) < 1e-12:
            # Same right endpoint: later block wins the y, but the evidence
            # base is the SUM of every block collapsed onto this knot.
            ys[-1] = y_val
            ns[-1] += n_val
        else:
            right_xs.append(x_val)
            ys.append(y_val)
            ns.append(n_val)
    return right_xs, ys, ns


def _pava_isotonic(
    x: List[float],
    y: List[float],
    weights: Optional[List[float]] = None,
) -> Tuple[List[float], List[float]]:
    """PAVA isotonic regression — backward-compatible 2-tuple wrapper."""
    xs, ys, _ns = _pava_isotonic_full(x, y, weights)
    return xs, ys


class TailProbabilityCalibrator:
    """Held-side probability calibrator backed by PAVA isotonic regression.

    The calibrator is intentionally not a generic Platt scaler.  It is fit on
    the held-side market price (the price of the contract we are long) and
    observed win/loss outcomes.  Separate YES and NO curves are maintained so
    the transform can cap model probability at ``actual_win_rate + buffer`` on
    the actual held side, not a symmetric dual approximation.
    """

    def __init__(
        self,
        yes_held_prices: Optional[List[float]] = None,
        yes_actual_probs: Optional[List[float]] = None,
        no_held_prices: Optional[List[float]] = None,
        no_actual_probs: Optional[List[float]] = None,
        held_prices: Optional[List[float]] = None,  # legacy single-curve
        actual_probs: Optional[List[float]] = None,  # legacy single-curve
        buffer: float = 0.05,
        n_trades: int = 0,
        metadata: Optional[Dict[str, Any]] = None,
        per_asset: Optional[Dict[str, Dict[str, Any]]] = None,
        yes_held_n: Optional[List[float]] = None,
        no_held_n: Optional[List[float]] = None,
    ):
        # Legacy single-curve path: use one curve for both sides.
        if held_prices is not None and actual_probs is not None:
            yes_held_prices = held_prices
            yes_actual_probs = actual_probs
            no_held_prices = [1.0 - x for x in held_prices]
            no_actual_probs = [1.0 - y for y in actual_probs]

        self.yes_held_prices = list(yes_held_prices or [])
        self.yes_actual_probs = list(yes_actual_probs or [])
        self.no_held_prices = list(no_held_prices or [])
        self.no_actual_probs = list(no_actual_probs or [])
        if len(self.yes_held_prices) != len(self.yes_actual_probs):
            raise ValueError("yes_held_prices and yes_actual_probs must have same length")
        if len(self.no_held_prices) != len(self.no_actual_probs):
            raise ValueError("no_held_prices and no_actual_probs must have same length")

        # Per-knot effective sample sizes, parallel to the price/prob knots.
        # Used ONLY to evidence-gate the two-sided lift (MERID_RECAL_TWO_SIDED);
        # absent or mismatched lengths disable lifting (cap-only, today's
        # behavior).  PAVA knots are right-endpoints, so ``*_held_n[i]`` is the
        # pooled count of the block ending at ``*_held_prices[i]``.
        self.yes_held_n = self._align_n(yes_held_n, len(self.yes_held_prices))
        self.no_held_n = self._align_n(no_held_n, len(self.no_held_prices))

        # Defensive: PAVA and _lookup both require ascending held prices.
        self.yes_held_prices, self.yes_actual_probs = _sort_price_prob_pair(
            self.yes_held_prices, self.yes_actual_probs
        )
        self.no_held_prices, self.no_actual_probs = _sort_price_prob_pair(
            self.no_held_prices, self.no_actual_probs
        )

        self.buffer = buffer
        self.n_trades = n_trades
        self.metadata = metadata or {}

        # Detect whether the NO curve is merely the YES dual (1 - p) rather than
        # fit on real NO-held data.  A real NO calibration must be re-fit from
        # held NO prices and outcomes; using the dual silently exposes the NO
        # side to the YES tail miscalibration.  Per-side fits will not be exactly
        # the mirror image, so this detection is conservative.
        self.no_curve_is_dual = self._check_no_curve_is_dual()

        # Per-asset curves (hierarchical: refit script shrinks each asset's
        # bucket rates toward this pooled curve with κ pseudo-observations).
        # A sub-curve is only used when it carries enough observations —
        # thin assets silently fall back to the pooled curve so a sparse fit
        # cannot dominate a decision.  Gate is env-tunable for tests.
        self._per_asset: Dict[str, "TailProbabilityCalibrator"] = {}
        self._per_asset_n: Dict[str, int] = {}
        for _name, _sub in (per_asset or {}).items():
            try:
                sub_cal = TailProbabilityCalibrator(
                    yes_held_prices=_sub.get("yes_held_prices"),
                    yes_actual_probs=_sub.get("yes_actual_probs"),
                    no_held_prices=_sub.get("no_held_prices"),
                    no_actual_probs=_sub.get("no_actual_probs"),
                    buffer=float(_sub.get("buffer", buffer)),
                    n_trades=int(_sub.get("n", 0) or 0),
                    yes_held_n=_sub.get("yes_held_n"),
                    no_held_n=_sub.get("no_held_n"),
                )
            except Exception:
                continue
            key = str(_name).upper()
            self._per_asset[key] = sub_cal
            self._per_asset_n[key] = int(_sub.get("n", 0) or 0)

    @staticmethod
    def _min_asset_obs() -> int:
        try:
            return max(0, int(os.getenv("MERID_TAIL_CALIBRATION_MIN_ASSET_OBS", "500")))
        except Exception:
            return 500

    def has_asset_curve(self, asset: Optional[str]) -> bool:
        """True when a populated per-asset curve with enough observations exists."""
        if not asset:
            return False
        key = str(asset).upper()
        sub = self._per_asset.get(key)
        return (
            sub is not None
            and self._per_asset_n.get(key, 0) >= self._min_asset_obs()
        )

    def _asset_curve(self, asset: Optional[str]) -> Optional["TailProbabilityCalibrator"]:
        return self._per_asset.get(str(asset).upper()) if self.has_asset_curve(asset) else None

    def _check_no_curve_is_dual(self) -> bool:
        if not self.yes_held_prices or not self.no_held_prices:
            return False
        if len(self.yes_held_prices) != len(self.no_held_prices):
            return False

        yes_idx = sorted(range(len(self.yes_held_prices)), key=lambda i: self.yes_held_prices[i])
        no_idx = sorted(range(len(self.no_held_prices)), key=lambda i: self.no_held_prices[i], reverse=True)

        tol = 1e-6
        for i in range(len(yes_idx)):
            yes_price = self.yes_held_prices[yes_idx[i]]
            no_price = self.no_held_prices[no_idx[i]]
            yes_prob = self.yes_actual_probs[yes_idx[i]]
            no_prob = self.no_actual_probs[no_idx[i]]
            if (
                abs((1.0 - yes_price) - no_price) > tol
                or abs((1.0 - yes_prob) - no_prob) > tol
            ):
                return False
        return True

    def p_yes(self, held_yes_price: float, asset: Optional[str] = None) -> float:
        """Actual P(YES wins) for a YES-held contract at ``held_yes_price``."""
        sub = self._asset_curve(asset)
        if sub is not None:
            return sub.p_yes(held_yes_price)
        return self._lookup(held_yes_price, self.yes_held_prices, self.yes_actual_probs)

    def p_no(self, held_no_price: float, asset: Optional[str] = None) -> float:
        """Actual P(NO wins) for a NO-held contract at ``held_no_price``."""
        sub = self._asset_curve(asset)
        if sub is not None:
            return sub.p_no(held_no_price)
        return self._lookup(held_no_price, self.no_held_prices, self.no_actual_probs)

    def cap_p_yes(
        self, p_yes_model: float, held_yes_price: float, asset: Optional[str] = None
    ) -> float:
        """Cap model P(YES) at actual + buffer for a YES-held price."""
        return min(p_yes_model, self.p_yes(held_yes_price, asset=asset) + self.buffer)

    def cap_p_no(
        self, p_no_model: float, held_no_price: float, asset: Optional[str] = None
    ) -> float:
        """Cap model P(NO) at actual + buffer for a NO-held price."""
        return min(p_no_model, self.p_no(held_no_price, asset=asset) + self.buffer)

    @staticmethod
    def _lookup(price: float, held_prices: List[float], actual_probs: List[float]) -> float:
        price = max(0.0, min(1.0, price))
        if not held_prices:
            return price  # uncalibrated fallback: trust the market
        if price <= held_prices[0]:
            return actual_probs[0]
        # PAVA returns right-endpoint knots.  The step value for any price is the
        # value at the first knot that is at or above it.  This preserves the
        # monotonic blocks instead of interpolating across gaps in the data.
        for x, y in zip(held_prices, actual_probs):
            if price <= x:
                return y
        return actual_probs[-1]

    @staticmethod
    def _align_n(n_values: Optional[List[float]], expected: int) -> Optional[List[float]]:
        """Return a per-knot count list only when it aligns 1:1 with the knots.

        A missing or length-mismatched count array disables evidence-gated
        lifting entirely (the calibrator falls back to cap-only behavior).
        """
        if n_values is None or len(n_values) != expected or expected == 0:
            return None
        try:
            out = [max(0.0, float(v)) for v in n_values]
        except Exception:
            return None
        return out

    @staticmethod
    def _lookup_n(
        price: float,
        held_prices: List[float],
        held_n: Optional[List[float]],
    ) -> Optional[float]:
        """Effective sample size of the PAVA block covering ``price``.

        Mirrors ``_lookup``'s right-endpoint step semantics: the block that
        first has ``price <= knot`` owns the lookup, so its pooled count is the
        evidence base for that price.
        """
        if held_n is None or not held_prices:
            return None
        price = max(0.0, min(1.0, price))
        for x, n in zip(held_prices, held_n):
            if price <= x:
                return float(n)
        return float(held_n[-1])

    # ── Two-sided recalibration (MERID_RECAL_TWO_SIDED, default OFF) ──────
    #
    # The cap path can only LOWER an over-confident claim.  When a bucket's
    # observed win rate sits ABOVE the model claim (under-confidence — the
    # high-side S-curve found in the 2026-11-16 Brier audit), a bounded,
    # evidence-gated lift raises p toward the observed rate.  Lifting requires
    # per-knot effective n, a minimum-N gate, a significance margin, a hard
    # lift cap, and empirical-Bayes shrinkage — the same discipline as
    # evidence_policy.edge_bias.  With the flag off, or without per-knot
    # counts, adjust_* reduces exactly to cap_*.

    @staticmethod
    def _recal_enabled() -> bool:
        return os.getenv("MERID_RECAL_TWO_SIDED", "0").strip().lower() in (
            "1", "true", "yes",
        )

    @staticmethod
    def _recal_min_neff() -> float:
        try:
            return float(os.getenv("MERID_RECAL_MIN_NEFF", "12"))
        except Exception:
            return 12.0

    @staticmethod
    def _recal_lift_cap() -> float:
        try:
            return float(os.getenv("MERID_RECAL_LIFT_CAP", "0.10"))
        except Exception:
            return 0.10

    @staticmethod
    def _recal_prior_k() -> float:
        try:
            return float(os.getenv("MERID_RECAL_PRIOR_K", "8"))
        except Exception:
            return 8.0

    @staticmethod
    def _recal_lift_z() -> float:
        try:
            return float(os.getenv("MERID_RECAL_LIFT_Z", "1.0"))
        except Exception:
            return 1.0

    def _lift_delta(
        self,
        p_model: float,
        observed: float,
        n_eff: Optional[float],
    ) -> float:
        """Bounded, shrunk, evidence-gated upward correction (>=0).

        Returns the probability to ADD to ``p_model`` (0.0 when the lift is
        not warranted).  The target is ``observed`` (the empirical win rate at
        this held price); the raw gap is shrunk toward zero by the empirical
        prior and hard-capped, and only applied when the bucket clears the
        minimum-N and significance gates.
        """
        if n_eff is None or n_eff < self._recal_min_neff():
            return 0.0
        gap = observed - p_model
        if gap <= 0.0:
            return 0.0
        # Significance: SE of the observed win rate at this bucket.
        se = math.sqrt(max(observed * (1.0 - observed), 1e-9) / n_eff)
        if gap <= self._recal_lift_z() * se:
            return 0.0
        # Empirical-Bayes shrinkage toward zero + hard cap.
        shrunk = gap * (n_eff / (n_eff + self._recal_prior_k()))
        return min(shrunk, self._recal_lift_cap())

    def adjust_p_yes(
        self, p_yes_model: float, held_yes_price: float, asset: Optional[str] = None
    ) -> float:
        """Two-sided calibrated P(YES): cap over-confidence, lift under-confidence.

        Falls back to ``cap_p_yes`` exactly when two-sided mode is off or the
        bucket lacks evidence.  Never exceeds ``observed + buffer`` upward and
        never lifts without per-knot n clearing the gates.
        """
        if not self._recal_enabled():
            return self.cap_p_yes(p_yes_model, held_yes_price, asset=asset)
        sub = self._asset_curve(asset)
        cal = sub if sub is not None else self
        observed = cal.p_yes(held_yes_price)
        capped = min(p_yes_model, observed + cal.buffer)
        n_eff = cal._lookup_n(held_yes_price, cal.yes_held_prices, cal.yes_held_n)
        lift = cal._lift_delta(capped, observed, n_eff)
        # Never lift above the observed win rate itself (the empirical bound),
        # and the cap already bounded the top — lift only fills the gap below.
        return min(capped + lift, observed + cal.buffer)

    def adjust_p_no(
        self, p_no_model: float, held_no_price: float, asset: Optional[str] = None
    ) -> float:
        """Two-sided calibrated P(NO): cap over-confidence, lift under-confidence."""
        if not self._recal_enabled():
            return self.cap_p_no(p_no_model, held_no_price, asset=asset)
        sub = self._asset_curve(asset)
        cal = sub if sub is not None else self
        observed = cal.p_no(held_no_price)
        capped = min(p_no_model, observed + cal.buffer)
        n_eff = cal._lookup_n(held_no_price, cal.no_held_prices, cal.no_held_n)
        lift = cal._lift_delta(capped, observed, n_eff)
        return min(capped + lift, observed + cal.buffer)

    def to_dict(self) -> Dict[str, Any]:
        metadata = dict(self.metadata)
        metadata["no_curve_is_dual"] = self.no_curve_is_dual
        out = {
            "yes_held_prices": self.yes_held_prices,
            "yes_actual_probs": self.yes_actual_probs,
            "no_held_prices": self.no_held_prices,
            "no_actual_probs": self.no_actual_probs,
            "buffer": self.buffer,
            "n_trades": self.n_trades,
            "metadata": metadata,
        }
        if self.yes_held_n is not None:
            out["yes_held_n"] = self.yes_held_n
        if self.no_held_n is not None:
            out["no_held_n"] = self.no_held_n
        if self._per_asset:
            out["per_asset"] = {
                name: {
                    "yes_held_prices": sub.yes_held_prices,
                    "yes_actual_probs": sub.yes_actual_probs,
                    "no_held_prices": sub.no_held_prices,
                    "no_actual_probs": sub.no_actual_probs,
                    "buffer": sub.buffer,
                    "n": self._per_asset_n.get(name, sub.n_trades),
                    **(
                        {"yes_held_n": sub.yes_held_n}
                        if sub.yes_held_n is not None
                        else {}
                    ),
                    **(
                        {"no_held_n": sub.no_held_n}
                        if sub.no_held_n is not None
                        else {}
                    ),
                }
                for name, sub in self._per_asset.items()
            }
        return out

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TailProbabilityCalibrator":
        # Backward compatibility with single-curve legacy files.
        if "yes_held_prices" not in data and "held_prices" in data:
            return cls(
                held_prices=data.get("held_prices", []),
                actual_probs=data.get("actual_probs", []),
                buffer=data.get("buffer", 0.05),
                n_trades=data.get("n_trades", 0),
                metadata=data.get("metadata", {}),
            )
        return cls(
            yes_held_prices=data.get("yes_held_prices", []),
            yes_actual_probs=data.get("yes_actual_probs", []),
            no_held_prices=data.get("no_held_prices", []),
            no_actual_probs=data.get("no_actual_probs", []),
            buffer=data.get("buffer", 0.05),
            n_trades=data.get("n_trades", 0),
            metadata=data.get("metadata", {}),
            per_asset=data.get("per_asset"),
            yes_held_n=data.get("yes_held_n"),
            no_held_n=data.get("no_held_n"),
        )

    @classmethod
    def from_trade_analysis(
        cls,
        trades: List[Dict[str, Any]],
        buffer: float = 0.05,
    ) -> "TailProbabilityCalibrator":
        """Fit per-side PAVA isotonic regression on trade analysis data.

        Each trade is converted into its held-side coordinate independently for
        YES-held and NO-held contracts.  This keeps the YES and NO calibrations
        separate instead of forcing symmetry through the dual relationship.
        """
        from decimal import Decimal

        yes_prices: List[float] = []
        yes_wins: List[int] = []
        no_prices: List[float] = []
        no_wins: List[int] = []

        for trade in trades:
            side = (trade.get("side") or "").upper()
            action = (trade.get("action") or "").lower()
            price = Decimal(str(trade.get("price", 0)))
            market_result = (trade.get("market_result") or "").lower()

            # Determine the held side and the price paid for that held side.
            if action == "buy":
                held_side = side
                held_price = float(price)
            else:  # sell -> held is the opposite side; price received is premium
                held_side = "YES" if side == "NO" else "NO"
                held_price = float(Decimal(1) - price)

            if held_side == "YES":
                win = 1 if market_result == "yes" else 0
                yes_prices.append(held_price)
                yes_wins.append(win)
            else:
                win = 1 if market_result == "no" else 0
                no_prices.append(held_price)
                no_wins.append(win)

        if len(yes_prices) < 5 and len(no_prices) < 5:
            raise ValueError(
                f"Need at least 5 YES and 5 NO trades to fit per-side calibration, "
                f"got YES={len(yes_prices)} NO={len(no_prices)}"
            )

        yes_xs, yes_ys, yes_ns = (
            _pava_isotonic_full(yes_prices, yes_wins) if yes_prices else ([], [], [])
        )
        no_xs, no_ys, no_ns = (
            _pava_isotonic_full(no_prices, no_wins) if no_prices else ([], [], [])
        )

        return cls(
            yes_held_prices=yes_xs,
            yes_actual_probs=yes_ys,
            no_held_prices=no_xs,
            no_actual_probs=no_ys,
            yes_held_n=yes_ns or None,
            no_held_n=no_ns or None,
            buffer=buffer,
            n_trades=len(yes_prices) + len(no_prices),
            metadata={
                "source": "trade_analysis_raw_7d",
                "fit_method": "per_side_pava_isotonic_regression",
                "held_side": "both",
            },
        )


_cached_calibrator: Optional[TailProbabilityCalibrator] = None
_cached_calibrator_mtime: Optional[float] = None
_cached_calibrator_path: Optional[str] = None


def load_tail_calibrator(
    path: Optional[Path] = None,
) -> Optional[TailProbabilityCalibrator]:
    """Load a tail calibrator from disk.

    2026-11-07: mtime-aware cache (same contract as the walk-forward
    calibrator loader).  The artifact used to be cached for the process
    lifetime, so a scheduled/manual refit never took effect until restart —
    the 23-day-stale artifact kept gating live decisions.  A refit now
    hot-loads on the next call; a torn/invalid rewrite simply fails to
    parse and the previous curve stays cached.
    """
    global _cached_calibrator, _cached_calibrator_mtime, _cached_calibrator_path

    if path is None:
        env_path = os.environ.get("MERID_TAIL_CALIBRATION_PATH")
        if env_path:
            path = Path(env_path)
        else:
            path = _default_calibration_path()

    try:
        mtime = path.stat().st_mtime
    except OSError:
        return _cached_calibrator

    if (
        _cached_calibrator is not None
        and _cached_calibrator_mtime == mtime
        and _cached_calibrator_path == str(path)
    ):
        return _cached_calibrator

    try:
        with open(path, "r") as f:
            data = json.load(f)
        calibrator = TailProbabilityCalibrator.from_dict(data)
    except Exception as exc:
        logger.warning(
            "[TAIL-CALIBRATOR] reload of %s failed (%s); keeping prior curve",
            path,
            exc,
        )
        return _cached_calibrator

    _cached_calibrator = calibrator
    _cached_calibrator_mtime = mtime
    _cached_calibrator_path = str(path)
    if calibrator.no_curve_is_dual:
        logger.warning(
            "[TAIL-CALIBRATOR] NO curve is the YES dual (1 - p_yes) from %s; "
            "treat NO-side tail caps as provisional until re-fit on real NO-held data.",
            path,
        )
    return _cached_calibrator


def clear_tail_calibrator_cache() -> None:
    global _cached_calibrator, _cached_calibrator_mtime, _cached_calibrator_path
    _cached_calibrator = None
    _cached_calibrator_mtime = None
    _cached_calibrator_path = None
