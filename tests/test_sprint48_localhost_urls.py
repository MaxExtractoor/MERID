"""Tests for Sprint 48 — No hardcoded localhost URLs in backend API calls."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MERID_DIR = ROOT / "merid"
WEB_API_DIR = ROOT / "web" / "api"

# Allowlisted: config defaults, docstrings, Kafka bootstrap
ALLOWLISTED_FILES = {
    "settings.py",           # Pydantic default for NEO4J_URI
    "ws_kafka_bridge.py",    # Kafka bootstrap_servers default + env fallback
    "us_compliant_markets.py",  # Docstring example
    "ws_trade_events.py",    # Docstring example
}


class TestNoHardcodedLocalhost:
    """Backend should not have hardcoded localhost in HTTP/WS calls."""

    def test_no_localhost_in_fetch_calls(self):
        """No requests.get/post to localhost — use internal imports instead."""
        violations = []
        for d in [MERID_DIR, WEB_API_DIR]:
            if not d.exists():
                continue
            for f in d.rglob("*.py"):
                if f.name in ALLOWLISTED_FILES:
                    continue
                text = f.read_text(encoding="utf-8", errors="ignore")
                for i, line in enumerate(text.split("\n"), 1):
                    stripped = line.strip()
                    if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith(">>>"):
                        continue
                    if re.search(r'(requests\.|httpx\.|aiohttp\.).*localhost', line):
                        violations.append(f"{f.name}:L{i}")
                    if re.search(r'(get|post|put|delete)\(["\']http://localhost', line):
                        violations.append(f"{f.name}:L{i}")
        assert len(violations) == 0, f"Hardcoded localhost HTTP calls: {violations}"
