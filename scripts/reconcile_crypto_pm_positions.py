#!/usr/bin/env python3
"""Cross-check Kalshi REST positions vs local cache vs risk notionals for one asset/tf.

Run::

    python scripts/reconcile_crypto_pm_positions.py BTC 15m
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from merid.pm_crypto_ops import reconcile_crypto_pm_positions


def main() -> None:
    if len(sys.argv) != 3:
        print("Usage: reconcile_crypto_pm_positions.py <BTC|ETH|SOL|XRP|DOGE> <15m|1h|daily|weekly|monthly|annual>")
        sys.exit(2)
    asset, tf = sys.argv[1], sys.argv[2]
    result = asyncio.run(reconcile_crypto_pm_positions(asset, tf))
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
