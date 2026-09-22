"""Diagnostic: trace who opens files under repo data/ during pytest collection/run."""
import pathlib
import sys
import traceback

ROOT = pathlib.Path(r"C:\Dev\MERID\data").resolve()


def _is_under_data(p) -> bool:
    try:
        rp = pathlib.Path(str(p)).resolve()
    except Exception:
        return False
    s = str(rp)
    return s.startswith(str(ROOT)) and "audit_sep" not in s


def hook(event, args):
    if event == "sqlite3.connect":
        if args and _is_under_data(args[0]):
            print(f"\n[DATA-WRITE] sqlite3.connect {args[0]}", file=sys.stderr)
            traceback.print_stack(limit=14, file=sys.stderr)
    elif event == "open":
        # args = (file, mode, flags)
        if len(args) >= 2:
            mode = args[1]
            if isinstance(mode, int):
                writing = mode != 0  # O_RDONLY == 0
            else:
                writing = any(c in str(mode) for c in "wax+")
            if writing and _is_under_data(args[0]):
                print(f"\n[DATA-WRITE] open {args[0]} mode={mode}", file=sys.stderr)
                traceback.print_stack(limit=14, file=sys.stderr)


sys.addaudithook(hook)

import pytest

sys.exit(
    pytest.main(
        [
            "tests/test_sprint24_empty_mutation.py",
            "tests/test_loop_lag_stress.py",
            "-q",
            "-p",
            "no:cacheprovider",
            "--timeout=60",
        ]
    )
)
