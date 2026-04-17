"""Kalshi lane constants and asset coverage invariants.

Frozen sets and validation hooks align with :mod:`config.kalshi_crypto_config`.
"""

from typing import FrozenSet, Set

from config.kalshi_crypto_config import ACTIVE_CRYPTO_ASSETS

ALL_CRYPTO_ASSETS: FrozenSet[str] = frozenset(ACTIVE_CRYPTO_ASSETS)
VALID_TIMEFRAMES: FrozenSet[str] = frozenset(
    {"15m", "1h", "daily", "weekly", "monthly", "annual"}
)


def assert_exact_assets(coverage_set: Set[str], context: str) -> None:
    """Hard-fail if coverage_set != ALL_CRYPTO_ASSETS.

    Args:
        coverage_set: The set of assets to validate.
        context: Description of the configuration surface being checked
                 (e.g., "MIN_EDGE_GRID", "MAX_PRICE_GRID").

    Raises:
        ValueError: If coverage_set is missing assets or has extras.
    """
    if coverage_set != ALL_CRYPTO_ASSETS:
        missing = ALL_CRYPTO_ASSETS - coverage_set
        extra = coverage_set - ALL_CRYPTO_ASSETS
        raise ValueError(
            f"[ASSET-COVERAGE-FAIL] {context}: missing={sorted(missing)}, extra={sorted(extra)}"
        )
