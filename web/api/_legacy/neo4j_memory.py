"""
Neo4j Memory API Endpoints.

Provides REST API access to Neo4j graph database queries for
agent networks, patterns, and advanced memory analytics.
"""

from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query

from memory.neo4j_graph import get_neo4j_graph, is_neo4j_available
from web.api.auth import get_current_session
from utils.logger import get_logger

router = APIRouter(prefix="/api/v1/memory/graph", tags=["neo4j_memory"], dependencies=[Depends(get_current_session)]  # ZT6-01
)
logger = get_logger(__name__)


@router.get("/status")
async def neo4j_status():
    """Check Neo4j connection status."""
    available = is_neo4j_available()
    
    if available:
        graph = get_neo4j_graph()
        return {
            "status": "connected",
            "uri": graph.config.uri,
            "database": graph.config.database,
            "available": True
        }
    else:
        return {
            "status": "unavailable",
            "message": "Neo4j not configured or connection failed",
            "available": False
        }


@router.get("/agent/{agent_id}/network")
async def get_agent_network(agent_id: str, depth: int = Query(2, ge=1, le=5)):
    """
    Get agent's collaboration network.
    
    Returns agents that have voted on the same energies,
    showing collaboration patterns and network distance.
    """
    if not is_neo4j_available():
        raise HTTPException(status_code=503, detail="Neo4j not available")
    
    graph = get_neo4j_graph()
    network = graph.get_agent_network(agent_id, depth=depth)
    
    return network


@router.get("/agent/{agent_id}/stats")
async def get_agent_graph_stats(agent_id: str):
    """
    Get comprehensive agent statistics from graph.
    
    Includes total votes, energies voted on, accuracy,
    average confidence, and consensus participation.
    """
    if not is_neo4j_available():
        raise HTTPException(status_code=503, detail="Neo4j not available")
    
    graph = get_neo4j_graph()
    stats = graph.get_agent_stats(agent_id)
    
    if not stats:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found in graph")
    
    return {"agent_id": agent_id, "stats": stats}


@router.get("/patterns")
async def get_patterns(limit: int = Query(10, ge=1, le=100)):
    """
    Find common patterns in validated decisions.
    
    Returns most frequent sources, consensus patterns,
    and validation trends from the graph.
    """
    if not is_neo4j_available():
        raise HTTPException(status_code=503, detail="Neo4j not available")
    
    graph = get_neo4j_graph()
    patterns = graph.find_patterns(limit=limit)
    
    return {
        "patterns": patterns,
        "count": len(patterns)
    }


@router.get("/decisions/recent")
async def get_recent_graph_decisions(limit: int = Query(20, ge=1, le=100)):
    """
    Get recent decisions with full graph context.
    
    Includes energy, decision, and all agent votes
    with relationships preserved.
    """
    if not is_neo4j_available():
        raise HTTPException(status_code=503, detail="Neo4j not available")
    
    graph = get_neo4j_graph()
    decisions = graph.get_recent_decisions(limit=limit)
    
    return {
        "decisions": decisions,
        "count": len(decisions)
    }


@router.get("/agents/top")
async def get_top_agents(limit: int = Query(10, ge=1, le=50)):
    """
    Get top agents by vote count and accuracy.
    
    Uses graph queries to rank agents by participation
    and prediction accuracy.
    """
    if not is_neo4j_available():
        raise HTTPException(status_code=503, detail="Neo4j not available")
    
    graph = get_neo4j_graph()
    
    # Get all agents with stats
    # This is a simplified version - could be optimized with a dedicated query
    try:
        with graph.driver.session(database=graph.config.database) as session:
            result = session.run("""
                MATCH (a:Agent)
                OPTIONAL MATCH (a)-[:VOTED_ON]->(e:Energy)-[:RESULTED_IN]->(d:Decision)
                WITH a, 
                     count(DISTINCT e) as votes,
                     count(DISTINCT CASE WHEN d.validated = true THEN d END) as correct,
                     count(DISTINCT d) as total_decisions
                WHERE votes > 0
                RETURN a.id as agent_id,
                       votes,
                       correct,
                       total_decisions,
                       CASE WHEN total_decisions > 0 
                            THEN toFloat(correct) / total_decisions 
                            ELSE 0.0 END as accuracy
                ORDER BY votes DESC, accuracy DESC
                LIMIT $limit
            """, limit=limit)
            
            agents = [dict(record) for record in result]
            
            return {
                "agents": agents,
                "count": len(agents)
            }
    except Exception as e:
        logger.error(f"Failed to get top agents: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/clear")
async def clear_graph_data():
    """
    Clear all data from Neo4j graph.
    
    ⚠️ WARNING: This is destructive and cannot be undone!
    Use only in development/testing.
    """
    if not is_neo4j_available():
        raise HTTPException(status_code=503, detail="Neo4j not available")
    
    graph = get_neo4j_graph()
    
    try:
        graph.clear_all_data()
        return {
            "status": "cleared",
            "message": "All Neo4j data has been deleted"
        }
    except Exception as e:
        logger.error(f"Failed to clear Neo4j data: {e}")
        raise HTTPException(status_code=500, detail=str(e))
