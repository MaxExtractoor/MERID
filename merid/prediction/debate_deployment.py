"""
Debate Deployment Configuration and Canary Management
Controls rollout modes and canary symbol sets for safe deployment.
"""

import time
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, Set
from dataclasses import dataclass, field
from enum import Enum
import logging
import asyncio
import json

from core.slo_monitor import SLOMonitor

logger = logging.getLogger("merid.prediction.debate_deployment")


class DebateMode(Enum):
    """Debate system deployment modes."""
    OFF = "off"          # All debate features disabled
    CANARY = "canary"    # Enabled only for canary symbols
    FULL = "full"        # Enabled globally


@dataclass
class CanaryConfig:
    """Configuration for canary deployment."""
    enabled_symbols: Set[str] = field(default_factory=set)
    mode: DebateMode = DebateMode.OFF
    kill_switch_active: bool = False
    last_updated: float = field(default_factory=time.time)
    updated_by: Optional[str] = None
    update_reason: Optional[str] = None


@dataclass
class ShadowRecommendation:
    """Shadow recommendation logged but not acted upon."""
    symbol: str
    timestamp: float
    base_kelly: float
    debate_multiplier: float
    agent_id: Optional[str]
    reason: str
    would_adjust: bool


class DebateDeploymentManager:
    """Manages debate system deployment modes and canary configuration."""
    
    def __init__(self):
        self.slo_monitor = SLOMonitor.get_instance()
        self.config = CanaryConfig()
        self.shadow_recommendations: List[ShadowRecommendation] = []
        self.max_shadow_recommendations = 10000
        
        # Default canary symbols (liquid, representative Kalshi markets)
        self.default_canary_symbols = {
            "KXBTCD-25JUN-T100000",  # Bitcoin
            "KETHCD-25JUN-T5000",    # Ethereum
            "KSP500-25JUN-T5000",    # S&P 500
            "KNDAQ-25JUN-T100",      # NASDAQ
            "KGOLD-25JUN-T1950",     # Gold
            "KOIL-25JUN-T85",        # Oil
            "KUSD-25JUN-T10100",     # USD
            "KEUR-25JUN-T10800",     # EUR
            "KGBP-25JUN-T12700",     # GBP
            "KJPY-25JUN-T7500",      # JPY
        }
        
        self.last_config_save = 0.0
        self.config_save_interval = 300  # Save config every 5 minutes
    
    def is_debate_enabled(self, symbol: str = None) -> bool:
        """
        Check if debate features are enabled for a symbol.
        
        Args:
            symbol: Kalshi symbol (optional)
            
        Returns:
            True if debate features are enabled
        """
        # Check kill switch first
        if self.config.kill_switch_active:
            return False
        
        # Check deployment mode
        if self.config.mode == DebateMode.OFF:
            return False
        
        if self.config.mode == DebateMode.FULL:
            return True
        
        # Canary mode - check if symbol is in canary set
        if self.config.mode == DebateMode.CANARY:
            return symbol in self.config.enabled_symbols
        
        return False
    
    def get_effective_multiplier(self, symbol: str, debate_multiplier: float) -> float:
        """
        Get the effective multiplier based on deployment mode.
        
        Args:
            symbol: Kalshi symbol
            debate_multiplier: Calculated debate multiplier
            
        Returns:
            Effective multiplier (1.0 if disabled)
        """
        if not self.is_debate_enabled(symbol):
            return 1.0
        
        return debate_multiplier
    
    def should_log_shadow_recommendation(self, symbol: str) -> bool:
        """
        Check if we should log a shadow recommendation for this symbol.
        
        Args:
            symbol: Kalshi symbol
            
        Returns:
            True if shadow recommendation should be logged
        """
        # Log shadow recommendations when:
        # - System is OFF (log everything)
        # - System is CANARY and symbol is NOT in canary set
        # - System is FULL (never log shadows, everything is live)
        
        if self.config.mode == DebateMode.OFF:
            return True
        
        if self.config.mode == DebateMode.CANARY and symbol not in self.config.enabled_symbols:
            return True
        
        return False
    
    def log_shadow_recommendation(
        self,
        symbol: str,
        base_kelly: float,
        debate_multiplier: float,
        agent_id: Optional[str] = None,
        reason: str = "Debate recommendation"
    ):
        """Log a shadow recommendation that wasn't acted upon."""
        try:
            recommendation = ShadowRecommendation(
                symbol=symbol,
                timestamp=time.time(),
                base_kelly=base_kelly,
                debate_multiplier=debate_multiplier,
                agent_id=agent_id,
                reason=reason,
                would_adjust=debate_multiplier != 1.0
            )
            
            self.shadow_recommendations.append(recommendation)
            
            # Trim if too many
            if len(self.shadow_recommendations) > self.max_shadow_recommendations:
                self.shadow_recommendations = self.shadow_recommendations[-self.max_shadow_recommendations:]
            
            # Track SLO for shadow recommendations
            self.slo_monitor.track_slo(
                metric_name="debate.deployment.shadow_recommendation",
                success=True,
                total=1,
                metadata={
                    "symbol": symbol,
                    "mode": self.config.mode.value,
                    "base_kelly": base_kelly,
                    "debate_multiplier": debate_multiplier,
                    "would_adjust": recommendation.would_adjust,
                    "agent_id": agent_id
                }
            )
            
            logger.debug(f"Shadow recommendation logged for {symbol}: {debate_multiplier:.2f}x")
            
        except Exception as e:
            logger.error(f"Error logging shadow recommendation for {symbol}: {e}")
    
    def set_deployment_mode(
        self,
        mode: DebateMode,
        updated_by: str,
        reason: str = None,
        canary_symbols: Optional[List[str]] = None
    ):
        """
        Set the deployment mode.
        
        Args:
            mode: New deployment mode
            updated_by: Who made the change
            reason: Reason for the change
            canary_symbols: Canary symbols (required for CANARY mode)
        """
        try:
            old_mode = self.config.mode
            
            # Validate canary symbols for CANARY mode
            if mode == DebateMode.CANARY:
                if not canary_symbols:
                    canary_symbols = list(self.default_canary_symbols)
                self.config.enabled_symbols = set(canary_symbols)
                
                logger.info(f"Set canary symbols: {len(canary_symbols)} markets")
            elif mode == DebateMode.FULL:
                self.config.enabled_symbols.clear()
            elif mode == DebateMode.OFF:
                self.config.enabled_symbols.clear()
            
            self.config.mode = mode
            self.config.last_updated = time.time()
            self.config.updated_by = updated_by
            self.config.update_reason = reason
            
            # Track SLO for mode changes
            self.slo_monitor.track_slo(
                metric_name="debate.deployment.mode_change",
                success=True,
                total=1,
                metadata={
                    "old_mode": old_mode.value,
                    "new_mode": mode.value,
                    "updated_by": updated_by,
                    "reason": reason,
                    "canary_symbols_count": len(self.config.enabled_symbols),
                    "kill_switch_active": self.config.kill_switch_active
                }
            )
            
            logger.warning(
                f"Debate deployment mode changed: {old_mode.value} → {mode.value} "
                f"by {updated_by} (reason: {reason})"
            )
            
        except Exception as e:
            logger.error(f"Error setting deployment mode: {e}")
            raise
    
    def toggle_kill_switch(self, activated: bool, updated_by: str, reason: str = None):
        """
        Toggle the global kill switch.
        
        Args:
            activated: Whether to activate the kill switch
            updated_by: Who made the change
            reason: Reason for the change
        """
        try:
            old_state = self.config.kill_switch_active
            self.config.kill_switch_active = activated
            self.config.last_updated = time.time()
            self.config.updated_by = updated_by
            self.config.update_reason = reason
            
            # Track SLO for kill switch changes
            self.slo_monitor.track_slo(
                metric_name="debate.deployment.kill_switch_toggle",
                success=True,
                total=1,
                metadata={
                    "old_state": old_state,
                    "new_state": activated,
                    "updated_by": updated_by,
                    "reason": reason,
                    "mode": self.config.mode.value
                }
            )
            
            logger.critical(
                f"Debate kill switch {'ACTIVATED' if activated else 'DEACTIVATED'} "
                f"by {updated_by} (reason: {reason})"
            )
            
        except Exception as e:
            logger.error(f"Error toggling kill switch: {e}")
            raise
    
    def update_canary_symbols(self, symbols: List[str], updated_by: str, reason: str = None):
        """
        Update the canary symbol set.
        
        Args:
            symbols: New canary symbols list
            updated_by: Who made the change
            reason: Reason for the change
        """
        try:
            old_symbols = self.config.enabled_symbols.copy()
            self.config.enabled_symbols = set(symbols)
            self.config.last_updated = time.time()
            self.config.updated_by = updated_by
            self.config.update_reason = reason
            
            # Track SLO for canary symbol changes
            self.slo_monitor.track_slo(
                metric_name="debate.deployment.canary_symbols_update",
                success=True,
                total=1,
                metadata={
                    "old_count": len(old_symbols),
                    "new_count": len(symbols),
                    "updated_by": updated_by,
                    "reason": reason,
                    "added": list(set(symbols) - old_symbols),
                    "removed": list(old_symbols - set(symbols))
                }
            )
            
            logger.info(
                f"Canary symbols updated by {updated_by}: {len(old_symbols)} → {len(symbols)} symbols"
            )
            
        except Exception as e:
            logger.error(f"Error updating canary symbols: {e}")
            raise
    
    def get_deployment_status(self) -> Dict[str, Any]:
        """Get current deployment status."""
        return {
            "mode": self.config.mode.value,
            "kill_switch_active": self.config.kill_switch_active,
            "canary_symbols": list(self.config.enabled_symbols) if self.config.mode == DebateMode.CANARY else [],
            "canary_symbols_count": len(self.config.enabled_symbols),
            "last_updated": datetime.fromtimestamp(self.config.last_updated, timezone.utc).isoformat(),
            "updated_by": self.config.updated_by,
            "update_reason": self.config.update_reason,
            "shadow_recommendations_count": len(self.shadow_recommendations),
            "is_debate_enabled_globally": self.is_debate_enabled()
        }
    
    def get_shadow_recommendations(self, hours_back: int = 24) -> Dict[str, Any]:
        """Get shadow recommendations for analysis."""
        cutoff_time = time.time() - (hours_back * 3600)
        recent_recommendations = [
            rec for rec in self.shadow_recommendations
            if rec.timestamp >= cutoff_time
        ]
        
        if not recent_recommendations:
            return {"message": "No shadow recommendations in specified period"}
        
        # Analyze shadow recommendations
        total_recommendations = len(recent_recommendations)
        adjustments = sum(1 for rec in recent_recommendations if rec.would_adjust)
        
        # Group by symbol
        symbol_counts = {}
        for rec in recent_recommendations:
            symbol_counts[rec.symbol] = symbol_counts.get(rec.symbol, 0) + 1
        
        # Group by agent
        agent_counts = {}
        for rec in recent_recommendations:
            agent = rec.agent_id or "unknown"
            agent_counts[agent] = agent_counts.get(agent, 0) + 1
        
        return {
            "period_hours": hours_back,
            "total_recommendations": total_recommendations,
            "adjustment_rate": adjustments / total_recommendations if total_recommendations > 0 else 0,
            "top_symbols": sorted(symbol_counts.items(), key=lambda x: x[1], reverse=True)[:10],
            "top_agents": sorted(agent_counts.items(), key=lambda x: x[1], reverse=True)[:10],
            "recommendations": [
                {
                    "symbol": rec.symbol,
                    "timestamp": datetime.fromtimestamp(rec.timestamp, timezone.utc).isoformat(),
                    "base_kelly": rec.base_kelly,
                    "debate_multiplier": rec.debate_multiplier,
                    "agent_id": rec.agent_id,
                    "reason": rec.reason,
                    "would_adjust": rec.would_adjust
                }
                for rec in recent_recommendations[-50:]  # Last 50 recommendations
            ]
        }
    
    def clear_shadow_recommendations(self):
        """Clear all shadow recommendations."""
        self.shadow_recommendations.clear()
        logger.info("Cleared all shadow recommendations")
    
    def save_config(self):
        """Save configuration to persistent storage."""
        try:
            # This would save to your preferred storage (Redis, file, DB)
            # For now, we'll just log that it would be saved
            config_data = {
                "mode": self.config.mode.value,
                "kill_switch_active": self.config.kill_switch_active,
                "enabled_symbols": list(self.config.enabled_symbols),
                "last_updated": self.config.last_updated,
                "updated_by": self.config.updated_by,
                "update_reason": self.config.update_reason
            }
            
            logger.info(f"Would save deployment config: {json.dumps(config_data, indent=2)}")
            self.last_config_save = time.time()
            
        except Exception as e:
            logger.error(f"Error saving deployment config: {e}")
    
    def load_config(self):
        """Load configuration from persistent storage."""
        try:
            # This would load from your preferred storage
            # For now, we'll use defaults
            logger.info("Loaded deployment config (using defaults)")
            
        except Exception as e:
            logger.error(f"Error loading deployment config: {e}")
            # Use defaults if loading fails
            self.config = CanaryConfig()


# Global instance
_deployment_manager_instance: Optional[DebateDeploymentManager] = None


def get_debate_deployment_manager() -> DebateDeploymentManager:
    """Get the global debate deployment manager instance."""
    global _deployment_manager_instance
    if _deployment_manager_instance is None:
        _deployment_manager_instance = DebateDeploymentManager()
    return _deployment_manager_instance


def is_debate_enabled(symbol: str = None) -> bool:
    """
    Check if debate features are enabled for a symbol.
    
    Args:
        symbol: Kalshi symbol (optional)
        
    Returns:
        True if debate features are enabled
    """
    manager = get_debate_deployment_manager()
    return manager.is_debate_enabled(symbol)


def get_effective_multiplier(symbol: str, debate_multiplier: float) -> float:
    """
    Get the effective multiplier based on deployment mode.
    
    Args:
        symbol: Kalshi symbol
        debate_multiplier: Calculated debate multiplier
        
    Returns:
        Effective multiplier (1.0 if disabled)
    """
    manager = get_debate_deployment_manager()
    return manager.get_effective_multiplier(symbol, debate_multiplier)


def should_log_shadow_recommendation(symbol: str) -> bool:
    """
    Check if we should log a shadow recommendation for this symbol.
    
    Args:
        symbol: Kalshi symbol
        
    Returns:
        True if shadow recommendation should be logged
    """
    manager = get_debate_deployment_manager()
    return manager.should_log_shadow_recommendation(symbol)
