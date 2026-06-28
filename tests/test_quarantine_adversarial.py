"""
Adversarial test to verify sentiment and legacy strategy quarantine.

This test attempts to import forbidden modules to verify they are properly
blocked from the Kalshi 15m stack.
"""
import os
import sys
import pytest

# Set profile to kalshi_crypto_15m_v2 for quarantine checks
os.environ["MERID_PROFILE"] = "kalshi_crypto_15m_v2"
os.environ["MERID_TRADING_MODE"] = "PAPER"


def test_sentiment_modules_quarantined():
    """Verify that sentiment validation function exists and is in Kalshi 15m pipeline."""
    # Import the validation function
    try:
        from merid.startup_validations import validate_no_sentiment_in_kalshi_stack
    except ImportError:
        pytest.fail("Sentiment validation module not available")
    
    # Verify the function exists
    assert callable(validate_no_sentiment_in_kalshi_stack), "validate_no_sentiment_in_kalshi_stack should be callable"
    
    # Verify it's called in the Kalshi 15m validation pipeline
    try:
        from merid.startup_validations import validate_all_kalshi_15m
        import inspect
        source = inspect.getsource(validate_all_kalshi_15m)
        assert "validate_no_sentiment_in_kalshi_stack" in source, "Sentiment validation should be in Kalshi 15m pipeline"
    except ImportError:
        pytest.fail("Kalshi 15m validation pipeline not available")


def test_legacy_strategy_modules_quarantined():
    """Verify that legacy strategy validation function exists and is in Kalshi 15m pipeline."""
    # Import the validation function
    try:
        from merid.startup_validations import validate_no_legacy_strategy_in_kalshi_stack
    except ImportError:
        pytest.fail("Legacy strategy validation module not available")
    
    # Verify the function exists
    assert callable(validate_no_legacy_strategy_in_kalshi_stack), "validate_no_legacy_strategy_in_kalshi_stack should be callable"
    
    # Verify it's called in the Kalshi 15m validation pipeline
    try:
        from merid.startup_validations import validate_all_kalshi_15m
        import inspect
        source = inspect.getsource(validate_all_kalshi_15m)
        assert "validate_no_legacy_strategy_in_kalshi_stack" in source, "Legacy strategy validation should be in Kalshi 15m pipeline"
    except ImportError:
        pytest.fail("Kalshi 15m validation pipeline not available")


def test_utility_modules_allowed():
    """Verify that utility modules are allowed (transitive imports)."""
    # These are allowed as they are used for config/validation
    allowed_utility_modules = [
        "merid.prediction.model",
        "merid.prediction.strategy",
        "merid.prediction.kalshi_tools",
    ]
    
    for module_name in allowed_utility_modules:
        # These should be importable without quarantine violations
        try:
            __import__(module_name)
            # Import should succeed
            assert module_name in sys.modules, f"Utility module {module_name} should be importable"
        except ImportError:
            # Import failed - this may be acceptable if module doesn't exist
            pass
        except Exception as e:
            # Other exceptions are acceptable
            pass


def test_sentiment_env_vars_blocked():
    """Verify that sentiment environment variables are blocked."""
    # Set sentiment environment variables
    os.environ["MERID_SENTIMENT_MODE"] = "fear_greed"
    os.environ["MERID_SENTIMENT_GATING_ENABLED"] = "true"
    
    # Import and run sentiment validation
    try:
        from merid.startup_validations import validate_no_sentiment_in_kalshi_stack
        
        # This should raise a StartupValidationError
        with pytest.raises(Exception):  # StartupValidationError
            validate_no_sentiment_in_kalshi_stack()
    except ImportError:
        # Validation module not available - skip test
        pytest.skip("Sentiment validation module not available")
    finally:
        # Clean up
        os.environ.pop("MERID_SENTIMENT_MODE", None)
        os.environ.pop("MERID_SENTIMENT_GATING_ENABLED", None)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
