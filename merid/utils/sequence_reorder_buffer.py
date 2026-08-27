"""Per-channel sequence reorder buffer for deterministic ingest ordering.

Single-writer by design: only the drain task calls into this.  Release order is
a pure function of the ``(channel, seq)`` stream -- never wall-clock arrival --
so replay is reproducible.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


class ResyncRequired(Exception):
    """Raised when a channel's gap grows past ``max_buffered``.

    The caller must re-establish a base via ``reset()`` (e.g. fetch a fresh
    snapshot).
    """

    def __init__(self, channel: str):
        self.channel = channel
        super().__init__(f"channel {channel!r} requires resync: gap too large")


class SequenceReorderBuffer:
    def __init__(self, max_buffered: int = 4096):
        self._max_buffered = max_buffered
        self._next_seq: Dict[str, int] = {}  # channel -> next expected
        self._buffered: Dict[str, Dict[int, Any]] = {}  # channel -> {seq: event}

    def reset(self, channel: str, base_seq: int) -> None:
        """Establish a contiguous base for a channel (snapshot / full reset).

        ``base_seq`` is the last known contiguous sequence for the channel.
        The next expected sequence is ``base_seq + 1``.  Events already buffered
        with ``seq <= base_seq`` are discarded as stale; events with
        ``seq > base_seq`` remain in the buffer.
        """
        self._next_seq[channel] = base_seq + 1
        buf = self._buffered.setdefault(channel, {})
        self._buffered[channel] = {s: e for s, e in buf.items() if s > base_seq}

    def push(self, channel: str, seq: int, event: Any) -> List[Any]:
        """Feed one event; return events released in deterministic order.

        Returns an empty list when the event is buffered (gap ahead) or dropped
        (stale/duplicate already past the watermark).
        """
        next_expected = self._next_seq.get(channel)
        if next_expected is None:
            # No base yet (no snapshot).  Buffer and wait for reset().
            self._buffered.setdefault(channel, {})[seq] = event
            return []

        if seq < next_expected:
            return []  # stale / duplicate, watermark already passed it

        if seq == next_expected:
            self._next_seq[channel] = seq + 1
            released: List[Any] = [event]
            buf = self._buffered[channel]
            while self._next_seq[channel] in buf:  # drain contiguous run
                nxt = self._next_seq[channel]
                released.append(buf.pop(nxt))
                self._next_seq[channel] = nxt + 1
            return released

        # seq > next_expected: gap ahead.  Buffer (idempotent on dup).
        buf = self._buffered.setdefault(channel, {})
        buf[seq] = event
        if len(buf) > self._max_buffered:
            raise ResyncRequired(channel)
        return []

    def reset_and_catch_up(self, channel: str, seq: int, event: Any) -> List[Any]:
        """Drop the stale buffer and release *event* as the new base for *channel*.

        This is the resync fast-forward path: we have lost too many events to
        repair the gap, so we accept the current event as the new contiguous
        base and continue from there.
        """
        self._next_seq[channel] = seq
        self._buffered[channel] = {}
        return self.push(channel, seq, event)

    def has_gap(self, channel: str) -> bool:
        return bool(self._buffered.get(channel))

    def next_seq(self, channel: str) -> Optional[int]:
        """Return the next expected sequence for a channel, or None if unbound."""
        return self._next_seq.get(channel)

    def missing_seqs(self, channel: str) -> List[int]:
        """Return the sequence numbers needed to close the gap."""
        nxt = self._next_seq.get(channel)
        buf = self._buffered.get(channel)
        if nxt is None or not buf:
            return []
        return [s for s in range(nxt, min(buf)) if s not in buf]
