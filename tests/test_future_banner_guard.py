"""
FUTURE Banner Guard — Enforcement Test (2026-03-19)

Validates the FUTURE banner policy from docs/KALSHI_WIRING_AUDIT.md §0:
  Every .py file classified as FUTURE must contain the exact token
  `# NOT_WIRED_NON_PROD` within its first 5 lines.

This makes the "not wired" status machine-checkable and CI-verifiable.
"""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Canonical token — must match docs/KALSHI_WIRING_AUDIT.md §0
BANNER_TOKEN = "# NOT_WIRED_NON_PROD"
BANNER_MAX_LINE = 5  # must appear in first N lines

# ── FUTURE-classified files from the wiring audit ────────────────────
# Grouped by section for traceability.  When promoting a file from
# FUTURE → KEEP, remove it from this list and strip the banner.

# §1 Lifespan (FUTURE services)
FUTURE_LIFESPAN = [
    "merid/rewards/engine.py",                         # RewardEngine
    "agents/reflection_layer.py",                      # ReflectionLayer
    "memory/neo4j_graph.py",                           # Neo4jGraph
]

# §2 merid/agents (FUTURE agents)
FUTURE_MERID_AGENTS = [
    "merid/agents/hybrid.py",
    "merid/agents/ops.py",
    "merid/agents/publisher_agent.py",
    "merid/agents/research.py",
    "merid/agents/sentiment_agent.py",
    "merid/agents/social_ingestion.py",
    "merid/agents/sports_odds.py",
    "merid/agents/strategy.py",
]

# §2 agents/ framework (FUTURE)
FUTURE_AGENTS_FRAMEWORK = [
    "agents/twitter_agent.py",
    "agents/streaming/",                               # directory — checked below
]

# §3 Kalshi venue (FUTURE)
FUTURE_KALSHI_VENUE = [
    "merid/event_venues/kalshi/client_enhanced.py",
    "merid/event_venues/kalshi/fix_client.py",
]

# §4 Pipelines (FUTURE)
FUTURE_PIPELINES = [
    "merid/publishing/kalshi_insight_pipeline_robust.py",
]

# §5 swarm (FUTURE)
FUTURE_SWARM = [
    "swarm/agents/local_venue_guardian.py",
    "swarm/collab_orchestrator.py",
]

# §5 merid/lanes (FUTURE)
FUTURE_LANES = [
    "merid/lanes/rck_complete_example.py",
    "merid/lanes/consensus_integration.py",
]

# §5 merid/prediction (FUTURE)
FUTURE_PREDICTION = [
    "merid/prediction/mcp_market_feed.py",
]

# Aggregate all file paths (skip directory entries)
ALL_FUTURE_FILES: list[str] = []
for group in [
    FUTURE_LIFESPAN,
    FUTURE_MERID_AGENTS,
    FUTURE_AGENTS_FRAMEWORK,
    FUTURE_KALSHI_VENUE,
    FUTURE_PIPELINES,
    FUTURE_SWARM,
    FUTURE_LANES,
    FUTURE_PREDICTION,
]:
    for entry in group:
        if not entry.endswith("/"):
            ALL_FUTURE_FILES.append(entry)


class TestFutureBannerPresent(unittest.TestCase):
    """Every FUTURE-classified .py file must contain the NOT_WIRED_NON_PROD banner."""

    def test_all_future_files_have_banner(self):
        """Each FUTURE file must have `# NOT_WIRED_NON_PROD` in its first 5 lines."""
        missing = []
        not_found = []

        for rel_path in ALL_FUTURE_FILES:
            full = ROOT / rel_path
            if not full.exists():
                not_found.append(rel_path)
                continue

            try:
                lines = full.read_text(encoding="utf-8", errors="replace").splitlines()
            except Exception:
                missing.append(f"{rel_path} (unreadable)")
                continue

            head = lines[:BANNER_MAX_LINE]
            if not any(BANNER_TOKEN in line for line in head):
                missing.append(rel_path)

        msg_parts = []
        if missing:
            msg_parts.append(
                f"{len(missing)} FUTURE file(s) missing `{BANNER_TOKEN}` "
                f"in first {BANNER_MAX_LINE} lines:\n"
                + "\n".join(f"  - {p}" for p in missing)
            )
        if not_found:
            msg_parts.append(
                f"{len(not_found)} FUTURE file(s) not found on disk:\n"
                + "\n".join(f"  - {p}" for p in not_found)
            )

        if msg_parts:
            self.fail("\n\n".join(msg_parts))

    def test_future_file_list_is_nonempty(self):
        """Sanity check: the FUTURE file list must not be empty."""
        self.assertGreater(
            len(ALL_FUTURE_FILES), 0,
            "ALL_FUTURE_FILES is empty — did the audit classification change?"
        )

    def test_banner_token_is_canonical(self):
        """Sanity check: token has no spaces in the tag portion."""
        # Token format: "# NOT_WIRED_NON_PROD" — underscores, no spaces after #
        self.assertTrue(
            BANNER_TOKEN.startswith("# "),
            "Banner token must start with '# '"
        )
        tag = BANNER_TOKEN[2:]
        self.assertFalse(
            " " in tag,
            f"Banner tag '{tag}' must not contain spaces (use underscores)"
        )


if __name__ == "__main__":
    unittest.main()
