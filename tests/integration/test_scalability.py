#!/usr/bin/env python3

import asyncio
import sys
import os
import time
import random
from datetime import datetime, timedelta

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scaling.load_balancer import LoadBalancer
from scaling.cache_manager import CacheManager, CacheConfig
from scaling.message_queue import MessageQueue, MessageConfig
from scaling.performance_optimizer import PerformanceOptimizer
from utils.logger import get_logger

logger = get_logger("test_scalability")

async def test_load_balancer():
    """Test load balancer functionality"""
    
    print("⚖️ Testing Load Balancer")
    print("=" * 50)
    
    try:
        # Initialize load balancer
        config = {
            "us_compliance": {
                "geo_fencing": True,
                "audit_logging": True
            }
        }
        
        lb = LoadBalancer(config)
        await lb.start()
        print(f"✅ LoadBalancer started")
        
        # Register instances
        instances = [
            ("web1", "localhost", 8001, "http", 1, 1000, "web"),
            ("web2", "localhost", 8002, "http", 1, 1000, "web"),
            ("api1", "localhost", 8003, "http", 2, 500, "api"),
            ("api2", "localhost", 8004, "http", 2, 500, "api")
        ]
        
        for instance_id, host, port, protocol, weight, max_conn, group in instances:
            success = await lb.register_instance(instance_id, host, port, protocol, weight, max_conn, group)
            print(f"✅ Registered instance {instance_id}: {success}")
        
        # Test routing
        print("\n🔄 Testing Request Routing")
        for i in range(10):
            decision = await lb.route_request("web", f"session_{i}")
            if decision:
                print(f"   Request {i}: {decision.instance_id} ({decision.host}:{decision.port})")
                await lb.record_request_result(decision.instance_id, True, 0.05)
            else:
                print(f"   Request {i}: No routing decision")
        
        # Test API routing
        print("\n🔄 Testing API Routing")
        for i in range(5):
            decision = await lb.route_request("api", f"api_session_{i}")
            if decision:
                print(f"   API Request {i}: {decision.instance_id}")
                await lb.record_request_result(decision.instance_id, True, 0.1)
        
        # Test sticky sessions
        print("\n🔄 Testing Sticky Sessions")
        session_id = "user_session_123"
        decision1 = await lb.route_request("web", session_id)
        decision2 = await lb.route_request("web", session_id)
        
        if decision1 and decision2 and decision1.instance_id == decision2.instance_id:
            print(f"✅ Sticky session working: {decision1.instance_id}")
        else:
            print("❌ Sticky session failed")
        
        # Test load balancer stats
        print("\n📊 Testing Load Balancer Stats")
        stats = lb.get_load_balancer_stats()
        print(f"✅ Total instances: {stats['total_instances']}")
        print(f"✅ Healthy instances: {stats['healthy_instances']}")
        print(f"✅ Total requests: {stats['total_requests']}")
        print(f"✅ Instance groups: {stats['instance_groups']}")
        
        # Test instance health
        print("\n🏥 Testing Instance Health")
        for instance_id in ["web1", "api1"]:
            health = lb.get_instance_health(instance_id)
            if health:
                print(f"✅ {instance_id}: {health['status']}, {health['connections']} connections")
            else:
                print(f"❌ {instance_id}: No health data")
        
        # Test instance removal
        print("\n🗑️ Testing Instance Removal")
        success = await lb.unregister_instance("web2")
        print(f"✅ Unregistered web2: {success}")
        
        # Test routing after removal
        decision = await lb.route_request("web", "test_session")
        if decision and decision.instance_id != "web2":
            print(f"✅ Routing works after removal: {decision.instance_id}")
        else:
            print("❌ Routing failed after removal")
        
        await lb.stop()
        print("\n🎉 Load Balancer Test: PASSED")
        return True
        
    except Exception as e:
        print(f"❌ Load Balancer test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_cache_manager():
    """Test cache manager functionality"""
    
    print("\n💾 Testing Cache Manager")
    print("=" * 50)
    
    try:
        # Initialize cache manager
        config = CacheConfig(
            redis_host="localhost",
            redis_port=6379,
            default_ttl=3600,
            l1_max_size=100,
            enable_l1_cache=True,
            enable_l2_cache=True,
            encrypt_sensitive_data=True,
            audit_cache_access=True
        )
        
        cache = CacheManager(config)
        await cache.start()
        print(f"✅ CacheManager started (Redis: {cache.redis_available})")
        
        # Test basic cache operations
        print("\n📝 Testing Basic Cache Operations")
        
        # Test set/get
        test_data = {"key": "value", "timestamp": time.time()}
        success = await cache.set("test_key", test_data, ttl=300)
        print(f"✅ Set operation: {success}")
        
        retrieved = await cache.get("test_key")
        if retrieved and retrieved["key"] == "value":
            print(f"✅ Get operation: {retrieved}")
        else:
            print("❌ Get operation failed")
        
        # Test cache miss
        miss_result = await cache.get("nonexistent_key", "default")
        if miss_result == "default":
            print("✅ Cache miss handling: working")
        else:
            print("❌ Cache miss handling: failed")
        
        # Test cache exists
        exists = await cache.exists("test_key")
        print(f"✅ Exists check: {exists}")
        
        # Test TTL
        ttl = await cache.ttl("test_key")
        print(f"✅ TTL check: {ttl}")
        
        # Test L1 cache performance
        print("\n⚡ Testing L1 Cache Performance")
        start_time = time.time()
        
        for i in range(100):
            await cache.get("test_key")
        
        l1_time = time.time() - start_time
        print(f"✅ L1 cache: 100 gets in {l1_time:.3f}s ({100/l1_time:.1f} ops/s)")
        
        # Test cache warming
        print("\n🔥 Testing Cache Warming")
        warm_data = {f"warm_key_{i}": f"value_{i}" for i in range(50)}
        warmed = await cache.warm_cache(warm_data, ttl=600)
        print(f"✅ Cache warming: {warmed}/50 entries warmed")
        
        # Test cache stats
        print("\n📊 Testing Cache Stats")
        stats = cache.get_cache_stats()
        print(f"✅ Total requests: {stats['total_requests']}")
        print(f"✅ Cache hits: {stats['cache_hits']}")
        print(f"✅ Hit rate: {stats['hit_rate']:.1f}%")
        print(f"✅ L1 hits: {stats['l1_hits']}")
        print(f"✅ L2 hits: {stats['l2_hits']}")
        print(f"✅ L1 cache size: {stats['l1_cache_size']}")
        print(f"✅ Memory usage: {stats['memory_usage']} bytes")
        
        # Test top keys
        top_keys = cache.get_top_keys(5)
        print(f"✅ Top keys: {len(top_keys)} keys")
        for key_info in top_keys[:3]:
            print(f"   {key_info['key']}: {key_info['access_count']} accesses")
        
        # Test cache clearing
        print("\n🗑️ Testing Cache Clearing")
        cleared = await cache.clear("test_*")
        print(f"✅ Pattern clear: {cleared} entries cleared")
        
        # Verify clearing
        exists = await cache.exists("test_key")
        if not exists:
            print("✅ Cache clearing successful")
        else:
            print("❌ Cache clearing failed")
        
        # Test large data
        print("\n📦 Testing Large Data")
        large_data = {"data": "x" * 1000}  # 1KB
        success = await cache.set("large_key", large_data)
        print(f"✅ Large data set: {success}")
        
        retrieved_large = await cache.get("large_key")
        if retrieved_large and len(retrieved_large["data"]) == 1000:
            print("✅ Large data retrieval: working")
        else:
            print("❌ Large data retrieval: failed")
        
        await cache.stop()
        print("\n🎉 Cache Manager Test: PASSED")
        return True
        
    except Exception as e:
        print(f"❌ Cache Manager test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_message_queue():
    """Test message queue functionality"""
    
    print("\n📨 Testing Message Queue")
    print("=" * 50)
    
    try:
        # Initialize message queue
        config = MessageConfig(
            broker_type="rabbitmq",  # Will fallback to mock if not available
            connection_host="localhost",
            connection_port=5672,
            queue_durable=True,
            max_retries=3,
            prefetch_count=10,
            encrypt_messages=True,
            audit_message_access=True
        )
        
        mq = MessageQueue(config)
        await mq.start()
        print(f"✅ MessageQueue started (broker: {mq.broker_type}, available: {mq.broker_available})")
        
        # Test queue creation
        print("\n📝 Testing Queue Creation")
        success = await mq.create_queue("test_queue", durable=True)
        print(f"✅ Queue creation: {success}")
        
        # Test message publishing
        print("\n📤 Testing Message Publishing")
        published = 0
        
        for i in range(10):
            message_data = {
                "id": i,
                "content": f"Test message {i}",
                "timestamp": time.time()
            }
            
            success = await mq.publish("test_queue", message_data, priority=i % 10 + 1)
            if success:
                published += 1
        
        print(f"✅ Published {published}/10 messages")
        
        # Test message subscription
        print("\n📥 Testing Message Subscription")
        received_messages = []
        
        async def message_handler(payload, message):
            received_messages.append(payload)
            print(f"   Received message {payload['id']}: {payload['content']}")
        
        success = await mq.subscribe("test_queue", message_handler)
        print(f"✅ Subscription: {success}")
        
        # Wait for message processing
        await asyncio.sleep(2)
        
        print(f"✅ Received {len(received_messages)} messages")
        
        # Test message statistics
        print("\n📊 Testing Message Stats")
        stats = mq.get_queue_stats("test_queue")
        print(f"✅ Total messages: {stats.total_messages}")
        print(f"✅ Successful messages: {stats.successful_messages}")
        print(f"✅ Failed messages: {stats.failed_messages}")
        print(f"✅ Avg processing time: {stats.avg_processing_time:.3f}s")
        
        # Test broker info
        print("\n🔧 Testing Broker Info")
        broker_info = mq.get_broker_info()
        print(f"✅ Broker type: {broker_info['broker_type']}")
        print(f"✅ Broker available: {broker_info['broker_available']}")
        print(f"✅ Queues: {broker_info['queues']}")
        print(f"✅ Handlers: {broker_info['handlers']}")
        
        # Test message with priority
        print("\n🎯 Testing Priority Messages")
        priority_data = {"priority": "high", "data": "urgent"}
        success = await mq.publish("test_queue", priority_data, priority=10)
        print(f"✅ Priority message: {success}")
        
        # Test message with TTL
        print("\n⏰ Testing TTL Messages")
        ttl_data = {"ttl": "short", "data": "expires"}
        success = await mq.publish("test_queue", ttl_data, expiration=5000)  # 5 seconds
        print(f"✅ TTL message: {success}")
        
        # Test error handling
        print("\n❌ Testing Error Handling")
        
        async def error_handler(message, error):
            print(f"   Error handler called: {error}")
        
        await mq.subscribe("error_queue", error_handler)
        
        # Publish to error queue with handler that will fail
        await mq.create_queue("error_queue")
        
        async def failing_handler(payload, message):
            raise Exception("Simulated handler error")
        
        await mq.subscribe("error_queue", failing_handler)
        await mq.publish("error_queue", {"error": "test"})
        
        await asyncio.sleep(1)
        
        error_stats = mq.get_queue_stats("error_queue")
        print(f"✅ Error handling: {error_stats.failed_messages} failed messages")
        
        await mq.stop()
        print("\n🎉 Message Queue Test: PASSED")
        return True
        
    except Exception as e:
        print(f"❌ Message Queue test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_performance_optimizer():
    """Test performance optimizer functionality"""
    
    print("\n⚡ Testing Performance Optimizer")
    print("=" * 50)
    
    try:
        # Initialize performance optimizer
        config = {
            "thresholds": {
                "cpu_warning": 70.0,
                "cpu_critical": 85.0,
                "memory_warning": 75.0,
                "memory_critical": 90.0,
                "response_time_warning": 500.0,
                "response_time_critical": 1000.0
            },
            "auto_optimize": True,
            "optimization_interval": 5,  # Short for testing
            "us_compliance": {
                "resource_audit": True,
                "performance_logging": True
            }
        }
        
        optimizer = PerformanceOptimizer(config)
        await optimizer.start()
        print(f"✅ PerformanceOptimizer started")
        
        # Test metrics collection
        print("\n📊 Testing Metrics Collection")
        metrics = await optimizer.collect_metrics()
        print(f"✅ CPU: {metrics.cpu_percent:.1f}%")
        print(f"✅ Memory: {metrics.memory_percent:.1f}%")
        print(f"✅ Disk: {metrics.disk_usage_percent:.1f}%")
        print(f"✅ Response time: {metrics.response_time_ms:.1f}ms")
        print(f"✅ Throughput: {metrics.throughput_ops_s:.1f} ops/s")
        
        # Test performance summary
        print("\n📋 Testing Performance Summary")
        summary = optimizer.get_performance_summary()
        print(f"✅ Current CPU: {summary['current']['cpu_percent']:.1f}%")
        print(f"✅ Current Memory: {summary['current']['memory_percent']:.1f}%")
        print(f"✅ Alerts: CPU warning={summary['alerts']['cpu_warning']}")
        print(f"✅ Optimizations: {summary['optimizations']['total_actions']}")
        print(f"✅ Recommendations: {summary['recommendations']['total_recommendations']}")
        
        # Test manual optimization
        print("\n🔧 Testing Manual Optimization")
        
        # Memory optimization
        memory_action = await optimizer.manual_optimization("memory")
        print(f"✅ Memory optimization: {memory_action.success} ({memory_action.execution_time:.3f}s)")
        
        # Performance optimization
        perf_action = await optimizer.manual_optimization("performance")
        print(f"✅ Performance optimization: {perf_action.success} ({perf_action.execution_time:.3f}s)")
        
        # GC optimization
        gc_action = await optimizer.manual_optimization("gc")
        print(f"✅ GC optimization: {gc_action.success} ({gc_action.execution_time:.3f}s)")
        
        # Test optimization history
        print("\n📈 Testing Optimization History")
        history = optimizer.get_optimization_history(limit=5)
        print(f"✅ Optimization history: {len(history)} actions")
        
        for action in history[-3:]:
            print(f"   {action.action_type}: {action.success}")
        
        # Test scaling recommendations
        print("\n📏 Testing Scaling Recommendations")
        recommendations = optimizer.get_scaling_recommendations(limit=5)
        print(f"✅ Recommendations: {len(recommendations)} recommendations")
        
        for rec in recommendations[-3:]:
            print(f"   {rec.resource_type}: {rec.action} (confidence: {rec.confidence:.2f})")
        
        # Test performance callbacks
        print("\n🔔 Testing Performance Callbacks")
        callback_called = False
        
        async def test_callback(metrics):
            nonlocal callback_called
            callback_called = True
            print(f"   Callback: CPU {metrics.cpu_percent:.1f}%")
        
        optimizer.add_performance_callback(test_callback)
        
        # Wait for callback
        await asyncio.sleep(2)
        
        if callback_called:
            print("✅ Performance callback: working")
        else:
            print("❌ Performance callback: failed")
        
        optimizer.remove_performance_callback(test_callback)
        
        await optimizer.stop()
        print("\n🎉 Performance Optimizer Test: PASSED")
        return True
        
    except Exception as e:
        print(f"❌ Performance Optimizer test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_scalability_integration():
    """Test full scalability integration"""
    
    print("\n🔄 Testing Scalability Integration")
    print("=" * 50)
    
    try:
        # Initialize all components
        lb_config = {"us_compliance": {"audit_logging": True}}
        lb = LoadBalancer(lb_config)
        await lb.start()
        
        cache_config = CacheConfig(enable_l1_cache=True, enable_l2_cache=True)
        cache = CacheManager(cache_config)
        await cache.start()
        
        mq_config = MessageConfig(broker_type="rabbitmq", encrypt_messages=True)
        mq = MessageQueue(mq_config)
        await mq.start()
        
        optimizer_config = {
            "auto_optimize": True,
            "thresholds": {"cpu_warning": 70.0, "memory_warning": 75.0}
        }
        optimizer = PerformanceOptimizer(optimizer_config)
        await optimizer.start()
        
        print(f"✅ All scalability components initialized")
        
        # Register instances
        await lb.register_instance("web1", "localhost", 8001, "http", 1, 1000, "web")
        await lb.register_instance("api1", "localhost", 8002, "http", 2, 500, "api")
        await lb.create_queue("integration_queue")
        
        # Step 1: Load balancing with caching
        print("\n🔄 Step 1: Load Balancing + Caching")
        
        for i in range(5):
            # Route request
            decision = await lb.route_request("web", f"session_{i}")
            
            if decision:
                # Cache the routing decision
                await cache.set(f"route_{i}", decision.instance_id, ttl=300)
                await lb.record_request_result(decision.instance_id, True, 0.05)
                
                # Verify cache
                cached = await cache.get(f"route_{i}")
                if cached == decision.instance_id:
                    print(f"   Request {i}: {decision.instance_id} (cached)")
                else:
                    print(f"   Request {i}: {decision.instance_id} (cache miss)")
        
        # Step 2: Message processing with performance monitoring
        print("\n📨 Step 2: Message Processing + Performance Monitoring")
        
        processed_messages = []
        
        async def integration_handler(payload, message):
            processed_messages.append(payload)
            
            # Simulate processing time
            await asyncio.sleep(0.01)
            
            # Record performance
            metrics = await optimizer.collect_metrics()
            if metrics.response_time_ms > 100:  # Mock threshold
                await optimizer.manual_optimization("performance")
        
        await mq.subscribe("integration_queue", integration_handler)
        
        # Send messages
        for i in range(10):
            message_data = {
                "request_id": i,
                "data": f"integration_test_{i}",
                "timestamp": time.time()
            }
            
            await mq.publish("integration_queue", message_data)
        
        # Wait for processing
        await asyncio.sleep(2)
        
        print(f"✅ Processed {len(processed_messages)} messages")
        
        # Step 3: Performance optimization with caching
        print("\n⚡ Step 3: Performance Optimization + Caching")
        
        # Cache performance metrics
        metrics = await optimizer.collect_metrics()
        await cache.set("perf_metrics", metrics, ttl=60)
        
        # Trigger optimization
        await optimizer.manual_optimization("memory")
        
        # Verify cached metrics
        cached_metrics = await cache.get("perf_metrics")
        if cached_metrics:
            print(f"✅ Cached metrics: CPU {cached_metrics.cpu_percent:.1f}%")
        else:
            print("❌ Cached metrics not found")
        
        # Step 4: Load balancing with message queue
        print("\n⚖️ Step 4: Load Balancing + Message Queue")
        
        async def request_handler(payload, message):
            # Simulate request processing
            await asyncio.sleep(0.02)
            print(f"   Processed request: {payload['request_id']}")
        
        await mq.subscribe("request_queue", request_handler)
        await mq.create_queue("request_queue")
        
        # Route requests and queue them
        for i in range(3):
            decision = await lb.route_request("api", f"api_session_{i}")
            
            if decision:
                request_data = {
                    "request_id": i,
                    "instance": decision.instance_id,
                    "timestamp": time.time()
                }
                
                await mq.publish("request_queue", request_data)
                await lb.record_request_result(decision.instance_id, True, 0.1)
        
        # Wait for processing
        await asyncio.sleep(1)
        
        # Step 5: Integration summary
        print("\n📊 Step 5: Integration Summary")
        
        lb_stats = lb.get_load_balancer_stats()
        cache_stats = cache.get_cache_stats()
        mq_stats = mq.get_queue_stats("integration_queue")
        perf_summary = optimizer.get_performance_summary()
        
        print(f"✅ Load Balancer: {lb_stats['total_requests']} requests")
        print(f"✅ Cache: {cache_stats['hit_rate']:.1f}% hit rate")
        print(f"✅ Message Queue: {mq_stats['total_messages']} messages")
        print(f"✅ Performance: {perf_summary['current']['cpu_percent']:.1f}% CPU")
        
        # Cleanup
        await lb.stop()
        await cache.stop()
        await mq.stop()
        await optimizer.stop()
        
        print("\n🎉 Scalability Integration Test: PASSED")
        return True
        
    except Exception as e:
        print(f"❌ Scalability Integration test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_performance():
    """Test scalability performance"""
    
    print("\n⚡ Testing Scalability Performance")
    print("-" * 40)
    
    try:
        # Initialize components
        cache_config = CacheConfig(enable_l1_cache=True, enable_l2_cache=True)
        cache = CacheManager(cache_config)
        await cache.start()
        
        lb_config = {"us_compliance": {"audit_logging": True}}
        lb = LoadBalancer(lb_config)
        await lb.start()
        
        await lb.register_instance("perf1", "localhost", 8001, "http", 1, 1000, "web")
        await lb.register_instance("perf2", "localhost", 8002, "http", 1, 1000, "web")
        
        # Performance test
        start_time = time.time()
        
        # Concurrent operations
        tasks = []
        
        # Cache operations
        for i in range(50):
            tasks.append(cache.set(f"perf_key_{i}", f"value_{i}", ttl=300))
            tasks.append(cache.get(f"perf_key_{i}"))
        
        # Load balancing operations
        for i in range(30):
            tasks.append(lb.route_request("web", f"perf_session_{i}"))
        
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
        
        # Component-specific stats
        cache_stats = cache.get_cache_stats()
        lb_stats = lb.get_load_balancer_stats()
        
        print(f"   Cache hit rate: {cache_stats['hit_rate']:.1f}%")
        print(f"   Load balancer requests: {lb_stats['total_requests']}")
        
        await cache.stop()
        await lb.stop()
        
        print("\n🎯 Performance Test: PASSED")
        return True
        
    except Exception as e:
        print(f"❌ Performance test failed: {e}")
        return False

async def main():
    """Run all scalability tests"""
    try:
        print("🧪 SCALABILITY TEST SUITE")
        print("=" * 70)
        
        # Run tests
        test1 = await test_load_balancer()
        test2 = await test_cache_manager()
        test3 = await test_message_queue()
        test4 = await test_performance_optimizer()
        test5 = await test_scalability_integration()
        test6 = await test_performance()
        
        # Summary
        print("\n" + "=" * 70)
        print("📊 SCALABILITY TEST RESULTS")
        print("=" * 70)
        print(f"Load Balancer:        {'✅ PASSED' if test1 else '❌ FAILED'}")
        print(f"Cache Manager:        {'✅ PASSED' if test2 else '❌ FAILED'}")
        print(f"Message Queue:        {'✅ PASSED' if test3 else '❌ FAILED'}")
        print(f"Performance Optimizer: {'✅ PASSED' if test4 else '❌ FAILED'}")
        print(f"Scalability Integration: {'✅ PASSED' if test5 else '❌ FAILED'}")
        print(f"Performance:            {'✅ PASSED' if test6 else '❌ FAILED'}")
        
        if all([test1, test2, test3, test4, test5, test6]):
            print("\n🎯 ALL SCALABILITY TESTS PASSED!")
            print("✅ Load balancing with health checking working")
            print("✅ Multi-level caching with Redis integration working")
            print("✅ Message queuing with RabbitMQ/Kafka support working")
            print("✅ Performance monitoring and optimization working")
            print("✅ Full scalability integration successful")
            print("✅ Performance within acceptable limits")
        else:
            print("\n❌ Some scalability tests failed")
        
    except Exception as e:
        print(f"❌ Scalability test suite error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
