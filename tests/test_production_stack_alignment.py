"""
Regression tests to prevent legacy contamination.

These tests ensure that the production 15m stack (main_15m_lean.py) is used
exclusively and that legacy code (main.py) does not contaminate the production path.

Run:
    pytest tests/test_production_stack_alignment.py -v
"""
import pytest
import sys
from pathlib import Path


class TestProductionStackAlignment:
    """Verify production stack alignment and prevent legacy contamination."""

    def test_main_15m_lean_module_exists(self):
        """Production main_15m_lean.py must exist and be importable."""
        from web import main_15m_lean
        assert main_15m_lean is not None
        assert hasattr(main_15m_lean, 'app')

    def test_startup_script_uses_main_15m_lean(self):
        """Startup script must reference main_15m_lean, not legacy main.py."""
        startup_script = Path(__file__).parent.parent / "start_15m.ps1"
        assert startup_script.exists(), "start_15m.ps1 not found"
        
        content = startup_script.read_text()
        assert "main_15m_lean" in content, "Startup script must reference main_15m_lean"
        assert "web.main:app" not in content, "Startup script must not use legacy web.main:app"

    def test_legacy_main_is_wrapper(self):
        """Legacy main.py.legacy must be a wrapper that imports from main_15m_lean."""
        legacy_main = Path(__file__).parent.parent / "web" / "main.py.legacy"
        if legacy_main.exists():
            content = legacy_main.read_text()
            assert "main_15m_lean" in content, "Legacy wrapper must import from main_15m_lean"
            assert "PROFILE-GUARD" in content, "Legacy wrapper must have profile guard comment"

    def test_no_direct_main_py_imports_in_tests(self):
        """Tests should not import app from web.main directly (use main_15m_lean).
        
        Exception: Tests may use web.main.create_app for test compatibility
        (main.py.legacy is a wrapper that imports from main_15m_lean).
        """
        test_dir = Path(__file__).parent
        violations = []
        
        for test_file in test_dir.glob("*.py"):
            try:
                content = test_file.read_text(encoding='utf-8')
            except UnicodeDecodeError:
                # Skip files with encoding issues (likely binary or non-UTF-8)
                continue
            # Check for direct app imports (create_app is allowed for testing)
            if "from web.main import app" in content:
                # Allow main.py.legacy references
                if "main.py.legacy" not in content:
                    violations.append(str(test_file))
        
        assert not violations, f"Tests import legacy web.main app directly: {violations}"

    def test_production_app_has_expected_attributes(self):
        """Production app must have expected FastAPI attributes."""
        from web.main_15m_lean import app
        
        assert hasattr(app, 'routes'), "App must have routes"
        assert hasattr(app, 'state'), "App must have state"
        # Verify it's a FastAPI app
        assert 'FastAPI' in str(type(app)), "App must be a FastAPI instance"

    def test_lifespan_function_exists_in_production(self):
        """Production main_15m_lean must have lifespan function."""
        from web import main_15m_lean
        
        assert hasattr(main_15m_lean, 'lifespan'), "main_15m_lean must have lifespan function"
        assert callable(main_15m_lean.lifespan), "lifespan must be callable"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
