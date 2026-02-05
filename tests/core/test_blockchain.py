"""Tests for MERID blockchain modules."""

import pytest
from decimal import Decimal
from unittest.mock import Mock, AsyncMock, patch, MagicMock
import asyncio


class TestTokenPair:
    """Tests for TokenPair dataclass."""
    
    def test_token_pair_creation(self):
        from core.blockchain_dex import TokenPair
        
        pair = TokenPair(
            base_token="0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
            quote_token="0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
            base_symbol="WETH",
            quote_symbol="USDC",
            decimals=18
        )
        
        assert pair.base_symbol == "WETH"
        assert pair.quote_symbol == "USDC"
        assert pair.decimals == 18


class TestDEXManager:
    """Tests for DEXManager."""
    
    @pytest.fixture
    def mock_w3(self):
        """Create mock Web3 instance."""
        with patch('core.blockchain_dex.Web3') as MockWeb3:
            mock_w3 = MagicMock()
            mock_w3.eth.gas_price = 20000000000
            mock_w3.to_wei = Mock(return_value=1000000000000000000)
            mock_w3.from_wei = Mock(return_value=1.0)
            MockWeb3.HTTPProvider.return_value = Mock()
            MockWeb3.return_value = mock_w3
            MockWeb3.to_checksum_address = Mock(return_value="0xMockAddress")
            yield mock_w3
    
    def test_dex_manager_initialization(self, mock_w3):
        from core.blockchain_dex import DEXManager
        
        with patch.dict('os.environ', {'ETH_RPC_URL': 'https://test.rpc'}):
            manager = DEXManager(chain="ethereum")
            
            assert manager.chain == "ethereum"
            assert manager.config["router"] == "0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D"
    
    def test_get_token_balance(self, mock_w3):
        from core.blockchain_dex import DEXManager
        
        # Mock token contract
        mock_contract = MagicMock()
        mock_contract.functions.balanceOf.return_value.call.return_value = 1000000000000000000
        mock_contract.functions.decimals.return_value.call.return_value = 18
        
        with patch.dict('os.environ', {'ETH_RPC_URL': 'https://test.rpc'}):
            with patch.object(DEXManager, 'get_token_contract', return_value=mock_contract):
                manager = DEXManager(chain="ethereum")
                balance = manager.get_token_balance(
                    "0xTokenAddress",
                    "0xWalletAddress"
                )
                
                assert balance == Decimal("1.0")


class TestSolanaManager:
    """Tests for SolanaManager."""
    
    @pytest.fixture
    def solana_manager(self):
        from core.blockchain_solana import SolanaManager
        return SolanaManager(rpc_url="https://api.devnet.solana.com")
    
    @pytest.mark.asyncio
    async def test_get_balance(self, solana_manager):
        """Test SOL balance fetching."""
        # Mock the async client
        mock_response = MagicMock()
        mock_response.value = 1000000000  # 1 SOL in lamports
        
        with patch.object(solana_manager.client, 'get_balance', new=AsyncMock(return_value=mock_response)):
            balance = await solana_manager.get_balance("So11111111111111111111111111111111111111112")
            
            assert balance == Decimal("1.0")
    
    def test_known_tokens(self):
        from core.blockchain_solana import SolanaManager
        
        sol_token = SolanaManager.KNOWN_TOKENS["SOL"]
        assert sol_token.symbol == "SOL"
        assert sol_token.decimals == 9
        
        usdc_token = SolanaManager.KNOWN_TOKENS["USDC"]
        assert usdc_token.symbol == "USDC"
        assert usdc_token.decimals == 6


class TestHDWalletManager:
    """Tests for HDWalletManager."""
    
    @pytest.fixture
    def hd_manager(self):
        from core.blockchain_wallet import HDWalletManager
        return HDWalletManager()
    
    def test_mnemonic_generation(self, hd_manager):
        """Test that mnemonic is generated."""
        assert hd_manager.mnemonic is not None
        assert len(hd_manager.mnemonic.split()) == 12
    
    def test_eth_address_derivation(self, hd_manager):
        """Test Ethereum address derivation."""
        address = hd_manager.get_eth_address(0)
        
        assert address.startswith("0x")
        assert len(address) == 42
    
    def test_sol_address_derivation(self, hd_manager):
        """Test Solana address derivation."""
        address = hd_manager.get_sol_address(0)
        
        # Solana addresses are base58 encoded
        assert len(address) >= 32
    
    def test_multiple_derivations(self, hd_manager):
        """Test deriving multiple addresses."""
        addresses = hd_manager.derive_multiple_accounts("eth", 5)
        
        assert len(addresses) == 5
        # Addresses should be unique
        assert len(set(addresses)) == 5


class TestMultiChainWalletManager:
    """Tests for MultiChainWalletManager."""
    
    @pytest.fixture
    def wallet_manager(self):
        from core.blockchain_wallet import MultiChainWalletManager
        return MultiChainWalletManager()
    
    def test_create_hd_wallet(self, wallet_manager):
        """Test HD wallet creation."""
        wallet_id = wallet_manager.create_hd_wallet("test_wallet")
        
        assert wallet_id.startswith("hd_test_wallet_")
        assert wallet_id in wallet_manager.hd_managers
    
    def test_import_eth_wallet(self, wallet_manager):
        """Test Ethereum wallet import."""
        # Generate a test key
        from eth_account import Account
        acct = Account.create()
        
        wallet_id = wallet_manager.import_eth_wallet("imported", acct.key.hex())
        
        assert wallet_id.startswith("imported_eth_imported_")
        assert wallet_id in wallet_manager.imported_wallets
    
    def test_get_wallet_addresses(self, wallet_manager):
        """Test getting wallet addresses."""
        wallet_id = wallet_manager.create_hd_wallet("test")
        addresses = wallet_manager.get_wallet_addresses(wallet_id)
        
        assert "eth" in addresses
        assert "sol" in addresses
        assert len(addresses["eth"]) == 1
        assert len(addresses["sol"]) == 1
    
    def test_list_wallets(self, wallet_manager):
        """Test listing wallets."""
        wallet_manager.create_hd_wallet("wallet1")
        wallet_manager.create_hd_wallet("wallet2")
        
        wallets = wallet_manager.list_wallets()
        
        assert len(wallets) == 2


class TestArbitrageDetector:
    """Tests for ArbitrageDetector."""
    
    @pytest.fixture
    def mock_dex_manager(self):
        mock = MagicMock()
        mock.get_manager.return_value = MagicMock()
        return mock
    
    def test_arbitrage_detector_initialization(self, mock_dex_manager):
        from core.blockchain_arbitrage import ArbitrageDetector
        
        detector = ArbitrageDetector(mock_dex_manager)
        
        assert detector.dex == mock_dex_manager
        assert detector.min_profit_percent == Decimal("0.005")


class TestArbitrageOpportunity:
    """Tests for ArbitrageOpportunity dataclass."""
    
    def test_opportunity_profitable(self):
        from core.blockchain_arbitrage import ArbitrageOpportunity
        from datetime import datetime
        
        opp = ArbitrageOpportunity(
            opportunity_id="test_1",
            token_symbol="TEST",
            buy_chain="ethereum",
            sell_chain="cronos",
            buy_price=Decimal("1.00"),
            sell_price=Decimal("1.02"),
            profit_percent=Decimal("0.02"),
            max_trade_size=Decimal("1000"),
            estimated_gas_cost=Decimal("5.00"),
            net_profit=Decimal("15.00"),
            confidence=0.85,
            ttl_seconds=60,
            timestamp=datetime.now()
        )
        
        assert opp.is_profitable() is True
    
    def test_opportunity_not_profitable(self):
        from core.blockchain_arbitrage import ArbitrageOpportunity
        from datetime import datetime
        
        opp = ArbitrageOpportunity(
            opportunity_id="test_2",
            token_symbol="TEST",
            buy_chain="ethereum",
            sell_chain="cronos",
            buy_price=Decimal("1.00"),
            sell_price=Decimal("1.001"),
            profit_percent=Decimal("0.001"),
            max_trade_size=Decimal("1000"),
            estimated_gas_cost=Decimal("5.00"),
            net_profit=Decimal("-4.00"),
            confidence=0.85,
            ttl_seconds=60,
            timestamp=datetime.now()
        )
        
        assert opp.is_profitable() is False


class TestBlockchainArbitrageAgent:
    """Tests for BlockchainArbitrageAgent."""
    
    @pytest.fixture
    def mock_components(self):
        return {
            'dex': MagicMock(),
            'wallets': MagicMock(),
            'solana': MagicMock()
        }
    
    def test_agent_initialization(self, mock_components):
        from core.blockchain_arbitrage import BlockchainArbitrageAgent
        
        agent = BlockchainArbitrageAgent(
            mock_components['dex'],
            mock_components['wallets'],
            mock_components['solana']
        )
        
        assert agent.is_scanning is False
        assert len(agent.opportunities) == 0


class TestSolanaToken:
    """Tests for SolanaToken dataclass."""
    
    def test_token_creation(self):
        from core.blockchain_solana import SolanaToken
        
        token = SolanaToken(
            mint="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            symbol="USDC",
            name="USD Coin",
            decimals=6
        )
        
        assert token.symbol == "USDC"
        assert token.decimals == 6
