"""
1D Kalman filter for smoothing noisy sentiment signals.

Replaces pure EMA/Fibonacci smoothing in the BTC 15m lane's
_update_sentiment() with a state-space filtered estimate.  The filter
tracks a hidden "true sentiment" state and updates it each cycle using
the Kalman gain, producing a signal that is:
  - Less reactive to single-bar noise than raw combined sentiment
  - More responsive than a long EMA window
  - Statistically optimal under Gaussian noise assumptions

Usage:
    from merid.sentiment.kalman_sentiment import SentimentKalman
import threading

    kalman = SentimentKalman()
    smoothed = kalman.update(raw_combined)   # call once per cycle

Tune process_var / meas_var to control responsiveness:
  - Higher process_var → trusts the signal more, faster tracking
  - Higher meas_var    → trusts the model more, slower tracking
"""

from __future__ import annotations

from utils.logger import get_logger
from dataclasses import dataclass
from typing import List, Optional

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

@dataclass
class KalmanState:
    """Internal state of the 1D Kalman filter."""
    x: float    # current estimate (filtered sentiment)
    P: float    # estimate error covariance


# ---------------------------------------------------------------------------
# Filter
# ---------------------------------------------------------------------------

class SentimentKalman:
    """
    1D Kalman filter for a scalar sentiment signal in [-1, 1].

    Equations (constant-velocity model, no control input):
        Predict:  x_pred = x,  P_pred = P + Q
        Update:   K      = P_pred / (P_pred + R)
                  x_new  = x_pred + K * (z - x_pred)
                  P_new  = (1 - K) * P_pred

    Args:
        process_var: Q — process noise variance.  Higher = faster tracking.
        meas_var:    R — measurement noise variance.  Higher = more smoothing.
        init_x:      Initial state estimate (default 0.0 = neutral).
        init_P:      Initial covariance (default 1.0 = high uncertainty).
    """

    def __init__(
        self,
        process_var: float = 0.01,
        meas_var: float = 0.10,
        init_x: float = 0.0,
        init_P: float = 1.0,
    ) -> None:
        self.Q = process_var
        self.R = meas_var
        self.state = KalmanState(x=init_x, P=init_P)
        self._history: List[float] = []

    def update(self, z: float) -> float:
        """
        Ingest a new raw measurement z and return the filtered estimate.

        Args:
            z: Raw sentiment value (typically combined_smoothed, -1..1).

        Returns:
            Filtered sentiment estimate in approximately the same range.
        """
        # Predict
        x_pred = self.state.x
        P_pred = self.state.P + self.Q

        # Kalman gain
        K = P_pred / (P_pred + self.R)

        # Update
        x_new = x_pred + K * (z - x_pred)
        P_new = (1.0 - K) * P_pred

        self.state = KalmanState(x=x_new, P=P_new)
        self._history.append(x_new)
        if len(self._history) > 500:
            self._history = self._history[-500:]

        return x_new

    def reset(self, init_x: float = 0.0, init_P: float = 1.0) -> None:
        """Reset filter state (e.g. after a fresh start or regime change)."""
        self.state = KalmanState(x=init_x, P=init_P)
        self._history.clear()

    @property
    def current_estimate(self) -> float:
        """Return the latest filtered estimate without ingesting a new measurement."""
        return self.state.x

    @property
    def kalman_gain(self) -> float:
        """Approximate current Kalman gain (useful for observability)."""
        P_pred = self.state.P + self.Q
        return P_pred / (P_pred + self.R)

    def get_status(self) -> dict:
        return {
            "estimate": self.state.x,
            "covariance": self.state.P,
            "kalman_gain": self.kalman_gain,
            "process_var": self.Q,
            "meas_var": self.R,
            "samples": len(self._history),
        }


# ---------------------------------------------------------------------------
# Sentiment-adjusted sizing helper
# ---------------------------------------------------------------------------

def kf_sentiment_adjust(
    risk_dollars: float,
    raw_sentiment: float,
    kalman: Optional["SentimentKalman"] = None,
) -> float:
    """
    Apply a Kalman-smoothed sentiment multiplier to a risk dollar value.

    Multiplier = 1.0 + 0.2 * smoothed_sentiment
    Clamped to [0.8, 1.2] so it can only nudge ±20%.

    Call this AFTER ATR + FG + drawdown sizing, not before, so it
    acts as a final fine-tuning layer rather than a primary sizer.

    Args:
        risk_dollars:   Dollar risk from upstream sizing stack.
        raw_sentiment:  Raw combined sentiment (-1..1).
        kalman:         Optional SentimentKalman instance.  If None,
                        uses the module-level singleton.

    Returns:
        Adjusted dollar risk (same sign as input).
    """
    kf = kalman or get_sentiment_kalman()
    smoothed = kf.update(raw_sentiment)
    multiplier = max(0.8, min(1.0 + 0.2 * smoothed, 1.2))
    return risk_dollars * multiplier


# ---------------------------------------------------------------------------
# Singleton (one filter per process; lanes share it or create their own)
# ---------------------------------------------------------------------------

_default_kalman: Optional[SentimentKalman] = None
_default_kalman_lock = threading.Lock()


def get_sentiment_kalman(
    process_var: float = 0.01,
    meas_var: float = 0.10,
) -> SentimentKalman:
    """Get (or create) the default SentimentKalman singleton."""
    global _default_kalman
    if _default_kalman is None:
        with _default_kalman_lock:
            if _default_kalman is None:
                _default_kalman = SentimentKalman(process_var=process_var, meas_var=meas_var)
    return _default_kalman
