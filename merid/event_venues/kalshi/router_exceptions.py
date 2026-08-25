"""Typed exceptions raised by the Kalshi order router.

These live in a dedicated module so that ``importlib.reload`` of
``order_router`` does not create a new exception class object, which would
break ``isinstance``/``pytest.raises`` checks in tests and other modules.
"""


class RepriceWouldCross(Exception):
    """Raised when price adjustment would cross the spread for the intended role.

    This is a typed rejection for the repricing/planning stage. It carries enough
    context to release the slot reservation exactly once and log the failure.
    """

    def __init__(
        self,
        ticker: str,
        side: str,
        action: str,
        role: str,
        attempted_price: int,
        side_bid: int | None,
        side_ask: int | None,
        reason: str,
    ) -> None:
        super().__init__(
            f"[REPRICE-WOULD-CROSS] {ticker} {role} {action} {side} "
            f"attempted={attempted_price}c "
            f"bid={side_bid}c ask={side_ask}c: {reason}"
        )
        self.ticker = ticker
        self.side = side
        self.action = action
        self.role = role
        self.attempted_price = attempted_price
        self.side_bid = side_bid
        self.side_ask = side_ask
        self.reason = reason
