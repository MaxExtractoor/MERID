"""
MERID Meta-Learning - Model-Agnostic Meta-Learning (MAML)

MAML learns an initialization that can quickly adapt to new tasks:
- Outer loop: optimize for fast adaptation across tasks
- Inner loop: few gradient steps on task-specific data
- Result: model that can adapt to new market regimes quickly

Reference: Finn et al., "Model-Agnostic Meta-Learning for Fast Adaptation of Deep Networks"
"""

from __future__ import annotations

import time
import copy
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Callable
import numpy as np

from utils.logger import get_logger

logger = get_logger("learning.meta.maml")


@dataclass
class MAMLConfig:
    """Configuration for MAML."""
    # Learning rates
    inner_lr: float = 0.01      # Task-specific adaptation rate
    outer_lr: float = 0.001    # Meta-learning rate
    
    # Adaptation
    n_inner_steps: int = 5     # Gradient steps for adaptation
    n_tasks_per_batch: int = 4  # Tasks per meta-update
    
    # Architecture
    hidden_dims: List[int] = field(default_factory=lambda: [64, 64])
    
    # Training
    n_meta_iterations: int = 1000
    eval_interval: int = 50
    
    # First-order approximation (faster but less accurate)
    first_order: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "inner_lr": self.inner_lr,
            "outer_lr": self.outer_lr,
            "n_inner_steps": self.n_inner_steps,
            "n_tasks_per_batch": self.n_tasks_per_batch,
            "first_order": self.first_order,
        }


@dataclass
class MAMLTask:
    """A task for meta-learning."""
    task_id: str
    
    # Task data
    support_x: np.ndarray  # Training data for adaptation
    support_y: np.ndarray
    query_x: np.ndarray    # Test data for meta-gradient
    query_y: np.ndarray
    
    # Task metadata
    regime: str = "unknown"
    description: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "regime": self.regime,
            "support_size": len(self.support_x),
            "query_size": len(self.query_x),
        }


class MAMLNetwork:
    """
    Neural network for MAML with explicit parameter handling.
    """
    
    def __init__(
        self,
        input_dim: int,
        output_dim: int,
        hidden_dims: List[int] = None,
    ):
        self.input_dim = input_dim
        self.output_dim = output_dim
        self.hidden_dims = hidden_dims or [64, 64]
        
        # Initialize parameters
        self.params = self._init_params()
    
    def _init_params(self) -> Dict[str, np.ndarray]:
        """Initialize network parameters."""
        params = {}
        dims = [self.input_dim] + self.hidden_dims + [self.output_dim]
        
        for i in range(len(dims) - 1):
            scale = np.sqrt(2.0 / (dims[i] + dims[i+1]))
            params[f"w{i}"] = np.random.randn(dims[i], dims[i+1]) * scale
            params[f"b{i}"] = np.zeros(dims[i+1])
        
        return params
    
    def forward(self, x: np.ndarray, params: Optional[Dict[str, np.ndarray]] = None) -> np.ndarray:
        """Forward pass with optional parameter override."""
        if params is None:
            params = self.params
        
        n_layers = len(self.hidden_dims) + 1
        
        for i in range(n_layers):
            x = x @ params[f"w{i}"] + params[f"b{i}"]
            if i < n_layers - 1:  # ReLU for hidden layers
                x = np.maximum(0, x)
        
        return x
    
    def compute_loss(
        self,
        x: np.ndarray,
        y: np.ndarray,
        params: Optional[Dict[str, np.ndarray]] = None,
    ) -> float:
        """Compute MSE loss."""
        predictions = self.forward(x, params)
        return float(np.mean((predictions - y) ** 2))
    
    def compute_gradients(
        self,
        x: np.ndarray,
        y: np.ndarray,
        params: Optional[Dict[str, np.ndarray]] = None,
    ) -> Dict[str, np.ndarray]:
        """Compute gradients using numerical differentiation."""
        if params is None:
            params = self.params
        
        gradients = {}
        epsilon = 1e-5
        
        for key in params:
            grad = np.zeros_like(params[key])
            
            # Sample gradient directions for efficiency
            n_samples = min(20, params[key].size)
            indices = np.random.choice(params[key].size, n_samples, replace=False)
            
            for idx in indices:
                flat_idx = np.unravel_index(idx, params[key].shape)
                
                # Positive perturbation
                params_plus = {k: v.copy() for k, v in params.items()}
                params_plus[key][flat_idx] += epsilon
                loss_plus = self.compute_loss(x, y, params_plus)
                
                # Negative perturbation
                params_minus = {k: v.copy() for k, v in params.items()}
                params_minus[key][flat_idx] -= epsilon
                loss_minus = self.compute_loss(x, y, params_minus)
                
                grad[flat_idx] = (loss_plus - loss_minus) / (2 * epsilon)
            
            gradients[key] = grad
        
        return gradients
    
    def get_params(self) -> Dict[str, np.ndarray]:
        """Get copy of parameters."""
        return {k: v.copy() for k, v in self.params.items()}
    
    def set_params(self, params: Dict[str, np.ndarray]) -> None:
        """Set parameters."""
        self.params = {k: v.copy() for k, v in params.items()}


class MAML:
    """
    Model-Agnostic Meta-Learning.
    
    Key features:
    - Learns initialization for fast adaptation
    - Task-agnostic: works with any differentiable model
    - Few-shot learning capability
    - Adapts to new market regimes quickly
    """
    
    def __init__(
        self,
        input_dim: int,
        output_dim: int,
        config: Optional[MAMLConfig] = None,
    ):
        self.input_dim = input_dim
        self.output_dim = output_dim
        self.config = config or MAMLConfig()
        
        # Initialize meta-learner network
        self.network = MAMLNetwork(
            input_dim, output_dim, self.config.hidden_dims
        )
        
        # Training statistics
        self._meta_iteration = 0
        self._meta_losses: List[float] = []
        self._adaptation_losses: List[float] = []
        
        logger.info(
            "MAML initialized: input_dim=%d, output_dim=%d",
            input_dim, output_dim
        )
    
    def inner_loop(
        self,
        task: MAMLTask,
        params: Dict[str, np.ndarray],
    ) -> Tuple[Dict[str, np.ndarray], float]:
        """
        Inner loop: adapt to a specific task.
        
        Returns (adapted_params, final_loss).
        """
        adapted_params = {k: v.copy() for k, v in params.items()}
        
        for step in range(self.config.n_inner_steps):
            # Compute gradients on support set
            gradients = self.network.compute_gradients(
                task.support_x, task.support_y, adapted_params
            )
            
            # Update parameters
            for key in adapted_params:
                adapted_params[key] -= self.config.inner_lr * gradients[key]
        
        # Compute final loss on support set
        final_loss = self.network.compute_loss(
            task.support_x, task.support_y, adapted_params
        )
        
        return adapted_params, final_loss
    
    def outer_loop(
        self,
        tasks: List[MAMLTask],
    ) -> Dict[str, Any]:
        """
        Outer loop: meta-update across tasks.
        
        Returns training info.
        """
        self._meta_iteration += 1
        
        meta_params = self.network.get_params()
        meta_gradients = {k: np.zeros_like(v) for k, v in meta_params.items()}
        
        total_query_loss = 0.0
        total_support_loss = 0.0
        
        for task in tasks:
            # Inner loop: adapt to task
            adapted_params, support_loss = self.inner_loop(task, meta_params)
            total_support_loss += support_loss
            
            # Compute query loss with adapted parameters
            query_loss = self.network.compute_loss(
                task.query_x, task.query_y, adapted_params
            )
            total_query_loss += query_loss
            
            # Compute meta-gradients
            if self.config.first_order:
                # First-order approximation: ignore second derivatives
                task_gradients = self.network.compute_gradients(
                    task.query_x, task.query_y, adapted_params
                )
            else:
                # Full MAML: compute gradients through inner loop
                # (Simplified: using first-order for numerical stability)
                task_gradients = self.network.compute_gradients(
                    task.query_x, task.query_y, adapted_params
                )
            
            # Accumulate gradients
            for key in meta_gradients:
                meta_gradients[key] += task_gradients[key]
        
        # Average gradients
        n_tasks = len(tasks)
        for key in meta_gradients:
            meta_gradients[key] /= n_tasks
        
        # Meta-update
        for key in meta_params:
            meta_params[key] -= self.config.outer_lr * meta_gradients[key]
        
        self.network.set_params(meta_params)
        
        # Track losses
        avg_query_loss = total_query_loss / n_tasks
        avg_support_loss = total_support_loss / n_tasks
        
        self._meta_losses.append(avg_query_loss)
        self._adaptation_losses.append(avg_support_loss)
        
        return {
            "meta_iteration": self._meta_iteration,
            "query_loss": avg_query_loss,
            "support_loss": avg_support_loss,
            "n_tasks": n_tasks,
        }
    
    def adapt(
        self,
        support_x: np.ndarray,
        support_y: np.ndarray,
        n_steps: Optional[int] = None,
    ) -> Dict[str, np.ndarray]:
        """
        Adapt to new data (few-shot learning).
        
        Returns adapted parameters.
        """
        n_steps = n_steps or self.config.n_inner_steps
        
        adapted_params = self.network.get_params()
        
        for step in range(n_steps):
            gradients = self.network.compute_gradients(
                support_x, support_y, adapted_params
            )
            
            for key in adapted_params:
                adapted_params[key] -= self.config.inner_lr * gradients[key]
        
        return adapted_params
    
    def predict(
        self,
        x: np.ndarray,
        params: Optional[Dict[str, np.ndarray]] = None,
    ) -> np.ndarray:
        """Make predictions."""
        return self.network.forward(x, params)
    
    def train(
        self,
        task_generator: Callable[[], List[MAMLTask]],
        n_iterations: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Full meta-training loop.
        
        task_generator: function that returns a batch of tasks
        """
        n_iterations = n_iterations or self.config.n_meta_iterations
        
        logger.info("Starting MAML training for %d iterations", n_iterations)
        start_time = time.time()
        
        for iteration in range(n_iterations):
            # Generate task batch
            tasks = task_generator()
            
            # Meta-update
            info = self.outer_loop(tasks)
            
            # Logging
            if (iteration + 1) % 50 == 0:
                avg_loss = np.mean(self._meta_losses[-50:])
                logger.info(
                    "Meta-iteration %d: avg_query_loss=%.4f",
                    iteration + 1, avg_loss
                )
        
        training_time = time.time() - start_time
        
        return {
            "n_iterations": n_iterations,
            "final_query_loss": self._meta_losses[-1] if self._meta_losses else 0,
            "avg_query_loss": np.mean(self._meta_losses[-100:]) if self._meta_losses else 0,
            "training_time_seconds": training_time,
        }
    
    def save(self, path: str) -> None:
        """Save model."""
        data = {
            "config": self.config.to_dict(),
            "params": self.network.get_params(),
            "meta_iteration": self._meta_iteration,
        }
        np.save(path, data, allow_pickle=True)
        logger.info("MAML saved to %s", path)
    
    def load(self, path: str) -> None:
        """Load model."""
        data = np.load(path, allow_pickle=True).item()
        self.network.set_params(data["params"])
        self._meta_iteration = data.get("meta_iteration", 0)
        logger.info("MAML loaded from %s", path)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get training statistics."""
        return {
            "meta_iteration": self._meta_iteration,
            "avg_query_loss": np.mean(self._meta_losses[-100:]) if self._meta_losses else 0,
            "avg_adaptation_loss": np.mean(self._adaptation_losses[-100:]) if self._adaptation_losses else 0,
            "config": self.config.to_dict(),
        }
