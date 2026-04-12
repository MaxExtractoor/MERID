"""merid_core.kalshi — LEGACY / NON-CANONICAL package.

.. deprecated::
    This package is NOT on the production DISCOVER→EXECUTE path.
    The canonical Kalshi implementation is ``merid.event_venues.kalshi``.

    ``merid_core.kalshi`` is retained for:
    - ``scripts/kalshi_demo_runner.py`` (demo/dev only)
    - ``web/api/kalshi_api.py`` optional REST fallback (best-effort, not relied upon for trading)

    Do NOT add new production dependencies on this package.
    Migrate any active trading code to ``merid.event_venues.kalshi``.
"""
