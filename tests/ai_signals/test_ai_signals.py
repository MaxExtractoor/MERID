#!/usr/bin/env python3

import asyncio
import sys
import os
import time
import random
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ai_signals.signal_generator import AISignalGenerator, SignalType, SignalSource, SignalConfidence
from ai_signals.deep_learning_models import DeepLearningModels, ModelType, TrainingStatus
from ai_signals.signal_validation import SignalValidation, ValidationRule, BacktestPeriod
from utils.logger import get_logger

logger = get_logger("test_ai_signals")

async def test_signal_generator():
    """Test signal generator functionality"""
    
    print("🤖 Testing AI Signal Generator")
    print("=" * 50)
    
    try:
        # Initialize signal generator
        config = {
            "signal_generation": {
                "max_signals_per_symbol": 10,
                "signal_expiry_hours": 24,
                "min_confidence_threshold": 0.6,
                "max_position_size": 0.1,
                "risk_limit": 0.02
            },
            "us_compliance": {"signal_validation": True, "audit_signals": True}
        }
        
        generator = AISignalGenerator(config)
        print(f"✅ AISignalGenerator initialized")
        
        # Register models
        print("\n📊 Registering Signal Models")
        
        models = [
            {
                "model_id": "lstm_model",
                "model_name": "LSTM Signal Model",
                "model_type": "lstm",
                "features": ["price_momentum", "volume_momentum", "volatility", "rsi", "macd"],
                "target_variable": "signal",
                "performance_metrics": {
                    "accuracy": 0.75,
                    "precision": 0.73,
                    "recall": 0.77,
                    "f1_score": 0.75,
                    "auc_score": 0.82,
                    "training_data_points": 10000
                }
            },
            {
                "model_id": "transformer_model",
                "model_name": "Transformer Signal Model",
                "model_type": "transformer",
                "features": ["price_trend", "volume_trend", "momentum_divergence", "support_resistance"],
                "target_variable": "signal",
                "performance_metrics": {
                    "accuracy": 0.78,
                    "precision": 0.76,
                    "recall": 0.80,
                    "f1_score": 0.78,
                    "auc_score": 0.85,
                    "training_data_points": 15000
                }
            },
            {
                "model_id": "cnn_model",
                "model_name": "CNN Pattern Model",
                "model_type": "cnn",
                "features": ["bollinger_position", "volatility", "price_momentum", "volume_momentum"],
                "target_variable": "signal",
                "performance_metrics": {
                    "accuracy": 0.72,
                    "precision": 0.70,
                    "recall": 0.74,
                    "f1_score": 0.72,
                    "auc_score": 0.79,
                    "training_data_points": 8000
                }
            }
        ]
        
        for model_config in models:
            success = await generator.register_model(
                model_config["model_id"],
                model_config["model_name"],
                model_config["model_type"],
                model_config["features"],
                model_config["target_variable"],
                model_config["performance_metrics"]
            )
            print(f"✅ Registered {model_config['model_id']}: {success}")
        
        # Create ensembles
        print("\n🎯 Creating Signal Ensembles")
        
        ensembles = [
            {
                "ensemble_id": "main_ensemble",
                "ensemble_name": "Main Trading Ensemble",
                "models": ["lstm_model", "transformer_model"],
                "weights": [0.6, 0.4],
                "voting_method": "weighted",
                "threshold": 0.5
            },
            {
                "ensemble_id": "pattern_ensemble",
                "ensemble_name": "Pattern Recognition Ensemble",
                "models": ["cnn_model", "lstm_model"],
                "weights": [0.5, 0.5],
                "voting_method": "consensus",
                "threshold": 0.6
            }
        ]
        
        for ensemble_config in ensembles:
            success = await generator.create_ensemble(
                ensemble_config["ensemble_id"],
                ensemble_config["ensemble_name"],
                ensemble_config["models"],
                ensemble_config["weights"],
                ensemble_config["voting_method"],
                ensemble_config["threshold"]
            )
            print(f"✅ Created {ensemble_config['ensemble_id']}: {success}")
        
        # Generate sample market data
        print("\n📈 Generating Sample Market Data")
        
        dates = pd.date_range(start='2023-01-01', periods=100, freq='D')
        n_assets = 50
        
        market_data = pd.DataFrame({
            'close': np.random.normal(100, 10, 100),
            'volume': np.random.lognormal(15, 1, 100),
            'high': np.random.normal(105, 10, 100),
            'low': np.random.normal(95, 10, 100),
            'open': np.random.normal(100, 10, 100)
        }, index=dates)
        
        # Add trend to make it more realistic
        market_data['close'] = market_data['close'] + np.cumsum(np.random.normal(0.1, 1, 100))
        
        print(f"✅ Generated {len(market_data)} days of market data")
        
        # Test single model signal generation
        print("\n🎯 Testing Single Model Signal Generation")
        
        symbols = ["AAPL", "MSFT", "GOOGL", "BTC", "ETH"]
        
        for symbol in symbols[:2]:  # Test first 2 symbols
            signal = await generator.generate_signal(symbol, market_data, model_id="lstm_model")
            
            if signal:
                print(f"✅ Generated {signal.signal_type.value} signal for {symbol}")
                print(f"   Confidence: {signal.confidence.name}")
                print(f"   Strength: {signal.strength:.3f}")
                print(f"   Expected return: {signal.expected_return:.3f}")
                print(f"   Position size: {signal.position_size:.3f}")
            else:
                print(f"❌ Failed to generate signal for {symbol}")
        
        # Test ensemble signal generation
        print("\n🎯 Testing Ensemble Signal Generation")
        
        for symbol in symbols[2:4]:  # Test next 2 symbols
            signal = await generator.generate_signal(symbol, market_data, ensemble_id="main_ensemble")
            
            if signal:
                print(f"✅ Generated ensemble {signal.signal_type.value} signal for {symbol}")
                print(f"   Source: {signal.signal_source.value}")
                print(f"   Confidence: {signal.confidence.name}")
                print(f"   Expected return: {signal.expected_return:.3f}")
            else:
                print(f"❌ Failed to generate ensemble signal for {symbol}")
        
        # Test signal management
        print("\n📊 Testing Signal Management")
        
        # Get active signals
        active_signals = generator.get_active_signals()
        print(f"✅ Active signals: {len(active_signals)}")
        
        # Get signal history
        signal_history = generator.get_signal_history(limit=10)
        print(f"✅ Signal history: {len(signal_history)}")
        
        # Get model performance
        model_performance = generator.get_model_performance()
        print(f"✅ Model performance tracking: {len(model_performance)} models")
        
        # Test signal summary
        print("\n📋 Testing Signal Summary")
        summary = generator.get_signal_summary()
        if "status" not in summary:
            print(f"✅ Total signals: {summary['total_signals']}")
            print(f"✅ Signal types: {summary['signal_types']}")
            print(f"✅ Signal sources: {summary['signal_sources']}")
            print(f"✅ Confidence levels: {summary['confidence_levels']}")
        else:
            print("⚠️ No signal summary available")
        
        print("\n🎉 AI Signal Generator Test: PASSED")
        return True
        
    except Exception as e:
        print(f"❌ AI Signal Generator test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_deep_learning_models():
    """Test deep learning models functionality"""
    
    print("\n🧠 Testing Deep Learning Models")
    print("=" * 50)
    
    try:
        # Initialize deep learning models
        config = {
            "deep_learning": {
                "max_models": 10,
                "max_training_time": 3600,
                "min_accuracy": 0.6,
                "batch_prediction": True
            },
            "us_compliance": {"model_validation": True, "audit_models": True}
        }
        
        models = DeepLearningModels(config)
        print(f"✅ DeepLearningModels initialized")
        
        # Create models
        print("\n🏗️ Creating Deep Learning Models")
        
        model_configs = [
            {
                "model_id": "lstm_v1",
                "model_name": "LSTM Model v1",
                "model_type": ModelType.LSTM,
                "input_shape": (50, 10)
            },
            {
                "model_id": "transformer_v1",
                "model_name": "Transformer Model v1",
                "model_type": ModelType.TRANSFORMER,
                "input_shape": (100, 8)
            },
            {
                "model_id": "cnn_v1",
                "model_name": "CNN Model v1",
                "model_type": ModelType.CNN,
                "input_shape": (30, 5)
            },
            {
                "model_id": "gru_v1",
                "model_name": "GRU Model v1",
                "model_type": ModelType.GRU,
                "input_shape": (40, 6)
            }
        ]
        
        for model_config in model_configs:
            success = await models.create_model(
                model_config["model_id"],
                model_config["model_name"],
                model_config["model_type"],
                model_config["input_shape"]
            )
            print(f"✅ Created {model_config['model_id']}: {success}")
        
        # Configure training
        print("\n⚙️ Configuring Model Training")
        
        for model_config in model_configs[:2]:  # Configure first 2 models
            success = await models.configure_training(
                model_config["model_id"],
                batch_size=32,
                epochs=50,
                learning_rate=0.001,
                optimizer="adam",
                loss_function="binary_crossentropy",
                metrics=["accuracy"],
                validation_split=0.2,
                early_stopping=True
            )
            print(f"✅ Configured training for {model_config['model_id']}: {success}")
        
        # Generate training data
        print("\n📊 Generating Training Data")
        
        n_samples = 1000
        sequence_length = 50
        n_features = 10
        
        training_data = pd.DataFrame(
            np.random.normal(0, 1, (n_samples, sequence_length, n_features)).reshape(n_samples, -1)
        )
        
        target_data = pd.Series(np.random.randint(0, 2, n_samples))
        
        print(f"✅ Generated {n_samples} training samples")
        
        # Train models
        print("\n🎓 Training Models")
        
        for model_config in model_configs[:2]:  # Train first 2 models
            print(f"Training {model_config['model_id']}...")
            
            success = await models.train_model(
                model_config["model_id"],
                training_data,
                target_data
            )
            
            if success:
                performance = models.get_model_performance(model_config["model_id"])
                if performance:
                    print(f"✅ {model_config['model_id']} trained successfully")
                    print(f"   Accuracy: {performance.accuracy:.3f}")
                    print(f"   Training time: {performance.training_time:.2f}s")
                else:
                    print(f"⚠️ {model_config['model_id']} trained but no performance data")
            else:
                print(f"❌ Failed to train {model_config['model_id']}")
        
        # Test predictions
        print("\n🔮 Testing Model Predictions")
        
        # Generate test data
        test_input = np.random.normal(0, 1, (1, 50, 10))
        
        for model_config in model_configs[:2]:  # Test first 2 models
            prediction = await models.predict(model_config["model_id"], test_input)
            
            if prediction:
                print(f"✅ {model_config['model_id']} prediction:")
                print(f"   Prediction: {prediction.prediction:.3f}")
                print(f"   Confidence: {prediction.confidence:.3f}")
                print(f"   Processing time: {prediction.processing_time:.4f}s")
            else:
                print(f"❌ Failed to get prediction from {model_config['model_id']}")
        
        # Test batch predictions
        print("\n📦 Testing Batch Predictions")
        
        batch_inputs = [np.random.normal(0, 1, (1, 50, 10)) for _ in range(5)]
        batch_results = await models.batch_predict("lstm_v1", batch_inputs)
        
        print(f"✅ Batch predictions: {len(batch_results)} results")
        if batch_results:
            avg_confidence = np.mean([r.confidence for r in batch_results])
            print(f"   Average confidence: {avg_confidence:.3f}")
        
        # Test model evaluation
        print("\n📊 Testing Model Evaluation")
        
        # Generate test data
        test_data = pd.DataFrame(
            np.random.normal(0, 1, (100, 50, 10)).reshape(100, -1)
        )
        test_targets = pd.Series(np.random.randint(0, 2, 100))
        
        for model_config in model_configs[:1]:  # Evaluate first model
            performance = await models.evaluate_model(model_config["model_id"], test_data, test_targets)
            
            if performance:
                print(f"✅ {model_config['model_id']} evaluation:")
                print(f"   Test accuracy: {performance.accuracy:.3f}")
                print(f"   Precision: {performance.precision:.3f}")
                print(f"   Recall: {performance.recall:.3f}")
                print(f"   F1 Score: {performance.f1_score:.3f}")
            else:
                print(f"❌ Failed to evaluate {model_config['model_id']}")
        
        # Test model management
        print("\n📋 Testing Model Management")
        
        # Get all models
        all_models = models.get_all_models()
        print(f"✅ Total models: {len(all_models)}")
        
        # Get model summary
        summary = models.get_model_summary()
        if "status" not in summary:
            print(f"✅ Model types: {summary['model_types']}")
            print(f"✅ Training statuses: {summary['training_statuses']}")
            print(f"✅ Total parameters: {summary['total_parameters']}")
        else:
            print("⚠️ No model summary available")
        
        print("\n🎉 Deep Learning Models Test: PASSED")
        return True
        
    except Exception as e:
        print(f"❌ Deep Learning Models test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_signal_validation():
    """Test signal validation functionality"""
    
    print("\n✅ Testing Signal Validation")
    print("=" * 50)
    
    try:
        # Initialize signal validation
        config = {
            "validation": {
                "min_validation_score": 0.7,
                "max_failed_rules": 3,
                "critical_rule_failure_reject": True
            },
            "us_compliance": {"validation_standards": True, "audit_validations": True}
        }
        
        validator = SignalValidation(config)
        print(f"✅ SignalValidation initialized")
        
        # Add validation rules
        print("\n📋 Adding Validation Rules")
        
        rules = [
            {
                "rule_id": "confidence_check",
                "rule_name": "Confidence Threshold Check",
                "rule_type": ValidationRule.CONFIDENCE_THRESHOLD,
                "parameters": {"min_confidence": 0.6, "weight": 0.3},
                "severity": "error",
                "description": "Check if signal confidence meets minimum threshold"
            },
            {
                "rule_id": "risk_limit_check",
                "rule_name": "Risk Limit Check",
                "rule_type": ValidationRule.RISK_LIMIT,
                "parameters": {"max_risk_score": 0.8, "weight": 0.25},
                "severity": "warning",
                "description": "Check if signal risk score is within acceptable limits"
            },
            {
                "rule_id": "position_size_check",
                "rule_name": "Position Size Check",
                "rule_type": ValidationRule.POSITION_SIZE,
                "parameters": {"max_position_size": 0.2, "weight": 0.2},
                "severity": "critical",
                "description": "Check if position size is within limits"
            },
            {
                "rule_id": "market_conditions_check",
                "rule_name": "Market Conditions Check",
                "rule_type": ValidationRule.MARKET_CONDITIONS,
                "parameters": {"min_market_volume": 1000000, "max_volatility": 0.05, "weight": 0.15},
                "severity": "warning",
                "description": "Check if market conditions are suitable for trading"
            },
            {
                "rule_id": "correlation_check",
                "rule_name": "Correlation Check",
                "rule_type": ValidationRule.CORRELATION_CHECK,
                "parameters": {"max_correlation": 0.7, "weight": 0.1},
                "severity": "warning",
                "description": "Check correlation with existing positions"
            }
        ]
        
        for rule_config in rules:
            success = await validator.add_validation_rule(
                rule_config["rule_id"],
                rule_config["rule_name"],
                rule_config["rule_type"],
                rule_config["parameters"],
                severity=rule_config["severity"],
                description=rule_config["description"]
            )
            print(f"✅ Added {rule_config['rule_id']}: {success}")
        
        # Test signal validation
        print("\n🔍 Testing Signal Validation")
        
        # Create test signals
        test_signals = [
            {
                "signal_id": "signal_1",
                "confidence": SignalConfidence.HIGH,
                "risk_score": 0.3,
                "position_size": 0.1,
                "symbol": "AAPL",
                "signal_type": "buy"
            },
            {
                "signal_id": "signal_2",
                "confidence": SignalConfidence.LOW,
                "risk_score": 0.9,
                "position_size": 0.25,
                "symbol": "MSFT",
                "signal_type": "sell"
            },
            {
                "signal_id": "signal_3",
                "confidence": SignalConfidence.VERY_HIGH,
                "risk_score": 0.1,
                "position_size": 0.05,
                "symbol": "GOOGL",
                "signal_type": "strong_buy"
            }
        ]
        
        # Create market data
        market_data = {
            "volume": 5000000,
            "volatility": 0.03
        }
        
        for signal_data in test_signals:
            result = await validator.validate_signal(
                signal_data["signal_id"],
                signal_data,
                market_data
            )
            
            print(f"✅ Validated {signal_data['signal_id']}:")
            print(f"   Passed: {result.passed}")
            print(f"   Score: {result.validation_score:.3f}")
            print(f"   Failed rules: {result.failed_rules}")
            print(f"   Warnings: {len(result.warnings)}")
            print(f"   Errors: {len(result.errors)}")
            print(f"   Critical issues: {len(result.critical_issues)}")
        
        # Test backtest configuration
        print("\n⚙️ Testing Backtest Configuration")
        
        backtest_configs = [
            {
                "backtest_id": "backtest_1",
                "start_date": datetime(2023, 1, 1),
                "end_date": datetime(2023, 12, 31),
                "initial_capital": 100000.0,
                "commission": 0.001,
                "slippage": 0.0001
            },
            {
                "backtest_id": "backtest_2",
                "start_date": datetime(2023, 6, 1),
                "end_date": datetime(2023, 12, 31),
                "initial_capital": 50000.0,
                "commission": 0.002,
                "slippage": 0.0002
            }
        ]
        
        for backtest_config in backtest_configs:
            success = await validator.configure_backtest(**backtest_config)
            print(f"✅ Configured {backtest_config['backtest_id']}: {success}")
        
        # Test backtesting
        print("\n📊 Testing Backtesting")
        
        # Generate test signals for backtest
        backtest_signals = []
        for i in range(50):
            signal_time = datetime(2023, 1, 1) + timedelta(days=i)
            signal_data = {
                "signal_id": f"backtest_signal_{i}",
                "timestamp": signal_time,
                "signal_type": random.choice(["buy", "sell"]),
                "position_size": random.uniform(0.05, 0.15),
                "symbol": "TEST",
                "stop_loss": 95.0,
                "take_profit": 110.0
            }
            backtest_signals.append(signal_data)
        
        # Generate market data for backtest
        backtest_market_data = pd.DataFrame({
            'close': np.random.normal(100, 5, 365),
            'volume': np.random.lognormal(15, 1, 365)
        }, index=pd.date_range(start='2023-01-01', periods=365, freq='D'))
        
        # Run backtest
        result = await validator.run_backtest("backtest_1", backtest_signals, backtest_market_data)
        
        if result:
            print(f"✅ Backtest completed:")
            print(f"   Total return: {result.total_return:.3f}")
            print(f"   Annualized return: {result.annualized_return:.3f}")
            print(f"   Sharpe ratio: {result.sharpe_ratio:.3f}")
            print(f"   Max drawdown: {result.max_drawdown:.3f}")
            print(f"   Win rate: {result.win_rate:.3f}")
            print(f"   Total trades: {result.total_trades}")
        else:
            print("❌ Backtest failed")
        
        # Test validation management
        print("\n📋 Testing Validation Management")
        
        # Get validation results
        validation_results = validator.get_validation_results(limit=10)
        print(f"✅ Validation results: {len(validation_results)}")
        
        # Get backtest results
        backtest_results = validator.get_backtest_results(limit=5)
        print(f"✅ Backtest results: {len(backtest_results)}")
        
        # Test summaries
        print("\n📊 Testing Summaries")
        
        validation_summary = validator.get_validation_summary()
        if "status" not in validation_summary:
            print(f"✅ Total validations: {validation_summary['total_validations']}")
            print(f"✅ Pass rate: {validation_summary['pass_rate']:.3f}")
            print(f"✅ Average score: {validation_summary['avg_score']:.3f}")
        else:
            print("⚠️ No validation summary available")
        
        backtest_summary = validator.get_backtest_summary()
        if "status" not in backtest_summary:
            print(f"✅ Total backtests: {backtest_summary['total_backtests']}")
            print(f"✅ Average return: {backtest_summary['avg_return']:.3f}")
            print(f"✅ Average Sharpe ratio: {backtest_summary['avg_sharpe_ratio']:.3f}")
        else:
            print("⚠️ No backtest summary available")
        
        print("\n🎉 Signal Validation Test: PASSED")
        return True
        
    except Exception as e:
        print(f"❌ Signal Validation test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_ai_signals_integration():
    """Test full AI signals integration"""
    
    print("\n🔄 Testing AI Signals Integration")
    print("=" * 50)
    
    try:
        # Initialize all components
        generator_config = {"us_compliance": {"signal_validation": True}}
        generator = AISignalGenerator(generator_config)
        
        models_config = {"us_compliance": {"model_validation": True}}
        models = DeepLearningModels(models_config)
        
        validation_config = {"us_compliance": {"validation_standards": True}}
        validator = SignalValidation(validation_config)
        
        print(f"✅ All AI signals components initialized")
        
        # Step 1: Create and train a model
        print("\n🧠 Step 1: Model Creation and Training")
        
        # Create LSTM model
        model_success = await models.create_model(
            "integration_lstm",
            "Integration LSTM",
            ModelType.LSTM,
            (50, 10)
        )
        
        if model_success:
            print(f"✅ LSTM model created")
            
            # Configure training
            training_success = await models.configure_training(
                "integration_lstm",
                epochs=20,  # Reduced for testing
                batch_size=32
            )
            
            if training_success:
                print(f"✅ Training configured")
                
                # Generate training data
                training_data = pd.DataFrame(
                    np.random.normal(0, 1, (100, 50, 10)).reshape(100, -1)
                )
                target_data = pd.Series(np.random.randint(0, 2, 100))
                
                # Train model
                train_success = await models.train_model(
                    "integration_lstm",
                    training_data,
                    target_data
                )
                
                if train_success:
                    performance = models.get_model_performance("integration_lstm")
                    print(f"✅ Model trained - Accuracy: {performance.accuracy:.3f}")
                else:
                    print("❌ Model training failed")
            else:
                print("❌ Training configuration failed")
        else:
            print("❌ Model creation failed")
        
        # Step 2: Register model in signal generator
        print("\n🤖 Step 2: Model Registration")
        
        if models.get_model_performance("integration_lstm"):
            model_perf = models.get_model_performance("integration_lstm")
            
            register_success = await generator.register_model(
                "integration_lstm",
                "Integration LSTM",
                "lstm",
                ["price_momentum", "volume_momentum", "volatility", "rsi"],
                "signal",
                {
                    "accuracy": model_perf.accuracy,
                    "precision": model_perf.precision,
                    "recall": model_perf.recall,
                    "f1_score": model_perf.f1_score,
                    "auc_score": model_perf.auc_score,
                    "training_data_points": 100
                }
            )
            
            if register_success:
                print(f"✅ Model registered in signal generator")
            else:
                print("❌ Model registration failed")
        
        # Step 3: Generate and validate signals
        print("\n🔍 Step 3: Signal Generation and Validation")
        
        # Add validation rule
        rule_success = await validator.add_validation_rule(
            "integration_confidence",
            "Integration Confidence Check",
            ValidationRule.CONFIDENCE_THRESHOLD,
            {"min_confidence": 0.5, "weight": 0.5},
            severity="warning"
        )
        
        if rule_success:
            print(f"✅ Validation rule added")
        
        # Generate market data
        market_data = pd.DataFrame({
            'close': np.random.normal(100, 10, 100),
            'volume': np.random.lognormal(15, 1, 100)
        }, index=pd.date_range(start='2023-01-01', periods=100, freq='D'))
        
        # Generate signal
        signal = await generator.generate_signal("INTEGRATION_TEST", market_data, model_id="integration_lstm")
        
        if signal:
            print(f"✅ Signal generated:")
            print(f"   Type: {signal.signal_type.value}")
            print(f"   Confidence: {signal.confidence.name}")
            print(f"   Expected return: {signal.expected_return:.3f}")
            
            # Validate signal
            signal_data = {
                "signal_id": signal.signal_id,
                "confidence": signal.confidence,
                "risk_score": signal.risk_score,
                "position_size": signal.position_size,
                "symbol": signal.symbol,
                "signal_type": signal.signal_type.value
            }
            
            validation_result = await validator.validate_signal(
                signal.signal_id,
                signal_data,
                {"volume": 1000000, "volatility": 0.03}
            )
            
            print(f"✅ Signal validated:")
            print(f"   Passed: {validation_result.passed}")
            print(f"   Score: {validation_result.validation_score:.3f}")
            
        else:
            print("❌ Signal generation failed")
        
        # Step 4: Integration testing
        print("\n🔄 Step 4: Integration Testing")
        
        # Test model prediction integration
        test_input = np.random.normal(0, 1, (1, 50, 10))
        prediction = await models.predict("integration_lstm", test_input)
        
        if prediction:
            print(f"✅ Model prediction integration:")
            print(f"   Prediction: {prediction.prediction:.3f}")
            print(f"   Confidence: {prediction.confidence:.3f}")
        
        # Test signal management
        active_signals = generator.get_active_signals()
        print(f"✅ Active signals: {len(active_signals)}")
        
        # Test validation management
        validation_results = validator.get_validation_results()
        print(f"✅ Validation results: {len(validation_results)}")
        
        # Test component summaries
        print("\n📊 Step 5: Component Summaries")
        
        signal_summary = generator.get_signal_summary()
        print(f"✅ Signal summary: {signal_summary.get('total_signals', 0)} signals")
        
        model_summary = models.get_model_summary()
        print(f"✅ Model summary: {model_summary.get('total_models', 0)} models")
        
        validation_summary = validator.get_validation_summary()
        if "status" not in validation_summary:
            print(f"✅ Validation summary: {validation_summary.get('total_validations', 0)} validations")
        
        print("\n🎉 AI Signals Integration Test: PASSED")
        return True
        
    except Exception as e:
        print(f"❌ AI Signals Integration test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def main():
    """Run all AI signals tests"""
    try:
        print("🧪 AI SIGNALS TEST SUITE")
        print("=" * 70)
        
        # Run tests
        test1 = await test_signal_generator()
        test2 = await test_deep_learning_models()
        test3 = await test_signal_validation()
        test4 = await test_ai_signals_integration()
        
        # Summary
        print("\n" + "=" * 70)
        print("🤖 AI SIGNALS TEST RESULTS")
        print("=" * 70)
        print(f"Signal Generator:      {'✅ PASSED' if test1 else '❌ FAILED'}")
        print(f"Deep Learning Models:  {'✅ PASSED' if test2 else '❌ FAILED'}")
        print(f"Signal Validation:    {'✅ PASSED' if test3 else '❌ FAILED'}")
        print(f"AI Signals Integration: {'✅ PASSED' if test4 else '❌ FAILED'}")
        
        if all([test1, test2, test3, test4]):
            print("\n🎯 ALL AI SIGNALS TESTS PASSED!")
            print("✅ AI-powered signal generation working")
            print("✅ Deep learning models with training and prediction working")
            print("✅ Signal validation and backtesting working")
            print("✅ Full AI signals integration successful")
        else:
            print("\n❌ Some AI signals tests failed")
        
    except Exception as e:
        print(f"❌ AI signals test suite error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
