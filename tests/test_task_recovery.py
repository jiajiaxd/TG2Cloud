"""Offline recovery regressions using real SQLite and bounded streaming fixtures."""
from __future__ import annotations

import asyncio
import json
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from test_scenarios import FakeRclone, make_service, make_settings
from test_telethon_compat import callback_data

from tg2cloud.domain.errors import StagingScan, failure_kind
from tg2cloud.monitoring.resources import ResourceSnapshot
from tg2cloud.persistence.sqlite import TaskDB
from tg2cloud.storage.rclone import RcloneClient, RcloneError


class RecoveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.settings = make_settings(Path(self.temp.name))
        self.db = TaskDB(self.settings.data_dir / "test.db")
        self.addCleanup(self.db.close)
        self.service = make_service(self.settings, self.db)
        self.service.rclone = FakeRclone()
        self.service._notify = AsyncMock()

    def task(self, **fields):
        task, _ = self.db.create_task(chat_id=self.settings.allowed_user_id, message_id=1,
                                    sender_id=self.settings.allowed_user_id, media_key="document:1",
                                    file_name="example.bin", file_size=4)
        self.db.update(task["id"], **fields)
        return self.db.get(task["id"])

    def local(self):
        path = self.settings.download_dir / "1-example.bin"
        path.write_bytes(b"test")
        return path

    async def test_cancelled_reforward_requires_confirmation_and_replay_is_safe(self):
        task = self.task(state="cancelled")
        event = SimpleNamespace(sender_id=self.settings.allowed_user_id, is_private=True,
                                chat_id=self.settings.allowed_user_id, raw_text="", reply=AsyncMock(),
                                message=SimpleNamespace(id=2, media=True, document=SimpleNamespace(id=1),
                                                        sender_id=self.settings.allowed_user_id,
                                                        chat_id=self.settings.allowed_user_id,
                                                        file=SimpleNamespace(size=4, ext=".bin", name="example.bin")))
        await self.service._on_message(event)
        self.assertEqual(self.db.get(task["id"])["state"], "cancelled")
        event.reply.assert_not_awaited()
        self.assertEqual(self.service.reactions.pending[(event.chat_id, 2)], "🫡")
        await self.service._handle_command(
            SimpleNamespace(is_reply=True, get_reply_message=AsyncMock(return_value=event.message), reply=AsyncMock()),
            f"/restart {task['id']}",
        )
        plan = self.service._recovery_confirmations[task["id"]]
        callback = SimpleNamespace(edit=AsyncMock())
        await self.service._confirm_recovery(callback, task["id"], plan["token"])
        await self.service._confirm_recovery(callback, task["id"], plan["token"])
        updated = self.db.get(task["id"])
        self.assertEqual((updated["state"], updated["message_id"]), ("queued", 2))
        self.assertEqual(len(self.db.list_recent()), 1)
        self.assertEqual(len(self.db.events(task["id"])), 2)

    async def test_two_connections_only_one_confirmed_restart_wins(self):
        task = self.task(state="cancelled")
        second = TaskDB(self.db.path)
        try:
            def submit(db):
                return db.requeue(task["id"], sender_id=self.settings.allowed_user_id,
                                  expected_updated_at=task["updated_at"], local_complete=False,
                                  restart_cancelled=True, fresh_path=True)
            with ThreadPoolExecutor(2) as pool:
                self.assertEqual(sorted(pool.map(submit, [self.db, second])), [False, True])
        finally:
            second.close()
        self.db.recover(self.settings.download_dir)
        self.assertEqual(self.db.get(task["id"])["state"], "queued")

    async def test_active_completed_and_cancelling_cannot_restart(self):
        for state in ("uploading", "completed", "confirmed", "queued"):
            task = self.task(state=state)
            self.assertFalse(self.db.requeue(task["id"], sender_id=self.settings.allowed_user_id,
                                            expected_updated_at=task["updated_at"], local_complete=False,
                                            restart_cancelled=True))
        task = self.task(state="cancelled", cancel_requested=1)
        event = SimpleNamespace(reply=AsyncMock())
        await self.service._offer_recovery(event, task["id"])
        self.assertFalse(getattr(self.service, "_recovery_confirmations", {}))

    async def test_openlist_partial_final_is_held_then_renamed_without_deletion(self):
        self.service.settings = replace(self.settings, storage_backend="openlist")
        local = self.local()
        task = self.task(state="waiting_upload", local_path=str(local))
        async def interrupted(path, remote, **kwargs):
            self.service.rclone.files[remote] = b"te"
            raise RcloneError("connection reset secret-value")
        self.service.rclone.upload = AsyncMock(side_effect=interrupted)
        with patch("tg2cloud.app.asyncio.sleep", new=AsyncMock()):
            await self.service._upload_one(task["id"])
        held = self.db.get(task["id"])
        self.assertEqual(held["failure_kind"], "remote_conflict")
        self.assertEqual(self.service.rclone.upload.await_count, 1)
        self.assertTrue(local.exists())
        self.assertFalse(self.service.rclone.removed)
        self.db.recover(self.settings.download_dir)
        self.assertEqual(self.db.get(task["id"])["state"], "upload_failed_retained")
        self.assertFalse(self.service._retry_task(held))
        event = SimpleNamespace(reply=AsyncMock(), edit=AsyncMock())
        await self.service._offer_recovery(event, task["id"], rename=True)
        plan = self.service._recovery_confirmations[task["id"]]
        await self.service._confirm_recovery(event, task["id"], plan["token"])
        self.service.rclone.upload = FakeRclone.upload.__get__(self.service.rclone)
        await self.service._upload_one(task["id"])
        done = self.db.get(task["id"])
        self.assertEqual(done["state"], "completed")
        self.assertEqual(done["verification_method"], "size")
        self.assertIsNotNone(done["verified_at"])
        self.assertEqual(self.service.rclone.files["example.bin"], b"te")
        self.assertEqual(self.service.rclone.files["example (task-1).bin"], b"test")
        self.assertFalse(self.service.rclone.removed)

    async def test_final_size_mismatch_never_deletes_final_on_either_backend(self):
        for backend in ("clouddrive2", "openlist"):
            task = self.task(state="uploading", local_path=str(self.local()), remote_final_path="example.bin")
            self.service.settings = replace(self.settings, storage_backend=backend)
            self.service.rclone.files["example.bin"] = b"t"
            await self.service._upload_one(task["id"])
            self.assertEqual(self.db.get(task["id"])["failure_kind"], "remote_conflict")
            self.assertFalse(self.service.rclone.removed)
            self.assertTrue(self.local().exists())

    async def test_reopened_database_recognizes_already_received_final_without_reupload(self):
        for backend in ("clouddrive2", "openlist"):
            with self.subTest(backend=backend):
                self.service.settings = replace(self.settings, storage_backend=backend)
                local = self.local()
                task = self.task(state="uploading", local_path=str(local), remote_final_path="example.bin",
                                 failure_kind=None, verification_method=None, verified_at=None)
                path = self.db.path
                self.db.close()
                self.db = TaskDB(path)
                self.addCleanup(self.db.close)
                self.service.db = self.db
                self.db.recover(self.settings.download_dir)
                self.service.rclone = FakeRclone()
                self.service.rclone.files["example.bin"] = b"test"
                self.service.rclone.upload = AsyncMock(side_effect=AssertionError("must not upload twice"))
                await self.service._upload_one(task["id"])
                final = self.db.get(task["id"])
                self.assertEqual(final["state"], "completed")
                self.assertEqual(final["verification_method"], "size")
                self.assertIsNotNone(final["verified_at"])
                self.service.rclone.upload.assert_not_awaited()
                self.assertFalse(self.service.rclone.removed)
                self.assertFalse(local.exists())

    async def test_auth_permission_and_rate_limit_stop_and_survive_restart(self):
        for code, kind in ((401, "authentication"), (403, "permission"), (429, "rate_limited")):
            task = self.task(state="waiting_upload", local_path=str(self.local()))
            self.service.rclone.upload = AsyncMock(side_effect=RcloneError(f"HTTP {code}: secret-value"))
            await self.service._upload_one(task["id"])
            self.assertEqual(self.service.rclone.upload.await_count, 1)
            self.assertEqual(self.db.get(task["id"])["failure_kind"], kind)
            self.assertNotIn("secret-value", self.db.get(task["id"])["error"])
            self.db.recover(self.settings.download_dir)
            self.assertEqual(self.db.get(task["id"])["state"], "upload_failed_retained")
        self.assertEqual(failure_kind("503 unavailable"), "server")

    async def test_recovery_foreign_task_and_stale_confirmation_rejected(self):
        task = self.task(state="cancelled")
        self.assertFalse(self.db.requeue(task["id"], sender_id=123,
                                        expected_updated_at=task["updated_at"], local_complete=False,
                                        restart_cancelled=True))
        event = SimpleNamespace(reply=AsyncMock(), edit=AsyncMock())
        await self.service._offer_recovery(event, task["id"])
        plan = self.service._recovery_confirmations[task["id"]]
        self.db.update(task["id"], wait_reason="changed")
        await self.service._confirm_recovery(event, task["id"], plan["token"])
        self.assertEqual(self.db.get(task["id"])["state"], "cancelled")

    async def test_incomplete_orphan_scan_cannot_claim_empty_or_delete(self):
        self.service.rclone.list_staging_objects = AsyncMock(return_value=StagingScan([], 10001, 0, False, "timeout"))
        event = SimpleNamespace(reply=AsyncMock())
        await self.service._command_orphans(event, ["/orphans", "clean"])
        text = event.reply.call_args.args[0]
        self.assertIn("未完成", text)
        self.assertIn("10001", text)
        self.assertNotIn("没有发现", text)
        self.assertFalse(getattr(self.service, "_orphan_cleanup_plan", None))
        self.assertFalse(self.service._is_orphan_staging(99, "../.uploading-99-file"))

    async def test_search_is_literal_owner_scoped_and_paged_across_failures(self):
        for i in range(12):
            task, _ = self.db.create_task(chat_id=1, message_id=i + 20,
                                         sender_id=self.settings.allowed_user_id if i < 11 else 123,
                                         file_name=f"100%_{i}.bin", file_size=4)
            self.db.update(task["id"], state="download_failed" if i % 2 else "upload_failed_retained")
        first = self.db.search(sender_id=self.settings.allowed_user_id, state="failed")
        second = self.db.search(sender_id=self.settings.allowed_user_id, state="failed", after_id=first[-1]["id"])
        self.assertEqual((len(first), len(second)), (6, 5))
        self.assertFalse({t["id"] for t in first} & {t["id"] for t in second})
        self.assertEqual(len(self.db.search(sender_id=self.settings.allowed_user_id, query="%_", limit=50)), 11)
        self.assertFalse(self.db.search(sender_id=self.settings.allowed_user_id, query="' OR 1=1 --"))

    async def test_cancel_race_with_completion_clears_cancellation_flag(self):
        task = self.task(state="uploading", local_path=str(self.local()))
        started = asyncio.Event()
        async def finishing():
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.db.update(task["id"], state="cleanup_pending")
        worker = asyncio.create_task(finishing())
        await started.wait()
        self.service.upload_tasks[task["id"]] = worker
        await self.service._command_cancel(SimpleNamespace(reply=AsyncMock()), ["/cancel", str(task["id"])])
        self.assertEqual(self.db.get(task["id"])["cancel_requested"], 0)
        self.assertEqual(self.db.get(task["id"])["state"], "cleanup_pending")
        self.assertFalse(self.service.rclone.removed)

    async def test_cleanup_verification_change_is_held_and_not_false_verified(self):
        task = self.task(state="cleanup_pending", local_path=str(self.local()), remote_path="example.bin",
                         verification_method="size", verified_at=time.time())
        self.service.rclone.files["example.bin"] = b"partial"
        await self.service._upload_one(task["id"])
        saved = self.db.get(task["id"])
        self.assertEqual(saved["failure_kind"], "remote_conflict")
        self.assertIsNone(saved["verified_at"])
        self.assertTrue(Path(saved["local_path"]).exists())
        self.db.recover(self.settings.download_dir)
        self.assertEqual(self.db.get(task["id"])["state"], "verification_failed_retained")

    async def test_missing_remote_reuses_local_complete_file(self):
        task = self.task(state="cleanup_pending", local_path=str(self.local()), remote_path="missing.bin",
                         verification_method="size", verified_at=time.time())
        await self.service._upload_one(task["id"])
        self.assertEqual(self.db.get(task["id"])["state"], "completed")
        self.assertEqual(self.service.rclone.files["example.bin"], b"test")

    async def test_resource_pressure_blocks_new_download_and_recovers(self):
        self.task()
        self.service.destination_healthy = True
        self.service._sample_fresh = lambda: True
        self.service._destination_ready = lambda: True
        self.service.download_window = SimpleNamespace(value=1)
        self.service.upload_window = SimpleNamespace(value=1)
        self.service.snapshot = ResourceSnapshot(1, 1024**3, 0, 100 * 1024**3, 0, time.time(), (("database", 1),))
        self.service._download_one = AsyncMock()
        await self.service._start_downloads()
        self.assertFalse(self.service.download_tasks)
        self.assertIn("安全线", self.service._resource_pause_reason)
        self.service.snapshot = replace(self.service.snapshot, filesystems=(("database", 100 * 1024**3),))
        with patch("tg2cloud.transfer.scheduler.shutil.disk_usage", return_value=SimpleNamespace(free=100 * 1024**3)):
            await self.service._start_downloads()
        await asyncio.gather(*self.service.download_tasks.values())
        self.service._download_one.assert_awaited_once()

    async def test_callback_recovery_keeps_confirmation_button(self):
        task = self.task(state="cancelled")
        event = SimpleNamespace(edit=AsyncMock())
        await self.service._callback_command(event, self.service._command_retry, ["/retry", str(task["id"])], task["id"])
        buttons = event.edit.call_args.kwargs["buttons"]
        self.assertTrue(callback_data(buttons[0][0]).startswith(b"task:recover_yes:"))

    async def test_failed_scan_does_not_reuse_previous_complete_summary(self):
        self.service._last_staging_scan = StagingScan([], 100, 0, True)
        self.service.rclone.list_staging_objects = AsyncMock(side_effect=TimeoutError())
        event = SimpleNamespace(reply=AsyncMock())
        await self.service._command_orphans(event, ["/orphans"])
        self.assertIn("未完成", event.reply.call_args.args[0])
        self.assertNotIn("100", event.reply.call_args.args[0])

    async def test_direct_final_upload_has_no_internal_write_retries(self):
        for backend, retries, low in (("openlist", "1", "1"), ("clouddrive2", "2", "5")):
            client = RcloneClient(replace(self.settings, storage_backend=backend))
            client.prepare_destination = AsyncMock()
            client._run = AsyncMock()
            await client.upload(self.local(), "safe.bin")
            args = client._run.call_args.args
            self.assertEqual(args[args.index("--retries") + 1], retries)
            self.assertEqual(args[args.index("--low-level-retries") + 1], low)

    async def test_interrupted_stream_preserves_partial_object_for_both_editions(self):
        for backend in ("clouddrive2", "openlist"):
            self.service.settings = replace(self.settings, storage_backend=backend)
            task = self.task(state="reserved", transfer_mode="stream", remote_path=None,
                             remote_temp_path=None, remote_final_path=None, download_retries=0)
            fake = FakeRclone()
            async def open_stream(path, exact_size, storage=fake):
                async def write(data):
                    storage.files[path] = data
                return SimpleNamespace(write=write, abort=AsyncMock())
            async def interrupted(message, *, file, progress_callback):
                await file.write(b"pa")
                raise RcloneError("connection reset")
            fake.open_upload_stream = open_stream
            self.service.rclone = fake
            self.service._source = SimpleNamespace(get_messages=AsyncMock(return_value=SimpleNamespace(media=True)),
                                                   download_media=interrupted)
            with patch("tg2cloud.app.asyncio.sleep", new=AsyncMock()):
                await self.service._stream_one(task["id"])
            self.assertEqual(self.db.get(task["id"])["failure_kind"], "remote_conflict")
            self.assertEqual(list(fake.files.values()), [b"pa"])
            self.assertFalse(fake.removed)


class ScanTests(unittest.IsolatedAsyncioTestCase):
    async def read(self, data: bytes, code=0):
        stream = asyncio.StreamReader()
        stream.feed_data(data)
        stream.feed_eof()
        scan = StagingScan()
        process = SimpleNamespace(stdout=stream, wait=AsyncMock(return_value=code))
        await RcloneClient._read_staging(process, scan)
        return scan

    async def test_more_than_ten_thousand_and_path_scope(self):
        items = [{"Name": f"normal-{i}"} for i in range(10001)]
        items += [{"Name": ".uploading-42-example"}, {"Name": ".uploading-43-../other"},
                  {"Name": ".uploading-44-file", "Path": "outside/.uploading-44-file"}]
        scan = await self.read(json.dumps(items).encode())
        self.assertEqual(scan.checked, 10004)
        self.assertEqual(scan.objects, [(42, ".uploading-42-example")])
        self.assertTrue(scan.complete)

    async def test_truncated_invalid_large_and_failed_lists_rejected(self):
        for data in (b'[', b'[]secret', b'[{"Name":"x"},]', b'["not-an-object"]', b'[{"Name":"' + b'x' * (1024 * 1024 + 1)):
            with self.subTest(length=len(data)), self.assertRaises(ValueError):
                await self.read(data)
        with self.assertRaises(ValueError):
            await self.read(b'[]', code=1)

    async def test_candidate_bound_does_not_report_complete(self):
        items = [{"Name": f".uploading-{i + 1}-test"} for i in range(20001)]
        with self.assertRaisesRegex(ValueError, "candidate limit"):
            await self.read(json.dumps(items).encode())

    async def test_timeout_kills_process_and_returns_incomplete(self):
        with tempfile.TemporaryDirectory() as folder:
            client = RcloneClient(make_settings(Path(folder)))
            client.ensure_config = AsyncMock()
            stderr = asyncio.StreamReader()
            stderr.feed_eof()
            process = SimpleNamespace(stderr=stderr, returncode=None, wait=AsyncMock(return_value=1), kill=lambda: None)
            client._read_staging = AsyncMock(side_effect=TimeoutError())
            with patch("tg2cloud.storage.rclone.asyncio.create_subprocess_exec", new=AsyncMock(return_value=process)), \
                    patch.object(process, "kill") as kill:
                result = await client.list_staging_objects()
            self.assertFalse(result.complete)
            kill.assert_called_once()
