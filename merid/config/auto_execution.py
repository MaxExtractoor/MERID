"""
Durable operator auto-execution configuration.

The canonical source is the YAML front matter in the repository's ``AGENTS.md``
file, which is under version control.  Environment variables take precedence
over the file so that an emergency manual override is possible without a code
change, but ``MERID_AUTO_EXECUTION_MODE`` must never be set in the repository
``.env``; it should be set in the secret store or operator shell only.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_AGENTS_PATH = _REPO_ROOT / "AGENTS.md"


def _parse_agents_front_matter() -> Optional[dict]:
    """Parse the YAML front matter from AGENTS.md if present.

    AGENTS.md stores the durable operator configuration inside a fenced
    ``yaml`` code block rather than as a true Jekyll-style YAML front matter,
    so we extract the first ``yaml`` fence.
    """
    try:
        text = _AGENTS_PATH.read_text(encoding="utf-8")
    except Exception:
        return None
    start = text.find("```yaml")
    if start < 0:
        return None
    end = text.find("```", start + 7)
    if end < 0:
        return None
    block = text[start + 7 : end]
    # Strip leading/trailing fences if the block contains nested --- markers.
    block = block.strip()
    if block.startswith("---"):
        block = block[3:].strip()
    if block.endswith("---"):
        block = block[:-3].strip()
    try:
        return yaml.safe_load(block) or {}
    except Exception:
        return None


def is_auto_execution_enabled() -> bool:
    """Return True when the durable operator configuration enables auto live startup.

    Sources (highest to lowest precedence):
      1. ``MERID_AUTO_EXECUTION_MODE`` environment variable (1/true/yes).
      2. ``auto_execution_mode: 1`` in ``AGENTS.md`` YAML front matter.
      3. Default: False (fail-closed).
    """
    env = os.environ.get("MERID_AUTO_EXECUTION_MODE", "").strip().lower()
    if env in ("1", "true", "yes"):
        return True
    if env in ("0", "false", "no"):
        return False

    front_matter = _parse_agents_front_matter() or {}
    value = front_matter.get("auto_execution_mode")
    return str(value) == "1"
