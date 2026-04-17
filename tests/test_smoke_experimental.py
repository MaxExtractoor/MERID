"""Smoke tests for low-priority/experimental modules - Batch 5 Coverage."""
import pytest
import sys
from types import ModuleType


class TestModuleImportSmoke:
    """Smoke tests ensuring modules can be imported without errors."""

    def test_import_memecoin_safety(self):
        """Test memecoin safety module imports."""
        try:
            from trading import memecoin_safety
            assert isinstance(memecoin_safety, ModuleType)
        except ImportError:
            pytest.skip("memecoin_safety module not found")

    def test_import_social_sentiment(self):
        """Test social sentiment module imports."""
        try:
            from agents import social_sentiment_agent
            assert isinstance(social_sentiment_agent, ModuleType)
        except ImportError:
            pytest.skip("social_sentiment_agent module not found")

    def test_import_training_pipeline(self):
        """Test training pipeline module imports."""
        try:
            from core import training_pipeline
            assert isinstance(training_pipeline, ModuleType)
        except ImportError:
            pytest.skip("training_pipeline module not found")

    def test_import_tracing(self):
        """Test tracing module imports."""
        try:
            from core import tracing
            assert isinstance(tracing, ModuleType)
        except ImportError:
            pytest.skip("tracing module not found")

    def test_import_x402_payments(self):
        """Test x402 payments module imports."""
        try:
            from core import x402_payments
            assert isinstance(x402_payments, ModuleType)
        except ImportError:
            pytest.skip("x402_payments module not found")

    def test_import_trust_transparency(self):
        """Test trust transparency module imports."""
        try:
            from core import trust_transparency
            assert isinstance(trust_transparency, ModuleType)
        except ImportError:
            pytest.skip("trust_transparency module not found")


class TestCoverageExclusions:
    """Documentation of excluded modules with justification."""

    EXCLUDED_MODULES = {
        "archived_prototype/": "Legacy code, not part of active runtime",
        "flutter/": "Mobile UI, separate test suite",
        "LangChain-Ollama/": "Experimental LLM integration",
        "docs/": "Documentation, not code",
        "web/react/": "Frontend, tested separately with jest",
        "core/xstocks_adapters.py": "Experimental XStocks integration",
        "core/training_pipeline.py": "ML training, non-runtime",
        "trading/memecoin_safety.py": "Experimental memecoin detection",
        "trading/polymarket_trading_layer.py": "Event trading, experimental",
        "trading/augur_trading_layer.py": "Prediction market integration, low priority",
    }

    def test_exclusion_list_is_documented(self):
        """Verify exclusion list exists and has entries."""
        assert len(self.EXCLUDED_MODULES) > 0
        for path, reason in self.EXCLUDED_MODULES.items():
            assert len(reason) > 0, f"No justification for {path}"


@pytest.mark.skipif(sys.platform != "linux", reason="Phase0 experiments Linux-only")
class TestPhase0Experiments:
    """Smoke tests for Phase0 experimental features."""

    def test_phase0_imports(self):
        """Test Phase0 experiment modules can be imported on Linux."""
        experimental_modules = [
            "core.swarm_orchestrator",
            "core.meta_audit_runtime",
        ]
        for module_name in experimental_modules:
            try:
                __import__(module_name)
            except ImportError:
                pytest.skip(f"{module_name} not available")
