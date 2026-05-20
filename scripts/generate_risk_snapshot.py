#!/usr/bin/env python3
"""
Pre-Deploy Risk Snapshot Generator

This script generates a risk snapshot artifact for each deployment that:
- Enumerates all active 15m-crypto agents and profiles
- Dumps drawdown parameters (halt/unwind/daily loss)
- Records whether they use canonical primitives (_prediction_risk.py, fees.py)
- Stores snapshots for diffing between builds to detect parameter drift

Usage:
    python scripts/generate_risk_snapshot.py [--output OUTPUT_FILE]

Output:
    JSON file with risk snapshot data
"""

import os
import sys
import json
import argparse
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional


def load_profile_data() -> Optional[Dict[str, Any]]:
    """Load profile data if 15m crypto profile is active."""
    try:
        from merid.risk.profiles.crypto_15m_profile import is_profile_active, get_active_profile
        
        if not is_profile_active():
            return None
        
        adapter = get_active_profile()
        if not adapter:
            return None
        
        profile_obj = adapter.profile
        
        # Extract relevant fields
        guardrails = getattr(profile_obj, 'guardrails', None)
        agent_defaults = getattr(profile_obj, 'agent_defaults', None)
        asset_configs = getattr(profile_obj, 'asset_configs', None)
        
        profile_data = {
            'profile_name': getattr(profile_obj, 'profile_name', 'unknown'),
            'profile_version': getattr(profile_obj, 'profile_version', 'unknown'),
            'capital_usd': getattr(profile_obj, 'capital_usd', 0.0),
            'venue_max_single_order_pct': getattr(profile_obj, 'venue_max_single_order_pct', 0.0),
            'enable_sentiment_execution': getattr(profile_obj, 'enable_sentiment_execution', False),
            'sentiment_mode': getattr(profile_obj, 'sentiment_mode', 'unknown'),
        }
        
        if guardrails:
            profile_data['guardrails'] = {
                'drawdown_halt_pct': getattr(guardrails, 'guardrails_drawdown_halt_pct', None),
                'drawdown_unwind_pct': getattr(guardrails, 'guardrails_drawdown_unwind_pct', None),
                'max_daily_loss_usd': getattr(guardrails, 'guardrails_max_daily_loss_usd', None),
                'max_spread_pct': getattr(guardrails, 'guardrails_max_spread_pct', None),
                'max_slippage_pct': getattr(guardrails, 'guardrails_max_slippage_pct', None),
                'min_depth_contracts': getattr(guardrails, 'guardrails_min_depth_contracts', None),
                'min_post_fee_edge': getattr(guardrails, 'guardrails_min_post_fee_edge', None),
            }
        
        if agent_defaults:
            profile_data['agent_defaults'] = {
                'max_notional_usd': getattr(agent_defaults, 'max_notional_usd', None),
                'max_orders_per_window': getattr(agent_defaults, 'max_orders_per_window', None),
                'max_yes_position': getattr(agent_defaults, 'max_yes_position', None),
                'max_no_position': getattr(agent_defaults, 'max_no_position', None),
                'minutes_before_expiry': getattr(agent_defaults, 'minutes_before_expiry', None),
                'cutoff_minutes_before_expiry': getattr(agent_defaults, 'cutoff_minutes_before_expiry', None),
            }
        
        if asset_configs:
            profile_data['asset_configs'] = {}
            for asset_name, config in asset_configs.items():
                profile_data['asset_configs'][asset_name] = {
                    'max_notional_usd': getattr(config, 'max_notional_usd', None),
                    'min_edge_early': getattr(config, 'min_edge_early', None),
                    'min_edge_mid': getattr(config, 'min_edge_mid', None),
                    'min_edge_late': getattr(config, 'min_edge_late', None),
                    'min_edge_terminal': getattr(config, 'min_edge_terminal', None),
                }
        
        return profile_data
        
    except ImportError:
        return None
    except Exception as e:
        print(f"Error loading profile data: {e}", file=sys.stderr)
        return None


def load_agent_grid() -> Optional[List[Dict[str, Any]]]:
    """Load agent grid configuration."""
    try:
        from merid.prediction.agent_grid_config import load_agent_grid_config
        
        agents = load_agent_grid_config()
        
        # Filter for 15m crypto agents
        allowed_15m_agents = {"BTC_15M", "ETH_15M", "SOL_15M", "XRP_15M", "DOGE_15M"}
        
        agent_data = []
        for agent in agents:
            if agent.name in allowed_15m_agents:
                agent_data.append({
                    'name': agent.name,
                    'enabled': agent.enabled,
                    'assets': agent.assets,
                    'timeframes': agent.timeframes,
                    'series_tickers': agent.series_tickers,
                    'risk_limits': {
                        'max_yes_position': agent.risk_limits.max_yes_position if agent.risk_limits else None,
                        'max_no_position': agent.risk_limits.max_no_position if agent.risk_limits else None,
                        'max_notional_usd': agent.risk_limits.max_notional_usd if agent.risk_limits else None,
                    } if agent.risk_limits else None,
                })
        
        return agent_data
        
    except ImportError:
        return None
    except Exception as e:
        print(f"Error loading agent grid: {e}", file=sys.stderr)
        return None


def check_canonical_primitive_usage() -> Dict[str, bool]:
    """Check if canonical primitives are being used."""
    checks = {
        'fees_py_exists': Path('merid/event_venues/kalshi/fees.py').exists(),
        'prediction_risk_py_exists': Path('merid/prediction/risk/_prediction_risk.py').exists(),
        'profile_loader_exists': Path('merid/risk/profiles/crypto_15m_profile.py').exists(),
        'profile_yaml_exists': Path('config/profiles/kalshi_crypto_15m.yaml').exists(),
    }
    
    # Check if _prediction_risk.py has profile gating
    try:
        with open('merid/prediction/risk/_prediction_risk.py', 'r') as f:
            content = f.read()
            checks['prediction_risk_has_profile_gating'] = 'is_profile_active' in content
    except Exception:
        checks['prediction_risk_has_profile_gating'] = False
    
    return checks


def generate_snapshot() -> Dict[str, Any]:
    """Generate complete risk snapshot."""
    snapshot = {
        'timestamp': datetime.utcnow().isoformat() + 'Z',
        'environment': os.getenv('KALSHI_ENV', 'unknown'),
        'profile': os.getenv('MERID_PROFILE', 'unknown'),
        'pm_profile': os.getenv('MERID_PM_PROFILE', 'unknown'),
        'profile_data': load_profile_data(),
        'agents': load_agent_grid(),
        'canonical_primitive_checks': check_canonical_primitive_usage(),
    }
    
    return snapshot


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Generate risk snapshot for deployment')
    parser.add_argument(
        '--output',
        '-o',
        type=str,
        default='risk_snapshot.json',
        help='Output file path (default: risk_snapshot.json)'
    )
    parser.add_argument(
        '--pretty',
        action='store_true',
        help='Pretty-print JSON output'
    )
    
    args = parser.parse_args()
    
    # Generate snapshot
    snapshot = generate_snapshot()
    
    # Write to file
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w') as f:
        if args.pretty:
            json.dump(snapshot, f, indent=2)
        else:
            json.dump(snapshot, f)
    
    print(f"Risk snapshot generated: {output_path}")
    print(f"Profile: {snapshot['profile']}")
    print(f"Environment: {snapshot['environment']}")
    
    if snapshot['profile_data']:
        guardrails = snapshot['profile_data'].get('guardrails', {})
        print(f"Drawdown halt: {guardrails.get('drawdown_halt_pct')}")
        print(f"Drawdown unwind: {guardrails.get('drawdown_unwind_pct')}")
        print(f"Max daily loss: ${guardrails.get('max_daily_loss_usd')}")
    
    if snapshot['agents']:
        enabled_agents = [a['name'] for a in snapshot['agents'] if a['enabled']]
        print(f"Enabled agents: {', '.join(enabled_agents)}")
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
