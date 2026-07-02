"""
Pipeline Configuration Schema for 15m Execution Shell

Defines the YAML schema for 15m feature graph pipelines.
Ensures only 15m execution agents can trade, everything else is features.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from enum import Enum


class AgentRole(str, Enum):
    """Agent roles in the pipeline."""
    FEATURE = "feature"
    EXECUTION = "execution"
    RISK = "risk"
    RESEARCH = "research"


class FeatureNamespace(str, Enum):
    """Feature namespaces for categorization."""
    SENTIMENT = "sentiment"
    MICROSTRUCTURE = "microstructure"
    REGIME = "regime"
    MACRO = "macro"
    VOLATILITY = "volatility"
    GENERAL = "general"


@dataclass
class FeatureAgentConfig:
    """Configuration for a feature-producing agent."""
    name: str
    role: AgentRole = AgentRole.FEATURE
    feature_namespace: Optional[FeatureNamespace] = None
    enabled: bool = True
    # Optional: restrict to specific assets
    assets: List[str] = field(default_factory=list)


@dataclass
class ExecutionAgentConfig:
    """Configuration for the 15m execution agent."""
    name: str
    asset: str
    role: AgentRole = AgentRole.EXECUTION
    timeframe: str = "15m"
    # Guardrail: must be one of the target assets
    allowed_assets: List[str] = field(default_factory=lambda: ["BTC", "ETH", "SOL", "XRP", "DOGE"])


@dataclass
class ExecutorConfig:
    """Configuration for the Kalshi trading executor."""
    series_ticker: str  # e.g., "KXBTC", "KXETH"
    executor_type: str = "kalshi_trading_agent"


@dataclass
class PipelineConfig:
    """
    Complete 15m pipeline configuration.
    
    Defines the feature graph: which agents produce features,
    which agent makes the decision, and which executor handles orders.
    """
    
    pipeline_id: str
    asset: str
    timeframe: str = "15m"
    enabled: bool = True
    
    # Feature-producing agents (multi-tf, sentiment, macro, etc.)
    feature_agents: List[FeatureAgentConfig] = field(default_factory=list)
    
    # The 15m decision agent (only one allowed)
    decision_agent: ExecutionAgentConfig = None
    
    # The Kalshi executor
    executor: ExecutorConfig = None
    
    # Risk agents (optional, can veto)
    risk_agents: List[str] = field(default_factory=list)
    
    # Pipeline-level settings
    max_feature_age_seconds: int = 60  # Features older than this are stale
    require_all_features: bool = False  # If False, proceed with partial features
    
    # Guardrail metadata
    version: str = "1.0"
    description: str = ""
    
    def validate(self) -> tuple[bool, List[str]]:
        """
        Validate pipeline configuration against guardrails.
        
        Returns (is_valid, error_messages).
        """
        errors = []
        
        # Check asset is allowed
        allowed_assets = {"BTC", "ETH", "SOL", "XRP", "DOGE"}
        if self.asset not in allowed_assets:
            errors.append(f"Invalid asset '{self.asset}'. Must be one of: {allowed_assets}")
        
        # Check timeframe is 15m
        if self.timeframe != "15m":
            errors.append(f"Invalid timeframe '{self.timeframe}'. Must be '15m'")
        
        # Check decision agent exists and is execution role
        if not self.decision_agent:
            errors.append("Missing decision_agent")
        else:
            if self.decision_agent.role != AgentRole.EXECUTION:
                errors.append(f"decision_agent must have role=execution, got {self.decision_agent.role}")
            
            if self.decision_agent.asset != self.asset:
                errors.append(f"decision_agent asset '{self.decision_agent.asset}' must match pipeline asset '{self.asset}'")
            
            if self.decision_agent.timeframe != "15m":
                errors.append(f"decision_agent timeframe must be '15m', got '{self.decision_agent.timeframe}'")
        
        # Check executor exists
        if not self.executor:
            errors.append("Missing executor")
        
        # Check feature agents are all role=feature
        for fa in self.feature_agents:
            if fa.role != AgentRole.FEATURE:
                errors.append(f"feature_agent '{fa.name}' must have role=feature, got {fa.role}")
            
            # Check asset alignment (feature agents can be broader, but warn if mismatch)
            if fa.assets and self.asset not in fa.assets and "CRYPTO" not in fa.assets:
                # Allow broader categories like "CRYPTO" but warn on specific mismatches
                pass  # Could add warning here
        
        # Check no execution agents in feature_agents list
        for fa in self.feature_agents:
            if fa.role == AgentRole.EXECUTION:
                errors.append(f"feature_agent '{fa.name}' has role=execution - execution agents cannot be feature producers")
        
        # Check risk agents (if any) have role=risk
        # Note: risk_agents is just a list of names, validation happens at runtime
        
        return len(errors) == 0, errors


@dataclass
class PipelineRegistry:
    """
    Registry of all 15m pipelines.
    
    Loads from YAML config and provides validation.
    """
    pipelines: Dict[str, PipelineConfig] = field(default_factory=dict)
    
    def add_pipeline(self, pipeline: PipelineConfig) -> None:
        """Add a pipeline to the registry."""
        self.pipelines[pipeline.pipeline_id] = pipeline
    
    def get_pipeline(self, pipeline_id: str) -> Optional[PipelineConfig]:
        """Get a pipeline by ID."""
        return self.pipelines.get(pipeline_id)
    
    def get_pipelines_for_asset(self, asset: str) -> List[PipelineConfig]:
        """Get all pipelines for a specific asset."""
        return [p for p in self.pipelines.values() if p.asset == asset]
    
    def validate_all(self) -> tuple[bool, Dict[str, List[str]]]:
        """
        Validate all pipelines in the registry.
        
        Returns (all_valid, {pipeline_id: [errors]}).
        """
        all_valid = True
        errors_by_pipeline = {}
        
        for pipeline_id, pipeline in self.pipelines.items():
            is_valid, errors = pipeline.validate()
            if not is_valid:
                all_valid = False
                errors_by_pipeline[pipeline_id] = errors
        
        return all_valid, errors_by_pipeline
    
    def summary(self) -> Dict[str, Any]:
        """Get summary of pipeline registry."""
        return {
            "total_pipelines": len(self.pipelines),
            "enabled_pipelines": sum(1 for p in self.pipelines.values() if p.enabled),
            "by_asset": {
                asset: len(self.get_pipelines_for_asset(asset))
                for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]
            },
            "pipeline_ids": list(self.pipelines.keys()),
        }
