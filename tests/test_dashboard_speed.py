"""Dashboard rate semantics, freshness and privacy without live Telegram/WebDAV."""
from __future__ import annotations

import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from test_scenarios import make_service, make_settings

from tg2cloud.domain.actors import user_scope
from tg2cloud.monitoring.resources import ResourceSnapshot
from tg2cloud.persistence.sqlite import TaskDB


class DashboardSpeedTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.settings = make_settings(Path(self.temp.name))
        self.db = TaskDB(self.settings.data_dir / "speed.db")
        self.service = make_service(self.settings, self.db)
        self.service.destination_healthy = True
        self.service.destination_error = ""
        self.service.snapshot = ResourceSnapshot(10, 2 * 1024**3, 0, 60 * 1024**3, 0, time.time())
        self.service.snapshot = replace(self.service.snapshot, network_bytes_per_second=12 * 1024**2)

    async def asyncTearDown(self):
        self.db.close()
        self.temp.cleanup()

    def task(self, state="uploading", *, sender=None, message=1):
        task, _ = self.db.create_task(
            chat_id=1, message_id=message,
            sender_id=self.settings.allowed_user_id if sender is None else sender,
            file_name="sample.mp4", file_size=1024**2,
        )
        self.db.update(task["id"], state=state)
        return self.db.get(task["id"])

    def sample(self, task, *, speed=3 * 1024**2, age=0):
        self.service._progress[task["id"]] = {
            "stage": "upload", "speed": speed, "bytes": 100,
            "at": time.monotonic() - age, "started": time.monotonic() - 10,
        }

    def test_no_sample_is_unknown_not_inferred_from_nic(self):
        self.task()
        text = self.service._format_status()
        self.assertIn("⬆️ --\n", text)
        self.assertIn("🌐 12.00 MB/s", text)
        self.assertIn("⬇️ 0 B/s", text)

    def test_fresh_zero_positive_stale_and_finished_samples(self):
        task = self.task()
        for speed, age, expected in ((3 * 1024**2, 0, "3.00 MB/s"), (0, 0, "0 B/s"),
                                     (3 * 1024**2, 6, "--")):
            with self.subTest(speed=speed, age=age):
                self.sample(task, speed=speed, age=age)
                self.assertIn(f"⬆️ {expected}\n", self.service._format_status())
        for state in ("verifying", "finalizing", "cleanup_pending", "completed"):
            with self.subTest(state=state):
                self.db.update(task["id"], state=state)
                self.assertIn("⬆️ 0 B/s\n", self.service._format_status())

    def test_member_only_sees_own_rate_and_unknown_sum(self):
        owner = self.task()
        member = self.task(sender=123456789, message=2)
        self.sample(owner, speed=99 * 1024**2)
        with user_scope(123456789):
            text = self.service._format_status()
            self.assertIn("⬆️ --\n", text)
            self.assertIn("🌐 --", text)
            self.assertNotIn("99.00", text)
            self.assertNotIn("12.00", text)
            self.sample(member, speed=2 * 1024**2)
            text = self.service._format_status()
            self.assertIn("⬆️ 2.00 MB/s\n", text)
            self.assertIn("🌐 2.00 MB/s", text)

    def test_details_and_queue_accept_unknown_and_stale_rates(self):
        task = self.task()
        for speed, age in ((None, 0), (1024, 6)):
            self.sample(task, speed=speed, age=age)
            self.assertIn("｜--", self.service._format_task(task))
            self.assertIn("｜--", self.service._format_queue_task(task))

    async def test_fresh_health_refresh_edits_same_message_without_network_probe(self):
        self.service._probe_destination_once = AsyncMock()
        event = SimpleNamespace(data=b"refresh:home", answer=AsyncMock(), edit=AsyncMock())
        await self.service._handle_callback(event)
        self.service._probe_destination_once.assert_not_awaited()
        event.answer.assert_awaited_once_with()
        event.edit.assert_awaited_once()
        self.assertIn("⬆️ 0 B/s\n", event.edit.await_args.args[0])

    def test_both_editions_share_compact_member_and_admin_text_without_extra_labels(self):
        self.service.snapshot = replace(self.service.snapshot, network_bytes_per_second=0)
        self.db.change_family_user(self.settings.allowed_user_id,
                                   {"id": 123456789, "action": "add", "revision": "initial"})
        for backend, label in (("clouddrive2", "CloudDrive2"), ("openlist", "OpenList")):
            self.service.settings = replace(self.settings, storage_backend=backend, destination_label=label)
            with patch("tg2cloud.telegram.views.time.strftime", return_value="19:03:25"):
                admin = self.service._format_status()
                with user_scope(123456789):
                    member = self.service._format_status()
                    self.assertEqual(len(self.service._user_home_buttons()[0]), 2)
                self.assertEqual(len(self.service._user_home_buttons()[0]), 3)
            self.assertEqual(member, admin)
            self.assertIn("🟢 正常运行 · " + label, member)
            self.assertIn("⬆️ 0 B/s\n", member)
            for text in (admin, member):
                self.assertNotIn("写入网关", text)
                self.assertNotIn("仅你的任务与传输速度", text)
                self.assertNotIn("共用保存目录", text)

    async def test_missing_stale_and_future_health_still_probe(self):
        for last in (0, time.time() - self.settings.remote_health_interval - 5, time.time() + 60):
            with self.subTest(last=last):
                self.service.destination_last_checked = last
                self.service._probe_destination_once = AsyncMock()
                await self.service._refresh_destination_for_dashboard()
                self.service._probe_destination_once.assert_awaited_once_with()
