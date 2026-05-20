"""
Notification Formatters for Alerts
Converts AlertItem objects into platform-specific message formats.
"""

from typing import Dict, Any
from datetime import datetime

# AlertItem structure for notification alerts
AlertItem = Dict[str, Any]

def format_telegram_alert(alert: AlertItem) -> str:
    """
    Format an alert for Telegram.

    Args:
        alert: AlertItem with agent_id, tier, utilization_pct, metric_id, metric_label, severity, message, triggered_at

    Returns:
        Formatted Telegram message with emoji and markdown
    """
    severity_emoji = "🔴" if alert["severity"] == "critical" else "🟡"
    tier_emoji = {
        "gold": "🥇",
        "silver": "🥈", 
        "bronze": "🥉",
        "restricted": "🔒"
    }.get(alert["tier"], "❓")
    
    # Format utilization percentage
    util_pct = alert["utilization_pct"] * 100
    util_emoji = "📈" if util_pct > 90 else "📊"
    
    # Format timestamp
    triggered_at = datetime.fromisoformat(alert["triggered_at"].replace("Z", "+00:00"))
    time_str = triggered_at.strftime("%H:%M UTC")
    
    message = f"""
{severity_emoji} **Debate Alert** {time_str}

{tier_emoji} **Agent:** `{alert['agent_id']}`
📊 **Tier:** {alert['tier'].upper()}
{util_emoji} **Utilization:** {util_pct:.1f}%

🔍 **Issue:** {alert['message']}
📈 **Metric:** {alert['metric_label']}

#debate #alert #{'critical' if alert['severity'] == 'critical' else 'warning'}
    """.strip()
    
    return message

def format_x_alert(alert: AlertItem) -> str:
    """
    Format a debate alert for X/Twitter (≤280 chars).
    
    Args:
        alert: AlertItem from debate alerts endpoint
        
    Returns:
        Concise X status update under 280 characters
    """
    severity_tag = "CRITICAL" if alert["severity"] == "critical" else "WARNING"
    agent_id = alert["agent_id"]
    issue = alert["message"]
    
    # Truncate if needed to stay under 280 chars
    base_msg = f"🚨 {severity_tag}: {agent_id} - {issue}"
    
    if len(base_msg) <= 240:
        return f"{base_msg} #debate #trading"
    else:
        # Need to truncate more aggressively
        max_issue_len = 240 - len(f"🚨 {severity_tag}: {agent_id} - ... #debate #trading")
        truncated_issue = issue[:max_issue_len-3] + "..."
        return f"🚨 {severity_tag}: {agent_id} - {truncated_issue} #debate #trading"

def format_daily_summary(alerts: list[AlertItem], rollups: list[Dict[str, Any]]) -> str:
    """
    Format a daily summary of debate activity for Telegram.
    
    Args:
        alerts: List of alerts from the past 24 hours
        rollups: Rollup data showing team/strategy performance
        
    Returns:
        Formatted daily summary message
    """
    critical_count = sum(1 for alert in alerts if alert["severity"] == "critical")
    warning_count = len(alerts) - critical_count
    
    # Calculate top performers from rollups
    top_teams = sorted(rollups, key=lambda x: x["debate_contribution_pct"], reverse=True)[:3]
    
    summary = f"""
📊 **Daily Debate Summary** ({datetime.now().strftime("%Y-%m-%d")})

🚨 **Alerts:** {critical_count} critical, {warning_count} warnings

🏆 **Top Teams:**
"""
    
    for i, team in enumerate(top_teams, 1):
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉"
        contribution_pct = team["debate_contribution_pct"] * 100
        summary += f"{medal} {team['label']}: +{contribution_pct:.1f}%\n"
    
    summary += "\n#debate #daily #summary"
    
    return summary.strip()

def format_x_daily_summary(alerts: list[AlertItem], rollups: list[Dict[str, Any]]) -> str:
    """
    Format a daily summary for X/Twitter.
    
    Args:
        alerts: List of alerts from the past 24 hours  
        rollups: Rollup data showing team/strategy performance
        
    Returns:
        Concise daily summary under 280 characters
    """
    critical_count = sum(1 for alert in alerts if alert["severity"] == "critical")
    total_alerts = len(alerts)
    
    if rollups:
        best_team = max(rollups, key=lambda x: x["debate_contribution_pct"])
        best_contribution = best_team["debate_contribution_pct"] * 100
        return f"📊 Daily Debate: {total_alerts} alerts ({critical_count} critical). Best: {best_team['label']} +{best_contribution:.1f}% #debate #trading"
    else:
        return f"📊 Daily Debate: {total_alerts} alerts ({critical_count} critical). View dashboard for details. #debate #trading"

def aggregate_similar_alerts(alerts: list[AlertItem]) -> list[Dict[str, Any]]:
    """
    Aggregate similar alerts to reduce notification spam.
    
    Args:
        alerts: List of alerts to aggregate
        
    Returns:
        List of aggregated alert groups
    """
    # Group by metric_id and severity
    groups: Dict[str, list[AlertItem]] = {}
    
    for alert in alerts:
        key = f"{alert['metric_id']}_{alert['severity']}"
        if key not in groups:
            groups[key] = []
        groups[key].append(alert)
    
    aggregated = []
    for key, group_alerts in groups.items():
        if len(group_alerts) == 1:
            # Single alert, keep as-is
            aggregated.append({"type": "single", "alert": group_alerts[0]})
        else:
            # Multiple similar alerts, aggregate
            parts = key.split('_')
            if len(parts) >= 2:
                metric_id, severity = parts[0], parts[1]
            else:
                metric_id = key
                severity = "unknown"
            agent_ids = [alert["agent_id"] for alert in group_alerts]
            avg_utilization = sum(alert["utilization_pct"] for alert in group_alerts) / len(group_alerts)
            
            aggregated.append({
                "type": "aggregated",
                "metric_id": metric_id,
                "severity": severity,
                "agent_ids": agent_ids,
                "count": len(group_alerts),
                "avg_utilization_pct": avg_utilization,
                "message": f"{len(group_alerts)} agents: {', '.join(agent_ids[:3])}{'...' if len(agent_ids) > 3 else ''}",
                "triggered_at": max(alert["triggered_at"] for alert in group_alerts)
            })
    
    return aggregated
