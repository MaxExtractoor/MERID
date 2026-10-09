#!/usr/bin/env python3
"""
Kalshi 15m Stack Alignment Watchdog

Implements the tiered health monitoring model:
- Tier 0: Process liveness (/api/v1/health)
- Tier 1: Core readiness (/api/v1/system/health, /api/v1/loop/status, /api/v1/agents)
- Tier 2: Deep diagnostics (/api/v1/kalshi/market-states, /api/v1/spot/prices, etc.)

Runs periodic checks and logs structured results for monitoring dashboards.
"""

import asyncio
import json
import time
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
import aiohttp
import logging

# Use centralized logger from utils.logger
from utils.logger import get_logger
logger = get_logger("alignment_watchdog")


class AlignmentWatchdog:
    """Periodic tiered health monitoring for Kalshi 15m stack."""
    
    def __init__(self, base_url: str = "http://localhost:8011"):
        self.base_url = base_url.rstrip('/')
        self.session: Optional[aiohttp.ClientSession] = None
        
        # Tier definitions
        self.tier_0 = [
            {"path": "/api/v1/health", "name": "process_liveness", "critical": True}
        ]
        
        self.tier_1 = [
            {"path": "/api/v1/system/health", "name": "system_readiness", "critical": True},
            {"path": "/api/v1/loop/status", "name": "loop_status", "critical": True},
            {"path": "/api/v1/agents", "name": "agent_grid", "critical": True}
        ]
        
        self.tier_2 = [
            {"path": "/api/v1/kalshi/markets", "name": "kalshi_markets", "critical": False},
            {"path": "/api/v1/kalshi/market-states", "name": "kalshi_market_states", "critical": False},
            {"path": "/api/v1/kalshi/consensus-signals", "name": "consensus_signals", "critical": False},
            {"path": "/api/v1/spot/prices", "name": "spot_prices", "critical": False},
            {"path": "/api/v1/system/execution-gate", "name": "execution_gate", "critical": False}
        ]
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10))
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def check_endpoint(self, endpoint: Dict[str, Any]) -> Dict[str, Any]:
        """Check a single endpoint and return structured results."""
        path = endpoint["path"]
        name = endpoint["name"]
        critical = endpoint["critical"]
        
        start_time = time.time()
        result = {
            "name": name,
            "path": path,
            "tier": "unknown",
            "critical": critical,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": "unknown",
            "response_time_ms": 0,
            "http_status": None,
            "payload_valid": False,
            "payload_shape": {},
            "error": None
        }
        
        try:
            url = f"{self.base_url}{path}"
            async with self.session.get(url) as response:
                result["http_status"] = response.status
                result["response_time_ms"] = round((time.time() - start_time) * 1000, 2)
                
                if response.status == 200:
                    result["status"] = "healthy"
                    try:
                        data = await response.json()
                        result["payload_valid"] = True
                        result["payload_shape"] = self._extract_shape(data)
                        
                        # Validate specific endpoint expectations
                        validation_result = self._validate_endpoint_payload(name, data)
                        result.update(validation_result)
                        
                    except json.JSONDecodeError:
                        result["status"] = "invalid_json"
                        result["error"] = "Response is not valid JSON"
                elif response.status == 503:
                    result["status"] = "service_unavailable"
                    result["error"] = "Service temporarily unavailable"
                else:
                    result["status"] = "unhealthy"
                    result["error"] = f"HTTP {response.status}"
                    
        except asyncio.TimeoutError:
            result["status"] = "timeout"
            result["error"] = "Request timed out"
        except aiohttp.ClientError as e:
            result["status"] = "connection_error"
            result["error"] = str(e)
        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)
        
        return result
    
    def _extract_shape(self, data: Any) -> Dict[str, Any]:
        """Extract the shape/structure of a payload for validation."""
        if isinstance(data, dict):
            return {k: type(v).__name__ for k, v in data.items()}
        elif isinstance(data, list):
            return {"type": "list", "length": len(data), "item_type": type(data[0]).__name__ if data else "unknown"}
        else:
            return {"type": type(data).__name__}
    
    def _validate_endpoint_payload(self, name: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate specific payload expectations for each endpoint."""
        validation = {"payload_validation": "passed", "validation_details": {}}
        
        try:
            if name == "process_liveness":
                # Expect: status, startup_completed, etc.
                required = ["status"]
                validation["validation_details"]["required_fields"] = all(field in data for field in required)
                
            elif name == "system_readiness":
                # Expect: ready, services dict with critical components
                validation["validation_details"]["ready_field"] = data.get("ready", False)
                validation["validation_details"]["services_present"] = "services" in data
                
                if "services" in data:
                    services = data["services"]
                    critical_services = ["agent_grid_15m", "kalshi_loop_15m", "spot_service"]
                    validation["validation_details"]["critical_services_ok"] = all(
                        services.get(svc) in ["running", "initialized"] for svc in critical_services
                    )
                
            elif name == "agent_grid":
                # Expect: initialized should be true, agents array
                validation["validation_details"]["initialized"] = data.get("initialized", False)
                validation["validation_details"]["has_agents"] = "agents" in data and len(data["agents"]) > 0
                
            elif name == "loop_status":
                # Expect: running field
                validation["validation_details"]["running"] = data.get("running", False)
                
            elif name == "spot_prices":
                # Expect: assets dict with 5 assets (BTC, ETH, SOL, XRP, DOGE)
                validation["validation_details"]["has_assets"] = "assets" in data
                if "assets" in data:
                    assets = data["assets"]
                    expected_assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
                    validation["validation_details"]["expected_assets_present"] = all(
                        asset in assets for asset in expected_assets
                    )
                    validation["validation_details"]["asset_count"] = len(assets)
                
            elif name == "kalshi_market_states":
                # Expect: states dict, count field
                validation["validation_details"]["has_states"] = "states" in data
                validation["validation_details"]["has_count"] = "count" in data
                
            else:
                validation["validation_details"]["generic_validation"] = "no_specific_checks"
                
        except Exception as e:
            validation["payload_validation"] = "failed"
            validation["validation_error"] = str(e)
        
        return validation
    
    async def run_tier_checks(self, tier: List[Dict[str, Any]], tier_name: str) -> List[Dict[str, Any]]:
        """Run checks for a specific tier."""
        logger.info(f"Running {tier_name} checks ({len(tier)} endpoints)")
        
        # Add tier info to each endpoint
        for endpoint in tier:
            endpoint["tier"] = tier_name
        
        # Run checks concurrently
        tasks = [self.check_endpoint(endpoint) for endpoint in tier]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Filter exceptions
        valid_results = []
        for result in results:
            if isinstance(result, Exception):
                logger.error(f"Check failed with exception: {result}")
                continue
            valid_results.append(result)
        
        return valid_results
    
    async def run_all_checks(self) -> Dict[str, Any]:
        """Run all tiered checks and return comprehensive results."""
        logger.info("Starting comprehensive alignment check")
        
        start_time = time.time()
        
        # Run all tiers
        tier_0_results = await self.run_tier_checks(self.tier_0, "Tier_0")
        tier_1_results = await self.run_tier_checks(self.tier_1, "Tier_1")
        tier_2_results = await self.run_tier_checks(self.tier_2, "Tier_2")
        
        all_results = tier_0_results + tier_1_results + tier_2_results
        
        # Calculate summary statistics
        summary = self._calculate_summary(all_results)
        
        total_time = time.time() - start_time
        
        comprehensive_result = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "total_duration_seconds": round(total_time, 3),
            "summary": summary,
            "tier_0": {"name": "Process Liveness", "results": tier_0_results},
            "tier_1": {"name": "Core Readiness", "results": tier_1_results},
            "tier_2": {"name": "Deep Diagnostics", "results": tier_2_results},
            "all_results": all_results
        }
        
        logger.info(f"Alignment check completed: {summary['healthy_count']}/{summary['total_count']} healthy")
        
        return comprehensive_result
    
    def _calculate_summary(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Calculate summary statistics from check results."""
        total = len(results)
        healthy = len([r for r in results if r["status"] == "healthy"])
        critical_failures = len([r for r in results if r["critical"] and r["status"] != "healthy"])
        
        # Status breakdown
        status_counts = {}
        for result in results:
            status = result["status"]
            status_counts[status] = status_counts.get(status, 0) + 1
        
        return {
            "total_count": total,
            "healthy_count": healthy,
            "unhealthy_count": total - healthy,
            "critical_failures": critical_failures,
            "overall_status": "healthy" if critical_failures == 0 else "degraded",
            "status_breakdown": status_counts,
            "health_percentage": round((healthy / total * 100) if total > 0 else 0, 1)
        }
    
    def log_results(self, results: Dict[str, Any]) -> None:
        """Log structured results for monitoring systems."""
        # Log summary
        summary = results["summary"]
        logger.info(
            f"ALIGNMENT_CHECK | status={summary['overall_status']} | "
            f"healthy={summary['healthy_count']}/{summary['total_count']} | "
            f"critical_failures={summary['critical_failures']} | "
            f"duration={results['total_duration_seconds']}s"
        )
        
        # Log individual failures
        for result in results["all_results"]:
            if result["status"] != "healthy":
                logger.warning(
                    f"ENDPOINT_FAILURE | name={result['name']} | path={result['path']} | "
                    f"tier={result['tier']} | status={result['status']} | "
                    f"http_status={result['http_status']} | error={result['error']}"
                )
        
        # Write detailed JSON to file
        with open("alignment_check_results.json", "w") as f:
            json.dump(results, f, indent=2, default=str)


async def main():
    """Main entry point for the alignment watchdog."""
    logger.info("Starting Kalshi 15m Alignment Watchdog")
    
    async with AlignmentWatchdog() as watchdog:
        # Run initial check
        results = await watchdog.run_all_checks()
        watchdog.log_results(results)
        
        # You could add periodic checks here:
        # while True:
        #     await asyncio.sleep(60)  # Check every minute
        #     results = await watchdog.run_all_checks()
        #     watchdog.log_results(results)


if __name__ == "__main__":
    asyncio.run(main())
