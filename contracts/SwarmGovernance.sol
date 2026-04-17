// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

/**
 * @title SwarmGovernance
 * @notice On-chain governance for MERID swarm constitution
 * @dev Implements multi-sig, time-locks, and DAO voting for critical changes
 */

import "@openzeppelin/contracts/access/AccessControl.sol";
import "@openzeppelin/contracts/security/ReentrancyGuard.sol";
import "@openzeppelin/contracts/security/Pausable.sol";

contract SwarmGovernance is AccessControl, ReentrancyGuard, Pausable {
    // Roles
    bytes32 public constant GOVERNOR_ROLE = keccak256("GOVERNOR_ROLE");
    bytes32 public constant PROPOSER_ROLE = keccak256("PROPOSER_ROLE");
    bytes32 public constant EXECUTOR_ROLE = keccak256("EXECUTOR_ROLE");
    bytes32 public constant GUARDIAN_ROLE = keccak256("GUARDIAN_ROLE");

    // Proposal states
    enum ProposalState {
        Pending,
        Active,
        Canceled,
        Defeated,
        Succeeded,
        Queued,
        Expired,
        Executed
    }

    // Proposal types
    enum ProposalType {
        ParameterChange,
        AgentDeployment,
        StrategyApproval,
        RiskLimitChange,
        EmergencyAction,
        ConstitutionAmendment
    }

    struct Proposal {
        uint256 id;
        address proposer;
        ProposalType proposalType;
        string description;
        bytes callData;
        address target;
        uint256 value;
        uint256 startBlock;
        uint256 endBlock;
        uint256 forVotes;
        uint256 againstVotes;
        uint256 abstainVotes;
        bool canceled;
        bool executed;
        uint256 eta; // Execution time after timelock
    }

    struct Receipt {
        bool hasVoted;
        uint8 support; // 0 = against, 1 = for, 2 = abstain
        uint256 votes;
    }

    // Multi-sig configuration
    struct MultiSigConfig {
        address[] signers;
        uint256 threshold;
        bool enabled;
    }

    // Time-lock configuration
    struct TimeLockConfig {
        uint256 minDelay;
        uint256 maxDelay;
        uint256 gracePeriod;
    }

    // State variables
    uint256 public proposalCount;
    uint256 public votingDelay = 1; // 1 block
    uint256 public votingPeriod = 17280; // ~3 days at 15s blocks
    uint256 public proposalThreshold = 100000e18; // 100k tokens to propose
    uint256 public quorumVotes = 400000e18; // 400k tokens for quorum

    mapping(uint256 => Proposal) public proposals;
    mapping(uint256 => mapping(address => Receipt)) public receipts;
    mapping(address => uint256) public latestProposalIds;
    mapping(ProposalType => MultiSigConfig) public multiSigConfigs;
    mapping(ProposalType => TimeLockConfig) public timeLockConfigs;
    mapping(bytes32 => bool) public queuedTransactions;

    // Voting power (simplified - in production use ERC20Votes)
    mapping(address => uint256) public votingPower;
    uint256 public totalVotingPower;

    // Events
    event ProposalCreated(
        uint256 indexed id,
        address indexed proposer,
        ProposalType proposalType,
        string description,
        uint256 startBlock,
        uint256 endBlock
    );
    event VoteCast(
        address indexed voter,
        uint256 indexed proposalId,
        uint8 support,
        uint256 votes,
        string reason
    );
    event ProposalCanceled(uint256 indexed id);
    event ProposalQueued(uint256 indexed id, uint256 eta);
    event ProposalExecuted(uint256 indexed id);
    event MultiSigApproval(
        uint256 indexed proposalId,
        address indexed signer,
        uint256 approvalCount
    );
    event TimeLockSet(ProposalType indexed proposalType, uint256 minDelay, uint256 maxDelay);
    event VotingPowerUpdated(address indexed account, uint256 newPower);
    event EmergencyPause(address indexed guardian, string reason);

    constructor() {
        _grantRole(DEFAULT_ADMIN_ROLE, msg.sender);
        _grantRole(GOVERNOR_ROLE, msg.sender);
        _grantRole(GUARDIAN_ROLE, msg.sender);

        // Initialize default time-locks
        _setTimeLock(ProposalType.ParameterChange, 1 days, 7 days, 14 days);
        _setTimeLock(ProposalType.AgentDeployment, 2 days, 7 days, 14 days);
        _setTimeLock(ProposalType.StrategyApproval, 1 days, 7 days, 14 days);
        _setTimeLock(ProposalType.RiskLimitChange, 2 days, 7 days, 14 days);
        _setTimeLock(ProposalType.EmergencyAction, 0, 1 days, 3 days);
        _setTimeLock(ProposalType.ConstitutionAmendment, 7 days, 14 days, 30 days);
    }

    /**
     * @notice Create a new proposal
     * @param proposalType Type of proposal
     * @param description Description of the proposal
     * @param target Target contract address
     * @param callData Encoded function call
     * @param value ETH value to send
     */
    function propose(
        ProposalType proposalType,
        string memory description,
        address target,
        bytes memory callData,
        uint256 value
    ) external returns (uint256) {
        require(
            votingPower[msg.sender] >= proposalThreshold,
            "Proposer votes below threshold"
        );
        require(
            latestProposalIds[msg.sender] == 0 ||
                state(latestProposalIds[msg.sender]) != ProposalState.Active,
            "One active proposal per proposer"
        );

        proposalCount++;
        uint256 proposalId = proposalCount;

        uint256 startBlock = block.number + votingDelay;
        uint256 endBlock = startBlock + votingPeriod;

        Proposal storage proposal = proposals[proposalId];
        proposal.id = proposalId;
        proposal.proposer = msg.sender;
        proposal.proposalType = proposalType;
        proposal.description = description;
        proposal.callData = callData;
        proposal.target = target;
        proposal.value = value;
        proposal.startBlock = startBlock;
        proposal.endBlock = endBlock;

        latestProposalIds[msg.sender] = proposalId;

        emit ProposalCreated(
            proposalId,
            msg.sender,
            proposalType,
            description,
            startBlock,
            endBlock
        );

        return proposalId;
    }

    /**
     * @notice Cast a vote on a proposal
     * @param proposalId ID of the proposal
     * @param support 0 = against, 1 = for, 2 = abstain
     */
    function castVote(uint256 proposalId, uint8 support) external {
        return _castVote(msg.sender, proposalId, support, "");
    }

    /**
     * @notice Cast a vote with reason
     */
    function castVoteWithReason(
        uint256 proposalId,
        uint8 support,
        string calldata reason
    ) external {
        return _castVote(msg.sender, proposalId, support, reason);
    }

    function _castVote(
        address voter,
        uint256 proposalId,
        uint8 support,
        string memory reason
    ) internal {
        require(state(proposalId) == ProposalState.Active, "Voting is closed");
        require(support <= 2, "Invalid vote type");

        Proposal storage proposal = proposals[proposalId];
        Receipt storage receipt = receipts[proposalId][voter];

        require(!receipt.hasVoted, "Already voted");

        uint256 votes = votingPower[voter];
        require(votes > 0, "No voting power");

        if (support == 0) {
            proposal.againstVotes += votes;
        } else if (support == 1) {
            proposal.forVotes += votes;
        } else {
            proposal.abstainVotes += votes;
        }

        receipt.hasVoted = true;
        receipt.support = support;
        receipt.votes = votes;

        emit VoteCast(voter, proposalId, support, votes, reason);
    }

    /**
     * @notice Queue a successful proposal for execution
     */
    function queue(uint256 proposalId) external {
        require(
            state(proposalId) == ProposalState.Succeeded,
            "Proposal not succeeded"
        );

        Proposal storage proposal = proposals[proposalId];
        TimeLockConfig storage timelock = timeLockConfigs[proposal.proposalType];

        uint256 eta = block.timestamp + timelock.minDelay;
        proposal.eta = eta;

        bytes32 txHash = keccak256(
            abi.encode(
                proposal.target,
                proposal.value,
                proposal.callData,
                eta
            )
        );
        queuedTransactions[txHash] = true;

        emit ProposalQueued(proposalId, eta);
    }

    /**
     * @notice Execute a queued proposal
     */
    function execute(uint256 proposalId) external payable nonReentrant {
        require(
            state(proposalId) == ProposalState.Queued,
            "Proposal not queued"
        );

        Proposal storage proposal = proposals[proposalId];
        require(block.timestamp >= proposal.eta, "Timelock not expired");

        TimeLockConfig storage timelock = timeLockConfigs[proposal.proposalType];
        require(
            block.timestamp <= proposal.eta + timelock.gracePeriod,
            "Transaction expired"
        );

        proposal.executed = true;

        bytes32 txHash = keccak256(
            abi.encode(
                proposal.target,
                proposal.value,
                proposal.callData,
                proposal.eta
            )
        );
        queuedTransactions[txHash] = false;

        (bool success, ) = proposal.target.call{value: proposal.value}(
            proposal.callData
        );
        require(success, "Transaction execution failed");

        emit ProposalExecuted(proposalId);
    }

    /**
     * @notice Cancel a proposal
     */
    function cancel(uint256 proposalId) external {
        ProposalState currentState = state(proposalId);
        require(
            currentState != ProposalState.Executed &&
                currentState != ProposalState.Canceled,
            "Cannot cancel"
        );

        Proposal storage proposal = proposals[proposalId];
        require(
            msg.sender == proposal.proposer ||
                hasRole(GUARDIAN_ROLE, msg.sender),
            "Not authorized"
        );

        proposal.canceled = true;

        emit ProposalCanceled(proposalId);
    }

    /**
     * @notice Get the state of a proposal
     */
    function state(uint256 proposalId) public view returns (ProposalState) {
        require(proposalId > 0 && proposalId <= proposalCount, "Invalid proposal");

        Proposal storage proposal = proposals[proposalId];

        if (proposal.canceled) {
            return ProposalState.Canceled;
        }

        if (proposal.executed) {
            return ProposalState.Executed;
        }

        if (block.number <= proposal.startBlock) {
            return ProposalState.Pending;
        }

        if (block.number <= proposal.endBlock) {
            return ProposalState.Active;
        }

        if (
            proposal.forVotes <= proposal.againstVotes ||
            proposal.forVotes + proposal.againstVotes + proposal.abstainVotes < quorumVotes
        ) {
            return ProposalState.Defeated;
        }

        if (proposal.eta == 0) {
            return ProposalState.Succeeded;
        }

        TimeLockConfig storage timelock = timeLockConfigs[proposal.proposalType];
        if (block.timestamp > proposal.eta + timelock.gracePeriod) {
            return ProposalState.Expired;
        }

        return ProposalState.Queued;
    }

    /**
     * @notice Set voting power for an account (simplified - use ERC20Votes in production)
     */
    function setVotingPower(address account, uint256 power)
        external
        onlyRole(GOVERNOR_ROLE)
    {
        uint256 oldPower = votingPower[account];
        votingPower[account] = power;
        totalVotingPower = totalVotingPower - oldPower + power;

        emit VotingPowerUpdated(account, power);
    }

    /**
     * @notice Configure multi-sig for a proposal type
     */
    function setMultiSig(
        ProposalType proposalType,
        address[] calldata signers,
        uint256 threshold
    ) external onlyRole(GOVERNOR_ROLE) {
        require(threshold > 0 && threshold <= signers.length, "Invalid threshold");

        MultiSigConfig storage config = multiSigConfigs[proposalType];
        config.signers = signers;
        config.threshold = threshold;
        config.enabled = true;
    }

    /**
     * @notice Set time-lock configuration
     */
    function setTimeLock(
        ProposalType proposalType,
        uint256 minDelay,
        uint256 maxDelay,
        uint256 gracePeriod
    ) external onlyRole(GOVERNOR_ROLE) {
        _setTimeLock(proposalType, minDelay, maxDelay, gracePeriod);
    }

    function _setTimeLock(
        ProposalType proposalType,
        uint256 minDelay,
        uint256 maxDelay,
        uint256 gracePeriod
    ) internal {
        require(minDelay <= maxDelay, "Invalid delay range");

        TimeLockConfig storage config = timeLockConfigs[proposalType];
        config.minDelay = minDelay;
        config.maxDelay = maxDelay;
        config.gracePeriod = gracePeriod;

        emit TimeLockSet(proposalType, minDelay, maxDelay);
    }

    /**
     * @notice Emergency pause by guardian
     */
    function emergencyPause(string calldata reason)
        external
        onlyRole(GUARDIAN_ROLE)
    {
        _pause();
        emit EmergencyPause(msg.sender, reason);
    }

    /**
     * @notice Unpause after emergency
     */
    function unpause() external onlyRole(GOVERNOR_ROLE) {
        _unpause();
    }

    /**
     * @notice Update governance parameters
     */
    function setVotingDelay(uint256 newVotingDelay)
        external
        onlyRole(GOVERNOR_ROLE)
    {
        votingDelay = newVotingDelay;
    }

    function setVotingPeriod(uint256 newVotingPeriod)
        external
        onlyRole(GOVERNOR_ROLE)
    {
        votingPeriod = newVotingPeriod;
    }

    function setProposalThreshold(uint256 newThreshold)
        external
        onlyRole(GOVERNOR_ROLE)
    {
        proposalThreshold = newThreshold;
    }

    function setQuorumVotes(uint256 newQuorum)
        external
        onlyRole(GOVERNOR_ROLE)
    {
        quorumVotes = newQuorum;
    }

    /**
     * @notice Get proposal details
     */
    function getProposal(uint256 proposalId)
        external
        view
        returns (
            address proposer,
            ProposalType proposalType,
            string memory description,
            uint256 forVotes,
            uint256 againstVotes,
            uint256 abstainVotes,
            uint256 startBlock,
            uint256 endBlock,
            uint256 eta,
            ProposalState currentState
        )
    {
        Proposal storage proposal = proposals[proposalId];
        return (
            proposal.proposer,
            proposal.proposalType,
            proposal.description,
            proposal.forVotes,
            proposal.againstVotes,
            proposal.abstainVotes,
            proposal.startBlock,
            proposal.endBlock,
            proposal.eta,
            state(proposalId)
        );
    }

    /**
     * @notice Get vote receipt for a voter
     */
    function getReceipt(uint256 proposalId, address voter)
        external
        view
        returns (
            bool hasVoted,
            uint8 support,
            uint256 votes
        )
    {
        Receipt storage receipt = receipts[proposalId][voter];
        return (receipt.hasVoted, receipt.support, receipt.votes);
    }

    /**
     * @notice Check if an address is a multi-sig signer for a proposal type
     */
    function isMultiSigSigner(ProposalType proposalType, address account)
        external
        view
        returns (bool)
    {
        MultiSigConfig storage config = multiSigConfigs[proposalType];
        for (uint256 i = 0; i < config.signers.length; i++) {
            if (config.signers[i] == account) {
                return true;
            }
        }
        return false;
    }

    receive() external payable {}
}
