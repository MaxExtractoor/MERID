"""
Startup Naming Validation for 15m Crypto Asset Agents and Lanes

This module enforces a strict naming convention across all BTC/ETH/SOL/XRP/DOGE
agents and lanes to prevent identity mismatches that could cause main loop hangs.

Naming Convention:
- Asset codes: BTC, ETH, SOL, XRP, DOGE
- Timeframe: 15M
- Lane IDs: <ASSET>_15M (e.g., BTC_15M, ETH_15M)
- Agent class names: <Asset>15mAgent (e.g., Btc15mAgent, Eth15mAgent)
"""

from typing import Dict, List, Any
from utils.logger import get_logger

logger = get_logger(__name__)


# Expected naming patterns
ASSET_CODES = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
TIMEFRAME = "15M"
EXPECTED_AGENT_CLASSES = {
    "BTC": "Btc15mAgent",
    "ETH": "Eth15mAgent",
    "SOL": "Sol15mAgent",
    "XRP": "Xrp15mAgent",
    "DOGE": "Doge15mAgent",
}
EXPECTED_LANE_IDS = {
    "BTC": "BTC_15M",
    "ETH": "ETH_15M",
    "SOL": "SOL_15M",
    "XRP": "XRP_15M",
    "DOGE": "DOGE_15M",
}


def log_agent_lane_registry_summary() -> None:
    """
    Log a summary table of all registered agents and lanes with their naming metadata.

    This helps identify naming mismatches at startup before they cause stalls.
    
    PROFILE-GUARD: Skip lane registry validation for kalshi_crypto_15m_v2 since this profile
    uses AgentGrid instead of the lane-based approach.
    """
    # PROFILE-GUARD: Skip lane registry validation for kalshi_crypto_15m_v2
    import os
    merid_profile = os.getenv("MERID_PROFILE", "").lower()
    if merid_profile == "kalshi_crypto_15m_v2":
        logger.info("[PROFILE-GUARD] Lane registry validation skipped for kalshi_crypto_15m_v2 (uses AgentGrid, not lanes)")
        return

    logger.info("=" * 80)
    logger.info("AGENT/LANE REGISTRY SUMMARY - 15m CRYPTO ASSETS")
    logger.info("=" * 80)

    # Log expected patterns
    logger.info("Expected naming patterns:")
    logger.info("  Asset codes: %s", ", ".join(ASSET_CODES))
    logger.info("  Timeframe: %s", TIMEFRAME)
    logger.info("  Lane IDs: %s", ", ".join(EXPECTED_LANE_IDS.values()))
    logger.info("  Agent classes: %s", ", ".join(EXPECTED_AGENT_CLASSES.values()))
    logger.info("-" * 80)

    # Log lane registry status
    try:
        from merid.lanes.registry import get_lane_registry
        registry = get_lane_registry()
        lanes = registry.get_all_lanes()

        logger.info("Lane Registry Status:")
        logger.info("  Total lanes: %d", len(lanes))
        logger.info("  Lane IDs: %s", ", ".join(registry.list_lane_ids()))

        for lane_id, lane in lanes.items():
            lane_class = lane.__class__.__name__
            symbol = getattr(lane, 'symbol', getattr(lane.cfg, 'symbol', 'unknown'))
            paper = getattr(lane.cfg, 'paper', False) if hasattr(lane, 'cfg') else False
            logger.info("  - Lane ID: %s | Class: %s | Symbol: %s | Paper: %s", lane_id, lane_class, symbol, paper)

        # Check for naming mismatches
        for asset in ASSET_CODES:
            expected_lane_id = EXPECTED_LANE_IDS[asset]
            if expected_lane_id not in lanes:
                logger.warning("[NAMING-MISMATCH] Expected lane %s not found in registry", expected_lane_id)

    except Exception as exc:
        logger.warning("Could not log lane registry status: %s", exc)

    logger.info("-" * 80)

    # Log agent registry status
    try:
        from merid.agents.agent_metadata import AGENT_CLASSIFICATION_MAP

        logger.info("Agent Registry Status (15m crypto):")
        for asset in ASSET_CODES:
            expected_agent = EXPECTED_AGENT_CLASSES[asset]
            if expected_agent in AGENT_CLASSIFICATION_MAP:
                classification = AGENT_CLASSIFICATION_MAP[expected_agent]
                logger.info("  - %s: %s", expected_agent, classification)
            else:
                logger.warning("[NAMING-MISMATCH] Expected agent %s not in classification map", expected_agent)

    except Exception as exc:
        logger.warning("Could not log agent registry status: %s", exc)

    logger.info("=" * 80)


def validate_naming_consistency() -> None:
    """
    WARN-only validation of naming consistency across agents and lanes.

    This does not block startup, but logs warnings for any mismatches that
    could cause confusion or bugs.

    PROFILE-GUARD: Skip lane validation for kalshi_crypto_15m_v2 since this profile
    uses AgentGrid instead of the lane-based approach.
    """
    # PROFILE-GUARD: Skip lane validation for kalshi_crypto_15m_v2
    import os
    merid_profile = os.getenv("MERID_PROFILE", "").lower()
    if merid_profile == "kalshi_crypto_15m_v2":
        logger.info("[PROFILE-GUARD] Lane naming validation skipped for kalshi_crypto_15m_v2 (uses AgentGrid, not lanes)")
        return

    logger.info("Running naming consistency validation...")

    # Validate lane IDs
    try:
        from merid.lanes.registry import get_lane_registry
        registry = get_lane_registry()
        lane_ids = registry.list_lane_ids()

        for asset in ASSET_CODES:
            expected_lane_id = EXPECTED_LANE_IDS[asset]
            if expected_lane_id not in lane_ids:
                logger.warning(
                    "[NAMING-WARN] Expected lane %s for asset %s not found in registry. Available lanes: %s",
                    expected_lane_id, asset, ", ".join(lane_ids)
                )
            else:
                logger.info("[NAMING-OK] Lane %s found for asset %s", expected_lane_id, asset)

    except Exception as exc:
        logger.warning("Could not validate lane naming: %s", exc)

    # Validate agent classes
    try:
        from merid.agents.agent_metadata import AGENT_CLASSIFICATION_MAP

        for asset in ASSET_CODES:
            expected_agent = EXPECTED_AGENT_CLASSES[asset]
            if expected_agent not in AGENT_CLASSIFICATION_MAP:
                logger.warning(
                    "[NAMING-WARN] Expected agent %s for asset %s not in classification map",
                    expected_agent, asset
                )
            else:
                classification = AGENT_CLASSIFICATION_MAP[expected_agent]
                if classification != "prod_15m_core":
                    logger.warning(
                        "[NAMING-WARN] Agent %s has unexpected classification: %s (expected prod_15m_core)",
                        expected_agent, classification
                    )
                else:
                    logger.info("[NAMING-OK] Agent %s has classification: %s", expected_agent, classification)

    except Exception as exc:
        logger.warning("Could not validate agent naming: %s", exc)

    # Validate no duplicate lane registrations
    try:
        from merid.lanes.registry import get_lane_registry
        registry = get_lane_registry()
        lanes = registry.get_all_lanes()

        for asset in ASSET_CODES:
            expected_lane_id = EXPECTED_LANE_IDS[asset]
            # Count how many lanes have this asset
            matching_lanes = 0
            for lane_id, lane in lanes.items():
                symbol = getattr(lane, 'symbol', getattr(lane.cfg, 'symbol', ''))
                if symbol == asset:
                    matching_lanes += 1

            if matching_lanes > 1:
                logger.warning(
                    "[NAMING-WARN] Asset %s has %d lanes registered (expected 1). This may cause confusion.",
                    asset, matching_lanes
                )
            elif matching_lanes == 0:
                logger.warning(
                    "[NAMING-WARN] Asset %s has 0 lanes registered (expected 1).",
                    asset
                )
            else:
                logger.info("[NAMING-OK] Asset %s has exactly 1 lane registered", asset)

    except Exception as exc:
        logger.warning("Could not validate duplicate lanes: %s", exc)

    logger.info("Naming consistency validation complete")


def check_for_legacy_lane_usage() -> None:
    """
    WARN-only check for legacy BTC15MLane usage in production code.

    This helps identify any remaining references to the legacy lane implementation.
    """
    logger.info("Checking for legacy lane usage...")

    # Check if BTC15MLane is imported anywhere in the startup path
    try:
        import sys
        btc15m_imported = False
        for module_name, module in sys.modules.items():
            if module is not None and hasattr(module, 'BTC15MLane'):
                btc15m_imported = True
                logger.warning(
                    "[LEGACY-LANE-DETECTED] BTC15MLane is imported in module: %s. "
                    "This is ANCIENT_EXPERIMENTAL and should be replaced with Crypto15MLane.",
                    module_name
                )

        if not btc15m_imported:
            logger.info("[LEGACY-LANE-OK] BTC15MLane not imported in current modules")

    except Exception as exc:
        logger.warning("Could not check for legacy lane usage: %s", exc)
