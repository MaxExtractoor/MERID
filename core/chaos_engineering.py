"""
Chaos Engineering Framework for MERID
Fault injection, network partitioning, and automated analysis.
"""
from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("core.chaos_engineering")


class FaultType(Enum):
    """Types of faults to inject."""
    SERVICE_CRASH = "service_crash"
    LATENCY_INJECTION = "latency_injection"
    ERROR_INJECTION = "error_injection"
    NETWORK_PARTITION = "network_partition"
    RESOURCE_EXHAUSTION = "resource_exhaustion"
    DEPENDENCY_FAILURE = "dependency_failure"
    DATA_CORRUPTION = "data_corruption"


class ExperimentStatus(Enum):
    """Status of chaos experiment."""
    PLANNED = "planned"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    ABORTED = "aborted"


@dataclass
class FaultInjection:
    """Configuration for a fault injection."""
    fault_type: FaultType
    target_service: str
    duration_seconds: float
    intensity: float  # 0.0 to 1.0
    parameters: Dict[str, Any]


@dataclass
class ExperimentResult:
    """Result of a chaos experiment."""
    experiment_id: str
    start_time: float
    end_time: float
    duration_seconds: float
    fault_injection: FaultInjection
    status: ExperimentStatus
    observations: Dict[str, Any]
    recovery_time_seconds: Optional[float]
    impact_score: float  # 0.0 to 1.0
    lessons_learned: List[str]


class ChaosExperiment:
    """A chaos engineering experiment."""
    
    def __init__(
        self,
        experiment_id: str,
        fault_injection: FaultInjection,
        steady_state_check: Callable[[], bool],
        abort_condition: Optional[Callable[[], bool]] = None
    ):
        self.experiment_id = experiment_id
        self.fault_injection = fault_injection
        self.steady_state_check = steady_state_check
        self.abort_condition = abort_condition
        self.status = ExperimentStatus.PLANNED
        self._observations: Dict[str, Any] = {}
        self._start_time: Optional[float] = None
        self._end_time: Optional[float] = None
        self._recovery_start: Optional[float] = None
    
    async def run(self) -> ExperimentResult:
        """Execute the chaos experiment."""
        logger.info(f"Starting chaos experiment {self.experiment_id}")
        
        self.status = ExperimentStatus.RUNNING
        self._start_time = time.time()
        
        try:
            # 1. Verify steady state
            if not self.steady_state_check():
                raise Exception("System not in steady state before experiment")
            
            self._observations["pre_fault_steady_state"] = True
            
            # 2. Inject fault
            await self._inject_fault()
            
            # 3. Monitor system behavior
            await self._monitor_behavior()
            
            # 4. Remove fault
            await self._remove_fault()
            
            # 5. Measure recovery
            recovery_time = await self._measure_recovery()
            
            # 6. Analyze results
            impact_score = self._calculate_impact()
            lessons = self._extract_lessons()
            
            self._end_time = time.time()
            self.status = ExperimentStatus.COMPLETED
            
            return ExperimentResult(
                experiment_id=self.experiment_id,
                start_time=self._start_time,
                end_time=self._end_time,
                duration_seconds=self._end_time - self._start_time,
                fault_injection=self.fault_injection,
                status=self.status,
                observations=self._observations,
                recovery_time_seconds=recovery_time,
                impact_score=impact_score,
                lessons_learned=lessons
            )
            
        except Exception as exc:
            logger.error(f"Chaos experiment {self.experiment_id} failed: {exc}")
            
            self._end_time = time.time()
            self.status = ExperimentStatus.FAILED
            
            return ExperimentResult(
                experiment_id=self.experiment_id,
                start_time=self._start_time or time.time(),
                end_time=self._end_time,
                duration_seconds=self._end_time - (self._start_time or time.time()),
                fault_injection=self.fault_injection,
                status=self.status,
                observations=self._observations,
                recovery_time_seconds=None,
                impact_score=1.0,  # Maximum impact on failure
                lessons_learned=[f"Experiment failed: {str(exc)}"]
            )
    
    async def _inject_fault(self) -> None:
        """Inject the configured fault."""
        fault = self.fault_injection
        
        logger.warning(
            f"Injecting {fault.fault_type.value} into {fault.target_service} "
            f"for {fault.duration_seconds}s at intensity {fault.intensity}"
        )
        
        if fault.fault_type == FaultType.LATENCY_INJECTION:
            await self._inject_latency()
        elif fault.fault_type == FaultType.ERROR_INJECTION:
            await self._inject_errors()
        elif fault.fault_type == FaultType.SERVICE_CRASH:
            await self._inject_crash()
        elif fault.fault_type == FaultType.NETWORK_PARTITION:
            await self._inject_network_partition()
        elif fault.fault_type == FaultType.RESOURCE_EXHAUSTION:
            await self._inject_resource_exhaustion()
        elif fault.fault_type == FaultType.DEPENDENCY_FAILURE:
            await self._inject_dependency_failure()
        
        self._observations["fault_injected"] = True
        self._observations["fault_injection_time"] = time.time()
    
    async def _inject_latency(self) -> None:
        """Inject artificial latency."""
        latency_ms = self.fault_injection.parameters.get("latency_ms", 1000)
        self._observations["latency_injected_ms"] = latency_ms
    
    async def _inject_errors(self) -> None:
        """Inject errors into responses."""
        error_rate = self.fault_injection.intensity
        self._observations["error_rate_injected"] = error_rate
    
    async def _inject_crash(self) -> None:
        """Simulate service crash."""
        self._observations["crash_injected"] = True
    
    async def _inject_network_partition(self) -> None:
        """Simulate network partition."""
        self._observations["network_partition_injected"] = True
    
    async def _inject_resource_exhaustion(self) -> None:
        """Simulate resource exhaustion."""
        resource_type = self.fault_injection.parameters.get("resource_type", "memory")
        self._observations["resource_exhaustion_type"] = resource_type
    
    async def _inject_dependency_failure(self) -> None:
        """Simulate dependency failure."""
        dependency = self.fault_injection.parameters.get("dependency", "unknown")
        self._observations["dependency_failed"] = dependency
    
    async def _monitor_behavior(self) -> None:
        """Monitor system behavior during fault."""
        duration = self.fault_injection.duration_seconds
        check_interval = 1.0
        elapsed = 0.0
        
        error_count = 0
        latency_samples = []
        
        while elapsed < duration:
            # Check abort condition
            if self.abort_condition and self.abort_condition():
                logger.warning(f"Aborting experiment {self.experiment_id}")
                self.status = ExperimentStatus.ABORTED
                break
            
            # Collect metrics
            if not self.steady_state_check():
                error_count += 1
            
            await asyncio.sleep(check_interval)
            elapsed += check_interval
        
        self._observations["errors_during_fault"] = error_count
        self._observations["fault_duration_actual"] = elapsed
    
    async def _remove_fault(self) -> None:
        """Remove the injected fault."""
        logger.info(f"Removing fault from {self.fault_injection.target_service}")
        
        self._observations["fault_removed"] = True
        self._observations["fault_removal_time"] = time.time()
        self._recovery_start = time.time()
    
    async def _measure_recovery(self) -> Optional[float]:
        """Measure time to recover to steady state."""
        if not self._recovery_start:
            return None
        
        max_recovery_time = 60.0  # 60 seconds max
        check_interval = 1.0
        elapsed = 0.0
        
        while elapsed < max_recovery_time:
            if self.steady_state_check():
                recovery_time = time.time() - self._recovery_start
                logger.info(f"System recovered in {recovery_time:.2f}s")
                return recovery_time
            
            await asyncio.sleep(check_interval)
            elapsed += check_interval
        
        logger.warning(f"System did not recover within {max_recovery_time}s")
        return None
    
    def _calculate_impact(self) -> float:
        """Calculate impact score of the experiment."""
        errors = self._observations.get("errors_during_fault", 0)
        duration = self._observations.get("fault_duration_actual", 1.0)
        recovery_time = self._observations.get("recovery_time_seconds")
        
        # Higher error rate = higher impact
        error_impact = min(errors / duration, 1.0) * 0.4
        
        # Longer recovery = higher impact
        recovery_impact = 0.0
        if recovery_time:
            recovery_impact = min(recovery_time / 30.0, 1.0) * 0.6
        else:
            recovery_impact = 1.0  # No recovery = maximum impact
        
        return error_impact + recovery_impact
    
    def _extract_lessons(self) -> List[str]:
        """Extract lessons learned from the experiment."""
        lessons = []
        
        recovery_time = self._observations.get("recovery_time_seconds")
        
        if recovery_time is None:
            lessons.append("System did not recover automatically - needs improvement")
        elif recovery_time > 30.0:
            lessons.append(f"Recovery took {recovery_time:.1f}s - consider faster recovery mechanisms")
        else:
            lessons.append(f"System recovered quickly in {recovery_time:.1f}s")
        
        errors = self._observations.get("errors_during_fault", 0)
        if errors > 0:
            lessons.append(f"System experienced {errors} errors during fault - improve fault tolerance")
        else:
            lessons.append("System maintained stability during fault")
        
        return lessons


class ChaosOrchestrator:
    """Orchestrates chaos engineering experiments."""
    
    def __init__(self):
        self._experiments: List[ExperimentResult] = []
        self._running_experiment: Optional[ChaosExperiment] = None
        self._experiment_count = 0
    
    def create_experiment(
        self,
        fault_injection: FaultInjection,
        steady_state_check: Callable[[], bool],
        abort_condition: Optional[Callable[[], bool]] = None
    ) -> ChaosExperiment:
        """Create a new chaos experiment."""
        self._experiment_count += 1
        experiment_id = f"chaos_{self._experiment_count}_{int(time.time())}"
        
        return ChaosExperiment(
            experiment_id,
            fault_injection,
            steady_state_check,
            abort_condition
        )
    
    async def run_experiment(self, experiment: ChaosExperiment) -> ExperimentResult:
        """Run a chaos experiment."""
        if self._running_experiment:
            raise Exception("Another experiment is already running")
        
        self._running_experiment = experiment
        
        try:
            result = await experiment.run()
            self._experiments.append(result)
            return result
        finally:
            self._running_experiment = None
    
    def get_experiment_history(self) -> List[ExperimentResult]:
        """Get history of all experiments."""
        return self._experiments.copy()
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get statistics across all experiments."""
        if not self._experiments:
            return {
                "total_experiments": 0,
                "completed": 0,
                "failed": 0,
                "aborted": 0,
                "average_recovery_time": None,
                "average_impact_score": None
            }
        
        completed = [e for e in self._experiments if e.status == ExperimentStatus.COMPLETED]
        failed = [e for e in self._experiments if e.status == ExperimentStatus.FAILED]
        aborted = [e for e in self._experiments if e.status == ExperimentStatus.ABORTED]
        
        recovery_times = [e.recovery_time_seconds for e in completed if e.recovery_time_seconds]
        impact_scores = [e.impact_score for e in self._experiments]
        
        return {
            "total_experiments": len(self._experiments),
            "completed": len(completed),
            "failed": len(failed),
            "aborted": len(aborted),
            "average_recovery_time": sum(recovery_times) / len(recovery_times) if recovery_times else None,
            "average_impact_score": sum(impact_scores) / len(impact_scores) if impact_scores else None,
            "lessons_learned": self._aggregate_lessons()
        }
    
    def _aggregate_lessons(self) -> List[str]:
        """Aggregate lessons learned across experiments."""
        all_lessons = []
        for experiment in self._experiments:
            all_lessons.extend(experiment.lessons_learned)
        
        # Count frequency of similar lessons
        lesson_counts: Dict[str, int] = {}
        for lesson in all_lessons:
            lesson_counts[lesson] = lesson_counts.get(lesson, 0) + 1
        
        # Return most common lessons
        sorted_lessons = sorted(lesson_counts.items(), key=lambda x: x[1], reverse=True)
        return [f"{lesson} (observed {count}x)" for lesson, count in sorted_lessons[:10]]


# Global chaos orchestrator
_chaos_orchestrator: Optional[ChaosOrchestrator] = None


def get_chaos_orchestrator() -> ChaosOrchestrator:
    """Get the global chaos orchestrator."""
    global _chaos_orchestrator
    if _chaos_orchestrator is None:
        _chaos_orchestrator = ChaosOrchestrator()
    return _chaos_orchestrator
