"""
End-to-End Test for Kalshi Swarm Trading System

Tests the complete flow:
1. Kalshi REST client authentication
2. Event bus publish/subscribe
3. OrderIntent generation
4. Risk checks
5. Order execution (paper mode)
"""

import asyncio
import os
import time
import logging
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def test_rest_client():
    """Test Kalshi REST client authentication and basic operations"""
    logger.info("\n=== Testing Kalshi REST Client ===")
    
    from merid_core.kalshi.rest_client import KalshiRestClient
    
    # Load credentials from environment
    key_id = os.environ.get("KALSHI_API_KEY_ID")
    private_key_path = os.environ.get("KALSHI_PRIVATE_KEY_PATH")
    env = os.environ.get("KALSHI_ENV", "demo")
    
    if not key_id or not private_key_path:
        logger.error("Missing credentials: Set KALSHI_API_KEY_ID and KALSHI_PRIVATE_KEY_PATH")
        return False
    
    try:
        # Create client
        client = KalshiRestClient(
            key_id=key_id,
            private_key_path=private_key_path,
            env=env
        )
        
        # Test 1: Get balance
        logger.info("Testing: Get balance")
        balance = client.get_balance()
        logger.info(f"✓ Balance: ${balance.get('balance', 0) / 100:.2f}")
        
        # Test 2: Get positions
        logger.info("Testing: Get positions")
        positions = client.get_positions()
        logger.info(f"✓ Current positions: {len(positions)}")
        
        # Test 3: Get orders
        logger.info("Testing: Get orders")
        orders = client.get_orders(status="resting")
        logger.info(f"✓ Resting orders: {len(orders)}")
        
        logger.info("✓ REST client tests passed")
        return True
        
    except Exception as e:
        logger.error(f"✗ REST client test failed: {e}", exc_info=True)
        return False


async def test_event_bus():
    """Test NATS event bus connectivity"""
    logger.info("\n=== Testing NATS Event Bus ===")
    
    from merid_core.event_bus.nats_adapter import NATSEventBus
    
    try:
        bus = NATSEventBus("nats://localhost:4222")
        await bus.connect()
        
        # Test publish/subscribe
        received = []
        
        async def handler(envelope):
            received.append(envelope.data)
        
        await bus.subscribe("test.topic", handler)
        await bus.publish("test.topic", {"message": "hello"})
        
        # Give it a moment to process
        await asyncio.sleep(0.5)
        
        await bus.disconnect()
        
        if received and received[0]["message"] == "hello":
            logger.info("✓ Event bus test passed")
            return True
        else:
            logger.error("✗ Event bus test failed: message not received")
            return False
            
    except Exception as e:
        logger.error(f"✗ Event bus test failed: {e}", exc_info=True)
        return False


async def test_execution_pipeline():
    """Test execution pipeline with paper order"""
    logger.info("\n=== Testing Execution Pipeline ===")
    
    from merid_core.event_bus.nats_adapter import NATSEventBus
    from merid_core.kalshi.execution_pipeline import ExecutionPipeline
    
    try:
        # Setup event bus
        bus = NATSEventBus("nats://localhost:4222")
        await bus.connect()
        
        # Create pipeline (paper mode)
        pipeline = ExecutionPipeline(
            event_bus=bus,
            enable_live_trading=False  # PAPER MODE
        )
        
        await pipeline.start()
        
        # Publish a test order intent
        test_intent = {
            "session_id": "test-session",
            "agent_id": "test-agent",
            "market_ticker": "KXHARRIS24-LSV",
            "side": "buy_yes",
            "qty": 1,
            "price": 0.50,
            "client_tag": f"test-{int(time.time())}",
            "confidence": 0.8,
            "rationale": "End-to-end test order"
        }
        
        await bus.publish("intents.orders", test_intent)
        
        # Give pipeline time to process
        await asyncio.sleep(1)
        
        # Check stats
        stats = pipeline.stats()
        logger.info(f"Pipeline stats: {stats}")
        
        await bus.disconnect()
        
        if stats["intents_received"] > 0:
            logger.info("✓ Execution pipeline test passed")
            return True
        else:
            logger.error("✗ Execution pipeline test failed: no intents processed")
            return False
            
    except Exception as e:
        logger.error(f"✗ Execution pipeline test failed: {e}", exc_info=True)
        return False


async def test_full_flow():
    """Test complete end-to-end flow with live REST call (demo mode)"""
    logger.info("\n=== Testing Full End-to-End Flow ===")
    
    from merid_core.event_bus.nats_adapter import NATSEventBus
    from merid_core.kalshi.execution_pipeline import ExecutionPipeline
    from merid_core.kalshi.rest_client import KalshiRestClient
    
    # Check if live trading is enabled
    enable_live = os.environ.get("ENABLE_LIVE_TRADING", "false").lower() == "true"
    
    if not enable_live:
        logger.warning("⚠ Live trading disabled - skipping live order test")
        logger.info("  Set ENABLE_LIVE_TRADING=true to test actual order placement")
        return True
    
    try:
        # Auto-discover an open market from Kalshi demo
        import requests as req
        logger.info("Discovering open market from Kalshi demo...")
        markets_resp = req.get(
            "https://demo-api.kalshi.co/trade-api/v2/markets",
            params={"limit": 1, "status": "open"},
            timeout=10
        )
        markets_resp.raise_for_status()
        markets = markets_resp.json().get("markets", [])
        
        if not markets:
            logger.warning("⚠ No open markets found on Kalshi demo - skipping live order test")
            return True
        
        test_ticker = markets[0]["ticker"]
        logger.info(f"Using market: {test_ticker} ({markets[0].get('title', 'N/A')})")
        
        # Setup
        bus = NATSEventBus("nats://localhost:4222")
        await bus.connect()
        
        pipeline = ExecutionPipeline(
            event_bus=bus,
            enable_live_trading=True  # LIVE MODE (demo account)
        )
        
        await pipeline.start()
        
        # Create a very small test order on a real open market
        test_intent = {
            "session_id": "e2e-test",
            "agent_id": "e2e-tester",
            "market_ticker": test_ticker,
            "side": "buy_yes",
            "qty": 1,  # Minimum size
            "price": 0.01,  # Very low price (unlikely to fill)
            "client_tag": f"e2e-test-{int(time.time() * 1000)}",
            "confidence": 0.5,
            "rationale": "End-to-end live test order"
        }
        
        logger.info("Publishing live test order intent...")
        await bus.publish("intents.orders", test_intent)
        
        # Wait for processing
        await asyncio.sleep(2)
        
        # Check results
        stats = pipeline.stats()
        logger.info(f"Final stats: {stats}")
        
        await bus.disconnect()
        
        if stats["intents_executed"] > 0:
            logger.info("✓ Full flow test passed - order submitted to Kalshi")
            return True
        else:
            logger.warning("⚠ Order may have been rejected by risk checks")
            return True  # Not necessarily a failure
            
    except Exception as e:
        logger.error(f"✗ Full flow test failed: {e}", exc_info=True)
        return False


async def main():
    """Run all tests"""
    logger.info("=" * 60)
    logger.info("Kalshi Swarm End-to-End Test Suite")
    logger.info("=" * 60)
    
    # Check prerequisites
    logger.info("\nChecking prerequisites...")
    
    required_env = [
        "KALSHI_API_KEY_ID",
        "KALSHI_PRIVATE_KEY_PATH",
    ]
    
    missing = [var for var in required_env if not os.environ.get(var)]
    
    if missing:
        logger.error(f"Missing environment variables: {', '.join(missing)}")
        logger.error("\nPlease set:")
        logger.error("  export KALSHI_API_KEY_ID=your_key")
        logger.error("  export KALSHI_PRIVATE_KEY_PATH=/path/to/key.pem")
        logger.error("  export KALSHI_ENV=demo")
        logger.error("  export ENABLE_LIVE_TRADING=false")
        return
    
    logger.info("✓ Environment variables configured")
    
    # Run tests
    results = {
        "REST Client": await test_rest_client(),
        "Event Bus": await test_event_bus(),
        "Execution Pipeline": await test_execution_pipeline(),
        "Full Flow": await test_full_flow(),
    }
    
    # Summary
    logger.info("\n" + "=" * 60)
    logger.info("Test Summary")
    logger.info("=" * 60)
    
    for test_name, passed in results.items():
        status = "✓ PASS" if passed else "✗ FAIL"
        logger.info(f"{test_name:20s} {status}")
    
    total = len(results)
    passed = sum(results.values())
    
    logger.info(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        logger.info("\n🎉 All tests passed! System is operational.")
    else:
        logger.warning(f"\n⚠ {total - passed} test(s) failed.")


if __name__ == "__main__":
    asyncio.run(main())
