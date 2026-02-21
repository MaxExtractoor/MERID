"""CLI gate for swarm integrity + data authenticity enforcement.

Usage:
  python scripts/enforce_swarm_integrity.py --snapshot tests/fixtures/swarm/healthy_snapshot.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from merid.safeguards.swarm_integrity_guard import run_swarm_integrity_gate  # noqa: E402


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Enforce MERID swarm integrity and data authenticity policy",
    )
    parser.add_argument(
        "--snapshot",
        default=None,
        help="Path to JSON swarm health snapshot (or use MERID_SWARM_HEALTH_SNAPSHOT)",
    )
    parser.add_argument(
        "--config",
        default=".merid_safeguard.yml",
        help="Path to safeguard policy (.merid_safeguard.yml)",
    )
    parser.add_argument(
        "--output-json",
        default=None,
        help="Optional path to write machine-readable report JSON",
    )

    default_strict = _env_flag("MERID_SWARM_INTEGRITY_STRICT", default=True)
    parser.set_defaults(strict=default_strict)
    parser.add_argument("--strict", dest="strict", action="store_true", help="Exit non-zero on violations")
    parser.add_argument("--no-strict", dest="strict", action="store_false", help="Always exit zero")
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    report = run_swarm_integrity_gate(snapshot_path=args.snapshot, policy_path=args.config)
    payload = report.to_dict()

    print("MERID Swarm Integrity Gate")
    print("=" * 36)
    print(f"OK: {payload['ok']}")
    print(f"Mode tags: {payload['mode_tags']}")
    print(f"Health summary: {payload['health_summary']}")
    print(f"Data summary: {payload['data_summary']}")

    if payload["issues"]:
        print("Issues:")
        for issue in payload["issues"]:
            print(f"  - {issue}")

    if payload["warning"]:
        print(payload["warning"])

    if args.output_json:
        output_path = Path(args.output_json)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    if args.strict and not payload["ok"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
