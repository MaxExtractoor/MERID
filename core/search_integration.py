"""MERID Search Integration (Elasticsearch & Meilisearch).

Fast fuzzy search for dashboard queries, trade history, and agent events.
Supports both Elasticsearch for logs and Meilisearch for UI search.
"""

from typing import List, Dict, Any, Optional, Union
from datetime import datetime
import structlog
import os

logger = structlog.get_logger(__name__)


class MeilisearchClient:
    """Client for Meilisearch fast fuzzy search."""
    
    def __init__(
        self,
        host: str = None,
        api_key: str = None
    ):
        self.host = host or os.getenv("MEILISEARCH_HOST", "http://localhost:7700")
        self.api_key = api_key or os.getenv("MEILISEARCH_API_KEY")
        self.client = None
        self.logger = logger.bind(search="Meilisearch")
        
        self._init_client()
    
    def _init_client(self):
        """Initialize Meilisearch client."""
        try:
            import meilisearch
            
            self.client = meilisearch.Client(self.host, self.api_key)
            self.logger.info("meilisearch_client_initialized", host=self.host)
            
        except ImportError:
            self.logger.error("meilisearch_not_installed")
        except Exception as e:
            self.logger.error("meilisearch_init_error", error=str(e))
    
    async def create_index(
        self,
        index_name: str,
        primary_key: str = "id"
    ) -> bool:
        """Create a new search index."""
        if not self.client:
            return False
        
        try:
            self.client.create_index(index_name, {"primaryKey": primary_key})
            self.logger.info("index_created", index=index_name)
            return True
        except Exception as e:
            self.logger.error("index_create_error", index=index_name, error=str(e))
            return False
    
    async def configure_index(
        self,
        index_name: str,
        searchable_attributes: List[str],
        filterable_attributes: List[str] = None,
        sortable_attributes: List[str] = None
    ) -> bool:
        """Configure index settings."""
        if not self.client:
            return False
        
        try:
            index = self.client.index(index_name)
            
            index.update_searchable_attributes(searchable_attributes)
            
            if filterable_attributes:
                index.update_filterable_attributes(filterable_attributes)
            
            if sortable_attributes:
                index.update_sortable_attributes(sortable_attributes)
            
            self.logger.info("index_configured", index=index_name)
            return True
            
        except Exception as e:
            self.logger.error("index_config_error", error=str(e))
            return False
    
    async def add_documents(
        self,
        index_name: str,
        documents: List[Dict[str, Any]]
    ) -> bool:
        """Add documents to index."""
        if not self.client:
            return False
        
        try:
            index = self.client.index(index_name)
            index.add_documents(documents)
            
            self.logger.info(
                "documents_added",
                index=index_name,
                count=len(documents)
            )
            return True
            
        except Exception as e:
            self.logger.error("add_documents_error", error=str(e))
            return False
    
    async def search(
        self,
        index_name: str,
        query: str,
        filters: str = None,
        limit: int = 20,
        offset: int = 0
    ) -> Dict[str, Any]:
        """Search documents."""
        if not self.client:
            return {"hits": [], "estimatedTotalHits": 0}
        
        try:
            index = self.client.index(index_name)
            
            params = {
                "limit": limit,
                "offset": offset
            }
            
            if filters:
                params["filter"] = filters
            
            results = index.search(query, params)
            
            return {
                "hits": results.get("hits", []),
                "total": results.get("estimatedTotalHits", 0),
                "page": offset // limit + 1,
                "query": query
            }
            
        except Exception as e:
            self.logger.error("search_error", query=query, error=str(e))
            return {"hits": [], "total": 0, "error": str(e)}
    
    async def delete_documents(
        self,
        index_name: str,
        document_ids: List[str]
    ) -> bool:
        """Delete documents from index."""
        if not self.client:
            return False
        
        try:
            index = self.client.index(index_name)
            index.delete_documents(document_ids)
            return True
        except Exception as e:
            self.logger.error("delete_error", error=str(e))
            return False


class ElasticsearchClient:
    """Client for Elasticsearch log and event search."""
    
    def __init__(
        self,
        hosts: List[str] = None,
        username: str = None,
        password: str = None
    ):
        self.hosts = hosts or [os.getenv("ELASTICSEARCH_HOST", "localhost:9200")]
        self.username = username or os.getenv("ELASTICSEARCH_USER")
        self.password = password or os.getenv("ELASTICSEARCH_PASSWORD")
        self.client = None
        self.logger = logger.bind(search="Elasticsearch")
        
        self._init_client()
    
    def _init_client(self):
        """Initialize Elasticsearch client."""
        try:
            from elasticsearch import Elasticsearch
            
            auth = None
            if self.username and self.password:
                auth = (self.username, self.password)
            
            self.client = Elasticsearch(
                self.hosts,
                basic_auth=auth,
                verify_certs=False
            )
            
            if self.client.ping():
                self.logger.info("elasticsearch_connected")
            else:
                self.logger.warning("elasticsearch_ping_failed")
                
        except ImportError:
            self.logger.error("elasticsearch_not_installed")
        except Exception as e:
            self.logger.error("elasticsearch_init_error", error=str(e))
    
    async def create_index(
        self,
        index_name: str,
        mappings: Dict[str, Any] = None
    ) -> bool:
        """Create Elasticsearch index with mappings."""
        if not self.client:
            return False
        
        try:
            if self.client.indices.exists(index=index_name):
                self.logger.info("index_already_exists", index=index_name)
                return True
            
            body = {"settings": {"number_of_shards": 1, "number_of_replicas": 0}}
            
            if mappings:
                body["mappings"] = mappings
            
            self.client.indices.create(index=index_name, body=body)
            self.logger.info("index_created", index=index_name)
            return True
            
        except Exception as e:
            self.logger.error("index_create_error", error=str(e))
            return False
    
    async def index_document(
        self,
        index_name: str,
        document: Dict[str, Any],
        doc_id: str = None
    ) -> bool:
        """Index a single document."""
        if not self.client:
            return False
        
        try:
            self.client.index(
                index=index_name,
                id=doc_id,
                body=document
            )
            return True
        except Exception as e:
            self.logger.error("index_document_error", error=str(e))
            return False
    
    async def bulk_index(
        self,
        index_name: str,
        documents: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Bulk index documents."""
        if not self.client:
            return {"success": False, "error": "Client not initialized"}
        
        try:
            from elasticsearch.helpers import bulk
            
            actions = [
                {
                    "_index": index_name,
                    "_source": doc
                }
                for doc in documents
            ]
            
            success, errors = bulk(self.client, actions)
            
            self.logger.info(
                "bulk_index_complete",
                success=success,
                errors=len(errors) if errors else 0
            )
            
            return {
                "success": True,
                "indexed": success,
                "errors": errors
            }
            
        except Exception as e:
            self.logger.error("bulk_index_error", error=str(e))
            return {"success": False, "error": str(e)}
    
    async def search(
        self,
        index_name: str,
        query: Dict[str, Any],
        size: int = 10
    ) -> Dict[str, Any]:
        """Search Elasticsearch."""
        if not self.client:
            return {"hits": {"hits": [], "total": {"value": 0}}}
        
        try:
            results = self.client.search(
                index=index_name,
                body={"query": query, "size": size}
            )
            
            return {
                "hits": results["hits"]["hits"],
                "total": results["hits"]["total"]["value"],
                "took": results["took"]
            }
            
        except Exception as e:
            self.logger.error("search_error", error=str(e))
            return {"hits": [], "total": 0, "error": str(e)}
    
    async def search_text(
        self,
        index_name: str,
        field: str,
        text: str,
        size: int = 10
    ) -> Dict[str, Any]:
        """Simple text search."""
        query = {
            "match": {
                field: text
            }
        }
        return await self.search(index_name, query, size)
    
    async def delete_index(self, index_name: str) -> bool:
        """Delete an index."""
        if not self.client:
            return False
        
        try:
            self.client.indices.delete(index=index_name, ignore=[400, 404])
            self.logger.info("index_deleted", index=index_name)
            return True
        except Exception as e:
            self.logger.error("delete_index_error", error=str(e))
            return False


class TradeSearchService:
    """Search service for trade history and signals."""
    
    def __init__(
        self,
        meilisearch: Optional[MeilisearchClient] = None,
        elasticsearch: Optional[ElasticsearchClient] = None
    ):
        self.meili = meilisearch or MeilisearchClient()
        self.elastic = elasticsearch or ElasticsearchClient()
        self.logger = logger.bind(component="TradeSearchService")
    
    async def index_trade(
        self,
        trade: Dict[str, Any],
        index_name: str = "trades"
    ) -> bool:
        """Index a trade for search."""
        # Add timestamp if missing
        if "timestamp" not in trade:
            trade["timestamp"] = datetime.now().isoformat()
        
        # Index in Meilisearch for UI search
        await self.meili.add_documents(index_name, [trade])
        
        # Index in Elasticsearch for log analysis
        await self.elastic.index_document(index_name, trade, trade.get("id"))
        
        return True
    
    async def search_trades(
        self,
        query: str,
        symbol: str = None,
        side: str = None,
        status: str = None,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """Search trades with filters."""
        filters = []
        
        if symbol:
            filters.append(f"symbol = {symbol}")
        if side:
            filters.append(f"side = {side}")
        if status:
            filters.append(f"status = {status}")
        
        filter_str = " AND ".join(filters) if filters else None
        
        results = await self.meili.search(
            "trades",
            query,
            filters=filter_str,
            limit=limit
        )
        
        return results.get("hits", [])
    
    async def get_recent_trades(
        self,
        symbol: str = None,
        minutes: int = 60
    ) -> List[Dict[str, Any]]:
        """Get recent trades from Elasticsearch."""
        query = {
            "range": {
                "timestamp": {
                    "gte": f"now-{minutes}m"
                }
            }
        }
        
        if symbol:
            query = {
                "bool": {
                    "must": [
                        query,
                        {"term": {"symbol": symbol}}
                    ]
                }
            }
        
        results = await self.elastic.search("trades", query, size=100)
        
        return [hit["_source"] for hit in results.get("hits", [])]


class SymbolSearchService:
    """Fast symbol/ticker search for dashboard."""
    
    def __init__(self, meilisearch: Optional[MeilisearchClient] = None):
        self.meili = meilisearch or MeilisearchClient()
        self.logger = logger.bind(component="SymbolSearchService")
        self.index_name = "symbols"
    
    async def initialize(self):
        """Initialize symbol index with configuration."""
        await self.meili.create_index(self.index_name, "symbol")
        await self.meili.configure_index(
            self.index_name,
            searchable_attributes=["symbol", "name", "description"],
            filterable_attributes=["type", "exchange"],
            sortable_attributes=["market_cap", "volume"]
        )
    
    async def index_symbols(self, symbols: List[Dict[str, Any]]):
        """Index symbols for search."""
        documents = [
            {
                "id": s.get("symbol", str(i)),
                "symbol": s.get("symbol"),
                "name": s.get("name"),
                "description": s.get("description", ""),
                "type": s.get("type", "stock"),
                "exchange": s.get("exchange"),
                "market_cap": s.get("market_cap", 0),
                "volume": s.get("volume", 0)
            }
            for i, s in enumerate(symbols)
        ]
        
        await self.meili.add_documents(self.index_name, documents)
    
    async def search_symbols(
        self,
        query: str,
        type_filter: str = None,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Fuzzy search for symbols."""
        filters = f"type = {type_filter}" if type_filter else None
        
        results = await self.meili.search(
            self.index_name,
            query,
            filters=filters,
            limit=limit
        )
        
        return results.get("hits", [])


class AgentEventSearchService:
    """Search service for swarm agent events."""
    
    def __init__(self, elasticsearch: Optional[ElasticsearchClient] = None):
        self.elastic = elasticsearch or ElasticsearchClient()
        self.logger = logger.bind(component="AgentEventSearchService")
        self.index_name = "agent_events"
    
    async def initialize(self):
        """Initialize agent events index."""
        mappings = {
            "properties": {
                "timestamp": {"type": "date"},
                "agent": {"type": "keyword"},
                "event_type": {"type": "keyword"},
                "level": {"type": "keyword"},
                "message": {"type": "text"},
                "data": {"type": "object"}
            }
        }
        
        await self.elastic.create_index(self.index_name, mappings)
    
    async def log_event(
        self,
        agent: str,
        event_type: str,
        message: str,
        level: str = "info",
        data: Dict = None
    ):
        """Log agent event."""
        event = {
            "timestamp": datetime.now().isoformat(),
            "agent": agent,
            "event_type": event_type,
            "level": level,
            "message": message,
            "data": data or {}
        }
        
        await self.elastic.index_document(self.index_name, event)
    
    async def search_events(
        self,
        agent: str = None,
        event_type: str = None,
        level: str = None,
        hours: int = 24,
        size: int = 100
    ) -> List[Dict[str, Any]]:
        """Search agent events."""
        must_clauses = [
            {
                "range": {
                    "timestamp": {
                        "gte": f"now-{hours}h"
                    }
                }
            }
        ]
        
        if agent:
            must_clauses.append({"term": {"agent": agent}})
        if event_type:
            must_clauses.append({"term": {"event_type": event_type}})
        if level:
            must_clauses.append({"term": {"level": level}})
        
        query = {"bool": {"must": must_clauses}}
        
        results = await self.elastic.search(self.index_name, query, size)
        
        return [hit["_source"] for hit in results.get("hits", [])]


# Singleton instances
meilisearch_client = MeilisearchClient()
elasticsearch_client = ElasticsearchClient()
trade_search = TradeSearchService()
symbol_search = SymbolSearchService()
agent_event_search = AgentEventSearchService()
