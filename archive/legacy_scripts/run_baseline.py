#!/usr/bin/env python3
"""
Run full 46-task baseline test for MERID swarm resilience
"""

import sys
import os
sys.path.append('.')
sys.path.append('swarm')

from swarm.testing.baseline_suite import baseline_suite

def main():
    print('=== Running Full 46-Task Baseline Test ===')
    results = baseline_suite.run_baseline_tests()
    
    print(f'\n=== BASELINE RESULTS ===')
    print(f'Total tasks: {results["test_summary"]["total_tasks"]}')
    print(f'Success rate: {results["test_summary"]["success_rate"]:.2%}')
    print(f'Avg duration per task: {results["test_summary"]["avg_duration_per_task"]:.2f}s')
    
    print(f'\nCascade Metrics:')
    print(f'  Avg cascade size: {results["cascade_metrics"]["avg_cascade_size"]:.2f}')
    print(f'  Avg cascade depth: {results["cascade_metrics"]["avg_cascade_depth"]:.2f}')
    print(f'  Avg branching factor: {results["cascade_metrics"]["avg_branching_factor"]:.2f}')
    print(f'  Max cascade size: {results["cascade_metrics"]["max_cascade_size"]}')
    
    print(f'\nOperational Metrics:')
    print(f'  Avg retry index: {results["operational_metrics"]["avg_retry_index"]:.2f}')
    print(f'  Total human interventions: {results["operational_metrics"]["total_human_interventions"]}')
    print(f'  Avg turns per task: {results["operational_metrics"]["avg_turns_per_task"]:.1f}')
    
    print(f'\nMisalignment Metrics:')
    print(f'  Avg misalignment: {results["misalignment_metrics"]["avg_misalignment_score"]:.3f}')
    print(f'  Total agent pairs: {results["misalignment_metrics"]["total_agent_pairs"]}')
    
    print(f'\nTopology Analysis:')
    print(f'  Behavior pattern: {results["topology_analysis"]["behavior_pattern"]}')
    print(f'  Resilience: {results["topology_analysis"]["resilience_characteristics"]}')
    
    print(f'\nRecommendations:')
    for rec in results["recommendations"]:
        print(f'  - {rec}')
    
    # Export results
    baseline_suite.export_results('full_baseline_results.json')
    print(f'\nResults exported to full_baseline_results.json')
    
    return results

if __name__ == "__main__":
    main()
