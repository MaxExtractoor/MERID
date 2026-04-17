"""
Deep Learning Models for MERID AI-Powered Signals

Provides comprehensive deep learning models for signal generation
with US-compliant configuration.

Features:
- LSTM neural networks
- Transformer models
- CNN for pattern recognition
- Ensemble deep learning
- US-compliant model training
"""

import asyncio
import time
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Any, Tuple, Union
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import deque
from enum import Enum

from utils.logger import get_logger

logger = get_logger("ai_signals.deep_learning_models")

class ModelType(Enum):
    """Model type enumeration."""
    LSTM = "lstm"
    TRANSFORMER = "transformer"
    CNN = "cnn"
    GRU = "gru"
    ENSEMBLE = "ensemble"
    HYBRID = "hybrid"

class TrainingStatus(Enum):
    """Training status enumeration."""
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

@dataclass
class ModelArchitecture:
    """Model architecture definition."""
    model_id: str
    model_name: str
    model_type: ModelType
    input_shape: Tuple[int, ...]
    layers: List[Dict[str, Any]]
    parameters: int
    trainable_parameters: int
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class TrainingConfig:
    """Training configuration."""
    model_id: str
    batch_size: int
    epochs: int
    learning_rate: float
    optimizer: str
    loss_function: str
    metrics: List[str]
    validation_split: float
    early_stopping: bool
    dropout_rate: float
    regularization: str
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class ModelPerformance:
    """Model performance metrics."""
    model_id: str
    training_loss: float
    validation_loss: float
    test_loss: float
    accuracy: float
    precision: float
    recall: float
    f1_score: float
    auc_score: float
    training_time: float
    inference_time: float
    memory_usage: float
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class PredictionResult:
    """Prediction result."""
    model_id: str
    prediction: float
    confidence: float
    features_used: List[str]
    processing_time: float
    timestamp: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)

class DeepLearningModels:
    """
    Comprehensive deep learning models system for MERID.
    
    Provides LSTM, Transformer, CNN, and ensemble models for
    signal generation with US-compliant configuration.
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        
        # Model architectures
        self.architectures: Dict[str, ModelArchitecture] = {}
        
        # Training configurations
        self.training_configs: Dict[str, TrainingConfig] = {}
        
        # Model performance
        self.performance_metrics: Dict[str, ModelPerformance] = {}
        
        # Training status
        self.training_status: Dict[str, TrainingStatus] = {}
        
        # Model weights (mock - in production, use actual model storage)
        self.model_weights: Dict[str, Any] = {}
        
        # Training history
        self.training_history: Dict[str, List[Dict[str, float]]] = {}
        
        # Configuration
        self.model_config = config.get("deep_learning", {
            "max_models": 10,
            "max_training_time": 3600,  # 1 hour
            "min_accuracy": 0.6,
            "max_memory_usage": 1024 * 1024 * 1024,  # 1GB
            "batch_prediction": True
        })
        
        # Model templates
        self.model_templates = {
            ModelType.LSTM: {
                "layers": [
                    {"type": "LSTM", "units": 50, "return_sequences": True},
                    {"type": "Dropout", "rate": 0.2},
                    {"type": "LSTM", "units": 50, "return_sequences": False},
                    {"type": "Dropout", "rate": 0.2},
                    {"type": "Dense", "units": 25, "activation": "relu"},
                    {"type": "Dense", "units": 1, "activation": "sigmoid"}
                ]
            },
            ModelType.TRANSFORMER: {
                "layers": [
                    {"type": "Input", "shape": (100, 10)},
                    {"type": "TransformerEncoder", "num_heads": 8, "ff_dim": 128},
                    {"type": "GlobalAveragePooling1D"},
                    {"type": "Dropout", "rate": 0.1},
                    {"type": "Dense", "units": 64, "activation": "relu"},
                    {"type": "Dense", "units": 1, "activation": "sigmoid"}
                ]
            },
            ModelType.CNN: {
                "layers": [
                    {"type": "Conv1D", "filters": 64, "kernel_size": 3, "activation": "relu"},
                    {"type": "MaxPooling1D", "pool_size": 2},
                    {"type": "Conv1D", "filters": 128, "kernel_size": 3, "activation": "relu"},
                    {"type": "MaxPooling1D", "pool_size": 2},
                    {"type": "Flatten"},
                    {"type": "Dense", "units": 64, "activation": "relu"},
                    {"type": "Dropout", "rate": 0.5},
                    {"type": "Dense", "units": 1, "activation": "sigmoid"}
                ]
            },
            ModelType.GRU: {
                "layers": [
                    {"type": "GRU", "units": 50, "return_sequences": True},
                    {"type": "Dropout", "rate": 0.2},
                    {"type": "GRU", "units": 50, "return_sequences": False},
                    {"type": "Dropout", "rate": 0.2},
                    {"type": "Dense", "units": 25, "activation": "relu"},
                    {"type": "Dense", "units": 1, "activation": "sigmoid"}
                ]
            }
        }
        
        # US compliance settings
        self.us_compliance = config.get("us_compliance", {
            "model_validation": True,
            "training_transparency": True,
            "performance_disclosure": True,
            "audit_models": True
        })
        
        logger.info("DeepLearningModels initialized")
    
    async def create_model(self, model_id: str, model_name: str, model_type: ModelType,
                         input_shape: Tuple[int, ...], custom_layers: Optional[List[Dict[str, Any]]] = None) -> bool:
        """Create a deep learning model."""
        try:
            # Validate model configuration
            if not self._validate_model_config(model_type, input_shape):
                logger.error(f"Invalid model configuration: {model_id}")
                return False
            
            # Get layers from template or custom
            if custom_layers:
                layers = custom_layers
            else:
                layers = self.model_templates.get(model_type, {}).get("layers", [])
            
            # Calculate parameters (simplified)
            parameters = self._calculate_model_parameters(layers, input_shape)
            trainable_parameters = parameters  # Simplified
            
            # Create architecture
            architecture = ModelArchitecture(
                model_id=model_id,
                model_name=model_name,
                model_type=model_type,
                input_shape=input_shape,
                layers=layers,
                parameters=parameters,
                trainable_parameters=trainable_parameters
            )
            
            # Store architecture
            self.architectures[model_id] = architecture
            
            # Initialize training status
            self.training_status[model_id] = TrainingStatus.NOT_STARTED
            
            # Initialize training history
            self.training_history[model_id] = []
            
            # Record for compliance
            if self.us_compliance.get("audit_models", True):
                await self._record_model_creation(architecture)
            
            logger.info(f"Model created: {model_id} ({model_type.value})")
            return True
            
        except Exception as e:
            logger.error(f"Failed to create model {model_id}: {e}")
            return False
    
    def _validate_model_config(self, model_type: ModelType, input_shape: Tuple[int, ...]) -> bool:
        """Validate model configuration."""
        try:
            # Check model type
            if model_type not in ModelType:
                return False
            
            # Check input shape
            if not input_shape or len(input_shape) < 2:
                return False
            
            # Check model count limit
            if len(self.architectures) >= self.model_config["max_models"]:
                return False
            
            # US compliance checks
            if self.us_compliance.get("model_validation", True):
                if not self._validate_model_compliance(model_type, input_shape):
                    return False
            
            return True
            
        except Exception as e:
            logger.error(f"Model configuration validation error: {e}")
            return False
    
    def _validate_model_compliance(self, model_type: ModelType, input_shape: Tuple[int, ...]) -> bool:
        """Validate model for US compliance."""
        try:
            # Check model complexity
            if len(input_shape) > 1000:  # Too complex
                return False
            
            # Check model type restrictions
            restricted_types = []  # In production, define restricted types
            if model_type.value in restricted_types:
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Model compliance validation error: {e}")
            return False
    
    def _calculate_model_parameters(self, layers: List[Dict[str, Any]], input_shape: Tuple[int, ...]) -> int:
        """Calculate model parameters (simplified)."""
        try:
            total_params = 0
            current_shape = input_shape
            
            for layer in layers:
                layer_type = layer.get("type", "")
                
                if layer_type == "Dense":
                    units = layer.get("units", 1)
                    input_features = current_shape[-1] if len(current_shape) > 0 else 1
                    total_params += input_features * units + units
                    current_shape = (units,)
                
                elif layer_type in ["LSTM", "GRU"]:
                    units = layer.get("units", 50)
                    input_features = current_shape[-1] if len(current_shape) > 0 else 1
                    # Simplified parameter calculation
                    total_params += 4 * (input_features * units + units * units + units)
                    if layer.get("return_sequences", False):
                        current_shape = (current_shape[0], units)
                    else:
                        current_shape = (units,)
                
                elif layer_type == "Conv1D":
                    filters = layer.get("filters", 64)
                    kernel_size = layer.get("kernel_size", 3)
                    input_features = current_shape[-1] if len(current_shape) > 0 else 1
                    total_params += filters * (kernel_size * input_features + 1)
                    # Simplified output shape
                    current_shape = (current_shape[0] // 2, filters)  # Assuming pooling
                
                elif layer_type == "TransformerEncoder":
                    # Simplified transformer parameter calculation
                    num_heads = layer.get("num_heads", 8)
                    ff_dim = layer.get("ff_dim", 128)
                    d_model = current_shape[-1] if len(current_shape) > 0 else 128
                    total_params += 4 * d_model * d_model + 2 * d_model * ff_dim
                    # Output shape remains the same
                    current_shape = current_shape
            
            return total_params
            
        except Exception as e:
            logger.error(f"Parameter calculation error: {e}")
            return 0
    
    async def configure_training(self, model_id: str, batch_size: int = 32, epochs: int = 100,
                              learning_rate: float = 0.001, optimizer: str = "adam",
                              loss_function: str = "binary_crossentropy",
                              metrics: Optional[List[str]] = None,
                              validation_split: float = 0.2,
                              early_stopping: bool = True,
                              dropout_rate: float = 0.2,
                              regularization: str = "l2") -> bool:
        """Configure training parameters."""
        try:
            # Check model exists
            if model_id not in self.architectures:
                logger.error(f"Model {model_id} not found")
                return False
            
            # Create training config
            training_config = TrainingConfig(
                model_id=model_id,
                batch_size=batch_size,
                epochs=epochs,
                learning_rate=learning_rate,
                optimizer=optimizer,
                loss_function=loss_function,
                metrics=metrics or ["accuracy"],
                validation_split=validation_split,
                early_stopping=early_stopping,
                dropout_rate=dropout_rate,
                regularization=regularization
            )
            
            # Store training config
            self.training_configs[model_id] = training_config
            
            logger.info(f"Training configured for {model_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to configure training for {model_id}: {e}")
            return False
    
    async def train_model(self, model_id: str, training_data: pd.DataFrame,
                        target_data: pd.DataFrame,
                        validation_data: Optional[Tuple[pd.DataFrame, pd.DataFrame]] = None) -> bool:
        """Train a deep learning model."""
        try:
            # Check model exists
            if model_id not in self.architectures:
                logger.error(f"Model {model_id} not found")
                return False
            
            # Check training config
            if model_id not in self.training_configs:
                logger.error(f"Training configuration not found for {model_id}")
                return False
            
            # Update training status
            self.training_status[model_id] = TrainingStatus.IN_PROGRESS
            
            # Get training config
            config = self.training_configs[model_id]
            
            # Mock training process
            logger.info(f"Starting training for {model_id}")
            
            start_time = time.time()
            
            # Simulate training epochs
            training_history = []
            
            for epoch in range(config.epochs):
                # Mock training loss
                training_loss = 1.0 * np.exp(-epoch / 50) + np.random.normal(0, 0.01)
                validation_loss = training_loss + np.random.normal(0, 0.02)
                accuracy = min(1.0, 0.5 + epoch / 100 + np.random.normal(0, 0.05))
                
                # Record epoch metrics
                epoch_metrics = {
                    "epoch": epoch + 1,
                    "training_loss": training_loss,
                    "validation_loss": validation_loss,
                    "accuracy": accuracy,
                    "timestamp": time.time()
                }
                
                training_history.append(epoch_metrics)
                
                # Early stopping check
                if config.early_stopping and epoch > 10:
                    recent_losses = [h["validation_loss"] for h in training_history[-5:]]
                    if np.std(recent_losses) < 0.001:  # Convergence
                        logger.info(f"Early stopping at epoch {epoch + 1}")
                        break
                
                # Progress logging
                if (epoch + 1) % 10 == 0:
                    logger.info(f"Epoch {epoch + 1}/{config.epochs} - Loss: {training_loss:.4f}, Accuracy: {accuracy:.4f}")
            
            training_time = time.time() - start_time
            
            # Calculate final metrics
            final_metrics = training_history[-1]
            
            # Create performance metrics
            performance = ModelPerformance(
                model_id=model_id,
                training_loss=final_metrics["training_loss"],
                validation_loss=final_metrics["validation_loss"],
                test_loss=final_metrics["validation_loss"],  # Simplified
                accuracy=final_metrics["accuracy"],
                precision=final_metrics["accuracy"] * 0.95,  # Mock
                recall=final_metrics["accuracy"] * 0.90,     # Mock
                f1_score=final_metrics["accuracy"] * 0.92,   # Mock
                auc_score=final_metrics["accuracy"] * 0.98,  # Mock
                training_time=training_time,
                inference_time=0.001,  # Mock
                memory_usage=100.0,    # Mock MB
                metadata={"epochs_trained": len(training_history)}
            )
            
            # Store results
            self.performance_metrics[model_id] = performance
            self.training_history[model_id] = training_history
            self.model_weights[model_id] = f"mock_weights_{model_id}"  # Mock weights
            
            # Update training status
            self.training_status[model_id] = TrainingStatus.COMPLETED
            
            # Record for compliance
            if self.us_compliance.get("audit_models", True):
                await self._record_model_training(model_id, performance)
            
            logger.info(f"Training completed for {model_id} - Accuracy: {performance.accuracy:.4f}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to train model {model_id}: {e}")
            self.training_status[model_id] = TrainingStatus.FAILED
            return False
    
    async def predict(self, model_id: str, input_data: np.ndarray) -> Optional[PredictionResult]:
        """Generate prediction using a trained model."""
        try:
            # Check model exists and is trained
            if model_id not in self.architectures:
                logger.error(f"Model {model_id} not found")
                return None
            
            if self.training_status.get(model_id) != TrainingStatus.COMPLETED:
                logger.error(f"Model {model_id} not trained")
                return None
            
            # Check model weights
            if model_id not in self.model_weights:
                logger.error(f"Model weights not found for {model_id}")
                return None
            
            start_time = time.time()
            
            # Mock prediction process
            architecture = self.architectures[model_id]
            
            # Simulate model inference
            if architecture.model_type == ModelType.LSTM:
                prediction = self._lstm_predict(input_data)
            elif architecture.model_type == ModelType.TRANSFORMER:
                prediction = self._transformer_predict(input_data)
            elif architecture.model_type == ModelType.CNN:
                prediction = self._cnn_predict(input_data)
            elif architecture.model_type == ModelType.GRU:
                prediction = self._gru_predict(input_data)
            else:
                prediction = np.random.uniform(-1, 1)
            
            # Calculate confidence
            confidence = min(1.0, abs(prediction) + np.random.uniform(0, 0.2))
            
            processing_time = time.time() - start_time
            
            # Create prediction result
            result = PredictionResult(
                model_id=model_id,
                prediction=prediction,
                confidence=confidence,
                features_used=["price", "volume", "momentum"],  # Mock
                processing_time=processing_time,
                timestamp=datetime.now()
            )
            
            return result
            
        except Exception as e:
            logger.error(f"Failed to generate prediction for {model_id}: {e}")
            return None
    
    def _lstm_predict(self, input_data: np.ndarray) -> float:
        """Mock LSTM prediction."""
        # Simplified LSTM prediction logic
        if len(input_data.shape) < 3:
            input_data = input_data.reshape(1, -1, 1)
        
        # Mock LSTM processing
        last_values = input_data[-1, -5:, 0] if input_data.shape[1] >= 5 else input_data[-1, :, 0].flatten()
        
        # Simple momentum-based prediction
        if len(last_values) >= 2:
            momentum = (last_values[-1] - last_values[0]) / last_values[0]
            return np.tanh(momentum * 2)  # Scale to [-1, 1]
        
        return np.random.uniform(-0.5, 0.5)
    
    def _transformer_predict(self, input_data: np.ndarray) -> float:
        """Mock Transformer prediction."""
        # Simplified Transformer prediction logic
        if len(input_data.shape) < 3:
            input_data = input_data.reshape(1, -1, 1)
        
        # Mock attention mechanism
        sequence = input_data[0, :, 0]
        
        # Simple attention weights (mock)
        attention_weights = np.softmax(sequence)
        
        # Weighted prediction
        prediction = np.sum(sequence * attention_weights) / np.sum(attention_weights)
        
        return np.tanh(prediction)
    
    def _cnn_predict(self, input_data: np.ndarray) -> float:
        """Mock CNN prediction."""
        # Simplified CNN prediction logic
        if len(input_data.shape) < 3:
            input_data = input_data.reshape(1, -1, 1)
        
        # Mock convolution
        sequence = input_data[0, :, 0]
        
        # Simple pattern detection
        if len(sequence) >= 5:
            # Detect upward/downward patterns
            recent_trend = np.mean(sequence[-3:]) - np.mean(sequence[-6:-3]) if len(sequence) >= 6 else 0
            return np.tanh(recent_trend)
        
        return np.random.uniform(-0.3, 0.3)
    
    def _gru_predict(self, input_data: np.ndarray) -> float:
        """Mock GRU prediction."""
        # Similar to LSTM but simplified
        return self._lstm_predict(input_data) * 0.9  # Slightly different output
    
    async def batch_predict(self, model_id: str, input_batch: List[np.ndarray]) -> List[PredictionResult]:
        """Generate batch predictions."""
        try:
            if not self.model_config.get("batch_prediction", True):
                # Fall back to individual predictions
                results = []
                for input_data in input_batch:
                    result = await self.predict(model_id, input_data)
                    if result:
                        results.append(result)
                return results
            
            # Mock batch prediction
            results = []
            for input_data in input_batch:
                result = await self.predict(model_id, input_data)
                if result:
                    results.append(result)
            
            return results
            
        except Exception as e:
            logger.error(f"Failed to generate batch predictions: {e}")
            return []
    
    async def evaluate_model(self, model_id: str, test_data: pd.DataFrame,
                          test_targets: pd.DataFrame) -> Optional[ModelPerformance]:
        """Evaluate model performance."""
        try:
            # Check model exists and is trained
            if model_id not in self.architectures:
                return None
            
            if self.training_status.get(model_id) != TrainingStatus.COMPLETED:
                return None
            
            # Mock evaluation
            n_samples = len(test_data)
            predictions = []
            
            for i in range(min(n_samples, 100)):  # Limit for performance
                input_data = test_data.iloc[i].values.reshape(1, -1, 1)
                result = await self.predict(model_id, input_data)
                if result:
                    predictions.append(result.prediction)
            
            if not predictions:
                return None
            
            # Calculate metrics
            predictions = np.array(predictions)
            actuals = test_targets.iloc[:len(predictions)].values
            
            # Mock metric calculations
            accuracy = np.mean(np.sign(predictions) == np.sign(actuals))
            precision = accuracy * 0.95  # Mock
            recall = accuracy * 0.90     # Mock
            f1_score = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0
            auc_score = accuracy * 0.98  # Mock
            
            # Create performance metrics
            performance = ModelPerformance(
                model_id=model_id,
                training_loss=self.performance_metrics[model_id].training_loss,
                validation_loss=self.performance_metrics[model_id].validation_loss,
                test_loss=1.0 - accuracy,  # Mock
                accuracy=accuracy,
                precision=precision,
                recall=recall,
                f1_score=f1_score,
                auc_score=auc_score,
                training_time=self.performance_metrics[model_id].training_time,
                inference_time=0.001,  # Mock
                memory_usage=100.0,    # Mock MB
                metadata={"test_samples": len(predictions)}
            )
            
            # Update performance metrics
            self.performance_metrics[model_id] = performance
            
            return performance
            
        except Exception as e:
            logger.error(f"Failed to evaluate model {model_id}: {e}")
            return None
    
    def get_model_architecture(self, model_id: str) -> Optional[ModelArchitecture]:
        """Get model architecture."""
        return self.architectures.get(model_id)
    
    def get_training_config(self, model_id: str) -> Optional[TrainingConfig]:
        """Get training configuration."""
        return self.training_configs.get(model_id)
    
    def get_model_performance(self, model_id: str) -> Optional[ModelPerformance]:
        """Get model performance."""
        return self.performance_metrics.get(model_id)
    
    def get_training_history(self, model_id: str) -> List[Dict[str, float]]:
        """Get training history."""
        return self.training_history.get(model_id, [])
    
    def get_all_models(self) -> Dict[str, ModelArchitecture]:
        """Get all model architectures."""
        return self.architectures.copy()
    
    def get_model_summary(self) -> Dict[str, Any]:
        """Get comprehensive model summary."""
        try:
            # Model type distribution
            model_types = {}
            total_parameters = 0
            
            for architecture in self.architectures.values():
                model_type = architecture.model_type.value
                model_types[model_type] = model_types.get(model_type, 0) + 1
                total_parameters += architecture.parameters
            
            # Training status distribution
            training_statuses = {}
            for model_id, status in self.training_status.items():
                status_name = status.value
                training_statuses[status_name] = training_statuses.get(status_name, 0) + 1
            
            # Performance summary
            performance_summary = {}
            if self.performance_metrics:
                accuracies = [p.accuracy for p in self.performance_metrics.values()]
                performance_summary = {
                    "avg_accuracy": np.mean(accuracies),
                    "max_accuracy": np.max(accuracies),
                    "min_accuracy": np.min(accuracies)
                }
            
            return {
                "total_models": len(self.architectures),
                "model_types": model_types,
                "training_statuses": training_statuses,
                "total_parameters": total_parameters,
                "performance_summary": performance_summary,
                "us_compliance": self.us_compliance
            }
            
        except Exception as e:
            logger.error(f"Failed to get model summary: {e}")
            return {"status": "error", "error": str(e)}
    
    def delete_model(self, model_id: str) -> bool:
        """Delete a model."""
        try:
            # Remove from all dictionaries
            if model_id in self.architectures:
                del self.architectures[model_id]
            if model_id in self.training_configs:
                del self.training_configs[model_id]
            if model_id in self.performance_metrics:
                del self.performance_metrics[model_id]
            if model_id in self.training_status:
                del self.training_status[model_id]
            if model_id in self.model_weights:
                del self.model_weights[model_id]
            if model_id in self.training_history:
                del self.training_history[model_id]
            
            logger.info(f"Model deleted: {model_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete model {model_id}: {e}")
            return False
    
    async def _record_model_creation(self, architecture: ModelArchitecture):
        """Record model creation for compliance."""
        if not self.us_compliance.get("audit_models", True):
            return
        
        audit_entry = {
            "action": "model_creation",
            "model_id": architecture.model_id,
            "model_name": architecture.model_name,
            "model_type": architecture.model_type.value,
            "parameters": architecture.parameters,
            "input_shape": architecture.input_shape,
            "timestamp": time.time(),
            "user": "system"  # In production, get actual user
        }
        
        # In production, store in audit database
        logger.debug(f"Model creation audit entry: {audit_entry}")
    
    async def _record_model_training(self, model_id: str, performance: ModelPerformance):
        """Record model training for compliance."""
        if not self.us_compliance.get("audit_models", True):
            return
        
        audit_entry = {
            "action": "model_training",
            "model_id": model_id,
            "accuracy": performance.accuracy,
            "precision": performance.precision,
            "recall": performance.recall,
            "training_time": performance.training_time,
            "epochs": len(self.training_history.get(model_id, [])),
            "timestamp": time.time(),
            "user": "system"  # In production, get actual user
        }
        
        # In production, store in audit database
        logger.debug(f"Model training audit entry: {audit_entry}")
    
    def update_config(self, new_config: Dict[str, Any]):
        """Update deep learning configuration."""
        self.config.update(new_config)
        
        # Update specific parameters
        if "deep_learning" in new_config:
            self.model_config.update(new_config["deep_learning"])
        
        logger.info("Deep learning models configuration updated")
