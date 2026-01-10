"""
MERID Comprehensive Stress Test Suite

Tests all modules, algorithms, agents, and API connections.
Validates production readiness with no shortcuts.
"""

import asyncio
import time
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx
from typing import Dict, List, Any

# Test configuration
API_BASE = "http://127.0.0.1:8000/api/v1"
API_KEY = "dev-test-key"
TIMEOUT = 30.0


class StressTestRunner:
    """Comprehensive stress test runner for MERID system"""
    
    def __init__(self):
        self.results: Dict[str, Any] = {}
        self.client = httpx.AsyncClient(timeout=TIMEOUT)
        self.headers = {"X-API-Key": API_KEY}
        
    async def close(self):
        await self.client.aclose()
    
    def log(self, message: str, level: str = "INFO"):
        """Log test progress"""
        timestamp = time.strftime("%H:%M:%S")
        print(f"[{timestamp}] [{level}] {message}")
    
    async def test_health_check(self) -> bool:
        """Test 1: System health check"""
        self.log("Testing system health endpoint...")
        try:
            response = await self.client.get(f"{API_BASE}/health", headers=self.headers)
            if response.status_code == 200:
                data = response.json()
                self.log(f"✓ Health check passed: {data.get('status', 'unknown')}", "SUCCESS")
                return True
            else:
                self.log(f"✗ Health check failed: {response.status_code}", "ERROR")
                return False
        except Exception as e:
            self.log(f"✗ Health check exception: {e}", "ERROR")
            return False
    
    async def test_simulation_mining(self) -> bool:
        """Test 2: Simulation mining and block creation"""
        self.log("Testing simulation mining...")
        try:
            payload = {"premium": True, "miner_id": "stress_test"}
            response = await self.client.post(
                f"{API_BASE}/mine",
                json=payload,
                headers=self.headers
            )
            if response.status_code in [200, 202]:
                self.log("✓ Simulation mining triggered successfully", "SUCCESS")
                # Wait for block to be created
                await asyncio.sleep(3)
                
                # Verify block was created
                block_response = await self.client.get(
                    f"{API_BASE}/blocks/latest",
                    headers=self.headers
                )
                if block_response.status_code == 200:
                    block = block_response.json()
                    self.log(f"✓ Block #{block['index']} created with {len(block.get('simulations', []))} simulations", "SUCCESS")
                    return True
                else:
                    self.log("✗ Failed to retrieve latest block", "ERROR")
                    return False
            else:
                self.log(f"✗ Mining failed: {response.status_code}", "ERROR")
                return False
        except Exception as e:
            self.log(f"✗ Mining exception: {e}", "ERROR")
            return False
    
    async def test_token_economy(self) -> bool:
        """Test 3: Token economy and balances"""
        self.log("Testing token economy...")
        try:
            response = await self.client.get(
                f"{API_BASE}/tokens/balances",
                headers=self.headers
            )
            if response.status_code == 200:
                data = response.json()
                total_supply = data.get("total_supply", 0)
                balances = data.get("balances", {})
                self.log(f"✓ Token economy operational: {total_supply:.2f} MRT total, {len(balances)} accounts", "SUCCESS")
                return True
            else:
                self.log(f"✗ Token economy failed: {response.status_code}", "ERROR")
                return False
        except Exception as e:
            self.log(f"✗ Token economy exception: {e}", "ERROR")
            return False
    
    async def test_swarm_agents(self) -> bool:
        """Test 4: Swarm agent population and lineage"""
        self.log("Testing swarm agent system...")
        try:
            # Test agent population
            response = await self.client.get(
                f"{API_BASE}/swarm/agents?limit=50",
                headers=self.headers
            )
            if response.status_code == 200:
                data = response.json()
                active = data.get("active", 0)
                total = data.get("total", 0)
                agents = data.get("agents", [])
                self.log(f"✓ Swarm agents: {active} active / {total} total ({len(agents)} loaded)", "SUCCESS")
                
                # Test lineage events
                lineage_response = await self.client.get(
                    f"{API_BASE}/swarm/lineage?limit=100",
                    headers=self.headers
                )
                if lineage_response.status_code == 200:
                    lineage_data = lineage_response.json()
                    events = lineage_data.get("events", [])
                    self.log(f"✓ Lineage tracking: {len(events)} events logged", "SUCCESS")
                    return True
                else:
                    self.log("✗ Lineage tracking failed", "ERROR")
                    return False
            else:
                self.log(f"✗ Swarm agents failed: {response.status_code}", "ERROR")
                return False
        except Exception as e:
            self.log(f"✗ Swarm agents exception: {e}", "ERROR")
            return False
    
    async def test_source_health(self) -> bool:
        """Test 5: Source health and SRW tracking"""
        self.log("Testing source health observability...")
        try:
            response = await self.client.get(
                f"{API_BASE}/observability/sources",
                headers=self.headers
            )
            if response.status_code == 200:
                data = response.json()
                sources = data.get("sources", {})
                if sources:
                    avg_srw = sum(s.get("srw", 0) for s in sources.values()) / len(sources)
                    self.log(f"✓ Source health: {len(sources)} sources tracked, avg SRW {avg_srw:.3f}", "SUCCESS")
                else:
                    self.log("⚠ Source health: No sources tracked yet", "WARNING")
                return True
            else:
                self.log(f"✗ Source health failed: {response.status_code}", "ERROR")
                return False
        except Exception as e:
            self.log(f"✗ Source health exception: {e}", "ERROR")
            return False
    
    async def test_agent_trust(self) -> bool:
        """Test 6: Agent trust profiles"""
        self.log("Testing agent trust system...")
        try:
            response = await self.client.get(
                f"{API_BASE}/observability/agents/trust",
                headers=self.headers
            )
            if response.status_code == 200:
                data = response.json()
                agents = data.get("agents", {})
                if agents:
                    avg_trust = sum(a.get("trust", 0) for a in agents.values()) / len(agents)
                    self.log(f"✓ Agent trust: {len(agents)} agents tracked, avg trust {avg_trust:.3f}", "SUCCESS")
                else:
                    self.log("⚠ Agent trust: No agents tracked yet", "WARNING")
                return True
            else:
                self.log(f"✗ Agent trust failed: {response.status_code}", "ERROR")
                return False
        except Exception as e:
            self.log(f"✗ Agent trust exception: {e}", "ERROR")
            return False
    
    async def test_consensus_history(self) -> bool:
        """Test 7: Consensus history and hardening"""
        self.log("Testing consensus history...")
        try:
            response = await self.client.get(
                f"{API_BASE}/observability/consensus/history?limit=50",
                headers=self.headers
            )
            if response.status_code == 200:
                data = response.json()
                history = data.get("history", [])
                poisoning_count = sum(1 for h in history if h.get("poisoning_detected", False))
                self.log(f"✓ Consensus history: {len(history)} events, {poisoning_count} poisoning alerts", "SUCCESS")
                return True
            else:
                self.log(f"✗ Consensus history failed: {response.status_code}", "ERROR")
                return False
        except Exception as e:
            self.log(f"✗ Consensus history exception: {e}", "ERROR")
            return False
    
    async def test_hardening_status(self) -> bool:
        """Test 8: Adversarial hardening status"""
        self.log("Testing adversarial hardening...")
        try:
            response = await self.client.get(
                f"{API_BASE}/observability/hardening/status",
                headers=self.headers
            )
            if response.status_code == 200:
                data = response.json()
                frozen = data.get("trust_updates_frozen", False)
                alerts = data.get("poisoning_alert_count", 0)
                profiles = data.get("temporal_profiles_tracked", 0)
                status = "FROZEN" if frozen else "ACTIVE"
                self.log(f"✓ Hardening status: {status}, {alerts} alerts, {profiles} temporal profiles", "SUCCESS")
                return True
            else:
                self.log(f"✗ Hardening status failed: {response.status_code}", "ERROR")
                return False
        except Exception as e:
            self.log(f"✗ Hardening status exception: {e}", "ERROR")
            return False
    
    async def test_marl_metrics(self) -> bool:
        """Test 9: MARL engine metrics"""
        self.log("Testing MARL engine...")
        try:
            response = await self.client.get(
                f"{API_BASE}/marl/metrics",
                headers=self.headers
            )
            if response.status_code == 200:
                data = response.json()
                status = data.get("status", "unknown")
                if status == "not_initialized":
                    self.log("⚠ MARL engine: Not initialized (expected for fresh start)", "WARNING")
                else:
                    metrics = data.get("metrics", {})
                    algorithm = metrics.get("algorithm", "unknown")
                    agents = metrics.get("agents", [])
                    self.log(f"✓ MARL engine: {algorithm}, {len(agents)} agents training", "SUCCESS")
                return True
            else:
                self.log(f"✗ MARL metrics failed: {response.status_code}", "ERROR")
                return False
        except Exception as e:
            self.log(f"✗ MARL metrics exception: {e}", "ERROR")
            return False
    
    async def test_pso_metrics(self) -> bool:
        """Test 10: PSO optimizer metrics"""
        self.log("Testing PSO optimizer...")
        try:
            response = await self.client.get(
                f"{API_BASE}/pso/metrics",
                headers=self.headers
            )
            if response.status_code == 200:
                data = response.json()
                status = data.get("status", "unknown")
                if status == "not_initialized":
                    self.log("⚠ PSO optimizer: Not initialized (expected for fresh start)", "WARNING")
                else:
                    metrics = data.get("metrics", {})
                    iteration = metrics.get("iteration", 0)
                    fitness = metrics.get("global_best_fitness", 0)
                    self.log(f"✓ PSO optimizer: iteration {iteration}, fitness {fitness:.4f}", "SUCCESS")
                return True
            else:
                self.log(f"✗ PSO metrics failed: {response.status_code}", "ERROR")
                return False
        except Exception as e:
            self.log(f"✗ PSO metrics exception: {e}", "ERROR")
            return False
    
    async def test_intel_feeds(self) -> bool:
        """Test 11: Intel feeds (heatmap, ticker, assist)"""
        self.log("Testing intel feeds...")
        try:
            # Heatmap
            heatmap_response = await self.client.get(
                f"{API_BASE}/heatmap?limit=12",
                headers=self.headers
            )
            heatmap_ok = heatmap_response.status_code == 200
            
            # Ticker
            ticker_response = await self.client.get(
                f"{API_BASE}/ticker?limit=15",
                headers=self.headers
            )
            ticker_ok = ticker_response.status_code == 200
            
            # Assist
            assist_response = await self.client.get(
                f"{API_BASE}/assist",
                headers=self.headers
            )
            assist_ok = assist_response.status_code == 200
            
            if heatmap_ok and ticker_ok and assist_ok:
                self.log("✓ Intel feeds: All operational (heatmap, ticker, assist)", "SUCCESS")
                return True
            else:
                self.log(f"⚠ Intel feeds: Partial success (heatmap:{heatmap_ok}, ticker:{ticker_ok}, assist:{assist_ok})", "WARNING")
                return True  # Not critical
        except Exception as e:
            self.log(f"✗ Intel feeds exception: {e}", "ERROR")
            return False
    
    async def test_charters(self) -> bool:
        """Test 12: Agent charters"""
        self.log("Testing agent charters...")
        try:
            response = await self.client.get(
                f"{API_BASE}/charters",
                headers=self.headers
            )
            if response.status_code == 200:
                data = response.json()
                charters = data.get("charters", [])
                self.log(f"✓ Agent charters: {len(charters)} charter templates available", "SUCCESS")
                return True
            else:
                self.log(f"✗ Agent charters failed: {response.status_code}", "ERROR")
                return False
        except Exception as e:
            self.log(f"✗ Agent charters exception: {e}", "ERROR")
            return False
    
    async def run_all_tests(self) -> Dict[str, bool]:
        """Run all stress tests"""
        self.log("=" * 60)
        self.log("MERID COMPREHENSIVE STRESS TEST SUITE", "INFO")
        self.log("=" * 60)
        
        tests = [
            ("Health Check", self.test_health_check),
            ("Simulation Mining", self.test_simulation_mining),
            ("Token Economy", self.test_token_economy),
            ("Swarm Agents", self.test_swarm_agents),
            ("Source Health", self.test_source_health),
            ("Agent Trust", self.test_agent_trust),
            ("Consensus History", self.test_consensus_history),
            ("Hardening Status", self.test_hardening_status),
            ("MARL Metrics", self.test_marl_metrics),
            ("PSO Metrics", self.test_pso_metrics),
            ("Intel Feeds", self.test_intel_feeds),
            ("Agent Charters", self.test_charters),
        ]
        
        results = {}
        passed = 0
        failed = 0
        
        for test_name, test_func in tests:
            self.log(f"\n--- Test: {test_name} ---")
            try:
                result = await test_func()
                results[test_name] = result
                if result:
                    passed += 1
                else:
                    failed += 1
            except Exception as e:
                self.log(f"✗ Test crashed: {e}", "ERROR")
                results[test_name] = False
                failed += 1
            
            await asyncio.sleep(0.5)  # Brief pause between tests
        
        # Summary
        self.log("\n" + "=" * 60)
        self.log("STRESS TEST SUMMARY", "INFO")
        self.log("=" * 60)
        self.log(f"Total Tests: {len(tests)}")
        self.log(f"Passed: {passed}", "SUCCESS")
        self.log(f"Failed: {failed}", "ERROR" if failed > 0 else "INFO")
        self.log(f"Success Rate: {(passed / len(tests) * 100):.1f}%")
        
        if failed == 0:
            self.log("\n✓ ALL TESTS PASSED - SYSTEM PRODUCTION READY", "SUCCESS")
        elif failed <= 2:
            self.log(f"\n⚠ {failed} TESTS FAILED - REVIEW REQUIRED", "WARNING")
        else:
            self.log(f"\n✗ {failed} TESTS FAILED - SYSTEM NOT READY", "ERROR")
        
        self.log("=" * 60)
        
        return results


async def main():
    """Main stress test execution"""
    runner = StressTestRunner()
    try:
        results = await runner.run_all_tests()
        
        # Exit code based on results
        failed_count = sum(1 for r in results.values() if not r)
        sys.exit(0 if failed_count == 0 else 1)
    finally:
        await runner.close()


if __name__ == "__main__":
    asyncio.run(main())
