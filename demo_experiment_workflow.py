#!/usr/bin/env python3
"""
Demo of the experiment framework - shows the complete workflow
without requiring the API server to be running.
"""

import json
import time
import uuid
from pathlib import Path

def create_mock_experiment_results():
    """Create mock experiment results to demonstrate the workflow."""
    
    # Simulate running the experiment
    print("🔬 MERID Prompt Experiment Driver")
    print("=" * 50)
    print("📋 Experiment: arb-prompt-2026-01-24")
    print("📝 Description: Prompt variant test for prediction arbitrage analyst")
    print("🎯 Agent: prediction-arbitrage-analyst-01")
    print("🔄 Runs per variant: 5")
    print("🔍 Filters: {'min_spread': 0.05, 'min_liquidity': 50000.0, 'categories': ['crypto']}")
    print()
    
    # Mock results for prompt-A
    prompt_a_results = {
        "variant": "prompt-A",
        "brier_scores": [0.003889, 0.004123, 0.003456, 0.004234, 0.003789],
        "latencies": [850.0, 920.0, 880.0, 950.0, 870.0],
        "success_count": 5,
        "error_count": 0
    }
    
    # Mock results for prompt-B
    prompt_b_results = {
        "variant": "prompt-B", 
        "brier_scores": [0.005234, 0.004876, 0.005123, 0.004987, 0.005345],
        "latencies": [820.0, 890.0, 860.0, 910.0, 850.0],
        "success_count": 5,
        "error_count": 0
    }
    
    print("🚀 Running prompt-A (5 runs)")
    for i, (brier, latency) in enumerate(zip(prompt_a_results["brier_scores"], prompt_a_results["latencies"]), 1):
        print(f"   Run {i}/5: ✅ Brier={brier:.4f}, Latency={latency:.0f}ms")
    
    print("🚀 Running prompt-B (5 runs)")
    for i, (brier, latency) in enumerate(zip(prompt_b_results["brier_scores"], prompt_b_results["latencies"]), 1):
        print(f"   Run {i}/5: ✅ Brier={brier:.4f}, Latency={latency:.0f}ms")
    
    # Calculate summary
    import statistics
    
    avg_brier_a = statistics.mean(prompt_a_results["brier_scores"])
    avg_latency_a = statistics.mean(prompt_a_results["latencies"])
    
    avg_brier_b = statistics.mean(prompt_b_results["brier_scores"])
    avg_latency_b = statistics.mean(prompt_b_results["latencies"])
    
    print(f"\n📊 Experiment Summary: arb-prompt-2026-01-24")
    print("=" * 50)
    
    print(f"\nprompt-A:")
    print(f"  Avg Brier: {avg_brier_a:.4f}")
    print(f"  Avg Latency: {avg_latency_a:.0f}ms")
    print(f"  Success Rate: 100.0%")
    print(f"  Runs: 5/5")
    
    print(f"\nprompt-B:")
    print(f"  Avg Brier: {avg_brier_b:.4f}")
    print(f"  Avg Latency: {avg_latency_b:.0f}ms")
    print(f"  Success Rate: 100.0%")
    print(f"  Runs: 5/5")
    
    # Determine winner
    winner = "prompt-A" if avg_brier_a < avg_brier_b else "prompt-B"
    best_brier = min(avg_brier_a, avg_brier_b)
    improvement = ((max(avg_brier_a, avg_brier_b) - min(avg_brier_a, avg_brier_b)) / max(avg_brier_a, avg_brier_b)) * 100
    
    print(f"\n🏆 Winner: {winner} (Brier: {best_brier:.4f})")
    print(f"📈 Improvement: {improvement:.1f}% over {'prompt-B' if winner == 'prompt-A' else 'prompt-A'}")
    
    # Save results
    output_dir = Path("experiments/results")
    output_dir.mkdir(exist_ok=True)
    
    results_file = output_dir / f"arb-prompt-2026-01-24.json"
    experiment_data = {
        "timestamp": time.time(),
        "config": {
            "id": "arb-prompt-2026-01-24",
            "description": "Prompt variant test for prediction arbitrage analyst",
            "agent_id": "prediction-arbitrage-analyst-01",
            "runs_per_variant": 5,
            "filters": {"min_spread": 0.05, "min_liquidity": 50000.0, "categories": ["crypto"]}
        },
        "results": {
            "prompt-A": prompt_a_results,
            "prompt-B": prompt_b_results
        },
        "winner": winner,
        "best_brier": best_brier
    }
    
    with results_file.open("w", encoding="utf-8") as f:
        json.dump(experiment_data, f, indent=2, default=str)
    
    print(f"\n💾 Results saved to: {results_file}")
    
    return experiment_data

def demo_log_analysis():
    """Demonstrate log analysis with the generated results."""
    print("\n🔍 Analyzing Experiment Results")
    print("=" * 50)
    
    # Load the results we just created
    results_file = Path("experiments/results/arb-prompt-2026-01-24.json")
    if results_file.exists():
        with results_file.open("r", encoding="utf-8") as f:
            data = json.load(f)
        
        print(f"📊 Experiment: {data['config']['id']}")
        print(f"📝 Description: {data['config']['description']}")
        print(f"🏆 Winner: {data['winner']}")
        print(f"📈 Best Brier: {data['best_brier']:.4f}")
        
        # Show variant comparison
        for variant, results in data["results"].items():
            import statistics
            avg_brier = statistics.mean(results["brier_scores"])
            avg_latency = statistics.mean(results["latencies"])
            
            print(f"\n{variant}:")
            print(f"  Avg Brier: {avg_brier:.4f}")
            print(f"  Avg Latency: {avg_latency:.0f}ms")
            print(f"  Success Rate: {results['success_count']}/{data['config']['runs_per_variant']}")
    
    print("\n✅ Experiment workflow demo complete!")

if __name__ == "__main__":
    # Run the complete demo
    create_mock_experiment_results()
    demo_log_analysis()
