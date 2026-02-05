"""
Neo4j Graph Database Integration for MERID Memory System.

Provides graph-based storage for reality memory, agent relationships,
and pattern detection with advanced querying capabilities.
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional
from dataclasses import dataclass

from utils.logger import get_logger

logger = get_logger(__name__)

# Try to import neo4j driver
try:
    from neo4j import GraphDatabase, Driver
    NEO4J_AVAILABLE = True
except ImportError:
    NEO4J_AVAILABLE = False
    GraphDatabase = None
    Driver = None
    logger.warning("neo4j package not installed - graph features disabled")


@dataclass
class Neo4jConfig:
    """Neo4j connection configuration."""
    uri: str = "bolt://localhost:7687"
    username: str = "neo4j"
    password: str = "password"
    database: str = "neo4j"
    
    @classmethod
    def from_env(cls) -> Neo4jConfig:
        """Load configuration from environment variables."""
        return cls(
            uri=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
            username=os.getenv("NEO4J_USERNAME", "neo4j"),
            password=os.getenv("NEO4J_PASSWORD", "password"),
            database=os.getenv("NEO4J_DATABASE", "neo4j")
        )


class Neo4jMemoryGraph:
    """Neo4j-backed graph database for MERID memory system."""
    
    def __init__(self, config: Optional[Neo4jConfig] = None):
        """Initialize Neo4j connection."""
        if not NEO4J_AVAILABLE:
            raise ImportError("neo4j package not installed. Install with: pip install neo4j")
        
        self.config = config or Neo4jConfig.from_env()
        self.driver: Optional[Driver] = None
        self._connected = False
        
    def connect(self) -> bool:
        """Establish connection to Neo4j database."""
        try:
            self.driver = GraphDatabase.driver(
                self.config.uri,
                auth=(self.config.username, self.config.password)
            )
            
            # Test connection
            with self.driver.session(database=self.config.database) as session:
                result = session.run("RETURN 1 as test")
                result.single()
            
            self._connected = True
            logger.info(f"✅ Neo4j connected: {self.config.uri}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Neo4j connection failed: {e}")
            self._connected = False
            return False
    
    def close(self):
        """Close Neo4j connection."""
        if self.driver:
            self.driver.close()
            self._connected = False
            logger.info("Neo4j connection closed")
    
    def is_connected(self) -> bool:
        """Check if connected to Neo4j."""
        return self._connected and self.driver is not None
    
    def initialize_schema(self):
        """Create indexes and constraints for optimal performance."""
        if not self.is_connected():
            logger.warning("Cannot initialize schema - not connected to Neo4j")
            return
        
        with self.driver.session(database=self.config.database) as session:
            # Create constraints (also creates indexes)
            constraints = [
                "CREATE CONSTRAINT agent_id IF NOT EXISTS FOR (a:Agent) REQUIRE a.id IS UNIQUE",
                "CREATE CONSTRAINT energy_id IF NOT EXISTS FOR (e:Energy) REQUIRE e.id IS UNIQUE",
                "CREATE CONSTRAINT decision_id IF NOT EXISTS FOR (d:Decision) REQUIRE d.id IS UNIQUE",
            ]
            
            # Create indexes for common queries
            indexes = [
                "CREATE INDEX agent_name IF NOT EXISTS FOR (a:Agent) ON (a.name)",
                "CREATE INDEX energy_timestamp IF NOT EXISTS FOR (e:Energy) ON (e.timestamp)",
                "CREATE INDEX decision_consensus IF NOT EXISTS FOR (d:Decision) ON (d.consensus)",
            ]
            
            for constraint in constraints:
                try:
                    session.run(constraint)
                except Exception as e:
                    logger.debug(f"Constraint already exists or failed: {e}")
            
            for index in indexes:
                try:
                    session.run(index)
                except Exception as e:
                    logger.debug(f"Index already exists or failed: {e}")
        
        logger.info("✅ Neo4j schema initialized")
    
    def record_reality(
        self,
        energy_id: str,
        payload: str,
        source: str,
        consensus: float,
        validated: bool,
        contributions: List[Dict[str, Any]],
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Record a reality memory entry in the graph.
        
        Creates:
        - Energy node
        - Decision node
        - Agent nodes (if not exist)
        - VOTED_ON relationships
        - RESULTED_IN relationship
        """
        if not self.is_connected():
            logger.warning("Cannot record reality - not connected to Neo4j")
            return False
        
        try:
            with self.driver.session(database=self.config.database) as session:
                # Create Energy node
                session.run("""
                    MERGE (e:Energy {id: $energy_id})
                    SET e.payload = $payload,
                        e.source = $source,
                        e.timestamp = $timestamp,
                        e.metadata = $metadata
                """, energy_id=energy_id, payload=payload, source=source,
                    timestamp=time.time(), metadata=metadata or {})
                
                # Create Decision node
                session.run("""
                    MERGE (d:Decision {id: $decision_id})
                    SET d.consensus = $consensus,
                        d.validated = $validated,
                        d.timestamp = $timestamp
                """, decision_id=f"decision_{energy_id}", consensus=consensus,
                    validated=validated, timestamp=time.time())
                
                # Link Energy -> Decision
                session.run("""
                    MATCH (e:Energy {id: $energy_id})
                    MATCH (d:Decision {id: $decision_id})
                    MERGE (e)-[:RESULTED_IN]->(d)
                """, energy_id=energy_id, decision_id=f"decision_{energy_id}")
                
                # Create Agent nodes and VOTED_ON relationships
                for contrib in contributions:
                    agent_id = contrib.get("agent_id", "unknown")
                    vote = contrib.get("vote", "abstain")
                    confidence = contrib.get("confidence", 0.0)
                    
                    # Create/update Agent node
                    session.run("""
                        MERGE (a:Agent {id: $agent_id})
                        ON CREATE SET a.created_at = $timestamp,
                                     a.total_votes = 1
                        ON MATCH SET a.total_votes = a.total_votes + 1,
                                    a.last_vote_at = $timestamp
                    """, agent_id=agent_id, timestamp=time.time())
                    
                    # Create VOTED_ON relationship
                    session.run("""
                        MATCH (a:Agent {id: $agent_id})
                        MATCH (e:Energy {id: $energy_id})
                        MERGE (a)-[v:VOTED_ON]->(e)
                        SET v.vote = $vote,
                            v.confidence = $confidence,
                            v.timestamp = $timestamp
                    """, agent_id=agent_id, energy_id=energy_id,
                        vote=vote, confidence=confidence, timestamp=time.time())
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to record reality in Neo4j: {e}")
            return False
    
    def get_agent_network(self, agent_id: str, depth: int = 2) -> Dict[str, Any]:
        """Get agent's network of collaborations and trust relationships."""
        if not self.is_connected():
            return {"agents": [], "relationships": []}
        
        try:
            with self.driver.session(database=self.config.database) as session:
                result = session.run("""
                    MATCH path = (a:Agent {id: $agent_id})-[:VOTED_ON*1..$depth]-(other:Agent)
                    WHERE a <> other
                    RETURN other.id as agent_id, 
                           other.total_votes as total_votes,
                           length(path) as distance
                    LIMIT 50
                """, agent_id=agent_id, depth=depth)
                
                network = [dict(record) for record in result]
                return {"agent_id": agent_id, "network": network}
                
        except Exception as e:
            logger.error(f"Failed to get agent network: {e}")
            return {"agents": [], "relationships": []}
    
    def get_agent_stats(self, agent_id: str) -> Dict[str, Any]:
        """Get comprehensive statistics for an agent."""
        if not self.is_connected():
            return {}
        
        try:
            with self.driver.session(database=self.config.database) as session:
                result = session.run("""
                    MATCH (a:Agent {id: $agent_id})
                    OPTIONAL MATCH (a)-[v:VOTED_ON]->(e:Energy)-[:RESULTED_IN]->(d:Decision)
                    RETURN a.total_votes as total_votes,
                           count(DISTINCT e) as energies_voted_on,
                           count(DISTINCT CASE WHEN d.validated = true THEN d END) as correct_predictions,
                           avg(v.confidence) as avg_confidence,
                           avg(d.consensus) as avg_consensus
                """, agent_id=agent_id)
                
                record = result.single()
                if record:
                    return dict(record)
                return {}
                
        except Exception as e:
            logger.error(f"Failed to get agent stats: {e}")
            return {}
    
    def find_patterns(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Find common patterns in validated decisions."""
        if not self.is_connected():
            return []
        
        try:
            with self.driver.session(database=self.config.database) as session:
                # Find most common sources
                result = session.run("""
                    MATCH (e:Energy)-[:RESULTED_IN]->(d:Decision)
                    WHERE d.validated = true
                    RETURN e.source as source, 
                           count(*) as frequency,
                           avg(d.consensus) as avg_consensus
                    ORDER BY frequency DESC
                    LIMIT $limit
                """, limit=limit)
                
                patterns = [dict(record) for record in result]
                return patterns
                
        except Exception as e:
            logger.error(f"Failed to find patterns: {e}")
            return []
    
    def get_recent_decisions(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get recent decisions with full context."""
        if not self.is_connected():
            return []
        
        try:
            with self.driver.session(database=self.config.database) as session:
                result = session.run("""
                    MATCH (e:Energy)-[:RESULTED_IN]->(d:Decision)
                    OPTIONAL MATCH (a:Agent)-[v:VOTED_ON]->(e)
                    RETURN e.id as energy_id,
                           e.payload as payload,
                           e.source as source,
                           d.consensus as consensus,
                           d.validated as validated,
                           d.timestamp as timestamp,
                           collect({agent: a.id, vote: v.vote, confidence: v.confidence}) as votes
                    ORDER BY d.timestamp DESC
                    LIMIT $limit
                """, limit=limit)
                
                decisions = [dict(record) for record in result]
                return decisions
                
        except Exception as e:
            logger.error(f"Failed to get recent decisions: {e}")
            return []
    
    def clear_all_data(self):
        """Clear all data from the graph (use with caution!)."""
        if not self.is_connected():
            logger.warning("Cannot clear data - not connected to Neo4j")
            return
        
        try:
            with self.driver.session(database=self.config.database) as session:
                session.run("MATCH (n) DETACH DELETE n")
            logger.info("⚠️  All Neo4j data cleared")
            
        except Exception as e:
            logger.error(f"Failed to clear Neo4j data: {e}")


# Global instance
_neo4j_graph: Optional[Neo4jMemoryGraph] = None


def get_neo4j_graph() -> Optional[Neo4jMemoryGraph]:
    """Get or create the global Neo4j graph instance."""
    global _neo4j_graph
    
    if _neo4j_graph is None:
        try:
            _neo4j_graph = Neo4jMemoryGraph()
            if _neo4j_graph.connect():
                _neo4j_graph.initialize_schema()
            else:
                _neo4j_graph = None
        except Exception as e:
            logger.warning(f"Neo4j initialization failed: {e}")
            _neo4j_graph = None
    
    return _neo4j_graph


def is_neo4j_available() -> bool:
    """Check if Neo4j is available and connected."""
    graph = get_neo4j_graph()
    return graph is not None and graph.is_connected()
