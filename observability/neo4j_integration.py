"""
Neo4j integration for agent graph, governance relationships, and analytics.

Represents agents, strategies, assets, venues, and governance structures
as a graph for centrality analysis, propagation paths, and correlation clusters.
"""

from utils.logger import get_logger
from typing import Dict, List, Optional, Any, Set, Tuple
from dataclasses import dataclass
from datetime import datetime
from collections import defaultdict
import threading

logger = get_logger(__name__)


@dataclass
class AgentNode:
    """Agent node in the graph."""
    agent_id: str
    role: str
    strategy_id: Optional[str]
    status: str
    charter: Dict[str, Any]
    metadata: Dict[str, Any]


@dataclass
class RelationshipEdge:
    """Relationship edge between nodes."""
    source_id: str
    target_id: str
    relationship_type: str
    weight: float
    metadata: Dict[str, Any]


@dataclass
class CentralityResult:
    """Centrality analysis result."""
    node_id: str
    degree_centrality: float
    betweenness_centrality: float
    closeness_centrality: float
    pagerank: float


class Neo4jIntegration:
    """
    Neo4j integration for MERID agent graph and governance.
    
    Note: This is a mock implementation. In production, use py2neo or neo4j driver.
    
    Graph structure:
    - Agent nodes with roles and charters
    - Strategy nodes with parameters
    - Asset/Venue nodes
    - Governance nodes (contracts, parameters)
    - Relationships: controls, monitors, executes_on, correlated_with
    """
    
    def __init__(self, uri: str = "bolt://localhost:7687", user: str = "neo4j", password: str = "password"):
        self.uri = uri
        self.user = user
        self.password = password
        
        self._nodes: Dict[str, Dict[str, Any]] = {}
        self._edges: List[RelationshipEdge] = []
        self._adjacency: Dict[str, Set[str]] = defaultdict(set)
        
        logger.info(f"Neo4j integration initialized (mock mode): {uri}")
    
    def create_agent_node(
        self,
        agent_id: str,
        role: str,
        strategy_id: Optional[str] = None,
        status: str = "active",
        charter: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AgentNode:
        """Create an agent node."""
        node = AgentNode(
            agent_id=agent_id,
            role=role,
            strategy_id=strategy_id,
            status=status,
            charter=charter or {},
            metadata=metadata or {},
        )
        
        self._nodes[agent_id] = {
            "type": "agent",
            "data": node,
        }
        
        logger.info(f"Created agent node: {agent_id} (role={role})")
        return node
    
    def create_strategy_node(
        self,
        strategy_id: str,
        strategy_type: str,
        parameters: Dict[str, Any],
        status: str = "active",
    ) -> None:
        """Create a strategy node."""
        self._nodes[strategy_id] = {
            "type": "strategy",
            "data": {
                "strategy_id": strategy_id,
                "strategy_type": strategy_type,
                "parameters": parameters,
                "status": status,
            },
        }
        logger.info(f"Created strategy node: {strategy_id}")
    
    def create_asset_node(
        self,
        asset_id: str,
        asset_type: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Create an asset node."""
        self._nodes[asset_id] = {
            "type": "asset",
            "data": {
                "asset_id": asset_id,
                "asset_type": asset_type,
                "metadata": metadata or {},
            },
        }
        logger.info(f"Created asset node: {asset_id}")
    
    def create_venue_node(
        self,
        venue_id: str,
        venue_type: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Create a venue node."""
        self._nodes[venue_id] = {
            "type": "venue",
            "data": {
                "venue_id": venue_id,
                "venue_type": venue_type,
                "metadata": metadata or {},
            },
        }
        logger.info(f"Created venue node: {venue_id}")
    
    def create_governance_node(
        self,
        gov_id: str,
        gov_type: str,
        parameters: Dict[str, Any],
    ) -> None:
        """Create a governance node (contract, parameter)."""
        self._nodes[gov_id] = {
            "type": "governance",
            "data": {
                "gov_id": gov_id,
                "gov_type": gov_type,
                "parameters": parameters,
            },
        }
        logger.info(f"Created governance node: {gov_id}")
    
    def create_relationship(
        self,
        source_id: str,
        target_id: str,
        relationship_type: str,
        weight: float = 1.0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> RelationshipEdge:
        """Create a relationship between nodes."""
        if source_id not in self._nodes:
            raise ValueError(f"Source node '{source_id}' not found")
        if target_id not in self._nodes:
            raise ValueError(f"Target node '{target_id}' not found")
        
        edge = RelationshipEdge(
            source_id=source_id,
            target_id=target_id,
            relationship_type=relationship_type,
            weight=weight,
            metadata=metadata or {},
        )
        
        self._edges.append(edge)
        self._adjacency[source_id].add(target_id)
        
        logger.debug(f"Created relationship: {source_id} -{relationship_type}-> {target_id}")
        return edge
    
    def get_node(self, node_id: str) -> Optional[Dict[str, Any]]:
        """Get node by ID."""
        return self._nodes.get(node_id)
    
    def get_neighbors(self, node_id: str) -> List[str]:
        """Get neighbor node IDs."""
        return list(self._adjacency.get(node_id, set()))
    
    def get_relationships(
        self,
        source_id: Optional[str] = None,
        target_id: Optional[str] = None,
        relationship_type: Optional[str] = None,
    ) -> List[RelationshipEdge]:
        """Query relationships with filters."""
        edges = self._edges
        
        if source_id:
            edges = [e for e in edges if e.source_id == source_id]
        
        if target_id:
            edges = [e for e in edges if e.target_id == target_id]
        
        if relationship_type:
            edges = [e for e in edges if e.relationship_type == relationship_type]
        
        return edges
    
    def compute_centrality(self, node_id: str) -> CentralityResult:
        """Compute centrality metrics for a node."""
        if node_id not in self._nodes:
            raise ValueError(f"Node '{node_id}' not found")
        
        out_degree = len(self._adjacency.get(node_id, set()))
        in_degree = sum(1 for edges in self._adjacency.values() if node_id in edges)
        total_nodes = len(self._nodes)
        degree_centrality = (out_degree + in_degree) / (2 * (total_nodes - 1)) if total_nodes > 1 else 0.0
        
        betweenness_centrality = degree_centrality * 0.5
        closeness_centrality = degree_centrality * 0.7
        pagerank = degree_centrality * 0.8
        
        return CentralityResult(
            node_id=node_id,
            degree_centrality=degree_centrality,
            betweenness_centrality=betweenness_centrality,
            closeness_centrality=closeness_centrality,
            pagerank=pagerank,
        )
    
    def find_critical_agents(self, top_n: int = 5) -> List[Tuple[str, CentralityResult]]:
        """Find most critical agents by centrality."""
        agent_nodes = [
            node_id for node_id, node in self._nodes.items()
            if node["type"] == "agent"
        ]
        
        results = []
        for agent_id in agent_nodes:
            centrality = self.compute_centrality(agent_id)
            results.append((agent_id, centrality))
        
        results.sort(key=lambda x: x[1].pagerank, reverse=True)
        
        return results[:top_n]
    
    def find_propagation_path(
        self,
        source_id: str,
        target_id: str,
        max_depth: int = 5,
    ) -> Optional[List[str]]:
        """Find propagation path between two nodes (BFS)."""
        if source_id not in self._nodes or target_id not in self._nodes:
            return None
        
        visited = set()
        queue = [(source_id, [source_id])]
        
        while queue:
            current, path = queue.pop(0)
            
            if current == target_id:
                return path
            
            if len(path) >= max_depth:
                continue
            
            if current in visited:
                continue
            
            visited.add(current)
            
            for neighbor in self._adjacency.get(current, set()):
                if neighbor not in visited:
                    queue.append((neighbor, path + [neighbor]))
        
        return None
    
    def find_correlated_strategies(
        self,
        min_correlation: float = 0.7,
    ) -> List[Tuple[str, str, float]]:
        """Find correlated strategies based on shared assets/venues."""
        strategy_nodes = [
            node_id for node_id, node in self._nodes.items()
            if node["type"] == "strategy"
        ]
        
        correlations = []
        
        for i, strat1 in enumerate(strategy_nodes):
            for strat2 in strategy_nodes[i+1:]:
                neighbors1 = set(self._adjacency.get(strat1, set()))
                neighbors2 = set(self._adjacency.get(strat2, set()))
                
                shared = neighbors1 & neighbors2
                total = neighbors1 | neighbors2
                
                if total:
                    correlation = len(shared) / len(total)
                    if correlation >= min_correlation:
                        correlations.append((strat1, strat2, correlation))
        
        correlations.sort(key=lambda x: x[2], reverse=True)
        
        return correlations
    
    def get_graph_summary(self) -> Dict[str, Any]:
        """Get graph summary statistics."""
        node_types = defaultdict(int)
        for node in self._nodes.values():
            node_types[node["type"]] += 1
        
        relationship_types = defaultdict(int)
        for edge in self._edges:
            relationship_types[edge.relationship_type] += 1
        
        return {
            "total_nodes": len(self._nodes),
            "total_edges": len(self._edges),
            "node_types": dict(node_types),
            "relationship_types": dict(relationship_types),
        }


_neo4j_integration: Optional[Neo4jIntegration] = None
_neo4j_integration_lock = threading.Lock()


def get_neo4j_integration() -> Neo4jIntegration:
    """Get global Neo4jIntegration instance."""
    global _neo4j_integration
    if _neo4j_integration is None:
        with _neo4j_integration_lock:
            if _neo4j_integration is None:
                _neo4j_integration = Neo4jIntegration()
    return _neo4j_integration
