"""
System Control API for MERID.

Provides endpoints to start/stop agents, monitor system health, and control orchestration.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.agent_orchestrator import get_agent_orchestrator
from utils.logger import get_logger

router = APIRouter(prefix="/api/v1/system", tags=["system"])
logger = get_logger("web.api.system_control")


@router.post("/start")
async def start_system():
    """Start all agents and orchestration."""
    orchestrator = get_agent_orchestrator()
    
    if orchestrator.running:
        return {"status": "already_running", "message": "System is already running"}
    
    try:
        # Start orchestrator in background
        import asyncio
        asyncio.create_task(orchestrator.start())
        
        return {
            "status": "started",
            "message": "MERID system started successfully",
            "agents_active": len(orchestrator.agents)
        }
    except Exception as exc:
        logger.error(f"Failed to start system: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/stop")
async def stop_system():
    """Stop all agents and orchestration."""
    orchestrator = get_agent_orchestrator()
    
    if not orchestrator.running:
        return {"status": "already_stopped", "message": "System is not running"}
    
    try:
        orchestrator.stop()
        
        return {
            "status": "stopped",
            "message": "MERID system stopped successfully"
        }
    except Exception as exc:
        logger.error(f"Failed to stop system: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/status")
async def get_system_status():
    """Get comprehensive system status."""
    orchestrator = get_agent_orchestrator()
    
    stats = orchestrator.get_system_stats()
    
    return {
        "system_running": stats['running'],
        "agents": {
            "total": stats['total_agents'],
            "active": stats['active_agents'],
            "twitter_enabled": stats['twitter_enabled'],
            "telegram_enabled": stats['telegram_enabled'],
            "news_monitoring": stats['news_monitoring'],
            "price_streaming": stats['price_streaming']
        },
        "activity": {
            "recent_decisions": stats['recent_decisions'],
            "consensus_results": stats['consensus_results'],
            "consensus_rate": stats['consensus_rate']
        }
    }


@router.get("/agents")
async def get_agents_status():
    """Get detailed status of all agents."""
    orchestrator = get_agent_orchestrator()
    
    agents_status = {}
    
    for role, agent in orchestrator.agents.items():
        agent_info = {
            "role": role.value,
            "enabled": getattr(agent, 'enabled', True),
            "running": getattr(agent, 'running', False)
        }
        
        # Add agent-specific stats
        if hasattr(agent, 'get_stats'):
            agent_info['stats'] = agent.get_stats()
        
        agents_status[role.value] = agent_info
    
    return {"agents": agents_status}


@router.get("/decisions/recent")
async def get_recent_decisions(limit: int = 20):
    """Get recent agent decisions."""
    orchestrator = get_agent_orchestrator()
    
    decisions = orchestrator.get_recent_decisions(limit=limit)
    
    return {
        "decisions": [
            {
                "agent": d.agent_role.value,
                "type": d.decision_type,
                "data": d.data,
                "confidence": d.confidence,
                "reasoning": d.reasoning,
                "timestamp": d.timestamp.isoformat()
            }
            for d in decisions
        ],
        "total": len(decisions)
    }


@router.get("/consensus/history")
async def get_consensus_history(limit: int = 10):
    """Get consensus formation history."""
    orchestrator = get_agent_orchestrator()
    
    history = orchestrator.get_consensus_history(limit=limit)
    
    return {
        "consensus_results": [
            {
                "approved": c.approved,
                "confidence": c.confidence,
                "votes_for": c.votes_for,
                "votes_against": c.votes_against,
                "participating_agents": [a.value for a in c.participating_agents],
                "timestamp": c.timestamp.isoformat()
            }
            for c in history
        ],
        "total": len(history)
    }


class ConsensusProposal(BaseModel):
    """Consensus proposal request."""
    proposal_type: str
    data: dict


@router.post("/consensus/propose")
async def propose_consensus(proposal: ConsensusProposal):
    """Propose a decision for consensus voting."""
    orchestrator = get_agent_orchestrator()
    
    try:
        result = await orchestrator.form_consensus({
            "type": proposal.proposal_type,
            "data": proposal.data
        })
        
        return {
            "approved": result.approved,
            "confidence": result.confidence,
            "votes_for": result.votes_for,
            "votes_against": result.votes_against,
            "participating_agents": [a.value for a in result.participating_agents],
            "timestamp": result.timestamp.isoformat()
        }
    except Exception as exc:
        logger.error(f"Failed to form consensus: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/agents/twitter/post")
async def post_to_twitter(text: str):
    """Manually post to Twitter."""
    orchestrator = get_agent_orchestrator()
    
    if not orchestrator.twitter_agent.enabled:
        raise HTTPException(status_code=400, detail="Twitter agent not enabled")
    
    tweet = orchestrator.twitter_agent.post_tweet(text, force=True)
    
    if tweet:
        return {
            "status": "posted",
            "tweet_id": tweet.tweet_id,
            "text": tweet.text
        }
    else:
        raise HTTPException(status_code=500, detail="Failed to post tweet")


@router.post("/agents/telegram/send")
async def send_to_telegram(text: str):
    """Manually send message to Telegram."""
    orchestrator = get_agent_orchestrator()
    
    if not orchestrator.telegram_agent.enabled:
        raise HTTPException(status_code=400, detail="Telegram agent not enabled")
    
    message = await orchestrator.telegram_agent.send_message(text, force=True)
    
    if message:
        return {
            "status": "sent",
            "message_id": message.message_id,
            "text": message.text
        }
    else:
        raise HTTPException(status_code=500, detail="Failed to send message")
