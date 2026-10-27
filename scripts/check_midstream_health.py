#!/usr/bin/env python3
"""
Midstream health check - validates our services (UnifiedSpotService, MarketCatalog, WS Bridge).

Usage:
    python scripts/check_midstream_health.py [--verbose] [--base-url=http://localhost:8011]

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
from typing import Dict, List, Any
import json

BASE_URL = "http://localhost:8011"

async def check_unified_spot_service(session: aiohttp.ClientSession, verbose: bool = False) -> Dict:
    """Check UnifiedSpotService health and asset coverage."""
    result = {
        'service': 'UnifiedSpotService',
        'endpoint': '/api/v1/spot/health',
        'status': 'UNKNOWN',
        'details': {},
        'errors': []
    }
    
    try:
        url = f"{BASE_URL}/api/v1/spot/health"
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=5.0)) as response:
            if response.status == 200:
                data = await response.json()
                result['status'] = 'HEALTHY'
                result['details'] = data
                
                # Validate asset coverage
                expected_assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
                cached_assets = data.get('assets_cached', [])
                missing_assets = [asset for asset in expected_assets if asset not in cached_assets]
                
                if missing_assets:
                    result['status'] = 'DEGRADED'
                    result['errors'].append(f"Missing assets: {', '.join(missing_assets)}")
                
                # Validate freshness
                source_health = data.get('source', 'UNKNOWN')
                if source_health != 'HEALTHY':
                    result['status'] = 'DEGRADED'
                    result['errors'].append(f"Source health: {source_health}")
                
                if verbose:
                    print(f"✅ UnifiedSpotService: {data.get('assets_fetched', '?')}/{data.get('assets_cached', '?')} assets, source={source_health}")
                    
            else:
                result['status'] = 'CRITICAL'
                result['errors'].append(f"HTTP {response.status}")
                if verbose:
                    print(f"❌ UnifiedSpotService: HTTP {response.status}")
                    
    except asyncio.TimeoutError:
        result['status'] = 'CRITICAL'
        result['errors'].append('Timeout')
        if verbose:
            print(f"❌ UnifiedSpotService: Timeout")
    except Exception as e:
        result['status'] = 'CRITICAL'
        result['errors'].append(str(e))
        if verbose:
            print(f"❌ UnifiedSpotService: {e}")
    
    return result

async def check_market_catalog(session: aiohttp.ClientSession, verbose: bool = False) -> Dict:
    """Check MarketCatalog health and 15m crypto coverage."""
    result = {
        'service': 'MarketCatalog',
        'endpoint': '/api/v1/kalshi/markets',
        'status': 'UNKNOWN',
        'details': {},
        'errors': []
    }
    
    try:
        # Check catalog snapshot
        url = f"{BASE_URL}/api/v1/kalshi/markets"
        params = {'series_ticker': 'KXBTC15M,KXETH15M,KXSOL15M,KXXRP15M,KXDOGE15M'}
        async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=5.0)) as response:
            if response.status == 200:
                data = await response.json()
                markets = data.get('markets', [])
                
                # Validate we have exactly 5 active 15m tickers
                expected_series = ["KXBTC15M", "KXETH15M", "KXSOL15M", "KXXRP15M", "KXDOGE15M"]
                found_series = set()
                open_markets = 0
                
                for market in markets:
                    if market.get('status') == 'open':
                        open_markets += 1
                    series = market.get('series_ticker')
                    if series in expected_series:
                        found_series.add(series)
                
                result['details'] = {
                    'total_markets': len(markets),
                    'open_markets': open_markets,
                    'found_series': list(found_series),
                    'expected_series': expected_series
                }
                
                missing_series = set(expected_series) - found_series
                if missing_series:
                    result['status'] = 'DEGRADED'
                    result['errors'].append(f"Missing series: {', '.join(missing_series)}")
                elif open_markets < 5:
                    result['status'] = 'DEGRADED'
                    result['errors'].append(f"Only {open_markets}/5 markets open")
                else:
                    result['status'] = 'HEALTHY'
                
                if verbose:
                    print(f"✅ MarketCatalog: {len(markets)} markets, {open_markets} open, {len(found_series)}/5 series")
                    
            else:
                result['status'] = 'CRITICAL'
                result['errors'].append(f"HTTP {response.status}")
                if verbose:
                    print(f"❌ MarketCatalog: HTTP {response.status}")
                    
    except asyncio.TimeoutError:
        result['status'] = 'CRITICAL'
        result['errors'].append('Timeout')
        if verbose:
            print(f"❌ MarketCatalog: Timeout")
    except Exception as e:
        result['status'] = 'CRITICAL'
        result['errors'].append(str(e))
        if verbose:
            print(f"❌ MarketCatalog: {e}")
    
    return result

async def check_ws_bridge(session: aiohttp.ClientSession, verbose: bool = False) -> Dict:
    """Check WebSocket bridge health and subscription state."""
    result = {
        'service': 'WSBridge',
        'endpoint': '/api/v1/kalshi/ws/status',
        'status': 'UNKNOWN',
        'details': {},
        'errors': []
    }
    
    try:
        url = f"{BASE_URL}/api/v1/kalshi/ws/status"
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=5.0)) as response:
            if response.status == 200:
                data = await response.json()
                
                # Extract key metrics
                raw_tickers = data.get('raw_tickers', 0)
                subscribed_tickers = data.get('subscribed_tickers', 0)
                mode = data.get('mode', 'UNKNOWN')
                last_event_age = data.get('last_event_age_s', float('inf'))
                
                result['details'] = {
                    'raw_tickers': raw_tickers,
                    'subscribed_tickers': subscribed_tickers,
                    'mode': mode,
                    'last_event_age_s': last_event_age
                }
                
                # Validate invariants
                if raw_tickers == 0:
                    result['status'] = 'CRITICAL'
                    result['errors'].append('No raw tickers configured')
                elif subscribed_tickers == 0:
                    result['status'] = 'CRITICAL'
                    result['errors'].append('No active subscriptions')
                elif subscribed_tickers != raw_tickers:
                    result['status'] = 'DEGRADED'
                    result['errors'].append(f'Subscription mismatch: {subscribed_tickers}/{raw_tickers}')
                elif last_event_age > 60:  # No events for 1 minute
                    result['status'] = 'DEGRADED'
                    result['errors'].append(f'Stale connection: {last_event_age:.1f}s since last event')
                else:
                    result['status'] = 'HEALTHY'
                
                if verbose:
                    print(f"✅ WSBridge: {subscribed_tickers}/{raw_tickers} subscriptions, mode={mode}, last_event={last_event_age:.1f}s ago")
                    
            else:
                result['status'] = 'CRITICAL'
                result['errors'].append(f"HTTP {response.status}")
                if verbose:
                    print(f"❌ WSBridge: HTTP {response.status}")
                    
    except asyncio.TimeoutError:
        result['status'] = 'CRITICAL'
        result['errors'].append('Timeout')
        if verbose:
            print(f"❌ WSBridge: Timeout")
    except Exception as e:
        result['status'] = 'CRITICAL'
        result['errors'].append(str(e))
        if verbose:
            print(f"❌ WSBridge: {e}")
    
    return result

async def check_midstream_health(base_url: str = BASE_URL, verbose: bool = False) -> Dict:
    """Check all midstream services."""
    global BASE_URL
    BASE_URL = base_url
    
    results = {
        'timestamp': time.time(),
        'base_url': base_url,
        'services': {},
        'summary': {
            'total_services': 3,
            'healthy': 0,
            'degraded': 0,
            'critical': 0,
            'status': 'UNKNOWN'
        }
    }
    
    async with aiohttp.ClientSession() as session:
        # Check all services in parallel
        tasks = [
            check_unified_spot_service(session, verbose),
            check_market_catalog(session, verbose),
            check_ws_bridge(session, verbose)
        ]
        
        responses = await asyncio.gather(*tasks, return_exceptions=True)
        
        for response in responses:
            if isinstance(response, Exception):
                print(f"ERROR: Unexpected exception: {response}", file=sys.stderr)
                continue
            
            service_name = response['service']
            results['services'][service_name] = response
            
            status = response['status']
            results['summary'][status.lower()] += 1
        
        # Determine overall status
        summary = results['summary']
        if summary['critical'] > 0:
            results['summary']['status'] = 'CRITICAL'
        elif summary['degraded'] > 0:
            results['summary']['status'] = 'DEGRADED'
        else:
            results['summary']['status'] = 'HEALTHY'
    
    return results

def main():
    parser = argparse.ArgumentParser(description='Check midstream health')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    parser.add_argument('--base-url', '-u', default=BASE_URL, help='Base URL for API endpoints')
    parser.add_argument('--json', '-j', action='store_true', help='JSON output')
    args = parser.parse_args()
    
    if not args.verbose and not args.json:
        print("🔍 Checking midstream health...")
    
    results = asyncio.run(check_midstream_health(args.base_url, args.verbose))
    
    if args.json:
        print(json.dumps(results, indent=2))
        return
    
    # Print summary
    summary = results['summary']
    status_emoji = {
        'healthy': '✅',
        'degraded': '⚠️',
        'critical': '❌',
        'unknown': '❓'
    }
    
    print(f"\n{status_emoji.get(summary['status'], '❓')} Status: {summary['status'].upper()}")
    print(f"📊 Services: {summary['healthy']} healthy, {summary['degraded']} degraded, {summary['critical']} critical")
    
    # Print service details
    print("\n📋 Service Details:")
    for service_name, service_data in results['services'].items():
        status = service_data['status']
        emoji = status_emoji.get(status.lower(), '❓')
        print(f"   {emoji} {service_name}: {status}")
        
        if service_data['errors']:
            for error in service_data['errors']:
                print(f"      • {error}")
    
    # Exit code based on status
    if summary['status'] == 'HEALTHY':
        return 0
    elif summary['status'] == 'DEGRADED':
        return 1
    else:
        return 2

if __name__ == '__main__':
    sys.exit(main())
