"""CLI entrypoint that runs the Prime Screen explainer worker."""
from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from web.api.prime_screen import PrimeScreenStore
from web.services.decision_explainer import DecisionExplainerService


async def _run(args) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    store = PrimeScreenStore(Path(args.store))
    worker = DecisionExplainerService(
        store,
        batch_size=args.batch_size,
        sleep_seconds=args.sleep,
    )
    await worker.run_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="Prime Screen explainer worker")
    parser.add_argument(
        "--store",
        default="data/prime_screen_store.json",
        help="Path to Prime Screen JSON store",
    )
    parser.add_argument("--batch-size", type=int, default=3)
    parser.add_argument("--sleep", type=float, default=2.0)
    args = parser.parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
