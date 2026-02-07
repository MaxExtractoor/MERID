"""On-chain analytics aggregators (Glassnode, Santiment)."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

import httpx

from utils.logger import get_logger

logger = get_logger("monitoring.onchain")


@dataclass
class OnchainSnapshot:
    timestamp_ms: float
    nupl: Optional[float]
    mvrv: Optional[float]
    exchange_netflow: Optional[float]
    sentiment_score: Optional[float]
    whale_tx_count: Optional[int]
    dev_activity: Optional[int]
    metadata: Dict[str, float]


class OnchainAnalyticsMonitor:
    """Fetch Glassnode + Santiment metrics (with mock fallbacks)."""

    def __init__(
        self,
        *,
        glassnode_key: Optional[str] = None,
        santiment_key: Optional[str] = None,
        asset: str = "BTC",
    ) -> None:
        self.glassnode_key = glassnode_key or os.getenv("MERID_GLASSNODE_API_KEY")
        self.santiment_key = santiment_key or os.getenv("MERID_SANTIMENT_API_KEY")
        self.asset = asset
        self.use_mock = not bool(self.glassnode_key and self.santiment_key)
        self._client = httpx.Client(timeout=10.0)

    def fetch_snapshot(self) -> OnchainSnapshot:
        if self.use_mock:
            return self._mock_snapshot()
        nupl = self._fetch_glassnode_metric("nupl")
        mvrv = self._fetch_glassnode_metric("mvrv_z_score")
        exchange_flow = self._fetch_glassnode_metric("exchange_net_position_change")
        sentiment = self._fetch_santiment_metric("sentiment")
        whale_tx = self._fetch_santiment_metric("whale_transactions_count")
        dev_activity = self._fetch_santiment_metric("dev_activity")
        return OnchainSnapshot(
            timestamp_ms=time.time() * 1000,
            nupl=nupl,
            mvrv=mvrv,
            exchange_netflow=exchange_flow,
            sentiment_score=sentiment,
            whale_tx_count=int(whale_tx) if whale_tx is not None else None,
            dev_activity=int(dev_activity) if dev_activity is not None else None,
            metadata={},
        )

    def _fetch_glassnode_metric(self, metric: str) -> Optional[float]:
        endpoint = f"https://api.glassnode.com/v1/metrics/indicators/{metric}"
        params = {
            "api_key": self.glassnode_key,
            "a": self.asset,
            "i": "24h",
        }
        try:
            resp = self._client.get(endpoint, params=params)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list) and data:
                return float(data[-1].get("v"))
        except Exception as exc:
            logger.debug("Glassnode metric %s unavailable: %s", metric, exc)
        return None

    def _fetch_santiment_metric(self, metric: str) -> Optional[float]:
        endpoint = f"https://api.santiment.net/graphql"
        query = """
        {
          getMetric(metric: "%s") {
            timeseriesData(
              slug: "%s"
              from: "utc_now-1d"
              to: "utc_now"
              interval: "1d"
            ) {
              values {
                value
              }
            }
          }
        }
        """ % (
            metric,
            self.asset.lower(),
        )
        try:
            resp = self._client.post(
                endpoint,
                json={"query": query},
                headers={"Authorization": f"Apikey {self.santiment_key}"},
            )
            resp.raise_for_status()
            data = resp.json()
            values = data.get("data", {}).get("getMetric", {}).get("timeseriesData", {}).get("values", [])
            if values:
                return float(values[-1].get("value"))
        except Exception as exc:
            logger.debug("Santiment metric %s unavailable: %s", metric, exc)
        return None

    def _mock_snapshot(self) -> OnchainSnapshot:
        """Return neutral snapshot when no API key - no fake data."""
        # Return neutral values - no random fake data
        # Real data requires Santiment API key
        logger.debug("No Santiment API key configured - onchain data unavailable")
        return OnchainSnapshot(
            timestamp_ms=time.time() * 1000,
            nupl=0.0,
            mvrv=0.0,
            exchange_netflow=0.0,
            sentiment_score=0.0,
            whale_tx_count=0,
            dev_activity=0,
            metadata={"unavailable": True, "reason": "No API key configured"},
        )
