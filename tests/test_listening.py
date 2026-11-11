"""No real accounts: metadata, authorization, transactions, cursors and input identity."""

from __future__ import annotations

import asyncio
import os
import sqlite3
import stat
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

from test_scenarios import FakeRclone, make_service, make_settings
from test_telethon_compat import callback_data

from tg2cloud.domain.actors import user_scope
from tg2cloud.domain.planning import fields, name_plan, profile
from tg2cloud.listening import account, rules
from tg2cloud.listening.service import (
    CheckedSource,
    Listener,
    ListenerReadError,
    task_source,
    verified_chat,
)
from tg2cloud.persistence.plans import Plans
from tg2cloud.persistence.sqlite import TaskDB
from tg2cloud.telegram import planning


def message(
    mid=1,
    *,
    original="Ab83Kd91X.mp4",
    caption="城市漫游 第二季 第03集 1080P",
    kind="video",
    protected=False,
    chat=-1001,
    group=None,
    size=100,
):
    extension = Path(original).suffix
    return NS(
        id=mid,
        chat_id=chat,
        sender_id=42,
        grouped_id=group,
        out=False,
        media=True,
        document=NS(id=1000 + mid) if kind != "photo" else None,
        photo=NS(id=1000 + mid) if kind == "photo" else None,
        video=True if kind == "video" else None,
        audio=None,
        voice=None,
        entities=[],
        file=NS(
            name=original,
            size=size,
            ext=extension,
            mime_type="video/mp4"
            if kind == "video"
            else "image/jpeg"
            if kind == "photo"
            else "application/pdf",
        ),
        raw_text=caption,
        message=caption,
        noforwards=protected,
        date=datetime.now(timezone.utc) - timedelta(seconds=10),
    )


def event(actor, msg=None, text=""):
    msg = msg or NS(media=None, file=None, grouped_id=None)
    return NS(
        sender_id=actor,
        chat_id=actor,
        is_private=True,
        message=msg,
        raw_text=text,
        reply=AsyncMock(),
    )


class RuleTests(unittest.TestCase):
    def test_new_source_defaults_filter_size_type_and_exclusions(self):
        config = rules.defaults()
        threshold = 50 * 1024**2
        item = rules.facts(message(size=threshold))
        self.assertTrue(rules.evaluate(config, item, source_allowed=True)[0])
        self.assertTrue(rules.evaluate(config, item | {"size": 10 * 1024**3}, source_allowed=True)[0])
        for size in (threshold - 1, 1):
            with self.subTest(size=size):
                self.assertEqual(rules.evaluate(config, item | {"size": size}, source_allowed=True),
                                 (False, "大小不符"))
        for word in ("广告", "内部群", "搜索引擎"):
            for field in ("original", "caption"):
                with self.subTest(word=word, field=field):
                    self.assertEqual(rules.evaluate(config, item | {field: word}, source_allowed=True),
                                     (False, "排除关键词命中"))
        for kind in ("图片", "音频", "文档", "压缩包", "其他文件"):
            with self.subTest(kind=kind):
                self.assertFalse(rules.evaluate(config, item | {"kind": kind}, source_allowed=True)[0])

    def test_new_defaults_do_not_leak_between_sources_or_reinterpret_old_rules(self):
        changed = rules.defaults()
        changed["groups"][0]["types"].append("图片")
        changed["exclude"].clear()
        changed["min_bytes"] = 0
        fresh = rules.defaults()
        self.assertEqual(fresh["groups"][0]["types"], ["视频"])
        self.assertEqual(fresh["exclude"], ["广告", "内部群", "搜索引擎"])
        self.assertEqual(fresh["min_bytes"], 50 * 1024**2)
        self.assertEqual(fresh["max_bytes"], 0)
        self.assertEqual(fresh["scope"], "both")
        self.assertFalse(fresh["all_attachments"])
        # Validation of existing/custom rules does not silently inject new defaults.
        old = rules.validate({"groups": [{"types": ["视频"]}]})
        self.assertEqual(old["exclude"], [])
        self.assertEqual(old["min_bytes"], 0)
        self.assertTrue(rules.evaluate(old, rules.facts(message(caption="广告", size=1)),
                                       source_allowed=True)[0])

    def match(self, config, **changes):
        item = rules.facts(message()) | changes
        return rules.evaluate(config, item, source_allowed=True)

    def test_and_groups_or_and_excludes_are_hard(self):
        cfg = {
            "groups": [
                {
                    "types": ["视频"],
                    "extensions": [".MP4", "mkv"],
                    "keywords": ["物理", "数学"],
                },
                {"extensions": ["pdf"], "keywords": ["讲义"]},
            ],
            "exclude": ["广告"],
            "max_bytes": 1024,
        }
        self.assertTrue(self.match(cfg, caption="物理", original="原名.MP4")[0])
        self.assertTrue(
            self.match(
                cfg, caption="讲义", original="课件.pdf", extension=".pdf", kind="文档"
            )[0]
        )
        for changes in (
            {"caption": "物理 广告"},
            {"caption": "物理", "size": 2048},
            {"caption": "物理", "size": None},
            {"caption": "旅行"},
        ):
            self.assertFalse(self.match(cfg, **changes)[0])

    def test_unicode_keywords_any_all_and_scopes(self):
        cfg = {"groups": [{"keywords": ["물리", "ＡＢＣ"], "keyword_mode": "all"}]}
        self.assertTrue(self.match(cfg, caption="물리 abc")[0])
        self.assertFalse(self.match(cfg, caption="물리")[0])
        self.assertFalse(self.match(cfg | {"scope": "name"}, caption="물리 abc")[0])
        self.assertTrue(
            self.match(
                {"groups": [{"keywords": ["日本語", "旅行"]}]}, caption="日本語"
            )[0]
        )

    def test_all_attachments_requires_confirmation_and_invalid_never_widens(self):
        for cfg in (
            {},
            {"groups": [{}]},
            {"all_attachments": 1},
            {"scope": "unknown"},
            {"groups": [{"regex": ".*"}]},
            {"min_bytes": 5, "max_bytes": 4},
        ):
            with self.subTest(cfg=cfg), self.assertRaises(ValueError):
                rules.validate(cfg)
        self.assertTrue(self.match({"all_attachments": True})[0])
        self.assertFalse(self.match({"all_attachments": True}, attachment=False)[0])

    def test_names_exact_contains_glob_and_multi_extensions(self):
        for mode, value in (
            ("exact", "AB83KD91X.MP4"),
            ("contains", "83kd"),
            ("glob", "Ab*?.mp4"),
        ):
            self.assertTrue(
                self.match({"groups": [{"names": [value], "name_mode": mode}]})[0]
            )
        self.assertTrue(
            self.match(
                {"groups": [{"extensions": ["tar.gz"]}]}, original="课程.tar.gz"
            )[0]
        )
        with self.assertRaises(ValueError):
            rules.validate({"groups": [{"names": ["[ab]*"], "name_mode": "glob"}]})

    def test_protection_metadata_does_not_replace_permissions_or_size_checks(self):
        item = rules.facts(message(protected=None))
        for flag in (None, True, False):
            self.assertTrue(rules.evaluate({"all_attachments": True}, item | {"protected": flag}, source_allowed=True)[0])
        self.assertFalse(
            rules.evaluate(
                {"all_attachments": True},
                item | {"protected": False},
                source_allowed=False,
            )[0]
        )
        for size in (None, 0, -1, True, "100"):
            self.assertFalse(self.match({"all_attachments": True}, size=size)[0])

    def test_metadata_type_uses_mime_not_document_transport(self):
        m = message(kind="document")
        m.file.mime_type = "video/mp4"
        self.assertEqual(rules.facts(m)["kind"], "视频")
        self.assertEqual(rules.facts(message(kind="photo"))["kind"], "图片")


class NamingPlanTests(unittest.TestCase):
    def test_compatible_preserves_semantic_name_and_caption_modes_preserve_numbers(
        self,
    ):
        p = name_plan(
            "The Last Journey.mp4", "城市旅行 第03集", "fallback.mp4", kind="视频"
        )
        self.assertEqual(p["file_name"], "The Last Journey.mp4")
        p = name_plan(
            "光学实验 第02讲.mp4",
            "光学实验",
            "fallback.mp4",
            kind="视频",
            options={"mode": "caption"},
        )
        self.assertIn("第02讲", p["file_name"])

    def test_template_extracts_only_real_fields(self):
        p = name_plan(
            "Ab83Kd91X.mp4",
            "城市漫游 第2季 第03集 1080P",
            "fallback.mp4",
            kind="视频",
            options={"mode": "template", "template": "{title} {episode}"},
        )
        self.assertIn("S02E03", p["file_name"])
        self.assertNotIn("1080P", p["file_name"])
        self.assertEqual(fields("没有季集的标题")["episode"], "")
        for language in (
            "今日の旅",
            "오늘의 여행",
            "The Last Journey",
            "Café de Paris",
        ):
            self.assertIn(
                language.split()[0],
                name_plan("123456789.mp4", language, "fallback.mp4", kind="视频")[
                    "file_name"
                ],
            )

    def test_missing_template_fields_keep_chapter_without_empty_separators(self):
        p = name_plan(
            "光学实验 第02讲.mp4",
            "光学实验 第02讲",
            "fallback.mp4",
            options={"mode": "template", "template": "{title} - {year} - {episode}"},
        )
        self.assertIn("第02讲", p["file_name"])
        self.assertNotIn("- -", p["file_name"])

    def test_source_prefix_rules_do_not_change_global_naming(self):
        result = name_plan(
            "本期推荐光学实验.mp4",
            "",
            "fallback.mp4",
            options={"prefixes": ["本期推荐"]},
        )
        self.assertEqual(result["file_name"], "光学实验.mp4")
        self.assertIn(
            "本期推荐",
            name_plan("本期推荐光学实验.mp4", "", "fallback.mp4")["file_name"],
        )
        with self.assertRaises(ValueError):
            profile({"template": "{unknown}"})
        for invalid in ([], ["bad"], True, "caption", 1):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                profile(invalid)

    def test_extension_paths_and_utf8_safety(self):
        p = name_plan(
            "1234.mp4",
            "标题.exe\nhttps://example.com @channel",
            "fallback.mp4",
            kind="视频",
            options={"mode": "caption"},
        )
        self.assertTrue(p["file_name"].endswith(".mp4"))
        p = name_plan("1234.mp4", "标题" * 500, "fallback.mp4", kind="视频")
        self.assertLessEqual(len(p["file_name"].encode()), 180)
        self.assertNotIn(
            "/", name_plan("../../escape.mp4", "", "fallback.mp4")["file_name"]
        )


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.settings = make_settings(self.root)
        self.db = TaskDB(self.root / "tasks.db")
        self.addCleanup(self.db.close)
        zone = patch.dict(os.environ, {"TZ": "UTC"})
        zone.start()
        self.addCleanup(zone.stop)
        self.admin = self.settings.allowed_user_id
        self.repo = Plans(self.db, self.admin)
        record = self.db.family_users(self.admin)
        self.db.change_family_user(
            self.admin,
            {"action": "add", "id": 2, "name": "家人", "revision": record["revision"]},
        )

    def plan(self, actor=None, mid=1, **kwargs):
        m = message(mid, chat=self.admin if actor is None else actor)
        item = rules.facts(m)
        naming = name_plan(
            item["original"],
            item["caption"],
            "fallback.mp4",
            kind="视频",
            options=kwargs.pop("options", None),
        )
        return self.repo.create(
            actor or self.admin,
            item,
            naming,
            target_base=self.settings.cd2_target,
            **kwargs,
        )[0]

    def source(self):
        s = self.repo.save_source(
            self.admin,
            account=42,
            chat=-1001,
            title="合成课程",
            cursor=100,
            config={"rules": {"groups": [{"types": ["视频"]}]}},
        )
        self.repo.change_source(self.admin, s["id"], s["revision"], enabled=True)
        return self.repo.source(self.admin, s["id"])

    def test_creating_plans_only_expires_owner_without_history_cleanup(self):
        own = self.plan(mid=1)
        other = self.plan(actor=2, mid=1)
        self.db._conn.execute("UPDATE transfer_plans SET expires=0")
        statements = []
        self.db._conn.set_trace_callback(statements.append)
        try:
            self.plan(mid=2)
        finally:
            self.db._conn.set_trace_callback(None)
        self.assertFalse(any(sql.lstrip().upper().startswith("DELETE") for sql in statements))
        self.assertEqual(self.db._conn.execute("SELECT status FROM transfer_plans WHERE id=?", (own["id"],)).fetchone()[0], "expired")
        self.assertEqual(self.db._conn.execute("SELECT status FROM transfer_plans WHERE id=?", (other["id"],)).fetchone()[0], "pending")
        # Live validation still rejects another owner's expired plan before maintenance.
        self.assertEqual(self.repo.pending(2), [])
        with self.assertRaises(ValueError):
            self.repo.submit(2, other["id"], other["revision"])
        with self.assertRaises(ValueError):
            self.repo.edit(2, other["id"], other["revision"], name="expired")
        self.assertEqual(self.db.counts(), {})

    def test_expired_pending_records_do_not_consume_admission_limit(self):
        first = self.plan()
        c = self.db._conn
        row = c.execute("SELECT * FROM transfer_plans WHERE id=?", (first["id"],)).fetchone()
        c.executemany(
            "INSERT INTO transfer_plans(owner,identity,chat,message,batch,payload,status,created,expires) "
            "VALUES(?,'bot',?,?,'',?,'pending',0,0)",
            ((self.admin, self.admin, mid, row["payload"]) for mid in range(2, 201)),
        )
        c.execute("UPDATE transfer_plans SET expires=0")
        new = self.plan(mid=201)
        self.assertEqual([p["id"] for p in self.repo.pending(self.admin)], [new["id"]])
        self.assertEqual(c.execute("SELECT COUNT(*) FROM transfer_plans WHERE status='expired'").fetchone()[0], 200)

    def test_large_maintenance_is_bounded_and_eventually_finishes(self):
        from tg2cloud.persistence.plans import MAINTENANCE_BATCH
        source = self.source()
        c = self.db._conn
        total = 10001
        c.execute("BEGIN IMMEDIATE")
        c.executemany(
            "INSERT INTO transfer_plans(id,owner,identity,chat,message,batch,payload,status,created,expires) "
            "VALUES(?,?,'bot',1,?,'','{}','ignored',0,0)",
            ((i, self.admin, i) for i in range(1, total + 1)),
        )
        c.executemany(
            "INSERT INTO listener_events(account,chat,message,source,result,plan,created) "
            "VALUES(42,-1001,?,?,'synthetic',?,0)",
            ((i, source["id"], i) for i in range(1, total + 1)),
        )
        c.execute("COMMIT")
        previous = total
        for _ in range(total // MAINTENANCE_BATCH + 2):
            with self.repo.transaction(self.admin, admin=True):
                backlog = self.repo.expire()
            events = c.execute("SELECT COUNT(*) FROM listener_events").fetchone()[0]
            plans = c.execute("SELECT COUNT(*) FROM transfer_plans").fetchone()[0]
            self.assertLessEqual(previous - events, MAINTENANCE_BATCH)
            self.assertGreater(previous - events, 0)
            self.assertEqual(events, plans)
            previous = events
            if not backlog:
                break
        self.assertEqual(previous, 0)
        self.assertEqual(c.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_maintenance_rollback_restores_all_tables(self):
        source = self.source()
        plan = self.plan()
        c = self.db._conn
        c.execute("UPDATE transfer_plans SET created=0,expires=0")
        c.execute("INSERT INTO listener_events(account,chat,message,source,result,plan,created) "
                  "VALUES(42,-1001,1,?,'synthetic',?,0)", (source["id"], plan["id"]))
        before = list(c.iterdump())
        with self.assertRaisesRegex(RuntimeError, "synthetic"), self.repo.transaction(self.admin, admin=True):
            self.repo.expire()
            raise RuntimeError("synthetic interruption")
        self.assertEqual(before, list(c.iterdump()))
        self.assertFalse(c.in_transaction)

    def test_batched_expiration_and_feedback_keep_retention_rules(self):
        from tg2cloud.persistence.plans import MAINTENANCE_BATCH
        c = self.db._conn
        c.executemany(
            "INSERT INTO transfer_plans(owner,identity,chat,message,batch,payload,status,created,expires) "
            "VALUES(?,'bot',1,?,'','{}','pending',0,0)",
            ((self.admin, i) for i in range(1, MAINTENANCE_BATCH + 2)),
        )
        c.executemany(
            "INSERT INTO naming_feedback(owner,plan,before_name,after_name,operation,created) "
            "VALUES(?,1,'before','after','synthetic',?)",
            ((self.admin, time.time()) for _ in range(2600)),
        )
        with self.repo.transaction(self.admin, admin=True):
            self.assertTrue(self.repo.expire())
        self.assertEqual(c.execute("SELECT COUNT(*) FROM transfer_plans WHERE status='pending'").fetchone()[0], 1)
        self.assertEqual(c.execute("SELECT COUNT(*) FROM naming_feedback").fetchone()[0], 2100)
        for _ in range(2):
            with self.repo.transaction(self.admin, admin=True):
                self.repo.expire()
        self.assertEqual(c.execute("SELECT COUNT(*) FROM transfer_plans").fetchone()[0], 0)
        self.assertEqual(c.execute("SELECT MIN(id),COUNT(*) FROM naming_feedback").fetchone()[:], (601, 2000))

    def test_new_maintenance_indexes_are_additive_and_recreated(self):
        c = self.db._conn
        expected = {"idx_listener_events_plan", "idx_plans_expiry", "idx_plans_retention"}
        task = self.db.create_task(chat_id=1, message_id=1, sender_id=self.admin,
                                   file_name="retained.mp4", file_size=100)[0]
        for name in expected:
            c.execute("DROP INDEX " + name)
        self.db.close()
        self.db = TaskDB(self.root / "tasks.db")
        self.addCleanup(self.db.close)
        self.assertEqual(self.db.get(task["id"])["file_name"], "retained.mp4")
        self.assertEqual(self.db._conn.execute("PRAGMA user_version").fetchone()[0], 3)
        names = {row[0] for row in self.db._conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
        self.assertLessEqual(expected, names)

    def test_full_maintenance_keeps_referenced_pending_and_recent_history(self):
        source = self.source()
        keep = self.plan(mid=1)
        remove = self.plan(mid=2)
        recent = self.plan(mid=3)
        old = time.time() - 40 * 86400
        c = self.db._conn
        c.execute("UPDATE transfer_plans SET created=?", (old,))
        c.execute("UPDATE transfer_plans SET status='ignored' WHERE id IN (?,?)", (remove["id"], recent["id"]))
        for mid, plan, created in ((1, keep["id"], old), (2, remove["id"], old), (3, recent["id"], time.time()), (4, None, old)):
            c.execute("INSERT INTO listener_events(account,chat,message,source,result,plan,created) VALUES(42,-1001,?,?,'synthetic',?,?)",
                      (mid, source["id"], plan, created))
        with self.repo.transaction(self.admin, admin=True):
            self.repo.expire()
        self.assertEqual([r[0] for r in c.execute("SELECT message FROM listener_events ORDER BY message")], [1, 3])
        self.assertEqual([r[0] for r in c.execute("SELECT id FROM transfer_plans ORDER BY id")], [keep["id"], recent["id"]])

    def test_migration_keeps_history_identity_and_unknown_schema_rejected(self):
        task = self.db.create_task(
            chat_id=1, message_id=1, sender_id=1, file_name="old.mp4", file_size=100
        )[0]
        self.assertEqual(task["read_identity"], "bot")
        self.assertEqual(self.db._conn.execute("PRAGMA user_version").fetchone()[0], 3)
        self.db.close()
        self.db = TaskDB(self.root / "tasks.db")
        self.addCleanup(self.db.close)
        self.assertEqual(self.db.get(task["id"])["file_name"], "old.mp4")
        self.db._conn.execute("PRAGMA user_version=999")
        with self.assertRaises(RuntimeError):
            TaskDB(self.root / "tasks.db")

    def test_duplicate_submit_concurrent_is_one_task_and_one_reservation(self):
        p = self.plan()
        with ThreadPoolExecutor(max_workers=4) as pool:
            tasks = list(
                pool.map(
                    lambda _: self.repo.submit(self.admin, p["id"], p["revision"]),
                    range(8),
                )
            )
        self.assertEqual(len({t[0]["id"] for t in tasks}), 1)
        self.assertEqual(sum(created for _, created in tasks), 1)
        self.assertEqual(
            self.db._conn.execute("SELECT count(*) FROM quota_ledger").fetchone()[0], 1
        )

    def test_crash_between_task_and_plan_rolls_back_both(self):
        p = self.plan()
        self.db._conn.execute(
            "CREATE TRIGGER fail_plan BEFORE UPDATE ON transfer_plans WHEN NEW.status='submitted' BEGIN SELECT RAISE(ABORT,'synthetic interruption'); END"
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.repo.submit(self.admin, p["id"], p["revision"])
        self.assertEqual(self.db.counts(), {})
        self.assertEqual(self.repo.get(self.admin, p["id"])["status"], "pending")
        self.assertEqual(
            self.db._conn.execute("SELECT count(*) FROM quota_ledger").fetchone()[0], 0
        )

    def test_pending_restarts_and_does_not_reserve(self):
        p = self.plan()
        self.assertEqual(self.db.counts(), {})
        self.db.close()
        self.db = TaskDB(self.root / "tasks.db")
        self.addCleanup(self.db.close)
        repo = Plans(self.db, self.admin)
        self.assertEqual(repo.pending(self.admin)[0]["id"], p["id"])
        self.assertEqual(repo.pending(2), [])
        with self.assertRaises(PermissionError):
            repo.get(2, p["id"])

    def test_listener_rules_and_tasks_cannot_be_used_by_member(self):
        s = self.source()
        p = self.plan(mid=2)
        for fn in (
            lambda: self.repo.sources(2),
            lambda: self.repo.source(2, s["id"]),
            lambda: self.repo.save_source(
                2, account=42, chat=-2, title="x", cursor=1, config={}
            ),
            lambda: self.repo.create(
                2,
                rules.facts(message()),
                name_plan("", "title", "f.mp4"),
                identity="listener:42",
                source=s["id"],
            ),
        ):
            with self.assertRaises(PermissionError):
                fn()
        with self.assertRaises(PermissionError):
            self.repo.edit(2, p["id"], p["revision"], name="mine")

    def test_revoked_family_cannot_continue_old_plans(self):
        p = self.plan(actor=2)
        record = self.db.family_users(self.admin)
        self.db.change_family_user(
            self.admin, {"action": "disable", "id": 2, "revision": record["revision"]}
        )
        with self.assertRaises(PermissionError):
            self.repo.submit(2, p["id"], p["revision"])

    def test_directories_are_allowlisted_paths_and_snapshots_frozen(self):
        for path in ("../escape", "/absolute", "a/%2e%2e", "a\\b", "a//b"):
            with self.assertRaises(ValueError):
                self.repo.set_directory(self.admin, "课程", path, [2])
        self.repo.set_directory(self.admin, "课程", "课程/光学", [2])
        p = self.plan(actor=2, directory_alias="课程")
        task, _ = self.repo.submit(2, p["id"], p["revision"])
        self.repo.set_directory(self.admin, "课程", "课程/数学", [])
        self.assertEqual(self.db.get(task["id"])["target_directory"], "课程/光学")
        with self.assertRaises(ValueError):
            self.repo.directory(2, "课程")

    def test_feedback_is_local_until_explicit_save_and_history_retained(self):
        s = self.source()
        item = rules.facts(message())
        item["original"] = "本期推荐光学实验.mp4"
        naming = name_plan(item["original"], "", "fallback.mp4")
        p = self.repo.create(
            self.admin, item, naming, identity="listener:42", source=s["id"]
        )[0]
        self.repo.edit(self.admin, p["id"], p["revision"], name="光学实验")
        self.assertEqual(
            self.repo.source(self.admin, s["id"])["config"]["profile"]["prefixes"], []
        )
        feedback = self.repo.feedback(self.admin)[0]
        self.repo.apply_feedback(self.admin, feedback["id"], s["revision"])
        self.assertIn(
            "本期推荐",
            self.repo.source(self.admin, s["id"])["config"]["profile"]["prefixes"],
        )
        self.assertTrue(self.repo.source_history(self.admin, s["id"]))

    def test_expired_old_revision_and_submitted_cannot_rename(self):
        p = self.plan()
        changed = self.repo.edit(self.admin, p["id"], p["revision"], name="new")
        with self.assertRaises(ValueError):
            self.repo.submit(self.admin, p["id"], p["revision"])
        self.repo.submit(self.admin, changed["id"], changed["revision"])
        with self.assertRaises(ValueError):
            self.repo.edit(self.admin, changed["id"], changed["revision"], name="bad")
        q = self.plan(mid=2)
        self.db._conn.execute(
            "UPDATE transfer_plans SET expires=0 WHERE id=?", (q["id"],)
        )
        with self.assertRaises(ValueError):
            self.repo.submit(self.admin, q["id"], q["revision"])

    def test_source_cas_delete_keeps_task_and_rejects_old_buttons(self):
        s = self.source()
        with self.assertRaises(ValueError):
            self.repo.change_source(
                self.admin, s["id"], s["revision"] - 1, enabled=False
            )
        self.repo.change_source(self.admin, s["id"], s["revision"], delete=True)
        self.assertEqual(self.repo.sources(self.admin), [])
        self.assertTrue(self.repo.source(self.admin, s["id"])["deleted"])

    def test_classification_and_rule_snapshot_frozen_before_approval(self):
        from tg2cloud.persistence import features

        prefs = self.db.feature_settings()
        features.change(self.db._conn, prefs["revision"], {"classification": "type"})
        p = self.plan()
        features.change(
            self.db._conn,
            self.db.feature_settings()["revision"],
            {"classification": "year"},
        )
        task, _ = self.repo.submit(self.admin, p["id"], p["revision"])
        self.assertEqual(task["target_directory"], "视频")
        self.assertEqual(task["created_at"], p["payload"]["created_at"])

    def test_v2_database_and_personal_session_remain_intact(self):
        self.db.create_task(
            chat_id=88,
            message_id=88,
            sender_id=self.admin,
            file_name="历史任务.mp4",
            file_size=10,
        )
        self.db._conn.execute("PRAGMA user_version=2")
        self.db._conn.execute("ALTER TABLE tasks DROP COLUMN read_identity")
        self.db._conn.execute("ALTER TABLE tasks DROP COLUMN source_id")
        self.db.close()
        self.db = TaskDB(self.root / "tasks.db")
        self.addCleanup(self.db.close)
        self.assertEqual(self.db.get(1)["file_name"], "历史任务.mp4")
        self.assertEqual(self.db.get(1)["read_identity"], "bot")
        self.assertEqual(self.db._conn.execute("PRAGMA user_version").fetchone()[0], 3)


class ListenerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.settings = make_settings(Path(self.temp.name))
        self.admin = self.settings.allowed_user_id
        self.db = TaskDB(self.settings.data_dir / "tg115.db")
        self.addCleanup(self.db.close)
        self.owner = make_service(self.settings, self.db)
        self.owner._notify = AsyncMock()
        self.owner._stop = asyncio.Event()
        self.listener = Listener(self.owner)
        self.owner.listener = self.listener
        self.listener.client = NS(get_messages=AsyncMock(), download_media=AsyncMock())
        self.repo = self.listener.plans
        account.write_state(self.db, account=42, enabled=True, status="synthetic")
        s = self.repo.save_source(
            self.admin,
            account=42,
            chat=-1001,
            title="合成来源",
            cursor=0,
            config={"rules": {"groups": [{"types": ["视频"]}]}},
        )
        self.repo.change_source(self.admin, s["id"], s["revision"], enabled=True)
        self.source = self.repo.source(self.admin, s["id"])
        self.verify = patch(
            "tg2cloud.listening.service.verified_chat",
            new=AsyncMock(return_value=NS(title="合成来源")),
        )
        self.checked = self.verify.start()
        self.addCleanup(self.verify.stop)

    async def test_album_rule_preview_matches_poll_without_writing(self):
        self.repo.change_source(
            self.admin, self.source["id"], self.source["revision"],
            config={"rules": {"groups": [{"types": ["视频"], "keywords": ["光学"]}]},
                    "profile": {"mode": "caption"}},
        )
        source = self.repo.source(self.admin, self.source["id"])
        video = message(1, caption="", group=91)
        cover = message(2, original="cover.jpg", caption="光学实验演示", kind="photo", group=91)
        messages = [video, cover]
        self.listener.client.get_messages.return_value = list(reversed(messages))
        before = self.db._conn.total_changes
        result = await self.listener.test(self.admin, source["id"])
        self.assertEqual(self.db._conn.total_changes, before)
        preview = next(row for row in result if row[0] == video.id)
        self.assertTrue(preview[1])
        self.assertIn("光学实验", preview[3]["file_name"])

        async def history(*_, **__):
            for item in messages:
                yield item

        self.listener.client.iter_messages = history
        await self.listener.poll(source)
        plans = self.repo.pending(self.admin)
        self.assertEqual(len(plans), 1)
        self.assertEqual(plans[0]["payload"]["file_name"], preview[3]["file_name"])

    async def test_preview_keeps_own_episode_and_does_not_borrow_other_group(self):
        messages = [
            message(1, original="光学实验 第01讲.mp4", caption="", group=91),
            message(2, caption="光学实验 第02讲", group=91),
            message(3, caption="", group=92),
        ]
        self.listener.client.get_messages.return_value = messages
        result = await self.listener.test(self.admin, self.source["id"])
        self.assertIn("第01讲", result[0][3]["file_name"])
        self.assertNotIn("第02讲", result[0][3]["file_name"])
        self.assertNotIn("光学实验", result[2][3]["file_name"])

    async def test_first_notice_after_fresh_boot_keeps_later_throttle(self):
        from tg2cloud.listening import service as module
        clock = [10.0]
        with patch.object(module, "time", NS(time=time.time, monotonic=lambda: clock[0])):
            await self.listener.receive(self.source, message(1))
            self.assertEqual(self.owner._notify.await_count, 1)
            clock[0] = 11.0
            await self.listener.receive(self.source, message(2))
            self.assertEqual(self.owner._notify.await_count, 1)
            clock[0] = 71.0
            await self.listener.receive(self.source, message(3))
            self.assertEqual(self.owner._notify.await_count, 2)

    async def test_poll_does_not_overwrite_pause_while_notifying(self):
        saved = {}

        async def pause(_):
            current = self.repo.source(self.admin, self.source["id"])
            self.repo.change_source(self.admin, current["id"], current["revision"], enabled=False)
            saved.update(self.repo.source(self.admin, current["id"]))

        async def history(*_, **__):
            yield message()

        self.owner._notify.side_effect = pause
        self.listener.client.iter_messages = history
        await self.listener.poll(self.source)
        self.assertEqual(self.repo.source(self.admin, self.source["id"]), saved)
        self.assertEqual(len(self.repo.pending(self.admin)), 1)

    async def test_poll_discards_page_fetched_before_configuration_change(self):
        saved = {}

        async def history(*_, **__):
            current = self.repo.source(self.admin, self.source["id"])
            self.repo.change_source(self.admin, current["id"], current["revision"],
                                    config=current["config"] | {"confirmation": False})
            saved.update(self.repo.source(self.admin, current["id"]))
            yield message()

        self.listener.client.iter_messages = history
        await self.listener.poll(self.source)
        self.assertEqual(self.repo.source(self.admin, self.source["id"]), saved)
        self.assertEqual(self.repo.pending(self.admin), [])
        self.assertEqual(self.db.counts(), {})

    async def test_download_rechecks_account_and_client_after_metadata(self):
        await self.listener.receive(self.source, message())
        plan = self.repo.pending(self.admin)[0]
        task, _ = self.repo.submit(self.admin, plan["id"], plan["revision"])
        original_client = self.listener.client
        original_client.get_messages.return_value = message()
        for change in ("account", "client"):
            with self.subTest(change=change):
                account.write_state(self.db, account=42, enabled=True)
                self.listener.client = original_client
                reader = CheckedSource(self.listener, task)
                msg = await reader.get_messages(-1001, ids=1)
                if change == "account":
                    account.write_state(self.db, account=43, enabled=True)
                else:
                    self.listener.client = NS(download_media=AsyncMock())
                with self.assertRaises(ListenerReadError):
                    await reader.download_media(msg, file="unused")
                self.listener.client.download_media.assert_not_awaited()
        original_client.download_media.assert_not_awaited()

    async def test_failed_metadata_recheck_revokes_previous_message(self):
        await self.listener.receive(self.source, message())
        plan = self.repo.pending(self.admin)[0]
        task, _ = self.repo.submit(self.admin, plan["id"], plan["revision"])
        reader = CheckedSource(self.listener, task)
        self.listener.client.get_messages.return_value = message()
        old_message = await reader.get_messages(-1001, ids=1)
        self.listener.client.get_messages.return_value = None
        with self.assertRaises(ListenerReadError):
            await reader.get_messages(-1001, ids=1)
        with self.assertRaises(ListenerReadError):
            await reader.download_media(old_message, file="unused")
        self.listener.client.download_media.assert_not_awaited()

    async def test_stale_poll_failure_does_not_pause_reconfigured_source(self):
        current = self.repo.source(self.admin, self.source["id"])
        self.repo.change_source(self.admin, current["id"], current["revision"],
                                config=current["config"] | {"confirmation": False})
        saved = self.repo.source(self.admin, current["id"])
        await self.listener.source_failure(self.source, ListenerReadError("synthetic refusal"))
        self.assertEqual(self.repo.source(self.admin, current["id"]), saved)

    async def test_metadata_request_cannot_cross_account_change(self):
        await self.listener.receive(self.source, message())
        plan = self.repo.pending(self.admin)[0]
        task, _ = self.repo.submit(self.admin, plan["id"], plan["revision"])
        client = self.listener.client

        async def change_account(*_args, **_kwargs):
            account.write_state(self.db, account=43, enabled=True)
            return message()

        client.get_messages.side_effect = change_account
        reader = CheckedSource(self.listener, task)
        with self.assertRaises(ListenerReadError):
            await reader.get_messages(-1001, ids=1)
        self.assertIsNone(reader.message)
        client.download_media.assert_not_awaited()

    async def test_configuration_changed_during_permission_check_is_retried(self):
        async def change(*_args):
            current = self.repo.source(self.admin, self.source["id"])
            self.repo.change_source(self.admin, current["id"], current["revision"],
                                    config=current["config"] | {"confirmation": False})

        self.listener._verified_until.clear()
        with patch("tg2cloud.listening.service.verified_chat", side_effect=change):
            await self.listener.receive(self.source, message())
        self.assertEqual(self.repo.pending(self.admin), [])
        self.assertEqual(self.db.counts(), {})
        self.assertEqual(self.repo.source(self.admin, self.source["id"])["cursor"], 0)
        await self.listener.receive(self.source, message())
        self.assertEqual(len(self.repo.pending(self.admin)), 0)
        self.assertEqual(sum(self.db.counts().values()), 1)

    async def test_repeat_receive_is_one_plan_and_no_early_download(self):
        m = message()
        await self.listener.receive(self.source, m)
        await self.listener.receive(self.source, m)
        self.assertEqual(len(self.repo.pending(self.admin)), 1)
        self.assertEqual(self.db.counts(), {})
        self.listener.client.download_media.assert_not_awaited()

    async def test_test_rules_has_no_side_effects_and_reports_duplicates(self):
        self.listener.client.get_messages.return_value = [message()]
        before = self.db._conn.total_changes
        result = await self.listener.test(self.admin, self.source["id"])
        self.assertTrue(result[0][1])
        self.assertEqual(before, self.db._conn.total_changes)
        await self.listener.receive(self.source, message())
        result = await self.listener.test(self.admin, self.source["id"])
        self.assertIn("重复", result[0][2])
        self.listener.client.download_media.assert_not_awaited()

    async def test_protection_flag_is_accepted_but_nonattachment_still_skips(self):
        await self.listener.receive(self.source, message(protected=True))
        m = message(2)
        m.media = None
        m.file = None
        await self.listener.receive(self.source, m)
        self.assertEqual(len(self.repo.pending(self.admin)), 1)
        self.assertEqual(self.repo.pending(self.admin)[0]["message"], 1)
        self.assertEqual(
            self.db._conn.execute("SELECT count(*) FROM listener_events").fetchone()[0],
            2,
        )

    async def test_cursor_progress_does_not_use_live_max_and_replays_dedupe(self):
        await self.listener.receive(self.source, message(3))

        async def history(*_, **__):
            for mid in (1, 2, 3):
                yield message(mid)

        self.listener.client.iter_messages = history
        await self.listener.poll(self.source)
        self.assertEqual(len(self.repo.pending(self.admin)), 3)
        self.assertEqual(self.repo.source(self.admin, self.source["id"])["cursor"], 3)
        await self.listener.poll(self.source)
        self.assertEqual(len(self.repo.pending(self.admin)), 3)

    async def test_receiving_failure_never_advances_cursor(self):
        async def history(*_, **__):
            yield message()

        self.listener.client.iter_messages = history
        with (
            patch.object(
                self.listener,
                "receive",
                new=AsyncMock(side_effect=OSError("synthetic persistence failure")),
            ),
            self.assertRaises(OSError),
        ):
            await self.listener.poll(self.source)
        self.assertEqual(self.repo.source(self.admin, self.source["id"])["cursor"], 0)

    async def test_paused_source_stops_receive_but_keeps_existing_plan(self):
        await self.listener.receive(self.source, message())
        self.repo.change_source(
            self.admin, self.source["id"], self.source["revision"], enabled=False
        )
        await self.listener.receive(self.source, message(2))
        self.assertEqual(len(self.repo.pending(self.admin)), 1)

    async def test_download_routes_by_identity_and_never_member_or_bot_fallback(self):
        await self.listener.receive(self.source, message())
        p = self.repo.pending(self.admin)[0]
        task, _ = self.repo.submit(self.admin, p["id"], p["revision"])
        self.listener.client.get_messages.return_value = message()
        reader = task_source(self.owner, task)
        self.assertIsInstance(reader, CheckedSource)
        msg = await reader.get_messages(-1001, ids=1)
        await reader.download_media(
            msg, file="synthetic", progress_callback=lambda *_: None
        )
        self.listener.client.download_media.assert_awaited_once()
        with self.assertRaises(ListenerReadError):
            task_source(self.owner, task | {"sender_id": 2})
        account.write_state(self.db, enabled=False)
        with self.assertRaises(ListenerReadError):
            await reader.get_messages(-1001, ids=1)

    async def test_empty_attachment_rechecks_once_and_can_recover_same_identity(self):
        await self.listener.receive(self.source, message())
        plan = self.repo.pending(self.admin)[0]
        task, _ = self.repo.submit(self.admin, plan["id"], plan["revision"])
        media = message()
        self.listener.client.get_messages.side_effect = [None, media]
        reader = CheckedSource(self.listener, task)
        with patch("tg2cloud.listening.service.asyncio.sleep", new=AsyncMock()) as sleep:
            self.assertIs(await reader.get_messages(-1001, ids=1), media)
        sleep.assert_awaited_once_with(1)
        self.assertEqual(self.listener.client.get_messages.await_count, 2)
        self.assertEqual(self.db.get(task["id"])["state"], "queued")

    async def test_empty_attachment_recheck_stops_after_identity_is_revoked(self):
        await self.listener.receive(self.source, message())
        plan = self.repo.pending(self.admin)[0]
        task, _ = self.repo.submit(self.admin, plan["id"], plan["revision"])
        self.listener.client.get_messages.return_value = None
        async def revoke(_):
            account.write_state(self.db, enabled=False)
        reader = CheckedSource(self.listener, task)
        with patch("tg2cloud.listening.service.asyncio.sleep", side_effect=revoke), self.assertRaises(ListenerReadError):
            await reader.get_messages(-1001, ids=1)
        self.listener.client.get_messages.assert_awaited_once()
        self.listener.client.download_media.assert_not_awaited()
        self.assertIsNone(reader.message)

    async def test_changed_or_deleted_message_blocks_download(self):
        await self.listener.receive(self.source, message())
        p = self.repo.pending(self.admin)[0]
        task, _ = self.repo.submit(self.admin, p["id"], p["revision"])
        reader = CheckedSource(self.listener, task)
        no_media = message()
        no_media.media = None
        for msg in (None, message(2), no_media):
            self.listener.client.get_messages.return_value = msg
            with self.assertRaises(ListenerReadError):
                await reader.get_messages(-1001, ids=1)
        self.listener.client.download_media.assert_not_awaited()

    async def test_missing_session_connect_isolated_from_manual(self):
        self.listener.client = None
        with (
            patch(
                "tg2cloud.listening.account.session_lock",
                side_effect=ValueError("synthetic invalid session"),
            ),
            self.assertRaises(ValueError),
        ):
            await self.listener.connect()
        bot = NS(get_messages=AsyncMock())
        self.owner._source = bot
        self.assertIs(task_source(self.owner, {"read_identity": "bot"}), bot)

    async def test_rule_changes_only_new_plan_snapshots(self):
        await self.listener.receive(self.source, message())
        p = self.repo.pending(self.admin)[0]
        self.repo.change_source(
            self.admin,
            self.source["id"],
            self.source["revision"],
            config={"rules": {"groups": [{"types": ["图片"]}]}},
        )
        self.assertEqual(self.repo.get(self.admin, p["id"])["payload"], p["payload"])

        self.repo.edit(self.admin, p["id"], p["revision"], name="人工修正")
        self.assertEqual(
            self.repo.feedback(self.admin)[0]["rule_revision"],
            p["payload"]["source_revision"],
        )

    async def test_member_forged_callbacks_and_cross_user_tokens_are_denied(self):
        record = self.db.family_users(self.admin)
        self.db.change_family_user(
            self.admin,
            {"action": "add", "id": 2, "name": "家人", "revision": record["revision"]},
        )
        button = planning.token_button(
            self.owner, self.admin, "管理", ("source", self.source["id"])
        )
        callback = NS(
            sender_id=2,
            chat_id=2,
            data=callback_data(button),
            answer=AsyncMock(),
            edit=AsyncMock(),
        )
        with user_scope(2):
            self.assertTrue(await planning.callback(self.owner, callback))
        callback.answer.assert_awaited_once()
        self.assertTrue(callback.answer.call_args.kwargs["alert"])
        self.assertEqual(
            self.repo.source(self.admin, self.source["id"])["revision"],
            self.source["revision"],
        )
        home = self.owner._home_buttons(admin=False)
        self.assertNotIn(
            b"menu:listen", [callback_data(b) for row in home for b in row]
        )

    async def test_interactions_never_swallow_private_media(self):
        m = message(chat=self.admin)
        m.sender_id = self.admin
        e = event(self.admin, m)
        with user_scope(self.admin):
            await planning.ask(self.owner, e, ("add",), "来源")
        await self.owner._on_message(e)
        self.assertEqual(sum(self.db.counts().values()), 1)
        self.assertIn(self.admin, planning.interactions(self.owner))
        self.assertEqual(len(self.repo.sources(self.admin)), 1)

    async def test_default_manual_delivery_and_confirmation_are_separate(self):
        m = message(chat=self.admin)
        m.sender_id = self.admin
        e = event(self.admin, m)
        await self.owner._on_message(e)
        self.assertEqual(len(self.repo.pending(self.admin)), 0)
        self.repo.preferences(self.admin, {"confirmation": True})
        m = message(2, chat=self.admin)
        m.sender_id = self.admin
        e = event(self.admin, m)
        await self.owner._on_message(e)
        e.reply.assert_not_awaited()
        self.assertEqual(self.owner.reactions.pending[(self.admin, 2)], "🤔")
        plans = self.repo.pending(self.admin)
        self.assertEqual(len(plans), 1)
        self.assertEqual(sum(self.db.counts().values()), 1)
        await planning.submit(self.owner, self.admin, plans[0]["id"], plans[0]["revision"])
        self.assertEqual(self.owner.reactions.pending[(self.admin, 2)], "👀")
        self.assertEqual(sum(self.db.counts().values()), 2)

    async def test_token_single_use_and_expired_interaction_do_not_write(self):
        b = planning.token_button(
            self.owner, self.admin, "设置", ("confirmation", True)
        )
        e = NS(data=callback_data(b), answer=AsyncMock(), edit=AsyncMock())
        with user_scope(self.admin):
            await planning.callback(self.owner, e)
            await planning.callback(self.owner, e)
        self.assertTrue(e.answer.call_args.kwargs["alert"])
        planning.interactions(self.owner)[self.admin] = (time.monotonic() - 1, ("add",))
        with user_scope(self.admin):
            self.assertFalse(
                await planning.text(self.owner, event(self.admin), "@example")
            )

    async def test_listener_download_uses_existing_backend_pipeline(self):
        for backend in ("clouddrive2", "openlist"):
            for stream in (False, True):
                with self.subTest(backend=backend, stream=stream):
                    mid = (
                        100
                        + (10 if backend == "openlist" else 0)
                        + (1 if stream else 0)
                    )
                    m = message(mid)
                    await self.listener.receive(self.source, m)
                    p = next(
                        p for p in self.repo.pending(self.admin) if p["message"] == mid
                    )
                    task, _ = self.repo.submit(self.admin, p["id"], p["revision"])
                    self.db.update(
                        task["id"],
                        state="reserved",
                        transfer_mode="stream" if stream else "local",
                    )
                    self.owner.settings = replace(
                        self.settings,
                        storage_backend=backend,
                        destination_label="OpenList"
                        if backend == "openlist"
                        else "CloudDrive2",
                    )
                    self.owner.rclone = FakeRclone()
                    self.listener.client.get_messages.return_value = m

                    async def download(_message, *, file, progress_callback):
                        if isinstance(file, str):
                            Path(file).write_bytes(b"x" * 100)
                        else:
                            await file.write(b"x" * 100)
                        progress_callback(100, 100)
                        return file

                    self.listener.client.download_media = download
                    await self.owner._download_one(task["id"])
                    if not stream:
                        await self.owner._upload_one(task["id"])
                    final = self.db.get(task["id"])
                    self.assertEqual(final["state"], "completed")
                    self.assertEqual(final["read_identity"], "listener:42")
                    self.assertEqual(final["verification_method"], "size")
                    self.assertEqual(len(self.owner.rclone.files), 1)

    async def test_group_member_episode_not_borrowed_and_filter_is_per_file(self):
        a = message(1, original="光学实验 第01讲.mp4", caption="", group=99)
        b = message(
            2, original="光学实验 第02讲.mp4", caption="光学实验 第02讲", group=99
        )
        c = message(3, original="合成封面.jpg", caption="", group=99, kind="photo")

        async def history(*_, **__):
            for m in (a, b, c):
                yield m

        self.listener.client.iter_messages = history
        await self.listener.poll(self.source)
        plans = self.repo.pending(self.admin)
        self.assertEqual(len(plans), 2)
        self.assertIn("第01讲", plans[0]["payload"]["file_name"])
        self.assertIn("第02讲", plans[1]["payload"]["file_name"])
        self.assertEqual(
            self.db._conn.execute(
                "SELECT result FROM listener_events WHERE message=3"
            ).fetchone()[0],
            "类型、名称或关键词不符",
        )

    async def test_global_disable_releases_client_and_loop_exits_without_manual_restart(
        self,
    ):
        personal = NS(disconnect=AsyncMock())
        self.listener.client = personal
        account.write_state(self.db, enabled=False)
        await self.listener.connect()
        personal.disconnect.assert_awaited_once()
        self.assertIsNone(self.listener.client)

    async def test_chat_protection_and_membership_check_use_real_types(self):
        self.verify.stop()
        from telethon.tl import types

        c = NS(get_entity=AsyncMock(), get_permissions=AsyncMock())
        for e in (
            types.User(id=1),
            types.Channel(
                id=1,
                title="fixture",
                photo=types.ChatPhotoEmpty(),
                date=datetime.now(timezone.utc),
                left=True,
            ),
        ):
            c.get_entity.return_value = e
            with self.assertRaises(ListenerReadError):
                await verified_chat(c, "@fixture")
        c.get_entity.return_value = types.Channel(
            id=1,
            title="fixture",
            photo=types.ChatPhotoEmpty(),
            date=datetime.now(timezone.utc),
            left=False,
            noforwards=False,
        )
        from telethon.tl.custom.participantpermissions import ParticipantPermissions

        c.get_permissions.return_value = ParticipantPermissions(
            types.ChannelParticipant(user_id=42, date=datetime.now(timezone.utc)),
            chat=False,
        )
        for flag in (False, True, None):
            c.get_entity.return_value.noforwards = flag
            await verified_chat(c, "@fixture")
        self.assertEqual(c.get_permissions.await_count, 3)
        for left, denied in ((True, False), (False, True), (False, None)):
            member = types.ChannelParticipantBanned(
                peer=types.PeerUser(42),
                kicked_by=1,
                date=datetime.now(timezone.utc),
                banned_rights=types.ChatBannedRights(
                    until_date=None, view_messages=denied
                ),
                left=left,
            )
            c.get_permissions.return_value = ParticipantPermissions(member, chat=False)
            with self.assertRaises(ListenerReadError):
                await verified_chat(c, "@fixture")
        # A joined reader restricted from sending is supported; restriction != unreadability.
        member = types.ChannelParticipantBanned(
            peer=types.PeerUser(42),
            kicked_by=1,
            date=datetime.now(timezone.utc),
            banned_rights=types.ChatBannedRights(
                until_date=None, view_messages=False, send_messages=True
            ),
            left=False,
        )
        c.get_permissions.return_value = ParticipantPermissions(member, chat=False)
        await verified_chat(c, "@fixture")
        c.get_permissions.return_value = None
        with self.assertRaises(ListenerReadError):
            await verified_chat(c, "@fixture")

    async def test_manual_priority_and_backpressure(self):
        s = self.source
        cfg = s["config"] | {"confirmation": False}
        self.repo.change_source(self.admin, s["id"], s["revision"], config=cfg)
        await self.listener.receive(s, message(1))
        self.db.create_task(
            chat_id=self.admin,
            message_id=2,
            sender_id=self.admin,
            file_name="manual.mp4",
            file_size=1,
        )
        batch = next(self.owner._queued_batches(("queued",)))
        self.assertEqual(batch[0]["read_identity"], "bot")
        with (
            patch.object(self.db, "count_states", return_value=100),
            self.assertRaises(ValueError),
        ):
            await self.listener.receive(s, message(3))
        self.assertFalse(
            self.db._conn.execute(
                "SELECT 1 FROM listener_events WHERE message=3"
            ).fetchone()
        )

    async def test_queue_limit_counts_active_states_and_ignores_history(self):
        from tg2cloud.listening.service import ReceiveLimited

        c = self.db._conn
        c.executemany(
            "INSERT INTO tasks(chat_id,message_id,sender_id,file_name,file_size,state,created_at,updated_at) "
            "VALUES(777,?,?,'synthetic.bin',1,'completed',0,0)",
            ((i, self.admin) for i in range(2000)),
        )
        active = []
        for i in range(100):
            task, _ = self.db.create_task(chat_id=778, message_id=i, sender_id=self.admin,
                                         file_name="synthetic.bin", file_size=1)
            self.db.update(task["id"], state=("queued", "reserved", "downloading", "streaming")[i % 4])
            active.append(task)
        with patch.object(self.db, "counts", side_effect=AssertionError("must not scan historical counts")):
            with self.assertRaises(ReceiveLimited):
                await self.listener.receive(self.source, message(999))
            self.assertEqual(self.repo.pending(self.admin), [])
            self.assertEqual(c.execute("SELECT COUNT(*) FROM listener_events").fetchone()[0], 0)
            self.db.update(active[0]["id"], state="completed")
            await self.listener.receive(self.source, message(999))
        self.assertEqual(len(self.repo.pending(self.admin)), 1)

    def another_source(self, chat=-1002):
        source = self.repo.save_source(self.admin, account=42, chat=chat, title="另一个合成来源", cursor=0,
                                      config=self.source["config"])
        self.repo.change_source(self.admin, source["id"], source["revision"], enabled=True)
        return self.repo.source(self.admin, source["id"])

    async def test_maintenance_runs_once_per_minute_and_after_restart(self):
        from tg2cloud.listening import service as module

        with patch.object(module, "time", NS(monotonic=lambda: 100)), patch.object(self.repo, "expire", wraps=self.repo.expire) as cleanup:
            for _ in range(12):
                self.listener._maintain_if_due()
            self.assertEqual(cleanup.call_count, 1)
            self.assertEqual(self.listener._next_maintenance_at, 160)
        with patch.object(module, "time", NS(monotonic=lambda: 160)), patch.object(self.repo, "expire", wraps=self.repo.expire) as cleanup:
            self.listener._maintain_if_due()
            self.assertEqual(cleanup.call_count, 1)
        replacement = Listener(self.owner)
        with patch.object(replacement.plans, "expire", wraps=replacement.plans.expire) as cleanup:
            replacement._maintain_if_due()
            self.assertEqual(cleanup.call_count, 1)

    async def test_maintenance_failure_rolls_back_without_revoking_account(self):
        from tg2cloud.listening import service as module

        await self.listener.receive(self.source, message())
        plan = self.repo.pending(self.admin)[0]
        self.db._conn.execute("UPDATE transfer_plans SET expires=0 WHERE id=?", (plan["id"],))
        before = account.state(self.db)
        def fail():
            self.repo.expire_pending()
            raise sqlite3.OperationalError("PRIVATE_DETAIL")
        with patch.object(module, "time", NS(monotonic=lambda: 100)), patch.object(self.repo, "expire", side_effect=fail) as cleanup:
            self.listener._maintain_if_due()
            self.listener._maintain_if_due()
            self.assertEqual(cleanup.call_count, 1)
        self.assertFalse(self.db._conn.in_transaction)
        self.assertEqual(self.db._conn.execute("SELECT status FROM transfer_plans WHERE id=?", (plan["id"],)).fetchone()[0], "pending")
        self.assertEqual(account.state(self.db), before)
        self.assertNotIn("PRIVATE_DETAIL", str(self.owner.log.warning.call_args))
        with patch.object(module, "time", NS(monotonic=lambda: 160)):
            self.listener._maintain_if_due()
        self.assertEqual(self.db._conn.execute("SELECT status FROM transfer_plans WHERE id=?", (plan["id"],)).fetchone()[0], "expired")

    async def test_poll_budget_rotates_sources_without_starving_later_ids(self):
        second, third = self.another_source(), self.another_source(-1003)
        with patch.object(self.listener, "poll", new=AsyncMock()) as poll, patch("tg2cloud.listening.service.POLL_ROUND_BUDGET", 0):
            for _ in range(4):
                await self.listener._poll_sources()
        self.assertEqual([call.args[0]["id"] for call in poll.await_args_list],
                         [self.source["id"], second["id"], third["id"], self.source["id"]])

    async def test_slow_source_is_cancelled_before_next_source_runs(self):
        second = self.another_source()
        cancelled = asyncio.Event()
        seen = []
        async def poll(source):
            seen.append(source["id"])
            if source["id"] == self.source["id"]:
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()
            else:
                self.assertTrue(cancelled.is_set())
        with patch.object(self.listener, "poll", new=poll), patch("tg2cloud.listening.service.SOURCE_POLL_TIMEOUT", 0.02):
            await self.listener._poll_sources()
        self.assertEqual(seen, [self.source["id"], second["id"]])
        current = self.repo.source(self.admin, self.source["id"])
        self.assertTrue(current["enabled"])
        self.assertEqual(current["cursor"], 0)
        self.assertIn("超时", current["status"])
        self.assertGreater(current["next_retry"], time.time())
        with patch.object(self.listener, "poll", new=AsyncMock()) as poll:
            await self.listener._poll_sources()
        self.assertEqual([call.args[0]["id"] for call in poll.await_args_list], [second["id"]])

    async def test_poll_timeout_after_registration_replays_without_duplicate_plan(self):
        async def history(*_, **__):
            yield message()
        async def stalled_notice(_):
            await asyncio.Event().wait()
        self.listener.client.iter_messages = history
        self.owner._notify.side_effect = stalled_notice
        with patch("tg2cloud.listening.service.SOURCE_POLL_TIMEOUT", 0.02):
            await self.listener._poll_sources()
        plans = self.repo.pending(self.admin)
        self.assertEqual(len(plans), 1)
        self.assertEqual(self.repo.source(self.admin, self.source["id"])["cursor"], 0)
        # Persisted inbox survives replacement of the worker (as on restart).
        self.db._conn.execute("UPDATE listener_sources SET next_retry=0")
        replacement = Listener(self.owner)
        replacement.client = self.listener.client
        self.owner._notify.side_effect = None
        await replacement._poll_sources()
        self.assertEqual([p["id"] for p in self.repo.pending(self.admin)], [plans[0]["id"]])
        self.assertEqual(self.repo.source(self.admin, self.source["id"])["cursor"], 1)

    async def test_account_cooldown_stops_remaining_source_requests(self):
        from telethon.errors import FloodWaitError

        self.another_source()
        with patch.object(self.listener, "poll", new=AsyncMock(side_effect=FloodWaitError(request=None, capture=45))) as poll:
            await self.listener._poll_sources()
            await self.listener._poll_sources()
        self.assertEqual(poll.await_count, 1)
        self.assertTrue(account.state(self.db)["enabled"])
        self.assertGreater(account.state(self.db)["cooldown_until"], time.time())

    async def test_poll_rechecks_source_and_account_changes_between_requests(self):
        second = self.another_source()
        seen = []
        async def pause_next(source):
            seen.append(source["id"])
            self.repo.change_source(self.admin, second["id"], second["revision"], enabled=False)
        with patch.object(self.listener, "poll", new=pause_next):
            await self.listener._poll_sources()
        self.assertEqual(seen, [self.source["id"]])
        async def disable(_):
            account.write_state(self.db, enabled=False)
        second = self.repo.source(self.admin, second["id"])
        self.repo.change_source(self.admin, second["id"], second["revision"], enabled=True)
        self.listener._poll_after = 0
        with patch.object(self.listener, "poll", new=AsyncMock(side_effect=disable)) as poll:
            await self.listener._poll_sources()
        self.assertEqual(poll.await_count, 1)

    async def test_revoked_authorization_stops_round_without_polling_other_sources(self):
        from telethon.errors import SessionRevokedError

        self.another_source()
        self.listener.client.disconnect = AsyncMock()
        with patch.object(self.listener, "poll", new=AsyncMock(side_effect=SessionRevokedError(request=None))) as poll:
            await self.listener._poll_sources()
        self.assertEqual(poll.await_count, 1)
        self.assertFalse(account.state(self.db)["enabled"])
        self.assertIsNone(self.listener.client)

    async def test_old_request_failure_cannot_revoke_replacement_account(self):
        from telethon.errors import SessionRevokedError

        async def replaced(_):
            account.write_state(self.db, account=43, enabled=True)
            raise SessionRevokedError(request=None)
        with patch.object(self.listener, "poll", new=replaced), patch.object(self.listener, "source_failure", new=AsyncMock()) as failure:
            await self.listener._poll_sources()
            failure.assert_not_awaited()
        self.assertEqual(account.state(self.db)["account"], 43)
        self.assertTrue(account.state(self.db)["enabled"])

    async def test_external_cancellation_joins_poll_and_does_not_record_failure(self):
        entered, finished = asyncio.Event(), asyncio.Event()
        async def poll(_):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                finished.set()
        with patch.object(self.listener, "poll", new=poll), patch.object(self.listener, "source_failure", new=AsyncMock()) as failure:
            worker = asyncio.create_task(self.listener._poll_sources())
            await entered.wait()
            worker.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await worker
            self.assertTrue(finished.is_set())
            failure.assert_not_awaited()
        self.assertEqual(self.repo.source(self.admin, self.source["id"])["cursor"], 0)

    async def test_connection_backoff_recovers_without_revoking_authorization(self):
        from tg2cloud.listening import service as module
        now = [1000.0]
        delays = []
        calls = 0

        async def connect():
            nonlocal calls
            calls += 1
            if calls <= 8:
                raise module.ListenerConnectionError("PRIVATE_DETAIL")
            account.write_state(self.db, status="正常监听", cooldown_until=0)
            return True

        async def sleep(_):
            value = account.state(self.db)
            if value.get("cooldown_until", 0) > now[0]:
                delays.append(value["cooldown_until"] - now[0])
                self.assertTrue(value["enabled"])
                self.assertNotIn("PRIVATE_DETAIL", value["status"])
                now[0] = value["cooldown_until"]

        async def polled():
            self.owner._stop.set()

        with (
            patch.object(module, "time", NS(time=lambda: now[0], monotonic=lambda: now[0])),
            patch.object(self.listener, "connect", side_effect=connect),
            patch.object(self.listener, "close", new=AsyncMock()),
            patch.object(self.listener, "_poll_sources", side_effect=polled),
            patch.object(module.asyncio, "sleep", side_effect=sleep),
        ):
            await self.listener.run()
        self.assertEqual(delays, [5, 10, 20, 40, 80, 160, 300, 300])
        self.assertEqual(calls, 9)
        self.assertEqual(self.listener._connect_failures, 0)
        self.assertTrue(account.state(self.db)["enabled"])
        self.owner._notify.assert_not_awaited()

    async def test_failed_connection_does_not_overwrite_changed_account(self):
        from tg2cloud.listening.service import ListenerConnectionError
        for enabled, identity in ((False, 42), (True, 43)):
            self.owner._stop.clear()
            account.write_state(self.db, enabled=True, account=42)
            async def connect(enabled=enabled, identity=identity):
                account.write_state(self.db, enabled=enabled, account=identity, status="new state")
                self.owner._stop.set()
                raise ListenerConnectionError("PRIVATE_DETAIL")
            with patch.object(self.listener, "connect", side_effect=connect), patch.object(self.listener, "close", new=AsyncMock()):
                await self.listener.run()
            current = account.state(self.db)
            self.assertEqual((current["enabled"], current["account"], current["status"]), (enabled, identity, "new state"))

    async def test_connection_auth_and_local_errors_still_disable(self):
        from telethon.errors import AuthKeyUnregisteredError
        for exc in (AuthKeyUnregisteredError(request=None), PermissionError("PRIVATE_DETAIL"),
                    ValueError("PRIVATE_DETAIL"), ListenerReadError("invalid account")):
            self.owner._stop.clear()
            account.write_state(self.db, enabled=True)
            async def halt(_):
                self.owner._stop.set()
            with (
                patch.object(self.listener, "connect", new=AsyncMock(side_effect=exc)),
                patch.object(self.listener, "close", new=AsyncMock()),
                patch("tg2cloud.listening.service.asyncio.sleep", side_effect=halt),
            ):
                await self.listener.run()
            self.assertFalse(account.state(self.db)["enabled"])
            self.assertNotIn("PRIVATE_DETAIL", str(account.state(self.db)))

    async def test_disconnected_client_is_replaced_and_healthy_client_reused(self):
        from contextlib import contextmanager
        path = self.settings.data_dir / "synthetic-reconnect"
        path.with_suffix(".session").touch()
        released = []
        @contextmanager
        def lock(_):
            try:
                yield path
            finally:
                released.append(True)
        stale = NS(is_connected=lambda: False, disconnect=AsyncMock())
        client = NS(is_connected=lambda: True, connect=AsyncMock(),
                    get_me=AsyncMock(return_value=NS(id=42, bot=False)), disconnect=AsyncMock())
        self.listener.client = stale
        with patch.object(account, "session_lock", lock), patch.object(account, "client", return_value=client) as factory:
            self.assertTrue(await self.listener.connect())
            self.assertTrue(await self.listener.connect())
            factory.assert_called_once()
        stale.disconnect.assert_awaited_once()
        client.connect.assert_awaited_once()
        self.assertIs(self.listener.client, client)
        self.assertTrue(account.state(self.db)["enabled"])
        await self.listener.close()
        self.assertEqual(released, [True])

    async def test_real_telethon_retry_exhaustion_preserves_server_error(self):
        from telethon.errors import ServerError

        from tg2cloud.listening.service import (
            ListenerConnectionError,
            connected_identity,
        )
        client = account.client(self.settings, self.settings.data_dir / "offline-test-session")
        self.addCleanup(client.session.close)
        self.assertTrue(client._raise_last_call_error)
        async def failed_request(*_args, **_kwargs):
            raise ServerError(request=None, message="synthetic", code=500)
        # Exercise actual get_me/_call with an offline sender, including retry
        # exhaustion; no Telegram connection or real Session is used.
        sender = NS(send=AsyncMock(side_effect=failed_request))
        with (
            patch.object(client, "connect", new=AsyncMock()),
            patch.object(client, "_sender", sender),
            patch("telethon.client.users.asyncio.sleep", new=AsyncMock()),
            self.assertRaises(ListenerConnectionError),
        ):
            await connected_identity(client)
        self.assertEqual(sender.send.await_count, 3)

    async def test_connection_network_boundary_and_timeout(self):
        from telethon.errors import FloodWaitError, ServerError

        from tg2cloud.listening import service as module
        client = NS(connect=AsyncMock(), get_me=AsyncMock())
        for exc in (OSError("PRIVATE_DETAIL"), ServerError(request=None, message="PRIVATE_DETAIL", code=500)):
            client.get_me.side_effect = exc
            with self.assertRaises(module.ListenerConnectionError):
                await module.connected_identity(client)
        client.get_me.side_effect = FloodWaitError(request=None, capture=45)
        with self.assertRaises(FloodWaitError):
            await module.connected_identity(client)
        client.get_me.side_effect = PermissionError("PRIVATE_DETAIL")
        with self.assertRaises(PermissionError):
            await module.connected_identity(client)
        finished = asyncio.Event()
        async def stalled():
            try:
                await asyncio.Event().wait()
            finally:
                finished.set()
        client.get_me.side_effect = stalled
        with patch.object(module, "CONNECT_TIMEOUT", 0.01), self.assertRaises(module.ListenerConnectionError):
            await module.connected_identity(client)
        self.assertTrue(finished.is_set())
        client.get_me.side_effect = None
        client.get_me.return_value = None
        self.assertIsNone(await module.connected_identity(client))

    async def test_connection_success_rechecks_identity_after_await(self):
        from contextlib import contextmanager
        path = self.settings.data_dir / "synthetic-personal"
        path.with_suffix(".session").touch()
        released = []
        @contextmanager
        def lock(_):
            try:
                yield path
            finally:
                released.append(True)
        client = NS(connect=AsyncMock(), get_me=AsyncMock(), disconnect=AsyncMock())
        async def changed():
            account.write_state(self.db, enabled=False, status="disabled by user")
            return NS(id=42, bot=False)
        client.get_me.side_effect = changed
        self.listener.client = None
        with patch.object(account, "session_lock", lock), patch.object(account, "client", return_value=client):
            self.assertFalse(await self.listener.connect())
        self.assertEqual(released, [True])
        self.assertFalse(account.state(self.db)["enabled"])
        self.assertIsNone(self.listener.client)
        client.disconnect.assert_awaited_once()

    async def test_connection_cooldown_does_not_attempt_early_reconnect(self):
        account.write_state(self.db, cooldown_until=time.time() + 3600, status="Telegram 限流冷却")
        async def halt(_):
            self.owner._stop.set()
        with (
            patch.object(self.listener, "connect", new=AsyncMock()) as connect,
            patch.object(self.listener, "close", new=AsyncMock()),
            patch("tg2cloud.listening.service.asyncio.sleep", side_effect=halt),
        ):
            await self.listener.run()
        connect.assert_not_awaited()
        self.assertEqual(account.state(self.db)["status"], "Telegram 限流冷却")
        self.assertTrue(account.state(self.db)["enabled"])

    async def test_cancelled_connect_releases_client_and_session_without_revoking(self):
        from contextlib import contextmanager
        path = self.settings.data_dir / "synthetic-cancelled"
        path.with_suffix(".session").touch()
        released = []
        @contextmanager
        def lock(_):
            try:
                yield path
            finally:
                released.append(True)
        entered, finished = asyncio.Event(), asyncio.Event()
        async def stalled():
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                finished.set()
        client = NS(connect=AsyncMock(side_effect=stalled), disconnect=AsyncMock())
        self.listener.client = None
        with patch.object(account, "session_lock", lock), patch.object(account, "client", return_value=client):
            task = asyncio.create_task(self.listener.run())
            await entered.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertTrue(finished.is_set())
        self.assertEqual(released, [True])
        self.assertIsNone(self.listener.client)
        self.assertIsNone(self.listener._session)
        client.disconnect.assert_awaited_once()
        self.assertTrue(account.state(self.db)["enabled"])

    async def test_account_conditional_write_rejects_stale_state(self):
        old = account.state(self.db)
        account.write_state(self.db, enabled=False)
        self.assertIsNone(account.write_state(self.db, expected=old, enabled=True, status="stale"))
        self.assertFalse(account.state(self.db)["enabled"])
        self.assertFalse(self.db._conn.in_transaction)

    async def test_maintenance_backlog_yields_until_next_round(self):
        from tg2cloud.listening import service as module
        with patch.object(module, "time", NS(monotonic=lambda: 100)), patch.object(self.repo, "expire", return_value=True) as cleanup:
            self.listener._maintain_if_due()
            self.listener._maintain_if_due()
            self.assertEqual(cleanup.call_count, 1)
            self.assertEqual(self.listener._next_maintenance_at, 105)

    async def test_empty_listener_loop_keeps_enabled_account(self):
        self.repo.change_source(
            self.admin, self.source["id"], self.source["revision"], enabled=False
        )

        async def halt(_):
            self.owner._stop.set()

        self.listener.client = NS(disconnect=AsyncMock())
        with (
            patch.object(self.listener, "connect", new=AsyncMock(return_value=True)),
            patch(
                "tg2cloud.listening.service.asyncio.sleep",
                new=AsyncMock(side_effect=halt),
            ),
        ):
            await self.listener.run()
        self.assertTrue(account.state(self.db)["enabled"])

    async def test_flood_wait_persists_cooldown_and_does_not_advance(self):
        from telethon.errors import FloodWaitError

        before = time.time()
        result = await self.listener.source_failure(
            self.source, FloodWaitError(request=None, capture=45)
        )
        self.assertFalse(result)
        self.assertGreaterEqual(account.state(self.db)["cooldown_until"], before + 45)
        self.assertEqual(self.repo.source(self.admin, self.source["id"])["cursor"], 0)

    async def test_source_failure_categories_do_not_store_raw_error(self):
        await self.listener.source_failure(self.source, OSError("PRIVATE_RAW_MESSAGE"))
        row = self.repo.source(self.admin, self.source["id"])
        self.assertIn("网络", row["status"])
        self.assertNotIn("PRIVATE_RAW_MESSAGE", row["status"])
        self.assertTrue(row["enabled"])
        await self.listener.source_failure(
            self.source, ListenerReadError("private source")
        )
        self.assertFalse(self.repo.source(self.admin, self.source["id"])["enabled"])
        self.assertTrue(account.state(self.db)["enabled"])

    async def test_enable_callback_sets_current_cursor_and_keeps_private_scope(self):
        self.listener.client.get_messages.return_value = [message(50)]
        self.repo.change_source(
            self.admin, self.source["id"], self.source["revision"], enabled=False
        )
        source = self.repo.source(self.admin, self.source["id"])
        button = planning.token_button(
            self.owner,
            self.admin,
            "启用",
            ("source-enable", source["id"], source["revision"], True),
        )
        callback = NS(data=callback_data(button), answer=AsyncMock(), edit=AsyncMock())
        with user_scope(self.admin):
            await planning.callback(self.owner, callback)
        row = self.repo.source(self.admin, self.source["id"])
        self.assertTrue(row["enabled"])
        self.assertEqual(row["cursor"], 50)
        self.assertGreater(row["polled_at"], 0)

    async def test_long_offline_gap_is_visible_even_without_new_messages(self):
        self.db._conn.execute(
            "UPDATE listener_sources SET polled_at=?", (time.time() - 7 * 3600,)
        )

        async def history(*_, **__):
            if False:
                yield None

        self.listener.client.iter_messages = history
        await self.listener.poll(self.repo.source(self.admin, self.source["id"]))
        row = self.repo.source(self.admin, self.source["id"])
        self.assertTrue(row["gap"])
        self.assertIn("缺口", row["status"])

    async def test_declared_batch_name_and_directory_edits(self):
        self.repo.set_directory(self.admin, "课程", "课程/光学", [])
        a = message(
            11, chat=self.admin, original="旧主题 第01讲.mp4", caption="", group=77
        )
        b = message(
            12, chat=self.admin, original="旧主题 第02讲.mp4", caption="", group=77
        )
        naming1 = name_plan(a.file.name, "", "fallback.mp4")
        naming2 = name_plan(b.file.name, "", "fallback.mp4")
        p1 = self.repo.create(self.admin, rules.facts(a), naming1, batch="test-course")[
            0
        ]
        p2 = self.repo.create(self.admin, rules.facts(b), naming2, batch="test-course")[
            0
        ]
        with user_scope(self.admin):
            planning.interactions(self.owner)[self.admin] = (
                time.monotonic() + 300,
                (
                    "batch-name",
                    [(p1["id"], p1["revision"]), (p2["id"], p2["revision"])],
                ),
            )
            await planning.text(self.owner, event(self.admin), "新主题")
        self.assertIn(
            "第01讲", self.repo.get(self.admin, p1["id"])["payload"]["file_name"]
        )
        self.assertIn(
            "第02讲", self.repo.get(self.admin, p2["id"])["payload"]["file_name"]
        )

    async def test_batch_edit_rolls_back_all_members_when_one_revision_is_stale(self):
        m1, m2 = message(31, chat=self.admin), message(32, chat=self.admin)
        p1 = self.repo.create(
            self.admin,
            rules.facts(m1),
            name_plan("第一讲.mp4", "", "fallback.mp4"),
            batch="rollback-course",
        )[0]
        p2 = self.repo.create(
            self.admin,
            rules.facts(m2),
            name_plan("第二讲.mp4", "", "fallback.mp4"),
            batch="rollback-course",
        )[0]
        self.repo.edit(self.admin, p2["id"], p2["revision"], name="已经单独修改")
        with user_scope(self.admin):
            planning.interactions(self.owner)[self.admin] = (
                time.monotonic() + 300,
                (
                    "batch-name",
                    [(p1["id"], p1["revision"]), (p2["id"], p2["revision"])],
                ),
            )
            await planning.text(self.owner, event(self.admin), "新共同主题")
        self.assertEqual(
            self.repo.get(self.admin, p1["id"])["payload"]["file_name"],
            p1["payload"]["file_name"],
        )

    async def test_download_flood_wait_is_persisted_without_short_retry(self):
        from telethon.errors import FloodWaitError

        await self.listener.receive(self.source, message())
        plan = self.repo.pending(self.admin)[0]
        task, _ = self.repo.submit(self.admin, plan["id"], plan["revision"])
        self.listener.client.get_messages.return_value = message()
        reader = CheckedSource(self.listener, task)
        m = await reader.get_messages(-1001, ids=1)
        self.listener.client.download_media.side_effect = FloodWaitError(
            request=None, capture=90
        )
        with self.assertRaises(ListenerReadError):
            await reader.download_media(
                m, file="synthetic", progress_callback=lambda *_: None
            )
        self.assertGreater(account.state(self.db)["cooldown_until"], time.time() + 85)
        self.listener.client.download_media.assert_awaited_once()

    async def test_cooldown_queue_waits_and_manual_work_continues_then_resumes(self):
        await self.listener.receive(self.source, message())
        p = self.repo.pending(self.admin)[0]
        watched, _ = self.repo.submit(self.admin, p["id"], p["revision"])
        manual, _ = self.db.create_task(
            chat_id=self.admin,
            message_id=22,
            sender_id=self.admin,
            file_name="manual.mp4",
            file_size=1,
        )
        self.owner.destination_healthy = True
        self.owner._sample_fresh = lambda: True
        self.owner._destination_ready = lambda: True
        self.owner.snapshot = NS(filesystems=[], disk_free=100 * 1024**3, memory_available=4 * 1024**3)
        self.owner.download_window = NS(value=2)
        self.owner.upload_window = NS(value=2)
        self.owner._download_one = AsyncMock()
        account.write_state(self.db, cooldown_until=time.time() + 60)
        with patch(
            "tg2cloud.transfer.scheduler.shutil.disk_usage",
            return_value=NS(free=100 * 1024**3),
        ):
            await self.owner._start_downloads()
            await asyncio.gather(*list(self.owner.download_tasks.values()))
            self.assertEqual(self.db.get(watched["id"])["state"], "queued")
            self.assertIn("冷却", self.db.get(watched["id"])["wait_reason"])
            self.owner._download_one.assert_awaited_once_with(manual["id"])
            before_wait = self.db.get(watched["id"])
            changes = self.db._conn.total_changes
            await self.owner._start_downloads()
            self.assertEqual(self.db._conn.total_changes, changes)
            self.assertEqual(self.db.get(watched["id"]), before_wait)
            account.write_state(self.db, cooldown_until=0)
            await self.owner._start_downloads()
            await asyncio.gather(*list(self.owner.download_tasks.values()))
        self.assertEqual(self.db.get(watched["id"])["state"], "reserved")
        self.assertEqual(self.owner._download_one.await_count, 2)

    async def test_manual_compatible_custom_rules_apply_for_owner_and_family(self):
        record = self.db.family_users(self.admin)
        self.db.change_family_user(
            self.admin,
            {"action": "add", "id": 2, "name": "家人", "revision": record["revision"]},
        )
        for actor in (self.admin, 2):
            for confirmation in (False, True):
                mid = 501 + int(confirmation)
                with self.subTest(actor=actor, confirmation=confirmation):
                    self.repo.preferences(
                        actor,
                        {
                            "confirmation": confirmation,
                            "profile": {"prefixes": ["本期推荐"]},
                        },
                    )
                    m = message(
                        mid, chat=actor, original="本期推荐光学实验.mp4", caption=""
                    )
                    m.sender_id = actor
                    await self.owner._on_message(event(actor, m))
                    if confirmation:
                        plan = self.repo.pending(actor)[0]
                        self.assertEqual(plan["payload"]["file_name"], "光学实验.mp4")
                        self.assertEqual(plan["identity"], "bot")
                    else:
                        task = self.db.list_recent(sender_id=actor)[0]
                        self.assertEqual(task["file_name"], "光学实验.mp4")
                        self.assertEqual(task["read_identity"], "bot")
        self.listener.client.get_messages.assert_not_awaited()

    async def test_stop_during_permission_request_does_not_admit_attachment(self):
        async def stop(*_args):
            account.write_state(self.db, enabled=False, status="已停用")
        self.listener._verified_until.clear()
        with patch("tg2cloud.listening.service.verified_chat", side_effect=stop):
            await self.listener.receive(self.source, message(100))
        self.assertFalse(self.repo.pending(self.admin))
        self.assertEqual(self.db._conn.execute("SELECT count(*) FROM listener_events").fetchone()[0], 0)

    async def test_explicit_new_start_does_not_admit_older_inflight_updates(self):
        self.repo.change_source(
            self.admin,
            self.source["id"],
            self.source["revision"],
            enabled=True,
            cursor=100,
        )
        await self.listener.receive(self.source, message(2))
        self.assertFalse(self.repo.pending(self.admin))
        await self.listener.receive(self.source, message(101))
        self.assertEqual(self.repo.pending(self.admin)[0]["message"], 101)
        self.assertEqual(self.repo.source(self.admin, self.source["id"])["cursor"], 100)


    async def test_premium_wait_is_classified_at_metadata_boundary_and_preserves_longer_cooldown(self):
        from telethon.errors import FloodPremiumWaitError

        from tg2cloud.listening.service import source_error
        await self.listener.receive(self.source, message())
        plan = self.repo.pending(self.admin)[0]
        task, _ = self.repo.submit(self.admin, plan["id"], plan["revision"])
        error = FloodPremiumWaitError(request=None, capture=4)
        self.assertIn("限流", source_error(error))
        account.write_state(self.db, cooldown_until=time.time() + 90)
        deadline = account.state(self.db)["cooldown_until"]
        self.listener.client.get_messages.side_effect = error
        with self.assertRaises(ListenerReadError):
            await CheckedSource(self.listener, task).get_messages(-1001, ids=1)
        self.assertEqual(account.state(self.db)["cooldown_until"], deadline)
        self.assertTrue(account.state(self.db)["enabled"])
        self.assertTrue(self.repo.source(self.admin, self.source["id"])["enabled"])

    async def test_premium_wait_fallback_stops_once_for_local_stream_and_both_gateways(self):
        from telethon.errors import FloodPremiumWaitError
        for backend in ("clouddrive2", "openlist"):
            for mode in ("local", "stream"):
                with self.subTest(backend=backend, mode=mode):
                    self.owner.settings = replace(self.settings, storage_backend=backend)
                    mid = 400 + (10 if backend == "openlist" else 0) + (mode == "stream")
                    m = message(mid)
                    await self.listener.receive(self.source, m)
                    plan = self.repo.pending(self.admin)[0]
                    task, _ = self.repo.submit(self.admin, plan["id"], plan["revision"])
                    self.db.update(task["id"], state="reserved", transfer_mode=mode)
                    self.listener.client.get_messages.return_value = m
                    self.listener.client.download_media = AsyncMock(side_effect=FloodPremiumWaitError(request=None, capture=90))
                    self.owner.rclone = FakeRclone()
                    self.owner._notify = AsyncMock()
                    await self.owner._download_one(task["id"])
                    saved = self.db.get(task["id"])
                    self.assertEqual(saved["state"], "download_failed")
                    self.assertEqual(saved["failure_kind"], "rate_limited")
                    self.assertIn("Telegram 限流", saved["error"])
                    self.listener.client.download_media.assert_awaited_once()
                    self.assertGreater(account.state(self.db)["cooldown_until"], time.time() + 85)
                    self.assertEqual(saved["download_retries"], 0)
                    self.assertTrue(self.repo.source(self.admin, self.source["id"])["enabled"])

    async def test_short_premium_wait_keeps_one_transfer_for_both_gateways_and_modes(self):
        from telethon import TelegramClient
        from telethon.errors import FloodPremiumWaitError
        from test_listening_transport import client, request
        self.owner.download_window = NS(value=8)
        for backend in ("clouddrive2", "openlist"):
            for mode in ("local", "stream"):
                with self.subTest(backend=backend, mode=mode):
                    self.owner.settings = replace(self.settings, storage_backend=backend)
                    mid = 500 + (10 if backend == "openlist" else 0) + (mode == "stream")
                    m = message(mid)
                    await self.listener.receive(self.source, m)
                    plan = self.repo.pending(self.admin)[0]
                    task, _ = self.repo.submit(self.admin, plan["id"], plan["revision"])
                    self.db.update(task["id"], state="reserved", transfer_mode=mode)
                    self.listener.client.get_messages.return_value = m
                    sdk = client()
                    async def download(msg, *, file, progress_callback, sdk=sdk):
                        if isinstance(file, str):
                            Path(file).write_bytes(b"x" * 50)
                        else:
                            await file.write(b"x" * 50)
                        await sdk._call(sdk._sender, request())
                        if isinstance(file, str):
                            Path(file).write_bytes(Path(file).read_bytes() + b"x" * 50)
                        else:
                            await file.write(b"x" * 50)
                        progress_callback(100, 100)
                        return file
                    self.listener.client.download_media = AsyncMock(side_effect=download)
                    self.owner.rclone = FakeRclone()
                    parent = AsyncMock(side_effect=[FloodPremiumWaitError(request=None, capture=3), object()])
                    with patch.object(TelegramClient, "_call", parent), patch(
                            "tg2cloud.listening.transport.asyncio.sleep", new=AsyncMock()), patch(
                            "tg2cloud.listening.transport.monotonic", return_value=0):
                        await self.owner._download_one(task["id"])
                        if mode == "local":
                            await self.owner._upload_one(task["id"])
                    saved = self.db.get(task["id"])
                    self.assertEqual(saved["state"], "completed")
                    self.assertEqual(saved["download_retries"], 0)
                    self.assertIsNone(saved["error"])
                    self.assertEqual(saved["verification_method"], "size")
                    self.listener.client.download_media.assert_awaited_once()
                    self.assertEqual(self.owner.rclone.files[saved["remote_path"]], b"x" * 100)
                    self.assertEqual(self.listener.download_backoff.cap, 4)
                    self.assertEqual(self.owner.download_window.value, 8)

    async def test_expired_rate_limit_status_returns_to_normal_but_future_wait_stays(self):
        self.listener.client.is_connected = lambda: True
        for deadline, expected in ((time.time() - 1, "正常监听"),
                                   (time.time() + 90, "Telegram 下载限速冷却")):
            account.write_state(self.db, status="Telegram 下载限速冷却", cooldown_until=deadline)
            await self.listener.connect()
            self.assertEqual(account.state(self.db)["status"], expected)
            self.assertEqual(account.state(self.db)["cooldown_until"], 0 if expected == "正常监听" else deadline)

    async def test_old_premium_rpc_cannot_change_replacement_account(self):
        from telethon.errors import FloodPremiumWaitError
        await self.listener.receive(self.source, message())
        plan = self.repo.pending(self.admin)[0]
        task, _ = self.repo.submit(self.admin, plan["id"], plan["revision"])
        self.listener.client.get_messages.return_value = message()
        reader = CheckedSource(self.listener, task)
        m = await reader.get_messages(-1001, ids=1)
        async def stale(*args, **kwargs):
            account.write_state(self.db, account=999, status="replacement")
            raise FloodPremiumWaitError(request=None, capture=90)
        self.listener.client.download_media.side_effect = stale
        with self.assertRaises(ListenerReadError):
            await reader.download_media(m, file="unused")
        saved = account.state(self.db)
        self.assertEqual(saved["account"], 999)
        self.assertEqual(saved["status"], "replacement")
        self.assertEqual(saved.get("cooldown_until", 0), 0)


    async def test_delayed_errors_cannot_revoke_or_pause_replacement_account_or_client(self):
        from telethon.errors import (
            AuthKeyUnregisteredError,
            ChannelPrivateError,
            SessionRevokedError,
        )
        mid = 700
        for phase in ("permissions", "metadata", "download"):
            for change in ("account", "client", "both"):
                for error_type in (AuthKeyUnregisteredError, SessionRevokedError, ChannelPrivateError):
                    with self.subTest(phase=phase, change=change, error=error_type.__name__):
                        mid += 1
                        account.write_state(self.db, account=42, enabled=True, status="synthetic")
                        original = NS(get_messages=AsyncMock(return_value=message(mid)),
                                      download_media=AsyncMock(), disconnect=AsyncMock())
                        self.listener.client = original
                        await self.listener.receive(self.source, message(mid))
                        plan = self.repo.pending(self.admin)[0]
                        task, _ = self.repo.submit(self.admin, plan["id"], plan["revision"])
                        reader = CheckedSource(self.listener, task)
                        replacement = NS(disconnect=AsyncMock())
                        observed = {}
                        async def late_error(*args, change=change, error_type=error_type,
                                             replacement=replacement, observed=observed, **kwargs):
                            if change in {"account", "both"}:
                                account.write_state(self.db, account=999, enabled=True, status="replacement")
                            if change in {"client", "both"}:
                                self.listener.client = replacement
                            observed["account"] = account.state(self.db)
                            observed["client"] = self.listener.client
                            observed["source"] = self.repo.source(self.admin, self.source["id"])
                            raise error_type(request=None)
                        if phase == "download":
                            media = await reader.get_messages(-1001, ids=mid)
                            original.download_media.side_effect = late_error
                            with self.assertRaises(ListenerReadError):
                                await reader.download_media(media, file="unused")
                        elif phase == "metadata":
                            original.get_messages.side_effect = late_error
                            with self.assertRaises(ListenerReadError):
                                await reader.get_messages(-1001, ids=mid)
                        else:
                            with patch("tg2cloud.listening.service.verified_chat", side_effect=late_error), self.assertRaises(ListenerReadError):
                                await reader.get_messages(-1001, ids=mid)
                        self.assertEqual(account.state(self.db), observed["account"])
                        self.assertIs(self.listener.client, observed["client"])
                        self.assertEqual(self.repo.source(self.admin, self.source["id"]), observed["source"])
                        original.disconnect.assert_not_awaited()
                        replacement.disconnect.assert_not_awaited()

    async def test_current_authorization_and_permission_denials_still_stop_safely(self):
        from telethon.errors import AuthKeyUnregisteredError, ChannelPrivateError
        for mid, error_type in enumerate((AuthKeyUnregisteredError, ChannelPrivateError), 800):
            with self.subTest(error=error_type.__name__):
                account.write_state(self.db, account=42, enabled=True, status="synthetic")
                original = NS(get_messages=AsyncMock(side_effect=error_type(request=None)),
                              disconnect=AsyncMock())
                self.listener.client = original
                await self.listener.receive(self.source, message(mid))
                plan = self.repo.pending(self.admin)[0]
                task, _ = self.repo.submit(self.admin, plan["id"], plan["revision"])
                with self.assertRaises(ListenerReadError):
                    await CheckedSource(self.listener, task).get_messages(-1001, ids=mid)
                if error_type is AuthKeyUnregisteredError:
                    self.assertFalse(account.state(self.db)["enabled"])
                    self.assertIsNone(self.listener.client)
                    original.disconnect.assert_awaited_once()
                else:
                    self.assertFalse(self.repo.source(self.admin, self.source["id"])["enabled"])
                    self.assertTrue(account.state(self.db)["enabled"])
                    original.disconnect.assert_not_awaited()

    async def test_temporary_metadata_failures_retry_for_both_gateways_and_modes(self):
        from telethon.errors import ServerError, TimedOutError
        async def download(msg, *, file, progress_callback):
            if isinstance(file, str):
                Path(file).write_bytes(b"x" * 100)
            else:
                await file.write(b"x" * 100)
            progress_callback(100, 100)
            return file
        mid = 900
        for backend in ("clouddrive2", "openlist"):
            for mode in ("local", "stream"):
                for phase in ("permissions", "metadata"):
                    for error in (ServerError(request=None, message="PRIVATE_DETAIL", code=500),
                                  TimedOutError(request=None, message="TIMEOUT"), ConnectionError("PRIVATE_DETAIL")):
                        with self.subTest(backend=backend, mode=mode, phase=phase, error=type(error).__name__):
                            mid += 1
                            self.owner.settings = replace(self.settings, storage_backend=backend)
                            m = message(mid)
                            await self.listener.receive(self.source, m)
                            plan = self.repo.pending(self.admin)[0]
                            task, _ = self.repo.submit(self.admin, plan["id"], plan["revision"])
                            self.db.update(task["id"], state="reserved", transfer_mode=mode)
                            self.owner.rclone = FakeRclone()
                            self.listener.client.get_messages = AsyncMock(return_value=m)
                            self.listener.client.download_media = AsyncMock(side_effect=download)
                            if phase == "metadata":
                                self.listener.client.get_messages.side_effect = [error, m]
                            verify = AsyncMock(side_effect=[error, NS()] if phase == "permissions" else [NS(), NS()])
                            with patch("tg2cloud.listening.service.verified_chat", verify), patch(
                                    "tg2cloud.transfer.download.asyncio.sleep", new=AsyncMock()):
                                await self.owner._download_one(task["id"])
                                if mode == "local":
                                    await self.owner._upload_one(task["id"])
                            saved = self.db.get(task["id"])
                            self.assertEqual(saved["state"], "completed")
                            self.assertEqual(saved["download_retries"], 1)
                            self.assertIsNone(saved["failure_kind"])
                            self.assertIsNone(saved["error"])
                            self.assertEqual(verify.await_count, 2)
                            self.listener.client.download_media.assert_awaited_once()
                            self.assertTrue(account.state(self.db)["enabled"])
                            self.assertTrue(self.repo.source(self.admin, self.source["id"])["enabled"])
                            self.assertIsNone(self.listener.download_backoff.cap)

    async def test_persistent_metadata_error_keeps_safe_source_cause_with_bounded_retries(self):
        from telethon.errors import ServerError
        for mid, mode in enumerate(("local", "stream"), 1000):
            with self.subTest(mode=mode):
                await self.listener.receive(self.source, message(mid))
                plan = self.repo.pending(self.admin)[0]
                task, _ = self.repo.submit(self.admin, plan["id"], plan["revision"])
                self.db.update(task["id"], state="reserved", transfer_mode=mode)
                self.owner.rclone = FakeRclone()
                self.listener.client.get_messages = AsyncMock(side_effect=ServerError(
                    request=None, message="PRIVATE_TOKEN https://private.invalid/secret", code=500))
                self.listener.client.download_media = AsyncMock()
                with patch("tg2cloud.transfer.download.asyncio.sleep", new=AsyncMock()):
                    await self.owner._download_one(task["id"])
                saved = self.db.get(task["id"])
                self.assertEqual(saved["state"], "download_failed")
                self.assertEqual(saved["failure_kind"], "server")
                self.assertIn("Telegram 服务端暂时异常", saved["error"])
                self.assertNotIn("PRIVATE_TOKEN", saved["error"])
                self.assertNotIn("private.invalid", str(self.owner.log.warning.call_args_list))
                self.assertEqual(self.listener.client.get_messages.await_count, self.settings.max_retries)
                self.assertEqual(saved["download_retries"], self.settings.max_retries)
                self.listener.client.download_media.assert_not_awaited()
                self.assertTrue(self.repo.source(self.admin, self.source["id"])["enabled"])

    async def test_listener_backoff_admission_recovers_gradually_and_keeps_manual_window(self):
        watched = []
        for mid in range(1100, 1104):
            await self.listener.receive(self.source, message(mid))
            p = self.repo.pending(self.admin)[0]
            task, _ = self.repo.submit(self.admin, p["id"], p["revision"])
            watched.append(task["id"])
        manual, _ = self.db.create_task(chat_id=self.admin, message_id=1200, sender_id=self.admin,
                                       file_name="manual.mp4", file_size=100)
        self.owner.destination_healthy = True
        self.owner._sample_fresh = lambda: True
        self.owner._destination_ready = lambda: True
        self.owner.snapshot = NS(filesystems=[], disk_free=100 * 1024**3, memory_available=4 * 1024**3)
        self.owner.download_window = NS(value=4)
        self.owner.upload_window = NS(value=4)
        release = asyncio.Event()
        async def hold(task_id):
            await release.wait()
        self.owner._download_one = hold
        try:
            with patch("tg2cloud.listening.transport.monotonic", return_value=0), patch(
                    "tg2cloud.transfer.scheduler.shutil.disk_usage", return_value=NS(free=100 * 1024**3)):
                self.listener.download_limited()
                await self.owner._start_downloads()
                await asyncio.sleep(0)
                self.assertIn(manual["id"], self.owner.download_tasks)
                self.assertEqual(len(set(watched) & self.owner.download_tasks.keys()), 2)
                self.assertEqual(self.owner.download_window.value, 4)
                for task_id in watched[2:]:
                    self.assertEqual(self.db.get(task_id)["state"], "queued")
                    self.assertIn("监听下载限速", self.db.get(task_id)["wait_reason"])
                running = dict(self.owner.download_tasks)
                await self.owner._start_downloads()
                self.assertEqual(self.owner.download_tasks, running)
                self.assertFalse(any(task.cancelled() for task in running.values()))
            with patch("tg2cloud.listening.transport.monotonic", return_value=60), patch(
                    "tg2cloud.transfer.scheduler.shutil.disk_usage", return_value=NS(free=100 * 1024**3)):
                await self.owner._start_downloads()
                self.assertEqual(len(set(watched) & self.owner.download_tasks.keys()), 3)
                self.assertEqual(self.owner.download_window.value, 4)
        finally:
            release.set()
            await asyncio.gather(*list(self.owner.download_tasks.values()))

    async def test_new_backoff_does_not_cancel_running_listeners_or_block_manual_task(self):
        self.owner.destination_healthy = True
        self.owner._sample_fresh = lambda: True
        self.owner._destination_ready = lambda: True
        self.owner.snapshot = NS(filesystems=[], disk_free=100 * 1024**3, memory_available=4 * 1024**3)
        self.owner.download_window = NS(value=4)
        self.owner.upload_window = NS(value=4)
        release = asyncio.Event()
        async def hold(task_id):
            await release.wait()
        self.owner._download_one = hold
        try:
            with patch("tg2cloud.transfer.scheduler.shutil.disk_usage", return_value=NS(free=100 * 1024**3)):
                for mid in range(1300, 1303):
                    await self.listener.receive(self.source, message(mid))
                    p = self.repo.pending(self.admin)[0]
                    self.repo.submit(self.admin, p["id"], p["revision"])
                await self.owner._start_downloads()
                await asyncio.sleep(0)
                running = dict(self.owner.download_tasks)
                self.listener.download_limited()
                await self.listener.receive(self.source, message(1303))
                p = self.repo.pending(self.admin)[0]
                deferred, _ = self.repo.submit(self.admin, p["id"], p["revision"])
                manual, _ = self.db.create_task(chat_id=self.admin, message_id=1400, sender_id=self.admin,
                                               file_name="manual.mp4", file_size=100)
                await self.owner._start_downloads()
                self.assertIn(manual["id"], self.owner.download_tasks)
                self.assertNotIn(deferred["id"], self.owner.download_tasks)
                self.assertFalse(any(task.cancelled() for task in running.values()))
                self.assertEqual(len(self.owner.download_tasks), 4)
        finally:
            release.set()
            await asyncio.gather(*list(self.owner.download_tasks.values()))


class AccountPermissionsTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "posix", "fcntl and UID permissions require Linux")
    def test_session_lock_permissions_and_independent_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "bot.session").write_bytes(b"existing-bot-session")
            settings = NS(data_dir=root)
            with account.session_lock(settings) as personal:
                self.assertEqual(personal.name, "personal")
                with self.assertRaises(BlockingIOError), account.session_lock(settings):
                    pass
                self.assertEqual(stat.S_IMODE(personal.parent.stat().st_mode), 0o700)
            self.assertEqual(
                (root / "bot.session").read_bytes(), b"existing-bot-session"
            )
            p = root / "listener/personal.session"
            p.write_bytes(b"synthetic")
            p.chmod(0o644)
            with self.assertRaises(ValueError), account.session_lock(settings):
                pass
            p.unlink()
            p.symlink_to(root / "bot.session")
            with self.assertRaises(ValueError), account.session_lock(settings):
                pass


if __name__ == "__main__":
    unittest.main()
