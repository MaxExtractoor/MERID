"""
External Integrations Configuration for MERID
Configuration for external APIs and services
"""

import os
from typing import Dict, Any, Optional
from dataclasses import dataclass
from enum import Enum

class IntegrationStatus(Enum):
    """Status of external integration"""
    DISABLED = "disabled"
    MOCK = "mock"
    LIVE = "live"
    ERROR = "error"

@dataclass
class ExternalAPIConfig:
    """Configuration for external API"""
    name: str
    base_url: str
    api_key: Optional[str] = None
    status: IntegrationStatus = IntegrationStatus.DISABLED
    timeout_seconds: int = 30
    rate_limit_per_minute: int = 60
    
    def is_enabled(self) -> bool:
        """Check if integration is enabled"""
        return self.status in [IntegrationStatus.MOCK, IntegrationStatus.LIVE]
    
    def is_live(self) -> bool:
        """Check if integration is live"""
        return self.status == IntegrationStatus.LIVE

class ExternalIntegrations:
    """Manager for external integrations"""
    
    def __init__(self):
        self.configs = self._load_configurations()
    
    def _load_configurations(self) -> Dict[str, ExternalAPIConfig]:
        """Load external API configurations"""
        return {
            # Price Feed APIs
            "coingecko": ExternalAPIConfig(
                name="CoinGecko",
                base_url="https://api.coingecko.com/api/v3",
                api_key=os.getenv("COINGECKO_API_KEY"),
                status=IntegrationStatus.MOCK if os.getenv("COINGECKO_API_KEY") else IntegrationStatus.DISABLED,
                timeout_seconds=30,
                rate_limit_per_minute=30
            ),
            "coinmarketcap": ExternalAPIConfig(
                name="CoinMarketCap",
                base_url="https://pro-api.coinmarketcap.com/v1",
                api_key=os.getenv("COINMARKETCAP_API_KEY"),
                status=IntegrationStatus.MOCK if os.getenv("COINMARKETCAP_API_KEY") else IntegrationStatus.DISABLED,
                timeout_seconds=30,
                rate_limit_per_minute=30
            ),
            
            # Blockchain Analytics APIs
            "nansen": ExternalAPIConfig(
                name="Nansen",
                base_url="https://api.nansen.ai/v1",
                api_key=os.getenv("NANSEN_API_KEY"),
                status=IntegrationStatus.MOCK if os.getenv("NANSEN_API_KEY") else IntegrationStatus.DISABLED,
                timeout_seconds=60,
                rate_limit_per_minute=60
            ),
            "arkham": ExternalAPIConfig(
                name="Arkham",
                base_url="https://api.arkhamintelligence.com/v1",
                api_key=os.getenv("ARKHAM_API_KEY"),
                status=IntegrationStatus.MOCK if os.getenv("ARKHAM_API_KEY") else IntegrationStatus.DISABLED,
                timeout_seconds=60,
                rate_limit_per_minute=60
            ),
            
            # News APIs
            "newsapi": ExternalAPIConfig(
                name="NewsAPI",
                base_url="https://newsapi.org/v2",
                api_key=os.getenv("NEWSAPI_API_KEY"),
                status=IntegrationStatus.MOCK if os.getenv("NEWSAPI_API_KEY") else IntegrationStatus.DISABLED,
                timeout_seconds=30,
                rate_limit_per_minute=1000
            ),
            
            # Web3/Blockchain
            "ethereum": ExternalAPIConfig(
                name="Ethereum",
                base_url=os.getenv("ETHEREUM_NODE_URL", "http://localhost:8545"),
                api_key=None,  # No API key needed for node
                status=IntegrationStatus.MOCK,  # Always mock for Phase 0
                timeout_seconds=30,
                rate_limit_per_minute=100
            ),
        }
    
    def get_config(self, name: str) -> Optional[ExternalAPIConfig]:
        """Get configuration for a specific integration"""
        return self.configs.get(name)
    
    def get_enabled_integrations(self) -> Dict[str, ExternalAPIConfig]:
        """Get all enabled integrations"""
        return {name: config for name, config in self.configs.items() if config.is_enabled()}
    
    def get_live_integrations(self) -> Dict[str, ExternalAPIConfig]:
        """Get all live integrations"""
        return {name: config for name, config in self.configs.items() if config.is_live()}
    
    def enable_integration(self, name: str, status: IntegrationStatus = IntegrationStatus.MOCK) -> bool:
        """Enable an integration"""
        if name in self.configs:
            self.configs[name].status = status
            return True
        return False
    
    def disable_integration(self, name: str) -> bool:
        """Disable an integration"""
        if name in self.configs:
            self.configs[name].status = IntegrationStatus.DISABLED
            return True
        return False
    
    def get_status_summary(self) -> Dict[str, Any]:
        """Get summary of all integration statuses"""
        total = len(self.configs)
        enabled = len([c for c in self.configs.values() if c.is_enabled()])
        live = len([c for c in self.configs.values() if c.is_live()])
        disabled = len([c for c in self.configs.values() if c.status == IntegrationStatus.DISABLED])
        
        return {
            "total_integrations": total,
            "enabled": enabled,
            "live": live,
            "disabled": disabled,
            "details": {
                name: {
                    "status": config.status.value,
                    "enabled": config.is_enabled(),
                    "live": config.is_live(),
                    "has_api_key": bool(config.api_key)
                }
                for name, config in self.configs.items()
            }
        }

# Global instance
external_integrations = ExternalIntegrations()

# Convenience functions
def get_external_integrations() -> ExternalIntegrations:
    """Get the external integrations manager"""
    return external_integrations

def is_integration_enabled(name: str) -> bool:
    """Check if an integration is enabled"""
    config = external_integrations.get_config(name)
    return config.is_enabled() if config else False

def is_integration_live(name: str) -> bool:
    """Check if an integration is live"""
    config = external_integrations.get_config(name)
    return config.is_live() if config else False
