/**
 * Deploy All MERID Contracts
 * 
 * Deploys:
 * - SwarmGovernance
 * - AgentPermissions
 * - PassiveIncomeVault
 * - SovereignDEX
 * - HFTSwarmController
 */

import { ethers } from "hardhat";

async function main() {
    const [deployer] = await ethers.getSigners();
    console.log("Deploying contracts with account:", deployer.address);
    console.log("Account balance:", (await deployer.getBalance()).toString());

    // Deploy SwarmGovernance
    console.log("\n--- Deploying SwarmGovernance ---");
    const SwarmGovernance = await ethers.getContractFactory("SwarmGovernance");
    const governance = await SwarmGovernance.deploy();
    await governance.deployed();
    console.log("SwarmGovernance deployed to:", governance.address);

    // Deploy AgentPermissions
    console.log("\n--- Deploying AgentPermissions ---");
    const AgentPermissions = await ethers.getContractFactory("AgentPermissions");
    const permissions = await AgentPermissions.deploy();
    await permissions.deployed();
    console.log("AgentPermissions deployed to:", permissions.address);

    // Deploy PassiveIncomeVault (using a mock token for testing)
    console.log("\n--- Deploying PassiveIncomeVault ---");
    // In production, use actual deposit token address
    const mockTokenAddress = "0x0000000000000000000000000000000000000001"; // Placeholder
    const PassiveIncomeVault = await ethers.getContractFactory("PassiveIncomeVault");
    const vault = await PassiveIncomeVault.deploy(mockTokenAddress);
    await vault.deployed();
    console.log("PassiveIncomeVault deployed to:", vault.address);

    // Deploy SovereignDEX
    console.log("\n--- Deploying SovereignDEX ---");
    const SovereignDEX = await ethers.getContractFactory("SovereignDEX");
    const dex = await SovereignDEX.deploy();
    await dex.deployed();
    console.log("SovereignDEX deployed to:", dex.address);

    // Deploy HFTSwarmController
    console.log("\n--- Deploying HFTSwarmController ---");
    const HFTSwarmController = await ethers.getContractFactory("HFTSwarmController");
    const hftController = await HFTSwarmController.deploy();
    await hftController.deployed();
    console.log("HFTSwarmController deployed to:", hftController.address);

    // Summary
    console.log("\n========================================");
    console.log("DEPLOYMENT SUMMARY");
    console.log("========================================");
    console.log("SwarmGovernance:", governance.address);
    console.log("AgentPermissions:", permissions.address);
    console.log("PassiveIncomeVault:", vault.address);
    console.log("SovereignDEX:", dex.address);
    console.log("HFTSwarmController:", hftController.address);
    console.log("========================================");

    // Verify contracts on block explorer (if not local)
    const network = await ethers.provider.getNetwork();
    if (network.chainId !== 31337) { // Not hardhat local
        console.log("\nVerifying contracts on block explorer...");
        
        try {
            await run("verify:verify", {
                address: governance.address,
                constructorArguments: [],
            });
        } catch (e) {
            console.log("SwarmGovernance verification:", e.message);
        }

        try {
            await run("verify:verify", {
                address: permissions.address,
                constructorArguments: [],
            });
        } catch (e) {
            console.log("AgentPermissions verification:", e.message);
        }

        try {
            await run("verify:verify", {
                address: vault.address,
                constructorArguments: [mockTokenAddress],
            });
        } catch (e) {
            console.log("PassiveIncomeVault verification:", e.message);
        }

        try {
            await run("verify:verify", {
                address: dex.address,
                constructorArguments: [],
            });
        } catch (e) {
            console.log("SovereignDEX verification:", e.message);
        }

        try {
            await run("verify:verify", {
                address: hftController.address,
                constructorArguments: [],
            });
        } catch (e) {
            console.log("HFTSwarmController verification:", e.message);
        }
    }

    return {
        governance: governance.address,
        permissions: permissions.address,
        vault: vault.address,
        dex: dex.address,
        hftController: hftController.address,
    };
}

main()
    .then((addresses) => {
        console.log("\nDeployment complete!");
        process.exit(0);
    })
    .catch((error) => {
        console.error(error);
        process.exit(1);
    });
