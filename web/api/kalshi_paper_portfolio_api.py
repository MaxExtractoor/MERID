# web/api/kalshi_paper_portfolio_api.py
"""Kalshi paper portfolio API endpoints."""

from fastapi import APIRouter, Depends
from web.api.auth import get_current_session
from utils.logger import get_logger
from merid.kalshi.paper_portfolio import get_kalshi_paper_portfolio

logger = get_logger("web.api.kalshi_paper_portfolio")

router = APIRouter(
    prefix="/api/v1/kalshi-grid/crypto",
    tags=["Kalshi Paper Portfolio"],
)


@router.get("/paper/portfolio")
async def get_paper_portfolio():
    """Get paper portfolio summary."""
    try:
        portfolio = get_kalshi_paper_portfolio()
        summary = portfolio.get_portfolio_summary()
        return {
            "summary": summary,
            "timestamp": logger.info("Paper portfolio summary retrieved")
        }
    except Exception as exc:
        logger.error(f"Failed to get paper portfolio: {exc}")
        return {
            "summary": {},
            "error": str(exc)
        }


@router.get("/paper/agent/{agent_id}")
async def get_paper_agent_performance(agent_id: str):
    """Get paper performance for a specific agent."""
    try:
        portfolio = get_kalshi_paper_portfolio()
        performance = portfolio.get_agent_performance(agent_id)
        return {
            "agent_id": agent_id,
            "performance": performance,
            "timestamp": logger.info(f"Paper agent performance retrieved for {agent_id}")
        }
    except Exception as exc:
        logger.error(f"Failed to get paper agent performance for {agent_id}: {exc}")
        return {
            "agent_id": agent_id,
            "performance": {},
            "error": str(exc)
        }


@router.get("/paper-vs-shadow")
async def get_paper_vs_shadow_comparison():
    """Compare paper vs shadow performance across crypto agents."""
    # PROFILE-GUARD: Disable for kalshi_crypto_15m_v2 (paper vs shadow comparison not needed for sealed 15m profile)
    profile = os.getenv("MERID_PROFILE", "").lower()
    if profile == "kalshi_crypto_15m_v2":
        raise HTTPException(
            403,
            "Paper vs shadow comparison is disabled for kalshi_crypto_15m_v2 profile (sealed 15m profile uses direct trading only)"
        )
    
    try:
        # Get paper portfolio data
        portfolio = get_kalshi_paper_portfolio()
        paper_summary = portfolio.get_portfolio_summary()
        
        # Get shadow performance from tracker
        from merid.prediction.agent_performance_tracker import get_agent_performance_tracker
        tracker = get_agent_performance_tracker()
        
        crypto_agents = ["btc_15m_regime", "eth_15m_regime", "sol_15m_regime", "xrp_15m_regime", "doge_15m_regime"]
        comparison = {}
        
        for agent_id in crypto_agents:
            paper_perf = portfolio.get_agent_performance(agent_id)
            shadow_metrics = tracker.get_agent_metrics(agent_id)
            
            shadow_perf = {
                "total_trades": shadow_metrics.total_closes if shadow_metrics else 0,
                "total_pnl": float(shadow_metrics.total_pnl_usd) if shadow_metrics else 0,
                "win_rate": shadow_metrics.win_rate if shadow_metrics else 0,
            }
            
            comparison[agent_id] = {
                "paper": paper_perf,
                "shadow": shadow_perf,
                "pnl_delta": paper_perf["total_pnl"] - shadow_perf["total_pnl"],
                "trade_rate_delta": paper_perf["total_trades"] - shadow_perf["total_trades"],
                "win_rate_delta": paper_perf["win_rate"] - shadow_perf["win_rate"],
            }
        
        return {
            "comparison": comparison,
            "paper_summary": paper_summary,
            "timestamp": logger.info("Paper vs shadow comparison retrieved")
        }
    except Exception as exc:
        logger.error(f"Failed to get paper vs shadow comparison: {exc}")
        return {
            "comparison": {},
            "paper_summary": {},
            "error": str(exc)
        }
