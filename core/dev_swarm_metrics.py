"""
Dev Swarm Prometheus Metrics

Exports metrics for monitoring and alerting.
"""

from typing import Dict, Any
from prometheus_client import Counter, Gauge, Histogram, Info
import structlog

logger = structlog.get_logger(__name__)

# Task metrics
tasks_created_total = Counter(
    'merid_dev_swarm_tasks_created_total',
    'Total number of tasks created',
    ['priority', 'effort']
)

tasks_completed_total = Counter(
    'merid_dev_swarm_tasks_completed_total',
    'Total number of tasks completed',
    ['status']
)

tasks_active = Gauge(
    'merid_dev_swarm_tasks_active',
    'Number of currently active tasks'
)

task_duration_seconds = Histogram(
    'merid_dev_swarm_task_duration_seconds',
    'Task execution duration in seconds',
    ['status'],
    buckets=[10, 30, 60, 120, 300, 600, 1200, 1800, 3600, 7200]
)

# Agent metrics
agents_registered = Gauge(
    'merid_dev_swarm_agents_registered',
    'Number of registered agents',
    ['role']
)

agent_phase_duration_seconds = Histogram(
    'merid_dev_swarm_agent_phase_duration_seconds',
    'Agent phase execution duration',
    ['agent_name', 'role'],
    buckets=[1, 5, 10, 30, 60, 120, 300, 600]
)

agent_phase_errors_total = Counter(
    'merid_dev_swarm_agent_phase_errors_total',
    'Total agent phase errors',
    ['agent_name', 'role', 'error_type']
)

# Cost metrics
daily_cost_usd = Gauge(
    'merid_dev_swarm_daily_cost_usd',
    'Daily cost in USD'
)

task_cost_usd = Histogram(
    'merid_dev_swarm_task_cost_usd',
    'Cost per task in USD',
    buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 25.0, 50.0]
)

# Queue depth metrics
task_history_length = Gauge(
    'merid_dev_swarm_task_history_length',
    'Total number of tasks in history (completed + failed + discarded)'
)

queue_depth = Gauge(
    'merid_dev_swarm_queue_depth',
    'Number of tasks waiting in queue (pending, not yet active)'
)

# System metrics
system_info = Info(
    'merid_dev_swarm_system',
    'Dev Swarm system information'
)

success_rate = Gauge(
    'merid_dev_swarm_success_rate',
    'Overall task success rate (0-1)'
)

storage_size_bytes = Gauge(
    'merid_dev_swarm_storage_size_bytes',
    'Storage size in bytes'
)


class DevSwarmMetrics:
    """Metrics collector for Dev Swarm."""
    
    def __init__(self):
        self.logger = logger.bind(component="DevSwarmMetrics")
        self._initialized = False
    
    def initialize(self, swarm):
        """Initialize metrics from swarm state."""
        try:
            # Set system info
            system_info.info({
                'version': '1.0.0',
                'persistence_enabled': str(swarm.persistence is not None),
                'max_concurrent_tasks': str(swarm.config.max_concurrent_tasks),
                'max_daily_cost': str(swarm.config.max_daily_cost_usd)
            })
            
            # Set agent counts
            for agent in swarm.agents:
                agents_registered.labels(role=agent.role.value).set(1)
            
            self._initialized = True
            self.logger.info("metrics_initialized")
            
        except Exception as e:
            self.logger.error("metrics_init_failed", error=str(e))
    
    def record_task_created(self, task):
        """Record task creation."""
        try:
            tasks_created_total.labels(
                priority=f"p{task.priority}",
                effort=task.estimated_effort
            ).inc()
        except Exception as e:
            self.logger.error("metric_record_failed", metric="task_created", error=str(e))
    
    def record_task_completed(self, task):
        """Record task completion."""
        try:
            # Completion counter
            tasks_completed_total.labels(status=task.status).inc()
            
            # Duration histogram
            if task.started_at and task.completed_at:
                duration = task.completed_at - task.started_at
                task_duration_seconds.labels(status=task.status).observe(duration)
            
            # Cost histogram
            if task.cost_usd > 0:
                task_cost_usd.observe(task.cost_usd)
                
        except Exception as e:
            self.logger.error("metric_record_failed", metric="task_completed", error=str(e))
    
    def update_active_tasks(self, count: int):
        """Update active tasks gauge."""
        try:
            tasks_active.set(count)
        except Exception as e:
            self.logger.error("metric_update_failed", metric="active_tasks", error=str(e))

    def update_task_history_length(self, count: int):
        """Update task history length gauge."""
        try:
            task_history_length.set(count)
        except Exception as e:
            self.logger.error("metric_update_failed", metric="task_history_length", error=str(e))

    def update_queue_depth(self, count: int):
        """Update queue depth gauge (pending tasks not yet active)."""
        try:
            queue_depth.set(count)
        except Exception as e:
            self.logger.error("metric_update_failed", metric="queue_depth", error=str(e))
    
    def update_daily_cost(self, cost: float):
        """Update daily cost gauge."""
        try:
            daily_cost_usd.set(cost)
        except Exception as e:
            self.logger.error("metric_update_failed", metric="daily_cost", error=str(e))
    
    def update_success_rate(self, rate: float):
        """Update success rate gauge."""
        try:
            success_rate.set(rate)
        except Exception as e:
            self.logger.error("metric_update_failed", metric="success_rate", error=str(e))
    
    def record_agent_phase(self, agent_name: str, role: str, duration: float, error: str = None):
        """Record agent phase execution."""
        try:
            agent_phase_duration_seconds.labels(
                agent_name=agent_name,
                role=role
            ).observe(duration)
            
            if error:
                agent_phase_errors_total.labels(
                    agent_name=agent_name,
                    role=role,
                    error_type=error[:50]  # Truncate error type
                ).inc()
                
        except Exception as e:
            self.logger.error("metric_record_failed", metric="agent_phase", error=str(e))
    
    def update_storage_stats(self, stats: Dict[str, Any]):
        """Update storage statistics."""
        try:
            if 'tasks_file_size_bytes' in stats:
                storage_size_bytes.set(stats['tasks_file_size_bytes'])
        except Exception as e:
            self.logger.error("metric_update_failed", metric="storage_stats", error=str(e))
    
    def update_from_swarm(self, swarm):
        """Update all metrics from swarm state."""
        try:
            # Active tasks
            self.update_active_tasks(len(swarm.active_tasks))

            # Task history length
            self.update_task_history_length(len(getattr(swarm, 'task_history', [])))

            # Queue depth (pending tasks)
            pending = [t for t in getattr(swarm, 'task_history', []) if getattr(t, 'status', '') == 'pending']
            self.update_queue_depth(len(pending))
            
            # Daily cost
            self.update_daily_cost(swarm.daily_cost_usd)
            
            # Success rate
            stats = swarm.get_stats()
            self.update_success_rate(stats.get('success_rate', 0))
            
            # Storage stats
            storage_stats = swarm.get_storage_stats()
            if storage_stats.get('persistence_enabled'):
                self.update_storage_stats(storage_stats)
                
        except Exception as e:
            self.logger.error("metrics_update_failed", error=str(e))


# Global instance
_metrics_instance = None


def get_metrics() -> DevSwarmMetrics:
    """Get global metrics instance."""
    global _metrics_instance
    if _metrics_instance is None:
        _metrics_instance = DevSwarmMetrics()
    return _metrics_instance
