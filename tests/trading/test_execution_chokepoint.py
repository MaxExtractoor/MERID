"""Execution chokepoint invariant — no production bypasses of ``route_order_async``.

This is a grep-based guardrail that prevents regression back to direct
Kalshi submit calls outside the canonical order router.  It complements
the runtime caller-allowlist in ``merid/event_venues/kalshi/order_router.py``.

Rules
-----
Production code (``.py`` files outside ``tests/``, ``_legacy/``, vendor,
and the router/client themselves) MUST NOT contain direct Kalshi submit
patterns, except for a small, explicitly-documented allowlist kept in
this file.  Any new occurrence fails the test.

The allowlist is keyed by repo-relative path and stores the **expected
count** of each forbidden pattern so adding a new bypass is caught
immediately (count goes up) and removing a documented one is also caught
(count goes down).

See ``docs/TRADING_OWNERSHIP_DECISION.md`` for the policy and
``docs/ORDER_FLOW_AND_OVERTRADING_AUDIT.md`` for the bypass audit.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Dict, List, Tuple

import pytest

# ─────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parents[2]

# Directories to scan.  Only production source dirs — tests are excluded
# because they legitimately exercise the forbidden patterns via mocks.
_PROD_ROOTS = [
    "merid",
    "web",
    "core",
    "agents",
    "trading",
    "scripts",
]

# Paths that are the canonical implementations of each pattern and thus
# allowed to contain them without counting as bypasses.  These are either
# (a) the router itself, (b) low-level venue transport / client wrappers,
# or (c) Kalshi-internal plumbing reachable only via the router.
_CANONICAL_OWNERS: Tuple[str, ...] = (
    "merid/event_venues/kalshi/order_router.py",
    "merid/event_venues/kalshi/client.py",
    "merid/event_venues/kalshi/ws.py",
    "merid/event_venues/kalshi/executor.py",
    "merid/event_venues/kalshi/trading.py",          # legacy wrapper; not an entry point
    "merid/event_venues/kalshi/venue_adapter.py",    # adapter used *by* the router
    "merid/event_venues/kalshi/robustness_integration.py",  # contains docstring examples + scanner strings
    "merid/execution/executors/kalshi_enhanced.py",
    "merid/trading/ct_execution_adapter.py",
    "trading/adapters/kalshi.py",
    "trading/integrations/kalshi_client.py",
)

# Files matching these substrings contain patterns that look like Kalshi
# submits but are NOT Kalshi (e.g. Binance, Polymarket docs examples).
# Skipped to avoid false positives.
_NON_KALSHI_FILE_SUBSTRS: Tuple[str, ...] = (
    "binance",
    "polymarket",
    "coinbase",
    "dydx",
)

# Always skip these directories (absolute substrings).
_SKIP_DIR_SUBSTRS: Tuple[str, ...] = (
    os.sep + "_legacy" + os.sep,
    os.sep + "__pycache__" + os.sep,
    os.sep + "archive" + os.sep,
    os.sep + "docs_archive" + os.sep,
    os.sep + ".venv" + os.sep,
    os.sep + "venv" + os.sep,
    os.sep + "node_modules" + os.sep,
)

# ─────────────────────────────────────────────────────────────────────
# Forbidden patterns
# ─────────────────────────────────────────────────────────────────────
# Each entry: (pattern_id, compiled_regex, human_description).

_PATTERNS: List[Tuple[str, re.Pattern, str]] = [
    (
        "kalshi_place_order",
        re.compile(r"\.kalshi\.place_order\b"),
        "direct `self.kalshi.place_order(...)` call — route via route_order_async",
    ),
    (
        "client_place_order",
        re.compile(r"\bclient\.place_order\b"),
        "direct `client.place_order(...)` call — route via route_order_async",
    ),
    (
        "client_batch_place_orders",
        re.compile(r"\bclient\.batch_place_orders\b"),
        "direct `client.batch_place_orders(...)` — route each through route_order_async",
    ),
    (
        "post_portfolio_orders",
        re.compile(r"""_post\(\s*["']/portfolio/orders"""),
        "direct `_post('/portfolio/orders', ...)` — route via route_order_async",
    ),
    (
        "fix_submit_order",
        re.compile(r"\bfix\.submit_order\b"),
        "direct `fix.submit_order(...)` — must be gated by shared GlobalRiskGuard + dedup",
    ),
]

# ─────────────────────────────────────────────────────────────────────
# Allow-list: documented bypasses with expected counts.
#
# Format: {(rel_path, pattern_id): expected_occurrence_count}
# Each entry MUST carry a justification comment right above it.
# ─────────────────────────────────────────────────────────────────────

_ALLOWED_BYPASSES: Dict[Tuple[str, str], int] = {
    # CT has two direct ``_post("/portfolio/orders", ...)`` call sites:
    #   1. ``_submit_sell_yes_limit`` — exit/close path that *reduces* exposure.
    #   2. Break-glass legacy entry path reached only when
    #      ``CT_USE_ROUTER_PERCENT=0`` (emits WARNING on every use); router is
    #      the default (=100) so this path is unreachable in normal ops.
    ("merid/trading/kalshi_continuous_trader.py", "post_portfolio_orders"): 2,

    # FIX gateway transport — the only legitimate site of ``fix.submit_order``
    # is the FIX endpoint itself, which pre-gates with shared GlobalRiskGuard
    # + OrderDedupRegistry explicitly (see web/api/kalshi_api.py::fix_submit_order).
    ("web/api/kalshi_api.py", "fix_submit_order"): 1,

    # ── Out-of-scope for THIS slice (to be closed in a follow-up) ───────
    # Legacy market-maker modules that pre-date the router chokepoint.
    # They are not reachable from the production continuous-trader / lane
    # paths but still exist in the tree.  A future slice should either
    # route them through ``route_order_async`` or remove them.
    ("core/swarm_market_maker.py", "kalshi_place_order"): 1,
    ("core/market_maker_prediction.py", "kalshi_place_order"): 1,

    # Standalone script — older mirror of the CT loop kept for ops triage.
    # Not imported by production backend.  Flagged for removal.
    ("scripts/kalshi_continuous_trader.py", "post_portfolio_orders"): 1,
}


# ─────────────────────────────────────────────────────────────────────
# Scanner
# ─────────────────────────────────────────────────────────────────────

def _iter_production_py_files():
    for root_name in _PROD_ROOTS:
        root = REPO_ROOT / root_name
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            p = str(path)
            if any(s in p for s in _SKIP_DIR_SUBSTRS):
                continue
            # Skip test files (``tests/`` tree never reached via _PROD_ROOTS,
            # but also skip inlined ``test_*.py`` and ``*_test.py``).
            name = path.name
            if name.startswith("test_") or name.endswith("_test.py"):
                continue
            # Skip non-Kalshi venue files (Binance/Polymarket/etc.)
            low = p.lower()
            if any(s in low for s in _NON_KALSHI_FILE_SUBSTRS):
                continue
            yield path


def _rel(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT)).replace(os.sep, "/")


_TRIPLE_QUOTE = re.compile(r'("""|\'\'\')')


def _strip_comments_and_docstrings(text: str) -> str:
    """Remove ``# ...`` comments and triple-quoted string bodies.

    This is a pragmatic line-based filter, not a full Python parser.  It's
    enough to cut the vast majority of false positives in docstrings and
    inline-commented example code.
    """
    out: List[str] = []
    in_doc = False
    doc_delim = ""
    for line in text.splitlines():
        # Handle triple-quoted string spans
        if in_doc:
            if doc_delim in line:
                # Close here; keep only content after the closing delim
                idx = line.index(doc_delim) + 3
                line = line[idx:]
                in_doc = False
            else:
                continue
        # Look for opening triple quotes on this line.
        m = _TRIPLE_QUOTE.search(line)
        while m:
            delim = m.group(1)
            open_idx = m.start()
            # Find a closing delim on the same line after the opener
            close_search = line.find(delim, open_idx + 3)
            if close_search == -1:
                # Docstring continues on following lines
                line = line[:open_idx]
                in_doc = True
                doc_delim = delim
                break
            # Single-line triple-quoted string: strip it out
            line = line[:open_idx] + line[close_search + 3:]
            m = _TRIPLE_QUOTE.search(line)
        # Strip ``# ...`` comments (naive: breaks for # inside strings,
        # but acceptable for our patterns which don't involve ``#``).
        hash_idx = line.find("#")
        if hash_idx >= 0:
            line = line[:hash_idx]
        out.append(line)
    return "\n".join(out)


def _scan() -> Dict[Tuple[str, str], int]:
    """Return {(rel_path, pattern_id): count} for every hit in production."""
    hits: Dict[Tuple[str, str], int] = {}
    for path in _iter_production_py_files():
        rel = _rel(path)
        if rel in _CANONICAL_OWNERS:
            continue
        try:
            raw = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        text = _strip_comments_and_docstrings(raw)
        for pattern_id, regex, _desc in _PATTERNS:
            n = len(regex.findall(text))
            if n:
                hits[(rel, pattern_id)] = n
    return hits


# ─────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────

def test_no_undocumented_direct_submit_bypasses():
    """Fail if production code contains a forbidden submit pattern not in the allowlist.

    This is the core invariant: every live Kalshi submit flows through
    ``route_order_async``.  Documented exceptions (CT exit path, FIX gateway)
    are pinned by exact count in ``_ALLOWED_BYPASSES``.
    """
    hits = _scan()
    violations: List[str] = []

    for (rel, pat_id), count in sorted(hits.items()):
        expected = _ALLOWED_BYPASSES.get((rel, pat_id), 0)
        if count > expected:
            desc = next(d for pid, _r, d in _PATTERNS if pid == pat_id)
            violations.append(
                f"{rel} :: {pat_id} → found {count} occurrence(s), "
                f"expected ≤ {expected}. {desc}"
            )

    # Also flag entries in the allow-list whose count has dropped (a
    # documented bypass was removed — great, update the allow-list).
    for (rel, pat_id), expected in _ALLOWED_BYPASSES.items():
        actual = hits.get((rel, pat_id), 0)
        if actual < expected:
            violations.append(
                f"{rel} :: {pat_id} → documented bypass count dropped "
                f"({actual} < {expected}) — remove from _ALLOWED_BYPASSES."
            )

    assert not violations, (
        "Execution chokepoint invariant failed.  Route direct Kalshi submits "
        "through ``route_order_async`` (or update the documented allow-list):\n  - "
        + "\n  - ".join(violations)
    )


def test_allowlist_entries_still_exist():
    """Every allow-listed bypass must still exist in the file it references.

    Prevents the allow-list from drifting into dead entries that mask real
    violations if the underlying file is ever restructured.
    """
    hits = _scan()
    missing: List[str] = []
    for (rel, pat_id), expected in _ALLOWED_BYPASSES.items():
        if expected == 0:
            continue
        abs_path = REPO_ROOT / rel
        if not abs_path.exists():
            missing.append(f"{rel}: file does not exist (allow-list stale)")
            continue
        if hits.get((rel, pat_id), 0) == 0:
            missing.append(f"{rel} :: {pat_id}: allow-listed bypass not found in file")
    assert not missing, (
        "Execution chokepoint allow-list drift:\n  - " + "\n  - ".join(missing)
    )


def test_router_is_canonical_owner():
    """Sanity: the router file itself owns one of the forbidden patterns."""
    router_path = REPO_ROOT / "merid/event_venues/kalshi/order_router.py"
    assert router_path.exists(), "order_router.py missing"
    text = router_path.read_text(encoding="utf-8", errors="ignore")
    # route_order_async is the chokepoint by name; must exist
    assert "async def route_order_async" in text


def test_ct_execution_adapter_goes_through_router():
    """The CT adapter's ``execute_live`` must call ``route_order_async``."""
    p = REPO_ROOT / "merid/trading/ct_execution_adapter.py"
    assert p.exists(), "ct_execution_adapter.py missing"
    text = p.read_text(encoding="utf-8", errors="ignore")
    assert "route_order_async" in text, (
        "CT execution adapter must import/call route_order_async — "
        "otherwise CT still bypasses the canonical chokepoint."
    )


def test_crypto15m_lane_uses_router_for_live_orders():
    """Regression guard for the crypto15m_lane bypass fix (§1 of master spec)."""
    p = REPO_ROOT / "merid/lanes/crypto15m_lane.py"
    assert p.exists(), "crypto15m_lane.py missing"
    text = p.read_text(encoding="utf-8", errors="ignore")
    assert "route_order_async" in text, (
        "crypto15m_lane must route live orders through route_order_async"
    )
    # Sanity: the old direct pattern is gone.
    assert "self.kalshi.place_order" not in text, (
        "crypto15m_lane still contains direct self.kalshi.place_order — "
        "must route via route_order_async."
    )


def test_kalshi_api_batch_goes_through_router():
    """Batch endpoint must iterate orders through route_order_async."""
    p = REPO_ROOT / "web/api/kalshi_api.py"
    text = p.read_text(encoding="utf-8", errors="ignore")
    # Find the batch endpoint body
    batch_idx = text.find("async def batch_place_orders")
    assert batch_idx >= 0, "batch_place_orders endpoint missing"
    next_def = text.find("\nasync def ", batch_idx + 1)
    if next_def == -1:
        next_def = text.find("\ndef ", batch_idx + 1)
    body = text[batch_idx : next_def if next_def > 0 else len(text)]
    assert "route_order_async" in body, (
        "batch_place_orders must route each order through route_order_async, "
        "not call client.batch_place_orders directly."
    )


def test_fix_submit_order_gated_by_shared_guard():
    """FIX path must explicitly gate on shared GlobalRiskGuard + dedup."""
    p = REPO_ROOT / "web/api/kalshi_api.py"
    text = p.read_text(encoding="utf-8", errors="ignore")
    fix_idx = text.find("async def fix_submit_order")
    assert fix_idx >= 0, "fix_submit_order endpoint missing"
    next_def = text.find("\nasync def ", fix_idx + 1)
    if next_def == -1:
        next_def = text.find("\ndef ", fix_idx + 1)
    body = text[fix_idx : next_def if next_def > 0 else len(text)]
    assert "check_intent" in body, "fix_submit_order must call shared GlobalRiskGuard.check_intent"
    assert "order_dedup_registry" in body or "OrderDedupRegistry" in body, (
        "fix_submit_order must consult OrderDedupRegistry"
    )
