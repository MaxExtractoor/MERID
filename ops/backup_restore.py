"""
MERID Backup & Restore Utility

Backs up critical state: Neo4j graph, Redis snapshots, audit trails,
configuration, and Dev Swarm persistence. Supports snapshot creation
and point-in-time restore.

Usage:
    python -m ops.backup_restore backup [--output-dir BACKUPS]
    python -m ops.backup_restore restore --snapshot <path>
    python -m ops.backup_restore list [--output-dir BACKUPS]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BACKUP_DIR = PROJECT_ROOT / "backups"

# Components to back up
BACKUP_COMPONENTS = {
    "dev_swarm_persistence": {
        "description": "Dev Swarm task history and state",
        "paths": ["data/dev_swarm_tasks.json", "data/dev_swarm_state.json"],
    },
    "audit_trails": {
        "description": "Explainability and audit trail records",
        "paths": ["data/audit_trail.json", "data/explainability_records.json"],
    },
    "configuration": {
        "description": "Runtime configuration files",
        "paths": [".env", "merid/settings.py", "policy/guardrails.yml"],
    },
    "risk_state": {
        "description": "Risk control state and breach history",
        "paths": ["data/risk_state.json", "data/breach_history.json"],
    },
    "trading_positions": {
        "description": "Paper trading positions, orders, and portfolio state",
        "paths": [
            "data/paper_positions.json",
            "data/paper_orders.json",
            "data/portfolio_state.json",
        ],
    },
}


def _timestamp() -> str:
    return datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def create_snapshot(output_dir: Path, components: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Create a backup snapshot of all (or selected) components.

    Returns a manifest dict describing what was backed up.
    """
    ts = _timestamp()
    snapshot_dir = output_dir / f"merid-snapshot-{ts}"
    _ensure_dir(snapshot_dir)

    manifest: Dict[str, Any] = {
        "timestamp": ts,
        "created_at": datetime.utcnow().isoformat(),
        "snapshot_dir": str(snapshot_dir),
        "components": {},
    }

    targets = components or list(BACKUP_COMPONENTS.keys())

    for comp_name in targets:
        comp = BACKUP_COMPONENTS.get(comp_name)
        if not comp:
            print(f"  [SKIP] Unknown component: {comp_name}")
            continue

        comp_dir = snapshot_dir / comp_name
        _ensure_dir(comp_dir)
        backed_up = []

        for rel_path in comp["paths"]:
            src = PROJECT_ROOT / rel_path
            if src.exists():
                dst = comp_dir / Path(rel_path).name
                shutil.copy2(str(src), str(dst))
                backed_up.append(rel_path)
                print(f"  [OK] {rel_path}")
            else:
                print(f"  [--] {rel_path} (not found, skipped)")

        manifest["components"][comp_name] = {
            "description": comp["description"],
            "files_backed_up": backed_up,
            "files_expected": comp["paths"],
        }

    # Neo4j dump (if docker is available)
    neo4j_dump = _backup_neo4j(snapshot_dir)
    manifest["components"]["neo4j"] = neo4j_dump

    # Redis dump (if docker is available)
    redis_dump = _backup_redis(snapshot_dir)
    manifest["components"]["redis"] = redis_dump

    # Write manifest
    manifest_path = snapshot_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))
    print(f"\n  Snapshot saved: {snapshot_dir}")
    print(f"  Manifest: {manifest_path}")

    return manifest


def _backup_neo4j(snapshot_dir: Path) -> Dict[str, Any]:
    """Attempt Neo4j dump via docker exec."""
    result: Dict[str, Any] = {"description": "Neo4j graph database"}
    try:
        r = subprocess.run(
            ["docker", "exec", "merid-neo4j", "neo4j-admin", "database", "dump", "neo4j",
             "--to-path=/tmp/neo4j-backup"],
            capture_output=True, text=True, timeout=120,
        )
        if r.returncode == 0:
            # Copy dump out of container
            dump_dir = snapshot_dir / "neo4j"
            _ensure_dir(dump_dir)
            subprocess.run(
                ["docker", "cp", "merid-neo4j:/tmp/neo4j-backup", str(dump_dir)],
                capture_output=True, timeout=60,
            )
            result["status"] = "ok"
            result["path"] = str(dump_dir)
            print("  [OK] Neo4j dump")
        else:
            result["status"] = "skipped"
            result["reason"] = r.stderr.strip() or "dump command failed"
            print(f"  [--] Neo4j dump skipped: {result['reason'][:80]}")
    except FileNotFoundError:
        result["status"] = "skipped"
        result["reason"] = "docker not available"
        print("  [--] Neo4j dump skipped: docker not available")
    except Exception as exc:
        result["status"] = "error"
        result["reason"] = str(exc)
        print(f"  [!!] Neo4j dump error: {exc}")
    return result


def _backup_redis(snapshot_dir: Path) -> Dict[str, Any]:
    """Attempt Redis BGSAVE + copy via docker."""
    result: Dict[str, Any] = {"description": "Redis state snapshot"}
    try:
        # Trigger BGSAVE
        subprocess.run(
            ["docker", "exec", "merid-redis", "redis-cli", "BGSAVE"],
            capture_output=True, timeout=30,
        )
        time.sleep(2)  # Wait for background save
        # Copy dump.rdb out
        dump_dir = snapshot_dir / "redis"
        _ensure_dir(dump_dir)
        r = subprocess.run(
            ["docker", "cp", "merid-redis:/data/dump.rdb", str(dump_dir / "dump.rdb")],
            capture_output=True, timeout=30,
        )
        if r.returncode == 0:
            result["status"] = "ok"
            result["path"] = str(dump_dir / "dump.rdb")
            print("  [OK] Redis dump")
        else:
            result["status"] = "skipped"
            result["reason"] = "copy failed"
            print("  [--] Redis dump skipped")
    except FileNotFoundError:
        result["status"] = "skipped"
        result["reason"] = "docker not available"
        print("  [--] Redis dump skipped: docker not available")
    except Exception as exc:
        result["status"] = "error"
        result["reason"] = str(exc)
        print(f"  [!!] Redis dump error: {exc}")
    return result


def restore_snapshot(snapshot_path: Path) -> bool:
    """
    Restore from a snapshot directory.

    Reads manifest.json and copies files back to their original locations.
    Neo4j/Redis restores require manual container restart.
    """
    manifest_path = snapshot_path / "manifest.json"
    if not manifest_path.exists():
        print(f"ERROR: No manifest.json in {snapshot_path}")
        return False

    manifest = json.loads(manifest_path.read_text())
    print(f"Restoring snapshot from {manifest.get('created_at', 'unknown')}...")

    for comp_name, comp_info in manifest.get("components", {}).items():
        if comp_name in ("neo4j", "redis"):
            print(f"  [INFO] {comp_name}: manual restore required (restart container with dump)")
            continue

        comp = BACKUP_COMPONENTS.get(comp_name)
        if not comp:
            continue

        comp_dir = snapshot_path / comp_name
        for rel_path in comp_info.get("files_backed_up", []):
            src = comp_dir / Path(rel_path).name
            dst = PROJECT_ROOT / rel_path
            if src.exists():
                _ensure_dir(dst.parent)
                shutil.copy2(str(src), str(dst))
                print(f"  [OK] Restored {rel_path}")
            else:
                print(f"  [--] {rel_path} not in snapshot")

    print("\nRestore complete. Restart services to pick up restored state.")
    return True


def list_snapshots(output_dir: Path) -> List[Dict[str, Any]]:
    """List available snapshots."""
    if not output_dir.exists():
        print("No backups directory found.")
        return []

    snapshots = []
    for d in sorted(output_dir.iterdir()):
        manifest_path = d / "manifest.json"
        if manifest_path.exists():
            m = json.loads(manifest_path.read_text())
            comp_count = len(m.get("components", {}))
            print(f"  {d.name}  ({m.get('created_at', '?')}, {comp_count} components)")
            snapshots.append(m)

    if not snapshots:
        print("  No snapshots found.")
    return snapshots


def main():
    parser = argparse.ArgumentParser(description="MERID Backup & Restore")
    sub = parser.add_subparsers(dest="command")

    bp = sub.add_parser("backup", help="Create a backup snapshot")
    bp.add_argument("--output-dir", default=str(DEFAULT_BACKUP_DIR))
    bp.add_argument("--components", nargs="*", help="Specific components to back up")

    rp = sub.add_parser("restore", help="Restore from a snapshot")
    rp.add_argument("--snapshot", required=True, help="Path to snapshot directory")

    lp = sub.add_parser("list", help="List available snapshots")
    lp.add_argument("--output-dir", default=str(DEFAULT_BACKUP_DIR))

    args = parser.parse_args()

    if args.command == "backup":
        create_snapshot(Path(args.output_dir), args.components)
    elif args.command == "restore":
        restore_snapshot(Path(args.snapshot))
    elif args.command == "list":
        list_snapshots(Path(args.output_dir))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
