"""Invariant: no new silent ``except Exception: pass`` in the scalper slice.

This guardrail is the in-process analogue of Ruff ``S110`` / Bandit ``B110``
(``try-except-pass``).  It exists because we've already been burned by a
silent handler hiding a real gate-update bug (see the CT pre-trade gate
dual-PENDING leak fixed in commit ``f16debb7``).

Scope
-----
The **scalper chokepoint slice** is the narrow band of code that a Kalshi
order crosses from intent to venue ack:

* ``merid/event_venues/kalshi/`` — router, gate, WS, client
* ``merid/execution/executors/`` — executor wrappers
* ``merid/trading/`` — continuous trader, filter pipeline, batch manager
* ``merid/lanes/`` — live lanes (crypto / btc 15m)
* ``merid/guards/`` — global risk guard + order dedup registry
* ``web/api/kalshi_api.py`` — REST entry points that speak to the router

Prediction, feature engineering, and strategy modules are *not* in this
slice — their silent handlers are mostly analytics fallbacks and belong in
a separate, future invariant.

What counts as "silent"
-----------------------
An ``ExceptHandler`` is flagged when **all** of the following hold:

1. The handler catches a generic exception (``except:`` or
   ``except Exception:``).  Narrow exception types are out of scope.
2. The handler's body has no observable side-effects, i.e. it consists
   only of ``pass``, bare ``...``, or a standalone string constant
   (docstring-style).

Policy
------
The current count of silent handlers per file is frozen in
``_ALLOWED_SILENT_COUNTS`` below.  The test asserts the live count is
**exactly** the allowlisted count — drift in either direction fails:

* **Count goes up** — a new silent handler was introduced; either
  (a) refactor to log + emit a metric (or re-raise a narrower exception),
  or (b) explicitly bump the allowlist with a code comment justifying why
  swallowing is correct at this site.
* **Count goes down** — an allowlisted handler was cleaned up; drop the
  entry (or lower the count) so the ratchet keeps tightening.

No "file not present" or "zero entries" shortcut: the allowlist is the
single source of truth.  ``scripts/audit_silent_handlers.py`` prints a
fresh baseline if the slice is re-scoped.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Dict, List, Tuple

import pytest


# ═══════════════════════════════════════════════════════════════════════════
# Scope
# ═══════════════════════════════════════════════════════════════════════════

REPO_ROOT = Path(__file__).resolve().parents[2]

SLICE_ROOTS: Tuple[str, ...] = (
    "merid/event_venues/kalshi",
    "merid/execution/executors",
    "merid/trading",
    "merid/lanes",
    "merid/guards",
    "web/api/kalshi_api.py",
)

_SKIP_SUBSTRS: Tuple[str, ...] = (
    "_legacy",
    "__pycache__",
    "archive",
    ".venv",
    "venv",
)


# ═══════════════════════════════════════════════════════════════════════════
# Frozen baseline — update deliberately, never as a drive-by
# ═══════════════════════════════════════════════════════════════════════════

# Map of repo-relative file path → expected number of naked
# ``except Exception: pass`` (or equivalent) handlers.  Keep sorted.
#
# When you change this table, include in the commit message:
#   * the file(s) that moved, and
#   * *why* the silent handler is justified (if count went up) or
#     *how* it was replaced (if count went down).
_ALLOWED_SILENT_COUNTS: Dict[str, int] = {
    "merid/event_venues/kalshi/kalshi_risk.py": 1,
    "merid/event_venues/kalshi/market_selector.py": 1,
    "merid/event_venues/kalshi/order_router.py": 2,
    "merid/event_venues/kalshi/ws.py": 1,
    "merid/execution/executors/coinbase.py": 1,
    "merid/execution/executors/kalshi.py": 1,
    "merid/guards/global_risk_guard.py": 1,
    "merid/lanes/btc15m_lane.py": 1,
    "merid/trading/kalshi_continuous_trader.py": 26,
    "merid/trading/kalshi_filter_pipeline.py": 3,
    "merid/trading/top3_batch_manager.py": 1,
}


# ═══════════════════════════════════════════════════════════════════════════
# AST scanner
# ═══════════════════════════════════════════════════════════════════════════


def _body_is_silent(body: List[ast.stmt]) -> bool:
    """Return True when an except-body has no observable side-effect.

    We treat the following as silent:

    * empty body (AST-impossible, but guarded anyway);
    * a single ``pass``;
    * a single bare string constant (historic "docstring" style);
    * a single bare ``...`` (Ellipsis);
    * any combination of the above.

    A single expression that is a :class:`ast.Call` — even one that looks
    trivial — is **not** treated as silent.  If a caller truly wants a
    no-op they can always add a ``logger.debug`` line; the point of this
    check is to forbid the pattern where the author wrote nothing at all.
    """
    if not body:
        return True
    for node in body:
        if isinstance(node, ast.Pass):
            continue
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            continue
        return False
    return True


def _handler_is_generic(handler: ast.ExceptHandler) -> bool:
    """True when the handler catches ``Exception`` or bare ``except``."""
    t = handler.type
    if t is None:
        return True  # bare ``except:``
    if isinstance(t, ast.Name) and t.id == "Exception":
        return True
    return False


def _silent_handlers_in_file(path: Path) -> List[int]:
    """Return the line numbers of silent generic handlers in ``path``."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return []
    hits: List[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        if not _handler_is_generic(node):
            continue
        if _body_is_silent(node.body):
            hits.append(node.lineno)
    return hits


def _iter_slice_files() -> List[Path]:
    """Yield every ``.py`` file inside the scalper chokepoint slice."""
    out: List[Path] = []
    for rel in SLICE_ROOTS:
        p = REPO_ROOT / rel
        if p.is_file():
            out.append(p)
            continue
        for f in p.rglob("*.py"):
            s = str(f)
            if any(skip in s for skip in _SKIP_SUBSTRS):
                continue
            out.append(f)
    return out


def _collect_current_counts() -> Dict[str, List[int]]:
    """Return ``{posix_relative_path: [line, line, ...]}`` for the slice."""
    current: Dict[str, List[int]] = {}
    for f in _iter_slice_files():
        lines = _silent_handlers_in_file(f)
        if not lines:
            continue
        rel = f.relative_to(REPO_ROOT).as_posix()
        current[rel] = lines
    return current


# ═══════════════════════════════════════════════════════════════════════════
# Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestSilentHandlerInvariant:
    """Freeze the scalper-slice silent-handler count at today's baseline."""

    def test_allowlist_matches_live_count(self):
        """Per-file count of silent handlers must match ``_ALLOWED_SILENT_COUNTS``.

        This is deliberately strict in both directions:

        * **New silent handler** → the file's live count exceeds the allowed
          count → test fails.  Fix the handler (log + metric, narrower
          exception, or re-raise) or justify and bump the allowlist.
        * **Silent handler removed** → the file's live count dips below
          the allowed count → test fails.  Drop the entry (or lower the
          count) so the ratchet keeps tightening.
        """
        current = _collect_current_counts()

        # Union of files from both sides — either a file in the allowlist
        # that no longer has any hits, or a file with fresh hits that isn't
        # allow-listed at all.
        all_files = set(_ALLOWED_SILENT_COUNTS.keys()) | set(current.keys())

        problems: List[str] = []
        for f in sorted(all_files):
            expected = _ALLOWED_SILENT_COUNTS.get(f, 0)
            live_lines = current.get(f, [])
            live = len(live_lines)
            if live == expected:
                continue
            if live > expected:
                added = live - expected
                problems.append(
                    f"  {f}: +{added} new silent handler(s) "
                    f"(expected {expected}, found {live}) at lines "
                    f"{live_lines}. "
                    f"Refactor to log + emit a metric, narrow the exception, "
                    f"or justify via an allowlist bump."
                )
            else:
                removed = expected - live
                problems.append(
                    f"  {f}: {removed} silent handler(s) removed "
                    f"(expected {expected}, found {live}). "
                    f"Lower or drop the allowlist entry."
                )

        assert not problems, (
            "Silent-handler invariant violated in the scalper chokepoint slice.\n"
            "Policy: `except Exception: pass` (or equivalent silent body) is\n"
            "forbidden unless the file/line is on the frozen allowlist in\n"
            f"{Path(__file__).name}.\n\n"
            "Drift:\n" + "\n".join(problems) + "\n\n"
            "Remediation:\n"
            "  1. Preferred — add `logger.warning(...)` (or stronger) inside\n"
            "     the handler and, where appropriate, bump a metric counter.\n"
            "  2. Second best — narrow the caught type so the intent is\n"
            "     obvious (e.g. `except (KeyError, ValueError):`).\n"
            "  3. Last resort — if swallowing really is correct, add an\n"
            "     inline comment explaining why and update the allowlist.\n"
        )

    def test_allowlist_only_references_existing_files(self):
        """No phantom entries — every allowlisted path must exist on disk.

        Catches the common failure mode where a file is renamed or moved
        but the allowlist still references the old path (making the
        invariant trivially satisfy-able with zero live hits).
        """
        missing = [
            f for f in _ALLOWED_SILENT_COUNTS
            if not (REPO_ROOT / f).is_file()
        ]
        assert not missing, (
            f"Allowlist references files that do not exist: {missing}. "
            f"Remove stale entries so the invariant can't be silently "
            f"bypassed by renames."
        )

    def test_allowlist_only_contains_positive_counts(self):
        """Zero-count entries are noise — drop them rather than list them."""
        zeros = [f for f, c in _ALLOWED_SILENT_COUNTS.items() if c <= 0]
        assert not zeros, (
            f"Allowlist contains zero-count entries: {zeros}. "
            f"Remove them — the invariant already assumes 0 for unlisted files."
        )


# ═══════════════════════════════════════════════════════════════════════════
# Unit-level coverage for the scanner itself
# ═══════════════════════════════════════════════════════════════════════════


class TestSilentHandlerScanner:
    """Sanity checks so the invariant can't go green by accident."""

    def test_scanner_flags_naked_pass(self, tmp_path: Path):
        src = tmp_path / "m.py"
        src.write_text(
            "def f():\n"
            "    try:\n"
            "        do()\n"
            "    except Exception:\n"
            "        pass\n"
        )
        assert _silent_handlers_in_file(src) == [4]

    def test_scanner_flags_bare_except_pass(self, tmp_path: Path):
        src = tmp_path / "m.py"
        src.write_text(
            "def f():\n"
            "    try:\n"
            "        do()\n"
            "    except:\n"
            "        pass\n"
        )
        assert _silent_handlers_in_file(src) == [4]

    def test_scanner_flags_docstring_only_body(self, tmp_path: Path):
        src = tmp_path / "m.py"
        src.write_text(
            "def f():\n"
            "    try:\n"
            "        do()\n"
            "    except Exception:\n"
            "        'intentionally ignored'\n"
        )
        assert _silent_handlers_in_file(src) == [4]

    def test_scanner_flags_ellipsis_body(self, tmp_path: Path):
        src = tmp_path / "m.py"
        src.write_text(
            "def f():\n"
            "    try:\n"
            "        do()\n"
            "    except Exception:\n"
            "        ...\n"
        )
        assert _silent_handlers_in_file(src) == [4]

    def test_scanner_ignores_narrow_exception(self, tmp_path: Path):
        src = tmp_path / "m.py"
        src.write_text(
            "def f():\n"
            "    try:\n"
            "        do()\n"
            "    except KeyError:\n"
            "        pass\n"
        )
        assert _silent_handlers_in_file(src) == []

    def test_scanner_ignores_handler_with_logging(self, tmp_path: Path):
        src = tmp_path / "m.py"
        src.write_text(
            "def f():\n"
            "    try:\n"
            "        do()\n"
            "    except Exception as exc:\n"
            "        logger.warning('oops: %s', exc)\n"
        )
        assert _silent_handlers_in_file(src) == []

    def test_scanner_ignores_handler_with_reraise(self, tmp_path: Path):
        src = tmp_path / "m.py"
        src.write_text(
            "def f():\n"
            "    try:\n"
            "        do()\n"
            "    except Exception:\n"
            "        raise\n"
        )
        assert _silent_handlers_in_file(src) == []

    def test_scanner_flags_multiple_handlers_in_one_file(self, tmp_path: Path):
        src = tmp_path / "m.py"
        src.write_text(
            "def a():\n"
            "    try:\n"
            "        do()\n"
            "    except Exception:\n"
            "        pass\n"
            "def b():\n"
            "    try:\n"
            "        do()\n"
            "    except Exception:\n"
            "        pass\n"
        )
        assert _silent_handlers_in_file(src) == [4, 9]


# ═══════════════════════════════════════════════════════════════════════════
# Regression: the specific handler the bug sat behind is accounted for
# ═══════════════════════════════════════════════════════════════════════════


class TestKnownHotspots:
    """Spot-checks on files that have historically hosted dangerous handlers."""

    def test_continuous_trader_has_not_regressed_above_cap(self):
        """CT's silent-handler count must not rise above the frozen cap.

        CT is where the dual-PENDING gate-update bug hid for months.  The
        allowlist caps it at today's count; this test makes the cap
        explicit so a reviewer skimming CT diffs can't miss a regression.
        """
        ct = "merid/trading/kalshi_continuous_trader.py"
        live = len(_silent_handlers_in_file(REPO_ROOT / ct))
        expected = _ALLOWED_SILENT_COUNTS[ct]
        assert live <= expected, (
            f"Continuous trader gained {live - expected} new silent "
            f"handler(s) (live={live}, cap={expected}).  This is the "
            f"file where the dual-PENDING gate-update bug hid — don't "
            f"add more without a very explicit justification."
        )


# ═══════════════════════════════════════════════════════════════════════════
# ``python -m`` entry point — regenerate the allowlist baseline
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # ``python -m tests.regression.test_no_silent_except_in_scalper_slice``
    # prints a fresh baseline suitable for pasting into
    # ``_ALLOWED_SILENT_COUNTS``.  Use this when you deliberately re-scope
    # the slice (e.g. adding ``merid/prediction/`` later) or do a sweep
    # that removes many silent handlers at once.
    from collections import Counter

    counts: Counter = Counter()
    for _f in _iter_slice_files():
        n = len(_silent_handlers_in_file(_f))
        if n:
            counts[_f.relative_to(REPO_ROOT).as_posix()] = n
    print(
        f"Total: {sum(counts.values())} naked-pass handlers "
        f"across {len(counts)} files"
    )
    for _path, _c in sorted(counts.items()):
        print(f'    "{_path}": {_c},')
