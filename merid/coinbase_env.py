"""Resolve Coinbase CDP / Advanced Trade credentials from the environment.

Coinbase Cloud API keys are often labeled *client API key* in the portal. We accept:

- API key (CB-ACCESS-KEY): ``MERID_COINBASE_API_KEY`` → ``COINBASE_CLIENT_API_KEY`` → ``COINBASE_API_KEY``
- Secret (signing): ``MERID_COINBASE_API_SECRET`` → ``COINBASE_CLIENT_API_SECRET`` → ``COINBASE_API_SECRET``
"""

from __future__ import annotations

import os
from typing import Optional


def coinbase_api_key() -> Optional[str]:
    v = (
        os.getenv("MERID_COINBASE_API_KEY")
        or os.getenv("COINBASE_CLIENT_API_KEY")
        or os.getenv("COINBASE_API_KEY")
    )
    return v if v else None


def coinbase_api_secret() -> Optional[str]:
    v = (
        os.getenv("MERID_COINBASE_API_SECRET")
        or os.getenv("COINBASE_CLIENT_API_SECRET")
        or os.getenv("COINBASE_API_SECRET")
    )
    return v if v else None
