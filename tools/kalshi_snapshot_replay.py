#!/usr/bin/env python3
"""P1-7 CLI entry — replays Kalshi cycle snapshots offline.

Delegates to :mod:`tools.replay_kalshi_snapshot` (FilterPipeline → NearSpotSelector).
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

if __name__ == "__main__":
    script = Path(__file__).resolve().parent / "replay_kalshi_snapshot.py"
    sys.argv[0] = str(script)
    runpy.run_path(str(script), run_name="__main__")
