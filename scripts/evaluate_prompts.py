#!/usr/bin/env python3
"""Script to evaluate MERID prompts and generate benchmark reports.

Usage:
    python evaluate_prompts.py --output=benchmark.json
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.prompt_eval import PromptEvaluator, MERID_TEST_CASES


async def main():
    parser = argparse.ArgumentParser(description="Evaluate MERID prompts")
    parser.add_argument("--output", type=str, default="prompt_benchmark.json", help="Output file path")
    parser.add_argument("--test-cases", type=str, help="JSON file with custom test cases")
    args = parser.parse_args()
    
    print("🧪 Starting MERID prompt evaluation...")
    print(f"📊 Test cases: {len(MERID_TEST_CASES)}")
    print()
    
    # Initialize evaluator
    evaluator = PromptEvaluator()
    
    # Run benchmark
    results = await evaluator.run_benchmark(MERID_TEST_CASES)
    
    # Generate report
    report = evaluator.generate_report(results)
    print(report)
    print()
    
    # Save results
    output_data = {
        "results": [
            {
                "prompt_name": r.prompt_name,
                "test_case": r.test_case,
                "model": r.model,
                "passed": r.passed,
                "score": r.score,
                "metrics": r.metrics,
                "latency_ms": r.latency_ms,
                "tokens_used": r.tokens_used,
                "error": r.error
            }
            for r in results
        ],
        "summary": {
            "total": len(results),
            "passed": sum(1 for r in results if r.passed),
            "failed": sum(1 for r in results if not r.passed),
            "avg_score": sum(r.score for r in results) / len(results) if results else 0,
            "avg_latency_ms": sum(r.latency_ms for r in results) / len(results) if results else 0
        }
    }
    
    with open(args.output, 'w') as f:
        json.dump(output_data, f, indent=2)
    
    print(f"✅ Results saved to: {args.output}")
    
    # Exit with error if any tests failed
    if output_data["summary"]["failed"] > 0:
        print(f"⚠️  {output_data['summary']['failed']} tests failed")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
