"""Listener directory policy: synthetic Telegram metadata, SQLite and mocked WebDAV only."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time
import unicodedata
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

from test_listening import event, message
from test_scenarios import FakeRclone, make_service, make_settings
from test_telethon_compat import callback_data

from tg2cloud.domain.actors import user_scope
from tg2cloud.domain.classification import safe_directory
from tg2cloud.domain.planning import name_plan
from tg2cloud.domain.source_directories import (
    CATEGORIES,
    columns,
    folder_name,
    media_directory,
)
from tg2cloud.listening import account, rules
from tg2cloud.listening.service import (
    CheckedSource,
    Listener,
    ListenerReadError,
    source_error,
)
from tg2cloud.persistence import features
from tg2cloud.persistence.migrations import SCHEMA_VERSION
from tg2cloud.persistence.plans import Plans
from tg2cloud.persistence.sqlite import TaskDB
from tg2cloud.telegram import planning


class FolderNameTests(unittest.TestCase):
    def test_emoji_sequences_flags_keycaps_and_controls_are_removed(self):
        title = "🎬👨‍👩‍👧‍👦🇨🇳👍🏽1️⃣ 東京 / 여행\\课堂:%2026\n"
        result = folder_name(title, -1001)
        self.assertEqual(result, "東京 여행 课堂 2026")
        self.assertEqual(folder_name("🎬🇨🇳👨‍👩‍👧‍👦", -1001), "来源-1001")
        self.assertNotIn("\u202e", folder_name("电影\u202e频道", -1))

    def test_multilingual_column_and_utf8_limits_include_suffix(self):
        for title in (
            "中" * 80,
            "a" * 100,
            "한글東京abc" * 40,
            "e\u0301" * 90,
            "अध्ययन" * 60,
        ):
            for suffix in ("", "-来源12345"):
                with self.subTest(title=title[:8], suffix=suffix):
                    name = folder_name(title, -1, suffix)
                    self.assertLessEqual(columns(name), 60)
                    self.assertEqual(name, unicodedata.normalize("NFC", name))
                    for category in CATEGORIES:
                        self.assertEqual(
                            safe_directory(name + "/" + category), name + "/" + category
                        )
                    self.assertTrue(name.endswith(suffix))
        self.assertEqual(len(folder_name("中" * 40, -1)), 30)
        self.assertEqual(len(folder_name("a" * 100, -1)), 60)

    def test_malicious_titles_stay_in_one_safe_component(self):
        for title in (
            "../../etc/passwd",
            "/",
            "a\x00b",
            "a\ud800b",
            "../%2e%2e/C:",
            ".",
            "\u0301" * 400,
        ):
            with self.subTest(title=ascii(title)):
                result = folder_name(title, -99)
                self.assertTrue(result)
                self.assertNotIn("/", result)
                self.assertEqual(safe_directory(result), result)
                self.assertLessEqual(len(result.encode("utf-8")), 112)


class SourceDirectoryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        zone = patch.dict(os.environ, {"TZ": "UTC"})
        zone.start()
        self.addCleanup(zone.stop)
        self.settings = make_settings(Path(self.temp.name))
        self.path = self.settings.data_dir / "tg115.db"
        self.db = TaskDB(self.path)
        self.addCleanup(self.db.close)
        self.owner = make_service(self.settings, self.db)
        self.admin = self.settings.allowed_user_id
        self.owner._notify = AsyncMock()
        self.owner.rclone = NS(ensure_directory=AsyncMock())
        self.listener = Listener(self.owner)
        self.owner.listener = self.listener
        self.repo = self.listener.plans
        account.write_state(self.db, account=42, enabled=True)
        self.listener.client = NS(
            get_messages=AsyncMock(return_value=[message()]),
            download_media=AsyncMock(),
            disconnect=AsyncMock(),
        )

    def source(self, chat=-1001, title="🎬 城市旅行", *, new=True):
        return self.repo.save_source(
            self.admin,
            account=42,
            chat=chat,
            title=title,
            cursor=0,
            config={"rules": {"all_attachments": True}},
            target_base=self.settings.cd2_target if new else None,
        )

    def plan(self, source, mid=1, **changes):
        source = self.repo.source(self.admin, source["id"])
        if not source["enabled"]:
            self.repo.change_source(
                self.admin, source["id"], source["revision"], enabled=True
            )
        item = rules.facts(message(mid, chat=source["chat"])) | changes
        return self.repo.create(
            self.admin,
            item,
            name_plan(item["original"], item["caption"], "fallback.mp4"),
            identity="listener:42",
            source=source["id"],
            target_base=self.settings.cd2_target,
        )[0]

    async def test_add_creates_parent_only_and_keeps_paused_video_confirmation_defaults(
        self,
    ):
        with (
            patch(
                "tg2cloud.listening.service.verified_chat",
                new=AsyncMock(return_value=NS(title="🎬 城市旅行")),
            ),
            patch("telethon.utils.get_peer_id", return_value=-1001),
        ):
            source = await self.listener.add(
                self.admin, "@fixture", {"rules": {"groups": [{"types": ["视频"]}]}}
            )
        self.assertEqual(source["config"]["source_folder"], "城市旅行")
        self.assertFalse(source["enabled"])
        self.assertTrue(source["config"]["confirmation"])
        self.assertEqual(source["config"]["rules"]["groups"][0]["types"], ["视频"])
        self.owner.rclone.ensure_directory.assert_awaited_once_with("城市旅行")
        self.listener.client.download_media.assert_not_awaited()
        self.assertEqual(self.db.counts(), {})
        self.assertEqual(self.repo.directories(self.admin), {})
        self.assertEqual(self.listener.client.get_messages.await_count, 1)

    async def test_bot_add_uses_new_filter_defaults_and_preserves_existing_source(self):
        existing = self.source(new=False)
        with (
            user_scope(self.admin),
            patch.object(self.listener, "_resolve", new=AsyncMock(
                return_value=(NS(title="合成新频道"), [message(9, chat=-1002)]))),
            patch("telethon.utils.get_peer_id", return_value=-1002),
        ):
            incoming = event(self.admin)
            planning.interactions(self.owner)[self.admin] = (time.monotonic() + 300, ("add",))
            self.assertTrue(await planning.text(self.owner, incoming, "@fixture"))
        source = next(s for s in self.repo.sources(self.admin) if s["chat"] == -1002)
        self.assertEqual(source["config"]["rules"], rules.defaults())
        self.assertFalse(source["enabled"])
        self.assertTrue(source["config"]["confirmation"])
        self.assertEqual(self.repo.source(self.admin, existing["id"]), existing)
        self.assertNotIn(self.admin, planning.interactions(self.owner))
        shown = "\n".join(c.args[0] for c in incoming.reply.await_args_list)
        self.assertIn("排除：广告、内部群、搜索引擎", shown)
        self.assertIn("大小：50.00MB 至 不限上限", shown)
        self.assertIn("文字范围：文件名和说明", shown)
        self.listener.client.download_media.assert_not_awaited()
        self.assertEqual(self.db.counts(), {})

    async def test_mkdir_failure_retains_paused_registration_and_can_retry(self):
        self.owner.rclone.ensure_directory.side_effect = RuntimeError("private-token")
        with (
            patch(
                "tg2cloud.listening.service.verified_chat",
                new=AsyncMock(return_value=NS(title="旅行")),
            ),
            patch("telethon.utils.get_peer_id", return_value=-1001),
        ):
            source = await self.listener.add(
                self.admin, "@fixture", {"rules": {"groups": [{"types": ["视频"]}]}}
            )
        self.assertFalse(source["enabled"])
        self.assertIn("目录创建未完成", source["status"])
        self.assertNotIn("private-token", source["status"])
        self.owner.rclone.ensure_directory.side_effect = None
        repaired = await self.listener.prepare_directory(self.admin, source)
        self.assertIn("已就绪", repaired["status"])
        self.assertFalse(repaired["enabled"])
        self.assertEqual(len(self.repo.sources(self.admin)), 1)

    async def test_cancellation_and_delete_during_mkdir_cannot_enable_source(self):
        source = self.source()
        self.owner.rclone.ensure_directory.side_effect = asyncio.CancelledError
        with self.assertRaises(asyncio.CancelledError):
            await self.listener.prepare_directory(self.admin, source)
        self.assertFalse(self.repo.source(self.admin, source["id"])["enabled"])

        async def delete(_):
            current = self.repo.source(self.admin, source["id"])
            self.repo.change_source(
                self.admin, source["id"], current["revision"], delete=True
            )

        self.owner.rclone.ensure_directory.side_effect = delete
        with self.assertRaises(ValueError):
            await self.listener.prepare_directory(self.admin, source)
        self.assertTrue(self.repo.source(self.admin, source["id"])["deleted"])

    def test_collisions_reserved_categories_and_readding_freeze_directory(self):
        first = self.source(title="视频")
        self.assertNotEqual(first["config"]["source_folder"], "视频")
        second = self.source(-1002, title="视频")
        self.assertNotEqual(
            first["config"]["source_folder"], second["config"]["source_folder"]
        )
        self.repo.change_source(self.admin, first["id"], first["revision"], delete=True)
        restored = self.repo.save_source(
            self.admin,
            account=42,
            chat=-1001,
            title="新标题",
            cursor=99,
            config={"rules": {"all_attachments": True}},
            target_base="changed",
        )
        self.assertEqual(restored["id"], first["id"])
        self.assertEqual(
            restored["config"]["source_folder"], first["config"]["source_folder"]
        )
        self.assertEqual(restored["config"]["source_base"], self.settings.cd2_target)
        with self.assertRaises(ValueError):
            media_directory(restored["config"], base="changed")

    def test_classification_is_independent_and_all_six_types_use_source_folder(self):
        source = self.source()
        for mid, (kind, mime, ext, category) in enumerate(
            [
                ("视频", "video/mp4", ".mp4", "视频"),
                ("图片", "image/jpeg", ".jpg", "图片"),
                ("音频", "audio/mpeg", ".mp3", "音频"),
                ("文档", "application/pdf", ".pdf", "文档"),
                ("文档", "application/zip", ".zip", "压缩包"),
                ("", "", ".bin", "其他文件"),
            ],
            1,
        ):
            for mode in ("off", "year", "month", "type_month"):
                features.change(
                    self.db._conn,
                    self.db.feature_settings()["revision"],
                    {"classification": mode},
                )
                item_id = mid * 10 + ("off", "year", "month", "type_month").index(mode)
                p = self.plan(source, item_id, kind=kind, mime=mime, extension=ext)
                self.assertEqual(
                    p["payload"]["directory_override"], "城市旅行/" + category
                )
                self.assertEqual(p["payload"]["directory_origin"], "source")

    def test_legacy_source_manual_and_aliases_are_not_automatically_rerouted(self):
        source = self.source(new=False)
        features.change(
            self.db._conn,
            self.db.feature_settings()["revision"],
            {"classification": "type"},
        )
        self.assertEqual(self.plan(source)["payload"]["directory_override"], "视频")
        item = rules.facts(message(2))
        p = self.repo.create(
            self.admin,
            item,
            name_plan(item["original"], "", "fallback.mp4"),
            target_base=self.settings.cd2_target,
        )[0]
        self.assertEqual(p["payload"]["directory_override"], "视频")
        self.repo.set_directory(self.admin, "旧目录", "我的课程", [])
        current = self.repo.source(self.admin, source["id"])
        self.repo.change_source(
            self.admin,
            source["id"],
            current["revision"],
            config=current["config"] | {"directory": "旧目录"},
        )
        current = self.repo.source(self.admin, source["id"])
        self.listener.client.download_media.assert_not_awaited()
        p = self.repo.create(
            self.admin,
            rules.facts(message(3)),
            name_plan("a.mp4", "", "a.mp4"),
            identity="listener:42",
            source=current["id"],
            directory_alias="旧目录",
            target_base=self.settings.cd2_target,
        )[0]
        self.assertEqual(p["payload"]["directory_override"], "我的课程")

    def test_restart_and_mode_change_keep_pending_paths_and_schema(self):
        source = self.source()
        p = self.plan(source)
        current = self.repo.source(self.admin, source["id"])
        self.repo.change_source(
            self.admin,
            source["id"],
            current["revision"],
            config=current["config"] | {"directory_mode": "legacy"},
        )
        reopened = TaskDB(self.path)
        try:
            repo = Plans(reopened, self.admin)
            task, _ = repo.submit(self.admin, p["id"], p["revision"])
            self.assertEqual(task["target_directory"], "城市旅行/视频")
            self.assertEqual(
                reopened._conn.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION
            )
        finally:
            reopened.close()

    def test_tampering_base_change_and_member_use_are_rejected(self):
        source = self.source()
        p = self.plan(source)
        payload = p["payload"] | {"directory_override": "另一个来源/视频"}
        self.db._conn.execute(
            "UPDATE transfer_plans SET payload=? WHERE id=?",
            (json.dumps(payload), p["id"]),
        )
        with self.assertRaises(PermissionError):
            self.repo.submit(self.admin, p["id"], p["revision"])
        current = self.repo.source(self.admin, source["id"])
        with self.assertRaises(ValueError):
            self.repo.change_source(
                self.admin,
                source["id"],
                current["revision"],
                config=current["config"] | {"source_folder": "other"},
            )
        with self.assertRaises(ValueError):
            self.repo.create(
                self.admin,
                rules.facts(message(2)),
                name_plan("a.mp4", "", "a.mp4"),
                identity="listener:42",
                source=source["id"],
                target_base="another-root",
            )
        with self.assertRaises(PermissionError):
            self.repo.source_config(2, current["config"])

    async def test_preview_is_read_only_and_shows_actual_source_media_path(self):
        source = self.source()
        self.listener.client.get_messages.return_value = [message()]
        with patch("tg2cloud.listening.service.verified_chat", new=AsyncMock()):
            before = self.db._conn.total_changes
            result = await self.listener.test(self.admin, source["id"])
        self.assertEqual(result[0][3]["directory_preview"], "城市旅行/视频")
        self.assertEqual(self.db._conn.total_changes, before)
        self.owner.rclone.ensure_directory.assert_not_awaited()

    async def test_both_backends_local_and_streaming_keep_existing_commit_verification(
        self,
    ):
        source = self.source()
        for index, (backend, stream) in enumerate(
            ((b, s) for b in ("clouddrive2", "openlist") for s in (False, True)), 1
        ):
            with self.subTest(backend=backend, stream=stream):
                msg = message(index, protected=True)
                p = self.plan(source, index)
                task, _ = self.repo.submit(self.admin, p["id"], p["revision"])
                self.db.update(
                    task["id"],
                    state="reserved",
                    transfer_mode="stream" if stream else "local",
                )
                self.owner.settings = replace(
                    self.settings, storage_backend=backend, destination_label=backend
                )
                self.owner.rclone = FakeRclone()
                self.owner.rclone.ensure_directory = AsyncMock()
                self.listener.client.get_messages.return_value = msg

                async def download(_message, *, file, progress_callback):
                    if isinstance(file, str):
                        Path(file).write_bytes(b"x" * 100)
                    else:
                        await file.write(b"x" * 100)
                    progress_callback(100, 100)
                    return file

                self.listener.client.download_media = download
                with patch("tg2cloud.listening.service.verified_chat", new=AsyncMock()):
                    await self.owner._download_one(task["id"])
                if not stream:
                    await self.owner._upload_one(task["id"])
                final = self.db.get(task["id"])
                self.assertEqual(final["state"], "completed")
                self.assertTrue(final["remote_path"].startswith("城市旅行/视频/"))
                self.assertEqual(final["verification_method"], "size")
                self.owner.rclone.ensure_directory.assert_awaited_with("城市旅行/视频")

    async def test_real_api_refusal_is_not_bypassed_or_automatically_retried(self):
        from telethon.errors import ChatForwardsRestrictedError

        source = self.source()
        p = self.plan(source)
        task, _ = self.repo.submit(self.admin, p["id"], p["revision"])
        reader = CheckedSource(self.listener, task)
        msg = message(protected=True)
        self.listener.client.get_messages.return_value = msg
        with patch("tg2cloud.listening.service.verified_chat", new=AsyncMock()):
            await reader.get_messages(-1001, ids=1)
        self.listener.client.download_media.side_effect = ChatForwardsRestrictedError(
            request=None
        )
        with self.assertRaisesRegex(ListenerReadError, "拒绝读取"):
            await reader.download_media(msg, file="unused")
        self.assertFalse(self.repo.source(self.admin, source["id"])["enabled"])
        self.listener.client.download_media.assert_awaited_once()

    async def test_add_failure_categories_and_private_error_text(self):
        from telethon.errors import (
            FloodWaitError,
            SessionRevokedError,
            UsernameInvalidError,
        )

        for exc, expected in (
            (OSError("private-token"), "超时"),
            (UsernameInvalidError(request=None), "无效"),
            (ListenerReadError("来源不是已加入且可访问的频道或群组"), "已加入"),
            (FloodWaitError(request=None, capture=123), "123"),
            (SessionRevokedError(request=None), "授权失效"),
        ):
            with (
                patch.object(self.listener, "_resolve", new=AsyncMock(side_effect=exc)),
                self.assertRaises(ListenerReadError) as caught,
            ):
                await self.listener.add(
                    self.admin, "@fixture", {"rules": {"all_attachments": True}}
                )
            self.assertIn(expected, str(caught.exception))
            self.assertNotIn("private-token", str(caught.exception))
        self.assertEqual(self.repo.sources(self.admin), [])
        self.assertFalse(account.state(self.db)["enabled"])
        self.assertNotIn("private-token", source_error(RuntimeError("private-token")))

    async def test_navigation_rows_and_add_failure_keep_cancel_button(self):
        with user_scope(self.admin):
            e = event(self.admin)
            await planning.settings(self.owner, e)
            rows = e.reply.await_args.kwargs["buttons"]
            self.assertEqual(
                [[b.text for b in row] for row in rows],
                [
                    ["切换确认模式", "命名设置"],
                    ["待确认列表", "修正记录"],
                    ["开启自动分类"],
                    ["目录别名管理", "返回系统状态"],
                ],
            )
            self.source()
            e = event(self.admin)
            await planning.listening(self.owner, e)
            rows = e.reply.await_args.kwargs["buttons"]
            self.assertEqual(callback_data(rows[2][0]), b"menu:home")
            self.assertIn("城市旅行", rows[3][0].text)
            planning.interactions(self.owner)[self.admin] = (
                time.monotonic() + 300,
                ("add",),
            )
            with patch.object(
                self.listener,
                "add",
                new=AsyncMock(side_effect=ListenerReadError("来源没有读取权限")),
            ):
                e = event(self.admin)
                await planning.text(self.owner, e, "@fixture")
            self.assertIn("读取权限", e.reply.await_args.args[0])
            self.assertEqual(
                e.reply.await_args.kwargs["buttons"][0][0].text, "取消填写"
            )
            self.assertIn(self.admin, planning.interactions(self.owner))

    def test_parallel_reservations_keep_full_width_colliding_names_distinct(self):
        databases = [TaskDB(self.path) for _ in range(4)]
        try:

            def register(index):
                repo = Plans(databases[index], self.admin)
                return repo.save_source(
                    self.admin,
                    account=42,
                    chat=-2000 - index,
                    title="中" * 40,
                    cursor=0,
                    config={"rules": {"all_attachments": True}},
                    target_base=self.settings.cd2_target,
                )["config"]["source_folder"]

            with ThreadPoolExecutor(max_workers=4) as pool:
                names = list(pool.map(register, range(4)))
            self.assertEqual(len(set(names)), 4)
            self.assertTrue(all(columns(name) <= 60 for name in names))
        finally:
            for database in databases:
                database.close()

    def test_empty_account_root_and_explicit_plan_alias_keep_scope_and_priority(self):
        source = self.repo.save_source(
            self.admin,
            account=42,
            chat=-1001,
            title="频道",
            cursor=0,
            config={"rules": {"all_attachments": True}},
            target_base="",
        )
        self.assertEqual(
            media_directory(source["config"], kind="视频", base=""), "频道/视频"
        )
        self.repo.change_source(
            self.admin, source["id"], source["revision"], enabled=True
        )
        item = rules.facts(message())
        p = self.repo.create(
            self.admin,
            item,
            name_plan(item["original"], "", "fallback.mp4"),
            identity="listener:42",
            source=source["id"],
            target_base="",
        )[0]
        self.repo.set_directory(self.admin, "本次目录", "我的选择", [])
        p = self.repo.edit(
            self.admin, p["id"], p["revision"], directory_alias="本次目录"
        )
        task, _ = self.repo.submit(self.admin, p["id"], p["revision"])
        self.assertEqual(task["target_directory"], "我的选择")
        self.assertEqual(task["target_base"], "")

    async def test_root_drift_pauses_and_never_makes_directory_in_new_root(self):
        source = self.source()
        self.repo.change_source(
            self.admin, source["id"], source["revision"], enabled=True
        )
        self.owner.settings = replace(self.settings, cd2_target="different-root")
        with self.assertRaisesRegex(ListenerReadError, "根目录已变化"):
            await self.listener.prepare_directory(self.admin, source)
        self.owner.rclone.ensure_directory.assert_not_awaited()
        current = self.repo.source(self.admin, source["id"])
        self.assertFalse(current["enabled"])
        self.assertIn("恢复原配置", current["status"])

    def test_old_raw_json_history_does_not_remove_bound_folder_or_change_pending_paths(
        self,
    ):
        source = self.source()
        p = self.plan(source)
        current = self.repo.source(self.admin, source["id"])
        legacy = {"rules": {"groups": [{"types": ["视频"]}]}, "confirmation": False}
        self.repo.change_source(
            self.admin, source["id"], current["revision"], config=legacy
        )
        restored = self.repo.source(self.admin, source["id"])
        self.assertEqual(
            restored["config"]["source_folder"], source["config"]["source_folder"]
        )
        self.assertEqual(restored["config"]["directory_mode"], "legacy")
        task, _ = self.repo.submit(self.admin, p["id"], p["revision"])
        self.assertEqual(task["target_directory"], "城市旅行/视频")
