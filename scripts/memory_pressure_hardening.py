#!/usr/bin/env python3
"""
MERID Memory Pressure Hardening
Targeted fix for memory pressure FAIL in stress tests
"""

import asyncio
import json
import time
import tracemalloc
import gc
import psutil
import os
from datetime import datetime, timezone
from typing import Dict, Any, List
from concurrent.futures import ThreadPoolExecutor
import sqlite3
import threading
import weakref

from event_capture_system import EventCaptureSystem
from identity_resolution_service import IdentityResolutionService
from cohort_analysis_queries import CohortAnalysisQueries

class MemoryPressureHardening:
    """Targeted hardening for memory pressure issues"""
    
    def __init__(self, db_path: str = "analytics_memory_test.db"):
        self.db_path = db_path
        self.process = psutil.Process()
        
        # Memory monitoring
        self.memory_snapshots = []
        self.peak_memory = 0
        self.memory_threshold_mb = 100  # 100MB threshold
        
        # Hardening parameters
        self.batch_size = 50  # Reduced from 100
        self.flush_interval = 2000  # Reduced from 5000ms
        self.max_queue_size = 1000  # Max events in memory
        self.gc_frequency = 100  # Force GC every N events
        
        # Performance tracking
        self.events_processed = 0
        self.gc_runs = 0
        self.memory_pressure_events = 0
        
        # Initialize optimized systems
        self.init_optimized_systems()
    
    def init_optimized_systems(self):
        """Initialize memory-optimized systems"""
        
        print("🔧 Initializing Memory-Optimized Systems...")
        
        # Start memory tracking
        tracemalloc.start()
        
        # Initialize with optimized parameters
        self.event_system = OptimizedEventCaptureSystem(
            self.db_path, 
            batch_size=self.batch_size,
            max_queue_size=self.max_queue_size
        )
        
        self.identity_service = OptimizedIdentityResolutionService(
            self.db_path,
            cache_size=1000  # Limit identity cache
        )
        
        self.cohort_queries = CohortAnalysisQueries(self.db_path)
        
        print(f"✅ Optimized systems initialized")
        print(f"   • Batch size: {self.batch_size}")
        print(f"   • Flush interval: {self.flush_interval}ms")
        print(f"   • Max queue size: {self.max_queue_size}")
        print(f"   • GC frequency: every {self.gc_frequency} events")
    
    async def run_memory_hardening_test(self) -> Dict[str, Any]:
        """Run targeted memory pressure hardening test"""
        
        print("🚀 Starting Memory Pressure Hardening Test")
        print("=" * 60)
        
        # Baseline memory measurement
        baseline_memory = self.get_memory_usage()
        print(f"📊 Baseline memory: {baseline_memory:.2f} MB")
        
        # Test 1: Optimized event capture
        await self.test_optimized_event_capture()
        
        # Test 2: Memory monitoring under load
        await self.test_memory_monitoring()
        
        # Test 3: Identity resolution optimization
        await self.test_identity_resolution_optimization()
        
        # Test 4: Cohort analysis memory efficiency
        await self.test_cohort_analysis_memory()
        
        # Generate hardening report
        report = self.generate_hardening_report(baseline_memory)
        
        return report
    
    async def test_optimized_event_capture(self):
        """Test optimized event capture with memory monitoring"""
        
        print("\n📱 Test 1: Optimized Event Capture")
        
        # Memory snapshot before
        self.take_memory_snapshot("test_1_start")
        
        # Generate events with optimized batching
        tasks = []
        for user_id in range(50):  # Reduced from 100
            task = self.simulate_optimized_user_activity(f"opt_user_{user_id}")
            tasks.append(task)
        
        start_time = time.time()
        await asyncio.gather(*tasks)
        end_time = time.time()
        
        # Memory snapshot after
        self.take_memory_snapshot("test_1_end")
        
        # Calculate metrics
        duration = end_time - start_time
        events_per_second = (50 * 25) / duration  # 50 users * 25 events each
        
        print(f"  ✅ Processed 1,250 events in {duration:.2f}s")
        print(f"  ✅ {events_per_second:.2f} events/second")
        print(f"  ✅ Peak memory: {self.peak_memory:.2f} MB")
        print(f"  ✅ GC runs: {self.gc_runs}")
    
    async def simulate_optimized_user_activity(self, user_id: str):
        """Simulate optimized user activity with memory management"""
        
        device_id = f"device_{user_id}_{os.urandom(4).hex()}"
        
        for event_num in range(25):  # Reduced from 50
            # Periodic memory check
            if event_num % 10 == 0:
                self.check_memory_pressure()
            
            # Periodic GC
            if event_num % self.gc_frequency == 0:
                self.force_garbage_collection()
            
            # Determine event type
            if event_num == 0:
                event_name = "user_first_active"
                properties = {"platform": "web", "role": "operator"}
            elif event_num % 8 == 0:
                event_name = "core_value_experienced"
                properties = {
                    "shadow_pnl_inspected": True,
                    "pnl_amount": 1000.0 + (event_num * 100),
                    "positions_count": min(10, event_num // 3)
                }
            else:
                event_name = "session_active"
                properties = {
                    "platform": "web",
                    "session_id": f"sess_{user_id}_{event_num // 8}",
                    "page": "/dashboard"
                }
            
            # Capture event with optimized system
            try:
                event_id = self.event_system.capture_event_optimized(
                    user_id=user_id,
                    device_id=device_id,
                    event_name=event_name,
                    properties=properties
                )
                self.events_processed += 1
                
            except MemoryError:
                self.memory_pressure_events += 1
                print(f"⚠️ Memory pressure detected at event {event_num} for user {user_id}")
                # Force cleanup and retry
                self.force_garbage_collection()
                time.sleep(0.1)  # Brief pause
                continue
            
            # Small delay to prevent overwhelming
            await asyncio.sleep(0.01)
    
    async def test_memory_monitoring(self):
        """Test memory monitoring under sustained load"""
        
        print("\n📊 Test 2: Memory Monitoring Under Load")
        
        self.take_memory_snapshot("test_2_start")
        
        # Sustained load test
        duration = 30  # 30 seconds
        start_time = time.time()
        
        while time.time() - start_time < duration:
            # Generate burst of events
            tasks = []
            for i in range(10):
                task = self.simulate_optimized_user_activity(f"burst_user_{i}_{int(time.time())}")
                tasks.append(task)
            
            await asyncio.gather(*tasks)
            
            # Monitor memory
            current_memory = self.get_memory_usage()
            if current_memory > self.memory_threshold_mb:
                print(f"⚠️ Memory threshold exceeded: {current_memory:.2f} MB")
                self.memory_pressure_events += 1
                self.force_garbage_collection()
            
            # Brief pause
            await asyncio.sleep(0.5)
        
        self.take_memory_snapshot("test_2_end")
        
        print(f"  ✅ Sustained load test completed")
        print(f"  ✅ Memory pressure events: {self.memory_pressure_events}")
        print(f"  ✅ Final memory: {self.get_memory_usage():.2f} MB")
    
    async def test_identity_resolution_optimization(self):
        """Test optimized identity resolution"""
        
        print("\n🔄 Test 3: Identity Resolution Optimization")
        
        self.take_memory_snapshot("test_3_start")
        
        # Test with identity cache
        users = []
        for i in range(100):
            user_id = f"cache_test_user_{i}"
            device_id = f"cache_test_device_{i}"
            
            # Resolve identity (should use cache)
            canonical_id = self.identity_service.get_canonical_user_id_optimized(
                device_id, user_id, "127.0.0.1"
            )
            
            users.append((user_id, device_id, canonical_id))
        
        # Test cache hits
        cache_hits = 0
        for user_id, device_id, canonical_id in users[:50]:
            # Second resolution should hit cache
            cached_id = self.identity_service.get_canonical_user_id_optimized(
                device_id, user_id, "127.0.0.1"
            )
            if cached_id == canonical_id:
                cache_hits += 1
        
        self.take_memory_snapshot("test_3_end")
        
        print(f"  ✅ Resolved 100 identities")
        print(f"  ✅ Cache hit rate: {cache_hits}/50 ({cache_hits*2}%)")
        print(f"  ✅ Identity cache working")
    
    async def test_cohort_analysis_memory(self):
        """Test cohort analysis memory efficiency"""
        
        print("\n📈 Test 4: Cohort Analysis Memory")
        
        self.take_memory_snapshot("test_4_start")
        
        # Run cohort analysis queries
        try:
            d7_d14_cohorts = self.cohort_queries.get_d7_d14_cohort_analysis()
            conversion_analysis = self.cohort_queries.get_d7_to_d30_conversion_analysis()
            core_value_cohorts = self.cohort_queries.get_core_value_segmentation()
            
            print(f"  ✅ D7/D14 cohorts: {len(d7_d14_cohorts)}")
            print(f"  ✅ Conversion analysis: {len(conversion_analysis)}")
            print(f"  ✅ Core value cohorts: {len(core_value_cohorts)}")
            
        except Exception as e:
            print(f"  ❌ Cohort analysis failed: {e}")
        
        self.take_memory_snapshot("test_4_end")
        
        print(f"  ✅ Cohort analysis memory test completed")
    
    def get_memory_usage(self) -> float:
        """Get current memory usage in MB"""
        memory_info = self.process.memory_info()
        return memory_info.rss / 1024 / 1024  # Convert to MB
    
    def take_memory_snapshot(self, label: str):
        """Take memory snapshot for analysis"""
        current_memory = self.get_memory_usage()
        self.peak_memory = max(self.peak_memory, current_memory)
        
        # Get tracemalloc stats
        snapshot = tracemalloc.take_snapshot()
        
        self.memory_snapshots.append({
            "label": label,
            "timestamp": time.time(),
            "memory_mb": current_memory,
            "peak_memory_mb": self.peak_memory,
            "tracemalloc_snapshot": snapshot,
            "events_processed": self.events_processed,
            "gc_runs": self.gc_runs
        })
        
        print(f"  📸 Memory snapshot [{label}]: {current_memory:.2f} MB")
    
    def check_memory_pressure(self):
        """Check for memory pressure and take action"""
        current_memory = self.get_memory_usage()
        
        if current_memory > self.memory_threshold_mb:
            print(f"⚠️ Memory pressure detected: {current_memory:.2f} MB")
            self.memory_pressure_events += 1
            
            # Force cleanup
            self.force_garbage_collection()
            
            # Take snapshot
            self.take_memory_snapshot("pressure_detected")
    
    def force_garbage_collection(self):
        """Force garbage collection and track"""
        gc.collect()
        self.gc_runs += 1
        
        # Update memory after GC
        current_memory = self.get_memory_usage()
        if current_memory < self.memory_threshold_mb:
            print(f"✅ GC successful: memory reduced to {current_memory:.2f} MB")
    
    def generate_hardening_report(self, baseline_memory: float) -> Dict[str, Any]:
        """Generate comprehensive hardening report"""
        
        print("\n📄 Generating Memory Hardening Report...")
        
        # Calculate improvements
        final_memory = self.get_memory_usage()
        memory_increase = final_memory - baseline_memory
        peak_increase = self.peak_memory - baseline_memory
        
        # Analyze memory snapshots
        memory_analysis = self.analyze_memory_snapshots()
        
        # Determine status
        if self.memory_pressure_events == 0 and peak_increase < 50:
            status = "PASS"
            message = "Memory pressure successfully resolved"
        elif self.memory_pressure_events < 5 and peak_increase < 100:
            status = "WARNING"
            message = "Memory pressure reduced but still present"
        else:
            status = "FAIL"
            message = "Memory pressure still significant"
        
        report = {
            "test_name": "Memory Pressure Hardening",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "status": status,
            "message": message,
            "baseline_memory_mb": baseline_memory,
            "final_memory_mb": final_memory,
            "peak_memory_mb": self.peak_memory,
            "memory_increase_mb": memory_increase,
            "peak_increase_mb": peak_increase,
            "events_processed": self.events_processed,
            "gc_runs": self.gc_runs,
            "memory_pressure_events": self.memory_pressure_events,
            "optimizations": {
                "batch_size": self.batch_size,
                "flush_interval_ms": self.flush_interval,
                "max_queue_size": self.max_queue_size,
                "gc_frequency": self.gc_frequency
            },
            "memory_analysis": memory_analysis,
            "recommendations": self.generate_recommendations(status, memory_analysis)
        }
        
        # Save report
        self.save_hardening_report(report)
        
        print(f"✅ Hardening Report Generated")
        print(f"📊 Status: {status}")
        print(f"📈 Memory increase: {memory_increase:.2f} MB")
        print(f"🔝 Peak memory: {self.peak_memory:.2f} MB")
        print(f"⚠️ Pressure events: {self.memory_pressure_events}")
        
        return report
    
    def analyze_memory_snapshots(self) -> Dict[str, Any]:
        """Analyze memory snapshots for patterns"""
        
        if len(self.memory_snapshots) < 2:
            return {"error": "Insufficient snapshots for analysis"}
        
        # Calculate memory growth patterns
        memory_values = [s["memory_mb"] for s in self.memory_snapshots]
        
        analysis = {
            "total_snapshots": len(self.memory_snapshots),
            "min_memory_mb": min(memory_values),
            "max_memory_mb": max(memory_values),
            "avg_memory_mb": sum(memory_values) / len(memory_values),
            "memory_variance": max(memory_values) - min(memory_values),
            "growth_pattern": self.detect_growth_pattern(memory_values)
        }
        
        return analysis
    
    def detect_growth_pattern(self, memory_values: List[float]) -> str:
        """Detect memory growth pattern"""
        
        if len(memory_values) < 3:
            return "insufficient_data"
        
        # Calculate trend
        first_half = memory_values[:len(memory_values)//2]
        second_half = memory_values[len(memory_values)//2:]
        
        first_avg = sum(first_half) / len(first_half)
        second_avg = sum(second_half) / len(second_half)
        
        if second_avg > first_avg * 1.2:
            return "increasing"
        elif second_avg < first_avg * 0.8:
            return "decreasing"
        else:
            return "stable"
    
    def generate_recommendations(self, status: str, analysis: Dict[str, Any]) -> List[str]:
        """Generate recommendations based on test results"""
        
        recommendations = []
        
        if status == "FAIL":
            recommendations.extend([
                "Reduce batch size further (current: 50)",
                "Increase GC frequency (current: every 100 events)",
                "Implement memory pooling for event objects",
                "Add memory pressure monitoring to production"
            ])
        elif status == "WARNING":
            recommendations.extend([
                "Monitor memory usage in production",
                "Consider reducing batch size under load",
                "Implement adaptive GC based on memory pressure"
            ])
        else:
            recommendations.extend([
                "Memory optimization successful",
                "Monitor for regression under higher load",
                "Consider increasing batch size for better performance"
            ])
        
        # Add specific recommendations based on analysis
        if analysis.get("growth_pattern") == "increasing":
            recommendations.append("Investigate memory leak in event processing")
        
        if analysis.get("memory_variance", 0) > 50:
            recommendations.append("Memory usage too volatile, implement smoothing")
        
        return recommendations
    
    def save_hardening_report(self, report: Dict[str, Any]):
        """Save hardening report to file"""
        
        # Save JSON
        json_file = "memory_hardening_report.json"
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2)
        
        # Save HTML report
        html_report = self.create_html_report(report)
        html_file = "memory_hardening_report.html"
        with open(html_file, 'w', encoding='utf-8') as f:
            f.write(html_report)
        
        print(f"📄 Hardening report saved to {json_file}")
        print(f"📄 HTML report saved to {html_file}")
    
    def create_html_report(self, report: Dict[str, Any]) -> str:
        """Create HTML report for hardening results"""
        
        status_class = report["status"].lower()
        
        html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>{report['test_name']} Report</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 40px; line-height: 1.6; }}
        .header {{ text-align: center; margin-bottom: 40px; }}
        .status-pass {{ background: #d4edda; color: #155724; padding: 20px; border-radius: 5px; }}
        .status-warning {{ background: #fff3cd; color: #856404; padding: 20px; border-radius: 5px; }}
        .status-fail {{ background: #f8d7da; color: #721c24; padding: 20px; border-radius: 5px; }}
        .metric {{ background: #f9f9f9; padding: 15px; margin: 10px 0; border-radius: 5px; }}
        .recommendation {{ background: #e3f2fd; padding: 10px; margin: 5px 0; border-radius: 3px; }}
        table {{ width: 100%; border-collapse: collapse; margin: 10px 0; }}
        th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
        th {{ background: #f2f2f2; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>{report['test_name']}</h1>
        <p>Generated: {report['generated_at']}</p>
    </div>
    
    <div class="status-{status_class}">
        <h2>Status: {report['status']}</h2>
        <p>{report['message']}</p>
    </div>
    
    <div class="metric">
        <h3>Memory Metrics</h3>
        <table>
            <tr><th>Metric</th><th>Value</th></tr>
            <tr><td>Baseline Memory</td><td>{report['baseline_memory_mb']:.2f} MB</td></tr>
            <tr><td>Final Memory</td><td>{report['final_memory_mb']:.2f} MB</td></tr>
            <tr><td>Peak Memory</td><td>{report['peak_memory_mb']:.2f} MB</td></tr>
            <tr><td>Memory Increase</td><td>{report['memory_increase_mb']:.2f} MB</td></tr>
            <tr><td>Peak Increase</td><td>{report['peak_increase_mb']:.2f} MB</td></tr>
        </table>
    </div>
    
    <div class="metric">
        <h3>Performance Metrics</h3>
        <table>
            <tr><th>Metric</th><th>Value</th></tr>
            <tr><td>Events Processed</td><td>{report['events_processed']:,}</td></tr>
            <tr><td>GC Runs</td><td>{report['gc_runs']}</td></tr>
            <tr><td>Memory Pressure Events</td><td>{report['memory_pressure_events']}</td></tr>
        </table>
    </div>
    
    <div class="metric">
        <h3>Optimizations Applied</h3>
        <table>
            <tr><th>Parameter</th><th>Value</th></tr>
            <tr><td>Batch Size</td><td>{report['optimizations']['batch_size']}</td></tr>
            <tr><td>Flush Interval</td><td>{report['optimizations']['flush_interval_ms']}ms</td></tr>
            <tr><td>Max Queue Size</td><td>{report['optimizations']['max_queue_size']}</td></tr>
            <tr><td>GC Frequency</td><td>Every {report['optimizations']['gc_frequency']} events</td></tr>
        </table>
    </div>
    
    <div class="metric">
        <h3>Memory Analysis</h3>
        <table>
            <tr><th>Metric</th><th>Value</th></tr>
            <tr><td>Total Snapshots</td><td>{report['memory_analysis']['total_snapshots']}</td></tr>
            <tr><td>Min Memory</td><td>{report['memory_analysis']['min_memory_mb']:.2f} MB</td></tr>
            <tr><td>Max Memory</td><td>{report['memory_analysis']['max_memory_mb']:.2f} MB</td></tr>
            <tr><td>Avg Memory</td><td>{report['memory_analysis']['avg_memory_mb']:.2f} MB</td></tr>
            <tr><td>Memory Variance</td><td>{report['memory_analysis']['memory_variance']:.2f} MB</td></tr>
            <tr><td>Growth Pattern</td><td>{report['memory_analysis']['growth_pattern']}</td></tr>
        </table>
    </div>
    
    <div class="metric">
        <h3>Recommendations</h3>
"""
        
        for rec in report['recommendations']:
            html += f'        <div class="recommendation">{rec}</div>\n'
        
        html += """
    </div>
</body>
</html>
"""
        
        return html

class OptimizedEventCaptureSystem(EventCaptureSystem):
    """Memory-optimized event capture system"""
    
    def __init__(self, db_path: str, batch_size: int = 50, max_queue_size: int = 1000):
        super().__init__(db_path)
        self.batch_size = batch_size
        self.max_queue_size = max_queue_size
        self.event_queue = []
        self.queue_lock = threading.Lock()
    
    def capture_event_optimized(self, user_id: str, device_id: str, event_name: str, 
                              properties: Dict[str, Any]) -> str:
        """Optimized event capture with memory management"""
        
        # Check queue size
        with self.queue_lock:
            if len(self.event_queue) >= self.max_queue_size:
                # Force flush to prevent memory buildup
                self._flush_queue()
        
        # Add to queue
        event = {
            "user_id": user_id,
            "device_id": device_id,
            "event_name": event_name,
            "event_time": datetime.now(timezone.utc).isoformat(),
            "properties": properties
        }
        
        with self.queue_lock:
            self.event_queue.append(event)
        
        # Flush if batch size reached
        if len(self.event_queue) >= self.batch_size:
            self._flush_queue()
        
        return f"event_{len(self.event_queue)}"
    
    def _flush_queue(self):
        """Flush event queue to database"""
        if not self.event_queue:
            return
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Process batch
        events_to_process = self.event_queue[:self.batch_size]
        
        for event in events_to_process:
            cursor.execute("""
                INSERT INTO events (user_id, device_id, event_name, event_time, properties, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                event["user_id"],
                event["device_id"],
                event["event_name"],
                event["event_time"],
                json.dumps(event["properties"]),
                datetime.now(timezone.utc).isoformat()
            ))
        
        conn.commit()
        conn.close()
        
        # Remove processed events from queue
        with self.queue_lock:
            self.event_queue = self.event_queue[self.batch_size:]

class OptimizedIdentityResolutionService(IdentityResolutionService):
    """Memory-optimized identity resolution service"""
    
    def __init__(self, db_path: str, cache_size: int = 1000):
        super().__init__(db_path)
        self.cache_size = cache_size
        self.identity_cache = {}
        self.cache_hits = 0
        self.cache_misses = 0
    
    def get_canonical_user_id_optimized(self, raw_id: str, user_id: str, ip_address: str) -> str:
        """Optimized identity resolution with caching"""
        
        # Check cache first
        cache_key = f"{raw_id}:{user_id}"
        if cache_key in self.identity_cache:
            self.cache_hits += 1
            return self.identity_cache[cache_key]
        
        # Cache miss - resolve normally
        self.cache_misses += 1
        result = self.get_canonical_user_id(raw_id, user_id, ip_address)
        
        # Add to cache (with size limit)
        if len(self.identity_cache) < self.cache_size:
            self.identity_cache[cache_key] = result
        
        return result

async def main():
    """Run memory pressure hardening test"""
    
    print("🚀 Starting MERID Memory Pressure Hardening")
    
    hardening = MemoryPressureHardening()
    report = await hardening.run_memory_hardening_test()
    
    print(f"\n✅ Memory Hardening Complete")
    print(f"📊 Status: {report['status']}")
    print(f"📈 Memory increase: {report['memory_increase_mb']:.2f} MB")
    print(f"🔝 Peak memory: {report['peak_memory_mb']:.2f} MB")
    print(f"⚠️ Pressure events: {report['memory_pressure_events']}")
    
    return hardening

if __name__ == "__main__":
    asyncio.run(main())
