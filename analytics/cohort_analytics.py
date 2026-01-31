"""
MERID Cohort Analytics Framework
Implements D7/D30 retention and behavior analytics under hardened governance conditions.

Date: 2026-01-26
Status: IMPLEMENTED
"""

import logging
import json
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, asdict
from enum import Enum
from pathlib import Path
import sqlite3
import uuid

# Configure UTF-8 logging first - robust approach using io.TextIOWrapper
import sys
import io
logger = logging.getLogger()
logger.setLevel(logging.INFO)
logger.handlers.clear()

# Wrap stdout in a UTF-8 TextIOWrapper (most robust approach)
utf8_stdout = io.TextIOWrapper(
    sys.stdout.buffer, 
    encoding="utf-8", 
    errors="replace"
)
console_handler = logging.StreamHandler(utf8_stdout)
console_handler.setLevel(logging.INFO)
formatter = logging.Formatter(
    "%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

# Add file handler with UTF-8 encoding
file_handler = logging.FileHandler(
    "analytics/cohort_analytics.log", mode="a", encoding="utf-8"
)
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)


class CohortStatus(Enum):
    """User cohort status."""
    NEW = "new"
    ACTIVE = "active"
    CHURNED = "churned"
    DORMANT = "dormant"
    POWER_USER = "power_user"


class EventType(Enum):
    """Event types for tracking."""
    USER_SIGNUP = "user_signup"
    USER_LOGIN = "user_login"
    TRADE_EXECUTED = "trade_executed"
    DASHBOARD_VIEW = "dashboard_view"
    API_CALL = "api_call"
    ALERT_TRIGGERED = "alert_triggered"
    RUNBOOK_ACCESSED = "runbook_accessed"
    INCIDENT_RESPONSE = "incident_response"


@dataclass
class UserEvent:
    """User event for analytics."""
    event_id: str
    user_id: str
    event_type: EventType
    timestamp: datetime
    metadata: Dict[str, Any]
    session_id: Optional[str] = None


@dataclass
class CohortMetrics:
    """Cohort metrics for a time period."""
    cohort_date: datetime
    period_days: int
    total_users: int
    active_users: int
    retained_users: int
    retention_rate: float
    avg_session_duration: float
    avg_trades_per_user: float
    total_trades: int
    total_api_calls: int
    governance_compliance: float


@dataclass
class UserBehavior:
    """User behavior analytics."""
    user_id: str
    signup_date: datetime
    last_active: datetime
    total_sessions: int
    total_trades: int
    total_api_calls: int
    avg_session_duration: float
    preferred_features: List[str]
    risk_profile: str
    compliance_score: float


class CohortAnalytics:
    """Cohort analytics for MERID under hardened governance."""
    
    def __init__(self, db_path: str = "analytics/cohort_data.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self._init_database()
        
        logger.info("📊 Cohort Analytics initialized")
    
    def _init_database(self):
        """Initialize database schema."""
        cursor = self.conn.cursor()
        
        # User events table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_events (
                event_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                timestamp DATETIME NOT NULL,
                metadata TEXT,
                session_id TEXT,
                INDEX(user_id, timestamp),
                INDEX(event_type, timestamp)
            )
        """)
        
        # Users table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                signup_date DATETIME NOT NULL,
                last_active DATETIME,
                cohort_date DATETIME,
                status TEXT,
                metadata TEXT
            )
        """)
        
        # Cohort metrics table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS cohort_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cohort_date DATETIME NOT NULL,
                period_days INTEGER NOT NULL,
                total_users INTEGER,
                active_users INTEGER,
                retained_users INTEGER,
                retention_rate REAL,
                avg_session_duration REAL,
                avg_trades_per_user REAL,
                total_trades INTEGER,
                total_api_calls INTEGER,
                governance_compliance REAL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Governance compliance table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS governance_compliance (
                user_id TEXT,
                date DATE,
                technical_gate_pass BOOLEAN,
                operational_gate_pass BOOLEAN,
                threeam_drill_pass BOOLEAN,
                compliance_score REAL,
                PRIMARY KEY (user_id, date)
            )
        """)
        
        self.conn.commit()
        logger.info("🗄️ Database schema initialized")
    
    async def track_event(self, event: UserEvent) -> bool:
        """Track a user event."""
        try:
            cursor = self.conn.cursor()
            
            # Insert event
            cursor.execute("""
                INSERT INTO user_events 
                (event_id, user_id, event_type, timestamp, metadata, session_id)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                event.event_id,
                event.user_id,
                event.event_type.value,
                event.timestamp,
                json.dumps(event.metadata),
                event.session_id
            ))
            
            # Update user record
            cursor.execute("""
                INSERT OR REPLACE INTO users 
                (user_id, signup_date, last_active, cohort_date, status, metadata)
                VALUES (?, 
                    COALESCE((SELECT signup_date FROM users WHERE user_id = ?), ?),
                    ?, 
                    COALESCE((SELECT cohort_date FROM users WHERE user_id = ?), ?),
                    ?,
                    COALESCE((SELECT metadata FROM users WHERE user_id = ?), '{}')
                )
            """, (
                event.user_id, event.user_id, event.timestamp,
                event.timestamp, event.user_id, event.timestamp.date(),
                CohortStatus.ACTIVE.value, event.user_id
            ))
            
            self.conn.commit()
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to track event: {e}")
            return False
    
    async def track_governance_compliance(self, user_id: str, compliance_data: Dict[str, Any]) -> bool:
        """Track governance compliance for a user."""
        try:
            cursor = self.conn.cursor()
            
            # Calculate compliance score
            technical_pass = compliance_data.get("technical_gate_pass", False)
            operational_pass = compliance_data.get("operational_gate_pass", False)
            drill_pass = compliance_data.get("threeam_drill_pass", False)
            
            compliance_score = 0.0
            if technical_pass:
                compliance_score += 0.4
            if operational_pass:
                compliance_score += 0.4
            if drill_pass:
                compliance_score += 0.2
            
            cursor.execute("""
                INSERT OR REPLACE INTO governance_compliance
                (user_id, date, technical_gate_pass, operational_gate_pass, threeam_drill_pass, compliance_score)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                user_id,
                datetime.now().date(),
                technical_pass,
                operational_pass,
                drill_pass,
                compliance_score
            ))
            
            self.conn.commit()
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to track governance compliance: {e}")
            return False
    
    def calculate_cohort_metrics(self, cohort_date: datetime, period_days: int) -> CohortMetrics:
        """Calculate metrics for a specific cohort and period."""
        cursor = self.conn.cursor()
        
        # Get cohort users
        cursor.execute("""
            SELECT user_id FROM users 
            WHERE cohort_date = ?
        """, (cohort_date.date(),))
        
        cohort_users = [row[0] for row in cursor.fetchall()]
        total_users = len(cohort_users)
        
        if total_users == 0:
            return CohortMetrics(
                cohort_date=cohort_date,
                period_days=period_days,
                total_users=0,
                active_users=0,
                retained_users=0,
                retention_rate=0.0,
                avg_session_duration=0.0,
                avg_trades_per_user=0.0,
                total_trades=0,
                total_api_calls=0,
                governance_compliance=0.0
            )
        
        # Calculate retention (users active in period)
        period_start = cohort_date + timedelta(days=period_days)
        period_end = period_start + timedelta(days=1)
        
        cursor.execute("""
            SELECT DISTINCT user_id FROM user_events
            WHERE user_id IN ({}) AND timestamp >= ? AND timestamp < ?
        """.format(','.join(['?'] * len(cohort_users))), cohort_users + [period_start, period_end])
        
        active_users = len(cursor.fetchall())
        retained_users = active_users
        retention_rate = retained_users / total_users if total_users > 0 else 0.0
        
        # Calculate average session duration
        cursor.execute("""
            SELECT AVG(CAST(JSON_EXTRACT(metadata, '$.duration') AS REAL)) as avg_duration
            FROM user_events
            WHERE user_id IN ({}) AND event_type = 'user_login'
            AND timestamp >= ? AND timestamp < ?
        """.format(','.join(['?'] * len(cohort_users))), cohort_users + [cohort_date, period_start])
        
        result = cursor.fetchone()
        avg_session_duration = result[0] if result and result[0] else 0.0
        
        # Calculate trades
        cursor.execute("""
            SELECT COUNT(*) FROM user_events
            WHERE user_id IN ({}) AND event_type = 'trade_executed'
            AND timestamp >= ? AND timestamp < ?
        """.format(','.join(['?'] * len(cohort_users))), cohort_users + [cohort_date, period_start])
        
        total_trades = cursor.fetchone()[0]
        avg_trades_per_user = total_trades / total_users if total_users > 0 else 0.0
        
        # Calculate API calls
        cursor.execute("""
            SELECT COUNT(*) FROM user_events
            WHERE user_id IN ({}) AND event_type = 'api_call'
            AND timestamp >= ? AND timestamp < ?
        """.format(','.join(['?'] * len(cohort_users))), cohort_users + [cohort_date, period_start])
        
        total_api_calls = cursor.fetchone()[0]
        
        # Calculate governance compliance
        cursor.execute("""
            SELECT AVG(compliance_score) FROM governance_compliance
            WHERE user_id IN ({}) AND date >= ? AND date <= ?
        """.format(','.join(['?'] * len(cohort_users))), cohort_users + [cohort_date.date(), period_start.date()])
        
        result = cursor.fetchone()
        governance_compliance = result[0] if result and result[0] else 0.0
        
        return CohortMetrics(
            cohort_date=cohort_date,
            period_days=period_days,
            total_users=total_users,
            active_users=active_users,
            retained_users=retained_users,
            retention_rate=retention_rate,
            avg_session_duration=avg_session_duration,
            avg_trades_per_user=avg_trades_per_user,
            total_trades=total_trades,
            total_api_calls=total_api_calls,
            governance_compliance=governance_compliance
        )
    
    def get_user_behavior(self, user_id: str) -> Optional[UserBehavior]:
        """Get detailed behavior analytics for a user."""
        cursor = self.conn.cursor()
        
        # Get user info
        cursor.execute("""
            SELECT signup_date, last_active, cohort_date, status, metadata
            FROM users WHERE user_id = ?
        """, (user_id,))
        
        user_info = cursor.fetchone()
        if not user_info:
            return None
        
        signup_date, last_active, cohort_date, status, metadata = user_info
        
        # Calculate metrics
        cursor.execute("""
            SELECT COUNT(*) FROM user_events WHERE user_id = ? AND event_type = 'user_login'
        """, (user_id,))
        total_sessions = cursor.fetchone()[0]
        
        cursor.execute("""
            SELECT COUNT(*) FROM user_events WHERE user_id = ? AND event_type = 'trade_executed'
        """, (user_id,))
        total_trades = cursor.fetchone()[0]
        
        cursor.execute("""
            SELECT COUNT(*) FROM user_events WHERE user_id = ? AND event_type = 'api_call'
        """, (user_id,))
        total_api_calls = cursor.fetchone()[0]
        
        cursor.execute("""
            SELECT AVG(CAST(JSON_EXTRACT(metadata, '$.duration') AS REAL))
            FROM user_events WHERE user_id = ? AND event_type = 'user_login'
        """, (user_id,))
        
        result = cursor.fetchone()
        avg_session_duration = result[0] if result and result[0] else 0.0
        
        # Get preferred features
        cursor.execute("""
            SELECT DISTINCT JSON_EXTRACT(metadata, '$.feature') as feature
            FROM user_events WHERE user_id = ? AND event_type = 'dashboard_view'
        """, (user_id,))
        
        preferred_features = [row[0] for row in cursor.fetchall() if row[0]]
        
        # Get compliance score
        cursor.execute("""
            SELECT AVG(compliance_score) FROM governance_compliance WHERE user_id = ?
        """, (user_id,))
        
        result = cursor.fetchone()
        compliance_score = result[0] if result and result[0] else 0.0
        
        # Determine risk profile based on behavior
        if total_trades > 100:
            risk_profile = "high"
        elif total_trades > 10:
            risk_profile = "medium"
        else:
            risk_profile = "low"
        
        return UserBehavior(
            user_id=user_id,
            signup_date=signup_date,
            last_active=last_active,
            total_sessions=total_sessions,
            total_trades=total_trades,
            total_api_calls=total_api_calls,
            avg_session_duration=avg_session_duration,
            preferred_features=preferred_features,
            risk_profile=risk_profile,
            compliance_score=compliance_score
        )
    
    def generate_d7_report(self, cohort_date: datetime) -> Dict[str, Any]:
        """Generate D7 cohort report."""
        metrics = self.calculate_cohort_metrics(cohort_date, 7)
        
        return {
            "report_type": "D7",
            "cohort_date": cohort_date.isoformat(),
            "period_days": 7,
            "metrics": asdict(metrics),
            "insights": self._generate_insights(metrics, "D7"),
            "recommendations": self._generate_recommendations(metrics, "D7")
        }
    
    def generate_d30_report(self, cohort_date: datetime) -> Dict[str, Any]:
        """Generate D30 cohort report."""
        metrics = self.calculate_cohort_metrics(cohort_date, 30)
        
        return {
            "report_type": "D30",
            "cohort_date": cohort_date.isoformat(),
            "period_days": 30,
            "metrics": asdict(metrics),
            "insights": self._generate_insights(metrics, "D30"),
            "recommendations": self._generate_recommendations(metrics, "D30")
        }
    
    def _generate_insights(self, metrics: CohortMetrics, period: str) -> List[str]:
        """Generate insights from cohort metrics."""
        insights = []
        
        if metrics.retention_rate > 0.8:
            insights.append(f"Excellent {period} retention ({metrics.retention_rate:.1%})")
        elif metrics.retention_rate > 0.6:
            insights.append(f"Good {period} retention ({metrics.retention_rate:.1%})")
        elif metrics.retention_rate > 0.4:
            insights.append(f"Moderate {period} retention ({metrics.retention_rate:.1%})")
        else:
            insights.append(f"Low {period} retention ({metrics.retention_rate:.1%}) - requires attention")
        
        if metrics.avg_trades_per_user > 10:
            insights.append(f"High trading activity ({metrics.avg_trades_per_user:.1f} trades/user)")
        elif metrics.avg_trades_per_user > 1:
            insights.append(f"Moderate trading activity ({metrics.avg_trades_per_user:.1f} trades/user)")
        else:
            insights.append(f"Low trading activity ({metrics.avg_trades_per_user:.1f} trades/user)")
        
        if metrics.governance_compliance > 0.9:
            insights.append(f"Excellent governance compliance ({metrics.governance_compliance:.1%})")
        elif metrics.governance_compliance > 0.7:
            insights.append(f"Good governance compliance ({metrics.governance_compliance:.1%})")
        else:
            insights.append(f"Poor governance compliance ({metrics.governance_compliance:.1%}) - needs improvement")
        
        return insights
    
    def _generate_recommendations(self, metrics: CohortMetrics, period: str) -> List[str]:
        """Generate recommendations from cohort metrics."""
        recommendations = []
        
        if metrics.retention_rate < 0.5:
            recommendations.append("Implement user onboarding improvements")
            recommendations.append("Add user engagement features")
        
        if metrics.avg_trades_per_user < 1:
            recommendations.append("Improve trading interface and education")
            recommendations.append("Add trading incentives or tutorials")
        
        if metrics.governance_compliance < 0.8:
            recommendations.append("Strengthen governance education and training")
            recommendations.append("Improve compliance monitoring and alerts")
        
        if metrics.avg_session_duration < 60:  # seconds
            recommendations.append("Enhance user experience to increase session duration")
        
        return recommendations
    
    def save_cohort_metrics(self, metrics: CohortMetrics):
        """Save cohort metrics to database."""
        cursor = self.conn.cursor()
        
        cursor.execute("""
            INSERT INTO cohort_metrics
            (cohort_date, period_days, total_users, active_users, retained_users, 
             retention_rate, avg_session_duration, avg_trades_per_user, total_trades, 
             total_api_calls, governance_compliance)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            metrics.cohort_date,
            metrics.period_days,
            metrics.total_users,
            metrics.active_users,
            metrics.retained_users,
            metrics.retention_rate,
            metrics.avg_session_duration,
            metrics.avg_trades_per_user,
            metrics.total_trades,
            metrics.total_api_calls,
            metrics.governance_compliance
        ))
        
        self.conn.commit()
    
    def get_retention_curve(self, cohort_date: datetime, max_days: int = 30) -> List[Tuple[int, float]]:
        """Get retention curve for a cohort."""
        retention_data = []
        
        for day in range(1, max_days + 1):
            metrics = self.calculate_cohort_metrics(cohort_date, day)
            retention_data.append((day, metrics.retention_rate))
        
        return retention_data
    
    def close(self):
        """Close database connection."""
        self.conn.close()
        logger.info("📊 Cohort Analytics closed")


async def main():
    """Main analytics execution."""
    analytics = CohortAnalytics()
    
    try:
        # Example usage
        # Track some sample events
        await analytics.track_event(UserEvent(
            event_id=str(uuid.uuid4()),
            user_id="user_123",
            event_type=EventType.USER_SIGNUP,
            timestamp=datetime.now(),
            metadata={"source": "web", "plan": "basic"}
        ))
        
        # Generate D7 report for today's cohort
        today = datetime.now()
        d7_report = analytics.generate_d7_report(today)
        print(f"D7 Report: {json.dumps(d7_report, indent=2)}")
        
    finally:
        analytics.close()


if __name__ == "__main__":
    asyncio.run(main())
