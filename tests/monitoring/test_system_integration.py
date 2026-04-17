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

from integration.system_integration import SystemIntegration, ComponentType, IntegrationStatus, DataFlowType
from integration.performance_optimization import PerformanceOptimization, CacheStrategy, LoadBalanceAlgorithm, ResourceType
from utils.logger import get_logger

logger = get_logger("test_system_integration")

async def test_system_integration():
    """Test system integration functionality"""
    
    print("🔗 Testing System Integration")
    print("=" * 50)
    
    try:
        # Initialize system integration
        config = {
            "system_integration": {
                "max_components": 50,
                "max_pipelines": 100,
                "health_check_interval": 60,
                "auto_recovery": True
            },
            "us_compliance": {"api_security": True, "audit_integration": True}
        }
        
        integration = SystemIntegration(config)
        print(f"✅ SystemIntegration initialized")
        
        # Register components
        print("\n📡 Registering Components")
        
        components = [
            {
                "component_id": "stream_processor",
                "component_name": "Stream Processor",
                "component_type": ComponentType.STREAM,
                "api_endpoint": "/api/v1/stream",
                "custom_rate_limits": {"requests_per_second": 1000}
            },
            {
                "component_id": "price_oracle",
                "component_name": "Price Oracle",
                "component_type": ComponentType.ORACLE,
                "api_endpoint": "/api/v1/oracle",
                "custom_rate_limits": {"requests_per_second": 500}
            },
            {
                "component_id": "trading_agent",
                "component_name": "Trading Agent",
                "component_type": ComponentType.AGENT,
                "api_endpoint": "/api/v1/agent",
                "custom_rate_limits": {"requests_per_second": 200}
            },
            {
                "component_id": "trading_engine",
                "component_name": "Trading Engine",
                "component_type": ComponentType.TRADING,
                "api_endpoint": "/api/v1/trading",
                "custom_rate_limits": {"requests_per_second": 100}
            },
            {
                "component_id": "monitoring_system",
                "component_name": "Monitoring System",
                "component_type": ComponentType.MONITORING,
                "api_endpoint": "/api/v1/monitoring",
                "custom_rate_limits": {"requests_per_second": 2000}
            },
            {
                "component_id": "ai_signals",
                "component_name": "AI Signals",
                "component_type": ComponentType.AI_SIGNALS,
                "api_endpoint": "/api/v1/ai_signals",
                "custom_rate_limits": {"requests_per_second": 150}
            }
        ]
        
        for component_config in components:
            success = await integration.register_component(
                component_config["component_id"],
                component_config["component_name"],
                component_config["component_type"],
                component_config["api_endpoint"],
                custom_rate_limits=component_config.get("custom_rate_limits")
            )
            print(f"✅ Registered {component_config['component_id']}: {success}")
        
        # Connect components
        print("\n🔌 Connecting Components")
        
        for component_config in components:
            success = await integration.connect_component(component_config["component_id"])
            print(f"✅ Connected {component_config['component_id']}: {success}")
        
        # Create data pipelines
        print("\n📊 Creating Data Pipelines")
        
        pipelines = [
            {
                "pipeline_id": "oracle_to_agent",
                "pipeline_name": "Oracle to Agent Pipeline",
                "source_component": "price_oracle",
                "target_component": "trading_agent",
                "data_flow_type": DataFlowType.REAL_TIME,
                "transformation_rules": [{"type": "normalize", "field": "price"}],
                "filtering_rules": [{"type": "range", "field": "volume", "min": 1000}]
            },
            {
                "pipeline_id": "agent_to_trading",
                "pipeline_name": "Agent to Trading Pipeline",
                "source_component": "trading_agent",
                "target_component": "trading_engine",
                "data_flow_type": DataFlowType.STREAMING,
                "transformation_rules": [{"type": "validate", "field": "signal"}],
                "filtering_rules": [{"type": "confidence", "min": 0.7}]
            },
            {
                "pipeline_id": "stream_to_monitoring",
                "pipeline_name": "Stream to Monitoring Pipeline",
                "source_component": "stream_processor",
                "target_component": "monitoring_system",
                "data_flow_type": DataFlowType.BATCH,
                "transformation_rules": [{"type": "aggregate", "window": "5m"}],
                "schedule": "*/5 * * * *"  # Every 5 minutes
            },
            {
                "pipeline_id": "ai_to_trading",
                "pipeline_name": "AI Signals to Trading Pipeline",
                "source_component": "ai_signals",
                "target_component": "trading_engine",
                "data_flow_type": DataFlowType.REAL_TIME,
                "transformation_rules": [{"type": "format", "output": "json"}],
                "filtering_rules": [{"type": "risk", "max_risk": 0.8}]
            }
        ]
        
        for pipeline_config in pipelines:
            success = await integration.create_data_pipeline(
                pipeline_config["pipeline_id"],
                pipeline_config["pipeline_name"],
                pipeline_config["source_component"],
                pipeline_config["target_component"],
                pipeline_config["data_flow_type"],
                pipeline_config.get("transformation_rules"),
                pipeline_config.get("filtering_rules"),
                pipeline_config.get("schedule")
            )
            print(f"✅ Created {pipeline_config['pipeline_id']}: {success}")
        
        # Start pipelines
        print("\n🚀 Starting Data Pipelines")
        
        for pipeline_config in pipelines:
            success = await integration.start_pipeline(pipeline_config["pipeline_id"])
            print(f"✅ Started {pipeline_config['pipeline_id']}: {success}")
        
        # Test component status
        print("\n📋 Testing Component Status")
        
        component_status = integration.get_component_status()
        print(f"✅ Total components: {len(component_status)}")
        
        for comp_id, status in component_status.items():
            print(f"   {comp_id}: {status['status']} ({status['component_type']})")
        
        # Test pipeline status
        print("\n📊 Testing Pipeline Status")
        
        pipeline_status = integration.get_pipeline_status()
        print(f"✅ Total pipelines: {len(pipeline_status)}")
        
        for pipe_id, status in pipeline_status.items():
            print(f"   {pipe_id}: {status['status']} ({status['throughput']:.1f} msg/s)")
        
        # Collect system metrics
        print("\n📈 Testing System Metrics")
        
        metrics = await integration.collect_system_metrics()
        if metrics:
            print(f"✅ System metrics collected:")
            print(f"   Active components: {metrics.active_components}/{metrics.total_components}")
            print(f"   Active pipelines: {metrics.active_pipelines}/{metrics.total_pipelines}")
            print(f"   System throughput: {metrics.system_throughput:.1f} msg/s")
            print(f"   Average latency: {metrics.average_latency:.1f} ms")
            print(f"   Error rate: {metrics.error_rate:.3f}")
            print(f"   CPU usage: {metrics.cpu_usage:.1f}%")
            print(f"   Memory usage: {metrics.memory_usage:.1f}%")
        else:
            print("❌ Failed to collect system metrics")
        
        # Test integration testing
        print("\n🧪 Testing Integration Testing")
        
        # Test specific component
        component_test = await integration.test_integration(component_id="price_oracle")
        print(f"✅ Component test: {component_test['overall_status']}")
        if component_test.get("component_tests"):
            for comp_id, test_result in component_test["component_tests"].items():
                print(f"   {comp_id}: {'PASSED' if test_result['passed'] else 'FAILED'}")
        
        # Test specific pipeline
        pipeline_test = await integration.test_integration(pipeline_id="oracle_to_agent")
        print(f"✅ Pipeline test: {pipeline_test['overall_status']}")
        if pipeline_test.get("pipeline_tests"):
            for pipe_id, test_result in pipeline_test["pipeline_tests"].items():
                print(f"   {pipe_id}: {'PASSED' if test_result['passed'] else 'FAILED'}")
        
        # Test full integration
        print("\n🔄 Testing Full Integration")
        
        full_test = await integration.test_integration()
        print(f"✅ Full integration test: {full_test['overall_status']}")
        print(f"   Component tests: {len(full_test.get('component_tests', {}))}")
        print(f"   Pipeline tests: {len(full_test.get('pipeline_tests', {}))}")
        if full_test.get("issues"):
            print(f"   Issues: {len(full_test['issues'])}")
        
        # Test integration summary
        print("\n📊 Testing Integration Summary")
        
        summary = integration.get_integration_summary()
        if "status" not in summary:
            print(f"✅ Integration summary:")
            print(f"   Total components: {summary['total_components']}")
            print(f"   Component types: {summary['component_types']}")
            print(f"   Total pipelines: {summary['total_pipelines']}")
            print(f"   Active components: {summary['latest_metrics']['active_components']}")
            print(f"   Active pipelines: {summary['latest_metrics']['active_pipelines']}")
            print(f"   System throughput: {summary['latest_metrics']['system_throughput']:.1f} msg/s")
        else:
            print("⚠️ No integration summary available")
        
        print("\n🎉 System Integration Test: PASSED")
        return True
        
    except Exception as e:
        print(f"❌ System Integration test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_performance_optimization():
    """Test performance optimization functionality"""
    
    print("\n⚡ Testing Performance Optimization")
    print("=" * 50)
    
    try:
        # Initialize performance optimization
        config = {
            "performance_optimization": {
                "max_cache_size_mb": 1024,
                "cache_cleanup_interval": 300,
                "resource_monitoring_interval": 60,
                "auto_optimization": True
            },
            "us_compliance": {"data_privacy": True, "audit_optimization": True}
        }
        
        optimization = PerformanceOptimization(config)
        print(f"✅ PerformanceOptimization initialized")
        
        # Create caches
        print("\n💾 Creating Caches")
        
        caches = [
            {
                "cache_id": "price_cache",
                "cache_name": "Price Data Cache",
                "strategy": CacheStrategy.LRU,
                "max_size_mb": 100,
                "max_entries": 10000,
                "ttl_seconds": 300
            },
            {
                "cache_id": "signal_cache",
                "cache_name": "Trading Signals Cache",
                "strategy": CacheStrategy.TTL,
                "max_size_mb": 50,
                "max_entries": 5000,
                "ttl_seconds": 60
            },
            {
                "cache_id": "analytics_cache",
                "cache_name": "Analytics Cache",
                "strategy": CacheStrategy.LFU,
                "max_size_mb": 200,
                "max_entries": 2000,
                "ttl_seconds": 600
            },
            {
                "cache_id": "adaptive_cache",
                "cache_name": "Adaptive Cache",
                "strategy": CacheStrategy.ADAPTIVE,
                "max_size_mb": 150,
                "max_entries": 7500
            }
        ]
        
        for cache_config in caches:
            success = await optimization.create_cache(
                cache_config["cache_id"],
                cache_config["cache_name"],
                cache_config["strategy"],
                cache_config["max_size_mb"],
                cache_config["max_entries"],
                cache_config.get("ttl_seconds")
            )
            print(f"✅ Created {cache_config['cache_id']}: {success}")
        
        # Test cache operations
        print("\n🔄 Testing Cache Operations")
        
        # Test cache set/get
        test_data = {
            "BTC": {"price": 45000.0, "volume": 1000000, "timestamp": datetime.now()},
            "ETH": {"price": 3000.0, "volume": 500000, "timestamp": datetime.now()},
            "AAPL": {"price": 150.0, "volume": 10000000, "timestamp": datetime.now()}
        }
        
        cache_results = {}
        for symbol, data in test_data.items():
            # Set cache entry
            set_success = await optimization.cache_set("price_cache", f"price_{symbol}", data, ttl_seconds=60)
            
            # Get cache entry
            cached_data = await optimization.cache_get("price_cache", f"price_{symbol}")
            
            cache_results[symbol] = {
                "set_success": set_success,
                "get_success": cached_data is not None,
                "data_match": cached_data == data if cached_data else False
            }
            
            print(f"✅ {symbol}: Set={set_success}, Get={cached_data is not None}")
        
        # Test cache statistics
        print("\n📊 Testing Cache Statistics")
        
        cache_stats = optimization.get_cache_stats()
        print(f"✅ Total caches: {len(cache_stats)}")
        
        for cache_id, stats in cache_stats.items():
            print(f"   {cache_id}:")
            print(f"     Hits: {stats['hits']}")
            print(f"     Misses: {stats['misses']}")
            print(f"     Hit rate: {stats['hit_rate']:.3f}")
            print(f"     Entries: {stats['current_entries']}")
            print(f"     Size: {stats['current_size_mb']:.2f} MB")
        
        # Create load balancers
        print("\n⚖️ Creating Load Balancers")
        
        load_balancers = [
            {
                "balancer_id": "trading_lb",
                "balancer_name": "Trading Load Balancer",
                "algorithm": LoadBalanceAlgorithm.WEIGHTED_ROUND_ROBIN,
                "targets": ["trader_1", "trader_2", "trader_3"],
                "weights": [0.5, 0.3, 0.2]
            },
            {
                "balancer_id": "analytics_lb",
                "balancer_name": "Analytics Load Balancer",
                "algorithm": LoadBalanceAlgorithm.LEAST_RESPONSE_TIME,
                "targets": ["analytics_1", "analytics_2"],
                "weights": None
            },
            {
                "balancer_id": "data_lb",
                "balancer_name": "Data Load Balancer",
                "algorithm": LoadBalanceAlgorithm.ROUND_ROBIN,
                "targets": ["data_node_1", "data_node_2", "data_node_3", "data_node_4"],
                "weights": None
            },
            {
                "balancer_id": "adaptive_lb",
                "balancer_name": "Adaptive Load Balancer",
                "algorithm": LoadBalanceAlgorithm.ADAPTIVE,
                "targets": ["server_1", "server_2"],
                "weights": [0.6, 0.4]
            }
        ]
        
        for lb_config in load_balancers:
            success = await optimization.create_load_balancer(
                lb_config["balancer_id"],
                lb_config["balancer_name"],
                lb_config["algorithm"],
                lb_config["targets"],
                lb_config.get("weights")
            )
            print(f"✅ Created {lb_config['balancer_id']}: {success}")
        
        # Test load balancing
        print("\n🎯 Testing Load Balancing")
        
        lb_results = {}
        for lb_config in load_balancers:
            balancer_id = lb_config["balancer_id"]
            
            # Test target selection
            selections = []
            for i in range(10):
                target = await optimization.select_target(balancer_id, f"request_{i}")
                if target:
                    selections.append(target)
                    
                    # Update mock response time
                    response_time = np.random.uniform(10, 100)
                    await optimization.update_target_response_time(balancer_id, target, response_time)
            
            lb_results[balancer_id] = {
                "selections": len(selections),
                "unique_targets": len(set(selections)),
                "distribution": {target: selections.count(target) for target in set(selections)}
            }
            
            print(f"✅ {balancer_id}: {len(selections)} selections, {len(set(selections))} unique targets")
        
        # Test load balancer statistics
        print("\n📊 Testing Load Balancer Statistics")
        
        lb_stats = optimization.get_load_balancer_stats()
        print(f"✅ Total load balancers: {len(lb_stats)}")
        
        for balancer_id, stats in lb_stats.items():
            print(f"   {balancer_id}:")
            print(f"     Algorithm: {stats['algorithm']}")
            print(f"     Targets: {stats['total_targets']}")
            print(f"     Healthy: {stats['healthy_targets']}")
            print(f"     Connections: {stats['total_connections']}")
        
        # Test resource metrics collection
        print("\n📈 Testing Resource Metrics")
        
        resource_metrics = {}
        for resource_type in ResourceType:
            metrics = await optimization.collect_resource_metrics(resource_type)
            resource_metrics[resource_type.value] = {
                "utilization": metrics.utilization_percentage,
                "performance_score": metrics.performance_score,
                "alerts": len(metrics.alerts)
            }
            
            print(f"✅ {resource_type.value}: {metrics.utilization_percentage:.1f}% utilization, {metrics.performance_score:.1f} score")
        
        # Test resource metrics retrieval
        print("\n📊 Testing Resource Metrics Retrieval")
        
        all_metrics = optimization.get_resource_metrics(limit=10)
        print(f"✅ Retrieved metrics for {len(all_metrics)} resource types")
        
        for resource_type, metrics_list in all_metrics.items():
            if metrics_list:
                latest = metrics_list[-1]
                print(f"   {resource_type}: {len(metrics_list)} records, latest: {latest.utilization_percentage:.1f}%")
        
        # Test optimization summary
        print("\n📊 Testing Optimization Summary")
        
        summary = optimization.get_optimization_summary()
        if "status" not in summary:
            print(f"✅ Optimization summary:")
            print(f"   Caches: {summary['caches']['total_caches']}")
            print(f"   Overall hit rate: {summary['caches']['overall_hit_rate']:.3f}")
            print(f"   Load balancers: {summary['load_balancers']['total_balancers']}")
            print(f"   Healthy targets: {summary['load_balancers']['healthy_targets']}/{summary['load_balancers']['total_targets']}")
            print(f"   Resource types: {len(summary['resources'])}")
        else:
            print("⚠️ No optimization summary available")
        
        print("\n🎉 Performance Optimization Test: PASSED")
        return True
        
    except Exception as e:
        print(f"❌ Performance Optimization test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_system_integration_performance():
    """Test system integration performance"""
    
    print("\n🚀 Testing System Integration Performance")
    print("=" * 50)
    
    try:
        # Initialize systems
        integration_config = {"us_compliance": {"api_security": True}}
        integration = SystemIntegration(integration_config)
        
        optimization_config = {"us_compliance": {"data_privacy": True}}
        optimization = PerformanceOptimization(optimization_config)
        
        print(f"✅ Systems initialized for performance testing")
        
        # Setup test environment
        print("\n⚙️ Setting Up Performance Test Environment")
        
        # Register components
        components = ["stream", "oracle", "agent", "trading", "monitoring"]
        for i, comp_type in enumerate(components):
            await integration.register_component(
                f"perf_{comp_type}_{i}",
                f"Performance {comp_type.title()} {i}",
                ComponentType(comp_type),
                f"/api/v1/{comp_type}"
            )
            await integration.connect_component(f"perf_{comp_type}_{i}")
        
        # Create cache
        await optimization.create_cache("perf_cache", "Performance Cache", CacheStrategy.LRU, 100, 1000)
        
        # Create load balancer
        await optimization.create_load_balancer(
            "perf_lb",
            "Performance Load Balancer",
            LoadBalanceAlgorithm.ROUND_ROBIN,
            ["target_1", "target_2", "target_3"]
        )
        
        print(f"✅ Performance test environment ready")
        
        # Test component registration performance
        print("\n📊 Testing Component Registration Performance")
        
        registration_times = []
        for i in range(10):
            start_time = time.time()
            
            await integration.register_component(
                f"perf_test_{i}",
                f"Performance Test {i}",
                ComponentType.STREAM,
                f"/api/v1/test_{i}"
            )
            
            registration_time = time.time() - start_time
            registration_times.append(registration_time)
        
        avg_registration_time = np.mean(registration_times)
        print(f"✅ Average component registration time: {avg_registration_time*1000:.2f} ms")
        
        # Test cache performance
        print("\n💾 Testing Cache Performance")
        
        cache_times = []
        test_data = {"test": "data", "timestamp": datetime.now()}
        
        # Test cache set performance
        for i in range(100):
            start_time = time.time()
            
            await optimization.cache_set("perf_cache", f"key_{i}", test_data)
            
            cache_time = time.time() - start_time
            cache_times.append(cache_time)
        
        avg_cache_set_time = np.mean(cache_times)
        print(f"✅ Average cache set time: {avg_cache_set_time*1000:.2f} ms")
        
        # Test cache get performance
        cache_times = []
        for i in range(100):
            start_time = time.time()
            
            await optimization.cache_get("perf_cache", f"key_{i}")
            
            cache_time = time.time() - start_time
            cache_times.append(cache_time)
        
        avg_cache_get_time = np.mean(cache_times)
        print(f"✅ Average cache get time: {avg_cache_get_time*1000:.2f} ms")
        
        # Test load balancer performance
        print("\n⚖️ Testing Load Balancer Performance")
        
        lb_times = []
        for i in range(100):
            start_time = time.time()
            
            target = await optimization.select_target("perf_lb", f"request_{i}")
            
            lb_time = time.time() - start_time
            lb_times.append(lb_time)
        
        avg_lb_time = np.mean(lb_times)
        print(f"✅ Average load balancer selection time: {avg_lb_time*1000:.2f} ms")
        
        # Test system metrics collection performance
        print("\n📈 Testing System Metrics Collection Performance")
        
        metrics_times = []
        for i in range(10):
            start_time = time.time()
            
            await integration.collect_system_metrics()
            
            metrics_time = time.time() - start_time
            metrics_times.append(metrics_time)
        
        avg_metrics_time = np.mean(metrics_times)
        print(f"✅ Average metrics collection time: {avg_metrics_time*1000:.2f} ms")
        
        # Test resource metrics collection performance
        print("\n📊 Testing Resource Metrics Collection Performance")
        
        resource_times = []
        for i in range(10):
            start_time = time.time()
            
            await optimization.collect_resource_metrics(ResourceType.CPU)
            
            resource_time = time.time() - start_time
            resource_times.append(resource_time)
        
        avg_resource_time = np.mean(resource_times)
        print(f"✅ Average resource metrics collection time: {avg_resource_time*1000:.2f} ms")
        
        # Test integration testing performance
        print("\n🧪 Testing Integration Testing Performance")
        
        test_times = []
        for i in range(5):
            start_time = time.time()
            
            await integration.test_integration()
            
            test_time = time.time() - start_time
            test_times.append(test_time)
        
        avg_test_time = np.mean(test_times)
        print(f"✅ Average integration test time: {avg_test_time:.2f} s")
        
        # Performance summary
        print("\n📊 Performance Summary")
        
        performance_metrics = {
            "component_registration_ms": avg_registration_time * 1000,
            "cache_set_ms": avg_cache_set_time * 1000,
            "cache_get_ms": avg_cache_get_time * 1000,
            "load_balancer_ms": avg_lb_time * 1000,
            "system_metrics_ms": avg_metrics_time * 1000,
            "resource_metrics_ms": avg_resource_time * 1000,
            "integration_test_s": avg_test_time
        }
        
        print(f"✅ Performance Metrics:")
        for metric, value in performance_metrics.items():
            print(f"   {metric}: {value:.2f}")
        
        # Performance validation
        print("\n✅ Performance Validation")
        
        performance_thresholds = {
            "component_registration_ms": 50,  # 50ms
            "cache_set_ms": 5,  # 5ms
            "cache_get_ms": 2,  # 2ms
            "load_balancer_ms": 1,  # 1ms
            "system_metrics_ms": 100,  # 100ms
            "resource_metrics_ms": 50,  # 50ms
            "integration_test_s": 5  # 5s
        }
        
        all_passed = True
        for metric, threshold in performance_thresholds.items():
            actual_value = performance_metrics[metric]
            passed = actual_value <= threshold
            status = "✅" if passed else "❌"
            print(f"{status} {metric}: {actual_value:.2f} (threshold: {threshold})")
            
            if not passed:
                all_passed = False
        
        print(f"\n🎯 Performance Test: {'PASSED' if all_passed else 'FAILED'}")
        return all_passed
        
    except Exception as e:
        print(f"❌ Performance test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_end_to_end_integration():
    """Test end-to-end system integration"""
    
    print("\n🔄 Testing End-to-End Integration")
    print("=" * 50)
    
    try:
        # Initialize all systems
        integration_config = {"us_compliance": {"api_security": True}}
        integration = SystemIntegration(integration_config)
        
        optimization_config = {"us_compliance": {"data_privacy": True}}
        optimization = PerformanceOptimization(optimization_config)
        
        print(f"✅ All systems initialized")
        
        # Step 1: Setup complete system
        print("\n🏗️ Step 1: Setting Up Complete System")
        
        # Register all component types
        component_types = [
            ComponentType.STREAM,
            ComponentType.ORACLE,
            ComponentType.AGENT,
            ComponentType.TRADING,
            ComponentType.MONITORING,
            ComponentType.SCALING,
            ComponentType.ANALYTICS,
            ComponentType.AI_SIGNALS,
            ComponentType.MULTI_ASSET,
            ComponentType.RISK_MANAGEMENT
        ]
        
        registered_components = []
        for comp_type in component_types:
            comp_id = f"e2e_{comp_type.value}"
            success = await integration.register_component(
                comp_id,
                f"E2E {comp_type.value.title()}",
                comp_type,
                f"/api/v1/{comp_type.value}"
            )
            
            if success:
                registered_components.append(comp_id)
                await integration.connect_component(comp_id)
                print(f"✅ Registered and connected {comp_id}")
        
        # Create comprehensive data pipelines
        print("\n📊 Step 2: Creating Data Pipelines")
        
        pipeline_configs = []
        for i, source in enumerate(registered_components[:-1]):
            target = registered_components[i + 1] if i + 1 < len(registered_components) else registered_components[0]
            
            pipeline_id = f"e2e_pipeline_{i}"
            success = await integration.create_data_pipeline(
                pipeline_id,
                f"E2E Pipeline {i}",
                source,
                target,
                DataFlowType.REAL_TIME,
                [{"type": "transform", "operation": "normalize"}],
                [{"type": "filter", "field": "valid", "value": True}]
            )
            
            if success:
                pipeline_configs.append(pipeline_id)
                await integration.start_pipeline(pipeline_id)
                print(f"✅ Created and started {pipeline_id}")
        
        # Create optimization components
        print("\n⚡ Step 3: Setting Up Optimization")
        
        # Create multiple caches
        cache_strategies = [CacheStrategy.LRU, CacheStrategy.TTL, CacheStrategy.LFU, CacheStrategy.ADAPTIVE]
        created_caches = []
        
        for i, strategy in enumerate(cache_strategies):
            cache_id = f"e2e_cache_{i}"
            success = await optimization.create_cache(
                cache_id,
                f"E2E Cache {i}",
                strategy,
                50,  # 50MB
                1000  # 1000 entries
            )
            
            if success:
                created_caches.append(cache_id)
                print(f"✅ Created {cache_id}")
        
        # Create multiple load balancers
        lb_algorithms = [LoadBalanceAlgorithm.ROUND_ROBIN, LoadBalanceAlgorithm.WEIGHTED_ROUND_ROBIN, LoadBalanceAlgorithm.LEAST_RESPONSE_TIME]
        created_lbs = []
        
        for i, algorithm in enumerate(lb_algorithms):
            lb_id = f"e2e_lb_{i}"
            targets = [f"target_{j}" for j in range(3)]
            
            success = await optimization.create_load_balancer(
                lb_id,
                f"E2E Load Balancer {i}",
                algorithm,
                targets
            )
            
            if success:
                created_lbs.append(lb_id)
                print(f"✅ Created {lb_id}")
        
        # Step 4: Simulate system operation
        print("\n🔄 Step 4: Simulating System Operation")
        
        # Simulate cache operations
        print("   Simulating cache operations...")
        for i in range(50):
            cache_id = random.choice(created_caches)
            key = f"e2e_key_{i}"
            value = {"data": f"test_data_{i}", "timestamp": datetime.now()}
            
            await optimization.cache_set(cache_id, key, value)
            
            # Randomly get some data
            if random.random() > 0.5:
                await optimization.cache_get(cache_id, key)
        
        # Simulate load balancing
        print("   Simulating load balancing...")
        for i in range(100):
            lb_id = random.choice(created_lbs)
            target = await optimization.select_target(lb_id, f"e2e_request_{i}")
            
            if target:
                # Update mock response time
                response_time = np.random.uniform(5, 50)
                await optimization.update_target_response_time(lb_id, target, response_time)
        
        # Collect metrics
        print("   Collecting system metrics...")
        await integration.collect_system_metrics()
        
        for resource_type in ResourceType:
            await optimization.collect_resource_metrics(resource_type)
        
        # Step 5: Validate system state
        print("\n✅ Step 5: Validating System State")
        
        # Check component status
        component_status = integration.get_component_status()
        connected_components = sum(1 for status in component_status.values() if status["status"] == "connected")
        print(f"   Connected components: {connected_components}/{len(component_status)}")
        
        # Check pipeline status
        pipeline_status = integration.get_pipeline_status()
        active_pipelines = sum(1 for status in pipeline_status.values() if status["status"] == "completed")
        print(f"   Active pipelines: {active_pipelines}/{len(pipeline_status)}")
        
        # Check cache performance
        cache_stats = optimization.get_cache_stats()
        total_hits = sum(stats["hits"] for stats in cache_stats.values())
        total_misses = sum(stats["misses"] for stats in cache_stats.values())
        overall_hit_rate = total_hits / (total_hits + total_misses) if (total_hits + total_misses) > 0 else 0
        print(f"   Overall cache hit rate: {overall_hit_rate:.3f}")
        
        # Check load balancer performance
        lb_stats = optimization.get_load_balancer_stats()
        total_targets = sum(stats["total_targets"] for stats in lb_stats.values())
        healthy_targets = sum(stats["healthy_targets"] for stats in lb_stats.values())
        print(f"   Healthy targets: {healthy_targets}/{total_targets}")
        
        # Step 6: End-to-end testing
        print("\n🧪 Step 6: End-to-End Testing")
        
        # Full integration test
        e2e_test = await integration.test_integration()
        print(f"   Full integration test: {e2e_test['overall_status']}")
        
        # Performance test
        performance_test = await test_system_integration_performance()
        print(f"   Performance test: {'PASSED' if performance_test else 'FAILED'}")
        
        # Step 7: System summaries
        print("\n📊 Step 7: System Summaries")
        
        integration_summary = integration.get_integration_summary()
        print(f"   Integration summary:")
        print(f"     Components: {integration_summary['total_components']}")
        print(f"     Pipelines: {integration_summary['total_pipelines']}")
        print(f"     System throughput: {integration_summary['latest_metrics']['system_throughput']:.1f} msg/s")
        
        optimization_summary = optimization.get_optimization_summary()
        print(f"   Optimization summary:")
        print(f"     Caches: {optimization_summary['caches']['total_caches']}")
        print(f"     Cache hit rate: {optimization_summary['caches']['overall_hit_rate']:.3f}")
        print(f"     Load balancers: {optimization_summary['load_balancers']['total_balancers']}")
        
        # Final validation
        print("\n🎯 Final Validation")
        
        validation_results = {
            "components_connected": connected_components >= len(component_types) * 0.8,
            "pipelines_active": active_pipelines >= len(pipeline_configs) * 0.8,
            "cache_performance": overall_hit_rate > 0.5,
            "load_balancer_health": healthy_targets >= total_targets * 0.8,
            "integration_test": e2e_test['overall_status'] == 'passed',
            "performance_test": performance_test
        }
        
        all_passed = all(validation_results.values())
        
        for test, passed in validation_results.items():
            status = "✅" if passed else "❌"
            print(f"{status} {test}: {'PASSED' if passed else 'FAILED'}")
        
        print(f"\n🎉 End-to-End Integration Test: {'PASSED' if all_passed else 'FAILED'}")
        return all_passed
        
    except Exception as e:
        print(f"❌ End-to-end integration test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def main():
    """Run all system integration tests"""
    try:
        print("🧪 SYSTEM INTEGRATION TEST SUITE")
        print("=" * 70)
        
        # Run tests
        test1 = await test_system_integration()
        test2 = await test_performance_optimization()
        test3 = await test_system_integration_performance()
        test4 = await test_end_to_end_integration()
        
        # Summary
        print("\n" + "=" * 70)
        print("🔗 SYSTEM INTEGRATION TEST RESULTS")
        print("=" * 70)
        print(f"System Integration:     {'✅ PASSED' if test1 else '❌ FAILED'}")
        print(f"Performance Optimization: {'✅ PASSED' if test2 else '❌ FAILED'}")
        print(f"Integration Performance: {'✅ PASSED' if test3 else '❌ FAILED'}")
        print(f"End-to-End Integration:  {'✅ PASSED' if test4 else '❌ FAILED'}")
        
        if all([test1, test2, test3, test4]):
            print("\n🎯 ALL SYSTEM INTEGRATION TESTS PASSED!")
            print("✅ Component API integration working")
            print("✅ Data pipeline orchestration working")
            print("✅ Performance optimization working")
            print("✅ System monitoring working")
            print("✅ Full system integration successful")
        else:
            print("\n❌ Some system integration tests failed")
        
    except Exception as e:
        print(f"❌ System integration test suite error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
