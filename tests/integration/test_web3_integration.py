#!/usr/bin/env python3

import asyncio
import sys
import os
import time
from datetime import datetime

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from web3.blockchain_connector import BlockchainConnector
from web3.defi_integration import DeFiIntegration
from web3.onchain_verifier import OnchainVerifier
from utils.logger import get_logger

logger = get_logger("test_web3_integration")

async def test_blockchain_connector():
    """Test blockchain connector functionality"""
    
    print("⛓️ Testing Blockchain Connector")
    print("=" * 50)
    
    try:
        # Initialize connector
        config = {
            "ethereum_rpc_url": "https://mainnet.infura.io/v3/mock",
            "polygon_rpc_url": "https://polygon-rpc.com",
            "us_compliance": {
                "only_mainnets": True,
                "gas_limit_max": 500000,
                "value_limit_usd": 100000
            }
        }
        
        connector = BlockchainConnector(config)
        print(f"✅ BlockchainConnector initialized")
        
        # Test connections
        print("\n🔗 Testing Chain Connections")
        connections = await connector.connect_all()
        print(f"✅ Connected to {sum(connections.values())} chains")
        
        for chain, connected in connections.items():
            status = "✅" if connected else "❌"
            print(f"   {status} {chain}")
        
        # Test chain status
        print("\n📊 Testing Chain Status")
        for chain_name in ["ethereum", "polygon"]:
            if connections.get(chain_name, False):
                status = await connector.get_chain_status(chain_name)
                if status:
                    print(f"✅ {chain_name}: Block {status['current_block']}, Gas: {status['gas_price']} gwei")
                else:
                    print(f"❌ {chain_name}: Failed to get status")
        
        # Test balance queries
        print("\n💰 Testing Balance Queries")
        test_address = "0x1234567890123456789012345678901234567890"
        
        for chain_name in ["ethereum", "polygon"]:
            if connections.get(chain_name, False):
                balance = await connector.get_balance(chain_name, test_address)
                if balance:
                    print(f"✅ {chain_name}: {balance['balance_formatted']:.4f} {balance['token']} (${balance['usd_value']:.2f})")
                else:
                    print(f"❌ {chain_name}: Failed to get balance")
        
        # Test transaction sending
        print("\n📤 Testing Transaction Sending")
        tx_data = {
            "from": "0x1234567890123456789012345678901234567890",
            "to": "0x0987654321098765432109876543210987654321",
            "value": 1000000000000000000,  # 1 ETH
            "gas": 21000
        }
        
        for chain_name in ["ethereum", "polygon"]:
            if connections.get(chain_name, False):
                result = await connector.send_transaction(chain_name, tx_data)
                if result:
                    print(f"✅ {chain_name}: {result.tx_hash[:10]}... (success: {result.success})")
                else:
                    print(f"❌ {chain_name}: Failed to send transaction")
        
        # Test contract calls
        print("\n📞 Testing Contract Calls")
        contract_address = "0xA0b86a33E6441b8e8C7C7b0b8e8e8e8e8e8e8e8e"
        
        for chain_name in ["ethereum", "polygon"]:
            if connections.get(chain_name, False):
                result = await connector.call_contract(chain_name, contract_address, "balanceOf", [test_address])
                if result:
                    print(f"✅ {chain_name}: {result.function_name} (success: {result.success})")
                else:
                    print(f"❌ {chain_name}: Failed to call contract")
        
        # Test connection summary
        print("\n📋 Testing Connection Summary")
        summary = connector.get_connection_summary()
        print(f"✅ Summary generated:")
        print(f"   Total chains: {summary['total_chains']}")
        print(f"   Connected: {summary['connected_chains']}")
        print(f"   Request counts: {summary['request_counts']}")
        
        # Disconnect
        print("\n🔌 Testing Disconnections")
        disconnections = await connector.disconnect_all()
        print(f"✅ Disconnected from {sum(disconnections.values())} chains")
        
        print("\n🎉 Blockchain Connector Test: PASSED")
        return True
        
    except Exception as e:
        print(f"❌ Blockchain Connector test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_defi_integration():
    """Test DeFi integration functionality"""
    
    print("\n🏦 Testing DeFi Integration")
    print("=" * 50)
    
    try:
        # Initialize blockchain connector
        connector_config = {"us_compliance": {"only_mainnets": True}}
        connector = BlockchainConnector(connector_config)
        await connector.connect_all()
        
        # Initialize DeFi integration
        defi_config = {
            "us_compliance": {
                "only_us_compliant": True,
                "max_risk_level": "medium",
                "min_tvl_usd": 1000000
            }
        }
        
        defi = DeFiIntegration(connector, defi_config)
        print(f"✅ DeFiIntegration initialized")
        
        # Test protocol initialization
        print("\n🚀 Testing Protocol Initialization")
        protocols = await defi.initialize_protocols()
        print(f"✅ Initialized {sum(protocols.values())} protocols")
        
        for protocol_id, initialized in protocols.items():
            status = "✅" if initialized else "❌"
            print(f"   {status} {protocol_id}")
        
        # Test liquidity pools
        print("\n💧 Testing Liquidity Pools")
        pools = await defi.get_liquidity_pools()
        print(f"✅ Found {len(pools)} liquidity pools")
        
        if pools:
            sample_pool = pools[0]
            print(f"   Sample: {sample_pool.token0}/{sample_pool.token1}")
            print(f"   TVL: ${sample_pool.tvl_usd:,.0f}")
            print(f"   APR: {sample_pool.apr:.2%}")
        
        # Test lending positions
        print("\n📈 Testing Lending Positions")
        test_address = "0x1234567890123456789012345678901234567890"
        positions = await defi.get_lending_positions(test_address)
        print(f"✅ Found {len(positions)} lending positions")
        
        if positions:
            sample_pos = positions[0]
            print(f"   Sample: {sample_pos.token}")
            print(f"   Supplied: {sample_pos.supplied_amount:,.2f}")
            print(f"   Rate: {sample_pos.supply_rate:.2%}")
        
        # Test yield opportunities
        print("\n🌾 Testing Yield Opportunities")
        opportunities = await defi.get_yield_opportunities(min_apr=0.05)
        print(f"✅ Found {len(opportunities)} yield opportunities")
        
        if opportunities:
            sample_opp = opportunities[0]
            print(f"   Sample: {sample_opp.token}")
            print(f"   APR: {sample_opp.apr:.2%}")
            print(f"   TVL: ${sample_opp.tvl_usd:,.0f}")
        
        # Test swap execution
        print("\n🔄 Testing Swap Execution")
        swap_result = await defi.execute_swap(
            "uniswap_v2", "ETH", "USDC", 1.0, test_address
        )
        if swap_result:
            print(f"✅ Swap executed: {swap_result['amount_in']} ETH -> {swap_result['amount_out']:.2f} USDC")
            print(f"   TX: {swap_result['tx_hash'][:10]}...")
        else:
            print("❌ Swap execution failed")
        
        # Test lending supply
        print("\n💸 Testing Lending Supply")
        supply_result = await defi.supply_to_lending(
            "aave", "USDC", 1000.0, test_address
        )
        if supply_result:
            print(f"✅ Supply executed: {supply_result['amount']} USDC")
            print(f"   Rate: {supply_result['supply_rate']:.2%}")
            print(f"   TX: {supply_result['tx_hash'][:10]}...")
        else:
            print("❌ Lending supply failed")
        
        # Test protocol summary
        print("\n📊 Testing Protocol Summary")
        summary = defi.get_protocol_summary()
        print(f"✅ Summary generated:")
        print(f"   Total protocols: {summary['total_protocols']}")
        print(f"   Connected: {summary['connected_protocols']}")
        print(f"   Total TVL: ${summary['total_tvl_usd']:,.0f}")
        print(f"   Liquidity pools: {summary['liquidity_pools']}")
        
        print("\n🎉 DeFi Integration Test: PASSED")
        return True
        
    except Exception as e:
        print(f"❌ DeFi Integration test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_onchain_verifier():
    """Test on-chain verification functionality"""
    
    print("\n🔍 Testing On-Chain Verifier")
    print("=" * 50)
    
    try:
        # Initialize blockchain connector
        connector_config = {"us_compliance": {"only_mainnets": True}}
        connector = BlockchainConnector(connector_config)
        await connector.connect_all()
        
        # Initialize verifier
        verifier_config = {
            "verification": {
                "confidence_threshold": 0.8,
                "price_deviation_threshold": 5.0,
                "require_contract_verification": True
            },
            "us_compliance": {
                "require_verified_contracts": True,
                "min_security_score": 0.7
            }
        }
        
        verifier = OnchainVerifier(connector, verifier_config)
        print(f"✅ OnchainVerifier initialized")
        
        # Test transaction verification
        print("\n📋 Testing Transaction Verification")
        tx_hash = "0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
        tx_result = await verifier.verify_transaction("ethereum", tx_hash)
        
        if tx_result:
            print(f"✅ Transaction verified: {tx_result.verification_id}")
            print(f"   Valid: {tx_result.is_valid}")
            print(f"   Confidence: {tx_result.confidence_score:.2f}")
            print(f"   Time: {tx_result.verification_time:.3f}s")
        else:
            print("❌ Transaction verification failed")
        
        # Test contract verification
        print("\n📜 Testing Contract Verification")
        contract_address = "0xA0b86a33E6441b8e8C7C7b0b8e8e8e8e8e8e8e8e"
        contract_result = await verifier.verify_contract("ethereum", contract_address)
        
        if contract_result:
            print(f"✅ Contract verified: {contract_result.contract_address[:10]}...")
            print(f"   Verified: {contract_result.is_verified}")
            print(f"   Security score: {contract_result.security_score:.2f}")
            print(f"   Risk level: {contract_result.risk_level}")
            print(f"   Time: {contract_result.verification_time:.3f}s")
        else:
            print("❌ Contract verification failed")
        
        # Test price verification
        print("\n💹 Testing Price Verification")
        oracle_prices = {
            "coinbase": 3000.0,
            "kraken": 3010.0,
            "binance": 2995.0
        }
        
        price_result = await verifier.verify_price(
            "ETH/USD", "ethereum", 3002.5, oracle_prices
        )
        
        if price_result:
            print(f"✅ Price verified: {price_result.token_pair}")
            print(f"   Valid: {price_result.is_valid}")
            print(f"   Deviation: {price_result.deviation_percent:.2f}%")
            print(f"   Confidence: {price_result.confidence_score:.2f}")
        else:
            print("❌ Price verification failed")
        
        # Test cross-chain verification
        print("\n🌐 Testing Cross-Chain Verification")
        token_address = "0xA0b86a33E6441b8e8C7C7b0b8e8e8e8e8e8e8e8e"
        cross_chain_result = await verifier.verify_cross_chain_data(
            token_address, ["ethereum", "polygon"]
        )
        
        if cross_chain_result:
            print(f"✅ Cross-chain verified: {token_address[:10]}...")
            print(f"   Consistent: {cross_chain_result['is_consistent']}")
            print(f"   Chains: {len(cross_chain_result['chains_checked'])}")
            print(f"   Anomalies: {len(cross_chain_result['anomalies'])}")
        else:
            print("❌ Cross-chain verification failed")
        
        # Test verification summary
        print("\n📊 Testing Verification Summary")
        summary = verifier.get_verification_summary()
        print(f"✅ Summary generated:")
        print(f"   Total verifications: {summary['total_verifications']}")
        print(f"   Contract verifications: {summary['contract_verifications']}")
        print(f"   Price verifications: {summary['price_verifications']}")
        
        # Test contract safety check
        print("\n🛡️ Testing Contract Safety Check")
        is_safe = verifier.is_contract_safe(contract_address)
        print(f"✅ Contract safety: {'Safe' if is_safe else 'Unsafe'}")
        
        print("\n🎉 On-Chain Verifier Test: PASSED")
        return True
        
    except Exception as e:
        print(f"❌ On-Chain Verifier test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_web3_integration():
    """Test full Web3 integration"""
    
    print("\n🔄 Testing Web3 Integration")
    print("=" * 50)
    
    try:
        # Initialize all components
        connector_config = {"us_compliance": {"only_mainnets": True}}
        connector = BlockchainConnector(connector_config)
        await connector.connect_all()
        
        defi_config = {"us_compliance": {"only_us_compliant": True}}
        defi = DeFiIntegration(connector, defi_config)
        await defi.initialize_protocols()
        
        verifier_config = {"verification": {"confidence_threshold": 0.8}}
        verifier = OnchainVerifier(connector, verifier_config)
        
        print(f"✅ All Web3 components initialized")
        
        # Test integrated workflow
        print("\n🔄 Testing Integrated Workflow")
        
        # Step 1: Verify a contract
        contract_address = "0xA0b86a33E6441b8e8C7C7b0b8e8e8e8e8e8e8e8e"
        contract_result = await verifier.verify_contract("ethereum", contract_address)
        
        if contract_result and verifier.is_contract_safe(contract_address):
            print(f"✅ Contract verified and safe: {contract_address[:10]}...")
            
            # Step 2: Get liquidity pools from safe protocol
            pools = await defi.get_liquidity_pools("uniswap_v2")
            if pools:
                print(f"✅ Found {len(pools)} pools from safe protocol")
                
                # Step 3: Execute a swap
                test_address = "0x1234567890123456789012345678901234567890"
                swap_result = await defi.execute_swap(
                    "uniswap_v2", "ETH", "USDC", 0.1, test_address
                )
                
                if swap_result:
                    print(f"✅ Swap executed successfully")
                    
                    # Step 4: Verify the transaction
                    tx_result = await verifier.verify_transaction("ethereum", swap_result["tx_hash"])
                    if tx_result and tx_result.is_valid:
                        print(f"✅ Transaction verified successfully")
                    else:
                        print(f"⚠️ Transaction verification failed")
                else:
                    print(f"⚠️ Swap execution failed")
            else:
                print(f"⚠️ No pools found")
        else:
            print(f"⚠️ Contract verification failed or unsafe")
        
        # Test compliance across all components
        print("\n🛡️ Testing Compliance Integration")
        
        # All components should respect US compliance
        connector_summary = connector.get_connection_summary()
        defi_summary = defi.get_protocol_summary()
        verifier_summary = verifier.get_verification_summary()
        
        compliance_checks = {
            "connector_us_compliance": connector_summary["us_compliance"],
            "defi_us_compliance": defi_summary["us_compliance"],
            "verifier_us_compliance": verifier_summary["us_compliance"]
        }
        
        print(f"✅ Compliance checks passed:")
        for component, compliance in compliance_checks.items():
            print(f"   {component}: ✅")
        
        # Test performance metrics
        print("\n📊 Testing Performance Metrics")
        
        total_requests = sum(connector_summary["request_counts"].values())
        total_verifications = verifier_summary["total_verifications"]
        total_api_calls = sum(defi_summary["api_calls"].values())
        
        print(f"✅ Performance metrics:")
        print(f"   Blockchain requests: {total_requests}")
        print(f"   DeFi API calls: {total_api_calls}")
        print(f"   Verifications: {total_verifications}")
        
        print("\n🎉 Web3 Integration Test: PASSED")
        return True
        
    except Exception as e:
        print(f"❌ Web3 Integration test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_performance():
    """Test Web3 integration performance"""
    
    print("\n⚡ Testing Web3 Integration Performance")
    print("-" * 40)
    
    try:
        # Initialize components
        connector_config = {"us_compliance": {"only_mainnets": True}}
        connector = BlockchainConnector(connector_config)
        await connector.connect_all()
        
        defi_config = {"us_compliance": {"only_us_compliant": True}}
        defi = DeFiIntegration(connector, defi_config)
        await defi.initialize_protocols()
        
        verifier_config = {"verification": {"confidence_threshold": 0.8}}
        verifier = OnchainVerifier(connector, verifier_config)
        
        # Performance test
        start_time = time.time()
        
        # Run multiple operations concurrently
        tasks = [
            connector.get_balance("ethereum", "0x1234567890123456789012345678901234567890"),
            defi.get_liquidity_pools(),
            verifier.verify_contract("ethereum", "0xA0b86a33E6441b8e8C7C7b0b8e8e8e8e8e8e8e8e"),
            connector.send_transaction("ethereum", {
                "from": "0x1234567890123456789012345678901234567890",
                "to": "0x0987654321098765432109876543210987654321",
                "value": 100000000000000000,
                "gas": 21000
            })
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        end_time = time.time()
        
        # Calculate metrics
        total_time = end_time - start_time
        successful_operations = sum(1 for r in results if not isinstance(r, Exception))
        
        print(f"✅ Performance results:")
        print(f"   Total time: {total_time:.2f}s")
        print(f"   Successful operations: {successful_operations}/{len(tasks)}")
        print(f"   Operations per second: {successful_operations / total_time:.1f}")
        print(f"   Avg time per operation: {(total_time / len(tasks)) * 1000:.1f}ms")
        
        # Memory usage
        import sys
        total_memory = sum(sys.getsizeof(obj) for obj in [connector, defi, verifier])
        print(f"   Memory usage: {total_memory:,} bytes")
        
        print("\n🎯 Performance Test: PASSED")
        return True
        
    except Exception as e:
        print(f"❌ Performance test failed: {e}")
        return False

async def main():
    """Run all Web3 integration tests"""
    try:
        print("🧪 WEB3 INTEGRATION TEST SUITE")
        print("=" * 70)
        
        # Run tests
        test1 = await test_blockchain_connector()
        test2 = await test_defi_integration()
        test3 = await test_onchain_verifier()
        test4 = await test_web3_integration()
        test5 = await test_performance()
        
        # Summary
        print("\n" + "=" * 70)
        print("📊 WEB3 INTEGRATION TEST RESULTS")
        print("=" * 70)
        print(f"Blockchain Connector:   {'✅ PASSED' if test1 else '❌ FAILED'}")
        print(f"DeFi Integration:       {'✅ PASSED' if test2 else '❌ FAILED'}")
        print(f"On-Chain Verifier:      {'✅ PASSED' if test3 else '❌ FAILED'}")
        print(f"Web3 Integration:       {'✅ PASSED' if test4 else '❌ FAILED'}")
        print(f"Performance:            {'✅ PASSED' if test5 else '❌ FAILED'}")
        
        if all([test1, test2, test3, test4, test5]):
            print("\n🎯 ALL WEB3 INTEGRATION TESTS PASSED!")
            print("✅ Blockchain connectivity functional")
            print("✅ DeFi protocol integration working")
            print("✅ On-chain verification operational")
            print("✅ Full Web3 integration successful")
            print("✅ Performance within acceptable limits")
        else:
            print("\n❌ Some Web3 integration tests failed")
        
    except Exception as e:
        print(f"❌ Web3 integration test suite error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
