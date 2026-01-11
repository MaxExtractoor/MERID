"""
MERID API Endpoint Verification.

Verifies all API endpoints are properly connected and responding.

Usage:
    python -m tests.verify_endpoints
"""

import asyncio
import time
from typing import Dict, List, Any, Optional
from dataclasses import dataclass

try:
    import httpx
except ImportError:
    httpx = None

from utils.logger import get_logger

logger = get_logger("tests.verify")


@dataclass
class EndpointCheck:
    """Result of an endpoint check."""
    path: str
    method: str
    status_code: int = 0
    response_time_ms: float = 0.0
    success: bool = False
    error: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "method": self.method,
            "status_code": self.status_code,
            "response_time_ms": round(self.response_time_ms, 2),
            "success": self.success,
            "error": self.error,
        }


# All API endpoints to verify
API_ENDPOINTS = [
    # Core endpoints
    ("GET", "/health"),
    ("GET", "/ready"),
    ("GET", "/api/status"),
    
    # Monitoring
    ("GET", "/api/v1/monitoring/status"),
    ("GET", "/api/v1/monitoring/metrics"),
    ("GET", "/api/v1/monitoring/health"),
    ("GET", "/api/v1/monitoring/system/status"),
    ("GET", "/api/v1/monitoring/performance/status"),
    ("GET", "/api/v1/monitoring/dashboard"),
    
    # Rate Limiting
    ("GET", "/api/v1/ratelimit/status"),
    ("GET", "/api/v1/ratelimit/rules"),
    ("GET", "/api/v1/ratelimit/blocked"),
    ("GET", "/api/v1/ratelimit/whitelist"),
    ("GET", "/api/v1/ratelimit/throttle"),
    
    # Backup
    ("GET", "/api/v1/backup/status"),
    ("GET", "/api/v1/backup/snapshots/status"),
    ("GET", "/api/v1/backup/snapshots"),
    ("GET", "/api/v1/backup/schedules"),
    ("GET", "/api/v1/backup/recovery/status"),
    ("GET", "/api/v1/backup/recovery/points"),
    
    # Plugins
    ("GET", "/api/v1/plugins/status"),
    ("GET", "/api/v1/plugins/discover"),
    ("GET", "/api/v1/plugins/hooks"),
    ("GET", "/api/v1/plugins/sandbox"),
    ("GET", "/api/v1/plugins/registry/statistics"),
    
    # Compliance
    ("GET", "/api/v1/compliance/status"),
    ("GET", "/api/v1/compliance/dashboard"),
    ("GET", "/api/v1/compliance/audit/status"),
    ("GET", "/api/v1/compliance/transactions/status"),
    ("GET", "/api/v1/compliance/reports/status"),
    ("GET", "/api/v1/compliance/retention/status"),
    
    # Notifications
    ("GET", "/api/v1/notifications/status"),
    ("GET", "/api/v1/notifications/channels"),
    ("GET", "/api/v1/notifications/rules"),
    ("GET", "/api/v1/notifications/escalations"),
    
    # Offline
    ("GET", "/api/v1/offline/status"),
    ("GET", "/api/v1/offline/cache/status"),
    ("GET", "/api/v1/offline/replay/status"),
    
    # Wallet
    ("GET", "/api/v1/wallet/status"),
    ("GET", "/api/v1/wallet/vaults"),
    ("GET", "/api/v1/wallet/walletconnect/sessions"),
    
    # Arbitrage
    ("GET", "/api/v1/arbitrage/status"),
    ("GET", "/api/v1/arbitrage/scanners"),
    ("GET", "/api/v1/arbitrage/opportunities"),
    ("GET", "/api/v1/arbitrage/gate/status"),
    
    # Prediction
    ("GET", "/api/v1/prediction/status"),
    ("GET", "/api/v1/prediction/oracle/status"),
    ("GET", "/api/v1/prediction/resolution/status"),
    
    # Schemas
    ("GET", "/api/v1/schemas"),
    
    # Agents
    ("GET", "/api/v1/agents"),
    ("GET", "/api/v1/agents/status"),
    
    # Consensus
    ("GET", "/api/v1/consensus/status"),
    ("GET", "/api/v1/consensus/proposals"),
    
    # Simulation
    ("GET", "/api/v1/simulation/status"),
    
    # Intelligence
    ("GET", "/api/v1/intelligence/signals"),
    
    # Paper Trading
    ("GET", "/api/v1/paper/status"),
    ("GET", "/api/v1/paper/positions"),
    
    # System Control
    ("GET", "/api/v1/system/status"),
    
    # Data
    ("GET", "/api/v1/data/prices"),
    
    # Charters
    ("GET", "/api/v1/charters"),
]


class EndpointVerifier:
    """Verifies all API endpoints."""
    
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.results: List[EndpointCheck] = []
    
    async def verify_endpoint(self, method: str, path: str) -> EndpointCheck:
        """Verify a single endpoint."""
        check = EndpointCheck(path=path, method=method)
        
        if httpx is None:
            check.error = "httpx not installed"
            return check
        
        start = time.time()
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                if method == "GET":
                    response = await client.get(f"{self.base_url}{path}")
                elif method == "POST":
                    response = await client.post(f"{self.base_url}{path}", json={})
                else:
                    response = await client.request(method, f"{self.base_url}{path}")
                
                check.status_code = response.status_code
                check.response_time_ms = (time.time() - start) * 1000
                check.success = response.status_code < 500
                
        except httpx.ConnectError:
            check.error = "Connection refused - is the server running?"
        except httpx.TimeoutException:
            check.error = "Request timed out"
        except Exception as e:
            check.error = str(e)
        
        return check
    
    async def verify_all(self) -> Dict[str, Any]:
        """Verify all endpoints."""
        print("=" * 60)
        print("MERID API ENDPOINT VERIFICATION")
        print("=" * 60)
        print(f"Base URL: {self.base_url}")
        print(f"Endpoints to check: {len(API_ENDPOINTS)}")
        print("-" * 60)
        
        self.results = []
        
        for method, path in API_ENDPOINTS:
            check = await self.verify_endpoint(method, path)
            self.results.append(check)
            
            status = "OK" if check.success else "FAIL"
            status_code = check.status_code if check.status_code else "---"
            time_str = f"{check.response_time_ms:.0f}ms" if check.response_time_ms else "---"
            
            print(f"[{status:4}] {method:4} {path:50} {status_code:3} {time_str:>8}")
            
            if check.error:
                print(f"       Error: {check.error}")
        
        # Summary
        successful = sum(1 for r in self.results if r.success)
        failed = len(self.results) - successful
        avg_time = sum(r.response_time_ms for r in self.results if r.response_time_ms) / max(successful, 1)
        
        print("-" * 60)
        print(f"RESULTS: {successful}/{len(self.results)} endpoints OK")
        print(f"Average response time: {avg_time:.1f}ms")
        
        if failed > 0:
            print(f"\nFailed endpoints ({failed}):")
            for r in self.results:
                if not r.success:
                    print(f"  - {r.method} {r.path}: {r.error or f'Status {r.status_code}'}")
        
        print("=" * 60)
        
        return {
            "total": len(self.results),
            "successful": successful,
            "failed": failed,
            "success_rate": (successful / len(self.results) * 100) if self.results else 0,
            "avg_response_time_ms": avg_time,
            "results": [r.to_dict() for r in self.results],
        }


async def main():
    """Run endpoint verification."""
    import argparse
    
    parser = argparse.ArgumentParser(description="MERID API Endpoint Verification")
    parser.add_argument("--url", default="http://localhost:8000", help="Base URL")
    args = parser.parse_args()
    
    verifier = EndpointVerifier(base_url=args.url)
    await verifier.verify_all()


if __name__ == "__main__":
    asyncio.run(main())
