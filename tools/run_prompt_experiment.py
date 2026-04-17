#!/usr/bin/env python3
"""
Simple HTTP-based Prompt Experiment Driver

Runs prompt experiments through the same HTTP endpoint as the dashboard.
"""

import argparse
import json
import statistics
import time
import uuid
import yaml
import requests
from pathlib import Path

def load_config(path):
    """Load experiment configuration from YAML."""
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def run_variant(cfg, variant_name):
    """Run all runs for a single variant."""
    url = f"{cfg['base_url']}/api/v1/institutional/agents/{cfg['agent_id']}/analyze"
    
    # Base params from config
    params = cfg["filters"].copy()
    params["max_opportunities"] = params.get("max_opportunities", 10)
    
    # Headers for experiment tracking
    headers = {
        "X-MERID-AGENT-VERSION": variant_name,
        "X-MERID-EXPERIMENT-ID": cfg["id"],
    }
    
    results = {
        "variant": variant_name,
        "brier_scores": [],
        "latencies": [],
        "success_count": 0,
        "error_count": 0
    }
    
    print(f"🚀 Running {variant_name} ({cfg['runs_per_variant']} runs)")
    
    for i in range(cfg["runs_per_variant"]):
        run_id = f"{variant_name}-{uuid.uuid4()}"
        t0 = time.time()
        
        try:
            # Use experiment config timeout if available, otherwise default to 30s
            timeout = cfg.get("experiment_config", {}).get("llm_timeout", 30)
            resp = requests.post(url, params=params, headers=headers, timeout=timeout)
            dt = (time.time() - t0) * 1000
            
            if resp.status_code == 200:
                result = resp.json()
                if result.get("status") == "success":
                    analysis = result.get("analysis", {})
                    brier_score = analysis.get("brier_score")
                    
                    if brier_score is not None:
                        results["brier_scores"].append(brier_score)
                    
                    results["latencies"].append(dt)
                    results["success_count"] += 1
                    
                    print(f"   Run {i + 1}/{cfg['runs_per_variant']}: ✅ Brier={brier_score:.4f}, Latency={dt:.0f}ms")
                else:
                    results["latencies"].append(dt)
                    results["error_count"] += 1
                    print(f"   Run {i + 1}/{cfg['runs_per_variant']}: ❌ {result.get('error', 'Unknown error')}")
            else:
                results["latencies"].append(dt)
                results["error_count"] += 1
                print(f"   Run {i + 1}/{cfg['runs_per_variant']}: ❌ HTTP {resp.status_code}")
                
        except Exception as e:
            dt = (time.time() - t0) * 1000
            results["latencies"].append(dt)
            results["error_count"] += 1
            print(f"   Run {i + 1}/{cfg['runs_per_variant']}: ❌ {e}")
    
    return results

def summarize_experiment(cfg, variant_results):
    """Summarize experiment results."""
    print(f"\n📊 Experiment Summary: {cfg['id']}")
    print("=" * 50)
    
    winner = None
    best_brier = float('inf')
    
    for variant_name, results in variant_results.items():
        if results["brier_scores"]:
            avg_brier = statistics.mean(results["brier_scores"])
            avg_latency = statistics.mean(results["latencies"])
            success_rate = results["success_count"] / cfg["runs_per_variant"]
            
            print(f"\n{variant_name}:")
            print(f"  Avg Brier: {avg_brier:.4f}")
            print(f"  Avg Latency: {avg_latency:.0f}ms")
            print(f"  Success Rate: {success_rate:.1%}")
            print(f"  Runs: {results['success_count']}/{cfg['runs_per_variant']}")
            
            if avg_brier < best_brier:
                best_brier = avg_brier
                winner = variant_name
    
    if winner:
        print(f"\n🏆 Winner: {winner} (Brier: {best_brier:.4f})")
        
        # Calculate improvement
        briers = [(name, statistics.mean(results["brier_scores"])) 
                 for name, results in variant_results.items() 
                 if results["brier_scores"]]
        
        if len(briers) >= 2:
            briers.sort(key=lambda x: x[1])
            improvement = ((briers[1][1] - briers[0][1]) / briers[1][1]) * 100
            print(f"📈 Improvement: {improvement:.1f}% over {briers[1][0]}")
    
    # Save results
    output_dir = Path("experiments/results")
    output_dir.mkdir(exist_ok=True)
    
    results_file = output_dir / f"{cfg['id']}.json"
    experiment_data = {
        "timestamp": time.time(),
        "config": cfg,
        "results": variant_results,
        "winner": winner,
        "best_brier": best_brier if winner != float('inf') else None
    }
    
    with results_file.open("w", encoding="utf-8") as f:
        json.dump(experiment_data, f, indent=2, default=str)
    
    print(f"\n💾 Results saved to: {results_file}")

def main():
    parser = argparse.ArgumentParser(description="Run prompt experiments via HTTP API")
    parser.add_argument("--config", default="experiments/prompt_experiments.yaml")
    parser.add_argument("--base-url", required=True, help="API base URL (e.g., http://localhost:8000)")
    
    args = parser.parse_args()
    
    print("🔬 MERID Prompt Experiment Driver")
    print("=" * 50)
    
    try:
        cfg = load_config(args.config)
        cfg["base_url"] = args.base_url
        
        print(f"📋 Experiment: {cfg['id']}")
        print(f"📝 Description: {cfg['description']}")
        print(f"🎯 Agent: {cfg['agent_id']}")
        print(f"🔄 Runs per variant: {cfg['runs_per_variant']}")
        print(f"🔍 Filters: {cfg['filters']}")
        print()
        
        variant_results = {}
        
        for variant in cfg["variants"]:
            variant_name = variant["name"]
            results = run_variant(cfg, variant_name)
            variant_results[variant_name] = results
        
        summarize_experiment(cfg, variant_results)
        
    except Exception as e:
        print(f"❌ Experiment failed: {e}")
        return 1
    
    return 0

if __name__ == "__main__":
    exit(main())
