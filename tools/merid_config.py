#!/usr/bin/env python3
"""
MERID Config Probe Tool

Diagnostic CLI for inspecting the configuration override chain.

Usage:
    python -m tools.merid_config dump [--env live] [--subsystem portfolio]
    python -m tools.merid_config explain KEY [--env live]
    python -m tools.merid_config fingerprint [--subsystem risk]
    python -m tools.merid_config check-danger [--env live]

Examples:
    # Show effective config for live environment
    python -m tools.merid_config dump --env live

    # Explain why a specific value is what it is
    python -m tools.merid_config explain portfolio.max_risk_usd

    # Check if danger keys have unexpected sources
    python -m tools.merid_config check-danger
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add project root to path
project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))

from core.config_loader import (
    ConfigLayer,
    ExplicitConfigLoader,
    dump_config,
    explain_config,
    get_config,
    get_config_fingerprint,
)
from utils.logger import get_logger

logger = get_logger("tools.merid_config")


def format_value(value: Any) -> str:
    """Format a value for display."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "(null)"
    if isinstance(value, (int, float)):
        return str(value)
    return f'"{value}"'


def cmd_dump(args: argparse.Namespace) -> int:
    """Execute the 'dump' command."""
    env = args.env or os.getenv("MERID_ENV", "development")

    loader = ExplicitConfigLoader()
    loader.load_all(env=env)

    dump = dump_config(args.subsystem)

    if args.json:
        print(json.dumps(dump, indent=2, default=str))
        return 0

    # Human-readable format
    print(f"=" * 70)
    print(f"MERID Configuration Dump")
    print(f"Environment: {env}")
    print(f"Subsystem: {args.subsystem or 'all'}")
    print(f"Config Fingerprint: {get_config_fingerprint(args.subsystem)}")
    print(f"=" * 70)

    for key in sorted(dump.keys()):
        entry = dump[key]
        value = entry["value"]
        source = entry["source"]

        print(f"\n{key}")
        print(f"  value: {format_value(value)}")
        print(f"  source: {source['layer']} ({source['source_name']})")

        if args.verbose and entry["provenance"]:
            print(f"  provenance:")
            for i, prov in enumerate(entry["provenance"], 1):
                line_info = f":{prov['line']}" if prov["line"] else ""
                print(f"    [{i}] {prov['layer']} from {prov['source_name']}{line_info}")
                if prov["raw_value"] is not None:
                    print(f"        raw: {prov['raw_value']}")

    print(f"\n{'=' * 70}")
    print(f"Total keys: {len(dump)}")
    return 0


def cmd_explain(args: argparse.Namespace) -> int:
    """Execute the 'explain' command."""
    env = args.env or os.getenv("MERID_ENV", "development")

    loader = ExplicitConfigLoader()
    loader.load_all(env=env)

    key = args.key

    if args.json:
        dump = dump_config()
        if key in dump:
            print(json.dumps(dump[key], indent=2, default=str))
        else:
            print(json.dumps({"error": f"Key '{key}' not found"}), file=sys.stderr)
            return 1
        return 0

    explanation = explain_config(key)

    if explanation:
        print(explanation)
    else:
        # Key not found - show available keys with similar names
        print(f"Key '{key}' not found in configuration.")

        # Suggest similar keys
        all_keys = list(dump_config().keys())
        key_parts = key.split(".")

        # Find keys with matching prefix
        suggestions = [k for k in all_keys if k.startswith(".".join(key_parts[:-1]))]
        if suggestions:
            print(f"\nAvailable keys with similar prefix:")
            for s in suggestions[:10]:
                print(f"  - {s}")
            if len(suggestions) > 10:
                print(f"  ... and {len(suggestions) - 10} more")

        return 1

    return 0


def cmd_fingerprint(args: argparse.Namespace) -> int:
    """Execute the 'fingerprint' command."""
    env = args.env or os.getenv("MERID_ENV", "development")

    loader = ExplicitConfigLoader()
    loader.load_all(env=env)

    fingerprint = get_config_fingerprint(args.subsystem)

    if args.json:
        result = {
            "fingerprint": fingerprint,
            "environment": env,
            "subsystem": args.subsystem or "all",
        }
        print(json.dumps(result, indent=2))
        return 0

    print(f"Config Fingerprint: {fingerprint}")
    print(f"  Environment: {env}")
    print(f"  Subsystem: {args.subsystem or 'all'}")

    # Also show key subsystems
    if not args.subsystem:
        print(f"\nPer-subsystem fingerprints:")
        for sub in ["portfolio", "risk", "kalshi", "feature_flags"]:
            sub_fp = get_config_fingerprint(sub)
            print(f"  {sub}: {sub_fp}")

    return 0


def cmd_check_danger(args: argparse.Namespace) -> int:
    """Execute the 'check-danger' command."""
    env = args.env or os.getenv("MERID_ENV", "development")

    loader = ExplicitConfigLoader()
    loader.load_all(env=env)

    # Danger keys that should be reviewed
    DANGER_KEYS = [
        ("portfolio.max_risk_usd", "Max risk per trade"),
        ("portfolio.max_position_usd", "Max position size"),
        ("portfolio.global_risk_budget", "Global risk budget"),
        ("kalshi.spot_strike_warn_pct", "Strike distance warning"),
        ("kalshi.spot_strike_max_pct", "Strike distance max"),
        ("risk.max_daily_loss_usd", "Daily loss limit"),
        ("risk.max_order_size_usd", "Max order size"),
        ("feature_flags.live_trading", "Live trading flag"),
        ("feature_flags.auto_execute", "Auto execution flag"),
    ]

    issues: List[str] = []
    warnings: List[str] = []

    print(f"Checking danger keys for environment: {env}")
    print(f"{'=' * 70}")

    for key, description in DANGER_KEYS:
        value, meta = get_config(key, with_meta=True)

        if meta is None:
            print(f"⚠️  {key}: NOT SET (using hardcoded default)")
            print(f"   {description}")
            warnings.append(f"{key} not configured")
            continue

        source = meta.effective_source
        layer = source.layer

        # Determine severity based on source layer
        status = "✅"
        if layer in (ConfigLayer.ENV_VAR, ConfigLayer.CLI_FLAG, ConfigLayer.RUNTIME_OVERRIDE):
            status = "⚠️ "
            issues.append(f"{key} from {layer.name} may override config files")
        elif layer == ConfigLayer.DEFAULT:
            status = "⚠️ "
            warnings.append(f"{key} using hardcoded default")

        print(f"{status} {key}: {format_value(value)}")
        print(f"   Source: {layer.name} ({source.source_name})")
        print(f"   {description}")

        # Check for suspicious patterns
        if key.endswith(".live_trading") and value is True:
            warnings.append(f"LIVE TRADING ENABLED via {source.source_name}")
        if key.endswith(".auto_execute") and value is True:
            warnings.append(f"AUTO EXECUTE ENABLED via {source.source_name}")

    print(f"\n{'=' * 70}")

    if issues:
        print(f"❌ Issues found ({len(issues)}):")
        for issue in issues:
            print(f"  - {issue}")

    if warnings:
        print(f"⚠️  Warnings ({len(warnings)}):")
        for warning in warnings:
            print(f"  - {warning}")

    if not issues and not warnings:
        print("✅ All danger keys properly configured from config files")

    return 1 if issues else 0


def cmd_diff(args: argparse.Namespace) -> int:
    """Execute the 'diff' command - compare configs between environments."""
    env1 = args.env1
    env2 = args.env2

    loader1 = ExplicitConfigLoader()
    loader1.load_all(env=env1)
    dump1 = dump_config(args.subsystem)

    # Reset registry for second env
    from core.config_loader import _registry
    import core.config_loader as cl

    cl._registry = None

    loader2 = ExplicitConfigLoader()
    loader2.load_all(env=env2)
    dump2 = dump_config(args.subsystem)

    # Find differences
    all_keys = set(dump1.keys()) | set(dump2.keys())

    only_in_1 = []
    only_in_2 = []
    different = []

    for key in sorted(all_keys):
        if key not in dump2:
            only_in_1.append(key)
        elif key not in dump1:
            only_in_2.append(key)
        elif dump1[key]["value"] != dump2[key]["value"]:
            different.append((key, dump1[key]["value"], dump2[key]["value"]))

    print(f"Config Diff: {env1} vs {env2}")
    print(f"{'=' * 70}")

    if only_in_1:
        print(f"\nOnly in {env1}:")
        for key in only_in_1:
            print(f"  {key}: {format_value(dump1[key]['value'])}")

    if only_in_2:
        print(f"\nOnly in {env2}:")
        for key in only_in_2:
            print(f"  {key}: {format_value(dump2[key]['value'])}")

    if different:
        print(f"\nDifferent values:")
        for key, val1, val2 in different:
            print(f"  {key}:")
            print(f"    {env1}: {format_value(val1)}")
            print(f"    {env2}: {format_value(val2)}")

    if not any([only_in_1, only_in_2, different]):
        print("No differences found (fingerprints may still differ due to sources)")

    return 0


def main(argv: Optional[List[str]] = None) -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        prog="merid-config",
        description="MERID configuration probe and diagnostic tool",
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # dump command
    dump_parser = subparsers.add_parser("dump", help="Dump all effective config values")
    dump_parser.add_argument("--env", help="Environment (dev/live/paper)")
    dump_parser.add_argument("--subsystem", help="Filter by subsystem prefix")
    dump_parser.add_argument("--json", action="store_true", help="Output as JSON")
    dump_parser.add_argument("-v", "--verbose", action="store_true", help="Show provenance")

    # explain command
    explain_parser = subparsers.add_parser(
        "explain", help="Explain why a specific value is set"
    )
    explain_parser.add_argument("key", help="Config key (e.g., portfolio.max_risk_usd)")
    explain_parser.add_argument("--env", help="Environment")
    explain_parser.add_argument("--json", action="store_true", help="Output as JSON")

    # fingerprint command
    fp_parser = subparsers.add_parser("fingerprint", help="Show config fingerprint")
    fp_parser.add_argument("--subsystem", help="Subsystem to fingerprint")
    fp_parser.add_argument("--env", help="Environment")
    fp_parser.add_argument("--json", action="store_true", help="Output as JSON")

    # check-danger command
    danger_parser = subparsers.add_parser(
        "check-danger", help="Check danger keys and their sources"
    )
    danger_parser.add_argument("--env", help="Environment")

    # diff command
    diff_parser = subparsers.add_parser("diff", help="Compare configs between environments")
    diff_parser.add_argument("env1", help="First environment")
    diff_parser.add_argument("env2", help="Second environment")
    diff_parser.add_argument("--subsystem", help="Filter by subsystem")

    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 1

    commands = {
        "dump": cmd_dump,
        "explain": cmd_explain,
        "fingerprint": cmd_fingerprint,
        "check-danger": cmd_check_danger,
        "diff": cmd_diff,
    }

    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
