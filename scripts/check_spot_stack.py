#!/usr/bin/env python3
"""
Upstream spot stack health check - validates Coinbase API connectivity and latency.

Usage:
    python scripts/check_spot_stack.py [--verbose] [--timeout=5.0]

Returns:
    0 - All checks passed
    1 - Some checks failed
    2 - Critical failures
"""

import asyncio
import aiohttp
import time
import sys
import argparse
from typing import Dict, List, Tuple
import json

# Assets to check
ASSETS = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
BASE_URL = "https://api.coinbase.com/v2/prices"

async def fetch_asset(session: aiohttp.ClientSession, asset: str, timeout: float) -> Tuple[str, float, bool, str]:
    """Fetch single asset spot price with timing."""
    pair = f"{asset}-USD"
    url = f"{BASE_URL}/{pair}/spot"
    
    start_time = time.time()
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as response:
            data = await response.json()
            latency_ms = (time.time() - start_time) * 1000
            
            if response.status == 200 and 'data' in data and 'amount' in data['data']:
                price = float(data['data']['amount'])
                return asset, latency_ms, True, f"price=${price:.2f}"
            else:
                return asset, latency_ms, False, f"HTTP {response.status}"
                
    except asyncio.TimeoutError:
        latency_ms = timeout * 1000
        return asset, latency_ms, False, f"timeout after {timeout}s"
    except Exception as e:
        latency_ms = (time.time() - start_time) * 1000
        return asset, latency_ms, False, str(e)

async def check_spot_stack(timeout: float = 5.0, verbose: bool = False) -> Dict:
    """Check spot stack health for all assets."""
    results = {
        'timestamp': time.time(),
        'timeout_s': timeout,
        'assets': {},
        'summary': {
            'total_assets': len(ASSETS),
            'successful': 0,
            'failed': 0,
            'avg_latency_ms': 0.0,
            'max_latency_ms': 0.0,
            'min_latency_ms': float('inf'),
            'status': 'UNKNOWN'
        }
    }
    
    async with aiohttp.ClientSession() as session:
        tasks = [fetch_asset(session, asset, timeout) for asset in ASSETS]
        responses = await asyncio.gather(*tasks, return_exceptions=True)
        
        latencies = []
        for response in responses:
            if isinstance(response, Exception):
                print(f"ERROR: Unexpected exception: {response}", file=sys.stderr)
                continue
                
            asset, latency_ms, success, details = response
            results['assets'][asset] = {
                'success': success,
                'latency_ms': round(latency_ms, 2),
                'details': details
            }
            
            if success:
                results['summary']['successful'] += 1
                latencies.append(latency_ms)
                if verbose:
                    print(f"✅ {asset}: {latency_ms:.1f}ms - {details}")
            else:
                results['summary']['failed'] += 1
                if verbose:
                    print(f"❌ {asset}: {latency_ms:.1f}ms - {details}")
        
        # Calculate summary statistics
        if latencies:
            results['summary']['avg_latency_ms'] = round(sum(latencies) / len(latencies), 2)
            results['summary']['max_latency_ms'] = round(max(latencies), 2)
            results['summary']['min_latency_ms'] = round(min(latencies), 2)
        
        # Determine overall status
        success_rate = results['summary']['successful'] / results['summary']['total_assets']
        if success_rate == 1.0:
            results['summary']['status'] = 'HEALTHY'
        elif success_rate >= 0.8:
            results['summary']['status'] = 'DEGRADED'
        else:
            results['summary']['status'] = 'CRITICAL'
        
        return results

def analyze_patterns(results: Dict) -> List[str]:
    """Analyze patterns in the results for insights."""
    insights = []
    assets = results['assets']
    
    # Check for consistently slow assets
    avg_latency = results['summary']['avg_latency_ms']
    slow_assets = [asset for asset, data in assets.items() 
                  if data['success'] and data['latency_ms'] > avg_latency * 1.5]
    
    if slow_assets:
        insights.append(f"Slow assets detected: {', '.join(slow_assets)} (>{avg_latency * 1.5:.1f}ms avg)")
    
    # Check for specific failure patterns
    failed_assets = [asset for asset, data in assets.items() if not data['success']]
    if failed_assets:
        failure_reasons = set(assets[asset]['details'] for asset in failed_assets)
        insights.append(f"Failed assets: {', '.join(failed_assets)} - reasons: {', '.join(failure_reasons)}")
    
    # Check for timeout patterns
    timeout_assets = [asset for asset, data in assets.items() 
                    if not data['success'] and 'timeout' in data['details']]
    if timeout_assets:
        insights.append(f"Timeout pattern: {', '.join(timeout_assets)} consistently timing out")
    
    return insights

def main():
    parser = argparse.ArgumentParser(description='Check spot stack health')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    parser.add_argument('--timeout', '-t', type=float, default=5.0, help='Request timeout in seconds')
    parser.add_argument('--json', '-j', action='store_true', help='JSON output')
    args = parser.parse_args()
    
    if not args.verbose and not args.json:
        print("🔍 Checking spot stack health...")
    
    results = asyncio.run(check_spot_stack(args.timeout, args.verbose))
    
    if args.json:
        print(json.dumps(results, indent=2))
        return
    
    # Print summary
    summary = results['summary']
    status_emoji = {
        'HEALTHY': '✅',
        'DEGRADED': '⚠️',
        'CRITICAL': '❌',
        'UNKNOWN': '❓'
    }
    
    print(f"\n{status_emoji.get(summary['status'], '❓')} Status: {summary['status']}")
    print(f"📊 Success rate: {summary['successful']}/{summary['total_assets']} ({summary['successful']/summary['total_assets']*100:.1f}%)")
    print(f"⏱️  Latency: avg={summary['avg_latency_ms']:.1f}ms, min={summary['min_latency_ms']:.1f}ms, max={summary['max_latency_ms']:.1f}ms")
    
    # Print insights
    insights = analyze_patterns(results)
    if insights:
        print("\n🔍 Insights:")
        for insight in insights:
            print(f"   • {insight}")
    
    # Exit code based on status
    if summary['status'] == 'HEALTHY':
        return 0
    elif summary['status'] == 'DEGRADED':
        return 1
    else:
        return 2

if __name__ == '__main__':
    sys.exit(main())
