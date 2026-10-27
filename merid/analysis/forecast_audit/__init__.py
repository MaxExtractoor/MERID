"""Independent forecast-audit scorer for the Kalshi 15m crypto stack.

Read-only analysis package. Nothing here is imported by the live trading
loop; every loader is read-only and no trading state is mutated.

See ``report.py`` for the report assembly and ``__main__.py`` for the CLI.
"""
