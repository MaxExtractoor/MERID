"""Paper Trading Ladder API.

Endpoints for seeding portfolios, checking progress, and viewing the ladder.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/paper-ladder", tags=["paper-ladder"])


class SeedRequest(BaseModel):
    portfolio_id: str
    tier_override: Optional[int] = None


@router.get("/status")
async def get_ladder_status():
    """Get full ladder status: tiers, all portfolios, goals."""
    try:
        from merid.paper_ladder import get_paper_ladder
        ladder = get_paper_ladder()
        return ladder.summary()
    except Exception as e:
        logger.error(f"Ladder status error: {e}")
        return {"error": str(e), "tiers": [], "portfolios": {}}


@router.post("/seed")
async def seed_portfolio(req: SeedRequest):
    """Seed a portfolio with paper capital at its current (or specified) tier."""
    try:
        from merid.paper_ladder import get_paper_ladder
        ladder = get_paper_ladder()
        progress = ladder.seed_portfolio(req.portfolio_id, req.tier_override)
        return {"status": "seeded", "progress": progress.to_dict()}
    except Exception as e:
        logger.error(f"Seed error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/seed-all")
async def seed_all_agents():
    """Seed all Kalshi grid agents + swarm portfolio at Tier 0.

    Full crypto surface: BTC/ETH/SOL/XRP/DOGE × 15m/hourly/daily/weekly (20 agents)
    Plus: CRYPTO_15M_MM, KALSHI_ARB_SCANNER, MACRO_DIRECTIONAL, KALSHI_CATCH_ALL
    Plus: swarm-consensus
    """
    try:
        from merid.paper_ladder import get_paper_ladder
        from merid.prediction.paper_session import crypto_agent_names
        ladder = get_paper_ladder()

        # Seed the swarm/consensus portfolio
        ladder.seed_portfolio("swarm-consensus")

        # Seed all 20 crypto directional agents
        for name in crypto_agent_names():
            ladder.seed_portfolio(f"kalshi-{name.lower()}")

        # Seed non-crypto agents
        extra_agents = [
            "CRYPTO_15M_MM", "KALSHI_ARB_SCANNER",
            "MACRO_DIRECTIONAL", "KALSHI_CATCH_ALL",
        ]
        for name in extra_agents:
            ladder.seed_portfolio(f"kalshi-{name.lower()}")

        all_portfolios = list(ladder.get_all_progress().keys())
        return {
            "status": "seeded",
            "count": len(all_portfolios),
            "portfolios": all_portfolios,
        }
    except Exception as e:
        logger.error(f"Seed-all error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/progress/{portfolio_id}")
async def get_portfolio_progress(portfolio_id: str):
    """Get a single portfolio's ladder progress."""
    try:
        from merid.paper_ladder import get_paper_ladder
        ladder = get_paper_ladder()
        progress = ladder.get_progress(portfolio_id)
        if not progress:
            raise HTTPException(status_code=404, detail=f"Portfolio {portfolio_id} not found")
        tier = ladder.get_tier(progress.current_tier)
        return {
            "progress": progress.to_dict(),
            "tier": {
                "name": tier.name,
                "seed_usd": tier.seed_usd,
                "profit_target_pct": tier.profit_target_pct,
                "max_drawdown_pct": tier.max_drawdown_pct,
                "min_trades": tier.min_trades,
            },
            "next_goal": ladder._next_goal(progress),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Progress error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tiers")
async def get_tiers():
    """Get all ladder tier definitions."""
    from merid.paper_ladder import get_paper_ladder
    from dataclasses import asdict
    ladder = get_paper_ladder()
    return {"tiers": [asdict(t) for t in ladder.tiers]}
