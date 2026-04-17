// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

/**
 * @title AgentPermissions
 * @notice On-chain permission system for AI agents
 * @dev Manages agent capabilities, limits, and access control
 */

import "@openzeppelin/contracts/access/AccessControl.sol";
import "@openzeppelin/contracts/security/ReentrancyGuard.sol";
import "@openzeppelin/contracts/security/Pausable.sol";

contract AgentPermissions is AccessControl, ReentrancyGuard, Pausable {
    // Roles
    bytes32 public constant ADMIN_ROLE = keccak256("ADMIN_ROLE");
    bytes32 public constant OPERATOR_ROLE = keccak256("OPERATOR_ROLE");
    bytes32 public constant AUDITOR_ROLE = keccak256("AUDITOR_ROLE");

    // Agent status
    enum AgentStatus {
        Inactive,
        Active,
        Suspended,
        Retired
    }

    // Permission levels
    enum PermissionLevel {
        None,
        ReadOnly,
        Limited,
        Standard,
        Elevated,
        Admin
    }

    // Agent capability types
    enum CapabilityType {
        Trading,
        RiskManagement,
        DataAccess,
        Execution,
        Governance,
        Security,
        Research,
        Monitoring
    }

    struct Agent {
        bytes32 agentId;
        string name;
        address owner;
        AgentStatus status;
        uint256 registeredAt;
        uint256 lastActiveAt;
        uint256 totalActions;
        uint256 suspensionCount;
    }

    struct AgentCapability {
        CapabilityType capabilityType;
        PermissionLevel level;
        uint256 dailyLimit;
        uint256 dailyUsed;
        uint256 lastResetTimestamp;
        bool enabled;
    }

    struct AgentLimits {
        uint256 maxTransactionSize;
        uint256 maxDailyVolume;
        uint256 maxPositionSize;
        uint256 maxLeverage;
        uint256 cooldownPeriod;
        uint256 lastActionTimestamp;
    }

    struct ActionLog {
        bytes32 agentId;
        bytes32 actionId;
        CapabilityType capability;
        uint256 amount;
        uint256 timestamp;
        bool success;
        string reason;
    }

    // State variables
    mapping(bytes32 => Agent) public agents;
    mapping(bytes32 => mapping(CapabilityType => AgentCapability)) public capabilities;
    mapping(bytes32 => AgentLimits) public limits;
    mapping(bytes32 => ActionLog[]) public actionLogs;
    mapping(address => bytes32[]) public ownerAgents;

    bytes32[] public allAgentIds;
    uint256 public totalAgents;
    uint256 public activeAgents;

    // Default limits
    uint256 public defaultMaxTransactionSize = 10000e18;
    uint256 public defaultMaxDailyVolume = 100000e18;
    uint256 public defaultCooldownPeriod = 60; // 1 minute

    // Events
    event AgentRegistered(
        bytes32 indexed agentId,
        string name,
        address indexed owner
    );
    event AgentStatusChanged(
        bytes32 indexed agentId,
        AgentStatus oldStatus,
        AgentStatus newStatus
    );
    event CapabilityGranted(
        bytes32 indexed agentId,
        CapabilityType capability,
        PermissionLevel level
    );
    event CapabilityRevoked(bytes32 indexed agentId, CapabilityType capability);
    event LimitsUpdated(bytes32 indexed agentId, uint256 maxTransaction, uint256 maxDaily);
    event ActionExecuted(
        bytes32 indexed agentId,
        bytes32 indexed actionId,
        CapabilityType capability,
        uint256 amount,
        bool success
    );
    event AgentSuspended(bytes32 indexed agentId, string reason);
    event EmergencyStop(bytes32 indexed agentId, address indexed triggeredBy);

    constructor() {
        _grantRole(DEFAULT_ADMIN_ROLE, msg.sender);
        _grantRole(ADMIN_ROLE, msg.sender);
        _grantRole(OPERATOR_ROLE, msg.sender);
    }

    /**
     * @notice Register a new agent
     * @param name Agent name
     * @param owner Agent owner address
     */
    function registerAgent(string calldata name, address owner)
        external
        onlyRole(OPERATOR_ROLE)
        returns (bytes32)
    {
        bytes32 agentId = keccak256(
            abi.encodePacked(name, owner, block.timestamp, totalAgents)
        );

        require(agents[agentId].registeredAt == 0, "Agent already exists");

        agents[agentId] = Agent({
            agentId: agentId,
            name: name,
            owner: owner,
            status: AgentStatus.Active,
            registeredAt: block.timestamp,
            lastActiveAt: block.timestamp,
            totalActions: 0,
            suspensionCount: 0
        });

        limits[agentId] = AgentLimits({
            maxTransactionSize: defaultMaxTransactionSize,
            maxDailyVolume: defaultMaxDailyVolume,
            maxPositionSize: defaultMaxTransactionSize * 10,
            maxLeverage: 3,
            cooldownPeriod: defaultCooldownPeriod,
            lastActionTimestamp: 0
        });

        allAgentIds.push(agentId);
        ownerAgents[owner].push(agentId);
        totalAgents++;
        activeAgents++;

        emit AgentRegistered(agentId, name, owner);
        return agentId;
    }

    /**
     * @notice Grant a capability to an agent
     */
    function grantCapability(
        bytes32 agentId,
        CapabilityType capabilityType,
        PermissionLevel level,
        uint256 dailyLimit
    ) external onlyRole(OPERATOR_ROLE) {
        require(agents[agentId].registeredAt > 0, "Agent not found");
        require(level != PermissionLevel.None, "Cannot grant None level");

        capabilities[agentId][capabilityType] = AgentCapability({
            capabilityType: capabilityType,
            level: level,
            dailyLimit: dailyLimit,
            dailyUsed: 0,
            lastResetTimestamp: block.timestamp,
            enabled: true
        });

        emit CapabilityGranted(agentId, capabilityType, level);
    }

    /**
     * @notice Revoke a capability from an agent
     */
    function revokeCapability(bytes32 agentId, CapabilityType capabilityType)
        external
        onlyRole(OPERATOR_ROLE)
    {
        require(agents[agentId].registeredAt > 0, "Agent not found");

        capabilities[agentId][capabilityType].enabled = false;
        capabilities[agentId][capabilityType].level = PermissionLevel.None;

        emit CapabilityRevoked(agentId, capabilityType);
    }

    /**
     * @notice Update agent limits
     */
    function updateLimits(
        bytes32 agentId,
        uint256 maxTransactionSize,
        uint256 maxDailyVolume,
        uint256 maxPositionSize,
        uint256 maxLeverage,
        uint256 cooldownPeriod
    ) external onlyRole(OPERATOR_ROLE) {
        require(agents[agentId].registeredAt > 0, "Agent not found");

        AgentLimits storage agentLimits = limits[agentId];
        agentLimits.maxTransactionSize = maxTransactionSize;
        agentLimits.maxDailyVolume = maxDailyVolume;
        agentLimits.maxPositionSize = maxPositionSize;
        agentLimits.maxLeverage = maxLeverage;
        agentLimits.cooldownPeriod = cooldownPeriod;

        emit LimitsUpdated(agentId, maxTransactionSize, maxDailyVolume);
    }

    /**
     * @notice Check if agent can perform an action
     */
    function canPerformAction(
        bytes32 agentId,
        CapabilityType capabilityType,
        uint256 amount
    ) public view returns (bool allowed, string memory reason) {
        Agent storage agent = agents[agentId];

        if (agent.registeredAt == 0) {
            return (false, "Agent not found");
        }

        if (agent.status != AgentStatus.Active) {
            return (false, "Agent not active");
        }

        AgentCapability storage cap = capabilities[agentId][capabilityType];

        if (!cap.enabled) {
            return (false, "Capability not enabled");
        }

        if (cap.level == PermissionLevel.None) {
            return (false, "No permission");
        }

        AgentLimits storage agentLimits = limits[agentId];

        if (amount > agentLimits.maxTransactionSize) {
            return (false, "Exceeds transaction limit");
        }

        // Check cooldown
        if (
            agentLimits.lastActionTimestamp > 0 &&
            block.timestamp < agentLimits.lastActionTimestamp + agentLimits.cooldownPeriod
        ) {
            return (false, "Cooldown period active");
        }

        // Check daily limit (reset if new day)
        uint256 dailyUsed = cap.dailyUsed;
        if (block.timestamp >= cap.lastResetTimestamp + 1 days) {
            dailyUsed = 0;
        }

        if (dailyUsed + amount > cap.dailyLimit) {
            return (false, "Exceeds daily limit");
        }

        return (true, "");
    }

    /**
     * @notice Record an action execution
     */
    function recordAction(
        bytes32 agentId,
        CapabilityType capabilityType,
        uint256 amount,
        bool success,
        string calldata reason
    ) external onlyRole(OPERATOR_ROLE) returns (bytes32) {
        require(agents[agentId].registeredAt > 0, "Agent not found");

        bytes32 actionId = keccak256(
            abi.encodePacked(agentId, capabilityType, amount, block.timestamp)
        );

        // Update capability usage
        AgentCapability storage cap = capabilities[agentId][capabilityType];
        if (block.timestamp >= cap.lastResetTimestamp + 1 days) {
            cap.dailyUsed = 0;
            cap.lastResetTimestamp = block.timestamp;
        }
        cap.dailyUsed += amount;

        // Update agent stats
        Agent storage agent = agents[agentId];
        agent.lastActiveAt = block.timestamp;
        agent.totalActions++;

        // Update limits
        limits[agentId].lastActionTimestamp = block.timestamp;

        // Log action
        actionLogs[agentId].push(
            ActionLog({
                agentId: agentId,
                actionId: actionId,
                capability: capabilityType,
                amount: amount,
                timestamp: block.timestamp,
                success: success,
                reason: reason
            })
        );

        emit ActionExecuted(agentId, actionId, capabilityType, amount, success);
        return actionId;
    }

    /**
     * @notice Suspend an agent
     */
    function suspendAgent(bytes32 agentId, string calldata reason)
        external
        onlyRole(OPERATOR_ROLE)
    {
        require(agents[agentId].registeredAt > 0, "Agent not found");
        require(
            agents[agentId].status == AgentStatus.Active,
            "Agent not active"
        );

        AgentStatus oldStatus = agents[agentId].status;
        agents[agentId].status = AgentStatus.Suspended;
        agents[agentId].suspensionCount++;
        activeAgents--;

        emit AgentStatusChanged(agentId, oldStatus, AgentStatus.Suspended);
        emit AgentSuspended(agentId, reason);
    }

    /**
     * @notice Reactivate a suspended agent
     */
    function reactivateAgent(bytes32 agentId)
        external
        onlyRole(ADMIN_ROLE)
    {
        require(agents[agentId].registeredAt > 0, "Agent not found");
        require(
            agents[agentId].status == AgentStatus.Suspended,
            "Agent not suspended"
        );

        AgentStatus oldStatus = agents[agentId].status;
        agents[agentId].status = AgentStatus.Active;
        activeAgents++;

        emit AgentStatusChanged(agentId, oldStatus, AgentStatus.Active);
    }

    /**
     * @notice Retire an agent permanently
     */
    function retireAgent(bytes32 agentId) external onlyRole(ADMIN_ROLE) {
        require(agents[agentId].registeredAt > 0, "Agent not found");
        require(
            agents[agentId].status != AgentStatus.Retired,
            "Already retired"
        );

        AgentStatus oldStatus = agents[agentId].status;
        if (oldStatus == AgentStatus.Active) {
            activeAgents--;
        }
        agents[agentId].status = AgentStatus.Retired;

        emit AgentStatusChanged(agentId, oldStatus, AgentStatus.Retired);
    }

    /**
     * @notice Emergency stop for an agent
     */
    function emergencyStop(bytes32 agentId) external {
        require(
            hasRole(ADMIN_ROLE, msg.sender) ||
                hasRole(OPERATOR_ROLE, msg.sender) ||
                agents[agentId].owner == msg.sender,
            "Not authorized"
        );
        require(agents[agentId].registeredAt > 0, "Agent not found");

        AgentStatus oldStatus = agents[agentId].status;
        if (oldStatus == AgentStatus.Active) {
            activeAgents--;
        }
        agents[agentId].status = AgentStatus.Suspended;

        emit AgentStatusChanged(agentId, oldStatus, AgentStatus.Suspended);
        emit EmergencyStop(agentId, msg.sender);
    }

    /**
     * @notice Get agent details
     */
    function getAgent(bytes32 agentId)
        external
        view
        returns (
            string memory name,
            address owner,
            AgentStatus status,
            uint256 registeredAt,
            uint256 lastActiveAt,
            uint256 totalActions
        )
    {
        Agent storage agent = agents[agentId];
        return (
            agent.name,
            agent.owner,
            agent.status,
            agent.registeredAt,
            agent.lastActiveAt,
            agent.totalActions
        );
    }

    /**
     * @notice Get agent capability
     */
    function getCapability(bytes32 agentId, CapabilityType capabilityType)
        external
        view
        returns (
            PermissionLevel level,
            uint256 dailyLimit,
            uint256 dailyUsed,
            bool enabled
        )
    {
        AgentCapability storage cap = capabilities[agentId][capabilityType];
        uint256 used = cap.dailyUsed;
        if (block.timestamp >= cap.lastResetTimestamp + 1 days) {
            used = 0;
        }
        return (cap.level, cap.dailyLimit, used, cap.enabled);
    }

    /**
     * @notice Get agent limits
     */
    function getLimits(bytes32 agentId)
        external
        view
        returns (
            uint256 maxTransactionSize,
            uint256 maxDailyVolume,
            uint256 maxPositionSize,
            uint256 maxLeverage,
            uint256 cooldownPeriod
        )
    {
        AgentLimits storage agentLimits = limits[agentId];
        return (
            agentLimits.maxTransactionSize,
            agentLimits.maxDailyVolume,
            agentLimits.maxPositionSize,
            agentLimits.maxLeverage,
            agentLimits.cooldownPeriod
        );
    }

    /**
     * @notice Get action log count for an agent
     */
    function getActionLogCount(bytes32 agentId) external view returns (uint256) {
        return actionLogs[agentId].length;
    }

    /**
     * @notice Get agents owned by an address
     */
    function getOwnerAgents(address owner)
        external
        view
        returns (bytes32[] memory)
    {
        return ownerAgents[owner];
    }

    /**
     * @notice Update default limits
     */
    function setDefaultLimits(
        uint256 maxTransaction,
        uint256 maxDaily,
        uint256 cooldown
    ) external onlyRole(ADMIN_ROLE) {
        defaultMaxTransactionSize = maxTransaction;
        defaultMaxDailyVolume = maxDaily;
        defaultCooldownPeriod = cooldown;
    }

    /**
     * @notice Pause all agent operations
     */
    function pause() external onlyRole(ADMIN_ROLE) {
        _pause();
    }

    /**
     * @notice Unpause agent operations
     */
    function unpause() external onlyRole(ADMIN_ROLE) {
        _unpause();
    }
}
