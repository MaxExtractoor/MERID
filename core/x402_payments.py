"""
x402 Payment Protocol Adapter for MERID

HTTP 402 Payment Required protocol implementation for micropayments.
Supports Lightning Network, stablecoins, and other payment rails.
All outbound calls respect offline/VPN enforcement policies.
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from core.network_client import get_network_client
from core.environment_flags import get_environment_flags
from utils.logger import get_logger

logger = get_logger("core.x402_payments")


class PaymentRail(str, Enum):
    """Supported payment rails."""
    LIGHTNING = "lightning"
    USDC_BASE = "usdc_base"
    USDC_ARBITRUM = "usdc_arbitrum"
    ETH_MAINNET = "eth_mainnet"
    STABLECOIN_GENERIC = "stablecoin"


class PaymentStatus(str, Enum):
    """Payment status."""
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    EXPIRED = "expired"
    REFUNDED = "refunded"


@dataclass
class PaymentRequest:
    """x402 payment request."""
    request_id: str
    resource_url: str
    amount_sats: int
    amount_usd: float
    rail: PaymentRail
    invoice: str
    expires_at: float
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)


@dataclass
class PaymentReceipt:
    """Payment receipt after successful payment."""
    receipt_id: str
    request_id: str
    amount_paid: float
    rail: PaymentRail
    tx_hash: Optional[str]
    preimage: Optional[str]
    access_token: str
    expires_at: float
    timestamp: float = field(default_factory=time.time)


@dataclass
class X402Resource:
    """Resource accessible via x402 payment."""
    resource_id: str
    url: str
    description: str
    price_sats: int
    price_usd: float
    supported_rails: List[PaymentRail]
    ttl_seconds: int
    provider: str


class X402Client:
    """
    Client for x402 payment protocol.
    
    Handles:
    - Payment request parsing from 402 responses
    - Invoice generation and payment
    - Receipt verification
    - Access token management
    """
    
    def __init__(self):
        self._network_client = get_network_client()
        self._env_flags = get_environment_flags()
        
        # Register module profile
        self._network_client.register_module_profile(
            module_name="x402_client",
            required_endpoints=["payment_gateway", "lightning_node"],
            fallback_behavior="block",
        )
        
        # Payment state
        self._pending_requests: Dict[str, PaymentRequest] = {}
        self._receipts: Dict[str, PaymentReceipt] = {}
        self._access_tokens: Dict[str, str] = {}
        
        # Statistics
        self._total_payments = 0
        self._total_amount_sats = 0
        
        logger.info("X402Client initialized")
    
    def _check_network_access(self, operation: str) -> bool:
        """Check if network access is allowed."""
        if self._env_flags.offline_mode:
            logger.warning("x402 %s blocked: offline mode enabled", operation)
            return False
        
        if not self._network_client.can_call_outbound("x402_client"):
            logger.warning("x402 %s blocked: network client denied", operation)
            return False
        
        return True
    
    def parse_402_response(
        self,
        url: str,
        headers: Dict[str, str],
        body: Optional[Dict[str, Any]] = None,
    ) -> Optional[PaymentRequest]:
        """
        Parse a 402 Payment Required response.
        
        Extracts payment details from WWW-Authenticate header or body.
        """
        if not self._check_network_access("parse_402"):
            return None
        
        # Extract payment info from headers
        www_auth = headers.get("WWW-Authenticate", "")
        x402_price = headers.get("X-402-Price", "")
        x402_invoice = headers.get("X-402-Invoice", "")
        
        # Parse amount
        amount_sats = 0
        amount_usd = 0.0
        
        if x402_price:
            try:
                parts = x402_price.split()
                amount_sats = int(parts[0])
                if len(parts) > 1 and parts[1].upper() == "USD":
                    amount_usd = float(parts[0])
                    amount_sats = int(amount_usd * 100000000 / 50000)  # Rough BTC conversion
            except (ValueError, IndexError):
                pass
        
        # Determine payment rail
        rail = PaymentRail.LIGHTNING
        if "usdc" in www_auth.lower():
            rail = PaymentRail.USDC_BASE
        elif "eth" in www_auth.lower():
            rail = PaymentRail.ETH_MAINNET
        
        # Generate request ID
        request_id = hashlib.sha256(
            f"{url}:{time.time()}".encode()
        ).hexdigest()[:16]
        
        request = PaymentRequest(
            request_id=request_id,
            resource_url=url,
            amount_sats=amount_sats,
            amount_usd=amount_usd,
            rail=rail,
            invoice=x402_invoice or "",
            expires_at=time.time() + 600,  # 10 minute default
            metadata=body or {},
        )
        
        self._pending_requests[request_id] = request
        
        logger.info(
            "Parsed 402 response: %s sats for %s",
            amount_sats,
            url,
        )
        
        return request
    
    def pay_invoice(
        self,
        request: PaymentRequest,
        max_fee_sats: int = 100,
    ) -> Optional[PaymentReceipt]:
        """
        Pay a Lightning invoice or execute on-chain payment.
        """
        if not self._check_network_access("pay_invoice"):
            return None
        
        if time.time() > request.expires_at:
            logger.error("Payment request expired: %s", request.request_id)
            return None
        
        # In production:
        # - For Lightning: call LND/CLN to pay invoice
        # - For USDC: execute ERC20 transfer
        # - For ETH: execute native transfer
        
        logger.info(
            "Paying %s sats via %s for %s",
            request.amount_sats,
            request.rail.value,
            request.resource_url,
        )
        
        # Simulate payment
        preimage = hashlib.sha256(
            f"preimage:{request.request_id}".encode()
        ).hexdigest()
        
        access_token = hashlib.sha256(
            f"token:{request.request_id}:{preimage}".encode()
        ).hexdigest()
        
        receipt = PaymentReceipt(
            receipt_id=f"rcpt_{request.request_id}",
            request_id=request.request_id,
            amount_paid=request.amount_sats,
            rail=request.rail,
            tx_hash=None if request.rail == PaymentRail.LIGHTNING else f"0x{'0' * 64}",
            preimage=preimage if request.rail == PaymentRail.LIGHTNING else None,
            access_token=access_token,
            expires_at=time.time() + 3600,  # 1 hour access
        )
        
        # Store receipt and token
        self._receipts[receipt.receipt_id] = receipt
        self._access_tokens[request.resource_url] = access_token
        
        # Update statistics
        self._total_payments += 1
        self._total_amount_sats += request.amount_sats
        
        # Remove from pending
        self._pending_requests.pop(request.request_id, None)
        
        logger.info(
            "Payment completed: %s (token expires %s)",
            receipt.receipt_id,
            time.strftime("%H:%M:%S", time.localtime(receipt.expires_at)),
        )
        
        return receipt
    
    def get_access_token(self, url: str) -> Optional[str]:
        """Get valid access token for a URL."""
        token = self._access_tokens.get(url)
        
        if token:
            # Check if token is still valid
            for receipt in self._receipts.values():
                if receipt.access_token == token:
                    if time.time() < receipt.expires_at:
                        return token
                    else:
                        # Token expired
                        self._access_tokens.pop(url, None)
                        return None
        
        return None
    
    def make_authenticated_request(
        self,
        url: str,
        method: str = "GET",
        headers: Optional[Dict[str, str]] = None,
        auto_pay: bool = False,
        max_auto_pay_sats: int = 1000,
    ) -> Dict[str, Any]:
        """
        Make a request to a potentially paywalled resource.
        
        If auto_pay is True and we get a 402, automatically pay if under limit.
        """
        if not self._check_network_access("authenticated_request"):
            return {"error": "network_blocked", "status": 0}
        
        headers = headers or {}
        
        # Check for existing access token
        token = self.get_access_token(url)
        if token:
            headers["Authorization"] = f"L402 {token}"
        
        # In production, make actual HTTP request
        # For now, simulate response
        
        # Simulate 402 response for demo
        if not token and "premium" in url:
            return {
                "status": 402,
                "headers": {
                    "WWW-Authenticate": "L402",
                    "X-402-Price": "100 sats",
                    "X-402-Invoice": "lnbc100n1...",
                },
                "body": {"error": "payment_required"},
            }
        
        return {
            "status": 200,
            "headers": {},
            "body": {"data": "resource_content"},
        }
    
    def discover_resources(
        self,
        provider_url: str,
    ) -> List[X402Resource]:
        """Discover available x402 resources from a provider."""
        if not self._check_network_access("discover_resources"):
            return []
        
        # In production, query provider's resource catalog
        # For now, return sample resources
        
        return [
            X402Resource(
                resource_id="res_001",
                url=f"{provider_url}/api/premium/signals",
                description="Premium trading signals",
                price_sats=500,
                price_usd=0.25,
                supported_rails=[PaymentRail.LIGHTNING, PaymentRail.USDC_BASE],
                ttl_seconds=3600,
                provider=provider_url,
            ),
            X402Resource(
                resource_id="res_002",
                url=f"{provider_url}/api/premium/analysis",
                description="Deep market analysis",
                price_sats=1000,
                price_usd=0.50,
                supported_rails=[PaymentRail.LIGHTNING],
                ttl_seconds=7200,
                provider=provider_url,
            ),
        ]
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get payment statistics."""
        return {
            "total_payments": self._total_payments,
            "total_amount_sats": self._total_amount_sats,
            "pending_requests": len(self._pending_requests),
            "active_tokens": len(self._access_tokens),
            "receipts_stored": len(self._receipts),
        }
    
    def get_pending_requests(self) -> List[PaymentRequest]:
        """Get pending payment requests."""
        return list(self._pending_requests.values())
    
    def get_receipts(self, limit: int = 50) -> List[PaymentReceipt]:
        """Get payment receipts."""
        receipts = list(self._receipts.values())
        return sorted(receipts, key=lambda r: r.timestamp, reverse=True)[:limit]


# Singleton instance
_x402_client: Optional[X402Client] = None


def get_x402_client() -> X402Client:
    """Get the singleton x402 client."""
    global _x402_client
    if _x402_client is None:
        _x402_client = X402Client()
    return _x402_client
