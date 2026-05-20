"""
Post-Trade PnL Attribution for Debate System
Analyzes realized PnL impact of debate-aware sizing and exit decisions.
"""

import time
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
import logging
import asyncio
import json

from core.slo_monitor import SLOMonitor
from merid.prediction.pnl_attribution_db import get_pnl_attribution_db, PersistentTradeRecord, AttributionRecord

logger = logging.getLogger("merid.prediction.pnl_attribution")


class TradeType(Enum):
    """Types of trades for attribution."""
    ENTRY = "entry"
    EXIT = "exit"
    TRIM = "trim"


@dataclass
class TradeRecord:
    """Record of a trade for PnL attribution."""
    symbol: str
    trade_type: TradeType
    timestamp: float
    price: float
    quantity: int
    trade_id: str
    agent_id: Optional[str]
    base_kelly_fraction: float = 0.0
    debate_multiplier: float = 1.0
    final_kelly_fraction: float = 0.0
    debate_recommendation: Optional[str] = None
    exit_reason: Optional[str] = None

    # Attribution fields (calculated later)
    base_position_size: float = 0.0  # What position size would have been with base Kelly
    debate_position_size: float = 0.0  # Actual position size with debate multiplier
    # LEGACY REMOVAL: debate_risk_amount field removed - debate module deleted

    # PnL fields (filled later)
    realized_pnl: Optional[float] = None
    base_pnl: Optional[float] = None  # Counterfactual PnL with base Kelly
    # LEGACY REMOVAL: debate_pnl_impact field removed - debate module deleted
    exit_pnl_impact: Optional[float] = None  # PnL difference from debate exit


@dataclass
class AttributionSummary:
    """Summary of PnL attribution over a period."""
    period_start: datetime
    period_end: datetime
    total_trades: int
    
    # PnL attribution
    total_realized_pnl: float
    total_base_pnl: float
    total_debate_pnl_impact: float
    total_exit_pnl_impact: float
    
    # Performance metrics
    debate_sizing_win_rate: float
    debate_exit_win_rate: float
    overall_debate_contribution_pct: float
    
    # Breakdown by agent/tier
    agent_contributions: Dict[str, Dict[str, float]] = field(default_factory=dict)
    tier_contributions: Dict[str, Dict[str, float]] = field(default_factory=dict)
    symbol_contributions: Dict[str, Dict[str, float]] = field(default_factory=dict)


class PnLAttributionEngine:
    """Analyzes realized PnL impact of debate-driven trading decisions."""
    
    def __init__(self):
        self.slo_monitor = SLOMonitor.get_instance()
        self.db = get_pnl_attribution_db()
        self.trade_records: List[TradeRecord] = []
        self.attribution_summaries: List[AttributionSummary] = []
        self.max_trade_records = 50000
        self.max_summaries = 100
        
        # Performance tracking
        self.last_analysis_time = 0.0
        self.analysis_interval = 3600  # Analyze every hour
        
        # Persistence settings
        self.persistence_enabled = True
        self.batch_size = 100  # Batch size for database writes
        
        # Attribution parameters
        self.min_holding_period_hours = 0.1  # Minimum holding period for attribution
        self.max_attribution_period_days = 30  # Maximum period for PnL attribution
    
    async def record_trade(
        self,
        symbol: str,
        trade_type: TradeType,
        timestamp: float,
        price: float,
        quantity: int,
        trade_id: str,
        agent_id: Optional[str] = None,
        base_kelly_fraction: float = 0.0,
        debate_multiplier: float = 1.0,
        final_kelly_fraction: float = 0.0,
        debate_recommendation: Optional[str] = None,
        exit_reason: Optional[str] = None
    ):
        """Record a trade for PnL attribution."""
        try:
            # Calculate position sizes
            base_position_size = abs(price * quantity * base_kelly_fraction)
            debate_position_size = abs(price * quantity * final_kelly_fraction)
            debate_risk_amount = debate_position_size - base_position_size
            
            trade_record = TradeRecord(
                symbol=symbol,
                trade_type=trade_type,
                timestamp=timestamp,
                price=price,
                quantity=quantity,
                trade_id=trade_id,
                agent_id=agent_id,
                base_kelly_fraction=base_kelly_fraction,
                debate_multiplier=debate_multiplier,
                final_kelly_fraction=final_kelly_fraction,
                debate_recommendation=debate_recommendation,
                exit_reason=exit_reason,
                base_position_size=base_position_size,
                debate_position_size=debate_position_size,
                debate_risk_amount=debate_risk_amount
            )
            
            self.trade_records.append(trade_record)
            
            # Trim if too many records
            if len(self.trade_records) > self.max_trade_records:
                self.trade_records = self.trade_records[-self.max_trade_records:]
            
            # Store trade record in database if persistence is enabled
            if self.persistence_enabled:
                try:
                    persistent_trade = PersistentTradeRecord(
                        symbol=symbol,
                        trade_type=trade_type,
                        timestamp=timestamp,
                        price=price,
                        quantity=quantity,
                        trade_id=trade_id,
                        agent_id=agent_id,
                        base_kelly_fraction=base_kelly_fraction,
                        debate_multiplier=debate_multiplier,
                        final_kelly_fraction=final_kelly_fraction,
                        debate_recommendation=debate_recommendation,
                        exit_reason=exit_reason,
                        base_position_size=base_position_size,
                        debate_position_size=debate_position_size,
                        debate_risk_amount=debate_risk_amount
                    )
                    
                    await self.db.store_trade_record(persistent_trade)
                    
                except Exception as e:
                    logger.warning(f"Failed to store trade record in database: {e}")
            
            # Track SLO for trade recording
            self.slo_monitor.track_slo(
                metric_name="debate.pnl_attribution.trade_recorded",
                success=True,
                total=1,
                metadata={
                    "symbol": symbol,
                    "trade_type": trade_type.value,
                    "agent_id": agent_id,
                    "debate_multiplier": debate_multiplier,
                    "debate_recommendation": debate_recommendation,
                    "exit_reason": exit_reason
                }
            )
            
            logger.debug(f"Recorded trade for attribution: {symbol} {trade_type.value} {trade_id}")
            
        except Exception as e:
            logger.error(f"Error recording trade for attribution: {e}")
    
    async def calculate_attribution(
        self,
        symbol: str,
        entry_trade: TradeRecord,
        exit_trade: TradeRecord,
        current_price: float = None
    ) -> Dict[str, Any]:
        """
        Calculate PnL attribution for a completed trade pair.
        
        Args:
            symbol: Kalshi symbol
            entry_trade: Entry trade record
            exit_trade: Exit trade record
            current_price: Current price for unrealized PnL (if still open)
            
        Returns:
            Attribution results
        """
        try:
            # Calculate realized PnL
            if exit_trade:
                # Completed trade
                realized_pnl = (exit_trade.price - entry_trade.price) * entry_trade.quantity
                holding_period_hours = (exit_trade.timestamp - entry_trade.timestamp) / 3600
            else:
                # Still open - use current price
                if current_price is None:
                    return {"error": "No exit trade and no current price provided"}
                realized_pnl = (current_price - entry_trade.price) * entry_trade.quantity
                holding_period_hours = (time.time() - entry_trade.timestamp) / 3600
            
            # Calculate counterfactual base PnL
            base_pnl = realized_pnl * (entry_trade.base_kelly_fraction / entry_trade.final_kelly_fraction) if entry_trade.final_kelly_fraction > 0 else realized_pnl
            
            # Calculate debate sizing impact
            debate_sizing_impact = realized_pnl - base_pnl
            
            # Calculate debate exit impact (if exit was debate-driven)
            debate_exit_impact = 0.0
            if exit_trade and exit_trade.exit_reason and "debate" in exit_trade.exit_reason.lower():
                # Estimate what the PnL would have been with a standard exit
                # This is simplified - in practice, you'd need more sophisticated modeling
                standard_exit_impact = realized_pnl * 0.1  # Assume 10% difference
                debate_exit_impact = standard_exit_impact
            
            # Total debate contribution
            total_debate_contribution = debate_sizing_impact + debate_exit_impact
            
            result = {
                "symbol": symbol,
                "entry_trade_id": entry_trade.trade_id,
                "exit_trade_id": exit_trade.trade_id if exit_trade else None,
                "holding_period_hours": holding_period_hours,
                "realized_pnl": realized_pnl,
                "base_pnl": base_pnl,
                "debate_sizing_impact": debate_sizing_impact,
                "debate_exit_impact": debate_exit_impact,
                "total_debate_contribution": total_debate_contribution,
                "debate_contribution_pct": (total_debate_contribution / abs(realized_pnl) * 100) if realized_pnl != 0 else 0,
                "agent_id": entry_trade.agent_id,
                "entry_debate_multiplier": entry_trade.debate_multiplier,
                "exit_debate_driven": exit_trade.exit_reason and "debate" in exit_trade.exit_reason.lower() if exit_trade else False
            }
            
            # Update trade records with attribution results
            entry_trade.realized_pnl = realized_pnl
            entry_trade.base_pnl = base_pnl
            entry_trade.debate_pnl_impact = debate_sizing_impact
            entry_trade.exit_pnl_impact = debate_exit_impact
            
            # Store attribution record in database if persistence is enabled
            if self.persistence_enabled:
                try:
                    # Get active config version for this attribution
                    active_configs = await self.db.get_active_config_versions(entry_trade.timestamp)
                    config_version = active_configs[0] if active_configs else None
                    
                    attribution_record = AttributionRecord(
                        symbol=symbol,
                        entry_trade_id=entry_trade.trade_id,
                        exit_trade_id=exit_trade.trade_id if exit_trade else None,
                        entry_timestamp=entry_trade.timestamp,
                        exit_timestamp=exit_trade.timestamp if exit_trade else None,
                        holding_period_hours=result["holding_period_hours"],
                        realized_pnl=realized_pnl,
                        base_pnl=base_pnl,
                        debate_sizing_impact=debate_sizing_impact,
                        debate_exit_impact=debate_exit_impact,
                        total_debate_contribution=total_debate_contribution,
                        debate_contribution_pct=result["debate_contribution_pct"],
                        agent_id=entry_trade.agent_id,
                        entry_debate_multiplier=entry_trade.debate_multiplier,
                        exit_debate_driven=result["exit_debate_driven"],
                        config_version=config_version
                    )
                    
                    await self.db.store_attribution_record(attribution_record)
                    
                except Exception as e:
                    logger.warning(f"Failed to store attribution record in database: {e}")
            
            # Track SLO for attribution calculation
            self.slo_monitor.track_slo(
                metric_name="debate.pnl_attribution.calculated",
                success=True,
                total=1,
                metadata={
                    "symbol": symbol,
                    "realized_pnl": realized_pnl,
                    "debate_contribution": total_debate_contribution,
                    "debate_contribution_pct": result["debate_contribution_pct"]
                }
            )
            
            return result
            
        except Exception as e:
            logger.error(f"Error calculating attribution for {symbol}: {e}")
            return {"error": str(e)}
    
    async def generate_attribution_summary(
        self,
        period_days: int = 30,
        agent_id: Optional[str] = None,
        symbol: Optional[str] = None
    ) -> AttributionSummary:
        """
        Generate PnL attribution summary for a period.
        
        Args:
            period_days: Number of days to analyze
            agent_id: Filter by agent (optional)
            symbol: Filter by symbol (optional)
            
        Returns:
            AttributionSummary with comprehensive metrics
        """
        try:
            cutoff_time = time.time() - (period_days * 24 * 3600)
            period_start = datetime.fromtimestamp(cutoff_time, timezone.utc)
            period_end = datetime.now(timezone.utc)
            
            # Filter trades for the period
            relevant_trades = [
                trade for trade in self.trade_records
                if trade.timestamp >= cutoff_time and
                (agent_id is None or trade.agent_id == agent_id) and
                (symbol is None or trade.symbol == symbol)
            ]
            
            if not relevant_trades:
                return AttributionSummary(
                    period_start=period_start,
                    period_end=period_end,
                    total_trades=0,
                    total_realized_pnl=0.0,
                    total_base_pnl=0.0,
                    total_debate_pnl_impact=0.0,
                    total_exit_pnl_impact=0.0,
                    debate_sizing_win_rate=0.0,
                    debate_exit_win_rate=0.0,
                    overall_debate_contribution_pct=0.0
                )
            
            # Group trades by symbol and calculate attribution
            symbol_trades = {}
            for trade in relevant_trades:
                if trade.symbol not in symbol_trades:
                    symbol_trades[trade.symbol] = []
                symbol_trades[trade.symbol].append(trade)
            
            # Calculate attribution for each symbol
            total_realized_pnl = 0.0
            total_base_pnl = 0.0
            total_debate_sizing_impact = 0.0
            total_debate_exit_impact = 0.0
            
            debate_sizing_wins = 0
            debate_sizing_total = 0
            debate_exit_wins = 0
            debate_exit_total = 0
            
            agent_contributions = {}
            tier_contributions = {}
            symbol_contributions = {}
            
            for symbol, trades in symbol_trades.items():
                # Find entry/exit pairs
                entry_trades = [t for t in trades if t.trade_type == TradeType.ENTRY]
                exit_trades = [t for t in trades if t.trade_type in [TradeType.EXIT, TradeType.TRIM]]
                
                for entry in entry_trades:
                    # Find corresponding exit
                    exit = next((e for e in exit_trades if e.timestamp > entry.timestamp), None)
                    
                    if exit or (time.time() - entry.timestamp) > 3600:  # At least 1 hour old
                        # Calculate attribution
                        attribution = await self.calculate_attribution(symbol, entry, exit)
                        
                        if "error" not in attribution:
                            total_realized_pnl += attribution["realized_pnl"]
                            total_base_pnl += attribution["base_pnl"]
                            total_debate_sizing_impact += attribution["debate_sizing_impact"]
                            total_debate_exit_impact += attribution["debate_exit_impact"]
                            
                            # Track wins
                            debate_sizing_total += 1
                            if attribution["debate_sizing_impact"] > 0:
                                debate_sizing_wins += 1
                            
                            if attribution["exit_debate_driven"]:
                                debate_exit_total += 1
                                if attribution["debate_exit_impact"] > 0:
                                    debate_exit_wins += 1
                            
                            # Agent contributions
                            agent = entry.agent_id or "unknown"
                            if agent not in agent_contributions:
                                agent_contributions[agent] = {
                                    "realized_pnl": 0.0,
                                    "debate_contribution": 0.0,
                                    "trade_count": 0
                                }
                            agent_contributions[agent]["realized_pnl"] += attribution["realized_pnl"]
                            agent_contributions[agent]["debate_contribution"] += attribution["total_debate_contribution"]
                            agent_contributions[agent]["trade_count"] += 1
                            
                            # Symbol contributions
                            if symbol not in symbol_contributions:
                                symbol_contributions[symbol] = {
                                    "realized_pnl": 0.0,
                                    "debate_contribution": 0.0,
                                    "trade_count": 0
                                }
                            symbol_contributions[symbol]["realized_pnl"] += attribution["realized_pnl"]
                            symbol_contributions[symbol]["debate_contribution"] += attribution["total_debate_contribution"]
                            symbol_contributions[symbol]["trade_count"] += 1
            
            # Calculate summary metrics
            total_debate_contribution = total_debate_sizing_impact + total_debate_exit_impact
            overall_debate_contribution_pct = (total_debate_contribution / abs(total_realized_pnl) * 100) if total_realized_pnl != 0 else 0
            
            debate_sizing_win_rate = (debate_sizing_wins / debate_sizing_total * 100) if debate_sizing_total > 0 else 0
            debate_exit_win_rate = (debate_exit_wins / debate_exit_total * 100) if debate_exit_total > 0 else 0
            
            summary = AttributionSummary(
                period_start=period_start,
                period_end=period_end,
                total_trades=len(relevant_trades),
                total_realized_pnl=total_realized_pnl,
                total_base_pnl=total_base_pnl,
                total_debate_pnl_impact=total_debate_sizing_impact,
                total_exit_pnl_impact=total_debate_exit_impact,
                debate_sizing_win_rate=debate_sizing_win_rate,
                debate_exit_win_rate=debate_exit_win_rate,
                overall_debate_contribution_pct=overall_debate_contribution_pct,
                agent_contributions=agent_contributions,
                tier_contributions=tier_contributions,
                symbol_contributions=symbol_contributions
            )
            
            # Store summary
            self.attribution_summaries.append(summary)
            if len(self.attribution_summaries) > self.max_summaries:
                self.attribution_summaries = self.attribution_summaries[-self.max_summaries:]
            
            # Store daily summary with config versions if persistence is enabled
            if self.persistence_enabled:
                try:
                    await self.db.update_daily_summary_with_configs(
                        datetime.now(timezone.utc).date(),
                        {
                            "total_trades": summary.total_trades,
                            "total_realized_pnl": summary.total_realized_pnl,
                            "total_base_pnl": summary.total_base_pnl,
                            "total_debate_contribution": summary.total_debate_pnl_impact + summary.total_exit_pnl_impact,
                            "debate_sizing_win_rate": summary.debate_sizing_win_rate,
                            "debate_exit_win_rate": summary.debate_exit_win_rate,
                            "debate_contribution_pct": summary.overall_debate_contribution_pct,
                            "top_agents": summary.agent_contributions,
                            "top_symbols": summary.symbol_contributions
                        }
                    )
                except Exception as e:
                    logger.warning(f"Failed to store daily summary: {e}")
            
            # Track SLO for summary generation
            self.slo_monitor.track_slo(
                metric_name="debate.pnl_attribution.summary_generated",
                success=True,
                total=1,
                metadata={
                    "period_days": period_days,
                    "total_trades": summary.total_trades,
                    "debate_contribution_pct": overall_debate_contribution_pct,
                    "debate_sizing_win_rate": debate_sizing_win_rate
                }
            )
            
            logger.info(
                f"Generated attribution summary: {summary.total_trades} trades, "
                f"debate contribution: {overall_debate_contribution_pct:.1f}%"
            )
            
            return summary
            
        except Exception as e:
            logger.error(f"Error generating attribution summary: {e}")
            # Return empty summary on error
            return AttributionSummary(
                period_start=datetime.fromtimestamp(time.time() - period_days * 24 * 3600, timezone.utc),
                period_end=datetime.now(timezone.utc),
                total_trades=0,
                total_realized_pnl=0.0,
                total_base_pnl=0.0,
                total_debate_pnl_impact=0.0,
                total_exit_pnl_impact=0.0,
                debate_sizing_win_rate=0.0,
                debate_exit_win_rate=0.0,
                overall_debate_contribution_pct=0.0
            )
    
    def get_attribution_dashboard(
        self,
        days_back: int = 30
    ) -> Dict[str, Any]:
        """Get dashboard-ready attribution data."""
        try:
            # Generate summary
            summary = asyncio.run(self.generate_attribution_summary(days_back))
            
            # Get recent trade activity
            cutoff_time = time.time() - (days_back * 24 * 3600)
            recent_trades = [
                trade for trade in self.trade_records
                if trade.timestamp >= cutoff_time
            ]
            
            # Calculate daily attribution
            daily_attributions = {}
            for trade in recent_trades:
                date = datetime.fromtimestamp(trade.timestamp, timezone.utc).date()
                if date not in daily_attributions:
                    daily_attributions[date] = {
                        "realized_pnl": 0.0,
                        "debate_contribution": 0.0,
                        "trade_count": 0
                    }
                
                if trade.realized_pnl is not None:
                    daily_attributions[date]["realized_pnl"] += trade.realized_pnl
                    daily_attributions[date]["debate_contribution"] += (trade.debate_pnl_impact or 0.0) + (trade.exit_pnl_impact or 0.0)
                    daily_attributions[date]["trade_count"] += 1
            
            # Convert to list for frontend
            daily_data = [
                {
                    "date": date.isoformat(),
                    "realized_pnl": data["realized_pnl"],
                    "debate_contribution": data["debate_contribution"],
                    "trade_count": data["trade_count"]
                }
                for date, data in sorted(daily_attributions.items())
            ]
            
            return {
                "summary": {
                    "period_days": days_back,
                    "total_trades": summary.total_trades,
                    "total_realized_pnl": summary.total_realized_pnl,
                    "total_base_pnl": summary.total_base_pnl,
                    "total_debate_contribution": summary.total_debate_pnl_impact + summary.total_exit_pnl_impact,
                    "debate_contribution_pct": summary.overall_debate_contribution_pct,
                    "debate_sizing_win_rate": summary.debate_sizing_win_rate,
                    "debate_exit_win_rate": summary.debate_exit_win_rate
                },
                "daily_data": daily_data,
                "top_agents": sorted(
                    summary.agent_contributions.items(),
                    key=lambda x: x[1]["debate_contribution"],
                    reverse=True
                )[:5],
                "top_symbols": sorted(
                    summary.symbol_contributions.items(),
                    key=lambda x: x[1]["debate_contribution"],
                    reverse=True
                )[:5]
            }
            
        except Exception as e:
            logger.error(f"Error getting attribution dashboard: {e}")
            return {"error": str(e)}
    
    def clear_trade_records(self, days_back: int = None):
        """Clear trade records (all or older than specified days)."""
        if days_back is None:
            self.trade_records.clear()
            logger.info("Cleared all trade records")
        else:
            cutoff_time = time.time() - (days_back * 24 * 3600)
            original_count = len(self.trade_records)
            self.trade_records = [t for t in self.trade_records if t.timestamp >= cutoff_time]
            removed_count = original_count - len(self.trade_records)
            logger.info(f"Cleared {removed_count} trade records older than {days_back} days")


# Global instance
_attribution_engine_instance: Optional[PnLAttributionEngine] = None


def get_pnl_attribution_engine() -> PnLAttributionEngine:
    """Get the global PnL attribution engine instance."""
    global _attribution_engine_instance
    if _attribution_engine_instance is None:
        _attribution_engine_instance = PnLAttributionEngine()
    return _attribution_engine_instance


async def record_debate_trade(
    symbol: str,
    trade_type: str,
    timestamp: float,
    price: float,
    quantity: int,
    trade_id: str,
    agent_id: Optional[str] = None,
    base_kelly_fraction: float = 0.0,
    debate_multiplier: float = 1.0,
    final_kelly_fraction: float = 0.0,
    debate_recommendation: Optional[str] = None,
    exit_reason: Optional[str] = None
):
    """
    Record a trade for PnL attribution.
    
    Args:
        symbol: Kalshi symbol
        trade_type: Type of trade (entry/exit/trim)
        timestamp: Trade timestamp
        price: Trade price
        quantity: Trade quantity
        trade_id: Unique trade identifier
        agent_id: Agent who made the trade
        base_kelly_fraction: Base Kelly fraction
        debate_multiplier: Debate multiplier applied
        final_kelly_fraction: Final Kelly fraction
        debate_recommendation: Debate recommendation
        exit_reason: Reason for exit (if applicable)
    """
    from merid.prediction.pnl_attribution import TradeType
    
    engine = get_pnl_attribution_engine()
    
    # Convert string to enum
    try:
        trade_type_enum = TradeType(trade_type.lower())
    except ValueError:
        logger.error(f"Invalid trade type: {trade_type}")
        return
    
    await engine.record_trade(
        symbol=symbol,
        trade_type=trade_type_enum,
        timestamp=timestamp,
        price=price,
        quantity=quantity,
        trade_id=trade_id,
        agent_id=agent_id,
        base_kelly_fraction=base_kelly_fraction,
        debate_multiplier=debate_multiplier,
        final_kelly_fraction=final_kelly_fraction,
        debate_recommendation=debate_recommendation,
        exit_reason=exit_reason
    )
