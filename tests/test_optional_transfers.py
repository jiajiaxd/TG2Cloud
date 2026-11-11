"""Full task flow with isolated fake transports, not real cloud data."""
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from test_scenarios import FakeRclone, make_service, make_settings

from tg2cloud.domain.actors import user_scope
from tg2cloud.persistence import features
from tg2cloud.persistence.sqlite import TaskDB


class ClassifiedRclone(FakeRclone):
    def __init__(self):
        super().__init__()
        self.directories = []

    async def ensure_directory(self, path):
        self.directories.append(path)


class OptionalTransferTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.settings = make_settings(Path(self.temp.name))
        self.db = TaskDB(self.settings.data_dir / "tg115.db")
        self.addCleanup(self.db.close)
        self.zone = patch.dict(os.environ, {"TZ": "UTC"})
        self.zone.start()
        self.addCleanup(self.zone.stop)
        self.service = make_service(self.settings, self.db)
        self.service._notify = AsyncMock()
        self.service.rclone = ClassifiedRclone()

    def mode(self, value):
        features.change(self.db._conn, self.db.feature_settings()["revision"], {"classification": value})

    async def test_both_backends_preserve_name_verify_cleanup_and_quota_once(self):
        self.mode("type_month")
        for number, backend in enumerate(("clouddrive2", "openlist"), 1):
            self.service.settings = replace(self.settings, storage_backend=backend)
            task, _ = self.db.create_task(chat_id=1, sender_id=self.settings.allowed_user_id, message_id=number,
                file_name="春日旅行.mp4", file_size=5, media_kind="视频", created_at=1791028800)
            local = self.settings.download_dir / f"{number}.mp4"
            local.write_bytes(b"movie")
            self.db.update(task["id"], state="waiting_upload", local_path=str(local))
            await self.service._upload_one(task["id"])
            result = self.db.get(task["id"])
            self.assertEqual(result["state"], "completed")
            self.assertEqual(result["file_name"], "春日旅行.mp4")
            self.assertTrue(result["remote_final_path"].startswith("视频/2026/10/"))
            self.assertFalse(local.exists())
            self.assertEqual(result["verification_method"], "size")
        self.assertEqual(len(self.service.rclone.files), 2)
        self.assertTrue(all(not name.startswith(".uploading-") for name in self.service.rclone.files))
        self.assertEqual(self.db.quota_usage(self.settings.allowed_user_id)["reserved_bytes"], 0)

    async def test_streaming_classifies_without_creating_local_file(self):
        self.mode("type")
        task, _ = self.db.create_task(chat_id=1, sender_id=self.settings.allowed_user_id, message_id=1,
            file_name="travel.mp4", file_size=5, media_kind="视频")
        self.db.update(task["id"], state="reserved")
        async def download(_message, *, file, progress_callback):
            await file.write(b"movie")
            progress_callback(5, 5)
        self.service.client = SimpleNamespace(get_messages=AsyncMock(return_value=SimpleNamespace(media=True)), download_media=download)
        await self.service._stream_one(task["id"])
        self.assertEqual(self.db.get(task["id"])["state"], "completed")
        self.assertEqual(self.service.rclone.files, {"视频/travel.mp4": b"movie"})
        self.assertFalse(list(self.settings.download_dir.iterdir()))

    async def test_album_freezes_rule_and_date_even_when_setting_changes_during_ingestion(self):
        self.mode("type_month")
        owner = self.settings.allowed_user_id
        messages = []
        for number, video in ((1, True), (2, False)):
            file = SimpleNamespace(name="123.mp4" if video else "123.jpg", ext=".mp4" if video else ".jpg", size=5,
                                   mime_type="video/mp4" if video else "image/jpeg")
            messages.append(SimpleNamespace(id=number, sender_id=owner, chat_id=owner, grouped_id=77, out=False,
                video=video, photo=None if video else SimpleNamespace(id=number), document=SimpleNamespace(id=number) if video else None,
                file=file, media=True, raw_text="春日旅行", entities=(), reply=AsyncMock()))
        queue = self.service.reactions.queue

        def change_after_first_reaction(chat_id, message_id, emoji):
            queue(chat_id, message_id, emoji)
            if message_id == 1:
                self.mode("off")

        event = SimpleNamespace(sender_id=owner, chat_id=owner, grouped_id=77, messages=messages, is_private=True)
        with patch("tg2cloud.telegram.handlers.time.time", return_value=1791028800), \
             patch.object(self.service.reactions, "queue", side_effect=change_after_first_reaction):
            await self.service._on_album(event)
        self.assertEqual(self.db.get(1)["target_directory"], "视频/2026/10")
        self.assertEqual(self.db.get(2)["target_directory"], "图片/2026/10")
        self.assertEqual(self.db.get(1)["created_at"], self.db.get(2)["created_at"])

    async def test_quota_command_never_uses_supplied_other_user_id(self):
        self.db.change_family_user(self.settings.allowed_user_id, {"id": 22, "action": "add", "revision": "initial"})
        self.service.snapshot = None
        reply = AsyncMock()
        with user_scope(22):
            await self.service._handle_command(SimpleNamespace(reply=reply), "/quota 999")
        self.assertIn("个人配额", reply.await_args.args[0])
        self.assertNotIn("999", reply.await_args.args[0])

    async def test_cleanup_pending_base_change_never_deletes_local_or_checks_wrong_remote(self):
        task, _ = self.db.create_task(chat_id=1, sender_id=self.settings.allowed_user_id, message_id=1,
            file_name="travel.mp4", file_size=5, target_base="old-base")
        local = self.settings.download_dir / "retained.mp4"
        local.write_bytes(b"movie")
        self.db.update(task["id"], state="cleanup_pending", local_path=str(local), remote_path="travel.mp4")
        self.service.rclone.exists = AsyncMock(side_effect=AssertionError("must not check changed base"))
        await self.service._upload_one(task["id"])
        self.assertTrue(local.is_file())
        self.assertEqual(self.db.get(task["id"])["state"], "verification_failed_retained")
        self.service.rclone.exists.assert_not_awaited()
