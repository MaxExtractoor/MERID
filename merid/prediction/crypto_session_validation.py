"""Session validation hints for Kalshi crypto PM + CT (``modern`` profile).

Run after a 15–30m session::

    py -3 -c "from merid.prediction.crypto_session_validation import print_validation_hints; print_validation_hints()"
"""

from __future__ import annotations

import json
from typing import Any, Dict

from merid.prediction.crypto_edge_production import enumerate_crypto_threshold_matrix


def threshold_matrix_snapshot() -> Dict[str, Any]:
    return enumerate_crypto_threshold_matrix()


def print_validation_hints() -> None:
    print("=== MERID crypto session checks (modern profile) ===")
    print("Env: MERID_CRYPTO_EDGE_PRODUCTION_PROFILE=modern")
    print("\n1) Threshold matrix (legacy vs modern, all 5 assets mirror these rows):")
    print(json.dumps(threshold_matrix_snapshot(), indent=2))
    print("\n2) Grep PM logs for actionable signals (one per asset/timeframe over 30m):")
    print(r'   findstr /i "[PM_SIGNAL] action=enter" your.log')
    print(r'   findstr /i "action=buy_yes action=buy_no" your.log')
    print("\n3) Confirm no persistent self-blocks:")
    print(r'   findstr /i "sentiment_below_contrarian_floor edge_below_threshold" your.log')
    print("\n4) MM + risk spread (modern allows 40¢ on KX*):")
    print(r'   findstr /i "Spread.*exceeds max" your.log')
    print("\n5) Orders:")
    print(r'   findstr /i "[KALSHI_ORDER_INTENT] EXECUTION_DECISION" your.log')
    print("\n6) Execution gate (LIMITED should not block crypto when modern + override on):")
    print(r'   findstr /i "execution_gate_blocked execution_gate_loop_lag" your.log')
    print("\n7) Vol bands (PM bridge) — set MERID_CRYPTO_VOL_BANDS_LOG=true for periodic JSON:")
    print(r'   findstr /i "CRYPTO_VOL_BANDS [PM_SIZE] vol_band=" your.log')


if __name__ == "__main__":
    print_validation_hints()
