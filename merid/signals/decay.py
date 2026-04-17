"""§1 Decay utilities — core decay math for time-aware signal processing.

Every signal in MERID carries a timestamp and a domain-specific decay rate (tau).
Older signals contribute less to consensus. This module provides:

  - DecayConfig: per-domain decay parameters
  - decay_weight(): exponential decay  e^(-age / tau)
  - DecayEnvelope: wraps a value + timestamp + weight for feature accessors
  - SignalSnapshot: frozen set of driver signals attached to an opinion/plan
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# ── Domain enum ───────────────────────────────────────────────────────

class SignalDomain(str, Enum):
    NEWS = "news"
    MACRO = "macro"
    SOCIAL = "social"
    ONCHAIN = "onchain"
    ARB = "arb"
    MEME = "meme"
    SPORTS = "sports"
    PREDICTION = "prediction"
    FUNDAMENTAL = "fundamental"


# ── Decay configuration per domain ────────────────────────────────────

@dataclass
class DecayConfig:
    """Decay parameters for a signal domain.

    tau_seconds: half-power time constant (seconds).  At t = tau, weight ≈ 0.37.
    min_weight:  floor below which the signal is considered stale/dead.
    refresh_boost: multiplier when a signal is refreshed with new data.
    """
    domain: str = "news"
    tau_seconds: float = 3600.0        # 1 hour default
    min_weight: float = 0.05           # below 5% → stale
    refresh_boost: float = 1.5         # refresh bumps weight by 1.5×
    max_age_seconds: float = 86400.0   # hard cutoff: 24h

    def to_dict(self) -> Dict[str, Any]:
        return {
            "domain": self.domain,
            "tau_seconds": self.tau_seconds,
            "min_weight": self.min_weight,
            "refresh_boost": self.refresh_boost,
            "max_age_seconds": self.max_age_seconds,
        }


# Default decay configs per domain
DEFAULT_DECAY_CONFIGS: Dict[str, DecayConfig] = {
    SignalDomain.NEWS.value: DecayConfig(
        domain="news", tau_seconds=1800, min_weight=0.05, max_age_seconds=43200,
    ),  # 30 min half-power, 12h max
    SignalDomain.MACRO.value: DecayConfig(
        domain="macro", tau_seconds=86400, min_weight=0.10, max_age_seconds=604800,
    ),  # 24h half-power, 7d max
    SignalDomain.SOCIAL.value: DecayConfig(
        domain="social", tau_seconds=600, min_weight=0.05, max_age_seconds=7200,
    ),  # 10 min half-power, 2h max
    SignalDomain.ONCHAIN.value: DecayConfig(
        domain="onchain", tau_seconds=3600, min_weight=0.05, max_age_seconds=86400,
    ),  # 1h half-power, 24h max
    SignalDomain.ARB.value: DecayConfig(
        domain="arb", tau_seconds=120, min_weight=0.10, max_age_seconds=1800,
    ),  # 2 min half-power, 30 min max
    SignalDomain.MEME.value: DecayConfig(
        domain="meme", tau_seconds=900, min_weight=0.05, max_age_seconds=14400,
    ),  # 15 min half-power, 4h max
    SignalDomain.SPORTS.value: DecayConfig(
        domain="sports", tau_seconds=7200, min_weight=0.10, max_age_seconds=86400,
    ),  # 2h half-power, 24h max
    SignalDomain.PREDICTION.value: DecayConfig(
        domain="prediction", tau_seconds=14400, min_weight=0.10, max_age_seconds=172800,
    ),  # 4h half-power, 48h max
    SignalDomain.FUNDAMENTAL.value: DecayConfig(
        domain="fundamental", tau_seconds=172800, min_weight=0.15, max_age_seconds=2592000,
    ),  # 2d half-power, 30d max
}


def get_decay_config(domain: str) -> DecayConfig:
    return DEFAULT_DECAY_CONFIGS.get(domain, DecayConfig(domain=domain))


# ── Core decay math ───────────────────────────────────────────────────

def decay_weight(
    age_seconds: float,
    tau_seconds: float = 3600.0,
    min_weight: float = 0.05,
    max_age_seconds: float = 86400.0,
) -> float:
    """Compute exponential decay weight: e^(-age / tau), clamped to [min_weight, 1.0].

    Returns 0.0 if age exceeds max_age_seconds (hard cutoff).
    """
    if age_seconds < 0:
        return 1.0
    if age_seconds > max_age_seconds:
        return 0.0
    w = math.exp(-age_seconds / tau_seconds)
    return max(min_weight, min(1.0, w))


def decay_weight_from_config(age_seconds: float, config: DecayConfig) -> float:
    """Compute decay weight using a DecayConfig."""
    return decay_weight(age_seconds, config.tau_seconds, config.min_weight, config.max_age_seconds)


def decay_weight_at(timestamp: float, domain: str, now: Optional[float] = None) -> float:
    """Compute decay weight for a signal at `timestamp` in domain `domain`."""
    now = now or time.time()
    age = now - timestamp
    config = get_decay_config(domain)
    return decay_weight_from_config(age, config)


def is_stale(timestamp: float, domain: str, now: Optional[float] = None) -> bool:
    """Check if a signal is stale (weight below min_weight or beyond max_age)."""
    w = decay_weight_at(timestamp, domain, now)
    return w <= 0.0 or w <= get_decay_config(domain).min_weight


# ── DecayEnvelope — wraps a value with decay metadata ─────────────────

@dataclass
class DecayEnvelope:
    """A signal value wrapped with its timestamp and computed decay weight.

    Used by feature accessors so agents always see value + freshness.
    """
    value: float = 0.0
    raw_value: float = 0.0          # original unweighted value
    timestamp: float = 0.0          # unix epoch
    age_seconds: float = 0.0
    decay_weight: float = 1.0
    domain: str = "news"
    label: str = ""                 # e.g., "news_sentiment", "macro_cpi_surprise"
    is_stale: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def create(
        raw_value: float,
        timestamp: float,
        domain: str,
        label: str = "",
        now: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "DecayEnvelope":
        """Factory: compute decay weight and create envelope."""
        now = now or time.time()
        age = now - timestamp
        config = get_decay_config(domain)
        w = decay_weight_from_config(age, config)
        return DecayEnvelope(
            value=raw_value * w,
            raw_value=raw_value,
            timestamp=timestamp,
            age_seconds=age,
            decay_weight=w,
            domain=domain,
            label=label,
            is_stale=(w <= 0.0 or w <= config.min_weight),
            metadata=metadata or {},
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "value": round(self.value, 6),
            "raw_value": round(self.raw_value, 6),
            "timestamp": self.timestamp,
            "age_seconds": round(self.age_seconds, 1),
            "decay_weight": round(self.decay_weight, 4),
            "domain": self.domain,
            "label": self.label,
            "is_stale": self.is_stale,
        }


# ── SignalSnapshot — frozen driver signals for opinion/plan metadata ──

@dataclass
class SignalSnapshot:
    """A snapshot of the key signals that drove an opinion or plan.

    Attached to every Opinion/Plan so we can audit what information
    the swarm was acting on and how fresh it was.
    """
    snapshot_id: str = ""
    timestamp: float = field(default_factory=time.time)
    signals: List[DecayEnvelope] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)

    def avg_freshness(self) -> float:
        """Average decay weight across all signals. 1.0 = all perfectly fresh."""
        if not self.signals:
            return 0.0
        return sum(s.decay_weight for s in self.signals) / len(self.signals)

    def stale_count(self) -> int:
        return sum(1 for s in self.signals if s.is_stale)

    def freshest_signal(self) -> Optional[DecayEnvelope]:
        if not self.signals:
            return None
        return max(self.signals, key=lambda s: s.decay_weight)

    def stalest_signal(self) -> Optional[DecayEnvelope]:
        if not self.signals:
            return None
        return min(self.signals, key=lambda s: s.decay_weight)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "timestamp": self.timestamp,
            "signal_count": len(self.signals),
            "avg_freshness": round(self.avg_freshness(), 4),
            "stale_count": self.stale_count(),
            "signals": [s.to_dict() for s in self.signals],
            "summary": self.summary,
        }


# ── Decay-weighted aggregation helpers ────────────────────────────────

def weighted_average(envelopes: List[DecayEnvelope]) -> float:
    """Compute decay-weighted average of envelope values."""
    if not envelopes:
        return 0.0
    total_weight = sum(e.decay_weight for e in envelopes)
    if total_weight == 0:
        return 0.0
    return sum(e.raw_value * e.decay_weight for e in envelopes) / total_weight


def weighted_sum(envelopes: List[DecayEnvelope]) -> float:
    """Compute sum of decay-weighted values."""
    return sum(e.value for e in envelopes)


def filter_fresh(envelopes: List[DecayEnvelope]) -> List[DecayEnvelope]:
    """Return only non-stale envelopes."""
    return [e for e in envelopes if not e.is_stale]
