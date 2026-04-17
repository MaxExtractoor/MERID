"""Replay harness safety oracle for pipeline equivalence checking.

Provides PipelineSnapshot dataclass and ReplayHarness class to assert
that live PRE-ORDER logs match replay output, detecting pipeline divergence.
"""

from dataclasses import dataclass
from typing import List, Dict, Any
import logging

logger = logging.getLogger(__name__)


@dataclass
class PipelineSnapshot:
    """Golden snapshot for replay equivalence checking."""

    candidate_count: int
    per_bucket_stats: Dict[str, int]  # bucket -> candidate count
    selected_orders: List[dict]
    timestamp: str


class ReplayHarness:
    """Safety oracle: assert live PRE-ORDER logs match replay output."""

    def assert_equivalence(
        self,
        live: PipelineSnapshot,
        replay: PipelineSnapshot,
    ) -> None:
        """Assert equivalence between live and replay snapshots.

        Hard-fails on divergence with [PIPELINE-DIVERGENCE] log marker.

        Args:
            live: Snapshot from live PRE-ORDER logs.
            replay: Snapshot from replay output.

        Raises:
            RuntimeError: If any metric diverges between live and replay.
        """
        mismatches: List[str] = []

        if live.candidate_count != replay.candidate_count:
            mismatches.append(
                f"candidates: live={live.candidate_count}, replay={replay.candidate_count}"
            )

        for bucket in live.per_bucket_stats:
            live_cnt = live.per_bucket_stats.get(bucket, 0)
            rep_cnt = replay.per_bucket_stats.get(bucket, 0)
            if live_cnt != rep_cnt:
                mismatches.append(
                    f"bucket[{bucket}]: live={live_cnt}, replay={rep_cnt}"
                )

        if mismatches:
            logger.error(
                "[PIPELINE-DIVERGENCE] context=%s mismatches=%s",
                live.timestamp,
                mismatches,
            )
            raise RuntimeError(f"Pipeline divergence detected: {mismatches}")
