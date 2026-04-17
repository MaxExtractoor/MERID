"""
Notification Worker for Debate Alerts
Periodically polls for alerts and routes them to notification channels.
"""

import asyncio
import logging
import threading
from datetime import datetime, timedelta
from typing import Optional

from web.api.debate_data_api import get_debate_alerts, get_debate_rollups
from web.api.notification_router import get_notification_router

logger = logging.getLogger(__name__)

class NotificationWorker:
    """Worker that periodically polls for debate alerts and sends notifications."""
    
    def __init__(self, poll_interval_minutes: int = 5):
        """
        Initialize the notification worker.
        
        Args:
            poll_interval_minutes: How often to poll for alerts (default: 5 minutes)
        """
        self.poll_interval = timedelta(minutes=poll_interval_minutes)
        self.router = get_notification_router()
        self.running = False
        self.last_daily_summary_date = None
        
    async def poll_and_process_alerts(self) -> bool:
        """
        Poll for new alerts and process them.
        
        Returns:
            True if any alerts were processed, False otherwise
        """
        try:
            # Get alerts from the last 24 hours (problems only)
            alerts_response = await get_debate_alerts(
                days_back=1,
                tier="all",
                utilization_band="all",
                problems_only=True
            )
            
            if not alerts_response or not alerts_response.get("alerts"):
                logger.debug("No new alerts found")
                return False
            
            alerts = alerts_response["alerts"]
            logger.info(f"Found {len(alerts)} alerts to process")
            
            # Process alerts through the router
            success = await self.router.process_alerts(alerts)
            
            # Check if we should send a daily summary
            await self.check_daily_summary()
            
            return success
            
        except Exception as e:
            logger.error(f"Error polling for alerts: {e}")
            return False
    
    async def check_daily_summary(self):
        """Check if we should send a daily summary and send it if needed."""
        today = datetime.now().date()
        
        # Send daily summary once per day at 9 AM UTC
        if (self.last_daily_summary_date != today and 
            datetime.now().hour >= 9):
            
            try:
                logger.info("Sending daily summary")
                
                # Get alerts from the past 24 hours
                alerts_response = await get_debate_alerts(
                    days_back=1,
                    tier="all", 
                    utilization_band="all",
                    problems_only=False
                )
                
                # Get rollups for the past 24 hours
                rollups_response = await get_debate_rollups(
                    group_by="team",
                    days_back=1
                )
                
                alerts = alerts_response.get("alerts", []) if alerts_response else []
                rollups = rollups_response.get("rows", []) if rollups_response else []
                
                # Send daily summary
                await self.router.send_daily_summary(alerts, rollups)
                
                self.last_daily_summary_date = today
                logger.info("Daily summary sent successfully")
                
            except Exception as e:
                logger.error(f"Error sending daily summary: {e}")
    
    async def run_once(self):
        """Run a single poll and process cycle."""
        logger.info("Running notification worker cycle")
        
        try:
            success = await self.poll_and_process_alerts()
            
            if success:
                logger.info("Notification worker cycle completed successfully")
            else:
                logger.debug("No alerts to process in this cycle")
                
        except Exception as e:
            logger.error(f"Error in notification worker cycle: {e}")
    
    async def start(self):
        """Start the notification worker loop."""
        if self.running:
            logger.warning("Notification worker is already running")
            return
        
        self.running = True
        logger.info(f"Starting notification worker with {self.poll_interval.total_seconds()/60:.1f} minute intervals")
        
        while self.running:
            try:
                await self.run_once()
                
                # Wait for next poll
                await asyncio.sleep(self.poll_interval.total_seconds())
                
            except asyncio.CancelledError:
                logger.info("Notification worker cancelled")
                break
            except Exception as e:
                logger.error(f"Unexpected error in notification worker loop: {e}")
                # Continue running despite errors
                await asyncio.sleep(min(60, self.poll_interval.total_seconds()))  # Wait at least 1 minute
    
    def stop(self):
        """Stop the notification worker."""
        self.running = False
        logger.info("Notification worker stop requested")

# Global worker instance
_notification_worker: Optional[NotificationWorker] = None
_notification_worker_lock = threading.Lock()

def get_notification_worker() -> NotificationWorker:
    """Get or create the global notification worker instance."""
    global _notification_worker
    if _notification_worker is None:  # E3a: double-checked locking
        with _notification_worker_lock:
            if _notification_worker is None:
                _notification_worker = NotificationWorker()
    return _notification_worker

# CLI entry point for testing
async def main():
    """CLI entry point for testing the notification worker."""
    import sys
    
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    worker = get_notification_worker()
    
    if len(sys.argv) > 1 and sys.argv[1] == "--once":
        # Run a single cycle for testing
        await worker.run_once()
    else:
        # Run continuously
        try:
            await worker.start()
        except KeyboardInterrupt:
            logger.info("Received interrupt signal")
            worker.stop()

if __name__ == "__main__":
    asyncio.run(main())
