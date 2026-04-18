"""Prediction Arbitrage Analyst Agent - analyzes arbitrage opportunities and provides structured insights."""

from __future__ import annotations
import logging

from dataclasses import dataclass
from typing import Any, Dict, List, Optional
import json
import time
import uuid
import os
from utils.logger import get_logger
from pathlib import Path

from agents.base_agent import BaseAgent
from monitoring.prediction_analytics import get_arbitrage_opportunities, ArbitrageOpportunity
from monitoring.prediction_markets import get_prediction_aggregator
from core.merid_metrics import (
    compute_brier, compute_bss, brier_decomposition,
    get_merid_metrics, BrierResult
)
from core.brier_metrics_db import get_brier_db
from core.event_bus import event_stream
from utils.logger import get_logger

# Try to import python-json-logger, fall back to simple JSON
try:
    from pythonjsonlogger import jsonlogger
    HAS_JSON_LOGGER = True
except ImportError:
    HAS_JSON_LOGGER = False

# Structured logging setup
SERVICE_NAME = os.getenv("SERVICE_NAME", "merid-agent")

class AgentJsonFormatter:
    """JSON formatter for agent runs - works with or without python-json-logger."""
    
    def __init__(self):
        if HAS_JSON_LOGGER:
            self.formatter = jsonlogger.JsonFormatter(
                fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%SZ"
            )
        else:
            self.formatter = None
    
    def format_log(self, msg: str, extra: dict = None) -> str:
        """Format a log entry as JSON."""
        if HAS_JSON_LOGGER and self.formatter:
            # Create a log record and format it
            record = logging.LogRecord(
                name="merid.agent",
                level=logging.INFO,
                pathname="",
                lineno=0,
                msg=msg,
                args=(),
                exc_info=None
            )
            if extra:
                for k, v in extra.items():
                    setattr(record, k, v)
            return self.formatter.format(record)
        else:
            # Fallback to simple JSON
            data = {
                "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "service": SERVICE_NAME,
                "level": "INFO",
                "logger": "merid.agent",
                "msg": msg,
                **(extra or {})
            }
            return json.dumps(data, ensure_ascii=False)

# Global formatter instance
_json_formatter = AgentJsonFormatter()

def log_agent_run(run: AgentRunLog) -> None:
    """Log agent run using structured JSON logging."""
    try:
        # Prepare structured log data
        log_data = {
            "agent_id": run.agent_id,
            "run_id": run.run_id,
            "agent_version": run.agent_version,
            "run_type": run.run_type,
            "experiment_id": run.experiment_id,
            "brier_score": run.brier_score,
            "estimates_only": run.estimates_only,
            "total_opportunities": run.total_opportunities,
            "recommendations_count": run.recommendations_count,
            "latency_ms": run.latency_ms,
            "status": run.status,
            "filters": run.filters,
            # Bucket stats as nested array
            "bucket_stats": [
                {
                    "bucket_range": bucket.bucket_range,
                    "count": bucket.count,
                    "avg_forecast": bucket.avg_forecast,
                    "empirical_success_rate": bucket.empirical_success_rate,
                    "avg_spread": bucket.avg_spread,
                    "avg_liquidity": bucket.avg_liquidity
                }
                for bucket in run.bucket_stats
            ]
        }
        
        # Add error fields if present
        if run.error_type:
            log_data["error_type"] = run.error_type
        if run.error_message:
            log_data["error_message"] = run.error_message
        
        # Format as JSON and log
        json_log_line = _json_formatter.format_log("agent_run_completed", log_data)
        
        # Also write to file for backwards compatibility
        LOG_PATH = Path("logs/agent_runs.jsonl")
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json_log_line + "\n")
        
        # Also send to standard logger
        logger = get_logger(f"agents.{run.agent_id}")
        logger.info(f"Agent run completed: {run.run_id}", extra=log_data)
        
    except Exception as e:
        # Don't let logging failures break the agent
        logger = get_logger("agents.prediction_arbitrage_analyst")
        logger.warning(f"Failed to log agent run: {e}")

@dataclass
class ArbitrageOpportunitySummary:
    """Structured summary of a single arbitrage opportunity."""
    canonical_question: str
    spread_probability: float
    best_venue: str
    best_probability: float
    worst_venue: str
    worst_probability: float
    days_to_resolution: Optional[float]
    total_liquidity: float
    risk_note: str
    forecast_probability: float  # Agent's confidence this will be profitable
    market_id: str = ""  # Optional market identifier for outcome tracking

@dataclass
class BucketAnalysis:
    """Analysis of forecast calibration by probability buckets."""
    bucket_range: str  # e.g., "0.4-0.6"
    count: int
    avg_forecast: float
    empirical_success_rate: float
    avg_spread: float
    avg_liquidity: float

@dataclass
class ArbitrageAnalysisResponse:
    """Structured response from the arbitrage analyst agent."""
    summary: str
    top_opportunities: List[ArbitrageOpportunitySummary]
    filters_used: Dict[str, Any]
    total_opportunities_analyzed: int
    analysis_timestamp: float
    bucket_analysis: List[BucketAnalysis]  # Calibration buckets
    brier_score: Optional[float] = None  # Legacy Brier score (deprecated)
    brier_metrics: Optional[Dict[str, Any]] = None  # Canonical Brier metrics
    brier_score: Optional[float] = None  # Legacy Brier score (deprecated)
    brier_metrics: Optional[Dict[str, Any]] = None  # Canonical Brier metrics
    brier_score: Optional[float] = None  # Legacy Brier score (deprecated)
    brier_metrics: Optional[Dict[str, Any]] = None  # Canonical Brier metrics
    brier_score: Optional[float] = None  # Legacy Brier score (deprecated)
    brier_metrics: Optional[Dict[str, Any]] = None  # Canonical Brier metrics
    brier_score: Optional[float] = None  # Legacy Brier score (deprecated)
    brier_metrics: Optional[Dict[str, Any]] = None  # Canonical Brier metrics
    brier_score: Optional[float] = None  # Legacy Brier score (deprecated)
    brier_metrics: Optional[Dict[str, Any]] = None  # Canonical Brier metrics

@dataclass
class AgentRunLog:
    """Log entry for each agent run with performance metrics."""
    run_id: str
    timestamp: float
    agent_id: str
    agent_version: str  # model name + prompt hash
    run_type: str  # "manual", "scheduled", "backtest", "prompt-experiment"
    experiment_id: Optional[str] = None  # e.g., "arb-prompt-2026-01-24"
    filters: Dict[str, Any] = None
    brier_score: Optional[float] = None
    estimates_only: bool = True  # True until we have real outcomes
    bucket_stats: List[BucketAnalysis] = None
    total_opportunities: int = 0
    recommendations_count: int = 0
    latency_ms: float = 0.0
    status: str = "unknown"  # "success", "error", "timeout"
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    llm_mode: Optional[str] = None  # "mock" | "live"
    llm_status: Optional[str] = None  # "ok" | "timeout" | "error" | "skipped"
    llm_mode: Optional[str] = None  # "mock" | "live"
    llm_status: Optional[str] = None  # "ok" | "timeout" | "error" | "skipped"
    llm_mode: Optional[str] = None  # "mock" | "live"
    llm_status: Optional[str] = None  # "ok" | "timeout" | "error" | "skipped"
    llm_mode: Optional[str] = None  # "mock" | "live"
    llm_status: Optional[str] = None  # "ok" | "timeout" | "error" | "skipped"
    llm_mode: Optional[str] = None  # "mock" | "live"
    llm_status: Optional[str] = None  # "ok" | "timeout" | "error" | "skipped"
    llm_mode: Optional[str] = None  # "mock" | "live"
    llm_status: Optional[str] = None  # "ok" | "timeout" | "error" | "skipped"
    llm_mode: Optional[str] = None  # "mock" | "live"
    llm_status: Optional[str] = None  # "ok" | "timeout" | "error" | "skipped"
    llm_mode: Optional[str] = None  # "mock" | "live"
    llm_status: Optional[str] = None  # "ok" | "timeout" | "error" | "skipped"
    llm_mode: Optional[str] = None  # "mock" | "live"
    llm_status: Optional[str] = None  # "ok" | "timeout" | "error" | "skipped"
    llm_mode: Optional[str] = None  # "mock" | "live"
    llm_status: Optional[str] = None  # "ok" | "timeout" | "error" | "skipped"
    llm_mode: Optional[str] = None  # "mock" | "live"
    llm_status: Optional[str] = None  # "ok" | "timeout" | "error" | "skipped"
    llm_mode: Optional[str] = None  # "mock" | "live"
    llm_status: Optional[str] = None  # "ok" | "timeout" | "error" | "skipped"
    llm_mode: Optional[str] = None  # "mock" | "live"
    llm_status: Optional[str] = None  # "ok" | "timeout" | "error" | "skipped"
    llm_mode: Optional[str] = None  # "mock" | "live"
    llm_status: Optional[str] = None  # "ok" | "timeout" | "error" | "skipped"

class PredictionArbitrageAnalystAgent(BaseAgent):
    """Agent that analyzes prediction market arbitrage opportunities and provides structured recommendations."""
    
    def __init__(
        self,
        agent_id: str = "prediction-arbitrage-analyst-01",
        model_name: str = "llama3:latest",
        *,
        min_spread: float = 0.05,
        max_opportunities: int = 10,
        min_liquidity: float = 50000.0,
        categories: Optional[List[str]] = None
    ) -> None:
        role_prompt = """
You are a prediction market arbitrage analyst specializing in identifying and ranking cross-venue trading opportunities.

Your task is to analyze arbitrage opportunities and provide structured, actionable insights. Focus on:
1. Ranking by spread probability (highest first)
2. Considering liquidity and time to resolution
3. Identifying potential risks or quality issues
4. Providing concise, data-driven recommendations

Always respond with JSON in this exact format:
{
    "summary": "Brief overview of findings (2-3 sentences)",
    "top_opportunities": [
        {
            "canonical_question": "Normalized question text",
            "spread_probability": 0.13,
            "best_venue": "polymarket",
            "best_probability": 0.65,
            "worst_venue": "kalshi", 
            "worst_probability": 0.52,
            "days_to_resolution": 30.5,
            "total_liquidity": 450000.0,
            "risk_note": "High liquidity, good time horizon"
        }
    ],
    "filters_used": {"min_spread": 0.05, "min_liquidity": 50000.0},
    "total_opportunities_analyzed": 15,
    "analysis_timestamp": 1640995200.0
}

Flag opportunities with very low liquidity, imminent resolution (< 1 day), or suspicious spreads in risk_notes.
""".strip()
        
        super().__init__(agent_id, model_name, role_prompt, tool_budget=0)
        self.min_spread = min_spread
        self.max_opportunities = max_opportunities
        self.min_liquidity = min_liquidity
        self.categories = categories or []
        self.logger = get_logger(f"agents.{agent_id}")
    
    async def _additional_context(self, energy: Dict[str, Any], research_findings: str) -> str:
        """Fetch arbitrage opportunities and prepare them for LLM analysis."""
        try:
            # Get aggregator and fetch opportunities directly
            aggregator = get_prediction_aggregator()
            opportunities = get_arbitrage_opportunities(
                min_spread=self.min_spread,
                limit=self.max_opportunities * 2,  # Get more to filter
                aggregator=aggregator
            )
            
            if not opportunities:
                return "No arbitrage opportunities found matching the current criteria."
            
            # Filter by liquidity and categories if specified
            filtered_opps = []
            for opp in opportunities:
                # Check liquidity filter
                total_liquidity = sum(market.get('liquidity', 0) for market in opp.markets)
                if total_liquidity < self.min_liquidity:
                    continue
                
                # Check category filter
                if self.categories:
                    opp_categories = set(market.get('category', '') for market in opp.markets)
                    if not any(cat in opp_categories for cat in self.categories):
                        continue
                
                filtered_opps.append(opp)
            
            if not filtered_opps:
                return f"No arbitrage opportunities found after applying filters (min_spread={self.min_spread}, min_liquidity=${self.min_liquidity})."
            
            # Prepare opportunities data for LLM
            opportunities_data = []
            for i, opp in enumerate(filtered_opps[:self.max_opportunities]):
                # Calculate total liquidity
                total_liquidity = sum(market.get('liquidity', 0) for market in opp.markets)
                
                # Find best and worst venues
                best_market = max(opp.markets, key=lambda m: m.get('implied_probability', 0))
                worst_market = min(opp.markets, key=lambda m: m.get('implied_probability', 0))
                
                # Calculate days to resolution (use average if available)
                days_to_resolution = None
                resolution_times = [m.get('days_to_resolution') for m in opp.markets if m.get('days_to_resolution')]
                if resolution_times:
                    days_to_resolution = sum(resolution_times) / len(resolution_times)
                
                # Generate risk note
                risk_note = self._generate_risk_note(opp, total_liquidity, days_to_resolution)
                
                opportunities_data.append({
                    "rank": i + 1,
                    "canonical_question": opp.canonical_question,
                    "spread_probability": opp.spread_probability,
                    "best_venue": best_market.get('venue', 'unknown'),
                    "best_probability": best_market.get('implied_probability', 0),
                    "worst_venue": worst_market.get('venue', 'unknown'),
                    "worst_probability": worst_market.get('implied_probability', 0),
                    "days_to_resolution": days_to_resolution,
                    "total_liquidity": total_liquidity,
                    "risk_note": risk_note,
                    "venue_count": len(opp.markets)
                })
            
            # Format as JSON for LLM input
            import json
            opportunities_json = json.dumps(opportunities_data, indent=2)
            
            context = f"""
ARBITRAGE OPPORTUNITIES ANALYSIS:
{opportunities_json}

FILTERS APPLIED:
- Minimum spread: {self.min_spread} ({self.min_spread * 100:.1f}%)
- Minimum liquidity: ${self.min_liquidity:,.0f}
- Maximum opportunities to analyze: {self.max_opportunities}
- Category filter: {self.categories or 'all'}
- Total opportunities found: {len(opportunities) if opportunities else 0}
- Opportunities after filtering: {len(filtered_opps) if filtered_opps else 0}
- Total opportunities found: {len(opportunities) if opportunities else 0}
- Opportunities after filtering: {len(filtered_opps) if filtered_opps else 0}
- Total opportunities found: {len(opportunities) if opportunities else 0}
- Opportunities after filtering: {len(filtered_opps) if filtered_opps else 0}
- Total opportunities found: {len(opportunities) if opportunities else 0}
- Opportunities after filtering: {len(filtered_opps) if filtered_opps else 0}
- Total opportunities found: {len(opportunities) if opportunities else 0}
- Opportunities after filtering: {len(filtered_opps) if filtered_opps else 0}
- Total opportunities found: {len(opportunities) if opportunities else 0}
- Opportunities after filtering: {len(filtered_opps) if filtered_opps else 0}
- Total opportunities found: {len(opportunities) if opportunities else 0}
- Opportunities after filtering: {len(filtered_opps) if filtered_opps else 0}
- Total opportunities found: {len(opportunities) if opportunities else 0}
- Opportunities after filtering: {len(filtered_opps) if filtered_opps else 0}
- Total opportunities found: {len(opportunities) if opportunities else 0}
- Opportunities after filtering: {len(filtered_opps) if filtered_opps else 0}
- Total opportunities found: {len(opportunities) if opportunities else 0}
- Opportunities after filtering: {len(filtered_opps) if filtered_opps else 0}
- Total opportunities found: {len(opportunities) if opportunities else 0}
- Opportunities after filtering: {len(filtered_opps) if filtered_opps else 0}
- Total opportunities found: {len(opportunities) if opportunities else 0}
- Opportunities after filtering: {len(filtered_opps) if filtered_opps else 0}
- Total opportunities found: {len(opportunities) if opportunities else 0}
- Opportunities after filtering: {len(filtered_opps) if filtered_opps else 0}
- Total opportunities found: {len(opportunities) if opportunities else 0}
- Opportunities after filtering: {len(filtered_opps) if filtered_opps else 0}
- Total opportunities found: {len(opportunities) if opportunities else 0}
- Opportunities after filtering: {len(filtered_opps) if filtered_opps else 0}

Please analyze these opportunities and provide your structured recommendations.
"""
            
            self.logger.info(f"Prepared {len(filtered_opps) if filtered_opps else 0} arbitrage opportunities for analysis")
            return context
            
        except Exception as exc:
            error_msg = f"Failed to fetch arbitrage opportunities: {str(exc)}"
            self.logger.error(error_msg)
            return f"Error: Unable to fetch arbitrage data. {error_msg}"
    
    def _generate_risk_note(self, opp: ArbitrageOpportunity, total_liquidity: float, days_to_resolution: Optional[float]) -> str:
        """Generate a risk assessment note for an opportunity."""
        risk_factors = []
        
        # Liquidity risk
        if total_liquidity < 100000:
            risk_factors.append("Low liquidity")
        elif total_liquidity > 1000000:
            risk_factors.append("High liquidity")
        
        # Time horizon risk
        if days_to_resolution is not None:
            if days_to_resolution < 1:
                risk_factors.append("Very near expiry")
            elif days_to_resolution > 365:
                risk_factors.append("Long time horizon")
        
        # Spread risk
        if opp.spread_probability > 0.20:
            risk_factors.append("Very high spread (potential error)")
        elif opp.spread_probability < 0.02:
            risk_factors.append("Minimal spread")
        
        # Venue count risk
        if len(opp.markets) < 2:
            risk_factors.append("Limited venues")
        
        if not risk_factors:
            return "Good liquidity and time horizon"
        
        return ", ".join(risk_factors)
    
    def _compute_bucket_analysis(self, opportunities: List[ArbitrageOpportunitySummary]) -> List[BucketAnalysis]:
        """Compute calibration buckets for forecast probabilities using dynamic boundaries."""
        if not opportunities:
            return []
        
        # Dynamic bucket boundaries based on opportunity distribution
        forecasts = [opp.forecast_probability for opp in opportunities]
        forecasts.sort()
        
        # Create 4 buckets with equal opportunity count when possible
        n = len(forecasts)
        if n >= 4:
            bucket_size = n // 4
            bucket_edges = [
                0.0,
                forecasts[bucket_size - 1],
                forecasts[bucket_size * 2 - 1],
                forecasts[bucket_size * 3 - 1],
                1.0
            ]
        else:
            # Fallback to fixed boundaries for small datasets
            bucket_edges = [0.0, 0.4, 0.6, 0.8, 1.0]
        
        bucket_labels = [f"{bucket_edges[i]:.2f}-{bucket_edges[i+1]:.2f}" for i in range(len(bucket_edges)-1)]
        
        buckets = []
        for i, (lower, upper) in enumerate(zip(bucket_edges[:-1], bucket_edges[1:])):
            # Find opportunities in this bucket
            bucket_opps = [
                opp for opp in opportunities 
                if lower <= opp.forecast_probability < upper
            ]
            
            if not bucket_opps:
                continue
            
            # Calculate bucket metrics
            count = len(bucket_opps)
            avg_forecast = sum(opp.forecast_probability for opp in bucket_opps) / count
            avg_spread = sum(opp.spread_probability for opp in bucket_opps) / count
            avg_liquidity = sum(opp.total_liquidity for opp in bucket_opps) / count
            
            # For now, empirical success rate is placeholder (will be updated with real outcomes)
            # In a real implementation, this would come from historical outcome data
            empirical_success_rate = avg_forecast * 0.9  # Placeholder: slightly calibrated
            
            buckets.append(BucketAnalysis(
                bucket_range=bucket_labels[i],
                count=count,
                avg_forecast=avg_forecast,
                empirical_success_rate=empirical_success_rate,
                avg_spread=avg_spread,
                avg_liquidity=avg_liquidity
            ))
        
        return buckets
    
    def _calculate_brier_score(self, opportunities: List[ArbitrageOpportunitySummary]) -> Optional[Dict[str, Any]]:
        """Calculate canonical Brier score metrics for forecast probabilities.
        
        Uses industry-standard Brier score, Brier Skill Score, and decomposition.
        Returns None if auditor is in blindness mode.
        """
        if not opportunities:
            return None
        
        # Check auditor mode first - don't calculate metrics when blind
        try:
            from core.reality_auditor import get_reality_auditor, AuditorMode
            auditor = get_reality_auditor()
            
            if auditor.current_mode != AuditorMode.NORMAL:
                return {
                    "brier_score": None,
                    "brier_skill_score_vs_baseline": None,
                    "brier_skill_score_vs_climatology": None,
                    "baseline_used": 0.004316,
                    "climatology_baseline": None,
                    "quality_category": "AWAITING_OUTCOMES",
                    "n_samples": len(opportunities),
                    "decomposition": {
                        "reliability": None,
                        "resolution": None,
                        "uncertainty": None,
                        "base_rate": None
                    },
                    "status": "awaiting_outcomes",
                    "reason": f"Auditor in {auditor.current_mode.value} mode",
                    "blindness_context": auditor.last_blindness_context.to_dict() if auditor.last_blindness_context else None
                }
        except Exception as e:
            # If auditor check fails, log but continue with calculation
            from utils.logger import get_logger
            logging.getLogger(__name__).warning(f"Failed to check auditor mode: {e}")
        
        if not opportunities:
            return None
        
        # Extract forecasts and outcomes
        y_prob = []
        y_true = []
        
        # Try to fetch real settled outcomes from RewardEngine DB (forecast category only)
        _settled: dict = {}
        try:
            import json as _json
            from merid.rewards.engine import get_reward_engine
            _engine = get_reward_engine()
            with _engine._connect() as _conn:
                _rows = _conn.execute(
                    "SELECT payload FROM reward_events WHERE category = 'forecast' "
                    "ORDER BY created_at DESC LIMIT 1000"
                ).fetchall()
            for _row in _rows:
                try:
                    _p = _json.loads(_row["payload"])
                    _sym = _p.get("symbol", "")
                    _outcome = _p.get("outcome")
                    if _sym and _outcome is not None:
                        _settled[_sym] = int(_outcome)
                except Exception:
                    logger.debug("Failed to parse settled outcome row: %s", _row)
        except Exception as _exc:
            logger.debug("Failed to load settled outcomes: %s", _exc)

        for opp in opportunities:
            y_prob.append(opp.forecast_probability)
            # Use real settled outcome if available; fall back to spread_probability proxy
            real_outcome = _settled.get(opp.market_id)
            if real_outcome is not None:
                y_true.append(float(real_outcome))
            else:
                y_true.append(1.0 if opp.spread_probability > 0.5 else 0.0)

        # Convert to numpy arrays for metrics functions
        import numpy as np
        y_true_arr = np.array(y_true)
        y_prob_arr = np.array(y_prob)

        # Calculate canonical metrics
        brier_score = compute_brier(y_true_arr, y_prob_arr)
        
        # Calculate BSS vs MERID baseline
        merid_baseline = 0.004316
        baseline_prob = y_true.count(1) / len(y_true)  # Use empirical base rate as baseline
        
        # Calculate BSS vs climatology (empirical base rate)
        # Pass None for baseline to let compute_bss use climatology internally
        bss_vs_climatology = compute_bss(y_true_arr, y_prob_arr, baseline=None)

        # For BSS vs MERID baseline, we need to compare Brier scores directly
        # BSS = 1 - BS_model / BS_baseline
        bss_vs_baseline = 1.0 - brier_score / merid_baseline

        # Calculate decomposition for diagnostics
        decomp = brier_decomposition(y_true_arr, y_prob_arr, n_bins=4)

        # Quality assessment
        quality = "Excellent" if brier_score < 0.1 else "Good" if brier_score < 0.2 else "Fair" if brier_score < 0.3 else "Poor"

        return {
            "brier_score": brier_score,
            "brier_skill_score_vs_baseline": bss_vs_baseline,
            "brier_skill_score_vs_climatology": bss_vs_climatology,
            "baseline_used": merid_baseline,
            "climatology_baseline": baseline_prob,
            "quality_category": quality,
            "n_samples": len(opportunities),
            "decomposition": {
                "reliability": decomp.reliability,
                "resolution": decomp.resolution,
                "uncertainty": decomp.uncertainty,
                "base_rate": baseline_prob
            },
            "status": "ok",
            "reason": "Metrics calculated successfully"
        }
    
    async def process(self, energy: Dict[str, Any], phase: str = "reasoning") -> Dict[str, Any]:
        """Execute the agent reasoning pipeline for arbitrage analysis."""
        await event_stream.publish(
            "agent:start",
            {"agent": self.agent_id, "energy_id": energy["energy_id"], "phase": phase},
        )
        self.logger.info("Processing energy %s", energy["energy_id"])

        research_findings = await self._gather_research(energy)
        extra_context = await self._additional_context(energy, research_findings)
        
        # Add reflection context for self-learning
        from agents.reflection.integration import get_reflection_system
        reflection_system = get_reflection_system()
        reflection_context = reflection_system.get_agent_context(
            self.agent_id,
            include_metrics=True,
            include_insights=True
        )
        if reflection_context:
            extra_context = f"{extra_context}\n\nReflection Context:\n{reflection_context}"

        prompt = self._build_prompt(energy, phase, research_findings, extra_context)

        start_time = time.time()
        
        # Create run log and set reference for LLM mode tracking
        run_log = AgentRunLog(
            run_id=energy.get("energy_id", f"run-{int(time.time())}"),
            timestamp=start_time,
            agent_id=self.agent_id,
            agent_version=energy.get("agent_version", self.model_name),
            run_type=energy.get("run_type", "manual"),
            experiment_id=energy.get("experiment_id"),
            filters={
                "min_spread": self.min_spread,
                "max_opportunities": self.max_opportunities,
                "min_liquidity": self.min_liquidity,
                "categories": self.categories
            },
            brier_score=None,  # Will be set after parsing
            estimates_only=True,  # Until we have real outcomes
            bucket_stats=[],  # Will be set after parsing
            total_opportunities=0,  # Will be set after parsing
            recommendations_count=0,  # Will be set after parsing
            latency_ms=0.0,  # Will be set after LLM call
            status="success",
            llm_mode=None,  # Will be set by _invoke_model
            llm_status=None  # Will be set by _invoke_model
        )
        
        # Set reference for LLM mode tracking
        self._current_run_log = run_log
        
        raw_response = await self._invoke_model(prompt)
        end_time = time.time()
        parsed = self._parse_response(raw_response)
        
        # Update run log with actual results
        run_log.latency_ms = (end_time - start_time) * 1000
        run_log.brier_score = parsed.get("brier_score")
        run_log.bucket_stats = parsed.get("bucket_analysis", [])
        run_log.total_opportunities = parsed.get("total_opportunities_analyzed", 0)
        run_log.recommendations_count = len(parsed.get("top_opportunities", []))
        run_log.status = "success"
        
        log_agent_run(run_log)
        
        # Clear reference
        delattr(self, '_current_run_log')

        # Return arbitrage-specific structure instead of standard agent response
        return {
            "agent_id": self.agent_id,
            "analysis": parsed,
            "trust": self.trust,
            "research": research_findings,
            "phase": phase,
            "energy_id": energy["energy_id"]
        }
    
    def _parse_response(self, raw: str) -> Dict[str, Any]:
        """Parse LLM response into structured ArbitrageAnalysisResponse."""
        import json
        import time
        
        # Try to parse as JSON first
        try:
            parsed = json.loads(raw)
            
            # Validate and structure the response
            summary = parsed.get("summary", "Analysis completed")
            
            # Parse top opportunities
            top_opportunities = []
            for opp_data in parsed.get("top_opportunities", []):
                # Calculate forecast probability based on conservative heuristics
                spread = float(opp_data.get("spread_probability", 0))
                liquidity = float(opp_data.get("total_liquidity", 0))
                venue_count = int(opp_data.get("venue_count", 2))
                
                # Conservative heuristic: maintain spread importance, reduce venue bonus
                base_confidence = min(spread * 4.5, 0.75)  # Higher spread weight, higher cap
                liquidity_bonus = min(liquidity / 1200000, 0.1)  # Higher threshold, lower bonus
                venue_diversity_bonus = min(venue_count * 0.03, 0.06)  # Reduced venue bonus
                
                forecast_probability = min(base_confidence + liquidity_bonus + venue_diversity_bonus, 0.85)
                
                opportunity = ArbitrageOpportunitySummary(
                    canonical_question=opp_data.get("canonical_question", ""),
                    spread_probability=spread,
                    best_venue=opp_data.get("best_venue", ""),
                    best_probability=float(opp_data.get("best_probability", 0)),
                    worst_venue=opp_data.get("worst_venue", ""),
                    worst_probability=float(opp_data.get("worst_probability", 0)),
                    days_to_resolution=opp_data.get("days_to_resolution"),
                    total_liquidity=liquidity,
                    risk_note=opp_data.get("risk_note", ""),
                    forecast_probability=forecast_probability
                )
                top_opportunities.append(opportunity)
            
            filters_used = parsed.get("filters_used", {
                "min_spread": self.min_spread,
                "min_liquidity": self.min_liquidity,
                "categories": self.categories
            })
            
            total_opportunities_analyzed = int(parsed.get("total_opportunities_analyzed", 0))
            analysis_timestamp = float(parsed.get("analysis_timestamp", time.time()))
            
            # Compute bucket analysis
            bucket_analysis = self._compute_bucket_analysis(top_opportunities)
            
            # Calculate Brier score
            brier_metrics = self._calculate_brier_score(top_opportunities)
            
            # Return structured response
            response = ArbitrageAnalysisResponse(
                summary=summary,
                top_opportunities=top_opportunities,
                filters_used=filters_used,
                total_opportunities_analyzed=total_opportunities_analyzed,
                analysis_timestamp=analysis_timestamp,
                bucket_analysis=bucket_analysis,
                brier_score=brier_metrics["brier_score"] if brier_metrics else None,
                brier_metrics=brier_metrics
            )
            
            # Convert to dict for return
            return {
                "summary": response.summary,
                "top_opportunities": [
                    {
                        "canonical_question": opp.canonical_question,
                        "spread_probability": opp.spread_probability,
                        "best_venue": opp.best_venue,
                        "best_probability": opp.best_probability,
                        "worst_venue": opp.worst_venue,
                        "worst_probability": opp.worst_probability,
                        "days_to_resolution": opp.days_to_resolution,
                        "total_liquidity": opp.total_liquidity,
                        "risk_note": opp.risk_note,
                        "forecast_probability": opp.forecast_probability
                    }
                    for opp in response.top_opportunities
                ],
                "filters_used": response.filters_used,
                "total_opportunities_analyzed": response.total_opportunities_analyzed,
                "analysis_timestamp": response.analysis_timestamp,
                "bucket_analysis": [
                    {
                        "bucket_range": bucket.bucket_range,
                        "count": bucket.count,
                        "avg_forecast": bucket.avg_forecast,
                        "empirical_success_rate": bucket.empirical_success_rate,
                        "avg_spread": bucket.avg_spread,
                        "avg_liquidity": bucket.avg_liquidity
                    }
                    for bucket in response.bucket_analysis
                ],
                "brier_score": response.brier_score,
                "brier_metrics": response.brier_metrics
            }
            
        except json.JSONDecodeError as exc:
            # Fallback for JSON parsing errors
            self.logger.error(f"JSON parsing failed for arbitrage analyst: {exc}")
            return {
                "summary": f"Analysis completed but response parsing failed. Raw response: {raw[:200]}...",
                "top_opportunities": [],
                "filters_used": {
                    "min_spread": self.min_spread,
                    "min_liquidity": self.min_liquidity,
                    "categories": self.categories
                },
                "total_opportunities_analyzed": 0,
                "analysis_timestamp": time.time(),
                "error": "JSON parsing failed"
            }
        except Exception as exc:
            # Fallback for other errors
            self.logger.error(f"Response parsing failed for arbitrage analyst: {exc}")
            return {
                "summary": f"Analysis completed but response processing failed: {str(exc)}",
                "top_opportunities": [],
                "filters_used": {
                    "min_spread": self.min_spread,
                    "min_liquidity": self.min_liquidity,
                    "categories": self.categories
                },
                "total_opportunities_analyzed": 0,
                "analysis_timestamp": time.time(),
                "error": "Response processing failed"
            }
