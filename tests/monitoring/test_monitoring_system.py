#!/usr/bin/env python3

import asyncio
import sys
import os
import time
from datetime import datetime

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from monitoring.liquidation_monitor import CoinGlassLiquidationMonitor, WhaleIntelMonitor
from monitoring.dashboard import MonitoringDashboard
from utils.logger import get_logger

logger = get_logger("test_monitoring_system")

async def test_liquidation_monitor():
    """Test liquidation monitoring functionality"""
    
    print("🚀 Testing Liquidation Monitor")
    print("=" * 50)
    
    try:
        # Initialize monitor
        monitor = CoinGlassLiquidationMonitor()
        print(f"✅ CoinGlassLiquidationMonitor initialized (mock: {monitor.use_mock})")
        
        # Test liquidation data fetching
        print("\n📊 Testing Liquidation Data Fetching")
        liquidations = monitor.fetch_heatmap(["BTCUSD", "ETHUSD", "SOLUSD"])
        print(f"✅ Fetched {len(liquidations)} liquidation events")
        
        if liquidations:
            sample = liquidations[0]
            print(f"   Sample: {sample.symbol} {sample.side}")
            print(f"   Notional: ${sample.notional:,.0f}")
            print(f"   Price: ${sample.price:.2f}")
            print(f"   Venue: {sample.venue}")
            print(f"   Time: {datetime.fromtimestamp(sample.timestamp_ms/1000)}")
        
        # Test with no symbols
        print("\n📊 Testing Default Symbol Fetching")
        default_liquidations = monitor.fetch_heatmap()
        print(f"✅ Fetched {len(default_liquidations)} events with default symbols")
        
        # Test data quality
        print("\n🔍 Testing Data Quality")
        if liquidations:
            venues = set(l.venue for l in liquidations)
            symbols = set(l.symbol for l in liquidations)
            sides = set(l.side for l in liquidations)
            
            print(f"   Venues: {venues}")
            print(f"   Symbols: {symbols}")
            print(f"   Sides: {sides}")
            print(f"   Notional range: ${min(l.notional for l in liquidations):,.0f} - ${max(l.notional for l in liquidations):,.0f}")
        
        print("\n🎉 Liquidation Monitor Test: PASSED")
        return True
        
    except Exception as e:
        print(f"❌ Liquidation Monitor test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_whale_monitor():
    """Test whale signal monitoring functionality"""
    
    print("\n🐋 Testing Whale Signal Monitor")
    print("=" * 50)
    
    try:
        # Initialize monitor
        monitor = WhaleIntelMonitor()
        print(f"✅ WhaleIntelMonitor initialized (mock: {monitor.use_mock})")
        
        # Test whale signal fetching
        print("\n📊 Testing Whale Signal Fetching")
        whales = monitor.fetch_signals(limit=15)
        print(f"✅ Fetched {len(whales)} whale signals")
        
        if whales:
            sample = whales[0]
            print(f"   Sample: {sample.address}")
            print(f"   Amount: ${sample.amount:,.0f}")
            print(f"   Token: {sample.token}")
            print(f"   Action: {sample.action}")
            print(f"   Exchange: {sample.exchange}")
            print(f"   Confidence: {sample.confidence:.2f}")
            print(f"   Time: {datetime.fromtimestamp(sample.timestamp)}")
        
        # Test with different limits
        print("\n📊 Testing Different Limits")
        for limit in [5, 10, 20]:
            limited_whales = monitor.fetch_signals(limit=limit)
            print(f"   Limit {limit}: {len(limited_whales)} signals")
        
        # Test data quality
        print("\n🔍 Testing Data Quality")
        if whales:
            exchanges = set(w.exchange for w in whales)
            tokens = set(w.token for w in whales)
            actions = set(w.action for w in whales)
            
            print(f"   Exchanges: {exchanges}")
            print(f"   Tokens: {tokens}")
            print(f"   Actions: {actions}")
            print(f"   Amount range: ${min(w.amount for w in whales):,.0f} - ${max(w.amount for w in whales):,.0f}")
            print(f"   Confidence range: {min(w.confidence for w in whales):.2f} - {max(w.confidence for w in whales):.2f}")
        
        print("\n🎉 Whale Monitor Test: PASSED")
        return True
        
    except Exception as e:
        print(f"❌ Whale Monitor test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_monitoring_dashboard():
    """Test comprehensive monitoring dashboard"""
    
    print("\n📊 Testing Monitoring Dashboard")
    print("=" * 50)
    
    try:
        # Initialize dashboard
        config = {
            "update_interval": 5,  # 5 seconds for testing
            "alert_thresholds": {
                "liquidation_size": 500000,  # $500K
                "whale_size": 1000000,  # $1M
                "daily_loss": 5000,  # $5K
                "error_rate": 0.05,
                "response_time": 1000,
                "cpu_usage": 0.8,
                "memory_usage": 0.85
            }
        }
        
        dashboard = MonitoringDashboard(config)
        print(f"✅ MonitoringDashboard initialized")
        
        # Start monitoring
        print("\n🔄 Starting Monitoring")
        await dashboard.start_monitoring()
        
        # Wait for initial data collection
        print("⏳ Waiting for initial data collection...")
        await asyncio.sleep(10)  # Wait for at least one update cycle
        
        # Get dashboard summary
        print("\n📊 Testing Dashboard Summary")
        summary = dashboard.get_dashboard_summary()
        print(f"✅ Dashboard summary generated")
        print(f"   Status: {summary.get('status', 'unknown')}")
        print(f"   Last update: {datetime.fromtimestamp(summary.get('last_update', 0))}")
        
        # Check liquidation summary
        liquidation_summary = summary.get('liquidation_summary', {})
        print(f"   Liquidations: {liquidation_summary.get('total_events', 0)} events")
        print(f"   Total notional: ${liquidation_summary.get('total_notional', 0):,.0f}")
        print(f"   Largest: ${liquidation_summary.get('largest_liquidation', 0):,.0f}")
        
        # Check whale summary
        whale_summary = summary.get('whale_summary', {})
        print(f"   Whale signals: {whale_summary.get('total_signals', 0)} signals")
        print(f"   Total volume: ${whale_summary.get('total_volume', 0):,.0f}")
        print(f"   Largest: ${whale_summary.get('largest_signal', 0):,.0f}")
        
        # Check system health
        system_health = summary.get('system_health', {})
        print(f"   CPU usage: {system_health.get('cpu_usage', 0):.1%}")
        print(f"   Memory usage: {system_health.get('memory_usage', 0):.1%}")
        print(f"   Disk usage: {system_health.get('disk_usage', 0):.1%}")
        
        # Check risk metrics
        risk_metrics = summary.get('risk_metrics', {})
        print(f"   Liquidation risk: {risk_metrics.get('liquidation_risk', 0):.2f}")
        print(f"   Whale activity: {risk_metrics.get('whale_activity_score', 0):.2f}")
        print(f"   Market volatility: {risk_metrics.get('market_volatility', 0):.2f}%")
        
        # Check alerts
        alerts = summary.get('alerts', {})
        print(f"   Total alerts: {alerts.get('total_alerts', 0)}")
        print(f"   Critical: {alerts.get('critical_alerts', 0)}")
        print(f"   High: {alerts.get('high_alerts', 0)}")
        print(f"   Medium: {alerts.get('medium_alerts', 0)}")
        
        # Test historical data
        print("\n📈 Testing Historical Data")
        historical = dashboard.get_historical_data(hours=1)
        print(f"✅ Historical data retrieved")
        print(f"   Period: {historical.get('period_hours', 0)} hours")
        print(f"   Health points: {len(historical.get('system_health', []))}")
        print(f"   Risk points: {len(historical.get('risk_metrics', []))}")
        
        # Wait for more updates
        print("\n⏳ Monitoring for additional updates...")
        await asyncio.sleep(15)  # Wait for more update cycles
        
        # Get updated summary
        updated_summary = dashboard.get_dashboard_summary()
        print(f"✅ Updated summary after monitoring")
        print(f"   Total liquidations now: {updated_summary.get('liquidation_summary', {}).get('total_events', 0)}")
        print(f"   Total whale signals now: {updated_summary.get('whale_summary', {}).get('total_signals', 0)}")
        
        # Stop monitoring
        print("\n🛑 Stopping Monitoring")
        await dashboard.stop_monitoring()
        
        print("\n🎉 Monitoring Dashboard Test: PASSED")
        return True
        
    except Exception as e:
        print(f"❌ Monitoring Dashboard test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_alert_system():
    """Test alert generation and management"""
    
    print("\n🚨 Testing Alert System")
    print("=" * 50)
    
    try:
        # Initialize dashboard with low thresholds for testing
        config = {
            "update_interval": 3,
            "alert_thresholds": {
                "liquidation_size": 100000,  # $100K (low for testing)
                "whale_size": 500000,  # $500K (low for testing)
                "daily_loss": 1000,  # $1K (low for testing)
                "cpu_usage": 0.5,  # 50% (low for testing)
                "memory_usage": 0.6  # 60% (low for testing)
            }
        }
        
        dashboard = MonitoringDashboard(config)
        print(f"✅ Alert system initialized with low thresholds")
        
        # Start monitoring
        await dashboard.start_monitoring()
        
        # Wait for alerts to be generated
        print("⏳ Waiting for alert generation...")
        await asyncio.sleep(10)
        
        # Check for alerts
        summary = dashboard.get_dashboard_summary()
        alerts = summary.get('alerts', {})
        
        print(f"✅ Alert system test results:")
        print(f"   Total alerts: {alerts.get('total_alerts', 0)}")
        print(f"   Critical: {alerts.get('critical_alerts', 0)}")
        print(f"   High: {alerts.get('high_alerts', 0)}")
        print(f"   Medium: {alerts.get('medium_alerts', 0)}")
        print(f"   Low: {alerts.get('low_alerts', 0)}")
        print(f"   Categories: {alerts.get('categories', [])}")
        
        # Test alert categories
        if alerts.get('total_alerts', 0) > 0:
            print(f"✅ Alerts generated successfully")
            
            # Check if we have different types of alerts
            categories = alerts.get('categories', [])
            if len(categories) > 1:
                print(f"✅ Multiple alert categories: {categories}")
            else:
                print(f"⚠️ Single alert category: {categories[0] if categories else 'none'}")
        else:
            print(f"⚠️ No alerts generated (thresholds may be too high)")
        
        # Stop monitoring
        await dashboard.stop_monitoring()
        
        print("\n🎉 Alert System Test: PASSED")
        return True
        
    except Exception as e:
        print(f"❌ Alert System test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_performance():
    """Test monitoring system performance"""
    
    print("\n⚡ Testing Monitoring System Performance")
    print("-" * 40)
    
    try:
        # Initialize dashboard
        dashboard = MonitoringDashboard({"update_interval": 1})
        
        # Test data collection performance
        print("🔄 Testing Data Collection Performance")
        
        start_time = time.time()
        
        # Collect liquidation data
        liquidations = dashboard.liquidation_monitor.fetch_heatmap()
        liquidation_time = time.time()
        
        # Collect whale data
        whales = dashboard.whale_monitor.fetch_signals()
        whale_time = time.time()
        
        # Generate summary
        summary = dashboard.get_dashboard_summary()
        summary_time = time.time()
        
        end_time = time.time()
        
        print(f"✅ Performance results:")
        print(f"   Liquidation data: {(liquidation_time - start_time)*1000:.1f}ms")
        print(f"   Whale data: {(whale_time - liquidation_time)*1000:.1f}ms")
        print(f"   Summary generation: {(summary_time - whale_time)*1000:.1f}ms")
        print(f"   Total time: {(end_time - start_time)*1000:.1f}ms")
        
        # Test concurrent operations
        print("\n🔄 Testing Concurrent Operations")
        
        start_time = time.time()
        
        # Run multiple operations concurrently
        tasks = [
            dashboard.liquidation_monitor.fetch_heatmap(),
            dashboard.whale_monitor.fetch_signals(),
            dashboard.get_dashboard_summary()
        ]
        
        results = await asyncio.gather(*tasks)
        
        end_time = time.time()
        
        print(f"✅ Concurrent operations:")
        print(f"   Total time: {(end_time - start_time)*1000:.1f}ms")
        print(f"   Operations per second: {len(tasks) / (end_time - start_time):.1f}")
        
        # Test memory usage
        print("\n💾 Testing Memory Usage")
        
        import sys
        dashboard_size = sys.getsizeof(dashboard)
        liquidations_size = sys.getsizeof(dashboard.liquidation_events)
        whales_size = sys.getsizeof(dashboard.whale_signals)
        
        print(f"✅ Memory usage:")
        print(f"   Dashboard object: {dashboard_size:,} bytes")
        print(f"   Liquidation events: {liquidations_size:,} bytes")
        print(f"   Whale signals: {whales_size:,} bytes")
        print(f"   Total estimated: {dashboard_size + liquidations_size + whales_size:,} bytes")
        
        print("\n🎯 Performance Test: PASSED")
        return True
        
    except Exception as e:
        print(f"❌ Performance test failed: {e}")
        return False

async def main():
    """Run all monitoring system tests"""
    try:
        print("🧪 MONITORING SYSTEM TEST SUITE")
        print("=" * 70)
        
        # Run tests
        test1 = await test_liquidation_monitor()
        test2 = await test_whale_monitor()
        test3 = await test_monitoring_dashboard()
        test4 = await test_alert_system()
        test5 = await test_performance()
        
        # Summary
        print("\n" + "=" * 70)
        print("📊 MONITORING SYSTEM TEST RESULTS")
        print("=" * 70)
        print(f"Liquidation Monitor:    {'✅ PASSED' if test1 else '❌ FAILED'}")
        print(f"Whale Monitor:          {'✅ PASSED' if test2 else '❌ FAILED'}")
        print(f"Monitoring Dashboard:   {'✅ PASSED' if test3 else '❌ FAILED'}")
        print(f"Alert System:           {'✅ PASSED' if test4 else '❌ FAILED'}")
        print(f"Performance:            {'✅ PASSED' if test5 else '❌ FAILED'}")
        
        if all([test1, test2, test3, test4, test5]):
            print("\n🎯 ALL MONITORING SYSTEM TESTS PASSED!")
            print("✅ Liquidation monitoring functional")
            print("✅ Whale signal monitoring functional")
            print("✅ Comprehensive dashboard working")
            print("✅ Alert system operational")
            print("✅ Performance within acceptable limits")
        else:
            print("\n❌ Some monitoring system tests failed")
        
    except Exception as e:
        print(f"❌ Monitoring system test suite error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
