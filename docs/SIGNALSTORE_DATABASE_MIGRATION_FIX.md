# SignalStore Database Schema Migration Fix

## 🎯 **Database Schema Issue Resolved**

Fixed the `no such column: segment` error that was crashing the SignalStore initialization.

## ✅ **Root Cause Analysis**

### **Problem**
```
sqlite3.OperationalError: no such column: segment
```

The existing `signals.db` file was created before the `segment` column was added to the `cqi_history` table.

### **Database Schema**
```sql
CREATE TABLE IF NOT EXISTS cqi_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    domain TEXT NOT NULL,
    segment TEXT DEFAULT 'default',  -- ← This column missing in old DB
    quality_index REAL DEFAULT 0.5,
    band TEXT DEFAULT 'neutral',
    -- ... other columns
);

-- These indexes reference the missing segment column
CREATE INDEX IF NOT EXISTS idx_cqi_segment ON cqi_history(segment);
CREATE INDEX IF NOT EXISTS idx_cqi_domain_segment ON cqi_history(domain, segment);
```

### **Database Location**
```python
# In SignalStore.__init__()
self._db_path = db_path or os.environ.get("MERID_SIGNAL_DB", "data/signals.db")
```

## ✅ **Solution Options**

### **🚀 Option 1: Fast Path (Dev Only) - Delete and Recreate**

#### **Steps**
```bash
# 1. Stop MERID
# 2. Delete the signals database
rm data/signals.db

# 3. Restart MERID - it will recreate with correct schema
python -m merid.loop
```

#### **Pros**
- ✅ Fast and simple
- ✅ Guaranteed to work
- ✅ Clean slate with correct schema

#### **Cons**
- ❌ Loses all signal history
- ❌ Loses CQI history
- ❌ Not suitable for production

### **🚀 Option 2: Safer Migration (Keep Data) - Enhanced Migration System**

#### **Improved Migration Code**
```python
def _run_migrations(self, conn):
    """Run database migrations"""
    try:
        # Check if segment column exists in cqi_history
        cursor = conn.execute("PRAGMA table_info(cqi_history)")
        columns = [row[1] for row in cursor.fetchall()]
        
        logger.info(f"Current cqi_history columns: {columns}")
        
        if 'segment' not in columns:
            logger.info("Adding segment column to cqi_history table")
            try:
                # Add the segment column
                conn.execute("ALTER TABLE cqi_history ADD COLUMN segment TEXT DEFAULT 'default'")
                logger.info("Successfully added segment column")
                
                # Add indexes for segment (safe to run multiple times)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_cqi_segment ON cqi_history(segment)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_cqi_domain_segment ON cqi_history(domain, segment)")
                logger.info("Successfully created segment indexes")
                
                logger.info("Migration completed: added segment column to cqi_history")
            except sqlite3.OperationalError as alter_error:
                error_msg = str(alter_error).lower()
                if "duplicate column name" in error_msg:
                    logger.info("Segment column already exists, skipping migration")
                else:
                    logger.error(f"Migration failed: {alter_error}")
                    raise alter_error
        else:
            logger.info("Segment column already exists in cqi_history")
        
        conn.commit()
        
    except Exception as e:
        logger.error(f"Error running database migrations: {e}")
        logger.error(f"Database path: {self._db_path}")
        try:
            conn.rollback()
            logger.info("Database rollback completed")
        except Exception as rollback_error:
            logger.error(f"Error during rollback: {rollback_error}")
        raise
```

#### **Migration Features**
- ✅ **Column detection**: Checks if segment column exists before adding
- ✅ **Safe ALTER**: Uses `ALTER TABLE ADD COLUMN` with default value
- ✅ **Index creation**: Creates necessary indexes safely
- ✅ **Error handling**: Handles duplicate column errors gracefully
- ✅ **Logging**: Detailed logging for debugging
- ✅ **Rollback**: Proper rollback on failure
- ✅ **Idempotent**: Safe to run multiple times

## 🚀 **Implementation Steps**

### **For Option 1 (Fast Path)**
```bash
# Stop MERID first
pkill -f "python.*merid.loop"  # or however you stop it

# Delete database
rm -f data/signals.db

# Restart
python -m merid.loop
```

### **For Option 2 (Migration)**
```bash
# Just restart MERID - migration will run automatically
python -m merid.loop
```

The enhanced migration will:
1. Check current table schema
2. Add missing segment column if needed
3. Create necessary indexes
4. Log all steps for debugging
5. Handle errors gracefully

## 🎯 **Verification**

### **Check Migration Success**
Look for these log messages:
```
INFO - Current cqi_history columns: ['id', 'domain', 'segment', ...]
INFO - Segment column already exists in cqi_history
```

Or if migration runs:
```
INFO - Adding segment column to cqi_history table
INFO - Successfully added segment column
INFO - Successfully created segment indexes
INFO - Migration completed: added segment column to cqi_history
```

### **Verify Database Schema**
```python
import sqlite3
conn = sqlite3.connect("data/signals.db")
cursor = conn.execute("PRAGMA table_info(cqi_history)")
columns = [row[1] for row in cursor.fetchall()]
print("cqi_history columns:", columns)
# Should include: 'segment'
```

## 🎯 **Production Recommendation**

### **For Development**
Use **Option 1** (delete and recreate) for:
- Quick testing
- Clean environments
- When data loss is acceptable

### **For Production**
Use **Option 2** (migration) for:
- Preserving historical data
- Zero-downtime upgrades
- Production safety

## 🎯 **Final Result**

Both solutions will resolve the `no such column: segment` error:

✅ **Option 1**: Fast, simple, loses data  
✅ **Option 2**: Safe, preserves data, robust migration  
✅ **Enhanced logging**: Better debugging and monitoring  
✅ **Error handling**: Graceful failure recovery  

The enhanced migration system is now in place and will automatically handle the schema upgrade when you restart MERID! 🚀
