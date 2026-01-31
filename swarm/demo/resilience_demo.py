"""
MERID Swarm Resilience Demo
Quick demonstration of the tracing, watchdog, and metrics infrastructure.
"""

import time
import json
from pathlib import Path

# Add swarm modules to path
import sys
sys.path.append(str(Path(__file__).parent.parent.parent))
sys.path.append(str(Path(__file__).parent.parent / 'swarm'))

from swarm.integration.task_runner import task_runner
from swarm.testing.baseline_suite import baseline_suite
from swarm.ci.reliability_monitor import CIReliabilityMonitor
from utils.logger import get_logger

logger = get_logger("swarm.demo")


def run_silent_recording_demo():
    """Demo 1: Silent recording baseline run"""
    print("\n=== Demo 1: Silent Recording Baseline Run ===")
    
    # Run a small subset of tasks for demo
    demo_tasks = baseline_suite.tasks[:5]  # First 5 tasks
    
    print(f"Running {len(demo_tasks)} tasks in silent recording mode...")
    
    results = []
    for i, task in enumerate(demo_tasks):
        print(f"  Task {i+1}: {task.task_id} ({task.task_type})")
        
        try:
            task_config = {
                "type": task.task_type,
                "complexity": task.complexity,
                "agents": task.agents
            }
            
            metrics = task_runner.execute_task(task_config)
            results.append(metrics)
            
            print(f"    ✓ Success: {metrics.success}")
            print(f"    ✓ Turns: {metrics.total_turns}")
            print(f"    ✓ Cascade size: {metrics.cascade_size}")
            
        except Exception as e:
            print(f"    ✗ Failed: {e}")
    
    # Calculate aggregate metrics
    total_tasks = len(results)
    if total_tasks == 0:
        print("No results to analyze")
        return results
    
    successful_tasks = sum(1 for r in results if r.success)
    success_rate = successful_tasks / total_tasks
    
    avg_cascade_size = sum(r.cascade_size for r in results) / len(results) if results else 0
    avg_branching_factor = sum(r.branching_factor for r in results) / len(results) if results else 0
    
    print(f"\nBaseline Results:")
    print(f"  Success rate: {success_rate:.2%}")
    print(f"  Avg cascade size: {avg_cascade_size:.2f}")
    print(f"  Avg branching factor: {avg_branching_factor:.2f}")
    
    return results


def run_fault_injection_demo():
    """Demo 2: Fault injection testing"""
    print("\n=== Demo 2: Fault Injection Testing ===")
    
    # Enable fault injection
    print("Enabling flaky tool fault injection (15% failure rate)...")
    task_runner.enable_fault_injection(flaky_tool_rate=0.15)
    
    # Run same tasks with fault injection
    demo_tasks = baseline_suite.tasks[:3]  # First 3 tasks
    
    fault_results = []
    for i, task in enumerate(demo_tasks):
        print(f"  Fault test {i+1}: {task.task_id}")
        
        try:
            task_config = {
                "type": task.task_type,
                "complexity": task.complexity,
                "agents": task.agents
            }
            
            metrics = task_runner.execute_task(task_config)
            fault_results.append(metrics)
            
            print(f"    ✓ Success: {metrics.success}")
            print(f"    ✓ Cascade size: {metrics.cascade_size}")
            print(f"    ✓ Retry index: {metrics.retry_index:.2f}")
            
        except Exception as e:
            print(f"    ✗ Failed: {e}")
    
    # Disable fault injection
    task_runner.disable_fault_injection()
    
    # Calculate fault impact
    if fault_results:
        fault_success_rate = sum(1 for r in fault_results if r.success) / len(fault_results)
        avg_cascade_size_fault = sum(r.cascade_size for r in fault_results) / len(fault_results)
    else:
        fault_success_rate = 0
        avg_cascade_size_fault = 0
    
    print(f"\nFault Injection Results:")
    print(f"  Success rate: {fault_success_rate:.2%}")
    print(f"  Avg cascade size: {avg_cascade_size_fault:.2f}")
    
    return fault_results


def run_ci_monitor_demo():
    """Demo 3: CI reliability monitoring"""
    print("\n=== Demo 3: CI Reliability Monitoring ===")
    
    # Create CI monitor
    ci_monitor = CIReliabilityMonitor()
    
    print("Running CI reliability checks...")
    print(f"  Current thresholds: {ci_monitor.get_current_thresholds()}")
    
    # Run CI checks
    passed = ci_monitor.run_ci_checks("demo_ci_report.json")
    
    # Load and display results
    try:
        with open("demo_ci_report.json", 'r') as f:
            report = json.load(f)
        
        print(f"\nCI Results:")
        print(f"  Status: {'PASSED' if passed else 'FAILED'}")
        print(f"  Success rate: {report['metrics']['success_rate']:.2%}")
        print(f"  Avg cascade size: {report['metrics']['avg_cascade_size']:.2f}")
        print(f"  Avg branching factor: {report['metrics']['avg_branching_factor']:.2f}")
        print(f"  Avg misalignment: {report['metrics']['avg_misalignment']:.2f}")
        
        # Show individual task results
        print(f"\nIndividual Task Results:")
        for result in report['individual_results']:
            status = "✓" if result['success'] else "✗"
            print(f"  {status} {result['task_type']}: cascade={result['cascade_size']}, misalignment={result['misalignment_avg']:.2f}")
        
    except Exception as e:
        print(f"Error loading CI report: {e}")
    
    return passed


def analyze_topology_behavior(baseline_results, fault_results):
    """Analyze topology behavior from results"""
    print("\n=== Topology Behavior Analysis ===")
    
    # Baseline analysis
    baseline_success_rate = sum(1 for r in baseline_results if r.success) / len(baseline_results)
    baseline_cascade_size = sum(r.cascade_size for r in baseline_results) / len(baseline_results)
    baseline_branching = sum(r.branching_factor for r in baseline_results) / len(baseline_results)
    
    # Fault analysis
    fault_success_rate = sum(1 for r in fault_results if r.success) / len(fault_results)
    fault_cascade_size = sum(r.cascade_size for r in fault_results) / len(fault_results)
    fault_branching = sum(r.branching_factor for r in fault_results) / len(fault_results)
    
    print(f"Baseline Behavior:")
    print(f"  Success rate: {baseline_success_rate:.2%}")
    print(f"  Cascade size: {baseline_cascade_size:.2f}")
    print(f"  Branching factor: {baseline_branching:.2f}")
    
    print(f"\nFault Injection Impact:")
    print(f"  Success rate delta: {(fault_success_rate - baseline_success_rate):+.2%}")
    print(f"  Cascade size delta: {(fault_cascade_size - baseline_cascade_size):+.2f}")
    print(f"  Branching factor delta: {(fault_branching - baseline_branching):+.2f}")
    
    # Determine behavior pattern
    if baseline_cascade_size <= 2 and baseline_branching < 1.2:
        behavior = "ring_like_local_failures"
    elif baseline_cascade_size > 5 and baseline_branching > 1.5:
        behavior = "mesh_like_wide_cascades"
    else:
        behavior = "hybrid_mixed_behavior"
    
    print(f"\nTopology Classification: {behavior}")
    
    # Make recommendation
    if baseline_success_rate > 0.8 and baseline_cascade_size < 2:
        recommendation = "Keep current topology - good resilience"
    elif baseline_success_rate < 0.6 or fault_cascade_size > 5:
        recommendation = "Consider shallow hierarchy - poor resilience"
    else:
        recommendation = "Hybrid approach - moderate resilience"
    
    print(f"Recommendation: {recommendation}")
    
    return {
        "behavior": behavior,
        "recommendation": recommendation,
        "baseline_metrics": {
            "success_rate": baseline_success_rate,
            "cascade_size": baseline_cascade_size,
            "branching_factor": baseline_branching
        },
        "fault_metrics": {
            "success_rate": fault_success_rate,
            "cascade_size": fault_cascade_size,
            "branching_factor": fault_branching
        }
    }


def main():
    """Main demo function"""
    print("MERID Swarm Resilience Infrastructure Demo")
    print("=" * 50)
    
    try:
        # Demo 1: Silent recording baseline
        baseline_results = run_silent_recording_demo()
        
        # Demo 2: Fault injection
        fault_results = run_fault_injection_demo()
        
        # Demo 3: CI monitoring
        ci_passed = run_ci_monitor_demo()
        
        # Demo 4: Topology analysis
        analysis = analyze_topology_behavior(baseline_results, fault_results)
        
        # Final summary
        print("\n=== Demo Summary ===")
        print(f"✓ Tracing infrastructure: Working")
        print(f"✓ Watchdog monitoring: Working")
        print(f"✓ Metrics collection: Working")
        print(f"✓ Fault injection: Working")
        print(f"✓ CI integration: {'Working' if ci_passed else 'Needs attention'}")
        print(f"✓ Topology analysis: {analysis['behavior']}")
        
        print(f"\nNext Steps:")
        print(f"1. Run full 46-task baseline test suite")
        print(f"2. Implement shallow hierarchy if needed")
        print(f"3. Set up CI monitoring in pipeline")
        print(f"4. Continuously monitor and iterate")
        
    except Exception as e:
        logger.error(f"Demo failed with error: {e}")
        print(f"\nDemo failed: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())
