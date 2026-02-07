#!/usr/bin/env python3
"""
Simple Agent Run Log Analyzer

Fast, scriptable tooling for analyzing MERID agent logs.
Can be ported to ES aggregations later.
"""

import argparse
import json
import statistics
from pathlib import Path
from typing import Iterator, Dict, List, Any, Optional

def load_runs(path: str, agent_version: Optional[str] = None, experiment_id: Optional[str] = None) -> Iterator[Dict[str, Any]]:
    """Load runs from JSONL file with optional filtering."""
    try:
        with Path(path).open() as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    run = json.loads(line.strip())
                    if agent_version and run.get("agent_version") != agent_version:
                        continue
                    if experiment_id and run.get("experiment_id") != experiment_id:
                        continue
                    yield run
                except json.JSONDecodeError:
                    continue
    except FileNotFoundError:
        print(f"❌ Log file not found: {path}")
        return

def summarize(runs: List[Dict[str, Any]]):
    """Summarize runs with key metrics."""
    if not runs:
        print("No runs found")
        return
    print("runs:", len(runs))

    briers = [r["brier_score"] for r in runs if r.get("brier_score") is not None]
    if briers:
        print("mean_brier:", sum(briers) / len(briers))
        print("median_brier:", statistics.median(briers))

    latencies = [r["latency_ms"] for r in runs if r.get("latency_ms") is not None]
    if latencies:
        print("mean_latency_ms:", sum(latencies) / len(latencies))

    status_counts = {}
    for r in runs:
        status = r.get("status", "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
    print("status_counts:", status_counts)

def main():
    parser = argparse.ArgumentParser(description="Analyze MERID agent runs")
    parser.add_argument("--file", default="logs/agent_runs.jsonl", help="Log file path")
    parser.add_argument("--agent-version", help="Filter by agent version")
    parser.add_argument("--experiment-id", help="Filter by experiment ID")
    args = parser.parse_args()

    runs = list(load_runs(args.file, args.agent_version, args.experiment_id))
    summarize(runs)

if __name__ == "__main__":
    main()
