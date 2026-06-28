# LEGACY: not used by kalshi_crypto_15m_v2 profile
# This module implements decentralized agent registry with DID-based identities
# The lean 15m stack uses agent_grid_15m for agent management

"""
Decentralized agent registry with DID-based identities for MERID.

Implements:
- Agent discovery metadata schema (ANP/ACDP-style)
- DID-based cryptographic identities
- Capability advertisement and versioning
- Hybrid decentralized storage (on-chain + DHT/IPFS)
- Signature verification and trust
"""

import threading

from utils.logger import get_logger
import hashlib
import json
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from decimal import Decimal

logger = get_logger(__name__)


class DIDMethod(Enum):
    """DID method types."""
    KEY = "key"  # did:key - self-contained, derived from public key
    WEB = "web"  # did:web - tied to HTTPS domains
    PKH = "pkh"  # did:pkh - blockchain address-based
    CUSTOM = "custom"  # Custom ecosystem DIDs


class CapabilityStatus(Enum):
    """Capability status."""
    STABLE = "stable"
    BETA = "beta"
    DEPRECATED = "deprecated"
    EXPERIMENTAL = "experimental"


class SecurityLevel(Enum):
    """Security level for capabilities."""
    PUBLIC = "public"  # No sensitive data
    CONFIDENTIAL = "confidential"  # Requires NDA
    RESTRICTED = "restricted"  # High trust only
    INTERNAL = "internal"  # MERID-only


class RegistryStorageType(Enum):
    """Registry storage backend."""
    ON_CHAIN = "on_chain"  # Blockchain registry
    DHT = "dht"  # Distributed hash table
    IPFS = "ipfs"  # InterPlanetary File System
    HYBRID = "hybrid"  # On-chain + off-chain


@dataclass
class PublicKey:
    """Public key for agent identity."""
    key_id: str
    key_type: str  # RSA, Ed25519, secp256k1
    public_key_pem: str
    cert_fingerprint: Optional[str] = None  # For mTLS
    
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class Endpoint:
    """Agent endpoint."""
    endpoint_id: str
    endpoint_type: str  # messaging, introspection, health, ui
    
    # Connection
    url: str
    protocol: str  # http, websocket, grpc
    
    # Security
    requires_mtls: bool = True
    requires_auth: bool = True
    
    # Metadata
    description: str = ""
    
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class CapabilitySchema:
    """Capability input/output schema."""
    schema_id: str
    schema_type: str  # json_schema, protobuf, avro
    schema_content: Dict[str, Any]
    
    version: str = "1.0.0"


@dataclass
class Capability:
    """Agent capability descriptor."""
    capability_id: str
    name: str  # e.g., "merid.defi.backtest.tick"
    version: str  # Semantic version
    
    # Status
    status: CapabilityStatus = CapabilityStatus.STABLE
    
    # Schemas
    input_schema: Optional[CapabilitySchema] = None
    output_schema: Optional[CapabilitySchema] = None
    
    # Performance
    latency_profile: str = "medium"  # low, medium, high
    throughput_profile: str = "medium"
    cost_profile: str = "medium"
    
    # Security and compliance
    security_level: SecurityLevel = SecurityLevel.PUBLIC
    jurisdictions_allowed: List[str] = field(default_factory=list)
    data_handling_rules: List[str] = field(default_factory=list)
    
    # Metadata
    description: str = ""
    tags: List[str] = field(default_factory=list)
    
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class AgentPolicy:
    """Agent usage policies."""
    policy_id: str
    
    # Data policies
    no_pii: bool = True
    no_financial_advice: bool = True
    no_market_abuse: bool = True
    
    # Rate limits
    max_requests_per_minute: int = 60
    max_concurrent_requests: int = 10
    
    # Data handling
    data_retention_days: int = 90
    anonymize_logs: bool = True
    
    # Compliance
    requires_nda: bool = False
    gdpr_compliant: bool = True
    
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class TrustAttestation:
    """Trust attestation from issuer."""
    attestation_id: str
    
    # Issuer
    issuer_did: str
    issuer_name: str
    
    # Attestation
    attestation_type: str  # security_audit, code_review, reputation
    score: float  # 0.0 to 1.0
    
    # Evidence
    evidence_url: Optional[str] = None
    audit_report_hash: Optional[str] = None
    
    # Validity
    issued_at: datetime = field(default_factory=datetime.utcnow)
    expires_at: Optional[datetime] = None
    
    # Signature
    signature: str = ""


@dataclass
class AgentMetadata:
    """Agent discovery metadata (ANP/ACDP-style)."""
    
    # Identity
    agent_id: str  # DID
    did_method: DIDMethod
    
    # Public keys
    public_keys: List[PublicKey] = field(default_factory=list)
    
    # Endpoints
    endpoints: List[Endpoint] = field(default_factory=list)
    
    # Capabilities
    capabilities: List[Capability] = field(default_factory=list)
    
    # Policies
    policies: AgentPolicy = field(default_factory=lambda: AgentPolicy(policy_id="default"))
    
    # Trust
    reputation_score: float = 0.5  # 0.0 to 1.0
    trust_attestations: List[TrustAttestation] = field(default_factory=list)
    
    # Metadata
    name: str = ""
    description: str = ""
    owner_organization: str = ""
    contact_email: str = ""
    tags: List[str] = field(default_factory=list)
    
    # Versioning
    metadata_version: str = "1.0.0"
    last_updated: datetime = field(default_factory=datetime.utcnow)
    
    # Signature
    signature: str = ""
    signature_algorithm: str = "Ed25519"
    
    created_at: datetime = field(default_factory=datetime.utcnow)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for signing."""
        return {
            "agent_id": self.agent_id,
            "did_method": self.did_method.value,
            "public_keys": [
                {
                    "key_id": pk.key_id,
                    "key_type": pk.key_type,
                    "public_key_pem": pk.public_key_pem,
                    "cert_fingerprint": pk.cert_fingerprint,
                }
                for pk in self.public_keys
            ],
            "endpoints": [
                {
                    "endpoint_id": ep.endpoint_id,
                    "endpoint_type": ep.endpoint_type,
                    "url": ep.url,
                    "protocol": ep.protocol,
                    "requires_mtls": ep.requires_mtls,
                    "requires_auth": ep.requires_auth,
                }
                for ep in self.endpoints
            ],
            "capabilities": [
                {
                    "capability_id": cap.capability_id,
                    "name": cap.name,
                    "version": cap.version,
                    "status": cap.status.value,
                    "security_level": cap.security_level.value,
                    "latency_profile": cap.latency_profile,
                    "description": cap.description,
                }
                for cap in self.capabilities
            ],
            "policies": {
                "no_pii": self.policies.no_pii,
                "no_financial_advice": self.policies.no_financial_advice,
                "no_market_abuse": self.policies.no_market_abuse,
                "max_requests_per_minute": self.policies.max_requests_per_minute,
            },
            "reputation_score": self.reputation_score,
            "name": self.name,
            "description": self.description,
            "owner_organization": self.owner_organization,
            "metadata_version": self.metadata_version,
            "last_updated": self.last_updated.isoformat(),
        }
    
    def compute_content_hash(self) -> str:
        """Compute content hash for integrity verification."""
        content = json.dumps(self.to_dict(), sort_keys=True)
        return hashlib.sha256(content.encode()).hexdigest()


@dataclass
class RegistryEntry:
    """Registry entry (on-chain or DHT)."""
    entry_id: str
    
    # Agent reference
    agent_did: str
    content_hash: str  # Hash of full metadata document
    
    # Storage location
    storage_type: RegistryStorageType
    storage_pointer: str  # URL, IPFS CID, or DHT key
    
    # On-chain metadata (minimal)
    on_chain_tx_hash: Optional[str] = None
    on_chain_block: Optional[int] = None
    
    # Verification
    verified: bool = False
    verification_timestamp: Optional[datetime] = None
    
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)


class AgentRegistry:
    """
    Decentralized agent registry with DID-based identities.
    
    Features:
    - Hybrid storage (on-chain + DHT/IPFS)
    - DID-based agent identities
    - Capability-based discovery
    - Signature verification
    - Reputation tracking
    """
    
    def __init__(self, storage_type: RegistryStorageType = RegistryStorageType.HYBRID):
        self._storage_type = storage_type
        
        # In-memory storage (in production, would use actual on-chain/DHT)
        self._agents: Dict[str, AgentMetadata] = {}
        self._registry_entries: Dict[str, RegistryEntry] = {}
        
        # Indexes for fast lookup
        self._capability_index: Dict[str, Set[str]] = {}  # capability_name -> agent_ids
        self._tag_index: Dict[str, Set[str]] = {}  # tag -> agent_ids
        
        # Trust and reputation
        self._trusted_issuers: Set[str] = set()  # Trusted attestation issuers
        self._min_reputation_threshold = 0.3
    
    def register_agent(
        self,
        agent_metadata: AgentMetadata,
        storage_pointer: Optional[str] = None,
    ) -> RegistryEntry:
        """Register agent in registry."""
        
        # Compute content hash
        content_hash = agent_metadata.compute_content_hash()
        
        # Verify signature (simplified - in production would verify against public key)
        if not agent_metadata.signature:
            logger.warning(f"Agent {agent_metadata.agent_id} has no signature")
        
        # Create registry entry
        entry_id = f"entry_{agent_metadata.agent_id}"
        
        # Determine storage pointer
        if storage_pointer is None:
            if self._storage_type == RegistryStorageType.IPFS:
                storage_pointer = f"ipfs://{content_hash}"
            elif self._storage_type == RegistryStorageType.DHT:
                storage_pointer = f"dht://{agent_metadata.agent_id}"
            elif self._storage_type == RegistryStorageType.ON_CHAIN:
                storage_pointer = f"chain://registry/{agent_metadata.agent_id}"
            else:  # HYBRID
                storage_pointer = f"hybrid://{content_hash}"
        
        entry = RegistryEntry(
            entry_id=entry_id,
            agent_did=agent_metadata.agent_id,
            content_hash=content_hash,
            storage_type=self._storage_type,
            storage_pointer=storage_pointer,
        )
        
        # Store agent metadata
        self._agents[agent_metadata.agent_id] = agent_metadata
        self._registry_entries[entry_id] = entry
        
        # Update indexes
        self._update_indexes(agent_metadata)
        
        logger.info(
            f"Registered agent '{agent_metadata.agent_id}' "
            f"({agent_metadata.name}) with {len(agent_metadata.capabilities)} capabilities"
        )
        
        return entry
    
    def _update_indexes(self, agent_metadata: AgentMetadata) -> None:
        """Update capability and tag indexes."""
        agent_id = agent_metadata.agent_id
        
        # Index capabilities
        for capability in agent_metadata.capabilities:
            cap_name = capability.name
            if cap_name not in self._capability_index:
                self._capability_index[cap_name] = set()
            self._capability_index[cap_name].add(agent_id)
        
        # Index tags
        for tag in agent_metadata.tags:
            if tag not in self._tag_index:
                self._tag_index[tag] = set()
            self._tag_index[tag].add(agent_id)
    
    def discover_agents(
        self,
        capability_name: Optional[str] = None,
        tags: Optional[List[str]] = None,
        min_reputation: Optional[float] = None,
        security_level: Optional[SecurityLevel] = None,
        max_results: int = 10,
    ) -> List[AgentMetadata]:
        """Discover agents by capability, tags, and filters."""
        
        candidates = set(self._agents.keys())
        
        # Filter by capability
        if capability_name:
            if capability_name in self._capability_index:
                candidates &= self._capability_index[capability_name]
            else:
                return []
        
        # Filter by tags
        if tags:
            for tag in tags:
                if tag in self._tag_index:
                    candidates &= self._tag_index[tag]
        
        # Get agent metadata
        agents = [self._agents[agent_id] for agent_id in candidates]
        
        # Filter by reputation
        min_rep = min_reputation or self._min_reputation_threshold
        agents = [a for a in agents if a.reputation_score >= min_rep]
        
        # Filter by security level
        if security_level:
            agents = [
                a for a in agents
                if any(
                    cap.security_level == security_level
                    for cap in a.capabilities
                )
            ]
        
        # Sort by reputation (highest first)
        agents.sort(key=lambda a: a.reputation_score, reverse=True)
        
        results = agents[:max_results]
        
        logger.info(
            f"Discovered {len(results)} agents "
            f"(capability: {capability_name}, tags: {tags})"
        )
        
        return results
    
    def get_agent(self, agent_id: str) -> Optional[AgentMetadata]:
        """Get agent metadata by DID."""
        return self._agents.get(agent_id)
    
    def verify_agent_signature(self, agent_metadata: AgentMetadata) -> bool:
        """Verify agent metadata signature."""
        # Simplified verification - in production would:
        # 1. Extract public key from DID or metadata
        # 2. Verify signature over canonical JSON
        # 3. Check signature algorithm matches
        
        if not agent_metadata.signature:
            return False
        
        # Mock verification
        return len(agent_metadata.signature) > 0
    
    def update_reputation(
        self,
        agent_id: str,
        new_score: float,
        reason: str = "",
    ) -> None:
        """Update agent reputation score."""
        agent = self._agents.get(agent_id)
        
        if not agent:
            logger.warning(f"Agent {agent_id} not found for reputation update")
            return
        
        old_score = agent.reputation_score
        agent.reputation_score = max(0.0, min(1.0, new_score))
        
        logger.info(
            f"Updated reputation for {agent_id}: "
            f"{old_score:.2f} -> {agent.reputation_score:.2f} ({reason})"
        )
    
    def add_trust_attestation(
        self,
        agent_id: str,
        attestation: TrustAttestation,
    ) -> None:
        """Add trust attestation to agent."""
        agent = self._agents.get(agent_id)
        
        if not agent:
            logger.warning(f"Agent {agent_id} not found for attestation")
            return
        
        agent.trust_attestations.append(attestation)
        
        # Update reputation based on attestation
        if attestation.issuer_did in self._trusted_issuers:
            # Weight attestation score into reputation
            agent.reputation_score = (
                agent.reputation_score * 0.7 + attestation.score * 0.3
            )
        
        logger.info(
            f"Added attestation to {agent_id} from {attestation.issuer_name} "
            f"(score: {attestation.score:.2f})"
        )
    
    def add_trusted_issuer(self, issuer_did: str) -> None:
        """Add trusted attestation issuer."""
        self._trusted_issuers.add(issuer_did)
        logger.info(f"Added trusted issuer: {issuer_did}")
    
    def get_capability_versions(
        self,
        capability_name: str,
    ) -> List[tuple[str, str]]:
        """Get all agents and versions for a capability."""
        if capability_name not in self._capability_index:
            return []
        
        results = []
        for agent_id in self._capability_index[capability_name]:
            agent = self._agents.get(agent_id)
            if agent:
                for cap in agent.capabilities:
                    if cap.name == capability_name:
                        results.append((agent_id, cap.version))
        
        return results
    
    def get_registry_stats(self) -> Dict[str, Any]:
        """Get registry statistics."""
        total_capabilities = sum(
            len(agent.capabilities) for agent in self._agents.values()
        )
        
        avg_reputation = (
            sum(agent.reputation_score for agent in self._agents.values()) / len(self._agents)
            if self._agents else 0.0
        )
        
        return {
            "total_agents": len(self._agents),
            "total_capabilities": total_capabilities,
            "unique_capability_names": len(self._capability_index),
            "unique_tags": len(self._tag_index),
            "avg_reputation": avg_reputation,
            "storage_type": self._storage_type.value,
            "trusted_issuers": len(self._trusted_issuers),
        }


_agent_registry: Optional[AgentRegistry] = None
_agent_registry_lock = threading.Lock()


def get_agent_registry() -> AgentRegistry:
    """Get global AgentRegistry instance."""
    global _agent_registry
    if _agent_registry is None:
        with _agent_registry_lock:
            if _agent_registry is None:
                _agent_registry = AgentRegistry()
    return _agent_registry
