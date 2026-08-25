"""Preflight check for the Kalshi CF-RTI WebSocket feed.

Connects to the authenticated ``cfbenchmarks_value`` channel using the same
config and credentials as the production server, logs the indexlist response,
and records the first frame for each configured crypto asset.
"""
from __future__ import annotations

import asyncio
import os
from typing import Any, Dict, Tuple

from merid.data.kalshi_cf_rti_ws import KalshiCfRtiStream, index_id_to_asset

os.environ["MERID_CFB_RTI_ADAPTER"] = "true"
os.environ["MERID_CFB_RTI_SOURCE"] = "kalshi_ws"

FIRST_FRAMES: Dict[str, Tuple[str, Dict[str, Any]]] = {}


def _on_frame(frame):
    asset = index_id_to_asset(frame.index_id)
    if not asset:
        print(f"  unknown index_id={frame.index_id} data={list(frame.data.keys())}")
        return
    if asset not in FIRST_FRAMES:
        FIRST_FRAMES[asset] = (frame.index_id, frame.data.copy())
        print(
            f"  FIRST {asset}: index_id={frame.index_id} "
            f"value={frame.data.get('value')} "
            f"time={frame.data.get('time')} "
            f"received_at={frame.data.get('received_at')} "
            f"avg_60s={frame.data.get('average_60s')} "
            f"seq={frame.data.get('seq')}"
        )


async def main() -> None:
    stream = KalshiCfRtiStream(on_frame=_on_frame)

    print(f"[PREFLIGHT] connecting to {stream.ws_url}")
    await stream._connect()
    print("[PREFLIGHT] connected")

    await stream._subscribe_and_indexlist(timeout=15)
    print(f"[PREFLIGHT] indexlist: {stream._index_ids}")

    stream._running = True
    try:
        await asyncio.wait_for(stream._process_messages(), timeout=45)
    except asyncio.TimeoutError:
        pass
    finally:
        if stream._ws:
            await stream._ws.close()

    print("\n[PREFLIGHT] summary")
    for asset in ("BTC", "ETH", "SOL", "XRP", "DOGE"):
        frame = FIRST_FRAMES.get(asset)
        if frame:
            print(f"  {asset}: OK index_id={frame[0]} data={list(frame[1].keys())}")
        else:
            print(f"  {asset}: NO FRAME")


if __name__ == "__main__":
    asyncio.run(main())
