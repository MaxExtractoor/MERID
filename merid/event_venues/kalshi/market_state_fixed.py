# DEADLOCK-FIX: Log lock hold time
        lock_elapsed = time.monotonic() - lock_start
        if lock_elapsed > 1.0:
            logger.warning(
                "[market-state] LOCK CONTENTION: held for %.3fs (ticker=%s) - possible deadlock",
                lock_elapsed, ticker
            )
        finally:
            # CRITICAL FIX: Always release lock
            self._lock.release()
