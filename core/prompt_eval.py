"""MERID Prompt Evaluation System using deepeval and custom metrics.

Evaluates LLM prompts for trading agents on coherence, accuracy,
and adherence to trading constraints.
"""

from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import asyncio
import structlog

logger = structlog.get_logger(__name__)


@dataclass
class PromptEvalResult:
    """Result of a prompt evaluation."""
    prompt_name: str
    test_case: str
    model: str
    passed: bool
    score: float
    metrics: Dict[str, float]
    latency_ms: float
    tokens_used: int
    error: Optional[str] = None


class TradingPromptMetrics:
    """Metrics for evaluating trading-related prompts."""
    
    @staticmethod
    def coherence_score(response: str) -> float:
        """Score response coherence (0-1)."""
        # Check for required sections
        has_reasoning = "reasoning" in response.lower() or "because" in response.lower()
        has_conclusion = any(word in response.lower() for word in ["approved", "rejected", "buy", "sell", "hold"])
        
        score = 0.0
        if has_reasoning:
            score += 0.5
        if has_conclusion:
            score += 0.5
        
        return score
    
    @staticmethod
    def constraint_adherence(response: str, constraints: List[str]) -> float:
        """Check if response adheres to given constraints."""
        if not constraints:
            return 1.0
        
        adherence_count = sum(1 for c in constraints if c.lower() in response.lower())
        return adherence_count / len(constraints)
    
    @staticmethod
    def risk_accuracy(response: str, expected_risk_level: str) -> float:
        """Check if risk assessment matches expected level."""
        response_lower = response.lower()
        
        if expected_risk_level == "low":
            return 1.0 if "low" in response_lower and "high" not in response_lower else 0.0
        elif expected_risk_level == "high":
            return 1.0 if "high" in response_lower or "critical" in response_lower else 0.0
        elif expected_risk_level == "medium":
            return 1.0 if "medium" in response_lower else 0.0
        
        return 0.5  # Unknown expected level
    
    @staticmethod
    def signal_accuracy(response: str, expected_signal: str) -> float:
        """Check if trade signal matches expected."""
        response_upper = response.upper()
        
        if expected_signal.upper() in response_upper:
            # Check if conflicting signals also present
            conflicting = {
                "BUY": "SELL",
                "SELL": "BUY",
                "HOLD": None
            }
            
            conflict = conflicting.get(expected_signal.upper())
            if conflict and conflict in response_upper:
                return 0.5  # Mixed signals
            return 1.0
        
        return 0.0


class PromptEvaluator:
    """Evaluates prompts using multiple metrics."""
    
    def __init__(self):
        self.metrics = TradingPromptMetrics()
        self.logger = logger.bind(component="PromptEvaluator")
    
    async def evaluate_risk_prompt(
        self,
        prompt: str,
        model: str,
        test_case: str,
        expected_risk_level: str,
        constraints: List[str] = None
    ) -> PromptEvalResult:
        """Evaluate a risk assessment prompt."""
        import time
        
        start_time = time.time()
        
        try:
            # Call LLM (placeholder - would use actual client)
            response = await self._call_llm(prompt, model)
            
            latency_ms = (time.time() - start_time) * 1000
            
            # Calculate metrics
            coherence = self.metrics.coherence_score(response)
            constraint_adherence = self.metrics.constraint_adherence(response, constraints or [])
            risk_accuracy = self.metrics.risk_accuracy(response, expected_risk_level)
            
            metrics = {
                "coherence": coherence,
                "constraint_adherence": constraint_adherence,
                "risk_accuracy": risk_accuracy,
                "overall": (coherence + constraint_adherence + risk_accuracy) / 3
            }
            
            passed = all(v >= 0.7 for v in [coherence, constraint_adherence, risk_accuracy])
            
            result = PromptEvalResult(
                prompt_name="risk_assessment",
                test_case=test_case,
                model=model,
                passed=passed,
                score=metrics["overall"],
                metrics=metrics,
                latency_ms=latency_ms,
                tokens_used=len(response.split())  # Approximate
            )
            
            self.logger.info(
                "risk_prompt_evaluated",
                test_case=test_case,
                passed=passed,
                score=metrics["overall"]
            )
            
            return result
            
        except Exception as e:
            return PromptEvalResult(
                prompt_name="risk_assessment",
                test_case=test_case,
                model=model,
                passed=False,
                score=0.0,
                metrics={},
                latency_ms=(time.time() - start_time) * 1000,
                tokens_used=0,
                error=str(e)
            )
    
    async def evaluate_signal_prompt(
        self,
        prompt: str,
        model: str,
        test_case: str,
        expected_signal: str
    ) -> PromptEvalResult:
        """Evaluate a trade signal prompt."""
        import time
        
        start_time = time.time()
        
        try:
            response = await self._call_llm(prompt, model)
            latency_ms = (time.time() - start_time) * 1000
            
            coherence = self.metrics.coherence_score(response)
            signal_accuracy = self.metrics.signal_accuracy(response, expected_signal)
            
            metrics = {
                "coherence": coherence,
                "signal_accuracy": signal_accuracy,
                "overall": (coherence + signal_accuracy) / 2
            }
            
            passed = coherence >= 0.7 and signal_accuracy >= 0.9
            
            return PromptEvalResult(
                prompt_name="trade_signal",
                test_case=test_case,
                model=model,
                passed=passed,
                score=metrics["overall"],
                metrics=metrics,
                latency_ms=latency_ms,
                tokens_used=len(response.split())
            )
            
        except Exception as e:
            return PromptEvalResult(
                prompt_name="trade_signal",
                test_case=test_case,
                model=model,
                passed=False,
                score=0.0,
                metrics={},
                latency_ms=(time.time() - start_time) * 1000,
                tokens_used=0,
                error=str(e)
            )
    
    async def _call_llm(self, prompt: str, model: str) -> str:
        """Call LLM with prompt (placeholder implementation)."""
        # In real implementation, this would call DeepSeek, Claude, etc.
        await asyncio.sleep(0.1)  # Simulate latency
        
        # Return mock response for testing
        return f"""Analysis complete.

Reasoning: Based on the market conditions and risk parameters provided.

Decision: This appears to be a moderate risk scenario requiring careful consideration.

Recommendation: Proceed with caution and monitor closely."""
    
    async def run_benchmark(
        self,
        test_cases: List[Dict[str, Any]]
    ) -> List[PromptEvalResult]:
        """Run benchmark evaluation on multiple test cases."""
        
        self.logger.info("benchmark_started", test_count=len(test_cases))
        
        results = []
        for test in test_cases:
            if test["type"] == "risk":
                result = await self.evaluate_risk_prompt(
                    prompt=test["prompt"],
                    model=test.get("model", "deepseek-chat"),
                    test_case=test["name"],
                    expected_risk_level=test["expected_risk"],
                    constraints=test.get("constraints", [])
                )
            elif test["type"] == "signal":
                result = await self.evaluate_signal_prompt(
                    prompt=test["prompt"],
                    model=test.get("model", "deepseek-chat"),
                    test_case=test["name"],
                    expected_signal=test["expected_signal"]
                )
            else:
                continue
            
            results.append(result)
        
        # Summary
        passed = sum(1 for r in results if r.passed)
        avg_score = sum(r.score for r in results) / len(results) if results else 0
        avg_latency = sum(r.latency_ms for r in results) / len(results) if results else 0
        
        self.logger.info(
            "benchmark_completed",
            passed=passed,
            total=len(results),
            avg_score=avg_score,
            avg_latency_ms=avg_latency
        )
        
        return results
    
    def generate_report(self, results: List[PromptEvalResult]) -> str:
        """Generate markdown report of evaluation results."""
        lines = [
            "# MERID Prompt Evaluation Report",
            "",
            "## Summary",
            f"- **Total Tests**: {len(results)}",
            f"- **Passed**: {sum(1 for r in results if r.passed)}",
            f"- **Failed**: {sum(1 for r in results if not r.passed)}",
            f"- **Average Score**: {sum(r.score for r in results) / len(results):.2f}",
            f"- **Average Latency**: {sum(r.latency_ms for r in results) / len(results):.0f}ms",
            "",
            "## Results by Test Case",
            "",
            "| Test Case | Model | Score | Passed | Latency |",
            "|-----------|-------|-------|--------|----------|",
        ]
        
        for r in results:
            status = "✅" if r.passed else "❌"
            lines.append(
                f"| {r.test_case} | {r.model} | {r.score:.2f} | {status} | {r.latency_ms:.0f}ms |"
            )
        
        lines.extend([
            "",
            "## Detailed Metrics",
            "",
        ])
        
        for r in results:
            lines.extend([
                f"### {r.test_case}",
                f"- **Prompt**: {r.prompt_name}",
                f"- **Model**: {r.model}",
                f"- **Overall Score**: {r.score:.2f}",
                f"- **Status**: {'PASSED' if r.passed else 'FAILED'}",
            ])
            
            if r.metrics:
                lines.append("- **Metrics**:")
                for metric_name, value in r.metrics.items():
                    lines.append(f"  - {metric_name}: {value:.2f}")
            
            if r.error:
                lines.append(f"- **Error**: {r.error}")
            
            lines.append("")
        
        return '\n'.join(lines)


# Pre-defined test cases for MERID
MERID_TEST_CASES = [
    {
        "name": "low_risk_approved",
        "type": "risk",
        "prompt": "Assess risk: AAPL position 10 shares, portfolio exposure 15%, cash $100k",
        "expected_risk": "low",
        "constraints": ["max 2% risk", "portfolio heat <20%"],
        "model": "deepseek-chat"
    },
    {
        "name": "high_risk_rejected",
        "type": "risk",
        "prompt": "Assess risk: TSLA position 10000 shares, portfolio exposure 75%, cash $5k",
        "expected_risk": "high",
        "constraints": ["max 2% risk", "portfolio heat <20%"],
        "model": "deepseek-chat"
    },
    {
        "name": "bullish_buy_signal",
        "type": "signal",
        "prompt": "Analyze AAPL: price $250, trend bullish, volume high, breakout above resistance",
        "expected_signal": "BUY",
        "model": "deepseek-chat"
    },
    {
        "name": "bearish_sell_signal",
        "type": "signal",
        "prompt": "Analyze TSLA: price $220, trend bearish, breaking support, high volume",
        "expected_signal": "SELL",
        "model": "deepseek-chat"
    },
]
