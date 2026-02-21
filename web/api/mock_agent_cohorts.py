"""
Mock Agent Cohorts API - Phase 2.2
Provides mock endpoints for agent cohorts functionality
"""

from fastapi import APIRouter, HTTPException
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta, timezone
import random

router = APIRouter()

# Mock data storage
mock_cohorts = []
mock_agents = []
mock_stats = {}

def initialize_mock_data():
    """Initialize mock agent cohorts data"""
    global mock_cohorts, mock_agents, mock_stats
    
    # Mock cohorts
    mock_cohorts = [
        {
            'id': 'research-cohort',
            'name': 'Research Cohort',
            'type': 'Research',
            'description': 'Specialized in market research and data analysis',
            'agent_count': 4,
            'performance': 0.85,
            'efficiency': 0.78,
            'tasks_completed': 156,
            'status': 'active',
            'last_activity': (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
            'created_at': '2024-01-01T00:00:00Z'
        },
        {
            'id': 'trading-cohort',
            'name': 'Trading Cohort',
            'type': 'Trading',
            'description': 'Focused on trading strategies and execution',
            'agent_count': 6,
            'performance': 0.92,
            'efficiency': 0.88,
            'tasks_completed': 234,
            'status': 'active',
            'last_activity': (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat(),
            'created_at': '2024-01-01T00:00:00Z'
        },
        {
            'id': 'analysis-cohort',
            'name': 'Analysis Cohort',
            'type': 'Analysis',
            'description': 'Performs deep analysis and pattern recognition',
            'agent_count': 3,
            'performance': 0.79,
            'efficiency': 0.82,
            'tasks_completed': 89,
            'status': 'active',
            'last_activity': (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
            'created_at': '2024-01-15T00:00:00Z'
        },
        {
            'id': 'monitoring-cohort',
            'name': 'Monitoring Cohort',
            'type': 'Monitoring',
            'description': 'System monitoring and alert management',
            'agent_count': 2,
            'performance': 0.94,
            'efficiency': 0.91,
            'tasks_completed': 67,
            'status': 'active',
            'last_activity': (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat(),
            'created_at': '2024-01-20T00:00:00Z'
        }
    ]
    
    # Mock agents
    mock_agents = [
        {
            'id': 'analyst-gemma-01',
            'name': 'Gemma Analyst 01',
            'model': 'gemma3:1b',
            'role': 'Analyst',
            'specialization': 'Market Analysis',
            'cohort_id': 'research-cohort',
            'performance': 0.87,
            'tasks_completed': 45,
            'uptime': 86400,  # 24 hours in seconds
            'success_rate': 0.92,
            'status': 'active',
            'last_seen': (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(),
            'created_at': '2024-01-01T00:00:00Z'
        },
        {
            'id': 'analyst-llama-01',
            'name': 'Llama Analyst 01',
            'model': 'merid-strategist:latest',
            'role': 'Senior Analyst',
            'specialization': 'Strategic Analysis',
            'cohort_id': 'research-cohort',
            'performance': 0.91,
            'tasks_completed': 67,
            'uptime': 172800,  # 48 hours
            'success_rate': 0.95,
            'status': 'active',
            'last_seen': (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat(),
            'created_at': '2024-01-01T00:00:00Z'
        },
        {
            'id': 'trader-01',
            'name': 'Crypto Trader 01',
            'model': 'merid-strategist:latest',
            'role': 'Trader',
            'specialization': 'Cryptocurrency Trading',
            'cohort_id': 'trading-cohort',
            'performance': 0.89,
            'tasks_completed': 89,
            'uptime': 259200,  # 72 hours
            'success_rate': 0.87,
            'status': 'active',
            'last_seen': (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
            'created_at': '2024-01-01T00:00:00Z'
        },
        {
            'id': 'arbitrage-agent-01',
            'name': 'Arbitrage Agent 01',
            'model': 'merid-interface:latest',
            'role': 'Arbitrage Specialist',
            'specialization': 'Cross-Exchange Arbitrage',
            'cohort_id': 'trading-cohort',
            'performance': 0.94,
            'tasks_completed': 123,
            'uptime': 432000,  # 120 hours
            'success_rate': 0.91,
            'status': 'active',
            'last_seen': (datetime.now(timezone.utc) - timedelta(minutes=3)).isoformat(),
            'created_at': '2024-01-02T00:00:00Z'
        },
        {
            'id': 'risk-analyst-01',
            'name': 'Risk Analyst 01',
            'model': 'merid-interface:latest',
            'role': 'Risk Analyst',
            'specialization': 'Risk Assessment',
            'cohort_id': 'analysis-cohort',
            'performance': 0.82,
            'tasks_completed': 34,
            'uptime': 86400,
            'success_rate': 0.88,
            'status': 'active',
            'last_seen': (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat(),
            'created_at': '2024-01-15T00:00:00Z'
        },
        {
            'id': 'monitor-01',
            'name': 'System Monitor 01',
            'model': 'gemma3:1b',
            'role': 'Monitor',
            'specialization': 'System Health',
            'cohort_id': 'monitoring-cohort',
            'performance': 0.96,
            'tasks_completed': 45,
            'uptime': 172800,
            'success_rate': 0.99,
            'status': 'active',
            'last_seen': (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
            'created_at': '2024-01-20T00:00:00Z'
        }
    ]
    
    # Calculate stats
    total_cohorts = len(mock_cohorts)
    total_agents = len(mock_agents)
    active_agents = len([a for a in mock_agents if a['status'] == 'active'])
    avg_performance = sum(a['performance'] for a in mock_agents) / len(mock_agents) if mock_agents else 0
    
    mock_stats = {
        'total_cohorts': total_cohorts,
        'total_agents': total_agents,
        'active_agents': active_agents,
        'avg_performance': avg_performance,
        'total_tasks_completed': sum(a['tasks_completed'] for a in mock_agents),
        'last_updated': datetime.now(timezone.utc).isoformat()
    }

# Initialize data on module load
initialize_mock_data()

@router.get("/cohorts")
async def get_cohorts():
    """Get all agent cohorts"""
    return {
        "cohorts": mock_cohorts,
        "total": len(mock_cohorts)
    }

@router.get("/cohorts/{cohort_id}")
async def get_cohort(cohort_id: str):
    """Get a specific agent cohort"""
    cohort = next((c for c in mock_cohorts if c['id'] == cohort_id), None)
    if not cohort:
        raise HTTPException(status_code=404, detail="Cohort not found")
    
    # Add agents for this cohort
    cohort_agents = [a for a in mock_agents if a['cohort_id'] == cohort_id]
    return {
        "cohort": cohort,
        "agents": cohort_agents,
        "agent_count": len(cohort_agents)
    }

@router.get("/agents/list")
async def get_agents():
    """Get all agents"""
    return {
        "agents": mock_agents,
        "total": len(mock_agents)
    }

@router.get("/agents/{agent_id}")
async def get_agent(agent_id: str):
    """Get a specific agent"""
    agent = next((a for a in mock_agents if a['id'] == agent_id), None)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent

@router.get("/agents/cohort/{cohort_id}")
async def get_agents_by_cohort(cohort_id: str):
    """Get agents by cohort"""
    agents = [a for a in mock_agents if a['cohort_id'] == cohort_id]
    return {
        "agents": agents,
        "cohort_id": cohort_id,
        "total": len(agents)
    }

@router.get("/stats")
async def get_stats():
    """Get agent cohorts statistics"""
    return mock_stats

@router.post("/cohorts/{cohort_id}/update")
async def update_cohort(cohort_id: str, update_data: Dict[str, Any]):
    """Update cohort metrics (mock simulation)"""
    cohort = next((c for c in mock_cohorts if c['id'] == cohort_id), None)
    if not cohort:
        raise HTTPException(status_code=404, detail="Cohort not found")
    
    # Update performance with some randomness
    if 'performance' in update_data:
        cohort['performance'] = max(0.0, min(1.0, update_data['performance']))
    
    if 'tasks_completed' in update_data:
        cohort['tasks_completed'] += update_data['tasks_completed']
    
    cohort['last_activity'] = datetime.now(timezone.utc).isoformat()
    
    # Update stats
    mock_stats['total_tasks_completed'] = sum(a['tasks_completed'] for a in mock_agents)
    mock_stats['last_updated'] = datetime.now(timezone.utc).isoformat()
    
    return cohort

@router.post("/agents/{agent_id}/update")
async def update_agent(agent_id: str, update_data: Dict[str, Any]):
    """Update agent metrics (mock simulation)"""
    agent = next((a for a in mock_agents if a['id'] == agent_id), None)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    # Update metrics
    if 'performance' in update_data:
        agent['performance'] = max(0.0, min(1.0, update_data['performance']))
    
    if 'tasks_completed' in update_data:
        agent['tasks_completed'] += update_data['tasks_completed']
    
    if 'uptime' in update_data:
        agent['uptime'] += update_data['uptime']
    
    agent['last_seen'] = datetime.now(timezone.utc).isoformat()
    
    # Update stats
    mock_stats['total_tasks_completed'] = sum(a['tasks_completed'] for a in mock_agents)
    mock_stats['avg_performance'] = sum(a['performance'] for a in mock_agents) / len(mock_agents)
    mock_stats['last_updated'] = datetime.now(timezone.utc).isoformat()
    
    return agent

@router.get("/performance/top")
async def get_top_performers(limit: int = 5):
    """Get top performing agents"""
    top_agents = sorted(mock_agents, key=lambda x: x['performance'], reverse=True)[:limit]
    return {
        "top_agents": top_agents,
        "limit": limit
    }

@router.get("/cohorts/performance")
async def get_cohort_performance():
    """Get performance metrics for all cohorts"""
    cohort_performance = []
    
    for cohort in mock_cohorts:
        cohort_agents = [a for a in mock_agents if a['cohort_id'] == cohort['id']]
        if cohort_agents:
            avg_performance = sum(a['performance'] for a in cohort_agents) / len(cohort_agents)
            total_tasks = sum(a['tasks_completed'] for a in cohort_agents)
            
            cohort_performance.append({
                'cohort_id': cohort['id'],
                'cohort_name': cohort['name'],
                'avg_performance': avg_performance,
                'total_tasks': total_tasks,
                'agent_count': len(cohort_agents)
            })
    
    return {
        "cohort_performance": cohort_performance,
        "total": len(cohort_performance)
    }

@router.get("/search")
async def search_agents(q: str = "", cohort_id: Optional[str] = None, role: Optional[str] = None):
    """Search agents by query and optional filters"""
    results = mock_agents
    
    # Filter by cohort if specified
    if cohort_id:
        results = [a for a in results if a['cohort_id'] == cohort_id]
    
    # Filter by role if specified
    if role:
        results = [a for a in results if a['role'].lower() == role.lower()]
    
    # Filter by search query
    if q:
        q_lower = q.lower()
        results = [a for a in results if 
                  q_lower in a['name'].lower() or 
                  q_lower in a['specialization'].lower() or
                  q_lower in a['role'].lower()]
    
    return {
        "agents": results,
        "query": q,
        "cohort_id": cohort_id,
        "role": role,
        "total": len(results)
    }

# WebSocket event simulation
def generate_agent_update():
    """Generate random agent update for WebSocket"""
    if not mock_agents:
        return None
    
    agent = random.choice(mock_agents)
    
    # Random performance change
    performance_change = random.uniform(-0.02, 0.02)
    new_performance = max(0.0, min(1.0, agent['performance'] + performance_change))
    
    return {
        "type": "agent_updated",
        "payload": {
            "id": agent['id'],
            "performance": new_performance,
            "tasks_completed": agent['tasks_completed'] + random.randint(1, 5),
            "last_seen": datetime.now(timezone.utc).isoformat()
        }
    }

def generate_cohort_update():
    """Generate random cohort update for WebSocket"""
    if not mock_cohorts:
        return None
    
    cohort = random.choice(mock_cohorts)
    
    return {
        "type": "cohort_updated",
        "payload": {
            "id": cohort['id'],
            "performance": max(0.0, min(1.0, cohort['performance'] + random.uniform(-0.01, 0.01))),
            "tasks_completed": cohort['tasks_completed'] + random.randint(1, 3),
            "last_activity": datetime.now(timezone.utc).isoformat()
        }
    }
