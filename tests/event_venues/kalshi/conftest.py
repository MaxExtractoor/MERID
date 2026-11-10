"""Shared environment for the Kalshi venue test package.

CI runners have no venue credentials and ``tests/conftest.py`` blanks
``KALSHI_API_KEY_ID``/``KALSHI_PRIVATE_KEY_PATH``.  Several suites build
``KalshiConfig``/``get_kalshi_config()`` during setup; they mock request
signing and all network I/O, so placeholder credentials satisfy the
"is set" validation without enabling any real venue traffic.

These are set at module level (before any test module import triggers
``merid.settings`` — a pydantic-settings singleton instantiated on first
merid import) and only when the variable is currently empty, so real
credentials present in a developer ``.env``/environment still win.
"""

import os as _os

for _var, _val in {
    "KALSHI_API_KEY_ID": "test_key_id",
    "KALSHI_PRIVATE_KEY_PATH": "test_key.pem",
}.items():
    if not _os.environ.get(_var):
        _os.environ[_var] = _val
