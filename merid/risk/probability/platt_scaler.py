"""
Platt Scaler for probability calibration.

Implements Platt scaling (logistic regression) to calibrate model probabilities.
This is particularly useful for binary classification tasks where the model's
raw probabilities may be poorly calibrated.

Reference: Platt, J. (1999). "Probabilistic Outputs for Support Vector Machines
and Comparisons to Regularized Likelihood Methods."
"""

import logging
import math
from typing import List, Tuple, Optional
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class CalibrationMetrics:
    """Metrics for evaluating calibration quality."""
    brier_score: float  # Mean squared error of probabilities
    expected_calibration_error: float  # ECE: weighted average of calibration error
    maximum_calibration_error: float  # MCE: maximum calibration error across bins
    num_samples: int  # Number of samples used for calibration


class PlattScaler:
    """
    Platt Scaler for probability calibration using logistic regression.
    
    Fits a logistic regression model to map raw model scores (logits) to
    well-calibrated probabilities. This is particularly useful when the
    model's raw probability estimates are overconfident or underconfident.
    
    Usage:
        scaler = PlattScaler()
        scaler.fit(logits, outcomes)
        calibrated_probs = scaler.predict(logits)
        metrics = scaler.evaluate_metrics(logits, outcomes)
    """
    
    def __init__(self, regularization: float = 1e-4):
        """
        Initialize Platt Scaler.
        
        Args:
            regularization: L2 regularization parameter to prevent overfitting.
                           Default is 1e-4 as recommended in Platt's paper.
        """
        self.regularization = regularization
        self._a: Optional[float] = None  # Slope parameter
        self._b: Optional[float] = None  # Intercept parameter
        self._is_fitted: bool = False
        self._num_fit_samples: int = 0
    
    def fit(self, logits: List[float], outcomes: List[int]) -> None:
        """
        Fit Platt scaling parameters using logistic regression.
        
        Args:
            logits: Raw model logits (can be probabilities transformed to logit space)
            outcomes: Binary outcomes (0 or 1)
            
        Raises:
            ValueError: If logits and outcomes have different lengths
            ValueError: If insufficient data for fitting
        """
        if len(logits) != len(outcomes):
            raise ValueError(f"Logits and outcomes must have same length: {len(logits)} vs {len(outcomes)}")
        
        if len(logits) < 10:
            raise ValueError(f"Insufficient data for fitting: need at least 10 samples, got {len(logits)}")
        
        # Convert to numpy arrays
        logits_arr = np.array(logits, dtype=np.float64)
        outcomes_arr = np.array(outcomes, dtype=np.float64)
        
        # Use gradient descent to fit logistic regression
        # Objective: minimize cross-entropy loss with L2 regularization
        self._a, self._b = self._fit_logistic_regression(logits_arr, outcomes_arr)
        
        self._is_fitted = True
        self._num_fit_samples = len(logits)
        
        logger.info(f"[PLATT-SCALER] Fitted with {len(logits)} samples: a={self._a:.4f}, b={self._b:.4f}")
    
    def _fit_logistic_regression(self, logits: np.ndarray, outcomes: np.ndarray) -> Tuple[float, float]:
        """
        Fit logistic regression using gradient descent.
        
        Args:
            logits: Array of logits
            outcomes: Array of binary outcomes
            
        Returns:
            Tuple of (a, b) parameters for logistic function: 1 / (1 + exp(-(a*x + b)))
        """
        # Initialize parameters
        a = 1.0  # Start with identity mapping
        b = 0.0
        
        # Gradient descent parameters
        learning_rate = 0.01
        max_iterations = 1000
        tolerance = 1e-6
        
        prev_loss = float('inf')
        
        for iteration in range(max_iterations):
            # Compute predictions
            z = a * logits + b
            p = 1.0 / (1.0 + np.exp(-z))
            
            # Clip predictions to avoid numerical issues
            p = np.clip(p, 1e-10, 1 - 1e-10)
            
            # Compute cross-entropy loss with L2 regularization
            loss = -np.mean(outcomes * np.log(p) + (1 - outcomes) * np.log(1 - p))
            loss += 0.5 * self.regularization * (a**2 + b**2)
            
            # Check convergence
            if abs(prev_loss - loss) < tolerance:
                break
            
            prev_loss = loss
            
            # Compute gradients
            # Gradient for a: mean((p - y) * x) + regularization * a
            grad_a = np.mean((p - outcomes) * logits) + self.regularization * a
            # Gradient for b: mean(p - y) + regularization * b
            grad_b = np.mean(p - outcomes) + self.regularization * b
            
            # Update parameters
            a -= learning_rate * grad_a
            b -= learning_rate * grad_b
        
        return a, b
    
    def predict(self, logits: List[float]) -> List[float]:
        """
        Calibrate probabilities using fitted Platt scaling parameters.
        
        Args:
            logits: Raw model logits to calibrate
            
        Returns:
            Calibrated probabilities
            
        Raises:
            RuntimeError: If scaler has not been fitted
        """
        if not self._is_fitted:
            raise RuntimeError("PlattScaler must be fitted before calling predict()")
        
        logits_arr = np.array(logits, dtype=np.float64)
        z = self._a * logits_arr + self._b
        calibrated = 1.0 / (1.0 + np.exp(-z))
        
        # Clip to valid probability range
        calibrated = np.clip(calibrated, 0.01, 0.99)
        
        return calibrated.tolist()
    
    def predict_single(self, logit: float) -> float:
        """
        Calibrate a single logit.
        
        Args:
            logit: Raw model logit to calibrate
            
        Returns:
            Calibrated probability
            
        Raises:
            RuntimeError: If scaler has not been fitted
        """
        if not self._is_fitted:
            raise RuntimeError("PlattScaler must be fitted before calling predict_single()")
        
        z = self._a * logit + self._b
        calibrated = 1.0 / (1.0 + math.exp(-z))
        
        # Clip to valid probability range
        calibrated = max(0.01, min(0.99, calibrated))
        
        return calibrated
    
    def evaluate_metrics(self, logits: List[float], outcomes: List[int], 
                        num_bins: int = 10) -> CalibrationMetrics:
        """
        Evaluate calibration metrics.
        
        Args:
            logits: Raw model logits
            outcomes: Binary outcomes (0 or 1)
            num_bins: Number of bins for Expected Calibration Error calculation
            
        Returns:
            CalibrationMetrics object with Brier score, ECE, and MCE
        """
        if not self._is_fitted:
            raise RuntimeError("PlattScaler must be fitted before calling evaluate_metrics()")
        
        # Get calibrated probabilities
        calibrated_probs = self.predict(logits)
        
        # Calculate Brier score (mean squared error)
        brier_score = np.mean((np.array(calibrated_probs) - np.array(outcomes)) ** 2)
        
        # Calculate Expected Calibration Error (ECE)
        ece = self._calculate_ece(calibrated_probs, outcomes, num_bins)
        
        # Calculate Maximum Calibration Error (MCE)
        mce = self._calculate_mce(calibrated_probs, outcomes, num_bins)
        
        return CalibrationMetrics(
            brier_score=brier_score,
            expected_calibration_error=ece,
            maximum_calibration_error=mce,
            num_samples=len(logits)
        )
    
    def _calculate_ece(self, probs: List[float], outcomes: List[int], num_bins: int) -> float:
        """
        Calculate Expected Calibration Error.
        
        ECE is the weighted average of calibration error across bins,
        weighted by the number of samples in each bin.
        """
        probs_arr = np.array(probs)
        outcomes_arr = np.array(outcomes)
        
        ece = 0.0
        bin_edges = np.linspace(0, 1, num_bins + 1)
        
        for i in range(num_bins):
            # Get samples in this bin
            mask = (probs_arr >= bin_edges[i]) & (probs_arr < bin_edges[i + 1])
            if i == num_bins - 1:
                # Include upper bound for last bin
                mask = (probs_arr >= bin_edges[i]) & (probs_arr <= bin_edges[i + 1])
            
            if np.sum(mask) == 0:
                continue
            
            bin_probs = probs_arr[mask]
            bin_outcomes = outcomes_arr[mask]
            
            # Calculate average predicted probability and actual outcome
            avg_pred = np.mean(bin_probs)
            avg_actual = np.mean(bin_outcomes)
            
            # Calibration error for this bin
            bin_error = abs(avg_pred - avg_actual)
            
            # Weight by bin size
            weight = len(bin_probs) / len(probs_arr)
            ece += weight * bin_error
        
        return ece
    
    def _calculate_mce(self, probs: List[float], outcomes: List[int], num_bins: int) -> float:
        """
        Calculate Maximum Calibration Error.
        
        MCE is the maximum calibration error across all bins.
        """
        probs_arr = np.array(probs)
        outcomes_arr = np.array(outcomes)
        
        max_error = 0.0
        bin_edges = np.linspace(0, 1, num_bins + 1)
        
        for i in range(num_bins):
            # Get samples in this bin
            mask = (probs_arr >= bin_edges[i]) & (probs_arr < bin_edges[i + 1])
            if i == num_bins - 1:
                # Include upper bound for last bin
                mask = (probs_arr >= bin_edges[i]) & (probs_arr <= bin_edges[i + 1])
            
            if np.sum(mask) == 0:
                continue
            
            bin_probs = probs_arr[mask]
            bin_outcomes = outcomes_arr[mask]
            
            # Calculate average predicted probability and actual outcome
            avg_pred = np.mean(bin_probs)
            avg_actual = np.mean(bin_outcomes)
            
            # Calibration error for this bin
            bin_error = abs(avg_pred - avg_actual)
            
            max_error = max(max_error, bin_error)
        
        return max_error
    
    def is_fitted(self) -> bool:
        """Check if the scaler has been fitted."""
        return self._is_fitted
    
    def get_parameters(self) -> Optional[Tuple[float, float]]:
        """
        Get fitted Platt scaling parameters.
        
        Returns:
            Tuple of (a, b) parameters, or None if not fitted
        """
        if not self._is_fitted:
            return None
        return (self._a, self._b)
    
    def reset(self) -> None:
        """Reset the scaler to unfitted state."""
        self._a = None
        self._b = None
        self._is_fitted = False
        self._num_fit_samples = 0
        logger.info("[PLATT-SCALER] Reset to unfitted state")
