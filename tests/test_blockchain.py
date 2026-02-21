"""Comprehensive test suite for merid.blockchain — On-chain data, execution, security.

Covers:
§1 OnChainDataService: adapters, domain objects, metrics, bias signal
§2 BlockchainExecutionService: simulation, execution, circuit breakers, positions
§3 SecretsManager: registration, RBAC, rotation, revocation, audit
§3 SigningService: policy checks, rate limiting, audit
"""

import os
import pytest
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from unittest.mock import patch

from merid.blockchain.onchain_data import (
    OnChainDataService,
    OnChainDataAdapter,
    HeliusAdapter,
    TheGraphAdapter,
    NansenAdapter,
    ExchangeFlow,
    WhaleActivity,
    ProtocolHealth,
    StablecoinMetrics,
    OnChainMetrics,
    FlowDirection,
)
from merid.blockchain.execution import (
    BlockchainExecutionService,
    TransactionRequest,
    TransactionResult,
    SimulationResult,
    RoutingPolicy,
    OnChainPosition,
    ChainCircuitBreaker,
    TxType,
    TxStatus,
)
from merid.blockchain.secrets import (
    SecretsManager,
    SecretEntry,
    KeyPermission,
    SecretEnvironment,
    AuditLogEntry,
)
from merid.blockchain.signing import (
    SigningService,
    SignRequest,
    SignResult,
    SignerBackend,
)


# ======================================================================
# §1 On-Chain Data Tests
# ======================================================================

class TestDomainObjects:

    def test_exchange_flow_to_dict(self):
        f = ExchangeFlow(chain="ethereum", exchange="binance", asset="ETH",
                         direction=FlowDirection.INFLOW, amount=Decimal("100"),
                         usd_value=Decimal("300000"))
        d = f.to_dict()
        assert d["direction"] == "inflow"
        assert d["chain"] == "ethereum"

    def test_whale_activity_to_dict(self):
        w = WhaleActivity(chain="solana", address="abc123def456",
                          label="whale", action="accumulate", asset="SOL")
        d = w.to_dict()
        assert "abc123def4..." in d["address"]

    def test_protocol_health_to_dict(self):
        p = ProtocolHealth(protocol="aave", chain="ethereum",
                           tvl_usd=Decimal("5000000000"), risk_score=0.3)
        d = p.to_dict()
        assert d["protocol"] == "aave"
        assert d["risk_score"] == 0.3

    def test_stablecoin_metrics_to_dict(self):
        s = StablecoinMetrics(asset="USDC", total_supply=Decimal("30000000000"))
        d = s.to_dict()
        assert d["asset"] == "USDC"

    def test_onchain_metrics_to_dict(self):
        m = OnChainMetrics(net_exchange_flow_usd=Decimal("500000"),
                           whale_accumulation_score=0.3, defi_risk_score=0.2)
        d = m.to_dict()
        assert d["whale_accumulation_score"] == 0.3

    def test_bias_signal_bullish(self):
        m = OnChainMetrics(
            net_exchange_flow_usd=Decimal("-2000000"),  # outflows (bullish)
            whale_accumulation_score=0.8,                # accumulating
            defi_risk_score=0.1,
        )
        assert m.bias_signal() == "bullish"

    def test_bias_signal_bearish(self):
        m = OnChainMetrics(
            net_exchange_flow_usd=Decimal("5000000"),   # inflows (bearish)
            whale_accumulation_score=-0.5,               # distributing
            defi_risk_score=0.8,
        )
        assert m.bias_signal() == "bearish"

    def test_bias_signal_neutral(self):
        m = OnChainMetrics(
            net_exchange_flow_usd=Decimal("0"),
            whale_accumulation_score=0.0,
            defi_risk_score=0.0,
        )
        assert m.bias_signal() == "neutral"


class TestOnChainAdapters:

    def test_helius_adapter_props(self):
        adapter = HeliusAdapter()
        assert adapter.provider_name == "helius"
        assert "solana" in adapter.supported_chains

    def test_the_graph_adapter_props(self):
        adapter = TheGraphAdapter()
        assert adapter.provider_name == "the_graph"
        assert "ethereum" in adapter.supported_chains

    def test_nansen_adapter_props(self):
        adapter = NansenAdapter()
        assert adapter.provider_name == "nansen"
        assert "ethereum" in adapter.supported_chains

    @pytest.mark.asyncio
    async def test_helius_exchange_flows_empty(self):
        adapter = HeliusAdapter()
        flows = await adapter.get_exchange_flows("SOL")
        assert flows == []

    @pytest.mark.asyncio
    async def test_adapter_health_check(self):
        adapter = HeliusAdapter()
        health = await adapter.health_check()
        assert health["provider"] == "helius"
        assert health["status"] == "ok"


class TestOnChainDataService:

    def test_register_and_list(self):
        svc = OnChainDataService()
        svc.register_adapter(HeliusAdapter())
        svc.register_adapter(NansenAdapter())
        assert len(svc.list_adapters()) == 2
        assert svc.get_adapter("helius") is not None

    @pytest.mark.asyncio
    async def test_get_exchange_flows_empty(self):
        svc = OnChainDataService()
        svc.register_adapter(HeliusAdapter())
        flows = await svc.get_exchange_flows("BTC")
        assert flows == []

    @pytest.mark.asyncio
    async def test_get_metrics(self):
        svc = OnChainDataService()
        svc.register_adapter(HeliusAdapter())
        metrics = await svc.get_metrics("BTC")
        assert isinstance(metrics, OnChainMetrics)
        assert metrics.net_exchange_flow_usd == Decimal("0")

    def test_summary(self):
        svc = OnChainDataService()
        svc.register_adapter(HeliusAdapter())
        s = svc.summary()
        assert len(s["adapters"]) == 1


# ======================================================================
# §2 Blockchain Execution Tests
# ======================================================================

class TestTransactionRequest:

    def test_to_dict(self):
        req = TransactionRequest(chain="ethereum", tx_type=TxType.SWAP,
                                 asset_in="ETH", asset_out="USDC",
                                 amount_in=Decimal("1.0"))
        d = req.to_dict()
        assert d["chain"] == "ethereum"
        assert d["tx_type"] == "swap"
        assert d["dry_run"] is True

    def test_default_dry_run(self):
        req = TransactionRequest()
        assert req.dry_run is True


class TestRoutingPolicy:

    def test_get_dexs(self):
        rp = RoutingPolicy()
        assert "jupiter" in rp.get_dexs("solana")
        assert "uniswap_v3" in rp.get_dexs("ethereum")
        assert rp.get_dexs("unknown_chain") == []


class TestChainCircuitBreaker:

    def test_trip_and_reset(self):
        cb = ChainCircuitBreaker(chain="ethereum")
        assert cb.tripped is False
        cb.trip("exploit detected")
        assert cb.tripped is True
        assert cb.reason == "exploit detected"
        cb.reset()
        assert cb.tripped is False


class TestBlockchainExecutionService:

    @pytest.mark.asyncio
    async def test_simulate_success(self):
        svc = BlockchainExecutionService()
        req = TransactionRequest(chain="ethereum", tx_type=TxType.SWAP,
                                 amount_in=Decimal("1.0"))
        sim = await svc.simulate(req)
        assert sim.success is True
        assert sim.expected_gas > 0

    @pytest.mark.asyncio
    async def test_simulate_halted_chain(self):
        svc = BlockchainExecutionService()
        svc.trip_breaker("ethereum", "test halt")
        req = TransactionRequest(chain="ethereum")
        sim = await svc.simulate(req)
        assert sim.success is False
        assert "halted" in sim.revert_reason

    @pytest.mark.asyncio
    async def test_execute_dry_run(self):
        svc = BlockchainExecutionService()
        req = TransactionRequest(chain="solana", dry_run=True,
                                 amount_in=Decimal("10"))
        result = await svc.execute(req)
        assert result.status == TxStatus.SIMULATED

    @pytest.mark.asyncio
    async def test_execute_live(self):
        svc = BlockchainExecutionService()
        req = TransactionRequest(chain="solana", dry_run=False,
                                 amount_in=Decimal("10"))
        result = await svc.execute(req)
        assert result.status == TxStatus.CONFIRMED
        assert result.tx_hash.startswith("0xSIM")

    @pytest.mark.asyncio
    async def test_execute_halted_chain(self):
        svc = BlockchainExecutionService()
        svc.trip_breaker("ethereum", "exploit")
        req = TransactionRequest(chain="ethereum", dry_run=False)
        result = await svc.execute(req)
        assert result.status == TxStatus.FAILED

    def test_circuit_breaker_management(self):
        svc = BlockchainExecutionService()
        assert svc.is_chain_halted("ethereum") is False
        svc.trip_breaker("ethereum", "test")
        assert svc.is_chain_halted("ethereum") is True
        svc.reset_breaker("ethereum")
        assert svc.is_chain_halted("ethereum") is False

    def test_position_tracking(self):
        svc = BlockchainExecutionService()
        pos = OnChainPosition(position_id="lp-1", chain="ethereum",
                              protocol="uniswap", position_type="lp",
                              value_usd=Decimal("5000"))
        svc.register_position(pos)
        assert len(svc.get_positions()) == 1
        assert len(svc.get_positions(chain="ethereum")) == 1
        assert len(svc.get_positions(chain="solana")) == 0

    def test_on_chain_position_to_dict(self):
        pos = OnChainPosition(position_id="lp-1", chain="ethereum")
        d = pos.to_dict()
        assert d["chain"] == "ethereum"

    def test_simulation_result_to_dict(self):
        sim = SimulationResult(request_id="r1", success=True)
        d = sim.to_dict()
        assert d["success"] is True

    def test_transaction_result_to_dict(self):
        r = TransactionResult(request_id="r1", status=TxStatus.CONFIRMED)
        d = r.to_dict()
        assert d["status"] == "confirmed"

    def test_summary(self):
        svc = BlockchainExecutionService()
        s = svc.summary()
        assert "circuit_breakers" in s
        assert "positions" in s


# ======================================================================
# §3 Secrets Manager Tests
# ======================================================================

class TestSecretEntry:

    def test_needs_rotation_new_key(self):
        entry = SecretEntry(key_id="test", venue="test", rotation_interval_days=90)
        assert entry.needs_rotation is False
        assert entry.age_days == 0

    def test_needs_rotation_old_key(self):
        old_date = datetime.now(timezone.utc) - timedelta(days=100)
        entry = SecretEntry(key_id="test", venue="test",
                            created_at=old_date, rotation_interval_days=90)
        assert entry.needs_rotation is True
        assert entry.age_days >= 100

    def test_to_dict(self):
        entry = SecretEntry(key_id="test", venue="binance",
                            permission=KeyPermission.TRADE)
        d = entry.to_dict()
        assert d["permission"] == "trade"


class TestSecretsManager:

    def test_register_and_list(self):
        sm = SecretsManager()
        sm.register_key(SecretEntry(key_id="k1", venue="binance",
                                    env_var_name="TEST_KEY"))
        assert len(sm.list_keys()) == 1
        assert sm.get_entry("k1") is not None

    def test_get_secret_not_found(self):
        sm = SecretsManager()
        val = sm.get_secret("nonexistent", service="test")
        assert val is None

    def test_get_secret_permission_denied(self):
        sm = SecretsManager()
        sm.register_key(SecretEntry(key_id="k1", venue="binance",
                                    env_var_name="TEST_KEY",
                                    permission=KeyPermission.READ_ONLY))
        val = sm.get_secret("k1", service="test",
                            required_permission=KeyPermission.SIGN)
        assert val is None

    def test_get_secret_with_env(self):
        sm = SecretsManager()
        sm.register_key(SecretEntry(key_id="k1", venue="test",
                                    env_var_name="MERID_TEST_SECRET_XYZ",
                                    permission=KeyPermission.TRADE))
        with patch.dict(os.environ, {"MERID_TEST_SECRET_XYZ": "secret123"}):
            val = sm.get_secret("k1", service="test",
                                required_permission=KeyPermission.READ_ONLY)
            assert val == "secret123"

    def test_get_secret_increments_access(self):
        sm = SecretsManager()
        sm.register_key(SecretEntry(key_id="k1", venue="test",
                                    env_var_name="MERID_TEST_SECRET_XYZ"))
        with patch.dict(os.environ, {"MERID_TEST_SECRET_XYZ": "val"}):
            sm.get_secret("k1", service="test")
            sm.get_secret("k1", service="test")
        entry = sm.get_entry("k1")
        assert entry.access_count == 2

    def test_revoke_key(self):
        sm = SecretsManager()
        sm.register_key(SecretEntry(key_id="k1", venue="test",
                                    env_var_name="X"))
        sm.revoke_key("k1", reason="compromised")
        assert sm.is_revoked("k1") is True
        with patch.dict(os.environ, {"X": "val"}):
            val = sm.get_secret("k1", service="test")
        assert val is None

    def test_rotate_key(self):
        sm = SecretsManager()
        sm.register_key(SecretEntry(key_id="k1", venue="test"))
        assert sm.rotate_key("k1") is True
        entry = sm.get_entry("k1")
        assert entry.last_rotated is not None

    def test_keys_needing_rotation(self):
        sm = SecretsManager()
        old = SecretEntry(key_id="old", venue="test",
                          created_at=datetime.now(timezone.utc) - timedelta(days=100),
                          rotation_interval_days=90)
        sm.register_key(old)
        sm.register_key(SecretEntry(key_id="new", venue="test"))
        needing = sm.keys_needing_rotation()
        assert len(needing) == 1
        assert needing[0].key_id == "old"

    def test_audit_log(self):
        sm = SecretsManager()
        sm.register_key(SecretEntry(key_id="k1", venue="test",
                                    env_var_name="X"))
        log = sm.get_audit_log()
        assert len(log) >= 1
        assert log[0].action == "register"

    def test_summary(self):
        sm = SecretsManager()
        sm.register_key(SecretEntry(key_id="k1", venue="test"))
        s = sm.summary()
        assert s["total_keys"] == 1
        assert s["environment"] == "dev"

    def test_audit_log_entry_to_dict(self):
        e = AuditLogEntry(key_id="k1", action="read", service="test")
        d = e.to_dict()
        assert d["action"] == "read"


# ======================================================================
# §3 Signing Service Tests
# ======================================================================

class TestSigningService:

    def _build_service(self, **kwargs):
        sm = SecretsManager()
        sm.register_key(SecretEntry(
            key_id="sign-key", venue="test",
            env_var_name="MERID_TEST_SIGN_KEY",
            permission=KeyPermission.SIGN,
        ))
        return SigningService(secrets=sm, **kwargs)

    @pytest.mark.asyncio
    async def test_sign_success(self):
        svc = self._build_service()
        with patch.dict(os.environ, {"MERID_TEST_SIGN_KEY": "privkey123"}):
            req = SignRequest(key_id="sign-key", payload_hash="abc123",
                              requesting_agent="test-agent",
                              requesting_service="test-svc")
            result = await svc.sign(req)
        assert result.success is True
        assert result.signature.startswith("0x")
        assert result.signer_backend == "env"

    @pytest.mark.asyncio
    async def test_sign_key_not_found(self):
        svc = self._build_service()
        req = SignRequest(key_id="nonexistent", payload_hash="abc")
        result = await svc.sign(req)
        assert result.success is False
        assert "not found" in result.error

    @pytest.mark.asyncio
    async def test_sign_revoked_key(self):
        svc = self._build_service()
        svc.secrets.revoke_key("sign-key", reason="test")
        req = SignRequest(key_id="sign-key", payload_hash="abc")
        result = await svc.sign(req)
        assert result.success is False
        assert "revoked" in result.error

    @pytest.mark.asyncio
    async def test_sign_permission_denied(self):
        sm = SecretsManager()
        sm.register_key(SecretEntry(
            key_id="read-key", venue="test",
            env_var_name="X",
            permission=KeyPermission.READ_ONLY,
        ))
        svc = SigningService(secrets=sm)
        with patch.dict(os.environ, {"X": "val"}):
            req = SignRequest(key_id="read-key", payload_hash="abc")
            result = await svc.sign(req)
        assert result.success is False

    @pytest.mark.asyncio
    async def test_sign_service_allowlist(self):
        svc = self._build_service(allowed_services=["allowed-svc"])
        req = SignRequest(key_id="sign-key", payload_hash="abc",
                          requesting_service="blocked-svc")
        result = await svc.sign(req)
        assert result.success is False
        assert "allowlist" in result.error

    @pytest.mark.asyncio
    async def test_sign_rate_limit(self):
        svc = self._build_service(max_signs_per_minute=2)
        with patch.dict(os.environ, {"MERID_TEST_SIGN_KEY": "key"}):
            for _ in range(2):
                req = SignRequest(key_id="sign-key", payload_hash="abc",
                                  requesting_service="svc")
                await svc.sign(req)
            # Third should be rate limited
            req = SignRequest(key_id="sign-key", payload_hash="abc",
                              requesting_service="svc")
            result = await svc.sign(req)
        assert result.success is False
        assert "Rate limit" in result.error

    def test_sign_log(self):
        svc = self._build_service()
        assert svc.get_sign_log() == []

    def test_summary(self):
        svc = self._build_service()
        s = svc.summary()
        assert s["backend"] == "env"
        assert s["total_signs"] == 0

    def test_sign_request_to_dict(self):
        r = SignRequest(key_id="k1", payload_hash="abc123def4567890extra")
        d = r.to_dict()
        assert "..." in d["payload_hash"]

    def test_sign_result_to_dict(self):
        r = SignResult(request_id="r1", success=True, signature="0xabcdef1234567890")
        d = r.to_dict()
        assert d["success"] is True
