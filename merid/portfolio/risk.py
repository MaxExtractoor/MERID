"""Shim: re-export PortfolioRiskAgent under the merid.portfolio.risk path.

Per-asset agents (eth_15m_agent, sol_15m_agent, …) import from this
module. The canonical implementation lives in
merid.prediction.portfolio_risk_agent.
"""
from merid.prediction.portfolio_risk_agent import PortfolioRiskAgent

__all__ = ["PortfolioRiskAgent"]
