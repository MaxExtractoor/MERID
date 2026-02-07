"""Tests for MERID structured prompts and prompt evaluation."""

import pytest
from unittest.mock import Mock, patch, AsyncMock
import asyncio


class TestTradeSignal:
    """Tests for TradeSignal Pydantic model."""
    
    def test_valid_trade_signal_creation(self):
        from core.structured_prompts import TradeSignal, TradeSide, ConfidenceLevel
        
        signal = TradeSignal(
            symbol="AAPL",
            side=TradeSide.BUY,
            quantity=100.0,
            price=150.0,
            confidence=0.85,
            confidence_level=ConfidenceLevel.HIGH,
            reasoning="Bullish breakout with volume confirmation",
            strategy="momentum",
            timeframe="1d"
        )
        
        assert signal.symbol == "AAPL"
        assert signal.side == TradeSide.BUY
        assert signal.confidence == 0.85
        assert signal.quantity > 0
    
    def test_symbol_normalization(self):
        from core.structured_prompts import TradeSignal, TradeSide, ConfidenceLevel
        
        signal = TradeSignal(
            symbol="aapl",  # lowercase
            side=TradeSide.BUY,
            quantity=100.0,
            confidence=0.8,
            confidence_level=ConfidenceLevel.HIGH,
            reasoning="Test",
            strategy="test"
        )
        
        assert signal.symbol == "AAPL"  # Should be uppercased
    
    def test_invalid_confidence_range(self):
        from core.structured_prompts import TradeSignal, TradeSide, ConfidenceLevel
        from pydantic import ValidationError
        
        with pytest.raises(ValidationError):
            TradeSignal(
                symbol="AAPL",
                side=TradeSide.BUY,
                quantity=100.0,
                confidence=1.5,  # Invalid: > 1
                confidence_level=ConfidenceLevel.HIGH,
                reasoning="Test",
                strategy="test"
            )
    
    def test_invalid_quantity(self):
        from core.structured_prompts import TradeSignal, TradeSide, ConfidenceLevel
        from pydantic import ValidationError
        
        with pytest.raises(ValidationError):
            TradeSignal(
                symbol="AAPL",
                side=TradeSide.BUY,
                quantity=-100.0,  # Invalid: negative
                confidence=0.8,
                confidence_level=ConfidenceLevel.HIGH,
                reasoning="Test",
                strategy="test"
            )


class TestRiskAssessment:
    """Tests for RiskAssessment model."""
    
    def test_valid_risk_assessment(self):
        from core.structured_prompts import RiskAssessment, RiskLevel
        
        assessment = RiskAssessment(
            approved=True,
            risk_score=0.25,
            risk_level=RiskLevel.LOW,
            max_position_size=1000.0,
            var_95=500.0,
            portfolio_heat=0.15,
            correlation_risk=0.2,
            reasoning="Within risk limits",
            conditions=[]
        )
        
        assert assessment.approved is True
        assert assessment.risk_score < 0.5
        assert assessment.risk_level == RiskLevel.LOW
    
    def test_rejected_trade_gets_conditions(self):
        from core.structured_prompts import RiskAssessment, RiskLevel
        
        assessment = RiskAssessment(
            approved=False,
            risk_score=0.85,
            risk_level=RiskLevel.HIGH,
            max_position_size=100.0,
            portfolio_heat=0.35,
            correlation_risk=0.6,
            reasoning="High risk",
            conditions=[]
        )
        
        assert assessment.approved is False
        assert len(assessment.conditions) > 0


class TestMarketAnalysis:
    """Tests for MarketAnalysis model."""
    
    def test_market_analysis_creation(self):
        from core.structured_prompts import MarketAnalysis
        
        analysis = MarketAnalysis(
            trend="bullish",
            trend_strength=0.85,
            support_levels=[140.0, 135.0],
            resistance_levels=[150.0, 155.0],
            volatility_regime="normal",
            volume_analysis="Above average",
            key_events=["earnings", "fed_meeting"],
            recommendation="Buy on dips"
        )
        
        assert analysis.trend == "bullish"
        assert len(analysis.support_levels) == 2


class TestPromptRegistry:
    """Tests for PromptRegistry."""
    
    @pytest.fixture
    def registry(self):
        from core.structured_prompts import PromptRegistry, PromptVersion
        reg = PromptRegistry()
        reg.register(PromptVersion(
            name="test_prompt",
            version="1.0.0",
            template="Hello {name}!",
            metadata={"author": "test"}
        ))
        return reg
    
    def test_register_and_retrieve(self, registry):
        prompt = registry.get("test_prompt", "1.0.0")
        assert prompt is not None
        assert prompt.name == "test_prompt"
        assert prompt.version == "1.0.0"
    
    def test_latest_version_retrieval(self, registry):
        from core.structured_prompts import PromptVersion
        
        # Add newer version
        registry.register(PromptVersion(
            name="test_prompt",
            version="2.0.0",
            template="Hi {name}!",
            metadata={}
        ))
        
        latest = registry.get("test_prompt", "latest")
        assert latest.version == "2.0.0"
    
    def test_prompt_rendering(self, registry):
        prompt = registry.get("test_prompt", "1.0.0")
        rendered = prompt.render(name="World")
        assert rendered == "Hello World!"
    
    def test_missing_prompt(self, registry):
        prompt = registry.get("nonexistent", "1.0.0")
        assert prompt is None


class TestTradingPromptMetrics:
    """Tests for prompt evaluation metrics."""
    
    @pytest.fixture
    def metrics(self):
        from core.prompt_eval import TradingPromptMetrics
        return TradingPromptMetrics()
    
    def test_coherence_score_with_reasoning(self, metrics):
        response = "I recommend BUY because the trend is bullish."
        score = metrics.coherence_score(response)
        assert score >= 0.5
    
    def test_coherence_score_without_reasoning(self, metrics):
        response = "Buy now!"
        score = metrics.coherence_score(response)
        assert score < 1.0
    
    def test_constraint_adherence(self, metrics):
        response = "Approved with max 2% risk limit and portfolio heat under 20%."
        constraints = ["max 2% risk", "portfolio heat <20%"]
        score = metrics.constraint_adherence(response, constraints)
        assert score == 1.0
    
    def test_risk_accuracy_low(self, metrics):
        response = "Risk level: LOW. Approved."
        score = metrics.risk_accuracy(response, "low")
        assert score == 1.0
    
    def test_risk_accuracy_mismatch(self, metrics):
        response = "Risk level: HIGH. Rejected."
        score = metrics.risk_accuracy(response, "low")
        assert score == 0.0
    
    def test_signal_accuracy_buy(self, metrics):
        response = "Signal: BUY at $150."
        score = metrics.signal_accuracy(response, "BUY")
        assert score == 1.0
    
    def test_signal_accuracy_conflict(self, metrics):
        response = "Signal: BUY but consider SELL if resistance breaks."
        score = metrics.signal_accuracy(response, "BUY")
        assert score == 0.5


class TestPromptEvaluator:
    """Tests for PromptEvaluator."""
    
    @pytest.fixture
    def evaluator(self):
        from core.prompt_eval import PromptEvaluator
        return PromptEvaluator()
    
    @pytest.mark.asyncio
    async def test_evaluate_risk_prompt(self, evaluator):
        result = await evaluator.evaluate_risk_prompt(
            prompt="Test risk prompt",
            model="deepseek-chat",
            test_case="test_case",
            expected_risk_level="low",
            constraints=["max 2% risk"]
        )
        
        assert result.prompt_name == "risk_assessment"
        assert result.test_case == "test_case"
        assert result.model == "deepseek-chat"
        assert result.score >= 0.0
        assert result.score <= 1.0
    
    @pytest.mark.asyncio
    async def test_evaluate_signal_prompt(self, evaluator):
        result = await evaluator.evaluate_signal_prompt(
            prompt="Test signal prompt",
            model="deepseek-chat",
            test_case="test_case",
            expected_signal="BUY"
        )
        
        assert result.prompt_name == "trade_signal"
        assert "coherence" in result.metrics
        assert "signal_accuracy" in result.metrics
    
    @pytest.mark.asyncio
    async def test_run_benchmark(self, evaluator):
        test_cases = [
            {
                "name": "test1",
                "type": "risk",
                "prompt": "Test",
                "expected_risk": "low",
                "model": "deepseek-chat"
            }
        ]
        
        results = await evaluator.run_benchmark(test_cases)
        assert len(results) == 1
        assert results[0].test_case == "test1"
    
    def test_generate_report(self, evaluator):
        from core.prompt_eval import PromptEvalResult
        
        results = [
            PromptEvalResult(
                prompt_name="test",
                test_case="case1",
                model="deepseek-chat",
                passed=True,
                score=0.9,
                metrics={"coherence": 0.9},
                latency_ms=100.0,
                tokens_used=50
            ),
            PromptEvalResult(
                prompt_name="test",
                test_case="case2",
                model="deepseek-chat",
                passed=False,
                score=0.5,
                metrics={"coherence": 0.5},
                latency_ms=150.0,
                tokens_used=75
            )
        ]
        
        report = evaluator.generate_report(results)
        assert "MERID Prompt Evaluation Report" in report
        assert "case1" in report
        assert "case2" in report


class TestStructuredLLMClient:
    """Tests for StructuredLLMClient."""
    
    @pytest.fixture
    def mock_client(self):
        from core.structured_prompts import StructuredLLMClient
        with patch('core.structured_prompts.OpenAI'):
            with patch('core.structured_prompts.instructor'):
                client = StructuredLLMClient(api_key="test", model="deepseek-chat")
                client.client = Mock()
                return client
    
    def test_client_initialization(self, mock_client):
        assert mock_client.model == "deepseek-chat"
        assert mock_client.api_key == "test"
    
    def test_generate_trade_signal(self, mock_client):
        # Mock the response
        mock_response = Mock()
        mock_response.symbol = "AAPL"
        mock_response.side = "buy"
        mock_response.confidence = 0.85
        mock_response.reasoning = "Bullish trend"
        
        mock_client.client.chat.completions.create.return_value = mock_response
        
        result = mock_client.generate_trade_signal(
            symbol="AAPL",
            market_data={"price": 150.0},
            strategy="momentum"
        )
        
        assert result.symbol == "AAPL"
        assert result.confidence == 0.85
    
    def test_assess_trade_risk(self, mock_client):
        from core.structured_prompts import TradeSignal, TradeSide, ConfidenceLevel
        
        mock_response = Mock()
        mock_response.approved = True
        mock_response.risk_score = 0.25
        mock_response.risk_level = "low"
        mock_response.reasoning = "Low risk"
        
        mock_client.client.chat.completions.create.return_value = mock_response
        
        signal = TradeSignal(
            symbol="AAPL",
            side=TradeSide.BUY,
            quantity=100.0,
            confidence=0.8,
            confidence_level=ConfidenceLevel.HIGH,
            reasoning="Test",
            strategy="test"
        )
        
        result = mock_client.assess_trade_risk(
            trade_signal=signal,
            portfolio_context={"exposure": 0.1}
        )
        
        assert result.approved is True
        assert result.risk_score < 0.5
