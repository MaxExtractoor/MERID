"""
Data snapshot for agent analysis.
Read-only view of current system state.
"""

from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta

from ..utils.types import Datum, DataSource, DataType


class DataSnapshot:
    """
    Immutable snapshot of data for agent analysis.
    Agents receive this read-only view - cannot modify memory.
    """
    
    def __init__(self, data: List[Datum], timestamp: datetime):
        self._data = data
        self._timestamp = timestamp
        self._index_by_source: Dict[DataSource, List[Datum]] = {}
        self._index_by_type: Dict[DataType, List[Datum]] = {}
        self._build_indices()
    
    def _build_indices(self) -> None:
        """Build indices for fast lookup."""
        for datum in self._data:
            if datum.source not in self._index_by_source:
                self._index_by_source[datum.source] = []
            self._index_by_source[datum.source].append(datum)
            
            if datum.data_type not in self._index_by_type:
                self._index_by_type[datum.data_type] = []
            self._index_by_type[datum.data_type].append(datum)
    
    def get_by_source(
        self,
        source: DataSource,
        max_age: Optional[timedelta] = None,
    ) -> List[Datum]:
        """
        Get all data from specific source.
        
        Args:
            source: Data source to filter by
            max_age: Optional maximum age of data
        
        Returns:
            List of matching data points
        """
        data = self._index_by_source.get(source, [])
        
        if max_age is not None:
            cutoff = self._timestamp - max_age
            data = [d for d in data if d.timestamp >= cutoff]
        
        return data
    
    def get_by_type(
        self,
        data_type: DataType,
        max_age: Optional[timedelta] = None,
    ) -> List[Datum]:
        """
        Get all data of specific type.
        
        Args:
            data_type: Data type to filter by
            max_age: Optional maximum age of data
        
        Returns:
            List of matching data points
        """
        data = self._index_by_type.get(data_type, [])
        
        if max_age is not None:
            cutoff = self._timestamp - max_age
            data = [d for d in data if d.timestamp >= cutoff]
        
        return data
    
    def get_latest(
        self,
        source: Optional[DataSource] = None,
        data_type: Optional[DataType] = None,
    ) -> Optional[Datum]:
        """
        Get most recent datum matching filters.
        
        Args:
            source: Optional source filter
            data_type: Optional type filter
        
        Returns:
            Most recent matching datum or None
        """
        candidates = self._data
        
        if source is not None:
            candidates = [d for d in candidates if d.source == source]
        
        if data_type is not None:
            candidates = [d for d in candidates if d.data_type == data_type]
        
        if not candidates:
            return None
        
        return max(candidates, key=lambda d: d.timestamp)
    
    def get_price(
        self,
        source: DataSource,
        max_age: timedelta = timedelta(minutes=5),
    ) -> Optional[float]:
        """
        Get latest price from source.
        
        Args:
            source: Exchange/data source
            max_age: Maximum age of price data
        
        Returns:
            Latest price or None
        """
        price_data = self.get_by_type(DataType.PRICE, max_age=max_age)
        price_data = [d for d in price_data if d.source == source]
        
        if not price_data:
            return None
        
        latest = max(price_data, key=lambda d: d.timestamp)
        return float(latest.value)
    
    def get_odds(
        self,
        source: DataSource,
        max_age: timedelta = timedelta(minutes=5),
    ) -> Optional[float]:
        """
        Get latest prediction market odds.
        
        Args:
            source: Prediction market source
            max_age: Maximum age of odds data
        
        Returns:
            Latest odds or None
        """
        odds_data = self.get_by_type(DataType.ODDS, max_age=max_age)
        odds_data = [d for d in odds_data if d.source == source]
        
        if not odds_data:
            return None
        
        latest = max(odds_data, key=lambda d: d.timestamp)
        return float(latest.value)
    
    def get_sentiment(
        self,
        source: Optional[DataSource] = None,
        max_age: timedelta = timedelta(hours=1),
    ) -> Optional[float]:
        """
        Get aggregated sentiment score.
        
        Args:
            source: Optional specific source
            max_age: Maximum age of sentiment data
        
        Returns:
            Sentiment score in [-1, 1] or None
        """
        sentiment_data = self.get_by_type(DataType.SENTIMENT, max_age=max_age)
        
        if source is not None:
            sentiment_data = [d for d in sentiment_data if d.source == source]
        
        if not sentiment_data:
            return None
        
        # Weighted average by confidence and recency
        total_weight = 0.0
        weighted_sum = 0.0
        
        for datum in sentiment_data:
            weight = datum.current_confidence(self._timestamp)
            weighted_sum += float(datum.value) * weight
            total_weight += weight
        
        if total_weight == 0:
            return None
        
        return weighted_sum / total_weight
    
    @property
    def timestamp(self) -> datetime:
        """Current snapshot timestamp."""
        return self._timestamp
    
    @property
    def data_count(self) -> int:
        """Total number of data points in snapshot."""
        return len(self._data)
    
    def summary(self) -> Dict[str, Any]:
        """
        Get snapshot summary statistics.
        
        Returns:
            Dictionary with source counts, type counts, age distribution
        """
        source_counts = {
            source.value: len(data)
            for source, data in self._index_by_source.items()
        }
        
        type_counts = {
            dtype.value: len(data)
            for dtype, data in self._index_by_type.items()
        }
        
        ages = [(self._timestamp - d.timestamp).total_seconds() for d in self._data]
        
        return {
            "timestamp": self._timestamp.isoformat(),
            "total_data_points": len(self._data),
            "sources": source_counts,
            "types": type_counts,
            "avg_age_seconds": sum(ages) / len(ages) if ages else 0,
            "max_age_seconds": max(ages) if ages else 0,
        }
