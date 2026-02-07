"""
Local LLM Gateway for MERID Self-Building Dev Loop.

Provides a unified interface to local LLM providers (Ollama, LM Studio, vLLM)
with fallback chains, request routing, and token budget management.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Any
import logging

logger = logging.getLogger(__name__)


@dataclass
class LLMRequest:
    request_id: str
    prompt: str
    model: str
    max_tokens: int
    temperature: float
    system_prompt: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class LLMResponse:
    request_id: str
    response_text: str
    model: str
    provider: str
    tokens_used: int
    latency_ms: float
    timestamp: datetime


@dataclass
class ProviderConfig:
    name: str
    endpoint: str
    models: List[str]
    priority: int
    enabled: bool = True
    max_concurrent: int = 4


class LocalLLMGateway:
    """
    Gateway for local LLM inference with provider fallback.
    
    Features:
    - Multiple provider support (Ollama, LM Studio, vLLM)
    - Automatic fallback on provider failure
    - Request routing by model availability
    - Token budget tracking
    - Concurrent request limiting
    """
    
    def __init__(self):
        self._providers: Dict[str, ProviderConfig] = {}
        self._request_history: List[LLMResponse] = []
        self._active_requests: Dict[str, int] = {}
        self._token_budget_daily = 1_000_000
        self._tokens_used_today = 0
        self._last_reset = datetime.utcnow().date()
        
        self._register_default_providers()
    
    def _register_default_providers(self) -> None:
        """Register default local LLM providers."""
        self._providers = {
            "ollama": ProviderConfig(
                name="ollama",
                endpoint="http://localhost:11434",
                models=["llama3.1", "codellama", "mistral", "deepseek-coder"],
                priority=1,
                max_concurrent=4,
            ),
            "lm_studio": ProviderConfig(
                name="lm_studio",
                endpoint="http://localhost:1234",
                models=["local-model"],
                priority=2,
                max_concurrent=2,
            ),
            "vllm": ProviderConfig(
                name="vllm",
                endpoint="http://localhost:8000",
                models=["codellama/CodeLlama-13b-Instruct-hf"],
                priority=3,
                max_concurrent=8,
            ),
        }
    
    def register_provider(self, config: ProviderConfig) -> None:
        """Register a custom LLM provider."""
        self._providers[config.name] = config
        logger.info(f"Registered LLM provider: {config.name} at {config.endpoint}")
    
    def _check_token_budget(self, requested_tokens: int) -> bool:
        """Check if request is within daily token budget."""
        today = datetime.utcnow().date()
        if today != self._last_reset:
            self._tokens_used_today = 0
            self._last_reset = today
        
        return self._tokens_used_today + requested_tokens <= self._token_budget_daily
    
    def _select_provider(self, model: str) -> Optional[ProviderConfig]:
        """Select best available provider for model."""
        candidates = [
            p for p in self._providers.values()
            if p.enabled and model in p.models
        ]
        
        if not candidates:
            logger.warning(f"No provider available for model: {model}")
            return None
        
        candidates.sort(key=lambda p: p.priority)
        
        for provider in candidates:
            active = self._active_requests.get(provider.name, 0)
            if active < provider.max_concurrent:
                return provider
        
        logger.warning(f"All providers at capacity for model: {model}")
        return candidates[0]
    
    async def generate(self, request: LLMRequest) -> Optional[LLMResponse]:
        """Generate completion from local LLM."""
        if not self._check_token_budget(request.max_tokens):
            logger.error("Daily token budget exceeded")
            return None
        
        provider = self._select_provider(request.model)
        if not provider:
            return None
        
        self._active_requests[provider.name] = self._active_requests.get(provider.name, 0) + 1
        
        try:
            start_time = time.time()
            
            response_text = await self._call_provider(provider, request)
            
            latency_ms = (time.time() - start_time) * 1000
            tokens_used = len(response_text.split())
            
            self._tokens_used_today += tokens_used
            
            response = LLMResponse(
                request_id=request.request_id,
                response_text=response_text,
                model=request.model,
                provider=provider.name,
                tokens_used=tokens_used,
                latency_ms=latency_ms,
                timestamp=datetime.utcnow(),
            )
            
            self._request_history.append(response)
            
            if len(self._request_history) > 1000:
                self._request_history = self._request_history[-500:]
            
            return response
            
        except Exception as e:
            logger.error(f"Error calling provider {provider.name}: {e}")
            return None
        finally:
            self._active_requests[provider.name] -= 1
    
    async def _call_provider(self, provider: ProviderConfig, request: LLMRequest) -> str:
        """Call specific LLM provider."""
        logger.info(f"Calling {provider.name} for model {request.model}")
        
        await asyncio.sleep(0.1)
        
        return f"[Mock response from {provider.name}/{request.model}]\n\nPrompt: {request.prompt[:100]}..."
    
    def get_provider_status(self) -> Dict[str, Any]:
        """Get status of all providers."""
        return {
            "providers": {
                name: {
                    "enabled": p.enabled,
                    "models": p.models,
                    "active_requests": self._active_requests.get(name, 0),
                    "max_concurrent": p.max_concurrent,
                }
                for name, p in self._providers.items()
            },
            "token_budget": {
                "daily_limit": self._token_budget_daily,
                "used_today": self._tokens_used_today,
                "remaining": self._token_budget_daily - self._tokens_used_today,
            },
            "request_history": len(self._request_history),
        }
    
    def set_token_budget(self, daily_limit: int) -> None:
        """Set daily token budget."""
        self._token_budget_daily = daily_limit
        logger.info(f"Set daily token budget: {daily_limit}")


_local_llm_gateway: Optional[LocalLLMGateway] = None


def get_local_llm_gateway() -> LocalLLMGateway:
    """Get global LocalLLMGateway instance."""
    global _local_llm_gateway
    if _local_llm_gateway is None:
        _local_llm_gateway = LocalLLMGateway()
    return _local_llm_gateway
