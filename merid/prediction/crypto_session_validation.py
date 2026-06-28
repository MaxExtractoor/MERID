"""Session validation hints for Kalshi crypto PM + CT (``modern`` profile).

LEGACY REMOVAL: crypto_edge_production moved to archive/legacy/ during 15m stack cleanup
This utility is deprecated for the kalshi_crypto_15m_v2 profile - use profile config instead.

Run after a 15–30m session::

    py -3 -c "from merid.prediction.crypto_session_validation import print_validation_hints; print_validation_hints()"
"""

from __future__ import annotations

import json
from typing import Any, Dict


def threshold_matrix_snapshot() -> Dict[str, Any]:
    # LEGACY REMOVAL: crypto_edge_production moved to archive/legacy/
    # Profile config (kalshi_crypto_15m.yaml) is now the single source of truth
    return {"deprecated": "Use profile config instead"}


def print_validation_hints() -> None:
    print("=== MERID crypto session checks (kalshi_crypto_15m_v2 profile) ===")
    print("LEGACY: crypto_edge_production moved to archive/legacy/ during 15m stack cleanup")
    print("Profile config (kalshi_crypto_15m.yaml) is now the single source of truth")
    print("\n1) Profile config:")
    print("   Check config/profiles/kalshi_crypto_15m.yaml for risk limits, edge thresholds, and Kelly sizing")
    print("\n2) Grep PM logs for actionable signals (one per asset/timeframe over 30m):")
    print(r'   findstr /i "[PM_SIGNAL] action=enter" your.log')
    print(r'   findstr /i "action=buy_yes action=buy_no" your.log')
    print("\n3) Confirm no persistent self-blocks:")
    print(r'   findstr /i "sentiment_below_contrarian_floor edge_below_threshold" your.log')
    print("\n4) MM + risk spread (profile sets max_spread_cents = 10):")
    print(r'   findstr /i "Spread.*exceeds max" your.log')
    print("\n5) Orders:")
    print(r'   findstr /i "[KALSHI_ORDER_INTENT] EXECUTION_DECISION" your.log')
    print("\n6) Execution gate (LIMITED should not block crypto when kalshi_crypto_15m_v2):")
    print(r'   findstr /i "execution_gate_blocked execution_gate_loop_lag" your.log')


if __name__ == "__main__":
    print_validation_hints()
