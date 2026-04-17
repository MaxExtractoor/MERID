"""
MERID repository entrypoint for `python -m main` / root-relative imports.

The canonical FastAPI application and lifespan live in ``web.main`` (single
source of truth). This module re-exports ``app`` so ``main.app is web.main.app``.
"""

import uvicorn

from web.api import test_page
from web.main import app

# Dev/test helpers that were historically mounted from this entrypoint.
app.include_router(test_page.router, tags=["test"])

if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info",
    )
