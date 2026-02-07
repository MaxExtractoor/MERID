"""
Structural weaknesses analysis and prevention for multi-agent workflows.

Identifies and prevents: over-chained workflows, circular dependencies,
single points of coordination, unclear incentives, unbounded recursion,
and hidden coupling.
"""

import logging
from typing import Dict, List, Optional, Any, Set, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from collections import defaultdict, deque
import networkx as nx

logger = logging.getLogger(__name__)


class WeaknessType(Enum):
    """Type of structural weakness."""
    OVER_CHAINED = "over_chained"
    CIRCULAR_DEPENDENCY = "circular_dependency"
    SINGLE_POINT_OF_COORDINATION = "single_point_of_coordination"
    UNCLEAR_INCENTIVES = "unclear_incentives"
    UNBOUNDED_RECURSION = "unbounded_recursion"
    HIDDEN_COUPLING = "hidden_coupling"
    EXCESSIVE_FAN_OUT = "excessive_fan_out"
    MISSING_FALLBACK = "missing_fallback"


class Severity(Enum):
    """Severity of structural weakness."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class WorkflowNode:
    """Node in workflow graph."""
    node_id: str
    node_type: str  # agent, tool, orchestrator, decision_point
    role: str
    dependencies: Set[str] = field(default_factory=set)
    dependents: Set[str] = field(default_factory=set)
    max_retries: Optional[int] = None
    timeout_seconds: Optional[float] = None
    fallback_node: Optional[str] = None
    optimization_metric: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkflowDefinition:
    """Definition of multi-agent workflow."""
    workflow_id: str
    name: str
    description: str
    nodes: Dict[str, WorkflowNode]
    entry_points: List[str]
    exit_points: List[str]
    global_objective: str
    created_at: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class StructuralWeakness:
    """Detected structural weakness."""
    weakness_id: str
    workflow_id: str
    weakness_type: WeaknessType
    severity: Severity
    
    description: str
    affected_nodes: List[str]
    evidence: Dict[str, Any]
    
    mitigation: str
    mitigated: bool = False
    
    detected_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class CoordinationRule:
    """Rule for multi-level coordination."""
    rule_id: str
    name: str
    description: str
    priority: int
    
    condition: str
    action: str
    
    agents_affected: List[str]
    enabled: bool = True


class StructuralWeaknessAnalyzer:
    """
    Structural weakness analyzer for multi-agent workflows.
    
    Detects and prevents:
    - Over-chained workflows (too many sequential agents)
    - Circular dependencies (deadlock potential)
    - Single points of coordination (brittleness)
    - Unclear incentives (conflicting metrics)
    - Unbounded recursion (resource exhaustion)
    - Hidden coupling (implicit dependencies)
    """
    
    def __init__(self):
        self._workflows: Dict[str, WorkflowDefinition] = {}
        self._weaknesses: List[StructuralWeakness] = []
        self._coordination_rules: Dict[str, CoordinationRule] = {}
        
        self._max_chain_length = 5
        self._max_fan_out = 10
        self._max_recursion_depth = 3
        
        self._initialize_coordination_rules()
    
    def _initialize_coordination_rules(self) -> None:
        """Initialize default coordination rules."""
        self.register_coordination_rule(
            rule_id="prevent_duplicate_trades",
            name="Prevent Duplicate Trades",
            description="Prevent multiple agents from trading same asset simultaneously",
            priority=100,
            condition="multiple_agents_targeting_same_asset",
            action="serialize_or_consolidate",
            agents_affected=["*"],
        )
        
        self.register_coordination_rule(
            rule_id="prevent_cancel_wars",
            name="Prevent Cancel Wars",
            description="Prevent agents from canceling each other's orders",
            priority=90,
            condition="conflicting_cancel_intents",
            action="escalate_to_coordinator",
            agents_affected=["*"],
        )
        
        self.register_coordination_rule(
            rule_id="prevent_circular_hedges",
            name="Prevent Circular Hedges",
            description="Prevent agents from creating offsetting positions",
            priority=85,
            condition="net_position_near_zero_with_high_gross",
            action="consolidate_positions",
            agents_affected=["*"],
        )
        
        logger.info("Initialized coordination rules")
    
    def register_coordination_rule(
        self,
        rule_id: str,
        name: str,
        description: str,
        priority: int,
        condition: str,
        action: str,
        agents_affected: List[str],
    ) -> CoordinationRule:
        """Register coordination rule."""
        rule = CoordinationRule(
            rule_id=rule_id,
            name=name,
            description=description,
            priority=priority,
            condition=condition,
            action=action,
            agents_affected=agents_affected,
        )
        
        self._coordination_rules[rule_id] = rule
        
        logger.info(f"Registered coordination rule '{rule_id}': {name}")
        
        return rule
    
    def register_workflow(
        self,
        workflow_id: str,
        name: str,
        description: str,
        nodes: Dict[str, WorkflowNode],
        entry_points: List[str],
        exit_points: List[str],
        global_objective: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> WorkflowDefinition:
        """Register workflow for analysis."""
        workflow = WorkflowDefinition(
            workflow_id=workflow_id,
            name=name,
            description=description,
            nodes=nodes,
            entry_points=entry_points,
            exit_points=exit_points,
            global_objective=global_objective,
            created_at=datetime.utcnow(),
            metadata=metadata or {},
        )
        
        self._workflows[workflow_id] = workflow
        
        logger.info(f"Registered workflow '{workflow_id}': {name} ({len(nodes)} nodes)")
        
        return workflow
    
    def analyze_workflow(
        self,
        workflow_id: str,
    ) -> List[StructuralWeakness]:
        """Analyze workflow for structural weaknesses."""
        if workflow_id not in self._workflows:
            raise ValueError(f"Workflow '{workflow_id}' not found")
        
        workflow = self._workflows[workflow_id]
        weaknesses = []
        
        # Build dependency graph
        graph = self._build_dependency_graph(workflow)
        
        # Check for over-chained workflows
        weaknesses.extend(self._check_over_chained(workflow, graph))
        
        # Check for circular dependencies
        weaknesses.extend(self._check_circular_dependencies(workflow, graph))
        
        # Check for single points of coordination
        weaknesses.extend(self._check_single_points(workflow, graph))
        
        # Check for unclear incentives
        weaknesses.extend(self._check_unclear_incentives(workflow))
        
        # Check for unbounded recursion
        weaknesses.extend(self._check_unbounded_recursion(workflow))
        
        # Check for hidden coupling
        weaknesses.extend(self._check_hidden_coupling(workflow))
        
        # Check for excessive fan-out
        weaknesses.extend(self._check_excessive_fan_out(workflow, graph))
        
        # Check for missing fallbacks
        weaknesses.extend(self._check_missing_fallbacks(workflow))
        
        self._weaknesses.extend(weaknesses)
        
        logger.info(
            f"Analyzed workflow '{workflow_id}': found {len(weaknesses)} weaknesses"
        )
        
        return weaknesses
    
    def _build_dependency_graph(
        self,
        workflow: WorkflowDefinition,
    ) -> nx.DiGraph:
        """Build NetworkX graph from workflow."""
        graph = nx.DiGraph()
        
        for node_id, node in workflow.nodes.items():
            graph.add_node(node_id, **{
                "node_type": node.node_type,
                "role": node.role,
            })
        
        for node_id, node in workflow.nodes.items():
            for dep_id in node.dependencies:
                graph.add_edge(dep_id, node_id)
        
        return graph
    
    def _check_over_chained(
        self,
        workflow: WorkflowDefinition,
        graph: nx.DiGraph,
    ) -> List[StructuralWeakness]:
        """Check for over-chained workflows."""
        weaknesses = []
        
        # Find longest paths from entry points
        for entry in workflow.entry_points:
            if entry not in graph:
                continue
            
            for exit_node in workflow.exit_points:
                if exit_node not in graph:
                    continue
                
                try:
                    paths = list(nx.all_simple_paths(graph, entry, exit_node))
                    
                    for path in paths:
                        if len(path) > self._max_chain_length:
                            weakness = self._create_weakness(
                                workflow_id=workflow.workflow_id,
                                weakness_type=WeaknessType.OVER_CHAINED,
                                severity=Severity.HIGH,
                                description=f"Workflow chain too long: {len(path)} nodes",
                                affected_nodes=path,
                                evidence={
                                    "chain_length": len(path),
                                    "max_allowed": self._max_chain_length,
                                    "path": path,
                                },
                                mitigation="Parallelize independent steps or introduce intermediate consolidation points",
                            )
                            weaknesses.append(weakness)
                
                except nx.NetworkXNoPath:
                    pass
        
        return weaknesses
    
    def _check_circular_dependencies(
        self,
        workflow: WorkflowDefinition,
        graph: nx.DiGraph,
    ) -> List[StructuralWeakness]:
        """Check for circular dependencies."""
        weaknesses = []
        
        try:
            cycles = list(nx.simple_cycles(graph))
            
            for cycle in cycles:
                weakness = self._create_weakness(
                    workflow_id=workflow.workflow_id,
                    weakness_type=WeaknessType.CIRCULAR_DEPENDENCY,
                    severity=Severity.CRITICAL,
                    description=f"Circular dependency detected: {' -> '.join(cycle)}",
                    affected_nodes=cycle,
                    evidence={
                        "cycle": cycle,
                        "cycle_length": len(cycle),
                    },
                    mitigation="Break cycle by introducing async messaging or removing back-edge",
                )
                weaknesses.append(weakness)
        
        except Exception as e:
            logger.error(f"Error checking circular dependencies: {e}")
        
        return weaknesses
    
    def _check_single_points(
        self,
        workflow: WorkflowDefinition,
        graph: nx.DiGraph,
    ) -> List[StructuralWeakness]:
        """Check for single points of coordination."""
        weaknesses = []
        
        # Find nodes with high betweenness centrality
        if len(graph.nodes) > 1:
            betweenness = nx.betweenness_centrality(graph)
            
            for node_id, centrality in betweenness.items():
                if centrality > 0.5:  # Node is on >50% of paths
                    node = workflow.nodes[node_id]
                    
                    # Check if it's an orchestrator without fallback
                    if node.node_type == "orchestrator" and not node.fallback_node:
                        weakness = self._create_weakness(
                            workflow_id=workflow.workflow_id,
                            weakness_type=WeaknessType.SINGLE_POINT_OF_COORDINATION,
                            severity=Severity.HIGH,
                            description=f"Single point of coordination: {node_id} (centrality={centrality:.2f})",
                            affected_nodes=[node_id],
                            evidence={
                                "betweenness_centrality": centrality,
                                "node_type": node.node_type,
                                "has_fallback": node.fallback_node is not None,
                            },
                            mitigation="Add fallback orchestrator or distribute coordination logic",
                        )
                        weaknesses.append(weakness)
        
        return weaknesses
    
    def _check_unclear_incentives(
        self,
        workflow: WorkflowDefinition,
    ) -> List[StructuralWeakness]:
        """Check for unclear or conflicting incentives."""
        weaknesses = []
        
        # Check if all nodes have optimization metrics
        nodes_without_metrics = []
        optimization_metrics = set()
        
        for node_id, node in workflow.nodes.items():
            if node.node_type == "agent":
                if not node.optimization_metric:
                    nodes_without_metrics.append(node_id)
                else:
                    optimization_metrics.add(node.optimization_metric)
        
        if nodes_without_metrics:
            weakness = self._create_weakness(
                workflow_id=workflow.workflow_id,
                weakness_type=WeaknessType.UNCLEAR_INCENTIVES,
                severity=Severity.MEDIUM,
                description=f"{len(nodes_without_metrics)} agents without optimization metrics",
                affected_nodes=nodes_without_metrics,
                evidence={
                    "nodes_without_metrics": nodes_without_metrics,
                    "global_objective": workflow.global_objective,
                },
                mitigation="Define optimization metrics aligned with global objective",
            )
            weaknesses.append(weakness)
        
        # Check for conflicting metrics
        conflicting_pairs = [
            ("pnl", "latency"),
            ("exploration", "exploitation"),
            ("risk", "return"),
        ]
        
        for metric1, metric2 in conflicting_pairs:
            if metric1 in optimization_metrics and metric2 in optimization_metrics:
                weakness = self._create_weakness(
                    workflow_id=workflow.workflow_id,
                    weakness_type=WeaknessType.UNCLEAR_INCENTIVES,
                    severity=Severity.MEDIUM,
                    description=f"Potentially conflicting metrics: {metric1} vs {metric2}",
                    affected_nodes=[],
                    evidence={
                        "conflicting_metrics": [metric1, metric2],
                        "all_metrics": list(optimization_metrics),
                    },
                    mitigation="Define clear priority hierarchy or combined objective function",
                )
                weaknesses.append(weakness)
        
        return weaknesses
    
    def _check_unbounded_recursion(
        self,
        workflow: WorkflowDefinition,
    ) -> List[StructuralWeakness]:
        """Check for unbounded recursion."""
        weaknesses = []
        
        for node_id, node in workflow.nodes.items():
            # Check if node can call itself (directly or indirectly)
            if node_id in node.dependencies:
                if not node.max_retries:
                    weakness = self._create_weakness(
                        workflow_id=workflow.workflow_id,
                        weakness_type=WeaknessType.UNBOUNDED_RECURSION,
                        severity=Severity.HIGH,
                        description=f"Node {node_id} has self-dependency without retry limit",
                        affected_nodes=[node_id],
                        evidence={
                            "self_dependency": True,
                            "max_retries": node.max_retries,
                        },
                        mitigation="Add max_retries limit or remove self-dependency",
                    )
                    weaknesses.append(weakness)
        
        return weaknesses
    
    def _check_hidden_coupling(
        self,
        workflow: WorkflowDefinition,
    ) -> List[StructuralWeakness]:
        """Check for hidden coupling."""
        weaknesses = []
        
        # Check for nodes with same external dependencies in metadata
        external_deps = defaultdict(list)
        
        for node_id, node in workflow.nodes.items():
            if "external_dependencies" in node.metadata:
                for dep in node.metadata["external_dependencies"]:
                    external_deps[dep].append(node_id)
        
        for dep, nodes in external_deps.items():
            if len(nodes) > 3:
                weakness = self._create_weakness(
                    workflow_id=workflow.workflow_id,
                    weakness_type=WeaknessType.HIDDEN_COUPLING,
                    severity=Severity.MEDIUM,
                    description=f"{len(nodes)} nodes depend on external dependency '{dep}'",
                    affected_nodes=nodes,
                    evidence={
                        "external_dependency": dep,
                        "dependent_nodes": nodes,
                    },
                    mitigation="Make dependency explicit in workflow or add fallback",
                )
                weaknesses.append(weakness)
        
        return weaknesses
    
    def _check_excessive_fan_out(
        self,
        workflow: WorkflowDefinition,
        graph: nx.DiGraph,
    ) -> List[StructuralWeakness]:
        """Check for excessive fan-out."""
        weaknesses = []
        
        for node_id in graph.nodes():
            out_degree = graph.out_degree(node_id)
            
            if out_degree > self._max_fan_out:
                weakness = self._create_weakness(
                    workflow_id=workflow.workflow_id,
                    weakness_type=WeaknessType.EXCESSIVE_FAN_OUT,
                    severity=Severity.MEDIUM,
                    description=f"Node {node_id} has excessive fan-out: {out_degree} dependents",
                    affected_nodes=[node_id],
                    evidence={
                        "fan_out": out_degree,
                        "max_allowed": self._max_fan_out,
                    },
                    mitigation="Introduce intermediate aggregation or routing nodes",
                )
                weaknesses.append(weakness)
        
        return weaknesses
    
    def _check_missing_fallbacks(
        self,
        workflow: WorkflowDefinition,
    ) -> List[StructuralWeakness]:
        """Check for missing fallbacks."""
        weaknesses = []
        
        critical_nodes = [
            node_id for node_id, node in workflow.nodes.items()
            if node.node_type in ["orchestrator", "decision_point"]
        ]
        
        for node_id in critical_nodes:
            node = workflow.nodes[node_id]
            
            if not node.fallback_node:
                weakness = self._create_weakness(
                    workflow_id=workflow.workflow_id,
                    weakness_type=WeaknessType.MISSING_FALLBACK,
                    severity=Severity.HIGH,
                    description=f"Critical node {node_id} has no fallback",
                    affected_nodes=[node_id],
                    evidence={
                        "node_type": node.node_type,
                        "has_fallback": False,
                    },
                    mitigation="Add fallback node or graceful degradation path",
                )
                weaknesses.append(weakness)
        
        return weaknesses
    
    def _create_weakness(
        self,
        workflow_id: str,
        weakness_type: WeaknessType,
        severity: Severity,
        description: str,
        affected_nodes: List[str],
        evidence: Dict[str, Any],
        mitigation: str,
    ) -> StructuralWeakness:
        """Create structural weakness record."""
        import hashlib
        weakness_id = hashlib.md5(
            f"{workflow_id}_{weakness_type.value}_{datetime.utcnow().isoformat()}".encode()
        ).hexdigest()[:16]
        
        return StructuralWeakness(
            weakness_id=weakness_id,
            workflow_id=workflow_id,
            weakness_type=weakness_type,
            severity=severity,
            description=description,
            affected_nodes=affected_nodes,
            evidence=evidence,
            mitigation=mitigation,
        )
    
    def mitigate_weakness(
        self,
        weakness_id: str,
        mitigation_notes: str,
    ) -> StructuralWeakness:
        """Mark weakness as mitigated."""
        weakness = next((w for w in self._weaknesses if w.weakness_id == weakness_id), None)
        if not weakness:
            raise ValueError(f"Weakness '{weakness_id}' not found")
        
        weakness.mitigated = True
        weakness.evidence["mitigation_notes"] = mitigation_notes
        weakness.evidence["mitigated_at"] = datetime.utcnow().isoformat()
        
        logger.info(f"Mitigated weakness '{weakness_id}': {mitigation_notes}")
        
        return weakness
    
    def get_weaknesses(
        self,
        workflow_id: Optional[str] = None,
        weakness_type: Optional[WeaknessType] = None,
        severity: Optional[Severity] = None,
        mitigated: Optional[bool] = None,
    ) -> List[StructuralWeakness]:
        """Query structural weaknesses."""
        weaknesses = self._weaknesses
        
        if workflow_id:
            weaknesses = [w for w in weaknesses if w.workflow_id == workflow_id]
        
        if weakness_type:
            weaknesses = [w for w in weaknesses if w.weakness_type == weakness_type]
        
        if severity:
            weaknesses = [w for w in weaknesses if w.severity == severity]
        
        if mitigated is not None:
            weaknesses = [w for w in weaknesses if w.mitigated == mitigated]
        
        return weaknesses
    
    def get_analysis_summary(self) -> Dict[str, Any]:
        """Get structural analysis summary."""
        return {
            "workflows_analyzed": len(self._workflows),
            "total_weaknesses": len(self._weaknesses),
            "by_type": {
                wtype.value: len([w for w in self._weaknesses if w.weakness_type == wtype])
                for wtype in WeaknessType
            },
            "by_severity": {
                sev.value: len([w for w in self._weaknesses if w.severity == sev])
                for sev in Severity
            },
            "mitigated": len([w for w in self._weaknesses if w.mitigated]),
            "unmitigated": len([w for w in self._weaknesses if not w.mitigated]),
            "coordination_rules": len(self._coordination_rules),
        }


_structural_weakness_analyzer: Optional[StructuralWeaknessAnalyzer] = None


def get_structural_weakness_analyzer() -> StructuralWeaknessAnalyzer:
    """Get global StructuralWeaknessAnalyzer instance."""
    global _structural_weakness_analyzer
    if _structural_weakness_analyzer is None:
        _structural_weakness_analyzer = StructuralWeaknessAnalyzer()
    return _structural_weakness_analyzer
