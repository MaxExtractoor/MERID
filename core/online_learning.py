"""
Online Learning and Adaptive Policies for MERID
Multi-armed bandits, reinforcement learning, and shadow deployments.
"""
from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

import numpy as np

from utils.logger import get_logger

logger = get_logger("core.online_learning")


class BanditAlgorithm(Enum):
    """Multi-armed bandit algorithms."""
    EPSILON_GREEDY = "epsilon_greedy"
    UCB = "ucb"
    THOMPSON_SAMPLING = "thompson_sampling"


@dataclass
class ArmStats:
    """Statistics for a bandit arm."""
    arm_id: str
    pulls: int
    total_reward: float
    mean_reward: float
    variance: float
    last_pull_time: float


class MultiArmedBandit:
    """Multi-armed bandit for strategy selection."""
    
    def __init__(
        self,
        arms: List[str],
        algorithm: BanditAlgorithm = BanditAlgorithm.UCB,
        epsilon: float = 0.1,
        ucb_c: float = 2.0
    ):
        self.arms = arms
        self.algorithm = algorithm
        self.epsilon = epsilon
        self.ucb_c = ucb_c
        
        self._stats: Dict[str, ArmStats] = {
            arm: ArmStats(
                arm_id=arm,
                pulls=0,
                total_reward=0.0,
                mean_reward=0.0,
                variance=0.0,
                last_pull_time=0.0
            )
            for arm in arms
        }
        
        self._total_pulls = 0
    
    def select_arm(self) -> str:
        """Select an arm to pull."""
        if self.algorithm == BanditAlgorithm.EPSILON_GREEDY:
            return self._epsilon_greedy()
        elif self.algorithm == BanditAlgorithm.UCB:
            return self._ucb()
        elif self.algorithm == BanditAlgorithm.THOMPSON_SAMPLING:
            return self._thompson_sampling()
        else:
            return random.choice(self.arms)
    
    def update(self, arm_id: str, reward: float) -> None:
        """Update statistics after observing reward."""
        if arm_id not in self._stats:
            logger.error(f"Unknown arm: {arm_id}")
            return
        
        stats = self._stats[arm_id]
        
        stats.pulls += 1
        stats.total_reward += reward
        
        old_mean = stats.mean_reward
        stats.mean_reward = stats.total_reward / stats.pulls
        
        if stats.pulls > 1:
            stats.variance = (
                (stats.pulls - 2) * stats.variance + (reward - old_mean) * (reward - stats.mean_reward)
            ) / (stats.pulls - 1)
        
        stats.last_pull_time = time.time()
        
        self._total_pulls += 1
        
        logger.debug(
            f"Updated arm {arm_id}: pulls={stats.pulls}, mean_reward={stats.mean_reward:.4f}"
        )
    
    def _epsilon_greedy(self) -> str:
        """Epsilon-greedy selection."""
        if random.random() < self.epsilon:
            return random.choice(self.arms)
        else:
            return max(self._stats.values(), key=lambda s: s.mean_reward).arm_id
    
    def _ucb(self) -> str:
        """Upper Confidence Bound selection."""
        if self._total_pulls < len(self.arms):
            unplayed = [arm for arm in self.arms if self._stats[arm].pulls == 0]
            if unplayed:
                return random.choice(unplayed)
        
        ucb_values = {}
        for arm_id, stats in self._stats.items():
            if stats.pulls == 0:
                ucb_values[arm_id] = float('inf')
            else:
                exploration_bonus = self.ucb_c * np.sqrt(np.log(self._total_pulls) / stats.pulls)
                ucb_values[arm_id] = stats.mean_reward + exploration_bonus
        
        return max(ucb_values.items(), key=lambda x: x[1])[0]
    
    def _thompson_sampling(self) -> str:
        """Thompson sampling selection."""
        samples = {}
        for arm_id, stats in self._stats.items():
            if stats.pulls == 0:
                samples[arm_id] = random.random()
            else:
                alpha = stats.total_reward + 1
                beta = stats.pulls - stats.total_reward + 1
                samples[arm_id] = np.random.beta(alpha, beta)
        
        return max(samples.items(), key=lambda x: x[1])[0]
    
    def get_stats(self) -> Dict[str, Any]:
        """Get bandit statistics."""
        return {
            "total_pulls": self._total_pulls,
            "arms": {
                arm_id: {
                    "pulls": stats.pulls,
                    "mean_reward": stats.mean_reward,
                    "variance": stats.variance,
                    "pull_rate": stats.pulls / self._total_pulls if self._total_pulls > 0 else 0
                }
                for arm_id, stats in self._stats.items()
            },
            "best_arm": max(self._stats.values(), key=lambda s: s.mean_reward).arm_id
        }


class ShadowDeployment:
    """Shadow deployment for safe model testing."""
    
    def __init__(
        self,
        production_model_id: str,
        shadow_model_id: str,
        sample_rate: float = 0.1
    ):
        self.production_model_id = production_model_id
        self.shadow_model_id = shadow_model_id
        self.sample_rate = sample_rate
        
        self._production_predictions: List[float] = []
        self._shadow_predictions: List[float] = []
        self._actuals: List[float] = []
        self._timestamps: List[float] = []
    
    def should_shadow(self) -> bool:
        """Determine if this request should be shadowed."""
        return random.random() < self.sample_rate
    
    def record_prediction(
        self,
        production_pred: float,
        shadow_pred: float,
        actual: Optional[float] = None
    ) -> None:
        """Record predictions from both models."""
        self._production_predictions.append(production_pred)
        self._shadow_predictions.append(shadow_pred)
        
        if actual is not None:
            self._actuals.append(actual)
        
        self._timestamps.append(time.time())
    
    def get_comparison(self) -> Dict[str, Any]:
        """Compare production and shadow model performance."""
        if not self._actuals:
            return {
                "status": "no_actuals",
                "samples": len(self._production_predictions)
            }
        
        prod_errors = [
            abs(pred - actual)
            for pred, actual in zip(self._production_predictions, self._actuals)
        ]
        
        shadow_errors = [
            abs(pred - actual)
            for pred, actual in zip(self._shadow_predictions, self._actuals)
        ]
        
        return {
            "samples": len(self._actuals),
            "production": {
                "mae": np.mean(prod_errors),
                "rmse": np.sqrt(np.mean([e**2 for e in prod_errors])),
                "max_error": max(prod_errors)
            },
            "shadow": {
                "mae": np.mean(shadow_errors),
                "rmse": np.sqrt(np.mean([e**2 for e in shadow_errors])),
                "max_error": max(shadow_errors)
            },
            "improvement": {
                "mae": (np.mean(prod_errors) - np.mean(shadow_errors)) / np.mean(prod_errors) * 100,
                "rmse": (np.sqrt(np.mean([e**2 for e in prod_errors])) - 
                        np.sqrt(np.mean([e**2 for e in shadow_errors]))) / 
                        np.sqrt(np.mean([e**2 for e in prod_errors])) * 100
            }
        }
    
    def should_promote_shadow(self, threshold_improvement: float = 5.0) -> bool:
        """Determine if shadow model should be promoted."""
        comparison = self.get_comparison()
        
        if comparison.get("status") == "no_actuals":
            return False
        
        mae_improvement = comparison["improvement"]["mae"]
        
        return mae_improvement > threshold_improvement


class AdaptivePolicy:
    """Adaptive policy with safety guards."""
    
    def __init__(
        self,
        policy_id: str,
        initial_params: Dict[str, float],
        param_bounds: Dict[str, tuple[float, float]],
        learning_rate: float = 0.01
    ):
        self.policy_id = policy_id
        self.params = initial_params.copy()
        self.param_bounds = param_bounds
        self.learning_rate = learning_rate
        
        self._param_history: List[Dict[str, float]] = [initial_params.copy()]
        self._performance_history: List[float] = []
    
    def update_params(self, gradient: Dict[str, float], performance: float) -> None:
        """Update policy parameters based on gradient."""
        for param_name, grad in gradient.items():
            if param_name not in self.params:
                continue
            
            new_value = self.params[param_name] + self.learning_rate * grad
            
            if param_name in self.param_bounds:
                min_val, max_val = self.param_bounds[param_name]
                new_value = max(min_val, min(max_val, new_value))
            
            self.params[param_name] = new_value
        
        self._param_history.append(self.params.copy())
        self._performance_history.append(performance)
        
        logger.info(f"Updated policy {self.policy_id}: {self.params}")
    
    def rollback(self, steps: int = 1) -> None:
        """Rollback policy parameters."""
        if len(self._param_history) <= steps:
            logger.warning(f"Cannot rollback {steps} steps, only {len(self._param_history)} available")
            return
        
        self.params = self._param_history[-(steps + 1)].copy()
        self._param_history = self._param_history[:-(steps)]
        self._performance_history = self._performance_history[:-(steps)]
        
        logger.info(f"Rolled back policy {self.policy_id} by {steps} steps")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get policy statistics."""
        return {
            "policy_id": self.policy_id,
            "current_params": self.params,
            "updates": len(self._param_history) - 1,
            "average_performance": np.mean(self._performance_history) if self._performance_history else 0,
            "recent_performance": self._performance_history[-10:] if self._performance_history else []
        }


class OnlineLearningOrchestrator:
    """Orchestrates online learning components."""
    
    def __init__(self):
        self._bandits: Dict[str, MultiArmedBandit] = {}
        self._shadow_deployments: Dict[str, ShadowDeployment] = {}
        self._adaptive_policies: Dict[str, AdaptivePolicy] = {}
    
    def create_bandit(
        self,
        name: str,
        arms: List[str],
        algorithm: BanditAlgorithm = BanditAlgorithm.UCB
    ) -> MultiArmedBandit:
        """Create a multi-armed bandit."""
        bandit = MultiArmedBandit(arms, algorithm)
        self._bandits[name] = bandit
        logger.info(f"Created bandit {name} with {len(arms)} arms")
        return bandit
    
    def get_bandit(self, name: str) -> Optional[MultiArmedBandit]:
        """Get a bandit by name."""
        return self._bandits.get(name)
    
    def create_shadow_deployment(
        self,
        production_model_id: str,
        shadow_model_id: str,
        sample_rate: float = 0.1
    ) -> ShadowDeployment:
        """Create a shadow deployment."""
        deployment = ShadowDeployment(production_model_id, shadow_model_id, sample_rate)
        self._shadow_deployments[shadow_model_id] = deployment
        logger.info(f"Created shadow deployment: {shadow_model_id} (sample rate: {sample_rate})")
        return deployment
    
    def get_shadow_deployment(self, shadow_model_id: str) -> Optional[ShadowDeployment]:
        """Get a shadow deployment."""
        return self._shadow_deployments.get(shadow_model_id)
    
    def create_adaptive_policy(
        self,
        policy_id: str,
        initial_params: Dict[str, float],
        param_bounds: Dict[str, tuple[float, float]]
    ) -> AdaptivePolicy:
        """Create an adaptive policy."""
        policy = AdaptivePolicy(policy_id, initial_params, param_bounds)
        self._adaptive_policies[policy_id] = policy
        logger.info(f"Created adaptive policy: {policy_id}")
        return policy
    
    def get_adaptive_policy(self, policy_id: str) -> Optional[AdaptivePolicy]:
        """Get an adaptive policy."""
        return self._adaptive_policies.get(policy_id)
    
    def get_all_stats(self) -> Dict[str, Any]:
        """Get statistics for all components."""
        return {
            "bandits": {
                name: bandit.get_stats()
                for name, bandit in self._bandits.items()
            },
            "shadow_deployments": {
                name: deployment.get_comparison()
                for name, deployment in self._shadow_deployments.items()
            },
            "adaptive_policies": {
                name: policy.get_stats()
                for name, policy in self._adaptive_policies.items()
            }
        }


# Global orchestrator
_online_learning_orchestrator: Optional[OnlineLearningOrchestrator] = None
_online_learning_orchestrator_lock = threading.Lock()


def get_online_learning_orchestrator() -> OnlineLearningOrchestrator:
    """Get the global online learning orchestrator."""
    global _online_learning_orchestrator
    if _online_learning_orchestrator is None:
        with _online_learning_orchestrator_lock:
            if _online_learning_orchestrator is None:
                _online_learning_orchestrator = OnlineLearningOrchestrator()
    return _online_learning_orchestrator
