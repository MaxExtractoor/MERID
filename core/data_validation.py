"""Data validation for MERID incoming streams using Great Expectations."""

from typing import Dict, Any, List, Optional
import pandas as pd
import great_expectations as gx
from great_expectations.core import ExpectationSuite
from great_expectations.expectations import (
    ExpectColumnValuesToNotBeNull,
    ExpectColumnValuesToBeBetween,
    ExpectColumnValuesToMatchRegex,
    ExpectTableRowCountToBeBetween
)
import structlog

logger = structlog.get_logger(__name__)


class MarketDataValidator:
    """Validator for incoming market data streams."""
    
    def __init__(self):
        self.context = gx.get_context()
        self.logger = logger.bind(component="MarketDataValidator")
    
    def validate_tick_data(self, data: pd.DataFrame) -> Dict[str, Any]:
        """Validate tick data for expected schema and ranges."""
        
        # Create expectation suite for tick data
        suite = ExpectationSuite(name="tick_data_validation")
        
        # Required columns
        required_columns = ["symbol", "price", "timestamp", "volume"]
        for col in required_columns:
            suite.add_expectation(
                ExpectColumnValuesToNotBeNull(column=col)
            )
        
        # Price should be positive
        suite.add_expectation(
            ExpectColumnValuesToBeBetween(column="price", min_value=0, max_value=1e6)
        )
        
        # Volume should be non-negative
        suite.add_expectation(
            ExpectColumnValuesToBeBetween(column="volume", min_value=0, max_value=1e12)
        )
        
        # Symbol should match ticker pattern
        suite.add_expectation(
            ExpectColumnValuesToMatchRegex(
                column="symbol",
                regex=r"^[A-Z]{1,5}(-[A-Z]+)?$"
            )
        )
        
        # Validate data
        batch = self.context.data_sources.add_pandas("ticks").add_dataframe_asset(name="tick_data")
        batch_definition = batch.add_batch_definition_whole_dataframe("batch_def")
        batch_parameters = {"dataframe": data}
        
        validation_result = batch_definition.validate(
            suite,
            batch_parameters=batch_parameters
        )
        
        self.logger.info(
            "tick_validation_complete",
            success=validation_result.success,
            records=len(data)
        )
        
        return {
            "success": validation_result.success,
            "statistics": validation_result.statistics,
            "results": validation_result.results
        }
    
    def validate_order_data(self, data: pd.DataFrame) -> Dict[str, Any]:
        """Validate order data."""
        
        suite = ExpectationSuite(name="order_data_validation")
        
        # Required fields
        suite.add_expectation(ExpectColumnValuesToNotBeNull(column="order_id"))
        suite.add_expectation(ExpectColumnValuesToNotBeNull(column="symbol"))
        suite.add_expectation(ExpectColumnValuesToNotBeNull(column="side"))
        
        # Side should be BUY or SELL
        suite.add_expectation(
            ExpectColumnValuesToMatchRegex(
                column="side",
                regex=r"^(buy|sell|BUY|SELL)$"
            )
        )
        
        # Quantity should be positive
        suite.add_expectation(
            ExpectColumnValuesToBeBetween(column="quantity", min_value=1e-8, max_value=1e12)
        )
        
        batch = self.context.data_sources.add_pandas("orders").add_dataframe_asset(name="order_data")
        batch_definition = batch.add_batch_definition_whole_dataframe("batch_def")
        batch_parameters = {"dataframe": data}
        
        validation_result = batch_definition.validate(suite, batch_parameters=batch_parameters)
        
        self.logger.info(
            "order_validation_complete",
            success=validation_result.success,
            records=len(data)
        )
        
        return {
            "success": validation_result.success,
            "statistics": validation_result.statistics
        }


class SchemaValidator:
    """JSON schema validator for API payloads."""
    
    def __init__(self):
        self.logger = logger.bind(component="SchemaValidator")
        self.schemas = self._load_schemas()
    
    def _load_schemas(self) -> Dict[str, Any]:
        """Load predefined schemas."""
        return {
            "trade_signal": {
                "type": "object",
                "required": ["symbol", "side", "quantity"],
                "properties": {
                    "symbol": {"type": "string", "pattern": "^[A-Z]{1,5}(-[A-Z]+)?$"},
                    "side": {"type": "string", "enum": ["buy", "sell", "BUY", "SELL"]},
                    "quantity": {"type": "number", "minimum": 0},
                    "price": {"type": "number", "minimum": 0},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1}
                }
            },
            "order_request": {
                "type": "object",
                "required": ["symbol", "side", "quantity"],
                "properties": {
                    "symbol": {"type": "string"},
                    "side": {"type": "string", "enum": ["buy", "sell"]},
                    "quantity": {"type": "number", "exclusiveMinimum": 0},
                    "order_type": {"type": "string", "enum": ["market", "limit", "stop"]},
                    "price": {"type": "number"}
                }
            }
        }
    
    def validate(self, data: Dict[str, Any], schema_name: str) -> Dict[str, Any]:
        """Validate data against a named schema."""
        import jsonschema
        
        schema = self.schemas.get(schema_name)
        if not schema:
            raise ValueError(f"Unknown schema: {schema_name}")
        
        try:
            jsonschema.validate(instance=data, schema=schema)
            self.logger.debug("validation_passed", schema=schema_name)
            return {"success": True, "errors": []}
        except jsonschema.ValidationError as e:
            self.logger.warning("validation_failed", schema=schema_name, error=str(e))
            return {"success": False, "errors": [str(e)]}


class DependencyContainer:
    """Dependency injection container for MERID services."""
    
    def __init__(self):
        self._services: Dict[str, Any] = {}
        self._factories: Dict[str, callable] = {}
        self.logger = logger.bind(component="DependencyContainer")
    
    def register(self, name: str, instance: Any):
        """Register a service instance."""
        self._services[name] = instance
        self.logger.debug("service_registered", name=name)
    
    def register_factory(self, name: str, factory: callable):
        """Register a factory function for lazy instantiation."""
        self._factories[name] = factory
        self.logger.debug("factory_registered", name=name)
    
    def get(self, name: str) -> Any:
        """Get a service by name."""
        if name in self._services:
            return self._services[name]
        
        if name in self._factories:
            instance = self._factories[name]()
            self._services[name] = instance  # Cache the instance
            return instance
        
        raise KeyError(f"Service not found: {name}")
    
    def has(self, name: str) -> bool:
        """Check if a service is registered."""
        return name in self._services or name in self._factories


# Global container instance
container = DependencyContainer()


def configure_dependencies():
    """Configure default MERID dependencies."""
    from core.redis_events import RedisEventBus
    from core.celery_tasks import celery_app
    
    # Register Redis event bus
    container.register_factory("event_bus", lambda: RedisEventBus())
    
    # Register Celery app
    container.register("celery", celery_app)
    
    # Register validators
    container.register_factory("market_validator", lambda: MarketDataValidator())
    container.register_factory("schema_validator", lambda: SchemaValidator())
    
    logger.info("dependencies_configured")
