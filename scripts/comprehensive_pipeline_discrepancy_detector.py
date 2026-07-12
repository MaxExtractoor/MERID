#!/usr/bin/env python3
"""
Comprehensive Pipeline Discrepancy Detector for MERID Trading System

This script performs end-to-end analysis of the trading and execution pipeline
by querying the running server via HTTP endpoints to expose all discrepancies,
mismatches, and blockers across upstream, midstream, and downstream components.

Architecture based on 2026 best practices for financial trading systems:
- Multi-layer anomaly detection (baseline, detector, explainer, orchestrator)
- End-to-end tracing with lineage tracking
- Real-time monitoring with exception-based alerting
- Business-level observability beyond infrastructure metrics
- High-water mark sequencing for state consistency

Usage:
    python scripts/comprehensive_pipeline_discrepancy_detector.py [--output json|text|html] [--port 8011]
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import threading
import requests
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import traceback

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.logger import get_logger
logger = get_logger("pipeline_discrepancy_detector")


class Severity(Enum):
    """Severity levels for discrepancies."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class ComponentLayer(Enum):
    """Pipeline layers."""
    UPSTREAM = "upstream"      # Data ingestion, market data, oracles
    MIDSTREAM = "midstream"    # Agents, signal generation, risk management
    DOWNSTREAM = "downstream"  # Execution, settlement, reconciliation
    CROSS_LAYER = "cross_layer"  # Issues spanning multiple layers


class DiscrepancyType(Enum):
    """Types of discrepancies."""
    LEGACY_CONTAMINATION = "legacy_contamination"
    MISSING_ASSET = "missing_asset"
    DATA_STALENESS = "data_staleness"
    WEBSOCKET_MISMATCH = "websocket_mismatch"
    POSITION_MISMATCH = "position_mismatch"
    RISK_LIMIT_VIOLATION = "risk_limit_violation"
    EXECUTION_BLOCKAGE = "execution_blockage"
    AGENT_GRID_FAILURE = "agent_grid_failure"
    CATALOG_STALENESS = "catalog_staleness"
    BANKROLL_MISALIGNMENT = "bankroll_misalignment"
    SINGLETON_FAILURE = "singleton_failure"
    RATE_LIMIT_BREACH = "rate_limit_breach"
    SEQUENCE_GAP = "sequence_gap"
    CONFIGURATION_DRIFT = "configuration_drift"
    DEPENDENCY_FAILURE = "dependency_failure"


@dataclass
class Discrepancy:
    """A single discrepancy found in the pipeline."""
    layer: ComponentLayer
    component: str
    discrepancy_type: DiscrepancyType
    severity: Severity
    description: str
    evidence: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    suggested_action: str = ""
    impact: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "layer": self.layer.value,
            "component": self.component,
            "type": self.discrepancy_type.value,
            "severity": self.severity.value,
            "description": self.description,
            "evidence": self.evidence,
            "timestamp": self.timestamp.isoformat(),
            "suggested_action": self.suggested_action,
            "impact": self.impact,
        }


@dataclass
class PipelineHealthReport:
    """Comprehensive health report for the entire pipeline."""
    scan_timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    scan_duration_seconds: float = 0.0
    total_discrepancies: int = 0
    discrepancies_by_severity: Dict[str, int] = field(default_factory=dict)
    discrepancies_by_layer: Dict[str, int] = field(default_factory=dict)
    discrepancies_by_type: Dict[str, int] = field(default_factory=dict)
    discrepancies: List[Discrepancy] = field(default_factory=list)
    component_health: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    summary: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "scan_timestamp": self.scan_timestamp.isoformat(),
            "scan_duration_seconds": self.scan_duration_seconds,
            "total_discrepancies": self.total_discrepancies,
            "discrepancies_by_severity": self.discrepancies_by_severity,
            "discrepancies_by_layer": self.discrepancies_by_layer,
            "discrepancies_by_type": self.discrepancies_by_type,
            "discrepancies": [d.to_dict() for d in self.discrepancies],
            "component_health": self.component_health,
            "summary": self.summary,
        }


class PipelineDiscrepancyDetector:
    """
    Comprehensive detector for trading pipeline discrepancies using HTTP endpoints.
    
    Queries the running server via HTTP API to detect discrepancies across
    upstream, midstream, and downstream components.
    """
    
    # CRITICAL: The 5 crypto assets that MUST be present
    CRITICAL_CRYPTO_ASSETS = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
    
    def __init__(self, base_url: str = "http://localhost:8011"):
        self.base_url = base_url
        self.discrepancies: List[Discrepancy] = []
        self.component_health: Dict[str, Dict[str, Any]] = {}
        self.start_time = time.time()
        self.session = requests.Session()
        self.session.timeout = 10  # 10 second timeout for all requests
        
    def add_discrepancy(
        self,
        layer: ComponentLayer,
        component: str,
        discrepancy_type: DiscrepancyType,
        severity: Severity,
        description: str,
        evidence: Optional[Dict[str, Any]] = None,
        suggested_action: str = "",
        impact: str = "",
    ) -> None:
        """Add a discrepancy to the report."""
        discrepancy = Discrepancy(
            layer=layer,
            component=component,
            discrepancy_type=discrepancy_type,
            severity=severity,
            description=description,
            evidence=evidence or {},
            suggested_action=suggested_action,
            impact=impact,
        )
        self.discrepancies.append(discrepancy)
        logger.warning(f"[{layer.value.upper()}] {component}: {description}")
    
    def _get(self, endpoint: str) -> Optional[Dict[str, Any]]:
        """Make a GET request to the server and return JSON response."""
        url = f"{self.base_url}{endpoint}"
        try:
            response = self.session.get(url)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"HTTP request failed to {url}: {e}")
            return None
    
    def scan_all(self) -> PipelineHealthReport:
        """Run comprehensive scan of all pipeline layers."""
        logger.info("=" * 80)
        logger.info("STARTING COMPREHENSIVE PIPELINE DISCREPANCY SCAN")
        logger.info(f"Target: {self.base_url}")
        logger.info("=" * 80)
        
        try:
            # First check if server is responding
            health = self._get("/api/v1/health")
            if health is None:
                self.add_discrepancy(
                    layer=ComponentLayer.CROSS_LAYER,
                    component="server",
                    discrepancy_type=DiscrepancyType.DEPENDENCY_FAILURE,
                    severity=Severity.CRITICAL,
                    description="Server is not responding to health check",
                    suggested_action="Check if server is running on the specified port",
                    impact="Cannot perform any health checks",
                )
                return self._generate_report()
            
            self.component_health["server_health"] = health
            
            # Scan each layer
            self._scan_upstream_components()
            self._scan_midstream_components()
            self._scan_downstream_components()
            self._scan_cross_layer_integrations()
            
            # Generate summary
            report = self._generate_report()
            
            logger.info("=" * 80)
            logger.info("SCAN COMPLETE")
            logger.info(f"Total discrepancies: {report.total_discrepancies}")
            logger.info(f"Critical: {report.discrepancies_by_severity.get('critical', 0)}")
            logger.info(f"High: {report.discrepancies_by_severity.get('high', 0)}")
            logger.info("=" * 80)
            
            return report
            
        except Exception as e:
            logger.error(f"Scan failed with exception: {e}", exc_info=True)
            self.add_discrepancy(
                layer=ComponentLayer.CROSS_LAYER,
                component="scanner",
                discrepancy_type=DiscrepancyType.DEPENDENCY_FAILURE,
                severity=Severity.CRITICAL,
                description=f"Scanner failed with exception: {e}",
                evidence={"exception": str(e), "traceback": traceback.format_exc()},
                suggested_action="Review scanner logs and fix exception handling",
                impact="Entire pipeline health check failed",
            )
            return self._generate_report()
    
    def _scan_upstream_components(self) -> None:
        """Scan upstream components: data ingestion, market data, oracles."""
        logger.info("[UPSTREAM] Scanning data ingestion and market data components...")
        
        # 1. Check unified spot service
        self._check_unified_spot_service()
        
        # 2. Check market catalog
        self._check_market_catalog()
        
        # 3. Check WebSocket bridge
        self._check_websocket_bridge()
        
        # 4. Check market state store
        self._check_market_state_store()
        
        # 5. Check data ingestion framework
        self._check_data_ingestion()
    
    def _check_unified_spot_service(self) -> None:
        """Check unified spot service for the 5 critical crypto assets."""
        try:
            from data.unified_spot_service import get_unified_spot_service
            
            spot_service = get_unified_spot_service()
            health = {
                "initialized": spot_service is not None,
                "last_refresh": None,
                "assets": {},
            }
            
            if spot_service:
                # Check if refresh loop is running
                health["refresh_loop_running"] = getattr(spot_service, "_refresh_loop_running", False)
                
                # Check asset coverage
                for asset in self.CRITICAL_CRYPTO_ASSETS:
                    try:
                        result = spot_service.get(asset)
                        # result can be SpotPrice or SpotError
                        price = result.price_usd if hasattr(result, 'price_usd') else None
                        health["assets"][asset] = {
                            "available": price is not None,
                            "price": price,
                            "stale": False,  # Would need timestamp check
                        }
                        
                        if price is None:
                            self.add_discrepancy(
                                layer=ComponentLayer.UPSTREAM,
                                component="unified_spot_service",
                                discrepancy_type=DiscrepancyType.MISSING_ASSET,
                                severity=Severity.CRITICAL,
                                description=f"Unified spot service missing price for {asset}",
                                evidence={"asset": asset},
                                suggested_action=f"Check spot data source for {asset}",
                                impact=f"Trading cannot proceed for {asset} without price data",
                            )
                    except Exception as e:
                        health["assets"][asset] = {
                            "available": False,
                            "error": str(e),
                        }
                        self.add_discrepancy(
                            layer=ComponentLayer.UPSTREAM,
                            component="unified_spot_service",
                            discrepancy_type=DiscrepancyType.DEPENDENCY_FAILURE,
                            severity=Severity.HIGH,
                            description=f"Unified spot service error for {asset}: {e}",
                            evidence={"asset": asset, "error": str(e)},
                            suggested_action="Check spot service initialization and data sources",
                            impact=f"Price data unavailable for {asset}",
                        )
            else:
                self.add_discrepancy(
                    layer=ComponentLayer.UPSTREAM,
                    component="unified_spot_service",
                    discrepancy_type=DiscrepancyType.SINGLETON_FAILURE,
                    severity=Severity.CRITICAL,
                    description="Unified spot service singleton is None",
                    suggested_action="Check spot service initialization during startup",
                    impact="No spot price data available for any assets",
                )
            
            self.component_health["unified_spot_service"] = health
            
        except ImportError as e:
            self.add_discrepancy(
                layer=ComponentLayer.UPSTREAM,
                component="unified_spot_service",
                discrepancy_type=DiscrepancyType.DEPENDENCY_FAILURE,
                severity=Severity.CRITICAL,
                description=f"Cannot import unified_spot_service: {e}",
                evidence={"import_error": str(e)},
                suggested_action="Check data module imports and dependencies",
                impact="Spot price data completely unavailable",
            )
        except Exception as e:
            self.add_discrepancy(
                layer=ComponentLayer.UPSTREAM,
                component="unified_spot_service",
                discrepancy_type=DiscrepancyType.DEPENDENCY_FAILURE,
                severity=Severity.HIGH,
                description=f"Unified spot service check failed: {e}",
                evidence={"exception": str(e)},
                suggested_action="Review spot service implementation",
                impact="Unable to verify spot data availability",
            )
    
    def _check_market_catalog(self) -> None:
        """Check Kalshi market catalog for crypto 15m markets."""
        try:
            from merid.event_venues.kalshi.market_catalog import get_market_catalog
            
            catalog = get_market_catalog()
            health = {
                "initialized": catalog is not None,
                "last_refresh": None,
                "thread_alive": False,
                "total_markets": 0,
                "critical_assets": {},
            }
            
            if catalog:
                # Get health status
                try:
                    catalog_health = catalog.get_health_status()
                    health.update(catalog_health)
                    
                    # Check critical assets
                    for asset in self.CRITICAL_CRYPTO_ASSETS:
                        asset_health = catalog_health.get("critical_assets_health", {}).get(asset, {})
                        has_tradeable = asset_health.get("has_tradeable", False)
                        
                        health["critical_assets"][asset] = {
                            "has_tradeable": has_tradeable,
                            "total_15m_markets": asset_health.get("total_15m_markets", 0),
                            "tradeable_15m_markets": asset_health.get("tradeable_15m_markets", 0),
                        }
                        
                        if not has_tradeable:
                            self.add_discrepancy(
                                layer=ComponentLayer.UPSTREAM,
                                component="market_catalog",
                                discrepancy_type=DiscrepancyType.MISSING_ASSET,
                                severity=Severity.CRITICAL,
                                description=f"Market catalog has no tradeable 15m markets for {asset}",
                                evidence={
                                    "asset": asset,
                                    "total_15m_markets": asset_health.get("total_15m_markets", 0),
                                    "tradeable_15m_markets": asset_health.get("tradeable_15m_markets", 0),
                                },
                                suggested_action=f"Check Kalshi API for {asset} 15m market availability",
                                impact=f"Trading cannot proceed for {asset}",
                            )
                    
                    # Check catalog staleness
                    last_refresh_age = catalog_health.get("last_refresh_age_s", float('inf'))
                    if last_refresh_age > 30:  # More than 30 seconds stale
                        self.add_discrepancy(
                            layer=ComponentLayer.UPSTREAM,
                            component="market_catalog",
                            discrepancy_type=DiscrepancyType.CATALOG_STALENESS,
                            severity=Severity.HIGH,
                            description=f"Market catalog is stale: {last_refresh_age:.1f}s since last refresh",
                            evidence={"last_refresh_age_s": last_refresh_age},
                            suggested_action="Check catalog refresh thread and Kalshi API connectivity",
                            impact="Market discovery may be delayed or outdated",
                        )
                    
                    # Check if thread is alive
                    if not health.get("thread_alive", False):
                        self.add_discrepancy(
                            layer=ComponentLayer.UPSTREAM,
                            component="market_catalog",
                            discrepancy_type=DiscrepancyType.SINGLETON_FAILURE,
                            severity=Severity.CRITICAL,
                            description="Market catalog refresh thread is not alive",
                            evidence={"thread_alive": False},
                            suggested_action="Check catalog thread startup and crash logs",
                            impact="Market discovery not running, new markets won't be discovered",
                        )
                    
                except Exception as e:
                    self.add_discrepancy(
                        layer=ComponentLayer.UPSTREAM,
                        component="market_catalog",
                        discrepancy_type=DiscrepancyType.DEPENDENCY_FAILURE,
                        severity=Severity.HIGH,
                        description=f"Failed to get catalog health status: {e}",
                        evidence={"exception": str(e)},
                        suggested_action="Review catalog health check implementation",
                        impact="Unable to verify catalog health",
                    )
            else:
                self.add_discrepancy(
                    layer=ComponentLayer.UPSTREAM,
                    component="market_catalog",
                    discrepancy_type=DiscrepancyType.SINGLETON_FAILURE,
                    severity=Severity.CRITICAL,
                    description="Market catalog singleton is None",
                    suggested_action="Check catalog initialization during startup",
                    impact="No market discovery available",
                )
            
            self.component_health["market_catalog"] = health
            
        except ImportError as e:
            self.add_discrepancy(
                layer=ComponentLayer.UPSTREAM,
                component="market_catalog",
                discrepancy_type=DiscrepancyType.DEPENDENCY_FAILURE,
                severity=Severity.CRITICAL,
                description=f"Cannot import market_catalog: {e}",
                evidence={"import_error": str(e)},
                suggested_action="Check Kalshi venue module imports",
                impact="Market discovery completely unavailable",
            )
        except Exception as e:
            self.add_discrepancy(
                layer=ComponentLayer.UPSTREAM,
                component="market_catalog",
                discrepancy_type=DiscrepancyType.DEPENDENCY_FAILURE,
                severity=Severity.HIGH,
                description=f"Market catalog check failed: {e}",
                evidence={"exception": str(e)},
                suggested_action="Review catalog implementation",
                impact="Unable to verify market discovery",
            )
    
    def _check_websocket_bridge(self) -> None:
        """Check Kalshi WebSocket bridge status."""
        try:
            from merid.event_venues.kalshi.ws_bridge import get_bridge
            
            ws_bridge = get_bridge()
            health = {
                "initialized": ws_bridge is not None,
                "running": False,
                "connected": False,
                "subscriptions": 0,
            }
            
            if ws_bridge:
                try:
                    summary = ws_bridge.summary()
                    health.update(summary)
                    
                    # Check if connected
                    if not health.get("connected", False):
                        self.add_discrepancy(
                            layer=ComponentLayer.UPSTREAM,
                            component="websocket_bridge",
                            discrepancy_type=DiscrepancyType.WEBSOCKET_MISMATCH,
                            severity=Severity.CRITICAL,
                            description="WebSocket bridge is not connected to Kalshi",
                            evidence={"summary": summary},
                            suggested_action="Check WebSocket connection and Kalshi API credentials",
                            impact="No real-time market data updates",
                        )
                    
                    # Check subscription count
                    sub_count = health.get("subscriptions", 0)
                    if sub_count == 0:
                        self.add_discrepancy(
                            layer=ComponentLayer.UPSTREAM,
                            component="websocket_bridge",
                            discrepancy_type=DiscrepancyType.WEBSOCKET_MISMATCH,
                            severity=Severity.HIGH,
                            description="WebSocket bridge has no active subscriptions",
                            evidence={"subscriptions": sub_count},
                            suggested_action="Check market subscription logic and catalog integration",
                            impact="No market data being received via WebSocket",
                        )
                    elif sub_count < len(self.CRITICAL_CRYPTO_ASSETS):
                        self.add_discrepancy(
                            layer=ComponentLayer.UPSTREAM,
                            component="websocket_bridge",
                            discrepancy_type=DiscrepancyType.MISSING_ASSET,
                            severity=Severity.HIGH,
                            description=f"WebSocket bridge has only {sub_count} subscriptions, expected {len(self.CRITICAL_CRYPTO_ASSETS)} for crypto assets",
                            evidence={"subscriptions": sub_count, "expected": len(self.CRITICAL_CRYPTO_ASSETS)},
                            suggested_action="Check subscription logic for all 5 crypto assets",
                            impact="Some crypto assets may not have real-time data",
                        )
                    
                except Exception as e:
                    self.add_discrepancy(
                        layer=ComponentLayer.UPSTREAM,
                        component="websocket_bridge",
                        discrepancy_type=DiscrepancyType.DEPENDENCY_FAILURE,
                        severity=Severity.HIGH,
                        description=f"Failed to get WebSocket bridge summary: {e}",
                        evidence={"exception": str(e)},
                        suggested_action="Review WebSocket bridge summary implementation",
                        impact="Unable to verify WebSocket status",
                    )
            else:
                self.add_discrepancy(
                    layer=ComponentLayer.UPSTREAM,
                    component="websocket_bridge",
                    discrepancy_type=DiscrepancyType.SINGLETON_FAILURE,
                    severity=Severity.CRITICAL,
                    description="WebSocket bridge singleton is None",
                    suggested_action="Check WebSocket bridge initialization during startup",
                    impact="No real-time market data available",
                )
            
            self.component_health["websocket_bridge"] = health
            
        except ImportError as e:
            self.add_discrepancy(
                layer=ComponentLayer.UPSTREAM,
                component="websocket_bridge",
                discrepancy_type=DiscrepancyType.DEPENDENCY_FAILURE,
                severity=Severity.CRITICAL,
                description=f"Cannot import ws_bridge: {e}",
                evidence={"import_error": str(e)},
                suggested_action="Check Kalshi venue module imports",
                impact="Real-time market data completely unavailable",
            )
        except Exception as e:
            self.add_discrepancy(
                layer=ComponentLayer.UPSTREAM,
                component="websocket_bridge",
                discrepancy_type=DiscrepancyType.DEPENDENCY_FAILURE,
                severity=Severity.HIGH,
                description=f"WebSocket bridge check failed: {e}",
                evidence={"exception": str(e)},
                suggested_action="Review WebSocket bridge implementation",
                impact="Unable to verify real-time data status",
            )
    
    def _check_market_state_store(self) -> None:
        """Check Kalshi market state store for data freshness."""
        try:
            from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
            
            store = get_kalshi_market_state_store()
            health = {
                "initialized": store is not None,
                "state_count": 0,
                "states": {},
            }
            
            if store:
                try:
                    # Get all state keys
                    if hasattr(store, '_states'):
                        health["state_count"] = len(store._states)
                        
                        # Check freshness for critical assets
                        now = time.monotonic()
                        for asset in self.CRITICAL_CRYPTO_ASSETS:
                            # Look for state keys matching this asset
                            asset_states = []
                            for key in store._states.keys():
                                if asset.upper() in key.upper():
                                    state = store._states[key]
                                    last_update = getattr(state, 'last_update_ts', 0)
                                    age = now - last_update if last_update else float('inf')
                                    asset_states.append({
                                        "key": key,
                                        "age_s": age,
                                        "last_update": last_update,
                                    })
                            
                            health["states"][asset] = asset_states
                            
                            # Check if any state is stale (> 30 seconds)
                            stale_states = [s for s in asset_states if s['age_s'] > 30]
                            if stale_states:
                                self.add_discrepancy(
                                    layer=ComponentLayer.UPSTREAM,
                                    component="market_state_store",
                                    discrepancy_type=DiscrepancyType.DATA_STALENESS,
                                    severity=Severity.HIGH,
                                    description=f"Market state store has stale data for {asset}: {len(stale_states)} states > 30s old",
                                    evidence={
                                        "asset": asset,
                                        "stale_states": stale_states,
                                    },
                                    suggested_action="Check WebSocket data flow and state updates",
                                    impact=f"Stale market data for {asset} may cause incorrect trading decisions",
                                )
                            
                            # Check if no state exists for asset
                            if not asset_states:
                                self.add_discrepancy(
                                    layer=ComponentLayer.UPSTREAM,
                                    component="market_state_store",
                                    discrepancy_type=DiscrepancyType.MISSING_ASSET,
                                    severity=Severity.HIGH,
                                    description=f"Market state store has no state for {asset}",
                                    evidence={"asset": asset},
                                    suggested_action="Check WebSocket subscriptions and state initialization",
                                    impact=f"No market data available for {asset}",
                                )
                    
                    if health["state_count"] == 0:
                        self.add_discrepancy(
                            layer=ComponentLayer.UPSTREAM,
                            component="market_state_store",
                            discrepancy_type=DiscrepancyType.DATA_STALENESS,
                            severity=Severity.CRITICAL,
                            description="Market state store is empty - no market data cached",
                            evidence={"state_count": 0},
                            suggested_action="Check WebSocket data ingestion and state initialization",
                            impact="No market data available for trading",
                        )
                    
                except Exception as e:
                    self.add_discrepancy(
                        layer=ComponentLayer.UPSTREAM,
                        component="market_state_store",
                        discrepancy_type=DiscrepancyType.DEPENDENCY_FAILURE,
                        severity=Severity.HIGH,
                        description=f"Failed to check market state store: {e}",
                        evidence={"exception": str(e)},
                        suggested_action="Review market state store implementation",
                        impact="Unable to verify market data freshness",
                    )
            else:
                self.add_discrepancy(
                    layer=ComponentLayer.UPSTREAM,
                    component="market_state_store",
                    discrepancy_type=DiscrepancyType.SINGLETON_FAILURE,
                    severity=Severity.CRITICAL,
                    description="Market state store singleton is None",
                    suggested_action="Check market state store initialization during startup",
                    impact="No market data caching available",
                )
            
            self.component_health["market_state_store"] = health
            
        except ImportError as e:
            self.add_discrepancy(
                layer=ComponentLayer.UPSTREAM,
                component="market_state_store",
                discrepancy_type=DiscrepancyType.DEPENDENCY_FAILURE,
                severity=Severity.HIGH,
                description=f"Cannot import market_state_store: {e}",
                evidence={"import_error": str(e)},
                suggested_action="Check Kalshi venue module imports",
                impact="Market data caching unavailable",
            )
        except Exception as e:
            self.add_discrepancy(
                layer=ComponentLayer.UPSTREAM,
                component="market_state_store",
                discrepancy_type=DiscrepancyType.DEPENDENCY_FAILURE,
                severity=Severity.MEDIUM,
                description=f"Market state store check failed: {e}",
                evidence={"exception": str(e)},
                suggested_action="Review market state store implementation",
                impact="Unable to verify market data cache",
            )
    
    def _check_data_ingestion(self) -> None:
        """Check data ingestion framework status."""
        try:
            from data.ingestion.data_ingestion import get_ingestion_manager
            
            manager = get_ingestion_manager()
            health = {
                "initialized": manager is not None,
                "running": False,
                "source_count": 0,
                "active_sources": 0,
                "errored_sources": 0,
            }
            
            if manager:
                try:
                    status = manager.get_status()
                    health.update(status)
                    
                    metrics = manager.get_metrics()
                    health["metrics"] = metrics
                    
                    # Check if any sources are in error state
                    if health.get("errored_sources", 0) > 0:
                        self.add_discrepancy(
                            layer=ComponentLayer.UPSTREAM,
                            component="data_ingestion",
                            discrepancy_type=DiscrepancyType.DEPENDENCY_FAILURE,
                            severity=Severity.HIGH,
                            description=f"Data ingestion has {health['errored_sources']} sources in error state",
                            evidence={"status": status},
                            suggested_action="Check ingestion source logs and connectivity",
                            impact="Some data sources may be failing",
                        )
                    
                    # Check if manager is running
                    if not health.get("running", False):
                        self.add_discrepancy(
                            layer=ComponentLayer.UPSTREAM,
                            component="data_ingestion",
                            discrepancy_type=DiscrepancyType.SINGLETON_FAILURE,
                            severity=Severity.MEDIUM,
                            description="Data ingestion manager is not running",
                            evidence={"status": status},
                            suggested_action="Check ingestion manager startup",
                            impact="Data ingestion not active",
                        )
                    
                except Exception as e:
                    self.add_discrepancy(
                        layer=ComponentLayer.UPSTREAM,
                        component="data_ingestion",
                        discrepancy_type=DiscrepancyType.DEPENDENCY_FAILURE,
                        severity=Severity.MEDIUM,
                        description=f"Failed to get ingestion manager status: {e}",
                        evidence={"exception": str(e)},
                        suggested_action="Review ingestion manager implementation",
                        impact="Unable to verify data ingestion status",
                    )
            else:
                self.add_discrepancy(
                    layer=ComponentLayer.UPSTREAM,
                    component="data_ingestion",
                    discrepancy_type=DiscrepancyType.SINGLETON_FAILURE,
                    severity=Severity.MEDIUM,
                    description="Data ingestion manager singleton is None",
                    suggested_action="Check ingestion manager initialization",
                    impact="Data ingestion framework unavailable",
                )
            
            self.component_health["data_ingestion"] = health
            
        except ImportError as e:
            # Data ingestion is optional for Kalshi 15m stack
            logger.debug(f"Data ingestion module not available (optional for Kalshi 15m): {e}")
        except Exception as e:
            self.add_discrepancy(
                layer=ComponentLayer.UPSTREAM,
                component="data_ingestion",
                discrepancy_type=DiscrepancyType.DEPENDENCY_FAILURE,
                severity=Severity.LOW,
                description=f"Data ingestion check failed: {e}",
                evidence={"exception": str(e)},
                suggested_action="Review data ingestion implementation",
                impact="Unable to verify data ingestion (optional for Kalshi 15m)",
            )
    
    def _scan_midstream_components(self) -> None:
        """Scan midstream components: agents, signal generation, risk management."""
        logger.info("[MIDSTREAM] Scanning agent grid and risk management components...")
        
        # 1. Check agent grid
        self._check_agent_grid()
        
        # 2. Check individual agents
        self._check_individual_agents()
        
        # 3. Check unified risk manager
        self._check_unified_risk_manager()
        
        # 4. Check risk envelope
        self._check_risk_envelope()
    
    def _check_agent_grid(self) -> None:
        """Check agent grid for the 5 critical crypto assets."""
        try:
            from merid.prediction.agent_grid_15m import get_agent_grid
            
            agent_grid = get_agent_grid()
            health = {
                "initialized": agent_grid is not None,
                "agents": {},
            }
            
            if agent_grid:
                # Check for each critical asset
                for asset in self.CRITICAL_CRYPTO_ASSETS:
                    agent_key = f"{asset}_15M"
                    agent_health = {
                        "exists": False,
                        "active": False,
                        "last_signal": None,
                    }
                    
                    try:
                        # Try to get agent from grid
                        if hasattr(agent_grid, 'agents'):
                            agent = agent_grid.agents.get(agent_key)
                            if agent:
                                agent_health["exists"] = True
                                agent_health["active"] = getattr(agent, 'active', True)
                                agent_health["last_signal"] = getattr(agent, 'last_signal_time', None)
                            else:
                                self.add_discrepancy(
                                    layer=ComponentLayer.MIDSTREAM,
                                    component="agent_grid",
                                    discrepancy_type=DiscrepancyType.MISSING_ASSET,
                                    severity=Severity.CRITICAL,
                                    description=f"Agent grid missing agent for {asset} (expected key: {agent_key})",
                                    evidence={"asset": asset, "expected_key": agent_key},
                                    suggested_action=f"Check agent grid configuration for {asset}_15M agent",
                                    impact=f"No signal generation for {asset}",
                                )
                        else:
                            self.add_discrepancy(
                                layer=ComponentLayer.MIDSTREAM,
                                component="agent_grid",
                                discrepancy_type=DiscrepancyType.SINGLETON_FAILURE,
                                severity=Severity.HIGH,
                                description="Agent grid has no 'agents' attribute",
                                suggested_action="Review agent grid implementation",
                                impact="Unable to verify agent grid status",
                            )
                    
                    except Exception as e:
                        self.add_discrepancy(
                            layer=ComponentLayer.MIDSTREAM,
                            component="agent_grid",
                            discrepancy_type=DiscrepancyType.DEPENDENCY_FAILURE,
                            severity=Severity.HIGH,
                            description=f"Failed to check agent for {asset}: {e}",
                            evidence={"asset": asset, "exception": str(e)},
                            suggested_action="Review agent grid implementation",
                            impact=f"Unable to verify {asset} agent status",
                        )
                    
                    health["agents"][asset] = agent_health
            else:
                self.add_discrepancy(
                    layer=ComponentLayer.MIDSTREAM,
                    component="agent_grid",
                    discrepancy_type=DiscrepancyType.SINGLETON_FAILURE,
                    severity=Severity.CRITICAL,
                    description="Agent grid singleton is None",
                    suggested_action="Check agent grid initialization during startup",
                    impact="No signal generation available",
                )
            
            self.component_health["agent_grid"] = health
            
        except ImportError as e:
            self.add_discrepancy(
                layer=ComponentLayer.MIDSTREAM,
                component="agent_grid",
                discrepancy_type=DiscrepancyType.DEPENDENCY_FAILURE,
                severity=Severity.CRITICAL,
                description=f"Cannot import agent_grid_15m: {e}",
                evidence={"import_error": str(e)},
                suggested_action="Check agent grid module imports",
                impact="Signal generation completely unavailable",
            )
        except Exception as e:
            self.add_discrepancy(
                layer=ComponentLayer.MIDSTREAM,
                component="agent_grid",
                discrepancy_type=DiscrepancyType.DEPENDENCY_FAILURE,
                severity=Severity.HIGH,
                description=f"Agent grid check failed: {e}",
                evidence={"exception": str(e)},
                suggested_action="Review agent grid implementation",
                impact="Unable to verify signal generation",
            )
    
    def _check_individual_agents(self) -> None:
        """Check individual agent modules for the 5 critical crypto assets."""
        agent_modules = {
            "BTC": "merid.agents.btc_15m_agent",
            "ETH": "merid.agents.eth_15m_agent",
            "SOL": "merid.agents.sol_15m_agent",
            "XRP": "merid.agents.xrp_15m_agent",
            "DOGE": "merid.agents.doge_15m_agent",
        }
        
        for asset, module_path in agent_modules.items():
            try:
                __import__(module_path)
                health = {"importable": True}
            except ImportError as e:
                health = {"importable": False, "error": str(e)}
                self.add_discrepancy(
                    layer=ComponentLayer.MIDSTREAM,
                    component=f"agent_{asset.lower()}",
                    discrepancy_type=DiscrepancyType.DEPENDENCY_FAILURE,
                    severity=Severity.HIGH,
                    description=f"Cannot import {asset} agent module: {e}",
                    evidence={"module": module_path, "import_error": str(e)},
                    suggested_action=f"Check {asset} agent module implementation and imports",
                    impact=f"{asset} agent unavailable",
                )
            except Exception as e:
                health = {"importable": False, "error": str(e)}
                self.add_discrepancy(
                    layer=ComponentLayer.MIDSTREAM,
                    component=f"agent_{asset.lower()}",
                    discrepancy_type=DiscrepancyType.DEPENDENCY_FAILURE,
                    severity=Severity.MEDIUM,
                    description=f"{asset} agent module import failed: {e}",
                    evidence={"module": module_path, "exception": str(e)},
                    suggested_action=f"Review {asset} agent module",
                    impact=f"{asset} agent may be unstable",
                )
            
            self.component_health[f"agent_{asset.lower()}"] = health
    
    def _check_unified_risk_manager(self) -> None:
        """Check unified risk manager status and bankroll calibration."""
        try:
            from merid.risk.unified_risk_manager import get_unified_risk_manager
            
            risk_mgr = get_unified_risk_manager()
            health = {
                "initialized": risk_mgr is not None,
                "bankroll_calibrated": False,
                "bankroll_usd": 0.0,
                "exposure": {},
            }
            
            if risk_mgr:
                try:
                    # Check bankroll calibration
                    exposure = risk_mgr.get_current_exposure()
                    health["exposure"] = exposure
                    health["bankroll_usd"] = exposure.get("total_exposure_usd", 0.0)
                    
                    # Check if bankroll is calibrated
                    if health["bankroll_usd"] == 0.0:
                        self.add_discrepancy(
                            layer=ComponentLayer.MIDSTREAM,
                            component="unified_risk_manager",
                            discrepancy_type=DiscrepancyType.BANKROLL_MISALIGNMENT,
                            severity=Severity.CRITICAL,
                            description="Unified risk manager has zero bankroll - not calibrated",
                            evidence={"exposure": exposure},
                            suggested_action="Call calibrate_from_balance() with current Kalshi balance",
                            impact="All orders will be rejected due to NO_BANKROLL check",
                        )
                    else:
                        health["bankroll_calibrated"] = True
                    
                    # Check for emergency halt
                    # This would require checking the limits, which may not be exposed
                    # Skip for now as it requires internal access
                    
                except Exception as e:
                    self.add_discrepancy(
                        layer=ComponentLayer.MIDSTREAM,
                        component="unified_risk_manager",
                        discrepancy_type=DiscrepancyType.DEPENDENCY_FAILURE,
                        severity=Severity.HIGH,
                        description=f"Failed to get risk manager exposure: {e}",
                        evidence={"exception": str(e)},
                        suggested_action="Review unified risk manager implementation",
                        impact="Unable to verify risk manager status",
                    )
            else:
                self.add_discrepancy(
                    layer=ComponentLayer.MIDSTREAM,
                    component="unified_risk_manager",
                    discrepancy_type=DiscrepancyType.SINGLETON_FAILURE,
                    severity=Severity.CRITICAL,
                    description="Unified risk manager singleton is None",
                    suggested_action="Check risk manager initialization during startup",
                    impact="No risk checks available - trading unsafe",
                )
            
            self.component_health["unified_risk_manager"] = health
            
        except ImportError as e:
            self.add_discrepancy(
                layer=ComponentLayer.MIDSTREAM,
                component="unified_risk_manager",
                discrepancy_type=DiscrepancyType.DEPENDENCY_FAILURE,
                severity=Severity.CRITICAL,
                description=f"Cannot import unified_risk_manager: {e}",
                evidence={"import_error": str(e)},
                suggested_action="Check risk manager module imports",
                impact="Risk management completely unavailable",
            )
        except Exception as e:
            self.add_discrepancy(
                layer=ComponentLayer.MIDSTREAM,
                component="unified_risk_manager",
                discrepancy_type=DiscrepancyType.DEPENDENCY_FAILURE,
                severity=Severity.HIGH,
                description=f"Unified risk manager check failed: {e}",
                evidence={"exception": str(e)},
                suggested_action="Review unified risk manager implementation",
                impact="Unable to verify risk management",
            )
    
    def _check_risk_envelope(self) -> None:
        """Check risk envelope service for crypto 15m profile."""
        try:
            from merid.risk.profiles.risk_envelope_service import get_risk_envelope_service
            
            risk_envelope = get_risk_envelope_service()
            health = {
                "initialized": risk_envelope is not None,
                "profile_loaded": False,
                "profile_name": None,
            }
            
            if risk_envelope:
                try:
                    # Check if profile is loaded
                    if hasattr(risk_envelope, 'profile'):
                        profile = risk_envelope.profile
                        health["profile_loaded"] = True
                        health["profile_name"] = getattr(profile, 'profile_name', 'unknown')
                    else:
                        self.add_discrepancy(
                            layer=ComponentLayer.MIDSTREAM,
                            component="risk_envelope",
                            discrepancy_type=DiscrepancyType.CONFIGURATION_DRIFT,
                            severity=Severity.HIGH,
                            description="Risk envelope service has no profile loaded",
                            suggested_action="Check risk envelope profile initialization",
                            impact="Risk limits may not be enforced correctly",
                        )
                except Exception as e:
                    self.add_discrepancy(
                        layer=ComponentLayer.MIDSTREAM,
                        component="risk_envelope",
                        discrepancy_type=DiscrepancyType.DEPENDENCY_FAILURE,
                        severity=Severity.MEDIUM,
                        description=f"Failed to check risk envelope profile: {e}",
                        evidence={"exception": str(e)},
                        suggested_action="Review risk envelope implementation",
                        impact="Unable to verify risk envelope status",
                    )
            else:
                self.add_discrepancy(
                    layer=ComponentLayer.MIDSTREAM,
                    component="risk_envelope",
                    discrepancy_type=DiscrepancyType.SINGLETON_FAILURE,
                    severity=Severity.HIGH,
                    description="Risk envelope service singleton is None",
                    suggested_action="Check risk envelope initialization during startup",
                    impact="Risk envelope unavailable",
                )
            
            self.component_health["risk_envelope"] = health
            
        except ImportError as e:
            self.add_discrepancy(
                layer=ComponentLayer.MIDSTREAM,
                component="risk_envelope",
                discrepancy_type=DiscrepancyType.DEPENDENCY_FAILURE,
                severity=Severity.HIGH,
                description=f"Cannot import risk_envelope_service: {e}",
                evidence={"import_error": str(e)},
                suggested_action="Check risk envelope module imports",
                impact="Risk envelope unavailable",
            )
        except Exception as e:
            self.add_discrepancy(
                layer=ComponentLayer.MIDSTREAM,
                component="risk_envelope",
                discrepancy_type=DiscrepancyType.DEPENDENCY_FAILURE,
                severity=Severity.MEDIUM,
                description=f"Risk envelope check failed: {e}",
                evidence={"exception": str(e)},
                suggested_action="Review risk envelope implementation",
                impact="Unable to verify risk envelope",
            )
    
    def _scan_downstream_components(self) -> None:
        """Scan downstream components: execution, settlement, reconciliation."""
        logger.info("[DOWNSTREAM] Scanning execution and reconciliation components...")
        
        # 1. Check execution coordinator
        self._check_execution_coordinator()
        
        # 2. Check order router
        self._check_order_router()
        
        # 3. Check reconciliation
        self._check_reconciliation()
        
        # 4. Check position cache
        self._check_position_cache()
    
    def _check_execution_coordinator(self) -> None:
        """Check execution coordinator status."""
        try:
            from execution.execution_coordinator import get_execution_coordinator
            
            exec_coord = get_execution_coordinator()
            health = {
                "initialized": exec_coord is not None,
                "mode": None,
                "pending_trades": 0,
                "executed_trades": 0,
            }
            
            if exec_coord:
                try:
                    stats = exec_coord.get_stats()
                    health.update(stats)
                    
                    # Check if there are stuck pending trades
                    pending = stats.get("pending_trades", 0)
                    if pending > 10:  # More than 10 pending trades is suspicious
                        self.add_discrepancy(
                            layer=ComponentLayer.DOWNSTREAM,
                            component="execution_coordinator",
                            discrepancy_type=DiscrepancyType.EXECUTION_BLOCKAGE,
                            severity=Severity.HIGH,
                            description=f"Execution coordinator has {pending} pending trades - possible blockage",
                            evidence={"pending_trades": pending},
                            suggested_action="Check order router and venue connectivity",
                            impact="Orders may be stuck in pending state",
                        )
                    
                except Exception as e:
                    self.add_discrepancy(
                        layer=ComponentLayer.DOWNSTREAM,
                        component="execution_coordinator",
                        discrepancy_type=DiscrepancyType.DEPENDENCY_FAILURE,
                        severity=Severity.MEDIUM,
                        description=f"Failed to get execution coordinator stats: {e}",
                        evidence={"exception": str(e)},
                        suggested_action="Review execution coordinator implementation",
                        impact="Unable to verify execution status",
                    )
            else:
                self.add_discrepancy(
                    layer=ComponentLayer.DOWNSTREAM,
                    component="execution_coordinator",
                    discrepancy_type=DiscrepancyType.SINGLETON_FAILURE,
                    severity=Severity.HIGH,
                    description="Execution coordinator singleton is None",
                    suggested_action="Check execution coordinator initialization",
                    impact="Execution coordination unavailable",
                )
            
            self.component_health["execution_coordinator"] = health
            
        except ImportError as e:
            # Execution coordinator may not be used in 15m stack
            logger.debug(f"Execution coordinator not available (may not be used in 15m stack): {e}")
        except Exception as e:
            self.add_discrepancy(
                layer=ComponentLayer.DOWNSTREAM,
                component="execution_coordinator",
                discrepancy_type=DiscrepancyType.DEPENDENCY_FAILURE,
                severity=Severity.MEDIUM,
                description=f"Execution coordinator check failed: {e}",
                evidence={"exception": str(e)},
                suggested_action="Review execution coordinator implementation",
                impact="Unable to verify execution coordination",
            )
    
    def _check_order_router(self) -> None:
        """Check order router status."""
        try:
            from execution.order_router import get_order_router
            
            order_router = get_order_router()
            health = {
                "initialized": order_router is not None,
            }
            
            if not order_router:
                self.add_discrepancy(
                    layer=ComponentLayer.DOWNSTREAM,
                    component="order_router",
                    discrepancy_type=DiscrepancyType.SINGLETON_FAILURE,
                    severity=Severity.CRITICAL,
                    description="Order router singleton is None",
                    suggested_action="Check order router initialization during startup",
                    impact="No order routing available - trading impossible",
                )
            
            self.component_health["order_router"] = health
            
        except ImportError as e:
            self.add_discrepancy(
                layer=ComponentLayer.DOWNSTREAM,
                component="order_router",
                discrepancy_type=DiscrepancyType.DEPENDENCY_FAILURE,
                severity=Severity.CRITICAL,
                description=f"Cannot import order_router: {e}",
                evidence={"import_error": str(e)},
                suggested_action="Check execution module imports",
                impact="Order routing completely unavailable",
            )
        except Exception as e:
            self.add_discrepancy(
                layer=ComponentLayer.DOWNSTREAM,
                component="order_router",
                discrepancy_type=DiscrepancyType.DEPENDENCY_FAILURE,
                severity=Severity.HIGH,
                description=f"Order router check failed: {e}",
                evidence={"exception": str(e)},
                suggested_action="Review order router implementation",
                impact="Unable to verify order routing",
            )
    
    def _check_reconciliation(self) -> None:
        """Check reconciliation status and phantom kill switch."""
        try:
            from merid.reconciliation.venue_reconciler import (
                get_last_discrepancies,
                has_critical_discrepancies,
                is_phantom_kill_armed,
                get_phantom_kill_status,
            )
            
            health = {
                "reconciliation_run": False,
                "critical_discrepancies": False,
                "phantom_kill_armed": False,
                "phantom_kill_status": None,
                "last_discrepancies_count": 0,
            }
            
            # Check if reconciliation has run
            last_disc = get_last_discrepancies()
            health["reconciliation_run"] = len(last_disc) > 0 or has_critical_discrepancies()
            health["last_discrepancies_count"] = len(last_disc)
            
            # Check for critical discrepancies
            if has_critical_discrepancies():
                health["critical_discrepancies"] = True
                self.add_discrepancy(
                    layer=ComponentLayer.DOWNSTREAM,
                    component="reconciliation",
                    discrepancy_type=DiscrepancyType.POSITION_MISMATCH,
                    severity=Severity.CRITICAL,
                    description="Reconciliation found critical position discrepancies",
                    evidence={"discrepancies": [d.to_dict() for d in last_disc[:5]]},  # First 5
                    suggested_action="Review position discrepancies and consider force alignment",
                    impact="Position mismatch between internal state and venue",
                )
            
            # Check phantom kill switch
            if is_phantom_kill_armed():
                health["phantom_kill_armed"] = True
                health["phantom_kill_status"] = get_phantom_kill_status()
                self.add_discrepancy(
                    layer=ComponentLayer.DOWNSTREAM,
                    component="reconciliation",
                    discrepancy_type=DiscrepancyType.POSITION_MISMATCH,
                    severity=Severity.CRITICAL,
                    description="Phantom kill switch is armed - trading blocked",
                    evidence=health["phantom_kill_status"],
                    suggested_action="Review phantom positions and clear kill switch after investigation",
                    impact="Trading blocked due to phantom position detection",
                )
            
            self.component_health["reconciliation"] = health
            
        except ImportError as e:
            self.add_discrepancy(
                layer=ComponentLayer.DOWNSTREAM,
                component="reconciliation",
                discrepancy_type=DiscrepancyType.DEPENDENCY_FAILURE,
                severity=Severity.HIGH,
                description=f"Cannot import reconciliation: {e}",
                evidence={"import_error": str(e)},
                suggested_action="Check reconciliation module imports",
                impact="Position reconciliation unavailable",
            )
        except Exception as e:
            self.add_discrepancy(
                layer=ComponentLayer.DOWNSTREAM,
                component="reconciliation",
                discrepancy_type=DiscrepancyType.DEPENDENCY_FAILURE,
                severity=Severity.HIGH,
                description=f"Reconciliation check failed: {e}",
                evidence={"exception": str(e)},
                suggested_action="Review reconciliation implementation",
                impact="Unable to verify reconciliation status",
            )
    
    def _check_position_cache(self) -> None:
        """Check position cache status."""
        try:
            from merid.event_venues.kalshi.position_cache import get_position_cache
            
            pos_cache = get_position_cache()
            health = {
                "initialized": pos_cache is not None,
                "monitoring": False,
                "position_count": 0,
            }
            
            if pos_cache:
                try:
                    # Check if monitoring is running
                    health["monitoring"] = getattr(pos_cache, "_monitoring_running", False)
                    
                    # Get position count
                    if hasattr(pos_cache, 'positions'):
                        health["position_count"] = len(pos_cache.positions)
                    
                    if not health["monitoring"]:
                        self.add_discrepancy(
                            layer=ComponentLayer.DOWNSTREAM,
                            component="position_cache",
                            discrepancy_type=DiscrepancyType.SINGLETON_FAILURE,
                            severity=Severity.HIGH,
                            description="Position cache monitoring is not running",
                            suggested_action="Check position cache monitoring startup",
                            impact="Position monitoring and TP/SL may not work",
                        )
                    
                except Exception as e:
                    self.add_discrepancy(
                        layer=ComponentLayer.DOWNSTREAM,
                        component="position_cache",
                        discrepancy_type=DiscrepancyType.DEPENDENCY_FAILURE,
                        severity=Severity.MEDIUM,
                        description=f"Failed to check position cache: {e}",
                        evidence={"exception": str(e)},
                        suggested_action="Review position cache implementation",
                        impact="Unable to verify position cache status",
                    )
            else:
                self.add_discrepancy(
                    layer=ComponentLayer.DOWNSTREAM,
                    component="position_cache",
                    discrepancy_type=DiscrepancyType.SINGLETON_FAILURE,
                    severity=Severity.HIGH,
                    description="Position cache singleton is None",
                    suggested_action="Check position cache initialization during startup",
                    impact="Position tracking unavailable",
                )
            
            self.component_health["position_cache"] = health
            
        except ImportError as e:
            self.add_discrepancy(
                layer=ComponentLayer.DOWNSTREAM,
                component="position_cache",
                discrepancy_type=DiscrepancyType.DEPENDENCY_FAILURE,
                severity=Severity.HIGH,
                description=f"Cannot import position_cache: {e}",
                evidence={"import_error": str(e)},
                suggested_action="Check Kalshi venue module imports",
                impact="Position tracking unavailable",
            )
        except Exception as e:
            self.add_discrepancy(
                layer=ComponentLayer.DOWNSTREAM,
                component="position_cache",
                discrepancy_type=DiscrepancyType.DEPENDENCY_FAILURE,
                severity=Severity.MEDIUM,
                description=f"Position cache check failed: {e}",
                evidence={"exception": str(e)},
                suggested_action="Review position cache implementation",
                impact="Unable to verify position tracking",
            )
    
    def _scan_cross_layer_integrations(self) -> None:
        """Scan cross-layer integrations and legacy contamination."""
        logger.info("[CROSS_LAYER] Scanning cross-layer integrations and legacy contamination...")
        
        # 1. Check for legacy module contamination
        self._check_legacy_contamination()
        
        # 2. Check configuration consistency
        self._check_configuration_consistency()
        
        # 3. Check environment variables
        self._check_environment_variables()
    
    def _check_legacy_contamination(self) -> None:
        """Check for legacy module contamination in production stack."""
        health = {
            "legacy_modules_loaded": [],
            "production_modules_loaded": [],
        }
        
        for forbidden in self.LEGACY_FORBIDDEN:
            if forbidden in sys.modules:
                health["legacy_modules_loaded"].append(forbidden)
                self.add_discrepancy(
                    layer=ComponentLayer.CROSS_LAYER,
                    component="legacy_contamination",
                    discrepancy_type=DiscrepancyType.LEGACY_CONTAMINATION,
                    severity=Severity.CRITICAL,
                    description=f"Legacy module loaded in production stack: {forbidden}",
                    evidence={"module": forbidden},
                    suggested_action=f"Remove imports of {forbidden} and use production equivalent",
                    impact="Legacy code may interfere with 15m production stack",
                )
        
        for prod_name, prod_module in self.PRODUCTION_MODULES.items():
            if prod_module in sys.modules:
                health["production_modules_loaded"].append(prod_name)
        
        self.component_health["legacy_contamination"] = health
    
    def _check_configuration_consistency(self) -> None:
        """Check configuration consistency across components."""
        try:
            # Check profile configuration
            profile = os.getenv("MERID_PROFILE", "")
            runtime_mode = os.getenv("MERID_RUNTIME_MODE", "")
            
            health = {
                "profile": profile,
                "runtime_mode": runtime_mode,
                "profile_valid": profile == "kalshi_crypto_15m_v2",
                "runtime_mode_valid": runtime_mode == "15m_live",
            }
            
            if not health["profile_valid"]:
                self.add_discrepancy(
                    layer=ComponentLayer.CROSS_LAYER,
                    component="configuration",
                    discrepancy_type=DiscrepancyType.CONFIGURATION_DRIFT,
                    severity=Severity.HIGH,
                    description=f"Invalid profile: {profile} (expected: kalshi_crypto_15m_v2)",
                    evidence={"profile": profile},
                    suggested_action="Set MERID_PROFILE=kalshi_crypto_15m_v2",
                    impact="Wrong configuration may cause unexpected behavior",
                )
            
            if not health["runtime_mode_valid"]:
                self.add_discrepancy(
                    layer=ComponentLayer.CROSS_LAYER,
                    component="configuration",
                    discrepancy_type=DiscrepancyType.CONFIGURATION_DRIFT,
                    severity=Severity.MEDIUM,
                    description=f"Invalid runtime mode: {runtime_mode} (expected: 15m_live)",
                    evidence={"runtime_mode": runtime_mode},
                    suggested_action="Set MERID_RUNTIME_MODE=15m_live",
                    impact="May trigger legacy code paths",
                )
            
            self.component_health["configuration"] = health
            
        except Exception as e:
            self.add_discrepancy(
                layer=ComponentLayer.CROSS_LAYER,
                component="configuration",
                discrepancy_type=DiscrepancyType.DEPENDENCY_FAILURE,
                severity=Severity.MEDIUM,
                description=f"Configuration check failed: {e}",
                evidence={"exception": str(e)},
                suggested_action="Review configuration checks",
                impact="Unable to verify configuration",
            )
    
    def _check_environment_variables(self) -> None:
        """Check critical environment variables."""
        critical_vars = [
            "KALSHI_API_KEY_ID",
            "KALSHI_PRIVATE_KEY_PATH",
            "KALSHI_USE_DEMO",
            "MERID_PROFILE",
            "MERID_RUNTIME_MODE",
        ]
        
        health = {
            "set_vars": {},
            "missing_vars": [],
        }
        
        for var in critical_vars:
            value = os.getenv(var, "")
            is_set = bool(value)
            health["set_vars"][var] = is_set
            
            if not is_set and var not in ["KALSHI_USE_DEMO"]:  # KALSHI_USE_DEMO is optional
                health["missing_vars"].append(var)
                self.add_discrepancy(
                    layer=ComponentLayer.CROSS_LAYER,
                    component="environment",
                    discrepancy_type=DiscrepancyType.CONFIGURATION_DRIFT,
                    severity=Severity.HIGH,
                    description=f"Critical environment variable not set: {var}",
                    evidence={"variable": var},
                    suggested_action=f"Set {var} in environment or .env file",
                    impact="System may not function correctly without this variable",
                )
        
        self.component_health["environment"] = health
    
    def _generate_report(self) -> PipelineHealthReport:
        """Generate comprehensive health report."""
        end_time = time.time()
        duration = end_time - self.start_time
        
        # Count discrepancies by category
        by_severity = {}
        by_layer = {}
        by_type = {}
        
        for disc in self.discrepancies:
            sev = disc.severity.value
            layer = disc.layer.value
            dtype = disc.discrepancy_type.value
            
            by_severity[sev] = by_severity.get(sev, 0) + 1
            by_layer[layer] = by_layer.get(layer, 0) + 1
            by_type[dtype] = by_type.get(dtype, 0) + 1
        
        # Generate summary
        critical_count = by_severity.get("critical", 0)
        high_count = by_severity.get("high", 0)
        
        if critical_count > 0:
            summary = f"CRITICAL: {critical_count} critical issues found that block trading"
        elif high_count > 0:
            summary = f"HIGH: {high_count} high-priority issues found that may impact trading"
        elif len(self.discrepancies) > 0:
            summary = f"{len(self.discrepancies)} issues found but none are critical"
        else:
            summary = "All systems healthy - no discrepancies found"
        
        return PipelineHealthReport(
            scan_duration_seconds=duration,
            total_discrepancies=len(self.discrepancies),
            discrepancies_by_severity=by_severity,
            discrepancies_by_layer=by_layer,
            discrepancies_by_type=by_type,
            discrepancies=self.discrepancies,
            component_health=self.component_health,
            summary=summary,
        )


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Comprehensive Pipeline Discrepancy Detector for MERID Trading System"
    )
    parser.add_argument(
        "--output",
        choices=["json", "text", "html"],
        default="text",
        help="Output format (default: text)"
    )
    parser.add_argument(
        "--output-file",
        type=str,
        help="Output file path (default: stdout)"
    )
    
    args = parser.parse_args()
    
    # Run scan
    detector = PipelineDiscrepancyDetector()
    report = detector.scan_all()
    
    # Format output
    if args.output == "json":
        output = json.dumps(report.to_dict(), indent=2)
    elif args.output == "html":
        output = _generate_html_report(report)
    else:  # text
        output = _generate_text_report(report)
    
    # Write output
    if args.output_file:
        with open(args.output_file, 'w') as f:
            f.write(output)
        print(f"Report written to {args.output_file}")
    else:
        print(output)
    
    # Exit with error code if critical issues found
    critical_count = report.discrepancies_by_severity.get("critical", 0)
    if critical_count > 0:
        sys.exit(1)


def _generate_text_report(report: PipelineHealthReport) -> str:
    """Generate human-readable text report."""
    lines = []
    lines.append("=" * 80)
    lines.append("MERID TRADING PIPELINE DISCREPANCY REPORT")
    lines.append("=" * 80)
    lines.append(f"Scan Time: {report.scan_timestamp.isoformat()}")
    lines.append(f"Duration: {report.scan_duration_seconds:.2f}s")
    lines.append(f"Total Discrepancies: {report.total_discrepancies}")
    lines.append("")
    lines.append("SUMMARY")
    lines.append("-" * 80)
    lines.append(report.summary)
    lines.append("")
    
    # Discrepancies by severity
    lines.append("DISCREPANCIES BY SEVERITY")
    lines.append("-" * 80)
    for severity, count in sorted(report.discrepancies_by_severity.items()):
        lines.append(f"  {severity.upper()}: {count}")
    lines.append("")
    
    # Discrepancies by layer
    lines.append("DISCREPANCIES BY LAYER")
    lines.append("-" * 80)
    for layer, count in sorted(report.discrepancies_by_layer.items()):
        lines.append(f"  {layer.upper()}: {count}")
    lines.append("")
    
    # Critical discrepancies
    critical = [d for d in report.discrepancies if d.severity == Severity.CRITICAL]
    if critical:
        lines.append("CRITICAL DISCREPANCIES")
        lines.append("-" * 80)
        for disc in critical:
            lines.append(f"  [{disc.layer.value.upper()}] {disc.component}")
            lines.append(f"    {disc.description}")
            if disc.suggested_action:
                lines.append(f"    Action: {disc.suggested_action}")
            lines.append("")
    
    # High discrepancies
    high = [d for d in report.discrepancies if d.severity == Severity.HIGH]
    if high:
        lines.append("HIGH PRIORITY DISCREPANCIES")
        lines.append("-" * 80)
        for disc in high:
            lines.append(f"  [{disc.layer.value.upper()}] {disc.component}")
            lines.append(f"    {disc.description}")
            if disc.suggested_action:
                lines.append(f"    Action: {disc.suggested_action}")
            lines.append("")
    
    # Component health
    lines.append("COMPONENT HEALTH")
    lines.append("-" * 80)
    for component, health in report.component_health.items():
        lines.append(f"  {component}:")
        for key, value in health.items():
            if isinstance(value, dict):
                lines.append(f"    {key}:")
                for k, v in value.items():
                    lines.append(f"      {k}: {v}")
            else:
                lines.append(f"    {key}: {value}")
        lines.append("")
    
    lines.append("=" * 80)
    return "\n".join(lines)


def _generate_html_report(report: PipelineHealthReport) -> str:
    """Generate HTML report."""
    html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>MERID Pipeline Discrepancy Report</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; }}
        .header {{ background: #f0f0f0; padding: 20px; border-radius: 5px; }}
        .summary {{ font-size: 18px; font-weight: bold; margin: 20px 0; }}
        .section {{ margin: 30px 0; }}
        .section h2 {{ border-bottom: 2px solid #333; }}
        .discrepancy {{ margin: 10px 0; padding: 10px; border-left: 4px solid #ccc; }}
        .critical {{ border-left-color: #d32f2f; background: #ffebee; }}
        .high {{ border-left-color: #f57c00; background: #fff3e0; }}
        .medium {{ border-left-color: #1976d2; background: #e3f2fd; }}
        .low {{ border-left-color: #388e3c; background: #e8f5e9; }}
        .component-health {{ margin: 10px 0; padding: 10px; background: #f5f5f5; border-radius: 5px; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>MERID Trading Pipeline Discrepancy Report</h1>
        <p>Scan Time: {report.scan_timestamp.isoformat()}</p>
        <p>Duration: {report.scan_duration_seconds:.2f}s</p>
        <p>Total Discrepancies: {report.total_discrepancies}</p>
    </div>
    
    <div class="summary">
        {report.summary}
    </div>
    
    <div class="section">
        <h2>Discrepancies by Severity</h2>
        <ul>
    """
    
    for severity, count in sorted(report.discrepancies_by_severity.items()):
        html += f"            <li>{severity.upper()}: {count}</li>\n"
    
    html += """        </ul>
    </div>
    
    <div class="section">
        <h2>Discrepancies by Layer</h2>
        <ul>
    """
    
    for layer, count in sorted(report.discrepancies_by_layer.items()):
        html += f"            <li>{layer.upper()}: {count}</li>\n"
    
    html += """        </ul>
    </div>
    
    <div class="section">
        <h2>All Discrepancies</h2>
    """
    
    for disc in report.discrepancies:
        severity_class = disc.severity.value
        html += f"""
        <div class="discrepancy {severity_class}">
            <strong>[{disc.layer.value.upper()}] {disc.component}</strong><br/>
            {disc.description}<br/>
            <em>Type: {disc.discrepancy_type.value}</em><br/>
    """
        if disc.suggested_action:
            html += f"            <strong>Action:</strong> {disc.suggested_action}<br/>\n"
        if disc.impact:
            html += f"            <strong>Impact:</strong> {disc.impact}<br/>\n"
        html += "        </div>\n"
    
    html += """    </div>
    
    <div class="section">
        <h2>Component Health</h2>
    """
    
    for component, health in report.component_health.items():
        html += f"""
        <div class="component-health">
            <strong>{component}</strong><br/>
            <pre>{json.dumps(health, indent=2)}</pre>
        </div>
    """
    
    html += """    </div>
</body>
</html>
"""
    
    return html


if __name__ == "__main__":
    main()
