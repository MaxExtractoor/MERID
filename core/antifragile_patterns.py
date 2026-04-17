"""
Antifragile Patterns for MERID
Canary releases, staged rollouts, adaptive retry, and resilience patterns.
"""
from __future__ import annotations

import asyncio
import threading
import random
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("core.antifragile_patterns")


class RolloutStage(Enum):
    """Stages of a rollout."""
    CANARY = "canary"
    STAGED_10 = "staged_10"
    STAGED_25 = "staged_25"
    STAGED_50 = "staged_50"
    STAGED_75 = "staged_75"
    FULL = "full"


class RolloutStatus(Enum):
    """Status of a rollout."""
    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    PAUSED = "paused"
    COMPLETED = "completed"
    ROLLED_BACK = "rolled_back"
    FAILED = "failed"


@dataclass
class RolloutConfig:
    """Configuration for a staged rollout."""
    service_name: str
    version: str
    canary_percentage: float = 5.0
    stage_percentages: List[float] = None
    stage_duration_seconds: float = 300.0
    success_threshold: float = 0.95
    error_rate_threshold: float = 0.05
    latency_threshold_ms: float = 1000.0
    auto_rollback: bool = True
    
    def __post_init__(self):
        if self.stage_percentages is None:
            self.stage_percentages = [10.0, 25.0, 50.0, 75.0, 100.0]


@dataclass
class RolloutMetrics:
    """Metrics for a rollout stage."""
    stage: RolloutStage
    percentage: float
    request_count: int
    success_count: int
    error_count: int
    average_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    timestamp: float


class CanaryRelease:
    """Manages canary releases with automatic rollback."""
    
    def __init__(self, config: RolloutConfig):
        self.config = config
        self.status = RolloutStatus.PLANNED
        self.current_stage = RolloutStage.CANARY
        self.current_percentage = config.canary_percentage
        self._metrics: List[RolloutMetrics] = []
        self._start_time: Optional[float] = None
    
    async def execute(self) -> bool:
        """Execute the canary release."""
        logger.info(f"Starting canary release for {self.config.service_name} v{self.config.version}")
        
        self.status = RolloutStatus.IN_PROGRESS
        self._start_time = time.time()
        
        try:
            # Stage 1: Canary (5%)
            if not await self._run_stage(RolloutStage.CANARY, self.config.canary_percentage):
                await self._rollback("Canary stage failed")
                return False
            
            # Stage 2-N: Progressive rollout
            for i, percentage in enumerate(self.config.stage_percentages):
                stage = RolloutStage(f"staged_{int(percentage)}")
                if not await self._run_stage(stage, percentage):
                    await self._rollback(f"Stage {percentage}% failed")
                    return False
            
            # Success
            self.status = RolloutStatus.COMPLETED
            logger.info(f"Canary release completed successfully for {self.config.service_name}")
            return True
            
        except Exception as exc:
            logger.error(f"Canary release failed: {exc}")
            await self._rollback(f"Exception: {exc}")
            return False
    
    async def _run_stage(self, stage: RolloutStage, percentage: float) -> bool:
        """Run a single rollout stage."""
        logger.info(f"Running stage {stage.value} at {percentage}%")
        
        self.current_stage = stage
        self.current_percentage = percentage
        
        # Simulate traffic routing to new version
        await asyncio.sleep(self.config.stage_duration_seconds)
        
        # Collect metrics
        metrics = await self._collect_metrics(stage, percentage)
        self._metrics.append(metrics)
        
        # Evaluate success
        success = self._evaluate_stage(metrics)
        
        if not success:
            logger.warning(f"Stage {stage.value} failed health checks")
        
        return success
    
    async def _collect_metrics(self, stage: RolloutStage, percentage: float) -> RolloutMetrics:
        """Collect metrics for the current stage.
        
        Returns zero counts and latencies until real metrics collection is wired.
        """
        return RolloutMetrics(
            stage=stage,
            percentage=percentage,
            request_count=0,
            success_count=0,
            error_count=0,
            average_latency_ms=0.0,
            p95_latency_ms=0.0,
            p99_latency_ms=0.0,
            timestamp=time.time()
        )
    
    def _evaluate_stage(self, metrics: RolloutMetrics) -> bool:
        """Evaluate if a stage passed health checks."""
        if metrics.request_count == 0:
            return True
        
        success_rate = metrics.success_count / metrics.request_count
        error_rate = metrics.error_count / metrics.request_count
        
        # Check success threshold
        if success_rate < self.config.success_threshold:
            logger.warning(f"Success rate {success_rate:.2%} below threshold {self.config.success_threshold:.2%}")
            return False
        
        # Check error rate threshold
        if error_rate > self.config.error_rate_threshold:
            logger.warning(f"Error rate {error_rate:.2%} above threshold {self.config.error_rate_threshold:.2%}")
            return False
        
        # Check latency threshold
        if metrics.p95_latency_ms > self.config.latency_threshold_ms:
            logger.warning(f"P95 latency {metrics.p95_latency_ms:.0f}ms above threshold {self.config.latency_threshold_ms:.0f}ms")
            return False
        
        return True
    
    async def _rollback(self, reason: str) -> None:
        """Rollback the release."""
        logger.error(f"Rolling back {self.config.service_name}: {reason}")
        
        self.status = RolloutStatus.ROLLED_BACK
        
        # In production, this would route all traffic back to old version
        await asyncio.sleep(1.0)
        
        logger.info(f"Rollback completed for {self.config.service_name}")
    
    def get_summary(self) -> Dict[str, Any]:
        """Get rollout summary."""
        return {
            "service_name": self.config.service_name,
            "version": self.config.version,
            "status": self.status.value,
            "current_stage": self.current_stage.value,
            "current_percentage": self.current_percentage,
            "stages_completed": len(self._metrics),
            "total_requests": sum(m.request_count for m in self._metrics),
            "total_errors": sum(m.error_count for m in self._metrics),
            "average_success_rate": sum(m.success_count / m.request_count for m in self._metrics if m.request_count > 0) / len(self._metrics) if self._metrics else 0,
            "duration_seconds": time.time() - self._start_time if self._start_time else 0
        }


class AdaptiveRetry:
    """Adaptive retry with exponential backoff tuned from production incidents."""
    
    def __init__(
        self,
        operation_name: str,
        base_delay_seconds: float = 1.0,
        max_delay_seconds: float = 60.0,
        max_attempts: int = 5,
        jitter: bool = True
    ):
        self.operation_name = operation_name
        self.base_delay = base_delay_seconds
        self.max_delay = max_delay_seconds
        self.max_attempts = max_attempts
        self.jitter = jitter
        
        # Learning from incidents
        self._success_history: List[int] = []  # Attempt number that succeeded
        self._failure_patterns: Dict[str, int] = {}
    
    async def execute(
        self,
        operation: Callable[[], Any],
        is_retryable: Optional[Callable[[Exception], bool]] = None
    ) -> Any:
        """Execute operation with adaptive retry."""
        last_exception = None
        
        for attempt in range(1, self.max_attempts + 1):
            try:
                result = await operation()
                
                # Record success
                self._success_history.append(attempt)
                
                # Learn: if we succeeded on retry, adjust base delay
                if attempt > 1:
                    self._adjust_delays()
                
                return result
                
            except Exception as exc:
                last_exception = exc
                
                # Check if retryable
                if is_retryable and not is_retryable(exc):
                    logger.warning(f"{self.operation_name} failed with non-retryable error: {exc}")
                    raise
                
                # Record failure pattern
                error_type = type(exc).__name__
                self._failure_patterns[error_type] = self._failure_patterns.get(error_type, 0) + 1
                
                # Last attempt
                if attempt >= self.max_attempts:
                    logger.error(f"{self.operation_name} failed after {self.max_attempts} attempts")
                    raise
                
                # Calculate delay
                delay = self._calculate_delay(attempt)
                
                logger.warning(
                    f"{self.operation_name} attempt {attempt}/{self.max_attempts} failed: {exc}. "
                    f"Retrying in {delay:.2f}s"
                )
                
                await asyncio.sleep(delay)
        
        raise last_exception
    
    def _calculate_delay(self, attempt: int) -> float:
        """Calculate delay with exponential backoff and jitter."""
        # Exponential backoff
        delay = min(self.base_delay * (2 ** (attempt - 1)), self.max_delay)
        
        # Add jitter to prevent thundering herd
        if self.jitter:
            delay = delay * (0.5 + random.random() * 0.5)
        
        return delay
    
    def _adjust_delays(self) -> None:
        """Adjust delays based on success history."""
        if len(self._success_history) < 10:
            return
        
        # If most successes happen on first retry, reduce base delay
        recent_successes = self._success_history[-10:]
        avg_attempt = sum(recent_successes) / len(recent_successes)
        
        if avg_attempt < 2.0:
            self.base_delay = max(0.5, self.base_delay * 0.9)
            logger.info(f"Reduced base delay to {self.base_delay:.2f}s for {self.operation_name}")
        elif avg_attempt > 3.0:
            self.base_delay = min(5.0, self.base_delay * 1.1)
            logger.info(f"Increased base delay to {self.base_delay:.2f}s for {self.operation_name}")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get retry statistics."""
        if not self._success_history:
            return {
                "operation_name": self.operation_name,
                "total_operations": 0,
                "average_attempts": 0,
                "failure_patterns": {}
            }
        
        return {
            "operation_name": self.operation_name,
            "total_operations": len(self._success_history),
            "average_attempts": sum(self._success_history) / len(self._success_history),
            "current_base_delay": self.base_delay,
            "failure_patterns": self._failure_patterns
        }


class Bulkhead:
    """Bulkhead pattern for resource isolation."""
    
    def __init__(
        self,
        name: str,
        max_concurrent: int,
        queue_size: int = 0,
        timeout_seconds: float = 30.0
    ):
        self.name = name
        self.max_concurrent = max_concurrent
        self.queue_size = queue_size
        self.timeout_seconds = timeout_seconds
        
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=queue_size)
        self._active_count = 0
        self._total_executions = 0
        self._total_rejections = 0
        self._total_timeouts = 0
    
    async def execute(self, operation: Callable[[], Any]) -> Any:
        """Execute operation within bulkhead."""
        self._total_executions += 1
        
        try:
            async with asyncio.timeout(self.timeout_seconds):
                async with self._semaphore:
                    self._active_count += 1
                    try:
                        return await operation()
                    finally:
                        self._active_count -= 1
        
        except asyncio.TimeoutError:
            self._total_timeouts += 1
            logger.warning(f"Bulkhead {self.name} operation timed out after {self.timeout_seconds}s")
            raise
        
        except Exception as exc:
            self._total_rejections += 1
            logger.error(f"Bulkhead {self.name} operation failed: {exc}")
            raise
    
    def get_stats(self) -> Dict[str, Any]:
        """Get bulkhead statistics."""
        return {
            "name": self.name,
            "max_concurrent": self.max_concurrent,
            "active_count": self._active_count,
            "total_executions": self._total_executions,
            "total_rejections": self._total_rejections,
            "total_timeouts": self._total_timeouts,
            "rejection_rate": self._total_rejections / self._total_executions if self._total_executions > 0 else 0
        }


class AntifragileOrchestrator:
    """Orchestrates antifragile patterns."""
    
    def __init__(self):
        self._canary_releases: Dict[str, CanaryRelease] = {}
        self._adaptive_retries: Dict[str, AdaptiveRetry] = {}
        self._bulkheads: Dict[str, Bulkhead] = {}
    
    def create_canary_release(self, config: RolloutConfig) -> CanaryRelease:
        """Create a canary release."""
        canary = CanaryRelease(config)
        self._canary_releases[config.service_name] = canary
        return canary
    
    def get_adaptive_retry(self, operation_name: str) -> AdaptiveRetry:
        """Get or create adaptive retry for operation."""
        if operation_name not in self._adaptive_retries:
            self._adaptive_retries[operation_name] = AdaptiveRetry(operation_name)
        return self._adaptive_retries[operation_name]
    
    def get_bulkhead(self, name: str, max_concurrent: int = 10) -> Bulkhead:
        """Get or create bulkhead."""
        if name not in self._bulkheads:
            self._bulkheads[name] = Bulkhead(name, max_concurrent)
        return self._bulkheads[name]
    
    def get_all_stats(self) -> Dict[str, Any]:
        """Get statistics for all patterns."""
        return {
            "canary_releases": {
                name: canary.get_summary()
                for name, canary in self._canary_releases.items()
            },
            "adaptive_retries": {
                name: retry.get_stats()
                for name, retry in self._adaptive_retries.items()
            },
            "bulkheads": {
                name: bulkhead.get_stats()
                for name, bulkhead in self._bulkheads.items()
            }
        }


# Global orchestrator
_antifragile_orchestrator: Optional[AntifragileOrchestrator] = None
_antifragile_orchestrator_lock = threading.Lock()


def get_antifragile_orchestrator() -> AntifragileOrchestrator:
    """Get the global antifragile orchestrator."""
    global _antifragile_orchestrator
    if _antifragile_orchestrator is None:
        with _antifragile_orchestrator_lock:
            if _antifragile_orchestrator is None:
                _antifragile_orchestrator = AntifragileOrchestrator()
    return _antifragile_orchestrator
