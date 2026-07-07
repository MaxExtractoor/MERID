"""
HMM-based Market Regime Detection Module

Implements Hidden Markov Model (HMM) for detecting market regimes:
- bull/trend: positive drift, low volatility
- choppy/range: near-zero drift, elevated volatility  
- crisis/bear: negative drift, high volatility

Based on 2026 best practices from Tradewink and RegimeSense.
Uses walk-forward training for production safety.
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
import logging
from enum import Enum

logger = logging.getLogger(__name__)

try:
    from hmmlearn import hmm
    HMM_AVAILABLE = True
except ImportError:
    HMM_AVAILABLE = False
    logger.warning("hmmlearn not available - regime detection disabled")


class Regime(Enum):
    """Market regime classifications"""
    BULL = "bull"  # Trending up, low volatility
    CHOPPY = "choppy"  # Range-bound, elevated volatility
    BEAR = "bear"  # Trending down, high volatility


@dataclass
class RegimeDetection:
    """Result of regime detection"""
    regime: Regime
    probabilities: Dict[Regime, float]  # Posterior probabilities
    confidence: float  # Highest probability
    features: np.ndarray  # Input features for debugging
    timestamp: int  # Unix timestamp in milliseconds


class RegimeDetector:
    """
    HMM-based regime detector for adaptive strategy switching.
    
    Uses 3-state Gaussian HMM with walk-forward training.
    Features: log returns, realized volatility, price momentum.
    """
    
    def __init__(
        self,
        n_states: int = 3,
        train_window: int = 300,  # Number of data points for training
        min_history: int = 50,  # Minimum history before making predictions
        refit_interval: int = 100,  # Refit every N points
        random_state: int = 42
    ):
        self.n_states = n_states
        self.train_window = train_window
        self.min_history = min_history
        self.refit_interval = refit_interval
        self.random_state = random_state
        
        self.model: Optional[hmm.GaussianHMM] = None
        self.state_labels: Dict[int, Regime] = {}  # Map HMM state index to Regime
        self.last_refit_idx: int = 0
        self.feature_history: List[Tuple[int, np.ndarray]] = []  # (timestamp, features)
        
        if not HMM_AVAILABLE:
            logger.error("hmmlearn not installed - regime detection will not work")
    
    def _compute_features(self, price_history: List[Tuple[int, float]]) -> np.ndarray:
        """
        Compute features for HMM from price history.
        
        Features:
        1. Log return (1-period)
        2. Realized volatility (rolling std of returns)
        3. Momentum (3-period return)
        
        Args:
            price_history: List of (timestamp, price) tuples, sorted by timestamp
            
        Returns:
            Feature vector [log_return, volatility, momentum]
        """
        if len(price_history) < 10:
            # Not enough history, return zeros
            return np.zeros(3)
        
        # Extract prices
        prices = np.array([p for _, p in price_history])
        
        # Log returns
        log_returns = np.diff(np.log(prices))
        
        # Current log return
        log_return = log_returns[-1] if len(log_returns) > 0 else 0.0
        
        # Realized volatility (rolling std of last 10 returns)
        vol_window = min(10, len(log_returns))
        volatility = np.std(log_returns[-vol_window:]) if vol_window > 1 else 0.0
        
        # Momentum (3-period return)
        momentum_window = min(3, len(prices))
        momentum = (prices[-1] - prices[-momentum_window]) / prices[-momentum_window] if momentum_window > 1 else 0.0
        
        return np.array([log_return, volatility, momentum])
    
    def _train_model(self, features: np.ndarray) -> Optional[hmm.GaussianHMM]:
        """
        Train HMM on feature data.
        
        Args:
            features: Feature matrix (n_samples, n_features)
            
        Returns:
            Trained GaussianHMM model, or None if training fails
        """
        if not HMM_AVAILABLE:
            raise RuntimeError("hmmlearn not available")
        
        # CRITICAL FIX: Validate features before training
        # NaN or inf values in features can cause HMM to produce invalid parameters
        if np.any(np.isnan(features)) or np.any(np.isinf(features)):
            logger.warning(
                f"[REGIME-DETECTOR] Features contain NaN or inf values, skipping HMM training"
            )
            return None
        
        # Use 'diag' covariance for better numerical stability
        # 'full' covariance can become singular with limited data
        model = hmm.GaussianHMM(
            n_components=self.n_states,
            covariance_type="diag",
            n_iter=1000,
            random_state=self.random_state,
            tol=1e-4
        )
        
        try:
            model.fit(features)
            
            # CRITICAL FIX: Validate model parameters after training
            # Check if startprob_ sums to 1 (or close to 1) and doesn't contain NaN
            if np.any(np.isnan(model.startprob_)) or np.any(np.isnan(model.transmat_)):
                logger.warning(
                    f"[REGIME-DETECTOR] HMM training produced NaN parameters, skipping model"
                )
                return None
            
            startprob_sum = np.sum(model.startprob_)
            if not (0.99 <= startprob_sum <= 1.01):
                logger.warning(
                    f"[REGIME-DETECTOR] HMM startprob_ doesn't sum to 1 (got {startprob_sum}), skipping model"
                )
                return None
            
            return model
            
        except Exception as e:
            logger.warning(
                f"[REGIME-DETECTOR] HMM training failed with error: {e}, skipping model"
            )
            return None
    
    def _label_states(self, model: hmm.GaussianHMM) -> Dict[int, Regime]:
        """
        Label HMM states as bull/choppy/bear based on mean returns.
        
        Args:
            model: Trained HMM model
            
        Returns:
            Mapping from state index to Regime enum
        """
        # Sort states by mean return (first feature)
        state_means = model.means_[:, 0]  # Mean log return for each state
        sorted_indices = np.argsort(state_means)
        
        # Map: lowest return -> bear, middle -> choppy, highest -> bull
        labels = {
            sorted_indices[0]: Regime.BEAR,
            sorted_indices[1]: Regime.CHOPPY,
            sorted_indices[2]: Regime.BULL
        }
        
        logger.info(f"[REGIME-DETECTOR] State labels: {labels}")
        return labels
    
    def update(self, timestamp: int, price: float) -> Optional[RegimeDetection]:
        """
        Update detector with new price data and detect current regime.
        
        Args:
            timestamp: Unix timestamp in milliseconds
            price: Current price
            
        Returns:
            RegimeDetection if sufficient history, None otherwise
        """
        if not HMM_AVAILABLE:
            return None
        
        # Add to history
        self.feature_history.append((timestamp, price))
        
        # Keep only last train_window points
        if len(self.feature_history) > self.train_window:
            self.feature_history = self.feature_history[-self.train_window:]
        
        # Check minimum history
        if len(self.feature_history) < self.min_history:
            logger.debug(f"[REGIME-DETECTOR] Insufficient history: {len(self.feature_history)} < {self.min_history}")
            return None
        
        # Compute features for all history
        features = np.array([self._compute_features(self.feature_history[:i+1]) 
                            for i in range(len(self.feature_history))])
        
        # Check if we need to refit
        current_idx = len(self.feature_history)
        should_refit = (self.model is None or 
                       current_idx - self.last_refit_idx >= self.refit_interval)
        
        if should_refit:
            logger.info(f"[REGIME-DETECTOR] Refitting HMM with {len(features)} samples")
            self.model = self._train_model(features)
            
            # CRITICAL FIX: Handle case where training failed (model is None)
            if self.model is None:
                logger.warning(
                    f"[REGIME-DETECTOR] HMM training failed, using default trend_following mode"
                )
                return None
            
            self.state_labels = self._label_states(self.model)
            self.last_refit_idx = current_idx
        
        # CRITICAL FIX: Check if model is still valid before prediction
        if self.model is None:
            logger.warning(
                f"[REGIME-DETECTOR] No valid HMM model available, using default trend_following mode"
            )
            return None
        
        # Predict current regime
        current_features = features[-1:].reshape(1, -1)
        state_idx = self.model.predict(current_features)[0]
        state_probs = self.model.predict_proba(current_features)[0]
        
        # Map to regime
        regime = self.state_labels.get(state_idx, Regime.CHOPPY)
        
        # Build probability dict
        probabilities = {}
        for idx, prob in enumerate(state_probs):
            regime_label = self.state_labels.get(idx, Regime.CHOPPY)
            probabilities[regime_label] = prob
        
        confidence = max(state_probs)
        
        detection = RegimeDetection(
            regime=regime,
            probabilities=probabilities,
            confidence=confidence,
            features=current_features[0],
            timestamp=timestamp
        )
        
        logger.info(
            f"[REGIME-DETECTOR] regime={regime.value} confidence={confidence:.2f} "
            f"probs={probabilities}"
        )
        
        return detection
    
    def get_strategy_mode(self, detection: RegimeDetection) -> str:
        """
        Get recommended strategy mode based on regime.
        
        CRITICAL FIX: Only use mean_reversion when confidence is high enough.
        Low confidence regime detection was causing signal inversion:
        - Insufficient training data led to incorrect CHOPPY classification
        - CHOPPY regime uses mean_reversion, which inverts velocity signals
        - This caused systematic losses (positive velocity -> buy NO instead of YES)
        
        Args:
            detection: RegimeDetection result
            
        Returns:
            Strategy mode: 'trend_following' or 'mean_reversion'
        """
        if detection is None:
            return 'trend_following'  # Default
        
        # CRITICAL FIX: Only use mean_reversion when confidence is high (>0.7)
        # Low confidence indicates insufficient training data or uncertain regime
        # In these cases, default to trend_following to avoid signal inversion
        if detection.confidence < 0.7:
            logger.debug(
                f"[REGIME-DETECTOR] Low confidence {detection.confidence:.2f} < 0.7, "
                f"defaulting to trend_following to avoid signal inversion"
            )
            return 'trend_following'
        
        # Trend-following in bull regimes
        if detection.regime == Regime.BULL:
            return 'trend_following'
        
        # Mean-reversion in choppy regimes (only with high confidence)
        elif detection.regime == Regime.CHOPPY:
            logger.warning(
                f"[REGIME-DETECTOR] High-confidence CHOPPY regime detected (confidence={detection.confidence:.2f}), "
                f"using mean_reversion mode - SIGNAL INVERSION RISK: positive velocity will trigger NO signals"
            )
            return 'mean_reversion'
        
        # Conservative in bear regimes (avoid or very selective)
        elif detection.regime == Regime.BEAR:
            return 'trend_following'  # Still follow trend, but could be more selective
        
        return 'trend_following'
