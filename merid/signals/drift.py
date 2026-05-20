"""§6 Drift detection & Consensus Quality Index (CQI).

Monitors:
  - Per-domain Brier/LogLoss vs baselines
  - Feature distribution drift (PSI approximation)
  - Decay discipline: how often the swarm trades on stale vs fresh signals
  - CQI: composite quality metric that feeds back into risk/weighting

CQI = w1*brier + w2*pnl_per_risk + w3*(1-drift) + w4*decay_discipline
Band: good (>0.65), neutral (0.35-0.65), poor (<0.35)
"""

from __future__ import annotations

import threading
import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from merid.signals.decay import (
    DecayEnvelope,
    SignalDomain,
    decay_weight_at,
    get_decay_config,
)

from utils.logger import get_logger

logger = get_logger("merid.signals.drift")


# ── Domain drift metrics ──────────────────────────────────────────────

@dataclass
class DomainDriftMetric:
    """Per-domain drift and quality metrics for a time window."""
    domain: str = ""
    window: str = "24h"

    # Accuracy
    brier_score: float = 0.25        # 0 = perfect, 1 = worst
    log_loss: float = 0.69           # ln(2) = random baseline

    # PnL
    pnl_per_risk: float = 0.0       # PnL / max drawdown or similar
    realized_pnl_usd: float = 0.0
    trade_count: int = 0

    # Feature drift (PSI-like)
    feature_psi: float = 0.0        # 0 = no drift, >0.2 = significant

    # Decay discipline
    decay_discipline: float = 0.5   # 0-1: fraction of trades based on fresh signals
    stale_trade_count: int = 0      # trades where avg signal freshness < threshold
    fresh_trade_count: int = 0      # trades where avg signal freshness > threshold
    avg_signal_freshness: float = 0.5

    timestamp: float = field(default_factory=time.time)

    @property
    def stale_trade_pct(self) -> float:
        total = self.stale_trade_count + self.fresh_trade_count
        if total == 0:
            return 0.0
        return self.stale_trade_count / total

    @property
    def fresh_trade_pct(self) -> float:
        return 1.0 - self.stale_trade_pct

    def to_dict(self) -> Dict[str, Any]:
        return {
            "domain": self.domain,
            "window": self.window,
            "brier_score": round(self.brier_score, 4),
            "log_loss": round(self.log_loss, 4),
            "pnl_per_risk": round(self.pnl_per_risk, 4),
            "realized_pnl_usd": round(self.realized_pnl_usd, 2),
            "trade_count": self.trade_count,
            "feature_psi": round(self.feature_psi, 4),
            "decay_discipline": round(self.decay_discipline, 4),
            "stale_trade_pct": round(self.stale_trade_pct, 4),
            "fresh_trade_pct": round(self.fresh_trade_pct, 4),
            "avg_signal_freshness": round(self.avg_signal_freshness, 4),
            "timestamp": self.timestamp,
        }


# ── CQI ───────────────────────────────────────────────────────────────

@dataclass
class ConsensusQualityIndex:
    """Composite quality metric for a domain."""
    domain: str = ""
    quality_index: float = 0.5       # 0-1
    band: str = "neutral"            # good, neutral, poor
    window: str = "24h"

    # Components
    brier_component: float = 0.5     # inverted: 1 - brier (higher = better)
    pnl_component: float = 0.5       # normalized PnL per risk
    drift_component: float = 0.5     # 1 - feature_psi (higher = less drift)
    decay_component: float = 0.5     # decay discipline score

    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "domain": self.domain,
            "quality_index": round(self.quality_index, 4),
            "band": self.band,
            "window": self.window,
            "components": {
                "brier": round(self.brier_component, 4),
                "pnl": round(self.pnl_component, 4),
                "drift": round(self.drift_component, 4),
                "decay": round(self.decay_component, 4),
            },
            "timestamp": self.timestamp,
        }


def classify_band(quality_index: float) -> str:
    if quality_index >= 0.65:
        return "good"
    elif quality_index >= 0.35:
        return "neutral"
    return "poor"


# ── DriftDetector — the engine ────────────────────────────────────────

class DriftDetector:
    """Monitors drift, decay discipline, and computes CQI per domain.

    Feed it trade outcomes and signal snapshots, and it computes
    rolling quality metrics.
    """

    # CQI weights
    W_BRIER = 0.30
    W_PNL = 0.25
    W_DRIFT = 0.20
    W_DECAY = 0.25

    FRESHNESS_THRESHOLD = 0.40  # below this avg freshness → "stale trade"

    def __init__(self):
        self._outcomes: Dict[str, List[Dict[str, Any]]] = {}  # domain → [{predicted, actual, freshness, ts}]
        self._drift_history: Dict[str, List[DomainDriftMetric]] = {}
        self._cqi_history: Dict[str, List[ConsensusQualityIndex]] = {}
        self._feature_baselines: Dict[str, Dict[str, float]] = {}  # domain → {feature: baseline_mean}

    # ── Record outcomes ───────────────────────────────────────────────

    def record_outcome(
        self,
        domain: str,
        predicted_prob: float,
        actual_outcome: float,  # 0 or 1 for binary, or continuous
        pnl_usd: float = 0.0,
        signal_freshness: float = 0.5,  # avg decay_weight of driving signals
        timestamp: Optional[float] = None,
    ):
        """Record a trade/prediction outcome for drift tracking."""
        ts = timestamp or time.time()
        self._outcomes.setdefault(domain, []).append({
            "predicted": predicted_prob,
            "actual": actual_outcome,
            "pnl_usd": pnl_usd,
            "signal_freshness": signal_freshness,
            "timestamp": ts,
        })

    # ── Record feature baseline ───────────────────────────────────────

    def set_feature_baseline(self, domain: str, feature_means: Dict[str, float]):
        """Set baseline feature distribution means for PSI computation."""
        self._feature_baselines[domain] = feature_means

    def compute_psi(self, domain: str, current_means: Dict[str, float]) -> float:
        """Compute Population Stability Index (simplified) for a domain.

        PSI = sum( (actual_i - expected_i) * ln(actual_i / expected_i) )
        Simplified: use means of key features.
        """
        baseline = self._feature_baselines.get(domain, {})
        if not baseline or not current_means:
            return 0.0

        psi = 0.0
        for key in baseline:
            if key in current_means:
                exp = max(baseline[key], 0.001)
                act = max(current_means[key], 0.001)
                # Normalize to proportions
                exp_norm = exp / (exp + act) if (exp + act) > 0 else 0.5
                act_norm = act / (exp + act) if (exp + act) > 0 else 0.5
                if exp_norm > 0 and act_norm > 0:
                    psi += (act_norm - exp_norm) * math.log(act_norm / exp_norm)

        return abs(psi)

    # ── Compute drift metrics ─────────────────────────────────────────

    def compute_drift(
        self,
        domain: str,
        window_seconds: float = 86400,
        now: Optional[float] = None,
    ) -> DomainDriftMetric:
        """Compute drift metrics for a domain over a time window."""
        now = now or time.time()
        cutoff = now - window_seconds

        outcomes = [o for o in self._outcomes.get(domain, []) if o["timestamp"] > cutoff]

        if not outcomes:
            return DomainDriftMetric(domain=domain, timestamp=now)

        # Brier score
        brier = sum(
            (o["predicted"] - o["actual"]) ** 2 for o in outcomes
        ) / len(outcomes)

        # Log loss (binary)
        eps = 1e-7
        log_loss_vals = []
        for o in outcomes:
            p = max(eps, min(1 - eps, o["predicted"]))
            a = o["actual"]
            ll = -(a * math.log(p) + (1 - a) * math.log(1 - p))
            log_loss_vals.append(ll)
        log_loss = sum(log_loss_vals) / len(log_loss_vals) if log_loss_vals else 0.69

        # PnL
        total_pnl = sum(o["pnl_usd"] for o in outcomes)
        max_dd = max(abs(o["pnl_usd"]) for o in outcomes) if outcomes else 1.0
        pnl_per_risk = total_pnl / max(max_dd, 1.0)

        # Decay discipline
        freshness_vals = [o["signal_freshness"] for o in outcomes]
        avg_freshness = sum(freshness_vals) / len(freshness_vals) if freshness_vals else 0.5
        stale_count = sum(1 for f in freshness_vals if f < self.FRESHNESS_THRESHOLD)
        fresh_count = len(freshness_vals) - stale_count
        discipline = fresh_count / max(len(freshness_vals), 1)

        # Feature PSI (if baseline exists)
        psi = 0.0  # Would compute from current feature distributions

        window_label = f"{int(window_seconds / 3600)}h" if window_seconds < 86400 else f"{int(window_seconds / 86400)}d"

        metric = DomainDriftMetric(
            domain=domain,
            window=window_label,
            brier_score=brier,
            log_loss=log_loss,
            pnl_per_risk=pnl_per_risk,
            realized_pnl_usd=total_pnl,
            trade_count=len(outcomes),
            feature_psi=psi,
            decay_discipline=discipline,
            stale_trade_count=stale_count,
            fresh_trade_count=fresh_count,
            avg_signal_freshness=avg_freshness,
            timestamp=now,
        )

        self._drift_history.setdefault(domain, []).append(metric)
        return metric

    # ── Compute CQI ───────────────────────────────────────────────────

    def compute_cqi(
        self,
        domain: str,
        window_seconds: float = 86400,
        now: Optional[float] = None,
    ) -> ConsensusQualityIndex:
        """Compute Consensus Quality Index for a domain."""
        drift = self.compute_drift(domain, window_seconds, now)
        now = now or time.time()

        # Component scores (all normalized to 0-1, higher = better)
        brier_comp = max(0, 1.0 - drift.brier_score * 4)  # 0.25 brier → 0 score
        pnl_comp = min(1.0, max(0, (drift.pnl_per_risk + 1) / 2))  # -1..1 → 0..1
        drift_comp = max(0, 1.0 - drift.feature_psi * 5)  # PSI > 0.2 → poor
        decay_comp = drift.decay_discipline

        qi = (
            self.W_BRIER * brier_comp +
            self.W_PNL * pnl_comp +
            self.W_DRIFT * drift_comp +
            self.W_DECAY * decay_comp
        )
        qi = max(0, min(1, qi))

        cqi = ConsensusQualityIndex(
            domain=domain,
            quality_index=qi,
            band=classify_band(qi),
            window=drift.window,
            brier_component=brier_comp,
            pnl_component=pnl_comp,
            drift_component=drift_comp,
            decay_component=decay_comp,
            timestamp=now,
        )

        self._cqi_history.setdefault(domain, []).append(cqi)
        return cqi

    # ── Risk feedback ─────────────────────────────────────────────────

    def get_risk_adjustments(self, domain: str) -> Dict[str, Any]:
        """Get risk adjustment recommendations based on CQI.

        Returns multipliers for agent weights and position sizing.
        """
        history = self._cqi_history.get(domain, [])
        if not history:
            return {"size_multiplier": 1.0, "agent_weight_multiplier": 1.0, "throttle": False}

        latest = history[-1]
        if latest.band == "poor":
            return {
                "size_multiplier": 0.5,
                "agent_weight_multiplier": 0.7,
                "throttle": True,
                "reason": f"CQI poor ({latest.quality_index:.2f}) for {domain}",
            }
        elif latest.band == "neutral":
            return {
                "size_multiplier": 0.8,
                "agent_weight_multiplier": 0.9,
                "throttle": False,
                "reason": f"CQI neutral ({latest.quality_index:.2f}) for {domain}",
            }
        return {"size_multiplier": 1.0, "agent_weight_multiplier": 1.0, "throttle": False}

    # ── Reset ──────────────────────────────────────────────────────────

    def reset(self) -> None:
        """Clear all outcomes, drift history, and CQI history.  Fresh start."""
        self._outcomes.clear()
        self._drift_history.clear()
        self._cqi_history.clear()
        self._feature_baselines.clear()
        logger.info("DriftDetector reset: all outcomes and CQI history cleared")

    # ── Accessors ─────────────────────────────────────────────────────

    def get_all_cqi(self) -> Dict[str, ConsensusQualityIndex]:
        result = {}
        for domain, history in self._cqi_history.items():
            if history:
                result[domain] = history[-1]
        return result

    def get_drift_history(self, domain: str, limit: int = 20) -> List[DomainDriftMetric]:
        return self._drift_history.get(domain, [])[-limit:]

    def get_cqi_history(self, domain: str, limit: int = 20) -> List[ConsensusQualityIndex]:
        return self._cqi_history.get(domain, [])[-limit:]

    def summary(self) -> Dict[str, Any]:
        all_cqi = self.get_all_cqi()
        return {
            "domains_tracked": list(self._outcomes.keys()),
            "total_outcomes": sum(len(v) for v in self._outcomes.values()),
            "cqi_by_domain": {d: c.to_dict() for d, c in all_cqi.items()},
        }


# ── Singleton ─────────────────────────────────────────────────────────

_detector: Optional[DriftDetector] = None
# TEMPORARILY DISABLED: threading.Lock causing deadlock during startup
# TODO: Re-enable lock after startup is stable and investigate proper async synchronization
# _detector_lock = threading.Lock()
_detector_lock = None  # Disabled to prevent startup hang


def get_drift_detector() -> DriftDetector:
    global _detector
    if _detector is None:
        if _detector_lock is not None:
            with _detector_lock:
                if _detector is None:
                    _detector = DriftDetector()
        else:
            # Lock disabled - direct initialization (startup workaround)
            _detector = DriftDetector()
    return _detector
