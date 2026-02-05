#!/usr/bin/env python3
"""Script to run autonomous coverage fixing.

Usage:
    python autonomous_coverage_fix.py --modules='["core/module.py"]' --target-coverage=85
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.autonomous_fixer import AutonomousCoverageFixer, BatchCoverageFixer


async def main():
    parser = argparse.ArgumentParser(description="Autonomous coverage fixing")
    parser.add_argument("--modules", type=str, required=True, help="JSON array of module paths")
    parser.add_argument("--target-coverage", type=float, default=85.0, help="Target coverage %")
    parser.add_argument("--output-report", type=str, default="fix_report.md", help="Report output path")
    args = parser.parse_args()
    
    # Parse modules
    try:
        modules = json.loads(args.modules)
    except json.JSONDecodeError:
        print("Error: --modules must be a valid JSON array", file=sys.stderr)
        sys.exit(1)
    
    print(f"🤖 DevSwarm starting coverage fixes for {len(modules)} modules")
    print(f"🎯 Target coverage: {args.target_coverage}%")
    print()
    
    # Initialize fixer
    fixer = AutonomousCoverageFixer()
    batch_fixer = BatchCoverageFixer(fixer)
    
    # Run fixes
    results = await batch_fixer.fix_tier2_coverage(modules, args.target_coverage)
    
    # Generate report
    report = batch_fixer.generate_report(results)
    
    # Save report
    with open(args.output_report, 'w') as f:
        f.write(report)
    
    print(report)
    print()
    
    # Summary
    successful = sum(1 for r in results if r.success)
    total_tests = sum(r.tests_added for r in results)
    
    print(f"✅ Fixed: {successful}/{len(results)} modules")
    print(f"📝 Tests added: {total_tests}")
    print(f"📄 Report saved to: {args.output_report}")
    
    # Exit with error if any fixes failed
    if successful < len(results):
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
