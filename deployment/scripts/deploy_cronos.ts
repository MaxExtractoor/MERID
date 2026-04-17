import { ethers } from "hardhat";
import * as fs from "fs";
import * as path from "path";

interface DeploymentRecord {
  network: string;
  chainId: number;
  contracts: {
    [name: string]: {
      address: string;
      deploymentTx: string;
      deploymentBlock: number;
      gasUsed: number;
      deployer: string;
      timestamp: number;
    };
  };
}

async function main() {
  const [deployer] = await ethers.getSigners();
  const network = await ethers.provider.getNetwork();
  
  console.log("=".repeat(60));
  console.log("MERID Cronos Deployment");
  console.log("=".repeat(60));
  console.log(`Network: ${network.name}`);
  console.log(`Chain ID: ${network.chainId}`);
  console.log(`Deployer: ${deployer.address}`);
  console.log(`Balance: ${ethers.formatEther(await ethers.provider.getBalance(deployer.address))} ${getGasToken(network.chainId)}`);
  console.log("=".repeat(60));
  
  const deploymentRecord: DeploymentRecord = {
    network: network.name,
    chainId: Number(network.chainId),
    contracts: {},
  };
  
  // Deploy MERID Token (ERC-20)
  console.log("\n1. Deploying MERID Token...");
  const MeridToken = await ethers.getContractFactory("MeridToken");
  const meridToken = await MeridToken.deploy(
    "MERID Token",
    "MRD",
    ethers.parseEther("1000000") // 1M initial supply
  );
  await meridToken.waitForDeployment();
  const meridTokenAddress = await meridToken.getAddress();
  const meridTokenTx = meridToken.deploymentTransaction();
  
  console.log(`✓ MERID Token deployed to: ${meridTokenAddress}`);
  console.log(`  Tx: ${meridTokenTx?.hash}`);
  console.log(`  Gas used: ${meridTokenTx?.gasLimit.toString()}`);
  
  deploymentRecord.contracts["MeridToken"] = {
    address: meridTokenAddress,
    deploymentTx: meridTokenTx?.hash || "",
    deploymentBlock: meridTokenTx?.blockNumber || 0,
    gasUsed: Number(meridTokenTx?.gasLimit || 0),
    deployer: deployer.address,
    timestamp: Date.now(),
  };
  
  // Deploy MERID Vault (ERC-4626)
  console.log("\n2. Deploying MERID Vault...");
  const MeridVault = await ethers.getContractFactory("MeridVault");
  const meridVault = await MeridVault.deploy(
    meridTokenAddress,
    "MERID Vault",
    "vMRD"
  );
  await meridVault.waitForDeployment();
  const meridVaultAddress = await meridVault.getAddress();
  const meridVaultTx = meridVault.deploymentTransaction();
  
  console.log(`✓ MERID Vault deployed to: ${meridVaultAddress}`);
  console.log(`  Tx: ${meridVaultTx?.hash}`);
  console.log(`  Gas used: ${meridVaultTx?.gasLimit.toString()}`);
  
  deploymentRecord.contracts["MeridVault"] = {
    address: meridVaultAddress,
    deploymentTx: meridVaultTx?.hash || "",
    deploymentBlock: meridVaultTx?.blockNumber || 0,
    gasUsed: Number(meridVaultTx?.gasLimit || 0),
    deployer: deployer.address,
    timestamp: Date.now(),
  };
  
  // Deploy MERID Router
  console.log("\n3. Deploying MERID Router...");
  const MeridRouter = await ethers.getContractFactory("MeridRouter");
  const meridRouter = await MeridRouter.deploy(
    meridVaultAddress
  );
  await meridRouter.waitForDeployment();
  const meridRouterAddress = await meridRouter.getAddress();
  const meridRouterTx = meridRouter.deploymentTransaction();
  
  console.log(`✓ MERID Router deployed to: ${meridRouterAddress}`);
  console.log(`  Tx: ${meridRouterTx?.hash}`);
  console.log(`  Gas used: ${meridRouterTx?.gasLimit.toString()}`);
  
  deploymentRecord.contracts["MeridRouter"] = {
    address: meridRouterAddress,
    deploymentTx: meridRouterTx?.hash || "",
    deploymentBlock: meridRouterTx?.blockNumber || 0,
    gasUsed: Number(meridRouterTx?.gasLimit || 0),
    deployer: deployer.address,
    timestamp: Date.now(),
  };
  
  // Deploy MERID Risk Manager
  console.log("\n4. Deploying MERID Risk Manager...");
  const MeridRiskManager = await ethers.getContractFactory("MeridRiskManager");
  const meridRiskManager = await MeridRiskManager.deploy(
    meridVaultAddress,
    deployer.address // Initial admin
  );
  await meridRiskManager.waitForDeployment();
  const meridRiskManagerAddress = await meridRiskManager.getAddress();
  const meridRiskManagerTx = meridRiskManager.deploymentTransaction();
  
  console.log(`✓ MERID Risk Manager deployed to: ${meridRiskManagerAddress}`);
  console.log(`  Tx: ${meridRiskManagerTx?.hash}`);
  console.log(`  Gas used: ${meridRiskManagerTx?.gasLimit.toString()}`);
  
  deploymentRecord.contracts["MeridRiskManager"] = {
    address: meridRiskManagerAddress,
    deploymentTx: meridRiskManagerTx?.hash || "",
    deploymentBlock: meridRiskManagerTx?.blockNumber || 0,
    gasUsed: Number(meridRiskManagerTx?.gasLimit || 0),
    deployer: deployer.address,
    timestamp: Date.now(),
  };
  
  // Save deployment record
  const deploymentsDir = path.join(__dirname, "..", "deployments");
  if (!fs.existsSync(deploymentsDir)) {
    fs.mkdirSync(deploymentsDir, { recursive: true });
  }
  
  const deploymentFile = path.join(
    deploymentsDir,
    `${network.name}_${network.chainId}_${Date.now()}.json`
  );
  fs.writeFileSync(deploymentFile, JSON.stringify(deploymentRecord, null, 2));
  
  console.log("\n" + "=".repeat(60));
  console.log("Deployment Summary");
  console.log("=".repeat(60));
  console.log(`Network: ${network.name} (${network.chainId})`);
  console.log(`Deployer: ${deployer.address}`);
  console.log(`\nContracts:`);
  console.log(`  MERID Token:        ${meridTokenAddress}`);
  console.log(`  MERID Vault:        ${meridVaultAddress}`);
  console.log(`  MERID Router:       ${meridRouterAddress}`);
  console.log(`  MERID Risk Manager: ${meridRiskManagerAddress}`);
  console.log(`\nDeployment record saved to: ${deploymentFile}`);
  console.log("=".repeat(60));
  
  console.log("\nNext steps:");
  console.log("1. Verify contracts on explorer:");
  console.log(`   npx hardhat verify --network ${network.name} ${meridTokenAddress} "MERID Token" "MRD" "${ethers.parseEther("1000000")}"`);
  console.log(`   npx hardhat verify --network ${network.name} ${meridVaultAddress} "${meridTokenAddress}" "MERID Vault" "vMRD"`);
  console.log(`   npx hardhat verify --network ${network.name} ${meridRouterAddress} "${meridVaultAddress}"`);
  console.log(`   npx hardhat verify --network ${network.name} ${meridRiskManagerAddress} "${meridVaultAddress}" "${deployer.address}"`);
  console.log("\n2. Configure vault permissions");
  console.log("3. Set up risk limits");
  console.log("4. Initialize agent integration");
}

function getGasToken(chainId: bigint): string {
  switch (Number(chainId)) {
    case 338: return "TCRO";
    case 25: return "CRO";
    case 282: return "zkTCRO";
    case 388: return "zkCRO";
    default: return "ETH";
  }
}

main()
  .then(() => process.exit(0))
  .catch((error) => {
    console.error(error);
    process.exit(1);
  });
