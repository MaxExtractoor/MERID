"""Comprehensive test suite for merid.blockchain v2 — Wallet, Contracts, Gateway, Compliance.

Covers:
§1 WalletService: action requests, policy checks, execution, audit
§2 Contracts: ContractRegistry, VaultContract, BatchRouter, BatchRoute validation
§3 BlockchainGateway: providers, caching, read/write ops, environment protection
§4 ComplianceRegistry: venue/asset allowlist, compliance checks, audit records
"""

import pytest
from datetime import datetime, timezone, timedelta
from decimal import Decimal

from merid.blockchain.wallet import (
    WalletService,
    ActionRequest,
    ActionResult,
    ActionType,
    WalletAddress,
)
from merid.blockchain.contracts import (
    ContractRegistry,
    ContractEntry,
    ContractType,
    VaultContract,
    VaultAction,
    BatchRouter,
    BatchStep,
    BatchRoute,
    build_default_contract_registry,
)
from merid.blockchain.gateway import (
    BlockchainGateway,
    RPCProvider,
    ProviderStatus,
    CachedResponse,
    BlockInfo,
    TokenBalance,
    GasEstimate,
)
from merid.blockchain.compliance import (
    ComplianceRegistry,
    VenueComplianceEntry,
    AssetComplianceEntry,
    ComplianceAuditRecord,
    VenueStatus,
    EntityClassification,
)
from merid.blockchain.execution import (
    BlockchainExecutionService,
    TxStatus,
)
from merid.blockchain.signing import SigningService
from merid.blockchain.secrets import SecretsManager


# ======================================================================
# §1 WalletService Tests
# ======================================================================

class TestActionRequest:

    def test_to_dict(self):
        req = ActionRequest(
            agent_id="arb-agent-01", action_type=ActionType.SWAP,
            chain="ethereum", asset_in="ETH", asset_out="USDC",
            amount=Decimal("1.5"),
        )
        d = req.to_dict()
        assert d["action_type"] == "swap"
        assert d["agent_id"] == "arb-agent-01"

    def test_default_dry_run(self):
        req = ActionRequest()
        assert req.dry_run is True


class TestWalletAddress:

    def test_to_dict_truncates(self):
        addr = WalletAddress(chain="ethereum", address="0x1234567890abcdef1234567890abcdef12345678")
        d = addr.to_dict()
        assert "..." in d["address"]

    def test_to_dict_short(self):
        addr = WalletAddress(chain="solana", address="short")
        d = addr.to_dict()
        assert d["address"] == "short"


class TestWalletService:

    def _build_service(self):
        exec_svc = BlockchainExecutionService()
        svc = WalletService(execution=exec_svc)
        svc.register_address(WalletAddress(
            chain="ethereum", address="0xMERID_ETH_WALLET", label="main", is_default=True,
        ))
        svc.register_address(WalletAddress(
            chain="solana", address="MERID_SOL_WALLET", label="main", is_default=True,
        ))
        return svc

    def test_register_and_get_addresses(self):
        svc = self._build_service()
        addrs = svc.get_addresses("ethereum")
        assert len(addrs) == 1
        assert addrs[0].label == "main"

    def test_get_default_address(self):
        svc = self._build_service()
        addr = svc.get_default_address("ethereum")
        assert addr is not None
        assert addr.is_default is True

    def test_get_default_address_none(self):
        svc = self._build_service()
        assert svc.get_default_address("bsc") is None

    def test_balance_management(self):
        svc = self._build_service()
        svc.set_balances("ethereum", {"ETH": Decimal("10"), "USDC": Decimal("5000")})
        balances = svc.get_balances("ethereum")
        assert balances["ETH"] == Decimal("10")

    def test_contract_whitelist(self):
        svc = self._build_service()
        assert svc.is_contract_whitelisted("ethereum", "0xE592427A0AEce92De3Edee1F18E0157C05861564")
        assert not svc.is_contract_whitelisted("ethereum", "0xUNKNOWN")

    def test_whitelist_contract(self):
        svc = self._build_service()
        svc.whitelist_contract("ethereum", "0xNEW_CONTRACT")
        assert svc.is_contract_whitelisted("ethereum", "0xNEW_CONTRACT")

    def test_policy_check_passes(self):
        svc = self._build_service()
        req = ActionRequest(chain="ethereum", action_type=ActionType.SWAP,
                            asset_in="ETH", amount=Decimal("1"))
        result = svc.check_policy(req)
        assert result.approved is True
        assert "chain_not_halted" in result.policy_checks_passed

    def test_policy_check_halted_chain(self):
        svc = self._build_service()
        svc.execution.trip_breaker("ethereum", "test halt")
        req = ActionRequest(chain="ethereum", action_type=ActionType.SWAP)
        result = svc.check_policy(req)
        assert result.approved is False
        assert any("halted" in f for f in result.policy_checks_failed)

    def test_policy_check_no_wallet(self):
        svc = self._build_service()
        req = ActionRequest(chain="bsc", action_type=ActionType.SWAP)
        result = svc.check_policy(req)
        assert result.approved is False
        assert any("No wallet" in f for f in result.policy_checks_failed)

    def test_policy_check_contract_not_whitelisted(self):
        svc = self._build_service()
        req = ActionRequest(
            chain="ethereum", action_type=ActionType.CONTRACT_CALL,
            target_contract="0xUNKNOWN_CONTRACT",
        )
        result = svc.check_policy(req)
        assert result.approved is False
        assert any("not whitelisted" in f for f in result.policy_checks_failed)

    def test_policy_check_insufficient_balance(self):
        svc = self._build_service()
        svc.set_balances("ethereum", {"ETH": Decimal("1")})
        req = ActionRequest(chain="ethereum", asset_in="ETH", amount=Decimal("5"))
        result = svc.check_policy(req)
        assert result.approved is False
        assert any("Insufficient" in f for f in result.policy_checks_failed)

    @pytest.mark.asyncio
    async def test_execute_action_dry_run(self):
        svc = self._build_service()
        req = ActionRequest(chain="ethereum", action_type=ActionType.SWAP,
                            asset_in="ETH", amount=Decimal("1"), dry_run=True)
        result = await svc.execute_action(req)
        assert result.approved is True
        assert result.tx_result.status == TxStatus.SIMULATED

    @pytest.mark.asyncio
    async def test_execute_action_live(self):
        svc = self._build_service()
        req = ActionRequest(chain="solana", action_type=ActionType.SWAP,
                            asset_in="SOL", amount=Decimal("10"), dry_run=False)
        result = await svc.execute_action(req)
        assert result.approved is True
        assert result.tx_result.status == TxStatus.CONFIRMED

    @pytest.mark.asyncio
    async def test_execute_action_policy_denied(self):
        svc = self._build_service()
        svc.execution.trip_breaker("ethereum", "test")
        req = ActionRequest(chain="ethereum", action_type=ActionType.SWAP)
        result = await svc.execute_action(req)
        assert result.approved is False

    def test_audit_log(self):
        svc = self._build_service()
        req = ActionRequest(chain="ethereum")
        svc.check_policy(req)
        log = svc.get_audit_log()
        assert len(log) >= 1

    def test_summary(self):
        svc = self._build_service()
        s = svc.summary()
        assert "ethereum" in s["chains"]

    def test_action_result_to_dict(self):
        r = ActionResult(request_id="r1", approved=True)
        d = r.to_dict()
        assert d["approved"] is True


# ======================================================================
# §2 Contract Tests
# ======================================================================

class TestContractRegistry:

    def test_register_and_get(self):
        reg = ContractRegistry()
        entry = ContractEntry(
            contract_id="test-1", chain="ethereum",
            address="0xABC", contract_type=ContractType.DEX_ROUTER,
            name="Test Router",
        )
        reg.register(entry)
        assert reg.get("test-1") is entry

    def test_by_chain(self):
        reg = build_default_contract_registry()
        eth = reg.by_chain("ethereum")
        assert len(eth) >= 2

    def test_by_type(self):
        reg = build_default_contract_registry()
        routers = reg.by_type(ContractType.DEX_ROUTER)
        assert len(routers) >= 3

    def test_by_address(self):
        reg = build_default_contract_registry()
        entry = reg.by_address("ethereum", "0xE592427A0AEce92De3Edee1F18E0157C05861564")
        assert entry is not None
        assert entry.name == "Uniswap V3 Router"

    def test_is_whitelisted(self):
        reg = build_default_contract_registry()
        assert reg.is_whitelisted("ethereum", "0xE592427A0AEce92De3Edee1F18E0157C05861564")
        assert not reg.is_whitelisted("ethereum", "0xUNKNOWN")

    def test_summary(self):
        reg = build_default_contract_registry()
        s = reg.summary()
        assert s["total_contracts"] >= 4

    def test_contract_entry_to_dict(self):
        e = ContractEntry(contract_id="c1", chain="ethereum",
                          address="0x1234567890", contract_type=ContractType.VAULT)
        d = e.to_dict()
        assert d["contract_type"] == "vault"


class TestVaultContract:

    def _build_vault(self):
        entry = ContractEntry(
            contract_id="vault-eth", chain="ethereum",
            address="0xVAULT", contract_type=ContractType.VAULT,
            name="MERID ETH Vault",
        )
        return VaultContract(entry)

    def test_deposit(self):
        vault = self._build_vault()
        action = vault.deposit("ETH", Decimal("5"))
        assert action.action_type == "deposit"
        assert action.amount == Decimal("5")

    def test_withdraw(self):
        vault = self._build_vault()
        action = vault.withdraw("USDC", Decimal("1000"))
        assert action.action_type == "withdraw"

    def test_execute_strategy(self):
        vault = self._build_vault()
        action = vault.execute_strategy("0xTARGET", "0xCALLDATA", {"max_slippage": "0.01"})
        assert action.action_type == "execute_strategy"
        assert action.target_contract == "0xTARGET"

    def test_get_actions(self):
        vault = self._build_vault()
        vault.deposit("ETH", Decimal("1"))
        vault.withdraw("ETH", Decimal("0.5"))
        assert len(vault.get_actions()) == 2

    def test_vault_action_to_dict(self):
        a = VaultAction(vault_id="v1", action_type="deposit", asset="ETH")
        d = a.to_dict()
        assert d["action_type"] == "deposit"


class TestBatchRouter:

    def _build_router(self):
        entry = ContractEntry(
            contract_id="batch-eth", chain="ethereum",
            address="0xBATCH", contract_type=ContractType.BATCH_ROUTER,
        )
        return BatchRouter(entry)

    def test_build_route(self):
        router = self._build_router()
        steps = [
            {"dex": "uniswap", "asset_in": "ETH", "asset_out": "USDC"},
            {"dex": "curve", "asset_in": "USDC", "asset_out": "DAI"},
        ]
        route = router.build_route("ethereum", steps, Decimal("1"), Decimal("0.99"))
        assert len(route.steps) == 2
        assert route.steps[0].dex == "uniswap"

    def test_route_validation_valid(self):
        route = BatchRoute(
            chain="ethereum",
            steps=[
                BatchStep(step_index=0, asset_in="ETH", asset_out="USDC"),
                BatchStep(step_index=1, asset_in="USDC", asset_out="DAI"),
            ],
            max_slippage_pct=Decimal("0.01"),
        )
        assert route.is_valid() is True

    def test_route_validation_broken_chain(self):
        route = BatchRoute(
            chain="ethereum",
            steps=[
                BatchStep(step_index=0, asset_in="ETH", asset_out="USDC"),
                BatchStep(step_index=1, asset_in="WBTC", asset_out="DAI"),
            ],
        )
        assert route.is_valid() is False

    def test_route_validation_empty(self):
        route = BatchRoute(chain="ethereum")
        assert route.is_valid() is False

    def test_route_validation_high_slippage(self):
        route = BatchRoute(
            chain="ethereum",
            steps=[BatchStep(step_index=0, asset_in="ETH", asset_out="USDC")],
            max_slippage_pct=Decimal("0.10"),
        )
        assert route.is_valid() is False

    def test_batch_route_to_dict(self):
        route = BatchRoute(chain="ethereum", total_input=Decimal("1"))
        d = route.to_dict()
        assert d["chain"] == "ethereum"

    def test_batch_step_to_dict(self):
        s = BatchStep(step_index=0, dex="uniswap", asset_in="ETH", asset_out="USDC")
        d = s.to_dict()
        assert d["dex"] == "uniswap"


# ======================================================================
# §3 BlockchainGateway Tests
# ======================================================================

class TestRPCProvider:

    def test_to_dict(self):
        p = RPCProvider(name="helius", chain="solana", url="https://rpc.helius.xyz")
        d = p.to_dict()
        assert d["name"] == "helius"
        assert d["status"] == "healthy"


class TestCachedResponse:

    def test_not_expired(self):
        c = CachedResponse(key="test", data="val", ttl_seconds=60)
        assert c.is_expired is False

    def test_expired(self):
        import time
        c = CachedResponse(key="test", data="val", cached_at=time.time() - 100, ttl_seconds=30)
        assert c.is_expired is True


class TestBlockchainGateway:

    def test_register_provider(self):
        gw = BlockchainGateway()
        gw.register_provider(RPCProvider(name="test", chain="ethereum", url="http://localhost"))
        assert gw.get_provider("ethereum") is not None

    def test_provider_priority(self):
        gw = BlockchainGateway()
        gw.register_provider(RPCProvider(name="low", chain="ethereum", url="http://a", priority=1))
        gw.register_provider(RPCProvider(name="high", chain="ethereum", url="http://b", priority=0))
        assert gw.get_provider("ethereum").name == "high"

    def test_mark_provider_down(self):
        gw = BlockchainGateway()
        gw.register_provider(RPCProvider(name="test", chain="ethereum", url="http://a"))
        gw.mark_provider_down("test")
        assert gw.get_provider("ethereum") is None

    def test_mark_provider_healthy(self):
        gw = BlockchainGateway()
        gw.register_provider(RPCProvider(name="test", chain="ethereum", url="http://a"))
        gw.mark_provider_down("test")
        gw.mark_provider_healthy("test")
        assert gw.get_provider("ethereum").name == "test"

    def test_no_provider(self):
        gw = BlockchainGateway()
        assert gw.get_provider("unknown") is None

    @pytest.mark.asyncio
    async def test_get_block(self):
        gw = BlockchainGateway()
        gw.register_provider(RPCProvider(name="test", chain="ethereum", url="http://a"))
        block = await gw.get_block("ethereum")
        assert block is not None
        assert block.chain == "ethereum"

    @pytest.mark.asyncio
    async def test_get_block_cached(self):
        gw = BlockchainGateway()
        gw.register_provider(RPCProvider(name="test", chain="ethereum", url="http://a"))
        await gw.get_block("ethereum")
        block2 = await gw.get_block("ethereum")
        assert block2 is not None
        assert gw._request_count == 1  # Second call was cached

    @pytest.mark.asyncio
    async def test_get_balance(self):
        gw = BlockchainGateway()
        gw.register_provider(RPCProvider(name="test", chain="solana", url="http://a"))
        bal = await gw.get_balance("solana", "addr123")
        assert bal is not None
        assert bal.chain == "solana"

    @pytest.mark.asyncio
    async def test_estimate_gas(self):
        gw = BlockchainGateway()
        gw.register_provider(RPCProvider(name="test", chain="ethereum", url="http://a"))
        gas = await gw.estimate_gas("ethereum")
        assert gas is not None

    @pytest.mark.asyncio
    async def test_send_blocked_in_dev(self):
        gw = BlockchainGateway(environment="dev", block_writes_in_dev=True)
        gw.register_provider(RPCProvider(name="test", chain="ethereum", url="http://a"))
        result = await gw.send_raw_transaction("ethereum", "0xSIGNED")
        assert result is None

    @pytest.mark.asyncio
    async def test_send_allowed_in_prod(self):
        gw = BlockchainGateway(environment="prod", block_writes_in_dev=True)
        gw.register_provider(RPCProvider(name="test", chain="ethereum", url="http://a"))
        result = await gw.send_raw_transaction("ethereum", "0xSIGNED")
        assert result is not None

    def test_clear_cache(self):
        gw = BlockchainGateway()
        gw._cache_set("test", "val")
        gw.clear_cache()
        assert gw._cache_get("test") is None

    def test_summary(self):
        gw = BlockchainGateway()
        s = gw.summary()
        assert s["environment"] == "dev"

    def test_block_info_to_dict(self):
        b = BlockInfo(chain="ethereum", block_number=12345)
        d = b.to_dict()
        assert d["block_number"] == 12345

    def test_token_balance_to_dict(self):
        t = TokenBalance(chain="ethereum", asset="ETH", balance=Decimal("10"))
        d = t.to_dict()
        assert d["asset"] == "ETH"

    def test_gas_estimate_to_dict(self):
        g = GasEstimate(chain="ethereum", base_fee_gwei=Decimal("30"))
        d = g.to_dict()
        assert d["chain"] == "ethereum"


# ======================================================================
# §4 ComplianceRegistry Tests
# ======================================================================

class TestVenueComplianceEntry:

    def test_to_dict(self):
        v = VenueComplianceEntry(venue="kalshi", status=VenueStatus.ALLOWED)
        d = v.to_dict()
        assert d["status"] == "allowed"


class TestAssetComplianceEntry:

    def test_to_dict(self):
        a = AssetComplianceEntry(asset="BTC", asset_type="crypto")
        d = a.to_dict()
        assert d["asset"] == "BTC"


class TestComplianceRegistry:

    def test_default_venues(self):
        from merid.blockchain.compliance import get_compliance_registry
        # Reset singleton for clean test
        import merid.blockchain.compliance as mod
        mod._registry = None
        reg = get_compliance_registry()
        assert reg.is_venue_allowed("kalshi") is True
        assert reg.is_venue_allowed("polymarket") is False
        assert reg.is_venue_allowed("coinbase") is True

    def test_venue_registration(self):
        reg = ComplianceRegistry()
        reg.register_venue(VenueComplianceEntry(venue="test_venue", status=VenueStatus.ALLOWED))
        assert reg.is_venue_allowed("test_venue") is True

    def test_unknown_venue_blocked(self):
        reg = ComplianceRegistry()
        assert reg.is_venue_allowed("unknown") is False

    def test_prohibited_venue(self):
        reg = ComplianceRegistry()
        reg.register_venue(VenueComplianceEntry(venue="bad", status=VenueStatus.PROHIBITED))
        assert reg.is_venue_allowed("bad") is False

    def test_restricted_venue_allowed(self):
        reg = ComplianceRegistry()
        reg.register_venue(VenueComplianceEntry(venue="okx", status=VenueStatus.RESTRICTED))
        assert reg.is_venue_allowed("okx") is True

    def test_asset_allowed(self):
        reg = ComplianceRegistry()
        reg.register_asset(AssetComplianceEntry(asset="BTC"))
        assert reg.is_asset_allowed("BTC") is True

    def test_asset_prohibited(self):
        reg = ComplianceRegistry()
        reg.register_asset(AssetComplianceEntry(asset="TORN", status=VenueStatus.PROHIBITED))
        assert reg.is_asset_allowed("TORN") is False

    def test_unknown_asset_allowed(self):
        reg = ComplianceRegistry()
        assert reg.is_asset_allowed("UNKNOWN_TOKEN") is True

    def test_check_trade_passes(self):
        reg = ComplianceRegistry()
        reg.register_venue(VenueComplianceEntry(venue="binance"))
        reg.register_asset(AssetComplianceEntry(asset="BTC"))
        record = reg.check_trade("binance", "BTC", agent_id="test")
        assert record.compliance_check == "passed"

    def test_check_trade_blocked_venue(self):
        reg = ComplianceRegistry()
        reg.register_venue(VenueComplianceEntry(venue="polymarket", status=VenueStatus.PROHIBITED))
        record = reg.check_trade("polymarket", "BTC")
        assert record.compliance_check == "blocked"

    def test_check_trade_blocked_asset(self):
        reg = ComplianceRegistry()
        reg.register_venue(VenueComplianceEntry(venue="binance"))
        reg.register_asset(AssetComplianceEntry(asset="TORN", status=VenueStatus.PROHIBITED))
        record = reg.check_trade("binance", "TORN")
        assert record.compliance_check == "blocked"

    def test_audit_records(self):
        reg = ComplianceRegistry()
        reg.register_venue(VenueComplianceEntry(venue="binance"))
        reg.check_trade("binance", "BTC")
        records = reg.get_audit_records()
        assert len(records) >= 1

    def test_record_event(self):
        reg = ComplianceRegistry()
        record = ComplianceAuditRecord(record_type="order", venue="binance", asset="BTC")
        reg.record_event(record)
        assert len(reg.get_audit_records()) == 1

    def test_review_overdue(self):
        reg = ComplianceRegistry()
        assert reg.review_overdue is True
        reg.mark_review_complete()
        assert reg.review_overdue is False

    def test_list_venues_by_status(self):
        reg = ComplianceRegistry()
        reg.register_venue(VenueComplianceEntry(venue="a", status=VenueStatus.ALLOWED))
        reg.register_venue(VenueComplianceEntry(venue="b", status=VenueStatus.PROHIBITED))
        allowed = reg.list_venues(VenueStatus.ALLOWED)
        assert len(allowed) == 1

    def test_classifications(self):
        reg = ComplianceRegistry()
        assert EntityClassification.PROPRIETARY_TRADER in reg.classifications
        assert EntityClassification.NOT_EXCHANGE in reg.classifications

    def test_summary(self):
        reg = ComplianceRegistry()
        reg.register_venue(VenueComplianceEntry(venue="binance"))
        s = reg.summary()
        assert s["jurisdiction"] == "US"
        assert s["venues_total"] == 1

    def test_compliance_audit_record_to_dict(self):
        r = ComplianceAuditRecord(record_type="order", venue="binance")
        d = r.to_dict()
        assert d["record_type"] == "order"
