"""
Notification & Alert API Endpoints.

Provides API access to notifications, alerts, and escalations.
"""

from __future__ import annotations

from typing import Dict, Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel

from notifications import (
    get_notification_manager,
    get_channel_manager,
    get_alert_rules_engine,
    get_escalation_manager,
)
from notifications.channels import ChannelType
from notifications.alert_rules import RuleCategory, RuleSeverity, RuleOperator, AlertRule, RuleCondition
from web.api.auth import get_current_session
from utils.logger import get_logger

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"], dependencies=[Depends(get_current_session)]  # ZT6-01
)
logger = get_logger("web.api.notifications")


# ============================================
# REQUEST MODELS
# ============================================

class SendNotificationRequest(BaseModel):
    channel: str
    recipient: str
    subject: str
    body: str
    priority: str = "normal"


class CreateAlertRuleRequest(BaseModel):
    name: str
    category: str
    severity: str
    field: str
    operator: str
    value: Any
    channels: List[str] = ["push"]
    template: str = ""
    cooldown_seconds: float = 300.0


class PriceAlertRequest(BaseModel):
    symbol: str
    target_price: float
    direction: str = "above"


class QuietHoursRequest(BaseModel):
    enabled: bool
    start_hour: int = 22
    end_hour: int = 8
    exceptions: List[str] = ["critical"]


class EvaluateDataRequest(BaseModel):
    source: str
    data: Dict[str, Any]


# ============================================
# NOTIFICATION MANAGER ENDPOINTS
# ============================================

@router.get("/status")
async def get_notification_status() -> Dict[str, Any]:
    """Get comprehensive notification status."""
    return get_notification_manager().get_status()


@router.post("/start")
async def start_notification_manager(background_tasks: BackgroundTasks) -> Dict[str, Any]:
    """Start notification manager."""
    manager = get_notification_manager()
    background_tasks.add_task(manager.start)
    return {"status": "starting"}


@router.post("/stop")
async def stop_notification_manager() -> Dict[str, Any]:
    """Stop notification manager."""
    await get_notification_manager().stop()
    return {"status": "stopped"}


@router.post("/send")
async def send_notification(request: SendNotificationRequest) -> Dict[str, Any]:
    """Send a notification directly."""
    message_id = await get_notification_manager().send(
        channel=request.channel,
        recipient=request.recipient,
        subject=request.subject,
        body=request.body,
        priority=request.priority,
    )
    if message_id:
        return {"status": "sent", "message_id": message_id}
    raise HTTPException(status_code=400, detail="Send failed")


@router.get("/history")
async def get_notification_history(limit: int = 100) -> Dict[str, Any]:
    """Get notification history."""
    history = get_notification_manager().get_notification_history(limit)
    return {"count": len(history), "notifications": history}


@router.post("/quiet-hours")
async def set_quiet_hours(request: QuietHoursRequest) -> Dict[str, Any]:
    """Configure quiet hours."""
    get_notification_manager().set_quiet_hours(
        enabled=request.enabled,
        start_hour=request.start_hour,
        end_hour=request.end_hour,
        exceptions=request.exceptions,
    )
    return {"status": "updated"}


# ============================================
# CHANNEL ENDPOINTS
# ============================================

@router.get("/channels")
async def get_channels() -> Dict[str, Any]:
    """Get channel status."""
    return get_channel_manager().get_status()


@router.post("/channels/{channel}/enable")
async def enable_channel(channel: str) -> Dict[str, Any]:
    """Enable a notification channel."""
    try:
        channel_type = ChannelType(channel)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid channel: {channel}")
    
    get_channel_manager().enable_channel(channel_type)
    return {"status": "enabled", "channel": channel}


@router.post("/channels/{channel}/disable")
async def disable_channel(channel: str) -> Dict[str, Any]:
    """Disable a notification channel."""
    try:
        channel_type = ChannelType(channel)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid channel: {channel}")
    
    get_channel_manager().disable_channel(channel_type)
    return {"status": "disabled", "channel": channel}


# ============================================
# ALERT RULES ENDPOINTS
# ============================================

@router.get("/rules")
async def get_alert_rules() -> Dict[str, Any]:
    """Get all alert rules."""
    return get_alert_rules_engine().get_status()


@router.post("/rules")
async def create_alert_rule(request: CreateAlertRuleRequest) -> Dict[str, Any]:
    """Create a new alert rule."""
    import uuid
    
    try:
        category = RuleCategory(request.category)
        severity = RuleSeverity(request.severity)
        operator = RuleOperator(request.operator)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    rule_id = f"rule_{uuid.uuid4().hex[:8]}"
    
    rule = AlertRule(
        rule_id=rule_id,
        name=request.name,
        category=category,
        severity=severity,
        conditions=[
            RuleCondition(
                field=request.field,
                operator=operator,
                value=request.value,
            )
        ],
        notification_channels=request.channels,
        notification_template=request.template or f"{request.name}: {{{request.field}}}",
        cooldown_seconds=request.cooldown_seconds,
    )
    
    get_alert_rules_engine().add_rule(rule)
    return {"status": "created", "rule_id": rule_id}


@router.get("/rules/{rule_id}")
async def get_alert_rule(rule_id: str) -> Dict[str, Any]:
    """Get a specific alert rule."""
    rule = get_alert_rules_engine().get_rule(rule_id)
    if rule:
        return rule.to_dict()
    raise HTTPException(status_code=404, detail="Rule not found")


@router.delete("/rules/{rule_id}")
async def delete_alert_rule(rule_id: str) -> Dict[str, Any]:
    """Delete an alert rule."""
    success = get_alert_rules_engine().remove_rule(rule_id)
    if success:
        return {"status": "deleted"}
    raise HTTPException(status_code=404, detail="Rule not found")


@router.post("/rules/{rule_id}/enable")
async def enable_alert_rule(rule_id: str) -> Dict[str, Any]:
    """Enable an alert rule."""
    success = get_alert_rules_engine().enable_rule(rule_id)
    if success:
        return {"status": "enabled"}
    raise HTTPException(status_code=404, detail="Rule not found")


@router.post("/rules/{rule_id}/disable")
async def disable_alert_rule(rule_id: str) -> Dict[str, Any]:
    """Disable an alert rule."""
    success = get_alert_rules_engine().disable_rule(rule_id)
    if success:
        return {"status": "disabled"}
    raise HTTPException(status_code=404, detail="Rule not found")


@router.post("/rules/price-alert")
async def create_price_alert(request: PriceAlertRequest) -> Dict[str, Any]:
    """Create a simple price alert."""
    rule_id = get_notification_manager().create_price_alert(
        symbol=request.symbol,
        target_price=request.target_price,
        direction=request.direction,
    )
    return {"status": "created", "rule_id": rule_id}


@router.get("/rules/triggered")
async def get_triggered_rules(since: Optional[float] = None) -> Dict[str, Any]:
    """Get recently triggered rules."""
    rules = get_alert_rules_engine().get_triggered_rules(since)
    return {"count": len(rules), "rules": [r.to_dict() for r in rules]}


@router.post("/rules/evaluate")
async def evaluate_data(request: EvaluateDataRequest) -> Dict[str, Any]:
    """Evaluate data against alert rules."""
    triggered = get_notification_manager().evaluate_data(request.source, request.data)
    return {"triggered_rules": triggered, "count": len(triggered)}


# ============================================
# ESCALATION ENDPOINTS
# ============================================

@router.get("/escalations")
async def get_escalations() -> Dict[str, Any]:
    """Get escalation status."""
    return get_escalation_manager().get_status()


@router.get("/escalations/active")
async def get_active_escalations() -> Dict[str, Any]:
    """Get active escalations."""
    escalations = get_notification_manager().get_active_escalations()
    return {"count": len(escalations), "escalations": escalations}


@router.get("/escalations/{escalation_id}")
async def get_escalation(escalation_id: str) -> Dict[str, Any]:
    """Get a specific escalation."""
    escalation = get_escalation_manager().get_escalation(escalation_id)
    if escalation:
        return escalation.to_dict()
    raise HTTPException(status_code=404, detail="Escalation not found")


@router.post("/escalations/{escalation_id}/acknowledge")
async def acknowledge_escalation(escalation_id: str, by: str = "user") -> Dict[str, Any]:
    """Acknowledge an escalation."""
    success = get_notification_manager().acknowledge_escalation(escalation_id, by)
    if success:
        return {"status": "acknowledged"}
    raise HTTPException(status_code=404, detail="Escalation not found")


@router.post("/escalations/{escalation_id}/resolve")
async def resolve_escalation(escalation_id: str, by: str = "user") -> Dict[str, Any]:
    """Resolve an escalation."""
    success = get_notification_manager().resolve_escalation(escalation_id, by)
    if success:
        return {"status": "resolved"}
    raise HTTPException(status_code=404, detail="Escalation not found")


# ============================================
# POLICIES ENDPOINTS
# ============================================

@router.get("/telegram/log")
async def get_telegram_log(limit: int = 50) -> Dict[str, Any]:
    """Return recent Telegram messages sent by TelegramAgent for the log viewer."""
    messages = []
    enabled = True
    try:
        from agents.telegram_agent import get_telegram_agent
        agent = get_telegram_agent()
        msgs = agent.get_recent_messages(limit=limit)
        enabled = agent.enabled
        messages = [
            {
                "id": str(m.message_id or i),
                "timestamp": m.sent_at.isoformat() if m.sent_at else "",
                "direction": "outbound",
                "type": _classify_telegram_msg(m.text),
                "text": m.text[:500],
                "chatId": str(m.chat_id or ""),
                "delivered": m.message_id is not None,
            }
            for i, m in enumerate(msgs)
        ]
    except Exception as exc:
        logger.debug(f"Telegram log fetch error: {exc}")

    # Fallback: surface recent system notifications as telegram-style entries
    if not messages:
        try:
            from core.notifications import get_notification_store
            store = get_notification_store()
            notes = store.list(limit=limit)
            logger.debug(f"Telegram fallback: {len(notes)} notifications from store")
            for i, n in enumerate(notes):
                nd = n.to_dict() if hasattr(n, "to_dict") else {}
                messages.append({
                    "id": getattr(n, "id", f"sys-{i}"),
                    "timestamp": nd.get("timestamp", ""),
                    "direction": "outbound",
                    "type": nd.get("type", "system"),
                    "text": nd.get("message", nd.get("title", "")),
                    "chatId": "merid-system",
                    "delivered": True,
                })
        except Exception as exc2:
            logger.debug(f"Telegram fallback notification store failed: {exc2}")

    return {"messages": messages, "enabled": enabled, "total": len(messages)}


def _classify_telegram_msg(text: str) -> str:
    """Classify a Telegram message into a UI type."""
    t = text.lower()
    if any(k in t for k in ("kill switch", "emergency", "halt", "🚨")):
        return "alert"
    if any(k in t for k in ("fill", "order", "trade", "filled", "💰")):
        return "trade"
    if any(k in t for k in ("status", "portfolio", "balance", "📊")):
        return "status"
    if any(k in t for k in ("/", "command", "bot")):
        return "command"
    return "system"


@router.get("/telegram/status")
async def get_telegram_status() -> Dict[str, Any]:
    """Return Telegram bot connection status."""
    try:
        from agents.telegram_agent import get_telegram_agent
        agent = get_telegram_agent()
        return {
            "enabled": agent.enabled,
            "connected": agent.enabled,
            "chat_id": agent.chat_id if hasattr(agent, "chat_id") else "",
            "messages_sent": len(agent.recent_messages) if hasattr(agent, "recent_messages") else 0,
        }
    except Exception as exc:
        logger.debug("telegram/status: %s", exc)
        return {"enabled": False, "connected": False, "chat_id": "", "messages_sent": 0}


@router.post("/telegram/send")
async def send_telegram_message(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Send a manual Telegram message."""
    text = payload.get("text", payload.get("message", ""))
    if not text:
        raise HTTPException(status_code=400, detail="text is required")
    try:
        from agents.telegram_agent import get_telegram_agent
        agent = get_telegram_agent()
        msg = await agent.send_message(text)
        return {"sent": msg is not None, "message_id": getattr(msg, "message_id", None)}
    except Exception as exc:
        logger.warning("telegram/send failed: %s", exc)
        return {"sent": False, "error": str(exc)}


@router.get("/policies")
async def get_escalation_policies() -> Dict[str, Any]:
    """Get escalation policies."""
    policies = get_escalation_manager()._policies
    return {
        "count": len(policies),
        "policies": [p.to_dict() for p in policies.values()],
    }
