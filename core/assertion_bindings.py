"""
MERID Assertion Framework - Language Bindings

Provides language-specific helpers and integration patterns for MERID services.
"""

from functools import wraps
import time
import traceback
from typing import Dict, Any, Optional, Callable
from contextlib import contextmanager

from core.assertion_framework import (
    get_assertion_client, AssertionStatus, AssertionSeverity,
    assert_not_null, assert_timeout, assert_resource_limits
)
from utils.logger import get_logger

logger = get_logger("merid_assertions")

# Python Decorators and Context Managers
def assertion_template(
    template_id: str,
    severity: Optional[AssertionSeverity] = None,
    owner_team: Optional[str] = None,
    on_failure: str = "raise"  # "raise", "log", "ignore"
):
    """Decorator for wrapping functions with assertion templates."""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.time()
            client = get_assertion_client()
            
            # Prepare assertion context
            assertion_id = f"{template_id}_{func.__name__}_{int(start_time)}"
            subject = {
                "function": func.__name__,
                "module": func.__module__,
                "args_count": len(args),
                "kwargs_keys": list(kwargs.keys())
            }
            
            try:
                # Execute function
                result = func(*args, **kwargs)
                
                # Record successful assertion
                duration_ms = (time.time() - start_time) * 1000
                client.record(
                    template_id=template_id,
                    parameters={
                        "duration_ms": duration_ms,
                        "success": True,
                        "error": None
                    },
                    status=AssertionStatus.PASSED,
                    subject=subject
                )
                
                return result
                
            except Exception as e:
                # Record failed assertion
                duration_ms = (time.time() - start_time) * 1000
                error_details = f"{type(e).__name__}: {str(e)}"
                
                client.record(
                    template_id=template_id,
                    parameters={
                        "duration_ms": duration_ms,
                        "success": False,
                        "error": error_details,
                        "traceback": traceback.format_exc()
                    },
                    status=AssertionStatus.FAILED,
                    details=error_details,
                    subject=subject
                )
                
                if on_failure == "raise":
                    raise
                elif on_failure == "log":
                    logger.error(f"Assertion failed for {func.__name__}: {e}")
                    return None
                elif on_failure == "ignore":
                    return None
                    
        return wrapper
    return decorator

def null_check(
    key: str,
    context: str,
    message: Optional[str] = None,
    severity: Optional[AssertionSeverity] = None
):
    """Decorator for null checking function return values."""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            result = func(*args, **kwargs)
            return assert_not_null(key, result, context, message, severity)
        return wrapper
    return decorator

def timeout_check(
    max_duration_ms: float,
    operation: Optional[str] = None,
    context: str = "function",
    severity: Optional[AssertionSeverity] = None
):
    """Decorator for timeout checking function execution."""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                duration_ms = (time.time() - start_time) * 1000
                
                op_name = operation or f"{func.__module__}.{func.__name__}"
                assert_timeout(op_name, duration_ms, max_duration_ms, context, severity)
                
                return result
            except Exception as e:
                duration_ms = (time.time() - start_time) * 1000
                op_name = operation or f"{func.__module__}.{func.__name__}"
                
                # Still record the timeout assertion even on failure
                assert_timeout(op_name, duration_ms, max_duration_ms, context, severity)
                raise
                
        return wrapper
    return decorator

@contextmanager
def resource_monitor(
    job_name: str,
    max_cpu_pct: float,
    max_memory_mb: float,
    severity: Optional[AssertionSeverity] = None
):
    """Context manager for monitoring resource usage."""
    import psutil
    import os
    
    process = psutil.Process(os.getpid())
    start_time = time.time()
    
    try:
        yield
        
        # Monitor resource usage
        cpu_pct = process.cpu_percent()
        memory_mb = process.memory_info().rss / 1024 / 1024
        
        assert_resource_limits(
            job_name, cpu_pct, memory_mb,
            max_cpu_pct, max_memory_mb, severity
        )
        
    except Exception as e:
        # Still record resource usage even on failure
        cpu_pct = process.cpu_percent()
        memory_mb = process.memory_info().rss / 1024 / 1024
        
        assert_resource_limits(
            job_name, cpu_pct, memory_mb,
            max_cpu_pct, max_memory_mb, severity
        )
        raise

# MERID-Specific Assertion Templates
def assert_forecast_must_resolve(
    market_id: str,
    forecast_time: float,
    max_resolution_lag_hours: float,
    resolution_source: str,
    severity: Optional[AssertionSeverity] = None
) -> str:
    """Assert that a forecast will be resolved within the allowed time."""
    client = get_assertion_client()
    assertion_id = f"forecast_resolve_{market_id}_{int(forecast_time)}"
    
    client.record(
        template_id="reality.forecast.must_resolve",
        parameters={
            "market_id": market_id,
            "forecast_time": forecast_time,
            "max_resolution_lag_hours": max_resolution_lag_hours,
            "resolution_source": resolution_source
        },
        status=AssertionStatus.PENDING,
        subject={"market_id": market_id, "forecast_time": forecast_time}
    )
    
    return assertion_id

def assert_spread_and_liquidity_rules(
    venue_a: str,
    venue_b: str,
    min_spread: float,
    min_liquidity: float,
    severity: Optional[AssertionSeverity] = None
) -> bool:
    """Assert that arbitrage execution meets spread and liquidity requirements."""
    # This would be called with actual spread/liquidity data
    # For now, it's a template for the assertion
    
    client = get_assertion_client()
    
    # In real usage, you'd pass actual spread and liquidity values
    # This is a placeholder for the assertion pattern
    parameters = {
        "venue_a": venue_a,
        "venue_b": venue_b,
        "min_spread": min_spread,
        "min_liquidity": min_liquidity
        # In real usage: "actual_spread": spread, "actual_liquidity": liquidity
    }
    
    # For now, assume it passes (would be determined by actual data)
    client.record(
        template_id="risk.arbitrage.spread_liquidity_rules",
        parameters=parameters,
        status=AssertionStatus.PASSED,
        subject={"venue_pair": f"{venue_a}-{venue_b}"}
    )
    
    return True

def assert_risk_limits(
    asset_id: str,
    exposure_amount: float,
    exposure_limit: float,
    severity: Optional[AssertionSeverity] = None
) -> bool:
    """Assert that exposure stays within risk limits."""
    exceeded = exposure_amount > exposure_limit
    
    client = get_assertion_client()
    status = AssertionStatus.FAILED if exceeded else AssertionStatus.PASSED
    details = f"Exposure {exposure_amount:.2f} exceeds limit {exposure_limit:.2f}" if exceeded else None
    
    client.record(
        template_id="risk.exposure.asset_limit",
        parameters={
            "asset_id": asset_id,
            "exposure_amount": exposure_amount,
            "exposure_limit": exposure_limit
        },
        status=status,
        details=details,
        subject={"asset_id": asset_id}
    )
    
    return not exceeded

def assert_data_quality_probabilities_sum_to_one(
    market_id: str,
    probabilities: Dict[str, float],
    epsilon: float = 0.01,
    severity: Optional[AssertionSeverity] = None
) -> bool:
    """Assert that market probabilities sum to approximately 1."""
    total_prob = sum(probabilities.values())
    deviation = abs(total_prob - 1.0)
    violated = deviation > epsilon
    
    client = get_assertion_client()
    status = AssertionStatus.FAILED if violated else AssertionStatus.PASSED
    details = f"Probability sum {total_prob:.6f} deviates from 1.0 by {deviation:.6f}" if violated else None
    
    client.record(
        template_id="data_quality.probabilities.sum_to_one",
        parameters={
            "market_id": market_id,
            "probabilities": probabilities,
            "total_prob": total_prob,
            "epsilon": epsilon,
            "deviation": deviation
        },
        status=status,
        details=details,
        subject={"market_id": market_id}
    )
    
    return not violated

# Integration with existing MERID components
def integrate_with_reality_auditor():
    """Integrate assertion framework with existing Reality Auditor."""
    from core.reality_auditor import get_reality_auditor
    
    auditor = get_reality_auditor()
    
    # Register assertion templates as reality assertions
    templates_to_register = [
        {
            "domain": "reality",
            "description": "Forecasts must have outcomes within allowed lag",
            "confidence": 0.9,
            "provenance_score": 0.8,
            "regime_compatibility": 0.8,
            "decay_rate": 0.01,
            "validity_window": 24 * 3600,  # 24 hours
            "sources": [{"source_id": "assertion_framework", "module_id": "reality", "weight": 1.0}]
        },
        {
            "domain": "risk",
            "description": "Risk limits must be enforced for all positions",
            "confidence": 0.95,
            "provenance_score": 0.9,
            "regime_compatibility": 0.9,
            "decay_rate": 0.005,
            "validity_window": 12 * 3600,  # 12 hours
            "sources": [{"source_id": "assertion_framework", "module_id": "risk", "weight": 1.0}]
        }
    ]
    
    for template in templates_to_register:
        try:
            assertion_id = auditor.registry.register_assertion(**template)
            logger.info(f"Registered assertion template with reality auditor: {assertion_id}")
        except Exception as e:
            logger.error(f"Failed to register template with reality auditor: {e}")

def integrate_with_prediction_agents():
    """Integrate assertion framework with prediction agents."""
    # This would be called by prediction agents to register assertions
    # about their forecasts and expected resolutions
    
    def forecast_wrapper(original_forecast_func):
        """Wrap forecast functions to register assertions."""
        @wraps(original_forecast_func)
        def wrapper(*args, **kwargs):
            # Extract market info from args/kwargs
            market_id = kwargs.get("market_id") or (args[0] if args else "unknown")
            
            # Register assertion about expected resolution
            assertion_id = assert_forecast_must_resolve(
                market_id=market_id,
                forecast_time=time.time(),
                max_resolution_lag_hours=72,  # 3 days default
                resolution_source="prediction_market"
            )
            
            # Call original forecast function
            result = original_forecast_func(*args, **kwargs)
            
            # Add assertion ID to result for tracking
            if isinstance(result, dict):
                result["assertion_id"] = assertion_id
            
            return result
        return wrapper
    
    return forecast_wrapper

# CI/CD Integration Helpers
def ci_assertion_decorator(
    stage: str,
    pipeline_id: str,
    severity: Optional[AssertionSeverity] = None
):
    """Decorator for CI/CD pipeline assertions."""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.time()
            client = get_assertion_client()
            
            subject = {
                "pipeline_id": pipeline_id,
                "stage": stage,
                "function": func.__name__
            }
            
            try:
                result = func(*args, **kwargs)
                
                duration_ms = (time.time() - start_time) * 1000
                client.record(
                    template_id="ci.stage.execution_success",
                    parameters={
                        "stage": stage,
                        "duration_ms": duration_ms,
                        "pipeline_id": pipeline_id
                    },
                    status=AssertionStatus.PASSED,
                    subject=subject
                )
                
                return result
                
            except Exception as e:
                duration_ms = (time.time() - start_time) * 1000
                error_details = f"{type(e).__name__}: {str(e)}"
                
                client.record(
                    template_id="ci.stage.execution_failure",
                    parameters={
                        "stage": stage,
                        "duration_ms": duration_ms,
                        "pipeline_id": pipeline_id,
                        "error": error_details
                    },
                    status=AssertionStatus.FAILED,
                    details=error_details,
                    subject=subject
                )
                
                raise
                
        return wrapper
    return decorator

# Usage Examples and Documentation
EXAMPLES = """
# Python Usage Examples:

# 1. Basic null checking
@null_check("brier_score", "pipeline_metrics")
def calculate_brier_score(predictions, outcomes):
    # Your calculation logic
    return score

# 2. Timeout checking
@timeout_check(max_duration_ms=5000, context="api_call")
def fetch_market_data(market_id):
    # Your API call logic
    return data

# 3. Resource monitoring
@resource_monitor("job_name", max_cpu_pct=200, max_memory_mb=1024)
def intensive_calculation():
    # Your calculation logic
    pass

# 4. Custom assertion template
@assertion_template("custom.business_rule", severity=AssertionSeverity.MAJOR)
def business_logic_function():
    # Your business logic
    return result

# 5. MERID-specific assertions
assert_forecast_must_resolve("market_123", time.time(), 72, "polymarket")
assert_risk_limits("BTC", 50000, 100000)
assert_data_quality_probabilities_sum_to_one("market_456", {"yes": 0.65, "no": 0.34})

# 6. CI/CD integration
@ci_assertion_decorator("unit_tests", pipeline_id="build-123")
def run_unit_tests():
    # Your test logic
    pass
"""

# Initialize integrations when module is imported
try:
    integrate_with_reality_auditor()
    logger.info("Assertion framework integrated with Reality Auditor")
except Exception as e:
    logger.warning(f"Failed to integrate with Reality Auditor: {e}")
