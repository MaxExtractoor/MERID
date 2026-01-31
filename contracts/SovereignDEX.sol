// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

/**
 * @title SovereignDEX
 * @notice Sovereign decentralized exchange for MERID ecosystem
 * @dev Implements order book, AMM hybrid with AI-driven routing
 */

import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import "@openzeppelin/contracts/access/AccessControl.sol";
import "@openzeppelin/contracts/security/ReentrancyGuard.sol";
import "@openzeppelin/contracts/security/Pausable.sol";

contract SovereignDEX is AccessControl, ReentrancyGuard, Pausable {
    using SafeERC20 for IERC20;

    // Roles
    bytes32 public constant OPERATOR_ROLE = keccak256("OPERATOR_ROLE");
    bytes32 public constant ROUTER_ROLE = keccak256("ROUTER_ROLE");
    bytes32 public constant GUARDIAN_ROLE = keccak256("GUARDIAN_ROLE");

    // Order types
    enum OrderType {
        Market,
        Limit,
        StopLoss,
        TakeProfit
    }

    // Order side
    enum OrderSide {
        Buy,
        Sell
    }

    // Order status
    enum OrderStatus {
        Open,
        PartiallyFilled,
        Filled,
        Cancelled,
        Expired
    }

    struct Order {
        bytes32 orderId;
        address trader;
        address baseToken;
        address quoteToken;
        OrderType orderType;
        OrderSide side;
        uint256 price;
        uint256 amount;
        uint256 filled;
        uint256 timestamp;
        uint256 expiry;
        OrderStatus status;
    }

    struct Pool {
        bytes32 poolId;
        address token0;
        address token1;
        uint256 reserve0;
        uint256 reserve1;
        uint256 totalLiquidity;
        uint256 fee; // basis points
        bool active;
    }

    struct LiquidityPosition {
        uint256 liquidity;
        uint256 token0Deposited;
        uint256 token1Deposited;
        uint256 timestamp;
    }

    // State variables
    mapping(bytes32 => Order) public orders;
    mapping(bytes32 => Pool) public pools;
    mapping(bytes32 => mapping(address => LiquidityPosition)) public liquidityPositions;
    mapping(address => bytes32[]) public userOrders;
    mapping(bytes32 => bytes32[]) public orderBook; // poolId => orderIds

    bytes32[] public allPools;
    uint256 public orderCount;
    uint256 public defaultFee = 30; // 0.3%
    uint256 public protocolFee = 5; // 0.05% to protocol

    // Trading limits
    uint256 public minOrderSize = 1e15; // 0.001 tokens
    uint256 public maxSlippage = 500; // 5%

    // Events
    event OrderPlaced(
        bytes32 indexed orderId,
        address indexed trader,
        bytes32 indexed poolId,
        OrderType orderType,
        OrderSide side,
        uint256 price,
        uint256 amount
    );
    event OrderFilled(
        bytes32 indexed orderId,
        uint256 filledAmount,
        uint256 price
    );
    event OrderCancelled(bytes32 indexed orderId);
    event PoolCreated(
        bytes32 indexed poolId,
        address token0,
        address token1,
        uint256 fee
    );
    event LiquidityAdded(
        bytes32 indexed poolId,
        address indexed provider,
        uint256 amount0,
        uint256 amount1,
        uint256 liquidity
    );
    event LiquidityRemoved(
        bytes32 indexed poolId,
        address indexed provider,
        uint256 amount0,
        uint256 amount1
    );
    event Swap(
        bytes32 indexed poolId,
        address indexed trader,
        address tokenIn,
        address tokenOut,
        uint256 amountIn,
        uint256 amountOut
    );

    constructor() {
        _grantRole(DEFAULT_ADMIN_ROLE, msg.sender);
        _grantRole(OPERATOR_ROLE, msg.sender);
        _grantRole(ROUTER_ROLE, msg.sender);
        _grantRole(GUARDIAN_ROLE, msg.sender);
    }

    /**
     * @notice Create a new liquidity pool
     */
    function createPool(
        address token0,
        address token1,
        uint256 fee
    ) external onlyRole(OPERATOR_ROLE) returns (bytes32) {
        require(token0 != token1, "Same token");
        require(fee <= 1000, "Fee too high"); // Max 10%

        // Sort tokens
        if (token0 > token1) {
            (token0, token1) = (token1, token0);
        }

        bytes32 poolId = keccak256(abi.encodePacked(token0, token1));
        require(pools[poolId].poolId == bytes32(0), "Pool exists");

        pools[poolId] = Pool({
            poolId: poolId,
            token0: token0,
            token1: token1,
            reserve0: 0,
            reserve1: 0,
            totalLiquidity: 0,
            fee: fee,
            active: true
        });

        allPools.push(poolId);

        emit PoolCreated(poolId, token0, token1, fee);
        return poolId;
    }

    /**
     * @notice Add liquidity to a pool
     */
    function addLiquidity(
        bytes32 poolId,
        uint256 amount0Desired,
        uint256 amount1Desired,
        uint256 amount0Min,
        uint256 amount1Min
    ) external nonReentrant whenNotPaused returns (uint256 liquidity) {
        Pool storage pool = pools[poolId];
        require(pool.active, "Pool not active");

        uint256 amount0;
        uint256 amount1;

        if (pool.totalLiquidity == 0) {
            amount0 = amount0Desired;
            amount1 = amount1Desired;
            liquidity = _sqrt(amount0 * amount1);
        } else {
            uint256 amount1Optimal = (amount0Desired * pool.reserve1) / pool.reserve0;
            if (amount1Optimal <= amount1Desired) {
                require(amount1Optimal >= amount1Min, "Insufficient amount1");
                amount0 = amount0Desired;
                amount1 = amount1Optimal;
            } else {
                uint256 amount0Optimal = (amount1Desired * pool.reserve0) / pool.reserve1;
                require(amount0Optimal >= amount0Min, "Insufficient amount0");
                amount0 = amount0Optimal;
                amount1 = amount1Desired;
            }
            liquidity = _min(
                (amount0 * pool.totalLiquidity) / pool.reserve0,
                (amount1 * pool.totalLiquidity) / pool.reserve1
            );
        }

        require(liquidity > 0, "Insufficient liquidity");

        IERC20(pool.token0).safeTransferFrom(msg.sender, address(this), amount0);
        IERC20(pool.token1).safeTransferFrom(msg.sender, address(this), amount1);

        pool.reserve0 += amount0;
        pool.reserve1 += amount1;
        pool.totalLiquidity += liquidity;

        LiquidityPosition storage position = liquidityPositions[poolId][msg.sender];
        position.liquidity += liquidity;
        position.token0Deposited += amount0;
        position.token1Deposited += amount1;
        position.timestamp = block.timestamp;

        emit LiquidityAdded(poolId, msg.sender, amount0, amount1, liquidity);
    }

    /**
     * @notice Remove liquidity from a pool
     */
    function removeLiquidity(
        bytes32 poolId,
        uint256 liquidity,
        uint256 amount0Min,
        uint256 amount1Min
    ) external nonReentrant returns (uint256 amount0, uint256 amount1) {
        Pool storage pool = pools[poolId];
        LiquidityPosition storage position = liquidityPositions[poolId][msg.sender];

        require(position.liquidity >= liquidity, "Insufficient liquidity");

        amount0 = (liquidity * pool.reserve0) / pool.totalLiquidity;
        amount1 = (liquidity * pool.reserve1) / pool.totalLiquidity;

        require(amount0 >= amount0Min, "Insufficient amount0");
        require(amount1 >= amount1Min, "Insufficient amount1");

        position.liquidity -= liquidity;
        pool.reserve0 -= amount0;
        pool.reserve1 -= amount1;
        pool.totalLiquidity -= liquidity;

        IERC20(pool.token0).safeTransfer(msg.sender, amount0);
        IERC20(pool.token1).safeTransfer(msg.sender, amount1);

        emit LiquidityRemoved(poolId, msg.sender, amount0, amount1);
    }

    /**
     * @notice Execute a swap
     */
    function swap(
        bytes32 poolId,
        address tokenIn,
        uint256 amountIn,
        uint256 amountOutMin
    ) external nonReentrant whenNotPaused returns (uint256 amountOut) {
        Pool storage pool = pools[poolId];
        require(pool.active, "Pool not active");
        require(amountIn >= minOrderSize, "Order too small");

        bool isToken0 = tokenIn == pool.token0;
        require(isToken0 || tokenIn == pool.token1, "Invalid token");

        uint256 reserveIn = isToken0 ? pool.reserve0 : pool.reserve1;
        uint256 reserveOut = isToken0 ? pool.reserve1 : pool.reserve0;

        // Calculate output with fee
        uint256 amountInWithFee = amountIn * (10000 - pool.fee);
        amountOut = (amountInWithFee * reserveOut) / (reserveIn * 10000 + amountInWithFee);

        require(amountOut >= amountOutMin, "Slippage exceeded");

        // Check slippage
        uint256 priceImpact = (amountOut * 10000) / reserveOut;
        require(priceImpact <= maxSlippage, "Price impact too high");

        // Transfer tokens
        IERC20(tokenIn).safeTransferFrom(msg.sender, address(this), amountIn);

        address tokenOut = isToken0 ? pool.token1 : pool.token0;
        IERC20(tokenOut).safeTransfer(msg.sender, amountOut);

        // Update reserves
        if (isToken0) {
            pool.reserve0 += amountIn;
            pool.reserve1 -= amountOut;
        } else {
            pool.reserve1 += amountIn;
            pool.reserve0 -= amountOut;
        }

        emit Swap(poolId, msg.sender, tokenIn, tokenOut, amountIn, amountOut);
    }

    /**
     * @notice Place a limit order
     */
    function placeLimitOrder(
        bytes32 poolId,
        OrderSide side,
        uint256 price,
        uint256 amount,
        uint256 expiry
    ) external nonReentrant whenNotPaused returns (bytes32) {
        Pool storage pool = pools[poolId];
        require(pool.active, "Pool not active");
        require(amount >= minOrderSize, "Order too small");
        require(expiry > block.timestamp, "Invalid expiry");

        orderCount++;
        bytes32 orderId = keccak256(
            abi.encodePacked(msg.sender, poolId, orderCount, block.timestamp)
        );

        // Lock tokens
        address tokenToLock = side == OrderSide.Buy ? pool.token1 : pool.token0;
        uint256 amountToLock = side == OrderSide.Buy ? (amount * price) / 1e18 : amount;
        IERC20(tokenToLock).safeTransferFrom(msg.sender, address(this), amountToLock);

        orders[orderId] = Order({
            orderId: orderId,
            trader: msg.sender,
            baseToken: pool.token0,
            quoteToken: pool.token1,
            orderType: OrderType.Limit,
            side: side,
            price: price,
            amount: amount,
            filled: 0,
            timestamp: block.timestamp,
            expiry: expiry,
            status: OrderStatus.Open
        });

        userOrders[msg.sender].push(orderId);
        orderBook[poolId].push(orderId);

        emit OrderPlaced(orderId, msg.sender, poolId, OrderType.Limit, side, price, amount);
        return orderId;
    }

    /**
     * @notice Cancel an order
     */
    function cancelOrder(bytes32 orderId) external nonReentrant {
        Order storage order = orders[orderId];
        require(order.trader == msg.sender, "Not order owner");
        require(
            order.status == OrderStatus.Open || 
            order.status == OrderStatus.PartiallyFilled,
            "Cannot cancel"
        );

        uint256 remainingAmount = order.amount - order.filled;
        address tokenToReturn = order.side == OrderSide.Buy ? 
            order.quoteToken : order.baseToken;
        uint256 amountToReturn = order.side == OrderSide.Buy ? 
            (remainingAmount * order.price) / 1e18 : remainingAmount;

        order.status = OrderStatus.Cancelled;

        IERC20(tokenToReturn).safeTransfer(msg.sender, amountToReturn);

        emit OrderCancelled(orderId);
    }

    /**
     * @notice Match orders (called by router)
     */
    function matchOrders(
        bytes32 buyOrderId,
        bytes32 sellOrderId,
        uint256 matchAmount,
        uint256 matchPrice
    ) external onlyRole(ROUTER_ROLE) nonReentrant {
        Order storage buyOrder = orders[buyOrderId];
        Order storage sellOrder = orders[sellOrderId];

        require(buyOrder.status == OrderStatus.Open || 
            buyOrder.status == OrderStatus.PartiallyFilled, "Buy order not open");
        require(sellOrder.status == OrderStatus.Open || 
            sellOrder.status == OrderStatus.PartiallyFilled, "Sell order not open");
        require(buyOrder.price >= sellOrder.price, "Price mismatch");

        uint256 buyRemaining = buyOrder.amount - buyOrder.filled;
        uint256 sellRemaining = sellOrder.amount - sellOrder.filled;
        uint256 fillAmount = _min(_min(buyRemaining, sellRemaining), matchAmount);

        uint256 quoteAmount = (fillAmount * matchPrice) / 1e18;

        // Update orders
        buyOrder.filled += fillAmount;
        sellOrder.filled += fillAmount;

        if (buyOrder.filled == buyOrder.amount) {
            buyOrder.status = OrderStatus.Filled;
        } else {
            buyOrder.status = OrderStatus.PartiallyFilled;
        }

        if (sellOrder.filled == sellOrder.amount) {
            sellOrder.status = OrderStatus.Filled;
        } else {
            sellOrder.status = OrderStatus.PartiallyFilled;
        }

        // Transfer tokens
        IERC20(buyOrder.baseToken).safeTransfer(buyOrder.trader, fillAmount);
        IERC20(sellOrder.quoteToken).safeTransfer(sellOrder.trader, quoteAmount);

        emit OrderFilled(buyOrderId, fillAmount, matchPrice);
        emit OrderFilled(sellOrderId, fillAmount, matchPrice);
    }

    /**
     * @notice Get quote for swap
     */
    function getQuote(
        bytes32 poolId,
        address tokenIn,
        uint256 amountIn
    ) external view returns (uint256 amountOut, uint256 priceImpact) {
        Pool storage pool = pools[poolId];
        
        bool isToken0 = tokenIn == pool.token0;
        uint256 reserveIn = isToken0 ? pool.reserve0 : pool.reserve1;
        uint256 reserveOut = isToken0 ? pool.reserve1 : pool.reserve0;

        uint256 amountInWithFee = amountIn * (10000 - pool.fee);
        amountOut = (amountInWithFee * reserveOut) / (reserveIn * 10000 + amountInWithFee);
        priceImpact = (amountOut * 10000) / reserveOut;
    }

    /**
     * @notice Get pool info
     */
    function getPool(bytes32 poolId)
        external
        view
        returns (
            address token0,
            address token1,
            uint256 reserve0,
            uint256 reserve1,
            uint256 totalLiquidity,
            uint256 fee
        )
    {
        Pool storage pool = pools[poolId];
        return (
            pool.token0,
            pool.token1,
            pool.reserve0,
            pool.reserve1,
            pool.totalLiquidity,
            pool.fee
        );
    }

    /**
     * @notice Get user's liquidity position
     */
    function getLiquidityPosition(bytes32 poolId, address user)
        external
        view
        returns (
            uint256 liquidity,
            uint256 token0Deposited,
            uint256 token1Deposited
        )
    {
        LiquidityPosition storage position = liquidityPositions[poolId][user];
        return (
            position.liquidity,
            position.token0Deposited,
            position.token1Deposited
        );
    }

    /**
     * @notice Get order details
     */
    function getOrder(bytes32 orderId)
        external
        view
        returns (
            address trader,
            OrderType orderType,
            OrderSide side,
            uint256 price,
            uint256 amount,
            uint256 filled,
            OrderStatus status
        )
    {
        Order storage order = orders[orderId];
        return (
            order.trader,
            order.orderType,
            order.side,
            order.price,
            order.amount,
            order.filled,
            order.status
        );
    }

    /**
     * @notice Update pool fee
     */
    function updatePoolFee(bytes32 poolId, uint256 newFee)
        external
        onlyRole(OPERATOR_ROLE)
    {
        require(newFee <= 1000, "Fee too high");
        pools[poolId].fee = newFee;
    }

    /**
     * @notice Toggle pool active status
     */
    function setPoolActive(bytes32 poolId, bool active)
        external
        onlyRole(OPERATOR_ROLE)
    {
        pools[poolId].active = active;
    }

    /**
     * @notice Update trading limits
     */
    function updateLimits(uint256 _minOrderSize, uint256 _maxSlippage)
        external
        onlyRole(DEFAULT_ADMIN_ROLE)
    {
        minOrderSize = _minOrderSize;
        maxSlippage = _maxSlippage;
    }

    /**
     * @notice Pause trading
     */
    function pause() external onlyRole(GUARDIAN_ROLE) {
        _pause();
    }

    /**
     * @notice Unpause trading
     */
    function unpause() external onlyRole(DEFAULT_ADMIN_ROLE) {
        _unpause();
    }

    // Internal functions
    function _sqrt(uint256 y) internal pure returns (uint256 z) {
        if (y > 3) {
            z = y;
            uint256 x = y / 2 + 1;
            while (x < z) {
                z = x;
                x = (y / x + x) / 2;
            }
        } else if (y != 0) {
            z = 1;
        }
    }

    function _min(uint256 a, uint256 b) internal pure returns (uint256) {
        return a < b ? a : b;
    }
}
