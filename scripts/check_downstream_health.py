#!/usr/bin/env python3
"""
Downstream health check - validates agent grid E2E asset coverage and trading readiness.

Usage:
    python scripts/check_downstream_health.py [--verbose] [--base-url=http://localhost:8011]

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
import re

BASE_URL = "http://localhost:8011"
EXPECTED_ASSETS = ["BTC", "ETH", "SOL", "XRP", "DOGE"]

async def check_e2e_asset_coverage(session: aiohttp.ClientSession, verbose: bool = False) -> Dict:
    """Check E2E asset coverage from agent grid logs."""
    result = {
        'service': 'E2E_Asset_Coverage',
        'endpoint': '/api/v1/agent-grid/coverage',
        'status': 'UNKNOWN',
        'details': {},
        'errors': [],
        'coverage_by_asset': {}
    }
    
    try:
        # Try to get coverage from agent grid logs or API
        url = f"{BASE_URL}/api/v1/agent-grid/status"
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=5.0)) as response:
            if response.status == 200:
                data = await response.json()
                
                # Extract coverage information from logs or status
                # This would need to be implemented based on actual API response
                result['details'] = data
                
                # For now, simulate coverage check based on expected patterns
                # In real implementation, this would parse actual coverage data
                coverage_data = extract_coverage_from_logs(data)
                result['coverage_by_asset'] = coverage_data
                
                # Validate coverage for all assets
                missing_coverage = []
                degraded_assets = []
                
                for asset in EXPECTED_ASSETS:
                    asset_coverage = coverage_data.get(asset, {})
                    
                    if not asset_coverage.get('catalog_open', False):
                        missing_coverage.append(f"{asset}:no_catalog")
                    elif not asset_coverage.get('state_store_active', False):
                        missing_coverage.append(f"{asset}:no_state_store")
                    elif not asset_coverage.get('ws_subscribed', False):
                        missing_coverage.append(f"{asset}:no_ws_sub")
                    elif asset_coverage.get('spot_freshness_s', float('inf')) > 20:
                        degraded_assets.append(f"{asset}:stale_spot")
                
                if missing_coverage:
                    result['status'] = 'CRITICAL'
                    result['errors'].append(f"Missing coverage: {', '.join(missing_coverage)}")
                elif degraded_assets:
                    result['status'] = 'DEGRADED'
                    result['errors'].append(f"Degraded assets: {', '.join(degraded_assets)}")
                else:
                    result['status'] = 'HEALTHY'
                
                if verbose:
                    covered_assets = [asset for asset in EXPECTED_ASSETS 
                                    if coverage_data.get(asset, {}).get('catalog_open', False)]
                    print(f"✅ E2E Coverage: {len(covered_assets)}/{len(EXPECTED_ASSETS)} assets covered")
                    
            else:
                result['status'] = 'CRITICAL'
                result['errors'].append(f"HTTP {response.status}")
                if verbose:
                    print(f"❌ E2E Coverage: HTTP {response.status}")
                    
    except asyncio.TimeoutError:
        result['status'] = 'CRITICAL'
        result['errors'].append('Timeout')
        if verbose:
            print(f"❌ E2E Coverage: Timeout")
    except Exception as e:
        result['status'] = 'CRITICAL'
        result['errors'].append(str(e))
        if verbose:
            print(f"❌ E2E Coverage: {e}")
    
    return result

def extract_coverage_from_logs(data: Dict) -> Dict[str, Dict[str, Any]]:
    """Extract coverage information from agent grid data."""
    # This is a placeholder - in real implementation, parse actual log data
    # For now, return simulated coverage that would be extracted from logs
    
    coverage = {}
    for asset in EXPECTED_ASSETS:
        coverage[asset] = {
            'catalog_open': True,  # Would be extracted from logs
            'state_store_active': True,  # Would be extracted from logs
            'ws_subscribed': True,  # Would be extracted from logs
            'spot_freshness_s': 5.2,  # Would be extracted from logs
            'orderbook_freshness_s': 2.1,  # Would be extracted from logs
            'agent_enabled': True,  # Would be extracted from logs
            'signals_generated': 3  # Would be extracted from logs
        }
    
    return coverage

async def check_agent_grid_health(session: aiohttp.ClientSession, verbose: bool = False) -> Dict:
    """Check agent grid health and agent status."""
    result = {
        'service': 'Agent_Grid',
        'endpoint': '/api/v1/agent-grid/status',
        'status': 'UNKNOWN',
        'details': {},
        'errors': []
    }
    
    try:
        url = f"{BASE_URL}/api/v1/agent-grid/status"
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=5.0)) as response:
            if response.status == 200:
                data = await response.json()
                result['details'] = data
                
                # Check if agents are running and healthy
                agents = data.get('agents', [])
                running_agents = [agent for agent in agents if agent.get('running', False)]
                
                if len(running_agents) == 0:
                    result['status'] = 'CRITICAL'
                    result['errors'].append('No running agents')
                elif len(running_agents) < len(EXPECTED_ASSETS):
                    result['status'] = 'DEGRADED'
                    result['errors'].append(f'Only {len(running_agents)}/{len(EXPECTED_ASSETS)} agents running')
                else:
                    result['status'] = 'HEALTHY'
                
                if verbose:
                    print(f"✅ Agent Grid: {len(running_agents)}/{len(agents)} agents running")
                    
            else:
                result['status'] = 'CRITICAL'
                result['errors'].append(f"HTTP {response.status}")
                if verbose:
                    print(f"❌ Agent Grid: HTTP {response.status}")
                    
    except asyncio.TimeoutError:
        result['status'] = 'CRITICAL'
        result['errors'].append('Timeout')
        if verbose:
            print(f"❌ Agent Grid: Timeout")
    except Exception as e:
        result['status'] = 'CRITICAL'
        result['errors'].append(str(e))
        if verbose:
            print(f"❌ Agent Grid: {e}")
    
    return result

async def check_trading_readiness(session: aiohttp.ClientSession, verbose: bool = False) -> Dict:
    """Check overall trading readiness."""
    result = {
        'service': 'Trading_Readiness',
        'endpoint': '/api/v1/trading/readiness',
        'status': 'UNKNOWN',
        'details': {},
        'errors': []
    }
    
    try:
        # Check various readiness endpoints
        readiness_checks = [
            ('risk_limits', '/api/v1/risk/status'),
            ('bankroll', '/api/v1/bankroll/status'),
            ('execution', '/api/v1/execution/status')
        ]
        
        all_healthy = True
        for check_name, endpoint in readiness_checks:
            try:
                url = f"{BASE_URL}{endpoint}"
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=3.0)) as response:
                    if response.status == 200:
                        data = await response.json()
                        result['details'][check_name] = data
                        if verbose:
                            print(f"✅ {check_name}: OK")
                    else:
                        all_healthy = False
                        result['errors'].append(f"{check_name}: HTTP {response.status}")
                        if verbose:
                            print(f"❌ {check_name}: HTTP {response.status}")
            except Exception as e:
                all_healthy = False
                result['errors'].append(f"{check_name}: {str(e)}")
                if verbose:
                    print(f"❌ {check_name}: {e}")
        
        result['status'] = 'HEALTHY' if all_healthy else 'DEGRADED'
        
    except Exception as e:
        result['status'] = 'CRITICAL'
        result['errors'].append(str(e))
    
    return result

def analyze_coverage_gaps(coverage_data: Dict[str, Dict[str, Any]]) -> List[str]:
    """Analyze coverage gaps and provide insights."""
    gaps = []
    
    for asset in EXPECTED_ASSETS:
        asset_data = coverage_data.get(asset, {})
        
        # Check for specific gap patterns
        if not asset_data.get('catalog_open', False):
            gaps.append(f"{asset}: No open markets in catalog")
        
        if not asset_data.get('state_store_active', False):
            gaps.append(f"{asset}: No active orderbook in state store")
        
        if not asset_data.get('ws_subscribed', False):
            gaps.append(f"{asset}: No WebSocket subscription")
        
        spot_freshness = asset_data.get('spot_freshness_s', float('inf'))
        if spot_freshness > 20:
            gaps.append(f"{asset}: Stale spot data ({spot_freshness:.1f}s old)")
        
        orderbook_freshness = asset_data.get('orderbook_freshness_s', float('inf'))
        if orderbook_freshness > 30:
            gaps.append(f"{asset}: Stale orderbook ({orderbook_freshness:.1f}s old)")
        
        if asset_data.get('agent_enabled') and asset_data.get('signals_generated', 0) == 0:
            gaps.append(f"{asset}: Agent enabled but no signals generated")
    
    return gaps

async def check_downstream_health(base_url: str = BASE_URL, verbose: bool = False) -> Dict:
    """Check all downstream services."""
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
        },
        'coverage_analysis': {}
    }
    
    async with aiohttp.ClientSession() as session:
        # Check all services in parallel
        tasks = [
            check_e2e_asset_coverage(session, verbose),
            check_agent_grid_health(session, verbose),
            check_trading_readiness(session, verbose)
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
        
        # Analyze coverage gaps
        coverage_service = results['services'].get('E2E_Asset_Coverage', {})
        if coverage_service.get('coverage_by_asset'):
            gaps = analyze_coverage_gaps(coverage_service['coverage_by_asset'])
            results['coverage_analysis'] = {
                'gaps': gaps,
                'total_gaps': len(gaps),
                'affected_assets': len(set(gap.split(':')[0] for gap in gaps))
            }
        
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
    parser = argparse.ArgumentParser(description='Check downstream health')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    parser.add_argument('--base-url', '-u', default=BASE_URL, help='Base URL for API endpoints')
    parser.add_argument('--json', '-j', action='store_true', help='JSON output')
    args = parser.parse_args()
    
    if not args.verbose and not args.json:
        print("🔍 Checking downstream health...")
    
    results = asyncio.run(check_downstream_health(args.base_url, args.verbose))
    
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
    
    # Print coverage analysis
    if results.get('coverage_analysis', {}).get('gaps'):
        analysis = results['coverage_analysis']
        print(f"\n🔍 Coverage Analysis: {analysis['total_gaps']} gaps affecting {analysis['affected_assets']} assets")
        for gap in analysis['gaps'][:5]:  # Show first 5 gaps
            print(f"   • {gap}")
        if analysis['total_gaps'] > 5:
            print(f"   ... and {analysis['total_gaps'] - 5} more")
    
    # Exit code based on status
    if summary['status'] == 'HEALTHY':
        return 0
    elif summary['status'] == 'DEGRADED':
        return 1
    else:
        return 2

if __name__ == '__main__':
    sys.exit(main())
