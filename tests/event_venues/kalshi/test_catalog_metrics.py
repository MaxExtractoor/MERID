import time
import pytest

from monitoring import kalshi_metrics


@pytest.fixture(autouse=True)
def reset_kalshi_collector():
    kalshi_metrics._collector = None  # type: ignore[attr-defined]
    yield
    kalshi_metrics._collector = None  # type: ignore[attr-defined]


def test_catalog_refresh_timestamp_gauge_updates():
    collector = kalshi_metrics.get_kalshi_metrics_collector()

    initial = collector.catalog_last_refresh_timestamp.get()
    assert initial == 0

    ts = time.time()
    kalshi_metrics.set_kalshi_catalog_refresh_timestamp(ts)

    assert collector.catalog_last_refresh_timestamp.get() == pytest.approx(ts)
