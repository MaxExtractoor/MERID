"""CI pytest wrapper: run pytest.main() then hard-exit with its status.

The Kalshi venue suite completes all tests in <1min on CI runners but the
interpreter then wedges during shutdown (leaked WS/asyncio/thread state —
Linux-only; Windows exits cleanly).  pytest has already printed its full
report by that point, so ``os._exit`` preserves the real result while
skipping interpreter teardown that can hang forever.  Stdout/stderr are
flushed first so the transcript and junitxml are complete.
"""

import os
import sys

import pytest


def main() -> None:
    code = pytest.main(sys.argv[1:])
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    finally:
        os._exit(int(code))


if __name__ == "__main__":
    main()
