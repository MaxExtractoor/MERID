"""Tests for ml/model_framework.py - ML Model Framework."""
import pytest
import numpy as np
from unittest.mock import patch, MagicMock, Mock
from dataclasses import asdict

from ml.model_framework import (
    ModelConfig,
    TrainingResult,
    PredictionResult,
    SKLEARN_AVAILABLE,
)


class TestModelConfig:
    """Test ModelConfig dataclass."""

    def test_creation(self):
        """Test creating model config."""
        config = ModelConfig(
            model_type="classification",
            framework="sklearn",
            target_column="target",
            feature_columns=["feat1", "feat2", "feat3"],
        )
        assert config.model_type == "classification"
        assert config.framework == "sklearn"
        assert len(config.feature_columns) == 3

    def test_default_values(self):
        """Test default values."""
        config = ModelConfig(
            model_type="regression",
            framework="sklearn",
            target_column="price",
            feature_columns=["vol", "momentum"],
        )
        assert config.hyperparameters == {}
        assert config.preprocessing == {}
        assert config.validation_split == 0.2
        assert config.random_state == 42

    def test_with_hyperparameters(self):
        """Test with hyperparameters."""
        config = ModelConfig(
            model_type="classification",
            framework="sklearn",
            target_column="signal",
            feature_columns=["rsi", "macd"],
            hyperparameters={"n_estimators": 100, "max_depth": 5},
        )
        assert config.hyperparameters["n_estimators"] == 100
        assert config.hyperparameters["max_depth"] == 5


class TestTrainingResult:
    """Test TrainingResult dataclass."""

    def test_creation(self):
        """Test creating training result."""
        result = TrainingResult(
            model_id="model_001",
            model_type="classification",
            framework="sklearn",
            training_time=10.5,
            train_score=0.95,
            val_score=0.90,
            test_score=0.88,
        )
        assert result.model_id == "model_001"
        assert result.train_score == 0.95
        assert result.feature_importance == {}

    def test_with_feature_importance(self):
        """Test with feature importance."""
        result = TrainingResult(
            model_id="model_002",
            model_type="regression",
            framework="sklearn",
            training_time=5.2,
            train_score=0.85,
            val_score=0.82,
            test_score=0.80,
            feature_importance={"vol": 0.4, "momentum": 0.3, "rsi": 0.3},
        )
        assert result.feature_importance["vol"] == 0.4
        assert sum(result.feature_importance.values()) == pytest.approx(1.0)


class TestPredictionResult:
    """Test PredictionResult dataclass."""

    def test_creation(self):
        """Test creating prediction result."""
        result = PredictionResult(
            model_id="model_001",
            prediction=1,
            confidence=0.85,
            prediction_time=0.05,
        )
        assert result.model_id == "model_001"
        assert result.prediction == 1
        assert result.confidence == 0.85

    def test_with_array_prediction(self):
        """Test with array prediction."""
        predictions = np.array([0.1, 0.2, 0.7])
        result = PredictionResult(
            model_id="model_002",
            prediction=predictions,
            confidence=0.7,
            prediction_time=0.1,
            feature_contributions={"feat1": 0.3, "feat2": 0.7},
        )
        assert len(result.prediction) == 3
        assert result.feature_contributions["feat2"] == 0.7


@pytest.mark.skipif(not SKLEARN_AVAILABLE, reason="Sklearn not available")
class TestSklearnModel:
    """Test SklearnModel class."""

    @pytest.fixture
    def classification_config(self):
        """Create classification config."""
        return ModelConfig(
            model_type="classification",
            framework="sklearn",
            target_column="target",
            feature_columns=["feat1", "feat2", "feat3"],
            hyperparameters={"n_estimators": 10, "max_depth": 3},
        )

    @pytest.fixture
    def regression_config(self):
        """Create regression config."""
        return ModelConfig(
            model_type="regression",
            framework="sklearn",
            target_column="price",
            feature_columns=["vol", "momentum"],
            hyperparameters={"n_estimators": 10},
        )

    @pytest.fixture
    def sample_classification_data(self):
        """Create sample classification data."""
        np.random.seed(42)
        X = np.random.randn(100, 3)
        y = (X[:, 0] + X[:, 1] > 0).astype(int)
        return X, y

    @pytest.fixture
    def sample_regression_data(self):
        """Create sample regression data."""
        np.random.seed(42)
        X = np.random.randn(100, 2)
        y = X[:, 0] * 2 + X[:, 1] * 0.5 + np.random.randn(100) * 0.1
        return X, y

    def test_sklearn_model_creation(self, classification_config):
        """Test creating sklearn model."""
        from ml.model_framework import SklearnModel
        
        model = SklearnModel(classification_config)
        assert model.config == classification_config
        assert model.model is not None
        assert model.is_trained is False

    def test_sklearn_classification_training(self, classification_config, sample_classification_data):
        """Test training classification model."""
        from ml.model_framework import SklearnModel
        
        X, y = sample_classification_data
        model = SklearnModel(classification_config)
        
        result = model.train(X, y)
        
        assert model.is_trained is True
        assert result.model_type == "classification"
        assert result.train_score >= 0
        assert result.train_score <= 1

    def test_sklearn_regression_training(self, regression_config, sample_regression_data):
        """Test training regression model."""
        from ml.model_framework import SklearnModel
        
        X, y = sample_regression_data
        model = SklearnModel(regression_config)
        
        result = model.train(X, y)
        
        assert model.is_trained is True
        assert result.model_type == "regression"

    def test_sklearn_prediction(self, classification_config, sample_classification_data):
        """Test making predictions."""
        from ml.model_framework import SklearnModel
        
        X, y = sample_classification_data
        model = SklearnModel(classification_config)
        model.train(X, y)
        
        result = model.predict(X[:5])
        
        assert result.model_id is not None
        assert result.prediction_time > 0

    def test_sklearn_feature_importance(self, classification_config, sample_classification_data):
        """Test getting feature importance."""
        from ml.model_framework import SklearnModel
        
        X, y = sample_classification_data
        model = SklearnModel(classification_config)
        model.train(X, y)
        
        importance = model.get_feature_importance()
        
        assert isinstance(importance, dict)
        assert len(importance) == 3

    def test_preprocessing_standard_scaler(self, classification_config, sample_classification_data):
        """Test preprocessing with standard scaler."""
        from ml.model_framework import SklearnModel
        
        classification_config.preprocessing = {"scale": True, "scaler_type": "standard"}
        X, y = sample_classification_data
        model = SklearnModel(classification_config)
        
        X_scaled = model.preprocess_features(X, fit_scaler=True)
        
        assert X_scaled.shape == X.shape
        assert np.abs(X_scaled.mean()) < 0.1  # Should be close to 0

    def test_preprocessing_minmax_scaler(self, classification_config, sample_classification_data):
        """Test preprocessing with minmax scaler."""
        from ml.model_framework import SklearnModel
        
        classification_config.preprocessing = {"scale": True, "scaler_type": "minmax"}
        X, y = sample_classification_data
        model = SklearnModel(classification_config)
        
        X_scaled = model.preprocess_features(X, fit_scaler=True)
        
        assert X_scaled.min() >= 0
        assert X_scaled.max() <= 1


class TestMLModelFramework:
    """Test MLModelFramework class."""

    @pytest.fixture
    def framework_config(self):
        """Create framework config."""
        return {
            "default_framework": "sklearn",
            "model_storage_path": "/tmp/models",
            "auto_train": False,
        }

    @pytest.fixture
    def framework(self, framework_config):
        """Create ML framework."""
        from ml.model_framework import MLModelFramework
        return MLModelFramework(framework_config)

    def test_framework_creation(self, framework):
        """Test creating framework."""
        assert framework is not None
        assert framework.models == {}

    @pytest.mark.skipif(not SKLEARN_AVAILABLE, reason="Sklearn not available")
    def test_create_model(self, framework):
        """Test creating a model."""
        config = ModelConfig(
            model_type="classification",
            framework="sklearn",
            target_column="target",
            feature_columns=["f1", "f2"],
        )
        
        result = framework.create_model("test_model", config)
        
        assert result is True
        assert "test_model" in framework.models

    @pytest.mark.skipif(not SKLEARN_AVAILABLE, reason="Sklearn not available")
    def test_create_model_invalid_framework(self, framework):
        """Test creating model with invalid framework."""
        config = ModelConfig(
            model_type="classification",
            framework="invalid_framework",
            target_column="target",
            feature_columns=["f1", "f2"],
        )
        
        result = framework.create_model("bad_model", config)
        
        assert result is False

    def test_framework_has_models_dict(self, framework):
        """Test framework has models dictionary."""
        assert hasattr(framework, 'models')
        assert isinstance(framework.models, dict)

    def test_framework_has_training_history(self, framework):
        """Test framework has training history."""
        assert hasattr(framework, 'training_history')
        assert isinstance(framework.training_history, list)
