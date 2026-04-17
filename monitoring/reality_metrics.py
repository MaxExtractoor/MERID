"""
Prometheus Metrics for Domain Priority System and SIGHTED_DEGRADED Mode.

Exposes metrics for monitoring degraded sighted behavior, assertion health,
priority violations, and mode transitions.
"""

from prometheus_client import Counter, Histogram, Gauge, Info
from typing import Dict, Any
import time

# Registry metrics
reality_valid_assertions = Gauge(
    'reality_valid_assertions',
    'Number of currently valid assertions by domain',
    ['domain']
)

reality_assertion_failures_total = Counter(
    'reality_assertion_failures_total',
    'Total assertion failures by domain and reason',
    ['domain', 'reason']
)

reality_priority_violations_total = Counter(
    'reality_priority_violations_total',
    'Total priority violations by domain',
    ['domain', 'operation']
)

# Mode and transition metrics
reality_mode = Gauge(
    'reality_mode',
    'Current system mode (0=BLIND, 1=SIGHTED_DEGRADED, 2=OPERATIONAL)'
)

reality_mode_transitions_total = Counter(
    'reality_mode_transitions_total',
    'Total mode transitions',
    ['from_mode', 'to_mode']
)

reality_mode_rollbacks_total = Counter(
    'reality_mode_rollbacks_total',
    'Total automatic rollbacks',
    ['reason']
)

# Latency metrics
reality_assertion_eval_latency_ms = Histogram(
    'reality_assertion_eval_latency_ms',
    'Assertion evaluation latency in milliseconds',
    buckets=[1, 5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000]
)

reality_priority_decision_latency_ms = Histogram(
    'reality_priority_decision_latency_ms',
    'Priority decision latency in milliseconds',
    buckets=[0.1, 0.5, 1, 2, 5, 10, 25, 50, 100]
)

# System health metrics
reality_domain_health = Gauge(
    'reality_domain_health',
    'Domain health score (0-100)',
    ['domain']
)

reality_system_health = Gauge(
    'reality_system_health',
    'Overall system health score (0-100)'
)

# Safety check metrics
reality_safety_checks_passed = Gauge(
    'reality_safety_checks_passed',
    'Number of safety checks currently passing',
    ['check_name']
)

reality_safety_check_failures_total = Counter(
    'reality_safety_check_failures_total',
    'Total safety check failures',
    ['check_name', 'reason']
)

# Query rate metrics
reality_domain_query_rate = Gauge(
    'reality_domain_query_rate',
    'Current query rate per minute by domain',
    ['domain']
)

# Build info
reality_build_info = Info(
    'reality_build_info',
    'Reality layer build information'
)


class RealityMetricsCollector:
    """Collects and updates reality system metrics."""
    
    def __init__(self):
        self.last_mode = None
        self.last_domain_counts = {}
        self.last_violation_counts = {}
    
    def update_mode_metrics(self, current_mode: str, old_mode: str = None):
        """Update mode-related metrics."""
        mode_mapping = {
            "BLIND": 0,
            "SIGHTED_DEGRADED": 1,
            "OPERATIONAL": 2,
            "DEGRADED": 3,
            "EMERGENCY": 4
        }
        
        mode_value = mode_mapping.get(current_mode, 0)
        reality_mode.set(mode_value)
        
        # Track mode transitions
        if old_mode and old_mode != current_mode:
            reality_mode_transitions_total.labels(
                from_mode=old_mode,
                to_mode=current_mode
            ).inc()
        
        # Track rollbacks
        if old_mode and old_mode == "SIGHTED_DEGRADED" and current_mode == "BLIND":
            reality_mode_rollbacks_total.labels(reason="safety_check_failure").inc()
        
        self.last_mode = current_mode
    
    def update_domain_assertion_metrics(self, domain_counts: Dict[str, Dict[str, int]]):
        """Update domain assertion metrics."""
        for domain, counts in domain_counts.items():
            # Update valid assertions gauge
            valid_count = counts.get("valid", 0)
            reality_valid_assertions.labels(domain=domain).set(valid_count)
            
            # Update failure counters
            total_count = counts.get("total", 0)
            failed_count = total_count - valid_count
            
            if failed_count > 0:
                # Calculate new failures since last update
                last_failed = self.last_domain_counts.get(domain, {}).get("failed", 0)
                new_failures = failed_count - last_failed
                
                if new_failures > 0:
                    reality_assertion_failures_total.labels(
                        domain=domain,
                        reason="invalid_or_expired"
                    ).inc(new_failures)
            
            # Update domain health score
            if total_count > 0:
                health_score = (valid_count / total_count) * 100
                reality_domain_health.labels(domain=domain).set(health_score)
        
        self.last_domain_counts = domain_counts
    
    def update_priority_violation_metrics(self, violation_counts: Dict[str, int]):
        """Update priority violation metrics."""
        for domain, count in violation_counts.items():
            # Calculate new violations since last update
            last_count = self.last_violation_counts.get(domain, 0)
            new_violations = count - last_count
            
            if new_violations > 0:
                # We don't have operation info here, so use "unknown"
                reality_priority_violations_total.labels(
                    domain=domain,
                    operation="unknown"
                ).inc(new_violations)
        
        self.last_violation_counts = violation_counts
    
    def update_query_rate_metrics(self, query_rates: Dict[str, float]):
        """Update query rate metrics."""
        for domain, rate in query_rates.items():
            reality_domain_query_rate.labels(domain=domain).set(rate)
    
    def update_safety_check_metrics(self, safety_results: Dict[str, bool]):
        """Update safety check metrics."""
        for check_name, passed in safety_results.items():
            reality_safety_checks_passed.labels(check_name=check_name).set(1 if passed else 0)
            
            if not passed:
                reality_safety_check_failures_total.labels(
                    check_name=check_name,
                    reason="check_failed"
                ).inc()
    
    def update_system_health(self, health_score: float):
        """Update overall system health."""
        reality_system_health.set(health_score)
    
    def record_assertion_eval_latency(self, duration_ms: float):
        """Record assertion evaluation latency."""
        reality_assertion_eval_latency_ms.observe(duration_ms)
    
    def record_priority_decision_latency(self, duration_ms: float):
        """Record priority decision latency."""
        reality_priority_decision_latency_ms.observe(duration_ms)
    
    def set_build_info(self, version: str, commit: str, build_time: str):
        """Set build information."""
        reality_build_info.info({
            'version': version,
            'commit': commit,
            'build_time': build_time
        })


# Global metrics collector instance
_metrics_collector = RealityMetricsCollector()


def get_metrics_collector() -> RealityMetricsCollector:
    """Get the global metrics collector."""
    return _metrics_collector


# Decorator for timing assertion evaluation
def time_assertion_eval(domain: str):
    """Decorator to time assertion evaluation."""
    def decorator(func):
        def wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                return result
            finally:
                duration_ms = (time.time() - start_time) * 1000
                get_metrics_collector().record_assertion_eval_latency(duration_ms)
        return wrapper
    return decorator


# Decorator for timing priority decisions
def time_priority_decision(domain: str, operation: str):
    """Decorator to time priority decisions."""
    def decorator(func):
        def wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                return result
            finally:
                duration_ms = (time.time() - start_time) * 1000
                get_metrics_collector().record_priority_decision_latency(duration_ms)
        return wrapper
    return decorator


# Alert condition helpers
class RealityAlertConditions:
    """Helper functions for common alert conditions."""
    
    @staticmethod
    def low_valid_assertions(domain: str, threshold: int = 3) -> bool:
        """Check if domain has too few valid assertions."""
        try:
            valid_count = reality_valid_assertions.labels(domain=domain)._value._value
            return valid_count < threshold
        except Exception:
            return True  # Assume worst case on error
    
    @staticmethod
    def high_violation_rate(domain: str, threshold: int = 10) -> bool:
        """Check if domain has too many violations."""
        try:
            # This would need to be tracked separately
            return False  # Placeholder
        except Exception:
            return True  # Assume worst case on error
    
    @staticmethod
    def mode_unstable() -> bool:
        """Check if mode has been unstable."""
        try:
            # This would need to track recent transitions
            return False  # Placeholder
        except Exception:
            return True  # Assume worst case on error
    
    @staticmethod
    def system_unhealthy(threshold: float = 70.0) -> bool:
        """Check if overall system health is low."""
        try:
            health_score = reality_system_health._value._value
            return health_score < threshold
        except Exception:
            return True  # Assume worst case on error


if __name__ == "__main__":
    # Example usage
    collector = get_metrics_collector()
    
    # Update some metrics
    collector.update_mode_metrics("SIGHTED_DEGRADED", "BLIND")
    collector.update_domain_assertion_metrics({
        "market": {"valid": 7, "total": 7, "failed": 0},
        "onchain": {"valid": 7, "total": 7, "failed": 0},
        "simulation": {"valid": 7, "total": 7, "failed": 0},
        "agent": {"valid": 7, "total": 7, "failed": 0}
    })
    collector.update_system_health(95.0)
    
    print("Metrics updated successfully")
