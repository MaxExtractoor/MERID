"""
Proprietary data and feedback loops system for MERID's competitive moat.

Implements:
- High-resolution internal datasets (tick data, on-chain state, execution logs, swarm telemetry)
- Data warehouse with clean schemas and labels
- Closed feedback loops for continuous model/strategy refinement
- Data aggregation and enrichment
- Competitive advantage tracking
"""

from utils.logger import get_logger
import time
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from decimal import Decimal
import json

logger = get_logger(__name__)


class DataCategory(Enum):
    """Data category types."""
    TICK_DATA = "tick_data"  # High-resolution price/volume data
    ON_CHAIN_STATE = "on_chain_state"  # Blockchain state snapshots
    EXECUTION_LOGS = "execution_logs"  # Trade execution details
    SWARM_TELEMETRY = "swarm_telemetry"  # Agent behavior and decisions
    STRATEGY_PERFORMANCE = "strategy_performance"  # Strategy metrics
    MARKET_MICROSTRUCTURE = "market_microstructure"  # Order book dynamics
    MEV_PATTERNS = "mev_patterns"  # MEV opportunities and outcomes
    USER_BEHAVIOR = "user_behavior"  # Anonymized user patterns


class DataQuality(Enum):
    """Data quality levels."""
    RAW = "raw"  # Unprocessed
    CLEANED = "cleaned"  # Validated and cleaned
    ENRICHED = "enriched"  # Enhanced with derived features
    LABELED = "labeled"  # Labeled for ML training


class AggregationPeriod(Enum):
    """Data aggregation periods."""
    TICK = "tick"  # Every tick
    SECOND = "second"
    MINUTE = "minute"
    HOUR = "hour"
    DAY = "day"


@dataclass
class DataSchema:
    """Data schema definition."""
    schema_id: str
    category: DataCategory
    
    # Schema definition
    fields: Dict[str, str]  # field_name -> field_type
    required_fields: List[str] = field(default_factory=list)
    
    # Metadata
    version: str = "1.0.0"
    description: str = ""
    
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class DataRecord:
    """Individual data record."""
    record_id: str
    category: DataCategory
    
    # Data
    data: Dict[str, Any]
    
    # Quality
    quality: DataQuality = DataQuality.RAW
    
    # Provenance
    source: str = ""
    collection_timestamp: datetime = field(default_factory=datetime.utcnow)
    
    # Enrichment
    enrichments: Dict[str, Any] = field(default_factory=dict)
    labels: Dict[str, Any] = field(default_factory=dict)
    
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class DataAggregation:
    """Aggregated data."""
    aggregation_id: str
    category: DataCategory
    period: AggregationPeriod
    
    # Time range
    start_time: datetime
    end_time: datetime
    
    # Aggregated metrics
    metrics: Dict[str, Any]
    
    # Statistics
    record_count: int = 0
    
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class FeedbackLoop:
    """Closed feedback loop."""
    loop_id: str
    
    # Source
    source_type: str  # strategy, experiment, ui_change, agent_decision
    source_id: str
    
    # Feedback data
    feedback_data: Dict[str, Any]
    
    # Impact
    impact_category: str  # model_refinement, prompt_tuning, parameter_adjustment
    impact_description: str = ""
    
    # Application
    applied: bool = False
    applied_at: Optional[datetime] = None
    
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class CompetitiveAdvantage:
    """Competitive advantage metric."""
    advantage_id: str
    
    # Advantage type
    advantage_type: str  # data_volume, data_quality, execution_speed, model_accuracy
    
    # Metrics
    our_metric: float
    industry_benchmark: float
    advantage_ratio: float  # our_metric / industry_benchmark
    
    # Description
    description: str = ""
    
    # Tracking
    measured_at: datetime = field(default_factory=datetime.utcnow)


class ProprietaryDataWarehouse:
    """
    Proprietary data warehouse for MERID's competitive moat.
    
    Features:
    - High-resolution internal datasets
    - Clean schemas and labels
    - Data aggregation and enrichment
    - Closed feedback loops
    - Competitive advantage tracking
    """
    
    def __init__(self):
        self._schemas: Dict[str, DataSchema] = {}
        self._records: List[DataRecord] = []
        self._aggregations: Dict[str, DataAggregation] = {}
        self._feedback_loops: List[FeedbackLoop] = []
        self._competitive_advantages: List[CompetitiveAdvantage] = []
        
        # Indexes
        self._category_index: Dict[DataCategory, List[str]] = {}
        
        self._initialize_schemas()
    
    def _initialize_schemas(self) -> None:
        """Initialize data schemas."""
        
        # Tick data schema
        self.register_schema(
            category=DataCategory.TICK_DATA,
            fields={
                "timestamp": "datetime",
                "exchange": "string",
                "pair": "string",
                "price": "decimal",
                "volume": "decimal",
                "bid": "decimal",
                "ask": "decimal",
                "spread_bps": "decimal",
            },
            required_fields=["timestamp", "exchange", "pair", "price", "volume"],
            description="High-resolution tick-level price and volume data",
        )
        
        # On-chain state schema
        self.register_schema(
            category=DataCategory.ON_CHAIN_STATE,
            fields={
                "timestamp": "datetime",
                "chain": "string",
                "block_number": "integer",
                "contract_address": "string",
                "state_key": "string",
                "state_value": "string",
                "gas_price": "decimal",
            },
            required_fields=["timestamp", "chain", "block_number", "contract_address"],
            description="Blockchain state snapshots",
        )
        
        # Execution logs schema
        self.register_schema(
            category=DataCategory.EXECUTION_LOGS,
            fields={
                "timestamp": "datetime",
                "order_id": "string",
                "strategy_id": "string",
                "exchange": "string",
                "pair": "string",
                "side": "string",
                "size": "decimal",
                "price": "decimal",
                "execution_time_ms": "decimal",
                "slippage_bps": "decimal",
                "success": "boolean",
            },
            required_fields=["timestamp", "order_id", "strategy_id", "exchange"],
            description="Trade execution details and performance",
        )
        
        # Swarm telemetry schema
        self.register_schema(
            category=DataCategory.SWARM_TELEMETRY,
            fields={
                "timestamp": "datetime",
                "agent_id": "string",
                "agent_role": "string",
                "decision_type": "string",
                "decision_data": "json",
                "confidence": "decimal",
                "execution_time_ms": "decimal",
                "outcome": "string",
            },
            required_fields=["timestamp", "agent_id", "agent_role", "decision_type"],
            description="Agent behavior and decision telemetry",
        )
        
        # Strategy performance schema
        self.register_schema(
            category=DataCategory.STRATEGY_PERFORMANCE,
            fields={
                "timestamp": "datetime",
                "strategy_id": "string",
                "pnl": "decimal",
                "sharpe_ratio": "decimal",
                "max_drawdown": "decimal",
                "win_rate": "decimal",
                "avg_trade_duration_seconds": "decimal",
                "total_trades": "integer",
            },
            required_fields=["timestamp", "strategy_id", "pnl"],
            description="Strategy performance metrics",
        )
        
        # Market microstructure schema
        self.register_schema(
            category=DataCategory.MARKET_MICROSTRUCTURE,
            fields={
                "timestamp": "datetime",
                "exchange": "string",
                "pair": "string",
                "order_book_depth": "integer",
                "bid_ask_spread_bps": "decimal",
                "order_flow_imbalance": "decimal",
                "trade_intensity": "decimal",
            },
            required_fields=["timestamp", "exchange", "pair"],
            description="Order book dynamics and microstructure",
        )
        
        # MEV patterns schema
        self.register_schema(
            category=DataCategory.MEV_PATTERNS,
            fields={
                "timestamp": "datetime",
                "chain": "string",
                "mev_type": "string",
                "opportunity_value": "decimal",
                "captured": "boolean",
                "competition_level": "decimal",
                "gas_cost": "decimal",
            },
            required_fields=["timestamp", "chain", "mev_type"],
            description="MEV opportunities and outcomes",
        )
        
        logger.info(f"Initialized {len(self._schemas)} data schemas")
    
    def register_schema(
        self,
        category: DataCategory,
        fields: Dict[str, str],
        required_fields: List[str],
        description: str,
        version: str = "1.0.0",
    ) -> DataSchema:
        """Register data schema."""
        schema_id = f"schema_{category.value}"
        
        schema = DataSchema(
            schema_id=schema_id,
            category=category,
            fields=fields,
            required_fields=required_fields,
            version=version,
            description=description,
        )
        
        self._schemas[schema_id] = schema
        
        logger.info(f"Registered schema '{schema_id}': {category.value}")
        
        return schema
    
    def ingest_data(
        self,
        category: DataCategory,
        data: Dict[str, Any],
        source: str,
        quality: DataQuality = DataQuality.RAW,
    ) -> DataRecord:
        """Ingest data record."""
        record_id = f"rec_{category.value}_{int(time.time() * 1000)}"
        
        # Validate against schema
        schema_id = f"schema_{category.value}"
        schema = self._schemas.get(schema_id)
        
        if schema:
            # Check required fields
            missing_fields = [
                field for field in schema.required_fields
                if field not in data
            ]
            if missing_fields:
                logger.warning(
                    f"Missing required fields for {category.value}: {missing_fields}"
                )
        
        record = DataRecord(
            record_id=record_id,
            category=category,
            data=data,
            quality=quality,
            source=source,
        )
        
        self._records.append(record)
        
        # Update index
        if category not in self._category_index:
            self._category_index[category] = []
        self._category_index[category].append(record_id)
        
        logger.debug(f"Ingested {category.value} record from {source}")
        
        return record
    
    def enrich_data(
        self,
        record_id: str,
        enrichments: Dict[str, Any],
    ) -> None:
        """Enrich data record with derived features."""
        record = self._get_record(record_id)
        
        if not record:
            logger.warning(f"Record '{record_id}' not found for enrichment")
            return
        
        record.enrichments.update(enrichments)
        record.quality = DataQuality.ENRICHED
        
        logger.debug(f"Enriched record '{record_id}' with {len(enrichments)} features")
    
    def label_data(
        self,
        record_id: str,
        labels: Dict[str, Any],
    ) -> None:
        """Label data record for ML training."""
        record = self._get_record(record_id)
        
        if not record:
            logger.warning(f"Record '{record_id}' not found for labeling")
            return
        
        record.labels.update(labels)
        record.quality = DataQuality.LABELED
        
        logger.debug(f"Labeled record '{record_id}' with {len(labels)} labels")
    
    def _get_record(self, record_id: str) -> Optional[DataRecord]:
        """Get record by ID."""
        for record in self._records:
            if record.record_id == record_id:
                return record
        return None
    
    def aggregate_data(
        self,
        category: DataCategory,
        period: AggregationPeriod,
        start_time: datetime,
        end_time: datetime,
        metrics: List[str],
    ) -> DataAggregation:
        """Aggregate data over time period."""
        aggregation_id = f"agg_{category.value}_{period.value}_{int(time.time())}"
        
        # Get records in time range
        records = [
            record for record in self._records
            if record.category == category
            and start_time <= record.collection_timestamp <= end_time
        ]
        
        # Compute aggregated metrics
        aggregated_metrics = {}
        
        for metric in metrics:
            values = [
                record.data.get(metric)
                for record in records
                if metric in record.data
            ]
            
            if values:
                # Compute statistics
                aggregated_metrics[metric] = {
                    "count": len(values),
                    "min": min(values) if values else None,
                    "max": max(values) if values else None,
                    "mean": sum(values) / len(values) if values else None,
                }
        
        aggregation = DataAggregation(
            aggregation_id=aggregation_id,
            category=category,
            period=period,
            start_time=start_time,
            end_time=end_time,
            metrics=aggregated_metrics,
            record_count=len(records),
        )
        
        self._aggregations[aggregation_id] = aggregation
        
        logger.info(
            f"Aggregated {len(records)} {category.value} records "
            f"over {period.value} period"
        )
        
        return aggregation
    
    def create_feedback_loop(
        self,
        source_type: str,
        source_id: str,
        feedback_data: Dict[str, Any],
        impact_category: str,
        impact_description: str,
    ) -> FeedbackLoop:
        """Create closed feedback loop."""
        loop_id = f"loop_{int(time.time() * 1000)}"
        
        loop = FeedbackLoop(
            loop_id=loop_id,
            source_type=source_type,
            source_id=source_id,
            feedback_data=feedback_data,
            impact_category=impact_category,
            impact_description=impact_description,
        )
        
        self._feedback_loops.append(loop)
        
        logger.info(
            f"Created feedback loop '{loop_id}': {source_type} -> {impact_category}"
        )
        
        return loop
    
    def apply_feedback_loop(self, loop_id: str) -> None:
        """Apply feedback loop to refine models/strategies."""
        loop = self._get_feedback_loop(loop_id)
        
        if not loop:
            logger.warning(f"Feedback loop '{loop_id}' not found")
            return
        
        # Mark as applied
        loop.applied = True
        loop.applied_at = datetime.utcnow()
        
        logger.info(
            f"Applied feedback loop '{loop_id}': {loop.impact_category}"
        )
    
    def _get_feedback_loop(self, loop_id: str) -> Optional[FeedbackLoop]:
        """Get feedback loop by ID."""
        for loop in self._feedback_loops:
            if loop.loop_id == loop_id:
                return loop
        return None
    
    def track_competitive_advantage(
        self,
        advantage_type: str,
        our_metric: float,
        industry_benchmark: float,
        description: str,
    ) -> CompetitiveAdvantage:
        """Track competitive advantage metric."""
        advantage_id = f"adv_{advantage_type}_{int(time.time())}"
        
        advantage_ratio = our_metric / industry_benchmark if industry_benchmark > 0 else 0.0
        
        advantage = CompetitiveAdvantage(
            advantage_id=advantage_id,
            advantage_type=advantage_type,
            our_metric=our_metric,
            industry_benchmark=industry_benchmark,
            advantage_ratio=advantage_ratio,
            description=description,
        )
        
        self._competitive_advantages.append(advantage)
        
        logger.info(
            f"Tracked competitive advantage '{advantage_type}': "
            f"{advantage_ratio:.2f}x industry benchmark"
        )
        
        return advantage
    
    def get_data_stats(self) -> Dict[str, Any]:
        """Get data warehouse statistics."""
        total_records = len(self._records)
        
        records_by_category = {
            category.value: len(self._category_index.get(category, []))
            for category in DataCategory
        }
        
        records_by_quality = {
            quality.value: sum(
                1 for record in self._records
                if record.quality == quality
            )
            for quality in DataQuality
        }
        
        labeled_records = sum(
            1 for record in self._records
            if record.quality == DataQuality.LABELED
        )
        
        feedback_loops_applied = sum(
            1 for loop in self._feedback_loops
            if loop.applied
        )
        
        avg_advantage_ratio = (
            sum(adv.advantage_ratio for adv in self._competitive_advantages) /
            len(self._competitive_advantages)
            if self._competitive_advantages else 0.0
        )
        
        return {
            "records": {
                "total": total_records,
                "by_category": records_by_category,
                "by_quality": records_by_quality,
                "labeled_percentage": (
                    labeled_records / total_records * 100
                    if total_records > 0 else 0.0
                ),
            },
            "aggregations": {
                "total": len(self._aggregations),
            },
            "feedback_loops": {
                "total": len(self._feedback_loops),
                "applied": feedback_loops_applied,
                "application_rate": (
                    feedback_loops_applied / len(self._feedback_loops) * 100
                    if self._feedback_loops else 0.0
                ),
            },
            "competitive_advantages": {
                "total": len(self._competitive_advantages),
                "avg_advantage_ratio": avg_advantage_ratio,
            },
        }


_proprietary_data_warehouse: Optional[ProprietaryDataWarehouse] = None


def get_proprietary_data_warehouse() -> ProprietaryDataWarehouse:
    """Get global ProprietaryDataWarehouse instance."""
    global _proprietary_data_warehouse
    if _proprietary_data_warehouse is None:
        _proprietary_data_warehouse = ProprietaryDataWarehouse()
    return _proprietary_data_warehouse
