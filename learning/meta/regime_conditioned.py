"""
MERID Meta-Learning - Regime-Conditioned Policies

Policies that adapt their behavior based on detected market regime.
Integrates with MERID-OPS regime detection for regime awareness.

Key features:
- Regime embedding for policy conditioning
- Fast adaptation when regime changes
- Regime-specific parameter modulation
- Uncertainty-aware regime transitions
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

from utils.logger import get_logger

logger = get_logger("learning.meta.regime_conditioned")


class MarketRegime(Enum):
    """Market regimes (mirrors ops/regime_detection.py)."""
    TRENDING_BULL = "trending_bull"
    TRENDING_BEAR = "trending_bear"
    MEAN_REVERTING = "mean_reverting"
    HIGH_VOLATILITY = "high_volatility"
    CRISIS = "crisis"
    UNKNOWN = "unknown"


@dataclass
class RegimeConditionedConfig:
    """Configuration for regime-conditioned policies."""
    # Architecture
    state_dim: int = 64
    action_dim: int = 5
    hidden_dims: List[int] = field(default_factory=lambda: [128, 128])
    regime_embed_dim: int = 32
    
    # Learning
    lr: float = 3e-4
    adaptation_lr: float = 0.01
    adaptation_steps: int = 5
    
    # Regime handling
    regime_transition_smoothing: float = 0.1
    min_regime_confidence: float = 0.5
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "state_dim": self.state_dim,
            "action_dim": self.action_dim,
            "regime_embed_dim": self.regime_embed_dim,
            "lr": self.lr,
            "adaptation_lr": self.adaptation_lr,
        }


class RegimeEmbedding:
    """
    Learns embeddings for each market regime.
    
    These embeddings condition the policy network.
    """
    
    def __init__(self, n_regimes: int = 6, embed_dim: int = 32):
        self.n_regimes = n_regimes
        self.embed_dim = embed_dim
        
        # Initialize regime embeddings
        self.embeddings = np.random.randn(n_regimes, embed_dim) * 0.1
        
        # Regime to index mapping
        self.regime_to_idx = {
            MarketRegime.TRENDING_BULL: 0,
            MarketRegime.TRENDING_BEAR: 1,
            MarketRegime.MEAN_REVERTING: 2,
            MarketRegime.HIGH_VOLATILITY: 3,
            MarketRegime.CRISIS: 4,
            MarketRegime.UNKNOWN: 5,
        }
    
    def get_embedding(self, regime: MarketRegime) -> np.ndarray:
        """Get embedding for a regime."""
        idx = self.regime_to_idx.get(regime, 5)
        return self.embeddings[idx].copy()
    
    def get_soft_embedding(
        self,
        regime_probs: Dict[MarketRegime, float],
    ) -> np.ndarray:
        """Get soft embedding weighted by regime probabilities."""
        embedding = np.zeros(self.embed_dim)
        
        for regime, prob in regime_probs.items():
            idx = self.regime_to_idx.get(regime, 5)
            embedding += prob * self.embeddings[idx]
        
        return embedding
    
    def update_embedding(
        self,
        regime: MarketRegime,
        gradient: np.ndarray,
        lr: float = 0.01,
    ) -> None:
        """Update embedding for a regime."""
        idx = self.regime_to_idx.get(regime, 5)
        self.embeddings[idx] -= lr * gradient
    
    def get_all_embeddings(self) -> Dict[str, np.ndarray]:
        """Get all embeddings."""
        return {
            regime.value: self.embeddings[idx].copy()
            for regime, idx in self.regime_to_idx.items()
        }


class RegimeConditionedNetwork:
    """
    Neural network conditioned on regime embedding.
    
    Architecture: [state, regime_embedding] -> hidden -> action
    """
    
    def __init__(
        self,
        state_dim: int,
        action_dim: int,
        regime_embed_dim: int,
        hidden_dims: List[int] = None,
    ):
        self.state_dim = state_dim
        self.action_dim = action_dim
        self.regime_embed_dim = regime_embed_dim
        self.hidden_dims = hidden_dims or [128, 128]
        
        # Input includes state and regime embedding
        input_dim = state_dim + regime_embed_dim
        
        # Initialize parameters
        self.params = self._init_params(input_dim)
    
    def _init_params(self, input_dim: int) -> Dict[str, np.ndarray]:
        """Initialize network parameters."""
        params = {}
        dims = [input_dim] + self.hidden_dims + [self.action_dim]
        
        for i in range(len(dims) - 1):
            scale = np.sqrt(2.0 / (dims[i] + dims[i+1]))
            params[f"w{i}"] = np.random.randn(dims[i], dims[i+1]) * scale
            params[f"b{i}"] = np.zeros(dims[i+1])
        
        return params
    
    def forward(
        self,
        state: np.ndarray,
        regime_embedding: np.ndarray,
        params: Optional[Dict[str, np.ndarray]] = None,
    ) -> np.ndarray:
        """Forward pass."""
        if params is None:
            params = self.params
        
        # Concatenate state and regime embedding
        x = np.concatenate([state, regime_embedding])
        
        n_layers = len(self.hidden_dims) + 1
        
        for i in range(n_layers):
            x = x @ params[f"w{i}"] + params[f"b{i}"]
            if i < n_layers - 1:
                x = np.maximum(0, x)  # ReLU
        
        return x
    
    def get_action_probs(
        self,
        state: np.ndarray,
        regime_embedding: np.ndarray,
        params: Optional[Dict[str, np.ndarray]] = None,
    ) -> np.ndarray:
        """Get action probabilities (softmax)."""
        logits = self.forward(state, regime_embedding, params)
        exp_logits = np.exp(logits - np.max(logits))
        return exp_logits / exp_logits.sum()
    
    def get_params(self) -> Dict[str, np.ndarray]:
        """Get copy of parameters."""
        return {k: v.copy() for k, v in self.params.items()}
    
    def set_params(self, params: Dict[str, np.ndarray]) -> None:
        """Set parameters."""
        self.params = {k: v.copy() for k, v in params.items()}


class RegimeConditionedPolicy:
    """
    Policy that adapts based on market regime.
    
    Key features:
    - Regime embedding conditions policy
    - Per-regime parameter adaptation
    - Smooth transitions between regimes
    - Uncertainty-aware action selection
    """
    
    def __init__(self, config: Optional[RegimeConditionedConfig] = None):
        self.config = config or RegimeConditionedConfig()
        
        # Regime embedding
        self.regime_embedding = RegimeEmbedding(
            n_regimes=6, embed_dim=self.config.regime_embed_dim
        )
        
        # Policy network
        self.network = RegimeConditionedNetwork(
            self.config.state_dim,
            self.config.action_dim,
            self.config.regime_embed_dim,
            self.config.hidden_dims,
        )
        
        # Per-regime adapted parameters
        self._regime_params: Dict[MarketRegime, Dict[str, np.ndarray]] = {}
        
        # Current regime state
        self._current_regime: MarketRegime = MarketRegime.UNKNOWN
        self._regime_confidence: float = 0.0
        self._regime_probs: Dict[MarketRegime, float] = {}
        
        # Transition smoothing
        self._prev_embedding: Optional[np.ndarray] = None
        
        # Statistics
        self._action_count = 0
        self._regime_history: List[Tuple[float, MarketRegime]] = []
        
        logger.info("Regime-conditioned policy initialized")
    
    def set_regime(
        self,
        regime: MarketRegime,
        confidence: float,
        regime_probs: Optional[Dict[MarketRegime, float]] = None,
    ) -> None:
        """Update current regime."""
        old_regime = self._current_regime
        
        self._current_regime = regime
        self._regime_confidence = confidence
        self._regime_probs = regime_probs or {regime: 1.0}
        
        if old_regime != regime:
            self._regime_history.append((time.time(), regime))
            logger.info(
                "Regime changed: %s -> %s (confidence=%.2f)",
                old_regime.value, regime.value, confidence
            )
    
    def get_action(
        self,
        state: np.ndarray,
        deterministic: bool = False,
    ) -> Tuple[int, float, Dict[str, Any]]:
        """
        Get action conditioned on current regime.
        
        Returns (action, log_prob, info).
        """
        self._action_count += 1
        
        # Get regime embedding
        if self._regime_confidence >= self.config.min_regime_confidence:
            embedding = self.regime_embedding.get_embedding(self._current_regime)
        else:
            # Use soft embedding when uncertain
            embedding = self.regime_embedding.get_soft_embedding(self._regime_probs)
        
        # Smooth transition
        if self._prev_embedding is not None:
            alpha = self.config.regime_transition_smoothing
            embedding = alpha * embedding + (1 - alpha) * self._prev_embedding
        
        self._prev_embedding = embedding.copy()
        
        # Get adapted parameters for current regime
        params = self._get_regime_params(self._current_regime)
        
        # Get action probabilities
        probs = self.network.get_action_probs(state, embedding, params)
        
        if deterministic:
            action = int(np.argmax(probs))
        else:
            action = int(np.random.choice(self.config.action_dim, p=probs))
        
        log_prob = float(np.log(probs[action] + 1e-10))
        
        info = {
            "regime": self._current_regime.value,
            "regime_confidence": self._regime_confidence,
            "action_probs": probs.tolist(),
        }
        
        return action, log_prob, info
    
    def _get_regime_params(self, regime: MarketRegime) -> Dict[str, np.ndarray]:
        """Get parameters adapted for regime."""
        if regime in self._regime_params:
            return self._regime_params[regime]
        return self.network.get_params()
    
    def adapt_to_regime(
        self,
        regime: MarketRegime,
        states: np.ndarray,
        actions: np.ndarray,
        rewards: np.ndarray,
    ) -> Dict[str, float]:
        """
        Adapt policy parameters for a specific regime.
        
        Uses few gradient steps on regime-specific data.
        """
        # Start from base parameters
        adapted_params = self.network.get_params()
        embedding = self.regime_embedding.get_embedding(regime)
        
        for step in range(self.config.adaptation_steps):
            # Compute policy gradient
            gradients = self._compute_policy_gradient(
                states, actions, rewards, embedding, adapted_params
            )
            
            # Update parameters
            for key in adapted_params:
                adapted_params[key] -= self.config.adaptation_lr * gradients[key]
        
        # Store adapted parameters
        self._regime_params[regime] = adapted_params
        
        # Compute final loss
        final_loss = self._compute_loss(states, actions, rewards, embedding, adapted_params)
        
        logger.info("Adapted to regime %s: loss=%.4f", regime.value, final_loss)
        
        return {
            "regime": regime.value,
            "final_loss": final_loss,
            "n_samples": len(states),
        }
    
    def _compute_policy_gradient(
        self,
        states: np.ndarray,
        actions: np.ndarray,
        rewards: np.ndarray,
        embedding: np.ndarray,
        params: Dict[str, np.ndarray],
    ) -> Dict[str, np.ndarray]:
        """Compute policy gradient."""
        gradients = {k: np.zeros_like(v) for k, v in params.items()}
        epsilon = 1e-5
        
        for key in params:
            n_samples = min(10, params[key].size)
            indices = np.random.choice(params[key].size, n_samples, replace=False)
            
            for idx in indices:
                flat_idx = np.unravel_index(idx, params[key].shape)
                
                params_plus = {k: v.copy() for k, v in params.items()}
                params_plus[key][flat_idx] += epsilon
                loss_plus = self._compute_loss(states, actions, rewards, embedding, params_plus)
                
                params_minus = {k: v.copy() for k, v in params.items()}
                params_minus[key][flat_idx] -= epsilon
                loss_minus = self._compute_loss(states, actions, rewards, embedding, params_minus)
                
                gradients[key][flat_idx] = (loss_plus - loss_minus) / (2 * epsilon)
        
        return gradients
    
    def _compute_loss(
        self,
        states: np.ndarray,
        actions: np.ndarray,
        rewards: np.ndarray,
        embedding: np.ndarray,
        params: Dict[str, np.ndarray],
    ) -> float:
        """Compute policy gradient loss."""
        loss = 0.0
        
        # Normalize rewards
        rewards = (rewards - rewards.mean()) / (rewards.std() + 1e-8)
        
        for i in range(len(states)):
            probs = self.network.get_action_probs(states[i], embedding, params)
            log_prob = np.log(probs[int(actions[i])] + 1e-10)
            loss -= log_prob * rewards[i]
        
        return loss / len(states)
    
    def get_regime_performance(self) -> Dict[str, Any]:
        """Get performance breakdown by regime."""
        return {
            "current_regime": self._current_regime.value,
            "regime_confidence": self._regime_confidence,
            "adapted_regimes": list(self._regime_params.keys()),
            "regime_history_length": len(self._regime_history),
            "total_actions": self._action_count,
        }
    
    def get_stats(self) -> Dict[str, Any]:
        """Get policy statistics."""
        return {
            "current_regime": self._current_regime.value,
            "regime_confidence": round(self._regime_confidence, 4),
            "action_count": self._action_count,
            "adapted_regimes": [r.value for r in self._regime_params.keys()],
            "config": self.config.to_dict(),
        }


class RegimeAdapter:
    """
    Manages regime adaptation for multiple policies.
    
    Integrates with MERID-OPS regime detection.
    """
    
    def __init__(self):
        self._policies: Dict[str, RegimeConditionedPolicy] = {}
        self._current_regime: MarketRegime = MarketRegime.UNKNOWN
        self._regime_confidence: float = 0.0
        
        # Adaptation history
        self._adaptation_history: List[Dict[str, Any]] = []
        
        logger.info("Regime adapter initialized")
    
    def register_policy(
        self,
        policy_id: str,
        policy: RegimeConditionedPolicy,
    ) -> None:
        """Register a policy for regime adaptation."""
        self._policies[policy_id] = policy
        logger.info("Registered policy: %s", policy_id)
    
    def update_regime(
        self,
        regime: MarketRegime,
        confidence: float,
        regime_probs: Optional[Dict[MarketRegime, float]] = None,
    ) -> None:
        """Update regime for all registered policies."""
        self._current_regime = regime
        self._regime_confidence = confidence
        
        for policy in self._policies.values():
            policy.set_regime(regime, confidence, regime_probs)
    
    def adapt_all_policies(
        self,
        regime: MarketRegime,
        experience_data: Dict[str, Tuple[np.ndarray, np.ndarray, np.ndarray]],
    ) -> Dict[str, Dict[str, float]]:
        """
        Adapt all policies to a regime.
        
        experience_data: {policy_id: (states, actions, rewards)}
        """
        results = {}
        
        for policy_id, policy in self._policies.items():
            if policy_id in experience_data:
                states, actions, rewards = experience_data[policy_id]
                result = policy.adapt_to_regime(regime, states, actions, rewards)
                results[policy_id] = result
        
        self._adaptation_history.append({
            "timestamp": time.time(),
            "regime": regime.value,
            "results": results,
        })
        
        return results
    
    def get_status(self) -> Dict[str, Any]:
        """Get adapter status."""
        return {
            "current_regime": self._current_regime.value,
            "regime_confidence": round(self._regime_confidence, 4),
            "registered_policies": list(self._policies.keys()),
            "adaptation_count": len(self._adaptation_history),
        }


# Singleton instance
_regime_adapter: Optional[RegimeAdapter] = None


def get_regime_adapter() -> RegimeAdapter:
    """Get the singleton regime adapter."""
    global _regime_adapter
    if _regime_adapter is None:
        _regime_adapter = RegimeAdapter()
    return _regime_adapter
