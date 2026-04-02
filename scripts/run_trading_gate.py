#!/usr/bin/env python3
"""
Full Trading Mode Gate Runner and Analyzer

Runs 10-minute or 30-minute trading gates and provides comprehensive analysis.

Usage:
    # 10-minute gate with full stack
    python scripts/run_trading_gate.py --duration 10 --output reports/gate_10min_$(date +%Y%m%d_%H%M%S).json

    # 30-minute gate for go-live validation
    python scripts/run_trading_gate.py --duration 30 --output reports/gate_30min_$(date +%Y%m%d_%H%M%S).json

    # Quick 5-minute smoke test
    python scripts/run_trading_gate.py --duration 5 --output reports/gate_5min_smoke.json

Environment Requirements:
    - MERID server must be running with VALIDATION_MODE=0 (full trading mode)
    - Full stack: MeridLoop, KalshiTradingAgents, StreamingAgents, WS bridge, etc.

Gate Criteria:
    - P95 < 500ms throughout
    - P99 < 800ms
    - Max < 1000ms
    - degraded_samples = 0
    - No recurring 5-minute spikes
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional


def print_header(title: str):
    """Print a formatted section header."""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80 + "\n")


def check_environment():
    """Check that environment is correctly configured for trading gate."""
    print_header("Environment Check")

    # Check if server is running
    try:
        import urllib.request
        req = urllib.request.Request("http://localhost:8000/health")
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status == 200:
                print("✅ MERID server is running")
            else:
                print(f"⚠️  MERID server returned HTTP {resp.status}")
                return False
    except Exception as e:
        print(f"❌ MERID server is not reachable: {e}")
        print("   Please start the server with: python -m web.main")
        return False

    # Check VALIDATION_MODE (if available via API)
    try:
        req = urllib.request.Request("http://localhost:8000/health/event_loop")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            print(f"✅ Event loop monitor is active")
    except Exception as e:
        print(f"⚠️  Event loop health endpoint not responding: {e}")

    print("\n✅ Environment check passed\n")
    return True


def run_gate(duration_min: float, output_path: Path) -> bool:
    """Run the paper gate using run_paper_gate.py."""
    print_header(f"Running {duration_min}-Minute Trading Gate")

    gate_script = Path(__file__).parent / "run_paper_gate.py"
    if not gate_script.exists():
        print(f"❌ Gate script not found: {gate_script}")
        return False

    cmd = [
        sys.executable,
        str(gate_script),
        "--duration", str(duration_min),
        "--poll-interval", "30",
        "--output", str(output_path),
    ]

    print(f"Command: {' '.join(cmd)}\n")

    try:
        result = subprocess.run(cmd, check=False, capture_output=False)
        return result.returncode == 0
    except Exception as e:
        print(f"❌ Gate execution failed: {e}")
        return False


def analyze_results(output_path: Path, highlight_5min: bool = True) -> bool:
    """Analyze gate results using analyze_gate_results.py."""
    print_header("Gate Results Analysis")

    analyzer_script = Path(__file__).parent / "analyze_gate_results.py"
    if not analyzer_script.exists():
        print(f"❌ Analyzer script not found: {analyzer_script}")
        return False

    cmd = [
        sys.executable,
        str(analyzer_script),
        str(output_path),
    ]

    if highlight_5min:
        cmd.append("--highlight-5min")

    try:
        result = subprocess.run(cmd, check=False, capture_output=False)
        return result.returncode == 0
    except Exception as e:
        print(f"❌ Analysis failed: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Run full trading mode gate and analyze results",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=10.0,
        help="Gate duration in minutes (default: 10)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output file for gate results (auto-generated if not specified)",
    )
    parser.add_argument(
        "--skip-env-check",
        action="store_true",
        help="Skip environment check (use with caution)",
    )
    parser.add_argument(
        "--no-analysis",
        action="store_true",
        help="Skip automatic result analysis",
    )

    args = parser.parse_args()

    # Environment check
    if not args.skip_env_check:
        if not check_environment():
            print("\n❌ Environment check failed. Fix issues before running gate.")
            return 2

    # Auto-generate output path if not specified
    if args.output is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = Path("reports")
        output_dir.mkdir(parents=True, exist_ok=True)
        args.output = output_dir / f"gate_{args.duration:.0f}min_{timestamp}.json"

    print(f"Gate results will be written to: {args.output}\n")

    # Run the gate
    gate_passed = run_gate(args.duration, args.output)

    if not args.output.exists():
        print(f"\n❌ Gate results file was not created: {args.output}")
        return 1

    # Analyze results
    if not args.no_analysis:
        analyze_passed = analyze_results(args.output, highlight_5min=True)
        if not analyze_passed:
            print("\n⚠️  Analysis completed with warnings")

    # Final verdict
    if gate_passed:
        print_header("✅ GATE PASSED — System Ready")
        return 0
    else:
        print_header("❌ GATE FAILED — Review Issues Above")
        return 1


if __name__ == "__main__":
    sys.exit(main())
