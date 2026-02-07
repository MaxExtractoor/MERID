// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

/**
 * @title HFTSwarmController
 * @notice Controller for HFT swarm operations with security and scam protection
 * @dev Manages Tier 0 execution, token safety, and anti-MEV measures
 */

import "@openzeppelin/contracts/access/AccessControl.sol";
import "@openzeppelin/contracts/security/ReentrancyGuard.sol";
import "@openzeppelin/contracts/security/Pausable.sol";

contract HFTSwarmController is AccessControl, ReentrancyGuard, Pausable {
    // Roles
    bytes32 public constant EXECUTOR_ROLE = keccak256("EXECUTOR_ROLE");
    bytes32 public constant SCANNER_ROLE = keccak256("SCANNER_ROLE");
    bytes32 public constant GUARDIAN_ROLE = keccak256("GUARDIAN_ROLE");

    // Token safety status
    enum TokenSafetyStatus {
        Unknown,
        Safe,
        Suspicious,
        Dangerous,
        Blacklisted
    }

    // Execution tier
    enum ExecutionTier {
        Tier0_UltraLow,  // < 10ms
        Tier1_Low,       // < 50ms
        Tier2_Standard,  // < 200ms
        Tier3_Relaxed    // < 1000ms
    }

    // MEV protection level
    enum MEVProtection {
        None,
        Basic,
        Enhanced,
        Maximum
    }

    struct TokenSafetyReport {
        address token;
        TokenSafetyStatus status;
        uint256 liquidityScore;      // 0-100
        uint256 holderScore;         // 0-100
        uint256 contractScore;       // 0-100
        bool hasHoneypot;
        bool hasRugPull;
        bool hasMintFunction;
        bool hasPauseFunction;
        bool hasBlacklist;
        uint256 lastScanned;
        string scannerNotes;
    }

    struct ExecutionConfig {
        ExecutionTier tier;
        MEVProtection mevProtection;
        uint256 maxGasPrice;
        uint256 maxSlippage;
        uint256 minLiquidity;
        uint256 maxPositionSize;
        bool requireSafeToken;
        bool usePrivateMempool;
    }

    struct SwarmAgent {
        bytes32 agentId;
        string name;
        ExecutionTier tier;
        bool active;
        uint256 executionCount;
        uint256 successCount;
        uint256 totalVolume;
        uint256 lastExecution;
    }

    struct ExecutionRecord {
        bytes32 executionId;
        bytes32 agentId;
        address token;
        uint256 amount;
        uint256 gasUsed;
        uint256 latencyMs;
        bool success;
        string failureReason;
        uint256 timestamp;
    }

    // State variables
    mapping(address => TokenSafetyReport) public tokenReports;
    mapping(bytes32 => SwarmAgent) public swarmAgents;
    mapping(bytes32 => ExecutionRecord[]) public executionHistory;
    mapping(ExecutionTier => ExecutionConfig) public tierConfigs;
    
    address[] public scannedTokens;
    bytes32[] public activeAgents;
    
    uint256 public totalExecutions;
    uint256 public successfulExecutions;
    uint256 public blockedExecutions;

    // Circuit breakers
    uint256 public maxExecutionsPerBlock = 100;
    uint256 public currentBlockExecutions;
    uint256 public lastExecutionBlock;
    
    uint256 public maxDailyVolume = 10000000e18;
    uint256 public dailyVolume;
    uint256 public lastVolumeReset;

    // Events
    event TokenScanned(
        address indexed token,
        TokenSafetyStatus status,
        uint256 overallScore
    );
    event TokenBlacklisted(address indexed token, string reason);
    event AgentRegistered(bytes32 indexed agentId, string name, ExecutionTier tier);
    event AgentStatusChanged(bytes32 indexed agentId, bool active);
    event ExecutionCompleted(
        bytes32 indexed executionId,
        bytes32 indexed agentId,
        address token,
        uint256 amount,
        bool success
    );
    event ExecutionBlocked(
        bytes32 indexed agentId,
        address token,
        string reason
    );
    event CircuitBreakerTriggered(string reason);
    event MEVProtectionActivated(bytes32 indexed executionId, MEVProtection level);

    constructor() {
        _grantRole(DEFAULT_ADMIN_ROLE, msg.sender);
        _grantRole(EXECUTOR_ROLE, msg.sender);
        _grantRole(SCANNER_ROLE, msg.sender);
        _grantRole(GUARDIAN_ROLE, msg.sender);

        // Initialize tier configs
        _initializeTierConfigs();
        
        lastVolumeReset = block.timestamp;
    }

    function _initializeTierConfigs() internal {
        tierConfigs[ExecutionTier.Tier0_UltraLow] = ExecutionConfig({
            tier: ExecutionTier.Tier0_UltraLow,
            mevProtection: MEVProtection.Maximum,
            maxGasPrice: 500 gwei,
            maxSlippage: 100, // 1%
            minLiquidity: 100000e18,
            maxPositionSize: 10000e18,
            requireSafeToken: true,
            usePrivateMempool: true
        });

        tierConfigs[ExecutionTier.Tier1_Low] = ExecutionConfig({
            tier: ExecutionTier.Tier1_Low,
            mevProtection: MEVProtection.Enhanced,
            maxGasPrice: 300 gwei,
            maxSlippage: 200, // 2%
            minLiquidity: 50000e18,
            maxPositionSize: 50000e18,
            requireSafeToken: true,
            usePrivateMempool: true
        });

        tierConfigs[ExecutionTier.Tier2_Standard] = ExecutionConfig({
            tier: ExecutionTier.Tier2_Standard,
            mevProtection: MEVProtection.Basic,
            maxGasPrice: 200 gwei,
            maxSlippage: 300, // 3%
            minLiquidity: 10000e18,
            maxPositionSize: 100000e18,
            requireSafeToken: true,
            usePrivateMempool: false
        });

        tierConfigs[ExecutionTier.Tier3_Relaxed] = ExecutionConfig({
            tier: ExecutionTier.Tier3_Relaxed,
            mevProtection: MEVProtection.None,
            maxGasPrice: 100 gwei,
            maxSlippage: 500, // 5%
            minLiquidity: 1000e18,
            maxPositionSize: 500000e18,
            requireSafeToken: false,
            usePrivateMempool: false
        });
    }

    /**
     * @notice Scan a token for safety
     */
    function scanToken(
        address token,
        uint256 liquidityScore,
        uint256 holderScore,
        uint256 contractScore,
        bool hasHoneypot,
        bool hasRugPull,
        bool hasMintFunction,
        bool hasPauseFunction,
        bool hasBlacklist,
        string calldata notes
    ) external onlyRole(SCANNER_ROLE) {
        TokenSafetyStatus status;
        
        if (hasHoneypot || hasRugPull) {
            status = TokenSafetyStatus.Dangerous;
        } else if (liquidityScore < 30 || holderScore < 30 || contractScore < 30) {
            status = TokenSafetyStatus.Suspicious;
        } else if (liquidityScore >= 70 && holderScore >= 70 && contractScore >= 70) {
            status = TokenSafetyStatus.Safe;
        } else {
            status = TokenSafetyStatus.Suspicious;
        }

        tokenReports[token] = TokenSafetyReport({
            token: token,
            status: status,
            liquidityScore: liquidityScore,
            holderScore: holderScore,
            contractScore: contractScore,
            hasHoneypot: hasHoneypot,
            hasRugPull: hasRugPull,
            hasMintFunction: hasMintFunction,
            hasPauseFunction: hasPauseFunction,
            hasBlacklist: hasBlacklist,
            lastScanned: block.timestamp,
            scannerNotes: notes
        });

        if (tokenReports[token].lastScanned == 0) {
            scannedTokens.push(token);
        }

        uint256 overallScore = (liquidityScore + holderScore + contractScore) / 3;
        emit TokenScanned(token, status, overallScore);
    }

    /**
     * @notice Blacklist a token
     */
    function blacklistToken(address token, string calldata reason)
        external
        onlyRole(GUARDIAN_ROLE)
    {
        tokenReports[token].status = TokenSafetyStatus.Blacklisted;
        emit TokenBlacklisted(token, reason);
    }

    /**
     * @notice Register a swarm agent
     */
    function registerAgent(
        string calldata name,
        ExecutionTier tier
    ) external onlyRole(DEFAULT_ADMIN_ROLE) returns (bytes32) {
        bytes32 agentId = keccak256(
            abi.encodePacked(name, tier, block.timestamp)
        );

        swarmAgents[agentId] = SwarmAgent({
            agentId: agentId,
            name: name,
            tier: tier,
            active: true,
            executionCount: 0,
            successCount: 0,
            totalVolume: 0,
            lastExecution: 0
        });

        activeAgents.push(agentId);

        emit AgentRegistered(agentId, name, tier);
        return agentId;
    }

    /**
     * @notice Set agent active status
     */
    function setAgentActive(bytes32 agentId, bool active)
        external
        onlyRole(DEFAULT_ADMIN_ROLE)
    {
        require(swarmAgents[agentId].agentId != bytes32(0), "Agent not found");
        swarmAgents[agentId].active = active;
        emit AgentStatusChanged(agentId, active);
    }

    /**
     * @notice Check if execution is allowed
     */
    function canExecute(
        bytes32 agentId,
        address token,
        uint256 amount
    ) public view returns (bool allowed, string memory reason) {
        SwarmAgent storage agent = swarmAgents[agentId];
        
        if (agent.agentId == bytes32(0)) {
            return (false, "Agent not found");
        }
        
        if (!agent.active) {
            return (false, "Agent not active");
        }

        ExecutionConfig storage config = tierConfigs[agent.tier];

        // Check token safety
        if (config.requireSafeToken) {
            TokenSafetyReport storage report = tokenReports[token];
            if (report.status == TokenSafetyStatus.Blacklisted) {
                return (false, "Token blacklisted");
            }
            if (report.status == TokenSafetyStatus.Dangerous) {
                return (false, "Token dangerous");
            }
            if (report.status == TokenSafetyStatus.Unknown) {
                return (false, "Token not scanned");
            }
        }

        // Check position size
        if (amount > config.maxPositionSize) {
            return (false, "Exceeds max position size");
        }

        // Check circuit breakers
        if (block.number == lastExecutionBlock && 
            currentBlockExecutions >= maxExecutionsPerBlock) {
            return (false, "Block execution limit reached");
        }

        // Check daily volume
        uint256 currentDailyVolume = dailyVolume;
        if (block.timestamp >= lastVolumeReset + 1 days) {
            currentDailyVolume = 0;
        }
        if (currentDailyVolume + amount > maxDailyVolume) {
            return (false, "Daily volume limit reached");
        }

        return (true, "");
    }

    /**
     * @notice Record an execution
     */
    function recordExecution(
        bytes32 agentId,
        address token,
        uint256 amount,
        uint256 gasUsed,
        uint256 latencyMs,
        bool success,
        string calldata failureReason
    ) external onlyRole(EXECUTOR_ROLE) returns (bytes32) {
        // Reset daily volume if needed
        if (block.timestamp >= lastVolumeReset + 1 days) {
            dailyVolume = 0;
            lastVolumeReset = block.timestamp;
        }

        // Reset block counter if needed
        if (block.number != lastExecutionBlock) {
            currentBlockExecutions = 0;
            lastExecutionBlock = block.number;
        }

        bytes32 executionId = keccak256(
            abi.encodePacked(agentId, token, amount, block.timestamp)
        );

        ExecutionRecord memory record = ExecutionRecord({
            executionId: executionId,
            agentId: agentId,
            token: token,
            amount: amount,
            gasUsed: gasUsed,
            latencyMs: latencyMs,
            success: success,
            failureReason: failureReason,
            timestamp: block.timestamp
        });

        executionHistory[agentId].push(record);

        // Update agent stats
        SwarmAgent storage agent = swarmAgents[agentId];
        agent.executionCount++;
        agent.totalVolume += amount;
        agent.lastExecution = block.timestamp;
        if (success) {
            agent.successCount++;
        }

        // Update global stats
        totalExecutions++;
        if (success) {
            successfulExecutions++;
        }
        dailyVolume += amount;
        currentBlockExecutions++;

        emit ExecutionCompleted(executionId, agentId, token, amount, success);
        return executionId;
    }

    /**
     * @notice Block an execution attempt
     */
    function blockExecution(
        bytes32 agentId,
        address token,
        string calldata reason
    ) external onlyRole(EXECUTOR_ROLE) {
        blockedExecutions++;
        emit ExecutionBlocked(agentId, token, reason);
    }

    /**
     * @notice Get token safety report
     */
    function getTokenReport(address token)
        external
        view
        returns (
            TokenSafetyStatus status,
            uint256 liquidityScore,
            uint256 holderScore,
            uint256 contractScore,
            bool hasHoneypot,
            bool hasRugPull,
            uint256 lastScanned
        )
    {
        TokenSafetyReport storage report = tokenReports[token];
        return (
            report.status,
            report.liquidityScore,
            report.holderScore,
            report.contractScore,
            report.hasHoneypot,
            report.hasRugPull,
            report.lastScanned
        );
    }

    /**
     * @notice Get agent stats
     */
    function getAgentStats(bytes32 agentId)
        external
        view
        returns (
            string memory name,
            ExecutionTier tier,
            bool active,
            uint256 executionCount,
            uint256 successCount,
            uint256 totalVolume,
            uint256 successRate
        )
    {
        SwarmAgent storage agent = swarmAgents[agentId];
        uint256 rate = agent.executionCount > 0 ? 
            (agent.successCount * 10000) / agent.executionCount : 0;
        return (
            agent.name,
            agent.tier,
            agent.active,
            agent.executionCount,
            agent.successCount,
            agent.totalVolume,
            rate
        );
    }

    /**
     * @notice Get execution history count for an agent
     */
    function getExecutionHistoryCount(bytes32 agentId)
        external
        view
        returns (uint256)
    {
        return executionHistory[agentId].length;
    }

    /**
     * @notice Get global stats
     */
    function getGlobalStats()
        external
        view
        returns (
            uint256 _totalExecutions,
            uint256 _successfulExecutions,
            uint256 _blockedExecutions,
            uint256 _dailyVolume,
            uint256 _scannedTokenCount,
            uint256 _activeAgentCount
        )
    {
        return (
            totalExecutions,
            successfulExecutions,
            blockedExecutions,
            dailyVolume,
            scannedTokens.length,
            activeAgents.length
        );
    }

    /**
     * @notice Update tier configuration
     */
    function updateTierConfig(
        ExecutionTier tier,
        uint256 maxGasPrice,
        uint256 maxSlippage,
        uint256 minLiquidity,
        uint256 maxPositionSize,
        bool requireSafeToken,
        bool usePrivateMempool,
        MEVProtection mevProtection
    ) external onlyRole(DEFAULT_ADMIN_ROLE) {
        tierConfigs[tier] = ExecutionConfig({
            tier: tier,
            mevProtection: mevProtection,
            maxGasPrice: maxGasPrice,
            maxSlippage: maxSlippage,
            minLiquidity: minLiquidity,
            maxPositionSize: maxPositionSize,
            requireSafeToken: requireSafeToken,
            usePrivateMempool: usePrivateMempool
        });
    }

    /**
     * @notice Update circuit breaker limits
     */
    function updateCircuitBreakers(
        uint256 _maxExecutionsPerBlock,
        uint256 _maxDailyVolume
    ) external onlyRole(DEFAULT_ADMIN_ROLE) {
        maxExecutionsPerBlock = _maxExecutionsPerBlock;
        maxDailyVolume = _maxDailyVolume;
    }

    /**
     * @notice Trigger circuit breaker manually
     */
    function triggerCircuitBreaker(string calldata reason)
        external
        onlyRole(GUARDIAN_ROLE)
    {
        _pause();
        emit CircuitBreakerTriggered(reason);
    }

    /**
     * @notice Pause operations
     */
    function pause() external onlyRole(GUARDIAN_ROLE) {
        _pause();
    }

    /**
     * @notice Unpause operations
     */
    function unpause() external onlyRole(DEFAULT_ADMIN_ROLE) {
        _unpause();
    }
}
