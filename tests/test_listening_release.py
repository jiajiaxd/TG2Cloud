"""Release audit regressions: no real Telegram, Session or server access."""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

from tg2cloud.listening import account
from tg2cloud.persistence.migrations import SCHEMA_VERSION, migrate
from tg2cloud.persistence.plans import create_schema
from tg2cloud.persistence.sqlite import TaskDB
from tg2cloud.telegram.planning import output


class ReleaseAuditTests(unittest.IsolatedAsyncioTestCase):
    async def test_long_unicode_pages_keep_all_text_and_last_keyboard(self):
        for callback in (False, True):
            e = NS(reply=AsyncMock(), edit=AsyncMock(), respond=AsyncMock())
            if callback:
                e.data = b"planui:test"
            text = ("示例电影😀.mp4 → 新名称\n" * 500)
            keyboard = [["synthetic-button"]]
            await output(e, text, keyboard)
            first = e.edit if callback else e.reply
            calls = [*first.await_args_list, *e.respond.await_args_list]
            self.assertEqual("".join(c.args[0] for c in calls), text)
            self.assertGreater(len(calls), 1)
            for c in calls:
                self.assertLessEqual(len(c.args[0].encode("utf-16-le")) // 2, 3500)
                self.assertIsNone(c.kwargs["parse_mode"])
            self.assertTrue(all(c.kwargs["buttons"] is None for c in calls[:-1]))
            self.assertEqual(calls[-1].kwargs["buttons"], keyboard)

    async def test_login_disconnect_failure_restores_umask_and_releases_lock(self):
        released = []
        @contextmanager
        def lock(_settings):
            try:
                yield Path("synthetic-personal")
            finally:
                released.append(True)
        personal = NS(start=AsyncMock(), get_me=AsyncMock(return_value=NS(id=42, bot=False)),
                      disconnect=AsyncMock(side_effect=OSError("synthetic")))
        with patch.object(account.os, "isatty", return_value=True), \
                patch.object(account.os, "umask", return_value=0o022) as umask, \
                patch.object(account, "session_lock", lock), \
                patch.object(account, "client", return_value=personal), \
                patch.object(account, "state", return_value={"account": 42}), \
                patch.object(account, "write_state"), patch("builtins.print"):
            with self.assertRaises(OSError):
                await account.login(NS(), NS())
            self.assertEqual([c.args for c in umask.call_args_list], [(0o077,), (0o022,)])
        self.assertEqual(released, [True])

    def test_interrupted_schema_two_upgrade_rolls_back_new_columns_and_tables(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "tasks.db"
            db = TaskDB(path)
            db.close()
            c = sqlite3.connect(path, isolation_level=None)
            try:
                c.execute("ALTER TABLE tasks DROP COLUMN source_id")
                c.execute("ALTER TABLE tasks DROP COLUMN read_identity")
                c.execute("ALTER TABLE tasks DROP COLUMN classification_parent")
                for table in ("transfer_preferences", "transfer_directories", "listener_events",
                              "transfer_plans", "listener_revisions", "naming_feedback", "listener_sources"):
                    c.execute('DROP TABLE "' + table + '"')
                old_schema = c.execute("SELECT type,name,sql FROM sqlite_master ORDER BY type,name").fetchall()
                c.execute("PRAGMA user_version=2")
                columns = {r[1] for r in c.execute("PRAGMA table_info(tasks)")}
                def interrupt_after_schema(connection):
                    create_schema(connection)
                    raise KeyboardInterrupt
                with patch("tg2cloud.persistence.plans.create_schema", side_effect=interrupt_after_schema), self.assertRaises(KeyboardInterrupt):
                    migrate(c, columns)
                self.assertFalse(c.in_transaction)
                self.assertEqual(c.execute("PRAGMA user_version").fetchone()[0], 2)
                self.assertEqual({r[1] for r in c.execute("PRAGMA table_info(tasks)")}, columns)
                self.assertEqual(c.execute("SELECT type,name,sql FROM sqlite_master ORDER BY type,name").fetchall(), old_schema)
                self.assertEqual(c.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                migrate(c, columns)
                self.assertEqual(c.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)
            finally:
                c.close()
