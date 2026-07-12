"""
Test that all critical routers can be imported without hanging.

This test ensures that the routers re-enabled in main_15m_lean.py
can be imported successfully and within reasonable time limits.
"""
import sys
import time
import pytest
from pathlib import Path

# Add repo root to sys.path
repo_root = str(Path(__file__).resolve().parents[1])
sys.path.insert(0, repo_root)


class TestRouterImports:
    """Test router imports for main_15m_lean.py."""
    
    @pytest.mark.slow
    def test_kalshi_agent_grid_router_import(self):
        """Test that kalshi_agent_grid_router can be imported within time limit."""
        start_time = time.time()
        
        # Clear module from cache if already imported
        if "web.api.kalshi_agent_grid_api" in sys.modules:
            del sys.modules["web.api.kalshi_agent_grid_api"]
        
        from web.api.kalshi_agent_grid_api import router as kalshi_agent_grid_router
        
        elapsed = time.time() - start_time
        
        # Import should complete within 20 seconds (slow but acceptable)
        assert elapsed < 20.0, f"kalshi_agent_grid_router import took {elapsed:.3f}s (limit: 20s)"
        assert kalshi_agent_grid_router is not None
    
    def test_diagnostics_router_import(self):
        """Test that diagnostics_router can be imported quickly."""
        start_time = time.time()
        
        # Clear module from cache if already imported
        if "merid.diagnostics.router" in sys.modules:
            del sys.modules["merid.diagnostics.router"]
        
        from merid.diagnostics.router import router as diagnostics_router
        
        elapsed = time.time() - start_time
        
        # Import should complete within 1 second (fast)
        assert elapsed < 1.0, f"diagnostics_router import took {elapsed:.3f}s (limit: 1s)"
        assert diagnostics_router is not None
    
    def test_individual_diagnostic_modules_import(self):
        """Test that individual diagnostic modules can be imported quickly."""
        diagnostic_modules = [
            "merid.diagnostics.time_alignment",
            "merid.diagnostics.catalog_ws_md_consistency",
            "merid.diagnostics.ws_raw_vs_parsed",
            "merid.diagnostics.market_state_health_distribution",
            "merid.diagnostics.ticker_inference_vs_close_ts",
            "merid.diagnostics.active_vs_truly_live",
            "merid.diagnostics.agent_grid_and_signals",
            "merid.diagnostics.end_to_end_signal_path",
        ]
        
        for module_name in diagnostic_modules:
            start_time = time.time()
            
            # Clear module from cache if already imported
            if module_name in sys.modules:
                del sys.modules[module_name]
            
            __import__(module_name)
            
            elapsed = time.time() - start_time
            
            # Each module should import within 0.5 seconds
            assert elapsed < 0.5, f"{module_name} import took {elapsed:.3f}s (limit: 0.5s)"
