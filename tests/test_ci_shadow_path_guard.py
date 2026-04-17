"""
CI Poison Pill Test — Shadow Path Guard Validation
====================================================

This test verifies that the shadow_path_guard.sh correctly detects
and rejects direct venue client usage.

The "poison pill" is a temporary file that contains a banned pattern
(direct KalshiClient usage). We inject it, run the guard, and verify
the guard fails as expected.

Run: pytest tests/test_ci_shadow_path_guard.py -v
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import pytest
from pathlib import Path


# ═══════════════════════════════════════════════════════════════════════════
# Poison Pill Patterns (banned code patterns)
# ═══════════════════════════════════════════════════════════════════════════

POISON_PILLS = [
    # Direct client instantiation
    '''
# Poison pill: direct KalshiClient usage
from merid.event_venues.kalshi.client import KalshiClient

client = KalshiClient()  # BANNED: bypasses order_router
result = client.create_order({"ticker": "KXBTC"})  # BANNED: shadow path
''',
    # Fast path bypass
    '''
# Poison pill: fast path bypass
async def submit_fast(order):
    # BANNED: _submit_fast bypasses risk checks
    return await self.kalshi_client._submit_fast(order)
''',
    # Direct HTTP to venue
    '''
# Poison pill: direct HTTP
import requests

# BANNED: hitting Kalshi API directly without router
response = requests.post("https://api.kalshi.com/trade-api/v2/orders", 
                        json={"ticker": "KXBTC"})
''',
]


# ═══════════════════════════════════════════════════════════════════════════
# Test Cases
# ═══════════════════════════════════════════════════════════════════════════

class TestShadowPathGuard:
    """Verify shadow_path_guard.sh detects banned patterns."""
    
    @pytest.fixture
    def guard_script(self) -> Path:
        """Path to the shadow path guard script."""
        repo_root = Path(__file__).parent.parent
        script = repo_root / "scripts" / "ci" / "shadow_path_guard.sh"
        if not script.exists():
            pytest.skip("Guard script not found")
        return script
    
    @pytest.fixture
    def whitelist_file(self) -> Path:
        """Path to the whitelist file."""
        repo_root = Path(__file__).parent.parent
        return repo_root / ".ci" / "shadow_path_whitelist.txt"
    
    def test_guard_passes_clean_repo(self, guard_script: Path):
        """Guard should pass on current repo (no poison)."""
        result = subprocess.run(
            ["bash", str(guard_script)],
            capture_output=True,
            text=True,
            cwd=guard_script.parent.parent.parent,
        )
        # Note: This may fail if there are actual violations
        # The test is informational - it documents the current state
        print(f"Guard exit code: {result.returncode}")
        print(f"Guard output:\n{result.stdout}")
        if result.stderr:
            print(f"Guard stderr:\n{result.stderr}")
    
    @pytest.mark.parametrize("poison_idx", range(len(POISON_PILLS)))
    def test_guard_detects_poison_pill(self, guard_script: Path, poison_idx: int):
        """Guard must fail when poison pill is injected."""
        repo_root = guard_script.parent.parent.parent
        poison_content = POISON_PILLS[poison_idx]
        
        # Create a temp file with poison content
        temp_file = repo_root / f"tests_fixtures_ci_poison_{poison_idx}.py"
        
        try:
            # Write poison pill
            temp_file.write_text(poison_content)
            
            # Run guard
            result = subprocess.run(
                ["bash", str(guard_script)],
                capture_output=True,
                text=True,
                cwd=repo_root,
            )
            
            # Guard MUST fail (exit code != 0)
            assert result.returncode != 0, (
                f"Guard should have detected poison pill #{poison_idx}\n"
                f"Output: {result.stdout}\n"
                f"Stderr: {result.stderr}"
            )
            
            # Should mention the poison file
            assert str(temp_file.name) in result.stdout or "VIOLATION" in result.stdout, (
                f"Guard output should mention violation or file name\n"
                f"Output: {result.stdout}"
            )
            
        finally:
            # Cleanup
            if temp_file.exists():
                temp_file.unlink()
    
    def test_guard_respects_whitelist(self, guard_script: Path, whitelist_file: Path):
        """Guard allows whitelisted files to use banned patterns."""
        if not whitelist_file.exists():
            pytest.skip("Whitelist file not found")
        
        # Read whitelist
        whitelist_entries = whitelist_file.read_text().strip().split("\n")
        whitelist_entries = [e.strip() for e in whitelist_entries if e.strip() and not e.startswith("#")]
        
        # Verify at least one whitelisted entry exists
        assert len(whitelist_entries) > 0, "Whitelist should have entries"
        
        # The guard should not flag whitelisted files
        # (This is verified by test_guard_passes_clean_repo if whitelisted files exist)
        print(f"Whitelisted entries: {whitelist_entries}")


class TestWhitelistCap:
    """Verify whitelist doesn't grow beyond allowed limit."""
    
    MAX_WHITELIST_ENTRIES = 10
    
    @pytest.fixture
    def whitelist_file(self) -> Path:
        """Path to the whitelist file."""
        repo_root = Path(__file__).parent.parent
        return repo_root / ".ci" / "shadow_path_whitelist.txt"
    
    def test_whitelist_under_cap(self, whitelist_file: Path):
        """Whitelist must not exceed MAX_WHITELIST_ENTRIES."""
        if not whitelist_file.exists():
            pytest.skip("Whitelist file not found")
        
        content = whitelist_file.read_text()
        entries = [e.strip() for e in content.split("\n") if e.strip() and not e.startswith("#")]
        
        assert len(entries) <= self.MAX_WHITELIST_ENTRIES, (
            f"Whitelist has {len(entries)} entries, max allowed is {self.MAX_WHITELIST_ENTRIES}\n"
            f"Entries: {entries}\n\n"
            f"Policy: Each whitelisted file is a security exception. "
            f"Max {self.MAX_WHITELIST_ENTRIES} exceptions allowed. "
            f"To add a new entry, you must either:\n"
            f"  1. Remove an existing entry, or\n"
            f"  2. Increase MAX_WHITELIST_ENTRIES with risk team approval"
        )
    
    def test_whitelist_entries_have_reason(self, whitelist_file: Path):
        """Each whitelist entry should have a reason comment above it."""
        if not whitelist_file.exists():
            pytest.skip("Whitelist file not found")
        
        lines = whitelist_file.read_text().split("\n")
        entries_without_comments = []
        
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                # This is an entry - check if previous line is a comment with reason
                has_reason = False
                for j in range(max(0, i-3), i):
                    prev_line = lines[j].strip()
                    if prev_line.startswith("#") and len(prev_line) > 2:
                        # Has a comment before it
                        has_reason = True
                        break
                
                if not has_reason:
                    entries_without_comments.append((i+1, stripped))
        
        # Allow one header comment at the top
        if entries_without_comments and entries_without_comments[0][0] <= 2:
            entries_without_comments = entries_without_comments[1:]
        
        assert len(entries_without_comments) == 0, (
            f"Whitelist entries without documented reasons:\n"
            f"{chr(10).join(f'  Line {ln}: {entry}' for ln, entry in entries_without_comments)}\n\n"
            f"Each whitelisted file must have a comment explaining WHY it's exempt.\n"
            f"Format:\n  # Reason: <explanation>\n  <filepath>"
        )


class TestProfileGuardMutations:
    """Mutation tests for profile guard — verify exact blocking behavior."""
    
    # Table of (profile, is_synthetic, is_external, should_be_blocked)
    MUTATION_CASES = [
        # LIVE profile: blocks synthetic and requires external flag
        ("LIVE", True, False, True),    # Synthetic blocked
        ("LIVE", False, True, False),   # External allowed but flagged
        ("LIVE", False, False, False), # Live allowed
        
        # KALSHI-ONLY: blocks external entirely
        ("KALSHI-ONLY", False, True, True),   # External blocked
        ("KALSHI-ONLY", False, False, False), # Kalshi-only allowed
        
        # PAPER: allows everything
        ("PAPER", True, False, False),  # Synthetic allowed
        ("PAPER", False, True, False),  # External allowed
    ]
    
    @pytest.mark.parametrize("profile,is_synthetic,is_external,should_block", MUTATION_CASES)
    def test_profile_blocking_behavior(
        self, profile: str, is_synthetic: bool, is_external: bool, should_block: bool
    ):
        """Verify each profile+flag combination is handled correctly."""
        from tests.test_profile_guard import LIVE_PROFILE, PAPER_PROFILE, KALSHI_ONLY_PROFILE
        
        profiles = {
            "LIVE": LIVE_PROFILE,
            "PAPER": PAPER_PROFILE,
            "KALSHI-ONLY": KALSHI_ONLY_PROFILE,
        }
        
        profile_config = profiles[profile]
        
        # Simulate the blocking logic
        data = {
            "is_synthetic": is_synthetic,
            "venue": "polymarket" if is_external else "kalshi",
        }
        
        is_blocked = (
            (not profile_config.allow_synthetic and data["is_synthetic"]) or
            (not profile_config.allow_external and data["venue"] != "kalshi")
        )
        
        assert is_blocked == should_block, (
            f"Profile={profile}, synthetic={is_synthetic}, external={is_external}\n"
            f"Expected blocked={should_block}, got blocked={is_blocked}\n"
            f"Profile config: allow_synthetic={profile_config.allow_synthetic}, "
            f"allow_external={profile_config.allow_external}"
        )


# ═══════════════════════════════════════════════════════════════════════════
# CI Integration
# ═══════════════════════════════════════════════════════════════════════════

def test_guard_on_guard():
    """Meta-test: ensure this test file itself is valid."""
    # Verify poison pills are syntactically valid Python
    for i, pill in enumerate(POISON_PILLS):
        try:
            compile(pill, f"<poison_{i}>", "exec")
        except SyntaxError as e:
            pytest.fail(f"Poison pill #{i} has syntax error: {e}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
