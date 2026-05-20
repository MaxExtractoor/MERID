"""Configuration for multi-exchange composite spot price system.

Environment variables for configuring the composite spot price subsystem
and CF Benchmarks RTI alignment monitoring.
"""
from __future__ import annotations

import os

# Enable/disable composite spot price system
# Set to "true" to enable multi-exchange aggregation, "false" to use legacy single-exchange feed
MERID_SPOT_COMPOSITE_ENABLED = os.getenv("MERID_SPOT_COMPOSITE_ENABLED", "false").lower() == "true"

# Spot feed source for spot_basis_tracker
# Options: "composite", "coinbase", "kraken", "coingecko"
# "composite" uses multi-exchange VWAP/median from SpotComposite
# Others use legacy single-exchange feeds
MERID_SPOT_FEED_SOURCE = os.getenv("MERID_SPOT_FEED_SOURCE", "coinbase")

# CF Benchmarks RTI configuration
# API key for CF Benchmarks (if required for production access)
CFB_API_KEY = os.getenv("CFB_API_KEY", "")

# CF Benchmarks API base URL
CFB_BASE_URL = os.getenv("CFB_BASE_URL", "https://api.cfbenchmarks.com")

# Composite spot calculation settings
# Window for VWAP calculation (seconds)
MERID_SPOT_COMPOSITE_VWAP_WINDOW = float(os.getenv("MERID_SPOT_COMPOSITE_VWAP_WINDOW", "60.0"))

# Maximum age for a tick to be considered fresh (seconds)
MERID_SPOT_COMPOSITE_FRESH_TICK_AGE = float(os.getenv("MERID_SPOT_COMPOSITE_FRESH_TICK_AGE", "10.0"))

# Minimum number of exchanges required for healthy composite
MERID_SPOT_COMPOSITE_MIN_EXCHANGES_HEALTHY = int(os.getenv("MERID_SPOT_COMPOSITE_MIN_EXCHANGES_HEALTHY", "2"))
MERID_SPOT_COMPOSITE_MIN_EXCHANGES_DEGRADED = int(os.getenv("MERID_SPOT_COMPOSITE_MIN_EXCHANGES_DEGRADED", "1"))

# Volume weight exponent for VWAP (higher = more weight to high-volume exchanges)
MERID_SPOT_COMPOSITE_VOLUME_WEIGHT_EXPONENT = float(os.getenv("MERID_SPOT_COMPOSITE_VOLUME_WEIGHT_EXPONENT", "0.5"))

# Spot alignment monitoring settings
# Monitoring interval (seconds)
MERID_SPOT_ALIGNMENT_INTERVAL = float(os.getenv("MERID_SPOT_ALIGNMENT_INTERVAL", "30.0"))

# Rolling stats window (seconds)
MERID_SPOT_ALIGNMENT_WINDOW = float(os.getenv("MERID_SPOT_ALIGNMENT_WINDOW", "3600.0"))

# Alignment thresholds (basis points)
# ALIGNED -> MILD_DRIFT threshold
MERID_SPOT_ALIGNMENT_THRESHOLD1_BPS = float(os.getenv("MERID_SPOT_ALIGNMENT_THRESHOLD1_BPS", "5.0"))

# MILD_DRIFT -> SEVERE_DRIFT threshold
MERID_SPOT_ALIGNMENT_THRESHOLD2_BPS = float(os.getenv("MERID_SPOT_ALIGNMENT_THRESHOLD2_BPS", "20.0"))

# Enable/disable spot alignment monitor background task
MERID_SPOT_ALIGNMENT_MONITOR_ENABLED = os.getenv("MERID_SPOT_ALIGNMENT_MONITOR_ENABLED", "false").lower() == "true"
