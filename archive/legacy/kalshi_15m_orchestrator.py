# LEGACY / DEMO: Not used by kalshi_crypto_15m_v2 15m stack.
# Do not import from 15m code paths.
# This module is archived and superseded by Kalshi15mLoop in loop_15m.py.

"""
15m Kalshi Pipeline Orchestrator

Orchestrates the feature graph execution for 15m crypto trading.
Ensures only 15m execution agents can place orders.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from merid.pipelines.feature_bundle import (
    FifteenMinuteFeatureBundle,
    FeatureDict,
    TradeDecision,
)
from merid.pipelines.pipeline_schema import (
    PipelineConfig,
    PipelineRegistry,
    AgentRole,
)
from merid.pipelines.pre_trade_risk import PreTradeRiskChecker
from merid.pipelines.observability import PipelineObservability
from utils.logger import get_logger

logger = get_logger("merid.pipelines.kalshi_15m_orchestrator")


class FeatureAgentInvoker:
    """Invokes feature-producing agents and normalizes their outputs."""
    
    def __init__(self, agent_registry: Dict[str, Any]):
        self.agent_registry = agent_registry
    
    async def invoke_feature_agent(
        self,
        agent_name: str,
        asset: str,
        context: Dict[str, Any],
    ) -> FeatureDict:
        """
        Invoke a feature agent and return normalized features.
        
        Args:
            agent_name: Name of the feature agent
            asset: Target asset (BTC, ETH, etc.)
            context: Execution context with market data
            
        Returns:
            FeatureDict with the agent's output
        """
        # Get agent from registry
        agent = self.agent_registry.get(agent_name)
        if not agent:
            logger.warning(f"Feature agent not found: {agent_name}")
            return FeatureDict(source_agent=agent_name, features={})
        
        # Check role is feature (guardrail)
        agent_role = getattr(agent, "role", "")
        if agent_role != "feature":
            logger.error(
                f"Guardrail violation: Agent {agent_name} has role={agent_role}, "
                f"but is being invoked as a feature producer"
            )
            return FeatureDict(source_agent=agent_name, features={})
        
        try:
            # Invoke agent (assuming async run method)
            if hasattr(agent, "run"):
                result = await agent.run(context)
            elif hasattr(agent, "_execute"):
                result = await agent._execute(context)
            else:
                logger.warning(f"Agent {agent_name} has no run/_execute method")
                return FeatureDict(source_agent=agent_name, features={})
            
            # Normalize output to FeatureDict
            if isinstance(result, dict):
                features = {k: float(v) for k, v in result.items() if isinstance(v, (int, float))}
            elif hasattr(result, "to_dict"):
                features = result.to_dict()
            else:
                logger.warning(f"Agent {agent_name} returned unsupported type: {type(result)}")
                features = {}
            
            return FeatureDict(
                features=features,
                timestamp=datetime.utcnow(),
                source_agent=agent_name,
                confidence=features.get("confidence", 1.0),
            )
        
        except Exception as e:
            logger.error(f"Error invoking feature agent {agent_name}: {e}")
            return FeatureDict(source_agent=agent_name, features={})


class Kalshi15mOrchestrator:
    """
    Orchestrator for 15m Kalshi trading pipelines.
    
    Runs on 15m schedule per asset:
    1. Queries all feature-producing agents
    2. Normalizes outputs into FifteenMinuteFeatureBundle
    3. Calls the 15m execution agent with the bundle
    4. Runs pre-trade risk checks
    5. Hands decision to KalshiTradingAgent
    """
    
    def __init__(
        self,
        pipeline_registry: PipelineRegistry,
        agent_registry: Dict[str, Any],
        risk_checker: Optional[PreTradeRiskChecker] = None,
        observability: Optional[PipelineObservability] = None,
    ):
        self.pipeline_registry = pipeline_registry
        self.agent_registry = agent_registry
        self.feature_invoker = FeatureAgentInvoker(agent_registry)
        self.risk_checker = risk_checker or PreTradeRiskChecker()
        self.observability = observability or PipelineObservability()
    
    async def run_pipeline(
        self,
        pipeline_id: str,
        context: Dict[str, Any],
        account_state: Optional[Dict[str, Any]] = None,
    ) -> Optional[TradeDecision]:
        """
        Run a single 15m pipeline with observability and risk checking.
        
        Args:
            pipeline_id: Pipeline identifier
            context: Execution context with market data
            account_state: Current account state for risk checks
            
        Returns:
            TradeDecision if generated, None otherwise
        """
        pipeline = self.pipeline_registry.get_pipeline(pipeline_id)
        if not pipeline:
            logger.error(f"Pipeline not found: {pipeline_id}")
            return None
        
        if not pipeline.enabled:
            logger.debug(f"Pipeline disabled: {pipeline_id}")
            return None
        
        logger.info(f"Running pipeline: {pipeline_id} (asset={pipeline.asset})")
        
        # Start observability trace
        trace = self.observability.start_trace(
            asset=pipeline.asset,
            timeframe=pipeline.timeframe,
            pipeline_id=pipeline_id,
        )
        
        try:
            # Build feature bundle
            start_time = time.time()
            bundle = await self._build_feature_bundle(pipeline, context)
            trace.feature_build_ms = (time.time() - start_time) * 1000
            
            # Log feature bundle to trace
            self.observability.log_feature_bundle(trace, bundle)
            
            # Call execution agent
            start_time = time.time()
            decision = await self._call_execution_agent(pipeline, bundle, context)
            trace.decision_ms = (time.time() - start_time) * 1000
            
            if decision:
                # Validate guardrails before execution
                is_valid, error = decision.validate_guardrails()
                if not is_valid:
                    logger.error(f"Guardrail violation in decision: {error}")
                    trace.execution_success = False
                    trace.execution_error = error
                    self.observability.finalize_trace(trace)
                    return None
                
                # Attach pipeline metadata and observability data
                decision.pipeline_id = pipeline_id
                decision.decision_agent = pipeline.decision_agent.name
                decision.feature_summary = {
                    ns: summary.to_dict()
                    for ns, summary in trace.feature_summaries.items()
                }
                decision.feature_time_window = trace.feature_time_window
                decision.features_fingerprint = trace.features_fingerprint
                
                # Log decision to trace
                self.observability.log_decision(trace, decision)
                
                # Run pre-trade risk checks
                start_time = time.time()
                account_state = account_state or {}
                risk_result = self.risk_checker.check_decision(decision, account_state)
                trace.risk_check_ms = (time.time() - start_time) * 1000
                
                # Log risk check to trace
                self.observability.log_risk_checks(trace, [risk_result], risk_result.passed)
                
                if not risk_result.passed:
                    logger.warning(
                        f"Pre-trade risk check failed: {risk_result.reason}"
                    )
                    # Apply size adjustment if provided
                    if risk_result.adjusted_size_pct is not None:
                        decision.size_pct = risk_result.adjusted_size_pct
                        logger.info(
                            f"Adjusted size to {decision.size_pct:.3f} due to risk check"
                        )
                    else:
                        # Veto the trade
                        self.observability.finalize_trace(trace)
                        return None
                
                logger.info(
                    f"Pipeline {pipeline_id} generated decision: {decision.side} "
                    f"(confidence={decision.confidence:.3f}, edge={decision.edge_estimate:.3f}, "
                    f"size_pct={decision.size_pct:.3f})"
                )
            
            self.observability.finalize_trace(trace)
            return decision
        
        except Exception as e:
            logger.error(f"Pipeline run error: {e}")
            trace.execution_success = False
            trace.execution_error = str(e)
            self.observability.finalize_trace(trace)
            return None
    
    async def _build_feature_bundle(
        self,
        pipeline: PipelineConfig,
        context: Dict[str, Any],
    ) -> FifteenMinuteFeatureBundle:
        """
        Build the feature bundle by invoking all feature agents.
        
        Args:
            pipeline: Pipeline configuration
            context: Execution context
            
        Returns:
            FifteenMinuteFeatureBundle with all features
        """
        bundle = FifteenMinuteFeatureBundle(
            asset=pipeline.asset,
            timestamp=datetime.utcnow(),
        )
        
        # Invoke feature agents in parallel
        tasks = []
        for fa in pipeline.feature_agents:
            if not fa.enabled:
                continue
            
            task = self.feature_invoker.invoke_feature_agent(
                fa.name,
                pipeline.asset,
                context,
            )
            tasks.append(task)
        
        feature_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Map feature results to bundle namespaces
        for fa, result in zip(pipeline.feature_agents, feature_results):
            if isinstance(result, Exception):
                logger.error(f"Feature agent {fa.name} failed: {result}")
                continue
            
            if not isinstance(result, FeatureDict):
                continue
            
            # Map to namespace based on feature_namespace or agent name
            namespace = self._map_agent_to_namespace(fa, result)
            
            # Merge features into the appropriate namespace
            if namespace == "sentiment":
                bundle.sentiment.features.update(result.features)
            elif namespace == "microstructure":
                bundle.ts_lower_tf.features.update(result.features)
            elif namespace == "regime":
                bundle.ts_higher_tf.features.update(result.features)
            elif namespace == "macro":
                bundle.macro.features.update(result.features)
            elif namespace == "volatility":
                bundle.volatility.features.update(result.features)
            elif namespace == "confidence":
                bundle.confidence_signals.features.update(result.features)
            else:
                # Default to ts_15m for native 15m features
                bundle.ts_15m.features.update(result.features)
        
        logger.debug(
            f"Built feature bundle for {pipeline.asset}: "
            f"ts_15m={len(bundle.ts_15m.features)}, "
            f"sentiment={len(bundle.sentiment.features)}, "
            f"regime={len(bundle.ts_higher_tf.features)}"
        )
        
        return bundle
    
    def _map_agent_to_namespace(
        self,
        fa_config: Any,
        result: FeatureDict,
    ) -> str:
        """Map a feature agent to its bundle namespace."""
        # If agent has explicit feature_namespace, use it
        if hasattr(fa_config, "feature_namespace") and fa_config.feature_namespace:
            return fa_config.feature_namespace.value
        
        # Otherwise infer from agent name or features
        name_lower = fa_config.name.lower()
        
        if "sentiment" in name_lower or "news" in name_lower or "social" in name_lower:
            return "sentiment"
        elif "microstructure" in name_lower or "1m" in name_lower or "5m" in name_lower:
            return "microstructure"
        elif "regime" in name_lower or "trend" in name_lower or "1h" in name_lower or "daily" in name_lower:
            return "regime"
        elif "macro" in name_lower or "fundamental" in name_lower:
            return "macro"
        elif "vol" in name_lower or "volatility" in name_lower:
            return "volatility"
        elif "confidence" in name_lower or "ensemble" in name_lower:
            return "confidence"
        else:
            return "ts_15m"
    
    async def _call_execution_agent(
        self,
        pipeline: PipelineConfig,
        bundle: FifteenMinuteFeatureBundle,
        context: Dict[str, Any],
    ) -> Optional[TradeDecision]:
        """
        Call the 15m execution agent with the feature bundle.
        
        Args:
            pipeline: Pipeline configuration
            bundle: Feature bundle
            context: Execution context
            
        Returns:
            TradeDecision if generated, None otherwise
        """
        agent_name = pipeline.decision_agent.name
        agent = self.agent_registry.get(agent_name)
        
        if not agent:
            logger.error(f"Execution agent not found: {agent_name}")
            return None
        
        # Guardrail: Check role is execution
        agent_role = getattr(agent, "role", "")
        if agent_role != "execution":
            logger.error(
                f"Guardrail violation: Agent {agent_name} has role={agent_role}, "
                f"but is configured as decision_agent (must be execution)"
            )
            return None
        
        # Guardrail: Check timeframe is 15m
        agent_timeframe = getattr(agent, "timeframe", "")
        if agent_timeframe != "15m":
            logger.error(
                f"Guardrail violation: Agent {agent_name} has timeframe={agent_timeframe}, "
                f"but is configured as decision_agent for 15m pipeline"
            )
            return None
        
        try:
            # Call agent with feature bundle
            if hasattr(agent, "decide"):
                result = await agent.decide(bundle)
            elif hasattr(agent, "get_opinion"):
                result = await agent.get_opinion()
            else:
                logger.warning(f"Execution agent {agent_name} has no decide/get_opinion method")
                return None
            
            # Normalize to TradeDecision
            if isinstance(result, TradeDecision):
                return result
            elif hasattr(result, "to_dict"):
                # Convert AgentOpinion or similar to TradeDecision
                return TradeDecision(
                    asset=pipeline.asset,
                    timeframe="15m",
                    side=result.side if hasattr(result, "side") else "yes",
                    confidence=result.confidence if hasattr(result, "confidence") else 0.5,
                    edge_estimate=result.edge_estimate if hasattr(result, "edge_estimate") else 0.0,
                    size_pct=result.size_pct if hasattr(result, "size_pct") else 0.01,
                    market_id=result.market_id if hasattr(result, "market_id") else "",
                    reason=result.metadata.get("reason", "") if hasattr(result, "metadata") else "",
                    metadata=result.metadata if hasattr(result, "metadata") else {},
                    timestamp=datetime.utcnow(),
                )
            else:
                logger.warning(f"Execution agent returned unsupported type: {type(result)}")
                return None
        
        except Exception as e:
            logger.error(f"Error calling execution agent {agent_name}: {e}")
            return None
    
    async def execute_decision(
        self,
        decision: TradeDecision,
        pipeline: PipelineConfig,
        trace: Optional[Any] = None,
    ) -> bool:
        """
        Execute a trade decision via the Kalshi executor with observability.
        
        Args:
            decision: Trade decision to execute
            pipeline: Pipeline configuration
            trace: Optional trace object for observability
            
        Returns:
            True if execution succeeded, False otherwise
        """
        start_time = time.time()
        
        # Get executor from registry
        executor = self.agent_registry.get(pipeline.executor.series_ticker)
        
        if not executor:
            logger.error(f"Executor not found: {pipeline.executor.series_ticker}")
            if trace:
                trace.execution_success = False
                trace.execution_error = f"Executor not found: {pipeline.executor.series_ticker}"
                trace.execution_ms = (time.time() - start_time) * 1000
                self.observability.finalize_trace(trace)
            return False
        
        try:
            # Attach guardrail metadata to order
            order_metadata = {
                "asset": decision.asset,
                "timeframe": decision.timeframe,
                "pipeline_id": decision.pipeline_id,
                "decision_agent": decision.decision_agent,
                "confidence": decision.confidence,
                "edge_estimate": decision.edge_estimate,
                "features_fingerprint": decision.features_fingerprint,
                "bundle_version": "1.0",
            }
            
            # Call executor (assuming place_order method)
            if hasattr(executor, "place_order"):
                result = await executor.place_order(
                    market_id=decision.market_id,
                    side=decision.side,
                    contracts=int(decision.size_pct * 100),  # Convert pct to contracts
                    metadata=order_metadata,
                )
                logger.info(f"Order placed via executor: {result}")
                
                if trace:
                    trace.execution_success = True
                    trace.execution_ms = (time.time() - start_time) * 1000
                    self.observability.log_execution(trace, True)
                    self.observability.finalize_trace(trace)
                
                return True
            else:
                logger.error(f"Executor has no place_order method")
                if trace:
                    trace.execution_success = False
                    trace.execution_error = "Executor has no place_order method"
                    trace.execution_ms = (time.time() - start_time) * 1000
                    self.observability.log_execution(trace, False, trace.execution_error)
                    self.observability.finalize_trace(trace)
                return False
        
        except Exception as e:
            logger.error(f"Error executing decision: {e}")
            if trace:
                trace.execution_success = False
                trace.execution_error = str(e)
                trace.execution_ms = (time.time() - start_time) * 1000
                self.observability.log_execution(trace, False, str(e))
                self.observability.finalize_trace(trace)
            return False
    
    async def run_all_pipelines(
        self,
        context: Dict[str, Any],
    ) -> Dict[str, Optional[TradeDecision]]:
        """
        Run all enabled pipelines for all assets.
        
        Args:
            context: Execution context
            
        Returns:
            Dict mapping pipeline_id to TradeDecision (or None)
        """
        results = {}
        
        for pipeline_id in self.pipeline_registry.pipelines.keys():
            decision = await self.run_pipeline(pipeline_id, context)
            results[pipeline_id] = decision
        
        return results
    
    def get_pipeline_summary(self) -> Dict[str, Any]:
        """Get summary of all pipelines."""
        return self.pipeline_registry.summary()
