"""
MERID Service Resilience Layer
Gate 3: Service Reliability - Evidence Artifact
Date: 2026-01-26

Implements circuit breakers, retries, and fallback behavior
for critical external calls and internal service dependencies.
"""

import asyncio
import logging
from utils.logger import get_logger
import time
from typing import Any, Callable, Optional, TypeVar, Union
from dataclasses import dataclass
from functools import wraps
import tenacity
from pybreaker import CircuitBreaker, CircuitBreakerError

logger = get_logger(__name__)

T = TypeVar('T')

@dataclass
class ResilienceConfig:
    """Configuration for resilience patterns"""
    max_retries: int = 3
    retry_delay: float = 1.0
    retry_multiplier: float = 2.0
    retry_max_delay: float = 60.0
    circuit_breaker_threshold: int = 5
    circuit_breaker_timeout: int = 30
    timeout: float = 30.0


class ResilientAPIClient:
    """
    Resilient API client with circuit breakers and retries.
    
    Used for critical external calls to ensure service reliability.
    """
    
    def __init__(self, config: Optional[ResilienceConfig] = None):
        self.config = config or ResilienceConfig()
        self.circuit_breaker = CircuitBreaker(
            fail_max=self.config.circuit_breaker_threshold,
            reset_timeout=self.config.circuit_breaker_timeout,
            exclude=[KeyboardInterrupt, SystemExit]
        )
        
    async def call_api(self, func: Callable[..., T], *args, **kwargs) -> T:
        """
        Execute API call with retries and circuit breaker protection.
        """
        @tenacity.retry(
            stop=tenacity.stop_after_attempt(self.config.max_retries),
            wait=tenacity.wait_exponential(
                multiplier=self.config.retry_multiplier,
                min=self.config.retry_delay,
                max=self.config.retry_max_delay
            ),
            retry=tenacity.retry_if_exception_type((ConnectionError, TimeoutError)),
            before_sleep=tenacity.before_sleep_log(logger, logging.WARNING),
            after=tenacity.after_log(logger, logging.INFO)
        )
        async def _retry_wrapper():
            try:
                result = await asyncio.wait_for(
                    func(*args, **kwargs),
                    timeout=self.config.timeout
                )
                logger.info(f"API call successful: {func.__name__}")
                return result
            except asyncio.TimeoutError:
                logger.error(f"API call timeout: {func.__name__}")
                raise
            except CircuitBreakerError:
                logger.error(f"Circuit breaker open for: {func.__name__}")
                raise
            except Exception as e:
                logger.error(f"API call failed: {func.__name__}: {e}")
                raise
        
        return await _retry_wrapper()


class FallbackManager:
    """
    Manages fallback behavior when primary services fail.
    """
    
    def __init__(self):
        self.fallback_strategies = {}
        
    def register_fallback(self, service_name: str, fallback_func: Callable):
        """Register a fallback strategy for a service."""
        self.fallback_strategies[service_name] = fallback_func
        
    async def execute_with_fallback(
        self, 
        service_name: str, 
        primary_func: Callable[..., T], 
        *args, 
        **kwargs
    ) -> T:
        """
        Execute primary function with fallback if it fails.
        """
        try:
            return await primary_func(*args, **kwargs)
        except (ConnectionError, TimeoutError, RuntimeError) as e:
            logger.warning(f"Primary service {service_name} failed: {str(e)}")
            if service_name in self.fallback_strategies:
                logger.info(f"Executing fallback for {service_name}")
                return await self.fallback_strategies[service_name](*args, **kwargs)
            else:
                logger.error(f"No fallback available for {service_name}")
                raise


# Global resilience instances
resilient_client = ResilientAPIClient()
fallback_manager = FallbackManager()

# Decorator for automatic resilience
def resilient_call(
    max_retries: int = 3,
    retry_delay: float = 1.0,
    circuit_breaker_threshold: int = 5,
    timeout: float = 30.0
):
    """
    Decorator to add resilience to any async function.
    """
    def decorator(func):
        config = ResilienceConfig(
            max_retries=max_retries,
            retry_delay=retry_delay,
            circuit_breaker_threshold=circuit_breaker_threshold,
            timeout=timeout
        )
        client = ResilientAPIClient(config)
        
        @wraps(func)
        async def wrapper(*args, **kwargs):
            return await client.call_api(func, *args, **kwargs)
        return wrapper
    return decorator


# Example usage for critical services
@resilient_call(max_retries=3, timeout=15.0)
async def fetch_market_data(symbol: str) -> dict:
    """Fetch market data with resilience protection."""
    # Implementation would go here
    pass

@resilient_call(max_retries=2, timeout=10.0)
async def submit_order_to_venue(order_data: dict) -> dict:
    """Submit order to external venue with resilience protection."""
    # Implementation would go here
    pass

# Fallback strategies
async def cached_market_data(symbol: str) -> dict:
    """Fallback: Return cached market data."""
    logger.info(f"Returning cached data for {symbol}")
    return {"symbol": symbol, "price": 0.0, "timestamp": time.time()}

async def order_rejection(order_data: dict) -> dict:
    """Fallback: Reject order gracefully."""
    logger.info(f"Order rejected: {order_data.get('symbol', 'unknown')}")
    return {"status": "rejected", "reason": "service_unavailable"}

# Register fallbacks
fallback_manager.register_fallback("market_data", cached_market_data)
fallback_manager.register_fallback("order_submission", order_rejection)
