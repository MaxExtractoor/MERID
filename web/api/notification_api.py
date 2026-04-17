"""
Notification API Endpoints
REST API for managing debate alert notifications and configuration.
"""

from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, HTTPException, Query, Body, Depends
from pydantic import BaseModel

from web.api.notification_worker import get_notification_worker
from web.api.notification_config import get_notification_config, NotificationChannel
from web.api.notification_router import get_notification_router
from web.api.auth import get_current_session

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])

# Pydantic models for API requests/responses
class ChannelStatus(BaseModel):
    channel: str
    enabled: bool
    configured: bool
    last_sent: Optional[datetime] = None
    rate_limit_status: Dict[str, Any]

class NotificationStatus(BaseModel):
    worker_running: bool
    last_poll: Optional[datetime] = None
    last_daily_summary: Optional[datetime] = None
    channels: List[ChannelStatus]

class ChannelConfigUpdate(BaseModel):
    enabled: Optional[bool] = None
    critical_alerts: Optional[bool] = None
    warning_alerts: Optional[bool] = None
    daily_summary: Optional[bool] = None

class RoutingConfigUpdate(BaseModel):
    critical_to_telegram: Optional[bool] = None
    critical_to_x: Optional[bool] = None
    warnings_to_telegram: Optional[bool] = None
    warnings_to_x: Optional[bool] = None
    high_utilization_only: Optional[bool] = None
    aggregate_similar: Optional[bool] = None

class TestNotificationRequest(BaseModel):
    channel: str
    message: Optional[str] = None

@router.get("/status", response_model=NotificationStatus)
async def get_notification_status(session=Depends(get_current_session)):
    """Get current status of the notification system."""
    worker = get_notification_worker()
    config_manager = get_notification_config()
    router = get_notification_router()
    
    # Get channel statuses
    channels = []
    
    # Telegram status
    telegram_config = config_manager.get_channel_config(NotificationChannel.TELEGRAM)
    telegram_status = ChannelStatus(
        channel="telegram",
        enabled=telegram_config.enabled,
        configured=router.telegram_client.is_configured(),
        rate_limit_status={
            "messages_per_hour": router.telegram_rate_limit["messages_per_hour"],
            "current_count": router.telegram_rate_limit["count"],
            "reset_time": router.telegram_rate_limit["last_reset"] + timedelta(hours=1)
        }
    )
    channels.append(telegram_status)
    
    # X/Twitter status
    x_config = config_manager.get_channel_config(NotificationChannel.X_TWITTER)
    x_status = ChannelStatus(
        channel="x_twitter",
        enabled=x_config.enabled,
        configured=router.x_client.is_configured(),
        rate_limit_status={
            "tweets_per_day": router.x_rate_limit["tweets_per_day"],
            "current_count": router.x_rate_limit["count"],
            "reset_date": router.x_rate_limit["last_reset"] + timedelta(days=1)
        }
    )
    channels.append(x_status)
    
    return NotificationStatus(
        worker_running=worker.running,
        channels=channels
    )

@router.post("/worker/start")
async def start_worker(session=Depends(get_current_session)):
    """Start the notification worker."""
    worker = get_notification_worker()
    
    if worker.running:
        return {"message": "Worker is already running"}
    
    # Start worker in background
    import asyncio
    asyncio.create_task(worker.start())
    
    return {"message": "Worker started"}

@router.post("/worker/stop")
async def stop_worker(session=Depends(get_current_session)):
    """Stop the notification worker."""
    worker = get_notification_worker()
    worker.stop()
    
    return {"message": "Worker stop requested"}

@router.post("/worker/run-once")
async def run_worker_once(session=Depends(get_current_session)):
    """Run a single notification worker cycle."""
    worker = get_notification_worker()
    
    try:
        success = await worker.run_once()
        return {
            "message": "Worker cycle completed",
            "success": success,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Worker cycle failed: {str(e)}")

@router.get("/config/channels/{channel}")
async def get_channel_config(channel: str, session=Depends(get_current_session)):
    """Get configuration for a specific channel."""
    try:
        channel_enum = NotificationChannel(channel)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid channel: {channel}")
    
    config_manager = get_notification_config()
    channel_config = config_manager.get_channel_config(channel_enum)
    
    return {
        "channel": channel,
        "enabled": channel_config.enabled,
        "critical_alerts": channel_config.critical_alerts,
        "warning_alerts": channel_config.warning_alerts,
        "daily_summary": channel_config.daily_summary,
        "rate_limit_messages_per_hour": channel_config.rate_limit_messages_per_hour,
        "rate_limit_tweets_per_day": channel_config.rate_limit_tweets_per_day
    }

@router.put("/config/channels/{channel}")
async def update_channel_config(
    channel: str, 
    updates: ChannelConfigUpdate,
    session=Depends(get_current_session)
):
    """Update configuration for a specific channel."""
    try:
        channel_enum = NotificationChannel(channel)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid channel: {channel}")
    
    config_manager = get_notification_config()
    
    # Convert updates to dict, removing None values
    update_dict = {k: v for k, v in updates.dict().items() if v is not None}
    
    if update_dict:
        config_manager.update_channel_config(channel_enum, update_dict)
    
    return {"message": f"Channel {channel} configuration updated"}

@router.get("/config/routing")
async def get_routing_config(session=Depends(get_current_session)):
    """Get routing configuration."""
    config_manager = get_notification_config()
    routing = config_manager.get_routing_rules()
    
    return {
        "critical_to_telegram": routing.critical_to_telegram,
        "critical_to_x": routing.critical_to_x,
        "warnings_to_telegram": routing.warnings_to_telegram,
        "warnings_to_x": routing.warnings_to_x,
        "high_utilization_only": routing.high_utilization_only,
        "aggregate_similar": routing.aggregate_similar
    }

@router.put("/config/routing")
async def update_routing_config(
    updates: RoutingConfigUpdate,
    session=Depends(get_current_session)
):
    """Update routing configuration."""
    config_manager = get_notification_config()
    
    # Convert updates to dict, removing None values
    update_dict = {k: v for k, v in updates.dict().items() if v is not None}
    
    if update_dict:
        config_manager.update_routing_config(update_dict)
    
    return {"message": "Routing configuration updated"}

@router.get("/config")
async def get_full_config(session=Depends(get_current_session)):
    """Get complete notification configuration."""
    config_manager = get_notification_config()
    
    return {
        "channels": {
            name: {
                "enabled": config.enabled,
                "critical_alerts": config.critical_alerts,
                "warning_alerts": config.warning_alerts,
                "daily_summary": config.daily_summary
            }
            for name, config in config_manager.config.channels.items()
        },
        "routing": {
            "critical_to_telegram": config_manager.config.routing.critical_to_telegram,
            "critical_to_x": config_manager.config.routing.critical_to_x,
            "warnings_to_telegram": config_manager.config.routing.warnings_to_telegram,
            "warnings_to_x": config_manager.config.routing.warnings_to_x,
            "high_utilization_only": config_manager.config.routing.high_utilization_only,
            "aggregate_similar": config_manager.config.routing.aggregate_similar
        },
        "poll_interval_minutes": config_manager.config.poll_interval_minutes,
        "daily_summary_time_utc": config_manager.config.daily_summary_time_utc
    }

@router.post("/test")
async def send_test_notification(
    request: TestNotificationRequest,
    session=Depends(get_current_session)
):
    """Send a test notification to verify channel configuration."""
    router = get_notification_router()
    
    try:
        channel_enum = NotificationChannel(request.channel)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid channel: {request.channel}")
    
    # Create test alert
    test_alert = {
        "agent_id": "test-agent",
        "tier": "gold",
        "utilization_pct": 0.95,
        "metric_id": "test-metric",
        "metric_label": "Test Notification",
        "severity": "warning",
        "message": request.message or "This is a test notification from the debate system",
        "triggered_at": datetime.now().isoformat() + "Z",
        "supporting_values": {}
    }
    
    success = False
    try:
        if channel_enum == NotificationChannel.TELEGRAM:
            if router.telegram_client.is_configured():
                from notification_formatters import format_telegram_alert
                message = format_telegram_alert(test_alert)
                success = await router.telegram_client.send_alert(message)
            else:
                raise HTTPException(status_code=400, detail="Telegram not configured")
        
        elif channel_enum == NotificationChannel.X_TWITTER:
            if router.x_client.is_configured():
                from notification_formatters import format_x_alert
                message = format_x_alert(test_alert)
                success = await router.x_client.send_alert(message)
            else:
                raise HTTPException(status_code=400, detail="X/Twitter not configured")
        
        if success:
            return {
                "message": f"Test notification sent to {request.channel}",
                "timestamp": datetime.now().isoformat()
            }
        else:
            raise HTTPException(status_code=500, detail=f"Failed to send test notification to {request.channel}")
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error sending test notification: {str(e)}")

@router.post("/daily-summary")
async def send_daily_summary(session=Depends(get_current_session)):
    """Manually trigger a daily summary notification."""
    worker = get_notification_worker()
    
    try:
        await worker.check_daily_summary()
        return {
            "message": "Daily summary triggered",
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error sending daily summary: {str(e)}")

@router.get("/recent-alerts")
async def get_recent_alerts(
    hours: int = Query(default=24, description="Hours of alerts to retrieve"),
    session=Depends(get_current_session)
):
    """Get recent alerts for debugging/monitoring."""
    try:
        from web.api.debate_data_api import get_debate_alerts
        
        alerts_response = await get_debate_alerts(
            days_back=max(1, hours // 24),
            tier="all",
            utilization_band="all",
            problems_only=False
        )
        
        if not alerts_response:
            return {"alerts": [], "total": 0, "hours": hours, "timestamp": datetime.now().isoformat()}
        
        # AlertsResponse is a Pydantic model — use attribute access
        raw_alerts = getattr(alerts_response, "alerts", None)
        if raw_alerts is None:
            raw_alerts = alerts_response.get("alerts", []) if isinstance(alerts_response, dict) else []
        alerts = [a.dict() if hasattr(a, "dict") else a for a in raw_alerts]
        
        # Filter by time window if needed
        if hours < 24:
            cutoff_time = datetime.now() - timedelta(hours=hours)
            filtered_alerts = []
            for alert in alerts:
                ts = alert.get("triggered_at", "") if isinstance(alert, dict) else getattr(alert, "triggered_at", "")
                try:
                    if datetime.fromisoformat(ts.replace("Z", "+00:00")) > cutoff_time:
                        filtered_alerts.append(alert)
                except (ValueError, AttributeError):
                    filtered_alerts.append(alert)
            alerts = filtered_alerts
        
        return {
            "alerts": alerts,
            "total": len(alerts),
            "hours": hours,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.warning("recent_alerts fallback: %s", e)
        return {"alerts": [], "total": 0, "hours": hours, "timestamp": datetime.now().isoformat()}
