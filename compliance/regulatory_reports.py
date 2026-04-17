"""
Regulatory Report Generator.

Generates compliance reports for various regulatory requirements.

Version: 1.0.0
"""

from __future__ import annotations

import threading
import json
import time
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timezone, timedelta

from compliance.transaction_log import TransactionLog, get_transaction_log, TransactionType
from compliance.audit_logger import AuditLogger, get_audit_logger
from utils.logger import get_logger

logger = get_logger("compliance.reports")


class ReportType(Enum):
    """Types of regulatory reports."""
    DAILY_ACTIVITY = "daily_activity"
    MONTHLY_SUMMARY = "monthly_summary"
    QUARTERLY_REPORT = "quarterly_report"
    ANNUAL_REPORT = "annual_report"
    TAX_REPORT = "tax_report"
    SUSPICIOUS_ACTIVITY = "suspicious_activity"
    LARGE_TRANSACTION = "large_transaction"
    POSITION_REPORT = "position_report"


class ReportFormat(Enum):
    """Report output formats."""
    JSON = "json"
    CSV = "csv"
    PDF = "pdf"
    HTML = "html"


@dataclass
class ReportConfig:
    """Configuration for a report type."""
    report_type: ReportType
    name: str
    description: str
    
    # Schedule
    auto_generate: bool = False
    schedule_cron: str = ""  # e.g., "0 0 * * *" for daily
    
    # Thresholds
    large_transaction_threshold_usd: float = 10000.0
    suspicious_activity_threshold: float = 5.0  # Standard deviations
    
    # Recipients
    recipients: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "report_type": self.report_type.value,
            "name": self.name,
            "description": self.description,
            "auto_generate": self.auto_generate,
            "schedule_cron": self.schedule_cron,
            "large_transaction_threshold_usd": self.large_transaction_threshold_usd,
        }


@dataclass
class GeneratedReport:
    """A generated report."""
    report_id: str
    report_type: ReportType
    
    # Period
    start_date: str
    end_date: str
    
    # Content
    data: Dict[str, Any] = field(default_factory=dict)
    summary: str = ""
    
    # Output
    format: ReportFormat = ReportFormat.JSON
    file_path: str = ""
    
    # Timing
    generated_at: float = field(default_factory=time.time)
    generation_time_ms: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "report_id": self.report_id,
            "report_type": self.report_type.value,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "summary": self.summary,
            "format": self.format.value,
            "file_path": self.file_path,
            "generated_at": self.generated_at,
            "generation_time_ms": self.generation_time_ms,
        }


class ReportGenerator:
    """
    Generates regulatory compliance reports.
    
    Features:
    - Multiple report types
    - Configurable thresholds
    - Multiple output formats
    - Scheduled generation
    """
    
    def __init__(self, output_dir: str = "data/reports"):
        self.logger = get_logger("compliance.reports")
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self._tx_log = get_transaction_log()
        self._audit_log = get_audit_logger()
        
        # Report configurations
        self._configs: Dict[ReportType, ReportConfig] = {}
        self._init_default_configs()
        
        # Generated reports
        self._reports: List[GeneratedReport] = []
    
    def _init_default_configs(self) -> None:
        """Initialize default report configurations."""
        self._configs[ReportType.DAILY_ACTIVITY] = ReportConfig(
            report_type=ReportType.DAILY_ACTIVITY,
            name="Daily Activity Report",
            description="Summary of all trading activity for the day",
            auto_generate=True,
            schedule_cron="0 0 * * *",
        )
        
        self._configs[ReportType.MONTHLY_SUMMARY] = ReportConfig(
            report_type=ReportType.MONTHLY_SUMMARY,
            name="Monthly Summary Report",
            description="Monthly trading and performance summary",
            auto_generate=True,
            schedule_cron="0 0 1 * *",
        )
        
        self._configs[ReportType.TAX_REPORT] = ReportConfig(
            report_type=ReportType.TAX_REPORT,
            name="Tax Report",
            description="Capital gains and losses for tax purposes",
            auto_generate=False,
        )
        
        self._configs[ReportType.LARGE_TRANSACTION] = ReportConfig(
            report_type=ReportType.LARGE_TRANSACTION,
            name="Large Transaction Report",
            description="Transactions exceeding reporting threshold",
            large_transaction_threshold_usd=10000.0,
        )
        
        self._configs[ReportType.SUSPICIOUS_ACTIVITY] = ReportConfig(
            report_type=ReportType.SUSPICIOUS_ACTIVITY,
            name="Suspicious Activity Report",
            description="Potentially suspicious trading patterns",
        )
    
    def generate_report(
        self,
        report_type: ReportType,
        start_date: str,
        end_date: str,
        format: ReportFormat = ReportFormat.JSON,
    ) -> GeneratedReport:
        """Generate a report."""
        import uuid
        
        start_time = time.time()
        report_id = f"report_{uuid.uuid4().hex[:12]}"
        
        # Parse dates
        start_dt = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc) + timedelta(days=1)
        
        # Generate report data based on type
        if report_type == ReportType.DAILY_ACTIVITY:
            data = self._generate_daily_activity(start_dt.timestamp(), end_dt.timestamp())
        elif report_type == ReportType.MONTHLY_SUMMARY:
            data = self._generate_monthly_summary(start_dt.timestamp(), end_dt.timestamp())
        elif report_type == ReportType.TAX_REPORT:
            data = self._generate_tax_report(start_dt.timestamp(), end_dt.timestamp())
        elif report_type == ReportType.LARGE_TRANSACTION:
            data = self._generate_large_transaction_report(start_dt.timestamp(), end_dt.timestamp())
        elif report_type == ReportType.SUSPICIOUS_ACTIVITY:
            data = self._generate_suspicious_activity_report(start_dt.timestamp(), end_dt.timestamp())
        else:
            data = {"error": "Report type not implemented"}
        
        # Create report
        report = GeneratedReport(
            report_id=report_id,
            report_type=report_type,
            start_date=start_date,
            end_date=end_date,
            data=data,
            summary=data.get("summary", ""),
            format=format,
            generation_time_ms=(time.time() - start_time) * 1000,
        )
        
        # Save report
        report.file_path = self._save_report(report)
        
        self._reports.append(report)
        self.logger.info(f"Generated report: {report_id} ({report_type.value})")
        
        return report
    
    def _generate_daily_activity(self, start_time: float, end_time: float) -> Dict[str, Any]:
        """Generate daily activity report."""
        txs = self._tx_log.query(start_time=start_time, end_time=end_time, limit=10000)
        
        total_trades = sum(1 for t in txs if t.tx_type == TransactionType.TRADE)
        total_volume = sum(abs(t.value_usd) for t in txs)
        total_fees = sum(t.fee for t in txs)
        
        by_asset: Dict[str, Dict[str, float]] = {}
        for tx in txs:
            if tx.asset not in by_asset:
                by_asset[tx.asset] = {"volume": 0, "trades": 0, "fees": 0}
            by_asset[tx.asset]["volume"] += abs(tx.value_usd)
            by_asset[tx.asset]["trades"] += 1
            by_asset[tx.asset]["fees"] += tx.fee
        
        by_venue: Dict[str, int] = {}
        for tx in txs:
            by_venue[tx.venue] = by_venue.get(tx.venue, 0) + 1
        
        return {
            "summary": f"Daily activity: {total_trades} trades, ${total_volume:,.2f} volume",
            "total_transactions": len(txs),
            "total_trades": total_trades,
            "total_volume_usd": total_volume,
            "total_fees_usd": total_fees,
            "by_asset": by_asset,
            "by_venue": by_venue,
            "transactions": [t.to_dict() for t in txs[:100]],
        }
    
    def _generate_monthly_summary(self, start_time: float, end_time: float) -> Dict[str, Any]:
        """Generate monthly summary report."""
        txs = self._tx_log.query(start_time=start_time, end_time=end_time, limit=100000)
        
        # Daily breakdown
        daily_volume: Dict[str, float] = {}
        for tx in txs:
            date = datetime.fromtimestamp(tx.timestamp, tz=timezone.utc).strftime("%Y-%m-%d")
            daily_volume[date] = daily_volume.get(date, 0) + abs(tx.value_usd)
        
        total_volume = sum(abs(t.value_usd) for t in txs)
        total_fees = sum(t.fee for t in txs)
        
        # P&L calculation (simplified)
        buys = sum(t.value_usd for t in txs if t.tx_type == TransactionType.TRADE and t.quantity > 0)
        sells = sum(t.value_usd for t in txs if t.tx_type == TransactionType.TRADE and t.quantity < 0)
        
        return {
            "summary": f"Monthly summary: ${total_volume:,.2f} volume, ${total_fees:,.2f} fees",
            "total_transactions": len(txs),
            "total_volume_usd": total_volume,
            "total_fees_usd": total_fees,
            "total_buys_usd": buys,
            "total_sells_usd": abs(sells),
            "daily_volume": daily_volume,
            "trading_days": len(daily_volume),
            "avg_daily_volume": total_volume / max(len(daily_volume), 1),
        }
    
    def _generate_tax_report(self, start_time: float, end_time: float) -> Dict[str, Any]:
        """Generate tax report with capital gains/losses."""
        txs = self._tx_log.query(
            tx_type=TransactionType.TRADE,
            start_time=start_time,
            end_time=end_time,
            limit=100000,
        )
        
        # Group by asset
        by_asset: Dict[str, List[Dict[str, Any]]] = {}
        for tx in txs:
            if tx.asset not in by_asset:
                by_asset[tx.asset] = []
            by_asset[tx.asset].append({
                "date": datetime.fromtimestamp(tx.timestamp, tz=timezone.utc).strftime("%Y-%m-%d"),
                "type": "buy" if tx.quantity > 0 else "sell",
                "quantity": abs(tx.quantity),
                "price": tx.price,
                "value_usd": abs(tx.value_usd),
                "fee": tx.fee,
            })
        
        # Calculate gains (simplified FIFO)
        total_gains = 0.0
        total_losses = 0.0
        
        return {
            "summary": f"Tax report: {len(txs)} trades",
            "total_trades": len(txs),
            "total_realized_gains": total_gains,
            "total_realized_losses": total_losses,
            "net_gain_loss": total_gains - total_losses,
            "by_asset": by_asset,
            "disclaimer": "This is a simplified report. Consult a tax professional.",
        }
    
    def _generate_large_transaction_report(self, start_time: float, end_time: float) -> Dict[str, Any]:
        """Generate large transaction report."""
        config = self._configs.get(ReportType.LARGE_TRANSACTION)
        threshold = config.large_transaction_threshold_usd if config else 10000.0
        
        txs = self._tx_log.query(start_time=start_time, end_time=end_time, limit=100000)
        large_txs = [t for t in txs if abs(t.value_usd) >= threshold]
        
        return {
            "summary": f"Large transactions: {len(large_txs)} above ${threshold:,.2f}",
            "threshold_usd": threshold,
            "total_large_transactions": len(large_txs),
            "total_value_usd": sum(abs(t.value_usd) for t in large_txs),
            "transactions": [t.to_dict() for t in large_txs],
        }
    
    def _generate_suspicious_activity_report(self, start_time: float, end_time: float) -> Dict[str, Any]:
        """Generate suspicious activity report."""
        txs = self._tx_log.query(start_time=start_time, end_time=end_time, limit=100000)
        
        suspicious = []
        
        # Check for patterns
        # 1. Rapid trading (many trades in short period)
        # 2. Round-trip trades
        # 3. Unusual volumes
        
        # Group by hour
        by_hour: Dict[str, List] = {}
        for tx in txs:
            hour = datetime.fromtimestamp(tx.timestamp, tz=timezone.utc).strftime("%Y-%m-%d %H:00")
            if hour not in by_hour:
                by_hour[hour] = []
            by_hour[hour].append(tx)
        
        # Flag hours with unusual activity
        for hour, hour_txs in by_hour.items():
            if len(hour_txs) > 50:  # More than 50 trades in an hour
                suspicious.append({
                    "type": "high_frequency",
                    "hour": hour,
                    "trade_count": len(hour_txs),
                    "reason": "Unusually high trading frequency",
                })
        
        return {
            "summary": f"Suspicious activity: {len(suspicious)} flags",
            "total_flags": len(suspicious),
            "flags": suspicious,
            "reviewed": False,
            "reviewer_notes": "",
        }
    
    def _save_report(self, report: GeneratedReport) -> str:
        """Save report to file."""
        date_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        
        if report.format == ReportFormat.JSON:
            file_path = self.output_dir / f"{report.report_type.value}_{date_str}.json"
            with open(file_path, "w") as f:
                json.dump({
                    "metadata": report.to_dict(),
                    "data": report.data,
                }, f, indent=2)
        
        elif report.format == ReportFormat.CSV:
            file_path = self.output_dir / f"{report.report_type.value}_{date_str}.csv"
            import csv
            with open(file_path, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["Key", "Value"])
                for key, value in report.data.items():
                    if not isinstance(value, (list, dict)):
                        writer.writerow([key, value])
        
        elif report.format == ReportFormat.HTML:
            file_path = self.output_dir / f"{report.report_type.value}_{date_str}.html"
            html = self._generate_html_report(report)
            with open(file_path, "w") as f:
                f.write(html)
        
        else:
            file_path = self.output_dir / f"{report.report_type.value}_{date_str}.json"
            with open(file_path, "w") as f:
                json.dump(report.data, f, indent=2)
        
        return str(file_path)
    
    def _generate_html_report(self, report: GeneratedReport) -> str:
        """Generate HTML report."""
        return f"""
<!DOCTYPE html>
<html>
<head>
    <title>{report.report_type.value} - {report.start_date} to {report.end_date}</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 40px; }}
        h1 {{ color: #333; }}
        .summary {{ background: #f5f5f5; padding: 20px; border-radius: 8px; }}
        table {{ border-collapse: collapse; width: 100%; margin-top: 20px; }}
        th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
        th {{ background: #4CAF50; color: white; }}
    </style>
</head>
<body>
    <h1>{report.report_type.value.replace('_', ' ').title()}</h1>
    <p>Period: {report.start_date} to {report.end_date}</p>
    <div class="summary">
        <h2>Summary</h2>
        <p>{report.summary}</p>
    </div>
    <h2>Details</h2>
    <pre>{json.dumps(report.data, indent=2)}</pre>
    <footer>
        <p>Generated: {datetime.fromtimestamp(report.generated_at, tz=timezone.utc).isoformat()}</p>
        <p>Report ID: {report.report_id}</p>
    </footer>
</body>
</html>
"""
    
    def get_report(self, report_id: str) -> Optional[GeneratedReport]:
        """Get a generated report."""
        for report in self._reports:
            if report.report_id == report_id:
                return report
        return None
    
    def list_reports(self, report_type: Optional[ReportType] = None) -> List[Dict[str, Any]]:
        """List generated reports."""
        reports = self._reports
        if report_type:
            reports = [r for r in reports if r.report_type == report_type]
        return [r.to_dict() for r in reports]
    
    def get_status(self) -> Dict[str, Any]:
        """Get report generator status."""
        return {
            "output_dir": str(self.output_dir),
            "configs": {k.value: v.to_dict() for k, v in self._configs.items()},
            "generated_reports": len(self._reports),
            "recent_reports": [r.to_dict() for r in self._reports[-10:]],
        }


# Singleton
_report_generator: Optional[ReportGenerator] = None
_report_generator_lock = threading.Lock()


def get_report_generator() -> ReportGenerator:
    """Get or create the Report Generator singleton."""
    global _report_generator
    if _report_generator is None:
        with _report_generator_lock:
            if _report_generator is None:
                _report_generator = ReportGenerator()
    return _report_generator
