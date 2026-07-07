"""Test that production code does not import legacy order_router_15m.

This test verifies that no production code imports the legacy order_router_15m module,
which is marked as mock/legacy and should not be used in production.
"""

import pytest
import os
import re


class TestNoLegacyRouterImports:
    """Test that production code does not import legacy order_router_15m."""

    def test_no_production_code_imports_legacy_router(self):
        """Verify no production code imports order_router_15m."""
        # Search for imports of order_router_15m
        import_pattern = re.compile(
            r'from.*order_router_15m|import.*order_router_15m',
            re.IGNORECASE
        )
        
        violating_files = []
        
        # Walk the codebase
        for root, dirs, files in os.walk(os.path.join(os.path.dirname(__file__), "..", "..", "..")):
            # Skip common exclusions
            dirs[:] = [d for d in dirs if d not in ['.git', '__pycache__', 'node_modules', '.venv']]
            
            for file in files:
                if file.endswith('.py'):
                    file_path = os.path.join(root, file)
                    
                    # Skip test files and audit script itself
                    if 'test' in file_path or 'audit_agent_grid_flaws' in file_path:
                        continue
                    
                    # Skip the legacy router file itself
                    if 'order_router_15m.py' in file_path:
                        continue
                    
                    # Skip __pycache__ directories
                    if '__pycache__' in file_path:
                        continue
                    
                    try:
                        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                            content = f.read()
                        
                        if import_pattern.search(content):
                            violating_files.append(file_path)
                    except Exception:
                        continue
        
        # Assert no violations
        assert len(violating_files) == 0, (
            f"Found {len(violating_files)} production files importing legacy order_router_15m:\n"
            + "\n".join(f"  - {f}" for f in violating_files)
        )

    def test_legacy_router_marked_as_mock(self):
        """Verify that order_router_15m.py is marked as legacy/mock."""
        router_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "..",
            "merid",
            "event_venues",
            "kalshi",
            "order_router_15m.py"
        )
        
        with open(router_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        
        # Check for warning comments
        assert "NOT USED IN PRODUCTION" in content or "MOCK" in content or "LEGACY" in content, (
            "order_router_15m.py should be marked as legacy/mock with warning comments"
        )
