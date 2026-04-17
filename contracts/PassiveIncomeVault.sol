// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

/**
 * @title PassiveIncomeVault
 * @notice Vault for passive income strategies (staking, LP, lending)
 * @dev Implements secure yield generation with risk controls
 */

import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import "@openzeppelin/contracts/access/AccessControl.sol";
import "@openzeppelin/contracts/security/ReentrancyGuard.sol";
import "@openzeppelin/contracts/security/Pausable.sol";

contract PassiveIncomeVault is AccessControl, ReentrancyGuard, Pausable {
    using SafeERC20 for IERC20;

    // Roles
    bytes32 public constant STRATEGIST_ROLE = keccak256("STRATEGIST_ROLE");
    bytes32 public constant KEEPER_ROLE = keccak256("KEEPER_ROLE");
    bytes32 public constant GUARDIAN_ROLE = keccak256("GUARDIAN_ROLE");

    // Strategy types
    enum StrategyType {
        Staking,
        LiquidityProvision,
        Lending,
        YieldFarming,
        Arbitrage
    }

    // Strategy status
    enum StrategyStatus {
        Inactive,
        Active,
        Paused,
        Deprecated
    }

    struct Strategy {
        bytes32 strategyId;
        string name;
        StrategyType strategyType;
        StrategyStatus status;
        address targetProtocol;
        address[] assets;
        uint256 allocatedAmount;
        uint256 currentValue;
        uint256 totalYield;
        uint256 lastHarvestTimestamp;
        uint256 minHarvestInterval;
        uint256 performanceFee; // basis points
        uint256 riskScore; // 1-100
    }

    struct UserDeposit {
        uint256 amount;
        uint256 shares;
        uint256 depositTimestamp;
        uint256 lastClaimTimestamp;
    }

    struct VaultStats {
        uint256 totalDeposits;
        uint256 totalShares;
        uint256 totalYieldGenerated;
        uint256 totalFeesCollected;
        uint256 highWaterMark;
    }

    // State variables
    IERC20 public immutable depositToken;
    
    mapping(bytes32 => Strategy) public strategies;
    mapping(address => UserDeposit) public userDeposits;
    mapping(address => uint256) public pendingYield;
    
    bytes32[] public activeStrategies;
    VaultStats public vaultStats;

    // Risk parameters
    uint256 public maxStrategyAllocation = 3000; // 30% max per strategy
    uint256 public maxRiskScore = 70; // Max risk score allowed
    uint256 public withdrawalFee = 50; // 0.5%
    uint256 public managementFee = 200; // 2% annual
    uint256 public performanceFee = 2000; // 20% of profits

    // Circuit breakers
    uint256 public maxDailyWithdrawal;
    uint256 public dailyWithdrawn;
    uint256 public lastWithdrawalReset;
    uint256 public emergencyWithdrawalDelay = 1 days;

    // Events
    event Deposited(address indexed user, uint256 amount, uint256 shares);
    event Withdrawn(address indexed user, uint256 amount, uint256 shares);
    event YieldHarvested(bytes32 indexed strategyId, uint256 amount);
    event YieldClaimed(address indexed user, uint256 amount);
    event StrategyAdded(bytes32 indexed strategyId, string name, StrategyType strategyType);
    event StrategyUpdated(bytes32 indexed strategyId, StrategyStatus status);
    event AllocationChanged(bytes32 indexed strategyId, uint256 newAllocation);
    event EmergencyWithdrawal(address indexed user, uint256 amount);
    event FeesCollected(uint256 managementFee, uint256 performanceFee);

    constructor(address _depositToken) {
        depositToken = IERC20(_depositToken);
        
        _grantRole(DEFAULT_ADMIN_ROLE, msg.sender);
        _grantRole(STRATEGIST_ROLE, msg.sender);
        _grantRole(KEEPER_ROLE, msg.sender);
        _grantRole(GUARDIAN_ROLE, msg.sender);

        maxDailyWithdrawal = 1000000e18; // 1M tokens
        lastWithdrawalReset = block.timestamp;
    }

    /**
     * @notice Deposit tokens into the vault
     * @param amount Amount to deposit
     */
    function deposit(uint256 amount) external nonReentrant whenNotPaused {
        require(amount > 0, "Amount must be > 0");

        uint256 shares = _calculateShares(amount);
        
        depositToken.safeTransferFrom(msg.sender, address(this), amount);

        UserDeposit storage userDeposit = userDeposits[msg.sender];
        userDeposit.amount += amount;
        userDeposit.shares += shares;
        userDeposit.depositTimestamp = block.timestamp;

        vaultStats.totalDeposits += amount;
        vaultStats.totalShares += shares;

        emit Deposited(msg.sender, amount, shares);
    }

    /**
     * @notice Withdraw tokens from the vault
     * @param shares Number of shares to withdraw
     */
    function withdraw(uint256 shares) external nonReentrant whenNotPaused {
        UserDeposit storage userDeposit = userDeposits[msg.sender];
        require(userDeposit.shares >= shares, "Insufficient shares");

        // Reset daily withdrawal counter if needed
        if (block.timestamp >= lastWithdrawalReset + 1 days) {
            dailyWithdrawn = 0;
            lastWithdrawalReset = block.timestamp;
        }

        uint256 amount = _calculateWithdrawalAmount(shares);
        require(dailyWithdrawn + amount <= maxDailyWithdrawal, "Daily limit exceeded");

        uint256 fee = (amount * withdrawalFee) / 10000;
        uint256 netAmount = amount - fee;

        userDeposit.shares -= shares;
        userDeposit.amount = (userDeposit.amount * userDeposit.shares) / 
            (userDeposit.shares + shares);

        vaultStats.totalShares -= shares;
        vaultStats.totalDeposits -= amount;
        vaultStats.totalFeesCollected += fee;
        dailyWithdrawn += amount;

        depositToken.safeTransfer(msg.sender, netAmount);

        emit Withdrawn(msg.sender, netAmount, shares);
    }

    /**
     * @notice Add a new strategy
     */
    function addStrategy(
        string calldata name,
        StrategyType strategyType,
        address targetProtocol,
        address[] calldata assets,
        uint256 minHarvestInterval,
        uint256 strategyPerformanceFee,
        uint256 riskScore
    ) external onlyRole(STRATEGIST_ROLE) returns (bytes32) {
        require(riskScore <= maxRiskScore, "Risk score too high");

        bytes32 strategyId = keccak256(
            abi.encodePacked(name, targetProtocol, block.timestamp)
        );

        strategies[strategyId] = Strategy({
            strategyId: strategyId,
            name: name,
            strategyType: strategyType,
            status: StrategyStatus.Active,
            targetProtocol: targetProtocol,
            assets: assets,
            allocatedAmount: 0,
            currentValue: 0,
            totalYield: 0,
            lastHarvestTimestamp: block.timestamp,
            minHarvestInterval: minHarvestInterval,
            performanceFee: strategyPerformanceFee,
            riskScore: riskScore
        });

        activeStrategies.push(strategyId);

        emit StrategyAdded(strategyId, name, strategyType);
        return strategyId;
    }

    /**
     * @notice Allocate funds to a strategy
     */
    function allocateToStrategy(bytes32 strategyId, uint256 amount)
        external
        onlyRole(STRATEGIST_ROLE)
    {
        Strategy storage strategy = strategies[strategyId];
        require(strategy.status == StrategyStatus.Active, "Strategy not active");

        uint256 totalAllocated = _getTotalAllocated();
        uint256 maxAllocation = (vaultStats.totalDeposits * maxStrategyAllocation) / 10000;
        
        require(
            strategy.allocatedAmount + amount <= maxAllocation,
            "Exceeds max allocation"
        );

        strategy.allocatedAmount += amount;

        emit AllocationChanged(strategyId, strategy.allocatedAmount);
    }

    /**
     * @notice Harvest yield from a strategy
     */
    function harvestYield(bytes32 strategyId, uint256 yieldAmount)
        external
        onlyRole(KEEPER_ROLE)
    {
        Strategy storage strategy = strategies[strategyId];
        require(strategy.status == StrategyStatus.Active, "Strategy not active");
        require(
            block.timestamp >= strategy.lastHarvestTimestamp + strategy.minHarvestInterval,
            "Too soon to harvest"
        );

        // Calculate fees
        uint256 fee = (yieldAmount * strategy.performanceFee) / 10000;
        uint256 netYield = yieldAmount - fee;

        strategy.totalYield += netYield;
        strategy.currentValue += netYield;
        strategy.lastHarvestTimestamp = block.timestamp;

        vaultStats.totalYieldGenerated += netYield;
        vaultStats.totalFeesCollected += fee;

        // Update high water mark
        uint256 currentValue = _getTotalValue();
        if (currentValue > vaultStats.highWaterMark) {
            vaultStats.highWaterMark = currentValue;
        }

        emit YieldHarvested(strategyId, netYield);
    }

    /**
     * @notice Claim pending yield
     */
    function claimYield() external nonReentrant {
        UserDeposit storage userDeposit = userDeposits[msg.sender];
        require(userDeposit.shares > 0, "No shares");

        uint256 userYield = _calculateUserYield(msg.sender);
        require(userYield > 0, "No yield to claim");

        userDeposit.lastClaimTimestamp = block.timestamp;
        pendingYield[msg.sender] = 0;

        depositToken.safeTransfer(msg.sender, userYield);

        emit YieldClaimed(msg.sender, userYield);
    }

    /**
     * @notice Update strategy status
     */
    function updateStrategyStatus(bytes32 strategyId, StrategyStatus status)
        external
        onlyRole(STRATEGIST_ROLE)
    {
        Strategy storage strategy = strategies[strategyId];
        require(strategy.strategyId != bytes32(0), "Strategy not found");

        strategy.status = status;

        emit StrategyUpdated(strategyId, status);
    }

    /**
     * @notice Emergency withdrawal (with delay)
     */
    function emergencyWithdraw() external nonReentrant {
        UserDeposit storage userDeposit = userDeposits[msg.sender];
        require(userDeposit.shares > 0, "No shares");
        require(
            block.timestamp >= userDeposit.depositTimestamp + emergencyWithdrawalDelay,
            "Emergency delay not passed"
        );

        uint256 amount = _calculateWithdrawalAmount(userDeposit.shares);
        uint256 shares = userDeposit.shares;

        userDeposit.shares = 0;
        userDeposit.amount = 0;

        vaultStats.totalShares -= shares;
        vaultStats.totalDeposits -= amount;

        depositToken.safeTransfer(msg.sender, amount);

        emit EmergencyWithdrawal(msg.sender, amount);
    }

    /**
     * @notice Collect management fees
     */
    function collectFees() external onlyRole(KEEPER_ROLE) {
        uint256 timeSinceLastCollection = block.timestamp - lastWithdrawalReset;
        uint256 annualFee = (vaultStats.totalDeposits * managementFee) / 10000;
        uint256 fee = (annualFee * timeSinceLastCollection) / 365 days;

        if (fee > 0) {
            vaultStats.totalFeesCollected += fee;
            emit FeesCollected(fee, 0);
        }
    }

    // View functions

    function _calculateShares(uint256 amount) internal view returns (uint256) {
        if (vaultStats.totalShares == 0) {
            return amount;
        }
        return (amount * vaultStats.totalShares) / _getTotalValue();
    }

    function _calculateWithdrawalAmount(uint256 shares) internal view returns (uint256) {
        if (vaultStats.totalShares == 0) {
            return 0;
        }
        return (shares * _getTotalValue()) / vaultStats.totalShares;
    }

    function _calculateUserYield(address user) internal view returns (uint256) {
        UserDeposit storage userDeposit = userDeposits[user];
        if (userDeposit.shares == 0) {
            return 0;
        }

        uint256 userShare = (userDeposit.shares * 1e18) / vaultStats.totalShares;
        uint256 totalYield = vaultStats.totalYieldGenerated;
        
        return (totalYield * userShare) / 1e18 + pendingYield[user];
    }

    function _getTotalValue() internal view returns (uint256) {
        return vaultStats.totalDeposits + vaultStats.totalYieldGenerated - 
            vaultStats.totalFeesCollected;
    }

    function _getTotalAllocated() internal view returns (uint256) {
        uint256 total = 0;
        for (uint256 i = 0; i < activeStrategies.length; i++) {
            total += strategies[activeStrategies[i]].allocatedAmount;
        }
        return total;
    }

    /**
     * @notice Get user's current position
     */
    function getUserPosition(address user)
        external
        view
        returns (
            uint256 depositedAmount,
            uint256 shares,
            uint256 currentValue,
            uint256 pendingYieldAmount
        )
    {
        UserDeposit storage userDeposit = userDeposits[user];
        return (
            userDeposit.amount,
            userDeposit.shares,
            _calculateWithdrawalAmount(userDeposit.shares),
            _calculateUserYield(user)
        );
    }

    /**
     * @notice Get strategy details
     */
    function getStrategy(bytes32 strategyId)
        external
        view
        returns (
            string memory name,
            StrategyType strategyType,
            StrategyStatus status,
            uint256 allocatedAmount,
            uint256 currentValue,
            uint256 totalYield,
            uint256 riskScore
        )
    {
        Strategy storage strategy = strategies[strategyId];
        return (
            strategy.name,
            strategy.strategyType,
            strategy.status,
            strategy.allocatedAmount,
            strategy.currentValue,
            strategy.totalYield,
            strategy.riskScore
        );
    }

    /**
     * @notice Get vault statistics
     */
    function getVaultStats()
        external
        view
        returns (
            uint256 totalDeposits,
            uint256 totalShares,
            uint256 totalYieldGenerated,
            uint256 totalFeesCollected,
            uint256 activeStrategyCount
        )
    {
        return (
            vaultStats.totalDeposits,
            vaultStats.totalShares,
            vaultStats.totalYieldGenerated,
            vaultStats.totalFeesCollected,
            activeStrategies.length
        );
    }

    /**
     * @notice Update risk parameters
     */
    function updateRiskParameters(
        uint256 _maxStrategyAllocation,
        uint256 _maxRiskScore,
        uint256 _maxDailyWithdrawal
    ) external onlyRole(DEFAULT_ADMIN_ROLE) {
        maxStrategyAllocation = _maxStrategyAllocation;
        maxRiskScore = _maxRiskScore;
        maxDailyWithdrawal = _maxDailyWithdrawal;
    }

    /**
     * @notice Update fee parameters
     */
    function updateFees(
        uint256 _withdrawalFee,
        uint256 _managementFee,
        uint256 _performanceFee
    ) external onlyRole(DEFAULT_ADMIN_ROLE) {
        require(_withdrawalFee <= 500, "Withdrawal fee too high"); // Max 5%
        require(_managementFee <= 500, "Management fee too high"); // Max 5%
        require(_performanceFee <= 3000, "Performance fee too high"); // Max 30%

        withdrawalFee = _withdrawalFee;
        managementFee = _managementFee;
        performanceFee = _performanceFee;
    }

    /**
     * @notice Pause vault operations
     */
    function pause() external onlyRole(GUARDIAN_ROLE) {
        _pause();
    }

    /**
     * @notice Unpause vault operations
     */
    function unpause() external onlyRole(DEFAULT_ADMIN_ROLE) {
        _unpause();
    }
}
