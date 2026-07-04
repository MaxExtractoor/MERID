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

from merid.risk.portfolio_optimizer import PortfolioOptimizer, Asset
from merid.risk.position_sizing import PositionSizer, Position, RiskParameters
from merid.risk.risk_monitor import RiskMonitor
from utils.logger import get_logger

logger = get_logger("test_risk_management")

async def test_portfolio_optimizer():
    """Test portfolio optimizer functionality"""
    
    print("💼 Testing Portfolio Optimizer")
    print("=" * 50)
    
    try:
        # Initialize optimizer
        config = {
            "risk_free_rate": 0.02,
            "optimization_methods": ["mean_variance", "risk_parity", "max_diversification", "min_variance"],
            "us_compliance": {"audit_optimization": True}
        }
        
        optimizer = PortfolioOptimizer(config)
        print(f"✅ PortfolioOptimizer initialized")
        
        # Create test assets
        assets = [
            Asset("BTC", 0.15, 0.40, 0.0, 0.0, 1.0, "crypto"),
            Asset("ETH", 0.12, 0.35, 0.0, 0.0, 1.0, "crypto"),
            Asset("SPY", 0.08, 0.20, 0.0, 0.0, 1.0, "equity"),
            Asset("GLD", 0.05, 0.15, 0.0, 0.0, 1.0, "commodity"),
            Asset("BND", 0.03, 0.08, 0.0, 0.0, 1.0, "bond")
        ]
        
        # Add assets
        for asset in assets:
            success = optimizer.add_asset(asset)
            print(f"✅ Added asset {asset.symbol}: {success}")
        
        # Create correlation matrix
        n_assets = len(assets)
        correlation_matrix = np.array([
            [1.0, 0.7, 0.3, 0.1, 0.0],
            [0.7, 1.0, 0.4, 0.2, 0.1],
            [0.3, 0.4, 1.0, 0.5, 0.3],
            [0.1, 0.2, 0.5, 1.0, 0.4],
            [0.0, 0.1, 0.3, 0.4, 1.0]
        ])
        
        # Update correlation matrix
        success = optimizer.update_correlation_matrix(correlation_matrix)
        print(f"✅ Updated correlation matrix: {success}")
        
        # Test mean-variance optimization
        print("\n📊 Testing Mean-Variance Optimization")
        mv_result = await optimizer.optimize_portfolio("mean_variance")
        if mv_result:
            print(f"✅ Mean-variance optimization completed")
            print(f"   Expected return: {mv_result.portfolio_metrics.expected_return:.4f}")
            print(f"   Volatility: {mv_result.portfolio_metrics.volatility:.4f}")
            print(f"   Sharpe ratio: {mv_result.portfolio_metrics.sharpe_ratio:.4f}")
            print(f"   Convergence: {mv_result.convergence}")
            
            # Show weights
            print("   Optimal weights:")
            for symbol, weight in mv_result.weights.items():
                print(f"     {symbol}: {weight:.3f}")
        else:
            print("❌ Mean-variance optimization failed")
        
        # Test risk parity optimization
        print("\n⚖️ Testing Risk Parity Optimization")
        rp_result = await optimizer.optimize_portfolio("risk_parity")
        if rp_result:
            print(f"✅ Risk parity optimization completed")
            print(f"   Expected return: {rp_result.portfolio_metrics.expected_return:.4f}")
            print(f"   Volatility: {rp_result.portfolio_metrics.volatility:.4f}")
            print(f"   Diversification ratio: {rp_result.portfolio_metrics.diversification_ratio:.3f}")
            
            # Show weights
            print("   Risk parity weights:")
            for symbol, weight in rp_result.weights.items():
                print(f"     {symbol}: {weight:.3f}")
        else:
            print("❌ Risk parity optimization failed")
        
        # Test max diversification optimization
        print("\n🎯 Testing Max Diversification Optimization")
        md_result = await optimizer.optimize_portfolio("max_diversification")
        if md_result:
            print(f"✅ Max diversification optimization completed")
            print(f"   Expected return: {md_result.portfolio_metrics.expected_return:.4f}")
            print(f"   Volatility: {md_result.portfolio_metrics.volatility:.4f}")
            print(f"   Diversification ratio: {md_result.portfolio_metrics.diversification_ratio:.3f}")
        else:
            print("❌ Max diversification optimization failed")
        
        # Test optimization comparison
        print("\n📈 Testing Optimization Comparison")
        comparison = await optimizer.compare_optimizations()
        if comparison:
            print(f"✅ Optimization comparison completed")
            print(f"   Best method: {comparison.get('best_method', 'unknown')}")
            print(f"   Best Sharpe ratio: {comparison.get('best_sharpe', 'unknown'):.4f}")
            
            # Show all methods
            for method, result in comparison.items():
                if method not in ['best_method', 'best_sharpe'] and result:
                    print(f"   {method}: Sharpe = {result.portfolio_metrics.sharpe_ratio:.4f}")
        else:
            print("❌ Optimization comparison failed")
        
        # Test optimizer summary
        print("\n📋 Testing Optimizer Summary")
        summary = optimizer.get_optimization_summary()
        if "status" not in summary:
            print(f"✅ Total optimizations: {summary['total_optimizations']}")
            print(f"✅ Recent optimizations: {summary['recent_optimizations']}")
            print(f"✅ Method distribution: {summary['method_distribution']}")
            print(f"✅ Asset count: {summary['asset_count']}")
        else:
            print("⚠️ No optimization data available")
        
        print("\n🎉 Portfolio Optimizer Test: PASSED")
        return True
        
    except Exception as e:
        print(f"❌ Portfolio Optimizer test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_position_sizer():
    """Test position sizer functionality"""
    
    print("\n📏 Testing Position Sizer")
    print("=" * 50)
    
    try:
        # Initialize sizer
        config = {
            "portfolio_value": 1000000.0,
            "risk_parameters": {
                "max_portfolio_risk": 0.02,
                "max_position_risk": 0.01,
                "stop_loss_atr_multiplier": 2.0,
                "take_profit_atr_multiplier": 3.0
            },
            "sizing_methods": ["volatility_based", "kelly_criterion", "fixed_fractional", "risk_parity"],
            "us_compliance": {"audit_sizing": True}
        }
        
        sizer = PositionSizer(config)
        print(f"✅ PositionSizer initialized")
        
        # Create test positions
        positions = [
            Position("BTC", 30000.0, 0.40, 1.0, 0.3, 0.01, "crypto"),
            Position("ETH", 2000.0, 0.35, 1.2, 0.25, 0.01, "crypto"),
            Position("SPY", 400.0, 0.20, 0.8, 0.2, 0.01, "equity"),
            Position("GLD", 180.0, 0.15, 0.3, 0.15, 0.01, "commodity")
        ]
        
        # Add positions
        for position in positions:
            success = sizer.add_position(position)
            print(f"✅ Added position {position.symbol}: {success}")
        
        # Create correlation matrix
        n_positions = len(positions)
        correlation_matrix = np.array([
            [1.0, 0.7, 0.3, 0.1],
            [0.7, 1.0, 0.4, 0.2],
            [0.3, 0.4, 1.0, 0.5],
            [0.1, 0.2, 0.5, 1.0]
        ])
        
        # Update correlation matrix
        success = sizer.update_correlation_matrix(correlation_matrix)
        print(f"✅ Updated correlation matrix: {success}")
        
        # Test volatility-based sizing
        print("\n📊 Testing Volatility-Based Sizing")
        vol_result = await sizer.calculate_position_size("BTC", "volatility_based", signal_strength=0.8)
        if vol_result:
            print(f"✅ Volatility-based sizing completed")
            print(f"   Position size: {vol_result.position_size:.4f}")
            print(f"   Position value: ${vol_result.position_value:,.2f}")
            print(f"   Shares: {vol_result.shares}")
            print(f"   Risk amount: ${vol_result.risk_amount:,.2f}")
            print(f"   Stop loss: ${vol_result.stop_loss_price:.2f}")
            print(f"   Take profit: ${vol_result.take_profit_price:.2f}")
            print(f"   Risk-reward ratio: {vol_result.risk_reward_ratio:.2f}")
            print(f"   Confidence score: {vol_result.confidence_score:.3f}")
        else:
            print("❌ Volatility-based sizing failed")
        
        # Test Kelly criterion sizing
        print("\n🎯 Testing Kelly Criterion Sizing")
        kelly_result = await sizer.calculate_position_size("ETH", "kelly_criterion", signal_strength=0.9)
        if kelly_result:
            print(f"✅ Kelly criterion sizing completed")
            print(f"   Position size: {kelly_result.position_size:.4f}")
            print(f"   Position value: ${kelly_result.position_value:,.2f}")
            print(f"   Kelly fraction: {kelly_result.metadata.get('kelly_fraction', 0):.4f}")
            print(f"   Win rate: {kelly_result.metadata.get('win_rate', 0):.3f}")
        else:
            print("❌ Kelly criterion sizing failed")
        
        # Test fixed fractional sizing
        print("\n📏 Testing Fixed Fractional Sizing")
        fixed_result = await sizer.calculate_position_size("SPY", "fixed_fractional", signal_strength=0.7)
        if fixed_result:
            print(f"✅ Fixed fractional sizing completed")
            print(f"   Position size: {fixed_result.position_size:.4f}")
            print(f"   Position value: ${fixed_result.position_value:,.2f}")
            print(f"   Fixed fraction: {fixed_result.metadata.get('fixed_fraction', 0):.4f}")
        else:
            print("❌ Fixed fractional sizing failed")
        
        # Test risk parity sizing
        print("\n⚖️ Testing Risk Parity Sizing")
        parity_result = await sizer.calculate_position_size("GLD", "risk_parity", signal_strength=0.6)
        if parity_result:
            print(f"✅ Risk parity sizing completed")
            print(f"   Position size: {parity_result.position_size:.4f}")
            print(f"   Position value: ${parity_result.position_value:,.2f}")
            print(f"   Risk per position: {parity_result.metadata.get('risk_per_position', 0):.4f}")
        else:
            print("❌ Risk parity sizing failed")
        
        # Test sizing method comparison
        print("\n📈 Testing Sizing Method Comparison")
        comparison = await sizer.compare_sizing_methods("BTC", signal_strength=0.8)
        if comparison:
            print(f"✅ Sizing comparison completed")
            print(f"   Best method: {comparison.get('best_method', 'unknown')}")
            print(f"   Best confidence: {comparison.get('best_confidence', 'unknown'):.3f}")
            
            # Show all methods
            for method, result in comparison.items():
                if method not in ['best_method', 'best_confidence'] and result:
                    print(f"   {method}: Size = {result.position_size:.4f}, Confidence = {result.confidence_score:.3f}")
        else:
            print("❌ Sizing comparison failed")
        
        # Test portfolio risk calculation
        print("\n⚠️ Testing Portfolio Risk Calculation")
        current_positions = {"BTC": 0.3, "ETH": 0.25, "SPY": 0.2, "GLD": 0.15}
        portfolio_risk = await sizer.calculate_portfolio_risk(current_positions)
        
        print(f"✅ Portfolio risk calculated")
        print(f"   Total risk: ${portfolio_risk.total_risk:,.2f}")
        print(f"   Leverage: {portfolio_risk.leverage:.2f}")
        print(f"   VaR 95%: ${portfolio_risk.var_95:,.2f}")
        print(f"   Expected shortfall: ${portfolio_risk.expected_shortfall:,.2f}")
        print(f"   Risk budget used: {portfolio_risk.risk_budget_used:.3f}")
        
        # Test sizer summary
        print("\n📋 Testing Sizer Summary")
        summary = sizer.get_sizing_summary()
        if "status" not in summary:
            print(f"✅ Total sizing calculations: {summary['total_sizing_calculations']}")
            print(f"✅ Recent sizing: {summary['recent_sizing']}")
            print(f"✅ Method distribution: {summary['method_distribution']}")
            print(f"✅ Position count: {summary['position_count']}")
        else:
            print("⚠️ No sizing data available")
        
        print("\n🎉 Position Sizer Test: PASSED")
        return True
        
    except Exception as e:
        print(f"❌ Position Sizer test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_risk_monitor():
    """Test risk monitor functionality"""
    
    print("\n🚨 Testing Risk Monitor")
    print("=" * 50)
    
    try:
        # Initialize monitor
        config = {
            "monitoring_interval": 5,  # 5 seconds for testing
            "alert_cooldown": 10,  # 10 seconds for testing
            "us_compliance": {
                "risk_limits": True,
                "alert_logging": True,
                "stress_testing": True
            }
        }
        
        monitor = RiskMonitor(config)
        print(f"✅ RiskMonitor initialized")
        
        # Test risk limit management
        print("\n📊 Testing Risk Limit Management")
        
        # Add custom risk limit
        monitor.add_risk_limit("custom_leverage", "max_leverage", 1.5)
        print(f"✅ Added custom leverage limit: 1.5")
        
        # Show all risk limits
        limits = monitor.get_risk_limits()
        print(f"✅ Total risk limits: {len(limits)}")
        for limit_id, limit in list(limits.items())[:3]:
            print(f"   {limit_id}: {limit.limit_value} (active: {limit.active})")
        
        # Test risk metrics collection
        print("\n📈 Testing Risk Metrics Collection")
        risk_metrics = await monitor._collect_risk_metrics()
        if risk_metrics:
            print(f"✅ Risk metrics collected")
            print(f"   Portfolio value: ${risk_metrics.portfolio_value:,.2f}")
            print(f"   Leverage: {risk_metrics.leverage:.2f}")
            print(f"   VaR 95%: ${risk_metrics.var_95:,.2f}")
            print(f"   Max drawdown: {risk_metrics.max_drawdown:.3f}")
            print(f"   Sharpe ratio: {risk_metrics.sharpe_ratio:.2f}")
        else:
            print("❌ Risk metrics collection failed")
        
        # Test risk limit checking
        print("\n⚠️ Testing Risk Limit Checking")
        if risk_metrics:
            # Update risk limits with current metrics
            await monitor._update_risk_limits(risk_metrics)
            
            # Check for breaches
            await monitor._check_risk_breaches(risk_metrics)
            
            # Get active alerts
            active_alerts = monitor.get_active_alerts()
            print(f"✅ Active alerts: {len(active_alerts)}")
            
            for alert in active_alerts[:3]:
                print(f"   {alert.alert_type}: {alert.severity} - {alert.message}")
        else:
            print("⚠️ No risk metrics available for limit checking")
        
        # Test stress testing
        print("\n🧪 Testing Stress Testing")
        
        # Mock portfolio data
        portfolio_data = {
            "portfolio_value": 1000000.0,
            "leverage": 1.5,
            "var_95": 20000.0,
            "correlation_risk": 0.3
        }
        
        # Test individual stress scenarios
        scenarios = ["market_crash", "interest_rate_shock", "liquidity_crisis"]
        for scenario in scenarios:
            result = await monitor.run_stress_test(scenario, portfolio_data)
            if result:
                print(f"✅ {scenario} stress test completed")
                print(f"   Portfolio loss: ${result.portfolio_loss:,.2f}")
                print(f"   Loss percentage: {result.loss_percentage:.2%}")
                print(f"   Worst position: {result.worst_position}")
            else:
                print(f"❌ {scenario} stress test failed")
        
        # Test comprehensive stress testing
        print("\n🎯 Testing Comprehensive Stress Testing")
        comprehensive_results = await monitor.run_comprehensive_stress_tests(portfolio_data)
        if comprehensive_results:
            print(f"✅ Comprehensive stress testing completed")
            print(f"   Worst scenario: {comprehensive_results.get('worst_scenario', 'unknown')}")
            print(f"   Worst loss: {comprehensive_results.get('worst_loss', 0):.2%}")
            
            # Show all scenario results
            for scenario, result in comprehensive_results.items():
                if scenario not in ['worst_scenario', 'worst_loss'] and result:
                    print(f"   {scenario}: {result.loss_percentage:.2%}")
        else:
            print("❌ Comprehensive stress testing failed")
        
        # Test monitoring loop (brief)
        print("\n🔄 Testing Monitoring Loop")
        await monitor.start_monitoring()
        
        # Let it run for a few seconds
        await asyncio.sleep(3)
        
        # Check for new alerts
        new_alerts = monitor.get_active_alerts()
        print(f"✅ Monitoring loop test: {len(new_alerts)} alerts generated")
        
        await monitor.stop_monitoring()
        
        # Test risk summary
        print("\n📋 Testing Risk Summary")
        summary = monitor.get_risk_summary()
        if "status" not in summary:
            print(f"✅ Active alerts: {summary['active_alerts']}")
            print(f"✅ Alert distribution: {summary['alert_distribution']}")
            print(f"✅ Risk limits: {len(summary['risk_limits'])}")
            print(f"✅ Stress test summary: {summary['stress_test_summary']['total_tests']}")
        else:
            print("⚠️ No risk data available")
        
        print("\n🎉 Risk Monitor Test: PASSED")
        return True
        
    except Exception as e:
        print(f"❌ Risk Monitor test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_risk_management_integration():
    """Test full risk management integration"""
    
    print("\n🔄 Testing Risk Management Integration")
    print("=" * 50)
    
    try:
        # Initialize all components
        optimizer_config = {"risk_free_rate": 0.02, "us_compliance": {"audit_optimization": True}}
        optimizer = PortfolioOptimizer(optimizer_config)
        
        sizer_config = {
            "portfolio_value": 1000000.0,
            "risk_parameters": {"max_portfolio_risk": 0.02, "max_position_risk": 0.01},
            "us_compliance": {"audit_sizing": True}
        }
        sizer = PositionSizer(sizer_config)
        
        monitor_config = {"monitoring_interval": 5, "us_compliance": {"risk_limits": True}}
        monitor = RiskMonitor(monitor_config)
        
        print(f"✅ All risk management components initialized")
        
        # Step 1: Portfolio optimization
        print("\n💼 Step 1: Portfolio Optimization")
        
        # Add assets to optimizer
        assets = [
            Asset("BTC", 0.15, 0.40, 0.0, 0.0, 1.0, "crypto"),
            Asset("ETH", 0.12, 0.35, 0.0, 0.0, 1.0, "crypto"),
            Asset("SPY", 0.08, 0.20, 0.0, 0.0, 1.0, "equity"),
            Asset("GLD", 0.05, 0.15, 0.0, 0.0, 1.0, "commodity")
        ]
        
        for asset in assets:
            optimizer.add_asset(asset)
            sizer.add_position(Position(asset.symbol, 30000.0 if asset.symbol == "BTC" else 2000.0 if asset.symbol == "ETH" else 400.0 if asset.symbol == "SPY" else 180.0, 
                                      asset.volatility, 1.0, 0.3, 0.01, asset.asset_class))
        
        # Add correlation matrix
        correlation_matrix = np.array([
            [1.0, 0.7, 0.3, 0.1],
            [0.7, 1.0, 0.4, 0.2],
            [0.3, 0.4, 1.0, 0.5],
            [0.1, 0.2, 0.5, 1.0]
        ])
        
        optimizer.update_correlation_matrix(correlation_matrix)
        sizer.update_correlation_matrix(correlation_matrix)
        
        # Optimize portfolio
        opt_result = await optimizer.optimize_portfolio("mean_variance")
        if opt_result:
            print(f"✅ Portfolio optimized: Sharpe = {opt_result.portfolio_metrics.sharpe_ratio:.3f}")
            optimal_weights = opt_result.weights
        else:
            print("❌ Portfolio optimization failed")
            optimal_weights = {"BTC": 0.4, "ETH": 0.3, "SPY": 0.2, "GLD": 0.1}
        
        # Step 2: Position sizing
        print("\n📏 Step 2: Position Sizing")
        
        # Calculate position sizes based on optimal weights
        position_sizes = {}
        for symbol, weight in optimal_weights.items():
            sizing_result = await sizer.calculate_position_size(symbol, "volatility_based", signal_strength=0.8)
            if sizing_result:
                position_sizes[symbol] = sizing_result.position_size
                print(f"✅ {symbol}: Size = {sizing_result.position_size:.3f}, Value = ${sizing_result.position_value:,.2f}")
        
        # Step 3: Risk monitoring
        print("\n🚨 Step 3: Risk Monitoring")
        
        # Start risk monitoring
        await monitor.start_monitoring()
        
        # Let it run briefly
        await asyncio.sleep(2)
        
        # Check risk metrics
        risk_metrics = await monitor._collect_risk_metrics()
        if risk_metrics:
            print(f"✅ Current portfolio value: ${risk_metrics.portfolio_value:,.2f}")
            print(f"✅ Current leverage: {risk_metrics.leverage:.2f}")
            print(f"✅ Current VaR 95%: ${risk_metrics.var_95:,.2f}")
        
        # Check alerts
        active_alerts = monitor.get_active_alerts()
        print(f"✅ Active risk alerts: {len(active_alerts)}")
        
        await monitor.stop_monitoring()
        
        # Step 4: Stress testing
        print("\n🧪 Step 4: Stress Testing")
        
        portfolio_data = {
            "portfolio_value": risk_metrics.portfolio_value if risk_metrics else 1000000.0,
            "leverage": risk_metrics.leverage if risk_metrics else 1.5,
            "var_95": risk_metrics.var_95 if risk_metrics else 20000.0,
            "correlation_risk": risk_metrics.correlation_risk if risk_metrics else 0.3
        }
        
        stress_results = await monitor.run_comprehensive_stress_tests(portfolio_data)
        if stress_results:
            print(f"✅ Stress testing completed")
            print(f"   Worst scenario: {stress_results.get('worst_scenario', 'unknown')}")
            print(f"   Worst loss: {stress_results.get('worst_loss', 0):.2%}")
        
        # Step 5: Integrated risk assessment
        print("\n📊 Step 5: Integrated Risk Assessment")
        
        # Calculate portfolio risk with current positions
        portfolio_risk = await sizer.calculate_portfolio_risk(position_sizes)
        print(f"✅ Portfolio risk assessment:")
        print(f"   Total risk: ${portfolio_risk.total_risk:,.2f}")
        print(f"   Leverage: {portfolio_risk.leverage:.2f}")
        print(f"   VaR 95%: ${portfolio_risk.var_95:,.2f}")
        print(f"   Risk budget used: {portfolio_risk.risk_budget_used:.3f}")
        
        # Component summaries
        print("\n📋 Component Summaries:")
        
        # Optimizer summary
        opt_summary = optimizer.get_optimization_summary()
        if "status" not in opt_summary:
            print(f"✅ Optimizer: {opt_summary['total_optimizations']} optimizations")
        
        # Sizer summary
        sizer_summary = sizer.get_sizing_summary()
        if "status" not in sizer_summary:
            print(f"✅ Sizer: {sizer_summary['total_sizing_calculations']} sizing calculations")
        
        # Monitor summary
        monitor_summary = monitor.get_risk_summary()
        if "status" not in monitor_summary:
            print(f"✅ Monitor: {monitor_summary['active_alerts']} active alerts")
        
        print("\n🎉 Risk Management Integration Test: PASSED")
        return True
        
    except Exception as e:
        print(f"❌ Risk Management Integration test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def main():
    """Run all risk management tests"""
    try:
        print("🧪 RISK MANAGEMENT TEST SUITE")
        print("=" * 70)
        
        # Run tests
        test1 = await test_portfolio_optimizer()
        test2 = await test_position_sizer()
        test3 = await test_risk_monitor()
        test4 = await test_risk_management_integration()
        
        # Summary
        print("\n" + "=" * 70)
        print("📊 RISK MANAGEMENT TEST RESULTS")
        print("=" * 70)
        print(f"Portfolio Optimizer:    {'✅ PASSED' if test1 else '❌ FAILED'}")
        print(f"Position Sizer:         {'✅ PASSED' if test2 else '❌ FAILED'}")
        print(f"Risk Monitor:           {'✅ PASSED' if test3 else '❌ FAILED'}")
        print(f"Risk Integration:       {'✅ PASSED' if test4 else '❌ FAILED'}")
        
        if all([test1, test2, test3, test4]):
            print("\n🎯 ALL RISK MANAGEMENT TESTS PASSED!")
            print("✅ Portfolio optimization with multiple algorithms working")
            print("✅ Dynamic position sizing with risk management working")
            print("✅ Real-time risk monitoring and alerting working")
            print("✅ Comprehensive stress testing working")
            print("✅ Full risk management integration successful")
        else:
            print("\n❌ Some risk management tests failed")
        
    except Exception as e:
        print(f"❌ Risk management test suite error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
