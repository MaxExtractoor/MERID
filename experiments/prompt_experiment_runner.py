#!/usr/bin/env python3
"""
Prompt Experiment Framework for MERID Agent Optimization

This script runs controlled A/B tests between different prompt variants
to measure impact on calibration metrics (Brier score, bucket distribution).
"""

import asyncio
import json
import time
import uuid
from pathlib import Path
from typing import Dict, List, Any
from dataclasses import dataclass
from agents.prediction_arbitrage_analyst import PredictionArbitrageAnalystAgent, log_agent_run, AgentRunLog

@dataclass
class PromptVariant:
    """Definition of a prompt variant for testing."""
    name: str
    version: str  # Used in agent_version field
    description: str
    # Future: actual prompt content when we make prompts configurable

@dataclass
class ExperimentConfig:
    """Configuration for a prompt experiment."""
    experiment_id: str
    variants: List[PromptVariant]
    runs_per_variant: int
    fixed_filters: Dict[str, Any]
    description: str

class PromptExperimentRunner:
    """Runs controlled prompt experiments with proper logging."""
    
    def __init__(self):
        self.experiment_results = {}
    
    async def run_experiment(self, config: ExperimentConfig) -> Dict[str, Any]:
        """Run a complete prompt experiment."""
        print(f"🧪 Starting Experiment: {config.experiment_id}")
        print(f"📋 Description: {config.description}")
        print(f"🔄 Variants: {[v.name for v in config.variants]}")
        print(f"📊 Runs per variant: {config.runs_per_variant}")
        print(f"🔍 Fixed filters: {config.fixed_filters}")
        print()
        
        results = {}
        
        for variant in config.variants:
            print(f"🚀 Running variant: {variant.name} ({variant.version})")
            variant_results = await self._run_variant(config, variant)
            results[variant.name] = variant_results
            
            # Print interim results
            avg_brier = variant_results["avg_brier_score"]
            avg_latency = variant_results["avg_latency_ms"]
            success_rate = variant_results["success_rate"]
            
            print(f"   ✅ Avg Brier: {avg_brier:.4f}")
            print(f"   ⏱️  Avg Latency: {avg_latency:.0f}ms")
            print(f"   📈 Success Rate: {success_rate:.1%}")
            print()
        
        # Calculate experiment summary
        summary = self._calculate_experiment_summary(config, results)
        self._save_experiment_results(config, results, summary)
        
        return {
            "experiment_id": config.experiment_id,
            "config": config,
            "results": results,
            "summary": summary
        }
    
    async def _run_variant(self, config: ExperimentConfig, variant: PromptVariant) -> Dict[str, Any]:
        """Run all runs for a single variant."""
        agent = PredictionArbitrageAnalystAgent()
        
        # Override agent version for this variant
        original_model_name = agent.model_name
        agent.model_name = f"{original_model_name}-{variant.version}"
        
        brier_scores = []
        latencies = []
        success_count = 0
        bucket_distributions = {f"{i*0.4}-{(i+1)*0.4}": 0 for i in range(4)}
        
        for run_num in range(config.runs_per_variant):
            # Create controlled energy packet
            energy = {
                "energy_id": f"{config.experiment_id}-{variant.name}-{run_num}-{uuid.uuid4().hex[:8]}",
                "source": "prompt_experiment",
                "run_type": "prompt-experiment",
                "experiment_id": config.experiment_id,
                "payload": config.fixed_filters
            }
            
            start_time = time.time()
            
            try:
                # Run the agent
                result = await agent.process(energy, phase="analysis")
                end_time = time.time()
                
                # Extract metrics
                analysis = result.get("analysis", {})
                brier_score = analysis.get("brier_score")
                latency_ms = (end_time - start_time) * 1000
                
                if brier_score is not None:
                    brier_scores.append(brier_score)
                
                latencies.append(latency_ms)
                success_count += 1
                
                # Track bucket distribution
                bucket_stats = analysis.get("bucket_analysis", [])
                for bucket in bucket_stats:
                    bucket_range = bucket.get("bucket_range", "")
                    count = bucket.get("count", 0)
                    if bucket_range in bucket_distributions:
                        bucket_distributions[bucket_range] += count
                
                print(f"   Run {run_num + 1}/{config.runs_per_variant}: Brier={brier_score:.4f}, Latency={latency_ms:.0f}ms")
                
            except Exception as e:
                print(f"   Run {run_num + 1}/{config.runs_per_variant}: FAILED - {e}")
                latencies.append((time.time() - start_time) * 1000)
        
        # Calculate variant statistics
        avg_brier = sum(brier_scores) / len(brier_scores) if brier_scores else None
        avg_latency = sum(latencies) / len(latencies)
        success_rate = success_count / config.runs_per_variant
        
        return {
            "variant": variant.name,
            "version": variant.version,
            "avg_brier_score": avg_brier,
            "avg_latency_ms": avg_latency,
            "success_rate": success_rate,
            "total_runs": config.runs_per_variant,
            "successful_runs": success_count,
            "brier_scores": brier_scores,
            "bucket_distribution": bucket_distributions
        }
    
    def _calculate_experiment_summary(self, config: ExperimentConfig, results: Dict[str, Any]) -> Dict[str, Any]:
        """Calculate experiment-level summary statistics."""
        summary = {
            "experiment_id": config.experiment_id,
            "total_runs": config.runs_per_variant * len(config.variants),
            "variants_compared": len(config.variants),
            "winner": None,
            "statistical_significance": False,
            "key_insights": []
        }
        
        # Find winner (lowest average Brier score)
        best_variant = None
        best_brier = float('inf')
        
        for variant_name, variant_result in results.items():
            avg_brier = variant_result["avg_brier_score"]
            if avg_brier is not None and avg_brier < best_brier:
                best_brier = avg_brier
                best_variant = variant_name
        
        if best_variant:
            summary["winner"] = {
                "variant": best_variant,
                "avg_brier_score": best_brier
            }
            
            # Calculate improvement over second best
            sorted_variants = sorted(
                [(name, result["avg_brier_score"]) for name, result in results.items() if result["avg_brier_score"] is not None],
                key=lambda x: x[1]
            )
            
            if len(sorted_variants) >= 2:
                improvement = (sorted_variants[1][1] - sorted_variants[0][1]) / sorted_variants[1][1]
                summary["improvement_percent"] = improvement * 100
                summary["key_insights"].append(f"{best_variant} improves Brier score by {improvement*100:.1f}% over {sorted_variants[1][0]}")
        
        # Add latency insights
        latencies = [(name, result["avg_latency_ms"]) for name, result in results.items()]
        fastest = min(latencies, key=lambda x: x[1])
        slowest = max(latencies, key=lambda x: x[1])
        
        if fastest[1] != slowest[1]:
            latency_diff = slowest[1] - fastest[1]
            summary["key_insights"].append(f"{fastest[0]} is {latency_diff:.0f}ms faster than {slowest[0]}")
        
        return summary
    
    def _save_experiment_results(self, config: ExperimentConfig, results: Dict[str, Any], summary: Dict[str, Any]):
        """Save experiment results to file."""
        output_dir = Path("experiments")
        output_dir.mkdir(exist_ok=True)
        
        output_file = output_dir / f"{config.experiment_id}.json"
        
        experiment_data = {
            "timestamp": time.time(),
            "config": {
                "experiment_id": config.experiment_id,
                "description": config.description,
                "variants": [{"name": v.name, "version": v.version, "description": v.description} for v in config.variants],
                "runs_per_variant": config.runs_per_variant,
                "fixed_filters": config.fixed_filters
            },
            "results": results,
            "summary": summary
        }
        
        with output_file.open("w", encoding="utf-8") as f:
            json.dump(experiment_data, f, indent=2, default=str)
        
        print(f"💾 Experiment results saved to: {output_file}")
        print(f"📊 Summary: {summary.get('winner', {}).get('variant', 'No clear winner')} wins")
        for insight in summary.get("key_insights", []):
            print(f"   💡 {insight}")

# Example experiment configurations
def create_sample_experiments() -> List[ExperimentConfig]:
    """Create sample experiment configurations."""
    
    # Experiment 1: Prompt focus comparison
    experiment_1 = ExperimentConfig(
        experiment_id="arb-prompt-2026-01-24",
        variants=[
            PromptVariant(
                name="liquidity-focused",
                version="prompt-A",
                description="Focus on liquidity and venue diversity"
            ),
            PromptVariant(
                name="spread-focused", 
                version="prompt-B",
                description="Focus on spread maximization and time decay"
            )
        ],
        runs_per_variant=10,  # Reduced for demo, use 50+ for real experiments
        fixed_filters={
            "min_spread": 0.05,
            "min_liquidity": 50000.0,
            "categories": ["crypto"]
        },
        description="Compare liquidity-focused vs spread-focused prompt strategies"
    )
    
    return [experiment_1]

async def main():
    """Run prompt experiments."""
    print("🔬 MERID Prompt Experiment Framework")
    print("=" * 50)
    
    experiments = create_sample_experiments()
    
    for experiment in experiments:
        print()
        runner = PromptExperimentRunner()
        results = await runner.run_experiment(experiment)
        
        # Print final summary
        summary = results["summary"]
        print(f"\n🎯 Experiment Complete: {summary['experiment_id']}")
        if summary.get("winner"):
            winner = summary["winner"]
            print(f"🏆 Winner: {winner['variant']} (Brier: {winner['avg_brier_score']:.4f})")
        
        for insight in summary.get("key_insights", []):
            print(f"💡 {insight}")

if __name__ == "__main__":
    asyncio.run(main())
