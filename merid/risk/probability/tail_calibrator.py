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
import math
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _default_calibration_path() -> Path:
    return Path(__file__).resolve().parent.parent.parent.parent / "data" / "probability_tail_calibration.json"


def _pava_isotonic(
    x: List[float],
    y: List[float],
    weights: Optional[List[float]] = None,
) -> Tuple[List[float], List[float]]:
    """Pool Adjacent Violators Algorithm (PAVA) for isotonic regression.

    Returns a compact step function as (right-endpoint x values, block y values).
    """
    import numpy as np

    x_arr = np.asarray(x, dtype=float)
    y_arr = np.asarray(y, dtype=float)
    w_arr = np.asarray(weights if weights is not None else [1.0] * len(y), dtype=float)

    if len(x_arr) == 0:
        return [], []

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
    for b in blocks:
        x_val = float(x_sorted[int(b[1])])
        y_val = float(b[2])
        if right_xs and abs(right_xs[-1] - x_val) < 1e-12:
            ys[-1] = y_val  # later block overwrites at the same right endpoint
        else:
            right_xs.append(x_val)
            ys.append(y_val)
    return right_xs, ys


class TailProbabilityCalibrator:
    """Held-side probability calibrator backed by PAVA isotonic regression.

    The calibrator is intentionally not a generic Platt scaler.  It is fit on
    the held-side market price (the price of the contract we are long) and
    observed win/loss outcomes.  The transform caps model probability at
    ``actual_win_rate + buffer`` so tail overconfidence cannot produce positive
    edge.
    """

    def __init__(
        self,
        held_prices: List[float],
        actual_probs: List[float],
        buffer: float = 0.05,
        n_trades: int = 0,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        if len(held_prices) != len(actual_probs):
            raise ValueError("held_prices and actual_probs must have same length")
        self.held_prices = list(held_prices)
        self.actual_probs = list(actual_probs)
        self.buffer = buffer
        self.n_trades = n_trades
        self.metadata = metadata or {}

    def p_yes(self, held_yes_price: float) -> float:
        """Actual P(YES wins) for a YES-held contract at ``held_yes_price``."""
        return self._lookup(held_yes_price)

    def p_no(self, held_no_price: float) -> float:
        """Actual P(NO wins) for a NO-held contract at ``held_no_price``.

        Uses the dual of the YES-held calibration.
        """
        return 1.0 - self._lookup(1.0 - held_no_price)

    def cap_p_yes(self, p_yes_model: float, held_yes_price: float) -> float:
        """Cap model P(YES) at actual + buffer for a YES-held price."""
        return min(p_yes_model, self.p_yes(held_yes_price) + self.buffer)

    def cap_p_no(self, p_no_model: float, held_no_price: float) -> float:
        """Cap model P(NO) at actual + buffer for a NO-held price."""
        return min(p_no_model, self.p_no(held_no_price) + self.buffer)

    def _lookup(self, price: float) -> float:
        price = max(0.0, min(1.0, price))
        if not self.held_prices:
            return price  # uncalibrated fallback: trust the market
        if price <= self.held_prices[0]:
            return self.actual_probs[0]
        # PAVA returns right-endpoint knots.  The step value for any price is the
        # value at the first knot that is at or above it.  This preserves the
        # monotonic blocks instead of interpolating across gaps in the data.
        for x, y in zip(self.held_prices, self.actual_probs):
            if price <= x:
                return y
        return self.actual_probs[-1]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "held_prices": self.held_prices,
            "actual_probs": self.actual_probs,
            "buffer": self.buffer,
            "n_trades": self.n_trades,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TailProbabilityCalibrator":
        return cls(
            held_prices=data.get("held_prices", []),
            actual_probs=data.get("actual_probs", []),
            buffer=data.get("buffer", 0.05),
            n_trades=data.get("n_trades", 0),
            metadata=data.get("metadata", {}),
        )

    @classmethod
    def from_trade_analysis(
        cls,
        trades: List[Dict[str, Any]],
        buffer: float = 0.05,
    ) -> "TailProbabilityCalibrator":
        """Fit PAVA isotonic regression on the held side of trade analysis data."""
        from decimal import Decimal

        held_prices: List[float] = []
        wins: List[int] = []

        for trade in trades:
            side = (trade.get("side") or "").upper()
            action = (trade.get("action") or "").lower()
            price = Decimal(str(trade.get("price", 0)))
            market_result = (trade.get("market_result") or "").lower()

            if action == "buy":
                held_side = side
                held_price = float(price)
            else:  # sell -> held is the opposite side
                held_side = "YES" if side == "NO" else "NO"
                held_price = float(Decimal(1) - price)

            if held_side == "YES":
                win = 1 if market_result == "yes" else 0
            else:
                win = 1 if market_result == "no" else 0

            # Convert all observations to a unified YES-held coordinate so the
            # isotonic is over the probability of the held side winning.
            if held_side == "YES":
                held_yes_price = held_price
                win_yes = win
            else:
                held_yes_price = 1.0 - held_price
                win_yes = 1 - win

            if 0.0 <= held_yes_price <= 1.0:
                held_prices.append(held_yes_price)
                wins.append(win_yes)

        if len(held_prices) < 10:
            raise ValueError(f"Need at least 10 trades to fit tail calibration, got {len(held_prices)}")

        right_xs, ys = _pava_isotonic(held_prices, wins)

        return cls(
            held_prices=right_xs,
            actual_probs=ys,
            buffer=buffer,
            n_trades=len(held_prices),
            metadata={
                "source": "trade_analysis_raw_7d",
                "fit_method": "pava_isotonic_regression",
                "held_side": "yes",
            },
        )


_cached_calibrator: Optional[TailProbabilityCalibrator] = None


def load_tail_calibrator(
    path: Optional[Path] = None,
) -> Optional[TailProbabilityCalibrator]:
    """Load a tail calibrator from disk.  Uses a process-level cache."""
    global _cached_calibrator
    if _cached_calibrator is not None:
        return _cached_calibrator

    if path is None:
        env_path = os.environ.get("MERID_TAIL_CALIBRATION_PATH")
        if env_path:
            path = Path(env_path)
        else:
            path = _default_calibration_path()

    if not path.exists():
        return None

    with open(path, "r") as f:
        data = json.load(f)

    _cached_calibrator = TailProbabilityCalibrator.from_dict(data)
    return _cached_calibrator


def clear_tail_calibrator_cache() -> None:
    global _cached_calibrator
    _cached_calibrator = None
