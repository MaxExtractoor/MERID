"""
Kalshi Wiring Dashboard API

Endpoints for surfacing mapping coverage, stats, and operational metrics
for CQI and operations dashboards.
"""

from __future__ import annotations

import time
from typing import Dict, List, Optional, Any
from fastapi import APIRouter, HTTPException, Query

from merid.event_venues.kalshi.market_context_resolver import get_market_context_resolver
from merid.event_venues.kalshi.market_mapping import get_market_mapping_registry
from merid.event_venues.kalshi.market_wiring.store import get_kalshi_market_store
from merid.event_venues.kalshi.market_wiring.safety import get_kalshi_safety_layer
from merid.event_venues.kalshi.market_wiring.models import RiskProfile
from merid.event_venues.kalshi.coverage_checker import get_coverage_checker
from merid.signals.store import get_signal_store
from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.dashboard_api")

router = APIRouter(prefix="/api/v1/kalshi/dashboard", tags=["kalshi_dashboard"])


@router.get("/segment-cqi")
async def get_segment_cqi():
    """Get CQI per segment for monitoring subsystem health"""
    try:
        safety_layer = get_kalshi_safety_layer()
        signal_store = get_signal_store()
        
        # Get CQI for each segment
        segment_cqi = {}
        segments = ["prediction_crypto_linked", "prediction_macro_election", "prediction_equity_linked", "prediction_other"]
        
        for segment in segments:
            try:
                cqi_history = signal_store.get_latest_cqi(domain="prediction", segment=segment)
                if cqi_history:
                    latest_cqi = cqi_history[0]
                    segment_cqi[segment] = {
                        "value": latest_cqi.get("quality_index", 0.5),
                        "band": latest_cqi.get("band", "neutral"),
                        "timestamp": latest_cqi.get("timestamp", 0),
                    }
                else:
                    segment_cqi[segment] = {
                        "value": 0.5,
                        "band": "neutral",
                        "timestamp": 0,
                        "status": "no_data"
                    }
            except Exception as e:
                logger.error(f"Error getting CQI for segment {segment}: {e}")
                segment_cqi[segment] = {
                    "value": 0.5,
                    "band": "neutral",
                    "timestamp": 0,
                    "status": "error",
                    "error": str(e)
                }
        
        return {
            "success": True,
            "data": {
                "segment_cqi": segment_cqi,
                "timestamp": time.time(),
            }
        }
        
    except Exception as e:
        logger.error(f"Failed to get segment CQI: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/safety-stats")
async def get_safety_stats():
    """Get safety layer statistics including blocked markets by reason"""
    try:
        safety_layer = get_kalshi_safety_layer()
        context_resolver = get_market_context_resolver()
        
        # Get all enabled mappings
        mapping_registry = get_market_mapping_registry()
        enabled_mappings = mapping_registry.get_enabled_mappings()
        
        # Collect safety statistics
        safety_stats = {
            "total_markets_checked": 0,
            "safe_to_trade": 0,
            "blocked_by_reason": {
                "missing_context": 0,
                "stale_context": 0,
                "cqi_suppression": 0,
                "risk_limit_breach": 0,
                "market_disabled": 0,
            },
            "blocked_markets": [],
        }
        
        for mapping in enabled_mappings:
            try:
                # Perform safety check
                safety_result = safety_layer.perform_safety_check(
                    market_ticker=mapping.market_ticker,
                    signal=None,
                    proposed_notional=100.0  # Standard notional for checking
                )
                
                safety_stats["total_markets_checked"] += 1
                
                if safety_result.safe_to_trade:
                    safety_stats["safe_to_trade"] += 1
                else:
                    # Categorize block reasons
                    for reason in safety_result.block_reasons:
                        if "context" in reason.lower() and "missing" in reason.lower():
                            safety_stats["blocked_by_reason"]["missing_context"] += 1
                        elif "context" in reason.lower() and "stale" in reason.lower():
                            safety_stats["blocked_by_reason"]["stale_context"] += 1
                        elif "cqi" in reason.lower():
                            safety_stats["blocked_by_reason"]["cqi_suppression"] += 1
                        elif "risk" in reason.lower() or "limit" in reason.lower():
                            safety_stats["blocked_by_reason"]["risk_limit_breach"] += 1
                        elif "disabled" in reason.lower():
                            safety_stats["blocked_by_reason"]["market_disabled"] += 1
                    
                    # Track blocked markets for details
                    safety_stats["blocked_markets"].append({
                        "market_ticker": mapping.market_ticker,
                        "underlying_symbol": mapping.underlying_symbol,
                        "risk_profile": mapping.risk_profile.value,
                        "block_reasons": safety_result.block_reasons,
                    })
                
            except Exception as e:
                logger.error(f"Error checking safety for {mapping.market_ticker}: {e}")
                safety_stats["blocked_by_reason"]["market_disabled"] += 1
        
        # Calculate percentages
        total = safety_stats["total_markets_checked"]
        if total > 0:
            safety_stats["safe_percentage"] = (safety_stats["safe_to_trade"] / total) * 100
            safety_stats["blocked_percentage"] = ((total - safety_stats["safe_to_trade"]) / total) * 100
        else:
            safety_stats["safe_percentage"] = 0.0
            safety_stats["blocked_percentage"] = 0.0
        
        return {
            "success": True,
            "data": safety_stats
        }
        
    except Exception as e:
        logger.error(f"Failed to get safety stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/coverage-stats")
async def get_coverage_stats():
    """Get comprehensive coverage statistics for dashboards"""
    try:
        # Get coverage checker and store
        coverage_checker = await get_coverage_checker()
        store = get_kalshi_market_store()
        mapping_registry = get_market_mapping_registry()
        
        # Get coverage summary
        coverage_summary = coverage_checker.get_coverage_summary()
        
        # Build validation stats by checking enabled mappings
        enabled_mappings = mapping_registry.get_enabled_mappings()
        validation_stats = {
            "total_enabled": len(enabled_mappings),
            "safe_to_trade": 0,
            "unsafe": 0,
            "issues_by_type": {
                "missing_context": 0,
                "stale_context": 0,
                "market_disabled": 0,
            }
        }
        
        # Check each enabled mapping for validation
        for mapping in enabled_mappings:
            try:
                # Get market record
                market = store.get_market(mapping.market_ticker)
                if not market or not market.enabled_for_merid:
                    validation_stats["issues_by_type"]["market_disabled"] += 1
                    validation_stats["unsafe"] += 1
                    continue
                
                # Check context availability (simplified validation)
                context_issues = []
                if mapping.requires_crypto_context:
                    # Check if crypto features exist
                    crypto_features = get_signal_store().get_latest_features(
                        symbol=mapping.underlying_symbol, domain="crypto"
                    )
                    if not crypto_features:
                        context_issues.append("missing_context")
                    elif (time.time() - crypto_features.get("timestamp", 0)) > mapping.max_crypto_staleness:
                        context_issues.append("stale_context")
                
                # Update stats based on issues
                if context_issues:
                    validation_stats["unsafe"] += 1
                    for issue in context_issues:
                        if issue in validation_stats["issues_by_type"]:
                            validation_stats["issues_by_type"][issue] += 1
                else:
                    validation_stats["safe_to_trade"] += 1
                    
            except Exception as e:
                logger.error(f"Error validating mapping {mapping.market_ticker}: {e}")
                validation_stats["unsafe"] += 1
        
        return {
            "success": True,
            "data": {
                "coverage_summary": coverage_summary,
                "validation_stats": validation_stats,
                "timestamp": time.time(),
            }
        }
        
    except Exception as e:
        logger.error(f"Failed to get coverage stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/mapping-summary")
async def get_mapping_summary():
    """Get mapping summary with risk profile breakdown"""
    try:
        store = get_kalshi_market_store()
        mapping_registry = get_market_mapping_registry()
        
        # Get all mappings
        all_mappings = mapping_registry.get_all_mappings()
        
        # Risk profile breakdown
        risk_profile_breakdown = {}
        for profile_enum in RiskProfile:
            markets = store.get_markets_by_risk_profile(profile_enum)
            mappings = mapping_registry.get_mappings_by_risk_profile(profile_enum)
            
            risk_profile_breakdown[profile_enum.value] = {
                "total_markets": len(markets),
                "mapped_markets": len(mappings),
                "enabled_mappings": len([m for m in mappings if m.enabled]),
                "coverage_percentage": (len(mappings) / len(markets) * 100) if markets else 0,
                "enablement_percentage": (len([m for m in mappings if m.enabled]) / len(markets) * 100) if markets else 0,
            }
        
        # Overall stats
        total_markets = len(store.get_open_markets())
        total_mappings = len(all_mappings)
        enabled_mappings = len([m for m in all_mappings if m.enabled])
        
        return {
            "success": True,
            "data": {
                "overall": {
                    "total_markets": total_markets,
                    "total_mappings": total_mappings,
                    "enabled_mappings": enabled_mappings,
                    "coverage_percentage": (total_mappings / total_markets * 100) if total_markets > 0 else 0,
                    "enablement_percentage": (enabled_mappings / total_markets * 100) if total_markets > 0 else 0,
                },
                "by_risk_profile": risk_profile_breakdown,
                "timestamp": time.time(),
            }
        }
        
    except Exception as e:
        logger.error(f"Failed to get mapping summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/context-status")
async def get_context_status():
    """Get context validation status for all markets"""
    try:
        context_resolver = get_market_context_resolver()
        
        # Get all enabled mappings
        mapping_registry = get_market_mapping_registry()
        enabled_mappings = mapping_registry.get_enabled_mappings()
        
        # Validate each market
        validation_results = []
        for mapping in enabled_mappings:
            validation = context_resolver.validate_context_for_signal(mapping.market_ticker)
            
            result = {
                "market_ticker": mapping.market_ticker,
                "underlying_symbol": mapping.underlying_symbol,
                "risk_profile": mapping.risk_profile.value,
                "valid": validation["valid"],
                "reason": validation["reason"],
                "safe_to_trade": validation["safe_to_trade"],
            }
            
            if validation["valid"]:
                result["effective_caps"] = validation["effective_caps"]
            else:
                result["context_issues"] = validation.get("context_issues", [])
            
            validation_results.append(result)
        
        # Summarize results
        total_markets = len(validation_results)
        safe_markets = len([r for r in validation_results if r["safe_to_trade"]])
        unsafe_markets = total_markets - safe_markets
        
        summary = {
            "total_markets": total_markets,
            "safe_to_trade": safe_markets,
            "unsafe": unsafe_markets,
            "safety_percentage": (safe_markets / total_markets * 100) if total_markets > 0 else 0.0,
        }
        
        return {
            "success": True,
            "data": {
                "summary": summary,
                "market_details": validation_results,
            }
        }
        
    except Exception as e:
        logger.error(f"Failed to get context status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/risk-profile-stats/{risk_profile}")
async def get_risk_profile_stats(risk_profile: str):
    """Get detailed stats for a specific risk profile"""
    try:
        from merid.event_venues.kalshi.market_wiring.models import RiskProfile
        
        # Validate risk profile
        try:
            profile_enum = RiskProfile(risk_profile)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid risk profile: {risk_profile}")
        
        store = get_kalshi_market_store()
        mapping_registry = get_market_mapping_registry()
        context_resolver = get_market_context_resolver()
        
        # Get markets and mappings for this risk profile
        markets = store.get_markets_by_risk_profile(profile_enum)
        mappings = mapping_registry.get_mappings_by_risk_profile(profile_enum)
        
        # Get context validation for enabled mappings
        enabled_mappings = [m for m in mappings if m.enabled]
        context_validations = []
        
        for mapping in enabled_mappings:
            validation = context_resolver.validate_context_for_signal(mapping.market_ticker)
            context_validations.append({
                "market_ticker": mapping.market_ticker,
                "valid": validation["valid"],
                "safe_to_trade": validation["safe_to_trade"],
                "reason": validation["reason"],
            })
        
        # Summarize
        safe_count = len([v for v in context_validations if v["safe_to_trade"]])
        
        profile_stats = {
            "risk_profile": risk_profile,
            "total_markets": len(markets),
            "mapped_markets": len(mappings),
            "enabled_mappings": len(enabled_mappings),
            "safe_to_trade": safe_count,
            "coverage_percentage": (len(mappings) / len(markets) * 100) if markets else 0.0,
            "enablement_percentage": (len(enabled_mappings) / len(markets) * 100) if markets else 0.0,
            "safety_percentage": (safe_count / len(enabled_mappings) * 100) if enabled_mappings else 0.0,
            "context_validations": context_validations,
        }
        
        return {
            "success": True,
            "data": profile_stats
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get risk profile stats for {risk_profile}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/operational-metrics")
async def get_operational_metrics():
    """Get operational metrics for monitoring"""
    try:
        store = get_kalshi_market_store()
        mapping_registry = get_market_mapping_registry()
        context_resolver = get_market_context_resolver()
        
        # Get sync timestamps
        sync_timestamps = store.get_sync_timestamps()
        current_time = sync_timestamps.get("current", 0)
        
        # Calculate sync ages
        universe_age = current_time - sync_timestamps.get("kalshi", 0)
        mapping_age = current_time - sync_timestamps.get("mapping", 0)
        coverage_age = current_time - sync_timestamps.get("coverage", 0)
        
        # Get coverage report
        coverage_checker = await get_coverage_checker()
        coverage_report = coverage_checker.get_latest_report()

        # Get context stats
        coverage_stats = context_resolver.get_coverage_stats()
        
        metrics = {
            "sync_status": {
                "universe_sync_age_minutes": universe_age / 60,
                "mapping_sync_age_minutes": mapping_age / 60,
                "coverage_check_age_minutes": coverage_age / 60,
                "last_universe_sync": sync_timestamps.get("kalshi", 0),
                "last_mapping_sync": sync_timestamps.get("mapping", 0),
                "last_coverage_check": sync_timestamps.get("coverage", 0),
            },
            "coverage_metrics": {
                "total_open_markets": coverage_report.total_open_markets if coverage_report else 0,
                "coverage_percentage": coverage_report.coverage_percentage if coverage_report else 0.0,
                "enablement_percentage": coverage_report.enablement_percentage if coverage_report else 0.0,
                "unmapped_markets": coverage_report.unmapped_markets if coverage_report else 0,
                "disabled_markets": coverage_report.disabled_markets if coverage_report else 0,
            },
            "context_metrics": {
                "total_enabled_mappings": coverage_stats.get("validation_stats", {}).get("total_enabled", 0),
                "safe_to_trade": coverage_stats.get("validation_stats", {}).get("safe_to_trade", 0),
                "unsafe": coverage_stats.get("validation_stats", {}).get("unsafe", 0),
                "safety_percentage": (
                    coverage_stats.get("validation_stats", {}).get("safe_to_trade", 0) / 
                    max(coverage_stats.get("validation_stats", {}).get("total_enabled", 1), 1) * 100
                ),
            },
            "mapping_metrics": coverage_stats.get("mapping_stats", {}),
        }
        
        # Determine overall health
        health_status = "healthy"
        issues = []
        
        if universe_age > 1800:  # 30 minutes
            health_status = "degraded"
            issues.append("Universe sync is stale")
        
        if coverage_report and coverage_report.coverage_percentage < 90.0:
            health_status = "degraded"
            issues.append("Low market coverage")
        
        if metrics["context_metrics"]["safety_percentage"] < 80.0:
            health_status = "degraded"
            issues.append("Low market safety percentage")
        
        metrics["overall_health"] = {
            "status": health_status,
            "issues": issues,
        }
        
        return {
            "success": True,
            "data": metrics,
            "timestamp": current_time,
        }
        
    except Exception as e:
        logger.error(f"Failed to get operational metrics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/alert-summary")
async def get_alert_summary():
    """Get summary of current alerts and issues"""
    try:
        store = get_kalshi_market_store()
        mapping_registry = get_market_mapping_registry()
        context_resolver = get_market_context_resolver()
        coverage_checker = await get_coverage_checker()

        alerts = []

        # Coverage alerts
        coverage_report = coverage_checker.get_latest_report()
        if coverage_report:
            if coverage_report.coverage_percentage < 95.0:
                alerts.append({
                    "type": "coverage",
                    "severity": "warning" if coverage_report.coverage_percentage >= 90.0 else "critical",
                    "message": f"Low market coverage: {coverage_report.coverage_percentage:.1f}%",
                    "details": {
                        "coverage_percentage": coverage_report.coverage_percentage,
                        "unmapped_markets": coverage_report.unmapped_markets,
                        "total_markets": coverage_report.total_open_markets,
                    }
                })
            
            if coverage_report.enablement_percentage < 90.0:
                alerts.append({
                    "type": "enablement",
                    "severity": "warning",
                    "message": f"Low enablement percentage: {coverage_report.enablement_percentage:.1f}%",
                    "details": {
                        "enablement_percentage": coverage_report.enablement_percentage,
                        "disabled_markets": coverage_report.disabled_markets,
                        "enabled_markets": coverage_report.enabled_markets,
                    }
                })
        
        # Sync staleness alerts
        sync_timestamps = store.get_sync_timestamps()
        current_time = sync_timestamps.get("current", 0)
        
        universe_age = current_time - sync_timestamps.get("kalshi", 0)
        if universe_age > 1800:  # 30 minutes
            alerts.append({
                "type": "sync_staleness",
                "severity": "critical" if universe_age > 3600 else "warning",
                "message": f"Universe sync is {universe_age/60:.0f} minutes old",
                "details": {
                    "age_minutes": universe_age / 60,
                    "last_sync": sync_timestamps.get("kalshi", 0),
                }
            })
        
        # Safety alerts
        coverage_stats = context_resolver.get_coverage_stats()
        validation_stats = coverage_stats.get("validation_stats", {})
        total_enabled = validation_stats.get("total_enabled", 0)
        safe_count = validation_stats.get("safe_to_trade", 0)
        
        if total_enabled > 0:
            safety_percentage = (safe_count / total_enabled) * 100
            if safety_percentage < 80.0:
                alerts.append({
                    "type": "safety",
                    "severity": "warning",
                    "message": f"Low market safety percentage: {safety_percentage:.1f}%",
                    "details": {
                        "safety_percentage": safety_percentage,
                        "safe_markets": safe_count,
                        "total_enabled": total_enabled,
                        "unsafe_markets": total_enabled - safe_count,
                    }
                })
        
        return {
            "success": True,
            "data": {
                "alerts": alerts,
                "alert_count": len(alerts),
                "critical_alerts": len([a for a in alerts if a["severity"] == "critical"]),
                "warning_alerts": len([a for a in alerts if a["severity"] == "warning"]),
                "timestamp": current_time,
            }
        }
        
    except Exception as e:
        logger.error(f"Failed to get alert summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))
