"""Naming regressions at Telegram caption and video suffix boundaries."""
from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from telethon import events
from telethon.tl import types
from test_scenarios import make_service, make_settings

from tg2cloud.persistence.sqlite import TaskDB


class NamingIngestionEdgeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.settings = make_settings(Path(temporary.name))
        self.db = TaskDB(self.settings.data_dir / "ingestion.db")
        self.addCleanup(self.db.close)
        self.service = make_service(self.settings, self.db)
        self.service.snapshot = None
        self.service.client = SimpleNamespace(get_messages=AsyncMock(side_effect=AssertionError("no history lookup")))

    def video(self, ident=1, caption="", *, name="123.mp4", grouped_id=None, sender=None):
        sender = self.settings.allowed_user_id if sender is None else sender
        stamp = datetime(2026, 10, 19, tzinfo=timezone.utc)
        document = types.Document(
            id=ident, access_hash=ident, file_reference=b"offline-fixture", date=stamp,
            mime_type="video/mp4", size=4, dc_id=2,
            attributes=[types.DocumentAttributeVideo(duration=1, w=16, h=16),
                        types.DocumentAttributeFilename(name)],
        )
        return types.Message(
            id=ident, peer_id=types.PeerUser(sender), from_id=types.PeerUser(sender),
            date=stamp, message=caption, media=types.MessageMediaDocument(document=document),
            grouped_id=grouped_id, out=False,
        )

    async def ingest(self, message):
        with patch.object(message, "reply", new=AsyncMock()) as reply:
            await self.service._on_message(events.NewMessage.Event(message))
        return reply

    async def test_slash_prefixed_media_caption_is_not_a_command_in_both_editions(self):
        self.service._handle_command = AsyncMock(side_effect=AssertionError("caption is not a command"))
        for ident, backend in enumerate(("clouddrive2", "openlist"), 1):
            with self.subTest(backend=backend):
                self.service.settings = replace(self.settings, storage_backend=backend)
                message = self.video(ident, "/春日旅行 第12集")
                await self.ingest(message)
                task = self.db.get(ident)
                self.assertEqual(task["file_name"], "春日旅行 第12集.mp4")
                self.assertEqual(task["original_file_name"], "123.mp4")
                self.assertEqual(task["state"], "queued")
        self.service._handle_command.assert_not_awaited()
        self.service.client.get_messages.assert_not_awaited()

    async def test_literal_start_and_pause_captions_are_received_without_side_effects(self):
        self.service._handle_command = AsyncMock(side_effect=AssertionError("caption is not a command"))
        for ident, caption in enumerate(("/start", "/pause"), 1):
            await self.ingest(self.video(ident, caption))
            self.assertEqual(self.db.get(ident)["state"], "queued")
        self.assertFalse(self.db.is_paused())
        self.service._handle_command.assert_not_awaited()

    async def test_text_only_start_keeps_existing_command_dispatch(self):
        self.service._format_status = Mock(return_value="existing status")
        self.service._user_home_buttons = Mock(return_value=[["existing buttons"]])
        message = self.video(caption="/start")
        message.media = None
        reply = await self.ingest(message)
        reply.assert_awaited_once_with("existing status", buttons=[["existing buttons"]],
                                       parse_mode="html", link_preview=False)
        self.assertEqual(self.db.list_recent(), [])

    async def test_downloadable_document_with_command_caption_keeps_document_name(self):
        message = self.video(caption="/start", name="report.pdf")
        message.document.mime_type = "application/pdf"
        message.document.attributes = [types.DocumentAttributeFilename("report.pdf")]
        await self.ingest(message)
        self.assertEqual(self.db.get(1)["file_name"], "report.pdf")
        self.assertEqual(self.db.get(1)["original_file_name"], "report.pdf")

    async def test_real_video_mime_corrects_only_nonvideo_extension_in_both_editions(self):
        ident = 0
        for backend in ("clouddrive2", "openlist"):
            self.service.settings = replace(self.settings, storage_backend=backend)
            for original, expected in (("123.exe", "春日旅行.mp4"),
                                       ("Movie.MKV", "Movie.MKV")):
                with self.subTest(backend=backend, original=original):
                    ident += 1
                    message = self.video(ident, "标题：春日旅行", name=original)
                    self.assertEqual(message.file.ext, ".mp4")
                    await self.ingest(message)
                    task = self.db.get(ident)
                    self.assertEqual(task["file_name"], expected)
                    self.assertEqual(task["original_file_name"], original)

    async def test_single_and_album_video_suffixes_follow_same_metadata_policy(self):
        for original, suffix in (("123.exe", ".mp4"), ("123.MKV", ".MKV")):
            ident = len(self.db.list_recent()) + 1
            with self.subTest(original=original):
                await self.ingest(self.video(ident, "标题：春日旅行", name=original))
                messages = [self.video(ident + 1, name=original, grouped_id=123),
                            self.video(ident + 2, "标题：春日旅行", name="456.mp4", grouped_id=123)]
                with patch.object(messages[0], "reply", new=AsyncMock()), \
                     patch.object(messages[1], "reply", new=AsyncMock()):
                    await self.service._on_album(events.Album.Event(messages))
                self.assertEqual(self.db.get(ident)["file_name"], "春日旅行" + suffix)
                self.assertEqual(self.db.get(ident + 1)["file_name"], "春日旅行-视频01" + suffix)
                self.assertEqual(self.db.get(ident + 1)["original_file_name"], original)

    async def test_caption_command_fix_does_not_bypass_authorization_or_private_chat(self):
        await self.ingest(self.video(caption="/start", sender=self.settings.allowed_user_id + 1))
        message = self.video(caption="/start")
        event = SimpleNamespace(sender_id=self.settings.allowed_user_id, is_private=False,
                                chat_id=-100, raw_text="/start", message=message, reply=AsyncMock())
        await self.service._on_message(event)
        self.assertEqual(self.db.list_recent(), [])
        event.reply.assert_not_awaited()

    async def test_repeated_command_like_media_keeps_existing_deduplication(self):
        message = self.video(caption="/春日旅行 第12集")
        await self.ingest(message)
        await self.ingest(message)
        self.assertEqual(len(self.db.list_recent()), 1)
        self.assertEqual(self.db.get(1)["file_name"], "春日旅行 第12集.mp4")


if __name__ == "__main__":
    unittest.main()
