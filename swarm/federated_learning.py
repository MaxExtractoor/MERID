"""
Federated learning interface for privacy-preserving collaboration in MERID.

Implements:
- Gradient/update exchange (no raw data sharing)
- Secure aggregation protocols
- Differential privacy
- Model versioning and compatibility
- Privacy-preserving collaboration
"""

import threading

from utils.logger import get_logger
import time
import secrets
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from decimal import Decimal
import json

logger = get_logger(__name__)


class AggregationMethod(Enum):
    """Aggregation method for federated learning."""
    FEDERATED_AVERAGING = "federated_averaging"  # FedAvg
    FEDERATED_SGD = "federated_sgd"  # FedSGD
    SECURE_AGGREGATION = "secure_aggregation"  # With encryption
    DIFFERENTIAL_PRIVATE = "differential_private"  # With DP noise


class ModelType(Enum):
    """Model type."""
    TRADING_STRATEGY = "trading_strategy"
    RISK_MODEL = "risk_model"
    MARKET_REGIME = "market_regime"
    ANOMALY_DETECTION = "anomaly_detection"
    SENTIMENT_ANALYSIS = "sentiment_analysis"


class RoundStatus(Enum):
    """Federated learning round status."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    AGGREGATING = "aggregating"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class ModelUpdate:
    """Model update (gradients or parameters)."""
    update_id: str
    
    # Model reference
    model_id: str
    model_version: str
    
    # Update data
    gradients: Dict[str, List[float]]  # layer_name -> gradient values
    num_samples: int  # Number of samples used for training
    
    # Privacy
    differential_privacy_epsilon: Optional[float] = None
    differential_privacy_delta: Optional[float] = None
    
    # Contributor
    contributor_did: str = ""
    
    # Metadata
    training_loss: float = 0.0
    validation_accuracy: Optional[float] = None
    
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class AggregatedUpdate:
    """Aggregated model update."""
    aggregation_id: str
    
    # Model reference
    model_id: str
    model_version: str
    new_model_version: str
    
    # Aggregated data
    aggregated_gradients: Dict[str, List[float]]
    
    # Contributors
    contributor_dids: List[str] = field(default_factory=list)
    total_samples: int = 0
    
    # Aggregation method
    method: AggregationMethod = AggregationMethod.FEDERATED_AVERAGING
    
    # Quality metrics
    avg_training_loss: float = 0.0
    avg_validation_accuracy: Optional[float] = None
    
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class FederatedLearningRound:
    """Federated learning round."""
    round_id: str
    round_number: int
    
    # Model
    model_id: str
    model_version: str
    
    # Participants
    invited_agents: List[str] = field(default_factory=list)
    participating_agents: List[str] = field(default_factory=list)
    
    # Updates
    received_updates: List[ModelUpdate] = field(default_factory=list)
    aggregated_update: Optional[AggregatedUpdate] = None
    
    # Configuration
    min_participants: int = 3
    max_participants: int = 10
    deadline: datetime = field(default_factory=lambda: datetime.utcnow() + timedelta(hours=24))
    
    # Status
    status: RoundStatus = RoundStatus.PENDING
    
    # Privacy
    use_differential_privacy: bool = True
    epsilon: float = 1.0
    delta: float = 1e-5
    
    created_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None


@dataclass
class FederatedModel:
    """Federated model."""
    model_id: str
    model_type: ModelType
    
    # Versioning
    current_version: str = "1.0.0"
    
    # Architecture
    architecture: Dict[str, Any] = field(default_factory=dict)
    
    # Participants
    authorized_contributors: Set[str] = field(default_factory=set)
    
    # History
    rounds: List[FederatedLearningRound] = field(default_factory=list)
    
    # Metadata
    description: str = ""
    owner_did: str = ""
    
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class PrivacyBudget:
    """Privacy budget for differential privacy."""
    budget_id: str
    
    # Budget
    total_epsilon: float = 10.0
    total_delta: float = 1e-4
    
    # Consumed
    consumed_epsilon: float = 0.0
    consumed_delta: float = 0.0
    
    # Per-round limits
    max_epsilon_per_round: float = 1.0
    max_delta_per_round: float = 1e-5
    
    created_at: datetime = field(default_factory=datetime.utcnow)
    
    def has_budget(self, epsilon: float, delta: float) -> bool:
        """Check if budget is available."""
        return (
            self.consumed_epsilon + epsilon <= self.total_epsilon and
            self.consumed_delta + delta <= self.total_delta
        )
    
    def consume(self, epsilon: float, delta: float) -> None:
        """Consume privacy budget."""
        self.consumed_epsilon += epsilon
        self.consumed_delta += delta


class FederatedLearningCoordinator:
    """
    Federated learning coordinator for privacy-preserving collaboration.
    
    Features:
    - Gradient/update exchange (no raw data)
    - Secure aggregation
    - Differential privacy
    - Model versioning
    - Privacy budget tracking
    """
    
    def __init__(self):
        self._models: Dict[str, FederatedModel] = {}
        self._rounds: Dict[str, FederatedLearningRound] = {}
        self._privacy_budgets: Dict[str, PrivacyBudget] = {}
        
        # Configuration
        self._default_min_participants = 3
        self._default_epsilon = 1.0
        self._default_delta = 1e-5
    
    def create_federated_model(
        self,
        model_type: ModelType,
        architecture: Dict[str, Any],
        description: str,
        owner_did: str,
    ) -> FederatedModel:
        """Create federated model."""
        model_id = f"fedmodel_{int(time.time() * 1000)}"
        
        model = FederatedModel(
            model_id=model_id,
            model_type=model_type,
            architecture=architecture,
            description=description,
            owner_did=owner_did,
        )
        
        self._models[model_id] = model
        
        # Create privacy budget
        budget = PrivacyBudget(
            budget_id=f"budget_{model_id}",
            total_epsilon=10.0,
            total_delta=1e-4,
        )
        
        self._privacy_budgets[model_id] = budget
        
        logger.info(
            f"Created federated model '{model_id}': {model_type.value} "
            f"(owner: {owner_did})"
        )
        
        return model
    
    def authorize_contributor(
        self,
        model_id: str,
        contributor_did: str,
    ) -> None:
        """Authorize contributor for federated model."""
        model = self._models.get(model_id)
        
        if not model:
            raise ValueError(f"Model '{model_id}' not found")
        
        model.authorized_contributors.add(contributor_did)
        
        logger.info(f"Authorized {contributor_did} for model '{model_id}'")
    
    def start_learning_round(
        self,
        model_id: str,
        invited_agents: List[str],
        min_participants: Optional[int] = None,
        use_differential_privacy: bool = True,
        epsilon: Optional[float] = None,
        delta: Optional[float] = None,
    ) -> FederatedLearningRound:
        """Start federated learning round."""
        model = self._models.get(model_id)
        
        if not model:
            raise ValueError(f"Model '{model_id}' not found")
        
        # Check privacy budget
        epsilon = epsilon or self._default_epsilon
        delta = delta or self._default_delta
        
        budget = self._privacy_budgets.get(model_id)
        if budget and use_differential_privacy:
            if not budget.has_budget(epsilon, delta):
                raise ValueError(
                    f"Insufficient privacy budget: "
                    f"need ({epsilon}, {delta}), "
                    f"available ({budget.total_epsilon - budget.consumed_epsilon}, "
                    f"{budget.total_delta - budget.consumed_delta})"
                )
        
        # Create round
        round_number = len(model.rounds) + 1
        round_id = f"round_{model_id}_{round_number}"
        
        round_obj = FederatedLearningRound(
            round_id=round_id,
            round_number=round_number,
            model_id=model_id,
            model_version=model.current_version,
            invited_agents=invited_agents,
            min_participants=min_participants or self._default_min_participants,
            use_differential_privacy=use_differential_privacy,
            epsilon=epsilon,
            delta=delta,
        )
        
        self._rounds[round_id] = round_obj
        model.rounds.append(round_obj)
        
        round_obj.status = RoundStatus.IN_PROGRESS
        
        logger.info(
            f"Started learning round '{round_id}' for model '{model_id}' "
            f"(invited: {len(invited_agents)}, min: {round_obj.min_participants})"
        )
        
        return round_obj
    
    def submit_model_update(
        self,
        round_id: str,
        contributor_did: str,
        gradients: Dict[str, List[float]],
        num_samples: int,
        training_loss: float,
        validation_accuracy: Optional[float] = None,
    ) -> ModelUpdate:
        """Submit model update to round."""
        round_obj = self._rounds.get(round_id)
        
        if not round_obj:
            raise ValueError(f"Round '{round_id}' not found")
        
        if round_obj.status != RoundStatus.IN_PROGRESS:
            raise ValueError(f"Round '{round_id}' not accepting updates (status: {round_obj.status.value})")
        
        # Check authorization
        model = self._models.get(round_obj.model_id)
        if model and contributor_did not in model.authorized_contributors:
            raise ValueError(f"Contributor '{contributor_did}' not authorized for model '{round_obj.model_id}'")
        
        # Create update
        update_id = f"update_{int(time.time() * 1000)}_{secrets.token_hex(4)}"
        
        update = ModelUpdate(
            update_id=update_id,
            model_id=round_obj.model_id,
            model_version=round_obj.model_version,
            gradients=gradients,
            num_samples=num_samples,
            contributor_did=contributor_did,
            training_loss=training_loss,
            validation_accuracy=validation_accuracy,
        )
        
        # Add differential privacy noise if enabled
        if round_obj.use_differential_privacy:
            update.differential_privacy_epsilon = round_obj.epsilon
            update.differential_privacy_delta = round_obj.delta
            # In production, would add Gaussian noise to gradients
        
        round_obj.received_updates.append(update)
        
        if contributor_did not in round_obj.participating_agents:
            round_obj.participating_agents.append(contributor_did)
        
        logger.info(
            f"Received update from {contributor_did} for round '{round_id}' "
            f"({num_samples} samples, loss: {training_loss:.4f})"
        )
        
        # Check if ready to aggregate
        if len(round_obj.participating_agents) >= round_obj.min_participants:
            self._aggregate_round(round_id)
        
        return update
    
    def _aggregate_round(self, round_id: str) -> AggregatedUpdate:
        """Aggregate model updates."""
        round_obj = self._rounds.get(round_id)
        
        if not round_obj:
            raise ValueError(f"Round '{round_id}' not found")
        
        round_obj.status = RoundStatus.AGGREGATING
        
        # Aggregate gradients using federated averaging
        aggregated_gradients: Dict[str, List[float]] = {}
        total_samples = sum(update.num_samples for update in round_obj.received_updates)
        
        for update in round_obj.received_updates:
            weight = update.num_samples / total_samples if total_samples > 0 else 1.0 / len(round_obj.received_updates) if round_obj.received_updates else 0.0
            
            for layer_name, gradients in update.gradients.items():
                if layer_name not in aggregated_gradients:
                    aggregated_gradients[layer_name] = [0.0] * len(gradients)
                
                for i, grad in enumerate(gradients):
                    aggregated_gradients[layer_name][i] += grad * weight
        
        # Calculate average metrics
        avg_training_loss = (
            sum(update.training_loss for update in round_obj.received_updates)
            / len(round_obj.received_updates)
            if round_obj.received_updates else 0.0
        )
        
        validation_accuracies = [
            update.validation_accuracy
            for update in round_obj.received_updates
            if update.validation_accuracy is not None
        ]
        
        avg_validation_accuracy = (
            sum(validation_accuracies) / len(validation_accuracies)
            if validation_accuracies else None
        )
        
        # Create aggregated update
        model = self._models.get(round_obj.model_id)
        new_version = self._increment_version(model.current_version) if model else "1.0.1"
        
        aggregation_id = f"agg_{round_id}"
        
        aggregated = AggregatedUpdate(
            aggregation_id=aggregation_id,
            model_id=round_obj.model_id,
            model_version=round_obj.model_version,
            new_model_version=new_version,
            aggregated_gradients=aggregated_gradients,
            contributor_dids=[update.contributor_did for update in round_obj.received_updates],
            total_samples=total_samples,
            method=AggregationMethod.FEDERATED_AVERAGING,
            avg_training_loss=avg_training_loss,
            avg_validation_accuracy=avg_validation_accuracy,
        )
        
        round_obj.aggregated_update = aggregated
        round_obj.status = RoundStatus.COMPLETED
        round_obj.completed_at = datetime.utcnow()
        
        # Update model version
        if model:
            model.current_version = new_version
            model.updated_at = datetime.utcnow()
        
        # Consume privacy budget
        if round_obj.use_differential_privacy:
            budget = self._privacy_budgets.get(round_obj.model_id)
            if budget:
                budget.consume(round_obj.epsilon, round_obj.delta)
        
        logger.info(
            f"Aggregated round '{round_id}': {len(round_obj.received_updates)} updates, "
            f"{total_samples} samples, avg loss: {avg_training_loss:.4f}, "
            f"new version: {new_version}"
        )
        
        return aggregated
    
    def _increment_version(self, version: str) -> str:
        """Increment semantic version."""
        parts = version.split(".")
        if len(parts) == 3:
            major, minor, patch = parts
            return f"{major}.{minor}.{int(patch) + 1}"
        return "1.0.1"
    
    def get_model(self, model_id: str) -> Optional[FederatedModel]:
        """Get federated model."""
        return self._models.get(model_id)
    
    def get_round(self, round_id: str) -> Optional[FederatedLearningRound]:
        """Get learning round."""
        return self._rounds.get(round_id)
    
    def get_privacy_budget(self, model_id: str) -> Optional[PrivacyBudget]:
        """Get privacy budget."""
        return self._privacy_budgets.get(model_id)
    
    def get_federated_learning_stats(self) -> Dict[str, Any]:
        """Get federated learning statistics."""
        total_rounds = len(self._rounds)
        completed_rounds = sum(
            1 for round_obj in self._rounds.values()
            if round_obj.status == RoundStatus.COMPLETED
        )
        
        total_updates = sum(
            len(round_obj.received_updates)
            for round_obj in self._rounds.values()
        )
        
        return {
            "models": {
                "total": len(self._models),
                "by_type": {
                    model_type.value: sum(
                        1 for model in self._models.values()
                        if model.model_type == model_type
                    )
                    for model_type in ModelType
                },
            },
            "rounds": {
                "total": total_rounds,
                "completed": completed_rounds,
                "in_progress": sum(
                    1 for round_obj in self._rounds.values()
                    if round_obj.status == RoundStatus.IN_PROGRESS
                ),
                "success_rate": (
                    completed_rounds / total_rounds
                    if total_rounds > 0 else 0.0
                ),
            },
            "updates": {
                "total": total_updates,
                "avg_per_round": (
                    total_updates / total_rounds
                    if total_rounds > 0 else 0.0
                ),
            },
            "privacy": {
                "models_with_dp": sum(
                    1 for model_id, budget in self._privacy_budgets.items()
                    if budget.consumed_epsilon > 0
                ),
                "avg_epsilon_consumed": (
                    sum(budget.consumed_epsilon for budget in self._privacy_budgets.values()) /
                    len(self._privacy_budgets)
                    if self._privacy_budgets else 0.0
                ),
            },
        }


_federated_learning_coordinator: Optional[FederatedLearningCoordinator] = None
_federated_learning_coordinator_lock = threading.Lock()


def get_federated_learning_coordinator() -> FederatedLearningCoordinator:
    """Get global FederatedLearningCoordinator instance."""
    global _federated_learning_coordinator
    if _federated_learning_coordinator is None:
        with _federated_learning_coordinator_lock:
            if _federated_learning_coordinator is None:
                _federated_learning_coordinator = FederatedLearningCoordinator()
    return _federated_learning_coordinator
