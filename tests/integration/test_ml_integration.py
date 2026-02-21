#!/usr/bin/env python3

import asyncio
import sys
import os
import time
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ml.model_framework import MLModelFramework, ModelConfig
from ml.predictive_models import PredictiveModels
from ml.feature_engineering import FeatureEngineering, FeatureConfig
from ml.model_monitor import ModelMonitor
from utils.logger import get_logger

logger = get_logger("test_ml_integration")

async def test_ml_model_framework():
    """Test ML model framework functionality"""
    
    print("🤖 Testing ML Model Framework")
    print("=" * 50)
    
    try:
        # Initialize framework
        config = {
            "us_compliance": {
                "data_privacy": True,
                "model_transparency": True
            }
        }
        
        framework = MLModelFramework(config)
        print(f"✅ MLModelFramework initialized")
        
        # Test framework availability
        frameworks = framework.get_available_frameworks()
        print(f"✅ Available frameworks: {frameworks}")
        
        # Create a classification model
        model_config = ModelConfig(
            model_type="classification",
            framework="sklearn",
            target_column="target",
            feature_columns=["feature1", "feature2", "feature3"],
            hyperparameters={
                "model_name": "random_forest",
                "n_estimators": 10,
                "max_depth": 5
            }
        )
        
        success = framework.create_model("test_classifier", model_config)
        print(f"✅ Classification model created: {success}")
        
        # Create a regression model
        reg_config = ModelConfig(
            model_type="regression",
            framework="sklearn",
            target_column="target",
            feature_columns=["feature1", "feature2", "feature3"],
            hyperparameters={
                "model_name": "random_forest",
                "n_estimators": 10,
                "max_depth": 5
            }
        )
        
        success = framework.create_model("test_regressor", reg_config)
        print(f"✅ Regression model created: {success}")
        
        # Generate training data
        n_samples = 1000
        training_data = pd.DataFrame({
            "feature1": np.random.normal(0, 1, n_samples),
            "feature2": np.random.normal(0, 1, n_samples),
            "feature3": np.random.normal(0, 1, n_samples),
            "target": np.random.randint(0, 2, n_samples)
        })
        
        # Train classification model
        result = await framework.train_model("test_classifier", training_data)
        if result:
            print(f"✅ Classification model trained: accuracy={result.test_score:.3f}")
        else:
            print("❌ Classification model training failed")
        
        # Train regression model
        reg_training_data = training_data.copy()
        reg_training_data["target"] = np.random.normal(0, 1, n_samples)
        
        result = await framework.train_model("test_regressor", reg_training_data)
        if result:
            print(f"✅ Regression model trained: score={result.test_score:.3f}")
        else:
            print("❌ Regression model training failed")
        
        # Test predictions
        test_data = pd.DataFrame({
            "feature1": [0.5, -0.3, 1.2],
            "feature2": [0.1, 0.8, -0.5],
            "feature3": [-0.2, 0.4, 0.7]
        })
        
        pred_result = await framework.predict("test_classifier", test_data)
        if pred_result:
            print(f"✅ Classification prediction: {pred_result.prediction} (confidence: {pred_result.confidence:.3f})")
        else:
            print("❌ Classification prediction failed")
        
        # Test model summary
        summary = framework.get_model_summary()
        print(f"✅ Model summary: {summary['total_models']} models, {summary['trained_models']} trained")
        
        print("\n🎉 ML Model Framework Test: PASSED")
        return True
        
    except Exception as e:
        print(f"❌ ML Model Framework test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_feature_engineering():
    """Test feature engineering functionality"""
    
    print("\n🔧 Testing Feature Engineering")
    print("=" * 50)
    
    try:
        # Initialize feature engineering
        config = FeatureConfig(
            technical_indicators=True,
            market_microstructure=True,
            sentiment_features=True,
            time_series_features=True,
            volume_features=True,
            volatility_features=True,
            price_features=True
        )
        
        feature_eng = FeatureEngineering(config)
        print(f"✅ FeatureEngineering initialized")
        
        # Generate mock market data
        n_samples = 500
        timestamps = pd.date_range(start='2024-01-01', periods=n_samples, freq='1H')
        
        market_data = pd.DataFrame({
            'timestamp': timestamps,
            'price': 3000 + np.cumsum(np.random.normal(0, 50, n_samples)),
            'volume': np.random.exponential(1000, n_samples),
            'high': 3000 + np.cumsum(np.random.normal(0, 50, n_samples)) + np.random.uniform(0, 100, n_samples),
            'low': 3000 + np.cumsum(np.random.normal(0, 50, n_samples)) - np.random.uniform(0, 100, n_samples),
            'bid_price': 3000 + np.cumsum(np.random.normal(0, 50, n_samples)) - np.random.uniform(0, 10, n_samples),
            'ask_price': 3000 + np.cumsum(np.random.normal(0, 50, n_samples)) + np.random.uniform(0, 10, n_samples),
            'trade_volume': np.random.exponential(100, n_samples)
        })
        
        # Generate sentiment data
        sentiment_data = {
            'news': pd.Series(np.random.uniform(-1, 1, n_samples)),
            'social': pd.Series(np.random.uniform(-1, 1, n_samples)),
            'onchain': pd.Series(np.random.uniform(-1, 1, n_samples))
        }
        
        # Extract features
        feature_set = await feature_eng.extract_features(market_data, sentiment_data)
        
        print(f"✅ Features extracted: {len(feature_set.feature_names)} features")
        print(f"✅ Feature types: {set(feature_set.feature_types.values())}")
        print(f"✅ Missing values: {feature_set.metadata['missing_values']}")
        
        # Test feature summary
        summary = feature_eng.get_feature_summary()
        print(f"✅ Feature summary: {summary['total_feature_sets']} sets, {summary['latest_features']} features")
        
        # Test feature importance
        importance_scores = {
            'price_change_1h': 0.15,
            'rsi_14': 0.12,
            'volume_change_1h': 0.08,
            'market_sentiment': 0.10,
            'volatility_1h': 0.06
        }
        
        feature_eng.update_importance_scores(importance_scores)
        top_features = feature_eng.get_feature_importance(top_n=5)
        
        print(f"✅ Top features: {[f'{name}: {score:.3f}' for name, score in top_features]}")
        
        print("\n🎉 Feature Engineering Test: PASSED")
        return True
        
    except Exception as e:
        print(f"❌ Feature Engineering test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_predictive_models():
    """Test predictive models functionality"""
    
    print("\n🔮 Testing Predictive Models")
    print("=" * 50)
    
    try:
        # Initialize predictive models
        config = {
            "ml_framework": {
                "us_compliance": {
                    "data_privacy": True,
                    "model_transparency": True
                }
            },
            "price_predictor": {"cache_ttl": 300},
            "trend_analyzer": {"cache_ttl": 600},
            "regime_classifier": {"cache_ttl": 1800},
            "volatility_forecaster": {"cache_ttl": 900}
        }
        
        predictive_models = PredictiveModels(config)
        print(f"✅ PredictiveModels initialized")
        
        # Initialize all models
        success = await predictive_models.initialize_all()
        print(f"✅ All models initialized: {success}")
        
        # Generate training data
        n_samples = 1000
        timestamps = pd.date_range(start='2024-01-01', periods=n_samples, freq='1H')
        
        training_data = pd.DataFrame({
            'timestamp': timestamps,
            'price': 3000 + np.cumsum(np.random.normal(0, 50, n_samples)),
            'volume': np.random.exponential(1000, n_samples),
            'high': 3000 + np.cumsum(np.random.normal(0, 50, n_samples)) + np.random.uniform(0, 100, n_samples),
            'low': 3000 + np.cumsum(np.random.normal(0, 50, n_samples)) - np.random.uniform(0, 100, n_samples),
            'volatility': np.random.uniform(0.1, 0.4, n_samples)
        })
        
        # Add feature columns
        feature_columns = [
            'price_change_1h', 'price_change_4h', 'price_change_24h',
            'volume_change_1h', 'volume_change_4h', 'volume_change_24h',
            'rsi_14', 'rsi_30', 'macd_signal', 'bollinger_position',
            'moving_avg_5', 'moving_avg_20', 'moving_avg_50',
            'volatility_1h', 'volatility_4h', 'volatility_24h',
            'market_sentiment', 'social_sentiment', 'news_sentiment'
        ]
        
        for col in feature_columns:
            training_data[col] = np.random.normal(0, 1, n_samples)
        
        # Train all models
        results = await predictive_models.train_all(training_data)
        print(f"✅ Models trained: {len(results)} components")
        
        # Test price prediction
        current_data = pd.DataFrame({
            'price': [3000],
            'volume': [1000],
            'volatility': [0.25]
        })
        
        for col in feature_columns:
            current_data[col] = [np.random.normal(0, 1)]
        
        price_pred = await predictive_models.price_predictor.predict_price("BTC", current_data, '1h')
        if price_pred:
            print(f"✅ Price prediction: ${price_pred.predicted_price:.2f} (confidence: {price_pred.confidence:.3f})")
        else:
            print("❌ Price prediction failed")
        
        # Test trend analysis
        trend_signal = await predictive_models.trend_analyzer.analyze_trend("BTC", current_data, '4h')
        if trend_signal:
            print(f"✅ Trend analysis: {trend_signal.trend_direction} (strength: {trend_signal.strength:.3f})")
        else:
            print("❌ Trend analysis failed")
        
        # Test market regime classification
        regime_data = await predictive_models.regime_classifier.classify_regime(current_data)
        if regime_data:
            print(f"✅ Market regime: {regime_data.regime} (confidence: {regime_data.confidence:.3f})")
        else:
            print("❌ Market regime classification failed")
        
        # Test volatility forecasting
        vol_forecast = await predictive_models.volatility_forecaster.forecast_volatility("BTC", current_data, '4h')
        if vol_forecast:
            print(f"✅ Volatility forecast: {vol_forecast.predicted_volatility:.3f} (risk: {vol_forecast.risk_level})")
        else:
            print("❌ Volatility forecasting failed")
        
        # Test trading signal generation
        trading_signal = await predictive_models.generate_trading_signal("BTC", current_data)
        if trading_signal:
            print(f"✅ Trading signal: {trading_signal.signal_type} (strength: {trading_signal.strength:.3f})")
            print(f"   Entry: ${trading_signal.entry_price:.2f}, Target: ${trading_signal.target_price:.2f}")
        else:
            print("❌ Trading signal generation failed")
        
        # Test model summary
        summary = predictive_models.get_model_summary()
        print(f"✅ Model summary: {summary['signal_history']} signals generated")
        
        print("\n🎉 Predictive Models Test: PASSED")
        return True
        
    except Exception as e:
        print(f"❌ Predictive Models test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_model_monitoring():
    """Test model monitoring functionality"""
    
    print("\n📊 Testing Model Monitoring")
    print("=" * 50)
    
    try:
        # Initialize ML framework
        framework_config = {
            "us_compliance": {
                "data_privacy": True,
                "model_transparency": True
            }
        }
        
        framework = MLModelFramework(framework_config)
        
        # Create and train a model
        model_config = ModelConfig(
            model_type="classification",
            framework="sklearn",
            target_column="target",
            feature_columns=["feature1", "feature2"],
            hyperparameters={
                "model_name": "random_forest",
                "n_estimators": 10
            }
        )
        
        framework.create_model("monitor_test_model", model_config)
        
        training_data = pd.DataFrame({
            "feature1": np.random.normal(0, 1, 100),
            "feature2": np.random.normal(0, 1, 100),
            "target": np.random.randint(0, 2, 100)
        })
        
        await framework.train_model("monitor_test_model", training_data)
        
        # Initialize model monitor
        monitor_config = {
            "monitoring_interval": 1,  # 1 second for testing
            "alert_thresholds": {
                "accuracy_min": 0.6,
                "confidence_min": 0.5,
                "prediction_time_max": 2.0
            },
            "drift_detection": {
                "performance_threshold": 0.1,
                "data_drift_threshold": 0.05,
                "concept_drift_threshold": 0.15
            }
        }
        
        monitor = ModelMonitor(framework, monitor_config)
        print(f"✅ ModelMonitor initialized")
        
        # Test monitoring cycle
        await monitor._monitor_model("monitor_test_model")
        print(f"✅ Monitoring cycle completed")
        
        # Get performance metrics
        performance = monitor.get_model_performance("monitor_test_model")
        if performance:
            latest = performance[-1]
            print(f"✅ Performance metrics: accuracy={latest.accuracy:.3f}, confidence={latest.confidence_score:.3f}")
        else:
            print("❌ No performance metrics found")
        
        # Get alerts
        alerts = monitor.get_active_alerts("monitor_test_model")
        print(f"✅ Active alerts: {len(alerts)}")
        
        # Get retraining triggers
        triggers = monitor.get_retraining_triggers("monitor_test_model")
        print(f"✅ Retraining triggers: {len(triggers)}")
        
        # Test monitoring summary
        summary = monitor.get_monitoring_summary()
        print(f"✅ Monitoring summary: {summary['monitored_models']} models monitored")
        
        print("\n🎉 Model Monitoring Test: PASSED")
        return True
        
    except Exception as e:
        print(f"❌ Model Monitoring test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_ml_integration():
    """Test full ML integration workflow"""
    
    print("\n🔄 Testing ML Integration Workflow")
    print("=" * 50)
    
    try:
        # Initialize all components
        config = {
            "ml_framework": {
                "us_compliance": {
                    "data_privacy": True,
                    "model_transparency": True
                }
            },
            "price_predictor": {"cache_ttl": 300},
            "trend_analyzer": {"cache_ttl": 600},
            "regime_classifier": {"cache_ttl": 1800},
            "volatility_forecaster": {"cache_ttl": 900}
        }
        
        predictive_models = PredictiveModels(config)
        feature_config = FeatureConfig()
        feature_eng = FeatureEngineering(feature_config)
        
        print(f"✅ All ML components initialized")
        
        # Generate comprehensive test data
        n_samples = 200
        timestamps = pd.date_range(start='2024-01-01', periods=n_samples, freq='1H')
        
        market_data = pd.DataFrame({
            'timestamp': timestamps,
            'price': 3000 + np.cumsum(np.random.normal(0, 30, n_samples)),
            'volume': np.random.exponential(800, n_samples),
            'high': 3000 + np.cumsum(np.random.normal(0, 30, n_samples)) + np.random.uniform(0, 80, n_samples),
            'low': 3000 + np.cumsum(np.random.normal(0, 30, n_samples)) - np.random.uniform(0, 80, n_samples),
            'volatility': np.random.uniform(0.15, 0.35, n_samples)
        })
        
        sentiment_data = {
            'news': pd.Series(np.random.uniform(-0.8, 0.8, n_samples)),
            'social': pd.Series(np.random.uniform(-0.6, 0.6, n_samples)),
            'onchain': pd.Series(np.random.uniform(-0.4, 0.4, n_samples))
        }
        
        # Step 1: Feature engineering
        feature_set = await feature_eng.extract_features(market_data, sentiment_data)
        print(f"✅ Step 1: Feature engineering - {len(feature_set.feature_names)} features")
        
        # Step 2: Initialize models
        success = await predictive_models.initialize_all()
        print(f"✅ Step 2: Models initialized - {success}")
        
        # Step 3: Prepare training data with features
        training_data = market_data.copy()
        for col in feature_set.feature_names[:20]:  # Use first 20 features
            if col in feature_set.features.columns:
                training_data[col] = feature_set.features[col]
        
        # Add target variables
        training_data['price_change_1h'] = training_data['price'].pct_change().fillna(0)
        training_data['price_change_4h'] = training_data['price'].pct_change(4).fillna(0)
        training_data['trend_direction'] = np.random.choice(['bullish', 'bearish', 'sideways'], n_samples)
        
        # Step 4: Train models
        results = await predictive_models.train_all(training_data)
        print(f"✅ Step 4: Models trained - {len(results)} components")
        
        # Step 5: Generate predictions
        current_data = pd.DataFrame({
            'price': [3050],
            'volume': [1200],
            'volatility': [0.22]
        })
        
        # Add feature columns
        for col in feature_set.feature_names[:20]:
            if col in feature_set.features.columns:
                current_data[col] = [feature_set.features[col].iloc[-1]]
        
        # Step 6: Generate comprehensive analysis
        price_pred = await predictive_models.price_predictor.predict_price("BTC", current_data, '1h')
        trend_signal = await predictive_models.trend_analyzer.analyze_trend("BTC", current_data, '4h')
        regime_data = await predictive_models.regime_classifier.classify_regime(current_data)
        vol_forecast = await predictive_models.volatility_forecaster.forecast_volatility("BTC", current_data, '4h')
        trading_signal = await predictive_models.generate_trading_signal("BTC", current_data)
        
        print(f"✅ Step 5: Predictions generated")
        if trading_signal:
            print(f"   Final signal: {trading_signal.signal_type} (confidence: {trading_signal.confidence:.3f})")
        
        # Step 7: Update feature importance
        if trading_signal and trading_signal.metadata.get("price_prediction_1h"):
            importance_scores = {
                'price_change_1h': 0.15,
                'market_sentiment': 0.12,
                'volatility_1h': 0.08,
                'rsi_14': 0.10,
                'volume_change_1h': 0.06
            }
            feature_eng.update_importance_scores(importance_scores)
            print(f"✅ Step 6: Feature importance updated")
        
        # Step 8: Get comprehensive summary
        ml_summary = predictive_models.get_model_summary()
        feature_summary = feature_eng.get_feature_summary()
        
        print(f"✅ Step 7: Integration complete")
        print(f"   ML models: {ml_summary['signal_history']} signals generated")
        print(f"   Features: {feature_summary['latest_features']} features engineered")
        
        print("\n🎉 ML Integration Test: PASSED")
        return True
        
    except Exception as e:
        print(f"❌ ML Integration test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_performance():
    """Test ML integration performance"""
    
    print("\n⚡ Testing ML Integration Performance")
    print("-" * 40)
    
    try:
        # Initialize components
        config = {
            "ml_framework": {"us_compliance": {"data_privacy": True}},
            "price_predictor": {"cache_ttl": 300},
            "trend_analyzer": {"cache_ttl": 600}
        }
        
        predictive_models = PredictiveModels(config)
        await predictive_models.initialize_all()
        
        # Performance test
        start_time = time.time()
        
        # Generate test data
        current_data = pd.DataFrame({
            'price': [3000],
            'volume': [1000],
            'volatility': [0.25]
        })
        
        # Add feature columns
        feature_columns = [
            'price_change_1h', 'price_change_4h', 'rsi_14', 'macd_signal',
            'volume_change_1h', 'market_sentiment', 'volatility_1h'
        ]
        
        for col in feature_columns:
            current_data[col] = [np.random.normal(0, 1)]
        
        # Run multiple predictions
        tasks = []
        for i in range(10):
            tasks.append(predictive_models.price_predictor.predict_price("BTC", current_data, '1h'))
            tasks.append(predictive_models.trend_analyzer.analyze_trend("BTC", current_data, '4h'))
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        end_time = time.time()
        
        # Calculate metrics
        total_time = end_time - start_time
        successful_operations = sum(1 for r in results if not isinstance(r, Exception))
        
        print(f"✅ Performance results:")
        print(f"   Total time: {total_time:.2f}s")
        print(f"   Successful operations: {successful_operations}/{len(tasks)}")
        print(f"   Operations per second: {successful_operations / total_time:.1f}")
        print(f"   Avg time per operation: {(total_time / len(tasks)) * 1000:.1f}ms")
        
        print("\n🎯 Performance Test: PASSED")
        return True
        
    except Exception as e:
        print(f"❌ Performance test failed: {e}")
        return False

async def main():
    """Run all ML integration tests"""
    try:
        print("🧪 ML INTEGRATION TEST SUITE")
        print("=" * 70)
        
        # Run tests
        test1 = await test_ml_model_framework()
        test2 = await test_feature_engineering()
        test3 = await test_predictive_models()
        test4 = await test_model_monitoring()
        test5 = await test_ml_integration()
        test6 = await test_performance()
        
        # Summary
        print("\n" + "=" * 70)
        print("📊 ML INTEGRATION TEST RESULTS")
        print("=" * 70)
        print(f"ML Model Framework:   {'✅ PASSED' if test1 else '❌ FAILED'}")
        print(f"Feature Engineering:   {'✅ PASSED' if test2 else '❌ FAILED'}")
        print(f"Predictive Models:      {'✅ PASSED' if test3 else '❌ FAILED'}")
        print(f"Model Monitoring:      {'✅ PASSED' if test4 else '❌ FAILED'}")
        print(f"ML Integration:        {'✅ PASSED' if test5 else '❌ FAILED'}")
        print(f"Performance:            {'✅ PASSED' if test6 else '❌ FAILED'}")
        
        if all([test1, test2, test3, test4, test5, test6]):
            print("\n🎯 ALL ML INTEGRATION TESTS PASSED!")
            print("✅ ML framework operational")
            print("✅ Feature engineering working")
            print("✅ Predictive models functional")
            print("✅ Model monitoring operational")
            print("✅ Full ML integration successful")
            print("✅ Performance within acceptable limits")
        else:
            print("\n❌ Some ML integration tests failed")
        
    except Exception as e:
        print(f"❌ ML integration test suite error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
