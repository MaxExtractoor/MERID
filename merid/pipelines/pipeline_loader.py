"""
Pipeline Configuration Loader

Loads and parses 15m pipeline YAML configurations.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional

import yaml

from merid.pipelines.pipeline_schema import (
    PipelineConfig,
    PipelineRegistry,
    FeatureAgentConfig,
    ExecutionAgentConfig,
    ExecutorConfig,
    AgentRole,
    FeatureNamespace,
)
from utils.logger import get_logger

logger = get_logger("merid.pipelines.pipeline_loader")


def _parse_feature_agent(raw: Dict) -> FeatureAgentConfig:
    """Parse a feature agent config from YAML."""
    role_str = raw.get("role", "feature")
    try:
        role = AgentRole(role_str.lower())
    except ValueError:
        logger.warning(f"Invalid role '{role_str}' for agent {raw.get('name')}, defaulting to FEATURE")
        role = AgentRole.FEATURE
    
    namespace_str = raw.get("feature_namespace")
    feature_namespace = None
    if namespace_str:
        try:
            feature_namespace = FeatureNamespace(namespace_str.lower())
        except ValueError:
            logger.warning(f"Invalid feature_namespace '{namespace_str}' for agent {raw.get('name')}")
    
    return FeatureAgentConfig(
        name=raw["name"],
        role=role,
        feature_namespace=feature_namespace,
        enabled=raw.get("enabled", True),
        assets=raw.get("assets", []),
    )


def _parse_execution_agent(raw: Dict) -> ExecutionAgentConfig:
    """Parse an execution agent config from YAML."""
    role_str = raw.get("role", "execution")
    try:
        role = AgentRole(role_str.lower())
    except ValueError:
        logger.warning(f"Invalid role '{role_str}' for execution agent, defaulting to EXECUTION")
        role = AgentRole.EXECUTION
    
    return ExecutionAgentConfig(
        name=raw["name"],
        role=role,
        asset=raw.get("asset", ""),
        timeframe=raw.get("timeframe", "15m"),
        allowed_assets=raw.get("allowed_assets", ["BTC", "ETH", "SOL", "XRP", "DOGE"]),
    )


def _parse_executor(raw: Dict) -> ExecutorConfig:
    """Parse an executor config from YAML."""
    return ExecutorConfig(
        series_ticker=raw["series_ticker"],
        executor_type=raw.get("executor_type", "kalshi_trading_agent"),
    )


def _parse_pipeline(raw: Dict) -> PipelineConfig:
    """Parse a pipeline config from YAML."""
    feature_agents = [
        _parse_feature_agent(fa) for fa in raw.get("feature_agents", [])
    ]
    
    decision_agent_raw = raw.get("decision_agent")
    decision_agent = None
    if decision_agent_raw:
        decision_agent = _parse_execution_agent(decision_agent_raw)
    
    executor_raw = raw.get("executor")
    executor = None
    if executor_raw:
        executor = _parse_executor(executor_raw)
    
    return PipelineConfig(
        pipeline_id=raw["pipeline_id"],
        asset=raw["asset"],
        timeframe=raw.get("timeframe", "15m"),
        enabled=raw.get("enabled", True),
        feature_agents=feature_agents,
        decision_agent=decision_agent,
        executor=executor,
        risk_agents=raw.get("risk_agents", []),
        max_feature_age_seconds=raw.get("max_feature_age_seconds", 60),
        require_all_features=raw.get("require_all_features", False),
        version=raw.get("version", "1.0"),
        description=raw.get("description", ""),
    )


def load_pipeline_config(config_path: str) -> PipelineRegistry:
    """
    Load pipeline configurations from a YAML file.
    
    Args:
        config_path: Path to the YAML config file
        
    Returns:
        PipelineRegistry with all loaded pipelines
    """
    config_file = Path(config_path)
    
    if not config_file.exists():
        logger.error(f"Pipeline config not found at {config_path}")
        return PipelineRegistry()
    
    with open(config_file, 'r') as f:
        raw = yaml.safe_load(f)
    
    if not raw:
        logger.warning(f"Empty pipeline config at {config_path}")
        return PipelineRegistry()
    
    registry = PipelineRegistry()
    
    pipelines_raw = raw.get("pipelines", [])
    for pipeline_raw in pipelines_raw:
        try:
            pipeline = _parse_pipeline(pipeline_raw)
            registry.add_pipeline(pipeline)
            logger.info(f"Loaded pipeline: {pipeline.pipeline_id} (asset={pipeline.asset}, enabled={pipeline.enabled})")
        except Exception as e:
            logger.error(f"Failed to parse pipeline {pipeline_raw.get('pipeline_id', 'unknown')}: {e}")
    
    # Validate all pipelines
    all_valid, errors_by_pipeline = registry.validate_all()
    if not all_valid:
        logger.error("Pipeline validation errors:")
        for pipeline_id, errors in errors_by_pipeline.items():
            logger.error(f"  {pipeline_id}:")
            for error in errors:
                logger.error(f"    - {error}")
    else:
        logger.info(f"All {len(registry.pipelines)} pipelines validated successfully")
    
    return registry


def get_default_pipeline_config_path() -> str:
    """Get the default path to the pipeline config file."""
    repo_root = Path(__file__).parent.parent.parent
    return str(repo_root / "config" / "kalshi_15m_pipelines.yaml")
