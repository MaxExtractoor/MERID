#!/usr/bin/env python3
"""Print effective crypto threshold matrix rows (paste into notes or a UI grid).

Usage:
  python scripts/print_crypto_agent_effective_config.py
"""

from __future__ import annotations

import json
import sys


def main() -> int:
    repo_root = __file__
    # Allow running from any cwd
    import os

    os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    sys.path.insert(0, os.getcwd())

    from merid.prediction.crypto_threshold_matrix import effective_matrix_payload

    payload = effective_matrix_payload()
    print(json.dumps(payload, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
