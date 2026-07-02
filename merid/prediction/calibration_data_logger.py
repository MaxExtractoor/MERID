"""
Continuous calibration data logger.

This module continuously logs calibration data for per-asset model fitting.
Logs:
- Full Kalshi series/events/markets for 15m crypto markets
- Order book snapshots around trade times and at expiry
- Spot proxy values and realized RTI at/near settlement
"""

import os
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional, Any

logger = logging.getLogger(__name__)


class CalibrationDataLogger:
    """Continuous calibration data logger."""
    
    def __init__(self, log_dir: Optional[str] = None):
        """
        Initialize calibration data logger.
        
        Args:
            log_dir: Directory to store calibration data logs
        """
        self.enabled = os.getenv('CALIBRATION_DATA_LOGGING_ENABLED', 'false').lower() == 'true'
        self.log_dir = Path(log_dir or os.getenv('CALIBRATION_DATA_LOG_DIR', '/var/log/merid/calibration'))
        self.retention_days = int(os.getenv('CALIBRATION_DATA_RETENTION_DAYS', '90'))
        
        if self.enabled:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            logger.info(
                "[CALIBRATION-LOGGER] Initialized with log_dir=%s, retention_days=%d",
                self.log_dir, self.retention_days
            )
        else:
            logger.info("[CALIBRATION-LOGGER] Disabled (CALIBRATION_DATA_LOGGING_ENABLED=false)")
    
    def log_market_metadata(self, market_id: str, metadata: Dict[str, Any]):
        """
        Log market metadata.
        
        Args:
            market_id: Market ID
            metadata: Market metadata dictionary
        """
        if not self.enabled:
            return
        
        try:
            timestamp = datetime.now(timezone.utc).isoformat()
            log_entry = {
                "timestamp": timestamp,
                "market_id": market_id,
                "type": "market_metadata",
                "data": metadata,
            }
            
            # Write to daily log file
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            log_file = self.log_dir / f"market_metadata_{date_str}.jsonl"
            
            with open(log_file, 'a') as f:
                f.write(json.dumps(log_entry) + '\n')
            
            logger.debug(
                "[CALIBRATION-LOGGER] Logged market metadata for %s",
                market_id
            )
        except Exception as e:
            logger.error(
                "[CALIBRATION-LOGGER-ERROR] Failed to log market metadata for %s: %s",
                market_id, e
            )
    
    def log_orderbook_snapshot(self, market_id: str, orderbook: Dict[str, Any]):
        """
        Log order book snapshot.
        
        Args:
            market_id: Market ID
            orderbook: Order book snapshot dictionary
        """
        if not self.enabled:
            return
        
        try:
            timestamp = datetime.now(timezone.utc).isoformat()
            log_entry = {
                "timestamp": timestamp,
                "market_id": market_id,
                "type": "orderbook_snapshot",
                "data": orderbook,
            }
            
            # Write to daily log file
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            log_file = self.log_dir / f"orderbook_{date_str}.jsonl"
            
            with open(log_file, 'a') as f:
                f.write(json.dumps(log_entry) + '\n')
            
            logger.debug(
                "[CALIBRATION-LOGGER] Logged orderbook snapshot for %s",
                market_id
            )
        except Exception as e:
            logger.error(
                "[CALIBRATION-LOGGER-ERROR] Failed to log orderbook snapshot for %s: %s",
                market_id, e
            )
    
    def log_spot_proxy(self, asset: str, spot_price: float, source: str):
        """
        Log spot proxy value.
        
        Args:
            asset: Asset symbol
            spot_price: Spot price in USD
            source: Spot source (CFB, composite, etc.)
        """
        if not self.enabled:
            return
        
        try:
            timestamp = datetime.now(timezone.utc).isoformat()
            log_entry = {
                "timestamp": timestamp,
                "asset": asset,
                "type": "spot_proxy",
                "data": {
                    "spot_price": spot_price,
                    "source": source,
                },
            }
            
            # Write to daily log file
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            log_file = self.log_dir / f"spot_proxy_{date_str}.jsonl"
            
            with open(log_file, 'a') as f:
                f.write(json.dumps(log_entry) + '\n')
            
            logger.debug(
                "[CALIBRATION-LOGGER] Logged spot proxy for %s: %.2f (%s)",
                asset, spot_price, source
            )
        except Exception as e:
            logger.error(
                "[CALIBRATION-LOGGER-ERROR] Failed to log spot proxy for %s: %s",
                asset, e
            )
    
    def log_unified_edge_decision(
        self,
        market_id: str,
        asset: str,
        edge: float,
        edge_risk_adjusted: float,
        edge_slippage_adjusted: float,
        confidence: float,
        decision: str
    ):
        """
        Log unified edge decision.
        
        Args:
            market_id: Market ID
            asset: Asset symbol
            edge: Raw edge
            edge_risk_adjusted: Risk-adjusted edge
            edge_slippage_adjusted: Slippage-adjusted edge
            confidence: Confidence score
            decision: Decision (take, skip, reject)
        """
        if not self.enabled:
            return
        
        try:
            timestamp = datetime.now(timezone.utc).isoformat()
            log_entry = {
                "timestamp": timestamp,
                "market_id": market_id,
                "asset": asset,
                "type": "unified_edge_decision",
                "data": {
                    "edge": edge,
                    "edge_risk_adjusted": edge_risk_adjusted,
                    "edge_slippage_adjusted": edge_slippage_adjusted,
                    "confidence": confidence,
                    "decision": decision,
                },
            }
            
            # Write to daily log file
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            log_file = self.log_dir / f"unified_edge_{date_str}.jsonl"
            
            with open(log_file, 'a') as f:
                f.write(json.dumps(log_entry) + '\n')
            
            logger.debug(
                "[CALIBRATION-LOGGER] Logged unified edge decision for %s: %s",
                market_id, decision
            )
        except Exception as e:
            logger.error(
                "[CALIBRATION-LOGGER-ERROR] Failed to log unified edge decision for %s: %s",
                market_id, e
            )
    
    def log_risk_routing_decision(
        self,
        market_id: str,
        asset: str,
        contracts: int,
        risk_usd: float,
        edge_r: float,
        decision: str
    ):
        """
        Log risk routing decision.
        
        Args:
            market_id: Market ID
            asset: Asset symbol
            contracts: Number of contracts
            risk_usd: Risk in USD
            edge_r: Edge_R (edge / volatility)
            decision: Decision (allocate, skip, reject)
        """
        if not self.enabled:
            return
        
        try:
            timestamp = datetime.now(timezone.utc).isoformat()
            log_entry = {
                "timestamp": timestamp,
                "market_id": market_id,
                "asset": asset,
                "type": "risk_routing_decision",
                "data": {
                    "contracts": contracts,
                    "risk_usd": risk_usd,
                    "edge_r": edge_r,
                    "decision": decision,
                },
            }
            
            # Write to daily log file
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            log_file = self.log_dir / f"risk_routing_{date_str}.jsonl"
            
            with open(log_file, 'a') as f:
                f.write(json.dumps(log_entry) + '\n')
            
            logger.debug(
                "[CALIBRATION-LOGGER] Logged risk routing decision for %s: %s",
                market_id, decision
            )
        except Exception as e:
            logger.error(
                "[CALIBRATION-LOGGER-ERROR] Failed to log risk routing decision for %s: %s",
                market_id, e
            )
    
    def cleanup_old_logs(self):
        """Clean up logs older than retention period."""
        if not self.enabled:
            return
        
        try:
            cutoff_date = datetime.now(timezone.utc).timestamp() - (self.retention_days * 86400)
            
            for log_file in self.log_dir.glob("*.jsonl"):
                if log_file.stat().st_mtime < cutoff_date:
                    log_file.unlink()
                    logger.info(
                        "[CALIBRATION-LOGGER] Cleaned up old log: %s",
                        log_file.name
                    )
        except Exception as e:
            logger.error(
                "[CALIBRATION-LOGGER-ERROR] Failed to cleanup old logs: %s",
                e
            )


# Singleton instance
_calibration_data_logger: Optional[CalibrationDataLogger] = None


def get_calibration_data_logger(log_dir: Optional[str] = None) -> CalibrationDataLogger:
    """
    Get the singleton calibration data logger instance.
    
    Args:
        log_dir: Directory to store calibration data logs
    
    Returns:
        Calibration data logger instance
    """
    global _calibration_data_logger
    if _calibration_data_logger is None:
        _calibration_data_logger = CalibrationDataLogger(log_dir=log_dir)
    return _calibration_data_logger
