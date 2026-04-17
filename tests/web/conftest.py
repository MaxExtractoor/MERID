"""
Web API test fixtures.

ZT4-02 / ZT6-01: All web/api routers now carry
    dependencies=[Depends(get_current_session)]

ZT7-01: Tests must bypass auth without modifying every test file.
FastAPI's Depends() captures function references, so monkeypatching the
module attribute won't work.  Instead we use an env-var test seam that
get_current_session checks at request-resolution time.

NEVER set MERID_SKIP_AUTH_FOR_TESTS=1 in production deployments.
"""
from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True, scope="session")
def _set_auth_bypass_env():
    """Set test-seam env var so get_current_session skips real validation."""
    os.environ["MERID_SKIP_AUTH_FOR_TESTS"] = "1"
    yield
    # Clean up after the session so other test packages aren't affected
    os.environ.pop("MERID_SKIP_AUTH_FOR_TESTS", None)
