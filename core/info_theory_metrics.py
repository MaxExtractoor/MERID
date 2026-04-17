"""
Information-theoretic metrics for drift detection and diversification.

Provides KL divergence, Shannon entropy, and information-based diversification
metrics for monitoring agent behavior, feature distributions, and portfolio composition.
"""

import threading
import numpy as np
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from datetime import datetime
from collections import defaultdict
from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class DistributionBaseline:
    """Baseline distribution for drift detection."""
    name: str
    distribution: np.ndarray
    bins: Optional[np.ndarray] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    sample_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DivergenceResult:
    """Result of KL divergence computation."""
    kl_divergence: float
    reverse_kl: float
    js_divergence: float
    threshold_breached: bool
    baseline_name: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EntropyResult:
    """Result of entropy computation."""
    shannon_entropy: float
    normalized_entropy: float
    max_entropy: float
    uncertainty_level: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)


class InformationTheoryMetrics:
    """
    Compute information-theoretic metrics for drift detection and diversification.
    
    Capabilities:
    - KL divergence between recent windows and baselines
    - Shannon entropy for distributions
    - Information-based diversification metrics
    - Baseline management and drift detection
    """
    
    def __init__(
        self,
        kl_threshold: float = 0.1,
        entropy_low_threshold: float = 0.3,
        entropy_high_threshold: float = 0.7,
        min_samples: int = 100,
    ):
        self.kl_threshold = kl_threshold
        self.entropy_low_threshold = entropy_low_threshold
        self.entropy_high_threshold = entropy_high_threshold
        self.min_samples = min_samples
        
        self._baselines: Dict[str, DistributionBaseline] = {}
        self._divergence_history: Dict[str, List[DivergenceResult]] = defaultdict(list)
        self._entropy_history: Dict[str, List[EntropyResult]] = defaultdict(list)
    
    def register_baseline(
        self,
        name: str,
        data: np.ndarray,
        bins: Optional[np.ndarray] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> DistributionBaseline:
        """
        Register a baseline distribution for drift detection.
        
        Args:
            name: Unique identifier for baseline
            data: Sample data to create distribution
            bins: Optional bin edges for histogram
            metadata: Optional metadata
            
        Returns:
            DistributionBaseline object
        """
        if bins is None:
            bins = np.linspace(data.min(), data.max(), 50)
        
        hist, _ = np.histogram(data, bins=bins, density=True)
        hist = hist / hist.sum()  # Normalize to probability distribution
        
        baseline = DistributionBaseline(
            name=name,
            distribution=hist,
            bins=bins,
            sample_count=len(data),
            metadata=metadata or {},
        )
        
        self._baselines[name] = baseline
        logger.info(f"Registered baseline '{name}' with {len(data)} samples")
        
        return baseline
    
    def compute_kl_divergence(
        self,
        recent_data: np.ndarray,
        baseline_name: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> DivergenceResult:
        """
        Compute KL divergence between recent data and baseline.
        
        Args:
            recent_data: Recent observations
            baseline_name: Name of baseline to compare against
            metadata: Optional metadata
            
        Returns:
            DivergenceResult with KL, reverse KL, and JS divergence
        """
        if baseline_name not in self._baselines:
            raise ValueError(f"Baseline '{baseline_name}' not found")
        
        baseline = self._baselines[baseline_name]
        
        # Create histogram for recent data using baseline bins
        recent_hist, _ = np.histogram(
            recent_data,
            bins=baseline.bins,
            density=True,
        )
        recent_hist = recent_hist / recent_hist.sum()
        
        # Compute KL divergence (add small epsilon to avoid log(0))
        epsilon = 1e-10
        p = baseline.distribution + epsilon
        q = recent_hist + epsilon
        
        kl_div = np.sum(p * np.log(p / q))
        reverse_kl = np.sum(q * np.log(q / p))
        
        # Jensen-Shannon divergence (symmetric)
        m = 0.5 * (p + q)
        js_div = 0.5 * np.sum(p * np.log(p / m)) + 0.5 * np.sum(q * np.log(q / m))
        
        result = DivergenceResult(
            kl_divergence=float(kl_div),
            reverse_kl=float(reverse_kl),
            js_divergence=float(js_div),
            threshold_breached=kl_div > self.kl_threshold,
            baseline_name=baseline_name,
            metadata=metadata or {},
        )
        
        self._divergence_history[baseline_name].append(result)
        
        if result.threshold_breached:
            logger.warning(
                f"KL divergence threshold breached for '{baseline_name}': "
                f"{kl_div:.4f} > {self.kl_threshold}"
            )
        
        return result
    
    def compute_shannon_entropy(
        self,
        data: np.ndarray,
        bins: Optional[int] = 50,
        name: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> EntropyResult:
        """
        Compute Shannon entropy for data distribution.
        
        Args:
            data: Observations
            bins: Number of bins for histogram
            name: Optional name for tracking
            metadata: Optional metadata
            
        Returns:
            EntropyResult with entropy and uncertainty level
        """
        hist, _ = np.histogram(data, bins=bins, density=True)
        hist = hist / hist.sum()
        
        # Shannon entropy: H(X) = -sum(p(x) * log(p(x)))
        epsilon = 1e-10
        p = hist + epsilon
        shannon_entropy = -np.sum(p * np.log2(p))
        
        # Max entropy for uniform distribution
        max_entropy = np.log2(bins)
        normalized_entropy = shannon_entropy / max_entropy
        
        # Classify uncertainty level
        if normalized_entropy < self.entropy_low_threshold:
            uncertainty_level = "low"
        elif normalized_entropy > self.entropy_high_threshold:
            uncertainty_level = "high"
        else:
            uncertainty_level = "medium"
        
        result = EntropyResult(
            shannon_entropy=float(shannon_entropy),
            normalized_entropy=float(normalized_entropy),
            max_entropy=float(max_entropy),
            uncertainty_level=uncertainty_level,
            metadata=metadata or {},
        )
        
        if name:
            self._entropy_history[name].append(result)
        
        return result
    
    def compute_portfolio_entropy(
        self,
        weights: np.ndarray,
    ) -> float:
        """
        Compute entropy of portfolio weights.
        
        High entropy = well-diversified
        Low entropy = concentrated
        
        Args:
            weights: Portfolio weights (must sum to 1)
            
        Returns:
            Shannon entropy of weights
        """
        if not np.isclose(weights.sum(), 1.0):
            raise ValueError("Weights must sum to 1.0")
        
        epsilon = 1e-10
        w = weights + epsilon
        entropy = -np.sum(w * np.log2(w))
        
        return float(entropy)
    
    def compute_information_diversification(
        self,
        returns: np.ndarray,
        weights: np.ndarray,
    ) -> Dict[str, float]:
        """
        Compute information-theoretic diversification metrics.
        
        Uses entropy and mutual information to measure how much
        independent information each asset adds.
        
        Args:
            returns: Asset returns (n_samples, n_assets)
            weights: Portfolio weights
            
        Returns:
            Dict with diversification metrics
        """
        n_assets = returns.shape[1]
        
        # Portfolio entropy
        portfolio_entropy = self.compute_portfolio_entropy(weights)
        
        # Max entropy (uniform weights)
        max_entropy = np.log2(n_assets)
        
        # Diversification ratio
        diversification_ratio = portfolio_entropy / max_entropy
        
        # Effective number of assets (exponential of entropy)
        effective_n_assets = 2 ** portfolio_entropy
        
        # Concentration metric (inverse of diversification)
        concentration = 1.0 - diversification_ratio
        
        return {
            "portfolio_entropy": float(portfolio_entropy),
            "max_entropy": float(max_entropy),
            "diversification_ratio": float(diversification_ratio),
            "effective_n_assets": float(effective_n_assets),
            "concentration": float(concentration),
            "actual_n_assets": n_assets,
        }
    
    def get_divergence_history(
        self,
        baseline_name: str,
        limit: Optional[int] = None,
    ) -> List[DivergenceResult]:
        """Get divergence history for a baseline."""
        history = self._divergence_history.get(baseline_name, [])
        if limit:
            return history[-limit:]
        return history
    
    def get_entropy_history(
        self,
        name: str,
        limit: Optional[int] = None,
    ) -> List[EntropyResult]:
        """Get entropy history for a named series."""
        history = self._entropy_history.get(name, [])
        if limit:
            return history[-limit:]
        return history
    
    def get_baseline(self, name: str) -> Optional[DistributionBaseline]:
        """Get baseline by name."""
        return self._baselines.get(name)
    
    def list_baselines(self) -> List[str]:
        """List all registered baseline names."""
        return list(self._baselines.keys())
    
    def update_baseline(
        self,
        name: str,
        new_data: np.ndarray,
        decay_factor: float = 0.9,
    ) -> DistributionBaseline:
        """
        Update baseline with exponential moving average.
        
        Args:
            name: Baseline name
            new_data: New observations
            decay_factor: Weight for old distribution (0-1)
            
        Returns:
            Updated baseline
        """
        if name not in self._baselines:
            raise ValueError(f"Baseline '{name}' not found")
        
        baseline = self._baselines[name]
        
        # Create histogram for new data
        new_hist, _ = np.histogram(
            new_data,
            bins=baseline.bins,
            density=True,
        )
        new_hist = new_hist / new_hist.sum()
        
        # Exponential moving average
        updated_dist = decay_factor * baseline.distribution + (1 - decay_factor) * new_hist
        updated_dist = updated_dist / updated_dist.sum()
        
        baseline.distribution = updated_dist
        baseline.sample_count += len(new_data)
        
        logger.info(f"Updated baseline '{name}' with {len(new_data)} new samples")
        
        return baseline
    
    def get_drift_summary(self) -> Dict[str, Any]:
        """
        Get summary of drift detection across all baselines.
        
        Returns:
            Dict with drift statistics
        """
        summary = {
            "total_baselines": len(self._baselines),
            "baselines": {},
        }
        
        for name, baseline in self._baselines.items():
            history = self._divergence_history.get(name, [])
            
            if history:
                recent = history[-10:]
                avg_kl = np.mean([r.kl_divergence for r in recent])
                max_kl = np.max([r.kl_divergence for r in recent])
                breach_count = sum(1 for r in recent if r.threshold_breached)
                
                summary["baselines"][name] = {
                    "sample_count": baseline.sample_count,
                    "checks_performed": len(history),
                    "recent_avg_kl": float(avg_kl),
                    "recent_max_kl": float(max_kl),
                    "recent_breaches": breach_count,
                    "last_check": history[-1].timestamp.isoformat(),
                }
            else:
                summary["baselines"][name] = {
                    "sample_count": baseline.sample_count,
                    "checks_performed": 0,
                }
        
        return summary


# Global singleton
_info_theory_metrics: Optional[InformationTheoryMetrics] = None
_info_theory_metrics_lock = threading.Lock()


def get_info_theory_metrics() -> InformationTheoryMetrics:
    """Get global InformationTheoryMetrics instance."""
    global _info_theory_metrics
    if _info_theory_metrics is None:
        with _info_theory_metrics_lock:
            if _info_theory_metrics is None:
                _info_theory_metrics = InformationTheoryMetrics()
    return _info_theory_metrics
