"""
JarvisMax - Database Migration Runner
Auto-detect and apply pending migrations with transaction safety.

Features:
- Automatic migration discovery from migrations/ directory
- Sequential execution with rollback on error
- Migration history tracking
- Execution time monitoring
- Dry-run mode for testing
"""
from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Optional

import structlog
_silent_log = __import__("structlog").get_logger(__name__)

log = structlog.get_logger(__name__)

# Migration configuration
MIGRATIONS_DIR = Path(__file__).parent.parent.parent / "migrations"
MIGRATION_PATTERN = re.compile(r"^(\d{3})_(.+)\.sql$")


def _get_db_connection():
    """Get PostgreSQL connection."""
    try:
        import psycopg2
        
        conn = psycopg2.connect(
            host=os.getenv("POSTGRES_HOST", "postgres"),
            database=os.getenv("POSTGRES_DB", "jarvis"),
            user=os.getenv("POSTGRES_USER", "jarvis"),
            password=os.getenv("POSTGRES_PASSWORD", "")
        )
        return conn
    except Exception as e:
        log.error("db_connection_failed", error=str(e))
        raise


def _ensure_migration_table(conn) -> None:
    """Ensure migration_history table exists."""
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS migration_history (
                id SERIAL PRIMARY KEY,
                migration_name VARCHAR(255) NOT NULL UNIQUE,
                applied_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                success BOOLEAN DEFAULT true,
                error_message TEXT,
                execution_time_ms INTEGER
            )
        """)
        conn.commit()
        log.debug("migration_table_ensured")
    except Exception as e:
        conn.rollback()
        log.error("migration_table_creation_failed", error=str(e))
        raise


def get_applied_migrations(conn) -> set[str]:
    """Get list of already-applied migrations."""
    try:
        cur = conn.cursor()
        cur.execute("SELECT migration_name FROM migration_history WHERE success = true")
        results = cur.fetchall()
        return {row[0] for row in results}
    except Exception as e:
        log.error("get_applied_migrations_failed", error=str(e))
        return set()


def discover_migrations() -> list[tuple[str, Path]]:
    """
    Discover migration files in migrations/ directory.
    
    Returns:
        List of (migration_name, file_path) tuples, sorted by number
    """
    if not MIGRATIONS_DIR.exists():
        log.warning("migrations_directory_not_found", path=str(MIGRATIONS_DIR))
        return []
    
    migrations = []
    for file in MIGRATIONS_DIR.glob("*.sql"):
        match = MIGRATION_PATTERN.match(file.name)
        if match:
            number, name = match.groups()
            migration_name = f"{number}_{name}"
            migrations.append((migration_name, file))
        else:
            log.warning("invalid_migration_filename", filename=file.name)
    
    # Sort by migration number
    migrations.sort(key=lambda x: x[0])
    return migrations


def get_pending_migrations(conn) -> list[tuple[str, Path]]:
    """Get migrations that haven't been applied yet."""
    applied = get_applied_migrations(conn)
    all_migrations = discover_migrations()
    
    pending = [(name, path) for name, path in all_migrations if name not in applied]
    
    log.info("migrations_discovered", 
             total=len(all_migrations), 
             applied=len(applied), 
             pending=len(pending))
    
    return pending


def apply_migration(conn, migration_name: str, migration_path: Path, dry_run: bool = False) -> tuple[bool, Optional[str]]:
    """
    Apply a single migration.
    
    Args:
        conn: Database connection
        migration_name: Name of the migration
        migration_path: Path to SQL file
        dry_run: If True, don't commit changes
    
    Returns:
        (success: bool, error_message: Optional[str])
    """
    start_time = time.time()
    
    try:
        # Read migration SQL
        with open(migration_path, "r") as f:
            sql = f.read()
        
        log.info("applying_migration", name=migration_name, dry_run=dry_run)
        
        cur = conn.cursor()
        
        # Execute migration SQL
        cur.execute(sql)
        
        # Record in migration history (unless it's already there from the migration itself)
        execution_time_ms = int((time.time() - start_time) * 1000)
        
        if dry_run:
            conn.rollback()
            log.info("migration_dry_run_success", name=migration_name, time_ms=execution_time_ms)
            return True, None
        else:
            # Update execution time if migration created its own history record
            cur.execute("""
                UPDATE migration_history 
                SET execution_time_ms = %s 
                WHERE migration_name = %s
            """, (execution_time_ms, migration_name))
            
            conn.commit()
            log.info("migration_applied", name=migration_name, time_ms=execution_time_ms)
            return True, None
        
    except Exception as e:
        conn.rollback()
        error_msg = str(e)
        log.error("migration_failed", name=migration_name, error=error_msg)
        
        # Record failure in history
        try:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO migration_history (migration_name, success, error_message)
                VALUES (%s, false, %s)
                ON CONFLICT (migration_name) DO UPDATE
                SET success = false, error_message = EXCLUDED.error_message
            """, (migration_name, error_msg))
            conn.commit()
        except:
            _silent_log.debug("suppressed_exception", src='migrate.py')
        
        return False, error_msg


def run_migrations(dry_run: bool = False, target_migration: Optional[str] = None) -> dict:
    """
    Run all pending migrations.
    
    Args:
        dry_run: If True, don't commit changes
        target_migration: If specified, only run up to this migration
    
    Returns:
        Dict with migration results
    """
    conn = None
    results = {
        "total": 0,
        "applied": 0,
        "failed": 0,
        "skipped": 0,
        "errors": []
    }
    
    try:
        conn = _get_db_connection()
        _ensure_migration_table(conn)
        
        pending = get_pending_migrations(conn)
        results["total"] = len(pending)
        
        if not pending:
            log.info("no_pending_migrations")
            return results
        
        for migration_name, migration_path in pending:
            # Stop if we've reached the target migration
            if target_migration and migration_name > target_migration:
                results["skipped"] += 1
                log.info("migration_skipped", name=migration_name, reason="after_target")
                continue
            
            success, error = apply_migration(conn, migration_name, migration_path, dry_run)
            
            if success:
                results["applied"] += 1
            else:
                results["failed"] += 1
                results["errors"].append({
                    "migration": migration_name,
                    "error": error
                })
                
                # Stop on first failure
                log.error("migration_sequence_halted", failed_migration=migration_name)
                break
            
            # If we just applied the target migration, stop
            if target_migration and migration_name == target_migration:
                break
        
        log.info("migrations_completed", **results)
        return results
        
    except Exception as e:
        log.error("migration_run_failed", error=str(e))
        results["errors"].append({"migration": "system", "error": str(e)})
        return results
    finally:
        if conn:
            conn.close()


def rollback_migration(migration_name: str) -> bool:
    """
    Rollback a migration (if rollback script exists).
    
    Note: This is a placeholder. Rollback scripts would need to be
    implemented as separate .rollback.sql files.
    
    Args:
        migration_name: Name of migration to rollback
    
    Returns:
        True if successful
    """
    log.warning("rollback_not_implemented", migration=migration_name)
    return False


def get_migration_status() -> dict:
    """
    Get current migration status.
    
    Returns:
        Dict with applied/pending counts and details
    """
    conn = None
    try:
        conn = _get_db_connection()
        _ensure_migration_table(conn)
        
        all_migrations = discover_migrations()
        applied = get_applied_migrations(conn)
        pending = [name for name, _ in all_migrations if name not in applied]
        
        return {
            "total_migrations": len(all_migrations),
            "applied": len(applied),
            "pending": len(pending),
            "applied_migrations": sorted(list(applied)),
            "pending_migrations": pending
        }
        
    except Exception as e:
        log.error("get_migration_status_failed", error=str(e))
        return {
            "error": str(e),
            "total_migrations": 0,
            "applied": 0,
            "pending": 0
        }
    finally:
        if conn:
            conn.close()


if __name__ == "__main__":
    import sys
    
    # CLI interface for testing
    if len(sys.argv) > 1 and sys.argv[1] == "status":
        status = get_migration_status()
        print(f"Migrations: {status['applied']}/{status['total_migrations']} applied")
        if status.get("pending_migrations"):
            print(f"Pending: {', '.join(status['pending_migrations'])}")
    elif len(sys.argv) > 1 and sys.argv[1] == "run":
        dry_run = "--dry-run" in sys.argv
        results = run_migrations(dry_run=dry_run)
        print(f"Applied: {results['applied']}, Failed: {results['failed']}")
        if results["errors"]:
            for error in results["errors"]:
                print(f"  ERROR {error['migration']}: {error['error']}")
    else:
        print("Usage: python -m core.db.migrate [status|run] [--dry-run]")
