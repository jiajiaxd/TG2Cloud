"""Optional paths are frozen per task and share existing commit policies."""
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from tg2cloud.domain import classification
from tg2cloud.persistence import features
from tg2cloud.persistence.migrations import SCHEMA_VERSION
from tg2cloud.persistence.sqlite import TaskDB
from tg2cloud.transfer.upload import _choose_remote_final


class ClassificationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "tasks.db"
        self.db = TaskDB(self.path)
        self.addCleanup(self.db.close)
        self.zone = patch.dict(os.environ, {"TZ": "UTC"})
        self.zone.start()
        self.addCleanup(self.zone.stop)

    def task(self, message=1, **values):
        return self.db.create_task(chat_id=1, sender_id=1, message_id=message,
            file_name="旅行.mp4", file_size=100, **values)[0]

    def mode(self, mode):
        features.change(self.db._conn, self.db.feature_settings()["revision"], {"classification": mode})

    def test_default_off_and_modes_types(self):
        self.assertEqual(self.task()["target_directory"], "")
        cases = [("video/mp4", ".bin", "视频"), ("image/jpeg", ".bin", "图片"),
                 ("audio/mpeg", ".bin", "音频"), ("application/pdf", ".bin", "文档"),
                 ("application/zip", ".bin", "压缩包"), ("", ".weird", "其他文件")]
        prefs = {**features.defaults(), "classification": "type_month"}
        for mime, ext, expected in cases:
            with self.subTest(mime=mime):
                self.assertEqual(classification.directory(prefs, 1791028800, mime=mime, extension=ext), expected + "/2026/10")
        for mode, expected in (("year", "2026"), ("month", "2026/10"), ("type", "视频")):
            self.assertEqual(classification.directory({**prefs, "classification": mode}, 1791028800, kind="视频"), expected)

    async def test_directory_frozen_after_rule_change_restart_and_conflict(self):
        self.mode("type_month")
        task = self.task(media_kind="视频", created_at=1791028800)
        self.mode("off")
        service = SimpleNamespace(db=self.db, settings=SimpleNamespace(cd2_target="root"),
            rclone=SimpleNamespace(ensure_directory=AsyncMock(), exists=AsyncMock(side_effect=[True, False])))
        result = await _choose_remote_final(service, task["file_name"], task["id"])
        self.assertEqual(result, "视频/2026/10/旅行 (task-1).mp4")
        self.assertEqual(self.db.get(task["id"])["target_directory"], "视频/2026/10")
        reopened = TaskDB(self.path)
        try:
            self.assertEqual(reopened.get(task["id"])["target_directory"], "视频/2026/10")
        finally:
            reopened.close()

    async def test_mkdir_failure_is_not_silent_fallback(self):
        self.mode("type")
        task = self.task(media_kind="视频")
        service = SimpleNamespace(db=self.db, settings=SimpleNamespace(),
            rclone=SimpleNamespace(ensure_directory=AsyncMock(side_effect=RuntimeError("mkdir failed")), exists=AsyncMock()))
        with self.assertRaises(RuntimeError):
            await _choose_remote_final(service, task["file_name"], task["id"])
        service.rclone.exists.assert_not_awaited()

    def test_malicious_subdirectories_rejected_and_base_change_stops(self):
        for value in ("../escape", "/root", "a\\b", "a//b", "a/%2e%2e", "a/./b", "a\x00", "C:/root"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                classification.safe_directory(value)
        with self.assertRaises(ValueError):
            classification.check_scope({"target_base": "old"}, SimpleNamespace(cd2_target="new"))

    def test_duplicate_keeps_original_directory_and_migration_idempotent(self):
        task = self.task()
        self.mode("type")
        repeated = self.task(media_kind="视频")
        self.assertEqual(task, repeated)
        self.db._conn.execute("ALTER TABLE tasks DROP COLUMN classification_parent")
        self.db._conn.execute("PRAGMA user_version=3")
        reopened = TaskDB(self.path)
        self.addCleanup(reopened.close)
        self.assertEqual(reopened._conn.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)
        self.assertEqual(reopened.get(task["id"]), task)
