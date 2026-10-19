# FillsLedger Concurrency Audit

## Overview
Audit of `KalshiFillsLedger` for race conditions between WebSocket fill callbacks and REST poller ingestion.

---

## Components Audited

### 1. Lock Protection

#### Singleton Initialization Lock
```python
_instance: Optional[KalshiFillsLedger] = None
_lock = threading.Lock()

def __new__(cls):
    if cls._instance is None:
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
    return cls._instance
```

**Strengths:**
- ✅ Double-checked locking pattern for thread-safe singleton
- ✅ Uses `threading.Lock()` for cross-thread safety

**Weaknesses:**
- ⚠️ None - correctly implemented

---

#### Mutex for Dict Mutations
```python
# Lock for thread safety (protects all dict mutations)
self._mutex = asyncio.Lock()
```

**Strengths:**
- ✅ Async lock for async context
- ✅ Protects all dict mutations

**Weaknesses:**
- ⚠️ None - correctly implemented

---

### 2. Ingestion Paths

#### ingest_http_fills() (Lines 844-1008)
**Purpose:** Ingest fills from HTTP /portfolio/fills endpoint

**Lock Usage:**
```python
async def ingest_http_fills(self, fills: List[Dict[str, Any]], 
                            agent_map: Optional[Dict[str, str]] = None) -> Tuple[int, List[str]]:
    new_count = 0
    new_fill_ids: List[str] = []
    merged_duplicate = False
    
    async with self._mutex:  # ✅ Protected by mutex
        for raw in fills:
            fill = self._parse_fill(raw, "http_poller")
            if _is_test_fixture_fill(fill.fill_id):
                continue
            if fill.fill_id in self._fills:
                # HTTP upsert over prior WS row: enrich without zeroing good data.
                existing = self._fills[fill.fill_id]
                # ... upsert logic ...
            else:
                # ... new fill logic ...
                self._fills[fill.fill_id] = fill
                self._index_fill(fill)
```

**Strengths:**
- ✅ Protected by `async with self._mutex`
- ✅ Entire batch processed under single lock acquisition
- ✅ Upsert logic preserves existing data from WS
- ✅ Idempotent - duplicate fills are merged, not rejected

**Weaknesses:**
- ⚠️ **Long-held lock** - entire batch processed under lock (could block WS callbacks)
- ⚠️ No lock timeout - could deadlock if exception occurs

**Recommendations:**
1. Consider processing fills in smaller batches to reduce lock hold time
2. Add lock timeout with `asyncio.wait_for(self._mutex.acquire(), timeout=5.0)`

---

#### ingest_ws_fill() (Lines 1010-1109)
**Purpose:** Ingest a single fill from WebSocket

**Lock Usage:**
```python
async def ingest_ws_fill(self, raw: Dict[str, Any], agent_id: Optional[str] = None) -> bool:
    async with self._mutex:  # ✅ Protected by mutex
        fill = self._parse_fill(raw, "websocket")
        
        if fill.fill_id in self._fills:
            self._duplicates_dropped += 1
            return False
        
        # ... fill enrichment logic ...
        
        if fill.is_incomplete():
            # Incomplete WebSocket fills are expected - HTTP will complete later
            return False
        
        self._fills[fill.fill_id] = fill
        self._index_fill(fill)
        self._ws_ingested += 1
```

**Strengths:**
- ✅ Protected by `async with self._mutex`
- ✅ Single fill processed quickly (minimal lock hold time)
- ✅ Rejects incomplete fills (HTTP will complete later)
- ✅ Duplicate detection

**Weaknesses:**
- ⚠️ None - correctly implemented

**Recommendations:**
1. None - implementation is correct

---

### 3. Persistence Layer

#### Single-Writer Pattern (Lines 3402-3491)
**Purpose:** Queue fills for persistence to avoid DB lock contention

**Implementation:**
```python
# Async queue for single-writer pattern (prevents DB lock contention)
self._persist_queue: asyncio.Queue[Optional[KalshiFill]] = asyncio.Queue(maxsize=10000)
self._writer_task: Optional[asyncio.Task] = None
self._shutdown_event = asyncio.Event()

async def _persist(self) -> None:
    """Queue a fill for persistence (single-writer pattern)."""
    # Start writer task if not running
    if self._writer_task is None or self._writer_task.done():
        self._writer_task = asyncio.create_task(self._writer_loop(), name="fills_writer")
    
    await self._persist_queue.put(fill)

async def _writer_loop(self) -> None:
    """Dedicated writer task that batches and writes to SQLite."""
    logger.info("Fills writer loop started")
    
    import aiosqlite
    
    # Single persistent connection for lifetime of loop
    _writer_db = await aiosqlite.connect(self._db_path)
    await _writer_db.execute("PRAGMA journal_mode=WAL")
    await _writer_db.execute("PRAGMA busy_timeout=5000")
    
    while not self._shutdown_event.is_set():
        try:
            # Wait for signal or timeout
            try:
                await asyncio.wait_for(
                    self._persist_queue.get(),
                    timeout=_FILLS_WRITER_QUEUE_TIMEOUT
                )
            except asyncio.TimeoutError:
                # Periodic flush even if no signals
                pass
            
            # Batch collect additional signals
            batch_signals = 1
            max_batch_collect = 50  # Limit to prevent event loop blocking
            while batch_signals < max_batch_collect and not self._persist_queue.empty():
                try:
                    self._persist_queue.get_nowait()
                    batch_signals += 1
                except asyncio.QueueEmpty:
                    break
            
            # Perform the actual persistence
            await self._flush_to_db(_writer_db)
```

**Strengths:**
- ✅ Single-writer pattern prevents DB lock contention
- ✅ Dedicated writer task with persistent connection
- ✅ Batching reduces DB write overhead
- ✅ WAL mode for better concurrency
- ✅ Busy timeout (5s) for DB locks
- ✅ Max batch size (50) prevents event loop blocking

**Weaknesses:**
- ⚠️ Queue maxsize 10000 - could fill under high load
- ⚠️ No backpressure mechanism when queue is full
- ⚠️ No alerting on queue depth

**Recommendations:**
1. Add queue depth monitoring and alerting
2. Add backpressure mechanism (drop oldest when queue > 90% full)
3. Log queue depth periodically

---

#### DB Retry Logic (Lines 3361-3400)
**Purpose:** Execute SQL with retry on database locked errors

**Implementation:**
```python
async def _execute_with_retry(self, db, sql: str, params: tuple = (), retries: int = None) -> None:
    """Execute SQL with retry on database locked errors."""
    if retries is None:
        retries = _FILLS_DB_RETRY_ATTEMPTS  # 3 retries
    
    last_error = None
    delay = _FILLS_DB_RETRY_DELAY_INITIAL  # 0.05s
    
    for i in range(retries):
        try:
            await db.execute(sql, params)
            return
        except sqlite3.Error as e:
            last_error = e
            error_str = str(e).lower()
            
            # Permanent errors: don't retry
            if is_permanent:
                raise
            
            # Only retry on database locked errors
            if "database is locked" not in error_str and "busy" not in error_str:
                raise
            
            if i < retries - 1:
                logger.debug(f"DB locked, retrying in {delay}s (attempt {i+1}/{retries})")
                await asyncio.sleep(delay)
                delay = min(delay * 2, _FILLS_DB_RETRY_DELAY_MAX)  # Exponential backoff
    
    raise last_error if last_error else sqlite3.OperationalError("database is locked after retries")
```

**Strengths:**
- ✅ Retry on DB locked errors
- ✅ Permanent errors not retried (schema mismatch)
- ✅ Exponential backoff (0.05s → 0.5s max)
- ✅ Limited retries (3) to prevent infinite loops

**Weaknesses:**
- ⚠️ None - correctly implemented

**Recommendations:**
1. None - implementation is correct

---

### 4. Read Operations

#### get_fills() (Lines 1400-1500)
**Purpose:** Query fills from in-memory cache

**Lock Usage:**
```python
def get_fills(self, since: Optional[datetime] = None, 
             market_ticker: Optional[str] = None,
             fill_source: Optional[str] = None) -> List[KalshiFill]:
    """Query fills from in-memory cache (no DB access)."""
    # ⚠️ NOT protected by mutex - reads from dict directly
    results = []
    for fill in self._fills.values():
        if since and fill.created_at < since:
            continue
        if market_ticker and fill.market_ticker != market_ticker:
            continue
        if fill_source and fill.fill_source != fill_source:
            continue
        results.append(fill)
    return results
```

**Strengths:**
- ✅ Fast read from in-memory cache
- ✅ No DB access

**Weaknesses:**
- ⚠️ **NOT protected by mutex** - could read inconsistent state during write
- ⚠️ Could see partially updated fill during HTTP upsert

**Recommendations:**
1. Add `async with self._mutex` for consistency (or document as "eventually consistent")
2. Or create a snapshot copy under lock and return that

---

#### compute_position_from_fills() (Lines 1517-1600)
**Purpose:** Recompute position for a market purely from fills ledger

**Lock Usage:**
```python
def compute_position_from_fills(self, market_ticker: str) -> Optional[Dict[str, Any]]:
    """Recompute position purely from fills ledger."""
    # ⚠️ NOT protected by mutex - reads from dict directly
    market_fills = self._fills_by_market.get(market_ticker, [])
    if not market_fills:
        return None
    
    # ... position computation logic ...
```

**Strengths:**
- ✅ Fast read from in-memory cache
- ✅ Uses indexed `_fills_by_market` for efficiency

**Weaknesses:**
- ⚠️ **NOT protected by mutex** - could read inconsistent state during write
- ⚠️ Could see partially updated fills during HTTP upsert

**Recommendations:**
1. Add `async with self._mutex` for consistency (or document as "eventually consistent")
2. Or use `asyncio.to_thread()` with lock for async wrapper

---

#### compute_net_positions() (Lines 1602-1630)
**Purpose:** Compute net positions across all markets

**Lock Usage:**
```python
def compute_net_positions(self) -> Dict[str, Dict[str, Any]]:
    """Compute net positions across all markets."""
    # ⚠️ NOT protected by mutex - reads from dict directly
    positions = {}
    for ticker, fill_ids in self._fills_by_market.items():
        # ... position computation logic ...
```

**Strengths:**
- ✅ Fast read from in-memory cache
- ✅ Uses indexed `_fills_by_market` for efficiency

**Weaknesses:**
- ⚠️ **NOT protected by mutex** - could read inconsistent state during write
- ⚠️ Could see partially updated fills during HTTP upsert

**Recommendations:**
1. Add `async with self._mutex` for consistency (or document as "eventually consistent")
2. Or use `asyncio.to_thread()` with lock for async wrapper

---

### 5. Async Wrappers

#### compute_position_from_fills_async() (Lines 1507-1510)
**Purpose:** Async wrapper for compute_position_from_fills

**Implementation:**
```python
async def compute_position_from_fills_async(self, market_ticker: str) -> Optional[Dict[str, Any]]:
    """Async wrapper for compute_position_from_fills - runs in thread pool to avoid blocking."""
    import asyncio
    return await asyncio.to_thread(self.compute_position_from_fills, market_ticker)
```

**Strengths:**
- ✅ Runs in thread pool to avoid blocking event loop
- ✅ Allows async callers to use sync computation

**Weaknesses:**
- ⚠️ Still not protected by mutex (delegates to sync method)

**Recommendations:**
1. Add mutex protection in sync method or wrapper

---

#### compute_net_positions_async() (Lines 1512-1515)
**Purpose:** Async wrapper for compute_net_positions

**Implementation:**
```python
async def compute_net_positions_async(self) -> Dict[str, Dict[str, Any]]:
    """Async wrapper for compute_net_positions - runs in thread pool to avoid blocking."""
    import asyncio
    return await asyncio.to_thread(self.compute_net_positions)
```

**Strengths:**
- ✅ Runs in thread pool to avoid blocking event loop
- ✅ Allows async callers to use sync computation

**Weaknesses:**
- ⚠️ Still not protected by mutex (delegates to sync method)

**Recommendations:**
1. Add mutex protection in sync method or wrapper

---

### 6. Snapshot Operations

#### _flush_to_db() (Lines 3520-3550)
**Purpose:** Flush fills snapshot to SQLite database

**Lock Usage:**
```python
async def _flush_to_db(self, db) -> None:
    """Flush fills snapshot to SQLite database."""
    # Ensure DB is initialized
    if not self._db_initialized:
        await self._init_db()
    
    # Take a SNAPSHOT of fills under lock to avoid "dict changed size during iteration"
    fills_snapshot: List[KalshiFill] = []
    async with self._mutex:  # ✅ Protected by mutex
        fills_snapshot = list(self._fills.values())
    
    if not fills_snapshot:
        return
    
    # ... DB write logic ...
```

**Strengths:**
- ✅ Takes snapshot under mutex to avoid iteration errors
- ✅ Fast snapshot (list copy)
- ✅ DB writes happen outside lock (non-blocking)

**Weaknesses:**
- ⚠️ None - correctly implemented

**Recommendations:**
1. None - implementation is correct

---

#### get_summary() (Lines 1890-1920)
**Purpose:** Get summary statistics from fills ledger

**Lock Usage:**
```python
def get_summary(self) -> Dict[str, Any]:
    """Get summary statistics from fills ledger."""
    # ... position cache lookup ...
    
    # Take snapshot under lock to avoid dict mutation during iteration
    fills_snapshot = list(self._fills.values())  # ⚠️ NOT protected by mutex
    
    for fill in fills_snapshot:
        total_fees += fill.fee_cost
        # ... summary computation ...
```

**Strengths:**
- ✅ Takes snapshot to avoid iteration errors

**Weaknesses:**
- ⚠️ **NOT protected by mutex** - could read inconsistent state
- ⚠️ Could see partially updated fills during HTTP upsert

**Recommendations:**
1. Add `async with self._mutex` for consistency

---

## Race Condition Analysis

### Potential Race Conditions

#### 1. WS Callback During HTTP Batch Upsert
**Scenario:** WS callback arrives while HTTP batch is upserting fills

**Current Protection:**
- Both paths use `async with self._mutex`
- Mutex ensures mutual exclusion

**Risk:** LOW - mutex protection is correct

**Recommendation:** None - correctly protected

---

#### 2. Read During Write
**Scenario:** `get_fills()` called while `ingest_http_fills()` is upserting

**Current Protection:**
- Write is protected by mutex
- Read is NOT protected by mutex

**Risk:** MEDIUM - could read inconsistent state (partially upserted fill)

**Impact:**
- Could see fill with old price but new count
- Could see fill before HTTP confirmation flag is set
- Could see fill before hedge reason is set

**Recommendation:** Add mutex protection to read operations or document as "eventually consistent"

---

#### 3. Concurrent HTTP Batches
**Scenario:** Two HTTP batches ingested concurrently

**Current Protection:**
- Both use `async with self._mutex`
- Mutex ensures mutual exclusion

**Risk:** LOW - mutex protection is correct

**Recommendation:** None - correctly protected

---

#### 4. Concurrent WS Callbacks
**Scenario:** Two WS callbacks arrive concurrently

**Current Protection:**
- Both use `async with self._mutex`
- Mutex ensures mutual exclusion

**Risk:** LOW - mutex protection is correct

**Recommendation:** None - correctly protected

---

#### 5. DB Write During Ingestion
**Scenario:** `_writer_loop()` flushes to DB while new fills arrive

**Current Protection:**
- Ingestion uses `_persist_queue` (single-writer pattern)
- DB writes happen in dedicated writer task
- No direct DB access from ingestion paths

**Risk:** LOW - single-writer pattern is correct

**Recommendation:** None - correctly protected

---

## Recommendations

### High Priority
1. **Add mutex protection to read operations**
   - `get_fills()`, `compute_position_from_fills()`, `compute_net_positions()`, `get_summary()`
   - Or document as "eventually consistent" and accept race condition risk

2. **Add lock timeout to mutex acquisitions**
   - Use `asyncio.wait_for(self._mutex.acquire(), timeout=5.0)`
   - Prevents deadlocks if exception occurs

3. **Add queue depth monitoring and alerting**
   - Log queue depth periodically
   - Alert if queue > 90% full
   - Add backpressure mechanism (drop oldest when queue full)

### Medium Priority
4. **Reduce HTTP batch lock hold time**
   - Process fills in smaller batches (e.g., 50 at a time)
   - Release lock between batches
   - Reduces blocking time for WS callbacks

5. **Add metrics for lock contention**
   - Track mutex wait time
   - Track mutex acquisition failures
   - Alert on high contention

### Low Priority
6. **Consider read-write lock pattern**
   - Use `asyncio.Lock` for writes
   - Use `asyncio.Semaphore` for reads (allow concurrent reads)
   - Improves read performance under high load

---

## Conclusion

**Overall Assessment:** The concurrency protection is **partially implemented** with good write protection but **missing read protection**.

**Strengths:**
- All write operations protected by `asyncio.Lock`
- Single-writer pattern for DB persistence
- Proper retry logic for DB locks
- Snapshot pattern for DB writes

**Weaknesses:**
- Read operations NOT protected by mutex
- No lock timeout (potential deadlock risk)
- No queue depth monitoring
- Long-held lock for HTTP batches

**Critical Fixes Needed:**
1. Add mutex protection to read operations (or document as eventually consistent)
2. Add lock timeout to mutex acquisitions
3. Add queue depth monitoring and alerting
