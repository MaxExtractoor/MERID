#!/usr/bin/env python3
"""
Config Snapshot Script for Risk Envelope Rollback

Captures configuration state for kalshi_crypto_15m_v2 profile on deployment.
Archives YAML files and relevant environment variables for rollback purposes.
"""

import os
import json
import shutil
from datetime import datetime
from pathlib import Path
import subprocess
from typing import Dict, Any


def get_git_sha() -> str:
    """Get current git SHA."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def get_relevant_env_vars() -> Dict[str, str]:
    """Get environment variables relevant to 15m profile and risk envelope."""
    relevant_vars = [
        "MERID_PROFILE",
        "MERID_PM_PROFILE",
        "MERID_RISK_ENVELOPE_ENABLED",
        "KALSHI_ENV",
        "MERID_PM_TRADING_MODE",
    ]
    
    env_snapshot = {}
    for var in relevant_vars:
        value = os.getenv(var)
        if value is not None:
            # Sanitize sensitive values
            if "KEY" in var or "SECRET" in var or "PASSWORD" in var:
                env_snapshot[var] = "***REDACTED***"
            else:
                env_snapshot[var] = value
    
    return env_snapshot


def copy_yaml_file(src_path: Path, dest_dir: Path) -> None:
    """Copy a YAML file to snapshot directory."""
    if src_path.exists():
        shutil.copy2(src_path, dest_dir / src_path.name)
        print(f"Copied {src_path.name}")
    else:
        print(f"Warning: {src_path} does not exist, skipping")


def capture_snapshot(output_dir: str = "snapshots") -> str:
    """Capture config snapshot for rollback.
    
    Args:
        output_dir: Directory to store snapshots (default: snapshots/)
    
    Returns:
        Path to created snapshot directory
    """
    # Create snapshot directory with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    snapshot_name = f"15m_risk_{timestamp}"
    snapshot_dir = Path(output_dir) / snapshot_name
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"Creating config snapshot: {snapshot_dir}")
    
    # Get git SHA
    git_sha = get_git_sha()
    print(f"Git SHA: {git_sha}")
    
    # Copy relevant YAML files
    repo_root = Path(__file__).parent.parent
    yaml_files = [
        repo_root / "config" / "profiles" / "kalshi_crypto_15m.yaml",
        repo_root / "config" / "kalshi_agent_grid.yaml",
    ]
    
    yaml_dir = snapshot_dir / "yaml"
    yaml_dir.mkdir(exist_ok=True)
    
    for yaml_file in yaml_files:
        copy_yaml_file(yaml_file, yaml_dir)
    
    # Capture environment variables
    env_snapshot = get_relevant_env_vars()
    env_file = snapshot_dir / "env_snapshot.json"
    with open(env_file, "w") as f:
        json.dump(env_snapshot, f, indent=2)
    print(f"Captured environment variables: {env_file}")
    
    # Create metadata file
    metadata = {
        "timestamp": timestamp,
        "git_sha": git_sha,
        "profile": "kalshi_crypto_15m_v2",
        "yaml_files_copied": [f.name for f in yaml_files if f.exists()],
        "env_vars_captured": list(env_snapshot.keys()),
    }
    
    metadata_file = snapshot_dir / "metadata.json"
    with open(metadata_file, "w") as f:
        json.dump(metadata, f, indent=2)
    print(f"Created metadata: {metadata_file}")
    
    print(f"\nSnapshot created successfully: {snapshot_dir}")
    print(f"To restore: Copy YAML files back and set env vars from {env_file}")
    
    return str(snapshot_dir)


def restore_snapshot(snapshot_dir: str) -> None:
    """Restore config from snapshot.
    
    Args:
        snapshot_dir: Path to snapshot directory
    """
    snapshot_path = Path(snapshot_dir)
    
    if not snapshot_path.exists():
        print(f"Error: Snapshot directory {snapshot_dir} does not exist")
        return
    
    print(f"Restoring from snapshot: {snapshot_dir}")
    
    # Restore YAML files
    yaml_dir = snapshot_path / "yaml"
    repo_root = Path(__file__).parent.parent
    config_dir = repo_root / "config" / "profiles"
    
    if yaml_dir.exists():
        for yaml_file in yaml_dir.glob("*.yaml"):
            dest = config_dir / yaml_file.name
            shutil.copy2(yaml_file, dest)
            print(f"Restored {yaml_file.name}")
    
    # Load env snapshot
    env_file = snapshot_path / "env_snapshot.json"
    if env_file.exists():
        with open(env_file, "r") as f:
            env_snapshot = json.load(f)
        
        print("\nTo restore environment variables, set:")
        for var, value in env_snapshot.items():
            print(f"  export {var}={value}")
    
    # Show metadata
    metadata_file = snapshot_path / "metadata.json"
    if metadata_file.exists():
        with open(metadata_file, "r") as f:
            metadata = json.load(f)
        print(f"\nSnapshot metadata:")
        print(f"  Timestamp: {metadata['timestamp']}")
        print(f"  Git SHA: {metadata['git_sha']}")
        print(f"  Profile: {metadata['profile']}")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Capture or restore config snapshots")
    parser.add_argument("action", choices=["capture", "restore"], help="Action to perform")
    parser.add_argument("--dir", help="Snapshot directory (for restore) or output directory (for capture)")
    
    args = parser.parse_args()
    
    if args.action == "capture":
        output_dir = args.dir or "snapshots"
        capture_snapshot(output_dir)
    elif args.action == "restore":
        if not args.dir:
            print("Error: --dir required for restore")
            exit(1)
        restore_snapshot(args.dir)
