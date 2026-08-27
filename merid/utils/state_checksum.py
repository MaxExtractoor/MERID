"""Canonical state checksum helpers for deterministic diff / replay verification.

Floats are rounded to a fixed number of decimal places before hashing so that
non-associative float arithmetic and platform differences do not change the
checksum.  Decimal values are serialized as strings to preserve exact precision.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal
from typing import Any, List


_FLOAT_PLACES = 8


def _canonical_value(value: Any) -> Any:
    """Recursively convert a Python object into a hash-friendly, JSON-safe form."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, float):
        # Round to a fixed number of places to avoid float noise.
        return round(value, _FLOAT_PLACES)
    if isinstance(value, dict):
        return {str(k): _canonical_value(v) for k, v in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_canonical_value(v) for v in value]
    if isinstance(value, set):
        return sorted([_canonical_value(v) for v in value])
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def canonical_json(value: Any, indent: bool = False) -> str:
    """Return a canonical JSON string suitable for hashing."""
    canonical = _canonical_value(value)
    return json.dumps(
        canonical,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=False,  # keys already sorted by _canonical_value
        separators=(",", ":"),
        indent=2 if indent else None,
    )


def state_checksum(value: Any) -> str:
    """Return a stable SHA-256 checksum of a canonical JSON representation."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def checksum_list_diff(left: List[str], right: List[str]) -> List[int]:
    """Return the indices where two checksum lists diverge."""
    diffs = []
    n = min(len(left), len(right))
    for i in range(n):
        if left[i] != right[i]:
            diffs.append(i)
    if len(left) != len(right):
        diffs.extend(range(n, max(len(left), len(right))))
    return diffs
