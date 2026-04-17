"""DEPRECATED - DO NOT USE

This module has been deprecated and replaced by merid.reconciliation.
The legacy trading.reconciliation module is no longer maintained.
All reconciliation functionality has been moved to merid.reconciliation.

Migration:
    OLD: from trading.reconciliation import X
    NEW: from merid.reconciliation import X
"""

import warnings

warnings.warn(
    "trading.reconciliation is deprecated. Use merid.reconciliation instead.",
    DeprecationWarning,
    stacklevel=2
)

raise ImportError(
    "trading.reconciliation has been deprecated. Use merid.reconciliation instead.\n"
    "See: merid/reconciliation/__init__.py for available exports."
)
