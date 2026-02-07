#!/usr/bin/env python3
"""Helper to prepare a local release: run tests, regenerate schemas, and create a tag.

This script is intentionally conservative and does not push tags or uploads; it
prints recommended commands for the user to run.
"""
from __future__ import annotations

import argparse
import subprocess
import sys


def run(cmd: list[str]) -> int:
    print("$ ", " ".join(cmd))
    rc = subprocess.call(cmd)
    return rc


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--tag", type=str, required=True, help="Tag to create (e.g., v0.1.0)")
    args = p.parse_args(argv)

    # Run tests
    rc = run([sys.executable, "-m", "pytest", "-q"])
    if rc != 0:
        print("Tests failed; aborting release.")
        return 1

    # Regenerate schemas
    rc = run([sys.executable, "-c", "from web.schema_export import export_schemas; export_schemas('generated/schemas')"])
    if rc != 0:
        print("Failed to regenerate schemas; aborting.")
        return 2

    print(f"Ready to create tag {args.tag}. Run the following commands to finish the release:")
    print(f"  git add generated/schemas && git commit -m \"chore: regenerate schemas\" || true")
    print(f"  git tag -a {args.tag} -m \"Release {args.tag}\"")
    print(f"  git push origin {args.tag}")
    print("Then create a GitHub release via `gh release create` or the UI.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())