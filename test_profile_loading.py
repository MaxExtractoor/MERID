#!/usr/bin/env python3
"""Test script to verify profile loading and bankroll_cap_pct wiring."""

import sys
sys.path.insert(0, 'c:\\Dev\\MERID')

from merid.risk.profiles.crypto_15m_profile import Crypto15mProfileAdapter

print("Loading profile...")
adapter = Crypto15mProfileAdapter()
profile = adapter._profile

print(f"Profile name: {profile.profile_name}")
print(f"venue_bankroll_cap_pct: {profile.venue_bankroll_cap_pct}")

print("\nGetting KalshiRiskConfig dict...")
config_dict = adapter.to_kalshi_risk_config()
print(f"bankroll_cap_pct in config: {config_dict.get('bankroll_cap_pct', 'NOT FOUND')}")

print("\nDone.")
