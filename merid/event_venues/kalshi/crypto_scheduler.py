"""
Crypto Bot Scheduler Integration

Wire crypto bot into MERID's scheduler system
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Any

logger = logging.getLogger(__name__)

class CryptoBotScheduler:
    """Scheduler for crypto bot trading cycles"""
    
    def __init__(self, crypto_bot, config: Dict[str, Any]):
        self.bot = crypto_bot
        self.config = config
        self.is_running = False
        self.last_run = None
        self.run_interval = config.get("run_interval_minutes", 5)
        self.dry_run = config.get("dry_run", True)
    
    async def start(self):
        """Start the crypto bot scheduler"""
        if self.is_running:
            logger.warning("Crypto bot scheduler already running")
            return
        
        self.is_running = True
        logger.info(f"Starting crypto bot scheduler (interval: {self.run_interval_minutes} minutes)")
        
        while self.is_running:
            try:
                await self.run_cycle()
                await asyncio.sleep(self.run_interval * 60)
            except Exception as e:
                logger.error(f"Error in crypto bot cycle: {e}")
                await asyncio.sleep(60)  # Wait 1 minute before retry
    
    async def stop(self):
        """Stop the crypto bot scheduler"""
        self.is_running = False
        logger.info("Crypto bot scheduler stopped")
    
    async def run_cycle(self):
        """Run one crypto bot cycle"""
        cycle_start = datetime.now(timezone.utc)
        
        try:
            logger.info("Starting crypto bot cycle")
            
            result = await self.bot.run_cycle()
            
            self.last_run = {
                "timestamp": cycle_start.isoformat(),
                "result": result,
                "duration_seconds": (datetime.now(timezone.utc) - cycle_start).total_seconds()
            }
            
            logger.info(f"Crypto bot cycle completed: {result['status']}")
            
            # Log trading opportunities
            if result.get("status") == "cycle_complete":
                logger.info(f"Trading opportunity found: {result.get('target_market')}")
            
        except Exception as e:
            logger.error(f"Crypto bot cycle failed: {e}")
            self.last_run = {
                "timestamp": cycle_start.isoformat(),
                "error": str(e),
                "duration_seconds": (datetime.now(timezone.utc) - cycle_start).total_seconds()
            }
    
    def get_status(self) -> Dict[str, Any]:
        """Get scheduler status"""
        return {
            "is_running": self.is_running,
            "last_run": self.last_run,
            "run_interval_minutes": self.run_interval,
            "dry_run": self.dry_run,
            "config": self.config
        }

# Global scheduler instance
_crypto_scheduler = None

def get_crypto_scheduler() -> CryptoBotScheduler:
    """Get global crypto scheduler instance"""
    return _crypto_scheduler

def initialize_crypto_scheduler(crypto_bot, config: Dict[str, Any] = None):
    """Initialize crypto scheduler"""
    global _crypto_scheduler
    
    if config is None:
        config = {
            "run_interval_minutes": 5,
            "dry_run": True,
            "max_position": 1000,
            "risk_per_trade": 0.02
        }
    
    _crypto_scheduler = CryptoBotScheduler(crypto_bot, config)
    return _crypto_scheduler

async def start_crypto_scheduler():
    """Start crypto scheduler"""
    scheduler = get_crypto_scheduler()
    if scheduler:
        await scheduler.start()

async def stop_crypto_scheduler():
    """Stop crypto scheduler"""
    scheduler = get_crypto_scheduler()
    if scheduler:
        await scheduler.stop()
