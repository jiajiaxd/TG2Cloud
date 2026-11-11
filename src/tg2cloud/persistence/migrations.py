"""Transactional business database migrations under the caller's lock."""
import sqlite3

from tg2cloud.domain.states import FAILED_STATES

SCHEMA_VERSION = 4

def migrate(connection: sqlite3.Connection, columns: set[str]) -> None:
    connection.execute("BEGIN IMMEDIATE")
    try:
        for name, declaration in (
            ("remote_temp_path", "TEXT"),
            ("remote_final_path", "TEXT"),
            ("cancel_requested", "INTEGER NOT NULL DEFAULT 0"),
            ("failure_kind", "TEXT"),
            ("verification_method", "TEXT"),
            ("verified_at", "REAL"),
            ("original_file_name", "TEXT"),
            ("target_directory", "TEXT NOT NULL DEFAULT ''"),
            ("target_base", "TEXT"),
            ("read_identity", "TEXT NOT NULL DEFAULT 'bot'"),
            ("source_id", "INTEGER"),
            ("classification_parent", "TEXT"),
        ):
            if name not in columns:
                connection.execute(f"ALTER TABLE tasks ADD COLUMN {name} {declaration}")
        connection.execute(
            """UPDATE tasks SET remote_temp_path=remote_path
                WHERE remote_temp_path IS NULL AND remote_path LIKE '.uploading-%'"""
        )
        connection.execute(
            """UPDATE tasks SET remote_final_path=remote_path
                WHERE remote_final_path IS NULL AND remote_path IS NOT NULL
                AND remote_path NOT LIKE '.uploading-%'"""
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS service_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS task_events (
                id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL REFERENCES tasks(id),
                old_state TEXT, new_state TEXT NOT NULL, happened_at REAL NOT NULL)"""
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_task ON task_events(task_id, id)"
        )
        connection.execute("CREATE INDEX IF NOT EXISTS idx_tasks_owner_id ON tasks(sender_id, id)")
        connection.execute("CREATE TABLE IF NOT EXISTS member_quotas (user_id INTEGER PRIMARY KEY, "
                           "daily_bytes INTEGER NOT NULL DEFAULT 0, max_queued INTEGER NOT NULL DEFAULT 0, "
                           "max_active INTEGER NOT NULL DEFAULT 0)")
        connection.execute("CREATE TABLE IF NOT EXISTS quota_ledger (task_id INTEGER PRIMARY KEY REFERENCES tasks(id), "
                           "user_id INTEGER NOT NULL, bytes INTEGER NOT NULL, charged_at REAL, released INTEGER NOT NULL DEFAULT 0)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_quota_owner_time ON quota_ledger(user_id,charged_at)")
        # Do not retroactively bill historical completions. Existing unfinished
        # tasks do reserve their known size before a member can receive a limit.
        connection.execute("INSERT OR IGNORE INTO quota_ledger(task_id,user_id,bytes) "
                           "SELECT id,sender_id,file_size FROM tasks WHERE state NOT IN ('completed','confirmed','cancelled')")
        connection.execute("CREATE TABLE IF NOT EXISTS quota_slots (task_id INTEGER PRIMARY KEY REFERENCES tasks(id))")
        connection.execute("""CREATE TRIGGER IF NOT EXISTS quota_state AFTER UPDATE OF state ON tasks BEGIN
            UPDATE quota_ledger SET charged_at=COALESCE(charged_at,NEW.updated_at)
                WHERE task_id=NEW.id AND NEW.state IN ('cleanup_pending','completed','confirmed')
                AND NEW.verification_method IN ('size','hash') AND NEW.verified_at IS NOT NULL;
            UPDATE quota_ledger SET released=CASE WHEN NEW.state='cancelled' THEN 1 ELSE 0 END
                WHERE task_id=NEW.id AND charged_at IS NULL;
            DELETE FROM quota_slots WHERE task_id=NEW.id AND NEW.state NOT IN
                ('reserved','downloading','streaming','uploading','verifying','finalizing');
            END""")
        connection.execute(
            """CREATE TABLE IF NOT EXISTS task_recoveries (
                id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL REFERENCES tasks(id),
                happened_at REAL NOT NULL, operation TEXT NOT NULL, previous TEXT NOT NULL)"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS retained_objects (
                path TEXT PRIMARY KEY, task_id INTEGER NOT NULL REFERENCES tasks(id))"""
        )
        connection.execute("CREATE INDEX IF NOT EXISTS idx_recoveries_task ON task_recoveries(task_id, id)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_events_state_time ON task_events(new_state, happened_at, task_id)")
        # Preserve the timestamp of pre-event-schema failures before recovery
        # or progress updates can change updated_at. Never delete old tasks.
        for state in FAILED_STATES:
            connection.execute(
                """INSERT INTO task_events(task_id,old_state,new_state,happened_at)
                    SELECT t.id,NULL,t.state,t.updated_at FROM tasks t WHERE t.state=?
                    AND NOT EXISTS (SELECT 1 FROM task_events e WHERE e.task_id=t.id)""", (state,),
            )
        connection.execute(
            """CREATE TRIGGER IF NOT EXISTS task_state_event AFTER UPDATE OF state ON tasks
                WHEN OLD.state != NEW.state BEGIN
                    INSERT INTO task_events(task_id,old_state,new_state,happened_at)
                    VALUES(NEW.id,OLD.state,NEW.state,NEW.updated_at);
                END"""
        )
        from tg2cloud.persistence.plans import create_schema
        create_schema(connection)
        connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        connection.execute("COMMIT")
    except BaseException:
        connection.execute("ROLLBACK")
        raise
