#!/usr/bin/env python3
"""
Run focused fault injection test for MERID swarm resilience
"""

import sys
import os
sys.path.append('.')
sys.path.append('swarm')

from swarm.testing.baseline_suite import baseline_suite

def main():
    print('=== Focused Fault Injection Test ===')
    
    # Run fault injection tests
    fault_modes = ['flaky_tool']
    fault_results = baseline_suite.run_fault_injection_tests(fault_modes)
    
    print(f'\n=== FAULT INJECTION RESULTS ===')
    
    for fault_mode, results in fault_results.items():
        print(f'\n{fault_mode.upper()} Results:')
        
        if not results:
            print('  No results available')
            continue
        
        # Calculate metrics
        total_tasks = len(results)
        successful_tasks = sum(1 for r in results if r.success)
        success_rate = successful_tasks / total_tasks if total_tasks > 0 else 0
        
        avg_cascade_size = sum(r.cascade_size for r in results) / len(results) if results else 0
        avg_branching_factor = sum(r.branching_factor for r in results) / len(results) if results else 0
        avg_retry_index = sum(r.retry_index for r in results) / len(results) if results else 0
        
        # Calculate misalignment
        all_misalignment_scores = []
        for r in results:
            all_misalignment_scores.extend(r.misalignment_scores.values())
        avg_misalignment = sum(all_misalignment_scores) / len(all_misalignment_scores) if all_misalignment_scores else 0
        
        print(f'  Tasks run: {total_tasks}')
        print(f'  Success rate: {success_rate:.2%}')
        print(f'  Avg cascade size: {avg_cascade_size:.2f}')
        print(f'  Avg branching factor: {avg_branching_factor:.2f}')
        print(f'  Avg retry index: {avg_retry_index:.2f}')
        print(f'  Avg misalignment: {avg_misalignment:.3f}')
        
        # Show individual task results
        print(f'  Individual results:')
        for i, result in enumerate(results[:5]):  # Show first 5
            status = "✓" if result.success else "✗"
            print(f'    {status} Task {i+1}: cascade={result.cascade_size}, retry={result.retry_index:.2f}')
    
    return fault_results

if __name__ == "__main__":
    main()
