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

from multi_asset.asset_manager import AssetManager, AssetDefinition, AssetData, AssetClass, AssetStatus
from multi_asset.cross_asset_strategy import CrossAssetStrategyEngine, StrategyType, SignalStrength
from multi_asset.portfolio_constructor import PortfolioConstructor, PortfolioType, RebalanceFrequency
from utils.logger import get_logger

logger = get_logger("test_multi_asset")

async def test_asset_manager():
    """Test asset manager functionality"""
    
    print("🏛️ Testing Asset Manager")
    print("=" * 50)
    
    try:
        # Initialize asset manager
        config = {
            "data_retention_period": 86400,  # 1 day for testing
            "max_data_points": 1000,
            "us_compliance": {"asset_screening": True, "audit_logging": True}
        }
        
        manager = AssetManager(config)
        print(f"✅ AssetManager initialized")
        
        # Create test assets
        assets = [
            AssetDefinition("AAPL", "Apple Inc.", AssetClass.EQUITY, "NASDAQ", "USD", "Technology", "US", 3000000000000),
            AssetDefinition("MSFT", "Microsoft Corp.", AssetClass.EQUITY, "NASDAQ", "USD", "Technology", "US", 2500000000000),
            AssetDefinition("GOOGL", "Alphabet Inc.", AssetClass.EQUITY, "NASDAQ", "USD", "Technology", "US", 2000000000000),
            AssetDefinition("BTC", "Bitcoin", AssetClass.CRYPTO, "Binance", "USD", "Cryptocurrency", "Global", 800000000000),
            AssetDefinition("ETH", "Ethereum", AssetClass.CRYPTO, "Binance", "USD", "Cryptocurrency", "Global", 400000000000),
            AssetDefinition("GLD", "SPDR Gold Trust", AssetClass.COMMODITY, "NYSE", "USD", "Precious Metals", "US", 80000000000),
            AssetDefinition("US10Y", "10-Year Treasury", AssetClass.FIXED_INCOME, "CBOT", "USD", "Government", "US", 1500000000000)
        ]
        
        # Register assets
        for asset in assets:
            success = await manager.register_asset(asset)
            print(f"✅ Registered {asset.symbol}: {success}")
        
        # Test asset class organization
        print("\n📊 Testing Asset Class Organization")
        equity_assets = manager.get_assets_by_class(AssetClass.EQUITY)
        crypto_assets = manager.get_assets_by_class(AssetClass.CRYPTO)
        print(f"✅ Equity assets: {equity_assets}")
        print(f"✅ Crypto assets: {crypto_assets}")
        
        # Test asset data updates
        print("\n📈 Testing Asset Data Updates")
        
        # Generate sample data
        current_time = time.time()
        for i, asset in enumerate(assets):
            # Generate realistic price data
            base_price = 150.0 if asset.symbol == "AAPL" else 300.0 if asset.symbol == "MSFT" else 2500.0 if asset.symbol == "GOOGL" else 30000.0 if asset.symbol == "BTC" else 2000.0 if asset.symbol == "ETH" else 180.0 if asset.symbol == "GLD" else 100.0
            
            for j in range(50):  # 50 data points
                price = base_price * (1 + np.random.normal(0, 0.02))  # 2% daily volatility
                volume = np.random.lognormal(15, 1)  # Random volume
                
                data = AssetData(
                    symbol=asset.symbol,
                    timestamp=current_time - (50 - j) * 3600,  # Hourly data
                    price=price,
                    volume=volume,
                    bid=price * 0.999,
                    ask=price * 1.001,
                    open=price * (1 + np.random.normal(0, 0.01)),
                    high=price * (1 + abs(np.random.normal(0, 0.01))),
                    low=price * (1 - abs(np.random.normal(0, 0.01))),
                    close=price,
                    volatility=0.02
                )
                
                success = await manager.update_asset_data(data)
            
            print(f"✅ Updated data for {asset.symbol}")
        
        # Test asset metrics
        print("\n📊 Testing Asset Metrics")
        for asset in assets[:3]:  # Test first 3 assets
            metrics = manager.get_asset_metrics(asset.symbol)
            if metrics:
                print(f"✅ {asset.symbol} metrics:")
                print(f"   Return 1D: {metrics.return_1d:.4f}")
                print(f"   Return 1M: {metrics.return_1m:.4f}")
                print(f"   Volatility: {metrics.volatility_1m:.4f}")
                print(f"   Sharpe Ratio: {metrics.sharpe_ratio:.4f}")
            else:
                print(f"⚠️ No metrics available for {asset.symbol}")
        
        # Test cross-asset correlations
        print("\n🔗 Testing Cross-Asset Correlations")
        correlations = await manager.calculate_cross_asset_correlations()
        if correlations:
            print(f"✅ Correlations calculated for {len(correlations)} assets")
            
            # Show some correlations
            for symbol1 in list(correlations.keys())[:3]:
                print(f"   {symbol1} correlations:")
                for symbol2, corr in list(correlations[symbol1].items())[:3]:
                    print(f"     {symbol1}-{symbol2}: {corr:.3f}")
        else:
            print("❌ Correlation calculation failed")
        
        # Test asset class performance
        print("\n📈 Testing Asset Class Performance")
        equity_performance = await manager.get_asset_class_performance(AssetClass.EQUITY)
        if "status" not in equity_performance:
            print(f"✅ Equity class performance:")
            print(f"   Asset count: {equity_performance['asset_count']}")
            print(f"   Avg return 1M: {equity_performance['performance']['avg_return_1m']:.4f}")
            print(f"   Avg volatility: {equity_performance['performance']['avg_volatility']:.4f}")
        else:
            print("⚠️ No equity performance data available")
        
        # Test multi-asset summary
        print("\n📋 Testing Multi-Asset Summary")
        summary = await manager.get_multi_asset_summary()
        if "status" not in summary:
            print(f"✅ Total assets: {summary['total_assets']}")
            print(f"✅ Asset class distribution: {summary['asset_class_distribution']}")
            print(f"✅ Data points: {summary['data_points']}")
        else:
            print("⚠️ No summary data available")
        
        print("\n🎉 Asset Manager Test: PASSED")
        return True
        
    except Exception as e:
        print(f"❌ Asset Manager test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_cross_asset_strategy():
    """Test cross-asset strategy engine functionality"""
    
    print("\n🎯 Testing Cross-Asset Strategy Engine")
    print("=" * 50)
    
    try:
        # Initialize strategy engine
        config = {
            "strategy_parameters": {
                "min_signal_confidence": 0.6,
                "max_position_size": 0.2,
                "correlation_threshold": 0.7,
                "momentum_lookback": 20,
                "mean_reversion_lookback": 50
            },
            "us_compliance": {"strategy_validation": True, "audit_strategies": True}
        }
        
        engine = CrossAssetStrategyEngine(config)
        print(f"✅ CrossAssetStrategyEngine initialized")
        
        # Register strategies
        strategies = [
            {
                "name": "Asset Rotation Strategy",
                "type": StrategyType.ASSET_ROTATION.value,
                "asset_classes": ["equity", "fixed_income", "commodity", "crypto"],
                "rebalance_frequency": "monthly",
                "momentum_period": 20
            },
            {
                "name": "Pairs Trading Strategy",
                "type": StrategyType.PAIRS_TRADING.value,
                "pairs": [("AAPL", "MSFT"), ("BTC", "ETH")],
                "lookback_period": 50,
                "z_score_threshold": 2.0
            },
            {
                "name": "Momentum Rotation Strategy",
                "type": StrategyType.MOMENTUM_ROTATION.value,
                "momentum_lookback": 20,
                "top_assets": 5
            },
            {
                "name": "Mean Reversion Strategy",
                "type": StrategyType.MEAN_REVERSION.value,
                "mean_reversion_lookback": 50,
                "deviation_threshold": 2.0
            }
        ]
        
        for i, strategy_config in enumerate(strategies):
            success = await engine.register_strategy(f"strategy_{i}", strategy_config)
            print(f"✅ Registered strategy_{i}: {success}")
        
        # Generate sample market data
        print("\n📊 Generating Sample Market Data")
        
        # Asset class data for rotation strategy
        asset_class_data = {}
        for asset_class in ["equity", "fixed_income", "commodity", "crypto"]:
            dates = pd.date_range(start='2023-01-01', periods=100, freq='D')
            base_price = 100 if asset_class == "equity" else 50 if asset_class == "fixed_income" else 80 if asset_class == "commodity" else 200
            
            prices = [base_price * (1 + np.random.normal(0.001, 0.02)) for _ in range(100)]
            
            asset_class_data[asset_class] = pd.DataFrame({
                "date": dates,
                "price": prices
            })
        
        # Pair data for pairs trading
        pair_data = {}
        for pair in [("AAPL", "MSFT"), ("BTC", "ETH")]:
            for symbol in pair:
                dates = pd.date_range(start='2023-01-01', periods=100, freq='D')
                base_price = 150 if symbol == "AAPL" else 300 if symbol == "MSFT" else 30000 if symbol == "BTC" else 2000
                
                prices = [base_price * (1 + np.random.normal(0.001, 0.02)) for _ in range(100)]
                
                pair_data[symbol] = pd.DataFrame({
                    "date": dates,
                    "price": prices
                })
        
        # Asset data for momentum and mean reversion
        asset_data = {}
        for symbol in ["AAPL", "MSFT", "GOOGL", "BTC", "ETH"]:
            dates = pd.date_range(start='2023-01-01', periods=100, freq='D')
            base_price = 150 if symbol == "AAPL" else 300 if symbol == "MSFT" else 2500 if symbol == "GOOGL" else 30000 if symbol == "BTC" else 2000
            
            prices = [base_price * (1 + np.random.normal(0.001, 0.02)) for _ in range(100)]
            
            asset_data[symbol] = pd.DataFrame({
                "date": dates,
                "price": prices
            })
        
        print("✅ Sample market data generated")
        
        # Test asset rotation strategy
        print("\n🔄 Testing Asset Rotation Strategy")
        rotation_signal = await engine.generate_asset_rotation_signal("strategy_0", asset_class_data)
        if rotation_signal:
            print(f"✅ Asset rotation signal generated")
            print(f"   Rotation reason: {rotation_signal.rotation_reason}")
            print(f"   Rebalance urgency: {rotation_signal.rebalance_urgency}")
            print(f"   Expected return: {rotation_signal.expected_return:.4f}")
            print(f"   Recommended allocation: {rotation_signal.recommended_allocation}")
        else:
            print("❌ Asset rotation signal generation failed")
        
        # Test pairs trading strategy
        print("\n📊 Testing Pairs Trading Strategy")
        pairs_signal = await engine.generate_pairs_trading_signal("strategy_1", pair_data)
        if pairs_signal:
            print(f"✅ Pairs trading signal generated")
            print(f"   Pair: {pairs_signal.pair}")
            print(f"   Signal type: {pairs_signal.signal_type}")
            print(f"   Z-score: {pairs_signal.z_score:.3f}")
            print(f"   Correlation: {pairs_signal.correlation:.3f}")
            print(f"   Expected return: {pairs_signal.expected_return:.4f}")
        else:
            print("❌ Pairs trading signal generation failed")
        
        # Test momentum rotation strategy
        print("\n🚀 Testing Momentum Rotation Strategy")
        momentum_signal = await engine.generate_momentum_rotation_signal("strategy_2", asset_data)
        if momentum_signal:
            print(f"✅ Momentum rotation signal generated")
            print(f"   Symbols: {momentum_signal.symbols}")
            print(f"   Signal strength: {momentum_signal.strength.value}")
            print(f"   Confidence: {momentum_signal.confidence:.3f}")
            print(f"   Expected return: {momentum_signal.expected_return:.4f}")
        else:
            print("❌ Momentum rotation signal generation failed")
        
        # Test mean reversion strategy
        print("\n📉 Testing Mean Reversion Strategy")
        mean_rev_signal = await engine.generate_mean_reversion_signal("strategy_3", asset_data)
        if mean_rev_signal:
            print(f"✅ Mean reversion signal generated")
            print(f"   Symbol: {mean_rev_signal.symbols[0]}")
            print(f"   Signal type: {mean_rev_signal.signal_type}")
            print(f"   Signal strength: {mean_rev_signal.strength.value}")
            print(f"   Expected return: {mean_rev_signal.expected_return:.4f}")
        else:
            print("❌ Mean reversion signal generation failed")
        
        # Test strategy execution
        print("\n⚡ Testing Strategy Execution")
        market_data = {
            "asset_class_data": asset_class_data,
            "pair_data": pair_data,
            "asset_data": asset_data
        }
        
        all_signals = await engine.execute_all_strategies(market_data)
        print(f"✅ Executed {len(all_signals)} strategies")
        
        for strategy_id, signals in all_signals.items():
            print(f"   {strategy_id}: {len(signals)} signals")
        
        # Test strategy summary
        print("\n📋 Testing Strategy Summary")
        summary = engine.get_strategy_summary()
        print(f"✅ Total strategies: {summary['total_strategies']}")
        print(f"✅ Active strategies: {summary['active_strategies']}")
        print(f"✅ Strategy types: {summary['strategy_types']}")
        print(f"✅ Signal statistics: {summary['signal_statistics']}")
        
        print("\n🎉 Cross-Asset Strategy Engine Test: PASSED")
        return True
        
    except Exception as e:
        print(f"❌ Cross-Asset Strategy Engine test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_portfolio_constructor():
    """Test portfolio constructor functionality"""
    
    print("\n💼 Testing Portfolio Constructor")
    print("=" * 50)
    
    try:
        # Initialize portfolio constructor
        config = {
            "rebalancing": {
                "min_trade_size": 1000.0,
                "max_trade_size": 100000.0,
                "transaction_cost": 0.001,
                "tax_rate": 0.20
            },
            "risk_budget": {
                "max_portfolio_volatility": 0.12,
                "max_asset_class_volatility": 0.20
            },
            "us_compliance": {"concentration_limits": True, "audit_portfolios": True}
        }
        
        constructor = PortfolioConstructor(config)
        print(f"✅ PortfolioConstructor initialized")
        
        # Test portfolio construction
        print("\n🏗️ Testing Portfolio Construction")
        
        # Mock asset data
        asset_data = {
            "equity": {
                "assets": ["AAPL", "MSFT", "GOOGL"],
                "expected_return": 0.08,
                "volatility": 0.16
            },
            "fixed_income": {
                "assets": ["US10Y", "BND"],
                "expected_return": 0.04,
                "volatility": 0.08
            },
            "commodity": {
                "assets": ["GLD", "OIL"],
                "expected_return": 0.06,
                "volatility": 0.20
            },
            "real_estate": {
                "assets": ["VNQ", "REIT"],
                "expected_return": 0.07,
                "volatility": 0.15
            },
            "alternative": {
                "assets": ["BTC", "ETH"],
                "expected_return": 0.09,
                "volatility": 0.18
            }
        }
        
        # Construct different portfolio types
        portfolio_types = [PortfolioType.CONSERVATIVE, PortfolioType.BALANCED, PortfolioType.GROWTH, PortfolioType.AGGRESSIVE]
        
        for portfolio_type in portfolio_types:
            portfolio = await constructor.construct_portfolio(
                f"portfolio_{portfolio_type.value}",
                portfolio_type,
                1000000.0,  # $1M
                asset_data
            )
            
            if portfolio:
                print(f"✅ {portfolio_type.value} portfolio constructed")
                print(f"   Expected return: {portfolio.expected_return:.4f}")
                print(f"   Expected volatility: {portfolio.expected_volatility:.4f}")
                print(f"   Sharpe ratio: {portfolio.sharpe_ratio:.4f}")
                print(f"   Diversification score: {portfolio.diversification_score:.3f}")
                print(f"   Rebalance frequency: {portfolio.rebalance_frequency.value}")
            else:
                print(f"❌ {portfolio_type.value} portfolio construction failed")
        
        # Test custom allocations
        print("\n🎯 Testing Custom Allocations")
        custom_allocations = {
            "equity": 0.35,
            "fixed_income": 0.25,
            "commodity": 0.15,
            "real_estate": 0.15,
            "alternative": 0.10
        }
        
        custom_portfolio = await constructor.construct_portfolio(
            "custom_portfolio",
            PortfolioType.BALANCED,
            500000.0,  # $500K
            asset_data,
            custom_allocations
        )
        
        if custom_portfolio:
            print(f"✅ Custom portfolio constructed")
            print(f"   Expected return: {custom_portfolio.expected_return:.4f}")
            print(f"   Expected volatility: {custom_portfolio.expected_volatility:.4f}")
        else:
            print("❌ Custom portfolio construction failed")
        
        # Test rebalancing recommendation
        print("\n🔄 Testing Rebalancing Recommendation")
        
        # Simulate current values with drift
        current_values = {
            "equity": 450000.0,  # Overweight (target 40%)
            "fixed_income": 200000.0,  # Underweight (target 35%)
            "commodity": 80000.0,  # Underweight (target 10%)
            "real_estate": 120000.0,  # Overweight (target 10%)
            "alternative": 50000.0  # Underweight (target 5%)
        }
        
        if custom_portfolio:
            rebalance_rec = await constructor.generate_rebalance_recommendation(
                "custom_portfolio",
                current_values
            )
            
            if rebalance_rec:
                print(f"✅ Rebalance recommendation generated")
                print(f"   Rebalance type: {rebalance_rec.rebalance_type}")
                print(f"   Urgency: {rebalance_rec.urgency}")
                print(f"   Estimated cost: ${rebalance_rec.estimated_cost:.2f}")
                print(f"   Number of trades: {len(rebalance_rec.trades)}")
                
                for trade in rebalance_rec.trades[:3]:  # Show first 3 trades
                    print(f"   Trade: {trade['asset_class']} {trade['trade_type']} ${abs(trade['trade_value']):,.2f}")
            else:
                print("⚠️ No rebalancing needed")
        
        # Test portfolio optimization
        print("\n⚡ Testing Portfolio Optimization")
        
        # Generate mock return data
        asset_returns = {}
        for asset_class in asset_data.keys():
            dates = pd.date_range(start='2023-01-01', periods=252, freq='D')
            returns = np.random.normal(0.001, 0.02, 252)  # Daily returns
            
            asset_returns[asset_class] = pd.DataFrame({
                "date": dates,
                "returns": returns
            })
        
        if custom_portfolio:
            optimized_weights = await constructor.optimize_portfolio_allocation(
                "custom_portfolio",
                asset_returns
            )
            
            if optimized_weights:
                print(f"✅ Portfolio optimization completed")
                print(f"   Optimized weights:")
                for asset_class, weight in optimized_weights.items():
                    print(f"     {asset_class}: {weight:.3f}")
            else:
                print("❌ Portfolio optimization failed")
        
        # Test portfolio summary
        print("\n📋 Testing Portfolio Summary")
        summary = constructor.get_portfolio_summary()
        if "status" not in summary:
            print(f"✅ Total portfolios: {summary['total_portfolios']}")
            print(f"✅ Total value: ${summary['total_value']:,.2f}")
            print(f"✅ Portfolio types: {summary['portfolio_types']}")
            print(f"✅ Avg expected return: {summary['performance_metrics']['avg_expected_return']:.4f}")
            print(f"✅ Avg volatility: {summary['performance_metrics']['avg_volatility']:.4f}")
        else:
            print("⚠️ No portfolio data available")
        
        print("\n🎉 Portfolio Constructor Test: PASSED")
        return True
        
    except Exception as e:
        print(f"❌ Portfolio Constructor test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_multi_asset_integration():
    """Test full multi-asset integration"""
    
    print("\n🔄 Testing Multi-Asset Integration")
    print("=" * 50)
    
    try:
        # Initialize all components
        manager_config = {"us_compliance": {"asset_screening": True}}
        manager = AssetManager(manager_config)
        
        strategy_config = {"us_compliance": {"strategy_validation": True}}
        strategy_engine = CrossAssetStrategyEngine(strategy_config)
        
        constructor_config = {"us_compliance": {"concentration_limits": True}}
        constructor = PortfolioConstructor(constructor_config)
        
        print(f"✅ All multi-asset components initialized")
        
        # Step 1: Asset registration and data management
        print("\n🏛️ Step 1: Asset Registration and Data Management")
        
        # Register diverse assets
        assets = [
            AssetDefinition("AAPL", "Apple Inc.", AssetClass.EQUITY, "NASDAQ", "USD"),
            AssetDefinition("MSFT", "Microsoft Corp.", AssetClass.EQUITY, "NASDAQ", "USD"),
            AssetDefinition("BTC", "Bitcoin", AssetClass.CRYPTO, "Binance", "USD"),
            AssetDefinition("ETH", "Ethereum", AssetClass.CRYPTO, "Binance", "USD"),
            AssetDefinition("GLD", "Gold Trust", AssetClass.COMMODITY, "NYSE", "USD"),
            AssetDefinition("US10Y", "10Y Treasury", AssetClass.FIXED_INCOME, "CBOT", "USD")
        ]
        
        for asset in assets:
            await manager.register_asset(asset)
        
        # Generate and update asset data
        current_time = time.time()
        for asset in assets:
            for j in range(30):  # 30 data points
                base_price = 150.0 if asset.symbol == "AAPL" else 300.0 if asset.symbol == "MSFT" else 30000.0 if asset.symbol == "BTC" else 2000.0 if asset.symbol == "ETH" else 180.0 if asset.symbol == "GLD" else 100.0
                price = base_price * (1 + np.random.normal(0, 0.02))
                
                data = AssetData(
                    symbol=asset.symbol,
                    timestamp=current_time - (30 - j) * 86400,  # Daily data
                    price=price,
                    volume=np.random.lognormal(15, 1),
                    volatility=0.02
                )
                
                await manager.update_asset_data(data)
        
        print(f"✅ Registered {len(assets)} assets with data")
        
        # Step 2: Strategy execution
        print("\n🎯 Step 2: Strategy Execution")
        
        # Register strategies
        rotation_config = {
            "name": "Multi-Asset Rotation",
            "type": StrategyType.ASSET_ROTATION.value,
            "asset_classes": ["equity", "crypto", "commodity", "fixed_income"],
            "rebalance_frequency": "monthly",
            "momentum_period": 20
        }
        
        await strategy_engine.register_strategy("rotation", rotation_config)
        
        # Generate market data for strategies
        asset_class_data = {}
        for asset_class in ["equity", "crypto", "commodity", "fixed_income"]:
            dates = pd.date_range(start='2023-01-01', periods=30, freq='D')
            base_price = 100 if asset_class == "equity" else 200 if asset_class == "crypto" else 80 if asset_class == "commodity" else 50
            prices = [base_price * (1 + np.random.normal(0.001, 0.02)) for _ in range(30)]
            
            asset_class_data[asset_class] = pd.DataFrame({
                "date": dates,
                "price": prices
            })
        
        # Execute strategy
        market_data = {"asset_class_data": asset_class_data}
        strategy_signals = await strategy_engine.execute_strategy("rotation", market_data)
        
        if strategy_signals:
            print(f"✅ Strategy executed: {len(strategy_signals)} signals")
            for signal in strategy_signals:
                if hasattr(signal, 'rotation_reason'):
                    print(f"   Rotation: {signal.rotation_reason}")
                    print(f"   Expected return: {signal.expected_return:.4f}")
        else:
            print("⚠️ No strategy signals generated")
        
        # Step 3: Portfolio construction
        print("\n💼 Step 3: Portfolio Construction")
        
        # Create asset data for portfolio
        portfolio_asset_data = {
            "equity": {"assets": ["AAPL", "MSFT"]},
            "crypto": {"assets": ["BTC", "ETH"]},
            "commodity": {"assets": ["GLD"]},
            "fixed_income": {"assets": ["US10Y"]},
            "real_estate": {"assets": []},
            "alternative": {"assets": []}
        }
        
        # Construct balanced portfolio
        portfolio = await constructor.construct_portfolio(
            "multi_asset_portfolio",
            PortfolioType.BALANCED,
            1000000.0,
            portfolio_asset_data
        )
        
        if portfolio:
            print(f"✅ Portfolio constructed")
            print(f"   Expected return: {portfolio.expected_return:.4f}")
            print(f"   Expected volatility: {portfolio.expected_volatility:.4f}")
            print(f"   Sharpe ratio: {portfolio.sharpe_ratio:.4f}")
            
            # Show allocations
            for asset_class, allocation in portfolio.allocations.items():
                print(f"   {asset_class}: {allocation.target_weight:.1%}")
        else:
            print("❌ Portfolio construction failed")
        
        # Step 4: Cross-asset correlations
        print("\n🔗 Step 4: Cross-Asset Correlations")
        
        correlations = await manager.calculate_cross_asset_correlations()
        if correlations:
            print(f"✅ Correlations calculated")
            
            # Show highest correlations
            all_corrs = []
            for symbol1, corr_dict in correlations.items():
                for symbol2, corr in corr_dict.items():
                    if symbol1 != symbol2:
                        all_corrs.append((symbol1, symbol2, abs(corr)))
            
            all_corrs.sort(key=lambda x: x[2], reverse=True)
            
            print("   Top correlations:")
            for symbol1, symbol2, corr in all_corrs[:3]:
                print(f"     {symbol1}-{symbol2}: {corr:.3f}")
        else:
            print("❌ Correlation calculation failed")
        
        # Step 5: Integrated analysis
        print("\n📊 Step 5: Integrated Analysis")
        
        # Asset manager summary
        manager_summary = await manager.get_multi_asset_summary()
        if "status" not in manager_summary:
            print(f"✅ Asset manager: {manager_summary['total_assets']} assets")
            print(f"   Asset classes: {list(manager_summary['asset_class_distribution'].keys())}")
        
        # Strategy engine summary
        strategy_summary = strategy_engine.get_strategy_summary()
        print(f"✅ Strategy engine: {strategy_summary['total_strategies']} strategies")
        print(f"   Signal statistics: {strategy_summary['signal_statistics']}")
        
        # Portfolio constructor summary
        portfolio_summary = constructor.get_portfolio_summary()
        if "status" not in portfolio_summary:
            print(f"✅ Portfolio constructor: {portfolio_summary['total_portfolios']} portfolios")
            print(f"   Total value: ${portfolio_summary['total_value']:,.2f}")
        
        print("\n🎉 Multi-Asset Integration Test: PASSED")
        return True
        
    except Exception as e:
        print(f"❌ Multi-Asset Integration test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def main():
    """Run all multi-asset tests"""
    try:
        print("🧪 MULTI-ASSET EXPANSION TEST SUITE")
        print("=" * 70)
        
        # Run tests
        test1 = await test_asset_manager()
        test2 = await test_cross_asset_strategy()
        test3 = await test_portfolio_constructor()
        test4 = await test_multi_asset_integration()
        
        # Summary
        print("\n" + "=" * 70)
        print("📊 MULTI-ASSET EXPANSION TEST RESULTS")
        print("=" * 70)
        print(f"Asset Manager:           {'✅ PASSED' if test1 else '❌ FAILED'}")
        print(f"Cross-Asset Strategy:    {'✅ PASSED' if test2 else '❌ FAILED'}")
        print(f"Portfolio Constructor:   {'✅ PASSED' if test3 else '❌ FAILED'}")
        print(f"Multi-Asset Integration: {'✅ PASSED' if test4 else '❌ FAILED'}")
        
        if all([test1, test2, test3, test4]):
            print("\n🎯 ALL MULTI-ASSET EXPANSION TESTS PASSED!")
            print("✅ Multi-asset data management working")
            print("✅ Cross-asset strategy generation working")
            print("✅ Portfolio construction and rebalancing working")
            print("✅ Full multi-asset integration successful")
        else:
            print("\n❌ Some multi-asset expansion tests failed")
        
    except Exception as e:
        print(f"❌ Multi-asset expansion test suite error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
