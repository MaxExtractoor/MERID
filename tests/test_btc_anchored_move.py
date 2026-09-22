"""Tests for BTC-Anchored Cross-Asset Move Model.

Covers:
  - BetaEstimate dataclass methods
  - BtcAnchoredMoveModel OLS regression
  - Prior fallback when insufficient data
  - Conditional bands by BTC move magnitude
  - Dollar and percent move predictions
  - Adjusted expected move blending
  - Suggested strike distance
  - Singleton access
  - Thread safety basics
  - Snapshot serialization
"""

from __future__ import annotations

import math
import random
import threading
import time
from decimal import Decimal
from typing import Dict, List

import pytest


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════

def _generate_correlated_returns(
    n: int,
    beta: float = 1.5,
    alpha: float = 0.0,
    noise_std: float = 0.001,
    btc_std: float = 0.005,
    seed: int = 42,
) -> tuple:
    """Generate synthetic BTC and alt returns with known beta."""
    rng = random.Random(seed)
    btc_rets = [rng.gauss(0, btc_std) for _ in range(n)]
    alt_rets = [alpha + beta * r + rng.gauss(0, noise_std) for r in btc_rets]
    return btc_rets, alt_rets


def _feed_model(model, btc_rets, alt_rets, asset="ETH", timeframe="15m"):
    """Feed paired returns into the model."""
    for b, a in zip(btc_rets, alt_rets):
        model.record_returns({"BTC": b, asset: a}, timeframe=timeframe)


# ═══════════════════════════════════════════════════════════════════════════
# Tests — BetaEstimate dataclass
# ═══════════════════════════════════════════════════════════════════════════



# ═══════════════════════════════════════════════════════════════════════════
# Tests — OLS Beta Regression
# ═══════════════════════════════════════════════════════════════════════════



# ═══════════════════════════════════════════════════════════════════════════
# Tests — Conditional Bands
# ═══════════════════════════════════════════════════════════════════════════



# ═══════════════════════════════════════════════════════════════════════════
# Tests — Convenience Methods
# ═══════════════════════════════════════════════════════════════════════════



# ═══════════════════════════════════════════════════════════════════════════
# Tests — Strike Distance Suggestion
# ═══════════════════════════════════════════════════════════════════════════



# ═══════════════════════════════════════════════════════════════════════════
# Tests — Snapshot & Serialization
# ═══════════════════════════════════════════════════════════════════════════



# ═══════════════════════════════════════════════════════════════════════════
# Tests — Singleton & Module Structure
# ═══════════════════════════════════════════════════════════════════════════



# ═══════════════════════════════════════════════════════════════════════════
# Tests — Thread Safety
# ═══════════════════════════════════════════════════════════════════════════



# ═══════════════════════════════════════════════════════════════════════════
# Tests — Record Prices (convenience)
# ═══════════════════════════════════════════════════════════════════════════




class TestThreadSafety:
    def test_concurrent_writes_and_reads(self):
        from merid.signals.btc_anchored_move import BtcAnchoredMoveModel

        model = BtcAnchoredMoveModel(window=500, min_obs=5)
        errors: List[str] = []

        def writer(asset, seed):
            rng = random.Random(seed)
            try:
                for _ in range(100):
                    model.record_returns(
                        {"BTC": rng.gauss(0, 0.005), asset: rng.gauss(0, 0.008)},
                        "15m",
                    )
            except Exception as e:
                errors.append(f"Writer {asset}: {e}")

        def reader():
            try:
                for _ in range(50):
                    model.get_beta("ETH", "15m")
                    model.get_beta("SOL", "15m")
                    model.snapshot("DOGE", "15m")
            except Exception as e:
                errors.append(f"Reader: {e}")

        threads = [
            threading.Thread(target=writer, args=("ETH", 1)),
            threading.Thread(target=writer, args=("SOL", 2)),
            threading.Thread(target=writer, args=("DOGE", 3)),
            threading.Thread(target=reader),
            threading.Thread(target=reader),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert errors == [], f"Thread errors: {errors}"


class TestThreadSafety:
    def test_concurrent_writes_and_reads(self):
        from merid.signals.btc_anchored_move import BtcAnchoredMoveModel

        model = BtcAnchoredMoveModel(window=500, min_obs=5)
        errors: List[str] = []

        def writer(asset, seed):
            rng = random.Random(seed)
            try:
                for _ in range(100):
                    model.record_returns(
                        {"BTC": rng.gauss(0, 0.005), asset: rng.gauss(0, 0.008)},
                        "15m",
                    )
            except Exception as e:
                errors.append(f"Writer {asset}: {e}")

        def reader():
            try:
                for _ in range(50):
                    model.get_beta("ETH", "15m")
                    model.get_beta("SOL", "15m")
                    model.snapshot("DOGE", "15m")
            except Exception as e:
                errors.append(f"Reader: {e}")

        threads = [
            threading.Thread(target=writer, args=("ETH", 1)),
            threading.Thread(target=writer, args=("SOL", 2)),
            threading.Thread(target=writer, args=("DOGE", 3)),
            threading.Thread(target=reader),
            threading.Thread(target=reader),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert errors == [], f"Thread errors: {errors}"