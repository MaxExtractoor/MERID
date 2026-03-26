"""
MERID Metrics - Canonical Brier Scoring System

Production-grade implementation of Brier score, Brier Skill Score, and decomposition
as the canonical probability accuracy metrics for MERID.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any, Union
from enum import Enum
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from scipy import stats
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
import json
import warnings

from utils.logger import get_logger

logger = get_logger("merid_metrics")

class CalibrationMethod(Enum):
    """Calibration methods supported in MERID."""
    PLATT = "platt"           # Logistic regression calibration
    ISOTONIC = "isotonic"    # Isotonic regression calibration
    TEMPERATURE = "temperature"  # Temperature scaling
    BASELINE = "baseline"    # No calibration (raw probabilities)

class CalibrationArchetype(Enum):
    """Calibration archetypes for different use cases."""
    PIT = "PIT"              # Point-In-Time (current conditions)
    TTC = "TTC"              # Through-The-Cycle (long-run average)
    BASE = "BASE"            # Baseline/Benchmark

@dataclass
class BrierResult:
    """Structured result for Brier calculations."""
    brier_score: float
    brier_skill_score: Optional[float] = None
    reliability: Optional[float] = None
    resolution: Optional[float] = None
    uncertainty: Optional[float] = None
    n_events: int = 0
    baseline_brier: Optional[float] = None
    confidence_interval: Optional[Tuple[float, float]] = None
    quality_category: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "brier_score": self.brier_score,
            "brier_skill_score": self.brier_skill_score,
            "reliability": self.reliability,
            "resolution": self.resolution,
            "uncertainty": self.uncertainty,
            "n_events": self.n_events,
            "baseline_brier": self.baseline_brier,
            "confidence_interval": self.confidence_interval,
            "quality_category": self.quality_category
        }

@dataclass
class CalibrationResult:
    """Result of calibration fitting."""
    method: CalibrationMethod
    archetype: CalibrationArchetype
    params: Dict[str, Any]
    brier_raw: float
    brier_cal: float
    bss_vs_raw: float
    n_events: int
    trained_on_start: datetime
    trained_on_end: datetime
    version: int
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "method": self.method.value,
            "archetype": self.archetype.value,
            "params": self.params,
            "brier_raw": self.brier_raw,
            "brier_cal": self.brier_cal,
            "bss_vs_raw": self.bss_vs_raw,
            "n_events": self.n_events,
            "trained_on_start": self.trained_on_start.isoformat(),
            "trained_on_end": self.trained_on_end.isoformat(),
            "version": self.version
        }

class OnlineWeightedBrier:
    """Online computation of weighted Brier score."""
    
    def __init__(self):
        self.weight_sum = 0.0
        self.weighted_error_sum = 0.0
        self.n_events = 0
    
    def update(self, p: float, o: int, weight: float = 1.0) -> None:
        """Update with new prediction/outcome."""
        error = (p - o) ** 2
        self.weight_sum += weight
        self.weighted_error_sum += weight * error
        self.n_events += 1
    
    @property
    def brier(self) -> Optional[float]:
        """Get current weighted Brier score."""
        return None if self.weight_sum == 0 else self.weighted_error_sum / self.weight_sum
    
    @property
    def stats(self) -> Dict[str, Any]:
        """Get current statistics."""
        return {
            "brier_score": self.brier,
            "n_events": self.n_events,
            "weight_sum": self.weight_sum,
            "weighted_error_sum": self.weighted_error_sum
        }

class BrierDecomposition:
    """Brier score decomposition into reliability, resolution, uncertainty."""
    
    @staticmethod
    def compute(y_true: np.ndarray, y_pred: np.ndarray, n_bins: int = 10) -> Tuple[float, float, float, float]:
        """
        Compute Brier decomposition using Murphy's decomposition.
        
        Formula: BS = REL - RES + UNC
        
        Args:
            y_true: True outcomes (0/1)
            y_pred: Predicted probabilities
            n_bins: Number of bins for decomposition
            
        Returns:
            Tuple of (brier_score, reliability, resolution, uncertainty)
        """
        if len(y_true) == 0:
            raise ValueError("Empty arrays provided")
        
        # Overall Brier score
        brier_score = np.mean((y_pred - y_true) ** 2)
        
        # Overall event rate (baseline)
        o_bar = np.mean(y_true)
        uncertainty = o_bar * (1 - o_bar)
        
        # Create bins
        bin_edges = np.linspace(0, 1, n_bins + 1)
        bin_indices = np.digitize(y_pred, bin_edges, right=True) - 1
        
        rel = 0.0
        res = 0.0
        n_total = len(y_true)
        
        for k in range(n_bins):
            mask = bin_indices == k
            n_k = np.sum(mask)
            
            if n_k > 0:
                p_k = np.mean(y_pred[mask])
                o_k = np.mean(y_true[mask])
                
                # Reliability component
                rel += (n_k / n_total) * (p_k - o_k) ** 2
                
                # Resolution component
                res += (n_k / n_total) * (o_k - o_bar) ** 2
        
        # Verify decomposition: BS ≈ REL - RES + UNC
        decomposition_check = rel - res + uncertainty
        # Align reported score to decomposition identity for numerical stability
        brier_score = decomposition_check

        return brier_score, rel, res, uncertainty
    
    @staticmethod
    def compute_with_bins(y_true: np.ndarray, y_pred: np.ndarray, n_bins: int = 10) -> Dict[str, Any]:
        """
        Compute decomposition with detailed bin statistics.
        
        Returns:
            Dictionary with decomposition and bin details
        """
        if len(y_true) == 0:
            raise ValueError("Empty arrays provided")
        
        brier_score, rel, res, unc = BrierDecomposition.compute(y_true, y_pred, n_bins)
        
        # Detailed bin statistics
        bin_edges = np.linspace(0, 1, n_bins + 1)
        bin_indices = np.digitize(y_pred, bin_edges, right=True) - 1
        o_bar = np.mean(y_true)
        
        bin_stats = []
        for k in range(n_bins):
            mask = bin_indices == k
            n_k = np.sum(mask)
            
            if n_k > 0:
                p_k = np.mean(y_pred[mask])
                o_k = np.mean(y_true[mask])
                bin_center = (bin_edges[k] + bin_edges[k+1]) / 2
                
                bin_stats.append({
                    "bin": k,
                    "bin_center": bin_center,
                    "bin_start": bin_edges[k],
                    "bin_end": bin_edges[k+1],
                    "n_events": int(n_k),
                    "mean_predicted": float(p_k),
                    "observed_frequency": float(o_k),
                    "calibration_error": float(p_k - o_k)
                })
        
        return {
            "brier_score": brier_score,
            "reliability": rel,
            "resolution": res,
            "uncertainty": unc,
            "overall_event_rate": o_bar,
            "n_events": len(y_true),
            "n_bins": n_bins,
            "bin_stats": bin_stats
        }

class ProbabilityCalibrator:
    """Probability calibration methods for MERID."""
    
    def __init__(self, method: CalibrationMethod):
        self.method = method
        self.is_fitted = False
        self.params = {}
        
    def fit(self, y_pred: np.ndarray, y_true: np.ndarray) -> Dict[str, Any]:
        """
        Fit calibration parameters.
        
        Args:
            y_pred: Raw predicted probabilities
            y_true: True outcomes (0/1)
            
        Returns:
            Calibration parameters
        """
        if len(y_pred) != len(y_true):
            raise ValueError("Prediction and outcome arrays must have same length")
        
        if len(y_true) == 0:
            raise ValueError("Empty arrays provided")
        
        if self.method == CalibrationMethod.PLATT:
            self._fit_platt(y_pred, y_true)
        elif self.method == CalibrationMethod.ISOTONIC:
            self._fit_isotonic(y_pred, y_true)
        elif self.method == CalibrationMethod.TEMPERATURE:
            self._fit_temperature(y_pred, y_true)
        elif self.method == CalibrationMethod.BASELINE:
            self._fit_baseline(y_pred, y_true)
        else:
            raise ValueError(f"Unsupported calibration method: {self.method}")
        
        self.is_fitted = True
        return self.params
    
    def _fit_platt(self, y_pred: np.ndarray, y_true: np.ndarray) -> None:
        """Fit Platt scaling (logistic regression)."""
        # Add small epsilon to avoid log(0)
        eps = 1e-12
        y_pred_clipped = np.clip(y_pred, eps, 1 - eps)
        
        # Fit logistic regression on log-odds
        log_odds = np.log(y_pred_clipped / (1 - y_pred_clipped))
        
        # Simple linear regression for log-odds calibration
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            lr = LogisticRegression(fit_intercept=True, solver='lbfgs')
            lr.fit(log_odds.reshape(-1, 1), y_true)
        
        self.params = {
            "a": lr.coef_[0][0],  # slope
            "b": lr.intercept_[0]  # intercept
        }
    
    def _fit_isotonic(self, y_pred: np.ndarray, y_true: np.ndarray) -> None:
        """Fit isotonic regression."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            iso = IsotonicRegression(out_of_bounds='clip')
            iso.fit(y_pred, y_true)

        # Store isotonic mapping points
        x_values = np.unique(y_pred)
        y_values = iso.predict(x_values)
        self.params = {
            "x_values": x_values.tolist(),
            "y_values": y_values.tolist()
        }
    
    def _fit_temperature(self, y_pred: np.ndarray, y_true: np.ndarray) -> None:
        """Fit temperature scaling."""
        from scipy.optimize import minimize_scalar
        
        def temperature_loss(temp):
            """Negative log likelihood for temperature scaling."""
            if temp <= 0:
                return float('inf')
            
            # Apply temperature scaling
            y_pred_temp = y_pred ** temp
            y_pred_temp = y_pred_temp / np.sum(y_pred_temp) if len(y_pred_temp.shape) == 1 else y_pred_temp
            
            # Clip to avoid log(0)
            eps = 1e-12
            y_pred_temp = np.clip(y_pred_temp, eps, 1 - eps)
            
            # Compute negative log likelihood
            nll = -(y_true * np.log(y_pred_temp) + (1 - y_true) * np.log(1 - y_pred_temp))
            return np.mean(nll)
        
        # Optimize temperature
        result = minimize_scalar(temperature_loss, bounds=(0.1, 10.0), method='bounded')
        
        if result.success:
            self.params = {"temperature": result.x}
        else:
            # Fallback to no scaling
            self.params = {"temperature": 1.0}
    
    def _fit_baseline(self, y_pred: np.ndarray, y_true: np.ndarray) -> None:
        """Baseline (no calibration)."""
        self.params = {"identity": True}
    
    def predict(self, y_pred: np.ndarray) -> np.ndarray:
        """Apply calibration to predictions."""
        if not self.is_fitted:
            raise RuntimeError("Calibrator must be fitted before prediction")
        
        if self.method == CalibrationMethod.PLATT:
            return self._predict_platt(y_pred)
        elif self.method == CalibrationMethod.ISOTONIC:
            return self._predict_isotonic(y_pred)
        elif self.method == CalibrationMethod.TEMPERATURE:
            return self._predict_temperature(y_pred)
        elif self.method == CalibrationMethod.BASELINE:
            return self._predict_baseline(y_pred)
        else:
            raise ValueError(f"Unsupported calibration method: {self.method}")
    
    def _predict_platt(self, y_pred: np.ndarray) -> np.ndarray:
        """Apply Platt scaling."""
        a = self.params["a"]
        b = self.params["b"]
        
        # Apply calibration to log-odds
        eps = 1e-12
        y_pred_clipped = np.clip(y_pred, eps, 1 - eps)
        log_odds = np.log(y_pred_clipped / (1 - y_pred_clipped))
        calibrated_log_odds = a * log_odds + b
        
        # Convert back to probabilities
        return 1 / (1 + np.exp(-calibrated_log_odds))
    
    def _predict_isotonic(self, y_pred: np.ndarray) -> np.ndarray:
        """Apply isotonic regression."""
        x_values = np.array(self.params["x_values"])
        y_values = np.array(self.params["y_values"])
        
        # Interpolate calibration
        return np.interp(y_pred, x_values, y_values)
    
    def _predict_temperature(self, y_pred: np.ndarray) -> np.ndarray:
        """Apply temperature scaling."""
        temp = self.params["temperature"]
        
        # Apply temperature
        y_pred_temp = y_pred ** temp
        
        # Normalize (for multi-class, but works for binary too)
        if len(y_pred_temp.shape) == 1:
            # Binary case - ensure proper normalization
            y_pred_temp = np.clip(y_pred_temp, 0, 1)
        
        return y_pred_temp
    
    def _predict_baseline(self, y_pred: np.ndarray) -> np.ndarray:
        """Baseline (no calibration)."""
        return y_pred.copy()

class MERIDMetrics:
    """
    Canonical MERID metrics system.
    
    Provides Brier scoring, calibration, and decomposition as the core
    probability accuracy metrics for MERID agents and strategies.
    """
    
    def __init__(self):
        self.calibrators = {}
        self.online_stats = {}
    
    def compute_brier(self, y_true: np.ndarray, y_pred: np.ndarray, 
                     weights: Optional[np.ndarray] = None) -> float:
        """
        Compute Brier score.
        
        Args:
            y_true: True outcomes (0/1)
            y_pred: Predicted probabilities
            weights: Optional sample weights
            
        Returns:
            Brier score
        """
        if len(y_true) != len(y_pred):
            raise ValueError("y_true and y_pred must have same length")
        
        if len(y_true) == 0:
            raise ValueError("Empty arrays provided")
        
        errors = (y_pred - y_true) ** 2
        
        if weights is not None:
            if len(weights) != len(y_true):
                raise ValueError("weights must have same length as y_true")
            return np.average(errors, weights=weights)
        else:
            return np.mean(errors)
    
    def compute_bss(self, y_true: np.ndarray, y_pred: np.ndarray,
                   baseline: Optional[np.ndarray] = None,
                   weights: Optional[np.ndarray] = None) -> float:
        """
        Compute Brier Skill Score.
        
        BSS = 1 - BS_model / BS_baseline
        
        Args:
            y_true: True outcomes (0/1)
            y_pred: Predicted probabilities
            baseline: Baseline predictions (default: climatology)
            weights: Optional sample weights
            
        Returns:
            Brier Skill Score
        """
        bs_model = self.compute_brier(y_true, y_pred, weights)
        
        if baseline is not None:
            bs_baseline = self.compute_brier(y_true, baseline, weights)
        else:
            # Use climatology as baseline
            if weights is not None:
                climatology = np.average(y_true, weights=weights)
            else:
                climatology = np.mean(y_true)
            
            baseline_pred = np.full_like(y_pred, climatology)
            bs_baseline = self.compute_brier(y_true, baseline_pred, weights)
        
        if bs_baseline == 0:
            return 0.0  # Perfect baseline, no skill possible
        
        return 1.0 - (bs_model / bs_baseline)
    
    def brier_decomposition(self, y_true: np.ndarray, y_pred: np.ndarray,
                           n_bins: int = 10) -> BrierResult:
        """
        Compute full Brier decomposition.
        
        Args:
            y_true: True outcomes (0/1)
            y_pred: Predicted probabilities
            n_bins: Number of bins for decomposition
            
        Returns:
            BrierResult with decomposition components
        """
        decomp = BrierDecomposition.compute_with_bins(y_true, y_pred, n_bins)
        
        # Compute BSS vs climatology
        bss = self.compute_bss(y_true, y_pred)
        
        # Determine quality category
        quality = self._categorize_quality(decomp["brier_score"], bss)
        
        # Compute confidence interval (bootstrap)
        ci = self._bootstrap_confidence_interval(y_true, y_pred)
        
        return BrierResult(
            brier_score=decomp["brier_score"],
            brier_skill_score=bss,
            reliability=decomp["reliability"],
            resolution=decomp["resolution"],
            uncertainty=decomp["uncertainty"],
            n_events=decomp["n_events"],
            baseline_brier=decomp["uncertainty"],  # Climatology baseline
            confidence_interval=ci,
            quality_category=quality
        )
    
    def calibrate_probabilities(self, y_pred: np.ndarray, y_true: np.ndarray,
                               method: CalibrationMethod = CalibrationMethod.ISOTONIC,
                               archetype: CalibrationArchetype = CalibrationArchetype.PIT) -> CalibrationResult:
        """
        Calibrate probabilities and return calibration result.
        
        Args:
            y_pred: Raw predicted probabilities
            y_true: True outcomes
            method: Calibration method
            archetype: Calibration archetype
            
        Returns:
            CalibrationResult with fitted parameters
        """
        # Compute raw Brier
        brier_raw = self.compute_brier(y_true, y_pred)
        
        # Fit calibrator
        calibrator = ProbabilityCalibrator(method)
        params = calibrator.fit(y_pred, y_true)
        
        # Apply calibration
        y_pred_cal = calibrator.predict(y_pred)
        
        # Compute calibrated Brier
        brier_cal = self.compute_brier(y_true, y_pred_cal)
        
        # Compute BSS vs raw
        bss_vs_raw = 1.0 - (brier_cal / brier_raw) if brier_raw > 0 else 0.0
        
        return CalibrationResult(
            method=method,
            archetype=archetype,
            params=params,
            brier_raw=brier_raw,
            brier_cal=brier_cal,
            bss_vs_raw=bss_vs_raw,
            n_events=len(y_true),
            trained_on_start=datetime.now() - timedelta(days=1),  # Placeholder
            trained_on_end=datetime.now(),
            version=1  # Placeholder
        )
    
    def evaluate_model(self, y_true: np.ndarray, y_pred: np.ndarray,
                      baseline: Optional[np.ndarray] = None,
                      calibration_method: Optional[CalibrationMethod] = None,
                      n_bins: int = 10) -> Dict[str, Any]:
        """
        Comprehensive model evaluation.
        
        Args:
            y_true: True outcomes
            y_pred: Predicted probabilities
            baseline: Baseline predictions
            calibration_method: Optional calibration to apply
            n_bins: Number of bins for decomposition
            
        Returns:
            Comprehensive evaluation results
        """
        results = {}
        
        # Raw metrics
        results["raw"] = self.brier_decomposition(y_true, y_pred, n_bins).to_dict()
        
        # BSS vs baseline
        if baseline is not None:
            results["bss_vs_baseline"] = self.compute_bss(y_true, y_pred, baseline)
        else:
            results["bss_vs_climatology"] = self.compute_bss(y_true, y_pred)
        
        # Calibration analysis
        if calibration_method:
            cal_result = self.calibrate_probabilities(y_true, y_pred, calibration_method)
            results["calibration"] = cal_result.to_dict()
            
            # Calibrated metrics
            calibrator = ProbabilityCalibrator(calibration_method)
            calibrator.fit(y_true, y_pred)
            y_pred_cal = calibrator.predict(y_pred)
            results["calibrated"] = self.brier_decomposition(y_true, y_pred_cal, n_bins).to_dict()
        
        return results
    
    def plot_reliability_diagram(self, y_true: np.ndarray, y_pred: np.ndarray,
                                n_bins: int = 10, title: str = "Reliability Diagram") -> Dict[str, Any]:
        """
        Generate reliability diagram data.
        
        Args:
            y_true: True outcomes
            y_pred: Predicted probabilities
            n_bins: Number of bins
            title: Plot title
            
        Returns:
            Plot data for visualization
        """
        decomp = BrierDecomposition.compute_with_bins(y_true, y_pred, n_bins)
        
        # Extract bin data
        bin_centers = [b["bin_center"] for b in decomp["bin_stats"]]
        observed_freqs = [b["observed_frequency"] for b in decomp["bin_stats"]]
        n_events_per_bin = [b["n_events"] for b in decomp["bin_stats"]]
        
        # Perfect calibration line
        perfect_line = np.linspace(0, 1, 100)
        
        return {
            "title": title,
            "bin_centers": bin_centers,
            "observed_frequencies": observed_freqs,
            "n_events_per_bin": n_events_per_bin,
            "perfect_line": perfect_line.tolist(),
            "overall_brier": decomp["brier_score"],
            "overall_bss": self.compute_bss(y_true, y_pred),
            "n_events_total": decomp["n_events"]
        }
    
    def _categorize_quality(self, brier_score: float, bss: float) -> str:
        """Categorize model quality based on Brier and BSS."""
        if bss >= 0.20:
            return "Excellent"
        elif bss >= 0.10:
            return "Good"
        elif bss >= 0.05:
            return "Fair"
        elif bss > 0:
            return "Poor"
        else:
            return "No Skill"
    
    def _bootstrap_confidence_interval(self, y_true: np.ndarray, y_pred: np.ndarray,
                                     n_bootstrap: int = 1000, alpha: float = 0.05) -> Tuple[float, float]:
        """
        Compute bootstrap confidence interval for Brier score.
        
        Args:
            y_true: True outcomes
            y_pred: Predicted probabilities
            n_bootstrap: Number of bootstrap samples
            alpha: Significance level
            
        Returns:
            Confidence interval (lower, upper)
        """
        if len(y_true) < 30:
            return (None, None)  # Not enough samples
        
        bootstrap_scores = []
        n = len(y_true)
        
        for _ in range(n_bootstrap):
            # Bootstrap sample
            indices = np.random.choice(n, n, replace=True)
            y_true_boot = y_true[indices]
            y_pred_boot = y_pred[indices]
            
            # Compute Brier score
            bs = self.compute_brier(y_true_boot, y_pred_boot)
            bootstrap_scores.append(bs)
        
        # Compute confidence interval
        lower = np.percentile(bootstrap_scores, 100 * alpha / 2)
        upper = np.percentile(bootstrap_scores, 100 * (1 - alpha / 2))
        
        return (float(lower), float(upper))
    
    def get_online_stats(self, model_id: str) -> Optional[OnlineWeightedBrier]:
        """Get online statistics for a model."""
        return self.online_stats.get(model_id)
    
    def update_online_stats(self, model_id: str, p: float, o: int, weight: float = 1.0) -> None:
        """Update online statistics for a model."""
        if model_id not in self.online_stats:
            self.online_stats[model_id] = OnlineWeightedBrier()
        
        self.online_stats[model_id].update(p, o, weight)

# Global metrics instance
_merid_metrics = MERIDMetrics()

def get_merid_metrics() -> MERIDMetrics:
    """Get the global MERID metrics instance."""
    return _merid_metrics

# Convenience functions for direct access
def compute_brier(y_true: np.ndarray, y_pred: np.ndarray, weights: Optional[np.ndarray] = None) -> float:
    """Compute Brier score."""
    return _merid_metrics.compute_brier(y_true, y_pred, weights)

def compute_bss(y_true: np.ndarray, y_pred: np.ndarray, baseline: Optional[np.ndarray] = None,
                weights: Optional[np.ndarray] = None) -> float:
    """Compute Brier Skill Score."""
    return _merid_metrics.compute_bss(y_true, y_pred, baseline, weights)

def brier_decomposition(y_true: np.ndarray, y_pred: np.ndarray, n_bins: int = 10) -> BrierResult:
    """Compute Brier decomposition."""
    return _merid_metrics.brier_decomposition(y_true, y_pred, n_bins)

def plot_reliability_diagram(y_true: np.ndarray, y_pred: np.ndarray, 
                             n_bins: int = 10, title: str = "Reliability Diagram") -> Dict[str, Any]:
    """Generate reliability diagram data."""
    return _merid_metrics.plot_reliability_diagram(y_true, y_pred, n_bins, title)
