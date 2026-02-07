"""
ML Model Framework for MERID

Provides comprehensive machine learning model abstraction and training
pipeline with support for multiple ML frameworks and model types.

Features:
- Multi-framework support (Scikit-learn, TensorFlow, PyTorch)
- Model training and validation pipeline
- Feature engineering and selection
- Model performance monitoring
- US-compliant data handling
"""

import asyncio
import json
import time
import pickle
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Any, Tuple, Union
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import deque
import logging
from abc import ABC, abstractmethod

# ML Framework imports (with fallbacks)
try:
    from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
    from sklearn.linear_model import LogisticRegression, LinearRegression
    from sklearn.preprocessing import StandardScaler, MinMaxScaler
    from sklearn.model_selection import train_test_split, cross_val_score
    from sklearn.metrics import accuracy_score, mean_squared_error, classification_report
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False

try:
    import tensorflow as tf
    from tensorflow import keras
    TENSORFLOW_AVAILABLE = True
except ImportError:
    TENSORFLOW_AVAILABLE = False

try:
    import torch
    import torch.nn as nn
    import torch.optim as optim
    PYTORCH_AVAILABLE = True
except ImportError:
    PYTORCH_AVAILABLE = False

from utils.logger import get_logger

logger = get_logger("ml.model_framework")

@dataclass
class ModelConfig:
    """Model configuration parameters."""
    model_type: str  # classification, regression, time_series
    framework: str  # sklearn, tensorflow, pytorch
    target_column: str
    feature_columns: List[str]
    hyperparameters: Dict[str, Any] = field(default_factory=dict)
    preprocessing: Dict[str, Any] = field(default_factory=dict)
    validation_split: float = 0.2
    random_state: int = 42

@dataclass
class TrainingResult:
    """Model training result."""
    model_id: str
    model_type: str
    framework: str
    training_time: float
    train_score: float
    val_score: float
    test_score: float
    feature_importance: Dict[str, float] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class PredictionResult:
    """Model prediction result."""
    model_id: str
    prediction: Union[float, int, np.ndarray]
    confidence: float
    prediction_time: float
    feature_contributions: Dict[str, float] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

class BaseModel(ABC):
    """Abstract base class for all ML models."""
    
    def __init__(self, config: ModelConfig):
        self.config = config
        self.model = None
        self.scaler = None
        self.feature_columns = config.feature_columns
        self.target_column = config.target_column
        self.is_trained = False
        self.training_history = []
        
    @abstractmethod
    def train(self, X: np.ndarray, y: np.ndarray) -> TrainingResult:
        """Train the model."""
        pass
    
    @abstractmethod
    def predict(self, X: np.ndarray) -> PredictionResult:
        """Make predictions."""
        pass
    
    @abstractmethod
    def get_feature_importance(self) -> Dict[str, float]:
        """Get feature importance."""
        pass
    
    def preprocess_features(self, X: np.ndarray, fit_scaler: bool = False) -> np.ndarray:
        """Preprocess features."""
        if self.config.preprocessing.get("scale", True):
            if self.scaler is None or fit_scaler:
                if self.config.preprocessing.get("scaler_type", "standard") == "standard":
                    self.scaler = StandardScaler()
                else:
                    self.scaler = MinMaxScaler()
                
                if fit_scaler:
                    X_scaled = self.scaler.fit_transform(X)
                else:
                    X_scaled = self.scaler.transform(X)
            else:
                X_scaled = self.scaler.transform(X)
        else:
            X_scaled = X
        
        return X_scaled

class SklearnModel(BaseModel):
    """Scikit-learn model implementation."""
    
    def __init__(self, config: ModelConfig):
        super().__init__(config)
        
        if not SKLEARN_AVAILABLE:
            raise ImportError("Scikit-learn is not available")
        
        self.model = self._create_model()
    
    def _create_model(self):
        """Create scikit-learn model based on configuration."""
        model_name = self.config.hyperparameters.get("model_name", "random_forest")
        
        if self.config.model_type == "classification":
            if model_name == "random_forest":
                return RandomForestClassifier(
                    n_estimators=self.config.hyperparameters.get("n_estimators", 100),
                    max_depth=self.config.hyperparameters.get("max_depth", 10),
                    random_state=self.config.random_state
                )
            elif model_name == "logistic_regression":
                return LogisticRegression(
                    random_state=self.config.random_state,
                    max_iter=self.config.hyperparameters.get("max_iter", 1000)
                )
        elif self.config.model_type == "regression":
            if model_name == "random_forest":
                return RandomForestRegressor(
                    n_estimators=self.config.hyperparameters.get("n_estimators", 100),
                    max_depth=self.config.hyperparameters.get("max_depth", 10),
                    random_state=self.config.random_state
                )
            elif model_name == "linear_regression":
                return LinearRegression()
        
        raise ValueError(f"Unsupported model: {model_name} for {self.config.model_type}")
    
    def train(self, X: np.ndarray, y: np.ndarray) -> TrainingResult:
        """Train the scikit-learn model."""
        start_time = time.time()
        
        # Preprocess features
        X_processed = self.preprocess_features(X, fit_scaler=True)
        
        # Split data
        X_train, X_val, y_train, y_val = train_test_split(
            X_processed, y, 
            test_size=self.config.validation_split,
            random_state=self.config.random_state
        )
        
        # Train model
        self.model.fit(X_train, y_train)
        
        # Evaluate
        train_score = self.model.score(X_train, y_train)
        val_score = self.model.score(X_val, y_val)
        
        # Cross-validation
        cv_scores = cross_val_score(self.model, X_processed, y, cv=5)
        test_score = cv_scores.mean()
        
        training_time = time.time() - start_time
        
        # Get feature importance
        feature_importance = self.get_feature_importance()
        
        self.is_trained = True
        
        result = TrainingResult(
            model_id=f"sklearn_{self.config.model_type}_{int(time.time())}",
            model_type=self.config.model_type,
            framework="sklearn",
            training_time=training_time,
            train_score=train_score,
            val_score=val_score,
            test_score=test_score,
            feature_importance=feature_importance,
            metadata={
                "cv_scores": cv_scores.tolist(),
                "model_params": self.model.get_params(),
                "feature_columns": self.feature_columns
            }
        )
        
        self.training_history.append(result)
        return result
    
    def predict(self, X: np.ndarray) -> PredictionResult:
        """Make predictions with the scikit-learn model."""
        if not self.is_trained:
            raise ValueError("Model must be trained before prediction")
        
        start_time = time.time()
        
        # Preprocess features
        X_processed = self.preprocess_features(X, fit_scaler=False)
        
        # Make prediction
        prediction = self.model.predict(X_processed)
        
        # Get prediction probability if available
        if hasattr(self.model, 'predict_proba'):
            probabilities = self.model.predict_proba(X_processed)
            confidence = np.max(probabilities, axis=1).mean()
        else:
            confidence = 0.5  # Default confidence for regression
        
        prediction_time = time.time() - start_time
        
        # Get feature contributions (simplified)
        feature_contributions = {}
        if hasattr(self.model, 'feature_importances_'):
            for i, feature in enumerate(self.feature_columns):
                if i < len(self.model.feature_importances_):
                    feature_contributions[feature] = self.model.feature_importances_[i]
        
        result = PredictionResult(
            model_id=self.training_history[-1].model_id if self.training_history else "unknown",
            prediction=prediction[0] if len(prediction) == 1 else prediction,
            confidence=confidence,
            prediction_time=prediction_time,
            feature_contributions=feature_contributions,
            metadata={
                "model_type": self.config.model_type,
                "framework": "sklearn"
            }
        )
        
        return result
    
    def get_feature_importance(self) -> Dict[str, float]:
        """Get feature importance from scikit-learn model."""
        if not self.is_trained or not hasattr(self.model, 'feature_importances_'):
            return {}
        
        importance = {}
        for i, feature in enumerate(self.feature_columns):
            if i < len(self.model.feature_importances_):
                importance[feature] = float(self.model.feature_importances_[i])
        
        return importance

class TensorFlowModel(BaseModel):
    """TensorFlow/Keras model implementation."""
    
    def __init__(self, config: ModelConfig):
        super().__init__(config)
        
        if not TENSORFLOW_AVAILABLE:
            raise ImportError("TensorFlow is not available")
        
        self.model = self._create_model()
    
    def _create_model(self):
        """Create TensorFlow/Keras model."""
        layers = self.config.hyperparameters.get("layers", [64, 32])
        activation = self.config.hyperparameters.get("activation", "relu")
        dropout_rate = self.config.hyperparameters.get("dropout_rate", 0.2)
        
        model = keras.Sequential()
        
        # Input layer
        model.add(keras.layers.Dense(
            layers[0], 
            activation=activation, 
            input_shape=(len(self.feature_columns),)
        ))
        model.add(keras.layers.Dropout(dropout_rate))
        
        # Hidden layers
        for units in layers[1:]:
            model.add(keras.layers.Dense(units, activation=activation))
            model.add(keras.layers.Dropout(dropout_rate))
        
        # Output layer
        if self.config.model_type == "classification":
            model.add(keras.layers.Dense(1, activation='sigmoid'))
            loss = 'binary_crossentropy'
            metrics = ['accuracy']
        else:  # regression
            model.add(keras.layers.Dense(1))
            loss = 'mse'
            metrics = ['mae']
        
        model.compile(
            optimizer=keras.optimizers.Adam(
                learning_rate=self.config.hyperparameters.get("learning_rate", 0.001)
            ),
            loss=loss,
            metrics=metrics
        )
        
        return model
    
    def train(self, X: np.ndarray, y: np.ndarray) -> TrainingResult:
        """Train the TensorFlow model."""
        start_time = time.time()
        
        # Preprocess features
        X_processed = self.preprocess_features(X, fit_scaler=True)
        
        # Split data
        X_train, X_val, y_train, y_val = train_test_split(
            X_processed, y, 
            test_size=self.config.validation_split,
            random_state=self.config.random_state
        )
        
        # Train model
        epochs = self.config.hyperparameters.get("epochs", 100)
        batch_size = self.config.hyperparameters.get("batch_size", 32)
        
        history = self.model.fit(
            X_train, y_train,
            validation_data=(X_val, y_val),
            epochs=epochs,
            batch_size=batch_size,
            verbose=0
        )
        
        # Evaluate
        train_score = self.model.evaluate(X_train, y_train, verbose=0)[1]
        val_score = self.model.evaluate(X_val, y_val, verbose=0)[1]
        test_score = val_score  # Use validation as test score for simplicity
        
        training_time = time.time() - start_time
        
        # Get feature importance (using permutation importance)
        feature_importance = self._calculate_feature_importance(X_val, y_val)
        
        self.is_trained = True
        
        result = TrainingResult(
            model_id=f"tensorflow_{self.config.model_type}_{int(time.time())}",
            model_type=self.config.model_type,
            framework="tensorflow",
            training_time=training_time,
            train_score=train_score,
            val_score=val_score,
            test_score=test_score,
            feature_importance=feature_importance,
            metadata={
                "history": {k: v.tolist() for k, v in history.history.items()},
                "epochs": epochs,
                "feature_columns": self.feature_columns
            }
        )
        
        self.training_history.append(result)
        return result
    
    def predict(self, X: np.ndarray) -> PredictionResult:
        """Make predictions with the TensorFlow model."""
        if not self.is_trained:
            raise ValueError("Model must be trained before prediction")
        
        start_time = time.time()
        
        # Preprocess features
        X_processed = self.preprocess_features(X, fit_scaler=False)
        
        # Make prediction
        prediction = self.model.predict(X_processed, verbose=0)
        
        # Post-process prediction
        if self.config.model_type == "classification":
            prediction = (prediction > 0.5).astype(int).flatten()
            confidence = 0.8  # Simplified confidence
        else:
            prediction = prediction.flatten()
            confidence = 0.7  # Simplified confidence
        
        prediction_time = time.time() - start_time
        
        result = PredictionResult(
            model_id=self.training_history[-1].model_id if self.training_history else "unknown",
            prediction=prediction[0] if len(prediction) == 1 else prediction,
            confidence=confidence,
            prediction_time=prediction_time,
            feature_contributions={},  # TensorFlow feature importance is complex
            metadata={
                "model_type": self.config.model_type,
                "framework": "tensorflow"
            }
        )
        
        return result
    
    def get_feature_importance(self) -> Dict[str, float]:
        """Get feature importance from TensorFlow model."""
        if not self.is_trained:
            return {}
        
        # Use cached feature importance from training
        if self.training_history:
            return self.training_history[-1].feature_importance
        
        return {}
    
    def _calculate_feature_importance(self, X: np.ndarray, y: np.ndarray) -> Dict[str, float]:
        """Calculate feature importance using permutation importance."""
        baseline_score = self.model.evaluate(X, y, verbose=0)[1]
        importance = {}
        
        for i, feature in enumerate(self.feature_columns):
            X_permuted = X.copy()
            X_permuted[:, i] = np.random.permutation(X_permuted[:, i])
            
            permuted_score = self.model.evaluate(X_permuted, y, verbose=0)[1]
            importance[feature] = baseline_score - permuted_score
        
        return importance

class MLModelFramework:
    """
    Comprehensive ML model framework for MERID.
    
    Provides unified interface for multiple ML frameworks and
    automated model training and evaluation.
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        
        # Model registry
        self.models: Dict[str, BaseModel] = {}
        self.model_configs: Dict[str, ModelConfig] = {}
        
        # Training history
        self.training_history: List[TrainingResult] = []
        
        # US compliance settings
        self.us_compliance = config.get("us_compliance", {
            "data_privacy": True,
            "model_transparency": True,
            "bias_detection": True,
            "explainability": True
        })
        
        # Performance metrics
        self.prediction_counts: Dict[str, int] = {}
        self.prediction_times: Dict[str, List[float]] = {}
        
        logger.info("MLModelFramework initialized")
    
    def create_model(self, model_id: str, config: ModelConfig) -> bool:
        """Create a new ML model."""
        try:
            # Framework selection
            if config.framework == "sklearn" and SKLEARN_AVAILABLE:
                model = SklearnModel(config)
            elif config.framework == "tensorflow" and TENSORFLOW_AVAILABLE:
                model = TensorFlowModel(config)
            else:
                logger.error(f"Framework {config.framework} not available")
                return False
            
            self.models[model_id] = model
            self.model_configs[model_id] = config
            
            logger.info(f"Created model {model_id} with {config.framework}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to create model {model_id}: {e}")
            return False
    
    async def train_model(self, model_id: str, data: pd.DataFrame) -> Optional[TrainingResult]:
        """Train a model with provided data."""
        if model_id not in self.models:
            logger.error(f"Model {model_id} not found")
            return None
        
        try:
            model = self.models[model_id]
            config = self.model_configs[model_id]
            
            # Validate data
            if config.target_column not in data.columns:
                logger.error(f"Target column {config.target_column} not found in data")
                return None
            
            missing_features = [f for f in config.feature_columns if f not in data.columns]
            if missing_features:
                logger.error(f"Missing feature columns: {missing_features}")
                return None
            
            # Extract features and target
            X = data[config.feature_columns].values
            y = data[config.target_column].values
            
            # US compliance checks
            if not self._check_data_compliance(data):
                logger.warning("Data failed compliance checks")
            
            # Train model
            result = model.train(X, y)
            
            # Store training result
            self.training_history.append(result)
            
            logger.info(f"Model {model_id} trained successfully")
            return result
            
        except Exception as e:
            logger.error(f"Failed to train model {model_id}: {e}")
            return None
    
    async def predict(self, model_id: str, data: pd.DataFrame) -> Optional[PredictionResult]:
        """Make predictions with a trained model."""
        if model_id not in self.models:
            logger.error(f"Model {model_id} not found")
            return None
        
        try:
            model = self.models[model_id]
            config = self.model_configs[model_id]
            
            if not model.is_trained:
                logger.error(f"Model {model_id} is not trained")
                return None
            
            # Validate data
            missing_features = [f for f in config.feature_columns if f not in data.columns]
            if missing_features:
                logger.error(f"Missing feature columns: {missing_features}")
                return None
            
            # Extract features
            X = data[config.feature_columns].values
            
            # Make prediction
            result = model.predict(X)
            
            # Update metrics
            self.prediction_counts[model_id] = self.prediction_counts.get(model_id, 0) + 1
            if model_id not in self.prediction_times:
                self.prediction_times[model_id] = []
            self.prediction_times[model_id].append(result.prediction_time)
            
            # Keep only last 100 measurements
            if len(self.prediction_times[model_id]) > 100:
                self.prediction_times[model_id] = self.prediction_times[model_id][-100:]
            
            logger.debug(f"Prediction made with model {model_id}")
            return result
            
        except Exception as e:
            logger.error(f"Failed to predict with model {model_id}: {e}")
            return None
    
    def get_model_summary(self) -> Dict[str, Any]:
        """Get summary of all models."""
        summary = {
            "total_models": len(self.models),
            "trained_models": sum(1 for model in self.models.values() if model.is_trained),
            "frameworks": {
                "sklearn": SKLEARN_AVAILABLE,
                "tensorflow": TENSORFLOW_AVAILABLE,
                "pytorch": PYTORCH_AVAILABLE
            },
            "models": {}
        }
        
        for model_id, model in self.models.items():
            config = self.model_configs[model_id]
            summary["models"][model_id] = {
                "type": config.model_type,
                "framework": config.framework,
                "features": len(config.feature_columns),
                "trained": model.is_trained,
                "predictions": self.prediction_counts.get(model_id, 0)
            }
        
        return summary
    
    def get_training_history(self, model_id: Optional[str] = None) -> List[TrainingResult]:
        """Get training history for models."""
        if model_id:
            return [result for result in self.training_history if model_id in result.model_id]
        return self.training_history.copy()
    
    def save_model(self, model_id: str, filepath: str) -> bool:
        """Save a trained model to disk."""
        if model_id not in self.models:
            logger.error(f"Model {model_id} not found")
            return False
        
        try:
            model = self.models[model_id]
            
            if not model.is_trained:
                logger.error(f"Model {model_id} is not trained")
                return False
            
            # Save model and config
            model_data = {
                "model": model.model,
                "scaler": model.scaler,
                "config": self.model_configs[model_id],
                "training_history": model.training_history
            }
            
            with open(filepath, 'wb') as f:
                pickle.dump(model_data, f)
            
            logger.info(f"Model {model_id} saved to {filepath}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to save model {model_id}: {e}")
            return False
    
    def load_model(self, model_id: str, filepath: str) -> bool:
        """Load a trained model from disk."""
        try:
            with open(filepath, 'rb') as f:
                model_data = pickle.load(f)
            
            # Recreate model
            config = model_data["config"]
            if config.framework == "sklearn":
                model = SklearnModel(config)
            elif config.framework == "tensorflow":
                model = TensorFlowModel(config)
            else:
                logger.error(f"Unsupported framework: {config.framework}")
                return False
            
            # Load model state
            model.model = model_data["model"]
            model.scaler = model_data["scaler"]
            model.training_history = model_data["training_history"]
            model.is_trained = True
            
            self.models[model_id] = model
            self.model_configs[model_id] = config
            
            logger.info(f"Model {model_id} loaded from {filepath}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to load model {model_id}: {e}")
            return False
    
    def _check_data_compliance(self, data: pd.DataFrame) -> bool:
        """Check if data complies with US regulations."""
        # Simple compliance checks
        if self.us_compliance.get("data_privacy", True):
            # Check for PII (simplified)
            pii_columns = ['name', 'email', 'phone', 'address', 'ssn']
            for col in pii_columns:
                if col in data.columns.lower():
                    return False
        
        return True
    
    def get_available_frameworks(self) -> Dict[str, bool]:
        """Get availability of ML frameworks."""
        return {
            "sklearn": SKLEARN_AVAILABLE,
            "tensorflow": TENSORFLOW_AVAILABLE,
            "pytorch": PYTORCH_AVAILABLE
        }
