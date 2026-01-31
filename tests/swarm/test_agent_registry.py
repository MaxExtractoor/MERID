"""Tests for swarm.agent_registry."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from swarm import agent_registry as ar


def make_agent_metadata(
    agent_id: str,
    *,
    capability_name: str = "merid.defi.backtest.tick",
    capability_status: ar.CapabilityStatus = ar.CapabilityStatus.STABLE,
    reputation: float = 0.6,
    tags: list[str] | None = None,
) -> ar.AgentMetadata:
    capability = ar.Capability(
        capability_id=f"cap_{agent_id}",
        name=capability_name,
        version="1.0.0",
        status=capability_status,
        security_level=ar.SecurityLevel.PUBLIC,
        description="Capability",
        tags=["defi"],
    )
    public_key = ar.PublicKey(key_id=f"key_{agent_id}", key_type="Ed25519", public_key_pem="PEM")
    endpoint = ar.Endpoint(
        endpoint_id=f"endpoint_{agent_id}",
        endpoint_type="messaging",
        url="https://agent.merid",
        protocol="https",
    )
    metadata = ar.AgentMetadata(
        agent_id=agent_id,
        did_method=ar.DIDMethod.KEY,
        public_keys=[public_key],
        endpoints=[endpoint],
        capabilities=[capability],
        reputation_score=reputation,
        tags=tags or [],
        name=f"Agent {agent_id}",
        signature="sig",
    )
    return metadata


@pytest.fixture()
def registry():
    return ar.AgentRegistry()


def test_register_agent_indexes_capabilities_and_tags(registry):
    metadata = make_agent_metadata("did:agent:1", tags=["strategist"])

    entry = registry.register_agent(metadata)

    assert entry.agent_did == "did:agent:1"
    assert registry.get_agent("did:agent:1") is metadata
    assert "merid.defi.backtest.tick" in registry._capability_index
    assert "strategist" in registry._tag_index


def test_discover_agents_filters_by_capability_tag_and_reputation(registry):
    registry.register_agent(make_agent_metadata("did:agent:hi", tags=["alpha"], reputation=0.9))
    registry.register_agent(make_agent_metadata("did:agent:low", tags=["beta"], reputation=0.2))

    results = registry.discover_agents(
        capability_name="merid.defi.backtest.tick",
        tags=["alpha"],
        min_reputation=0.5,
        max_results=5,
    )

    assert len(results) == 1
    assert results[0].agent_id == "did:agent:hi"


def test_update_reputation_clamps_between_zero_and_one(registry):
    metadata = make_agent_metadata("did:agent:rep", reputation=0.4)
    registry.register_agent(metadata)

    registry.update_reputation("did:agent:rep", new_score=1.5, reason="great")
    assert registry.get_agent("did:agent:rep").reputation_score == 1.0

    registry.update_reputation("did:agent:rep", new_score=-0.5, reason="bad")
    assert registry.get_agent("did:agent:rep").reputation_score == 0.0


def test_add_trust_attestation_updates_reputation_for_trusted_issuer(registry):
    metadata = make_agent_metadata("did:agent:att", reputation=0.4)
    registry.register_agent(metadata)
    registry.add_trusted_issuer("did:issuer:trusted")

    attestation = ar.TrustAttestation(
        attestation_id="att-1",
        issuer_did="did:issuer:trusted",
        issuer_name="Trusted",
        attestation_type="security_audit",
        score=0.9,
        issued_at=datetime.utcnow(),
    )
    registry.add_trust_attestation("did:agent:att", attestation)

    expected = 0.4 * 0.7 + 0.9 * 0.3
    assert registry.get_agent("did:agent:att").reputation_score == pytest.approx(expected)


def test_verify_agent_signature_false_when_missing_signature(registry):
    metadata = make_agent_metadata("did:agent:nosig")
    metadata.signature = ""
    assert registry.verify_agent_signature(metadata) is False


def test_get_capability_versions(registry):
    registry.register_agent(make_agent_metadata("did:agent:a", capability_name="cap.one"))
    registry.register_agent(make_agent_metadata("did:agent:b", capability_name="cap.one"))

    versions = registry.get_capability_versions("cap.one")
    assert set(agent for agent, _ in versions) == {"did:agent:a", "did:agent:b"}


def test_get_registry_stats_counts_entities(registry):
    registry.register_agent(make_agent_metadata("did:agent:stats1"))
    registry.register_agent(make_agent_metadata("did:agent:stats2", tags=["ops"]))

    stats = registry.get_registry_stats()
    assert stats["total_agents"] == 2
    assert stats["total_capabilities"] == 2
    assert stats["unique_capability_names"] >= 1


def test_get_agent_registry_singleton(monkeypatch):
    monkeypatch.setattr(ar, "_agent_registry", None)
    first = ar.get_agent_registry()
    second = ar.get_agent_registry()
    assert first is second
