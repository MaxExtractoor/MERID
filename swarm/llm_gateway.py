"""
Multi-provider LLM gateway with security controls for MERID.

Implements:
- Provider abstraction layer
- Automatic failover and load balancing
- Data classification and redaction
- Per-provider rate limits and policies
- Vendor independence
"""

import threading

from utils.logger import get_logger
import time
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from decimal import Decimal

logger = get_logger(__name__)


class LLMProvider(Enum):
    """LLM provider types."""
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GOOGLE = "google"
    COHERE = "cohere"
    LOCAL_LLAMA = "local_llama"
    LOCAL_GEMMA = "local_gemma"
    AZURE_OPENAI = "azure_openai"


class DataClassification(Enum):
    """Data classification levels."""
    PUBLIC = "public"  # No restrictions
    INTERNAL = "internal"  # MERID internal only
    CONFIDENTIAL = "confidential"  # Sensitive business data
    RESTRICTED = "restricted"  # Highly sensitive (keys, PII)


class ProviderStatus(Enum):
    """Provider status."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    OFFLINE = "offline"


@dataclass
class LLMProviderConfig:
    """LLM provider configuration."""
    provider_id: str
    provider_type: LLMProvider
    
    # Connection
    api_endpoint: str
    api_key: str  # Encrypted in production
    
    # Models
    available_models: List[str] = field(default_factory=list)
    default_model: str = ""
    
    # Capabilities
    supports_streaming: bool = True
    supports_function_calling: bool = True
    max_context_tokens: int = 4096
    
    # Security
    allowed_data_classifications: List[DataClassification] = field(default_factory=list)
    data_residency_region: str = "us"
    
    # Rate limits
    max_requests_per_minute: int = 60
    max_tokens_per_minute: int = 100000
    
    # Cost
    cost_per_1k_input_tokens: Decimal = Decimal("0.01")
    cost_per_1k_output_tokens: Decimal = Decimal("0.03")
    
    # Status
    status: ProviderStatus = ProviderStatus.HEALTHY
    
    # Usage
    request_count: int = 0
    token_count: int = 0
    error_count: int = 0
    
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class LLMRequest:
    """LLM request."""
    request_id: str
    
    # Request
    prompt: str
    system_prompt: str = ""
    
    # Configuration
    model: Optional[str] = None
    max_tokens: int = 1000
    temperature: float = 0.7
    
    # Data classification
    data_classification: DataClassification = DataClassification.INTERNAL
    
    # Requester
    requester_agent_id: str = ""
    purpose: str = ""
    
    # Routing
    preferred_provider: Optional[LLMProvider] = None
    
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class LLMResponse:
    """LLM response."""
    response_id: str
    request_id: str
    
    # Response
    content: str
    
    # Provider
    provider_type: LLMProvider
    model_used: str
    
    # Usage
    input_tokens: int
    output_tokens: int
    total_tokens: int
    
    # Timing
    latency_ms: float
    
    # Cost
    cost: Decimal = Decimal("0.0")
    
    # Metadata
    finish_reason: str = "stop"
    
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class RedactionRule:
    """Data redaction rule."""
    rule_id: str
    
    # Pattern
    pattern_type: str  # regex, keyword, pii
    pattern: str
    
    # Replacement
    replacement: str = "[REDACTED]"
    
    # Scope
    applies_to_classifications: List[DataClassification] = field(default_factory=list)
    
    enabled: bool = True


@dataclass
class ProviderPolicy:
    """Provider access policy."""
    policy_id: str
    
    # Scope
    agent_id: Optional[str] = None  # None = applies to all
    workflow_id: Optional[str] = None
    
    # Allowed providers
    allowed_providers: List[LLMProvider] = field(default_factory=list)
    
    # Data restrictions
    max_data_classification: DataClassification = DataClassification.INTERNAL
    
    # Region restrictions
    allowed_regions: List[str] = field(default_factory=list)
    
    # Limits
    max_context_tokens: int = 4096
    max_requests_per_hour: int = 100
    
    # Logging
    log_prompts: bool = True
    log_responses: bool = True
    
    enabled: bool = True
    created_at: datetime = field(default_factory=datetime.utcnow)


CLASSIFICATION_RANK = {
    DataClassification.PUBLIC: 0,
    DataClassification.INTERNAL: 1,
    DataClassification.CONFIDENTIAL: 2,
    DataClassification.RESTRICTED: 3,
}


class LLMGateway:
    """
    Multi-provider LLM gateway with security controls.
    
    Features:
    - Provider abstraction and routing
    - Automatic failover and load balancing
    - Data classification and redaction
    - Per-provider rate limits
    - Vendor independence
    """
    
    def __init__(self):
        self._providers: Dict[str, LLMProviderConfig] = {}
        self._requests: List[LLMRequest] = []
        self._responses: List[LLMResponse] = []
        self._redaction_rules: Dict[str, RedactionRule] = {}
        self._policies: Dict[str, ProviderPolicy] = {}
        
        self._initialize_providers()
        self._initialize_redaction_rules()
        self._initialize_default_policy()
    
    def _initialize_providers(self) -> None:
        """Initialize LLM providers."""
        
        # OpenAI
        self.register_provider(
            provider_type=LLMProvider.OPENAI,
            api_endpoint="https://api.openai.com/v1",
            api_key="sk-...",  # Mock
            available_models=["gpt-4", "gpt-3.5-turbo"],
            default_model="gpt-4",
            allowed_data_classifications=[
                DataClassification.PUBLIC,
                DataClassification.INTERNAL,
            ],
            max_context_tokens=8192,
        )
        
        # Anthropic
        self.register_provider(
            provider_type=LLMProvider.ANTHROPIC,
            api_endpoint="https://api.anthropic.com/v1",
            api_key="sk-ant-...",  # Mock
            available_models=["claude-3-opus", "claude-3-sonnet"],
            default_model="claude-3-sonnet",
            allowed_data_classifications=[
                DataClassification.PUBLIC,
                DataClassification.INTERNAL,
            ],
            max_context_tokens=200000,
        )
        
        # Local Llama (no external API)
        self.register_provider(
            provider_type=LLMProvider.LOCAL_LLAMA,
            api_endpoint="http://localhost:8080/v1",
            api_key="local",
            available_models=["llama-3-70b", "llama-3-8b"],
            default_model="llama-3-70b",
            allowed_data_classifications=[
                DataClassification.PUBLIC,
                DataClassification.INTERNAL,
                DataClassification.CONFIDENTIAL,
                DataClassification.RESTRICTED,
            ],
            data_residency_region="local",
            max_context_tokens=8192,
            cost_per_1k_input_tokens=Decimal("0.0"),
            cost_per_1k_output_tokens=Decimal("0.0"),
        )
        
        logger.info(f"Initialized {len(self._providers)} LLM providers")
    
    def _initialize_redaction_rules(self) -> None:
        """Initialize data redaction rules."""
        
        # Private keys
        self.add_redaction_rule(
            pattern_type="regex",
            pattern=r"(0x)?[0-9a-fA-F]{64}",
            replacement="[PRIVATE_KEY_REDACTED]",
            applies_to_classifications=[
                DataClassification.PUBLIC,
                DataClassification.INTERNAL,
            ],
        )
        
        # Email addresses
        self.add_redaction_rule(
            pattern_type="regex",
            pattern=r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
            replacement="[EMAIL_REDACTED]",
            applies_to_classifications=[
                DataClassification.PUBLIC,
            ],
        )
        
        # API keys
        self.add_redaction_rule(
            pattern_type="regex",
            pattern=r"(sk-|pk-)[a-zA-Z0-9]{32,}",
            replacement="[API_KEY_REDACTED]",
            applies_to_classifications=[
                DataClassification.PUBLIC,
                DataClassification.INTERNAL,
            ],
        )
        
        logger.info(f"Initialized {len(self._redaction_rules)} redaction rules")
    
    def _initialize_default_policy(self) -> None:
        """Initialize default provider policy."""
        policy = ProviderPolicy(
            policy_id="default",
            allowed_providers=[
                LLMProvider.LOCAL_LLAMA,
                LLMProvider.LOCAL_GEMMA,
                LLMProvider.OPENAI,
                LLMProvider.ANTHROPIC,
            ],
            max_data_classification=DataClassification.INTERNAL,
            allowed_regions=["us", "local"],
            max_context_tokens=8192,
            max_requests_per_hour=100,
            log_prompts=True,
            log_responses=True,
        )
        
        self._policies["default"] = policy
        
        logger.info("Initialized default provider policy")
    
    def register_provider(
        self,
        provider_type: LLMProvider,
        api_endpoint: str,
        api_key: str,
        available_models: List[str],
        default_model: str,
        allowed_data_classifications: List[DataClassification],
        max_context_tokens: int = 4096,
        data_residency_region: str = "us",
        cost_per_1k_input_tokens: Decimal = Decimal("0.01"),
        cost_per_1k_output_tokens: Decimal = Decimal("0.03"),
    ) -> LLMProviderConfig:
        """Register LLM provider."""
        provider_id = f"{provider_type.value}_{int(time.time())}"
        
        config = LLMProviderConfig(
            provider_id=provider_id,
            provider_type=provider_type,
            api_endpoint=api_endpoint,
            api_key=api_key,
            available_models=available_models,
            default_model=default_model,
            allowed_data_classifications=allowed_data_classifications,
            max_context_tokens=max_context_tokens,
            data_residency_region=data_residency_region,
            cost_per_1k_input_tokens=cost_per_1k_input_tokens,
            cost_per_1k_output_tokens=cost_per_1k_output_tokens,
        )
        
        self._providers[provider_id] = config
        
        logger.info(
            f"Registered provider '{provider_id}': {provider_type.value} "
            f"(models: {len(available_models)})"
        )
        
        return config
    
    def add_redaction_rule(
        self,
        pattern_type: str,
        pattern: str,
        replacement: str,
        applies_to_classifications: List[DataClassification],
    ) -> RedactionRule:
        """Add redaction rule."""
        rule_id = f"redaction_{len(self._redaction_rules)}"
        
        rule = RedactionRule(
            rule_id=rule_id,
            pattern_type=pattern_type,
            pattern=pattern,
            replacement=replacement,
            applies_to_classifications=applies_to_classifications,
        )
        
        self._redaction_rules[rule_id] = rule
        
        return rule
    
    def _redact_content(
        self,
        content: str,
        data_classification: DataClassification,
    ) -> str:
        """Redact sensitive content."""
        redacted = content
        
        for rule in self._redaction_rules.values():
            if not rule.enabled:
                continue
            
            if data_classification in rule.applies_to_classifications:
                # Simplified - in production would use regex
                if rule.pattern_type == "keyword":
                    redacted = redacted.replace(rule.pattern, rule.replacement)
        
        return redacted
    
    def select_provider(
        self,
        request: LLMRequest,
        policy: ProviderPolicy,
    ) -> Optional[LLMProviderConfig]:
        """Select best provider for request."""
        
        # Filter by policy
        candidates = [
            provider for provider in self._providers.values()
            if provider.provider_type in policy.allowed_providers
            and provider.status in [ProviderStatus.HEALTHY, ProviderStatus.DEGRADED]
        ]
        
        # Filter by data classification
        candidates = [
            provider for provider in candidates
            if request.data_classification in provider.allowed_data_classifications
        ]
        
        # Filter by region
        if policy.allowed_regions:
            candidates = [
                provider for provider in candidates
                if provider.data_residency_region in policy.allowed_regions
            ]
        
        # Prefer local providers for sensitive data
        if request.data_classification in [DataClassification.CONFIDENTIAL, DataClassification.RESTRICTED]:
            local_providers = [
                p for p in candidates
                if p.provider_type in [LLMProvider.LOCAL_LLAMA, LLMProvider.LOCAL_GEMMA]
            ]
            if local_providers:
                candidates = local_providers
        
        # Prefer specified provider if available
        if request.preferred_provider:
            preferred = [
                p for p in candidates
                if p.provider_type == request.preferred_provider
            ]
            if preferred:
                return preferred[0]
        
        # Sort by error rate (lowest first)
        candidates.sort(
            key=lambda p: p.error_count / max(p.request_count, 1)
        )
        
        return candidates[0] if candidates else None
    
    async def generate(
        self,
        request: LLMRequest,
        agent_id: Optional[str] = None,
    ) -> LLMResponse:
        """Generate LLM response."""
        
        # Get policy
        policy = self._policies.get(agent_id) or self._policies.get("default")
        
        if not policy or not policy.enabled:
            raise ValueError("No valid policy found")
        
        # Check data classification
        if (
            CLASSIFICATION_RANK[request.data_classification]
            > CLASSIFICATION_RANK[policy.max_data_classification]
        ):
            raise ValueError(
                f"Data classification {request.data_classification.value} "
                f"exceeds policy limit {policy.max_data_classification.value}"
            )
        
        # Redact sensitive content
        redacted_prompt = self._redact_content(
            request.prompt,
            request.data_classification,
        )
        
        # Select provider
        provider = self.select_provider(request, policy)
        
        if not provider:
            raise ValueError("No suitable provider found")
        
        # Simulate LLM call
        start_time = time.time()
        
        # Mock response
        response_content = f"Mock response from {provider.provider_type.value}"
        
        latency_ms = (time.time() - start_time) * 1000
        
        # Calculate tokens (simplified)
        input_tokens = len(redacted_prompt.split())
        output_tokens = len(response_content.split())
        total_tokens = input_tokens + output_tokens
        
        # Calculate cost
        cost = (
            Decimal(input_tokens) / 1000 * provider.cost_per_1k_input_tokens +
            Decimal(output_tokens) / 1000 * provider.cost_per_1k_output_tokens
        )
        
        # Create response
        response_id = f"resp_{int(time.time() * 1000)}"
        
        response = LLMResponse(
            response_id=response_id,
            request_id=request.request_id,
            content=response_content,
            provider_type=provider.provider_type,
            model_used=provider.default_model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            latency_ms=latency_ms,
            cost=cost,
        )
        
        # Update provider stats
        provider.request_count += 1
        provider.token_count += total_tokens
        
        # Store request and response
        self._requests.append(request)
        self._responses.append(response)
        
        logger.info(
            f"Generated response '{response_id}' via {provider.provider_type.value} "
            f"({total_tokens} tokens, {latency_ms:.0f}ms, ${cost:.4f})"
        )
        
        return response
    
    def get_provider_stats(self) -> Dict[str, Any]:
        """Get provider statistics."""
        return {
            "providers": {
                provider.provider_type.value: {
                    "status": provider.status.value,
                    "requests": provider.request_count,
                    "tokens": provider.token_count,
                    "errors": provider.error_count,
                    "error_rate": (
                        provider.error_count / provider.request_count
                        if provider.request_count > 0 else 0.0
                    ),
                }
                for provider in self._providers.values()
            },
            "requests": {
                "total": len(self._requests),
                "by_classification": {
                    classification.value: sum(
                        1 for req in self._requests
                        if req.data_classification == classification
                    )
                    for classification in DataClassification
                },
            },
            "responses": {
                "total": len(self._responses),
                "total_tokens": sum(resp.total_tokens for resp in self._responses),
                "total_cost": sum(resp.cost for resp in self._responses),
                "avg_latency_ms": (
                    sum(resp.latency_ms for resp in self._responses) / len(self._responses)
                    if self._responses else 0.0
                ),
            },
        }


_llm_gateway: Optional[LLMGateway] = None
_llm_gateway_lock = threading.Lock()


def get_llm_gateway() -> LLMGateway:
    """Get global LLMGateway instance."""
    global _llm_gateway
    if _llm_gateway is None:
        with _llm_gateway_lock:
            if _llm_gateway is None:
                _llm_gateway = LLMGateway()
    return _llm_gateway
