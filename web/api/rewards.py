"""
Unified Rewards API — gamification, quests, x402 payments, leaderboard.

Consolidates the disconnected rewards subsystems into a single API surface:
- XP and leaderboard (services/gamification.py)
- Quest campaigns with seasons (services/quest_campaigns.py)
- Reward pool emissions (services/reward_pool_manager.py)
- x402 micropayment stats (core/x402_payments.py)
- Gamified security quests (swarm/gamified_security.py)
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from utils.logger import get_logger

router = APIRouter(prefix="/api/v1/rewards", tags=["rewards"])
logger = get_logger("web.api.rewards")


# ── Singletons ────────────────────────────────────────────────────

def _gamification():
    from services.gamification import GamificationEngine
    # Reuse the module-level singleton pattern
    if not hasattr(_gamification, "_inst"):
        _gamification._inst = GamificationEngine()
    return _gamification._inst


def _quest_service():
    from services.quest_campaigns import QuestCampaignService, Quest
    if not hasattr(_quest_service, "_inst"):
        svc = QuestCampaignService()
        # Seed default quests
        svc.register_quest(Quest(
            quest_id="q-first-trade", title="First Trade",
            description="Execute your first simulated trade",
            season=1, reward_points=100, requirements={"min_trades": "1"},
        ))
        svc.register_quest(Quest(
            quest_id="q-risk-compliant", title="Risk Compliant",
            description="Complete 10 trades with zero risk violations",
            season=1, reward_points=250, requirements={"compliant_trades": "10"},
        ))
        svc.register_quest(Quest(
            quest_id="q-streak-7", title="7-Day Streak",
            description="Log in and review positions for 7 consecutive days",
            season=1, reward_points=150, requirements={"streak_days": "7"},
        ))
        svc.register_quest(Quest(
            quest_id="q-bug-hunter", title="Bug Hunter",
            description="Report a verified bug in the system",
            season=1, reward_points=500, requirements={"verified_bugs": "1"},
        ))
        svc.register_quest(Quest(
            quest_id="q-consensus-voter", title="Consensus Voter",
            description="Participate in 50 consensus rounds",
            season=1, reward_points=200, requirements={"consensus_rounds": "50"},
        ))
        _quest_service._inst = svc
    return _quest_service._inst


def _reward_pool():
    from services.reward_pool_manager import RewardPoolManager
    if not hasattr(_reward_pool, "_inst"):
        mgr = RewardPoolManager()
        mgr.register_pool("trading", Decimal("5000.0"))
        mgr.register_pool("security", Decimal("2000.0"))
        mgr.register_pool("governance", Decimal("1000.0"))
        _reward_pool._inst = mgr
    return _reward_pool._inst


def _x402_client():
    try:
        from core.x402_payments import get_x402_client
        return get_x402_client()
    except Exception:
        return None


def _security_system():
    try:
        from swarm.gamified_security import GamifiedSecuritySystem
        if not hasattr(_security_system, "_inst"):
            _security_system._inst = GamifiedSecuritySystem()
        return _security_system._inst
    except Exception:
        return None


# ── Request/Response Models ───────────────────────────────────────

class AwardXpRequest(BaseModel):
    user_id: str = Field(..., description="User or agent ID")
    multiplier: float = Field(1.0, ge=0.1, le=10.0, description="XP multiplier")
    reason: str = Field(..., description="Reason for XP award")
    metadata: Dict[str, str] = Field(default_factory=dict)


class QuestProgressRequest(BaseModel):
    quest_id: str = Field(..., description="Quest ID")
    user_id: str = Field(..., description="User or agent ID")
    completed: bool = Field(False, description="Whether quest is completed")


class BugReportRequest(BaseModel):
    reporter_id: str
    title: str
    description: str
    severity: str = Field("low", description="info, low, medium, high, critical")
    affected_contract: Optional[str] = None
    evidence: List[str] = Field(default_factory=list)
    reproduction_steps: List[str] = Field(default_factory=list)


# ── Dashboard / Summary ──────────────────────────────────────────

@router.get("/summary")
async def rewards_summary() -> Dict[str, Any]:
    """Full rewards system summary — gamification, quests, pools, x402."""
    result: Dict[str, Any] = {}

    # Gamification
    gam = _gamification()
    result["gamification"] = {
        "leaderboard": gam.leaderboard(limit=10),
        "total_users": len(gam._xp),
        "total_events": len(gam._events),
    }

    # Quests
    svc = _quest_service()
    result["quests"] = {
        "registered": len(svc._quests),
        "quests": [
            {"id": q.quest_id, "title": q.title, "season": q.season, "points": q.reward_points}
            for q in svc._quests.values()
        ],
        "progress_entries": len(svc._progress),
    }

    # Reward pools
    pool_mgr = _reward_pool()
    pools = {}
    for pid, state in pool_mgr._pools.items():
        pools[pid] = {
            "base_emission": float(state.base_emission_per_day),
            "multiplier": float(state.multiplier),
            "current_emission": float(pool_mgr.current_emission(pid)),
            "participation_rate": float(state.participation_rate),
        }
    result["reward_pools"] = pools

    # x402
    x402 = _x402_client()
    if x402:
        result["x402"] = x402.get_statistics()
    else:
        result["x402"] = {"available": False}

    # Security quests
    sec = _security_system()
    if sec:
        result["security"] = {
            "quests": len(sec._quests),
            "bug_reports": len(sec._bug_reports),
            "seasons": len(sec._seasons),
            "users": len(sec._user_profiles),
        }

    return result


# ── Gamification / XP ─────────────────────────────────────────────

@router.get("/leaderboard")
async def leaderboard(limit: int = Query(20, ge=1, le=100)) -> Dict[str, Any]:
    """XP leaderboard."""
    gam = _gamification()
    return {"items": gam.leaderboard(limit=limit)}


@router.post("/xp/award")
async def award_xp(req: AwardXpRequest) -> Dict[str, Any]:
    """Award XP to a user or agent."""
    gam = _gamification()
    xp_gained = gam.award_xp(req.user_id, req.multiplier, req.reason, req.metadata)
    return {
        "user_id": req.user_id,
        "xp_gained": xp_gained,
        "total_xp": gam.xp_for(req.user_id),
        "reason": req.reason,
    }


@router.get("/xp/{user_id}")
async def get_user_xp(user_id: str) -> Dict[str, Any]:
    """Get XP and event history for a user."""
    gam = _gamification()
    return {
        "user_id": user_id,
        "total_xp": gam.xp_for(user_id),
        "events": gam.events_for(user_id, limit=50),
    }


# ── Quests ────────────────────────────────────────────────────────

@router.get("/quests")
async def list_quests(season: int = Query(1, ge=1)) -> Dict[str, Any]:
    """List all quests for a season."""
    svc = _quest_service()
    quests = [
        {"id": q.quest_id, "title": q.title, "description": q.description,
         "season": q.season, "points": q.reward_points, "requirements": q.requirements}
        for q in svc._quests.values() if q.season == season
    ]
    return {"season": season, "quests": quests}


@router.post("/quests/progress")
async def record_quest_progress(req: QuestProgressRequest) -> Dict[str, Any]:
    """Record quest progress for a user."""
    svc = _quest_service()
    if req.quest_id not in svc._quests:
        raise HTTPException(status_code=404, detail=f"Quest '{req.quest_id}' not found")
    progress = svc.record_progress(req.quest_id, req.user_id, req.completed)

    # Award XP on completion
    if req.completed:
        quest = svc._quests[req.quest_id]
        gam = _gamification()
        gam.award_xp(req.user_id, quest.reward_points / 50.0, f"quest:{req.quest_id}")

    return {
        "quest_id": progress.quest_id,
        "user_id": progress.user_id,
        "completed": progress.completed,
        "completion_timestamp": str(progress.completion_timestamp) if progress.completion_timestamp else None,
    }


@router.get("/quests/leaderboard/{season}")
async def quest_season_leaderboard(season: int) -> Dict[str, Any]:
    """Season leaderboard by quest points."""
    svc = _quest_service()
    return {"season": season, "leaderboard": svc.season_leaderboard(season)}


# ── Reward Pools ──────────────────────────────────────────────────

@router.get("/pools")
async def list_reward_pools() -> Dict[str, Any]:
    """List all reward pools with current emissions."""
    mgr = _reward_pool()
    pools = {}
    for pid, state in mgr._pools.items():
        pools[pid] = {
            "base_emission_per_day": float(state.base_emission_per_day),
            "multiplier": float(state.multiplier),
            "current_emission": float(mgr.current_emission(pid)),
            "participation_rate": float(state.participation_rate),
            "last_adjusted": str(state.last_adjusted),
        }
    return {"pools": pools}


@router.post("/pools/{pool_id}/adjust")
async def adjust_pool(pool_id: str, participation_rate: float = Query(..., ge=0, le=1)) -> Dict[str, Any]:
    """Update participation rate and adjust pool emissions."""
    mgr = _reward_pool()
    if pool_id not in mgr._pools:
        raise HTTPException(status_code=404, detail=f"Pool '{pool_id}' not found")
    mgr.update_participation(pool_id, Decimal(str(participation_rate)))
    state = mgr.adjust_rewards(pool_id)
    return {
        "pool_id": pool_id,
        "new_multiplier": float(state.multiplier),
        "current_emission": float(mgr.current_emission(pool_id)),
        "participation_rate": float(state.participation_rate),
    }


# ── x402 Payments ─────────────────────────────────────────────────

@router.get("/x402/stats")
async def x402_stats() -> Dict[str, Any]:
    """x402 payment statistics."""
    client = _x402_client()
    if not client:
        return {"available": False, "reason": "x402 client not initialized"}
    return client.get_statistics()


@router.get("/x402/receipts")
async def x402_receipts(limit: int = Query(20, ge=1, le=100)) -> Dict[str, Any]:
    """Recent x402 payment receipts."""
    client = _x402_client()
    if not client:
        return {"receipts": []}
    receipts = client.get_receipts(limit=limit)
    return {
        "receipts": [
            {
                "receipt_id": r.receipt_id,
                "amount_paid": r.amount_paid,
                "rail": r.rail.value,
                "tx_hash": r.tx_hash,
                "timestamp": r.timestamp,
            }
            for r in receipts
        ]
    }


@router.get("/x402/resources")
async def x402_resources() -> Dict[str, Any]:
    """Discover available x402 resources."""
    client = _x402_client()
    if not client:
        return {"resources": []}
    resources = client.discover_resources("https://api.merid.com")
    return {
        "resources": [
            {
                "id": r.resource_id,
                "url": r.url,
                "description": r.description,
                "price_sats": r.price_sats,
                "price_usd": r.price_usd,
                "rails": [rail.value for rail in r.supported_rails],
                "ttl_seconds": r.ttl_seconds,
            }
            for r in resources
        ]
    }


# ── Security Quests ───────────────────────────────────────────────

@router.get("/security/quests")
async def security_quests() -> Dict[str, Any]:
    """List gamified security quests."""
    sec = _security_system()
    if not sec:
        return {"quests": []}
    return {
        "quests": [
            {
                "id": q.quest_id,
                "type": q.quest_type.value,
                "title": q.title,
                "description": q.description,
                "points": q.reward_points,
                "tier": q.reward_tier.value,
                "status": q.status.value,
            }
            for q in sec._quests.values()
        ]
    }


@router.post("/security/bug-report")
async def submit_bug_report(req: BugReportRequest) -> Dict[str, Any]:
    """Submit a security bug report."""
    sec = _security_system()
    if not sec:
        raise HTTPException(status_code=503, detail="Security system not available")

    from swarm.gamified_security import SeverityLevel
    severity_map = {
        "info": SeverityLevel.INFO, "low": SeverityLevel.LOW,
        "medium": SeverityLevel.MEDIUM, "high": SeverityLevel.HIGH,
        "critical": SeverityLevel.CRITICAL,
    }
    severity = severity_map.get(req.severity.lower(), SeverityLevel.LOW)

    report = sec.submit_bug_report(
        reporter_id=req.reporter_id,
        title=req.title,
        description=req.description,
        reported_severity=severity,
        affected_contract=req.affected_contract,
        evidence=req.evidence,
        reproduction_steps=req.reproduction_steps,
    )
    return {
        "report_id": report.report_id,
        "reporter_id": report.reporter_id,
        "severity": report.reported_severity.value,
        "status": "submitted",
    }
