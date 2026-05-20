#!/usr/bin/env python3
"""
Drift Monitor Alerting Module

Simple alerting for Kalshi drift monitor using Slack and PagerDuty.

Alerts are sent only when status == DRIFTING or ERROR for N consecutive runs.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger("drift_alerting")


class DriftAlerter:
    """Alerting handler for drift monitor results."""

    def __init__(
        self,
        slack_webhook_url: Optional[str] = None,
        pagerduty_routing_key: Optional[str] = None,
        consecutive_threshold: int = 3,
    ):
        """
        Initialize the alerter.

        Args:
            slack_webhook_url: Slack webhook URL (from env SLACK_WEBHOOK_URL)
            pagerduty_routing_key: PagerDuty routing key (from env PAGERDUTY_ROUTING_KEY)
            consecutive_threshold: Number of consecutive failures before alerting
        """
        self.slack_webhook_url = slack_webhook_url or os.getenv("SLACK_WEBHOOK_URL")
        self.pagerduty_routing_key = pagerduty_routing_key or os.getenv("PAGERDUTY_ROUTING_KEY")
        self.consecutive_threshold = consecutive_threshold
        self.consecutive_failures = 0
        self.alerted = False

    def should_alert(self, status: str) -> bool:
        """
        Determine if we should alert based on status and consecutive failures.

        Args:
            status: Current status (OK, DRIFTING, ERROR)

        Returns:
            True if we should alert, False otherwise
        """
        if status == "OK":
            # Reset consecutive failures on OK
            if self.consecutive_failures > 0:
                logger.info(f"Status OK, resetting consecutive failures from {self.consecutive_failures}")
            self.consecutive_failures = 0
            
            # Resolve PagerDuty incident if we had previously alerted
            if self.alerted:
                self.resolve_pagerduty()
                self.alerted = False
            
            return False
        
        # Track consecutive failures
        if status in ("DRIFTING", "ERROR"):
            self.consecutive_failures += 1
            logger.info(f"Consecutive failures: {self.consecutive_failures}/{self.consecutive_threshold}")
            
            # Alert only after threshold
            if self.consecutive_failures >= self.consecutive_threshold and not self.alerted:
                self.alerted = True
                return True
        
        return False

    async def send_alert(
        self,
        status: str,
        discrepancy_count: int,
        worst_delta: float,
        asset_breakdown: dict,
        details: dict,
    ) -> None:
        """
        Send alert to configured channels.

        Args:
            status: Current status
            discrepancy_count: Number of discrepancies
            worst_delta: Worst delta observed
            asset_breakdown: Breakdown by asset
            details: Additional details
        """
        alert_data = {
            "status": status,
            "discrepancy_count": discrepancy_count,
            "worst_delta": worst_delta,
            "asset_breakdown": asset_breakdown,
            "details": details,
        }

        # Send to Slack
        if self.slack_webhook_url:
            await self.send_slack_alert(alert_data)

        # Send to PagerDuty
        if self.pagerduty_routing_key:
            await self.trigger_pagerduty(alert_data)

    async def send_slack_alert(self, data: dict) -> None:
        """
        Send alert to Slack webhook.

        Args:
            data: Alert data dictionary
        """
        try:
            message = f"""
🚨 Kalshi Drift Alert

Status: {data['status']}
Discrepancies: {data['discrepancy_count']}
Worst Delta: {data['worst_delta']}
Asset Breakdown: {json.dumps(data['asset_breakdown'], indent=2)}
Duration: {data['details'].get('duration_seconds', 'N/A')}s
Fills: {data['details'].get('fills_count', 'N/A')}
Positions: {data['details'].get('positions_count', 'N/A')}
"""
            
            payload = {
                "text": "Kalshi Drift Alert",
                "attachments": [
                    {
                        "color": "danger" if data['status'] == "ERROR" else "warning",
                        "text": message,
                        "footer": "Kalshi 15m Crypto Drift Monitor",
                        "ts": data['details'].get('timestamp', ''),
                    }
                ],
            }

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.slack_webhook_url,
                    json=payload,
                    timeout=10.0,
                )
                response.raise_for_status()
                
            logger.info("Slack alert sent successfully")
            
        except Exception as e:
            logger.error(f"Failed to send Slack alert: {e}")

    async def trigger_pagerduty(self, data: dict) -> None:
        """
        Trigger PagerDuty incident.

        Args:
            data: Alert data dictionary
        """
        try:
            payload = {
                "routing_key": self.pagerduty_routing_key,
                "event_action": "trigger",
                "payload": {
                    "summary": f"Kalshi Drift Alert: {data['status']} - {data['discrepancy_count']} discrepancies",
                    "severity": "error" if data['status'] == "ERROR" else "warning",
                    "source": "kalshi_drift_monitor",
                    "custom_details": data,
                },
            }

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://events.pagerduty.com/v2/enqueue",
                    json=payload,
                    timeout=10.0,
                )
                response.raise_for_status()
                
            logger.info("PagerDuty alert sent successfully")
            
        except Exception as e:
            logger.error(f"Failed to send PagerDuty alert: {e}")

    async def resolve_pagerduty(self) -> None:
        """
        Resolve PagerDuty incident when status returns to OK.
        """
        if not self.pagerduty_routing_key:
            return
            
        try:
            payload = {
                "routing_key": self.pagerduty_routing_key,
                "event_action": "resolve",
                "payload": {
                    "summary": "Kalshi Drift Monitor: Status returned to OK",
                    "severity": "info",
                    "source": "kalshi_drift_monitor",
                },
            }

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://events.pagerduty.com/v2/enqueue",
                    json=payload,
                    timeout=10.0,
                )
                response.raise_for_status()
                
            logger.info("PagerDuty incident resolved")
            
        except Exception as e:
            logger.error(f"Failed to resolve PagerDuty incident: {e}")
