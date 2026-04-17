import { HardhatUserConfig } from "hardhat/config";
import "@nomicfoundation/hardhat-toolbox";
import "@nomicfoundation/hardhat-verify";
import * as dotenv from "dotenv";

dotenv.config();

const config: HardhatUserConfig = {
  solidity: {
    version: "0.8.24",
    settings: {
      optimizer: {
        enabled: true,
        runs: 200,
      },
      viaIR: false,
    },
  },
  
  networks: {
    // Cronos EVM Testnet
    cronosevmtestnet: {
      url: process.env.CRONOS_EVM_TESTNET_RPC || "https://evm-t3.cronos.org",
      chainId: 338,
      accounts: process.env.DEPLOYER_PK ? [process.env.DEPLOYER_PK] : [],
      gasPrice: 5000000000000, // 5000 gwei
    },
    
    // Cronos EVM Mainnet
    cronosevmmainnet: {
      url: process.env.CRONOS_EVM_MAINNET_RPC || "https://evm.cronos.org",
      chainId: 25,
      accounts: process.env.DEPLOYER_PK ? [process.env.DEPLOYER_PK] : [],
      gasPrice: 5000000000000, // 5000 gwei
    },
    
    // Cronos zkEVM Testnet
    cronoszkvmtestnet: {
      url: process.env.CRONOS_ZKEVM_TESTNET_RPC || "https://testnet.zkevm.cronos.org",
      chainId: 282,
      accounts: process.env.DEPLOYER_PK ? [process.env.DEPLOYER_PK] : [],
      gasPrice: 1000000000000, // 1000 gwei
    },
    
    // Cronos zkEVM Mainnet
    cronoszkvmmainnet: {
      url: process.env.CRONOS_ZKEVM_MAINNET_RPC || "https://mainnet.zkevm.cronos.org",
      chainId: 388,
      accounts: process.env.DEPLOYER_PK ? [process.env.DEPLOYER_PK] : [],
      gasPrice: 1000000000000, // 1000 gwei
    },
    
    // Hardhat local network
    hardhat: {
      chainId: 31337,
    },
  },
  
  etherscan: {
    apiKey: {
      cronosevmtestnet: process.env.CRONOS_EXPLORER_API_KEY || "placeholder",
      cronosevmmainnet: process.env.CRONOS_EXPLORER_API_KEY || "placeholder",
      cronoszkvmtestnet: process.env.CRONOS_ZKEVM_EXPLORER_API_KEY || "placeholder",
      cronoszkvmmainnet: process.env.CRONOS_ZKEVM_EXPLORER_API_KEY || "placeholder",
    },
    customChains: [
      {
        network: "cronosevmtestnet",
        chainId: 338,
        urls: {
          apiURL: "https://cronos.org/explorer/testnet3/api",
          browserURL: "https://cronos.org/explorer/testnet3",
        },
      },
      {
        network: "cronosevmmainnet",
        chainId: 25,
        urls: {
          apiURL: "https://cronos.org/explorer/api",
          browserURL: "https://cronos.org/explorer",
        },
      },
      {
        network: "cronoszkvmtestnet",
        chainId: 282,
        urls: {
          apiURL: "https://explorer-testnet.zkevm.cronos.org/api",
          browserURL: "https://explorer-testnet.zkevm.cronos.org",
        },
      },
      {
        network: "cronoszkvmmainnet",
        chainId: 388,
        urls: {
          apiURL: "https://explorer.zkevm.cronos.org/api",
          browserURL: "https://explorer.zkevm.cronos.org",
        },
      },
    ],
  },
  
  paths: {
    sources: "./contracts",
    tests: "./test",
    cache: "./cache",
    artifacts: "./artifacts",
  },
  
  mocha: {
    timeout: 40000,
  },
};

export default config;
