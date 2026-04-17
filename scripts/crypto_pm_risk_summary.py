#!/usr/bin/env python3
"""Print crypto PM risk snapshot (Kalshi risk state + feed staleness hooks).

Run::

    python scripts/crypto_pm_risk_summary.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from merid.pm_crypto_ops import collect_crypto_pm_risk_summary


def main() -> None:
    summary = collect_crypto_pm_risk_summary()
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
