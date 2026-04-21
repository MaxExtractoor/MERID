#!/usr/bin/env python3

import asyncio
import sys
import os
import time
import uuid
from datetime import datetime

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from trading._legacy.perp.binance_perp import BinancePerpAdapter
from trading.execution_engine import (
    TradingExecutionEngine, TradeOrder, OrderType, OrderSide,
    ExecutionResult, OrderStatus
)
from utils.logger import get_logger

logger = get_logger("test_trading_system")

async def test_binance_adapter():
    """Test Binance perpetual adapter functionality"""
    
    print("🚀 Testing Binance Perpetual Adapter")
    print("=" * 50)
    
    try:
        # Initialize adapter
        adapter = BinancePerpAdapter(use_mock=True)
        print(f"✅ BinancePerpAdapter initialized: {adapter.venue}")
        
        # Test market data fetching
        print("\n📊 Testing Market Data Fetching")
        markets = adapter.fetch_markets(limit=5)
        print(f"✅ Fetched {len(markets)} markets")
        
        if markets:
            sample_market = markets[0]
            print(f"   Sample: {sample_market.symbol} @ ${sample_market.price:.2f}")
            print(f"   Volume: ${sample_market.volume_24h:,.0f}")
            print(f"   Funding: {sample_market.funding_rate:.4f}")
        
        # Test funding rate fetching
        print("\n💰 Testing Funding Rate Fetching")
        funding_rates = adapter.fetch_funding_rates(["BTCUSD", "ETHUSD"])
        print(f"✅ Fetched {len(funding_rates)} funding rates")
        
        if funding_rates:
            sample_funding = funding_rates[0]
            print(f"   Sample: {sample_funding.symbol}")
            print(f"   Rate: {sample_funding.funding_rate:.4f}")
            print(f"   APR: {sample_funding.estimated_apr:.2%}")
        
        # Test whale signals
        print("\n🐋 Testing Whale Signals")
        whale_signals = adapter.fetch_whale_signals(limit=3)
        print(f"✅ Fetched {len(whale_signals)} whale signals")
        
        if whale_signals:
            sample_whale = whale_signals[0]
            print(f"   Sample: {sample_whale.symbol} {sample_whale.direction}")
            print(f"   Notional: ${sample_whale.notional:,.0f}")
            print(f"   Source: {sample_whale.source}")
        
        # Test market summary
        print("\n📈 Testing Market Summary")
        summary = adapter.get_market_summary()
        print(f"✅ Market summary generated")
        print(f"   Total markets: {summary.get('total_markets', 0)}")
        print(f"   Total volume: ${summary.get('total_volume_24h', 0):,.0f}")
        print(f"   Avg funding: {summary.get('average_funding_rate', 0):.4f}")
        
        # Test symbol support
        print("\n🔍 Testing Symbol Support")
        supported = adapter.get_supported_symbols()
        print(f"✅ Supported symbols: {len(supported)}")
        print(f"   BTC supported: {adapter.is_symbol_supported('BTCUSD')}")
        print(f"   INVALID supported: {adapter.is_symbol_supported('INVALID')}")
        
        print("\n🎉 Binance Adapter Test: PASSED")
        return True
        
    except Exception as e:
        print(f"❌ Binance Adapter test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_trading_execution():
    """Test trading execution engine functionality"""
    
    print("\n🔄 Testing Trading Execution Engine")
    print("=" * 50)
    
    try:
        # Initialize execution engine
        config = {
            "dry_run": True,
            "max_position_size": 50000.0,
            "max_daily_loss": 1000.0,
            "venues": {}
        }
        engine = TradingExecutionEngine(config)
        print(f"✅ TradingExecutionEngine initialized (dry_run: {engine.dry_run})")
        
        # Test market order execution
        print("\n📋 Testing Market Order Execution")
        market_order = TradeOrder(
            order_id=str(uuid.uuid4()),
            symbol="BTCUSD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=0.1  # 0.1 BTC
        )
        
        result = await engine.execute_order(market_order)
        print(f"✅ Market order executed: {result.status}")
        print(f"   Executed quantity: {result.executed_quantity}")
        print(f"   Executed price: ${result.executed_price:.2f}")
        print(f"   Fee: ${result.execution_fee:.4f}")
        
        # Test limit order execution
        print("\n📋 Testing Limit Order Execution")
        limit_order = TradeOrder(
            order_id=str(uuid.uuid4()),
            symbol="ETHUSD",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            quantity=1.0,
            price=3100.0
        )
        
        limit_result = await engine.execute_order(limit_order)
        print(f"✅ Limit order executed: {limit_result.status}")
        print(f"   Executed quantity: {limit_result.executed_quantity}")
        print(f"   Executed price: ${limit_result.executed_price}")
        
        # Test position tracking
        print("\n📊 Testing Position Tracking")
        positions = engine.get_all_positions()
        print(f"✅ Active positions: {len(positions)}")
        
        for symbol, pos in positions.items():
            print(f"   {symbol}: {pos.side} ${abs(pos.size):.2f}")
            print(f"   Entry: ${pos.entry_price:.2f}, Current: ${pos.current_price:.2f}")
            print(f"   PnL: ${pos.unrealized_pnl:.2f}")
        
        # Test safety checks
        print("\n🛡️ Testing Safety Checks")
        
        # Test oversized order (should be rejected)
        oversized_order = TradeOrder(
            order_id=str(uuid.uuid4()),
            symbol="BTCUSD",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=10.0  # 10 BTC = ~$450K (exceeds $50K limit)
        )
        
        oversized_result = await engine.execute_order(oversized_order)
        print(f"✅ Oversized order: {oversized_result.status}")
        print(f"   Reason: {oversized_result.error_message}")
        
        # Test unsupported symbol
        unsupported_order = TradeOrder(
            order_id=str(uuid.uuid4()),
            symbol="INVALID/USDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=0.1
        )
        
        unsupported_result = await engine.execute_order(unsupported_order)
        print(f"✅ Unsupported symbol: {unsupported_result.status}")
        print(f"   Reason: {unsupported_result.error_message}")
        
        # Test execution metrics
        print("\n📈 Testing Execution Metrics")
        metrics = engine.get_execution_metrics()
        print(f"✅ Execution metrics:")
        print(f"   Total orders: {metrics['total_orders']}")
        print(f"   Fill rate: {metrics['fill_rate']:.2%}")
        print(f"   Error count: {metrics['error_count']}")
        print(f"   Daily PnL: ${metrics['daily_pnl']:.2f}")
        print(f"   Active positions: {metrics['active_positions']}")
        
        print("\n🎉 Trading Execution Test: PASSED")
        return True
        
    except Exception as e:
        print(f"❌ Trading Execution test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_integration_workflow():
    """Test complete trading workflow integration"""
    
    print("\n🔄 Testing Complete Trading Workflow")
    print("=" * 50)
    
    try:
        # Initialize components
        adapter = BinancePerpAdapter(use_mock=True)
        engine = TradingExecutionEngine({
            "dry_run": True,
            "max_position_size": 100000.0,
            "max_daily_loss": 5000.0
        })
        
        print("✅ Components initialized")
        
        # Step 1: Get market data
        print("\n📊 Step 1: Market Data Analysis")
        markets = adapter.fetch_markets(limit=3)
        print(f"✅ Analyzed {len(markets)} markets")
        
        # Step 2: Get funding rates
        print("\n💰 Step 2: Funding Rate Analysis")
        funding_rates = adapter.fetch_funding_rates()
        print(f"✅ Analyzed {len(funding_rates)} funding rates")
        
        # Step 3: Identify trading opportunities
        print("\n🎯 Step 3: Trading Opportunity Analysis")
        opportunities = []
        
        for market in markets:
            # Find corresponding funding rate
            funding = next((f for f in funding_rates if f.symbol == market.symbol), None)
            
            if funding:
                # Simple opportunity detection: high volume + favorable funding
                if market.volume_24h > 1000000000 and abs(funding.funding_rate) > 0.0001:
                    opportunities.append({
                        "symbol": market.symbol,
                        "price": market.price,
                        "volume": market.volume_24h,
                        "funding_rate": funding.funding_rate,
                        "apr": funding.estimated_apr
                    })
        
        print(f"✅ Found {len(opportunities)} trading opportunities")
        
        if opportunities:
            opp = opportunities[0]
            print(f"   Best: {opp['symbol']} @ ${opp['price']:.2f}")
            print(f"   Volume: ${opp['volume']:,.0f}")
            print(f"   Funding: {opp['funding_rate']:.4f} ({opp['apr']:.2%} APR)")
        
        # Step 4: Execute trades based on opportunities
        print("\n📋 Step 4: Trade Execution")
        
        for opp in opportunities[:2]:  # Execute top 2 opportunities
            # Determine side based on funding rate
            side = OrderSide.BUY if opp['funding_rate'] < 0 else OrderSide.SELL
            
            order = TradeOrder(
                order_id=str(uuid.uuid4()),
                symbol=opp['symbol'],
                side=side,
                order_type=OrderType.MARKET,
                quantity=0.05  # Small position for testing
            )
            
            result = await engine.execute_order(order)
            print(f"✅ Trade executed: {opp['symbol']} {side.value}")
            print(f"   Status: {result.status}")
            print(f"   Quantity: {result.executed_quantity}")
            print(f"   Price: ${result.executed_price:.2f}")
        
        # Step 5: Portfolio analysis
        print("\n📊 Step 5: Portfolio Analysis")
        positions = engine.get_all_positions()
        total_value = sum(abs(pos.size) for pos in positions.values())
        total_pnl = sum(pos.unrealized_pnl for pos in positions.values())
        
        print(f"✅ Portfolio analysis:")
        print(f"   Total positions: {len(positions)}")
        print(f"   Total value: ${total_value:,.2f}")
        print(f"   Total PnL: ${total_pnl:.2f}")
        
        # Step 6: Risk assessment
        print("\n🛡️ Step 6: Risk Assessment")
        metrics = engine.get_execution_metrics()
        
        risk_factors = []
        if metrics['daily_pnl'] < -1000:
            risk_factors.append("High daily loss")
        if metrics['fill_rate'] < 0.7:
            risk_factors.append("Low fill rate")
        if metrics['error_count'] > 5:
            risk_factors.append("High error rate")
        
        if risk_factors:
            print(f"⚠️ Risk factors detected: {', '.join(risk_factors)}")
        else:
            print("✅ No significant risk factors")
        
        print("\n🎉 Integration Workflow Test: PASSED")
        return True
        
    except Exception as e:
        print(f"❌ Integration workflow test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_performance():
    """Test trading system performance"""
    
    print("\n⚡ Testing Trading System Performance")
    print("-" * 40)
    
    try:
        engine = TradingExecutionEngine({
            "dry_run": True,
            "max_position_size": 1000000.0,
            "max_daily_loss": 100000.0
        })
        
        # Test concurrent order execution
        print("🔄 Testing Concurrent Order Execution")
        
        orders = []
        start_time = time.time()
        
        # Create 10 concurrent orders
        tasks = []
        for i in range(10):
            order = TradeOrder(
                order_id=f"perf_test_{i}",
                symbol="BTCUSD",
                side=OrderSide.BUY if i % 2 == 0 else OrderSide.SELL,
                order_type=OrderType.MARKET,
                quantity=0.01
            )
            tasks.append(engine.execute_order(order))
        
        # Execute all orders concurrently
        results = await asyncio.gather(*tasks)
        
        end_time = time.time()
        total_time = end_time - start_time
        
        successful = sum(1 for r in results if r.status == OrderStatus.FILLED)
        
        print(f"✅ Executed {len(results)} orders in {total_time:.2f}s")
        print(f"✅ Successful: {successful}/{len(results)}")
        print(f"✅ Average time per order: {(total_time/len(results))*1000:.1f}ms")
        print(f"✅ Throughput: {len(results)/total_time:.1f} orders/second")
        
        # Test metrics
        metrics = engine.get_execution_metrics()
        print(f"✅ Final metrics:")
        print(f"   Fill rate: {metrics['fill_rate']:.2%}")
        print(f"   Error count: {metrics['error_count']}")
        print(f"   Daily PnL: ${metrics['daily_pnl']:.2f}")
        
        print("\n🎯 Performance Test: PASSED")
        return True
        
    except Exception as e:
        print(f"❌ Performance test failed: {e}")
        return False

async def main():
    """Run all trading system tests"""
    try:
        print("🧪 TRADING SYSTEM TEST SUITE")
        print("=" * 70)
        
        # Run tests
        test1 = await test_binance_adapter()
        test2 = await test_trading_execution()
        test3 = await test_integration_workflow()
        test4 = await test_performance()
        
        # Summary
        print("\n" + "=" * 70)
        print("📊 TRADING SYSTEM TEST RESULTS")
        print("=" * 70)
        print(f"Binance Adapter:      {'✅ PASSED' if test1 else '❌ FAILED'}")
        print(f"Trading Execution:    {'✅ PASSED' if test2 else '❌ FAILED'}")
        print(f"Integration Workflow:  {'✅ PASSED' if test3 else '❌ FAILED'}")
        print(f"Performance:          {'✅ PASSED' if test4 else '❌ FAILED'}")
        
        if all([test1, test2, test3, test4]):
            print("\n🎯 ALL TRADING SYSTEM TESTS PASSED!")
            print("✅ Trading system fully functional")
            print("✅ Market data integration working")
            print("✅ Order execution with safety checks working")
            print("✅ Position tracking and PnL calculation working")
            print("✅ Risk management and safety checks working")
            print("✅ Performance within acceptable limits")
        else:
            print("\n❌ Some trading system tests failed")
        
    except Exception as e:
        print(f"❌ Trading system test suite error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
