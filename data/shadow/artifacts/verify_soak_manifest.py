"""Verify a shadow soak manifest against the current working tree.

Usage (from repo root with PYTHONPATH set to repo root):
    $env:PYTHONPATH='C:\Dev\MERID'
    .\.venv\Scripts\python.exe data\shadow\artifacts\verify_soak_manifest.py data\shadow\artifacts\shadow_soak_manifest_*.json

Any mismatch printed to stdout causes exit code 1.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: verify_soak_manifest.py <manifest.json>")
        return 1

    manifest_path = Path(sys.argv[1])
    with open(manifest_path) as f:
        manifest = json.load(f)

    ok = True
    print(f"[MANIFEST-VERIFY] verifying {manifest_path}")
    print(f"  run_id: {manifest.get('run_id')}")
    print(f"  git_head: {manifest.get('git_head')}")

    patch_path = Path(manifest["rti_postgres_patch_sha256"].split()[1])
    patch_hash = _sha256(patch_path)
    expected = manifest["rti_postgres_patch_sha256"].split()[0]
    status = "OK" if patch_hash == expected else "MISMATCH"
    print(f"  patch {patch_path}: {status}")
    if patch_hash != expected:
        ok = False

    for rel, expected in manifest["runtime_file_sha256"].items():
        path = Path(rel)
        actual = _sha256(path)
        status = "OK" if actual == expected else "MISMATCH"
        print(f"  {rel}: {status}")
        if actual != expected:
            ok = False

    if ok:
        print("[MANIFEST-VERIFY] ALL HASHES MATCH")
        return 0
    print("[MANIFEST-VERIFY] HASH MISMATCH — DO NOT START SOAK")
    return 1


if __name__ == "__main__":
    sys.exit(main())
