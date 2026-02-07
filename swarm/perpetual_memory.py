"""
Perpetual memory and swarm long-term learning system for MERID.

Implements:
- Layered memory architecture (short-term, long-term, preference)
- Multi-agent memory sharing
- Semantic memory with vector storage
- Lifecycle management and pruning
- Knowledge base for swarm learning
"""

import logging
import uuid
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from decimal import Decimal

logger = logging.getLogger(__name__)


class MemoryLayer(Enum):
    """Memory layer."""
    SHORT_TERM = "short_term"  # Per-agent rolling state
    LONG_TERM = "long_term"  # Semantic memory of strategies, incidents
    PREFERENCE = "preference"  # Summarized decisions and governance


class MemoryType(Enum):
    """Memory type."""
    STRATEGY = "strategy"
    INCIDENT = "incident"
    USER_BEHAVIOR = "user_behavior"
    LESSON_LEARNED = "lesson_learned"
    EXPERIMENT = "experiment"
    GOVERNANCE_DECISION = "governance_decision"
    PERFORMANCE_TRACE = "performance_trace"


class MemoryImportance(Enum):
    """Memory importance."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class MemoryEntry:
    """Memory entry."""
    memory_id: str
    layer: MemoryLayer
    memory_type: MemoryType
    
    # Content
    title: str
    content: str
    summary: str = ""
    
    # Metadata
    agent_id: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    
    # Importance and relevance
    importance: MemoryImportance = MemoryImportance.MEDIUM
    relevance_score: float = 1.0  # Decays over time
    
    # Embeddings (for semantic search)
    embedding: Optional[List[float]] = None
    
    # Access
    access_count: int = 0
    last_accessed: Optional[datetime] = None
    
    # Lifecycle
    expires_at: Optional[datetime] = None
    merged_into: Optional[str] = None  # If merged with another memory
    
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class KnowledgeArticle:
    """Knowledge base article."""
    article_id: str
    
    # Content
    title: str
    content: str
    category: str
    
    # Metadata
    author_agent_id: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    
    # Evidence
    source_memories: List[str] = field(default_factory=list)  # memory_ids
    citations: List[str] = field(default_factory=list)
    
    # Validation
    validated: bool = False
    validation_score: float = 0.0
    
    # Access
    view_count: int = 0
    
    # Versioning
    version: int = 1
    previous_version: Optional[str] = None
    
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class MemoryQuery:
    """Memory query."""
    query_id: str
    
    # Query
    query_text: str
    agent_id: str
    
    # Filters
    memory_types: List[MemoryType] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    min_importance: Optional[MemoryImportance] = None
    
    # Results
    results: List[str] = field(default_factory=list)  # memory_ids
    result_count: int = 0
    
    executed_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class MemorySummary:
    """Periodic memory summary."""
    summary_id: str
    
    # Scope
    start_time: datetime
    end_time: datetime
    
    # Content
    title: str
    summary: str
    
    # Key insights
    key_strategies: List[str] = field(default_factory=list)
    key_incidents: List[str] = field(default_factory=list)
    key_lessons: List[str] = field(default_factory=list)
    
    # Source memories
    source_memory_ids: List[str] = field(default_factory=list)
    
    created_at: datetime = field(default_factory=datetime.utcnow)


class PerpetualMemorySystem:
    """
    Perpetual memory and swarm long-term learning system.
    
    Features:
    - Layered memory (short-term, long-term, preference)
    - Multi-agent memory sharing
    - Semantic search with embeddings
    - Automatic lifecycle management
    - Knowledge base generation
    """
    
    def __init__(self):
        self._memories: Dict[str, MemoryEntry] = {}
        self._knowledge_articles: Dict[str, KnowledgeArticle] = {}
        self._queries: List[MemoryQuery] = []
        self._summaries: List[MemorySummary] = []
        
        # Agent access control
        self._agent_roles: Dict[str, str] = {}  # agent_id -> role
        
        # Configuration
        self._short_term_ttl_hours = 24
        self._relevance_decay_rate = 0.95  # Per day
        self._importance_rank = {
            MemoryImportance.LOW: 0,
            MemoryImportance.MEDIUM: 1,
            MemoryImportance.HIGH: 2,
            MemoryImportance.CRITICAL: 3,
        }
    
    def store_memory(
        self,
        layer: MemoryLayer,
        memory_type: MemoryType,
        title: str,
        content: str,
        agent_id: Optional[str] = None,
        tags: Optional[List[str]] = None,
        importance: MemoryImportance = MemoryImportance.MEDIUM,
    ) -> MemoryEntry:
        """Store memory entry."""
        memory_id = f"mem_{layer.value}_{uuid.uuid4().hex[:8]}"
        
        memory = MemoryEntry(
            memory_id=memory_id,
            layer=layer,
            memory_type=memory_type,
            title=title,
            content=content,
            agent_id=agent_id,
            tags=tags or [],
            importance=importance,
        )
        
        # Set expiry for short-term memories
        if layer == MemoryLayer.SHORT_TERM:
            memory.expires_at = datetime.utcnow() + timedelta(hours=self._short_term_ttl_hours)
        
        # Generate summary (simplified)
        memory.summary = content[:200] + "..." if len(content) > 200 else content
        
        # Generate embedding (mock - in real implementation would use sentence transformers)
        memory.embedding = [0.1] * 768  # Mock 768-dim embedding
        
        self._memories[memory_id] = memory
        
        logger.info(
            f"Stored memory '{memory_id}': {layer.value}/{memory_type.value} - {title}"
        )
        
        return memory
    
    def query_memories(
        self,
        query_text: str,
        agent_id: str,
        memory_types: Optional[List[MemoryType]] = None,
        tags: Optional[List[str]] = None,
        min_importance: Optional[MemoryImportance] = None,
        max_results: int = 10,
    ) -> List[MemoryEntry]:
        """Query memories with semantic search."""
        query_id = f"query_{uuid.uuid4().hex[:8]}"
        
        # Filter memories
        candidates = list(self._memories.values())
        
        # Apply filters
        if memory_types:
            candidates = [m for m in candidates if m.memory_type in memory_types]
        
        if tags:
            candidates = [
                m for m in candidates
                if any(tag in m.tags for tag in tags)
            ]
        
        if min_importance:
            importance_order = [
                MemoryImportance.LOW,
                MemoryImportance.MEDIUM,
                MemoryImportance.HIGH,
                MemoryImportance.CRITICAL,
            ]
            min_idx = importance_order.index(min_importance)
            candidates = [
                m for m in candidates
                if importance_order.index(m.importance) >= min_idx
            ]
        
        # Check agent access (role-based)
        agent_role = self._agent_roles.get(agent_id, "default")
        
        if agent_role == "trading":
            # Trading agents see performance-focused memories
            candidates = [
                m for m in candidates
                if m.memory_type in [
                    MemoryType.STRATEGY,
                    MemoryType.EXPERIMENT,
                    MemoryType.PERFORMANCE_TRACE,
                ]
            ]
        elif agent_role == "risk":
            # Risk agents see everything relevant
            pass  # No filter
        
        # Semantic search (simplified - would use vector similarity in real implementation)
        # For now, just sort by relevance score and recency
        candidates.sort(
            key=lambda m: (m.relevance_score, m.created_at),
            reverse=True,
        )
        
        results = candidates[:max_results]
        
        # Update access stats
        for memory in results:
            memory.access_count += 1
            memory.last_accessed = datetime.utcnow()
        
        # Store query
        query = MemoryQuery(
            query_id=query_id,
            query_text=query_text,
            agent_id=agent_id,
            memory_types=memory_types or [],
            tags=tags or [],
            min_importance=min_importance,
            results=[m.memory_id for m in results],
            result_count=len(results),
        )
        
        self._queries.append(query)
        
        logger.info(
            f"Query '{query_id}' by {agent_id}: found {len(results)} memories"
        )
        
        return results
    
    def create_knowledge_article(
        self,
        title: str,
        content: str,
        category: str,
        author_agent_id: Optional[str] = None,
        source_memories: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
    ) -> KnowledgeArticle:
        """Create knowledge base article from memories."""
        article_id = f"kb_{uuid.uuid4().hex[:8]}"
        
        article = KnowledgeArticle(
            article_id=article_id,
            title=title,
            content=content,
            category=category,
            author_agent_id=author_agent_id,
            source_memories=source_memories or [],
            tags=tags or [],
        )
        
        self._knowledge_articles[article_id] = article
        
        logger.info(
            f"Created knowledge article '{article_id}': {title} "
            f"(from {len(source_memories or [])} memories)"
        )
        
        return article
    
    def validate_knowledge_article(
        self,
        article_id: str,
        validation_score: float,
    ) -> KnowledgeArticle:
        """Validate knowledge article."""
        article = self._knowledge_articles.get(article_id)
        
        if not article:
            raise ValueError(f"Article '{article_id}' not found")
        
        article.validated = validation_score >= 0.7
        article.validation_score = validation_score
        article.updated_at = datetime.utcnow()
        
        logger.info(
            f"Validated article '{article_id}': "
            f"score={validation_score:.2f}, validated={article.validated}"
        )
        
        return article
    
    def create_periodic_summary(
        self,
        start_time: datetime,
        end_time: datetime,
        title: str,
    ) -> MemorySummary:
        """Create periodic summary of memories."""
        summary_id = f"summary_{uuid.uuid4().hex[:8]}"
        
        # Get memories in time range
        memories = [
            m for m in self._memories.values()
            if m.created_at >= start_time and m.created_at <= end_time
        ]
        
        # Extract key items by type
        key_strategies = [
            m.title for m in memories
            if m.memory_type == MemoryType.STRATEGY
            and m.importance in [MemoryImportance.HIGH, MemoryImportance.CRITICAL]
        ][:5]
        
        key_incidents = [
            m.title for m in memories
            if m.memory_type == MemoryType.INCIDENT
            and m.importance in [MemoryImportance.HIGH, MemoryImportance.CRITICAL]
        ][:5]
        
        key_lessons = [
            m.title for m in memories
            if m.memory_type == MemoryType.LESSON_LEARNED
        ][:5]
        
        # Generate summary text
        summary_text = f"""
Period: {start_time.strftime('%Y-%m-%d')} to {end_time.strftime('%Y-%m-%d')}

Total memories: {len(memories)}

Key strategies: {len(key_strategies)}
Key incidents: {len(key_incidents)}
Key lessons: {len(key_lessons)}

Top strategies:
{chr(10).join(f'- {s}' for s in key_strategies)}

Top incidents:
{chr(10).join(f'- {i}' for i in key_incidents)}

Top lessons:
{chr(10).join(f'- {l}' for l in key_lessons)}
"""
        
        summary = MemorySummary(
            summary_id=summary_id,
            start_time=start_time,
            end_time=end_time,
            title=title,
            summary=summary_text.strip(),
            key_strategies=key_strategies,
            key_incidents=key_incidents,
            key_lessons=key_lessons,
            source_memory_ids=[m.memory_id for m in memories],
        )
        
        self._summaries.append(summary)
        
        logger.info(
            f"Created summary '{summary_id}': {title} "
            f"({len(memories)} memories)"
        )
        
        return summary
    
    def decay_relevance(self) -> int:
        """Decay relevance scores over time."""
        now = datetime.utcnow()
        decayed_count = 0
        
        for memory in self._memories.values():
            age_days = (now - memory.created_at).days
            
            if age_days > 0:
                # Apply exponential decay
                memory.relevance_score *= (self._relevance_decay_rate ** age_days)
                decayed_count += 1
        
        logger.info(f"Decayed relevance for {decayed_count} memories")
        
        return decayed_count
    
    def prune_expired_memories(self) -> int:
        """Prune expired short-term memories."""
        now = datetime.utcnow()
        
        expired_ids = [
            memory_id for memory_id, memory in self._memories.items()
            if memory.expires_at and memory.expires_at <= now
        ]
        
        for memory_id in expired_ids:
            del self._memories[memory_id]
        
        logger.info(f"Pruned {len(expired_ids)} expired memories")
        
        return len(expired_ids)
    
    def merge_similar_memories(
        self,
        similarity_threshold: float = 0.9,
    ) -> int:
        """Merge similar memories to reduce redundancy."""
        merged_count = 0
        
        # Group by type and layer
        groups: Dict[tuple, List[MemoryEntry]] = {}
        
        for memory in self._memories.values():
            if memory.merged_into:
                continue  # Already merged
            
            key = (memory.layer, memory.memory_type)
            if key not in groups:
                groups[key] = []
            groups[key].append(memory)
        
        # Find similar pairs within each group
        for group_memories in groups.values():
            for i, mem1 in enumerate(group_memories):
                for mem2 in group_memories[i+1:]:
                    # Check similarity (simplified - would use embedding similarity)
                    if mem1.title == mem2.title or mem1.content[:100] == mem2.content[:100]:
                        # Merge mem2 into mem1
                        mem2.merged_into = mem1.memory_id
                        
                        # Update mem1
                        mem1.access_count += mem2.access_count
                        if self._importance_rank[mem2.importance] > self._importance_rank[mem1.importance]:
                            mem1.importance = mem2.importance
                        
                        merged_count += 1
                        
                        logger.debug(f"Merged memory '{mem2.memory_id}' into '{mem1.memory_id}'")
        
        logger.info(f"Merged {merged_count} similar memories")
        
        return merged_count
    
    def set_agent_role(self, agent_id: str, role: str) -> None:
        """Set agent role for access control."""
        self._agent_roles[agent_id] = role
        logger.info(f"Set agent '{agent_id}' role to '{role}'")
    
    def get_memory_stats(self) -> Dict[str, Any]:
        """Get memory statistics."""
        active_memories = [
            m for m in self._memories.values()
            if not m.merged_into
        ]
        
        return {
            "total_memories": len(self._memories),
            "active_memories": len(active_memories),
            "merged_memories": len(self._memories) - len(active_memories),
            "by_layer": {
                layer.value: sum(
                    1 for m in active_memories
                    if m.layer == layer
                )
                for layer in MemoryLayer
            },
            "by_type": {
                mem_type.value: sum(
                    1 for m in active_memories
                    if m.memory_type == mem_type
                )
                for mem_type in MemoryType
            },
            "by_importance": {
                importance.value: sum(
                    1 for m in active_memories
                    if m.importance == importance
                )
                for importance in MemoryImportance
            },
            "knowledge_articles": {
                "total": len(self._knowledge_articles),
                "validated": sum(
                    1 for a in self._knowledge_articles.values()
                    if a.validated
                ),
            },
            "queries_last_hour": len([
                q for q in self._queries
                if q.executed_at >= datetime.utcnow() - timedelta(hours=1)
            ]),
            "summaries": len(self._summaries),
        }
    
    def get_perpetual_memory_dashboard(self) -> Dict[str, Any]:
        """Get perpetual memory dashboard."""
        stats = self.get_memory_stats()
        
        # Calculate average relevance
        active_memories = [
            m for m in self._memories.values()
            if not m.merged_into
        ]
        
        avg_relevance = (
            sum(m.relevance_score for m in active_memories) / len(active_memories)
            if active_memories else 0.0
        )
        
        # Most accessed memories
        top_accessed = sorted(
            active_memories,
            key=lambda m: m.access_count,
            reverse=True,
        )[:5]
        
        return {
            "stats": stats,
            "health": {
                "avg_relevance_score": avg_relevance,
                "expired_memories": sum(
                    1 for m in self._memories.values()
                    if m.expires_at and m.expires_at <= datetime.utcnow()
                ),
            },
            "top_accessed": [
                {
                    "memory_id": m.memory_id,
                    "title": m.title,
                    "access_count": m.access_count,
                    "type": m.memory_type.value,
                }
                for m in top_accessed
            ],
            "recent_summaries": [
                {
                    "summary_id": s.summary_id,
                    "title": s.title,
                    "memory_count": len(s.source_memory_ids),
                }
                for s in self._summaries[-5:]
            ],
        }


_perpetual_memory_system: Optional[PerpetualMemorySystem] = None


def get_perpetual_memory_system() -> PerpetualMemorySystem:
    """Get global PerpetualMemorySystem instance."""
    global _perpetual_memory_system
    if _perpetual_memory_system is None:
        _perpetual_memory_system = PerpetualMemorySystem()
    return _perpetual_memory_system
