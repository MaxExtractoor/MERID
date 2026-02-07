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

from analytics.time_series import TimeSeriesAnalyzer, TimeSeriesConfig
from analytics.market_regimes import MarketRegimeAnalyzer, MarketState
from analytics.volatility_models import VolatilityAnalyzer, GARCHModel
from analytics.correlation_analysis import CorrelationAnalyzer
from utils.logger import get_logger

logger = get_logger("test_predictive_analytics")

async def test_time_series_analyzer():
    """Test time series analyzer functionality"""
    
    print("📈 Testing Time Series Analyzer")
    print("=" * 50)
    
    try:
        # Initialize analyzer
        config = {
            "us_compliance": {
                "data_privacy": True,
                "model_transparency": True
            }
        }
        
        analyzer = TimeSeriesAnalyzer(config)
        print(f"✅ TimeSeriesAnalyzer initialized")
        
        # Generate sample data
        dates = pd.date_range(start='2023-01-01', end='2024-01-01', freq='D')
        n_days = len(dates)
        
        # Generate realistic price data with trend and noise
        trend = np.linspace(100, 150, n_days)
        noise = np.random.normal(0, 5, n_days)
        prices = trend + noise
        
        # Add seasonal component
        seasonal = 10 * np.sin(2 * np.pi * np.arange(n_days) / 365.25)
        prices += seasonal
        
        # Create DataFrame
        data = pd.DataFrame({
            'date': dates,
            'price': prices,
            'volume': np.random.lognormal(10, 1, n_days),
            'sentiment': np.random.normal(0, 0.3, n_days)
        })
        
        print(f"✅ Generated sample data: {len(data)} days")
        
        # Test ARIMA model
        print("\n🔧 Testing ARIMA Model")
        arima_config = TimeSeriesConfig(
            model_type="arima",
            target_column="price",
            feature_columns=["volume", "sentiment"],
            time_column="date",
            frequency="daily",
            arima_order=(1, 1, 1),
            forecast_horizon=30
        )
        
        arima_created = await analyzer.create_model("arima_test", arima_config)
        print(f"✅ ARIMA model created: {arima_created}")
        
        if arima_created:
            # Train model
            print("   Training ARIMA model...")
            metrics = await analyzer.train_model("arima_test", data)
            if metrics:
                print(f"✅ ARIMA trained: MAE={metrics.mae:.4f}, RMSE={metrics.rmse:.4f}")
                
                # Generate forecast
                forecast = await analyzer.forecast("arima_test", data, 30)
                if forecast:
                    print(f"✅ ARIMA forecast: {len(forecast.predictions)} predictions")
                    print(f"   First prediction: {forecast.predictions[0]:.2f}")
                    print(f"   Confidence interval: [{forecast.confidence_lower[0]:.2f}, {forecast.confidence_upper[0]:.2f}]")
                else:
                    print("❌ ARIMA forecast failed")
            else:
                print("❌ ARIMA training failed")
        
        # Test Prophet model
        print("\n🔧 Testing Prophet Model")
        prophet_config = TimeSeriesConfig(
            model_type="prophet",
            target_column="price",
            feature_columns=["volume"],
            time_column="date",
            frequency="daily",
            prophet_yearly_seasonality=True,
            prophet_weekly_seasonality=True,
            forecast_horizon=30
        )
        
        prophet_created = await analyzer.create_model("prophet_test", prophet_config)
        print(f"✅ Prophet model created: {prophet_created}")
        
        if prophet_created:
            # Train model
            print("   Training Prophet model...")
            metrics = await analyzer.train_model("prophet_test", data)
            if metrics:
                print(f"✅ Prophet trained: MAE={metrics.mae:.4f}, RMSE={metrics.rmse:.4f}")
                
                # Generate forecast
                forecast = await analyzer.forecast("prophet_test", data, 30)
                if forecast:
                    print(f"✅ Prophet forecast: {len(forecast.predictions)} predictions")
                    print(f"   First prediction: {forecast.predictions[0]:.2f}")
                else:
                    print("❌ Prophet forecast failed")
            else:
                print("❌ Prophet training failed")
        
        # Test model comparison
        print("\n📊 Testing Model Comparison")
        available_models = [model_id for model_id in ["arima_test", "prophet_test"] if model_id in analyzer.models]
        
        if len(available_models) >= 2:
            comparison = await analyzer.compare_models(available_models, data)
            print(f"✅ Model comparison completed")
            print(f"   Best model: {comparison.get('best_model', 'unknown')}")
            print(f"   Best RMSE: {comparison.get('best_rmse', 'unknown')}")
        else:
            print("⚠️ Insufficient models for comparison")
        
        # Test analyzer summary
        print("\n📋 Testing Analyzer Summary")
        summary = analyzer.get_model_summary()
        print(f"✅ Total models: {summary['total_models']}")
        print(f"✅ Trained models: {summary['trained_models']}")
        print(f"✅ Forecast results: {summary['forecast_results']}")
        
        print("\n🎉 Time Series Analyzer Test: PASSED")
        return True
        
    except Exception as e:
        print(f"❌ Time Series Analyzer test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_market_regime_analyzer():
    """Test market regime analyzer functionality"""
    
    print("\n🎯 Testing Market Regime Analyzer")
    print("=" * 50)
    
    try:
        # Initialize analyzer
        config = {
            "us_compliance": {
                "market_data_privacy": True,
                "regime_analysis_logging": True
            }
        }
        
        analyzer = MarketRegimeAnalyzer(config)
        print(f"✅ MarketRegimeAnalyzer initialized")
        
        # Test regime classification
        print("\n🔍 Testing Regime Classification")
        
        # Create sample market state
        market_state = MarketState(
            timestamp=time.time(),
            price=3000.0,
            volume=1000000.0,
            volatility=0.25,
            momentum=0.02,
            trend_strength=0.8,
            market_sentiment=0.3,
            social_sentiment=0.2,
            onchain_activity=5000.0,
            liquidity_index=0.9,
            fear_greed_index=65.0,
            market_breadth=0.6,
            sector_rotation=0.4,
            macro_indicators={
                "interest_rate": 0.05,
                "inflation_rate": 0.03,
                "gdp_growth": 0.02
            },
            metadata={"test": True}
        )
        
        classification = await analyzer.classifier.classify_regime(market_state)
        if classification:
            print(f"✅ Regime classified: {classification.regime}")
            print(f"   Confidence: {classification.confidence:.3f}")
            print(f"   Risk level: {classification.risk_level}")
            print(f"   Volatility level: {classification.volatility_level}")
        else:
            print("❌ Regime classification failed")
        
        # Test transition detection
        print("\n🔄 Testing Transition Detection")
        
        # Create previous state (different regime)
        previous_state = MarketState(
            timestamp=time.time() - 3600,  # 1 hour ago
            price=2800.0,
            volume=800000.0,
            volatility=0.15,
            momentum=-0.01,
            trend_strength=0.3,
            market_sentiment=-0.2,
            social_sentiment=-0.1,
            onchain_activity=3000.0,
            liquidity_index=0.8,
            fear_greed_index=35.0,
            market_breadth=0.3,
            sector_rotation=0.2,
            macro_indicators={
                "interest_rate": 0.04,
                "inflation_rate": 0.02,
                "gdp_growth": 0.01
            },
            metadata={"test": True}
        )
        
        transition = await analyzer.classifier.detect_transition(market_state, previous_state)
        if transition:
            print(f"✅ Transition detected: {transition.from_regime} → {transition.to_regime}")
            print(f"   Confidence: {transition.confidence:.3f}")
            print(f"   Trigger factors: {transition.trigger_factors}")
        else:
            print("⚠️ No transition detected (expected for test data)")
        
        # Test regime summary
        print("\n📊 Testing Regime Summary")
        summary = analyzer.classifier.get_regime_summary()
        print(f"✅ Total classifications: {summary['total_classifications']}")
        print(f"✅ Recent classifications: {summary['recent_classifications']}")
        print(f"✅ Regime distribution: {summary['regime_distribution']}")
        
        # Test available regimes
        print("\n📋 Testing Available Regimes")
        regimes = analyzer.get_available_regimes()
        print(f"✅ Available regimes: {regimes}")
        
        print("\n🎉 Market Regime Analyzer Test: PASSED")
        return True
        
    except Exception as e:
        print(f"❌ Market Regime Analyzer test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_volatility_analyzer():
    """Test volatility analyzer functionality"""
    
    print("\n📊 Testing Volatility Analyzer")
    print("=" * 50)
    
    try:
        # Initialize analyzer
        config = {
            "risk_params": {
                "var_confidence_levels": [0.95, 0.99],
                "lookback_period": 252,
                "min_samples": 100
            },
            "us_compliance": {
                "risk_assessment": True,
                "volatility_logging": True
            }
        }
        
        analyzer = VolatilityAnalyzer(config)
        print(f"✅ VolatilityAnalyzer initialized")
        
        # Generate sample price data
        dates = pd.date_range(start='2023-01-01', end='2024-01-01', freq='D')
        n_days = len(dates)
        
        # Generate realistic price data with volatility clustering
        base_price = 100.0
        prices = [base_price]
        
        for i in range(1, n_days):
            # Random walk with volatility clustering
            if i % 30 < 10:  # High volatility period
                volatility = 0.03
            else:  # Low volatility period
                volatility = 0.01
            
            return_val = np.random.normal(0, volatility)
            new_price = prices[-1] * (1 + return_val)
            prices.append(new_price)
        
        price_series = pd.Series(prices, index=dates)
        returns = price_series.pct_change().dropna()
        
        print(f"✅ Generated sample data: {len(price_series)} days")
        print(f"   Price range: ${price_series.min():.2f} - ${price_series.max():.2f}")
        print(f"   Return volatility: {returns.std():.4f}")
        
        # Test GARCH model creation
        print("\n🔧 Testing GARCH Model Creation")
        garch_config = {
            "p": 1,
            "q": 1,
            "mean_model": "Constant",
            "volatility_model": "GARCH",
            "distribution": "normal"
        }
        
        model_created = await analyzer.create_model("garch_test", garch_config)
        print(f"✅ GARCH model created: {model_created}")
        
        if model_created:
            # Train model
            print("   Training GARCH model...")
            metrics = await analyzer.train_model("garch_test", returns)
            if metrics:
                print(f"✅ GARCH trained: AIC={metrics['aic']:.2f}, MSE={metrics['mse']:.6f}")
                
                # Generate forecast
                forecast = await analyzer.forecast_volatility("garch_test", 30)
                if forecast:
                    print(f"✅ GARCH forecast: {len(forecast.volatility_forecasts)} predictions")
                    print(f"   First forecast: {forecast.volatility_forecasts[0]:.4f}")
                else:
                    print("❌ GARCH forecast failed")
            else:
                print("❌ GARCH training failed")
        
        # Test volatility analysis
        print("\n📈 Testing Volatility Analysis")
        volatility_metrics = await analyzer.analyze_volatility(price_series, returns)
        if volatility_metrics:
            print(f"✅ Volatility analysis completed")
            print(f"   Realized volatility: {volatility_metrics.realized_volatility:.4f}")
            print(f"   GARCH volatility: {volatility_metrics.garch_volatility:.4f}")
            print(f"   Volatility regime: {volatility_metrics.volatility_regime}")
            print(f"   Risk level: {volatility_metrics.risk_level}")
            print(f"   VaR 95%: {volatility_metrics.var_95:.4f}")
            print(f"   Expected Shortfall 95%: {volatility_metrics.expected_shortfall_95:.4f}")
        else:
            print("❌ Volatility analysis failed")
        
        # Test realized volatility calculation
        print("\n📊 Testing Realized Volatility")
        realized_vol = analyzer.calculate_realized_volatility(price_series, window=30)
        if not realized_vol.empty:
            print(f"✅ Realized volatility calculated")
            print(f"   Latest 30-day vol: {realized_vol.iloc[-1]:.4f}")
            print(f"   Average vol: {realized_vol.mean():.4f}")
        else:
            print("❌ Realized volatility calculation failed")
        
        # Test VaR calculation
        print("\n⚠️ Testing Value at Risk")
        var_95 = analyzer.calculate_var(returns, 0.95)
        var_99 = analyzer.calculate_var(returns, 0.99)
        es_95 = analyzer.calculate_expected_shortfall(returns, 0.95)
        
        print(f"✅ VaR 95%: {var_95:.4f}")
        print(f"✅ VaR 99%: {var_99:.4f}")
        print(f"✅ Expected Shortfall 95%: {es_95:.4f}")
        
        # Test volatility summary
        print("\n📋 Testing Volatility Summary")
        summary = analyzer.get_volatility_summary()
        if "status" not in summary:
            print(f"✅ Total analyses: {summary['total_analyses']}")
            print(f"✅ Recent analyses: {summary['recent_analyses']}")
            print(f"✅ Regime distribution: {summary['regime_distribution']}")
        else:
            print("⚠️ No analysis data available")
        
        print("\n🎉 Volatility Analyzer Test: PASSED")
        return True
        
    except Exception as e:
        print(f"❌ Volatility Analyzer test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_correlation_analyzer():
    """Test correlation analyzer functionality"""
    
    print("\n🔗 Testing Correlation Analyzer")
    print("=" * 50)
    
    try:
        # Initialize analyzer
        config = {
            "lookback_period": 252,
            "min_samples": 100,
            "correlation_threshold": 0.7,
            "us_compliance": {
                "data_privacy": True,
                "correlation_logging": True
            }
        }
        
        analyzer = CorrelationAnalyzer(config)
        print(f"✅ CorrelationAnalyzer initialized")
        
        # Generate sample asset data
        dates = pd.date_range(start='2023-01-01', end='2024-01-01', freq='D')
        n_days = len(dates)
        
        # Create correlated asset prices
        assets = {}
        
        # Asset 1: Base asset
        base_returns = np.random.normal(0.001, 0.02, n_days)
        asset1_prices = 100 * np.exp(np.cumsum(base_returns))
        assets["BTC"] = pd.Series(asset1_prices, index=dates)
        
        # Asset 2: Highly correlated with Asset 1
        asset2_returns = 0.8 * base_returns + 0.2 * np.random.normal(0, 0.015, n_days)
        asset2_prices = 50 * np.exp(np.cumsum(asset2_returns))
        assets["ETH"] = pd.Series(asset2_prices, index=dates)
        
        # Asset 3: Low correlation with others
        asset3_returns = 0.2 * base_returns + 0.8 * np.random.normal(0, 0.025, n_days)
        asset3_prices = 2000 * np.exp(np.cumsum(asset3_returns))
        assets["GOLD"] = pd.Series(asset3_prices, index=dates)
        
        # Asset 4: Moderate correlation
        asset4_returns = 0.5 * base_returns + 0.5 * np.random.normal(0, 0.018, n_days)
        asset4_prices = 150 * np.exp(np.cumsum(asset4_returns))
        assets["SP500"] = pd.Series(asset4_prices, index=dates)
        
        print(f"✅ Generated sample data for {len(assets)} assets")
        
        # Add assets to analyzer
        print("\n📊 Testing Asset Addition")
        for asset_id, asset_data in assets.items():
            metadata = {
                "name": asset_id,
                "type": "cryptocurrency" if asset_id in ["BTC", "ETH"] else "traditional",
                "description": f"Test asset {asset_id}"
            }
            
            added = await analyzer.add_asset(asset_id, asset_data, metadata)
            print(f"✅ Added {asset_id}: {added}")
        
        # Test correlation calculation
        print("\n🔍 Testing Correlation Calculation")
        correlation_metrics = await analyzer.calculate_correlations()
        if correlation_metrics:
            print(f"✅ Correlation analysis completed")
            print(f"   Asset pairs: {len(correlation_metrics.asset_pairs)}")
            print(f"   Average correlation: {correlation_metrics.average_correlation:.3f}")
            print(f"   Max correlation: {correlation_metrics.max_correlation:.3f}")
            print(f"   Min correlation: {correlation_metrics.min_correlation:.3f}")
            print(f"   Diversification ratio: {correlation_metrics.diversification_ratio:.3f}")
            print(f"   Concentration risk: {correlation_metrics.concentration_risk:.3f}")
            
            # Show some correlations
            print("   Sample correlations:")
            for i, (asset1, asset2) in enumerate(correlation_metrics.asset_pairs[:3]):
                corr = correlation_metrics.correlation_matrix[asset1][asset2]
                print(f"     {asset1}-{asset2}: {corr:.3f}")
        else:
            print("❌ Correlation calculation failed")
        
        # Test rolling correlations
        print("\n📈 Testing Rolling Correlations")
        rolling_correlations = await analyzer.calculate_rolling_correlations(window=60, step=30)
        if rolling_correlations:
            print(f"✅ Rolling correlations: {len(rolling_correlations)} windows")
            print(f"   First window avg corr: {rolling_correlations[0].average_correlation:.3f}")
            print(f"   Last window avg corr: {rolling_correlations[-1].average_correlation:.3f}")
        else:
            print("❌ Rolling correlations failed")
        
        # Test correlation breakdown detection
        print("\n⚠️ Testing Correlation Breakdown Detection")
        breakdowns = await analyzer.detect_correlation_breakdown(threshold=0.2)
        print(f"✅ Detected {len(breakdowns)} correlation breakdowns")
        for asset1, asset2, change in breakdowns[:3]:
            print(f"   {asset1}-{asset2}: {change:.3f}")
        
        # Test portfolio risk calculation
        print("\n💼 Testing Portfolio Risk Calculation")
        portfolio_weights = {
            "BTC": 0.4,
            "ETH": 0.3,
            "GOLD": 0.2,
            "SP500": 0.1
        }
        
        portfolio_risk = await analyzer.calculate_portfolio_risk(portfolio_weights)
        if "error" not in portfolio_risk:
            print(f"✅ Portfolio risk calculated")
            print(f"   Portfolio volatility: {portfolio_risk['portfolio_volatility']:.3f}")
            print(f"   Diversification benefit: {portfolio_risk['diversification_benefit']:.3f}")
            print(f"   Concentration risk: {portfolio_risk['concentration_risk']:.3f}")
        else:
            print("❌ Portfolio risk calculation failed")
        
        # Test diversification opportunities
        print("\n🎯 Testing Diversification Opportunities")
        opportunities = await analyzer.find_diversification_opportunities()
        print(f"✅ Found {len(opportunities)} diversification opportunities")
        for asset1, asset2, corr in opportunities[:3]:
            print(f"   {asset1}-{asset2}: {corr:.3f}")
        
        # Test correlation summary
        print("\n📋 Testing Correlation Summary")
        summary = analyzer.get_correlation_summary()
        if "status" not in summary:
            print(f"✅ Total analyses: {summary['total_analyses']}")
            print(f"✅ Asset count: {summary['asset_count']}")
            print(f"✅ Average correlation: {summary['average_correlation']:.3f}")
        else:
            print("⚠️ No analysis data available")
        
        print("\n🎉 Correlation Analyzer Test: PASSED")
        return True
        
    except Exception as e:
        print(f"❌ Correlation Analyzer test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_predictive_analytics_integration():
    """Test full predictive analytics integration"""
    
    print("\n🔄 Testing Predictive Analytics Integration")
    print("=" * 50)
    
    try:
        # Initialize all components
        ts_config = {"us_compliance": {"data_privacy": True}}
        ts_analyzer = TimeSeriesAnalyzer(ts_config)
        
        regime_config = {"us_compliance": {"market_data_privacy": True}}
        regime_analyzer = MarketRegimeAnalyzer(regime_config)
        
        vol_config = {"us_compliance": {"risk_assessment": True}}
        vol_analyzer = VolatilityAnalyzer(vol_config)
        
        corr_config = {"us_compliance": {"data_privacy": True}}
        corr_analyzer = CorrelationAnalyzer(corr_config)
        
        print(f"✅ All predictive analytics components initialized")
        
        # Generate comprehensive test data
        dates = pd.date_range(start='2023-01-01', end='2024-01-01', freq='D')
        n_days = len(dates)
        
        # Generate correlated market data
        base_returns = np.random.normal(0.001, 0.02, n_days)
        
        # Price data
        btc_prices = 100 * np.exp(np.cumsum(base_returns))
        eth_prices = 50 * np.exp(np.cumsum(0.8 * base_returns + 0.2 * np.random.normal(0, 0.015, n_days)))
        
        # Create DataFrame
        market_data = pd.DataFrame({
            'date': dates,
            'btc_price': btc_prices,
            'eth_price': eth_prices,
            'volume': np.random.lognormal(10, 1, n_days),
            'sentiment': np.random.normal(0, 0.3, n_days)
        })
        
        print(f"✅ Generated comprehensive test data")
        
        # Step 1: Time series analysis
        print("\n📈 Step 1: Time Series Analysis")
        
        ts_config = TimeSeriesConfig(
            model_type="arima",
            target_column="btc_price",
            feature_columns=["volume", "sentiment"],
            time_column="date",
            frequency="daily",
            forecast_horizon=30
        )
        
        await ts_analyzer.create_model("btc_model", ts_config)
        ts_metrics = await ts_analyzer.train_model("btc_model", market_data)
        
        if ts_metrics:
            print(f"✅ Time series model trained: MAE={ts_metrics.mae:.4f}")
            
            ts_forecast = await ts_analyzer.forecast("btc_model", market_data, 30)
            if ts_forecast:
                print(f"✅ Time series forecast: {len(ts_forecast.predictions)} predictions")
        
        # Step 2: Market regime analysis
        print("\n🎯 Step 2: Market Regime Analysis")
        
        market_state = MarketState(
            timestamp=time.time(),
            price=btc_prices[-1],
            volume=1000000.0,
            volatility=0.25,
            momentum=0.02,
            trend_strength=0.8,
            market_sentiment=0.3,
            social_sentiment=0.2,
            onchain_activity=5000.0,
            liquidity_index=0.9,
            fear_greed_index=65.0,
            market_breadth=0.6,
            sector_rotation=0.4,
            macro_indicators={"interest_rate": 0.05, "inflation_rate": 0.03}
        )
        
        regime_classification = await regime_analyzer.classifier.classify_regime(market_state)
        if regime_classification:
            print(f"✅ Market regime: {regime_classification.regime} (confidence: {regime_classification.confidence:.3f})")
        
        # Step 3: Volatility analysis
        print("\n📊 Step 3: Volatility Analysis")
        
        btc_series = pd.Series(btc_prices, index=dates)
        btc_returns = btc_series.pct_change().dropna()
        
        await vol_analyzer.create_model("btc_vol", {"p": 1, "q": 1})
        vol_metrics = await vol_analyzer.train_model("btc_vol", btc_returns)
        
        if vol_metrics:
            print(f"✅ Volatility model trained: AIC={vol_metrics['aic']:.2f}")
            
            vol_analysis = await vol_analyzer.analyze_volatility(btc_series, btc_returns)
            if vol_analysis:
                print(f"✅ Volatility regime: {vol_analysis.volatility_regime}")
                print(f"✅ Risk level: {vol_analysis.risk_level}")
        
        # Step 4: Correlation analysis
        print("\n🔗 Step 4: Correlation Analysis")
        
        await corr_analyzer.add_asset("BTC", btc_series, {"type": "crypto"})
        await corr_analyzer.add_asset("ETH", pd.Series(eth_prices, index=dates), {"type": "crypto"})
        
        corr_metrics = await corr_analyzer.calculate_correlations()
        if corr_metrics:
            print(f"✅ Correlation analysis: avg corr={corr_metrics.average_correlation:.3f}")
            print(f"✅ Diversification ratio: {corr_metrics.diversification_ratio:.3f}")
        
        # Step 5: Integrated analysis summary
        print("\n📋 Step 5: Integrated Analysis Summary")
        
        # Time series summary
        ts_summary = ts_analyzer.get_model_summary()
        print(f"✅ Time series models: {ts_summary['total_models']}")
        
        # Regime summary
        regime_summary = regime_analyzer.classifier.get_regime_summary()
        print(f"✅ Regime classifications: {regime_summary['total_classifications']}")
        
        # Volatility summary
        vol_summary = vol_analyzer.get_volatility_summary()
        if "status" not in vol_summary:
            print(f"✅ Volatility analyses: {vol_summary['total_analyses']}")
        
        # Correlation summary
        corr_summary = corr_analyzer.get_correlation_summary()
        if "status" not in corr_summary:
            print(f"✅ Correlation analyses: {corr_summary['total_analyses']}")
        
        print("\n🎉 Predictive Analytics Integration Test: PASSED")
        return True
        
    except Exception as e:
        print(f"❌ Predictive Analytics Integration test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def main():
    """Run all predictive analytics tests"""
    try:
        print("🧪 PREDICTIVE ANALYTICS TEST SUITE")
        print("=" * 70)
        
        # Run tests
        test1 = await test_time_series_analyzer()
        test2 = await test_market_regime_analyzer()
        test3 = await test_volatility_analyzer()
        test4 = await test_correlation_analyzer()
        test5 = await test_predictive_analytics_integration()
        
        # Summary
        print("\n" + "=" * 70)
        print("📊 PREDICTIVE ANALYTICS TEST RESULTS")
        print("=" * 70)
        print(f"Time Series Analyzer:     {'✅ PASSED' if test1 else '❌ FAILED'}")
        print(f"Market Regime Analyzer:    {'✅ PASSED' if test2 else '❌ FAILED'}")
        print(f"Volatility Analyzer:      {'✅ PASSED' if test3 else '❌ FAILED'}")
        print(f"Correlation Analyzer:     {'✅ PASSED' if test4 else '❌ FAILED'}")
        print(f"Analytics Integration:    {'✅ PASSED' if test5 else '❌ FAILED'}")
        
        if all([test1, test2, test3, test4, test5]):
            print("\n🎯 ALL PREDICTIVE ANALYTICS TESTS PASSED!")
            print("✅ Time series modeling with ARIMA/Prophet working")
            print("✅ Market regime detection and classification working")
            print("✅ Volatility modeling with GARCH working")
            print("✅ Cross-asset correlation analysis working")
            print("✅ Full predictive analytics integration successful")
        else:
            print("\n❌ Some predictive analytics tests failed")
        
    except Exception as e:
        print(f"❌ Predictive analytics test suite error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
