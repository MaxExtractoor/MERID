"""Watchdog wrapper for the forecast audit CLI.

Dumps a faulthandler traceback to stderr every ``--watchdog`` seconds so a
hung run leaves evidence instead of silent zero-CPU stalls (observed
2026-11-14 when audits launched from a dead parent shell froze at probe
start). All arguments pass through to ``merid.analysis.forecast_audit``.
"""

from __future__ import annotations

import faulthandler
import runpy
import sys
from pathlib import Path

_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def main() -> int:
    interval = 300.0
    argv = list(sys.argv[1:])
    if "--watchdog" in argv:
        i = argv.index("--watchdog")
        interval = float(argv[i + 1])
        del argv[i : i + 2]
    faulthandler.dump_traceback_later(interval, repeat=True)
    sys.argv = ["forecast_audit", *argv]
    runpy.run_module("merid.analysis.forecast_audit", run_name="__main__")
    return 0


if __name__ == "__main__":
    sys.exit(main())
