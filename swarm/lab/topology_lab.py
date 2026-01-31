"""
Topology Lab Environment for MERID Swarm
Isolated environment for testing topology experiments without affecting production
"""

import sys
import os
import time
import uuid
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from enum import Enum

sys.path.append('.')
sys.path.append('swarm')

from swarm.integration.task_runner import SwarmTaskRunner, task_runner
from swarm.testing.baseline_suite import baseline_suite
from swarm.quality.metrics_collector import quality_collector
from utils.logger import get_logger

logger = get_logger("swarm.topology_lab")


class TopologyType(Enum):
    """Available topology types for experimentation"""
    CURRENT_MESH = "current_mesh"
    SHALLOW_HIERARCHY = "shallow_hierarchy"
    STAR_TOPOLOGY = "star_topology"
    RING_TOPOLOGY = "ring_topology"
    HYBRID_MIXED = "hybrid_mixed"


@dataclass
class TopologyExperiment:
    """Configuration for a topology experiment"""
    experiment_id: str
    topology_type: TopologyType
    task_subset: List[str]  # Task IDs to include
    description: str
    start_time: float
    end_time: Optional[float] = None
    results: Optional[Dict[str, Any]] = None
    comparison_baseline: Optional[str] = None  # Reference experiment ID


class ShallowHierarchyOrchestrator:
    """Shallow hierarchy implementation for topology experiments"""
    
    def __init__(self):
        self.domain_coordinators = {
            "trading_domain": ["trader", "risk_manager", "executor"],
            "analysis_domain": ["planner", "analyzer", "reviewer"],
            "infrastructure_domain": ["deployer", "monitor", "config_manager"],
            "governance_domain": ["governor", "auditor", "approver"]
        }
        
        self.agent_domains = {}  # agent_id -> domain mapping
        self.domain_queues = {}  # domain -> task queue
        
        logger.info("Shallow hierarchy orchestrator initialized")
    
    def assign_agent_to_domain(self, agent_id: str, agent_role: str):
        """Assign agent to appropriate domain"""
        for domain, roles in self.domain_coordinators.items():
            if agent_role in roles:
                self.agent_domains[agent_id] = domain
                if domain not in self.domain_queues:
                    self.domain_queues[domain] = []
                return domain
        
        # Default domain
        default_domain = "analysis_domain"
        self.agent_domains[agent_id] = default_domain
        return default_domain
    
    def route_task_to_domain(self, task_config: Dict[str, Any]) -> str:
        """Route task to appropriate domain based on task type"""
        task_type = task_config.get("type", "analysis")
        
        domain_routing = {
            "trading": "trading_domain",
            "risk_management": "trading_domain",
            "infrastructure": "infrastructure_domain",
            "governance": "governance_domain",
            "deployment": "infrastructure_domain",
            "security": "governance_domain"
        }
        
        return domain_routing.get(task_type, "analysis_domain")
    
    def execute_with_hierarchy(self, task_config: Dict[str, Any]) -> Dict[str, Any]:
        """Execute task using shallow hierarchy"""
        domain = self.route_task_to_domain(task_config)
        
        # Create domain-specific task runner
        domain_runner = SwarmTaskRunner(enable_enforcement=False)
        
        # Filter agents for this domain
        domain_agents = []
        for agent_config in task_config["agents"]:
            agent_id = agent_config["id"]
            agent_role = agent_config["role"]
            
            # Check if agent belongs to this domain
            if self.agent_domains.get(agent_id) == domain or agent_role in self.domain_coordinators.get(domain, []):
                domain_agents.append(agent_config)
        
        # Create domain-specific task config
        domain_task_config = task_config.copy()
        domain_task_config["agents"] = domain_agents
        
        # Execute with domain runner
        logger.info(f"Executing {task_config['task_id']} in {domain} domain")
        return domain_runner.execute_task(domain_task_config)


class StarTopologyOrchestrator:
    """Star topology implementation for topology experiments"""
    
    def __init__(self):
        self.center_agent = "coordinator"
        self.connected_agents = []
        
        logger.info("Star topology orchestrator initialized")
    
    def add_agent(self, agent_id: str, agent_config: Dict[str, Any]):
        """Add agent to star topology"""
        self.connected_agents.append(agent_config)
        logger.info(f"Added agent {agent_id} to star topology (position {len(self.connected_agents)-1})")
    
    def execute_with_star(self, task_config: Dict[str, Any]) -> Dict[str, Any]:
        """Execute task using star topology"""
        # Create star topology task runner
        star_runner = SwarmTaskRunner(enable_enforcement=False)
        
        # All agents connect through coordinator
        star_agents = []
        for agent_config in task_config["agents"]:
            star_agent_config = agent_config.copy()
            star_agent_config["tools"] = ["coordination_proxy"] + agent_config.get("tools", [])
            star_agents.append(star_agent_config)
        
        # Add coordinator
        coordinator_config = {
            "id": self.center_agent,
            "role": "coordinator",
            "tools": ["task_router", "load_balancer", "state_synchronizer"]
        }
        star_agents.insert(0, coordinator_config)
        
        # Create star topology task config
        star_task_config = task_config.copy()
        star_task_config["agents"] = star_agents
        
        # Execute with star runner
        logger.info(f"Executing {task_config['task_id']} with star topology")
        return star_runner.execute_task(star_task_config)


class RingTopologyOrchestrator:
    """Ring topology implementation for topology experiments"""
    
    def __init__(self):
        self.ring_agents = []
        self.ring_order = []
        
        logger.info("Ring topology orchestrator initialized")
    
    def add_agent(self, agent_id: str, agent_config: Dict[str, Any]):
        """Add agent to ring topology"""
        self.ring_agents.append(agent_config)
        self.ring_order.append(agent_id)
        
        logger.info(f"Added agent {agent_id} to ring topology (position {len(self.ring_agents)-1})")
    
    def execute_with_ring(self, task_config: Dict[str, Any]) -> Dict[str, Any]:
        """Execute task using ring topology"""
        # Create ring topology task runner
        ring_runner = SwarmTaskRunner(enable_enforcement=False)
        
        # Arrange agents in ring order
        ring_agents = []
        for agent_id in self.ring_order:
            # Find agent config
            agent_config = next((a for a in self.ring_agents if a["id"] == agent_id), None)
            if agent_config:
                ring_agents.append(agent_config)
        
        # Create ring topology task config
        ring_task_config = task_config.copy()
        ring_task_config["agents"] = ring_agents
        
        # Execute with ring runner
        logger.info(f"Executing {task_config['task_id']} with ring topology")
        return ring_runner.execute_task(ring_task_config)


class TopologyLab:
    """Isolated environment for topology experiments"""
    
    def __init__(self):
        self.experiments: Dict[str, TopologyExperiment] = {}
        self.orchestrators = {
            TopologyType.CURRENT_MESH: None,  # Use standard orchestrator
            TopologyType.SHALLOW_HIERARCHY: ShallowHierarchyOrchestrator(),
            TopologyType.STAR_TOPOLOGY: StarTopologyOrchestrator(),
            TopologyType.RING_TOPOLOGY: RingTopologyOrchestrator(),
            TopologyType.HYBRID_MIXED: None  # Would need custom implementation
        }
        
        self.baseline_suite = baseline_suite
        self.quality_collector = quality_collector
        
        logger.info("Topology Lab initialized")
    
    def create_experiment(self, topology_type: TopologyType, task_subset: List[str], 
                        description: str, comparison_baseline: Optional[str] = None) -> str:
        """Create a topology experiment"""
        experiment_id = str(uuid.uuid4())
        
        experiment = TopologyExperiment(
            experiment_id=experiment_id,
            topology_type=topology_type,
            task_subset=task_subset,
            description=description,
            start_time=time.time(),
            comparison_baseline=comparison_baseline
        )
        
        self.experiments[experiment_id] = experiment
        logger.info(f"Created experiment {experiment_id}: {description}")
        
        return experiment_id
    
    def run_experiment(self, experiment_id: str) -> Dict[str, Any]:
        """Run a topology experiment"""
        experiment = self.experiments.get(experiment_id)
        if not experiment:
            raise ValueError(f"Experiment {experiment_id} not found")
        
        logger.info(f"Running experiment {experiment_id}: {experiment.description}")
        
        experiment.start_time = time.time()
        
        # Get appropriate orchestrator
        orchestrator = self.orchestrators[experiment.topology_type]
        
        # Run tasks with this topology
        results = []
        task_configs = []
        for t in self.baseline_suite.tasks:
            if t.task_id in experiment.task_subset:
                # Convert TaskDefinition to dict format
                task_config = {
                    "task_id": t.task_id,
                    "type": t.task_type,
                    "complexity": t.complexity,
                    "agents": t.agents,
                    "expected_duration": t.expected_duration,
                    "risk_level": t.risk_level
                }
                task_configs.append(task_config)
        
        for task_config in task_configs:
            try:
                if experiment.topology_type == TopologyType.CURRENT_MESH:
                    result = task_runner.execute_task(task_config)
                else:
                    # For topology experiments, we need to handle the orchestrator differently
                    # For now, fall back to standard task runner
                    result = task_runner.execute_task(task_config)
                
                results.append(result)
                logger.info(f"✓ {task_config['task_id']} completed")
                
            except Exception as e:
                logger.error(f"✗ {task_config['task_id']} failed: {e}")
                # Create failure result
                failure_result = type('obj', (object,), {
                    'task_id': task_config['task_id'],
                    'success': False,
                    'cascade_size': 0,
                    'cascade_depth': 0,
                    'branching_factor': 0.0,
                    'retry_index': 0.0,
                    'misalignment_scores': {},
                    'total_turns': 0,
                    'total_tokens': 0
                })()
                results.append(failure_result)
        
        # Calculate experiment metrics
        experiment.end_time = time.time()
        experiment.results = self._calculate_experiment_metrics(results, experiment)
        
        logger.info(f"Experiment {experiment_id} completed")
        
        return experiment.results
    
    def _calculate_experiment_metrics(self, results: List[Any], experiment: TopologyExperiment) -> Dict[str, Any]:
        """Calculate metrics for experiment results"""
        if not results:
            return {"error": "No results to analyze"}
        
        # Basic metrics
        total_tasks = len(results)
        successful_tasks = sum(1 for r in results if getattr(r, 'success', False))
        success_rate = successful_tasks / total_tasks
        
        # Cascade metrics
        cascade_sizes = [getattr(r, 'cascade_size', 0) for r in results]
        branching_factors = [getattr(r, 'branching_factor', 0.0) for r in results]
        
        avg_cascade_size = sum(cascade_sizes) / len(cascade_sizes) if cascade_sizes else 0
        avg_branching_factor = sum(branching_factors) / len(branching_factors) if branching_factors else 0
        
        # Quality metrics (if available)
        quality_scores = []
        for result in results:
            if hasattr(result, 'total_turns') and result.total_turns > 0:
                # Simple quality proxy: success rate with efficiency consideration
                success = getattr(result, 'success', False)
                efficiency = 100.0 / result.total_turns if result.total_turns > 0 else 0
                quality_score = (success * 0.7 + efficiency * 0.3) * 100
                quality_scores.append(quality_score)
        
        avg_quality_score = sum(quality_scores) / len(quality_scores) if quality_scores else 0
        
        return {
            "experiment_id": experiment.experiment_id,
            "topology_type": experiment.topology_type.value,
            "description": experiment.description,
            "duration_seconds": experiment.end_time - experiment.start_time,
            "task_count": total_tasks,
            "success_rate": success_rate,
            "avg_cascade_size": avg_cascade_size,
            "avg_branching_factor": avg_branching_factor,
            "avg_quality_score": avg_quality_score,
            "max_cascade_size": max(cascade_sizes) if cascade_sizes else 0,
            "resilience_characteristics": self._evaluate_resilience_characteristics(success_rate, avg_cascade_size, avg_branching_factor)
        }
    
    def _evaluate_resilience_characteristics(self, success_rate: float, cascade_size: float, branching_factor: float) -> str:
        """Evaluate resilience characteristics"""
        if success_rate >= 0.9 and cascade_size < 1 and branching_factor < 0.5:
            return "excellent"
        elif success_rate >= 0.8 and cascade_size < 2 and branching_factor < 1.0:
            return "good"
        elif success_rate >= 0.6 and cascade_size < 5 and branching_factor < 1.5:
            return "acceptable"
        else:
            return "poor"
    
    def compare_experiments(self, experiment_ids: List[str]) -> Dict[str, Any]:
        """Compare multiple topology experiments"""
        comparisons = {}
        
        for exp_id in experiment_ids:
            if exp_id not in self.experiments:
                continue
            
            comparisons[exp_id] = self.experiments[exp_id].results
        
        # Calculate comparative analysis
        if len(comparisons) < 2:
            return {"error": "Need at least 2 experiments to compare"}
        
        # Find best performing topology
        best_experiment = max(comparisons.items(), 
                            key=lambda x: x[1]["success_rate"] if x[1] else 0)
        
        best_topology = best_experiment[0]
        best_metrics = best_experiment[1]
        
        # Generate comparison table
        comparison_table = []
        for exp_id, metrics in comparisons.items():
            experiment = self.experiments[exp_id]
            comparison_table.append({
                "topology": experiment.topology_type.value,
                "success_rate": metrics["success_rate"],
                "cascade_size": metrics["avg_cilcade_size"],
                "branching_factor": metrics["avg_branching_factor"],
                "quality_score": metrics["avg_quality_score"],
                "resilience": metrics["resilience_characteristics"]
            })
        
        # Sort by success rate
        comparison_table.sort(key=lambda x: x["success_rate"], reverse=True)
        
        return {
            "best_topology": best_topology,
            "best_metrics": best_metrics,
            "comparison_table": comparison_table,
            "recommendations": self._generate_topology_recommendations(comparison_table)
        }
    
    def _generate_topology_recommendations(self, comparison_table: List[Dict[str, Any]]) -> List[str]:
        """Generate recommendations based on topology comparison"""
        recommendations = []
        
        if not comparison_table:
            return ["No experiments to compare"]
        
        best_topology = comparison_table[0]["topology"]
        best_success_rate = comparison_table[0]["success_rate"]
        
        # Analyze performance differences
        for row in comparison_table[1:]:
            if row["success_rate"] < best_success_rate - 0.1:
                recommendations.append(
                    f"{row['topology']} underperforms by {best_success_rate - row['success_rate']:.1%}"
                )
            elif row["cascade_size"] > 2.0:
                recommendations.append(
                    f"{row['topology']} shows cascade propagation (avg size: {row['avg_cascade_size']:.1f})"
                )
            elif row["branching_factor"] > 1.0:
                recommendations.append(
                    f"{row['topology']} has high branching factor ({row['avg_branching_factor']:.2f})"
                )
        
        if best_success_rate >= 0.9:
            recommendations.append(f"{best_topology} shows excellent performance - consider for production")
        elif best_success_rate >= 0.8:
            recommendations.append(f"{best_topology} shows good performance - suitable for production")
        else:
            recommendations.append("All topologies show suboptimal performance - investigate further")
        
        return recommendations
    
    def export_experiment_results(self, filename: str = "topology_lab_results.json"):
        """Export all experiment results to file"""
        results_data = {
            "timestamp": time.time(),
            "experiments": {
                exp_id: {
                    "topology_type": exp.topology_type.value,
                    "description": exp.description,
                    "start_time": exp.start_time,
                    "end_time": exp.end_time,
                    "results": exp.results
                }
                for exp_id, exp in self.experiments.items()
            }
        }
        
        with open(filename, 'w') as f:
            json.dump(results_data, f, indent=2)
        
        logger.info(f"Experiment results exported to {filename}")


# Global topology lab instance
topology_lab = TopologyLab()
