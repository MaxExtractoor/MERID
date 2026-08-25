"""CI guard: detect new direct ``KalshiVenueClient`` order submissions.

All production order flow must go through ``order_router`` ->
``KalshiVenueClientExecutionPort`` -> ``KalshiVenueClient``.  Direct calls to
``client.place_order`` or ``client.place_order_result`` outside the known
legacy/allow-listed files are a bypass and must fail CI.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest


# Production call graph must route through order_router and the execution port.
# The files below are grandfathered legacy direct-call sites that existed before
# the ExecutionRiskFirewall. No new files may join this list without a risk
# committee exception and a matching firewall token strategy.
#
# Each entry must either:
#   - Be a final venue client/port that enforces the ExecutionRiskFirewall token
#     (client.py, venue_client_port.py, venue_adapter.py), or
#   - Be a testing-only/retired legacy path that hard-blocks in production
#     (order_manager.py, trading.py, rebalancer.py), or
#   - Contain the call only inside a docstring (robustness_integration.py).
_ALLOW_LISTED_DIRECT_CALLERS = {
    # Final venue port/adapter that enforces a firewall token before delegating.
    "merid/event_venues/kalshi/venue_client_port.py",
    "merid/event_venues/kalshi/venue_adapter.py",
    # Legacy callers that hard-block direct client use in production.
    "merid/event_venues/kalshi/order_manager.py",
    "merid/event_venues/kalshi/trading.py",
    "merid/event_venues/kalshi/rebalancer.py",
}

# Match direct invocations like client.place_order(...), self.client.place_order(...), etc.
# Ignore attribute references that are not calls (no opening paren) and ignore
# mock/test helpers.
_DIRECT_PLACE_PATTERN = re.compile(
    r"(?:self\._client|self\.client|client|kalshi_client)\.(?:place_order|place_order_result)\s*\("
)

# Production-safety patterns.  A file in the allow-list must contain at least one
# of these if it has a non-docstring direct client call.
_SAFETY_PATTERNS = re.compile(
    r"settings\.is_production|"
    r"ExecutionRiskFirewall|"
    r"firewall_approval_id|"
    r"MERID_EXIT_FIREWALL_OBSERVE_ONLY|"
    r"route_order_async",
    re.IGNORECASE,
)


def _repo_root() -> Path:
    return Path(__file__).parent.parent


def _git_tracked_python_files(repo: Path) -> list[tuple[str, Path]]:
    """Return tracked .py files under merid/ (fast, ignores build artifacts)."""
    try:
        result = subprocess.run(
            ["git", "ls-files", "merid/*.py"],
            capture_output=True,
            text=True,
            check=False,
            cwd=repo,
        )
    except FileNotFoundError:
        # If git is unavailable in this environment, skip the guard rather than
        # false-failing. CI will have git.
        return []
    return [
        (line, repo / line)
        for line in result.stdout.splitlines()
        if line.endswith(".py")
    ]


def _find_direct_place_calls(allow_listed: set[str] | None = None) -> list[tuple[str, int, str]]:
    violations: list[tuple[str, int, str]] = []
    repo = _repo_root()
    for rel, py in _git_tracked_python_files(repo):
        if allow_listed is not None and rel in allow_listed:
            continue
        # Skip test files that are expected to exercise client internals.
        if rel.startswith("tests/"):
            continue
        text = py.read_text(encoding="utf-8", errors="ignore")
        for lineno, line in enumerate(text.splitlines(), 1):
            if _DIRECT_PLACE_PATTERN.search(line):
                violations.append((rel, lineno, line.strip()))
    return violations


def _is_in_docstring(lines: list[str], call_lineno: int) -> bool:
    """Rough docstring detection: the call line sits inside an unclosed triple quote."""
    in_docstring: str | None = None
    quote_chars = ("\"\"\"", "'''")
    for i, line in enumerate(lines, 1):
        if in_docstring is None:
            if i <= call_lineno:
                for quote in quote_chars:
                    if quote in line:
                        # It could open and close on the same line; count occurrences.
                        opens = line.count(quote)
                        if opens % 2 == 1:
                            in_docstring = quote
                            break
        else:
            if in_docstring in line:
                opens = line.count(in_docstring)
                if opens % 2 == 1:
                    in_docstring = None
            if i == call_lineno:
                return True
    return False


def test_no_new_direct_venue_order_submissions():
    violations = _find_direct_place_calls(allow_listed=_ALLOW_LISTED_DIRECT_CALLERS)
    if violations:
        msg = "New direct KalshiVenueClient order submission(s) detected:\n"
        for rel, lineno, line in violations:
            msg += f"  {rel}:{lineno}: {line}\n"
        msg += (
            "All production orders must be routed through order_router and "
            "KalshiVenueClientExecutionPort so the ExecutionRiskFirewall can "
            "issue an approval token."
        )
        raise AssertionError(msg)


@pytest.mark.parametrize(
    "rel",
    sorted(_ALLOW_LISTED_DIRECT_CALLERS),
)
def test_allow_listed_caller_has_production_gate(rel: str) -> None:
    """Every allow-listed direct-call file must contain a production-safety gate."""
    repo = _repo_root()
    py = repo / rel
    if not py.exists():
        raise AssertionError(f"Allow-listed file does not exist: {rel}")

    text = py.read_text(encoding="utf-8", errors="ignore")
    lines = text.splitlines()
    direct_calls: list[int] = []
    for lineno, line in enumerate(lines, 1):
        if _DIRECT_PLACE_PATTERN.search(line):
            direct_calls.append(lineno)

    if not direct_calls:
        raise AssertionError(
            f"{rel} has no direct place_order/place_order_result calls. "
            "Remove it from _ALLOW_LISTED_DIRECT_CALLERS."
        )

    # If every direct call is inside a docstring, the file is effectively safe.
    if all(_is_in_docstring(lines, ln) for ln in direct_calls):
        return

    if not _SAFETY_PATTERNS.search(text):
        raise AssertionError(
            f"{rel} contains a non-docstring direct client call but no "
            f"recognized production-safety gate (settings.is_production, "
            f"ExecutionRiskFirewall, firewall_approval_id, "
            f"MERID_EXIT_FIREWALL_OBSERVE_ONLY, or route_order_async)."
        )
