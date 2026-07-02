"""
CQI and Drift-Based Signal Gating

Uses Consensus Quality Index (CQI) and drift metrics to gate signal volume
and maintain signal quality across domains.
"""

from __future__ import annotations

import time
import random
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from enum import Enum

from merid.signals.store import get_signal_store
from merid.signals.unified_manager import get_unified_signal_manager
from utils.logger import get_logger

logger = get_logger("signals.cqi_gating")


class GatingDecision(Enum):
    """Gating decision for signals"""
    ALLOW = "allow"
    THROTTLE = "throttle"
    SUPPRESS = "suppress"


class QualityBand(Enum):
    """CQI quality bands"""
    EXCELLENT = "excellent"  # 0.8-1.0
    GOOD = "good"           # 0.6-0.8
    NEUTRAL = "neutral"     # 0.4-0.6
    POOR = "poor"          # 0.2-0.4
    CRITICAL = "critical"   # 0.0-0.2


@dataclass
class GatingThresholds:
    """Thresholds for signal gating based on quality metrics"""
    # CQI thresholds
    min_cqi_for_signals: float = 0.4
    throttle_cqi_threshold: float = 0.6
    
    # Drift thresholds
    max_drift_psi: float = 0.2  # Population Stability Index
    max_stale_trade_pct: float = 0.3
    min_fresh_trade_pct: float = 0.1
    
    # Performance thresholds
    max_brier_score: float = 0.25
    min_pnl_per_risk: float = -0.1
    
    # Throttling parameters
    throttle_factor: float = 0.5  # Reduce signals by this factor when throttling
    suppression_duration: int = 3600  # 1 hour in seconds


@dataclass
class DomainQualityMetrics:
    """Quality metrics for a domain"""
    domain: str
    cqi_score: float
    cqi_band: QualityBand
    drift_psi: float
    stale_trade_pct: float
    fresh_trade_pct: float
    brier_score: float
    pnl_per_risk: float
    decay_discipline: float
    timestamp: float
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "domain": self.domain,
            "cqi_score": self.cqi_score,
            "cqi_band": self.cqi_band.value,
            "drift_psi": self.drift_psi,
            "stale_trade_pct": self.stale_trade_pct,
            "fresh_trade_pct": self.fresh_trade_pct,
            "brier_score": self.brier_score,
            "pnl_per_risk": self.pnl_per_risk,
            "decay_discipline": self.decay_discipline,
            "timestamp": self.timestamp,
        }


class CQIGatingManager:
    """Manages signal gating based on CQI and drift metrics"""
    
    def __init__(self, thresholds: Optional[GatingThresholds] = None):
        self._thresholds = thresholds or GatingThresholds()
        self._signal_store = get_signal_store()
        self._unified_manager = get_unified_signal_manager()
        
        # Cache for quality metrics
        self._quality_cache: Dict[str, DomainQualityMetrics] = {}
        self._cache_ttl = 300  # 5 minutes
        
        # Gating state
        self._suppressed_domains: Dict[str, float] = {}  # domain -> suppression end time
        self._throttled_domains: Dict[str, float] = {}   # domain -> throttle factor
    
    def gate_signal(self, signal: Dict[str, Any]) -> Tuple[GatingDecision, Optional[Dict[str, Any]]]:
        """Gate a signal based on domain quality metrics"""
        try:
            domain = signal.get("domain", "")
            if not domain:
                return GatingDecision.ALLOW, signal
            
            # Get current quality metrics for domain
            quality_metrics = self._get_domain_quality_metrics(domain)
            if not quality_metrics:
                logger.warning(f"No quality metrics available for domain {domain}, allowing signal")
                return GatingDecision.ALLOW, signal
            
            # Check if domain is currently suppressed
            if self._is_domain_suppressed(domain):
                suppressed_signal = self._create_suppressed_signal(signal, "Domain quality suppression")
                return GatingDecision.SUPPRESS, suppressed_signal
            
            # Evaluate gating decision
            decision, reason = self._evaluate_gating_decision(signal, quality_metrics)
            
            if decision == GatingDecision.ALLOW:
                return GatingDecision.ALLOW, signal
            elif decision == GatingDecision.THROTTLE:
                throttled_signal = self._apply_throttling(signal, quality_metrics)
                
                # Deterministic hard-suppress for severely degraded CQI.
                # A score < 0.3 is POOR/CRITICAL territory — always suppress at
                # this level rather than using random.random() which breaks
                # reproducibility and makes audit trails unreliable.
                domain = signal.get("domain", "")
                if quality_metrics.cqi_score < 0.3:
                    logger.info(
                        "Suppressing throttled signal in %s: "
                        "CQI=%.3f below hard-suppress threshold (0.30)",
                        domain, quality_metrics.cqi_score,
                    )
                    suppressed_signal = self._create_suppressed_signal(signal, "CQI below hard-suppress threshold")
                    return GatingDecision.SUPPRESS, suppressed_signal
                
                return GatingDecision.THROTTLE, throttled_signal
            else:
                suppressed_signal = self._create_suppressed_signal(signal, reason)
                return GatingDecision.SUPPRESS, suppressed_signal
                
        except Exception as e:
            logger.warning(f"Failed to gate signal: {e}")
            return GatingDecision.ALLOW, signal
    
    def update_domain_quality(self, domain: str) -> Optional[DomainQualityMetrics]:
        """Update quality metrics for a domain"""
        try:
            # Get latest CQI for domain
            cqi_data = self._signal_store.get_latest_cqi(domain)
            if not cqi_data:
                return None
            
            latest_cqi = cqi_data[0]
            
            # Get latest drift metrics for domain
            drift_data = self._signal_store.get_drift_metrics(domain, limit=1)
            latest_drift = drift_data[0] if drift_data else None
            
            # Create quality metrics
            quality_metrics = DomainQualityMetrics(
                domain=domain,
                cqi_score=latest_cqi.get("quality_index", 0.5),
                cqi_band=self._classify_cqi_band(latest_cqi.get("quality_index", 0.5)),
                drift_psi=latest_drift.get("feature_psi", 0.0) if latest_drift else 0.0,
                stale_trade_pct=latest_drift.get("stale_trade_pct", 0.0) if latest_drift else 0.0,
                fresh_trade_pct=latest_drift.get("fresh_trade_pct", 0.0) if latest_drift else 0.0,
                brier_score=latest_cqi.get("brier_component", 0.0),
                pnl_per_risk=latest_cqi.get("pnl_component", 0.0),
                decay_discipline=latest_cqi.get("decay_component", 0.0),
                timestamp=time.time()
            )
            
            # Cache the result
            self._quality_cache[domain] = quality_metrics
            
            # Update gating state based on quality
            self._update_gating_state(domain, quality_metrics)
            
            return quality_metrics
            
        except Exception as e:
            logger.warning(f"Failed to update quality metrics for {domain}: {e}")
            return None
    
    def get_domain_quality_summary(self) -> Dict[str, Any]:
        """Get summary of quality metrics across all domains"""
        summary = {
            "domains": {},
            "overall_health": 0.0,
            "suppressed_domains": list(self._suppressed_domains.keys()),
            "throttled_domains": list(self._throttled_domains.keys()),
            "timestamp": time.time()
        }
        
        total_cqi = 0.0
        domain_count = 0
        
        for domain in ["crypto", "prediction", "equity", "betting", "macro"]:
            quality = self._get_domain_quality_metrics(domain)
            if quality:
                summary["domains"][domain] = quality.to_dict()
                total_cqi += quality.cqi_score
                domain_count += 1
        
        if domain_count > 0:
            summary["overall_health"] = total_cqi / domain_count
        
        return summary
    
    def _get_domain_quality_metrics(self, domain: str) -> Optional[DomainQualityMetrics]:
        """Get cached quality metrics for a domain"""
        cached = self._quality_cache.get(domain)
        if cached and (time.time() - cached.timestamp) < self._cache_ttl:
            return cached
        
        # Update if not cached or expired
        return self.update_domain_quality(domain)
    
    def _classify_cqi_band(self, cqi_score: float) -> QualityBand:
        """Classify CQI score into quality band"""
        if cqi_score >= 0.8:
            return QualityBand.EXCELLENT
        elif cqi_score >= 0.6:
            return QualityBand.GOOD
        elif cqi_score >= 0.4:
            return QualityBand.NEUTRAL
        elif cqi_score >= 0.2:
            return QualityBand.POOR
        else:
            return QualityBand.CRITICAL
    
    def _evaluate_gating_decision(self, signal: Dict[str, Any], quality: DomainQualityMetrics) -> Tuple[GatingDecision, str]:
        """Evaluate gating decision based on quality metrics"""
        
        # Check CQI threshold
        if quality.cqi_score < self._thresholds.min_cqi_for_signals:
            logger.warning(
                f"Suppressing signal in {quality.domain}: "
                f"CQI={quality.cqi_score:.3f} < {self._thresholds.min_cqi_for_signals:.3f}, "
                f"PSI={quality.drift_psi:.3f}, stale={quality.stale_trade_pct:.3f}, fresh={quality.fresh_trade_pct:.3f}"
            )
            return GatingDecision.SUPPRESS, f"Low CQI score: {quality.cqi_score:.3f}"
        
        # Check drift metrics
        if quality.drift_psi > self._thresholds.max_drift_psi:
            logger.warning(
                f"Suppressing signal in {quality.domain}: "
                f"PSI={quality.drift_psi:.3f} > {self._thresholds.max_drift_psi:.3f}, "
                f"CQI={quality.cqi_score:.3f}, stale={quality.stale_trade_pct:.3f}, fresh={quality.fresh_trade_pct:.3f}"
            )
            return GatingDecision.SUPPRESS, f"High drift PSI: {quality.drift_psi:.3f}"
        
        if quality.stale_trade_pct > self._thresholds.max_stale_trade_pct:
            logger.warning(
                f"Suppressing signal in {quality.domain}: "
                f"stale_trade_pct={quality.stale_trade_pct:.3f} > {self._thresholds.max_stale_trade_pct:.3f}, "
                f"CQI={quality.cqi_score:.3f}, PSI={quality.drift_psi:.3f}, fresh={quality.fresh_trade_pct:.3f}"
            )
            return GatingDecision.SUPPRESS, f"High stale trade percentage: {quality.stale_trade_pct:.3f}"
        
        if quality.fresh_trade_pct < self._thresholds.min_fresh_trade_pct:
            logger.warning(
                f"Suppressing signal in {quality.domain}: "
                f"fresh_trade_pct={quality.fresh_trade_pct:.3f} < {self._thresholds.min_fresh_trade_pct:.3f}, "
                f"CQI={quality.cqi_score:.3f}, PSI={quality.drift_psi:.3f}, stale={quality.stale_trade_pct:.3f}"
            )
            return GatingDecision.SUPPRESS, f"Low fresh trade percentage: {quality.fresh_trade_pct:.3f}"
        
        # Check performance metrics
        if quality.brier_score > self._thresholds.max_brier_score:
            return GatingDecision.THROTTLE, f"Poor Brier score: {quality.brier_score:.3f}"
        
        if quality.pnl_per_risk < self._thresholds.min_pnl_per_risk:
            return GatingDecision.THROTTLE, f"Poor PnL per risk: {quality.pnl_per_risk:.3f}"
        
        # Check if domain should be throttled based on CQI
        if quality.cqi_score < self._thresholds.throttle_cqi_threshold:
            return GatingDecision.THROTTLE, f"Moderate CQI score: {quality.cqi_score:.3f}"
        
        return GatingDecision.ALLOW, "Quality metrics acceptable"
    
    def _is_domain_suppressed(self, domain: str) -> bool:
        """Check if a domain is currently suppressed"""
        suppression_end = self._suppressed_domains.get(domain, 0)
        return time.time() < suppression_end
    
    def _apply_throttling(self, signal: Dict[str, Any], quality: DomainQualityMetrics) -> Dict[str, Any]:
        """Apply throttling to a signal"""
        # Reduce confidence and strength
        throttled_signal = signal.copy()
        
        # Fix dict.get call with correct positional arguments
        domain = signal.get("domain", "")
        throttle_factor = self._throttled_domains.get(domain, self._thresholds.throttle_factor)
        
        if "confidence" in throttled_signal:
            throttled_signal["confidence"] *= throttle_factor
        
        if "strength" in throttled_signal:
            throttled_signal["strength"] *= throttle_factor
        
        # Add throttling annotation
        throttled_signal["features"] = throttled_signal.get("features", {})
        throttled_signal["features"]["throttled"] = True
        throttled_signal["features"]["throttle_factor"] = throttle_factor
        throttled_signal["features"]["throttle_reason"] = f"CQI: {quality.cqi_score:.3f}"
        
        return throttled_signal
    
    def _create_suppressed_signal(self, signal: Dict[str, Any], reason: str) -> Dict[str, Any]:
        """Create a suppressed signal for analysis"""
        # Build suppressed copy of the dict; do NOT call suppress_signal here
        suppressed = dict(signal)
        suppressed["suppressed"] = True
        suppressed["suppressed_reason"] = reason
        suppressed["confidence"] = 0.1

        # Ensure features dict exists
        suppressed["features"] = suppressed.get("features", {}) or {}
        suppressed["features"]["suppressed_by_cqi"] = True
        suppressed["features"]["suppression_timestamp"] = time.time()

        return suppressed
    
    def _update_gating_state(self, domain: str, quality: DomainQualityMetrics):
        """Update gating state based on quality metrics"""
        current_time = time.time()
        
        # Remove expired suppressions
        expired_suppressions = [
            d for d, end_time in self._suppressed_domains.items()
            if current_time >= end_time
        ]
        for d in expired_suppressions:
            del self._suppressed_domains[d]
            logger.info(f"Lifted suppression for domain {d}")
        
        # Apply suppression for critical quality
        if quality.cqi_band in [QualityBand.CRITICAL, QualityBand.POOR]:
            suppression_end = current_time + self._thresholds.suppression_duration
            self._suppressed_domains[domain] = suppression_end
            logger.warning(f"Applied suppression to domain {domain} due to {quality.cqi_band.value} quality")
        
        # Apply throttling for neutral quality
        elif quality.cqi_band == QualityBand.NEUTRAL:
            self._throttled_domains[domain] = self._thresholds.throttle_factor
        else:
            # Remove throttling for good/excellent quality
            if domain in self._throttled_domains:
                del self._throttled_domains[domain]
                logger.info(f"Removed throttling for domain {domain} due to {quality.cqi_band.value} quality")


# Singleton instance
_gating_manager: Optional[CQIGatingManager] = None


def get_cqi_gating_manager(thresholds: Optional[GatingThresholds] = None) -> CQIGatingManager:
    """Get the singleton CQI gating manager"""
    global _gating_manager
    if _gating_manager is None:
        _gating_manager = CQIGatingManager(thresholds)
    return _gating_manager


def gate_signal_with_cqi(signal: Dict[str, Any]) -> Tuple[GatingDecision, Optional[Dict[str, Any]]]:
    """Gate a signal using CQI and drift metrics"""
    manager = get_cqi_gating_manager()
    return manager.gate_signal(signal)


def update_all_domain_quality() -> Dict[str, Any]:
    """Update quality metrics for all domains"""
    manager = get_cqi_gating_manager()
    
    domains = ["crypto", "prediction", "equity", "betting", "macro"]
    updated_count = 0
    
    for domain in domains:
        if manager.update_domain_quality(domain):
            updated_count += 1
    
    return manager.get_domain_quality_summary()
