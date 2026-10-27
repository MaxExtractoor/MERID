"""
Bankroll Service Diagnostic Script

Exposes flaws, gaps, and wiring issues in the bankroll service that may be
causing order submission hangs.

Run: py scripts/diagnose_bankroll_service.py
"""

import asyncio
import time
import sys
import os
from datetime import datetime
from typing import Optional, Dict, Any
import traceback

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from merid.event_venues.kalshi.bankroll_service_v2 import (
    get_bankroll_service,
    BankrollServiceV2,
    BankrollSummary,
    _BANKROLL_SUMMARY_TIMEOUT_S,
    get_summary_sync,
)


class BankrollDiagnostics:
    """Comprehensive diagnostics for bankroll service issues."""
    
    def __init__(self):
        self.issues = []
        self.warnings = []
        self.info = []
        self.results = {}
        
    def log_issue(self, category: str, message: str, severity: str = "HIGH"):
        """Log an issue found during diagnostics."""
        self.issues.append({
            "category": category,
            "message": message,
            "severity": severity,
            "timestamp": datetime.now().isoformat()
        })
        print(f"❌ [{severity}] {category}: {message}")
        
    def log_warning(self, category: str, message: str):
        """Log a warning."""
        self.warnings.append({
            "category": category,
            "message": message,
            "timestamp": datetime.now().isoformat()
        })
        print(f"⚠️  [WARNING] {category}: {message}")
        
    def log_info(self, category: str, message: str):
        """Log informational finding."""
        self.info.append({
            "category": category,
            "message": message,
            "timestamp": datetime.now().isoformat()
        })
        print(f"ℹ️  [INFO] {category}: {message}")
        
    def check_timeout_configuration(self):
        """Check if timeout configuration is appropriate."""
        print("\n" + "="*60)
        print("CHECK 1: Timeout Configuration")
        print("="*60)
        
        timeout = _BANKROLL_SUMMARY_TIMEOUT_S
        print(f"Current timeout: {timeout}s")
        
        if timeout < 5:
            self.log_issue("TIMEOUT_CONFIG", 
                          f"Timeout too low ({timeout}s). Should be at least 10-30s for reliable operation.",
                          "HIGH")
        elif timeout < 15:
            self.log_warning("TIMEOUT_CONFIG",
                            f"Timeout may be too low ({timeout}s). Consider increasing to 20-30s.")
        else:
            self.log_info("TIMEOUT_CONFIG", f"Timeout is reasonable ({timeout}s)")
            
        self.results["timeout"] = timeout
        
    async def check_service_initialization(self):
        """Check if service can be initialized."""
        print("\n" + "="*60)
        print("CHECK 2: Service Initialization")
        print("="*60)
        
        try:
            start = time.time()
            service = await get_bankroll_service()
            init_time = time.time() - start
            
            if service is None:
                self.log_issue("SERVICE_INIT", "Service initialization returned None", "CRITICAL")
                return False
                
            print(f"✓ Service initialized in {init_time:.2f}s")
            
            if init_time > 5:
                self.log_warning("SERVICE_INIT", 
                                f"Slow initialization ({init_time:.2f}s). May cause delays.")
            else:
                self.log_info("SERVICE_INIT", f"Fast initialization ({init_time:.2f}s)")
                
            self.results["service_init_time"] = init_time
            return True
            
        except Exception as e:
            self.log_issue("SERVICE_INIT", 
                          f"Failed to initialize service: {str(e)}",
                          "CRITICAL")
            traceback.print_exc()
            return False
            
    async def check_async_fetch(self):
        """Check async bankroll fetch performance."""
        print("\n" + "="*60)
        print("CHECK 3: Async Bankroll Fetch")
        print("="*60)
        
        try:
            service = await get_bankroll_service()
            if service is None:
                self.log_issue("ASYNC_FETCH", "Service not available for async fetch", "CRITICAL")
                return
                
            # Test single fetch
            start = time.time()
            summary = await service.get_summary(caller_module="diagnostics")
            fetch_time = time.time() - start
            
            print(f"Fetch time: {fetch_time:.2f}s")
            print(f"Summary: {summary}")
            
            if summary is None:
                self.log_issue("ASYNC_FETCH", "Async fetch returned None", "HIGH")
            elif summary.equity_usd is None:
                self.log_issue("ASYNC_FETCH", 
                              "Summary returned but equity_usd is None",
                              "HIGH")
            else:
                print(f"✓ Equity: ${summary.equity_usd:.2f}")
                self.log_info("ASYNC_FETCH", f"Successful fetch in {fetch_time:.2f}s")
                
            if fetch_time > 3:
                self.log_warning("ASYNC_FETCH",
                                f"Slow async fetch ({fetch_time:.2f}s). Should be < 1s.")
            elif fetch_time > 1:
                self.log_warning("ASYNC_FETCH",
                                f"Moderately slow async fetch ({fetch_time:.2f}s).")
                
            self.results["async_fetch_time"] = fetch_time
            
            # Test multiple consecutive fetches
            print("\nTesting consecutive fetches...")
            fetch_times = []
            for i in range(5):
                start = time.time()
                summary = await service.get_summary(caller_module="diagnostics")
                fetch_time = time.time() - start
                fetch_times.append(fetch_time)
                print(f"  Fetch {i+1}: {fetch_time:.2f}s")
                
            avg_time = sum(fetch_times) / len(fetch_times)
            print(f"Average fetch time: {avg_time:.2f}s")
            self.results["avg_async_fetch_time"] = avg_time
            
            if avg_time > 2:
                self.log_issue("ASYNC_FETCH",
                              f"Consistently slow fetches (avg {avg_time:.2f}s)",
                              "HIGH")
                
        except Exception as e:
            self.log_issue("ASYNC_FETCH",
                          f"Async fetch failed: {str(e)}",
                          "CRITICAL")
            traceback.print_exc()
            
    def check_sync_fetch(self):
        """Check sync bankroll fetch via run_coroutine_threadsafe."""
        print("\n" + "="*60)
        print("CHECK 4: Sync Bankroll Fetch (run_coroutine_threadsafe)")
        print("="*60)
        
        try:
            start = time.time()
            summary = get_summary_sync(caller_module="diagnostics")
            fetch_time = time.time() - start
            
            print(f"Sync fetch time: {fetch_time:.2f}s")
            print(f"Summary: {summary}")
            
            if summary is None:
                self.log_issue("SYNC_FETCH", "Sync fetch returned None", "HIGH")
            elif summary.equity_usd is None:
                self.log_issue("SYNC_FETCH",
                              "Sync fetch returned but equity_usd is None",
                              "HIGH")
            else:
                print(f"✓ Equity: ${summary.equity_usd:.2f}")
                self.log_info("SYNC_FETCH", f"Successful sync fetch in {fetch_time:.2f}s")
                
            if fetch_time > _BANKROLL_SUMMARY_TIMEOUT_S:
                self.log_issue("SYNC_FETCH",
                              f"Sync fetch exceeded timeout ({fetch_time:.2f}s > {_BANKROLL_SUMMARY_TIMEOUT_S}s)",
                              "CRITICAL")
            elif fetch_time > 5:
                self.log_warning("SYNC_FETCH",
                                f"Slow sync fetch ({fetch_time:.2f}s). Approaching timeout.")
                
            self.results["sync_fetch_time"] = fetch_time
            
        except Exception as e:
            self.log_issue("SYNC_FETCH",
                          f"Sync fetch failed: {str(e)}",
                          "CRITICAL")
            traceback.print_exc()
            
    async def check_caching(self):
        """Check if caching is working properly."""
        print("\n" + "="*60)
        print("CHECK 5: Caching Behavior")
        print("="*60)
        
        try:
            service = await get_bankroll_service()
            if service is None:
                return
                
            # First fetch (should hit API)
            start = time.time()
            summary1 = await service.get_summary(caller_module="diagnostics")
            time1 = time.time() - start
            
            # Immediate second fetch (should use cache)
            start = time.time()
            summary2 = await service.get_summary(caller_module="diagnostics")
            time2 = time.time() - start
            
            print(f"First fetch: {time1:.2f}s")
            print(f"Second fetch: {time2:.2f}s")
            print(f"Cache speedup: {time1/time2:.2f}x")
            
            if time2 > time1 * 0.5:
                self.log_warning("CACHING",
                                f"Cache may not be working (second fetch {time2:.2f}s not much faster than first {time1:.2f}s)")
            else:
                self.log_info("CACHING", f"Cache working effectively ({time1/time2:.2f}x speedup)")
                
            self.results["cache_speedup"] = time1/time2
            
        except Exception as e:
            self.log_issue("CACHING",
                          f"Cache check failed: {str(e)}",
                          "MEDIUM")
            
    async def check_loop_threading(self):
        """Check asyncio loop and threading issues."""
        print("\n" + "="*60)
        print("CHECK 6: AsyncIO Loop and Threading")
        print("="*60)
        
        try:
            # Check if there's a running loop
            try:
                loop = asyncio.get_running_loop()
                self.log_info("LOOP", f"Running loop detected: {loop}")
            except RuntimeError:
                self.log_warning("LOOP", "No running loop detected - may cause threading issues")
                
            # Test run_coroutine_threadsafe behavior
            try:
                loop = asyncio.get_running_loop()
                
                async def test_coro():
                    await asyncio.sleep(0.1)
                    return "success"
                    
                start = time.time()
                future = asyncio.run_coroutine_threadsafe(test_coro(), loop)
                result = future.result(timeout=5.0)
                thread_time = time.time() - start
                
                print(f"run_coroutine_threadsafe test: {thread_time:.2f}s")
                
                if thread_time > 2:
                    self.log_warning("THREADING",
                                    f"Slow run_coroutine_threadsafe ({thread_time:.2f}s)")
                else:
                    self.log_info("THREADING", f"run_coroutine_threadsafe working ({thread_time:.2f}s)")
                    
                self.results["threading_test_time"] = thread_time
                
            except Exception as e:
                self.log_issue("THREADING",
                              f"Threading test failed: {str(e)}",
                              "HIGH")
                
        except Exception as e:
            self.log_issue("LOOP",
                          f"Loop check failed: {str(e)}",
                          "MEDIUM")
            
    async def check_service_state(self):
        """Check service internal state."""
        print("\n" + "="*60)
        print("CHECK 7: Service Internal State")
        print("="*60)
        
        try:
            service = await get_bankroll_service()
            if service is None:
                return
                
            # Check service attributes
            attrs_to_check = [
                'client',
                'cache',
                'last_update',
                '_cache_ttl',
            ]
            
            for attr in attrs_to_check:
                if hasattr(service, attr):
                    value = getattr(service, attr)
                    print(f"✓ {attr}: {value}")
                else:
                    self.log_warning("SERVICE_STATE", f"Missing attribute: {attr}")
                    
        except Exception as e:
            self.log_issue("SERVICE_STATE",
                          f"State check failed: {str(e)}",
                          "MEDIUM")
            
    def print_summary(self):
        """Print diagnostic summary."""
        print("\n" + "="*60)
        print("DIAGNOSTIC SUMMARY")
        print("="*60)
        
        print(f"\n📊 Results:")
        for key, value in self.results.items():
            print(f"  {key}: {value}")
            
        print(f"\n❌ Issues Found: {len(self.issues)}")
        for issue in self.issues:
            print(f"  [{issue['severity']}] {issue['category']}: {issue['message']}")
            
        print(f"\n⚠️  Warnings: {len(self.warnings)}")
        for warning in self.warnings:
            print(f"  {warning['category']}: {warning['message']}")
            
        print(f"\nℹ️  Info: {len(self.info)}")
        for info in self.info:
            print(f"  {info['category']}: {info['message']}")
            
        # Root cause analysis
        print("\n" + "="*60)
        print("ROOT CAUSE ANALYSIS")
        print("="*60)
        
        critical_issues = [i for i in self.issues if i['severity'] == 'CRITICAL']
        high_issues = [i for i in self.issues if i['severity'] == 'HIGH']
        
        if critical_issues:
            print("\n🔴 CRITICAL ISSUES (blocking order submission):")
            for issue in critical_issues:
                print(f"  - {issue['category']}: {issue['message']}")
                
        if high_issues:
            print("\n🟠 HIGH PRIORITY ISSUES:")
            for issue in high_issues:
                print(f"  - {issue['category']}: {issue['message']}")
                
        # Recommendations
        print("\n" + "="*60)
        print("RECOMMENDATIONS")
        print("="*60)
        
        if any(i['category'] == 'SYNC_FETCH' and i['severity'] == 'CRITICAL' for i in self.issues):
            print("1. CRITICAL: Sync fetch is failing or timing out.")
            print("   - Increase _BANKROLL_SUMMARY_TIMEOUT_S to 20-30s")
            print("   - Check Kalshi API connectivity")
            print("   - Verify authentication credentials")
            
        if any(i['category'] == 'ASYNC_FETCH' and i['severity'] == 'CRITICAL' for i in self.issues):
            print("2. CRITICAL: Async fetch is failing.")
            print("   - Check service initialization")
            print("   - Verify Kalshi client is properly configured")
            print("   - Check network connectivity")
            
        if any(i['category'] == 'THREADING' and i['severity'] == 'HIGH' for i in self.issues):
            print("3. HIGH: Threading issues detected.")
            print("   - Review run_coroutine_threadsafe usage")
            print("   - Ensure event loop is properly managed")
            print("   - Consider using fully async path instead of sync wrapper")
            
        if any(i['category'] == 'CACHING' for i in self.warnings):
            print("4. Caching may not be working optimally.")
            print("   - Review cache TTL settings")
            print("   - Check cache invalidation logic")
            
        if self.results.get('sync_fetch_time', 0) > 5:
            print("5. Sync fetch is slow (>5s).")
            print("   - This is causing order submission delays")
            print("   - Consider making order submission fully async")
            print("   - Or increase timeout to accommodate slow fetches")


async def main():
    """Run all diagnostics."""
    print("="*60)
    print("BANKROLL SERVICE DIAGNOSTICS")
    print("="*60)
    print(f"Started at: {datetime.now().isoformat()}")
    
    diagnostics = BankrollDiagnostics()
    
    # Run all checks
    diagnostics.check_timeout_configuration()
    
    init_success = await diagnostics.check_service_initialization()
    
    if init_success:
        await diagnostics.check_async_fetch()
        await diagnostics.check_caching()
        await diagnostics.check_service_state()
        
    diagnostics.check_sync_fetch()
    await diagnostics.check_loop_threading()
    
    # Print summary
    diagnostics.print_summary()
    
    print(f"\nCompleted at: {datetime.now().isoformat()}")
    
    # Return exit code based on critical issues
    critical_count = len([i for i in diagnostics.issues if i['severity'] == 'CRITICAL'])
    return 1 if critical_count > 0 else 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
