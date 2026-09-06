"""Settlement-aware probability distribution for Kalshi 15m crypto binaries.

The contract settles on the simple average of 60 one-second CF RTI values in the
final minute before expiry.  The random variable to model is therefore the future
60-second average A_e, not the terminal spot S_{t_e}.  This module builds a
conditional normal distribution for A_e given the current state.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Iterable, List, Optional, Sequence, Tuple

# Same as trade_decision.py to keep vol/time conversions consistent.
_SECONDS_PER_YEAR = 365.0 * 24.0 * 60.0 * 60.0
_SETTLEMENT_WINDOW_SECONDS = 60.0
_MODEL_VERSION = "settlement-average-normal-v2-discrete"


@dataclass(frozen=True)
class SettlementState:
    """Snapshot of the settlement-relevant state at a decision instant."""

    ticker: str
    asset: str
    strike_price: float
    latest_rti: float
    latest_rti_decimal: Optional[Decimal]
    seconds_to_expiry: float
    expiry_ts: Optional[datetime]
    window_start_ts: Optional[datetime]
    now_ts: Optional[datetime]
    observed_samples: Sequence[Tuple[datetime, Decimal]]
    observed_count: int
    observed_sum: Decimal
    remaining_count: int
    latest_rti_ts: Optional[datetime]
    latest_rti_age_ms: Optional[int]
    phase: str  # "pre_window", "in_window", "expired", "invalid"
    source: str
    settlement_reference: str


@dataclass(frozen=True)
class SettlementDistribution:
    """Conditional distribution of the final 60s settlement average."""

    mean: float
    std: float
    z_score: float
    p_yes_raw: float
    observed_count: int
    remaining_count: int
    seconds_to_expiry: float
    phase: str
    forecast_method: str
    model_version: str = _MODEL_VERSION


@dataclass(frozen=True)
class SettlementWindowAccumulator:
    """Accumulator for the official one-second settlement samples.

    Holds the 60 seconds of the final settlement minute as they are observed.
    Samples are keyed by source timestamp (UTC) at one-second resolution to
    handle retransmissions and out-of-order frames deterministically.
    """

    ticker: str
    expiry_ts: datetime
    window_start_ts: datetime
    samples_by_second: dict = None  # type: ignore[assignment]

    _source_timestamps: dict = field(default_factory=dict, init=False, repr=False, compare=False)

    def __post_init__(self):
        if self.samples_by_second is None:
            object.__setattr__(self, "samples_by_second", {})

    def add_observation(self, source_ts: datetime, value: Decimal) -> None:
        """Add or update the sample for ``source_ts`` at one-second resolution."""
        if source_ts is None or value is None or not value.is_finite() or value <= 0:
            return
        # Floor to the second to align with the official 1s cadence.
        second_key = source_ts.replace(microsecond=0)
        if self.window_start_ts < second_key <= source_ts <= self.expiry_ts:
            previous = self._source_timestamps.get(second_key)
            if previous is None or source_ts > previous:
                self.samples_by_second[second_key] = value
                self._source_timestamps[second_key] = source_ts
            elif source_ts == previous and self.samples_by_second[second_key] != value:
                raise ValueError("Conflicting settlement samples at the same source timestamp")

    def observed_sum(self) -> Decimal:
        return sum(self.samples_by_second.values(), Decimal("0"))

    def observed_count(self) -> int:
        return len(self.samples_by_second)

    def observed_average(self) -> Optional[Decimal]:
        count = self.observed_count()
        if count == 0:
            return None
        return self.observed_sum() / count

    def remaining_count(self, now_ts: datetime) -> int:
        """Number of unobserved one-second slots from ``now_ts`` to expiry."""
        if now_ts >= self.expiry_ts:
            return 0
        elapsed_in_window = max(
            0,
            min(
                int(_SETTLEMENT_WINDOW_SECONDS),
                math.floor((now_ts - self.window_start_ts).total_seconds()),
            ),
        )
        return max(0, int(_SETTLEMENT_WINDOW_SECONDS) - elapsed_in_window)


def _to_utc_datetime(ts: Any) -> Optional[datetime]:
    """Convert a timestamp value to a timezone-aware UTC datetime."""
    if ts is None:
        return None
    if isinstance(ts, datetime):
        if ts.tzinfo is None:
            return ts.replace(tzinfo=timezone.utc)
        return ts.astimezone(timezone.utc)
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    return None


def _source_ts_to_datetime(source_ts_ms: Optional[int]) -> Optional[datetime]:
    if source_ts_ms is None:
        return None
    return datetime.fromtimestamp(source_ts_ms / 1000.0, tz=timezone.utc)


def _price_volatility(
    annualized_vol: float,
    reference_price: float,
) -> float:
    """Convert annualized return vol to price units per sqrt(year).

    ``annualized_vol`` is a fraction (e.g. 0.60 for 60% per year).
    The arithmetic Bachelier volatility for dollar/price moves is
    ``sigma_price = annualized_vol * reference_price``.
    """
    ref = float(reference_price)
    vol = float(annualized_vol)
    if not math.isfinite(ref) or ref <= 0 or not math.isfinite(vol) or vol < 0:
        raise ValueError("Settlement price and volatility must be finite and valid")
    result = vol * ref
    if not math.isfinite(result):
        raise ValueError("Settlement price volatility overflow")
    return result


def _group_observations_by_second(
    observations: Iterable[Any],
    window_start: datetime,
    window_end: datetime,
) -> List[Tuple[datetime, Decimal]]:
    """Return a list of (second, value) tuples within the settlement window.

    If multiple frames fall in the same second, the latest value wins.
    Only positive, finite values are kept.
    """
    by_second: dict = {}
    for obs in observations:
        if obs is None:
            continue
        ts = None
        if hasattr(obs, "source_ts_ms"):
            ts = _source_ts_to_datetime(getattr(obs, "source_ts_ms", None))
        if ts is None and hasattr(obs, "source_ts"):
            ts = _to_utc_datetime(getattr(obs, "source_ts", None))

        val = None
        if hasattr(obs, "value_decimal"):
            val = getattr(obs, "value_decimal", None)
        if val is None and hasattr(obs, "value"):
            v = getattr(obs, "value", None)
            if v is not None:
                try:
                    val = Decimal(str(v))
                except Exception:
                    val = None

        if ts is None or val is None or not val.is_finite() or val <= 0:
            continue
        second_key = ts.replace(microsecond=0)
        if window_start < second_key <= ts <= window_end:
            previous = by_second.get(second_key)
            if previous is None or ts > previous[0]:
                by_second[second_key] = (ts, val)
            elif ts == previous[0] and val != previous[1]:
                raise ValueError("Conflicting settlement samples at the same source timestamp")

    return [(second, value) for second, (_, value) in sorted(by_second.items())]


def build_settlement_state(
    *,
    ticker: str,
    asset: str,
    strike_price: float,
    expiry_ts: Any,
    now_ts: Any,
    latest_rti: float,
    latest_rti_decimal: Optional[Decimal] = None,
    latest_rti_ts: Optional[Any] = None,
    rti_history: Optional[Sequence[Any]] = None,
    source: str = "cf_rti",
    settlement_reference: str = "cfb_rti_live",
) -> SettlementState:
    """Build a SettlementState from the current CF RTI state and history."""

    expiry_dt = _to_utc_datetime(expiry_ts)
    now_dt = _to_utc_datetime(now_ts)
    latest_dt = _to_utc_datetime(latest_rti_ts)

    if expiry_dt is None or now_dt is None:
        return SettlementState(
            ticker=ticker,
            asset=asset,
            strike_price=float(strike_price),
            latest_rti=float(latest_rti),
            latest_rti_decimal=latest_rti_decimal,
            seconds_to_expiry=0.0,
            expiry_ts=None,
            window_start_ts=None,
            now_ts=now_dt,
            observed_samples=[],
            observed_count=0,
            observed_sum=Decimal("0"),
            remaining_count=0,
            latest_rti_ts=latest_dt,
            latest_rti_age_ms=None,
            phase="invalid",
            source=source,
            settlement_reference=settlement_reference,
        )

    window_start_dt = expiry_dt - timedelta(seconds=int(_SETTLEMENT_WINDOW_SECONDS))
    seconds_to_expiry = (expiry_dt - now_dt).total_seconds()

    if now_dt >= expiry_dt:
        phase = "expired"
    elif now_dt >= window_start_dt:
        phase = "in_window"
    else:
        phase = "pre_window"

    # Observed samples are those inside the settlement window up to ``now``.
    window_end = min(now_dt, expiry_dt)
    if rti_history is not None:
        observed = _group_observations_by_second(rti_history, window_start_dt, window_end)
    else:
        observed = []

    observed_sum = sum(v for _, v in observed) if observed else Decimal("0")
    observed_count = len(observed)

    # Remaining unobserved seconds.
    if now_dt >= expiry_dt:
        remaining_count = 0
    else:
        elapsed = max(0, min(_SETTLEMENT_WINDOW_SECONDS, (now_dt - window_start_dt).total_seconds()))
        remaining_count = max(0, int(_SETTLEMENT_WINDOW_SECONDS) - int(elapsed))

    latest_rti_age_ms = None
    if latest_dt is not None and now_dt is not None:
        latest_rti_age_ms = max(0, int((now_dt - latest_dt).total_seconds() * 1000))

    return SettlementState(
        ticker=ticker,
        asset=asset,
        strike_price=float(strike_price),
        latest_rti=float(latest_rti),
        latest_rti_decimal=latest_rti_decimal,
        seconds_to_expiry=float(seconds_to_expiry),
        expiry_ts=expiry_dt,
        window_start_ts=window_start_dt,
        now_ts=now_dt,
        observed_samples=observed,
        observed_count=observed_count,
        observed_sum=observed_sum,
        remaining_count=remaining_count,
        latest_rti_ts=latest_dt,
        latest_rti_age_ms=latest_rti_age_ms,
        phase=phase,
        source=source,
        settlement_reference=settlement_reference,
    )


def compute_settlement_distribution(
    state: SettlementState,
    annualized_vol: float,
) -> SettlementDistribution:
    """Return a zero-drift Bachelier distribution on 60 right-endpoint samples.

    The schedule follows Kalshi's documented quarter-hour feed window
    (expiry - 60s, expiry]: https://docs.kalshi.com/websockets/cfbenchmarks-value.
    Flooring subsecond source frames is a local cadence approximation, not an
    exchange correction policy. All elapsed slots must be present; unavailable
    inputs raise ValueError rather than implying a known settlement outcome.
    Callers must retain provenance/freshness gates and must not trade a fallback.

    For future offsets u_i in seconds, variance is sigma_price**2 / year_seconds
    times sum(min(u_i, u_j)) / 60**2. The continuous-limit variance formulas
    retained below are reference identities, not the implemented discrete law.
    """

    strike = float(state.strike_price)
    latest = float(state.latest_rti)
    tte = float(state.seconds_to_expiry)
    window_s = _SETTLEMENT_WINDOW_SECONDS
    price_vol = _price_volatility(annualized_vol, latest)

    if state.phase not in {"pre_window", "in_window", "expired"}:
        raise ValueError("Invalid settlement phase")
    if not math.isfinite(strike) or strike <= 0 or not math.isfinite(tte):
        raise ValueError("Invalid settlement strike or time")
    expected_phase = "expired" if tte <= 0 else ("in_window" if tte <= window_s else "pre_window")
    if state.phase != expected_phase:
        raise ValueError("Inconsistent settlement phase and time")
    if state.expiry_ts is None or state.now_ts is None or state.expiry_ts.microsecond:
        raise ValueError("Settlement timestamps require a whole-second expiry")
    if abs((state.expiry_ts - state.now_ts).total_seconds() - tte) > 1e-6:
        raise ValueError("Inconsistent settlement timestamps")
    if state.latest_rti_ts is not None and state.latest_rti_ts > state.now_ts:
        raise ValueError("Future settlement reference")
    schedule = [state.expiry_ts - timedelta(seconds=i) for i in range(59, -1, -1)]
    expected_samples = {ts for ts in schedule if ts <= state.now_ts}
    actual_samples = dict(state.observed_samples)
    if (set(actual_samples) != expected_samples
            or len(actual_samples) != state.observed_count
            or len(state.observed_samples) != state.observed_count
            or any(not v.is_finite() or v <= 0 for v in actual_samples.values())
            or sum(actual_samples.values(), Decimal("0")) != state.observed_sum):
        raise ValueError("Incomplete or inconsistent elapsed settlement samples")
    offsets = [(ts - state.now_ts).total_seconds() for ts in schedule if ts > state.now_ts]
    variance_seconds = math.fsum(
        (2 * (len(offsets) - i) - 1) * u for i, u in enumerate(offsets)
    ) / window_s ** 2

    if state.phase == "expired":
        # Degenerate: all settlement samples are fixed.  Use the observed average.
        if state.observed_count > 0:
            mean = float(state.observed_sum / state.observed_count)
        else:
            mean = latest
        std = 0.0
        z = _z_score(mean, std, strike)
        p_yes = _probability_yes(mean, std, strike)
        return SettlementDistribution(
            mean=mean,
            std=std,
            z_score=z,
            p_yes_raw=p_yes,
            observed_count=state.observed_count,
            remaining_count=0,
            seconds_to_expiry=0.0,
            phase="expired",
            forecast_method="observed_average",
        )

    if state.phase == "pre_window":
        # T >= W: no samples fixed yet, forecast mean is the current latent level.
        effective_t_years = variance_seconds / _SECONDS_PER_YEAR
        mean = latest
        std = price_vol * math.sqrt(effective_t_years)
        z = _z_score(mean, std, strike)
        p_yes = _probability_yes(mean, std, strike)
        return SettlementDistribution(
            mean=mean,
            std=std,
            z_score=z,
            p_yes_raw=p_yes,
            observed_count=0,
            remaining_count=int(window_s),
            seconds_to_expiry=tte,
            phase="pre_window",
            forecast_method="zero_drift_forward_average",
        )

    # Phase: in_window.  Some samples are realized, the rest are forecast from latest.
    n_obs = state.observed_count
    n_rem = max(0, int(window_s) - n_obs)
    r_seconds = min(window_s, tte)
    r_years = r_seconds / _SECONDS_PER_YEAR

    observed_avg = 0.0
    if n_obs > 0:
        observed_avg = float(state.observed_sum / n_obs)

    # Conditional mean: (n_o * A_o + n_r * S_t) / 60
    if n_obs + n_rem > 0:
        mean = (n_obs * observed_avg + n_rem * latest) / (n_obs + n_rem)
    else:
        mean = latest

    # Variance of a 60-second average with R seconds of residual Brownian motion.
    # Var(A_e | F_t) = sigma_price^2 * R^3 / (3 * W^2)  with R,W in years.
    if n_rem > 0 and r_years > 0:
        var = (price_vol ** 2) * variance_seconds / _SECONDS_PER_YEAR
        # Equivalent in seconds as a check: var = sigma_price^2 * R_s^3 / (3*W_s^2*_SECONDS_PER_YEAR)
    else:
        var = 0.0

    std = math.sqrt(max(0.0, var))
    z = _z_score(mean, std, strike)
    p_yes = _probability_yes(mean, std, strike)

    return SettlementDistribution(
        mean=mean,
        std=std,
        z_score=z,
        p_yes_raw=p_yes,
        observed_count=n_obs,
        remaining_count=n_rem,
        seconds_to_expiry=tte,
        phase="in_window",
        forecast_method="partial_realization_forward_average",
    )


def _z_score(mean: float, std: float, strike: float) -> float:
    if not math.isfinite(std) or std < 0:
        raise ValueError("Invalid settlement standard deviation")
    if std == 0:
        return float("inf") if mean > strike else (float("-inf") if mean < strike else 0.0)
    return (mean - strike) / std


def _probability_yes(mean: float, std: float, strike: float) -> float:
    if not math.isfinite(mean) or not math.isfinite(strike):
        raise ValueError("Invalid settlement mean or strike")
    if not math.isfinite(std) or std < 0:
        raise ValueError("Invalid settlement standard deviation")
    if std == 0:
        return 1.0 if mean >= strike else 0.0
    try:
        return statistics.NormalDist().cdf((mean - strike) / std)
    except Exception:
        return 0.5


def probability_yes(distribution: SettlementDistribution, strike: Optional[float] = None) -> float:
    if strike is not None:
        return _probability_yes(distribution.mean, distribution.std, strike)
    return distribution.p_yes_raw
