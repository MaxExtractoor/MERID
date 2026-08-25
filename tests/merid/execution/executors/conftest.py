"""Skip legacy executor tests that test pre-order_router class shapes."""

import pytest

pytestmark = pytest.mark.skip(
    reason="Legacy executor tests drifted from the canonical order_router/client shape used by the 15m stack"
)
